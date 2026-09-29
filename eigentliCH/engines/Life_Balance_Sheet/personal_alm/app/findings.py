"""The findings that recur, as rules rather than as things somebody remembered to check.

`architecture/manual-gameplan.html` section 16 lists nine patterns that appeared in case after case, each with
how to spot it and why it matters. A list of checks a human is asked to perform is a list of checks a human will
eventually skip, and the five worked dossiers each caught a different subset. So the triggers are transcribed
here, one function per pattern, and every one of them runs on every household.

**Each rule returns the same shape, and every field is load-bearing.**

    code       stable identifier, so a finding can be referred to across reports
    title      what the reader sees
    severity   "blocking" | "high" | "medium" | "note" -- how much of the reader's attention it deserves
    trigger    the condition IN WORDS, next to the figures that satisfied it. A finding that cannot show why
               it fired is an assertion.
    figures    the numbers the trigger used, so the prose layer has a closed set to draw on and the number
               verifier has something to check against
    why        why it matters, from the manual
    action     what to do about it. NOT a Recommendation: "ask", "quantify", "decide between" (G7).
    urgency    "now" | "months" | "year" | "watch" -- what orders the Zeitplan

**Severity and urgency are different axes and collapsing them loses information.** An empty pillar 3a is
"medium" in severity and "now" in urgency: it is small money that is forgone every single year it is not fixed.
A thin liquidity buffer against a large debt is "high" and "now". A missing will with property and no statutory
heir is "high" and "now" and outranks every financial item in the report -- which is why the ordering of the
Zeitplan is by urgency and then severity, not by the order the sections happen to appear in.

**A rule that cannot be evaluated returns None rather than a negative.** "Not triggered" and "not checkable"
are different states, and reporting an unchecked rule as passed is the failure that makes a checklist worse than
no checklist. What could not be checked is collected separately and reported as such.
"""

from __future__ import annotations

from typing import Any, Callable

from ..model.params import Params

#: Severity ranks. Only used for ordering; the strings are what the report renders.
SEVERITY_ORDER = {"blocking": 0, "high": 1, "medium": 2, "note": 3}

#: Urgency ranks. `now` means it costs something every month it is not done; `watch` means nothing is due but
#: the reader should know the condition exists.
URGENCY_ORDER = {"now": 0, "months": 1, "year": 2, "watch": 3}

#: The Zeitplan's groups, one per urgency. Kept next to `URGENCY_ORDER` and checked against it below, because
#: they were two independent dicts that happened to agree: `schedule()` grouped by its own labels and silently
#: discarded any finding whose urgency was not among them.
SCHEDULE_LABELS: dict[str, str] = {
    "now": "Jetzt, vor jeder Anlageentscheidung",
    "months": "In den nächsten Monaten",
    "year": "Im Verlauf des Jahres",
    "watch": "Mitlesen, kein Termin",
}
assert set(SCHEDULE_LABELS) == set(URGENCY_ORDER), "every urgency needs a group in the Zeitplan"


def _f(x: float | None, d: int = 0) -> str:
    return "-" if x is None else f"{x:,.{d}f}".replace(",", " ")


def _d(x: float | None, digits: int = 2) -> str:
    """A decimal number in German notation.

    **Not cosmetic.** These strings are read straight into a German dossier, and a trigger reading
    "4.75-fach" beside a table reading "4,75" tells the reader the two were produced by different hands --
    which was true and is exactly what this layer exists to stop being true.
    """
    if x is None:
        return "-"
    return f"{x:.{digits}f}".replace(".", ",")


def _p(x: float | None, digits: int = 1) -> str:
    """A percentage in German notation. Plain space before the sign, matching `dossier.pc`."""
    if x is None:
        return "-"
    return f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def _finding(code: str, title: str, severity: str, trigger: str, figures: dict,
             why: str, action: str, urgency: str, answers: tuple[str, ...] = ()) -> dict:
    """One finding. `answers` names the INTERVIEW fields whose answers would respond to it.

    **Most actions here are questions in disguise, and the ones that are should be answerable in place.**
    "Den Betrag benennen und ihm eine Verwendung geben" is a request for a figure; the reader should be able to
    give it without going back through the interview. So a finding may name the fields that would.

    **A field only belongs here if answering it changes a computation.** `mortgage_fixed_until` is the
    counter-example and it is deliberately absent: the converter defers it because the model has one mortgage
    rate for the whole horizon and no date on which it resets, so an input would collect an answer that moves
    nothing. The canton was offered that way once and had to be taken back out. An action that cannot be
    answered by a number is still an action -- it stays prose, which is the honest form for a decision.
    """
    return {"code": code, "title": title, "severity": severity, "trigger": trigger,
            "figures": figures, "why": why, "action": action, "urgency": urgency,
            "answers": list(answers)}


