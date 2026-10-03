# cycle: decisions index

Every place this build departs from the first draft (`Projects/eigentliCH/engines/Macro_Model`,
`macrofield/model/cycles.py` and `cycle_bins.py`), from the engine page, or from a
convention, with the reason. The golden test classifies divergences against this list: a
difference that is not here is a bug.

## Decisions taken in this build

**C-01 Anatomy.** The same as `honi`: the Guide's section 2 layout plus `service.py`
(orchestration), `settings.py`, `schema.sql` and `__main__.py`; the PostgreSQL store with
append-only calibrations and artefacts; tests against a real server in throwaway schemas and a
real datafeed; the concurrency test; the test bench; `start.cmd`; the deploy builder. `store.py`,
`settings.py`, `schema.sql`, `clients.py` and `__main__.py` are honi's with the names changed.

**C-02 `psycopg` is outside the allowlist.** As honi D-05: the Guide mandates PostgreSQL. `scipy`
is on the allowlist and is used at run time for `signal.hilbert` and `signal.welch`, as the draft.

**C-03 Data comes from datafeed (and, from 1.1.0, macrofield; C-18).** Six series, by name (`engine.REQUIRED_SERIES`):
`production.gdp_nominal`, `inflation.cpi_yoy` and the four debt series honi's capital saturation
is built from. The draft read its own economy files; nothing here does.

**C-04 Annual, December.** The draft is annual (its macro path is annual, and it states that a
monthly timeline held flat within the year adds no sub-annual information). The panel is reduced
to calendar years by the December cell, as honi (`annualisation: year_end`; `mean` available).
Real output = nominal GDP deflated by the December CPI year-on-year rate (`deflate_output`).
Output growth is `np.gradient(log real output)`, the draft's input, rebuilt from year-on-year log
growth so that a deflator gap stays local.

**C-05 A gap is never filled.** The draft refuses non-finite input. Here an estimated cycle is
band-passed on the **trailing contiguous span** of its input, and the years outside it carry no
phase; the span is stated in the track's notes and the gap in `coverage.input_gaps`. The
superposition and synchrony cover the years every member has a position in. On the production
snapshot one economy is affected: CH, whose CPI for December 2025 is missing, so its estimated
cycles end in 2024 and `/cycles/{id}/current` reports them for 2024. PH and VN have no capital
saturation at all (their corporate debt is a placeholder in datafeed, DF-13), so their capital
cycle cannot be anchored.

**C-06 The Christiano-Fitzgerald filter is reimplemented.** statsmodels is not on the allowlist.
`engine.cf_filter` is a transcription of `statsmodels.tsa.filters.cf_filter.cffilter` (0.14),
index for index, and agrees with it to 0.0 on every test series. statsmodels is a `dev`
dependency only, for `golden/build_golden.py` and one test. Hodrick-Prescott, the draft's
alternative, is not ported: the draft's default is CF and HP mixes neighbouring cycles.

**C-07 The five cycles, and what each reads.** The engine page asks for five nested cycles; the
draft carries six. Calibration `1.0.0` takes the **nested ladder**: `fundamental_pulse` (3.6 y,
band 3.0 to 4.5), `business` (7 y), `credit` (18 y), `innovation` (anchored low 2032, 47 y) and
`capital` (anchored at saturation 3.5 = 90 years in, 90 y). The 130-year hegemonic succession is
left out of the five, since the draft already keeps it out of the interference measure; it is one
calibration entry away (`anchored_peak`, 1945, 130 y, `in_interference: false`, tested).
**Confirmed by the author on 2026-09-27**: the five are pulse, business, credit, innovation and
capital; the hegemonic period is carried by the capital cycle's 130-year length (C-16). Pulse,
business and credit all read real output growth, as in the draft. In 1.1.0 the credit cycle
is anchored on crisis dates instead (C-17); `input: saturation_change` remains implemented.

