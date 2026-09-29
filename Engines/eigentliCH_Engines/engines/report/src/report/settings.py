"""Settings: where ``config.yaml`` is read, and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  CHATBOT_DATABASE_URL / DATABASE_URL  <  CHATBOT_*  <  overrides

``config.yaml`` is committed and describes the shape of the setup: port, the upstream engines, the
model service, the store, the active calibration. It never holds a secret. ``config.local.yaml`` is git-ignored and
holds the local database password. The spark7 access token is read from the environment, and from
the family ``.env`` (git-ignored) for any variable the environment does not already set; the file is
parsed here, in a few lines, because ``python-dotenv`` is not on the allowlist.

The database name and schema are the only values ever interpolated into SQL as text, so both are
validated as plain identifiers here, once, at load time. The model host is checked here too, at
load time and so at start: a service that comes up and fails at its first question has already
broken the rule (REP-04).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

from .spark7 import ModelConfigError, ModelSettings, check_host

#: The engine folder: ``engines/report``. ``config.yaml`` lives here, beside ``src``.
ROOT = Path(__file__).resolve().parents[2]

PREFIX = "REPORT_"


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
    schema: str = "report"
    user: str = "report"
    password: str = field(default="", repr=False)
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
    pcp_url: str
    lbs_url: str
    upstream_timeout_s: float
    model: ModelSettings
    active_calibration: str
    database: DatabaseConfig
    #: The variables the model client may read its secret headers from: the process environment
    #: over the family ``.env``. ``repr=False``: this mapping holds the token.
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    sources: tuple[str, ...] = field(default=())
    #: lbsim (Engine 14, REP-32): findings, paths and plan, ``GET /artefacts/{id}``.
    lbsim_url: str = "http://127.0.0.1:8014"


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


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a ``.env`` file. Comments, blanks and ``export`` are tolerated; quotes and
    carriage returns are stripped. A missing file is an empty mapping, not an error: a deployment may
    set the variables in the environment instead."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.replace("\r", "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


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


def _switch(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """Read the configuration. ``overrides`` is a partial config tree, applied last."""
    if path is None:
        env_path = os.environ.get(f"{PREFIX}CONFIG")
        path = Path(env_path) if env_path else ROOT / "config.yaml"
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

    service = dict(tree.get("service") or {})
    if f"{PREFIX}HOST" in os.environ:
        service["host"] = os.environ[f"{PREFIX}HOST"]
    if f"{PREFIX}PORT" in os.environ:
        service["port"] = int(os.environ[f"{PREFIX}PORT"])
    if f"{PREFIX}CORS_ORIGINS" in os.environ:
        service["cors_origins"] = [o.strip() for o in os.environ[f"{PREFIX}CORS_ORIGINS"].split(",") if o.strip()]
    tree["service"] = service

    upstream = dict(tree.get("upstream") or {})
    for key in ("pcp_url", "lbs_url", "lbsim_url"):
        var = f"{PREFIX}{key.upper()}"
        if var in os.environ:
            upstream[key] = os.environ[var]
            sources.append(f"env: {var}")
    tree["upstream"] = upstream

    model = dict(tree.get("model") or {})
    if os.environ.get(f"{PREFIX}MODEL_URL", "").strip():
        model["base_url"] = os.environ[f"{PREFIX}MODEL_URL"].strip()
        sources.append(f"env: {PREFIX}MODEL_URL")
    if os.environ.get(f"{PREFIX}MODEL_NAME", "").strip():
        model["model"] = os.environ[f"{PREFIX}MODEL_NAME"].strip()
        sources.append(f"env: {PREFIX}MODEL_NAME")
    if os.environ.get(f"{PREFIX}WARMUP", "").strip():
        model["warmup"] = {**dict(model.get("warmup") or {}), "enabled": _switch(os.environ[f"{PREFIX}WARMUP"])}
        sources.append(f"env: {PREFIX}WARMUP")
    tree["model"] = model

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, path.parent, tuple(sources))


def _model_settings(model: Mapping[str, Any]) -> ModelSettings:
    try:
        protocol = str(model.get("protocol", "openai")).strip().lower()
        if protocol != "openai":
            raise ConfigError(f"model.protocol {protocol!r} is not supported; spark7 runs vLLM and speaks "
                              "the OpenAI-compatible routes only ('openai')")
        base_url = str(model["base_url"]).strip().rstrip("/")
        check_host(base_url)
        timeouts = dict(model.get("timeouts") or {})
        warmup = dict(model.get("warmup") or {})
        return ModelSettings(
            service=str(model.get("service") or "spark7"),
            protocol=protocol,
            base_url=base_url,
            model=str(model["model"]).strip(),
            stream=bool(model.get("stream", True)),
            connect_timeout_s=float(timeouts.get("connect_s", 10)),
            first_byte_timeout_s=float(timeouts.get("first_byte_s", 120)),
            total_timeout_s=float(timeouts.get("total_s", 300)),
            fixed_headers={str(k): str(v) for k, v in (model.get("headers") or {}).items()},
            secret_header_env={str(k): str(v) for k, v in (model.get("headers_from_env") or {}).items()},
            warmup_enabled=bool(warmup.get("enabled", True)),
            warmup_interval_s=max(30.0, float(warmup.get("interval_s", 240))),
            display_name=str(model.get("display_name") or "MiniMind").strip(),
        )
    except KeyError as exc:
        raise ConfigError(f"config.yaml model block is missing {exc.args[0]!r}") from exc
    except ModelConfigError as exc:
        raise ConfigError(str(exc)) from exc


def _build(tree: Mapping[str, Any], folder: Path, sources: tuple[str, ...]) -> Settings:
    try:
        service = tree["service"]
        upstream = tree["upstream"]
        model = tree["model"]
        db = tree["database"]
        active = tree["calibration"]["active"]
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing the {exc.args[0]!r} section") from exc

    known = {f.name for f in DatabaseConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    extra = set(db) - known
    if extra:
        raise ConfigError(f"unknown database keys: {sorted(extra)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=_identifier(database.dbname, "dbname"),
                       schema=_identifier(database.schema, "schema"),
                       port=int(database.port))

    model_settings = _model_settings(model)
    env_file = model.get("env_file")
    env: dict[str, str] = {}
    if env_file:
        env_path = (folder / str(env_file)).resolve()
        env.update(read_env_file(env_path))
        if env_path.is_file():
            sources = sources + (f"env file: {env_path}",)
    # The process environment wins over the file, for the named variables only.
    for var in model_settings.secret_header_env.values():
        if os.environ.get(var, "").strip():
            env[var] = os.environ[var].strip()
    env = {k: v for k, v in env.items() if k in set(model_settings.secret_header_env.values())}

    return Settings(
        host=str(service.get("host", "127.0.0.1")),
        port=int(service["port"]),
        cors_origins=tuple(service.get("cors_origins") or ("*",)),
        pcp_url=str(upstream["pcp_url"]).rstrip("/"),
        lbs_url=str(upstream["lbs_url"]).rstrip("/"),
        upstream_timeout_s=float(upstream.get("timeout_s", 60)),
        model=model_settings,
        active_calibration=str(active),
        database=database,
        env=env,
        sources=sources,
        lbsim_url=str(upstream.get("lbsim_url") or "http://127.0.0.1:8014").rstrip("/"),
    )
