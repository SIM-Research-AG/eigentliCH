"""Typed contracts: Regime, ReturnSet, Mandate, and the results the optimiser emits.

Two rules this module exists to enforce.

**The regime rule (binding, spec section 3.2).** A ReturnSet whose `regime_id` does not match the
Regime the mandate is being optimised against is rejected, not reconciled. There is no override: the
alignment is wired in the producers (decisions.md D11), so a mismatch here means a genuine build-order
violation rather than a local inconvenience.

**The unit rule (decisions.md D2).** Instrument profiles and the mandate target curve are both
annualised decimal fractions. A ReturnSet that does not declare `annualised_decimal` on the horizon the
mandate expects is rejected, because comparing a percent curve against a decimal one silently
misstates the fit by two orders of magnitude, which is exactly the defect the reference implementation
carried.

Nothing here interpolates, defaults, or infers a missing input. A run that needs an unavailable input
fails loudly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from pcp.config import Config, Vocabulary

STATE_GRID: int = 25


class ContractError(ValueError):
    """Raised when a consumed contract is malformed or internally inconsistent."""


class RegimeMismatchError(ContractError):
    """Raised when a ReturnSet's regime_id does not match the Regime being optimised against.

    Separate from ContractError so the CLI can report it as the specific, expected handled failure it
    is (exit code 1) rather than as a malformed file.
    """


class MandateError(ValueError):
    """Raised when a mandate is malformed, or names something the universe does not contain."""


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeTimeline:
    """The Regime timeline the macro programme publishes, as the optimiser consumes it.

    `distributions` is the object the objective integrates over: one row per period, each a 25-length
    probability vector ordered crisis-low (index 0) to boom-high (index 24). The contract delivers the
    full distribution rather than only a state path, so nothing downstream has to expand one.
    """

    regime_timeline_id: str
    economy_scope: str
    model_version: str
    as_of: str
    period: str
    state_grid: int
    dates: tuple[str, ...]
    distributions: np.ndarray          # shape (T, state_grid), each row sums to 1
    regime_id: str
    current_state: int
    phase: int | None
    saturation_pct: float | None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state_grid != STATE_GRID:
            raise ContractError(f"regime state_grid must be {STATE_GRID}, got {self.state_grid}")
        arr = np.asarray(self.distributions, dtype=float)
        if arr.ndim != 2 or arr.shape[1] != self.state_grid:
            raise ContractError(
                f"regime distributions must have shape (T, {self.state_grid}), got {arr.shape}"
            )
        if arr.shape[0] != len(self.dates):
            raise ContractError(
                f"regime has {arr.shape[0]} distribution rows against {len(self.dates)} dates"
            )
        if arr.shape[0] == 0:
            raise ContractError("regime timeline is empty")
        if np.any(arr < -1e-12):
            worst = int(np.argmin(arr.min(axis=1)))
            raise ContractError(
                f"regime distribution for period {self.dates[worst]} has a negative weight"
            )
        sums = arr.sum(axis=1)
        bad = np.flatnonzero(np.abs(sums - 1.0) > 1e-6)
        if bad.size:
            i = int(bad[0])
            raise ContractError(
                f"regime distribution for period {self.dates[i]} sums to {sums[i]:.8f}, not 1. "
                f"A distribution that does not sum to one rescales every instrument's contribution."
            )
        if not (0 <= self.current_state < self.state_grid):
            raise ContractError(
                f"regime current_state={self.current_state} outside 0..{self.state_grid - 1}"
            )

    @property
    def n_periods(self) -> int:
        return int(np.asarray(self.distributions).shape[0])

    def current(self) -> np.ndarray:
        """The distribution for the latest period: the `M` a live run optimises against."""
        return np.asarray(self.distributions, dtype=float)[-1].copy()

    def at(self, index: int) -> np.ndarray:
        """The distribution for one period by position, for the backtest loop."""
        arr = np.asarray(self.distributions, dtype=float)
        if not (-arr.shape[0] <= index < arr.shape[0]):
            raise ContractError(f"regime period index {index} out of range (T={arr.shape[0]})")
        return arr[index].copy()

    def crisis_tail(self, bins: int = 5) -> float:
        """Probability mass on the most cautious `bins` states of the latest period.

        Reported alongside every allocation. The asymmetric objective penalises only the downside of
        the target curve weighted by this distribution, so the crisis tail is what makes the method
        behave differently from a symmetric fit. A tail that has been smoothed away upstream would
        quietly turn the optimiser into something else.
        """
        return float(self.current()[:bins].sum())


# ---------------------------------------------------------------------------
# ReturnSet
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildingBlock:
    """One investable building block, with everything the constraints and the map need.

    `region_geo` is geography and drives the regional constraint. `region_scope` is the regime signal
    scope and drives regime selection only. Conflating the two is the defect that decisions.md D15
    fixes, so they are separate fields here and never assigned from one another.
    """

    bb_id: int
    name: str
    ticker: str
    role: str
    home_scenario: str
    region_geo: str
    region_scope: str
    currency: str
    asset_class: str
    economic_phase: str
    capital_type: str
    liquidity: str
    esg: float
    profile_by_state: np.ndarray       # shape (25,), annualised decimals, crisis-low to boom-high
    estimation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        arr = np.asarray(self.profile_by_state, dtype=float)
        if arr.shape != (STATE_GRID,):
            raise ContractError(
                f"building block {self.bb_id} ({self.name!r}) has a profile of shape {arr.shape}, "
                f"expected ({STATE_GRID},)"
            )
        if not np.all(np.isfinite(arr)):
            raise ContractError(
                f"building block {self.bb_id} ({self.name!r}) has a non-finite profile value"
            )


@dataclass(frozen=True, slots=True)
class ReturnSet:
    """The per-block return profiles the Fund Map programme publishes.

    Carries no `mu`, `sigma`, or covariance: the curve fit integrates the profiles directly.
    """

    return_set_id: str
    regime_id: str
    as_of: str
    model_version: str
    universe_version: str
    state_to_scenario_version: str
    horizon_years: float
    values_unit: str
    state_grid: int
    scenarios: tuple[str, ...]
    state_to_scenario: dict[int, str]
    house_view: dict[str, float]
    blocks: tuple[BuildingBlock, ...]
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state_grid != STATE_GRID:
            raise ContractError(f"ReturnSet state_grid must be {STATE_GRID}, got {self.state_grid}")
        if not self.blocks:
            raise ContractError("ReturnSet carries no building blocks")
        ids = [b.bb_id for b in self.blocks]
        if len(set(ids)) != len(ids):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            raise ContractError(f"ReturnSet has duplicate bb_ids: {duplicates}")

    def by_id(self) -> dict[int, BuildingBlock]:
        return {b.bb_id: b for b in self.blocks}

    def subset(self, bb_ids: Sequence[int]) -> tuple[BuildingBlock, ...]:
        """The blocks named by `bb_ids`, in the order given.

        Order is load-bearing: it fixes the meaning of every position in the weight vector and every
        column of the constraint matrix. Callers pass the mandate's universe order and get it back.
        """
        index = self.by_id()
        missing = [i for i in bb_ids if i not in index]
        if missing:
            raise MandateError(
                f"the mandate names building blocks the ReturnSet does not contain: {missing}. "
                f"The PCP does not fabricate a return profile, so the run cannot proceed."
            )
        return tuple(index[i] for i in bb_ids)

    @staticmethod
    def bb_matrix(blocks: Sequence[BuildingBlock]) -> np.ndarray:
        """The `BB` matrix: row j is block j's 25-length profile."""
        if not blocks:
            raise MandateError("cannot build a BB matrix from an empty universe")
        return np.vstack([np.asarray(b.profile_by_state, dtype=float) for b in blocks])


