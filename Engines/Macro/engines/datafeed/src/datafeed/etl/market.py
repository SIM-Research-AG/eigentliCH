"""The market layer (DF-18): unit corrections, public market series and monthly fills.

Built on top of the filled snapshot, as its child, in three steps and in this order:

1. **correct**: primary cells whose ticker-sheet scale factor is wrong are multiplied by a
   stated factor (the implied volatility of six economies is in percent where the registry
   says decimal, Japan's is a hundred times too small). The definition's magnitude and
   description say so, and the manifest records every cell count.
2. **series**: series with no usable Bloomberg equivalent, taken from a public provider as
   their primary source (Cboe SKEW for the discontinued Credit Suisse Fear Barometer, the
   BIS nominal broad effective exchange rate for the JPM series that was never pulled).
   They get their own series ids; nothing already in the registry changes meaning.
3. **fill**: a public monthly value goes into a *missing* primary cell only, and only if the
   primary and public series agree on the months both cover: the median ratio is the scale,
   and every overlap month must lie within the tolerance of it. Fitted after the
   corrections, so a rescaled series is compared in its corrected unit.

Every step, applied or refused, is a ``MarketRecord`` on the manifest. Fetching is the only
step that needs the network; ``--offline`` uses the store, seeded from the frozen responses
in ``golden/`` when it is empty.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Mapping, Optional

from ..contracts import CellIn, MarketRecord, SeriesDefinition, SeriesIn, SnapshotIn
from ..engine import axis, checksum, panel_of
from ..settings import MarketSource, Settings
from .. import store as st

MarketKey = tuple[str, str]                        # provider, code
Stored = Mapping[MarketKey, tuple[str, dict[str, float]]]

_FIELD = {"cboe": "close (last of month)", "bis": "OBS_VALUE (monthly)"}
_PERIOD = {"cboe": "daily", "bis": "monthly"}


def fetch_id(provider: str, code: str, response_sha256: str) -> str:
    blob = f"{provider}|{code}|{response_sha256}".encode("utf-8")
    return "MKT-" + hashlib.sha256(blob).hexdigest()[:16]


def needed(settings: Settings) -> list[MarketKey]:
    return sorted({(m.provider, m.code_for(c)) for m in settings.market.sources for c in m.countries})


def ensure(conn, settings: Settings, clients: Mapping[str, object], *, refresh: bool) -> list[str]:
    """Fetch every market series the configuration names and store it."""
    log = []
    for provider, code in needed(settings):
        if not refresh and st.latest_market(conn, provider=provider, code=code):
            continue
        try:
            r = clients[provider].monthly(code)
        except Exception as exc:  # noqa: BLE001 - a failed fetch leaves the gap, never the run
            log.append(f"{provider}:{code}: fetch failed ({exc})")
            continue
        fid = fetch_id(provider, code, r.sha256)
        new = st.put_market_fetch(conn, fetch_id=fid, provider=provider, code=code, url=r.url,
                                  fetched_at=st.utc_now(), response_sha256=r.sha256, values=r.values)
        log.append(f"{provider}:{code}: {len(r.values)} months {'stored' if new else 'unchanged'}")
    return log


def stored(conn, settings: Settings) -> dict[MarketKey, tuple[str, dict[str, float]]]:
    out = {}
    for provider, code in needed(settings):
        hit = st.latest_market(conn, provider=provider, code=code)
        if hit:
            out[(provider, code)] = hit
    return out


def load_fixture(conn, path: Path) -> int:
    rows = json.loads(path.read_text(encoding="utf-8"))["fetches"]
    return sum(st.put_market_fetch(conn, fetch_id=r["fetch_id"], provider=r["provider"], code=r["code"],
                                   url=r["url"], fetched_at=r["fetched_at"],
                                   response_sha256=r["response_sha256"], values=r["values"])
               for r in rows)


def freeze_fixture(conn, path: Path, settings: Settings) -> int:
    fetches = []
    for (provider, code), (fid, values) in sorted(stored(conn, settings).items()):
        meta = next(f for f in st.market_fetches(conn) if f["fetch_id"] == fid)
        fetches.append({"fetch_id": fid, "provider": provider, "code": code, "url": meta["url"],
                        "fetched_at": meta["fetched_at"], "response_sha256": meta["response_sha256"],
                        "values": values})
    path.write_text(json.dumps({"_note": "Frozen market responses (DF-18), for offline builds and tests.",
                                "fetches": fetches}, indent=1) + "\n", encoding="utf-8")
    return len(fetches)


# ---------------------------------------------------------------------------
# The plan: pure, given the parent snapshot, the registry and the stored responses
# ---------------------------------------------------------------------------

Cells = dict[str, tuple[float, str, str]]          # date -> (value, flag, source)


def plan(parent: SnapshotIn, settings: Settings, registry: Mapping[str, Mapping[str, str]],
         responses: Stored) -> tuple[Optional[SnapshotIn], tuple[MarketRecord, ...]]:
    """The market snapshot (None if no step applied) and a record per step.

    ``registry`` maps series id to its registry row (category, unit, period).
    """
    dates = set(axis(parent.first_date, parent.last_date))
    defs: dict[tuple[str, str], SeriesDefinition] = {
        (s.definition.country, s.definition.series_id): s.definition for s in parent.series}
    work: dict[tuple[str, str], Cells] = {
        (s.definition.country, s.definition.series_id): {c.date: (c.value, c.flag, c.source) for c in s.cells}
        for s in parent.series}
    order = [(s.definition.country, s.definition.series_id) for s in parent.series]
    records: list[MarketRecord] = []

    # 1. corrections ---------------------------------------------------------------
    for c in settings.market.corrections:
        for country in c.countries:
            key = (country, c.series)
            cells = work.get(key)
            if not cells:
                records.append(MarketRecord(action="correct", country=country, series_id=c.series,
                                            source=parent.primary_source, factor=c.factor, accepted=False,
                                            reason="no primary cells to correct", note=c.reason))
                continue
            work[key] = {d: (v * c.factor, f, src) for d, (v, f, src) in cells.items()}
            d0 = defs[key]
            defs[key] = d0.model_copy(update={
                "magnitude": d0.magnitude * c.factor,
                "description": f"{d0.description} (rescaled x{c.factor:g} by datafeed, DF-18: {c.reason})"})
            records.append(MarketRecord(action="correct", country=country, series_id=c.series,
                                        source=parent.primary_source, factor=c.factor, accepted=True,
                                        reason=c.reason, cells_written=len(cells),
                                        first_date=min(cells), last_date=max(cells)))

    # 2. public series, then 3. fills ------------------------------------------------
    for m in [m for m in settings.market.sources if not m.fill] + [m for m in settings.market.sources if m.fill]:
        for country in m.countries:
            code = m.code_for(country)
            source = f"{m.provider}:{code}"
            hit = responses.get((m.provider, code))
            if hit is None:
                records.append(MarketRecord(action="fill" if m.fill else "series", country=country,
                                            series_id=m.series, source=source, accepted=False,
                                            reason="not fetched", note=m.note))
                continue
            fid, raw_values = hit
            values = {d: v * m.unit_scale for d, v in raw_values.items() if d in dates}
            if m.fill:
                records.append(_fill(m, country, source, fid, values, work, defs, settings))
            else:
                records.append(_series(m, country, source, code, fid, values, work, defs, order, registry))

    applied = [r for r in records if r.accepted and r.cells_written]
    if not applied:
        return None, tuple(records)
    tag = hashlib.sha256(json.dumps({"parent": checksum(panel_of(parent)),
                                     "records": [r.model_dump(mode="json") for r in records]},
                                    sort_keys=True).encode("utf-8")).hexdigest()[:8]
    series = tuple(
        SeriesIn(definition=defs[k], cells=tuple(CellIn(date=d, value=v, flag=f, source=src)
                                                 for d, (v, f, src) in sorted(work[k].items())))
        for k in order)
    child = SnapshotIn(
        snapshot_id=f"{parent.snapshot_id}.market-{tag}", parent_id=parent.snapshot_id,
        source=f"{parent.source} + market layer", primary_source=parent.primary_source, as_of=parent.as_of,
        first_date=parent.first_date, last_date=parent.last_date,
        note=(f"{parent.snapshot_id} with the market layer (DF-18): {len(applied)} of {len(records)} steps "
              "applied (unit corrections, public market series, monthly fills); the manifest lists every one."),
        series=series, fills=parent.fills, market=tuple(records))
    return child, tuple(records)


def _series(m: MarketSource, country: str, source: str, code: str, fid: str, values: dict[str, float],
            work, defs, order, registry) -> MarketRecord:
    key = (country, m.series)
    spec = registry.get(m.series)
    if spec is None:
        return MarketRecord(action="series", country=country, series_id=m.series, source=source,
                            accepted=False, reason="series not in the registry", fetch_ids=(fid,), note=m.note)
    if key in work:
        return MarketRecord(action="series", country=country, series_id=m.series, source=source,
                            accepted=False, reason="the parent already carries this series", fetch_ids=(fid,),
                            note=m.note)
    if not values:
        return MarketRecord(action="series", country=country, series_id=m.series, source=source,
                            accepted=False, reason="no values on the snapshot axis", fetch_ids=(fid,), note=m.note)
    work[key] = {d: (v, "observed", source) for d, v in values.items()}
    defs[key] = SeriesDefinition(
        series_id=m.series, country=country, category=spec["category"], unit=spec["unit"], currency="",
        magnitude=m.unit_scale, period=_PERIOD[m.provider], pull_code=code, field=_FIELD[m.provider],
        source=m.provider, description=m.note, indices=())
    order.append(key)
    return MarketRecord(action="series", country=country, series_id=m.series, source=source, accepted=True,
                        reason="primary source for this series", cells_written=len(values),
                        first_date=min(values), last_date=max(values), fetch_ids=(fid,), note=m.note)


def _fill(m: MarketSource, country: str, source: str, fid: str, values: dict[str, float],
          work, defs, settings: Settings) -> MarketRecord:
    key = (country, m.series)
    cfg = settings.market
    if m.identical:
        tol = m.tolerance if m.tolerance is not None else cfg.identical_tolerance
        min_overlap = cfg.identical_min_overlap
    else:
        tol = m.tolerance if m.tolerance is not None else cfg.fill_tolerance
        min_overlap = cfg.min_overlap_months
    base = dict(action="fill", country=country, series_id=m.series, source=source, tolerance=tol,
                fetch_ids=(fid,), note=m.note)
    if key not in work:
        return MarketRecord(**base, accepted=False, reason="no primary series to fill")
    primary = work[key]
    overlap = sorted(d for d in values if d in primary and values[d] != 0)
    if len(overlap) < min_overlap:
        return MarketRecord(**base, overlap_months=len(overlap), accepted=False,
                            reason=f"overlap {len(overlap)} months, below {min_overlap}")
    ratios = [primary[d][0] / values[d] for d in overlap]
    k = statistics.median(ratios)
    deviation = max(abs(r / k - 1.0) for r in ratios)
    common = dict(**base, overlap_months=len(overlap), scale=k, deviation=deviation)
    if m.identical:
        exact = sum(abs(r / k - 1.0) <= 0.01 for r in ratios)
        if abs(k - 1.0) > tol:
            return MarketRecord(**common, accepted=False,
                                reason=f"same index, but the median ratio is {k:.4f}: the units disagree")
        k = 1.0
        verdict = (f"same index: median ratio within {tol:.0%} of 1, {exact} of {len(overlap)} overlap "
                   f"months within 1%, worst {deviation:.1%}")
    elif deviation > tol:
        return MarketRecord(**common, accepted=False,
                            reason=f"fit fails: worst month {deviation:.1%} from the median ratio")
    else:
        verdict = f"fit holds: worst month {deviation:.1%} from the median ratio"
    missing = sorted(d for d in values if d not in primary)
    for d in missing:
        primary[d] = (values[d] * k, "observed", source)
    if missing:
        d0 = defs[key]
        defs[key] = d0.model_copy(update={"description": f"{d0.description} (gaps filled from {source}, DF-18)"})
    return MarketRecord(**common, accepted=True, reason=verdict, cells_written=len(missing), first_date=missing[0] if missing else None,
                        last_date=missing[-1] if missing else None)
