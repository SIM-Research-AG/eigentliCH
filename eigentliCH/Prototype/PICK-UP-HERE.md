# Pick up here — parked 22 September 2026

**The Know answers now.** Of sixty members asked the opening question they arrived with, **58 got an
answer**; on 20 September it was eight of fifty. C-11 was reversed to get there (A175) and what that
costs is measured rather than asserted — see below.

```
backend/  ../.venv/Scripts/python.exe -m pytest -q
          2461 passed, 15 skipped, 3 xfailed, 1 failed

the 1 failed is A142's W_L disagreement. It predates all of this and fails on a clean checkout.

migrations at head: b81f4c2e9a37
branch:             update-script-v2.1, 92 commits ahead of master, nothing pushed
```

**Start with [`reports/ISSUES-2026-09-21-FOLLOWUP.md`](reports/ISSUES-2026-09-21-FOLLOWUP.md).** It is
the before-and-after on §2 of the 20 September run, with the audit numbers. Everything in this section
is either something it names or something it does not.

---

## What changed, in one paragraph each

**The diagnosis was not the corpus.** Thirty-six of the fifty questions that retrieved nothing were
personal and computational — *"wie gross ist meine Vorsorgelücke"*, *"reicht unser Sparen"* — and no
Merkblatt can answer those. Meanwhile 296 positions and 128 goals sat in the same database and the answer
path could not see one of them: its universe was the vault, the learning units and the impersonal corpus,
and the fifty loaded clients had neither vault items nor learning units.

**`services/member_ground.py`** puts the member's own record in front of the model — what they stated
about themselves, their positions, their goals, their household, and what they said about their plan.
Route-gated exactly as the vault is, with a planted-violation test.

**`services/compose.py`** writes the answer. `ANSWER_MODE=quote` restores C-11 exactly and is still
tested in full (52 tests in `test_know.py`). The two C-11 checks still run, as an **audit on each
answer's record** rather than a gate — that is the instrument for what the reversal cost.

**`services/prose.py`** guarantees the answer is prose. It was a line in the system prompt until a model
returned 645 words under six headings with two tables and sixteen emoji; tightening the wording made it
longer.

---

## The two things approved on 22 September

Both on the owner's instruction, both recorded honestly where they live.

**`bvg-projection.json`** is signed. Its four `_for_review` concerns are **not resolved** and the record
says so; every franc it produces carries three caveats on the answer itself.

**The knowledge corpus is 35 of 35 approved**, up from 14. Four of the twenty-one flipped that day were
written by a model the night before and were approved without the line-by-line reading the README calls
for. The README says that about itself now.

`ahv-pension.json` is **untouched and still refuses.** It had shared a test with the BVG record; they
have one each now, because one guard over two records means approving either silences both.

---

## What is open, in the order I would take it

1. **The answer can be long and can drift to an adjacent question.** The 648-word example is in the
   follow-up report. The drift is S-08/relevance, already a strict xfail in the suite; the length has no
   mechanical bound yet and the prompt does not hold it.
2. **Twenty-one of 58 answers contain a figure that is in no source.** That is the price of A175 and the
   number to watch: if it climbs, the prompt has stopped working on whatever model is configured.
3. **§3 of the 20 September run — every goal unfunded.** 128 goals, none linked to a position. The loader
   is right not to guess which money covers which goal, but the first thing every loaded member sees is
   that nothing is covered.
4. **§6 — seven corrupted filenames.** `ChristophL├╝thi` and six more. Those members are in the system
   under an unreadable surname, and `load_submission._names` derives the login address from the filename.
5. **`retirement_provision` does not compute a gap**, only the provision. A gap needs an approved record
   of what a member needs to live on, and there is none.

---

## What is deliberately not done

The estate (`engines/`, `contracts/`, `orchestration/`) is untouched; §9 puts it out of scope. Nothing is
pushed. `tools/make_distribution.py` and `tools/extract_reference_questions.py` both want files from the
sibling `andersCH-prototype/` that the cull archived into `andersCH-prototype_old.zip` — extracting
`Modelfile.apertus-8b-de` and `onboarding-chat.html` from it restores both.

---

# The 5 September parking note, kept

The **eigentliCH app update script v2.1** is built end to end (A108–A128). What happened after it is more
useful to read: all six real submissions were run through the running application, the gap between what
the product said and what the data supports was written up, and then most of that gap was closed.

