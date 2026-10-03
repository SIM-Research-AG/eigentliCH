"""Freeze golden layer B: lbsim's findings under 1.0.0 to 1.6.0 on the frozen lbs cases, and ``changes.json`` in
six steps.

Run with the family interpreter::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_layer_b.py

See ``lbsim.layer_b``: step one attributes every leaf 1.1.0 changes against 1.0.0 to LBSIM-08, LBSIM-11 or
LBSIM-07; step two attributes every leaf 1.2.0 changes against 1.1.0 to the income-path correction (P-9); step
three every leaf 1.3.0 changes against 1.2.0 to the plan settings (O-18), which move none; step four every leaf
1.4.0 changes against 1.3.0 to the paths' household (P-21 to P-24), which moves none either; step five every leaf
1.5.0 changes against 1.4.0 to the stated incomes (P-25); step six every leaf 1.6.0 changes against 1.5.0 to the
iteration limit (O-19), which moves none.
"""

from __future__ import annotations

import json
from pathlib import Path

from lbsim.calibration import ACTIVE_SEED, SEED, SEED_1_1, SEED_1_2, SEED_1_3, SEED_1_4, SEED_1_5, calibration_hash
from lbsim.layer_b import (attribute, attribute_1_2, attribute_1_3, attribute_1_4, attribute_1_5, attribute_1_6,
                           findings)

HERE = Path(__file__).resolve().parents[1]
CASES = HERE / "golden" / "lbs_cases"
OUT = HERE / "golden" / "layer_b"


def _summary(changes: dict[str, dict[str, list[str]]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for per in changes.values():
        for who in per.values():
            key = "+".join(who) or "UNATTRIBUTED"
            out[key] = out.get(key, 0) + 1
    return out


def main() -> int:
    (OUT / "expected").mkdir(parents=True, exist_ok=True)
    records = json.loads((CASES / "records.json").read_text(encoding="utf-8"))["records"]
    names = json.loads((CASES / "manifest.json").read_text(encoding="utf-8"))["cases"]
    changes: dict[str, dict[str, list[str]]] = {}
    changes_12: dict[str, dict[str, list[str]]] = {}
    changes_13: dict[str, dict[str, list[str]]] = {}
    changes_14: dict[str, dict[str, list[str]]] = {}
    changes_15: dict[str, dict[str, list[str]]] = {}
    changes_16: dict[str, dict[str, list[str]]] = {}
    for name in names:
        folder = CASES / name
        out = {cal.version: findings(folder, records, cal) for cal in (SEED, SEED_1_1, SEED_1_2, SEED_1_3, SEED_1_4,
                                                                 SEED_1_5, ACTIVE_SEED)}
        (OUT / "expected" / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
        changes[name] = attribute(folder, records)
        changes_12[name] = attribute_1_2(folder, records)
        changes_13[name] = attribute_1_3(folder, records)
        changes_14[name] = attribute_1_4(folder, records)
        changes_15[name] = attribute_1_5(folder, records)
        changes_16[name] = attribute_1_6(folder, records)
        print(name, len(changes[name]), len(changes_12[name]), len(changes_13[name]), len(changes_14[name]))
    body = {"about": ("Every leaf of the findings artefact that calibration 1.1.0 changes against 1.0.0, per case, "
                      "with the decisions that move it (lbsim.layer_b)."),
            "from": {"version": SEED.version, "hash": calibration_hash(SEED)},
            "to": {"version": SEED_1_1.version, "hash": calibration_hash(SEED_1_1)},
            "summary": _summary(changes), "cases": changes,
            "step_1_2_0": {
                "about": ("Every leaf calibration 1.2.0 changes against 1.1.0: the income-path correction "
                          "(DECISIONS P-9), its one switch."),
                "from": {"version": SEED_1_1.version, "hash": calibration_hash(SEED_1_1)},
                "to": {"version": SEED_1_2.version, "hash": calibration_hash(SEED_1_2)},
                "summary": _summary(changes_12), "cases": changes_12},
            "step_1_3_0": {
                "about": ("Every leaf calibration 1.3.0 changes against 1.2.0: the owner's plan settings (DECISIONS "
                          "O-18, the optimiser block only), which the findings do not read."),
                "from": {"version": SEED_1_2.version, "hash": calibration_hash(SEED_1_2)},
                "to": {"version": SEED_1_3.version, "hash": calibration_hash(SEED_1_3)},
                "summary": _summary(changes_13), "cases": changes_13},
            "step_1_4_0": {
                "about": ("Every leaf calibration 1.4.0 changes against 1.3.0: the paths' household (DECISIONS P-21 "
                          "to P-24, one switch that only the Monte Carlo reads)."),
                "from": {"version": SEED_1_3.version, "hash": calibration_hash(SEED_1_3)},
                "to": {"version": SEED_1_4.version, "hash": calibration_hash(SEED_1_4)},
                "summary": _summary(changes_14), "cases": changes_14},
            "step_1_5_0": {
                "about": ("Every leaf calibration 1.5.0 changes against 1.4.0: each stated income where it belongs "
                          "(DECISIONS P-25), its one switch."),
                "from": {"version": SEED_1_4.version, "hash": calibration_hash(SEED_1_4)},
                "to": {"version": SEED_1_5.version, "hash": calibration_hash(SEED_1_5)},
                "summary": _summary(changes_15), "cases": changes_15},
            "step_1_6_0": {
                "about": ("Every leaf calibration 1.6.0 changes against 1.5.0: the owner's iteration limit of 1000 "
                          "(DECISIONS O-19, the optimiser block only), which the findings do not read."),
                "from": {"version": SEED_1_5.version, "hash": calibration_hash(SEED_1_5)},
                "to": {"version": ACTIVE_SEED.version, "hash": calibration_hash(ACTIVE_SEED)},
                "summary": _summary(changes_16), "cases": changes_16}}
    (OUT / "changes.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(body["summary"], body["step_1_2_0"]["summary"], body["step_1_3_0"]["summary"],
          body["step_1_4_0"]["summary"], body["step_1_5_0"]["summary"], body["step_1_6_0"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
