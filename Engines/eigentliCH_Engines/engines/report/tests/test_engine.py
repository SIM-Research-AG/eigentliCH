"""The pure core: extraction, formatting, sections, changes, the reject rules and the number check."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from report import engine
from report.calibration import PRODUCTION as CAL
from report.contracts import Allocation, Fact, FactSource, LifeBalanceSheet

from .conftest import INPUTS, LBS, PCP

ALLOC = Allocation.model_validate_json(PCP)
SHEET = LifeBalanceSheet.model_validate_json(LBS)


def resolve(artefact: dict, pointer: str):
    node = artefact
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@pytest.mark.parametrize("lang", ["de", "en"])
def test_every_pcp_fact_is_read_from_the_path_it_cites(lang):
    raw = json.loads(PCP)
    facts = engine.extract_pcp(ALLOC, CAL, lang)
    assert len(facts) > 20
    for f in facts:
        (src,) = f.sources
        assert src.engine == "pcp" and src.artefact_id == ALLOC.artefact_id
        node = resolve(raw, src.path)
        if f.derivation and f.derivation.startswith("count"):
            assert f.value == float(len(node) if "held" not in f.fact_id else
                                    sum(i["weight"] >= CAL.position_min_weight for i in node))
        else:
            assert node == f.value or float(node) == f.value, f.fact_id


def constructed_sheet() -> dict:
    """syn-couple with what the constructed lbs cases leave empty filled in: human capital values, a
    retirement finding, an available AHV pension, couple cap and risk profile. Only to exercise the extractor."""
    raw = json.loads(LBS)
    raw["human_capital"][0]["E"] = {**raw["human_capital"][0]["E"], "value": 0.9571, "absent_because": None}
    raw["retirement"] = [{"goal_id": "g9", "verdict": "does_not_meet", "needs_per_year": 96000.0,
                          "target_date": "2039-01-01", "undetermined_because": [], "caveats": [], "ahv": None,
                          "pillar2": None, "covered_per_year": 71000.0, "shortfall_per_year": 25000.0}]
    raw["pensions"][0]["ahv"] = {"status": "available", "basis": "mdje_stated", "mdje": 88000.0, "years": 44,
                                 "full_scale": 44, "full_monthly": 2450, "factor": 1.0, "monthly": 2450.0,
                                 "yearly": 29400.0, "at_minimum": False, "at_maximum": True, "caveats": [], "levers": []}
    raw["couple_cap"] = {"status": "available", "uncapped_monthly": 4900.0, "cap": 3675, "monthly": 3675.0,
                         "yearly": 44100.0, "cap_binds": True, "lost_to_the_cap_monthly": 1225.0}
    raw["risk_profile"] = {"status": "available", "value": 0.42, "binds_on": "capacity", "willingness": {},
                           "capacity": {}, "capacity_inputs": {}, "role_bounds": None, "asset_class_bounds": None,
                           "curve_slope": None, "sustainability": {}, "caveats": []}
    return raw


SHEETS = {"couple": json.loads(LBS), "property": json.loads((INPUTS / "lbs_sheet_property.json").read_bytes()),
          "liquidity": json.loads((INPUTS / "lbs_sheet_liquidity.json").read_bytes()), "constructed": constructed_sheet()}


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("name", sorted(SHEETS))
def test_every_lbs_fact_is_read_from_the_path_it_cites(name, lang):
    raw = SHEETS[name]
    sheet = LifeBalanceSheet.model_validate(raw)
    facts = engine.extract_lbs(sheet, CAL, lang)
    assert facts and (raw["totals"]["net_worth"] is None) != any(f.fact_id == "lbs.totals.net_worth" for f in facts)
    for f in facts:
        (src,) = f.sources
        assert src.engine == "lbs" and src.artefact_id == sheet.artefact_id
        node = resolve(raw, src.path)
        if f.fact_id.startswith("lbs.capital."):
            # A capital's level in words (REP-41), derived from the value its path cites.
            assert f.derivation and f.value == engine.level_of(float(node), 0.0, 1.0), f.fact_id
        elif f.derivation:
            assert f.value == float(len(node))
        elif f.unit == "count":
            assert f.value == float(node), f.fact_id
        elif f.fact_id.startswith("lbs.gap."):
            assert f.value.endswith(node)
        elif src.path.endswith(("/reason", "/absent_because")) and not f.fact_id.startswith("lbs.liquidity."):
            assert f.value == (node if node.startswith("not available") else f"not available: {node}"), f.fact_id
            assert "not available: not available" not in f.value, f.fact_id
        else:
            assert node == f.value, f.fact_id


@pytest.mark.parametrize("name", sorted(SHEETS))
def test_a_section_lbs_could_not_compute_is_stated_and_never_a_number(name):
    raw = SHEETS[name]
    facts = engine.extract_lbs(LifeBalanceSheet.model_validate(raw), CAL, "de")
    stated = [f for f in facts if isinstance(f.value, str) and f.value.startswith("not available")]
    assert stated, "every constructed case has at least one section lbs could not compute"
    for f in stated:
        assert f.unit == "text" and f.display.startswith("nicht verfügbar")
    by = {f.fact_id: f for f in facts}
    for p in raw["pensions"]:
        for kind in ("ahv", "bvg"):
            if p[kind]["status"] == "not_available":
                assert by[f"lbs.pension.{p['person_id']}.{kind}"].unit == "text"
                assert not any(i.startswith(f"lbs.pension.{p['person_id']}.{kind}.") for i in by)
    if raw["mandate_proposal"]["status"] == "not_available":
        assert by["lbs.mandate"].value.startswith("not available")


def test_the_constructed_sheet_reports_every_available_section():
    facts = {f.fact_id: f for f in engine.extract_lbs(LifeBalanceSheet.model_validate(constructed_sheet()), CAL, "de")}
    assert facts["lbs.human.p1.E"].value == 0.9571 and facts["lbs.human.p1.E"].display == "0,96"
    assert facts["lbs.retirement.g9.shortfall"].display == "CHF 25 000 pro Jahr"
    assert facts["lbs.retirement.g9.verdict"].display == "nicht erfüllt"
    assert facts["lbs.pension.p1.ahv.yearly"].value == 29400.0
    assert facts["lbs.couple_cap.yearly"].value == 44100.0 and facts["lbs.couple_cap.binds"].value is True
    assert facts["lbs.risk.value"].value == 0.42
    assert {f.section for f in facts.values()} >= {"human_capital", "pensions", "retirement", "risk", "mandate"}


def test_no_label_carries_a_figure():
    """A number in a label reaches the prompt without being a fact, and the model quotes it (measured on the
    live run of 28.09.2026: "Pensionskassenguthaben mit 65"). Labels carry words; figures are facts."""
    import re

    for raw in SHEETS.values():
        for lang in ("de", "en"):
            for f in engine.extract_lbs(LifeBalanceSheet.model_validate(raw), CAL, lang):
                assert not re.search(r"\d{2,}", f.label), (f.fact_id, f.label)
    for lang in ("de", "en"):
        for f in engine.extract_pcp(ALLOC, CAL, lang):
            if not f.fact_id.startswith(("pcp.position.", "pcp.position_role.")):   # instrument names are names
                assert not re.search(r"\d{2,}", f.label), (f.fact_id, f.label)


def test_property_and_liquidity_findings():
    prop = {f.fact_id: f for f in engine.extract_lbs(LifeBalanceSheet.model_validate(SHEETS["property"]), CAL, "en")}
    assert any(k.startswith("lbs.property.") and k.endswith(".verdict") for k in prop)
    liq = {f.fact_id: f for f in engine.extract_lbs(LifeBalanceSheet.model_validate(SHEETS["liquidity"]), CAL, "en")}
    assert any(k.startswith("lbs.liquidity.") and k.endswith(".gap") for k in liq)


def test_positions_are_listed_from_the_threshold_in_weight_order():
    facts = [f for f in engine.extract_pcp(ALLOC, CAL, "de") if f.fact_id.startswith("pcp.position.")]
    held = [i for i in ALLOC.instruments if i.weight >= CAL.position_min_weight]
    rounded = [round(f.value, 9) for f in facts]
    assert len(facts) == len(held) and rounded == sorted(rounded, reverse=True)


@pytest.mark.parametrize("value,unit,de,en", [
    (1035000.0, "chf", "CHF 1,04 Mio.", "CHF 1.04 m"), (-780000.0, "chf", "−CHF 780 000", "−CHF 780,000"),
    (174000.0, "chf_per_year", "CHF 174 000 pro Jahr", "CHF 174,000 a year"), (0.45, "share", "45 %", "45%"),
    (7.0, "count", "7", "7"), (28.985346, "number", "28,99", "28.99"), (True, "flag", "ja", "yes"),
    ("2024-12-31", "date", "31.12.2024", "31 December 2024")])
def test_the_house_formats(value, unit, de, en):
    assert engine.fmt(value, unit, "de") == de and engine.fmt(value, unit, "en") == en


def test_sections_keep_the_fixed_order_and_skip_the_empty():
    facts = engine.extract_pcp(ALLOC, CAL, "de") + engine.extract_lbs(SHEET, CAL, "de")
    keys = [k for k, _ in engine.sections_for(facts)]
    assert keys == [k for k in engine.SECTION_KEYS if k in keys]
    assert "retirement" not in keys and "changes" not in keys and keys[0] == "household"


def _fact(fid, value, unit="chf", section="balance_sheet", previous=None, display=None):
    return Fact(fact_id=fid, section=section, label=fid, value=value, unit=unit,
                display=display or engine.fmt(value, unit, "de"), previous=previous,
                sources=(FactSource(engine="t", artefact_id="T-1", contract_version="t", path="/x"),))


def test_the_number_check_accepts_renderings_and_flags_inventions():
    facts = [_fact("a", 1035000.0), _fact("b", 0.45, "share"), _fact("c", 7.0, "count"),
             _fact("d", "2024-12-31", "date")]
    ok = ("Das Reinvermögen beträgt CHF 1 035 000, also rund 1,0 Millionen Franken; 45 % liegen in einer Rolle, "
          "auf sieben oder 7 Bausteine verteilt, Stand 31.12.2024 (im Jahr 2024).")
    assert engine.unverified_numbers(ok, facts, CAL) == ()
    bad = "Das Reinvermögen beträgt CHF 1 053 000 und 46 % liegen in einer Rolle, Stand 30.12.2024."
    assert engine.unverified_numbers(bad, facts, CAL) == ("30.12.2024", "1 053 000", "46")
    # a scaled rendering needs its scale word, a percentage its percent sign
    assert engine.unverified_numbers("rund 1,0 Franken und 45 Rollen", facts, CAL) == ("1,0", "45")


def test_a_figure_from_another_section_does_not_verify():
    """The narrow allowed set (sectionprose.py): a true figure of another section is not this section's."""
    balance = [_fact("lbs.totals.net_worth", 1035000.0)]
    assert engine.unverified_numbers("Das Einkommen beträgt CHF 174 000 pro Jahr.", balance, CAL) == ("174 000",)


