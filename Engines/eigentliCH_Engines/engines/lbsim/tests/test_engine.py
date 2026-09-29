"""Unit and property tests of the fast half, the adapter, the calibrations, the texts and the import boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from conftest import GOLDEN, ROOT, load_json

from lbsim.adapter import AdapterError, adapt
from lbsim.calibration import ACTIVE_SEED, SEED, SEED_1_1, SEED_1_2, SEED_1_3, SEED_1_4, SEEDS, calibration_hash, seed
from lbsim.contracts import (FINDING_CODES, LbsRequest, LbsSheet, LifeBalanceFindings, LifeBalanceSimRequest,
                             Unchecked, Words)
from lbsim.fast.build import build_findings
from lbsim.ids import sha256
from lbsim.model import bvg

CASES = GOLDEN / "lbs_cases"
RECORDS = load_json(CASES / "records.json")["records"]
NAMES = load_json(CASES / "manifest.json")["cases"]
TEXT = ACTIVE_SEED.records["findings-text"]


def _case(name: str):
    sheet = load_json(CASES / name / "sheet.json")
    request = load_json(CASES / name / "request.json")
    return LbsSheet.model_validate(sheet), LbsRequest.model_validate(request), sheet


def _findings(name: str, cal=ACTIVE_SEED) -> LifeBalanceFindings:
    sheet, request, raw = _case(name)
    return build_findings(sheet, request, RECORDS, cal, sheet_sha256=sha256(raw))


# --- LBSIM-03: the import boundary ----------------------------------------------------------------------

def test_the_fast_half_and_the_model_import_without_casadi():
    code = ("import sys; import lbsim.contracts, lbsim.calibration, lbsim.adapter, lbsim.fast.build, "
            "lbsim.model.dynamics, lbsim.layer_b; print('casadi' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# --- calibrations (LBSIM-13) ----------------------------------------------------------------------------

def test_the_seed_hashes_are_pinned():
    """A changed seed is a new version: these two hashes move only with a deliberate new calibration."""
    pins = load_json(ROOT / "golden" / "calibration_hashes.json")
    assert {c.version: calibration_hash(c) for c in SEEDS} == pins
    # 1.0.0 and 1.1.0 keep the hashes they had before 1.2.0 existed, and 1.2.0 its own before 1.3.0 (each new
    # field is left out of the canonical form while unset).
    assert pins["1.0.0"] == "CAL-16ddc8c0f11af63f" and pins["1.1.0"] == "CAL-c276230b32143099"
    assert pins["1.2.0"] == "CAL-3a4ecac98ac98b90" and pins["1.3.0"] == "CAL-5f544bab06ed5f76"
    assert pins["1.4.0"] == "CAL-95bbbd2c2f4e7576"


def test_1_0_0_is_the_draft_and_1_1_0_switches_the_three_decisions():
    assert SEED.params == {} and SEED.behaviour.inflation == "none"
    assert SEED.behaviour.earning_power == "draft" and SEED.behaviour.market == "draft"
    assert ACTIVE_SEED.behaviour.inflation == "sheet"
    assert ACTIVE_SEED.behaviour.earning_power == "record" and ACTIVE_SEED.behaviour.market == "allocation"
    assert ACTIVE_SEED.behaviour.currencies == ("CHF",)
    assert ACTIVE_SEED.retirement.withdrawal_rate == 0.03 and ACTIVE_SEED.optimiser.confidence == 0.90
    assert seed("1.1.0") is SEED_1_1 and seed("1.2.0") is SEED_1_2 and seed("1.3.0") is SEED_1_3
    assert seed("1.4.0") is SEED_1_4 and seed("1.5.0") is ACTIVE_SEED
    assert SEED_1_1.behaviour.income_paths is None and SEED_1_2.behaviour.income_paths == "corrected"
    assert SEED_1_2.parent_version == "1.1.0" and SEED.behaviour.income_paths is None
    # 1.3.0 (DECISIONS O-18): 1.2.0 with the owner's plan settings, the optimiser block only.
    assert SEED_1_3.version == "1.3.0" and SEED_1_3.parent_version == "1.2.0"
    o13 = SEED_1_3.optimiser
    assert (o13.max_iter, o13.max_solve_horizon_years, o13.grid, o13.grid_rule) == (500, 10.0, ((10.0, 0.5),),
                                                                                     "variable")
    assert SEED_1_3.model_copy(update={"version": "1.2.0", "parent_version": "1.1.0", "note": SEED_1_2.note,
                                       "optimiser": SEED_1_2.optimiser}) == SEED_1_2
    # 1.4.0 (DECISIONS P-21 to P-24): 1.3.0 with the paths' household, one behaviour switch.
    assert SEED_1_4.version == "1.4.0" and SEED_1_4.parent_version == "1.3.0"
    assert SEED_1_4.behaviour.paths_household == "pensions"
    assert all(c.behaviour.paths_household is None for c in (SEED, SEED_1_1, SEED_1_2, SEED_1_3))
    assert SEED_1_4.model_copy(update={"version": "1.3.0", "parent_version": "1.2.0", "note": SEED_1_3.note,
                                       "behaviour": SEED_1_3.behaviour}) == SEED_1_3
    # 1.5.0 (DECISIONS P-25): 1.4.0 with each stated income where it belongs, one behaviour switch.
    assert ACTIVE_SEED.version == "1.5.0" and ACTIVE_SEED.parent_version == "1.4.0"
    assert ACTIVE_SEED.behaviour.income_levels == "stated"
    assert all(c.behaviour.income_levels is None for c in SEEDS[:-1])
    assert ACTIVE_SEED.model_copy(update={"version": "1.4.0", "parent_version": "1.3.0", "note": SEED_1_4.note,
                                          "behaviour": SEED_1_4.behaviour}) == SEED_1_4
    assert all(c.optimiser.max_solve_horizon_years is None for c in (SEED, SEED_1_1, SEED_1_2))
    # The draft's run_case settings, verbatim.
    o = SEED.optimiser
    assert (o.M_opt, o.M_eval, o.n_starts, o.restore_starts, o.max_iter, o.seed_retries, o.cvar_tol) == \
        (14, 400, 3, 2, 400, 3, 1e-3)


def test_config_names_the_active_calibration():
    import yaml
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert config["calibration"]["active"] == ACTIVE_SEED.version
    assert config["service"]["port"] == 8014


# --- LBSIM-12: the tables agree with lbs's records ------------------------------------------------------

def _lbs_record(name: str) -> dict:
    return json.loads((ROOT.parent / "lbs" / "src" / "lbs" / "seed_records" / f"{name}.json")
                      .read_text(encoding="utf-8"))


def test_every_figure_shared_with_lbs_is_equal():
    table = bvg.load()
    ahv, proj = _lbs_record("ahv-pension"), _lbs_record("bvg-projection")
    a, b = table["ahv"], table["bvg"]
    assert a["min_pension_monthly"] == ahv["monthly"]["minimum"]
    assert a["max_pension_monthly"] == ahv["monthly"]["maximum"]
    assert a["max_couple_sum_monthly"] == ahv["monthly"]["couple_cap"]
    assert a["payments_per_year"] == ahv["monthly"]["payments_per_year"]
    assert b["entry_threshold_yearly"] == proj["coordination"]["entry_threshold"]
    assert b["coordination_deduction_yearly"] == proj["coordination"]["deduction"]
    assert b["upper_limit_yearly"] == proj["coordination"]["upper_limit"]
    assert b["min_coordinated_salary_yearly"] == proj["coordination"]["minimum_coordinated"]
    assert b["savings_start_age"] == proj["credits"]["starts_at_age"]
    assert [(x["from_age"], x["to_age"], x["rate"]) for x in b["savings_rates"]] == \
        [(x["from_age"], x["to_age"], x["rate"]) for x in proj["credits"]["bands"]]
    # The draft's Params figures that rest on the same table.
    from lbsim.model.params import Params
    p = Params()
    assert p.ahv_full_single == a["max_pension_monthly"] * a["payments_per_year"]
    assert p.ahv_min_single == a["min_pension_monthly"] * a["payments_per_year"]
    assert p.ahv_income_for_max == ahv["monthly"]["scale_44"][-1]["up_to"]
    assert p.pension_interest == proj["interest"]["minimum_rate"]
    assert p.ahv_couple_cap_multiple * a["max_pension_monthly"] == ahv["monthly"]["couple_cap"]
    assert p.pillar3a_cap == table["pillar3a"]["max_with_pension_fund"]


def test_the_one_known_difference_is_the_conversion_rate():
    """Not an overlap but worth pinning: the draft's 5.25 % on the whole capital is a declared assumption, lbs's
    6.8 % the legal minimum on the mandatory part. The findings name it as an assumption."""
    from lbsim.fast.gameplan import PILLAR2_CONVERSION_RATE
    assert PILLAR2_CONVERSION_RATE == 0.0525
    assert _lbs_record("bvg-projection")["conversion"]["minimum_rate"] == 0.068
    f = _findings("lbsim-couple")
    assert any(a.key == "conversion_rate" and a.value == 0.0525 for a in f.assumptions)


# --- LBSIM-17: the findings never say "buy" --------------------------------------------------------------

def _all_templates(record: dict) -> list[str]:
    out: list[str] = []

    def walk(v, key=""):
        if key in ("_about", "policy", "headlines"):
            return
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and len(v) > 12:
            out.append(v)
    walk(record)
    return out


def test_no_template_carries_a_forbidden_verb_or_a_product_name():
    policy = TEXT["policy"]
    alloc = load_json(GOLDEN / "samples" / "upstream" / "allocation.json")
    names = [i["name"] for i in alloc["instruments"]]
    words = policy["forbidden_verbs"] + policy["product_words"] + names
    hits = []
    for template in _all_templates(TEXT):
        for w in words:
            if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", template, flags=re.IGNORECASE):
                hits.append((w, template[:80]))
    assert not hits, hits[:5]


def test_the_scan_would_catch_a_forbidden_verb():
    """A mutation check on the scan itself: a template that says buy is caught."""
    policy = TEXT["policy"]
    bad = "Kaufen Sie jetzt mehr davon."
    assert any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", bad, flags=re.IGNORECASE)
               for w in policy["forbidden_verbs"])


def test_no_template_carries_a_number():
    for code, spec in TEXT["findings"].items():
        for lang in ("de", "en"):
            for part, template in spec["text"][lang].items():
                # "3a" is the name of a pillar (Säule 3a), not a figure.
                stripped = re.sub(r"(?<![0-9A-Za-z])3a(?![0-9A-Za-z])", "", re.sub(r"\{[a-z0-9_]+\}", "", template))
                assert not re.search(r"\d", stripped), (code, lang, part, template)


def test_every_rule_has_a_template_and_every_placeholder_is_a_figure():
    assert set(TEXT["findings"]) == set(FINDING_CODES)
    for code, spec in TEXT["findings"].items():
        assert spec["action_kind"] in ("ask", "quantify", "decide_between")
        for lang in ("de", "en"):
            for template in spec["text"][lang].values():
                for name in re.findall(r"\{([a-z0-9_]+)\}", template):
                    assert name in spec["figures"], (code, name)
    assert set(TEXT["unchecked"]) >= set(FINDING_CODES)


# --- the findings artefact -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_every_rule_is_either_fired_or_unchecked_or_passed_and_unchecked_names_its_question(name):
    f = _findings(name)
    fired = {x.code for x in f.findings}
    unchecked = {u.code for u in f.unchecked}
    assert not fired & unchecked
    for u in f.unchecked:
        assert u.missing or u.answered_by == "plan"
    assert "goal_not_fundable" in unchecked  # only the plan decides it


@pytest.mark.parametrize("name", NAMES)
def test_the_artefact_is_deterministic_and_content_addressed(name):
    a, b = _findings(name), _findings(name)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    assert re.match(r"^LSF-[0-9a-f]{16}$", a.artefact_id)
    assert a.provenance.upstream["lbs"]["artefact_id"] == a.life_balance_sheet_id


def test_the_findings_key_moves_with_the_calibration_but_not_with_anything_else():
    a, b = _findings("lbsim-couple", SEED), _findings("lbsim-couple", ACTIVE_SEED)
    assert a.provenance.idempotency_key != b.provenance.idempotency_key


def test_the_sheets_inflation_is_used_and_stated():
    f = _findings("lbsim-couple")
    sheet, _, _ = _case("lbsim-couple")
    assert f.inflation.annual_rate == sheet.real_view.inflation.annual_rate == 0.01
    assert f.basis == "nominal"
    assert any(a.key == "inflation" for a in f.assumptions)
    assert _findings("lbsim-couple", SEED).inflation.annual_rate == 0.0


def test_the_real_view_of_saving_needs_is_the_deflated_target():
    f = _findings("lbsim-couple")
    for path in f.income_paths:
        for nom, real in zip(path.saving_need, path.views.real.saving_need):
            assert real.target_chf == pytest.approx(nom.target_chf / 1.01 ** nom.years, rel=1e-12)


def test_a_property_goal_is_its_deposit():
    """lbs's property.mandate_target: the deposit, never the price (20 % owner-occupied)."""
    sheet, request, _ = _case("lbsim-couple")
    a = adapt(sheet, request, RECORDS, SEED)
    home = next(g for g in a.submission["goals"] if g["kind"] == "home")
    assert home["amount_chf"] == pytest.approx(0.2 * 1_150_000.0)


