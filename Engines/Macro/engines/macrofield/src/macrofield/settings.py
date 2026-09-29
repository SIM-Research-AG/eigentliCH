"""Settings: where ``config.yaml`` is read, and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  MACROFIELD_DATABASE_URL / DATABASE_URL  <  MACROFIELD_*
                 <  overrides

``config.yaml`` is committed and never holds a password. ``config.local.yaml`` is git-ignored
and holds the local container's password; in deployment it comes from ``MACROFIELD_DB_PASSWORD``
or a full ``MACROFIELD_DATABASE_URL``. Model parameters are not here: they are versioned
calibrations (calibration.py, ``PUT /calibration``).

The database name and schema are the only values interpolated into SQL as text, so both are
validated as plain identifiers here, once. Same shape as the ``honi`` engine's settings.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

#: The engine folder: ``engines/macrofield``. ``config.yaml`` lives here, beside ``src``.
ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """The configuration is unusable. The message names the offending value."""


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str, what: str) -> str:
    if not value or len(value.encode("utf-8")) > 63 or not _IDENTIFIER.match(value):
        raise ConfigError(f"{what} {value!r} must be a plain SQL identifier of at most 63 bytes")
    return value.lower()


def _quote_libpq(value: Any) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "simtech"
    schema: str = "macrofield"
    user: str = "macrofield"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout: int = 10
    maintenance_dbname: str = "postgres"

    def conninfo(self, *, dbname: Optional[str] = None) -> str:
        parts = {"host": self.host, "port": self.port, "dbname": dbname or self.dbname,
                 "user": self.user, "sslmode": self.sslmode,
                 "connect_timeout": self.connect_timeout}
        if self.password:
            parts["password"] = self.password
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def redacted_url(self) -> str:
        return (f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}"
                f"?schema={self.schema}")

    def describe(self) -> dict[str, Any]:
        """Safe to publish: never contains the password."""
        return {"backend": "postgresql", "host": self.host, "port": self.port,
                "dbname": self.dbname, "schema": self.schema, "user": self.user,
                "sslmode": self.sslmode, "password_set": bool(self.password),
                "url": self.redacted_url()}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    active_calibration: str
    #: Worker processes a run spreads its economies over. 1 runs them in the service process.
    max_workers: int
    #: Folder holding the frozen raw snapshot and its MANIFEST.json.
    raw_dir: Path
    database: DatabaseConfig
    sources: tuple[str, ...] = field(default=())


def _deep_merge(base: dict[str, Any], top: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in top.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(dict(out[key]), value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not hold a mapping")
    return data


def _from_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ConfigError("a database URL must start with postgresql://")
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    out: dict[str, Any] = {"host": parsed.hostname or "127.0.0.1", "port": parsed.port or 5432,
                           "user": unquote(parsed.username or ""),
                           "password": unquote(parsed.password or "")}
    if parsed.path.strip("/"):
        out["dbname"] = parsed.path.strip("/")
    for key in ("sslmode", "schema"):
        if key in query:
            out[key] = query[key]
    return out


_DB_ENV = {
    "MACROFIELD_DB_HOST": ("host", str),
    "MACROFIELD_DB_PORT": ("port", int),
    "MACROFIELD_DB_NAME": ("dbname", str),
    "MACROFIELD_DB_SCHEMA": ("schema", str),
    "MACROFIELD_DB_USER": ("user", str),
    "MACROFIELD_DB_PASSWORD": ("password", str),
    "MACROFIELD_DB_SSLMODE": ("sslmode", str),
}


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """Read the configuration. ``overrides`` is a partial config tree, applied last."""
    if path is None:
        env = os.environ.get("MACROFIELD_CONFIG")
        path = Path(env) if env else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    sources = [str(path)]
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
        sources.append(str(local))

    db = dict(tree.get("database") or {})
    url = os.environ.get("MACROFIELD_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        db.update(_from_url(url))
        sources.append("env: database url")
    for var, (key, cast) in _DB_ENV.items():
        if var in os.environ:
            db[key] = cast(os.environ[var])
            sources.append(f"env: {var}")
    tree["database"] = db

    service = dict(tree.get("service") or {})
    if "MACROFIELD_HOST" in os.environ:
        service["host"] = os.environ["MACROFIELD_HOST"]
    if "MACROFIELD_PORT" in os.environ:
        service["port"] = int(os.environ["MACROFIELD_PORT"])
    if "MACROFIELD_CORS_ORIGINS" in os.environ:
        service["cors_origins"] = [o.strip() for o in
                                   os.environ["MACROFIELD_CORS_ORIGINS"].split(",") if o.strip()]
    tree["service"] = service

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, tuple(sources), path.parent)


def _build(tree: Mapping[str, Any], sources: tuple[str, ...], base: Path) -> Settings:
    try:
        service, run, data, db = tree["service"], tree["run"], tree["data"], tree["database"]
        active = tree["calibration"]["active"]
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing the {exc.args[0]!r} section") from exc

    known = set(DatabaseConfig.__dataclass_fields__)  # type: ignore[attr-defined]
    extra = set(db) - known
    if extra:
        raise ConfigError(f"unknown database keys: {sorted(extra)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=_identifier(database.dbname, "dbname"),
                       schema=_identifier(database.schema, "schema"), port=int(database.port))

    workers = int(run.get("max_workers", 1))
    if workers < 1:
        raise ConfigError("run.max_workers must be at least 1")
    raw_dir = Path(str(data["raw_dir"]))
    if not raw_dir.is_absolute():
        raw_dir = (base / raw_dir).resolve()

    return Settings(
        host=str(service.get("host", "127.0.0.1")),
        port=int(service["port"]),
        cors_origins=tuple(service.get("cors_origins") or ("*",)),
        active_calibration=str(active),
        max_workers=workers,
        raw_dir=raw_dir,
        database=database,
        sources=sources,
    )
