# hh-0002 / derived-fi-5y: allocation brief

Model-derived, not a forecast. Optimised for the regime as at 2024-12-31 under the asymmetric squared-shortfall curve fit.

## What produced this

- Regime: `REG-53d939e6559e60d9` (timeline `RTL-53d939e6559e60d9`, ms@0.1.0)
- ReturnSet: `RS-5580cf25e9ecfdd8` (re@0.2.0, universe fm@0.2.0)
- Engine: pcp@0.1.0, speed fast
- Market scope: Global, reported in CHF
- Replay: `01bce49586460b0b` (trace `TR-01bce49586460b0b`)
- Regime blend: br 5%, ch 5%, cn 25%, de 15%, fr 10%, gb 10%, us 30%

## Whether it is feasible

The budget equality was met and the mandate's constraints are satisfied, so the weights below are a feasible allocation.

The crisis tail of the live regime carries 23.4% of the probability mass. The objective penalises only shortfall below the mandate curve, weighted by the regime, so this is the share of the fit driven by the crisis states.

## What binds

These constraints are active at the optimum, so they, not the fit, set the exposures they govern:

| dimension | category | side | bound | realised |
|---|---|---|---|---|
| currency | CHF | lower | 0.5000 | 0.5000 |
| currency | RMB | lower | 0.0000 | -0.0000 |
| currency | GBP | lower | 0.0000 | -0.0000 |
| currency | JPY | lower | 0.0000 | -0.0000 |
| currency | HKD | lower | 0.0000 | 0.0000 |
| currency | AUD | lower | 0.0000 | -0.0000 |
| currency | INR | lower | 0.0000 | -0.0000 |
| currency | Others | lower | 0.0000 | -0.0000 |
| region | East Asia | lower | 0.0000 | 0.0000 |
| region | South Asia | lower | 0.0000 | -0.0000 |
| region | South Pacific | lower | 0.0000 | -0.0000 |
| role | Protection | upper | 0.3500 | 0.3500 |
| capital_type | Others | lower | 0.0000 | -0.0000 |
| liquidity | Decade | upper | 0.1000 | 0.1000 |
| phase | Saturation | upper | 1.0000 | 1.0000 |
| phase | Foundation | lower | 0.0000 | -0.0000 |
| phase | Build-up | lower | 0.0000 | 0.0000 |
| phase | Optimisation | lower | 0.0000 | 0.0000 |
| asset_class | Alternative | upper | 0.2500 | 0.2500 |

## The allocation

| instrument | weight | role | region | currency | asset class |
|---|---|---|---|---|---|
| Real Estate direct | 25.00% | Stabilisation | Switzerland | CHF | Real Assets |
| CHF Corporate Loans IG | 15.00% | Income | Switzerland | CHF | Fixed Income |
| CS Long Vola | 12.50% | Protection | North America | USD | Alternative |
| Long Volatility Index | 12.50% | Protection | North America | USD | Alternative |
| Fixed Holding | 10.00% | Gain | Others | EUR | Equity |
| CHF Cash | 10.00% | Protection | Switzerland | CHF | Cash |
| EU Equities | 7.50% | Gain | Europe | EUR | Equity |
| Aktien Europe aktiv | 7.50% | Gain | Europe | EUR | Equity |

8 of 54 instruments in the investable universe carry weight. Positions below 0.005 percent are omitted from the table as rounding.

## By role

| role | weight |
|---|---|
| Gain | 25.00% |
| Income | 15.00% |
| Stabilisation | 25.00% |
| Protection | 35.00% |

Weighted-average ESG is 1.00 against a mandate floor of 0.00.

## The curve fit

The mandate target runs from +35.2% in the most cautious state to +35.2% in the most aggressive. The achieved portfolio profile runs from -4.1% to +4.6%.

The achieved profile is the portfolio's own per-state return and is not the quantity the objective minimises: the objective weights each instrument's contribution by the regime probability of the state, so the two can differ while the fit is still optimal for this regime.

**How much the fit decided.** The objective is 9041.43 against a floor of 9045.33 with nothing allocated, so the weights control 0.04% of its level.

That is a small share, so this allocation was settled mainly by the mandate's constraints, with the curve fit acting as a tie-breaker between portfolios the constraints already permit. Read the binding constraints above as the substantive answer. The cause is a property of the objective, not a solver failure: it sums shortfall over instruments before squaring, so an instrument at zero weight still contributes its full target to every state, and a probability-normalised regime makes each contribution small against that. Recorded as decisions.md D28 and D29.

The largest remaining shortfall is in state 1 of 25, where the summed gap below the mandate curve is 19.0240. States with no shortfall are already met or exceeded.

## Backtest

24 periods re-optimised, from 2023-01 to 2024-12. Every path is model-derived, not a forecast and not a realised return.

## What a reader must know

- the weights control only 0.04% of the objective's level: the objective is 9041.43 against a floor of 9045.33 with nothing allocated. This allocation is therefore driven mainly by the mandate's constraints, with the curve fit acting as a tie-breaker. The cause is the objective summing shortfall over instruments before squaring, combined with a probability-normalised regime vector, and it is an accepted property of the current model rather than a solver failure. See decisions.md D28 and D29.

---

This is decision-support and research tooling, not investment advice. Every figure is model-derived, not a forecast. Read the binding condition before the number.
