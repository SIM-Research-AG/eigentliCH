"""Route A: scenario-based finite-horizon NLP with a CVaR chance constraint (spec §10-11, §9.3).

lbsim port (agent C, 29.09.2026) of the draft's ``optim/problem.py``. The formulation, the two phases, the warm
starts, the bounds, the gates and the redraw rule are the draft's; the draft's long measurement notes are in the
draft and are not repeated here (each rule below names its M-number). What the port adds:

- **the grid** (``grid.Grid``): a step length per step instead of one ``dt_opt``; discounting at the node's own
  time. Under the ``draft_single_step`` rule the grid is uniform and every expression is the draft's.
- **the market** (``Market``): ``draft`` keeps the draft's Euler-Maruyama step on the Gaussian shocks and the
  tilt; ``allocation`` uses ``symbolic.allocation_step`` on scenarios drawn from the base Regime's per-state
  returns and inflation (LBSIM-07), with theta fixed at 1 by an equality (its slot and the costate layout stay).
- **the terminal requirement** beyond the solve cap: a goal dated after the last node is tested at the last
  node with the zero-return allowance (the planned saving times the remaining years) added to its measure.
- **the time budget** (``Budget``): ``ipopt.max_wall_time`` is the time left before the run's deadline, the
  deadline and ``should_cancel`` are checked between IPOPT solves, and ``progress`` hears of every solve. A
  timeout or a cancel raises out of the whole solve, so no figure leaves a stopped run.

Multiple-shooting formulation:
  variables   control path U[k] (shared across scenarios: non-anticipativity), states X[m][k] per scenario,
              and the CVaR auxiliaries (VaR z, tail slacks s[m]) per goal.
  objective   sample-average discounted utility of habit-adjusted consumption + leisure x health, plus a
              terminal bequest (eq. 9.2), maximised.
  constraints the step defects (their initial-condition duals are the costates, §10.2-10.3), the time simplex
              and money box, a liquidity floor, per-node state bounds, and one CVaR surrogate per goal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import casadi as ca
import numpy as np

from ..contracts import PropertyParameters
from ..model import dynamics as dyn
from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from . import symbolic as sym
from .grid import Grid
from .market import AllocationScenarios, no_market_params, sample_allocation
from .spec import GoalSpec
from .types import MarketInputs

_EPS = 1e-6
_LEISURE_MIN = 0.05       # M67
_TAU_Y_MAX = 0.70         # M67
_TAU_H_MIN = 0.05         # M67
_GAMMA_V = 0.5            # bounded leisure curvature (finite at 0)
_HABIT_FLOOR: float = 0.05
_STATE_BOUND_SLACK: float = 1.0
#: M77 / M87: both settled off by the draft's full-matrix measurement; pinned by a test.
_ENFORCE_PARTS_LE_WHOLE: bool = False
_SCALE_NLP: bool = False
_CONTROL_FREE_STATES: tuple[int, ...] = (sym.W_R, sym.W_RES, sym.W_HOL, sym.AGE)


def _crra(x, gamma: float):
    xf = ca.fmax(x, _EPS)
    if abs(gamma - 1.0) < 1e-9:
        return ca.log(xf)
    return xf ** (1.0 - gamma) / (1.0 - gamma)


def _state_vec(x0: State, p: Params) -> np.ndarray:
    return np.array([x0.wealth.W_L, x0.wealth.W_R, x0.wealth.D,
                     x0.person.E.aggregate(), x0.person.N, x0.person.H,
                     x0.person.age, float(x0.wealth.W_res or 0.0),
                     x0.wealth.W_hol, x0.wealth.W_P, x0.wealth.W_3a,
                     dyn.habit_of(x0, p)], dtype=float)


def _sample_shocks(M: int, K: int, rho: float, seed: int) -> np.ndarray:
    """Correlated wealth shocks z[m,k] = (z_W, z_R), matching the draft's sim/montecarlo.py."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((M, K, 2))
    zW = z[:, :, 0]
    zR = rho * zW + np.sqrt(max(0.0, 1.0 - rho * rho)) * z[:, :, 1]
    return np.stack([zW, zR], axis=-1)


