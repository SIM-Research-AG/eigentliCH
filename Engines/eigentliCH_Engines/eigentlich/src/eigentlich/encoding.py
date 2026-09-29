"""Text that was UTF-8 but was read as a single-byte code page, found and reversed (owner decision 29.09.2026,
EIG-46).

The pattern: each byte of a UTF-8 sequence shown as one character of CP437 or CP850 (a Windows console) or
CP1252: ``é`` (C3 A9) became ``├⌐`` (CP437), ``├®`` (CP850) or ``Ã©`` (CP1252); ``ü`` became ``├╝``, ``ä``
``├ñ``. The reversal encodes the characters back to those bytes with the code page and decodes them as
UTF-8. A group is repaired only when it decodes, strictly, to exactly one non-ASCII character, so correct
text (``Müller``, ``Céline``, ``Zürich``) is never touched: a correct ``é`` is one byte in every one of
these code pages, which is not UTF-8.

``scan`` lists every hit in the migrated text fields; ``fix`` corrects them by the rule of each table:

* ``client.display_name``, ``thread.subject``: a direct update by the owning role (both columns are free to
  change under ``guard_update``);
* plan tables (``household_member.label``, ``position.label`` and ``description``, ``goal.name``,
  ``client_fact.stated_value``): through ``store.plan_change`` under one decision per client, "encoding
  correction, owner 29.09.2026" (C-09); a fact is superseded by the corrected fact;
* ``decision`` (append-only): a correcting decision (``corrects_id``) with the corrected text;
* ``answer``: superseded by the corrected answer;
* ``thread_message`` and ``submission`` are append-only with no correction path: listed, not changed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

CODECS = ("cp437", "cp850", "cp1252")
_RUN = re.compile(r"[^\x00-\x7f]{2,}")

DECISION_QUESTION = "encoding correction, owner 29.09.2026"
REF = "owner 29.09.2026 (EIG-46)"


def _plausible(ch: str) -> bool:
    """A character the store's texts use: Latin-1 and Latin Extended-A letters, dashes, quotes, the euro.
    Two code pages can both turn a group into valid UTF-8 (``Ã©`` read back as CP850 is ``Ǹ``); only one of
    them gives a letter of these ranges."""
    o = ord(ch)
    return 0xA0 <= o <= 0x17F or 0x2010 <= o <= 0x2027 or o == 0x20AC


def _repair_run(run: str) -> str:
    out, i = [], 0
    while i < len(run):
        for k in (4, 3, 2):
            seg = run[i:i + k]
            if len(seg) < k:
                continue
            fixed = None
            for codec in CODECS:
                try:
                    decoded = seg.encode(codec).decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
                if len(decoded) == 1 and _plausible(decoded):
                    fixed = decoded
                    break
            if fixed is not None:
                out.append(fixed)
                i += k
                break
        else:
            out.append(run[i])
            i += 1
    return "".join(out)


def repair(text: str) -> str:
    """``text`` with every mis-decoded UTF-8 sequence reversed; unchanged when there is none."""
    return _RUN.sub(lambda m: _repair_run(m.group(0)), text)


def misdecoded(text: Any) -> bool:
    return isinstance(text, str) and repair(text) != text


def _strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")


def repair_json(value: Any) -> Any:
    if isinstance(value, str):
        return repair(value)
    if isinstance(value, dict):
        return {k: repair_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [repair_json(v) for v in value]
    return value


#: (table, text columns, JSON columns, how a hit is corrected). The migrated text fields of the store.
FIELDS: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...] = (
    ("client", ("display_name",), (), "direct update"),
    ("household_member", ("label",), (), "plan change"),
    ("position", ("label", "description"), (), "plan change"),
    ("goal", ("name",), (), "plan change"),
    ("client_fact", (), ("stated_value",), "plan change (superseding fact)"),
    ("decision", ("question", "choice", "reasoning"), ("options_considered",), "correcting decision"),
    ("answer", (), ("value",), "superseding answer"),
    ("thread", ("subject",), (), "direct update"),
    ("thread_message", ("body",), (), "append-only: listed, not changed"),
    ("submission", (), ("payload",), "append-only: listed, not changed"),
)

#: Only the rows that still count: current facts and answers, and decisions nobody has corrected.
_CURRENT = {"client_fact": "superseded_on IS NULL", "answer": "superseded_at IS NULL",
            "decision": "NOT EXISTS (SELECT 1 FROM decision c WHERE c.corrects_id = decision.id)"}


def scan(conn) -> list[dict[str, Any]]:
    """Every hit: table, row id, column, JSON path, the text and its repair, and how it would be corrected."""
    hits: list[dict[str, Any]] = []
    for table, texts, jsons, how in FIELDS:
        where = f" WHERE {_CURRENT[table]}" if table in _CURRENT else ""
        for row in conn.execute(f"SELECT * FROM {table}{where} ORDER BY id").fetchall():
            for col in texts + jsons:
                for path, text in _strings(row[col]):
                    if misdecoded(text):
                        hits.append({"table": table, "id": row["id"], "column": col, "path": path or None,
                                     "text": text, "repaired": repair(text), "how": how})
    return hits


def fix(conn, *, today: Optional[date] = None) -> dict[str, Any]:
    """Correct every hit, in one transaction, and return what changed and what could not change."""
    from . import store
    from .store import Decision

    today = today or date.today()
    changed: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []
    with conn.transaction():
        hits = scan(conn)
        by_row: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for h in hits:
            by_row.setdefault((h["table"], h["id"]), []).append(h)

        plan: dict[str, list[tuple[str, dict[str, Any]]]] = {}       # client -> [(table, row)]
        for (table, row_id), row_hits in by_row.items():
            row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,)).fetchone()
            if table in ("client", "thread"):
                values = {h["column"]: repair(row[h["column"]]) for h in row_hits}
                store._update(conn, table, row_id, values)
                changed.extend(row_hits)
            elif table in ("household_member", "position", "goal", "client_fact"):
                client = row.get("client_id")
                if table == "household_member" and client is None:
                    other = conn.execute("SELECT client_id FROM household_member WHERE household_id = %s "
                                         "AND client_id IS NOT NULL ORDER BY id LIMIT 1", (row["household_id"],)).fetchone()
                    client = other["client_id"] if other else None
                if client is None:
                    left.extend({**h, "why": "no client to name in the decision"} for h in row_hits)
                    continue
                plan.setdefault(client, []).append((table, row))
                changed.extend(row_hits)
            elif table == "decision":
                if row["client_id"] is None:
                    left.extend({**h, "why": "a decision without a client (erased) takes no correction"}
                                for h in row_hits)
                    continue
                store._insert(conn, "decision", {
                    "client_id": row["client_id"], "author": "system", "author_ref": REF,
                    "question": repair(row["question"]), "choice": repair(row["choice"]),
                    "reasoning": repair(row["reasoning"]) if row["reasoning"] else None,
                    "options_considered": repair_json(row["options_considered"]), "corrects_id": row["id"],
                    "curator_session_id": row["curator_session_id"]})
                changed.extend(row_hits)
            elif table == "answer":
                store.put_answer(conn, client_id=row["client_id"], questionnaire_key=row["questionnaire_key"],
                                 content_version=row["content_version"], question_key=row["question_key"],
                                 value=repair_json(row["value"]), answered_by_kind="migration",
                                 answered_by_ref=f"encoding correction of answer {row['id']}")
                changed.extend(row_hits)
            else:
                left.extend({**h, "why": f"{table} is append-only"} for h in row_hits)

        for client, rows in plan.items():
            # The corrected text only: the decision must not carry the garbled form again.
            choice = "Korrigiert: " + "; ".join(f"{t} {repair(_label(r))!r}" for t, r in rows)
            with store.plan_change(conn, decision=Decision(
                    client_id=client, author="system", author_ref=REF, question=DECISION_QUESTION,
                    choice=choice[:2000],
                    reasoning="UTF-8 text read as a code page (CP437/CP850/CP1252) during an earlier import; "
                              "reversed. Nothing else changes.")) as ch:
                for table, row in rows:
                    if table == "client_fact":
                        ch.state_fact(client_id=row["client_id"], stated_key=row["stated_key"],
                                      stated_value=repair_json(row["stated_value"]), stated_on=max(today, row["stated_on"]),
                                      stated_by=row["stated_by"], data_class=row["data_class"])
                    else:
                        cols = {"household_member": ("label",), "position": ("label", "description"),
                                "goal": ("name",)}[table]
                        ch.update(table, row["id"], **{c: repair(row[c]) for c in cols if misdecoded(row[c])})
    return {"changed": changed, "left": left, "remaining": scan(conn)}


def _label(row: dict[str, Any]) -> str:
    for col in ("label", "name", "display_name"):
        if isinstance(row.get(col), str):
            return row[col]
    return str(row.get("stated_value"))
