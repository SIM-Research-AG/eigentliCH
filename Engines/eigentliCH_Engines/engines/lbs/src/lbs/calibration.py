"""Calibration: the prototype's content records, the mandate policy figures and which prototype quirks are
corrected, nothing else.

Six seeds, append-only, each a child of the one before:

``1.0.0``  the prototype reproduced, records as shipped (ahv-pension and risk-profile unapproved).
``1.1.0``  the owner's approval of ahv-pension and risk-profile (Nicolas, 29.09.2026, LBS-23): the same
           records with only their ``_about`` completed, the prototype's behaviour otherwise. The golden
           reference's "approved" variant runs under it.
``1.2.0``  1.1.0 with the four LBS-17 quirks corrected (owner, 29.09.2026, LBS-24).
``1.3.0``  1.2.0 with three more corrections (owner, 29.09.2026, LBS-28): a human-capital stock is never free
           wealth, a stated mortgage of 0 is a paid-off mortgage, and the yearly saving is split between the
           goals by their stated shares.
``1.4.0``  1.3.0 with the nominal and real view (owner's decisions of 29.09.2026, LBS-31 to LBS-35): a goal
           amount is in today's francs unless stated otherwise and is inflated to its date at the calibrated
           long-run inflation of the currency; an indexed contribution rises with it; the required return is
           judged against a plausibility ceiling by risk level.
``1.5.0``  1.4.0 with the owner's decisions on its two assumptions (Nicolas, 29.09.2026, LBS-36, LBS-37): the
           CHF long-run inflation is 1.0 %, the midpoint of the SNB's 0 to 2 % price-stability range
           (forward-looking), in place of the measured 0.50 %; EUR and USD stay measured; the plausibility
           table is approved unchanged. **Active.**

The hashes of 1.0.0 to 1.5.0 are pinned (``tests/test_api.py``): each is stored and a changed hash
stops the service at startup.

``1.0.0``
    The nine records of ``Projects/eigentliCH/Prototype/client/content/`` as of 28.09.2026, byte for byte
    (``seed_records/*.json``), each with its own ``_about`` approval metadata, and the eigentliCH draft's
    mandate figures from ``Projects/eigentliCH/engines/lbs/derive.py`` and the S-curve engine
    (``MandatePolicy``). Approval state at seeding:

    ============================  ==========  ===============================================
    record                        approved    read by
    ============================  ==========  ===============================================
    ahv-pension                   no          AHV pension, couple cap, retirement finding
    bvg-projection                yes         BVG projection, retirement finding
    human-capital                 yes         E, N, H, time budget (the prototype reads it ungated)
    property-funding              yes         property findings, the mandate's deposit target
    liquidity-levers              yes         the liquidity finding's lever precedence
    risk-profile                  no          risk profile, role bounds, curve slope, ESG floor
    intake-scales                 no          N's people scale, civil status (read ungated)
    roles                         no          grid display names and definitions (display only)
    currency-horizons             yes         the household composition's validity horizon
    ============================  ==========  ===============================================

A record is approved when ``_about.provisional`` is false and ``_about.published_by`` is set: the prototype's
own gate (``ahv.scale``, ``property.conventions``, ...). Approving a record is the owner's act and is a new
calibration version through ``PUT /calibration`` with the record's ``_about`` completed; a seed is never
changed in place, and the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any

from .contracts import (
    LATER_CORRECTIONS,
    RECORD_NAMES,
    Calibration,
    Corrections,
    InflationAssumption,
    LiquidityRule,
    MandatePolicy,
    PlausibilityRow,
    RealViewPolicy,
)


def _record(name: str) -> dict[str, Any]:
    text = resources.files("lbs").joinpath("seed_records", f"{name}.json").read_text(encoding="utf-8")
    return json.loads(text)


#: derive.py ``_liquidity_floor``: a near deadline forces reachable wealth; beyond fifteen years the goal
#: imposes no liquidity requirement and none is claimed.
LIQUIDITY_RULES = (
    LiquidityRule(horizon_at_most_years=2.0, bounds={"Daily": (0.60, 1.0), "Decade": (0.0, 0.0)}),
    LiquidityRule(horizon_at_most_years=5.0, bounds={"Daily": (0.30, 1.0), "Decade": (0.0, 0.10)}),
    LiquidityRule(horizon_at_most_years=15.0, bounds={"Daily": (0.10, 1.0)}),
)

SEED = Calibration(
    contract_version="lbs-calibration@1.0.0",
    version="1.0.0",
    note=("The eigentliCH prototype's content records of 28.09.2026 verbatim, with their approval metadata "
          "(ahv-pension and risk-profile unapproved), and the draft derive.py mandate figures: the +/-2.5 "
          "point policy ramp, the 50 percent home-currency floor, the deadline liquidity ladder and the "
          "S-curve bisection."),
    records={name: _record(name) for name in RECORD_NAMES},
    policy=MandatePolicy(liquidity_rules=LIQUIDITY_RULES),
)



def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in. An absent ``corrections`` block is left out
    rather than written as null, so a calibration stored before the block existed (the seed 1.0.0) keeps its
    bytes and its hash; likewise an unnamed later correction (LBS-28), so 1.2.0 keeps its own, and an absent
    ``real_view`` block (LBS-35), so 1.0.0 to 1.3.0 keep theirs."""
    payload = calibration.model_dump(mode="json")
    if payload.get("real_view") is None:
        payload.pop("real_view", None)
    if payload.get("corrections") is None:
        payload.pop("corrections", None)
    else:
        for name in LATER_CORRECTIONS:
            if payload["corrections"].get(name) is None:
                payload["corrections"].pop(name, None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]


