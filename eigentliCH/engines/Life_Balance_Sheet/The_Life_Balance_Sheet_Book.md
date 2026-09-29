# The Life Balance Sheet

**Asset–liability management for a human life**

*Nicolas Bürkler · First edition, 2026 · Illustrative throughout, not financial advice*

> Savings, skill, network, health and time as assets; the milestones we plan for as liabilities; and a standard of living that compounds. How a person reaches their goals over time, and whether those goals are actually feasible.

---

## Preface — why a balance sheet for a life

This book takes an idea from institutional finance, asset–liability management, and asks what happens if we apply it honestly to a single human life.

A pension fund does not measure success by how much cash it holds. It asks whether its *assets* will meet its *liabilities* as they fall due, under uncertainty, with an acceptable margin of safety. That question, not "how much do we have?" but "will what we have meet what we owe, on time, probably?", turns out to be exactly the right one to ask of a person deciding how to spend the next decade.

The trouble with money-only planning is not that money is unimportant; it is that money is downstream. What actually produces the money, and the life, is a set of slower-moving capitals: what you know, who you know, and the health and hours you have to deploy them. Those capitals grow in a characteristic way, they feed one another, and they decay if neglected. A model that keeps them on the balance sheet can say things a cash-flow spreadsheet cannot, most usefully, what an hour of your time is actually worth, and toward which goal.

The book has four parts. **Part I** motivates the reframe and the dynamical-systems view. **Part II** builds the model in full: the state, the controls, the stochastic dynamics, the goals, the notion of feasibility, and the optimisation that turns all of it into a recommendation. **Part III** works five lives in detail, each an *instance* of the one framework rather than a model of its own. **Part IV** is candid about what the model cannot do. Everything numerical here is illustrative.

A note on this edition. The model now carries a standard-of-living **habit** as a state variable, names the first portfolio role **Gain**, and treats the macro **regime** as a layer the adviser can switch on to couple a personal plan to the wider capital cycle.

---

# Part I · The idea

## Chapter 1 — The reframe

Three moves turn a life into something an asset–liability manager would recognise.

**Move one: capitals are assets.** We treat everything that carries value across time as an asset. Financial wealth is the obvious one, but it is joined by **expertise** (what you can do), **network** (who will act on your behalf), and **health** (the energy that makes the other three usable). Each can be invested in, each yields a return, and each depreciates if left alone.

**Move two: goals are liabilities.** A milestone (a home, a company, financial independence, retirement) is a *claim*: an amount, due at a date, that the assets must be able to meet.

> **Definition 1.1 — Liability.** A goal is a triple *(deadline, region, confidence)*: a time by which it must be met, a set of states that count as meeting it, and the probability of success the planner requires. A goal with no required confidence is a wish, not a liability.

**Move three: the saving rate is an output, and time is the constraint.** The saving rate is what remains after consumption and self-investment, an *output* of the plan, not an input. And the truly scarce resource is not money but **time**: money can be borrowed and compounded; the twenty-four-hour day cannot.

> **Assumption 1.2 — Time is binding.** The allocation of time is constrained to a fixed budget each period and cannot be stored or transferred across periods.

## Chapter 2 — A person as a dynamical system

If capitals are assets and goals are liabilities, then a life is a *controlled dynamical system*: a state that evolves over time, steered by decisions, disturbed by chance, aiming to reach target regions. The characteristic motion of each capital is the **S-curve**: slow while small, accelerating once large enough to reinforce itself, and flattening toward a ceiling. Because the capitals are distinct dimensions, a goal can require several of them *at once*, and the *trajectory* through the state space, not just the effort expended, decides feasibility.

*Figure 2.1 (illustrative): two lives, same start, same goal region (high expertise and high network). The earning-heavy path stalls short on network; the network-heavy path curves into the region.*

---

# Part II · The model

## Chapter 3 — The state: four capitals and a habit

The state is what we must carry forward in time. Four capitals suffice, with wealth split three ways, and alongside them a standard-of-living habit.

$$x = (\,W_L,\ W_R,\ D,\ E,\ N,\ H,\ \kappa \mid m\,)$$

Here $W_L$ is **liquid financial wealth**, $W_R$ is **real or illiquid assets**, and $D$ is **debt**. Net worth is derived:

$$W = W_L + W_R - D$$

