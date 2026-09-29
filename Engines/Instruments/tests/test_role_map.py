"""R-001: Income is real estate 75 % and equity 25 % (owner, 29 September 2026, FMRE-15).

The role map enters the calibration's parameter hash, so the choice has its own
calibration id. These tests pin the new id, reproduce the earlier one from the earlier map
(it stays in the live store for comparison), and assert the owner's acceptance for the
choice: Income above Stabilisation in expansion and boom and below it in crisis, with all
eight shape checks and both role checks still passing.
"""

from __future__ import annotations

import pytest

from engines.fund_map import roles
from engines.fund_map.phases import PHASE_NAMES
from tests.conftest import needs_sources

NEW_CALIBRATION = "CAL-69d9d1ee5245ac71"
OLD_CALIBRATION = "CAL-092efd097adb0b26"

CRISIS, EXPANSION, BOOM = 0, PHASE_NAMES.index("expansion"), PHASE_NAMES.index("boom")


def test_income_is_the_owners_choice_and_says_so():
    income = roles.ROLE_BY_NAME["income"]
    assert income.weights == {"real_estate": 0.75, "equity": 0.25}
    assert "R-001" in income.basis and "29.09.2026" in income.basis
    assert "CIO override" in income.basis


def test_the_other_roles_are_unchanged():
    by_name = {r.role: r.weights for r in roles.ROLE_MAP}
    assert by_name["gain"] == {"equity": 1.0}
    assert by_name["stabilisation"] == {"short_rate": 1.0, "commodities": 1.0,
                                        "agriculture": 1.0}
    assert by_name["protection"] == {"gov_bonds": 1.0, "gold": 1.0}
    before = {r.role: r.weights for r in roles.ROLE_MAP_BEFORE_R001}
    assert before == dict(by_name, income={"real_estate": 1.0})


def test_candidate_a_is_the_published_income():
    a = next(c for c in roles.INCOME_CANDIDATES if c.basis.startswith("A "))
    assert a.weights == roles.ROLE_BY_NAME["income"].weights


@needs_sources
class TestTheCalibration:
    @pytest.fixture(scope="class")
    def new(self, long_record):
        from engines.fund_map.service import run_calibration
        return run_calibration(long_record)

    @pytest.fixture(scope="class")
    def old(self, long_record):
        from engines.fund_map.service import run_calibration
        return run_calibration(long_record, role_map=roles.ROLE_MAP_BEFORE_R001)

    def test_the_new_calibration_id(self, new):
        assert new.calibration_id == NEW_CALIBRATION

    def test_the_earlier_calibration_is_reproduced_from_the_earlier_map(self, old):
        assert old.calibration_id == OLD_CALIBRATION

    def test_only_income_moved(self, new, old):
        for role in ("gain", "stabilisation", "protection"):
            assert new.roles[role].profile_by_state == old.roles[role].profile_by_state
        assert new.roles["income"].profile_by_state != old.roles["income"].profile_by_state

    def test_income_against_stabilisation(self, new):
        """The owner's target: above Stabilisation in expansion and boom, below in crisis."""
        income = new.roles["income"].phase_means
        stab = new.roles["stabilisation"].phase_means
        assert income[EXPANSION] > stab[EXPANSION]
        assert income[BOOM] > stab[BOOM]
        assert income[CRISIS] < stab[CRISIS]
        # Clearly, not by the 0.2 to 0.3 points real estate alone managed.
        assert income[EXPANSION] - stab[EXPANSION] > 0.015
        assert income[BOOM] - stab[BOOM] > 0.015

    def test_the_income_phase_values(self, new):
        assert [round(v, 4) for v in new.roles["income"].phase_means] == [
            -0.0321, 0.0325, 0.0303, 0.0519, 0.0545]
        assert [round(v, 4) for v in new.roles["stabilisation"].phase_means] == [
            0.0181, 0.0676, 0.0132, 0.0344, 0.025]

    def test_the_eight_shape_checks_and_both_role_checks_pass(self, new):
        from engines.fund_map.service import shape_checks
        means = {k: [e.mean for e in b.phase_estimates] for k, b in new.blocks.items()}
        checks = shape_checks(means)
        assert len(checks) == 8 and all(ok for _, ok in checks), checks
        assert roles.protection_beats_gain_in_crisis(new.roles)
        assert roles.gain_beats_protection_in_boom(new.roles)
