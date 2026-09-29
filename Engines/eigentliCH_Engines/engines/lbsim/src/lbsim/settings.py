"""Settings: where ``config.yaml`` is read, and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  LBSIM_DATABASE_URL / DATABASE_URL  <  LBSIM_*  <  overrides

The upstream addresses take ``LBSIM_LBS_URL``, ``LBSIM_PCP_URL``, ``LBSIM_AGGREGATION_URL`` and ``LBSIM_FMRE_URL``.

``config.yaml`` is committed and describes how the engine runs: port, store, upstream engines, the figures a
request resolves to when it leaves them open, the worker harness. It never holds a password.
``config.local.yaml`` is git-ignored and is where a developer keeps the local container's password (as lbs
does); in deployment the password comes from ``LBSIM_DB_PASSWORD`` or a full ``LBSIM_DATABASE_URL``. ``LBSIM_CONFIG``
points at another configuration file (the worker tests use it).

The database name and schema are the only values ever interpolated into SQL as text, so both are validated as
plain identifiers here, once, at load time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

#: The engine folder: ``engines/lbsim``. ``config.yaml`` lives here, beside ``src``.
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
    schema: str = "lbsim"
    user: str = "lbsim"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout: int = 10
    maintenance_dbname: str = "postgres"

    def conninfo(self, *, dbname: Optional[str] = None) -> str:
        parts = {"host": self.host, "port": self.port, "dbname": dbname or self.dbname, "user": self.user,
                 "sslmode": self.sslmode, "connect_timeout": self.connect_timeout}
        if self.password:
            parts["password"] = self.password
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def redacted_url(self) -> str:
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}?schema={self.schema}"

    def describe(self) -> dict[str, Any]:
        """Safe to publish: never contains the password."""
        return {"backend": "postgresql", "host": self.host, "port": self.port, "dbname": self.dbname,
                "schema": self.schema, "user": self.user, "sslmode": self.sslmode,
                "password_set": bool(self.password), "url": self.redacted_url()}


@dataclass(frozen=True)
class SimulationConfig:
    n_paths: int = 2000
    default_seed: int = 20260929
    max_horizon_years: int = 60
    reference_age: float = 65.0
    steps_per_year: int = 12
    paths_budget_s: float = 20.0
    findings_budget_s: float = 5.0
    run_budget_s: float = 30.0


@dataclass(frozen=True)
class OptimiserConfig:
    workers: int = 3
    budget_minutes: float = 120.0
    max_solve_horizon_years: float = 20.0
    heartbeat_s: float = 30.0
    max_attempts: int = 2
    stale_after_s: float = 120.0
    redraw_seed_step: int = 1000
    out_of_sample_seed_offset: int = 500_000
    poll_s: float = 2.0

    @property
    def budget_s(self) -> float:
        return float(self.budget_minutes) * 60.0


@dataclass(frozen=True)
class UpstreamConfig:
    lbs_url: str = "http://127.0.0.1:8013"
    pcp_url: str = "http://127.0.0.1:8007"
    aggregation_url: str = "http://127.0.0.1:8004"
    fmre_url: str = "http://127.0.0.1:8006"
    accept_ipt: tuple[str, ...] = ("ipt@1.1.0",)
    connect_s: float = 5.0
    read_s: float = 30.0
    contracts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    active_calibration: str
    database: DatabaseConfig
    simulation: SimulationConfig
    optimiser: OptimiserConfig
    upstream: UpstreamConfig
    sources: tuple[str, ...] = field(default=())
    config_path: Optional[str] = None


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
                           "user": unquote(parsed.username or ""), "password": unquote(parsed.password or "")}
    if parsed.path.strip("/"):
        out["dbname"] = parsed.path.strip("/")
    for key in ("sslmode", "schema"):
        if key in query:
            out[key] = query[key]
    return out


_DB_ENV = {
    "LBSIM_DB_HOST": ("host", str), "LBSIM_DB_PORT": ("port", int), "LBSIM_DB_NAME": ("dbname", str),
    "LBSIM_DB_SCHEMA": ("schema", str), "LBSIM_DB_USER": ("user", str), "LBSIM_DB_PASSWORD": ("password", str),
    "LBSIM_DB_SSLMODE": ("sslmode", str),
}


#: The upstream engines whose address an environment variable ``LBSIM_<NAME>_URL`` may set.
UPSTREAM_NAMES: tuple[str, ...] = ("lbs", "pcp", "aggregation", "fmre")


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """Read the configuration. ``overrides`` is a partial config tree, applied last."""
    if path is None:
        path = Path(os.environ["LBSIM_CONFIG"]) if os.environ.get("LBSIM_CONFIG") else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    sources = [str(path)]
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if not local.is_file():
        local = ROOT / "config.local.yaml"
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
        sources.append(str(local))

    db = dict(tree.get("database") or {})
    url = os.environ.get("LBSIM_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        db.update(_from_url(url))
        sources.append("env: database url")
    for var, (key, cast) in _DB_ENV.items():
        if var in os.environ:
            db[key] = cast(os.environ[var])
            sources.append(f"env: {var}")
    tree["database"] = db

    service = dict(tree.get("service") or {})
    if "LBSIM_HOST" in os.environ:
        service["host"] = os.environ["LBSIM_HOST"]
    if "LBSIM_PORT" in os.environ:
        service["port"] = int(os.environ["LBSIM_PORT"])
    if "LBSIM_CORS_ORIGINS" in os.environ:
        service["cors_origins"] = [o.strip() for o in os.environ["LBSIM_CORS_ORIGINS"].split(",") if o.strip()]
    tree["service"] = service

    # The upstream engines' addresses (deploy/ENGINE_CHANGES.md item 1): LBSIM_LBS_URL, LBSIM_PCP_URL,
    # LBSIM_AGGREGATION_URL, LBSIM_FMRE_URL, after the config.local.yaml merge, as report does for REPORT_*_URL.
    upstream = dict(tree.get("upstream") or {})
    for name in UPSTREAM_NAMES:
        var = f"LBSIM_{name.upper()}_URL"
        value = os.environ.get(var, "").strip()
        if value:
            upstream[name] = {**dict(upstream.get(name) or {}), "url": value}
            sources.append(f"env: {var}")
    tree["upstream"] = upstream

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, tuple(sources), str(path))


def _pick(cls, block: Mapping[str, Any]) -> Any:
    known = set(cls.__dataclass_fields__)
    return cls(**{k: v for k, v in (block or {}).items() if k in known})


def _build(tree: Mapping[str, Any], sources: tuple[str, ...], config_path: Optional[str] = None) -> Settings:
    try:
        service = tree["service"]
        db = tree["database"]
        active = tree["calibration"]["active"]
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing the {exc.args[0]!r} section") from exc
    known = set(DatabaseConfig.__dataclass_fields__)
    extra = set(db) - known
    if extra:
        raise ConfigError(f"unknown database keys: {sorted(extra)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=_identifier(database.dbname, "dbname"),
                       schema=_identifier(database.schema, "schema"), port=int(database.port))
    sim = _pick(SimulationConfig, tree.get("simulation") or {})
    opt = _pick(OptimiserConfig, tree.get("optimiser") or {})
    up = tree.get("upstream") or {}
    timeouts = up.get("timeouts") or {}
    upstream = UpstreamConfig(
        lbs_url=str((up.get("lbs") or {}).get("url", UpstreamConfig.lbs_url)),
        pcp_url=str((up.get("pcp") or {}).get("url", UpstreamConfig.pcp_url)),
        aggregation_url=str((up.get("aggregation") or {}).get("url", UpstreamConfig.aggregation_url)),
        fmre_url=str((up.get("fmre") or {}).get("url", UpstreamConfig.fmre_url)),
        accept_ipt=tuple((up.get("fmre") or {}).get("accept_ipt") or UpstreamConfig.accept_ipt),
        connect_s=float(timeouts.get("connect_s", 5.0)), read_s=float(timeouts.get("read_s", 30.0)),
        contracts={f"{name}:{k}": v for name in ("lbs", "pcp", "aggregation", "fmre")
                   for k, v in ((up.get(name) or {}).get("contracts") or {}).items()})
    if sim.n_paths < 200 or sim.n_paths > 20_000:
        raise ConfigError("simulation.n_paths must lie in 200..20000 (the request contract's range)")
    return Settings(host=str(service.get("host", "127.0.0.1")), port=int(service["port"]),
                    cors_origins=tuple(service.get("cors_origins") or ("*",)), active_calibration=str(active),
                    database=database, simulation=sim, optimiser=opt, upstream=upstream, sources=sources,
                    config_path=config_path)
