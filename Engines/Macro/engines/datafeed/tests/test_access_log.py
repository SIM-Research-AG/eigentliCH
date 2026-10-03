"""Successful health probes stay out of uvicorn's access log (DF-19)."""

from __future__ import annotations

import logging

import pytest

from datafeed.access_log import HealthProbeFilter, install


def _access_record(path: str, status: int) -> logging.LogRecord:
    """A record shaped like the one uvicorn's access logger writes."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", status), None,
    )


@pytest.mark.parametrize("path,status,kept", [
    ("/health", 200, False),
    ("/health?x=1", 200, False),
    ("/health", 503, True),             # a failing probe is the line worth reading
    ("/meta", 200, True),
    ("/health/extra", 200, True),
])
def test_drops_only_successful_health_probes(path, status, kept):
    assert HealthProbeFilter().filter(_access_record(path, status)) is kept


def test_passes_records_of_another_shape():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "plain", None, None)
    assert HealthProbeFilter().filter(record) is True


def test_install_is_idempotent():
    logger = logging.getLogger("uvicorn.access")
    first, second = install(), install()
    assert first is second
    assert sum(isinstance(f, HealthProbeFilter) for f in logger.filters) == 1


def test_create_app_installs_it():
    """Read from the source, so the check needs no database and no upstream."""
    from pathlib import Path
    import datafeed.api as api

    text = Path(api.__file__).read_text(encoding="utf-8")
    assert "access_log.install()" in text.split("def create_app", 1)[1]
