"""Configuration: ``config.yaml`` < ``config.local.yaml`` < ``COCKPIT_*`` environment.

Paths in the file are relative to the cockpit folder, so the configuration reads the same on
every machine that keeps the repository layout (``Projects/Engines/{cockpit,Macro,Instruments}``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

#: The cockpit folder (holds config.yaml). ``src/cockpit/settings.py`` -> three levels up.
ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"

MODES = ("development", "cio")
STATUSES = ("built", "parked", "scaffold", "planned")
#: ``engine``: a roster engine, number NN on port 80NN. ``app``: an application the cockpit
#: starts and links to (the eigentliCH consumer app), with no engine number (C-18).
KINDS = ("engine", "app")
#: First path segments under /api that belong to the cockpit itself, never to an engine.
#: ``cio``: the CIO's writes to an engine that the proxy cannot allow by an exact path (C-32).
RESERVED = frozenset({"graph", "config", "decisions", "export", "launcher", "curator", "cio"})


@dataclass(frozen=True)
class CuratorDb:
    """The curator's connection to schema ``eigentlich`` (C-16). No password in config.yaml:
    it comes from ``config.local.yaml`` or ``COCKPIT_CURATOR_DB_PASSWORD``."""

    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "simtech"
    schema: str = "eigentlich"
    user: str = "curator"
    password: Optional[str] = None
    connect_timeout: int = 5

    @property
    def configured(self) -> bool:
        return bool(self.password)

    def public(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "dbname": self.dbname, "schema": self.schema,
                "user": self.user, "configured": self.configured}


@dataclass(frozen=True)
class Engine:
    key: str
    number: Optional[int]
    name: str
    family: str
    url: str
    status: str
    produces: str = ""
    consumes: tuple[str, ...] = ()
    api: str = "standard"
    bench: Optional[Path] = None
    start_cwd: Optional[Path] = None
    start_args: tuple[str, ...] = ()
    autostart: bool = False
    notion: str = ""
    kind: str = "engine"
    #: Interpreter for this engine when it lives in another virtual environment (C-17).
    python: Optional[Path] = None
    #: The address a browser reaches the engine at, when it is not ``url`` (behind a tunnel or a
    #: proxy, C-40). ``url`` stays the cockpit's own address for the engine.
    public_url: Optional[str] = None

    @property
    def health_path(self) -> str:
        return "/v1/health" if self.api == "v1" else "/health"

    @property
    def meta_path(self) -> Optional[str]:
        # The Fund Map engine predates the standard endpoints; its /v1/health carries the
        # version and the store, and it has no /meta.
        return None if self.api == "v1" else "/meta"

    @property
    def docs_url(self) -> str:
        return self.url.rstrip("/") + "/docs"

    def public(self, launcher: bool = True) -> dict[str, Any]:
        """What the front end reads. ``startable`` is false for every engine when the launcher is
        off (C-39). ``public_url`` and ``public_docs`` are None unless a browser-facing address is
        set (C-40); the page then links ``url`` only when it is itself opened on this machine."""
        return {"key": self.key, "number": self.number, "name": self.name, "family": self.family,
                "url": self.url, "status": self.status, "produces": self.produces,
                "consumes": list(self.consumes), "api": self.api,
                "bench": self.bench is not None and self.bench.is_file(),
                "startable": launcher and self.start_cwd is not None, "autostart": self.autostart,
                "notion": self.notion, "docs": self.docs_url, "kind": self.kind,
                "public_url": self.public_url,
                "public_docs": None if self.public_url is None else self.public_url + "/docs"}


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    mode: str = "development"
    #: May the cockpit start engines (C-39)? Off where something else starts them (supervisord in
    #: the Docker image): the start route answers 409, autostart and ``start-engines`` do nothing.
    launcher: bool = True
    timeout_s: float = 60.0
    data_dir: Path = ROOT / "data"
    cio_snapshot: str = ""
    cio_writable: tuple[str, ...] = ()
    python: Optional[Path] = None
    engines: tuple[Engine, ...] = ()
    curator_db: CuratorDb = field(default_factory=CuratorDb)
    sources: tuple[str, ...] = field(default_factory=tuple)

    def engine(self, key: str) -> Optional[Engine]:
        return next((e for e in self.engines if e.key == key), None)

    def writable(self, key: str, path: str) -> bool:
        """May the proxy forward a non-GET request to this engine and path?"""
        if self.mode == "development":
            return True
        return f"{key}:/{path.lstrip('/')}" in self.cio_writable


def _rel(value: Optional[str]) -> Optional[Path]:
    return None if not value else (ROOT / value).resolve()


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _switch(value: Any, name: str) -> bool:
    """on / off (YAML reads a bare ``off`` as false), also true / false, yes / no, 1 / 0."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("on", "true", "yes", "1"):
        return True
    if text in ("off", "false", "no", "0"):
        return False
    raise ValueError(f"{name} must be on or off, not {value!r}")


