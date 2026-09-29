"""Render one report per client from what the application answered, and collect what it could not do.

Reads `reports/new-clients.json` — the raw payloads `tools/run_new_clients.py` captured by calling the
member-facing routes as each member — and writes one HTML report per client plus an index, in the shape
of the reports already in `reports/`.

**This file interprets nothing and computes nothing.** Every sentence in every report is a sentence the
application produced, rendered where it was returned. Where the application returned nothing, the report
says so rather than filling the space; that is the whole reason the last two sections exist and it is
what makes the set usable as evidence.

**The issue collection is the second output and the more useful one.** While rendering, this notes every
place the system declined, returned nothing, or held an answer it could not use, and writes
`reports/new-clients-issues.json` for `tools/summarise_client_issues.py` to read. Nothing is judged here
either: an issue is a fact about a payload — "the Know found nothing", "this answer has no field" — and
the judgement of what matters belongs in the overview, where a person reads it.

Usage:

    python tools/render_client_reports.py
"""

from __future__ import annotations

import collections
import datetime
import html
import io
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "reports"
sys.path.insert(0, str(REPO / "backend"))

TODAY = datetime.date(2026, 9, 20)

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #F4F2EE; color: #17171B;
  font: 15px/1.6 "Inter", "Segoe UI", system-ui, -apple-system, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 48px 20px 96px; }