def test_a_change_in_a_share_may_be_said_in_percentage_points():
    delta = _fact("delta.x", 0.15, "share", section="changes", display=engine.fmt_change(0.15, "share", "de"))
    assert delta.display == "+15 Prozentpunkte"
    assert engine.unverified_numbers("Der Anteil stieg um 15 Prozentpunkte.", [delta], CAL) == ()
    assert engine.unverified_numbers("Der Anteil stieg um 16 Prozentpunkte.", [delta], CAL) == ("16",)


@hsettings(max_examples=200, deadline=None)
@given(st.integers(min_value=100, max_value=99_999_999))
def test_property_the_printed_display_of_a_figure_always_verifies(value):
    f = _fact("a", float(value))
    for lang in ("de", "en"):
        text = f"Der Betrag ist {engine.fmt(float(value), 'chf', lang)} in diesem Abschnitt."
        assert engine.unverified_numbers(text, [f], CAL) == (), text


@pytest.mark.parametrize("text,why", [
    ("Sie sollten mehr sparen, weil das Vermögen gross ist und die Lage es erlaubt, sagen wir.", "recommends"),
    ("Das Vermögen beträgt 130 000 Euro, das ist viel Geld für einen Haushalt dieser Art.", "currency"),
    ("Abschnitt: Die Bilanz. Hier steht das Vermögen des Haushalts mit allen Positionen.", "repeats"),
    ("DAS VERMÖGEN IST GROSS UND DIE SCHULDEN SIND KLEIN UND DAS IST ALLES WAS HIER STEHT.", "capitals"),
    ("Zu kurz.", "too short"), ("wort " * 150, "too long"),
    ("Das Vermögen ist 很好 und die Schulden sind klein, so steht es in der Tabelle daneben.", "language")])