def _legal_why(civil: str, household: str, property_total: float) -> str:
    """Why the missing instruments matter, for THIS household.

    One sentence for a cohabiting partner with no statutory claim, another for someone with no partner at
    all. The first version of this rule printed the partner sentence at a widowed single person with five
    million in property, which is the kind of mismatch that makes a reader stop trusting the whole report.
    """
    partnered = "Partner" in civil or bool(household) and household not in ("alleine", "")
    if partnered and not (civil.startswith("verheiratet") or civil.startswith("eingetragen")):
        return ("Bei einer Partnerschaft ohne gesetzliches Erbrecht und mit erheblichem "
                "Liegenschaftsvermögen steht dieser Punkt über jedem finanziellen Posten des Berichts. "
                "Er kostet nichts und ist in Wochen erledigt.")
    if property_total > 0:
        return ("Ohne Testament folgt der Nachlass der gesetzlichen Erbfolge, und bei erheblichem "
                "Liegenschaftsvermögen entscheidet das über die Liegenschaft mit. Ebenso offen ist, wer "
                "handeln darf, wenn die Urteilsfähigkeit fehlt: das regelt ein Vorsorgeauftrag und "
                "sonst niemand. Beides kostet nichts und steht damit über jedem finanziellen Posten "
                "dieses Berichts.")
    return ("Ohne Testament folgt der Nachlass der gesetzlichen Erbfolge, und ohne Vorsorgeauftrag ist "
            "nicht bestimmt, wer bei fehlender Urteilsfähigkeit handeln darf.")


# --- the nine patterns of manual section 16 -------------------------------------------------------------

def wealth_that_cannot_work(q: dict, p: Params, raw: dict) -> dict | None:
    """Drawable under 20 % of total wealth. In three of five worked cases it was."""
    b = q["balance"]
    if b["drawable_share"] is None:
        return None
    if b["drawable_share"] >= 0.20:
        return None
    return _finding(
        "drawable_thin", "Vermögen, das nicht arbeiten kann", "high",
        f"entnahmefähig {_f(b['drawable'])} von {_f(b['total_wealth'])} Gesamtvermögen, "
        f"also {_p(b['drawable_share'])} — die Schwelle des Befundes liegt bei 20 %",
        {"drawable": b["drawable"], "total_wealth": b["total_wealth"],
         "drawable_share": b["drawable_share"], "threshold": 0.20},
        "Das Gespräch über die Anlage betrifft eine kleine Scheibe der Bilanz. Über die Belehnungsspanne "
        "von null bis 65 % schwankt das Nettovermögen um die ganze Hypothek, und das entnahmefähige "
        "Vermögen bewegt sich dabei nicht.",
        "Vor jeder Anlageentscheidung festhalten, worauf sie sich bezieht: auf das entnahmefähige "
        "Vermögen, nicht auf das Gesamtvermögen.",
        "months")


def spending_doubling(q: dict, p: Params, raw: dict) -> dict | None:
    """`spend_later` far above `spend_now`: the goal, not the means, is what fails."""
    now, later = raw.get("spend_now"), raw.get("spend_later")
    if now is None or later is None:
        return None
    now, later = float(now), float(later)
    if now <= 0 or later <= now * 1.25:
        return None
    return _finding(
        "spending_doubling", "Das Ausgabenziel liegt deutlich über heute", "high",
        f"Ausgabenziel {_f(later)} gegen heutige Lebenskosten {_f(now)}, Faktor {_d(later / now)}",
        {"spend_now": now, "spend_later": later, "factor": later / now},
        "In diesen Fällen scheitert das Ziel und nicht das Mittel. Ein Ziel, das über den heutigen "
        "Lebensstandard hinausgeht, verlangt Kapital, das nie für den heutigen Standard nötig war.",
        "Prüfen, ob das Ziel den gewünschten Lebensstandard beschreibt oder eine Sicherheitsmarge "
        "enthält. Beides ist zulässig, aber es sind zwei verschiedene Zahlen.",
        "months",
        answers=("spend_later",))


