# Review dossier: engines and test benches

Nicolas's review comments on the engines, their test benches and the cockpit, collected
for Claude Code. One entry per comment. Screenshots sit in `review/img/`.

**For Claude Code:** work through the entries with status `Open` or `Decided`, in index
order. For each entry: read the context, check it against the code (the code is the ground
truth), implement once the decision is taken, and fill in the "Outcome" line. An entry
marked "Decision needed" waits for Nicolas; report back what he has to decide, with the
options side by side. Follow the Engine Build Instruction
(Notion `3e90ba72543f819b9fa1ff13ecf5fb59`) and the Engine Building Guide.

**Status:** `Open` (logged, context checked) · `Decided` (Nicolas has chosen, ready to
build) · `Done` (built, tested, documented) · `Parked`.

## Index

| ID | Engine | Screen | Title | Status | Decision needed |
|---|---|---|---|---|---|
| R-001 | fmre | Instrument selection › Role profiles | Income and stabilisation have nearly the same curve | Open | Income composition |
| R-002 | fmre | Instrument selection › instrument against its role | Instrument profiles are jagged | Open | Switch the default estimator to D2 |
| R-003 | fmre | Instrument selection › Precious Metals against protection | Gold loses in crisis | Open | Via R-002; currency of the gold profile |

---

## R-001 · Income and stabilisation have nearly the same curve

- **Engine / screen:** `fmre` (Projects/Engines/Instruments), test bench "Instrument
  selection", chart "Role profiles". Screenshot: `img/R-001_R-002_instrument_selection.png`.
- **Logged:** 28.09.2026, Nicolas.
- **Observation:** the income and stabilisation curves run almost on top of each other
  across the 25 states.
- **Wish:** a clear difference between the two roles. Income rises higher in a good
  environment and falls further in a bad one; stabilisation stays flatter.
- **Context from the code (28.09.2026):** the role curves are built from the eight
  blocks of the long record, never from the instruments. `ROLE_MAP` in
  `engines/fund_map/roles.py` defines them: income = real estate alone; stabilisation =
  short rate, commodities and agriculture (equal weight). Re-classifying instruments
  therefore moves instruments between roles and leaves the role curves as they are. The
  curves change through the block composition of a role, which `ROLE_MAP` allows as a CIO
  override carrying its reason in `basis`. The 10-year Treasury block appears in no role;
  confirm whether that is intended.
- **Proposed approach:**
  1. Offer two or three candidate compositions for income (for example real estate with
     a share of equity) and show their curves side by side with stabilisation in the test
     bench, together with the eight shape checks for each.
  2. After Nicolas picks one: write it as a CIO override in `ROLE_MAP` with its basis,
     which produces a new calibration id (keep the current one, `CAL-092efd097adb0b26`,
     for comparison).
  3. Then review the instrument role assignments against the new curves
     (`/v1/data/classification`) and list the instruments whose role should change.
- **Decision needed:** the income composition.
- **Acceptance:** income above stabilisation in expansion and boom and below it in
  crisis; all eight shape checks still pass; the new calibration id and the override's
  basis are recorded on the Engine 06 page and in `DECISIONS`.
- **Outcome:**

---

## R-002 · Instrument profiles are jagged

- **Engine / screen:** `fmre`, test bench "Instrument selection", chart
  "<instrument> against its role" (example: APAC Equities against gain). Screenshot:
  `img/R-001_R-002_instrument_selection.png`.
- **Logged:** 28.09.2026, Nicolas.
- **Observation:** across all instruments the 25-state return profile jumps from state
  to state (APAC Equities swings between about -30 % and +35 % within neighbouring states).
