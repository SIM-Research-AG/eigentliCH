"""``/health`` stays out of uvicorn's access log (ENGINE_CHANGES item 10); every other request is still logged."""

from __future__ import annotations

import logging

import uvicorn

from eigentlich.__main__ import quiet_health_probes


def _record(path: str) -> logging.LogRecord:
    """An access record as uvicorn writes it: client, method, path with query, HTTP version, status."""
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:50000", "GET", path, "1.1", 200), None)


def test_health_probes_stay_out_of_the_access_log():
    quiet_health_probes()
    quiet_health_probes()  # a second call adds nothing
    uvicorn.Config("eigentlich.api:create_app", factory=True)  # applies uvicorn's logging configuration, as run() does
    logger = logging.getLogger("uvicorn.access")
    assert sum(type(f).__name__ == "_NoHealthAccess" for f in logger.filters) == 1
    assert not logger.filter(_record("/health"))
    assert not logger.filter(_record("/health?probe=1"))
    assert logger.filter(_record("/meta"))
    assert logger.filter(_record("/healthz"))
