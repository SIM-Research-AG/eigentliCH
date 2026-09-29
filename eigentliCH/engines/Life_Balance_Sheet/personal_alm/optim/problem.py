"""Route A: scenario-based finite-horizon NLP with a CVaR chance constraint
(spec §10–11, §9.3).

Multiple-shooting formulation:
  variables   control path U[k] (shared across scenarios — non-anticipativity),
              states X[m][k] per scenario, and the CVaR auxiliaries (VaR z, tail
              slacks s[m]).
  objective   sample-average discounted utility of consumption + leisure·health,
              plus a terminal bequest (eq. 9.2), maximised.
  constraints Euler–Maruyama defects (their duals are the costates, §10.2–10.3),
              the time simplex + money/θ box, a liquidity floor, and the FI CVaR
              surrogate CVaR_{1−ε}[−g] ≤ 0 (eq. 8.4).

Apply only u*[0] (spec §12); the costates give the exchange-rate output (§13).

Numerical notes: consumption utility is normalised by the target spend G so it is
O(1) and commensurate with the leisure term; leisure uses a bounded curvature
(γ_v = 0.5, finite at 0) so the objective stays well-conditioned; and the state
trajectory is warm-started from a deterministic rollout, which is what makes the
multiple-shooting problem converge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import casadi as ca
import numpy as np

from ..goals.spec import GoalSpec
from ..model import dynamics as dyn
from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from ..sim.montecarlo import constant_policy, simulate
from . import symbolic as sym

_EPS = 1e-6
#: Minimum leisure, raised 0.01 → 0.05 on 3 August 2026 (M67). One hour a week was close enough to nothing that
#: the model could recommend a life with no free time in it and break no rule. Five hours still permits a
#: genuinely intense phase — the engine's own backtest records epochs with none at all — while forbidding the
#: degenerate case. Advice-side only: `calibrate/nicolas.py` runs through `sim/montecarlo`, not through here, so
#: the recorded biography stays reproducible.
_LEISURE_MIN = 0.05

#: Hard ceiling on working time: 70 h of a 100 h/week productive budget. Set well above `tau_Y_star = 0.50`
#: deliberately, so the `eta` health penalty does the work across a real 50–70 h range and this bound only
#: forbids the physically absurd. Previously absent entirely — `tau_Y = 1.0` was admissible.
_TAU_Y_MAX = 0.70

#: Minimum recovery time, 5 h/week. Previously absent, so zero rest was admissible indefinitely.
_TAU_H_MIN = 0.05
_GAMMA_V = 0.5  # bounded leisure curvature (finite at 0)


def _crra(x: ca.SX, gamma: float) -> ca.SX:
    xf = ca.fmax(x, _EPS)
    if abs(gamma - 1.0) < 1e-9:
        return ca.log(xf)
    return xf ** (1.0 - gamma) / (1.0 - gamma)


def _state_vec(x0: State, p: Params) -> np.ndarray:
    # Order must match `sym.W_L, W_R, D, E, N, H, AGE, W_RES`. `W_RES` is last because it was appended rather
    # than slotted beside `W_R`, precisely so the positional reads at lines ~356-360 below kept their meaning.
    # `kappa` is last for the same reason `W_RES` is not slotted beside `W_R`: appending keeps every
    # positional read below meaning what it meant. An unset habit is read through `habit_of`, which takes the
    # consumption the household's own drawable wealth supports rather than zero -- see there for why zero
    # would hand the optimiser a free lunch in the early periods and charge for it later.
    from ..model.dynamics import habit_of  # noqa: PLC0415 - avoids a module-level cycle
    return np.array([x0.wealth.W_L, x0.wealth.W_R, x0.wealth.D,
                     x0.person.E.aggregate(), x0.person.N, x0.person.H,
                     x0.person.age, float(x0.wealth.W_res or 0.0),
                     x0.wealth.W_hol, x0.wealth.W_P, x0.wealth.W_3a,
                     habit_of(x0, p)], dtype=float)


def _sample_shocks(M: int, K: int, rho: float, seed: int) -> np.ndarray:
    """Correlated wealth shocks z[m,k] = (z_W, z_R), matching sim/montecarlo.py."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((M, K, 2))
    zW = z[:, :, 0]
    zR = rho * zW + np.sqrt(max(0.0, 1.0 - rho * rho)) * z[:, :, 1]
    return np.stack([zW, zR], axis=-1)


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

    _CAP = 5.0  # a ratio beyond this is reported as "dominant", not a wild number

    @property
    def determined(self) -> bool:
        """Whether there is any signal here at all.

        Both values are a costate times a marginal product. A non-converged solve leaves every costate at
        0.0, so both sides come out 0.0 and the comparison below has nothing to compare.
        """
        return max(self.networking_value, self.overtime_value) > 0.0

    @property
    def winner(self) -> str:
        """Which lever moves the goal more, or `undetermined` when the solve gave no costates.

        The `>=` used to return "networking" from two zeroes, so a failed solve reported a confident answer
        to the engine's most differentiated question (spec §383) with nothing behind it. That is how M11
        presented: not as a crash but as a plausible wrong verdict. An absent answer is now said to be
        absent.
        """
        if not self.determined:
            return "undetermined"
        return "networking" if self.networking_value >= self.overtime_value else "overtime"

    @property
    def raw_ratio(self) -> float:
        hi, lo = sorted((self.networking_value, self.overtime_value), reverse=True)
        # Floor the denominator relative to the numerator: a near-zero costate is
        # numerically noisy and would otherwise blow the ratio up to nonsense.
        return hi / max(lo, hi * 1e-3) if hi > 0 else 1.0

    @property
    def ratio(self) -> float:
        return min(self.raw_ratio, self._CAP)

    @property
    def dominant(self) -> bool:
        """The winning lever so outweighs the other that a precise multiple is
        meaningless — the alternative barely moves this goal."""
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
    u_path: list = field(default_factory=list)   # planned control per horizon step
    dt_opt: float = 0.5                            # step length of u_path (years)


class SolveFailed(RuntimeError):
    """One solve could not be started or finished, for a reason that is about the SOLVE and not the household.

    Raised rather than returned because the caller's job is to drop this candidate and try the next warm start,
    which is a different thing from a candidate that solved and missed. `_solve_case_once` catches it, records
    the reason, and only reports `undetermined` if EVERY candidate failed — one bad warm start out of three is
    normal and should not sink a household that another start solves cleanly.
    """


def _warmstart_control(G: float) -> Control:
    return Control(tau_Y=0.45, tau_E=0.05, tau_N=0.10, tau_H=0.20,
                   C=min(G, 100_000), m_E=3_000, m_N=5_000, p_A=0.0, theta=0.40)


#: Floor on habit-adjusted consumption `z`, as a share of `c_ref`.
#:
#: `z = C - h*kappa` is genuinely negative when a household spends below its own habit, which is exactly what
#: a plan that cuts spending does. At `gamma = 3` the CRRA of a negative argument is a pole, not a penalty, so
#: the floor turns "worse than the habit" into a steep but finite cost. Set small enough that no plan reaches
#: it except one consuming essentially nothing.
_HABIT_FLOOR: float = 0.05

