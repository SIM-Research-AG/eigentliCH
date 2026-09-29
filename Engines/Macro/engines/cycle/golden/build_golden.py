"""Build the golden fixtures (dev only; needs the ``dev`` extra and the first draft on disk).

    python golden/build_golden.py [--datafeed URL] [--draft PATH]

Writes, under ``golden/snapshot_2026-01-05.public/``:

``panel.json`` and ``source.json``
    The production snapshot ``matlab-m_ts-2026-01-05.public-8e90be47``, fetched from
    datafeed ``GET /panel`` in full, with datafeed's manifest checksum.

``draft_1.0.0.json``
    **The first draft's output, frozen** (engine page section 5). The inputs are prepared
    by this engine (``engine.prepare_inputs``: annualise, real output growth, saturation);
    then the draft's own functions from ``Macro_Model/macrofield/model/cycles.py`` and
    ``cycle_bins.py`` are run on them, with statsmodels' filter and the draft's settings as
    calibration 1.0.0 carries them. Only economies whose inputs cover the whole window,
    since the draft refuses a gap and needs every cycle on the same periods.

``expected_1.0.0.json``
    This build's output on the same panel under calibration 1.0.0. Regression only.

``macrofield_<artefact>.json``
    The macrofield ``MacroState`` that calibration 1.1.0 reads (the output path Y per
    economy), fetched from macrofield ``GET /artefacts/{id}`` and trimmed to the fields this
    engine reads, with the sha256 of that trimmed state.

``expected_1.1.0.json``
    This build's output on ``panel.json`` and that state under calibration 1.1.0. Regression only.

Refreeze only with a reason, recorded in DECISIONS.md.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SNAPSHOT_ID = "matlab-m_ts-2026-01-05.public-8e90be47"
FOLDER = HERE / "snapshot_2026-01-05.public"
DRAFT = ROOT.parents[3] / "eigentliCH" / "engines" / "Macro_Model" / "macrofield" / "model"

sys.path.insert(0, str(ROOT / "src"))

from cycle.calibration import DEFAULT, HISTORICAL_RESETS  # noqa: E402
from cycle.clients import state_checksum  # noqa: E402
from cycle.contracts import Panel, UpstreamMacroState  # noqa: E402
from cycle.engine import annualise, prepare_inputs, run_model  # noqa: E402


def _nan_list(x) -> list:
    return [None if not np.isfinite(v) else float(v) for v in np.atleast_1d(np.asarray(x, dtype=float))]


def load_draft(folder: Path):
    """The draft's two modules, loaded by path so its package (and its I/O) never imports."""
    modules = []
    for name in ("cycles", "cycle_bins"):
        spec = importlib.util.spec_from_file_location(f"draft_{name}", folder / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def fetch(datafeed: str) -> Panel:
    FOLDER.mkdir(parents=True, exist_ok=True)
    base = datafeed.rstrip("/")
    body = httpx.get(f"{base}/panel", params={"snapshot_id": SNAPSHOT_ID}, timeout=120).raise_for_status()
    manifest = httpx.get(f"{base}/snapshots/{SNAPSHOT_ID}", timeout=30).raise_for_status().json()
    (FOLDER / "panel.json").write_bytes(body.content)
    (FOLDER / "source.json").write_text(json.dumps({
        "_note": ("Frozen copy of datafeed's production snapshot, fetched from GET /panel. The "
                  "checksum is datafeed's manifest checksum; test_golden checks the copy against it."),
        "snapshot_id": SNAPSHOT_ID, "datafeed_checksum": manifest["checksum"],
    }, indent=1), encoding="utf-8")
    print(f"wrote {FOLDER / 'panel.json'} from {base}")
    return Panel.model_validate_json(body.content)


def draft_output(panel: Panel, economies: list[str], draft_folder: Path) -> dict:
    cycles, bins = load_draft(draft_folder)
    cal = DEFAULT
    annual = annualise(panel, economies, cal.annualisation)
    saturation, inputs = prepare_inputs(annual, cal)
    periods = list(annual.years)
    n = len(periods)
    bins_settings = {  # config/defaults.yaml cycles.bins, restricted to the five
        "members": [c.name for c in cal.cycles],
        "weights": {},
        "orientation": {c.name: c.orientation for c in cal.cycles},
        "widths": cal.widths.model_dump(),
        "skew_coefficient": cal.skew_coefficient,
    }
    out = {}
    for j, code in enumerate(economies):
        growth, span = inputs[j]["output_growth"]
        if span != (0, n - 1):
            continue
        estimates = {}
        for spec in (c for c in cal.cycles if c.kind == "estimated"):
            band = (cycles.CycleBand.from_explicit(spec.name, *spec.band) if spec.band
                    else cycles.CycleBand.from_prior(spec.name, spec.period_years, cal.band_fraction))
            estimates[spec.name] = cycles.extract_cycle(growth, band, sampling_per_year=1.0)
        anchored = {
            "innovation": cycles.fixed_innovation_cycle(periods, trough_year=2032.0, period_years=47.0),
            "capital": cycles.anchor_capital_cycle(periods, saturation[:, j], anchor_saturation=3.5,
                                                   years_into_cycle_at_anchor=90.0, period_years=90.0),
        }
        for name, cycle in anchored.items():
            estimates[name] = cycle.estimate
        layers = bins.layer_matrix(estimates, anchored, bins_settings, n, step_years=1.0)[0]
        superposition = cycles.superpose(periods, estimates, {})
        synchrony = cycles.detect_synchrony(periods, estimates, phase_tolerance_radians=0.5,
                                            minimum_cycles_in_phase=3)
        out[code] = {
            "cycles": {name: {
                "identifiable": bool(e.identifiable),
                "estimated_period": e.estimated_period,
                "component": None if e.component is None else _nan_list(e.component),
                "phase": None if e.phase is None else _nan_list(e.phase),
                "amplitude": None if e.amplitude is None else _nan_list(e.amplitude),
            } for name, e in estimates.items()},
            "anchored": {name: {"anchored": bool(a.anchored), "reference_year": a.reference_year,
                                "years_into_cycle": None if a.years_into_cycle is None
                                else _nan_list(a.years_into_cycle)} for name, a in anchored.items()},
            "layer": [_nan_list(row) for row in layers],
            "superposition": _nan_list(superposition.total),
            "alignment": _nan_list(superposition.alignment),
            "synchrony_windows": [{"start_year": int(w.start_period), "end_year": int(w.end_period),
                                   "cycles": list(w.cycles_in_phase),
                                   "mean_absolute_phase_spread": w.mean_absolute_phase_spread}
                                  for w in synchrony.windows],
        }
    return {"_note": ("The first draft (Macro_Model cycles.py, cycle_bins.py; statsmodels "
                      "cffilter) run on inputs prepared by this engine from panel.json, under the "
                      "settings calibration 1.0.0 carries. Economies whose inputs cover the whole "
                      "window only."),
            "years": periods, "economies": out}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datafeed", default="http://127.0.0.1:8001")
    parser.add_argument("--draft", type=Path, default=DRAFT)
    parser.add_argument("--macrofield", default="http://127.0.0.1:8003")
    parser.add_argument("--macrofield-artefact", default="MFS-6183873b127fcd58")
    args = parser.parse_args(argv)

    panel = fetch(args.datafeed)
    economies = ["BR", "CH", "CN", "EU", "IN", "ID", "MY", "PH", "TH", "GB", "US", "JP", "BD", "VN", "DE", "ES"]
    draft = draft_output(panel, economies, args.draft)
    (FOLDER / "draft_1.0.0.json").write_text(json.dumps(draft), encoding="utf-8")
    print(f"froze the draft on {len(draft['economies'])} economies: {', '.join(draft['economies'])}")

    built = run_model(panel, DEFAULT, economies, {c: c for c in economies})
    (FOLDER / "expected_1.0.0.json").write_text(json.dumps({
        "_note": "Frozen output of this build on panel.json under calibration 1.0.0. Regression only.",
        "years": list(built.years),
        "economies": [e.model_dump(mode="json") for e in built.economies],
        "coverage": built.coverage.model_dump(mode="json"),
    }), encoding="utf-8")
    print("froze this build's output")

    state = fetch_macrofield(args.macrofield, args.macrofield_artefact)
    macro = {e.code: (e.years, e.observed.Y) for e in state.economies if e.status == "ok" and e.observed}
    active = run_model(panel, HISTORICAL_RESETS, economies, {c: c for c in economies}, macro)
    (FOLDER / "expected_1.1.0.json").write_text(json.dumps({
        "_note": ("Frozen output of this build on panel.json and the frozen macrofield state under "
                  "calibration 1.1.0. Regression only."),
        "macrofield_artefact": state.artefact_id,
        "years": list(active.years),
        "economies": [e.model_dump(mode="json") for e in active.economies],
        "coverage": active.coverage.model_dump(mode="json"),
    }), encoding="utf-8")
    print("froze this build's output under 1.1.0")
    return 0


def fetch_macrofield(url: str, artefact_id: str) -> UpstreamMacroState:
    """macrofield's state, trimmed to what this engine reads, frozen with its checksum."""
    body = httpx.get(f"{url.rstrip('/')}/artefacts/{artefact_id}", timeout=120).raise_for_status()
    state = UpstreamMacroState.model_validate_json(body.content)
    path = HERE / f"macrofield_{artefact_id}.json"
    path.write_text(json.dumps({"state": state.model_dump(mode="json"),
                                "state_sha256": state_checksum(state),
                                "_note": ("macrofield GET /artefacts/%s, trimmed to the fields cycle reads "
                                          "(UpstreamMacroState)." % artefact_id)}), encoding="utf-8")
    print(f"wrote {path} from {url}")
    return state


if __name__ == "__main__":
    raise SystemExit(main())