# --- results --------------------------------------------------------------------------------------------------

@dataclass
class Costates:
    lam_W: float
    lam_E: float
    lam_N: float
    lam_H: float


@dataclass
class ExchangeRate:
    goal: str
    networking_value: float
    overtime_value: float

    _CAP = 5.0

    @property
    def determined(self) -> bool:
        return max(self.networking_value, self.overtime_value) > 0.0

    @property
    def winner(self) -> str:
        if not self.determined:
            return "undetermined"
        return "networking" if self.networking_value >= self.overtime_value else "overtime"

    @property
    def raw_ratio(self) -> float:
        hi, lo = sorted((self.networking_value, self.overtime_value), reverse=True)
        return hi / max(lo, hi * 1e-3) if hi > 0 else 1.0

    @property
    def ratio(self) -> float:
        return min(self.raw_ratio, self._CAP)

    @property
    def dominant(self) -> bool:
        return self.raw_ratio > self._CAP


@dataclass
class SolveResult:
    u0: dict
    costates: Costates
    exchange_rate: ExchangeRate
    p_fi_insample: float
    cvar_shortfall: float
    objective: float
    success: bool
    stats: dict = field(default_factory=dict)
    u_path: list = field(default_factory=list)
    dt_opt: float = 0.5
    #: lbsim: the step lengths of ``u_path`` (the grid).
    dts: tuple = ()


class SolveFailed(RuntimeError):
    """One solve could not be started, for a reason about the SOLVE and not the household (draft)."""


class Stopped(RuntimeError):
    """The run stopped before it could finish: ``kind`` is ``timed_out`` or ``cancelled``. Raised through every
    layer, so nothing computed before the stop is reported."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# --- the market and the time budget -------------------------------------------------------------------------

@dataclass(frozen=True)
class Market:
    """``draft``: the draft's Gaussian market and tilt. ``allocation``: LBSIM-07, with the base Regime's inputs."""

    kind: str = "draft"
    inputs: Optional[MarketInputs] = None
    prop: Optional[PropertyParameters] = None

    def __post_init__(self) -> None:
        if self.kind not in ("draft", "allocation"):
            raise ValueError(f"unknown market {self.kind!r}")
        if self.kind == "allocation" and (self.inputs is None or self.prop is None):
            raise ValueError("the allocation market needs its inputs and the property parameters")


DRAFT_MARKET = Market("draft")


@dataclass
class Budget:
    """The run's clock. ``deadline`` is a ``time.monotonic()`` value (None: no limit)."""

    deadline: Optional[float] = None
    should_cancel: Callable[[], bool] = lambda: False
    progress: Callable[[dict], None] = lambda _event: None
    started: float = field(default_factory=time.monotonic)
    solves: int = 0
    #: Every in-sample seed a solve was started on, so a stopped run still records them.
    seeds: list = field(default_factory=list)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self) -> Optional[float]:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def check(self) -> None:
        """Between IPOPT solves: cancelled or out of time stops the run."""
        if self.should_cancel():
            raise Stopped("cancelled", "The plan calculation was cancelled; no figures are reported.")
        left = self.remaining()
        if left is not None and left <= 0.0:
            raise Stopped("timed_out", "The plan calculation ran out of its time budget; no figures are reported.")

    def before_solve(self, *, phase: str, start: int, of: int, seed_attempt: int) -> None:
        self.check()
        self.progress({"phase": phase, "start": start, "of": of, "seed_attempt": seed_attempt,
                       "elapsed_s": round(self.elapsed(), 3)})

    def ipopt_options(self) -> dict:
        left = self.remaining()
        return {} if left is None else {"ipopt.max_wall_time": max(1.0, float(left))}

    def after_solve(self, status: str) -> None:
        self.solves += 1
        if status == "Maximum_WallTime_Exceeded":
            raise Stopped("timed_out", "The plan calculation ran out of its time budget inside a solve; no figures "
                                       "are reported.")
        self.check()


