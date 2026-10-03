"""Health probes stay out of uvicorn's access log.

The container's health check calls every engine's health route every 30 seconds, and
uvicorn's access log recorded each call, so the log a person reads was mostly
``GET /health`` lines between the ones that matter (``deploy/ENGINE_CHANGES.md`` item 10,
03.10.2026). A filter on the ``uvicorn.access`` logger drops exactly those lines when they
answered below 400; every other request is still logged, and so is a health call that
answered 400 or more, because that is the line a person looking at the log wants.

``create_app`` installs it. ``serve`` runs uvicorn with the app factory, and uvicorn
configures its loggers before it calls the factory, so the filter lands on the logger
uvicorn actually writes through.

Recorded as C-27 in DECISIONS.md.
"""

from __future__ import annotations

import logging
from typing import Iterable

LOGGER = "uvicorn.access"

#: The routes a probe calls. Matched on the path alone, without the query string.
HEALTH_PATHS = frozenset({"/health"})


class HealthProbeFilter(logging.Filter):
    """Refuse an access-log record of a health route that answered below 400.

    uvicorn's access record carries ``(client, method, path_with_query, http_version,
    status)`` as its arguments; anything shaped otherwise passes untouched.
    """

    def __init__(self, paths: Iterable[str] = HEALTH_PATHS) -> None:
        super().__init__()
        self.paths = frozenset(paths)

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not (isinstance(args, tuple) and len(args) >= 5):
            return True
        path = str(args[2]).split("?", 1)[0]
        if path not in self.paths:
            return True
        try:
            return int(args[4]) >= 400
        except (TypeError, ValueError):
            return True


def install(paths: Iterable[str] = HEALTH_PATHS) -> HealthProbeFilter:
    """Add the filter to ``uvicorn.access`` once; calling again returns the one there."""
    logger = logging.getLogger(LOGGER)
    for existing in logger.filters:
        if isinstance(existing, HealthProbeFilter):
            return existing
    added = HealthProbeFilter(paths)
    logger.addFilter(added)
    return added
