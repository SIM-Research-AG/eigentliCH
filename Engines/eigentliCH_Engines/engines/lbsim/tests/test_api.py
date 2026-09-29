"""The HTTP surface (spec 3.7) against a throwaway schema and the stand-in upstream engines: every endpoint, the
idempotency of 3.9, the outlook states, supersede and cancel, and each refusal with its status and a plain
sentence."""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from stub import Stub

from lbsim.api import create_app
from lbsim.clients import Upstream
from lbsim.settings import load
from lbsim.store import Store

CASE = "lbsim-sample"


def temp_settings():
    s = load()
    return replace(s, database=replace(s.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


@pytest.fixture(scope="module")
def world():
    settings = temp_settings()
    stub = Stub((CASE, "lbsim-couple", "db-02"))
    app = create_app(settings, Upstream.from_config(settings.upstream, transport=stub.transport()))
    with TestClient(app) as client:
        yield client, stub, settings
    schema = settings.database.schema
    assert schema.startswith("t_")
    Store(settings.database).drop_schema()


def body(stub: Stub, name: str = CASE, **over):
    sid = stub.sheet_id(name)
    out = {"client_ref": stub.sheets[sid]["client_ref"], "life_balance_sheet_id": sid,
           "allocation_id": stub.allocation_id, "n_paths": 300}
    out.update(over)
    return out


def plain_sentence(detail: str) -> None:
    assert isinstance(detail, str) and detail and "Traceback" not in detail
    assert detail.rstrip().endswith((".", ")")), detail


# --- standard endpoints ------------------------------------------------------------------------------------

def test_health_meta_contracts(world):
    client, _, settings = world
    assert client.get("/health").json()["engine"] == "lbsim"
    meta = client.get("/meta").json()
    assert meta["allowlist"]["ok"] and meta["allowlist"]["packages"]["casadi"]["admitted_by"].startswith("LBSIM-02")
    assert meta["store"]["schema"] == settings.database.schema and meta["store"]["password_set"] is True
    assert "password" not in str(meta["store"]["url"]).replace("password_set", "")
    contracts = client.get("/contracts").json()
    assert contracts["LifeBalancePaths"]["version"] == "lbsim-paths@1.0.0"
    assert contracts["upstream"]["contracts"]["fmre:return_set"] == "rs@1.0.0"


def test_the_test_bench_is_served_at_the_root(world):
    client, _, _ = world
    r = client.get("/")
    assert r.status_code == 200 and "lbsim test bench" in r.text and "/outlook?client_ref=" in r.text
    assert "LBS-1" not in r.text and "RGM-" not in r.text


def test_calibration_endpoints(world):
    client, _, _ = world
    versions = client.get("/calibration/versions").json()
    assert [v["version"] for v in versions] == ["1.0.0", "1.1.0", "1.2.0"] and versions[2]["active"]
    cal = client.get("/calibration").json()
    assert cal["version"] == "1.2.0"
    assert client.get("/calibration", params={"version": "9.9.9"}).status_code == 404
    again = client.put("/calibration", json=cal)
    assert again.status_code == 200
    changed = copy.deepcopy(cal)
    changed["retirement"]["withdrawal_rate"] = 0.04
    r = client.put("/calibration", json=changed)
    assert r.status_code == 409
    plain_sentence(r.json()["detail"])
    changed["version"] = "1.1.1"
    changed["parent_version"] = "1.2.0"
    assert client.put("/calibration", json=changed).status_code == 201


# --- POST /run and the reads -------------------------------------------------------------------------------

def test_run_makes_findings_and_paths_and_queues_the_plan(world):
    client, stub, _ = world
    r = client.post("/run", json=body(stub))
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["kind"] == "outlook" and acc["status"] == "succeeded" and not acc["cached"]
    assert acc["findings_artefact_id"].startswith("LSF-") and acc["paths_artefact_id"].startswith("LSP-")
    assert acc["plan_run_id"].startswith("RUN-") and acc["not_made"] == []
    again = client.post("/run", json=body(stub)).json()
    assert again["cached"] is True and again["paths_artefact_id"] == acc["paths_artefact_id"]
    assert again["plan_run_id"] == acc["plan_run_id"] and again["idempotency_key"] == acc["idempotency_key"]

    paths = client.get(f"/paths/{acc['paths_artefact_id']}").json()
    assert paths["n_paths"] == 300 and paths["seed"] == 20260929
    typed = client.get(f"/artefacts/{acc['paths_artefact_id']}").json()
    assert typed == paths
    findings = client.get(f"/findings/{acc['findings_artefact_id']}").json()
    assert findings["artefact_id"] == paths["findings_artefact_id"]
    assert client.get(f"/findings/{acc['paths_artefact_id']}").status_code == 404
    fan = client.get(f"/paths/{acc['paths_artefact_id']}/fan", params={"basis": "real"}).json()
    assert fan["series"] == "deposit_eligible" and fan["goal"]["line"] == "solid"
    assert client.get(f"/paths/{acc['paths_artefact_id']}/fan", params={"regime": "boom"}).status_code == 404
    assert client.get(f"/paths/{acc['paths_artefact_id']}/fan", params={"basis": "gold"}).status_code == 422

    run = client.get(f"/runs/{acc['run_id']}").json()
    assert run["kind"] == "outlook" and run["status"] == "succeeded"
    assert set(run["request"]) == {"request", "resolved"} and run["artefact_ids"] == [
        acc["findings_artefact_id"], acc["paths_artefact_id"]]
    plan = client.get(f"/runs/{acc['plan_run_id']}").json()
    assert plan["kind"] == "plan" and plan["status"] == "queued" and plan["budget_s"] == 7200
    assert plan["requested_by"] == {"kind": "system", "ref": "run"}
    assert set(plan["request"]) == {"paths_artefact_id", "findings_artefact_id", "seed", "calibration_version"}
    listed = client.get("/runs", params={"client_ref": body(stub)["client_ref"], "kind": "plan"}).json()
    assert acc["plan_run_id"] in [x["run_id"] for x in listed]
    other_seed = client.post("/run", json=body(stub, seed=99)).json()
    assert other_seed["idempotency_key"] != acc["idempotency_key"]
    assert client.get(f"/runs/{acc['plan_run_id']}").json()["failure_kind"] == "superseded"
    assert client.get("/runs/RUN-0000000000000000").status_code == 404
    assert client.get("/artefacts/XYZ-0000000000000000").status_code == 404


def test_the_request_holds_ids_and_options_only(world):
    client, stub, _ = world
    acc = client.post("/run", json=body(stub)).json()
    run = client.get(f"/runs/{acc['run_id']}").json()
    text = str(run["request"])
    assert "spend_now" not in text and "W_L" not in text and "stated_gross_income" not in text


def test_outlook_states(world):
    client, stub, _ = world
    b = body(stub, "lbsim-couple", allocation_id=None)
    stub.edit("allocation", lambda a: {**a, "client": b["client_ref"]})
    try:
        acc = client.post("/run", json=b).json()
        assert acc["paths_artefact_id"] is None
        assert [n["reason"] for n in acc["not_made"]] == ["no_allocation", "no_allocation"]
        o = client.get("/outlook", params={"client_ref": b["client_ref"]}).json()
        assert o["plan"]["state"] == "waiting_for_allocation" and o["findings"] is not None and o["paths"] is None
        acc = client.post("/run", json={**b, "allocation_id": stub.allocation_id, "optimise": "no"}).json()
        assert [n["reason"] for n in acc["not_made"]] == ["not_requested"] and acc["plan_run_id"] is None
        o = client.get("/outlook", params={"client_ref": b["client_ref"]}).json()
        assert o["plan"]["state"] == "not_requested" and o["paths"]["artefact_id"] == acc["paths_artefact_id"]
        acc = client.post("/run", json={**b, "allocation_id": stub.allocation_id}).json()
        o = client.get("/outlook", params={"client_ref": b["client_ref"],
                                           "life_balance_sheet_id": b["life_balance_sheet_id"]}).json()
        assert o["plan"]["state"] == "calculating" and o["plan"]["budget_s"] == 7200
        assert o["plan"]["run"]["run_id"] == acc["plan_run_id"]
    finally:
        stub.edit("allocation", lambda a: {**a, "client": stub.sheets[stub.sheet_id(CASE)]["client_ref"]})
    assert client.get("/outlook", params={"client_ref": "nobody"}).status_code == 404


def test_optimise_is_idempotent_and_cancel_stops_a_queued_plan(world):
    client, stub, _ = world
    acc = client.post("/run", json=body(stub, optimise="no", seed=5)).json()
    req = {"paths_artefact_id": acc["paths_artefact_id"], "requested_by": {"kind": "curator", "ref": "cur-7"}}
    one = client.post("/optimise", json=req).json()
    assert one["kind"] == "plan" and one["status"] == "queued" and not one["cached"]
    two = client.post("/optimise", json=req).json()
    assert two["run_id"] == one["run_id"] and two["idempotency_key"] == one["idempotency_key"]
    other = client.post("/optimise", json={**req, "seed": 1234}).json()
    assert other["idempotency_key"] != one["idempotency_key"]
    status = client.get(f"/runs/{one['run_id']}").json()
    assert status["requested_by"] == {"kind": "curator", "ref": "cur-7"}
    cancelled = client.post(f"/runs/{one['run_id']}/cancel").json()
    assert cancelled["status"] == "failed" and cancelled["failure_kind"] == "cancelled"
    r = client.post(f"/runs/{one['run_id']}/cancel")
    assert r.status_code == 409
    plain_sentence(r.json()["detail"])
    r = client.post(f"/runs/{acc['run_id']}/cancel")
    assert r.status_code == 409 and "plan" in r.json()["detail"]
    assert client.post("/optimise", json={**req, "paths_artefact_id": "LSP-0000000000000000"}).status_code == 404


def test_a_newer_sheet_supersedes_a_queued_plan(world):
    client, stub, _ = world
    first = client.post("/run", json=body(stub, seed=777)).json()
    assert client.get(f"/runs/{first['plan_run_id']}").json()["status"] == "queued"
    newer = client.post("/run", json=body(stub, seed=778)).json()
    old = client.get(f"/runs/{first['plan_run_id']}").json()
    assert old["status"] == "failed" and old["failure_kind"] == "superseded"
    assert client.get(f"/runs/{newer['plan_run_id']}").json()["status"] == "queued"


def test_validate_stores_nothing(world):
    client, stub, _ = world
    before = client.get("/meta").json()["store"]["counts"]
    v = client.post("/validate", json=body(stub, "db-02", allocation_id=None)).json()
    assert v["contract_version"] == "lbsim-validation@1.0.0" and v["gate"] is not None
    assert [n["reason"] for n in v["not_made"]] == ["no_allocation"]
    assert all(u["missing"] or u["answered_by"] for u in v["unchecked"])
    bad = client.post("/validate", json=body(stub, calibration_version="9.9.9")).json()
    assert bad["ok"] is False and bad["problems"]
    assert client.get("/meta").json()["store"]["counts"] == before


# --- the refusals of 3.7 -------------------------------------------------------------------------------------

def refused(client, payload, status, pattern):
    r = client.post("/run", json=payload)
    assert r.status_code == status, r.text
    detail = r.json()["detail"]
    plain_sentence(detail)
    assert re.search(pattern, detail, re.I), detail
    return detail


def test_404_unknown_sheet_and_allocation(world):
    client, stub, _ = world
    refused(client, {**body(stub), "life_balance_sheet_id": "LBS-0000000000000000"}, 404, "Life Balance Sheet")
    refused(client, {**body(stub), "allocation_id": "PCP-0000000000000000"}, 404, "allocation")


def test_409_client_mismatch(world):
    client, stub, _ = world
    refused(client, {**body(stub), "client_ref": "someone-else"}, 409, "another client")
    stub.edit("allocation", lambda a: {**a, "client": "bench"})
    try:
        refused(client, body(stub), 409, "allocation belongs to another client")
    finally:
        stub.edit("allocation", lambda a: {**a, "client": stub.sheets[stub.sheet_id(CASE)]["client_ref"]})


def _edited(stub, key, fn):
    saved = copy.deepcopy(stub.data[key])
    stub.edit(key, fn)
    return saved


def test_409_fmre_moved_on(world):
    client, stub, _ = world
    saved = _edited(stub, "return_set_base", lambda rs: {**rs, "return_set_id": "RS-0000000000000000"})
    try:
        refused(client, body(stub), 409, "moved since this allocation")
    finally:
        stub.data["return_set_base"] = saved

    heaviest = max(stub.data["allocation"]["instruments"], key=lambda i: i["raw_weight"])["instrument_id"]

    def bump(rs):
        rs = copy.deepcopy(rs)
        prof = next(p for p in rs["instrument_profiles"] if p["key"] == heaviest)
        prof["states"][0]["value"] += 1e-6
        return rs
    saved = _edited(stub, "return_set_base", bump)
    try:
        refused(client, body(stub), 409, "moved since this allocation")
    finally:
        stub.data["return_set_base"] = saved

    def other_ipt(rs):
        rs = copy.deepcopy(rs)
        rs["provenance"]["inflation_pass_through"]["calibration_version"] = "ipt@1.0.0"
        return rs
    saved = _edited(stub, "return_set_depression", other_ipt)
    try:
        refused(client, body(stub), 409, "pass-through")
    finally:
        stub.data["return_set_depression"] = saved


def test_422_currency_fallback_scenario_base_and_invalid(world):
    client, stub, _ = world
    saved = _edited(stub, "allocation", lambda a: {**a, "currency": "EUR"})
    try:
        refused(client, body(stub), 422, "Swiss francs only")
    finally:
        stub.data["allocation"] = saved
    saved = _edited(stub, "allocation", lambda a: {k: v for k, v in a.items() if k != "currency"})
    try:
        refused(client, body(stub), 422, "does not state its currency")
    finally:
        stub.data["allocation"] = saved

    def fallback(a):
        a = copy.deepcopy(a)
        a["provenance"]["hard_currency_fallback"] = {"from": "CHF", "to": "USD", "states": [1], "reason": "band"}
        return a
    saved = _edited(stub, "allocation", fallback)
    try:
        refused(client, body(stub), 422, "fell back")
    finally:
        stub.data["allocation"] = saved

    def on_scenario(reg):
        reg = copy.deepcopy(reg)
        reg["provenance"]["scenario"] = {"policy": "depression", "base_regime_id": "RGM-x", "horizon_months": 60}
        return reg
    saved = _edited(stub, "regime_base", on_scenario)
    try:
        refused(client, body(stub), 422, "scenario Regime")
    finally:
        stub.data["regime_base"] = saved

    def not_computable(infl):
        infl = copy.deepcopy(infl)
        infl["states"][3]["label"] = "not_computable"
        return infl
    saved = _edited(stub, "inflation_hyperinflation", not_computable)
    try:
        refused(client, body(stub), 422, "cannot compute Swiss inflation")
    finally:
        stub.data["inflation_hyperinflation"] = saved

    r = client.post("/run", json={**body(stub), "n_paths": 5})
    assert r.status_code == 422
    plain_sentence(r.json()["detail"])
    refused(client, {**body(stub), "calibration_version": "9.9.9"}, 422, "no calibration")
    refused(client, {**body(stub), "income_path": "education"}, 422, "does not exist")


def test_503_upstream_down(world):
    client, stub, _ = world
    stub.down.add("fmre")
    try:
        refused(client, body(stub), 503, "does not answer")
    finally:
        stub.down.discard("fmre")
    stub.down.add("lbs")
    try:
        refused(client, body(stub), 503, "lbs")
    finally:
        stub.down.discard("lbs")
