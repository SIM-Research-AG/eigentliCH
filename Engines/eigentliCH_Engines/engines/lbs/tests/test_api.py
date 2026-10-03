"""The HTTP surface: every standard endpoint and every additive one against a freshly provisioned store; runs
are idempotent; calibrations are append-only and a new version is how a record gets approved; the active
calibration (1.5.0, the owner's CHF inflation of 1.0 % on the nominal and real view, LBS-36) is the default and
the prototype's behaviour, 1.2.0, 1.3.0 and 1.4.0 stay selectable (LBS-23, LBS-24, LBS-35, LBS-38)."""

from __future__ import annotations

import pytest

from lbs.calibration import (APPROVED, CORRECTED, CORRECTED_1_3, CORRECTED_1_4, CORRECTED_1_5, SEED, calibration_hash,
                             with_approved)
from lbs.contracts import CONTRACT_VERSIONS

from .conftest import sample_request


@pytest.fixture(scope="module")
def run(client):
    r = client.post("/run", json=sample_request())
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["status"] == "succeeded", client.get(f"/runs/{accepted['run_id']}").json()["error"]
    return accepted


def test_standard_endpoints(client, run):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["engine_version"] == "lbs@1.4.0"
    meta = client.get("/meta").json()
    assert meta["contract_versions"] == CONTRACT_VERSIONS and meta["allowlist"]["ok"]
    assert meta["allowlist"]["packages"]["psycopg"]["admitted_by"].startswith("LBS-02")
    assert meta["calibration_version"] == "1.5.0" and meta["upstream"] == {}
    assert "password" not in str(meta["store"]).replace("password_set", "")
    contracts = client.get("/contracts").json()
    assert contracts["LifeBalanceSheetRequest"]["version"] == "lbs-request@1.0.0"
    assert contracts["LifeBalanceSheet"]["version"] == "lbs-balance-sheet@1.0.0"
    assert contracts["LifeBalanceSheet"]["direction"] == "out" and contracts["Mandate(pcp)"]["direction"] == "mirrored"
    cal = client.get("/calibration").json()
    assert cal["version"] == "1.5.0" and set(cal["records"]) >= {"ahv-pension", "bvg-projection"}
    assert cal["corrections"] == {"required_return_search_reaches_its_ceiling": True,
                                  "capacity_horizon_is_years_to_the_planned_age": True,
                                  "zero_income_is_a_stated_zero": True, "unstated_vessel_is_a_gap": True,
                                  "human_capital_is_never_free_wealth": True, "zero_mortgage_is_a_stated_zero": True,
                                  "contribution_is_split_by_goal_share": True}
    assert cal["real_view"]["inflation"]["CHF"]["annual_rate"] == 0.01
    status = client.get(f"/runs/{run['run_id']}").json()
    assert status["status"] == "succeeded" and status["provenance"]["calibration_version"] == "1.5.0"
    assert not any(g["input"] in ("ahv", "risk-profile") for g in status["gaps"])
    assert client.get(f"/artefacts/{run['artefact_id']}").status_code == 200
    assert any(r["run_id"] == run["run_id"] for r in client.get("/runs").json())


def test_the_sheet_and_its_views(client, run):
    aid = run["artefact_id"]
    s = client.get(f"/sheet/{aid}").json()
    assert s["client_ref"] == "sample-01" and s["notice"] == "Model-derived research output. Not investment advice."
    assert s["totals"]["net_worth"] == 330_000 and s["provenance"]["idempotency_key"] == run["idempotency_key"]
    assert s["provenance"]["request_hash"].startswith("REQ-") and s["provenance"]["calibration_hash"].startswith("CAL-")
    for view in ("grid", "human-capital", "pensions", "findings", "mandate", "gaps"):
        r = client.get(f"/sheet/{aid}/{view}")
        assert r.status_code == 200, view
        assert r.json()["notice"].endswith("Not investment advice.")
    mandate = client.get(f"/sheet/{aid}/mandate").json()["mandate_proposal"]
    assert mandate["shape"] == "pcp-mandate@1.0.0" and mandate["curve_unit"] == "annualised_log_return"
    assert client.get(f"/sheet/{aid}/nothing").status_code == 404