def test_an_other_goal_with_an_amount_and_a_date_is_a_capital_goal():
    sheet, request, _ = _case("lbsim-early")
    a = adapt(sheet, request, RECORDS, ACTIVE_SEED)
    assert any(g["kind"] == "capital" and g["description"] == "g-gift" for g in a.submission["goals"])


def test_the_adapter_refuses_a_client_mismatch():
    sheet, request, _ = _case("lbsim-couple")
    other = request.model_copy(update={"client_ref": "someone-else"})
    with pytest.raises(AdapterError):
        adapt(sheet, other, RECORDS, ACTIVE_SEED)


def test_missing_new_facts_leave_their_rules_unchecked():
    """db-* cases predate lbs@1.4.0: no legal documents, no amortisation mode, no stop age."""
    f = _findings("db-01")
    unchecked = {u.code: u for u in f.unchecked}
    assert unchecked["no_legal_documents"].missing == ("legal_documents",)


def test_the_earning_power_of_each_adult_is_reported():
    f = _findings("lbsim-couple")
    assert {e.person_id for e in f.earning_power} == {"p1", "p2"}
    p1 = next(e for e in f.earning_power if e.person_id == "p1")
    assert p1.level_basis == "stated" and p1.modelled.responsibility.tier == "oberes und mittleres Kader"
    assert p1.modelled.inputs.earning_power_at_unit == 0.7207
    p2 = next(e for e in f.earning_power if e.person_id == "p2")
    assert p2.level_basis == "modelled" and not p2.modelled.responsibility.stated