```
backend/  ../.venv/Scripts/python.exe -m pytest -q
          2730 passed, 16 skipped, 4 xfailed        (2652 on 4 Sept, 2278 on 1 Sept)

migrations at head: b7c2f1e48a30
decisions recorded: A108 – A153   (DECISIONS.md, 153 entries)
branch:             update-script-v2.1, 16 commits ahead of master, nothing pushed
```

**Start with [`reports/members-2026-09-04.html`](reports/members-2026-09-04.html).** It is the state of the
product seen through **all ten members**, with allocation by vessel, asset trajectories, a twenty-six-year
timeline and dated action points. Everything below is either something it names or something it does not.

Beside it on disk, and **deliberately not in git**: `cases.json`, `members-system-output.txt`,
`members-allocation.txt` and `members-property-arithmetic.txt`. Those are full API captures of real
people's finances under their own names, which is the same reason `client/submissions/` is ignored — and
three of them were committed on 4 September before anyone thought about it. They are regenerable in one
command, so nothing is lost:

```
python tools/run_cases.py && python tools/allocation_check.py && python tools/property_check.py
```

**One question that is yours.** The curated report *is* tracked, and it carries the same names and the
same figures — Marvin's 222'750, Reto's 2'500'000 mortgage, everyone's own question. It is the
deliverable, so it stays until you say otherwise; but if submissions are ignored because they are real
people's money answers, the report is the same data with better typography. The three already-committed
captures are also still in history, which matters only if this repo ever gets a remote — the same caveat
as the database.

---

## Where the models live

`C:\Users\nicol\.ollama\models` is a **junction** to `D:\ollama\models` (A146). 34.57 GB moved off C:,
which now has 92 GB free instead of 55. Ollama looks where it always looked, so nothing needed configuring
and nothing breaks at logon — `OLLAMA_MODELS` was tried first, works for a hand-started server and **not**
for the app Windows autostarts, and was deliberately cleared so there is only one mechanism.

The embedder is **`bge-m3`** and is fixed by the book index — two models are two coordinate systems, so
that one must not change (A145).

---

## The one thing to know before touching anything

**The developer database drifted from the schema and `alembic current` did not notice.** Two tables from
A108's household migration were absent while the version row said head, so a household could never have
been written in this database — which is why every Befund said *«Zu Ihrem Haushalt ist nichts erfasst»*
(A134). Repaired.

There is still **no check comparing the model's tables against the database's**. It is three lines, it does
not exist, and it is why a whole feature was silently unreachable for four days:

```python
from sqlalchemy import inspect
from eigentlich.db import make_engine
from eigentlich.models import Base
missing = set(Base.metadata.tables) - set(inspect(make_engine()).get_table_names())
```

---

## Five things waiting on you

### 1. Read the seventeen knowledge drafts — and the four rule sources behind them

`content/knowledge/` now holds **26 entries: 14 approved, 12 draft**. Every draft carries
`approved: false`, which is that directory's own rule — *no member sees a sentence a person has not signed
off* — and they are inert until you read them and flip the flag.

The twelve split into two groups.

**Eight from 4 September**, on Wohneigentum, Teilzeit, Selbständigkeit and Anlegen. Unchanged since you
last saw them, except `wohneigentum-eigenmittel.md`, which had one sentence rephrased: it was tripping the
outbound C-01 gate on a description of an asset, because every pattern in `boundary` compiles with
`re.IGNORECASE` and so cannot tell `sie` from `Sie` (A149). A test now runs the real gate over every entry.

**Four from 5 September**, and these are new in kind — they carry Franken amounts, because the corpus
finally holds documents that state them:

| file | what it covers |
|---|---|
| `ahv-altersrente-hoehe.md` | min 1 260 / max 2 520 per month, the 13. Altersrente, Rentenskala 44, the 1/44 a missing year costs |
| `zweite-saeule-obligatorium.md` | the 22 680 threshold, Koordinationsabzug 26 460, Altersgutschriften 7/10/15/18 %, Umwandlungssatz 6,8 % |
| `wohneigentum-vorbezug-regeln.md` | WEF: 20 000 minimum, every five years, the age-50 formula, and the letting exception in WEFV Art. 4 Abs. 2 |
| `saeule-3a-hoechstbetrag.md` | 7 258 with a Vorsorgeeinrichtung, 36 288 without |

