"""The member's own record as grounding The Know may answer from.

**Why this module exists, measured rather than argued.** On 20 September 2026 fifty loaded clients were
each asked the opening question they had come with. Eight got an answer. Thirty-six retrieved nothing at
all — not a weak passage, nothing — and the reason is visible the moment the questions are read together:

    "Wie gross ist meine Vorsorgelücke wirklich?"
    "Reicht unser Sparen für ein Eigenheim in sieben Jahren?"
    "Wie früh kann ich mit dieser Sparquote aufhören zu arbeiten?"
    "Tragen wir das Haus auch, wenn die Zinsen deutlich steigen?"

Every one of them is about the person asking it, and no sentence in any Merkblatt can answer any of them,
because the answer is a number derived from that member's own figures. The Know was asking an impersonal
corpus a personal question and then, correctly, refusing to answer.

Meanwhile the same database held 296 positions and 128 goals for those fifty people, and `know.retrieve`
was architecturally unable to look at a single one. Its whole universe was the member's **vault**, the
**learning units** and the **impersonal corpus** — and the fifty loaded clients had no vault items and no
learning units, so for all fifty the personal channel was empty by construction.

**This is not a relaxation of the boundary and it is worth being precise about why.** `know.member_material`
already retrieves the member's own vault with no relevance floor at all, on a stated argument: a member's
own document matching their own words "is not a claim about the world; it is their paperwork, retrieved
because they asked about it." Their positions, goals and household are the same category — things they
told this application about themselves — and a floor that refuses "wie gross ist meine Vorsorgelücke" for
a member whose pension capital is in the next table is the same failure that argument was written against.

What this module does NOT do is decide anything. It reads; it never computes an answer. Arithmetic is
`services/computations.py` and the engines behind it, and the separation is deliberate: a number that
appears here would be a number with no derivation attached to it.

**Route-gated by the caller, always.** Nothing here checks a branch. `know.ask` calls this only where
`routed.reads_member_data` is true, exactly as it does for the vault, so a question about how the AHV
household cap works never reads anybody's balance sheet to answer a fact about the world.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FLOW_UNIT, STOCK_UNITS, Goal, Member, Position

#: The `Passage.kind` this module produces. One kind rather than four, because what a citation has to say
#: is "this came from your own record" — the four sections below are the passage's title, not its
#: provenance, and a member reading a citation cares about the second.
KIND = "member_record"

#: How many francs count as worth naming. Not a rounding: a position recorded at zero is a real answer —
#: "I have no securities" — and it is stated as zero rather than dropped, because a member reading their
#: own dossier back should find what they said.
_ALWAYS_STATE = ("income", "pension", "property")


@dataclass(frozen=True)
class Section:
    """One part of the member's record, rendered for a model to read and for a member to recognise."""

    key: str
    title: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _chf(value) -> str:
    """Swiss thousands, the apostrophe this product uses everywhere else."""
    try:
        return f"CHF {float(value):,.0f}".replace(",", "'")
    except (TypeError, ValueError):
        return str(value)


def _stated(session: Session, *, member_id: str) -> dict:
    """The member's own answers, facts winning over the submission they were read from.

    Borrowed from `computations._answers` rather than reimplemented — one reading of "what did this person
    say about themselves" is the point, and two would drift.
    """
    from .computations import _answers

    return _answers(session, member_id=member_id)


def _about_them(session: Session, *, member_id: str) -> Section | None:
    """Age, canton, civil status, employment, income — the frame every other answer sits in."""
    stated = _stated(session, member_id=member_id)
    fields = (
        ("age", "Alter"),
        ("canton", "Kanton"),
        ("civil_status", "Zivilstand"),
        ("employment", "Erwerbssituation"),
        ("income_gross", "Bruttoeinkommen"),
        ("hours_per_week", "Arbeitspensum (Stunden pro Woche)"),
        ("stop_work_age", "Geplantes Alter beim Aufhören"),
        ("plan_until_age", "Planungshorizont (Alter)"),
        ("children_count", "Kinder"),
        ("matrimonial_regime", "Güterstand"),
    )
    lines = []
    for key, label in fields:
        value = stated.get(key)
        if value in (None, "", []):
            continue
        if key in ("income_gross",):
            value = _chf(value)
        lines.append(f"{label}: {value}")
    if not lines:
        return None
    return Section("about", "Was Sie über sich angegeben haben", tuple(lines))


