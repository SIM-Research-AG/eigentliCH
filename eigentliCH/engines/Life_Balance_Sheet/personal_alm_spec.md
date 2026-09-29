# Personal Asset–Liability Management as Stochastic Optimal Control

**A build specification for a consumer-facing life-planning engine**

Version 0.1 · Draft for implementation via Claude Code
Author context: Nicolas Bürkler (control systems / ALM background) — this document is written to be read by a developer and turned directly into code.

---

## 0. How to read this document

This is an implementation spec, not a paper. It is organised so that a developer (or Claude Code) can build modules in dependency order:

1. **State & controls** (Sections 3–4) → data structures.
2. **Dynamics** (Section 5–6) → the simulator.
3. **Goals & feasibility** (Sections 7–8) → the constraint layer.
4. **Objective & optimisation** (Sections 9–11) → the solver.
5. **MPC loop** (Section 12) → the runtime.
6. **Outputs** (Sections 13–14) → the consumer layer.
7. **Nicolas calibration** (Section 15) → the backtest fixture.
8. **Engineering notes** (Section 16) → module layout, libraries, tests.

Every parameter has a symbol, a default value, and a "to calibrate" flag. Defaults are illustrative and chosen to make the system runnable on day one, **not** empirically fitted.

---

## 1. Purpose & scope

We model an individual's life-planning problem as the control of a **stochastic dynamical system**: several *capitals* (wealth, expertise, network, health) evolve over time, driven by how the person allocates two scarce budgets — **time** and **money** — and buffeted by random shocks (markets, career, health). *Goals* (buy a home, found a company, retire) are treated as **liabilities**: claims that must be met, on time, with a required level of confidence.

The engine answers three questions:

- **Feasibility** — "Can I still reach each goal, and with what probability?"
- **Prescription** — "Given where I am today, what should I do *this period*?"
- **Valuation** — "Right now, what is an hour of networking worth toward my founding goal, versus an hour of overtime?" (the shadow-price / exchange-rate output).

### Design decisions (locked)

| # | Decision | Choice | Consequence |
|---|----------|--------|-------------|
| 1 | Purpose | **Prescriptive optimiser** | We solve an optimal-control problem, not just simulate. |
| 2 | Capitals | **Distinct dimensions** (not collapsed to money) | Goals are *regions* in state space; multi-dimensional feasibility. |
| 3 | Uncertainty | **Stochastic** | Dynamics are SDEs; feasibility is a *probability*; constraints are *chance constraints*. |
| 4 | Coupling | **Proposed defaults** (Section 6) | Editable graph; domain content lives in one place. |
| 5 | End user | **Consumer** | No raw HJB. Optimiser runs as **Model-Predictive Control** (receding horizon): re-solve each period, output only this period's action. |

The consumer requirement is load-bearing. A consumer cannot be handed a global stochastic optimal-control solution. Instead the engine **re-solves a finite-horizon problem each period from the current observed state and applies only the first action** — this is what makes it robust to "life happened" and keeps each interaction cheap.

---

## 2. Notation conventions

- Time `t` in **years**; simulation step `Δt` (default **1/12**, monthly).
- Money in **CHF**.
- Capital indices `E, N, H` are **dimensionless**, normalised so a well-developed professional sits near `1.0` (they may exceed 1 where coupling lifts the ceiling).
- Random increments `dB_•` are independent standard Brownian motions unless a correlation matrix `Σ_B` is supplied.
- Subscripts: `L` liquid, `R` real/illiquid, `P` portfolio.

---

## 3. State variables

The state `x(t)` is a vector. The wealth block is split into three pieces because Nicolas's own history (a trading system funding a property purchase, later leveraged) is impossible to model honestly with a single scalar `W`.