- **Wish:** smooth profiles, for example through an interpolation or smoothing function.
- **Context from the code (28.09.2026):** the role curves are already smooth (pchip over
  the five phase estimates). The jumps come from the default instrument estimator
  (`CASCADE`), which estimates each state from a few monthly returns or borrows another
  instrument's profile (APAC Equities borrows from Japan Equities). The alternative, D2
  (`ProfileMethod.SHAPE_SCALED`, HANDOVER §4.1), is built and selectable with
  `INSTRUMENTS_PROFILE_METHOD=shape_scaled`: it takes the shape from the role and the level
  and amplitude from the instrument's own returns. Measured on 42 instruments, the mean
  jump between neighbouring states falls from 9.66 % to 1.44 %, and crisis hedges get the
  right sign (Precious Metals in crisis: -4.81 % under the cascade, +33.05 % under D2).
  Interpolating over the cascade's noisy buckets would give smoother lines with the same
  wrong signs underneath.
- **Proposed approach:**
  1. A toggle in the test bench to show every instrument under the cascade and under D2.
  2. After Nicolas's review of the three caveats in HANDOVER §4.1 (selection bias of the
     level, amplitudes above 1 because `vol_role` is a median over a mixed role,
     instruments that move against their role): switch the default to D2.
  3. Only if D2 still leaves visible jumps: a light smoothing step, labelled with its own
     method so every value still says how it was produced.
- **Decision needed:** switch the default estimator to D2.
- **Acceptance:** mean jump between neighbouring states below 2 % across instruments; no
  protection instrument negative in crisis; every state value carries its method; Engine
  06 page and HANDOVER updated.
- **Link to R-001:** D2 inherits the role shape, so a changed income composition changes
  every income instrument's profile. Decide R-001 before switching R-002's default, or
  switch both together.
- **Outcome:**

---

## R-003 · Gold (Precious Metals) loses in crisis

- **Engine / screen:** `fmre`, test bench "Instrument selection", chart "Precious Metals
  against its role (protection)". Screenshot: `img/R-003_precious_metals.png`.
- **Logged:** 28.09.2026, Nicolas.
- **Observation:** Precious Metals reads about -5 % in every state from crisis to
  stagnation, jumps to +17 % to +27 % in stagnation and expansion, then copies the role
  curve in boom. Profile coverage: `seed`. Gold is clearly wrong here.
- **Wish:** gold performs well in a crisis. Month by month the returns in crisis months
  can look weak, but over a longer holding period through a crisis gold pays; the profile
  has to show that.
- **Context from the code (28.09.2026):** this is the horizon fault found in the
  estimator review (Notion note `3e80ba72543f816e8092e906dc53ed3f`). The role calibration
  measures annual returns in crisis years, and there the gold block peaks in crisis (one of
  the eight shape checks). The default instrument estimator (`CASCADE`) measures monthly
  returns in crisis months: the same crisis months give -12.51 % over the month and
  +11.67 % over the following year. The flat -5 % from crisis to contraction and the copy of
  the role in boom are filled states (open markers), because the recovered monthly returns
  cover only some states. A measurement on an annual horizon with non-overlapping 12-month
  windows was tested and leaves almost every state below the sufficiency floor of six.
  D2 (`SHAPE_SCALED`, see R-002) gives Precious Metals **+33.05 %** in crisis, because it
  takes the shape from the protection role and only level and amplitude from gold's own
  returns.
- **Further point:** the register lists the instrument in CHF, the proxy is GLD (gold in
  USD). Check whether the profile should be in CHF, which changes gold's crisis behaviour
  for a Swiss investor (see the real and currency layer on the Engine 06 page).
- **Proposed approach:**
  1. Resolve with R-002: under D2 gold follows the protection shape (highest in crisis).
  2. Add a diagnostic to the test bench: per instrument, the average return over the
     12 months following each crisis and contraction month, next to its profile, so the
     longer-horizon behaviour you describe is visible and checkable.
  3. Add an acceptance test: every instrument in the protection role is positive in the
     crisis states and above its own boom value.
  4. Settle the currency of the gold profile (CHF or USD).
- **Decision needed:** covered by R-002 (switch to D2); currency of the gold profile.
- **Acceptance:** Precious Metals positive in crisis and highest in the crisis states;
  coverage label no longer `seed`; the 12-month forward diagnostic shown; the new
  protection test passes.
- **Outcome:**
