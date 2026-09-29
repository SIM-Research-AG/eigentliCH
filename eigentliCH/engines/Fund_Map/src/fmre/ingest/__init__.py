"""Ingestion layer: sources, harmonisation, period returns, pipeline."""

from fmre.ingest.pipeline import HarmonisedSeries, Provenance, ingest_ticker, write_parquet
from fmre.ingest.sources import (
    CsvSource,
    SeriesSource,
    StateConditionalHint,
    SyntheticParams,
    SyntheticSource,
    seed_state_conditional_hints,
)

__all__ = [
    "HarmonisedSeries",
    "Provenance",
    "CsvSource",
    "SeriesSource",
    "SyntheticParams",
    "SyntheticSource",
    "StateConditionalHint",
    "seed_state_conditional_hints",
    "ingest_ticker",
    "write_parquet",
]
