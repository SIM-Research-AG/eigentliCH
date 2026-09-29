"""Regime and ReturnSet: referenced, not redefined.

**Why there is no Regime or ReturnSet class here.** Both already exist as typed, versioned, schema-emitting
contracts in the engines that produce them:

- Regime: `Projects/Macro_Model/macrofield/contracts/regime_timeline.py`, contract `rtl@0.1.0`
- ReturnSet: `Projects/Fund_Map/src/fmre/contracts/returnset.py`, contract `re@0.2.0`

Defining them again here would create two definitions of one promise, and the copy in the master model would
drift from the producer's the first time either changed. So this module holds **references** and a
**resolver**, and the producers keep ownership of the shapes.

That also matches the manual's "contracts passed by reference": a per-user contract carries a `regime_id`,
not an embedded Regime. The reference is what travels; the payload is fetched when needed.

**ReturnSets are keyed on (market scope, horizon).** Decided 2026-07-28, see
architecture/DESIGN_snapshot_to_mandate.md section 5.2. A ten-year per-state return is not a one-year return
compounded, because the regime does not persist for ten years, so each horizon is separately estimated.
Regime timelines are keyed on scope alone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

STATE_GRID: int = 25

#: Where the producers publish. Overridable by environment variable so a run can point at a fixture set.
#: The producers live under `engines/`, relocated there on 2026-07-28 so each project sits beside the adapter
#: that wraps it.
_ENGINES = Path(__file__).resolve().parents[1] / "engines"

DEFAULT_REGIME_DIR = Path(
    os.environ.get(
        "ANDERSCH_REGIME_DIR",
        _ENGINES / "Macro_Model" / "output" / "regime",
    )
)
DEFAULT_RETURNSET_DIR = Path(
    os.environ.get(
        "ANDERSCH_RETURNSET_DIR",
        _ENGINES / "Fund_Map" / "artifacts",
    )
)


class ContractUnavailable(RuntimeError):
    """Raised when a referenced contract has not been published.

    Carries the command that would publish it. The ground rules say a missing input fails loudly; a failure
    that also says how to fix itself is the difference between loud and useful.
    """


class RegimeMismatch(ValueError):
    """Raised when two contracts disagree about which Regime they were computed under.

    The manual's invariant: the Optimiser rejects a ReturnSet whose `regime_id` does not match the
    snapshot's. No mixing of regime vintages.
    """


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


class RegimeRef(BaseModel):
    """A reference to a published Regime timeline.

    This is what a per-user contract carries. `regime_id` is the load-bearing field: every downstream
    artefact stamps it, and any two artefacts that must be consistent are checked on it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime_id: str
    regime_timeline_id: str
    scope: str = Field(description="Economy code or blended market scope, for example 'Global' or 'ch'")
    as_of: str
    model_version: str
    #: Probability mass on the five most cautious states of the latest period. Carried because the framework
    #: weights the crisis tail directly, so a reader needs it beside any allocation.
    crisis_tail: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any], scope: str | None = None) -> "RegimeRef":
        current = payload.get("current") or {}
        return cls(
            regime_id=str(current["regime_id"]),
            regime_timeline_id=str(payload["regime_timeline_id"]),
            scope=str(scope or payload.get("economy_scope", "")),
            as_of=str(payload["as_of"]),
            model_version=str(payload["model_version"]),
            crisis_tail=current.get("crisis_tail"),
        )