def with_approved(calibration: Calibration, *names: str, version: str, published_by: str,
                  decided_on: str, approval: str | None = None, note: str | None = None) -> Calibration:
    """A new calibration with the named records approved: only each record's ``_about`` changes (not
    provisional, the publisher, the decision and effective date, and ``_approval`` when given); the record's
    content is untouched. For the seeds, for tests and for preparing a ``PUT /calibration`` body; it never
    touches a stored version."""
    records = json.loads(json.dumps(calibration.records))
    for name in names:
        about = {"provisional": False, "published_by": published_by, "decided_on": decided_on,
                 "effective_from": decided_on}
        if approval is not None:
            about["_approval"] = approval
        records[name]["_about"].update(about)
    contract = (calibration.contract_version
                if calibration.contract_version in ("lbs-calibration@1.2.0", "lbs-calibration@1.3.0")
                else "lbs-calibration@1.1.0")
    return Calibration.model_validate({**calibration.model_dump(), "contract_version": contract,
                                       "version": version, "parent_version": calibration.version,
                                       "records": records,
                                       "note": note or f"{calibration.version} with {', '.join(names)} approved"})


#: The owner's approval of 29.09.2026 (LBS-23). Content unchanged; ``_about`` completed.
APPROVED = with_approved(
    SEED, "ahv-pension", "risk-profile", version="1.1.0", published_by="Nicolas", decided_on="2026-09-29",
    approval="Approved by Nicolas, 29.09.2026 (owner's decision, lbs calibration 1.1.0, LBS-23).",
    note=("1.0.0 with ahv-pension and risk-profile approved by Nicolas on 29.09.2026 (LBS-23): the records' "
          "content unchanged, only their _about completed; the prototype's behaviour otherwise, so the golden "
          "reference's approved variant reproduces under it."))

#: The owner's correction of the four LBS-17 quirks, 29.09.2026 (LBS-24). Its payload names only those four
#: (``lbs-calibration@1.1.0``, as stored on 29.09.2026).
CORRECTED = Calibration.model_validate({
    **APPROVED.model_dump(), "version": "1.2.0", "parent_version": APPROVED.version,
    "note": ("1.1.0 with the four prototype quirks of LBS-17 corrected (owner, 29.09.2026, LBS-24): the "
             "required-return search reaches its stated 1000 percent ceiling; without a dated goal the capacity "
             "horizon is the years to the planned age, not the age; a stated zero income is zero; a funding "
             "stock without a vessel is a named gap, neither hard equity nor free wealth."),
    "corrections": Corrections(required_return_search_reaches_its_ceiling=True,
                               capacity_horizon_is_years_to_the_planned_age=True,
                               zero_income_is_a_stated_zero=True,
                               unstated_vessel_is_a_gap=True).model_dump()})

