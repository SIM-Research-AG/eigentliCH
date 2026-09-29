"""The report as one self-contained HTML page, rendered from the facts and the checked prose. Pure.

**House style, copied not reinvented** (``Projects/eigentliCH/desktop/dossier.py``): the stylesheet of the
hand-written dossiers verbatim (serif body, sans headings, the gradient rule, tabular numerals), inlined so
the page survives being sent as a single file; the fixed section order, numbered at render time so a
section left out leaves no hole.

**Every figure on the page is a fact.** A value is printed only as ``<span data-fact="{id}">{display}</span>``
(or ``<b data-fact>``), so the page can be traced figure by figure to the artefact behind it; identifiers and
versions are in ``<code>``; engine messages sit in elements marked ``data-meta``. Model prose is printed only
when its check passed (``prose_status == "verified"``), marked ``data-prose``. ``tests/test_golden.py`` holds
the page to this: outside those elements it carries no number of two or more digits.
"""

from __future__ import annotations

import html
from typing import Any, Mapping, Optional, Sequence

from . import vocabulary as voc
from .contracts import NOTICE, Fact, ReportProvenance, Section

#: The stylesheet of the five hand-written dossiers, verbatim from dossier.py (the form elements of its
#: interactive stage are left out: a report has no controls).
CSS = """
  :root{--ink:#1A1740;--soft:#5d4591;--line:#ECE8F4;--tint:#F6F4FB;--acc:#A059C1;
        --warn:#C1445A;--ok:#2E7D64;--g1:#8890e7;--g2:#A059C1;--g3:#FEA479;--g4:#FFE8A1}
  *{box-sizing:border-box}
  body{margin:0;background:#fff;color:var(--ink);font:16px/1.62 "Iowan Old Style","Palatino Linotype",Georgia,serif}
  .w{max-width:860px;margin:0 auto;padding:44px 28px 90px}
  .ey{font-family:ui-sans-serif,system-ui,sans-serif;font-size:11px;letter-spacing:.14em;
      text-transform:uppercase;color:var(--soft);font-weight:600}
  h1{font-size:31px;line-height:1.2;margin:10px 0 4px;font-weight:600}
  .lede{font-size:18px;color:#3b3363;margin:0}
  .rule{height:3px;border-radius:3px;margin:24px 0 30px;
        background:linear-gradient(110deg,var(--g1),var(--g2) 40%,var(--g3) 80%,var(--g4))}
  h2{font-family:ui-sans-serif,system-ui,sans-serif;font-size:15px;margin:38px 0 10px;
     padding-top:16px;border-top:1px solid var(--line);font-weight:700}
  h2 .ix{display:inline-block;min-width:2.1em;color:var(--acc);font-variant-numeric:tabular-nums}
  h3{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13.5px;margin:20px 0 5px}
  p{margin:0 0 12px}
  .box{background:var(--tint);border:1px solid var(--line);border-radius:12px;padding:15px 19px;margin:18px 0}
  .box.warn{background:#FDF3F5;border-color:#F0D3DA}
  .box.ok{background:#F1F8F5;border-color:#CFE6DC}
  .box.draft{background:#FCFBFE;border-style:dashed;border-color:#D8CEE8}
  .banner{border:1px solid var(--line);border-radius:12px;padding:13px 17px;margin:14px 0 0;
          background:var(--tint)}
  .chips{display:flex;gap:8px;flex-wrap:wrap;font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px}
  .chip{background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 11px;color:var(--soft)}
  .chip b{color:var(--ink);font-variant-numeric:tabular-nums}
  .box p{font-size:14.6px;margin:0 0 8px}
  .box p:last-child{margin:0}
  .tag{font-family:ui-sans-serif,system-ui,sans-serif;font-size:10.5px;font-weight:700;
       letter-spacing:.09em;text-transform:uppercase;display:block;margin-bottom:5px}
  .tag.w{color:var(--warn)} .tag.o{color:var(--ok)} .tag.n{color:var(--acc)}
  table{width:100%;border-collapse:collapse;margin:10px 0 6px;
        font-family:ui-sans-serif,system-ui,sans-serif;font-size:13.4px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--soft)}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .neg{color:var(--warn)} .pos{color:var(--ok)}
  tr.tot td{border-top:2px solid var(--ink);border-bottom:none;font-weight:700}
  small{font-size:12.4px;color:var(--soft);font-family:ui-sans-serif,system-ui,sans-serif}
  .foot{margin-top:40px;padding-top:15px;border-top:1px solid var(--line);
        font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px;color:var(--soft)}
  code{font:11.5px ui-monospace,Consolas,monospace}
  ul{margin:6px 0 12px;padding-left:22px}
  li{margin-bottom:6px}
  @media print{body{font-size:11pt}.w{padding:0}h2{page-break-after:avoid}.box{page-break-inside:avoid}}
"""