#: The figures a member stated about their plan, with the DIMENSION each one carries.
#:
#: Dimension and not `unit`: these are not `magnitude_unit` values. The package uses that name
#: for `chf` and `chf_per_year`, and a local called `unit` holding the string "flow" reads as
#: though it were one. `test_stock_unit.py` found exactly that collision here.
#:
#: **Every one of these was in the submission and none of them reached the model.** Measured over the 60
#: members holding a submission: all 60 stated what they spend now, what they expect to spend after they
#: stop, and how much loss they could bear; 58 stated what they save each year. Those four are the inputs
#: to "reicht es?", which is the question under most of what members actually asked — and the answer path
#: had their positions and their goals and not one of these.
#:
#: `flow` and `stock` are carried per field rather than inferred, for the reason the position list is
#: split in two: a model reading a column of francs cannot tell a yearly outgoing from a balance, and the
#: one time it guessed it added a salary to four balances.
_PLAN_FIELDS = (
    ("spend_now", "Ausgaben heute", "flow"),
    ("spend_later", "Ausgaben nach dem Aufhören", "flow"),
    ("savings", "Sparbetrag", "flow"),
    ("partner_income", "Einkommen der Partnerin/des Partners", "flow"),
    ("property_total", "Wert der Liegenschaft(en)", "stock"),
    ("mortgage", "Hypothekarschuld", "stock"),
    ("amortisation", "Amortisation", "flow"),
    ("pillar2_buyin", "Einkaufspotenzial Pensionskasse", "stock"),
    # **A franc amount, not a yes/no**, which is why it is here and not below. It was in the plain list
    # with the label "Schwankt das Einkommen" until the stored values were read: they are 0, 6'000,
    # 25'000, 30'000 — the variable PART of the income, in francs a year. The label would have put
    # "Schwankt das Einkommen: 30000" in front of the model, which is not a sentence about anything.
    ("income_variable", "Davon variabel (Bonus, schwankender Anteil)", "flow"),
)

#: Stated plan figures that are not francs, so they are rendered as they were given.
_PLAN_PLAIN = (
    ("ahv_years_missing", "Fehlende AHV-Beitragsjahre"),
    ("max_loss_pct", "Maximal tragbarer Verlust (Anteil)"),
    ("crisis_behaviour", "Verhalten bei einem Einbruch"),
    ("goal_confidence", "Zuversicht, die Ziele zu erreichen"),
)


def _plan(session: Session, *, member_id: str) -> Section | None:
    """What the member said about their plan: what they spend, what they save, what they could bear.

    Separate from `_about_them` because these are statements about a future the member intends, and that
    section is about who they are today. A model answering "reicht unser Sparen" needs this one and can
    answer nothing useful without it.
    """
    stated = _stated(session, member_id=member_id)

    money: list[str] = []
    for key, label, dimension in _PLAN_FIELDS:
        value = stated.get(key)
        if value in (None, "", []):
            continue
        suffix = " pro Jahr" if dimension == "flow" else ""
        money.append(f"{label}: {_chf(value)}{suffix}")

    plain: list[str] = []
    for key, label in _PLAN_PLAIN:
        value = stated.get(key)
        if value in (None, "", []):
            continue
        plain.append(f"{label}: {value}")

    if not money and not plain:
        return None

    lines: list[str] = []
    if money:
        lines.append("Beträge (die mit «pro Jahr» sind Flüsse, die anderen Bestände):")
        lines.extend(f"  {line}" for line in money)
    if plain:
        lines.append("Weitere Angaben:")
        lines.extend(f"  {line}" for line in plain)
    return Section("plan", "Was Sie für Ihre Planung angegeben haben", tuple(lines))


def _positions(session: Session, *, member_id: str) -> Section | None:
    """Everything recorded as this member's money, by role, with its unit named.

    The unit is stated because a stock and a flow are not comparable and a model reading `120000` twice
    would have no way to know that one is a balance and the other a salary.
    """
    rows = list(session.execute(
        select(Position).where(Position.member_id == member_id, Position.active.is_(True))
    ).scalars())
    if not rows:
        return None

    # **Stocks and flows under separate headings, and the reason is a measured error.** The first composed
    # answer produced from this section added a salary of 280'000 to four balances and reported the total
    # as the member's wealth. Both numbers were real and the sentence was false. A model reading a flat
    # list of francs has no way to know which rows may be summed, and a parenthetical unit at the end of
    # the line is not enough — so the list is split, each half is titled with what it is, and neither
    # half invites the other's arithmetic.
    stocks: list[str] = []
    flows: list[str] = []
    other: list[str] = []
    unpriced: list[str] = []
    for position in sorted(rows, key=lambda p: (p.role or "", p.label or "")):
        label = position.label or position.capital_type or position.role or "Position"
        if position.magnitude is None:
            unpriced.append(f"{label}: erfasst, ohne Betrag")
            continue
        # **`in STOCK_UNITS`, which is the house idiom, and not a guess at how a unit is spelled.** This
        # read `magnitude_unit.startswith("flow")` until a test asked what `FLOW_UNIT` actually is: it is
        # `chf_per_year`, so that branch was never once true and the whole split was resting on
        # `role == "income"` alone — a flow with any other role was rendered as a balance, which is the
        # defect this function exists to prevent, still half open inside the fix for it.
        #
        # `models/plan.py` names this hazard in full and `test_stock_unit.py` greps for it, and neither
        # could see this one: the guard scans for the literal `chf` written where `STOCK_UNITS` belongs,
        # and `"flow"` is not `chf` — it is not a unit at all. Writing the *wrong* literal is a different
        # failure from writing the *right* literal wrongly, and it is the one that is silent.
        if position.magnitude_unit in STOCK_UNITS and position.role != "income":
            stocks.append(f"{label}: {_chf(position.magnitude)}")
        elif position.magnitude_unit == FLOW_UNIT or position.role == "income":
            flows.append(f"{label}: {_chf(position.magnitude)} pro Jahr")
        else:
            # A share is neither. `share_of_total` is dimensionless, so `_chf` would put a franc sign on
            # `0.35`. No position carries one today; the branch exists so that the day one does, it is
            # rendered as what it is rather than as a third of a franc.
            other.append(f"{label}: {position.magnitude} ({position.magnitude_unit})")

    lines: list[str] = []
    if stocks:
        lines.append("Vermögen (Bestände in Franken, zu einem Zeitpunkt):")
        lines.extend(f"  {line}" for line in stocks)
    if flows:
        lines.append("Einkommen und Ausgaben (Franken pro Jahr — NICHT zum Vermögen addieren):")
        lines.extend(f"  {line}" for line in flows)
    if other:
        lines.append("In einer anderen Einheit erfasst:")
        lines.extend(f"  {line}" for line in other)
    if unpriced:
        lines.append("Ohne Betrag erfasst:")
        lines.extend(f"  {line}" for line in unpriced)
    return Section("positions", "Ihre erfassten Positionen", tuple(lines))


