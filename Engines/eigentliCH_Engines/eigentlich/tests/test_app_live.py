"""Opt-in: the app against the real engines at the configured URLs (lbs 8013, lbsim 8014, chatbot 8016, report 8015).

    set EIGENTLICH_LIVE=1 && ..\\.venv\\Scripts\\python -m pytest tests\\test_app_live.py

Runs on a throwaway schema like every other test. Each engine part is skipped, with the reason, when that
engine does not answer ``/health``; the chatbot and report parts can take minutes (spark7)."""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from eigentlich import seed as seeding
from eigentlich.api import create_app

from .appkit import app_settings

pytestmark = pytest.mark.skipif(os.environ.get("EIGENTLICH_LIVE") != "1", reason="set EIGENTLICH_LIVE=1 to run")


def _up(url: str) -> bool:
    try:
        return httpx.get(url + "/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def live(settings, st):
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
    cfg = app_settings(settings)
    with TestClient(create_app(cfg)) as http:
        cid = http.post("/api/clients", json={"display_name": "Live", "age_at_registration": 42}).json()["id"]
        http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Lohn",
                                                         "magnitude": 110000, "magnitude_unit": "chf_per_year"})
        http.post(f"/api/clients/{cid}/positions", json={"role": "stabilisation", "capital_type": "financial",
                                                         "label": "Sparkonto", "magnitude": 60000, "magnitude_unit": "chf",
                                                         "stock_kind": "asset", "liquidity": "immediate", "vessel": "free"})
        http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": []})
        yield {"http": http, "cid": cid, "cfg": cfg}


def test_live_lbs(live):
    if not _up(live["cfg"].lbs_url):
        pytest.skip(f"lbs not reachable at {live['cfg'].lbs_url}")
    http, cid = live["http"], live["cid"]
    r = http.post(f"/api/clients/{cid}/balance-sheet")
    assert r.status_code == 200, r.text
    sheet = r.json()["sheet"]
    assert len(sheet["grid"]) == 8 and sheet["totals"]["financial_assets"] == 60000


def test_live_lbsim(live):
    """lbsim on the sheet just made (EIG-66): no allocation for this client, so the findings come alone and the plan
    waits for an allocation; the page names no id."""
    if not (_up(live["cfg"].lbsim_url) and _up(live["cfg"].lbs_url)):
        pytest.skip(f"lbsim or lbs not reachable ({live['cfg'].lbsim_url})")
    http, cid = live["http"], live["cid"]
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    r = http.post(f"/api/clients/{cid}/outlook")
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["available"] and page["earning_power"] and page["paths"] is None
    assert page["plan"]["state"] == "waiting_for_allocation"
    import re
    assert not re.search(r"\b(LBS|LSF|LSP|LSO|RUN|PCP)-[0-9a-f]", r.text)


def test_live_chatbot(live):
    if not _up(live["cfg"].chatbot_url):
        pytest.skip(f"chatbot not reachable at {live['cfg'].chatbot_url}")
    http, cid = live["http"], live["cid"]
    tid = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Was ist die Säule 3a?"}).json()["thread_id"]
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    if t["draft"] and t["draft"]["state"] == "failed":
        pytest.fail(f"the chatbot answered, the draft failed: {t['draft']['error']}")
    ai = t["messages"][-1]
    assert ai["author_kind"] == "spark7" and ai["chatbot_artefact_id"] and ai["model"]


def test_live_report(live):
    if not (_up(live["cfg"].report_url) and _up(live["cfg"].lbs_url)):
        pytest.skip("report or lbs not reachable")
    http, cid = live["http"], live["cid"]
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"}).json()
    assert r["job"]["state"] == "done", r["job"]
    rep = http.get(f"/api/clients/{cid}/reports").json()[0]["reports"][0]
    assert "<" in http.get(f"/api/clients/{cid}/report/{rep['id']}/html").text