def undirected_surplus(q: dict, p: Params, raw: dict) -> dict | None:
    """Free cash flow far above the stated saving. The most powerful finding in the set."""
    cf = q["cash_flow"]
    # **Measured against what the household frees, not against what it says it saves.** The stated figure was
    # the yardstick until 21 August 2026, which meant the finding could not fire for anyone who never gave one
    # -- and gave a negative "surplus" for anyone whose stated figure exceeded the arithmetic.
    free, undirected = cf.get("free"), cf.get("undirected")
    if free is None or undirected is None or free <= 0:
        return None
    # A quarter of the free cash flow with no destination is the threshold. Below that the household has
    # essentially allocated what it generates, and saying otherwise would be noise.
    if undirected <= 0.25 * free:
        return None
    return _finding(
        "undirected_surplus", "Ein Überschuss ohne Verwendung", "high",
        f"frei verfügbar {_f(free)}, davon fest verplant {_f(cf.get('committed'))}: "
        f"{_f(undirected)} pro Jahr haben keine Verwendung",
        {"free": free, "committed": cf.get("committed"), "undirected": undirected,
         "stated_saving": cf.get("stated_saving")},
        "Das ist der Befund, der eine unmögliche Renditeanforderung in eine triviale verwandelt. Der "
        "Haushalt erzeugt mehr, als er lenkt, und die Frage ist nicht die Rendite, sondern die "
        "Verwendung des Überschusses.",
        "Den Betrag benennen und ihm eine Verwendung geben. Solange er nicht zugeordnet ist, wird er "
        "verbraucht.",
        "now",
        answers=("savings", "amortisation", "pillar3a_contribution",))


def debt_service_equals_spending(q: dict, p: Params, raw: dict) -> dict | None:
    """i * D approximately equal to G. Then amortisation is the mechanism for the goal, not its rival."""
    cf = q["cash_flow"]
    interest, target = cf["mortgage_interest"], q["gap"]["target_spend"]
    if interest <= 0 or target <= 0:
        return None
    ratio = interest / target
    if not 0.80 <= ratio <= 1.25:
        return None
    return _finding(
        "debt_service_equals_spending", "Der Schuldendienst kostet, was der Haushalt lebt", "high",
        f"Hypothekarzins {_f(interest)} gegen Ausgabenziel {_f(target)}, Verhältnis {_d(ratio)} "
        f"(der Befund greift zwischen 0,80 und 1,25)",
        {"mortgage_interest": interest, "target_spend": target, "ratio": ratio,
         "mortgage_rate": cf["mortgage_rate"], "debt": q["balance"]["debt"]},
        "Damit wird die Amortisation zum Mechanismus des Ziels und nicht zu seinem Rivalen: jeder "
        "getilgte Franken senkt genau die Ausgabe, die das Ziel definiert.",
        "Die Amortisation nicht als Alternative zur Anlage rechnen, sondern als Teil der Zielrechnung. "
        "Beide Wege nebeneinander in Franken pro Jahr stellen.",
        "months")


def thin_liquidity(q: dict, p: Params, raw: dict) -> dict | None:
    """Cash under 2 % of debt. A rate move then forces a sale of the illiquid asset."""
    b = q["balance"]
    if b["debt"] <= 0:
        return None
    share = b["liquid"] / b["debt"]
    if share >= 0.02:
        return None
    cf = q["cash_flow"]
    two_points = 0.02 * b["debt"]
    return _finding(
        "thin_liquidity", "Dünne Liquidität gegen grosse Schulden", "high",
        f"liquide Mittel {_f(b['liquid'])} gegen Schulden {_f(b['debt'])}, also {_p(share, 2)} — "
        f"die Schwelle des Befundes liegt bei 2 %",
        {"liquid": b["liquid"], "debt": b["debt"], "share": share, "threshold": 0.02,
         "cost_of_two_points": two_points, "free": cf["free"],
         "months_covered": (b["liquid"] / (two_points / 12.0)) if two_points else None},
        "Eine Zinsbewegung erzwingt dann den Verkauf des illiquiden Vermögenswerts, und zwar zu dem "
        "Zeitpunkt, den der Markt wählt, nicht der Haushalt.",
        "Eine Reserve festlegen und in Franken benennen, bevor über Anlage oder Amortisation entschieden "
        "wird. Die Grössenordnung ergibt sich aus dem Zinsanstieg, den der Haushalt tragen können will.",
        "now",
        answers=("cash",))


