"""Configuration loading.

Every threshold the model uses lives in config rather than in code, per section 7 of the build
brief. This module loads `config/defaults.yaml`, optionally overlays a per-economy YAML from
`macrofield/economies/`, and gives dotted-path access with a clear error when a key is missing.

Adding an economy is a config change, not a code change (brief section 1).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

#: Repository root, resolved from this file's location.
ROOT = Path(__file__).resolve().parent.parent

#: The defaults file, which every run loads.
DEFAULTS_PATH = ROOT / "config" / "defaults.yaml"

#: Directory holding the per-economy configuration files.
ECONOMIES_DIR = ROOT / "macrofield" / "economies"

#: Sentinel distinguishing "no default supplied" from "default is None".
_MISSING = object()


class ConfigError(KeyError):
    """Raised when a configuration key is missing or a config file is malformed."""


class Config:
    """A read-only view over a nested configuration mapping.

    Access is by dotted path, so `config.get("phases.foundation_saturation_ceiling")` reaches into
    the nested mapping. A missing key raises rather than returning None, because a threshold that
    silently defaults to nothing is how a magic constant creeps back into the code.
    """

    def __init__(self, data: dict[str, Any], sources: tuple[Path, ...] = ()) -> None:
        self._data = copy.deepcopy(data)
        self._sources = sources

    @property
    def sources(self) -> tuple[Path, ...]:
        """The files this configuration was assembled from, in overlay order.

        Recorded in the run manifest so a result can be traced to the configuration that produced it.
        """
        return self._sources

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Return the value at a dotted path.

        Args:
            path: A dotted path, for example "honi.coverage_floor.composite".
            default: Returned if the path is absent. If omitted, a missing path raises.

        Raises:
            ConfigError: If the path is absent and no default was supplied.
        """
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise ConfigError(
                        f"missing configuration key {path!r}. Configuration was loaded from "
                        f"{[str(s) for s in self._sources]}."
                    )
                return default
            node = node[part]
        return copy.deepcopy(node) if isinstance(node, (dict, list)) else node

    def section(self, path: str) -> "Config":
        """Return a sub-configuration rooted at a dotted path."""
        node = self.get(path)
        if not isinstance(node, dict):
            raise ConfigError(f"configuration key {path!r} is not a section, it is {type(node).__name__}")
        return Config(node, self._sources)

    def as_dict(self) -> dict[str, Any]:
        """Return a deep copy of the underlying mapping, for export into a manifest."""
        return copy.deepcopy(self._data)

    def __contains__(self, path: str) -> bool:
        return self.get(path, default=None) is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Config(top_level_keys={sorted(self._data)}, sources={len(self._sources)})"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping from disk."""
    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"configuration file {path} must contain a mapping, got {type(data).__name__}")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return base with overlay merged in, recursing into nested mappings.

    Lists are replaced rather than concatenated, so an economy that overrides a list of components
    states the whole list and there is no ambiguity about what is in effect.
    """
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load(economy: str | None = None, defaults_path: Path | None = None) -> Config:
    """Load the configuration, optionally overlaid with a per-economy file.

    Args:
        economy: An economy code, for example "us". Overlays
            `macrofield/economies/<economy>.yaml` onto the defaults.
        defaults_path: Override for the defaults file, used by tests.

    Returns:
        The assembled configuration.

    Raises:
        ConfigError: If a file is missing or malformed.
    """
    defaults_file = defaults_path or DEFAULTS_PATH
    data = _read_yaml(defaults_file)
    sources: tuple[Path, ...] = (defaults_file,)

    if economy is not None:
        economy_file = ECONOMIES_DIR / f"{economy}.yaml"
        overlay = _read_yaml(economy_file)
        data = _deep_merge(data, overlay)
        sources = sources + (economy_file,)

    return Config(data, sources)


def available_economies() -> list[str]:
    """Return the economy codes that have a configuration file, sorted."""
    if not ECONOMIES_DIR.exists():
        return []
    return sorted(p.stem for p in ECONOMIES_DIR.glob("*.yaml"))