WORDS: dict[str, dict[str, str]] = {
    "de": {
        "eyebrow_report": "eigentliCH · Bericht", "eyebrow_update": "eigentliCH · Update",
        "h1_report": "Bericht", "h1_update": "Update zum Bericht",
        "lede": "Stand {as_of}. Jede Zahl in diesem Bericht stammt aus einem veröffentlichten Artefakt; woher, steht "
                "im letzten Abschnitt.",
        "lede_prose": " Die verbindenden Sätze schreibt {assistant}, die KI von eigentliCH, und jede Zahl darin ist "
                      "gegen die Fakten ihres Abschnitts geprüft.",
        "lede_update": " Der erste Abschnitt nennt, was sich seit dem vorigen Bericht verändert hat.",
        "figure": "Grösse", "value": "Wert", "block": "Baustein", "role": "Rolle", "weight": "Gewicht",
        "cell": "Rolle und Kapitalart", "assets": "Vermögen", "liabilities": "Verbindlichkeiten",
        "before_now": "vorher → jetzt", "change": "Veränderung", "engine": "Engine", "artefact": "Artefakt",
        "contract": "Vertrag", "checksum": "Prüfsumme", "source": "Quelle", "dated": "Stand",
        "withheld": "Der verbindende Text zu diesem Abschnitt ist zurückgehalten: er enthielt eine Zahl, die in den "
                    "Fakten des Abschnitts nicht vorkommt.",
        "warnings": "Hinweise zu diesem Bericht",
        "allocation": "Die Gewichte sind die Lösung eines Modells für das Mandat {name} zum {date}. Sie sind {state}: "
                      "eine Freigabe ist der Entscheid einer Person ausserhalb dieses Berichts.",
        "no_changes": "Keine Zahl hat sich verändert.",
        "revision": "Diese Fassung überarbeitet einen früheren Bericht. Die Kuratorin oder der Kurator merkt dazu an:",
        "foot": "Kalibrierung {calibration} · {engine}. Dieser Bericht ist eine "
                "Standortbestimmung und keine Empfehlung. Modellbasierte Auswertung. Keine Anlageberatung.",
    },
    "en": {
        "eyebrow_report": "eigentliCH · Report", "eyebrow_update": "eigentliCH · Update",
        "h1_report": "Report", "h1_update": "Update to the report",
        "lede": "As of {as_of}. Every figure in this report comes from a published artefact; where from is set out in "
                "the last section.",
        "lede_prose": " The connecting sentences are written by {assistant}, eigentliCH's AI, and every figure in "
                      "them is checked against the facts of their section.",
        "lede_update": " The first section sets out what has changed since the previous report.",
        "figure": "Figure", "value": "Value", "block": "Building block", "role": "Role", "weight": "Weight",
        "cell": "Role and capital type", "assets": "Assets", "liabilities": "Liabilities",
        "before_now": "before → now", "change": "Change", "engine": "Engine", "artefact": "Artefact",
        "contract": "Contract", "checksum": "Checksum", "source": "Source", "dated": "As of",
        "withheld": "The connecting text for this section is withheld: it contained a figure that is not among the "
                    "section's facts.",
        "warnings": "Notes on this report",
        "allocation": "The weights are the solution of a model for the mandate {name} as of {date}. They are {state}: "
                      "releasing them is a person's decision outside this report.",
        "no_changes": "No figure has changed.",
        "revision": "This version revises an earlier report. The curator's remark:",
        "foot": "Calibration {calibration} · {engine}. This report sets out a position "
                "and is not a recommendation. " + NOTICE,
    },
}


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def v(f: Fact, tag: str = "span") -> str:
    """A fact's value as the page prints it, traceable by its id."""
    return f'<{tag} data-fact="{e(f.fact_id)}">{e(f.display)}</{tag}>'


