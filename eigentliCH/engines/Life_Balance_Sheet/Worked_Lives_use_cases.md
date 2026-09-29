# Worked Lives: One Framework, Many Plans

*The framework is a generic stochastic optimal-control problem, not a personal model. Its content is what happens when it is instantiated with a specific capital mix, goal set, risk aversion, and constraints. Here are five lives, each an instance of the same machinery. The named flagship, Nicolas, is treated separately (see the Nicolas special-case note); he is the calibration anchor, not a generic setting.*

Everything that distinguishes one life from another enters as a parameter of the same control problem: the initial capitals (including the starting habit `κ₀`), the dated goals with confidences `ε_k`, the risk aversion `γ`, and the constraints on labour, liquidity, and permitted assets. A case is a choice of the tuple `(K₀, {(G_k, T_k, ε_k)}, c*, γ, {constraints})`; the solver returns a state-contingent policy for consumption, the time budget, capital investment, the role weights, and the discrete jumps. The five lives differ only in this tuple.

Numbers are illustrative. Each case is calibrated so that the correct binding constraint bites at a sensible target confidence; the exact percentage is a well-reasoned estimate under the model, not a promise. All five are solved by the two-phase solver, which restores feasibility first and then maximises the life subject to the achievable funding bound, so the reported probabilities are stable across scenario counts.

---

## Results at a glance

<!-- RESULTS_TABLE -->

*Engine settings: two-phase multistart solve, out-of-sample Monte-Carlo scoring. "Binds" is the tightest sub-condition at the deadline; "insight" is the costate exchange rate between an hour of networking and an hour of earning.*

---

## Case one: the young professional

*28, technologist, high and market-correlated human capital.*

| Liquid | Real | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 40k | 0 | 0 | 0.45 | 0.30 | 0.92 | 0.75 |

A person early in a high-earning, market-correlated career holds most of their wealth as human capital, `HC ≫ W`, carrying a high effective beta `β_HC` to the Gain role. The human-capital-adjusted Merton rule scales the Gain weight to total wealth and then offsets it by the market exposure the career already carries:

$$w_G^{*} = \frac{\mu - r}{\gamma\sigma^2}\cdot\frac{W + \text{HC}}{W} - \beta_{\text{HC}}\frac{\text{HC}}{W}$$

With `HC` several times `W` and `β_HC` high, the second term dominates and `w_G*` is driven low or negative. The young professional is already long the Gain role through their career and should hold a defensive financial book tilted to Income and Protection, while pouring time and money into expertise and network, whose S-curves are still steep and whose marginal return exceeds that of financial assets. **The plan for the young is to build the human capitals and hedge them, not to chase the Gain role in the portfolio.**

---

## Case two: independence by fifty

*40, mid-career, work by choice rather than need.*

| Liquid | Real (residence) | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 1.6m | CHF 1.1m | CHF 300k | 0.80 | 0.72 | 0.80 | 0.45 |

Independence at fifty on a lifestyle of `c* = CHF 120k` per year in real terms, net of mortgage, with the residence walled off, and a conservative sustainable real withdrawal of `y = 3%`. The independence condition fixes the required drawable wealth:

$$\text{Fundable}^{*} = \frac{c^{*}}{y} = \frac{120{,}000}{0.03} = 4{,}000{,}000$$

Four million in real terms of drawable wealth, with the residence excluded (`h_home = 0`) and human capital excluded because independence is precisely the state of not needing it. The solver steers liquid and income-producing wealth to the target by the date, subject to the tail constraint. Because work continues by choice, labour supply does not collapse at the independence date; independence changes its meaning, from a source that must be harvested into one free to be withdrawn. **The binding quantity is drawable wealth, not net worth.**

---

## Case three: the near-retiree

*60, approaching decumulation, horizon short and the tail binding.*

| Liquid | Real | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 1.6m | CHF 1.4m | CHF 0.1m | 0.82 | 0.75 | 0.68 | 0.55 |

Approaching decumulation, the horizon shortens and the tolerance for a bad path falls, so the tail constraint binds. The near-retiree faces sequence-of-returns risk: early drawdown-phase losses permanently impair the funding ratio. The policy responds by gliding the portfolio toward the value-preserving roles, Protection and Income, and away from Gain. As the terminal date nears and the shortfall tail tightens, the per-goal constraint `CVaR_ε(shortfall) ≤ 0` becomes active and pulls the Gain weight down until the worst-tail funding shortfall is back within tolerance. Model-predictive control re-solves each period, so the glide is a response to the realised funding ratio, not a fixed schedule: a good early sequence relaxes the constraint and permits more Gain, a bad one forces further de-risking. **A modest encore income closes any gap better than one more full year of work.**

---

## Case four: the entrepreneur

*46, founder, balance sheet dominated by one concentrated, illiquid venture.*

| Liquid | Real (venture + stakes) | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 300k | CHF 2.5m | CHF 0.6m | 0.85 | 0.70 | 0.72 | 0.40 |

The business is simultaneously real capital, intellectual capital, and the whole of the founder's human capital, all loaded on one idiosyncratic risk. The framework handles this through the liquidity and capital-type constraints, which cap the fundable illiquid share and force the liquid financial sleeve to diversify away from the business's risk rather than toward it. The optimal policy is counterintuitive to many founders: because the business already supplies extreme concentration and behaves like a leveraged Gain-role holding, the liquid capital should be maximally diversified and uncorrelated with the venture, tilted to Stabilization and Protection. **The plan diversifies an undiversifiable balance sheet by making everything the founder controls outside the business the opposite of the business.**

---

## Case five: the tail shock

*A scenario, not a person: job loss, disability, a health event.*

The last case is not a different person but a different scenario for any of them: the realised tail. The tail constraint exists precisely to pre-position for it. Requiring `CVaR_ε(shortfall) ≤ 0` forces the plan, before any shock, to hold a buffer `B` in the Protection role and a hedge `q` large enough that the funding shortfall in the worst `ε` tail stays within tolerance. Sizing follows directly: the buffer plus hedge payout must cover the drop in fundable capital plus the rise in liabilities across the tail scenarios, at the `ε` quantile:

$$B + \text{hedge payout} \ge (\Delta L - \Delta\text{fundable})_{\text{tail}}$$

For the illustrative profile used in the engine (age 44, a job-loss shock that switches labour income off for a year while spending and debt service continue), the net cash gap the buffer must plug is about **CHF 71k**, and the plan pre-positions a **CHF 120k** protection buffer, which covers it. The well-posed plan carries liquidity and insurance that look excessive in the central case and prove exactly sufficient in the bad one.

---

## What varies and what does not

Across the five, the four-capital state, the two budgets and the role-based portfolio (Gain, Income, Stabilization, Protection), the habit-adjusted objective, the per-goal tail constraints, and the model-predictive solver never change; only the parameter tuple does. That the same machinery produces a defensive book for one, a four-million drawable target for another, a preservation glide for a third, forced diversification for a fourth, and a pre-positioned protection buffer for the fifth is the demonstration that the framework is generic and the cases are instantiations, not a personal recipe dressed as a method.

*Illustrative throughout. Not financial advice. Companion to the Nicolas special-case note and "The Life Balance Sheet" book.*
