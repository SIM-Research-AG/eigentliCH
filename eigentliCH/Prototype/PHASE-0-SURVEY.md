# andersCH — Phase 0 survey

Deliverable of build-spec §10 phase 0. **Nothing has been built.** Phase 0's gate is
"canonical versions declared by a human", and two of those declarations are still open
(D-08). This file is the written inventory; the questions it raises are at the end.

Surveyed 30 August 2026 against `andersCH-build-spec.html` v1.0.

---

## 0. A correction to the spec itself

Spec §"Target stack" says: *HTML/JS front end with a Python backend, matching the
existing prototype.*

That describes **`andersCH/` (the parent folder)**, not `andersCH-prototype/`.
`andersCH-prototype/` is a pnpm/Next.js + TypeScript monorepo plus a pile of loose
single-file HTML prototypes. The Python backend, the engines, the contracts layer, the
Decision Record and the Curator Workbench all live one level up in `andersCH/`.

So "the existing prototype" names two different code estates depending on which
sentence of the spec you read. This is upstream of D-08 — see question **Q1**.

---

## 1. Onboarding questionnaire (spec S-01, §9 "reuse the schema")

**Reusable, and it is the strongest asset in the estate.**

| | |
|---|---|
| Schema | `andersCH-prototype/onboarding.schema.json` |
| Schema version | **`onb@0.1.3`** (const, enforced) |
| Implementation | `andersCH-prototype/onboarding-chat.html` — 193 KB, single file, 25 Aug 2026 (newest client artefact in the estate) |
| Questions | **78**, each with a unique model key |
| Sections | 11 — Person 17, Weiteres 12, Arbeit 8, Vermögen 7, Erwerbskraft 6, Immobilien 6, Feinjustierung 6, Ziele 5, Risiko 5, Weiterbildung 4, Anliegen 2 |
| Conditional | 36 of 78 gated behind `onlyIf` predicates |
| Hard-required | 7 (`req:1`); 51 marked `core:1` |
| Language | German |

Version history is documented inside the schema: 0.1.0 → 0.1.1 (4 Aug, partner params +
P6), → 0.1.2 (9 Aug, children as dynamic cost), → 0.1.3 (20 Aug, mortgage and exit
params). The schema also records that **`state` becoming `persons: [...]` will be the
breaking 0.2.0** — worth knowing before mapping to `Position`.

Each question already declares the engine field it fills (`k:`), and the schema's own
docstring states the design rule: *"the engine consumes the schema, never the
conversation."* That is compatible with C-02 and with §7.

**Two things the questionnaire does not have**, both required by the spec:

- No **age floor** (R-100). `birth_year` accepts `min:1930, max:2010` — a 2010 birth year
  is 16. Nothing rejects under-25 (NG-05).
- No **resumability** (R-101). State is in-page; there is no per-question persistence.

**Mapping note:** the schema targets the Life Balance Sheet engine's own state
variables. The spec's `Position` / `Goal` model is a different shape. A mapping proposal
is Phase 2 work and is not attempted here.

## 2. Client submissions — moved as requested

Eight saved submissions copied to **`andersCH-prototype2/client/submissions/`**
(originals left in place). These are **real answers from named real people**, not
fixtures.

| File | Schema | Raw answers |
|---|---|---|
| *(named submission A)* | `onb@0.1.3` | 44 |
| *(named submission B)* | `onb@0.1.3` | 50 |
| *(named submission C)* | `onb@0.1.3` | 47 |
| `andersch-onboarding-2026-08-18.json` | `onb@0.1.2` | 57 |
| `andersch-onboarding-2026-08-06 (1).json` | `onb@0.1.1` | 56 |
| `andersch-onboarding-2026-08-06 (2).json` | `onb@0.1.1` | 51 |
| `andersch-onboarding-2026-08-05.json` | `onb@0.1.1` | 51 |
| `andersch-onboarding-2026-08-05 (3).json` | `onb@0.1.1` | 51 |

**Three filenames are redacted above.** They were real people's surnames. This file was clean
as a *path* — it is not one of the ignored submissions — but not clean as *text*: a table of
filenames is a list of who has an andersCH account, and membership is itself a personal fact.
The dated filenames carry no name and are left as written. Found on 30 August 2026 while
building the distribution, by a content scan rather than a path scan; the same scan is now part
of `tools/make_distribution.py`, so a ZIP cannot ship this either.

