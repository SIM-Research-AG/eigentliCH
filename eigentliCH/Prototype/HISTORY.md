# andersCH prototype2 — the history

**This file is the record. [DECISIONS.md](DECISIONS.md) is the rules.**

Split on 20 September 2026 (A170). `DECISIONS.md` had grown to 169 entries and most of them were
forensic narratives rather than standing rules — the account of a defect found, what it cost and what was
decided about it. Those are the most valuable thing in this repository and the least useful way to answer
"what are the rules". So the standing rules were restated in `DECISIONS.md`, each keeping its original
number and date, and **every one of the 169 entries is reproduced here unchanged**, including the ones
whose rule is still live. Nothing was deleted and nothing was rewritten.

Two things are added rather than changed:

- **A dated withdrawal line** at the head of each entry that existed to serve C-01, which the owner
  withdrew on 20 September 2026. Eleven entries carry one. The entry itself is untouched below it.
- **This index**, so an entry can be found by number without scrolling.

The product was renamed after this split. Entries here use the name the product had when they were
written, for the same reason the three departed colleagues are described by role rather than erased:
rewriting the record to say events happened differently makes it untrustworthy for every other claim.

---

## Index

- [A1](#a1) — Base estate: **both**
- [A2](#a2) — Client: **new, on the 19 Aug SPA's pattern**
- [A3](#a3) — Chatbot: **#4's loop, ported to Python**
- [A4](#a4) — Engine IP owners: **superseded by A10**
- [A5](#a5) — Data classes: **spec §4 wins**
- [A6](#a6) — `Score` name collision: **scope the C-07 grep**
- [A7](#a7) — Decision naming: **rename the existing, take the name**
- [A8](#a8) — Pre-0.1.3 submissions: **archived, not consumed**
- [A9](#a9) — Backend stack: **FastAPI + SQLAlchemy + SQLite + Alembic**
- [A10](#a10) — Engine IP owners: **SIM Research owns all seven**
- [A11](#a11) — Auth: **email + password, self-hosted**
- [A12](#a12) — Language: **bilingual from the start, de-CH default**
- [A13](#a13) — Onboarding questions: **rewritten against Position and Goal**
- [A14](#a14) — The A7 rename: **now, as its own isolated step**
- [A15](#a15) — The 34 orphaned files: **left in git, deletion committed deliberately**
- [A16](#a16) — The five curricula: **discarded with the game layer**
- [A17](#a17) — The A7 rename, as executed
- [A18](#a18) — Two findings surfaced by the rename, both left open
- [A19](#a19) — Role definitions: **sourced from the System Build Manual**
- [A20](#a20) — A vacuous test, and the guard added because of it
- [A21](#a21) — German role terms, reviewed
- [A22](#a22) — D-07 resolved: the destination is the spec's own phrase
- [A23](#a23) — The 78 existing questions, extracted before any rewriting
- [A24](#a24) — Role grid on a narrow screen: **paired cards per role**
- [A25](#a25) — The new onboarding questions: **reconsidered, wording reused where it fits**
- [A26](#a26) — Language switching: **a setting, on `Member.locale`**
- [A27](#a27) — Password reset: **deferred until the mail route is named**
- [A28](#a28) — What phase 2 actually shipped
- [A29](#a29) — Correlation tags: **free text, optional**
- [A30](#a30) — Magnitude: **optional, and its unit never inferred**
- [A31](#a31) — S-01 question set: **four questions, only the first required**
- [A32](#a32) — Onboarding completion is single-shot
- [A33](#a33) — Interpretation runs on the local model, and is checked
- [A34](#a34) — What "already trained with the books" turned out to mean
- [A35](#a35) — AssumptionSet: **seeded from the estate's own engines**
- [A36](#a36) — The local model may read K3
- [A37](#a37) — Working scope: **everything reachable, inventing nothing**
- [A38](#a38) — Commits: **one per phase, on a branch off master**
- [A39](#a39) — Engine inputs: **a mapping layer, gaps left visible**
- [A40](#a40) — Curators: **their own table and their own login**
- [A41](#a41) — Market Place and learning content: **fictional seed data**
- [A42](#a42) — The eight German role definitions: **reviewed**
- [A43](#a43) — Password reset is a backend operation, not a mail flow
- [A44](#a44) — The Modelfile naming mismatch, cleared
- [A45](#a45) — Containers (S-04), and the field §4 does not list
- [A46](#a46) — The System Build Manual is kept current
- [A47](#a47) — A deployable distribution, for a naked laptop
- [A48](#a48) — Vault decisions taken while building phase 3
- [A49](#a49) **[withdrawn]** — How C-01 is actually enforced (phase 4)
- [A50](#a50) — The age floor is 18, not 25
- [A51](#a51) — The design system is the live site's, verbatim
- [A52](#a52) — Phase 6 shipped as learning, and one file was renamed
- [A53](#a53) — Demonstration accounts, and why their passwords may be written down
- [A54](#a54) — A finding that bears on the age floor
- [A55](#a55) — The persona framework narrowed to 18–60, and Lea aged up
- [A56](#a56) — One demonstration account per persona, each with its own password
- [A57](#a57) — A timezone bug that would have crashed every real login
- [A58](#a58) — Phases 7 and 8, and the client surfaces
- [A59](#a59) — Three defects the parallel work surfaced, all real
- [A60](#a60) — Elio: documented like the others, but good for one login
- [A61](#a61) — R-231's erasure: null the reference, and empty the fields that hold the person
- [A62](#a62) — The curators are five named people
- [A63](#a63) — A migration silently switched off an append-only trigger
- [A64](#a64) — Routers wired, and a test that was right becoming wrong
- [A65](#a65) — The desktop app reports the real state
- [A66](#a66) — Erasure left the database with no append-only triggers at all
- [A67](#a67) — The curator directory, and a hole it exposed
- [A68](#a68) — A63 was never fixed, and the test that guarded it had never run a migration · 2026-08-30
- [A69](#a69) — The engines run in their own interpreter, and C-02 has a published set · 2026-08-30
- [A70](#a70) — The accessibility pass, and a CSS rule that was deleting data · 2026-08-30
- [A71](#a71) — C-04's filter was installed and inert in the running server · 2026-08-30
- [A72](#a72) — C-09 held for the ORM and not for the Session · 2026-08-30
- [A73](#a73) — A member who had applied to be listed could not be erased at all · 2026-08-30
- [A74](#a74) — Ordering cannot be bought, and now cannot be taken with a checkbox either · 2026-08-30
- [A75](#a75) — C-06's content half, and why it is a trigger rather than a CHECK · 2026-08-30
- [A76](#a76) **[withdrawn]** — C-01 is a blacklist, blacklists are unbounded, and the destination is grounding · 2026-08-30
- [A77](#a77) — The exception hole in C-04, closed by not needing to see the traceback · 2026-08-31
- [A78](#a78) **[withdrawn]** — C-01, third round: how people actually type, and a comparison left unfinished · 2026-08-31
- [A107](#a107) **[withdrawn]** — C-01 now admits a statement of statutory duty, and still refuses it in the subjunctive
- [A106](#a106) — The Know surface returned confidently wrong law; it now quotes instead of paraphrasing
- [A79](#a79) — The application had no authentication at its boundary, and now does · 2026-08-31
- [A80](#a80) — The book index is wired, and the calibration that made it honest · 2026-08-31
- [A81](#a81) — Login, wired by removing the parameter rather than checking it · 2026-08-31
- [A82](#a82) — D-01, D-02 and D-04 are answered. §12's list is now empty. · 2026-08-31
- [A83](#a83) **[withdrawn]** — C-01 admits statements of statutory duty · 2026-08-31
- [A84](#a84) — R-152's other sources: action items derived from the plan itself · 2026-08-31
- [A85](#a85) — The engines are reachable from the product, and a goal returns a number · 2026-08-31
- [A86](#a86) — Five defects the owner found by using the application · 2026-08-31
- [A87](#a87) **[withdrawn]** — C-01 was reading the wrong vocabulary: advice about a member's own plan was not advice · 2026-08-31
- [A88](#a88) — Two guarantees that could not fire, and the fourth backspace byte · 2026-08-31
- [A89](#a89) — Five real curators had credentials and nowhere to use them · 2026-08-31
- [A90](#a90) — The audit, and what it says about the shape of the build · 2026-08-31
- [A91](#a91) — Two more guards that could not fail, and one that could not see · 2026-08-31
- [A92](#a92) **[withdrawn]** — S-07 Decisions, and C-01 had no word for a decision · 2026-08-31
- [A93](#a93) — Consent is captured, and erasure is reachable · 2026-08-31
- [A94](#a94) — The capability route, and R-005's gate becoming passable · 2026-08-31
- [A95](#a95) — Three more filters that could not see, one of them mine · 2026-08-31
- [A96](#a96) — A correction chain ordered by the clock, and a guard that was flaky about a flaky bug · 2026-08-31
- [A97](#a97) — The decision record is a notice, not a consent · 2026-08-31
- [A98](#a98) — `CuratorSession.curator_id` is a foreign key, and what that cost in the development database · 2026-08-31
- [A99](#a99) — Three payloads that carried a decision nobody could read · 2026-08-31
- [A100](#a100) — The seeding call that nobody made, and why the demonstration did not work · 2026-08-31
- [A101](#a101) **[withdrawn]** — C-01 refused the modal and passed the imperative · 2026-08-31
- [A102](#a102) **[withdrawn]** — A101 had a hole on the day it landed, and the model writes advice with nobody in it · 2026-08-31
- [A103](#a103) — The wrong-law risk is worse than recorded, and was the one thing missing from the board · 2026-08-31
- [A104](#a104) — Consent withdrawal: soften the wording, not the behaviour · 2026-09-01
- [A105](#a105) — A market return rate was being applied to a salary · 2026-09-01
- [A108](#a108) — The household is a table, not a column, and it is never backfilled · 2026-09-03
- [A109](#a109) — Erasure redacts a household membership; the export carries the whole composition · 2026-09-03
- [A110](#a110) — The validity horizons are a content record, not a published assumption table · 2026-09-03
- [A111](#a111) — A plan version is a numbered baseline, and its household stamp is copied rather than joined · 2026-09-03
- [A112](#a112) — How a household change is learned, and what happens when one closes · 2026-09-03
- [A113](#a113) **[withdrawn]** — The ask field's three branches, and the boundary that was being crossed to answer a question below it · 2026-09-03
- [A114](#a114) **[withdrawn]** — C-01 required the pronoun next to the modal, so the one forbidden sentence passed · 2026-09-03
- [A115](#a115) — The Curator button was two taps on a phone, and inside something that closes · 2026-09-03
- [A116](#a116) — The question field is the landing screen, and it holds its own answer · 2026-09-03
- [A117](#a117) — The intake asks the household first, and records who drove it · 2026-09-03
- [A118](#a118) — The intake identities, reimplemented in Python against the original's own output · 2026-09-03
- [A119](#a119) — Progress is a consequence, and the payload carries no number at all · 2026-09-03
- [A120](#a120) — The first-session finding, and the figures the Befund did not have · 2026-09-04
- [A121](#a121) — Three doors: Vault, Know, Market. The Befund moved inside and the Plan door became the Vault · 2026-09-04
- [A122](#a122) — The blocking liquidity finding, built narrow because the vocabulary it needs does not exist · 2026-09-04
- [A123](#a123) — The Actions pane, the Regime before sign-in, and where community belongs · 2026-09-04
- [A124](#a124) — Item 7's two hard rules, and what "recover" meant · 2026-09-04
- [A125](#a125) — Content hooks: one implementation, two directions · 2026-09-04
- [A126](#a126) — The Feed, in the Reading Room's shape, with two sections that say what they are waiting for · 2026-09-04
- [A127](#a127) — The five instrument keys, stored as facts rather than columns · 2026-09-04
- [A128](#a128) — The pre-authentication archive was deleted rather than left labelled · 2026-09-04
- [A129](#a129) — Property is bought with a mortgage, and the plan had no way to say so · 2026-09-04
- [A130](#a130) — A credential is not a plan, and Yasmin lost her record to the difference · 2026-09-04
- [A131](#a131) — Two symbols mean opposite quantities on the two sides of the engine bridge · 2026-09-04
- [A132](#a132) — The debt is one debt, and it belongs to the household · 2026-09-04
- [A133](#a133) — Four rulings taken on 4 September, and what each one moved · 2026-09-04
- [A134](#a134) — The developer database was missing two tables and no household could ever have been written · 2026-09-04
- [A135](#a135) — The Know now answers all six members' questions, and the reason it did not is worth keeping · 2026-09-04
- [A136](#a136) — Tresor, Wissen, Marktplatz · 2026-09-04
- [A137](#a137) — The occupancy question is askable, and running it found the mirror of A110 · 2026-09-04
- [A138](#a138) — The archived submissions are richer than the current ones, and 0.1.3 dropped the questions this week needed · 2026-09-04
- [A139](#a139) — The corpus answers the six it was written for, and does not generalise · 2026-09-04
- [A140](#a140) — Four invented Swiss names, in the file rather than in the code · 2026-09-04
- [A141](#a141) — A8 reversed: the four are loaded and are ordinary members · 2026-09-04
- [A142](#a142) — `W_L` is liquid wealth and the submissions do not agree with each other about what is liquid · 2026-09-04
- [A143](#a143) — The report covers all ten, and the allocation chart is the one that changed the reading · 2026-09-05
- [A144](#a144) — Four members are 39 to 62, and that is a different product · 2026-09-05
- [A145](#a145) — The local model is qwen2.5:14b, measured rather than assumed · 2026-09-05
- [A146](#a146) — The model store lives on D:, reached by a junction rather than an environment variable · 2026-09-05
- [A147](#a147) — Four Swiss rule sources went into the index, and the figures came out of memory into quotation · 2026-09-05
- [A148](#a148) — The equity ceiling: two constraints, the conservative binds, and it changes exactly one member · 2026-09-05
- [A149](#a149) — An entry in the approval queue was tripping the outbound gate, and nothing was checking · 2026-09-05
- [A150](#a150) — A148 is withdrawn: the allocation comes from the Optimiser, and the return is the manual's · 2026-09-05
- [A151](#a151) — The occupancy question is on the screen, and answering it found a second defect · 2026-09-05
- [A152](#a152) — Alias groups: the query is widened, never the corpus, and the floor moves to a different number · 2026-09-05
- [A153](#a153) — The first two pillars are in the model, from the statutory table and the age bands · 2026-09-05
- [A154](#a154) — The intake file is kept whole, and mapped afterwards · 2026-09-06
- [A155](#a155) — Two portfolios became six, because the inputs that could distinguish clients finally do · 2026-09-06
- [A156](#a156) — R-210 is relaxed for the curator dashboard, and the scope of that is written down · 2026-09-06
- [A157](#a157) — «No equity» was an infeasible mandate, not a considered allocation · 2026-09-06
- [A158](#a158) — Capacity becomes the signal, behaviour lifts as well as caps, and nothing is removed · 2026-09-06
- [A159](#a159) — The capacity inputs come from the plan first and the stored submission second · 2026-09-06
- [A160](#a160) — The cull of 20 September 2026: what was asked, what was ruled, and what it costs · 2026-09-20
- [A161](#a161) — Three curators left, and the rows stayed · 2026-09-20
- [A162](#a162) — The member keeps the record and loses the name · 2026-09-20
- [A163](#a163) — The register keeps its history and loses the names · 2026-09-20
- [A164](#a164) — C-01 is deleted, and this is what it was catching on its last day · 2026-09-20
- [A165](#a165) — The router keeps the boundary that protects the vault and loses the one that protected a licence · 2026-09-20
- [A166](#a166) — The Optimiser's allocation reaches the member, and nothing stands between them · 2026-09-20
- [A167](#a167) — The curriculum's handoffs were reported, and all ten of them survive · 2026-09-20
- [A168](#a168) — C-06 is dropped, and an action item is now well-formed only by convention · 2026-09-20
- [A169](#a169) — What the cull actually let through: three questions out of a hundred and thirty-eight · 2026-09-20
- [A170](#a170) — The register is split: the rules in one file, the record in another · 2026-09-20
- [A171](#a171) — The board is rendered, because five of its rows were wrong · 2026-09-20
- [A172](#a172) — Fifty new clients were run through the system, and what they found · 2026-09-20
- [A173](#a173) — Health takes any number between 0 and 1 · 2026-09-21
- [A174](#a174) — The rename: eigentliCH, in six groups, with one near-miss · 2026-09-21

---

## A1 — Base estate: **both**

Python backend from `andersCH/`, front end from `andersCH-prototype/`.

The spec's stack sentence and its file paths pointed at different estates; the answer is
that each was right about a different layer. The backend keeps the contracts layer, the
seven engines, the FDT event stream and the curator layer. The front end draws on the
prototype's questionnaire and UI work.

**Consequence:** the two estates must not drift. `andersCH/` is imported, not copied.

## A2 — Client: **new, on the 19 Aug SPA's pattern**

Not a fork of any of the six candidates. A new client in `prototype2/`, built on the
architecture of `andersCH/index.html` + `app/` + `surfaces/` — vanilla ES modules, no
build step, content in `data/*.json`.

**What is deliberately not carried over:** the altitude ring, `alt.score`, the
"n of m answered" line, the stage progression, and `altitude` as a data key. Those are
C-07, R-006, R-113 and R-143 violations and the reason the newest client was not adopted
wholesale.

## A3 — Chatbot: **#4's loop, ported to Python**

`apps/anderschapp/app/api/chat/route.ts` is canonical *as a design*: the tool-calling
loop, the Apertus-via-Ollama provider, the master prompt, and the strict-JSON intent
router fallback.

It cannot run where it stands. A1 puts the backend in Python and A2 leaves the client
without a build step, so the loop is **ported into the Python backend**, not adopted as a
Next.js route. This also satisfies C-03: the loop runs server-side, and no model artefact
is reachable from the browser.

**The boundary does not move with it.** Spec §6 forbids C-01 resting on prompt
instructions. A deterministic check runs server-side on the response before
serialisation, in front of the model. `andersCH/client/coach.py`'s `classify()` is the
candidate: it already errs towards refusing and routes to a Curator.

## A4 — Engine IP owners: **superseded by A10**

Originally left unset, because R-300 makes `ip_owner` required and no owner was recorded
anywhere in the estate; §12 makes an invented owner a defect. Answered on 30 August 2026 —
see A10. Kept here rather than deleted, because the fact that this was blank and blocking
is part of why the manifests exist at all.

## A5 — Data classes: **spec §4 wins**

`AssumptionSet` K0 · `Member` K1 · `Position`, `Goal`, `Decision`, `ActionItem` K2 ·
`VaultItem` K3.

This diverges from `architecture/DECISIONS.md`, which has Decision Records at K3 and the
Score at K1. The build spec is the leading document. The divergence is recorded here so
that a reader of the older document is not silently contradicted — the two schemes
describe different systems and both are internally coherent.

## A6 — `Score` name collision: **scope the C-07 grep**

`engines/score/` and the `Score` contract are an analytical household-standing measure —
decomposable, weights summing to one, labelled an editorial judgement. Not gamification.

`test_no_gamification_identifiers_in_model_layer()` therefore covers **the member
application's model layer only**, not the engines or the shared contracts. The test states
its own scope, so a future reader does not mistake the narrowing for an oversight.

## A7 — Decision naming: **rename the existing, take the name**

The estate's `DecisionRecord` (keyed `household_id` + `recommendation_id` + `snapshot_id`,
recording a curator releasing advice) is renamed. The spec's `Decision` (keyed
`member_id`, wrapping every plan mutation, C-09) takes the name outright.

**Cost, accepted:** this touches `contracts/`, the schema emitter, `curator/decide.py` and
every consumer of the old name. It is done rather than deferred because two different
objects sharing one name in one system is the more expensive mistake.

## A8 — Pre-0.1.3 submissions: **archived, not consumed**

The five 0.1.1/0.1.2 submissions moved to `client/submissions/archive/`. The loader reads
only the three `onb@0.1.3` files.

The schema's own rule is that a consumer which does not recognise a version must refuse
rather than guess. Migrating them would mean inventing answers to questions their owners
were never asked, which §12 forbids.

## A9 — Backend stack: **FastAPI + SQLAlchemy + SQLite + Alembic**

The estate carries pydantic and pytest and nothing else; both existing servers are stdlib
`http.server` over JSON/JSONL files.

Chosen because Phase 1 names *migrations* explicitly, and because C-09 requires a plan
mutation and its `Decision` to be **one transaction** — which append-only JSONL files
cannot provide atomically. C-04's `data_class` wants to be a column, and C-10's
append-only audit is enforceable at the database level rather than by convention.

**Cost, accepted:** four dependencies in a repo that had none. SQLite keeps it to a file,
so nothing has to be administered.

## A10 — Engine IP owners: **SIM Research owns all seven**

Declared by Nicolas Bürkler, 30 August 2026, answering the gap A4 recorded. No exceptions
and no per-engine variation: `market_signal`, `return_estimation`, `portfolio_optimiser`,
`life_balance_sheet`, `s_curve_trajectory`, `scenario_generator` and `score_engine` all
carry `"ip_owner": "SIM Research"`.

This unblocks R-300. All seven manifests are written, and `load_manifest` refuses any
engine whose owner is missing or blank — so the field cannot quietly go back to unset.

**The manifests live in `backend/andersch/engines/manifests/`, not in the estate.** §9 says
wrap behind `call_engine` and do not refactor internals, and the estate's engines are not
laid out one-directory-per-engine — `market_signal` is a flat module whose home is
`Macro_Model`. Writing a `manifest.json` into each engine's project would be exactly the
refactor this build is told not to make.

**Two manifests carry a warning in their notes**, because the name alone misleads:

- `portfolio_optimiser` produces a `Recommendation` — ranked instruments. C-01 applies to
  every one of its call sites.
- `score_engine` produces an analytical `Score`, not a game mechanic. This is the collision
  A6 scopes the C-07 grep around, and the manifest is where a reader finds out why it is
  allowed to exist at all.

## A11 — Auth: **email + password, self-hosted**

No third-party identity provider: C-05 makes andersCH sole data controller from the first
intake question, and an external IdP on an authenticated page contradicts that directly.

Email is K1. The password is stored as a modern KDF hash and never logged — the C-04 filter
drops by field name, so the credential field name must be classified, not just avoided by
habit. Reset still needs a mail route, so the SMTP path is a follow-on decision and is
recorded as open rather than assumed.

## A12 — Language: **bilingual from the start, de-CH default**

Every content record carries `de` and `en`. Not a later retrofit: role definitions (D-03),
life-event modules (S-09) and capability statements (R-191) are all *authored* content, and
adding a second language after they are written is a re-authoring rather than a migration.

D-07's "English name for the destination" becomes one key in the content file with both
forms, which is what "all destination copy comes from a single content key" asks for.

R-143's mountain-vocabulary test must run against **both** languages. Berg, Gipfel, Hütte
and Tour are as forbidden in authenticated German strings as summit and climb are in English.

## A13 — Onboarding questions: **rewritten against Position and Goal**

New questions, authored directly against the `Position` / `Goal` model, rather than a
mapping layer over the 78 existing German questions.

**Two consequences, accepted deliberately.**

First, this departs from S-01's "Reuse" note, which asks for a mapping to be *proposed*
rather than a new questionnaire written. The spec's owner chose otherwise; recorded here so
the departure is visible rather than looking like the note was missed.

Second, and the larger one: the `onb@0.1.3` schema's `state` and `params` field names are
the **Life Balance Sheet engine's own**. That is what lets a case be built by reading the
file instead of transcribing an interview. Questions authored against `Position`/`Goal`
no longer land in those names, so feeding the LBS engine will need a reverse mapping that
does not exist today. Engine integration gets harder, not easier — plan for it in phase 2
rather than discovering it there.

**Mitigation:** `onboarding-chat.html`'s question array is extracted verbatim to
`client/reference/questions-onb-0.1.3.json` before any rewriting starts. The wording was
refined across five schema versions and three real interviews; the rewrite should be able
to read it, even where it does not reuse it. Extraction is not adoption.

## A14 — The A7 rename: **now, as its own isolated step**

Done while the parent tree is otherwise clean, with the estate's own test suite as the
check, rather than folded into a later phase. Blocked on the working-tree question below —
see `PHASE-0-SURVEY.md` §8.

## A15 — The 34 orphaned files: **left in git, deletion committed deliberately**

`andersCH-prototype2/` was a tracked directory before it was this build's name. Its 34
files — a Next.js knowledge-tree quest game — are gone from the working tree and are not
coming back to disk. The removal is committed with a message naming **`4220af3`**, so the
content is one `git show` away for anyone who needs it.

Not restored to a sibling path, because keeping an abandoned application on disk to feel
safe about it is how an estate ends up with six client versions and no declared canonical
one. That is the exact problem §9 and D-08 were written about, and it had already happened
once here.

## A16 — The five curricula: **discarded with the game layer**

`capital-saturation`, `hivemind`, `life-os`, `mba-innovation` and `psychological` are the
only authored learning content in the estate, and they are not salvaged.

They were authored *for* the quest layer — typed puzzles, shrines, a scored loop. Lifting
the content out would carry its shape with it, and the shape assumes the mechanic C-07
forbids. Phase 6 authors fresh content against the capability model instead, where
progression is a capability statement a member can read (R-191) and the rung scheme stays
unset until D-01 has an owner.

**Consequence, stated plainly:** phase 6 has no content to start from. That is a real cost
and it was chosen with the alternative visible.

## A17 — The A7 rename, as executed

`DecisionRecord` → **`AdviceRelease`**, committed on `chore/rename-decision-record`
(`33e5019`). The estate's suite is green afterwards: 712 passed, 3 skipped.

**Narrower than A7 implied, deliberately.** A7 said "touches `contracts/`, the schema
emitter, `curator/decide.py` and every consumer". The identifier does. The *concept name*
turned out to be about fifty occurrences of the prose "Decision Record" across thirty
files, and three of those places make renaming it a different kind of change:

- engine internals (`engines/Life_Balance_Sheet/...`, `engines/portfolio_optimiser.py`),
  which §9 forbids refactoring;
- generated HTML surfaces built by `tools/blueprint/`;
- two test assertions that match on the phrase itself.

So the identifier moved and the prose did not. `contracts/advice.py`'s module docstring
now states the split outright, so the next reader does not have to work out whether it is
a rename half-done or a rename with a boundary. Finishing the prose is a follow-on.

**The estate's own `Decision` class is untouched** — a Curator's confirm/override/reject
act, in `contracts.advice`. It collides with the member application's `Decision` by name
only, lives in a different package, and the two meet at one import that can qualify it.
Renaming it would reach into engine projects for nothing.

## A18 — Two findings surfaced by the rename, both left open

**1. A stale emitted schema.** Regenerating the contracts showed
`BalanceSheetSnapshot.schema.json` carrying `policy_cap: default 0.25` while
`contracts/snapshot.py:109` says `1.0`. The schema has not been regenerated since the
initial commit; the code is the source of truth and the artefact drifted from it. This is
material — a policy cap of 1.0 is no cap — so it is **not** bundled into the rename commit
and needs its own decision about which value is intended.

**2. The `.gitignore` protection is uncommitted.** The rule keeping the three real client
submissions out of version control is live in the working tree but not in history. It
works either way, since git reads the working file; committing it is still the right end
state.

## A19 — Role definitions: **sourced from the System Build Manual**

D-03 is discharged. Both sides of the role grid now have definitions from the published
model, in `client/content/roles.json`, marked `provisional: true` as §12 requires.

- **Human capital**, quoted verbatim from the manual's household-model callout: Growth is
  "the activity with the highest leverage on future earning"; Income is "the dependable
  mandate or employment that pays the bills now"; Stabilisation is "smaller, unrelated
  earning streams that reduce the variance of the whole"; Protection is "what keeps a
  person functioning so the other three continue: health, network, the activity not done
  for money".
- **Financial capital**, from the manual's §11.4 rule: "A block rising with the environment
  is Gain; paying in crisis is Protection; peaking in contraction is Stabilisation; paying
  a steady distribution is Income."

**A naming discrepancy, reconciled rather than chosen between.** The manual's canonical
financial-capital role is **`Gain`**, not `Growth`; its glossary says "Any `Growth` label
maps to `Gain` at the boundary". The build spec's §4 enum says `growth`. Both are kept:
`growth` is the stored key, `Gain` is the financial-capital display name, and `Growth` is
the human-capital display name — which is what the manual itself calls it on that side.
A test asserts this so a later tidy-up cannot quietly collapse it.

**German is draft.** Every `de` string was written for this file and none is reviewed. They
carry `de_draft: true`. A12 makes the product bilingual, so shipping without them would
mean shipping a German product with no German definitions.

## A20 — A vacuous test, and the guard added because of it

The R-143 and C-07 copy tests were briefly **unable to fail**. A shell escaping fault turned
the matcher's word-boundary pattern into a literal backspace byte, so it matched nothing —
and both tests passed, because a filter that cannot match and a filter with nothing to
report return the same empty list.

Caught by probing the file rather than trusting the green run. Three things changed:

1. The matcher uses real word boundaries, written through the editor rather than a shell
   heredoc.
2. `test_the_word_filter_actually_matches` asserts known-positives match and
   known-negatives do not — a guard on the guard.
3. The word lists were narrowed to what the constraints actually name. Substring matching
   had been firing on `hut` inside **Schutz** (the German for Protection), `peak` inside
   "peaks in contraction", and `level` inside "leverage". Every one of those would have
   forced worse copy to satisfy a broken filter.

**The general rule this is an instance of:** a blocklist test is green when it is broken.
Any future one gets a self-check in the same commit.

## A21 — German role terms, reviewed

Corrected by Nicolas Bürkler on 30 August 2026. These are no longer my drafts.

| Role | Human capital | Financial capital |
|---|---|---|
| growth | Wachstum | **Wertsteigerung** |
| income | Einkommen | **Einkommen** |
| stabilisation | Stabilisierung | Stabilisierung |
| protection | **Absicherung** | **Absicherung** |

**Absicherung, not Schutz.** Schutz is the dictionary word for protection; Absicherung is the
term of art for the role. This is the correction most likely to be silently undone by a
later pass reaching for the obvious translation, so a test pins all seven strings.

**Einkommen on both sides, overriding the drafting.** I had used different words for the two
capital types to keep them tellable apart. Overruled deliberately: income is income whether
it comes from employment or from a holding, and the capital-type column already distinguishes
them. Recorded because it reverses a distinction the draft was making on purpose.

**Wertsteigerung preserves the Gain/Growth split** that A19 reconciled — Wachstum on the human
side, Wertsteigerung on the financial one, mirroring the manual's own boundary.

## A22 — D-07 resolved: the destination is the spec's own phrase

**"a self-determined life" / "ein selbstbestimmtes Leben"**, in
`client/content/destination.json`, read through `content.destination(language)`.

Promoted from the build spec's §1 prose into the single content key D-07 asks for rather than
coined fresh. A test scans the backend for the phrase as a literal and fails if anything
inlines it, because "one content key" is a claim that decays the moment a template says it
directly.

## A23 — The 78 existing questions, extracted before any rewriting

`client/reference/questions-onb-0.1.3.json` — all 78 at `onb@0.1.3`, every one with its
question text and its `why:` line, 36 conditional, 7 required. Verified UTF-8, no BOM.

**Reference, not content.** Nothing loads it at runtime, and the directory name is the
distinction: `content/` is what the product says, `reference/` is what the product's authors
consult. A13 rewrites the questions; this makes the wording that took five schema versions and
three real interviews readable while that happens.

Each entry keeps its original JavaScript in `raw`, because parsing a JS object literal with
regular expressions is unreliable at the edges. Where `raw` and the parsed fields disagree,
`raw` is authoritative. Regenerate with `python tools/extract_reference_questions.py`.

## A24 — Role grid on a narrow screen: **paired cards per role**

Wide screens get the specification's literal layout: four role rows × two capital columns.
Below 700px each role becomes one card holding both kinds of capital stacked.

**Not a horizontal scroll**, which was the alternative. R-114 and principle 9 say both kinds
of capital are shown together; a column parked off-screen until the member scrolls sideways
is not together, and a phone is where that would bite hardest. NG-07 makes this responsive
web only, so phones are in scope rather than a later concern.

## A25 — The new onboarding questions: **reconsidered, wording reused where it fits**

Not a re-pointing of the existing 78 and not a minimal stub. The target model changed from
the Life Balance Sheet engine's state variables to `Position` and `Goal`, so the question set
follows the model; where a question survives that change, its German wording and its `why:`
line come across intact from `client/reference/questions-onb-0.1.3.json` (A23).

The draft will mark which questions are carried, which are reworded, and which are new, so
the review is a diff rather than a fresh read.

## A26 — Language switching: **a setting, on `Member.locale`**

One toggle in S-14, stored on the column that already exists, applied server-side to every
content lookup. No per-screen switcher: the authenticated product is not the place for chrome
that exists for the twenty seconds a year someone changes their mind about language.

## A27 — Password reset: **deferred until the mail route is named**

A11 chose email and password, self-hosted. Login is buildable now; reset needs a sender, and
C-05's sole-controller position makes that a real decision rather than a library choice. Until
it is taken, the reset endpoint raises "not configured".

Safe to defer precisely because no real member exists yet, so nobody can be locked out. It
stops being safe the day one does — this is the item to settle before any member registers.

## A28 — What phase 2 actually shipped

`GET /api/positions` and `POST /api/positions`, the S-02 client on the vanilla ES-module
pattern with no build step, and the content layer behind R-111.

**C-05 is now a real test rather than an xfail.** `tests/test_client_bundle.py` scans the
served client for cross-origin references, font services, analytics, and `innerHTML`. Checked
statically rather than by driving a browser: a headless run proves *one* page load made no
external request, while a scan proves the source contains nothing that could. For a constraint
about who the data controller is, the second is the stronger claim.

**Two of those tests failed on their first run against my own comments** — `index.html`
explaining that it links to no font service, and `dom.js` documenting that it never uses
`innerHTML`. Both now strip comments before scanning. Same class of fault as A20, caught the
same way: by reading the failure rather than trusting the pass.

## A29 — Correlation tags: **free text, optional**

R-120 requires the five tags be captured; D-02 says store them and ship no inference. Free text in the
member's own words, every one skippable, folded behind a disclosure in S-03 so "optional" looks optional.

A controlled vocabulary would make the eventual comparison rule far easier to write — and choosing the
list would be most of choosing the comparison space, which is deciding D-02 by the back door.

**Known cost:** two members will write "IT" and "Informatik" and nothing yet reconciles them. That is the
price of not pre-deciding, and it is paid deliberately.

## A30 — Magnitude: **optional, and its unit never inferred**

The spec's units are `chf_per_year` and `share_of_total`. A human-capital Growth position — an MBA being
taken, a venture being started — fits neither, so it carries no magnitude and its `time_basis` does the
work. R-020 already makes a position without a magnitude valid; the manual says hours are the binding
constraint on human capital.

`hours_per_week` was NOT added as a third unit. That would have been a change to §4's enum for a case the
existing model already handles.

In the form the unit selector appears only once an amount is typed, so the two cannot get out of step.

## A31 — S-01 question set: **four questions, only the first required**

`employment_position` (required) · `employment_magnitude` · `employment_time_basis` · `first_goal`.
Reviewed 30 August 2026. Two carried verbatim from the original 78, two reworded. Recorded in
`client/content/onboarding-questions.json` with per-question provenance.

**One `why` line was rewritten rather than carried**, and it is worth knowing why. The original read "das
Modell rechnet mit rund 100 verfügbaren Stunden und bestraft Dauerbelastung über etwa 50" — two figures.
Under C-02 those belong in a versioned `AssumptionSet`, not in a question. The replacement makes the same
point without asserting a number whose source the code cannot show.

**The gating question is gone.** `goal_kinds` was a multi-select that decided what the rest of the
questionnaire would ask, and it is what made 78 questions tolerable. Dropped on the claim that the role
grid does that job better — a member adds a cell when ready rather than declaring up front what they will
be asked. That is a claim, not a fact, and it is the largest single departure from the original.

## A32 — Onboarding completion is single-shot

`Member.onboarding_completed_at`, set inside the same transaction that writes the first Position and Goal.
A second attempt returns 409.

**Found by walking the flow, not by a test.** Completing twice produced two identical positions and two
Decisions — and because R-040 makes Decisions append-only, neither could be deleted afterwards. A
double-click was enough to permanently duplicate a member's plan. The state is explicit rather than
inferred from "does a position exist", because the inference is what was wrong.

## A33 — Interpretation runs on the local model, and is checked

Free-text answers are read by **apertus:8b via Ollama on loopback**, proposing a structure the member
confirms. `backend/andersch/llm/` and `backend/andersch/interpret.py`.

**Local is enforced in code, not configured.** A non-loopback host raises `NotLocal`. A member's answer is
K2 the moment they type it, and C-05 makes andersCH sole controller of it — there is no environment
variable that permits a hosted model. The estate reached this first: the prototype's chat route already
carried "Never sends data to a cloud model. No Anthropic path (decision 2026-08-01)".

**Every extracted value is verified against the member's own text.** A year or an amount that does not
appear in what they wrote is discarded outright rather than offered with low confidence. This is C-02's
instinct applied to reading: a number whose source cannot be shown does not enter the system. Swiss
apostrophe and spaced thousands are folded so `250'000` verifies against `250000`.

**It cannot advise.** The model is handed a sentence and asked to segment it. It is never asked a
question, and its output is a typed record with no prose field. C-01's enforcement point is
`/api/know/ask` in phase 4; this surface is not that and must not grow into it.

**It degrades.** No model running means no suggestions and a form that works as before — R-302's rule for
engines, applied here for the same reason.

**The suite does not depend on Ollama.** The model is stubbed in tests; what is tested is the refusal
logic, which is the part a model upgrade could silently break.

## A34 — What "already trained with the books" turned out to mean

Not a fine-tune. Two things, both already built and both reusable:

- **`desktop/bookindex/`** — a **bge-m3** retrieval index (dim 1024) over five sources: the Capital
  Saturation manuscript, The Life Balance Sheet, the Methodik der Standortbestimmung, the Portfolio
  Creation Program, and an AHV rules document quoted from Merkblatt 2.03/3.04. All K0.
- **`Modelfile.apertus-8b-de`** — the Apertus chat template, `num_ctx 8192`, stop tokens, temperature 0.2.

**The Modelfile is already applied.** `apertus:8b` in Ollama carries that exact template and those
parameters — it was built from the file under a different name than the file's own instructions give
(`ollama create apertus-8b-de`). Worth reconciling so a second laptop reproduces what this one runs.

**This corpus is for outputs, not inputs.** Interpreting what a member typed needs no book. The index is
what should ground The Know in phase 4, where `desktop/coach.py`'s K0-only allow-list and refusal boundary
already show the shape.

## A35 — AssumptionSet: **seeded from the estate's own engines**

Not invented and not left empty. `market_signal` (Macro_Model) and `return_estimation` (Fund_Map) produce
a Regime and a ReturnSet that are properties of the world rather than of a household — real, computed,
reproducible, and SIM Research's own. The first AssumptionSet is published from those, stamped with the
`REG-` and `RS-` ids it came from, so every illustration can be traced to a run.

This is the only route that satisfies C-02 and §12 at once: the numbers exist, they have provenance, and
nobody had to make one up.

## A36 — The local model may read K3

R-171 requires The Know's answers to cite the vault items they drew on, which means the model reads member
data — K2 for the plan, K3 for the vault.

Permitted because the model is **local**: Ollama on loopback, no processor, no egress. The estate's
`architecture/DECISIONS.md` says a model reading K1 or above must run inside the core perimeter; loopback
is inside it. `desktop/coach.py` stays K0-only by its own design, and is not the thing being extended.

**Two obligations this creates**, both to be built in phase 4:
- the C-04 logging filter must cover model prompts and completions, or a K3 value reaches a log by a route
  the current filter does not watch;
- C-01's boundary check still runs in code before serialisation. Reading a member's vault does not license
  advising them about it.

## A37 — Working scope: **everything reachable, inventing nothing**

Phases 2 through 8 in the spec's order. Where §12 says a decision is not mine, I state the assumption
explicitly and continue rather than stopping — flagged in this file and in the code, so every one is
findable and reversible.

## A38 — Commits: **one per phase, on a branch off master**

Each phase lands as a single reviewable commit with its reasoning in the message, on its own branch.
Nothing reaches master unreviewed.

## A39 — Engine inputs: **a mapping layer, gaps left visible**

One documented module translating `Position` and `Goal` into each engine's own input names. A13 removed
the direct route the onboarding schema used to give, so the translation is now explicit rather than
implicit — which is arguably better: the mapping is a file someone can read.

**Anything the plan cannot fill is left absent, never defaulted.** A defaulted input is an invented input
one layer down, and it is the failure mode §12 exists to prevent.

## A40 — Curators: **their own table and their own login**

Not a flag on `Member`. Curators are staff; a role flag on a member row is exactly the mistake C-10's audit
table exists to make impossible.

**Correction, 30 August 2026.** This entry originally said `curator_id` "becomes a foreign key rather than
a free string". On `AccessGrant` it is one. **On `CuratorSession` it is not** — it is a plain `String(120)`,
so until today any string could be written into the audit table whose entire purpose is being true. The
claim was false as written and is corrected here rather than left to be discovered. See A67.

**Carried out 31 August 2026 — see A98.** The column is a foreign key on both tables now, so this entry's
original wording is true as written for the first time.

## A41 — Market Place and learning content: **fictional seed data**

Both ship with demonstrable content rather than empty frameworks.

**Three constraints this puts under strain, and how each is held:**
- **C-08** — seeded listings carry no fee field the ranking function can read; the ranking test stays as
  written.
- **NG-04** — no seeded capability, unit or listing may claim federal or accredited status. Asserted by a
  test over the seed data, not by care.
- **Honesty** — every seeded record is marked fictional in the data itself and rendered as such, so a
  screenshot cannot be mistaken for real supply.

## A42 — The eight German role definitions: **reviewed**

Read and signed off by Nicolas Bürkler on 30 August 2026, with three corrections applied:

| | draft | reviewed |
|---|---|---|
| stabilisation / financial | „nicht während ihm" | **„nicht währenddessen"** — the draft was ungrammatical |
| growth / human | „die gemacht wird" | **„die absolviert wird"** — register, for a qualification |
| stabilisation / human | „die Schwankung" | **„die Schwankungen"** — plural |

`de_draft` is now false on all eight and a test pins each correction, because these are precisely the
strings a later pass would "improve" back toward the dictionary.

**One German string remains a draft:** `substitution_note.de`, which was `null` at review time and so had
nothing to review. It is not rendered anywhere. A bulk flag-clear briefly marked it reviewed while it was
still empty; a test now fails on any cleared flag over a missing string.

**`provisional` stays true at the file level.** That flag is D-03's — about the definitions coming from a
published model — and is a separate question from whether the German reads correctly.

## A43 — Password reset is a backend operation, not a mail flow

A27 deferred reset because C-05 made the sender a real decision. Resolved on 30 August 2026 by removing
the dependency instead of choosing a provider: **andersCH runs locally, so the operator has the machine.**

    python -m andersch.reset someone@example.ch     # generates and prints a new password
    python -m andersch.reset --list                 # who is registered

**What this deletes rather than defers.** No SMTP configuration, no reset-token table, no expiry window,
no single-use enforcement, and no "we sent you a link if that address exists" — which is a membership
oracle wearing a politeness. A test asserts no table with `reset` or `token` in its name exists, because
the guarantee is the absence.

**Authenticated by having the machine.** An HTTP reset endpoint would need to authenticate the operator,
which needs another credential, which needs another reset. Anyone who can run this command can already
read `andersch.db`, so a command is the honest boundary rather than a weaker one dressed up.

**The trade, stated:** a member cannot reset unattended. Correct for a locally-run product with an
operator present; it stops being correct the day this is hosted for members who cannot reach one. At that
point a mail route becomes a real decision again — and this is the note that should be found then.

**Around it:** PBKDF2-HMAC-SHA256 from the standard library, 600,000 iterations stored per row so the
count can be raised without invalidating old credentials. Session tokens are stored hashed, so the table
is not a set of live keys. Login does not distinguish a wrong password from an unknown address, and
derives against a throwaway salt when the account is missing so the two take comparable time. Password
rules are length only — composition rules produce shorter, more guessable passwords.

## A44 — The Modelfile naming mismatch, cleared

`Modelfile.apertus-8b-de` said `ollama create apertus-8b-de`, but the model built and used everywhere is
**`apertus:8b`** — verified identical: same template, `num_ctx 8192`, the same three stop tokens,
`temperature 0.2`, Q4_K_M. The estate asks Ollama for `apertus:8b` in 23 places against that file's own.

The create instruction now says `apertus:8b`. A second laptop following the old line would have built a
correctly configured model that nothing could find.

The **filename** keeps its `-de` suffix, because `KNOWLEDGE-TREE-WORKFLOW-PREFLIGHT.md` refers to it by
path. That document is planning for the knowledge-tree application removed under A15 — history, left as
written.

## A45 — Containers (S-04), and the field §4 does not list

`Position.liquidity` was added — bands (`immediate` / `within_months` / `within_years` / `illiquid`),
not numbers. R-031 needs a funding liquidity profile to compare against a goal's date and §4 does not
carry one; §4 also says "field lists are the minimum, not the maximum", so this is an extension rather
than a departure.

**Bands rather than a threshold in years**, because a threshold is an assumption under C-02 and nobody
has published one. A band describes a kind of holding, which is a fact the member can state about their
own position.

**R-031 is answered without inventing a threshold.** The comparison is made only where it needs no number:
a dated goal funded entirely by holdings the member marked *illiquid* is inconsistent with having a date
at all, and an *immediate* holding never is. Everything between is stated as two facts side by side and
left to the member. Where liquidity was not stated, the payload says so rather than guessing — a member
who has not answered is not the same as one who said "immediate".

**Observations carry no severity, no status and no `dismissed` flag**, and a test asserts it. R-031 says a
statement of fact, not a warning to be dismissed; there is nowhere to click "ignore" because the thing
being reported is not an alert.

**No total, no funded percentage, no "on track".** A "72% funded" is the completion meter this product
exists without (R-113, R-006), and a test greps the payload for it.

Courage money is a template with its own name and purpose in both languages (R-132) and **prescribes none
of the five parameters**: what makes it courage money is what it is for, and setting its volatility
tolerance here would be inventing the member's own answer.

## A46 — The System Build Manual is kept current

The Notion manual is updated as the build moves, at the owner's request. A new **Part V — The member
application** was appended on 30 August 2026 (§§28–33), by insertion rather than rewrite: the manual is
3,537 lines of someone else's prose and nothing existing was touched.

**It records where the code has moved away from Parts I–IV**, which is the part that decays silently:

- **Nine `DecisionRecord` references in Parts I–III are now stale** — §15.2, the handover table, and the
  Decision Boundary passages. Deliberately *not* rewritten in place: renaming them is an editorial
  decision on that manual's own prose and belongs to its owner. Part V names them so a reader is not
  misled meanwhile.
- The `Growth`/`Gain` reconciliation, which the manual's glossary already gets right.
- The `policy_cap` drift, which matters for any run made before 30 August 2026.
- The K-class divergence, so a reader of Part I knows the application does not follow it.

## A47 — A deployable distribution, for a naked laptop

Requested 30 August 2026. andersCH must be installable by someone who has a laptop and nothing else — no
Docker, no container runtime, no Python, no build chain, and no appetite for acquiring any of them.

**What ships:** a ZIP containing the application, an install manual that starts from nothing, and a prompt
for Claude Code in VS Code so a friend who gets stuck has something to hand it.

**Constraints this puts on the build, and they are worth keeping anyway:**

- **No container.** The install is Python, a virtual environment, four dependencies, Ollama, and one model.
  Nothing that needs virtualisation enabled in a BIOS or an administrator to install a daemon.
- **No build step in the client.** A2 already chose vanilla ES modules for other reasons; it pays here
  too, because there is no Node, no npm and no bundler to install.
- **SQLite.** A9's choice of a file rather than a server is what makes "unzip and run" possible at all.
- **The model is the heavy part** — roughly 5 GB for apertus:8b — so the manual must set that expectation
  before someone starts, and the application must run without it. It already does: no local model means
  no interpretation suggestions and a form that works exactly as before.

**The install manual has to cover Ollama and Apertus honestly**, including the Modelfile step and the
naming correction from A44 — a friend following the old instruction would build a working model that
nothing could find.

Built after the phases it ships, so that what is distributed is what has passed its gates. Recorded now
because it constrains choices made before then.

## A48 — Vault decisions taken while building phase 3

**Bytes live beside the database, not in it.** A K3 document stored in a row is carried by every
incidental query and every backup. The store is a directory keyed by member and item; the row keeps the
hash. Both the directory and any export are gitignored.

**No deduplication across members.** Two members holding the same document is two documents. A store that
noticed they were identical would be a store that could tell you they both hold it, and that is a fact
about two people that nothing here should be able to answer.

**Unbuilt intake answers 501, not 422.** The member did nothing wrong; the path is undecided under D-04
and not built. A 422 would blame the request for a gap in the product.

**The expiry action item carries no figure.** Its two options state what happens, not what it costs —
a cost would need a published `AssumptionSet` and there is none. A test asserts no digit appears in the
consequences, which is a crude check that happens to be exactly right here.

**The export reflects over columns rather than listing them.** A hand-written field list silently stops
exporting a column added later, which makes an export untrustworthy precisely when someone needs it.

**`verify_round_trip` returns a report rather than raising.** The phase gate is a claim a member should be
able to see checked, not only a test that passed once on a developer's machine.

**One limitation, recorded rather than hidden:** the content hash is recomputed at export and compared
against the stored one. If they disagree the export says so — it does not correct the row and does not
refuse. Silent correction would destroy the evidence that something had gone wrong with the bytes.

## A49 — How C-01 is actually enforced (phase 4)

> **WITHDRAWN 20 September 2026.** How C-01 was enforced in phase 4. The enforcement described here no longer exists. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

The specification says the check "must not be a prompt instruction alone — a model that ignores its
instructions has to be caught by code". So:

**`boundary.py` imports no model, and a test asserts it.** It is a classifier over the question and a scan
over the answer. Both run whatever the model was told. A model cannot be its own gate, so the gate is not
made of model. 59 boundary tests plus 15 Know tests pass with nothing installed — that is what "provably
not by prompt alone" means.

**Both sides of the model, not one.** A question asking what to do never reaches it (`model=None` in the
response proves the call did not happen). An answer that ranks or recommends never reaches the member.
The second half is the half a prompt cannot provide, and it is the one that catches the real failure.

**It errs towards refusing, and that has a cost worth measuring.** Ambiguity resolves to refusal because a
question misread as education and answered is a regulatory breach, while one misread as advice and refused
is an inconvenience. So there is a second test set of ten real education questions asserting they get
through — a boundary that refuses everything is a wall, and the fix for that belongs here rather than in
the copy.

**Two shapes are caught, not one.** "Soll ich" is the obvious one. The other is an instrument named
together with a sum — that shape survives rephrasing into a question that contains no modal verb at all.

**The model is handed retrieved passages, never the vault.** There is no parameter through which the whole
vault could travel. Same guarantee `desktop/coach.py` gets from having no household parameter: a model
cannot disclose what it was never given. A test asserts the member id never appears in a prompt.

**A36's obligation is discharged.** Nothing in `services/know.py` logs a prompt, a completion or a
retrieved passage — the C-04 filter drops K3 by field name, and a prompt is a paragraph rather than a
field. One test runs a real question and asserts the vault text appears in no log record; another greps
the module, so a logger added later has to justify itself.

**Retrieval is crude and inspectable on purpose.** Term overlap, capped at six passages. A black-box
retrieval that grounds an answer in the wrong document is worse than a simple one whose reasoning can be
seen — the estate reached the same conclusion for its branch matcher. The book corpus (A34) is the better
ground for general questions and is not wired yet.

**Verified live against apertus:8b**, not only against stubs: an education question answered from the
member's own vault with a citation; "Soll ich mein Freizügigkeitskonto auflösen?" refused with the model
never called; and a cost question answered with "Es gibt keine Kostenangabe in den Auszügen" rather than
an invented figure.

## A50 — The age floor is 18, not 25

Lowered on 30 August 2026 at the owner's instruction, so that andersCH can serve younger people.

**Moved rather than removed.** NG-05 set 25 and gave its reason as "no minor-consent flows". 18 is the age
at which that reason stops applying: everyone admitted is an adult in Swiss law, so NG-05's actual promise
is kept while its number is not. Removing the floor entirely would have admitted children into a product
with no consent handling — the specific thing NG-05 was written to prevent.

**Swiss apprentices were the case for going lower**, and it was considered: Lehrlinge earn from about 16
and are exactly the audience a financial-capability product wants. It was declined for now because under
18 makes parental or guardian consent a real requirement rather than a config change, and those flows do
not exist. `test_the_floor_is_at_or_above_adulthood` is the tripwire on lowering it further without
building them.

**The tests now assert the mechanism, not the number.** They were written against a literal 24 and 25;
they read `MINIMUM_AGE - 1` and `MINIMUM_AGE`, because the floor has moved once and R-100 is about the
refusal being server-side rather than about any particular age.

**The downgrade migration is deliberately unguarded.** It raises if a member aged 18-24 exists by then.
Restoring the old floor is a policy reversal, and what happens to the people it would exclude is a
decision — not something a migration should make quietly on its own.

The member-facing copy is now "Ab 18 Jahren." rather than "andersCH führt Konten ab 25 Jahren", which read
as a rejection notice on a welcome screen.

## A51 — The design system is the live site's, verbatim

`client/style/tokens.css` now carries the `:root` of andersch.sim-research.ch — the ink ramp, the line and
surface colours, the five gradient stops, both gradients, the spacing scale, the radii and the font stack.
Copied rather than interpreted, with `client/reference/andersch-site-styles.css` kept as the source, so the
member application and the public site are demonstrably one brand rather than two that resemble each other.

**What is not copied is the exuberance.** Principle 10 puts flourish in the marketing surfaces and
plainness in the product. The gradient — the brand's signature device — appears exactly once, on the
wordmark, where it is identity rather than decoration and touches no data a member entered. No hover lift,
no fade-in, no backdrop blur.

**Two additions the marketing site never needed**, both derived from the palette rather than borrowed from
a generic kit: an attention hue and a refusal hue. A marketing site states things; this product refuses
them, and a refusal a member cannot tell apart from a hint is a bad refusal. A signal red would have been
the only saturated non-brand colour in the application.

**One accessibility split, made from the palette itself.** `--primary` is 4.47:1 on white — right for the
rules and focus rings the site uses it for, under the 4.5:1 floor for small text. `--ink-soft` is the same
violet at 7.5:1, so words that want to be purple use one token and lines that want to be purple use the
other. Nothing invented.

**Dark mode was dropped, not half-derived.** The live site is light-only and three of its colours are
translucent purples that mean nothing over a dark ground; the parts that resist mechanical inversion are
precisely the ones carrying the brand. `color-scheme: light` is declared, so a browser in dark mode does
not paint its own dark form controls into a light page — that half-working state being the thing worth
avoiding.

## A52 — Phase 6 shipped as learning, and one file was renamed

S-10 is built: six units, ten capability statements, three named exits (R-193), all bilingual, every
record marked fictional per A41, and `rung` null on every capability because D-01 is not mine to decide.

**`services/knowledge.py` was renamed to `services/learning.py`.** It had landed one letter from
`services/know.py` (S-08, The Know), which is a genuine trap in a directory listing for two things that
are not related. S-10 is the learning path; the name now says so.

**Three places where the build pressed toward deciding D-01, and what happened instead:**
- Prerequisites wanted to become a gate (`locked`, `available`, `met`). Whether evidence of a
  prerequisite's capabilities *constitutes* having met it is the assessment question D-01 owns. The
  payload reports `capabilities_without_evidence` — a fact — and states `units_are_not_gated`.
- File order wanted to be a ladder. Capabilities return in file order because they must return in some
  order, and the payload says `capabilities_are_unordered` so a client cannot read the sequence as rank.
- An HTTP verb for recording an assessment. `record_assertion` exists in the service and is deliberately
  not exposed: a POST is a decision about how a capability is assessed whether or not it is called one.

**`fictional: true` lives in the content file, not on the row**, and `seed()` raises on any record lacking
it — which makes the marker load-bearing rather than decorative. Putting it on the row is a column and a
migration, and is the better home if the seed data ever grows.

## A53 — Demonstration accounts, and why their passwords may be written down

`tools/seed_demo_accounts.py` creates one member and one curator, and their credentials are documented on
the andersCH System Engine page in Notion so someone installing this on their own laptop can get in.

**Writing a password into a shared document is normally wrong.** It is acceptable here only because three
things are true at once, and the script's docstring names them so the reasoning survives:

1. the database is local, created by the installer, and holds no real member's material;
2. every account created this way is marked `fictional` in the data — so a demonstration curator can never
   be mistaken for a real one in an audit table whose whole purpose is recording who did something;
3. nothing here is reused as a production credential.

**The third stops being automatic the day a real member registers.** That is the trigger to remove the
table from Notion, and it is written on the page itself rather than only here — a warning that lives only
in the repository is a warning the person reading the wiki never sees.

**The passwords are long and readable rather than random**, deliberately. They are typed by hand from a
page onto someone else's laptop; a 24-character random string in that path gets pasted wrong, written on
paper, or replaced with something worse. Length is the property that matters and they protect nothing real.

**Curator hashing is written out in the seed script rather than imported.** A40 keeps the tables apart, not
the algorithm — but importing the curator service's helper would let seeding diverge silently if that
service changes. Two independent implementations of the same standard KDF is the cheaper failure.

## A54 — A finding that bears on the age floor

The System Engine page carries **"andersCH Persona Framework — Swiss Fintech Users 16–60"**. The product's
own persona work already starts at 16, which is four years below where A50 put the floor and two below
adulthood.

Not acted on: reaching 16 makes parental or guardian consent a real requirement and those flows do not
exist. Recorded because it means the 18 floor is a *staging post* rather than a settled position, and
whoever picks this up should know the product's own audience definition disagrees with its current gate.
`test_the_floor_is_at_or_above_adulthood` is what makes the gap fail loudly rather than drift.

## A55 — The persona framework narrowed to 18–60, and Lea aged up

A54 reported that the product's own persona work started at 16 while the gate sat at 18. Resolved on
30 August 2026 by narrowing the personas rather than lowering the gate.

Changed in Notion: the framework title, "five age cohorts covering Swiss fintech users 18–60", Cohort 1
now "18–24", both out-of-scope notes, and the companion page's title.

**Lea was aged from 17 to 18, not dropped.** She is Cohort 1's deliberate stress case — first-year
apprentice hairdresser in Renens, CHF 650 a month, lives at home, Portuguese-Swiss, French region — and
the framework's own principle is that "if a screen works for both her and Timo, it works for the cohort as
a whole". Dropping her would have removed the immigrant-background, French-region, lives-at-home and
near-zero-savings combination that nothing else in the roster carries, and left the cohort's young edge
undefended. An 18-year-old at the start of a VET apprenticeship is entirely ordinary.

One consequential edit inside her record: her triggers listed "age-18 first tax filing" as something
ahead of her. At 18 it is current, so it now reads "her first tax filing".

**A tension this surfaced and did not resolve.** The framework's design implications include "the
gamification layer must be optional (metaphor / minimal / off)" and describe Timo and Lea engaging with a
hiker figure. C-07 forbids gamification primitives outright and R-143 forbids mountain vocabulary in the
authenticated product. The persona document is marketing-side research and was left as written, but the
two documents disagree, and the specification wins where the product is concerned.

## A56 — One demonstration account per persona, each with its own password

Replaced the single shared demo login. Ten member accounts — Lea 18, Timo 23, Elena 26, Lukas 29, Marc 35,
Céline 43, Yasmin 46, Regina 53, Roland 55, Beatrice 58 — plus the curator.

**Two reasons, and the second is the one that matters.** A shared login means everyone exploring writes
into the same plan, and a role grid four people have poked at demonstrates nothing. And a shared password
teaches the wrong habit about a product whose whole posture is that one member's material is theirs: the
credential model already gives every member their own, and seeding should not be the one place that
pretends otherwise.

Ages are the personas' own, so the roster also exercises the age floor at its edge — Lea at exactly 18.
Kurt (68) and Lena (14) are out of scope in the framework itself and are not seeded.

## A57 — A timezone bug that would have crashed every real login

Found by the phase 5 agent in `AccessGrant.is_live()`, and it reported that `Session.active` had the
identical shape. Verified by reproduction before acting: it does.

**`DateTime(timezone=True)` is a promise SQLite cannot keep.** It stores the instant and drops the offset,
so a row written with an aware datetime returns naive. `self.expires_at > utcnow()` then raises

    TypeError: can't compare offset-naive and offset-aware datetimes

**Why a 450-test suite did not catch it.** It only fires when the row is loaded from disk rather than
served from the session's identity map. Tests use one session, and `expire_on_commit=False` keeps objects
aware in memory. Under FastAPI, which opens a session per request, it would have fired on the first real
login — and as a `TypeError` on a read path, so it would have read as a bug rather than as a refusal.

**Fixed at the boundary, not at the comparison.** A `DateTime` `TypeDecorator` in `models/base.py` coerces
on bind and on result, and every model now imports it instead of SQLAlchemy's. Fixing `is_live()` alone
would have left `Session.active` broken — which is precisely what had already happened, twice, in two
files written days apart. A naive value arriving at bind time is assumed UTC rather than local: the
alternative silently shifts an instant by the machine's offset, which is a worse wrong than an obvious one.

A test asserts no model column uses the raw type, so the next datetime column cannot reintroduce it.

**What this says about the agents.** The phase 5 agent could have fixed only its own path and moved on; it
reported the second occurrence in a file it had been told not to touch. That is the behaviour worth having
from parallel work — and the reason the report was worth verifying rather than trusting was that it turned
out to be worse than described.

## A58 — Phases 7 and 8, and the client surfaces

Built in parallel and verified independently rather than on report. **622 passed, 3 xfailed.**

**Phase 7, Market Place.** C-08 is made provable in both halves the specification asks for: `ordering_key`
is handed three integers and an opaque row id — no listing, no provider, no session, so there is no fee in
scope and no way to fetch one without changing the signature. Structurally, an AST scan over the four
ordering functions rejects any reference to `Provider`, a billing field, or a fee name reached by
`getattr`. Behaviourally, a fee is put on the bottom listing's provider, then the opposite arrangement,
and the order is asserted unchanged both times — plus the order a fee-reading ranking *would* have
produced is computed and asserted different, so "unchanged" is a result rather than an arithmetic accident.

**Phase 8.** R-141 is held by an *absent parameter*: `stage()` takes no age, so an 18-year-old opens the
stage marked 50 and the payloads are byte-identical. R-142 raises at load on any stage after 50. R-183's
seven life-event modules are genuinely empty — no title, no curator role, not even the `vault_kinds`,
because "which documents to retrieve" is one of R-180's four authored fields rather than a technical
mapping. Verified: no prose anywhere in that file.

**The client.** The Know is mounted once onto `document.body` outside the router, so `route()` clearing
`#main` never touches it — persistent (R-002) without becoming the fourth tab that would have been the
obvious wrong answer.

## A59 — Three defects the parallel work surfaced, all real

**1. A stale relationship would have refused a legitimate publish.** `publish` read `listing.disclosures`
— a cached collection. A first, refused publish loads it empty; because sessions are created with
`expire_on_commit=False`, adding a disclosure afterwards does not expire it; the second publish still sees
zero. That is the exact sequence an applicant follows. It appeared as an order-dependent test failure and
was a production bug underneath. Now counted with a query.

**2. Nothing created an ActionItem.** `action_item_for_expiry` was called only from tests, so
`/api/actions` was empty in the running application forever and R-152 — "expiry dates are the primary
source of action items" — was satisfied on paper only. Found by the agent building the panel that lists
them and finding nothing to list. `store_item` now raises one, with no horizon threshold: "within how many
months is an expiry worth surfacing" is an assumption nobody has published, and ordering by due date needs
no such number. A superseded document's item is filtered at read time rather than by mutating its status,
because marking it `acted` would assert the member renewed when they may have uploaded a better scan.

**3. A docstring of mine was wrong.** `models/marketplace.py` claimed the CHECK constraint kept
`registration_refs` empty under the capability pipeline. It does not — it ties domain to pipeline and
nothing else. Saying so was worse than saying nothing, because a reader trusting it would have skipped the
check that matters. Corrected, with the real enforcement point named.

## A60 — Elio: documented like the others, but good for one login

Decided by the owner on 30 August 2026 after the alternative was put: a real person's name beside a
password in a shared document is a different thing from a fictional persona's, and the five submissions
are treated as real everywhere else in this build — the `.gitignore` and the A46 survey redaction both
say so.

Implemented in the least-exposed way consistent with that decision: the account carries `must_change`, so
the documented password works exactly once and stops working the moment he chooses his own. The full cycle
is verified — first login, change, old password dead.

**The account does not read the submission.** They are separate things: one is a login, the other is data.
The age in the seed file is a placeholder that clears the floor and is not a fact about anyone. When the
auto-mode classifier blocked an attempt to read his canton, civil status and employment out of the
submission to populate the account, that was the correct outcome and it was not worked around.

## A61 — R-231's erasure: null the reference, and empty the fields that hold the person

Decided by the owner on 30 August 2026, after the alternative was put: erase now by nulling the member
reference on the records that cannot be deleted, rather than deferring until a retention policy exists.

**Carried through the fields that actually hold the person.** `Decision` carries `question`, `choice` and
`reasoning` — free text about the member's plan. Nulling only `member_id` would leave that prose in the
table, unattached and perfectly readable, which is the version of this that looks compliant and is not. A
redacted Decision keeps its id, its timestamps and its author kind, and nothing else. That is the
instruction carried out, not softened.

**A test sweeps every table for the member's own words** after an erasure — their employer, their goal
name, their document title, their reasoning, their email. That is the claim being made to a person about
their data, so it is asserted rather than described.

**The curator audit keeps what a curator did.** Only the member reference is nulled there; the actor, the
kind and the time stay. An audit that erased itself whenever a member left would not be an audit.

**Two narrow exceptions, both named rather than hidden:**
- The append-only triggers are dropped and re-created around the redaction, inside the caller's
  transaction, with the restore in a `finally`. A test asserts a Decision is immutable again immediately
  afterwards, which is the proof the exception was narrow.
- The C-09 guard stands down, via an explicit `ERASING` marker on the session that only this module sets.
  Removing a plan is not a change to one, and the Decision recording the *request* is written before the
  erasure begins — so a crash between them leaves a request without an erasure rather than the reverse.

**Found while building it:** association rows have to be cleared before the rows they point at, or the
delete fails on a foreign key. Obvious in hindsight; not obvious until SQLite said so.

## A62 — The curators are five named people

> **Superseded in part on 20 September 2026 (A161).** Three of the five below — the compliance reviewer,
> the GTM lead and a curator — are no longer part of andersCH. Their accounts were revoked on that date,
> not deleted, because the audit table has to be able to resolve who did something. **The live list is
> Nicolas and Nicolai.** The rest of this entry is left as it was written, because it records what was
> decided on 30 August 2026 and that did not change retrospectively.
>
> The three are named by role here and throughout, on the owner's ruling of the same date — see A160.

Nicolas, Nicolai and three colleagues since departed, named by the owner on 30 August 2026. Each gets a
password good for **one login** — the same treatment as Elio and Yasmin T., and for the same reason:
these are real people, not personas.

**They are not marked `fictional`.** The demonstration curator is; these are not. C-10's audit table
exists to say who did something, and a real curator flagged as fictional would make every record they
touch ambiguous.

**Their addresses are in their own namespace** — `@kurator.andersch.local` rather than
`@andersch.local` — so an address can never be ambiguous about which table it belongs to. A40 keeps
curators and members in separate tables; separate namespaces keep that visible at a glance.

**One of the five shares a given name with a real submission.** As far as this system is concerned they
are different people: a curator is a row in `curators`, a submission is data in `client/submissions/`,
and nothing joins them. Worth knowing before someone assumes otherwise — the same collision as the two
Yasmins, and handled the same way, by being written down. *(Closed on 20 September 2026: that curator was
revoked by A161 and that member was given a pseudonym by A162, so the two no longer share anything. The
note stays because the hazard was real while it lasted.)*

**One thing the seeding caught about itself.** It printed "good for one login" beside a curator's password
while `Curator` had no `must_change` field and nothing enforced it. A false statement on an operator's
terminal is worse than no statement, so the field was added rather than the wording removed.

## A63 — A migration silently switched off an append-only trigger

`batch_alter_table` on `decisions` (the A61 migration making `member_id` nullable) **dropped
`trg_decisions_no_update` and `trg_decisions_no_delete`.** SQLite cannot alter a column in place, so batch
mode copies the rows into a new table and renames it — and everything attached to the old table goes with
it, triggers included.

**Nothing failed.** The `before_flush` guard in `db.py` still held, so the ORM path was still protected and
634 tests stayed green while raw SQL could have rewritten a Decision. It was visible only as a trigger
count on a migrated database, which is a thing nobody looks at.

Fixed in the migration, in both directions, and two tests now hold it: one asserts all four triggers exist
after migrating from nothing, the other checks the development database the desktop icon actually opens.

**The general lesson, worth carrying:** every constraint in this build has two enforcement points — an ORM
guard and a storage-level one — precisely so that one failing is not silent. This is the first time the
second one failed, and it proved the design right and the monitoring wrong. A guarantee nobody counts is a
guarantee nobody notices losing.

## A64 — Routers wired, and a test that was right becoming wrong

The four phase routers are now included in `api/main.py`. They were written as separate routers so four
phases could be built in parallel without colliding in one file; wiring them is the step that ends that
arrangement.

`test_the_router_does_not_touch_main` asserted that `main.py` never mentioned the curator router. That was
correct while the phases were being written concurrently and wrong the moment they were joined. Rewritten
to assert what it was actually protecting: that the routes are DEFINED in the phase's own file and not in
`main.py`. The test kept its purpose and lost its literal.

**One diagnostic worth recording, because it cost time.** FastAPI 0.141 / Starlette 1.6 nest an included
router under a single `_IncludedRouter` entry rather than flattening its routes into `app.routes`. Every
inspection of `app.routes` therefore reported the routers as missing while they were working perfectly.
The only trustworthy check is a request. Two hundred lines of correct diagnosis of a non-problem.

## A65 — The desktop app reports the real state

`/api/health` said phase 4 and the status page said phase 1, long after both were untrue. Both now report
all eight phases, the eighteen constraints that are enforced and by what mechanism, and the six things
still open — including the three `D-` decisions that are not ours to make.

A status page that lags the build is worse than none: it is the one surface whose entire job is being
accurate about what exists.

**Also found here:** a server left running from earlier was still serving the old code on port 8420, and
the launcher's "already running, opening it rather than starting a second copy" behaviour — added in A47's
work as a convenience — meant a restart silently did nothing. Correct behaviour, confusing consequence.
Worth knowing when a change does not seem to take effect.

## A66 — Erasure left the database with no append-only triggers at all

Found by erasing one account on the development database and counting: **zero triggers afterwards**, where
there should have been four.

**The cause.** Erasure drops the triggers, redacts, and re-creates them. The re-creation went through
`install_append_only_triggers(engine)`, which opens its **own** transaction via `engine.begin()`. So the
CREATEs committed on a second connection while the DROPs were still uncommitted on the session's — and
when the session committed, the drops landed last. Every append-only guarantee in the system, silently off,
as a side effect of a member exercising their right to be forgotten.

**Why the test that was written to catch exactly this did not.** It used `sqlite:///:memory:`, where every
connection gets its own separate database. The second connection created triggers in a database that was
not the one under test, and the test read them back from a third. It passed while the real path destroyed
them. **A test on the wrong substrate is worse than no test, because it is believed.** It now runs against
a file, and planting the bug back makes it fail — checked, not assumed.

**The fix.** `append_only_trigger_statements()` is separated from `install_append_only_triggers()`, so code
already inside a transaction runs them on its own connection. The install helper stays for setup and
migrations, which are not in one.

**This is the third time in this build that a guarantee stopped holding while the suite stayed green** —
after A20's word filter that could not match and A63's migration that dropped the same triggers. All three
were absence-shaped: nothing failed, because the thing that should have complained had itself stopped
working. The pattern is now explicit enough to name: *a test that asserts something is absent must be
proven able to detect its presence.*

## A67 — The curator directory, and a hole it exposed

`GET /api/curators` lists the five real curators — id, display name, role label, and nothing else. No
email, no password state, no member linkage, no count. Unauthenticated on purpose: it says nothing about
any member, and R-170 needs the button able to name someone. An empty directory returns `200` with an
empty list rather than an error, because a client that got an error would be entitled to hide the button.

**The demo curator is listed by nobody and resolvable by everybody.** She is omitted from the directory —
a member who picked her would open a real audit row about a consultation nobody will hold — but
`resolve_curator` still finds her, because she *is* a row and a session naming her is true. Listing her
with a "demo" mark was rejected: a tag like that beside real colleagues reads as a verdict on a person
rather than a fact about a seeded account.

**The hole it exposed.** `POST /api/curator/sessions` took `curator_id` on the caller's word. Combined
with `CuratorSession.curator_id` being a plain string rather than a foreign key, an invented curator would
have been written into an append-only table and nothing at any layer would have caught it. That route now
resolves the id first and writes the resolved row's, so `"unassigned"`, `""` and a plausible-looking
`"curator:nb"` are all refused — for one reason, *there is no such row*, which needs no list of
placeholder words to keep current.

**Still outstanding, and stated plainly: `CuratorSession.curator_id` should be a foreign key.** The HTTP
surface is closed, but the service layer would still accept an invented id. Making it a real constraint
means a migration, cleaning three rows in the development database, and updating six test files that use
placeholder ids — three of which belong to agents running as this is written. Doing it while they read
those files would be reckless, so it is the next thing after they land rather than a thing left undone.

**Done 31 August 2026, in A98.** It took a migration, a pragma in `env.py`, three corrected rows in the
development database and four test files — two of the six named above already used real ids.

**One artefact accepted:** exercising the live route wrote a real `curator_sessions` row into the
development database. Its `opened` event sits in an append-only table that refuses DELETE, so removing the
parent would be worse than keeping a demonstration row. Left, and noted.


## A68 — A63 was never fixed, and the test that guarded it had never run a migration

*Owner: Nicolas · 2026-08-30 · cost: one line of source, two rewritten tests*

An adversarial audit was asked to break every constraint the build claims to enforce. Its first finding
was that **A63 was not fixed**. A database built by `alembic upgrade head` had exactly two triggers —
both on `curator_session_events`. `trg_decisions_no_update` and `trg_decisions_no_delete` were absent, so
`UPDATE decisions SET choice = '...'` succeeded on any real deployment. R-040, the guarantee that a
recorded decision survives a change of adviser, was off.

The cause is the same mistake as A66, one file over. Migration `ee959786d912` — *the migration written to
fix A63* — calls `install_append_only_triggers(op.get_bind().engine)`. Reaching for `.engine` opens a
**second connection outside the migration's transaction**. That connection still saw the pre-swap
`decisions` table with its triggers attached, so `CREATE TRIGGER IF NOT EXISTS` did nothing at all; the
batch swap then committed and took the real triggers with it. `db.py`'s own docstring warns about exactly
this, three lines above the helper that exists to prevent it. It re-creates them on `op.get_bind()` now.

**Why nothing went red for a week.** `create_all` installs the triggers directly, and `create_all` is what
the test suite and the development database both use. Only the migrated path — the one every deployment
takes and no test took — showed it.

**The test that existed to prevent precisely this was vacuous.** It pointed alembic at a temporary
database by setting `ANDERSCH_DB_URL` in a subprocess environment. Nothing reads that variable: not
`migrations/env.py`, not `alembic.ini`, not `db.py`. So the temporary file was never created, a fallback
branch ran `create_all()` followed by `install_append_only_triggers()`, and the test asserted that the
triggers it had itself just installed by hand were installed. It had never once run a migration. As a side
effect, every test run migrated the developer's real `backend/andersch.db`.

It now drives alembic through its Python API with the url set on the object that actually reads it, and
there is no branch that can quietly substitute `create_all`. A second test writes a Decision through raw
SQL and requires both verbs to be refused — because presence is not the property that matters, refusal is.
Both were verified by re-planting the original bug, watching them fail, and restoring the fix.

**This is the fourth absence-shaped guarantee to stop holding while the suite stayed green** (A20, A63,
A66, and now A63 again). The practice A66 stated is not optional and was not followed here: *a test that
asserts something is absent must be proven able to detect its presence.* A63's fix was accompanied by a
test that could not fail, which is why the fix being wrong cost a week rather than a minute.


## A69 — The engines run in their own interpreter, and C-02 has a published set

*Owner: Nicolas · 2026-08-30 · cost: a stdio bridge, one builder per engine, one published AssumptionSet*

All seven engines were surveyed before anything was wired, per R-305, and all seven are healthy — every
venv present, every CLI responding, every one returning a schema-valid contract. The July 2026 move left
`engines/` intact.

**Why a bridge and not an import.** prototype2's venv cannot import `contracts`/`orchestration`, and the
four wrapped engines each need a third venv again. `call_engine` therefore runs the estate under *its own*
interpreter over JSON on stdio — §7's "one subprocess per engine, its own venv" applied one level further
out. Nothing was added to the estate (§9): the bridge is a string, not a file. One call round-trips in
about 185 ms.

**C-02 is satisfied by a real set, not a placeholder.** `2024-12-31+REG-38d91c1a+RS-874b03c9`, derived
from a named Regime and ReturnSet, with both run ids and their replay commands copied in verbatim.
`effective_from` is the data vintage, not the day it was read.

**Two things were deliberately not written.** `inflation` is NULL — the string does not occur in either
source artefact, which is a finding rather than an omission. And no blended expected return is published:
the role profiles and the house-view probabilities sit side by side and nothing multiplies them, because
which probabilities weight which horizon is a decision with an owner. A test forbids a composed rate
appearing later.

Twenty-one inputs across the seven engines are recorded as *absent* rather than defaulted, each carrying
one of four kinds. The temptations worth naming: capitalising a `chf_per_year` flow into a wealth stock
needs a discount rate (a C-02 assumption); synthesising a mandate from a Goal's parameters would invent an
investment policy and then optimise against it, crossing C-01 twice; and `months_observed` was computable
from the earliest position start, which is not the same quantity the engine weights at 35 %.

**Carried, not fixed:** the estate's `ENGINE_HOMES` maps the three native engines to `Master_Model`, a
directory that does not exist. `NativeEngineAdapter.home` overrides it, so it is cosmetic — and it lives in
the estate, which §9 puts out of scope for this build. Noted so the next reader does not go looking for the
directory. Separately, the estate's `ReturnSet` calls the first role **`gain`** where §4 and
`models.plan.ROLES` call it **`growth`**. Recorded rather than silently renamed; nothing in prototype2
currently maps between the two vocabularies, and whatever does so first must do it explicitly.

## A70 — The accessibility pass, and a CSS rule that was deleting data

*Owner: Nicolas · 2026-08-30 · cost: two new tokens, 56 tests*

**The worst finding was not a contrast ratio.** A media query hid `.cell-capital` on every screen wider
than 700px, treating it as a repeated column header. But `vault.js` and `containers.js` reuse
`.role-row`/`.cell-capital` as a one-column card, where that span is *the only place* the vault item's kind
and the goal's template name appear. Desktop users were silently losing real content. Now scoped so the
grid's rows and those cards are separated without a class the JavaScript would have to add.

Second: `grid-template-columns: 170px 1fr 1fr` with `overflow: hidden`. A `1fr` track will not shrink below
min-content, so "Erwerbsunfähigkeitsversicherung" widened the track, the row overflowed, and the clip
removed the text **with no scrollbar and no ellipsis — the sentence simply stopped.** `minmax(0, 1fr)`,
`min-width: 0`, and wrapping.

**Contrast was fixed by extending the palette's own split, not by inventing colours.** `--ink-mute` carried
essentially every secondary word in the client at 4.06:1 on a card and 3.72:1 on the tinted page — failing
on both. It keeps the live site's value and its name; `--ink-quiet` is the same hue and saturation at lower
lightness, giving 5.37:1 and 4.92:1. `--control-line` does the same for boundaries, where 1.4.11's 3:1
applies. Input borders had been 1.21:1, and hovering a field made its edge *fainter* than at rest.

The ratios were recomputed independently before this was accepted, with the contrast function itself pinned
against WCAG's published reference pairs first — per A20, a measurement you cannot verify is not a
measurement. The operator page at `client/status.html` was missed by that pass (it is not part of the
member bundle) and was fixed afterwards: its table headers were 10px uppercase at 3.72:1.

**Known and not fixed, because it needs JavaScript:** the chrome is monolingually German. The three door
labels and the skip link are hardcoded in `index.html` and `main.js` retranslates neither, so an English
member keeps a German header — A12's gap, now with a precise location. `.notice.error` has no
`role="alert"`, so a refusal appearing after submit is never announced.


## A71 — C-04's filter was installed and inert in the running server

*Owner: Nicolas · 2026-08-30 · cost: a handler sweep, one patched method, a lifespan hook*

`install_log_filter()` ran at import, on the root logger, which at that moment has **no handlers**. It
attached the filter to the logger and to `target.handlers` — an empty list. Uvicorn adds its handlers
afterwards, and a filter attached at *logger* level does not run for records that arrive by propagation
from an `andersch.*` child. So in the real server a K3 field name travelled to the handler unredacted,
which is the one thing C-04 exists to prevent.

The constraint test built its own filter instance and attached it by hand, so it never exercised
`install()` at all. That is why it was green.

Three mechanisms, all needed. The filter attaches to **handlers**, not loggers — a handler filter runs for
every record the handler emits, propagated or not, and that is the load-bearing change. `install()` sweeps
the handlers that already exist, **including `logging.lastResort`**: uvicorn's `LOGGING_CONFIG` configures
only the `uvicorn*` loggers and leaves root with none, so an `andersch.*` warning in the real server is
emitted by `lastResort`, which a sweep of `logger.handlers` would never reach. And `Logger.addHandler` is
patched once so handlers added later are covered — the single funnel that `dictConfig`, `basicConfig`,
uvicorn and pytest's `caplog` all pass through.

Verified against a real uvicorn started the way the desktop icon starts it, in the order the server
actually uses: import the app first, let uvicorn configure logging second. A vault title now comes out as
`title=[K3 redacted]`.

That run exposed a second, older bug: the marker was emitted as `[K3 redacted]]`, because the rendered-text
pattern stops a value at `]` and so re-matched its own output. Harmless while the filter ran once; now that
it can run more than once per record it would compound. `_scrub_text` is idempotent and a test pins the
exact string.

**One named form is not caught, and the docstring now says so instead of claiming otherwise.** A filter is
never handed the traceback, so `logger.exception()` on an exception whose message contains `title=<value>`
still emits it. The docstring used to call the forms it handles "the full range of ways a field name
travels with its value". They are not, and it now says that in those words. The test stays
`xfail(strict=True)` — a real open hole, recorded rather than closed by assertion.

## A72 — C-09 held for the ORM and not for the Session

*Owner: Nicolas · 2026-08-30 · cost: one `before_execute` listener, a flush bracket, a token*

`before_flush` sees the ORM unit of work and nothing else. `positions` and `goals` carry no trigger, so
that guard was the only thing enforcing "every plan change produces a Decision" — and three ordinary calls
walked past it: `session.execute(insert(...))`, `session.execute(update(...))` (R-123's exact case), and
`bulk_save_objects`, which is an ORM call, not raw SQL. The module docstring claimed the guard "has to hold
for code that never heard of the service, including a future maintainer's one-line fix in a REPL". It did
not.

`SessionEvents.do_orm_execute` was tried first and rejected on evidence: it fires for Core `insert` and
`update` but **not** for `bulk_save_objects`, which reaches `connection.execute` through
`bulk_persistence`. A `ConnectionEvents.before_execute` listener sees all of them, so one chokepoint
replaces two.

The bracket that tells the listener a flush has been vetted is set at the **end** of `before_flush`, after
every raise, so a rejected flush cannot vet itself. It is released on `after_flush_postexec`,
`after_commit`, `after_rollback` **and `after_soft_rollback`** — the last being the one that matters: a
flush whose SQL raises never reaches `after_flush_postexec`, and a stuck flag would silently disarm the
guard, which is the A63 failure mode exactly.

Now refused: Core insert, update and delete; `bulk_save_objects`; `bulk_insert_mappings`;
`query().update()`; `query().delete()`; raw `text()` DML; and engine-level `conn.execute`. Verified
independently of the report, on a fresh database, before this was accepted.

**Deliberately no database-level guard on `positions`/`goals`, which is a decision and not an omission.**
`decisions` and `curator_session_events` carry triggers because "never UPDATE, never DELETE" is a property
of a single statement. C-09 is not: it requires a Decision *in the same transaction*, a SQLite trigger
fires per statement — before the Decision and its link rows exist — and SQLite has no deferred constraint
to move the check to COMMIT. A trigger there would refuse the legitimate path as readily as the illegal
one.

**What it does not cover, stated in the docstring rather than papered over:** a DBAPI cursor from
`engine.raw_connection()`, or `sqlite3` opened directly on the file, bypasses SQLAlchemy entirely. The
honest statement is that C-09 holds for everything that goes through SQLAlchemy and does not hold against a
raw DBAPI cursor.

`session.info[ERASING]` is now compared by identity against a private token, so a caller who merely knows
the key cannot set `True` and stand the guard down. Python cannot make that unreachable and the docstring
says so; what it buys is that the escape hatch is one greppable identifier, and a test greps the package
and fails if a third module acquires it.


## A73 — A member who had applied to be listed could not be erased at all

*Owner: Nicolas · 2026-08-30 · cost: one registry module, read by both sides*

The audit's finding was that R-154's export omitted five member-owned tables. Fixing it surfaced something
worse that nobody had asked about: **erasing a member who had been through `apply_to_be_listed` raised a
constraint failure on `DELETE FROM members` and rolled the entire erasure back.** `Provider` was not in the
erasure's list. The member could not leave.

Reproduced here independently of the report, both directions: with `Provider`, `Listing` and `Disclosure`
present the erasure completes and every table empties; with them removed it raises and **the member row is
still there**. That is R-231 failing in the only way that actually matters — not leaving a trace behind,
but refusing to act.

`listings` and `disclosures` were the same defect one level down, and harder to see: a listing's title and
summary are words the member wrote, and the erasure destroys them, but those rows carry no `member_id`, so
no schema scan finds them. They are reached through the provider chain.

**The fix is one registry, not five names.** `services/member_data.py` holds what a member owns, and both
the export and the erasure read it — including `owning_predicate()`, the single answer to "how does a row
belong to a member", used by the export's SELECTs and the erasure's DELETEs alike. Adding a table to one
and forgetting the other is now not expressible. The export went from 8 collections to 15.

This is the same shape as A63: the defect was not the five missing names, it was that two lists which must
agree were maintained separately. Fixing the instance without fixing that would have bought a week.

## A74 — Ordering cannot be bought, and now cannot be taken with a checkbox either

*Owner: Nicolas · 2026-08-30 · cost: one function, and the arithmetic to justify it*

Two C-08 defects, both of which made the constraint weaker than its tests suggested.

**Two of R-203's three ordering inputs were dead on the real write path.** `Listing.standing_inputs` was
written once, empty, and never derived from the database. A provider with six capability assertions and six
attendances scored zero on both. Every ordering test drew its non-zero standing from the seed fixture,
which is why this looked fine — and it meant `test_listing_ranking_cannot_read_fee_fields`, a genuinely
good test that does hold, was proving a fee could not move an order that was two-thirds constant.

**And declaring all four roles beat genuine standing.** `role_match` counted declared roles intersecting
the query, a provider declares its own roles unaudited, so a generalist with one assertion outranked a
specialist with six on any multi-role query.

`role_match` is now a **share**: `|declared ∩ requested| × 12 ÷ |declared|`. The count was monotone in how
many roles you declare, so ticking boxes was free. A share inverts that — declaring a role nobody asked for
*lowers* it — and because it is capped, **no declaration can beat another declaration; the most it can do
is tie, and ties fall to capability evidence and community presence.** That is C-08's principle expressed
as arithmetic rather than as intent, and it is proved over all 225 declared/requested pairs. Twelfths
because 12 is the lowest common multiple of 1 through 4, so the sort key stays an exact integer.

Three alternatives were rejected for stated reasons. **Binary** would have removed the input along with the
incentive: `browse` already filters to entries matching at least one requested role, so every survivor
would score identically and R-203 would be down to two live inputs — the defect being fixed, one input
over. **Weighting it below evidence** leaves the count in place, so a generalist still wins every tie.
**Requiring corroboration** is the purest reading of C-08 and the data cannot support it: `Capability`
carries no role and D-01 leaves the rung scheme undecided, so the mapping would have to be invented.

One hole the fix opened and closed: `standing_inputs` is a field the ordering reads but does not compute,
so it was a route by which a commercial term could have reached the sort. An AST scan now requires every
expression assigned to it to be free of the same vocabulary the ordering functions are.

**Accepted limitation:** published standing is as of the last publish, so a member who earns an assertion
afterwards does not re-rank until re-publication. Deriving at read time would need a provider lookup inside
the browse loop, widening exactly what C-08's scan exists to narrow. Staleness only ever understates.

## A75 — C-06's content half, and why it is a trigger rather than a CHECK

*Owner: Nicolas · 2026-08-30 · cost: two triggers and a migration*

The CHECK counted the array; it could not look inside it. SQLite prohibits subqueries in a CHECK and
`json_each` is a table-valued function needing a FROM, so two options carrying no `consequence` persisted
through any path that skipped the ORM validator — `bulk_insert_mappings` among them. C-06 says an action
item exists only if it carries the options *and their consequences*; the store enforced only the count.

Two BEFORE triggers on `action_items`, derived from `REQUIRED_OPTION_KEYS` rather than written out,
attached via `after_create` so they arrive with `create_all`, plus a migration that runs them on
`op.get_bind()` — **not `.engine`**, citing A63, A66 and A68 by number. The trap was not repeated.

They fire only on an array already at least two long, so a JSON object, a bare string, an empty array and a
single option all still fail by the CHECK's own name rather than by a confusing content error.

**The test had to be inverted, which is the interesting part.** It used to write the row and then assert
the row was absent. Once the store refuses, the write itself raises — so an un-inverted test fails on the
exception before reaching its own assertion, and therefore passes as an `xfail` over a defect that has been
*fixed*. That is A63's pattern in miniature, pointing the other way: a test that cannot observe success is
as useless as one that cannot observe failure. The refusal is the property; the absence was only ever a
proxy for it.


## A76 — C-01 is a blacklist, blacklists are unbounded, and the destination is grounding

> **WITHDRAWN 20 September 2026.** The blacklist argument, and the conclusion that grounding was the destination. It was right, and A164 is where the build acted on it. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-30 · cost: 255 patterns, and an honest answer about their ceiling*

C-01's outbound check began as **six regexes** matching exactly the seven phrasings that had tests. "You
should put all 10,000 into the Vanguard FTSE All-World ETF" passed through and was serialised to the member
with `requires_curator: false`. French and Italian were not covered at all — on either gate — for a Swiss
product, and `refusal_text` fell back to German silently.

It is now a **per-sentence co-occurrence rule** built from C-01's own verbs: directive force conjoined with
something financial to direct; a comparison drawn explicitly for this member; a share *of* an instrument;
a suitability verdict with both member-direction and a financial object. Four languages, both registers.

**Two rounds, and the second is the one worth recording.** The first pass fixed everything the audit had
named and produced a careful seven-class list of what still got through. I then wrote fifteen probes of my
own and **eleven passed** — including `Kauf den Weltfonds` (a du-register imperative, a register the guard
did not cover) and `An deiner Stelle würde ich…` (ordinary German verb-fronting, and a construct the *old*
code caught, so a regression). Neither was on the list. The list had been arrived at by introspection.

The instruction that followed is the transferable part: **generate the probes and read the failures, do not
reason about what the rules ought to catch.** The second pass ran ~300 probes across a register matrix and
closed three classes it had previously given up on. It also found two things I had not: a bare `\bbeste\b`
was refusing "Was ist der beste *Weg*, meine Säule 3a zu verstehen?" — A20's `hut`-in-*Schutz* again — and
the two gates disagreed, with inbound refusing a question whose answer outbound would have returned.

**The considered answer to "can this be bounded": no.** 255 patterns catch 118 of 119 register probes, but
that number measures the author's imagination, not coverage — the same suite scored 100% before I broke it
in eleven places. Every round has the same shape: probe, several escape, add patterns. That is not
convergence.

**The destination is the grounding rule.** Requiring every claim to be supported by a retrieved passage
changes the question from *how is this phrased* to *where did this come from*; since the corpus is
impersonal it contains no advice about this member, so personalised advice becomes structurally
unproducible rather than merely hard to phrase. Two cautions carried forward: it is an entailment check,
and the obvious implementation puts a model back inside the gate — which breaks "provably not by prompt
alone" unless the judge is separate, non-generative and independently testable. And it is a *superset*
check, not a replacement: an answer can be perfectly grounded and still rank ("Passage 3 says fund X
returned more than fund Y" → "Fonds X schlägt Fonds Y"). The pattern module stays as the last gate beneath
it.

**The largest open hole is a bare instrument name.** A ticker matches no lexicon entry, so the
co-occurrence rules have nothing to conjoin with and `VWRL für Sie, zehn Jahre halten` reaches the member.
A named-instrument detector is bounded in a way phrasing is not and would close it — but an all-caps
heuristic drowns in AHV, BVG, IV, UVG, PK, CHF and ETF, so it needs a stoplist, which is a blacklist again,
merely smaller and more stable. Recorded with a test that **asserts the hole is open** and instructs its own
deletion on the day it closes.


## A77 — The exception hole in C-04, closed by not needing to see the traceback

*Owner: Nicolas · 2026-08-31 · cost: one method*

A71 closed C-04's installation defect and left one named form open, honestly: a logging filter is never
handed the traceback, so `logger.exception()` on an exception whose message reads `could not parse
title=<value>` emitted that value verbatim. Vault extraction is precisely the code that raises with the
document it was parsing in the message, so this was not hypothetical.

**The premise was true and the conclusion was not.** A filter does not see the traceback, but it does not
need to. `logging.Formatter.format` renders `record.exc_info` *only when* `record.exc_text` is empty, and
uses `exc_text` verbatim when it is set. So the filter renders the exception itself, runs it through the
same text scrubber the message already goes through, and assigns the result — the Formatter then emits the
redacted rendering because it believes the work is already done. `stack_info` goes the same way, since
`stack_info=True` renders a frame list that can carry a local's value into the line.

`exc_text` is set **only when something was actually redacted**. A JSON or otherwise custom Formatter
overrides `formatException`, and pre-rendering every traceback with the standard library's version would
quietly flatten that. The cost is that a record needing redaction loses a custom exception rendering, which
is the right way round.

Verified in both directions before acceptance: without the filter the secret is present in the emitted
text, with it the secret is gone. A test that only checked the second half would pass on a formatter that
emitted nothing at all.

**Two smaller things worth recording.** Writing this through a bash heredoc turned `
` into a real
newline and produced an unterminated string literal — A20's hazard, third appearance, and the reason the
standing instruction to agents is to write source through the editor. And the health board's `known_gaps`
guard from A70's practice fired the moment the fix landed: C-04 was still listed as a gap with no failing
test behind it. That is the guard doing exactly what it was written for, one day after being written.


## A78 — C-01, third round: how people actually type, and a comparison left unfinished

> **WITHDRAWN 20 September 2026.** C-01's third adversarial round. The probes it describes are deleted with the suite. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31 · cost: one compile-time transform, one inbound rule*

The agent drafting German knowledge content was told to run every sentence through the live C-01 gate. It
reported zero refusals on its own prose — and then, unprompted, reported a hole it had found by writing
naturally.

**ASCII-transliterated German walked through both gates.** The same sentences, refused with umlauts and
passed without:

| | with umlauts | as typed without |
|---|---|---|
| `Fonds X ist für Sie geeigneter als Fonds Y` | refused | **passed** |
| `Wählen Sie beim Austritt ein Freizügigkeitskonto` | refused | **passed** |
| `Sie müssten den Maximalbetrag einzahlen` | refused | **passed** |

Verified independently before acting: four bypasses, outbound and inbound.

**This is not the documented obfuscation class.** The module lists "spacing, homoglyphs, zero-width
characters" as a known evasion, and it would be easy to file this beside it and move on. It does not
belong there. `fuer` and `waehlen` are how German is typed on a keyboard without umlauts, and how a model
asked for ASCII-safe output writes. Nobody is evading anything. An accidental bypass by an ordinary user is
worth more attention than a deliberate one by an adversary, because it happens without anyone choosing it.

**Closed by rewriting the patterns, not the text.** Folding incoming text — turning `ue` back into `ü`
before matching — manufactures false positives out of ordinary words: `Steuer` becomes `Stür`, `neue`
becomes `nü`. Making a pattern tolerant can only ever let it match another spelling of what it already
matched; no pattern gains reach over a word it did not already describe. Character classes are handled
rather than skipped, because 68 patterns spelled the tolerance by hand as `[üu]` — which accepts `fur` and
`für` but *not* `fuer`, so the hand-written version had precisely the hole this closes.

**A second hole, found while checking the first.** `Wäre ein Freizügigkeitskonto für mich besser?` was
classified as education, and so was `Was wäre für mich sinnvoller?`. Two causes: the comparative patterns
required an explicit `besser ALS`, so a question that leaves the alternative unsaid never matched; and the
entire comparison branch sat behind `if instruments`, so a question naming no instrument never reached it
— which is exactly how a member who has not learned the vocabulary yet asks. Asking which side of a
comparison you fall on is a request for a judgement about you whether or not you finish the sentence.

The new comparative list is deliberately only the **evaluative** words. `Was ist für mich einfacher zu
verstehen?` is a question about learning and must stay education; `Was wäre für mich sinnvoller?` is a
request for a judgement. That distinction is the whole cost of the rule and the list is meant to stay
short. Both directions are pinned by tests, and a guard-on-the-guard proves the transliteration tolerance
is load-bearing rather than incidentally covered by some pattern that never had an umlaut in it.

**The reporting practice is what produced this.** The instruction to the author was to report any sentence
the gate refused rather than quietly rewording it, because a refusal of genuinely educational content is a
finding about the gate. It complied, and also reported the inverse — a bypass it had no reason to look for.


## A107 — C-01 now admits a statement of statutory duty, and still refuses it in the subjunctive

> **WITHDRAWN 20 September 2026.** C-01 admitting a statement of statutory duty while refusing the subjunctive. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Raised 2026-08-31 as OPEN · answered by the owner 2026-09-01: **yes, C-01 may state a legal duty** ·
the only place C-01 has ever been loosened*

The gate refuses a member-directed statement of a **legal obligation**, verified:

- `Sie müssen Beiträge an die Pensionskasse zahlen, sobald der Jahreslohn die Eintrittsschwelle erreicht.`
- `Sie müssen das 3a-Guthaben spätestens mit dem Erreichen des Referenzalters beziehen.`
- `You must withdraw the pillar 3a capital by the reference age at the latest.`

All three are facts about Swiss law, all three are the kind of thing a member most needs to be told, and
all three are refused. Rule 2 conjoins deontic force with a financial object, and in a Vorsorge corpus
nearly every duty is a duty *about* a Vorsorgegefäss — so the exemption the docstring offers ("Sie sollten
die Steuererklärung bis März einreichen" survives, because *Steuererklärung* is not an instrument) almost
never applies.

**The impersonal construction passes**: `Wer nicht erwerbstätig ist, muss AHV-Beiträge zahlen` is fine, and
the drafted knowledge entries use that form throughout. It reads well — arguably better. But that is a
workaround available to an author and **not to a model answering live**, which is the case C-01 exists for.

**Why this is not being fixed on the implementer's judgement.** The obvious narrowing — treat indicative
`müssen` as duty and subjunctive `müssten` as advice — does not survive contact: `Sie müssen unbedingt
Fonds X kaufen` is advice wearing duty's grammar, and it is currently caught. Separating the two needs the
statutory *marker* (a threshold, a deadline, a named legal age) rather than the modal, which is a whitelist
in the loosening direction on the one constraint the spec calls regulated.

The trade is: **false refusals of legal facts, against a weaker advice gate.** That is a decision about what
the product may say about the law, and §12's principle is that decisions of that kind belong to the owner.
Recorded here rather than taken.

**The owner answered yes.** `boundary.states_statutory_duty()` now exempts a sentence from rule 2, and
because this is the only place C-01 has ever been *loosened*, all three of its conditions must hold
together:

1. **indicative duty** — `müssen`, `muss`, `ist zu`, `must`. The advisory subjunctive `müssten` and
   `sollten` are deliberately absent, so German's own verb form carries the distinction the narrowing
   needed — which is why this works in German and is not portable to the English gate.
2. **a statutory marker** — a named institution, a cited article, a threshold, a legal age, a deadline. A
   duty with no source is not a statement of law; it is an instruction.
3. **no selectable instrument, and no share of one** — which stops `Sie müssen unbedingt Fonds X kaufen`
   on this condition alone, independently of the other two.

**Verified after the change**, against the entry's own three sentences and three more written to defeat
the exemption. All three above are now admitted. Still referred, each with `answer_ranks_or_recommends`:
`Sie müssten den Maximalbetrag einzahlen`, `Sie müssen unbedingt Fonds X kaufen`, and `Sie müssen das
3a-Guthaben in den Indexfonds Y einzahlen, spätestens mit dem Referenzalter`.

**The third of those is the one worth keeping.** It satisfies conditions 1 and 2 — indicative duty, a real
statutory deadline — and is refused on condition 3 alone, because it names a fund. It is the sentence that
a two-condition version of this exemption would have shipped, and it reads exactly like the legal facts
the loosening exists to admit.

**The residual risk is stated in the function rather than left to be found.** A sentence can satisfy all
three conditions and still be a nudge — *"Sie müssen die Beitragslücke bis Ende Jahr schliessen"* reports
a real deadline, applies it to this member, and names no instrument. The judgement is that reporting a
duty a member is genuinely under is the product's job, and that C-01 protects against *selection*, which
such a sentence cannot perform. If that proves wrong, the fix is condition 2, not the exemption.

**A near-miss worth recording, because it is the third of its kind.** The verification above first
reported all six sentences refused — including the three it was meant to confirm as admitted. The probe
read `verdict.ok`, and `Verdict` has no `ok`: its fields are `requires_curator`, `reason`, `matched`, so
`getattr(v, "ok", None)` returned `None` for every sentence and rendered as a refusal. Two earlier false
zeros in this build came from the same shape. **A probe that reports a uniform result across cases chosen
to differ has usually not run** — check the accessor before believing the finding, especially when the
finding is the one that would have been recorded as a defect.


## A106 — The Know surface returned confidently wrong law; it now quotes instead of paraphrasing

*Raised 2026-08-31 as OPEN · answered by the owner 2026-09-01: **extractive only** · this one gated
whether S-08 ships at all*

The book index is wired and retrieval is good. Asked *"Kann ich den Bezug der AHV-Rente aufschieben?"* the
system retrieves the right passages — Merkblatt 3.04, the Vorbezug-und-Aufschub section — and then the
model produced this, verbatim, with three citations attached and `requires_curator: false`:

> „Die **Kürzung** des Rentenbetrags erfolgt dabei um einen versicherungstechnischen Prozentsatz, der von
> der **Vorbezugsdauer** abhängt. Die **Kürzung** muss zwischen 20 % und 80 % der zustehenden Altersrente
> liegen."

Three errors in two sentences. An **Aufschub gives a Zuschlag, not a Kürzung** — the sign is inverted. It
attributes the effect to *Vorbezugsdauer*, which is the opposite operation from the one asked about. And
the 20–80 % band is the **Teilbezug** proportion — what share of the pension you draw — not a range of
reductions; it is a real figure from the corpus, applied to the wrong quantity.

**It reproduces about one run in three.** The other two runs stop after the correct first two sentences.
It never says *Zuschlag* at all, so the correct fact is not stated even when the wrong one is omitted.
Intermittency is the worst property here: it survives a spot-check and fails on a member.

**C-01 passed it, correctly.** The boundary asks whether an answer *advises*, not whether it is *true*.
This answer recommends nothing. Every guarantee in the build held — retrieval grounded, citations rendered,
the advice gate ran — and the member is told the opposite of the law by a system that shows its sources.

**Why this is worse than a recommendation.** A member who reads "ich würde" knows they are being given an
opinion. A member who reads a cited paragraph about their pension has every reason to believe it. The
citation is what makes it dangerous: it converts a model error into something that looks checked.

**Not fixed, because the options are a decision and not a detail:**

- A **numeric faithfulness check** — every figure in the answer must appear in a cited passage — is cheap
  and deterministic, and would *not* have caught this: `20` and `80` are both in the corpus. It is worth
  having anyway, against invented figures, but it is not the answer to this.
- **Extractive-only answers**, quoting retrieved sentences rather than paraphrasing, would close it
  outright. The estate already applies exactly this instinct one layer over: onboarding interpretation is
  extractive and every value is verified to appear in the member's own text. The cost is that the answer
  surface stops explaining and starts quoting.
- An **entailment check** — the destination A76 names — is the general form, and carries A76's own caution
  that the obvious implementation puts a model back inside the gate.

**The owner chose extractive only.** The Know no longer writes sentences. `ask()` keeps C-01's order —
classify, retrieve, model, check, cite — and what changed is the middle step: each retrieved passage is
split into quotable units, the model is asked *which numbered sentences of this source answer the
question*, and the sentences those numbers name are what the member reads, verbatim, in quotation marks,
each carrying the index of its own citation. The reply is JSON at temperature 0. **There is no field in it
through which prose could arrive.**

**Selection runs per source, and that was measured rather than preferred.** One pass over every retrieved
sentence at once was wrong on 2 of 6 AHV questions and, on the longest list, degenerated into returning a
consecutive run of 70 numbers. Both misses had the same shape: a true sentence from the source whose
*title* matched, chosen over the sentence carrying the answer. Per-source selection went to **18 of 18
across three runs of six questions**, with a short rerank over the union cutting to at most three and
ordering them.

**The guard the decision rests on is a property of the emitted string, not a promise about the model.**
`unquoted_sentences` reports any quoted span occurring in none of the passages *and* any letter or digit
standing outside the quotation marks — that second half is what makes "the member reads nothing that is
not quoted" checkable rather than assertable. Planted against it: commentary inserted between two quotes,
a lead-in before the first quote, bare unquoted prose, and the wrong-law sentence from the top of this
entry. All four were caught, the last because it occurs in no passage and therefore cannot be assembled.
Four gates now run on what will be emitted, each refusing the whole answer: `check_answer` on the raw
reply, `check_answer` on the assembled quotation, `unquoted_sentences`, and `unverifiable_figures`.

**The question at the top now answers correctly, identically in 5 of 5 runs**, and *Kürzung* does not
appear in it. The 20–80 % band is reachable only as the corpus's own „Der **Anteil** muss zwischen 20 %
und höchstens 80 %…" — the sign cannot be inverted, because the words are not the model's. Across 45 live
answers `unverifiable_figures` fired 0 times and `unquoted_sentences` 0 times.

**The model is still needed, and that was measured too.** Lexical scoring alone cannot pick the sentence:
on *"Wie hoch ist der Mindestbeitrag…"* the retriever's own weighted term overlap put the answering
sentence outside its top 8 of 142, ranking above it a true sentence about a different calculation. Scoring
finds the passage; it does not find the sentence. The model keeps exactly one job, and it is a job where
being wrong produces a wrong *quotation* rather than a wrong *fact*.

**What it costs, stated plainly.** Answers now address the corpus's phrasing rather than the member's.
Quotations carry the source's own inline list dashes, because that is literally what the Merkblatt says.
Nothing bridges two quotes — the member gets two adjacent sentences and infers the connection themselves.
**The failure mode has moved from truth to relevance:** the residual error is a true, correctly cited
sentence answering an adjacent question, and it is visible to a member precisely because the citation
names the source of that quote. That is a categorically better failure than an inverted sign wearing a
correct citation.

**The strict xfail stays, and `S-08/truth` stays on the board in narrowed form.**
`test_a_grounded_answer_that_misapplies_a_real_figure_is_refused` asserts a property of
`boundary.check_answer` in isolation, and `check_answer` is still blind to a misapplied figure. This was
closed **by construction, not by detection** — and if the extractive constraint is ever loosened, that
boundary is the only thing that would be standing here, and it would not hold.


## A79 — The application had no authentication at its boundary, and now does

*Owner: Nicolas · 2026-08-31 · cost: one router, one dependency, 41 route signatures, a login surface*

`GET /api/positions?member_id=<any id>` returned any member's entire role grid — every position, every
franc figure, human capital and financial — to a caller with no token, no password and no header. So did
the vault listing, the goals, the consent history and R-154's whole export. Every member-facing route took
`member_id` as a query parameter or a body field and believed it.

**`services/auth.py` had been complete and tested since phase 2.** `register_with_credentials`, `login`,
`member_for_token`, `logout`, `revoke_all_sessions`, `change_password`, `operator_reset` — all of it, with
the twelve demonstration credentials seeded against it (A53, A56). Exactly one thing HTTP-facing called any
of it: `current_member` in `api/curator.py`, for the grant routes, because R-213 forced the question there.
A11 was decided in phase 0 and the service was built in phase 2; the HTTP and client layers never were, and
nothing in the suite noticed, because there was no test that asked an anonymous caller to be refused.

**The fix is the removal of the parameter, not a check on it.** `api/auth.py` holds one dependency,
`current_member`, which reads the bearer token and hands the route a `Member`. `member_id` is gone from
every non-curator route signature and from `AnswerRequest`, `PositionRequest`, `AskRequest`,
`VaultItemRequest`, `GoalRequest`, `CuratorSessionRequest`, `OpenCuratorSessionRequest`,
`ApplicationRequest`, `RecordAttendance`, `WithdrawConsent` and `DataRequest`. A route that never receives
an id cannot be handed the wrong one, and no forgotten comparison can put the hole back. The distinction is
not academic: the "check it instead" fix is an optional parameter that wins when present, and the test that
would pass against it is the one that only ever makes plain requests. Both shapes were planted; the plain
pass stayed green against the second and the `?member_id=<B>` pass caught it.

**No developer bypass, at the owner's instruction.** No `ANDERSCH_DEV_MEMBER`, no localhost exemption, no
operator header. The stated reason is that a second way in is the thing that gets shipped by accident; the
demonstration accounts are how someone gets into their own laptop and they go through the same door.
A test greps the api package for an environment read and for the words a bypass would be spelled with.

**The routes that stay open are twelve, and each has a written reason** in `api/auth.py`'s docstring rather
than being inferable from forty signatures. The rule they were drawn from is one line: *a route is open
only if it is incapable of returning anything about any member and takes no member-owned input* — plus
registration and the login form, which are where a session becomes possible and so cannot require one.
`test_the_open_list_and_the_dependency_graph_agree` compares that list against the application's real
dependency graph in both directions, so a route added without a guard fails by name, and
`test_every_open_route_is_argued_for_in_the_auth_docstring` fails if one is opened without an argument.

Two of them lost a parameter rather than gaining a guard: `GET /api/life-events` took `member_id` and
echoed it back into the payload without reading a single member-owned row, and `GET /api/stages/{key}`
never had one. A parameter that buys nothing is not made safe by a dependency; it is made honest by being
deleted.

**`must_change` is enforced by the server, not by the client.** A forced password change that only the
client enforces is not enforced. A session whose credential is marked reaches `GET /api/session`,
`DELETE /api/session` and `POST /api/password` and nothing else. That is what makes A53's argument true
rather than aspirational: the passwords for Elio and Yasmin T. are written down in Notion because they are
good for exactly one login, and until today nothing in the application made that so.

**Two defects found by writing the tests, not by reading the code.**
A bare `Authorization: Bearer ` — the scheme with nothing after it — raised `IndexError` on
`split(None, 1)[1]` and came back as a 500. `api/curator.py` had carried that line for three phases. It
parses with `partition` now, in the one place the header is read.
And `POST /api/members` created a member row, flushed it, and only then hashed the password, so a password
under twelve characters left behind a member nobody could ever log in as. Removing the rollback makes that
test fail; the same removal on the age-floor branch changes nothing, because `ck_members_age_floor` refuses
the INSERT — so that line is insurance and the code now says so instead of looking load-bearing.

**Sixteen guards, each verified by planting the violation and watching it fail.** Three of the first
fourteen did not fail on the first attempt and all three were findings rather than formalities: a plant that
did not reproduce the bug it named; a rollback that was dead code held up by a CHECK constraint; and
`test_only_one_module_reads_a_session_token`, which matched `member_for_token(` **with the parenthesis** and
so did not notice the import being added back — one line short of a second implementation with the guard
still green. That is A66's rule (*a test that asserts something is absent must be proven able to detect its
presence*) catching a defect in a test written to obey it.

**The client is A11's other half.** `store.js` — a list of member ids in `localStorage`, whose own comment
said it "authenticates nothing and must be deleted the moment real sessions exist" — is deleted, along with
`?member=<id>`. `session.js` holds one token and the identity the server returned with it; `api.js`
attaches the bearer header in the single place this client reaches the network; `surfaces/login.js` is the
login form, the registration form and the forced password change. A 401 from any route ends the session in
one place, and a 403 carrying `password_change_required` is the server directing the member to the one
screen they may use.

The password is never stored: only `session.js` touches browser storage, and what it writes is a token and
a name. `localStorage` rather than a cookie deliberately — a cookie is sent automatically on every request
to this origin, which is where CSRF lives, and a header the client attaches is not sent by a form on
another page.

**A12's chrome gap, which A70 recorded with a precise location, is closed on the way past.** The three door
labels and the skip link were German literals in `index.html`; they carry `data-i18n` keys now and
`applyChrome` rewrites them at boot and on every language change, with the German text left in the document
as the served default so a member whose script has not run still reads a real header. The language is the
member's own locale, which the server splits into a language for them — a client that guesses gets `de-CH`
right and a future `rm-CH` wrong, silently, in German.

**One hole opened and left open, stated rather than discovered later.**
`POST /api/marketplace/applications/{id}/disclosures` and `.../publish` are addressed by listing id and
carry no member field, so requiring a session is all they gained: any authenticated member can still add a
disclosure to, or publish, another member's draft listing. The ownership chain exists
(`Listing.provider_id` → `Provider.member_id`) and the check is small. It is not made here because whether
a curator or an operator may publish on an applicant's behalf is a second decision, and it is the same
"who may call this write route" question `api/remainder.py` has recorded as open for the whole prototype.

**Two narrowings worth knowing about.** `POST /api/community/attendance` now writes attendance against the
token's member, so a member records their own; before, any caller could inflate any provider's community
presence — one of C-08's three ordering inputs — by posting attendances in someone else's name. And
`GET /api/learning` lost its anonymous mode: it was optional-`member_id`, which meant passing somebody
else's id returned their capability evidence. `GET /api/learning/exits` is the route that still answers
"what is this for" without a session.


## A80 — The book index is wired, and the calibration that made it honest

*Owner: Nicolas · 2026-08-31 · cost: one module, 95 calibration probes*

A34 deferred the book corpus. It is wired now, read-only, from the estate at `desktop/bookindex/`.

**The floor is conjunctive — semantic ≥ 540 per mille AND lexical ≥ 100 — because neither channel
separates alone.** A multilingual embedding scores a German question against a 91-per-cent-English corpus
on *language*, not topic: "Was kostet eine Kinderkrippe in Zürich?" scores 0.576, above any semantic
threshold that still admits real questions. What the junk shares is a lexical score of exactly 0.000.

| gate | kept of 40 answerable | false positives of 55 |
|---|---|---|
| semantic ≥ 0.540 alone | 37 | **7** |
| semantic ≥ 0.600 alone | 17 | 0 |
| lexical ≥ 0.700 alone | 16 | 0 |
| **both** | **31** | **0** |

Measured over two rounds with the second held out and scored only after the floors were fixed. The
separation is **five per mille** — highest unanswerable 0.537, lowest answerable kept 0.542 — and both
bounds came from the held-out round. That is a filter, not a guarantee, and it is recorded as such rather
than presented as a threshold with authority.

One correction did most of the work: normalising the lexical share over *all* query terms, including ones
the corpus has never seen. Before that, a passage carrying a question's single in-vocabulary word scored
1.000.

**The approval gate for authored content is enforced by the reader, not trusted to the author.** Only
`approved: true` — in any case — is retrievable; `yes`, `pending`, `1`, `[true]`, a typo'd key, an indented
key and an unparsable file all fail closed, and an approved entry with no `sources:` is not retrievable
either, because R-171 cannot cite it. Verified independently in both directions: all 14 drafts refused, and
all 14 retrievable when flipped — a gate, not a wall. The wall failure mattered: the parser initially
mis-read the drafting convention's real shape and failed closed on all of them, which is safe and would
also have meant approval silently doing nothing forever.

## A81 — Login, wired by removing the parameter rather than checking it

*Owner: Nicolas · 2026-08-31 · cost: one router, one dependency, the client's whole entry path*

`services/auth.py` had been complete and tested since phase 1 and nothing HTTP-facing called it. Any
member's full record was readable with `GET /api/positions?member_id=<id>` and no credential at all.

**The decision that shaped the fix: no bypass.** The owner declined a developer escape hatch explicitly,
on the grounds that a second way in is the thing that gets shipped by accident. There is no env var, no
header, no localhost exemption.

**`member_id` is gone from every non-member-agnostic route, not validated.** 67 route/method pairs; 55
guarded, 12 open under a written rule — *open only if it cannot return anything about any member and takes
no member-owned input*, plus the two that make a session possible. Removal beats checking because a
removed parameter cannot be forgotten in a route added next month. Verified live against the real seeded
database: `?member_id=<someone else>` with a valid token returns the token holder's own record, every time.

Two routes could not be closed by removal, because they address a listing by its own id: adding a
disclosure to, and publishing, an application. Any authenticated member could act on anyone's draft. The
agent that found it recorded it as an open decision, on the grounds that whether a curator may publish on
an applicant's behalf is a second question. **It was closed instead, in the restrictive direction** —
publishing someone else's application is not a feature anyone asked for, and a curator path is an addition
someone can make deliberately. A permission added on purpose is reviewable; one left behind is not. The
refusal is 404, not 403, on the same reasoning that makes a wrong address and a wrong password
indistinguishable.

**Two real defects surfaced from writing the tests, not from reading the code.** A bare `Authorization:
Bearer ` raised `IndexError` and returned 500 — a line `api/curator.py` had carried for three phases. And
`POST /api/members` left an unusable member row behind when the password was too short.

**One test was one line short of vacuous.** `test_only_one_module_reads_a_session_token` matched
`member_for_token(` *with the parenthesis*, so a second module could re-add the import and the guard would
stay green. Found by planting it — A66's rule catching a defect in a test written to obey A66's rule.

And a plant that did not fail, which was the finding: removing the age floor's `session.rollback()` changed
nothing, because the CHECK constraint catches it anyway. That line is insurance and now says so instead of
looking load-bearing. The `WeakPassword` rollback beside it *is* load-bearing, proven the same way.

**The distribution ZIP is the same hazard by another route.** `dist/andersCH-prototype2.zip`, dated
2026-08-30, contains `store.js` and `welcome.js` and no session module — a friend installing it would get
an application with no authentication at all. Not the bypass someone added; the bypass nobody remembered to
remove. Not deleted and not rebuilt, both deliberately: the archive is the owner's, and the rebuild is
gated on their review. Labelled with `dist/STALE-DO-NOT-DISTRIBUTE.md`, which lists what the rebuild has to
pick up.

A12's chrome gap is closed as part of this: the doors and skip link carry `data-i18n` and are rewritten on
every language change, so an English member no longer keeps a German header.


## A82 — D-01, D-02 and D-04 are answered. §12's list is now empty.

*Owner: Nicolas · 2026-08-31*

All three were answered directly, and two of them close by **confirming that nothing should be built**,
which is why they were on §12's list rather than in a backlog.

**D-01 — the rung scheme and how a capability is assessed: the member's own responsibility.** Recorded as
*"it's their responsibility"*. Read as self-assessment: a member asserts a capability, and andersCH does
not test, grade or certify it. That is consistent with R-194's prohibition on any claim of accredited
status, and it means `Capability.rung` can stay null permanently rather than awaiting a scheme. **If
"their" meant the curators rather than the members, this is the one line to correct** — it changes who
writes a `CapabilityAssertion` and nothing else.

**D-02 — several positions as one risk: never aggregated.** *"That is the user's decision, we look at each
position individually and don't aggregate them as risk."* The five correlation tags stay stored and
uninterpreted, which is exactly what the build already does — so this closes as a **decision not to build
the inference at all**, rather than as a deferral. The tags remain useful to a member reading their own
plan and to a curator; no code reads them to combine positions.

**D-04 — automated vault intake: not now.** Manual upload only, which is what exists. The other adapters
stay as stubs that raise.

**What this leaves.** §12 said "these are unresolved; build the structure that holds them and leave them
configurable and empty. Filling one in is a defect." All eight are now answered — D-03 by the reviewed
role definitions in `client/content/roles.json`, D-05 through D-07 by the specification itself, D-08 by A1,
and these three here. There is no longer any part of the build waiting on a decision.

## A83 — C-01 admits statements of statutory duty

> **WITHDRAWN 20 September 2026.** C-01's statutory-duty exemption. There is no gate for it to be an exemption to. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31 · answered: yes*

The gate refused a member-directed statement of a legal obligation — `Sie müssen das 3a-Guthaben
spätestens mit dem Erreichen des Referenzalters beziehen` — because rule 2 conjoins deontic force with a
financial object, and in a Vorsorge corpus almost every duty is a duty *about* a Vorsorgegefäss. The
impersonal workaround belongs to an author and not to a model answering live.

The owner answered **yes**: the product may tell a member what the law obliges them to do.

**The exemption is narrow and guarded three ways, because this is the loosening direction on the one
constraint the specification calls regulated.** A sentence is admitted only when all three hold:

1. the modal is **indicative duty** — `müssen`, `muss`, `ist zu`, `must`, `hat zu` — and not the advisory
   subjunctive `müssten`, `sollten`, `würde`, which stay refused. German marks the difference between an
   obligation and a suggestion in the verb, and that is the whole distinction C-01 cares about here;
2. the sentence carries a **statutory marker** — a named institution, a threshold, a deadline, a reference
   age, a cited article. A duty with no source is not a statement of law;
3. the sentence names **no selectable instrument** and states **no weight or share of one**. `Sie müssen
   unbedingt Fonds X kaufen` is advice wearing duty's grammar, and it stays refused by this condition
   alone.

**Institutional vehicles are not selectable instruments.** `AHV`, `BVG`, `Pensionskasse`, `Säule 3a` are
not things a member picks from a shelf — nobody chooses whether to have an AHV — whereas a fund, an ETF or
a ticker is. That distinction is what makes condition 3 usable at all, and it is the substantive judgement
in this change.

**One separate precision fix, not a loosening.** Rule 4 refused `Der Höchstbetrag beträgt 20 Prozent des
Erwerbseinkommens für Personen ohne Pensionskasse` — a verbatim statutory rate — because a share
co-occurred with an instrument word anywhere in the sentence. The share there is of *income*, not of an
instrument. Rule 4 now requires the share to be **of** the instrument, which is what it always meant.
## A84 — R-152's other sources: action items derived from the plan itself

*Owner: Nicolas · 2026-08-31 · cost: one service, one column, one unique index, one migration*

R-152 says expiry dates are **the primary** source of action items. They were the only one. `store_item`
calls `action_item_for_expiry` when a document is stored with an expiry date, and nothing else in the
system ever created an item — so a member who had recorded positions and goals and uploaded no dated
document read an empty `/api/actions` forever. This is the same defect R-152 already had once, one layer
up: a requirement satisfied on paper because nothing in the running application called the function.

**Four derivations built, all threshold-free.** A goal with no active funding position (R-030 permits it,
so it is an observation and not an error); a goal whose target date has passed **with no Decision linked
to it since the date went by**; a capital type with nothing active in it; an optional onboarding question
still unanswered after onboarding completed. A fifth — a position still active whose start is long past
and which no later Decision names — is built but **fires only when the caller supplies the date**, with no
default, exactly as `expiring_items` takes `on_or_before`. "Long past" is a horizon, a horizon is an
assumption nobody has published, and `store_item` already refused to gate the expiry items on one for that
reason. The read path supplies no date, so that derivation is dormant in the application until someone
publishes the number.

**Three candidates rejected, and the rejections are the substance.**

*A concentration warning across the correlation tags: forbidden, not deferred.* D-02 closed yesterday
(A82) as a decision **not to build the inference at all**. A test greps the module and fails if any code
in it reads `Position.tags`.

*An item per empty cell of the role grid: rejected on R-113 and S-02's own acceptance test.* A member with
one position has seven empty cells. Seven items saying so is a completion meter written as a list, and
S-02 accepts only a screen where "no element implies eight positions is the goal". R-110's principle —
an empty cell states what would go there — is served by the grid, which is where it states it. The
**capital type** half was built instead: it can produce at most one item ever (firing needs one active
position and a type with none, and there are two types), and it says something the grid cannot.

*A consent never given or withdrawn: rejected because the requirement's own qualifier cannot be met.* The
candidate is "where something depends on it". **Nothing in this build depends on a consent.**
`Consent.purpose` is free text supplied at registration, no code path reads it, and there is no registry
of purposes. An item would have to state a consequence that is not true, and C-06 asks for the options
*and their consequences*. Building it would mean inventing the purpose registry and the dependency first.
Recorded as an open gap rather than filled in — and deliberately NOT added to `/api/health`'s
`known_gaps`, because an entry there is a promise that a strict `xfail` in `test_adversarial.py`
demonstrates it, and there is none.

**Idempotence is a claim about the store.** The derivations re-run on every read of the action list, so
"twice must not produce two items for the same cause" decides whether the feature is a list or a pile.
`ActionItem.derived_from` names the cause and a UNIQUE INDEX over `(member_id, trigger_kind,
derived_from)` enforces one item per cause forever. A read-then-insert in the service is the ordinary fix
and is still a race between two concurrent readers — the same argument A63, A66, A68 and A72 all make.
Onboarding `complete` called twice is this estate's own worked example of the cost.

An **Index** and not a `UniqueConstraint`, deliberately: `create_all` renders a UniqueConstraint inline in
the CREATE TABLE and a migration renders it as a separate index, so the two paths would produce schemas
that differ — and A68 is the week lost to exactly that. A test compares the two. The migration uses plain
`add_column` rather than `batch_alter_table`, so the table is never recreated and cannot lose C-06's two
content triggers; a test asserts both are still attached after `alembic upgrade head`.

Closing and reopening are part of it. A cause that stops holding closes its item as `expired` — not
`acted`, which would assert the member acted, the distinction `know.py` already draws for a superseded
vault item. A cause that returns **reopens the same row**, because the unique index means there can be no
second one. An item the *member* closed — `acted` or `dismissed` — is never reopened; a dismissed item
that comes back tomorrow is the nag R-175 forbids.

**C-01's outbound gate cannot police this register, and finding that out is the most useful thing here.**
All 24 member-facing strings pass `boundary.check_answer` with `requires_curator` False. Not one draft was
refused — and that is a finding about the gate's scope, not a compliment to the drafting. `check_answer`
is a per-sentence co-occurrence rule: **rules 2, 4, 5 and 7 require the sentence to land on something
financial** — an instrument from the lexicon, an amount, or a verb of moving money. A derived plan item
carries none of those by construction, because C-02 forbids the figures and the subjects are goals,
positions, dates and grid columns. Probed on the real gate, these are all recommendations and all come
back clean:

    "Sie sollten ein neues Datum festhalten."               rule 2, no financial object
    "Am besten setzen Sie ein neues Datum."                 rule 2 again; `am besten` is a directive
    "Eine Position ohne Betrag ist die sinnvollste Wahl."   superlative selecting a Wahl, rule 2
    "Ein Ziel ohne Zuordnung ist für Sie geeignet."         rule 5, no third conjunct
    "Warum nicht die Spalte jetzt ausfüllen?"               advice wearing a question mark, rule 2

Rules 1 and 3 need no financial object and do their job here — `Wir empfehlen …`, `An Ihrer Stelle …` and
`besser für Sie als …` are all refused, so the shared gate is half load-bearing in this register and is
kept. But a green `check_answer` over these strings would have been A20's hazard exactly: a check that
passes because nothing it looks for can occur. So C-01 is read again in `test_derive.py` with the
financial conjunct removed — narrower domain, stricter rule, legitimate because these are six fixed pairs
of sentences about a member's own plan rather than free model output. Which of the eight shapes the shared
gate catches is **pinned in both directions**, so growth in `boundary.py` retires the local pattern with
evidence and a weakening of it fails the suite.

**Every guard was planted, watched fail, and restored — 27 of them, mechanically.** Two findings came out
of doing it rather than claiming it. **One test was vacuous:** `test_a_skipped_onboarding_answer_is_derived`
asserted that the *required* onboarding question is never derived, and that assertion cannot fail —
onboarding cannot complete without an answer to it, so an answered question is absent from the skipped set
whether the filter exists or not. Deleting the filter left the suite green. The replacement blanks the
required answer *after* completion, which is a state a real member reaches by clearing a field, and it
goes red. **And three docstrings claimed plants that do not happen:** deleting the unique index leaves both
the idempotence test and the route test green, because the service's own lookup keeps them from ever
attempting the duplicate — the index guards the concurrent race, which no single-threaded test stages.
Those docstrings now say which test does catch it, and say that these two do not.

**Two smaller things worth recording.** `session.no_autoflush` is required to attach a funding position:
both orderings without it raise `PlanMutationWithoutDecision`, for opposite reasons — mutate the goal
first and the lazy-load's autoflush finds a dirty `PlanMutable` the Decision does not yet cover; link
first and the autoflush *persists* the Decision, which then leaves `session.new`, so the flush carrying
the goal's change sees no new Decision. Verified in all three arrangements. And `onboarding.complete`
calls `float()` on `employment_magnitude`, so a whitespace answer raises `ValueError` there rather than
being treated as unanswered — one module over, not fixed here, reported.

## A85 — The engines are reachable from the product, and a goal returns a number

*Owner: Nicolas · 2026-08-31 · cost: one table, one worker thread, one router, two service modules, 66 tests*

The owner's account of the problem was *"So, I can put all the information in but I don't get anything out
of it."* They were right, and there were two causes, one structural and one a stale literal.

**All seven engines worked and none was reachable from the product.** `call_engine` had exactly one caller
in the whole build — `tools/publish_assumption_set.py`, at a terminal. No member-facing path touched it,
because R-301 forbids an engine on a request thread (the fastest manifest declares 30 s, the slowest 1800;
the HTTP budget is two) and **the queue R-301 tells you to build instead was never built.** The engines were
wired in A69 and unreachable in the same breath.

**And `services/goals.py` told every member a reason that was false.** It returned `illustration: None`
with `"no_assumption_set_published"` — hardcoded, with a comment reading "none is published yet". A69
published one on 30 August. A35's blocker was lifted and nothing propagated. The test beside it passed
because the test database has no assumption set either, which is the whole lesson: a test can only check
the case it sets up.

### The queue: a table and a thread, and why not anything else

**The row is the queue and the row is the status.** `engine_runs` holds the engine, the payload, the result,
the reason, the timings, the declared budget and the member it belongs to. `POST /api/runs` writes a row and
returns 202 with a poll URL; `GET /api/runs/{id}` reads the same row the worker writes.

Rejected, with reasons: **Celery/RQ/arq** add a broker to install and a second answer to "what is the status
of this run", and A47's naked-laptop ZIP has no way to carry either. **`BackgroundTasks`** dies with the
process holding no record and runs *after the response on the same worker*, so a 1800-second engine occupies
an HTTP worker for half an hour — R-301's problem wearing a different hat. **A `queue.Queue` beside the
table** was the near miss, and it would put a run's state in two places; A63's triggers and A40's
`curator_id` were both exactly that.

**R-301 is held structurally rather than by a check.** There is no path from a route to a synchronous engine
call: `submit` builds the payload and writes a row. The thread flag exists as a second net —
`serving_request()` — and a test proves `call_engine` refuses inside it. The flag was *never called anywhere
in the application* before today, so R-301's runtime guard had been inert in the running server since it
was written; that is now closed for the route that is about engines, and the module says plainly that it is
not applied to every route.

**The worker binds to the database the request came in on, not at boot.** The lifespan hook started it
first, and that was removed: `api/main.py` holds a module-level factory pointed at `backend/andersch.db`, a
test overrides the *dependency* and not that global, so a boot-time worker would poll the developer's real
database from inside the test suite — and execute a run it found there, which is a subprocess that can take
half an hour. A68 records what "every test run touched the real database" already cost once. The price of
binding late is stated in the code: a row left `submitted` by a dead process is picked up on the next submit
or the next listing rather than at boot.

**A defect ends the run, not the worker.** `engines.attempt()` deliberately re-raises `EngineOnRequestThread`
and `UndeclaredInput`, which is right for a caller who can see the traceback. A worker thread has nobody to
raise at, and letting one through would kill the loop and leave the row `running` for ever — the same defect
with the evidence deleted. So it is recorded on the row as a defect in andersCH rather than an engine
failure, by exception *type* and not by message.

### What a goal returns now, and what it refuses to return

**No trajectory, because a trajectory needs two numbers nobody has published.** `initial_wealth` is not in
the plan at all — `Position.magnitude` is a flow in francs per year or a share of a total, never a stock
(A30) — and `annual_return` needs one blended rate the AssumptionSet deliberately does not carry.

**What is offered instead is the arithmetic the published set genuinely supports:** the range of one-year
outcomes per macro scenario, for the roles the member's own funding occupies, applied to the amount the
member named. Against the real set, a CHF 250 000 goal funded by one growth position comes back as five
scenarios from −35.8 % to +9.7 %, each with the change in francs, the amount after the horizon, and the
scenario probability *as published beside it and never multiplied into it*.

**The horizon is not extended, and that is the discipline this whole change turns on.** The set carries
rates for **one** year, because a ten-year per-state return is not a one-year return compounded — the
regime does not persist for ten years. The goal in the example is dated 4.75 years out. Both numbers travel
in the payload with `rates_extended_to_the_goal_horizon: false`. Compounding that rate over the member's own
horizon is the single easiest invented number in the build, it would have looked like exactly what the owner
asked for, and a test plants it.

**Ten inputs were refused rather than defaulted**, each with the reason `services/engine_inputs.py` already
gives, carried into the payload verbatim rather than summarised: `initial_wealth`, `annual_return`, `W_L`,
`W_R`, `D`, `E`, `mandate`, `stream`, `events`, `months_observed`. Four of the seven engines are therefore
refused at `POST /api/runs` with their gap list attached — **and the refusal is the product**, not a
shortfall: it names which of the member's own inputs is missing, so a screen can say what to fill in rather
than "engine unavailable".

**Every reason a goal gives is now derived.** `no_assumption_set_published` may be returned only when the
table is genuinely empty; a set published with a future `effective_from` gets its own word, and so do a goal
with no amount (R-132's normal case), a goal with no active funding (R-030), a set with no role profiles,
and funding whose roles the set does not publish.

**A69's role-name mismatch is mapped here, explicitly, for the first time.** The estate's ReturnSet calls
the first role `gain`; §4 and `models.plan.ROLES` call it `growth`. A69 said whatever mapped them first must
do it explicitly. `PLAN_ROLE_TO_SET_ROLE` is checked against `ROLES` **at import**, so a fifth plan role
cannot silently fall out of every illustration, and both names travel in the payload so a reader can see
that a translation happened.

**One stale reason was corrected while passing.** `engine_inputs.RETURN_IS_AN_ASSUMPTION` said a return
"comes from a published AssumptionSet" as though none existed. One does. The gap is real and the kind is
still right, but what is unpublished is not the set — it is a blended annual rate. The string now says that,
because a gap whose stated reason has quietly gone stale is the same defect `goals.py` was carrying.

### C-03 at runtime, which the existing test could not reach

`test_no_engine_artefact_served_over_http` checked three static things: the mounts, the bundle, and the API
package's imports. It could not see a payload assembled at request time, and there are two new ones. So
`services/served.py` holds the runtime half: both builders assemble from a named allowlist, then
`strip_artefacts` removes the published-artefact keys and `assert_no_engine_artefact` **raises** if one
survived. It raises rather than filtering, because a payload that got here carrying an artefact key was
built wrong and filtering it would hide that. Done on the way **in**, so the stored row, the HTTP poll and
the R-154 export are covered by one pass. `replay` is on the marker list: not an artefact, a route to one.

**Two things in that test were wrong and are now narrower and honest.** It matched the *strings*
`andersch.engines` and `from ..engines` anywhere in a file, so a docstring explaining why a module must not
import the engine façade failed the test that the module must not import it — the same false-positive class
that made a `"blended"` substring check fail on prose explaining that no blended rate is published. Both
are AST or field-name checks now. And its stated claim — "the API package never imports the engine façade" —
was about to become false: the queue must reach an engine from somewhere the application can start, so
`api/main.py` reaches it transitively through `services.runs`. What layer 3 still holds is that no API
module can *name* `call_engine`. Layer 4 covers what it gave up.

### Verification

**Thirty-one violations were planted, one per guard, and every one was caught.** Three were not, on the
first pass, and all three were defects in the tests:

  * `test_the_empty_table_is_the_only_route_to_no_assumption_set_published` called the illustration builder
    directly, so **re-planting the original bug left it green** — the defect was never in the arithmetic, it
    was in the wiring, and the test now crosses the wire through `list_goals`;
  * the C-04 log test opened its capture around the worker only, so a payload logged inside `queue` was
    written before the window began;
  * one plant was itself wrong — it changed a signature rather than the logged dict — and proved nothing
    either way.

That is three tests that would have shipped looking like guards and holding nothing, found by the practice
A66 stated and A68 restated. **A real defect was also found this way**: the C-03 reduction sat outside the
worker's `try`, so an artefact surviving the strip killed the loop and left the row `running` instead of
failing the run.

The migrated schema was diffed against `create_all`'s and is byte-identical. The migration runs its DDL
through `op.create_table` on the migration's own connection; nothing reaches for `.engine` and there is no
`batch_alter_table`, so no trigger is dropped (A63, A66, A68). And a real `market_signal` run was queued,
executed off the request thread by the worker, and polled back in 188 ms — with `regime_timeline_id`, `raw`,
`replay` and the artefact absent from what was stored.

### Carried, not fixed

* **R-303 logs the member's values, not just their reference.** `engines._log_call` strips the member
  *reference* from an engine payload and logs the rest at INFO — which is R-303 exactly as written. A goal's
  target amount and a horizon read off the member's own date are not references, so they appear in that
  line. The queue adds no log line beyond ids and status. Changing what R-303 means is a specification
  question with an owner and is not taken here.
* **The client shows none of this yet.** `client/` was another agent's this session and was not touched. The
  illustration is in the `/api/goals` payload and `/api/runs` is live; the screens that render them are the
  next step, and the caveats are emitted as stable keys rather than sentences precisely so the wording lands
  in the client's content files beside every other string (A12).
* **`engine_runs.status` has no CHECK constraint**, because `sa.Enum` on SQLite does not create one by
  default and every other enum column in this schema is the same. Consistent rather than better; a
  storage-level guard on the status vocabulary would be a deliberate, separate change across all of them.
* **No curator-facing run route.** `portfolio_optimiser` is refused outright under C-01 rather than gated on
  a session nothing can open. Whether a curator may run the optimiser for a member is a second question, and
  A81's rule applies: a permission added on purpose is reviewable, one left behind is not.


## A86 — Five defects the owner found by using the application

*Owner: Nicolas · 2026-08-31 · cost: two routes, one service function, nine goal templates, 98 tests*

Not an audit's findings. The owner installed the thing, used it, and reported five in their own words. Four
were features that had been decided and not built; the fifth was a question that asked for the wrong thing.

**1. "English vs German Version - where can I switch" → "Make a switch in the browser".** There was
nowhere. A12 shipped both languages in phase 0, A26 put the switch on `Member.locale`, A81 closed the
chrome's translation gap — and no route could write the column, so every seeded member was `de-CH` and
`STRINGS.en` was complete and unreachable. `PUT /api/settings/language` and a two-button switch in the
header.

**A26 is amended, not overturned.** It said "no per-screen switcher: the authenticated product is not the
place for chrome that exists for the twenty seconds a year someone changes their mind about language."
That reasoning is sound and it answers the wrong question: those twenty seconds are the moment the control
has to be *findable*, and a setting nobody can find is a setting nobody has. What A26 actually decided —
one setting, on the column that already exists, applied server-side to every content lookup — is untouched.
Only the door moved. The switch offers `de` and `en` and is built from `i18n.js::languages()`, so it cannot
offer `fr` or `it`, which have refusal texts on the server and no interface at all.

**2. "This Question is unclear: Wofür ist das Geld da? ... Auf welches finanzielle Ziel arbeiten Sie hin
would be better."** The owner's wording, adopted verbatim, and the reason is the part worth keeping:
*what is the money for* invites an expense — a kitchen, a car — and an expense stored in a `Goal` is not
what a `Goal` models. *What are you working toward* asks for the thing the model holds. The question also
stopped asking for "Jahr und Betrag": onboarding never stored either, so "Wohneigentum 2031" was becoming
the goal's **name**.

**3. "There is only one Vorlage Mutgeld ... when in the onboarding the system ask for a goal, then we should
immediately fill that goal out."** `GOAL_TEMPLATES` held `courage_money` and `unspecified`, so the owner's
own "Frühpensionierung" was stored as `unspecified`. Nine templates now, **Frühpensionierung first at the
owner's request**, seven of them the options of `goal_kinds` in the estate's own
`questions-onb-0.1.3.json` — the wording from three real interviews. The goal question offers them and
writes the template onto the `Goal`.

*Three judgements inside that.* **"Einfach den Standort bestimmen" is deliberately not a template**: it is
a reason for using andersCH, not a thing money is for, and a goal no position could ever fund is a
completed onboarding wearing a goal's clothes. **No template carries a figure** — C-02, and the AHV
material is exactly why: a Vorbezug age, a reduction per month and a minimum contribution are all
published, dated numbers that belong where their `Stand` travels with them, which is
`content/knowledge/ahv-*.md`, not a one-line purpose. The one substantive claim any template makes is the
one the AHV material calls the most commonly mis-assumed: drawing the pension early does not end the duty
to contribute. That is a statement of statutory duty and A83 admits it. **A plain-string answer still lands
as a name with no template**, because every answer stored before today is one, and mapping one onto a
template would be choosing for the member from a sentence they typed for a different question.

**4. "Wachstum menschliches Kapital -> Betrag in welcher Frequenz?"** The form asked for a Betrag and did
not say per what. Two decisions that were each defensible and wrong together: the unit selector was hidden
until an amount existed, and `chf_per_year` was first in the list and therefore preselected. **A default is
an inference** — the quietest kind, because nobody sees it happen — and R-120 says the unit is never
inferred. The selector is on screen from the start, nothing is preselected, an amount without a unit is
refused, and the hint says to convert a monthly figure. The goal screen had the same defect in a line
reading `Zielbetrag: 250000`; the label now says CHF and the figure is formatted.

**5. "If I have a Ziel, I can not change it afterwards."** True: `/api/goals` carried `GET` and `POST`, and
`services/goals.py` had no function that wrote to a `Goal`. **The decision was what changing one should
mean**, because two of the estate's guarantees pull opposite ways here.

*The choice: an in-place UPDATE with a correcting `Decision`, not a superseding row.* Four reasons, and
`revise_goal`'s docstring carries them:

* **The model already says a goal is mutable, and says it deliberately.** `db.py`: "`positions` and `goals`
  carry no append-only trigger (they are legitimately mutable, which is the point of C-09)." An append-only
  `Goal` would leave C-09 guarding nothing.
* **R-040 is a property of `Decision`, not of every table.** "A correction is a new record referencing the
  prior one" is honoured where R-040 puts it: `corrects_id` on the new Decision, the prior one untouched and
  undeletable at the storage layer.
* **A superseding-row scheme fails invisibly.** Six read paths would each have to filter for the current
  version, `goal_funding` points at a goal id so funding would have to be copied forward every time, and the
  one that forgot presents as "andersCH has doubled my plan".
* **A vault item is a document and a goal is an intention.** The earlier version of a document is evidence
  and has to survive; a revised intention has one current form. What has to survive is the record *that it
  was revised*.

**What that costs is paid rather than waved off.** An UPDATE loses the prior values, so both states go into
the Decision — in C-06's own label/consequence shape, the two options the member actually weighed, plus a
machine-readable `values` map so the earlier state is readable rather than reconstructable. **A revision
that changes nothing is refused**: a Decision saying a change happened when none did is permanent under
R-040 and makes S-07 less true, not more complete. **There is no delete**, and that is a decision — nothing
in the specification says what removing a goal means for the Decisions that reference it, and answering
that in a form is how a member loses the record of a decision they made.

**One real defect came out of running the client rather than reading it.** A DOM harness drove the language
switch end to end, and the announcement to `#live` never arrived: every surface announces itself when it
finishes loading, four of the five route handlers are async, and the language change was announcing *before*
the screen behind it had settled. So a member using a screen reader heard the position count and never heard
that the language had changed. `route()` returns its handler's promise now and `changeLanguage` awaits it.
No static test would have found that — the code reads correctly either way and the symptom is audible only.

**Every guard here was planted before it was trusted** — 27 violations, each observed red and restored, plus
a live uvicorn run of all five paths on a throwaway database, in the order the desktop icon starts them.


## A87 — C-01 was reading the wrong vocabulary: advice about a member's own plan was not advice

> **WITHDRAWN 20 September 2026.** C-01's vocabulary fix for advice about a member's own plan. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31 · found by building the Befund*

Every rule that needs "something financial to direct" was reading `_INSTRUMENT_PATTERNS`, a lexicon of
market instruments. A directive aimed at the member's **own plan** therefore had nothing to conjoin with,
and all seven of these reached a member untouched:

    Sie sollten eine Position als Deckung dieses Ziels hinterlegen.
    Sie sollten dieses Ziel streichen.
    Für dieses Ziel wäre ein liquideres Gefäss besser.
    Am besten füllen Sie die leere Zelle zuerst.
    Von den beiden Möglichkeiten ist die erste für Sie die geeignetere.
    You should record a position for this goal.
    Your plan is on track.

Each is a personalised recommendation, which is the whole of what C-01 forbids. **A member cannot tell that
advice about a fund is refused and advice about their own goals is not** — from where they sit, both are
andersCH telling them what to do.

Found because the Befund is the first surface to discuss a member's plan at length. Three adversarial
rounds on C-01 had all probed *investment* advice, so the gap was invisible to every one of them: the
probes and the lexicon shared an assumption.

Three additions, each closing a different miss:

- **`_PLAN_OBJECT`** — `Position`, `Ziel`, `Deckung`, `Gefäss`, `Zelle`, `Plan`, `Rolle` and their
  translations, folded into rule 2's object test.
- **A demonstrative pointing at the member's plan** counts as member-direction. `Für dieses Ziel` is drawn
  about them as surely as `für Sie`; the goal is theirs and no other member's goal is under discussion.
- **German comparatives carrying an adjective ending.** `\bgeeigneter\b` does not match `geeignetere`, so
  an inflected form walked past a rule written for the uninflected one. Safe without a second conjunct
  because rule 3 consults that list only once the sentence is already member-directed.

**The false-positive direction was checked first, because that is the direction that breaks the product.**
`Keine erfasste Position ist als Deckung dieses Ziels hinterlegt` and `Für dieses Ziel ist keine Position
hinterlegt` — the Befund's own factual copy — still pass. The whole 1 742-test suite passes, including the
Befund's 83 tests, whose `Fact` constructor runs every sentence through this gate.

**One test correctly failed and was updated rather than deleted.** `test_derive.py` pinned the measurement
of which shapes the shared gate misses, in both directions, and said in its own docstring that if
`boundary.py` grew, whoever saw the failure could retire the local pattern *with evidence*. Two of its four
recorded misses are now caught. The local patterns are kept: a closed-set scan over a module's own copy
table is a different guarantee from a blacklist over model output.

## A88 — Two guarantees that could not fire, and the fourth backspace byte

*Owner: Nicolas · 2026-08-31*

**R-301's runtime guard had never been called.** `mark_request_thread` existed and no code in the
application invoked it, so "no engine runs on a request thread" was enforced at runtime by nothing. The
queue now holds R-301 **structurally** — there is no path from a route to a synchronous engine call — which
is worth more than a check. That is the fourth guard found installed and inert: C-04's filter (A71), the
`ANDERSCH_DB_URL` migration test (A68), A81's token test that matched `member_for_token(` with the
parenthesis and so missed an import, and this.

**C-07's word filter missed German inflection.** `punkte` is whole-word matched, so `Ihr Haushalt erreicht
74 von 100 Punkten` walked past the gamification list entirely. `punkten`, `punktzahl`, `rangliste`,
`ränge`, `bestenliste` and `abzeichen` are now on it. The bare stem `punkt` is deliberately not: it is the
ordinary German word for a decimal point and for an item on an agenda, and forbidding it would fire on
ordinary prose the way bare `level` would. Found by probing the filter, not by reading it.

**And A20's hazard landed twice more, both times inside a sentence describing it.** A78's entry contained
`<BS>beste<BS>` where it meant `\bbeste\b`; the repair of that was followed, within the hour, by writing
`<BS>punkte<BS>` into the comment explaining why `\bpunkte\b` was insufficient. Rendered, both read as
almost the right thing, which is why neither was caught by reading.

`test_no_tracked_text_file_contains_a_control_byte` now scans every tracked text file — proven able to fail
by planting a byte — and it caught the second one within a minute of being written. Four occurrences in one
day is not a coincidence to be noted; it is a shell that cannot be used for this purpose, and the guard is
the only durable answer.

## A89 — Five real curators had credentials and nowhere to use them

*Owner: Nicolas · 2026-08-31 · found by trying to sign in · cost: one service function, one route, one
dependency split, two client modules, 41 tests*

The owner typed `nicolas@kurator.andersch.local` into the login screen and got *"email or password is
incorrect"*. The address was right, the account existed, the password was the one
`tools/seed_demo_accounts.py` prints. **The member login screen reads `credentials`; curators live in
`curators` (A40), and there was no curator login screen anywhere in the client.** The whole workbench
surface had been built in phase 5, tested, and left unreachable by any person.

**The vague message is correct and is unchanged.** A wrong address, a wrong password and an address that is
not a curator's are one 401 with one body, and `authenticate_curator` derives against a throwaway salt so
the two take comparable time — who curates for andersCH is not a fact to be enumerated at a login prompt.
`test_the_two_halves_of_a_refusal_are_one_message_over_http` pins it, and it is the one test in the new file
that would have to be *deleted* rather than edited for the wording to become helpful. The defect was the
missing screen.

**The second defect, found while fixing the first: `Curator.must_change` was a flag nothing could read.**
All five real curators are seeded with it set, and the seeding script prints "each good for ONE login"
beneath their passwords. There was no service that could clear it, no route that could change a curator's
password, and no dependency that refused a credential carrying it. So the documented passwords worked
forever, and the column's own comment — which says the field exists precisely so that "good for one login"
is not a false statement on an operator's terminal — was describing behaviour no code implemented. Three
things closed it: `services.curator.change_curator_password`, `POST /api/curator/password`, and the
`authenticating_curator` / `current_curator` split that mirrors `api/auth.py`'s member pair. Two routes take
the outer one; every workbench route takes the inner one and answers 403 with
`curator_password_change_required`. `reset_curator_password` marks the flag too now, which
`services.auth.operator_reset` has always done for members.

**The current password is required in the body even though HTTP Basic has already carried one**, and that is
not redundancy. The member route's reason applies — `must_change` means somebody else set this password and
the person at the keyboard is supposed to know it — and one more is specific to Basic: a browser or a proxy
replaying a cached `Authorization` header supplies no typing, so a route trusting the header alone would let
a cached header rewrite a password.

**The door on the member screen is one sentence and one quiet link, not a second form.** Five people in the
world need it and everybody else has to read past it. A second pair of credential fields beside the member's
would put a choice in front of every member on their way in, and would invite exactly the confusion the two
tables exist to prevent: a member typing their own address into the curator half and being refused by a form
that looked like it was for them. The link is `.definition-toggle`, the client's existing quiet text
treatment — so this added **no CSS at all**, which is why it needed no new entry in
`test_client_accessibility.py::INTERACTIVE_SELECTORS`, and a test now fails if a `.curator*` class appears.

**What a curator can do, and what they cannot, stated because the screen has to state it.** A40 issues no
token and this work did not invent one. `POST /api/curator/login` returns an identity and
`session_token: null`; `client/app/curator.js` holds the credential **in memory for one window** — never
`localStorage`, never `sessionStorage` — and every request re-authenticates. A reload signs the curator out,
and `curator.no_token` says so on the screen rather than leaving them to discover it. **Whether a real
workbench needs a curator session table is a decision for the owner and is not taken here.**

**The landing screen is shaped by R-210 more than by anything else.** A curator cannot browse: every read
beneath `/api/curator` consults a live, scoped grant or raises. So the screen shows the worklist the server
composes from live grants, the scope vocabulary from `GET /api/curator/grantable`, and — for a curator whom
nobody has granted anything, which is all five of them today — a sentence saying that and that there is no
way past it. An empty table there would have read as "no members exist" or as a search box waiting to be
typed into. R-213 is held by holding nothing: `surfaces/curator.js` declares no module-scope state at all,
`app/curator.js` contains no scope, grant, worklist or expiry, and the reload control re-reads rather than
re-renders. C-10's one writing control says beside itself, before it is pressed, that it appends to a log
that cannot afterwards be changed.

**One real defect came out of running it rather than reading it.** `api.js` attached the member's bearer
token unconditionally, so a curator signing in on a machine where a member was also logged in would have had
their Basic header overwritten — and the route answers 401 to a member token. On screen that reads as *"email
or password is incorrect"*: the owner's own report, reproduced by the fix for it. The header is now attached
only when the caller has not set one, guarded on the caller's header rather than on a list of curator
prefixes.

**A20's shape, three more times, and all three inside tests written to obey A66.** Three of 27 planted
violations did not fire: a substring test for `curator.nothing_granted` over a whole file stayed green when
the notice was emptied (the key is also passed to `announce`); a count of `renderCurator()` calls stayed
above three when the dispatch was deleted from `route()`; and a plant that passed `body.new` as `current` was
not the violation at all, so the test was right to stay green. All three assertions are scoped to the branch
or the function they are about now, and all three fail under the same plants.

**And a fourth kind of quiet wrong answer, in the test helpers rather than in a test.** Every client scanner
in this suite strips `/* ... */` before `//`, so a **line** comment containing the sequence `/*` starts a
block-comment match that runs to the next `*/` and eats the code between. Writing ``under `/api/curator/*` ``
in a header comment silently deleted the imports and two functions from what one test could see. Found
because the assertion that noticed happened to be about a constant in the deleted region. The client is clean
of the pattern now and **there is a test for it** — `test_no_line_comment_in_the_client_contains_a_block_
comment_opener`, proven able to fire by putting the sequence back. It is a guard on the other guards rather
than on the product, and it is the same class as the four inert ones A88 records.

*A fifth backspace-class incident, for the record, and it was this paragraph.* The sentence above was
written into DECISIONS.md through `python -c "..."` from bash, and bash read the backticks around the test
name as command substitution — so the name was replaced by the empty output of trying to run it as a
command, leaving `**there is a test for it** — ,` on the page. The rule in A88 is not only about
heredocs and `\b`: **do not pass prose through a shell.** Repaired with an editor.

**One test was amended rather than worked around.** `test_the_client_sends_no_member_id_anywhere` forbade the
wire name in every client module. `POST /api/curator/workbench/sessions` legitimately names the member in its
body, because the caller is a curator and not that member — the exception `test_no_guarded_route_accepts_a_
member_id_from_the_caller` already records on the server side. `app/api.js` is allowed exactly one
occurrence, and the test then requires that one to be inside `openWorkbenchSession`. A blanket file exemption
would have let a second one in beside it.

**Verified live**, in the order `desktop/run.py` starts things, against a working copy of the real database
so the owner's file was never written: 31 HTTP checks including the real seeded curator's login, the
must-change refusal, the change, the documented password dying, a real member's scoped grant appearing on the
worklist, the consultation's audit row, and the revocation refusing the next read. Then 47 more through a DOM
harness that drives the actual surfaces — both languages, the wrong password, the mismatch caught in the
browser, the forced change end to end, and a curator signing in with a member session already stored. The
real `backend/andersch.db` is byte-identical afterwards (sha256 checked) and all five documented passwords
still verify, still good for their one login.

**Still open, and stated plainly.** There is no curator session table, so there is no way for a curator to
stay signed in across a reload, and nothing in this work is a workbench a curator could hold a consultation
in — the landing screen opens a recorded session and shows what a member shared, and stops there. Notes,
recommendations and closing a session all exist behind `/api/curator` and have no surface. Both are additions
somebody can make deliberately; the second needs the first, and the first is the owner's decision.


## A90 — The audit, and what it says about the shape of the build

*Owner: Nicolas · 2026-08-31 · an agent asked to check every identifier in the specification*

117 identifiers checked — 10 constraints, 78 requirements, 14 screens, 7 non-goals, 8 decisions — plus
§10's nine phase gates and §11's nineteen named checks. **86 built, 23 partial, 6 not built, 2 deliberately
not built.**

The finding that matters is not any single item:

> **The backend is close to complete and unusually well guarded. The product a member can touch is about
> six screens of fourteen.**

Every one of the ten constraints is enforced where the document says to enforce it. What is missing is
almost entirely **screens over finished servers** — and in four places a server that works makes a promise
the product cannot keep:

- **S-07 Decisions has no route and no screen.** R-160 is the only identifier in the document with zero
  references anywhere in the code. The spec calls this "the thing that survives a change of adviser".
- **No consent is ever captured** (R-103), so R-230's "consent history visible and withdrawable" returns an
  empty list for every real member, and C-05's "sole data controller from the first intake question" has no
  artefact behind it.
- **Erasure has no route.** `erase_member` is complete, tested, and reachable only from tests; the
  deletion route records a Decision and returns `executed: false`.
- **A member can neither grant nor revoke curator access** — there is no client function for grants at all,
  so R-210 and R-213 are unreachable in both directions.

And one stale reason worth naming: `api/learning.py` withholds the capability route "until D-01 has an
owner". D-01 was answered the same day. Because no route records a `CapabilityAssertion`,
`POST /api/marketplace/applications` refuses **every real member** with a 403.

**`client/status.html` was the most consequential artefact in the audit.** It told the operator *"All eight
phases are built and their gates pass"*, and was wrong in five places — including listing D-01, D-02 and
D-04 as "not ours to decide" on the day all three were answered. It is served at `/status`, and nobody
re-reads a page that says everything is fine.

It now carries a **Server** column and a **Screen** column, because "done" against a phase whose screen
does not exist is what made it misleading rather than merely out of date. It also now names the open
wrong-law problem, which it had omitted while marking phase 4 done.

## A91 — Two more guards that could not fail, and one that could not see

*Owner: Nicolas · 2026-08-31*

**The client's forbidden vocabularies were weaker than the server's, under a comment claiming parity.**
`test_client_bundle.py`'s mountain list said *"matching the backend's list"* and omitted `hut`, `berg` and
`tour` — two of which principle 10 names explicitly — while its C-07 list was missing `points`, `punkte`,
`score`, `badge`, `rang` and `xp`. Nothing was leaking: every occurrence in the client sat inside a comment
and both scanners strip comments first. That is luck, not a guarantee.

Both halves now import one `tests/vocabulary.py`. The same defect as A73's export-versus-erasure lists and
A63's two-stores-one-fact: **two lists that must agree, maintained separately.** Topping up the shorter one
would have left the next divergence free to happen; the fix is that divergence is no longer expressible. It
immediately caught a real word in `status.html`.

**`test_no_guarded_route_accepts_a_member_id_from_the_caller` had never checked a request body.** It read
`parameter.annotation` and asked for `model_fields`, but every module begins `from __future__ import
annotations`, so the annotation is the *string* `'PositionRequest'` and the attribute is never there. The
signature half worked; the half that would catch `member_id` arriving in a **body** was inert from the day
it was written — on the constraint that closed the application's only authentication hole. It resolves the
hints now, carries a `resolved > 20` guard on itself, and was proven by planting `member_id` on
`GoalRequest` and watching it name the route. Sixth guard here found unable to fail.

**And a defect in the test helpers themselves.** Every client scanner strips `/* … */` before `//`, so a
line comment containing `/*` — as in a comment mentioning `/api/curator/*` — deletes everything up to the
next `*/` from what those scanners can see. It silently hid a whole surface's imports and two functions
from every client guard at once. Now caught by its own test.

**The shell hazard reached five and six.** `
` in a heredoc produced an unterminated string literal in a
test file, and separately prose with backticks passed through `python -c` let the shell execute a test name
as a command. The rule is no longer "escape carefully" but **do not pass prose or pattern source through a
shell** — use the editor tools. `test_no_tracked_text_file_contains_a_control_byte` catches the residue; it
cannot catch a file that fails to parse, which at least fails loudly.


## A92 — S-07 Decisions, and C-01 had no word for a decision

> **WITHDRAWN 20 September 2026.** C-01's handling of S-07 Decisions. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31*

R-160 was the only identifier in the specification with **zero references anywhere in the code**, on the
component §7 calls *"the thing that survives a change of adviser"*. Three routes now: the member's
decisions filterable by the position, goal or vault item they touched; one decision with its full
correction chain; and R-162's correction, recorded as a **new Decision referencing the prior one**.

**Vault links are ids only.** A `VaultItem` is K3 entity-wide, so including even its `kind` would raise the
whole payload from K2 to K3. The Befund makes the identical call, which is the agreement you want between
two things describing one object.

**`record_correction` was misattributing corrections.** It copied `author` from the prior decision, so a
member correcting a curator's decision produced a row **naming a curator who had not written it** — worse
than R-212's absent attribution, because a confident wrong one is not visibly wrong. Fixed additively.

**A member may correct a curator-authored decision.** R-040's "survives a change of adviser" argues they
must be able to: a record nobody can correct once the adviser has gone is precisely the thing that does not
survive. Reversible if that reading is wrong.

**And C-01 had no word for a decision.** A87 widened rule 2 from market instruments to the member's own
plan — Ziel, Position, Deckung, Gefäss, the grid cells — and left out the *record of a plan change*. So
`Sie sollten Ihr Ziel anpassen` was refused while `Sie sollten diese Entscheidung korrigieren` passed: the
same advice about the same act, one step further back, **on the one screen whose entire subject is
decisions.** That is A87's own failure repeating — there the probes and the lexicon shared an assumption
about *investment* advice; here they shared one about what counts as the plan.

Closing it took three edits, because the vocabulary was written down in three places, and the third was the
interesting one: the outbound comparative list covered "besser als" and "bessere" and left the plainest
form of all — a bare "besser" at the end of a sentence — uncovered.

The agent recorded it as a strict `xfail` rather than editing `boundary.py`, so closing it forced the
marker's removal instead of letting it rot. That mechanism is worth keeping.

## A93 — Consent is captured, and erasure is reachable

*Owner: Nicolas · 2026-08-31 · the wording needs the owner*

**No consent had ever been captured.** `Consent` rows existed only in tests, so R-230's "history visible
and withdrawable" returned an empty list for every real member, and C-05's "sole data controller from the
first intake question" had no artefact behind it.

Two purposes, both required, in a closed registry: **`datenbearbeitung`** and **`entscheidprotokoll`**.
`kuratoren_zugriff` was deliberately not added, because `AccessGrant` *is* that consent — per curator, per
scope — and a registry entry nothing reads is the defect A90 names.

**`purpose` is now a closed set**, enforced by `@validates` on the model so it holds for a row built in a
REPL. Three jobs it had been failing: R-230's history mixed incommensurable strings as if they answered one
question; withdrawal cannot have a consequence if no code can branch on the value, so a typo was
indistinguishable from a grant; and `purpose="datenbearbeitung", document_version="kur@2026-01"` was
storable nonsense.

**Deliberately no CHECK constraint**, and this is a place to decide otherwise if you disagree. A `Consent`
row must outlive the registry entry it names — R-230's question is exactly about a purpose no longer
offered — and a CHECK naming today's vocabulary is fired at every historical row by alembic's batch-mode
table copy, so retiring a purpose would fail the migration on the very history the constraint was written
to protect. A63 and A68 were both `batch_alter_table` casualties.

**Two things for the owner.** The wording is marked `PROVISIONAL` and the route says so: these are honest
plain-language descriptions written so the capture point could exist, **not** a DSG notice, and nobody
qualified wrote them. And the prior question is legal: **is `entscheidprotokoll` properly consent, or a
notice?** An append-only record that survives erasure is arguably necessary to the service rather than
something a member elects. It was captured as consent because the alternative was leaving the member never
told.

**Erasure is reachable.** A typed sentence — `ALLE MEINE DATEN LÖSCHEN`, case not folded — **plus the
member's own password**, both checked in the service rather than the route so a second route cannot skip
them. No boolean field, because pydantic's lax mode accepts `1`, `"y"` and `"on"` as true, which would have
made the deliberate-agreement field the most permissive input on the request. A token left open on a
borrowed laptop must not be enough to destroy a record.

Verified live on the running server, refusal paths only: wrong sentence 422, lowercase 422, `"true"` 422,
right sentence with a wrong password **403** — and the member still there afterwards.

**`GET /api/export` stays a plain read and does not write a Decision.** A GET must be safe: a prefetch, a
retry after a dropped connection, a proxy revalidation or a double-click each repeat it, and each
repetition appends to a table R-040 makes append-only — so S-07's screen would fill with export requests
the member never made and **there would be no removing them.** The *request* is the POST. A test pins both
halves so the two cannot drift into two formats. **Outstanding: the client still calls the GET.**

## A94 — The capability route, and R-005's gate becoming passable

*Owner: Nicolas · 2026-08-31*

Nothing recorded a `CapabilityAssertion`, so **`POST /api/marketplace/applications` refused every real
member with a 403** and the most heavily guarded module in the build could not be entered by anybody. The
route was withheld "until D-01 has an owner"; D-01 had been answered that morning.

`evidence_kind` is a **server constant**, not a request field: `record_assertion` takes free text, which is
right for a caller who knows what happened and wrong for a browser, because `capability_review` renders it
straight back — so a free-text kind is where "level 3" gets stored *and displayed*. `assessed_by` is
`member:<id>`, because naming andersCH would be andersCH vouching for a statement it never examined: the
claim of accredited standing R-194 forbids, made in a column rather than in copy. `evidence_ref` may only
name a learning unit whose own content record evidences that capability; an uncorroborated reference is
refused, because a reference that does not hold reads as corroboration.

**A74's property now holds on real data for the first time.** Until today `capability_evidence` was
permanently 0, so the fee test was proving a fee could not move an order that was two-thirds constant.
Measured through the routes with two real members: on a single-role query the specialist wins on share; on
all four roles the shares **tie at 12/12 and the order falls to capability evidence, 3 against 1**;
unfiltered, evidence decides alone. That is exactly what A74 argued and could previously only prove as
arithmetic.

**Deactivating a position is its own act, on its own route** — beyond A86, and argued: the Decision says
something different (an edit corrects what a position *is*; deactivating changes what the **live plan** is,
and the Befund, the illustration and the derivations all stop counting it), a boolean in an edit form is how
a member deactivates by accident, and `active` is therefore refused **by name** rather than ignored.
Reactivation exists, because R-122 does not say the mark is one-way and one-way makes a mis-click permanent.

## A95 — Three more filters that could not see, one of them mine

*Owner: Nicolas · 2026-08-31*

**A word boundary does not break at an underscore.** So a pattern for "count" never fires inside
`asserted_count`, and one for "score" never inside `my_score` — and a **payload key** is exactly where a
tally word arrives underscore-joined. Found by an agent planting `"asserted_count": 1` and watching the
shared filter pass it: a plant meant to prove the filter fires, proving the opposite.

**My first fix was too blunt and I reverted it.** Splitting on the underscore for every caller broke two
legitimate identifiers immediately, and one is instructive: **`not_indexed_by_profession` is a key that
exists to assert the absence of the forbidden concept**, and splitting it made the filter forbidding that
concept fire on the statement that it is absent. `cell_filled` is the other — "filled" is forbidden as a
*tally* (`filled: 3, total: 8`), not as a statement that one cell holds something. So prose and identifiers
are two scans now, and a caller has to say which it is doing.

**A duplicate dict key is silent in Python, and two agents produced one within the hour** — both adding
`position_id` to `PATH_VALUES` while wiring different routers. Harmless here because the values matched, but
the failure mode is that the second entry wins with no diff to see. Now caught by reading the source rather
than the dict, because by the time the dict exists the duplicate is gone.

**And a stale test pinned a stale file.** `test_the_content_file_defines_no_rung_scheme` required
`learning.json` to say `rung_scheme_open_decision: "D-01"` — so the content file *could not be corrected*
without the test failing. D-01's prohibition is unchanged; what changed is that `rung_scheme` is null
permanently rather than pending. Correcting it also tripped the same test's own copy filter on the word
*grades*, in a note explaining that andersCH does not grade anything.

**The shell rule, restated because I broke it again while writing this entry.** Passing this prose through a
bash heredoc failed on an apostrophe, and earlier today the same channel turned a pattern into a backspace
byte twice and let a backtick execute a command once. The rule is not "escape carefully": **prose and
pattern source do not go through a shell.** Write the file, then move it.


## A96 — A correction chain ordered by the clock, and a guard that was flaky about a flaky bug

*Owner: Nicolas · 2026-08-31*

The chain in S-07 sorted on `(created_at, id)`. Three decisions written inside one microsecond — every
test, and any correction a member makes quickly — tie on `created_at` and fall through to `id`, which is
random hex. So the chain came back in a different order on different runs: two failures in five. On a real
database it means **a member's correction history could reshuffle between two page loads.**

A correction chain already carries its own order, because each record corrects the one before it. `depth`
counts links from the root and cannot tie. `created_at` now orders only two corrections *of the same
record* — genuinely concurrent, and the one place a clock is the right answer — and `id` remains last so
the result is total rather than merely usually total.

**The interesting part is what it took to guard it.** The first replacement asserted the invariant — each
record follows the one it corrects — which is the right property and, with the defect restored, **failed
only one run in six**: a probabilistic guard against a probabilistic bug, which is not a guard.

Two attempts to force the collision failed, and both were informative. Stamping the rows with one
timestamp afterwards was refused by `DecisionImmutable` — R-040 blocking a test that tried to edit a
Decision, that guard being real rather than decorative. Freezing `utcnow` with `monkeypatch` did nothing,
because the column default captured the function object at class-definition time and patching the module
name afterwards cannot reach it.

What worked: passing `created_at` **at construction** (R-040 forbids changing a Decision that exists, not
writing one with a stated timestamp) *and* pinning the ids to sort against the lineage. Without the second
half the defective sort still landed on the right order about one run in six, purely by where three random
ids fell. With both, the plant fails eight times out of eight.

Both tests are kept: the invariant one says what must be true, the constructed one makes the failure
certain. The second does one thing a member never does — building Decision rows directly — and that is the
price of a guard that does not depend on luck.

**And the shell claimed a seventh victim, inside this very entry's neighbouring comment.** Two words in
backticks were passed through bash and executed as commands, leaving `"guard.  first and  last makes"` in
the source. The rule stands and I keep breaking it: **prose and pattern source do not go through a shell.**


## A97 — The decision record is a notice, not a consent

*Owner: Nicolas · 2026-08-31 · answered: "notice is sufficient"*

A93 built consent capture with two required purposes and flagged the legal question rather than deciding
it: **is `entscheidprotokoll` properly consent, or a notice?** An append-only record that survives erasure
is arguably necessary to the service rather than something a member elects.

The owner answered: **a notice is sufficient.**

That is the more defensible reading, and the reason is worth stating so nobody re-litigates it. A member
cannot use andersCH without their decisions being recorded — R-040 and C-10 make those rows undeletable at
the storage layer, and R-231 empties them rather than removing them. So presenting it as a choice they
could decline was misleading: there is no version of the product where declining is honoured. They must be
**told**, and telling them is what a notice is.

So registration asks for consent to **`datenbearbeitung`** and *tells* the member about the decision
record. Nothing writes a `Consent` row for the notice.

**What was deliberately not built.** No table, no migration, and no per-member record of the notice having
been displayed. "Sufficient" was a request for less machinery, not for a second kind of ceremony wearing a
different name — and a row asserting "we told them" is a consent record with the honesty removed. The
wording is published, versioned and K0, and that is the whole of what a notice needs.

**Two things this does not change.** The wording stays marked `PROVISIONAL`: these are plain-language
descriptions written so the capture point could exist, **not** a DSG notice, and nobody qualified wrote
them. And `purpose` stays a closed set with no CHECK constraint, for A93's reasons — a `Consent` row must
outlive the registry entry it names, and a CHECK naming today's vocabulary is fired at every historical row
by alembic's batch-mode table copy, so retiring a purpose would fail the migration on the very history the
constraint exists to protect.

**One thing to watch.** The development database may already hold `entscheidprotokoll` consent rows written
yesterday. A row naming a purpose that is no longer a consent is *exactly* R-230's case — a purpose no
longer offered — so the history has to say something true about it rather than dropping it silently. That
is the first real exercise of the reason the CHECK constraint was refused.

---

**Built the same day. One registry, two `kind`s.** `consent.py` holds one tuple of purposes and each one
says whether the member is asked (`"consent"`) or told (`"notice"`). Splitting them into two modules would
have produced two lists that must agree, which is the defect A73 and A91 both are. The one combination that
cannot be expressed is a notice marked required at registration — refused in `Purpose.__post_init__`,
because every other test in the file *derives* from `required_at_registration`, so flipping that one field
would have had registration demanding acceptance of something nobody may decline while the suite stayed
green.

**Where the notice reaches the member.** `GET /api/consent-statement` carries both purposes with their
`kind`, plus `notices`, `notices_are_not_a_choice: true`, and an `echo_at_registration` naming the consent
alone. `GET /api/settings/consents` grew a `notices` block reading the same registry — because a member who
registers from now on has **no row** for the notice, so a settings screen built from rows would mention the
processing they agreed to and never mention the record that cannot be deleted. No table, no migration, no
row asserting it was shown.

**What R-230 shows for a row written yesterday.** It stays in the list — they *were* asked, on a date, to a
version, and that is the question R-230 answers. Three fields now come from the registry rather than the
row: `kind` is `"notice"`, `withdrawable` is **false**, and `consequence` says why there is nothing to
withdraw and why an agreement to it is still listed. Leaving `withdrawable` true was the worst outcome
available: a button offering to revoke a record R-040 makes undeletable, with `required_at_registration:
false` beside it, reads as *optional, and you may take it back*. `POST .../withdraw` on such a row is a
422 from the service, not the route, so a second route cannot skip it — marking `withdrawn_at` would write
a revocation that cannot happen into a column.

**Where the "no row for a notice" rule is enforced:** `verify_acceptance` refuses one offered as a consent
(422 naming it, rather than dropping it silently — a form still sending it is a form still showing a
checkbox for something nobody may decline), and `register_member` refuses one handed to it directly, which
is the only function in the application that constructs a `Consent`. **Not** on the model validator: rows
naming `entscheidprotokoll` exist, and a validator refusing the key would leave them readable — `@validates`
does not fire on load — and unwritable.

**Eleven plants, ten caught first time.** The eleventh was A93's ordering plant, re-run: the first attempt
passed `consents=(consents := verify_acceptance(...))` in the call's argument list, which *looks* like the
check moved behind the write and is not, because Python evaluates arguments before calling. Everything
passed, and a plant that changes nothing reads exactly like a guard that cannot fail. Planted properly —
member and credential written first, consent checked after, no rollback — **six of the seven** refusal
shapes went red; the seventh is the absent field, which pydantic refuses before the route body runs. The
five refusal messages now go through `boundary.check_answer` too, because a route hands them to a member
as an HTTP detail.


## A98 — `CuratorSession.curator_id` is a foreign key, and what that cost in the development database

*Owner: Nicolas · 2026-08-31 · cost: one migration, one pragma in `env.py`, three corrected rows, six test files*

A40 said `curator_id` "becomes a foreign key rather than a free string". A67 recorded that this was true of
`AccessGrant` and **false of `CuratorSession`**, and deferred the work because three agents were reading the
affected test files. It stayed deferred. It is done now: `curator_sessions.curator_id` references
`curators.id`, indexed, in the model and in migration `5dcf92664790`.

**Why this column and not another.** `curator_session_events` refuses UPDATE and DELETE by trigger, and
every event references its session. So a wrong curator on a session is not correctable by the means
everything else in this build is correctable by — the child rows that name the act cannot be rewritten and
cannot be removed. A constraint that has to hold *before* the row exists has to live in the storage layer.

**The migration refuses rather than repairs, and that is the decision in it.** A session naming a curator
who is not a row cannot be fixed by any rule: it cannot be deleted, and pointing it at *some* curator writes
a new false statement into an audit in order to satisfy a constraint whose only purpose is that the audit be
true. So `_refuse_sessions_naming_nobody` stops the upgrade and prints the ids, and a human decides per row.

**What was decided about the three rows in `backend/andersch.db`.** They carried `curator_id =
'curator:nb'` — a placeholder written on 30 August while the Curator button was being exercised by hand,
all three against one member, from `know_panel:vault` and `know_panel:containers`. They now name **Demo
Kuratorin**, the seeded curator, on A67's own reasoning: she *is* a row, and a session naming her is true.
That is exactly what those three rows are — a demonstration session nobody held. Pointing them at one of the
five real curators was rejected: no consultation with any of those people ever happened, and there is no
version of "make the audit satisfy its constraint" that is worth writing a colleague's name into a
consultation they did not hold.

**The original string survives, and that matters.** `curator_session_events.actor` still reads
`'curator:nb'` on all three, because that table refuses UPDATE. So the correction is visible by comparing a
parent row against its own event rather than hidden by it. The database was migrated, not recreated: six
curator sessions, six append-only events and twenty-four members all still there, `PRAGMA foreign_key_check`
clean, six triggers. A copy of the file as it was is at `backend/andersch.db.before-fk`.

**A third hazard, found by running the migration on real data rather than on a fresh file.** Alembic's batch
mode rebuilds a table by copying it, **dropping the original** and renaming. `DROP TABLE` with foreign keys
enforced performs an implicit `DELETE FROM`, and `curator_session_events` points at every row of
`curator_sessions` — so the migration failed on the development database and passed on an empty one. **This
is A68's shape a third time**: the path with rows in it was the path nothing took. `migrations/env.py` now
turns enforcement off for a migration run and runs `PRAGMA foreign_key_check` on the finished result inside
the transaction, so a violation rolls the whole upgrade back and names the row.

Two traps were measured rather than reasoned about on the way there, and both are recorded in `env.py`
because the next person will reach for exactly them:

  * `PRAGMA defer_foreign_keys=ON` looks like the transaction-safe answer. SQLite switches it off at every
    COMMIT, and a migration that has only run SELECTs and DDL is in autocommit — so it is switched off by
    the implicit commit of the statement that set it. It appears to work and does nothing.
  * setting the pragma through `connection.exec_driver_sql` **silently discards the entire upgrade**. Any
    statement through the SQLAlchemy `Connection` autobegins its transaction; `context.begin_transaction()`
    then sees a connection already in one and returns a context that commits nothing. Every migration ran,
    alembic reported success, and the file on disk was unchanged. It is done on the DBAPI cursor instead.

**The service layer resolves too, and the reason is not belt-and-braces for its own sake.**
`services/know.open_curator_session` — the opener underneath the Curator button, and the one A67 left taking
its id on trust — now calls `resolve_curator` first. The foreign key alone would refuse an invented curator
as an `IntegrityError` naming a column, which tells a caller nothing about what it did wrong. A63's lesson
is that every constraint here has two enforcement points precisely so one failing is not silent; this is the
one that produces a sentence.

**A gap left open and stated plainly.** `test_adversarial.py::test_no_migration_rewrites_an_append_only_table_without_restoring_its_triggers`
scans for migrations that batch `decisions` or `curator_session_events`. It does not cover
`curator_sessions`, which is the *parent* of an append-only table — this migration batches it and the
tripwire is silent by construction. Covered here by
`test_a_migrated_database_actually_refuses_to_rewrite_a_curator_session_event`, which checks the property
rather than the source, but the source scan's set is one table short and that file was out of scope to edit.


## A99 — Three payloads that carried a decision nobody could read

*Owner: Nicolas · 2026-08-31 · cost: one field, one route, three tests*

Three findings that turned out to be the same finding: something was decided, recorded, and then not put
anywhere a screen could reach it.

**`GET /api/positions` omitted `liquidity`.** The grid payload carried every other field
`PATCH /api/positions/{id}` can change, and not that one — so the position edit form could not show a member
which band their own position holds and had to render an additive "leave unchanged" selector. Meanwhile
`services/goals.py` reports `liquidity_not_stated` about that same position under R-031. The product named a
gap, built a route to fill it, and hid the current value. `time_basis` and `started_on` were checked for the
same defect and did not have it. The rule is now stated as a rule and tested against
`POSITION_REVISABLE_FIELDS` rather than against a list of field names, so the next field added to the edit
route is covered without anyone remembering the test.

**C-04: no change of class.** `Position` is K2, no column on it declares a higher class of its own, and
`liquidity` is a band the member stated about their own holding. The payload was K2 before and is K2 now.

**The four band names were deliberately not added.** `GET /api/goal-templates` already serves them as
`liquidity_bands`. A second copy inside a member-scoped payload is a second place for an authored list to
drift.

**D-07's phrase had one key and no reader.** A22 promoted the specification's §1 phrasing into
`client/content/destination.json` and added a test scanning the backend to make sure nothing inlined it. The
test passed — because nothing said the phrase at all. `content.destination()` had no production caller and
appeared in no payload. **An absence-shaped test passing over an absence**, which is the fourth time this
build has been bitten by that shape (A20, A63, A66, A68). `GET /api/destination` serves it now, in both
languages, with no fallback for a third: one route, one content function, one file, and D-07's "one key" is
a key something reads.

Its own route rather than a field on an existing payload, and that is argued rather than convenient. D-07's
reason for one key is that this is the phrase most likely to be revised and the one a template would most
naturally inline; a route for *the* phrase means every screen asks the same URL and a reviewer finds one
place. Folding it into the grid payload would have made it a field two screens read and a third copied.

**R-232's statement was reachable and read by nobody.** `GET /api/settings/data-classes` derived the whole
thing from the model layer and was already an open route with an HTTP test; what it did not have was a
consumer or a field-by-field contract. A screen renders it now, and a test requires every key that screen
resolves — a field dropped from the payload would have left a blank line beside a category rather than an
error. Checked by planting: removing `holds_member_material` leaves
`test_the_api_states_the_data_classes` green, because "the route returns categories" is true of a payload
missing most of its fields.


## A100 — The seeding call that nobody made, and why the demonstration did not work

*Owner: Nicolas · 2026-08-31 · found by a re-audit counting rows rather than reading code*

`services/learning.py::seed` and `services/marketplace.py::seed` were both complete, idempotent, and well
tested. **Nothing called either of them outside the test suite.** No startup hook, no operator command,
nothing in the distribution installer.

So on the database the desktop icon actually opens:

- `capabilities`, `learning_units`, `providers`, `listings`, `disclosures` and `member_offers` held **zero
  rows** against 24 members;
- S-10 listed ten capability statements read from the *content file*, and pressing any of them returned
  **503 — "no capability … in the store. Run `seed` first"**: a server error naming a command that did not
  exist;
- with no `CapabilityAssertion` possible, **R-005's gate refused every real member** — which is exactly the
  condition A94 records as fixed;
- the Market Place was empty over a payload that worked perfectly.

Every function involved was correct. What was missing was the **call**, and no test could have found it,
because every test seeds its own fixture. It was found by counting rows in the shipped database.

`tools/seed_content.py` closes it. Verified end to end afterwards: Market Place 0 → **15 entries**, the
assertion route 503 → **201** with `rung: None` and `andersch_assesses_capabilities: False`, and
`POST /api/marketplace/applications` → **201**, so R-005's gate is passable by a real member for the first
time. The tool does not repair existing rows, on `learning.seed`'s own reasoning: a member's assertion
points at a capability id, and restating a statement under an id somebody has already been assessed against
changes what their assertion means.

**Still empty, and not seeded: `gatherings`.** `services/community.py` has `create_gathering` and no seed
function, so S-13 remains a screen over an empty table. Inventing gatherings would be seeding events that
never happened, which is a different thing from seeding published content — so it is recorded rather than
filled.

**The lesson is the shape, not the fix.** This is the same class as A99's destination phrase — a content
record nothing read, while a test confirmed nothing had inlined it — and as A90's screens over finished
servers. Three times now the defect has been *an artefact that exists and is never reached*, and none of
the three was visible to a test suite. The question that finds them is "what does the shipped database
contain", and it is not a question any test asks.

## A101 — C-01 refused the modal and passed the imperative

> **WITHDRAWN 20 September 2026.** C-01's modal-versus-imperative round. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31 · the third repetition of one failure*

`Sie sollten Ihr Ziel anpassen` was refused. **`Passen Sie Ihr Ziel an` passed** — the same advice, in the
stronger mood, about the member's own plan. For an *instrument* both moods were caught.

The cause: the clause-initial imperative patterns are keyed to a list of **money-move verbs** — kaufen,
verkaufen, investieren, wählen. A87 and A92 widened the **object** vocabulary to the member's own plan
twice, and neither widened the **verb**, because every probe in both rounds used a modal. Third time the
probes and the lexicon have shared an assumption; the first was about investment advice, the second about
what counts as the plan, this one about how advice is phrased.

**The German half is closed by matching the shape rather than a list.** The polite imperative is infinitive
+ `Sie`, clause-initial, so no verb list is needed and the next verb somebody writes is covered. Modals and
auxiliaries are excluded, because they form questions: `Haben Sie Ihr Ziel erreicht?` is not advice.

**Two false positives cost a test each and both taught something.** `Wenn Sie einen ETF kaufen, zahlen Sie
eine Courtage an die Bank` — after a comma, German verb-first is as likely to be a conditional's main clause
as an imperative, so the generic pattern is anchored at the start of a sentence where the keyed lists can
afford the comma. And `Fragen Sie Ihre Pensionskasse nach dem Vorsorgeausweis` is the most useful sentence
this product can write.

**The English half cannot be closed here, and that is a finding rather than a shortfall.** Adding the plan
verbs immediately refused `Record a position`, `Change this goal` and `Record the goal` — **button labels**.
English forms its imperative bare, so a label and a command are the same string; German keeps labels
infinitive (`Position erfassen`), which is why the shape works there. C-01 is handed strings and does not
know a label from a sentence, and refusing the labels to catch the advice would leave the product unable to
name its own controls — the worse failure of the two.

So English bare-imperative plan advice still reaches a member. It is declared in `/api/health`'s
`known_gaps` as `C-01/imperative` with a strict `xfail` behind it, and the guard that requires every
declared gap to have a failing test caught the mismatch when the key and the reason did not yet agree.
Closing it needs the label/prose distinction to exist somewhere other than inside this gate.


## A102 — A101 had a hole on the day it landed, and the model writes advice with nobody in it

> **WITHDRAWN 20 September 2026.** The hole A101 left on the day it landed. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-08-31 · found by a second audit running real questions through apertus:8b*

**A101 closed the German imperative and left a gap in its own object list.** `Überprüfen Sie Ihren Plan` was
refused; `Überprüfen Sie Ihre finanzielle Planung` passed, because `plan` was matched whole-word and
`Planung` is not `Plan`. German derives where English inflects. The rule was hours old when this was found.

**And a whole class of advice had no rule at all.** Every rule until now needed either a speaker (`ich
würde`, `wir empfehlen`) or an addressee (`Sie sollten`, `Passen Sie`). An **impersonal** construction has
neither — and it is the shape the local model actually reaches for:

    Es ist ratsam, sich an einen Finanzberater zu wenden.
    Kann es sinnvoll sein, die AHV-Rente früher zu beziehen?
    Es ist auch sinnvoll, private Rentenversicherungen zu berücksichtigen.

The second recommends when to draw a state pension. The first sends the member to an **external adviser**,
which is the one referral this product exists not to make. All three reached a member untouched.

Rule 2b conjoins an impersonal advisory with a financial or plan object — rule 2's shape with the addressee
removed. Two word-order variants cost a probe each: one optional adverb between copula and verdict (`es ist
AUCH sinnvoll`), and the inverted question form (`Kann es sinnvoll sein`), which is precisely how a model
softens a recommendation into a suggestion.

The object set gained the things a Swiss answer about money is *about* — `Rente`, `Versicherung`,
`Vorsorge`, `Guthaben`, `Berater`. Not instruments a member picks from a shelf; a pension is not selected.
Declarative prose is unaffected, because rules 2 and 2b need a directive or an advisory beside the object,
and the entire authored corpus says `Rente` and `Vorsorge` throughout without being refused.

**`Es ist sinnvoll, die Steuererklärung früh einzureichen` still passes, and must.** C-01 forbids the
*personalised* recommendation, and the object is what makes a sentence about this member's money rather
than about a deadline.

## A103 — The wrong-law risk is worse than recorded, and was the one thing missing from the board

*Owner: Nicolas · 2026-08-31 · the largest member-facing risk in this build*

The OPEN entry recorded the Know surface stating pension law wrongly with correct citations, "about one run
in three". An audit measured it against apertus:8b with the real index: **it reproduced in 3 of 3 runs, and
no run stated the correct fact** — the word *Zuschlag* never appeared. A second question was worse: a
five-point list of „Punkte, die Sie berücksichtigen sollten", a recommendation about when to draw a pension,
a referral to an external Finanzberater, and figures quoted out of an internal manual as though they were
AHV law.

**C-01 passes all of it, correctly.** The boundary asks whether an answer *advises*, not whether it is
*true*. The numeric faithfulness check asks only whether each figure appears in the cited passages — and
these figures are real and misapplied. Every guarantee in the build held, and the member was told the
opposite of the law by a system showing its sources.

**It was disclosed in `DECISIONS.md` and on the operator page, and absent from `/api/health`'s
`known_gaps`** — a direct breach of A65, the practice this build congratulated itself for one day after
writing it. The audit found the omission by checking the board against the record rather than by reading
either. It is on the board now as `S-08/truth`, with a strict xfail behind it that uses the boundary alone,
so it does not depend on the model being installed or on which of three runs it produces.

Closing it needed an entailment check or extractive-only answers, and the owner chose **extractive-only**
on 2026-09-01 — recorded in A106, which resolves the OPEN entry this one was waiting on. The board entry
was narrowed rather than removed: what closed is the member-facing route, not the boundary's blindness.

**The shell claimed its ninth victim in this entry.** Passing this prose through `python -c` let bash
execute every backticked word as a command. The rule has been written down three times and broken nine:
**prose and pattern source do not go through a shell.** Write the file, then move it.


## A104 — Consent withdrawal: soften the wording, not the behaviour

*Owner: Nicolas · 2026-09-01 · answered: "notice is sufficient" for the record, "soften the wording" here*

Withdrawing consent to `datenbearbeitung` wrote `withdrawn_at`, returned 200, and **changed nothing** —
verified: login still succeeded afterwards and every member route answered 200, including a fresh vault
upload. The consequence shown before confirming said andersCH may no longer process the member's entries
and that *"an account cannot continue without it"*.

Two ways to make that true. **The owner chose the wording.** The behaviour stays: a withdrawal is a record,
not a gate.

That is defensible and worth stating rather than leaving as an omission. An automatic revocation on a
single click makes a mis-click destructive on the one screen where a member is thinking about their rights,
and the product already has a deliberate, confirmed path out — the erasure, behind a typed sentence and a
password. What the withdrawal does is put the question to a person. So the sentence now says the withdrawal
is recorded with its date and the version of the wording shown; the account and the entries stay;
processing does not stop with the click; andersCH settles what follows with the member; and if the data is
to be removed, the erasure is the way.

**It must not overstate in the other direction either.** A text saying only "we have noted this" would
leave a member believing nothing had been registered. Both failure modes are pinned by tests: one plants
the old sentence back, one plants a version that says only that nothing happens.

**Nine docstrings asserted a consequence that did not exist** — in `consent.py` (five sites),
`services/registration.py`, `services/settings.py`, `api/remainder.py` and `models/member.py`. The last also
claimed "withdrawal is a new row", which was never true: `withdraw_consent` only sets a column. That
`withdrawn_at` is a record and not a gate is now stated as the intended design, so the next reader does not
have to work out which of the two the code means.

**One thing left standing, deliberately:** `consent.required` on the *registration* screen — „Ohne diese
Zustimmung entsteht kein Konto." — is **true**, and stays. It was the settings-screen twin that was false.

## A105 — A market return rate was being applied to a salary

*Owner: Nicolas · 2026-09-01*

`services/illustration.py::_funding_roles` grouped a goal's funding by `Position.role` and **never read
`capital_type`** — a grep for it returned nothing. So a goal funded by a human-capital income position got
the ReturnSet's `income` market profile applied to the member's stated salary: measured, `rate -0.0593 →
change_chf -14825.0`, with no caveat and no mention of human capital anywhere in the payload.

**This was one click off the default path.** Onboarding gives every member exactly one position — `role:
income, capital_type: human` — and the containers form offers it in the funding multiselect. Zero of the
nine illustration fixtures used human capital, which is why it survived.

Principle 9's testable form is *"a summary component that accepts only financial inputs"*. The owner chose
to restore it: only financial capital gets a market rate.

A goal funded **only** by human capital returns no figure and its own reason,
`the_goal_is_funded_only_by_human_capital` — not `the_goal_names_no_active_funding`, which would have been
A85's false-reason defect repeated, since the goal *is* funded. Mixed funding projects the financial part
and lists the salary under `excluded_from_the_projection`, which travels on **every** goal payload including
the empty case, so no client infers anything from its absence. Excluded, never zeroed.

**One test exists purely to keep the others honest.** The old `RATES` fixture published no `income` profile,
so a salary-funded goal fell out through a *different* reason and looked handled — which is exactly how nine
fixtures missed this. `test_the_income_profile_would_reach_a_salary_without_the_filter` fails if that ever
becomes true again.

An import-time contract now fails the module if a third `capital_type` is ever added, rather than letting
it fall silently into whichever branch was written first.

**And a test that would have started failing at midnight.** `test_the_empty_table_is_the_only_route_to_no_assumption_set_published`
compared a payload built from the real `date.today()` against one pinned to 2026-08-31, so it passed only
while the wall clock agreed. Found in passing on the last day it could have been found by accident.

## A108 — The household is a table, not a column, and it is never backfilled

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 6*

Until this change the build was single-subject. `Position.member_id`, `Goal.member_id`, and nowhere to put
"we are two" — `tools/load_submission.py` had already recorded the consequence from the other end, with
`children_count` sitting in `NO_FIELD_HOLDS_IT` under the reason "no household model in this build". A real
submission's answer was read, reported, and dropped.

Item 6 of the update script needs a household for four separate things: `household_as_of` on every plan
version, a twelve-month currency horizon on composition, the seventh goal field (`whose goal it is`), and
the closing rules on separation. All four were unbuildable.

**Three tables, and no column on any existing table changes.** `households`, `household_members`,
`goal_owners`, plus the two decision-link tables C-09 needs. Every row that existed before the migration is
valid after it.

**Nothing is backfilled, and that is the decision.** The obvious alternative was to put `household_id` on
`members`, `positions` and `goals` and give every existing member a single-member household.
`households.composition_as_of` carries the date a member says their composition describes; inventing one —
today? their registration date? — writes a K2 fact whose source is the migration, and the twelve-month
horizon would then expire against a date no human ever gave. C-02's argument about invented rates is the
same argument about an invented date, which is worse only in that it looks more innocent.

So a member acquires a household when they answer the question. Until then `services/household.py` returns
`None` and `describe()` says `stated: false`. An unstated composition is a gap; a guessed one is a fact.

**`Household` and `HouseholdMember` are `PlanMutable`.** Composition sets the AHV path, the tax path, goal
ownership and the human role vector — changing it is a material change to the plan, so C-09 applies and the
guard in `db.py` enforces it rather than this module's manners.

**`goal_owners` is a link table rather than a nullable `owner_id`,** because ownership is genuinely plural:
a goal owned by both partners is the normal couple case and it is the case with consequences. On a closing,
singly-owned goals follow their owner and jointly-owned ones are frozen and flagged for division. A column
would have to encode "both" as a sentinel, and a sentinel in a foreign key is how the division case gets
discovered by a member rather than by a test.

**It names a `household_member`, not a `member`,** so a partner with no account can own the goal that is
about them. `HouseholdMember.member_id` is nullable for the same reason: refusing to model a partner until
they register would make the couple case wait on an invitation flow the build does not have.

**`kind` is stated, never derived from an age.** A 19-year-old in an apprenticeship is a dependant in one
household and an adult in the next. Deriving it would be a threshold, and a threshold is an assumption
nobody has published.

## A109 — Erasure redacts a household membership; the export carries the whole composition

*Owner: Nicolas · 2026-09-03*

`household_members` carries a `member_id`, so the export/erasure completeness guards caught it immediately
— three tests failed the moment the table existed, which is those guards working exactly as intended.

**The treatment chosen, and why.** The row names the erasing member, so R-231 must take their name off it.
But the row is *also* the other member's statement about their own household — "we were two adults as of
March 2027" — and every plan version that household produced is stamped against that composition. Deleting
it would silently rewrite a second person's stated history, leaving their `household_as_of` describing a
household that, according to the database, never had two people in it. **One member exercising erasure may
not edit another member's record.** So `HouseholdMember` joins `Decision` and `CuratorSession` in
`REDACTED_IN_ERASURE`: `member_id` goes to NULL and `label` is replaced with the standard redaction
marker. The composition stays true and nothing in it identifies anybody. A single-member household ends up
holding one anonymous row, which is the honest result — somebody stated a household and then left.

**What is not decided, and is the owner's call.** Whose personal data a partner's `label` is. If a member
writes "Anna" for their partner, that string is at once the member's own record and personal data about a
third party who has no account and gave no consent. Two consequences hang on it:

1. The export currently gives a member **only their own row**, through `owning_predicate`'s `member_id`
   match. So a member who stated "me, Anna, and Lena" exports one row and cannot see the composition they
   themselves described. That narrowness is deliberate until the question is answered, not an oversight.
2. If a partner's label is the partner's data, an unregistered partner has data in the system and no way to
   reach it — which is a question for the same ruling.

**Ruled on 3 September 2026: keep the label, and give the member the whole composition they stated.**
They authored it, so R-154 hands all of it back — an export that returned one row would not show a member
what they described. The erasure treatment above is unchanged: they may read rows they do not own and may
not destroy them.

**That breaks `owning_predicate`'s stated invariant, so the break is named rather than hidden.** That
function's docstring promises one definition for both the erasure and the export, and it is right for
every table but this one. A boolean parameter would have made the erasure's behaviour depend on an
argument a future caller forgets to pass, and the failure would be silent and in the direction that
destroys a third party's data. So there is a second, named function — `readable_predicate` — over a table
of models with a written reason each, `READS_WIDER_THAN_IT_ERASES`. A test asserts the two disagree on
exactly the models that declare it, and a plant proves that test can see an undeclared widening.

**What is accepted and recorded rather than solved:** an unregistered partner has personal data in the
system — the label the member wrote for them — and no way to reach it. That is the residual, it follows
from modelling a partner before they have an account, and the alternative (option 2 at the time: store
only "adult 2") was rejected because it costs the couple case the legibility the division flow needs.


## A110 — The validity horizons are a content record, not a published assumption table

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 6*

Item 6 requires every input class to carry an age and a validity horizon, and sets household composition's
at twelve months. Twelve is a number, so C-02 applies: no literal rate or horizon in application code.

**The engine-seeded stream was the wrong home.** `services/assumptions.py` composes an `AssumptionSet` by
*reading* two engine runs and refuses to compose any value of its own — it will not even blend a rate,
because "which probabilities weight which horizon is a modelling decision with an owner". A horizon decided
editorially by a person has no place in that stream, and `current()` returning one row ordered by
`effective_from` means a second publication stream in the same table would shadow the first.

**Three options were on the table:** a new published `InputHorizonSet` table parallel to `AssumptionSet`;
extending `AssumptionSet` with a second editorial stream; or a K0 content record. The owner chose the
content record. `client/content/` is already where this build keeps K0 values a person decided and can
review — `roles.json` carries its source document, the date it was read, and a `provisional` flag — so the
mechanism exists and is the one a reviewer already knows.

**The cost of that choice, and what was done about it.** A content record has no database identity, so a
Befund fact resting on one has `source: "content"` and owes no `assumption_set_id` — there is no column
carrying an author. So `published_by`, `decided_on` and `effective_from` are recorded inside the file's
`_about` block, `content.horizon_provenance()` reads them, and the Befund carries them in its `currency`
block. A value nobody stands behind is the defect C-02 exists to prevent, and changing the mechanism does
not change that requirement.

**It fails closed.** `content.horizon_months` raises `HorizonNotPublished` for an input class nobody has
published a horizon for, and `services/currency.py` contains no number at all — a grep test plants
`months = 12` and fails. An unpublished horizon means the currency of a finding cannot be judged, and the
honest response is to say so; treating the input as never expiring would present a stale figure as
standing, which is the exact defect item 6 closes. `currency-horizons.json` lists the five classes that
will need one and have none, so an absence is visible rather than assumed.

**The third state is the Household Optimiser's, not a new one.** A fact `stands` or it
`could_not_be_determined`. There is deliberately no `stale`, `expired`, `warning` or `needs_review`: those
name the member's problem to fix, and Principle 4 forbids the nag. A test asserts the vocabulary is exactly
two values.

**The degraded sentence replaces the composition rather than annotating it.** Past the horizon the report
does not say "two adults as of March 2027" with a warning beside it — it states the date, the horizon and
that whether the household is still as recorded could not be determined, and the counts are absent from
`values` entirely. A figure with a caveat next to it is still a figure the member will act on, which is the
failure item 6 names.

**And `certified` is not the word.** The update script says a plan "cannot be certified"; NG-04 reserves
that word for the SIM Research credential, and the guard on member-facing strings caught it in an error
message. The code says "cannot be presented as standing". The collision is worth avoiding on its own
merits: a plan figure is not a qualification.

## A111 — A plan version is a numbered baseline, and its household stamp is copied rather than joined

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 6*

Item 6: *"Every plan version carries a `household_as_of` stamp, so the app can state 'this plan assumes a
two-member household as of March 2027.'"* There were no plan versions.

**It closes a gap the build had already recorded against itself.**
`services/engine_inputs._scenario_generator` left `base_snapshot_id` absent with the reason *"prototype2
has no Snapshot. The plan is Position and Goal with a Decision behind every mutation (C-09), which is a
history rather than a numbered baseline"*, and the Befund reported that to the member as
`numbered_baseline`. So the same object answers both: `PlanVersion`.

**A version freezes stated inputs, not a rendering.** Positions and goals as the member stated them, at the
granularity the engines read; no computed figure, no illustration, no sentence. A frozen *output* would be
a figure whose assumption set nobody can trace, which is what C-02 exists to prevent, and a rate published
later has to remain applicable to an old baseline or *"you are eight months behind the plan you made in
March 2027"* cannot be computed at all.

**`household_as_of` is COPIED at capture. This is the decision, not an implementation detail.** Joining it
through `household_id` at render time would mean a member restating their composition in 2029 silently
rewrote what the March 2027 plan is recorded as having assumed — every past version would quietly agree
with the present. That is the exact class of quiet wrongness item 6 exists to close, so a stamp that later
events can rewrite is not a stamp. `inputs` is copied for the same reason: positions are revisable, so a
baseline made of pointers would drift every time the member corrected a figure.

**Proposed → standing → superseded, because a re-solve may not silently win.** Page 1: *"A re-solve is
always proposed against the standing plan and never silently replaces it — adopting it is the member's
act."* So a capture arrives `proposed` and only adoption makes it standing. An unadopted proposal stays
proposed forever — not expired, not cleaned up, not auto-adopted, because an auto-adopting proposal is a
silent replacement with a delay. There is deliberately no `capture_and_adopt()`.

**Adoption writes a Decision naming its author, and that is what makes item 2 checkable.** *"A confirmation
from a curator does not carry forward to a re-solved plan."* Only checkable if each adoption can be asked
who made it — so `adoption_decision_id` is on the row, and a curator's release of version 3 says nothing
about version 4. `PlanVersion` itself is **not** `PlanMutable`: writing a version records the plan rather
than changing it, the same reasoning `EngineRun` states.

**"At most one standing version" is a database rule, not a service promise.** A partial unique index
(`uq_plan_versions_one_standing … WHERE status = 'standing'`) — partial because a plain unique index on
`(member_id, status)` would also forbid two *superseded* versions, which is the normal case after two
adoptions. A test reads `sqlite_master` to confirm the `WHERE` survived, and a second test proves the index
still allows many superseded rows.

**Two things that index and the CHECKs caught immediately, both worth recording:**

1. **SQLAlchemy's unit of work ordered the promotion before the demotion.** `adopt()` assigned
   `previous.status = SUPERSEDED` and then `version.status = STANDING` and flushed once; the UPDATEs went
   out ordered by identity, not by assignment, so the database saw two standing rows for the length of one
   statement and the index refused it. Fixed by flushing the demotion on its own. The general lesson: an
   index enforcing "at most one" catches a *transient* violation inside a flush, not only a final one.

2. **The erasure tried to null `superseded_by_id` and was refused.**
   `ck_plan_versions_superseded_names_successor` forbids a superseded version with no successor, and
   erasure is not a licence to write a row the schema forbids. The fix is to delete oldest first: the
   reference points forward, so the referrer always goes before the row it references. Foreign keys are
   enforced (`PRAGMA foreign_keys=ON`) and the generic erasure loop selects rows unordered, so
   `services/erasure` deletes these itself and `member_data` says so.

**The old gap reason was false the moment this landed, and that is a defect in its own right.**
`base_snapshot_id` is now filled when the caller passes a version and otherwise absent as
`supplied_by_the_caller` — the same kind as that engine's `field` and `to_value`, which the caller has
always named. A reason that outlives its truth is what A85 and A105 both are: the member is told something
no longer so and nothing fails. Consequences, both asserted: the Scenario Generator's refusal for a member
who has stated nothing now names `initial_wealth`, and the plan-blocking gap count for an empty plan falls
from 12 to 11 while the total stays at 21 — the gap was reclassified, not filled, which is precisely the
distinction asserting both numbers exists to catch.

## A112 — How a household change is learned, and what happens when one closes

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 6*

### Declared: the annual review's structured confirmation

Five closed items in `client/content/household-confirmation.json`, not a freeform prompt. A freeform "has
anything changed?" is answered "no" by everyone whose change was not on their mind that morning, and
household composition is exactly the input a member does not think of as financial.

**All no re-dates the same people, in place.** `composition_as_of` is updated on the same `households` row,
which resets the twelve-month horizon — and is why horizon expiry and the annual review are the same event
in the common case. No new household row: nothing about the household changed, the plan versions pointing
at it still point at the right thing, and each version carries its own copied `household_as_of`, so
updating rewrites no history. A test asserts exactly that.

**Any yes changes nothing.** A yes/no cannot say who joined, what they are called, or whether they are an
adult or a person in the member's care, so patching from one would write facts nobody stated. No Decision
is written either: the member said something changed and has not said what, and a Decision recording an
undescribed change would be a record of the wrong event. The open action item stays open, so the question
is still prepared at the next return.

### Inferred: a flag, and nothing else

`flag_inferred_change` creates an action item and touches no plan row and writes no Decision. `partner_invited`
firing does not make the household two adults; it makes the question worth asking. The signal set is closed
and published with, for each, whether this build can actually observe it — four of five cannot yet, and
each says why. An empty inference layer and a broken one look identical, and the reasons are the difference.

**This is the one derived kind whose cause is an event rather than a state**, so `derive_action_items`
cannot recompute it and never creates, closes or reopens it — `COMPUTED_TRIGGER_KINDS` names that exception
rather than leaving it as an absence in a dict. It is still in `DERIVED_TRIGGER_KINDS`, deliberately: that
tuple is what the C-01 outbound scan walks, and a kind excluded from it would have unscanned member-facing
copy. It is closed by `confirm()` or `state()` — the question having been answered is what resolves it —
and a dismissed flag is never re-raised by the same signal firing again.

### When a household closes

The five rules are implemented as item 6 states them, with one deliberate difference recorded below.

1. **Closed, not deleted**, with a closing date; every plan version made while it was open stays attached.
2. **Each adult with an account gets a new single-member household** naming the closed one through
   `succeeds_household_id`. An adult *without* an account gets none and is named in the report rather than
   silently skipped: there is no plan to show a person the product cannot authenticate.
3. **Shared history is frozen and readable by both — and nothing is copied to achieve it.** Item 6
   specifies copy-and-freeze. What is implemented is the guarantee rather than the mechanism, because in
   this build the guarantee already holds without duplication: plan versions carry their own `inputs` and
   their own `household_as_of`, `decisions` is append-only at the storage layer, and `readable_predicate`
   (A109) gives each member every row of every household they belong to, the closed one included. A second
   copy of immutable rows would be a second thing to keep in step, which is the drift this estate has paid
   for twice. **Recorded as a departure from the letter of the script so it can be overruled.**
4. **Goals owned by both are frozen and flagged, never split.** `Goal.frozen_at` is set, `revise_goal`
   refuses a frozen goal, and a derived item carries two prepared options, one of which names a curator.
   No arithmetic: dividing a goal needs a view of two people's preferences the planner does not have, and
   carries an emotional load a rule should not touch. A goal owned by one adult has its *ownership*
   re-pointed at that person's row in their new household — the goal itself does not move, because
   `Goal.member_id` already names one account and nothing should move it.
5. **Neither member sees the other's post-closing plan.** Structural rather than enforced: the successors
   are separate households, so A109's read rule gives each member their own successor and the shared closed
   one, and nothing of the other's afterwards. Asserted on a real export.

A single-adult household cannot be closed. It has nobody to separate from, and what that member wants is
either erasure or a restatement; closing would produce a successor identical to the record just closed.

### Two SQLAlchemy failures worth not relearning

Both were caught by existing guards, and both looked like bugs in the guard rather than in the calling code.

1. **`decision.linked_*.append(...)` can itself autoflush.** Appending to a relationship collection loads
   it first, and `before_flush` then sees a dirty `PlanMutable` object whose link has not landed —
   `PlanMutationWithoutDecision`, on a mutation that was about to be linked one line later. **Link before
   mutating, every time.**
2. **A mid-block autoflush writes the Decision, and every later link is then a modification of a written
   one** — `DecisionImmutable`, R-040. A closing links a dozen objects to one Decision, so the whole block
   runs under `session.no_autoflush` and flushes once. The consequence is that `new_id` has not run inside
   the block, so `Household.id` is unassigned there and the successors are collected as objects and read
   after the flush.

## A113 — The ask field's three branches, and the boundary that was being crossed to answer a question below it

> **WITHDRAWN 20 September 2026.** **Branch 3 only.** The three-branch router. Branches 1 and 2 survive as the two-branch router (A165); the advice refusal does not. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 1*

Item 1 requires the router to be "a named module with the three branches as an enum" and that "adding a
fourth branch requires touching one place". `services/router.py` is that module.

**C-01 did not move and was not re-implemented.** Branch 3 is exactly what `boundary.classify_question`
already refused, and branch 3's text is exactly `boundary.REFUSAL` — a fixed human-written string, per item
1's instruction that a reworded refusal can become advice. What the router adds is the split between a
question about the world and a question about this member, plus the permission that follows from it.

**Precedence is fixed and there is no score.** Advice first, then personal, then population. "Should I put
MY bonus in 3a" is both personal and advice, and it is branch 3. A router returning "0.7 personal" would
leave every caller to pick a threshold and the thresholds would disagree.

**One place, enforced.** A branch is an enum member plus a `BranchSpec`, and an import-time check fails the
module if one is missing. Everything downstream — whether member data may be read, which boundary was
crossed, what the client is told — is read off the spec. A test plants a missing spec and proves the check
fires.

### The finding: branch 1 was reading the member's vault

`services/know.ask` called `own_material` for **every** question, so "how does the AHV household cap work"
retrieved the member's vault items to answer a fact about the world. Nothing leaked — the corpus outscored
them or they did not match — but **the first regulatory boundary was being crossed to answer a question
that sits below it**, and "no member data touched" was not a true statement about the code.

**The fix needed a split by data class, not a flag.** `own_material` searched two quite different things in
one pass: the member's vault (K3, theirs) and `LearningUnit` (K0, the curriculum, identical for every
member). Withholding the pair from a population question would have withheld the curriculum from exactly
the questions the curriculum exists to answer. So it is now `member_material` and `learning_material`, the
curriculum is retrieved on every branch, the vault only where the route permits it, and `own_material`
survives as the composition of the two. A test replaces `member_material` with a spy and asserts branch 1
never calls it.

**Thirteen existing tests changed their question, and it is worth saying why that is not test-fitting.**
They use vault items as convenient passages while testing the answering machinery — selection, quoting,
citation markers, the cap, the outbound gate — and asked "Was ist ein Freizügigkeitskonto?". That question
is a fact about the world, and quoting the member's own bank statement at it is the behaviour item 1
removes. They now ask "Was steht in meinem Freizügigkeitskonto?", which reaches their own fixtures. The two
adversarial ones carry a comment saying so, because a test that passes on an empty retrieval is the
vacuous-guard shape that file exists to prevent.

### Branch 2 with an empty Vault names one input

Item 1: it "does not fail. It answers the population part of the question, then names the single input that
would make it personal, and offers to start there." The population part is answered from the corpus as
before; `missing_personal_input` adds the first missing thing in the intake's own order — household
composition, then a position, then a goal, which is also the light-intake floor.

**One, not a list.** Principle 4's shape applied to a prompt: a member told three things are missing has
been handed a backlog; a member told one has been handed a next step. The sentence is a fixed phrase from
the four-language table, composed by code — the same rule as the refusal, for the same reason.

### The post-hoc numeric check was already there, and a second one was written and deleted

Item 1 asks for it, and `services/know.unverifiable_figures` has done it since before this work: it runs
after generation, compares figure to figure rather than by substring, and treats `7'258` and `7258` as the
same number. A `services/figures.py` was written for item 1 before that was found, and **deleted rather
than kept** — a second implementation of a rule is the two-lists-that-must-agree defect A73 and A91 both
are. What item 1 asks for on this path was already true; what was missing was the router.

**Still owed on item 1 when this was written:** the product-comparison path's general/personal split, the
ask screen itself, and the source bar and caveat fold.

**Both of those first two are since closed, and neither by building them.** The owner dropped the
general/personal split on 3 September 2026 — a probe showed the inbound line already sits where the script
wants it, with a category comparison routing to `population_fact` and a for-me comparison to the curator,
without any comparison-specific code. And on 4 September 2026 the owner recorded that **the compliance
reviewer's pre-FINMA
read is no longer relevant**, so the "must not ship to production until the confirmation lands" caveat is
lifted. Nothing waits on it. Struck through here rather than deleted, so a reader of the original entry is
not left looking for a confirmation that is not coming.

## A114 — C-01 required the pronoun next to the modal, so the one forbidden sentence passed

> **WITHDRAWN 20 September 2026.** C-01's pronoun-adjacency defect. C-01 was withdrawn by the owner on that date; the reasoning is in **A160**, the deletion and its final measurement in **A164**. This entry is kept unchanged below it, because a reader tracing why the patterns are gone should land on the reasoning rather than on a gap.

*Owner: Nicolas · 2026-09-03 · found while checking where the product-comparison line sits*

The update script names one sentence as the thing that must never be said: *"you have CHF 88,000 in a cash
3a and you should move it."* **C-01's outbound gate allowed it, in three of four languages.**

Probed, not reasoned:

```
Sie sollten das Konto-3a umschichten.                                    REFUSED
Sie haben CHF 88'000 auf einem Konto-3a und sollten das umschichten.     ALLOWED
You have CHF 88,000 in a cash 3a and should move it.                     ALLOWED
Vous avez CHF 88 000 sur un compte 3a et devriez le transférer.          ALLOWED
Lei ha CHF 88 000 su un conto 3a e dovrebbe spostarli.                   REFUSED
You should move the money out of the cash 3a.                            ALLOWED
```

Two independent causes, and the Italian passed only by accident.

**1. Adjacency.** Every Sie-register and you-register pattern in `_DIRECTIVE_FORCE` requires the pronoun
beside the modal — `\bsie\s+sollten\b`, `\byou\s+should\b`. German, English and French all state the
subject once and carry it into a coordinated clause, so `… und sollten …` has no pronoun to match. Italian
caught it because its pattern makes the pronoun optional, which is the shape all four should have had.

**2. The object vocabulary was German-weighted.** Rule 2 needs directive force *and* something financial.
`move` was absent from the English money-move verbs — the German column had `umschichten` from the start —
and `3a` was matched only as `säule 3a` / `pillar 3a`, never as `Konto-3a`, `cash 3a` or a bare `3a`. So
"You should move the money out of the cash 3a" had the force and nothing to conjoin with.

**The fix is rule 2c: a deontic modal anywhere in a sentence that addresses the member, plus an object.**
A83's statutory-duty exemption sits in front of it exactly as it sits in front of rule 2, so `Sie müssen
das 3a-Guthaben spätestens mit dem Referenzalter beziehen` is still admitted. Third-person singular forms
are included — `Ihr Konto-3a, das Sie halten, sollte umgeschichtet werden` names no actor and is still a
recommendation, which is A102's finding arriving from a new direction.

**The `könnte` family is excluded from the detached rule, and finding out why took one test run.** The
first version refused this build's own empty-state copy: *"Sie haben noch keine Position erfasst, die ein
Ziel tragen könnte"* — a statement that no position is CAPABLE of funding a goal. German and English use
the same word for capability and for suggestion; `should`, `ought` and `must` do not. So the split is by
whether the word is ambiguous when detached, not by how strong it sounds, and `könnten`/`could` stay in the
adjacency rule where they really are advisory. Refusing the product's own copy is not a boundary working,
it is a boundary that gets turned off.

**Exposure, stated rather than implied.** This was not an active leak on the ask path: `know.ask` refuses
any sentence not quoted verbatim from a retrieved passage, so the corpus itself would have had to contain
the sentence. It matters because items 3 and 5 — the first-session finding and the content hooks — are
specified as **composed on the go** about the member's own figures, and they rely on this gate. Closing it
is a prerequisite for that work, not a tidy-up.

**Method note, because this is the fifth time.** A87, A92, A101 and A102 all widened this file after
probing, and its own docstring says the evasion list "was produced by probing, not by reasoning". That is
now five. The lesson is not that the list is nearly complete — it is that a co-occurrence rule keyed to
adjacency will keep failing on ordinary word order, and each fix should ask whether the SHAPE can be
matched rather than one more arrangement of it. Rule 2c matches a shape; the patterns it replaces matched
arrangements.

**Parallel implementations, checked.** `client/coach.py` in the root estate carries the other half of this
boundary and does **not** need the same fix: it generates no text — its answers are deterministic templates
— so it has an inbound `classify()` and no outbound scan at all. There is no drift risk between the two on
this rule, and the fix is prototype2's alone.

## A115 — The Curator button was two taps on a phone, and inside something that closes

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 2*

Item 2: the Curator button is "reachable in one tap from every screen. It is not a feature of the chat —
it is a product-wide constraint. It is never inside a menu, and its treatment is identical everywhere."

**What was there.** R-170 put the button in the Know panel's own header and reasoned that it is therefore
"present whatever else the panel is showing". That reasoning is correct and the conclusion held **only
while the panel is docked**. Below `know.js::DOCK_QUERY` the panel is a drawer behind a launcher, so on a
phone the route to a human was: tap the launcher, wait for the drawer, tap Curator. Two taps, and inside a
thing that can be closed — which is the definition item 2 rules out.

**The fix is a second entry point, not a second implementation.** `know.mount` now returns `openCurator()`,
and the chrome grows a button that calls it. The directory fetch, the ordering, the session write and
R-173's `opened_from` all stay in one place; a copy in `main.js` would have been the two-lists defect A73
and A91 both are, in a spot where the two copies would have disagreed about which screen they recorded.
A test asserts `main.js` neither fetches the directory nor posts a curator session of its own.

**In `.chrome-end`, not as a fifth door.** A door is a place you go; this opens a chooser over wherever the
member already is, and the session records the screen underneath it. `.doors` is what `aria-current` and
the print sheet both treat as the set of pages, so putting it there would have made it one.

**Also confirmed while checking: the persistent chat item 2 asks for already exists.** `main.js` mounts the
panel once, outside `ROUTES`, and calls `panel.sync()` on every route change — so the thread survives a
route change, which is item 2's first acceptance criterion. It was built for R-002 and happens to satisfy
this. Nothing was rebuilt.

**A plant caught a weakness in the new guard itself, which is the part worth recording.** The first version
of `test_the_curator_button_is_in_the_chrome_and_not_only_in_the_panel` asserted that the string
`curator-button` appeared in `main.js`. Planting a removal of the `prepend` left it **green**: the button
was constructed and never attached to the document. Defined is not attached, and asserting on a class name
is asserting on the definition. The test now requires the append itself, and the plant fails it. This is
A68's four absence-shaped guarantees in a fifth place.

## A116 — The question field is the landing screen, and it holds its own answer

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 1*

`#/ask` is the route a member lands on after sign-in. It was `#/plan`, the four-role grid, which page 2 of
Journey & Design rules out in one line: "nobody meets the four roles before they have entered data". Page 1
gives the positive case — the field "carries no member data, needs no intake, works in the first second,
and does not assume which journey the person is on".

**Nothing else above the fold.** Item 1 names four things that must not be there — no metrics, no cards, no
hero number, no onboarding prompt — and a test asserts the surface never imports `formatAmount` and never
mentions a score, a percentage or a progress figure. There is no heading either: a title would be the first
of that list to creep back. The answers container is appended AFTER the form, so an answer can never push
the field down the screen, which on a phone is the difference between asking a second question and hunting
for the box.

**The field behaviour is the LU OGD portal's, copied rather than invented**, as item 1 instructs. Multiline
growing to a cap and then scrolling; Enter submits and Shift+Enter breaks the line; the question stays
above the answer as "the only thing on the screen that came from the person". `event.isComposing` is
checked on the Enter binding — without it an IME submits the word the member was still spelling, which is
not in the script and is the same class of mistake.

**The answer is module state, and `render()` contains no call to the API.** Item 1: "Never recompute
silently on return: a second run can produce a different figure than the one the person already acted on.
Same rule as a re-solve never silently replacing the standing plan." `main.js` calls `render()` on every
arrival at `#/ask`, so a surface that asked on render would do exactly that. A planted `askKnow` in
`render` fails the guard.

**It is deliberately not persisted across a reload.** Surviving a route change is required; surviving a
reload is not, and an answer restored from `localStorage` would be a figure with no visible provenance that
looked as though it had just been computed. A reload is a fresh screen, which is honest.

**Three surfaces, one curator chooser.** The refusal's handoff calls `panel.openCurator()` — A115's chooser,
now reached from the panel, the chrome and the ask screen. A test asserts `surfaces/ask.js` contains no
`/api/curator` call of its own.

**The branch and the boundary reach the screen as sentences**, keyed from `services/router.py`'s own enum
and boundary tuple, so a fourth branch cannot ship without its copy. They live inside one collapsed fold
with the model name — several disclosures in a row are read as none, and none of it belongs in front of
somebody who just wants the answer.

**Not built, and named so it is not mistaken for done:** the source bar and fold follow the OGD portal's
*pattern* but not its screenshots, which the script says Nicolas has and this work did not. What is there
is a list of citations under the answer and one `<details>`; if the portal's treatment differs, this is the
place to change and no logic moves with it.

## A117 — The intake asks the household first, and records who drove it

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 3*

**Two of item 3's requirements were already met and nothing was rebuilt.** `services/onboarding.resume_point`
already resumes at the next unanswered question — R-101's per-question rows — and it is already named to
avoid a count, with its own docstring arguing that "a function called progress is an invitation to add a
count to it, and R-113 forbids the count". Item 3's "never state a question count" and "resumable at any
point" were therefore standing before this work.

**Household composition is `order: 0`**, ahead of the four questions that were there, which keep their
numbering and the wording they were refined with. Item 3's reason is the one on the question itself: the
AHV path, the tax path and goal ownership all hang on it, and it is the only input the system cannot notice
changing.

**It is asked first and is still not required.** "The onboarding is offered but never forced." Which raised
a problem the old set did not have, because its first question was required: an optional question at the
front would return a member to it on every visit, which is a nag rather than a question (R-175). A skip is
therefore a **row with a null value** — answered, so `resume_point` advances — rather than an absence. The
mechanism already worked; what was missing was a test saying so, and there is one now.

**The composition is written by `complete()`, not by `record_answer`.** `record_answer` writes one row and
no plan mutation by design, and a `Household` is `PlanMutable`. The answer is still stored the moment it is
given, which is what resumability actually asks for.

**Two Decisions, one transaction.** The composition is its own recorded fact with its own question; the
plan is another. Same transaction, so a failure in either rolls back both and no member ends up with a
household and no plan.

**The client sends labels, and the server attaches the account.** The stored shape is
`{adults: [...], dependants: [...], as_of: ...}` and the member answering is the first adult. A composition
carrying an account id would be one a client could point at somebody else's account.

**`initiated_by` is recorded and nothing branches on it.** It becomes the Decision's author and the
household's `stated_by`. A grep test refuses a conditional on it, and a behavioural test runs the same
answers through both initiators and asserts the rows are identical — which is what "one code path, two
initiators" actually claims.

**The first goal's owner defaults to the member, and is not asked.** A single-adult household has nobody
else it could be; for a couple the default is still the member and the field is editable on Containers. A
sixth question in a light intake whose whole purpose is to be short would cost every member a question to
save some members an edit. The default is a real owner rather than none, because a household that never
populates the field cannot be divided cleanly (A112).

**Still owed on item 3, and named so it is not mistaken for done:** progress shown as consequence — the
findings still locked and what each needs — and the first-session finding itself, composed on the go and
verified against the Befund. The second is where A114's boundary fix becomes load-bearing.

**One conflict with the script's letter, raised rather than worked around.** Item 3 says of `derive()`,
`goalsFrom()`, `netScale()`, `expertiseScale()` and `childAges()`: "Preserve ... as they are — they are
tested against the book cases and must not be rewritten in the move." Those are JavaScript in
`andersCH-prototype/onboarding-chat.html`, computing a client-side Sofortbefund against fixed assumptions.
prototype2 computes server-side in Python, against published assumption sets and the real engines, and its
`Befund` is a different object — a report over what the member has recorded, not a projection. **A port
into prototype2 is a rewrite by construction; there is no move that preserves them as they are.** Nothing
has been ported yet, so nothing has been silently rewritten. The choice — reimplement the identities
server-side against the book cases as tests, or keep the old prototype as the place those functions live —
is the owner's, and is the largest open question in item 3.

## A118 — The intake identities, reimplemented in Python against the original's own output

*Owner: Nicolas · 2026-09-03 · ruling on the conflict raised in A117*

Item 3 says `derive()`, `goalsFrom()`, `netScale()`, `expertiseScale()` and `childAges()` "must not be
rewritten in the move". They are JavaScript in a single-file prototype and this build is Python, so there
is no move that preserves them as they are — A117 raised that rather than quietly rewriting them. **The
owner ruled: reimplement in Python.**

**So the standard is differential, not editorial.** `tools/extract_identities.mjs` runs the ORIGINAL
JavaScript over a 62-case corpus and writes `backend/tests/fixtures/identities-reference.json`;
`tests/test_identities.py` asserts the Python reproduces it exactly. "Did the port change the behaviour" is
answered by the original rather than by whoever wrote the port, which is the only reading of "must not be
rewritten" that a test can hold. The fixture is committed and the suite needs no Node — `conftest.py` makes
the same point about the book corpus.

The corpus covers every case the source's own comments call out by name, every boundary each function turns
on, and the shapes the six real submissions contain. It is 62 cases and it is **not** the input space;
anything outside it is untested in both languages equally, and that is stated in the module rather than
left to be discovered.

### The differential caught two real defects that reading would not have

1. **`Math.round` is not what it looks like.** The port said "half away from zero" — in the code, in the
   docstring and in the test that was supposed to check it, all three agreeing with each other and all
   three wrong. `Math.round` rounds half toward **positive infinity**: `floor(x + 0.5)` for every x, so
   `Math.round(-0.5)` is `-0` and `Math.round(-1.5)` is `-1`. Python's own `round` is different again (half
   to even), so **none of the three obvious choices is right**. Confirmed by asking `node` rather than by
   reasoning harder.
2. **`String([])` is `""` in JavaScript and `"[]"` in Python.** `expertise_scale`'s "has anything been
   answered" check turns on that string's length, so an empty multi-select meant *unanswered* in the
   original and would have meant *answered* here — a member with an empty `education_planned` would have
   got a 0.5 expertise score out of nothing. Caught by the fixture, invisible to review.

Neither would have been found by hand-written expectations, because the person writing them is the person
who misread the semantics.

### The numbers moved to a content record, and the guard is why

`net_scale`, `expertise_scale` and the confidence table turn on numbers. The port's first version kept them
in code, arguing they are declared conventions rather than rates and that C-02 therefore did not reach
them. **`test_no_literal_rate_in_application_code` refused it**, and it is right to: its docstring says it
"cannot tell a rate from any other number, so it forbids the whole shape rather than trying to be clever
about intent". Excusing twenty-four values would have been twenty-four holes in the one check that stops an
invented rate reaching a member, in a file that will grow.

They are in `client/content/intake-scales.json`, `provisional: true`. That flag does real work: **nobody
has calibrated them**, the prototype's own comment says so ("this model's own construct and has no
published calibration behind it"), and `roles.json` ships D-03's definitions provisional for the same
reason. Publishing a number is not endorsing it.

Four literals remain in the module and each is allowlisted with its reason: `0.0` as a coercion's floor,
`0.5` as the half in the rounding rule, and `1e6`/`1e3` as the multipliers behind a member writing "1 Mio"
or "80k". All arithmetic; none a quantity anybody published.

**Not ported yet:** `derive()` itself, and `befund()`. Those are where the prototype's fixed assumption
block lives — `y_R 0.02`, `swr 0.035`, `ahv_max 30240`, `conv 0.0525` — and those genuinely are rates, so
they cannot come across as literals at all. They need a published AssumptionSet, which is a different
conversation from this one.

## A119 — Progress is a consequence, and the payload carries no number at all

*Owner: Nicolas · 2026-09-03 · from the andersCH app update script v2.1, item 3*

Item 3: "Progress shows consequence, not reward. Replace the percent-complete bar with a list of the
findings still locked and, for each, the questions it needs ... No percentages, no badges, no streaks. This
is how [the GTM lead]'s point about motivation and Principle 5 are both satisfied; a builder reading only
one of them gets it wrong."

*The bracketed role replaces a name in the owner's original wording, on the ruling of 20 September 2026
(A160). It is marked rather than done silently: this is a quotation from `andersCH-app-update-script.md`
and a reader comparing the two should be able to see that the difference is a substitution and not a
misquotation.*

`services/onboarding.locked_findings` returns `{"locked": [...], "unlocked": [...]}`, each entry naming a
finding, a sentence, and the questions still missing for it.

**The difference from a bar is not cosmetic.** A bar measures the member against completion — it is a score
of them, and R-113 and C-07 forbid it. This names a thing that is not yet possible and what would make it
possible: the subject is the finding, not the member. `resume_point` already made the same argument in its
own docstring and this keeps it.

**Both halves are returned.** A member who has answered something has unlocked something, and reporting
only what is missing would be a backlog rather than a consequence.

**No count, anywhere.** Not a total, not a remaining, not a ratio. Two guards hold it: one walks the
returned payload and fails on a bare number at any depth, the other walks the function's AST and refuses
`len`, `round`, `sum`, a division and any identifier containing percent, ratio, total or score. A planted
`"percent": len(unlocked) / 5` fails both.

That does mean the update script's own example sentence — "six answers make your retirement figure
certifiable rather than provisional" — is not composed here. The client has the list and can say "these
questions", which is the same consequence without a number the server computed about the member. If the
counted phrasing is wanted it is a client decision about a list it already holds, and it should be taken
deliberately rather than inherited from a field.

**The findings are content, not derived from the questions' `fills`.** Which findings are worth naming is
editorial; deriving them would make the list whatever the question set happened to contain, and a question
added for another reason would silently become a promise. The join runs the other way — a finding names the
questions it needs — and a test asserts every key it names exists in the set, because a finding naming a
renamed question would sit locked forever with nothing to notice.

**A text scan failed on its own docstring for the second time this session.** The first version of the
no-ratio guard grepped the function's source for "percent" and matched the word in its own prose. It now
walks the AST. Recorded because it is the same mistake as the router's purity test earlier the same day:
**a guard that reads prose is a guard that fails for reasons unrelated to the property it names**, and both
times the fix was to assert the property instead of the text.

## A120 — The first-session finding, and the figures the Befund did not have

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 3*

Principle 2 asks the first session for "one true, specific, surprising statement about the member's own
situation", and rules out "onboarding that reflects back what was typed in".

**The Befund could not carry one, and that was the first thing to fix.** Rendered for a real member
(Marvin, four positions, two goals) it held no computed figure at all: every number in it was one he had
typed, and every other fact was structural — which cell is filled, which goal is unfunded, what is not
known. An honest report, and not enough for Principle 2, whose whole point is a statement the member could
not have made themselves.

So `_stock_facts` adds the member's stated balances, summed. **Arithmetic over stated figures and nothing
else**: no rate, no projection, no horizon, so C-02 has nothing to bite on. `engine_inputs.stated_stocks`
does the summing and is not reimplemented — it already carries the four filters that make the sum correct.
Absent rather than zero: a member who has stated no balance gets no fact, because "you have nothing" is a
different and wrong claim from "you have not said". The net figure appears only when both sides are stated,
because a net over an unstated liability asserts there is none.

For Marvin that produces: *"Ihr erfasstes Finanzvermögen beträgt 222'750."* — three balances he entered
separately, and a total he never did.

### The three rules, each structural rather than editorial

1. **About them** — the candidate pool is the Befund and nowhere else, so a `content` fact (a role
   definition, a template purpose) can never be one.
2. **Not what was typed in** — a candidate must be `computed_from_plan`, never `member_stated`. That is
   Principle 2's own exclusion made checkable, and it is one field: "you have CHF 103,500 in cash" is a
   sentence the member could have written; the total is not.
3. **Every figure present in the Befund, checked after the sentence exists** — `unverifiable_figures`, the
   estate's existing check rather than a second one, plus C-01 over the sentence. Item 3's reason is the
   one it gives twice more: "instructing a model not to invent a number does not hold; checking the number
   against the source does."

**The model does not even choose.** It is handed one sentence code has already composed and asked to reword
it; it never sees the report. Non-negotiable 10 is "model chooses, code computes", and this is one step
short of that. Rewording is **off by default** — the Befund's sentence is already deterministic, sourced
and C-01-checked, and asking a model to improve a correct sentence buys wording and risks meaning. An
unavailable model falls back to the computed sentence, which is not a degraded answer: it is the one the
model was going to be asked to reword.

**Returning nothing is allowed and is not a failure.** A member who has said too little gets `None`, and
the caller says nothing rather than something weaker. That is the light-intake floor observed from the
other side.

**None of the three forbidden things is here.** The pool is everything computed about the member minus a
visible exclusion list of fact KEYS — the opposite of a curated library, because adding a fact to the
Befund adds it to the pool. The exclusions were found by rendering a Befund for a member who has said
nothing and reading what came back, rather than by imagining the list: they are all the same shape,
"nothing of this kind is recorded", which is `locked_findings`' job.

### A method note: three text scans failed on their own prose in two days

The router's purity guard, the progress guard, and this module's no-library guard were each written as a
grep over source code, and each matched the word it was forbidding **inside its own docstring**. All three
now assert the property over the AST. Recorded as a pattern rather than as three slips: **a guard that
reads prose fails for reasons unrelated to the property it names**, and in this estate the prose is long
enough that it will keep happening.

## A121 — Three doors: Vault, Know, Market. The Befund moved inside and the Plan door became the Vault

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 8*

Item 8's header is Vault / Know / Market, with `ask` always reachable. prototype2 had four doors — Plan,
Befund, Know, Market — so two decisions were needed and both were the owner's.

**The Plan door became the Vault door.** Item 4 makes the Vault "everything about the client and everything
they have to do", and page 2 puts the four-role grid *inside* it: "nobody meets the four roles before they
have entered data". So the door's name changed and its contents grew; `surfaceLinks` became `vaultLinks`.

**The Befund is a pane, not a door.** It became a door on 31 August because the owner opened the
application and said *"there is still no output"* — a complete report existed behind `GET /api/befund` and
nothing rendered it. **That fix is not undone.** It is one tap from every room of the Vault, beside the
material it reports on, and the test that used to hold the join to the chrome now holds it to the Vault
rather than having been deleted with the door. The owner also considered opening the Vault *on* the Befund
and chose the role grid, which is what page 2 calls the primary view inside the Vault.

**`ask` is not a fourth door.** The wordmark leads home. `.doors` is the set `aria-current` and the print
sheet treat as pages, and the entry surface is where a member starts rather than one of three places they
go. A test asserts `ask` never acquires `data-route`.

**One rename, because two things could not share a name.** `vault` meant the document table; item 4 makes
Vault the whole screen and documents one pane inside it. The table is now `documents`, which is also what
item 4 calls it — and item 4 is explicit that it is "secondary, not the main event". A test checks both
halves of the rename, because this is the kind that leaves a dead link behind.

**The rooms stayed rooms.** `containers`, `runs`, `stages`, `life-events` and `grants` keep their routes
and are reached from inside the Vault, exactly as they were reached from inside Plan. `main.js` already
argued for that shape — "a room behind the Plan door rather than a door of its own" — and the argument did
not change when the door was renamed.

**The Tree of Knowledge, which item 8 says to leave in place and report as a pending decision, does not
exist in this build.** It is in `andersCH-prototype/index.html`, the single-file prototype, where it is the
`tree` screen and its d3 dependency. Nothing here references it and nothing here needs to be left alone.
Reported rather than silently skipped, because "not applicable" and "forgotten" look identical afterwards.

## A122 — The blocking liquidity finding, built narrow because the vocabulary it needs does not exist

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 4*

Page 2: "The `liquidity` field is enforced rather than displayed ... The enforcement is what makes the goal
system honest rather than decorative." Item 4 says what the member sees — the gap in francs, the date, the
reason in one line — and that exactly one option is prepared, by a fixed lever precedence held in config.

**The general finding cannot be computed yet, and this does not approximate it.** It needs
`Goal.liquidity_need` to be comparable with `Position.liquidity`. `liquidity_need` is a free-text column
with **no published answer options**: the five return-profile questions are drafted and awaiting the
owner's line-by-line approval, which `PICK-UP-HERE.md` already records as an open decision. Comparing free
text with a band means inventing the mapping.

**One case needs no vocabulary and is decidable today**: a dated goal funded *entirely* by holdings marked
`illiquid`. `services/goals.observations` already found it — "the one comparison that needs no threshold" —
and reported it as a note with no gap, no prepared option and no consequence. It now carries the state, the
figure and the option. When the parameter vocabulary lands, `assess` grows a branch and everything below
it is already built.

**Three things and no fourth.** The payload is state, gap, date, reason, the positions meant, and whether
it blocks certification. A test asserts no `severity`, `level`, `colour`, `status` or `warning` key can
appear — item 4's "no warning colour doing the work of a sentence", enforced on the shape rather than
trusted to the client.

**The gap is absent rather than zero when no balance is stated.** "How much" is a different question from
"whether".

### An undecidable lever routes to a human rather than being skipped

The precedence claims the prepared option is *the first that closes the gap*. A lever whose effect cannot
be worked out cannot be ruled out — so skipping it would let a later, dearer lever be prepared while an
earlier and cheaper one might have closed the gap, and the claim would be one the code does not keep.
`prepare` stops at the first undecidable lever and routes to a curator, which is what item 4 says happens
when the order cannot deliver an option.

`move_the_goal_date` is where this bites, and only sometimes: **no date makes an `illiquid` holding
available**, so for today's one case it is decidably *no*. For `within_years` funding it would close the
gap at some date, and naming that date needs a duration nobody has published.

Three verdicts, not two — the Household Optimiser's third answer again, and it is what makes "cannot be
decided" different from "does not close".

### Two guards caught real defects in this work

1. **C-01 refused the English lever labels.** "Move the existing funding into a form…" is an imperative
   landing on something financial, and `move` entered the money-move lexicon in A114 — so the gate I
   widened three days ago refused copy I wrote today. The German column was already infinitive clauses,
   which is the house register for a prepared option and what `services/derive.py` uses. The English now
   matches. **A prepared option describes a change the member may choose; it does not tell them to make
   it, and the difference is the mood.**
2. **`test_no_module_writes_the_stock_unit_as_a_literal` refused `magnitude_unit == "chf"`.** The literal
   is a prefix of `chf_per_year`, which is A105's defect — a market rate applied to a salary. `in
   STOCK_UNITS` is the form, and the guard exists precisely because the wrong one reads as correct.

## A123 — The Actions pane, the Regime before sign-in, and where community belongs

*Owner: Nicolas · 2026-09-04 · items 4, 5 and 7 of the update script*

### The Actions pane is the panel's list, in a second place

Item 4 gives the Vault an Actions pane — "what the client has to do, with dates" — and R-174 keeps the
same items in the Know panel, where they arrive with a prepared decision rather than as a notification.
Those are **two places to meet one list, not two lists**: `know.renderActionList` was extracted and both
call it. A second copy of `actionNode` and the "which goal" join would have drifted in the worst possible
place, with the panel and the pane disagreeing about what a member has to do.

### The Regime is the first screen this product has that needs no account

Item 5: "population-level ... can be shown to anyone — including before sign-in. **This is the product's
most distinctive output at zero data cost**, and today nothing exposes it to someone who has not completed
an intake." `GET /api/regime` joins `OPEN_ROUTES`, and `route()` returns the screen **before** the token
check — beside the curator door, and for the same reason: a person without a session has somewhere to be.

**A reading, never an artefact.** The AssumptionSet's `rates` block carries the whole Fund Map beside the
regime — per-state return profiles, the state grid, scenario probabilities. `services/regime` admits **only
scalars** out of the Regime's own `current` block. That is a rule about SHAPE rather than a list of keys: a
scalar is a reading, a nested array is a piece of a model, and a key added upstream is therefore served if
it is one and dropped if it is the other, with nobody maintaining a whitelist. C-03 and R-304 both.

**Not available is a 200.** An unpublished AssumptionSet is a true state of the world and the payload says
so, with the server's own reason underneath. Raising would make a public page look broken when it is merely
honest — and inventing a reading would be "a default rate wearing a different hat" with a larger audience.

Three guards had to be satisfied before this could ship, and each is worth naming: `OPEN_ROUTES` refuses an
unauthenticated route that is not registered; a second test refuses one that is registered without being
**argued for in `api/auth.py`'s docstring**; and a client test asserts the surface sends no member id, since
one acquired later would cross the first boundary silently.

### Community belongs to the Market, not the Know

Item 7 names the Market's four panes — community, services, ventures, build your own venture — and item 5
names the Know's three, which do not include it. `community` was a room behind the Know door and is now one
behind the Market door. Page 1 agrees with the script: a lecture attended and a café evening with a guide
are the Market Place serving learners "before they arrive at the planner", which is demand rather than
curriculum.

`ventures` and `build your own venture` are **not stubbed**. A link to a screen that says "not built" is
the placeholder S-11 was criticised for, one level out.

### Item 7's survey, which the script asks for before anything is written

"Recover the community surface from the earlier andersCH version rather than rebuilding it — locate it
first and report what is there before writing anything new."

**Located: `andersCH-prototype/index.html`, the `network` pane of the Marketplace module** (also in
`anderschapp-v3/v5/v6.html`, growing across versions). What is there:

  * **Five tabs** — All · Curators · Creators · Peers · MBA.
  * **A radial canvas**: the member at the centre, six people placed around them on two rings. Solid
    connectors to the inner ring, dashed to the outer.
  * **Six nodes**, each a name, a role label, a colour and a one-line bio behind a click. Three are
    connections (Dr. Anna Weber · real estate; Markus Frei · pillar 3a; Emma Liu · peer) and three are
    suggestions (Thomas B. · mortgage, carrying an `MBA` marker; Sara Keller · tax; Yves Marchand ·
    behavioural).
  * **A two-row summary**: inner ring 3, outer ring "3 suggested".
  * **A privacy boundary stated on the screen**: "Asset, liability, and goals data are never exposed. Only
    shareable attributes feed the matcher."

**The last of those is the part worth carrying, and it is already item 7's first hard rule** — "Market has
no read access to Vault data. Enforce this in code, not by convention." The earlier version stated it as a
footnote to the member; this build has to make it true of the code. Nothing has been written yet, per the
script's instruction.

**One thing the recovery will have to decide.** The old canvas places six people at hardcoded percentages
with hardcoded bios; there is no matcher behind it. Recovering "the surface" means recovering the *shape* —
two rings, connections and suggestions, a role label per person — over `services/directory` and
`services/marketplace`, which are real. Recovering the markup would be recovering a mock.

## A124 — Item 7's two hard rules, and what "recover" meant

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 7*

### Rule 1, narrowed by the owner and then made enforceable

"**Market has no read access to Vault data.** Enforce this in code, not by convention."

Taken literally it collides with R-201 and with item 7's own sentence two paragraphs earlier — "Index
supply by the four roles rather than by profession, so **the member's own role grid tells them which entry
is relevant**." `services/marketplace._member_role_grid` reads `Position.role` to pre-filter, which is
exactly what R-201 asks for. Raised rather than resolved unilaterally.

**Ruled: keep the server-side read, narrow the rule.** It means no access to balances, goals, documents or
decisions; *which roles are filled* is too thin to count as Vault data.

A narrowing is only worth having if it is a line rather than a judgement, so `tests/test_market_boundary.py`
draws it in three places: the market layer may not **import** `Goal`, `VaultItem`, `Decision`, `Household`
or `PlanVersion`; it may read only `role`, `member_id`, `active` and `id` off a `Position`; and no Market
payload may carry a franc figure. A planted `Goal` import and a planted `Position.magnitude` read each fail
it. Verified as non-vacuous too — a fourth test asserts `Position.role` really is read, so the first two
are not forbidding an empty set.

### Rule 2 holds because the object does not exist, which is worth pinning

"**Private altitude and public standing are two distinct objects and are never joined.**"

There is no altitude in this build: A2 excluded "the altitude ring, `alt.score`, the 'n of m answered'
line, the stage progression, and `altitude` as a data key" as C-07, R-113 and R-143 violations. So the rule
holds for the weakest possible reason, and a test now makes the absence explicit — reintroducing a private
progression measure fails there rather than quietly satisfying nothing.

Two further tests hold the shape rather than the vocabulary: `member_standing` is built from
`CapabilityAssertion` and `Attendance` and from no plan model, so a member's balances can never decide
where they rank among other people; and the module's two member-scoped reads are asserted to be about
**different people** — the role filter about the browsing member, standing about the offering one. Two
facts about two people on one page is not two facts about one person combined.

### "Recover" meant the shape, not the markup

The earlier surface — the `network` pane of `andersCH-prototype/index.html` — is six named advisers with
biographies at hardcoded percentages on a radial canvas, with no matcher behind any of it.

**Recovered:** the two-ring distinction (reachable / suggested), a role label per person from
`Curator.role_label`, and the privacy line on the screen — which is item 7's first hard rule stated to the
member, and the best thing in the original. Here it is also true of the code.

**Not recovered, each deliberately:** the radial SVG, because a canvas whose geometry is six hardcoded
percentages is a picture of a matcher rather than a view of one; the five tabs, because four of the five
categories have no object behind them in this build; and the suggestions themselves, because there is no
matcher — the group renders empty **with its reason** rather than with invented people. A test asserts
none of the six names came across.

### The meter guard caught a word, not a number

`test_no_meter_exists_anywhere_in_the_client` refused the class `network-ring`. The domain concept really
is two rings and the original said so — but "ring" is the vocabulary of the altitude ring A2 threw out, and
a CSS class teaching that word back is how it returns. The class is `network-group`; the prose still says
rings. **A guard on vocabulary is doing real work when the word is right and the association is wrong.**

## A125 — Content hooks: one implementation, two directions

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 5*

Item 5: "This is the same mechanism as the first-session finding, running in the other direction: the
chatbot composes a grounded statement when the app has something to say, and the same path serves the
member pulling when they want to know something. **One implementation serves both.**"

That is a claim about the code, so it is now one. Both directions need the same question answered — *which
of these inputs has this member already given?* — and `services/inputs` answers it once:

  * **Pushing** (item 3): `know.missing_personal_input` names the one input that would make a branch-2
    answer personal. Its predicates lived there first and were **extracted rather than copied**.
  * **Pulling** (item 5): `hooks.hook` asks which of a content item's declared inputs are still missing,
    so the ones already in the Vault are skipped.

Two tests hold the claim: one reads both call sites and asserts they reach the same module; the other fills
a Vault step by step and asserts that what the push names as missing is never something the pull thinks is
already there.

**These are inputs, not questions**, and the distinction is load-bearing. `household_composition` happens
to be both, but `financial_stock` is satisfied by any stated balance from any route — the intake, the role
grid, a curator session — and asking "has question X been answered" would have missed all but the first. So
the set is keyed on what the plan HOLDS, and each entry carries its own predicate. An import-time contract
fails the module if the order and the predicates disagree, because an input with no predicate is one
nothing can ever satisfy.

**A declaration is inputs and never a sentence.** Item 5 is precise about this and it is the part most
easily got wrong: "What a content item declares is which inputs are needed, not a prepared sentence — the
finding itself is composed on the go." So a hook is at most three input names on the content record and
nothing else; what the member gets after answering is `services/finding`, composing against the Befund with
every figure verified afterwards (A120). No prepared text, no per-item template, no eligibility rule.

**No tap is a real answer.** `wenn_sie_es_anbieten` declares nothing, because offering a service is about
the member's own economic ties rather than their balances — it says the same thing to everybody. Item 5
calls that "an editorial constraint, not an engineering one", and the content exercises the case rather
than avoiding it: a test asserts that unit is untappable, so the branch is live rather than theoretical.

**A salary is not a balance**, and a test says so. `financial_stock` requires a `chf` stock unit, never
`chf_per_year` — A105's defect and A122's, arriving a third time in a new module. The comment at that line
names both.

## A126 — The Feed, in the Reading Room's shape, with two sections that say what they are waiting for

*Owner: Nicolas · 2026-09-04 · from the andersCH app update script v2.1, item 5*

The reference page at `https://stk.sim-tech.ch/` was read on 4 September 2026, as item 5 instructs
("Open that page and read its actual structure before building"). It carries exactly three section labels
under the heading "Share the Know — Prototype": **pinned groups, pinned follows, pinned vaults**. Those are
reused rather than renamed.

**Two of the three have no object behind them in this build**, which the owner was told before the decision
was taken: `Gathering` exists and is never seeded (already an open item in `PICK-UP-HERE.md`), and there is
no follow relation at all — no table, no route, nothing. The owner chose the same treatment as the
community recovery on the same day: **reuse the shape, populate what is real, and render the rest empty
with its reason.**

The argument is the one A124 makes: a section that is missing looks like a build error, a section filled
with placeholders is a lie, and a section that says what it is waiting for is the truth. Dropping the two
would also have produced exactly "the generic article list" item 5 names as the thing to avoid, and
reintroducing them later would be a second decision nobody would remember to take.

**A structurally empty section and one that is merely empty for this member say different things.**
`empty_reason` is null for the second, and the surface renders a different sentence. "Nothing can fill this
yet" and "you have none" are not the same statement and a member should not have to guess which they are
reading.

**The ordering item 5 asks for is not implemented and is not faked.** "The Know's feed is ordered by what
follows from what they have read and what is in their Vault" — nothing in this build records what a member
has read, so an ordering claiming to follow from it would follow from nothing. The payload says
`ordered_by: content_order` with `no_read_history_recorded` beside it, and the screen carries the sentence,
so the order cannot be read as relevance. **No outbound channel exists and none was added**, per item 5's
explicit instruction not to add one even behind a flag.

**"Vault" means two different things and the surface is careful about it.** The Reading Room's "pinned
vaults" are collections of reading; this application's Vault is the member's own plan and is a door (A121).
The section key stays `vaults` so the two pages can be compared; the member-facing label says
*Sammlungen* / *Collections* and never uses the word.

**R-222 caught the copy, which is the third vocabulary guard to earn its keep this week.** The German empty
state said *Veranstaltung*; page 4 reserves the word for life events and names gatherings as lectures,
evenings or meet-ups. It now says *kein Vortrag und kein Treffen*. A114 caught a mood, the meter guard
caught a word with the wrong association, and this caught a word with the wrong referent.

## A127 — The five instrument keys, stored as facts rather than columns

*Owner: Nicolas · 2026-09-04 · from the sim-tech task "Add the five missing keys to the intake instrument"*

The task asked for two things and the second is the one with consequences: **name the five keys**, and
**"build the instrument so keys can be added without touching the intake flow"**.

**The five are canton, civil status, health, network size and education.** They were not written down
anywhere — the task said to name them — and they were not guessed either. `tools/load_submission.py` has
reported the same absence against all six real submissions since 30 August: read, printed, and dropped for
want of anywhere to put them. The owner confirmed the five on 4 September. `ahv_years_missing` is not among
them, and `children_count` had already been answered by the household model (A108).

**Every one of the five already had wording**, refined across five schema versions and three real
interviews, in `client/reference/questions-onb-0.1.3.json` — the file the instrument's own `provenance`
names. All five are therefore `carried` and not a word of German here is drafted. That was worth checking
before writing rather than after: **the reference's `civil_status` offers six options, and the second is
`ledig, mit Partner`.** It is not a legal civil status, a tidy five-option list of the legal statuses could
not hold it, and one of the six real submissions answers exactly that. Redrafting would have recorded a
false answer for Levin — which is the Renzo case from the other side, where a drafted option set could not
hold a real one. It is kept, and the partner appears as a second adult in the household as well; nothing
reconciles the two, because a member may state either without the other.

**One table, not five columns, and that is the whole of the second requirement.** Five columns on `Member`
would satisfy today's list and break the promise on the sixth key — a column, a migration, a branch in
`complete`, a control in the client. `member_facts` is key/value, and the keys, their types, their options
and their data classes all come from the content record. `services/member_fact.py` contains no list of
keys; `onboarding.complete` walks `fills.entity == "member_fact"` and does not know their names. A test
plants a question this build has never seen, answers it, completes the intake and reads the value back —
and planting a hardcoded key list in `complete` makes that test fail, which is what stops the claim from
being decoration.

**Not `OnboardingAnswer` wearing a different name.** An onboarding answer is what was typed in one session,
so a member can resume at question *n*; it is deliberately not a plan mutation. A member fact is current
standing — it has a date it describes, someone who stated it, and it changes over a life. Storing the
canton only as an onboarding answer would mean a member who moved could correct it only by editing the
record of a conversation they had years ago. So `MemberFact` is `PlanMutable` and takes a Decision, exactly
as `Household` does, and for the same reason: the tax path moves when it moves.

**C-09 required the link table rather than merely preferring it.** `Decision.covered_plan_objects` is what
the guard compares against, so a `PlanMutable` row with no link table cannot be written at all. And the
guard made a second correction that was right: superseding a fact modifies the old row, so **the Decision
covers both** the statement that ended and the one that began. That reads better on S-07 too — a Decision
naming only the new canton would leave a member wondering what it replaced.

**The entity is K3 because of one key.** `health` is a person's own statement about their body. The C-04
filter drops by field **name** across the whole model layer, so a K2 entity would have left `health` in log
lines. Classifying the entity K3 means its column names join the global drop list — which is why they are
`stated_key` and `stated_value` rather than `key` and `value`. A K3 column called `key` would redact `key=`
in every log line this application writes, and `models/base.py` already argues that a filter which removes
the field every trace is followed by is an unused filter. `stated_on` and `stated_by` carry an override
back to K1, because leaving them at K3 would drop `stated_by=` from log lines about `households` — one
table's classification deleting another table's diagnostic. The **per-row** class comes from the key's own
declaration, so a canton row stores K1 and a health row K3.

**Superseding is a date, not a pointer at the successor.** A `superseded_by_id` would be a self-referencing
foreign key, and this build has paid for one: `erasure._erase` has to delete plan versions itself, oldest
first, outside its own generic loop. It is also unwritable in the required order — the old row must stop
being current *before* the new one is inserted, or the partial unique index sees two current rows, and at
that moment the row a pointer would name does not exist.

**Two defects were found on the way and both are repairs rather than new work.** `GET /api/onboarding` has
never sent `min` or `max`, while `client/surfaces/onboarding.js` has always read them — so
`employment_magnitude`, which declares 0 to 5,000,000, has been rendering as an unbounded field since it
was written. And `alembic revision --autogenerate` produced three edits belonging to nothing in this
change, one of which dropped a real CHECK constraint from `households`; the migration is hand-written and
says so. A migration whose stated purpose is to add two tables, quietly weakening a third, is the same
shape as the trigger defect in A68.

**Two counts went stale and were replaced rather than corrected.** The intake screen's title said *Vier
Fragen* and the loader printed "the four onboarding answers". Both are now countless, because a title with
a number in it goes false every time the instrument grows — which is R-113's argument arriving from an
unexpected direction.

**All five are optional and ordered last, so the light-intake floor does not move.** The sim-tech task
asked for that to be confirmed rather than assumed. `health` is last of the five deliberately: it is the
most intrusive question in the instrument and there is no reason for it to stand between a member and the
rest.

**The six loaded members were topped up, not reloaded.** `onboarding.complete` refuses a second run and
Decisions are append-only, so `_add_missing_facts` adds what the model can hold today — the case the
loader's re-runnability was written for, arriving a second time. Twenty-eight facts across six members;
Elio and Yasmin get four each because neither states a network size, and absence is silence rather than a
zero.

**The four structured education answers are still not stored, and are now reported rather than dropped.**
`expertise_scale` reads `education_recent`, `education_planned`, `education_hours` and `education_budget` —
the free-text `education` is explicitly not scored — so the expertise estimate has nothing to run on. They
were not in `NO_FIELD_HOLDS_IT` either, which means they were being discarded silently. `mandates` is the
same case for `net_scale`, which now has one of its two inputs. None of the five is among the keys the
owner named; adding any of them is one entry in the content file and no code, which is the point.

**The new client control was rendered before it was believed.** `tools/walk_screens.mjs` now draws every
question in the instrument and reports the control each one produced. Removing the `choice` branch is
caught — but only by the option-count assertion: the plant renders as a plain text input, and a check that
merely asked "is there a control" reported it as fine. A canton silently falling through to a text field is
exactly the failure a source-reading test cannot see.

## A128 — The pre-authentication archive was deleted rather than left labelled

*Owner: Nicolas · 2026-09-04*

`dist/andersCH-prototype2.zip`, cut on 30 August, shipped the client as it stood before the session layer:
`store.js` and `welcome.js` present, `session.js` and `login.js` absent. Anyone who installed it got an
application with no authentication at all, in which any member's full record was readable from a URL.

It was found on 31 August and **labelled rather than deleted**, on the argument that removing an owner's
artefact is not the implementer's call and that the owner had asked to review the application before any
rebuild. That was a correct reading and it also left a pre-authentication client sitting in a folder called
`dist` for five days.

The owner's decision on 4 September was to **separate the two questions**. The hazard goes now; the rebuild
still waits on their own pass through the running application. Neither half was a compromise: a label
protects against a careless reader and not against a hurried one, and a rebuild is a different decision
from a deletion.

The archive was read immediately before removal, so `dist/NO-ARCHIVE-YET.md` records what was in it as an
observation rather than a recollection — including that it contained no database, which is the one thing it
got right. `dist/` is gitignored in full, so nothing is recoverable from history and nothing needs purging
from it either.

## A129 — Property is bought with a mortgage, and the plan had no way to say so

*Owner: Nicolas · 2026-09-04 · from running all six real submissions through the application and reading what came back*

Four of the eleven goals across the six real submissions are property purchases, and they carry the largest
figures any member wrote down. The build had exactly one way to read a goal — *can this member accumulate
`target_amount` by `target_date`* — and for a property goal that is the wrong question. **A member does not
save 1.5 million to buy a 1.5 million house.** They save the deposit and borrow the rest.

The first edition of the six-case report made that mistake in full, and it made four of six cases wrong in
the same direction: it told the owner that members needed to save 147 %, 149 %, 155 % and 202 % of their
gross income. Recomputed against the tests a lender actually applies, **three of the five property cases
already reach the deposit comfortably and fail on income instead** — a different problem with different
remedies — and one of them, Levin, is 11 % away rather than hopeless.

**Two tests, and they bind in different places.**

  * **Equity.** At least a fifth of the price for a home the member lives in, of which at least half must
    be *hard* — not from pillar 2. Pillar 3a counts as hard equity; pillar 2 does not.
  * **Affordability.** Imputed interest, plus maintenance, plus amortisation of the portion above the
    first mortgage, all of it at most a third of gross **household** income. The imputed rate is deliberately
    above any rate on offer, which is the entire point of the test — reporting it against an actual rate
    would defeat it. The convention produces the familiar ceiling of about 5.7 × gross income, which is
    what says the figures were transcribed correctly rather than invented.

**And one rule that is not a matter of degree at all.** Pillar 2 and pillar 3a may be drawn only for a
property the member occupies as their primary residence. For a holiday home or a property they let out the
pension capital is **not illiquid — it is unavailable**. Yasmin holds 172'000 across pillar 2 and 3a against
a Ferienhaus goal; a naive reading of her own balance sheet says she is most of the way to the deposit when
she has a fifth of it. No horizon and no risk appetite changes that, which is why it is a rule and not a
parameter.

**`Goal.occupancy` exists because nothing else could carry it, and nothing infers it.** The six wrote
*Wohneigentum*, *Eigenheim*, *Eigentum kaufen* and *Ferienhaus kaufen*; only the last is unambiguous, and
Marvin's goal says Wohneigentum while his own question describes letting it out. So even one member has to
be asked. A goal with no occupancy gets `could_not_be_determined`, **never the favourable case** — A110's
discipline, and the plant that proves it is a version of `assess` that defaults to owner-occupied.

**The conventions are published, provisional, and refuse to serve.** `client/content/property-funding.json`
carries the equity floors, the imputed rate, the maintenance fraction, the amortisation term and the
affordability share, and `services/property.conventions()` raises `ConventionsNotApproved` while
`provisional` is true. Nothing computed from them can reach a member on the implementer's word: these
figures tell someone what a lender would say. The module is fully built and fully tested against an
approved fixture, and today it serves `could_not_be_determined` to all five property goals. **Approving is
three fields and a boolean**, and `test_the_shipped_record_is_provisional` should be deleted in the same
commit that does it.

**Seven things are named as not modelled rather than approximated**, and the list is asserted so it cannot
quietly empty: rental income and its haircut, the pension and cover reduction a pillar 2 withdrawal causes,
the age-50 withdrawal cap, the 20'000 minimum and five-year interval, the tax on a withdrawal, cantonal and
lender variation, and Eigenmietwert.

**Wired into the goals payload rather than left for a caller to reach.** `services/learning.seed` and
`services/marketplace.seed` were both complete, correct, tested and invoked by nothing, and the Market Place
shipped empty because of it. A module that answers the largest figures in a member's plan and is reached by
nothing would have been the fourth instance. `goals.property_finding` is on every goal payload, `None` on
every goal that is not a property purchase — one key to read rather than an absence to interpret, the
argument `short_on_date` already makes.

**A latent defect closed on the way.** `services/illustration.py` reads `Goal.target_amount` as *what the
member says the goal needs*. For a property goal it holds the **price**, and what the goal needs on the
target date is the **deposit** — a factor of roughly five, in the direction that tells a member they are
far behind when they may already be there. It never fired because no goal in the build is funded. A
property goal is now not projected at all, with its own reason.

**Two limitations stated rather than hidden.** The funding split reads `Position.label` to tell a 3a from a
pillar 2, because the plan has no field saying which vessel a position is and `role == protection` is not
it — a protection holding may be an insurance policy. Anything unrecognised counts as hard equity, which is
conservative for the eligibility test and wrong for a member who typed *PK-Guthaben*. And where a household
has more than one adult and only this member's income is on file, `_household_income` returns `None`: a
true statement about the wrong household is worse than no statement, and Levin's case is reachable jointly
and absurd alone.

**C-01's line, stated in the module.** *"A property at this price is tested against an income of 265'000;
your plan records 69'550"* is a per-member computation, the second branch of the router, below the advice
boundary. *"Buy a cheaper house"* is a recommendation. `levers()` returns the dimensions with their
arithmetic and no ranking and no imperative, and a test asserts it carries no prose at all.

## A130 — A credential is not a plan, and Yasmin lost her record to the difference

*Owner: Nicolas · 2026-09-04*

`tools/load_submission.py` branched on whether a **credential** existed, not on whether a **plan** did. One
member's account already existed as a seeded access shell (A53) — a name, a guessed age, a first-login
password, nothing else — so every load of her submission took the top-up path and added stocks and facts to
a member who had never been through `complete()`.

What that produced, found by signing in as her and reading what the product served: **two positions, no
income, no goals, no consent record, an age of 46 against a stated 53, and a display name that was the
shell's own instruction sentence** — *"Yasmin T. (Zugang, Passwort bei der ersten Anmeldung ändern)"*. Her
Befund opened with *"Es ist kein Ziel erfasst"* for a member whose submission carries two goals.

Everything downstream behaved correctly. The Befund composed, the Decisions were append-only and ordered,
the data classes held, the C-01 gate classified her question. **All of it on a record that should not have
existed in that state**, which is the part worth carrying: none of the guards this build is dense with
could see it, because none of them is about whether a member's record is coherent.

The condition is now `onboarding_completed_at is not None`, read from the column rather than inferred from
the presence of rows — the same argument `Member.onboarding_completed_at` makes in its own docstring. A
member with a login and no plan takes a third path that completes the intake it never had, corrects the age
and the name against the submission, and grants the consents the shell was created without.

**Consent needed a second writer and did not get one.** A97 states that `Consent` rows are written in
exactly one function so that "nothing writes a row for a notice" is one check rather than a rule every
caller remembers. `register_member` could not be used — the member already exists — so the row-writing was
extracted into `_write_consents` and `grant_consents` was built on it. The guarantee is still one function;
it now has two callers.

**The goal-writing was duplicated and is now shared.** The create path built the first goal, revised it with
the stated amount and date, then wrote the rest. The shell path would have needed the same thing, and
"similar-looking" is how the two would have drifted. Extracted to `_write_goals`, called by both.

## A131 — Two symbols mean opposite quantities on the two sides of the engine bridge

*Owner: Nicolas · 2026-09-04*

Each submission carries a `state` block of single-letter symbols — `W_L`, `W_R`, `D`, `H`, `N`, `E` — which
look exactly like the Life Balance Sheet's input names and are the obvious thing to wire together.

  * **`W_L`** — the engine declares *human capital as a stock in francs*. The submissions use it for
    **liquid financial wealth**: Marvin's 205'000 is his 103'500 of cash plus his 101'500 of securities,
    and the arithmetic holds for all six.
  * **`E`** — the engine calls it a state variable of `personal_alm` with no counterpart in the plan. The
    submissions use it for the **expertise scale**, which `services/identities.expertise_scale` reproduces
    exactly for the four submissions that carry the structured answers behind it.
  * **`D`** agrees on both sides. It is in the registry precisely because "they all disagree" would be the
    wrong lesson.

Nothing in the build maps them, which is the only reason this has not bitten. It would not fail if it did:
it would produce a plausible number that is wrong for every member at once, and the first sign would be a
household being told its goal is unreachable.

Neither side can be renamed — §9 of the build manual says wrap the engine rather than reinterpret it, and
the submissions are somebody else's source data. So the collision cannot be removed, only known about, and
`tests/test_submission_symbols.py` is where it is known. It asserts each meaning from the data rather than
from a comment, and refuses an undocumented overlap.

**The guard immediately found a fourth collision the reading had missed.** `W_R`: the engine's subject is
the member's financial capital, and the submissions report `W_R: 0` for a member holding 101'500 of
securities — so it is certainly not financial capital. What it *is* cannot be established from these six,
because every value is 0 or null. It tracks `property_total` exactly, which is consistent with real-estate
wealth and equally consistent with anything else that is zero everywhere. **Recorded as undetermined rather
than guessed**: a registry whose purpose is to prevent a wrong mapping must not contain one.

**And one figure in the source data has no working behind it.** Yasmin's submission states `E: 0.7` that her
own answers cannot produce — she carries none of the four structured education answers the scale reads. Her
file is marked `source: profile-document-reconstruction`. It is not a defect in the scale; two of these six
are reconstructions and one of them carries a number nobody can derive.

## A132 — The debt is one debt, and it belongs to the household

*Owner: Nicolas · 2026-09-04*

Yasmin states 782'100 of debt. Elio, her husband, states 0. It is **one mortgage against one property**,
recorded by one of them and forgotten by the other — the owner's own reading, and the plainest argument for
the household model there is. A liability held per member is either doubled or lost depending on which
record you read.

`tools/load_submission.py` read `D` from nowhere at all: the field lives in the submission's `state` block
and both of the loader's registries look in `raw` first, so it was neither stored nor reported, unlike
`pillar2` which is at least printed. Yasmin's 782'100 was dropped in silence on every load.

It is now reported, with the household caveat in its reason. It is still not **written**, for the same
reason `pillar2` is not: `Position.stock_kind = 'liability'` exists and which of the four roles a mortgage
occupies is a ruling nobody has made. Two rulings are now waiting on the same question, and both of them
are about a Vorsorge or a debt vessel rather than about anything the member said.

## A133 — Four rulings taken on 4 September, and what each one moved

*Owner: Nicolas · 2026-09-04*

**The property conventions are approved.** `client/content/property-funding.json` carries the owner's name,
`provisional: false`, and the equity floors, imputed rate, maintenance fraction, amortisation term and
affordability share are live. Approved as drafted, knowing that the 20 % and 10 % are self-regulation while
the 30 % for a second home and the 25 % for a let property are market practice that varies more widely
between lenders than anything else in the record. `test_the_shipped_record_is_provisional` was deleted in
the same commit and replaced by its inverse — the property that matters was never "is it provisional" but
**does a person stand behind these figures**, and a record that lost its publisher in an edit would be one
nobody stands behind, computing away.

**Pillar 2 is Protection, illiquid — the same ruling as the 3a and for the same reason.** A Vorsorge
entitlement, ruled on what a pillar 2 *is* rather than on how any given one is invested. The effect was
immediate and large: **Elio's Befund went from 81'000 to 697'000**, seven years before he retires, and
Yasmin's from 141'000 to 236'000. The liquidity band stays `illiquid` and the one exception the law allows
— a draw for an owner-occupied primary residence — is modelled by `services/property.py` as an
*eligibility*, not as a liquidity band, because it depends on what the money is for and not on how fast it
can be reached.

**A household is the couple, and the children are not in it.** Elio and Yasmin each get two adults; the
three children they name are 21, 24 and 26, and two of them hold their own accounts in this application.
`tools/load_submission.py` builds a household from `civil_status` plus the partner's name where the member
wrote one, and refuses where a marriage is stated and nobody is named.

**The cost of the literal reading is Levin, and it is stated rather than absorbed.** `ledig, mit Partner`
is not a married couple, so he gets a household of one — and his partner's stated income of 85'000 stays
out of the affordability test. On his income alone the ceiling is 509'434; on the household's it is
990'566, against a goal of 1'100'000. The same goal is absurd or nearly met depending on that one field.
`MARRIED` in the loader is where that changes if the ruling is widened to unmarried couples who plan
together.

**Risk profile: the most conservative answer binds.** Maximum acceptable loss, volatility tolerance and
flexibility belong to the household; horizon and liquidity need stay with the goal. Where a couple has
answered differently — Elio 10 %, Yasmin 30 % on largely the same money — the stricter answer governs.

The implementer's recommendation was the other option: record one joint answer and report
`could_not_be_determined` until it exists. The argument against the ruling was put and the owner took it
anyway, and the argument for it is real — the person who cannot tolerate the loss is the one who acts at
the worst moment. **What the ruling costs is that it silently replaces a stated answer**, which is the one
thing this build has otherwise refused to do all week. If it is implemented, the member whose answer was
overridden should be able to see that it was.

**Not implemented, and the reason is upstream.** The five return-profile questions are still unapproved, so
there is no published vocabulary and no ordering to be conservative about. Building a resolver now would
be an artefact that exists, is correct, is tested, and is never reached — the pattern this build has
recorded three times. The ruling is written down and waits for the vocabulary.

## A134 — The developer database was missing two tables and no household could ever have been written

*Owner: Nicolas · 2026-09-04*

`decision_households` and `decision_household_members` were absent from `backend/andersch.db`, while
`alembic current` reported the schema at head. Thirty-six tables of thirty-seven present, and both missing
ones belong to A108's household migration.

**The consequence is the one the six-case report attributed to something else.** Every Befund opened with
*«Zu Ihrem Haushalt ist nichts erfasst»*, and the report explained that by saying the loader had no mapping
from a civil status to named people. That was true and it was not the whole truth: **a household could not
have been written in this database at all.** `Household` is `PlanMutable`, so writing one links it to a
Decision, and the link table did not exist — the write failed with `no such table` at the first attempt.
Nobody had attempted one, so nobody had seen it.

Nothing is wrong with the migration. A database built by `alembic upgrade head` has both tables and the
migration tests prove it. The developer database drifted — created by `create_all` before those tables
existed in the model and stamped afterwards is the likeliest history — and the drift was invisible because
`alembic current` reads a version row rather than the schema.

Repaired with a targeted `create_all` for the two tables. **The lesson is the one this build keeps
relearning in new clothes**: a claim that something is at head is not evidence that it is, and the check
that would have caught this compares the model's tables against the database's rather than reading a
version string. It is three lines and it did not exist.

Worth noting that `alembic revision --autogenerate` reported both tables as missing on 4 September and
that report was dismissed as a false positive, because two other edits in the same output genuinely were
ones. A tool that is right about one thing and wrong about two in the same breath is a tool whose output
has to be read line by line.

## A135 — The Know now answers all six members' questions, and the reason it did not is worth keeping

*Owner: Nicolas · 2026-09-04*

Six real members put six real questions to the product and got the same sentence six times: *«Dazu finde
ich in Ihren Unterlagen und im Lernmaterial nichts.»* The routing was correct every time and the relevance
floor was working as designed. **The corpus was the gap** — fourteen approved German entries on AHV, the
three pillars, ETFs and risk, and not one on property, when four of the six questions were about buying
one.

Eight drafts were added: the equity floors, the affordability test, what Vorsorge capital may and may not
fund, letting and holiday objects, the amortisation of a mortgage, part-time work and the pension gap,
self-employment, and an entry on the order in which the investing questions have to be asked. All eight
carry `approved: false` and `reviewed_by: null`, which is the README's own rule and the reason the
directory exists: *no member sees a sentence a person has not signed off*. They are inert until read line
by line.

**Writing them was not what closed the gap, and that is the finding.** Measured against the retrieval
floor, the eight new entries answered two of twelve probes. Authored entries are scored on **word overlap
alone** against a deliberately punishing floor of 700 per mille — and German compounds do not decompose. An
entry full of *Wohneigentum* cannot be reached by a member who types *Eigentum*. One that says *Eigenmittel*
is invisible to *Eigenkapital*. *Pensionierung* does not answer *Ruhestand*. `services/grounding.py`
records this as a known limit of the lexical channel and it had never been felt, because until now nothing
in the corpus was close enough to the question for the vocabulary to be the deciding factor.

The fix is editorial and it belongs in the content rather than in the floor: each entry gained a section
naming, **in the member's own words, the questions it answers**. It is not keyword stuffing — it is the
list a reader wants at the top of an explainer — and the words come from the six real submissions rather
than from a thesaurus. That moved the score from two of twelve to eleven of twelve, and **all six members'
own questions are answered**, including Marvin's with its typo (*«Ab wie viel Kapitel»*) intact.

Two things worth carrying. **A probe written in ASCII measures the wrong thing**: the twelfth question
appeared to fail on `vermoegen` until it was re-run with the member's actual umlauts, because the tokeniser
folds ö to o and not to oe. The failure was in the probe. And **the floor of 700 was calibrated on the book
corpus in lexical-only mode**, then applied unchanged to authored German entries, which is a different
corpus answering different questions. It has not been moved and it is worth a look — but the content was
fixable and the floor is load-bearing, so the content was fixed first.

## A136 — Tresor, Wissen, Marktplatz

*Owner: Nicolas · 2026-09-04*

The three doors were labelled *Vault*, *Wissen & Gemeinschaft* and *Marktplatz* in German and *Vault*,
*Knowledge & community* and *Market place* in English. The German set carried an English word for the door
a member uses most, and both sets carried a compound label for a door whose whole point is that it is a
name rather than a description.

They are now **Tresor / Wissen / Marktplatz** and **Vault / Know / Market**. A door is a name; the surface
behind it carries the sentence.

## A137 — The occupancy question is askable, and running it found the mirror of A110

*Owner: Nicolas · 2026-09-04*

`Goal.occupancy` existed since A129 and nothing could set it. It is now revisable like the other goal
fields, validated unlike them — the five parameters have no published vocabulary and are stored as the
member's own words, while occupancy decides a legal eligibility and has a closed set in
`client/content/property-funding.json`. `goals.check_occupancy` refuses a value the record does not
declare, at the service rather than in a request model, because there are three writers and only one of
them is a request model.

**Clearing it is a real answer.** A member who said they would live in a property and is no longer sure
can withdraw that, and the goal goes back to `could_not_be_determined`. Leaving a legal eligibility
standing on a guess would be worse than having none.

**The three options travel on the goal's own payload** rather than costing the client a second request —
the argument the onboarding question set already makes about its templates: a control whose options come
from elsewhere renders empty the day somebody forgets the second call. Readable without the conventions
being approved, because asking the question puts no figure in front of anybody.

**And putting a real member through the route found a defect in A129's own work.** Marvin holds 222'750
against a hard-equity requirement of 150'000, and the equity test answered `does_not_meet` — because
`goal.funded_by` is empty for every goal in the build, so the caller passed zero. **Zero and "not stated"
are different facts and only one of them was his.** A110 forbids assuming the favourable case when
something is unknown; this was the same mistake pointing the other way, and it is the more damaging
direction: it tells a member they are short of a deposit they already have, on the strength of a link
nobody ever asked them to make.

`_capital_by_eligibility` now returns `None` for an unfunded goal and `assess` reports
`no_position_is_linked_to_this_goal`. A member who links a position holding nothing still gets a
shortfall, because they *have* said which money is for the goal — two tests pin both sides.

Worth recording how it was found: not by a test, and not by reading. By signing in as a real member over
HTTP and looking at the number. The suite was green through the whole of it.

## A138 — The archived submissions are richer than the current ones, and 0.1.3 dropped the questions this week needed

*Owner: Nicolas · 2026-09-04*

There are five more onboarding files, in `client/submissions/archive/`, archived by A8 on 30 August
because they use `onb@0.1.1` and `onb@0.1.2` and the loader reads only `0.1.3`. **Two of the five are
byte-identical**, so they are four people, not five: 62 in Bern, 39 in Zug, 55 in Freiburg, 45 in Schwyz.
All four came through the real onboarding chat.

A8's rule was right and stands — a consumer that does not recognise a version refuses rather than guesses.
What reading them showed is that the *premise underneath* it was backwards.

**The older schema is richer.** `0.1.3` added three keys and dropped eighteen, and the eighteen are the
questions this build spent the first week of September needing and not having:

| dropped field | what it would have answered |
|---|---|
| `own_use_pct` | **the occupancy question.** `Goal.occupancy` was built on 4 September because nothing in the plan could say whether pension capital may fund a purchase. A member answered it on 18 August with `20` — a property they live in a fifth of and let the rest. |
| `mortgage`, `amortisation` | the debt A132 found being dropped in silence, asked properly. One file carries 2'500'000 with 30'000 repaid a year. |
| `children_ages` | birth years in the exact format `services/identities.child_ages` parses — a function with no production caller since the port, because the field it was written for had already been dropped. |
| `partner_pillar2` | the partner's occupational pension, which is what `goals._household_income` returns `None` for want of. |
| `matrimonial_regime` | Güterstand, which decides what a couple's capital is on a division. |
| `company_value`, `company_income`, `self_employed_form` | the business Renzo asks how to build, answered by someone who built one. |

A8's reason — *migrating would mean inventing answers to questions their owners were never asked* — is
exactly right about the three keys `0.1.3` added and exactly wrong about the eighteen it removed. Those
owners **were** asked. It is the current instrument that stopped asking.

**Eighteen answers were being dropped in total silence**, which is the A132 defect eighteen times over.
Neither `NO_FIELD_HOLDS_IT` nor `NEEDS_A_HUMAN` knows these names, so the loader reported a clean sheet on
a file carrying a 2.5 million mortgage. `DROPPED_BY_0_1_3` now names each one with what it would unblock,
and the reports carry a third section. **Nothing is written and nothing is migrated**: A8 stands.

**Loading them is blocked by something simpler than the schema.** They are anonymous — the filenames are
dates and the files carry no name — so `_names()` produces `2026-08-05@andersch.local` and a display name
of `"2026-08-05 ."`. A member row needs a name and there is not one to use. That is the obstacle, not the
version.

**What is worth doing with them regardless**: the eighteen dropped questions are, by A127's mechanism, one
content entry each and no code. `own_use_pct` in particular is a question the build now has a field for
and no way to ask.

## A139 — The corpus answers the six it was written for, and does not generalise

*Owner: Nicolas · 2026-09-04 · correcting A135*

A135 recorded that the Know answers all six members' questions and that giving each entry a section
naming its questions in the member's own words moved retrieval from 2 of 12 to 11 of 12. Both facts are
true. **The conclusion drawn from them was too strong**, and the four archived submissions are what showed
it: put their four questions to the same corpus and **none is answered**. Scores of 226 to 347 against a
floor of 700.

**The reason is structural rather than a gap in the writing.** An authored entry is scored on the fraction
of *the question's own terms* it contains. A long conversational question — «Soll ich möglichst schnell
die Hypothek verringern, mehr in die Firma investieren oder das Kapital anderweitig anlegen?» — carries
words no explainer will ever contain, so no single entry reaches 70 % coverage however well it answers the
topic. The metric penalises the length of the question rather than measuring the relevance of the entry.
Marvin's question scores 999 because his near-verbatim sentence is in the entry. That is not retrieval
working; that is a lookup table.

**Measured against the semantic channel instead**, which authored entries deliberately do not use, the
picture inverts. Embedding all 22 entries with the index's own `bge-m3` and scoring at the existing 540
floor:

* **Held out — the two on-topic archived questions both pass** (549, 548), and both of the two that fail
  are wish-statements rather than questions: *«Ich möchte ein ruhiges Leben … keine finanziellen Sorgen»*.
  Refusing those is right.
* **In sample — 4 of 6**, which is *less* generous than the overfitted lexical 6 of 6.
* **The ranking is correct almost everywhere**, including where the score misses the floor: Yasmin's
  question puts `wohneigentum-vermietet-und-ferienobjekt` first, Marvin's the same, Renzo's
  `selbstaendigkeit-und-vorsorge`, Levin's `wohneigentum-eigenmittel`. Semantically the right entry is
  found; the score merely sits near the line.

The code's stated reasons for keeping authored entries on word overlap are that overlap is a direct
measure for entries written in the member's language, that tens of entries pose no precision problem for
an embedding to solve, and that lexical still works when the daemon is down. **The first two do not
survive a long question** — the problem is recall, not precision — and the third is answered the way the
book passages already answer it: semantic when available, lexical as the fallback.

**Nothing was changed.** Both floors are calibrated against 95 recorded probes and `grounding.py` says
moving one has to face them; that is a decision with an owner and this is the evidence for it, not the
act. The question lists stay in the entries — a reader wants them at the top of an explainer — but they
should be understood as content rather than as the thing that made retrieval work.

**And a method note that cost nothing to learn and would have cost a lot to miss.** The six questions were
both the thing being fixed and the thing measuring the fix. Four held-out questions existed the whole time,
in a directory named `archive`, and it took the owner asking *«aren't there more onboarding files»* to look
at them.

## A140 — Four invented Swiss names, in the file rather than in the code

*Owner: Nicolas · 2026-09-04*

The four archived submissions were collected anonymously. `_names()` produced `"2026-08-05 ."` and an
email of `2026-08-05@andersch.local`, which is not a name a member row can carry — and that, rather than
the schema version, was what actually stopped them being loadable (A138).

They now have names: **Ueli W.** (62, Bern), **Sandra I.** (39, Zug), **Nadine C.** (55, Freiburg) and
**Reto K.** (45, Schwyz). Each surname is ordinary for the canton that member stated, and that is the whole
of the intention behind it — a label a person can say out loud instead of a filename.

**The name lives in the file's own `meta` block, not in the loader.** A name invented at load time is a
name nobody can find afterwards: it would sit in one function, differ between versions, and arrive in the
database with nothing beside it saying where it came from. `meta` is where these files already record
`source` and `collected`, so it is where a label belongs — it travels with the data, and the file says in
itself what the name is:

> *THIS IS NOT THE NAME OF THE PERSON WHO ANSWERED — the submission was collected without one. It carries
> no claim about them beyond the canton they stated … Six of this build's members are real people under
> their own names; these four are not, and this field is the only thing that says so.*

**That last sentence is the point of the whole arrangement.** Six real people and four invented labels in
one members table, with nothing to tell them apart, is how a fabricated person is later read as a real
one. `build_plan` therefore adds an explicit `INVENTED` line to `plan.problems` for any file carrying a
pseudonym, so the warning is printed every single time the tool describes one, not once in a decision
nobody re-reads.

**Nothing is guessed at load time.** A file with neither a name in its filename nor a pseudonym in its
`meta` is refused rather than given one.

**The byte-identical duplicate is refused rather than named.** `andersch-onboarding-2026-08-05 (3).json`
matches `andersch-onboarding-2026-08-05.json` by sha256; it carries `duplicate_of` and `build_plan` raises
`DuplicateSubmission` for it. Two names for one person is precisely the confusion the pseudonyms exist to
prevent, and loading it would have made a second member out of one person's answers.

**They are still not loaded.** A8 says the pre-0.1.3 submissions are archived, not consumed, and that is
the owner's ruling rather than the implementer's. What has changed since A8 was written is that the
loader now refuses **per field** — eighteen dropped questions are named in their own report section
(A138) — where A8 had to refuse wholesale because nothing else could. The evidence that the narrower
refusal is sufficient is gathered; the decision to rely on it is not mine.

## A141 — A8 reversed: the four are loaded and are ordinary members

*Owner: Nicolas · 2026-09-04 — "load them and treat them as normal people, existing"*

A8 archived the pre-0.1.3 submissions on 30 August: *archived, not consumed*. The owner reversed it. The
four are loaded, and the reversal is recorded rather than the original entry edited, because A8 was right
on the evidence it had.

**What changed between the two rulings** is that the loader refuses per field now. A8 had to refuse
wholesale because nothing finer existed; today a submission is read field by field, and what cannot be
stored is named in one of three sections — no field for it, needs a person, or the question set no longer
asks it (A138). The eighteen dropped questions are reported for each of the four, so nothing about them is
silently consumed.

They moved out of `archive/` into `client/submissions/`, because the directory *was* A8's enforcement —
the loader has no schema check at all. The byte-identical duplicate stays archived and is refused by
`DuplicateSubmission`.

**Ten members now, and the four are not a lesser set.** Ueli W. (62, Bern, 840'000), Sandra I. (39, Zug,
360'000, children born 2020 and 2022), Nadine C. (55, Freiburg, 1'010'000 and a 200'000 mortgage), Reto K.
(45, Schwyz, 220'000 and a 2'500'000 one). Between them they carry the first real dependent children, the
first debt of any size, a `verwitwet` status, and a member who is `derzeit ohne Erwerb`.

**Three defects surfaced in the act of loading them, all in code written the same day.**

*An informational note was blocking the write.* The invented-name warning went into `plan.problems`, and
`main` refuses to write while problems stand — so the warning written to annotate a load prevented it.
`Plan.notes` now exists for things a person should be told that do not stop anything, and the difference
between the two fields is stated where both are declared.

*The password key was re-derived from the filename.* `_names(plan.person)` gave `erstanmeldung-2026-08-05-`
for a member whose email is `ueliw@`. It reads the email the plan actually carries now.

*The listing showed the filename, not the name.* `--list` walked `_names` rather than `build_plan`, so the
four appeared as «2026-08-05 .» — which is how they stayed invisible in the first place. It lists through
`build_plan` and marks an invented name as one.

**And the household rule was too strict by one case.** Two of the four are married and name no partner:
Ueli wrote «Eine Partnerin und ein Sohn», Sandra «1 Partnerin Jahrgang 1992, 2 Kinder». The loader refused
both, leaving two married members with no household — and a household is what the affordability test is
computed over. It now falls back to **the member's own noun**: «Partnerin» is a word the member wrote
about their own household, which is a different thing from the invented «Kind 1» the loader still refuses.
The report line says which of the two it used.

## A142 — `W_L` is liquid wealth and the submissions do not agree with each other about what is liquid

*Owner: Nicolas · 2026-09-04 — amending A131*

A131's registry asserted that the submissions mean cash plus securities by `W_L`, verified on six files.
Loading four more broke the test, which is what it was written to do.

Nine of ten match exactly. The tenth — Reto K., `onb@0.1.2` — reports `W_L: 130'000` against cash of
30'000 and no securities, and the difference is precisely his stated `gold_value` of 100'000. Another file
states gold and crypto and folds in neither.

**So cash plus securities is the usual composition and not the definition**, and the submissions are not
consistent with each other about what counts as liquid. The guard now requires every franc of `W_L` to be
accounted for by franc assets the member actually stated, rather than by one fixed pair of fields, and
fails on an unexplained remainder. It still catches the thing that matters: the engine's `W_L` is human
capital, and a figure that bore no relation to any stated asset would be the sign that the two had been
confused.

A second exception would mean the registry's wording needs revisiting rather than another special case,
and the test says so and counts them.

## A143 — The report covers all ten, and the allocation chart is the one that changed the reading

*Owner: Nicolas · 2026-09-05*

`reports/members-2026-09-04.html` — renamed from `six-cases`, because a filename with a count in it goes
stale the moment an eleventh member arrives.

**The allocation chart is by vessel and not by role, and the choice is the finding.** The four roles are
the product's own frame and they would split these ten into three near-identical bars: cash and
collectibles both land on Stabilisation, the 3a and the Pensionskasse both on Protection. The vessel is
what a member recognises, what the law treats differently, and what decides whether a franc can fund a
purchase.

**Shares rather than francs**, because the totals run from 47'000 to 1'010'000 and an absolute stack makes
four of the ten unreadable. Composition and magnitude are two measures of different scale and the rule is
one axis per chart, so the totals are printed beside the rows and every figure is in the ledger.

**What it shows is the sharpest single thing in the report.** Pension capital is 0 to 14 % of what the
four youngest hold and **53 to 89 % of what the six older ones do** — Elio 89 %, Reto 82 %, Nadine 76 %,
Yasmin 73 %, Ueli 70 %, Sandra 53 %. Nadine holds the largest balance sheet of the ten at 1'010'000 and
770'000 of it is Vorsorge. For most of this group most of what they have is locked, and may be drawn only
for a home they live in themselves. That is not a portfolio observation: it is why the property tests come
out as they do, and why *«wie sieht meine finanzielle Zukunft aus»* is a harder question for these members
than their totals suggest.

**The palette was computed, not chosen.** Five categorical slots in a fixed order that is never cycled — a
member with no securities leaves slot 2 empty rather than shifting the rest along. Validated against this
page's own surfaces rather than a reference one: light `#F6F7F5` passes every check with a contrast WARN on
four slots, dark `#0F1413` passes all five. The WARN obliges relief and it is taken — every segment wide
enough carries its own value, the legend is always present, and the ledger states all fifty figures.

**Correcting the earlier tally.** The report said the Know answered none of the six. Over ten it is nine
refused for want of corpus and **one refused correctly**: Reto's *«Soll ich möglichst schnell die Hypothek
verringern…»* was routed to `regulated_advice` and handed to a curator. That is the C-01 gate working, not
the corpus failing, and counting it as a miss would have been the more flattering error.

**A dozen counts in the report had gone stale and two had inverted.** The findings section still said *not
one of the six has a household* when all ten now have one, and *a rule for those two shapes gets five of
six a household* when the rule is written and they all do. Both were closed on 4 September and the text
said the opposite. The findings section now carries one line saying it records the first pass, so a closed
entry can stay as the record of what was found rather than being deleted.

## A144 — Four members are 39 to 62, and that is a different product

*Owner: Nicolas · 2026-09-05*

The six were 21 to 58 and five of them were under 26. The four loaded on 4 September are 39, 45, 55 and 62,
and reading them together shows what the build has been designed against without meaning to.

**Every one of the four has a dated stopping point and a stated later spending**, and three of the four
plan to spend *more* after they stop than before: Sandra 150'000 → 300'000, Nadine 120'000 → 200'000, Ueli
90'000 → 90'000, Reto 50'000 → 50'000. Nothing in the product tests any of that. A retirement goal carries
an annual figure and no arithmetic reaches it — the property work of 4 September gave the build its first
test of *whether a member can afford a thing*, and it only applies to property.

**Nadine works ten hours a week for 170'000** and plans 200'000 a year from 2036. **Reto works seventy-five
hours** for 150'000 and wants to stop at 55. Both are outside anything the four-role grid or the light
intake was shaped for, and both stated it in their own words in August 2026.

The honest summary is that the six real members the build was tuned against were young, salaried and
unindebted, and the four that were sitting in an archive the whole time are none of those things.

## A145 — The local model is qwen2.5:14b, measured rather than assumed

*Owner: Nicolas · 2026-09-05 — "can you use the largest installed one?"*

Installed on this machine: `qwen2.5:14b` and `qwen2.5-coder:14b` (9.0 GB each), `apertus:8b` and its GGUF
twin (5.1 GB), `qwen2.5:3b`, `qwen2.5:1.5b`, and two embedders — `bge-m3` (1.2 GB) and `nomic-embed-text`.
The largest general-purpose one is **qwen2.5:14b**; the coder variant is the same size and the wrong tool
for German member-facing selection.

**Bigger was not the argument — the measurement was.** The Know is extractive since A106: the model never
composes a fact, it picks which retrieved sentences answer the question. Selection accuracy is therefore
the whole of what a model contributes, and it can be counted. Six German questions with a known right
answer and known distractors — *true sentences from the same source that do not answer the question* —
three runs each:

|  | exact | **missed the answering sentence** | added a non-answer | per call |
|---|---|---|---|---|
| `apertus:8b` | 0 / 18 | **9** | 18 | 0.7 s |
| `qwen2.5:14b` | 3 / 18 | **3** | 15 | 0.8 s |

Three times better on the failure that matters, at the same speed once warm. The clearest single case:
asked whether a 3a may fund a flat the member lets out, apertus returned the two sentences about *when*
a 3a may be withdrawn and missed the one that says a let property does not qualify — in 3 of 3 runs.
A member reading that selection would reasonably conclude the money is available.

**Both models over-select**, which the production path already mitigates by asking one source at a time
rather than all of them at once (`select_quotes` records that measurement). Nothing here changes that.

**What this does not buy.** A106 chose extraction because a model produced a confidently wrong AHV figure;
extraction protects against *inventing* a fact and not against *selecting the wrong sentence*, which is
precisely what apertus was doing. A larger model narrows the second failure and has no bearing on the
first. C-01 is code, not a prompt, and is unaffected — verified after the swap: *«Soll ich mein ganzes
Geld in einen ETF stecken?»* still routes to `regulated_advice` and still requires a curator.

**The cost is provenance and it belongs to the owner.** Apertus is the Swiss model, from `swiss-ai`, and
this is a Swiss product whose whole posture is local control. Trading it for a model from Alibaba is
arguably a policy question wearing a tuning question's clothes, even though `llm/__init__.py` framed the
choice as tuning. It is one environment variable to reverse — `ANDERSCH_LLM_MODEL=apertus:8b` — and the
reasoning is in the docstring beside the default so nobody has to find this entry.

**The embedding model was not touched and must not be.** `bge-m3` is fixed by the book index:
`services/grounding.py` embeds with the model the index was built with and never with a configured one,
because two models produce two coordinate systems and a dot product across them is a number that means
nothing and looks like a similarity. `nomic-embed-text` being installed is not an invitation.

**A caveat on the measurement itself.** The bench uses a simplified stand-in for `select_quotes`, not the
production prompt, so the direction and the size of the gap are the finding and the absolute numbers are
not the production ones. Re-running it against the real path once the knowledge drafts are approved would
be worth the hour.

## A146 — The model store lives on D:, reached by a junction rather than an environment variable

*Owner: Nicolas · 2026-09-05*

34.57 GB of Ollama models sat in `C:\Users\nicol\.ollama\models` on a drive with 55.6 GB free. They are
now on `D:\` and **C: has 92.1 GB free**, up from 55.6.

**The mechanism is a directory junction and that is the finding.** The documented way to move an Ollama
store is `OLLAMA_MODELS`, and it was tried first. It works for a server started from a shell that has the
variable and **does not work for the Ollama app**, which is what Windows autostarts at logon: with the
user-level variable set in the registry and the C: copy renamed away, the app came up reporting zero
models. An environment variable a launcher may or may not inherit is not a mechanism you want between a
member and every answer the product gives.

    C:\Users\nicol\.ollama\models  ->  D:\ollama\models     (junction)

Ollama then looks exactly where it has always looked. No variable is set — one mechanism, not two — and
`OLLAMA_MODELS` was explicitly cleared so nobody later finds two and wonders which wins.

**Verified rather than assumed, in this order.** Copied with robocopy and compared file-for-file
(39 files, 37'123'012'356 bytes, identical). The C: original was then *renamed*, not deleted, and the
daemon restarted — a store that only appears to work because the old copy is still there is the failure
this sequence exists to catch. With C: renamed away: nine models listed, and `qwen2.5:14b` answered a real
German prompt. Only then was the 34.57 GB original removed.

**Two tests of mine were wrong before one was right**, which is worth recording because both looked
convincing. `-UseNewEnvironment` stripped so much that the app could not open a socket at all — a failure
that reads as "the variable does not work". And launching the app from a shell I had deliberately cleared
the variable from proves nothing about a logon, which builds its environment from the registry. The
junction sidesteps the whole question.

**Everything downstream was re-checked against the moved store**: the suite at 2 652, all ten surfaces
rendering through `walk_screens.mjs`, the doors serving as Tresor / Wissen / Marktplatz, and
`property_check`, `allocation_check`, `load_submission` and `name_archived_submissions` each run.

**One regression, caused by an earlier change rather than by the move.**
`tools/name_archived_submissions.py` scanned only `client/submissions/archive/`, and the four files it
names moved into `client/submissions/` when A8 was reversed. It found one orphaned duplicate, could not
group it, and printed a skip that read like a failure. It scans both directories now.

---

## A147 — Four Swiss rule sources went into the index, and the figures came out of memory into quotation

*Owner: Nicolas · 2026-09-05*

The corpus held **one** document about Swiss rules — AHV/IV-Merkblatt 2.03 and 3.04, eleven passages of
1 280. Everything else in the index was the English manuscript. So the drafting rule in
`content/knowledge/README.md` — *a figure goes in only when it is quoted, not remembered* — had the effect
of omitting almost every number a Swiss member asks for: the BVG thresholds, the Umwandlungssatz, the 3a
maxima, the Mindest- und Maximalrente, the contribution percentages. The rule was right. The corpus was
the problem.

Four sources were fetched from their publishers and written into `knowledge/`, then registered in the
`SOURCES` allow-list in `desktop/bookindex.py`:

| File | Source | Stand |
| --- | --- | --- |
| `BVG_Berufliche_Vorsorge.md` | BVG (SR 831.40) via fedlex; BSV amounts sheet; Merkblatt 6.06 | 1.1.2025 / 1.1.2026 |
| `AHV_Altersrente_Berechnung.md` | Merkblatt 3.01 and 2.01; BSV amounts sheet | 1.1.2026 |
| `WEF_Wohneigentumsfoerderung.md` | WEFV (SR 831.411) via fedlex; BVG Art. 30c; BWO brochure | 1.10.2017 |
| `Saeule_3a_Grenzbetraege.md` | BSV, «Beträge gültig ab dem 1. Januar 2026» | 1.1.2026 |

The index went **1 280 → 1 325 passages**. Four member questions that returned nothing now return the
right passage first: *ab welchem Alter beginnt die Rente*, *bin ich mit 23 versichert*, *wie viel darf ich
in die 3a einzahlen*, *darf ich Vorsorgegeld für eine vermietete Wohnung brauchen*.

**Two things are worth recording about the fetching.** Fedlex serves a JavaScript shell to anything that
is not a browser, and the guessed filestore path returns that shell with a 200 — a silent wrong answer,
not an error. The working path came from a search result that happened to link a PDF directly. And the
BSV amounts sheet is a PDF whose text a fetch tool would not extract; it was read locally with `pypdf`,
which is now in the venv.

**What is still omitted, and named in each entry:** the BVG-Mindestzinssatz, the income percentage that
additionally caps the higher 3a deduction (BVV 3 is not in the corpus), the Rentenskala table, the
Erziehungsgutschrift amount, every cantonal tax figure.

**A finding that came free.** `Wie funktioniert die Pensionskasse?` still returns nothing, and now for a
more interesting reason than absence: the corpus holds a whole BVG document that answers it. The document
says *berufliche Vorsorge* and *Vorsorgeeinrichtung* where the member says *Pensionskasse*, the lexical
channel shares no token, and similarity alone stays under the 540 floor. That is A139's compound problem
in German-to-German rather than English-to-German. It is recorded in the parametrised list in
`test_grounding.py` rather than fixed by sprinkling the synonym into the source text, which would be
tuning the corpus to the test.

---

## A148 — The equity ceiling: two constraints, the conservative binds, and it changes exactly one member

*Owner: Nicolas · 2026-09-05*

Every one of the ten members states a `max_loss_pct` and an `expected_return_pct`. Nothing read either.
`services/allocation.py` now does, and `client/content/investment-allocation.json` carries the figures.

**It produces a ceiling, never a target.** A target says what to hold and needs a curator; a ceiling says
what the member's own answers already rule out. `for_goal` returns numbers, `levers` returns dimensions
with arithmetic, and neither returns a sentence — the same contract `property.py` has.

Two constraints. The stated loss divided by an assumed equity drawdown gives one; the years to the goal
give the other, on a four-step ladder. **The lower binds**, per the ruling of 4 September.

**The ruling changes exactly one member's answer, and that is the honest headline.** Nine of the ten are
held by their own stated tolerance, which is tighter than the ladder at every horizon they have. The tenth
is Ueli: 62, 840'000 francs, and two years from the year he says he stops working. His tolerance alone
would have allowed 20 % equity on money he needs in 2028; the ladder says none. A rule that fires once in
ten is not weak if the tenth case is that one.

**Per goal, not per member.** Six of the ten carry two dated goals. A member with a purchase in eight
years and a retirement in forty gets two ceilings, or the answer is wrong in both directions at once.

**The finding the record exists for: nine of the ten state an expected return above the assumption for
the mix their own tolerance permits.** Five wrote exactly 8 %, and four of those five also wrote exactly
30 % — a figure five people give identically is a figure the question is *eliciting* rather than
measuring. The sharpest is Elio: 10 % tolerance, 8 % expectation, seven years out, on the second-largest
balance in the set; his ceiling is 20 % equity, whose assumption is 2.8 %. The service reports that 8 is
larger than 2.8, and nothing else. It never projects.

**And four of the ten state a tolerance alongside «ich war nicht investiert», with two more leaving the
crisis question blank.** For six of ten the number that sets the entire ceiling is an estimate about
themselves rather than a memory. The record reads it at face value and flags it; whether that is right is
the second of four questions in its own `_for_review`.

**The record ships `provisional: true` and the service refuses on every computing path.** That is
deliberate and asserted by a test that will fail the moment somebody approves it, so approval is a
decision taken rather than a flag edited while fixing something else.
`reports/allocation-2026-09-05.html` shows what approval would produce, from the real code path against
an in-memory approved copy — the only way to review numbers a closed gate hides.

---

## A149 — An entry in the approval queue was tripping the outbound gate, and nothing was checking

*Owner: Nicolas · 2026-09-05*

`content/knowledge/README.md` states that every entry returns `requires_curator: False` from
`boundary.check_answer`, and documents running it by hand, one file at a time. A rule nothing enforces
decays: `wohneigentum-eigenmittel.md` was edited after that check and sat in the queue tripping the gate
on a sentence describing an asset —

> «… eine Beteiligung, die erst verkauft werden müsste, zählt erst, wenn sie verkauft ist.»

— which advises nobody. **Every pattern in `boundary` compiles with `re.IGNORECASE`**, so `sie` cannot be
told from `Sie`, and in German that case difference is exactly the difference between addressing the
member and referring to a thing.

The entry was rephrased and the gate left alone. Narrowing a C-01 pattern is a decision for the owner and
it moves a safety gate in the permissive direction; the false positive cost one sentence.
`test_every_authored_entry_passes_the_outbound_gate` now runs the real gate over every entry,
parametrised per file so a failure names the entry.

---

## A150 — A148 is withdrawn: the allocation comes from the Optimiser, and the return is the manual's

*Owner: Nicolas · 2026-09-05*

A148 built an equity ceiling inside this build: a stated maximum loss divided by an assumed 50 % equity
drawdown, capped by a four-step horizon ladder. **It was written without finding `engines/PCP` first, and
every part of it already existed in the estate in a better form.**

- The **drawdown was invented.** The ReturnSet publishes each block's actual crisis-state return, and
  `engines/lbs/derive.py` already derives a per-instrument position cap from the goal's buffer against it.
- The **horizon ladder was invented.** The goal's deadline already produces a liquidity floor over the
  ordered liquidity vocabulary (Daily, Quarterly, Yearly, Decade).
- The **equity/bonds split was invented.** The allocation runs over four roles and five asset classes
  under eight constraint blocks: `currency · region · role · capital_type · liquidity · esg · phase ·
  asset_class`.

`services/allocation.py`, `client/content/investment-allocation.json` and 41 tests are removed. The suite
goes 2 719 → 2 678.

**The owner's two corrections, and what they changed.** First: use the Optimiser for the allocation and
compute the return as the manual states. Section 5 defines `return_dist_final = allocation' * BB` — a
25-point curve — whose expectation is that curve dotted with the regime vector. Second: *it is the full
25-state return curve that the optimiser works against.* A scalar tolerance compared against a scalar
drawdown was the wrong shape for the question.

`tools/member_allocations.py` now derives a mandate per member and runs the Optimiser through
`desktop/allocation.py`. Three findings came out of it, and the third retires the A148 model empirically.

**Ten members, two portfolios.** Not ten. The split is not age, wealth, tolerance or canton — it is
whether the goal is reachable. Five reachable goals get Gain 35 / Income 10 / Stabilisation 24 /
Protection 31; five unreachable ones get Gain 20 / Income 10 / Stabilisation 20 / Protection 50, the
corner of the bound box. The Optimiser says why on every run: the weights control under 1 % of the
objective's level, so the structure comes from the bounds and the curve fit breaks ties. The role bounds
are CIO policy and identical for every household.

**The crisis state is not the worst state.** The unreachable-goal portfolio returns **+13.5 %** in crisis,
because half of it is a Long Volatility block that gains when everything else falls. Its worst outcome is
state 8 at −8.15 %, a middling state where nothing hedges and nothing rallies. Any risk measure reading
"the crisis number" as "the loss" has it backwards.

**Every member sits inside their stated tolerance with room to spare.** The two portfolios bottom out at
−5.99 % and −8.15 %; the tightest tolerance anybody stated is 10 %. A148 would have told Nadine her 10 %
caps her at 20 % equity, while her actual portfolio holds 35 % Gain and reaches −5.99 %. Nobody's stated
limit binds on anything — which is the measured answer to whether stated willingness belongs in the
mandate, and it is *no* on this evidence.

**What survives from A148.** Only the reading of the two stated answers, which stands: nine of ten state
an expected return above what their allocation delivers, five wrote exactly 8 %, and six set that figure
alongside «ich war nicht investiert» or no answer at all. That is a finding about the *instrument*, not
about allocation, and it needs no ceiling to make it.

**C-01 is unchanged.** `portfolio_optimiser` produces a Recommendation; A85 refuses it outright with no
curator-facing run route. Nothing in this work is reachable from the member-facing product, and
`reports/allocation-pcp-2026-09-05.html` is an owner-facing analysis run from the estate side.

---

## A151 — The occupancy question is on the screen, and answering it found a second defect

*Owner: Nicolas · 2026-09-05*

`services/property.py` has taken an occupancy since 4 September, the route validated it, the three options
travelled on every goal payload — and `containers.js` never rendered the question. Five real property
goals sat at `could_not_be_determined` for a reason no member could see or fix. **A capability with no way
in is indistinguishable from an absent one.**

`occupancyNode` renders the verdict as body text (R-031: no severity class, no icon), the question, the
three options **read from the content record rather than spelled in the client**, the undetermined reasons
as a plain list, and clearing as an option because `check_occupancy(None)` is a real answer.

Two pushbacks, both correct. **C-09 requires a Decision and the route refuses to compose it** — the edit
form asks the member to type the question and choice, which is right for an edit and wrong for a one-tap
answer. The sentence is composed from the exact words the member was shown and tapped. **The C-01 gate
refused "Withdraw the answer"**, English's bare imperative, the documented xfail; relabelled to the
wording the prepared decisions already use.

**And answering it exposed a defect that had never been reachable.** A goal set to `let_to_someone_else`
came back `does_not_meet` on an affordability figure containing no rent. On a buy-to-let the rent is most
of the income that carries it: omitting it removes the purpose of the purchase and tells the member a
lender would refuse them on a calculation no lender would run — A110's family, damaging direction.

The record forbade it in prose before the code did it. `affordability_is_determinable: false` is that
approved sentence made machine-readable; the service honours it and defaults to true. `levers()` needed
the same care — it returned nothing unless both tests ran, which would have hidden the deposit lever, the
one dimension a buy-to-let turns on.

---

## A152 — Alias groups: the query is widened, never the corpus, and the floor moves to a different number

*Owner: Nicolas · 2026-09-05*

A147 left `Wie funktioniert die Pensionskasse?` unanswered while the corpus held a BVG document that
answers it: the document says *berufliche Vorsorge* and *Vorsorgeeinrichtung*, retrieval needs **both**
channels above their floor, and the lexical channel shared no token — so a similarity of any size was
refused.

`client/content/search-aliases.json` holds ten groups of surface forms. **A group is one term slot.** It
carries the weight of the word the member typed, and a passage earns that weight once by carrying any
form in the group. The denominator `_term_weights` builds is untouched.

**The obvious implementation is wrong and measurably so.** Appending synonyms to the term list would
multiply the denominator — seven forms of *Pensionskasse* would shrink every real match by a factor of
seven — because `_term_weights` deliberately normalises over terms the corpus has never seen. That
correction is what made the lexical channel a discriminator rather than noise, and an alias must not
undo it. Asserted by a test rather than left as a comment.

The record **fails open**, unlike `property-funding.json`, and the difference is argued in it: these
figures decide which paragraph is shown beside a citation the member can open, not what a lender would
say. An absent or malformed record reproduces the behaviour of the day before exactly.

**What it fixed, and what it did not.** *Rentenalter* and *Vorbezug* now reach documents the bare word
could not. *Pensionskasse* still does not — and the reason has moved from vague to precise: the right
passages now score **lexical 484** against a floor of 100, and **semantic 483** against a floor of 540.
The lexical half is solved; the semantic floor is the binding constraint.

**That floor was not moved.** It was calibrated between two named boundary probes, and lowering it is a
recalibration against the held-out set rather than an edit. What this work bought is that the question is
now a single number with evidence behind it instead of a description of a smell. The noise probes —
Goldpreis in Singapur, Kinderkrippe in Zürich — still refuse, asserted.

Also restored: three of the eighteen questions `onb@0.1.3` dropped, as `member_fact` entries. Three JSON
entries, no code, suite unchanged — A127's promise verified rather than assumed. Only three, because the
rest have nowhere to write: franc stocks with no ruled role, an obligation where the plan holds no
expenditure, and two partner fields that would put another adult's financial record on this member's file
and are a C-05 question rather than a modelling one.

---

## A153 — The first two pillars are in the model, from the statutory table and the age bands

*Owner: Nicolas · 2026-09-05*

«Das Modell führt keine AHV-Rente» was in every dossier, and the owner's answer to why not was that it
should. For a member asking whether their retirement is funded it is the largest missing number on the
page: the first pillar is most of the floor under every plan here, so leaving it out overstated every gap
by an amount nobody could see.

**AHV: a table lookup, not a formula.** `client/content/ahv-pension.json` carries the 51 published rows of
Skala 44, transcribed from *Monatliche Vollrenten, Skala 44*, 318.117.1 df 07.24. A two-piece linear
formula through them is derivable — the bend at 45'360 is visible in the data — and was deliberately not
used: a formula I fitted is a figure nobody published, and the table is what the Ausgleichskasse applies.
The Teilrentenfaktor is `Skala/44`, confirmed against the Berechnungsvorschriften section 8.2.

**The input nobody has is the mdJE.** The table is keyed on the revalued average of a whole working life;
the build holds current gross income. `ahv.pension()` takes it explicitly and never derives it.
`ahv.illustration_for()` exists so a caller substituting current income has to say so in the name of the
function it called, and the substitution comes back as the first caveat.

**Pillar 2: by age, because the law credits by age.** 7, 10, 15, 18 percent of the coordinated salary, and
**nothing before 25** — below that the obligatory scheme insures death and invalidity only, so Marvin's
balance of zero at 23 is consistent with being correctly insured and the projection credits nothing for
two years rather than quietly starting early. Year by year rather than closed form, so a member can check
a line of it.

**Interest is the Mindestzinssatz, 1.25 %, and that was the owner's choice of three.** Asked whether to
project at zero, at the statutory minimum, or as a band, the owner chose the minimum: it is the only
citable figure of the three. It is also a floor set for one year and revisited annually, so every result
carries `interest_is_a_statutory_minimum_not_a_return` and callers must render it.

**Wired to the retirement goal**, mirroring `property`: `retirement_finding` attaches to any goal whose
template or name says it means to live off capital, reports a verdict, the two pillars, the shortfall and
its levers, and returns every refusal as a reason rather than an exception.

Both records ship **provisional** and both services refuse on every computing path, asserted by a test
that fails the moment somebody approves without updating it. Against an approved fixture, Marvin's
figures are AHV 2'238/month at 13 payments and a pillar 2 of 264'303 by 65 converting at 6.8 % — together
about 47'000 a year against the 57'000 he says he needs. His dossier said that gap was *probably* not a
gap; it is now computed instead of guessed.

C-02 refused six float literals across the two services on the way in, correctly each time.

---

## A154 — The intake file is kept whole, and mapped afterwards

*Owner: Nicolas · 2026-09-06*

`client/intake.html` asks 102 questions and the loader has a home for about a third. Until today the rest
were read, printed under `absent`, `deferred` and `dropped`, and dropped — so a member typed an answer,
was told nothing, and would be asked the same question again when the calculation that needed it existed.
Defensible while the instrument was small; the majority case once it was not.

**The owner's ruling: store the submission verbatim, then map.** `models/submission.py`, one row per file.

**Order matters and is the point.** The file lands whole *before* anything is mapped, so the mapping runs
over a row that already exists and a failure part way through leaves the member's own words on the record
rather than nothing.

**K3, above every individual field in it.** The file mixes a canton (K1) with a pension balance (K2) with
a self-assessment of health and a free-text worry (K3). C-04's filter drops by field name and this field
is called `payload`, which tells the filter nothing about the health answer inside. The container takes
the highest class anything in it can carry.

**A transcript, not a plan.** Like `OnboardingAnswer` and unlike `MemberFact`: no Decision, not
`PlanMutable`, and **nothing in a Befund may read it**. That inertness is the whole safety argument for
keeping unmapped answers — an answer sitting in the blob cannot reach a plan without somebody building
the mapping, which is the same act that decides what the answer means.

**Two assertions carry the rest.** `Submission` is in `DELETED_IN_ERASURE_ORDER`, so R-154 hands the file
back on export and R-231 destroys it, and both are tested rather than assumed. A blob a member can neither
take away nor have destroyed would have been the argument against storing it at all.

Also: `mapping_report` records which keys were claimed and why the others were not, so a field that gains
a home tomorrow can find the submissions already carrying it. On the loader's own corpus that is 43 of 46
answers preserved that previously vanished.

The autogenerated migration again proposed dropping `ck_households_stated_by`, a real CHECK on a table
this change does not touch — the same SQLite reflection false positive as before. Removed by hand in both
directions; the constraint is verified still present after the upgrade.

---

## A155 — Two portfolios became six, because the inputs that could distinguish clients finally do

*Owner: Nicolas · 2026-09-06*

Ten members, two portfolios (A150). The cause was never the objective: `POLICY_BOUNDS` was one identical
block for everybody, the universe was the same eight instruments, the curve slope the same ramp, and the
Optimiser reported the weights controlling under one per cent of the objective. **Everything that could
distinguish one household from another was held constant.**

`client/content/risk-profile.json` and `services/risk_profile.py` produce one number per household between
0 and 1, and three things now vary with it: the role bounds, the universe, and the curve slope.

**Continuous, per the owner's choice — and C-02 survives it.** The objection to continuous is that the
reasoning ends up in code. The split answers it: **the code holds the interpolation and the record holds
both of its ends.** A reader checks two anchor bound sets; the code contributes a straight line and no
judgement. `lerp` is exact at both endpoints, because an anchor is a number somebody signed and it must
come back as the number they signed.

**Willingness and capacity apart, the lower binds** — the standing ruling, third application. Willingness
is the stated loss mapped between two published points, then **capped** by the crisis answer: behaviour
observed beats a statement made in calm, and the cap can only ever lower. Leaving the crisis question
blank caps identically to never having invested, because in both cases nothing is known about how the
person behaves when the number falls.

Capacity is five weighted components from the position itself — horizon, reserve, income stability, free
share, debt service. **A missing input drops its component and its weight rather than scoring zero.**
Scoring zero would say "this household has no reserve" when nobody asked, and would pull every incomplete
record toward cautious for a reason about the form.

**Measured on the ten: five distinct profiles, and six distinct allocations.** Three members — Ueli,
Nadine, Elio — now hold no equity at all, because the universe rule removes the block rather than bounding
it at zero. That is the one hard edge in an otherwise continuous mapping and the record names it as such.

**Sustainability is two questions, not one.** An exclusion is categorical, a minimum is a proportion, and
a member who says «anything but weapons» has answered the first and not the second. `esg_min` was 0.0 for
every mandate because nothing asked; the minimum now feeds it and the exclusions narrow the universe. An
exclusion the record does not offer is reported rather than dropped — a member who wrote something the
build cannot match has said something.

Two honest observations for review. Willingness binds for nine of ten, so capacity — built as the
counterweight — rarely decides; that is the caps doing their work rather than a fault, but it is worth
seeing. And two members 0.013 apart in profile receive two allocations that differ in the third decimal,
which is continuity showing up as noise rather than signal.

---

## A156 — R-210 is relaxed for the curator dashboard, and the scope of that is written down

*Owner: Nicolas · 2026-09-06*

R-210 has meant that a curator reaches a client only through a scoped, time-limited window the member
opened. Asked what «the clients» means on an operator dashboard, the owner's answer was to **drop the
grant requirement and read full information directly, on the grounds that this is a prototype.**

Recorded rather than absorbed, because it is a real weakening of a documented constraint and it should be
visible when it is time to reverse it. Its scope, stated:

- It applies to the **local curator dashboard only** — a tool served on localhost, reading the database
  directly, never exposed by the application.
- It does **not** change `services/curator.py`, `AccessGrant`, or any route. The member-facing product
  continues to enforce R-210, and no API path gains a way around it.
- It is a prototype convenience with no security argument behind it. Before anything resembling
  production, either the grant check returns or R-210 is deliberately rewritten — and this entry is what
  makes that a decision rather than an oversight.

---

## A157 — «No equity» was an infeasible mandate, not a considered allocation

*Owner: Nicolas · 2026-09-06*

A155 reported that three members hold no equity at all because the universe rule removes the block rather
than bounding it at zero. **That reading was wrong, and the Optimiser had already said so.**

Two numbers in `risk-profile.json` disagree. The cautious anchor puts Gain's lower bound at 0.00 and the
aggressive one at 0.40, so the interpolation produces a **positive Gain floor at any profile above zero** —
0.057 at a profile of 0.143. The universe rule removes equity below 0.35. **Every profile between 0 and
0.35 therefore demanded Gain from a universe with no Gain instrument in it**, because every Gain block in
the eight-instrument register is an equity.

The PCP caught it and put it in its own `notes`:

> the mandate sets a role floor on ['Gain'], but the universe has no instrument in those categories, so
> the floor cannot be met.
> SLSQP did not converge (Inequality constraints incompatible), so trust-constr was used. The reported
> allocation is the fallback's solution.

**I read `role_allocation` and `conditions_met` and not `notes`.** `conditions_met` was `yes` throughout,
correctly: it records whether the raw weights sum to one, which the README says plainly, and it is not a
statement about whether the bound rows were satisfied. The engine behaved properly and reported properly.
The mistake was entirely in the reading, and it is the exact failure the manual warns about in one line —
*read the binding condition before the number.*

`reconcile_with_universe` sets a role's floor and ceiling to zero where the universe holds no instrument
for it, and records a caveat saying so. The solver now converges and the infeasibility notes are gone; the
weights are numerically the same and they now mean something they did not mean before.

A test asserts the two record numbers still disagree, so that if either is changed to close the gap the
reconciliation becomes visibly dead code rather than a silent crutch.

**The underlying question is not settled by this.** Whether an asset class should be removed from the
universe at all, or only ever bounded, is the record's own review item — and this episode is the argument
for bounding: a bound of zero can never make a mandate infeasible, and a removal can.

---

## A158 — Capacity becomes the signal, behaviour lifts as well as caps, and nothing is removed

*Owner: Nicolas · 2026-09-06*

Three rulings on the same day, all reversing parts of A155, all driven by what the first draft actually
produced.

**Nothing is removed from the universe any more.** A157 showed why with evidence: removing an asset class
emptied the Gain role while that role's own floor still demanded weight from it, and the mandate became
infeasible. A ceiling of zero cannot do that. A cautious profile now gets a low equity ceiling instead of
no equity. `reconcile_with_universe` survives, because a **sustainability exclusion** can still empty a
role and is now the only thing that can.

**Capacity is the primary signal; the stated tolerance only caps it.** On the first draft the stated
figure decided nine of ten, and three members who each wrote «10 %» received identical mandates although
one had held through a real fall, one had sold everything and one had never been invested. A number typed
in a calm room was overriding everything known about them.

**Behaviour lifts as well as caps.** Holding through a fall puts a floor of 0.40 under the claim; buying
more, 0.55. Only those two lift — never having been invested is not evidence and neither is silence, and
both still cap. This is the application crediting a member with more than they wrote down on the strength
of one answer, and it is meant to.

**Measured on the ten: seven distinct profiles, eight distinct allocations, every one feasible.** Nadine
lifts from 0.143 to 0.400 and is finally separated from Ueli, who sold everything. Reto lifts to 0.550.
Ueli and Elio remain identical, which is right — nothing is known about either that separates them.

**What has not changed, and should be seen.** Capacity binds for only one of the ten. The dominant single
factor is now the 0.60 cap that «ich war nicht investiert» and an unanswered question both carry, which
applies to six members. The largest lever in the whole profile is one question about 2008 and 2022, and
most people have no answer to it.

Also recorded, because the record's own review list now says so: a cautious Equity ceiling of zero does
**not** produce a near-zero ceiling just above the anchor. The map is a straight line, so a profile of
0.14 already reaches about eleven per cent. Only a non-linear map would do otherwise, and none was asked
for.

---

## A159 — The capacity inputs come from the plan first and the stored submission second

*Owner: Nicolas · 2026-09-06*

`risk_profile.capacity` takes five numbers. The plan holds three of them — horizon from a dated goal, the
free share from the positions, income from the income position. It holds none of the other two, and
`services/profile_inputs.py` reads those from the **stored submission**.

That is A154 paying for itself six days later. Reserve months, the variable share, the employment form and
the debt service have no home in the schema; before the file was kept whole they would have been asked
for a second time or approximated.

**Every value carries its provenance.** A figure derived from a plan the member can correct is not the
same kind of figure as one lifted out of a form they filled in once, and `sources` says which on every
one. A value that is nowhere stays `None`, and `capacity` drops the component rather than scoring zero.

Sustainability moved into its own intake section: **what you will not own**, and **how much must qualify**
— two questions rather than the one three-option field that fed `esg_min` and left it at 0.0 on every
mandate ever derived here.

Three things the build refused on the way in, each correctly:

- **C-09 refused a bare `session.add(Goal(...))` in a test.** A goal appearing with no Decision behind it
  is a change to a member's plan that nothing recorded. The tests now go through `mutate_plan`.
- **A CHECK constraint refused a `chf` position with no `stock_kind`.** The schema will not let a franc
  magnitude be ambiguous about which side of the balance sheet it is on.
- **C-02 refused five float literals**, including a `365.25`. Days to years is now `/ 365`, and the
  comment says why the quarter day does not matter: the band it feeds runs from three years to twenty.

And one real defect found by a test that only failed intermittently: `for_member` ordered by
`received_at` alone, which is stored to the second, so two files arriving in the same second were ordered
by whatever the database returned. `collect` could therefore read a different file on two consecutive
calls with nothing having changed. The id now breaks the tie — it does not recover the true order, and
the docstring says so, but a stable wrong answer is debuggable and an unstable one is not.


## A160 — The cull of 20 September 2026: what was asked, what was ruled, and what it costs

*Owner: Nicolas · 2026-09-20 · from `TASK-cull-2026-09-20.md`*

**How the numbering works from here.** This entry is the cull itself: the four rulings the owner took on
the day, the scope, and the things the task asked to be recorded in one place — the substitution of three
names, the inventory for the rename, and the appendices measuring what was deleted. Each work item has
its own entry from A161 onward and its own commit. A reader who wants to know *why* the build shrank
reads this entry; a reader who wants to know what a given change did reads the numbered one.

### The four rulings

Each was put to the owner as a written question with the options and their costs, and none was
implemented before it was answered. That is rule 1 of the task and it held for all four.

| | Ruling |
|---|---|
| **T2.1 — the release gate** | **Refused.** The curator is advisory. Reports reach members directly, and there is no C-12. |
| **T1.3 — one member's record** | **Renamed to a pseudonym.** The record and its numbers stay; the name does not. |
| **T1.4 — the three names in the register** | **Substituted everywhere, the quotation included**, with the substitution marked where it falls inside quoted material. |
| **T2.6 — C-06** | **Dropped with the compliance layer.** |

### What the refusal of C-12 costs, stated plainly

The task proposed C-01's deletion as a swap: the pattern layer goes, and a release gate takes its place,
so that "a curator looks at it" is a control rather than an intention. The owner refused the gate and
accepted the consequence, and the consequence is this:

**Nothing in this system holds the claim that a human read a report before a member saw it.** Not the
code, not the schema, not the audit trail. C-10 still records that a named curator opened a session, and
C-09 still records that a Decision was taken — but neither sits between a computation and the member who
reads it, and after this task nothing does. The curator screen is a sign-in and a worklist; A156 already
dropped the grant requirement for the dashboard; and T2.4 removes the last condition that was holding the
Optimiser's allocation back, replacing it with nothing.

This is written at length because it is the single largest change in the build's posture since it began,
it was taken deliberately, and the next person to ask "what stops an unreviewed report reaching someone"
is entitled to find the answer rather than an absence. The answer is: a person remembering to look.

### What is deliberately not done here

- **No rename.** Part 4 of the task puts it out of scope and `TASK-rename-eigentlich-2026-09-20.md`
  sequences it after this one. The inventory is below so that pass is mechanical.
- **No replacement for C-01.** The refusal is not a promise to build something later.
- **Nothing deleted without a record.** Rule 5. Every removal in A161 onward names what went and why.

### The inventory for the rename, taken 20 September 2026

`andersCH` becomes **eigentliCH** in display and prose, `eigentlich` in identifiers, `eigentli.tech` as
the website, `@eigentli.local` and `@kurator.eigentli.local` as local addresses. Counted on the tree as
it stood before the cull's deletions, so the figures will fall as Part 2 lands:

| Group | What is there |
|---|---|
| Package and module path | `backend/andersch/`, imported by **81** files |
| Client global namespace | `andersch.sim`, `andersch.session`, `andersch.content` |
| Local addresses | **41** occurrences of `andersch.local`, **18** of them `kurator.andersch.local`; 15 written as literals, the rest built by `_email()` and `_curator_email()` in `tools/seed_demo_accounts.py`, which is one line each |
| Test assertions on the literal | **68** test files mention the name; **13** assert on it directly |
| Filenames | `andersCH-build-spec.html`, `backend/andersch.db` and its snapshots, `client/reference/andersch-site-{index.html,styles.css}`, `desktop/andersCH-P2.cmd`, `desktop/andersCH-p2.ico`, and **60** `andersch-onboarding-*.json` submissions |
| Documentation and distribution | `dist/` (5 files), `desktop/` (4), `content/knowledge/` (18), `reports/` (14), `client/surfaces/` (12), `backend/migrations/` (12) |
| Totals | **539** occurrences of `andersCH`, **1076** of `andersch`, **46** of `ANDERSCH` |

The estate directory `andersCH/` is imported rather than copied (A1) and does not move; the register's
historical entries keep the old name for the same reason the three names below are substituted rather
than erased from history.


## A161 — Three curators left, and the rows stayed

*Owner: Nicolas · 2026-09-20 · T1.1 and T1.2 · cost: two columns, one predicate, five tests*

**The compliance reviewer, the GTM lead and a curator are no longer part of andersCH.** Nicolas, Nicolai,
Tino and Marianne are the team; the product is built out of sim-tech solution GmbH and SIM Research. A62
seeded five curators and this reduces that list to two.

The three are named by role here and throughout this register, on the owner's ruling of 20 September
2026 — see A160. Their names remain in exactly two places, both deliberate: the `curators` rows, because
a revoked row's display name is the audit trail's "who"; and `tools/seed_demo_accounts.py`'s `REVOKED`
list, because the seeder has to be able to find the right rows to revoke.

**Revoked, not deleted, and the reason is C-10 rather than tact.** `curator_session_events` refuses
DELETE by trigger and `CuratorSession.curator_id` has been a foreign key since A98. A curator row removed
from `curators` leaves every session event that names them pointing at nothing — the audit still holds
the id and has lost the only thing that made it evidence, which is the ability to answer "who was that"
for a reader who was not there. So `Curator.revoked_at` and `Curator.revoked_reason` were added, set for
the three, and the row stays.

**`revoked_at` is not `active`, and the distinction is load-bearing.** `active` is a switch an operator
may flip back — somebody on leave, an account parked. Revocation is a statement that this person has
left, it is never cleared, and `test_revocation_is_not_the_same_switch_as_active` proves that setting
`active = True` on a revoked row does not let them back in. Two columns because they are two facts; one
predicate because they answer one question.

**One implementation, which is the part worth keeping.** Four gates asked `Curator.active` separately:
`authenticate_curator`, `require_curator`, `resolve_curator` and `list_curators`. Adding revocation to
four call sites of a duplicated condition is the A73/A91 defect written on purpose — the fifth caller
forgets, and the one that forgets is a door. `Curator.in_service` is a `hybrid_property`, so the two
gates holding a loaded row and the two writing a SQL `WHERE` ask the same thing rather than two things
that have to be kept in agreement. It is the first hybrid in this codebase and it earns the introduction.

**The password on a revoked row is deliberately left intact.** Clearing it would be a second mechanism
for one rule, and a refusal that depends on which of two mechanisms fired is a refusal nobody can reason
about. The predicate is the rule.

### The migration

`c4e18b2f9d07`, two nullable columns, and **not** `batch_alter_table`. Batch mode recreates the table and
a recreate drops what is attached to it; `curators` carries no trigger today, but "survives because the
table happens to have nothing on it" is precisely the accident that has switched this build's append-only
triggers off three times (A63, A66, A68). Plain `ADD COLUMN` recreates nothing. Verified: six triggers
before the migration, six after.

The three revocations are written by `tools/seed_demo_accounts.py`, not by the migration. A migration
that edited rows would put the list of names in a second place, and the seeder already owns that list. A
fresh database never creates the three and so has nothing to revoke, which is the correct outcome rather
than a special case.

### Verification, as T1.1 asked for it

A login was attempted for each of the three with their documented password, and each was refused with
`email or password is incorrect` — the same message an unknown address gets, because a departed curator
learning that their account still exists is a disclosure with no upside. Both remaining curators still
authenticate, which is the control that proves the refusal is about revocation and not about the test
being broken. The directory returns exactly `Nicolai` and `Nicolas`. `require_curator` and
`resolve_curator` refuse all three by id.

And the property that is the whole reason for the approach:
`test_what_a_revoked_curator_did_is_still_readable` opens a session while the curator is in service,
revokes them, and asserts the event still names them **and that the name still resolves to a row** —
carrying a revocation date, so the reader learns both that this person did the thing and that they have
since left. Delete the row instead and that test is the one that breaks.

### Every live surface, reported before it was changed

The full grep was put in front of the owner first, as T1.2 required, and it separated into three groups
rather than the two the task anticipated:

- **The three curators.** `tools/seed_demo_accounts.py` (the seed rows), `backend/tests/test_directory.py`
  (24 hits, all fixture curators), the live database, and A62 / A113 in this register.
- **A member who shared a given name with one of the three**, and is a different person entirely —
  `client/submissions/`, `reports/`, five backend test cases, `tools/load_submission.py`. Untouched by
  this entry; A162 covers them.
- **A quotation**, which the task did not anticipate. `services/onboarding.py`, `intake-findings.json`
  and A119 all carry the same sentence from the owner's own update script v2.1, naming the GTM lead.
  Covered by the substitution ruling and handled in A163.

**The test fixtures were renamed to invented names rather than to the two who remain.** `test_directory.py`
used two of A62's five as fixture curators, which was a convenience and a quiet dependency: nothing in
that file asserts anything about who the curators are, and naming real people meant editing it whenever
the staff changed for reasons unrelated to what it tests. It now uses Vreni, Tobias and Anouk. The sort
assertions were preserved in both directions — insertion order still differs from display order, which
is the property `test_the_directory_names_people` exists to check.

**One collision closed itself.** A62 recorded that one of the curators and one of the members were
different people who shared a given name, and wrote it down because nothing joined them. With the curator
revoked and the member renamed (A162), the collision no longer exists — but A62's note stays in the
history, because it explains a hazard that was real for three weeks.

47 tests in `test_directory.py`, all green, five of them new.


## A162 — The member keeps the record and loses the name

*Owner: Nicolas · 2026-09-20 · T1.3 · cost: one tool, one Decision, one rewritten append-only row*

**Ruled: a pseudonym.** One of the six real submissions is **Renzo T.** from today. The alternatives were
leaving the record alone or erasing it through R-231, and the middle course was chosen because the six
real members are the corpus A135 and A139 measure against: erasing one changes what the Know surface has
been *proved* to answer, and a pseudonym changes nothing except what the person is called. Every number,
answer, finding and derived position is untouched.

**This entry does not name the person it renamed, and that is not squeamishness.** A pseudonym works by
being the only name the record holds. A register entry reading "X became Renzo T." would rebuild the link
in the one document most likely to be read by someone outside the team — which is the same reason the
Decision written below does not name them either. If the substitution ever has to be reversed, the
instruction came from the owner and the owner knows who it was.

**Almost all of it was a file rename, and that is a fact about the design worth recording.**
`load_submission._names` derives the slug, the address and the display name from the submission's
*filename*; the JSON carries no name anywhere. So `andersch-onboarding-RenzoTommasini.json` produces
`renzot`, `renzo.t` and `Renzo T.` with no code change at all. A build that had copied the name into the
payload would have needed a migration here, and would have left copies of it in every derived record.

**`tools/pseudonymise_member.py` exists only for the database that already holds the old name**, where
re-loading would mean discarding a plan, its versions and its decision history. It is a dry run by
default. Four places held the name: `members.display_name`, `credentials.email`,
`household_members.label`, and the `reasoning` of one Decision.

### C-09 refused this script twice, and was right both times

Worth the space, because the second refusal changed the answer rather than the implementation.

**First refusal, the ORM guard.** Assigning to `HouseholdMember.label` and flushing raised
`PlanMutationWithoutDecision`. The argument against obeying it was that a pseudonymisation is not a change
to the plan — the household's composition, its relationships and its numbers are identical before and
after — so the write went round the ORM through a Core `update()`, which is how `services/erasure.py`
reaches the append-only tables.

**Second refusal, `_refuse_unvetted_plan_dml`.** C-09 has two enforcement points, not one, and the second
inspects statements on their way to the connection. Its message says in as many words that a violation
"does not become one because the write went round the ORM". That guard is A72's fix, landed on 31 August,
and this is the first time since that anything has tried the door it was added to close. It held.

**The second refusal settles the argument against the argument.** This build has already classified
`household_members` as plan-mutable. A tool deciding from outside that one particular column does not
count is a tool overruling the schema to save itself a record — which is the shape of every defect in this
register where something was enforced in one place and assumed in another. So the label change is made
the way C-09 requires, through `mutate_plan`, and the Decision it writes is true: the label did change, on
the owner's instruction, and there is now a row saying so.

**The Decision deliberately does not name the old name.** A record reading "X became Y", in a database
that holds X nowhere else, rebuilds exactly the link the pseudonym exists to break. It says that a
pseudonym was substituted on the owner's instruction of 20 September 2026 and what the name is now.

### The one append-only row that was rewritten, and what it costs

One Decision's `reasoning` quoted the source filename, and the source filename was the person's name.
`decisions` refuses UPDATE by trigger and by `DecisionImmutable`, and the
script drops the triggers, rewrites through Core, and re-creates them in a `finally` **on the session's
own connection** — erasure's shape exactly, because going through `engine.begin()` commits the CREATEs
ahead of the DROPs and leaves the database with no append-only triggers at all. A63, A66 and A68 are three
separate occasions on which this build lost them silently. The script counts the triggers before and
after and raises if they differ. Six before, six after.

**The cost is real and is not hidden here: the register can no longer say that no decision has ever been
altered.** One has. It was altered to remove a name the owner ruled must go, by a documented tool that
verified the guarantees it suspended, rather than at a prompt with no record. That is the trade, and
rule 5 of the cull task is why it is written down rather than simply done.

### What was deliberately not changed

- **The submission's answers, figures and free text.** The ruling was that the record stays; only the
  name goes. A pseudonymisation that rewrote the content would destroy the corpus it exists to preserve.
- **`client/submissions/` and `reports/` are not in git.** Both are gitignored — they are real people's
  data and were never tracked. The renames there are local-data operations, and a fresh clone has neither
  the old name nor the new one.
- **The revoked curator rows keep their display names.** That is A161's decision, not an oversight: a
  curator's name on a revoked row is the audit trail's "who", and they are different people from any
  member. One of those names happened to collide with this member's, which is why A62 wrote the collision
  down; after this entry the two no longer share anything.
- **A62's note about the collision stays in the history.** The collision no longer exists, but it was
  real for three weeks and the note explains a hazard somebody reasoned about.

178 tests across the five files that carried the name as a case, all green.


## A163 — The register keeps its history and loses the names

*Owner: Nicolas · 2026-09-20 · T1.4 · cost: nine edits, one marked quotation*

**Two different things, treated differently**, which is the whole of this item.

**Live references came out.** A62's list of five is now the list of two, under a dated note at the head
of the entry saying three were revoked on 20 September 2026 and why. A113's struck-through
waiting-on-the-compliance-reviewer caveat loses the name; the caveat had already been lifted on
4 September, so only the name went.

**Historical narrative stayed, with roles in place of names.** Mike becomes *the compliance reviewer*,
Nino *the GTM lead*, Gian *a curator*. Entries describing what happened on a given day are the record;
rewriting them to say events had a different cast makes the register untrustworthy for every other claim
in it, and this register is cited by number in fifty places. The events are unchanged and the people in
them are now described by what they did.

### The quotation, which the task did not anticipate

Three places carry the same sentence from the owner's own update script v2.1 — A119, the docstring of
`services/onboarding.locked_findings`, and `client/content/intake-findings.json`. It names a person
inside material quoted verbatim from another document.

The owner was asked specifically about this and ruled **substitute there too**. So all three now read
`[the GTM lead]`, in brackets, each with a line saying the bracket marks a substitution made on this
date. The bracket is the point: a reader holding `andersCH-app-update-script.md` beside the register will
find the two texts differ, and is entitled to know that the difference is a deliberate substitution and
not a misquotation or a drafting error. An unmarked edit to quoted material is the thing that makes every
other quotation in a document suspect.

### One error found in this task's own output

A161 and A162 were written before this item ran, and A162 named both the old name and the new one — in
the entry recording a pseudonymisation, and two paragraphs after explaining why the Decision written into
the database deliberately does not. A pseudonym works by being the only name the record holds; a register
entry saying "X became Y" rebuilds the link in the document most likely to be read by someone outside the
team, and the register is the exact place where that matters most.

Both entries were corrected before this one was committed, and `tools/pseudonymise_member.py` had the
same defect in its module docstring and its usage examples — a tool that documents itself with a worked
before-and-after is a tool that publishes the mapping it exists to break. It now uses placeholders.

It is recorded rather than quietly fixed because it is a good example of the failure this register keeps
catching in other forms: the rule was enforced carefully at the place it was obviously needed, and
restated casually three paragraphs away.

### Where the three names still appear, deliberately

- **The `curators` rows.** A revoked curator's display name is the audit trail's "who", and erasing it
  would defeat the reason A161 revoked rather than deleted.
- **`tools/seed_demo_accounts.py`'s `REVOKED` list.** The seeder has to name the rows it revokes.

Both are operational: one is evidence, one is code that has to find three specific records. Neither is
narrative, and the ruling was about narrative.


## A164 — C-01 is deleted, and this is what it was catching on its last day

*Owner: Nicolas · 2026-09-20 · T2.2 · cost: 1,191 lines of `boundary.py`, 2,801 lines of probe suite,
and the build's only claim about what reaches a member*

**C-01 is withdrawn.** The regulatory-compliance layer is not a constraint on this build. The report is
valid advice only once a curator has looked at it, so the human is the gate and the code does not need to
decide whether a sentence is advice.

**The reasoning is A76's and it was right.** 255 patterns across four languages, four adversarial rounds
since, each one finding a class nobody had listed — the bare instrument name, the ASCII transliteration,
the fronted verb, the du register, the imperative without a pronoun — and a written conclusion that a
phrasing blacklist is unbounded by construction and does not converge. This was the most expensive thing
in the build to maintain and the least able to say what it guaranteed.

### What was deleted

| | |
|---|---|
| `boundary.py` | 1,340 lines to 149. The pattern lexicons, the inbound classifier, the outbound scan, the four-language refusal matrix, `Verdict`, `check_answer`, `classify_question`, `states_statutory_duty`, `refusal_text` |
| Probe suites | `test_boundary_c01.py` (1,312 lines) and `test_boundary.py` (215) deleted outright; 12 C-01 tests cut out of `test_adversarial.py` |
| Consumers | The two outbound gates and the inbound refusal in `services/know.py`; the `Fact` constructor's gate in `services/befund.py`; the advice half of `services/finding.py`'s predicate |
| Tests elsewhere | 21 further tests across `test_consent.py`, `test_decisions.py`, `test_derive.py`, `test_finding.py`, `test_grounding.py`, `test_know.py`, `test_liquidity.py`, `test_onboarding.py`, `test_computations.py`, `test_client_surfaces.py`, `test_position_edit_api.py`, `test_router.py` |
| The board | `C-01` and `C-01/imperative` out of `known_gaps`; `C-01` out of `constraints_enforced` |

### What survives in `boundary.py`, and why it is not compliance

`asks_about_the_member` decides whether a question is about the person asking it, which governs whether
their vault may be read. That is C-04 and C-05 — data protection, a different law and a different
argument — and it would be just as necessary in a product nobody regulated. `normalise_language` and
`SUPPORTED_LANGUAGES` were never C-01's; the product is bilingual by A12.

### The measurement, which is the point of this entry

T2.2 required the probe corpus run one last time and the output kept, because once the patterns are gone
the question "what did we stop doing" has no answer. `tools/measure_c01.py` produced
`reports/c01-final-measurement.txt` immediately before the deletion. The whole corpus, 20 September 2026:

```
OUTBOUND — model output the gate refuses          133 probes, 133 refused
  AUDITED_ESCAPES                 7/7     DU_REGISTER                    26/26
  UNAUDITED_REGISTERS_DE_EN      14/14    VERB_FRONTED                    8/8
  UNAUDITED_REGISTERS_FR_IT      16/16    SUITABILITY_VERDICTS           12/12
  INTERROGATIVE_ADVICE           18/18    CLOSED_FROM_THE_HONESTY_LIST   19/19
  ADVICE_WEARING_DUTY             6/6     DETACHED_ADVICE                 7/7

OUTBOUND — education and duty it must NOT refuse   26 probes, 26 allowed
  EDUCATION_ANSWERS              19/19    STATUTORY_DUTY                  7/7

INBOUND — questions it refuses                     43 probes, 43 refused
  ADVICE_QUESTIONS_FR            13/13    ADVICE_QUESTIONS_DU             7/7
  ADVICE_QUESTIONS_IT            11/11    RANKING_REQUESTS               12/12

INBOUND — questions and traps it must NOT refuse   21 probes, 21 allowed
  EDUCATION_QUESTIONS_FR          6/6     SUBSTRING_TRAPS                 9/9
  EDUCATION_QUESTIONS_IT          6/6

WHICH RULE FIRED
  answer_ranks_or_recommends      133      asks_what_to_do                 31
  asks_to_rank_instruments         12

TOTAL: 223 probes. 176 refusals, 47 correct passes, no false positive and no miss.
```

**Every number in the refusal rows is now zero.** Not because the probes stopped matching — because
nothing looks at the text. That is the trade, stated as a number rather than as a feeling.

### Three things this cost that are worth naming

**1. Build-spec §S-08's acceptance example is now false.** The spec says of *"Should I buy fund X with my
10,000?"* that the system "explains the boundary and offers a curator; it does not answer". It answers.
The test was rewritten to assert the new behaviour rather than deleted —
`test_the_specs_acceptance_example_is_now_answered_rather_than_refused` — because a spec criterion that
silently stops being tested is one nobody discovers has lapsed. If a gate is ever reinstated, that test
is the one that should go red first.

**2. A103's wrong-law test had to change guard, and the change is an improvement.** It was a strict
`xfail` asserting C-01 caught a false-but-correctly-cited statement of pension law. C-01 never caught it
and was never going to: C-01 asked whether an answer *advises*, not whether it is *true*. With C-01 gone
the test is re-expressed against the rule that does hold — the sentence is in no passage, so the
extractive path cannot emit it — and it now **passes** instead of being an expected failure. The risk it
describes is the one C-11 exists for.

**3. The client's refusal rendering is unreachable and was kept.** `ask.js` and `know.js` still handle
`requires_curator`. The flag is still set elsewhere — A122's undecidable liquidity lever routes a
computation nobody can make to a human — and a client that drops a key the server still sends fails
silently the day something sets it again. Both comments now say the branch is unreachable from that route
and why it stays.

### C-11, promoted the same day

A106's extractive-only rule becomes a constraint in its own right: **no member-facing sentence asserts a
fact it cannot attribute to a retrieved passage.** It is on the health board under its own number. The
reason it is promoted now rather than left as a practice is that the Know stated pension law wrongly in
3 of 3 runs with correct citations (A103), that harms the member whether or not anyone is licensed, and
with C-01 gone it is the only protection left on that surface.

`known_gaps` gains **S-08/relevance** in place of `S-08/truth`: a sentence copied verbatim out of the
corpus with a correct citation can still answer an *adjacent* question. C-11 checks attribution, not
aboutness. It carries its own strict `xfail`, so the board cannot claim the gap while nothing
demonstrates it — which is the check that caught this entry trying to list a gap with no test behind it.

2,425 tests pass. The one failure is `test_the_submission_state_block_means_liquid_wealth_by_W_L`, which
predates this task and is A142's unresolved `W_L` disagreement.


## A165 — The router keeps the boundary that protects the vault and loses the one that protected a licence

*Owner: Nicolas · 2026-09-20 · T2.3*

A113 gave the ask field three branches. Branch 3 was regulated advice: refused, routed to a curator,
never answered. It existed because C-01's inbound classifier existed, and it goes with it.

**The split that remains earns its place for a different reason, and the difference is the whole entry.**
Branch 3 asked *"is this regulated advice"* — a question about licensing, decided by a pattern layer that
four rounds of audit could not make converge. What is left asks *"is this question about the person
asking it"*, and that governs whether their vault may be read. A question about the world is answered
from the corpus and never touches their material; a question about them is answered with their material
in front of it. That is C-04 and C-05, it protects a member from having their financial position read to
answer a question that was not about them, and it would be necessary in a product nobody regulated.

So `Branch.REGULATED_ADVICE`, the `regulated_advice` boundary, `Route.reason` and the refusal path are
gone. `BOUNDARIES` is two entries rather than three: **a boundary nothing can return is a thing the next
reader has to work out is dead.**

`Route.requires_curator` stays as a constant `False`, and its docstring says so plainly. It is on the
payload because two client surfaces read the key, and an answer path that stops sending a key the client
reads produces a silent `undefined` rather than a visible change.

`_check_every_branch_is_specified()` is unchanged and still runs at import. Item 1's acceptance criterion
was that adding a branch touches one place; removing one turned out to touch the same one place, which is
the first time that property has been tested in the direction nobody designed it for.

The test that proved a population question never touches the vault is untouched and still passes. It was
always the valuable half.


## A166 — The Optimiser's allocation reaches the member, and nothing stands between them

*Owner: Nicolas · 2026-09-20 · T2.4*

A150 and A155 produce six portfolios and an allocation per member. `portfolio_optimiser` was refused to
members outright — `CURATOR_ONLY_ENGINES`, checked in `submit` before the plan is read — because its
output ranks instruments and C-01 put that behind a licensed human. The authorisation is no longer being
sought. The condition is removed.

**T2.4 proposed a swap and got half of it.** The task's wording was "remove the authorisation condition
and make the release record the only thing between the computation and the member". There is no release
record: the owner refused C-12 (T2.1, recorded in A160). So the condition was removed and **nothing was
put in its place.** A member can queue an allocation and read what comes back. Whether a curator saw it
first is not a fact this system records, and after this change nothing makes it one.

`CURATOR_ONLY_ENGINES` is now `()` rather than deleted. The check still runs, still before the plan is
read, and an engine may yet need to be curator-only for a reason that is not regulatory. Empty, the tuple
says that today none is — which is a different statement from the check not existing.

**What still refuses the engine is not a control and must not be mistaken for one.** Its `mandate` gap is
real: PCP solves against a named investment policy, a Goal carries five qualitative parameters and a
purpose, and writing a mandate from a goal would be inventing a policy for the member and then optimising
against it. That objection survives C-01 unchanged, because fabricating a policy and solving against it
is a fabrication regardless of who is licensed — so the gap stays and nothing fills it. But A81's warning
is exactly on point: **a guard that depends on an unrelated gap is not a guard.** Fill `mandate` and
nothing stands here.

`score_engine` stays in `ENGINES_WITHHELD_FROM_A_MEMBER`. That one is C-07 — listing the inputs the Score
lacks invites "so what would my score be", which is the primitive C-07 forbids — and C-07 is product
philosophy, not compliance. It survives the cull on its own merits.

### The two tests that changed sides

`test_the_ranking_engine_is_refused_before_the_plan_is_read` asserted the refusal fired before `plan_for`
was consulted, proven by making `plan_for` explode. It is now
`test_no_engine_is_curator_only_any_more`, asserting the tuple is empty and that the remaining refusal is
`the_plan_does_not_answer_this_engine`. The inversion is why it was rewritten rather than deleted: a test
that changes sides records the change, and a deleted one records nothing. Its HTTP twin changed the same
way, and `test_every_engine_in_the_estate_is_accounted_for` now expects the optimiser to give the same
answer as the other three unrunnable engines.

### Stale prose, reported and not yet fixed

C-01 is referenced in roughly sixty docstrings and comments across thirty modules that this item did not
touch — `services/befund.py`, `services/curator.py`, `services/derive.py`, `services/property.py`,
`services/time_allocation.py`, `services/vault.py`, `services/stages.py`, `api/curator.py`,
`api/decisions.py`, `interpret.py`, `llm/__init__.py` and others. Most are of the form "C-01 forbids X, so
this does Y": the *reasoning* usually survives on other grounds, but the sentence asserts a constraint
that no longer exists, and a docstring claiming a gate that was deleted is worse than no docstring.

It is named here rather than quietly left, because the next reader will otherwise conclude the cull was
partial. It is a prose pass over thirty files, it belongs with the rename pass that has to read the same
files anyway, and it is the largest piece of known debt this task leaves behind.


## A167 — The curriculum's handoffs were reported, and all ten of them survive

*Owner: Nicolas · 2026-09-20 · T2.5 · cost: one sentence changed*

T2.5 asked for every compliance handoff in the education nodes to be reported before any was removed, on
the grounds that some teach the member something true about the difference between learning and being
advised and survive on their own merits, while the ones that exist only to route around a licensing rule
do not. **The report is the finding: there are ten, and none of them is the second kind.**

### The ten, in full

Each sits under a closing heading — *«Wo dieser Text aufhört»* or its equivalent — at the end of one
knowledge article, and each has the same shape: this note explains the category; what applies in *your*
case depends on the following named things; that belongs in a conversation.

| Article | What it names as the reason a text cannot answer |
|---|---|
| `absicherung-was-versicherung-leistet.md:85` | which cover fits a particular situation |
| `ahv-beitragsluecken.md:91` | the contribution history, the age, the rest of the situation |
| `freizuegigkeit-stellenwechsel.md:61` | the timing, and emigration's cash-payout question |
| `indexfonds-und-aktive-fonds.md:67` | that choosing a form and a fund is a *selection*, not a fact |
| `risiko-und-horizont.md:68` | that mapping risk to horizon to investment is a suitability assessment |
| `saeule-3a-bezug.md:47` | residence, year, and the rest of the situation |
| `saeule-3a-und-3b.md:48` | income, canton of residence, timing, and when the money is needed |
| `vermoegen-anlegen-grundlagen.md:90` | that the text describes an *order*, not a selection |
| `was-ist-ein-etf.md:62` | that which fund suits a situation is not a question a text answers |
| `zweite-saeule-pensionskasse.md:60` | that the choice is irreversible, and the deadline is in the Kasse's Reglement |

**Every one of them names why the answer is situation-dependent.** That is the teaching. A member who
reads the 3a article learns that the canton they live in changes the answer — which is true, useful, and
exactly the distinction between being taught a subject and being advised about their own position. Not
one is a bare "ask a curator", and not one rests on andersCH's licensing status.

### The one that looked like the exception, and why it is not

`risiko-und-horizont.md` is the only handoff that cites a statute for the wall itself: *"eine solche
Zuordnung wäre eine Eignungsprüfung, und die ist nach FIDLEG eine persönliche Abklärung."* It was the
obvious candidate for removal, and it stays — because it teaches the member that there is a named legal
category for what they are asking, and that a document cannot perform one for them. That is the
difference between learning and being advised, stated more precisely than any of the other nine manage.
Deleting it would remove a true thing about the world to tidy up a constraint that no longer applies.

The regulatory citations elsewhere in the corpus — KAG, FIDLEG's Basisinformationsblatt, the Bankiers-
vereinigung's mortgage minimums that FINMA recognises — are **subject matter, not handoffs**. They are
what the articles are teaching about, and C-11 now requires every member-facing sentence to be
attributable to exactly such a source. They were never in scope and they are more load-bearing after the
cull than before it.

### What did change

One sentence, and it is not a handoff. `client/content/household-confirmation.json` recorded that the
`salary_step_change` signal was unobservable because *"Aggregation is Phase 1, with FINMA."* That is a
roadmap claim, and the authorisation it named is no longer being sought (A166), so it was stale rather
than merely regulatory. It now says the signal has no dated route to becoming observable and is not
waiting on anything, which is the truth.

### T6.17 is already closed, and the entry stays in anyway

T2.5 describes T6.17 as "an education/advice wall gating the Summit exit". **There is no Summit exit and
no such wall in prototype2.** The three exits in `learning.json` are `run_own_affairs`,
`offer_a_service` and `start_a_venture`; the learning payload carries `units_are_not_gated: True`, and
`services/learning.py` states prerequisites "as facts about each prerequisite, never as a gate". R-143
goes further and forbids summit and mountain vocabulary outright, with `mountain_hits()` matching stems
rather than literals after an audit walked eight compounds past it (A88).

So the item was closed before this task reached it, and the entry is left in per the task's own
instruction, because "we looked and there was nothing there" is a different record from silence.


## A168 — C-06 is dropped, and an action item is now well-formed only by convention

*Owner: Nicolas · 2026-09-20 · T2.6 · cost: a validator, a CHECK, two triggers, eleven tests*

**Ruled: drop it with the compliance layer.** T2.6 put the question because C-06 reads as a product
principle rather than a regulatory one, and the owner could reasonably have kept it. The argument that
decided it is the one the task itself made: **"two options with consequences" can be satisfied vacuously,
and nothing ever checked that the consequences differed.** Two triggers and a CHECK were enforcing to the
letter a property nobody had defined tightly enough to be worth that machinery.

### What came off, and from where

C-06 was enforced three times over, deliberately, and A75 is worth reading for why the third layer had to
be a trigger: the CHECK could count the array and could not look inside it, because SQLite prohibits
subqueries in a CHECK and `json_each` needs a FROM.

| Layer | Where |
|---|---|
| `@validates("prepared_options")` hook, `PreparedOptionsTooFew`, `MINIMUM_PREPARED_OPTIONS`, `REQUIRED_OPTION_KEYS` | `models/action.py`, 205 lines to 106 |
| `ck_action_items_prepared_options_min` | the spine migration's CHECK, dropped by table rebuild |
| The two A75 content triggers | `e7b3a95d612f`, dropped by name |
| Eleven tests | three in `test_constraints.py`, eight in its storage-layer section, two in `test_adversarial.py`, one in `test_derive.py` |
| The board | `C-06` out of `constraints_enforced` |

### What replaced it: nothing at the store, a convention in one module

`services/derive.py` still writes two options with labels and consequences, and `test_derive.py` still
asserts it does — under a locally-defined `OPTIONS_DERIVE_WRITES = 2` rather than an imported constraint.
**That is a weaker guarantee and both places say so.** It holds for what that module writes, because that
is what the test reads. `bulk_insert_mappings`, raw SQL, or any future writer can now put an action item
in the table with an empty array, and nothing will stop it.

The test that proved exactly that — `bulk_insert_mappings` being refused — was deleted, because there is
nothing left to refuse it.

### Two things the migration had to be careful about

**The table rebuild is the dangerous half.** Dropping a CHECK in SQLite means recreating the table, and a
recreate takes every trigger attached to it. This build has lost its append-only triggers to exactly that
three times (A63, A66, A68). So `e7b3a95d612f` reads the live schema first and **refuses to run** if it
finds a trigger on `action_items` it was not told about, rather than sweeping it away; afterwards it
verifies that nothing survived and that `uq_action_items_derived_cause` — which is idempotence, not C-06,
and is what stops every read of the action list writing another copy of every derived item — came back.
Downgrade restores the CHECK and both triggers, and the round trip was run.

**A historical migration had been importing from live model code.** `a7c41b6f28de` built its trigger SQL
by importing `OPTION_CONTENT_TRIGGERS` and `option_content_trigger_statements` from
`andersch.models.action`. Deleting C-06 broke it, and *a migration that cannot run has lost the history
it records*. The statements are now inlined into that file, byte for byte as the model generated them on
the day it was written. The general lesson is worth keeping: a migration is a record of what happened,
so it must not depend on code that describes what is true now.

### One thing the board now says by omission

Build-spec §10 gates phase 1 on C-04, C-06, C-07 and C-09. One of those four has been **withdrawn rather
than satisfied**, and `/api/health` reflects that by not listing it — with the module docstring saying so
in words, because a constraint quietly missing from a board reads as an oversight.

2,405 tests pass; twenty fewer than before this item, all of them C-06's.


## A169 — What the cull actually let through: three questions out of a hundred and thirty-eight

*Owner: Nicolas · 2026-09-20 · T2.7 · the evidence the trade was worth making*

T2.7 asked for the six real members' questions and the 78 intake questions to be run through the Know
surface after the deletions, and for a record of what now comes back that would previously have been
refused. `tools/measure_cull.py` produced `reports/cull-measurement.txt`.

**It reconstructs C-01 from git rather than from memory.** The module is deleted, so the tool loads
`boundary.py` out of the commit before the deletion with `git show` and executes it into a module that is
never installed. Re-implementing the classifier would have measured a reconstruction, which answers a
different question; if the revision is ever unreachable the tool refuses and says so rather than guessing.

### The numbers

| Corpus | Asked | C-01 refused | Now answered |
|---|---|---|---|
| Every real submission's `main_question` | 60 | **3** | 3 |
| The 78 intake questions (A23, `onb@0.1.3`) | 78 | **0** | 0 |

The three:

- *«Soll ich möglichst schnell die Hypothek verringern, mehr in die Firma investieren oder andersweitig
  Kapital anlegen»* — `asks_what_to_do`
- *«Lohnt sich für mich der freiwillige Anschluss an eine Pensionskasse?»* — `asks_what_to_do`
- *«Welche Einkäufe in die Pensionskasse lohnen sich vor 62 noch?»* — `names_an_instrument_and_a_sum`

### What this says, and it is not what anyone expected

A164 measured the same gate against the probe corpus and got **176 refusals out of 223**. This measures it
against what people actually typed and gets **3 out of 138**. The gate was almost entirely occupied with
the adversary's questions and almost never touched a member's.

**That is the strongest single argument for the cull, and it was not the argument the cull was made on.**
The owner's reasoning was A76's: a phrasing blacklist is unbounded, four rounds found a new class each
time, it does not converge. True, and about maintenance cost. This is about what the thing was *doing*:
1,340 lines and 2,801 lines of probe suite, standing between members and three questions.

**The three are real, though, and they are exactly the ones worth looking at.** All three ask what to do
with a specific sum of the member's own money. They are the product's central use case, not edge cases —
which is the other half of the finding, and the reason A160 states the consequence of refusing C-12 as
starkly as it does. Those three members now get an answer out of the corpus, held to a retrieved passage
by C-11, with no curator having seen it. Whether that is better than a handoff is the owner's judgement
and the owner has made it; what this entry fixes is that nobody can later say the scale was unknown.

### A note on the corpus, so the number is not read as more than it is

Sixty submissions carry a `main_question`, not six. A135 and A139's "six real members" are the subset
loaded into the database; the rest are the synthetic records of 20 September 2026 and the earlier
archive. The intake set is A23's 78, extracted before any rewriting. Neither corpus is a sample of
future use — they are what exists, and they are what the previous measurements in this register used.


## A170 — The register is split: the rules in one file, the record in another

*Owner: Nicolas · 2026-09-20 · T3.1 and T3.2*

`DECISIONS.md` had reached 169 entries and 6,189 lines. Most of them are forensic narratives — a defect
found, what it cost, what was decided about it — which is the most valuable thing in this repository and
the worst possible way to answer "what rule applies here".

**So the two jobs were separated.** `DECISIONS.md` is now 39 restated rules, each keeping its original
number and date and linking to the entry it came from. This file holds all 169 entries unchanged.

**Nothing was deleted, and the interpretation is worth stating.** T3.1 said the live rules move to the
new `DECISIONS.md` and "everything else moves to `HISTORY.md` unchanged". Read strictly, the full text of
a live rule's entry would then exist nowhere, since only the restatement survives — which contradicts
"no entry is deleted". So **every** entry is reproduced here, including the ones whose rule is still
live, and `DECISIONS.md` links to them. A restatement is a summary; the entry is the evidence, and the
evidence is what the register is for.

**T3.2: eleven entries carry a dated withdrawal line.** A49, A76, A78, A83, A87, A92, A101, A102, A107,
A113 and A114 all existed to serve C-01. Each now has a line at its head saying it was withdrawn on
20 September 2026 and pointing at A160 for the reasoning and A164 for the deletion. The entries are
untouched below it. A reader tracing why the patterns are gone lands on the reasoning rather than on a
gap — and A113's line says **branch 3 only**, because its other two branches survive as the two-branch
router.

A76 deserves a note of its own. Its withdrawal line does not say it was wrong; it says it was right. A76
concluded in writing that a phrasing blacklist is unbounded by construction and that requiring every
claim to be supported by a retrieved passage was the destination. That is exactly what happened, three
weeks later, when C-11 was promoted and C-01 deleted.

The index at the top of this file is generated from the entries, so an entry cannot be in the file and
missing from the index.


## A171 — The board is rendered, because five of its rows were wrong

*Owner: Nicolas · 2026-09-20 · T3.3*

`client/status.html` described 31 August 2026. On the day it was rebuilt, five of its rows were false:

- `CuratorSession.curator_id` was listed as **"next"**. A98 had made it a foreign key on 31 August.
- D-07's destination phrase was **"read by nothing"**. A99 had it serving from the day after.
- The wrong-law risk was **"may gate S-08"**. A103 and A106 had narrowed it to relevance.
- **C-01** had a row in "what is enforced" and two in "still open". It no longer exists.
- C-06's row described a validator and a CHECK that had just been dropped.

**Not one of those was a mistake anybody made.** Each was a hand-written copy of something that moved
while the copy stayed still. That is the defect, and it is the same one A73, A91 and A125 are about: a
second copy of a fact is a second place for it to be wrong.

**So the page no longer states anything.** It fetches `/api/health` on load and renders
`constraints_enforced`, `known_gaps` and the store's own revision and trigger list. A withdrawn
constraint stops appearing because it stops being in the payload — which is how C-01 and C-06 left the
board without anyone editing it. The page explains their absence in prose, because a reader needs to know
a constraint was *withdrawn* rather than quietly dropped, and prose is not a copy.

**A parity test in both directions**, which is what T3.3 asked for:

- `test_the_board_keeps_no_second_copy_of_the_health_payload` reads the markup and fails if a constraint
  or gap id appears inside a `<td>`. Prose may name one; a table cell may not.
- `test_every_known_gap_on_the_health_board_still_has_a_failing_test_behind_it` — A65's existing test —
  fails if the payload lists a gap that no strict `xfail` demonstrates.

Together: the board cannot disagree with `known_gaps`, and `known_gaps` cannot disagree with the tests.

**Every open row now carries a date and an owner**, so `known_gaps` entries became objects rather than
strings. An undated gap is one nobody can tell has been open for three weeks or three months; an unowned
one is one nobody has agreed to answer. `test_every_gap_the_board_will_render_carries_a_date_and_an_owner`
parses the date rather than matching a pattern, so `2026-02-31` fails.

The three gaps, with the third newly added: `S-08/relevance` (since 1 September),
`C-09/raw-dbapi` (31 August) and **`curator/no-release-gate`** (20 September) — the last being A160's
consequence written onto the board, with a strict `xfail` asking a Befund for the release record it does
not carry. The day one exists, that mark goes red and somebody has to read A160.

And the failure mode was chosen deliberately: if `/api/health` cannot be reached the page shows an error
and no rows at all, rather than showing something stale. That is the whole reason it was rewritten.


## A172 — Fifty new clients were run through the system, and what they found

*Owner: Nicolas · 2026-09-20 · cost: two loader defects fixed, one renderer defect fixed*

Fifty submissions dated 20 September 2026 were loaded and run through the application the way a member
uses it: sign in, the first-login password change A43 requires, every member-facing route, and each
member's own opening question put to the Know. One report per client is in `reports/clients/`, the
findings in `reports/ISSUES-2026-09-20.md`. Both are under `reports/`, which is gitignored because it
holds people's material — so this entry carries the findings and names nobody.

**46 of 50 loaded.** The four refused are refused correctly, and that is the first finding.

### The five systematic findings

**1. Four clients cannot complete onboarding because 0.75 is not on the list.** The `health` instrument
offers 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00 — irregular, with a gap between 0.70 and 0.80 and none
above it — and four submissions state 0.75. R-020 forbids coercing it to 0.80, so the guard refuses and
is right to. This is the same defect `onboarding-questions.json` already documents in its own note about
a tidier list recording a false answer. **Needs an owner ruling**: add 0.75, or regularise the scale. The
four failed cleanly — no member row, no partial plan.

**2. 38 of 46 get no answer to the question they arrived with.** Eight answered with a citation; 16 got
*"material exists, no sentence in it answers"*; 22 got *"nothing found"*. The split is the useful part:
the 22 are a corpus gap that more material would close, the 16 are a retrieval or aiming gap that it
would not. This is A139 — "the corpus answers the six it was written for, and does not generalise" —
measured against fifty people rather than six. Nothing is malfunctioning: C-11 held, all eight answers
are verbatim quotes with sources, and the product said it did not know 38 times rather than inventing.

**3. Every goal of every client is unfunded — 0 of 92.** The loader creates goals and creates stocks and
never links them, correctly, because which money is meant for which goal is a judgement it should not
guess. The consequence is that the first thing every loaded member reads is that none of their goals is
covered, which is a fact about the loader wearing the appearance of a fact about them.

**4. All 46 clients have an identical action list**, and this is the finding most likely to matter to
someone using the product. Fourteen items each: two unfunded goals and twelve *"you skipped an onboarding
question"*. **552 of the 644 action items in the run — 86% — are that second kind**, always the same
twelve questions. The instrument serves 21 and the loader answers 9; the other 12 are recorded as skipped
*by the member*, who was never asked. A curator opening any client sees a worklist that is mostly an
artefact of loading and identical to everyone else's.

**5. The loader's own account of what it could not store is wrong by 414 entries.**
`services/submissions.unmapped()` compares two namespaces: `record_mapping` is handed the *question* keys
(`employment_position`, `employment_magnitude`, `employment_time_basis`) while `answers()` returns the
*submission* keys (`employment`, `income_gross`, `hours_per_week`). Five names coincide by accident. So
everything renamed on the way in is reported as having no home, and so are all five franc stocks and the
goals — whose source keys are never added to `mapped_keys` at all, in the same record whose `created`
field says `{goals: 2, stocks: 4}`. Nine keys across 46 clients. The remaining ~1,808 are real.

### Two defects in the loader, and one in the reporting, found by running them

- **`NameError: name 'subs_unmapped' is not defined`** on the last line of a *successful* write — the
  call site expected an import that was never added, so the loader raised after committing. 38 of 50 hit
  it. This is the class of defect this register keeps finding: a code path nothing had ever called.
- **`UnicodeEncodeError`** on every client with an umlaut in their name, in the `print` announcing the
  name rather than in the data. Fixed by reconfiguring the stream — the fix for "cannot display this
  person's name" is never to change the name.
- **My own renderer reported `no_positions` for all 46**, which was false: `/api/positions` serves the
  role grid (R-110) and the positions are inside its cells. Corrected before the reports were written,
  and recorded because a tool that miscounts in the direction of alarm is worse than one that miscounts
  quietly.

### Seven filenames are corrupted, and were left that way

Seven of the fifty carry literal box-drawing characters — `U+251C`, `U+255D` — where `ü`, `é` and `ä`
belong: UTF-8 bytes decoded as cp437 and written back as the filename. An older submission in the same
directory has a correct `ü`, so whatever generated the fifty did this and the earlier pipeline did not.
It matters because `load_submission._names` derives the display name, the slug and the login address from
the filename, so those seven are in the system under an unreadable surname.

**Not repaired.** Renaming a submission file edits the record of what was received, and the decision of
whether these regenerable synthetic records are evidence belongs to the owner.


## A173 — Health takes any number between 0 and 1

*Owner: Nicolas · 2026-09-21 · cost: an option list*

**Ruled: the guard does not make sense; let any numerical value between 0 and 1 through.**

`health` offered seven discrete readings — 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00 — and the list was
irregular: coarse below 0.80, fine above it, with exactly one gap, between 0.70 and 0.80. Four of the
fifty submissions loaded on 20 September answered **0.75** and landed in it. R-020 forbids rounding a
member's own answer to the nearest option, so `onboarding.complete` refused all four and none of them
could be loaded (A172).

It is now `type: number, min: 0, max: 1`. The option list is gone.

**The ruling is coherent with what the build already did, which is why it is the right call rather than
merely the owner's call.** `services/human_capital.py` has always accepted a bare number in that range —
its own note reads *"Read as a bare number; not a published option"* — and health is a multiplier on
income, which is a continuous quantity. The instrument was the only thing in the chain refusing a value
the model could already use, and the seven readings were a rendering decision wearing the authority of a
validation rule.

**What did not change is the guard, and the distinction matters.** Widening a question is not removing
its protection:

- a figure outside 0..1 is still refused, by the bounds the question declares;
- a label is still not an answer — the stored value is never the rendering, so `"0,85"` is refused as a
  string;
- **C-07 is untouched.** The old note argued that seven discrete readings were safer than a slider
  because "a 0-to-1 figure about a person is one render away from being a score of them". That argument
  was always about the RENDERING, not about the number of options: this is never shown as a position on
  a scale, never compared against another member, never graded. D-01's treatment of capabilities, and it
  survives the widening unchanged. The note now says so instead of resting on the discreteness.

Two tests pin it. `0.75` is named explicitly in one of them rather than being covered by a range, because
a test that only checked the bounds would pass again the day somebody reintroduces a list that happens to
include 0 and 1.

**All four clients now load**, all fifty are in the system, and `0.75` is stored four times as the value
those members actually gave. The re-run across all fifty is in `reports/ISSUES-2026-09-20.md`, whose
figures moved with it: 42 of 50 still get no answer to their own question, all 50 have the same
fourteen-item action list, and none of the other findings changed.


## A174 — The rename: eigentliCH, in six groups, with one near-miss

*Owner: Nicolas · 2026-09-21 · from `TASK-rename-eigentlich-2026-09-20.md`*

The product is **eigentliCH**. `eigentlich` in identifiers, `eigentli.local` for local addresses,
eigentli.tech for the website. Run after the cull, as the task sequences it, and in the task's own order:
inventory, then code, then content, then tests.

**The inventory came first and changed nothing**, which earned its keep immediately. `anders` is an
ordinary German word and appears **32 times where it is not the product** — in twelve member-facing
knowledge articles (*"Die AHV verhält sich anders"*, *"was seit 2023 anders ist"*), in a member-facing
notice in `services/know.py` (*"Fragen Sie anders"*), in five fixture labels, and in one assertion,
`test_time_allocation.py:113`'s `"kein Kapital anders"`. An unanchored case-insensitive replace would
have corrupted German prose in a dozen articles silently and broken exactly one test loudly. Every
replacement is anchored: `\bandersch\b` for identifiers, and `andersCH` not followed by a path,
filename or estate marker for the display name.

| Group | What moved |
|---|---|
| 1 · identifiers | `backend/andersch/` → `backend/eigentlich/`; **858** occurrences across 107 files; `pyproject`; `andersch.db` → `eigentlich.db` with its snapshots |
| 2 · client namespace, payload keys | `andersch.session.v1`, `anderschIntakeDraft`, `andersch-export-*`, and the two payload keys `andersch_{assesses,states}_capabilities` — server, client and tests in one commit, because they are a contract |
| 3 · content | the destination key and `life-events.json`; A22's literal scan run immediately after, not at the end |
| 4 · addresses | migration `b81f4c2e9a37`: 71 member credentials and 6 curator rows |
| 5 · tests | carried by groups 1 and 6; the one assertion that must **not** move is the German `anders` |
| 6 · display | **311** occurrences of `andersCH` across 87 files, including every member-facing surface |

### The near-miss, and it would have locked everyone out

Group 1's `\bandersch\b` matched the domain inside `f"{key}@andersch.local"` and rewrote it to
**`@eigentlich.local`**. The migration, written from the casing table, wrote **`@eigentli.local`**. Two
different domains: the code generating one, the database holding the other, and **nobody able to sign
in**.

It was caught by the task's own step 3 — *"after the migration, log in once as each remaining account
and record the result"* — and not by the test suite, which was green the whole time because the tests
generate their own addresses through the same wrong constant. A rename that agrees with itself and
disagrees with the database is exactly the failure an end-to-end sign-in catches and a unit test cannot.

**The result of that sign-in check, which is the evidence group 4 is done:**

- **6 curators**: Nicolas, Nicolai and the demonstration curator in; **Mike, Nino and Gian refused**,
  which is A161 still holding after the addresses moved underneath it.
- **10 personas**, each with its own documented password: all in.
- **71 member credentials** rewritten, sampled across three password generations: all in.

### What is deliberately still called andersCH

- **`DECISIONS.md` and `HISTORY.md`.** The product was called andersCH and the record says so.
- **`andersCH-build-spec.html`.** The specification the build was written against.
- **`client/reference/`** — a verbatim capture of the live site (A51), URLs and all. Editing URLs inside
  a capture is what stops it being one.
- **The estate**: `andersCH/`, its `.cmd` files, its two desktop icons. Imported, not copied (A1).
- **The 60 submission filenames.** A submission's filename is the record of what was received.
  `load_submission._person` keys on the `onboarding-` marker rather than on the brand, so new files
  written `eigentlich-onboarding-*` load through the same two lines with no glob change.
- **`backend/migrations/`** prose. Dated artefacts, like the register.

### The desktop icon, and why renaming a shortcut does not rename anything

The owner renamed the desktop `.lnk` to `eigentliCH` and reported that the icon had vanished and it still
pointed at an andersch folder. Both were true and neither was caused by the renaming: a shortcut's label
is not its content. The `.lnk` still held `desktop\andersCH-P2.cmd` as its target and
`desktop\andersCH-p2.ico` as its icon, and this rename had moved both to `eigentlich.cmd` and
`eigentlich.ico` — so the target did not exist and the icon could not be drawn.

`desktop/install-shortcut.ps1` rewrites the shortcut from the current filenames and was re-run. Verified:
target exists, icon exists, and the application launches through it and serves `/api/health` on 8420.
The working directory still contains `andersCH` because the repository root is still called that — see
below.

### Still outstanding

**The repository root is still `andersCH/`.** Windows refuses to rename a directory while a process has
its working directory inside it, and that process is the session doing the work; `os.rename` and
`Rename-Item` fail identically. It is one command, it breaks nothing — the estate bridge resolves
`ESTATE_ROOT` by a relative walk and was verified either side of the directory move — and it is written
out in `RENAME-THE-ROOT.md`.

---

## A175 — C-11 reversed: the Know answers in its own words, over the member's own record

*Owner: Nicolas · 2026-09-21 · from the fifty-client run of 20 September (`reports/ISSUES-2026-09-20.md`, §2)*

**The measurement that forced it.** Fifty loaded clients were each asked the question they arrived with.
Eight got an answer. Eighteen were told material exists but no sentence in it answers them, and
twenty-four were told nothing was found at all. The product said "I don't know" forty-two times, and
every one of those refusals was honest — which is exactly why the number was worth taking seriously.

Reading the thirty-six that retrieved nothing, together, says what was wrong:

> *"Wie gross ist meine Vorsorgelücke wirklich?"* · *"Reicht unser Sparen für ein Eigenheim in sieben
> Jahren?"* · *"Wie früh kann ich mit dieser Sparquote aufhören zu arbeiten?"* · *"Tragen wir das Haus
> auch, wenn die Zinsen deutlich steigen?"*

Every one is about the person asking it. **No sentence in any Merkblatt can answer any of them**, because
the answer is arithmetic over that member's own figures — and no corpus, however large, contains those.
More material was never going to fix it. This is A139 (*"the corpus answers the six it was written for
and does not generalise"*) measured against fifty people instead of six, and the conclusion is different
from the one A135 drew: the gap is not in the corpus, it is in what the answer path is allowed to see.

**What it was allowed to see.** `know.retrieve`'s universe was the member's vault, the learning units and
the impersonal corpus. The fifty had no vault items and no learning units, so for all fifty the personal
channel was empty *by construction*. Meanwhile the same database held **296 positions and 128 goals** for
those same people, and nothing on the answer path could look at one of them.

### The ruling

Asked on 21 September whether to (a) keep verbatim quoting and widen the inputs, (b) let the model compose
with every figure traceable, or (c) let it answer freely, with the cost of each stated, the owner chose
**(c), free generation**.

What that gives up is stated here rather than buried: **a composed answer can state something no source
backs**, and there is no mechanical check that every clause is true. There cannot be one — that is what
composition means.

### What was built

| | |
|---|---|
| `services/compose.py` | the model writes the answer; carries the argument and the cost |
| `services/member_ground.py` | positions, goals, household and stated facts as grounding |
| `computations.retirement_provision` | the second pillar to the reference age, via `pension_projection` |
| `computations.wealth_concentration` | what share sits in the largest position |
| `know.ANSWER_MODE` | `compose` (default) or `quote`, which restores C-11 exactly |

**The two C-11 checks still run.** `unquoted_sentences` and `unverifiable_figures` are now an **audit**
written into each answer's record rather than a gate that refuses it. That is deliberate and it is the
honest instrument: a curator can see, per answer, how many sentences left the sources and which figures
appear in none of them. A rising count is a signal; under C-11 it was simply an outage.

### Four things the measurement caught that argument would not have

**A salary added to four balances.** The first composed answer from a member's record reported their
wealth as CHF 840'000 by summing a stock list that included a CHF 280'000 income line. Both figures were
real and the sentence was false. Fixed where a unit can be checked rather than in a prompt: stocks and
flows now go under separate headings, and `_stocks()` excludes flows before any arithmetic.

**The configured model writes Chinese.** `qwen2.5:14b` was chosen for *reading* a member's text and
returning three integers. Asked for 200 words of German it produced one line of German and then switched
to Chinese mid-clause for the rest. `apertus:8b` wrote fluent German and invented an assumption nobody
made — *"angenommen, Ihre Ausgaben steigen um 10% pro Jahr"* — plus eleven figures in no source.
`qwen3:8b` stayed in German and named what was missing instead of estimating it. Composing has its own
model constant, and an answer that leaves German is retried once and then withheld.

**Every model duzt eventually.** Two sentences of `Sie`, then a slip. Repaired for the forms a word swap
can get right and counted for `du`, which governs the verb and cannot be swapped without conjugating.

**German endings defeated the computation matcher.** `vermögens` never reached `vermögen`, so a member
asking about their own concentration fell through to prose. Prefix matching above five characters;
computation coverage over the fifty questions went from **6 to 20**.

### The floor that was hiding the reviewed material

`LEXICAL_ONLY_FLOOR` is 700 and its own note says what it is for: word overlap alone *"cannot answer a
German question about an English book at all."* The authored entries are not an English book — German,
reviewed, tens rather than thousands, each carrying a section naming the questions it answers in the
member's own words. At 700, **two** of the fifty questions reached one. `COMPOSE_ENTRY_FLOOR` is 400,
composing only; authored entries now reach twelve, and retrieval overall went from 14 of 50 to 41 of 50.

### What is open, and belongs to the owner

- **`bvg-projection.json` is unapproved**, so `retirement_provision` — which nine of the fifty questions
  match — returns "not determinable" rather than a figure. Approving it is `published_by`, `decided_on`,
  `effective_from`, `provisional: false`, and its four `_for_review` concerns are real.
- **Seventeen of the thirty-one knowledge entries are drafted and unapproved**, including all five on
  Wohneigentum. The material exists and the Know cannot see it.

→ [A139](HISTORY.md#a139) · [A135](HISTORY.md#a135) · [A164](HISTORY.md#a164) · [A169](HISTORY.md#a169)
