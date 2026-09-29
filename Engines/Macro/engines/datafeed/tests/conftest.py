"""Shared fixtures, on the Instruments engine's pattern.

* **A real PostgreSQL server**, no fallback. Unreachable means the run stops with the
  remedy; it never goes green by skipping the store.
* **A throwaway schema per test module**, built by the real bootstrap (``--frozen
  --offline``: the frozen raw snapshot and the frozen public responses), so the store under
  test is built exactly as production builds it.
* **Source-dependent tests skip** when the MATLAB folder or the network is absent, and say
  why. The frozen references in ``golden/`` make everything else run anywhere.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from datafeed.settings import Settings, load

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"
RAW_ID = "matlab-m_ts-2026-01-05.r3"


def _online() -> bool:
    try:
        socket.create_connection(("api.worldbank.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


needs_matlab = pytest.mark.skipif(
    not (load().matlab.dir / load().matlab.file).is_file(),
    reason="M_TS.mat not found; set DATAFEED_MATLAB_DIR to run the importer tests")
needs_network = pytest.mark.skipif(
    os.environ.get("DATAFEED_OFFLINE") == "1" or not _online(),
    reason="no network (or DATAFEED_OFFLINE=1); the live public-source tests need it")


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
            "  Create the database once:  python -m datafeed init-db") from exc


def temp_settings() -> Settings:
    base = load()
    return replace(base, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


def drop(settings: Settings) -> None:
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {settings.database.schema} CASCADE")


@pytest.fixture(scope="module")
def settings():
    """An empty throwaway schema for this module."""
    s = temp_settings()
    yield s
    drop(s)


@pytest.fixture(scope="module")
def built(settings):
    """The throwaway schema, bootstrapped exactly as production is (offline)."""
    from datafeed.etl.bootstrap import main

    assert main(["--frozen", "--offline"], settings) == 0
    return settings


@pytest.fixture(scope="module")
def service(built):
    from datafeed.service import Service
    from datafeed.store import Store
    return Service(built, Store(built.database))


@pytest.fixture(scope="module")
def filled_id(service) -> str:
    return next(s.snapshot_id for s in service.snapshots() if s.parent_id == RAW_ID)


@pytest.fixture(scope="module")
def client(built):
    from fastapi.testclient import TestClient

    from datafeed.api import create_app
    with TestClient(create_app(built)) as c:
        yield c


@pytest.fixture(scope="session")
def frozen_manifest() -> dict:
    return json.loads((GOLDEN / "snapshot_2026-01-05" / "manifest.json").read_text(encoding="utf-8"))