def pension_too_small(q: dict, p: Params, raw: dict) -> dict | None:
    """Pillar 2 under one year's income after 20+ working years: the projection rests on a contradicted past."""
    gross, w_p = raw.get("income_gross"), q["balance"]["pillar2"]
    years = raw.get("work_years_current")
    age = q["age"]
    if gross in (None, 0) or w_p is None:
        return None
    gross = float(gross)
    # 20+ working years is the manual's condition. Where the answer is absent, age is the fallback: at 45 a
    # standard career has 20 years behind it, and saying so is better than skipping the check.
    long_career = (float(years) >= 20.0) if years is not None else (age is not None and age >= 45.0)
    if not long_career or w_p >= gross:
        return None
    return _finding(
        "pension_too_small", "Das Pensionskassenguthaben ist für die Vorgeschichte zu klein", "high",
        f"Guthaben {_f(w_p)} gegen ein Jahreseinkommen von {_f(gross)}, bei einem Erwerbsleben von "
        f"mindestens 20 Jahren",
        {"pillar2": w_p, "income_gross": gross, "ratio": w_p / gross,
         "work_years": float(years) if years is not None else None, "age": age},
        "Die Vorwärtsrechnung stützt sich auf einen Beitrag, den die Vergangenheit widerlegt. Entweder "
        "ist Kapital vorbezogen worden, oder es gibt Beitragslücken, oder ein Teil des Erwerbslebens war "
        "selbständig — und in allen drei Fällen ist die Projektion zu optimistisch.",
        "Den Pensionskassenausweis beschaffen und die Differenz erklären, bevor die Rente ab 65 als "
        "Grundlage dient. Vorbezug, Selbständigkeit und Beitragslücken sind die drei Kandidaten.",
        "months",
        answers=("pillar2", "pillar2_buyin",))


def hours_above_threshold(q: dict, p: Params, raw: dict) -> dict | None:
    """Hours above the model's threshold: the plan consumes the earning power that funds it."""
    h = q["health"]
    if not h.get("hours") or h["hours"] <= h["threshold_hours"]:
        return None
    return _finding(
        "hours_above_threshold", "Die Arbeitszeit liegt über der Schwelle des Modells", "high",
        f"{h['hours']:.0f} Wochenstunden gegen eine Schwelle von {h['threshold_hours']:.0f}: "
        f"Gesundheitsabbau {_d(h['decay_own'], 4)} pro Jahr statt {_d(h['decay_at_threshold'], 4)}, "
        f"also {_d(h['multiple'])}-fach",
        {"hours": h["hours"], "threshold_hours": h["threshold_hours"], "decay_own": h["decay_own"],
         "decay_at_threshold": h["decay_at_threshold"], "multiple": h["multiple"],
         "horizon_years": h["horizon_years"], "endpoint_own": h["endpoint_own"],
         "endpoint_at_threshold": h["endpoint_at_threshold"],
         "earning_power_ratio": h["earning_power_ratio"]},
        "Die Ertragskraft skaliert im Modell mit der Gesundheit, und der Exponent ist 1. Ein "
        "Gesundheitsverhältnis ist deshalb ein Verhältnis der Ertragskraft: der Plan finanziert sich, "
        "indem er verbraucht, was ihn finanziert.",
        "Die Stunden als Finanzgrösse behandeln und die Reduktion mit denselben Franken bewerten wie "
        "eine Anlageentscheidung. Der Betrag steht in der Hebelliste.",
        "now",
        answers=("hours_per_week",))


def empty_pillar3a(q: dict, p: Params, raw: dict) -> dict | None:
    """Balance and contribution both zero at a taxed income: a recurring deduction forgone."""
    b, cf = q["balance"], q["cash_flow"]
    if b["pillar3a"] > 0 or (cf.get("pillar3a_contribution") or 0.0) > 0:
        return None
    if not cf.get("marginal_rate") or cf["gross"] <= 0:
        return None
    cap = cf["pillar3a_cap"]
    return _finding(
        "empty_pillar3a", "Die Säule 3a ist leer, und sie ist leer geblieben", "medium",
        f"Guthaben 0 und Beitrag 0 bei einem Bruttoeinkommen von {_f(cf['gross'])} und einem "
        f"Grenzsteuersatz von {_p(cf['marginal_rate'])}",
        {"cap": cap, "marginal_rate": cf["marginal_rate"], "annual_effect": cap * cf["marginal_rate"],
         "gross": cf["gross"], "interest": p.pillar3a_interest, "available_from": p.pillar3a_age},
        "Ein wiederkehrender Abzug bleibt ungenutzt, und er ist in einer Zeile bezifferbar. Anders als "
        "die meisten Befunde kostet dieser jedes Jahr erneut, in dem er offen bleibt.",
        f"Den Einzahlungsraum von {_f(cap)} pro Jahr klären. Das Guthaben ist ab "
        f"{p.pillar3a_age:.0f} verfügbar und kann damit eine Frühpensionierung mittragen.",
        "now",
        answers=("pillar3a_contribution", "pillar3a",))