The next three capitals are dimensionless indices in $[0,1]$: **expertise** $E$, **network** $N$, and **health** $H$, the last an efficiency multiplier on everything the person does. Carried alongside is a standard-of-living **habit** $\kappa$, a stock that tracks recent consumption. It is on by default, because it is not a bare reference point but a stock with consequences: a maintained lifestyle keeps a person in the rooms and memberships that raise the network (and, weakly, the expertise) ceiling. The macro **regime** $m$ is optional: off, returns are constant; on, it couples the personal problem to the capital cycle (Chapter 11).

> **Definition 3.1 — Capital.** A stock that (i) carries value across periods, (ii) can be increased by time or money, (iii) yields a flow return, and (iv) depreciates without maintenance. Wealth uniquely does not depreciate. The habit $\kappa$ is not a capital: it is a reference stock that shapes utility and lifts ceilings, not an asset one draws on.

## Chapter 4 — The controls: two budgets and a portfolio

You move the capitals by allocating time and money each period, and by choosing a portfolio.

$$u = (\,\tau,\ C,\ m_E,\ m_N,\ p_A,\ w \mid \text{jumps}\,)$$

The time shares $\tau = (\tau_Y, \tau_E, \tau_N, \tau_H)$ divide the day between earning, learning, networking and recovery. The money flows are consumption $C$, education and network spend $m_E, m_N$, and amortisation $p_A$.

**The portfolio and its four roles.** The portfolio is expressed as weights on four *roles*, the same taxonomy the institutional Optimizer uses:

- **Gain** — growth assets that compound the estate (broad equity and equity-like risk).
- **Income** — cash-flow assets (yielding credit, dividend and rental streams).
- **Stabilization** — diversifiers that cushion drawdowns (high-grade duration and the like).
- **Protection** — convex tail hedges and cash that pay off in the bad states.

Written as a vector, $w = (w_G, w_I, w_S, w_P)$ over Gain, Income, Stabilization and Protection, cash the residual. When the regime layer is off, this collapses to a single scalar **risk tilt** $\theta$; $\theta$ denotes the risk tilt and nothing else.

**Admissibility.** The time budget is the hard constraint:

$$\tau_i \ge 0,\quad \sum_i \tau_i \le 1,\quad \tau_L = 1 - \sum_i \tau_i,\quad \theta \in [0,1]$$

$$C + \text{debt service} \le Y + \text{yields} + \text{accessible } W_L,\quad W_L \ge W_{\text{buf}}$$

Two controls are discrete and fire at events: taking on leverage to acquire property, and founding a company.

> **Assumption 4.1 — Separable effort.** Time and money contribute additively to each capital's growth, up to the saturation term.

## Chapter 5 — Dynamics

**Income** is the hinge between the capitals and wealth, Cobb–Douglas in expertise and network, scaled by earning time and health:

$$Y = A_Y\,\tau_Y\,\varphi(H)\,E^a N^b,\qquad a,b < 1$$
$$\varphi(H) = H^c$$

**Wealth accumulates.** Net cash into liquid wealth is

$$F = Y + \text{yields} - C - m_E - m_N - p_A - \text{debt service}$$

and liquid wealth follows a controlled process carrying the role weights and phase-dependent role returns:

$$dW_L = \Big[F + W_L\big(r_f + w^{\top}(\mu_m - r_f\mathbf{1})\big)\Big]dt + W_L\,w^{\top}\Sigma_m^{1/2}\,dB$$

With the regime layer off, $\mu_m,\Sigma_m$ are constant and the vector collapses to the scalar tilt, $\mu_P = r_f + \theta(\mu_M - r_f)$, $\sigma_P = \theta\sigma_M$. Real assets and debt evolve as

$$dW_R = (\mu_R + y_R)W_R\,dt + \sigma_R W_R\,dB_R,\qquad dD = -p_A\,dt + \Delta D^{\text{jump}}$$

**Expertise, network and health saturate** on logistic laws:

$$\dot E = \big[g_E(\tau_E,m_E)(1 - E/\bar E) - \delta_E\big]E$$
$$\dot N = \big[g_N(\tau_N,m_N)(1 - N/\bar N) - \delta_N\big]N$$
$$\dot H = \big[g_H(\tau_H)(1 - H) - \delta_H(\tau_Y)\big]H$$

Health carries the key feedback: its decay rises with overwork,