#: The owner's three further corrections, 29.09.2026 (LBS-28). The active calibration.
CORRECTED_1_3 = Calibration.model_validate({
    **CORRECTED.model_dump(), "contract_version": "lbs-calibration@1.2.0", "version": "1.3.0",
    "parent_version": CORRECTED.version,
    "note": ("1.2.0 with three further corrections (owner, 29.09.2026, LBS-28): a human-capital stock in chf is "
             "human capital only, never free wealth or equity; a stated mortgage of 0 is a paid-off mortgage, not "
             "an unknown one; the yearly saving is split between the goals by their stated contribution_share, "
             "and the designated goal's missing share, with other goals in the request, is a gap."),
    "corrections": Corrections(required_return_search_reaches_its_ceiling=True,
                               capacity_horizon_is_years_to_the_planned_age=True,
                               zero_income_is_a_stated_zero=True,
                               unstated_vessel_is_a_gap=True,
                               human_capital_is_never_free_wealth=True,
                               zero_mortgage_is_a_stated_zero=True,
                               contribution_is_split_by_goal_share=True).model_dump()})

#: The calibrated long-run inflation per currency (LBS-32): the mean log inflation of the datafeed's monthly
#: year-on-year CPI series in snapshot ``bloomberg-2026-01-05`` (checksum 2b4bc756...), read once at build time
#: on 29.09.2026 through ``GET /panel`` of datafeed (8001), as a simple rate ``exp(mean ln(1 + yoy)) - 1``,
#: rounded to 0.01 point. lbs reads no engine at run time.
INFLATION = {
    "CHF": InflationAssumption(
        annual_rate=0.0050, index="Swiss CPI (LIK), datafeed inflation.cpi_yoy CH (SZCPIYOY Index)",
        source=("mean log inflation of the monthly year-on-year series, 238 months from 2006-01 to 2025-10 (the "
                "last three months are a named datafeed gap): 0.4997 % a year, rounded to 0.50 %; datafeed "
                "snapshot bloomberg-2026-01-05, read 29.09.2026"),
        cross_check=("SNB: price stability is CPI inflation below 2 % a year (a range of 0 to 2 %); the measured "
                     "mean sits in its lower half")),
    "EUR": InflationAssumption(
        annual_rate=0.0211, index="euro-area HICP, datafeed inflation.cpi_yoy EU (EHPIEU Index)",
        source=("mean log inflation of the monthly year-on-year series, 241 months from 2006-01 to 2026-01: "
                "2.1114 % a year, rounded to 2.11 %; datafeed snapshot bloomberg-2026-01-05, read 29.09.2026"),
        cross_check="ECB: 2 % HICP inflation over the medium term"),
    "USD": InflationAssumption(
        annual_rate=0.0254, index="US CPI-U, datafeed inflation.cpi_yoy US (CPI YOY Index)",
        source=("mean log inflation of the monthly year-on-year series, 241 months from 2006-01 to 2026-01: "
                "2.5390 % a year, rounded to 2.54 %; datafeed snapshot bloomberg-2026-01-05, read 29.09.2026"),
        cross_check=("Fed: 2 % a year measured by the PCE price index, which has run below CPI-U; the measured "
                     "CPI-U mean is above the target by about that wedge")),
}

#: The plausibility ceiling of a required return by risk level (LBS-34), real, simple, a year. A house
#: assumption proposed by this build on 29.09.2026 for the owner to confirm, not a measured figure.
PLAUSIBILITY = (
    PlausibilityRow(risk_level=0.0, real_return=0.020),
    PlausibilityRow(risk_level=0.5, real_return=0.035),
    PlausibilityRow(risk_level=1.0, real_return=0.050),
)
PLAUSIBILITY_SOURCE = (
    "house assumption proposed on 29.09.2026 for the owner to confirm (LBS-34): the most a portfolio at the "
    "risk profile's level can reasonably be planned to earn over the long run, real, a year; 2 % at the cautious "
    "end (about the long-run real return of Swiss government bonds), 5 % at the aggressive end (about the "
    "long-run real return of Swiss equities), linear in between; a plan that needs more than the long-run "
    "return of the asset class it may hold rests on luck")