| Symbol | Name | Unit | Range | Notes |
|--------|------|------|-------|-------|
| `W_L` | Liquid financial wealth | CHF | ≥ 0 | Cash + marketable portfolio. Subject to portfolio return. |
| `W_R` | Real / illiquid assets | CHF | ≥ 0 | Property, private stakes. Appreciates, yields, illiquid. |
| `D`   | Debt (mortgage etc.) | CHF | ≥ 0 | Serviced from cash flow; interest + amortisation. |
| `E`   | Expertise / human capital | index | ≥ 0 | Redirectable across domains (see §3.1). |
| `N`   | Network / social capital | index | ≥ 0 | Ceiling raised by `E` and wealth. |
| `H`   | Health / energy capital | index | [0, 1] | Modulates income; decays under overwork. |

**Derived quantities** (not state, computed):

- Net worth `Ω = W_L + W_R − D`.
- Income `Y` (Section 5).
- Saving rate `s = (Y − C) / Y` — **an output, never an input**.

### 3.1 Expertise as redirectable capital (extension flag)

Nicolas's career is serial reinvention (control theory → algorithmic trading → entrepreneurship → information governance). For **v1**, model `E` as a single scalar "professional reputation/expertise capital" that compounds and depreciates. For **v2**, promote `E` to a vector `E = (E_1, …, E_d)` of domain-specific capitals, where a *pivot* seeds a new component `E_j` and existing `N` accelerates its ceiling. Keep the interface ready for this (i.e. don't hard-code `E` as a float everywhere; wrap it).

---

## 4. Control variables

Two budgets, allocated each period.

### 4.1 Time budget (the hard constraint)

Time shares of the productive budget, each in `[0, 1]`:

```
τ_Y  earning / working
τ_E  learning / building expertise
τ_N  networking / relationship-building
τ_H  recovery / health / rest
```

Constraint: `τ_Y + τ_E + τ_N + τ_H ≤ 1`. The slack `τ_L = 1 − Σ τ` is **leisure**, which enters utility.

### 4.2 Money budget

| Symbol | Name | Unit | Notes |
|--------|------|------|-------|
| `C`   | Consumption | CHF/yr | Endogenous → sets the saving rate. |
| `m_E` | Education / skill spend | CHF/yr | Feeds `E`. |
| `m_N` | Network spend | CHF/yr | Feeds `N` (events, memberships, travel). |
| `p_A` | Amortisation payment | CHF/yr | Reduces `D`. |

### 4.3 Financial control

| Symbol | Name | Range | Notes |
|--------|------|-------|-------|
| `θ` | Portfolio risk tilt | [0, 1] | Fraction of `W_L` in the risky asset. Drives `(μ_P, σ_P)`. |

### 4.4 Discrete / event controls

Executed at goal events, not every period:

- **Property acquisition / leverage**: converts `W_L` → `W_R`, takes on `D`. Governed by the down-payment and serviceability rules in Section 7.
- **Company founding**: draws down a buffer, may reduce `τ_Y` in wage employment and raise venture income exposure.

---

## 5. Dynamics (the SDE system)

Not everything is a logistic. **Wealth accumulates; expertise, network and health saturate.** Hence a mixed system.

**Income** (Cobb–Douglas in the productive capitals, scaled by health and work time):

```
Y(E, N, H, τ_Y) = w0 · E^a · N^b · τ_Y · φ(H)
φ(H) = H            (health as a linear efficiency multiplier; H^c optional)
```

**Cash-flow identity** (feeds the liquid wealth SDE):

```
NetCashToLiquid = Y + y_R·W_R − C − m_E − m_N − i·D − p_A
```

**Liquid wealth** (accumulates; portfolio return controlled by θ):

```
dW_L = [ NetCashToLiquid + μ_P(θ)·W_L ] dt + σ_P(θ)·W_L dB_W
μ_P(θ) = r_f + θ·(μ_M − r_f)
σ_P(θ) = θ·σ_M
```

**Real assets** (appreciate + yield, illiquid, own noise):

