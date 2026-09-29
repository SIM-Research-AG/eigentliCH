# eigentliCH Report Engine (report): handover

Where the build stands, how to pick it up, and what is still open. The README is the reference; this file is the
resume point. Model-derived research output; not investment advice.

## State (29.09.2026)

- **Engine 15, v1.4.1**, calibration 1.0.0, prompt `report-prompt@1.1.0`. 418 tests pass (`python -m pytest`,
  about 60 s, needs the PostgreSQL container); the prose case re-frozen live on 29.09.2026, seven prose sections
  verified on the first draft (model `google/gemma-4-31B-it-qat-w4a16-ct`). The running server on 8015 needs a
  restart to serve 1.4.1 (the coordinator restarts it; this build did not).
- **29.09.2026, lbsim and the charts** (REP-32 to REP-37): lbsim as a source (one per engine and artefact kind:
  findings, paths, plan), the refusals of a mix of sheets, Allocations, findings or paths, the five sections
  (earning power, income paths, outlook, plan, findings), lbsim's templates in the report's language, "wird
  berechnet" while the plan runs, and the three inline SVG charts (`charts.py`) with every printed value a fact.
  Built on B1's frozen samples; lbsim itself (B2, C) and the app's outlook routes (E) were built in parallel.
  Golden page with all three charts: `golden/reports/de_outlook.html` (and `en_outlook.html`).
- **29.09.2026, the nominal and real view** (REP-27 to REP-30): optional `basis: nominal|real` in
  `report-request@1.0.0` (default nominal, in the key only when real, so every earlier request keeps its id);
  the basis in the lede and next to every return and goal figure; real takes lbs's own real figures
  (lbs calibration 1.4.0, `real_view`, `views`) and needs a pcp Allocation of basis real; a mix is refused
  with its reason. Frozen inputs: two lbs 1.4.0 sheets built by lbs's code, one pcp real Allocation stand-in
  (`dev/freeze_inputs.py --real`). The running server on 8015 needs a restart to serve 1.3.0 (the
  coordinator restarts it; this build did not).