That was possible because four rule sources went into the index — BVG and WEFV from fedlex, the BSV
amounts sheet for 1.1.2026, and Merkblätter 3.01 / 2.01 / 6.06 (A147). The index went 1 280 → 1 325
passages, and questions that used to come back empty now land on the right passage first.

Approve with the tool, never by hand — it records **who**:

```
python tools/approve_knowledge.py --list
python tools/approve_knowledge.py --by "Nicolas Bürkler, SIM Research" <slug>
```

Each entry ends with **«Für die Prüfung angemerkt»** naming what specifically wants your eye. The four new
ones each flag something real: a figure this text computed rather than quoted, three different Stand dates
in one entry, a sentence that is market practice rather than law, and one deliberately-blank percentage.

### 2. Eighteen questions the current instrument stopped asking

`onb@0.1.3` added three keys and dropped eighteen (A138). The dropped ones are the questions this week
needed and did not have — most sharply **`own_use_pct`**, which *is* the occupancy question: `Goal.occupancy`
was built on 4 September because nothing could answer it, and a member answered it on 18 August with `20`.
Also `mortgage` and `amortisation` (one file carries 2'500'000), `children_ages` in the exact format
`identities.child_ages` parses, `partner_pillar2`, and `matrimonial_regime`.

By A127's mechanism each is **one entry in `client/content/onboarding-questions.json` and no code**. The
loader now names all eighteen in a third report section instead of dropping them silently; nothing is
written and A8 stands.

### 3. The five return-profile questions

Still drafted, still unapproved, and now blocking more than before. You ruled that **the most conservative
answer binds** at household level — recorded as A133 and *not implementable*, because without published
bands there is no ordering to be conservative about. Every goal in the build has all five parameters open.

The fourth option Renzo's answer needs — *noch nicht investiert* — is still missing from `crisis_behaviour`.

### 4. Two questions the Optimiser raised, and neither is about a member

The allocation record drafted earlier on 5 September was **withdrawn the same day** (A150). It invented a
50 % drawdown, a horizon ladder and an equity/bonds split, all of which already existed better in
`engines/PCP`. The service, the record and its 41 tests are gone. Nothing there needs your approval.

What replaced it raised two questions that do need you, and both are CIO questions rather than member ones.
**Read `reports/allocation-pcp-2026-09-05.html` first.**

**4a. Ten members came back with two portfolios.** The role bounds in `POLICY_BOUNDS` are identical for
every household, the universe is the same eight instruments, and the Optimiser reports that the weights
control under 1 % of the objective's level. So the household's own position barely moves the result: five
reachable goals get one portfolio, five unreachable ones get the other, and that is the whole variation.
Is that the intended sensitivity, or should some bound vary by household?

**4b. Four of the eight instruments receive nothing, in either portfolio.** And the register carries
exactly **one** Income block, so the 10 % Income floor is a floor on a single instrument rather than on a
category with alternatives. `engines/lbs/derive.py` already says in its own comment that this argues for a
second Income instrument more than it argues against the floor. That is a Fund Map decision, not a PCP one.

**What does not need you:** whether a member's stated maximum loss should reach the mandate. It was
measured instead. Both portfolios bottom out at −5.99 % and −8.15 %, and the tightest tolerance anybody
stated is 10 %, so no stated limit binds on anything. The question is answered on the evidence.

---

### 5. Approve the AHV table and the pension projection — or say why not

Two new content records, both `provisional: true`, both refusing on every computing path (A153). The
retirement finding attaches to a goal and reports `could_not_be_determined` until you sign them.

**`ahv-pension.json`** carries the 51 published rows of Skala 44. Its own `_for_review` names four things,
and the first is mine to flag rather than yours to find: the table is *«Gültig ab 1. Januar 2025»* and is
used for 2026 on the strength of the BSV sheet saying the amounts did not change. That inference is the
first thing to check. The other three are about what is missing — Erziehungs- and Betreuungsgutschriften
and Splitting all raise the figure and none is modelled, so what it produces is too low for anyone who
raised children.

**`bvg-projection.json`** projects the age bands forward at the Mindestzinssatz of 1.25 %, which you chose
over zero and over a band. Its `_for_review` says the uncomfortable part plainly: it is this year's floor
projected forty years, it covers the obligatory portion only when the überobligatorisch part is usually
larger, and a member will read a forecast whatever the caveat says.

