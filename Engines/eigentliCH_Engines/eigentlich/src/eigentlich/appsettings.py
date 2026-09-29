"""Settings of the consumer web app: the ``app:`` section of ``config.yaml`` on top of the store settings.

Precedence, lowest to highest, as for the store::

    config.yaml  <  config.local.yaml  <  EIGENTLICH_APP_* / EIGENTLICH_*_URL  <  overrides

The store's own settings (``settings.load``) are read unchanged; this module only adds what the app needs:
where it listens and where the three engines it calls are.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional

from .settings import PREFIX, ROOT, ConfigError, Settings, _deep_merge, _read_yaml, load


@dataclass(frozen=True)
class Timeouts:
    connect_s: float = 5.0
    lbs_s: float = 60.0
    chatbot_s: float = 330.0
    report_s: float = 330.0
    health_s: float = 1.5


@dataclass(frozen=True)
class Grounding:
    max_notes: int = 4
    max_chars_per_note: int = 5800
    min_score: int = 2
    #: When no note reaches min_score: the best fallback_notes at or above floor, rather than none (EIG-51).
    floor: int = 1
    fallback_notes: int = 2


@dataclass(frozen=True)
class LbsAuto:
    """The automatic balance-sheet runs (EIG-47): on after every change, debounced."""
    enabled: bool = True
    debounce_s: float = 5.0


@dataclass(frozen=True)
class AppSettings:
    store: Settings
    host: str = "127.0.0.1"
    port: int = 8017
    cors_origins: tuple[str, ...] = ()
    lbs_url: str = "http://127.0.0.1:8013"
    chatbot_url: str = "http://127.0.0.1:8016"
    report_url: str = "http://127.0.0.1:8015"
    timeouts: Timeouts = field(default_factory=Timeouts)
    grounding: Grounding = field(default_factory=Grounding)
    lbs_auto: LbsAuto = field(default_factory=LbsAuto)

    def describe(self) -> dict[str, Any]:
        """Safe to publish: no password."""
        return {"host": self.host, "port": self.port, "cors_origins": list(self.cors_origins),
                "engines": {"lbs": self.lbs_url, "chatbot": self.chatbot_url, "report": self.report_url},
                "timeouts": self.timeouts.__dict__, "grounding": self.grounding.__dict__,
                "lbs_auto": self.lbs_auto.__dict__,
                "store": self.store.database.describe()}


_ENV = {
    f"{PREFIX}APP_HOST": ("host", str),
    f"{PREFIX}APP_PORT": ("port", int),
    f"{PREFIX}LBS_URL": ("lbs_url", str),
    f"{PREFIX}CHATBOT_URL": ("chatbot_url", str),
    f"{PREFIX}REPORT_URL": ("report_url", str),
}


def load_app(path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None,
             store: Optional[Settings] = None) -> AppSettings:
    """The app settings. ``store`` replaces the store settings (the tests' throwaway schema)."""
    if path is None:
        path = Path(os.environ[f"{PREFIX}CONFIG"]) if os.environ.get(f"{PREFIX}CONFIG") else ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    tree = _read_yaml(path)
    local = path.with_name("config.local.yaml")
    if local.is_file():
        tree = _deep_merge(tree, _read_yaml(local))
    app = dict(tree.get("app") or {})
    for var, (key, cast) in _ENV.items():
        if var in os.environ:
            app[key] = cast(os.environ[var])
    if f"{PREFIX}APP_CORS_ORIGINS" in os.environ:
        app["cors_origins"] = [o.strip() for o in os.environ[f"{PREFIX}APP_CORS_ORIGINS"].split(",") if o.strip()]
    if overrides:
        app = _deep_merge(app, overrides)

    known = {"host", "port", "cors_origins", "lbs_url", "chatbot_url", "report_url", "timeouts", "grounding",
             "lbs_auto"}
    extra = set(app) - known
    if extra:
        raise ConfigError(f"unknown app keys: {sorted(extra)}")
    timeouts = dict(app.pop("timeouts", None) or {})
    grounding = dict(app.pop("grounding", None) or {})
    auto = dict(app.pop("lbs_auto", None) or {})
    try:
        t = replace(Timeouts(), **{k: float(v) for k, v in timeouts.items()})
        g = replace(Grounding(), **{k: int(v) for k, v in grounding.items()})
        a = replace(LbsAuto(), **{k: (bool(v) if k == "enabled" else float(v)) for k, v in auto.items()})
    except TypeError as exc:
        raise ConfigError(f"app.timeouts, app.grounding or app.lbs_auto: {exc}") from exc
    if a.debounce_s < 0:
        raise ConfigError("app.lbs_auto.debounce_s is not negative")
    for key in ("lbs_url", "chatbot_url", "report_url"):
        if key in app:
            app[key] = str(app[key]).rstrip("/")
    port = int(app.pop("port", 8017))
    if 8000 <= port <= 8016:
        raise ConfigError(f"port {port} belongs to an engine (8000-8016); the app listens on 8017")
    return AppSettings(store=store or load(path), port=port,
                       cors_origins=tuple(app.pop("cors_origins", None) or ()),
                       timeouts=t, grounding=g, lbs_auto=a, **app)