Only the three named ones are at the current schema. The five dated ones are 0.1.1/0.1.2
and, by the schema's own rule, **a 0.1.3 consumer must refuse rather than guess** — they
are historical, not a test corpus, unless they are migrated deliberately.

**`.gitignore` was amended.** The existing rule
`andersCH-prototype/andersch-onboarding-*.json` is anchored to the old directory and did
not reach the copy. Without the amendment this move would have made real client
financial data committable — precisely the failure the 5 August generalisation in that
file was written against. Added `andersCH-prototype2/client/submissions/` plus two
`**/`-anchored patterns, and verified with `git check-ignore`.

## 3. Python backend (spec §9 "extend rather than replace. Report its routes")

There is **no member-application backend**. There are two unrelated local servers, both
`http.server`, neither with auth, sessions, a database, or a member concept.

**`cockpit/server.py`** (180 lines) — internal panel viewer.

```
GET  /  |  /index.html
GET  /api/context
GET  /api/<panel>              # dispatch over a PANELS registry
POST /api/<panel>
```

**`desktop/server.py`** (698 lines) — local desktop hub, launched from `desktop/andersCH.cmd`.

```
GET  /replays        /replay-data/<id>   /hub      /file/<path>
GET  /favicon.ico    /questionnaire      /questionnaire-info
GET  /health         /dashboard
POST /prose          /ask                /gameplan  /readiness
```

Assessment: **neither is the backend the spec assumes.** Extending either to carry
`Member`, auth, an age floor, consent records and per-question persistence is close to
writing a new server around the existing `contracts/` and `engines/` layers — which are
genuinely reusable. The spec's §6 API surface has essentially no overlap with what exists.

## 4. Engines (spec §7)

The out-of-process pattern the spec asks for **already exists and is well argued**
(`engines/base.py`). Do not rebuild it.

Seven registered in `ENGINE_HOMES`:

| Engine | Home | Note |
|---|---|---|
| `market_signal` | `Macro_Model` | own venv — pandas 3.0.5 / numpy 2.5.1 |
| `return_estimation` | `Fund_Map` | own venv — pandas pinned <3 |
| `portfolio_optimiser` | `PCP` | own venv — + scipy |
| `life_balance_sheet` | `Life_Balance_Sheet` | own venv — + casadi. **The engine onboarding feeds.** |
| `s_curve_trajectory` | native | in-process |
| `scenario_generator` | native | in-process |
| `score_engine` | native | in-process — see §6 |

`base.py` documents why the dependency trees cannot be unified. That matches the spec's
"do not attempt to unify" exactly.

**Gaps against §7:**

- **No `manifest.json` exists anywhere in the estate.** R-300 says an engine without one
  is not callable — so all seven are currently non-callable under the new rules. Seven
  manifests must be authored, and **each needs a declared IP owner, which is recorded
  nowhere I can find** (Q4).
- **No per-engine timeout.** One default of `900s` for all of them. R-301 forbids calling
  anything over 2s on a request thread — at 900s that is all of them, so the
  queue-and-poll path is mandatory, not optional.
- The interface is `EngineAdapter.run()`, not the spec's
  `call_engine(name, payload, timeout_s)`. A thin façade over the existing registry is
  the honest way to get the spec's call site.

## 5. andersCH-owned components that already exist

| Component | Where | State |
|---|---|---|
| Decision Record | `contracts/schemas/DecisionRecord.schema.json`, `curator/decide.py` | Real, and stricter than the spec in places — rationale required, minimum length enforced, blocking concerns must be named by key, pre-check refusals cannot be signed over. **But its shape is different:** keyed on `household_id` + `recommendation_id` + `snapshot_id`, i.e. a record of a *curator releasing advice*. The spec's `Decision` is keyed on `member_id` and wraps *every plan mutation* (C-09). Two different objects with one name. |
| Curator Workbench | `curator/` + `curator/workbench.html` (86 KB, 3 Aug) | Partially built: `queue.py`, `review.py`, `decide.py`, `render.py`. No member-granted, scoped, time-limited, revocable access (R-210, R-213) — it assumes the curator sees the case. |
| Data classes K0–K3 | `architecture/DECISIONS.md`, `architecture/SYSTEM_MANUAL.md` | **A documented convention, not a column.** C-04 requires a field on the model with a logging filter behind it. Nothing to reuse but the vocabulary. Mapping in use: K0 SIM content · K1 Score/traces · K2 twin/client data · K3 Recommendations + Decision Records. This **inverts the spec's §4 assignment** in places (Q5). |
| Contracts layer | `contracts/` — 7 pydantic models, JSON Schema emitted by `make contracts` | Reusable. Schemas are build artefacts; do not hand-edit `contracts/schemas/`. |
| FDT event stream | `fdt/store.py`, `fdt/twin.py`, `data/fdt/hh-*.jsonl` | Append-only per-household event log. Plausibly the substrate for C-09 / R-040 immutability. |
| Deterministic coach | `client/coach.py` | **Directly relevant to C-01 and R-172.** Not a language model — a deterministic explainer with `classify()` as a refusal boundary that routes to a Curator, deliberately erring towards refusing. The closest thing in the estate to the server-side boundary check §6 demands. |

