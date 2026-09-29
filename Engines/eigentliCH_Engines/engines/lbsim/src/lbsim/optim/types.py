"""The optimiser's handshake with the rest of lbsim (agent C with agent B2, 29.09.2026). No casadi here.

``PlanProblem`` is everything the NLP needs; ``ControlPath`` is what the plan assumes over time and what B2's
Monte Carlo simulates for the out-of-sample chance; ``PlanOutcome`` is what ``lbsim.optim.solve`` returns. The
field names are fixed: B2 builds the worker harness against them.

Units. CHF amounts, decimal rates a year, annualised log returns, chances in [0, 1], ages and times in years.

Money in a ``ControlPath`` (``money_basis``):

``today_indexed``  C, m_E and m_N are in today's francs and each path indexes them with its own price level
                   (``exp`` of the cumulated per-state log inflation), which is the pass-through of 1.0 for
                   spending (LBSIM-07). p_A (amortisation) is nominal: debt is nominal. Under calibration 1.1.0.
``nominal``        Calibration 1.0.0: no inflation, so both readings coincide.

After the last step (the solved horizon, at most the cap) the last step's controls continue to the end of the
horizon (``after_last_step = "hold_last"``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional

from ..contracts import Calibration

#: The draft's control vector, in the draft's order (``optim.symbolic``: tau_Y, tau_E, tau_N, tau_H, C, m_E, m_N,
#: p_A, theta). theta is fixed at 1 under the allocation market (LBSIM-07) and keeps its slot.
CONTROL_NAMES: tuple[str, ...] = ("tau_Y", "tau_E", "tau_N", "tau_H", "C", "m_E", "m_N", "p_A", "theta")

GoalKind = Literal["home", "retirement", "capital", "fi", "company"]
GoalMeasure = Literal["drawable", "deposit_eligible", "retirement_capital"]
FailureKind = Literal["timed_out", "cancelled", "solver"]
Outcome = Literal["solved", "goal_not_fundable"]


@dataclass(frozen=True)
class MarketInputs:
    """The market the NLP's scenarios are drawn from (LBSIM-07), for the base Regime.

    ``kind = "allocation"`` (calibration 1.1.0): ``log_returns[s]`` is the portfolio's annualised log return in
    state s (renormalised Allocation weights times fmre's per-state profiles), ``log_inflation[s]`` fmre's CHF log
    inflation in state s, ``state_distribution[y]`` the 25 state probabilities of simulated year ``y + 1`` (year 1 is
    ``Allocation.curves.regime``, then the linear reversion to the long-run distribution). A horizon longer than
    the list uses the last entry. ``kind = "draft"`` (calibration 1.0.0): the draft's Gaussian market and tilt; the
    three tuples are empty.
    """

    kind: Literal["draft", "allocation"]
    log_returns: tuple[float, ...] = ()
    log_inflation: tuple[float, ...] = ()
    state_distribution: tuple[tuple[float, ...], ...] = ()
    regime_id: Optional[str] = None
    return_set_id: Optional[str] = None


@dataclass(frozen=True)
class GoalInput:
    """One dated goal. lbsim's goals (``home``, ``retirement``, ``capital``) are a target on a measure: the
    target in both bases and the basis it was stated in (LBSIM-09), as the paths artefact states it. The draft's
    kinds (``fi``, ``company``, and ``home``/``retirement`` with ``measure=None``) carry the draft's ``GoalSpec``
    parameters in ``params`` instead; they exist for the reproduction of the draft under calibration 1.0.0.

    ``planned_saving_chf_per_year`` is the fast half's free cash for the goal (``saving_need[].free_cash``): the
    saving at which the zero-return terminal requirement is read for a goal beyond the solve cap (section 5).
    """

    goal_id: str
    kind: GoalKind
    horizon_years: float
    confidence: float
    measure: Optional[GoalMeasure] = None
    target_nominal_chf: Optional[float] = None
    target_real_chf: Optional[float] = None
    amount_basis: Literal["today", "future"] = "future"
    planned_saving_chf_per_year: float = 0.0
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanProblem:
    """Everything the NLP needs.

    ``submission`` is B1's adapter submission (``lbsim.adapter.adapt(...).submission``): the state, the draft's
    ``params`` block and the raw answers. ``calibration`` carries the optimiser block (``calibration.optimiser``:
    confidence, M_opt, M_eval, n_starts, restore_starts, max_iter, seed_retries, cvar_tol, grid, grid_rule), the
    property parameters (``calibration.property``, also ``problem.property_parameters``) and the market
    pass-throughs (``calibration.market``). ``horizon_years`` is the resolved total horizon (LBSIM-18); the NLP
    solves at most
    ``max_solve_horizon_years`` of it. ``seed`` is the in-sample seed; redraws use ``seed + 1000 k``, the
    out-of-sample chance ``seed + 500 000`` (section 3.9). ``n_out_of_sample`` paths are simulated for it
    (None: ``calibration.optimiser.M_eval``).
    """

    submission: Mapping[str, Any]
    calibration: Calibration
    market: MarketInputs
    goal: GoalInput
    horizon_years: float
    seed: int
    extra_goals: tuple[GoalInput, ...] = ()
    max_solve_horizon_years: float = 20.0
    n_out_of_sample: Optional[int] = None
    client_ref: Optional[str] = None
    life_balance_sheet_id: Optional[str] = None
    paths_artefact_id: Optional[str] = None

    @property
    def optimiser(self):
        return self.calibration.optimiser

    @property
    def property_parameters(self):
        return self.calibration.property

    @property
    def goals(self) -> tuple[GoalInput, ...]:
        return (self.goal, *self.extra_goals)


@dataclass(frozen=True)
class ControlStep:
    t_years: float
    dt_years: float
    #: The nine controls by ``CONTROL_NAMES``.
    controls: Mapping[str, float]


@dataclass(frozen=True)
class ControlPath:
    """The planned controls step by step (the variable grid), from t = 0."""

    steps: tuple[ControlStep, ...]
    horizon_years: float
    money_basis: Literal["today_indexed", "nominal"]
    after_last_step: Literal["hold_last"] = "hold_last"

    def at(self, t_years: float) -> Mapping[str, float]:
        """The controls in force at time ``t_years`` (the step that contains it; the last beyond it)."""
        for s in self.steps:
            if t_years < s.t_years + s.dt_years - 1e-12:
                return s.controls
        return self.steps[-1].controls


@dataclass(frozen=True)
class ActionNow:
    """``lbsim-plan@1.0.0`` ``action_now``: the first step's controls in plain units."""

    work_share: float
    learning_hours_per_week: float
    network_hours_per_week: float
    rest_hours_per_week: float
    consumption_chf_per_year: float
    saving_chf_per_year: float
    education_spend_chf_per_year: float
    network_spend_chf_per_year: float
    amortisation_chf_per_year: float


@dataclass(frozen=True)
class PlanChance:
    in_sample: float
    out_of_sample: float
    n_out_of_sample: int
    seed_out: int


@dataclass(frozen=True)
class Reachable:
    amount_chf: float
    at_confidence: float


@dataclass(frozen=True)
class ExchangeRate:
    winner: Literal["networking", "overtime", "undetermined"]
    ratio: Optional[float]
    #: The dominant lever's control name (``tau_N`` or ``tau_Y``) when one so outweighs the other that a multiple
    #: means nothing, else None.
    dominant: Optional[str]


@dataclass(frozen=True)
class Costates:
    W: float
    E: float
    N: float
    H: float


@dataclass(frozen=True)
class PlanHorizon:
    solved_years: float
    total_years: float
    beyond_cap_rule: Optional[Literal["zero_return_terminal"]]


@dataclass(frozen=True)
class SolverRecord:
    return_status: str
    iterations: int
    wall_clock_s: float
    seed: int
    seed_attempt: int
    M_opt: int
    grid: tuple[float, ...]
    casadi_version: str
    ipopt_version: Optional[str]


@dataclass(frozen=True)
class PlanResult:
    """The figures of ``lbsim-plan@1.0.0`` (section 3.4) that the optimiser makes. B2 adds the header, the
    framing, the provenance and the ids when it writes the artefact."""

    outcome: Outcome
    goal_id: str
    goal_kind: str
    confidence: float
    extra_goals: tuple[str, ...]
    action_now: ActionNow
    chance: PlanChance
    shortfall_cvar_chf: float
    reachable: Optional[Reachable]
    exchange_rate: ExchangeRate
    costates: Costates
    control_path: ControlPath
    horizon: PlanHorizon
    solver: SolverRecord
    #: Every seed the run used, in order (in-sample attempts, then the out-of-sample seed).
    seeds_used: tuple[int, ...]


@dataclass(frozen=True)
class PlanOutcome:
    """What ``solve`` returns. ``status == "succeeded"`` carries a ``result``; ``"failed"`` carries a
    ``failure_kind`` and no figures at all (no figure from a non-converged or timed-out solve)."""

    status: Literal["succeeded", "failed"]
    failure_kind: Optional[FailureKind] = None
    result: Optional[PlanResult] = None
    #: A plain sentence for a failed run.
    error: Optional[str] = None
    wall_clock_s: float = 0.0
    #: Every seed tried (for the record even when the run failed).
    seeds_used: tuple[int, ...] = ()
    #: Diagnostics for curators and tests (return statuses, iteration counts, s_star). Never client figures.
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == "succeeded" and (self.result is None or self.failure_kind is not None):
            raise ValueError("a succeeded plan run carries a result and no failure kind")
        if self.status == "failed" and (self.result is not None or self.failure_kind is None):
            raise ValueError("a failed plan run carries a failure kind and no result")
