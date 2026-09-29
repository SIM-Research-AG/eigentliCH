"""Write SCHEMA.md: the narrative contract (dev/SCHEMA.head.md) followed by the catalogue of the real schema
(columns, constraints, indexes, triggers, views), so the listing cannot drift from what init-db creates.
Reads the configured schema; changes nothing in the database.

    ..\\.venv\\Scripts\\python dev\\schema_catalogue.py            # rewrite SCHEMA.md
    ..\\.venv\\Scripts\\python dev\\schema_catalogue.py --stdout   # print the catalogue only
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from eigentlich.settings import load
from eigentlich.store import TABLES, VIEWS


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cfg = load().database
    s = cfg.schema
    out = io.StringIO()
    with psycopg.connect(cfg.conninfo(), row_factory=dict_row) as conn:
        for t in TABLES:
            out.write(f"#### `{t}`\n\n")
            out.write(conn.execute("SELECT obj_description(%s::regclass) AS d", (f"{s}.{t}",)).fetchone()["d"] + "\n\n")
            out.write("| column | type | null | default |\n|---|---|---|---|\n")
            for c in conn.execute(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull, "
                    "pg_get_expr(d.adbin, d.adrelid) AS def, a.attidentity FROM pg_attribute a "
                    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                    "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
                    (f"{s}.{t}",)):
                default = "identity" if c["attidentity"] else (c["def"] or "")
                out.write(f"| {c['attname']} | {c['type']} | {'' if c['attnotnull'] else 'yes'} | "
                          f"{default.replace('|', '/')} |\n")
            out.write("\nConstraints:\n\n")
            for c in conn.execute("SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                                  "WHERE conrelid = %s::regclass AND contype <> 'n' ORDER BY contype, conname", (f"{s}.{t}",)):
                out.write(f"- `{c['conname']}`: `{c['d']}`\n")
            idx = conn.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s "
                               "AND indexname NOT IN (SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass) "
                               "ORDER BY indexname", (s, t, f"{s}.{t}")).fetchall()
            if idx:
                out.write("\nIndexes:\n\n")
                for i in idx:
                    out.write(f"- `{i['indexname']}`: `{i['indexdef'].replace(s + '.', '')}`\n")
            trg = conn.execute("SELECT tgname, pg_get_triggerdef(oid) AS d FROM pg_trigger WHERE tgrelid = %s::regclass "
                               "AND NOT tgisinternal ORDER BY tgname", (f"{s}.{t}",)).fetchall()
            if trg:
                out.write("\nTriggers:\n\n")
                for g in trg:
                    out.write(f"- `{g['d'].replace(s + '.', '')}`\n")
            out.write("\n")
        for v in VIEWS:
            out.write(f"#### view `{v}`\n\n")
            out.write(conn.execute("SELECT obj_description(%s::regclass) AS d", (f"{s}.{v}",)).fetchone()["d"] + "\n\n")
            cols = conn.execute("SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 "
                                "ORDER BY attnum", (f"{s}.{v}",)).fetchall()
            out.write("Columns: " + ", ".join(f"`{c['attname']}`" for c in cols) + "\n\n")
    if "--stdout" in sys.argv:
        sys.stdout.write(out.getvalue())
        return 0
    head = (ROOT / "dev" / "SCHEMA.head.md").read_text(encoding="utf-8")
    (ROOT / "SCHEMA.md").write_text(head + out.getvalue().rstrip() + "\n", encoding="utf-8")
    print(f"wrote {ROOT / 'SCHEMA.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
