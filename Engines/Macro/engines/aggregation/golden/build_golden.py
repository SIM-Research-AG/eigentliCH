"""Build the golden fixtures (dev only; needs the first draft on disk).

    python golden/build_golden.py --cycle FILE --macrofield FILE [--mrs FILE] [--draft PATH]

The inputs are the three upstream artefacts as JSON files (``GET /artefacts/{id}`` of each
engine). Without ``--mrs``, the market half is the first draft's own TAA file
(``Macro_Model/market_risk_signal.csv``, one series, read by the draft's loader), given to every
economy as the draft gave it; the ``MarketRiskSignal`` stand-in is frozen beside the others.

Writes, under ``golden/``:

``inputs/``
    The three inputs, trimmed to the fields this engine reads (its contract mirrors), with the
    sha256 of each trimmed file in ``inputs/source.json``.

``draft_1.0.0.json``
    **The first draft's output, frozen** (engine page section 5). The readings (saturation,
    K_R/K_I, the unsecured change, the cycle superposition and anchors) are prepared by this
    engine (``engine.readings``); then the draft's own ``saa_signal.signal_from_state`` (with
    ``regime.RegimeKernels``) and ``saa_signal.merge`` are run on them with the draft's shipped
    settings, which calibration 1.0.0 carries: the annual macro rows, and the monthly merged
    distributions over the months the draft publishes (the market months whose year has a
    macro reading). Economies are left out where a cycle layer row is missing in a used year,
    since the draft needs the layer on every period.

``expected_<version>.json``
    This build's Regime on the same inputs under each seed calibration and every optimism
    level: the state on every date and the last assessed distribution, per economy and market,
    and the artefact id. Regression only.

Refreeze only with a reason, recorded in DECISIONS.md.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DRAFT = ROOT.parents[3] / "eigentliCH" / "engines" / "Macro_Model"

sys.path.insert(0, str(ROOT / "src"))

from aggregation import calibration as seeds  # noqa: E402
from aggregation.contracts import OPTIMISM_SCALES, CycleState, MacroState, MarketRiskSignal  # noqa: E402
from aggregation.engine import readings, select_economies  # noqa: E402
from aggregation.service import build_regime, content_id, regime_id_for  # noqa: E402


def _dump(path: Path, payload) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_draft(root: Path):
    """The draft's ``regime``, ``saa_signal`` and ``data/taa`` modules, loaded by path under
    their package names, with a minimal stand-in for ``macrofield.control`` (provenance labels
    only; nothing numeric)."""
    for name in ("macrofield", "macrofield.model", "macrofield.data"):
        pkg = types.ModuleType(name)
        pkg.__path__ = []
        sys.modules[name] = pkg
    spec = importlib.util.spec_from_file_location("macrofield.control", root / "macrofield" / "control.py")
    control = importlib.util.module_from_spec(spec)
    sys.modules["macrofield.control"] = control
    spec.loader.exec_module(control)
    modules = {}
    for dotted, rel in (("macrofield.model.regime", "model/regime.py"),
                        ("macrofield.data.taa", "data/taa.py"),
                        ("macrofield.model.saa_signal", "model/saa_signal.py")):
        spec = importlib.util.spec_from_file_location(dotted, root / "macrofield" / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[dotted] = module
        spec.loader.exec_module(module)
        modules[dotted.rsplit(".", 1)[-1]] = module
    return modules["regime"], modules["saa_signal"], modules["taa"]


def draft_market(taa_module, codes) -> dict:
    sig = taa_module.load_signal(DRAFT / "market_risk_signal.csv")
    dates = [f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}" for y, m in sig.months]
    rows = [[float(v) for v in np.asarray(r, dtype=float)] for r in sig.distribution]
    return {"contract_version": "mrs-signal@1.0.0", "artefact_id": "MRS-draft-taa-2026-07",
            "dates": dates,
            "economies": [{"code": c, "name": c, "distribution": rows} for c in codes],
            "provenance": {"snapshot_id": "draft:market_risk_signal.csv", "as_of": dates[-1],
                           "calibration_version": "draft", "regime_id": None}}


def draft_output(regime_mod, saa_mod, mrs: MarketRiskSignal, cycle: CycleState, macro: MacroState) -> dict:
    cal = seeds.DRAFT
    kernels = regime_mod.RegimeKernels(symmetric=cal.kernels.symmetric, crisis=cal.kernels.crisis,
                                       placement=dict(cal.kernels.placement), state_count=25)
    tilts = dict(cal.tilts.coefficients)
    band = (cal.tilts.band_lower, cal.tilts.band_upper)
    chosen, _ = select_economies(mrs, cycle, macro, None)
    mrs_by = {e.code: e for e in mrs.economies}
    cycle_by = {e.code: e for e in cycle.economies}
    macro_by = {e.code: e for e in macro.economies}
    cyear = {y: i for i, y in enumerate(cycle.years)}
    out, left_out = {}, {}
    for code in chosen:
        m, cy = macro_by[code], cycle_by[code]
        reads, _ = readings(m, cy, cycle.years, cal.tilts)
        years, macro_rows, cycle_rows = [], [], []
        for r in reads:
            if r is None:
                continue
            state = saa_mod.StateReading(
                period=r.year, saturation=r.saturation, band=band, real_to_financial=r.real_to_financial,
                unsecured_change=r.unsecured_change, interference=r.interference, alignment=r.alignment,
                capital_years_overdue=r.capital_years_overdue,
                innovation_years_to_trough=r.innovation_years_to_trough)
            signal = saa_mod.signal_from_state(state, kernels=kernels, tilts=tilts,
                                               minimum_tail_probability=cal.reading.minimum_tail_probability,
                                               tail_bins=cal.reading.tail_bins)
            years.append(r.year)
            macro_rows.append(np.asarray(signal.probabilities, dtype=float))
            k = cyear.get(r.year)
            cycle_rows.append(None if k is None or cy.layer[k] is None else np.asarray(cy.layer[k], dtype=float))
        by_year = {y: i for i, y in enumerate(years)}
        months = [(t, d) for t, d in enumerate(mrs.dates)
                  if int(d[:4]) in by_year and mrs_by[code].distribution[t] is not None]
        if any(cycle_rows[by_year[int(d[:4])]] is None for _, d in months):
            left_out[code] = "a used year has no cycle layer row"
            continue
        saa = np.vstack([macro_rows[by_year[int(d[:4])]] for _, d in months])
        taa = np.vstack([np.asarray(mrs_by[code].distribution[t], dtype=float) for t, _ in months])
        cyc = np.vstack([cycle_rows[by_year[int(d[:4])]] for _, d in months])
        merged = saa_mod.merge([int(d[:4]) * 12 + int(d[5:7]) - 1 for _, d in months], saa, taa,
                               weight=cal.blend.macro, cycles=cyc, cycles_weight=cal.blend.cycle)
        out[code] = {"years": years, "macro_rows": [r.tolist() for r in macro_rows],
                     "dates": [d for _, d in months], "merged": np.asarray(merged.merged).tolist()}
    return {"calibration": "1.0.0", "economies": out, "left_out": left_out,
            "draft": str(DRAFT), "note": "the first draft's saa_signal and merge on this engine's readings"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", required=True, type=Path)
    parser.add_argument("--macrofield", required=True, type=Path)
    parser.add_argument("--mrs", type=Path)
    parser.add_argument("--draft", type=Path, default=DRAFT)
    args = parser.parse_args(argv)

    regime_mod, saa_mod, taa_mod = load_draft(args.draft)
    cycle = CycleState.model_validate_json(args.cycle.read_text(encoding="utf-8"))
    macro = MacroState.model_validate_json(args.macrofield.read_text(encoding="utf-8"))
    if args.mrs:
        mrs = MarketRiskSignal.model_validate_json(args.mrs.read_text(encoding="utf-8"))
    else:
        mrs = MarketRiskSignal.model_validate(draft_market(taa_mod, [e.code for e in cycle.economies]))

    inputs = HERE / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    source = {
        "mrs.json": _dump(inputs / "mrs.json", mrs.model_dump(mode="json")),
        "cycle.json": _dump(inputs / "cycle.json", cycle.model_dump(mode="json")),
        "macrofield.json": _dump(inputs / "macrofield.json", macro.model_dump(mode="json")),
    }
    (inputs / "source.json").write_text(json.dumps({"sha256": source, "artefacts": {
        "mrs": mrs.artefact_id, "cycle": cycle.artefact_id, "macrofield": macro.artefact_id}},
        indent=2), encoding="utf-8")

    draft = draft_output(regime_mod, saa_mod, mrs, cycle, macro)
    _dump(HERE / "draft_1.0.0.json", draft)
    print(f"draft: {len(draft['economies'])} economies, left out {draft['left_out']}")

    for cal in seeds.SEEDS:
        expected = {}
        for level in OPTIMISM_SCALES:
            key = content_id("IDK", {"golden": True, "calibration": cal.version, "optimism": level})
            regime = build_regime(mrs, cycle, macro, cal, level, key, regime_id_for(key))
            def last(dists):
                k = max((i for i, d in enumerate(dists) if d is not None), default=None)
                return None if k is None else {"date": regime.dates[k], "distribution": dists[k]}
            expected[level] = {"artefact_id": regime.artefact_id,
                               "economies": {e.code: {"state": e.state, "last": last(e.distribution)}
                                             for e in regime.economies},
                               "markets": {m.code: {"state": m.state, "last": last(m.distribution)}
                                           for m in regime.markets}}
        _dump(HERE / f"expected_{cal.version}.json", expected)
        print(f"expected_{cal.version}.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
