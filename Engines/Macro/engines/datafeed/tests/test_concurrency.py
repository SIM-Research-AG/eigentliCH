"""The opening burst against a live server (TestClient serialises requests)."""

from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn

from datafeed.api import create_app

from .conftest import RAW_ID


@pytest.fixture(scope="module")
def live(built):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(built), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_many_panels_at_once(live, filled_id):
    paths = [f"/panel?snapshot_id={RAW_ID}", f"/panel?snapshot_id={filled_id}&countries=BD",
             "/snapshots", f"/coverage?snapshot_id={filled_id}", "/meta", "/series"] * 3
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda p: httpx.get(live + p, timeout=120).status_code, paths))
    assert codes == [200] * len(paths)


def test_concurrent_identical_runs_agree(live):
    body = {"snapshot_id": RAW_ID, "countries": ["US", "JP"]}
    with ThreadPoolExecutor(6) as pool:
        answers = list(pool.map(lambda _: httpx.post(f"{live}/run", json=body, timeout=120).json(), range(6)))
    assert {a["status"] for a in answers} == {"succeeded"}
    assert len({a["artefact_id"] for a in answers}) == 1
