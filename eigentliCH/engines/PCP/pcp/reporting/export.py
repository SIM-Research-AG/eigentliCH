"""The single write boundary.

Every artefact leaves through here, which is the point: the stamps that make a number interpretable (the
regime vintage, the ReturnSet vintage, the mandate identity, the currency, the versions, the
model-derived label and the disclaimer) are attached at the moment of writing. A caller cannot forget
them, because a caller never assembles a payload itself.

Nothing here computes. If a figure is not already on the `Result`, it does not appear in the file.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from pcp.config import Config
from pcp.contracts import Allocation, Result

#: Stamped on every projected or backtested figure, per the house rules.
MODEL_DERIVED = "model-derived"


def result_payload(
    result: Result,
    config: Config,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The full machine-readable payload for a run.

    Shaped as spec section 5 describes, with the header carrying everything needed to trace the numbers
    back to the inputs and versions that produced them.
    """
    mandate = result.mandate
    current = result.current
    vocabularies = config.vocabularies

    payload: dict[str, Any] = {
        "header": {
            "client": mandate.client,
            "mandate": mandate.name,
            "market": mandate.market,
            "currency": mandate.currency,
            "benchmark": mandate.benchmark,
            "as_of": result.as_of,
            "regime_id": result.regime_id,
            "regime_timeline_id": result.regime_timeline_id,
            "regime_model_version": result.regime_model_version,
            "return_set_id": result.return_set_id,
            "returnset_model_version": result.returnset_model_version,
            "universe_version": result.universe_version,
            "engine_version": result.engine_version,
            "optimiser": result.optimiser,
            "speed": result.speed,
            "idempotency_key": result.idempotency_key,
            "trace_id": result.trace_id,
            "label": result.label,
            "values_unit": str(config.get("contracts.expected_values_unit")),
            "horizon_years": mandate.horizon_years,
            "country_weights": result.country_weights,
            "crisis_tail": result.crisis_tail,
            "conditions_met": current.conditions_met,
            "disclaimer": config.disclaimer,
        }
        | (
            # How much of the objective the weights control. Promoted into the header rather than left in
            # the diagnostics, because it qualifies every number below it (decisions.md D28, D29).
            {
                "weight_leverage": diagnostics.get("weight_leverage"),
                "objective_floor": diagnostics.get("objective_floor"),
            }
            if diagnostics is not None
            else {}
        ),
        "vocabularies": {
            "roles": list(vocabularies.roles.labels),
            "scenarios": list(vocabularies.scenarios.labels),
            "note": (
                "the portfolio map is roles by scenarios, with scenarios ordered crisis-low to boom-high "
                "matching the state index. Any boom-first presentation is a display convention only."
            ),
        },
        "allocation": _allocation_rows(result, current, diagnostics),
        "portfolio_map": _as_lists(current.portfolio_map),
        "role_allocation": current.role_allocation,
        "return_dist_target": _as_lists(mandate.target_curve),
        "return_dist_final": _as_lists(current.return_dist_final),
        "regime": _as_lists(current.regime),
        "esg": current.esg,
        "esg_minimum": mandate.esg_min,
        "objective_value": current.objective_value,
        "solver": {
            "method": current.solver_method,
            "status": current.solver_status,
            "conditions_met": current.conditions_met,
        },
        "binding_constraints": [
            {
                "dimension": b.dimension,
                "category": b.category,
                "side": b.side,
                "bound": b.bound,
                "realised": b.realised,
            }
            for b in current.binding
        ],
        "notes": list(result.notes),
    }

    if len(result.allocations) > 1:
        payload["timeline"] = [
            {
                "period": allocation.period,
                "label": MODEL_DERIVED,
                "conditions_met": allocation.conditions_met,
                "objective_value": allocation.objective_value,
                "esg": allocation.esg,
                "role_allocation": allocation.role_allocation,
                "allocation": _as_lists(allocation.weights),
                "return_dist_final": _as_lists(allocation.return_dist_final),
            }
            for allocation in result.allocations
        ]
        payload["header"]["backtest_periods"] = len(result.allocations)
        payload["header"]["backtest_label"] = MODEL_DERIVED

    if diagnostics is not None:
        payload["diagnostics"] = _jsonable(diagnostics)

    return payload


