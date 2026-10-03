// The outlook's three charts (LBSIM_INTERFACES section 7, EIG-68): SVG built in the browser with the
// namespace-aware h() of dom.js, no library, no external script, no web font. Each chart is a function of its
// figures and its words: the page gives it the series in the basis the switch shows and the sentences in the
// page's language, and draws it again when the switch changes. Every chart is role="img" with a title and a
// description in words, a viewBox, and its values written beside the marks.
//
// (1) weightsChart: the weights as horizontal bars (by role, the house's names; by instrument, by name).
// (2) fitChart: the Mandate's target against the reached return in each of the 25 market states, "Krise" to
//     "Boom" as words at the ends, and the line of zero return.
// (3) fanChart: the wealth paths as a fan (5 to 95 and 25 to 75 of 100 paths, the median), and the goal's line,
//     solid in the goal's own basis and dashed in the other (converted, LBSIM-09).

import { amount, svg } from './dom.js';

const W = 640;

function frame(height, title, desc, kids) {
  return svg('svg', { class: 'chart', role: 'img', viewBox: `0 0 ${W} ${height}`, width: '100%',
    preserveAspectRatio: 'xMinYMin meet', 'aria-label': title }, [
    svg('title', { text: title }), svg('desc', { text: desc }), ...kids]);
}

function pctText(value, L) {
  return `${new Intl.NumberFormat(L === 'en' ? 'en-CH' : 'de-CH', { maximumFractionDigits: 1 }).format(value * 100)} %`;
}

/** (1) Horizontal bars. `rows`: [{label, weight}] (weights 0..1); `words`: {title, desc}. */
export function weightsChart(rows, words, L) {
  const shown = rows.filter((r) => typeof r.weight === 'number' && r.weight > 1e-6);
  const bar = 26;
  const height = 16 + shown.length * bar;
  const left = 220;
  const span = W - left - 80;
  const max = Math.max(...shown.map((r) => r.weight), 1e-9);
  const kids = [];
  shown.forEach((r, i) => {
    const y = 8 + i * bar;
    const width = Math.max(1, (r.weight / max) * span);
    kids.push(
      svg('text', { x: left - 8, y: y + bar * 0.62, class: 'chart-label', 'text-anchor': 'end', text: r.label }),
      svg('rect', { x: left, y: y + 4, width: width.toFixed(1), height: bar - 9, rx: 3, class: 'chart-bar' }),
      svg('text', { x: left + width + 6, y: y + bar * 0.62, class: 'chart-value', text: pctText(r.weight, L) }),
    );
  });
  return frame(height, words.title, words.desc, kids);
}

function line(points, cls, dashed = false) {
  return svg('polyline', { points: points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '), class: cls,
    fill: 'none', 'stroke-dasharray': dashed ? '6 4' : null });
}

/** (2) Target against reached per state. `curves`: {target[25], achieved[25]} (annualised log returns);
 *  `words`: {title, desc, target, achieved, zero, crisis, boom}. */
export function fitChart(curves, words) {
  const target = curves.target || [];
  const achieved = curves.achieved || [];
  const all = [...target, ...achieved, 0];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const height = 260;
  const top = 30;
  const bottom = height - 40;
  const left = 40;
  const right = W - 150;
  const x = (i) => left + (i / Math.max(1, target.length - 1)) * (right - left);
  const y = (v) => bottom - ((v - lo) / Math.max(1e-9, hi - lo)) * (bottom - top);
  const kids = [
    svg('line', { x1: left, x2: right, y1: y(0).toFixed(1), y2: y(0).toFixed(1), class: 'chart-zero' }),
    svg('text', { x: right + 6, y: y(0) + 4, class: 'chart-label', text: words.zero }),
    line(target.map((v, i) => [x(i), y(v)]), 'chart-target'),
    line(achieved.map((v, i) => [x(i), y(v)]), 'chart-achieved'),
    svg('text', { x: left, y: height - 12, class: 'chart-label', text: words.crisis }),
    svg('text', { x: right, y: height - 12, class: 'chart-label', 'text-anchor': 'end', text: words.boom }),
  ];
  if (target.length) kids.push(svg('text', { x: right + 6, y: y(target[target.length - 1]) + 4, class: 'chart-label target', text: words.target }));
  if (achieved.length) kids.push(svg('text', { x: right + 6, y: y(achieved[achieved.length - 1]) + 18, class: 'chart-label achieved', text: words.achieved }));
  return frame(height, words.title, words.desc, kids);
}

