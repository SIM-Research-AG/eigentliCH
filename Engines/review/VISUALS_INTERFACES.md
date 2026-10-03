# Balance-sheet and capitals graphs, and the engine benches (build of 03.10.2026)

## The owner's decisions (03.10.2026)

1. **Graphs everywhere:** the lbs and lbsim test benches, the consumer app, the report and the cockpit's client page.
   They follow the nominal/real switch where they show money (default nominal).
2. **Today and over time:** lbs shows today's picture; lbsim adds how the capitals develop year by year, with the
   range of outcomes.
3. **What is shown:**
   - **The life balance sheet as a graph:** assets (financial by vessel: free, pillar 2, pillar 3a, real assets; human
     capital) against liabilities and the goals' claims, with net worth. Amounts in CHF.
   - **The four capitals per adult:** wealth (CHF), health `H`, expertise or education `E`, network `N`. `H`, `E` and `N`
     are model levels without a currency (lbs `human_capital[].E/N/H.value`, with their scales from lbs's
     `human-capital` record); they are shown on their own scale with words, not as money, and never on a money axis.
4. **The benches show what the engine does:** each bench has a short plain explanation of the engine's job, a picker
   of real use-case clients that fills a valid request (no empty or hand-typed ids), and the engine's result drawn as
   graphs. The report bench shows a rendered report page as the client sees it.
5. Standing rules: no raw ids or keys where people read; one language per page; British spelling, no em-dashes in
   docs; no external scripts except the cockpit's existing Plotly; the report keeps inline SVG with every printed value
   a fact (the digit rule).

## The one new engine field (lbsim, additive, fixed for every agent)

`LifeBalancePaths.regimes[].capitals` (optional; absent on artefacts made before it), for the **principal**
(the draft simulates one person; the partner enters as income only, P-6):

```json
"capitals": {
  "person_id": "<the principal's person_id>",
  "expertise": {"p10": [..], "p25": [..], "p50": [..], "p75": [..], "p90": [..]},
  "network":   {"p10": [..], "p25": [..], "p50": [..], "p75": [..], "p90": [..]},
  "health":    {"p10": [..], "p25": [..], "p50": [..], "p75": [..], "p90": [..]},
  "scale": {"expertise": {"min": 0, "max": K_E}, "network": {"min": 0, "max": K_N}, "health": {"min": 0, "max": K_H}},
  "labels": {"expertise": {"de": "Wissen und Ausbildung", "en": "Expertise and education"},
             "network":   {"de": "Netzwerk", "en": "Network"},
             "health":    {"de": "Gesundheit", "en": "Health"}}
}
```

Each list has `horizon_years + 1` year-end values from the same Monte Carlo draws as the wealth bands (the model's
state `E`, `N`, `H`). `K_E`, `K_N`, `K_H` are the model's ceilings from the active calibration. Wealth over time is the
existing `bands.net_worth` (nominal and real).

The lbs sheet already carries today's values: `human_capital[]` per adult with `E`, `N`, `H`, and the balance sheet's
`totals` (by vessel, liabilities). Agents read field names from `engines/lbs/src/lbs/contracts.py`.
