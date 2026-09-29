"""Configuration and the fixed vocabularies.

Everything the legacy Master Controller held in spreadsheet control cells is loaded from
`config/defaults.yaml`. No threshold, preset, tolerance, or vocabulary is a constant in code.

The vocabularies are ordered, and the order is load-bearing: the constraint rows of section 4.2 are
indexed by position within each vocabulary, so reordering one silently changes what a mandate bound
means. `Vocabularies` therefore exposes an index lookup rather than letting callers use `list.index`
on a raw list, and refuses an unknown label instead of bucketing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "defaults.yaml"


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or internally inconsistent."""


class VocabularyError(ValueError):
    """Raised when a label is not in the vocabulary it is being classified against."""


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """One ordered classification dimension.

    `name` is the dimension (for example "currency"); `labels` is the ordered set of categories. The
    position of a label is its constraint-row index, so it must never be derived from anything but
    this object.
    """

    name: str
    labels: tuple[str, ...]
    #: Where an unrecognised label folds to, when the dimension has such a slot. `None` means an
    #: unrecognised label is an error.
    catch_all: str | None = None

    def __post_init__(self) -> None:
        if not self.labels:
            raise ConfigError(f"vocabulary {self.name!r} is empty")
        if len(set(self.labels)) != len(self.labels):
            duplicates = sorted({label for label in self.labels if self.labels.count(label) > 1})
            raise ConfigError(f"vocabulary {self.name!r} has duplicate labels: {duplicates}")
        if self.catch_all is not None and self.catch_all not in self.labels:
            raise ConfigError(
                f"vocabulary {self.name!r} names catch_all={self.catch_all!r}, which is not one of "
                f"its labels {list(self.labels)}"
            )

    def __len__(self) -> int:
        return len(self.labels)

    def index(self, label: str) -> int:
        """Row index of `label`.

        Raises VocabularyError when the label is unknown and the dimension has no catch-all, rather
        than bucketing it. Silently folding an unrecognised currency into Others would move weight
        against a bound the mandate never set.
        """
        try:
            return self.labels.index(label)
        except ValueError:
            pass
        if self.catch_all is not None:
            return self.labels.index(self.catch_all)
        raise VocabularyError(
            f"{label!r} is not a known {self.name}. Known: {list(self.labels)}. "
            f"This dimension has no catch-all, so the label must be corrected upstream."
        )

    def contains(self, label: str) -> bool:
        return label in self.labels