- **29.09.2026, fixes from the use cases**: the four roles carry the house's names from `reference/roles`
  (Absicherung and Einkommen, not Schutz and Ertrag; REP-24); a revision is a distinct report: optional
  `revision_of` and `revision_note` in `report-request@1.0.0`, in the key, the curator's remark on the page
  (REP-25); engine 1.2.0, goldens rebuilt with a revision case, the prose case re-frozen live (REP-26). The
  running server on 8015 needs a restart to serve 1.2.0 (the owner's session restarts it).
- **29.09.2026, owner's changes**: readers see no internal id and no upstream key, and one language: every lbs
  and pcp key and reason is a plain sentence in German and English (REP-19, `vocabulary.py`); persons and goals
  are named generically or by the caller's display facts `person.<id>` and `goal.<id>` (REP-20); the AI is
  MiniMind, spark7 the server (REP-21). Goldens rebuilt, the prose case re-frozen live (REP-22).
- Both extractors are complete: pcp (`pcp-allocation@1.0.0`) and lbs (`lbs-balance-sheet@1.0.0`, final).
- Store: database `simtech`, schema `report`, role `report`; password in `config.local.yaml` (git-ignored).
- spark7 token in `eigentliCH_Engines/.env` (git-ignored).
- Golden: sixteen frozen reports over frozen artefacts (`golden/inputs`, `golden/reports`; open the `.html` files to
  see them).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\Optimizer\engines\pcp && start.cmd                    :: 8007
cd Projects\Engines\eigentliCH_Engines\engines\lbs && start.cmd           :: 8013
:: lbsim on 8014 is started by the cockpit (autostart)
cd Projects\Engines\eigentliCH_Engines\engines\report && start.cmd        :: 8015, test bench at /
..\..\.venv\Scripts\python -m pytest
```

After an upstream contract change: `python dev/freeze_inputs.py` (lbs in-process; pcp with `--pcp PCP-... --pcp2
PCP-...` from the running pcp, or `--pcp-offline` with the Optimizer venv), then `python dev/build_golden.py`
(and `--live` for the prose case), and check the diffs.

## Open points

1. **pcp carries no `client_ref`**: its `client` is a free label, so a report cannot check that an Allocation is
   this client's (REP-10). lbs is checked.
2. **Upstream vocabulary** (REP-19): closed for every key lbs and pcp emit today; `tests/test_vocabulary.py` turns
   red when either adds one. The consumer app should send `goal.<goal_id>` display facts with the client's own
   goal names so the page reads them instead of "Ihr Wohneigentumsziel". No id is shown on any page (REP-23, the owner's
   decision): the sources table names each source in words with its date; the ids stay in the artefact.
3. **Misattribution** is not caught by the number check: a true figure of the section under the wrong label
   passes (narrowed by the per-section check, not closed).
4. The frozen pcp Allocations were built offline (pcp was stopped during the build); re-freeze them from the
   running pcp when convenient (`dev/freeze_inputs.py --pcp ... --pcp2 ...`).
5. **The consumer app** must add `revision_of` and `revision_note` to its mirror of `report-request@1.0.0`
   (extra fields are forbidden there) and send them on a curator's revision; its `Report` mirror ignores extra
   fields, so reading is unaffected.
6. The family README (`eigentliCH_Engines/README.md`) still lists this engine as a scaffold; it was outside this
   build's folders.
7. Deploy folder when signed off: `python dev/make_deploy.py`.
8. **The real view's inputs**: `pcp_allocation_real.json` is a stand-in (REP-29); freeze a real Allocation from
   the running pcp once fmre serves real ReturnSets, and re-run `dev/freeze_inputs.py --real` if lbs's 1.4.0
   sheets change. `freeze_lbs` builds under lbs's newest calibration (now 1.4.0): a plain re-freeze would
   change the nominal inputs too, so check the diff.
9. **The consumer app** must add `basis` to its mirror of `report-request@1.0.0` (extra fields are forbidden
   there) and send `"basis": "real"` with the real switch, together with a pcp Allocation solved on basis real
   and an lbs sheet under calibration 1.4.0; otherwise the report answers 422 with the reason.
10. lbs's plausibility reason and levers (LBS-34) and a goal's `amount_basis` are not printed yet; only the
   judgement is. The pensions' AHV figures carry no basis mark (lbs states none for them).
11. **lbsim's samples are hand-built** (B1, `made_by: sample`): once B2's engine publishes real artefacts, freeze
   one outlook from the running lbsim (findings, paths, plan of one sheet, with its lbs sheet and pcp Allocation)
   into `golden/inputs` and rebuild the goldens; the mirrors read only the fields named in REP-32, so an additive
   change upstream does not break them.
12. **The fan's last year** (REP-35): the sample's `deposit_eligible` band records the goal year after the deposit
   is paid, so the home goal's fan and its end figures dip at the goal date. The report reads index
   `goal year - start_year`; lbsim (B2) should state whether that year-end value is before or after a goal's
   payment, and if after, give the value at the goal date (the report then reads that instead).
13. **The consumer app** (E) sends the lbsim sources: findings and paths while the plan runs (the page says "wird
   berechnet"), then an update with the plan once `GET /outlook` says `ready`. A plan run that fails leaves the
   report saying "wird berechnet" until a report without the paths, or with a later plan, is asked; the report
   does not read lbsim's run state (REP-33). Its mirror of `report-request@1.0.0` must admit `lbsim` as a source
   engine and more than one source of that engine (one per kind).
14. A real report with lbsim draws on lbs and lbsim alone while lbsim's Allocations are nominal (REP-36), and takes
   charts 1 and 2 from the paths' `allocation_view`, chart 2 as lbsim's converted real curves (REP-38). The app
   must therefore leave the pcp source out of a real request that carries lbsim paths.
15. The five lbsim sections have no prose slot; adding slots is a new calibration version.
