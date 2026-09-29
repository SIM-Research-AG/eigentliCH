"""Assemble the mandate's constraints: `A x <= b`, `sum(x) = 1`, and per-instrument bounds.

**Block order is the contract.** The rows of `A` and the entries of `b` are positional, so a reordering
changes what every bound means without changing any number. The order, from
`curveoptimization.m` lines 32 to 34 and 148 to 150:

    Currency (10), Region (7), Role (4), Capital Type (3), Liquidity (4), ESG (1), Phase (4),
    Asset Class (5)

Each classification block appears twice: `+block x <= upper` then `-block x <= -lower`. ESG is a single
negated row between Liquidity and Phase. Total rows: 2*(10+7+4+3+4+4+5) + 1 = 75.

**The ESG row is a real constraint here.** In the reference implementation the ESG row was
`ones(1, n)`, so `-ESG . x <= -esg_min` reduced to `sum(x) >= esg_min`, which the budget equality
satisfies for any minimum at or below one. The constraint never referenced an instrument's ESG score and
was inert. This build uses the per-instrument scores, so the row is a genuine weighted-average floor. See
decisions.md D16, and expect mandates whose minimum was set against the inert version to bind now.

**Bounds.** The lower bound per instrument is its fixed allocation (zero if none). The upper bound is the
fixed allocation where that is non-zero, which pins the position, else the mandate's maximum single
position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from pcp.config import Config, Vocabulary
from pcp.contracts import BindingConstraint, BuildingBlock, Mandate


@dataclass(frozen=True, slots=True)
class ConstraintBlock:
    """One classification dimension's contribution to `A` and `b`."""

    dimension: str
    vocabulary: Vocabulary
    indicator: np.ndarray            # (k, n), 1 where instrument is in category k
    lower: np.ndarray                # (k,)
    upper: np.ndarray                # (k,)
    upper_rows: tuple[int, ...]      # row positions in A of the +block half
    lower_rows: tuple[int, ...]      # row positions in A of the -block half


@dataclass(frozen=True, slots=True)
class ConstraintSystem:
    """The assembled system the solver consumes.

    Attributes:
        a: Inequality matrix, `A x <= b`.
        b: Inequality right-hand side.
        lower_bounds: Per-instrument lower bound.
        upper_bounds: Per-instrument upper bound.
        blocks: Per dimension, the indicator and the row positions, for reporting which bound bound.
        esg_row: The ESG coefficient row, one score per instrument.
        esg_min: The mandate's weighted-average floor.
        esg_row_index: Where the ESG row sits in `A`.
        row_labels: One human-readable label per row of `A`, so a binding row can be named.
    """

    a: np.ndarray
    b: np.ndarray
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    blocks: tuple[ConstraintBlock, ...]
    esg_row: np.ndarray
    esg_min: float
    esg_row_index: int
    row_labels: tuple[str, ...]

    @property
    def n_instruments(self) -> int:
        return int(self.a.shape[1])

    @property
    def n_rows(self) -> int:
        return int(self.a.shape[0])

    def feasibility_notes(self) -> list[str]:
        """Structural infeasibilities that can be detected before solving.

        Worth reporting up front: a mandate whose category upper bounds cannot reach one, or whose lower
        bounds already exceed one, has no feasible portfolio at all, and saying so is more useful than a
        solver failure message.
        """
        notes: list[str] = []
        for block in self.blocks:
            # Only categories with at least one member can carry weight.
            populated = self.indicator_is_populated(block)
            reachable = float(block.upper[populated].sum()) if populated.any() else 0.0
            if reachable < 1.0 - 1e-9:
                notes.append(
                    f"the {block.dimension} upper bounds sum to {reachable:.4f} across categories that "
                    f"have members, so the weights cannot reach one. This mandate is infeasible as "
                    f"stated."
                )
            demanded = float(block.lower.sum())
            if demanded > 1.0 + 1e-9:
                notes.append(
                    f"the {block.dimension} lower bounds sum to {demanded:.4f}, which exceeds one. This "
                    f"mandate is infeasible as stated."
                )
            empty_with_floor = [
                block.vocabulary.labels[k]
                for k in range(len(block.vocabulary))
                if block.lower[k] > 1e-12 and not populated[k]
            ]
            if empty_with_floor:
                notes.append(
                    f"the mandate sets a {block.dimension} floor on {empty_with_floor}, but the universe "
                    f"has no instrument in those categories, so the floor cannot be met."
                )
        if float(self.upper_bounds.sum()) < 1.0 - 1e-9:
            notes.append(
                f"the per-instrument upper bounds sum to {float(self.upper_bounds.sum()):.4f}, so the "
                f"weights cannot reach one. Raise max_single_position or widen the universe."
            )
        if float(self.lower_bounds.sum()) > 1.0 + 1e-9:
            notes.append(
                f"the fixed allocations sum to {float(self.lower_bounds.sum()):.4f}, which exceeds one."
            )
        return notes

    def indicator_is_populated(self, block: ConstraintBlock) -> np.ndarray:
        return block.indicator.sum(axis=1) > 0


