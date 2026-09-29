"""Store access. PostgreSQL, through psycopg, with no ORM.

The schema is small, the queries are few, and an ORM's main contribution here would be to
hide the SQL that makes the data flow legible. There is no migration framework either:
``schema.sql`` is idempotent and :func:`initialise` applies it.

**Every table lives in the engine's own schema.** The server is shared with other
projects, so the engine takes its own database *and* its own schema inside it, and
``search_path`` is pinned on connect. That is why every statement in this codebase names a
bare table and still cannot collide with anything else on the server.

**Every floating-point column is ``DOUBLE PRECISION``, never ``REAL``.** PostgreSQL's
``REAL`` is four bytes and loses about 1.7e-9 on a calibrated profile value. This engine's
central claim is that it reproduces a published reference to 5e-16, and a single-precision
column would quietly end that. ``tests/test_store.py`` asserts no such column exists.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row

from store.config import DatabaseConfig, load, redacted_url

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DATAFEED_SCHEMA_PATH = Path(__file__).resolve().parent / "datafeed_schema.sql"

#: Process-wide default, resolved once. Tests replace it with :func:`use_config`.
_CONFIG: DatabaseConfig | None = None


def get_config() -> DatabaseConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load()
    return _CONFIG


def use_config(config: DatabaseConfig | None) -> None:
    """Replace the process-wide configuration. ``None`` resets to the resolved default."""
    global _CONFIG
    _CONFIG = config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """An ISO-8601 UTC timestamp, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_id(prefix: str, payload: Any) -> str:
    """A deterministic content id: ``PREFIX-`` plus 16 hex of the payload's SHA-256.

    The payload is serialised with sorted keys and no insignificant whitespace, so the id
    depends on the content and not on how a dict happened to be ordered. Identical inputs
    produce identical ids, which is what lets a consumer tell whether two artefacts are
    the same artefact -- the property manual section 6 calls determinism, and the whole
    audit story rests on it.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def sha256_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, byte_size)`` for a file."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def dumps(value: Any) -> str:
    """Compact, deterministic JSON for a text column."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def loads(value: str) -> Any:
    return json.loads(value)


def upsert(
    table: str,
    columns: Sequence[str],
    conflict: Sequence[str],
    *,
    update: Sequence[str] | None = None,
) -> str:
    """Build an ``INSERT ... ON CONFLICT`` statement.

    Every write in this codebase is an upsert, because re-running the bootstrap against
    unchanged inputs must change nothing. ``DO UPDATE`` touches only the columns it is
    given; passing an empty ``update`` produces ``DO NOTHING``, which is what the seeded
    instrument register wants -- re-running must not overwrite a role edited through the
    API.
    """
    targets = list(update) if update is not None else [c for c in columns if c not in conflict]
    placeholders = ", ".join(["%s"] * len(columns))
    statement = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(conflict)}) "
    )
    if not targets:
        return statement + "DO NOTHING"
    assignments = ", ".join(f"{c} = excluded.{c}" for c in targets)
    return statement + f"DO UPDATE SET {assignments}"


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


class Connection:
    """A thin wrapper over a psycopg connection.

    Deliberately thin, and not a query builder: the SQL stays visible at the call site.
    It exists to give ``executemany`` and ``executescript`` a uniform shape and to keep
    ``conn.config`` to hand.
    """

    def __init__(self, raw: psycopg.Connection, config: DatabaseConfig) -> None:
        self._raw = raw
        self.config = config

    @property
    def raw(self) -> psycopg.Connection:
        """The underlying driver connection, for the rare need this does not cover."""
        return self._raw

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._raw.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> Any:
        rows = [tuple(r) for r in rows]
        if not rows:
            return None
        with self._raw.cursor() as cur:
            return cur.executemany(sql, rows)

    def executescript(self, sql: str) -> None:
        """Run a multi-statement script.

        psycopg sends a whole block in one round trip as long as it carries no parameters,
        which the schema file does not.
        """
        with self._raw.cursor() as cur:
            cur.execute(sql)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def _open(config: DatabaseConfig, *, dbname: str | None = None,
          autocommit: bool = False) -> Connection:
    raw = psycopg.connect(
        config.conninfo(dbname=dbname), row_factory=dict_row, autocommit=autocommit
    )
    if dbname is None:
        # Safe to interpolate: config._identifier has already restricted the name to
        # [A-Za-z_][A-Za-z0-9_]*, and SET does not accept a bound parameter.
        # The engine's own schema first, then the shared source data. An
        # unqualified name therefore resolves to this engine's artefact if it
        # has one, and otherwise to the feed -- which is the read path the
        # datafeed contract describes.
        raw.execute(
            f"SET search_path TO {config.schema}, {config.datafeed_schema}, public"
        )
        if not autocommit:
            raw.commit()
    return Connection(raw, config)


