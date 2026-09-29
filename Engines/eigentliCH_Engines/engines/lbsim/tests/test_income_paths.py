"""DECISIONS P-9 (calibration 1.2.0): the income paths say what their names say.

The defect (B2's live check, 29.09.2026): a principal on 56 000 at a 30-hour week with no stated expectation got a
`today` path of 56 000, 63 058, 71 566, 81 911, 94 604, 110 330 (about twice today's level in five years, from the
draft's autonomous 15 % a year of expertise growth), and `full_pensum` and `network` byte-identical to it (the
draft applies a path's pensum only after an education ends). Under the draft's own interpreter the draft's
`paths.ledger` does the same, so it is the draft's behaviour: 1.0.0 and 1.1.0 keep it, 1.2.0 corrects it.
"""

from __future__ import annotations

import pytest

from conftest import GOLDEN, load_json

from lbsim.calibration import ACTIVE_SEED, SEED, SEED_1_1
from lbsim.contracts import LbsRequest, LbsSheet
from lbsim.fast.build import build_findings
from lbsim.ids import sha256
from lbsim.model.dynamics import age_factor
from lbsim.model.params import Params

CASES = GOLDEN / "lbs_cases"
RECORDS = load_json(CASES / "records.json")["records"]
NAMES = load_json(CASES / "manifest.json")["cases"]


def _paths(name: str, cal=ACTIVE_SEED):
    raw = load_json(CASES / name / "sheet.json")
    f = build_findings(LbsSheet.model_validate(raw), LbsRequest.model_validate(load_json(CASES / name / "request.json")),
                       RECORDS, cal, sheet_sha256=sha256(raw))
    return f, {p.code: p for p in f.income_paths}


def _pensum_now(name: str) -> float:
    return next(p.pensum_now for p in _paths(name)[1].values())


@pytest.mark.parametrize("name", NAMES)
def test_today_stays_at_todays_level_within_the_age_profile(name):
    """`today` is today's income moved only by the sheet's inflation and the model's age profile."""
    f, paths = _paths(name)
    today = paths["today"]
    if not today.income:
        pytest.skip("at or past the reference age: no working years on any path")
    pi = f.inflation.annual_rate
    first = today.income[0]
    p = Params()
    for y in today.income:
        t = y.year - first.year
        bound = first.gross_chf_per_year * (1.0 + pi) ** t * age_factor(y.age, p) / age_factor(first.age, p)
        assert y.gross_chf_per_year == pytest.approx(bound, rel=1e-9), (name, y)


@pytest.mark.parametrize("name", NAMES)
def test_paths_with_a_different_pensum_differ(name):
    _, paths = _paths(name)
    today = paths["today"]
    if not today.income:
        pytest.skip("at or past the reference age: no working years on any path")
    for code in ("full_pensum", "network"):
        other = paths.get(code)
        if other is None or abs(other.pensum_after - today.pensum_now) < 1e-12:
            continue
        if other.education_end_age is None:
            # No education to finish: the pensum applies from today.
            ratio = other.income[0].gross_chf_per_year / today.income[0].gross_chf_per_year
            assert ratio == pytest.approx(other.pensum_after / today.pensum_now, rel=1e-9)
        assert [y.gross_chf_per_year for y in other.income] != [y.gross_chf_per_year for y in today.income]


@pytest.mark.parametrize("name", NAMES)
def test_a_network_path_is_shown_only_when_it_adds_something(name):
    _, paths = _paths(name)
    if "network" in paths and "full_pensum" in paths:
        assert [y.gross_chf_per_year for y in paths["network"].income] != \
            [y.gross_chf_per_year for y in paths["full_pensum"].income]


def test_the_reduced_pensum_household_regression():
    """The live household's shape, anonymised (``golden/lbs_cases/lbsim-reduced-pensum``)."""
    _, before = _paths("lbsim-reduced-pensum", SEED_1_1)
    inc = [round(y.gross_chf_per_year) for y in before["today"].income]
    assert inc[:6] == [56_000, 63_058, 71_566, 81_911, 94_604, 110_330]    # the draft's paths, kept in 1.1.0
    assert [y.gross_chf_per_year for y in before["full_pensum"].income] == \
        [y.gross_chf_per_year for y in before["today"].income]
    f, after = _paths("lbsim-reduced-pensum")
    assert set(after) == {"today", "full_pensum"}          # the network adds nothing at this network's level
    today = [round(y.gross_chf_per_year) for y in after["today"].income]
    full = [round(y.gross_chf_per_year) for y in after["full_pensum"].income]
    assert today[:3] == [56_000, 56_560, 57_126]            # today's level, with the sheet's 1 % inflation
    assert full[:3] == [78_400, 79_184, 79_976]             # the same person at a full pensum, from today
    ep = next(e for e in f.earning_power if e.person_id == f.principal)
    assert ep.level_basis == "modelled" and ep.current.full_pensum_equivalent_chf == pytest.approx(78_400.0)


def test_1_0_0_still_reproduces_the_draft_on_this_household():
    """The correction is 1.2.0's only: under 1.0.0 the adapter's submission carries no switch."""
    _, draft = _paths("lbsim-reduced-pensum", SEED)
    assert [round(y.gross_chf_per_year) for y in draft["today"].income][1] > 60_000