**C-08 The cycle set is calibration.** Each cycle is a `CycleSpec`: kind (estimated or one of
three anchors), period, band, input, orientation, whether it enters interference, and its layer
and superposition weights. The draft kept these in four separate config blocks keyed by name.
Adding, removing or re-reading a cycle is a new calibration version, not a code change.

**C-09 A cycle without a position is left off the axis.** In the draft, a cycle with no phase
(the unidentifiable credit cycle, an unanchored capital cycle) raises in `layer_from_cycles` for
the first year and makes `layer_matrix` publish a **flat row** there, while later years skip it.
Here it is skipped in every year, so the first year is the mixture of the cycles that do have a
position. Where no cycle at all can be placed, the layer is `null` for that year, not a flat row:
a flat row reads as a claim of total uncertainty, `null` says nothing was placed. This is the one
divergence golden layer A allows, and it asserts the draft's row is flat exactly there.

**C-10 Phases.** The engine page asks for each cycle's current phase; the draft names none (its
`phases.py` Foundation/Saturation taxonomy classifies saturation, not cycles). Four phases are
read off the phase angle in the cycle's own variable, in the draft's convention (0 peak, plus or
minus pi trough): `recovery` [-pi, -pi/2), `expansion` [-pi/2, 0), `slowdown` [0, pi/2),
`contraction` [pi/2, pi). Each year gets exactly one, or none if the cycle has no position there.

**C-11 Phase order is checked, not enforced.** A phase moves forward through the order; the pulse,
at 3.6 years against annual data, can skip one. The Hilbert phase of a band-passed series can step
backwards where the component's amplitude is small. Those years are listed in `order_breaks` per
track and counted in the run's warnings (13 on the production snapshot, all in estimated cycles);
the phase is not altered to hide them. Anchored cycles never step backwards (tested).

**C-12 Economies, not a peer set.** Each economy's cycles are its own (the innovation cycle is the
same everywhere by construction), so the default list in `config.yaml` changes nothing but what
is computed. A run takes the whole window of complete years in the snapshot (2006 to 2025).

**C-13 Identity.** `idempotency_key = IDK-hash(snapshot_id, economies, calibration content hash,
engine_version, contract_versions)`; `artefact_id = CYS-hash(payload)`. A repeated request is
answered with the run that made the artefact (`cached: true`).

**C-14 The capital projection stays off (calibration 1.0.0).** The draft's `assume_capital_crossing` (solve the recent
saturation trend for when it would reach 3.5, marked assumed) is ported and off by default, as in
the draft's timeline. With it off, capital is unanchored in 11 of 16 economies on the production
snapshot, including **JP**, whose saturation is above 3.5 for the whole window: there is no upward
crossing inside 2006 to 2025 to date it from. That is the draft's rule applied faithfully, and
worth a model decision (a longer saturation history, or a stated JP anchor).

**C-16 Historical resets and the 130-year capital cycle (calibration 1.1.0, active).** Decided
by the author on 2026-09-27. The saturation crossing dated only 5 of 16 economies, and those
dates matched no event. In 1.1.0 every economy's capital cycle starts at a **historical reset**,
year 0 of the cycle (`CycleSpec.resets`, `calibration.RESETS`): US 1933, TH 1932, CH 1936,
ES 1939, EU, GB and JP 1945, PH 1946, IN 1947, CN and DE 1948, MY 1963, BR 1964, ID 1966,
BD 1971, VN 1986. CN was given; the rest were read off history and chosen one by one. The shape
changes too (`shape: rise_fall`): the reset is the **low**, the cycle rises for 90 years to its
peak (the reordering), then falls for 40 years to the next reset at **130 years**, the hegemonic
period. The draft's cosine peaked at the reordering *and* at year 0, with its low at year 45, which
put an economy 39 years after its reset in "contraction". Under `rise_fall` the phases are recovery
(years 0 to 45), expansion (45 to 90), slowdown (90 to 110) and contraction (110 to 130), and only
move forward. An economy without a reset falls back to the saturation crossing, dated as the peak
of the same shape. Resets are supplied, so the confidence class is `supplied`. 1.0.0 is kept
unchanged as the draft's reconciliation. 1.1.0 and the calibration contract `1.1.0` were created
and reshaped on the same day, in the dev schema only; the schema was rebuilt, and nothing had
consumed it.

