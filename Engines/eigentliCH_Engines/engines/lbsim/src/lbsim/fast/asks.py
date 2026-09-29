"""What is missing, ranked by how much it would move the answer -- measured, not assumed.

`architecture/manual-gameplan.html` ranks the things worth asking for: owner-occupied against let, marital
status, the pension certificate, the mortgage's rate and fixing date, one goal with an amount and a year. That
ranking came from five worked cases and it is a good prior. It is also a *fixed* ranking, and the whole point of
having the arithmetic in code is that the ranking does not have to be fixed: for THIS household, the mortgage
rate might move the answer by forty thousand francs a year and the marital status by nothing, or the reverse.

So each candidate gap is probed. The quantities are closed-form -- measured at a few milliseconds for a whole
household -- so the report is recomputed at a plausible low and a plausible high for each unknown, and the ask
is ranked by the **spread it produces in the figures the client actually reads**: the capital the gap implies,
the free cash flow, and the bridge. That is a defensible answer to "why are you asking me this", which "the
manual says it usually matters" is not.

**Three properties this has to have, and each one rules out a simpler design.**

*Only ask what is genuinely unknown.* A question the client already answered is an insult and a question whose
answer the engine already has is noise. Every ask tests the submission first.

*Never invent the answer while probing.* The probe values exist to MEASURE sensitivity and are thrown away.
Nothing here writes a probe into the report, and `probe_low`/`probe_high` travel with the ask so a reader can
see what range produced the number.

*An unanswerable question is worse than none.* Each ask carries the words to put to the client and, where the
answer is a document rather than a number, says which document. "Ask for the insured salary" is actionable;
"more pension detail would help" is not.

**Nothing here is a Recommendation.** These are requests for information, which is the one thing a Befund may
always ask for.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

#: The figures an ask is measured against. Each is something the client reads and acts on, so a franc of
#: movement in one of these is a franc of movement in the answer -- unlike a franc of movement in an
#: intermediate quantity nobody sees.
def _headline(q: dict) -> dict[str, float]:
    gap = q.get("gap") or {}
    cf = q.get("cash_flow") or {}
    br = q.get("bridge") or {}
    rr = q.get("required_return") or {}
    return {
        "Kapitalbedarf": float(rr.get("target") or 0.0),
        "Deckungslücke pro Jahr": float(gap.get("gap") or 0.0),
        "freier Cashflow": float(cf.get("free") or 0.0),
        "Steuern": float(cf.get("income_tax") or 0.0),
        "Brückenbedarf": float(br.get("need") or 0.0),
    }


def _put(sub: dict, block: str, key: str, value: Any) -> dict:
    """A copy of the submission with one engine-visible field set.

    **Written to `state`/`params`, never to `raw`.** `raw` is the interview's own record of the answers and
    the mapping from it to the engine's fields lives in the questionnaire's JavaScript -- so a probe written
    into `raw` would change nothing at all and every ask would measure a spread of zero. That is a silent
    failure, which is why it is stated here rather than discovered later.
    """
    out = copy.deepcopy(sub)
    out.setdefault(block, {})[key] = value
    return out


#: One candidate ask. `patch` is (block, key) into the submission; `low` and `high` bracket a plausible answer.
_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "code": "residence_share",
        "field": "own_use_pct", "kind": "num", "unit": "%",
        "block": "state", "key": "W_res",
        "question": "Welcher Teil Ihrer Liegenschaften ist selbst bewohnt, und welcher vermietet?",
        "why": "Die Miete ist der einzige Kanal, über den eine Liegenschaft den Cashflow erreicht. Ein "
               "selbst bewohntes Objekt ist im Modell vollständig abgeschottet, ein vermietetes wirft "
               "Ertrag ab. Das ist in einem Vermögensblock meist die grösste einzelne Unklarheit.",
        "how": "Der Anteil in Prozent, oder die Werte der beiden Teile.",
        "probe": lambda sub, p: (0.0, float((sub.get("state") or {}).get("W_R") or 0.0)),
        "unknown": lambda sub, raw, p: (raw.get("own_use_pct") is None
                                        and float((sub.get("state") or {}).get("W_R") or 0.0) > 0),
    },
    {
        "code": "civil_status",
        "field": "civil_status", "kind": "opts",
        "options": ["ledig", "ledig, mit Partner", "verheiratet", "eingetragene Partnerschaft", "geschieden", "verwitwet"],
        "block": "params", "key": "tax_split_factor",
        "question": "Sind Sie verheiratet, in eingetragener Partnerschaft, oder keines von beiden?",
        "why": "Vollsplitting gegen den Einzeltarif ist bei einem beruflichen Einkommen ein fünfstelliger "
               "Betrag pro Jahr. Zusammen veranlagt wird nur bei Ehe und eingetragener Partnerschaft, "
               "nicht beim Konkubinat — das ist eine rechtliche Unterscheidung und keine des Wortlauts.",
        "how": "Der Zivilstand genügt.",
        "probe": lambda sub, p: (1.0, 2.0),
        "unknown": lambda sub, raw, p: not raw.get("civil_status"),
    },
    {
        "code": "pillar2_certificate",
        "field": "pillar2", "kind": "num", "unit": "CHF",
        "block": "state", "key": "W_P",
        "question": "Wie hoch ist Ihr Pensionskassenguthaben, und was steht im Vorsorgeausweis zum "
                    "versicherten Lohn, zum Umwandlungssatz und zum Einkaufspotenzial?",
        "why": "Vier Zahlen, die oft die Hälfte des Befundes entscheiden. Der Umwandlungssatz dieses "
               "Berichts ist eine erklärte Annahme; der Ausweis ersetzt sie durch die Ihrer Kasse.",
        "how": "Der Vorsorgeausweis der Pensionskasse, eine Seite.",
        "probe": lambda sub, p: (0.0, max(4.0 * _income(sub), 200_000.0)),
        "unknown": lambda sub, raw, p: raw.get("pillar2") is None,
    },
    {
        "code": "mortgage_rate",
        "field": "mortgage_rate", "kind": "num", "unit": "%",
        "block": "params", "key": "mortgage_rate",
        "question": "Zu welchem Zinssatz läuft Ihre Hypothek, und bis wann ist er fixiert?",
        "why": "Der Schuldendienst ist meist das grösste einzelne Risiko des Haushalts, und jede Zahl im "
               "Cashflow hängt an diesem Satz. Bis zum Ablauf der Fixierung ist er ein Faktum, danach "
               "ein Risiko.",
        "how": "Der Kreditvertrag: Satz und Fälligkeit je Tranche.",
        "probe": lambda sub, p: (0.005, 0.04),
        "unknown": lambda sub, raw, p: (raw.get("mortgage_rate") is None
                                        and (sub.get("params") or {}).get("mortgage_rate") is None
                                        and float((sub.get("state") or {}).get("D") or 0.0) > 0),
    },
    {
        "code": "stop_work_age",
        "field": "stop_work_age", "kind": "num", "unit": "Jahre",
        "block": "params", "key": "stop_work_age",
        "question": "Ab welchem Alter möchten Sie nicht mehr auf Erwerbseinkommen angewiesen sein?",
        "why": "Die Jahre zwischen dem Ausstieg und der Referenzaltersgrenze sind die teuersten des ganzen "
               "Plans: AHV und Pensionskasse setzen erst mit 65 ein, die Säule 3a ab 60. Ohne diese Zahl "
               "ist die Brücke nicht berechenbar.",
        "how": "Ein Zieljahr oder ein Alter.",
        "probe": lambda sub, p: (float(p.ahv_age) - 10.0, float(p.ahv_age) - 1.0),
        "unknown": lambda sub, raw, p: ((sub.get("params") or {}).get("stop_work_age") is None
                                        and raw.get("stop_work_age") is None),
    },
    {
        "code": "spend_now",
        "field": "spend_now", "kind": "num", "unit": "CHF / Jahr",
        "block": "params", "key": "G",
        "question": "Was kostet Ihr Leben heute, ohne Sparen und ohne Steuern?",
        "why": "Die wichtigste Zahl im ganzen Gespräch. Der Kapitalbedarf ist die Differenz zweier grosser "
               "Zahlen geteilt durch einen kleinen Satz, also reagiert er auf diese Angabe stärker als "
               "auf jede andere.",
        "how": "Eine Jahreszahl genügt; ein Kontoauszug über zwölf Monate ist genauer.",
        "probe": lambda sub, p: (0.5 * float(p.G or 0.0), 1.5 * float(p.G or 0.0)),
        "unknown": lambda sub, raw, p: raw.get("spend_now") is None,
    },
    {
        "code": "savings",
        "field": "savings", "kind": "num", "unit": "CHF / Jahr",
        "block": None, "key": None,
        "question": "Wie viel bleibt bei Ihnen pro Jahr tatsächlich übrig?",
        "why": "Der Bericht rechnet den freien Cashflow aus Ihren Angaben. Was Sie selbst als Sparquote "
               "nennen, ist die Gegenprobe — und die Differenz zwischen beiden war in zwei von fünf "
               "Fällen der wichtigste Befund des ganzen Dossiers.",
        "how": "Ergebnis, nicht Vorsatz: Einkommen minus Ausgaben.",
        "probe": None,
        "unknown": lambda sub, raw, p: raw.get("savings") is None,
    },
    {
        "code": "ahv_record",
        "field": "ahv_years_missing", "kind": "num", "unit": "Jahre",
        "block": "params", "key": "ahv_record_share",
        "question": "Fehlen Ihnen AHV-Beitragsjahre — etwa durch Studium, Auslandsaufenthalt oder "
                    "Selbständigkeit?",
        "why": "Ein fehlendes Jahr kostet dauerhaft rund ein Vierundvierzigstel der Rente. Höchstens die "
               "letzten fünf Jahre sind nachzahlbar, und das ist eine Frage an die Ausgleichskasse.",
        "how": "Der IK-Auszug der Ausgleichskasse listet jedes Beitragsjahr.",
        "probe": lambda sub, p: (0.8, 1.0),
        "unknown": lambda sub, raw, p: raw.get("ahv_years_missing") is None,
    },
    {
        "code": "goal_amount_year",
        "field": "goals", "kind": "text",
        "block": None, "key": None,
        "question": "Nennen Sie ein Ziel mit einem Betrag und einem Jahr.",
        "why": "Ein Intake nennt regelmässig fünf bis sieben Absichten und kein Ziel. Ohne Betrag und Jahr "
               "kann die Optimierung nichts prüfen: sie braucht eine Bedingung, die erfüllt oder verfehlt "
               "werden kann.",
        "how": "Ein Satz: was, wie viel, bis wann.",
        "probe": None,
        "unknown": lambda sub, raw, p: not any(
            g.get("amount_chf") and g.get("target_year") for g in (sub.get("goals") or [])),
    },
)


def _income(sub: dict) -> float:
    return float((sub.get("raw") or {}).get("income_gross") or 0.0)


def rank(submission: dict, params: Any, assemble: Callable[..., dict],
         base: dict | None = None) -> list[dict]:
    """Every ask that applies to this household, largest measured effect first.

    `assemble` is passed in rather than imported, because `app.gameplan` imports this module and importing it
    back would be a cycle. It must be called with `with_asks=False` or this recurses once per probe.
    """
    raw = submission.get("raw") or {}
    if base is None:
        base = assemble(submission, None, with_asks=False)
    base_h = _headline(base)

    out: list[dict] = []
    for c in _CANDIDATES:
        try:
            if not c["unknown"](submission, raw, params):
                continue
        except (KeyError, TypeError, ValueError):
            continue

        ask = {"code": c["code"], "question": c["question"], "why": c["why"], "how": c["how"],
               # The interview field this answer belongs in, so the client can answer it in place and the
               # questionnaire's own mapping does the rest. Duplicating that mapping here is how two copies
               # of one rule start.
               "field": c.get("field"), "kind": c.get("kind", "text"),
               "options": list(c.get("options") or []), "unit": c.get("unit", ""),
               "measured": False, "impact": None, "impact_of": None,
               "probe_low": None, "probe_high": None}

        if c["probe"] and c["block"]:
            try:
                lo, hi = c["probe"](submission, params)
                a = _headline(assemble(_put(submission, c["block"], c["key"], lo), None, with_asks=False))
                b = _headline(assemble(_put(submission, c["block"], c["key"], hi), None, with_asks=False))
                # The largest movement in anything the client reads. Reported with its name, because "this
                # moves the answer by 300 000" means nothing without saying which answer.
                spreads = {k: abs(b.get(k, 0.0) - a.get(k, 0.0)) for k in base_h}
                where = max(spreads, key=lambda k: spreads[k])
                ask.update(measured=True, impact=spreads[where], impact_of=where,
                           probe_low=lo, probe_high=hi)
            except Exception:  # noqa: BLE001 - an unmeasurable ask is still worth asking
                pass
        out.append(ask)

    # Measured asks first, by size; then the ones whose effect cannot be bracketed by moving one number --
    # a missing goal changes what is computed at all, not how much, and sorting it as zero would bury it.
    measured = sorted([a for a in out if a["measured"]], key=lambda a: -(a["impact"] or 0.0))
    unmeasured = [a for a in out if not a["measured"]]
    return measured + unmeasured

def summarise(asks: list[dict]) -> dict:
    """How much of the answer is still unsettled, as a figure that shrinks when a question is answered.

    **A statement of what is open, not a score.** A completeness percentage would need a denominator, and any
    denominator here is invented: there is no finite set of everything that could be known about a household,
    so "84 % complete" would be a number with no referent. What IS defensible is the swing the open questions
    can still produce, because every part of it was measured.

    Reported per headline rather than as one total, because the movements are not commensurable: francs of
    capital requirement and francs of annual cash flow do not add up to francs of anything. `largest` names
    the biggest single one so a banner has something to say in one line.
    """
    by_headline: dict[str, float] = {}
    for a in asks:
        if not a.get("measured") or a.get("impact") is None:
            continue
        where = a["impact_of"]
        # The MAXIMUM per headline, not the sum. Two unknowns that each move the capital requirement by
        # 100 000 do not move it by 200 000 -- they may well move it the same way, or cancel. The largest
        # single one is the only claim the probes actually support.
        by_headline[where] = max(by_headline.get(where, 0.0), float(a["impact"]))
    largest = None
    if by_headline:
        of = max(by_headline, key=lambda k: by_headline[k])
        largest = {"amount": by_headline[of], "of": of}
    return {
        "open": len(asks),
        "measured": sum(1 for a in asks if a.get("measured")),
        "unmeasured": sum(1 for a in asks if not a.get("measured")),
        "by_headline": by_headline,
        "largest": largest,
    }