## 6. Constraint violations found in existing code

Reported, not fixed.

**C-07 (no gamification primitives) — three collisions, of two different kinds.**

1. **Real violation, deliberate.**
   `andersCH-prototype/apps/anderschapp/lib/domain/score.ts` and `score-config.ts`
   implement `ScoreState.total` as an **XP counter**, with tunable XP award rates,
   "ceremony triggers", and a `LadderRank` of
   Apprentice → Junior Curator → Curator → Senior Curator. The file's own comment cites a
   2026-08-01 gamification decision. This is exactly what C-07 forbids and cannot be
   reused for the learning layer. It also pre-empts D-01 (the rung scheme), which the
   spec says must stay unset.

2. **Real violation, in the newest client.** `andersCH/surfaces/home.js` renders an
   **"altitude ring"**: `alt.score` on a 0–100 scale drawn as a progress ring, with
   `"{n} of {applicable} answered"` and a "next stage" line. That is a completion meter
   and a progress ring (R-113), progress-as-achievement (R-006), and a score (C-07), in
   the default landing screen.

3. **Name collision, not a violation.** `engines/score/` and the `Score` contract are an
   analytical household-standing measure, decomposable by design, with weights that must
   sum to one and are labelled an editorial judgement. Nothing gamified — but a literal
   grep for `score` in the model layer (the spec's
   `test_no_gamification_identifiers_in_model_layer()`) will fail on it (Q6).

**R-143 (no mountain vocabulary in authenticated UI).** "Altitude" is load-bearing
throughout the 19 Aug client: `app/state.js`, `app/observe.js`, `surfaces/home.js`,
`surfaces/plan.js`, `surfaces/market.js`, and in the content files `data/copy.json`,
`data/rules.json`, `data/profile.json`, `data/market.json`. It is a data key, not just a
string — a schema change, not a copy edit.

**NG-05 / R-100.** No age floor anywhere.

## 7. The two blocking ambiguities (D-08)

### Client application — 6 candidates, none declared canonical

| # | What | Where | Date | Stack |
|---|---|---|---|---|
| 1 | ES-module SPA — Tree · Know · Plan · Market | `andersCH/index.html` + `app/` + `surfaces/` + `style/` | **19 Aug** | vanilla JS, no build |
| 2 | Next.js app — chat, home, marketplace, network, profile, wisdom, tree-poc | `andersCH-prototype/apps/anderschapp/` | 1 Aug | Next + TS + Tailwind |
| 3 | Single-file prototypes v1→v7 | `andersCH-prototype/anderschapp*.html` | 13 May → 9 Aug | standalone HTML |
| 4 | Python-rendered client pages | `andersCH/client/` (`build.py`, `render.py`, `plan*.html`) | 3 Aug | server-rendered static |
| 5 | Next.js onboarding demo (10 scripted screens) | `andersCH-prototype/apps/onboarding-demo/` | 13 May | Next + TS |
| 6 | Desktop hub | `andersCH/desktop/` | 25 Aug | local `http.server` + HTML |

Newest is #1 (19 Aug) — and it is also the one carrying the altitude ring, so
"newest wins" is not a safe default. `MOCKUP.md` describes #1 and says that where it
contradicts `CLAUDE_New_Try.md` "the brief wins" — but that brief predates this spec,
and this spec is now leading.

### Chatbot / MiniMind — 4 candidates, none declared canonical

