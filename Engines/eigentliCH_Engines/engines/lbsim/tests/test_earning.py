"""LBSIM-11: one earning-power computation, the prototype's, on lbs's golden households."""

from __future__ import annotations

import hashlib
import json

import pytest

from conftest import GOLDEN, ROOT, load_json

from lbsim.fast import earning

GOLD = load_json(GOLDEN / "earning" / "expected.json")
RECORD_PATH = ROOT.parent / "lbs" / "src" / "lbs" / "seed_records" / "human-capital.json"


def _record() -> dict:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def _rows():
    return [r for r in GOLD["rows"]]


def test_the_record_is_the_one_the_golden_was_built_on():
    assert hashlib.sha256(RECORD_PATH.read_bytes()).hexdigest() == GOLD["manifest"]["record_sha256"]
    assert earning.at_unit(_record()) == pytest.approx(0.7207, abs=0)


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['case']}-{r['person_id']}-{r['kader']}-{r['sector']}")
def test_earning_power_reproduces_the_prototype(row):
    got = earning.modelled(_record(), E=row["E"], N=row["N"], age=row["age"],
                           qualification=row["qualification_highest"], responsibility_stated=row["kader"],
                           sector=row["sector"])
    exp = row["earning_power"]
    if exp is None:
        assert got is None
        return
    assert got is not None
    for mine, theirs in (("at_full_productive_week_chf", "at_full_productive_week"),
                         ("full_time_chf_per_year", "annual_at_forty_hours"),
                         ("monthly_standardised_chf", "monthly_standardised"),
                         ("before_responsibility_chf", "before_responsibility")):
        assert getattr(got, mine) == pytest.approx(exp[theirs], rel=1e-9, abs=1e-9)
    assert got.tier.key == exp["responsibility"]
    assert got.tier.multiplier == pytest.approx(exp["multiplier"], rel=1e-12)
    assert got.inputs["earning_power_at_unit"] == exp["inputs"]["earning_power_at_unit"]
    # The prototype's caveats are the capitals' own, then the tier's, then the unstated tier's; lbsim takes the
    # capitals' caveats from the sheet, so the rest must match word for word.
    assert list(got.caveats) == exp["caveats"][len(exp["caveats"]) - len(got.caveats):]


def test_the_golden_covers_every_tier_and_a_sector():
    seen = {(r["earning_power"] or {}).get("responsibility") for r in GOLD["rows"]}
    assert {"ohne Kaderfunktion", "oberes und mittleres Kader", "topmanagement"} <= seen
    assert any(r["sector"] == "Banken" and r["earning_power"] for r in GOLD["rows"])


def test_a_label_names_the_same_tier_as_its_key():
    record = _record()
    for key, tier in earning.tiers(record).items():
        for label in (tier.get("label") or {}).values():
            a = earning.responsibility(record, key, qualification="Fachhochschule FH", sector=None)
            b = earning.responsibility(record, label, qualification="Fachhochschule FH", sector=None)
            assert (a.key, a.multiplier) == (b.key, b.multiplier)


def test_unknown_capitals_give_no_figure():
    assert earning.modelled(_record(), E=None, N=0.5, age=40, qualification=None, responsibility_stated=None,
                            sector=None) is None