def test_the_reject_rules(text, why):
    assert why in engine.reject_reason(text, "de", CAL)


def test_a_sound_draft_passes_the_reject_rules():
    text = "Das Reinvermögen beträgt gut eine Million Franken, und der grösste Teil davon ist gebunden."
    assert engine.reject_reason(text, "de", CAL) is None
    assert engine.reject_reason("You should buy this fund now, it is clearly the best option here.", "en", CAL)


def test_clean_removes_presentation_and_writes_swiss_german():
    assert engine.clean("## Titel\n- Das **große** Vermögen", "de") == "Titel Das grosse Vermögen"


def _report(facts):
    from report.contracts import Report, ReportProvenance

    prov = ReportProvenance(engine_version="report@1.0.0", contract_versions={}, calibration_version="1.0.0",
                            calibration_hash="CAL-x", idempotency_key="IDK-x", request_id="RRQ-x", sources=(),
                            previous_report_id=None, model=None)
    return Report(artefact_id="REP-prev", client_ref="c", kind="report", language="de", title="t",
                  previous_report_id=None, as_of="2026-01-01", facts=tuple(facts), sections=(), complete=True,
                  html="", provenance=prov)


def test_changes_cite_both_reports_and_carry_the_difference():
    prev = _report([_fact("lbs.totals.net_worth", 1000000.0), _fact("lbs.totals.drawable", 95000.0),
                    _fact("gone", 5.0, "count")])
    now = [_fact("lbs.totals.net_worth", 1035000.0), _fact("lbs.totals.drawable", 95000.0), _fact("new", 1.0, "count")]
    ch = {f.fact_id: f for f in engine.change_facts(prev, now, "de")}
    moved = ch["change.lbs.totals.net_worth"]
    assert moved.previous == 1000000.0 and moved.value == 1035000.0
    assert moved.display == "CHF 1,00 Mio. → CHF 1,04 Mio."
    assert [s.artefact_id for s in moved.sources] == ["REP-prev", "T-1"] and moved.sources[0].path == "/facts/0/value"
    assert ch["delta.lbs.totals.net_worth"].value == 35000.0 and ch["delta.lbs.totals.net_worth"].display == "+CHF 35 000"
    assert ch["changes.unchanged"].value == 1.0
    assert ch["changes.added"].value == "new" and ch["changes.removed"].value == "gone"
    assert engine.unverified_numbers("Das Reinvermögen stieg von CHF 1 000 000 auf CHF 1 035 000, um CHF 35 000.",
                                     list(ch.values()), CAL) == ()


def test_the_extractor_registry_names_both_engines():
    assert set(engine.EXTRACTORS) == {"pcp", "lbs"}
    assert engine.EXTRACTORS["pcp"].path("PCP-1") == "/allocation/PCP-1"
    assert engine.EXTRACTORS["lbs"].path("LBS-1") == "/artefacts/LBS-1"
    assert engine.EXTRACTORS["lbs"].client_ref(SHEET) == SHEET.client_ref
    assert engine.EXTRACTORS["pcp"].client_ref(ALLOC) is None
