"""Migrate the prototype's SQLite store into PostgreSQL, reconciled table by table.

The source is opened read-only (``mode=ro``) and its SHA-256 is taken before and after: the run fails if
the file changed. Every source table is classified, migrated or skipped with a reason; a table the
classification does not know fails the run, so a drifted source cannot be half-migrated.

**One transaction.** Every row goes in inside a single transaction, so the migrated decisions carry the
migration's transaction id and the C-09 trigger accepts the plan rows written under them, exactly as it
accepts a live plan change. No guard is stood down: there is no migration switch. Each plan row's
``decision_id`` is the latest decision (by ``created_at``, then id) the source links it to, which is the
decision that last changed it; the source links themselves are migrated in full. The transaction id is
recorded in ``migration_run``.

**Idempotent or refusing.** If the target already holds a migration of the same file (same SHA-256) and
every migrated id is still present, the run reports "already migrated" and writes nothing. Otherwise a
target holding any row in a table this writes is refused.

**Renames.** ``member`` becomes ``client`` in values as well as names (decision author, stated_by). The
curator's ``active`` flag is not carried: every source row has it set, and "in service" is
``revoked_at IS NULL`` (A161); a source row with ``active = 0`` and no revocation fails the run.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote

import psycopg
from psycopg.types.json import Jsonb

from . import store

EXPECTED_ALEMBIC_HEAD = "b81f4c2e9a37"
ONBOARDING_KEY = "questionnaire/onboarding"


class MigrationError(RuntimeError):
    """The run cannot proceed or did not reconcile. Nothing was written."""


class AlreadyMigrated(Exception):
    """The same source is already in the target, completely."""

    def __init__(self, report: dict[str, Any]):
        super().__init__("already migrated")
        self.report = report


#: Source tables not migrated, each with its reason.
SKIPPED: dict[str, str] = {
    "credentials": "sign-in removed (owner decision 28.09.2026): no passwords are carried",
    "sessions": "sign-in removed: login sessions are not carried",
    "access_grants": "curator access grants belonged to the sign-in model, which is removed",
    "action_items": "derived from the plan; the backend recomputes them",
    "vault_items": "the document vault is out of scope for this store",
    "decision_vault_items": "links to vault items; the vault is out of scope",
    "plan_versions": "numbered plan baselines (A111) are not in this store; engine artefacts carry the versions",
    "engine_runs": "prototype engine calls; engine_run records calls to the new engines",
    "assumption_sets": "published assumptions, not client data; engines own their calibrations",
    "capabilities": "learning ladder, out of scope",
    "capability_assertions": "learning ladder, out of scope",
    "learning_units": "learning ladder, out of scope",
    "gatherings": "community, out of scope",
    "attendances": "community, out of scope",
    "listings": "market place, out of scope",
    "disclosures": "market place, out of scope",
    "providers": "market place, out of scope",
    "member_offers": "market place, out of scope",
    "alembic_version": "the source's schema revision; recorded in migration_run.alembic_head",
}


def _ts(value: Any) -> Optional[datetime]:
    """SQLite stores the prototype's UTC instants as naive text; they are UTC (models/base.DateTime)."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise MigrationError(f"not a timestamp: {value!r}") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _date(value: Any) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MigrationError(f"not a date: {value!r}") from exc


