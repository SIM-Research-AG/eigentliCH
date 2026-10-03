// ---- display rounding: begin (review/ROUNDING.md; cockpit C-37) ----
// Canonical copy: Engines/cockpit/dev/display_rounding.js. The cockpit page and every engine's test bench carry this
// block verbatim between the begin and end lines; tests/test_api.py checks that every copy is identical. Change it
// here, then copy it into each page. Display only: the figures stay exact everywhere else (contracts, artefacts,
// stores, raw JSON views); a number is rounded only where it becomes text or a chart label.
// Use: const N = displayRounding({ lang: "en", group: "’", na: "–" }); then N.money(38250) is "CHF 38’300".
function displayRounding(opts) {
  const o = Object.assign({ lang: "en", group: "’", na: "–", minus: "−" }, opts || {});
  const WORDS = { en: { m: "m", bn: "bn", tn: "tn", below: "below", above: "above" },
                  de: { m: "Mio.", bn: "Mrd.", tn: "Bio.", below: "unter", above: "über" } };
  const w = () => WORDS[o.lang] || WORDS.en;
  const ok = v => v !== null && v !== undefined && v !== "" && typeof v !== "boolean" && Number.isFinite(Number(v));
  const grouped = s => s.replace(/\B(?=(\d{3})+(?!\d))/g, o.group);
  // d decimals, the integer part grouped, a true minus sign, never "-0"; sign: "+" before a positive figure
  function fixed(v, d, sign) {
    const x = Number(v), t = Math.abs(x).toFixed(d || 0), parts = t.split(".");
    const body = grouped(parts[0]) + (parts[1] ? "." + parts[1] : "");
    return (Number(t) === 0 ? "" : x < 0 ? o.minus : sign ? "+" : "") + body;
  }
  // from a million: millions, billions or trillions, two decimals (a GDP reads "USD 27.36 tn", not millions of millions)
  function large(x) {
    const a = Math.abs(x);
    if (a >= 999.995e9) return fixed(x / 1e12, 2) + " " + w().tn;
    if (a >= 999.995e6) return fixed(x / 1e9, 2) + " " + w().bn;
    return fixed(x / 1e6, 2) + " " + w().m;
  }
  const stepped = (x, step) => Math.sign(x) * Math.round(Math.abs(x) / step) * step;
  // CHF, EUR, USD: below 1 000 whole units; to 99 999 the nearest 100; to 999 999 the nearest 1 000; then millions
  // (billions, trillions), two decimals
  function amountText(v) {
    const x = Number(v), a = Math.abs(x);
    if (a < 999.5) return fixed(x, 0);
    if (a < 99950) return fixed(stepped(x, 100), 0);
    if (a < 999500) return fixed(stepped(x, 1000), 0);
    return large(x);
  }
  const pre = (cur, text) => cur ? cur + " " + text : text;
  const N = {
    opts: o,
    ok,
    fixed: (v, d, sign) => ok(v) ? fixed(v, d, sign) : o.na,
    // an amount by the stepped rule, with its currency in front ("" for none)
    money: (v, cur = "CHF") => ok(v) ? pre(cur, amountText(v)) : o.na,
    amount: v => ok(v) ? amountText(v) : o.na,
    // a figure the client stated (a fee, a deposit, a price): shown as stated, whole units unless it has cents
    stated: (v, cur = "CHF") => ok(v) ? pre(cur, fixed(v, Number.isInteger(Number(v)) ? 0 : 2)) : o.na,
    // returns, rates, inflation: one decimal, percent; rate takes a fraction (0.049), ratePct a percent (4.9)
    rate: (v, sign) => ok(v) ? fixed(Number(v) * 100, 1, sign) + " %" : o.na,
    ratePct: (v, sign) => ok(v) ? fixed(v, 1, sign) + " %" : o.na,
    // percentage points (a shift between two rates given in percent)
    pp: (v, sign = true) => ok(v) ? fixed(v, 1, sign) + " pp" : o.na,
    // chances: whole percent; below 1 % and above 99 % in words; 0 % and 100 % only when every path agrees (exactly 0 or 1)
    chance: v => {
      if (!ok(v)) return o.na;
      const p = Number(v);
      if (p <= 0) return "0 %";
      if (p >= 1) return "100 %";
      if (p < 0.01) return w().below + " 1 %";
      if (p > 0.99) return w().above + " 99 %";
      return Math.round(p * 100) + " %";
    },
    // portfolio weights and shares: whole percent; below 1 % one decimal; 0 is "–"; weight takes a fraction, weightPct a percent
    weightPct: v => {
      if (!ok(v)) return o.na;
      const p = Number(v), a = Math.abs(p);
      if (a === 0) return "–";
      if (a < 0.05) return w().below + " 0.1 %";
      return fixed(p, a < 0.95 ? 1 : 0) + " %";
    },
    weight: v => ok(v) ? N.weightPct(Number(v) * 100) : o.na,
    // model levels without a unit (scores, expertise, network, health): the word first when there is one, two decimals
    level: (v, word) => ok(v) ? (word ? word + " (" + fixed(v, 2) + ")" : fixed(v, 2)) : o.na,
    // ratios and durations one decimal; betas two
    ratio: v => ok(v) ? fixed(v, 1) : o.na,
    beta: v => ok(v) ? fixed(v, 2) : o.na,
    // a change with its sign, d decimals (a score change 2, a z-score 1)
    signed: (v, d = 2) => ok(v) ? fixed(v, d, true) : o.na,
    // years, ages, hours, seconds: whole, never grouped (2034); counts: whole, grouped (12’000)
    whole: v => ok(v) ? fixed(Math.round(Number(v)), 0).split(o.group).join("") : o.na,
    count: v => ok(v) ? fixed(Math.round(Number(v)), 0) : o.na,
    // a figure of no stated kind (raw index values, a model card's series): three significant digits, whole from 100;
    // below 0.0001 in exponent form with two significant digits, so a tiny residual does not read as "0"
    auto: v => {
      if (!ok(v)) return o.na;
      const x = Number(v), a = Math.abs(x);
      if (a === 0) return "0";
      if (a >= 999500) return large(x);
      if (a >= 99.5) return fixed(x, 0);
      if (a < 1e-4) { const [m, e] = x.toExponential(1).split("e"); return m.replace("-", o.minus) + "e" + e.replace("+", "").replace("-", o.minus); }
      const d = Math.min(8, Math.max(0, 2 - Math.floor(Math.log10(a))));
      return fixed(x, d).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    },
    // chart axis: about n round ticks covering lo to hi, one step past each end (the chart hides the ticks outside its
    // range), each labelled by fn (N.money, N.rate, ...): spread the result into the chart's axis
    ticks: (lo, hi, fn, n = 5) => {
      lo = Number(lo) || 0; hi = Number(hi) || 0;
      if (hi < lo) { const t = lo; lo = hi; hi = t; }
      const raw = ((hi - lo) || Math.abs(hi) || 1) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
      const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(s => s >= raw * 0.999);
      const vals = [];
      for (let k = Math.floor(lo / step + 1e-9); k * step < hi + step * (1 - 1e-9); k++) vals.push(Math.round(k * step * 1e9) / 1e9);
      return { tickmode: "array", tickvals: vals, ticktext: vals.map(v => fn(v)) };
    },
  };
  return N;
}
// ---- display rounding: end ----