$$\delta_H(\tau_Y) = \delta_{H0} + \eta\cdot\max(0,\ \tau_Y - \tau_Y^{*})$$

**The habit** adjusts toward recent consumption at speed $\alpha$:

$$d\kappa = \alpha(C - \kappa)\,dt$$

Under the regime layer, $m$ is a continuous-time Markov chain with generator $Q$: $\Pr[m_{t+dt}=n \mid m_t=m] = Q_{mn}\,dt$.

## Chapter 6 — Coupling

The single most consequential wire lets expertise, wealth *and a maintained standard of living* raise the *ceiling* on network:

$$\bar N = N_0 + \lambda_E E + \lambda_W W + \lambda_\kappa \kappa$$

The habit term $\lambda_\kappa\kappa$ is the new wire, and it is why a cut in spending is not free even when the goal is purely financial: it lowers the ceiling on the network that lifts income. The coefficient $\lambda_\kappa$ is the least identifiable in the model and is held small and stress-tested rather than estimated precisely.

The **reinforcing loop** runs expertise → income → wealth → network ceiling → income, and the habit reinforces it. The **balancing loop** runs earning → overwork → lower health → lower income.

## Chapter 7 — Goals as liabilities

**Lump claim: a home.** A purchase at price $P$ demands a deposit and the income to service the loan at a stressed rate:

$$W_L \ge \xi P \quad\text{and}\quad a\,Y \ge i_{\text{calc}}(1-\xi)P + \mu_{\text{maint}}P$$

**Joint region: a company.** Founding requires a buffer *and* a network *and* the expertise, simultaneously:

$$W_L \ge B_{\text{buf}} \ \wedge\ N \ge N_{\min} \ \wedge\ E \ge E_{\min}$$

**Liability stream: retirement.** Funded when the funding ratio clears one:

$$\Phi(t) = \frac{W_L + h_R W_R - D + h_H\,\text{HC}}{L(t)} \ge 1$$

**Counterfactual: financial independence.** Switch off labour income and ask whether passive cash flow plus a safe drawdown covers spending. Only *drawable* wealth counts; the residence enters at haircut $h_{\text{home}} = 0$:

$$\Omega^{\text{draw}} = W_L + h_R W_R - D,\qquad h_{\text{home}} = 0$$
$$y\,(W_L + h_R W_R - D) + y_R W_R \ge c^{*}$$

Rearranging gives the drawable wealth required, net of the residence's operating yield:

$$\text{Fundable}^{*} = \frac{c^{*}}{y}$$

**Human capital and the self-occupied residence are excluded from the fundable base**, since independence is precisely the state of not needing to work and a home one lives in funds no consumption.

> **Definition 7.1 — Independence ≠ net worth.** A goal on net worth can be satisfied while the independence goal on drawable wealth is not. When wealth is concentrated in an illiquid residence, the two diverge sharply.

## Chapter 8 — Feasibility and uncertainty

For each goal $k$ we require

$$\Pr(x_{T_k} \in G_k) \ge 1 - \varepsilon_k$$

estimated by Monte Carlo, $\hat p = \frac1M\sum_{j=1}^{M}\mathbf 1\{x^{(j)}\in G\}$. Because a probability is awkward for an optimiser, we impose the convex Rockafellar–Uryasev surrogate on the shortfall's Conditional Value-at-Risk:

$$\text{CVaR}_{\varepsilon}(L) = \min_{\zeta}\Big\{\zeta + \tfrac1\varepsilon\,\mathbb E[(L-\zeta)^{+}]\Big\},\qquad \text{CVaR}_{\varepsilon_k}(\text{shortfall}_k) \le 0$$

one constraint per active goal.

> **Assumption 8.1 — Estimable dynamics.** Monte-Carlo frequencies approximate true probabilities. The numbers are well-reasoned estimates conditional on the model, not guarantees.

## Chapter 9 — The objective

Consumption enters through CRRA utility of consumption measured *against the habit*:

$$U(z) = \frac{z^{1-\gamma}}{1-\gamma},\qquad z = C - \kappa$$

The planner maximises expected discounted utility of habit-adjusted consumption and of leisure, plus a bequest:

$$\max_{u(\cdot)}\ \mathbb E\left[\int_0^T e^{-\rho t}\big(U(C-\kappa) + \psi\,v(\tau_L,H)\big)\,dt + e^{-\rho T}B(x_T)\right]$$

