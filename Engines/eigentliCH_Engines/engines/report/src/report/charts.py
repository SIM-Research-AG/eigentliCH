"""The report's charts as inline SVG (REP-34, REP-40, REP-41). Pure functions, no I/O.

* (1) **Weights**: horizontal bars, by role (section ``roles``) and by building block (section ``positions``),
  from the pcp Allocation's facts.
* (2) **Target against reached per state** (section ``fit``): the 25 market states from crisis to boom, the
  Mandate's target return and the return the weights reach, and the line of zero return; on the Allocation's
  basis (REP-28).
* (3) **The fan** (section ``outlook``): lbsim's p05 to p95 and p25 to p75 bands of the designated goal's
  measure up to its date, the median path, and the goal line; the line is dashed when the goal is set in the other
  basis and converted (LBSIM-09).
* (4) **The life balance sheet** (section ``life_sheet``, REP-40): the assets by vessel and human capital against
  the liabilities and the goals' claims, and net worth, on one CHF scale without an axis.
* (5) **The four capitals** (section ``capitals``, REP-41): wealth in CHF as a stated figure, and per adult
  expertise, network and health each on its own track with words at its ends; and, from lbsim's ``capitals``, how
  the principal's three develop over the years (median and the p10 to p90 band). A capital is never on a money axis.

**The page's figure rule holds inside a chart.** No tick labels and no axis numbers: every printed value is a
``<tspan data-fact="...">`` carrying a fact's display, labelled directly; the ends of an axis are words ("Krise",
"Boom", "heute") or a date fact. ``<title>`` and ``<desc>`` say what the chart shows in words. No ``<script>``, no
external reference, no web font, no ``xmlns`` (an inline SVG in HTML needs none, and the page carries no ``http``
inside an SVG); a ``viewBox`` so it scales; the house colours of the dossiers' stylesheet.
"""

from __future__ import annotations

import html
from typing import Optional, Sequence

from .contracts import Fact

INK = "#1A1740"
SOFT = "#5d4591"
LINE = "#ECE8F4"
MUTED = "#BDB5D6"
ACC = "#A059C1"
BLUE = "#8890e7"
GOAL = "#C8662E"
FONT = "ui-sans-serif,system-ui,sans-serif"

WIDTH = 640


def _e(x: object) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _f(x: float) -> str:
    """A coordinate: attributes are not printed text, but short and stable."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def fact_text(f: Fact) -> str:
    """A printed value inside a chart: the fact's display, traceable by its id."""
    return f'<tspan data-fact="{_e(f.fact_id)}">{_e(f.display)}</tspan>'


def _svg(key: str, height: float, title: str, desc: str, body: str, caption: str = "") -> str:
    cap = f"<figcaption>{_e(caption)}</figcaption>" if caption else ""
    return (f'<figure class="chart" data-chart="{_e(key)}">'
            f'<svg viewBox="0 0 {WIDTH} {_f(height)}" role="img" aria-label="{_e(title)}" '
            f'font-family="{FONT}" font-size="12">'
            f"<title>{_e(title)}</title><desc>{_e(desc)}</desc>{body}</svg>{cap}</figure>")


# ---------------------------------------------------------------------------
# (1) Weights
# ---------------------------------------------------------------------------

def weights(key: str, rows: Sequence[tuple[str, Fact]], title: str, desc: str, caption: str = "") -> str:
    """Horizontal bars: ``rows`` are ``(name, weight fact)``, the weight a share in ``fact.value``."""
    if not rows:
        return ""
    label_w, bar_w, row_h, top = 210.0, 330.0, 24.0, 8.0
    top_value = max([float(f.value or 0.0) for _, f in rows] + [1e-9])
    parts = []
    for n, (name, f) in enumerate(rows):
        y = top + n * row_h
        share = max(0.0, float(f.value or 0.0))
        length = bar_w * share / top_value
        parts.append(f'<text x="{_f(label_w - 8)}" y="{_f(y + 15)}" text-anchor="end" fill="{INK}">{_e(name)}</text>')
        if length > 0:
            parts.append(f'<rect x="{_f(label_w)}" y="{_f(y + 5)}" width="{_f(max(length, 2.0))}" height="14" rx="3" '
                         f'fill="{ACC}"/>')
        parts.append(f'<text x="{_f(label_w + length + 6)}" y="{_f(y + 15)}" fill="{INK}">{fact_text(f)}</text>')
    height = top + len(rows) * row_h + 8
    base = f'<line x1="{_f(label_w)}" y1="{_f(top)}" x2="{_f(label_w)}" y2="{_f(height - 8)}" stroke="{MUTED}"/>'
    return _svg(key, height, title, desc, base + "".join(parts), caption)


