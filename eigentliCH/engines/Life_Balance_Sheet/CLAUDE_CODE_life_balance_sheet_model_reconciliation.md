# Claude Code task: reconcile the Life Balance Sheet model across book, program, and docs

## Purpose and scope

We have settled a single canonical formulation of the personal asset-liability (Life Balance Sheet) model. The Notion working note "A Life as an Optimal-Control Problem" has already been rewritten to this canonical form and is the reference statement. Your job is to bring the files in this repository into line with it, surgically, preserving each document's voice and structure.

Two decisions were locked and must be applied everywhere:

1. **Habit is on by default**, and it is a stock with consequences, not a bare reference point.
2. **The first portfolio role is named "Gain"**, not "Growth", everywhere.

**Do not** introduce em-dashes anywhere in prose (house style, this is a hard rule). Use commas or parentheses. Do not fabricate market data. Keep the first-person-plural analytical register the book already uses.

### Files you should edit 

- `The_Life_Balance_Sheet_Book_source.html` (the book, primary target)
- `life_balance_sheet_dashboard.html` (the program UI)
- `Schulung_Life_Balance_Sheet.html`, `Training_Life_Balance_Sheet.html` (training material)



---

## 0. The canonical model (source of truth)

Implement and describe exactly this. Where the book already matches, leave the prose alone and change nothing.

### State: four capitals, wealth split three ways, plus a habit

```
x = ( W_L , W_R , D , E , N , H , κ | m )
```

- `W_L` liquid financial wealth, `W_R` real or illiquid assets (residence, private stakes), `D` debt. Net worth `W = W_L + W_R − D` is derived, not carried.
- `E` expertise, `N` network, `H` health, each in [0,1]. `H` multiplies the productivity of everything.
- `κ` (kappa) consumption habit, a standard-of-living stock. **On by default.**
- `m` macro regime (five phases boom to crisis). **Optional layer**, off by default in the lean model, on when the cycle view is part of the mandate.

Symbol discipline, apply consistently:
- `H` means **health**. Expertise is `E`. Never use `H` for human capital.
- `θ` (theta) means the **portfolio risk tilt** (a control), never the habit.
- `κ` (kappa) means the **habit**. Never reuse `κ` for a liquidity haircut in the same passage without disambiguation; if a haircut symbol is needed, use `h_R` for the real-asset haircut rather than `κ_R`.

### Controls: two budgets and a portfolio

```
u = ( τ , C , m_E , m_N , p_A , w | jumps )
```

- Time budget `τ = (τ_Y, τ_E, τ_N, τ_H)`, non-negative, summing to at most one, slack is leisure `τ_L`.
- Money flows: consumption `C`, education spend `m_E`, network spend `m_N`, amortisation `p_A`.
- Portfolio `w = (w_G, w_I, w_S, w_P)` over the four roles **Gain, Income, Stabilization, Protection**, cash the residual. When the regime layer is off, `w` collapses to the scalar risk tilt `θ` the book already uses (two blocks, risky and safe). When on, it is the four-role vector.
- Discrete jumps: leverage to acquire property, founding a company.
- The saving rate is an **output** of the money flows, not a control. **Time is the binding constraint.**

### Dynamics (deltas from the current book)

Income unchanged: `Y = A_Y · τ_Y · φ(H) · E^a · N^b`, `a, b < 1`.

Liquid wealth carries role- and regime-dependent returns when the regime layer is on:

```
dW_L = [ F + W_L ( r_f + wᵀ(μ_m − r_f·1) ) ] dt + W_L · wᵀ Σ_m^{1/2} dB
```

with `F` the net cash flow. Off, `μ_m, Σ_m` are constant and `w` is the scalar tilt.

Capitals `E, N, H` keep their logistic laws. **Change the network ceiling** to add the habit term:

```
N̄ = N_0 + λ_E E + λ_W W + λ_κ κ
```

Optionally add a weak habit term to the expertise ceiling (`Ē = E_0 + ... + λ_Eκ κ`); keep `λ_Eκ` small.

Health depreciation still rises with overwork `τ_Y`.

**Add the habit dynamics:**

```
dκ = α ( C − κ ) dt
```

Regime (optional): `m` a continuous-time Markov chain with generator `Q`, `Pr[m_{t+dt}=n | m_t=m] = Q_{mn} dt`.

### Objective

```
max E [ ∫_0^T e^{−ρt} ( U(C − κ) + ψ · v(τ_L, H) ) dt + e^{−ρT} B(x_T) ] ,  U(z) = z^(1−γ)/(1−γ)
```

Habit-adjusted consumption `U(C − κ)` **and** the leisure term `ψ·v(τ_L, H)` both appear. They are distinct channels: leisure acts through time to health, habit acts through consumption reference and through the capital ceilings. Do not collapse them into one term.

### Goals and the tail constraint

Goals stay as triples `(deadline, region, confidence)`. Per-goal chance constraint with a CVaR surrogate, one per active goal:

```
P( x_{T_k} ∈ G_k ) ≥ 1 − ε_k   ⟹   CVaR_{ε_k}( shortfall_k ) ≤ 0   (Rockafellar-Uryasev)
```

Financial independence is the counterfactual with labour income set to zero. The fundable base is drawable wealth only:

```
Fundable = W_L + h_R · W_R − D ,  with h_home = 0 for a self-occupied residence
```

