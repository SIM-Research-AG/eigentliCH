"""Adapter: the S-curve engine behind the standard interface, returning a Trajectory.

**Two routes, and which one runs depends on what the caller supplies.** Since 2026-08-02 (`DECISIONS.md` M55,
closing register item 20):

- Given `returns_by_state` and `state_weights`, it projects across the macro states and the band on the
  published Trajectory is a **weighted quantile over the Regime's own distribution**.
- Given neither, it falls back to the constant-return route with the `z*sigma*sqrt(t)` sketch, exactly as
  before.

The fallback is kept rather than removed because the constant route is still the right one for a caller that
genuinely has a single return and no distribution — the mandate's required return is a constant by definition,
and `validation/calibration.py` checks that recursion against a closed form. What is *not* kept is a hardcoded
volatility: the smoke test used to pass `annual_volatility=0.12`, which is where the retired sketch reached the
published contract from, and it now exercises the regime route instead.

**A caller that supplies a distribution and a volatility is refused rather than served.** Two bands drawn on
two different bases, silently preferring one, is how a reader ends up unable to tell which they are looking at.
"""

from __future__ import annotations

from typing import Any, Sequence

from contracts.analysis import Trajectory, TrajectoryPoint
from contracts.references import RegimeRef
from engines.base import EngineResult, NativeEngineAdapter, register
from engines.s_curve_trajectory.engine import STEPS_PER_YEAR, project, project_over_regime


class _RegimeCurveAsCurve:
    """Presents a `RegimeCurve` through the handful of attributes this adapter reads off a `Curve`.

    A small shim rather than a shared base class or a union type. The two results genuinely differ — one has
    `state_paths` and a `funded_probability`, the other an `annual_return` and nothing per state — and forcing
    them into one type would either widen `Curve` with fields that are meaningless on it or make every reader
    branch. Six attributes are all this method needs, so six attributes is what this exposes.
    """

    def __init__(self, regime_curve) -> None:
        self._c = regime_curve
        self.points = regime_curve.points
        self.on_track = regime_curve.on_track
        self.notes = regime_curve.notes
        self.total_contributed = regime_curve.total_contributed
        self.required_return = regime_curve.required_return
        self.final_value = regime_curve.mixture_final_value
        # The first time the *mixture* reaches the target, which is not any single state's funding date. Named
        # here rather than on the contract because it means something different from the constant route's.
        self.funded_at_years = next(
            (p.t_years for p in regime_curve.points if target_reached(p, regime_curve.target)), None
        )


def target_reached(point, target) -> bool:
    return target is not None and point.value >= target