def no_legal_documents(q: dict, p: Params, raw: dict) -> dict | None:
    """No legal instruments where there is property and no statutory heir for the partner."""
    docs = raw.get("legal_docs")
    if docs is None:
        return None
    have = [str(x) for x in (docs if isinstance(docs, list) else [docs])]
    has_will = any(x in ("Testament", "Erbvertrag") for x in have)
    nothing = has_will is False
    if not nothing:
        return None
    civil = str(raw.get("civil_status") or "")
    household = str(raw.get("household") or "")
    property_total = q["balance"]["property_total"]
    # The pattern is strongest where the partner has no statutory claim: cohabitation, or a single person with
    # a household. Married with children is a different situation and the finding is a note there.
    exposed = civil.startswith("ledig") or civil.startswith("verwitwet") or "Partner" in civil
    if property_total <= 0 and not exposed:
        return None
    return _finding(
        "no_legal_documents",
        "Keine rechtlichen Instrumente", "high" if exposed and property_total > 0 else "medium",
        f"erfasste Instrumente: {', '.join(have) or 'keine'}; Zivilstand {civil or 'nicht erfasst'}, "
        f"Haushalt {household or 'nicht erfasst'}, Liegenschaften {_f(property_total)}",
        {"documents": have, "civil_status": civil, "household": household,
         "property_total": property_total},
        _legal_why(civil, household, property_total),
        "Testament oder Erbvertrag, Vorsorgeauftrag und Patientenverfügung als eigenen Termin führen, "
        "getrennt von jeder Anlagefrage.",
        "now",
        answers=("legal_docs",))


# --- findings beyond the nine, each one earned by a real submission --------------------------------------

def rate_reset_near(q: dict, p: Params, raw: dict) -> dict | None:
    """The fixed rate ends within three years: until then the interest is a fact, afterwards a risk."""
    until = raw.get("mortgage_fixed_until")
    collected = q.get("collected") or ""
    if until is None or q["balance"]["debt"] <= 0:
        return None
    try:
        until_y = int(float(until))
        now_y = int(collected[:4]) if collected[:4].isdigit() else None
    except (TypeError, ValueError):
        return None
    if now_y is None or until_y - now_y > 3:
        return None
    debt = q["balance"]["debt"]
    return _finding(
        "rate_reset_near", "Die Hypothek läuft innerhalb von drei Jahren aus", "high",
        f"Zinsbindung bis {until_y}, Erhebung {now_y}: {until_y - now_y} Jahre",
        {"fixed_until": until_y, "collected_year": now_y, "debt": debt,
         "cost_per_point": 0.01 * debt, "rate_used": p.i},
        "Bis dahin ist der Zins ein Faktum, danach ein Risiko. Ein Prozentpunkt auf dieser Schuld ist "
        f"{_f(0.01 * debt)} pro Jahr.",
        "Die Anschlussfrage vor dem Ablauf klären und die Reserve auf den Zinsanstieg auslegen, den der "
        "Haushalt tragen können will.",
        "months")


def rate_not_recorded(q: dict, p: Params, raw: dict) -> dict | None:
    """No mortgage rate given: the model's own rate is used and the substitution must be visible.

    The answer reaches `params.mortgage_rate`, not `raw` -- the interview routes it as a parameter because it
    IS one. Checking only `raw` reported "kein Zinssatz erfasst" at a household that had given one, next to a
    cash flow computed at that very rate.
    """
    if q["balance"]["debt"] <= 0:
        return None
    if q["cash_flow"].get("mortgage_rate_is_stated"):
        return None
    debt = q["balance"]["debt"]
    return _finding(
        "rate_not_recorded", "Kein Hypothekarzins erfasst", "note",
        f"Schuld {_f(debt)}, kein Zinssatz erfasst: gerechnet wird mit {_p(p.i, 0)}",
        {"debt": debt, "rate_used": p.i, "cost_per_point": 0.01 * debt},
        "Jede Zahl des Cashflows hängt an diesem Satz. Ein Prozentpunkt entspricht "
        f"{_f(0.01 * debt)} pro Jahr.",
        "Den tatsächlichen Satz und die Zinsbindung nachtragen. Bis dahin ist der Cashflow eine "
        "Rechnung mit einem gesetzten Satz.",
        "months",
        answers=("mortgage_rate",))