# ---------------------------------------------------------------------------
# (2) Target against reached per state
# ---------------------------------------------------------------------------

def _spread(ys: list[float], gap: float) -> list[float]:
    """End labels nudged apart so that none overlaps its neighbour."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def target_vs_reached(target: Sequence[float], achieved: Sequence[float], words: dict[str, str], title: str,
                      desc: str, caption: str) -> str:
    """Two lines over the states (index 0 the crisis, the last the boom) and the line of zero return. No value is
    printed: the lines are labelled directly, the axis ends in words."""
    if not target or len(target) != len(achieved):
        return ""
    left, right, top, bottom, height = 90.0, 120.0, 14.0, 34.0, 230.0
    lo = min(min(target), min(achieved), 0.0)
    hi = max(max(target), max(achieved), 0.0)
    span = (hi - lo) or 1.0
    lo, hi = lo - 0.06 * span, hi + 0.06 * span
    plot_w, plot_h = WIDTH - left - right, height - top - bottom

    def x(i: int) -> float:
        return left + plot_w * i / (len(target) - 1)

    def y(v: float) -> float:
        return top + plot_h * (hi - v) / (hi - lo)

    def poly(vs: Sequence[float]) -> str:
        return " ".join(f"{_f(x(i))},{_f(y(v))}" for i, v in enumerate(vs))

    zero = y(0.0)
    parts = [f'<line x1="{_f(left)}" y1="{_f(zero)}" x2="{_f(left + plot_w)}" y2="{_f(zero)}" stroke="{MUTED}" '
             f'stroke-dasharray="3 3"/>',
             f'<text x="{_f(left - 8)}" y="{_f(zero + 4)}" text-anchor="end" fill="{SOFT}">{_e(words["zero"])}</text>',
             f'<polyline points="{poly(target)}" fill="none" stroke="{GOAL}" stroke-width="2"/>',
             f'<polyline points="{poly(achieved)}" fill="none" stroke="{SOFT}" stroke-width="2"/>']
    for i, v in enumerate(achieved):
        parts.append(f'<circle cx="{_f(x(i))}" cy="{_f(y(v))}" r="2.5" fill="{SOFT}"/>')
    ends = _spread([y(target[-1]), y(achieved[-1])], 14.0)
    parts.append(f'<text x="{_f(left + plot_w + 8)}" y="{_f(ends[0] + 4)}" fill="{INK}">{_e(words["target"])}</text>')
    parts.append(f'<text x="{_f(left + plot_w + 8)}" y="{_f(ends[1] + 4)}" fill="{INK}">{_e(words["achieved"])}</text>')
    parts.append(f'<text x="{_f(left)}" y="{_f(height - 12)}" fill="{SOFT}">{_e(words["crisis"])}</text>')
    parts.append(f'<text x="{_f(left + plot_w)}" y="{_f(height - 12)}" text-anchor="end" fill="{SOFT}">'
                 f'{_e(words["boom"])}</text>')
    return _svg("fit", height, title, desc, "".join(parts), caption)


# ---------------------------------------------------------------------------
# (3) The fan
# ---------------------------------------------------------------------------

def fan(bands: dict[str, Sequence[float]], ends: dict[str, Fact], goal_value: Optional[float],
        goal_fact: Optional[Fact], chance_fact: Optional[Fact], date_fact: Optional[Fact], dashed: bool,
        words: dict[str, str], title: str, desc: str, caption: str) -> str:
    """``bands`` holds p05, p25, p50, p75, p95 over the years shown (index 0 today); ``ends`` the p10, p50 and p90
    facts at the last year, printed at the right edge. The goal line is horizontal at ``goal_value``, labelled with
    its target and chance facts; dashed when converted from the other basis."""
    n = len(bands["p50"])
    if n < 2:
        return ""
    left, right, top, bottom, height = 16.0, 190.0, 30.0, 30.0, 290.0
    hi = max(list(bands["p95"]) + ([goal_value] if goal_value is not None else [])) * 1.06
    lo = min(0.0, min(bands["p05"]))
    span = (hi - lo) or 1.0
    plot_w, plot_h = WIDTH - left - right, height - top - bottom

    def x(i: int) -> float:
        return left + plot_w * i / (n - 1)

    def y(v: float) -> float:
        return top + plot_h * (hi - v) / span

    def area(lower: Sequence[float], upper: Sequence[float]) -> str:
        pts = [f"{_f(x(i))},{_f(y(v))}" for i, v in enumerate(upper)]
        pts += [f"{_f(x(i))},{_f(y(v))}" for i, v in reversed(list(enumerate(lower)))]
        return " ".join(pts)

    parts = [f'<line x1="{_f(left)}" y1="{_f(y(lo))}" x2="{_f(left + plot_w)}" y2="{_f(y(lo))}" stroke="{MUTED}"/>',
             f'<polygon points="{area(bands["p05"], bands["p95"])}" fill="{ACC}" fill-opacity="0.16"/>',
             f'<polygon points="{area(bands["p25"], bands["p75"])}" fill="{ACC}" fill-opacity="0.34"/>',
             f'<polyline points="{" ".join(f"{_f(x(i))},{_f(y(v))}" for i, v in enumerate(bands["p50"]))}" '
             f'fill="none" stroke="{INK}" stroke-width="2"/>']
    if goal_value is not None:
        gy = y(goal_value)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        parts.append(f'<line x1="{_f(left)}" y1="{_f(gy)}" x2="{_f(left + plot_w)}" y2="{_f(gy)}" stroke="{GOAL}" '
                     f'stroke-width="2"{dash}/>')
        label = [f"{_e(words['goal'])}"]
        if goal_fact is not None:
            label.append(f" {fact_text(goal_fact)}")
        if dashed:
            label.append(f" ({_e(words['converted'])})")
        if chance_fact is not None:
            label.append(f" · {_e(words['chance'])} {fact_text(chance_fact)}")
        ly = gy - 7 if gy - 7 > top - 16 else gy + 15
        parts.append(f'<text x="{_f(left + 4)}" y="{_f(max(ly, 12.0))}" fill="{INK}">{"".join(label)}</text>')
    order = [k for k in ("p90", "p50", "p10") if k in ends]
    source = {"p90": "high", "p50": "mid", "p10": "low"}
    raw_ys = [y(float(ends[k].value)) if isinstance(ends[k].value, (int, float)) else y(bands["p50"][-1])
              for k in order]
    ys = _spread(raw_ys, 15.0)
    for k, yy, ry in zip(order, ys, raw_ys):
        parts.append(f'<line x1="{_f(left + plot_w)}" y1="{_f(ry)}" x2="{_f(left + plot_w + 6)}" y2="{_f(yy)}" '
                     f'stroke="{MUTED}"/>')
        parts.append(f'<text x="{_f(left + plot_w + 9)}" y="{_f(yy + 4)}" fill="{INK}">'
                     f'{_e(words[source[k]])} {fact_text(ends[k])}</text>')
    parts.append(f'<text x="{_f(left)}" y="{_f(height - 10)}" fill="{SOFT}">{_e(words["today"])}</text>')
    if date_fact is not None:
        parts.append(f'<text x="{_f(left + plot_w)}" y="{_f(height - 10)}" text-anchor="end" fill="{SOFT}">'
                     f'{fact_text(date_fact)}</text>')
    return _svg("outlook", height, title, desc, "".join(parts), caption)


# ---------------------------------------------------------------------------
# (4) The life balance sheet (section ``life_sheet``, REP-40)
# ---------------------------------------------------------------------------

#: The segment colours: the vessels and human capital on the assets side, liabilities and the goals' claims on the
#: other, net worth in ink. Checked for colour-blind separation of neighbours (dataviz validator, 03.10.2026);
#: every segment is also named and valued in the rows under its bar, so no colour carries meaning alone.
SEGMENT = {"free": ACC, "pillar_2": "#24997a", "pillar_3a": "#5f6ad8", "real_asset": "#D9783F",
           "not_stated": MUTED, "human": "#b8487a", "liabilities": "#57536e", "goal": GOAL, "net_worth": INK}


def _amount(f: Optional[Fact]) -> float:
    return abs(float(f.value)) if f is not None and isinstance(f.value, (int, float)) else 0.0


def balance_sheet(assets: Sequence[tuple[str, str, Fact]], claims: Sequence[tuple[str, str, Fact]],
                  total: Optional[Fact], net: Optional[Fact], words: dict[str, str], title: str, desc: str,
                  caption: str) -> str:
    """Three bars on one CHF scale, no axis: the assets (``(colour key, name, fact)`` per vessel and human capital),
    the liabilities and the goals' claims, and net worth. Each segment is named under its bar with its fact."""
    if not assets and not claims and net is None:
        return ""
    top = max(sum(_amount(f) for _, _, f in assets), sum(_amount(f) for _, _, f in claims), _amount(net), 1e-9)
    left, bar_w = 16.0, WIDTH - 32.0
    y = 6.0
    parts: list[str] = []

    def bar(head: str, head_fact: Optional[Fact], segs: Sequence[tuple[str, str, Fact]]) -> None:
        nonlocal y
        label = _e(head) + (f" {fact_text(head_fact)}" if head_fact is not None else "")
        parts.append(f'<text x="{_f(left)}" y="{_f(y + 13)}" fill="{INK}" font-weight="600">{label}</text>')
        y += 20
        x = left
        goals = {i: g for g, i in enumerate(i for i, (k, _, _) in enumerate(segs) if k == "goal")}
        drawn = [(goals.get(n, 0), k, f) for n, (k, _, f) in enumerate(segs) if _amount(f) > 0]
        for n, k, f in drawn:
            w = max(bar_w * _amount(f) / top, 2.0)
            fade = ' fill-opacity="0.6"' if k == "goal" and n % 2 else ""
            parts.append(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(max(w - 2, 1.0))}" height="20" rx="4" '
                         f'fill="{SEGMENT[k]}"{fade}/>')
            x += w
        if not drawn:
            parts.append(f'<text x="{_f(left)}" y="{_f(y + 14)}" fill="{SOFT}">{_e(words["nothing"])}</text>')
        y += 28
        for n, (k, name, f) in enumerate(segs):
            fade = ' fill-opacity="0.6"' if k == "goal" and goals.get(n, 0) % 2 else ""
            parts.append(f'<rect x="{_f(left)}" y="{_f(y + 2)}" width="10" height="10" rx="2" fill="{SEGMENT[k]}"{fade}/>')
            parts.append(f'<text x="{_f(left + 16)}" y="{_f(y + 11)}" fill="{SOFT}">{_e(name)}</text>')
            parts.append(f'<text x="{_f(WIDTH - left)}" y="{_f(y + 11)}" text-anchor="end" fill="{INK}">'
                         f'{fact_text(f)}</text>')
            y += 17
        y += 12

    bar(words["assets"], total, assets)
    bar(words["claims"], None, claims)
    if net is not None:
        parts.append(f'<text x="{_f(left)}" y="{_f(y + 13)}" fill="{INK}" font-weight="600">{_e(words["net_worth"])} '
                     f'{fact_text(net)}</text>')
        y += 20
        negative = isinstance(net.value, (int, float)) and net.value < 0
        fade = ' fill-opacity="0.45"' if negative else ""
        parts.append(f'<rect x="{_f(left)}" y="{_f(y)}" width="{_f(max(bar_w * _amount(net) / top, 2.0))}" '
                     f'height="20" rx="4" fill="{SEGMENT["net_worth"]}"{fade}/>')
        y += 28
    return _svg("life_sheet", y + 2, title, desc, "".join(parts), caption)


