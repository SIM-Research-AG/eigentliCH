"""Freeze golden layer C: this build's own production run on the frozen live inputs. Development only.

Run from the engine folder, after ``dev/freeze_inputs.py``::

    python dev/build_golden_production.py

Solves the test mandates of ``tests/conftest.py`` against ``golden/inputs/`` (the Default Regime and the
fmre ReturnSet, stamped with the Regime's id) with the active calibration, through the pure engine exactly
as the service prepares them, and writes ``golden/production/<case>.json``: weights, objective, month and
binding rows. A regression reference, not an external one: it pins the build as validated on 28.09.2026.

Model-derived research output. Not investment advice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))

from golden_cases import CASES, solve_case  # noqa: E402

OUT = HERE.parent / "golden" / "production"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in CASES:
        outcome, date = solve_case(name)
        payload = {
            "_note": "Golden layer C: pcp's production run of this case on golden/inputs (dev/build_golden_production.py).",
            "case": name, "date": date,
            "weights": [float(v) for v in outcome.weights],
            "raw_sum": outcome.raw_sum, "objective": outcome.objective, "floor": outcome.floor,
            "binding": sorted(f"{b.row}:{b.dimension}:{b.category}:{b.side}" for b in outcome.binding),
        }
        (OUT / f"{name}.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        print(f"froze {name}: {date}, objective {outcome.objective:.10g}, {len(outcome.binding)} binding rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
