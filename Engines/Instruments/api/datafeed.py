"""The datafeed read surface: `/series`, `/panel`, `/coverage`, `/snapshots`.

The contract on the datafeed engine page, served from the shared schema. Engines read
through here; only ``store/etl/datafeed.py`` writes.

**A panel never invents a value.** Every cell carries a flag, and there are three, not two:

    observed   measured in that period
    stitched   real, but from a different underlying series joined onto this one
    carried    forward-filled because the period had no observation
    (absent)   the series does not cover that period at all

The fourth is the one a two-state flag gets wrong. Three of the nineteen annual series are
genuinely shorter than the window, and "this did not exist yet" is a different statement
from "this was flat" -- the manual is explicit that truncation is handled by matching only
where the series exists and never by back-filling. So a missing cell comes back as ``null``
with flag ``absent``, and carrying is opt-in rather than the default.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_conn
from store import db

router = APIRouter(prefix="/v1/datafeed", tags=["datafeed"])

#: How far a value may be carried forward, per frequency. Beyond this the cell is absent
#: rather than carried: a number repeated for years is not evidence, and the further it is
#: carried the more confidently wrong it looks.
MAX_CARRY = {"A": 1, "M": 3, "D": 5}


def _feed(conn: db.Connection) -> str:
    return conn.config.datafeed_schema


@router.get("/series")
def list_series(
    category: str | None = Query(None),
    country: str | None = Query(None),
    period: str | None = Query(None, description="A, M or D"),
    stitched: bool | None = Query(None),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The registry. Every series the feed serves, with its metadata."""
    clauses, params = [], []
    for column, value in (("category", category), ("country", country),
                          ("period", period)):
        if value:
            clauses.append(f"{column} = %s")
            params.append(value)
    if stitched is not None:
        clauses.append("is_stitched = %s")
        params.append(stitched)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM {_feed(conn)}.series_definition {where} ORDER BY series_id",
        tuple(params),
    ).fetchall()
    return {"count": len(rows), "series": [dict(r) for r in rows]}


