"""``python -m eigentlich init-db | seed | migrate [--from PATH] | show | serve | align-content | revise-content |
fix-encoding | lbs-backfill | lbsim-backfill``.

``init-db``  create the tables, functions, triggers and views in the configured schema (idempotent).
``seed``     write content version 1 from the prototype's questionnaires, scoring maps, reference content
             and knowledge notes; print and save the seed report. Exit 1 on a conflict.
``migrate``  copy the prototype's SQLite data in one transaction; print the reconciliation. Exit 1 on any
             mismatch; exit 0 with "already migrated" when the same file is already in the target.
``show``     what the store holds: counts per table, content keys, bind check, migrations.
``serve``    the consumer web app on the host and port of ``config.yaml`` (``app:``, 8017 by default).
``align-content --curator ID|EMAIL``  save the questionnaires aligned to the scoring maps as new versions by
             that curator (EIG-44, EIG-45); nothing when already aligned. Prints the bind check.
``revise-content --curator ID|EMAIL``  save the intake with the partner section and without ``hours_learning``
             as a new version by that curator (EIG-53, EIG-58), and the onboarding with the nominal and real
             view's two questions (EIG-60, EIG-61), and the intake with lbsim's earning-power questions for the
             principal and the partner (EIG-65); nothing when already done.
``fix-encoding [--apply]``  list the migrated texts that are UTF-8 read as a code page and, with ``--apply``,
             correct them (EIG-46). Without ``--apply`` nothing is written.
``lbs-backfill [--limit N] [--dry-run]``  one lbs run for every client without a successful one (EIG-47).
             Refuses to start when lbs does not answer (exit 1, nothing written).
``lbsim-backfill [--limit N] [--dry-run]``  one lbsim run for every client whose newest sheet has no successful
             one (EIG-67). Refuses to start when lbsim does not answer (exit 1, nothing written).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .settings import ROOT, ConfigError, load


def _report_path(kind: str, schema: str) -> Path:
    path = ROOT / "dev" / "reports" / f"{kind}-{schema}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eigentlich")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sub.add_parser("seed")
    m = sub.add_parser("migrate")
    m.add_argument("--from", dest="source", type=Path, default=None, help="the prototype SQLite file")
    sub.add_parser("show")
    sub.add_parser("serve")
    a = sub.add_parser("align-content")
    a.add_argument("--curator", required=True, help="the saving curator's id or email")
    r = sub.add_parser("revise-content")
    r.add_argument("--curator", required=True, help="the saving curator's id or email")
    f = sub.add_parser("fix-encoding")
    f.add_argument("--apply", action="store_true", help="write the corrections (default: list only)")
    b = sub.add_parser("lbs-backfill")
    b.add_argument("--limit", type=int, default=None)
    b.add_argument("--dry-run", action="store_true", help="count the clients, run nothing")
    bs = sub.add_parser("lbsim-backfill")
    bs.add_argument("--limit", type=int, default=None)
    bs.add_argument("--dry-run", action="store_true", help="count the clients, run nothing")
    args = parser.parse_args(argv)

    if args.command in ("lbs-backfill", "lbsim-backfill"):
        return _backfill(args)

    if args.command == "serve":
        from .appsettings import load_app
        try:
            app_settings = load_app()
        except ConfigError as exc:
            print(f"configuration error: {exc}", file=sys.stderr)
            return 2
        import uvicorn
        print(f"eigentliCH app on http://{app_settings.host}:{app_settings.port}/  "
              f"store {app_settings.store.database.redacted_url()}")
        uvicorn.run("eigentlich.api:create_app", factory=True, host=app_settings.host, port=app_settings.port)
        return 0

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    from .store import Store, StoreError

    st = Store(settings.database)
    print(f"store: {settings.database.redacted_url()}")
    try:
        if args.command == "init-db":
            st.initialise()
            print(f"schema {settings.database.schema} ready")
            return 0

        if args.command == "seed":
            from .seed import SeedError, format_report, seed
            try:
                with st.session() as conn:
                    report = seed(conn, settings.prototype_root)
            except SeedError as exc:
                print(f"seed failed: {exc}", file=sys.stderr)
                return 3
            print(format_report(report))
            path = _report_path("seed-report", settings.database.schema)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print(f"report written to {path}")
            return 0 if report["ok"] else 1

        if args.command == "migrate":
            from .migrate import AlreadyMigrated, MigrationError, format_reconciliation, migrate
            source = args.source or settings.migrate_from
            try:
                with st.session() as conn:
                    report = migrate(conn, source)
            except AlreadyMigrated as done:
                print(f"already migrated: {source} is in {settings.database.schema} completely; nothing written")
                print(format_reconciliation({"source": str(source), "sha256": "(recorded)", "alembic_head": "(recorded)",
                                             "tables": done.report["tables"], "notes": done.report.get("notes", [])}))
                return 0
            except MigrationError as exc:
                print(f"migration failed, nothing written: {exc}", file=sys.stderr)
                return 1
            print(format_reconciliation(report))
            path = _report_path("migration-report", settings.database.schema)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print(f"report written to {path}")
            return 0

        if args.command in ("align-content", "revise-content"):
            from .alignment import align, revise, revise_basis, revise_earning
            with st.session() as conn:
                row = conn.execute("SELECT id FROM curator WHERE id = %s OR email = %s", (args.curator, args.curator)).fetchone()
                if row is None:
                    print(f"no curator {args.curator}", file=sys.stderr)
                    return 2
                if args.command == "align-content":
                    report = align(conn, curator_id=row["id"])
                else:
                    report = revise(conn, curator_id=row["id"])
                    basis = revise_basis(conn, curator_id=row["id"])
                    earning = revise_earning(conn, curator_id=row["id"])
                    report = {"saved": {**report["saved"], **basis["saved"]}, "binds": earning["binds"]}
                    # the intake is revised twice (the partner section, then earning power): report its last save
                    for key, r in earning["saved"].items():
                        if r["status"] == "saved" or report["saved"].get(key, {}).get("status") != "saved":
                            report["saved"][key] = r
                mismatches = conn.execute("SELECT scoring_key, question_key, option_value, status FROM scoring_bind_check "
                                          "WHERE status <> 'ok' ORDER BY scoring_key, bind_index").fetchall()
            for key, r in report["saved"].items():
                extra = f" (from {r['from_version']}; questions {', '.join(r['questions'])})" if r["status"] == "saved" else ""
                print(f"{key}: {r['status']} version {r['version']}{extra}")
            print("scoring binds: " + ", ".join(f"{k} {v}" for k, v in sorted(report["binds"].items())))
            for m in mismatches:
                print(f"  MISMATCH {m['scoring_key']} {m['question_key']} {m['option_value']!r}: {m['status']}")
            return 0 if not mismatches else 1

        if args.command == "fix-encoding":
            from . import encoding
            with st.session() as conn:
                if args.apply:
                    result = encoding.fix(conn)
                    hits, left, remaining = result["changed"], result["left"], result["remaining"]
                else:
                    hits, left, remaining = encoding.scan(conn), [], None
            for h in hits:
                where = h["column"] + (f" {h['path']}" if h["path"] else "")
                print(f"{'fixed' if args.apply else 'found'} {h['table']} {h['id']} {where}: {h['text']!r} -> "
                      f"{h['repaired']!r} ({h['how']})")
            for h in left:
                print(f"left {h['table']} {h['id']} {h['column']}: {h['text']!r} ({h['why']})")
            if remaining is not None:
                print(f"remaining after the fix: {len(remaining)}")
            return 0

        if args.command == "show":
            from .store import TABLES, content_keys, table_counts
            with st.session() as conn:
                counts = table_counts(conn)
                keys = content_keys(conn)
                binds = conn.execute("SELECT status, count(*) AS n FROM scoring_bind_check GROUP BY status "
                                     "ORDER BY status").fetchall()
                runs = conn.execute("SELECT source_path, source_sha256, alembic_head, txid, ran_at FROM migration_run "
                                    "ORDER BY ran_at").fetchall()
            print("tables:")
            for t in TABLES:
                print(f"  {t:<28} {counts[t]:>7}")
            by_kind: dict[str, int] = {}
            for k in keys:
                by_kind[k["kind"]] = by_kind.get(k["kind"], 0) + 1
            print("content keys: " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
            print("scoring binds: " + (", ".join(f"{b['status']} {b['n']}" for b in binds) or "none"))
            for r in runs:
                print(f"migration: {r['source_path']} sha256 {r['source_sha256'][:12]} head {r['alembic_head']} "
                      f"txid {r['txid']} at {r['ran_at']:%Y-%m-%d %H:%M}")
            return 0
    except StoreError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 2  # pragma: no cover


def _backfill(args) -> int:
    from .appsettings import load_app
    from .clients import ChatbotClient, EngineUnavailable, LbsClient, LbsimClient, ReportClient
    from .service import Service
    from .store import Store as _Store

    try:
        cfg = load_app()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    t = cfg.timeouts
    service = Service(cfg, _Store(cfg.store.database), LbsClient(cfg.lbs_url, t.lbs_s, t.connect_s),
                      ChatbotClient(cfg.chatbot_url, t.chatbot_s, t.connect_s),
                      ReportClient(cfg.report_url, t.report_s, t.connect_s), workers=1,
                      lbsim=LbsimClient(cfg.lbsim_url, t.lbsim_s, t.connect_s))
    sim = args.command == "lbsim-backfill"
    print(f"store: {cfg.store.database.redacted_url()}  " + (f"lbsim: {cfg.lbsim_url}" if sim else f"lbs: {cfg.lbs_url}"))
    try:
        run = service.lbsim_backfill if sim else service.lbs_backfill
        result = run(limit=args.limit, dry_run=args.dry_run, progress=print)
    except EngineUnavailable as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1
    finally:
        service.close()
    if result["dry_run"]:
        what = "newest sheet has no outlook yet" if sim else "have no balance sheet yet"
        print(f"{result['clients']} clients: {what}; nothing run (dry run)")
        return 0
    print(f"{result['clients']} clients: {len(result['succeeded'])} succeeded, {len(result['failed'])} failed")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