# --- one IPOPT solve ----------------------------------------------------------------------------------------

def _seed_trajectories(x0v, ws_u, step, *, M: int, K: int):
    """One state trajectory per scenario, rolled out through the very step the constraints impose (draft)."""
    uv = np.array([ws_u.tau_Y, ws_u.tau_E, ws_u.tau_N, ws_u.tau_H,
                   ws_u.C, ws_u.m_E, ws_u.m_N, ws_u.p_A, ws_u.theta], dtype=float)
    out = []
    for m in range(M):
        xv = np.asarray(x0v, dtype=float).flatten()
        traj = [xv]
        for k in range(K):
            xv = np.array(step(m, k, xv, uv)).flatten()
            traj.append(xv)
        out.append(traj)
    return out


def _warm_theta(warm: Control, market: Market) -> Control:
    if market.kind == "allocation":
        return Control(warm.tau_Y, warm.tau_E, warm.tau_N, warm.tau_H, warm.C, warm.m_E, warm.m_N, warm.p_A, 1.0)
    return warm


def _solve_once(
    x0: State,
    goal: GoalSpec,
    *,
    warm: Control,
    grid: Grid,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    market: Market = DRAFT_MARKET,
    psi: float = 1.0,
    bequest_weight: float = 0.10,
    M: int = 24,
    seed: int = 0,
    W_buffer: float | None = None,
    max_iter: int = 3000,
    objective: str = "utility",
    cvar_bound: float = 0.0,
    verbose: bool = False,
    extra_opts: dict | None = None,
    budget: Budget | None = None,
) -> SolveResult:
    """One IPOPT solve of the finite-horizon problem from a given warm start (``utility`` or
    ``min_shortfall``, as the draft). Each goal evaluates its CVaR at its own node."""
    p = params or Params()
    goals_all = [goal, *(extra_goals or [])]
    W_buffer = p.liquidity_floor if W_buffer is None else W_buffer
    gamma = p.gamma
    epsilon = goal.epsilon
    c_ref = p.G

    horizon_years = max(g.horizon_years for g in goals_all)
    if grid.rule == "variable":
        horizon_years = min(horizon_years, grid.times[-1])
    K = grid.K
    dts = grid.dts
    times = grid.times

    def _goal_step(g: GoalSpec) -> int:
        return grid.goal_node(g.horizon_years)

    x0v = _state_vec(x0, p)
    warm = _warm_theta(warm, market)

    # --- the step, per market ---
    scen: Optional[AllocationScenarios] = None
    levels = np.ones((M, K + 1))
    if market.kind == "draft":
        Z = _sample_shocks(M, K, p.rho_WR, seed)
        xs, us, zs = ca.SX.sym("xs", sym.NX), ca.SX.sym("us", sym.NU), ca.SX.sym("zs", 2)
        step_fns = {dt: ca.Function("seed_step", [xs, us, zs], [sym.euler_step(xs, us, zs, p, dt)])
                    for dt in set(dts)}

        def seed_step(m, k, xv, uv):
            return step_fns[dts[k]](xv, uv, Z[m, k])

        def nlp_step(m, k, xk, uk):
            return sym.euler_step(xk, uk, Z[m, k], p, dts[k])
    else:
        scen = sample_allocation(market.inputs, market.prop, dts, M, seed)
        levels = scen.level
        p_nm = no_market_params(p)
        xs, us = ca.SX.sym("xs", sym.NX), ca.SX.sym("us", sym.NU)
        rs, infs, grs = ca.SX.sym("r"), ca.SX.sym("infl"), ca.SX.sym("g")

        step_fns = {dt: ca.Function("seed_step", [xs, us, rs, infs, grs],
                                    [sym.allocation_step(xs, us, p_nm, dt, r=rs, infl=infs, growth=grs)])
                    for dt in set(dts)}

        def seed_step(m, k, xv, uv):
            return step_fns[dts[k]](xv, uv, scen.r[m, k], scen.infl[m, k], scen.growth[m, k])

        def nlp_step(m, k, xk, uk):
            return sym.allocation_step(xk, uk, p_nm, dts[k], r=float(scen.r[m, k]), infl=float(scen.infl[m, k]),
                                       growth=float(scen.growth[m, k]))

    seed_X = _seed_trajectories(x0v, warm, seed_step, M=M, K=K)

    opti = ca.Opti()
    sx = np.ones(sym.NX)
    su = np.ones(sym.NU)
    Us = U = [opti.variable(sym.NU) for _ in range(K)]
    Xs = X = [[opti.variable(sym.NX) for _ in range(K + 1)] for _ in range(M)]

    # --- control admissibility (spec §4, §10; M67) ---
    for k in range(K):
        u = U[k]
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_Y], _TAU_Y_MAX))
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_E], 1.0))
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_N], 1.0))
        opti.subject_to(opti.bounded(_TAU_H_MIN, u[sym.TAU_H], 1.0))
        opti.subject_to(u[0] + u[1] + u[2] + u[3] <= 1.0 - _LEISURE_MIN)
        for j in (sym.C, sym.M_E, sym.M_N, sym.P_A):
            opti.subject_to(u[j] >= 0)
        if market.kind == "allocation":
            # LBSIM-07: the optimiser does not choose the portfolio. theta keeps its slot, fixed at 1.
            opti.subject_to(u[sym.THETA] == 1.0)
        else:
            opti.subject_to(opti.bounded(0.0, u[sym.THETA], 1.0))
        opti.subject_to(u[sym.C] >= 1_000.0)

    # --- initial conditions (relational, so duals -> costates, §13) ---
    init_cons = []
    for m in range(M):
        rel = X[m][0] == x0v
        opti.subject_to(rel)
        init_cons.append(rel)

    # --- dynamics defects + per-node state bounds (the draft's 4 August 2026 lesson) ---
    for m in range(M):
        for k in range(K):
            opti.subject_to(X[m][k + 1] == nlp_step(m, k, X[m][k], U[k]))
        for k in range(K + 1):
            xk = X[m][k]
            opti.subject_to(xk[sym.W_L] >= W_buffer)
            opti.subject_to(xk[sym.W_R] >= 0)
            opti.subject_to(xk[sym.D] >= 0)
            opti.subject_to(opti.bounded(_EPS, xk[sym.E], 2.0))
            opti.subject_to(opti.bounded(_EPS, xk[sym.N], 6.0))
            opti.subject_to(opti.bounded(1e-3, xk[sym.H], p.K_H))
            opti.subject_to(xk[sym.W_RES] >= -_STATE_BOUND_SLACK)
            opti.subject_to(xk[sym.W_HOL] >= -_STATE_BOUND_SLACK)
            opti.subject_to(xk[sym.W_P] >= -_STATE_BOUND_SLACK)
            opti.subject_to(xk[sym.W_3A] >= -_STATE_BOUND_SLACK)
            opti.subject_to(xk[sym.KAPPA] >= -_STATE_BOUND_SLACK)
            if _ENFORCE_PARTS_LE_WHOLE:
                opti.subject_to(xk[sym.W_RES] + xk[sym.W_HOL] <= xk[sym.W_R])

    # --- one CVaR surrogate per goal, each at its own node (eq. 8.4); auxiliaries unseeded (draft) ---
    cvar_primary = None
    for gi, g in enumerate(goals_all):
        kg = _goal_step(g)
        z_g = opti.variable()
        s_g = opti.variable(M)
        tail = 0
        for m in range(M):
            L_m = -g.symbolic_slack(X[m][kg], U[kg - 1], p, level=float(levels[m, kg]))
            opti.subject_to(s_g[m] >= 0)
            opti.subject_to(s_g[m] >= L_m - z_g)
            tail = tail + s_g[m]
        cvar_g = z_g + tail / (g.epsilon * M)
        if objective == "utility":
            opti.subject_to(cvar_g <= cvar_bound)
        if gi == 0:
            cvar_primary = cvar_g
    cvar = cvar_primary

    # --- objective: SAA discounted utility + terminal bequest (eq. 9.2; habit M80) ---
    J = 0
    for m in range(M):
        acc = 0
        for k in range(K):
            disc = ca.exp(-p.rho * times[k])
            u = U[k]
            leisure = 1.0 - (u[0] + u[1] + u[2] + u[3])
            z = ca.fmax(u[sym.C] - p.habit_intensity * X[m][k][sym.KAPPA], _HABIT_FLOOR * c_ref)
            u_c = _crra(z / c_ref, gamma)
            v = _crra(leisure * X[m][k][sym.H], _GAMMA_V)
            acc = acc + disc * (u_c + psi * v) * dts[k]
        omega = X[m][K][sym.W_L] + X[m][K][sym.W_R] - X[m][K][sym.D]
        acc = acc + ca.exp(-p.rho * horizon_years) * bequest_weight * _crra(omega / c_ref, gamma)
        J = J + acc
    J = J / M
    if objective == "min_shortfall":
        opti.minimize(cvar_primary)
    else:
        opti.minimize(-J)

    # --- warm start (per-scenario rollout through the constraint's own step; non-finite refused) ---
    _uv0 = np.array([warm.tau_Y, warm.tau_E, warm.tau_N, warm.tau_H,
                     warm.C, warm.m_E, warm.m_N, warm.p_A, warm.theta], dtype=float)
    for k in range(K):
        opti.set_initial(Us[k], _uv0 / su)
    for m in range(M):
        for k in range(K + 1):
            seedv = np.asarray(seed_X[m][k], dtype=float).flatten()
            if not np.all(np.isfinite(seedv)):
                bad = [i for i, v in enumerate(seedv) if not np.isfinite(v)]
                raise SolveFailed(
                    f"the warm-start rollout went non-finite at scenario {m}, step {k} of {K} "
                    f"(t = {times[k]:g} yr of {horizon_years:g}), in state component(s) {bad}; there is nothing to "
                    f"start the optimiser from. This is about the solve, not the household: no figure may be quoted.")
            opti.set_initial(Xs[m][k], seedv / sx)

    opts = {
        "ipopt.max_iter": max_iter, "ipopt.tol": 1e-6,
        "ipopt.mu_strategy": "adaptive",
        "ipopt.acceptable_tol": 1e-4,
        "ipopt.acceptable_iter": 8,
    }
    if not verbose:
        opts.update({"ipopt.print_level": 0, "print_time": 0, "ipopt.sb": "yes"})
    if budget is not None:
        opts.update(budget.ipopt_options())
    if extra_opts:
        opts.update(extra_opts)
    opti.solver("ipopt", opts)

    t0 = time.monotonic()
    success = True
    status = "Solve_Succeeded"
    try:
        sol = opti.solve()
    except RuntimeError:
        sol = opti.debug
        try:
            status = opti.stats().get("return_status", "")
        except Exception:  # noqa: BLE001
            status = ""
        success = status == "Solved_To_Acceptable_Level"
    wall = time.monotonic() - t0
    try:
        _st = opti.stats()
        iter_count = int(_st.get("iter_count", -1))
    except Exception:  # noqa: BLE001
        iter_count = -1
    if budget is not None:
        budget.after_solve(status)

    def _named(u):
        return dict(tau_Y=float(u[0]), tau_E=float(u[1]), tau_N=float(u[2]), tau_H=float(u[3]),
                    C=float(u[4]), m_E=float(u[5]), m_N=float(u[6]), p_A=float(u[7]), theta=float(u[8]))

    u0 = np.array(sol.value(U[0])).flatten()
    u0_named = _named(u0)
    u_path = [_named(np.array(sol.value(U[k])).flatten()) for k in range(K)]

    lam = np.zeros(sym.NX)
    if success:
        for rel in init_cons:
            lam += np.array(sol.value(opti.dual(rel))).flatten()
    costates = Costates(lam_W=float(lam[sym.W_L]), lam_E=float(lam[sym.E]),
                        lam_N=float(lam[sym.N]), lam_H=float(lam[sym.H]))

    E0, N0, H0 = x0v[sym.E], x0v[sym.N], x0v[sym.H]
    K_N0 = p.K_N0 * (1.0 + p.lambda_E * E0 + p.lambda_W * (x0v[sym.W_L] + x0v[sym.W_R]) / p.W_scale)
    dN_dtauN = p.alpha_N * (1.0 - N0 / K_N0)
    dY_dtauY = dyn.earning_power(E0, N0, x0.person.age, p) * H0 ** p.c
    xr = ExchangeRate(goal=goal.name, networking_value=abs(costates.lam_N) * dN_dtauN,
                      overtime_value=abs(costates.lam_W) * dY_dtauY)

    kg0 = _goal_step(goal)
    slacks = np.array([
        float(sol.value(goal.symbolic_slack(X[m][kg0], U[kg0 - 1], p, level=float(levels[m, kg0]))))
        for m in range(M)
    ])
    p_fi = float(np.mean(slacks >= 0))

    # --- the CVaR constraint has to actually hold (M70; the gate only where it exists, M79) ---
    cvar_value = float(sol.value(cvar))
    cvar_tol = max(1e-6, 1e-6 * money_scale(goal, p))
    cvar_constrained = objective == "utility"
    cvar_ok = cvar_value <= cvar_bound + cvar_tol
    if success and cvar_constrained and not cvar_ok:
        success = False

    return SolveResult(
        u0=u0_named, costates=costates, exchange_rate=xr,
        p_fi_insample=p_fi, cvar_shortfall=cvar_value,
        objective=float(sol.value(J)), success=success,
        stats={"K": K, "M": M, "epsilon": epsilon, "objective": objective,
               "cvar_ok": cvar_ok, "cvar_constrained": cvar_constrained,
               "cvar_bound": cvar_bound, "cvar_tol": cvar_tol,
               "return_status": status, "iter_count": iter_count, "max_iter": max_iter,
               "n_var": opti.nx, "n_con": opti.ng, "wall_clock_s": wall, "market": market.kind},
        u_path=u_path, dt_opt=float(dts[0]), dts=tuple(dts),
    )


