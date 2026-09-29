"""Settings: ``config.yaml`` and what may override it.

Precedence, lowest to highest::

    config.yaml  <  config.local.yaml  <  DATAFEED_DATABASE_URL / DATABASE_URL  <  DATAFEED_*  <  overrides

Same rules as every engine: the committed file holds the shape of the setup and never a
secret; the password comes from ``config.local.yaml`` (git-ignored) or the environment.
Engines share no code, so this module is datafeed's own.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, unquote, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


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
    schema: str = "datafeed"
    user: str = "datafeed"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout: int = 10
    maintenance_dbname: str = "postgres"

    def conninfo(self, *, dbname: Optional[str] = None) -> str:
        parts = {"host": self.host, "port": self.port, "dbname": dbname or self.dbname,
                 "user": self.user, "sslmode": self.sslmode, "connect_timeout": self.connect_timeout}
        if self.password:
            parts["password"] = self.password
        return " ".join(f"{k}={_quote_libpq(v)}" for k, v in parts.items())

    def redacted_url(self) -> str:
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}?schema={self.schema}"

    def describe(self) -> dict[str, Any]:
        return {"backend": "postgresql", "host": self.host, "port": self.port, "dbname": self.dbname,
                "schema": self.schema, "user": self.user, "sslmode": self.sslmode,
                "password_set": bool(self.password), "url": self.redacted_url()}


@dataclass(frozen=True)
class FillSpec:
    country: str
    series: str
    provider: str
    code: str
    mode: str
    anchor: Optional[str] = None
    anchor_code: Optional[str] = None
    fx: bool = False
    unit_scale: float = 1.0
    tolerance: Optional[float] = None
    #: share mode only: remove the series' primary cells first (a known-bad primary series).
    replace: bool = False
    note: str = ""

    @property
    def source(self) -> str:
        return f"{self.provider}:{self.code}"


@dataclass(frozen=True)
class MarketCorrection:
    """DF-18: primary cells whose sheet scale factor is wrong, multiplied by ``factor``."""

    series: str
    countries: tuple[str, ...]
    factor: float
    reason: str


@dataclass(frozen=True)
class MarketSource:
    """DF-18: a monthly public series. ``code`` may hold ``{area}``, replaced per country by
    ``areas`` (the provider's code for that economy; default: the country code). With
    ``fill`` it goes only into missing primary cells, and only if the monthly fit holds;
    without, it is the primary source of a series Bloomberg does not carry for us."""

    series: str
    provider: str
    code: str
    countries: tuple[str, ...]
    unit_scale: float = 1.0
    fill: bool = False
    #: fill only: the public series is the same index as the primary ticker (from its
    #: publisher). The fit then only has to confirm the unit: median ratio within
    #: ``identical_tolerance`` of 1 over at least ``identical_min_overlap`` months. Single
    #: months may differ where the two sources close the month on different days.
    identical: bool = False
    areas: Mapping[str, str] = field(default_factory=dict)
    tolerance: Optional[float] = None
    note: str = ""

    def code_for(self, country: str) -> str:
        return self.code.replace("{area}", self.areas.get(country, country))


@dataclass(frozen=True)
class Market:
    corrections: tuple[MarketCorrection, ...] = ()
    sources: tuple[MarketSource, ...] = ()
    #: A fill is accepted if every overlap month's ratio is within this of the median ratio.
    fill_tolerance: float = 0.10
    min_overlap_months: int = 12
    identical_tolerance: float = 0.02
    identical_min_overlap: int = 6


@dataclass(frozen=True)
class MatlabImport:
    dir: Path
    file: str
    tickers: str
    snapshot_id: str
    as_of: str
    first_month: str
    months: int
    placeholder_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    cors_origins: tuple[str, ...]
    admin_token_env: str
    active_calibration: str
    primary_source: str
    fills: tuple[FillSpec, ...]
    matlab: MatlabImport
    database: DatabaseConfig
    sources: tuple[str, ...] = field(default=())
    market: Market = field(default_factory=Market)


    @property
    def admin_token(self) -> Optional[str]:
        return os.environ.get(self.admin_token_env) or None


def _deep_merge(base: dict[str, Any], top: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in top.items():
        out[k] = _deep_merge(dict(out[k]), v) if isinstance(v, Mapping) and isinstance(out.get(k), Mapping) else v
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
    "DATAFEED_DB_HOST": ("host", str), "DATAFEED_DB_PORT": ("port", int),
    "DATAFEED_DB_NAME": ("dbname", str), "DATAFEED_DB_SCHEMA": ("schema", str),
    "DATAFEED_DB_USER": ("user", str), "DATAFEED_DB_PASSWORD": ("password", str),
    "DATAFEED_DB_SSLMODE": ("sslmode", str),
}


def load(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    if path is None:
        path = Path(os.environ["DATAFEED_CONFIG"]) if os.environ.get("DATAFEED_CONFIG") else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    sources = [str(path)]
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
        sources.append(str(local))

    db = dict(tree.get("database") or {})
    url = os.environ.get("DATAFEED_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        db.update(_from_url(url))
        sources.append("env: database url")
    for var, (key, cast) in _DB_ENV.items():
        if var in os.environ:
            db[key] = cast(os.environ[var])
            sources.append(f"env: {var}")
    tree["database"] = db

    service = dict(tree.get("service") or {})
    for var, key, cast in (("DATAFEED_HOST", "host", str), ("DATAFEED_PORT", "port", int)):
        if var in os.environ:
            service[key] = cast(os.environ[var])
    if "DATAFEED_CORS_ORIGINS" in os.environ:
        service["cors_origins"] = [o.strip() for o in os.environ["DATAFEED_CORS_ORIGINS"].split(",") if o.strip()]
    tree["service"] = service

    if overrides:
        tree = _deep_merge(tree, overrides)
        sources.append("explicit override")
    return _build(tree, tuple(sources))


def _build(tree: Mapping[str, Any], sources: tuple[str, ...]) -> Settings:
    try:
        service, db, m = tree["service"], tree["database"], tree["import"]["matlab"]
        fills = tuple(FillSpec(**f) for f in tree.get("fills") or ())
        market = _market(tree.get("market") or {})
        active = str(tree["calibration"]["active"])
        primary = str(tree["primary_source"])
    except KeyError as exc:
        raise ConfigError(f"config.yaml is missing {exc.args[0]!r}") from exc
    except TypeError as exc:
        raise ConfigError(f"config.yaml has an unknown key: {exc}") from exc

    for f in fills:
        if f.mode not in ("level", "rate", "share"):
            raise ConfigError(f"fill {f.country}/{f.series}: mode must be level, rate or share")
        if f.mode == "share" and not f.anchor:
            raise ConfigError(f"fill {f.country}/{f.series}: a share needs an anchor series")
        if f.replace and f.mode != "share":
            raise ConfigError(f"fill {f.country}/{f.series}: only a share may replace primary cells")
        if f.anchor and f.mode == "level" and not f.anchor_code:
            raise ConfigError(f"fill {f.country}/{f.series}: a level anchor needs anchor_code")

    known = set(DatabaseConfig.__dataclass_fields__)  # type: ignore[attr-defined]
    if set(db) - known:
        raise ConfigError(f"unknown database keys: {sorted(set(db) - known)}")
    database = replace(DatabaseConfig(), **db)
    database = replace(database, dbname=_identifier(database.dbname, "dbname"),
                       schema=_identifier(database.schema, "schema"), port=int(database.port))

    return Settings(
        host=str(service.get("host", "127.0.0.1")), port=int(service["port"]),
        cors_origins=tuple(service.get("cors_origins") or ("*",)),
        admin_token_env=str(service.get("admin_token_env", "DATAFEED_ADMIN_TOKEN")),
        active_calibration=active, primary_source=primary, fills=fills,
        matlab=MatlabImport(dir=Path(os.environ.get("DATAFEED_MATLAB_DIR", m["dir"])), file=m["file"],
                            tickers=m["tickers"], snapshot_id=m["snapshot_id"], as_of=str(m["as_of"]),
                            first_month=str(m["first_month"]), months=int(m["months"]),
                            placeholder_tickers=tuple(str(t).strip() for t in m.get("placeholder_tickers") or ())),
        database=database, sources=sources, market=market,
    )


def _market(tree: Mapping[str, Any]) -> Market:
    corrections = tuple(
        MarketCorrection(series=c["series"], countries=tuple(c["countries"]), factor=float(c["factor"]),
                         reason=str(c["reason"]))
        for c in tree.get("corrections") or ())
    sources = tuple(
        MarketSource(series=m["series"], provider=m["provider"], code=str(m["code"]),
                     countries=tuple(m["countries"]), unit_scale=float(m.get("unit_scale", 1.0)),
                     fill=bool(m.get("fill", False)), identical=bool(m.get("identical", False)),
                     areas=dict(m.get("areas") or {}),
                     tolerance=m.get("tolerance"), note=str(m.get("note", "")))
        for m in tree.get("sources") or ())
    for c in corrections:
        if c.factor <= 0 or not c.reason:
            raise ConfigError(f"market correction {c.series}: a positive factor and a reason are required")
    for m in sources:
        if m.provider not in ("cboe", "bis"):
            raise ConfigError(f"market source {m.series}: provider must be cboe or bis")
    return Market(corrections=corrections, sources=sources,
                  fill_tolerance=float(tree.get("fill_tolerance", 0.10)),
                  min_overlap_months=int(tree.get("min_overlap_months", 12)),
                  identical_tolerance=float(tree.get("identical_tolerance", 0.02)),
                  identical_min_overlap=int(tree.get("identical_min_overlap", 6)))
