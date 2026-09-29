# The rename inventory — 21 September 2026

`TASK-rename-eigentlich-2026-09-20.md` step 1: *"Inventory first, change nothing."* This is that, taken
against the tree as it stands **after** the cull and the move, which is why the figures differ from the
ones in A160 — C-01's deletion removed a large amount of text and the old material left the repository.

## Totals

| Form | Occurrences |
|---|---|
| `andersch` | 986 |
| `andersCH` | 474 |
| `ANDERSCH` | 47 |

Excludes `.venv`, `.git`, caches, `reports/` and `client/submissions/`.

---

## The six groups

### 1 — Code identifiers and module paths

| | |
|---|---|
| Package directory | `backend/andersch/` → `backend/eigentlich/` |
| Files importing it | **82** |
| `pyproject.toml` | `name`, `description`, `[tool.setuptools.packages.find] include` |
| `db.py:379` | the default database file, `andersch.db` |

### 2 — The client global namespace

`andersch.sim` (4) and `andersch.session` (1). Five occurrences, one object.

### 3 — Content keys under `client/content`

Two files only: `destination.json` (`andersch.content.destination`) and `life-events.json`. **A22's
literal scan guards the destination phrase** — a test fails if anything inlines it — so this group runs
before the tests are touched and the scan runs immediately after, not at the end.

### 4 — Database values: the addresses

| | |
|---|---|
| `andersch.local` | 34 |
| of which `kurator.andersch.local` | 19 |
| Literal addresses in tracked source | 6 (`befund@`, `kurator@`, `yasmin@`, `nicolas@kurator`, `niemand@kurator`, and one malformed `05@`) |

Everything else is built by `_email()` and `_curator_email()` in `tools/seed_demo_accounts.py`, which is
one line each. **This group is a data migration, not a find-and-replace** — 83 member rows and 6 curator
rows hold these as login credentials.

### 5 — Test assertions on the literal

66 test files mention the name; **12 assert on it directly**:

| File | What it asserts |
|---|---|
| `test_capability_assertion_api.py:182` | the word is in a forbidden list |
| `test_capability_assertion_api.py:405,406` | payload keys `andersch_states_capabilities_only`, `andersch_assesses_capabilities` |
| `test_client_s07_settings_capabilities.py:363` | the same key, in client source |
| `test_consent.py:523` | `"andersCH stores and processes"` — member-facing consent copy |
| `test_curator_signin.py:238` | `nicolas@kurator.andersch.local` |
| `test_learning.py:244,480` | the two payload keys again |
| `test_learning.py:464`, `test_marketplace.py:1189` | NG-04 messages |
| `test_runs.py:455` | `"a defect in andersCH"` |
| `test_time_allocation.py:113` | **`"kein Kapital anders"` — the German word. Must not be renamed.** |

`andersch_assesses_capabilities` is a **payload key** read by the client, so renaming it is a contract
change across server, client and four tests in one commit or none.

### 6 — Documentation, operator page, design system, distribution

| Location | Files |
|---|---|
| `content/knowledge/` | 18 |
| `backend/migrations/` | 12 |
| `dist/` | 5 |
| `desktop/` | 4 |
| root `*.md` / `*.html` | 7 |
| `client/reference/` | 3 |
| `client/style/` | 2 |

---

## The false positives — 32 of them, and one is an assertion

`anders` is an ordinary German word meaning *differently*, and it appears 32 times where it is **not**
the product:

- **12 knowledge articles** — member-facing prose: *"Die AHV verhält sich anders"*, *"was seit 2023
  anders ist"*, *"warum diese Käufe anders finanziert werden"*.
- **`test_time_allocation.py:113`** — `assert "kein Kapital anders" in ...`. A case-insensitive rename
  breaks this test, and it is the only one that would fail loudly. The others would corrupt German prose
  silently.
- `services/know.py:607,613` — *"Fragen Sie anders"*, in a member-facing notice.
- `services/time_allocation.py:232`, `client/app/i18n.js:385`, `client/intake.html:738`,
  `test_position_edit_api.py` (5 × a fixture label `"Anders benannt"`), `questions-onb-0.1.3.json` (4).

**Every replacement must therefore be anchored**: `anders` followed by `ch`, `CH` or `Ch`, never `anders`
alone.

---

## Filenames

| | |
|---|---|
| `backend/andersch/` | the package |
| `backend/andersch.db` | plus 5 `.before-*` snapshots from this week's migrations |
| `client/reference/andersch-site-index.html`, `andersch-site-styles.css` | |
| `andersCH-build-spec.html` | the specification — **keeps its name**, it is the document the build is named after |
| `client/submissions/andersch-onboarding-*.json` | **60** |

On the submissions, the task rules: real ones keep their filenames because those are the record of what
was received; the 50 synthetic ones may be regenerated. **Recommendation: change neither, and widen the
loader's glob instead.** All 60 are now loaded, and `load_submission._names` derives each member's login
address from the filename — renaming the files after loading would leave 83 member rows whose addresses
no longer match their source. Widening the glob costs one line and breaks nothing.

---

## What is deliberately not renamed

1. **`DECISIONS.md` and `HISTORY.md`.** The product was called andersCH and the record says so. One
   dated line at the head of each, and a new entry. Same argument as the three names in the cull.
2. **The estate.** `engines/`, `contracts/`, `orchestration/` are imported, not copied (A1), and §9 puts
   them out of scope. Note: the estate is now the *only* thing beside the build in the repository root,
   so "which `anders` is which" is easier than it was — anything under `andersCH-prototype2/` is the
   build's.
3. **The schema version `onb@0.1.3`.** Carries no brand.
4. **`andersCH-build-spec.html`.** The specification the build was written against.

---

## Order of execution, and the two traps

Groups run in the task's order — code, then content, then tests — one commit each, full suite green
before the next.

- **A22's literal scan** runs after every content change, not at the end.
- **Absence-shaped assertions.** A rename can make an `assert X not in ...` pass for the wrong reason,
  because the old string is gone and the new one was never in the assertion. Grepped: there are **no**
  absence-shaped assertions containing the name, so this trap is not present here. Recorded because the
  task asks for it to be checked, and "checked, not present" is a different statement from silence.
