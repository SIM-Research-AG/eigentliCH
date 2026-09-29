# Change report — Life Balance Sheet model reconciliation & update (2026-07-26)

Scope: bring the book, program, and docs into line with the updated canonical model
(the Notion "A Life as an Optimal-Control Problem" note, confirmed by
`CLAUDE_CODE_life_balance_sheet_model_reconciliation.md`), replace the use cases with
the five new Worked Lives, keep Nicolas as a special case, and produce Notion-ready
deliverables (Notion is not writable from this environment, so everything is a local
file for manual upload).

Two locked model decisions applied everywhere: **habit `κ` is on by default** (a stock
with consequences), and **the first portfolio role is "Gain"**, not "Growth". No new
em-dashes were introduced in prose; the haircut symbol is `h_R` (not `κ_R`).

---

## Deliverables produced (for Notion upload)

| File | Purpose | Notion target |
|---|---|---|
| `The_Life_Balance_Sheet_Book_source.html` | the book, rebuilt self-contained | (source) |
| `The_Life_Balance_Sheet_Book.pdf` | regenerated PDF (headless Chrome) | book page (PDF) |
| `The_Life_Balance_Sheet_Book.md` | book as Markdown, LaTeX equations | book page (MD) |
| `Worked_Lives_use_cases.md` | the five new worked lives | Worked Lives page |
| `Nicolas_special_case.md` | how the model fits Nicolas | (new sub-page / article) |

---

## Book — `The_Life_Balance_Sheet_Book_source.html`

Rebuilt **self-contained** (the original `assets/` folder of equation/figure PNGs was
missing, so the old PDF could not be reproduced). Changes:

- **Equations**: every `assets/eq_*.png` replaced with inline **MathML** (Chrome renders
  natively; no external files). No `eq_*.png` remain to regenerate.
- **Figures**: `assets/fig_*.png` replaced with inline **SVG** schematics (phase portrait,
  CVaR distribution, MPC schematic, coupling diagram with the new habit wire, and the
  five worked-life charts). `cover_hero.png` replaced with a clean typographic cover.
- **Ch 3 (state)**: added habit `κ` to the state vector and prose; added the optional
  regime `m`.
- **Ch 4 (controls)**: portfolio now the four roles **Gain, Income, Stabilization,
  Protection** with role chips; `θ` documented as the scalar tilt when the regime layer
  is off.
- **Ch 5 (dynamics)**: added `dκ = α(C−κ)dt` (5.12) and the regime Markov law (5.13);
  wrote `dW_L` in role/regime-dependent form.
- **Ch 6 (coupling)**: network ceiling now `N̄ = N₀ + λ_E E + λ_W W + λ_κ κ`; diagram gained
  a habit node and "habit lifts ceiling" wire.
- **Ch 7 & fundable base**: `Ω^draw = W_L + h_R W_R − D`, `h_home = 0`, **human capital
  excluded** (Definition 7.1 updated).
- **Ch 9 (objective)**: `U(C−κ)` habit-adjusted; habit and leisure stated as distinct
  channels.
- **Ch 10**: HJB stated once (with the regime-jump term) before MPC.
- **Ch 11 (new title "The regime layer and calibration")**: regime layer promoted from a
  future extension to an optional core layer; Merton demoted to a **validation** box
  (unit test, not framing); added params `α`, `λ_κ`, with `λ_κ` flagged least identifiable.
- **Part III replaced**: old Maya/Jonas&Lena/Amara/Nicolas/David chapters retired; new
  Ch 13–17 are the five worked lives; Ch 18 rewritten. Nicolas's backtest moved to the
  companion article; Ch 11 references it generically.
- **Ch 20**: regime-switching item rewritten as "already switched on".
- **Appendix A/B/Notation**: added the habit/HC-Merton equations, `α` and `λ_κ` rows, `h_R`,
  `κ`, role vector, `HC`/`β_HC`.

Backups kept: `The_Life_Balance_Sheet_Book_source.ORIGINAL.html`,
`The_Life_Balance_Sheet_Book.ORIGINAL.pdf`.

---

## Program — `personal_alm/`

### Solver reliability (the calibration prerequisite) — `optim/problem.py`
Replaced the single-phase multistart with a **two-phase solve**:
1. **Feasibility restoration** (`objective="min_shortfall"`): minimise the primary goal's
   CVaR shortfall from aggressive warm starts (`_restore_starts`). No give-up incentive,
   so it finds the best achievable funding `s*` and an aggressive seed.
