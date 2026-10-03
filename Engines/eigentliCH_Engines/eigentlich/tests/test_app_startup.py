"""Start-up and the maintenance commands' reports (ENGINE_CHANGES items 6 and 8).

* The app applies its schema at start-up, as the engines do, so ``/health`` is ok on an empty database. A store
  that cannot be reached does not stop the app; ``/health`` says ``degraded``.
* ``EIGENTLICH_REPORT_DIR`` moves the reports of ``seed`` and ``migrate``; unset, they stay in ``dev/reports``.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from eigentlich import __main__ as cli
from eigentlich.settings import ROOT, load, with_schema
from eigentlich.store import TABLES, Store

from .appkit import Engines, make_app
from .conftest import drop_schema


@pytest.fixture()
def empty():
    """A schema name nobody has created yet: an empty database, as far as the app can tell."""
    s = with_schema(load(), f"t_{uuid.uuid4().hex[:12]}")
    yield s
    drop_schema(s)


def test_health_is_ok_on_an_empty_database(empty):
    with TestClient(make_app(empty, Engines())) as http:
        h = http.get("/health").json()
    assert h["store"] == "ok" and h["status"] == "ok"
    with Store(empty.database).session() as conn:
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (empty.database.schema,))}
    assert tables == set(TABLES)


def test_a_second_start_changes_nothing(settings, st):
    with st.session() as conn:
        before = conn.execute("SELECT count(*) AS n FROM client").fetchone()["n"]
    with TestClient(make_app(settings, Engines())) as http:
        assert http.get("/health").json()["store"] == "ok"
    with st.session() as conn:
        assert conn.execute("SELECT count(*) AS n FROM client").fetchone()["n"] == before


def test_an_unreachable_store_does_not_stop_the_app(settings, capfd):
    gone = replace(settings, database=replace(settings.database, host="127.0.0.1", port=1, connect_timeout=2))
    with TestClient(make_app(gone, Engines())) as http:
        h = http.get("/health").json()
    assert h["status"] == "degraded" and h["store"].startswith("unreachable")
    assert "the schema was not applied at start-up" in capfd.readouterr().err


def test_the_report_folder_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv(cli.REPORT_DIR_VAR, raising=False)
    assert cli.REPORT_DIR_VAR == "EIGENTLICH_REPORT_DIR"
    assert cli.report_dir() == ROOT / "dev" / "reports"
    target = tmp_path / "reports" / "nested"
    monkeypatch.setenv(cli.REPORT_DIR_VAR, str(target))
    path = cli._report_path("seed-report", "t_example")
    assert path == target / "seed-report-t_example.json" and target.is_dir()
    monkeypatch.setenv(cli.REPORT_DIR_VAR, "   ")
    assert cli.report_dir() == ROOT / "dev" / "reports"
