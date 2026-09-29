"""Freeze the earning-power golden: the eigentliCH prototype's ``human_capital.earning_power`` (LBSIM-11).

Run with the PROTOTYPE's interpreter, never this family's (it imports the prototype's services)::

    C:\\Users\\nicol\\Desktop\\SIM_NAS\\Projects\\eigentliCH\\Prototype\\.venv\\Scripts\\python.exe -X utf8 dev/build_golden_earning.py

The prototype's function is called, not reimplemented: ``services/human_capital.earning_power`` reaches the draft's
``personal_alm.model.dynamics.earning_power`` by path, at the ``earning_power_at_unit`` of the ``human-capital``
record, and applies the responsibility tier. The record passed in is lbs's seed record (the one lbs's
calibrations carry), so the golden is the computation lbsim must reproduce on the record lbsim reads.

The households are lbs's golden cases (``engines/lbs/golden/cases``, read only): every adult with intake answers,
under each responsibility tier (by key and by label, as the app sends them) and, for top management, under a
published sector, an unpublished one and none. Nothing is written outside ``golden/earning``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

PROTO = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\Prototype")
HERE = Path(__file__).resolve().parents[1]
LBS = HERE.parent / "lbs"
OUT = HERE / "golden" / "earning"
RECORD = LBS / "src" / "lbs" / "seed_records" / "human-capital.json"

sys.path.insert(0, str(PROTO / "backend"))

from eigentlich.services import human_capital as hc  # noqa: E402

VARIANTS: tuple[tuple[str | None, str | None], ...] = (
    (None, None),
    ("ohne Kaderfunktion", None),
    ("Keine Führungsfunktion", None),
    ("oberes und mittleres Kader", None),
    ("Oberes oder mittleres Kader", None),
    ("Upper or middle management", None),
    ("topmanagement", None),
    ("topmanagement", "Banken"),
    ("Oberste Führung", "Gastronomie"),
    ("Top management", "Informationstechnologie"),
    ("topmanagement", "Landwirtschaft"),
    ("Abteilungsleitung", None),
)


def main() -> int:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in sorted((LBS / "golden" / "cases").glob("*.json")):
        request = json.loads(case.read_text(encoding="utf-8"))
        household = request.get("household") or {}
        for person in household.get("persons") or []:
            if person.get("kind") != "adult" or person.get("age") is None:
                continue
            answers = {k: v for k, v in (person.get("human_capital") or {}).items() if v is not None}
            caps = hc.capitals(answers, record=record)
            for kader, sector in VARIANTS:
                given = dict(answers)
                if kader is not None:
                    given["kader"] = kader
                if sector is not None:
                    given["sector"] = sector
                ep = hc.earning_power(given, record=record, age=float(person["age"]))
                rows.append({
                    "case": case.stem, "person_id": person["person_id"], "age": person["age"],
                    "qualification_highest": answers.get("qualification_highest"),
                    "kader": kader, "sector": sector,
                    "E": caps.E.value, "N": caps.N.value, "H": caps.H.value,
                    "earning_power": dataclasses.asdict(ep) if ep is not None else None,
                })
    manifest = {
        "built_by": "dev/build_golden_earning.py",
        "interpreter": sys.executable,
        "prototype": str(PROTO),
        "human_capital_py_sha256": hashlib.sha256(Path(hc.__file__).read_bytes()).hexdigest(),
        "record": str(RECORD),
        "record_sha256": hashlib.sha256(RECORD.read_bytes()).hexdigest(),
        "earning_power_at_unit": record["earning_power"]["calibration"]["earning_power_at_unit"],
        "rows": len(rows),
    }
    (OUT / "expected.json").write_text(json.dumps({"manifest": manifest, "rows": rows}, ensure_ascii=False,
                                                  indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(len(rows), "rows,", sum(1 for r in rows if r["earning_power"]), "with an earning power")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
