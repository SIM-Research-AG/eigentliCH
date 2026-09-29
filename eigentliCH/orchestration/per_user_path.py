"""The per-user path: everything downstream of the privacy boundary.

`FDT -> Life Balance Sheet (+Regime) -> Snapshot -> Optimiser (+ReturnSet) -> Recommendation`, with the side
branches `Snapshot -> Scenario`, `Snapshot -> Trajectory` and `FDT + Regime -> Score`.

**The chain is joined as of Phase 4, and the join is derived rather than authored.** The Optimiser reads a
*mandate*; the Life Balance Sheet now produces a `BalanceSheetSnapshot` carrying one, derived per
DESIGN_snapshot_to_mandate.md from the household's own required return. Phase 3 had refused this stage and graded
the break as a failing check rather than fabricate a Snapshot with an authored mandate, which would have joined
the chain visually while putting a free parameter where a derived quantity belongs. The check that reported the
break now asserts the opposite.

Where an input is genuinely absent the stage is still skipped and *said* to be skipped, never approximated.

**What it produces, all of it real:** a Score from the event stream, a goal Trajectory from the S-curve, a
household Trajectory from the Life Balance Sheet simulation, a Scenario from a client-proposed change, and, when
a mandate is available, a Recommendation. The Recommendation always arrives **unreleased**: nothing on this path
can take it across the wall.

**Phase 5 wrapped the whole path in one mediated context.** Every engine call below is attributed to the
Investment Agent, passes the control-plane pre-check and leaves a replayable trace — enforced at
`EngineAdapter.result()`, so a call that forgot to ask raises rather than proceeding quietly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import engines
from contracts.advice import Recommendation
from contracts.analysis import Scenario as ScenarioContract
from contracts.analysis import Score, Trajectory
from contracts.base import idempotency_key, trace_id_from
from contracts.fdt import EventStream, FDTEvent
from contracts.references import RegimeRef
from engines.score import NotEnoughHistory
from orchestration.agents import INVESTMENT, mediated
from orchestration.shared_path import Check, Severity, SharedPathResult, run_shared_path


class PerUserPathError(RuntimeError):
    """Raised when the per-user path cannot run at all, as distinct from running with a known break."""


@dataclass(frozen=True)
class PerUserPathResult:
    """One household through as much of the chain as exists."""

    household_id: str
    shared: SharedPathResult
    snapshot: Any | None
    score: Score | None
    goal_trajectory: Trajectory | None
    household_trajectory: Trajectory | None
    scenario: ScenarioContract | None
    recommendation: Recommendation | None
    #: The quantity the derived mandate needs, now that the S-curve computes it.
    required_return: float | None
    checks: tuple[Check, ...]
    idempotency_key: str
    trace_id: str
    notes: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def green(self) -> bool:
        return not self.blocking_failures()

    @property
    def joined(self) -> bool:
        """Whether the Snapshot to Optimiser link exists. False until the derived mandate is built."""
        return bool(
            self.recommendation
            and self.recommendation.snapshot_id
            and self.recommendation.snapshot_id != "not-from-a-snapshot"
        )

    def blocking_failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.severity is Severity.BLOCKING and not c.passed)

    def advisories(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.severity is Severity.ADVISORY and not c.passed)

    def summary(self) -> str:
        produced = [
            name
            for name, value in (
                ("Snapshot", self.snapshot),
                ("Score", self.score),
                ("Trajectory (goal)", self.goal_trajectory),
                ("Trajectory (household)", self.household_trajectory),
                ("Scenario", self.scenario),
                ("Recommendation", self.recommendation),
            )
            if value is not None
        ]
        lines = [
            f"per-user path for {self.household_id}: "
            f"{'GREEN' if self.green else 'NOT GREEN'}, chain "
            f"{'joined' if self.joined else 'NOT joined'}",
            f"  regime     {self.shared.regime.regime_id}",
            f"  returnset  {self.shared.returnset.return_set_id}",
            f"  produced   {', '.join(produced) if produced else 'nothing'}",
            f"  trace      {self.trace_id}",
            "",
        ]
        lines += [f"  {c.line()}" for c in self.checks]
        if self.notes:
            lines.append("")
            lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


@mediated(
    INVESTMENT,
    purpose=lambda a: f"per-user path for {a['household_id']}",
    household_id=lambda a: a["household_id"],
    # A derived or named mandate means a Recommendation can be produced, and a Recommendation is regulated
    # output: analysis until a Curator confirms it. Without one the path stops at the diagnostic stages.
    regulated=lambda a: a["mandate"] is not None or a["derive_mandate"],
)
def run_per_user_path(
    household_id: str,
    W_L: float,
    W_R: float,
    D: float,
    target: float,
    horizon_years: float,
    annual_contribution: float = 0.0,
    annual_return: float = 0.05,
    #: The household's age in years, forwarded to the Life Balance Sheet where it drives the age-earnings
    #: decline. Defaults to 40; the roster supplies the real one; roster.Client.age supplies the real one.
    age: float = 40.0,
    #: The residence / second-home split of `W_R`, as amounts. Forwarded to the engine, which credits rent to
    #: the LET remainder only (step 3, 3 August 2026).
    W_res: float | None = None,
    W_hol: float = 0.0,
    annual_volatility: float | None = None,
    events: EventStream | Sequence[FDTEvent] | None = None,
    months_observed: int = 12,
    scenario_field: str | None = None,
    scenario_to_value: Any = None,
    mandate: str | None = None,
    derive_mandate: bool = True,
    universe: Sequence[int] | None = None,
    currency: str = "CHF",
    scope: str = "Global",
    returnset_horizon_years: float = 1.0,
    epsilon: float = 0.10,
    as_of: str = "2024-12-31",
    E: float = 1.0,
    N: float = 1.0,
    H: float = 1.0,
) -> PerUserPathResult:
    """Run the per-user path for one household.

    Every stage is optional in the sense that its inputs may be absent, and an absent input means the stage is
    skipped and said to be skipped, never approximated. `mandate` is a mandate *name* rather than a Snapshot,
    which is the break this path reports.

    The `@mediated` decorator puts the whole body inside one context attributed to the Investment Agent, so every
    engine call below passes the pre-check and leaves a trace against this household — not because each call site
    remembered to ask, but because an engine call outside a context raises.

    Raises:
        PerUserPathError: When the shared path is not green. There is no point optimising against a Regime that
            failed its own checks.
    """
    shared = run_shared_path(scope, returnset_horizon_years, publish=False)
    if not shared.green:
        raise PerUserPathError(
            "the shared macro path is not green, so the per-user path will not run against it:\n  "
            + "\n  ".join(c.line() for c in shared.blocking_failures())
        )

    regime: RegimeRef = shared.regime
    checks: list[Check] = [
        Check(
            "shared path green",
            Severity.BLOCKING,
            True,
            f"regime {regime.regime_id}, returnset {shared.returnset.return_set_id}",
        )
    ]
    notes: list[str] = []

    # ---- the per-state distribution the Trajectory's band is drawn over -----
    #
    # Loaded here rather than only before the Optimiser (M55, closing register item 20). The Trajectory used to
    # carry a z*sigma*sqrt(t) band from a hardcoded volatility while the Schulung page taught a weighted
    # quantile over the Regime's own states; the page was right about the engine and wrong about the build.
    #
    # The per-state portfolio return is the EQUAL-WEIGHTED universe figure, the same neutral proxy the mandate
    # derivation uses to measure a goal buffer, and for the same reason: the Optimiser's chosen weights are not
    # known yet and using them here would be circular.
    from contracts.references import load_regime as _load_regime
    from contracts.references import load_returnset as _load_returnset

    returns_by_state: list[float] | None = None
    state_weights: list[float] | None = None
    try:
        _rs = _load_returnset(scope, returnset_horizon_years)
        _regime_payload = _load_regime(scope)
        _weights = [float(w) for w in _regime_payload["distributions"][-1]["weights"]]
        _blocks = _rs.get("building_blocks") or []
        if _blocks and _weights:
            returns_by_state = [
                sum(float(b["profile_by_state"][s]) for b in _blocks) / len(_blocks)
                for s in range(len(_weights))
            ]
            state_weights = _weights
    except (KeyError, IndexError, OSError, ValueError) as error:
        # A Trajectory without a band is honest; a Trajectory with a band drawn on an unstated basis is not.
        notes.append(
            f"the per-state distribution could not be formed ({error}), so the Trajectory carries no band "
            f"rather than falling back to a sketch whose basis the contract would not record."
        )

    # ---- FDT + Regime -> Score -----------------------------------------
    score: Score | None = None
    if events is not None:
        try:
            score = (
                engines.get("score_engine")
                .run(
                    household_id=household_id,
                    stream=events,
                    months_observed=months_observed,
                    regime=regime,
                    as_of=as_of,
                )
                .contract
            )
            checks.append(
                Check("Score", Severity.BLOCKING, True, f"{score.value:.1f} ({score.tier})")
            )
        except NotEnoughHistory as error:
            # Not a failure of the path: "not yet scored" is the correct answer for a thin stream.
            checks.append(
                Check("Score", Severity.ADVISORY, False, f"not yet scored: {error}")
            )
    else:
        checks.append(
            Check("Score", Severity.ADVISORY, False, "no event stream supplied, so no score")
        )

    # ---- Goal + contributions + return -> Trajectory --------------------
    goal_result = engines.get("s_curve_trajectory").run(
        household_id=household_id,
        initial_wealth=W_L,
        target=target,
        horizon_years=horizon_years,
        annual_return=annual_return,
        annual_contribution=annual_contribution,
        # Only one basis for the band reaches the engine. The adapter refuses both at once rather than
        # silently preferring one, so passing the volatility here as well would raise.
        annual_volatility=None if returns_by_state is not None else annual_volatility,
        returns_by_state=returns_by_state,
        state_weights=state_weights,
        epsilon=epsilon,
        as_of=as_of,
        regime=regime,
    )
    goal_trajectory = goal_result.contract
    required = goal_result.raw.get("required_return")
    checks.append(
        Check(
            "Trajectory (goal)",
            Severity.BLOCKING,
            True,
            f"{'on track' if goal_trajectory.on_track else 'not on track'}; required return "
            + ("unavailable" if required is None else f"{required:.2%}"),
        )
    )

    # ---- FDT -> Life Balance Sheet -> household Trajectory --------------
    household_trajectory: Trajectory | None = None
    lbs = engines.get("life_balance_sheet")
    if lbs.available():
        household_trajectory = lbs.run(
            household_id=household_id,
            W_L=W_L, W_R=W_R, D=D, E=E, N=N, H=H, age=age, W_res=W_res, W_hol=W_hol,
            horizon_years=horizon_years,
            target=target,
            epsilon=epsilon,
            as_of=as_of,
        ).contract
        checks.append(
            Check(
                "Trajectory (household)",
                Severity.BLOCKING,
                True,
                f"{len(household_trajectory.points)} points over {horizon_years:g}y",
            )
        )
    else:
        checks.append(
            Check(
                "Trajectory (household)",
                Severity.BLOCKING,
                False,
                "the Life Balance Sheet is not installed here",
            )
        )

    # ---- Snapshot -> Scenario ------------------------------------------
    scenario: ScenarioContract | None = None
    if scenario_field is not None:
        scenario = (
            engines.get("scenario_generator")
            .run(
                household_id=household_id,
                # The base snapshot does not exist yet, so the scenario records what it departed from by name.
                base_snapshot_id="not-from-a-snapshot",
                field=scenario_field,
                to_value=scenario_to_value,
                initial_wealth=W_L,
                target=target,
                horizon_years=horizon_years,
                annual_return=annual_return,
                annual_contribution=annual_contribution,
                annual_volatility=annual_volatility,
                change_origin="client",
                as_of=as_of,
                regime=regime,
            )
            .contract
        )
        checks.append(
            Check(
                "Scenario",
                Severity.BLOCKING,
                scenario.change_origin == "client",
                f"client-originated change to {scenario_field}",
            )
        )

    # ---- FDT -> Life Balance Sheet -> Snapshot ---------------------------
    #
    # The derived mandate: the target curve is the annual return this household's goal requires, and the
    # position caps come from its buffer against each block's published crisis loss. Derived in the Life
    # Balance Sheet, per M4, and materialised into the Optimiser's own mandate format below so the Optimiser
    # needs no change.
    snapshot = None
    derived_mandate_path: str | None = None
    #: The Recommendation the fixed point already solved, when it ran. `None` on a path that was given a mandate
    #: *name* instead of a derived Snapshot: there is no iteration to run there, because an authored mandate has
    #: no household buffer to feed back into.
    recommendation_from_loop: Recommendation | None = None
    if derive_mandate and lbs.available():
        from contracts.references import load_returnset
        from engines.lbs.derive import DerivationInputs

        derivation = DerivationInputs(
            household_id=household_id,
            W_L=W_L, W_R=W_R, D=D, E=E, N=N, H=H,
            goal_kind="fi",
            target=target,
            horizon_years=horizon_years,
            epsilon=epsilon,
            annual_contribution=annual_contribution,
            currency=currency,
            as_of=as_of,
        )
        returnset_payload = load_returnset(scope, returnset_horizon_years)

        # The mandate and the allocation are solved together, not in sequence (DECISIONS.md M63).
        fixed_point = _iterate_to_fixed_point(
            lbs=lbs,
            optimiser=engines.get("portfolio_optimiser"),
            derivation=derivation,
            regime=regime,
            returnset_payload=returnset_payload,
            universe=universe,
            household_id=household_id,
            scope=scope,
            shared_returnset=shared.returnset,
            mandate_dir=engines.get("portfolio_optimiser").home / "mandates",
        )
        snapshot = fixed_point.snapshot
        recommendation_from_loop = fixed_point.recommendation
        notes.extend(fixed_point.notes)

        # One return through the whole chain, by decision of 3 August 2026. The Trajectory and the Scenario
        # previously projected at the caller's `annual_return` (default 5%) while the mandate that produced the
        # allocation was derived at a different figure, and nothing said so. The converged return replaces it,
        # so a client's projected wealth path and their allocation now rest on one number.
        #
        # **The goal Trajectory is recomputed rather than reordered, deliberately.** The fixed point cannot run
        # before the Trajectory without moving the Optimiser ahead of it, and the Trajectory's own output is not
        # an input to the iteration — only the goal and the position are. Recomputing costs one closed-form
        # projection and leaves the sequence of stages above readable; reordering would have moved four stages
        # to save it. The first projection is the seed-based one and is discarded, which is why two Trajectory
        # traces appear per household on a joined run.
        seeded_return = annual_return
        annual_return = fixed_point.mu
        goal_result = engines.get("s_curve_trajectory").run(
            household_id=household_id,
            initial_wealth=W_L,
            target=target,
            horizon_years=horizon_years,
            annual_return=annual_return,
            annual_contribution=annual_contribution,
            annual_volatility=None if returns_by_state is not None else annual_volatility,
            returns_by_state=returns_by_state,
            state_weights=state_weights,
            epsilon=epsilon,
            as_of=as_of,
            regime=regime,
        )
        goal_trajectory = goal_result.contract
        # `required_return` is a property of the goal and the position, so it must not have moved. Checked
        # rather than assumed: if it ever does, the recomputation is doing more than restating the basis.
        recomputed_required = goal_result.raw.get("required_return")
        if required is not None and recomputed_required is not None:
            if abs(float(recomputed_required) - float(required)) > 1e-9:
                raise PerUserPathError(
                    f"the required return moved from {required} to {recomputed_required} when the Trajectory "
                    f"was recomputed on the converged return. It is a function of the goal and the position "
                    f"alone, so this means the recomputation changed something it should not have."
                )
        required = recomputed_required
        notes.append(
            f"the Trajectory is projected at {annual_return:.4%}, the converged return, rather than at the "
            f"{seeded_return:.4%} supplied by the caller. One return now runs through the mandate, the "
            f"allocation and the projected path; before 3 August 2026 the path and the allocation used "
            f"different figures and nothing said so. DECISIONS.md M63."
        )

        if fixed_point.verdict == "fixed_point":
            settled_detail = (
                f"exact fixed point at {fixed_point.mu:.4%} in {fixed_point.passes} pass(es) from a seed of "
                f"{fixed_point.sequence[0]:.4%}; the allocation repeated, so the return is forced to repeat"
            )
        elif fixed_point.verdict == "cycle":
            settled_detail = (
                f"the allocation CYCLES over {len(fixed_point.cycle)} allocation(s): "
                f"{', '.join(f'{m:.4%}' for _, m in fixed_point.cycle)}. No fixed point on this path. The most "
                f"conservative member is published, at {fixed_point.mu:.4%}, so the buffer cannot be overstated "
                f"by where the loop stopped."
            )
        elif fixed_point.verdict == "no_optimiser":
            settled_detail = "the Optimiser is unavailable, so nothing was iterated; the proxy stands"
        else:
            settled_detail = (
                f"neither settled nor closed a cycle in {FIXED_POINT_MAX_PASSES} passes; last pass "
                f"{fixed_point.mu:.4%}. Genuinely unknown rather than known-bad."
            )
        checks.append(
            Check(
                "return assumption settled",
                Severity.ADVISORY,
                fixed_point.converged,
                settled_detail,
            )
        )
        checks.append(
            Check(
                "Snapshot derived",
                Severity.BLOCKING,
                True,
                f"{snapshot.snapshot_id()}, required return "
                f"{snapshot.mandate.curve.required_return:.4%}, bound sources "
                f"{snapshot.mandate.sources_in_use()}",
            )
        )
        # Whether the goal is reachable is a fact about the household, not a defect in the path, so it is
        # advisory. It is surfaced as a check rather than left in the notes because it is the single most
        # important thing a reader of this result needs to know.
        checks.append(
            Check(
                "goal is reachable",
                Severity.ADVISORY,
                bool(snapshot.goal.feasible),
                (
                    f"buffer {snapshot.goal.buffer:,.0f} at the universe's expected return"
                    if snapshot.goal.feasible
                    else f"the goal needs {snapshot.mandate.curve.required_return:.2%} a year but the universe "
                    f"offers far less, leaving a buffer of {snapshot.goal.buffer:,.0f}. The mandate is still "
                    f"derived and usable, and the Optimiser will report persistent shortfall, which is the "
                    f"honest signal that this goal does not work from this position."
                ),
            )
        )

        # The mandate file was already written by each pass of the iteration — writing it is how the Optimiser
        # is handed a mandate at all, so it cannot be deferred to after the loop. What is left here is only the
        # name and the path, for the result and the notes.
        stem = f"derived_{household_id}".replace(" ", "_").replace("/", "_")
        derived_mandate_path = str(
            engines.get("portfolio_optimiser").home / "mandates" / f"{stem}.yaml"
        )
        mandate = stem

    # ---- Snapshot -> Optimiser -> Recommendation -------------------------
    recommendation: Recommendation | None = None
    optimiser = engines.get("portfolio_optimiser")
    if recommendation_from_loop is not None:
        # Already solved, inside the fixed point. Re-running here would spend another PCP subprocess to
        # reproduce a result the loop's final pass has already produced against this exact mandate — and if it
        # ever produced a *different* one, the fixed point would be a fiction.
        recommendation = recommendation_from_loop
    elif mandate is not None and optimiser.available():
        # An authored mandate, named rather than derived. No iteration: a fixed point needs a household buffer
        # to feed the measured return back into, and an authored mandate has none. Single pass, notes carried.
        optimiser_result = optimiser.run(
            mandate=mandate,
            market=scope,
            household_id=household_id,
            snapshot_id=snapshot.snapshot_id() if snapshot is not None else None,
        )
        recommendation = optimiser_result.contract
        notes.extend(f"Optimiser: {n}" for n in optimiser_result.notes)
        notes.append(
            "the mandate was named rather than derived, so the return assumption was not iterated to a fixed "
            "point. The allocation is solved once against a mandate nothing here produced. DECISIONS.md M63."
        )

    if recommendation is not None:
        checks.append(
            Check(
                "Recommendation regime agreement",
                Severity.BLOCKING,
                recommendation.regime.regime_id == regime.regime_id,
                f"stamped {recommendation.regime.regime_id}",
            )
        )
        checks.append(
            Check(
                "Recommendation arrives unreleased",
                Severity.BLOCKING,
                not recommendation.released,
                "analysis until a Curator confirms it; nothing on this path can release it",
            )
        )

    # ---- the known breaks, graded so they are visible on every run -------
    checks.append(_snapshot_link(recommendation))
    checks.append(_regime_reaches_the_household(household_trajectory))
    checks.append(_derived_mandate_input(required))

    if snapshot is None:
        notes.append(
            "the Optimiser was given a mandate name rather than a derived Snapshot, so the per-user chain is "
            "not joined on this run. Pass derive_mandate=True with the Life Balance Sheet installed to join it."
        )
    else:
        notes.append(
            f"the mandate was derived from the household's own position and goal, then materialised at "
            f"{derived_mandate_path} in the Optimiser's own format. That file is transport: the derivation "
            f"happened in the Life Balance Sheet, per DECISIONS.md M4."
        )
    if recommendation is not None:
        notes.append(
            "the Recommendation is regulated and unreleased. It reaches a client only after the control-plane "
            "pre-check and a Curator confirmation, which writes a Decision Record."
        )

    key = idempotency_key(
        {
            "household_id": household_id,
            "position": {"W_L": W_L, "W_R": W_R, "D": D},
            "goal": {"target": target, "horizon_years": horizon_years, "epsilon": epsilon},
            "annual_return": annual_return,
            "annual_contribution": annual_contribution,
            "mandate": mandate,
            "scenario": {"field": scenario_field, "to_value": scenario_to_value},
            "shared": shared.idempotency_key,
        },
        "peruser@0.1.0",
    )

    return PerUserPathResult(
        household_id=household_id,
        shared=shared,
        snapshot=snapshot,
        score=score,
        goal_trajectory=goal_trajectory,
        household_trajectory=household_trajectory,
        scenario=scenario,
        recommendation=recommendation,
        required_return=required,
        checks=tuple(checks),
        idempotency_key=key,
        trace_id=trace_id_from(key),
        notes=tuple(dict.fromkeys(notes)),
        raw={"shared_trace": shared.trace_id, "goal_trace": goal_result.trace_id},
    )


#: How close two successive return estimates must be before the iteration is called settled. 1e-6 on a decimal
#: return is a hundredth of a basis point — far below any figure this system reports, so convergence at this
#: tolerance cannot move a published number.
FIXED_POINT_TOLERANCE: float = 1e-6

#: The most passes attempted before giving up. Twenty is generous: the map contracts quickly in practice and a
#: run that has not settled in twenty passes is oscillating rather than converging slowly. Stated as a constant
#: because a silent loop bound is indistinguishable from a hang.
FIXED_POINT_MAX_PASSES: int = 20

#: How much of each measured correction is fed back: `x <- x + lambda(f(x) - x)`.
#:
#: **Added 3 August 2026 by CIO decision (DECISIONS.md M65), and it changes what "the fixed point" means, which
#: is why it is a stated choice and not a quiet numerical convenience.** It does not move the fixed point itself
#: — any `x` with `f(x) = x` satisfies the damped update for every lambda — but it changes which fixed points are
#: *reachable*, and it changes what a non-convergence flag means from "no fixed point found" to "none found even
#: damped".
#:
#: **Set to 1.0 — damping disabled — after building it at 0.5 and measuring that it is harmful here.** The
#: mechanism is kept, with its measurement, because the negative result is worth more than the code:
#:
#:     household   undamped              damped 0.5
#:     hh-0011     converged, 2 passes   converged, 16 passes
#:     hh-0012     not settled, 2.62%    not settled, 2.87%
#:     hh-0013     converged, 3 passes   NOT SETTLED, 3.20%
#:     hh-0014     converged, 2 passes   converged, 16 passes
#:     hh-0015     converged, 2 passes   converged, 16 passes
#:
#: It failed to fix `hh-0012`, **broke `hh-0013`**, and turned two-pass convergence into sixteen. That 16 is the
#: diagnosis: `log2(0.026 / 1e-6)` is about 15, so the residual was merely halving each pass, which is what
#: happens when `f` is *locally constant*. And it is: the allocation depends on the assumed return only through
#: which bounds bind, so `f` is **piecewise constant with jumps**, not a smooth map that overshoots. Damping is
#: the remedy for overshoot. Against a piecewise-constant map it takes smaller steps through the same cells,
#: visiting more of them, which is how it broke a household that had been converging.
#:
#: The real mechanism is structural, and measured: **the two households that fail to settle are exactly the two
#: funded ones.** For a funded household the chain closes — return -> goal buffer -> derived per-instrument caps
#: -> allocation -> return. For an unfunded one the buffer is negative, the caps fall back to policy, the loop is
#: broken, and `f` is constant. No choice of lambda addresses that; see M65 for what would.
FIXED_POINT_DAMPING: float = 1.0


#: Weights closer than this are the same allocation. 1e-6 is a ten-thousandth of a percentage point; two
#: allocations differing by less than that are identical for every purpose this system has, and the optimiser
#: returns exact zeros as values like 2.4e-16 which must not read as distinct.
ALLOCATION_EQUALITY_DECIMALS: int = 6


def _allocation_key(holdings: Sequence[Any]) -> tuple[tuple[int, float], ...]:
    """A canonical, comparable identity for an allocation.

    Sorted by block id and rounded, so the same portfolio always produces the same key regardless of holding
    order or floating-point dust.
    """
    return tuple(
        sorted(
            (int(getattr(h, "bb_id")), round(float(getattr(h, "weight")), ALLOCATION_EQUALITY_DECIMALS))
            for h in holdings
        )
    )


@dataclass(frozen=True)
class FixedPoint:
    """The outcome of the LBS/Optimiser iteration.

    `sequence` is every return estimate in order, starting with the seed, so a reader can see whether it
    contracted, oscillated, or walked. It is carried into the trace rather than summarised because the shape of
    the sequence is the evidence for the verdict.

    `verdict` distinguishes the three real outcomes, which a bare boolean conflated:

    - `fixed_point` — the allocation repeated the previous pass's. **This is exact, not a tolerance.** The
      measured return is a function of the allocation alone, so an allocation that repeats forces the return to
      repeat, which makes the iterate a true fixed point rather than one within 1e-6 of something.
    - `cycle` — the allocation repeated an *earlier* pass's. The map is orbiting a set of allocations and no
      fixed point exists on this path. Reported with the cycle's length and members.
    - `exhausted` — neither happened inside the pass budget. Genuinely unknown rather than known-bad.
    """

    snapshot: Any
    recommendation: Recommendation | None
    mu: float
    sequence: tuple[float, ...]
    verdict: str
    notes: tuple[str, ...]
    #: Members of the detected cycle as (pass index, measured return), when `verdict` is `cycle`.
    cycle: tuple[tuple[int, float], ...] = ()

    @property
    def converged(self) -> bool:
        """True only for a real fixed point. A cycle is not convergence, however tidily it repeats."""
        return self.verdict == "fixed_point"

    @property
    def passes(self) -> int:
        """One entry per pass: `sequence` holds the iterate fed to each derivation."""
        return len(self.sequence)


def _iterate_to_fixed_point(
    *,
    lbs: Any,
    optimiser: Any,
    derivation: Any,
    regime: Any,
    returnset_payload: Mapping[str, Any],
    universe: Sequence[int] | None,
    household_id: str,
    scope: str,
    shared_returnset: Any,
    mandate_dir: Path,
) -> FixedPoint:
    """Iterate the Life Balance Sheet and the Optimiser to a common return assumption.

    **The circle this closes.** The mandate's level is derived from what the household's goal requires against
    what the portfolio is expected to earn. The portfolio's expected return depends on the allocation. The
    allocation depends on the mandate. Every earlier version cut that circle with a proxy and lived with the
    inconsistency: the buffer was measured on a return no real allocation delivered.

    The iteration resolves it instead of cutting it. Pass 0 derives a mandate on the M59 role-bounded proxy — a
    deliberate upper bound — and optimises against it. Each later pass re-derives on the *measured* return of the
    previous pass's allocation. At a fixed point the mandate and the allocation agree about what the portfolio
    earns, which is the only state in which either number means what it says.

    **On non-convergence the last iterate is published, flagged.** Decided by the CIO on 3 August 2026, in
    preference to refusing. The reasoning to keep in view: an oscillating iteration means the mandate and the
    allocation disagree, so the published pair is internally inconsistent and the flag is the only thing telling
    a reader so. The note carries the amplitude, because an oscillation of a basis point and one of two
    percentage points are different facts.
    """
    from engines.lbs.derive import (
        allocation_expected_return,
        proxy_expected_return,
        render_mandate_yaml,
    )

    stem = f"derived_{household_id}".replace(" ", "_").replace("/", "_")
    mandate_dir.mkdir(parents=True, exist_ok=True)
    target_path = mandate_dir / f"{stem}.yaml"

    notes: list[str] = []
    #: The iterates actually fed to the derivation, `x_n`. The first is the proxy seed.
    sequence: list[float] = []
    #: What each iterate's allocation turned out to earn, `f(x_n)`. Same length as `sequence`.
    measured_at: list[float] = []
    mu: float | None = None
    snapshot = None
    recommendation: Recommendation | None = None
    verdict = "exhausted"
    residual = 0.0
    #: One canonical allocation key per pass, for the fixed-point and cycle tests.
    keys: list[tuple[tuple[int, float], ...]] = []
    #: `(snapshot, recommendation, measured)` per pass, so a cycle can publish a member other than the last.
    snapshots: list[tuple[Any, Recommendation, float]] = []
    cycle_from = 0

    for _pass in range(FIXED_POINT_MAX_PASSES):
        snapshot_result = lbs.snapshot(
            inputs=replace(derivation, expected_return_override=mu),
            regime=regime,
            returnset_payload=returnset_payload,
            universe=universe,
        )
        snapshot = snapshot_result.contract
        snapshot.require_returnset(shared_returnset)
        if mu is None:
            # Pass 0's own notes are the ones a reader needs: later passes repeat them with a moved number.
            notes.extend(snapshot_result.notes)
            mu = float(proxy_expected_return(returnset_payload, universe))
        sequence.append(mu)

        target_path.write_text(
            render_mandate_yaml(snapshot, returnset_payload, market=scope), encoding="utf-8"
        )
        if not optimiser.available():
            notes.append(
                "the Optimiser is unavailable, so the return assumption could not be iterated and the mandate "
                "rests on the role-bounded proxy. That proxy is an upper bound, not a forecast."
            )
            return FixedPoint(
                snapshot, None, sequence[-1], tuple(sequence), "no_optimiser", tuple(notes)
            )

        result = optimiser.run(
            mandate=stem, market=scope, household_id=household_id,
            snapshot_id=snapshot.snapshot_id(),
        )
        recommendation = result.contract
        if _pass == 0:
            notes.extend(f"Optimiser: {n}" for n in result.notes)

        measured = allocation_expected_return(recommendation.holdings, returnset_payload)
        measured_at.append(measured)

        # **The allocation is what this map really iterates, so it is what convergence is tested on.**
        # Added 3 August 2026 (DECISIONS.md M66), replacing a tolerance on the return as the primary test.
        #
        # The measured return is a function of the allocation alone. So if this pass's allocation equals the
        # previous pass's, the return it produces must equal the previous pass's too, which means the iterate
        # already *is* a fixed point — exactly, not to within 1e-6. And if the allocation equals any earlier
        # pass's, the map is orbiting a finite set of allocations and no fixed point lies on this path; that is a
        # cycle, and it is a different fact from "not settled yet" even though a return tolerance reports both
        # the same way.
        #
        # This is the right test because `f` is piecewise constant: the allocation changes only when the set of
        # binding bounds changes (M65). A tolerance on a continuous quantity cannot see the structure of a map
        # whose range is discrete, which is why the return test needed 16 passes to creep up on answers the
        # allocation test settles in two, and why it could not tell a 2-cycle from slow progress.
        key = _allocation_key(recommendation.holdings)
        keys.append(key)
        snapshots.append((snapshot, recommendation, measured))
        residual = measured - mu
        if len(keys) >= 2 and key == keys[-2]:
            verdict = "fixed_point"
            break
        earlier = keys.index(key)
        if earlier < len(keys) - 1:
            verdict = "cycle"
            cycle_from = earlier
            break

        # A secondary test, kept because it costs nothing: two *different* allocations can in principle produce
        # the same return, and if they do the iterate is stationary even though the key changed.
        if abs(residual) < FIXED_POINT_TOLERANCE:
            verdict = "fixed_point"
            break

        # Damped update, added 3 August 2026 (DECISIONS.md M65) after the undamped iteration failed to settle on
        # `hh-0012` — a 2-cycle of 2.6172% amplitude, not a slow drift. Feeding back the measured return whole is
        # `x <- f(x)`, which converges only where `|f'| < 1`; for a *funded* household the chain is
        # return -> buffer -> derived caps -> allocation -> return, and that composition overshoots. Feeding back
        # a partial step contracts the overshoot in the standard way.
        mu = mu + FIXED_POINT_DAMPING * residual

    span = max(measured_at) - min(measured_at) if measured_at else 0.0
    cycle: tuple[tuple[int, float], ...] = ()

    if verdict == "fixed_point":
        notes.append(
            f"the Life Balance Sheet and the Optimiser reached a common return assumption in {len(sequence)} "
            f"pass(es), at {measured_at[-1]:.4%} from a seed of {sequence[0]:.4%}. The allocation repeated the "
            f"previous pass's exactly, and because the measured return is a function of the allocation alone, "
            f"that makes this an exact fixed point rather than one within a tolerance: the mandate's level and "
            f"the allocation now mean the same thing. Before this iteration existed, the buffer was measured on "
            f"a return no real allocation delivered. DECISIONS.md M63, M66."
        )
    elif verdict == "cycle":
        members = list(range(cycle_from, len(keys) - 1))
        cycle = tuple((i, measured_at[i]) for i in members)
        # **Publish the most conservative member, not whichever pass happened to be last.**
        # Lowest measured return, because that yields the smallest goal buffer of the orbit: an orbiting
        # iteration cannot say what the portfolio earns, and of the answers it offers, the one that will not
        # overstate a household's funding is the only defensible choice. M65 recorded the alternative's cost —
        # `hh-0012`'s published buffer moved by 419,000 depending purely on where the loop stopped.
        chosen = min(members, key=lambda i: measured_at[i])
        snapshot, recommendation, chosen_measured = snapshots[chosen]
        target_path.write_text(
            render_mandate_yaml(snapshot, returnset_payload, market=scope), encoding="utf-8"
        )
        notes.append(
            f"the allocation cycles: pass {len(keys) - 1} reproduced the allocation of pass {cycle_from}, so the "
            f"iteration is orbiting {len(members)} allocation(s) and no fixed point lies on this path. Returns "
            f"around the orbit: {', '.join(f'{m:.4%}' for _, m in cycle)}. **This is a stronger and cleaner "
            f"statement than the old 'did not settle in 20 passes'**, which could not tell an orbit from slow "
            f"progress. Published is the most conservative member, pass {chosen} at {chosen_measured:.4%}, "
            f"chosen as the lowest return of the orbit so the goal buffer cannot be overstated by where the "
            f"loop happened to stop. The mandate file was rewritten to match that pass. A cycle means the "
            f"mandate and the allocation disagree about what this portfolio earns, and the disagreement is "
            f"structural rather than numerical: this household is funded, so its caps are derived from its "
            f"buffer, which depends on the return, which depends on the caps. DECISIONS.md M65, M66."
        )
    else:
        notes.append(
            f"the iteration neither settled nor closed a cycle within {FIXED_POINT_MAX_PASSES} passes: the "
            f"allocation was still new on the last pass. The mandate was derived at {sequence[-1]:.4%} while its "
            f"allocation earns {measured_at[-1]:.4%}, a disagreement of {abs(residual):.4%}, and the measured "
            f"return moved across {span:.4%}. This is genuinely unknown rather than known-bad — with {len(keys)} "
            f"distinct allocations seen and none repeated, the orbit may simply be longer than the budget. The "
            f"last pass is published, flagged. DECISIONS.md M63, M66."
        )

    # `mu` is what the published allocation actually earns, not the iterate fed in. At a fixed point they are the
    # same number; on a cycle or an exhausted run the distinction is the whole point, and the honest answer to
    # "what does this portfolio return" is the measured one.
    published_measured = (
        snapshots[min(range(cycle_from, len(keys) - 1), key=lambda i: measured_at[i])][2]
        if verdict == "cycle"
        else (measured_at[-1] if measured_at else sequence[-1])
    )
    return FixedPoint(
        snapshot,
        recommendation,
        float(published_measured),
        tuple(sequence),
        verdict,
        tuple(notes),
        cycle,
    )


def _snapshot_link(recommendation: Recommendation | None) -> Check:
    """The chain's break. Advisory, because every stage that exists ran correctly."""
    if recommendation is None:
        return Check(
            "Snapshot to Optimiser joined",
            Severity.ADVISORY,
            False,
            "no Recommendation was produced, so the link was not exercised",
        )
    if recommendation.snapshot_id == "not-from-a-snapshot":
        return Check(
            "Snapshot to Optimiser joined",
            Severity.ADVISORY,
            False,
            "the Optimiser read a mandate rather than a BalanceSheetSnapshot. The derived mandate of "
            "DECISIONS.md M4 is not built, so the per-user chain is not joined.",
        )
    return Check(
        "Snapshot to Optimiser joined",
        Severity.ADVISORY,
        True,
        f"optimised against snapshot {recommendation.snapshot_id}",
    )


