"""Settings: where ``config.yaml`` is read, and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  CYCLE_DATABASE_URL / DATABASE_URL  <  CYCLE_*  <  overrides

``config.yaml`` is committed and describes the shape of the setup: port, upstream, default
economies, active calibration. It never holds a password. ``config.local.yaml`` is git-ignored and
is where a developer keeps the local container's password; in deployment the password
comes from ``CYCLE_DB_PASSWORD`` or a full ``CYCLE_DATABASE_URL``.

The database name and schema are the only values ever interpolated into SQL as text, so
both are validated as plain identifiers here, once, at load time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

#: The engine folder: ``engines/cycle``. ``config.yaml`` lives here, beside ``src``.
ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """The configuration is unusable. The message names the offending value."""


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str, what: str) -> str:
    if not value or len(value.encode("utf-8")) > 63 or not _IDENTIFIER.match(value):
        raise ConfigError(f"{what} {value!r} must be a plain SQL identifier of at most 63 bytes")
    return value.lower()


def _quote_libpq(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "simtech"
    schema: str = "cycle"
    user: str = "cycle"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout: int = 10
    maintenance_dbname: str = "postgres"

    def conninfo(self, *, dbname: Optional[str] = None) -> str:
        parts = {
            "host": self.host, "port": self.port, "dbname": dbname or self.dbname,
            "user": self.user, "sslmode": self.sslmode, "connect_timeout": self.connect_timeout,
        }
        if self.password:
            parts["password"] = self.password
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def redacted_url(self) -> str:
        return (f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}"
                f"?schema={self.schema}")

    def describe(self) -> dict[str, Any]:
        """Safe to publish: never contains the password."""
        return {
            "backend": "postgresql", "host": self.host, "port": self.port,
            "dbname": self.dbname, "schema": self.schema, "user": self.user,
            "sslmode": self.sslmode, "password_set": bool(self.password),
            "url": self.redacted_url(),
        }


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    datafeed_url: str
    datafeed_timeout_s: float
    macrofield_url: str
    macrofield_timeout_s: float
    #: Default economies, as datafeed country codes (validated against datafeed at run time).
    default_economies: tuple[str, ...]
    #: Project the anchored cycles to macrofield's horizon when a request does not say.
    default_project: bool
    active_calibration: str
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
    out: dict[str, Any] = {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
    }
    if parsed.path.strip("/"):
        out["dbname"] = parsed.path.strip("/")
    for key in ("sslmode", "schema"):
        if key in query:
            out[key] = query[key]
    return out


_DB_ENV = {
    "CYCLE_DB_HOST": ("host", str),
    "CYCLE_DB_PORT": ("port", int),
    "CYCLE_DB_NAME": ("dbname", str),
    "CYCLE_DB_SCHEMA": ("schema", str),
    "CYCLE_DB_USER": ("user", str),
    "CYCLE_DB_PASSWORD": ("password", str),
    "CYCLE_DB_SSLMODE": ("sslmode", str),
}


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """Read the configuration. ``overrides`` is a partial config tree, applied last."""
    if path is None:
        path = Path(os.environ["CYCLE_CONFIG"]) if os.environ.get("CYCLE_CONFIG") else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    sources = [str(path)]
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
        sources.append(str(local))

    db = dict(tree.get("database") or {})
    url = os.environ.get("CYCLE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        db.update(_from_url(url))
        sources.append("env: database url")
    for var, (key, cast) in _DB_ENV.items():
        if var in os.environ:
            db[key] = cast(os.environ[var])
            sources.append(f"env: {var}")
    tree["database"] = db

    service = dict(tree.get("service") or {})
    if "CYCLE_HOST" in os.environ:
        service["host"] = os.environ["CYCLE_HOST"]
    if "CYCLE_PORT" in os.environ:
        service["port"] = int(os.environ["CYCLE_PORT"])
    if "CYCLE_CORS_ORIGINS" in os.environ:
        service["cors_origins"] = [o.strip() for o in os.environ["CYCLE_CORS_ORIGINS"].split(",") if o.strip()]
    tree["service"] = service

    upstream = dict(tree.get("upstream") or {})
    if "CYCLE_DATAFEED_URL" in os.environ:
        upstream["datafeed_url"] = os.environ["CYCLE_DATAFEED_URL"]
    if "CYCLE_MACROFIELD_URL" in os.environ:
        upstream["macrofield_url"] = os.environ["CYCLE_MACROFIELD_URL"]
    tree["upstream"] = upstream

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, tuple(sources))


def _build(tree: Mapping[str, Any], sources: tuple[str, ...]) -> Settings:
    try:
        service = tree["service"]
        upstream = tree["upstream"]
        run = tree["run"]
        db = tree["database"]
        active = tree["calibration"]["active"]
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing the {exc.args[0]!r} section") from exc

    default_economies = tuple(str(c) for c in run.get("economies") or ())
    if not default_economies:
        raise ConfigError("run.economies needs at least one country code")
    if len(set(default_economies)) != len(default_economies):
        raise ConfigError("run.economies lists a country twice")

    known = {f.name for f in DatabaseConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    extra = set(db) - known
    if extra:
        raise ConfigError(f"unknown database keys: {sorted(extra)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=_identifier(database.dbname, "dbname"),
                       schema=_identifier(database.schema, "schema"),
                       port=int(database.port))

    return Settings(
        host=str(service.get("host", "127.0.0.1")),
        port=int(service["port"]),
        cors_origins=tuple(service.get("cors_origins") or ("*",)),
        datafeed_url=str(upstream["datafeed_url"]).rstrip("/"),
        datafeed_timeout_s=float(upstream.get("timeout_s", 30)),
        macrofield_url=str(upstream["macrofield_url"]).rstrip("/"),
        macrofield_timeout_s=float(upstream.get("macrofield_timeout_s", 60)),
        default_economies=default_economies,
        default_project=bool(run.get("project", True)),
        active_calibration=str(active),
        database=database,
        sources=sources,
    )
