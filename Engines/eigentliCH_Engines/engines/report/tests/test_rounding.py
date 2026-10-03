"""Display rounding (owner, 03.10.2026, ``review/ROUNDING.md``; REP-44): every row of the rule in both languages,
the edges (negatives, exactly 1 000, 100 000 and 1 000 000, zero, the ends of a chance), which rule a fact
follows, and that a rounded display still verifies under the number check. The scan of every golden page's
displays is in ``test_golden.py``."""

from __future__ import annotations

import pytest

from report import engine
from report import rounding as rnd
from report.calibration import PRODUCTION as CAL
from report.contracts import Fact, FactSource


@pytest.mark.parametrize("value,de,en", [
    (0.0, "CHF 0", "CHF 0"), (0.4, "CHF 0", "CHF 0"), (640.0, "CHF 640", "CHF 640"), (999.4, "CHF 999", "CHF 999"),
    (999.6, "CHF 1 000", "CHF 1,000"), (1000.0, "CHF 1 000", "CHF 1,000"), (1_249.0, "CHF 1 200", "CHF 1,200"),
    (1_250.0, "CHF 1 300", "CHF 1,300"), (38_234.0, "CHF 38 200", "CHF 38,200"),
    (99_949.0, "CHF 99 900", "CHF 99,900"), (99_950.0, "CHF 100 000", "CHF 100,000"),
    (100_000.0, "CHF 100 000", "CHF 100,000"), (578_640.0, "CHF 579 000", "CHF 579,000"),
    (999_499.0, "CHF 999 000", "CHF 999,000"), (999_500.0, "CHF 1,00 Mio.", "CHF 1.00 m"),
    (1_000_000.0, "CHF 1,00 Mio.", "CHF 1.00 m"), (1_354_999.0, "CHF 1,35 Mio.", "CHF 1.35 m"),
    (1_355_000.0, "CHF 1,36 Mio.", "CHF 1.36 m"), (12_345_678.0, "CHF 12,35 Mio.", "CHF 12.35 m"),
    (-780_400.0, "−CHF 780 000", "−CHF 780,000"), (-38_250.0, "−CHF 38 300", "−CHF 38,300"),
    (-0.3, "CHF 0", "CHF 0"), (-2_500_000.0, "−CHF 2,50 Mio.", "−CHF 2.50 m")])
def test_amounts(value, de, en):
    assert rnd.money(value, "de") == de and rnd.money(value, "en") == en


@pytest.mark.parametrize("value,de,en", [
    (0.049, "4,9 %", "4.9%"), (0.04949, "4,9 %", "4.9%"), (0.0495, "5,0 %", "5.0%"), (-0.013, "−1,3 %", "−1.3%"),
    (0.0, "0,0 %", "0.0%"), (-0.0004, "0,0 %", "0.0%"), (0.068, "6,8 %", "6.8%"), (0.2412, "24,1 %", "24.1%")])
def test_rates(value, de, en):
    assert rnd.rate(value, "de") == de and rnd.rate(value, "en") == en


@pytest.mark.parametrize("value,de,en", [
    (0.0, "0 %", "0%"), (1.0, "100 %", "100%"), (0.0001, "unter 1 %", "below 1%"), (0.0099, "unter 1 %", "below 1%"),
    (0.01, "1 %", "1%"), (0.684, "68 %", "68%"), (0.685, "69 %", "69%"), (0.99, "99 %", "99%"),
    (0.991, "über 99 %", "above 99%"), (0.9999, "über 99 %", "above 99%")])
def test_chances(value, de, en):
    assert rnd.chance(value, "de") == de and rnd.chance(value, "en") == en


@pytest.mark.parametrize("value,de,en", [
    (0.27, "27 %", "27%"), (0.2749, "27 %", "27%"), (0.004, "0,4 %", "0.4%"), (0.0095, "1 %", "1%"),
    (0.0094, "0,9 %", "0.9%"), (0.0, "–", "–"), (2.0413626404960775e-16, "–", "–"), (0.0004, "unter 0,1 %", "below 0.1%"), (1.0, "100 %", "100%"),
    (-0.05, "−5 %", "−5%")])