#: Slack on the four added state bounds, in CHF. **Not a fudge — it removes an interior-point degeneracy.**
#:
#: `W_hol` is 0 for a household with no second home and `dW_HOL = mu_R * W_HOL`, so `W_HOL` is *identically* 0
#: at every node. `W_3a` is the same whenever `pillar3a_contribution` is 0 (its default since M73), and `W_P`
#: starts at 0. Imposing `>= 0` on a variable that the dynamics equalities pin exactly to 0 asks IPOPT to be
#: strictly interior where the equality constraints forbid it: the barrier wants slack, the dynamics give none.
#: With bounds at every node that is ~700 degenerate constraints, which is why moving them inside the `k` loop
#: made the flagship worse rather than better (p_goal 0.550 -> 0.113).
#:
#: CHF 1 is economically nothing — six orders below the smallest quantity in the model — while making a pinned
#: zero strictly feasible. The bound still blocks the negative `W_RES` that motivated it, since the exploit
#: needed values of order 1e6 to manufacture rent worth having.
_STATE_BOUND_SLACK: float = 1.0

#: Whether to impose `W_RES + W_HOL <= W_R` at every node (M77). **Default False, and that is a measured trade
#: rather than a clean decision:** removing it fixed `Near-retiree` (400 stalled -> 21 iterations) and `Tail shock`
#: (-> 46) and BROKE the flagship (226 iterations and `Solve_Succeeded` -> 400 and `Maximum_Iterations_Exceeded`).
#: The constraint is *inactive* for the flagship, so it changes no optimum — it changes the NLP's row set, and on a
#: problem this ill-conditioned that alone moves IPOPT from converging to not. An inactive constraint is not free.
#:
#: A flag rather than a deletion so the choice can be re-measured across every case simultaneously. Scoring one
#: subset at a time is exactly how two contradictory verdicts were reached on 4 August 2026.
#:
#: **Settled at False on 25 August 2026 by the full matrix re-run on the M80 model (M87), and the trade above no
#: longer describes it.** With it ON, nothing in the roster certifies -- 0 of 6 under either scaling -- and it
#: costs more than the certificate: the usable-finding count (a plan, or P8's `goal_not_fundable`) falls from
#: 4 of 6 to 1 of 6, with the rest `undetermined`, which makes no claim at all. An inactive constraint that
#: costs the household its answer is worse than one that costs it a certificate.
_ENFORCE_PARTS_LE_WHOLE: bool = False

#: Whether to nondimensionalise the NLP by a change of variables (see `_nlp_scales`). **Default False, also a
#: measured trade.** It fixed `Entrepreneur` (400 stalled -> 132 iterations, hitting the known optimum 48 509) and
#: the flagship post-M77, and it cost `Near-retiree` and `Tail shock` their certification — they reached the same
#: `cvar` and exited `Search_Direction_Becomes_Too_Small` / `Error_In_Step_Computation` instead of succeeding.
#:
#: **Settled at False on 25 August 2026 (M87).** On the M80 model the certifying sets are nested rather than
#: disjoint -- unscaled certifies `Independence by fifty` and `Near-retiree`, scaled certifies only the second --
#: so unscaled weakly dominates and M78's "no single knob" no longer holds. Read the whole verdict with M87
#: finding 2 attached: publishable AND meeting the case's own confidence is **0 of 24** cells, so neither flag
#: moves any household to a plan that works. These two are settled; what stops the roster publishing is not here.
_SCALE_NLP: bool = False

#: States whose trajectory does not depend on the control at all, so their values are *known* once `x0` and the
#: shock draw are known. Verified from `symbolic.drift`/`diffusion`:
#:
#:     dW_R = mu_R * W_R   (+ sigma_R * W_R noise)     no control term
#:     dW_RES = mu_R * W_RES                           no control, no noise
#:     dW_HOL = mu_R * W_HOL                           no control, no noise
#:     dAGE = 1                                        no control, no noise
#:
#: The optimiser cannot influence any of them, so the seeded rollout *is* the solution rather than a guess at it,
#: and each can be fixed by equal lower and upper bounds. That is 4 of 11 states — at `M=32, K=10`, **1 408 of
#: 3 995 variables that were being solved for when they were already determined.**
#:
#: If a control term is ever added to one of these (a `W_R` purchase or sale, a residence share the household
#: chooses), it MUST come off this list in the same commit. `test_optim.py` re-derives the list from the symbolic
#: Jacobian rather than trusting it, so that removal is enforced rather than remembered.
#:
#: **Not yet exploited, and the two attempts on 4 August 2026 are recorded so they are not repeated blind.**
#:
#: 1. *Fixing* these states by equal bounds fails: their dynamics rows remain, so 1 408 fixed variables left
#:    2 587 free against 3 872 equalities and IPOPT exits `Too few degrees of freedom`. Making it work means also
#:    deleting their dynamics AND initial-condition rows — but the initial-condition duals *are* the costates
#:    (`Costates`, sized from `sym.NX`), so that would silently drop the marginal value of `W_R` and of age.
#: 2. Declaring the state box as one vectorised `opti.bounded(lb, X[m][k], ub)` does **not** produce variable
#:    bounds either. IPOPT still reported `variables with only lower bounds: 0`; `casadi.Opti` routes every
#:    `subject_to` into `g` whatever its shape. Real `lbx`/`ubx` need the lower-level `nlpsol` interface, which is
#:    its own refactor. The attempt also *cost* iterations — 226 and `Solve_Succeeded` became 400 and
#:    `Maximum_Iterations_Exceeded` — because the extra rows are not free.
#:
#: So the payoff here is real (35% of the variables are determined) but it is gated on moving off `Opti`. The
#: honest note for whoever takes it: the M67 comment claiming `opti.bounded` gives "variable bounds" is wrong,
#: and the IPOPT header is where to check rather than the CasADi docs.
_CONTROL_FREE_STATES: tuple[int, ...] = (sym.W_R, sym.W_RES, sym.W_HOL, sym.AGE)


def _nlp_scales(x0v, p: Params):
    """Characteristic scales for the optional change of variables. Returns `(sx, su)`.

    **A change of variables, NOT a change of units.** The decision variables become `X / sx` and `U / su`, and
    every expression handed to `sym.*` is the unscaled product — so `model/dynamics.py` and `optim/symbolic.py` are
    untouched, parity is unaffected by construction, `cvar_shortfall` stays in francs, and the initial-condition
    residual keeps its units. That last point matters: those duals *are* the costates, and silently rescaling them
    would corrupt the exchange rate.

    Stocks and flows get different scales because they are different quantities. The stock scale comes from the
    household's own balance sheet, floored at `G` so a household with no real assets still gets a sane divisor
    rather than a division by zero (`Young professional` has `W_R = 0`). `E`, `N`, `H` and `AGE` stay at 1: already
    O(1)–O(100), so scaling them would add risk without removing spread.
    """
    x0f = np.asarray(x0v, dtype=float).flatten()
    stock = max(float(p.G), float(x0f[sym.W_L] + x0f[sym.W_R]))
    sx = np.ones(sym.NX)
    for i in (sym.W_L, sym.W_R, sym.D, sym.W_RES, sym.W_HOL, sym.W_P, sym.W_3A):
        sx[i] = stock
    su = np.ones(sym.NU)
    for j in (sym.C, sym.M_E, sym.M_N, sym.P_A):
        su[j] = max(1.0, float(p.G))
    return sx, su