**C-17 The credit cycle is anchored on crises (calibration 1.1.0).** Decided by the author on
2026-09-27. Twenty years of data cannot identify an 18-year cycle (C-07), so in 1.1.0 credit is an
`anchored_trough` with an 18-year period and a low per economy (`CycleSpec.anchor_years`,
`calibration.CREDIT_LOWS`): 2009 for US, GB, DE, CH and EU (the Global Financial Crisis), ES 2012
(banking crisis), 1998 for TH, MY, ID, PH and JP (Asian and Japanese banking crises), CN 2015,
IN 2013, BR 2016, VN 2012, BD 2011. Proposed from history and chosen by the author. The low is
phase pi, so the cycle peaks 9 years later; it enters the superposition and the synchrony windows.
An economy with no anchor year has no position. The alternative, long BIS credit-to-GDP history in
datafeed so that credit can be band-passed from credit, is not taken for now.

**C-18 The pulse and business cycles read macrofield (calibration 1.1.0).** Decided by the
author on 2026-09-27. In the draft the cycles came from macrofield's own economy path. In 1.1.0
the pulse and business cycles are band-passed from `np.gradient(log Y)` of macrofield's observed
output Y, **in current US dollars and not deflated, exactly as the draft read it** (the author's
choice over deflating by US CPI or splicing onto datafeed); inflation and exchange-rate swings are
therefore part of what they measure. `POST /run` takes `macrofield_artefact_id`; omitted, the
engine uses macrofield's latest successful run. The artefact id enters the idempotency key, and
provenance records it with macrofield's snapshot, calibration and a sha256 of the part read.
`contracts.UpstreamMacroState` mirrors only the fields read and ignores the rest, so the engine
does not break when macrofield's contract grows. The year axis extends back to macrofield's first
year (1972 on today's state); macrofield ends in 2024, so these two cycles' current phase is 2024
(VN 2022, IN 2018) and `/cycles/{id}/current` says so per cycle. The gain: 53 years for US and GB,
45 for DE, against 20 in datafeed. Calibration 1.0.0 reads no macrofield input and needs none.
macrofield still runs on its own static snapshot, not datafeed, so its data can differ from
datafeed's; the tests serve a frozen state (`golden/macrofield_*.json`) through a mock transport.

**C-19 Trailing span, else the longest (all calibrations).** Decided by the author on 2026-09-27.
macrofield drops years for some economies (IN 2019 to 2021, DE 1991 to 1998). An estimated cycle
uses the trailing gap-free span of its input (C-05); where that span is too short to identify the
cycle, it falls back to the longest gap-free span, and the track's notes say so. Only IN changes
today: its pulse and business cycles run 1981 to 2018 and carry no phase after 2018.
`coverage.input_gaps` now lists the years no cycle reading an input has a phase in.

**C-20 The capital peak reads as aggressive (calibration 1.2.0, active).** Decided by the
author on 2026-09-28. The draft oriented the capital cycle at -1 (peak saturation at the cautious
end of the 25-bin axis, `cycle_bins.py`, 2026-08-02). 1.2.0 inverts that to +1, like every other
cycle: an economy near the peak of its capital cycle (year 90 after its reset) now sits at the
aggressive end. The shape, the resets and the other cycles are unchanged, so phases and levels
are identical to 1.1.0; only the capital kernel is mirrored on the axis (bin b becomes 26 - b).
On the production snapshot the cycle layer's mean bin rises by about 5 bins in most economies
(US 5.3 to 10.6, CN 10.5 to 16.0). A new version rather than a change to 1.1.0, since the
cockpit had already stored and shown 1.1.0 runs.

**C-21 The capital shape is inverted (calibration 1.3.0, active).** Decided by the author on
2026-09-28, because 1.2.0 was hard to read. 1.3.0 keeps 1.2.0's orientation (+1) and inverts the
shape (`shape: fall_rise`): the capital cycle peaks at the reset, falls for 90 years to its low at
saturation, and rises for 40 years to the next reset at 130. Every cycle now follows one rule, a
high level reads as aggressive, and a saturated economy sits at the cautious end of the 25-bin axis
again: the layer equals 1.1.0's, while the capital curve and its phases are mirrored (US, 92 years
in, is just past its low: recovery). 1.1.0 and 1.2.0 stay stored.