def _env_key(key: str) -> str:
    """An engine key as it appears in an environment variable name: ``lbsim`` -> ``LBSIM``."""
    return "".join(c if c.isalnum() else "_" for c in key).upper()


def _public_url(row: dict[str, Any], env: dict[str, str]) -> Optional[str]:
    value = env.get(f"COCKPIT_ENGINE_{_env_key(row['key'])}_PUBLIC_URL") or row.get("public_url") or ""
    value = str(value).strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"{row['key']}: public_url must start with http:// or https://, not {value!r}")
    return value


def _engines(rows: list[dict[str, Any]], env: Optional[dict[str, str]] = None) -> tuple[Engine, ...]:
    env = env or {}
    engines, seen = [], set()
    for row in rows:
        key = row["key"]
        if key in RESERVED:
            raise ValueError(f"engine key {key!r} collides with a cockpit endpoint")
        if key in seen:
            raise ValueError(f"engine key {key!r} is listed twice")
        if row.get("status") not in STATUSES:
            raise ValueError(f"{key}: status must be one of {STATUSES}")
        kind = row.get("kind", "engine")
        if kind not in KINDS:
            raise ValueError(f"{key}: kind must be one of {KINDS}")
        if kind == "engine" and row.get("number") is None:
            raise ValueError(f"{key}: an engine needs its number")
        seen.add(key)
        start = row.get("start") or {}
        engines.append(Engine(
            key=key, number=None if row.get("number") is None else int(row["number"]), name=row["name"],
            family=row.get("family", ""),
            url=row["url"].rstrip("/"), status=row["status"], produces=row.get("produces", ""),
            consumes=tuple(row.get("consumes") or ()), api=row.get("api", "standard"),
            bench=_rel(row.get("bench")), start_cwd=_rel(start.get("cwd")),
            start_args=tuple(start.get("args") or ()), autostart=bool(row.get("autostart")),
            notion=row.get("notion", ""), kind=kind, python=_rel(row.get("python")),
            public_url=_public_url(row, env)))
    return tuple(engines)


def _curator_db(raw: dict[str, Any], env: dict[str, str]) -> CuratorDb:
    """config.yaml < config.local.yaml < ``COCKPIT_CURATOR_DB_HOST``, ``_PORT``, ``_NAME``, ``_USER``
    and ``_PASSWORD`` (C-38). The schema stays in the file: the curator's grants are on it."""
    d = CuratorDb()
    return CuratorDb(host=str(env.get("COCKPIT_CURATOR_DB_HOST") or raw.get("host", d.host)),
                     port=int(env.get("COCKPIT_CURATOR_DB_PORT") or raw.get("port", d.port)),
                     dbname=str(env.get("COCKPIT_CURATOR_DB_NAME") or raw.get("dbname", d.dbname)),
                     schema=str(raw.get("schema", d.schema)),
                     user=str(env.get("COCKPIT_CURATOR_DB_USER") or raw.get("user", d.user)),
                     password=env.get("COCKPIT_CURATOR_DB_PASSWORD") or raw.get("password") or None,
                     connect_timeout=int(raw.get("connect_timeout", d.connect_timeout)))


def load(path: Optional[Path] = None, env: Optional[dict[str, str]] = None) -> Settings:
    env = dict(os.environ if env is None else env)
    path = path or ROOT / "config.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = [str(path)]
    local = path.with_name("config.local.yaml")
    if local.is_file():
        raw = _merge(raw, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
        sources.append(str(local))

    service = raw.get("service") or {}
    cio = raw.get("cio") or {}
    mode = env.get("COCKPIT_MODE", service.get("mode", "development"))
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    data_dir = env.get("COCKPIT_DATA_DIR") or raw.get("data_dir") or "data"
    if any(k.startswith("COCKPIT_") for k in env):
        sources.append("environment")
    return Settings(
        host=env.get("COCKPIT_HOST", service.get("host", "127.0.0.1")),
        port=int(env.get("COCKPIT_PORT", service.get("port", 8000))),
        mode=mode,
        launcher=_switch(env.get("COCKPIT_LAUNCHER", service.get("launcher", True)), "COCKPIT_LAUNCHER"),
        timeout_s=float(service.get("timeout_s", 60)),
        data_dir=Path(data_dir) if Path(data_dir).is_absolute() else (ROOT / data_dir).resolve(),
        cio_snapshot=cio.get("snapshot", ""),
        cio_writable=tuple(cio.get("writable") or ()),
        python=_rel(raw.get("python")),
        engines=_engines(raw.get("engines") or [], env),
        curator_db=_curator_db(raw.get("curator_db") or {}, env),
        sources=tuple(sources),
    )
