"""Shared fixtures.

* **A real PostgreSQL server**, no fallback. Unreachable means the run stops with the remedy; it never goes
  green by skipping the store.
* **A throwaway schema per test module**, ``t_<uuid>``, created and dropped as the real ``pcp`` role; the
  teardown asserts it drops only that schema.
* **Upstream engines served from the frozen inputs** in ``golden/inputs/`` through ``httpx.MockTransport``:
  the Default Regime from ``aggregation`` and the ReturnSet and register from ``fmre``. The frozen ReturnSet
  is fmre's default as served on 28.09.2026: unstamped and in each series' source currency. The double
  stamps it as fmre does on request: the requested ``regime_id`` written in, and the requested currency named
  in the opt-in note fmre writes on a converted set (PCP-19). The profiles are served unchanged: the frozen
  inputs stand for the CHF set, so golden layer C and every test below read as CHF (PCP-18).
  ``unstamped_client`` serves the set exactly as frozen.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

import httpx
import psycopg
import pytest

from pcp.settings import Settings, load

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"
INPUTS = GOLDEN / "inputs"
REGIME_ID = "RGM-e2658e8e9bbbc81e"


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
            "  Provision the pcp role once:  python -m store.provision   (in Projects\\Engines\\Instruments)"
        ) from exc


def read(name: str) -> bytes:
    return (INPUTS / name).read_bytes()


def currency_note(currency: str) -> str:
    """The note fmre writes on an opt-in set (Instruments/api/main.py, ``/v1/return-set``)."""
    return (f"Opt-in view: instrument profiles computed on request with profile_method=cascade in "
            f"currency={currency}; not the stored default.")


def stamped_return_set(regime_id: str = REGIME_ID, currency: str | None = "CHF",
                       currency_field: str | None = None) -> bytes:
    """The frozen set stamped with ``regime_id`` and, as fmre notes it today, measured in ``currency``.
    ``currency_field`` writes the structured ``provenance.currency`` pcp asks fmre to add (PCP-19)."""
    payload = json.loads(read("return_set.json"))
    payload["provenance"]["regime_id"] = regime_id
    if currency is not None:
        kept = [n for n in payload["provenance"]["notes"] if "in currency=" not in n]   # a refrozen CHF set
        payload["provenance"]["notes"] = kept + [currency_note(currency)]
    if currency_field is not None:
        payload["provenance"]["currency"] = currency_field
    return json.dumps(payload).encode("utf-8")


def aggregation_transport() -> httpx.MockTransport:
    regime = read("regime.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/regime/{REGIME_ID}":
            return httpx.Response(200, content=regime)
        return httpx.Response(404, json={"detail": f"no regime {request.url.path}"})

    return httpx.MockTransport(handler)


def fmre_transport(return_set: bytes | None = None, seen: list | None = None) -> httpx.MockTransport:
    """fmre as a test double. With ``return_set`` it serves those bytes whatever is asked; without, it stamps
    the ``regime_id`` and the currency the request names, as fmre does, and serves the unstamped set when no
    ``regime_id`` is named. ``seen`` collects the query of every ReturnSet request."""
    instruments = read("instruments.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/return-set":
            if seen is not None:
                seen.append(dict(request.url.params))
            if return_set is not None:
                return httpx.Response(200, content=return_set)
            asked = request.url.params.get("regime_id")
            currency = request.url.params.get("currency")
            return httpx.Response(200, content=stamped_return_set(asked, currency) if asked
                                  else read("return_set.json"))
        if request.url.path == "/v1/instruments":
            return httpx.Response(200, content=instruments)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def temp_settings() -> Settings:
    base = load()
    return replace(base, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


def _drop(settings: Settings) -> None:
    from pcp.store import Store

    schema = settings.database.schema
    assert schema.startswith("t_") and schema != "pcp", f"refusing to drop {schema!r}"
    Store(settings.database).drop_schema()


@pytest.fixture(scope="module")
def settings() -> Iterator[Settings]:
    s = temp_settings()
    yield s
    _drop(s)


def _client(settings: Settings, return_set: bytes | None, seen: list | None = None):
    from fastapi.testclient import TestClient

    from pcp.api import create_app

    return TestClient(create_app(settings, aggregation_transport(), fmre_transport(return_set, seen)))


@pytest.fixture(scope="module")
def client(settings) -> Iterator:
    """The app against fmre stamping the requested Regime: the state a successful run needs."""
    with _client(settings, None) as c:
        yield c


@pytest.fixture(scope="module")
def unstamped_client(settings) -> Iterator:
    """The app against the ReturnSet exactly as fmre serves it today (regime_id null)."""
    with _client(settings, read("return_set.json")) as c:
        yield c


def instruments() -> list[dict]:
    return json.loads(read("instruments.json"))


@pytest.fixture()
def mandate() -> Callable[..., dict]:
    """A feasible balanced mandate over the whole fmre universe, as a JSON body; override any field."""

    def make(**over) -> dict:
        body = {
            "client": "test", "name": "balanced", "currency": "CHF",
            "curve_unit": "annualised_log_return", "target_curve": [0.02] * 25,
            "universe": sorted(i["instrument_id"] for i in instruments()),
            "max_single_position": 0.15, "esg_min": 0.0,
            "bounds": {"role": {"Gain": {"lower": 0.2, "upper": 0.6}, "Protection": {"lower": 0.05, "upper": 0.4}},
                       "currency": {"CHF": {"lower": 0.3, "upper": 1.0}}},
            "bound_sources": {"role": "derived", "currency": "derived"},
            "regime_market": "global",
        }
        body.update(over)
        return body

    return make


def run_body(mandate_body: dict, **over) -> dict:
    body = {"regime_id": REGIME_ID, "return_set_id": json.loads(read("return_set.json"))["return_set_id"],
            "mandate": mandate_body}
    body.update(over)
    return body
