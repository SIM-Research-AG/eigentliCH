"""Fill gaps from public sources: fetch, store, fit, apply.

For every fill candidate in ``config.yaml`` the importer fetches the public series (World
Bank or IMF), keeps the raw response in the store, fits it against the primary Bloomberg
series on the years both cover, and applies it to missing December cells only if the fit
holds. The fit is always made against the *raw* snapshot, so one fill can never lend
credibility to another. The outcome of every candidate, accepted or not, goes on the
filled snapshot's manifest.

Fetching is the only step that needs the network. ``--offline`` uses what the store holds,
seeded from the frozen responses in ``golden/`` when the store is empty, which is how the
tests run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Optional

from ..calibration import calibration_hash
from ..contracts import Calibration, CellIn, FillRecord, SeriesIn, SnapshotIn
from ..engine import Cell, apply_annual, axis, checksum, december_values, fit_level, fit_rate, panel_of
from ..settings import FillSpec, Settings
from .. import store as st

FX_CODE = "PA.NUS.FCRF"          # official exchange rate, LCU per USD, period average

Key = tuple[str, str, str]      # provider, code, country
Public = Mapping[Key, tuple[str, dict[int, float]]]


def fetch_id(provider: str, code: str, country: str, response_sha256: str) -> str:
    blob = f"{provider}|{code}|{country}|{response_sha256}".encode("utf-8")
    return "PUB-" + hashlib.sha256(blob).hexdigest()[:16]


def needed(settings: Settings) -> list[Key]:
    keys: list[Key] = []
    for f in settings.fills:
        keys.append((f.provider, f.code, f.country))
        if f.anchor_code:
            keys.append((f.provider, f.anchor_code, f.country))
        if f.fx:
            keys.append(("worldbank", FX_CODE, f.country))
    return sorted(set(keys))


def ensure(conn, settings: Settings, clients: Mapping[str, object], iso3: Mapping[str, str], *,
           refresh: bool) -> list[str]:
    """Fetch every public series the fills need and store it. ``iso3`` maps country code to
    ISO3 (from the registry). Returns one line per fetch."""
    log = []
    for provider, code, country in needed(settings):
        if not refresh and st.latest_public(conn, provider=provider, code=code, country=country):
            continue
        try:
            r = clients[provider].annual(iso3[country], code)
        except Exception as exc:  # noqa: BLE001 - a failed fetch leaves the gap, never the run
            log.append(f"{provider}:{code} {country}: fetch failed ({exc})")
            continue
        fid = fetch_id(provider, code, country, r.sha256)
        new = st.put_public_fetch(conn, fetch_id=fid, provider=provider, code=code, country=country,
                                  url=r.url, fetched_at=st.utc_now(), response_sha256=r.sha256,
                                  values=r.values)
        log.append(f"{provider}:{code} {country}: {len(r.values)} years {'stored' if new else 'unchanged'}")
    return log


def load_fixture(conn, path: Path) -> int:
    """Seed the store with frozen public responses."""
    rows = json.loads(path.read_text(encoding="utf-8"))["fetches"]
    n = 0
    for r in rows:
        n += st.put_public_fetch(conn, fetch_id=r["fetch_id"], provider=r["provider"], code=r["code"],
                                 country=r["country"], url=r["url"], fetched_at=r["fetched_at"],
                                 response_sha256=r["response_sha256"],
                                 values={int(y): v for y, v in r["values"].items()})
    return n


def freeze_fixture(conn, path: Path, settings: Settings) -> int:
    """Write the latest stored response of every needed series to ``path``."""
    out = []
    for provider, code, country in needed(settings):
        latest = st.latest_public(conn, provider=provider, code=code, country=country)
        if latest is None:
            continue
        meta = next(m for m in st.public_fetches(conn) if m["fetch_id"] == latest[0])
        out.append({**meta, "values": {str(y): v for y, v in sorted(latest[1].items())}})
    path.write_text(json.dumps({"_note": "Frozen public responses used by the offline bootstrap "
                                         "and the tests. Refresh with `bootstrap --refresh "
                                         "--freeze-public`.", "fetches": out}, indent=1) + "\n",
                    encoding="utf-8")
    return len(out)


def stored_public(conn, settings: Settings) -> dict[Key, tuple[str, dict[int, float]]]:
    out = {}
    for key in needed(settings):
        latest = st.latest_public(conn, provider=key[0], code=key[1], country=key[2])
        if latest is not None:
            out[key] = latest
    return out


# ---------------------------------------------------------------------------
# Planning the fills (pure given its inputs)
# ---------------------------------------------------------------------------

def _candidate(public: Public, provider: str, code: str, country: str, fx: bool
               ) -> tuple[Optional[dict[int, float]], list[str]]:
    got = public.get((provider, code, country))
    if got is None:
        return None, []
    ids = [got[0]]
    values = dict(got[1])
    if fx:
        rate = public.get(("worldbank", FX_CODE, country))
        if rate is None:
            return None, ids
        ids.append(rate[0])
        values = {y: v * rate[1][y] for y, v in values.items() if y in rate[1]}
    return values, ids


def plan(raw: SnapshotIn, settings: Settings, calibration: Calibration,
         public: Public) -> tuple[Optional[SnapshotIn], tuple[FillRecord, ...]]:
    """The filled snapshot (None if nothing was accepted) and a record per candidate."""
    dates = axis(raw.first_date, raw.last_date)
    raw_cells: dict[tuple[str, str], dict[str, Cell]] = {
        (s.definition.country, s.definition.series_id): {c.date: (c.value, c.flag, c.source) for c in s.cells}
        for s in raw.series}
    work = {k: dict(v) for k, v in raw_cells.items()}
    records = []
    for spec in settings.fills:
        records.append(_one(spec, dates, raw_cells, work, calibration, public, raw.primary_source))

    accepted = [r for r in records if r.accepted and r.years_filled]
    if not accepted:
        return None, tuple(records)
    raw_digest = checksum(panel_of(raw))
    tag = hashlib.sha256(json.dumps({"raw": raw_digest,
                                     "records": [r.model_dump(mode="json") for r in records],
                                     "calibration": calibration_hash(calibration)},
                                    sort_keys=True).encode("utf-8")).hexdigest()[:8]
    series = tuple(
        SeriesIn(definition=s.definition, cells=tuple(
            CellIn(date=d, value=v, flag=f, source=src)
            for d, (v, f, src) in sorted(work[(s.definition.country, s.definition.series_id)].items())))
        for s in raw.series)
    filled = SnapshotIn(
        snapshot_id=f"{raw.snapshot_id}.public-{tag}", parent_id=raw.snapshot_id,
        source=f"{raw.source} + public fills", primary_source=raw.primary_source, as_of=raw.as_of,
        first_date=raw.first_date, last_date=raw.last_date,
        note=(f"{raw.snapshot_id} with gaps filled from public sources where the fit holds "
              f"(calibration {calibration.version}). {len(accepted)} of {len(records)} "
              "candidates applied; the manifest lists every one."),
        series=series, fills=tuple(records))
    return filled, tuple(records)


def _share(spec: FillSpec, dates, raw_cells, work, cal: Calibration, candidate, ids, common,
           primary: str) -> FillRecord:
    """value = public share of the anchor x the primary anchor (e.g. consumption % GDP x GDP).

    Nothing to fit: the result is in the anchor's unit by construction. It is checked instead:
    every share must lie within the calibration's plausibility bounds. With ``replace`` the
    target's primary cells are removed first, because the primary series is known to be in
    another unit (the plausibility finding that motivates the entry).
    """
    target = (spec.country, spec.series)
    shares = {y: v * spec.unit_scale for y, v in candidate.items()}
    lo, hi = cal.consumption_share_bounds
    anchor = december_values(dates, raw_cells.get((spec.country, spec.anchor), {}))
    years = sorted(y for y in shares if y in anchor)
    outside = [y for y in years if not lo <= shares[y] <= hi]

    def record(accepted, reason, applied=None, replaced=0):
        return FillRecord(**common, overlap_years=len(years), scale=None, offset=None, deviation=None,
                          accepted=accepted, reason=reason,
                          years_filled=applied.years if applied else (),
                          cells_observed=applied.observed if applied else 0,
                          cells_carried=applied.carried if applied else 0,
                          fetch_ids=tuple(ids), cells_replaced=replaced)

    if len(years) < cal.min_overlap_years:
        return record(False, f"{len(years)} years with both the share and the anchor, {cal.min_overlap_years} needed")
    if outside:
        return record(False, f"share outside {lo}-{hi} in {outside[:3]}")
    stored = work.get(target, {})
    replaced = 0
    if spec.replace:
        kept = {d: c for d, c in stored.items() if c[2] != primary}
        replaced = len(stored) - len(kept)
        stored = kept
    applied = apply_annual(dates, stored, {y: shares[y] * anchor[y] for y in years}, spec.source,
                           cal.annual_carry_months)
    work[target] = applied.cells
    return record(True, "share of the anchor, within bounds" + (f"; replaced {replaced} primary cells" if replaced else ""),
                  applied, replaced)


def _one(spec: FillSpec, dates, raw_cells, work, cal: Calibration, public: Public, primary: str) -> FillRecord:
    target = (spec.country, spec.series)
    tolerance = spec.tolerance if spec.tolerance is not None else (
        cal.level_tolerance if spec.mode == "level" else cal.rate_tolerance)
    common = dict(country=spec.country, series_id=spec.series, source=spec.source, mode=spec.mode,
                  anchor=spec.anchor or spec.series, fx=spec.fx, tolerance=tolerance, note=spec.note)

    def reject(reason: str, fit=None, ids=()) -> FillRecord:
        return FillRecord(**common, overlap_years=fit.overlap if fit else 0,
                          scale=fit.scale if fit else None, offset=fit.offset if fit else None,
                          deviation=fit.deviation if fit else None, accepted=False, reason=reason,
                          years_filled=(), cells_observed=0, cells_carried=0, fetch_ids=tuple(ids))

    candidate, ids = _candidate(public, spec.provider, spec.code, spec.country, spec.fx)
    if candidate is None:
        return reject(f"no public data for {spec.source}", ids=ids)

    if spec.mode == "share":
        return _share(spec, dates, raw_cells, work, cal, candidate, ids, common, primary)

    if spec.mode == "level":
        anchor_series = spec.anchor or spec.series
        if spec.anchor_code:
            anchor_values, anchor_ids = _candidate(public, spec.provider, spec.anchor_code, spec.country, spec.fx)
            ids = ids + anchor_ids
            if anchor_values is None:
                return reject(f"no public data for the anchor {spec.provider}:{spec.anchor_code}", ids=ids)
        else:
            anchor_values = candidate
        primary = december_values(dates, raw_cells.get((spec.country, anchor_series), {}))
        fit = fit_level(primary, anchor_values, cal.min_overlap_years, tolerance)
        fill = {y: v * fit.scale for y, v in candidate.items()} if fit.accepted else {}
    else:
        scaled = {y: v * spec.unit_scale for y, v in candidate.items()}
        primary = december_values(dates, raw_cells.get(target, {}))
        fit = fit_rate(primary, scaled, cal.min_overlap_years, tolerance)
        fill = {y: v + fit.offset for y, v in scaled.items()} if fit.accepted else {}

    if not fit.accepted:
        return reject(fit.reason, fit, ids)
    applied = apply_annual(dates, work.get(target, {}), fill, spec.source, cal.annual_carry_months)
    work[target] = applied.cells
    return FillRecord(**common, overlap_years=fit.overlap, scale=fit.scale, offset=fit.offset,
                      deviation=fit.deviation, accepted=True,
                      reason="fits" if applied.years else "fits, but the source has no value for any gap",
                      years_filled=applied.years, cells_observed=applied.observed,
                      cells_carried=applied.carried, fetch_ids=tuple(ids))