def test_weights(value, de, en):
    assert rnd.weight(value, "de") == de and rnd.weight(value, "en") == en


@pytest.mark.parametrize("fn,value,de,en", [
    (rnd.level, 0.6234, "0,62", "0.62"), (rnd.level, 0.625, "0,63", "0.63"), (rnd.level, 0.0, "0,00", "0.00"),
    (rnd.ratio, 6.04, "6,0", "6.0"), (rnd.whole, 2034.0, "2034", "2034"), (rnd.whole, 66.5, "67", "67"),
    (rnd.whole, 19.6, "20", "20")])
def test_levels_ratios_and_whole_numbers(fn, value, de, en):
    assert fn(value, "de") == de and fn(value, "en") == en
    assert rnd.ratio(0.8, "en", 2) == "0.80", "a beta: two decimals"


@pytest.mark.parametrize("fact_id,unit,kind", [
    ("lbs.totals.net_worth", "chf", "money"), ("lbs.retirement.goal1.needs", "chf_per_year", "money"),
    ("lbs.mandate.required_return", "share", "rate"), ("lbs.pension.person1.bvg.conversion", "share", "rate"),
    ("lbs.real.inflation", "share", "rate"), ("lbsim.chance.base.goal1", "share", "chance"),
    ("lbsim.plan.chance", "share", "chance"), ("lbsim.plan.confidence", "share", "chance"),
    ("pcp.role.Gain", "share", "weight"), ("lbsim.alloc.position.X", "share", "weight"),
    ("lbsim.earning_power.person1.pensum", "share", "weight"), ("lbs.human.person1.E", "number", "level"),
    ("lbs.mandate.horizon", "number", "whole"), ("lbsim.plan.action_now.learning_hours_per_week", "number", "whole"),
    ("pcp.positions_held", "count", "whole"), ("change.lbs.mandate.required_return", "share", "rate"),
    ("delta.lbsim.chance.base.goal1", "share", "chance")])
def test_which_rule_a_fact_follows(fact_id, unit, kind):
    assert rnd.kind_of(fact_id, unit) == kind


def test_the_fact_keeps_its_value_and_prints_the_rounded_display():
    assert engine.fmt(0.0525, "share", "de", "lbs.mandate.required_return") == "5,3 %"
    assert engine.fmt(0.0525, "share", "de", "pcp.role.Gain") == "5 %"
    assert engine.fmt(0.004, "share", "en", "lbsim.chance.base.goal1") == "below 1%"
    assert engine.fmt(174_321.0, "chf_per_year", "de") == "CHF 174 000 pro Jahr"
    assert engine.fmt(14.0, "number", "en", "lbs.mandate.horizon") == "14"
    assert engine.fmt_change(0.0034, "share", "de", "delta.lbs.mandate.required_return") == "+0,3 Prozentpunkte"
    assert engine.fmt_change(0.034, "share", "de", "delta.pcp.role.Gain") == "+3 Prozentpunkte"
    assert engine.fmt_change(35_400.0, "chf", "de", "delta.lbs.totals.net_worth") == "+CHF 35 400"
    assert engine.fmt_change(-0.2, "chf", "de", "delta.lbs.totals.net_worth") == "CHF 0"


def _fact(value: float, unit: str, fid: str = "a") -> Fact:
    return Fact(fact_id=fid, section="balance_sheet", label=fid, value=value, unit=unit,
                display=engine.fmt(value, unit, "de", fid),
                sources=(FactSource(engine="t", artefact_id="T-1", contract_version="t", path="/x"),))


def test_a_sentence_quoting_the_rounded_display_verifies():
    cal = CAL
    facts = [_fact(1_354_999.0, "chf"), _fact(38_234.0, "chf", "b")]
    for text in ("Das Vermögen beträgt rund CHF 1,35 Mio., davon CHF 38 200 frei.",
                 "Net worth is CHF 1.35 m, of which CHF 38,200 is free.",
                 "Das Vermögen beträgt CHF 1 354 999 und CHF 38 234."):
        assert engine.unverified_numbers(text, facts, cal) == (), text
    assert engine.unverified_numbers("Das Vermögen beträgt CHF 1,45 Mio.", facts, cal) == ("1,45",)
