# `content/knowledge/` — German source material for the Know surface

Member-facing German explainers, one topic per file. They exist because the Know surface grounds its
answers in `desktop/bookindex/`, which is almost entirely the English *Capital Saturation* manuscript
plus eleven AHV passages — so it holds nothing on the third pillar, the second pillar, or what an ETF
is, and refuses most of what a Swiss member actually types.

**The retrieval gate loads only entries with `approved: true`.** A draft is inert until the owner has
read it line by line and flipped it — the drafts were written by a model, and no member sees a sentence a
person has not signed off. Fourteen entries were approved on 1 September 2026. The remaining twenty-one
were approved on 22 September 2026, on the owner's instruction and in one pass — including the four
written the night before, which is stated here because the paragraph above says approval means a person
read it line by line and that is not what happened for those four. The table at the bottom says which is
which, and it is generated from the files rather than kept by hand, because the hand-kept version went on
saying all fourteen were drafts for four days after they had been approved.

---

## File format

`<slug>.md`, UTF-8, Swiss orthography (`ss`, never `ß`). YAML frontmatter, then plain Markdown.

```yaml
---
id: saeule-3a-grundlagen          # matches the filename slug
title_de: "Säule 3a — was sie ist und wie sie rechnet"
language: de-CH
topic: vorsorge                   # vorsorge | anlegen | risiko | versicherung | wohneigentum
approved: false                   # the gate. false on every draft, without exception
reviewed_by: null                 # who approved it
reviewed_on: null                 # when, ISO date
sources:
  - label: "Verordnung über die steuerliche Abzugsberechtigung … (BVV 3), Art. 7"
    where: "SR 831.461.3, fedlex.admin.ch"
---

Body in German, plain Markdown.
```

Rules the drafts hold to, and any new entry should:

- **No file without a `sources:` list.** Every factual claim traces to something named.
- **A source is never invented.** Where the ground is general knowledge rather than a document, the
  entry says so in the `where` field, in those words. Where a leaflet number is uncertain, the entry
  names the series and flags the number for review rather than guessing one.
- **Every figure carries its year, in the sentence.** Swiss figures move annually. A figure with no
  year attached does not go in.
- **When in doubt about a current figure, the mechanism goes in and the number stays out.** Most
  entries end with a short section — *Was hier bewusst keine Zahl ist* — naming what was left out and
  where the current value is published. This is C-02's posture applied to statutory amounts: an
  invented maximum is worse than an absent one.
- **A figure goes in only when it is quoted, not remembered.** This is the rule that decides what an
  entry may say, and it is enforced by what is in the corpus rather than by good intentions.

  Until 5 September 2026 the only Swiss rule source in the index was AHV/IV-Merkblatt 2.03 and 3.04, so
  the three AHV entries carried Franken amounts and **everything else stayed omitted** — BVG thresholds,
  the Umwandlungssatz, the 3a maxima, the Mindest-/Maximalrente, the contribution percentages.

  Four more sources went in that day, and most of those omitted figures came with them. They live in the
  `knowledge/` folder of the **parent** estate, one level above prototype2, and are registered in the
  `SOURCES` allow-list in `desktop/bookindex.py` — an allow-list and not a glob, so that adding a source
  is a deliberate act and a dossier can never be swept in:

  | File | Source, and its Stand |
  | --- | --- |
  | `AHV_Beitraege_und_flexibler_Bezug.md` | Merkblatt 2.03 and 3.04, 1.1.2026 |
  | `AHV_Altersrente_Berechnung.md` | Merkblatt 3.01 and 2.01, 1.1.2026; BSV amounts sheet 1.1.2026 |
  | `BVG_Berufliche_Vorsorge.md` | BVG (fedlex) 1.1.2025; BSV amounts 1.1.2026; Merkblatt 6.06, 1.1.2025 |
  | `WEF_Wohneigentumsfoerderung.md` | WEFV (fedlex) 1.10.2017; BVG Art. 30c; BWO brochure |
  | `Saeule_3a_Grenzbetraege.md` | BSV amounts sheet, 1.1.2026 |

  The index went from 1 280 passages to 1 325. Every figure in those five files names its own Stand date
  in its own sentence, and each file ends with a section saying what it deliberately does not quantify.

  **Still omitted, because no source in the corpus states them:** the BVG-Mindestzinssatz, the percentage
  of earned income that additionally caps the higher 3a deduction (BVV 3 is not in the corpus), the
  Rentenskala table, the Erziehungs- and Betreuungsgutschrift amounts, and every cantonal tax figure.
  Each entry that wanted one says so in its own *Was hier bewusst keine Zahl ist*.
- **Where a source states its own limits, those limits go into the entry.** The AHV entries each end
  with *Was die Quelle selbst nicht sagt*, carrying the leaflets' own four caveats — above all that
  they do not compute an individual case and that the Ausgleichskasse is what binds. That caveat is
  the same boundary the product draws, so it belongs in front of the member.

---

## The approval workflow

1. Read the file. All of it, including the `sources` block.
2. Correct the German and the substance in place. Register: `Sie`, formal Swiss business prose, plain,
   unhurried, never salesy. The reference points are `client/content/roles.json`, the refusal texts in
   `backend/eigentlich/boundary.py`, and the `why_de` strings in
   `client/reference/questions-onb-0.1.3.json`.
3. Fill in the figures that were deliberately omitted, or leave them out — both are decisions.
4. Then, and only then, edit the frontmatter:

