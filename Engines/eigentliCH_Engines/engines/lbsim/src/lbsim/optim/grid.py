"""The optimiser's time grid (section 5). No casadi.

Two rules, both read from ``calibration.optimiser``:

``draft_single_step``  the draft's ``cases.run_case``: one step for the whole horizon, 0.5 years up to ten years
                       and 1.0 beyond (the first rung whose ``until`` holds the horizon), ``K = round(H / dt)``,
                       and a goal at node ``max(1, min(K, round(h / dt)))``. No cap. Calibration 1.0.0.
``variable``           0.5-year steps while ``t < 10``, 1.0-year steps while ``t < 20``, the grid ending at the
                       nearest node to the horizon and never past the cap (``min(max_solve_horizon_years, last
                       rung)``, 20 years). A goal sits at the node nearest its date; a goal beyond the last node
                       is a terminal requirement at it (``zero_return_terminal``). Calibration 1.1.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

_TOL = 1e-9


@dataclass(frozen=True)
class Grid:
    rule: str
    dts: tuple[float, ...]
    #: Node times, ``times[0] = 0`` and ``times[k + 1] = times[k] + dts[k]``.
    times: tuple[float, ...]
    #: The horizon the NLP covers (the cap applied), and the total horizon asked for.
    solved_years: float
    total_years: float
    capped: bool

    @property
    def K(self) -> int:
        return len(self.dts)

    def goal_node(self, horizon_years: float) -> int:
        """The node a goal dated ``horizon_years`` is tested at (1..K)."""
        K = self.K
        if self.rule == "draft_single_step":
            dt = self.dts[0]
            return max(1, min(K, int(round(horizon_years / dt))))
        if horizon_years >= self.times[-1] - _TOL:
            return K
        best = min(range(1, K + 1), key=lambda k: (abs(self.times[k] - horizon_years), k))
        return best

    def beyond(self, horizon_years: float) -> float:
        """Years a goal lies beyond the last node (0 when it is inside the solved horizon)."""
        return max(0.0, float(horizon_years) - self.times[-1]) if self.rule == "variable" else 0.0


def _rung_dt(rungs: Sequence[tuple[float, float]], t: float) -> float:
    for until, dt in rungs:
        if t < until - _TOL:
            return float(dt)
    return float(rungs[-1][1])


def build(horizon_years: float, rungs: Sequence[tuple[float, float]], rule: str, *,
          cap: Optional[float] = None) -> Grid:
    """The grid for a horizon of ``horizon_years`` (the latest goal, or the resolved horizon)."""
    H = float(horizon_years)
    if H <= 0:
        raise ValueError("the optimiser needs a positive horizon")
    rungs = [(float(u), float(d)) for u, d in rungs]
    if rule == "draft_single_step":
        dt = next((d for u, d in rungs if H <= u + _TOL), rungs[-1][1])
        K = max(1, int(round(H / dt)))
        dts = (dt,) * K
        times = tuple(k * dt for k in range(K + 1))
        return Grid(rule=rule, dts=dts, times=times, solved_years=min(H, times[-1]) if K else H,
                    total_years=H, capped=False)
    if rule != "variable":
        raise ValueError(f"unknown grid rule {rule!r}")
    limit = rungs[-1][0]
    if cap is not None:
        limit = min(limit, float(cap))
    target = min(H, limit)
    dts: list[float] = []
    t = 0.0
    while True:
        dt = _rung_dt(rungs, t)
        if dts and t + 0.5 * dt > target + _TOL:
            break
        if t + dt > limit + _TOL:
            break
        dts.append(dt)
        t += dt
    times = [0.0]
    for dt in dts:
        times.append(times[-1] + dt)
    return Grid(rule=rule, dts=tuple(dts), times=tuple(times), solved_years=times[-1], total_years=H,
                capped=H > times[-1] + _TOL and H > limit - _TOL)