def indirect_amortisation(q: dict, p: Params, raw: dict) -> dict | None:
    """Indirect amortisation: the debt does not fall, and the payment is the 3a contribution."""
    mode = str(raw.get("amortisation_mode") or "")
    if not mode.startswith("indirekt"):
        return None
    amount = q["cash_flow"].get("amortisation_indirect")
    return _finding(
        "indirect_amortisation", "Indirekte Amortisation", "note",
        f"Amortisationsart {mode!r}, Betrag {_f(amount)}",
        {"amount": amount, "debt": q["balance"]["debt"]},
        "Die Schuld sinkt nicht, das Guthaben in der Säule 3a wächst. Im Modell ist das keine Tilgung, "
        "sondern Sparen — und es ist dieselbe Zahlung wie der 3a-Beitrag, also nur einmal zu zählen.",
        "Bei jeder Aussage über die Verschuldung mitlesen, dass sie bis zur Pensionierung stehen bleibt.",
        "watch")


def positions_outside_model(q: dict, p: Params, raw: dict) -> dict | None:
    """Recorded wealth the model has no line for. Reported as the omission it is."""
    b = q["balance"]
    if not b["outside_model"]:
        return None
    total = b["outside_total"]
    severe = b["drawable"] > 0 and total > b["drawable"]
    return _finding(
        "positions_outside_model", "Erfasste Positionen ohne Zeile im Modell",
        "high" if severe else "medium",
        "; ".join(f"{o['label']} {_f(o['amount'])}" for o in b["outside_model"])
        + f" — zusammen {_f(total)}, gegen ein entnahmefähiges Vermögen von {_f(b['drawable'])}",
        {"total": total, "drawable": b["drawable"],
         "items": [{"label": o["label"], "amount": o["amount"]} for o in b["outside_model"]]},
        "Diese Beträge stehen in keiner Bilanzzeile des Modells und damit in keiner Rechnung dieses "
        "Berichts. Wo sie das entnahmefähige Vermögen übersteigen, ist das die grösste Auslassung des "
        "Befundes.",
        "Für jede Position getrennt entscheiden, ob sie als Vermögen, als Ertragsquelle oder als "
        "nichts gelten soll. Das Modell kann sie nicht führen, der Bericht kann sie benennen.",
        "months")


def goal_not_computed(q: dict, p: Params, raw: dict) -> dict | None:
    """A goal the household stated and this report did not solve for.

    **Measured on a live submission and the reason this rule exists.** A twenty-four-year-old stated "Eigentum
    kaufen 2037 2 Mio"; the report solved the retirement gap instead, printed the return that target demands,
    and never named his. The deferral is legitimate -- the kind of a free-text goal is genuinely unresolved
    when the same household ticks Wohneigentum, Ferienobjekt and Firma -- but a legitimate deferral that is
    never stated is indistinguishable from an oversight.

    Severity follows the size of what was left out against the size of what was solved: a deferred goal larger
    than the computed target means the report answers the smaller of the two questions.
    """
    deferred = q.get("goals_deferred") or []
    named = [g for g in deferred if g.get("description")]
    if not named:
        return None
    rr = q.get("required_return") or {}
    target = float(rr.get("target") or 0.0)
    amounts = [float(g["amount_chf"]) for g in named if g.get("amount_chf")]
    biggest = max(amounts) if amounts else 0.0
    # **A target of zero is the severe case, not an exempt one.** Zero means the flows at 65 already cover
    # the spending target, so the report concludes there is nothing to build -- and concluding that while a
    # stated two-million goal sits uncomputed is the most misleading version of this finding, not the mildest.
    # The first version required `target > 0` and rated exactly that case medium.
    severe = biggest > 0 and (target <= 0 or biggest >= target)
    return _finding(
        "goal_not_computed",
        "Ein genanntes Ziel ist in dieser Rechnung nicht enthalten",
        "high" if severe else "medium",
        "; ".join(
            f"\u00ab{g['description']}\u00bb"
            + (f" ({_f(float(g['amount_chf']))}" if g.get("amount_chf") else " (ohne Betrag")
            + (f" bis {int(g['target_year'])})" if g.get("target_year") else ", ohne Jahr)")
            for g in named)
        + (f" — gerechnet wurde gegen {_f(target)}" if target else ""),
        {"deferred": named, "target_solved": target, "largest_deferred": biggest},
        " ".join(dict.fromkeys(g.get("reason") or "" for g in named)).strip()
        + (" Der Bericht kommt ohne dieses Ziel zum Schluss, dass kein Kapital zu bilden ist."
           if biggest > 0 and target <= 0 else
           " Der Bericht rechnet damit gegen ein kleineres Ziel als das genannte." if severe else
           " Der Bericht rechnet gegen ein anderes Ziel als dieses."),
        "Die Art des Ziels festlegen: selbst bewohntes Wohneigentum, Ferienobjekt oder Firma. Danach "
        "rechnet der Bericht dagegen. Ohne diese Festlegung bleibt das Ziel genannt und ungerechnet.",
        "now")


