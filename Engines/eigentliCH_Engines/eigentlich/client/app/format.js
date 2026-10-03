// Display rounding (owner, 03.10.2026, review/ROUNDING.md; EIG-73): the one number formatter of this client. Every
// figure a person reads on a page, in a chart (labels and values) or in a sentence goes through here; the engines'
// exact values stay as they arrived, and what is typed into a field is never rounded. The Swiss style stays as the
// app always wrote it (the browser's de-CH / en-CH: an apostrophe between thousands, a decimal point); only the
// number of digits is this module's business. Absent stays absent: null is not zero (R-020).
//
//   amounts (CHF a stock or a year): below 1 000 whole francs; 1 000 to 99 999 to the nearest 100; 100 000 to
//     999 999 to the nearest 1 000; from 1 000 000 millions with two decimals ("1.35 Mio." / "1.35 m")
//   stated: the client's own figure as stated (a target, a position, an answer)
//   rate: one decimal, percent (4.9 %)
//   chance: whole percent; "unter 1 %" / "über 99 %" at the ends; 0 % and 100 % only for exactly 0 and 1
//   share: whole percent; below 1 % one decimal; 0 as "–"
//   level: two decimals (0.62), after a word the caller puts first
//   ratio: one decimal (a beta two); count and year: whole

const locale = (L) => (L === 'en' ? 'en-CH' : 'de-CH');
const absent = (v) => v === null || v === undefined || typeof v !== 'number' || !Number.isFinite(v);

/** |x| rounded half up to `places` decimals (negative places: tens, hundreds, ...), without binary drift. */
export function roundAbs(x, places = 0) {
  const a = Math.abs(x);
  if (places >= 0) {
    const f = 10 ** places;
    return Math.round(Number((a * f).toPrecision(15))) / f;
  }
  const step = 10 ** -places;
  return Math.round(Number((a / step).toPrecision(15))) * step;
}

function digits(n, places, L, group = true) {
  return new Intl.NumberFormat(locale(L), { minimumFractionDigits: places, maximumFractionDigits: places, useGrouping: group }).format(n);
}

const sign = (x, shown) => (x < 0 && shown !== 0 ? '-' : '');

/** An amount's figure without the currency: 640, 38’200, 579’000, 1.35 Mio. (de) / 1.35 m (en). */
export function amount(value, L = 'de') {
  if (absent(value)) return null;
  const a = Math.abs(value);
  const r = a < 1000 ? roundAbs(a, 0) : a < 100000 ? roundAbs(a, -2) : roundAbs(a, -3);
  if (r >= 1e6) {
    const m = roundAbs(a / 1e6, 2);
    return `${sign(value, m)}${digits(m, 2, L)} ${L === 'en' ? 'm' : 'Mio.'}`;
  }
  return `${sign(value, r)}${digits(r, 0, L)}`;
}

/** "CHF 38’200", or null. */
export function money(value, L = 'de') {
  const a = amount(value, L);
  return a === null ? null : `CHF ${a}`;
}

/** The client's own figure, shown as stated (up to two decimals, grouped). */
export function stated(value, L = 'de') {
  if (absent(value)) return null;
  return new Intl.NumberFormat(locale(L), { maximumFractionDigits: 2 }).format(value);
}

/** A return or rate (a decimal a year): "4.9 %". */
export function rate(value, L = 'de') {
  if (absent(value)) return null;
  const d = roundAbs(value * 100, 1);
  return `${sign(value, d)}${digits(d, 1, L)} %`;
}

/** A chance (0 to 1): "68 %", "unter 1 %", "über 99 %"; 0 % and 100 % only when every path agrees. */
export function chance(p, L = 'de') {
  if (absent(p)) return null;
  if (p <= 0) return '0 %';
  if (p >= 1) return '100 %';
  if (p < 0.01) return L === 'en' ? 'below 1 %' : 'unter 1 %';
  if (p > 0.99) return L === 'en' ? 'above 99 %' : 'über 99 %';
  return `${digits(roundAbs(p * 100, 0), 0, L)} %`;
}

/** A weight or share (0 to 1): "27 %", below 1 % "0.4 %", 0 as "–". */
export function share(w, L = 'de') {
  if (absent(w)) return null;
  if (Math.abs(w) < 1e-9) return '–'; // an optimiser's 2e-16 is a zero
  const one = roundAbs(w * 100, 1);
  if (one < 1) {
    if (one === 0) return `${L === 'en' ? 'below' : 'unter'} ${digits(0.1, 1, L)} %`;
    return `${sign(w, one)}${digits(one, 1, L)} %`;
  }
  const d = roundAbs(w * 100, 0);
  return `${sign(w, d)}${digits(d, 0, L)} %`;
}

/** A model level or score without a unit: two decimals ("0.62"). The caller puts the word first. */
export function level(value, L = 'de') {
  if (absent(value)) return null;
  const d = roundAbs(value, 2);
  return `${sign(value, d)}${digits(d, 2, L)}`;
}

/** A duration or ratio: one decimal (a beta: places 2). */
export function ratio(value, L = 'de', places = 1) {
  if (absent(value)) return null;
  const d = roundAbs(value, places);
  return `${sign(value, d)}${digits(d, places, L)}`;
}

/** Hours, ages and counts: a whole number ("20", "1’250"). */
export function count(value, L = 'de') {
  if (absent(value)) return null;
  const d = roundAbs(value, 0);
  return `${sign(value, d)}${digits(d, 0, L)}`;
}

/** A calendar year: whole and ungrouped ("2034"). */
export function year(value) {
  if (absent(value)) return null;
  return String(Math.round(value));
}