# --- warm starts (draft) ------------------------------------------------------------------------------------

def _default_starts(G: float) -> list[Control]:
    return [
        Control(0.45, 0.05, 0.10, 0.20, min(G, 100_000), 3_000, 5_000, 0.0, 0.40),  # balanced
        Control(0.55, 0.05, 0.05, 0.15, 0.55 * G, 2_000, 3_000, 0.0, 0.30),          # work & save
        Control(0.35, 0.15, 0.15, 0.20, 0.70 * G, 5_000, 8_000, 0.0, 0.50),          # invest capitals
        Control(0.50, 0.02, 0.05, 0.25, 0.45 * G, 1_000, 2_000, 0.0, 0.20),          # frugal
    ]


def _restore_starts(G: float) -> list[Control]:
    return [
        Control(0.60, 0.05, 0.05, 0.10, 0.30 * G, 1_000, 1_000, 0.0, 0.55),  # save hard, risk-on
        Control(0.50, 0.10, 0.12, 0.18, 0.40 * G, 3_000, 5_000, 0.0, 0.45),  # save + build capitals
    ]


def _control_from_named(u: dict) -> Control:
    return Control(u["tau_Y"], u["tau_E"], u["tau_N"], u["tau_H"],
                   u["C"], u["m_E"], u["m_N"], u["p_A"], u["theta"])