def _seed_trajectories(x0v, ws_u, Z, p: Params, *, M: int, K: int, dt_opt: float):
    """One state trajectory per scenario, rolled out under that scenario's own shocks.

    Built through `sym.euler_step` — the very expression the dynamics constraints impose — so the residual at the
    initial point is exactly zero rather than approximately zero. Seeding from the numpy `simulate` twin would
    leave a 1e-9 parity difference, which is nothing for parity and not nothing next to a barrier method's
    restoration trigger.
    """
    xs, us, zs = ca.SX.sym("xs", sym.NX), ca.SX.sym("us", sym.NU), ca.SX.sym("zs", 2)
    step = ca.Function("seed_step", [xs, us, zs], [sym.euler_step(xs, us, zs, p, dt_opt)])
    uv = np.array([ws_u.tau_Y, ws_u.tau_E, ws_u.tau_N, ws_u.tau_H,
                   ws_u.C, ws_u.m_E, ws_u.m_N, ws_u.p_A, ws_u.theta], dtype=float)
    out = []
    for m in range(M):
        xv = np.asarray(x0v, dtype=float).flatten()
        traj = [xv]
        for k in range(K):
            xv = np.array(step(xv, uv, Z[m, k])).flatten()
            traj.append(xv)
        out.append(traj)
    return out