def test_rerunning_is_free_and_gives_the_same_artefact(client, run):
    again = client.post("/run", json=sample_request()).json()
    assert again["cached"] and again["artefact_id"] == run["artefact_id"] and again["run_id"] == run["run_id"]
    named = client.post("/run", json=sample_request(calibration_version="1.5.0")).json()
    assert named["cached"] and named["idempotency_key"] == run["idempotency_key"]


def test_a_changed_request_is_a_new_artefact(client, run):
    other = client.post("/run", json=sample_request(as_of="2026-09-29")).json()
    assert not other["cached"] and other["artefact_id"] != run["artefact_id"]


def test_validate_reports_gaps_without_storing(client):
    before = len(client.get("/runs").json())
    v = client.post("/validate", json=sample_request(client_ref="validate-only")).json()
    assert v["ok"] and v["calibration_version"] == "1.5.0" and v["sections"]["risk_profile"] == "available"
    assert not any(g["kind"] == "record_not_approved" for g in v["gaps"])
    old = client.post("/validate", json=sample_request(client_ref="validate-only", calibration_version="1.0.0")).json()
    assert old["ok"] and old["sections"]["risk_profile"].startswith("not available: record not approved")
    assert any(g["kind"] == "record_not_approved" for g in old["gaps"])
    assert len(client.get("/runs").json()) == before
    bad = client.post("/validate", json=sample_request(calibration_version="9.9.9")).json()
    assert not bad["ok"] and "no calibration" in bad["problems"][0]


def test_a_calibration_is_approved_by_a_new_version_never_in_place(client):
    proposal = with_approved(SEED, "ahv-pension", version="1.9.0", published_by="API Test", decided_on="2026-09-28")
    body = proposal.model_dump(mode="json")
    first = client.put("/calibration", json=body)
    assert first.status_code == 201
    assert client.put("/calibration", json=body).status_code == 200
    changed = {**body, "note": "same version, different content"}
    assert client.put("/calibration", json=changed).status_code == 409
    orphan = {**body, "version": "1.9.1", "parent_version": "0.0.9"}
    assert client.put("/calibration", json=orphan).status_code == 422
    records = client.get("/records", params={"version": "1.9.0"}).json()["records"]
    seeded = client.get("/records", params={"version": "1.0.0"}).json()["records"]
    assert records["ahv-pension"]["approved"] and not seeded["ahv-pension"]["approved"]
    r = client.post("/run", json=sample_request(calibration_version="1.9.0")).json()
    pensions = client.get(f"/sheet/{r['artefact_id']}/pensions").json()["pensions"][0]
    assert pensions["ahv"]["status"] == "available" and pensions["ahv"]["full_monthly"] > 0
    versions = {v["version"]: v["active"] for v in client.get("/calibration/versions").json()}
    assert versions == {"1.0.0": False, "1.1.0": False, "1.2.0": False, "1.3.0": False, "1.4.0": False,
                        "1.5.0": True, "1.9.0": False}


def test_the_owner_approval_is_seeded_and_the_reproduction_stays_selectable(client):
    """LBS-23: 1.1.0 approves ahv-pension and risk-profile (Nicolas, 29.09.2026); LBS-24: 1.2.0 corrects the
    quirks; LBS-28: 1.3.0 corrects three more; LBS-35: 1.4.0 adds the real view; LBS-38: 1.5.0 sets the CHF
    inflation to 1.0 % and is the default; 1.0.0 to 1.4.0 stay selectable by name."""
    default = client.get("/records").json()
    assert default["calibration_version"] == "1.5.0"
    for name in ("ahv-pension", "risk-profile"):
        rec = default["records"][name]
        assert rec["approved"] and rec["published_by"] == "Nicolas" and rec["decided_on"] == "2026-09-29"
    parents = {v["version"]: v["parent_version"] for v in client.get("/calibration/versions").json()}
    assert parents["1.1.0"] == "1.0.0" and parents["1.2.0"] == "1.1.0" and parents["1.3.0"] == "1.2.0"
    assert parents["1.4.0"] == "1.3.0" and parents["1.5.0"] == "1.4.0"
    assert client.get("/calibration", params={"version": "1.1.0"}).json()["corrections"] is None
    later = client.get("/calibration", params={"version": "1.2.0"}).json()["corrections"]
    assert {k: v for k, v in later.items() if v is not None} == {
        "required_return_search_reaches_its_ceiling": True, "capacity_horizon_is_years_to_the_planned_age": True,
        "zero_income_is_a_stated_zero": True, "unstated_vessel_is_a_gap": True}
    assert client.get("/calibration", params={"version": "1.3.0"}).json().get("real_view") is None
    assert client.get("/calibration", params={"version": "1.4.0"}).json()["real_view"]["inflation"]["CHF"][
        "annual_rate"] == 0.005
    for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"):
        r = client.post("/run", json=sample_request(calibration_version=version)).json()
        assert r["status"] == "succeeded"
        assert client.get(f"/sheet/{r['artefact_id']}").json()["calibration_version"] == version


