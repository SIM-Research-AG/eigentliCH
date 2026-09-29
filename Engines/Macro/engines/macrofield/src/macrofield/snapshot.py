"""The frozen raw folder to snapshot rows. Reads disk; computes nothing about the model.

A snapshot is ``data/raw`` as described by its ``MANIFEST.json``. Loading verifies every file
against its SHA-256 before a single number is read, then parses with :mod:`macrofield.sources`.
The snapshot id is the hash of the (path, sha256) pairs, so the same files are always the same
snapshot and a changed file is always a new one.

Observations are keyed by the source's own country code, so a snapshot does not depend on any
calibration. This module is the stand-in for the Data Feed engine: when that exists, a snapshot
arrives over HTTP with the same series ids and nothing downstream changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .sources import (
    CATALOGUE,
    SourceError,
    bis_total_credit,
    bundesbank_year_end,
    imf_datamapper,
    jst_column,
    penn_world_table,
    world_bank,
)


class SnapshotError(ValueError):
    """The raw folder is not a valid snapshot. The message names the file."""


@dataclass(frozen=True)
class RawSnapshot:
    snapshot_id: str
    frozen_on: str
    manifest: dict
    #: (series_id, area, year, value, source_path)
    rows: tuple[tuple[str, str, int, Optional[float], str], ...]
    #: Things a reader must know, e.g. BIS countries excluded as ambiguous.
    notes: tuple[str, ...]


def snapshot_id(files: list[dict]) -> str:
    pairs = sorted((f["path"], f["sha256"]) for f in files)
    blob = json.dumps(pairs, separators=(",", ":"))
    return "SNP-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def read_manifest(raw: Path) -> dict:
    path = raw / "MANIFEST.json"
    if not path.is_file():
        raise SnapshotError(f"{path} does not exist; freeze a snapshot with dev/freeze_sources.py")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        target = raw / entry["path"]
        if not target.is_file():
            raise SnapshotError(f"{entry['path']} is in the manifest but not on disk")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise SnapshotError(f"{entry['path']} does not match its manifest hash")
    return manifest


def load(raw: Path) -> RawSnapshot:
    manifest = read_manifest(raw)
    world_bank_series = {s.identifier: s.series_id for s in CATALOGUE if s.source == "world_bank"}
    rows: list[tuple[str, str, int, Optional[float], str]] = []
    notes: list[str] = []

    def emit(series_id: str, area: str, values: dict, path: str) -> None:
        for year, value in values.items():
            rows.append((series_id, area, int(year), value, path))

    for entry in manifest["files"]:
        path: str = entry["path"]
        payload = (raw / path).read_bytes()
        parts = path.split("/")
        try:
            if parts[0] == "worldbank" and len(parts) == 3:
                indicator = parts[2].removesuffix(".json")
                if indicator in world_bank_series:
                    emit(world_bank_series[indicator], parts[1], world_bank(payload, path), path)
            elif parts[0] == "bis":
                data, ambiguous = bis_total_credit(payload)
                if ambiguous:
                    notes.append(f"BIS countries excluded as ambiguous: {list(ambiguous)}")
                for area, values in data.items():
                    emit("bis.total_credit", area, values, path)
            elif parts[0] == "bundesbank" and len(parts) == 2:
                # BBBK1_M_OU0308.csv -> bbk.OU0308; the area is Germany by construction.
                code = parts[1].removesuffix(".csv").split("_")[-1]
                emit(f"bbk.{code}", "DE", bundesbank_year_end(payload, path), path)
            elif parts[0] == "imf" and len(parts) == 2:
                indicator = parts[1].removesuffix(".json")
                for area, values in imf_datamapper(payload, path).items():
                    emit(f"imf.{indicator}", area, values, path)
            elif parts[0] == "jst":
                for area, values in jst_column(payload, "gdp").items():
                    emit("jst.gdp", area, values, path)
            elif parts[0] == "pwt":
                for area, columns in penn_world_table(payload).items():
                    for column, values in columns.items():
                        emit(f"pwt.{column}", area, values, path)
            else:
                notes.append(f"{path} is not a recognised source file and was not read")
        except SourceError as exc:
            # A World Bank file with no observations is a published absence, not a broken
            # snapshot: the economy that needs it is reported unavailable at run time.
            if parts[0] == "worldbank":
                notes.append(f"{path}: {exc}")
            else:
                raise SnapshotError(f"{path}: {exc}") from exc

    return RawSnapshot(snapshot_id=snapshot_id(manifest["files"]),
                       frozen_on=str(manifest.get("frozen_on", "")), manifest=manifest,
                       rows=tuple(rows), notes=tuple(notes))