@router.get("/series/{series_id}")
def get_series(series_id: str, conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """One series definition, its segments if stitched, and its values."""
    feed = _feed(conn)
    row = conn.execute(
        f"SELECT * FROM {feed}.series_definition WHERE series_id = %s", (series_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no series {series_id!r}")
    observations = conn.execute(
        f"SELECT period, value, flag, segment FROM {feed}.observation "
        f"WHERE series_id = %s ORDER BY period", (series_id,)
    ).fetchall()
    segments = conn.execute(
        f"SELECT * FROM {feed}.series_segment WHERE series_id = %s "
        f"ORDER BY segment_index", (series_id,)
    ).fetchall()
    return {
        "definition": dict(row),
        "segments": [
            {**dict(s), "rejected_candidates": db.loads(s["rejected_candidates"])}
            for s in segments
        ],
        "observations": [dict(o) for o in observations],
    }


@router.get("/panel")
def panel(
    series: list[str] = Query(..., description="Repeatable."),
    start: str | None = Query(None),
    end: str | None = Query(None),
    carry: bool = Query(False, description="Forward-fill gaps, within the frequency limit."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """An aligned panel, with a flag on every cell.

    Alignment is on the union of periods actually present, so the panel never invents a
    row either. ``carry`` is off by default: a consumer that wants forward-filling has to
    ask for it, and gets told which cells it received.
    """
    feed = _feed(conn)
    definitions = conn.execute(
        f"SELECT * FROM {feed}.series_definition WHERE series_id = ANY(%s)",
        (list(series),),
    ).fetchall()
    found = {d["series_id"]: dict(d) for d in definitions}
    missing = [s for s in series if s not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"unknown series: {missing}")

    frequencies = {d["period"] for d in found.values()}
    if len(frequencies) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"mixed frequencies {sorted(frequencies)}. A panel aligns one frequency; "
                f"combining an annual and a monthly series is a modelling decision and "
                f"belongs to the consumer, not to the feed."
            ),
        )
    frequency = frequencies.pop()

    data: dict[str, dict[str, float]] = {}
    for series_id in series:
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if start:
            clauses.append("period >= %s")
            params.append(start)
        if end:
            clauses.append("period <= %s")
            params.append(end)
        rows = conn.execute(
            f"SELECT period, value, flag FROM {feed}.observation "
            f"WHERE {' AND '.join(clauses)}", tuple(params)
        ).fetchall()
        data[series_id] = {r["period"]: (r["value"], r["flag"]) for r in rows}

    periods = sorted({p for d in data.values() for p in d})
    limit = MAX_CARRY.get(frequency, 0)

    cells: list[dict[str, Any]] = []
    counts = {"observed": 0, "stitched": 0, "carried": 0, "absent": 0}
    for series_id in series:
        own = data[series_id]
        last_value, distance = None, 0
        for period in periods:
            if period in own:
                value, flag = own[period]
                last_value, distance = value, 0
            elif carry and last_value is not None and distance < limit:
                value, flag = last_value, "carried"
                distance += 1
            else:
                value, flag = None, "absent"
                distance += 1
            counts[flag] = counts.get(flag, 0) + 1
            cells.append({"series_id": series_id, "period": period,
                          "value": value, "flag": flag})

    return {
        "frequency": frequency,
        "periods": periods,
        "series": [found[s] for s in series],
        "cells": cells,
        "flag_counts": counts,
        "carry": {"enabled": carry, "max_periods": limit if carry else 0},
        "note": (
            "absent means the series does not cover that period. It is not zero and it is "
            "not the previous value; a consumer that treats it as either is inventing data."
        ),
    }


@router.get("/coverage")
def coverage(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Missingness by series. The gate before any model run."""
    feed = _feed(conn)
    rows = conn.execute(
        f"SELECT series_id, name, category, country, period, origin_kind, quality_grade, "
        f"       is_stitched, first_period, last_period, observation_count "
        f"FROM {feed}.series_definition ORDER BY category, series_id"
    ).fetchall()

    by_category: dict[str, dict[str, int]] = {}
    by_origin: dict[str, int] = {}
    by_grade: dict[str, int] = {}
    for r in rows:
        bucket = by_category.setdefault(r["category"], {"series": 0, "observations": 0})
        bucket["series"] += 1
        bucket["observations"] += r["observation_count"]
        by_origin[r["origin_kind"]] = by_origin.get(r["origin_kind"], 0) + 1
        by_grade[r["quality_grade"]] = by_grade.get(r["quality_grade"], 0) + 1

    gaps = conn.execute(
        f"SELECT series_id, COUNT(*) AS n FROM {feed}.observation "
        f"WHERE flag = 'stitched' GROUP BY series_id ORDER BY n DESC"
    ).fetchall()

    return {
        "series": len(rows),
        "by_category": by_category,
        "by_origin": by_origin,
        "by_quality_grade": by_grade,
        "stitched_observations": [dict(g) for g in gaps],
        "detail": [dict(r) for r in rows],
    }


@router.get("/snapshots")
def snapshots(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Available snapshots, newest first. A snapshot is immutable once written."""
    feed = _feed(conn)
    rows = conn.execute(
        f"SELECT * FROM {feed}.snapshot ORDER BY created_at DESC"
    ).fetchall()
    return {"count": len(rows), "snapshots": [dict(r) for r in rows]}


@router.get("/snapshots/{snapshot_id}")
def snapshot(snapshot_id: str, conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """One snapshot's manifest: coverage per series and the checksum that pins it."""
    feed = _feed(conn)
    row = conn.execute(
        f"SELECT * FROM {feed}.snapshot WHERE snapshot_id = %s", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no snapshot {snapshot_id!r}")
    members = conn.execute(
        f"SELECT * FROM {feed}.snapshot_series WHERE snapshot_id = %s ORDER BY series_id",
        (snapshot_id,),
    ).fetchall()
    return {"manifest": dict(row), "series": [dict(m) for m in members]}
