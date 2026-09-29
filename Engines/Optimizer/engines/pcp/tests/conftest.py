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
  ``unstamped_client`` serves the set exactly as frozen. Asked for ``basis=real`` (PCP-22), the double
  deflates as fmre does (REAL_VIEW_INTERFACES.md): it subtracts ``ln(1 + inflation)`` per state
  (``STAND_IN_INFLATION``) from every instrument profile, writes ``provenance.basis`` and a ``deflator``, adds
  a notes line and gives the set its own ``return_set_id`` (``real_return_set_id``). A nominal request is
  served as before, without ``provenance.basis``. Given ``hard_currency`` (``{"EUR": "CHF"}``), the double takes
  fmre's decision-5 fallback for a real request in that currency (PCP-23): it serves the real set measured in
  the hard currency, with ``provenance.currency`` and the notes naming it, ``deflator.hard_currency_fallback``
  ``{from, to, states, reason}`` as ``inflation.hard_currency`` writes it, and an id of its own.
"""

from __future__ import annotations

import hashlib
import json
import math
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


#: The stand-in's per-state annual inflation, crisis to boom: 0 % to 4.8 % a year.
STAND_IN_INFLATION: tuple[float, ...] = tuple(0.002 * s for s in range(25))


def real_return_set_id(base: str | None = None, fallback: dict | None = None) -> str:
    """The id the double gives the real set: fmre puts the basis into its ``return_set_id``, and a hard-currency
    fallback too (its identity ``deflator.fallback``, PCP-23)."""
    base = base or json.loads(read("return_set.json"))["return_set_id"]
    tail = f"|fallback={fallback['from']}>{fallback['to']}" if fallback else ""
    return "RS-" + hashlib.sha256(f"{base}|basis=real{tail}".encode()).hexdigest()[:16]


#: The states the stand-in's EUR inflation leaves fmre's band in, for the hard-currency fallback (PCP-23).
FALLBACK_STATES: list[int] = [1, 2]


def hard_currency_fallback(asked: str, hard: str, states: list[int] | None = None) -> dict:
    """fmre's decision-5 fallback as ``engines/fund_map/inflation.py::hard_currency`` writes it."""
    states = FALLBACK_STATES if states is None else states
    return {"from": asked, "to": hard, "states": states,
            "reason": f"real in {hard}: {asked} inflation of 104.0% a year is above the ceiling of 100%; no real "
                      f"figure is computed in {asked} (decisions 4 and 5) (states {states})"}


def stamped_return_set(regime_id: str = REGIME_ID, currency: str | None = "CHF",
                       currency_field: str | None = None, basis: str | None = None,
                       deflator: dict | None = None, fallback: dict | None = None) -> bytes:
    """The frozen set stamped with ``regime_id`` and, as fmre notes it today, measured in ``currency``.
    ``currency_field`` writes the structured ``provenance.currency`` pcp asks fmre to add (PCP-19).
    ``basis`` writes ``provenance.basis``; ``real`` also deflates the profiles, writes the deflator (or
    ``deflator``) and the notes line, and moves the id (PCP-22). ``fallback`` (real only) is fmre's
    hard-currency fallback: the set is then measured and deflated in ``currency``, the hard one, and states the
    fallback and fmre's structured ``provenance.currency`` (PCP-23)."""
    payload = json.loads(read("return_set.json"))
    if basis is not None:
        payload["provenance"]["basis"] = basis
    if basis == "real":
        for p in payload["instrument_profiles"]:
            for st in p["states"]:
                st["value"] -= math.log1p(STAND_IN_INFLATION[st["state"] - 1])
        payload["return_set_id"] = real_return_set_id(payload["return_set_id"], fallback)
        labels = ["measured"] * 22 + ["extrapolated"] * 3
        payload["provenance"]["deflator"] = deflator or {      # fmre's Deflator (contracts/return_set.py)
            "currency": currency or "CHF", "index": "CPI", "method": "per-state 12m forward inflation",
            "labels": labels, "hard_currency_fallback": fallback, "scenario": None,
            "curves": [{"currency": currency or "CHF", "index": "CPI", "source": "stand-in",
                        "log_inflation": [math.log1p(v) for v in STAND_IN_INFLATION], "labels": labels,
                        "applied_to": ["instruments"]}]}
        payload["provenance"]["notes"] = list(payload["provenance"]["notes"]) + [
            "Basis: real, net of the per-state log inflation of the currency."]
    payload["provenance"]["regime_id"] = regime_id
    if currency is not None:
        kept = [n for n in payload["provenance"]["notes"] if "in currency=" not in n]   # a refrozen CHF set
        note = currency_note(currency)
        if basis == "real" and fallback:        # fmre's wording on a hard-currency set (api/main.py)
            note += f" Hard-currency view: the request asked for currency={fallback['from']}."
            payload["provenance"]["currency"] = currency
        payload["provenance"]["notes"] = kept + [note]
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


def fmre_transport(return_set: bytes | None = None, seen: list | None = None,
                   not_computable: str | None = None,
                   hard_currency: dict[str, str] | None = None) -> httpx.MockTransport:
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
            basis = request.url.params.get("basis")
            if basis == "real" and not_computable is not None:        # fmre's answer outside the band
                return httpx.Response(422, json={"detail": {"status": "not_computable", "basis": "real",
                                                            "reason": not_computable}})
            if basis == "real" and asked and currency in (hard_currency or {}):   # decision 5, PCP-23
                hard = hard_currency[currency]
                return httpx.Response(200, content=stamped_return_set(
                    asked, hard, basis="real", fallback=hard_currency_fallback(currency, hard)))
            return httpx.Response(200, content=stamped_return_set(
                asked, currency, basis=basis if basis == "real" else None) if asked
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


def _client(settings: Settings, return_set: bytes | None, seen: list | None = None,
            not_computable: str | None = None, hard_currency: dict[str, str] | None = None):
    from fastapi.testclient import TestClient

    from pcp.api import create_app

    return TestClient(create_app(settings, aggregation_transport(),
                                 fmre_transport(return_set, seen, not_computable, hard_currency)))


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