def _json(value: Any) -> Any:
    """A SQLite JSON column: text holding JSON, or a bare number SQLite stored natively."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return json.loads(value)
    except ValueError as exc:
        raise MigrationError(f"not JSON: {str(value)[:40]!r}...") from exc


def _bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if value not in (0, 1):
        raise MigrationError(f"not a boolean: {value!r}")
    return bool(value)


def _member(value: str) -> str:
    return "client" if value == "member" else value


@dataclass(frozen=True)
class Table:
    source: str
    target: str
    key: tuple[str, ...]                     # the source key, for reconciliation
    order: str = "rowid"


#: Migrated tables, in the order they are written.
MIGRATED: tuple[Table, ...] = (
    Table("curators", "curator", ("id",)),
    Table("members", "client", ("id",)),
    Table("consents", "consent", ("id",)),
    Table("curator_sessions", "curator_session", ("id",)),
    Table("curator_session_events", "curator_session_event", ("id",)),
    Table("decisions", "decision", ("id",), order="created_at, id"),
    Table("households", "household", ("id",)),
    Table("household_members", "household_member", ("id",)),
    Table("positions", "position", ("id",)),
    Table("goals", "goal", ("id",)),
    Table("member_facts", "client_fact", ("id",)),
    Table("decision_positions", "decision_position", ("decision_id", "position_id")),
    Table("decision_goals", "decision_goal", ("decision_id", "goal_id")),
    Table("decision_households", "decision_household", ("decision_id", "household_id")),
    Table("decision_household_members", "decision_household_member", ("decision_id", "household_member_id")),
    Table("decision_facts", "decision_client_fact", ("decision_id", "member_fact_id")),
    Table("goal_funding", "goal_funding", ("goal_id", "position_id")),
    Table("goal_owners", "goal_owner", ("goal_id", "household_member_id")),
    Table("onboarding_answers", "answer", ("id",)),
    Table("submissions", "submission", ("id",)),
)

#: Target key columns where they differ from the source's.
TARGET_KEY = {"decision_client_fact": ("decision_id", "client_fact_id")}


def open_source(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"no SQLite file at {path}")
    conn = sqlite3.connect(f"file:{quote(path.resolve().as_posix())}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(src: sqlite3.Connection, table: Table) -> list[sqlite3.Row]:
    return src.execute(f'SELECT * FROM "{table.source}" ORDER BY {table.order}').fetchall()


def _latest_decision(src: sqlite3.Connection, link: str, column: str) -> dict[str, str]:
    """For each plan row, the latest decision the source links it to."""
    out: dict[str, str] = {}
    for row in src.execute(f'SELECT l.{column} AS rid, d.id AS did FROM "{link}" l JOIN decisions d '
                           f'ON d.id = l.decision_id ORDER BY d.created_at, d.id'):
        out[row["rid"]] = row["did"]
    return out


def _canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _insert(conn: psycopg.Connection, table: str, values: dict[str, Any]) -> None:
    cols = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 [Jsonb(v) if isinstance(v, (dict, list)) else v for v in values.values()])


def _insert_json(conn: psycopg.Connection, table: str, values: dict[str, Any], json_cols: Iterable[str]) -> None:
    js = set(json_cols)
    cols = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 [Jsonb(v) if c in js and v is not None else v for c, v in values.items()])


def _link_insert(conn: psycopg.Connection, table: str, a: str, b: str, row: sqlite3.Row, sa: str, sb: str) -> None:
    conn.execute(f"INSERT INTO {table} ({a}, {b}) VALUES (%s, %s) ON CONFLICT DO NOTHING", (row[sa], row[sb]))


def classify(src: sqlite3.Connection) -> list[str]:
    names = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                       "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    known = {t.source for t in MIGRATED} | set(SKIPPED)
    unknown = sorted(set(names) - known)
    if unknown:
        raise MigrationError(f"source tables neither migrated nor skipped with a reason: {unknown}")
    absent = sorted({t.source for t in MIGRATED} - set(names))
    if absent:
        raise MigrationError(f"source lacks tables this migration reads: {absent}")
    return names


def _target_count(conn: psycopg.Connection, table: Table, src_keys: set[tuple[Any, ...]]) -> int:
    cols = TARGET_KEY.get(table.target, table.key)
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table.target}").fetchall()
    present = {tuple(r[c] for c in cols) for r in rows}
    return len(src_keys & present)


def migrate(conn: psycopg.Connection, source: Path) -> dict[str, Any]:
    """Run the migration in one transaction; return the reconciliation. Raises on any mismatch."""
    before = sha256(source)
    src = open_source(source)
    try:
        names = classify(src)
        head = src.execute("SELECT version_num FROM alembic_version").fetchall()
        if [h[0] for h in head] != [EXPECTED_ALEMBIC_HEAD]:
            raise MigrationError(f"source alembic head is {[h[0] for h in head]}, expected {EXPECTED_ALEMBIC_HEAD}")
        fk = src.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise MigrationError(f"the source has {len(fk)} foreign key violations: {[tuple(r) for r in fk[:5]]}")

        source_keys = {t.source: {tuple(r[k] for k in t.key) for r in _rows(src, t)} for t in MIGRATED}

        prior = conn.execute("SELECT * FROM migration_run WHERE source_sha256 = %s ORDER BY ran_at DESC LIMIT 1",
                             (before,)).fetchone()
        if prior is not None:
            complete = all(_target_count(conn, t, source_keys[t.source]) == len(source_keys[t.source])
                           for t in MIGRATED)
            if complete:
                raise AlreadyMigrated(prior["reconciliation"])
            raise MigrationError("a migration of this file ran before and rows of it are gone from the target; "
                                 "refusing to write it again")
        occupied = {t.target: n for t in MIGRATED
                    for n in [conn.execute(f"SELECT count(*) AS n FROM {t.target}").fetchone()["n"]] if n}
        if occupied:
            raise MigrationError(f"the target is not empty: {occupied}; migration writes only into empty tables")

        onboarding = conn.execute("SELECT version, body ->> 'version' AS v FROM content_record WHERE key = %s "
                                  "ORDER BY version", (ONBOARDING_KEY,)).fetchall()
        if not onboarding:
            raise MigrationError(f"no {ONBOARDING_KEY} content: run `python -m eigentlich seed` first")

        notes: list[str] = []
        with conn.transaction():
            txid = conn.execute("SELECT txid_current() AS t").fetchone()["t"]
            _write(conn, src, onboarding, notes)
            reconciliation = _reconcile(conn, src, names, source_keys)
            conn.execute("INSERT INTO migration_run (source_path, source_sha256, alembic_head, reconciliation) "
                         "VALUES (%s, %s, %s, %s)", (str(source), before, EXPECTED_ALEMBIC_HEAD,
                                                     Jsonb({"tables": reconciliation, "notes": notes})))
    finally:
        src.close()
    after = sha256(source)
    if after != before:
        raise MigrationError("the source file changed during the run")
    return {"source": str(source), "sha256": before, "alembic_head": EXPECTED_ALEMBIC_HEAD, "txid": txid,
            "tables": reconciliation, "notes": notes}


def _write(conn: psycopg.Connection, src: sqlite3.Connection, onboarding: list[dict[str, Any]],
           notes: list[str]) -> None:
    rows = {t.source: _rows(src, t) for t in MIGRATED}

    for r in rows["curators"]:
        if not r["active"] and r["revoked_at"] is None:
            raise MigrationError(f"curator {r['id']} is inactive but not revoked; no rule says what that means")
        _insert(conn, "curator", {
            "id": r["id"], "display_name": r["display_name"], "email": r["email"], "role_label": r["role_label"],
            "fictional": _bool(r["fictional"]), "created_at": _ts(r["created_at"]), "created_by_kind": "migration",
            "revoked_at": _ts(r["revoked_at"]), "revoked_reason": r["revoked_reason"], "source_curator_id": r["id"],
            "data_class": r["data_class"]})

    for r in rows["members"]:
        _insert(conn, "client", {
            "id": r["id"], "display_name": r["display_name"], "locale": r["locale"],
            "age_at_registration": r["age_at_registration"], "stage_hint": r["stage_hint"],
            "onboarding_completed_at": _ts(r["onboarding_completed_at"]), "created_at": _ts(r["created_at"]),
            "created_by_kind": "migration", "source_member_id": r["id"], "data_class": r["data_class"]})

    for r in rows["consents"]:
        _insert(conn, "consent", {
            "id": r["id"], "client_id": r["member_id"], "purpose": r["purpose"],
            "document_version": r["document_version"], "granted_at": _ts(r["granted_at"]),
            "withdrawn_at": _ts(r["withdrawn_at"]), "notes": r["notes"], "created_at": _ts(r["created_at"]),
            "data_class": r["data_class"]})

    for r in rows["curator_sessions"]:
        _insert(conn, "curator_session", {
            "id": r["id"], "client_id": r["member_id"], "curator_id": r["curator_id"], "opened_from": r["opened_from"],
            "opened_at": _ts(r["opened_at"]), "liability_flag": _bool(r["liability_flag"]),
            "created_at": _ts(r["created_at"]), "data_class": r["data_class"]})

    for r in rows["curator_session_events"]:
        _insert_json(conn, "curator_session_event", {
            "id": r["id"], "session_id": r["session_id"], "kind": r["kind"], "at": _ts(r["at"]), "actor": r["actor"],
            "detail": _json(r["detail"]), "created_at": _ts(r["created_at"]), "data_class": r["data_class"]},
            ("detail",))

    written: set[str] = set()
    for r in rows["decisions"]:
        if r["corrects_id"] is not None and r["corrects_id"] not in written:
            raise MigrationError(f"decision {r['id']} corrects {r['corrects_id']}, which is not earlier")
        _insert_json(conn, "decision", {
            "id": r["id"], "client_id": r["member_id"], "author": _member(r["author"]), "author_ref": r["author_ref"],
            "question": r["question"], "options_considered": _json(r["options_considered"]), "choice": r["choice"],
            "reasoning": r["reasoning"], "curator_session_id": r["curator_session_id"], "corrects_id": r["corrects_id"],
            "origin": "migration", "created_at": _ts(r["created_at"]), "data_class": r["data_class"]},
            ("options_considered",))
        written.add(r["id"])

    latest = {
        "households": _latest_decision(src, "decision_households", "household_id"),
        "household_members": _latest_decision(src, "decision_household_members", "household_member_id"),
        "positions": _latest_decision(src, "decision_positions", "position_id"),
        "goals": _latest_decision(src, "decision_goals", "goal_id"),
        "member_facts": _latest_decision(src, "decision_facts", "member_fact_id"),
    }

    def decision_for(table: str, row_id: str) -> str:
        did = latest[table].get(row_id)
        if did is None:
            raise MigrationError(f"{table} {row_id} is covered by no decision; C-09 has nothing to name")
        return did

    # Households in succession order: a successor after the household it succeeds.
    pending = list(rows["households"])
    done: set[str] = set()
    while pending:
        progressed = False
        for r in list(pending):
            if r["succeeds_household_id"] is None or r["succeeds_household_id"] in done:
                _insert(conn, "household", {
                    "id": r["id"], "composition_as_of": _date(r["composition_as_of"]),
                    "stated_by": _member(r["stated_by"]), "closed_on": _date(r["closed_on"]),
                    "succeeds_household_id": r["succeeds_household_id"],
                    "decision_id": decision_for("households", r["id"]), "created_at": _ts(r["created_at"]),
                    "data_class": r["data_class"]})
                done.add(r["id"])
                pending.remove(r)
                progressed = True
        if not progressed:
            raise MigrationError(f"households succeed each other in a cycle: {[r['id'] for r in pending]}")

    for r in rows["household_members"]:
        _insert(conn, "household_member", {
            "id": r["id"], "household_id": r["household_id"], "client_id": r["member_id"], "label": r["label"],
            "kind": r["kind"], "joined_on": _date(r["joined_on"]), "left_on": _date(r["left_on"]),
            "decision_id": decision_for("household_members", r["id"]), "created_at": _ts(r["created_at"]),
            "data_class": r["data_class"]})

    for r in rows["positions"]:
        _insert_json(conn, "position", {
            "id": r["id"], "client_id": r["member_id"], "role": r["role"], "capital_type": r["capital_type"],
            "label": r["label"], "description": r["description"], "magnitude": r["magnitude"],
            "magnitude_unit": r["magnitude_unit"], "tags": _json(r["tags"]), "time_basis": r["time_basis"],
            "started_on": _date(r["started_on"]), "active": _bool(r["active"]), "liquidity": r["liquidity"],
            "stock_kind": r["stock_kind"], "decision_id": decision_for("positions", r["id"]),
            "created_at": _ts(r["created_at"]), "data_class": r["data_class"]}, ("tags",))

    for r in rows["goals"]:
        _insert(conn, "goal", {
            "id": r["id"], "client_id": r["member_id"], "name": r["name"], "target_amount": r["target_amount"],
            "target_date": _date(r["target_date"]), "safety": r["safety"], "liquidity_need": r["liquidity_need"],
            "volatility_tolerance": r["volatility_tolerance"], "horizon": r["horizon"],
            "flexibility": r["flexibility"], "template": r["template"], "frozen_at": _date(r["frozen_at"]),
            "occupancy": r["occupancy"], "decision_id": decision_for("goals", r["id"]),
            "created_at": _ts(r["created_at"]), "data_class": r["data_class"]})

    for r in rows["member_facts"]:
        _insert_json(conn, "client_fact", {
            "id": r["id"], "client_id": r["member_id"], "stated_key": r["stated_key"],
            "stated_value": _json(r["stated_value"]), "stated_on": _date(r["stated_on"]),
            "stated_by": _member(r["stated_by"]), "superseded_on": _date(r["superseded_on"]),
            "decision_id": decision_for("member_facts", r["id"]), "created_at": _ts(r["created_at"]),
            "data_class": r["data_class"]}, ("stated_value",))

    for r in rows["decision_positions"]:
        _link_insert(conn, "decision_position", "decision_id", "position_id", r, "decision_id", "position_id")
    for r in rows["decision_goals"]:
        _link_insert(conn, "decision_goal", "decision_id", "goal_id", r, "decision_id", "goal_id")
    for r in rows["decision_households"]:
        _link_insert(conn, "decision_household", "decision_id", "household_id", r, "decision_id", "household_id")
    for r in rows["decision_household_members"]:
        _link_insert(conn, "decision_household_member", "decision_id", "household_member_id", r,
                     "decision_id", "household_member_id")
    for r in rows["decision_facts"]:
        _link_insert(conn, "decision_client_fact", "decision_id", "client_fact_id", r, "decision_id", "member_fact_id")

    for r in rows["goal_funding"]:
        conn.execute("INSERT INTO goal_funding (goal_id, position_id, data_class) VALUES (%s, %s, "
                     "(SELECT data_class FROM goal WHERE id = %s))", (r["goal_id"], r["position_id"], r["goal_id"]))
    for r in rows["goal_owners"]:
        conn.execute("INSERT INTO goal_owner (goal_id, household_member_id, data_class) VALUES (%s, %s, "
                     "(SELECT data_class FROM goal WHERE id = %s))", (r["goal_id"], r["household_member_id"],
                                                                      r["goal_id"]))

    versions = {o["v"]: o["version"] for o in onboarding}
    raised = 0
    for r in rows["onboarding_answers"]:
        version = versions.get(r["question_set_version"])
        if version is None:
            raise MigrationError(f"onboarding answer {r['id']} names question set {r['question_set_version']!r}, "
                                 f"which no version of {ONBOARDING_KEY} carries (have {sorted(versions)})")
        value = _json(r["value"])
        if value is None:
            raise MigrationError(f"onboarding answer {r['id']} has no value")
        cls = conn.execute(
            "INSERT INTO answer (id, client_id, questionnaire_key, content_version, question_key, value, answered_at, "
            "answered_by_kind, answered_by_ref, created_at, data_class) VALUES (%s, %s, %s, %s, %s, %s, %s, "
            "'migration', %s, %s, %s) RETURNING data_class",
            (r["id"], r["member_id"], ONBOARDING_KEY, version, r["question_key"], Jsonb(value), _ts(r["answered_at"]),
             f"onboarding_answers:{r['id']}", _ts(r["created_at"]), r["data_class"])).fetchone()["data_class"]
        raised += cls > r["data_class"]
    if raised:
        notes.append(f"{raised} onboarding answers raised to the class their question declares "
                     f"(health: K3, per onboarding-questions.json fills.data_class)")

    bad_hash = 0
    for r in rows["submissions"]:
        payload = _json(r["payload"])
        if _canonical_hash(payload) != r["content_hash"]:
            bad_hash += 1
        _insert_json(conn, "submission", {
            "id": r["id"], "client_id": r["member_id"], "schema_version": r["schema_version"], "source": r["source"],
            "collected_on": r["collected_on"], "received_at": _ts(r["received_at"]), "payload": payload,
            "content_hash": r["content_hash"], "household_code": r["household_code"],
            "mapping_report": _json(r["mapping_report"]), "note": r["note"], "created_at": _ts(r["created_at"]),
            "data_class": r["data_class"]}, ("payload", "mapping_report"))
    if bad_hash:
        raise MigrationError(f"{bad_hash} submissions do not hash to their stored content_hash")
    # The payloads must come back from PostgreSQL hashing the same: jsonb is not allowed to have changed them.
    back = conn.execute("SELECT id, payload, content_hash FROM submission").fetchall()
    changed = [b["id"] for b in back if _canonical_hash(b["payload"]) != b["content_hash"]]
    if changed:
        raise MigrationError(f"{len(changed)} submission payloads changed in jsonb: {changed[:3]}")
    notes.append(f"{len(back)} submission payloads verified: each hashes to its stored content_hash after the "
                 f"round trip through jsonb")


def _reconcile(conn: psycopg.Connection, src: sqlite3.Connection, names: list[str],
               source_keys: dict[str, set[tuple[Any, ...]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mismatched: list[str] = []
    for t in MIGRATED:
        n_src = len(source_keys[t.source])
        n_dst = _target_count(conn, t, source_keys[t.source])
        total = conn.execute(f"SELECT count(*) AS n FROM {t.target}").fetchone()["n"]
        out.append({"source": t.source, "target": t.target, "source_count": n_src, "migrated": n_dst,
                    "target_total": total, "skipped": 0, "reason": None})
        if n_src != n_dst or total != n_dst:
            mismatched.append(f"{t.source}: source {n_src}, migrated {n_dst}, target holds {total}")
    for name in names:
        if name in SKIPPED:
            n = src.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            out.append({"source": name, "target": None, "source_count": n, "migrated": 0, "target_total": None,
                        "skipped": n, "reason": SKIPPED[name]})
    if mismatched:
        raise MigrationError("reconciliation failed: " + "; ".join(mismatched))
    return out


def format_reconciliation(report: dict[str, Any]) -> str:
    lines = [f"Migration of {report['source']}", f"sha256 {report['sha256']}, alembic head {report['alembic_head']}, "
             f"transaction {report.get('txid')}", ""]
    header = f"{'source table':<28} {'target':<26} {'source':>7} {'migrated':>9} {'skipped':>8}  reason"
    lines += [header, "-" * len(header)]
    for r in report["tables"]:
        lines.append(f"{r['source']:<28} {(r['target'] or '-'):<26} {r['source_count']:>7} {r['migrated']:>9} "
                     f"{r['skipped']:>8}  {r['reason'] or ''}")
    for note in report.get("notes", []):
        lines.append(f"note: {note}")
    return "\n".join(lines)
