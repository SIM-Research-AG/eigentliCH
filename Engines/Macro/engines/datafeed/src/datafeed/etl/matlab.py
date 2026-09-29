"""Import the Bloomberg pull that ``Web_Dataloader2.m`` saved as ``M_TS.mat``.

The only module in the system that knows MATLAB's row-position contract: sheet and column
per series (``series.matlab_sheet`` / ``matlab_column`` in the registry) and one ticker
workbook per country (``country.matlab_field``), where row n describes column n. Everything past this module addresses series by name.

``M_TS`` carries no dates and stores missing values as 0 (``D(isnan(D)) = 0`` in the
loader). Both are undone here, by rule, and the rule's counts go on the manifest:

* dates are reconstructed from the import settings (first month, month count);
* a series whose ticker is a placeholder (``placeholder_tickers``: the sheets' "blank
  holding space", which MATLAB pulled as USD spot = 1.0) is imported with no cells;
* NaN, leading zeros and trailing zeros are missing; interior zeros are kept only in the
  series marked ``zero_is_a_value`` (rates and balances), missing elsewhere.

Needs ``scipy`` (allowlisted) for the ``.mat`` file and ``openpyxl`` (development extra)
for the ticker sheets. Neither is imported by the running engine.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..contracts import CellIn, Country, SeriesDefinition, SeriesIn, SeriesSpec, SnapshotIn
from ..engine import axis, month_end
from ..settings import Settings


class MatlabImportError(RuntimeError):
    """The MATLAB sources are missing or not in the expected shape."""


@dataclass(frozen=True)
class SourceFile:
    name: str
    path: Path
    sha256: str
    byte_size: int


def sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def to_gaps(x: np.ndarray, zero_is_a_value: bool) -> tuple[list[Optional[float]], dict[str, int]]:
    """Undo MATLAB's NaN -> 0 where it can be undone."""
    x = x.astype(float)
    missing = ~np.isfinite(x)
    zero = (x == 0) & ~missing
    counts = {"nan": int(missing.sum()), "leading_zero": 0, "trailing_zero": 0, "interior_zero": 0}
    nonzero = np.flatnonzero((x != 0) & ~missing)
    if nonzero.size == 0:
        counts["leading_zero"] = int(zero.sum())
        missing |= zero
    else:
        lead, trail = nonzero[0], nonzero[-1]
        interior = zero.copy()
        interior[:lead] = False
        interior[trail + 1:] = False
        counts["leading_zero"] = int(zero[:lead].sum())
        counts["trailing_zero"] = int(zero[trail + 1:].sum())
        counts["interior_zero"] = int(interior.sum())
        missing |= zero & ~interior
        if not zero_is_a_value:
            missing |= interior
    return [None if missing[i] else float(x[i]) for i in range(len(x))], counts


def _tickers(settings: Settings, countries: list[Country], series: list[SeriesSpec]) -> dict[str, dict[str, tuple]]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise MatlabImportError("openpyxl is needed to read the ticker sheets: pip install -e .[dev]") from exc
    folder = settings.matlab.dir / settings.matlab.tickers
    out: dict[str, dict[str, tuple]] = {}
    for c in countries:
        path = folder / f"{c.matlab}.xlsx"
        if not path.is_file():
            raise MatlabImportError(f"ticker sheet {path} not found")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = {sheet: list(wb[sheet].iter_rows(values_only=True)) for sheet in {s.matlab_sheet for s in series}}
        out[c.code] = {s.series_id: rows[s.matlab_sheet][s.matlab_column - 1] for s in series}
        wb.close()
    return out


def read(settings: Settings, countries: list[Country], series: list[SeriesSpec]
         ) -> tuple[SnapshotIn, list[SourceFile], dict[str, dict[str, int]]]:
    """M_TS.mat + ticker sheets -> the raw snapshot, its source files and the zero-rule counts.

    ``countries`` and ``series`` are the registry: only countries with a MATLAB field and
    series with a MATLAB sheet and column are imported.
    """
    countries = [c for c in countries if c.matlab]
    series = [s for s in series if s.matlab_sheet and s.matlab_column]
    try:
        import scipy.io as sio
    except ImportError as exc:  # pragma: no cover
        raise MatlabImportError("scipy is needed to read M_TS.mat") from exc

    m = settings.matlab
    mat_path = m.dir / m.file
    if not mat_path.is_file():
        raise MatlabImportError(f"{mat_path} not found; set DATAFEED_MATLAB_DIR or import.matlab.dir")
    data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)["M_TS"]
    dates = axis(m.first_month, _last_month(m.first_month, m.months))
    tickers = _tickers(settings, countries, series)

    series_in, conversions = [], {}
    for c in countries:
        country = getattr(data, c.matlab)
        for spec in series:
            sheet, col = spec.matlab_sheet, spec.matlab_column
            block = np.asarray(getattr(country, sheet))
            if block.ndim == 1:              # a one-series sheet (Commodity) is saved as a vector
                block = block[:, None]
            if block.shape[0] != m.months:
                raise MatlabImportError(f"{c.matlab}.{sheet} has {block.shape[0]} rows, expected {m.months}")
            t = tickers[c.code][spec.series_id]
            placeholder = str(t[0]).strip() in m.placeholder_tickers
            values, counts = to_gaps(block[:, col - 1], spec.zero_is_a_value)
            if placeholder:
                counts["placeholder"] = sum(v is not None for v in values)
                values = [None] * len(values)
            conversions[f"{c.code}/{spec.series_id}"] = counts
            definition = SeriesDefinition(
                series_id=spec.series_id, country=c.code, category=spec.category, unit=spec.unit,
                currency=str(t[3] or ""), magnitude=float(t[2] or 1), period=spec.period,
                pull_code=str(t[0]), field=str(t[1]), source=settings.primary_source,
                description=str(t[5] or "").strip() + (" (placeholder ticker: no data)" if placeholder else ""),
                indices=spec.indices)
            cells = tuple(CellIn(date=d, value=v, flag="observed", source=settings.primary_source)
                          for d, v in zip(dates, values) if v is not None)
            series_in.append(SeriesIn(definition=definition, cells=cells))

    files = [SourceFile("M_TS.mat", mat_path, *sha256(mat_path))]
    for c in countries:
        p = m.dir / m.tickers / f"{c.matlab}.xlsx"
        files.append(SourceFile(f"Tickers/{c.matlab}.xlsx", p, *sha256(p)))

    snapshot = SnapshotIn(
        snapshot_id=m.snapshot_id, source=f"matlab:{m.file}", primary_source=settings.primary_source,
        as_of=m.as_of, first_date=dates[0], last_date=dates[-1],
        note=(f"Bloomberg pull by Web_Dataloader2.m, saved as M_TS.mat, {len(series)} series. Dates reconstructed "
              "from the loader's window; MATLAB's zeros turned back into gaps by rule. "
              f"M_TS.mat sha256 {files[0].sha256}."),
        series=tuple(series_in))
    return snapshot, files, conversions


def _last_month(first: str, months: int) -> str:
    k = int(first[:4]) * 12 + int(first[5:7]) - 1 + months - 1
    return month_end(k // 12, k % 12 + 1)