def _solve_once(
    x0: State,
    goal: GoalSpec,
    *,
    warm: Control,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    psi: float = 1.0,
    bequest_weight: float = 0.10,
    dt_opt: float = 0.5,
    M: int = 24,
    seed: int = 0,
    W_buffer: float | None = None,
    horizon_cap: float | None = None,
    #: IPOPT iteration budget. Raised from 1000 to 3000 on 2026-08-01 (M11).
    #:
    #: This problem's difficulty is not monotone in the scenario count: with the book's 45-year-old case at
    #: a 5-year horizon and seed 0, M=12 converges in 288 iterations and M=16 in 248, but **M=14 needs more
    #: than 1000** and exhausted the old budget. It was not infeasible and not mis-specified — the same M=14
    #: instance solves cleanly at 3000 (and at the old budget under seed 1). A scenario draw that happens to
    #: make the CVaR constraint nearly degenerate costs iterations, and 1000 sat just below what this one
    #: needed.
    #:
    #: The three long-standing failures in `test_optim.py` were all this one cause: a non-converged solve
    #: skips the dual extraction below, so every costate came back 0.0, which in turn made the
    #: overtime-versus-networking verdict meaningless. See DECISIONS.md M11.
    max_iter: int = 3000,
    objective: str = "utility",
    cvar_bound: float = 0.0,
    verbose: bool = False,
    extra_opts: dict | None = None,
) -> SolveResult:
    """One IPOPT solve of the finite-horizon problem from a given warm start.

    Two objective modes (spec §11, solver-reliability two-phase):
      "utility"        maximise SAA discounted utility subject to CVaR ≤ `cvar_bound`
                       per goal (the plan we actually apply);
      "min_shortfall"  minimise the primary goal's CVaR shortfall with NO CVaR
                       constraint (feasibility restoration). This objective has no
                       "give-up and consume" incentive, so it reliably finds the
                       best-achievable funding s* used to set phase 2's bound.

    Each goal (primary + extras) evaluates its CVaR at its own deadline step; the
    horizon spans the latest deadline (spec §11–12)."""
    p = params or Params()
    goals_all = [goal, *(extra_goals or [])]
    W_buffer = p.liquidity_floor if W_buffer is None else W_buffer
    gamma = p.gamma
    epsilon = goal.epsilon
    c_ref = p.G  # a generic consumption scale so utility is O(1)

    # Horizon spans the latest deadline among all goals.
    horizon_years = max(g.horizon_years for g in goals_all)
    if horizon_cap is not None:
        horizon_years = min(horizon_years, horizon_cap)
    K = max(1, int(round(horizon_years / dt_opt)))

    def _goal_step(g: GoalSpec) -> int:
        return max(1, min(K, int(round(g.horizon_years / dt_opt))))
    x0v = _state_vec(x0, p)
    Z = _sample_shocks(M, K, p.rho_WR, seed)

    # The deterministic `simulate` rollout that used to seed the states is gone: see the warm-start block for why
    # a noise-free seed left IPOPT in feasibility restoration for 390 consecutive iterations.
    ws_u = warm
    seed_X = _seed_trajectories(x0v, ws_u, Z, p, M=M, K=K, dt_opt=dt_opt)

    opti = ca.Opti()
    # Dimensions come from symbolic rather than being restated, so a state addition is one change there.
    #
    # **Nondimensionalisation was implemented here on 4 August 2026 and REVERTED, and the measurement is worth
    # more than the code was.** The variables span about seven orders of magnitude (`W_R = 5e6` and `C = 1.2e5`
    # beside `E = 0.9`), which is the textbook ill-conditioning profile, so the states and flows were divided by
    # characteristic scales as a pure change of variables — decision variables dimensionless, every expression
    # handed to `sym.*` the unscaled product, so the model and the parity tests were untouched. It was correct:
    # the flagship returned `cvar = 13266.9`, identical to the unscaled optimum. It was also a net regression:
    #
    #     case                    before scaling              after scaling
    #     Entrepreneur            400 stalled                 Solve_Succeeded, 132 iters   <- fixed
    #     Independence by fifty   400, cvar 4.848e4           400, cvar 2.262e4            <- 53% better
    #     Young professional      400, cvar 1.953e4           400, cvar 2.423e4
    #     Near-retiree            Solve_Succeeded, 21 iters   Search_Direction_Becomes_Too_Small
    #     Tail shock              Solve_Succeeded, 46 iters   Error_In_Step_Computation, same cvar
    #
    # Publishable results went 2 of 5 to 1 of 5. Every intermediate metric improved and the one that matters got
    # worse: `Tail shock` reached the *identical* `cvar = 1.451e4` and still could not certify it. So the spread of
    # magnitudes is NOT the whole conditioning story — a single global scale relocates which cases fail rather than
    # fixing them, exactly as the `nlp_scaling_max_gradient` sweep did (0/1/1/0/1 converged over 1e2..1e6,
    # non-monotone). Whatever is wrong is per-case and finer-grained than a magnitude rescale.
    if _SCALE_NLP:
        sx, su = _nlp_scales(x0v, p)
        Us = [opti.variable(sym.NU) for _ in range(K)]
        Xs = [[opti.variable(sym.NX) for _ in range(K + 1)] for _ in range(M)]
        U = [Us[k] * ca.DM(su) for k in range(K)]
        X = [[Xs[m][k] * ca.DM(sx) for k in range(K + 1)] for m in range(M)]
    else:
        sx = np.ones(sym.NX)
        su = np.ones(sym.NU)
        Us = U = [opti.variable(sym.NU) for _ in range(K)]
        Xs = X = [[opti.variable(sym.NX) for _ in range(K + 1)] for _ in range(M)]

    # --- control admissibility (spec §4, §10) ---
    #
    # **Feasibility bounds, added 3 August 2026 (M67).** Before them the only limits were `tau >= 0` and
    # `sum tau <= 1 − 0.01`, so the solve could propose 70 h of work, 29 h of learning and networking, **zero
    # rest and one hour of leisure**, indefinitely, and call it optimal. Health decay pushed back on overwork but
    # nothing forbade it, and nothing at all limited learning or networking.
    #
    # Declared through `opti.bounded` rather than as inequality pairs so IPOPT treats them as *variable bounds*
    # and never evaluates outside them. That matters for `_rest_effect`, which raises `tau_H` to a fractional
    # power: a negative argument would be NaN, and a NaN poisons the whole solve instead of failing visibly.
    for k in range(K):
        u = U[k]
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_Y], _TAU_Y_MAX))
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_E], 1.0))
        opti.subject_to(opti.bounded(0.0, u[sym.TAU_N], 1.0))
        opti.subject_to(opti.bounded(_TAU_H_MIN, u[sym.TAU_H], 1.0))
        opti.subject_to(u[0] + u[1] + u[2] + u[3] <= 1.0 - _LEISURE_MIN)
        for j in (sym.C, sym.M_E, sym.M_N, sym.P_A):
            opti.subject_to(u[j] >= 0)
        opti.subject_to(opti.bounded(0.0, u[sym.THETA], 1.0))
        opti.subject_to(u[sym.C] >= 1_000.0)

    # --- initial conditions (relational, so duals → costates, §13) ---
    init_cons = []
    for m in range(M):
        rel = X[m][0] == x0v
        opti.subject_to(rel)
        init_cons.append(rel)

    # --- dynamics defects + state bounds ---
    #
    # --- the states added on 3-4 August 2026, which were UNBOUNDED and exploitable ---------------
    #
    # **This is the cause of the flagship's out-of-sample collapse, and it took a day to find.**
    # `W_RES`, `W_HOL`, `W_P` and `W_3A` were added to the state vector without state constraints,
    # while `W_L`, `W_R`, `D`, `E`, `N` and `H` have always had them. Four of eleven states were free.
    #
    # The exploit is specific and it is not exotic: `W_inv = fmax(0, W_R - W_RES - W_HOL)`, so driving
    # `W_RES` NEGATIVE inflates the let share beyond the whole property stock and manufactures rent that
    # does not exist. The FI slack reads that rent, the CVaR constraint is satisfied in-sample, and
    # `success` comes back True - while `feasibility()` scores the plan out-of-sample by simulating from
    # the REAL initial state, where `W_res` starts at its true value and only grows at `mu_R`. So the
    # optimiser was buying feasibility with a degree of freedom that exists in the NLP and nowhere else.
    #
    # Symptom: p_goal fell from ~0.84 to between 0.11 and 0.67 depending on the scenario draw, with the
    # constraint satisfied throughout. It also explains why more scenarios helped: the exploit is less
    # uniformly profitable across a larger sample, which made the seed spread the visible signal.
    #
    # The lesson generalises past this bug: **a new state needs a constraint in the same commit as its
    # dynamics.** Parity tests compare the two transcriptions and both were correct here; nothing in a
    # parity test asks whether a state is allowed to go somewhere it cannot go in reality.
    #
    # **Indentation defect in the first version of this fix, found 4 August 2026.** These four bounds were
    # written at the `for m` level rather than inside `for k`, so they bound the leaked loop variable --
    # `X[m][K]`, the terminal node -- and nothing else. `X[m][0]` is pinned by the initial condition, so the
    # exploit stayed open at `k = 1 .. K-1` and the manufactured rent still accumulated into `W_L`, which is
    # exactly what `drawable` reads at the deadline. The fix was ~2/11 effective and the flagship's verdict on
    # it was meaningless. State bounds belong in the same loop as the states they bound.
    for m in range(M):
        for k in range(K):
            opti.subject_to(X[m][k + 1] == sym.euler_step(X[m][k], U[k], Z[m, k], p, dt_opt))
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
            # **The habit, bounded in the same commit as its dynamics** — the lesson the four states above
            # cost a day to learn. A negative habit would make `z = C - h*kappa` exceed consumption and hand
            # the objective free utility; the slack keeps the interior point off the boundary.
            opti.subject_to(xk[sym.KAPPA] >= -_STATE_BOUND_SLACK)
            # **`W_RES + W_HOL <= W_R` WAS imposed here and was REMOVED on 4 August 2026. It made the default
            # household infeasible.**
            #
            # It looks unarguable — the parts cannot exceed the whole — and as a statement about reality it is.
            # As a constraint on this NLP it is not, because the two sides do not carry the same noise:
            #
            #     dW_R   = mu_R * W_R + sigma_R * W_R * noise     stochastic
            #     dW_RES = mu_R * W_RES                           deterministic, no noise
            #
            # `W_res` defaults to `None`, meaning *all* of `W_R` is the residence — so `W_res(0) == W_R(0)` with
            # **zero margin**, and the first downward property shock puts `W_R` below `W_res`. Not an edge case:
            # four of the five worked lives take that default, and the seed violated this constraint by 262 608
            # to 724 353, which was the entire `inf_pr` IPOPT then failed to repair (3.47e+05 for `Near-retiree`,
            # against a violation of 346 879). All four sat in restoration for 400 iterations — 3 objective
            # gradient evaluations in 400 — and 3000 iterations changed the objective not at all. Nicolas escaped
            # only because `own_use_share=0.2` leaves a 4m margin.
            #
            # `symbolic.diffusion` predicted the divergence and expected the `fmax` in `drift` to absorb it:
            # "a large negative shock to `W_R` can push it below `W_res` and the `fmax` clamp starts doing
            # load-bearing work". That is exactly right, and it is why this belongs as a clamp and not as a hard
            # constraint — a clamp degrades, a constraint makes the problem unsolvable.
            #
            # Removing it is safe rather than merely expedient: `W_inv = fmax(0, W_R - W_RES - W_HOL)` already
            # floors the let share at zero on both sides of the parity test, so no negative rent can be
            # manufactured; and `W_RES` is control-free (`_CONTROL_FREE_STATES`), so the optimiser cannot walk
            # into the region deliberately. The original reason for adding it — M75's "the optimiser drove
            # `W_RES` negative" — turned out not to be a real mechanism at all.
            #
            # The *principled* fix is the one `symbolic.diffusion` names: give `W_res` the same proportional
            # shock as `W_R`, so the relation is preserved by construction instead of asserted. That changes both
            # transcriptions, and step 5 deletes the diffusion term outright, so it is recorded rather than done.
            #
            # Kept behind a flag rather than deleted, because removing it turned out to be a TRADE and not a win:
            # it fixed `Near-retiree` and `Tail shock` and broke the flagship (226 iterations and
            # `Solve_Succeeded` became 400 and `Maximum_Iterations_Exceeded`). The flag exists so the decision can
            # be measured across every case at once instead of one subset at a time, which is how the two
            # contradictory verdicts of 4 August were produced.
            if _ENFORCE_PARTS_LE_WHOLE:
                opti.subject_to(xk[sym.W_RES] + xk[sym.W_HOL] <= xk[sym.W_R])

    # --- one CVaR surrogate per goal, each at its own deadline step (eq. 8.4) ---
    #
    # **The CVaR auxiliaries are deliberately NOT seeded, and that is a measured decision, not an omission.**
    #
    # `z_g` and `s_g` default to zero, which violates `s_g >= L_m - z_g` by the size of the shortfall, so
    # `inf_pr` starts at 3.69e+04 on the flagship rather than at 0. Seeding them from the definition of CVaR at
    # the seeded trajectory — `z_g` at the (1-eps) quantile of the losses, `s_g` at the hinge above it — looks
    # like the obvious completion of the state seeding above, and it makes the flagship **worse**:
    #
    #     unseeded auxiliaries   Solve_Succeeded              226 iters   cvar 13 267
    #     seeded auxiliaries     Maximum_Iterations_Exceeded   400 iters   cvar 3.35e+04
    #
    # Both measured at `M=32, seed=0`, everything else identical. The likely reason is that these rows carry
    # explicit slack variables, so IPOPT repairs them cheaply by moving the slacks, whereas a seeded `z_g` starts
    # the barrier from a point that is feasible but far from the optimal quantile — trading a violation IPOPT is
    # good at fixing for a position it is not. Left unseeded until someone has a better theory AND a measurement.
    cvar_primary = None
    for gi, g in enumerate(goals_all):
        kg = _goal_step(g)
        z_g = opti.variable()
        s_g = opti.variable(M)
        tail = 0
        for m in range(M):
            L_m = -g.symbolic_slack(X[m][kg], U[kg - 1], p)
            opti.subject_to(s_g[m] >= 0)
            opti.subject_to(s_g[m] >= L_m - z_g)
            tail = tail + s_g[m]
        cvar_g = z_g + tail / (g.epsilon * M)
        if objective == "utility":
            opti.subject_to(cvar_g <= cvar_bound)
        if gi == 0:
            cvar_primary = cvar_g
    cvar = cvar_primary

    # --- objective: SAA discounted utility + terminal bequest (eq. 9.2) ---
    J = 0
    for m in range(M):
        acc = 0
        for k in range(K):
            disc = ca.exp(-p.rho * k * dt_opt)
            u = U[k]
            leisure = 1.0 - (u[0] + u[1] + u[2] + u[3])
            # **Habit-adjusted consumption, book eq. 30.4: `z = C - h*kappa`.** Added 25 August 2026 with the
            # habit stock (M80 decision 2). `h` is fixed at 0.70 and is not a free choice: §30.3 shows that
            # setting it to one makes the objective unbounded below along its own equilibrium path.
            #
            # Floored at a small positive share of `c_ref` before the CRRA, because `z` can go negative during
            # a line search — consumption below the habit is a real state, and `z^(1-gamma)` at gamma = 3 is a
            # pole rather than a large number. The floor is what keeps that a steep penalty instead of a NaN.
            z = ca.fmax(u[sym.C] - p.habit_intensity * X[m][k][sym.KAPPA], _HABIT_FLOOR * c_ref)
            u_c = _crra(z / c_ref, gamma)
            v = _crra(leisure * X[m][k][sym.H], _GAMMA_V)
            acc = acc + disc * (u_c + psi * v) * dt_opt
        omega = X[m][K][sym.W_L] + X[m][K][sym.W_R] - X[m][K][sym.D]
        acc = acc + ca.exp(-p.rho * horizon_years) * bequest_weight * _crra(omega / c_ref, gamma)
        J = J + acc
    J = J / M
    if objective == "min_shortfall":
        opti.minimize(cvar_primary)      # phase 1: restore feasibility, no give-up basin
    else:
        opti.minimize(-J)                # phase 2: best life subject to the funding bound

    # --- warm start ---
    #
    # **The state seed is rolled out PER SCENARIO, under that scenario's own shocks, from 4 August 2026.**
    #
    # It used to seed every one of the `M` scenarios with the same *deterministic* rollout (`ws_states`, a
    # noise-free `simulate`). But `X[m][k+1] == euler_step(X[m][k], U[k], Z[m,k], ...)` is a shocked equality per
    # scenario, so a noise-free seed violates it by the size of the noise — measured at **inf_pr = 9.85e+05** at
    # iteration 0 on the flagship, since `sigma_R` acts on `W_R = 5e6`.
    #
    # IPOPT spent ten iterations failing to close that gap, entered the feasibility restoration phase at
    # iteration 11 and **never left it**: every remaining iteration to 400 was a restoration iteration, with the
    # objective frozen to eight significant figures and steps of 1e-4 accepted at full length. That is why 3000
    # iterations returned the identical objective to 400 — it was not a budget that was slightly too small, it
    # was a solve locked in restoration from a start it could not repair.
    #
    # Seeding through `sym.euler_step` itself — the very expression the constraint imposes — rather than through
    # the numpy `simulate` twin makes the dynamics residual exactly zero at the initial point rather than
    # approximately zero. The two transcriptions agree to 1e-9, which is small for parity and not small next to a
    # barrier method's feasibility restoration trigger.
    # Set on `Us`/`Xs` — the actual decision variables — divided by the same scales the expressions multiply back.
    # When `_SCALE_NLP` is off these are the same objects and the scales are all 1, so this is the plain seed.
    _uv0 = np.array([ws_u.tau_Y, ws_u.tau_E, ws_u.tau_N, ws_u.tau_H,
                     ws_u.C, ws_u.m_E, ws_u.m_N, ws_u.p_A, ws_u.theta], dtype=float)
    for k in range(K):
        opti.set_initial(Us[k], _uv0 / su)

    # **A non-finite seed is refused HERE, with a sentence, rather than by CasADi with an assertion.**
    #
    # Measured 6 August 2026 on a real submission (Zug, 26-year horizon, `M_opt=32`): after roughly 74 minutes
    # of CPU the run died inside `Opti::set_initial` with
    #
    #     Assertion "v.is_regular()" failed ... Notify the CasADi developers.
    #
    # That message is wrong twice over. It is not a CasADi defect — the seed genuinely held a NaN or an Inf, and
    # asserting on it is correct behaviour — and it points the reader at the wrong project. Worse, the engine
    # already has a documented outcome for "this household could not be solved": `undetermined`, which the
    # report layer turns into a blocking warning and no published figures. A crash bypasses all of it and
    # returns a stack trace to a caller that was expecting JSON.
    #
    # The seed under the FIRST warm start was verified finite at M = 1, 8 and 32, so the non-finite values arrive
    # under a LATER start — `_solve_case_once` seeds phase 2 with phase 1's own control, and phase 1 is a
    # heuristic restoration solve this file already records as frequently not converging. A control that came
    # back degenerate rolls a 52-step trajectory to infinity.
    #
    # Raising `SolveFailed` rather than clamping is deliberate. A clamped seed would start the solver from a
    # fabricated trajectory and return numbers about a household nobody modelled, which is the failure this
    # codebase keeps paying for. The caller drops this candidate and reports what actually happened.
    for m in range(M):
        for k in range(K + 1):
            seed = np.asarray(seed_X[m][k], dtype=float).flatten()
            if not np.all(np.isfinite(seed)):
                bad = [i for i, v in enumerate(seed) if not np.isfinite(v)]
                raise SolveFailed(
                    f"the warm-start rollout went non-finite at scenario {m}, step {k} of {K} "
                    f"(t = {k * dt_opt:g} yr of {horizon_years:g}), in state component(s) {bad}. The control "
                    f"seeding this solve drives the state to infinity over the horizon, so there is nothing to "
                    f"start the optimiser from. This is a determination about the solve, not about the "
                    f"household: no figure may be quoted from it."
                )
            opti.set_initial(Xs[m][k], seed / sx)

    opts = {
        "ipopt.max_iter": max_iter, "ipopt.tol": 1e-6,
        "ipopt.mu_strategy": "adaptive",        # more robust barrier updates
        "ipopt.acceptable_tol": 1e-4,           # accept a good-enough iterate
        "ipopt.acceptable_iter": 8,
    }
    if not verbose:
        opts.update({"ipopt.print_level": 0, "print_time": 0, "ipopt.sb": "yes"})
    # Escape hatch for solver tuning experiments, so comparing barrier strategies or tolerances does not mean
    # editing this function between runs. Callers in the engine leave it alone; it exists because the settings
    # above were chosen once and never compared against alternatives on this problem.
    if extra_opts:
        opts.update(extra_opts)
    opti.solver("ipopt", opts)

    success = True
    status = "Solve_Succeeded"
    try:
        sol = opti.solve()
    except RuntimeError:
        # IPOPT "Solved_To_Acceptable_Level" is a usable solve even though CasADi
        # raises; only treat a genuine failure (max-iter, infeasible, error) as
        # non-convergence. The applied iterate comes from the debug handle.
        sol = opti.debug
        try:
            status = opti.stats().get("return_status", "")
        except Exception:
            status = ""
        success = status == "Solved_To_Acceptable_Level"

    # `return_status` and `iter_count` recorded from 4 August 2026. Without them a failed solve was
    # indistinguishable from a bad one: `success=False` said only "not converged", never *why*, so
    # max-iter-exceeded, infeasible and restoration-failed all looked alike from the caller. Two wrong
    # diagnoses of the flagship's `p_goal` collapse were made for want of this one string.
    try:
        _st = opti.stats()
        iter_count = int(_st.get("iter_count", -1))
    except Exception:
        iter_count = -1

    def _named(u):
        return dict(tau_Y=float(u[0]), tau_E=float(u[1]), tau_N=float(u[2]), tau_H=float(u[3]),
                    C=float(u[4]), m_E=float(u[5]), m_N=float(u[6]), p_A=float(u[7]), theta=float(u[8]))

    u0 = np.array(sol.value(U[0])).flatten()
    u0_named = _named(u0)
    u_path = [_named(np.array(sol.value(U[k])).flatten()) for k in range(K)]

    # costates: sum of initial-condition duals across scenarios (∂J*/∂x0).
    # Sized from `sym.NX` rather than a literal — this was a hardcoded 6 and was the last place the state
    # dimension was restated, found by `test_optim` when age made the vector 7 (PLAN_2026-08.md §0B step 1).
    lam = np.zeros(sym.NX)
    if success:
        for rel in init_cons:
            lam += np.array(sol.value(opti.dual(rel))).flatten()
    costates = Costates(lam_W=float(lam[sym.W_L]), lam_E=float(lam[sym.E]),
                        lam_N=float(lam[sym.N]), lam_H=float(lam[sym.H]))

    # exchange rate at (x0, u0) (spec §13).
    E0, N0, H0 = x0v[sym.E], x0v[sym.N], x0v[sym.H]
    K_N0 = p.K_N0 * (1.0 + p.lambda_E * E0
                     + p.lambda_W * (x0v[sym.W_L] + x0v[sym.W_R]) / p.W_scale)
    dN_dtauN = p.alpha_N * (1.0 - N0 / K_N0)
    dY_dtauY = dyn.earning_power(E0, N0, x0.person.age, p) * H0 ** p.c
    xr = ExchangeRate(
        goal=goal.name,
        networking_value=abs(costates.lam_N) * dN_dtauN,
        overtime_value=abs(costates.lam_W) * dY_dtauY,
    )

    kg0 = _goal_step(goal)
    slacks = np.array([
        float(sol.value(goal.symbolic_slack(X[m][kg0], U[kg0 - 1], p)))
        for m in range(M)
    ])
    p_fi = float(np.mean(slacks >= 0))

    # --- The CVaR constraint has to actually hold, not merely have been asked for -----------------------
    #
    # **`success` used to mean only "IPOPT did not fail", and that was not enough.** Measured 3 August 2026 on
    # the flagship case at M=16: `cvar_shortfall` came back at 1.06e4, 2.22e4 and 4.34e4 against a bound of
    # 1e-3 — violated by seven orders of magnitude — with `success = True` on every one of them, and
    # out-of-sample confidence collapsing to 0.555 and 0.273 as a result. The plans were not bad answers to
    # the stated problem; they were answers to a problem with no effective tail constraint.
    #
    # How it got through: when `opti.solve()` raises, the handler above accepts
    # `Solved_To_Acceptable_Level`. IPOPT's *acceptable* level relaxes its tolerances — **including
    # constraint violation** — so a large breach is a legitimate "acceptable" termination as far as the
    # solver is concerned. Trusting that status alone imports the solver's idea of good enough into a claim
    # the advice layer reads as "this plan meets the confidence target".
    #
    # It is not local optima: `n_starts=8` reproduces `n_starts=3` byte for byte. It is scenario count —
    # `M=32` collapses the seed spread from 0.585 to 0.032 — so the honest fix is more scenarios, and this
    # gate is what stops too few from passing silently while that is calibrated.
    #
    # The tolerance is scaled by the target spend because the shortfall is a money quantity: 1e-6·G is about
    # CHF 0.09 a year at G = 90 000, which is generous against real violations of O(1e4) and immune to the
    # last few digits of a solve that pins the bound exactly. `test_optim.py` had been asserting this on one
    # `M` value all along and caught it there first; the guard belongs here so every caller inherits it.
    #
    # **The gate applies only where the constraint exists (corrected 5 August 2026, M79).** In
    # `min_shortfall` mode no CVaR constraint is imposed — the shortfall is the *objective* — so comparing it
    # against `cvar_bound` there tested a constraint the NLP never contained, and flipped every converged
    # phase-1 solve of an underfunded goal to `success = False`. That silently defeated
    # `p1_ok = [c for c in phase1 if c.success] or phase1` in `_solve_case_once`: with every candidate
    # failing, the `or` branch took the minimum over *unconverged* solves too, which is precisely the M75
    # four-fold error (52 687 reported against a true 13 267). Phase 1's `success` now means what the caller
    # needs it to mean: this solve converged, so its shortfall can be believed.
    cvar_value = float(sol.value(cvar))
    cvar_tol = max(1e-6, 1e-6 * abs(p.G))
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
               "n_var": opti.nx, "n_con": opti.ng},
        u_path=u_path, dt_opt=dt_opt,
    )