class ReturnSetRef(BaseModel):
    """A reference to a published ReturnSet, keyed on scope and horizon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    return_set_id: str
    #: The Regime this was estimated under. Must match whatever it is used alongside.
    regime_id: str
    scope: str
    horizon_years: float
    as_of: str
    model_version: str
    universe_version: str
    values_unit: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any], scope: str) -> "ReturnSetRef":
        return cls(
            return_set_id=str(payload["return_set_id"]),
            regime_id=str(payload["regime_id"]),
            scope=scope,
            horizon_years=float(payload.get("horizon_years", 1.0)),
            as_of=str(payload["as_of"]),
            model_version=str(payload["model_version"]),
            universe_version=str(payload["universe_version"]),
            values_unit=str(payload.get("values_unit", "unknown")),
        )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def regime_path(scope: str, directory: Path | str | None = None) -> Path:
    root = Path(directory) if directory is not None else DEFAULT_REGIME_DIR
    return root / f"{scope}.json"


def returnset_path(
    scope: str,
    horizon_years: float,
    directory: Path | str | None = None,
) -> Path:
    """`<dir>/returnset/<scope>/<horizon>y.json`, with a flat fallback.

    The flat `artifacts/rs.json` is what exists today, before the Fund Map is keyed by horizon. It is
    accepted so the master model runs now, and the key path is preferred so it keeps working when the
    producer catches up.
    """
    root = Path(directory) if directory is not None else DEFAULT_RETURNSET_DIR
    keyed = root / "returnset" / scope / f"{_horizon_label(horizon_years)}.json"
    if keyed.exists():
        return keyed
    return root / "rs.json"


def _horizon_label(horizon_years: float) -> str:
    if float(horizon_years).is_integer():
        return f"{int(horizon_years)}y"
    return f"{horizon_years:g}y".replace(".", "_")


def load_regime(scope: str, directory: Path | str | None = None) -> dict[str, Any]:
    """Read a published Regime timeline, checking the parts a consumer relies on.

    Structural validation only. The producer owns the full validator, and duplicating it here would be the
    same drift problem this module exists to avoid. What is checked is what this side would misread.
    """
    path = regime_path(scope, directory)
    if not path.exists():
        raise ContractUnavailable(
            f"no Regime timeline published for scope {scope!r} at {path}. Publish it with:\n"
            f"  cd Macro_Model && python -m macrofield.cli regime cn in us ch br gb de fr --scope {scope}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))

    for required in ("regime_timeline_id", "as_of", "model_version", "current", "state_grid"):
        if required not in payload:
            raise ValueError(f"regime timeline {path} is missing {required!r}")
    if payload["state_grid"] != STATE_GRID:
        raise ValueError(
            f"regime timeline {path} declares state_grid={payload['state_grid']}, expected {STATE_GRID}"
        )
    if "distributions" not in payload:
        raise ValueError(
            f"regime timeline {path} carries no 'distributions' block, only a state path. The downstream "
            f"objective integrates a 25-length distribution per period, and expanding a path into one is a "
            f"modelling decision the producer owns. Republish with distributions."
        )
    return payload


def load_returnset(
    scope: str,
    horizon_years: float = 1.0,
    directory: Path | str | None = None,
) -> dict[str, Any]:
    """Read a published ReturnSet for a scope and horizon.

    Asserts the manual's invariant that it carries no mean-variance moments. That check is here rather than
    left to the producer because it is an invariant of the *architecture*, not of one engine: the whole point
    of the method is that the curve fit integrates profiles, and a moment arriving on this contract would
    mean something upstream had drifted.
    """
    path = returnset_path(scope, horizon_years, directory)
    if not path.exists():
        raise ContractUnavailable(
            f"no ReturnSet published for scope {scope!r} at horizon {horizon_years}y (looked at {path}). "
            f"Publish it with:\n"
            f"  cd engines/Fund_Map && .venv/Scripts/python -m fmre.cli build-returnset \\\n"
            f"      --timeline ../Macro_Model/output/regime/{scope}.json \\\n"
            f"      --source seed-aware-synthetic \\\n"
            f"      --horizon-years {horizon_years} --out artifacts/rs.json\n"
            f"\n"
            f"  --source is NOT optional. Its default is 'synthetic', a uniform GBM that ignores the seed's\n"
            f"  state-conditional shapes and puts CHF cash at about +11%/yr. This message omitted the flag\n"
            f"  until 3 August 2026, and following it produced exactly that artefact — twice, months apart.\n"
            f"  Fund_Map has its own interpreter; the root .venv has no numpy."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))

    for required in ("return_set_id", "regime_id", "as_of", "model_version", "universe_version"):
        if required not in payload:
            raise ValueError(f"ReturnSet {path} is missing {required!r}")
    _refuse_moments(payload, path)

    published = float(payload.get("horizon_years", 1.0))
    if abs(published - float(horizon_years)) > 1e-9:
        raise ValueError(
            f"ReturnSet {path} is estimated on a {published}y horizon but {horizon_years}y was requested. "
            f"A per-state return is not re-scaled across horizons, because the regime does not persist: "
            f"publish a ReturnSet for this horizon rather than converting."
        )
    return payload


_FORBIDDEN = frozenset({"mu", "sigma", "cov", "covariance", "variance"})


def _refuse_moments(node: Any, path: Path, where: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _FORBIDDEN:
                raise ValueError(
                    f"ReturnSet {path} carries the forbidden key {key!r} at {where or '<root>'}. The "
                    f"contract holds return profiles, not moments."
                )
            _refuse_moments(value, path, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _refuse_moments(value, path, f"{where}[{index}]")


def resolve_pair(
    scope: str,
    horizon_years: float = 1.0,
    regime_dir: Path | str | None = None,
    returnset_dir: Path | str | None = None,
) -> tuple[RegimeRef, ReturnSetRef]:
    """The Regime and ReturnSet for a scope and horizon, checked against each other.

    This is the function the per-user engines should call rather than loading either alone, because the pair
    is only meaningful when the identifiers agree.
    """
    regime = load_regime(scope, regime_dir)
    returnset = load_returnset(scope, horizon_years, returnset_dir)

    regime_ref = RegimeRef.from_payload(regime, scope=scope)
    returnset_ref = ReturnSetRef.from_payload(returnset, scope=scope)

    require_regime_match(returnset_ref.regime_id, regime_ref.regime_id)
    return regime_ref, returnset_ref


def require_regime_match(candidate: str, expected: str, what: str = "ReturnSet") -> None:
    """Refuse two artefacts computed under different Regimes.

    Not reconciled, not warned about, not overridable. Mixing vintages means optimising a profile estimated
    under one macro state against the weights of another, and the result would carry a `regime_id` that did
    not produce it.
    """
    if candidate != expected:
        raise RegimeMismatch(
            f"regime_id mismatch, refusing to proceed. The {what} was computed under "
            f"{candidate!r}; the Regime in use is {expected!r}. Rebuild the {what} against the current "
            f"Regime rather than mixing vintages."
        )