#: The draft's relative-shortfall table (``optim.achievable``): the FI slack is money, the others are ratios.
_SHORTFALL_IS_RELATIVE: dict[str, bool] = {"fi": False, "retirement": True, "home": True, "company": True,
                                           "measure": True}


def amount_deficit(kind: str, amount: float, cvar_shortfall: float) -> float:
    s = max(0.0, float(cvar_shortfall))
    return amount * s if _SHORTFALL_IS_RELATIVE.get(kind, True) else s


def money_scale(goal: GoalSpec, p: Params) -> float:
    """The scale the draft widens its CVaR tolerances by (M70, 5 August 2026): ``|G|`` for a slack in francs.

    lbsim departure (O-4): the draft applied ``|G|`` to every kind, but only the FI slack is money. The home,
    company and retirement slacks are ratios (``_SHORTFALL_IS_RELATIVE``) and so is lbsim's ``measure`` slack, and
    ``1e-5 * G`` on a ratio is a tolerance of about 1 (a 100 % shortfall passing as funded: measured on the sample
    household, a bound of 1.2 certified a plan with an in-sample chance of 0). A relative slack keeps the calibration's
    ``cvar_tol`` unscaled (1e-3: a thousandth of the target), which is what the draft's comment asks for, a
    tolerance on the goal's own scale."""
    return abs(float(p.G)) if not _SHORTFALL_IS_RELATIVE.get(goal.kind, True) else 1.0