| # | What | Where | Kind |
|---|---|---|---|
| 1 | `client/coach.py` | deterministic explainer, refusal boundary, **no generation step** | K0-safe by construction |
| 2 | `desktop/coach.py` | local model over the house's own K0 corpus, allow-list + `_clean_or_refuse` guard | 45 KB, 25 Aug, newest |
| 3 | `app/ask.js` + `app/chat.js` + `surfaces/know.js` | client-side two-mode ask (Quick / Deep learning), inspectable keyword branch matcher | in the 19 Aug SPA |
| 4 | `apps/anderschapp/app/api/chat/route.ts` + `lib/llm/` + `lib/master-prompt.ts` | provider-agnostic tool-calling loop, Apertus via Ollama, no cloud path | Next.js |

**These are not four versions of one thing.** #1 and #2 are deliberate non-recommenders
and already satisfy C-01 structurally rather than by prompt. #4 is the only one with
tool-calling and a master prompt, and the only one whose boundary would rest on prompt
instructions — which §6 explicitly forbids. #3 runs in the browser, which C-03 forbids
for anything touching an engine.

---

## Questions blocking phase 1

**Q1 — Which estate is the base?** `andersCH/` (Python + contracts + engines + HTML/JS)
or `andersCH-prototype/` (Next.js monorepo)? The spec's stack sentence points at the
first, its file paths at the second. Everything below depends on this.

**Q2 — Which client is canonical?** (6 candidates above.) Not a technical preference —
spec §9.

**Q3 — Which chatbot is canonical?** (4 candidates above.) #1/#2 vs #4 is a compliance
choice, not a stack choice.

**Q4 — Who is the declared IP owner of each of the seven engines?** R-300 makes this a
required manifest field and it is recorded nowhere.

**Q5 — Does the spec's K-class assignment or the estate's win?** They disagree: the
estate has Decision Records at K3 and the Score at K1; the spec §4 puts `Decision` at K2,
`VaultItem` at K3, `AssumptionSet` at K0.

**Q6 — `Score` / `score_engine`: rename, or scope the C-07 grep?** The analytical score
is not gamification, but the acceptance test as written will fail on it.

**Q7 — Do the five pre-0.1.3 submissions get migrated, or archived?** The schema's own
rule says a 0.1.3 consumer must refuse them.

---

## 8. A seventh client, found in git after the survey (30 August 2026)

**The survey above was taken from the filesystem, and missed this.** `git status` in the
parent repo shows **34 files deleted from the working tree under `andersCH-prototype2/`**,
tracked since the initial commit of 3 August 2026 and present in `HEAD` (`4220af3`). They
exist nowhere on disk.

They are a **seventh client candidate** — a Next.js knowledge-tree application, distinct
from the `andersCH-prototype/apps/anderschapp/` that is on disk:

```
apps/anderschapp/lib/game/puzzle.ts          lib/game/world-builder.ts
apps/anderschapp/components/quest/QuestScene.tsx   quest/PuzzleModal.tsx
apps/anderschapp/components/tree3d/HomeTree.tsx    components/ArticleReader.tsx
apps/anderschapp/content/curriculum/*.json   (5 curricula)
apps/anderschapp/lib/curriculum.ts           lib/learning-context.tsx
apps/anderschapp/lib/domain/score.test.ts    lib/puzzle-prompt.ts
apps/anderschapp/app/api/chat/route.ts       lib/llm/*
```

It is a **quest game**: typed puzzles (`riddle | multiple_choice | order | match |
fill_blank`), shrines that are "ALWAYS solvable", a world builder, and a scored learning
loop. That makes it the most gamified of the seven and the furthest from C-07 — but it is
also the only one carrying **five authored curricula**, which R-192 and S-10 will need and
which nothing else in the estate has.

**Nothing is lost.** Every file is in `HEAD`. The risk is narrow and specific: a
`git add -A` or `git commit -a` from the repo root would record the 34 deletions as an
intentional removal.

**No commit has been made, and the A7 rename is held until this is decided.** Three ways:

1. **Restore to a sibling path** — `git checkout HEAD -- andersCH-prototype2/` then move it
   to e.g. `andersCH-prototype-knowledge-tree/`. Keeps the curricula reachable, gets the
   name collision out of the way. *Recommended.*
2. **Leave it in git only** and commit the deletion deliberately, with the message naming
   `4220af3` as where it lives.
3. **Restore in place first** and review it as a client candidate before deciding — the
   curricula in particular.

The path collision is the root cause: the new build was given the name of a tracked
directory that already had content.