def test_no_raw_key_reaches_a_sentence():
    """Readable text: every sentence a person reads is a {de, en} pair from the record."""
    f = _findings("lbsim-thin").model_dump(mode="json")

    def words(v):
        if isinstance(v, dict):
            if set(v) == {"de", "en"} and all(isinstance(x, str) for x in v.values()):
                yield v
            else:
                for x in v.values():
                    yield from words(x)
        elif isinstance(v, list):
            for x in v:
                yield from words(x)
    for w in words(f):
        for text in w.values():
            assert not re.search(r"\b[a-z]+_[a-z_]+\b", text), text


# --- contracts --------------------------------------------------------------------------------------------

def test_the_request_contract():
    r = LifeBalanceSimRequest(client_ref="c1", life_balance_sheet_id="LBS-0123456789abcdef")
    assert r.optimise == "background" and r.scenarios is None
    with pytest.raises(ValueError):
        LifeBalanceSimRequest(client_ref="a name", life_balance_sheet_id="LBS-0123456789abcdef")
    with pytest.raises(ValueError):
        LifeBalanceSimRequest(client_ref="c1", life_balance_sheet_id="LBS-0123456789abcdef", n_paths=10)
    with pytest.raises(ValueError):
        LifeBalanceSimRequest(client_ref="c1", life_balance_sheet_id="LBS-0123456789abcdef",
                              scenarios=("depression", "depression"))
    with pytest.raises(ValueError):
        LifeBalanceSimRequest(client_ref="c1", life_balance_sheet_id="LBS-0123456789abcdef", extra=1)


def test_an_unchecked_rule_must_name_its_question():
    with pytest.raises(ValueError):
        Unchecked(code="thin_liquidity", reason=Words(de="x", en="x"))
