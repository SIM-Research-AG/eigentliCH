# Rounding for display (owner, 03.10.2026)

"The numbers should be rounded meaningfully in all the engines in the sim-tech cockpit as well as in the eigentliCH
system." One rule for every number a person reads: the consumer app, the report pages, the cockpit (all pages and
panels) and every engine's test bench.

## The principle

- **Display only.** Engines keep computing and storing exact values. Contracts, artefacts, ids, hashes, stored facts
  and the raw JSON views for experts are never rounded. Rounding happens at the last step, where a number becomes text
  or a chart label.
- **No false precision.** A figure carries no more digits than the model can stand behind.
- **One formatter per code base**, used everywhere in it (one in the app's client, one in report, one in the cockpit
  page, one shared snippet the benches copy). No ad-hoc `toFixed` or f-string formats left behind.
- Where rounded parts are shown next to a rounded total, the total is rounded from the exact sum (never summed from the
  rounded parts), and a table that may not add up says "gerundet" / "rounded" once.

## The rules

| Kind | Rule | Examples |
|---|---|---|
| CHF (and EUR, USD) amounts, stocks and per year | below 1 000: whole units; 1 000 to 99 999: nearest 100; 100 000 to 999 999: nearest 1 000; from 1 000 000: millions with two decimals ("Mio." / "m"); from a billion "Mrd." / "bn", from a trillion "Bio." / "tn" | 640; 38 200; 579 000; CHF 1.35 Mio.; USD 27.36 tn |
| Small amounts that matter exactly (a fee, a deposit already stated by the client, a stated price) | the client's own stated figure is shown as stated | 1 800 |
| Returns, rates, inflation, required return | one decimal, percent | 4.9 %; −1.3 % |
| Chances (probabilities) | whole percent; below 1 % "unter 1 %" / "below 1 %"; above 99 % "über 99 %" / "above 99 %"; exactly 0 or 1 only when every path agrees, then "0 %" / "100 %" | 68 %; über 99 % |
| Portfolio weights and shares | whole percent; below 1 % one decimal; 0 shown as "–" | 27 %; 0.4 % |
| Model levels without a unit (expertise, network, health, scores 0 to 1) | a word first, then two decimals | mittel (0.62) |
| Raw model figures of no stated kind (bench diagnostics, residuals) | three significant digits; below 0.0001 in exponent form with two significant digits | 0.0123; 3.2e−12 |
| Betas, durations, ratios | one decimal (betas two decimals) | Duration 6.0; β 0.80 |
| Years, ages, hours, counts | whole numbers | 2034; 67; 20 Std. |
| Dates | as today (dd.mm.yyyy in German, d Mon yyyy in English) | 29.09.2026 |

Thousands separator, decimal mark and currency placement stay as each page already does them (the app and report use
a space as thousands separator and "CHF" before the amount); only the number of digits changes.

## Report specifics

The report's digit rule and facts stay: the fact keeps the exact value; its `display` is the rounded text. Golden pages
are rebuilt; prose from MiniMind receives the rounded displays, so the sentences use the same rounded figures.

## Charts

Axis ticks, labels and tooltips follow the same rules. Hover tooltips in the cockpit may show one more digit than the
label, never the raw float.