def _stated_amount(goal: GoalSpec, p: Params) -> float:
    if goal.kind == "measure":
        return float(goal.params["target"])
    return float(goal.params.get(
        {"fi": "G", "retirement": "G_ret", "home": "price", "company": "B_buffer"}[goal.kind], p.G))


# --- the two-phase multistart solve with the redraw rule (draft) --------------------------------------------

def solve_case(
    x0: State,
    goal: GoalSpec,
    *,
    grid: Grid,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    starts: list[Control] | None = None,
    n_starts: int = 3,
    restore_starts: int = 2,
    cvar_tol: float = 1e-3,
    seed_retries: int = 3,
    seed: int = 0,
    seed_step: int = 1_000,
    budget: Budget | None = None,
    **kwargs,
) -> SolveResult:
    """Two-phase multistart solve (the draft's ``solve_case``): phase 1 minimises the primary goal's CVaR
    shortfall from aggressive starts, phase 2 maximises utility subject to CVaR <= ``cvar_tol`` on every goal.
    Redraws the scenarios at ``seed + seed_step * k`` when a draw is pathological, never for an unfundable goal
    (M79). The seed used is in ``stats``."""
    p = params or Params()
    if starts is None:
        starts = _default_starts(p.G)[:max(1, n_starts)]
    attempts: list[SolveResult] = []
    tried: list[int] = []
    for attempt in range(max(1, seed_retries)):
        s = seed + seed_step * attempt
        tried.append(s)
        if budget is not None:
            budget.seeds.append(s)
        res = _solve_case_once(x0, goal, grid=grid, params=p, extra_goals=extra_goals, starts=starts,
                               restore_starts=restore_starts, cvar_tol=cvar_tol, seed=s, seed_attempt=attempt,
                               budget=budget, **kwargs)
        res.stats["seed"] = s
        res.stats["seed_attempt"] = attempt
        res.stats["seeds_tried"] = list(tried)
        attempts.append(res)
        if res.success:
            return res
        if res.stats.get("outcome") == "goal_not_fundable":
            return res
    best = min(attempts, key=lambda c: (not c.success, c.cvar_shortfall))
    best.stats["seed_attempts_exhausted"] = len(attempts)
    best.stats["seeds_tried"] = list(tried)
    return best