#: Dimension name, the vocabulary it uses, and how to read the label off a building block. The order of
#: this tuple is the block order of section 4.2 and must not be changed: it fixes the row positions.
_CLASSIFICATIONS: tuple[tuple[str, str, Callable[[BuildingBlock], str]], ...] = (
    ("currency", "currency", lambda b: b.currency),
    ("region", "region", lambda b: b.region_geo),
    ("role", "role", lambda b: b.role),
    ("capital_type", "capital_type", lambda b: b.capital_type),
    ("liquidity", "liquidity", lambda b: b.liquidity),
    # ESG is inserted here, as a single row, by build_constraints.
    ("phase", "phase", lambda b: b.economic_phase),
    ("asset_class", "asset_class", lambda b: b.asset_class),
)

#: Where the ESG row sits within the block order.
_ESG_AFTER: str = "liquidity"


def build_constraints(
    mandate: Mandate,
    blocks: Sequence[BuildingBlock],
    config: Config,
) -> ConstraintSystem:
    """Assemble the constraint system for one mandate and universe.

    `blocks` must be in the mandate's universe order: that order fixes the meaning of every column of
    `A` and every entry of the weight vector.
    """
    n = len(blocks)
    if n == 0:
        raise ValueError("cannot build constraints for an empty universe")

    configured_order = list(config.get("constraints.block_order"))
    expected_order = [name for name, _, _ in _CLASSIFICATIONS]
    expected_with_esg = expected_order[:expected_order.index(_ESG_AFTER) + 1] + ["esg"] + \
        expected_order[expected_order.index(_ESG_AFTER) + 1:]
    if configured_order != expected_with_esg:
        raise ValueError(
            f"constraints.block_order is {configured_order}, but the assembler implements "
            f"{expected_with_esg}. The rows of A are positional, so the two must agree exactly or every "
            f"bound would mean something other than what the mandate set."
        )

    a_rows: list[np.ndarray] = []
    b_values: list[float] = []
    row_labels: list[str] = []
    assembled: list[ConstraintBlock] = []
    esg_row_index = -1
    esg_row = np.zeros(n, dtype=float)

    for dimension, vocabulary_name, getter in _CLASSIFICATIONS:
        vocabulary = config.vocabularies.by_name(vocabulary_name)
        indicator = _indicator(blocks, vocabulary, getter)
        bounds = mandate.bounds_for(dimension, vocabulary)
        lower = np.asarray([bd.lower for bd in bounds], dtype=float)
        upper = np.asarray([bd.upper for bd in bounds], dtype=float)

        # The upper half: +block x <= upper.
        upper_rows = tuple(range(len(a_rows), len(a_rows) + len(vocabulary)))
        for k, label in enumerate(vocabulary.labels):
            a_rows.append(indicator[k].copy())
            b_values.append(float(upper[k]))
            row_labels.append(f"{dimension}:{label}:upper")

        # The lower half: -block x <= -lower.
        lower_rows = tuple(range(len(a_rows), len(a_rows) + len(vocabulary)))
        for k, label in enumerate(vocabulary.labels):
            a_rows.append(-indicator[k])
            b_values.append(-float(lower[k]))
            row_labels.append(f"{dimension}:{label}:lower")

        assembled.append(
            ConstraintBlock(
                dimension=dimension,
                vocabulary=vocabulary,
                indicator=indicator,
                lower=lower,
                upper=upper,
                upper_rows=upper_rows,
                lower_rows=lower_rows,
            )
        )

        if dimension == _ESG_AFTER:
            # A genuine weighted-average floor: -esg . x <= -esg_min.
            esg_row = np.asarray([float(block.esg) for block in blocks], dtype=float)
            esg_row_index = len(a_rows)
            a_rows.append(-esg_row)
            b_values.append(-float(mandate.esg_min))
            row_labels.append("esg:portfolio:lower")

    a = np.vstack(a_rows) if a_rows else np.zeros((0, n))
    b = np.asarray(b_values, dtype=float)

    lower_bounds, upper_bounds = _instrument_bounds(mandate, blocks)

    return ConstraintSystem(
        a=a,
        b=b,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        blocks=tuple(assembled),
        esg_row=esg_row,
        esg_min=float(mandate.esg_min),
        esg_row_index=esg_row_index,
        row_labels=tuple(row_labels),
    )