.lbl { font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: #6B6B72; font-weight: 600; }
h1 { font-size: 2rem; margin: 6px 0 4px; letter-spacing: -.02em; }
.sub { color: #6B6B72; margin: 0 0 32px; }
h2 { font-size: 1.05rem; margin: 44px 0 0; padding-bottom: 8px; border-bottom: 2px solid #17171B;
  display: flex; gap: 12px; align-items: baseline; }
h2 .n { font-size: 11px; color: #6B6B72; font-variant-numeric: tabular-nums; }
h3 { font-size: .95rem; margin: 22px 0 6px; color: #33333A; }
p { margin: 10px 0; }
.q { background: #FFF; border-left: 3px solid #17171B; padding: 14px 18px; margin: 14px 0; }
.a { background: #FFF; border: 1px solid #DEDBD4; padding: 14px 18px; margin: 14px 0; }
table { border-collapse: collapse; width: 100%; background: #FFF; margin-top: 12px; font-size: .9rem; }
th, td { text-align: left; padding: 8px 11px; border-bottom: 1px solid #E6E3DC; vertical-align: top; }
th { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: #6B6B72; background: #FAF9F6; }
code { font-size: .87em; background: #FAF9F6; padding: 1px 4px; }
.none { color: #8A5A2B; font-weight: 600; }
.ok { color: #1F6B4E; font-weight: 600; }
.muted { color: #6B6B72; }
.note { background: #FFF8EC; border: 1px solid #E8D9BC; padding: 12px 16px; margin: 14px 0; font-size: .92rem; }
ul { margin: 8px 0; padding-left: 20px; }
li { margin: 4px 0; }
"""


#: The two notices `services/know.py` emits when it does not answer, matched on their opening words so a
#: reworded notice fails loudly here rather than being silently counted as an answer.
NOTHING_RETRIEVED = "Dazu finde ich"
NO_SENTENCE_ANSWERS = "Zu Ihrer Frage gibt es Material"


def _know_outcome(answer: str, quotes: list) -> str:
    """What the Know actually did. Three outcomes, and the difference between the last two matters.

    `nothing_retrieved` means the corpus held nothing close enough to the question to be worth reading.
    `no_sentence_answers` means material came back and no sentence in it answered — the corpus has the
    subject and not the answer. They point at different work: the first at what is missing, the second
    at what is written badly or retrieved wrongly.
    """
    text = (answer or "").strip()
    if not text:
        return "nothing_retrieved"
    if text.startswith(NOTHING_RETRIEVED):
        return "nothing_retrieved"
    if text.startswith(NO_SENTENCE_ANSWERS):
        return "no_sentence_answers"
    return "answered" if (quotes or text) else "nothing_retrieved"


def esc(value) -> str:
    """Escape for HTML text content, leaving quotes alone.

    `quote=True` is the default and is wrong here: these strings are Swiss German prose in which the
    apostrophe is a thousands separator, so `863'000` came out as `863&#x27;000` on the page. Nothing
    rendered by this tool is interpolated into an attribute, so the quote is text like any other.
    """
    return html.escape("" if value is None else str(value), quote=False)


def slug_for(display_name: str, local: str) -> str:
    base = display_name.lower().replace(".", "").replace(" ", "-")
    return "".join(c for c in base if c.isalnum() or c == "-") or local


def unmapped_for(member_id: str) -> list[dict]:
    """What this member stated that nothing in the build reads."""
    from eigentlich.db import make_engine, make_session_factory
    from eigentlich.services.submissions import for_member, unmapped

    with make_session_factory(make_engine())() as db:
        rows = for_member(db, member_id=member_id)
        if not rows:
            return []
        return [
            {"key": u.key, "value": u.value, "reason": u.reason}
            for u in unmapped(rows[0])
        ]


def section(number: int, title: str, body: str) -> str:
    return f'<h2><span class="n">{number:02d}</span>{esc(title)}</h2>\n{body}\n'


def render_one(local: str, record: dict, unmapped: list[dict]) -> tuple[str, list[dict]]:
    """One client's report, and the issues found while rendering it."""
    issues: list[dict] = []
    name = record.get("display_name") or local
    parts: list[str] = []

    # -- 01 the member's own question -------------------------------------------------------------
    question = record.get("main_question")
    ask = (record.get("know_ask") or {}).get("body") or {}
    answer = ask.get("answer") or ""
    citations = ask.get("citations") or []
    body = ""
    if not question:
        body = '<p class="none">Diese Aufnahme enthält keine eigene Frage.</p>'
        issues.append({"kind": "no_main_question", "client": name,
                       "detail": "the submission carries no main_question"})
    else:
        body += f'<div class="q"><strong>Die Frage, wie sie gestellt wurde</strong><p>{esc(question)}</p></div>'
        quotes = ask.get("quotes") or []
        outcome = _know_outcome(answer, quotes)
        if ask.get("requires_curator"):
            body += f'<div class="a"><p>{esc(answer)}</p></div>'
            issues.append({"kind": "know_refused", "client": name, "detail": question})
        elif outcome == "nothing_retrieved":
            body += f'<div class="a"><p class="none">{esc(answer) or "Keine Antwort."}</p></div>'
            body += ('<div class="note">Zu dieser Frage wurde im Korpus nichts gefunden — nicht ein '
                     'Satz, der sie falsch beantwortet, sondern gar kein Material. Das System '
                     'antwortet ausschliesslich mit Sätzen aus abgelegten Quellen (C-11); wo keine '
                     'Quelle passt, sagt es das, statt etwas zu formulieren.</div>')
            issues.append({"kind": "know_nothing_retrieved", "client": name, "detail": question})
        elif outcome == "no_sentence_answers":
            body += f'<div class="a"><p class="none">{esc(answer)}</p></div>'
            body += ('<div class="note">Material zu dieser Frage ist vorhanden, aber kein einzelner '
                     'Satz darin beantwortet sie. Das ist eine andere Lücke als die vorige: hier '
                     'existiert der Stoff und trifft die Frage nicht.</div>')
            issues.append({"kind": "know_no_sentence_answers", "client": name, "detail": question})
        else:
            body += f'<div class="a"><p>{esc(answer)}</p></div>'
            if citations:
                body += "<table><thead><tr><th>Beleg</th><th>Quelle</th></tr></thead><tbody>"
                for i, c in enumerate(citations, 1):
                    body += (f"<tr><td>[{i}]</td><td>{esc(c.get('source') or c.get('kind') or '')}"
                             f"</td></tr>")
                body += "</tbody></table>"
            else:
                issues.append({"kind": "answer_without_citation", "client": name, "detail": question})
    parts.append(section(1, "Was die Anwendung auf Ihre Frage antwortet", body))

    # -- 02 the Befund ----------------------------------------------------------------------------
    befund = (record.get("befund") or {}).get("body") or {}
    sections = befund.get("sections") or []
    body = ""
    if not sections:
        body = '<p class="none">Die Anwendung liefert keinen Befund.</p>'
        issues.append({"kind": "no_befund", "client": name, "detail": "befund carried no sections"})
    for sec in sections:
        facts = sec.get("facts") or []
        body += f"<h3>{esc(sec.get('title'))}</h3>"
        if not facts:
            body += '<p class="muted">Zu diesem Abschnitt führt das System nichts.</p>'
            continue
        body += "<ul>"
        for fact in facts:
            sentence = fact.get("sentence") or ""
            body += f"<li>{esc(sentence)}"
            if fact.get("determination") and fact["determination"] != "stands":
                body += f' <span class="none">({esc(fact["determination"])})</span>'
                issues.append({"kind": "fact_undetermined", "client": name,
                               "detail": f"{fact.get('key')}: {fact['determination']}"})
            body += "</li>"
        body += "</ul>"
    prose = befund.get("prose") or {}
    if prose.get("refused"):
        body += ('<div class="note">Das Sprachmodell hat für diesen Bericht Sätze vorgeschlagen, die '
                 'verworfen wurden; ausgeliefert wurde die gerechnete Fassung.</div>')
        issues.append({"kind": "prose_refused", "client": name,
                       "detail": str(prose.get("refused"))[:200]})
    parts.append(section(2, "Der Befund, wie die Anwendung ihn ausliefert", body))

    # -- 03 positions -----------------------------------------------------------------------------
    # `/api/positions` serves the ROLE GRID (R-110): eight cells, each naming what would go in it.
    # The positions are inside the cells, and an empty cell is a statement rather than a blank.
    cells = ((record.get("positions") or {}).get("body") or {}).get("cells") or []
    positions = [(c, p) for c in cells for p in (c.get("positions") or [])]
    if positions:
        body = "<table><thead><tr><th>Position</th><th>Rolle</th><th>Kapital</th><th>Betrag</th></tr></thead><tbody>"
        for cell, p in positions:
            amount = p.get("magnitude")
            shown = f"{amount:,.0f}".replace(",", "’") if isinstance(amount, (int, float)) else esc(amount)
            body += (f"<tr><td>{esc(p.get('label'))}</td><td>{esc(cell.get('display'))}</td>"
                     f"<td>{esc(cell.get('capital_type'))}</td>"
                     f"<td>{shown} {esc((p.get('magnitude_unit') or '').upper())}</td></tr>")
        body += "</tbody></table>"
        empty = [c for c in cells if not (c.get("positions") or [])]
        if empty:
            body += (f'<p class="muted">{len(empty)} der {len(cells)} Felder des Rasters sind leer. '
                     f'Ein leeres Feld sagt, was dort hingehörte — es ist keine Lücke im Bericht.</p>')
    else:
        body = '<p class="none">Keine Position erfasst.</p>'
        issues.append({"kind": "no_positions", "client": name, "detail": "no position in any grid cell"})
    parts.append(section(3, "Was das System über Ihr Vermögen führt", body))

    # -- 04 goals ---------------------------------------------------------------------------------
    goals = ((record.get("goals") or {}).get("body") or {}).get("goals") or []
    if goals:
        body = "<table><thead><tr><th>Ziel</th><th>Zieldatum</th><th>Betrag</th><th>Gedeckt durch</th></tr></thead><tbody>"
        for g in goals:
            funded = g.get("funded_by") or []
            body += (f"<tr><td>{esc(g.get('name'))}</td><td>{esc(g.get('target_date'))}</td>"
                     f"<td>{esc(g.get('target_amount'))}</td>"
                     f"<td>{esc(len(funded)) if funded else '<span class=none>nichts</span>'}</td></tr>")
            if not funded:
                issues.append({"kind": "goal_unfunded", "client": name, "detail": g.get("name")})
        body += "</tbody></table>"
    else:
        body = '<p class="none">Kein Ziel erfasst.</p>'
        issues.append({"kind": "no_goals", "client": name, "detail": "goals list is empty"})
    parts.append(section(4, "Die Ziele, und wodurch sie gedeckt sind", body))

    # -- 05 actions -------------------------------------------------------------------------------
    actions = ((record.get("actions") or {}).get("body") or {}).get("items") or []
    if actions:
        body = "<ul>"
        for a in actions:
            options = a.get("prepared_options") or []
            body += f"<li><strong>{esc(a.get('trigger_kind'))}</strong>"
            if options:
                body += "<ul>" + "".join(
                    f"<li>{esc(o.get('label'))} — {esc(o.get('consequence'))}</li>" for o in options
                ) + "</ul>"
            else:
                body += ' <span class="none">ohne vorbereitete Optionen</span>'
                issues.append({"kind": "action_without_options", "client": name,
                               "detail": a.get("trigger_kind")})
            body += "</li>"
        body += "</ul>"
    else:
        body = '<p class="muted">Es steht nichts an.</p>'
    parts.append(section(5, "Was als Nächstes zu tun ist", body))

    # -- 06 what the system could not hold --------------------------------------------------------
    if unmapped:
        body = ('<p>Diese Angaben stehen in Ihrer Aufnahme und werden von der Anwendung nicht gelesen. '
                'Sie sind vollständig gespeichert und gehen nicht verloren — es gibt nur kein Feld, das '
                'sie trägt.</p>'
                "<table><thead><tr><th>Angabe</th><th>Wert</th><th>Warum nicht</th></tr></thead><tbody>")
        for u in unmapped:
            body += (f"<tr><td><code>{esc(u['key'])}</code></td><td>{esc(u['value'])[:70]}</td>"
                     f"<td class='muted'>{esc(u['reason'] or 'kein Mapping beansprucht diesen Schlüssel')}</td></tr>")
            issues.append({"kind": "unmapped_answer", "client": name, "detail": u["key"],
                           "reason": u["reason"]})
        body += "</tbody></table>"
    else:
        body = '<p class="ok">Jede Angabe dieser Aufnahme hat ein Feld gefunden.</p>'
    parts.append(section(6, "Was die Aufnahme enthält und das Modell nicht trägt", body))

    # -- 07 decisions -----------------------------------------------------------------------------
    decisions = ((record.get("decisions") or {}).get("body") or {}).get("decisions") or []
    body = (f"<p>{len(decisions)} Entscheid(e) sind zu diesem Plan festgehalten. Jede Änderung am Plan "
            f"erzeugt einen; das ist C-09 und es gilt ohne Ausnahme.</p>") if decisions else \
           '<p class="none">Kein Entscheid festgehalten.</p>'
    if not decisions:
        issues.append({"kind": "no_decisions", "client": name, "detail": "decision list is empty"})
    parts.append(section(7, "Der Entscheidverlauf", body))

    head = (f'<span class="lbl">eigentliCH · Standortbestimmung</span>'
            f"<h1>{esc(name)}</h1>"
            f'<p class="sub">Erzeugt am {TODAY.strftime("%d.%m.%Y")} aus dem, was die laufende '
            f"Anwendung auf die Mitglieder-Routen geantwortet hat. Nichts darin ist interpretiert.</p>")

    page = (f"<!DOCTYPE html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{esc(name)} · Standortbestimmung</title>\n<style>{STYLE}</style>\n</head>\n"
            f"<body>\n<main>\n{head}\n" + "\n".join(parts) + "\n</main>\n</body>\n</html>\n")
    return page, issues


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    data = json.loads((OUT / "new-clients.json").read_text(encoding="utf-8"))
    target = OUT / "clients"
    target.mkdir(parents=True, exist_ok=True)

    all_issues: list[dict] = []
    written: list[tuple[str, str, dict]] = []
    for local, record in sorted(data.items(), key=lambda kv: kv[1].get("display_name") or kv[0]):
        unmapped = unmapped_for(record["member_id"]) if record.get("member_id") else []
        page, issues = render_one(local, record, unmapped)
        slug = slug_for(record.get("display_name") or local, local)
        path = target / f"{slug}.html"
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(page)
        all_issues.extend(issues)
        written.append((slug, record.get("display_name") or local, record))
        print(f"  {path.name:<28} {len(issues):>3} issue(s)")

    # -- the index --------------------------------------------------------------------------------
    counts = collections.Counter(i["kind"] for i in all_issues)
    rows = ""
    for slug, name, record in written:
        ask = (record.get("know_ask") or {}).get("body") or {}
        answer = ask.get("answer") or ""
        answered = bool(answer.strip()) and "finde ich" not in answer and "nichts" not in answer.lower()
        goals = ((record.get("goals") or {}).get("body") or {}).get("goals") or []
        positions = ((record.get("positions") or {}).get("body") or {}).get("positions") or []
        rows += (f'<tr><td><a href="clients/{slug}.html">{esc(name)}</a></td>'
                 f'<td class="{"ok" if answered else "none"}">'
                 f'{"beantwortet" if answered else "nichts gefunden"}</td>'
                 f"<td>{len(goals)}</td><td>{len(positions)}</td></tr>")

    index = (f"<!DOCTYPE html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
             f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
             f"<title>eigentliCH · {len(written)} Standortbestimmungen</title>\n<style>{STYLE}</style>\n"
             f"</head>\n<body>\n<main>\n"
             f'<span class="lbl">eigentliCH</span><h1>{len(written)} Standortbestimmungen</h1>'
             f'<p class="sub">Alle am {TODAY.strftime("%d.%m.%Y")} durch die laufende Anwendung '
             f"erzeugt. Die Übersicht der Befunde über das System selbst liegt in "
             f"<code>ISSUES-2026-09-20.md</code>.</p>"
             f"<table><thead><tr><th>Mitglied</th><th>Eigene Frage</th><th>Ziele</th>"
             f"<th>Positionen</th></tr></thead><tbody>{rows}</tbody></table>"
             f"</main>\n</body>\n</html>\n")
    with io.open(OUT / "clients" / "index.html", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(index)

    with io.open(OUT / "new-clients-issues.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(all_issues, handle, ensure_ascii=False, indent=1)

    print(f"\n{len(written)} report(s) + index in {target}")
    print(f"{len(all_issues)} issue(s) recorded, by kind:")
    for kind, n in counts.most_common():
        print(f"    {kind:<26} {n:>4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