def _solve_case_once(
    x0: State,
    goal: GoalSpec,
    *,
    grid: Grid,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    starts: list[Control] | None = None,
    restore_starts: int = 2,
    cvar_tol: float = 1e-3,
    seed_attempt: int = 0,
    budget: Budget | None = None,
    **kwargs,
) -> SolveResult:
    p = params or Params()
    starts = starts or _default_starts(p.G)
    cvar_tol = max(cvar_tol, 1e-5 * money_scale(goal, p))
    failures: list[str] = []
    log: list[dict] = []

    def _try_solve(*, phase: str, index: int, of: int, **kw):
        if budget is not None:
            budget.before_solve(phase=phase, start=index, of=of, seed_attempt=seed_attempt)
        try:
            r = _solve_once(x0, goal, grid=grid, params=p, extra_goals=extra_goals, budget=budget, **kw)
        except SolveFailed as exc:
            failures.append(str(exc))
            log.append({"phase": phase, "start": index, "failed_to_start": True})
            return None
        log.append({"phase": phase, "start": index, "return_status": r.stats.get("return_status"),
                    "iter_count": r.stats.get("iter_count"), "success": r.success,
                    "cvar": r.cvar_shortfall, "wall_clock_s": r.stats.get("wall_clock_s")})
        return r

    restore_warms = _restore_starts(p.G)[:max(1, restore_starts)]
    phase1 = []
    for i, w in enumerate(restore_warms):
        c = _try_solve(phase="restore", index=i + 1, of=len(restore_warms), warm=w, objective="min_shortfall",
                       **kwargs)
        if c is not None:
            phase1.append(c)
    if not phase1:
        raise SolveFailed("every phase-1 warm start failed to start:\n  " + "\n  ".join(failures))
    p1_ok = [c for c in phase1 if c.success] or phase1
    best_restore = min(p1_ok, key=lambda c: c.cvar_shortfall)
    s_star = best_restore.cvar_shortfall
    restore_converged = (best_restore.success
                         and best_restore.stats.get("return_status") == "Solve_Succeeded")

    bound = cvar_tol
    phase2_starts = [_control_from_named(best_restore.u0), *starts]
    cands = []
    for i, w in enumerate(phase2_starts):
        c = _try_solve(phase="best_life", index=i + 1, of=len(phase2_starts), warm=w, objective="utility",
                       cvar_bound=bound, **kwargs)
        if c is not None:
            cands.append(c)
    if not cands:
        raise SolveFailed("every phase-2 warm start failed to start:\n  " + "\n  ".join(failures))

    meets = [c for c in cands if c.success and c.cvar_shortfall <= bound + cvar_tol]
    if meets:
        best = max(meets, key=lambda c: c.objective)
        best.stats.update(s_star=s_star, cvar_bound=bound, restore_converged=bool(restore_converged),
                          outcome="plan", solves=log)
        return best

    if restore_converged and s_star > cvar_tol:
        best_restore.success = False
        best_restore.stats.update(s_star=s_star, cvar_bound=bound, restore_converged=True,
                                  outcome="goal_not_fundable", solves=log)
        best_restore.stats["shortfall_annual"] = amount_deficit(goal.kind, _stated_amount(goal, p), s_star)
        best_restore.stats["shortfall_cvar_raw"] = s_star
        return best_restore

    best = max(cands, key=lambda c: c.objective)
    best.success = False
    best.stats.update(s_star=s_star, cvar_bound=bound, restore_converged=bool(restore_converged),
                      outcome="undetermined", solves=log)
    return best


def solve_fi(
    x0: State,
    *,
    horizon_years: float,
    params: Params | None = None,
    G: float | None = None,
    swr: float | None = None,
    h_res: float | None = None,
    epsilon: float = 0.10,
    dt_opt: float = 0.5,
    **kwargs,
) -> SolveResult:
    """The draft's FI entry point on a uniform grid of ``dt_opt`` (the draft's ``K = round(H / dt_opt)``)."""
    from .grid import Grid as _Grid  # noqa: PLC0415

    p = params or Params()
    goal = GoalSpec(kind="fi", horizon_years=horizon_years, epsilon=epsilon,
                    params=dict(G=p.G if G is None else G,
                                swr=p.swr if swr is None else swr,
                                h_res=p.h_res if h_res is None else h_res))
    K = max(1, int(round(horizon_years / dt_opt)))
    grid = _Grid(rule="draft_single_step", dts=(dt_opt,) * K, times=tuple(k * dt_opt for k in range(K + 1)),
                 solved_years=horizon_years, total_years=horizon_years, capped=False)
    return solve_case(x0, goal, grid=grid, params=p, **kwargs)