**C-22 The anchored cycles are projected to macrofield's horizon.** Decided by the author on
2026-09-28. A run projects as far ahead as macrofield projects (its `projection.years`, 2039 on
today's state; request `project`, default `run.project: true` in config.yaml). Only the anchored
cycles (innovation, credit, capital) have a position in projected years: they are defined for any
date. The band-passed ones (pulse, business) stop at their data, as the draft's forward view did
("a band-passed component cannot be extrapolated at all"). The layer continues on the anchored
cycles; the superposition does not (it needs every member). `CycleState` gains `observed_until`
and `projected_until` (contract `cycle-state@1.1.0`); `/cycles/{id}/current` reads the last
observed year, never a projected one. The horizon enters the idempotency key and provenance
(`macrofield:projection_horizon`). The cycle schema was rebuilt for the new contract (test runs only).

**C-23 Production snapshot `bloomberg-2026-01-05`.** 2026-09-28: datafeed's newest snapshot
(`matlab-m_ts-2026-01-05.r3.public-21886dde.market-690ff362`) was written as one self-contained
snapshot under this id, with identical panel and coverage. It carries every series of the old
production snapshot `...public-8e90be47` with identical values, so cycle's output is unchanged; the
golden input stays the frozen `...public-8e90be47` panel. The eight older snapshots were deleted the
same day on the owner's instruction, after a backup of the datafeed schema.

**C-24 The model explains itself: `GET /model` (owner, 2026-09-28).** The owner wants every engine
shown in one style: what comes in (plain names), what it looks like, what gets calculated (the
functions with their maths, and charts) and what goes out. `GET /model?economy=` returns a
`model-card@1.0.0`: the inputs with their data, every step of the pipeline with its formula
(LaTeX), its parameters (read from the active calibration) and the numbers it produced, and the
outputs. It runs the engine's own functions (`model_card.py` calls `engine.py`) for one economy
on datafeed's current snapshot and macrofield's latest run, so every chart is a figure the model
computed; a test checks the card's cycle levels and mean state against a normal run, cell for
cell. The card shape is the same in every engine (each keeps its own copy of the contract), so
the cockpit draws all of them with one page. The card is a view, not a result: it is not in `CONTRACT_VERSIONS`, which
feeds every idempotency key and artefact id, so it never changes a published id. One axis per chart, and each cycle keeps its colour
in every chart (`slot`), as the house chart rules require.

**C-25 The aggregate continues over the anchored cycles (review R-004, 2026-09-28).** The review
asked for the combined reading as a thick line over the five cycles, continued into the projection
over the anchored cycles only. `superposition` needs every interference member, so it stops where
pulse and business stop (2024 on today's state; IN 2018, VN 2022). Rather than compute a
re-normalised sum in the browser, `EconomyCycles` gains `superposition_anchored` and
`anchored_members` (contract `cycle-state@1.2.0`), computed in `engine.anchored_superposition`
(pure): the weighted mean of the anchored interference members' components (today credit,
innovation and capital), sum_k w_k c_k / sum_k w_k, on the span they all cover, which is the whole
axis including the projection. The weights are each member's `superposition_weight` re-normalised
to the anchored members' sum (1/3 each with today's equal weights); the notes state them. An
anchored component is cos(phase), unit amplitude by construction, so it enters **unscaled**:
`superpose` divides each component by its maximum over the span (the draft's rule, kept for
`superposition`), which for an anchored cycle would make the figures move with the projection
horizon (up to 0.016 on today's data between 2039 and 2080; tested not to). The field is published
over every year, not only the projected ones; where both exist, `superposition` is the aggregate
and this one leaves pulse and business out, so the two differ at the data edge (US 2024: -0.49 with
all five, 2025: -0.78 anchored only). Alignment and the synchrony windows are not continued: they
measure the agreement of the full set. The test bench draws `superposition` solid and
`superposition_anchored` dashed from the year after the full aggregate ends, both unaltered, with
`alignment` in a panel below and the synchrony windows shaded. A new contract version because a
field was added; every run key changes with the contract, so `POST /run` makes new artefacts.
Stored 1.1.0 artefacts stay readable as they were published (C-26).

**C-26 A stored artefact is served as it was published (2026-09-28).** The C-25 bump first made
stored `cycle-state@1.1.0` artefacts fail to validate on read. They are not only test runs: the
Default Regime `RGM-e2658e8e9bbbc81e`, which pcp runs on, was built from `CYS-ae1207d818257915`, and
its lineage must stay readable through `GET /artefacts/{id}`. `contracts.py` now has one read model
per published version, sharing their fields: `CycleStateV110` / `EconomyCyclesV110` (1.1.0, exactly
the fields 1.1.0 published) and `CycleState` / `EconomyCycles` (1.2.0, 1.1.0's fields plus
`superposition_anchored` and `anchored_members`, in the same order). `Service.artefact` reads the
stored `contract_version` and validates the payload with that version's model
(`STORED_CYCLE_STATES`); an unknown version is an error, never a silent upgrade. The endpoint's
response model is the union discriminated on `contract_version`, so a 1.1.0 artefact comes back as
1.1.0, without the new fields, and byte for byte the stored JSON; `/cycles/{id}` and
`/cycles/{id}/current` read either. New runs publish 1.2.0 only. The regression test stores a real
1.1.0 artefact of the `cycle` schema (`golden/cycle_state_1.1.0_CYS-c6a5185ec9c743a0.json`, trimmed
to US and CN) and reads it back unchanged; with the fix reverted, it fails. The two artefacts in
the real `cycle` schema on 28.09.2026 (`CYS-c6a5185ec9c743a0`, `CYS-ae1207d818257915`, both 1.1.0)
read back identical to their stored payload. A later contract bump adds one model to
`STORED_CYCLE_STATES` rather than replacing the last.

**C-27 Health probes stay out of the access log** (03.10.2026, `deploy/ENGINE_CHANGES.md` item 10). `access_log.py` puts a filter on uvicorn's `uvicorn.access` logger, installed at the top of `create_app` (uvicorn configures its loggers before it calls the factory). It drops a `GET /health` line that answered below 400, matched on the path without the query string; every other request is still logged, and so is a health call that answered 400 or more. No new dependency; `tests/test_access_log.py`. The engine version stays `cycle@1.0.0`: it enters every idempotency key (`Service.idempotency_key`), so a bump would give a rerun of unchanged inputs new ids for a change that alters no figure. The container's health check calls 14 routes every 30 seconds, about 40,000 health lines a day between the lines that matter. A failing probe is the line worth reading, so it stays.

**C-15 What is not ported.** The draft's `years_into_capital_cycle` restart (needs the saturation
phase classifier), `spectrum` (a chart helper), the regime tilts that read the cycles
(`capital_overdue`, `innovation_to_trough`: they belong to `aggregation`) and the blend of the
layer into the SAA/TAA merge at `blend_weight` 0.20 (also `aggregation`: this engine publishes the
layer, the aggregation layer decides its weight).
