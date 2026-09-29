"""The one live test: the real spark7, with the token from the family .env. Opt-in:

    python -m pytest -m live -s

The whole engine (real settings, a throwaway schema, upstream doubles on the frozen artefacts) writes a
German report with prose against the real server, and prints the model and the timings so the run can be
reported.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

import pytest

from report.settings import load

from .conftest import Upstream, drop, request_body

pytestmark = pytest.mark.live


def test_live_spark7_writes_checked_prose():
    from fastapi.testclient import TestClient

    from report.api import create_app

    base = load(overrides={"model": {"warmup": {"enabled": False}}})
    if len(base.env) < 2 or not all(base.env.values()):
        pytest.fail("the spark7 token is not set: SPARK7_CLIENT_ID and SPARK7_CLIENT_SECRET in the family .env")
    settings = replace(base, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))
    try:
        with TestClient(create_app(settings, Upstream().transports())) as client:
            probe = client.get("/model").json()
            assert probe["reachable"] and probe["serves_configured_model"], probe
            t0 = time.perf_counter()
            r = client.post("/report", json=request_body(display_facts=[
                {"key": "name", "label": "Kundin", "value": f"Live {uuid.uuid4().hex[:6]}", "source": "live test"}]))
            wall = time.perf_counter() - t0
            assert r.status_code == 200, r.text
            rep = r.json()
            prose = [s for s in rep["sections"] if s["prose_status"] not in ("no_slot",)]
            print(f"\nlive spark7: model {rep['provenance']['model']['model']}, {len(prose)} prose sections in "
                  f"{wall:.1f} s, probe {probe['ms']:.0f} ms")
            for s in prose:
                print(f"  {s['key']}: {s['prose_status']} after {s['prose_attempts']} draft(s) {s['unverified_numbers']}")
            assert rep["complete"], rep["warnings"]
            assert all(s["prose_status"] in ("verified", "flagged", "rejected") for s in prose)
            assert sum(s["prose_status"] == "verified" for s in prose) >= len(prose) - 1
            assert all(s["unverified_numbers"] == [] for s in prose if s["prose_status"] == "verified")
    finally:
        drop(settings)
