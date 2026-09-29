// Differential harness. Extracts the identity functions from the ORIGINAL
// `andersCH-prototype/onboarding-chat.html` and runs them over a case corpus, emitting the results as
// JSON. The Python reimplementation is then asserted against that file — so the standard the port is held
// to is "same output as the original", not "same output as whoever wrote the port thought it should be".
//
// The fixture it writes is COMMITTED and the suite reads it. Node is used here, once, by hand; the test
// does not need it. `tests/conftest.py` makes the same point about the book corpus: a suite that is green
// only where a particular machine's tooling happens to sit proves nothing about the code a friend runs.

import { readFileSync, writeFileSync } from 'node:fs';

const SOURCE = process.argv[2];
const OUT = process.argv[3];

const html = readFileSync(SOURCE, 'utf8');

// The region holding the five functions the update script names, plus the two lookup tables they read.
const start = html.indexOf("const CONF = {");
const endMarker = "/* --- derive the model's own fields";
const end = html.indexOf(endMarker);
if (start === -1 || end === -1 || end < start) {
  throw new Error(`could not locate the identity block (start=${start}, end=${end})`);
}
const block = html.slice(start, end);

// Evaluated in a function scope and handed back, rather than dropped into the module's own scope.
const identities = new Function(`
  ${block}
  return { CONF, PARTNERED, MARRIED, parseGoalText, goalsFrom, netScale, expertiseScale, childAges };
`)();

// ---------------------------------------------------------------- the corpus
//
// Every case the source comments call out by name, plus the boundaries each function turns on, plus the
// shapes the six real submissions actually contain. A corpus that only covered the happy path would let a
// port that mishandles null pass.

const goalText = [
  "2040 Ferienvilla in Südfrankreich, 1 Mio",
  "2030: 750'000 für die Firma",
  "Wohneigentum 2038 1.5 Mio",
  "Ausgaben ab 65 aus eigenem Vermögen gedeckt",
  "Ferienhaus",
  "",
  null,
  "3 Kinder",
  "im Jahr 2035 etwa 250 000",
  "ca. 80k für ein Sabbatical",
  "1'250'000",
  "12345",
  "2027",
  "2.5 Mio bis 2045",
  "500 tsd",
  "1,5 mio",
];

const goalsFromCases = [
  { data: { birth_year: 1993, spend_now: 60000, goal_confidence: "80 %" }, year: 2026 },
  { data: { birth_year: 1993, spend_later: 48000, spend_now: 60000, goal_confidence: "90 % — es muss halten" }, year: 2026 },
  { data: { birth_year: 1955, spend_now: 55000, goal_confidence: "70 % — ich kann nachjustieren" }, year: 2026 },
  { data: { birth_year: 1961, spend_now: 40000 }, year: 2026 },
  { data: { birth_year: 2002, spend_now: 47000, goals: "Wohneigentum 2038 1.5 Mio", goal_confidence: "95 % — kein Spielraum" }, year: 2026 },
  { data: { goals: "2040 Ferienvilla, 1 Mio" }, year: 2026 },
  { data: { birth_year: 1993 }, year: 2026 },
  { data: {}, year: 2026 },
  { data: { birth_year: 1993, spend_now: 0, goals: "" }, year: 2026 },
];

const netScaleCases = [
  [null, null], [0, 0], [1, 0], [3, 0], [6, 0], [15, 0], [20, 0], [100, 0],
  [0, 1], [0, 3], [0, 5], [3, 2], [20, 4], [null, 3], [6, null],
  ["20", "2"],
];

const expertiseCases = [
  {},
  { education_recent: "nein" },
  { education_recent: "CAS Finanzen" },
  { education_recent: "CAS", education_planned: ["MAS"] },
  { education_recent: "CAS", education_planned: ["MAS"], education_hours: "3–5" },
  { education_hours: "kaum welche" },
  { education_hours: "1–2" },
  { education_hours: "5–10" },
  { education_hours: "mehr als 10" },
  { education_budget: 5000 },
  { education_budget: 4999 },
  { education_recent: "CAS", education_planned: ["a", "b"], education_hours: "mehr als 10", education_budget: 9000 },
  { education_planned: [] },
  { education_recent: "" },
];

const childAgesCases = [
  ["2020 und 2022", 2026],
  ["2015", 2026],
  ["", 2026],
  [null, 2026],
  ["keine", 2026],
  ["1998, 2001 und 2030", 2026],
  ["1950", 2026],
];

const result = {
  _about:
    "Generated from andersCH-prototype/onboarding-chat.html by scratchpad/extract_identities.mjs. " +
    "The reference output the Python reimplementation is held to. Regenerate only if the ORIGINAL changes.",
  source: SOURCE.replace(/\\/g, "/").split("/").slice(-2).join("/"),
  tables: { CONF: identities.CONF, PARTNERED: identities.PARTNERED, MARRIED: identities.MARRIED },
  parseGoalText: goalText.map((text) => ({ in: text, out: identities.parseGoalText(text) })),
  goalsFrom: goalsFromCases.map((c) => ({ in: c, out: identities.goalsFrom(c.data, c.year) })),
  netScale: netScaleCases.map(([people, mandates]) => ({
    in: { people, mandates },
    out: identities.netScale(people, mandates),
  })),
  expertiseScale: expertiseCases.map((d) => ({ in: d, out: identities.expertiseScale(d) })),
  childAges: childAgesCases.map(([text, year]) => ({
    in: { text, year },
    out: identities.childAges(text, year),
  })),
};

writeFileSync(OUT, JSON.stringify(result, null, 2) + "\n", "utf8");
console.log(
  `wrote ${OUT}: ` +
    `${result.parseGoalText.length} parseGoalText, ${result.goalsFrom.length} goalsFrom, ` +
    `${result.netScale.length} netScale, ${result.expertiseScale.length} expertiseScale, ` +
    `${result.childAges.length} childAges`,
);