# ---------------------------------------------------------------------------
# Mandate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bound:
    """A per-category allocation bound. Both ends are fractions of the portfolio."""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.lower > self.upper + 1e-12:
            raise MandateError(f"bound lower={self.lower} exceeds upper={self.upper}")
        if self.lower < -1e-12:
            raise MandateError(f"bound lower={self.lower} is negative")


@dataclass(frozen=True, slots=True)
class Mandate:
    """The per-user input: a target return curve and the allocation constraints.

    Lives on the user side of the regulated wall. The Regime and the ReturnSet are population-level;
    this is where the client's mandate meets them.
    """

    client: str
    name: str
    market: str
    currency: str
    benchmark: str
    max_single_position: float
    esg_min: float
    horizon_years: float
    target_curve: np.ndarray                       # shape (25,), annualised decimals
    universe: tuple[int, ...]                      # bb_ids, order fixes the weight vector
    fixed_allocations: dict[int, float]            # bb_id -> pinned weight
    bounds: dict[str, dict[str, Bound]]            # dimension -> category label -> bound

    def __post_init__(self) -> None:
        curve = np.asarray(self.target_curve, dtype=float)
        if curve.shape != (STATE_GRID,):
            raise MandateError(
                f"mandate {self.client}/{self.name} target curve has shape {curve.shape}, "
                f"expected ({STATE_GRID},)"
            )
        if not np.all(np.isfinite(curve)):
            raise MandateError(f"mandate {self.client}/{self.name} target curve has a non-finite value")
        if not self.universe:
            raise MandateError(f"mandate {self.client}/{self.name} has an empty investable universe")
        if len(set(self.universe)) != len(self.universe):
            raise MandateError(f"mandate {self.client}/{self.name} repeats a building block")
        if not (0.0 < self.max_single_position <= 1.0):
            raise MandateError(
                f"mandate {self.client}/{self.name} max_single_position={self.max_single_position} "
                f"must lie in (0, 1]"
            )
        for bb_id, weight in self.fixed_allocations.items():
            if bb_id not in self.universe:
                raise MandateError(
                    f"mandate {self.client}/{self.name} pins bb_id {bb_id}, which is not in its universe"
                )
            if not (0.0 <= weight <= 1.0):
                raise MandateError(
                    f"mandate {self.client}/{self.name} pins bb_id {bb_id} at {weight}, outside [0, 1]"
                )
        pinned = sum(self.fixed_allocations.values())
        if pinned > 1.0 + 1e-9:
            raise MandateError(
                f"mandate {self.client}/{self.name} pins {pinned:.4f} of the portfolio, which exceeds "
                f"1. The budget equality could never be met."
            )

    @property
    def identity(self) -> str:
        return f"{self.client}/{self.name}"

    def bounds_for(self, dimension: str, vocabulary: Vocabulary) -> list[Bound]:
        """Bounds for one dimension, in vocabulary order, one per category.

        A category the mandate does not mention is unconstrained: [0, 1]. Returning a dense list in
        vocabulary order is what lets the constraint assembler stay positional without ever calling
        `list.index` itself.
        """
        declared = self.bounds.get(dimension, {})
        unknown = [label for label in declared if not vocabulary.contains(label)]
        if unknown:
            raise MandateError(
                f"mandate {self.identity} sets a {dimension} bound on {unknown}, which is not in the "
                f"{vocabulary.name} vocabulary {list(vocabulary.labels)}"
            )
        return [declared.get(label, Bound(0.0, 1.0)) for label in vocabulary.labels]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BindingConstraint:
    """One constraint that was active at the optimum, reported alongside the number it produced."""

    dimension: str
    category: str
    side: str            # "lower" | "upper"
    bound: float
    realised: float