```yaml
approved: true
reviewed_by: "Nicolas Bürkler"
reviewed_on: "2026-09-01"
```

Approval is per file. There is no bulk flip, and there is no default-approve: a file with `approved`
missing or malformed is treated as unapproved.

If a file is later edited in substance, `approved` goes back to `false` until it is read again. The
signature is on a version, not on a filename.

---

## C-01

Nothing here may constitute personalised advice. The line the product draws is generic-versus-specific:
*"Die Säule 3a erlaubt 2026 einen Höchstbetrag von X"* is a rule that applies to everyone and belongs
here. *"Sie sollten den Höchstbetrag einzahlen"* is a recommendation and does not.

Every entry written before 20 September 2026 was run through the live outbound gate —
`eigentlich.boundary.check_answer` — sentence by sentence, and every sentence returned
`requires_curator: False`.

**That gate no longer exists.** C-01 was withdrawn on 20 September 2026 (A164) and the module was deleted
in the cull (A169); `eigentlich.boundary` now offers `asks_about_the_member`, which reads a question and
not an answer. The command that used to stand here raised `ImportError` when it was next run, on
22 September. There is no mechanical check of this rule any more, so the line above the code — generic
versus specific — is enforced by whoever reads the file and by nothing else.

Passing the gate is a floor, not a warrant. The gate is a pattern check with documented holes, and the
grounding rule described in DECISIONS A76 is what is meant to carry this eventually. A human reading is
still the thing that makes an entry safe.

---

## Current entries

35 files, 35 approved and 0 draft. Generated from the frontmatter.

| Slug | Topic | State |
| --- | --- | --- |
| `absicherung-was-versicherung-leistet` | versicherung | approved |
| `ahv-altersrente-hoehe` | vorsorge | approved |
| `ahv-beitragsluecken` | vorsorge | approved |
| `ahv-beitragspflicht` | vorsorge | approved |
| `ahv-referenzalter-und-bezug` | vorsorge | approved |
| `amortisieren-oder-anlegen` | wohneigentum | approved |
| `drei-saeulen-system` | vorsorge | approved |
| `erbrecht-pflichtteil` | recht | approved |
| `erbrecht-wer-erbt` | recht | approved |
| `freizuegigkeit-stellenwechsel` | vorsorge | approved |
| `hypothek-amortisation` | wohneigentum | approved |
| `indexfonds-und-aktive-fonds` | anlegen | approved |
| `klumpenrisiko-eigene-firma` | vermoegen | approved |
| `konkubinat-was-rechtlich-fehlt` | recht | approved |
| `rente-oder-kapital` | vorsorge | approved |
| `risiko-und-horizont` | risiko | approved |
| `saeule-3a-bezug` | vorsorge | approved |
| `saeule-3a-grundlagen` | vorsorge | approved |
| `saeule-3a-hoechstbetrag` | vorsorge | approved |
| `saeule-3a-und-3b` | vorsorge | approved |
| `scheidung-und-vorsorge` | vorsorge | approved |
| `selbstaendigkeit-und-vorsorge` | vorsorge | approved |
| `steuern-was-ein-abzug-wert-ist` | steuern | approved |
| `teilzeit-und-vorsorge` | vorsorge | approved |
| `vermoegen-anlegen-grundlagen` | anlegen | approved |
| `vorsorgeauftrag-und-patientenverfuegung` | recht | approved |
| `vorsorgeausweis-lesen` | vorsorge | approved |
| `was-ist-ein-etf` | anlegen | approved |
| `wohneigentum-eigenmittel` | wohneigentum | approved |
| `wohneigentum-tragbarkeit` | wohneigentum | approved |
| `wohneigentum-vermietet-und-ferienobjekt` | wohneigentum | approved |
| `wohneigentum-vorbezug-regeln` | wohneigentum | approved |
| `wohneigentum-vorsorgekapital-einsetzen` | wohneigentum | approved |
| `zweite-saeule-obligatorium` | vorsorge | approved |
| `zweite-saeule-pensionskasse` | vorsorge | approved |

Approve with the tool rather than by hand — it records **who**:

```
python tools/approve_knowledge.py --list
python tools/approve_knowledge.py --by "Nicolas Bürkler, SIM Research" <slug>
```

---

## Known gaps in the coverage

Named here so nobody mistakes this directory for complete:

- **Steuern** — one entry so far (`steuern-was-ein-abzug-wert-ist`), on progression and what an abzug is
  actually worth. It contains **no tax rate at all**, deliberately: a rate without a municipality is a
  number that gets misread. Still missing: the Steuererklärung itself, the Kapitalbezugssteuer, the
  Eigenmietwert, and cantonal differences as a subject.
- ~~**Wohneigentum**~~ — closed 4–5 September 2026: five entries now cover Eigenmittel, Tragbarkeit,
  Amortisation, let and holiday objects, and the WEF-Vorbezug with its statutory limits. All drafts.
- ~~**Life events**~~ — partly closed 5 September 2026. Inheritance has three entries and its own source
  document (`ZGB_Erbrecht.md`, quoting Art. 457–472 including the 2023 revision), and incapacity has one.
  **Separation and divorce remain open**, and the Vorsorgeausgleich is the biggest single thing missing.
- **Selbständigkeit** as a vorsorge situation, in its own right rather than as an aside.
- **Schulden und Zinsen** — the arithmetic of a mortgage, amortisation, compound interest.
- **French and Italian.** These entries are `de-CH` only, and the product addresses four languages.