The two terms are *distinct channels*: habit-adjusted consumption runs through the reference stock and the ceilings; the leisure term $\psi\,v(\tau_L,H)$ runs through time to health. Read plainly: *live as well as you can now, while keeping each goal funded to the confidence you require.*

## Chapter 10 — Solving it

The optimal value function satisfies a Hamilton–Jacobi–Bellman equation, with a regime-jump term when the layer is on:

$$\rho V = \max_{u\in U}\Big\{U(C-\kappa) + \psi v + V_t + \nabla V^{\top} f + \tfrac12\text{tr}(\sigma\sigma^{\top}\nabla^2_{xx}V) + \sum_n Q_{mn}\big(V(x,n)-V(x,m)\big)\Big\}$$

We state it once and decline to grid it. It is solved instead by **model-predictive control**: Euler–Maruyama discretisation, $x_{k+1} = x_k + f(x_k,u_k)\Delta t + \sigma\sqrt{\Delta t}\,\zeta_k$; sample-average approximation over $M$ scenarios; first-period non-anticipativity; apply only the first action and re-solve next period.

**Shadow prices.** The multipliers on the state-transition constraints are the **costates**, $\lambda = \partial J^{*}/\partial x_0$, the marginal value of each capital. Their ratios are the exchange rates the model is really for, for instance an hour of networking against an hour of earning:

$$\text{ER} = \frac{\lambda_N\cdot\partial\dot N/\partial\tau_N}{\lambda_{W_L}\cdot\partial Y/\partial\tau_Y}$$

Whichever side is larger is where the next hour should go, for that goal, at that state.

## Chapter 11 — The regime layer and calibration

**The regime layer.** Switched on, the role returns $\mu_m,\Sigma_m$ become phase-dependent, so the portfolio rotates across the four roles as the cycle turns: protection and stabilization into contraction and crisis, gain and income into expansion and boom, exactly as the institutional allocation does. Switched off, the model is the lean default with constant returns and the scalar tilt $\theta$. The layer is not a future extension but an option the adviser turns on when the cycle view is part of the mandate.

> **Validation 11.1 — the Merton limit.** With a single liquid capital, no goals, no habit and constant returns, the problem must collapse to Merton's rule, $w^{*} = (\mu - r)/(\gamma\sigma^2)$ with consumption a fixed fraction of wealth. Reproducing this is a unit test, not the framing.

**Calibration.** Parameters fall into three groups: *market* (role returns, vols, rates), *structural* (growth/saturation/depreciation rates, income exponents, the habit speed $\alpha$), and *personal* (initial state, risk aversion, leisure weight, goal thresholds). Only the last must be set per person. The honest test of a structural calibration is a backtest against a life that was actually lived; a companion case study does this over a twenty-six-year record.

> **Assumption 11.2 — Identifiability.** Not every parameter is separately identifiable from a single life. Where data cannot pin a parameter down (the habit-to-network coupling $\lambda_\kappa$ is the clearest case), it is fixed small from population priors and stress-tested by sensitivity analysis.

---

# Part III · Worked lives

*One framework, filled with different capitals, goals and constraints, produces different optimal lives. Five instances of the same machinery. A case is a choice of the tuple*

$$\big(K_0,\ \{(G_k,T_k,\varepsilon_k)\},\ c^{*},\ \gamma,\ \{\text{constraints}\}\big)$$

*Numbers are illustrative. A sixth life, a real twenty-six-year trajectory used to calibrate the dynamics, is treated separately as a companion case study.*

## Chapter 13 — The young professional: hedge and build

*28 · technologist · high, market-correlated human capital.*

| Liquid | Real | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 40k | 0 | 0 | 0.45 | 0.30 | 0.92 | 0.75 |

*(starting habit $\kappa_0 \approx$ CHF 46k)*

**Goal.** Build toward long-run independence while hedging a career that is itself a leveraged bet on the Gain role. The case is about the *policy*, in particular the Gain weight the financial book should carry.

**The human-capital-adjusted Merton rule.** With human capital $\text{HC}$ several times financial wealth $W$ and a high effective beta $\beta_{\text{HC}}$ to the Gain role,

$$w_G^{*} = \frac{\mu - r}{\gamma\sigma^2}\cdot\frac{W + \text{HC}}{W} - \beta_{\text{HC}}\frac{\text{HC}}{W}$$

