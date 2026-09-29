"""S-01. Answering, resuming, and the one transaction at the end that writes the plan.

**Two different kinds of write, deliberately kept apart.**

  `record_answer`   one row, written as the member types. Not a plan mutation, not a Decision.
  `complete`        the Position and the Goal, in ONE transaction with ONE Decision (C-09, R-102).

The split is what keeps S-07 readable. A Decisions screen that logged every keystroke would be technically
compliant and practically useless, and "the record of what was decided and why" is the thing that survives
a change of adviser — it earns its scarcity.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import (
    intake_finding_sentence,
    intake_findings,
    onboarding_questions,
    question as onboarding_question,
    question_set_version,
)
from ..models.household import ADULT, DEPENDANT
from ..models import (
    Goal,
    MAGNITUDE_UNITS,
    Member,
    OnboardingAnswer,
    Position,
    STATED_BY,
    STOCK_UNITS,
    utcnow,
)
from .goals import GOAL_TEMPLATES
from .household import Person, state as state_household
from .member_fact import (
    FILLS_ENTITY as FACT_ENTITY,
    RefusedValue,
    declarations as fact_declarations,
    state as state_fact,
)
from .plan import mutate_plan


class UnknownQuestion(KeyError):
    """An answer to a question that is not in the set. Refused rather than stored loose."""


#: Item 3: "Curator-initiated as well as self-directed. The same intake can be driven by a curator on the
#: member's behalf, in a meeting or in the app, and produces the same versioned plan. One code path, two
#: initiators — record which one."
#:
#: Read from `models.household.STATED_BY` rather than re-spelled, so the intake and the composition cannot
#: come to disagree about who is allowed to have driven it.
INITIATORS = STATED_BY


class InvalidComposition(ValueError):
    """The stored household answer is not a composition. Nothing is written."""


class OnboardingIncomplete(Exception):
    """Completion attempted without the one answer R-102 requires."""


class OnboardingAlreadyComplete(Exception):
    """Completion attempted twice.

    Refused rather than made idempotent-by-overwrite, because the first run already wrote a Decision and
    R-040 makes Decisions append-only — there is nothing to undo. A second run would leave the member with
    two identical positions and two decisions saying the same thing, and no way to remove either.
    """


def record_answer(session: Session, *, member_id: str, question_key: str, value) -> OnboardingAnswer:
    """R-101. One question, one row, written now.

    Idempotent per question: answering again updates the row. A member correcting a typo has not made a
    second answer, and two rows would make "where did they get to" ambiguous.
    """
    keys = {q["key"] for q in onboarding_questions()}
    if question_key not in keys:
        raise UnknownQuestion(
            f"{question_key!r} is not in question set {question_set_version()!r}. "
            f"Known: {sorted(keys)}"
        )

    existing = session.execute(
        select(OnboardingAnswer).where(
            OnboardingAnswer.member_id == member_id,
            OnboardingAnswer.question_key == question_key,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.value = value
        existing.question_set_version = question_set_version()
        return existing

    answer = OnboardingAnswer(
        member_id=member_id,
        question_key=question_key,
        value=value,
        question_set_version=question_set_version(),
    )
    session.add(answer)
    return answer


#: The onboarding question whose answer becomes `Position.magnitude`. Named once so the function below and
#: the content file cannot be about different questions.
MAGNITUDE_QUESTION = "employment_magnitude"


def declared_magnitude_unit(key: str = MAGNITUDE_QUESTION) -> str:
    """The unit the question set declares for the answer it collects, checked against the vocabulary.

    **This was a hardcoded `"chf_per_year"` with a comment saying "the unit comes from the question's own
    declaration".** It did not: it was a literal beside a content file that also carries the unit, and the
    two agreed only because nobody had changed either. That made this the **third** site the unit list was
    maintained at — after `api/main.py` and `services/plan.py` — and the only one of the three that wrote a
    unit into the plan **without validating it at all**, because `complete` builds the `Position` directly
    rather than through the create route.

    So it is read, and it is checked. A content file that declared a unit this build does not accept would
    now fail loudly at the one write it affects, rather than storing a magnitude whose unit nothing
    downstream can interpret.

    **A stock unit is refused here on purpose, and that is not a limitation to tidy up later.** The question
    is "Ihr Bruttoeinkommen pro Jahr?" — an income, a flow. If this ever returned a stock unit, onboarding
    would file a salary as a balance, which is the A105 defect at the point of entry: everything downstream
    that may apply a rate to a balance would then apply one to a wage.
    """
    record = onboarding_question(key)
    declared = (record.get("fills") or {}).get("magnitude_unit")
    if declared not in MAGNITUDE_UNITS:
        raise OnboardingIncomplete(
            f"onboarding question {key!r} declares magnitude_unit {declared!r}, which is not one of "
            f"{list(MAGNITUDE_UNITS)}. R-120: the unit is never inferred, so there is nothing to fall back "
            f"to and this write does not proceed."
        )
    if declared in STOCK_UNITS:
        raise OnboardingIncomplete(
            f"onboarding question {key!r} declares the stock unit {declared!r}. It asks for an income — a "
            f"flow — and storing a flow as a balance would put a wage in front of every market rate that "
            f"may be applied to a balance. Change the question, not this unit."
        )
    return declared


def _stated_goal(answer: object) -> tuple[str | None, str | None]:
    """The name and the template out of whatever the goal question was answered with.

    **Two shapes, because there are two histories.** The question is a `goal_template` question now: the
    client sends `{"template": <key>, "name": <text>}`, so a member who chooses "Frühpensionierung" gets a
    Goal that carries the template as well as the name — which is what the owner asked for, and what
    `unspecified` was standing in for before this existed.

    A plain string is still accepted and still lands as a name with **no** template. That is not politeness
    to old clients: it is what every answer stored before 31 August 2026 looks like, and mapping one of
    those onto a template would be choosing a template on the member's behalf from a sentence they typed
    for a different question. R-151's rule about extraction never overwriting a member-entered value is the
    same rule one level up.

    An empty name is no goal at all, whichever shape it arrives in — a member who opened the select and
    chose nothing has skipped the question, and R-102 writes the goal only "if stated".
    """
    if isinstance(answer, dict):
        name = answer.get("name")
        template = answer.get("template")
        name = name.strip() if isinstance(name, str) else name
        # An unknown key is dropped rather than stored: `Goal.template` is read against `GOAL_TEMPLATES`
        # by every surface that renders it, and a key nothing can resolve renders as no template while
        # looking like one in the database.
        if template not in GOAL_TEMPLATES:
            template = None
        return (name or None), (template if name else None)

    name = answer.strip() if isinstance(answer, str) else answer
    return (name or None), None


#: The question whose answer becomes a `Household`. Named once: the content file, this module and the
#: resume point all mean the same key.
HOUSEHOLD_QUESTION = "household_composition"


def fact_questions() -> dict[str, str]:
    """The questions that fill a `MemberFact`, as `{question key: fact key}`.

    **There is no list of them in this module, and that is the whole point of A127.** The sim-tech task
    the owner closed on 4 September 2026 asked that keys be addable "without touching the intake flow", so
    this reads the instrument: any question whose `fills.entity` is `member_fact`. A sixth key is one
    entry in `client/content/onboarding-questions.json` and no change here.

    `record_answer` already accepts it — it validates against the question set, which the new key is now
    part of — and `resume_point` already asks for it, because it walks the same set in `order`. So the
    only thing that had to be written for the five keys to work end to end is the loop in `complete`
    below, and that loop does not know their names either.
    """
    return {
        declared["question_key"]: key for key, declared in fact_declarations().items()
    }


def _people_from(answer: object, *, member_id: str) -> list[Person] | None:
    """The stored answer, as the people `services/household.state` takes. `None` when it was skipped.

    **The first adult is the member, and the client never says so.** The stored shape is labels only —
    `{adults: [...], dependants: [...], as_of: ...}` — because a composition carrying an account id would
    be a composition a client could point at somebody else's account. The server attaches the id, to the
    first adult, because the person answering is in the household by construction.

    Raises:
        InvalidComposition: The answer is present and is not a composition. Refused rather than
            half-read: a household built from a misread answer is a stated fact nobody stated.
    """
    if answer in (None, "", {}, []):
        return None
    if not isinstance(answer, dict):
        raise InvalidComposition(
            f"the {HOUSEHOLD_QUESTION!r} answer is {type(answer).__name__}, not an object with `adults` "
            f"and `dependants`."
        )

    adults = [str(one).strip() for one in (answer.get("adults") or []) if str(one).strip()]
    dependants = [str(one).strip() for one in (answer.get("dependants") or []) if str(one).strip()]
    if not adults:
        raise InvalidComposition(
            "a household has at least one adult in it, and the member answering is one of them. An "
            "answer with no adults is an unanswered question wearing a shape."
        )

    people = [Person(label=adults[0], kind=ADULT, member_id=member_id)]
    people += [Person(label=label, kind=ADULT) for label in adults[1:]]
    people += [Person(label=label, kind=DEPENDANT) for label in dependants]
    return people


def composition_as_of(answer: object, *, today: date) -> date:
    """The date the stated composition describes.

    Defaults to `today` and takes it as an argument, which is the one place a default is right: a member
    answering the question in the app IS describing today. A curator recording a session held last week
    sends `as_of` and it is used instead — see `models/household.py` on why that date is not `created_at`.
    """
    if isinstance(answer, dict) and answer.get("as_of"):
        return date.fromisoformat(str(answer["as_of"]))
    return today


def answers(session: Session, *, member_id: str) -> dict:
    rows = session.execute(
        select(OnboardingAnswer).where(OnboardingAnswer.member_id == member_id)
    ).scalars()
    return {row.question_key: row.value for row in rows}


def resume_point(session: Session, *, member_id: str) -> dict:
    """Where the member got to, so they resume at question n rather than at the start.

    Named `resume_point` and not `progress`: it answers "which question next", never "how far along".
    A function called progress is an invitation to add a count to it, and R-113 forbids the count.

    **Reports the next unanswered question, not a count.** R-113 and C-07 forbid a completion meter, and
    "3 of 4 answered" in a payload is one component away from being one. What the client needs to resume is
    *which question*, and that is what this returns.
    """
    given = answers(session, member_id=member_id)
    ordered = sorted(onboarding_questions(), key=lambda q: q["order"])
    next_key = next((q["key"] for q in ordered if q["key"] not in given), None)
    return {
        "question_set_version": question_set_version(),
        "answered_keys": sorted(given),
        "next_question_key": next_key,
        "can_complete": bool(given.get("employment_position")),
    }


def complete(
    session: Session,
    *,
    member_id: str,
    initiated_by: str = "member",
    author_ref: str | None = None,
    curator_session_id: str | None = None,
    today: date | None = None,
) -> dict:
    """R-102. Ends by writing the household, one Position, and the member's first Goal if stated.

    One transaction, and the Decisions the plan needs — C-09. The Decision's question and choice are
    written from what the member actually answered, so the first entry in their Decisions screen is a true
    sentence about their own situation rather than a system message.

    **Two Decisions, not one, and the split is the same one this module already makes.** The composition is
    its own recorded fact with its own question — "What is the household this plan is for?" — and the plan
    is another. They are written in the same transaction, so a failure in either rolls back both, and a
    member never ends up with a household and no plan.

    **`initiated_by` is recorded and nothing branches on it** (item 3: "one code path, two initiators —
    record which one"). It becomes the Decision's author and the household's `stated_by`. The moment a
    curator-driven intake takes a different path from a member-driven one, the two stop producing the same
    plan and the requirement is broken quietly; a test asserts the two produce the same rows.

    **Household composition is written here rather than when it is answered.** `record_answer` writes one
    row and no plan mutation, by design, and a `Household` is `PlanMutable`. The answer is still stored the
    moment it is given, which is what R-101's resumability actually asks for.
    """
    member = session.get(Member, member_id)
    if member is None:
        raise OnboardingIncomplete(f"no member {member_id!r}")
    if member.onboarding_completed_at is not None:
        raise OnboardingAlreadyComplete(
            f"onboarding for {member_id!r} completed at "
            f"{member.onboarding_completed_at.isoformat()}. Positions are added from the role grid (S-03)."
        )

    if initiated_by not in INITIATORS:
        raise OnboardingIncomplete(
            f"{initiated_by!r} is not an initiator; expected one of {', '.join(INITIATORS)}."
        )

    given = answers(session, member_id=member_id)

    # Item 3: household composition is asked first, so it is written first — the goal's owner names a row
    # that has to exist by the time the goal is created. Skipped is a real answer and leaves `household`
    # as None; every finding that would have rested on it then reports that it could not be determined
    # (A110) rather than assuming a household of one.
    people = _people_from(given.get(HOUSEHOLD_QUESTION), member_id=member_id)
    household = None
    if people is not None:
        household = state_household(
            session,
            member_id=member_id,
            people=people,
            as_of=composition_as_of(given.get(HOUSEHOLD_QUESTION), today=today or date.today()),
            stated_by=initiated_by,
            author_ref=author_ref,
            curator_session_id=curator_session_id,
        )

    label = (given.get("employment_position") or "").strip() if isinstance(
        given.get("employment_position"), str
    ) else given.get("employment_position")
    if not label:
        raise OnboardingIncomplete(
            "R-102: onboarding writes one Position from `employment_position`, which has not been answered."
        )

    magnitude = given.get("employment_magnitude")
    hours = given.get("employment_time_basis")
    goal_name, goal_template = _stated_goal(given.get("first_goal"))

    created = {}
    with mutate_plan(
        session,
        member_id=member_id,
        question="Was aus dem Erstgespräch wird als Plan festgehalten?",
        choice=f"Erste Position: {label}" + (f". Erstes Ziel: {goal_name}" if goal_name else ""),
        reasoning="Aus den Antworten des Erstgesprächs (S-01) übernommen.",
        author=initiated_by,
        author_ref=author_ref,
        curator_session_id=curator_session_id,
    ) as decision:
        position = Position(
            member_id=member_id,
            role="income",
            capital_type="human",
            label=str(label),
            magnitude=float(magnitude) if magnitude not in (None, "") else None,
            # R-120: never inferred. The unit comes from the question's own declaration — READ from it,
            # see `declared_magnitude_unit` — and is absent exactly when the magnitude is.
            magnitude_unit=(
                declared_magnitude_unit() if magnitude not in (None, "") else None
            ),
            # A flow has no side of a balance sheet, and `ck_positions_stock_kind_iff_stock` refuses one
            # here. Stated as an explicit None rather than left off the constructor, because the next
            # person to read this needs to see that the question was asked.
            stock_kind=None,
            # R-121: hours are the binding constraint on human capital.
            time_basis=f"{hours} Std./Woche" if hours not in (None, "") else None,
            # D-02: stored, never interpreted. Nothing here infers a tag from an answer.
            tags={},
        )
        session.add(position)
        decision.linked_positions.append(position)
        created["position"] = position

        # "if stated" — a member who skipped the goal question gets a plan with one position and no goal,
        # which R-020 and principle 3 make a complete and useful state rather than a half-finished one.
        if goal_name:
            goal = Goal(member_id=member_id, name=str(goal_name), template=goal_template)
            # A108's seventh field: whose goal it is. The member's own row in the household they have just
            # stated — they are the first adult, and a goal named in their own intake is theirs unless
            # they say otherwise on Containers.
            #
            # **Not asked as a question, and that is a decision rather than an omission.** For a
            # single-adult household there is nobody else it could belong to, so asking would be a
            # question with one answer. For a couple the default is still the member and the field is
            # editable, because the alternative — a sixth question in the light intake, whose whole
            # purpose is to be short — costs every member a question to save some members an edit.
            # A household that never populates this cannot be divided cleanly (A112), so the default is
            # deliberately a real owner rather than none.
            if household is not None:
                mine = [one for one in household.members if one.member_id == member_id]
                goal.owners.extend(mine)
            session.add(goal)
            decision.linked_goals.append(goal)
            created["goal"] = goal

        # A127's five keys, and any key added after them. **This loop does not know their names.** It
        # walks whatever the instrument declares as filling a `member_fact`, in the question set's own
        # order, and writes each stated one against this Decision.
        #
        # A skipped one writes no row: `member_fact.check` refuses an empty answer, and a row holding
        # "nothing" is indistinguishable from a member who declined to say, which is a different fact.
        # Every one of the five is `required: false`, so skipping is the ordinary case and not an error.
        #
        # **A stored answer the question no longer admits stops the whole intake**, rather than being
        # dropped the way `civil_status` was dropped for the five days before this existed. That is the
        # same call `_people_from` makes about a misread composition: refused rather than half-read.
        stated_facts = {}
        for question_key, fact_key in fact_questions().items():
            answer = given.get(question_key)
            if answer in (None, "", [], {}):
                continue
            try:
                state_fact(
                    session,
                    member_id=member_id,
                    key=fact_key,
                    value=answer,
                    decision=decision,
                    on=today or date.today(),
                    by=initiated_by,
                )
            except RefusedValue as refused:
                raise OnboardingIncomplete(
                    f"the stored answer to {question_key!r} is not one this question admits: {refused}"
                ) from refused
            stated_facts[fact_key] = True
        if stated_facts:
            created["facts"] = sorted(stated_facts)

        # Marked inside the same transaction as the writes it guards. Set outside it, a crash between the
        # two would leave a member who can complete again and duplicate their own plan.
        member.onboarding_completed_at = utcnow()

    return {"decision": decision, **created}


# ---------------------------------------------------------------------------
# Progress as consequence (update script item 3)
# ---------------------------------------------------------------------------


def locked_findings(session: Session, *, member_id: str, language: str = "de") -> dict:
    """What is not yet possible, and which questions would make it possible.

    Item 3: "Progress shows consequence, not reward. Replace the percent-complete bar with a list of the
    findings still locked and, for each, the questions it needs ... No percentages, no badges, no
    streaks. This is how [the GTM lead]'s point about motivation and Principle 5 are both satisfied; a
    builder reading only one of them gets it wrong."

    The bracketed role replaces a name in the owner's original wording, on the ruling of 20 September
    2026 (A160), and is marked so that a reader comparing this against the update script can see the
    difference is a substitution rather than a misquotation.

    **The difference from a progress bar is not cosmetic.** A bar measures the member against completion —
    it is a score of them, and R-113 and C-07 forbid it. This names a thing that is not yet possible and
    the questions that would make it possible: the subject is the finding, not the member.

    **There is no count in what this returns, and that is deliberate.** Not a total, not a remaining, not
    a ratio. The lists are the answer, and a client that wants to say "these three questions" has them; a
    total computed here would be the meter, one component away from being rendered as one. `resume_point`
    makes the same argument in its own docstring and this module keeps it.

    Returns `{"locked": [...], "unlocked": [...]}` — both, because a member who has answered something
    has unlocked something, and reporting only what is missing would be the backlog rather than the
    consequence.
    """
    given = answers(session, member_id=member_id)
    stated = {key for key, value in given.items() if value not in (None, "", [], {})}

    locked: list[dict] = []
    unlocked: list[dict] = []
    for finding in intake_findings():
        missing = [key for key in finding["needs"] if key not in stated]
        entry = {
            "key": finding["key"],
            "sentence": intake_finding_sentence(finding["key"], language),
            # The questions still needed, in the order the finding names them. A client renders the
            # question's own wording from the set; the keys are what joins the two.
            "needs": missing,
        }
        (locked if missing else unlocked).append(entry)

    return {"locked": locked, "unlocked": unlocked}
