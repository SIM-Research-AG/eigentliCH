"""The test bench's opening burst, against a live server.

``TestClient`` runs requests one at a time, so it cannot find the defects that only show
when a browser fires several fetches at once (the lesson the Instruments engine learnt the
hard way). This starts the real app under uvicorn on a free port and fires the burst from
a thread pool.
"""

from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn

from cycle.api import create_app


@pytest.fixture(scope="module")
def live(settings, macrofield_transport):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(settings, macrofield_transport=macrofield_transport)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_concurrent_identical_runs_agree(live, datafeed):
    """Eight simultaneous identical runs: one artefact, and every answer names it."""
    with ThreadPoolExecutor(8) as pool:
        answers = list(pool.map(lambda _: httpx.post(f"{live}/run", json={"snapshot_id": datafeed["filled"]},
                                                     timeout=60).json(), range(8)))
    assert {a["status"] for a in answers} == {"succeeded"}
    assert len({a["artefact_id"] for a in answers}) == 1
    assert len({a["idempotency_key"] for a in answers}) == 1


def test_the_opening_burst(live, datafeed):
    artefact = httpx.post(f"{live}/run", json={"snapshot_id": datafeed["filled"]}, timeout=60).json()["artefact_id"]
    paths = ["/health", "/meta", "/calibration/versions", "/calibration",
             f"/artefacts/{artefact}", f"/cycles/{artefact}", f"/cycles/{artefact}/current",
] * 3
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda p: httpx.get(live + p, timeout=60).status_code, paths))
    assert codes == [200] * len(paths)