def connect(config: DatabaseConfig | None = None) -> Connection:
    """Open a connection to the configured store, with the search path pinned."""
    return _open(config or get_config())


@contextmanager
def session(config: DatabaseConfig | None = None) -> Iterator[Connection]:
    """A connection that commits on success and rolls back on any exception."""
    conn = connect(config)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def datafeed_session(config: DatabaseConfig | None = None) -> Iterator[Connection]:
    """A session whose search path puts the shared feed schema **first**.

    The engine's own schema and the feed both define a ``source_file`` table, and the
    default search path resolves an unqualified name to the engine's. That is right for an
    engine reading its own artefacts and wrong for a loader writing the feed, which would
    silently write to the engine's copy. The loaders that populate ``datafeed`` use this;
    everything else uses :func:`session`.
    """
    conn = connect(config)
    try:
        conn.execute(f"SET search_path TO {conn.config.datafeed_schema}, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Creating the store
# ---------------------------------------------------------------------------


def create_database(config: DatabaseConfig | None = None) -> bool:
    """Create the engine's database if it is absent. Returns whether it created one.

    A database cannot be created from inside itself, so this connects to
    ``maintenance_dbname``. Many managed providers forbid ``CREATE DATABASE``; there,
    point ``dbname`` at the database they gave you and rely on the schema for isolation.
    The failure is reported plainly rather than swallowed.
    """
    resolved = config or get_config()
    admin = _open(resolved, dbname=resolved.maintenance_dbname, autocommit=True)
    try:
        row = admin.execute(
            "SELECT 1 AS present FROM pg_database WHERE datname = %s", (resolved.dbname,)
        ).fetchone()
        if row:
            return False
        admin.execute(f'CREATE DATABASE "{resolved.dbname}"')
        return True
    finally:
        admin.close()


def initialise(config: DatabaseConfig | None = None) -> None:
    """Create the engine's schema and apply ``schema.sql``. Safe to call repeatedly."""
    with session(config) as conn:
        c = conn.config
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {c.datafeed_schema}")
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {c.schema}")
        # The shared feed first: the engine's own tables may reference it.
        conn.execute(f"SET search_path TO {c.datafeed_schema}, public")
        conn.executescript(DATAFEED_SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(f"SET search_path TO {c.schema}, {c.datafeed_schema}, public")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def drop_schema(config: DatabaseConfig | None = None, *, include_datafeed: bool = False) -> None:
    """Remove the engine's schema and everything in it. Used by the test fixtures.

    **The shared feed is not dropped unless explicitly asked for**, and there is a scar
    behind that default. An earlier version dropped both, while the test fixture renamed
    only the engine schema -- so every test run deleted the real ``datafeed`` schema and
    the 117 series in it. A cleanup routine that reaches outside the thing it was given is
    a destructive bug waiting for the moment you are not watching.
    """
    resolved = config or get_config()
    with session(resolved) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {resolved.schema} CASCADE")
        if include_datafeed:
            conn.execute(f"DROP SCHEMA IF EXISTS {resolved.datafeed_schema} CASCADE")


def register_source(conn: Connection, *, name: str, path: Path, note: str = "",
                    origin_kind: str | None = None) -> str:
    """Record a source file's hash and return it.

    Re-registering the same name with different bytes overwrites the row, so the store
    always describes the bytes currently loaded rather than the first ones ever seen.

    ``origin_kind`` is written only when given, because the two ``source_file`` tables
    differ: the feed's requires it, the engine's older copy does not have the column.
    That divergence is temporary -- provenance of source data belongs to the feed, and the
    engine's copy should go once Fund Map reads through ``Panel``.
    """
    digest, size = sha256_file(path)
    columns = ["name", "sha256", "byte_size", "loaded_at", "origin", "note"]
    values = [name, digest, size, utc_now(), str(Path(path).resolve()), note]
    if origin_kind is not None:
        columns.append("origin_kind")
        values.append(origin_kind)
    conn.execute(upsert("source_file", tuple(columns), ("name",)), tuple(values))
    return digest


def describe() -> dict[str, Any]:
    """A safe summary of where the store is. Never includes the password."""
    config = get_config()
    return {**config.describe(), "url": redacted_url(config)}
