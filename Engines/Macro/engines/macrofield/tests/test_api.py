"""The HTTP surface and the store, end to end, on a throwaway schema.

One module-scoped app: the snapshot is loaded once (about 46,000 observations) and one small
run (US, which calibrates, and PH, which is unavailable) is shared by the read tests.
"""

from __future__ import annotations

import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from macrofield import snapshot as snap
from macrofield.calibration import V1_0_0
from macrofield.contracts import Calibration, EconomyState, MacroState
from macrofield.engine import run_economy
from macrofield.service import Service
from macrofield.store import Store

from .conftest import RAW, temp_settings

#: The calibration config.yaml makes active; the read tests follow it.
ACTIVE = temp_settings().active_calibration


@pytest.fixture(scope="module")
def client(module_settings):
    from macrofield.api import create_app

    with TestClient(create_app(module_settings)) as c:
        c.app.state.service.load_snapshot(RAW)
        yield c


@pytest.fixture(scope="module")
def snapshot_id(client) -> str:
    return client.get("/snapshots").json()[-1]["snapshot_id"]


def wait(client, run_id: str, timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


@pytest.fixture(scope="module")
def finished(client, snapshot_id) -> dict:
    accepted = client.post("/run", json={"snapshot_id": snapshot_id, "economies": ["US", "PH"]})
    assert accepted.status_code == 202, accepted.text
    body = wait(client, accepted.json()["run_id"])
    assert body["status"] == "succeeded", body["error"]
    return body


# ---- standard endpoints -----------------------------------------------------

def test_health_and_meta(client):
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/meta").json()
    assert meta["allowlist"]["ok"] is True
    assert meta["calibration_version"] == ACTIVE == "1.5.0"  # TB-28, owner 29.09.2026
    assert meta["contract_versions"]["MacroState"] == "macrofield-state@1.2.0"   # pinned downstream
    assert "password" not in str(meta["store"]).replace("password_set", "")


def test_contracts_publish_a_schema_for_every_model(client):
    body = client.get("/contracts").json()
    assert {"MacroRunRequest", "MacroState", "Calibration", "DataNeed"} <= set(body)
    assert body["MacroRunRequest"]["direction"] == "in"


def test_run_produces_a_valid_artefact_with_full_provenance(client, finished, snapshot_id):
    artefact = MacroState.model_validate(
        client.get(f"/artefacts/{finished['artefact_id']}").json())
    assert artefact.provenance.snapshot_id == snapshot_id
    assert artefact.provenance.calibration_version == ACTIVE
    assert artefact.contract_version == "macrofield-state@1.2.0"
    assert artefact.provenance.resolution_policy == "stagflation"
    assert len(artefact.provenance.sources) == 106
    assert artefact.coverage.available == ("US", "PH")    # PH on the IMF debt axis
    assert "Not investment advice" in artefact.notice


def test_an_identical_request_is_answered_from_the_cache(client, finished, snapshot_id):
    again = client.post("/run", json={"snapshot_id": snapshot_id, "economies": ["US", "PH"]})
    assert again.status_code == 200
    assert again.json()["cached"] is True
    assert again.json()["artefact_id"] == finished["artefact_id"]


def test_unknown_snapshot_economy_and_run_are_refused(client, snapshot_id):
    assert client.post("/run", json={"snapshot_id": "SNP-nope"}).status_code == 422
    assert client.post("/run", json={"snapshot_id": snapshot_id,
                                     "economies": ["ZZ"]}).status_code == 422
    assert client.get("/runs/RUN-nope").status_code == 404
    assert client.get("/artefacts/MFS-nope").status_code == 404


def test_calibration_versions_are_append_only(client):
    current = Calibration.model_validate(client.get("/calibration").json())
    proposal = current.model_copy(update={"version": "9.1.0", "parent_version": ACTIVE,
                                          "credit_uplift": 1.0, "note": "test: no uplift"})
    body = proposal.model_dump(mode="json")
    assert client.put("/calibration", json=body).status_code == 201
    assert client.put("/calibration", json=body).status_code == 200
    body["capital_target"] = 0.8
    assert client.put("/calibration", json=body).status_code == 409
    assert client.get("/calibration").json()["version"] == ACTIVE    # active is unchanged


# ---- engine specific ----------------------------------------------------------

def test_state_reads(client, finished):
    aid = finished["artefact_id"]
    current = client.get(f"/state/{aid}/current").json()
    by_code = {e["code"]: e for e in current["economies"]}
    assert by_code["US"]["current"]["phase"] in (1, 2, 3, 4)
    assert by_code["PH"]["status"] == "ok"
    us = EconomyState.model_validate(client.get(f"/state/{aid}/economies/US").json())
    assert us.years[0] == 1972 and us.fit is not None
    assert client.get(f"/state/{aid}/economies/DE").status_code == 404


def test_data_need_marks_what_the_snapshot_lacks(client):
    rows = client.get("/data-need").json()["rows"]
    status = {(r["proposed_series_id"], r["country_or_scope"]): r["status"] for r in rows}
    assert status[("bis.total_credit", "US")] == "in_snapshot"
    assert status[("imf.PVD_LS", "PH")] == "in_snapshot"         # PH: IMF debt axis
    assert ("bis.total_credit", "PH") not in status              # no longer read for PH
    assert status[("pwt.cn", "EU:DEU")] == "in_snapshot"         # euro area from its members
    assert status[("imf.GGXCNL_NGDP", "JP")] == "in_snapshot"    # JP fiscal from the IMF
    assert status[("bbk.OU0308", "DE")] == "in_snapshot"         # Genreith's K for Germany


def test_default_projection_is_in_the_artefact_and_what_ifs_are_recomputed(client, finished):
    aid = finished["artefact_id"]
    us = EconomyState.model_validate(client.get(f"/state/{aid}/economies/US").json())
    assert us.projection.status == "ok"
    assert us.projection.years[0] == us.years[-1] + 1 and us.projection.years[-1] == 2080
    body = {"artefact_id": aid, "economy": "US", "horizon": 5,
            "stimulus": {"mode": "pulse", "base": 1.0, "target": 2.0, "start_year": 2026,
                         "end_year": 2027}}
    what_if = client.post("/project", json=body)
    assert what_if.status_code == 200, what_if.text
    assert what_if.json()["years"][-1] == us.years[-1] + 5
    assert what_if.json()["settings"]["stimulus"]["mode"] == "pulse"
    assert client.post("/project", json={**body, "economy": "PH"}).json()["status"] == "ok"
    bad = {**body, "stimulus": {"mode": "ramp", "target": 2.0, "start_year": 2027}}
    assert client.post("/project", json=bad).status_code == 422


# ---- store ----------------------------------------------------------------------

def test_snapshot_load_is_idempotent(client):
    again = client.app.state.service.load_snapshot(RAW)
    assert again["created"] is False


@pytest.mark.parametrize("table", ["observation", "calibration", "artefact", "snapshot"])
def test_append_only_tables_refuse_changes(module_settings, client, table):
    store = Store(module_settings.database)
    with pytest.raises(psycopg.errors.RaiseException):
        with store.session() as conn:
            conn.execute(f"DELETE FROM {table}")


def test_a_tampered_raw_file_is_refused(tmp_path):
    import shutil

    shutil.copytree(RAW, tmp_path / "raw")
    target = tmp_path / "raw" / "worldbank" / "USA" / "SP.POP.TOTL.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(snap.SnapshotError, match="does not match"):
        snap.load(tmp_path / "raw")


# ---- determinism ----------------------------------------------------------------------

def test_parallel_and_serial_runs_give_the_same_states(raw_observations):
    codes = ["CN", "EU"]
    specs = [V1_0_0.economy(c) for c in codes]
    obs = {c: raw_observations[c] for c in codes}
    serial = [run_economy(s, obs[s.code], V1_0_0) for s in specs]
    parallel_service = Service(temp_settings(max_workers=2), Store(temp_settings().database))
    parallel = parallel_service._states(specs, obs, V1_0_0)
    assert [s.model_dump_json() for s in serial] == [p.model_dump_json() for p in parallel]


# ---- the model card -----------------------------------------------------------

def test_model_card_explains_the_latest_run(client, finished):
    """GET /model reads the latest successful run; every figure is the artefact's own."""
    r = client.get("/model", params={"economy": "US"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["contract_version"] == "model-card@1.0.0"
    assert [s["key"] for s in card["steps"]] == ["assembly", "identities", "dynamics", "diagnostics",
                                                 "phases", "projection"]
    assert [o["code"] for o in card["economies"]] == ["US", "PH"], "the economies of the run"
    artefact_id = card["data"].split()[2]
    us = client.get(f"/state/{artefact_id}/economies/US").json()
    dynamics = next(s for s in card["steps"] if s["key"] == "dynamics")
    for chart, key in zip(dynamics["charts"], ("Y", "K_R", "K_I")):
        assert chart["x"] == us["years"]
        assert chart["series"][0]["y"] == us["observed"][key]
        assert chart["series"][1]["y"] == us["simulated"][key]
    assert len(dynamics["parameters"]) == len(us["fit"]["free_parameters"]) + 1
    assert all(f.strip() for s in card["steps"] for f in s["formulas"])


def test_model_card_refuses_an_economy_outside_the_run(client, finished):
    assert client.get("/model", params={"economy": "JP"}).status_code == 422


# ---- R-005: resolution policy, horizon to 2080 --------------------------------------

def test_the_resolution_policy_is_a_run_parameter_in_the_idempotency_key(client, finished, snapshot_id):
    service = client.app.state.service
    cal = service.calibration()
    key = service.idempotency_key(snapshot_id, ("US", "PH"), cal, "stagflation")
    assert key == finished["idempotency_key"]                      # the default policy
    assert service.idempotency_key(snapshot_id, ("US", "PH"), cal, "deferral") != key
    bad = client.post("/run", json={"snapshot_id": snapshot_id, "economies": ["US"],
                                    "resolution_policy": "bailout"})
    assert bad.status_code == 422
    old = client.post("/run", json={"snapshot_id": snapshot_id, "economies": ["US"],
                                    "calibration_version": "1.3.0", "resolution_policy": "deferral"})
    assert old.status_code == 422 and "no resolution policies" in old.text


def test_project_takes_a_policy_and_a_horizon_year(client, finished):
    aid = finished["artefact_id"]
    base = {"artefact_id": aid, "economy": "US"}
    runs = {}
    for policy in ("depression", "hyperinflation", "stagflation", "deferral"):
        r = client.post("/project", json={**base, "resolution_policy": policy})
        assert r.status_code == 200, r.text
        runs[policy] = r.json()
        assert runs[policy]["resolution_policy"] == policy and runs[policy]["years"][-1] == 2080
        assert max(runs[policy]["saturation"]) <= 5.5
        assert {s["name"] for s in runs[policy]["scenarios"]} == {
            "depression", "hyperinflation", "stagflation", "deferral"}
    short = client.post("/project", json={**base, "horizon_until": 2039}).json()
    assert short["years"][-1] == 2039
    assert client.post("/project", json={**base, "resolution_policy": "bailout"}).status_code == 422
