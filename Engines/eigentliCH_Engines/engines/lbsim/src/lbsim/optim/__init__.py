"""The plan calculation (agent C): the draft's Route A optimiser, ported with the market adapter of LBSIM-07.

Importing this package does not load casadi (LBSIM-03): ``types`` is plain dataclasses, and ``solve`` imports the
NLP only when it is called. Only optimiser workers call it.

    solve(problem, *, simulate, deadline, should_cancel, progress) -> PlanOutcome

``simulate(problem, controls, n_paths, seed)`` is B2's vectorised Monte Carlo and returns at least
``{"chance", "n_reached", "shortfall_cvar_chf"}``; it gives the out-of-sample chance. ``deadline`` is a
``time.monotonic()`` value for the whole run; ``should_cancel`` is asked between IPOPT solves; ``progress``
receives ``{phase, start, of, seed_attempt, elapsed_s}``.
"""

from __future__ import annotations

from typing import Callable

from .types import (CONTROL_NAMES, ControlPath, ControlStep, GoalInput, MarketInputs, PlanOutcome, PlanProblem,
                    PlanResult)

__all__ = ["CONTROL_NAMES", "ControlPath", "ControlStep", "GoalInput", "MarketInputs", "PlanOutcome",
           "PlanProblem", "PlanResult", "solve"]


def solve(problem: PlanProblem, *, simulate: Callable[[PlanProblem, ControlPath, int, int], dict],
          deadline: float, should_cancel: Callable[[], bool], progress: Callable[[dict], None]) -> PlanOutcome:
    """Solve the plan for ``problem``. Never raises for a solver failure: a failed run is a ``PlanOutcome`` with
    a ``failure_kind`` and no result."""
    from .run import solve as _solve  # noqa: PLC0415 - casadi is loaded here and only here

    return _solve(problem, simulate=simulate, deadline=deadline, should_cancel=should_cancel, progress=progress)