**The one input neither can get.** The AHV table is keyed on the *massgebendes durchschnittliches
Jahreseinkommen* — a revalued lifetime average. The build holds current income. `illustration_for()` makes
the substitution loud rather than silent, and `intake.html` now asks for the real figure, which is on the
IK-Auszug. Whether a member should be shown a pension keyed on a stand-in at all is the second review item.

---

## Where the property work stopped

`services/property.py` is built, tested, wired into every goal payload, and its conventions are approved
under your name. It answers `could_not_be_determined` for all five real property goals, for **two reasons,
neither of them a defect**:

1. ~~**Nobody has been asked the occupancy question.**~~ **Closed 5 September (A151).** The control is on
   the screen: `occupancyNode` in `containers.js` renders the verdict, the question, the three options
   read from the content record, and clearing as an option. Verified in a real browser and end to end
   against a live server — answering it records a Decision in the member's own words and the affordability
   test computes. **And answering it for the first time found a defect**: a let property was reporting
   `does_not_meet` on an affordability figure containing no rent.
2. **No goal has funding linked**, so the equity half reports `no_position_is_linked_to_this_goal`. The
   loader creates goals and positions and never links them, because which holding funds which goal is a
   judgement. The affordability half answers regardless — it reads the income position directly.

   **Checked on 5 September and it is not a build gap.** The funding control already exists in the edit
   form and works end to end: linking Marvin's positions cleared every undetermined reason and produced
   all three levers. This is unpopulated data behind a working affordance, and the loader is right not to
   guess. Verified while there that a salary linked as funding is *not* counted toward a deposit — the
   `STOCK_UNITS` filter skips flows.

   One weakness worth your eye, already flagged in `_capital_by_eligibility`'s own docstring: it
   classifies the Vorsorge vessels by reading `Position.label`. A member who types a label the patterns
   miss has their pension counted as **hard equity**, which is the permissive direction on a regulated
   test. The fix is a vessel field on `Position`, which is a schema change and not mine to make.

**Do not close the second by linking funding in the loader.** A guess there is one a member cannot see or
correct, and the finding it produced would be about the guess.

---

## What the six cases closed

| Finding | State |
|---|---|
| Property goals read as savings targets | closed — A129, conventions approved |
| The Know answered none of six questions | closed pending your review — A135 |
| A credential mistaken for a plan; a record half-built | closed, and the record repaired — A130 |
| `W_L` and `E` mean opposite things across the bridge | registered and guarded; a fourth found — A131 |
| The household mortgage read by nothing at all | reported — A132 |
| A funded property goal measured against the price | closed |
| Pillar 2 withheld with no role | closed — Elio 81'000 → 697'000 |
| No member had a household | closed — all six have one |
| Two tables missing from the developer database | closed — A134 |
| Doors labelled in the wrong language | closed — Tresor / Wissen / Marktplatz |

---

## Open, recorded, not blocked on you

* **Levin's household is one adult**, because `ledig, mit Partner` is not a married couple and your ruling
  said married couple. His partner's stated 85'000 stays out of the affordability test, so his ceiling is
  509'434 instead of 990'566 against a 1.1 million goal. `MARRIED` in `tools/load_submission.py` is the one
  word that changes it.
* **Elio and Yasmin's households do not know about each other.** Two adults each, and no way to reach the
  other member's income — a household member row carries a label, not an account. So `_household_income`
  returns `None` for both and their affordability is undetermined. Linking one member's record to another
  member's account is a privacy question with an owner and has not been asked.
* **The four structured education answers and `mandates`** are still unstored, so `expertise_scale` and
  half of `net_scale` have nothing to run on. Reported by the loader rather than dropped. Each costs one
  entry in the content file.
* `gatherings` is never seeded, so the Feed's `groups` section is empty in any running copy.
* R-151 extraction has no production caller. R-182: the Know cannot open a life-event module.
  `Member.stage_hint` has no writer. `Consent.notes` is written by nothing.
* **The client audit's twenty-two findings from 1 September are still unaddressed** — including
  `client/surfaces/vault.js:285` using `ApiError` without importing it, so a failed save shows the member
  nothing. One line.