With $\text{HC}$ large and $\beta_{\text{HC}}$ high, the second term dominates and $w_G^{*}$ is driven low or negative: the young professional should tilt to Income and Protection, not chase Gain. The policy also directs heavy investment of time into the still-steep expertise and network S-curves.

> **Lever.** Hold the financial book defensive (Income and Protection, cash the residual) and pour the marginal hour into expertise and network. Build the human capitals and hedge them, do not double a career bet in the portfolio.

## Chapter 14 — Independence by fifty: a drawable target

*40 · mid-career · work by choice, not need.*

| Liquid | Real (residence) | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 800k | CHF 1.2m | CHF 400k | 0.75 | 0.65 | 0.80 | 0.45 |

*(starting habit $\kappa_0 \approx$ CHF 110k)*

**Goal.** Independence at fifty on $c^{*} = $ CHF 120k/yr real, net of mortgage service, at confidence 0.85, residence walled off ($h_{\text{home}}=0$). At a conservative $y = 3\%$, the independence condition fixes the drawable-wealth target:

$$\text{Fundable}^{*} = \frac{c^{*}}{y} = \frac{120{,}000}{0.03} = 4{,}000{,}000$$

**Binding constraint.** Drawable wealth, not net worth: the residence is walled off, so only the liquid and income-producing sleeve counts. Work continuing by choice changes independence from a source that must be harvested into one free to be withdrawn.

> **Lever.** Direct earned income preferentially into the drawable sleeve rather than the residence, and hold permanent lifestyle inflation down, since every franc added to $c^{*}$ raises the four-million bar in proportion.

## Chapter 15 — The near-retiree: a preservation glide

*60 · approaching decumulation · horizon short, tail binding.*

| Liquid | Real | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 1.6m | CHF 1.4m | CHF 0.1m | 0.82 | 0.75 | 0.68 | 0.55 |

*(starting habit $\kappa_0 \approx$ CHF 95k)*

**Goal.** Fund a retirement stream from age 65 to about 90 (the funding-ratio condition) at confidence 0.90, against sequence-of-returns risk.

**Binding constraint.** As the terminal date nears and the shortfall tail tightens, the CVaR constraint becomes active and pulls the Gain weight down until the worst-tail shortfall is within tolerance, gliding the book toward Protection and Income. Because MPC re-solves each period, a good early sequence relaxes the constraint and a bad one tightens it.

> **Lever.** A modest encore income for a few years lowers the required nest egg more than one more full year of work, and protects the health and network a hard stop tends to erode.

## Chapter 16 — The entrepreneur: diversifying the undiversifiable

*46 · founder · balance sheet dominated by one venture.*

| Liquid | Real (venture + stakes) | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 300k | CHF 2.5m | CHF 0.6m | 0.85 | 0.70 | 0.72 | 0.40 |

*(starting habit $\kappa_0 \approx$ CHF 130k)*

**Goal.** Sustain a lifestyle and edge toward independence while most of the estate is locked in the venture, at confidence 0.80. Liquidity and capital-type constraints cap the fundable illiquid share and force the liquid sleeve to diversify away from the venture.

**Binding constraint.** Because the business already supplies extreme concentration and behaves like a leveraged Gain-role holding, the liquid capital should be maximally diversified and uncorrelated with the venture, tilted to Stabilization and Protection. The binding constraint is drawable liquidity against a concentrated, illiquid book.

> **Lever.** Build and hold a diversified liquid sleeve uncorrelated with the venture rather than reinvesting every spare franc back into it; the marginal franc is worth far more outside than inside.

## Chapter 17 — The tail shock: a pre-positioned buffer

*A scenario, not a person: job loss, disability, a health event.*

**Goal.** Hold, before any shock, a buffer $B$ in the Protection role and a hedge $q$ large enough that the funding shortfall in the worst $\varepsilon$ tail stays within tolerance.

**Sizing.** The buffer plus hedge payout must cover the drop in fundable capital plus the rise in liabilities across the tail scenarios, at the $\varepsilon$ quantile:

$$B + \text{hedge payout} \ge (\Delta L - \Delta\text{fundable})_{\text{tail}}$$

**Binding constraint.** The tail itself: the worst $\varepsilon$ of scenarios sets the buffer, and the central case merely carries it. This is the purpose of solving with a tail constraint rather than to an expectation.

