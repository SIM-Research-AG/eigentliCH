"""The dossier, rendered from the deterministic quantities. No model in this path.

**Why the renderer is deterministic and the prose is not.** Every figure, every table row, every finding and the
whole Zeitplan come from `personal_alm.app.gameplan` and `personal_alm.app.findings`, which are rules. What a
language model adds is the connective sentence -- and `desktop/prose.py` already exists for exactly that, with a
number verifier, because the model has been caught calling 800 000 of debt *das Eigenkapital*. So the structure,
the order and the arithmetic are fixed here, and the prose layer may fill declared slots inside a page that is
already complete and readable without it.

**The section order is fixed and is an argument.** The five hand-written dossiers each chose their own order,
and comparing them showed the same shape underneath: where the household stands, what it generates, what
arrives without a decision, what is missing, then the question it actually asked, then the levers, then the
findings, then what the report cannot say, and last the schedule. A reader who stops after three sections has
still read the three that matter most. Bespoke headlines are what a human adds on top; they are not what makes
the document work.

**Sections disappear rather than print empty.** A household with no children, no early stop and no mortgage
gets a shorter dossier, not one with three sections saying "not applicable". The numbering is therefore
assigned at render time and the cross-references are computed, never typed.

**House style, copied not reinvented.** The stylesheet is the one the five dossiers share -- serif body, sans
headings, the gradient rule, tabular numerals. It is inlined because the page must survive being emailed as a
single file, which is how every one of these has actually been delivered.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

#: The stylesheet of the five hand-written dossiers, verbatim. Kept as one string rather than assembled, so a
#: diff against any existing dossier shows nothing changed.
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
  /* Dashed, and off-white rather than tinted: a draft must not look like a finding. */
  .box.draft{background:#FCFBFE;border-style:dashed;border-color:#D8CEE8}
  .banner{border:1px solid var(--line);border-radius:12px;padding:13px 17px;margin:14px 0 0;
          background:var(--tint)}
  .chips{display:flex;gap:8px;flex-wrap:wrap;font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px}
  .chip{background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 11px;color:var(--soft)}
  .chip b{color:var(--ink);font-variant-numeric:tabular-nums}
  .chip.open{border-color:#F0D3DA;background:#FDF3F5}
  .chip.open b{color:var(--warn)}
  .chip.done{border-color:#CFE6DC;background:#F1F8F5;color:var(--ok)}
  .bnote{font-size:14px;margin:10px 0 0}
  .barwrap{display:inline-block;width:74px;height:7px;border-radius:4px;background:var(--line);
           margin-right:8px;vertical-align:middle;overflow:hidden}
  .bar{display:block;height:100%;background:var(--acc)}
  .askq{font-family:ui-sans-serif,system-ui,sans-serif;font-size:14px;font-weight:600;margin-bottom:3px}
  .askwhy{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13px;color:var(--soft);margin-bottom:2px}
  .askrow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
  .askchk{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13px;display:inline-flex;
          align-items:center;gap:5px;margin-right:10px;white-space:nowrap}
  .askin{font:inherit;font-size:14px;padding:6px 9px;border:1px solid var(--line);border-radius:8px;
         min-width:9rem;background:#fff;color:var(--ink)}
  .askrow button{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13px;font-weight:600;
                 padding:7px 13px;border:1px solid var(--acc);border-radius:8px;background:var(--acc);
                 color:#fff;cursor:pointer}
  .askrow button:disabled{opacity:.45;cursor:default}
  /* The way past the gate, styled as the secondary action it is: available, not inviting. Somebody who has
     the figure should answer the question; this is for somebody who does not have it. */
  .askgo{font-family:ui-sans-serif,system-ui,sans-serif;font-size:13px;font-weight:600;cursor:pointer;
    padding:7px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;color:var(--soft)}
  .askgo:hover{border-color:var(--acc);color:var(--acc)}
  .askgo:disabled{opacity:.45;cursor:default}
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
  .tl{border-left:2px solid var(--line);margin:14px 0 14px 8px;padding-left:20px}
  .tl .it{position:relative;margin-bottom:17px}
  .tl .it:before{content:"";position:absolute;left:-27px;top:6px;width:9px;height:9px;
                 border-radius:50%;background:var(--acc)}
  .tl .yr{font-family:ui-sans-serif,system-ui,sans-serif;font-size:11.5px;font-weight:700;
          letter-spacing:.06em;color:var(--acc)}
  .tl .hd{font-weight:600;margin:1px 0 2px}
  .tl p{font-size:14.4px;margin:0}
  small{font-size:12.4px;color:var(--soft);font-family:ui-sans-serif,system-ui,sans-serif}
  .foot{margin-top:40px;padding-top:15px;border-top:1px solid var(--line);
        font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px;color:var(--soft)}
  figure{margin:16px 0 6px}
  figure svg{width:100%;height:auto;display:block}
  figcaption{margin-top:4px}
  ul{margin:6px 0 12px;padding-left:22px}
  li{margin-bottom:6px}
  @media print{body{font-size:11pt}.w{padding:0}h2{page-break-after:avoid}.box{page-break-inside:avoid}}
"""

#: The colours the figures use, matching the stylesheet's variables. Duplicated as literals because an SVG
#: attribute cannot read a CSS custom property in every renderer that matters, notably print.
INK, SOFT, LINE, ACC, WARN, OK = "#1A1740", "#5d4591", "#ECE8F4", "#A059C1", "#C1445A", "#2E7D64"

#: Severity to the stylesheet's box class and tag class.
_SEV = {"blocking": ("warn", "w"), "high": ("warn", "w"), "medium": ("", "n"), "note": ("", "n")}


# --- the register's vocabulary, in German ---------------------------------------------------------------
#
# **The data keeps its English keys and only the rendering is translated.** `Gain`, `Daily` and `derived` are
# identifiers: they come from the published ReturnSet and the mandate contract, they are matched on elsewhere,
# and translating them at the source would mean a German string had to travel back through the Optimiser. So
# the canonical form stays English, as every other identifier in this repo does, and the German exists only
# where a client reads it. That is the same split the house rule already draws -- client-facing material in
# German, architecture and method in English -- applied one level down.
#
# An unknown key falls through to itself rather than to a placeholder. A register that gains a ninth building
# block should show its English role rather than a dash: wrong language beats missing information.
_DE_FAMILY = {
    "liquidity": "Liquidität", "currency": "Währung", "role": "Rolle",
    "asset_class": "Anlageklasse", "region": "Region", "capital_type": "Kapitalart",
    "phase": "Phase", "esg": "ESG",
}

#: Gain and Income both translate naturally to something income-like, which would lose the distinction the
#: register draws. Gain is capital appreciation, Income is a paid yield, so: Wertsteigerung and Ertrag.
_DE_CATEGORY = {
    "Gain": "Wertsteigerung", "Income": "Ertrag", "Protection": "Schutz",
    "Stabilisation": "Stabilisierung",
    "Daily": "täglich", "Quarterly": "vierteljährlich", "Yearly": "jährlich",
    "Decade": "über zehn Jahre",
    "Cash": "Barmittel", "Equity": "Aktien", "Fixed Income": "Anleihen",
    "Real Assets": "Realwerte", "Real Estate": "Immobilien", "Alternative": "Alternative",
    "Financial": "finanziell", "Real": "real", "Others": "übrige",
    "Switzerland": "Schweiz", "Europe": "Europa", "North America": "Nordamerika",
    "East Asia": "Ostasien", "South Asia": "Südasien", "South Pacific": "Südpazifik",
    "Foundation": "Aufbau", "Build-up": "Aufbau", "Optimisation": "Optimierung",
    "Saturation": "Sättigung",
}

#: Where a bound came from. `derived` means this household's own goal and position produced it; `policy` means
#: the CIO set it and no household model implies it. Naming that in the table is the point of the column.
_DE_SOURCE = {"derived": "abgeleitet", "policy": "CIO-Vorgabe", "household": "Ihre Angabe"}


def de_family(x: object) -> str:
    return _DE_FAMILY.get(str(x), str(x))


def de_category(x: object) -> str:
    return _DE_CATEGORY.get(str(x), str(x))


def de_source(x: object) -> str:
    return _DE_SOURCE.get(str(x), str(x))


#: Measured wall-clock for one `befund` at DEFAULT_SETTINGS, by the goal's horizon in years. Three points from
#: real runs: 3 years about ten minutes, 10 years about forty, 20 years over seventy. Roughly three and a half
#: minutes per year of horizon, which is what the cost driver predicts -- each solve is M_opt scenarios times
#: K = horizon / dt_opt steps, and dt_opt is 0.5, so the step count is twice the horizon.
#:
#: **Given as a range, because a single figure here would be false precision.** The same household re-run is
#: not the same wall clock: the multistart takes a different number of IPOPT iterations each time.
_MINUTES_PER_HORIZON_YEAR = 3.5


def solve_estimate(q: dict) -> tuple[int, int, bool]:
    """Minutes low, minutes high, and whether the probes could multiply it.

    The probes are the reason the high end is not the whole story and are called out separately rather than
    folded in: they fire only when the stated goal comes back short of its required confidence, and each one
    is another full solve. Averaging that into a single range would understate a household whose goal does not
    hold and overstate one whose does.

    **The SEED REDRAW is a second multiplier and was not mentioned to the household until 26 August 2026.**
    `solve_case` carries `seed_retries = 3`: a run that does not succeed is recomputed on a fresh scenario
    draw up to twice more before it gives up. So a household whose solve comes back `undetermined` waits up to
    three times this range before the probes even begin, and nothing said so. Measured on a real submission
    with a 41-year horizon: this function estimates 100 to 201 minutes and the run took four and a half hours.
    Not folded into the number here for the same reason as the probes — it fires on failure, not in general —
    but now stated in the prose beside it.
    """
    years = float((q.get("required_return") or {}).get("years")
                  or (q.get("income_65") or {}).get("years_to_reference") or 10.0)
    mid = max(4.0, _MINUTES_PER_HORIZON_YEAR * years)
    return int(round(mid * 0.7)), int(round(mid * 1.4)), True


def e(x: Any) -> str:
    """Escaped. Every value that reaches the page goes through this, including ones from the intake."""
    return html.escape("" if x is None else str(x), quote=True)


def m(x: float | None, digits: int = 0) -> str:
    """Swiss money. A thin space as the thousands separator, as in every existing dossier."""
    if x is None:
        return "–"
    return f"{x:,.{digits}f}".replace(",", " ").replace("-", "−")