**Human capital is excluded from the fundable base.** If any file currently adds a human-capital term (for example `κ_H · H`) to the independence or funding-ratio numerator, remove it. This is the one substantive correction to make wherever the funding ratio is defined.

### Solver and output

HJB stated once (with the regime-jump term when the layer is on), then solved by model-predictive control: Euler-Maruyama discretisation, sample-average approximation over scenarios, first-period non-anticipativity, receding horizon. The headline deliverable is the **costates / shadow prices**: the marginal value of each capital, and the exchange rate between an hour of networking and an hour of earning. Keep this as the interpretive centrepiece.

### Merton as validation, not framing

With a single liquid capital, no goals, no habit, and constant returns, the model must collapse to `w* = (μ − r)/(γσ²)` with consumption a fixed fraction of wealth. Treat this as a unit test, not as the organising narrative.

---

## 1. Global notation and naming pass (all editable files)

Apply with judgement, not blind find-replace:

1. **Growth to Gain.** Rename the first portfolio role from "Growth" (and any localisation such as "Wachstum" or "Crecimiento" if it is author-facing rather than a fixed data label) to "Gain" so the four roles read Gain, Income, Stabilization, Protection everywhere. In fixed data tables that are quoted verbatim from a published PDF, leave the quote but add a note that the house term is now Gain.
2. **`θ` is the risk tilt only.** Confirm no file uses `θ` for the habit.
3. **`H` is health, `E` is expertise.** Confirm no file uses `H` for human capital. If one does, split it as the book does.
4. **Habit symbol is `κ`.** If `κ` is also used as a haircut, rename the haircut to `h`.

Produce a short report of every rename you made, grouped by file.

---

## 2. The book: `The_Life_Balance_Sheet_Book_source.html`

The book already matches most of the canonical model (four capitals, wealth split three ways, two budgets, per-goal chance constraints, shadow prices, health feedback). Make only these deltas:

- **Chapter 3 (state):** add the habit `κ` as a state variable, defined as a standard-of-living stock that adjusts toward recent consumption. Keep the four-capital framing; `κ` is a scalar carried alongside.
- **Chapter 4 (controls):** where the portfolio control is introduced, keep `θ` as the default scalar tilt and note that under the regime layer it generalises to the four-role weight vector `w = (w_G, w_I, w_S, w_P)`. Confirm the roles are named Gain, Income, Stabilization, Protection.
- **Chapter 5 (dynamics):** add `dκ = α(C − κ) dt`. Add the habit term `λ_κ κ` to the network ceiling `N̄`. Make the return parameters regime-dependent `μ_m, Σ_m` behind the optional regime switch.
- **Chapter 6 (coupling):** state the new wire explicitly, that a maintained standard of living lifts the network ceiling, alongside the existing expertise and wealth terms.
- **Chapter 7 and Chapter 16 (independence):** confirm the fundable base excludes human capital and the self-occupied residence. Correct it if it does not.
- **Chapter 9 (objective):** confirm both the habit-adjusted consumption `U(C − κ)` and the leisure term appear, described as distinct channels.
- **Chapter 20 (extensions):** the regime-switching item is now promoted to an optional core layer, not a future extension. Move it out of "extensions" into the model proper (Chapter 5 or a short new section), and leave a one-line pointer in Chapter 20 noting it is now available as a switch.
- **Chapter 11 / Appendix B (calibration, parameters):** add the new parameters `α` (habit adjustment speed) and `λ_κ` (habit-to-network coupling). Flag `λ_κ` as the least identifiable parameter, to be held small and stress-tested in sensitivity analysis rather than estimated precisely.

Preserve the book's voice, its figures, and its "illustrative" labelling. Do not regenerate the equation image assets unless the change touches that specific equation; if it does, note which `assets/eq_*.png` need regenerating and list them rather than silently breaking references.

---


## 4. Training and PCP documentation

- `Schulung_Life_Balance_Sheet.html`, `Training_Life_Balance_Sheet.html`: add the habit `κ` to the state description ("vier Kapitalien" stays, `κ` is an additional stock), add the habit-to-network wire to the coupling section, add the optional regime toggle, and rename Growth to Gain. Keep the German register in the Schulung file and the existing register in the Training file.



---

## 6. Acceptance checks

Before you finish, verify:

1. No file uses `H` for human capital, `θ` for the habit, or "Growth" for the first role.
2. The habit `κ` appears as a state, has dynamics `dκ = α(C − κ)`, enters utility as `U(C − κ)`, and lifts the network ceiling via `λ_κ κ`.
3. The four roles are Gain, Income, Stabilization, Protection in every editable file that lists them.
4. Every funding-ratio or independence definition excludes human capital and the self-occupied residence.
5. The regime layer is presented as optional (default off) and, when on, drives role-based returns.
6. The Merton limit is described as a validation, not the framing.
7. No em-dashes were introduced. No fabricated data. Third-party and Abdellah-authored files untouched.

Deliver a change report: per file, the edits made, the renames applied, any `assets/eq_*.png` that need regenerating, and any place you were unsure and left alone for review.

---

## 7. Reference

The canonical statement of the model is the Notion working note "A Life as an Optimal-Control Problem: Capitals, Budgets, and a Tail Constraint" (in the SIM Research Working Notes database). Its embedded HTML paper is the polished version. If any ambiguity arises, that note governs.
