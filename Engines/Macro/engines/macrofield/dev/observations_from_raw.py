"""Build engine observations straight from ``data/raw``, without the store. Development only.

Used by ``dev/reconcile.py`` and the golden tests to check the pure engine against the old
build independently of PostgreSQL. The ETL (``python -m macrofield load``) uses the same parsers
and the same manifest check, so the two routes see identical numbers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from macrofield.calibration import V1_0_0
from macrofield.contracts import Calibration
from macrofield.sources import CATALOGUE, bis_total_credit, penn_world_table, world_bank

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def load_manifest(raw: Path = RAW) -> dict:
    manifest = json.loads((raw / "MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        digest = hashlib.sha256((raw / entry["path"]).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{entry['path']} does not match its manifest hash")
    return manifest


def observations(cal: Calibration = V1_0_0, raw: Path = RAW) -> dict[str, dict[str, dict]]:
    load_manifest(raw)
    out: dict[str, dict[str, dict]] = {e.code: {} for e in cal.economies}
    bis, _ = bis_total_credit((raw / "bis" / "WS_TC_csv_flat.zip").read_bytes(),
                           {e.bis for e in cal.economies if e.bis})
    pwt = penn_world_table((raw / "pwt" / "pwt1001.xlsx").read_bytes(),
                           {e.pwt for e in cal.economies if e.pwt})
    for e in cal.economies:
        for s in CATALOGUE:
            if s.source == "world_bank":
                path = raw / "worldbank" / e.world_bank / f"{s.identifier}.json"
                if path.is_file():
                    out[e.code][s.series_id] = world_bank(path.read_bytes(), str(path))
        if e.bis and e.bis in bis:
            out[e.code]["bis.total_credit"] = bis[e.bis]
        if e.pwt and e.pwt in pwt:
            for column, values in pwt[e.pwt].items():
                out[e.code][f"pwt.{column}"] = values
    return out