```
dW_R = μ_R·W_R dt + σ_R·W_R dB_R
```
(Renovation/improvement capex at events adds a jump to `W_R`.)

**Debt** (amortises down; jumps up at leverage events):

```
dD = −p_A dt        (between events; p_A ≥ 0, floored at D ≥ 0)
```

**Expertise** (logistic growth + compounding, with depreciation):

```
dE = [ (α_E·τ_E + κ_E·m_E) + β_E·E ]·(1 − E/K_E) dt − δ_E·E dt + σ_E·E dB_E
```

**Network** (logistic, ceiling raised by expertise and wealth):

```
dN = [ (α_N·τ_N + κ_N·m_N) + β_N·N ]·(1 − N/K_N(E, W)) dt − δ_N·N dt + σ_N·N dB_N
K_N(E, W) = K_N0 · (1 + λ_E·E + λ_W·(W_L + W_R)/W_scale)
```

**Health** (recovers with rest, decays faster under overwork):

```
dH = α_H·τ_H·(1 − H/K_H) dt − δ_H(τ_Y)·H dt + σ_H dB_H
δ_H(τ_Y) = δ_H0 + η·max(0, τ_Y − τ_Y*)
```

The `δ_H(τ_Y)` term is the loop that punishes grinding: high `τ_Y` accelerates health decay, low `H` drags `φ(H)` down, which shrinks effective income. Any honest personal model needs this or it will recommend working 100% forever.

**Discretisation**: Euler–Maruyama.
```
x_{k+1} = x_k + f(x_k, u_k)·Δt + g(x_k, u_k)·√Δt · Z_k ,   Z_k ~ N(0, Σ_B)
```
Clamp indices at their floors (E, N, H ≥ 0; H ≤ K_H) after each step.

---

## 6. Coupling graph (proposed defaults)

Read as "row influences column."

| ↓ influences → | `Y` | `W_L` | `W_R` | `E` | `N` | `H` |
|---|---|---|---|---|---|---|
| `E` | ↑ (exponent `a`) | — | — | self | ↑ ceiling `K_N` | — |
| `N` | ↑ (exponent `b`) | — | — | — | self | — |
| `W` | — | self (return) | self (appn.) | — | ↑ ceiling `K_N` | — |
| `H` | ↑ (factor `φ`) | — | — | — | — | self |
| `τ_Y` | ↑ | (via `Y`) | — | — | — | ↓ (overwork `δ_H`) |
| `τ_E`,`m_E` | — | — | — | ↑ | — | — |
| `τ_N`,`m_N` | — | — | — | — | ↑ | — |
| `τ_H` | — | — | — | — | — | ↑ |
| `θ` | — | ↑μ / ↑σ | — | — | — | — |

This graph is the single place domain content lives. Everything else is machinery. Edit here, not in the equations.

---

## 7. Goals as regions

Three archetypes cover the cases named (home, company, retirement). Each goal is `(type, deadline t_k, region g_k, confidence 1 − ε_k)`.

### 7.1 Home — lump claim **and** serviceability

A property purchase at price `P` at time `t_home` is feasible iff:

```
Down payment:    W_L ≥ ξ · P                      (ξ = 0.20, of which ≥ half non-pension)
Serviceability:  i_calc·D_new + p_A_req + maint ≤ (1/3) · Y_annual
                 with D_new = (1 − ξ)·P, stressed rate i_calc ≈ 0.05
```

On execution (jump): `W_R += P`, `D += (1 − ξ)·P`, `W_L −= ξ·P`.
Nicolas's age-36 event is the *leverage* variant: take on `D = 2 000 000`, add renovation value to `W_R`.

### 7.2 Company — a joint region

Founding requires several capitals **simultaneously above threshold** (this is exactly why capitals are not collapsed to money):

```
g_company = { W_L ≥ B_buffer } ∧ { N ≥ N_min } ∧ { E ≥ E_min }
```
Optionally: sustained for a minimum dwell time (avoid a one-period fluke).

