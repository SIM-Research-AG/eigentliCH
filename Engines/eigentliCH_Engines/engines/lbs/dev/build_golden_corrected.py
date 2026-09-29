"""Freeze golden layer B: lbs's own output under the corrected calibrations 1.2.0 (LBS-24) and 1.3.0 (LBS-28).

Run with this family's interpreter (it imports lbs, not the prototype):

    ..\\..\\.venv\\Scripts\\python dev/build_golden_corrected.py

Layer A (``golden/cases``, ``golden/expected``, frozen from the prototype by ``build_golden.py``) stays the
reference for the reproduction mode (calibrations 1.0.0 and 1.1.0) and is not touched here. Layer B covers the
fifteen layer-A cases and four constructed quirk cases (``golden/corrected/cases/q-*.json``), and writes:

* ``golden/corrected/expected/<case>.json``: the corrected sheet (1.2.0), flattened (``tests/layer_b.py``);
* ``golden/corrected/changes.json``: every figure that differs from the reproduction (1.1.0), per case, with
  the correction that moves it on its own;
* ``golden/corrected/manifest.json``;

and the step 1.3.0 in ``golden/corrected/1.3.0/``: the layer-A cases, the quirk cases and its own cases
(``golden/corrected/1.3.0/cases/r-*.json``) under 1.3.0, and ``changes.json`` against 1.2.0, each changed
figure with the LBS-28 correction that moves it on its own; and the step 1.4.0 in ``golden/corrected/1.4.0/``
(every earlier case and ``v-*`` under 1.4.0, ``changes.json`` against 1.3.0, LBS-35); and the step 1.5.0 in
``golden/corrected/1.5.0/`` (every earlier case under 1.5.0, ``changes.json`` against 1.4.0 and the designated
goals' required returns under both, LBS-38). Step 1.2.0 is rewritten byte for byte as it was
(1.2.0 is unchanged); the diff after a rebuild shows it.

A regression reference, not an outside one: rebuild it only for a deliberate change, and read the diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lbs import ENGINE_VERSION  # noqa: E402
from lbs.calibration import (APPROVED, CORRECTED, CORRECTED_1_3, CORRECTED_1_4, CORRECTED_1_5,  # noqa: E402
                             calibration_hash)
from tests import layer_b as L  # noqa: E402


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8",
                    newline="\n")


def main() -> int:
    names = L.layer_a_names() + L.layer_b_names()
    all_changes = {}
    for name in names:
        write(L.LAYER_B / "expected" / f"{name}.json", L.sheet_of(name, CORRECTED))
        all_changes[name] = L.changes(name)
        print(f"{name:16s} {len(all_changes[name]):4d} changed leaves")
    write(L.LAYER_B / "changes.json", all_changes)
    write(L.LAYER_B / "manifest.json", {
        "built_by": "dev/build_golden_corrected.py", "engine_version": ENGINE_VERSION,
        "corrected": {"version": CORRECTED.version, "hash": calibration_hash(CORRECTED)},
        "reproduction": {"version": APPROVED.version, "hash": calibration_hash(APPROVED)},
        "tolerance": "1e-9 relative on every number (absolute near zero), every other leaf exactly",
        "layer_a_cases": L.layer_a_names(), "quirk_cases": {n: L.CASE_ABOUT[n] for n in L.layer_b_names()},
        "corrections": L.WHY,
    })

    names13 = L.layer_a_names() + L.layer_b_names() + L.layer_b13_names()
    changes13 = {}
    for name in names13:
        write(L.LAYER_B13 / "expected" / f"{name}.json", L.sheet_of(name, CORRECTED_1_3))
        changes13[name] = L.changes(name, "1.3.0")
        print(f"1.3.0 {name:16s} {len(changes13[name]):4d} changed leaves")
    write(L.LAYER_B13 / "changes.json", changes13)
    write(L.LAYER_B13 / "manifest.json", {
        "built_by": "dev/build_golden_corrected.py", "engine_version": ENGINE_VERSION,
        "after": {"version": CORRECTED_1_3.version, "hash": calibration_hash(CORRECTED_1_3)},
        "before": {"version": CORRECTED.version, "hash": calibration_hash(CORRECTED)},
        "tolerance": "1e-9 relative on every number (absolute near zero), every other leaf exactly",
        "layer_a_cases": L.layer_a_names(), "quirk_cases": L.layer_b_names(),
        "cases": {n: L.CASE_ABOUT_13[n] for n in L.layer_b13_names()},
        "corrections": L.WHY_13,
    })

    names14 = names13 + L.layer_b14_names()
    changes14 = {}
    for name in names14:
        write(L.LAYER_B14 / "expected" / f"{name}.json", L.sheet_of(name, CORRECTED_1_4))
        changes14[name] = L.changes_14(name)
        print(f"1.4.0 {name:16s} {len(changes14[name]):4d} changed leaves")
    write(L.LAYER_B14 / "changes.json", changes14)
    write(L.LAYER_B14 / "manifest.json", {
        "built_by": "dev/build_golden_corrected.py", "engine_version": ENGINE_VERSION,
        "after": {"version": CORRECTED_1_4.version, "hash": calibration_hash(CORRECTED_1_4)},
        "before": {"version": CORRECTED_1_3.version, "hash": calibration_hash(CORRECTED_1_3)},
        "tolerance": "1e-9 relative on every number (absolute near zero), every other leaf exactly",
        "layer_a_cases": L.layer_a_names(), "quirk_cases": L.layer_b_names(), "cases_13": L.layer_b13_names(),
        "cases": {n: L.CASE_ABOUT_14[n] for n in L.layer_b14_names()},
        "changes_by": L.WHY_14,
    })

    names15 = L.layer_b15_names()
    changes15, returns15 = {}, {}
    for name in names15:
        write(L.LAYER_B15 / "expected" / f"{name}.json", L.sheet_of(name, CORRECTED_1_5))
        changes15[name] = L.changes_15(name)
        returns = L.required_returns_15(name)
        if returns is not None:
            returns15[name] = returns
        print(f"1.5.0 {name:16s} {len(changes15[name]):4d} changed leaves")
    write(L.LAYER_B15 / "changes.json", changes15)
    write(L.LAYER_B15 / "required_returns.json", returns15)
    write(L.LAYER_B15 / "manifest.json", {
        "built_by": "dev/build_golden_corrected.py", "engine_version": ENGINE_VERSION,
        "after": {"version": CORRECTED_1_5.version, "hash": calibration_hash(CORRECTED_1_5)},
        "before": {"version": CORRECTED_1_4.version, "hash": calibration_hash(CORRECTED_1_4)},
        "tolerance": "1e-9 relative on every number (absolute near zero), every other leaf exactly",
        "cases": names15,
        "changes_by": L.WHY_15, "figures": L.FIGURE_15,
        "required_returns": ("required_returns.json: the designated goal's required return under 1.4.0 and 1.5.0, "
                             "nominal and real, and its move in points, for every case that has one"),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
