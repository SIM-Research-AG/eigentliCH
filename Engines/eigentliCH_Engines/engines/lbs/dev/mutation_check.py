"""Revert each guarded rule once and confirm its regression test turns red (Engine Building Guide: "each
regression test verified by reverting").

    ..\\..\\.venv\\Scripts\\python dev/mutation_check.py

Each mutation is a literal replacement in one source file, applied, tested and restored in a ``finally``, so
the tree is left byte for byte as it was found even when a run is interrupted by an exception. A mutation whose text is not
found fails the check: the rule moved and the mutation must move with it.

Twenty rules up to lbs@1.1.0 (LBS-22) and nine for the owner's decisions of LBS-28 to LBS-30 (lbs@1.2.0).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lbs"

#: (name, file, original text, mutated text, tests that must fail)
MUTATIONS = (
    ("approval gate", "engine.py",
     'return (not about.get("provisional", True)) and bool(about.get("published_by"))', "return True",
     ["tests/test_engine.py::test_an_unapproved_record_is_a_reason_and_never_a_number",
      "tests/test_golden.py::test_the_refusals_are_golden_too"]),
    ("no silent zero for liabilities", "engine.py",
     "        liabilities = None\n        ctx.gap(\"totals\", \"liabilities\"",
     "        liabilities = 0.0\n        ctx.gap(\"totals\", \"liabilities\"",
     ["tests/test_engine.py::test_no_liability_stated_leaves_net_worth_open_rather_than_zero"]),
    ("growth read as gain", "contracts.py",
     'ROLE_SYNONYMS: dict[str, str] = {"growth": "gain"}', "ROLE_SYNONYMS: dict[str, str] = {}",
     ["tests/test_engine.py::test_growth_is_read_as_gain_at_the_boundary"]),
    ("a stock is never matched by prefix", "engine.py",
     "amounts = [p.magnitude for p in stated if p.magnitude is not None and p.unit in STOCK_UNITS]",
     'amounts = [p.magnitude for p in stated if p.magnitude is not None and (p.unit or "").startswith("chf")]',
     ["tests/test_engine.py::test_a_flow_never_counts_as_an_illiquid_balance"]),
    ("no debt contradicts a debt", "contracts.py",
     'if self.facts.has_no_liabilities and any(p.stock_kind == "liability" for p in self.positions):',
     "if False:",
     ["tests/test_engine.py::test_stating_no_debt_and_a_debt_is_a_contradiction"]),
    ("derived dimensions only", "contracts.py",
     'if PCP_BOUND_SOURCE.get(dimension) != "derived":', "if False:",
     ["tests/test_engine.py::test_only_derived_dimensions_are_proposed_and_policy_is_left_to_the_curator"]),
    ("idempotent re-run", "service.py",
     "done = st.succeeded_run_for_key(conn, key)", "done = None",
     ["tests/test_api.py::test_rerunning_is_free_and_gives_the_same_artefact"]),
    ("every adult's income", "engine.py",
     "        if uncovered:\n", "        if False:\n",
     ["tests/test_engine.py::test_two_adults_need_both_incomes_for_a_household_income"]),
    ("no link is not a zero", "engine.py",
     "    if not funding:\n        return None, 0, 0", "    if not funding:\n        return 0.0, 0, 0",
     ["tests/test_engine.py::test_unlinked_funding_is_undetermined_and_not_a_shortfall"]),
    ("valid on the day it expires", "engine.py",
     "expired = ctx.req.as_of > expires", "expired = ctx.req.as_of >= expires",
     ["tests/test_engine.py::test_a_composition_is_valid_on_the_day_it_expires"]),
    ("the bands start where article 16 says", "engine.py",
     'if band["from_age"] <= age <= band["to_age"]:', 'if band["from_age"] < age <= band["to_age"]:',
     ["tests/test_engine.py::test_the_credit_rate_steps_where_article_16_says"]),
    ("the principal's age", "engine.py",
     "    if h.principal is not None:\n        return by_id[h.principal]\n", "",
     ["tests/test_golden.py::test_reproduces_the_prototype"]),
    # -- the owner's decisions of 29.09.2026 (LBS-23 to LBS-25)
    ("both records approved in 1.1.0", "calibration.py",
     'SEED, "ahv-pension", "risk-profile", version="1.1.0"', 'SEED, "ahv-pension", version="1.1.0"',
     ["tests/test_engine.py::test_the_approval_changes_only_the_about_block",
      "tests/test_golden.py::test_reproduces_the_prototype"]),
    ("the corrected calibration is the default", "../../config.yaml",
     'active: "1.3.0"', 'active: "1.2.0"',
     ["tests/test_api.py::test_standard_endpoints"]),
    ("the seed keeps its stored bytes", "calibration.py",
     '    if payload.get("corrections") is None:\n        payload.pop("corrections", None)\n', "",
     ["tests/test_api.py::test_the_seed_keeps_its_stored_hash"]),
    ("the search reaches its stated ceiling", "engine.py",
     "    if reach_the_ceiling:\n", "    if False:\n",
     ["tests/test_engine.py::test_the_search_reaches_its_stated_ceiling",
      "tests/test_golden_corrected.py::test_the_corrected_sheet_matches_its_frozen_form"]),
    ("the horizon is years to the planned age", "engine.py",
     'if horizon is None and ctx.corrects("capacity_horizon_is_years_to_the_planned_age"):', "if False:",
     ["tests/test_engine.py::test_the_capacity_horizon_is_years_to_the_planned_age",
      "tests/test_golden_corrected.py::test_the_corrected_sheet_matches_its_frozen_form"]),
    ("a stated zero income is zero", "engine.py",
     '    if ctx.corrects("zero_income_is_a_stated_zero"):\n        if owned:', "    if False:\n        if owned:",
     ["tests/test_engine.py::test_a_stated_zero_income_is_zero",
      "tests/test_golden_corrected.py::test_the_corrected_sheet_matches_its_frozen_form"]),
    ("a stock without a vessel is not equity", "engine.py",
     "            if p.vessel is None and corrected:", "            if False:",
     ["tests/test_engine.py::test_a_stock_without_a_vessel_is_a_gap_and_not_equity",
      "tests/test_golden_corrected.py::test_the_corrected_sheet_matches_its_frozen_form"]),
    ("no silent zero for the contribution", "engine.py",
     "    saving = m.annual_contribution\n", "    saving = m.annual_contribution or 0.0\n",
     ["tests/test_engine.py::test_the_yearly_contribution_sets_the_required_return_and_the_curve"]),
    # -- the owner's decisions of 29.09.2026, second round (LBS-28 to LBS-30), calibration 1.3.0
    ("a human-capital stock is not free wealth", "engine.py",
     '            if p.capital_type == "human" and human_is_human:\n                # Human capital only',
     "            if False:\n                # Human capital only",
     ["tests/test_engine.py::test_a_human_capital_stock_is_never_free_wealth",
      "tests/test_golden_corrected.py::test_the_13_sheet_matches_its_frozen_form"]),
    ("a human-capital stock is not equity", "engine.py",
     '        if p.capital_type == "human" and human_is_human:\n            ctx.gap(f"property',
     '        if False:\n            ctx.gap(f"property',
     ["tests/test_engine.py::test_a_human_capital_stock_is_never_free_wealth",
      "tests/test_golden_corrected.py::test_the_13_sheet_matches_its_frozen_form"]),
    ("a stated mortgage of 0 is paid off", "engine.py",
     "        if r.mortgage is not None:\n", "        if r.mortgage:\n",
     ["tests/test_engine.py::test_a_stated_mortgage_of_zero_is_paid_off",
      "tests/test_golden_corrected.py::test_the_13_sheet_matches_its_frozen_form"]),
    ("the saving is split by the stated share", "engine.py",
     "        amount = saving * share\n", "        amount = saving\n",
     ["tests/test_engine.py::test_the_saving_is_split_by_the_stated_shares",
      "tests/test_golden_corrected.py::test_the_13_sheet_matches_its_frozen_form"]),
    ("a missing share is a gap, not all of the saving", "engine.py",
     "    if not split or (goal.contribution_share is None and not others):",
     "    if not split or goal.contribution_share is None:",
     ["tests/test_engine.py::test_a_missing_share_is_a_gap_and_the_required_return_a_lower_bound",
      "tests/test_golden_corrected.py::test_the_13_sheet_matches_its_frozen_form"]),
    ("the calibrations before 1.3.0 do not split", "engine.py",
     '    split = ctx.corrects("contribution_is_split_by_goal_share")', "    split = True",
     ["tests/test_engine.py::test_the_saving_is_split_by_the_stated_shares"]),
    ("the shares sum to at most 1", "contracts.py",
     "        if sum(shares) > 1 + 1e-9:", "        if False:",
     ["tests/test_engine.py::test_the_shares_sum_to_at_most_one"]),
    ("1.2.0 keeps its stored bytes", "calibration.py",
     '            if payload["corrections"].get(name) is None:\n                payload["corrections"].pop(name, None)\n',
     "            pass\n",
     ["tests/test_api.py::test_the_stored_calibrations_keep_their_hashes"]),
    ("a request without the new field hashes as before", "service.py",
     '        if goal.get("contribution_share") is None:\n            goal.pop("contribution_share", None)\n',
     "        pass\n",
     ["tests/test_api.py::test_a_request_without_the_new_field_hashes_as_before"]),
)


def main() -> int:
    python = sys.executable
    failures = []
    for name, file, original, mutated, tests in MUTATIONS:
        path = SRC / file
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        if text.count(original) != 1:
            failures.append(f"{name}: the original text occurs {text.count(original)} times in {file}")
            continue
        try:
            path.write_bytes(text.replace(original, mutated).encode("utf-8"))
            result = subprocess.run([python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
                                    cwd=ROOT, capture_output=True, text=True)
        finally:
            path.write_bytes(raw)
        red = result.returncode != 0
        print(f"{'red  ' if red else 'GREEN'}  {name}")
        if not red:
            failures.append(f"{name}: the tests stayed green with the rule reverted")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"\nall {len(MUTATIONS)} reverted rules turned their tests red; sources restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
