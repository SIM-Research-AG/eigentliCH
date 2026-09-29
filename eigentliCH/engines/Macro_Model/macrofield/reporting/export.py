"""Machine-readable export of results.

Brief section 6: export machine-readable results as CSV and JSON alongside charts, and make every chart
and table carry the calibration window, the data vintage, and an "illustrative or model-derived" label on
any projected path.

The labelling is enforced here rather than left to each caller. `ResultBundle` requires the window and the
vintage, and `write_json` refuses to write a payload whose projected sections are unlabelled. A label that
depends on somebody remembering to add it is not a safeguard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

#: The label every projected path must carry, per brief section 6.
PROJECTION_LABEL = "illustrative, model-derived"

#: The disclaimer every export and every brief must carry, per brief sections 6 and 7.
DISCLAIMER = (
    "This is model-derived research and decision support, not investment advice. Projected paths are "
    "consequences of the calibrated model rather than dated predictions."
)

#: Payload keys whose contents are projections and therefore require a label.
PROJECTED_SECTIONS = ("scenarios", "stock_to_gold", "synchronisation", "projection")


class ExportError(ValueError):
    """Raised when a result cannot be exported as required."""


@dataclass
class ResultBundle:
    """Everything one economy's run produced, ready to write out.

    Attributes:
        economy: The economy code.
        calibration_window: The (first, last) period calibrated over.
        data_vintage: Per-series vintage or retrieval date, so a number can be traced to what was
            published when.
        series: Tabular results, as named data frames.
        diagnostics: Scalar and nested diagnostic results.
        adjustments: The standardising adjustment applied per series, if any.
        notes: Anything a reader must know.
    """

    economy: str
    calibration_window: tuple[int, int]
    data_vintage: Mapping[str, str]
    series: dict[str, pd.DataFrame] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    adjustments: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        first, last = self.calibration_window
        if first > last:
            raise ExportError(
                f"the calibration window {self.calibration_window} runs backwards"
            )
        if not self.data_vintage:
            raise ExportError(
                "a result bundle must carry the data vintage. Brief section 6 requires every chart and "
                "table to state it, so it cannot be optional here."
            )

    def header(self) -> dict[str, Any]:
        """The provenance header every export carries."""
        return {
            "economy": self.economy,
            "calibration_window": {
                "first": int(self.calibration_window[0]),
                "last": int(self.calibration_window[1]),
            },
            "data_vintage": dict(self.data_vintage),
            "standardising_adjustments": dict(self.adjustments),
            "projection_label": PROJECTION_LABEL,
            "disclaimer": DISCLAIMER,
            "notes": list(self.notes),
        }


def _jsonable(value: Any) -> Any:
    """Convert numpy and pandas types into plain JSON-serialisable ones."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, pd.DataFrame):
        return {str(k): _jsonable(v) for k, v in value.to_dict(orient="list").items()}
    if isinstance(value, pd.Series):
        return _jsonable(value.to_dict())
    if isinstance(value, float):
        # A bare NaN or infinity is not valid JSON, and writing it produces a file that some parsers
        # accept and others reject, which is worse than losing the distinction.
        return None if not np.isfinite(value) else value
    return value


def _check_projection_labels(payload: Mapping[str, Any]) -> list[str]:
    """Return the projected sections that lack a label."""
    unlabelled: list[str] = []
    for key in PROJECTED_SECTIONS:
        section = payload.get(key)
        if section is None:
            continue
        candidates = section if isinstance(section, list) else [section]
        for candidate in candidates:
            if isinstance(candidate, Mapping) and "label" not in candidate:
                unlabelled.append(key)
                break
    return unlabelled


def write_json(bundle: ResultBundle, path: Path) -> Path:
    """Write the full result as JSON.

    Raises:
        ExportError: If a projected section lacks its label. Brief section 6 requires the label on any
            projected path, and enforcing it at the write boundary is the only way to be sure it is
            present in what actually leaves the programme.
    """
    payload: dict[str, Any] = {"header": bundle.header()}
    payload["diagnostics"] = _jsonable(bundle.diagnostics)
    payload["series"] = {name: _jsonable(frame) for name, frame in bundle.series.items()}

    unlabelled = _check_projection_labels(bundle.diagnostics)
    if unlabelled:
        raise ExportError(
            f"these projected sections carry no label: {unlabelled}. Brief section 6 requires every "
            f"projected path to be labelled {PROJECTION_LABEL!r}, so the export is refused rather than "
            f"written without it."
        )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False, allow_nan=False)
        handle.write("\n")
    return path


def write_csv(bundle: ResultBundle, directory: Path, prefix: str | None = None) -> list[Path]:
    """Write each tabular result as a CSV, with the provenance header as comment lines.

    The header is written as comments rather than a separate sidecar file, so that a CSV opened on its own
    still states which economy, window and vintage it came from. A table that travels without its
    provenance is how a number ends up quoted against the wrong vintage.

    Returns:
        The paths written.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = prefix or bundle.economy
    written: list[Path] = []

    header_lines = [
        f"# economy: {bundle.economy}",
        f"# calibration window: {bundle.calibration_window[0]} to {bundle.calibration_window[1]}",
        f"# data vintage: {json.dumps(dict(bundle.data_vintage), sort_keys=True)}",
        f"# standardising adjustments: {json.dumps(_jsonable(bundle.adjustments), sort_keys=True)}",
        f"# projected paths are: {PROJECTION_LABEL}",
        f"# {DISCLAIMER}",
    ]

    for name, frame in bundle.series.items():
        path = directory / f"{stem}_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            for line in header_lines:
                handle.write(line + "\n")
            frame.to_csv(handle, index=True)
        written.append(path)
    return written


def state_frame(
    periods: Sequence[Any],
    observed: Mapping[str, Sequence[float]],
    simulated: Mapping[str, Sequence[float]] | None = None,
) -> pd.DataFrame:
    """Assemble the three-body trajectory with the calibration fit alongside the observations.

    Brief section 6 asks for the trajectory with the fit shown against data, so observed and simulated
    columns sit in one table rather than in two files a reader has to join.
    """
    data: dict[str, Any] = {}
    for name, values in observed.items():
        data[f"{name}_observed"] = list(values)
    if simulated:
        for name, values in simulated.items():
            if len(values):
                data[f"{name}_simulated"] = list(values)
    frame = pd.DataFrame(data, index=pd.Index(list(periods), name="period"))
    return frame
