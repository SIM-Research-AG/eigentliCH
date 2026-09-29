"""End-to-end ingestion pipeline for one ticker.

Steps 1..6 of spec 4.2, executed in order and each recorded in provenance:
    1. resolve pull_code from the DataSeries register
    2. fetch raw series from the chosen SeriesSource
    3. apply magnitude to LEVEL
    4. apply FX (labelled passthrough if same currency)
    5. resample to monthly (or hold native for low-frequency blocks)
    6. compute period returns

The result is a HarmonisedSeries with attached Provenance and a
vintage-stamped identity that a downstream Parquet write can persist.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from fmre.ingest.harmonise import apply_fx, apply_magnitude, resample_to_monthly
from fmre.ingest.returns import ReturnMethod, period_returns
from fmre.ingest.sources import SeriesSource
from fmre.registers.data_series import Currency, DataSeries, Period, Unit


@dataclass(frozen=True, slots=True)
class Provenance:
    ticker: str
    pull_code: str
    source: str
    magnitude_label: str
    unit: str
    native_period: str
    from_currency: str
    to_currency: str
    resample: str
    return_method: str
    transforms: tuple[str, ...]
    data_vintage: str            # YYYY-MM stamp
    ingested_at: str             # ISO-8601 UTC
    idempotency_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HarmonisedSeries:
    ticker: str
    levels: pd.Series             # DatetimeIndex, LEVEL-unit
    returns: pd.Series | None     # None if unit is not a price series
    currency: str
    period: str
    provenance: Provenance

    def n_obs_returns(self) -> int:
        return 0 if self.returns is None else int(self.returns.shape[0])


def _idempotency_key(*parts: str) -> str:
    joined = "|".join(parts)
    return "id-" + hashlib.sha256(joined.encode()).hexdigest()[:16]


def ingest_ticker(
    ticker: str,
    source: SeriesSource,
    register: dict[str, DataSeries],
    to_currency: str = "LCY",
    fx: pd.Series | float | None = None,
    return_method: ReturnMethod = "simple",
    data_vintage: str | None = None,
) -> HarmonisedSeries:
    """Ingest one ticker end-to-end, returning a HarmonisedSeries.

    ``fx`` is optional; if the DataSeries currency equals ``to_currency`` (or
    both are 'LCY'), FX is passthrough. Constant-FX (float) is the invariance
    test path.
    """
    if ticker not in register:
        raise KeyError(f"ingest_ticker: ticker {ticker!r} not in DataSeries register")
    ds = register[ticker]

    raw = source.fetch(ds.pull_code)
    transforms: list[str] = [f"fetch:{source.name}"]

    scaled = apply_magnitude(raw, ds.magnitude)
    transforms.append(f"magnitude:{ds.magnitude.value}")

    converted = apply_fx(scaled, from_currency=ds.crncy.value, to_currency=to_currency, fx_series=fx)
    transforms.append(f"fx:{converted.attrs.get('fx_handling', 'passthrough')}")

    monthly = resample_to_monthly(converted, ds.period)
    transforms.append(f"resample:{monthly.attrs.get('resample', 'unknown')}")

    if ds.unit == Unit.PX:
        rets = period_returns(monthly, method=return_method)
        transforms.append(f"returns:{return_method}")
    else:
        rets = None
        transforms.append(f"returns:skipped_unit={ds.unit.value}")

    vintage = data_vintage or f"{date.today():%Y-%m}"
    key = _idempotency_key(ticker, ds.pull_code, source.name, ds.magnitude.value, ds.crncy.value, to_currency, ds.period.value, vintage)
    prov = Provenance(
        ticker=ticker,
        pull_code=ds.pull_code,
        source=source.name,
        magnitude_label=ds.magnitude.value,
        unit=ds.unit.value,
        native_period=ds.period.value,
        from_currency=ds.crncy.value,
        to_currency=to_currency,
        resample=monthly.attrs.get("resample", "unknown"),
        return_method=return_method,
        transforms=tuple(transforms),
        data_vintage=vintage,
        ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        idempotency_key=key,
    )
    return HarmonisedSeries(
        ticker=ticker,
        levels=monthly,
        returns=rets,
        currency=to_currency,
        period=ds.period.value,
        provenance=prov,
    )


def write_parquet(harmonised: HarmonisedSeries, root: Path | str) -> Path:
    """Write one Parquet per ticker with provenance embedded as file metadata.

    Filename: ``<root>/<safe_ticker>.parquet``. Contents: date, level, and
    (if present) return, plus a JSON provenance blob in the file metadata.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    safe = harmonised.ticker.replace(" ", "_").replace("$", "_")
    path = root / f"{safe}.parquet"

    df = pd.DataFrame({"level": harmonised.levels})
    if harmonised.returns is not None:
        df = df.join(harmonised.returns.rename("return"), how="left")
    df.index.name = "date"
    table = pa.Table.from_pandas(df.reset_index())
    prov_json = json.dumps(harmonised.provenance.to_dict()).encode("utf-8")
    meta = {b"fmre_provenance": prov_json}
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})
    pq.write_table(table, path)
    return path


def read_parquet_provenance(path: Path | str) -> dict[str, Any]:
    """Read the provenance blob written by ``write_parquet``."""
    import pyarrow.parquet as pq

    md = pq.read_schema(path).metadata or {}
    blob = md.get(b"fmre_provenance")
    if blob is None:
        raise ValueError(f"read_parquet_provenance: {path} missing fmre_provenance metadata")
    return json.loads(blob.decode("utf-8"))
