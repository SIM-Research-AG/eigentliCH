"""Shared fixtures.

* **A real PostgreSQL server**, no fallback. Unreachable means the run stops with the remedy; it never goes
  green by skipping the store.
* **A throwaway schema per test module**, ``t_<uuid>``, created and dropped as the real ``lbs`` role; the
  teardown asserts it drops only that schema.
* **The golden cases** in ``golden/cases`` (requests) and ``golden/expected`` (the prototype's outputs), and
  the calibrations they run under: the seed 1.0.0 and the owner's approval 1.1.0 for the prototype layer,
  1.2.0 and 1.3.0 for the corrected layer.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

import psycopg
import pytest

from lbs.calibration import APPROVED, CORRECTED, CORRECTED_1_3, SEED
from lbs.settings import Settings, load

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"

#: The golden reference's two variants run under the real seeds: ``seed`` under 1.0.0, ``approved`` under 1.1.0
#: (the owner's approval of 29.09.2026, LBS-23; frozen in the prototype with an in-memory approval fixture,
#: which differs from 1.1.0 only in the publisher's name). 1.2.0, the corrected behaviour, has its own layer
#: (``golden/corrected``, LBS-24).
CALIBRATIONS = {"seed": SEED, "approved": APPROVED}
__all__ = ["APPROVED", "CORRECTED", "CORRECTED_1_3", "SEED", "CALIBRATIONS"]


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
            "  The lbs role and schema are provisioned by Instruments/store/provision.py"
        ) from exc


def golden_names() -> list[str]:
    return sorted(p.stem for p in (GOLDEN / "cases").glob("*.json"))


def golden_request(name: str) -> dict:
    return json.loads((GOLDEN / "cases" / f"{name}.json").read_text(encoding="utf-8"))


def golden_expected(name: str) -> dict:
    return json.loads((GOLDEN / "expected" / f"{name}.json").read_text(encoding="utf-8"))


def temp_settings() -> Settings:
    base = load()
    return replace(base, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


def drop(settings: Settings) -> None:
    from lbs.store import Store

    schema = settings.database.schema
    assert schema.startswith("t_") and schema != "lbs", f"refusing to drop {schema!r}"
    Store(settings.database).drop_schema()


@pytest.fixture(scope="module")
def settings() -> Iterator[Settings]:
    s = temp_settings()
    yield s
    drop(s)


@pytest.fixture(scope="module")
def client(settings) -> Iterator:
    from fastapi.testclient import TestClient

    from lbs.api import create_app

    with TestClient(create_app(settings)) as c:
        yield c


def sample_request(**over) -> dict:
    """One adult with a property goal and a retirement goal: most sections have something to say."""
    body = {
        "client_ref": "sample-01", "as_of": "2026-09-28",
        "household": {"composition_as_of": "2026-06-01", "persons": [
            {"person_id": "p1", "kind": "adult", "age": 40,
             "human_capital": {"qualification_highest": "Fachhochschule FH", "qualification_year": 2014,
                               "years_in_field": 12, "network_people": 6, "health": "0.85",
                               "hours_per_week": 42, "rest_hours": "5–10"},
             "ahv": {"contribution_years_missing": 1}}]},
        "positions": [
            {"position_id": "cash", "role": "stabilisation", "capital_type": "financial", "magnitude": 80000,
             "unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free", "owner": "p1",
             "funds_goals": ["home"]},
            {"position_id": "depot", "role": "growth", "capital_type": "financial", "magnitude": 120000,
             "unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free", "owner": "p1",
             "funds_goals": ["home"]},
            {"position_id": "pk", "role": "protection", "capital_type": "financial", "magnitude": 150000,
             "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid", "vessel": "pillar_2", "owner": "p1"},
            {"position_id": "salary", "role": "income", "capital_type": "human", "magnitude": 120000,
             "unit": "chf_per_year", "owner": "p1"},
            {"position_id": "loan", "role": "stabilisation", "capital_type": "financial", "magnitude": 20000,
             "unit": "chf", "stock_kind": "liability", "owner": "p1"}],
        "goals": [
            {"goal_id": "home", "kind": "property", "target_amount": 1000000, "target_date": "2032-12-31",
             "occupancy": "owner_occupied_primary", "owners": ["p1"]},
            {"goal_id": "later", "kind": "retirement", "target_amount": 80000, "target_date": "2051-01-01"}],
        "facts": {"civil_status": "ledig"},
        "mandate": {"goal_id": "home", "annual_contribution": 24000},
    }
    body.update(over)
    return body


@pytest.fixture()
def request_body() -> Callable[..., dict]:
    return sample_request