> **Lever.** Size the Protection buffer and any hedge to the tail, not to the average; the provision that looks like drag in the central case is what keeps the plan solvent when the shock lands.

## Chapter 18 — What the five have in common

Across the five, the four-capital state, the two budgets and the role-based portfolio, the habit-adjusted objective, the per-goal tail constraints, and the MPC solver never change. Only the parameter tuple does.

1. **The binding constraint is usually not money.** A career's market beta; drawable liquidity against a walled-off residence; sequence risk; concentration; the worst-$\varepsilon$ scenario itself.
2. **Time and health are the quiet limiters.** They cap what every other capital produces, and the overwork loop means they can be spent without noticing.
3. **The tail is where a plan earns its keep.** The framework beats the cookie-cutter by solving each life's actual problem and re-solving as the state evolves, closing the loop with the institutional Optimizer.

---

# Part IV · Limits and extensions

## Chapter 19 — Honest limits

The model reduces a person to a handful of capitals and a habit; the things hardest to quantify often matter most. The parameters are illustrative unless calibrated, and probabilities are conditional on the model. A reported "85% chance" is a well-reasoned estimate, not a law of nature; the right use is comparative. The habit-to-network coupling $\lambda_\kappa$ is the least identifiable parameter and is held small. Nothing here is personalised financial, tax, or legal advice.

## Chapter 20 — Extensions

1. **Expertise as a vector** — promote $E$ to domain-specific capitals for serial reinvention.
2. **Households and dependants** — couple two state vectors through shared wealth and correlated time.
3. **Taxes and institutions** — the reference implementation already carries a Swiss-style progressive income tax and a wealth tax.
4. **The regime layer, already switched on** — now part of the model proper; what remains is richer regime estimation and fuller two-way coupling with the institutional cycle.
5. **Behaviour and adherence** — model the probability that a recommended action is actually taken.

---

## Appendix B — Default parameters

Illustrative defaults; to be calibrated in a real deployment.

| Symbol | Meaning | Default | Unit |
|---|---|---|---|
| w0 | income scale at E=N=H=1, full earning time | 200,000 | CHF/yr |
| a, b | income exponents on expertise, network | 0.5, 0.4 | — |
| αE, βE, δE | expertise: time-gain, self-compounding, decay | 0.30, 0.15, 0.03 | 1/yr |
| αN, βN, δN | network: time-gain, self-compounding, decay | 0.25, 0.20, 0.08 | 1/yr |
| αH, δH0, η | health: recovery, baseline decay, overwork slope | 0.50, 0.02, 0.30 | 1/yr |
| τY* | overwork threshold (earning share) | 0.50 | share |
| λE, λW | network-ceiling lift from expertise, wealth | 0.5, 0.3 | — |
| α (habit) | habit adjustment speed toward consumption | 0.35 | 1/yr |
| λκ | habit-to-network-ceiling lift (least identifiable; held small) | 0.10 | — |
| rf, μM, σM | risk-free, Gain return, Gain volatility | 0.01, 0.06, 0.16 | 1/yr |
| μR, σR, yR | property appreciation, volatility, operating yield | 0.03, 0.08, 0.02 | 1/yr |
| i, i-calc | mortgage rate, stressed serviceability rate | 0.02, 0.05 | 1/yr |
| ξ | down-payment fraction | 0.20 | — |
| y (swr) | safe withdrawal / sustainable yield | 0.03–0.035 | 1/yr |
| h-R, h-home | drawable haircut on income-producing real assets, on residence | ≥0, 0.0 | — |
| ρ, γ | utility discount rate, risk aversion | 0.02, 2.0 | — |

## Notation

$W_L, W_R, D$ liquid/real/debt · $E, N, H$ expertise/network/health · $\kappa$ habit · $\alpha$ habit speed · $\tau$ time shares · $\theta$ risk tilt (layer off) · $w$ role weights (Gain, Income, Stabilization, Protection) · $m$ macro regime · $h_R, h_{\text{home}}$ drawable haircuts (residence = 0) · $\text{HC}, \beta_{\text{HC}}$ human capital and its beta to Gain · $\varepsilon_k$ failure tolerance · $\lambda$ costate · $\lambda_\kappa$ habit-to-network lift.

*Figures and case-study numbers are illustrative throughout. First edition, 2026.*
