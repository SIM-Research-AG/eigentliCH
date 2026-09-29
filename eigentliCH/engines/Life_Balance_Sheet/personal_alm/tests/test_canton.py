"""The canton, which was collected from the first interview and reached no equation until 25 August 2026.

`income_tax` is a smooth approximation with one asymptotic rate for the whole country and `wealth_tax_rate` is
flat, so every report told a household in Zug and a household in Neuchâtel the same thing about tax. Between
those two the measured burden on a single person at 100 000 is 6.12 % against 18.65 %.

**The factors are measured, not derived.** The plan was to derive them from the ESTV's 2026 «Steuersatz und
Steuerfuss», and that document gives the multiplier without the tariff: Bern's is 2.975 units where Zurich's
is 95 %, because each applies to its own schedule. A factor built from multipliers alone ranks Geneva as the
cheapest canton in Switzerland. So the source is the BFS's own measurement of the burden per cantonal capital,
scaled onto the model's national curve.

Every threshold asserted here is read from `data/canton_tax.json`, never written into the test, so a new
vintage cannot leave a stale number behind in an assertion.
"""

from __future__ import annotations

import json

import pytest

from personal_alm.model import canton
from personal_alm.model.params import Params

TABLE = canton.load()


def test_the_table_covers_every_canton_the_interview_offers():
    """A canton absent from the table is a household silently uncalibrated, and the interview offers 26."""
    assert set(TABLE["factors"]) == set(canton.CANTONS)
    assert set(TABLE["wealth_factors"]) == set(canton.CANTONS)


def test_the_table_carries_its_source_and_vintage():
    """Every forward-looking figure in a report inherits this vintage, so it may not be absent."""
    assert TABLE["as_of"] and "BFS" in TABLE["source"]


def test_the_ordering_matches_what_is_known_about_switzerland():
    """**The check that would have caught a factor built from the multipliers alone.** That version ranked
    Geneva cheapest, which is the opposite of the truth, and no unit test on shape would have noticed.
    """
    f = TABLE["factors"]
    assert f["Zug"] < f["Schwyz"] < f["Zürich"]
    assert f["Zug"] < f["Genf"]
    assert f["Zürich"] < f["Bern"]
    assert f["Zug"] == min(f.values()), "Zug is the lightest income burden in the country"


def test_an_uncalibrated_canton_degrades_to_the_national_rate_and_says_so():
    got = canton.factors_for("Nirgendwo")
    assert got["calibrated"] is False
    assert got["income_factor"] == 1.0 and got["wealth_factor"] == 1.0
    assert got["why_not"]


def test_a_wealth_factor_may_spread_further_than_an_income_factor():
    """**Measuring corrected the guard.** The wealth bound was 2.5 like the income one, and the first real
    table was refused for Freiburg at 2.8. That was not a units error: wealth burdens run from 0.12 % in
    Nidwalden to 0.68 % in Neuchâtel, a factor of nearly six, because the federal share that flattens income
    burdens across cantons has no counterpart in the wealth tax.
    """
    inc = sorted(TABLE["factors"].values())
    wea = sorted(TABLE["wealth_factors"].values())
    assert wea[-1] / wea[0] > inc[-1] / inc[0]
    assert canton._WEALTH_FACTOR_MAX > canton._FACTOR_MAX


def test_a_factor_that_reads_as_a_percentage_is_still_refused(tmp_path):
    """The guard's purpose: a percentage entered as a rate is wrong by a hundred, and would look calibrated."""
    bad = tmp_path / "canton_tax.json"
    bad.write_text(json.dumps({
        "source": "test", "as_of": "2023-12-31",
        "income_factors": {"Zug": 68.3},
        "wealth_factors": {},
    }), encoding="utf-8")
    with pytest.raises(canton.CantonTableError, match="percentage"):
        canton.load(bad)


def test_an_unknown_canton_name_is_refused_rather_than_applied_to_nobody(tmp_path):
    bad = tmp_path / "canton_tax.json"
    bad.write_text(json.dumps({
        "source": "test", "as_of": "2023-12-31",
        "income_factors": {"Zoug": 1.0},
        "wealth_factors": {},
    }), encoding="utf-8")
    with pytest.raises(canton.CantonTableError, match="26 cantons"):
        canton.load(bad)


# --- what the converter does with it ----------------------------------------------------------------------

def submission(canton_name: str) -> dict:
    return {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22"},
        "state": {"age": 45, "W_L": 200_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 300_000.0, "W_3a": 50_000.0, "H": 0.9, "N": 0.5, "E": 0.6},
        "params": {"G": 90_000.0, "ahv_record_share": 1.0, "epsilon": 0.10},
        "goals": [{"kind": "fi", "description": "Unabhängigkeit", "target_year": 2046,
                   "amount_chf": 90_000.0, "confidence": 0.90, "is_consumption": False}],
        "raw": {"birth_year": 1981, "canton": canton_name, "income_gross": 150_000.0,
                "spend_now": 90_000.0},
    }


def test_the_canton_reaches_the_parameters():
    from personal_alm.app.onboarding import case_from_submission
    conv = case_from_submission(submission("Zug"))
    base = Params()
    assert conv.case.param_overrides["tax_rate_max"] < base.tax_rate_max, "Zug is below the national rate"
    assert any("kalibriert" in str(a[2]) for a in conv.assumed), "the calibration must be reported"


def test_two_cantons_produce_different_tax_parameters():
    """The whole point: before this, Zug and Neuchâtel were told the same thing about tax."""
    from personal_alm.app.onboarding import case_from_submission
    zug = case_from_submission(submission("Zug")).case.param_overrides["tax_rate_max"]
    ne = case_from_submission(submission("Neuchâtel")).case.param_overrides["tax_rate_max"]
    assert ne > zug * 2.0


def test_an_uncalibrated_canton_is_deferred_rather_than_assumed():
    from personal_alm.app.onboarding import case_from_submission
    conv = case_from_submission(submission("Nirgendwo"))
    assert "tax_rate_max" not in conv.case.param_overrides
    assert any("canton" in str(d[0]) for d in conv.deferred)


def test_an_explicit_rate_in_the_submission_outranks_the_table():
    """A figure somebody entered is a statement about this household; the table is a statement about a canton."""
    from personal_alm.app.onboarding import case_from_submission
    sub = submission("Zug")
    sub["params"]["tax_rate_max"] = 0.33
    conv = case_from_submission(sub)
    assert conv.case.param_overrides["tax_rate_max"] == 0.33