def _goals(session: Session, *, member_id: str) -> Section | None:
    """The member's goals, each with whether anything is recorded as funding it.

    The funding half is stated because it is the question behind most of what members actually ask — "reicht
    es?" is a question about cover — and because a goal with no position behind it is a fact about the
    record rather than about the plan, which a reader has to be able to tell apart.
    """
    rows = list(session.execute(select(Goal).where(Goal.member_id == member_id)).scalars())
    if not rows:
        return None

    # **Sorted without ever comparing a `target_date` to a `created_at`.** `target_date` is a `date` and
    # `created_at` is a `datetime`, and Python refuses to order the two — so `g.target_date or g.created_at`
    # raises `TypeError` for any member holding one goal with a date and one without. Found by running
    # this over the real development database, where it failed on the fourth member; every unit test had
    # given its goals the same shape. Dated goals first, in date order, then the undated ones by name.
    def _when(goal):
        return (goal.target_date is None, goal.target_date or date.min, goal.name or "")

    lines = []
    for goal in sorted(rows, key=_when):
        parts = [goal.name or "Ziel"]
        if goal.target_amount is not None:
            parts.append(_chf(goal.target_amount))
        if goal.target_date is not None:
            parts.append(f"bis {goal.target_date.year}")
        if goal.template and goal.template != "unspecified":
            parts.append(f"Vorlage {goal.template}")
        lines.append(" · ".join(parts))
    return Section("goals", "Ihre Ziele", tuple(lines))


def _household(session: Session, *, member_id: str) -> Section | None:
    """Who the member plans with. Empty for most loaded members, and its absence is itself worth saying."""
    from . import household as household_service

    try:
        current = household_service.current(session, member_id=member_id)
    except Exception:  # pragma: no cover - a household service that cannot read is not this module's
        return None
    if current is None:
        return None
    lines = []
    for person in getattr(current, "members", None) or []:
        label = getattr(person, "label", None) or getattr(person, "role", None) or str(person)
        born = getattr(person, "birth_year", None)
        lines.append(f"{label}{f' (Jahrgang {born})' if born else ''}")
    if not lines:
        return None
    return Section("household", "Ihr Haushalt", tuple(lines))


def sections(session: Session, *, member_id: str) -> list[Section]:
    """Every part of this member's record that holds anything, in the order a reader wants them.

    Order is the frame first, then what they have, then what they want, then who they plan with — which is
    how the Befund reads and how a curator opens a file. A model given these in this order writes an answer
    that starts from the person rather than from their securities.
    """
    if session.get(Member, member_id) is None:
        return []
    found = [
        _about_them(session, member_id=member_id),
        _positions(session, member_id=member_id),
        _plan(session, member_id=member_id),
        _goals(session, member_id=member_id),
        _household(session, member_id=member_id),
    ]
    return [section for section in found if section is not None]


def passages(session: Session, *, member_id: str, question: str):
    """The member's record as `know.Passage` objects, ready to be assembled with everything else.

    **No relevance floor and no term matching.** Every section is returned whether or not it shares a word
    with the question, and that is the difference between this and `member_material`. A member asking "kann
    ich mit 60 aufhören" shares no vocabulary with a row labelled `Freizügigkeitsguthaben`, and that row is
    the answer. Filtering the member's own record by keyword is what made thirty-six of fifty questions
    retrieve nothing; the whole record is four short sections and it fits.

    `score` is fixed rather than computed, because there is nothing to rank: these are not candidates, they
    are the facts of the case. `Passage.score` is documented as comparable only within a `kind`, and within
    this one every member is equally about themselves.
    """
    from .know import Passage

    return [
        Passage(
            kind=KIND,
            source_id=f"{member_id}:{section.key}",
            title=section.title,
            text=section.text,
            score=1,
        )
        for section in sections(session, member_id=member_id)
    ]


__all__ = ["KIND", "Section", "passages", "sections"]