### 7.3 Retirement — a liability stream

Not a point but a funding condition on a stream of future claims:

```
Funding ratio  F = ( Ω(t_ret) + PV_income(t_ret) ) / PV_liabilities(t_ret) ≥ 1
PV_liabilities = PV( future consumption + fixed claims ), discounted at r_disc
```

### 7.4 Financial independence — work becomes *optional*

Distinct from both retirement and "net worth." **FI is the point at which the person could stop earning labor income and still sustain their desired lifestyle** — whether or not they actually stop. Many people (the target user here included) reach FI and keep working *by choice*.

The generic, reusable formulation is a **counterfactual funding ratio**: evaluate the retirement condition (§7.3) at an early date `t_FI`, with future labor income set to zero, over the remaining life horizon:

```
Drawable wealth:   Ω_draw = W_L + h_res·(W_R − D)      # residence you live in counts only at haircut h_res (≈0)
Sustainable non-labor cash flow at t_FI:
                   NL(t) = y_R·W_R + swr·W_L           # asset yield + safe withdrawal (swr ≈ 0.035)
FI condition (any equivalent form):
   (a) flow form:   NL(t_FI) ≥ G                        # passive income covers desired spend G
   (b) stock form:  Ω_draw + PV(non-labor income) ≥ PV(G over remaining horizon)   # funding ratio ≥ 1 with Y_labor ≡ 0
```

Chance-constrained: `P( FI condition holds at t_FI ) ≥ 1 − ε`.

Two properties that make this the *right* generic archetype:

- **It decouples the goal from labor.** The actual trajectory keeps whatever labor income the person chooses to earn — which only helps and provides buffer. The *test* is the counterfactual "could you stop." That is exactly what "independence" means.
- **It exposes the illiquidity trap.** Net worth can clear the bar while *drawable* wealth does not: a large primary residence inflates `Ω` but contributes little to `Ω_draw` (hence the haircut `h_res`). The three-way wealth split (§3) exists precisely so this shows up instead of being hidden. A residence that also *operates* (guest/seminar use) earns a real `y_R·W_R` and partially escapes the trap — the model captures that through the yield term rather than by special-casing.

---

## 8. Feasibility as a chance constraint

For each goal `k`:

```
P( trajectory satisfies g_k by deadline t_k ) ≥ 1 − ε_k
```

Estimated by Monte Carlo over the SDE: simulate `M` scenarios under the current policy, count the fraction meeting `g_k`. This *fraction* is the number the consumer sees as a gauge.

**Making it optimiser-friendly.** Exact chance constraints via scenario counting are mixed-integer and hard. Use the **CVaR surrogate** (Rockafellar–Uryasev), which is convex and conservative:

```
Replace   P(g_k ≥ 0) ≥ 1 − ε_k
by        CVaR_{1−ε_k}[ −g_k ] ≤ 0
```

This is the standard trick in ALM/stochastic programming and is the recommended default. Fall back to a smooth penalty on the shortfall if CVaR is inconvenient in the chosen solver.

---

## 9. Objective function

Maximise expected discounted lifetime utility of consumption **and** leisure, with a terminal bequest/legacy term, subject to the goal chance constraints:

```
max_u  E[ ∫_0^{T_h} e^{−ρ t} ( u(C_t) + ψ·v(τ_L,t · H_t) ) dt  +  e^{−ρ T_h} B(Ω_{T_h}) ]

u(C) = C^{1−γ} / (1 − γ)          (CRRA, γ default 2)
v(·) = leisure·health utility     (concave; weight ψ)
B(Ω) = terminal net-worth utility (bequest / legacy)
```

Plain-language reading for the consumer: *live as well as you can now, while keeping each life goal on track with the confidence you demand.*

---

## 10. The full optimisation problem

At planning time from state `x_0`:

```
maximise   J = E[ Σ_{k=0}^{K-1} e^{−ρ t_k} ( u(C_k) + ψ v_k ) Δt + e^{−ρ T_h} B(Ω_K) ]

over        u_k = (τ_Y, τ_E, τ_N, τ_H, C, m_E, m_N, p_A, θ)_k,  k = 0..K−1

subject to  x_{k+1} = EulerMaruyama(x_k, u_k, Z_k)          (dynamics)
            τ_Y+τ_E+τ_N+τ_H ≤ 1,  all τ ≥ 0                 (time budget)
            C, m_E, m_N, p_A ≥ 0                             (non-negativity)
            W_L ≥ W_buffer                                   (liquidity floor)
            D ≥ 0,  θ ∈ [0,1]
            CVaR_{1−ε_k}[ −g_k ] ≤ 0  for each active goal k (feasibility)
```

---

## 11. Solution method (be honest about tractability)

Do **not** attempt a full HJB solve over a 6-D stochastic state. Two viable routes; **Route A is the recommended v1.**

### Route A — Scenario-based MPC with CVaR (recommended)

1. At the current state, sample `M` exogenous scenarios `{Z^{(m)}}` over the horizon `K` (a scenario *fan*, or a small scenario *tree* for early stages).
2. Solve a single finite-horizon NLP: decision variables are the control path plus first-stage recourse; the expectation in `J` becomes a sample average (SAA); each chance constraint becomes its CVaR surrogate (auxiliary VaR variable + averaged shortfall). Non-anticipativity: the **first-period control is shared across all scenarios**.
3. Solve with an NLP solver (IPOPT). Apply only `u_0`. Advance one real period. Re-solve.

This is the ALM-native formulation (scenario stochastic programming) and will feel familiar to anyone from that world.

### Route B — Parametric policy search (v2, for full nonlinearity)

Represent the policy `u = π_w(x)` (affine or a small neural net in the state), simulate many trajectories, and optimise `w` by cross-entropy method or stochastic gradient. Handles the nonlinear coupling and chance constraints via penalties without linearisation. Heavier, but the endgame if Route A's convexity assumptions chafe.

**Recommendation:** ship Route A first. It is enough for a credible consumer product and for the Nicolas backtest.

---

## 12. The MPC runtime loop

```
initialise x ← observed state (from user onboarding)
for each period k:
    active_goals ← goals not yet met and not past deadline
    (u*, diagnostics) ← solve_finite_horizon(x, active_goals, horizon H)   # §11 Route A
    apply u*_0                     # the only action the consumer sees
    x ← observe_new_state()        # next period: real data if available, else simulate one step
    emit consumer_output(x, u*_0, diagnostics)   # §13
```

Cadence: monthly or quarterly re-solve. Horizon `T_h`: to the last goal's deadline (e.g. retirement), capped for cost (rolling horizon).

---

## 13. Costates → the exchange-rate output

The KKT multipliers on the state-transition constraints of the NLP are the **costates** (shadow prices): the marginal value of one more unit of each capital toward the objective and toward each active goal.

```
λ_E, λ_N, λ_W, λ_H  =  ∂J* / ∂(E, N, W, H)   at the optimum
```

Report **ratios** as intuitive exchange rates, e.g.:

```
value of 1 hour networking toward FOUNDING
   = λ_N · (∂N/∂τ_N)      vs.
value of 1 hour overtime toward FOUNDING
   = λ_W · (∂W/∂τ_Y) · (∂Y/∂τ_Y)
```

Present the *winner* and the *ratio*. This is the single most differentiated output of the whole engine.

---

## 14. Consumer output layer

Hide all math. Surface:

- **Goal gauges** — one probability dial per goal (the Monte-Carlo fraction from Section 8).
- **Work-optional date** — for a financial-independence goal, the earliest age at which `P(FI)` clears the target confidence; paired with the *drawable* net worth vs. total net worth, so the illiquidity gap is visible at a glance.
- **Funding ratio** — one number for the retirement stream (Section 7.3).
- **This period's action** — the applied `u_0`, in plain words: e.g. *"This month: work 55%, 4 h/week networking, save 22%, hold a moderate equity tilt, pay CHF X to the mortgage."*
- **One insight** — the top exchange rate from Section 13: *"Right now, an hour of networking moves you toward founding ~1.8× faster than an hour of overtime."*
- **Early warning** — if any `P(goal)` drops below its target `1 − ε`, flag it and show the single most effective lever.

---

## 15. Nicolas — calibration & backtest fixture

Nicolas's biography is a **realised trajectory** through this exact state space. Use it twice: (a) as a *backtest* — can the dynamics, run forward from age 19 with his actual choices, reproduce his observed states (Rigi Maison equity at 26, CHF 2M leverage at 36, >CHF 5M valuation)? and (b) as the *live use case* for the prescriptive mode going forward.

### 15.1 Life epochs (control history to reproduce)

| Age | Phase | Control emphasis (τ, money, θ) | Event / observed state |
|-----|-------|-------------------------------|------------------------|
| 19 | ETH, control-systems, hardest track; ~60% side work | high `τ_E`, `τ_Y≈0.6`, capex into building a trading system (an S-curve `W`-engine seeded by `E`) | `E` climbing steeply; `W_L` seeded |
| ~24–26 | Trading system runs | `θ` high (system *is* the risky engine); `W_L` compounding | Equity sufficient for property |
| **26** | **Buys Rigi Maison** | leverage/acquisition event | `W_L → W_R`; property becomes both asset **and** network/seminar hub (raises `K_N`) |
| 29 | Founds SIM Research; keeps part-time education job | split `τ_Y`; the education role is deliberately an `E`- and `N`-builder, not just income (the `K_N(E)` coupling) | venture income begins; `N` accelerating |
| 29–36 | Building income + reputation | steady `τ_E`, `τ_N`; `W_R` appreciating | income capacity rising |
| **36** | **CHF 2M mortgage to renovate** | leverage event: `D += 2 000 000`, renovation capex → `W_R` | property valuation later **> CHF 5M** (test `μ_R` + capex) |
| Now | Board seats, sim-tech, Mont Rigi Society, mandates; **pivot to information-governance authority** | high `N` deployed to accelerate a *new* `E`-domain (IG); `τ_Y` fragmented across mandates | the v2 "redirectable `E`" case (§3.1); binding constraint likely **time & `H`**, not money |

### 15.2 What the backtest must show

- Forward simulation with the epoch controls reproduces the three hard observables (equity-funded purchase ~26, 2M leverage at 36, >5M valuation) within a tolerance band → validates `μ_R`, the `E→Y` exponent `a`, and the leverage mechanics.
- The `K_N(E, W)` coupling should show the network ceiling lifting *after* the property purchase and the education role — i.e. the model explains why the network compounded when it did.

### 15.3 Forward (prescriptive) goal — financial independence at 50

The live case is a single primary goal, an instance of the generic §7.4 archetype:

> **From age 45, reach financial independence within 5 years (by age 50), defined as being able to sustain lifestyle spending of CHF 10 000/month (≈ CHF 120 000/yr) without requiring labor income — while continuing to work by choice as a strategist, consultant, and MBA educator.**

Instantiation:

```
t_FI      = now + 5 yr        (age 50)
G         = 120 000 CHF/yr    (desired spend; index for inflation π if modelled)
swr       = 0.035             (safe withdrawal rate on liquid wealth)
h_res     ≈ 0                 (primary residence not drawable; but see yield note)
Y_labor   kept ON in the trajectory (works by choice) — set to 0 only in the FI test
1 − ε     = 0.85–0.90         (confidence — user to confirm)
```

Why this profile is interesting for the model, not trivial:

