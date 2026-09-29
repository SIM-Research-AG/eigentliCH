"""API and store, against a real PostgreSQL server (no fallback) and the upstream engines served
from the frozen inputs through mock transports.

Needs the ``aggregation`` login role in database ``simtech`` (Engine Building Guide section 8,
provisioned by ``Projects/Engines/Instruments/store/provision.py``). Every module gets its own
throwaway schema, dropped afterwards.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

import httpx
import psycopg
import pytest

from aggregation.settings import load

from .conftest import INPUTS


def _reachable() -> str | None:
    db = load().database
    try:
        with psycopg.connect(db.conninfo(), connect_timeout=5):
            return None
    except Exception as exc:  # noqa: BLE001
        return (f"cannot reach PostgreSQL as {db.redacted_url()}: {exc}. Start it (docker compose up -d "
                "in Projects\\PostgreSQL) and provision the aggregation role (Guide section 8)")


REASON = _reachable()
if REASON:
    raise pytest.UsageError(REASON)


def _transport(path_to_file: dict[str, str]) -> httpx.MockTransport:
    bodies = {path: (INPUTS / name).read_bytes() for path, name in path_to_file.items()}

    def handle(request: httpx.Request) -> httpx.Response:
        body = bodies.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    return httpx.MockTransport(handle)


_IDS = json.loads((INPUTS / "source.json").read_text(encoding="utf-8"))["artefacts"]
MRS_ID, CYCLE_ID, MACRO_ID = _IDS["mrs"], _IDS["cycle"], _IDS["macrofield"]
REQUEST = {"mrs_artefact_id": MRS_ID, "cycle_artefact_id": CYCLE_ID, "macro_artefact_id": MACRO_ID}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from aggregation.api import create_app

    base = load()
    schema = f"t_{uuid.uuid4().hex[:12]}"
    settings = replace(base, database=replace(base.database, schema=schema))
    app = create_app(settings,
                     mrs_transport=_transport({f"/artefacts/{MRS_ID}": "mrs.json"}),
                     cycle_transport=_transport({f"/artefacts/{CYCLE_ID}": "cycle.json"}),
                     macrofield_transport=_transport({f"/artefacts/{MACRO_ID}": "macrofield.json"}))
    with TestClient(app) as c:
        yield c
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def test_health_meta_contracts(client):
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/meta").json()
    assert meta["allowlist"]["ok"] and meta["calibration_version"] == "1.2.0"
    assert set(meta["calibration_versions"]) >= {"1.0.0", "1.1.0", "1.2.0"}
    contracts = client.get("/contracts").json()
    assert contracts["Regime"]["version"] == "aggregation-regime@1.0.0"
    assert contracts["MarketRiskSignal(mrs)"]["direction"] == "in"


def test_run_is_idempotent_and_issues_the_regime_id(client):
    first = client.post("/run", json={**REQUEST, "optimism_scale": "rogue"}).json()
    assert first["status"] == "succeeded", client.get(f"/runs/{first['run_id']}").json()
    assert first["regime_id"].startswith("RGM-") and not first["cached"]
    again = client.post("/run", json={**REQUEST, "optimism_scale": "rogue"}).json()
    assert again["cached"] and again["regime_id"] == first["regime_id"]
    assert again["artefact_id"] == first["artefact_id"]
    other = client.post("/run", json={**REQUEST, "optimism_scale": "defensive"}).json()
    assert other["regime_id"] != first["regime_id"]

    status = client.get(f"/runs/{first['run_id']}").json()
    assert status["regime_id"] == first["regime_id"]
    assert any("one datafeed snapshot" in w for w in status["warnings"])
    assert client.get("/runs").json()[0]["run_id"] in {first["run_id"], other["run_id"]}


def test_regime_reads(client):
    run = client.post("/run", json=REQUEST).json()
    rid = run["regime_id"]
    regime = client.get(f"/regime/{rid}").json()
    assert regime["regime_id"] == rid and regime["optimism_scale"] == "default"
    assert client.get(f"/artefacts/{run['artefact_id']}").json()["regime_id"] == rid

    path = client.get(f"/regime/{rid}/path", params={"economy": "US"}).json()
    assert path["paths"][0]["code"] == "US" and path["paths"][0]["path"]

    dist = client.get(f"/regime/{rid}/distribution", params={"date": "2020-06"}).json()
    assert dist["date"] == "2020-06-30"
    us = next(d for d in dist["distributions"] if d["code"] == "US")
    assert len(us["distribution"]) == 25 and abs(sum(us["distribution"]) - 1.0) < 1e-12

    current = client.get(f"/regime/{rid}/current").json()
    assert {e["code"] for e in current["economies"]} >= {"US", "CH", "EU"}

    contrib = client.get(f"/regime/{rid}/contributions", params={"economy": "US", "date": "2020-06"}).json()
    total = [sum(c["contribution"][k] for c in contrib["contributions"].values() if c["contribution"])
             for k in range(25)]
    assert abs(sum(total) - 1.0) < 1e-12


def test_errors(client):
    assert client.get("/regime/RGM-0000000000000000").status_code == 404
    assert client.post("/run", json={**REQUEST, "calibration_version": "9.9.9"}).status_code == 422
    bad = client.post("/run", json={**REQUEST, "mrs_artefact_id": "MRS-missing"}).json()
    assert bad["status"] == "failed"
    assert "no artefact" in client.get(f"/runs/{bad['run_id']}").json()["error"]


def test_calibration_is_append_only(client):
    active = client.get("/calibration").json()
    assert active["version"] == "1.2.0"
    assert client.put("/calibration", json=active).status_code == 200            # identical: no-op
    changed = {**active, "note": "changed"}
    assert client.put("/calibration", json=changed).status_code == 409
    new = {**active, "version": "1.2.1", "parent_version": "1.2.0", "note": "test"}
    assert client.put("/calibration", json=new).status_code == 201


def test_model_card_rebuilds_the_published_regime(client):
    """GET /model: the card's blend of the stored components, moved by the stored shift, is the
    published distribution, so the steps shown are the ones the Regime was made from."""
    import numpy as np

    from aggregation.calibration import SEEDS
    from aggregation.engine import shift_distribution

    run = client.post("/run", json={**REQUEST, "optimism_scale": "default"}).json()
    assert run["status"] == "succeeded"
    r = client.get("/model")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["contract_version"] == "model-card@1.0.0"
    assert [s["key"] for s in card["steps"]] == ["tilts", "macro_layer", "blend", "optimism", "reading"]
    assert all(f.strip() for s in card["steps"] for f in s["formulas"])
    opt = next(s for s in card["steps"] if s["key"] == "optimism")["charts"][0]
    blend, published = (np.array(s["y"], dtype=float) for s in opt["series"])
    cal = next(c for c in SEEDS if c.version == card["calibration_version"])
    rebuilt = shift_distribution(blend, cal.optimism.shift("default"), cal.optimism.keep_tail)
    assert np.max(np.abs(rebuilt - published)) < 1e-12
    assert client.get("/model", params={"economy": "XX"}).status_code == 422


def test_scenarios_are_issued_stored_and_served_like_any_regime(client):
    """POST /scenario, GET /scenarios, GET /scenarios/policies, and the Regime reads on a scenario
    Regime (AGG-19 to AGG-22). The model card still reads the latest base run."""
    base = client.post("/run", json={**REQUEST, "optimism_scale": "default"}).json()
    assert base["status"] == "succeeded"
    bid = base["regime_id"]

    policies = client.get("/scenarios/policies").json()
    assert [p["policy"] for p in policies] == ["depression", "hyperinflation", "stagflation", "deferral"]
    assert all(p["label_en"] and p["label_de"] and p["description_en"] for p in policies)

    made = {}
    for p in ("depression", "hyperinflation", "stagflation", "deferral"):
        r = client.post("/scenario", json={"base_regime_id": bid, "policy": p})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"regime_id", "cached", "policy", "base_regime_id"}
        assert body["policy"] == p and body["base_regime_id"] == bid and body["regime_id"].startswith("RGM-")
        made[p] = body["regime_id"]
    again = client.post("/scenario", json={"base_regime_id": bid, "policy": "depression"}).json()
    assert again["cached"] and again["regime_id"] == made["depression"]
    assert len(set(made.values())) == 4

    listed = client.get("/scenarios", params={"base": bid}).json()
    assert [x["policy"] for x in listed] == ["depression", "hyperinflation", "stagflation", "deferral"]
    assert {x["regime_id"] for x in listed} == set(made.values())
    assert all(set(x) == {"regime_id", "policy", "base_regime_id", "created_at"} for x in listed)
    assert client.get("/scenarios", params={"base": "RGM-0000000000000000"}).json() == []

    rid = made["depression"]
    regime = client.get(f"/regime/{rid}").json()
    s = regime["provenance"]["scenario"]
    assert regime["contract_version"] == "aggregation-regime@1.0.0" and regime["regime_id"] == rid
    assert s["policy"] == "depression" and s["base_regime_id"] == bid and s["horizon_months"] == 60
    assert regime["dates"][-1] == s["scenario_date"] == regime["provenance"]["as_of"]
    assert "scenario" not in client.get(f"/regime/{bid}").json()["provenance"]

    current = client.get(f"/regime/{rid}/current").json()
    assert current["scenario"]["policy"] == "depression"
    assert all(e["date"] == s["scenario_date"] and e["state"] <= 6 for e in current["economies"])
    dist = client.get(f"/regime/{rid}/distribution").json()
    assert dist["date"] == s["scenario_date"]
    assert all(abs(sum(d["distribution"]) - 1.0) < 1e-12 for d in dist["distributions"] if d["distribution"])
    path = client.get(f"/regime/{rid}/path", params={"economy": "US"}).json()
    assert path["paths"][0]["path"][-1]["date"] == s["scenario_date"]
    projected = client.get(f"/regime/{rid}/contributions", params={"economy": "US"}).json()
    assert projected["projected"] and projected["contributions"] == {}
    history = client.get(f"/regime/{rid}/contributions", params={"economy": "US", "date": "2020-06"}).json()
    assert history["contributions"]
    art = client.get(f"/artefacts/{regime['artefact_id']}")
    assert art.status_code == 200 and art.json()["regime_id"] == rid

    assert client.post("/scenario", json={"base_regime_id": rid, "policy": "stagflation"}).status_code == 422
    assert client.post("/scenario", json={"base_regime_id": "RGM-0000000000000000",
                                          "policy": "stagflation"}).status_code == 404
    assert client.post("/scenario", json={"base_regime_id": bid, "policy": "boom"}).status_code == 422
    assert client.get("/meta").json()["store"]["counts"]["scenario"] == 4
    assert client.get("/model").status_code == 200                # scenarios are not runs
