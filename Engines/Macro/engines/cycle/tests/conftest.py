"""Shared fixtures, on the Instruments engine's pattern.

* **A real PostgreSQL server**, no fallback: unreachable means the run stops with the
  remedy, never a quietly skipped store.
* **A throwaway schema per test module** for the cycle engine's own store, dropped afterwards.
* **macrofield from a frozen state.** Calibration 1.1.0 reads macrofield's output; the API
  tests serve the frozen ``golden/macrofield_*.json`` through a mock transport, since a live
  macrofield needs its own data load and a 30-second run.
* **A real datafeed**, not a mock: once per session, datafeed is bootstrapped into its own
  throwaway schema (``--frozen --offline``: the frozen raw snapshot and the frozen public
  responses, so no MATLAB folder and no network) and served on a free port as a separate
  process. The engine talks to it over HTTP exactly as in production. Needs the ``datafeed``
  package installed in the same environment (``pip install -e ../datafeed[dev]``).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import psycopg
import pytest

from cycle.contracts import Panel
from cycle.settings import Settings, load

GOLDEN = Path(__file__).resolve().parent.parent / "golden"
SNAPSHOT = GOLDEN / "snapshot_2026-01-05.public"
#: The raw snapshot the throwaway datafeed bootstraps, read from datafeed's own frozen
#: manifest so that a new datafeed import does not break this suite. The golden input is the
#: frozen production snapshot instead (golden/README.md); the live datafeed serves the API tests.
RAW_ID = json.loads((Path(__file__).resolve().parents[2] / "datafeed" / "golden" / "snapshot_2026-01-05"
                     / "manifest.json").read_text(encoding="utf-8"))["snapshot_id"]


def pytest_configure(config):
    target = load().database
    try:
        with psycopg.connect(target.conninfo(), connect_timeout=5):
            pass
    except Exception as exc:  # noqa: BLE001
        raise pytest.UsageError(
            f"cannot reach PostgreSQL at {target.redacted_url()}: {exc}\n"
            "  The suite runs against a real server; there is no fallback.\n"
            "  Start it:  docker compose up -d   (in Projects\\PostgreSQL)\n"
            "  Create the database once:  python -m cycle init-db") from exc
    try:
        import datafeed  # noqa: F401
    except ImportError as exc:
        raise pytest.UsageError("the datafeed engine is not installed here: "
                                "pip install -e ../datafeed[dev]") from exc


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def datafeed() -> dict:
    """A live, bootstrapped datafeed: {'url', 'raw', 'filled'}."""
    db = load().database
    schema = f"t_df_{uuid.uuid4().hex[:10]}"
    port = _free_port()
    env = {**os.environ, "DATAFEED_DB_SCHEMA": schema, "DATAFEED_PORT": str(port),
           "DATAFEED_DB_PASSWORD": db.password, "PYTHONUTF8": "1"}
    boot = subprocess.run([sys.executable, "-m", "datafeed", "bootstrap", "--frozen", "--offline"],
                          env=env, capture_output=True, text=True, timeout=300)
    if boot.returncode != 0:
        raise pytest.UsageError(f"datafeed bootstrap failed:\n{boot.stdout}\n{boot.stderr}")
    proc = subprocess.Popen([sys.executable, "-m", "datafeed", "serve"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while True:
        try:
            if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if proc.poll() is not None or time.time() > deadline:
            proc.kill()
            raise pytest.UsageError(f"datafeed did not start: {proc.stderr.read().decode()[-2000:]}")
        time.sleep(0.2)
    snapshots = httpx.get(f"{url}/snapshots", timeout=30).json()
    # The public-fill child of the raw snapshot (datafeed may derive further snapshots from it).
    filled = next(s["snapshot_id"] for s in snapshots if s["parent_id"] == RAW_ID)
    yield {"url": url, "raw": RAW_ID, "filled": filled}
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    # The throwaway schema is owned by the datafeed role, and the cycle role may not drop it
    # (Engine Building Guide 8.2), so it is dropped with datafeed's own credentials.
    from datafeed.settings import load as load_datafeed

    owner = load_datafeed().database
    with psycopg.connect(owner.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(scope="session")
def panel_json() -> str:
    return (SNAPSHOT / "panel.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def panel(panel_json) -> Panel:
    return Panel.model_validate_json(panel_json)


@pytest.fixture(scope="session")
def draft() -> dict:
    return json.loads((SNAPSHOT / "draft_1.0.0.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def expected_build() -> dict:
    return json.loads((SNAPSHOT / "expected_1.0.0.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def expected_active() -> dict:
    return json.loads((SNAPSHOT / "expected_1.1.0.json").read_text(encoding="utf-8"))


MACROFIELD_ARTEFACT = "MFS-6183873b127fcd58"


@pytest.fixture(scope="session")
def macrofield_frozen() -> dict:
    return json.loads((GOLDEN / f"macrofield_{MACROFIELD_ARTEFACT}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def macro(macrofield_frozen):
    """The frozen macrofield output, as the service hands it to the engine."""
    from cycle.contracts import UpstreamMacroState

    state = UpstreamMacroState.model_validate(macrofield_frozen["state"])
    return {e.code: (e.years, e.observed.Y) for e in state.economies if e.status == "ok" and e.observed}


@pytest.fixture(scope="session")
def macrofield_transport(macrofield_frozen):
    """macrofield's GET /runs and GET /artefacts/{id}, answered from the frozen state."""
    body = json.dumps(macrofield_frozen["state"]).encode("utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/runs":
            return httpx.Response(200, json=[{"run_id": "RUN-frozen", "status": "succeeded",
                                              "artefact_id": MACROFIELD_ARTEFACT,
                                              "started_at": "2026-09-27T05:54:49+00:00"}])
        if request.url.path == f"/artefacts/{MACROFIELD_ARTEFACT}":
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handle)


@pytest.fixture(scope="module")
def settings(datafeed) -> Settings:
    """Engine settings: a throwaway schema for this module, upstream at the live datafeed."""
    base = load()
    schema = f"t_{uuid.uuid4().hex[:12]}"
    s = replace(base, database=replace(base.database, schema=schema), datafeed_url=datafeed["url"],
                macrofield_url="http://macrofield.test")
    yield s
    with psycopg.connect(s.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(scope="module")
def client(settings, macrofield_transport):
    from fastapi.testclient import TestClient

    from cycle.api import create_app
    with TestClient(create_app(settings, macrofield_transport=macrofield_transport)) as c:
        yield c
