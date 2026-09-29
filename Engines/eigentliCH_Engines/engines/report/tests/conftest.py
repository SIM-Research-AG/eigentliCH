"""Shared fixtures.

* **A real PostgreSQL server**, no fallback, and a throwaway schema per test module (``t_<uuid>``), created
  and dropped as the real ``report`` role.
* **Upstream engines served from the frozen inputs** in ``golden/inputs/`` through ``httpx.MockTransport``:
  a pcp Allocation and an lbs LifeBalanceSheet (``dev/freeze_inputs.py``).
* **spark7 is a stand-in** on a real socket (``standin.py``), streaming as vLLM does; the settings carry
  fake token values. By default it answers each section with a paragraph built from the figures it was
  given (``echo``), so a draft verifies; tests script it otherwise.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx
import psycopg
import pytest

from report.settings import Settings, load

from .standin import Reply, StandIn

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "golden" / "inputs"
FAKE_ENV = {"SPARK7_CLIENT_ID": "test-client-id.access", "SPARK7_CLIENT_SECRET": "test-secret-value-0123456789"}

PCP = (INPUTS / "pcp_allocation.json").read_bytes()
LBS = (INPUTS / "lbs_sheet.json").read_bytes()
PCP_ID = json.loads(PCP)["artefact_id"]
LBS_ID = json.loads(LBS)["artefact_id"]
CLIENT = json.loads(LBS)["client_ref"]


def pytest_configure(config):
    target = load().database
    try:
        with psycopg.connect(target.conninfo(), connect_timeout=5):
            pass
    except Exception as exc:  # noqa: BLE001
        raise pytest.UsageError(
            f"cannot reach PostgreSQL at {target.redacted_url()}: {exc}\n"
            "  The suite runs against a real server; there is no fallback.\n"
            "  Start it:  docker compose up -d   (in Projects\\PostgreSQL)"
        ) from exc


class Upstream:
    """pcp, lbs and lbsim as test doubles serving the frozen artefacts; ``extra`` adds more by path."""

    def __init__(self) -> None:
        self.extra: dict[str, dict[str, bytes]] = {"pcp": {}, "lbs": {}, "lbsim": {}}
        self.down: set[str] = set()
        self.calls: list[str] = []

    def transport(self, engine: str) -> httpx.MockTransport:
        base = {"pcp": {f"/allocation/{PCP_ID}": PCP}, "lbs": {f"/artefacts/{LBS_ID}": LBS}, "lbsim": {}}[engine]

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(f"{engine}{request.url.path}")
            if engine in self.down:
                raise httpx.ConnectError("refused", request=request)
            body = {**base, **self.extra[engine]}.get(request.url.path)
            return httpx.Response(200, content=body) if body is not None else httpx.Response(404, json={"detail": "no"})

        return httpx.MockTransport(handler)

    def transports(self) -> dict[str, httpx.BaseTransport]:
        return {"pcp": self.transport("pcp"), "lbs": self.transport("lbs"), "lbsim": self.transport("lbsim")}


def settings_for(url: str, **model_over) -> Settings:
    base = load(overrides={"model": {"base_url": url, "warmup": {"enabled": False}, **model_over}})
    return replace(base, env=dict(FAKE_ENV), database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))


def drop(settings: Settings) -> None:
    from report.store import Store

    schema = settings.database.schema
    assert schema.startswith("t_") and schema != "report", f"refusing to drop {schema!r}"
    Store(settings.database).drop_schema()


_FIGURE_LINE = re.compile(r"^- (.+?): (.+)$", re.M)


def echo(body: dict[str, Any]) -> Reply:
    """A draft that quotes the first two figures it was given, with their labels: it verifies."""
    prompt = body["messages"][-1]["content"]
    german = "Alle Beträge" in prompt
    lines = _FIGURE_LINE.findall(prompt)[:2]
    said = " und ".join(f"{k} {v}" for k, v in lines) if german else " and ".join(f"{k} {v}" for k, v in lines)
    text = (f"Dieser Abschnitt zeigt {said}. Die Tabelle daneben nennt jede Grösse mit ihrer Quelle, und nichts "
            "davon ist eine Empfehlung." if german else
            f"This section shows {said}. The table beside it names every figure with its source, and none of it is "
            "a recommendation.")
    return Reply(content=text)


@pytest.fixture(scope="session")
def standin() -> Iterator[StandIn]:
    server = StandIn().start()
    yield server
    server.stop()


@pytest.fixture()
def spark(standin: StandIn) -> StandIn:
    standin.reset()
    standin.responder = echo
    return standin


@pytest.fixture(scope="module")
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture(scope="module")
def settings(standin: StandIn) -> Iterator[Settings]:
    s = settings_for(standin.url)
    yield s
    drop(s)


@pytest.fixture(scope="module")
def client(settings, upstream) -> Iterator:
    from fastapi.testclient import TestClient

    from report.api import create_app

    with TestClient(create_app(settings, upstream.transports())) as c:
        yield c


def request_body(*, sources: Optional[list] = None, **over) -> dict:
    body = {"client_ref": CLIENT, "kind": "report", "language": "de",
            "sources": sources if sources is not None else [{"engine": "pcp", "artefact_id": PCP_ID},
                                                             {"engine": "lbs", "artefact_id": LBS_ID}],
            "display_facts": [{"key": "name", "label": "Kundin", "value": "Muster", "source": "app"}]}
    body.update(over)
    return body
