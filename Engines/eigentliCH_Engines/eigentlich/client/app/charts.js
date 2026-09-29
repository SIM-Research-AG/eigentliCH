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