/** (3) The fan. `bands`: {p05, p10, p25, p50, p75, p90, p95} of year-end values from `startYear`, up to `until`
 *  (an index, the goal's year); `goal`: {value, dashed, label} or null; `words`: {title, desc, outer, inner,
 *  median, today}. */
export function fanChart(bands, startYear, until, goal, words, L) {
  const n = Math.max(1, Math.min((bands.p50 || []).length - 1, until ?? (bands.p50 || []).length - 1));
  const cut = (q) => (bands[q] || []).slice(0, n + 1);
  const series = { p05: cut('p05'), p25: cut('p25'), p50: cut('p50'), p75: cut('p75'), p95: cut('p95') };
  const values = [...series.p05, ...series.p95, 0, ...(goal && typeof goal.value === 'number' ? [goal.value] : [])];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const height = 300;
  const top = 24;
  const bottom = height - 40;
  const left = 20;
  const right = W - 200;
  const x = (i) => left + (i / n) * (right - left);
  const y = (v) => bottom - ((v - lo) / Math.max(1e-9, hi - lo)) * (bottom - top);
  const area = (upper, lower, cls) => svg('polygon', { class: cls, points: [
    ...upper.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`),
    ...lower.map((v, i) => [i, v]).reverse().map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)].join(' ') });
  const end = series.p50[series.p50.length - 1];
  const kids = [
    area(series.p95, series.p05, 'chart-band-outer'),
    area(series.p75, series.p25, 'chart-band-inner'),
    line(series.p50.map((v, i) => [x(i), y(v)]), 'chart-median'),
    svg('text', { x: left, y: height - 12, class: 'chart-label', text: words.today }),
    svg('text', { x: right, y: height - 12, class: 'chart-label', 'text-anchor': 'end', text: String(startYear + n) }),
    svg('text', { x: right + 8, y: y(end) + 4, class: 'chart-label', text: `${words.median}: CHF ${amount(end, L)}` }),
    svg('text', { x: right + 8, y: y(series.p95[series.p95.length - 1]) + 4, class: 'chart-label muted', text: words.outer }),
    svg('text', { x: right + 8, y: y(series.p75[series.p75.length - 1]) - 6, class: 'chart-label muted', text: words.inner }),
  ];
  if (goal && typeof goal.value === 'number') {
    kids.push(svg('line', { x1: left, x2: right, y1: y(goal.value).toFixed(1), y2: y(goal.value).toFixed(1),
      class: 'chart-goal', 'stroke-dasharray': goal.dashed ? '6 4' : null }));
    kids.push(svg('text', { x: right + 8, y: y(goal.value) + 16, class: 'chart-label goal', text: goal.label }));
  }
  return frame(height, words.title, words.desc, kids);
}

// ---- the life balance sheet and the four capitals (VISUALS_INTERFACES.md, EIG-70 to EIG-72) -----------------
//
// (4) balanceChart: three columns on one franc scale: the assets stacked by vessel with the human capital, the
//     debts with the net worth above them, the goals' amounts in the basis the switch shows. Each column's parts
//     are listed under it with their amounts, so a thin part is never a label lost on top of another.
// (5) capitalsChart: per adult, wealth in francs as words, and expertise, network and health as bars from zero
//     to the model's ceiling with the level in words. Never on a money axis. A withheld health is not drawn.
// (6) capitalPathChart: one capital over time, the middle path and the band of 10 to 90 of 100 paths, on its own
//     scale with words at both ends, never francs.

/** "gering" / "mittel" / "hoch": a level in words, by its third of the scale. */
export function levelWord(value, scale, words) {
  const lo = (scale && typeof scale.min === 'number') ? scale.min : 0;
  const hi = (scale && typeof scale.max === 'number' && scale.max > lo) ? scale.max : 1;
  const share = (value - lo) / (hi - lo);
  return share < 1 / 3 ? words.low : share < 2 / 3 ? words.mid : words.high;
}

function levelNumber(value, L) {
  return new Intl.NumberFormat(L === 'en' ? 'en-CH' : 'de-CH', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value);
}

/** (4) The balance sheet. `columns`: [{title, parts: [{label, chf, cls, open}], note}] (parts bottom to top; a
 *  part without a positive amount is listed under its column but not stacked); `words`: {title, desc}. */
export function balanceChart(columns, words, L) {
  const top = 30;
  const barH = 220;
  const colW = W / columns.length;
  const bar = Math.min(84, colW * 0.42);
  const sums = columns.map((c) => c.parts.reduce((s, p) => s + (p.chf > 0 ? p.chf : 0), 0));
  const max = Math.max(...sums, 1);
  const rows = Math.max(...columns.map((c) => c.parts.length + (c.note ? 1 : 0)), 1);
  const height = top + barH + 16 + rows * 34 + 8;
  const kids = [];
  columns.forEach((c, i) => {
    const x0 = i * colW;
    const bx = x0 + (colW - bar) / 2;
    kids.push(svg('text', { x: x0 + colW / 2, y: 18, class: 'chart-label strong', 'text-anchor': 'middle', text: c.title }));
    kids.push(svg('line', { x1: bx - 6, x2: bx + bar + 6, y1: top + barH, y2: top + barH, class: 'chart-zero' }));
    let y = top + barH;
    for (const p of c.parts) {
      if (!(p.chf > 0)) continue;
      const hgt = (p.chf / max) * barH;
      y -= hgt;
      kids.push(svg('rect', { x: bx.toFixed(1), y: y.toFixed(1), width: bar.toFixed(1), height: Math.max(1, hgt).toFixed(1), class: `chart-part ${p.cls}` }));
    }
    let ly = top + barH + 16;
    [...c.parts].reverse().forEach((p) => {
      kids.push(svg('rect', { x: x0 + 12, y: ly + 2, width: 10, height: 10, rx: 2, class: `chart-part ${p.cls}` }));
      kids.push(svg('text', { x: x0 + 28, y: ly + 11, class: 'chart-label', text: p.label.length > 30 ? `${p.label.slice(0, 29)}…` : p.label },
        [svg('title', { text: p.label })]));
      kids.push(svg('text', { x: x0 + 28, y: ly + 26, class: 'chart-value', text: typeof p.chf === 'number' ? `CHF ${amount(p.chf, L)}` : p.open }));
      ly += 34;
    });
    if (c.note) kids.push(svg('text', { x: x0 + 12, y: ly + 11, class: 'chart-label muted', text: c.note }));
  });
  return frame(height, words.title, words.desc, kids);
}

/** (5) The four capitals of one adult. `row`: {name, expertise, network, health, health_withheld}; `scale`:
 *  {min, max}; `words`: {title, desc, wealth, wealthText, expertise, network, health, low, mid, high, of, unknown,
 *  withheld}. */
export function capitalsChart(row, scale, words, L) {
  const left = 190;
  const track = W - left - 210;
  const lo = typeof scale.min === 'number' ? scale.min : 0;
  const hi = typeof scale.max === 'number' && scale.max > lo ? scale.max : 1;
  const kids = [
    svg('text', { x: 0, y: 20, class: 'chart-label strong', text: words.wealth }),
    svg('text', { x: left, y: 20, class: 'chart-value', text: words.wealthText }),
  ];
  let y = 40;
  for (const key of ['expertise', 'network', 'health']) {
    kids.push(svg('text', { x: 0, y: y + 15, class: 'chart-label strong', text: words[key] }));
    if (key === 'health' && row.health_withheld) {
      kids.push(svg('text', { x: left, y: y + 15, class: 'chart-label muted', text: words.withheld }));
    } else if (typeof row[key] !== 'number') {
      kids.push(svg('text', { x: left, y: y + 15, class: 'chart-label muted', text: words.unknown }));
    } else {
      const share = Math.max(0, Math.min(1, (row[key] - lo) / (hi - lo)));
      kids.push(svg('rect', { x: left, y: y + 4, width: track, height: 14, rx: 7, class: 'chart-track' }),
        svg('rect', { x: left, y: y + 4, width: Math.max(2, share * track).toFixed(1), height: 14, rx: 7, class: `chart-capital ${key}` }),
        svg('text', { x: left + track + 10, y: y + 15, class: 'chart-value',
          text: `${levelWord(row[key], { min: lo, max: hi }, words)} (${words.of.replace('{value}', levelNumber(row[key], L)).replace('{max}', levelNumber(hi, L))})` }));
    }
    y += 30;
  }
  return frame(y + 6, words.title, words.desc, kids);
}

/** (6) One capital over time. `series`: {bands: {p10, p25, p50, p75, p90}, scale: {min, max}, label}; `words`:
 *  {title, desc, outer, median, today, min, max, low, mid, high}. */
export function capitalPathChart(series, startYear, words, L) {
  const b = series.bands || {};
  const p50 = b.p50 || [];
  const n = Math.max(1, p50.length - 1);
  const lo = series.scale && typeof series.scale.min === 'number' ? series.scale.min : 0;
  const hi = series.scale && typeof series.scale.max === 'number' && series.scale.max > lo ? series.scale.max
    : Math.max(lo + 1e-9, ...(b.p90 || p50));
  const height = 190;
  const top = 18;
  const bottom = height - 34;
  const left = 110;
  const right = W - 190;
  const x = (i) => left + (i / n) * (right - left);
  const y = (v) => bottom - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (bottom - top);
  const band = (upper, lower, cls) => svg('polygon', { class: cls, points: [
    ...upper.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`),
    ...lower.map((v, i) => [i, v]).reverse().map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)].join(' ') });
  const end = p50[p50.length - 1];
  const kids = [
    svg('line', { x1: left, x2: right, y1: top, y2: top, class: 'chart-zero' }),
    svg('line', { x1: left, x2: right, y1: bottom, y2: bottom, class: 'chart-zero' }),
    svg('text', { x: left - 8, y: top + 4, class: 'chart-label muted', 'text-anchor': 'end', text: `${words.max} ${levelNumber(hi, L)}` }),
    svg('text', { x: left - 8, y: bottom + 4, class: 'chart-label muted', 'text-anchor': 'end', text: `${words.min} ${levelNumber(lo, L)}` }),
    svg('text', { x: left, y: height - 10, class: 'chart-label', text: words.today }),
    svg('text', { x: right, y: height - 10, class: 'chart-label', 'text-anchor': 'end', text: String(startYear + n) }),
  ];
  if (b.p10 && b.p90) kids.push(band(b.p90, b.p10, 'chart-band-outer'));
  if (b.p25 && b.p75) kids.push(band(b.p75, b.p25, 'chart-band-inner'));
  kids.push(line(p50.map((v, i) => [x(i), y(v)]), 'chart-median'));
  if (typeof end === 'number') {
    kids.push(svg('text', { x: right + 8, y: y(end) + 4, class: 'chart-label',
      text: `${words.median}: ${levelWord(end, { min: lo, max: hi }, words)} (${levelNumber(end, L)})` }));
  }
  if (b.p90 && b.p90.length) {
    kids.push(svg('text', { x: right + 8, y: Math.max(top + 4, y(b.p90[b.p90.length - 1]) - 10), class: 'chart-label muted', text: words.outer }));
  }
  return frame(height, words.title, words.desc, kids);
}