@dataclass(frozen=True, slots=True)
class Allocation:
    """One optimised period.

    `conditions_met` records whether the solver's raw weights summed to one before renormalisation,
    which is the honest signal about feasibility. The renormalised weights always sum to one, so
    reading only those would hide an infeasible mandate.
    """

    period: str
    weights: np.ndarray                       # normalised, one per universe member, in universe order
    bb_ids: tuple[int, ...]
    objective_value: float
    conditions_met: str                       # "yes" | "no"
    solver_status: str
    solver_method: str
    return_dist_final: np.ndarray             # shape (25,), the achieved portfolio curve
    portfolio_map: np.ndarray                 # shape (4, 5), roles by scenarios, crisis-low first
    role_allocation: dict[str, float]
    esg: float
    regime: np.ndarray                        # shape (25,), the M this period was optimised against
    binding: tuple[BindingConstraint, ...] = ()

    def __post_init__(self) -> None:
        w = np.asarray(self.weights, dtype=float)
        if w.shape != (len(self.bb_ids),):
            raise ContractError(
                f"allocation for {self.period} has {w.shape[0]} weights against {len(self.bb_ids)} "
                f"building blocks"
            )
        if np.asarray(self.portfolio_map).shape != (4, 5):
            raise ContractError(
                f"portfolio map must be 4 by 5, got {np.asarray(self.portfolio_map).shape}"
            )