def own_share_only(q: dict, p: Params, raw: dict) -> dict | None:
    """Wealth recorded as the subject's own share: the household balance sheet is incomplete by construction."""
    scope = str(raw.get("asset_scope") or "")
    if not scope.startswith("nur mein"):
        return None
    return _finding(
        "own_share_only", "Erfasst ist der eigene Anteil, nicht der Haushalt", "medium",
        f"Erfassungsumfang {scope!r}",
        {"net_worth": q["balance"]["net_worth"], "drawable": q["balance"]["drawable"]},
        "Die Vorsorge des Partners ist separat erfasst, das übrige Vermögen des Partners fehlt. Die "
        "Haushaltsbilanz ist entsprechend unvollständig und die Unabhängigkeitsrechnung zu tief.",
        "Entscheiden, ob der Bericht den eigenen Anteil oder den Haushalt beschreiben soll, und die "
        "Erfassung entsprechend vervollständigen. Ein halbierter Schuldanteil neben einem vollen "
        "Liegenschaftswert unterschätzt die Belehnung um den Faktor zwei.",
        "months",
        answers=("asset_scope",))


def unmarried_tax_overstated(q: dict, p: Params, raw: dict) -> dict | None:
    """The converter's single tariff on a joint base. Corrected here, and the correction is stated."""
    cf = q["cash_flow"]
    if not cf.get("unmarried_correction_applied") or not cf.get("tax_overstatement"):
        return None
    return _finding(
        "unmarried_tax_overstated", "Steuerkorrektur für die unverheiratete Partnerschaft", "note",
        f"gemeinsame Bemessung zum Einzeltarif ergäbe {_f(cf['income_tax_joint_base'])}, getrennte "
        f"Veranlagung {_f(cf['income_tax_separate'])}: Differenz {_f(cf['tax_overstatement'])}",
        {"joint_base": cf["income_tax_joint_base"], "separate": cf["income_tax_separate"],
         "overstatement": cf["tax_overstatement"]},
        "Der Konverter setzt für „ledig, mit Partner“ richtig keinen Splittingfaktor, rechnet das "
        "Partnereinkommen aber in dieselbe Bemessungsgrundlage. Tatsächlich wird getrennt veranlagt.",
        "Dieser Bericht rechnet mit der korrigierten Zahl. Die Differenz ist hier ausgewiesen, damit "
        "sie gegen eine Steuererklärung geprüft werden kann.",
        "watch")


def stop_age_missing(q: dict, p: Params, raw: dict) -> dict | None:
    """No stop-work age. The bridge is the most under-estimated part of an early-retirement plan."""
    if q.get("bridge") is not None:
        return None
    if raw.get("stop_work_age") is not None:
        return None
    # Only worth reporting where the intake suggests an early stop is actually wanted.
    hint = " ".join(str(raw.get(k) or "") for k in ("goals", "work_plan", "main_question")).lower()
    wants = any(t in hint for t in ("nicht mehr arbeiten", "frühpension", "fruehpension",
                                    "aufhören", "aufhoeren", "reduzieren", "mandate"))
    if not wants:
        return None
    return _finding(
        "stop_age_missing", "Das Wunschalter für den Ausstieg fehlt", "medium",
        "Der Fragebogen erfasst kein Ausstiegsalter, die Ziele nennen aber einen Ausstieg",
        {"reference_age": p.ahv_age, "pillar3a_age": p.pillar3a_age},
        "Ohne Ausstiegsalter ist die Brücke bis 65 nicht berechenbar, und sie ist der am stärksten "
        "unterschätzte Teil jedes Frühpensionierungsplans: die AHV und die Pensionskasse setzen erst "
        f"mit {p.ahv_age:.0f} ein, die Säule 3a ab {p.pillar3a_age:.0f}.",
        "Ein Zieljahr für den Ausstieg festlegen. Danach ist die Brücke eine Rechnung und keine "
        "Schätzung.",
        "months",
        answers=("stop_work_age",))


