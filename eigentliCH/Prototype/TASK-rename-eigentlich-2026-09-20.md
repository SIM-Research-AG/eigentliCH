# TASK — the rename, andersCH becomes eigentliCH

For Claude Code, working in `andersCH-prototype2`. To be run **after** `TASK-cull-2026-09-20.md`
and not before. The cull deletes a large amount of code; renaming first means renaming
strings that are about to be removed, and then resolving both sets of changes in the same
files. One pass, in that order.

The precedent for how a rename is done in this repository is **A14 and A17**, the earlier
Decision rename: its own isolated step, its own commit, nothing else in it.

---

## The name

| Where | Form |
|---|---|
| Display, prose, UI, marketing | **eigentliCH** |
| Code identifiers, packages, modules, keys | `eigentlich` |
| Website | `eigentli.tech` |
| Local addresses | `@eigentli.local`, curators `@kurator.eigentli.local` |
| Repository and directories | `eigentlich-prototype2` |

Do not invent variants. No `EigentliCH` inside an identifier, no `eigentliCH` in a filename,
no camel case. If a place needs a form not in this table, stop and ask.

---

## What must not be renamed

1. **`DECISIONS.md` and `HISTORY.md` historical entries.** The product was called andersCH
   and the record says so. Rewriting 159 entries to claim otherwise destroys the value of
   the register, which is the same argument as the one about the three names in the cull
   task. Add one new entry recording the rename with its date, and one line at the top of
   each file saying the product was renamed on that date and that earlier entries use the
   earlier name.
2. **The estate.** `andersCH/` is imported, not copied (A1), and §9 puts it out of scope.
   Its directory name stays. Note every import path that crosses the boundary so the next
   reader knows which `anders` is which.
3. **The schema version.** `onb@0.1.3` carries no brand and does not move.
4. **Existing submission files already collected from real people.** Their filenames are a
   record of what was received. New submissions take the new prefix; the archive keeps its
   own. If the loader globs a prefix, widen the glob rather than renaming the evidence.

---

## Order of work

### 1. Inventory first, change nothing

Grep the repository for every case-insensitive occurrence of `anders`, and report a table
of file, line and context before editing anything. Split the hits into six groups so the
owner can see the shape once:

- code identifiers and module paths
- the client global namespace (`andersch.content.destination()` and anything else hanging
  off it)
- content keys and JSON files under `client/content`
- database values, above all the `@andersch.local` and `@kurator.andersch.local` addresses
- test assertions on literal strings
- documentation, the operator page, the design system, the Modelfile (A44 already records
  one naming mismatch there), and the distribution ZIP

Expect false positives. `anders` is a German word and a surname.

### 2. Code, then content, then tests

One commit per group. After each, the full suite runs green before the next begins.

Two known traps in this repository:

- **A22's literal scan.** A test scans the backend for the destination phrase as a literal
  and fails if anything inlines it. Renaming around content keys is exactly the work that
  trips it. Run it after every content change, not at the end.
- **Absence-shaped guards.** Several tests assert that something does *not* appear. A
  rename can make them pass for the wrong reason, because the old string is gone and the
  new one was never in the assertion. Grep the test suite for assertions containing
  `anders` and update the assertion, not only the fixture. A68's pattern, again.

### 3. The addresses are a data migration, not a find and replace

`@andersch.local` and `@kurator.andersch.local` are values in the database, and they are
login credentials. A62 put curators in their own namespace deliberately so an address can
never be ambiguous about which table it belongs to; the new namespace keeps that split.

- Write an Alembic migration that rewrites both namespaces, using `op.get_bind()` and not
  `.engine`. A63, A66 and A68 are all that mistake.
- Verify the append-only triggers survive the migration. They have been silently switched
  off three times by migrations in this repository, and the verification runs on a
  *migrated* database, not on `create_all`.
- After the migration, log in once as each remaining account and record the result. Four
  people and the demonstration accounts. An address change that nobody tested is an outage
  for the whole team.

### 4. The submission prefix

New files are `eigentlich-onboarding-<Name>.json`. The 50 synthetic records of
20 September 2026 carry the old prefix and can be regenerated with the new one, since
nobody answered them and there is no evidence to preserve; the real submissions keep theirs.
Widen the loader's glob to accept both, and add a test with one file of each prefix in the
fixture directory.

### 5. The operator page and the register

`status.html` carries the name in its title, its label and its prose. If Part 3 of the cull
task has already made the page a generated view, the name comes from one place and this is
a one-line change. If it has not, do that first rather than editing the page twice.

---

## The entry

One entry, A16x, in the new `DECISIONS.md`. It records: the name, the date, the casing
table above, what was deliberately not renamed and why, the migration and its verification,
and the count of occurrences changed per group. A rename whose scope is not written down is
one nobody can audit afterwards.

---

## Not in scope

The domain, the DNS, the mail, the certificates and anything outside the repository. The
owner is handling those. Nothing in this task reaches the network.
