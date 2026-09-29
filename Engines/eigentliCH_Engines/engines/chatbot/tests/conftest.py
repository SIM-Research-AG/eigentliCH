"""Shared fixtures.

* **A real PostgreSQL server**, no fallback. Unreachable means the run stops with the remedy; it never goes
  green by skipping the store.
* **A throwaway schema per test module**, ``t_<uuid>``, created and dropped as the real ``chatbot`` role;
  the teardown asserts it drops only that schema.
* **spark7 is a stand-in** on a real socket (``standin.py``), streaming as vLLM does. The settings point
  the engine at it and carry fake token values, so the real token never leaves the machine in a test.
  The one live test (``-m live``) is the exception, and opt-in.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Iterator

import psycopg
import pytest

from chatbot.settings import Settings, load

from .standin import StandIn

FAKE_ENV = {"SPARK7_CLIENT_ID": "test-client-id.access", "SPARK7_CLIENT_SECRET": "test-secret-value-0123456789"}


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
            "  Provision the chatbot role once:  python -m store.provision   (in Projects\\Engines\\Instruments)"
        ) from exc


def settings_for(url: str, **model_over) -> Settings:
    """The real configuration, pointed at ``url``, warm-up off, a fresh throwaway schema, fake token."""
    base = load(overrides={"model": {"base_url": url, "warmup": {"enabled": False}, **model_over}})
    return replace(base, env=dict(FAKE_ENV),
                   database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


def drop(settings: Settings) -> None:
    from chatbot.store import Store

    schema = settings.database.schema
    assert schema.startswith("t_") and schema != "chatbot", f"refusing to drop {schema!r}"
    Store(settings.database).drop_schema()


@pytest.fixture(scope="session")
def standin() -> Iterator[StandIn]:
    server = StandIn().start()
    yield server
    server.stop()


@pytest.fixture()
def spark(standin: StandIn) -> StandIn:
    """The stand-in, emptied for this test."""
    standin.reset()
    return standin


@pytest.fixture(scope="module")
def settings(standin: StandIn) -> Iterator[Settings]:
    s = settings_for(standin.url)
    yield s
    drop(s)


@pytest.fixture(scope="module")
def client(settings) -> Iterator:
    from fastapi.testclient import TestClient

    from chatbot.api import create_app

    with TestClient(create_app(settings)) as c:
        yield c


NOTES = [
    {"id": "N1", "title": "Säule 3a: Maximalbetrag 2026",
     "text": "Erwerbstätige mit Pensionskasse dürfen 2026 höchstens CHF 7'258 pro Jahr in die Säule 3a einzahlen. "
             "Ohne Pensionskasse sind es 20 % des Erwerbseinkommens, höchstens CHF 36'288.",
     "source_label": "eigentliCH Wissen: Säule 3a (2026)"},
    {"id": "N2", "title": "AHV: Referenzalter",
     "text": "Das Referenzalter der AHV beträgt 65 Jahre, für Frauen wie für Männer (AHV 21).",
     "source_label": "eigentliCH Wissen: AHV (2026)"},
]


def request_body(question: str = "Wie viel darf ich 2026 in die Säule 3a einzahlen?", **over) -> dict:
    body = {"question": question, "language": "de", "grounding": NOTES}
    body.update(over)
    return body
