"""The registry branch 2 was missing: a question about this member, answered by running something.

===========================================================================================================
WHY THIS EXISTS
===========================================================================================================

`services/router` classifies a question about the member's own situation as `MEMBER_SITUATION`, and marks
the boundary it crosses `per_member_computation` — described in that module as *"the first boundary.
Begins at the Life Balance Sheet"*. The answer path then retrieves prose, hands a local model the
passages, and quotes the sentences it points at.

**So the boundary is named after an engine that the answer path never calls.** Over the ten loaded
members, the Know answered the member's own opening question in one case out of ten, and that one was a
quotation from the WEFV. The other nine were not nine missing documents. A member asking "how do I afford
a home by 2035, and what would I have to give up" is not asking for a passage; the answer is arithmetic,
and this build has had the arithmetic all along in `services/property`.

This registry closes that. A question that matches a registered computation is answered by RUNNING it.

===========================================================================================================
WHAT A COMPUTED ANSWER MAY AND MAY NOT SAY
===========================================================================================================

C-01 is untouched and unweakened. Three things hold it:

1. **The router still runs first.** A question that asks what to *do* is branch 3 and never reaches here.
2. **A computation states a measurement, never a course of action.** «Your deposit is reached and the
   carrying cost is 2.2 times what your income allows» is a finding; «so buy something cheaper» is not,
   and no renderer here writes the second kind.
3. **`know.check_answer` still runs on the rendered text before it is emitted.** The outbound gate does
   not get to be skipped because the words came from arithmetic instead of from a book. If a renderer
   drifts into advice, the member sees the boundary.

The shape is `optim/achievable.py`'s in the engine, whose docstring puts it best: *"It is a Befund, not a
Recommendation… Nothing here says anyone should want X."*

===========================================================================================================
WHAT IT REFUSES
===========================================================================================================

A computation with a missing input **does not run**. It reports which input is missing, which is a better
answer than a number built on a default: `Undetermined` carries the keys, and branch 2's existing
`missing_personal_input` already exists to ask for exactly that kind of thing.

And a registered computation that matches nothing falls through to retrieval unchanged. This is an
addition to the answer path, not a replacement for it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session

#: Every computation's answer carries this instead of a document citation. R-171 requires a member to be
#: able to see where words came from; for a computed answer that is the service and the record it read,
#: not a page.
KIND = "computation"


@dataclass(frozen=True)
class Determined:
    """A computation that ran. `text` is what the member reads."""

    key: str
    text: str
    #: Every figure that went in, with where it came from. The audit trail for one answer.
    inputs: dict = field(default_factory=dict)
    #: Service and content record, so a reader can go and check.
    sources: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    determined: bool = True


@dataclass(frozen=True)
class Undetermined:
    """A computation that matched but could not run, and exactly what is missing."""

    key: str
    missing: list
    text: str = ""
    caveats: list = field(default_factory=list)

    determined: bool = False


@dataclass(frozen=True)
class Computation:
    """One thing this build can work out about a member, and the words that reach it."""

    key: str
    #: What the computation is, in one line, for a curator reading the registry.
    about: str
    #: All of these must appear for the question to match. Lower-cased, matched as whole words.
    any_of: tuple
    #: At least one of these must appear too, where given. Narrows a term that is too common alone.
    and_any_of: tuple = ()
    run: Callable[..., object] = None
    sources: tuple = ()


def _words(text: str) -> set:
    return set(re.findall(r"[a-zà-ÿäöüß]+", (text or "").lower()))


def _chf(value) -> str:
    return "—" if value is None else f"{round(value):,}".replace(",", "'")


def _de(value, digits=2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


# ============================================================ the computations


def _property_affordability(session: Session, *, member_id: str, language: str = "de"):
    """Both tests on a member's own property goal: the deposit, and what the loan costs.

    **The one that answers Levin.** He asked how to afford a home by 2035 and what he would have to give
    up; the mandate told him his goal needed 31.3 % a year, because it targets the whole purchase price.
    The deposit is reachable. The carrying cost is not, and that is a different conversation.
    """
    from . import goals as goal_service
    from . import property as prop

    record = prop._record()
    occupancy, affordability = record["occupancy"], record["affordability"]

    goal = None
    for candidate in goal_service.list_goals(session, member_id=member_id)["goals"]:
        text = f"{candidate.get('name') or ''} {candidate.get('description') or ''}"
        if re.search(r"eigenheim|eigentum|wohneigentum|ferienhaus|haus|wohnung", text, re.I):
            if candidate.get("target_amount"):
                goal = candidate
                break
    if goal is None:
        return Undetermined(key="property_affordability", missing=["a property goal with a price"])

    price = float(goal["target_amount"])
    income = _gross_income(session, member_id=member_id)
    if not income:
        return Undetermined(key="property_affordability", missing=["income_gross"])

    allowed = income * affordability["max_share_of_gross_income"]
    # **The goal may already carry the answer.** Occupancy is a question the member can answer, and where
    # they have, showing all three cases would be pretending not to know.
    answered = goal.get("occupancy")
    keys = ((answered,) if answered in occupancy
            else ("owner_occupied_primary", "second_or_holiday_home", "let_to_someone_else"))
    lines = []
    for key in keys:
        rule = occupancy[key]
        equity = price * rule["equity_min"]
        mortgage = price - equity
        amortisation = (max(0, mortgage - price * affordability["first_mortgage_max"])
                        / affordability["amortisation_years"])
        cost = (mortgage * affordability["imputed_rate"]
                + price * affordability["maintenance_and_ancillary"] + amortisation)
        label = (rule.get("label") or {}).get("de", key)
        if not rule.get("affordability_is_determinable", True):
            lines.append(f"{label}: Eigenmittel {_chf(equity)}. Die Tragbarkeit ist hier nicht "
                         f"bestimmbar, weil das Modell keinen Mietertrag führt.")
            continue
        lines.append(f"{label}: Eigenmittel {_chf(equity)}, kalkulatorische Kosten {_chf(cost)} im Jahr "
                     f"gegen {_chf(allowed)}, die ein Drittel des Bruttoeinkommens zulässt — das "
                     f"{_de(cost / allowed)}-Fache.")

    text = (f"Ihr Wohnziel nennt {_chf(price)}. Zwei Prüfungen entscheiden darüber, und sie sind "
            f"unabhängig voneinander: die Eigenmittel und die Tragbarkeit. Welche Nutzung gilt, ist "
            f"nicht erfasst, deshalb stehen hier alle drei Fälle.\n\n" + "\n".join(lines) +
            f"\n\nDer kalkulatorische Zins von {_de(affordability['imputed_rate'] * 100, 0)} % ist eine "
            f"Prüfkonvention und keine Prognose: er liegt bewusst über jedem Zins, der heute angeboten "
            f"wird.")
    return Determined(
        key="property_affordability", text=text,
        inputs={"price": price, "income_gross": income, "allowed": allowed},
        sources=["services/property", "client/content/property-conventions.json"],
        caveats=([] if answered in occupancy
                 else ["Die Nutzungsfrage ist unbeantwortet und entscheidet über den "
                       "Eigenmittelsatz sowie darüber, ob Vorsorgekapital eingesetzt werden darf."]),
    )


def _earning_power(session: Session, *, member_id: str, language: str = "de"):
    """What the model says a person could earn, and at what working time."""
    from . import human_capital as hc

    answers = _answers(session, member_id=member_id)
    capitals = hc.capitals(answers)
    missing = [c.key for c in (capitals.E, capitals.N) if not c.known]
    if missing:
        keys = {"E": "qualification_highest", "N": "network_people"}
        return Undetermined(key="earning_power", missing=[keys[k] for k in missing])
    if hc._number(answers.get("age")) is None:
        return Undetermined(key="earning_power", missing=["age"])

    power = hc.earning_power(answers)
    if power is None:
        return Undetermined(key="earning_power", missing=["the Life Balance Sheet engine"])

    hours = hc._number(answers.get("hours_per_week"))
    text = (f"Nach dem Modell liegt Ihre Verdienstfähigkeit bei {_chf(power.monthly_standardised)} "
            f"im Monat für eine 100-Prozent-Stelle, also {_chf(power.annual_at_forty_hours)} im Jahr. "
            f"Diese Zahl ist an die Medianlöhne der Schweizerischen Lohnstrukturerhebung 2024 geknüpft "
            f"und gilt für Ihren Abschluss und Ihr Netzwerk.")
    if hours:
        # **Health multiplies income and not earning power**, so it belongs here and not in the figure
        # above. Leaving it out overstated Levin by fifteen per cent — his H is 0.85 — which is exactly
        # the direction the record warns about when health is missing, arrived at by forgetting it
        # instead.
        at_hours = power.annual_at_forty_hours * hours / 40
        health = capitals.H.value
        if health is None:
            text += (f" Bei den {_de(hours, 0)} Stunden pro Woche, die Sie angegeben haben, entspricht "
                     f"das {_chf(at_hours)} im Jahr — bei voller Gesundheit gerechnet, weil dazu keine "
                     f"Angabe vorliegt, und damit eher zu hoch.")
        else:
            text += (f" Bei den {_de(hours, 0)} Stunden pro Woche und der Belastbarkeit von "
                     f"{_de(health)}, die Sie angegeben haben, entspricht das "
                     f"{_chf(at_hours * health)} im Jahr.")
    text += ("\n\nEin Medianlohn ist keine Prognose für eine einzelne Person: die Hälfte aller "
             "Beschäftigten in einer Kategorie verdient weniger und die Hälfte mehr.")
    return Determined(
        key="earning_power", text=text,
        inputs={"E": capitals.E.value, "N": capitals.N.value, "H": capitals.H.value,
                "responsibility": power.responsibility},
        sources=["services/human_capital", "knowledge/BFS_Lohnstrukturerhebung.md"],
        caveats=list(power.caveats),
    )


def _time_allocation(session: Session, *, member_id: str, language: str = "de"):
    """Where the marginal hour could go, and what each option produces. Options, never a choice."""
    from . import time_allocation as ta

    answers = _answers(session, member_id=member_id)
    try:
        result = ta.frontier(answers)
    except ta.EngineUnavailable:
        return Undetermined(key="time_allocation", missing=["the Life Balance Sheet engine"])
    except ValueError as error:
        needed = str(error).split("Missing: ")[-1]
        return Undetermined(key="time_allocation",
                            missing=[part.strip() for part in needed.split(",")])

    lines = [f"· {option.label['de']} — {option.consequence['de']}"
             for option in [result.current, *result.options]]
    text = ("Die knappe Grösse in diesem Modell ist nicht das Geld, sondern die Zeit. Was eine "
            "Verschiebung von fünf Stunden pro Woche bewirkt, steht hier für jede Richtung:\n\n"
            + "\n".join(lines) +
            "\n\nWelche davon zu Ihnen passt, sagt diese Rechnung nicht. Sie zeigt, was jede kostet "
            "und was jede bringt.")
    return Determined(
        key="time_allocation", text=text,
        inputs={"productive_week_hours": result.productive_week_hours,
                "options": len(result.options) + 1},
        sources=["services/time_allocation", "engines/Life_Balance_Sheet"],
        caveats=list(result.caveats),
    )


# ============================================================ the registry


def _stocks(session: Session, *, member_id: str) -> dict:
    """Every recorded BALANCE, by label. Flows are excluded and that exclusion is the point.

    The first composed answers produced from this member's record added a salary to four balances and
    reported the total as their wealth — twice, on two different models. Both numbers were real and the
    sentence was false. A stock and a flow are not addable, so the addition happens here, once, where a
    unit can be checked, rather than in a language model's head.
    """
    from sqlalchemy import select

    from ..models import FLOW_UNIT, Position

    out: dict[str, float] = {}
    for position in session.execute(
        select(Position).where(Position.member_id == member_id, Position.active.is_(True),
                               Position.magnitude.is_not(None))
    ).scalars():
        if position.magnitude_unit == FLOW_UNIT or position.role == "income":
            continue
        label = position.label or position.capital_type or position.id
        out[label] = out.get(label, 0) + float(position.magnitude)
    return out


def _retirement_provision(session: Session, *, member_id: str, language: str = "de"):
    """What the second pillar reaches by the reference age, and what it converts to.

    **The question thirty-six people asked in some form on 20 September 2026** — "wie gross ist meine
    Vorsorgelücke wirklich", "was fehlt mir, um mit 60 aufzuhören", "reicht das im Alter" — and the one
    the corpus could never answer, because the answer is this member's balance carried forward at the
    statutory rate and nothing in any Merkblatt knows their balance.

    It does not compute a "Lücke". A gap is a difference against a target standard of living, and this
    build has no approved record of what a member needs to live on; inventing one to subtract from would
    be the estimate that C-07 and R-020 both exist to prevent. What it computes is the provision — the
    capital and the pension the rule produces — and it states the two figures beside whatever the member
    themselves said they expect to spend. The subtraction is then the member's, with both numbers visible.
    """
    from . import pension_projection as pp

    answers = _answers(session, member_id=member_id)
    age = answers.get("age")
    try:
        age = int(age)
    except (TypeError, ValueError):
        return Undetermined(key="retirement_provision", missing=["age"])

    stocks = _stocks(session, member_id=member_id)
    pillar2 = sum(value for label, value in stocks.items()
                  if re.search(r"pensionskasse|zweite s|2\. s|bvg|freiz", label, re.I))
    income = _gross_income(session, member_id=member_id)
    if not income:
        return Undetermined(key="retirement_provision", missing=["income_gross"])

    try:
        result = pp.project(current_age=age, opening_balance=pillar2, gross_salary=income)
    except pp.ProjectionNotApproved:
        return Undetermined(key="retirement_provision",
                            missing=["an approved pension projection record"])

    yearly = result.monthly_pension * 12
    lines = [
        f"Ihr erfasstes Guthaben in der zweiten Säule beträgt {_chf(pillar2)}, Ihr Bruttoeinkommen "
        f"{_chf(income)}.",
    ]
    if result.coordinated is None:
        lines.append("Ihr Lohn liegt unter der Eintrittsschwelle, deshalb wird obligatorisch nichts "
                     "gutgeschrieben.")
    else:
        lines.append(
            f"Auf dem koordinierten Lohn von {_chf(result.coordinated)} schreibt das Obligatorium bis "
            f"zum Referenzalter {result.to_age} insgesamt {_chf(result.total_credited)} gut, dazu "
            f"{_chf(result.total_interest)} Zins zum gesetzlichen Mindestsatz von "
            f"{_de(result.interest_rate * 100)} %.")
    lines.append(
        f"Das ergibt bei unverändertem Lohn {_chf(result.closing_balance)} im Alter {result.to_age}, "
        f"was zum Mindestumwandlungssatz von {_de(result.conversion_rate * 100)} % eine Rente von "
        f"{_chf(yearly)} im Jahr ergibt, also {_chf(result.monthly_pension)} im Monat.")

    spend = answers.get("spend_later") or answers.get("G")
    if spend:
        try:
            lines.append(
                f"Sie haben angegeben, ab dem Aufhören {_chf(float(spend))} im Jahr zu brauchen. Die "
                f"Differenz zu dieser Rente deckt, was AHV, Säule 3a und Ihr übriges Vermögen tragen "
                f"müssen.")
        except (TypeError, ValueError):
            pass

    other = {label: value for label, value in stocks.items()
             if not re.search(r"pensionskasse|zweite s|2\. s|bvg|freiz", label, re.I)}
    if other:
        lines.append("Daneben erfasst, ohne dass hier etwas davon angerechnet wäre: "
                     + ", ".join(f"{label} {_chf(value)}" for label, value in sorted(other.items()))
                     + ".")

    return Determined(
        key="retirement_provision", text="\n\n".join(lines),
        inputs={"age": age, "pillar2": pillar2, "income_gross": income,
                "closing_balance": result.closing_balance, "yearly_pension": yearly},
        sources=["services/pension_projection", "content/pension-projection.json"],
        caveats=[
            "Nur das Obligatorium. Ein überobligatorischer Teil ist hier nicht sichtbar und erhöht die "
            "Zahl.",
            "Der Lohn wird bis zum Referenzalter unverändert fortgeschrieben.",
            "Der Zinssatz ist der gesetzliche Mindestsatz und keine Renditeprognose.",
        ],
    )


def _wealth_concentration(session: Session, *, member_id: str, language: str = "de"):
    """How much of the recorded wealth sits in one place. Arithmetic over balances, nothing else.

    Answers "wie viel meines Vermögens hängt an der eigenen Firma, und ist das zu viel", "wie viel Krypto
    darf im Depot bleiben" and "ist die Belehnung auf beiden Liegenschaften noch tragbar" in its first
    half — the share — and deliberately not in its second. What share is too much is a judgement about
    this member's ability to bear a loss, and this build does not hold a rule that decides it.
    """
    stocks = _stocks(session, member_id=member_id)
    total = sum(stocks.values())
    if not stocks or total <= 0:
        return Undetermined(key="wealth_concentration", missing=["at least one recorded balance"])

    ordered = sorted(stocks.items(), key=lambda pair: -pair[1])
    lines = [f"Ihr erfasstes Vermögen beträgt {_chf(total)}, verteilt auf {len(stocks)} Positionen:"]
    for label, value in ordered:
        lines.append(f"  {label}: {_chf(value)} — {_de(value / total * 100, 1)} %")
    top, top_value = ordered[0]
    lines.append(
        f"Die grösste Position ist {top} mit {_de(top_value / total * 100, 1)} % des erfassten "
        f"Vermögens. Ob dieser Anteil zu hoch ist, hängt davon ab, was ein Verlust auf dieser Position "
        f"für Ihre Ziele bedeuten würde — dazu ist hier keine Regel hinterlegt.")
    return Determined(
        key="wealth_concentration", text="\n".join(lines),
        inputs={"total": total, "positions": dict(ordered)},
        sources=["services/computations", "die erfassten Positionen"],
        caveats=["Nur was als Position erfasst ist. Was nicht erfasst ist, fehlt auch im Anteil."],
    )


REGISTRY: tuple = (
    Computation(
        key="property_affordability",
        about="Both property tests on the member's own goal: the deposit, and the carrying cost.",
        any_of=("eigenheim", "eigentum", "wohneigentum", "haus", "wohnung", "ferienhaus",
                "immobilie", "hypothek", "kaufen", "leisten"),
        and_any_of=("kann", "könnte", "wie", "wann", "was", "reicht", "genug", "leisten",
                    "finanzieren", "tragbar", "eigenmittel"),
        run=_property_affordability,
        sources=("services/property", "client/content/property-conventions.json"),
    ),
    Computation(
        key="earning_power",
        about="What the model says the member could earn, from education, network, health and hours.",
        any_of=("verdienen", "verdienst", "lohn", "gehalt", "einkommen", "verdienstfähigkeit",
                "salär"),
        and_any_of=("könnte", "kann", "wie", "viel", "mehr", "steigern", "erhöhen", "wert"),
        run=_earning_power,
        sources=("services/human_capital", "knowledge/BFS_Lohnstrukturerhebung.md"),
    ),
    #: Before `earning_power` and `time_allocation` on purpose. First match wins, and "was bringt mir das
    #: im Alter" carries `bringt`, which `time_allocation` claims — so a retirement question asked in the
    #: ordinary way would have been answered with a working-hours table. Registry order is the rule and
    #: this is what the rule is for.
    Computation(
        key="retirement_provision",
        about="The second pillar carried to the reference age, and the pension it converts to.",
        any_of=("vorsorge", "vorsorgelücke", "vorsorgeluecke", "rente", "pensionierung",
                "pensionskasse", "altersvorsorge", "ruhestand", "aufhören", "aufhoeren",
                "frühpensionierung", "fruehpensionierung", "altersrente", "altersvorsorge"),
        and_any_of=("wie", "gross", "gross?", "reicht", "genug", "wieviel", "viel", "was", "wann",
                    "fehlt", "lücke", "luecke", "kann", "könnte", "koennte", "früh", "frueh"),
        run=_retirement_provision,
        sources=("services/pension_projection", "content/pension-projection.json"),
    ),
    Computation(
        key="wealth_concentration",
        about="What share of the recorded wealth sits in the largest single position.",
        any_of=("vermögen", "vermoegen", "depot", "klumpen", "anteil", "krypto", "aktien",
                "firma", "unternehmen", "beteiligung", "konzentration", "streuung"),
        and_any_of=("wie", "viel", "anteil", "hängt", "haengt", "zu", "gross", "prozent",
                    "verteilt", "abhängig", "abhaengig", "risiko"),
        run=_wealth_concentration,
        sources=("services/computations",),
    ),
    Computation(
        key="time_allocation",
        about="What moving hours between work, learning, networking and rest produces.",
        any_of=("zeit", "stunden", "arbeitszeit", "pensum", "weiterbildung", "verzichten",
                "aufwand"),
        and_any_of=("mehr", "weniger", "verschieben", "reduzieren", "investieren", "lohnt",
                    "bringt", "müsste", "soll", "was"),
        run=_time_allocation,
        sources=("services/time_allocation", "engines/Life_Balance_Sheet"),
    ),
)


#: Below this, a term must match a whole word. At or above it, a word that STARTS with the term counts.
#:
#: **German is why, and the measurement is why the number is five.** `wealth_concentration` lists
#: `vermögen`; a member wrote "wie viel meines Vermögens hängt an einer einzigen Position" and matched
#: nothing, because the genitive is a different string. Compounds do the same thing — `vorsorgelücke`
#: against `vorsorge`, `frühpensionierung` against `pension` — and a registry of exact words cannot hold
#: a language that builds them.
#:
#: Five, because four admits `alte` into `alternativ` and `rent` into `rentabel`, and because every term
#: in the registry that needs this is longer: the short ones (`wie`, `viel`, `was`, `kann`) are the
#: question words, they are already whole, and prefix-matching them would match most of the language.
_STEM_MIN = 5


def _carries(words: set, terms) -> bool:
    """Whether the question carries any of these terms, allowing a German ending on the longer ones."""
    for term in terms:
        if term in words:
            return True
        if len(term) >= _STEM_MIN and any(word.startswith(term) for word in words):
            return True
    return False


def match(question: str) -> Computation | None:
    """The one computation this question asks for, or `None`.

    **First match wins and the registry order is the rule**, the same convention as
    `tools/read_qualifications`. A question that reads as two computations is a question that needs
    splitting, and answering half of it silently is worse than answering the first half openly.
    """
    words = _words(question)
    for computation in REGISTRY:
        if not _carries(words, computation.any_of):
            continue
        if computation.and_any_of and not _carries(words, computation.and_any_of):
            continue
        return computation
    return None


def answer(session: Session, *, member_id: str, question: str, language: str = "de"):
    """Run the computation this question asks for, or `None` if none does.

    Returns `Determined`, `Undetermined`, or `None`. The caller decides what to do with each: `know.ask`
    emits a determined answer, asks for the missing input on an undetermined one, and falls through to
    retrieval on `None`.
    """
    computation = match(question)
    if computation is None:
        return None
    return computation.run(session, member_id=member_id, language=language)


# ============================================================ reading the member


def _answers(session: Session, *, member_id: str) -> dict:
    """Everything known about this member, from the stored submission and the member facts.

    Facts win over the submission where both hold a key: a fact is a later, deliberate statement, and a
    curator's reading of an old free-text answer is exactly the case that must not be overwritten by the
    free text it was read from.
    """
    from . import member_fact as facts
    from . import submissions as submission_service

    stored = submission_service.for_member(session, member_id=member_id)
    answers = dict(submission_service.answers(stored[0])) if stored else {}
    for key, row in facts.current(session, member_id=member_id).items():
        answers[key] = row.stated_value
    if answers.get("age") is None:
        # `age_at_registration` and not a birth year, because that is the only age this build stores.
        # It is stale by however long the member has been here, which for a ten-week-old prototype is
        # nothing and for a five-year-old plan would be five years. Named rather than silently used.
        from ..models import Member

        member = session.get(Member, member_id)
        stated = getattr(member, "age_at_registration", None)
        if stated is not None:
            answers["age"] = stated
    return answers


def _gross_income(session: Session, *, member_id: str) -> float:
    """Gross income, from the plan's income positions and the submission as a fallback."""
    from sqlalchemy import select

    from ..models import FLOW_UNIT, Position

    total = 0
    for position in session.execute(
        select(Position).where(Position.member_id == member_id, Position.active.is_(True),
                               Position.magnitude.is_not(None),
                               Position.magnitude_unit == FLOW_UNIT)
    ).scalars():
        if position.role == "income":
            total += position.magnitude
    if total:
        return float(total)
    stated = _answers(session, member_id=member_id).get("income_gross")
    try:
        return float(str(stated).replace("'", "")) if stated is not None else 0
    except (TypeError, ValueError):
        return 0


__all__ = ["Computation", "Determined", "KIND", "REGISTRY", "Undetermined", "answer", "match"]
