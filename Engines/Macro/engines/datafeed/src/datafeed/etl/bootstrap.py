"""Build the store: ``python -m datafeed bootstrap [options]``.

1. Create the schema and seed the calibrations, and the registry (``country``, ``series``)
   from ``seed/registry.yaml`` where rows are missing. The database wins on differences.
2. Import the raw Bloomberg snapshot: from ``M_TS.mat`` and the ticker sheets, or with
   ``--frozen`` from the frozen copy in ``golden/`` (no MATLAB folder needed).
3. Make sure every public series the fill candidates need is in the store: fetched from
   the internet, or with ``--offline`` seeded from the frozen responses in ``golden/``.
4. Fit every candidate and write the filled snapshot, a child of the raw one.
5. The market layer (DF-18): unit corrections, public market series (Cboe, BIS) and monthly
   fills, written as a child of the filled snapshot.

Idempotent: rerunning against unchanged inputs changes nothing. Exit codes: 0 done,
2 a source is missing, 3 the store refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import store as st
from ..contracts import CellIn, Panel, PanelRequest, SeriesDefinition, SeriesIn, Snapshot, SnapshotIn
from ..engine import cell_sources, checksum
from ..service import Conflict, InvalidRequest, Service
from ..settings import ROOT, Settings, load
from . import market, public
from .seed import load_seed

GOLDEN = ROOT / "golden"
FROZEN_RAW = GOLDEN / "snapshot_2026-01-05"          # manifest.json, panel.json, definitions.json
FROZEN_PUBLIC = GOLDEN / "public_2026-09-27.json"
FROZEN_MARKET = GOLDEN / "market_2026-09-27.json"


def read_frozen(folder: Path) -> SnapshotIn:
    """The frozen raw snapshot, back in ingest form. Checked against its own manifest."""
    manifest = Snapshot.model_validate_json((folder / "manifest.json").read_text(encoding="utf-8"))
    panel = Panel.model_validate_json((folder / "panel.json").read_text(encoding="utf-8"))
    if checksum(panel) != manifest.checksum:
        raise ValueError(f"{folder}/panel.json does not match its manifest checksum")
    defs = {(d.country, d.series_id): d for d in (SeriesDefinition.model_validate(x) for x in
            json.loads((folder / "definitions.json").read_text(encoding="utf-8")))}
    series = []
    for s in panel.series:
        sources = cell_sources(panel, s)
        cells = tuple(CellIn(date=d, value=v, flag=f, source=src)
                      for d, v, f, src in zip(panel.dates, s.values, s.flags, sources) if v is not None)
        series.append(SeriesIn(definition=defs[(s.country, s.series_id)], cells=cells))
    return SnapshotIn(snapshot_id=manifest.snapshot_id, parent_id=manifest.parent_id, source=manifest.source,
                      primary_source=manifest.primary_source, as_of=manifest.as_of,
                      first_date=manifest.first_date, last_date=manifest.last_date, note=manifest.note,
                      series=tuple(series), fills=manifest.fills, market=manifest.market)


def freeze(service: Service, snapshot_id: str, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    manifest = service.snapshot(snapshot_id)
    (folder / "manifest.json").write_text(manifest.model_dump_json(indent=1) + "\n", encoding="utf-8")
    (folder / "panel.json").write_text(
        service.panel(PanelRequest(snapshot_id=snapshot_id)).model_dump_json() + "\n", encoding="utf-8")
    (folder / "definitions.json").write_text(json.dumps(
        [d.model_dump(mode="json") for d in service.series(snapshot_id)], indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m datafeed bootstrap")
    parser.add_argument("--create-database", action="store_true")
    parser.add_argument("--frozen", action="store_true", help="raw snapshot from golden/, not M_TS.mat")
    parser.add_argument("--offline", action="store_true", help="no network: use stored or frozen public data")
    parser.add_argument("--refresh", action="store_true", help="fetch every public series again")
    parser.add_argument("--freeze-raw", action="store_true", help="write golden/.../snapshot_in.json")
    parser.add_argument("--freeze-public", action="store_true", help="write golden/public_*.json")
    parser.add_argument("--freeze-market", action="store_true", help="write golden/market_*.json")
    args = parser.parse_args(argv)
    settings = settings or load()
    store = st.Store(settings.database)
    print(f"store: {settings.database.redacted_url()}")

    try:
        if args.create_database:
            print("database created" if store.create_database() else "database exists")
        service = Service(settings, store)
        service.startup()
    except Exception as exc:  # noqa: BLE001
        print(f"store unavailable: {exc}", file=sys.stderr)
        return 3

    # -- registry ------------------------------------------------------------------
    added, differ = service.seed_registry(*load_seed())
    print(f"registry: {added} rows seeded" + (f", {len(differ)} kept as the database has them" if differ else ""))
    for line in differ:
        print("  " + line)
    problems = service.check_fills()
    if problems:
        print("config.yaml fills do not match the registry:", *problems, sep="\n  ", file=sys.stderr)
        return 2
    countries, series = service.countries(), service.series_specs()

    # -- raw snapshot ------------------------------------------------------------
    if args.frozen:
        if not (FROZEN_RAW / "manifest.json").is_file():
            print(f"no frozen snapshot in {FROZEN_RAW}", file=sys.stderr)
            return 2
        raw = read_frozen(FROZEN_RAW)
        files, conversions = [], json.loads((FROZEN_RAW / "zero_rule.json").read_text(encoding="utf-8"))["conversions"]
    else:
        from .matlab import MatlabImportError, read
        try:
            raw, files, conversions = read(settings, countries, series)
        except MatlabImportError as exc:
            print(f"import failed: {exc}", file=sys.stderr)
            return 2

    try:
        with store.session() as conn:
            for f in files:
                st.put_source_file(conn, name=f.name, sha256=f.sha256, byte_size=f.byte_size, origin=str(f.path))
        manifest, created = service.ingest(raw)
        print(f"{'wrote' if created else 'unchanged'} {manifest.snapshot_id}: {manifest.cells_present} cells, "
              f"checksum {manifest.checksum[:12]}")
        if service.put_conversions(raw.snapshot_id, conversions):
            print(f"recorded the import counts of {len(conversions)} series")
        if args.freeze_raw:
            freeze(service, raw.snapshot_id, FROZEN_RAW)
            if not args.frozen:
                (FROZEN_RAW / "zero_rule.json").write_text(json.dumps(
                    {"_note": "What MATLAB's zeros became, per country/series (etl/matlab.py).",
                     "conversions": conversions}, indent=1) + "\n", encoding="utf-8")
            print(f"froze {FROZEN_RAW.relative_to(ROOT)}")

        # -- public data ----------------------------------------------------------
        with store.session() as conn:
            if args.offline:
                seeded = public.load_fixture(conn, FROZEN_PUBLIC) if FROZEN_PUBLIC.is_file() else 0
                print(f"offline: {seeded} frozen public responses seeded")
            else:
                client, clients = public_clients()
                try:
                    iso3 = {c.code: c.iso3 for c in countries}
                    for line in public.ensure(conn, settings, clients, iso3, refresh=args.refresh):
                        print("  " + line)
                finally:
                    client.close()
            if args.freeze_public:
                print(f"froze {public.freeze_fixture(conn, FROZEN_PUBLIC, settings)} public responses")
            available = public.stored_public(conn, settings)

        filled, records = public.plan(raw, settings, service.calibration(), available)
        for r in records:
            verdict = f"filled {list(r.years_filled)}" if r.accepted and r.years_filled else r.reason
            print(f"  {r.country} {r.series_id:36s} {r.source:30s} {verdict}")
        if filled is not None:
            manifest, created = service.ingest(filled)
            print(f"{'wrote' if created else 'unchanged'} {manifest.snapshot_id}: {manifest.cells_present} cells")

        # -- market layer (DF-18) ---------------------------------------------------
        if settings.market.sources or settings.market.corrections:
            with store.session() as conn:
                if args.offline:
                    seeded = market.load_fixture(conn, FROZEN_MARKET) if FROZEN_MARKET.is_file() else 0
                    print(f"offline: {seeded} frozen market responses seeded")
                else:
                    client, clients = market_clients()
                    try:
                        for line in market.ensure(conn, settings, clients, refresh=args.refresh):
                            print("  " + line)
                    finally:
                        client.close()
                if args.freeze_market:
                    print(f"froze {market.freeze_fixture(conn, FROZEN_MARKET, settings)} market responses")
                responses = market.stored(conn, settings)
            registry = {s.series_id: {"category": s.category, "unit": s.unit, "period": s.period}
                        for s in series}
            child, steps = market.plan(filled or raw, settings, registry, responses)
            for r in steps:
                verdict = f"{r.cells_written} cells" if r.accepted else r.reason
                print(f"  {r.action:7s} {r.country} {r.series_id:30s} {r.source:22s} {verdict}")
            if child is not None:
                manifest, created = service.ingest(child)
                print(f"{'wrote' if created else 'unchanged'} {manifest.snapshot_id}: {manifest.cells_present} cells")
    except (Conflict, InvalidRequest, st.StoreError) as exc:
        print(f"store refused: {exc}", file=sys.stderr)
        return 3
    return 0


def public_clients():
    from ..clients import public_clients as make
    return make()


def market_clients():
    from ..clients import market_clients as make
    return make()