def pc(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "–"
    return f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def num(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "–"
    return f"{x:.{digits}f}".replace(".", ",")


class Doc:
    """A dossier under construction. Sections number themselves, so a skipped one leaves no hole."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.n = 0
        self.index: dict[str, int] = {}
        #: Fields already offered a control, so no field is asked twice in one document.
        self.slots: set[str] = set()

    def slot(self, field: str | None, fallback: str) -> str:
        """A control for `field`, or plain text if it has already been offered once in this document.

        **The same field can be the answer to more than one thing.** Two assumptions both pointed at the
        canton and the report rendered the question twice, with two independent selects — which is not merely
        untidy: two controls for one field invite two different answers, and only one of them can win. So the
        first occurrence gets the control and every later one gets the text.
        """
        if not field:
            return fallback
        if field in self.slots:
            # Already offered. With a fallback, say where; without one, say nothing rather than leave an
            # empty box that looks like a rendering fault.
            return (f'{fallback} <small>— die Frage dazu steht weiter oben</small>' if fallback else "")
        self.slots.add(field)
        return f'<span data-ask-slot="{e(field)}">{fallback}</span>'

    def section(self, key: str, title: str) -> None:
        """Open a numbered section. **The wrapper is what lets a section be replaced later.**

        Each section is its own element with a stable id, so the two-stage report can swap one in place
        without touching the rest of the page or the reader's scroll position. Without the wrapper the only
        unit of replacement is the whole document, and re-rendering the whole document under someone who is
        reading paragraph four is worse than making them wait.
        """
        if self.n:
            self.parts.append("</section>")
        self.n += 1
        self.index[key] = self.n
        self.parts.append(f'<section id="sec-{key}" data-section="{key}">')
        self.parts.append(f'<h2><span class="ix">{self.n:02d}</span>{e(title)}</h2>')

    def sub(self, title: str) -> None:
        self.parts.append(f"<h3>{e(title)}</h3>")

    def p(self, text: str) -> None:
        """Raw HTML paragraph. Callers escape their own values; the surrounding markup is ours."""
        self.parts.append(f"<p>{text}</p>")

    def box(self, tag: str, title: str, *paragraphs: str, kind: str = "") -> None:
        cls = f"box {kind}".strip()
        body = "".join(f"<p>{t}</p>" for t in paragraphs)
        self.parts.append(f'<div class="{cls}"><span class="tag {tag}">{e(title)}</span>{body}</div>')

    def table(self, headers: list[tuple[str, bool]], rows: list[tuple | None]) -> None:
        """`headers` is (label, numeric). A row of None is dropped, so a caller can filter inline."""
        head = "".join(f'<th class="n">{e(h)}</th>' if n else f"<th>{e(h)}</th>" for h, n in headers)
        out = [f"<tr>{head}</tr>"]
        for row in rows:
            if row is None:
                continue
            cls = ' class="tot"' if len(row) > len(headers) and row[len(headers)] == "tot" else ""
            cells = []
            for (label, numeric), value in zip(headers, row):
                extra = ""
                text = value
                if isinstance(value, tuple):
                    text, extra = value
                cells.append(f'<td class="{("n " + extra).strip() if numeric else extra}">{text}</td>'
                             if (numeric or extra) else f"<td>{text}</td>")
            out.append(f"<tr{cls}>{''.join(cells)}</tr>")
        self.parts.append(f"<table>{''.join(out)}</table>")

    def figure(self, svg: str, caption: str) -> None:
        self.parts.append(f"<figure>{svg}<figcaption><small>{caption}</small></figcaption></figure>")

    def html(self) -> str:
        return "".join(self.parts) + ("</section>" if self.n else "")


# --- figures --------------------------------------------------------------------------------------------

def _svg_health(h: dict) -> str:
    """Two health paths to the horizon. The chart that turned a coefficient into a decision in three cases."""
    own, base = h["path_own"], h["path_at_threshold"]
    n = max(1, len(own) - 1)
    top = max(own[0], base[0]) or 1.0
    x = lambda i: 60 + 640 * i / n  # noqa: E731
    y = lambda v: 170 - 150 * (v / top)  # noqa: E731
    p_own = " ".join(f"{'M' if i == 0 else 'L'} {x(i):.0f} {y(v):.0f}" for i, v in enumerate(own))
    p_base = " ".join(f"{'M' if i == 0 else 'L'} {x(i):.0f} {y(v):.0f}" for i, v in enumerate(base))
    age0 = h.get("age_start")
    age1 = h.get("age_end")
    return (
        f'<svg viewBox="0 0 760 210" role="img" aria-label="Gesundheitsverlauf">'
        f'<line x1="60" y1="170" x2="700" y2="170" stroke="{LINE}"/>'
        f'<line x1="60" y1="20" x2="60" y2="170" stroke="{LINE}"/>'
        f'<text x="52" y="26" text-anchor="end" style="font:11px ui-sans-serif;fill:{SOFT}">'
        f'{num(top)}</text>'
        f'<text x="52" y="174" text-anchor="end" style="font:11px ui-sans-serif;fill:{SOFT}">0,0</text>'
        f'<path d="{p_own}" fill="none" stroke="{WARN}" stroke-width="2.4"/>'
        f'<path d="{p_base}" fill="none" stroke="{OK}" stroke-width="2.4"/>'
        f'<circle cx="{x(n):.0f}" cy="{y(own[-1]):.0f}" r="4" fill="{WARN}"/>'
        f'<circle cx="{x(n):.0f}" cy="{y(base[-1]):.0f}" r="4" fill="{OK}"/>'
        f'<text x="694" y="{y(own[-1]) + 16:.0f}" text-anchor="end" '
        f'style="font:11px ui-sans-serif;fill:{WARN}">{h["hours"]:.0f} h: {num(own[-1])}</text>'
        f'<text x="694" y="{y(base[-1]) - 8:.0f}" text-anchor="end" '
        f'style="font:11px ui-sans-serif;fill:{OK}">{h["threshold_hours"]:.0f} h: '
        f'{num(base[-1])}</text>'
        f'<text x="60" y="192" style="font:11px ui-sans-serif;fill:{SOFT}">'
        f'{"" if age0 is None else f"{age0:.0f}"}</text>'
        f'<text x="700" y="192" text-anchor="end" style="font:11px ui-sans-serif;fill:{SOFT}">'
        f'{"" if age1 is None else f"{age1:.0f}"}</text>'
        f'</svg>'
    )


def _svg_capital(gap: dict) -> str:
    """The capital requirement at three withdrawal rates. Bars, because the point is the spread."""
    items = sorted(gap["capital"].items())
    top = max([v for _, v in items] or [1.0]) or 1.0
    bars = []
    for i, (rate, value) in enumerate(items):
        x = 90 + i * 210
        h = max(2.0, 150 * value / top)
        fill = ACC if abs(float(rate) - gap["model_rate"]) < 1e-9 else "#C9B6DE"
        bars.append(
            f'<rect x="{x}" y="{170 - h:.0f}" width="120" height="{h:.0f}" rx="4" fill="{fill}"/>'
            f'<text x="{x + 60}" y="{170 - h - 8:.0f}" text-anchor="middle" '
            f'style="font:12px ui-sans-serif;font-weight:700;fill:{INK}">{m(value)}</text>'
            f'<text x="{x + 60}" y="190" text-anchor="middle" '
            f'style="font:11px ui-sans-serif;fill:{SOFT}">{pc(float(rate))}</text>')
    return (f'<svg viewBox="0 0 760 205" role="img" aria-label="Kapitalbedarf nach Entnahmesatz">'
            f'<line x1="70" y1="170" x2="700" y2="170" stroke="{LINE}"/>{"".join(bars)}</svg>')


def _svg_allocation(alloc: dict) -> str:
    """The weights as a stacked bar by role, then the rows. One figure, because roles are the argument."""
    rows = [r for r in alloc.get("allocation", []) if r["weight"] > 0.0005]
    if not rows:
        return ""
    colours = {"Gain": "#8890e7", "Income": "#A059C1", "Protection": "#2E7D64",
               "Stabilisation": "#FEA479"}
    x, segs, labels = 60.0, [], []
    for r in rows:
        w = 640 * r["weight"]
        segs.append(f'<rect x="{x:.1f}" y="30" width="{max(0.6, w):.1f}" height="34" '
                    f'fill="{colours.get(r["role"], "#C9B6DE")}"/>')
        if w > 46:
            labels.append(f'<text x="{x + w / 2:.1f}" y="52" text-anchor="middle" '
                          f'style="font:11px ui-sans-serif;font-weight:700;fill:#fff">'
                          f'{pc(r["weight"], 0)}</text>')
        x += w
    key = []
    for i, (role, colour) in enumerate(colours.items()):
        share = sum(r["weight"] for r in rows if r["role"] == role)
        kx = 60 + i * 175
        key.append(f'<rect x="{kx}" y="88" width="10" height="10" rx="2" fill="{colour}"/>'
                   f'<text x="{kx + 16}" y="97" style="font:11px ui-sans-serif;fill:{SOFT}">'
                   f'{role} {pc(share, 0)}</text>')
    return (f'<svg viewBox="0 0 760 112" role="img" aria-label="Allokation nach Rolle">'
            f'{"".join(segs)}{"".join(labels)}{"".join(key)}</svg>')


# --- the sections ---------------------------------------------------------------------------------------

def _prose(d: Doc, q: dict, section: str) -> None:
    """The local model's paragraph for one section, if one was drafted and survived every check.

    **Rendered as a visibly separate draft, and that is a measured decision rather than caution.** Three live
    drafts on 20 August 2026: one clean, one rejected for inventing an income figure, and one accepted by every
    check while inventing a Ferienwohnung the household does not own and a conclusion about accumulating
    capital that appears in no fact. The number verifier cannot see either -- a category is not a number, and a
    wrong inference quotes only right figures.

    So the paragraph is offered to whoever writes the final headline, marked as unreviewed, and it never speaks
    in the report's own voice. `prose=false` is the default for exactly this reason.
    """
    slot = (q.get("prose") or {}).get(section)
    if not slot or not slot.get("text"):
        return
    d.parts.append(
        f'<div class="box draft"><span class="tag n">Entwurf des lokalen Modells · nicht geprüft</span>'
        f'<p>{e(slot["text"])}</p>'
        f'<p><small>{e(slot.get("model") or "lokales Modell")}. Dieser Absatz ist ein Vorschlag für die '
        f'Redaktion und keine Aussage dieses Berichts: jede Zahl darin ist gegen die Zahlen dieses '
        f'Abschnitts geprüft, eine erfundene Kategorie oder ein falscher Schluss aber nicht.</small></p>'
        f'</div>')


def _lede(q: dict) -> str:
    """The opening paragraph, assembled from what the household actually asked and what was found."""
    bits = []
    if q.get("main_question"):
        bits.append(f"Ihre Frage war: {e(q['main_question'])}")
    # **The stated goal, in the client's own words.** Carried in `goals_text` since the interview was
    # restructured and never rendered until a live submission showed what that costs: "Eigentum kaufen 2037
    # 2 Mio" appeared nowhere in the dossier built from it, while the report solved a different target.
    if q.get("goals_text"):
        bits.append(f"Als Ziel haben Sie genannt: {e(q['goals_text'])}")
    hard = [f for f in q["findings"] if f["urgency"] == "now"]
    if hard:
        bits.append(f"Vor der Antwort darauf stehen {len(hard)} Befunde, die jedes Jahr kosten, "
                    f"in dem sie offen bleiben. Sie stehen im Zeitplan am Ende, geordnet nach Dringlichkeit.")
    elif q["findings"]:
        bits.append(f"Die Rechnung ergab {len(q['findings'])} Befunde. Keiner davon verlangt eine "
                    f"Entscheidung in dieser Woche.")
    if q.get("plan") is None:
        bits.append("Die Optimierung ist für diesen Bericht nicht gelaufen; welche Aussage damit fehlt, "
                    "steht im Abschnitt zur gestellten Frage.")
    return " ".join(bits)



def _banner(q: dict) -> str:
    """The counters, at the top, before anything else is read.

    **Data attributes as well as text.** The interview page reads these back out of the rendered report to
    tell the client what an answer just changed, so the numbers travel with the document instead of needing a
    second request for the same computation. A figure that is on screen and also machine-readable cannot
    drift from itself.
    """
    s_ = q.get("asks_summary") or {}
    n = int(s_.get("open") or 0)
    largest = s_.get("largest") or {}
    amount = float(largest.get("amount") or 0.0)
    sections = int(q.get("_section_count") or 0)
    findings = len(q.get("findings") or [])
    actions = sum(len(g["items"]) for g in (q.get("schedule") or []))

    chips = [
        f'<span class="chip"><b>{sections}</b> Abschnitte</span>',
        f'<span class="chip"><b>{findings}</b> Befunde</span>',
        f'<span class="chip"><b>{actions}</b> Massnahmen im Zeitplan</span>',
    ]
    if n:
        chips.append(f'<span class="chip open"><b>{n}</b> offene Angabe{"n" if n != 1 else ""}</span>')
    else:
        chips.append('<span class="chip done">keine offenen Angaben</span>')

    tail = ""
    if amount > 0:
        # Phrased so the label follows a dash rather than a preposition. "im {label}" needs the label to
        # carry the right gender and case, and these labels are table headings -- "im Deckungslücke pro Jahr"
        # is what that produced. A sentence that stays correct whatever the label says is worth more than one
        # that reads slightly better for three of five labels and wrong for the other two.
        tail = (f'<p class="bnote">Die offenen Angaben können die Antwort noch um <strong>bis zu '
                f'{m(amount)}</strong> verschieben — gemessen an dieser Grösse: '
                f'<em>{e(largest.get("of"))}</em>. Der Abschnitt am Ende zeigt, welche Frage wie viel '
                f'bewegt.</p>')
    elif n:
        tail = ('<p class="bnote">Was noch offen ist, ändert <em>was</em> gerechnet werden kann und nicht '
                'nur wie viel. Der Abschnitt am Ende sagt, was.</p>')
    return (f'<div class="banner" data-open-asks="{n}" data-largest-swing="{amount:.0f}" '
            f'data-largest-of="{e(largest.get("of") or "")}" data-findings="{findings}" '
            f'data-actions="{actions}">'
            f'<div class="chips">{"".join(chips)}</div>{tail}</div>')

def _balance(d: Doc, q: dict) -> None:
    b = q["balance"]
    d.section("balance", "Wo Sie heute stehen")
    rows: list[tuple | None] = [
        ("Liquide Mittel", m(b["liquid"]), "frei verfügbar", "tot"),
        ("Liegenschaften, vermietet", m(b["let"]),
         f"Ertrag {pc(q['income_65']['rent_yield'], 0)}, nicht entnahmefähig") if b["let"] else None,
        ("Liegenschaft, selbst bewohnt", m(b["residence"]),
         ("kein Ertrag, nicht entnahmefähig", "neg")) if b["residence"] else None,
        ("Ferienobjekt", m(b["holiday"]), "negativer Nettoertrag") if b["holiday"] else None,
        ("Hypothek und übrige Schulden", (m(-b["debt"]), "neg"),
         f"Belehnung {pc(b['ltv'])}" if b["ltv"] else "") if b["debt"] else None,
        ("Pensionskasse", m(b["pillar2"]),
         f"ab {q['income_65']['reference_age']:.0f}") if b["pillar2"] else None,
        ("Säule 3a", (m(b["pillar3a"]), "" if b["pillar3a"] else "neg"),
         ("vorhanden" if b["pillar3a"] else ("nicht vorhanden", "neg"))),
        ("Nettovermögen", m(b["net_worth"]),
         f"entnahmefähig: {pc(b['drawable_share'])} des Gesamtvermögens", "tot"),
    ]
    d.table([("Position", False), ("CHF", True), ("Verfügbarkeit", False)], rows)
    d.p("Die Aufteilung ist keine Konvention dieses Berichts, sondern die des Modells: " +
        e(b["why_walled"]))
    if b["inside_liquid"]:
        d.p("Enthalten im liquiden Vermögen, weil täglich handelbar: " +
            e(", ".join(b["inside_liquid"])) + ".")
    if b["outside_model"]:
        items = "; ".join(f"<strong>{e(o['label'])} {m(o['amount'])}</strong> ({e(o['why'])})"
                          for o in b["outside_model"])
        d.box("w", f"{len(b['outside_model'])} Position(en) sind erfasst und in keiner Zeile",
              items + ".",
              f"Zusammen <strong>{m(b['outside_total'])} Franken</strong>, gegenüber einem "
              f"entnahmefähigen Vermögen von {m(b['drawable'])}. Was das Modell nicht führt, "
              f"kommt in keiner Rechnung dieses Berichts vor.",
              kind="warn")


def _cash_flow(d: Doc, q: dict) -> None:
    c = q["cash_flow"]
    d.section("cashflow", "Was der Haushalt erzeugt, und was davon übrig bleibt")
    rows: list[tuple | None] = [
        ("Erwerbseinkommen, brutto", m(c["gross"]), ""),
        ("Einkommen des Partners", m(c["partner_income"]), "") if c["partner_income"] else None,
        ("Nettomiete auf dem vermieteten Anteil", m(c["rent_net"]),
         pc(q["income_65"]["rent_yield"], 0)) if c["rent_net"] else None,
        ("Ausschüttung der Firma", m(c["company_income"]), "") if c["company_income"] else None,
        ("Übriges Einkommen", m(c["other_income"]), "") if c["other_income"] else None,
        ("Einkommenssteuer", (m(-c["income_tax"]), "neg"),
         f"Grenzsatz {pc(c['marginal_rate'])}" if c["marginal_rate"] else ""),
        ("Vermögenssteuer", (m(-c["wealth_tax"]), "neg"),
         pc(c["wealth_tax_rate"], 2)) if c["wealth_tax"] else None,
        ("Unterhalt, erhalten", m(c["alimony_received"]), "") if c.get("alimony_received") else None,
        ("Hypothekarzins", (m(-c["mortgage_interest"]), "neg"),
         pc(c["mortgage_rate"], 1)) if c["mortgage_interest"] else None,
        ("Unterhalt, bezahlt", (m(-c["alimony_paid"]), "neg"), "")
        if c.get("alimony_paid") else None,
        ("Lebenskosten", (m(-c["spending"]), "neg"), ""),
        # **The line the reader was asked for and should never have been.** It is derived from everything
        # above it, and asking for it invited a figure that contradicted the arithmetic -- measured at 30 000
        # stated against 18 626 computed on a real household.
        ("Frei verfügbar", (m(c["free"]), "" if c["free"] >= 0 else "neg"),
         "pro Jahr, vor jeder Sparentscheidung", "tot"),
        # Saving is not spending: these are destinations, and they sit BELOW the free line rather than
        # inside it. Counting an amortisation as a cost made the same franc an outflow or an investment
        # depending only on where it was sent.
        ("davon Amortisation, direkt", (m(-c["committed_amortisation"]), ""),
         "senkt die Schuld") if c.get("committed_amortisation") else None,
        ("davon Säule 3a", (m(-c["committed_pillar3a"]), ""),
         "gebunden bis 60") if c.get("committed_pillar3a") else None,
        ("Noch ohne Verwendung", (m(c["undirected"]), "" if c["undirected"] >= 0 else "neg"),
         "pro Jahr", "tot") if c.get("committed") else None,
    ]
    d.table([("Position", False), ("CHF", True), ("Anmerkung", False)], rows)

    if c["free_subject_alone"] is not None:
        d.box("n", "Dieselbe Rechnung ohne das Partnereinkommen",
              f"Trägt Ihr Einkommen allein sämtliche Kosten, bleiben "
              f"<strong>{m(c['free_subject_alone'])}</strong> statt {m(c['free'])}. Beide Zahlen "
              f"stehen hier, weil die ehrliche Spanne mehr trägt als die günstigere Zahl.")
    if c["unmarried_correction_applied"]:
        d.box("n", "Steuerkorrektur, unverheiratete Partnerschaft",
              f"Der Konverter setzt richtig keinen Splittingfaktor, rechnet das Partnereinkommen aber in "
              f"dieselbe Bemessungsgrundlage: das ergäbe {m(c['income_tax_joint_base'])}. Tatsächlich "
              f"wird getrennt veranlagt, also {m(c['income_tax_separate'])}. Dieser Bericht rechnet mit "
              f"der zweiten Zahl; die Differenz von {m(c['tax_overstatement'])} ist hier ausgewiesen, "
              f"damit sie gegen eine Steuererklärung geprüft werden kann.")
    if c["undirected"] is not None:
        # **Three cases, and the negative one is not a surplus.** A stated saving above the computed free cash
        # flow means the two figures disagree; calling that difference "heute keiner Verwendung zugeordnet"
        # printed a minus sign in front of a sentence about unassigned money, which is nonsense in the
        # direction that matters -- it reads as though there were something to assign.
        gap = -(c.get("stated_vs_free") or 0.0) if c.get("stated_saving") is not None else c["undirected"]
        if gap < -1.0:
            d.box("w", "Diese beiden Zahlen widersprechen sich",
                  f"Nach Ihren eigenen Angaben bleiben <strong>{m(c['free'])}</strong> pro Jahr frei. "
                  f"Gespart werden sollen {m(c['stated_saving'])} — das sind "
                  f"<strong>{m(abs(gap))} mehr</strong>, als die Rechnung findet.",
                  "Beides kann stimmen und je eine andere Angabe treffen: die Lebenskosten sind vielleicht "
                  "zu hoch angesetzt, oder ein Einkommensbestandteil fehlt, oder die Sparquote enthält "
                  "etwas, das oben schon als Kosten steht — eine Amortisation etwa. Der Bericht rechnet "
                  "mit der abgeleiteten Zahl, weil sie aus Einnahmen und Ausgaben folgt, und weist die "
                  "Differenz hier aus, damit Sie sie auflösen können.",
                  kind="warn")
        elif gap > 0.25 * max(1.0, c["stated_saving"] or 1.0):
            d.box("w", "Frei erzeugt gegen bewusst gerichtet",
                  f"Frei bleiben {m(c['free'])} pro Jahr. Gerichtet werden davon "
                  f"{m(c['stated_saving'])}. Die Differenz von <strong>{m(gap)}</strong> ist "
                  f"heute keiner Verwendung zugeordnet.", kind="warn")
        else:
            d.box("o", "Erzeugt und gerichtet stimmen überein",
                  f"Frei bleiben {m(c['free'])} pro Jahr, gerichtet werden {m(c['stated_saving'])}. "
                  f"Die beiden Zahlen liegen nah beieinander, was für die übrigen Angaben spricht.",
                  kind="ok")


def _income65(d: Doc, q: dict) -> None:
    f = q["income_65"]
    d.section("income65", f"Was ab {f['reference_age']:.0f} zufliesst, ohne dass etwas entschieden wird")
    rows: list[tuple | None] = [
        ("AHV, eigener Anspruch", m(f["ahv_own"]),
         f"Beitragsdauer {pc(f['ahv_record_share'], 0)}"),
        ("AHV, Haushalt nach Plafonierung", m(f["ahv_household"]),
         f"Plafond {m(f['ahv_couple_cap'])}") if f["ahv_household"] != f["ahv_own"] else None,
        ("Pensionskasse, Rente", m(f["pillar2_annuity"]),
         f"aus {m(f['pillar2_capital'])} zu {pc(f['conversion_rate'], 2)}"),
        ("Nettomiete", m(f["rent_net"]), "wenn die Liegenschaft gehalten wird")
        if f["rent_net"] else None,
        ("Ferienobjekt", (m(f["holiday_yield_net"]), "neg"), "negativer Nettoertrag")
        if f["holiday_yield_net"] else None,
        ("Zusammen", m(f["total"]), "pro Jahr", "tot"),
    ]
    d.table([("Zufluss", False), ("CHF pro Jahr", True), ("Grundlage", False)], rows)
    notes = []
    if f["ahv_is_regressive"]:
        notes.append(f"Die AHV ist regressiv: oberhalb eines Einkommens von "
                     f"{m(f['ahv_income_for_max'])} steigt die Rente nicht mehr. Ein Einkommen von "
                     f"{m(f['ahv_income_for_max'])} und eines von einer halben Million erhalten "
                     f"dieselbe Rente.")
    if f["ahv_record_share"] < 1.0:
        notes.append("Fehlende Beitragsjahre wirken dauerhaft. Höchstens die letzten fünf sind "
                     "nachzahlbar, und das ist eine Frage an die Ausgleichskasse.")
    if f["ahv_partner_gated"]:
        notes.append("Der Anspruch des Partners ist auf dessen eigenes Alter abgestellt. Ein jüngerer "
                     "Partner erscheint deshalb als Null, bis er selbst die Altersgrenze erreicht — "
                     "das ist kein Fehler der Rechnung.")
    notes.append(e(f["gate_note"]))
    d.box("n", "Zwei Eigenschaften dieser Zahlen", *notes)
    d.p(f"Der Umwandlungssatz von {pc(f['conversion_rate'], 2)} ist eine <strong>erklärte "
        f"Annahme</strong> und kein Modellparameter. Er wird über alle Dossiers gleich gehalten, damit "
        f"sie vergleichbar bleiben, und ein Pensionskassenausweis ersetzt ihn.")


def _plausibility(d: Doc, q: dict) -> None:
    """Answers that contradict each other, before any figure derived from them.

    **First, because a data error is not a finding.** Everything below this section is arithmetic on the
    answers; where two of them cannot both be true, the arithmetic is about a household that does not exist.
    The check never corrects an input -- it names both figures and asks, because the two usual causes of a
    contradiction need opposite corrections and only the reader knows which applies.
    """
    pl = q.get("plausibility") or {}
    checks = pl.get("checks") or []
    if not checks:
        return
    d.section("plausibility", "Angaben, die sich widersprechen")
    hard = [c for c in checks if c["severity"] == "impossible"]
    if hard:
        d.box("w", f"{len(hard)} Angabe{'n' if len(hard) > 1 else ''}, die so nicht stimmen "
                   f"{'können' if len(hard) > 1 else 'kann'}",
              "Zwei Zahlen können nicht gleichzeitig richtig sein. Solange das offen ist, rechnet dieser "
              "Bericht mit einer Annahme darüber, welche gilt — und jede Zahl danach hängt daran.",
              kind="warn")
    for c in checks:
        tag = "w" if c["severity"] == "impossible" else "o"
        d.box(tag, e(c["title"]),
              f"<strong>{e(c['conflict'])}</strong>",
              e(c["why"]),
              f"<em>{e(c['ask'])}</em>",
              kind="warn" if c["severity"] == "impossible" else "")
    if pl.get("unchecked"):
        d.p(f"<small>{len(pl['unchecked'])} Prüfung(en) konnten nicht laufen und sind damit weder "
            f"bestanden noch gescheitert.</small>")


def _paths(d: Doc, q: dict) -> None:
    """What each way forward demands per year, at a return of zero.

    **Before the gap and everything after it, because everything after it assumes an income.** A household
    whose salary is low because it is in education reads the rest of this report as a verdict on a number
    nobody expects it to keep; this section is where that number is allowed to change.
    """
    pl = q.get("paths") or {}
    runs = pl.get("paths") or []
    if not runs:
        # **A section that failed says so.** The exception was recorded in `error` and nothing rendered it,
        # so for every household without a stated stop age the paths simply were not there -- indistinguishable
        # from a household the section does not apply to.
        if pl.get("error"):
            d.section("paths", "Wege, und was sie pro Jahr verlangen")
            d.box("w", "Dieser Abschnitt konnte nicht gerechnet werden", e(str(pl["error"])),
                  "Das ist ein Fehler im Programm und keine Aussage über Ihre Lage. Alles andere in diesem "
                  "Bericht ist davon unabhängig.", kind="warn")
        return
    d.section("paths", "Wege, und was sie pro Jahr verlangen")
    d.p("Die erste Spalte rechnet <strong>ohne Rendite</strong>. Das ist der Überblick: Sie zeigt, was ein "
        "Ziel an reinem Sparen kostet — eine Zahl, die an Arbeitszeit, Ausbildung und Ausgaben hängt und "
        "nicht am Markt. Die weiteren Spalten rechnen <strong>mit Rendite</strong> und beantworten dann, "
        "was der Überblick offenlässt: ob die Ziele damit erreicht werden. Was schon ohne Rendite trägt, "
        "braucht den Markt nicht; was auch mit Rendite nicht trägt, ist keine Anlagefrage.")
    if not pl.get("anchored"):
        d.box("o", "Das Einkommensniveau ist eine Modellaussage",
              "Zum erwarteten Einkommen bei vollem Pensum nach der Ausbildung liegt keine Angabe vor. Die "
              "Form des Verlaufs stammt aus dem Modell, das Niveau ebenfalls — es ist damit keine Ihrer "
              "Angaben. Eine einzige Zahl von Ihnen ersetzt sie und macht jede Zeile unten zu Ihrer.")

    d.table([("Weg", False), ("Einkommen heute", True), ("mit 45", True),
             ("frei pro Jahr heute", True), ("Zufluss ab 65", True)],
            [(r["name"], m(r["income_now"]), m(r["income_at_45"]), m(r["free_now"]),
              m(r["flows_from_65"]["total"])) for r in runs])

    # One column per rate, each labelled with whose expectation it is: a return in a plan is a claim about
    # the future, and this report makes none of its own.
    rates = pl.get("rates") or [{"rate": "0.0000", "label": "ohne Rendite", "whose": ""}]
    for r in runs:
        if not r["goals"]:
            continue
        rows = []
        for g in r["goals"]:
            by = g.get("required_by_rate") or {}
            cells = [m(by.get(lab["rate"], g["required_saving"])) for lab in rates]
            best = min((by.get(lab["rate"], g["required_saving"]) for lab in rates),
                       default=g["required_saving"])
            verdict = ("trägt" if g["available_saving"] >= best
                       else f"{m(best - g['available_saving'])} zu wenig")
            rows.append((f"{g['description'][:52]} ({g['target_year']})", m(g["target"]),
                         *cells, m(g["available_saving"]), verdict))
        d.box("n", r["name"], e(r["note"]))
        d.table([("Ziel", False), ("Kapital dafür", True)]
                + [(f"nötig / Jahr, {lab['label']}", True) for lab in rates]
                + [("frei pro Jahr", True), ("Ergebnis", False)], rows)
    if len(rates) > 1:
        d.box("n", "Wessen Renditeerwartung in welcher Spalte steht",
              *[f"<strong>{e(lab['label'])}</strong> — {e(lab['whose'])}" for lab in rates])

    d.box("n", "Was dabei angenommen ist", *[e(a) for a in (pl.get("assumptions") or [])])


def _search(d: Doc, q: dict) -> None:
    """The smallest change that makes each goal hold, in two kinds that are never ranked against each other.

    **The refusal is the design.** Given a goal that does not hold there are two answers -- change what you do,
    or change what you want -- and ranking them would mean the machine deciding whether working more beats
    wanting less. G7 reserves that judgement for a person. So both are stated, with what each costs, and the
    choice stays where it belongs.
    """
    all_rates = q.get("search") or {}
    if not all_rates or "error" in all_rates:
        return
    labels = {lab["rate"]: lab for lab in ((q.get("paths") or {}).get("rates") or [])}
    # The zero column first: it is the baseline the household can check without believing anything.
    ordered = sorted(all_rates.items(), key=lambda kv: float(kv[0]))
    if not any((fr.get("goals") or []) for _, fr in ordered):
        return

    d.section("search", "Der kleinste Schritt, der ein Ziel trägt")
    d.p("Für jedes Ziel, das heute nicht trägt, sind zwei Antworten möglich: <strong>am eigenen Aufwand "
        "etwas ändern</strong> oder <strong>am Ziel selbst</strong>. Beide stehen hier nebeneinander und "
        "keine ist der anderen vorgezogen — ob mehr arbeiten besser ist als weniger wollen, ist keine "
        "Rechnung. Gesucht wird über Pensum, Weiterbildung, Netzwerk, Ausgaben, Erwerbsende sowie Zieljahr "
        "und Zielbetrag; «am kleinsten» heisst zuerst <em>wenige</em> Änderungen und dann <em>kleine</em>.")

    for rate_key, fr in ordered:
        lab = labels.get(rate_key, {"label": f"{float(rate_key):.1%} pro Jahr", "whose": ""})
        rows = []
        for g in fr.get("goals") or []:
            if g.get("refused"):
                rows.append((f"{g['description'][:46]} ({g['target_year']})", "—",
                             e(g["refused"][:80]), "—"))
                continue
            if g.get("holds_today"):
                rows.append((f"{g['description'][:46]} ({g['target_year']})",
                             "trägt bereits", "—", "—"))
                continue

            def cell(c):
                return (", ".join(c["moves"]) + f" → nötig {m(c['required'])}, frei {m(c['available'])}"
                        if c else "kein Weg gefunden")

            rows.append((f"{g['description'][:46]} ({g['target_year']})",
                         cell(g.get("cheapest_effort")),
                         cell(g.get("cheapest_goal_change")),
                         cell(g.get("cheapest_combination"))))
        if not rows:
            continue
        d.box("n", f"Gerechnet mit {lab['label']}" + (f" — {lab['whose']}" if lab.get("whose") else ""), "")
        d.table([("Ziel", False), ("nur eigener Aufwand", False),
                 ("nur am Ziel", False), ("beides zusammen", False)], rows)

    tried = sum(g.get("combinations_tried", 0) for _, fr in ordered for g in (fr.get("goals") or []))
    d.p(f"<small>{tried} Kombinationen geprüft. Die Suche bricht ab, sobald der günstigste Weg jeder Art "
        f"gefunden ist — unter dieser Ordnung ist der erste Treffer der günstigste.</small>")


def _gap(d: Doc, q: dict) -> None:
    g = q["gap"]
    d.section("gap", "Die Lücke, und das Kapital dahinter")
    # **The goals this report did not solve for, stated before the numbers that answer a different one.**
    # This section is the one that always renders, which is why the box lives here rather than beside the
    # required return: a household whose flows already cover its spending reads "Es gibt keine Lücke" and
    # returns early, and that is exactly the household for whom an uncomputed two-million goal matters most.
    for dg in (q.get("goals_deferred") or []):
        if not dg.get("description"):
            continue
        size = " · ".join(x for x in (
            m(float(dg["amount_chf"])) if dg.get("amount_chf") else "",
            f"bis {int(dg['target_year'])}" if dg.get("target_year") else "") if x)
        d.box("o", "Nicht gegen dieses Ziel gerechnet",
              f"«{e(str(dg['description']))}»" + (f" — {size}" if size else ""),
              e(str(dg.get("reason") or "")),
              "Was es <em>pro Jahr</em> verlangt, steht trotzdem im Bericht: im Abschnitt <em>Wege</em> und "
              "in <em>Der kleinste Schritt</em>. Denn was bis zu einem Datum zu sparen ist, folgt aus Betrag "
              "und Datum allein. Was der Kauf danach mit Ihrer Bilanz macht, folgt aus der Art — und genau "
              "das ist der Teil, den diese Rechnung ohne Ihre Festlegung nicht beantworten kann.")
    if g["gap"] <= 0:
        d.box("o", "Es gibt keine Lücke",
              f"Das Ausgabenziel von {m(g['target_spend'])} pro Jahr steht gegen Zuflüsse von "
              f"{m(g['flows'])}. Der Überschuss beträgt <strong>{m(-g['gap'])}</strong> pro Jahr. "
              f"Damit ist kein Kapital zu bilden, um dieses Ziel zu erreichen.", kind="ok")
        return
    d.table([("Position", False), ("CHF pro Jahr", True)],
            [("Ausgabenziel", m(g["target_spend"])),
             ("Zuflüsse", m(g["flows"])),
             ("Lücke", (m(g["gap"]), "neg"), "tot")])
    d.figure(_svg_capital(g),
             f"Kapitalbedarf, um {m(g['gap'])} pro Jahr zu decken. Der markierte Balken ist der Satz "
             f"des Modells ({pc(g['model_rate'])}); die beiden anderen zeigen, wie stark die Antwort "
             f"an dieser Annahme hängt.")
    if g["annuity_beats_withdrawal"]:
        d.p("Zur häufigen Frage, ob die Pensionskasse als Kapital zu nehmen ist: bei diesen Sätzen "
            "liefert die Rente mehr als eine Entnahme auf demselben Kapital. " +
            e(g["annuity_note"]))


def _plan(d: Doc, q: dict) -> None:
    facts = q.get("plan")
    d.section("plan", "Ihre Frage, gerechnet")
    if facts is None:
        # **Two different absences, and telling the reader the wrong one is worse than saying nothing.**
        # `solve_pending` means the optimisation is running right now and this section will replace itself
        # when it lands; without it, the optimisation was not run at all and will not be. The first is a
        # progress note, the second is a limitation of the report -- and the earlier version printed the
        # second in both cases, telling a client the calculation had not run while it was running.
        if q.get("solve_pending"):
            lo, hi, probes = solve_estimate(q)
            years = (q.get("required_return") or {}).get("years")
            # `id="solve-clock"` is updated once a second by the page that opened this report. **No script
            # runs in here**, deliberately: the dossier is a static document that has to survive being saved
            # to disk and emailed, and a counter that only ticks while the interview tab is open is honest --
            # when that tab is gone, nothing is computing for this reader any more.
            d.box("n", "Teil 2, wird hier ergänzt",
                  "Die Optimierung rechnet gerade. Sie beantwortet genau eine Frage: ob das gestellte Ziel "
                  "bei der verlangten Sicherheit hält, und welche Handlung dieser Periode dazu gehört. "
                  "Sobald sie fertig ist, erscheint das Ergebnis an dieser Stelle — Sie müssen nichts tun "
                  "und nichts neu laden.",
                  f'<strong>Läuft seit <span id="solve-clock">0:00</span></strong> · erwartet '
                  f'<strong>{lo} bis {hi} Minuten</strong>'
                  + (f' bei Ihrem Zeithorizont von {num(years, 0)} Jahren' if years else '')
                  + '. Die Schätzung stammt aus gemessenen Läufen und nicht aus einer Fortschrittsanzeige: '
                    'der Solver weiss selbst nicht, wie viele Iterationen er noch braucht.',
                  "Wenn Ihr Ziel bei der verlangten Sicherheit nicht hält, sucht das Modell anschliessend, "
                  "was stattdessen erreichbar ist — bis zu vier weitere vollständige Durchläufe. Dann kann "
                  "es ein Mehrfaches der oben genannten Zeit werden. Und wenn ein Durchlauf nicht "
                  "konvergiert, rechnet das Modell ihn mit einer neuen Zufallsstichprobe noch bis zu zweimal "
                  "neu, bevor es aufgibt: die Stichprobe ist willkürlich, und an einer ungünstigen scheitert "
                  "der Solver, an einer anderen nicht. Auch das kann die Zeit verdreifachen."
                  if probes else "",
                  "Alles andere in diesem Bericht steht schon: es ist Arithmetik auf Ihren Angaben und von "
                  "der Optimierung unabhängig.")
            return
        d.box("w", "Die Optimierung ist für diesen Bericht nicht gelaufen",
              "Damit fehlt genau eine Aussage: ob das gestellte Ziel bei der verlangten Sicherheit "
              "hält, und welche Handlung dieser Periode dazu gehört. Jede andere Zahl dieses Berichts "
              "ist Arithmetik auf Ihren Angaben und davon unabhängig.",
              "Der Grund ist Rechenzeit und keine Panne: gemessen sind rund 40 Minuten bei einem "
              "Zehnjahreshorizont und über 70 bei zwanzig Jahren.", kind="warn")
        return
    outcome = facts.get("outcome")
    if outcome == "goal_not_fundable":
        eps = facts.get("goal_epsilon") or 0
        tail = (f"im schlechtesten {pc(eps, 0)} der Verläufe" if eps
                else "im schlechten Rand der Verläufe")
        d.box("w", "Dieses Ziel liegt nicht innerhalb dieser Mittel",
              "Die Rechnung ist vollständig durchgelaufen. Das Ergebnis ist ein Befund und keine "
              "Panne: dieses Ziel ist mit diesen Mitteln und dieser Sicherheitsanforderung nicht "
              "erreichbar, auch dann nicht, wenn alles auf seine Finanzierung ausgerichtet wird.",
              kind="warn")
        d.table([("Grösse", False), ("Wert", True)],
                [(f"Fehlbetrag pro Jahr, {tail}", (m(facts.get("shortfall")), "neg"))
                 if facts.get("shortfall") is not None else None,
                 ("Erreicht in … der Verläufe, bestenfalls",
                  (pc(facts.get("p_goal"), 0), "neg")),
                 ("Von Ihnen verlangt", pc(facts.get("required_confidence"), 0)),
                 ("Zieljahr erreicht mit Alter", num(facts.get("deadline_age"), 0))])
        if facts.get("achievable_amount") is not None:
            d.box("n", "Was mit diesen Mitteln erreichbar ist",
                  f"Bei der von Ihnen verlangten Sicherheit tragen Ihre Mittel "
                  f"<strong>{m(facts['achievable_amount'])}</strong>, gemessen mit "
                  f"{pc(facts.get('achievable_p_goal'), 0)} Erfolgsanteil. Das ist eine "
                  f"<em>Messung</em> und kein Zielvorschlag: was jemand anstreben soll, ist keine "
                  f"Aussage, die dieses Modell treffen darf."
                  + (f" Der volle gestellte Betrag hält, wenn das Datum um "
                     f"{num(facts['achievable_full_deadline_years'], 0)} Jahre später liegt."
                     if facts.get("achievable_full_deadline_years") is not None else ""))
        return
    converged = facts.get("solver_converged", True)
    if not converged or not facts.get("publishable", True):
        # Which of the two failures this is. They read alike and mean different things: an unconverged solve
        # produces numbers nobody should believe, while a converged plan that fails out of sample produces
        # numbers that are correct and describe something that does not work.
        if not converged:
            d.box("w", "Die Optimierung hat keine belastbare Lösung gefunden",
                  "Der Solver ist nicht konvergiert, deshalb steht hier keine Zahl aus der Optimierung: "
                  "ein nicht konvergierter Fehlbetrag ist an einem echten Fall gemessen worden als um den "
                  "Faktor vier falsch. Eine unfertige Rechnung ist keine ungenaue Rechnung.", kind="warn")
        else:
            d.box("w", "Der Plan hält auf frischen Verläufen nicht",
                  f"Der Solver ist durchgelaufen und das Ergebnis ist belastbar gemessen: auf "
                  f"{int((facts.get('engine_settings') or {}).get('M_eval') or 400)} neuen Verläufen "
                  f"erreicht dieser Plan das Ziel in {pc(facts.get('p_goal'), 0)} der Fälle. Die Absicherung "
                  f"hielt auf den Verläufen, gegen die gerechnet wurde, und fällt auf ungesehenen um — die "
                  f"Zahlen beschreiben also jene Stichprobe und nicht diesen Haushalt. Eine Handlung wird "
                  f"daraus nicht abgeleitet.", kind="warn")

        # **And now the part that was missing: where it lands, and what moves it.** Refusing the optimiser's
        # figures is right. Refusing everything is not: the gap, the capital it implies, the required return at
        # three saving rates and the ranked levers are arithmetic on the intake and owe the solver nothing.
        gp = q.get("gap") or {}
        rr = q.get("required_return") or {}
        stated = (rr.get("rungs") or [{}])[0]
        better = rr.get("solved_by_saving")
        where = []
        if gp.get("gap", 0) > 0:
            # **The fallback used to be a literal 0.035, and it went stale on 25 August 2026** when M80
            # decision 5 moved the model to 3.0 %. A default rate here is the worst kind of stale number: it
            # names a withdrawal rate to the client in bold, keys the capital lookup by it, and looks sourced.
            # If the engine did not send its rate, the gap is still true and the capital is not known -- so the
            # gap is stated alone. If a number is not sourced, it does not appear.
            rate = gp.get("model_rate")
            capital = (gp.get("capital") or {}).get(f"{rate:.3f}") if rate is not None else None
            capital = capital or rr.get("target")
            if rate is not None and capital is not None:
                where.append(f"Die Deckungslücke beträgt <strong>{m(gp['gap'])}</strong> pro Jahr, und bei "
                             f"{pc(rate)} Entnahme entspricht das einem Kapital von "
                             f"<strong>{m(capital)}</strong>.")
            else:
                where.append(f"Die Deckungslücke beträgt <strong>{m(gp['gap'])}</strong> pro Jahr. Das dafür "
                             f"nötige Kapital steht hier nicht, weil der Entnahmesatz des Modells zu dieser "
                             f"Auswertung nicht mitgeliefert wurde.")
        if stated.get("outcome") == "ok" and stated.get("rate") is not None:
            where.append(f"Bei Ihrer heutigen Sparquote verlangt dieses Ziel "
                         f"<strong>{pc(stated['rate'], 2)}</strong> Rendite pro Jahr.")
        elif stated.get("outcome") == "unreachable":
            where.append("Bei Ihrer heutigen Sparquote ist dieses Ziel auf diesem Weg nicht erreichbar, "
                         "auch nicht mit einer sehr hohen Rendite.")
        if better and better.get("saving") is not None:
            where.append(f"Bei {m(better['saving'])} Sparen pro Jahr sinkt die Anforderung auf "
                         f"{pc(better.get('rate'), 2) if better.get('rate') is not None else 'null'} — "
                         f"das ist der Hebel, der hier am meisten bewegt.")
        if where:
            d.box("n", "Wo Ihre Lage landet, ohne die Optimierung",
                  " ".join(where),
                  "Diese Zahlen kommen nicht vom Solver. Sie sind Arithmetik auf Ihren Angaben und stehen "
                  "unabhängig davon, ob die Optimierung durchläuft — ebenso wie die Bilanz, der Cashflow, "
                  "die Zuflüsse ab 65, die Brücke, die Hebel und der Zeitplan. Was ohne die Optimierung "
                  "fehlt, ist genau eine Aussage: wie sicher das Ziel unter schlechten Verläufen hält.",
                  "<strong>Welche Grössen sich verstellen lassen.</strong> Der Betrag, das Datum, die "
                  "Sparquote und die Arbeitszeit. Der Abschnitt zu den Hebeln stellt sie in Franken "
                  "nebeneinander, damit die Wahl vergleichbar wird.")
        return
    a = facts.get("action") or {}
    # **"Von Ihnen verlangt" is only true if something was.** With the risk assessment declined the confidence
    # is measured and not required, and a row reading "verlangt: –" invites the reader to think they forgot to
    # answer something. So the row is dropped and the first row says the number is a measurement.
    required = facts.get("required_confidence")
    d.table([("Grösse", False), ("Wert", True)],
            [("Erreicht in … der Verläufe" if required is not None
              else "Gemessen: erreicht in … der Verläufe", pc(facts.get("p_goal"), 0)),
             ("Von Ihnen verlangt", pc(required, 0)) if required is not None else None,
             ("Bindende Bedingung", e(facts.get("binding_constraint") or "–")),
             ("Arbeitszeit im Plan", f"{num(facts.get('work_hours_per_week'), 1)} h / Woche"),
             ("Sparquote im Plan", pc(facts.get("saving_rate"))),
             ("Konsum im Plan", m(a.get("C"))) if a.get("C") is not None else None,
             ("Anteil risikobehaftet", pc(a.get("theta"))) if a.get("theta") is not None else None])
    if required is None:
        d.box("n", "Gemessen, nicht vorgegeben",
              "Sie haben keine Sicherheitsanforderung gesetzt, also hat das Modell keine erzwungen: das Ziel "
              "musste im Erwartungswert halten. Der Anteil oben ist anschliessend an frischen Verläufen "
              "gemessen worden — er sagt, wie belastbar dieser Plan ist, und nicht, ob er eine Vorgabe "
              "erfüllt.",
              "Wenn Sie eine Vorgabe setzen möchten, die das Modell erzwingen und im Zweifel ablehnen soll, "
              "ist das die Risikoprüfung mit verlangter Sicherheit. Sie rechnet deutlich länger, weil die "
              "Absicherung gegen schlechte Verläufe dann eine Bedingung der Optimierung ist und nicht "
              "erst eine Auswertung danach.")
    warnings = facts.get("warnings") or []
    if warnings:
        d.box("w" if any(w.get("severity") == "blocking" for w in warnings) else "n",
              "Was zu diesen Zahlen gehört",
              *[f"<strong>{e(w.get('severity'))}:</strong> {e(w.get('message'))}" for w in warnings],
              kind="warn" if any(w.get("severity") == "blocking" for w in warnings) else "")


def _bridge(d: Doc, q: dict) -> None:
    b = q.get("bridge")
    if not b:
        return
    d.section("bridge", f"Die Brücke von {b['stop_age']:.0f} bis {b['ahv_gated_at']:.0f}")
    d.p(f"Wer mit {b['stop_age']:.0f} aufhört, überbrückt {num(b['years'], 0)} Jahre ohne AHV und "
        f"ohne Pensionskasse: beide setzen erst mit {b['ahv_gated_at']:.0f} ein. Die Säule 3a ist ab "
        f"{b['pillar3a_age']:.0f} verfügbar.")
    d.table([("Position", False), ("CHF", True), ("Anmerkung", False)],
            [("Lebenskosten über die Brücke", m(b["spending"] * b["years"]), "ohne Schuldendienst"),
             ("Schuldendienst über die Brücke", m(b["mortgage_interest"] * b["years"]),
              "wird regelmässig vergessen") if b["mortgage_interest"] else None,
             ("Nettomiete über die Brücke", (m(-b["rent_offset"] * b["years"]), "pos"),
              "deckt einen Teil") if b["rent_offset"] else None,
             ("Bedarf", m(b["need"]), "", "tot"),
             ("Liquide Mittel mit " + f"{b['stop_age']:.0f}", m(b["liquid_at_stop"]),
              f"heute {m(b['liquid_today'])}, plus {m(b['saving_assumed'])} pro Jahr"),
             ("Säule 3a mit " + f"{b['stop_age']:.0f}", m(b["pillar3a_at_stop"]),
              f"verfügbar ab {b['pillar3a_age']:.0f}"),
             ("Verfügbar", m(b["available"]), "", "tot"),
             ("Fehlbetrag", (m(b["shortfall"]), "neg" if b["shortfall"] else "pos"), "", "tot")])
    if b["permanent_pension_cost"] > 0:
        d.box("w", "Die dauerhafte Seite der Frühpensionierung",
              e(b["permanent_note"]),
              f"Rente mit voller Beitragsdauer {m(b['pension_full'])}, mit Ausstieg bei "
              f"{b['stop_age']:.0f} noch {m(b['pension_early'])}. Die Differenz von "
              f"<strong>{m(b['permanent_pension_cost'])} pro Jahr</strong> gilt für den Rest des "
              f"Lebens, nicht nur für die Jahre der Brücke.", kind="warn")


def _health(d: Doc, q: dict) -> None:
    h = q["health"]
    if not h.get("hours") or h["hours"] <= h["threshold_hours"]:
        return
    d.section("health", "Die Arbeitszeit, als Finanzgrösse gerechnet")
    h = dict(h)
    h["age_start"] = q.get("age")
    h["age_end"] = (q.get("age") or 0) + h["horizon_years"]
    d.figure(_svg_health(h),
             f"Gesundheitsverlauf nach der Gleichung des Modells über {num(h['horizon_years'], 0)} "
             f"Jahre. Der Abbau ist bis {h['threshold_hours']:.0f} Wochenstunden konstant und steigt "
             f"darüber linear.")
    d.p(f"Sie arbeiten <strong>{h['hours']:.0f} Stunden pro Woche</strong>. Die Schwelle des Modells "
        f"liegt bei {h['threshold_hours']:.0f}. Darüber beschleunigt der Abbau linear, und bei "
        f"{h['hours']:.0f} Stunden ist er <strong>{num(h['multiple'])}-mal</strong> so hoch wie "
        f"darunter.")
    d.table([("Stunden / Woche", True), ("Abbau pro Jahr", True), ("gegenüber Basis", False)],
            [(f"{r['hours']:.0f}", num(r["decay"], 4), f"{num(r['multiple'])} ×")
             for r in h["ladder"]])
    d.p(f"Nach {num(h['horizon_years'], 0)} Jahren steht der Wert bei "
        f"<strong>{num(h['endpoint_own'])}</strong> gegen {num(h['endpoint_at_threshold'])} auf dem "
        f"Verlauf an der Schwelle. Die Ertragskraft skaliert im Modell mit der Gesundheit, und der "
        f"Exponent ist {num(h['c'], 0)} — ein Gesundheitsverhältnis ist damit ein Verhältnis der "
        f"Ertragskraft, also <strong>{pc(h['earning_power_ratio'], 0)}</strong> davon.")


def _children(d: Doc, q: dict) -> None:
    k = q.get("children")
    if not k:
        return
    d.section("children", "Kinder, als Kostenverlauf und nicht als Konstante")
    d.p(f"Erfasst sind {len(k['ages'])} Kind(er) im Alter von "
        f"{e(', '.join(f'{a:.0f}' for a in k['ages']))}. Das Modell lässt sie mit Ihnen älter werden, "
        f"also endet die Kostenreihe von selbst — mit "
        f"{num(k['end_age'], 0) if k['end_age'] else '21'} Jahren.")
    d.table([("Grösse", False), ("CHF pro Jahr", True), ("Grundlage", False)],
            [("Heute", m(k["cost_now"]), f"Aufteilung ab {num(k['split_age'], 0)} Jahren"),
             ("Bis zum Ende, kumuliert", m(k["total_remaining"]), f"über {len(k['path'])} Jahre"),
             ("Selbst angegeben", m(k["stated_total"]), "ersetzt den publizierten Wert")
             if k["stated_total"] else None])
    d.box("n", "Drei Eigenschaften dieser Zahlen", e(k["source"]), *[e(c) for c in k["caveats"]])


def _required_return(d: Doc, q: dict) -> None:
    rr = q["required_return"]
    if rr["target"] <= 0:
        return
    d.section("rr", "Die Rendite, die dieser Plan verlangt")
    d.p(f"Gerechnet gegen {e(rr['target_source'])}, über {num(rr['years'], 0)} Jahre, ausgehend von "
        f"{m(rr['liquid_today'])} liquiden Mitteln heute.")
    # **This section rests on today's income, and where the paths say otherwise it must say so.** Two numbers
    # answering different questions read as two answers to one: the required return here is what today's
    # salary demands, while the paths above show what each way forward demands at no return at all. On the
    # household this was found on, the first said 17,84 % a year and the second said the retirement goal is
    # covered at a full Pensum. Both are right about their own question.
    reachable = [g for r in ((q.get("paths") or {}).get("paths") or [])
                 for g in r["goals"] if g.get("reachable")]
    if reachable:
        d.box("o", "Diese Zahl gilt für Ihr heutiges Einkommen",
              "Sie beantwortet: Was müsste das Portfolio leisten, wenn Einkommen und Ausgaben bleiben, wie "
              "sie heute sind?",
              "Im Abschnitt <em>Wege</em> steht die andere Frage — und dort wird mindestens ein Ziel "
              "<strong>ohne jede Rendite</strong> getragen, sobald sich Pensum oder Ausbildung ändern. Wo "
              "das zutrifft, ist die Zahl hier keine Anforderung an den Markt, sondern der Preis dafür, "
              "alles beim Alten zu lassen.")
    rows = []
    for r in rr["rungs"]:
        if r["outcome"] == "covered":
            value = "ohne Rendite gedeckt"
        elif r["outcome"] == "unreachable":
            value = "nicht erreichbar"
        else:
            value = pc(r["rate"], 2)
        label = ("Ihre Sparquote" if r["multiple"] == 1.0
                 else f"{num(r['multiple'], 1)}-fache Sparquote")
        rows.append((label, m(r["saving"]), value))
    d.table([("Fall", False), ("Sparen pro Jahr", True), ("Verlangte Rendite", True)], rows)
    if rr["expected_return"] is not None:
        d.p(f"Ihre eigene Renditeerwartung liegt bei {pc(rr['expected_return'], 1)}, Ihre erklärte "
            f"Verlusttoleranz bei {pc(rr['loss_tolerance'], 0) if rr['loss_tolerance'] else '–'}"
            + (f", und in der letzten Krise haben Sie {e(rr['crisis_behaviour'])}."
               if rr["crisis_behaviour"] else "."))
    if rr["exceeds_expectation"] and rr["solved_by_saving"]:
        s = rr["solved_by_saving"]
        d.box("o", "Das ist keine Renditefrage",
              f"Bei Ihrer Sparquote verlangt der Plan {pc(rr['rungs'][0]['rate'], 2)}, mehr als Sie "
              f"selbst erwarten. Bei {m(s['saving'])} pro Jahr verlangt er "
              f"{pc(s['rate'], 2) if s['rate'] is not None else 'nichts mehr'} — also weniger, als "
              f"Sie erwarten. Die Grösse, die hier entscheidet, ist die Sparquote und nicht die "
              f"Anlage.", kind="ok")
    elif rr["unreachable_at_stated"]:
        d.box("w", "Auf diesem Weg nicht erreichbar",
              "Auch bei einer Rendite von 100 % pro Jahr wird dieser Betrag in dieser Zeit aus "
              "diesen Mitteln nicht gebildet. Was sich ändern lässt, ist der Betrag, das Datum oder "
              "die Mittel — nicht die Rendite.", kind="warn")


def _levers(d: Doc, q: dict) -> None:
    lv = q["levers"]
    if not lv:
        return
    d.section("levers", "Ihre Hebel, nach Wirkung geordnet")
    d.p("Vier Grössen, in derselben Einheit, damit sie vergleichbar sind. Die Einheit steht in jeder "
        "Zeile, weil sie nicht überall dieselbe ist: ein wiederkehrender Franken pro Jahr und eine "
        "Ertragskraft am Ende des Horizonts sind zwei verschiedene Dinge.")
    d.table([("Hebel", False), ("Wirkung", True), ("Einheit", False)],
            [(e(l["name"]),
              m(l["amount"]) if l.get("amount") is not None else pc(l.get("rate"), 2),
              e(l["unit_label"])) for l in lv])
    for l in lv:
        d.p(f"<strong>{e(l['name'])}.</strong> {e(l['note'])}")


def _findings(d: Doc, q: dict) -> None:
    fs = q["findings"]
    if not fs:
        return
    d.section("findings", "Was Ihre Zahlen ausserdem zeigen")
    d.p(f"{len(fs)} Befunde, jeder mit der Bedingung, die ihn ausgelöst hat. Die Bedingungen sind "
        f"nicht für diesen Fall gewählt: sie werden bei jedem Haushalt geprüft.")
    for f in fs:
        kind, tag = _SEV.get(f["severity"], ("", "n"))
        # **An action that is a request for a figure becomes a field the reader can fill in.** "Den Betrag
        # benennen und ihm eine Verwendung geben" is a question; making the reader carry it back into the
        # interview to answer it is friction with no purpose. Where a finding names no answerable field the
        # action stays prose, which is the honest form for a decision rather than a datum.
        slots = "".join(d.slot(field, "") for field in (f.get("answers") or []))
        d.box(tag, f["title"],
              f"<strong>Ausgelöst durch:</strong> {e(f['trigger'])}.",
              e(f["why"]),
              f"<strong>Was daraus folgt:</strong> {e(f['action'])}",
              *([slots] if slots.strip() else []),
              kind=kind)
    if q.get("findings_unchecked"):
        d.box("w", "Nicht geprüft",
              "Diese Prüfungen sind nicht gelaufen. Eine nicht gelaufene Prüfung ist nicht dasselbe "
              "wie eine bestandene, und deshalb steht sie hier: " +
              e("; ".join(q["findings_unchecked"])), kind="warn")


def _allocation(d: Doc, q: dict) -> None:
    a = q.get("allocation")
    if not a:
        return
    d.section("allocation", "Die Anlageallokation")
    if a["state"] in ("no_capital_and_nothing_drawable", "unavailable"):
        d.box("w", "Keine Allokation", e(a.get("why") or a.get("reason") or ""), kind="warn")
        return
    d.p(f"Das Mandat ist aus Ihrer eigenen Lage abgeleitet, nicht gewählt: der Zielwert kommt aus "
        f"{e(a.get('target_basis_label') or '')} — {m(a.get('target'))} über "
        f"{num(a.get('horizon_years'), 0)} Jahre, finanziert mit "
        f"{m(a.get('annual_contribution'))} pro Jahr.")
    # **Named where the allocation is stated, because the allocation is what it changes.** This section funded
    # itself from the stated saving while the required return solved at the computed one, and on a live
    # submission that put 17,50 % a year and 0,9 % feasible in the same report.
    if a.get("contribution_note"):
        d.box("o", "Womit hier gerechnet wird", e(a["contribution_note"]))

    # **When the mandate is derived from an unfundable goal, the weights are a symptom and not an answer.**
    # The derivation says so -- `feasible: False`, a negative buffer, and a note naming both rates -- and the
    # renderer used to print the table anyway. `architecture/manual-gameplan.html` states the rule this broke:
    # do not present a constraint-pinned weight as a view. Measured on a real household: the goal needed
    # 12.18 % a year against a best available 7.78 %, and every single position came back sitting on a bound.
    required = a.get("required_return")
    proxy = a.get("proxy_expected_return")
    buffer = a.get("buffer")
    if a.get("feasible") is False:
        gap = (f"Verlangt sind {pc(required, 2)} pro Jahr; das Beste, was dieses Mandat zulässt, sind "
               f"{pc(proxy, 2)}. " if required is not None and proxy is not None else "")
        d.box("w", "Diese Allokation beantwortet eine Frage, die keine Antwort hat",
              gap + ("Der Fehlbetrag am Ende des Horizonts beträgt "
                     f"<strong>{m(abs(buffer))}</strong>. " if buffer is not None and buffer < 0 else "")
              + "Das Mandat ist aus einem Ziel abgeleitet, das kein zulässiges Portfolio finanzieren kann.",
              "<strong>Was die Gewichte unten deshalb sind.</strong> Wenn die verlangte Rendite über dem "
              "Erreichbaren liegt, drückt der Optimierer jede Position an ihre Schranke: das Maximum dort, "
              "wo die Kurve am besten passt, das Minimum überall sonst. Das Ergebnis liest sich wie eine "
              "Überzeugung und ist eine Nebenbedingung. Es ist keine Anlagemeinung und darf nicht als "
              "solche gelesen werden.",
              "<strong>Was sich ändern lässt.</strong> Nicht die Allokation — der Betrag, das Datum oder "
              "die Mittel. Der Abschnitt zur nötigen Rendite zeigt, wie stark schon eine höhere Sparquote "
              "die Anforderung senkt.",
              kind="warn")
    elif required is not None and abs(required) < 5e-4:
        # **A required return of zero is a degenerate mandate, and its output reads as a view.** It happens on
        # the preservation basis: there is no shortfall, so the derivation asks the portfolio for nothing, and
        # the curve level is set to zero. An optimiser asked for nothing has no reason to take risk and fills
        # the protection sleeve. That is a consequence of the question, not an opinion about markets, and the
        # same trap as the infeasible case one branch up: the weights look like conviction either way.
        d.box("n", "Dieses Mandat verlangt vom Portfolio nichts",
              f"Es gibt keine Deckungslücke, also ist der Zielwert der Erhalt des heute entnahmefähigen "
              f"Vermögens und die abgeleitete Renditeanforderung <strong>{pc(required, 2)}</strong>. Das "
              f"Beste, was dieses Mandat zulässt, wären {pc(proxy, 2)} — gelesen als Obergrenze und nicht "
              f"als Prognose.",
              "Ein Optimierer, von dem nichts verlangt wird, hat keinen Grund, Risiko zu nehmen: das "
              "Gewicht wandert in die schützenden Bausteine. Das folgt aus der Fragestellung und ist keine "
              "Markteinschätzung. Wenn Sie eine Rendite anstreben, die über den Erhalt hinausgeht, ist das "
              "ein Ziel mit Betrag und Datum — und daraus würde ein anderes Mandat abgeleitet.")
    elif required is not None and proxy is not None:
        d.p(f"Verlangt sind <strong>{pc(required, 2)}</strong> pro Jahr. Das Beste, was dieses Mandat "
            f"zulässt, sind {pc(proxy, 2)} — gelesen als Obergrenze und nicht als Prognose.")
    if a["state"] == "mandate_only":
        d.box("w", "Das Mandat steht, die Gewichte nicht",
              f"Der Optimierer konnte nicht gerechnet werden: {e(a.get('optimiser_error') or '')}. "
              f"Die Schranken unten sind dennoch abgeleitet und gültig.", kind="warn")
    if a.get("allocation"):
        d.figure(_svg_allocation(a), "Gewichte nach Rolle. Die Reihenfolge ist die der Gewichte.")
        d.table([("Baustein", False), ("Gewicht", True), ("Rolle", False), ("Währung", False),
                 ("Liquidität", False)],
                [(e(r["name"]), pc(r["weight"]), e(de_category(r["role"])), e(r["currency"]),
                  e(de_category(r["liquidity"])))
                 for r in a["allocation"] if r["weight"] > 0.0005])
    bounds = a.get("bounds") or {}
    if bounds:
        rows = []
        for family, entries in bounds.items():
            for key, bd in entries.items():
                rows.append((e(de_family(family)), e(de_category(key)),
                             pc(bd.get("lower")), pc(bd.get("upper")),
                             e(de_source(bd.get("source")))))
        d.sub("Die Schranken, und woher jede kommt")
        d.table([("Familie", False), ("Kategorie", False), ("Unten", True), ("Oben", True),
                 ("Quelle", False)], rows)
    fit = a.get("fit") or {}
    if fit.get("weight_leverage") is not None:
        d.box("n", "Drei Dinge, die zu jeder Allokation gehören",
              f"<strong>Sie ist schrankengetrieben.</strong> Die Gewichte beeinflussen "
              f"{pc(fit['weight_leverage'], 2)} des Zielniveaus. Die Struktur kommt damit aus den "
              f"Schranken; die Kurvenanpassung entscheidet Gleichstände.",
              (f"<strong>Was sie ausschliesst.</strong> Ohne Gewicht bleiben: "
               f"{e(', '.join(b['name'] for b in a.get('excluded', [])))}."
               if a.get("excluded") else
               "<strong>Was sie ausschliesst.</strong> Jeder Baustein hat ein Gewicht erhalten."),
              f"<strong>Der Datenstand.</strong> {e(a.get('provenance') or '')}")
        d.p(e(a.get("proxy_note") or ""))
        notes = a.get("notes") or []
        if notes:
            d.sub("Wie das Mandat zustande kam")
            d.parts.append("<ul>" + "".join(f"<li><small>{e(n)}</small></li>" for n in notes[:4])
                           + "</ul>")



def _pending(d: Doc, q: dict) -> None:
    """The questions the client deliberately left open, offered back rather than quietly inherited.

    **Skipping a question is a legitimate answer and this is not a reproach.** The interview says every field
    may be left blank, and a client with the pension certificate in another drawer is right to move on. What
    is not acceptable is for that decision to become permanent by default: the report inherits the gap, uses a
    model value in its place, and nothing ever asks again.

    Each entry is a slot rather than a rendered question. The wording, the input type, the unit and the bounds
    all live in the interview's own question list, and copying them here would be a second copy that drifts --
    this file would have to be edited every time a question was reworded. So the report marks the field and the
    page fills it in, which is the same division the asks section uses.
    """
    pending = [str(x) for x in (q.get("pending_fields") or [])]
    if not pending:
        return
    d.section("pending", "Was Sie bewusst offen gelassen haben")
    d.p(f"{len(pending)} Angabe{'n' if len(pending) != 1 else ''}. Das war zulässig und bleibt es — hier "
        f"stehen sie, weil eine offen gelassene Frage sonst durch Nichtstun zur endgültigen Antwort wird. "
        f"Was an ihnen hängt, steht in der Tabelle der Annahmen weiter unten.")
    for field in pending:
        d.parts.append('<div class="box">'
                       + d.slot(field, f'<b>{e(field)}</b> — die Frage dazu steht im Fragebogen.')
                       + '</div>')

def _limits(d: Doc, q: dict) -> None:
    d.section("limits", "Was dieses Dossier nicht sagen kann")
    d.parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in q["limits"]) + "</ul>")
    if q.get("assumptions"):
        d.sub("Jede Zahl, die nicht von Ihnen kam")
        # The last column is a SLOT where the interview has a question that would replace the assumption, and
        # plain text where it does not. An entnahmesatz is not something a household supplies, and offering an
        # input for it would invite an answer nobody should give.
        rows = []
        for a in q["assumptions"]:
            field = a.get("field")
            rows.append((e(a["what"]), e(a["value"]), e(a["source"]),
                         d.slot(field, e(a["replaced_by"]))))
        d.table([("Grösse", False), ("Verwendet", False), ("Herkunft", False),
                 ("Ersetzt durch", False)], rows)


def _schedule(d: Doc, q: dict) -> None:
    sch = q["schedule"]
    if not sch:
        return
    d.section("schedule", "Der Zeitplan")
    d.p("Jeder Punkt hier steht in einem Befund weiter oben, und die Reihenfolge ist die Dringlichkeit "
        "dieses Befundes. Der Plan ist damit nachprüfbar: nichts steht hier, was nicht oben "
        "hergeleitet ist.")
    # The group label once per group, not once per item. It repeated on every row, which made a schedule of
    # nine actions read as nine separate deadlines that happen to share a name.
    n = d.index.get("findings")
    items = []
    for group in sch:
        items.append(f'<div class="it"><div class="yr">{e(group["label"])}</div>'
                     f'<div class="hd">{e(group["items"][0]["title"])}</div>'
                     f'<p>{e(group["items"][0]["action"])}'
                     + (f' <small>Abschnitt {n:02d}.</small>' if n else "") + "</p></div>")
        for it in group["items"][1:]:
            items.append(f'<div class="it"><div class="hd">{e(it["title"])}</div>'
                         f'<p>{e(it["action"])}</p></div>')
    d.parts.append(f'<div class="tl">{"".join(items)}</div>')



def _asks(d: Doc, q: dict) -> None:
    """What is still missing, ranked by the measured effect of knowing it.

    **The effect is measured on this household, not looked up.** Each unknown was probed by recomputing the
    report at a plausible low and high, and the figure shown is the spread that produced in something the
    client reads. So "why are you asking me this" has a franc answer, and the order is this household's own
    order rather than the manual's general one.

    The controls are inert HTML on purpose: no script runs inside the dossier, so a saved copy of this page
    still shows the questions and simply cannot submit them. The interview page wires them when the report is
    open inside it, which is the only context in which submitting means anything.
    """
    asks = q.get("asks_ranked") or []
    if not asks:
        return
    d.section("asks", "Was noch fehlt, und was es ändern würde")
    d.p("Diese Angaben fehlen oder sind gesetzt. Die Spalte <em>Wirkung</em> ist gemessen und nicht "
        "geschätzt: der Bericht wurde für jede Zeile zweimal neu gerechnet, einmal mit einem tiefen und "
        "einmal mit einem hohen plausiblen Wert, und dort steht der Unterschied, den das in einer Zahl "
        "macht, die Sie oben lesen. Die Reihenfolge ist damit die Ihres Haushalts.")

    # Scaled to the largest ask, so the bar shows the ORDER between rows rather than an absolute quantity.
    # Three numbers in a column are read one at a time; three bars are read at once, and the whole value of
    # this section is that the client sees which question matters most.
    top = max([a["impact"] or 0.0 for a in asks if a["measured"]] or [1.0]) or 1.0
    rows = []
    for a in asks:
        if a["measured"]:
            w = max(2.0, 100.0 * (a["impact"] or 0.0) / top)
            effect = (f'<span class="barwrap"><span class="bar" style="width:{w:.0f}%"></span></span>'
                      f'{m(a["impact"])} <small>{e(a["impact_of"])}</small>')
        else:
            effect = "<small>ändert, <em>was</em> gerechnet wird</small>"
        rows.append((e(a["question"]), effect, e(a["how"])))
    d.table([("Frage", False), ("Wirkung", True), ("Woher die Antwort kommt", False)], rows)

    for a in asks:
        # **Through `d.slot`, like every other control in the document.** This section built its own inputs at
        # first, which meant the guard against offering a field twice did not cover it -- and `mortgage_rate`
        # and `stop_work_age` were duly offered twice, once by a finding and once here. One mechanism, one
        # guard. Fields the findings already offered get a pointer instead of a second input.
        control = d.slot(a.get("field"), "Diese Frage") if a.get("field") else ""
        if control and not control.startswith("<span"):
            control = f'<p><small>{control}</small></p>'   # the "already offered" pointer
        probe = ""
        if a["measured"] and a.get("probe_low") is not None:
            probe = (f' <small>Gemessen zwischen {num(a["probe_low"], 2)} und '
                     f'{num(a["probe_high"], 2)}; beide Werte sind Sonden und stehen in keiner '
                     f'Rechnung dieses Berichts.</small>')
        d.box("n", a["question"], e(a["why"]) + probe, control)

#: The order sections are attempted in, each with the prose slot it may carry. A section that has nothing to
#: say returns without emitting, so the numbering closes over whatever is actually present. The slot name is
#: paired with the function HERE rather than called inside each one: eight call sites is eight places to forget
#: it, and a section that silently loses its draft looks exactly like a model that refused.
SECTIONS: tuple[tuple[Any, str], ...] = (
    (_plausibility, ""),   # first: a contradiction in the inputs invalidates everything after it
    (_balance, "balance"),
    (_cash_flow, "cash_flow"),
    (_paths, ""),          # before the gap: everything after it assumes an income path
    (_search, ""),         # and directly after: what the paths table shows failing, this one prices

    (_income65, "income_65"),
    (_gap, "gap"),
    (_plan, ""),           # the M79 wording is the compliance boundary; no model near it
    (_bridge, "bridge"),
    (_health, "health"),
    (_children, ""),
    (_required_return, ""),
    (_levers, "levers"),
    (_findings, ""),
    (_allocation, ""),
    (_asks, ""),
    (_pending, ""),
    (_limits, ""),
    (_schedule, ""),
)


def _open_page(d: Doc, q: dict) -> None:
    """The open items and nothing else.

    **No figures here, and that is the whole point of the stage.** A number printed beside the question that
    determines it is a number the reader remembers; the answer then changes it, and the report has already
    made its first impression with the wrong one. So this page states what is open, why it matters, and what
    would settle it.
    """
    gate = q.get("gate") or {}
    blocking = gate.get("blocking") or []
    optional = gate.get("optional") or []

    d.section("open", "Bevor gerechnet wird")
    d.p(f"Ihre Angaben sind fast vollständig. <strong>{len(blocking)} "
        f"{'Punkt' if len(blocking) == 1 else 'Punkte'}</strong> "
        f"{'ist' if len(blocking) == 1 else 'sind'} noch offen — und zwar solche, von denen Zahlen abhängen, "
        f"die sonst im Bericht stünden. Deshalb steht hier noch kein Bericht: eine Zahl, die neben der Frage "
        f"steht, die sie bestimmt, bleibt im Kopf, auch wenn die Antwort sie danach verschiebt.")

    for i, item in enumerate(blocking, start=1):
        d.box("w", f"{i:02d} · {e(item['title'])}",
              f"<strong>{e(item['detail'])}</strong>" if item.get("detail") else "",
              e(item.get("why") or ""),
              (f"<em>{e(item['question'])}</em>" if item.get("question") else "")
              + "".join(d.slot(f, "") for f in (item.get("fields") or [])),
              kind="warn")

    if optional:
        d.p("Die folgenden Punkte <strong>halten den Bericht nicht auf</strong>. Sie würden ihn genauer "
            "machen, und Sie können sie jederzeit nachtragen.")
        for item in optional:
            d.box("n", e(item["title"]),
                  f"<strong>{e(item['detail'])}</strong>" if item.get("detail") else "",
                  e(item.get("why") or ""),
                  (f"<em>{e(item['question'])}</em>" if item.get("question") else "")
                  + "".join(d.slot(f, "") for f in (item.get("fields") or [])))

    d.box("n", "Was danach kommt",
          "Sobald die offenen Punkte beantwortet sind, erscheint hier der vollständige Bericht: Bilanz, "
          "Cashflow, Wege, der kleinste Schritt je Ziel, Hebel, Befunde und Zeitplan. Sie müssen nichts neu "
          "laden — jede Antwort rechnet die Seite neu, und beim letzten offenen Punkt steht der Bericht da.",
          "Die Risikoanalyse ist der Schritt danach und wird eigens gestartet. Sie beantwortet eine einzige "
          "Frage — ob das Ziel bei der verlangten Sicherheit hält — und braucht dafür Rechenzeit in der "
          "Grössenordnung einer Stunde.")

    # **Der Weg vorbei am Tor, und warum er hier steht statt in einer Fussnote.** Eine Zahl, die jemand
    # schlicht noch nicht kennt, darf ihn nicht aus seiner eigenen Standortbestimmung aussperren. Der Bericht
    # trägt die offenen Punkte dann oben als Vorbehalt — ein Zwischenstand, kein Befund.
    d.box("n", "Wenn Sie eine Angabe nicht haben",
          "Dann rechnet der Bericht trotzdem, und die offenen Punkte stehen oben darüber. Jede Zahl darin "
          "hängt dann an einer Annahme darüber, wie sie ausgehen.",
          '<button type="button" class="askgo" data-force-report="1">Trotzdem rechnen</button>')


def render(q: dict, *, title: str = "andersCH · Standortbestimmung und Zeitplan",
           force: bool = False) -> str:
    """The dossier for the stage this household is in, as one self-contained HTML page.

    `force` renders the report even while items are open, with them listed above it: a household whose figure
    genuinely is not known yet must not be locked out of its own Standortbestimmung.
    """
    gate = q.get("gate") or {}
    if gate.get("stage") == "open" and not force:
        d = Doc()
        _open_page(d, q)
        return _page(d, q, title=title, stage="open")

    d = Doc()
    if gate.get("blocking"):
        # Forced past the gate. What stayed open is stated once, at the top, in the reader's own terms.
        d.box("w", f"{len(gate['blocking'])} offene Punkte, trotzdem gerechnet",
              "; ".join(e(b["title"]) for b in gate["blocking"]),
              "Jede Zahl unten hängt an einer Annahme darüber, wie diese Punkte ausgehen. Der Bericht ist "
              "damit ein Zwischenstand und kein Befund.", kind="warn")
    for section, slot in SECTIONS:
        before = len(d.parts)
        section(d, q)
        # Only where the section actually emitted something: a draft under a heading that is not there would
        # render as a floating box belonging to whatever came before it.
        if slot and len(d.parts) > before:
            _prose(d, q, slot)

    return _page(d, q, title=title, stage="report")


def _page(d: Doc, q: dict, *, title: str, stage: str) -> str:
    """The shell both stages share: one identity, one provenance line, a different headline.

    Extracted when the open stage arrived. Two shells would have meant two places where the provenance is
    written, and a page whose footer disagrees with the report's is a page a reader cannot check.
    """
    # The banner counts the sections, so it is built after the body exists. A count taken before would be
    # zero, and a report announcing "0 Abschnitte" above eleven of them is the kind of small wrongness that
    # makes a reader distrust the large numbers too.
    q = {**q, "_section_count": d.n}
    where = " \u00b7 ".join(x for x in (q.get("canton"),
                                    f"Jahrgang {q['birth_year']:.0f}" if q.get("birth_year") else None,
                                    f"Alter {q['age']:.0f}" if q.get("age") else None) if x)
    provenance = (f"Erhebung {e(q.get('collected') or '\u2013')} \u00b7 Schema "
                  f"{e(q.get('submission_schema') or '\u2013')} \u00b7 Auswertung {e(q.get('schema'))}")
    if stage == "open":
        head = "Was noch offen ist"
        lede = ("Diese Seite ist noch kein Bericht. Sie listet, was beantwortet sein muss, damit die Zahlen "
                "danach etwas bedeuten \u2014 und sonst nichts.")
        banner = ""
        foot = (f"{provenance}. Kein Befund: die Auswertung ist noch nicht gelaufen. Was hier steht, sind "
                f"Ihre eigenen Angaben und die Fragen, die sie aufwerfen.")
    else:
        conv = q["income_65"]["conversion_rate"]
        head = "Standortbestimmung und Zeitplan"
        lede = _lede(q)
        banner = _banner(q)
        foot = (f"{provenance} \u00b7 Umwandlungssatz {pc(conv, 2)} als erkl\u00e4rte Annahme "
                f"\u00b7 Entnahmesatz des Modells {pc(q['gap']['model_rate'])}. "
                f"Dieser Bericht ist ein Befund und keine Empfehlung: eine Empfehlung verlangt einen "
                f"benannten Kurator und einen Entscheidungsnachweis.")
    return (
        f'<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>{e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<div class="w">\n'
        f'<div class="ey">andersCH \u00b7 Standortbestimmung{" \u00b7 " + e(where) if where else ""}</div>\n'
        f'<h1>{e(head)}</h1>\n'
        f'<p class="lede">{lede}</p>\n{banner}\n<div class="rule"></div>\n'
        f'{d.html()}\n<div class="foot">{foot}</div>\n</div>\n</body>\n</html>\n'
    )


def render_fragment(q: dict, name: str) -> str:
    """One section of the dossier, ready to replace the same section in an already-open report.

    **Rendered by building the whole page and cutting one section out of it, which is deliberate.** The
    alternative -- running that section's function alone -- would number it 01 whatever its real position, and
    a plan section that arrives calling itself 01 in a report where it is 05 is worse than no plan section.
    Building the whole document costs milliseconds and cannot disagree with the page it is being spliced into.

    Returns an empty string when the section is not present for this household, which is a real answer: a
    household with no early stop has no bridge section, and the caller must not invent one.
    """
    page = render(q)
    m = re.search(rf'<section id="sec-{re.escape(name)}".*?</section>', page, re.S)
    return m.group(0) if m else ""


def main(argv: list[str] | None = None) -> int:
    """`python desktop/dossier.py --in quantities.json --out dossier.html`."""
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Render a gameplan dossier from its quantities.")
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile")
    args = ap.parse_args(argv)
    q = json.loads(Path(args.infile).read_text(encoding="utf-8-sig"))
    page = render(q)
    if args.outfile:
        Path(args.outfile).write_text(page, encoding="utf-8")
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
