"""Concurrency regressions.

**Why this file exists.** An earlier version of the store shipped two defects that the
entire rest of the suite passed straight over, because FastAPI's ``TestClient`` serialises
requests onto a single thread. Both appeared the moment a browser opened the test bench
and issued six fetches at once. The lesson outlived the backend they were found in:

* FastAPI runs a generator dependency's **setup and teardown in different threadpool
  threads**, so a connection opened for a request is released from another one. Any driver
  with a same-thread guard fails there, and only under concurrency.
* A statement that takes an exclusive lock must never sit on the connection-open path. The
  original offender was ``PRAGMA journal_mode``; the equivalent here would be anything
  that creates or alters on connect, which is why :func:`store.db.connect` does nothing
  but ``SET search_path``.

So every engine gets a test that issues the front end's whole opening burst from a thread
pool. A suite that only ever exercises one request at a time cannot see this class of bug.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from store import db
from tests.conftest import needs_feed, needs_sources

MANIFEST_COLUMNS = (
    "run_id", "engine", "engine_version", "started_at", "finished_at",
    "wall_clock_ms", "inputs_json", "params_hash", "outputs_json", "status",
)


class TestConnections:
    def test_a_connection_survives_moving_between_threads(self, store):
        """The exact lifecycle FastAPI imposes: open in A, use in B, release in C."""
        box: dict[str, object] = {}
        errors: list[Exception] = []

        def step(fn):
            def run():
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            thread.join()

        step(lambda: box.__setitem__("conn", db.connect()))
        step(lambda: box.__setitem__(
            "rows", box["conn"].execute("SELECT COUNT(*) AS n FROM instrument").fetchone()["n"]
        ))
        step(lambda: box["conn"].close())

        assert not errors, f"moving the connection between threads raised: {errors!r}"
        assert box["rows"] == 0

    def test_opening_a_connection_takes_no_exclusive_lock(self, store):
        """Eight simultaneous opens while a writer holds a transaction.

        The shape of the original defect: opening a connection in order to *read* must not
        contend with a write in flight.
        """
        errors: list[Exception] = []
        barrier = threading.Barrier(9)

        def reader():
            try:
                barrier.wait(timeout=20)
                with db.session() as conn:
                    conn.execute("SELECT COUNT(*) FROM calibration").fetchone()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer():
            try:
                barrier.wait(timeout=20)
                with db.session() as conn:
                    conn.execute(
                        db.upsert("run_manifest", MANIFEST_COLUMNS, ("run_id",)),
                        ("RUN-lock", "t", "v", "t", "t", 1.0, "{}", "p", "{}", "ok"),
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=9) as pool:
            futures = [pool.submit(reader) for _ in range(8)] + [pool.submit(writer)]
            for future in futures:
                future.result()

        assert not errors, f"concurrent access raised: {errors!r}"

    def test_connections_are_released_rather_than_leaked(self, store):
        """A connection is a server-side resource and the default server allows 100.

        Sixty-four sessions in quick succession would exhaust a leaking pool; the idle
        count afterwards is the direct check.
        """
        errors: list[Exception] = []

        def worker(n: int):
            try:
                for _ in range(8):
                    with db.session() as conn:
                        conn.execute(
                            db.upsert("run_manifest", MANIFEST_COLUMNS, ("run_id",)),
                            (f"RUN-{n}", "t", "v", "t", "t", 1.0, "{}", "p", "{}", "ok"),
                        )
                        conn.execute("SELECT COUNT(*) FROM run_manifest").fetchone()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for future in [pool.submit(worker, i) for i in range(8)]:
                future.result()

        assert not errors, f"concurrent access raised: {errors!r}"

        with db.session() as conn:
            idle = conn.execute(
                "SELECT COUNT(*) AS n FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle'"
            ).fetchone()["n"]
        assert idle < 10, f"{idle} idle connections left behind; the request path is leaking"


@needs_sources
@needs_feed
class TestApiUnderLoad:
    """The whole test bench's opening burst, issued at once from many threads."""

    #: Every endpoint the test bench calls while rendering its seven tabs.
    PAGE_LOAD = [
        "/v1/health",
        "/v1/calibration",
        "/v1/diagnostics/shapes",
        "/v1/roles",
        "/v1/market-environment",
        "/v1/calibration/blocks",
        "/v1/return-set?include_instruments=true",
        "/v1/diagnostics/coverage",
        "/v1/instruments",
        "/v1/state-map",
        "/v1/market-risk-signal?limit=12",
        "/v1/diagnostics/recomposition",
        "/v1/diagnostics/expected",
        "/v1/runs?limit=12",
    ]

    @pytest.fixture(scope="class")
    def client(self, module_store):
        from fastapi.testclient import TestClient
        from store.etl import bootstrap

        bootstrap.main([])
        from api.main import app
        with TestClient(app) as c:
            yield c

    def test_the_whole_page_load_issued_concurrently(self, client):
        def call(path: str) -> tuple[str, int, str]:
            response = client.get(path)
            return path, response.status_code, response.text[:200]

        with ThreadPoolExecutor(max_workers=len(self.PAGE_LOAD)) as pool:
            results = list(pool.map(call, self.PAGE_LOAD))

        failures = [(p, code, body) for p, code, body in results if code != 200]
        assert not failures, "concurrent page load failed:\n" + "\n".join(
            f"  {p} -> {code}: {body}" for p, code, body in failures
        )

    def test_repeated_concurrent_bursts_stay_clean(self, client):
        """Once is luck. The original defects were intermittent and moved between endpoints."""
        for _ in range(3):
            with ThreadPoolExecutor(max_workers=8) as pool:
                codes = list(pool.map(lambda p: client.get(p).status_code, self.PAGE_LOAD))
            assert set(codes) == {200}, f"a burst returned {sorted(set(codes))}"

    def test_concurrent_writers_do_not_deadlock(self, client):
        """Several endpoints write a run manifest; they must not lock each other out."""
        with ThreadPoolExecutor(max_workers=6) as pool:
            codes = list(pool.map(lambda _: client.get("/v1/return-set").status_code, range(6)))
        assert set(codes) == {200}