def _default_starts(G: float) -> list[Control]:
    """A diverse spread of warm starts spanning the plausible policy space — enough
    to escape the poor local optima a single start can fall into (e.g. the
    'barely work' basin). Each is rolled out to seed the state trajectory."""
    return [
        Control(0.45, 0.05, 0.10, 0.20, min(G, 100_000), 3_000, 5_000, 0.0, 0.40),  # balanced
        Control(0.55, 0.05, 0.05, 0.15, 0.55 * G, 2_000, 3_000, 0.0, 0.30),          # work & save
        Control(0.35, 0.15, 0.15, 0.20, 0.70 * G, 5_000, 8_000, 0.0, 0.50),          # invest capitals
        Control(0.50, 0.02, 0.05, 0.25, 0.45 * G, 1_000, 2_000, 0.0, 0.20),          # frugal
    ]


def _restore_starts(G: float) -> list[Control]:
    """Aggressive 'try hardest to fund the goal' warm starts for the phase-1
    feasibility-restoration solve: work and save hard, invest for growth. These
    guarantee the good (goal-funding) basin is in the start set, which is what the
    old single-phase solver lacked — it could only fall into a give-up basin."""
    return [
        Control(0.60, 0.05, 0.05, 0.10, 0.30 * G, 1_000, 1_000, 0.0, 0.55),  # save hard, risk-on
        Control(0.50, 0.10, 0.12, 0.18, 0.40 * G, 3_000, 5_000, 0.0, 0.45),  # save + build capitals
    ]