- **Net worth is likely already "enough"; drawable wealth may not be.** A residence valued well above the spending requirement contributes almost nothing to `Ω_draw`. The engine's job is to show whether the *drawable* side — liquid portfolio plus sustainable yield — clears CHF 120k/yr by age 50, and if not, by how much and via which lever.
- **The operating residence softens the trap.** Guest/seminar use turns part of `W_R` into a genuine `y_R·W_R` cash flow, so the house partly funds itself. This is captured by the yield term, not a special case.
- **The binding constraint is time and health, not capital — a hypothesis to test.** Because labor income continues (and the user *wants* it to), the FI gap is closed largely by directing the strategist/consultant/teaching income into drawable wealth at a sufficient saving rate, without over-loading `τ_Y` to the point where `δ_H(τ_Y)` erodes the health that makes the income possible. The optimiser should surface the saving rate and the work-intensity ceiling, not a demand to grind.

> **Remaining user inputs (see §18):** (1) confidence level `1 − ε`; (2) is the CHF 10k/month *net of* mortgage/debt service, or inclusive? (3) haircut `h_res` — is any equity release from the residence on the table, or strictly excluded?

---

## 16. Engineering notes (for Claude Code)

### 16.1 Suggested module layout

```
personal_alm/
  model/
    state.py         # State dataclass (W_L, W_R, D, E, N, H); helpers Ω, saving rate
    controls.py      # Control dataclass; feasibility of the simplex/budget
    params.py        # Params dataclass + defaults table (§17); "to_calibrate" flags
    dynamics.py      # f(x,u), g(x,u); income Y; K_N coupling; δ_H(τ_Y)
  sim/
    montecarlo.py    # Euler–Maruyama; scenario fan/tree generation; correlation Σ_B
  goals/
    goals.py         # Goal types (lump/region/stream); g_k(x); serviceability rule
    feasibility.py   # MC estimation of P(goal); CVaR surrogate builders
  optim/
    mpc.py           # receding-horizon loop
    problem.py       # NLP assembly (Route A): SAA objective + CVaR constraints
    solver.py        # IPOPT/CasADi interface; returns u*, costates (KKT multipliers)
    policy.py        # Route B parametric policy (v2)
  calibrate/
    nicolas.py       # epoch control history (§15.1); backtest harness & tolerances
  ui/
    output.py        # gauges, funding ratio, plain-language action, exchange-rate insight
  tests/
    test_dynamics.py test_goals.py test_feasibility.py test_backtest_nicolas.py
```

### 16.2 Libraries

- `numpy`, `scipy` — core, SDE integration, PV math.
- `casadi` + IPOPT — the NLP (Route A). CasADi gives autodiff → costates for free.
- `cvxpy` — optional, for convex CVaR subproblems / prototyping.
- `matplotlib` / `plotly` — trajectory fans, gauges (dev + demo).
- `pytest`, `hypothesis` — tests, including property-based invariants (e.g. capitals never negative; time shares ≤ 1).

### 16.3 Numerical guidance

- Start `Δt = 1/12`, `M = 200` scenarios, horizon capped at ~40 yrs rolling. Tune up once correct.
- Seed RNG for reproducible backtests; use **common random numbers** across candidate policies so the optimiser compares like with like.
- Clamp/project states after each step; guard `1 − x/K` from going negative.
- Log costates every solve — they are both a debugging aid and a product feature.

### 16.4 Validation strategy (build in this order)

1. **Deterministic skeleton** — set all `σ = 0`, integrate forward with fixed controls; check the identities balance and the S-curves saturate.
2. **Nicolas backtest** — epoch controls reproduce the three observables (§15.2).
3. **Feasibility layer** — turn on noise; verify MC probabilities move sensibly with controls.
4. **Optimiser** — check it recovers sane allocations on toy goals; verify chance constraints bind at the right `ε`.
5. **MPC loop** — end-to-end; confirm re-planning recovers from an injected shock.