class SCurveTrajectoryAdapter(NativeEngineAdapter):
    name = "s_curve_trajectory"
    produces = "Trajectory"
    model_version = "scurve@0.1.0"

    def run(
        self,
        household_id: str,
        initial_wealth: float,
        horizon_years: float,
        annual_return: float,
        target: float | None = None,
        annual_contribution: float = 0.0,
        contributions: Sequence[float] | None = None,
        annual_volatility: float | None = None,
        goal_kind: str = "fi",
        goal_ref: str | None = None,
        epsilon: float = 0.10,
        as_of: str = "2024-12-31",
        regime: RegimeRef | None = None,
        returns_by_state: Sequence[float] | None = None,
        state_weights: Sequence[float] | None = None,
        **_: Any,
    ) -> EngineResult:
        """Project one goal and return a Trajectory.

        Args:
            returns_by_state: One annual return per macro state, from the ReturnSet's per-state profiles over
                the universe being projected. With `state_weights`, switches the band to a weighted quantile
                across states.
            state_weights: The Regime's probability per state.

        Raises:
            ValueError: If only one of the pair is supplied, or if a volatility is supplied alongside them.
        """
        if (returns_by_state is None) != (state_weights is None):
            raise ValueError(
                "returns_by_state and state_weights must be supplied together. One without the other is a "
                "half-specified distribution, and defaulting the missing half would invent either a return "
                "profile or a regime."
            )
        regime_weighted = returns_by_state is not None

        if regime_weighted and annual_volatility is not None:
            raise ValueError(
                "a volatility was supplied alongside a per-state distribution. Those are two different bases "
                "for a band — a normal assumption over a supplied sigma, and a quantile over the Regime's own "
                "states — and drawing one while being handed the other would publish a band whose meaning "
                "nobody could determine from the contract. Pass one or the other."
            )

        funded_probability: float | None = None
        jensen_gap: float | None = None
        if regime_weighted:
            regime_curve = project_over_regime(
                initial_wealth=initial_wealth,
                target=target,
                horizon_years=horizon_years,
                returns_by_state=returns_by_state,
                state_weights=state_weights,
                annual_contribution=annual_contribution,
                contributions=contributions,
            )
            # A shim so the rest of this method reads the same either way. `project_over_regime` already
            # carries the constant-route figures it needs, computed from the weighted-average return.
            curve = _RegimeCurveAsCurve(regime_curve)
            funded_probability = regime_curve.funded_probability
            jensen_gap = regime_curve.mixture_final_value - regime_curve.deterministic_final_value
        else:
            curve = project(
                initial_wealth=initial_wealth,
                target=target,
                horizon_years=horizon_years,
                annual_return=annual_return,
                annual_contribution=annual_contribution,
                contributions=contributions,
                annual_volatility=annual_volatility,
            )

        # One point per year on the contract, not per month. A ten-year monthly path is 121 points, which makes
        # a contract that a human reads unwieldy for no gain: the S is legible annually. The engine still
        # computes monthly, so the compounding is right.
        annual_points = tuple(
            TrajectoryPoint(
                t_years=p.t_years, value=p.value, lower=p.lower, upper=p.upper
            )
            for p in curve.points
            if abs(p.t_years * STEPS_PER_YEAR % STEPS_PER_YEAR) < 1e-9
        )

        trajectory = Trajectory(
            as_of=as_of,
            model_version=self.model_version,
            household_id=household_id,
            goal_kind=goal_kind,
            goal_ref=goal_ref or f"{goal_kind}-{horizon_years:g}y",
            horizon_years=float(horizon_years),
            epsilon=epsilon,
            points=annual_points,
            target=target,
            on_track=curve.on_track,
            regime=regime,
        )

        notes = list(curve.notes)
        notes.append(
            f"contributed {curve.total_contributed:,.0f} over the horizon; the path ends at "
            f"{curve.final_value:,.0f}, so {curve.final_value - curve.total_contributed - initial_wealth:,.0f} "
            f"came from return rather than from saving."
        )
        if regime is None:
            notes.append(
                "no Regime is attached: the return is an input to this engine rather than something it reads "
                "from a Regime. Pass one to record which vintage the return assumption belongs to."
            )
        if regime_weighted:
            notes.append(
                f"the band on this Trajectory is a weighted quantile across {len(returns_by_state)} macro "
                f"states, not a z*sigma*sqrt(t) sketch. It carries regime uncertainty and not within-regime "
                f"volatility. DECISIONS.md M54, M55."
            )
        else:
            notes.append(
                "the band on this Trajectory, where it has one, is the z*sigma*sqrt(t) sketch: this call "
                "supplied a single return and no per-state distribution. Supply returns_by_state and "
                "state_weights for the quantile route. DECISIONS.md M54."
            )

        return self.result(
            contract=trajectory,
            call=self.native_call(),
            inputs={
                "initial_wealth": initial_wealth,
                "target": target,
                "horizon_years": horizon_years,
                "annual_return": annual_return,
                "annual_contribution": annual_contribution,
                "contributions": list(contributions) if contributions else None,
                "annual_volatility": annual_volatility,
                # The distribution goes into the inputs digest, so two Trajectories drawn on different bases
                # cannot share an idempotency key.
                "returns_by_state": list(returns_by_state) if returns_by_state is not None else None,
                "state_weights": list(state_weights) if state_weights is not None else None,
            },
            as_of=as_of,
            notes=notes,
            raw={
                "final_value": curve.final_value,
                "total_contributed": curve.total_contributed,
                "funded_at_years": curve.funded_at_years,
                "required_return": curve.required_return,
                "monthly_steps": len(curve.points) - 1,
                "band_basis": "regime_quantile" if regime_weighted else "sigma_sqrt_t",
                "funded_probability": funded_probability,
                "jensen_gap": jensen_gap,
            },
        )

    def smoke(self) -> EngineResult:
        """A household saving towards financial independence, ten years out.

        Runs the **regime-weighted** route on a small synthetic distribution. It used to pass
        `annual_volatility=0.12`, and that hardcoded sigma was where the retired sketch reached the published
        contract from — so the smoke test now exercises the route the system is supposed to use. Synthetic
        rather than the published contracts on purpose: a smoke test that needs a Regime on disk stops being a
        smoke test.
        """
        states = 25
        return self.run(
            household_id="smoke-household",
            initial_wealth=450_000,
            target=2_000_000,
            horizon_years=10.0,
            annual_return=0.05,
            annual_contribution=36_000,
            returns_by_state=[-0.20 + 0.0125 * s for s in range(states)],
            state_weights=[1.0] * states,
        )


register(SCurveTrajectoryAdapter())
