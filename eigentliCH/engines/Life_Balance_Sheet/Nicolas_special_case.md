# Nicolas: the model fit to a single life

*A special-case note, companion to the Worked Lives. Nicolas is not one of the five worked lives; he is the calibration anchor, the one real trajectory the model is fit to and must retrodict before it is allowed to predict anyone else. This note says how the framework fits his case.*

---

## Why Nicolas is a special case, not a worked life

The five worked lives are archetypes: a young professional, an independence-seeker, a near-retiree, an entrepreneur, a tail shock. Each is deliberately generic, an instance of the framework at a different setting. Nicolas is the opposite: a specific, twenty-six-year record of an actual life, used to discipline the structural parameters. He earns his own note for two reasons.

1. **He is the backtest.** Calibration is only honest if the fitted dynamics can reproduce a life that was actually lived. Nicolas's trajectory from nineteen to forty-five is that test (Chapter 11 of the book). If the model cannot retrodict his path, it has no business predicting anyone's.
2. **His forward problem is the flagship.** Independence at fifty, on a defined lifestyle net of mortgage, with the residence walled off. It is the case that first showed net worth is the wrong number and drawable wealth is the right one.

---

## The backtest: nineteen to forty-five

From age nineteen, the hardest available programme (control-systems theory at ETH), funded by working to sixty per cent while building a trading system. In the model's language:

- Early **expertise** converts, through the trading system, into **liquid wealth** — enough at twenty-six to acquire property (a leverage jump: liquid wealth falls, real assets and debt rise).
- Founding a research firm at twenty-nine while keeping a part-time teaching role is a deliberate sacrifice of earning time to raise the **network ceiling** through the coupling `N̄ = N₀ + λ_E·E + λ_W·W + λ_κ·κ`. The payoff arrives years later as board seats and mandates that would have been unreachable earlier.
- At thirty-six, income supports a two-million-franc mortgage; the renovated property later carries a valuation above five million.

Run forward from nineteen with these actual choices, the model reproduces the observed capitals and wealth at the known dates. The fit is not decorative: it constrains the income exponents, the network-ceiling couplings, and the property dynamics. A calibration that could not retrodict the trading-funded purchase or the post-founding network acceleration would be rejected.

---

## The forward problem: independence by fifty

**Initial state, age 45 (illustrative).**

| Liquid | Real (property) | Debt | Expertise | Network | Health | Free time |
|---|---|---|---|---|---|---|
| CHF 0.6m | CHF 5.0m | CHF 1.8m | 0.90 | 0.90 | 0.70 | 0.35 |

**Goal.** Financial independence within five years, by age fifty: lifestyle spending of CHF 120k per year, *net of mortgage service*, sustainable without labour income. Two constraints are fixed by the person:

- **No equity release** from the residence, so the drawable haircut `h_home = 0`. The CHF 5m property contributes nothing to drawable wealth; only its operating yield helps.
- The CHF 120k is pure lifestyle, with debt service handled separately (the "net of mortgage service" convention). The fundable base is therefore drawable liquid wealth, not net worth, and not the residence.

He intends to keep working, as strategist, consultant, and in the MBA programme he built, by choice rather than necessity.

---

## What the model says

Running the case through the engine (two-phase solve, out-of-sample scoring) gives the flagship result:

- **Probability of independence by fifty ≈ 90%** on the recommended plan, at the 90%-confidence target.
- **The binding constraint is drawable wealth**, and behind it, time and health. Net worth (about CHF 3.8m net, rising) sits far above the requirement; drawable liquid wealth is what binds. This is the whole point of splitting wealth three ways.
- **The exchange rate favours overtime over networking by roughly 5×.** This is the inverse of a founder's instinct, and a direct read-off of the costate ratio: expertise and network are near their ceilings, so their marginal value is low, while the goal is drawable wealth, which earned income converts into directly. The engine also flags the winner as *dominant* when networking barely moves the goal at all.
- **Health carries the highest shadow price.** It is the scarcest capital and the quiet limiter behind the plan, because the income that funds independence depends on hours already committed near the overwork threshold.

**The standing recommendation.** Direct the strategist and teaching income preferentially into the liquid, drawable sleeve rather than the property, and let the residence's operating yield count toward spending. The true limiter is hours and energy, not capital; protecting both protects the income that funds independence. Plan against age roughly 52 to 53, not 50, and treat any earlier date as requiring a lever the person has ruled out (equity release).

---

## How the new model elements read for Nicolas

The current edition adds a habit, renames the first portfolio role, and promotes the regime layer. For Nicolas specifically:

- **Habit (`κ`).** His standard of living is high and long-established, so `κ` sits near his CHF 120k lifestyle. The habit term makes explicit why he cannot simply "spend less to get there faster" without cost: a cut in spending is felt as a loss and, through `λ_κ·κ`, would lower the very network ceiling that his advisory income leans on. In practice `λ_κ` is held small, so this is a second-order effect for him, but it is the right sign.
- **The Gain role.** His portfolio tilt is conservative-to-moderate; in role terms he is underweight Gain and carries Income and Stabilization, appropriate for someone whose human capital and concentrated property already load the estate with growth-like, illiquid risk. This rhymes with the entrepreneur worked life.
- **The regime layer.** Switched off, his plan is the lean default used above. Switched on, his portfolio would rotate toward Protection and Stabilization into a late-cycle contraction, exactly as the institutional Optimizer would tilt a fund, which is the bridge his wider work is built on.

---

## The lesson Nicolas anchors

Nicolas is the case that makes the framework's central claim concrete: **for a person with ample net worth locked in an illiquid residence, independence is a drawable-liquidity problem and a time-and-health problem, not a net-worth problem.** Every worked life inherits that lesson in a different form. He is kept out of the worked-lives gallery precisely because he is not a generic setting to be varied; he is the fixed point the whole calibration is pinned to.

*Illustrative throughout. Not financial advice.*
