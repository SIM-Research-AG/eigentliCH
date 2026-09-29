"""Recorded MATLAB output as reference data: parse, describe, load.

The CIO site ``signal`` export is MATLAB's ``WM`` struct as JSON: ``{segment: [month_1 ..
month_n]}``, each month ``{economy: [25 floats]}``. It carries no dates; month k is the k-th
month of the ``M_TS`` it was computed from. Parsing is pure; ``load`` writes it to the store.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .contracts import N_STATES

#: MATLAB segment field -> mrs segment name.
SEGMENTS = {"BusinessCycle": "business_cycle", "Investment": "investment",
            "MarketBehaviour": "market_behaviour", "MarketStress": "market_stress"}

#: MATLAB economy field -> datafeed country code (the datafeed registry's ``matlab`` column).
ECONOMIES = {"Brazil": "BR", "CH": "CH", "China": "CN", "EU": "EU", "India": "IN",
             "Indonesia": "ID", "Malaysia": "MY", "Philippines": "PH", "Thailand": "TH",
             "UK": "GB", "USA": "US", "Japan": "JP", "Bangladesh": "BD", "Vietnam": "VN",
             "Germany": "DE", "Spain": "ES"}

#: Fixed blends that appear in the export (``MRS_Tester.m``, ``w_em``). Kept as reference
#: rows, flagged; blends belong to ``aggregation``.
BLENDS = {"EMCN": "EMCN"}


class ReferenceError(ValueError):
    """The file is not the shape the reference loader expects."""


@dataclass(frozen=True)
class SignalRow:
    segment: str
    economy: str
    matlab_name: str
    is_blend: bool
    month_index: int
    date: str
    probs: tuple[float, ...]


def month_end(first: str, k: int) -> str:
    """Month end of the k-th month (1-based) counted from ``first`` (``YYYY-MM``)."""
    y, m = int(first[:4]), int(first[5:7])
    idx = y * 12 + (m - 1) + (k - 1)
    y, m = divmod(idx, 12)
    m += 1
    return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def parse_signal(payload: dict[str, Any], first_month: str) -> tuple[list[SignalRow], int]:
    """Every row of a ``signal`` export, and the month count. Fails on anything unexpected."""
    if set(payload) != set(SEGMENTS):
        raise ReferenceError(f"expected segments {sorted(SEGMENTS)}, got {sorted(payload)}")
    lengths = {len(v) for v in payload.values()}
    if len(lengths) != 1:
        raise ReferenceError(f"segments have different month counts: {sorted(lengths)}")
    months = lengths.pop()
    rows: list[SignalRow] = []
    for matlab_segment, series in payload.items():
        for k, month in enumerate(series, start=1):
            for name, values in month.items():
                if name in ECONOMIES:
                    code, blend = ECONOMIES[name], False
                elif name in BLENDS:
                    code, blend = BLENDS[name], True
                else:
                    raise ReferenceError(f"unknown economy {name!r} in {matlab_segment} month {k}")
                if len(values) != N_STATES or any(not math.isfinite(float(v)) for v in values):
                    raise ReferenceError(f"{matlab_segment}/{name} month {k}: need {N_STATES} finite values")
                rows.append(SignalRow(segment=SEGMENTS[matlab_segment], economy=code,
                                      matlab_name=name, is_blend=blend, month_index=k,
                                      date=month_end(first_month, k),
                                      probs=tuple(float(v) for v in values)))
    return rows, months


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(folder: Path) -> dict[str, Any]:
    """``manifest.json`` beside the frozen file: provenance the file itself does not carry."""
    path = folder / "manifest.json"
    if not path.is_file():
        raise ReferenceError(f"no manifest.json in {folder}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_folder(folder: Path) -> Iterator[tuple[dict[str, Any], list[SignalRow], int]]:
    manifest = read_manifest(folder)
    path = folder / manifest["file_name"]
    digest = sha256(path)
    if digest != manifest["sha256"]:
        raise ReferenceError(f"{path} has sha256 {digest}, manifest says {manifest['sha256']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows, months = parse_signal(payload, manifest["first_month"])
    if months != manifest["months"]:
        raise ReferenceError(f"{path} has {months} months, manifest says {manifest['months']}")
    yield {**manifest, "byte_size": path.stat().st_size}, rows, months