def test_the_seed_keeps_its_stored_hash():
    """The corrections block is left out of the canonical form when absent, so 1.0.0, stored on 28.09.2026,
    keeps its bytes: a changed hash would stop the service at startup."""
    assert calibration_hash(SEED) == "CAL-2c0d67f4f820dfc9"


def test_the_stored_calibrations_keep_their_hashes():
    """1.1.0 and 1.2.0 were stored on 29.09.2026; the LBS-28 corrections, which 1.2.0 does not name, are left out
    of its canonical form, so both keep their bytes (LBS-30)."""
    assert calibration_hash(APPROVED) == "CAL-e69eb8fc77af48a3"
    assert calibration_hash(CORRECTED) == "CAL-6e23bd89792ac4dc"
    assert CORRECTED.contract_version == "lbs-calibration@1.1.0"


def test_13_keeps_its_stored_hash_and_14_is_pinned():
    """1.3.0 is stored as an lbs-calibration@1.2.0 payload; an absent real_view block is left out of the canonical
    form, so it keeps its bytes (LBS-35). 1.4.0 is pinned from its first build."""
    assert calibration_hash(CORRECTED_1_3) == "CAL-2fa18ff0a38495b5"
    assert CORRECTED_1_3.contract_version == "lbs-calibration@1.2.0"
    assert calibration_hash(CORRECTED_1_4) == "CAL-99a3654972f86773"
    assert CORRECTED_1_4.contract_version == "lbs-calibration@1.3.0"


def test_14_keeps_its_hash_and_15_is_pinned():
    """1.5.0 (LBS-38) changes only its own real_view block: 1.4.0 keeps CAL-99a3654972f86773, and 1.5.0 is pinned
    from its first build, on the same calibration contract."""
    assert calibration_hash(CORRECTED_1_4) == "CAL-99a3654972f86773"
    assert calibration_hash(CORRECTED_1_5) == "CAL-fdf122697c7aa04b"
    assert CORRECTED_1_5.contract_version == "lbs-calibration@1.3.0"


def test_a_request_without_the_new_field_hashes_as_before():
    """contribution_share is additive (LBS-29): a request that does not state it keeps the request hash lbs@1.1.0
    gave it, and lbs-request@1.0.0 stays the request's contract."""
    from lbs.contracts import LifeBalanceSheetRequest
    from lbs.service import request_hash

    assert request_hash(LifeBalanceSheetRequest.model_validate(sample_request())) == "REQ-d6000dfa05961ba6"


def test_a_request_without_the_real_view_fields_hashes_as_before():
    """amount_basis and contribution_indexed are additive (LBS-31): unstated, the hash is lbs@1.2.0's; stated,
    it is a new request."""
    from lbs.contracts import LifeBalanceSheetRequest
    from lbs.service import request_hash

    body = sample_request()
    assert request_hash(LifeBalanceSheetRequest.model_validate(body)) == "REQ-d6000dfa05961ba6"
    body["goals"][0]["amount_basis"] = "today"
    assert request_hash(LifeBalanceSheetRequest.model_validate(body)) != "REQ-d6000dfa05961ba6"
    body = sample_request(mandate={"goal_id": "home", "annual_contribution": 24000, "contribution_indexed": False})
    assert request_hash(LifeBalanceSheetRequest.model_validate(body)) != "REQ-d6000dfa05961ba6"