#: The owner's decisions on the nominal and real view, 29.09.2026 (LBS-31 to LBS-35).
CORRECTED_1_4 = Calibration.model_validate({
    **CORRECTED_1_3.model_dump(), "contract_version": "lbs-calibration@1.3.0", "version": "1.4.0",
    "parent_version": CORRECTED_1_3.version,
    "note": ("1.3.0 with the nominal and real view (owner's decisions of 29.09.2026, LBS-31 to LBS-35): a goal "
             "amount is in today's francs unless the request says future francs (decision 7) and is inflated to "
             "its target date at the currency's calibrated long-run inflation; a contribution the request states "
             "as indexed rises with it, else it is fixed in francs (decision 9); the sheet carries the goal "
             "figures and the required return in both bases; the retirement comparison is made in today's "
             "francs; and the required return is judged against a plausibility ceiling by risk level."),
    "real_view": RealViewPolicy(inflation=INFLATION, plausibility=PLAUSIBILITY,
                                plausibility_source=PLAUSIBILITY_SOURCE).model_dump()})

#: The owner's CHF inflation assumption, 29.09.2026 (LBS-36): forward-looking, not measured. EUR and USD keep
#: their measured figures of 1.4.0, source for source.
INFLATION_1_5 = {
    **INFLATION,
    "CHF": InflationAssumption(
        annual_rate=0.0100, index="Swiss CPI (LIK), datafeed inflation.cpi_yoy CH (SZCPIYOY Index)",
        source=("owner's decision (Nicolas, 29.09.2026, LBS-36): 1.0 % a year, the midpoint of the SNB's "
                "price-stability range of 0 to 2 % CPI inflation, a forward-looking assumption; it replaces the "
                "measured mean of 1.4.0 (0.4997 % a year, 238 months from 2006-01 to 2025-10, datafeed snapshot "
                "bloomberg-2026-01-05), which reflects the low-inflation regime of 2006 to 2026"),
        cross_check=("SNB: price stability is CPI inflation below 2 % a year (a range of 0 to 2 %); the "
                     "assumption is its midpoint, twice the measured 2006 to 2026 mean")),
}

#: The plausibility table of 1.4.0, confirmed by the owner (Nicolas, 29.09.2026, LBS-37): no value changes.
PLAUSIBILITY_SOURCE_1_5 = (
    "approved by the owner (Nicolas, 29.09.2026, LBS-37), the table unchanged from its proposal in 1.4.0 "
    "(LBS-34): the most a portfolio at the risk profile's level can reasonably be planned to earn over the long "
    "run, real, a year; 2 % at the cautious end (about the long-run real return of Swiss government bonds), 5 % "
    "at the aggressive end (about the long-run real return of Swiss equities), linear in between; a plan that "
    "needs more than the long-run return of the asset class it may hold rests on luck")

#: The owner's decisions on the two assumptions of 1.4.0, 29.09.2026 (LBS-36 to LBS-38). The active calibration.
CORRECTED_1_5 = Calibration.model_validate({
    **CORRECTED_1_4.model_dump(), "contract_version": "lbs-calibration@1.3.0", "version": "1.5.0",
    "parent_version": CORRECTED_1_4.version,
    "note": ("1.4.0 with the owner's decisions on its two assumptions (Nicolas, 29.09.2026, LBS-36, LBS-37): the "
             "CHF long-run inflation is 1.0 % a year, the midpoint of the SNB's 0 to 2 % price-stability range "
             "(forward-looking), in place of the measured 0.50 %; EUR 2.11 % and USD 2.54 % stay measured; the "
             "plausibility table (2 %, 3.5 % and 5 % real at risk levels 0, 0.5 and 1) is approved unchanged."),
    "real_view": RealViewPolicy(inflation=INFLATION_1_5, plausibility=PLAUSIBILITY,
                                plausibility_source=PLAUSIBILITY_SOURCE_1_5).model_dump()})

SEEDS: tuple[Calibration, ...] = (SEED, APPROVED, CORRECTED, CORRECTED_1_3, CORRECTED_1_4, CORRECTED_1_5)
