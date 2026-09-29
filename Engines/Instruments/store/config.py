"""Where the store lives, and how to reach it.

One resolved :class:`DatabaseConfig`, built from three sources in a fixed order of
precedence: **environment beats file beats default.** That order is not arbitrary. A
password in a committed file is a leak; a password in the environment is how every
deployment target already expects to be configured. So the file is for the shape of the
setup -- which host, which database, which schema -- and the environment is for the
secret and for whatever the deployment overrides.

**One database, one schema per engine, one role per engine.** The system shares a single
database, ``simtech``; this engine owns the schema ``fmre`` and connects as the role of the
same name. The role owns its own schemas and holds ``SELECT`` and nothing more on the
shared feed, so writing outside its own schema is refused by the server rather than by a
convention.

``fmre_feed`` is an interim second schema: Fund Map still keeps a private copy of the
series it reads, and it goes away when the engine reads Engine 01's ``Panel`` instead. It
is deliberately **not** called ``datafeed``, because that name belongs to Engine 01 and two
different schemas answering to it is what the consolidation was for.

See ``store/provision.py`` for the layout and the grants.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent

#: Searched in order; the first that exists wins. ``config.toml`` is deliberately absent
#: from the repository -- see ``config.example.toml``.
CONFIG_CANDIDATES = (
    Path(os.environ.get("INSTRUMENTS_CONFIG", "")) if os.environ.get("INSTRUMENTS_CONFIG") else None,
    ROOT / "config.toml",
    ROOT / "config.example.toml",
)

DEFAULT_DBNAME = "simtech"
DEFAULT_SCHEMA = "fmre"
#: The shared source-data schema. Every engine reads from it; only the
#: datafeed loaders write to it.
DEFAULT_DATAFEED_SCHEMA = "fmre_feed"


class ConfigError(ValueError):
    """Raised when the configuration is present but does not make sense."""


def _identifier(value: str, what: str) -> str:
    """Validate a database or schema name.

    These two names are the only configuration values that end up interpolated into SQL
    rather than bound as parameters -- ``CREATE SCHEMA`` and ``SET search_path`` cannot
    take a placeholder. So they are checked against a deliberately narrow pattern here,
    at the point they are read, instead of being trusted at the point they are used.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ConfigError(f"{what} cannot be empty")
    if len(cleaned) > 63:
        raise ConfigError(f"{what} {cleaned!r} is longer than PostgreSQL's 63-byte limit")
    if not cleaned[0].isalpha() and cleaned[0] != "_":
        raise ConfigError(f"{what} {cleaned!r} must start with a letter or underscore")
    if not all(c.isalnum() or c == "_" for c in cleaned):
        raise ConfigError(
            f"{what} {cleaned!r} may contain only letters, digits and underscores"
        )
    return cleaned.lower()


@dataclass(frozen=True)
class DatabaseConfig:
    """A resolved target for the store."""

    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = DEFAULT_DBNAME
    user: str = "postgres"
    password: str = ""
    sslmode: str = "prefer"
    schema: str = DEFAULT_SCHEMA
    datafeed_schema: str = DEFAULT_DATAFEED_SCHEMA
    connect_timeout: int = 10
    #: The database to connect to when creating :attr:`dbname`, which cannot be created
    #: from inside itself. Almost always ``postgres``.
    maintenance_dbname: str = "postgres"
    #: Where the values actually came from, for the diagnostics endpoint.
    sources: tuple[str, ...] = field(default_factory=tuple)

    def conninfo(self, *, dbname: str | None = None) -> str:
        """A libpq connection string. Never logged -- it carries the password."""
        parts = {
            "host": self.host,
            "port": str(self.port),
            "dbname": dbname or self.dbname,
            "user": self.user,
            "connect_timeout": str(self.connect_timeout),
        }
        if self.password:
            parts["password"] = self.password
        if self.sslmode:
            parts["sslmode"] = self.sslmode
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def describe(self) -> dict[str, Any]:
        """A safe summary for logs and the health endpoint. **Never includes the password.**"""
        return {
            "backend": "postgresql",
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "schema": self.schema,
            "datafeed_schema": self.datafeed_schema,
            "user": self.user,
            "sslmode": self.sslmode,
            "password_set": bool(self.password),
            "config_sources": list(self.sources),
        }


