"""FMRE-42: the schema at start-up, a health answer on an empty schema, a quiet access log.

Each database test here points the store at a throwaway schema pair that does **not** exist
yet, which is exactly the empty database the deployment meets, and drops both afterwards.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import replace

import pytest


@contextmanager
def empty_schema():
    """A throwaway schema pair that has never been initialised."""
    from store import db

    name = f"t_{uuid.uuid4().hex[:12]}"
    previous = db.get_config()
    config = replace(previous, schema=name, datafeed_schema=f"{name}_feed", sources=("test",))
    assert config.schema != previous.schema
    assert config.datafeed_schema != previous.datafeed_schema
    db.use_config(config)
    try:
        yield config
    finally:
        try:
            db.drop_schema(config, include_datafeed=True)
        except Exception:  # noqa: BLE001 - cleanup must not mask a test failure
            pass
        db.use_config(previous)


def _schema_exists(name: str) -> bool:
    from store import db

    with db.session() as conn:
        row = conn.execute(
            "SELECT 1 AS present FROM information_schema.schemata WHERE schema_name = %s",
            (name,),
        ).fetchone()
    return row is not None


def test_health_answers_200_on_a_schema_without_tables():
    from fastapi.testclient import TestClient
    import api.main

    with empty_schema() as config:
        # Without the context manager the lifespan does not run: the schema stays empty.
        client = TestClient(api.main.app)
        response = client.get("/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "uninitialised"
        assert body["missing_tables"] == list(api.main.HEALTH_TABLES)
        assert body["calibration_id"] is None
        assert body["store"]["schema"] == config.schema
        # Health reads; it never creates.
        assert not _schema_exists(config.schema)


def test_startup_applies_the_schema_and_is_idempotent():
    from fastapi.testclient import TestClient
    import api.main

    with empty_schema() as config:
        assert not _schema_exists(config.schema)
        with TestClient(api.main.app) as client:
            body = client.get("/v1/health").json()
        assert _schema_exists(config.schema) and _schema_exists(config.datafeed_schema)
        assert body["status"] == "uncalibrated"
        assert set(body["counts"]) == set(api.main.HEALTH_TABLES)
        assert all(n == 0 for n in body["counts"].values())
        # A second start on the same store changes nothing and does not fail.
        with TestClient(api.main.app) as client:
            again = client.get("/v1/health")
        assert again.status_code == 200 and again.json()["counts"] == body["counts"]


def test_startup_survives_a_store_it_cannot_reach(caplog):
    """A failed start-up initialise is logged, and the engine still starts."""
    from fastapi.testclient import TestClient
    from store import db
    import api.main

    previous = db.get_config()
    # Port 1 refuses at once; nothing is written anywhere.
    db.use_config(replace(previous, port=1, connect_timeout=2, schema="t_unreachable",
                          datafeed_schema="t_unreachable_feed", sources=("test",)))
    try:
        with caplog.at_level(logging.WARNING, logger="fmre"):
            with TestClient(api.main.app) as client:
                assert client.get("/v1/axis").status_code == 200
        assert any("could not be applied" in r.getMessage() for r in caplog.records)
    finally:
        db.use_config(previous)


# ---------------------------------------------------------------------------
# The access log
# ---------------------------------------------------------------------------


def _access_record(path: str, status: int) -> logging.LogRecord:
    """A record shaped like the one uvicorn's access logger writes."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", status), None,
    )


@pytest.mark.parametrize("path,status,kept", [
    ("/v1/health", 200, False),
    ("/v1/health?x=1", 200, False),
    ("/v1/health", 500, True),          # a failing probe is the line worth reading
    ("/v1/return-set", 200, True),
    ("/v1/health/extra", 200, True),
    ("/health", 200, True),             # not fmre's route
])
def test_access_filter_drops_only_successful_health_probes(path, status, kept):
    from api.access_log import HealthProbeFilter

    assert HealthProbeFilter().filter(_access_record(path, status)) is kept


def test_access_filter_passes_records_of_another_shape():
    from api.access_log import HealthProbeFilter

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "plain", None, None)
    assert HealthProbeFilter().filter(record) is True


def test_access_filter_is_installed_once_on_uvicorn_access():
    from api import access_log
    import api.main  # noqa: F401 - importing installs it

    logger = logging.getLogger("uvicorn.access")
    access_log.install()
    installed = [f for f in logger.filters if isinstance(f, access_log.HealthProbeFilter)]
    assert len(installed) == 1
    assert installed[0].paths == {"/v1/health"}
