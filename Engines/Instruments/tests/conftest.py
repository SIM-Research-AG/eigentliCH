"""Shared fixtures.

The suite runs against **a real PostgreSQL server** and there is no in-memory fallback.
That is a deliberate trade: the engine has one store, so the tests exercise that store
rather than a stand-in that might behave differently. The cost is that the suite needs the
container up, and it says so loudly rather than skipping -- a suite that goes green by
quietly skipping the half that matters is worse than one that fails.

Each test that needs a store gets **its own throwaway schema** on the configured server,
dropped on the way out. A schema rather than a database, because creating one per test is
fast and needs no privilege a CI account might lack. Nothing here ever touches the
configured schema, so a test run cannot damage the real store.

The arithmetic tests need no database at all. They run against the frozen reference in
``fixtures/`` and are the reason most of the suite is fast.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ECN_DIR = Path(os.environ.get(
    "INSTRUMENTS_ECN_DIR",
    r"C:\Users\nicol\Desktop\SIM_NAS\Knowledge_Center\Published"
    r"\Dynamic Investment\Model\ecn_model",
))
FEED_CSV = Path(os.environ.get(
    "INSTRUMENTS_FEED_CSV",
    r"C:\Users\nicol\Desktop\SIM_NAS\Projects\andersCH-prototype_old"
    r"\andersCH-prototype_old\data\feeds\2026-08-01_andersCH-report.csv",
))

needs_sources = pytest.mark.skipif(
    not ECN_DIR.is_dir(),
    reason=f"the Steiner workbooks are not at {ECN_DIR}; set INSTRUMENTS_ECN_DIR",
)
needs_feed = pytest.mark.skipif(
    not FEED_CSV.is_file(),
    reason=f"the monthly feed is not at {FEED_CSV}; set INSTRUMENTS_FEED_CSV",
)


def pytest_configure(config):
    """Fail the whole run, early and clearly, if the database is not reachable.

    Checked once here rather than skipped per test, because every database test skipping
    looks a lot like a passing suite.
    """
    from store.config import load, redacted_url

    try:
        import psycopg
    except ImportError:  # pragma: no cover
        raise pytest.UsageError(
            "psycopg is not installed. pip install -r requirements.txt"
        )

    target = load()
    try:
        with psycopg.connect(target.conninfo(dbname=target.maintenance_dbname), connect_timeout=5):
            pass
    except Exception as exc:  # noqa: BLE001
        raise pytest.UsageError(
            f"cannot reach PostgreSQL at {redacted_url(target)}: {exc}\n"
            f"  The suite runs against a real server; there is no fallback.\n"
            f"  Start it:  docker compose -f <path>/docker-compose.yml up -d\n"
            f"  Or point elsewhere with INSTRUMENTS_DATABASE_URL / INSTRUMENTS_DB_*."
        ) from exc


@contextmanager
def temp_schema():
    """Point the store at a throwaway schema, and drop it afterwards."""
    from store import db

    name = f"t_{uuid.uuid4().hex[:12]}"
    previous = db.get_config()
    # **Both** schemas get a throwaway name. Renaming only the engine's would leave the
    # shared feed pointing at the real one, and a test would then read -- or delete --
    # production data. That is not hypothetical: it happened.
    config = replace(previous, schema=name, datafeed_schema=f"{name}_feed",
                     sources=("test",))
    assert config.datafeed_schema != previous.datafeed_schema, (
        "a test must never be pointed at the real datafeed schema"
    )
    db.use_config(config)
    try:
        db.initialise()
        yield config
    finally:
        try:
            db.drop_schema(config, include_datafeed=True)
        except Exception:  # noqa: BLE001 - cleanup must not mask a test failure
            pass
        db.use_config(previous)


@pytest.fixture()
def store():
    """A throwaway schema for one test."""
    with temp_schema() as config:
        yield config


@pytest.fixture(scope="module")
def module_store():
    """A throwaway schema shared by one module, for the expensive bootstrap fixtures."""
    with temp_schema() as config:
        yield config


@pytest.fixture(scope="session")
def reference() -> dict[str, list[float]]:
    """The published 25-state profiles, frozen from ``return_dist.xlsx``."""
    path = Path(__file__).parent / "fixtures" / "steiner_2021_reference.json"
    return json.loads(path.read_text(encoding="utf-8"))["profiles"]


@pytest.fixture(scope="session")
def long_record():
    from store.etl.long_record import read_long_record
    if not ECN_DIR.is_dir():
        pytest.skip("source workbooks unavailable")
    return read_long_record(ECN_DIR)


@pytest.fixture(scope="session")
def calibration(long_record):
    from engines.fund_map.calibrate import build_block_returns, calibrate_all
    from engines.fund_map.indicators import build_indicators
    from engines.fund_map.phases import PhaseTimeline, classify_series

    environment = build_indicators(long_record)
    timeline = PhaseTimeline(environment.first_year, tuple(classify_series(environment.cycle)))
    blocks = calibrate_all(build_block_returns(long_record), timeline)
    return {"environment": environment, "timeline": timeline, "blocks": blocks}


@pytest.fixture(scope="session")
def sections():
    from store.etl.market_signal import split_sections
    if not FEED_CSV.is_file():
        pytest.skip("monthly feed unavailable")
    return split_sections(FEED_CSV)
