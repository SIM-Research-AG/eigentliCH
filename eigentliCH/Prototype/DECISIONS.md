# andersCH prototype2 — the rules

**This file is the rules. [HISTORY.md](HISTORY.md) is the record.**

Every rule below is still in force. Each keeps its original number and date, and each links to the entry
it was taken in — go there for what was found, what it cost, and what was deliberately not done. This
file says what holds; `HISTORY.md` says why, and holds all 169 entries unchanged.

Split on 20 September 2026 (A170) because 169 forensic narratives is the wrong shape for answering "what
are the rules", and the narratives are too valuable to summarise away.

**Constraints referenced here** are the build specification's: `C-02` reproducibility, `C-03` no engine
artefact reachable from the browser, `C-04` and `C-05` data protection, `C-07` and `C-08` the product's
refusal to score or rank people, `C-09` the Decision record, `C-10` the append-only curator audit, `C-11`
attribution. **`C-01` and `C-06` no longer exist** — both were withdrawn on 20 September 2026 (A160).

---

## The member

### A11 · 2026-08-30 — The member is the session
Authentication is email and password, self-hosted. **No route accepts a `member_id` from a caller.**
Every member route resolves its member from a bearer session token; the parameter is gone from the
routes and from the request models rather than being validated. There is no developer bypass — no
environment variable, no header, no localhost exemption. The routes that deliberately need no session
are listed, with a reason for each, in `api/auth.py`. → [A11](HISTORY.md#a11)

### A50 · 2026-08-30 — The age floor is 18
Enforced in the service and as a CHECK constraint. → [A50](HISTORY.md#a50) · [A54](HISTORY.md#a54) ·
[A55](HISTORY.md#a55)

### A61 · 2026-08-30 — Erasure nulls the reference and empties the fields that held the person
R-231 cannot delete rows an append-only table owns, so it removes the person from them instead. Erasure
is the one operation permitted to drop and re-create the append-only triggers, it does so inside the
caller's transaction on the caller's own connection, and it is the only holder of the token that stands
C-09 down. → [A61](HISTORY.md#a61) · [A66](HISTORY.md#a66) · [A73](HISTORY.md#a73) ·
[A109](HISTORY.md#a109)

### A12 · 2026-08-30 — Bilingual from the start, de-CH the default
There is no silent fallback to German: an unwritten language is refused. `Member.locale` is where the
choice lives (A26). → [A12](HISTORY.md#a12) · [A26](HISTORY.md#a26)

---

## What reaches a member

### A106 · 2026-09-01 — C-11: nothing a member reads is unattributed
**No member-facing sentence asserts a fact it cannot attribute to a retrieved passage.** The Know emits
only sentences copied verbatim from retrieved passages, chosen by the model as *numbers* rather than
written by it, and `unquoted_sentences` refuses any answer carrying a letter or digit outside the
quotation marks.

Promoted from a practice to a constraint on 20 September 2026 (A164). The Know stated Swiss pension law
wrongly in 3 of 3 runs while citing correct passages (A103); that harms the member whether or not anyone
is licensed, and with C-01 gone this is the only protection left on that surface. → [A106](HISTORY.md#a106)
· [A103](HISTORY.md#a103) · [A164](HISTORY.md#a164)

### A165 · 2026-09-20 — The router has two branches, and they are about the vault
A question is either about the person asking it or about the world. The first may read their material;
the second never touches it. This is C-04 and C-05 — data protection — and it is decided by
`boundary.asks_about_the_member`, which is the only thing left in `boundary.py`.

The third branch refused regulated advice and went with C-01. Nothing in this build now declines to
answer a question on the grounds of what it is about. → [A165](HISTORY.md#a165) · [A113](HISTORY.md#a113)

### A160 · 2026-09-20 — The curator is advisory, and nothing enforces it
The owner refused the release gate proposed as C-12. **Nothing in this system holds the claim that a
human read a report before a member saw it** — not the code, not the schema, not the audit trail. C-10
still records that a named curator opened a session and C-09 that a Decision was taken, but neither sits
between a computation and the member who reads it.

This is a stated position, not a gap. → [A160](HISTORY.md#a160) · [A166](HISTORY.md#a166)

### A121 · 2026-09-03 — Three doors: Vault, Know, Market
The Befund lives inside the Vault and the Plan door *is* the Vault. → [A121](HISTORY.md#a121) ·
[A136](HISTORY.md#a136)

### A136 · 2026-09-04 — Tresor, Wissen, Marktplatz
The German names of the three doors. → [A136](HISTORY.md#a136)

---

## The plan

### A9 · 2026-08-30 — FastAPI, SQLAlchemy, SQLite, Alembic
→ [A9](HISTORY.md#a9)

### A111 · 2026-09-02 — A plan version is a numbered baseline
Its household stamp is copied onto it rather than joined, so a version says what the household *was*.
→ [A111](HISTORY.md#a111)

### A132 · 2026-09-04 — The debt is one debt, and it belongs to the household
→ [A132](HISTORY.md#a132) · [A129](HISTORY.md#a129)

### A129 · 2026-09-04 — Property is bought with a mortgage, and a property goal funds the deposit
A goal for a home funds the equity, not the purchase price. → [A129](HISTORY.md#a129)

### A127 · 2026-09-03 — The five instrument keys are facts, not columns
→ [A127](HISTORY.md#a127)

### A117 · 2026-09-03 — The intake asks the household first
It records who drove the answer. The household is a table, never a column, and is never backfilled.
→ [A117](HISTORY.md#a117) · [A108](HISTORY.md#a108) · [A112](HISTORY.md#a112)

### A154 · 2026-09-05 — The intake file is kept whole, and mapped afterwards
The submission is stored as received and read from; nothing is dropped because the schema of the day had
nowhere to put it. A159 is what that bought: capacity inputs come from the plan first and the stored
submission second, and every value carries its provenance. → [A154](HISTORY.md#a154) ·
[A159](HISTORY.md#a159)

### A140 · 2026-09-04 — Invented names live in the file, never in the code
→ [A140](HISTORY.md#a140) · [A141](HISTORY.md#a141)

---

## Reproducibility and the engines

### A35 · 2026-08-30 — C-02: every figure comes from a published, versioned AssumptionSet
No literal rate in application code. A figure derived from an assumption carries the id of the set that
produced it, and nothing else carries one. → [A35](HISTORY.md#a35) · [A110](HISTORY.md#a110)

### A110 · 2026-09-02 — Validity horizons are a content record, not a published assumption table
→ [A110](HISTORY.md#a110)

### A69 · 2026-08-31 — C-03: the engines run in their own interpreter
No engine artefact is reachable from the browser. The `api` package does not import the engine façade,
and every runtime payload carrying engine output is checked before it is stored or returned. The
subprocess bridge exists because of a venv incompatibility, which is a packaging fact and not part of
the constraint. → [A69](HISTORY.md#a69) · [A85](HISTORY.md#a85)

### A150 · 2026-09-05 — The allocation comes from the Optimiser
Six portfolios, one allocation per member, the return from the manual. A148's equity ceiling is
withdrawn. Since A166 the allocation reaches the member with nothing between. → [A150](HISTORY.md#a150) ·
[A155](HISTORY.md#a155) · [A166](HISTORY.md#a166)

### A10 · 2026-08-30 — SIM Research owns all seven engines
→ [A10](HISTORY.md#a10)

### A146 · 2026-09-05 — The model store is on D:, reached by a junction
Not by an environment variable. The local model is qwen2.5:14b, measured rather than assumed (A145).
→ [A146](HISTORY.md#a146) · [A145](HISTORY.md#a145)

---

## The record, and who did what

### A40 · 2026-08-30 — Curators are staff, with their own table and their own login
Not a flag on `Member`. `CuratorSession.curator_id` is a foreign key into `curators`: the identified
curator is a row, never a role and never a queue. → [A40](HISTORY.md#a40) · [A98](HISTORY.md#a98)

### A161 · 2026-09-20 — A curator who leaves is revoked, not deleted
`curator_session_events` refuses DELETE by trigger, so deleting a curator who appears in a session event
leaves the audit unable to resolve its own "who". `Curator.in_service` is the single predicate every gate
asks — one implementation, because four copies of a condition is four chances to forget.
→ [A161](HISTORY.md#a161)

### C-09 · A72 · 2026-08-31 — Every material change to a plan produces a Decision, in the same transaction
Enforced twice: `before_flush` for ORM writes, and `before_execute` for Core DML, `bulk_save_objects`
and raw SQL. A write that goes round the ORM does not thereby stop being a violation. → [A72](HISTORY.md#a72)
· [A162](HISTORY.md#a162)

### C-10 · A63 · 2026-08-30 — The curator audit is append-only, at the store and in the ORM
A session is closed by appending a `closed` event, never by editing the one before it. Verified on a
*migrated* database, not on `create_all` — three separate migrations have silently dropped these triggers.
→ [A63](HISTORY.md#a63) · [A66](HISTORY.md#a66) · [A68](HISTORY.md#a68)

### A156 · 2026-09-06 — R-210 is relaxed for the curator dashboard, and the scope is written down
Everywhere else, a curator reading a member's material consults a live, scoped grant or raises.
→ [A156](HISTORY.md#a156)

---

## The product's own refusals

### A6 · 2026-08-30 — C-07: nothing scores a member
No gamification identifier in the member model layer — identifiers as well as words, because a payload
key named `score` passes a prose filter and is still the primitive C-07 forbids. The estate's `Score` is
an analytical household-standing measure and is never surfaced. R-113: the grid payload carries no filled
count, total or ratio. → [A6](HISTORY.md#a6) · [A119](HISTORY.md#a119)

### A74 · 2026-08-31 — C-08: ordering cannot be bought, and cannot be taken with a checkbox
Ranking is handed three integers and an opaque id; it cannot reach a fee. `role_match` is a *share* of
declared roles, so declaring more can only lower it. → [A74](HISTORY.md#a74)

### A119 · 2026-09-03 — Progress is a consequence, never a reward
No percentages, no badges, no streaks. The payload carries no number at all: a list of the findings still
locked and, for each, the questions it needs. → [A119](HISTORY.md#a119)

### A122 · 2026-09-03 — An undecidable lever routes to a human rather than being skipped
This is the one remaining path that sets `requires_curator`, and it is a product decision about a
computation that cannot be made — not a statement about who is licensed. → [A122](HISTORY.md#a122)

### A168 · 2026-09-20 — C-06 is gone; an action item is well-formed only by convention
`services/derive.py` still writes two options with labels and consequences and its own test asserts it.
Nothing at the store requires it, and any other writer may produce an item with an empty array.
→ [A168](HISTORY.md#a168)

---

## Building it

### A51 · 2026-08-30 — The design system is the live site's, verbatim
→ [A51](HISTORY.md#a51)

### A47 · 2026-08-30 — A deployable distribution, for a naked laptop
A friend unzips a folder and it works. No broker, no second process, no service to install.
→ [A47](HISTORY.md#a47)

### A53 · 2026-08-30 — Demonstration passwords may be written down, and say so truthfully
They guard a local demonstration database and nothing else. A password documented as good for one login
is enforced as good for one login (A89) — a false statement on an operator's terminal is worse than no
statement. → [A53](HISTORY.md#a53) · [A89](HISTORY.md#a89)

### A125 · 2026-09-03 — One implementation of a rule
A second copy of a list that must agree with the first is a defect, not a convenience. This is the
lesson A73 and A91 both are, and it is why `Curator.in_service` and `boundary.asks_about_the_member` each
live in exactly one place. → [A125](HISTORY.md#a125) · [A73](HISTORY.md#a73) · [A91](HISTORY.md#a91)

### A20 · 2026-08-30 — A guard that cannot fail is not a guard
Every absence-shaped assertion needs a companion proving it can still fire. A test that cannot observe
success is as useless as one that cannot observe failure. → [A20](HISTORY.md#a20) · [A75](HISTORY.md#a75)
· [A88](HISTORY.md#a88) · [A95](HISTORY.md#a95)

### A38 · 2026-08-30 — One commit per phase, on a branch
→ [A38](HISTORY.md#a38)

### A175 · 2026-09-21 — An answer may be written, and what that costs is measured rather than assumed
C-11 is reversed: the Know composes rather than quoting, over the corpus, the member's own record and
whatever this build can compute. A composed answer **can state something no source backs** — that is the
accepted cost, taken against forty-two refusals in fifty, thirty-six of which asked something no corpus
could ever answer. The two C-11 checks still run, as an audit on each answer's record rather than as a
gate, because the count of sentences that left the sources is the honest instrument for what was given up.
`ANSWER_MODE=quote` restores C-11 exactly and is still tested in full.
→ [A175](HISTORY.md#a175) · [A164](HISTORY.md#a164) · [A139](HISTORY.md#a139)

### A176 · 2026-09-21 — A model may write the words; it may not do the arithmetic
Every figure a member reads is computed by code that can be checked, or is quoted from a source, or is
named as missing. Three measured failures stand behind this and not one of them was a bad model: a salary
summed into four balances, an invented 10 % inflation assumption, and a twenty-year total nobody asked
for. Stocks and flows are therefore rendered under separate headings, `services/computations` runs before
the prompt is built, and the prompt forbids arithmetic outright.
→ [A176](HISTORY.md#a175)

### A177 · 2026-09-21 — A floor calibrated against one corpus is not a floor for another
`LEXICAL_ONLY_FLOOR` was measured against a 91 % English book index and applied to thirty-one reviewed
German entries written for members' own questions. Two of fifty questions reached one. A number that was
right where it was measured can be wrong one directory away, and the tell is that it never fires.
→ [A177](HISTORY.md#a175)

---

## Where to look for what

| Question | File |
|---|---|
| What rule applies here? | this file |
| Why is it that rule, and what did it cost? | [HISTORY.md](HISTORY.md), by entry number |
| What is known *not* to hold? | `/api/health` → `known_gaps`, and [status.html](client/status.html) |
| What did C-01 catch on its last day? | `reports/c01-final-measurement.txt` (A164) |
| What did deleting it let through? | `reports/cull-measurement.txt` (A169) |