@dataclass(frozen=True, slots=True)
class Result:
    """A complete run: its stamps, its allocations, and the context every number needs.

    Every figure this carries is model-derived, not a forecast.
    """

    mandate: Mandate
    regime_id: str
    regime_timeline_id: str
    regime_model_version: str
    return_set_id: str
    returnset_model_version: str
    universe_version: str
    engine_version: str
    optimiser: str                            # "curve" | "mv"
    speed: str
    as_of: str
    idempotency_key: str
    trace_id: str
    allocations: tuple[Allocation, ...]
    crisis_tail: float
    country_weights: dict[str, float]
    notes: tuple[str, ...] = ()
    label: str = "model-derived"

    @property
    def current(self) -> Allocation:
        """The allocation for the latest period, which a live run's single solve produces."""
        if not self.allocations:
            raise ContractError("result carries no allocations")
        return self.allocations[-1]

    @property
    def ok(self) -> bool:
        return all(a.conditions_met == "yes" for a in self.allocations)


# ---------------------------------------------------------------------------
# The binding checks
# ---------------------------------------------------------------------------


def require_regime_match(returnset: ReturnSet, regime: RegimeTimeline) -> None:
    """Reject a ReturnSet estimated under a different Regime (binding, spec section 3.2).

    Not reconciled, not warned about, not overridable. Mixing regime vintages would mean optimising a
    profile estimated under one macro state against the weights of another, and the resulting
    allocation would carry a `regime_id` that did not produce it.
    """
    if returnset.regime_id != regime.regime_id:
        raise RegimeMismatchError(
            f"regime_id mismatch, refusing to proceed. The ReturnSet {returnset.return_set_id} was "
            f"estimated under regime_id={returnset.regime_id!r}; the Regime timeline "
            f"{regime.regime_timeline_id} carries regime_id={regime.regime_id!r}. Rebuild the "
            f"ReturnSet against the current Regime rather than mixing vintages."
        )
    if returnset.state_grid != regime.state_grid:
        raise ContractError(
            f"state grid mismatch: ReturnSet has {returnset.state_grid}, Regime has "
            f"{regime.state_grid}"
        )


def require_units(returnset: ReturnSet, mandate: Mandate, config: Config) -> None:
    """Reject a ReturnSet whose units or horizon are not what the mandate curve is expressed on.

    See decisions.md D2. The reference implementation compared a decimal mandate curve against percent
    instrument profiles, which understates every shortfall by a factor of one hundred. Checking rather
    than converting is deliberate: a silent rescale would hide an upstream change of convention.
    """
    expected_unit = str(config.get("contracts.expected_values_unit"))
    if returnset.values_unit != expected_unit:
        raise ContractError(
            f"ReturnSet {returnset.return_set_id} declares values_unit={returnset.values_unit!r}, "
            f"but this programme requires {expected_unit!r}. The mandate target curve is expressed on "
            f"that unit, so the fit would be wrong by the unit ratio. Correct the producer rather than "
            f"rescaling here."
        )
    if abs(returnset.horizon_years - mandate.horizon_years) > 1e-9:
        raise ContractError(
            f"horizon mismatch: ReturnSet {returnset.return_set_id} is on "
            f"{returnset.horizon_years} year(s); mandate {mandate.identity} states "
            f"{mandate.horizon_years}. Normalise both to one horizon before optimising."
        )