def _control_from_named(u: dict) -> Control:
    return Control(u["tau_Y"], u["tau_E"], u["tau_N"], u["tau_H"],
                   u["C"], u["m_E"], u["m_N"], u["p_A"], u["theta"])


def solve_case(
    x0: State,
    goal: GoalSpec,
    *,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    starts: list[Control] | None = None,
    n_starts: int = 3,
    restore_starts: int = 2,
    cvar_tol: float = 1e-3,
    seed_retries: int = 3,
    **kwargs,
) -> SolveResult:
    """Two-phase multistart solve (spec §11; the solver-reliability fix).

    PHASE 1 — feasibility restoration. Minimise the primary goal's CVaR shortfall
    from aggressive warm starts. The min-shortfall objective has no give-up
    incentive, so it reliably finds the best achievable funding ``s*`` and an
    aggressive action to seed phase 2. This is what stops the old failure mode
    where a hard goal collapsed the applied plan into 'consume instead' (P≈0).

    PHASE 2 — best life, funded. Maximise SAA utility subject to CVaR ≤ bound,
    where ``bound = tol`` when the goal is feasible (``s* ≤ 0``, full funding
    enforced) and ``bound = s* + tol`` when it is not (get as close as the problem
    allows). Because the bound is achievable by construction and the restore action
    seeds the good basin, the applied plan and its out-of-sample P respond smoothly
    to parameters instead of jumping between 'achieve' and 'give up'.

    Selection: among converged candidates meeting the bound, take the highest
    objective (best life, goal funded to the achievable level).
    """
    p = params or Params()
    if starts is None:
        starts = _default_starts(p.G)[:max(1, n_starts)]

    # --- REDRAW THE SCENARIOS WHEN A DRAW TURNS OUT TO BE PATHOLOGICAL --------------------------------
    #
    # **The solver's difficulty is not monotone in the problem size; it lives in the specific scenario draw.**
    # Measured on a real submission with a 20-year horizon (`K = 20`):
    #
    #     M    status                       iters   cvar        vars
    #      8   Solve_Succeeded                 35   -2.714      2 037
    #     12   Solve_Succeeded                 34   -3.498      2 965
    #     16   Maximum_Iterations_Exceeded    400   14 569      3 893
    #     24   Solve_Succeeded                 52   -4.111      5 749
    #     32   Maximum_Iterations_Exceeded    400   41.1        7 605
    #
    # M=24 converges in 52 iterations while M=16 exhausts 400. That is not a size threshold, and M11 had already
    # recorded the same shape a week earlier: "M=12 converges in 288 iterations and M=16 in 248, but M=14 needs
    # more than 1000". A draw that happens to make the CVaR constraint nearly degenerate costs a solve.
    #
    # **The seed is an arbitrary choice, so redrawing is legitimate rather than a workaround.** The in-sample
    # draw only has to BE a valid sample of the scenario distribution; nothing about the answer depends on which
    # sample, and `run_case` already scores out-of-sample on a different seed entirely. Where the same case
    # converges under several draws it lands on the same answer (-2.7, -3.5, -4.1 above, all funded), so this
    # picks a draw the solver can handle rather than a draw that flatters it.
    #
    # The seed actually used is recorded in `stats`, because a result nobody can reproduce is not a result.
    base_seed = kwargs.pop("seed", 0)
    attempts: list[SolveResult] = []
    for attempt in range(max(1, seed_retries)):
        seed = base_seed + 1_000 * attempt
        res = _solve_case_once(x0, goal, params=p, extra_goals=extra_goals, starts=starts,
                               restore_starts=restore_starts, cvar_tol=cvar_tol, seed=seed, **kwargs)
        res.stats["seed"] = seed
        res.stats["seed_attempt"] = attempt
        attempts.append(res)
        if res.success:
            return res
        # **An unfundable goal is not redrawn (M79).** Redraw exists for solver pathology — a draw that makes
        # the CVaR constraint nearly degenerate costs a solve, and the seed is arbitrary, so picking another
        # sample of the same distribution is legitimate. Redrawing a goal the model has determined it cannot
        # fund would be a different act entirely: `s_star` varies by a factor of 2.3 across draws on the
        # flagship (29 032 at seed 0, 65 924 at seed 4), so retrying until one draw comes back fundable is
        # shopping for a scenario sample that flatters the answer. The determination stands on the draw it was
        # made on, and the draw is recorded.
        if res.stats.get("outcome") == "goal_not_fundable":
            return res
    # Every draw failed. Return the best of them so the caller still gets its `return_status` and can say why,
    # rather than a bare exception that discards the diagnosis.
    best = min(attempts, key=lambda c: (not c.success, c.cvar_shortfall))
    best.stats["seed_attempts_exhausted"] = len(attempts)
    return best