def goal_not_fundable(q: dict, p: Params, raw: dict) -> dict | None:
    """The engine converged and the answer is that the goal is out of reach (M79)."""
    facts = q.get("plan")
    if not facts or facts.get("outcome") != "goal_not_fundable":
        return None
    return _finding(
        "goal_not_fundable", "Dieses Ziel liegt nicht innerhalb dieser Mittel", "blocking",
        f"Der Solver ist durchgelaufen. Erreicht in {_p(facts.get('p_goal') or 0, 0)} der "
        f"Verläufe, verlangt sind {_p(facts.get('required_confidence') or 0, 0)}",
        {"shortfall": facts.get("shortfall"), "p_goal": facts.get("p_goal"),
         "required_confidence": facts.get("required_confidence"),
         "goal_epsilon": facts.get("goal_epsilon"),
         "achievable_amount": facts.get("achievable_amount"),
         "achievable_p_goal": facts.get("achievable_p_goal"),
         "achievable_full_deadline_years": facts.get("achievable_full_deadline_years")},
        "Das ist ein Befund und keine Panne. Jeder Plan, der dieses Ziel erreicht, ist unzulässig, und "
        "ein Plan, der es verfehlt, ist nicht der Plan, nach dem gefragt wurde. Was sich ändern lässt, "
        "ist das Ziel — seine Höhe, sein Datum, die verlangte Sicherheit — oder die Mittel.",
        "Die Höhe, das Datum und die verlangte Sicherheit einzeln durchrechnen. Was mit diesen Mitteln "
        "erreichbar ist, steht daneben — als Messung, nicht als Zielvorschlag.",
        "now")


#: Every rule, in the order the report checks them. The order here does not determine the report's order:
#: findings are sorted by severity and urgency. It determines only the order of evaluation, which matters
#: solely for reproducibility of the list.
RULES: tuple[Callable[[dict, Params, dict], dict | None], ...] = (
    goal_not_fundable,
    thin_liquidity,
    no_legal_documents,
    hours_above_threshold,
    undirected_surplus,
    debt_service_equals_spending,
    wealth_that_cannot_work,
    pension_too_small,
    empty_pillar3a,
    spending_doubling,
    positions_outside_model,
    rate_reset_near,
    rate_not_recorded,
    goal_not_computed,
    own_share_only,
    stop_age_missing,
    indirect_amortisation,
    unmarried_tax_overstated,
)


def evaluate(quantities: dict, p: Params, raw: dict) -> tuple[list[dict], list[str]]:
    """Run every rule. Returns the findings that fired, and the codes that could not be checked.

    **The second list is not a diagnostic detail.** A rule that returned None because the answer it needs is
    missing is a rule that did not run, and a report that presents an unchecked rule as passed is worse than a
    report with no checklist. The renderer states them.
    """
    fired: list[dict] = []
    unchecked: list[str] = []
    for rule in RULES:
        try:
            got = rule(quantities, p, raw)
        except (KeyError, TypeError, ValueError) as exc:
            # A rule that raises is a defect in the rule, not in the household. It is reported as unchecked
            # rather than allowed to take the whole report down: nine other findings are still worth having.
            unchecked.append(f"{rule.__name__}: {type(exc).__name__}: {exc}")
            continue
        if got is not None:
            fired.append(got)
    fired.sort(key=lambda f: (URGENCY_ORDER.get(f["urgency"], 9),
                              SEVERITY_ORDER.get(f["severity"], 9), f["code"]))
    return fired, unchecked


def schedule(findings: list[dict]) -> list[dict]:
    """The Zeitplan: the findings' actions, grouped by when they are due.

    This is a sort, not a judgement. Every entry is an action a finding already carried, and the grouping is
    the finding's own urgency. A schedule assembled by hand is a schedule whose order somebody chose; this one
    can be checked against the findings above it.
    """
    out = []
    for key, label in SCHEDULE_LABELS.items():
        items = [f for f in findings if f["urgency"] == key]
        if items:
            out.append({"when": key, "label": label,
                        "items": [{"code": f["code"], "title": f["title"],
                                   "action": f["action"], "severity": f["severity"]} for f in items]})
    # **Nothing is dropped for having an urgency this function does not know.** A rule of mine was written
    # with `urgency="weeks"`, which is not in the vocabulary: the finding fired, appeared in the findings
    # list, and vanished from the schedule -- the one list a client acts from. A typo should degrade to a
    # visible oddity, not to an absence, so anything unrecognised is grouped and labelled as such.
    stray = [f for f in findings if f["urgency"] not in SCHEDULE_LABELS]
    if stray:
        out.append({"when": "unsorted",
                    "label": "Ohne Einordnung — ein Befund ohne gültige Dringlichkeit (Fehler im Regelwerk)",
                    "items": [{"code": f["code"], "title": f["title"],
                               "action": f["action"], "severity": f["severity"]} for f in stray]})
    return out
