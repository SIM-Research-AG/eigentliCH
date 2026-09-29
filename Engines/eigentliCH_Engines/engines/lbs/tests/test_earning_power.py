"""lbs@1.4.0 (LBS-39 to LBS-41): the answers lbsim reads, stated once in lbs, validated and never computed from, and
the request of a sheet read back.

* A request without the new fields hashes exactly as it did under lbs@1.3.0: pinned on all 28 golden cases
  (layer A and every step of layer B) and on the sample request. The idempotency key moves only through the
  engine version.
* Each new field, once stated, is a new request. Out-of-range values are refused with a sentence.
* The sheet is unchanged: earning power stays ``not_available`` with the gap naming lbsim.
* ``GET /artefacts/{id}/request`` returns the stored request; its hash equals the sheet's ``request_hash``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lbs import service
from lbs.calibration import CORRECTED_1_5, SEED
from lbs.contracts import FACTS_ADDED_1_4, LifeBalanceSheetRequest, NotAvailable
from lbs.service import build_sheet, idempotency_key, request_hash

from . import layer_b as L
from .conftest import sample_request

#: Every golden request's hash under lbs@1.3.0, computed before the fields of LBS-39 existed. Frozen.
GOLDEN_REQUEST_HASHES = {
    "db-01": "REQ-ec7529a6329728ce",
    "db-02": "REQ-ccde63cea5d415b7",
    "db-03": "REQ-2017ca4551cc2f8f",
    "db-04": "REQ-d2dce07aef5963b8",
    "db-05": "REQ-114579c11b1f020c",
    "db-06": "REQ-b526325212739151",
    "db-07": "REQ-3575b08609478c9b",
    "db-08": "REQ-506ad0294089228e",
    "syn-couple": "REQ-2f4ec6072ec6507f",
    "syn-liquidity": "REQ-8289b399bd26a6b7",
    "syn-property-1": "REQ-89097137260e9a2e",
    "syn-property-2": "REQ-20c7bc32e926adba",
    "syn-property-3": "REQ-e9a9e4e100a3ee2e",
    "syn-property-4": "REQ-e1d578e10394ed05",
    "syn-property-5": "REQ-532ab96486b6da35",
    "q-ceiling": "REQ-533e23358a755b41",
    "q-horizon": "REQ-8d3523f5d836c428",
    "q-no-vessel": "REQ-9763823641ebb3a0",
    "q-zero-income": "REQ-4de42f9bf841d511",
    "r-human-capital": "REQ-56c9121cbd95e27b",
    "r-paid-mortgage": "REQ-e07cc263423099f0",
    "r-share-missing": "REQ-441475aa52bd3809",
    "r-share-stated": "REQ-3b15872b56b07e35",
    "v-future": "REQ-745f6f6cb2c7de27",
    "v-indexed": "REQ-b1fd25bb66adfc26",
    "v-not-realistic": "REQ-2c3c7766ba2d519a",
    "v-retirement": "REQ-5cf28c05f2130e16",
    "v-worked-example": "REQ-ebde6c8e393a02a5",
}
SAMPLE_HASH = "REQ-d6000dfa05961ba6"
#: The sample request's key under calibration 1.5.0 with the engine version of lbs@1.3.0.
SAMPLE_KEY_13 = "IDK-c236483236e287e9"

EARNING_POWER = {"expected_full_pensum_income": 135000, "responsibility": "oberes und mittleres Kader",
                 "sector": "Versicherungen", "education_status": "in_progress", "education_end_year": 2028,
                 "education_hours": "3–5", "education_budget_per_year": 8000, "health_work_capacity": 0.8}
FACTS = {"stop_work_age": 63, "legal_documents": ["Testament", "Vorsorgeauftrag"],
         "mortgage_fixed_until": "2029-03-31", "amortisation_mode": "indirect", "own_use_share": 1.0,
         "pillar3a_contribution_per_year": 7258}


def with_answers(**facts) -> dict:
    body = sample_request()
    body["household"]["persons"][0]["earning_power"] = dict(EARNING_POWER)
    body["facts"] = {**body["facts"], **FACTS, **facts}
    return body


def req(body: dict) -> LifeBalanceSheetRequest:
    return LifeBalanceSheetRequest.model_validate(body)


# ===========================================================================
# The request hash
# ===========================================================================

def test_the_pins_cover_every_golden_case():
    assert sorted(GOLDEN_REQUEST_HASHES) == sorted(L.layer_b15_names()) and len(GOLDEN_REQUEST_HASHES) == 28


@pytest.mark.parametrize("name", sorted(GOLDEN_REQUEST_HASHES))
def test_a_golden_request_hashes_as_under_13(name):
    body = L.request_of(name)
    persons = (body.get("household") or {}).get("persons", [])
    assert not any("earning_power" in p for p in persons)
    assert not set(FACTS_ADDED_1_4) & set(body.get("facts") or {})
    assert request_hash(req(body)) == GOLDEN_REQUEST_HASHES[name]


def test_the_sample_request_hashes_as_before_and_its_key_moves_only_with_the_engine_version(monkeypatch):
    request = req(sample_request())
    assert request_hash(request) == SAMPLE_HASH
    new_key = idempotency_key(request, CORRECTED_1_5)
    monkeypatch.setattr(service, "ENGINE_VERSION", "lbs@1.3.0")
    assert idempotency_key(request, CORRECTED_1_5) == SAMPLE_KEY_13 != new_key


def test_a_new_field_stated_explicitly_as_null_hashes_as_absent():
    body = sample_request()
    body["household"]["persons"][0]["earning_power"] = None
    body["facts"] = {**body["facts"], **{name: None for name in FACTS_ADDED_1_4}}
    assert request_hash(req(body)) == SAMPLE_HASH


@pytest.mark.parametrize("name", FACTS_ADDED_1_4)
def test_each_new_fact_stated_is_a_new_request(name):
    body = sample_request()
    body["facts"][name] = FACTS[name]
    assert request_hash(req(body)) != SAMPLE_HASH


def test_the_earning_power_answers_stated_are_a_new_request():
    for field, value in EARNING_POWER.items():
        body = sample_request()
        body["household"]["persons"][0]["earning_power"] = {field: value}
        assert request_hash(req(body)) != SAMPLE_HASH, field
    body = sample_request()
    body["household"]["persons"][0]["earning_power"] = {}
    assert request_hash(req(body)) != SAMPLE_HASH
    body["facts"]["legal_documents"] = []
    stated_none = request_hash(req(body))
    body["facts"]["legal_documents"] = None
    assert stated_none != request_hash(req(body))


# ===========================================================================
# Validation
# ===========================================================================

def test_the_full_answers_are_accepted():
    r = req(with_answers())
    ep = r.household.persons[0].earning_power
    assert ep.education_status == "in_progress" and ep.health_work_capacity == 0.8 and ep.education_hours == "3–5"
    assert r.facts.amortisation_mode == "indirect" and r.facts.legal_documents == ("Testament", "Vorsorgeauftrag")


BAD_EARNING_POWER = [
    ("expected_full_pensum_income", -1), ("expected_full_pensum_income", float("inf")),
    ("education_status", "abgeschlossen"), ("education_end_year", 1999), ("education_end_year", 2101),
    ("education_hours", -2), ("education_hours", 200), ("education_hours", ""),
    ("education_budget_per_year", -100), ("health_work_capacity", 1.2), ("health_work_capacity", -0.1),
    ("responsibility", " "), ("sector", ""), ("surprise", 1),
]


@pytest.mark.parametrize("field,value", BAD_EARNING_POWER)
def test_out_of_range_earning_power_answers_are_refused(field, value):
    body = with_answers()
    body["household"]["persons"][0]["earning_power"][field] = value
    with pytest.raises(ValidationError):
        req(body)


BAD_FACTS = [
    ("stop_work_age", 39), ("stop_work_age", 76), ("stop_work_age", float("nan")),
    ("legal_documents", ["Testament", "Testament"]), ("legal_documents", [""]),
    ("mortgage_fixed_until", "bald"), ("amortisation_mode", "sometimes"), ("own_use_share", 1.5),
    ("own_use_share", -0.2), ("pillar3a_contribution_per_year", -1),
]


@pytest.mark.parametrize("field,value", BAD_FACTS)
def test_out_of_range_facts_are_refused(field, value):
    with pytest.raises(ValidationError):
        req(with_answers(**{field: value}))


def test_the_education_answers_must_agree():
    body = with_answers()
    ep = body["household"]["persons"][0]["earning_power"]
    ep.update(education_status="none", education_end_year=2028)
    with pytest.raises(ValidationError, match="no education but an education end year"):
        req(body)
    ep.update(education_status="in_progress", education_end_year=2020)
    with pytest.raises(ValidationError, match="before the sheet's year 2026"):
        req(body)
    ep.update(education_status="planned", education_end_year=2026)
    assert req(body).household.persons[0].earning_power.education_end_year == 2026


def test_health_withheld_covers_the_work_capacity():
    """K3: a withheld health cannot carry a stated work capacity, as it carries no H."""
    body = with_answers()
    body["household"]["persons"][0]["human_capital"]["health_withheld"] = True
    with pytest.raises(ValidationError, match="withheld as K3 data"):
        req(body)
    del body["household"]["persons"][0]["earning_power"]["health_work_capacity"]
    assert req(body).household.persons[0].earning_power.health_work_capacity is None


def test_earning_power_is_asked_of_adults_only():
    body = with_answers()
    body["household"]["persons"].append({"person_id": "kid", "kind": "dependant", "age": 9,
                                         "earning_power": {"education_status": "none"}})
    with pytest.raises(ValidationError, match="dependant"):
        req(body)


def test_the_responsibility_is_a_tier_of_the_calibration(client):
    from lbs import engine

    names = engine.responsibility_tiers(CORRECTED_1_5)
    assert set(names.values()) == {"ohne Kaderfunktion", "oberes und mittleres Kader", "topmanagement"}
    assert names["Keine Führungsfunktion"] == names["No management function"] == "ohne Kaderfunktion"
    assert engine.responsibility_tiers(SEED) == names
    for stated in ("topmanagement", "Oberes oder mittleres Kader", "Top management"):
        body = with_answers()
        body["household"]["persons"][0]["earning_power"]["responsibility"] = stated
        assert engine.earning_power_problems(req(body), CORRECTED_1_5) == ()
    body = with_answers()
    body["household"]["persons"][0]["earning_power"]["responsibility"] = "Chef"
    r = client.post("/run", json=body)
    assert r.status_code == 422 and "'Chef' is not a tier of the human-capital record" in r.text
    v = client.post("/validate", json=body).json()
    assert v["ok"] is False and "is not a tier" in v["problems"][0]


def test_the_api_refuses_out_of_range_values(client):
    body = with_answers(own_use_share=2)
    assert client.post("/run", json=body).status_code == 422
    body = with_answers()
    body["household"]["persons"][0]["earning_power"]["health_work_capacity"] = 3
    assert client.post("/run", json=body).status_code == 422


# ===========================================================================
# The sheet is unchanged
# ===========================================================================

def _body_of(sheet) -> dict:
    out = sheet.model_dump(mode="json")
    for name in ("artefact_id", "provenance"):
        out.pop(name)
    return out


def test_the_answers_change_nothing_on_the_sheet():
    plain, answered = build_sheet(req(sample_request()), CORRECTED_1_5), build_sheet(req(with_answers()),
                                                                                    CORRECTED_1_5)
    assert _body_of(plain) == _body_of(answered)
    assert plain.provenance.request_hash != answered.provenance.request_hash
    assert plain.artefact_id != answered.artefact_id
    hc = answered.human_capital[0]
    assert isinstance(hc.earning_power, NotAvailable) and "lbsim" in hc.earning_power.reason
    assert any(g.kind == "owned_by_another_engine" and g.input == "earning_power" and "lbsim" in g.reason
               for g in answered.gaps)


# ===========================================================================
# GET /artefacts/{id}/request (LBS-40)
# ===========================================================================

def test_the_request_of_a_sheet_is_read_back(client):
    for body in (sample_request(), with_answers()):
        accepted = client.post("/run", json=body).json()
        assert accepted["status"] == "succeeded"
        sheet = client.get(f"/artefacts/{accepted['artefact_id']}").json()
        r = client.get(f"/artefacts/{accepted['artefact_id']}/request")
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["artefact_id"] == accepted["artefact_id"]
        assert got["contract_version"] == "lbs-request@1.0.0"
        assert got["request_hash"] == sheet["provenance"]["request_hash"]
        assert request_hash(req(got["request"])) == got["request_hash"]
        assert got["request"]["client_ref"] == body["client_ref"]
    assert got["request"]["household"]["persons"][0]["earning_power"]["responsibility"] == "oberes und mittleres Kader"
    assert got["request"]["facts"]["stop_work_age"] == 63


def test_the_request_of_an_unknown_sheet_is_404(client):
    r = client.get("/artefacts/LBS-0000000000000000/request")
    assert r.status_code == 404 and "no life balance sheet" in r.text


def test_a_request_stored_before_the_new_fields_reads_back_with_its_hash():
    """A run stored by lbs@1.3.0 has no new field in its request_json; read back, it hashes as it was stored."""
    import json

    legacy = req(sample_request()).model_dump(mode="json")
    for p in legacy["household"]["persons"]:
        p.pop("earning_power")
    for name in FACTS_ADDED_1_4:
        legacy["facts"].pop(name)
    assert request_hash(LifeBalanceSheetRequest.model_validate_json(json.dumps(legacy))) == SAMPLE_HASH
