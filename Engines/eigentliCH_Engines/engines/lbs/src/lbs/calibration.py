"""Calibration: the prototype's content records, the mandate policy figures and which prototype quirks are
corrected, nothing else.

Four seeds, append-only, each a child of the one before:

``1.0.0``  the prototype reproduced, records as shipped (ahv-pension and risk-profile unapproved).
``1.1.0``  the owner's approval of ahv-pension and risk-profile (Nicolas, 29.09.2026, LBS-23): the same
           records with only their ``_about`` completed, the prototype's behaviour otherwise. The golden
           reference's "approved" variant runs under it.
``1.2.0``  1.1.0 with the four LBS-17 quirks corrected (owner, 29.09.2026, LBS-24).
``1.3.0``  1.2.0 with three more corrections (owner, 29.09.2026, LBS-28): a human-capital stock is never free
           wealth, a stated mortgage of 0 is a paid-off mortgage, and the yearly saving is split between the
           goals by their stated shares. **Active.**

The hashes of 1.0.0, 1.1.0 and 1.2.0 are pinned (``tests/test_api.py``): each is stored and a changed hash
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

from .contracts import LATER_CORRECTIONS, RECORD_NAMES, Calibration, Corrections, LiquidityRule, MandatePolicy


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
    bytes and its hash; likewise an unnamed later correction (LBS-28), so 1.2.0 keeps its own."""
    payload = calibration.model_dump(mode="json")
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
    contract = ("lbs-calibration@1.2.0" if calibration.contract_version == "lbs-calibration@1.2.0"
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

SEEDS: tuple[Calibration, ...] = (SEED, APPROVED, CORRECTED, CORRECTED_1_3)
