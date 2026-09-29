"""Shared fixtures.

The store tests run against the real PostgreSQL container, never a stand-in, and the suite
fails loudly when it is unreachable rather than skipping: a run that goes green by quietly
skipping the half that matters is worse than one that fails. Every test module that needs a
store gets its own throwaway schema, dropped afterwards, so the suite never touches the real one.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

from macrofield.settings import Settings, load  # noqa: E402
from macrofield.store import Store  # noqa: E402

RAW = ROOT / "data" / "raw"
GOLDEN = ROOT / "golden"


def pytest_configure(config: pytest.Config) -> None:
    settings = load()
    try:
        psycopg.connect(settings.database.conninfo(), connect_timeout=5).close()
    except psycopg.OperationalError as exc:
        raise pytest.UsageError(
            f"PostgreSQL is not reachable at {settings.database.redacted_url()} ({exc}). "
            "Start it with `docker compose up -d` in Projects\\PostgreSQL and run "
            "`python -m macrofield init-db` once. The suite does not skip the store tests."
        ) from exc


def temp_settings(**run: object) -> Settings:
    """Settings on a fresh throwaway schema. ``run`` overrides the run section."""
    overrides: dict = {"database": {"schema": f"t_{uuid.uuid4().hex[:12]}"}}
    if run:
        overrides["run"] = dict(run)
    return load(overrides=overrides)


@pytest.fixture(scope="module")
def module_settings():
    settings = temp_settings(max_workers=2)
    yield settings
    Store(settings.database).drop_schema()


@pytest.fixture(scope="session")
def raw_observations():
    """Engine observations parsed straight from data/raw, as the golden route sees them."""
    from observations_from_raw import observations

    return observations()