def _indicator(
    blocks: Sequence[BuildingBlock],
    vocabulary: Vocabulary,
    getter: Callable[[BuildingBlock], str],
) -> np.ndarray:
    """A k by n matrix with 1 where instrument j is in category k.

    Every instrument lands in exactly one category per dimension, which is checked: an instrument in none
    would have its weight escape the dimension's bounds entirely, and one in two would be double counted.
    """
    matrix = np.zeros((len(vocabulary), len(blocks)), dtype=float)
    for j, block in enumerate(blocks):
        matrix[vocabulary.index(getter(block)), j] = 1.0
    per_instrument = matrix.sum(axis=0)
    if not np.allclose(per_instrument, 1.0):
        wrong = [
            (blocks[j].bb_id, blocks[j].name, float(per_instrument[j]))
            for j in np.flatnonzero(~np.isclose(per_instrument, 1.0))
        ]
        raise ValueError(
            f"every instrument must fall in exactly one {vocabulary.name}; these do not: {wrong}"
        )
    return matrix


def _instrument_bounds(
    mandate: Mandate,
    blocks: Sequence[BuildingBlock],
) -> tuple[np.ndarray, np.ndarray]:
    """Per-instrument `(lower, upper)`.

    A fixed allocation pins the position by setting both ends to it. Otherwise the lower bound is zero,
    which forbids a short, and the upper bound is the mandate's maximum single position.
    """
    lower = np.zeros(len(blocks), dtype=float)
    upper = np.full(len(blocks), float(mandate.max_single_position), dtype=float)
    for j, block in enumerate(blocks):
        pinned = mandate.fixed_allocations.get(block.bb_id)
        if pinned is not None and pinned != 0.0:
            lower[j] = float(pinned)
            upper[j] = float(pinned)
    return lower, upper


def realised_exposures(
    weights: np.ndarray,
    system: ConstraintSystem,
) -> dict[str, dict[str, float]]:
    """The portfolio's actual exposure per dimension and category.

    This is what a reader checks a bound against, and it is computed from the same indicator matrices the
    constraints were built from rather than recomputed from the blocks, so a discrepancy between reported
    exposure and applied constraint is impossible.
    """
    x = np.asarray(weights, dtype=float).ravel()
    out: dict[str, dict[str, float]] = {}
    for block in system.blocks:
        out[block.dimension] = {
            label: float(block.indicator[k] @ x)
            for k, label in enumerate(block.vocabulary.labels)
        }
    return out


def binding_constraints(
    weights: np.ndarray,
    system: ConstraintSystem,
    tolerance: float = 1e-6,
) -> tuple[BindingConstraint, ...]:
    """Which constraints are active at the solution.

    Reported with every allocation because a weight is only interpretable alongside the limit that
    produced it: an exposure sitting exactly on its ceiling was chosen by the bound, not by the fit.
    """
    x = np.asarray(weights, dtype=float).ravel()
    slack = system.b - system.a @ x
    active = np.flatnonzero(np.abs(slack) <= tolerance)

    found: list[BindingConstraint] = []
    for row in active:
        label = system.row_labels[row]
        dimension, category, side = label.split(":")
        realised = float(system.a[row] @ x)
        bound = float(system.b[row])
        if side == "lower":
            # Stored negated, so report the mandate's own numbers.
            realised, bound = -realised, -bound
        found.append(
            BindingConstraint(
                dimension=dimension,
                category=category,
                side=side,
                bound=bound,
                realised=realised,
            )
        )
    return tuple(found)