def _solve_case_once(
    x0: State,
    goal: GoalSpec,
    *,
    params: Params | None = None,
    extra_goals: list[GoalSpec] | None = None,
    starts: list[Control] | None = None,
    restore_starts: int = 2,
    cvar_tol: float = 1e-3,
    **kwargs,
) -> SolveResult:
    """One two-phase solve at one scenario draw. `solve_case` wraps this with the redraw loop."""
    p = params or Params()
    starts = starts or _default_starts(p.G)

    # **The fundability tolerance scales with the goal's money, because a sub-franc shortfall is not a
    # shortfall.** Measured 5 August 2026 on a real submission: `s_star` came back between 1e-3 and 0.5 against
    # the fixed `cvar_tol = 1e-3`, so the gate below fired and the report told the household its goal was "not
    # within the limits of this household's resources" and quantified the miss as **CHF 0 a year**. A
    # determination that reads "you cannot afford this, by nothing" is worse than no determination: it is the
    # right machinery reporting solver noise as a finding.
    #
    # One part in 100 000 of the annual target — 90 centimes on a 90 000 goal — is the floor for calling
    # something a shortfall. The same widened value is used as phase 2's bound so the two agree: if the gate
    # would not call a miss of this size a shortfall, phase 2 must not refuse a plan for it either. `p.G` is the
    # engine's own consumption scale, which is what makes this a relative tolerance rather than a new constant.
    cvar_tol = max(cvar_tol, 1e-5 * abs(p.G))

    # --- phase 1: how well *can* this goal be funded? ---
    #
    # `_try_solve` swallows `SolveFailed` into `None`. A warm start whose rollout goes non-finite is a dead
    # candidate, not a dead household: with three starts, one failing and two solving is a solved case, and
    # before 9 August 2026 the first failure took the whole process down with a CasADi assertion. The reasons
    # are kept so that a case where EVERY start fails can say why rather than merely that.
    failures: list[str] = []

    def _try_solve(**kw):
        try:
            return _solve_once(x0, goal, params=p, extra_goals=extra_goals, **kw)
        except SolveFailed as exc:
            failures.append(str(exc))
            return None

    restore_warms = _restore_starts(p.G)[:max(1, restore_starts)]
    phase1 = [c for c in (_try_solve(warm=w, objective="min_shortfall", **kwargs)
                          for w in restore_warms) if c is not None]
    if not phase1:
        raise SolveFailed("every phase-1 warm start failed to start:\n  " + "\n  ".join(failures))
    p1_ok = [c for c in phase1 if c.success] or phase1
    best_restore = min(p1_ok, key=lambda c: c.cvar_shortfall)
    s_star = best_restore.cvar_shortfall
    restore_converged = (best_restore.success
                         and best_restore.stats.get("return_status") == "Solve_Succeeded")

    # --- phase 2: best life, goal funded at the requirement that was actually asked for -------------------
    #
    # **The bound is `cvar_tol`. It used to be `s_star + cvar_tol` when phase 1 could not fully fund the goal,
    # and that made the constraint a function of the scenario draw** — see M79. On the flagship at its
    # calibrated `M_opt=32`, two draws certified `success = True` against requirements tens of thousands of
    # francs a year apart, and out-of-sample confidence landed at 0.82 and 0.3025 on the same household with
    # the same goal. A satisfied constraint whose bound nobody chose is not the claim the advice layer reads
    # it as. The decision (user's, 5 August 2026): **if a plan is not feasible, drop it and state that it is
    # not within the limits.** So there is no bound-relaxing path.
    #
    # **PHASE 2 RUNS EVEN WHEN PHASE 1 SAYS THE GOAL IS UNDERFUNDED, and the first cut of this got that
    # wrong.** It short-circuited on `s_star > cvar_tol` and returned the determination without ever trying
    # the properly-bounded problem. That is not the same rule: it decides feasibility from phase 1's estimate
    # rather than from an attempt. Phase 1 is a *heuristic* restoration solve, and on this model it frequently
    # does not converge — measured 5 August 2026 at `max_iter=400`, every phase-1 solve of the flagship hit
    # `Maximum_Iterations_Exceeded`, and two warm starts at the SAME draw reported 52 687 and 29 032. Trusting
    # that to veto phase 2 would refuse a plan the properly-bounded solve might well certify, and 52 687 is
    # verbatim the number M75 recorded as an unconverged restore's answer against a true 13 267.
    bound = cvar_tol
    phase2_starts = [_control_from_named(best_restore.u0), *starts]
    cands = [c for c in (_try_solve(warm=w, objective="utility", cvar_bound=bound, **kwargs)
                         for w in phase2_starts) if c is not None]
    if not cands:
        raise SolveFailed("every phase-2 warm start failed to start:\n  " + "\n  ".join(failures))

    # `success` already implies the bound holds — the M70 gate compares `cvar_shortfall` against `cvar_bound`,
    # which is now `cvar_tol` — so this is "a certified, funded plan exists".
    meets = [c for c in cands if c.success and c.cvar_shortfall <= bound + cvar_tol]
    if meets:
        best = max(meets, key=lambda c: c.objective)
        best.stats["s_star"] = s_star
        best.stats["cvar_bound"] = bound
        best.stats["restore_converged"] = bool(restore_converged)
        best.stats["outcome"] = "plan"
        return best

    # --- no funded plan could be certified. WHICH of the two reasons is it? -------------------------------
    #
    # Only a CONVERGED phase 1 can distinguish them. If it converged and still could not fund the goal, the
    # goal is out of reach and `s_star` is the quotable shortfall — the determination the user asked for. If it
    # did not converge, nothing numeric may be claimed: the shortfall would be a stalled iterate, wrong by a
    # factor of four in the case M75 measured, and two warm starts at one draw disagreed by 1.8x.
    #
    # The determination returns phase 1's own solve, because that is the object the claim is about. Its `u0` is
    # NOT a plan — it maximises funding rather than this household's life — so `success` stays False and the
    # report layer withholds the action. `outcome` is what a caller reads to say WHY there is no plan.
    if restore_converged and s_star > cvar_tol:
        best_restore.success = False
        best_restore.stats["s_star"] = s_star
        best_restore.stats["cvar_bound"] = bound
        best_restore.stats["restore_converged"] = True
        best_restore.stats["outcome"] = "goal_not_fundable"
        # **`shortfall_annual` was the raw CVaR, and the raw CVaR is not in francs for three of the four goal
        # kinds.** `report.ReportFacts.shortfall` documents itself as "annual CHF by which the goal is missed"
        # and prints it as `CHF {x:,.0f} a year` in a client-facing warning. Only the FI slack is money: it is
        # `y_R·W_inv + swr·Ω_draw − G`, so a shortfall of 13 267 really is 13 267 francs. The retirement slack
        # is `assets/(G_ret·af) − 1`, a dimensionless funding-ratio deficit, so a shortfall of 0.42 was being
        # printed as "CHF 0 a year" — the machinery reporting a 42% funding gap as nothing. Home and company
        # are normalised the same way.
        #
        # `amount_deficit` is the single definition of that conversion and is shared with `optim.achievable`,
        # which needs the identical mapping to seed its search. Two copies of this would be M67 again.
        from .achievable import amount_deficit  # noqa: PLC0415 - circular at module load
        stated_amount = float(goal.params.get(
            {"fi": "G", "retirement": "G_ret", "home": "price", "company": "B_buffer"}[goal.kind], p.G))
        best_restore.stats["shortfall_annual"] = amount_deficit(goal.kind, stated_amount, s_star)
        best_restore.stats["shortfall_cvar_raw"] = s_star
        return best_restore

    best = max(cands, key=lambda c: c.objective)
    best.success = False
    best.stats["s_star"] = s_star
    best.stats["cvar_bound"] = bound
    # **Which of the two undetermined states this is, recorded rather than reconstructed.** `undetermined` is
    # reached two ways and they mean opposite things. If phase 1 did NOT converge, nothing numeric may be
    # claimed and `s_star` is a stalled iterate. If it DID converge with `s_star <= cvar_tol` -- phase 1 says
    # the goal is fundable -- and phase 2 still certified nothing, then the goal is within reach and the
    # optimiser failed on the household's own problem, which is a solver defect and not a finding about the
    # household. Without this flag the two are indistinguishable downstream, which is why no diagnosis of an
    # `undetermined` risk assessment has been possible.
    best.stats["restore_converged"] = bool(restore_converged)
    best.stats["outcome"] = "undetermined"
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
    **kwargs,
) -> SolveResult:
    """Back-compatible FI entry point — a thin GoalSpec wrapper over solve_case."""
    p = params or Params()
    goal = GoalSpec(kind="fi", horizon_years=horizon_years, epsilon=epsilon,
                    params=dict(G=p.G if G is None else G,
                                swr=p.swr if swr is None else swr,
                                h_res=p.h_res if h_res is None else h_res))
    return solve_case(x0, goal, params=p, **kwargs)