def _table(headers: Sequence[tuple[str, bool]], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f'<th class="n">{e(h)}</th>' if n else f"<th>{e(h)}</th>" for h, n in headers)
    body = []
    for row in rows:
        cells = "".join(f'<td class="n">{c}</td>' if n else f"<td>{c}</td>" for (_, n), c in zip(headers, row))
        body.append(f"<tr>{cells}</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def _default(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    return _table([(w["figure"], False), (w["value"], True)], [(e(f.label), v(f)) for f in facts])


def _positions(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    weights = [f for f in facts if f.fact_id.startswith("pcp.position.")]
    roles = {f.fact_id.removeprefix("pcp.position_role."): f for f in facts if f.fact_id.startswith("pcp.position_role.")}
    rows = []
    for f in weights:
        iid = f.fact_id.removeprefix("pcp.position.")
        role = roles.get(iid)
        rows.append((e(f.label), v(role) if role else "", v(f)))
    return _table([(w["block"], False), (w["role"], False), (w["weight"], True)], rows)


def _grid(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    cells: dict[str, dict[str, Fact]] = {}
    for f in facts:
        base, _, kind = f.fact_id.rpartition(".")
        cells.setdefault(base, {})[kind] = f
    rows = []
    for parts in cells.values():
        name = next(iter(parts.values())).label
        rows.append((e(name), v(parts["assets"]) if "assets" in parts else "–",
                     v(parts["liabilities"]) if "liabilities" in parts else "–"))
    return _table([(w["cell"], False), (w["assets"], True), (w["liabilities"], True)], rows)


def _changes(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    by = {f.fact_id: f for f in facts}
    moved = [f for f in facts if f.fact_id.startswith("change.")]
    out = []
    if moved:
        rows = []
        for f in moved:
            delta = by.get("delta." + f.fact_id.removeprefix("change."))
            rows.append((e(f.label), v(f), v(delta) if delta else ""))
        out.append(_table([(w["figure"], False), (w["before_now"], True), (w["change"], True)], rows))
    else:
        out.append(f"<p>{e(w['no_changes'])}</p>")
    rest = [by[k] for k in ("changes.unchanged", "changes.added", "changes.removed") if k in by]
    if rest:
        out.append(_default(rest, w))
    return "".join(out)


def _limits(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    items = "".join(f"<li><small>{e(f.label)}:</small> {v(f)}</li>" for f in facts)
    return f'<div class="box"><ul>{items}</ul></div>'


def _sources(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    """The sources in words and dates (REP-23): "Ihre Bilanz, Stand ...". Their ids, contracts and checksums stay
    in the artefact's provenance and in every fact's sources; the page shows none of them."""
    rows = [(e(f.label), v(f)) for f in facts if f.fact_id.startswith("sources.date.")]
    out = _table([(w["source"], False), (w["dated"], False)], rows)
    shown = [f for f in facts if f.fact_id == "sources.as_of"]
    return out + (_default(shown, w) if shown else "")


def _allocation(facts: Sequence[Fact], w: Mapping[str, str]) -> str:
    by = {f.fact_id: f for f in facts}
    lead = ""
    if all(k in by for k in ("pcp.mandate_name", "pcp.date", "pcp.release_state")):
        lead = "<p>" + w["allocation"].format(name=v(by["pcp.mandate_name"]), date=v(by["pcp.date"]),
                                             state=v(by["pcp.release_state"])) + "</p>"
    rest = [f for f in facts if f.fact_id not in ("pcp.mandate_name", "pcp.date", "pcp.release_state")]
    return lead + _default(rest, w)


BODY = {"positions": _positions, "grid": _grid, "changes": _changes, "limits": _limits, "allocation": _allocation}


def render(*, lang: str, kind: str, title: str, facts: Sequence[Fact], sections: Sequence[Section],
           warnings: Sequence[str], provenance: ReportProvenance, calibration_version: str, engine_version: str,
           assistant: str = "MiniMind", names: Optional[Mapping[str, str]] = None) -> str:
    """The page. ``warnings`` are the page's notes, already in the reader's language (the artefact's own
    ``warnings`` are the engine's, in English). ``names`` maps a generic subject name ("Person 1", "Ihr
    Wohneigentumsziel") to the name the caller sent for it (REP-20); it is applied to labels, text values and
    prose on the page only, never to what the model saw."""
    w = WORDS[lang]
    names = dict(names or {})
    if names:
        facts = [f.model_copy(update={"label": voc.apply_names(f.label, names),
                                      "display": voc.apply_names(f.display, names) if f.unit == "text" else f.display})
                 for f in facts]
    by = {f.fact_id: f for f in facts}
    parts: list[str] = []
    for n, s in enumerate(sections, start=1):
        sf = [by[i] for i in s.fact_ids]
        parts.append(f'<section id="sec-{e(s.key)}" data-section="{e(s.key)}">')
        parts.append(f'<h2><span class="ix">{n:02d}</span>{e(s.title)}</h2>')
        if s.prose_status == "verified" and s.prose:
            parts.append(f'<p class="prose" data-prose="{e(s.key)}">{e(voc.apply_names(s.prose, names))}</p>')
        elif s.prose_status == "flagged":
            parts.append(f"<p><small>{e(w['withheld'])}</small></p>")
        if s.key == "sources":
            parts.append(_sources([f for f in sf if not f.fact_id.startswith("caller.")], w))
        else:
            parts.append(BODY.get(s.key, _default)(sf, w))
        parts.append("</section>")

    as_of = by.get("sources.as_of")
    lede = w["lede"].format(as_of=v(as_of) if as_of else "–")
    if any(s.prose_status == "verified" for s in sections):
        lede += w["lede_prose"].format(assistant=e(assistant))
    if kind == "update":
        lede += w["lede_update"]
    chips = "".join(f'<span class="chip">{e(f.label)} {v(f, "b")}</span>'
                    for f in facts if f.fact_id.startswith("caller.") and f.fact_id != "caller.revision_note"
                    and not voc.NAMING_KEY.match(f.fact_id.removeprefix("caller.")))
    banner = f'<div class="banner"><div class="chips">{chips}</div></div>' if chips else ""
    # A revision (REP-25): the curator's remark, as written, in its own box under the lede.
    revision = ""
    if "caller.revision_note" in by:
        remark = by["caller.revision_note"]
        revision = (f'<div class="box" data-meta="revision"><span class="tag n">{e(remark.label)}</span>'
                    f'<p>{e(w["revision"])}</p><p>{v(remark)}</p></div>\n')
    notes = ""
    if warnings:
        items = "".join(f"<p>{e(x)}</p>" for x in warnings)
        notes = f'<div class="box warn" data-meta="warnings"><span class="tag w">{e(w["warnings"])}</span>{items}</div>'
    foot = w["foot"].format(calibration=f"<code>{e(calibration_version)}</code>",
                            engine=f"<code>{e(engine_version)}</code>")
    return (
        f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<div class=\"w\">\n"
        f'<div class="ey">{e(w["eyebrow_" + kind])}</div>\n'
        f'<h1>{e(w["h1_" + kind])}</h1>\n<p class="lede">{lede}</p>\n{banner}\n{revision}{notes}\n<div class="rule"></div>\n'
        f'{"".join(parts)}\n<div class="foot">{foot}</div>\n</div>\n</body>\n</html>\n'
    )


def plain_title(lang: str, kind: str, name: Optional[str] = None) -> str:
    """The page title: the kind, and the client's name when the caller sent one (display fact ``name``); never
    the ``client_ref``, which is an identifier (REP-20)."""
    head = WORDS[lang]["h1_" + kind]
    return f"{head} · {name}" if name else head

