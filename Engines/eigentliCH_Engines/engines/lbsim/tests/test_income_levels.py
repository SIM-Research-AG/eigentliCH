"""DECISIONS P-25 (calibration 1.5.0): each stated income where it belongs.

The defect (B2's live refresh, 29.09.2026): the stated expectation at a full pensum ("once any education is
done") was applied from today and multiplied by a pensum above 1, so a principal working 55 hours who earns and
expects 155 000 was shown 200 846 in the first year of the education path (and 202 976 on `today`, 200 846 on
`full_pensum`). The draft reads it so; 1.0.0 to 1.4.0 keep it, 1.5.0 corrects it.
"""

from __future__ import annotations

import pytest

from conftest import GOLDEN, load_json

from lbsim.adapter import adapt
from lbsim.calibration import ACTIVE_SEED, SEED_1_4
from lbsim.contracts import LbsRequest, LbsSheet
from lbsim.fast.build import build_findings
from lbsim.ids import sha256

CASES = GOLDEN / "lbs_cases"
RECORDS = load_json(CASES / "records.json")["records"]
NAMES = load_json(CASES / "manifest.json")["cases"]


def _run(name: str, cal=ACTIVE_SEED):
    raw = load_json(CASES / name / "sheet.json")
    sheet = LbsSheet.model_validate(raw)
    request = LbsRequest.model_validate(load_json(CASES / name / "request.json"))
    f = build_findings(sheet, request, RECORDS, cal, sheet_sha256=sha256(raw))
    a = adapt(sheet, request, RECORDS, cal)
    return f, a, request, {p.code: p for p in f.income_paths}


@pytest.mark.parametrize("name", NAMES)
def test_before_the_education_ends_no_path_is_above_the_stated_income(name):
    f, a, request, paths = _run(name)
    gross = a.adults[a.principal].gross_income
    if not gross or not paths or not paths["today"].income:
        pytest.skip("no stated current income, or no working years")
    pi = f.inflation.annual_rate
    for code in ("today", "education", "full_pensum"):
        path = paths.get(code)
        if path is None:
            continue
        first = path.income[0]
        if code != "today" and path.education_end_age is None:
            continue  # without an education the path's change applies from today (P-9)
        assert first.gross_chf_per_year <= gross * (1 + 1e-9), (name, code, first)
        if path.education_end_age is not None:
            for y in path.income:
                if y.age < path.education_end_age:
                    level = gross * (1 + pi) ** (y.year - first.year)
                    assert y.gross_chf_per_year <= level * 1.10, (name, code, y)  # shape within the age profile


@pytest.mark.parametrize("name", NAMES)
def test_from_the_end_year_the_stated_amount_applies_at_a_full_pensum(name):
    f, a, request, paths = _run(name)
    principal = next(p for p in request.household.persons if p.person_id == a.principal)
    ep = principal.earning_power
    path = paths.get("full_pensum")
    if ep is None or ep.expected_full_pensum_income is None or path is None or not path.income:
        pytest.skip("no stated expectation or no full-pensum path")
    start = path.education_end_age if path.education_end_age is not None else path.income[0].age
    y = next((y for y in path.income if y.age >= start), None)
    if y is None:
        pytest.skip("the education ends after the last working year")
    t = y.year - path.income[0].year
    assert y.gross_chf_per_year == pytest.approx(ep.expected_full_pensum_income * (1 + f.inflation.annual_rate) ** t,
                                                 rel=1e-9)


@pytest.mark.parametrize("name", NAMES)
def test_no_education_path_without_a_stated_education(name):
    _, _, request, paths = _run(name)
    principal = next(p for p in request.household.persons if p.person_id == request.household.principal) \
        if request.household.principal else None
    ep = principal.earning_power if principal else None
    if ep is None or ep.education_status not in ("in_progress", "planned"):
        assert "education" not in paths


@pytest.mark.parametrize("case, today_first, stated", [("lbsim-overtime-a", 155_000.0, 155_000.0),
                                                       ("lbsim-overtime-b", 140_000.0, 150_000.0)])
def test_the_overtime_shapes_regression(case, today_first, stated):
    """Reto's and Michele's shapes, anonymised: over full-time hours, an education ending in 2027."""
    _, _, _, before = _run(case, SEED_1_4)
    assert before["education"].income[0].gross_chf_per_year > stated          # the draft's reading, kept in 1.4.0
    f, _, _, after = _run(case)
    for code in ("today", "education", "full_pensum"):
        assert after[code].income[0].gross_chf_per_year == pytest.approx(today_first, rel=1e-12)
    y2027 = next(y for y in after["full_pensum"].income if y.year == 2027)
    assert y2027.gross_chf_per_year == pytest.approx(stated * 1.01, rel=1e-9)
    edu2027 = next(y for y in after["education"].income if y.year == 2027)
    assert edu2027.gross_chf_per_year == pytest.approx(stated * 1.01, rel=1e-9)  # pensum above 1 never on top
