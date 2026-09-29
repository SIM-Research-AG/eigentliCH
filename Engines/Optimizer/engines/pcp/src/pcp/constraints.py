"""The 75-row constraint block, ``A x <= b``, the budget ``sum(x) = 1`` and per-instrument bounds. Pure.

**Row order is the contract** (Manual section 15.2, "Where diversification actually lives"). Dimension by
dimension, each bucket takes two adjacent rows, its floor then its ceiling; ESG is one floor row with no
ceiling::

    rows  1-20  currency (10)      rows 43-48  capital type (3)    rows 58-65  phase (4)
    rows 21-34  region (7)         rows 49-56  liquidity (4)       rows 66-75  asset class (5)
    rows 35-42  role (4)           row  57     ESG (floor only)

A floor row is ``-indicator . x <= -lower``, a ceiling row ``indicator . x <= upper``. The dimension start
rows and row 57 are the draft's and MATLAB's; the pairing inside a dimension is the Manual's (the draft
grouped all ceilings, then all floors). The solution does not depend on it (golden layer A reproduces under
either, to 3e-14), the row numbers reported for a binding constraint do (PCP-10).

Per-instrument bounds: lower zero, upper the mandate's maximum single position; a non-zero fixed
allocation pins both ends to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .contracts import DIMENSIONS, BindingRow, ConstraintRow, Vocabularies

#: ESG sits after this dimension, as row 57.
ESG_AFTER = "liquidity"

#: Manual section 15.2 and Step 25: the first row of each dimension, and the total.
STARTS = {"currency": 1, "region": 21, "role": 35, "capital_type": 43, "liquidity": 49, "esg": 57,
          "phase": 58, "asset_class": 66}
N_ROWS = 75


class LayoutError(ValueError):
    """The block does not have the layout the Manual fixes; every bound would mean something else."""


def verify_layout(rows: Sequence[ConstraintRow]) -> None:
    """Refuse a block whose rows are not where the Manual puts them (section 15.7 test 1).

    Exactly 75 rows; each dimension starts at its stated row; within a dimension every bucket is a floor
    row followed by its ceiling row; ESG (row 57) is the only one-sided row.
    """
    if len(rows) != N_ROWS:
        raise LayoutError(f"the constraint block has {len(rows)} rows, not {N_ROWS}")
    starts: dict[str, int] = {}
    for r in rows:
        starts.setdefault(r.dimension, r.row)
    if starts != STARTS:
        raise LayoutError(f"the dimensions start at {starts}, not {STARTS}")
    one_sided = [r.row for r in rows if r.dimension == "esg"]
    if one_sided != [57] or rows[56].side != "floor":
        raise LayoutError(f"row 57 must be the ESG floor and the only one-sided row; ESG rows are {one_sided}")
    pairs = [r for r in rows if r.dimension != "esg"]
    for floor_row, ceiling_row in zip(pairs[0::2], pairs[1::2]):
        if (floor_row.side, ceiling_row.side) != ("floor", "ceiling") or \
                (floor_row.dimension, floor_row.category) != (ceiling_row.dimension, ceiling_row.category):
            raise LayoutError(f"rows {floor_row.row} and {ceiling_row.row} are not the floor and ceiling of one bucket")


@dataclass(frozen=True)
class Block:
    dimension: str
    labels: tuple[str, ...]
    indicator: np.ndarray        # (k, n): 1 where instrument j is in bucket k
    lower: np.ndarray            # (k,)
    upper: np.ndarray            # (k,)


@dataclass(frozen=True)
class ConstraintSystem:
    a: np.ndarray
    b: np.ndarray
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    blocks: tuple[Block, ...]
    esg_row: np.ndarray
    esg_min: float
    rows: tuple[ConstraintRow, ...]

    @property
    def n_rows(self) -> int:
        return int(self.a.shape[0])

    def feasibility_problems(self) -> list[str]:
        """Structural infeasibilities, found before any solve (the engine page: infeasible mandates fail
        at ``/validate``, not in the solver)."""
        problems: list[str] = []
        for block in self.blocks:
            populated = block.indicator.sum(axis=1) > 0
            reachable = float(block.upper[populated].sum())
            if reachable < 1.0 - 1e-9:
                problems.append(f"the {block.dimension} ceilings sum to {reachable:.4f} over the buckets the "
                                f"universe populates, so the weights cannot reach one")
            demanded = float(block.lower.sum())
            if demanded > 1.0 + 1e-9:
                problems.append(f"the {block.dimension} floors sum to {demanded:.4f}, which exceeds one")
            empty = [block.labels[k] for k in range(len(block.labels))
                     if block.lower[k] > 1e-12 and not populated[k]]
            if empty:
                problems.append(f"the mandate sets a {block.dimension} floor on {empty}, but no instrument "
                                f"of the universe is in those buckets")
        if float(self.upper_bounds.sum()) < 1.0 - 1e-9:
            problems.append(f"the per-instrument ceilings sum to {float(self.upper_bounds.sum()):.4f}, so "
                            "the weights cannot reach one; raise max_single_position or widen the universe")
        if float(self.lower_bounds.sum()) > 1.0 + 1e-9:
            problems.append(f"the fixed allocations sum to {float(self.lower_bounds.sum()):.4f}")
        # A weighted average cannot exceed the highest score in the universe.
        if self.esg_min > float(self.esg_row.max()) + 1e-12:
            problems.append(f"esg_min {self.esg_min} exceeds the highest ESG score in the universe "
                            f"({float(self.esg_row.max())})")
        # One bucket against the per-instrument bounds (PCP-21): a floor above what the bucket's instruments
        # can hold together, or a ceiling below what its fixed allocations already hold.
        for block in self.blocks:
            for k, label in enumerate(block.labels):
                members = block.indicator[k] > 0
                count = int(members.sum())
                if not count:
                    continue
                capacity = float(self.upper_bounds[members].sum())
                if block.lower[k] > capacity + FEASIBILITY_TOL:
                    problems.append(
                        f"the mandate sets a {block.dimension} floor of {block.lower[k]:.4f} on {label}, but the "
                        f"universe's {count} {label} instrument{'s' if count != 1 else ''} can hold at most "
                        f"{capacity:.4f} together (each capped at its per-instrument ceiling); add {label} "
                        "instruments to the universe, raise max_single_position or lower the floor")
                pinned = float(self.lower_bounds[members].sum())
                if block.upper[k] < pinned - FEASIBILITY_TOL:
                    problems.append(f"the mandate caps {block.dimension} {label} at {block.upper[k]:.4f}, but its "
                                    f"fixed allocations already hold {pinned:.4f} there")
        if not problems:
            problems.extend(self.joint_problems())
        return problems

    def reduced(self) -> tuple[np.ndarray, np.ndarray]:
        """``(A, b)`` without the rows the budget and the per-instrument bounds already imply (PCP-21).

        A floor at zero over non-negative coefficients holds for any ``x >= 0``, and a ceiling at one over
        coefficients in [0, 1] holds whenever ``x >= 0`` and ``sum(x) = 1``; an empty bucket's rows are all
        zero. The feasible set is the same with or without them, but SLSQP's subproblem degenerates on
        them (in the failing mandates of 29.09.2026 about 58 of the 75 rows, reported as "Inequality
        constraints incompatible" on a feasible block). Used by the rescue only; the calibrated solve keeps
        the full block, as the draft passed it.
        """
        keep = []
        for i, row in enumerate(self.rows):
            coeffs = self.a[i]
            implied = ((row.side == "floor" and self.b[i] >= -1e-15 and bool(np.all(coeffs <= 0.0))) or
                       (row.side == "ceiling" and self.b[i] >= 1.0 - 1e-15 and bool(np.all((coeffs >= 0.0) & (coeffs <= 1.0)))))
            if not implied:
                keep.append(i)
        return self.a[keep], self.b[keep]

    def joint_problems(self) -> list[str]:
        """Whether the whole block admits weights at all, by a phase-1 linear programme (PCP-21).

        The checks above look at one dimension or one bucket at a time. Rows of different dimensions can
        conflict as well (an equity floor above the Gain ceiling when every equity instrument is a Gain
        instrument). This finds it before any solve and names one smallest relaxation of the rows that
        would remove the conflict, and the rows held at their bounds against it.
        """
        p1 = phase_one(self)
        if p1.feasible:
            return []
        if not p1.relaxation:
            return [f"no weights within the per-instrument bounds sum to one ({p1.status})"]
        short = "; ".join(f"{_describe(r)} misses by {amount:.4f}" for r, amount in p1.relaxation)
        text = ("the mandate is infeasible as a whole: no weights meet every row of the constraint block "
                f"together, although each dimension is feasible on its own. One smallest relaxation: {short}")
        if p1.held:
            text += "; at that point, held at their bounds: " + "; ".join(_describe(r) for r in p1.held)
        if p1.capped:
            text += f"; {p1.capped} instrument{'s' if p1.capped != 1 else ''} at the per-instrument ceiling"
        return [text]


#: Constraint rows, the budget and the per-instrument bounds are met to this (PCP-21).
FEASIBILITY_TOL = 1e-6


def _describe(row: ConstraintRow) -> str:
    if row.dimension == "esg":
        return f"the ESG floor {row.bound:.4f} (row {row.row})"
    return f"{row.dimension} {row.category} {row.side} {row.bound:.4f} (row {row.row})"


def _nontrivial(system: "ConstraintSystem") -> np.ndarray:
    """Rows that bound anything: a floor above zero or a ceiling below one (the ESG row when esg_min > 0)."""
    return np.asarray([(r.side == "floor" and r.bound > 1e-12) or (r.side == "ceiling" and r.bound < 1.0 - 1e-12)
                       for r in system.rows])


@dataclass(frozen=True)
class PhaseOne:
    """The phase-1 linear programme over ``A x <= b``, ``sum(x) = 1`` and the per-instrument bounds.

    ``point`` is a feasible point as far inside the rows that bind anything as the block allows (the
    largest common margin), ``None`` when the block is infeasible; then ``relaxation`` is one smallest
    total relaxation of the rows (row, amount), ``held`` the other non-trivial rows at their bounds at
    that relaxed point and ``capped`` the number of instruments at their ceiling there.
    """

    feasible: bool
    point: "np.ndarray | None"
    margin: float
    relaxation: tuple[tuple[ConstraintRow, float], ...]
    held: tuple[ConstraintRow, ...]
    capped: int
    status: str


def phase_one(system: ConstraintSystem) -> PhaseOne:
    from scipy.optimize import linprog

    a, b = system.a, system.b
    m, n = a.shape
    bounds = list(zip(system.lower_bounds.tolist(), system.upper_bounds.tolist()))
    # Elastic programme: minimise the total violation v of the rows, the budget and the bounds kept hard.
    elastic = linprog(np.concatenate([np.zeros(n), np.ones(m)]),
                      A_ub=np.hstack([a, -np.eye(m)]), b_ub=b,
                      A_eq=np.hstack([np.ones((1, n)), np.zeros((1, m))]), b_eq=[1.0],
                      bounds=bounds + [(0.0, None)] * m, method="highs")
    if elastic.status != 0:
        return PhaseOne(False, None, 0.0, (), (), 0, str(elastic.message))
    x, v = elastic.x[:n], elastic.x[n:]
    if float(v.sum()) > FEASIBILITY_TOL:
        slack = b - a @ x
        nontrivial = _nontrivial(system)
        relaxed = tuple((system.rows[i], float(v[i])) for i in np.flatnonzero(v > FEASIBILITY_TOL))
        held = tuple(system.rows[i] for i in np.flatnonzero((np.abs(slack) <= FEASIBILITY_TOL) & nontrivial)
                     if v[i] <= FEASIBILITY_TOL)
        capped = int(np.sum((x >= system.upper_bounds - FEASIBILITY_TOL) & (system.upper_bounds > 0)))
        return PhaseOne(False, None, 0.0, relaxed, held, capped, "infeasible")
    # Largest common margin t on every row that binds anything and on every free per-instrument bound.
    rows = np.flatnonzero(_nontrivial(system))
    free = np.flatnonzero(system.upper_bounds - system.lower_bounds > 1e-12)
    a_t = [np.hstack([a[rows], np.ones((len(rows), 1))]),
           np.hstack([-np.eye(n)[free], np.ones((len(free), 1))]),
           np.hstack([np.eye(n)[free], np.ones((len(free), 1))])]
    b_t = np.concatenate([b[rows], -system.lower_bounds[free], system.upper_bounds[free]])
    central = linprog(np.concatenate([np.zeros(n), [-1.0]]), A_ub=np.vstack(a_t), b_ub=b_t,
                      A_eq=np.hstack([np.ones((1, n)), [[0.0]]]), b_eq=[1.0],
                      bounds=bounds + [(0.0, 1.0)], method="highs")
    if central.status == 0:
        return PhaseOne(True, np.asarray(central.x[:n], dtype=float), float(central.x[n]), (), (), 0, "feasible")
    return PhaseOne(True, np.asarray(x, dtype=float), 0.0, (), (), 0, "feasible")


def max_violation(x: np.ndarray, system: ConstraintSystem) -> float:
    """The largest breach at ``x`` of a row, the budget or a per-instrument bound (zero when none)."""
    x = np.asarray(x, dtype=float)
    return float(max(0.0, float(np.max(system.a @ x - system.b)), abs(float(x.sum()) - 1.0),
                     float(np.max(system.lower_bounds - x)), float(np.max(x - system.upper_bounds))))


def layout(vocabularies: Vocabularies) -> tuple[ConstraintRow, ...]:
    """The row layout for a vocabulary set, with every bound at its default (floor 0, ceiling 1, ESG 0)."""
    rows: list[ConstraintRow] = []
    for dimension in DIMENSIONS:
        for label in vocabularies.of(dimension):
            rows.append(ConstraintRow(row=len(rows) + 1, dimension=dimension, category=label,
                                      side="floor", bound=0.0))
            rows.append(ConstraintRow(row=len(rows) + 1, dimension=dimension, category=label,
                                      side="ceiling", bound=1.0))
        if dimension == ESG_AFTER:
            rows.append(ConstraintRow(row=len(rows) + 1, dimension="esg", category="portfolio",
                                      side="floor", bound=0.0))
    return tuple(rows)


def build(labels: Mapping[str, Sequence[str]], esg: Sequence[float], vocabularies: Vocabularies,
          bounds: Mapping[str, Mapping[str, tuple[float, float]]], esg_min: float,
          max_single_position: float, fixed: Sequence[float]) -> ConstraintSystem:
    """Assemble the system for one universe.

    ``labels[dimension][j]`` is instrument j's bucket (already classified); ``fixed[j]`` its pinned weight
    (0 for none). Every instrument must fall in exactly one bucket per dimension.
    """
    n = len(esg)
    if n == 0:
        raise ValueError("cannot build constraints for an empty universe")
    a_rows: list[np.ndarray] = []
    b_values: list[float] = []
    rows: list[ConstraintRow] = []
    blocks: list[Block] = []
    esg_row = np.asarray(esg, dtype=float)

    for dimension in DIMENSIONS:
        vocab = vocabularies.of(dimension)
        indicator = np.zeros((len(vocab), n))
        for j, label in enumerate(labels[dimension]):
            indicator[vocab.index(label), j] = 1.0
        if not np.allclose(indicator.sum(axis=0), 1.0):
            raise ValueError(f"every instrument must fall in exactly one {dimension} bucket")
        declared = bounds.get(dimension, {})
        unknown = sorted(set(declared) - set(vocab))
        if unknown:
            raise ValueError(f"the mandate bounds {dimension} buckets {unknown}, which are not in the "
                             f"{dimension} vocabulary {list(vocab)}")
        lower = np.asarray([declared.get(l, (0.0, 1.0))[0] for l in vocab], dtype=float)
        upper = np.asarray([declared.get(l, (0.0, 1.0))[1] for l in vocab], dtype=float)
        for k, label in enumerate(vocab):
            a_rows.append(-indicator[k]); b_values.append(-float(lower[k]))
            rows.append(ConstraintRow(row=len(rows) + 1, dimension=dimension, category=label,
                                      side="floor", bound=float(lower[k])))
            a_rows.append(indicator[k].copy()); b_values.append(float(upper[k]))
            rows.append(ConstraintRow(row=len(rows) + 1, dimension=dimension, category=label,
                                      side="ceiling", bound=float(upper[k])))
        blocks.append(Block(dimension, tuple(vocab), indicator, lower, upper))
        if dimension == ESG_AFTER:
            a_rows.append(-esg_row); b_values.append(-float(esg_min))
            rows.append(ConstraintRow(row=len(rows) + 1, dimension="esg", category="portfolio",
                                      side="floor", bound=float(esg_min)))

    verify_layout(rows)
    fixed_arr = np.asarray(fixed, dtype=float)
    lower_bounds = np.where(fixed_arr != 0.0, fixed_arr, 0.0)
    upper_bounds = np.where(fixed_arr != 0.0, fixed_arr, float(max_single_position))
    return ConstraintSystem(a=np.vstack(a_rows), b=np.asarray(b_values), lower_bounds=lower_bounds,
                            upper_bounds=upper_bounds, blocks=tuple(blocks), esg_row=esg_row,
                            esg_min=float(esg_min), rows=tuple(rows))


def binding(x: np.ndarray, system: ConstraintSystem, tolerance: float) -> tuple[BindingRow, ...]:
    """The rows active at ``x``, with the mandate's own numbers (floors reported un-negated)."""
    x = np.asarray(x, dtype=float)
    slack = system.b - system.a @ x
    out = []
    for i in np.flatnonzero(np.abs(slack) <= tolerance):
        row = system.rows[i]
        realised = float(system.a[i] @ x)
        if row.side == "floor":
            realised = -realised
        out.append(BindingRow(row=row.row, dimension=row.dimension, category=row.category, side=row.side,
                              bound=row.bound, realised=realised))
    return tuple(out)


def exposures(x: np.ndarray, system: ConstraintSystem) -> dict[str, dict[str, float]]:
    x = np.asarray(x, dtype=float)
    return {b.dimension: {label: float(b.indicator[k] @ x) for k, label in enumerate(b.labels)}
            for b in system.blocks}