def _quote_libpq(value: str) -> str:
    if value == "" or any(c.isspace() or c in "'\\" for c in value):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return value


def _load_file() -> tuple[dict[str, Any], str | None]:
    for candidate in CONFIG_CANDIDATES:
        if candidate and candidate.is_file():
            with candidate.open("rb") as handle:
                return tomllib.load(handle), str(candidate)
    return {}, None


def _from_url(url: str) -> dict[str, Any]:
    """Parse a ``postgresql://`` URL, which is how hosted providers hand out credentials."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ConfigError(
            f"a database URL must use the postgresql:// scheme, got {parsed.scheme!r}"
        )
    out: dict[str, Any] = {}
    if parsed.hostname:
        out["host"] = parsed.hostname
    if parsed.port:
        out["port"] = parsed.port
    if parsed.username:
        out["user"] = parsed.username
    if parsed.password:
        out["password"] = parsed.password
    if parsed.path and parsed.path != "/":
        out["dbname"] = parsed.path.lstrip("/")
    for pair in (parsed.query or "").split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        if key in ("sslmode", "schema"):
            out[key] = value
    return out


def load(overrides: dict[str, Any] | None = None) -> DatabaseConfig:
    """Resolve the database configuration.

    Precedence, lowest to highest: built-in defaults, the config file, ``DATABASE_URL`` or
    ``INSTRUMENTS_DATABASE_URL``, individual ``INSTRUMENTS_DB_*`` variables, and finally
    anything passed in ``overrides`` (which exists so tests can point at a temp database
    without touching the process environment).
    """
    sources: list[str] = ["defaults"]
    file_data, file_path = _load_file()
    if file_path:
        sources.append(file_path)

    database = dict(file_data.get("database", {}))
    values: dict[str, Any] = dict(database.get("postgresql", {}))

    url = (
        os.environ.get("INSTRUMENTS_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or values.pop("url", None)
    )
    if url:
        values.update(_from_url(url))
        sources.append("database url")

    env_map = {
        "INSTRUMENTS_DB_HOST": ("host", str),
        "INSTRUMENTS_DB_PORT": ("port", int),
        "INSTRUMENTS_DB_NAME": ("dbname", str),
        "INSTRUMENTS_DB_USER": ("user", str),
        "INSTRUMENTS_DB_PASSWORD": ("password", str),
        "INSTRUMENTS_DB_SSLMODE": ("sslmode", str),
        "INSTRUMENTS_DB_SCHEMA": ("schema", str),
        "INSTRUMENTS_DB_DATAFEED_SCHEMA": ("datafeed_schema", str),
    }
    env_used = []
    for variable, (key, cast) in env_map.items():
        raw = os.environ.get(variable)
        if raw is None or raw == "":
            continue
        env_used.append(variable)
        values[key] = cast(raw)
    if env_used:
        sources.append("env: " + ", ".join(sorted(env_used)))

    if overrides:
        values.update(overrides)
        sources.append("explicit override")

    return DatabaseConfig(
        host=str(values.get("host", "127.0.0.1")),
        port=int(values.get("port", 5432)),
        dbname=_identifier(str(values.get("dbname", DEFAULT_DBNAME)), "dbname"),
        user=str(values.get("user", "postgres")),
        password=str(values.get("password", "")),
        sslmode=str(values.get("sslmode", "prefer")),
        schema=_identifier(str(values.get("schema", DEFAULT_SCHEMA)), "schema"),
        datafeed_schema=_identifier(
            str(values.get("datafeed_schema", DEFAULT_DATAFEED_SCHEMA)), "datafeed_schema"),
        connect_timeout=int(values.get("connect_timeout", 10)),
        maintenance_dbname=str(values.get("maintenance_dbname", "postgres")),
        sources=tuple(sources),
    )


def redacted_url(config: DatabaseConfig) -> str:
    """A URL safe to print: the password is replaced, never shown."""
    auth = quote(config.user, safe="")
    if config.password:
        auth += ":***"
    return f"postgresql://{auth}@{config.host}:{config.port}/{config.dbname}?schema={config.schema}"
