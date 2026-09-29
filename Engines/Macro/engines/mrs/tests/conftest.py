"""Shared fixtures.

* **A real PostgreSQL server**, no fallback: unreachable means the run stops with the
  remedy, never a quietly skipped store.
* **A throwaway schema per test module** for the mrs store, dropped afterwards.
* **A real datafeed**, not a mock, as in honi: once per session, datafeed is bootstrapped
  into its own throwaway schema (``--frozen --offline``: no MATLAB folder, no network) and
  served on a free port as a separate process. mrs reads its panel over HTTP exactly as in
  production. Needs the ``datafeed`` package in the same environment
  (``pip install -e ../datafeed[dev]``). Runs read its market layer (production) and its
  raw snapshot (the ``matlab`` calibration), never the live datafeed on 8001.
* **The golden files** in ``golden/``: the frozen raw snapshot, and the CIO site exports
  (``assets`` in, ``stats`` and ``signal`` out) of one MATLAB run.
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

from mrs.settings import Settings, load

GOLDEN = Path(__file__).resolve().parent.parent / "golden"
SNAPSHOT = GOLDEN / "snapshot_2026-01-05"
CIO = {"assets": GOLDEN / "cio_assets_2026-09" / "assets.txt",
       "stats": GOLDEN / "cio_stats_2026-09" / "stats.txt",
       "signal": GOLDEN / "cio_signal_2026-09" / "signal.txt"}
#: datafeed's raw snapshot: the Bloomberg pull of 2026-01-05, all 28 mrs series.
RAW_ID = "matlab-m_ts-2026-01-05.r3"


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
            "  Create the database once:  python -m mrs init-db") from exc
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
    """A live, bootstrapped datafeed: {'url', 'raw', 'filled', 'market'}."""
    from datafeed.settings import load as load_datafeed

    owner = load_datafeed().database
    schema = f"t_df_{uuid.uuid4().hex[:10]}"
    port = _free_port()
    env = {**os.environ, "DATAFEED_DB_SCHEMA": schema, "DATAFEED_PORT": str(port),
           "DATAFEED_DB_PASSWORD": owner.password, "PYTHONUTF8": "1"}
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
    filled = next(s["snapshot_id"] for s in snapshots if s["parent_id"] == RAW_ID)
    market = next(s["snapshot_id"] for s in snapshots if s["parent_id"] == filled)   # DF-18
    yield {"url": url, "raw": RAW_ID, "filled": filled, "market": market}
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    # Owned by the datafeed role; mrs's role may not drop it (Engine Building Guide 8.2).
    with psycopg.connect(owner.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


# ---------------------------------------------------------------------------
# Store and app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def settings(datafeed) -> Settings:
    """mrs settings: a throwaway schema for this module, upstream at the bootstrapped
    datafeed, default snapshot its market layer (what production reads)."""
    base = load()
    schema = f"t_{uuid.uuid4().hex[:12]}"
    s = replace(base, database=replace(base.database, schema=schema), datafeed_url=datafeed["url"],
                snapshot_id=datafeed["market"])
    yield s
    with psycopg.connect(s.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(scope="module")
def client(settings):
    from fastapi.testclient import TestClient

    from mrs.api import create_app
    with TestClient(create_app(settings)) as c:
        yield c


# ---------------------------------------------------------------------------
# The frozen input
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def frozen() -> dict:
    """golden/snapshot_2026-01-05: the panel, conversions, countries and source record."""
    from mrs.contracts import ImportConversion, Panel

    read = lambda name: (SNAPSHOT / name).read_text(encoding="utf-8")  # noqa: E731
    return {
        "panel": Panel.model_validate_json(read("panel.json")),
        "conversions": [ImportConversion.model_validate(c) for c in json.loads(read("conversions.json"))],
        "countries": json.loads(read("countries.json")),
        "source": json.loads(read("source.json")),
    }


@pytest.fixture(scope="session")
def cio() -> dict:
    """The CIO site exports of one MATLAB run (03.09.2026): assets in, stats and signal out."""
    return {k: json.loads(p.read_text(encoding="utf-8")) for k, p in CIO.items()}