def _regime_reaches_the_household(trajectory: Trajectory | None) -> Check:
    """The manual's `Regime -> Life Balance Sheet` edge, which does not exist yet (M5)."""
    if trajectory is None:
        return Check(
            "Regime reaches the household model",
            Severity.ADVISORY,
            False,
            "no household trajectory was produced",
        )
    if trajectory.regime is None:
        return Check(
            "Regime reaches the household model",
            Severity.ADVISORY,
            False,
            "the Life Balance Sheet does not read the Regime: its seam is a documented no-op, so the household "
            "path is regime-invariant. See DECISIONS.md M5.",
        )
    return Check(
        "Regime reaches the household model",
        Severity.ADVISORY,
        True,
        f"conditioned on {trajectory.regime.regime_id}",
    )


def _derived_mandate_input(required: float | None) -> Check:
    """Whether the quantity the derived mandate needs is now computable.

    Kept as a check after the derivation was wired, because it is the *input* the derivation rests on. If the
    S-curve ever stops producing a required return, the mandate silently loses its target curve, and this check
    is what would say so before the mandate's own checks reported something more confusing downstream.
    """
    if required is None:
        return Check(
            "derived mandate input available",
            Severity.ADVISORY,
            False,
            "no required return could be computed for this goal, so a derived mandate has no target curve to "
            "rest on",
        )
    return Check(
        "derived mandate input available",
        Severity.ADVISORY,
        True,
        f"the goal requires {required:.2%} a year, which is the target curve the derived mandate of "
        f"DECISIONS.md M4 rests on.",
    )