@dataclass(frozen=True, slots=True)
class Vocabularies:
    """The full set of ordered dimensions the optimiser classifies against."""

    scenarios: Vocabulary
    roles: Vocabulary
    phases: Vocabulary
    capital_types: Vocabulary
    asset_classes: Vocabulary
    liquidity: Vocabulary
    regions: Vocabulary
    currencies: Vocabulary
    signal_scopes: Vocabulary

    #: Dimension name to Vocabulary, for the constraint assembler which walks `block_order`.
    def by_name(self, name: str) -> Vocabulary:
        mapping = {
            "scenario": self.scenarios,
            "role": self.roles,
            "phase": self.phases,
            "capital_type": self.capital_types,
            "asset_class": self.asset_classes,
            "liquidity": self.liquidity,
            "region": self.regions,
            "currency": self.currencies,
            "signal_scope": self.signal_scopes,
        }
        if name not in mapping:
            raise ConfigError(f"no vocabulary named {name!r}. Known: {sorted(mapping)}")
        return mapping[name]

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "Vocabularies":
        def vocab(key: str, name: str, catch_all: str | None = None) -> Vocabulary:
            if key not in raw:
                raise ConfigError(f"config vocabularies is missing {key!r}")
            labels = raw[key]
            if not isinstance(labels, Sequence) or isinstance(labels, str):
                raise ConfigError(f"config vocabularies.{key} must be a list, got {type(labels).__name__}")
            return Vocabulary(name=name, labels=tuple(str(v) for v in labels), catch_all=catch_all)

        return cls(
            scenarios=vocab("scenarios", "scenario"),
            roles=vocab("roles", "role"),
            phases=vocab("phases", "phase"),
            # `Others` absorbs a capital type outside Financial and Real (decisions.md D8).
            capital_types=vocab("capital_types", "capital type", catch_all="Others"),
            asset_classes=vocab("asset_classes", "asset class"),
            liquidity=vocab("liquidity", "liquidity class"),
            # `Others` absorbs a region outside the six named ones.
            regions=vocab("regions", "region", catch_all="Others"),
            # `Others` absorbs a currency outside the nine named ones, reproducing the legacy
            # else-branch of curveoptimization.m.
            currencies=vocab("currencies", "currency", catch_all="Others"),
            signal_scopes=vocab("signal_scopes", "signal scope"),
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class Config:
    """A loaded configuration, addressed by dotted path.

    `get` raises on a missing key rather than returning a default, so a typo in a config path fails
    the run instead of silently substituting a value nobody chose.
    """

    def __init__(self, raw: Mapping[str, Any], source: Path | None = None) -> None:
        self._raw: dict[str, Any] = dict(raw)
        self.source = source
        self.vocabularies = Vocabularies.from_raw(self._raw.get("vocabularies", {}))
        self._validate()

    # -- access ------------------------------------------------------------

    def get(self, path: str) -> Any:
        node: Any = self._raw
        walked: list[str] = []
        for part in path.split("."):
            walked.append(part)
            if not isinstance(node, Mapping) or part not in node:
                raise ConfigError(
                    f"config path {path!r} not found (stopped at {'.'.join(walked)!r})"
                    + (f" in {self.source}" if self.source else "")
                )
            node = node[part]
        return node

    def get_or(self, path: str, default: Any) -> Any:
        """Only for genuinely optional settings, such as an unset override."""
        try:
            return self.get(path)
        except ConfigError:
            return default

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def disclaimer(self) -> str:
        return " ".join(str(self.get("programme.disclaimer")).split())

    @property
    def engine_version(self) -> str:
        return str(self.get("programme.engine_version"))

    @property
    def state_grid(self) -> int:
        return int(self.get("state_grid"))

    # -- ingest label mapping ---------------------------------------------

    def map_label(self, dimension: str, label: str) -> str:
        """Apply the configured ingest rename for one dimension.

        Upstream spelling (`Growth`, `Stabilization`, `Maturing`, `Real Estate`) is normalised here so
        it never reaches the optimiser. A label with no mapping passes through unchanged.
        """
        table = self.get_or(f"ingest_maps.{dimension}", {}) or {}
        return str(table.get(label, label))

    # -- validation --------------------------------------------------------

    def _validate(self) -> None:
        grid = self.state_grid
        if grid != 25:
            raise ConfigError(f"state_grid must be 25, got {grid}")

        scenarios = self.vocabularies.scenarios
        if len(scenarios) != 5:
            raise ConfigError(f"there must be exactly 5 scenarios, got {len(scenarios)}")
        if grid % len(scenarios) != 0:
            raise ConfigError(
                f"the {grid}-state grid does not divide evenly into {len(scenarios)} scenarios"
            )

        order = list(self.get("constraints.block_order"))
        expected = {"currency", "region", "role", "capital_type", "liquidity", "esg", "phase", "asset_class"}
        if set(order) != expected:
            raise ConfigError(
                f"constraints.block_order must be exactly {sorted(expected)}, got {sorted(set(order))}"
            )
        if len(order) != len(set(order)):
            raise ConfigError("constraints.block_order has a repeated block")

        self._validate_country_weights()
        self._validate_solver()

    def _validate_country_weights(self) -> None:
        slots = list(self.get("country_weights.order"))
        if len(slots) != 7:
            raise ConfigError(f"country_weights.order must name 7 slots, got {len(slots)}")

        mapping = dict(self.get("country_weights.economies_for_slot"))
        missing = [s for s in slots if s not in mapping]
        if missing:
            raise ConfigError(f"country_weights.economies_for_slot is missing slots: {missing}")
        for slot in slots:
            members = mapping[slot]
            if not isinstance(members, Mapping) or not members:
                raise ConfigError(
                    f"country_weights.economies_for_slot[{slot!r}] must be a non-empty mapping of "
                    f"economy code to weight, got {members!r}"
                )
            total = float(sum(float(w) for w in members.values()))
            if abs(total - 1.0) > 1e-9:
                raise ConfigError(
                    f"country_weights.economies_for_slot[{slot!r}] sums to {total}, not 1. A slot whose "
                    f"members do not sum to one would silently rescale that slot's contribution."
                )
            if any(float(w) < 0.0 for w in members.values()):
                raise ConfigError(
                    f"country_weights.economies_for_slot[{slot!r}] has a negative member weight"
                )

        presets = dict(self.get("country_weights.presets"))
        if not presets:
            raise ConfigError("country_weights.presets is empty")
        for name, vector in presets.items():
            if len(vector) != 7:
                raise ConfigError(
                    f"country weight preset {name!r} has {len(vector)} entries, expected 7"
                )
            total = float(sum(vector))
            if abs(total - 1.0) > 1e-9:
                raise ConfigError(
                    f"country weight preset {name!r} sums to {total}, not 1. A blend over weights "
                    f"that do not sum to one would rescale the Regime distribution."
                )
            if any(float(w) < 0.0 for w in vector):
                raise ConfigError(f"country weight preset {name!r} has a negative weight")

        overwrite = self.get_or("country_weights.overwrite", None)
        if overwrite is not None:
            if len(overwrite) != 7:
                raise ConfigError(
                    f"country_weights.overwrite has {len(overwrite)} entries, expected 7"
                )
            total = float(sum(overwrite))
            if abs(total - 1.0) > 1e-9:
                raise ConfigError(f"country_weights.overwrite sums to {total}, not 1")

    def _validate_solver(self) -> None:
        speeds = dict(self.get("solver.speeds"))
        for required in ("fast", "exact"):
            if required not in speeds:
                raise ConfigError(f"solver.speeds is missing {required!r}")
            for key in ("ftol", "maxiter"):
                if key not in speeds[required]:
                    raise ConfigError(f"solver.speeds.{required} is missing {key!r}")

    # -- construction ------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> "Config":
        """Load YAML config, optionally applying dotted-path overrides.

        Overrides are how the CLI and the cockpit drive a run without editing the file. An override
        naming a path that does not already exist is an error, so a mistyped flag cannot introduce a
        setting nothing reads.
        """
        config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise ConfigError(f"config file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, Mapping):
            raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

        merged = dict(raw)
        for dotted, value in (overrides or {}).items():
            _apply_override(merged, dotted, value, config_path)
        return cls(merged, source=config_path)


def _apply_override(raw: dict[str, Any], dotted: str, value: Any, source: Path) -> None:
    parts = dotted.split(".")
    node: Any = raw
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(
                f"override {dotted!r} does not name an existing config path in {source}"
            )
        node = node[part]
    leaf = parts[-1]
    if not isinstance(node, dict) or leaf not in node:
        raise ConfigError(f"override {dotted!r} does not name an existing config path in {source}")
    node[leaf] = value


def load_config(
    path: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Config:
    """Module-level convenience wrapper around `Config.load`."""
    return Config.load(path=path, overrides=overrides)