2. **Utility maximisation** subject to `CVaR ≤ bound`, where `bound = tol` if feasible
   (`s* ≤ 0`) else `s* + tol`. The bound is achievable by construction, so the applied
   plan and its out-of-sample probability respond smoothly instead of collapsing into a
   give-up basin.
Also: `_solve_once` now treats IPOPT `Solved_To_Acceptable_Level` as success (was
reporting spurious non-convergence). The objective's utility/leisure balance was **not**
touched (the reformulation that failed in a prior session).

Harness (`calibrate/reliability.py`, runnable as a module): Nicolas is **stable** across
M_opt=10/14/18 (P = 83/90/89%, spread 8%, was an 83↔90 basin-flip with give-up collapses)
and monotonic in income. Flagship test passes: P≈90%, drawable binds, overtime≈5×,
`success=True`.

### Use cases — `cases.py`
- Old personas (Maya, Jonas & Lena, Amara, David) retired.
- New `WORKED_LIVES = [YOUNG_PRO, INDEPENDENCE_50, NEAR_RETIREE, ENTREPRENEUR, TAIL_SHOCK]`;
  `FIVE_LIVES` kept as a back-compat alias.
- **Nicolas kept** in code (flagship + 26-year backtest anchor + tests) but removed from
  the gallery; he has the standalone article.
- Added `tail_shock_buffer()` sizing helper (book eq. 17.1).
- `run_case` now forwards `extra_goals` and `restore_starts`.

### Tests — `tests/test_cases.py`
- Imports updated to the new names; `test_interface_produces_distinct_results` relaxed
  from an exact `{home,fi,company,retirement}` set to "≥2 distinct kinds, subset of the
  four" (all four kinds are still covered by `test_every_goal_kind_builds_...`).

### App — `app/inputs.py`
- Unchanged in logic: `presets()` iterates `FIVE_LIVES` (now the worked lives), so the
  gallery is the five worked lives. Nicolas is not a preset.

---

## Docs

- `Training_Life_Balance_Sheet.html` (EN) and `Schulung_Life_Balance_Sheet.html` (DE):
  added habit `κ` to the state table + prose, the habit-to-network wire in coupling,
  the four Gain/Income/Stabilization/Protection roles (θ as the layer-off tilt), the
  optional regime layer, HC exclusion in the independence row, the two-phase-solver
  reliability note, and updated the "five lives" and calibration-status text.
- `life_balance_sheet_dashboard.html`: the Nicolas flagship results view. It uses no
  portfolio-role names ("Growth" was **not** present, so no rename was needed) and
  describes results, not the model; tied explicitly to the special-case note. Otherwise
  unchanged (its illustrative numbers remain consistent with Nicolas's case).

---

## Renames applied (Growth → Gain)
- Book: portfolio role introduced as Gain across Ch 4, 5, 8, 11, Part III, appendices.
- Training + Schulung: role tables and prose.
- No other file used "Growth"/"Wachstum" as a role name. The dashboard had none.

## Assets to regenerate
- **None.** The book no longer references external image assets (all inline MathML/SVG).

---

## Calibration results (five worked lives)

<!-- CALIB_TABLE -->

Targets were the **binding mechanism** plus a **sensible confidence** (no per-case book
probabilities exist for the new archetypes; the only fixed number is FI Fundable* = 4.0m).
The young-professional and tail-shock cases are policy/scenario archetypes, so their goals
are set so the engine engages and the intended mechanism (the build-vs-earn exchange rate;
the pre-positioned buffer) is the story rather than a pass/fail FI number.

---

## Points left for review / notes
- **Fundable-base debt term.** `optim/symbolic.py::fi_slack` uses drawable
  `= W_L + h_res·(W_R − D)`, i.e. debt is netted only against the (haircut) real-asset
  term. With `h_res = 0` this gives drawable `= W_L`, which matches the book's
  "spend net of debt service" convention for a self-occupied residence and keeps Nicolas's
  calibration. It differs from the book's general written form `W_L + h_R W_R − D` (full
  debt subtraction) only when `h_R > 0`. Left as-is deliberately; flag if you want the
  general form.
- **Nicolas in the app.** Per instruction he is out of the worked-lives gallery. If you
  want him selectable in the app as a labelled "special case", say so and I will add him
  back as a flagged preset.
- **Exact probabilities.** The two-phase solver makes probabilities *stable*; it does not
  make an arbitrary target dial-in-able on a genuinely hard goal. Where a case is
  ambitious, its probability reflects the honest difficulty (this is the intended
  "illustrative" behaviour).
