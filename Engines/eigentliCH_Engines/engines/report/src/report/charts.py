"""The report's three charts as inline SVG (REP-34). Pure functions, no I/O.

* (1) **Weights**: horizontal bars, by role (section ``roles``) and by building block (section ``positions``),
  from the pcp Allocation's facts.
* (2) **Target against reached per state** (section ``fit``): the 25 market states from crisis to boom, the
  Mandate's target return and the return the weights reach, and the line of zero return; on the Allocation's
  basis (REP-28).
* (3) **The fan** (section ``outlook``): lbsim's p05 to p95 and p25 to p75 bands of the designated goal's
  measure up to its date, the median path, and the goal line; the line is dashed when the goal is set in the other
  basis and converted (LBSIM-09).

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
