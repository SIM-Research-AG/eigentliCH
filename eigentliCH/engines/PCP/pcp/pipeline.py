"""Orchestration: ingest, check, optimise, assemble the result.

One code path. The CLI and the cockpit both call `run`, so a result seen in the cockpit is the result the
CLI would write, and there is no second implementation to drift.

Order of operations matters, and it is: read every input, then run every check, then solve. The checks
(regime_id agreement, units, classifiability, structural feasibility) all run before the first solve, so a
run that cannot produce a meaningful answer fails before spending time on an optimisation whose result
would have to be thrown away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from pcp import ENGINE_VERSION
from pcp.config import Config
from pcp.contracts import (
    Allocation,
    BuildingBlock,
    ContractError,
    Mandate,
    RegimeTimeline,
    Result,
    ReturnSet,
    idempotency_key,
    require_classifiable,
    require_regime_match,
    require_units,
    trace_id_from,
)
from pcp.ingest import load_mandate, load_regime_for_market, load_returnset
from pcp.ingest.regime import RegimeBlend
from pcp.model.constraints import (
    ConstraintSystem,
    binding_constraints,
    build_constraints,
    realised_exposures,
)
from pcp.model.objective import achieved_curve, shortfall_by_state
from pcp.model.optimiser_curve import solve_curve
from pcp.model.pfmap import portfolio_map, role_allocation, scenario_allocation


class PipelineError(RuntimeError):
    """Raised when a run cannot proceed. Carries a reason a reader can act on."""


@dataclass(frozen=True, slots=True)
class RunInputs:
    """Everything a run consumes, after reading and checking."""

    mandate: Mandate
    returnset: ReturnSet
    regime: RegimeTimeline
    blocks: tuple[BuildingBlock, ...]
    bb: np.ndarray
    system: ConstraintSystem
    feasibility_notes: tuple[str, ...]
    #: The blend the Regime producer recorded, read from the published timeline's provenance. Empty for a
    #: single-economy timeline, which carries no blend.
    economy_weights: dict[str, float] = field(default_factory=dict)
    slot_weights: dict[str, float] = field(default_factory=dict)
    contributors: dict[str, Any] = field(default_factory=dict)
    regime_notes: tuple[str, ...] = ()


def prepare(
    mandate_name: str,
    config: Config,
    market: str | None = None,
    regime_dir: Path | str | None = None,
    returnset_path: Path | str | None = None,
    mandates_dir: Path | str | None = None,
) -> RunInputs:
    """Read every input and run every check that does not need a solution.

    Raises:
        PipelineError: On any unusable input, with the reason.
    """
    try:
        mandate = load_mandate(mandate_name, directory=mandates_dir, config=config)
    except Exception as error:  # ingest raises typed errors; the CLI wants one class
        raise PipelineError(str(error)) from error

    scope = market or mandate.market

    try:
        regime, _ = load_regime_for_market(scope, config, directory=regime_dir)
    except Exception as error:
        raise PipelineError(str(error)) from error

    # The blend is the producer's, read from the timeline it published rather than recomputed. See
    # `load_regime_for_market` for why recomputing it here would break the regime_id check.
    provenance = regime.provenance or {}
    economy_weights = {str(k): float(v) for k, v in (provenance.get("economy_weights") or {}).items()}
    slot_weights = {str(k): float(v) for k, v in (provenance.get("slot_weights") or {}).items()}
    contributors = dict(provenance.get("contributors") or {})

    source = returnset_path if returnset_path is not None else _default_returnset(config)
    try:
        returnset = load_returnset(source, config)
    except Exception as error:
        raise PipelineError(str(error)) from error

    # The binding checks, before any solve.
    if bool(config.get("contracts.strict_regime_id")):
        try:
            require_regime_match(returnset, regime)
        except ContractError as error:
            raise PipelineError(str(error)) from error
    try:
        require_units(returnset, mandate, config)
    except ContractError as error:
        raise PipelineError(str(error)) from error

    try:
        blocks = returnset.subset(mandate.universe)
    except Exception as error:
        raise PipelineError(str(error)) from error

    try:
        require_classifiable(blocks, config)
    except ContractError as error:
        raise PipelineError(str(error)) from error

    bb = ReturnSet.bb_matrix(blocks)

    try:
        system = build_constraints(mandate, blocks, config)
    except ValueError as error:
        raise PipelineError(str(error)) from error

    return RunInputs(
        mandate=mandate,
        returnset=returnset,
        regime=regime,
        blocks=blocks,
        bb=bb,
        system=system,
        feasibility_notes=tuple(system.feasibility_notes()),
        economy_weights=economy_weights,
        slot_weights=slot_weights,
        contributors=contributors,
        regime_notes=tuple(str(n) for n in (regime.provenance.get("notes") or [])),
    )


def run(
    mandate_name: str,
    config: Config,
    market: str | None = None,
    speed: str | None = None,
    optimiser: str = "curve",
    backtest_months: int = 0,
    regime_dir: Path | str | None = None,
    returnset_path: Path | str | None = None,
    mandates_dir: Path | str | None = None,
    inputs: RunInputs | None = None,
) -> Result:
    """Optimise a mandate, live or over a backtest window.

    Args:
        mandate_name: File stem, mandate name, or `client/mandate`.
        config: Loaded configuration.
        market: Override the mandate's market scope.
        speed: "fast" or "exact". Defaults to the configured run speed.
        optimiser: "curve" for the model of record, "mv" for the labelled comparison.
        backtest_months: How many trailing periods to re-optimise. Zero solves the current period only.
        inputs: Pre-prepared inputs, so the cockpit can prepare once and solve repeatedly.

    Returns:
        The result, stamped with every version and identifier that produced it.
    """
    prepared = inputs or prepare(
        mandate_name,
        config,
        market=market,
        regime_dir=regime_dir,
        returnset_path=returnset_path,
        mandates_dir=mandates_dir,
    )
    resolved_speed = speed or str(config.get("run.speed"))
    notes: list[str] = list(prepared.feasibility_notes)
    notes.extend(prepared.regime_notes)

    periods = _periods_to_solve(prepared.regime, backtest_months, notes, config)

    if optimiser == "mv":
        from pcp.model.optimiser_mv import solve_mean_variance

        solver = solve_mean_variance
        notes.append(
            f"the mean-variance branch produced this allocation. It is a "
            f"{config.get('mean_variance.label')} and reintroduces a covariance matrix, so it is not the "
            f"model of record."
        )
    elif optimiser == "curve":
        solver = None
    else:
        raise PipelineError(f"unknown optimiser {optimiser!r}; expected 'curve' or 'mv'")

    allocations: list[Allocation] = []
    for index in periods:
        regime_vector = prepared.regime.at(index)
        if optimiser == "curve":
            solved = solve_curve(
                prepared.bb,
                prepared.mandate.target_curve,
                regime_vector,
                prepared.system,
                config,
                speed=resolved_speed,
            )
        else:
            solved = solver(  # type: ignore[misc]
                prepared,
                regime_vector,
                index,
                config,
                speed=resolved_speed,
            )

        weights = solved.weights
        grid = portfolio_map(weights, prepared.blocks, config)
        esg_scores = np.asarray([float(b.esg) for b in prepared.blocks], dtype=float)

        allocations.append(
            Allocation(
                period=prepared.regime.dates[index],
                weights=weights,
                bb_ids=tuple(b.bb_id for b in prepared.blocks),
                objective_value=solved.objective_value,
                conditions_met=solved.conditions_met,
                solver_status=solved.status,
                solver_method=solved.method,
                return_dist_final=achieved_curve(weights, prepared.bb),
                portfolio_map=grid,
                role_allocation=role_allocation(grid, config),
                esg=float(esg_scores @ weights),
                regime=regime_vector,
                binding=binding_constraints(weights, prepared.system),
            )
        )
        notes.extend(solved.notes)

    if not allocations:
        raise PipelineError("no period was solved, so there is no allocation to report")

    # How much of the objective the weights actually control.
    #
    # Measured rather than assumed, and reported on every run. Because the shortfall is summed over
    # instruments before squaring, an instrument at zero weight still contributes its full target to every
    # state, so the objective carries a floor set by the universe size (decisions.md D28). Where the regime
    # is a probability vector each contribution is small against the target, and that floor dominates
    # (D29). A reader needs to know when an allocation was settled by the constraints rather than by the
    # fit, and the only honest way to say so is to compute it.
    leverage = _weight_leverage(prepared, allocations[-1])
    if leverage is not None and leverage < 0.05:
        notes.append(
            f"the weights control only {leverage:.2%} of the objective's level: the objective is "
            f"{allocations[-1].objective_value:.6g} against a floor of "
            f"{_objective_floor(prepared, allocations[-1]):.6g} with nothing allocated. This allocation is "
            f"therefore driven mainly by the mandate's constraints, with the curve fit acting as a "
            f"tie-breaker. The cause is the objective summing shortfall over instruments before squaring, "
            f"combined with a probability-normalised regime vector, and it is an accepted property of the "
            f"current model rather than a solver failure. See decisions.md D28 and D29."
        )

    key = idempotency_key(
        prepared.mandate,
        prepared.returnset,
        prepared.regime,
        ENGINE_VERSION,
        optimiser,
        resolved_speed,
        backtest_months,
        prepared.economy_weights,
    )

    return Result(
        mandate=prepared.mandate,
        regime_id=prepared.regime.regime_id,
        regime_timeline_id=prepared.regime.regime_timeline_id,
        regime_model_version=prepared.regime.model_version,
        return_set_id=prepared.returnset.return_set_id,
        returnset_model_version=prepared.returnset.model_version,
        universe_version=prepared.returnset.universe_version,
        engine_version=ENGINE_VERSION,
        optimiser=optimiser,
        speed=resolved_speed,
        as_of=prepared.regime.as_of,
        idempotency_key=key,
        trace_id=trace_id_from(key),
        allocations=tuple(allocations),
        crisis_tail=prepared.regime.crisis_tail(),
        country_weights=dict(prepared.economy_weights),
        notes=tuple(_dedupe(notes)),
    )


def _objective_floor(prepared: RunInputs, allocation: Allocation) -> float:
    """The objective with nothing allocated: the part no weighting can reach.

    See decisions.md D28. This is not zero, because a zero-weight instrument still contributes its full
    target to every state's shortfall.
    """
    from pcp.model.objective import curve_objective

    zero = np.zeros(prepared.bb.shape[0], dtype=float)
    return curve_objective(zero, prepared.bb, prepared.mandate.target_curve, allocation.regime)


def _weight_leverage(prepared: RunInputs, allocation: Allocation) -> float | None:
    """The fraction of the objective's level the allocation actually controls.

    `(floor - achieved) / floor`. None when the floor is zero, which means the mandate curve is met
    everywhere and the ratio would say nothing.
    """
    floor = _objective_floor(prepared, allocation)
    if floor <= 0.0:
        return None
    return (floor - allocation.objective_value) / floor


def _periods_to_solve(
    regime: RegimeTimeline,
    backtest_months: int,
    notes: list[str],
    config: Config,
) -> list[int]:
    """Which period indices to solve.

    Live mode solves the latest period only. Backtest mode solves the trailing window, matching the
    reference implementation's loop from `n = len(path) - backtest` to the end.
    """
    total = regime.n_periods
    if backtest_months <= 0:
        return [total - 1]

    ceiling = int(config.get("run.max_backtest_months"))
    requested = int(backtest_months)
    if requested > ceiling:
        notes.append(
            f"a backtest of {requested} months was requested but the configured ceiling is {ceiling}, so "
            f"{ceiling} was used."
        )
        requested = ceiling
    if requested > total:
        notes.append(
            f"a backtest of {requested} months was requested but the Regime covers {total}, so the whole "
            f"available history was used. The window is set by the Regime, not by the request."
        )
        requested = total
    return list(range(total - requested, total))


def _dedupe(notes: Sequence[str]) -> list[str]:
    """Preserve order, drop repeats.

    A backtest solves many periods and most notes are identical across them, so an undeduplicated list
    would report the same sentence two hundred times.
    """
    seen: set[str] = set()
    out: list[str] = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            out.append(note)
    return out


def _default_returnset(config: Config) -> Path:
    configured = Path(str(config.get("contracts.returnset")))
    if configured.is_absolute():
        return configured
    return (Path(__file__).resolve().parent.parent / configured).resolve()


def diagnostics(inputs: RunInputs, result: Result, config: Config) -> dict[str, Any]:
    """The context a reader needs alongside the numbers.

    Kept separate from `Result` because it is derived, not produced: everything here can be recomputed
    from the result and the inputs, and putting it on the result would invite it drifting out of step.
    """
    current = result.current
    return {
        "realised_exposures": realised_exposures(current.weights, inputs.system),
        "shortfall_by_state": [
            float(v)
            for v in shortfall_by_state(
                current.weights, inputs.bb, inputs.mandate.target_curve, current.regime
            )
        ],
        "scenario_allocation": scenario_allocation(current.portfolio_map, config),
        "constraint_rows": inputs.system.n_rows,
        "universe_size": len(inputs.blocks),
        # See decisions.md D28 and D29. Carried on every result so a constraint-driven allocation is
        # visible rather than something a reader has to know to suspect.
        "objective_floor": _objective_floor(inputs, current),
        "weight_leverage": _weight_leverage(inputs, current),
        "regime_contributors": inputs.contributors,
        "slot_weights": inputs.slot_weights,
        "regime_window": {
            "first": inputs.regime.dates[0],
            "last": inputs.regime.dates[-1],
            "months": inputs.regime.n_periods,
        },
        "instruments": [
            {
                "bb_id": b.bb_id,
                "name": b.name,
                "ticker": b.ticker,
                "role": b.role,
                "region_geo": b.region_geo,
                "region_scope": b.region_scope,
                "currency": b.currency,
                "asset_class": b.asset_class,
                "economic_phase": b.economic_phase,
                "capital_type": b.capital_type,
                "liquidity": b.liquidity,
                "home_scenario": b.home_scenario,
                "esg": b.esg,
                "weight": float(w),
            }
            for b, w in zip(inputs.blocks, current.weights)
        ],
    }