* **A database is in git history.** `backend/eigentlich.db.before-fk`, two commits, member rows and
  credential hashes. Out of the index, ignored, still in history. Bounded only while no remote exists.
* **The distribution has no archive**, deliberately. `dist/NO-ARCHIVE-YET.md` says why and what a rebuild
  must pick up. Your pass through the running application is what releases it.

---

## The members you can test against

**Ten**, all coherent as of this evening. Each was created through the same path a member's own clicks
take, so each carries the Decisions C-09 requires. Six are real people under their own names; the four
loaded last (A141) came in anonymously and carry **invented** names — the file's own `meta.pseudonym_note`
says so, and the loader prints an `INVENTED` line every time it describes one.

| Member | Age | Household | What they exercise |
|---|---|---|---|
| **Marvin M.** | 23 | 1 adult | All four role cells; deposit met, income binds; his question is a sublet |
| Renzo T. | 24 | 1 adult | The `crisis_behaviour` answer no option holds; savings exceed income |
| Elia T. | 21 | 1 adult | Highest savings rate of the six, and no 3a at all |
| Levin S. | 25 | 1 adult | `ledig, mit Partner`; the near miss at 11 %; a partner not in the model |
| Elio T. | 58 | 2 adults | 697'000, retires 2033, seven contribution years left |
| Yasmin T. | 53 | 2 adults | 782'100 of household debt; 172'000 that may not fund her goal |
| Ueli W. | 62 | 2 adults | 840'000, retires soon, a partner named only as «Partnerin» |
| Sandra I. | 39 | 2 adults | The first real dependent children — born 2020 and 2022 |
| Nadine C. | 55 | 1 adult | 1'010'000 and a 200'000 mortgage; «derzeit ohne Erwerb» at 10 h/wk |
| Reto K. | 45 | 1 adult | A 2'500'000 mortgage, a company, and `verwitwet` |

The four loaded last have first-login passwords of the form `erstanmeldung-<local part>-bitte-aendern`
— `erstanmeldung-ueliw-bitte-aendern` and so on, good for one sign-in.

Passwords are **`andersch vergleichslauf vom vierten september`** for Renzo, Elia, Levin, Elio and Yasmin —
changed by the comparison run, because `must_change` refuses every member route and completing the change
is part of signing in. Marvin's is `ein hinreichend langes passwort`.

**And four more, unloaded and anonymous.** `client/submissions/archive/` holds four distinct people (two
of the five files are byte-identical): 62 in Bern, 39 in Zug with children born 2020 and 2022, 55 in
Freiburg with a 200'000 mortgage, 45 in Schwyz with a 2'500'000 one and a company. They are the only
**held-out** questions this build has, and they are why A139 exists. Loading them is blocked by something
simpler than the schema: they carry no names, so there is no display name to give a member row.

Reproduce the whole comparison:

```
python -m uvicorn eigentlich.api.main:app --port 8894      # from backend/, in the venv
python tools/run_cases.py                                # twelve routes per member, plus their own question
python tools/property_check.py                           # the two property tests, against the submissions
```

---

## Method notes worth not relearning

**Running it is not the same as testing it, and this week paid for that three times.** The suite was green
at 2 650 while: a member's record was half-built and rendering perfectly; a whole feature was unreachable
because two tables were missing; and the equity test told a member they were short of a deposit they had.
All three were found by signing in as a real person and reading the number. None was found by a test.

**A guard that reads prose fails for reasons unrelated to the property it names.** Three written this week
matched the forbidden word inside their own docstring. All three now walk the AST.

**A control with no branch renders as a text input and looks fine.** `tools/walk_screens.mjs` draws every
question and reports the control each produced — but only the *option-count* assertion catches a missing
`choice` branch; "is there a control" says ok.

**A probe written in ASCII measures the wrong thing.** A knowledge entry looked unreachable on `vermoegen`
until it was re-run with the member's actual umlauts: the tokeniser folds ö to o, not to oe. The failure
was in the probe.

**German compounds do not decompose in the lexical channel.** An entry full of *Wohneigentum* cannot be
reached by someone who types *Eigentum*, and *Eigenmittel* never answers *Eigenkapital*. Writing eight good
entries moved retrieval from 2 of 12 to 2 of 12. Giving each entry a section naming its questions *in the
member's own words* took it to 11 of 12. The content was the fix; the floor of 700 was calibrated on a
different corpus and is still worth a look.
