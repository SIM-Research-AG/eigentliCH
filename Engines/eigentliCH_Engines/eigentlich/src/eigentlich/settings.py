"""Settings: where ``config.yaml`` is read, and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  EIGENTLICH_DATABASE_URL / DATABASE_URL  <  EIGENTLICH_*  <  overrides

``config.yaml`` is committed and never holds a password. ``config.local.yaml`` is git-ignored and is
where a developer keeps the local container's passwords; in deployment they come from
``EIGENTLICH_DB_PASSWORD`` (and ``EIGENTLICH_CURATOR_PASSWORD`` for the tests' curator connection) or
a full ``EIGENTLICH_DATABASE_URL``.

The database name and schema are the only values ever interpolated into SQL as text, so both are
validated as plain identifiers here, once, at load time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

#: The package folder: ``eigentliCH_Engines/eigentlich``. ``config.yaml`` lives here, beside ``src``.
ROOT = Path(__file__).resolve().parents[2]

PREFIX = "EIGENTLICH_"


class ConfigError(ValueError):
    """The configuration is unusable. The message names the offending value."""


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def identifier(value: str, what: str) -> str:
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
    schema: str = "eigentlich"
    user: str = "eigentlich"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout: int = 10

    def conninfo(self, *, user: Optional[str] = None, password: Optional[str] = None) -> str:
        parts = {
            "host": self.host, "port": self.port, "dbname": self.dbname,
            "user": user or self.user, "sslmode": self.sslmode, "connect_timeout": self.connect_timeout,
        }
        pw = self.password if password is None else password
        if pw:
            parts["password"] = pw
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def redacted_url(self) -> str:
        return (f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}"
                f"?schema={self.schema}")

    def describe(self) -> dict[str, Any]:
        """Safe to publish: never contains the password."""
        return {"backend": "postgresql", "host": self.host, "port": self.port, "dbname": self.dbname,
                "schema": self.schema, "user": self.user, "sslmode": self.sslmode,
                "password_set": bool(self.password), "url": self.redacted_url()}


@dataclass(frozen=True)
class CuratorConfig:
    """The cockpit's login role. This package never writes as it; the tests connect as it to prove
    what it can and cannot do."""

    user: str = "curator"
    password: str = ""


@dataclass(frozen=True)
class Settings:
    database: DatabaseConfig
    curator: CuratorConfig
    prototype_root: Path
    migrate_from: Path
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
    f"{PREFIX}DB_HOST": ("host", str),
    f"{PREFIX}DB_PORT": ("port", int),
    f"{PREFIX}DB_NAME": ("dbname", str),
    f"{PREFIX}DB_SCHEMA": ("schema", str),
    f"{PREFIX}DB_USER": ("user", str),
    f"{PREFIX}DB_PASSWORD": ("password", str),
    f"{PREFIX}DB_SSLMODE": ("sslmode", str),
}


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """Read the configuration. ``overrides`` is a partial config tree, applied last."""
    if path is None:
        path = Path(os.environ[f"{PREFIX}CONFIG"]) if os.environ.get(f"{PREFIX}CONFIG") else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    sources = [str(path)]
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
        sources.append(str(local))

    db = dict(tree.get("database") or {})
    url = os.environ.get(f"{PREFIX}DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        db.update(_from_url(url))
        sources.append("env: database url")
    for var, (key, cast) in _DB_ENV.items():
        if var in os.environ:
            db[key] = cast(os.environ[var])
            sources.append(f"env: {var}")
    tree["database"] = db

    curator = dict(tree.get("curator") or {})
    for var, key in ((f"{PREFIX}CURATOR_USER", "user"), (f"{PREFIX}CURATOR_PASSWORD", "password")):
        if var in os.environ:
            curator[key] = os.environ[var]
            sources.append(f"env: {var}")
    tree["curator"] = curator

    src = dict(tree.get("sources") or {})
    for var, key in ((f"{PREFIX}PROTOTYPE_ROOT", "prototype_root"), (f"{PREFIX}MIGRATE_FROM", "migrate_from")):
        if var in os.environ:
            src[key] = os.environ[var]
            sources.append(f"env: {var}")
    tree["sources"] = src

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, tuple(sources))


def _build(tree: Mapping[str, Any], sources: tuple[str, ...]) -> Settings:
    db = tree["database"]
    known = set(DatabaseConfig.__dataclass_fields__)  # type: ignore[attr-defined]
    extra = set(db) - known
    if extra:
        raise ConfigError(f"unknown database keys: {sorted(extra)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=identifier(database.dbname, "dbname"),
                       schema=identifier(database.schema, "schema"), port=int(database.port))

    cur = tree.get("curator") or {}
    extra = set(cur) - set(CuratorConfig.__dataclass_fields__)  # type: ignore[attr-defined]
    if extra:
        raise ConfigError(f"unknown curator keys: {sorted(extra)}")
    curator = replace(CuratorConfig(), **cur)

    src = tree.get("sources") or {}
    try:
        prototype_root = Path(src["prototype_root"])
        migrate_from = Path(src["migrate_from"])
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing sources.{exc.args[0]}") from exc
    return Settings(database=database, curator=curator, prototype_root=prototype_root,
                    migrate_from=migrate_from, sources=sources)


def with_schema(settings: Settings, schema: str) -> Settings:
    """The same settings pointed at another schema (the tests' throwaway ``t_<hex>``)."""
    return replace(settings, database=replace(settings.database, schema=identifier(schema, "schema")))