# ---------------------------------------------------------------------------
# (5) The four capitals (section ``capitals``, REP-41)
# ---------------------------------------------------------------------------

def scaled(value: float, lo: float, hi: float) -> float:
    """A capital's position on its own scale: 0 at the low end, 1 at the high end."""
    return min(1.0, max(0.0, (value - lo) / ((hi - lo) or 1.0)))


#: One capital of one adult: ``(capital name, value fact, level fact, position on its scale, low word, high word)``.
Track = tuple[str, Optional[Fact], Optional[Fact], Optional[float], str, str]


def capitals_today(wealth: Optional[Fact], persons: Sequence[tuple[str, Sequence[Track]]], words: dict[str, str],
                   title: str, desc: str, caption: str) -> str:
    """Wealth in CHF as a stated figure, and per adult each capital on its own track from its scale's low end to its
    high end, the ends in words, the level as a fact and a word. Never a money axis: a capital has no currency."""
    if not persons:
        return ""
    left, right = 16.0, 16.0
    track = WIDTH - left - right
    y = 6.0
    parts: list[str] = []
    if wealth is not None:
        parts.append(f'<text x="{_f(left)}" y="{_f(y + 14)}" fill="{INK}" font-weight="600">{_e(words["wealth"])} '
                     f'{fact_text(wealth)}</text>')
        y += 30
    for name, caps in persons:
        parts.append(f'<text x="{_f(left)}" y="{_f(y + 14)}" fill="{INK}" font-weight="700">{_e(name)}</text>')
        y += 24
        for cap_name, value, level, share, low, high in caps:
            parts.append(f'<text x="{_f(left)}" y="{_f(y + 12)}" fill="{INK}">{_e(cap_name)}</text>')
            if value is not None and share is not None:
                shown = fact_text(value) + (f" · {fact_text(level)}" if level is not None else "")
                parts.append(f'<text x="{_f(WIDTH - right)}" y="{_f(y + 12)}" text-anchor="end" fill="{INK}">'
                             f'{shown}</text>')
            else:
                parts.append(f'<text x="{_f(WIDTH - right)}" y="{_f(y + 12)}" text-anchor="end" fill="{SOFT}">'
                             f'{_e(words["not_stated"])}</text>')
            y += 18
            parts.append(f'<rect x="{_f(left)}" y="{_f(y)}" width="{_f(track)}" height="8" rx="4" fill="{LINE}"/>')
            if value is not None and share is not None:
                pos = left + track * share
                parts.append(f'<rect x="{_f(left)}" y="{_f(y)}" width="{_f(max(pos - left, 2.0))}" height="8" rx="4" '
                             f'fill="{BLUE}"/>')
                parts.append(f'<circle cx="{_f(pos)}" cy="{_f(y + 4)}" r="6" fill="{SOFT}" stroke="#fff" '
                             f'stroke-width="2"/>')
            y += 22
            parts.append(f'<text x="{_f(left)}" y="{_f(y)}" fill="{SOFT}" font-size="11">{_e(low)}</text>')
            parts.append(f'<text x="{_f(WIDTH - right)}" y="{_f(y)}" text-anchor="end" fill="{SOFT}" font-size="11">'
                         f'{_e(high)}</text>')
            y += 16
        y += 6
    return _svg("capitals", y, title, desc, "".join(parts), caption)