def _allocation_rows(
    result: Result,
    current: Allocation,
    diagnostics: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """One row per instrument, carrying the classification each weight was constrained by."""
    by_id: dict[int, dict[str, Any]] = {}
    if diagnostics is not None:
        for row in diagnostics.get("instruments", []) or []:
            by_id[int(row["bb_id"])] = row

    rows: list[dict[str, Any]] = []
    for bb_id, weight in zip(current.bb_ids, np.asarray(current.weights, dtype=float)):
        row: dict[str, Any] = {"bb_id": int(bb_id), "weight": float(weight)}
        extra = by_id.get(int(bb_id))
        if extra is not None:
            row.update(
                {
                    key: extra[key]
                    for key in (
                        "name", "ticker", "role", "region_geo", "region_scope", "currency",
                        "asset_class", "economic_phase", "capital_type", "liquidity",
                        "home_scenario", "esg",
                    )
                    if key in extra
                }
            )
        rows.append(row)
    return rows


def write_json(
    result: Result,
    config: Config,
    path: Path | str,
    diagnostics: Mapping[str, Any] | None = None,
) -> Path:
    """Write the result as JSON, with every stamp attached."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = result_payload(result, config, diagnostics)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    return target


def write_csv(
    result: Result,
    config: Config,
    path: Path | str,
    diagnostics: Mapping[str, Any] | None = None,
) -> Path:
    """Write the allocation as CSV, with the stamps as comment lines above the header.

    The stamps are written as `#` comments rather than dropped, because a CSV that leaves them out is a
    column of numbers with no way back to the regime and vintage that produced it. Spreadsheet software
    shows them as leading rows, which is the intended effect.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = result_payload(result, config, diagnostics)
    header = payload["header"]

    with target.open("w", encoding="utf-8", newline="") as handle:
        for key in (
            "client", "mandate", "market", "currency", "as_of", "regime_id", "return_set_id",
            "engine_version", "optimiser", "speed", "idempotency_key", "trace_id", "label",
            "values_unit", "conditions_met",
        ):
            handle.write(f"# {key}: {header[key]}\n")
        handle.write(f"# disclaimer: {header['disclaimer']}\n")

        rows = payload["allocation"]
        fieldnames = [
            "bb_id", "name", "ticker", "weight", "role", "region_geo", "region_scope", "currency",
            "asset_class", "economic_phase", "capital_type", "liquidity", "home_scenario", "esg",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return target


def export_result(
    result: Result,
    config: Config,
    directory: Path | str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    stem: str | None = None,
    write_brief: bool = True,
) -> dict[str, Path]:
    """Write every artefact for a run and return the paths.

    The stem defaults to the mandate identity, so repeated runs of one mandate overwrite rather than
    accumulate. Two mandates never collide.
    """
    root = Path(directory) if directory is not None else _default_output(config)
    name = stem or f"{result.mandate.client}_{result.mandate.name}".replace(" ", "_")

    written = {
        "json": write_json(result, config, root / f"{name}.json", diagnostics),
        "csv": write_csv(result, config, root / f"{name}.csv", diagnostics),
    }
    if write_brief:
        from pcp.reporting.brief import render_brief

        target = root / f"{name}_brief.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_brief(result, config, diagnostics), encoding="utf-8")
        written["brief"] = target
    return written


def _default_output(config: Config) -> Path:
    configured = Path(str(config.get("paths.output_dir")))
    if configured.is_absolute():
        return configured
    return (Path(__file__).resolve().parent.parent.parent / configured).resolve()


def _as_lists(value: Any) -> Any:
    array = np.asarray(value, dtype=float)
    if array.ndim == 0:
        return float(array)
    return array.tolist()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value
