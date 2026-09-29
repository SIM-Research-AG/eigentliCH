"""Freeze golden layer B: lbsim's findings under 1.0.0 and 1.1.0 on the frozen lbs cases, and ``changes.json``.

Run with the family interpreter::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_layer_b.py

See ``lbsim.layer_b`` for how every changed leaf is attributed to LBSIM-08, LBSIM-11 or LBSIM-07.
"""

from __future__ import annotations

import json
from pathlib import Path

from lbsim.calibration import ACTIVE_SEED, SEED, calibration_hash
from lbsim.layer_b import attribute, findings

HERE = Path(__file__).resolve().parents[1]
CASES = HERE / "golden" / "lbs_cases"
OUT = HERE / "golden" / "layer_b"


def main() -> int:
    (OUT / "expected").mkdir(parents=True, exist_ok=True)
    records = json.loads((CASES / "records.json").read_text(encoding="utf-8"))["records"]
    names = json.loads((CASES / "manifest.json").read_text(encoding="utf-8"))["cases"]
    changes: dict[str, dict[str, list[str]]] = {}
    for name in names:
        folder = CASES / name
        out = {cal.version: findings(folder, records, cal) for cal in (SEED, ACTIVE_SEED)}
        (OUT / "expected" / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
        changes[name] = attribute(folder, records)
        counts = {}
        for who in changes[name].values():
            counts["+".join(who) or "UNATTRIBUTED"] = counts.get("+".join(who) or "UNATTRIBUTED", 0) + 1
        print(name, len(changes[name]), counts)
    summary: dict[str, int] = {}
    for per in changes.values():
        for who in per.values():
            key = "+".join(who) or "UNATTRIBUTED"
            summary[key] = summary.get(key, 0) + 1
    body = {"about": ("Every leaf of the findings artefact that calibration 1.1.0 changes against 1.0.0, per case, "
                      "with the decisions that move it (lbsim.layer_b)."),
            "from": {"version": SEED.version, "hash": calibration_hash(SEED)},
            "to": {"version": ACTIVE_SEED.version, "hash": calibration_hash(ACTIVE_SEED)},
            "summary": summary, "cases": changes}
    (OUT / "changes.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