#: One capital over time: ``(name, bands p10 p50 p90, (low, high) of its scale, end facts, today's median fact)``.
Panel = tuple[str, dict[str, Sequence[float]], tuple[float, float], dict[str, Fact], Optional[Fact]]


def capitals_over_time(panels: Sequence[Panel], horizon: Optional[Fact], words: dict[str, str], title: str,
                       desc: str, caption: str) -> str:
    """One small panel per capital over the years (index 0 today): the p10 to p90 band and the median, on the
    capital's own scale, its ends in words; today's median and the p10, p50, p90 of the last year are facts. No tick
    and no axis number, and never a money axis."""
    panels = [p for p in panels if len(p[1].get("p50", ())) >= 2]
    if not panels:
        return ""
    left, right, panel_h, gap = 44.0, 170.0, 92.0, 46.0
    plot_w = WIDTH - left - right
    parts: list[str] = []
    y0 = 4.0
    for name, bands, (lo, hi), ends, today in panels:
        n = len(bands["p50"])
        span = (hi - lo) or 1.0
        top = y0 + 22

        def x(i: int) -> float:
            return left + plot_w * i / (n - 1)

        def y(v: float) -> float:
            return top + panel_h * (hi - min(max(v, lo), hi)) / span

        head = _e(name)
        if today is not None:
            head += f' <tspan fill="{SOFT}">· {_e(words["today"])}</tspan> {fact_text(today)}'
        parts.append(f'<text x="{_f(left)}" y="{_f(y0 + 14)}" fill="{INK}" font-weight="600">{head}</text>')
        parts.append(f'<rect x="{_f(left)}" y="{_f(top)}" width="{_f(plot_w)}" height="{_f(panel_h)}" fill="none" '
                     f'stroke="{LINE}"/>')
        parts.append(f'<text x="{_f(left - 6)}" y="{_f(top + 10)}" text-anchor="end" fill="{SOFT}" font-size="11">'
                     f'{_e(words["high_end"])}</text>')
        parts.append(f'<text x="{_f(left - 6)}" y="{_f(top + panel_h)}" text-anchor="end" fill="{SOFT}" '
                     f'font-size="11">{_e(words["low_end"])}</text>')
        upper = [f"{_f(x(i))},{_f(y(v))}" for i, v in enumerate(bands["p90"])]
        lower = [f"{_f(x(i))},{_f(y(v))}" for i, v in reversed(list(enumerate(bands["p10"])))]
        parts.append(f'<polygon points="{" ".join(upper + lower)}" fill="{ACC}" fill-opacity="0.22"/>')
        median = " ".join(f"{_f(x(i))},{_f(y(v))}" for i, v in enumerate(bands["p50"]))
        parts.append(f'<polyline points="{median}" fill="none" stroke="{INK}" stroke-width="2"/>')
        order = [k for k in ("p90", "p50", "p10") if k in ends]
        if "p50" in ends and len({ends[k].display for k in order}) == 1:
            order = ["p50"]   # a band collapsed to one line: one label, the table under the chart has all three
        source = {"p90": "high", "p50": "mid", "p10": "low"}
        raw = [y(float(ends[k].value)) if isinstance(ends[k].value, (int, float)) else y(bands["p50"][-1])
               for k in order]
        for k, yy, ry in zip(order, _spread(raw, 14.0), raw):
            parts.append(f'<line x1="{_f(left + plot_w)}" y1="{_f(ry)}" x2="{_f(left + plot_w + 6)}" y2="{_f(yy)}" '
                         f'stroke="{MUTED}"/>')
            parts.append(f'<text x="{_f(left + plot_w + 9)}" y="{_f(yy + 4)}" fill="{INK}">'
                         f'{_e(words[source[k]])} {fact_text(ends[k])}</text>')
        parts.append(f'<text x="{_f(left)}" y="{_f(top + panel_h + 16)}" fill="{SOFT}" font-size="11">'
                     f'{_e(words["today"])}</text>')
        if horizon is not None:
            parts.append(f'<text x="{_f(left + plot_w)}" y="{_f(top + panel_h + 16)}" text-anchor="end" '
                         f'fill="{SOFT}" font-size="11">{_e(words["in"])} {fact_text(horizon)} '
                         f'{_e(words["years"])}</text>')
        y0 = top + panel_h + gap - 14
    return _svg("capitals_time", y0 + 4, title, desc, "".join(parts), caption)
