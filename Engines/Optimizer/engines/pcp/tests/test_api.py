"""The HTTP surface: every standard endpoint and every additive one returns 200 against a freshly
provisioned store; runs are idempotent; the Allocation carries what the engine page says it carries."""

from __future__ import annotations

import pytest

from pcp.contracts import CONTRACT_VERSIONS

from .conftest import REGIME_ID, run_body


@pytest.fixture(scope="module")
def run(client):
    from .conftest import instruments

    body = {"client": "api", "name": "balanced", "currency": "CHF", "curve_unit": "annualised_log_return",
            "target_curve": [0.02] * 25, "universe": sorted(i["instrument_id"] for i in instruments()),
            "max_single_position": 0.15,
            "bounds": {"role": {"Gain": {"lower": 0.2, "upper": 0.6}}}, "bound_sources": {"role": "derived"},
            "regime_weights": {"CH": 0.5, "EU": 0.3, "US": 0.2}}
    r = client.post("/run", json=run_body(body))
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["status"] == "succeeded", client.get(f"/runs/{accepted['run_id']}").json()["error"]
    return {"body": body, "accepted": accepted}


def test_standard_endpoints(client, run):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["engine_version"] == "pcp@1.2.0"
    meta = client.get("/meta").json()
    assert meta["contract_versions"] == CONTRACT_VERSIONS and meta["allowlist"]["ok"]
    assert meta["calibration_version"] == "1.1.0" and set(meta["calibration_versions"]) == {"1.0.0", "1.1.0"}
    contracts = client.get("/contracts").json()
    assert contracts["Allocation"]["version"] == "pcp-allocation@1.0.0"
    assert contracts["Mandate"]["direction"] == "in" and contracts["Allocation"]["direction"] == "out"
    assert client.get("/calibration").json()["version"] == "1.1.0"
    assert client.get("/calibration", params={"version": "1.0.0"}).json()["budget_check"]["mode"] == "rounded"
    status = client.get(f"/runs/{run['accepted']['run_id']}").json()
    assert status["status"] == "succeeded" and status["provenance"]["regime_id"] == REGIME_ID
    assert client.get(f"/artefacts/{run['accepted']['artefact_id']}").status_code == 200
    assert any(r["run_id"] == run["accepted"]["run_id"] for r in client.get("/runs").json())


def test_the_allocation_and_its_views(client, run):
    aid = run["accepted"]["artefact_id"]
    a = client.get(f"/allocation/{aid}").json()
    assert a["regime_id"] == REGIME_ID and a["release_state"] == "unreleased"
    assert a["budget_met"] and abs(a["raw_weight_sum"] - 1) <= 1e-6
    assert abs(sum(i["weight"] for i in a["instruments"]) - 1) < 1e-12
    assert all("raw_weight" in i and "coverage" in i for i in a["instruments"])
    assert a["provenance"]["regime_weights"] == {"CH": 0.5, "EU": 0.3, "US": 0.2}
    assert a["provenance"]["snapshot_id"] and a["provenance"]["as_of"] and a["date"] == "2026-01-31"
    assert a["notice"].endswith("Not investment advice.")
    m = client.get(f"/allocation/{aid}/map").json()
    assert m["roles"] == ["Gain", "Income", "Stabilisation", "Protection"] and len(m["grid"]) == 4
    roles = client.get(f"/allocation/{aid}/roles").json()
    assert roles["bounds"]["Gain"] == {"lower": 0.2, "upper": 0.6}
    assert 0.2 - 1e-9 <= roles["weights_by_role"]["Gain"] <= 0.6 + 1e-9
    d = client.get(f"/allocation/{aid}/diagnostics").json()
    assert d["solver_method"] in ("SLSQP", "trust-constr") and d["constraint_rows"] == 75
    assert d["objective"] <= d["objective_floor"] and d["success"]


def test_constraints_endpoint(client):
    c = client.get("/constraints").json()
    assert c["n_rows"] == 75 and c["starts"]["esg"] == 57 and c["rows"][56]["dimension"] == "esg"


def test_rerunning_is_free_and_gives_the_same_artefact(client, run):
    again = client.post("/run", json=run_body(run["body"])).json()
    assert again["cached"] and again["artefact_id"] == run["accepted"]["artefact_id"]
    assert again["idempotency_key"] == run["accepted"]["idempotency_key"]


def test_the_speed_mode_enters_the_idempotency_key(client, run):
    fast = client.post("/run", json=run_body(run["body"], speed_mode="fast")).json()
    assert fast["idempotency_key"] != run["accepted"]["idempotency_key"]


def test_validate_passes_a_feasible_mandate(client, run):
    v = client.post("/validate", json=run_body(run["body"])).json()
    assert v["ok"] and v["constraint_rows"] == 75 and v["date"] == "2026-01-31"


def test_a_return_set_id_fmre_does_not_serve_is_refused(client, run):
    v = client.post("/validate", json=run_body(run["body"], return_set_id="RS-0000000000000000")).json()
    assert not v["ok"] and "serves ReturnSet" in v["problems"][0]


def test_a_curve_in_another_unit_is_refused(client, run):
    body = {**run["body"], "curve_unit": "annualised_decimal"}
    v = client.post("/validate", json=run_body(body)).json()
    assert not v["ok"] and "unit" in v["problems"][0]


def test_an_unknown_bucket_label_is_refused(client, run):
    body = {**run["body"], "bounds": {"role": {"Growth": {"lower": 0.1, "upper": 0.5}}}}
    v = client.post("/validate", json=run_body(body)).json()
    assert not v["ok"] and "not in the role vocabulary" in v["problems"][0]


def test_an_unknown_regime_is_refused(client, run):
    v = client.post("/validate", json=run_body(run["body"], regime_id="RGM-ffffffffffffffff")).json()
    assert not v["ok"] and "no regime" in v["problems"][0]


def test_a_mandate_breaking_its_contract_is_422(client, run):
    body = {**run["body"], "target_curve": [0.02] * 24}
    assert client.post("/run", json=run_body(body)).status_code == 422


def test_unknown_artefact_is_404(client):
    assert client.get("/allocation/PCP-0000000000000000").status_code == 404
