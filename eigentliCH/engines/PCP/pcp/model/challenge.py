"""Portfolio challenge: score a proposed portfolio against the optimised one.

The question this answers is the one a client actually asks. Not "what would you build", which the
optimiser already answers, but "what is wrong with what I hold". So the proposal is scored on exactly the
objective, regime and constraints the optimiser used, and the comparison is like for like: same profile
matrix, same target curve, same regime distribution, same bounds.

What it reports, in the order a reader needs it:

1. Whether the proposal is admissible at all under the mandate, and precisely which limits it breaches.
2. How much worse it fits, on the objective and per regime state, so a gap can be located rather than
   just totalled.
3. Where the weight differs, by instrument and by category.

**A worse objective is not automatically a worse portfolio.** The optimiser minimises shortfall below the
mandate curve weighted by the live regime, and that is the mandate's own definition of good. A proposal
can score worse and still be the right holding for a reason outside the mandate: a tax position, an
illiquid stake, a view the mandate does not encode. The report says how much worse and where, and stops
there.

**Naming note.** The legacy `Expert_Controller` flag called "Generic Portfolio Challenge" did something
else: it re-ran the optimiser under each of four `opti_scale` stances and exported four workbooks. That is
a risk-stance sweep rather than a comparison against holdings, and it depends on `opti_scale` variants
which live in the Regime producer (decisions.md D12). See decisions.md D28.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from pcp.config import Config
from pcp.contracts import BuildingBlock, Mandate, MandateError, ReturnSet
from pcp.model.objective import achieved_curve, curve_objective, shortfall_by_state
from pcp.model.pfmap import portfolio_map, role_allocation


class ChallengeError(ValueError):
    """Raised when a proposed portfolio cannot be scored against a mandate."""


#: The dimensions a breach is checked against, and how to read the label off a block.
_DIMENSIONS: tuple[tuple[str, str, Any], ...] = (
    ("currency", "currency", lambda b: b.currency),
    ("region", "region", lambda b: b.region_geo),
    ("role", "role", lambda b: b.role),
    ("capital_type", "capital_type", lambda b: b.capital_type),
    ("liquidity", "liquidity", lambda b: b.liquidity),
    ("phase", "phase", lambda b: b.economic_phase),
    ("asset_class", "asset_class", lambda b: b.asset_class),
)


@dataclass(frozen=True, slots=True)
class Breach:
    """One mandate limit the proposal does not respect."""

    kind: str            # "bound" | "position" | "esg" | "universe" | "budget"
    dimension: str
    category: str
    side: str            # "lower" | "upper"
    limit: float
    realised: float

    @property
    def size(self) -> float:
        return abs(self.realised - self.limit)

    def describe(self) -> str:
        if self.kind == "universe":
            return (
                f"{self.category} carries {self.realised:.2%} but is not in the mandate's investable "
                f"universe"
            )
        if self.kind == "position":
            return (
                f"{self.category} is {self.realised:.2%}, above the maximum single position of "
                f"{self.limit:.2%}"
            )
        if self.kind == "esg":
            return (
                f"weighted-average ESG is {self.realised:.2f}, below the mandate floor of {self.limit:.2f}"
            )
        if self.kind == "budget":
            return f"the weights sum to {self.realised:.4f} rather than {self.limit:.4f}"
        direction = "above" if self.side == "upper" else "below"
        return (
            f"{self.dimension} {self.category} is {self.realised:.2%}, {direction} its "
            f"{self.side} bound of {self.limit:.2%}"
        )


@dataclass(frozen=True, slots=True)
class Side:
    """One portfolio, scored."""

    label: str
    weights: np.ndarray                  # over the comparison universe, in its order
    objective_value: float
    shortfall_by_state: np.ndarray
    achieved_curve: np.ndarray
    esg: float
    role_allocation: dict[str, float]
    exposures: dict[str, dict[str, float]]
    portfolio_map: np.ndarray


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """A proposal set against the optimised allocation.

    `universe` is the union of the mandate's investable universe and whatever the proposal holds, so both
    sides are scored on one profile matrix and the objective values are directly comparable.
    """

    proposed: Side
    optimised: Side
    universe: tuple[BuildingBlock, ...]
    breaches: tuple[Breach, ...]
    outside_universe: tuple[int, ...]
    notes: tuple[str, ...] = ()

    @property
    def admissible(self) -> bool:
        """Whether the proposal respects every mandate limit."""
        return not self.breaches

    @property
    def objective_gap(self) -> float:
        """How much worse the proposal fits. Positive means worse."""
        return self.proposed.objective_value - self.optimised.objective_value

    @property
    def objective_ratio(self) -> float | None:
        """The proposal's objective as a multiple of the optimum, or None when the optimum is zero.

        None rather than infinity: an optimum of zero means the mandate curve is fully met, and a ratio
        against zero would report a meaningless number instead of saying so.
        """
        if self.optimised.objective_value <= 0.0:
            return None
        return self.proposed.objective_value / self.optimised.objective_value

    def weight_differences(self) -> list[dict[str, Any]]:
        """Per instrument, proposed against optimised, largest absolute difference first."""
        rows = [
            {
                "bb_id": block.bb_id,
                "name": block.name,
                "role": block.role,
                "region_geo": block.region_geo,
                "currency": block.currency,
                "asset_class": block.asset_class,
                "proposed": float(p),
                "optimised": float(o),
                "difference": float(p - o),
                "in_universe": block.bb_id not in self.outside_universe,
            }
            for block, p, o in zip(self.universe, self.proposed.weights, self.optimised.weights)
        ]
        return sorted(rows, key=lambda row: -abs(row["difference"]))

    def exposure_differences(self) -> dict[str, dict[str, dict[str, float]]]:
        """Per dimension and category, both sides and the gap."""
        out: dict[str, dict[str, dict[str, float]]] = {}
        for dimension, categories in self.proposed.exposures.items():
            out[dimension] = {}
            for category, value in categories.items():
                other = self.optimised.exposures[dimension][category]
                if abs(value) < 1e-12 and abs(other) < 1e-12:
                    continue
                out[dimension][category] = {
                    "proposed": float(value),
                    "optimised": float(other),
                    "difference": float(value - other),
                }
        return out

    def worst_states(self, count: int = 3) -> list[dict[str, Any]]:
        """The regime states where the proposal falls furthest behind the optimum.

        Reported because the objective is a sum over states and a single number cannot say whether a
        proposal is uniformly slightly worse or badly exposed in the crisis tail. Those are different
        findings.
        """
        gap = np.asarray(self.proposed.shortfall_by_state) - np.asarray(
            self.optimised.shortfall_by_state
        )
        order = np.argsort(-gap)[:count]
        return [
            {
                "state": int(i) + 1,
                "proposed_shortfall": float(self.proposed.shortfall_by_state[i]),
                "optimised_shortfall": float(self.optimised.shortfall_by_state[i]),
                "gap": float(gap[i]),
            }
            for i in order
            if gap[i] > 1e-12
        ]


# ---------------------------------------------------------------------------
# Reading a proposal
# ---------------------------------------------------------------------------


def load_proposal(path: Path | str) -> dict[int, float]:
    """Read a proposed portfolio from YAML, JSON or CSV.

    Accepted shapes:

        {"weights": {"1": 0.2, "5": 0.8}}      mapping of bb_id to weight
        {"1": 0.2, "5": 0.8}                   the mapping directly
        bb_id,weight                           CSV with a header

    Weights may be fractions or percentages: a set summing to about 100 is read as percentages and
    converted, with a note. Anything else is left alone and checked against the budget rule.
    """
    source = Path(path)
    if not source.exists():
        raise ChallengeError(f"proposed portfolio not found: {source}")

    if source.suffix.lower() == ".csv":
        import csv

        raw: dict[str, Any] = {}
        with source.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                keys = {k.lower().strip(): k for k in row}
                id_key = keys.get("bb_id") or keys.get("id")
                weight_key = keys.get("weight") or keys.get("weights")
                if id_key is None or weight_key is None:
                    raise ChallengeError(
                        f"{source} needs columns 'bb_id' and 'weight'; found {sorted(row)}"
                    )
                raw[str(row[id_key]).strip()] = row[weight_key]
    else:
        import json

        import yaml

        text = source.read_text(encoding="utf-8")
        payload = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
        if not isinstance(payload, Mapping):
            raise ChallengeError(f"{source} must contain a mapping of bb_id to weight")
        raw = dict(payload.get("weights") or payload)

    weights: dict[int, float] = {}
    for key, value in raw.items():
        if str(key) in {"weights", "client", "name", "label", "note"}:
            continue
        try:
            weights[int(key)] = float(value)
        except (TypeError, ValueError) as error:
            raise ChallengeError(
                f"{source}: {key!r} -> {value!r} is not a bb_id and weight pair"
            ) from error

    if not weights:
        raise ChallengeError(f"{source} contains no weights")
    return weights


def normalise_proposal(weights: Mapping[int, float]) -> tuple[dict[int, float], list[str]]:
    """Convert an obvious percentage set to fractions. Otherwise leave it alone."""
    notes: list[str] = []
    total = float(sum(weights.values()))
    if 95.0 <= total <= 105.0:
        notes.append(
            f"the proposed weights summed to {total:.2f}, so they were read as percentages and divided by "
            f"one hundred."
        )
        return {k: v / 100.0 for k, v in weights.items()}, notes
    return dict(weights), notes


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def challenge(
    proposal: Mapping[int, float],
    mandate: Mandate,
    returnset: ReturnSet,
    optimised_weights: Mapping[int, float] | Sequence[float],
    optimised_bb_ids: Sequence[int],
    regime: np.ndarray,
    config: Config,
    proposal_label: str = "proposed",
) -> ChallengeResult:
    """Score a proposal against an optimised allocation on one mandate.

    Args:
        proposal: bb_id to weight. Need not match the mandate universe.
        mandate: The mandate whose objective and limits apply.
        returnset: Supplies the profile for every instrument on either side.
        optimised_weights: The optimiser's weights, either as a mapping or positionally.
        optimised_bb_ids: The order `optimised_weights` is in, when given positionally.
        regime: The 25-length distribution the comparison is made under.
        config: Loaded configuration.

    Returns:
        The comparison.

    Raises:
        ChallengeError: If the proposal names an instrument the ReturnSet has no profile for. Nothing is
            fabricated, so an unknown holding stops the comparison rather than being dropped from it.
    """
    notes: list[str] = []
    proposed, conversion_notes = normalise_proposal(proposal)
    notes.extend(conversion_notes)

    if isinstance(optimised_weights, Mapping):
        optimised = {int(k): float(v) for k, v in optimised_weights.items()}
    else:
        optimised = {
            int(bb_id): float(w) for bb_id, w in zip(optimised_bb_ids, optimised_weights)
        }

    known = set(returnset.by_id())
    unknown = sorted(bb_id for bb_id in proposed if bb_id not in known)
    if unknown:
        raise ChallengeError(
            f"the proposal holds building block(s) {unknown}, which the ReturnSet has no profile for, so "
            f"they cannot be scored. The PCP does not invent a return profile. Either add them to the "
            f"Fund Map register and rebuild the ReturnSet, or remove them from the proposal."
        )

    negative = sorted(bb_id for bb_id, w in proposed.items() if w < 0.0)
    if negative:
        notes.append(
            f"the proposal holds a negative weight in {negative}. The mandate forbids shorts, so these "
            f"are reported as breaches and the objective below is computed on the weights as supplied."
        )

    # One universe for both sides, so the two objective values are comparable. The mandate's own order
    # first, then anything the proposal adds, which keeps the optimised side in its familiar order.
    extra = [bb_id for bb_id in sorted(proposed) if bb_id not in mandate.universe]
    order = list(mandate.universe) + extra
    universe = returnset.subset(order)
    bb = ReturnSet.bb_matrix(universe)

    proposed_vector = np.asarray([proposed.get(bb_id, 0.0) for bb_id in order], dtype=float)
    optimised_vector = np.asarray([optimised.get(bb_id, 0.0) for bb_id in order], dtype=float)

    if extra:
        notes.append(
            f"the proposal holds {len(extra)} instrument(s) outside the mandate's investable universe, "
            f"which are scored so the comparison is complete and reported as breaches because the mandate "
            f"would not permit them."
        )

    proposed_side = _score(proposal_label, proposed_vector, universe, bb, mandate, regime, config)
    optimised_side = _score("optimised", optimised_vector, universe, bb, mandate, regime, config)

    breaches = _breaches(
        proposed_vector, universe, mandate, config, outside=set(extra), esg=proposed_side.esg
    )

    return ChallengeResult(
        proposed=proposed_side,
        optimised=optimised_side,
        universe=universe,
        breaches=breaches,
        outside_universe=tuple(extra),
        notes=tuple(notes),
    )


def _score(
    label: str,
    weights: np.ndarray,
    universe: Sequence[BuildingBlock],
    bb: np.ndarray,
    mandate: Mandate,
    regime: np.ndarray,
    config: Config,
) -> Side:
    grid = portfolio_map(weights, universe, config)
    esg_scores = np.asarray([float(b.esg) for b in universe], dtype=float)
    total = float(weights.sum())
    return Side(
        label=label,
        weights=weights,
        objective_value=curve_objective(weights, bb, mandate.target_curve, regime),
        shortfall_by_state=shortfall_by_state(weights, bb, mandate.target_curve, regime),
        achieved_curve=achieved_curve(weights, bb),
        # Weighted average, so a proposal that does not sum to one is still comparable on ESG rather than
        # being flattered or penalised by its total.
        esg=float(esg_scores @ weights / total) if total > 0 else 0.0,
        role_allocation=role_allocation(grid, config),
        exposures=_exposures(weights, universe, config),
        portfolio_map=grid,
    )


def _exposures(
    weights: np.ndarray,
    universe: Sequence[BuildingBlock],
    config: Config,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for dimension, vocabulary_name, getter in _DIMENSIONS:
        vocabulary = config.vocabularies.by_name(vocabulary_name)
        totals = {label: 0.0 for label in vocabulary.labels}
        for weight, block in zip(np.asarray(weights, dtype=float), universe):
            totals[vocabulary.labels[vocabulary.index(getter(block))]] += float(weight)
        out[dimension] = totals
    return out


def _breaches(
    weights: np.ndarray,
    universe: Sequence[BuildingBlock],
    mandate: Mandate,
    config: Config,
    outside: set[int],
    esg: float,
    tolerance: float = 1e-6,
) -> tuple[Breach, ...]:
    """Every mandate limit the proposal does not respect.

    Computed from the category exposures rather than from the constraint matrix, so the check is
    independent of universe ordering and works on a universe wider than the mandate's own.
    """
    found: list[Breach] = []
    x = np.asarray(weights, dtype=float)

    total = float(x.sum())
    if abs(total - 1.0) > 1e-4:
        found.append(Breach("budget", "portfolio", "sum", "upper", 1.0, total))

    for dimension, vocabulary_name, getter in _DIMENSIONS:
        vocabulary = config.vocabularies.by_name(vocabulary_name)
        bounds = mandate.bounds_for(dimension, vocabulary)
        totals = {label: 0.0 for label in vocabulary.labels}
        for weight, block in zip(x, universe):
            totals[vocabulary.labels[vocabulary.index(getter(block))]] += float(weight)
        for k, label in enumerate(vocabulary.labels):
            realised = totals[label]
            if realised > bounds[k].upper + tolerance:
                found.append(
                    Breach("bound", dimension, label, "upper", bounds[k].upper, realised)
                )
            if realised < bounds[k].lower - tolerance:
                found.append(
                    Breach("bound", dimension, label, "lower", bounds[k].lower, realised)
                )

    for weight, block in zip(x, universe):
        if block.bb_id in outside and abs(weight) > tolerance:
            found.append(
                Breach("universe", "universe", block.name, "upper", 0.0, float(weight))
            )
        elif weight > mandate.max_single_position + tolerance:
            found.append(
                Breach(
                    "position", "position", block.name, "upper",
                    mandate.max_single_position, float(weight),
                )
            )
        elif weight < -tolerance:
            found.append(Breach("position", "position", block.name, "lower", 0.0, float(weight)))

    if esg < mandate.esg_min - tolerance:
        found.append(Breach("esg", "esg", "portfolio", "lower", mandate.esg_min, esg))

    # Largest first: the biggest breach is the one to answer for.
    return tuple(sorted(found, key=lambda b: -b.size))


def equal_weight_proposal(mandate: Mandate) -> dict[int, float]:
    """An equal-weight portfolio over the mandate's universe.

    A neutral reference, so a challenge can be run without a client portfolio to hand and the objective
    scale has something to be read against.
    """
    n = len(mandate.universe)
    if n == 0:
        raise MandateError(f"mandate {mandate.identity} has an empty universe")
    return {bb_id: 1.0 / n for bb_id in mandate.universe}