---

## 17. Parameter defaults (illustrative — **all to be calibrated**)

| Symbol | Meaning | Default | Unit |
|--------|---------|---------|------|
| `w0` | Income scale at `E=N=H=1`, full `τ_Y` | 200 000 | CHF/yr |
| `a` | Income exponent on `E` | 0.5 | — |
| `b` | Income exponent on `N` | 0.4 | — |
| `α_E` | Learning rate from time | 0.30 | 1/yr |
| `β_E` | Expertise self-compounding | 0.15 | 1/yr |
| `κ_E` | Learning rate from money | 1e-6 | 1/CHF |
| `δ_E` | Expertise depreciation | 0.03 | 1/yr |
| `K_E` | Expertise ceiling | 1.0 | index |
| `α_N` | Networking rate from time | 0.25 | 1/yr |
| `β_N` | Network self-compounding | 0.20 | 1/yr |
| `κ_N` | Networking rate from money | 1.5e-6 | 1/CHF |
| `δ_N` | Network depreciation (fades fast) | 0.08 | 1/yr |
| `K_N0` | Base network ceiling | 1.0 | index |
| `λ_E` | Ceiling lift from expertise | 0.5 | — |
| `λ_W` | Ceiling lift from wealth | 0.3 | — |
| `W_scale` | Wealth normaliser for `K_N` | 1e6 | CHF |
| `α_H` | Recovery rate | 0.5 | 1/yr |
| `δ_H0` | Baseline health decay | 0.02 | 1/yr |
| `η` | Overwork penalty slope | 0.30 | 1/yr |
| `τ_Y*` | Overwork threshold | 0.5 | share |
| `K_H` | Health ceiling | 1.0 | index |
| `r_f` | Risk-free rate | 0.01 | 1/yr |
| `μ_M` | Risky expected return | 0.06 | 1/yr |
| `σ_M` | Risky volatility | 0.16 | 1/√yr |
| `μ_R` | Real-asset appreciation | 0.03 | 1/yr |
| `σ_R` | Real-asset volatility | 0.08 | 1/√yr |
| `y_R` | Real-asset yield (rent) | 0.02 | 1/yr |
| `i` | Mortgage interest | 0.02 | 1/yr |
| `i_calc` | Stressed serviceability rate | 0.05 | 1/yr |
| `ξ` | Down-payment fraction | 0.20 | — |
| `G` | Desired lifestyle spend (FI target) | 120 000 | CHF/yr |
| `swr` | Safe withdrawal rate (FI) | 0.035 | 1/yr |
| `h_res` | Drawable haircut on residence equity | 0.0 | — |
| `π` | Inflation (spend indexing) | 0.01 | 1/yr |
| `ρ` | Utility discount rate | 0.02 | 1/yr |
| `γ` | CRRA risk aversion | 2.0 | — |
| `ψ` | Leisure-utility weight | tbd | — |
| `Δt` | Simulation step | 1/12 | yr |
| `M` | Monte-Carlo scenarios | 200 | count |

---

## 18. Open questions to resolve before/while building

1. **Confidence & spend definition** — the FI goal is specified (§15.3); still needed: the confidence level `1 − ε`, whether CHF 10k/month is net or inclusive of debt service, and the residence haircut `h_res`.
2. **Correlations** `Σ_B` — do we couple market and real-asset shocks? (Property and equities co-move.) Default: mild positive correlation.
3. **Leisure utility form** `v(·)` and weight `ψ` — how much does the model value not-working? This strongly shapes recommendations.
4. **Venture income** — should company founding switch `Y` from a wage form to an equity/lumpy payoff form? (Matters a lot for the entrepreneurial profile.)
5. **v1 vs v2 on redirectable `E`** — ship scalar `E` first, or invest early in the vector form the IG pivot needs?

---

*End of spec v0.1.*