def test_the_real_view_fields_are_checked_at_the_boundary(client):
    body = sample_request()
    body["goals"][0]["amount_basis"] = "yesterday"
    assert client.post("/run", json=body).status_code == 422
    body["goals"][0]["amount_basis"] = "future"
    r = client.post("/run", json=body).json()
    assert r["status"] == "succeeded"
    sheet = client.get(f"/sheet/{r['artefact_id']}").json()
    assert sheet["real_view"]["goals"][0]["amount_basis"] == "future"
    assert sheet["mandate_proposal"]["basis"] == "nominal" and set(sheet["mandate_proposal"]["views"]) == {
        "nominal", "real"}


def test_contribution_shares_are_checked_at_the_boundary(client):
    body = sample_request()
    body["goals"][0]["contribution_share"] = 0.7
    body["goals"][1]["contribution_share"] = 0.4
    r = client.post("/run", json=body)
    assert r.status_code == 422 and "sum to at most 1" in r.text
    body["goals"][1]["contribution_share"] = 0.3
    assert client.post("/run", json=body).json()["status"] == "succeeded"
    body["goals"][1]["contribution_share"] = -0.1
    assert client.post("/run", json=body).status_code == 422


def test_a_request_breaking_its_contract_is_422(client):
    assert client.post("/run", json=sample_request(client_ref="someone@example.ch")).status_code == 422
    assert client.post("/run", json={"client_ref": "x", "as_of": "2026-09-28", "surprise": 1}).status_code == 422
    assert client.post("/run", json=sample_request(calibration_version="9.9.9")).status_code == 422


def test_unknown_ids_are_404(client):
    assert client.get("/artefacts/LBS-0000000000000000").status_code == 404
    assert client.get("/runs/RUN-0000000000000000").status_code == 404
    assert client.get("/calibration", params={"version": "7.7.7"}).status_code == 404


def test_the_testbench_is_served_in_development(client):
    """The bench draws its graphs as inline SVG in the page: no external script (owner, 03.10.2026)."""
    import re

    r = client.get("/")
    assert r.status_code == 200 and "/bench/candidates" in r.text
    assert not re.search(r"<script[^>]+src=", r.text) and "plotly" not in r.text.lower()
    assert "<svg" in r.text and "cdn" not in r.text.lower()


def test_the_bench_candidates_are_the_newest_sheet_per_client_with_a_readable_label(client):
    """LBS-42: ``GET /bench/candidates`` lists the newest sheet of each client, newest first, labelled from its stored
    request; never a client_ref, a person or goal id or a sheet id as the label; read-only."""
    case = "0123456789abcdef0123456789abcdef"
    couple = sample_request(client_ref=case, as_of="2026-09-30")
    couple["household"]["persons"] = list(couple["household"]["persons"]) + [
        {"person_id": "p2", "kind": "adult", "age": 38}, {"person_id": "k1", "kind": "dependant", "age": 6}]
    couple["facts"] = {"civil_status": "verheiratet", "canton": "Bern"}
    first = client.post("/run", json=couple).json()
    newer = client.post("/run", json={**couple, "as_of": "2026-10-01"}).json()
    assert first["status"] == newer["status"] == "succeeded" and first["artefact_id"] != newer["artefact_id"]
    runs_before = len(client.get("/runs", params={"limit": 500}).json())
    got = client.get("/bench/candidates").json()
    assert len(client.get("/runs", params={"limit": 500}).json()) == runs_before
    mine = [c for c in got if c["artefact_id"] in (first["artefact_id"], newer["artefact_id"])]
    assert [c["artefact_id"] for c in mine] == [newer["artefact_id"]]
    label = mine[0]["label"]
    assert label == "Couple, 40 and 38, one child · assets CHF 350k · goals: home, retirement · Bern · as of 1 Oct 2026"
    assert mine[0]["kind"] == "use case"
    sample = next(c for c in got if c["label"].startswith("Single adult, 40"))
    assert sample["kind"] == "bench or test"
    assert len({c["label"] for c in got}) == len(got)
    for c in got:
        assert case not in c["label"] and "LBS-" not in c["label"] and "sample-01" not in c["label"]
        assert not any(w in c["label"].split() for w in ("p1", "p2", "k1", "later"))
    assert client.get("/artefacts/" + mine[0]["artefact_id"] + "/request").json()["request"]["client_ref"] == case