def require_classifiable(
    blocks: Sequence[BuildingBlock],
    config: Config,
) -> None:
    """Fail before solving if any block cannot be placed in every constraint dimension.

    Assembling the constraint matrix with a silently dropped instrument would produce a portfolio whose
    realised exposures do not match the bounds it claims to satisfy.
    """
    vocabularies = config.vocabularies
    dimensions = (
        ("currency", vocabularies.currencies, lambda b: b.currency),
        ("region", vocabularies.regions, lambda b: b.region_geo),
        ("role", vocabularies.roles, lambda b: b.role),
        ("capital_type", vocabularies.capital_types, lambda b: b.capital_type),
        ("liquidity", vocabularies.liquidity, lambda b: b.liquidity),
        ("phase", vocabularies.phases, lambda b: b.economic_phase),
        ("asset_class", vocabularies.asset_classes, lambda b: b.asset_class),
        ("scenario", vocabularies.scenarios, lambda b: b.home_scenario),
    )
    problems: list[str] = []
    for block in blocks:
        for name, vocabulary, getter in dimensions:
            label = getter(block)
            if vocabulary.catch_all is None and not vocabulary.contains(label):
                problems.append(
                    f"block {block.bb_id} ({block.name!r}) has {name}={label!r}, not in "
                    f"{list(vocabulary.labels)}"
                )
    if problems:
        raise ContractError(
            "the universe contains blocks that cannot be classified:\n  " + "\n  ".join(problems)
        )


# ---------------------------------------------------------------------------
# Determinism stamps
# ---------------------------------------------------------------------------


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def idempotency_key(
    mandate: Mandate,
    returnset: ReturnSet,
    regime: RegimeTimeline,
    engine_version: str,
    optimiser: str,
    speed: str,
    backtest_months: int,
    country_weights: Mapping[str, float],
) -> str:
    """`hash(inputs + version)`, so an identical run is recognisable as one.

    Deliberately free of wall-clock and of any unseeded value: the key is a pure function of the
    inputs and the versions, which is what makes a run replayable from it.
    """
    payload = {
        "engine_version": engine_version,
        "optimiser": optimiser,
        "speed": speed,
        "backtest_months": int(backtest_months),
        "mandate": {
            "client": mandate.client,
            "name": mandate.name,
            "market": mandate.market,
            "currency": mandate.currency,
            "benchmark": mandate.benchmark,
            "max_single_position": mandate.max_single_position,
            "esg_min": mandate.esg_min,
            "horizon_years": mandate.horizon_years,
            "target_curve": [float(v) for v in np.asarray(mandate.target_curve, dtype=float)],
            "universe": list(mandate.universe),
            "fixed_allocations": {str(k): float(v) for k, v in sorted(mandate.fixed_allocations.items())},
            "bounds": {
                dimension: {
                    label: [bound.lower, bound.upper]
                    for label, bound in sorted(categories.items())
                }
                for dimension, categories in sorted(mandate.bounds.items())
            },
        },
        "return_set_id": returnset.return_set_id,
        "returnset_model_version": returnset.model_version,
        "universe_version": returnset.universe_version,
        "regime_id": regime.regime_id,
        "regime_timeline_id": regime.regime_timeline_id,
        "regime_model_version": regime.model_version,
        "country_weights": {k: float(v) for k, v in sorted(country_weights.items())},
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def trace_id_from(key: str) -> str:
    """A short, deterministic replay handle derived from the idempotency key.

    Derived rather than random so that replaying the same inputs reproduces the same trace, which is
    the point of recording one.
    """
    return f"TR-{key[:16]}"
