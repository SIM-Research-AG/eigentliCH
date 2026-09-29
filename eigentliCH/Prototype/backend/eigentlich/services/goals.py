"""S-04, Containers. What each franc is for.

**A reporting layer, not a set of accounts** (R-130, R-030). Goals name the positions that fund them, the
same position may fund several goals, and nothing here sums a position into one goal and out of another.
Principle 7: one portfolio, many meanings.

**R-031 is a statement of fact, not a warning to be dismissed.** So this module returns *observations* —
sentences that are true about the member's own plan — and never a severity, a status colour, or a
`dismissed` flag. There is nowhere to click "ignore", because the thing being reported is not an alert.

**What it deliberately does not decide.** Whether "in three years" is too soon for a holding that takes
years to sell is a threshold, and a threshold is an assumption nobody has published. So the comparison is
made only where it needs no number: a goal funded entirely by holdings the member has marked *illiquid*
is inconsistent with having any target date at all, and an *immediate* holding is never inconsistent with
one. Everything between those is stated as two facts side by side and left to the member.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Decision, FLOW_UNIT, Goal, Position, STOCK_UNITS
from .illustration import goal_illustration
from .liquidity import finding as liquidity_finding
from .plan import mutate_plan

#: R-131. The five parameters, named once so the API, the client and the tests cannot drift apart.
FIVE_PARAMETERS = ("safety", "liquidity_need", "volatility_tolerance", "horizon", "flexibility")

#: R-132. Courage money is a first-class template, not a footnote. Its parameters are deliberately left
#: unset: what makes it courage money is what it is FOR, and prescribing its volatility tolerance here
#: would be inventing the member's own answer. The same applies to every template below — none of them
#: prescribes a parameter, an amount, a date or a rate.
#:
#: **Where the eight kinds come from.** The owner found on 31 August 2026 that only two templates existed,
#: so "Frühpensionierung" — their own plan — was stored as `unspecified`. The list is not invented: seven
#: of these are the options of `goal_kinds` in `client/reference/questions-onb-0.1.3.json`, the owner's own
#: onboarding wording refined across five schema versions and three real interviews. **Frühpensionierung is
#: first at the owner's request**; it was theirs and it was the one missing, and for a Swiss product aimed
#: at 18–60 it is close to *the* goal.
#:
#: **One of the eight is deliberately not here: "Einfach den Standort bestimmen".** It is a reason for
#: using eigentliCH, not a thing money is for, and a `Goal` no position could ever fund is not a goal — it is
#: a completed onboarding wearing a goal's clothes. `unspecified` stays, because a member must be able to
#: name their own (R-020's spirit: what the member states is what is stored).
#:
#: **No template carries a figure, and that is C-02 rather than caution.** The purposes below describe a
#: KIND of goal. A reduction percentage for drawing the AHV early, a Vorbezug age, a minimum contribution
#: for a non-employed person — every one of those is published, dated material that belongs in an
#: `AssumptionSet` or in a citable knowledge note (`content/knowledge/ahv-referenzalter-und-bezug.md` and
#: `ahv-beitragspflicht.md` carry them with their `Stand`), and none of them belongs in a template's
#: one-sentence purpose where nothing states where it came from or when it was true.
#:
#: The one substantive statement any of these makes is on early retirement, and it is the one the AHV
#: material calls the most commonly mis-assumed point: **drawing the pension early does not end the duty to
#: contribute.** A83 admits a statement of statutory duty — indicative, sourced to a named institution, and
#: naming no selectable instrument — and this is one.
GOAL_TEMPLATES = {
    "early_retirement": {
        "key": "early_retirement",
        "de": {
            "name": "Frühpensionierung",
            "purpose": "Früher aufhören zu arbeiten, als es die Vorsorge vorsieht. Zwischen dem letzten "
            "Lohn und der ersten Rente liegt eine Zeit, die aus eigenem Vermögen getragen wird — und die "
            "AHV-Beitragspflicht endet mit dem Vorbezug der Rente nicht.",
        },
        "en": {
            "name": "Early retirement",
            "purpose": "Stopping work earlier than the pension system assumes. Between the last salary "
            "and the first pension there is a stretch carried out of your own assets — and drawing the "
            "AHV pension early does not end the duty to contribute to it.",
        },
    },
    "financial_independence": {
        "key": "financial_independence",
        "de": {
            "name": "Finanzielle Unabhängigkeit",
            "purpose": "Vermögen, das so weit trägt, dass Erwerbsarbeit eine Wahl ist und keine "
            "Notwendigkeit. Nicht dasselbe wie aufhören — das Ziel ist, es zu können.",
        },
        "en": {
            "name": "Financial independence",
            "purpose": "Assets that carry far enough that paid work is a choice rather than a necessity. "
            "Not the same as stopping — the goal is being able to.",
        },
    },
    "courage_money": {
        "key": "courage_money",
        "de": {
            "name": "Mutgeld",
            "purpose": "Geld, das da ist, damit Sie nein sagen können — zu einem Mandat, zu einer "
            "Stelle, zu einer Bedingung, die Sie nicht wollen.",
        },
        "en": {
            "name": "Courage money",
            "purpose": "Money that exists so you can say no — to a mandate, to a job, to a condition "
            "you do not want.",
        },
    },
    "home_ownership": {
        "key": "home_ownership",
        "de": {
            "name": "Wohneigentum",
            "purpose": "Eine eigene Wohnung oder ein eigenes Haus. Ein Kauf bindet Eigenmittel und "
            "Einkommen langfristig, und beides steht danach für anderes nicht mehr zur Verfügung.",
        },
        "en": {
            "name": "Home ownership",
            "purpose": "A flat or a house of your own. A purchase ties up both capital and income for a "
            "long time, and neither is available for anything else afterwards.",
        },
    },
    "holiday_property": {
        "key": "holiday_property",
        "de": {
            "name": "Ferienobjekt",
            "purpose": "Ein Objekt für die eigene Nutzung, das nicht Ihr Wohnsitz ist. Es kostet auch in "
            "den Jahren, in denen Sie es nicht brauchen.",
        },
        "en": {
            "name": "Holiday property",
            "purpose": "A property for your own use that is not where you live. It costs something in "
            "the years you do not use it, too.",
        },
    },
    "education": {
        "key": "education",
        "de": {
            "name": "Weiterbildung oder Umschulung",
            "purpose": "Eine Ausbildung, eine Weiterbildung oder ein Wechsel des Berufs. Das Ziel ist "
            "menschliches Kapital; es kostet Zeit und Geld, und die Zeit ist meist die knappere von beiden.",
        },
        "en": {
            "name": "Further education or retraining",
            "purpose": "A qualification, a course of further education, or a change of profession. The "
            "goal is human capital; it costs time and money, and time is usually the scarcer of the two.",
        },
    },
    "own_business": {
        "key": "own_business",
        "de": {
            "name": "Firma aufbauen oder kaufen",
            "purpose": "Eine eigene Firma aufbauen, übernehmen oder kaufen. Eine Beteiligung am eigenen "
            "Betrieb ist selten verlässlich verfügbar, und sie trägt Ihr Einkommen und Ihr Vermögen "
            "gleichzeitig.",
        },
        "en": {
            "name": "Building or buying a business",
            "purpose": "Building, taking over or buying a business of your own. A stake in your own "
            "business is rarely reliably available, and it carries your income and your wealth at once.",
        },
    },
    "estate": {
        "key": "estate",
        "de": {
            "name": "Nachlass und Erben",
            "purpose": "Was nach Ihnen weitergehen soll, und an wen. Ein Nachlass ist auch dann ein Ziel, "
            "wenn er nichts kostet — er verlangt Entscheide und nicht Beiträge.",
        },
        "en": {
            "name": "Estate and inheritance",
            "purpose": "What should pass on after you, and to whom. An estate is a goal even when it "
            "costs nothing — what it asks for is decisions rather than contributions.",
        },
    },
    # Last, and named. It used to carry `name: ""`, which made every surface fall back to its own word for
    # "no template" and made the option in a select read as a blank line. A member naming their own goal has
    # chosen something, and the option says what.
    "unspecified": {
        "key": "unspecified",
        "de": {"name": "Ein eigenes Ziel", "purpose": "Ein Ziel, das Sie selbst benennen."},
        "en": {"name": "A goal of your own", "purpose": "A goal you name yourself."},
    },
}

#: The template a member's own wording lands on when they name a goal no template covers. Named here so
#: the onboarding, the containers form and the tests all mean the same key by it.
UNSPECIFIED_TEMPLATE = "unspecified"


def observations(goal: Goal, *, today: date | None = None) -> list[dict]:
    """Statements of fact about one goal. R-031.

    Each carries `kind` for the client to render, and never a severity. A member reading these should
    recognise their own situation described, not be told they have a problem.
    """
    found: list[dict] = []
    funding = [p for p in goal.funded_by if p.active]

    if goal.target_date and not funding:
        found.append({
            "kind": "dated_but_unfunded",
            "target_date": goal.target_date.isoformat(),
            # R-030: a goal may be unfunded and that is a legitimate state, not an error.
            "note": "no_position_names_this_goal",
        })

    stated = [p for p in funding if p.liquidity]
    if goal.target_date and stated and all(p.liquidity == "illiquid" for p in stated):
        # The one comparison that needs no threshold: everything funding this has been marked as not
        # reliably convertible, and the goal has a date.
        found.append({
            "kind": "dated_but_funding_is_illiquid",
            "target_date": goal.target_date.isoformat(),
            "position_ids": [p.id for p in stated],
        })

    unstated = [p for p in funding if not p.liquidity]
    if goal.target_date and unstated:
        found.append({
            "kind": "liquidity_not_stated",
            "position_ids": [p.id for p in unstated],
            "note": "cannot_compare_without_it",
        })

    # R-030 made visible rather than merely permitted: if a funding position also funds another goal, say
    # so. The member should see that their wealth is not being divided up.
    shared = [p for p in funding if len(getattr(p, "_goal_count", []) or []) > 1]
    if shared:
        found.append({"kind": "funding_shared_with_other_goals", "position_ids": [p.id for p in shared]})

    return found


def goal_payload(session: Session, goal: Goal, *, today: date | None = None,
                 member: object | None = None) -> dict:
    """One goal, with its five parameters, its funding and its observations."""
    # How many goals each funding position serves. Computed here so `observations` can say that a holding
    # is shared without the caller having to know how to find out.
    for position in goal.funded_by:
        count = session.execute(
            select(Goal).join(Goal.funded_by).where(Position.id == position.id)
        ).scalars().all()
        position._goal_count = count  # noqa: SLF001 - transient, for this payload only

    return {
        "id": goal.id,
        "name": goal.name,
        "template": goal.template,
        # A129. Always present, null where nobody has asked. The client shows the control only where
        # `property` below is non-null, so a member is not asked about occupancy for a retirement goal.
        "occupancy": goal.occupancy,
        "target_amount": goal.target_amount,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        # R-131. All five, always present, null where unanswered — a missing key and an unanswered
        # parameter are different facts.
        "parameters": {name: getattr(goal, name) for name in FIVE_PARAMETERS},
        "funded_by": [
            {
                "id": p.id,
                "label": p.label,
                "role": p.role,
                "capital_type": p.capital_type,
                "liquidity": p.liquidity,
                # R-130: the count is here so the UI can say "also funds 2 other goals" rather than
                # implying this goal owns it.
                "also_funds_goal_count": max(0, len(getattr(p, "_goal_count", [])) - 1),
            }
            for p in goal.funded_by
        ],
        # The seventh field of a container: whose goal it is (A108). A list rather than a single owner,
        # because a goal owned by both partners is the normal couple case and is the one with a
        # consequence on a closing. An EMPTY list is a real state and the client must not read it as
        # "mine": goals recorded before households existed have no owner, and so does any goal created
        # before the member stated a composition.
        "owners": [
            {"household_member_id": owner.id, "label": owner.label, "kind": owner.kind}
            for owner in goal.owners
        ],
        "owner_recorded": bool(goal.owners),
        # A112. Present on every goal so a client reads one key rather than inferring a frozen goal from
        # a failed revision.
        "frozen_at": goal.frozen_at.isoformat() if goal.frozen_at else None,
        "may_be_revised": goal.frozen_at is None,
        "observations": observations(goal, today=today),
        # Item 4's blocking liquidity finding. `None` when the goal is not short on its date — a key that
        # is always present, so a client reads one thing rather than inferring from an absence. The goal
        # stays in the list either way: "not hidden, not greyed out, not marked failed".
        "short_on_date": liquidity_finding(goal, today=today or date.today()),
        # R-133 / C-02. Both keys are always present and both are now DERIVED — see
        # `services/illustration.py`. Until 31 August 2026 this was a hardcoded `None` with the reason
        # `"no_assumption_set_published"`, which had been false since A69 published one: the blocker was
        # lifted and nothing propagated, so every goal told the member a reason that was not true. The
        # reason may only say the table is empty when the table is empty.
        **goal_illustration(session, goal, member_id=goal.member_id, today=today),
        # A129. Present on every goal, `None` on every goal that is not a property purchase — one key to
        # read rather than an absence to interpret, the same argument `short_on_date` makes above.
        "property": property_finding(session, goal),
        # The mirror of `property` for a goal that means to live off capital. `None` for every
        # other goal, so a client reads one key rather than inferring from an absence.
        "retirement": retirement_finding(session, goal, member=member),
    }


def property_finding(session: Session, goal: Goal) -> dict | None:
    """The two tests that decide a property goal, or `None` for a goal that is not one.

    **Wired here rather than left for a caller to remember.** `services/learning.seed` and
    `services/marketplace.seed` were both complete, correct, tested and never invoked by any path in the
    running application, and the Market Place shipped empty because of it. A module that answers the
    largest figures in a member's plan and is reached by nothing would be the fourth instance.

    Composes the household income the affordability test needs, and passes `None` rather than a member's
    own income where the household has more than one earner and only one has stated a figure — a true
    statement about the wrong household is worse than no statement.

    Every refusal is caught and reported as a reason. The conventions record is provisional until an owner
    signs it, so today this returns `could_not_be_determined` for every real goal; a goal payload must not
    fail to render because a content record is unapproved.
    """
    from . import property as property_service

    if goal.occupancy is None and not _looks_like_a_property_goal(goal):
        return None

    hard, pillar2, pillar3a = _capital_by_eligibility(goal)
    try:
        assessment = property_service.assess(
            goal_id=goal.id,
            price=goal.target_amount,
            target_date=goal.target_date,
            occupancy=goal.occupancy,
            hard_available=hard,
            pillar2_available=pillar2,
            pillar3a_available=pillar3a,
            household_income=_household_income(session, goal),
        )
    except property_service.ConventionsNotApproved:
        return {
            "occupancy": goal.occupancy,
            "verdict": property_service.COULD_NOT_BE_DETERMINED,
            "undetermined_because": ["the_property_conventions_are_not_approved"],
            "conventions": "property-funding.json",
        }
    except property_service.UnknownOccupancy:
        return {
            "occupancy": goal.occupancy,
            "verdict": property_service.COULD_NOT_BE_DETERMINED,
            "undetermined_because": ["the_goal_names_an_occupancy_the_record_does_not_declare"],
            "conventions": "property-funding.json",
        }

    payload = assessment.as_payload()
    payload["levers"] = property_service.levers(
        assessment, household_income=_household_income(session, goal)
    )
    payload["occupancy_options"] = _occupancy_options()
    return payload


def _occupancy_options() -> list[dict]:
    """The three answers, with their labels, on the goal's own payload.

    Travels with the goal rather than costing the client a second request, for the reason the onboarding
    question set gives about its templates: a control whose options come from somewhere else is a control
    that renders empty the day somebody forgets the second call. Readable without the conventions being
    approved — asking the question puts no figure in front of anybody.
    """
    from .property import occupancies

    return [
        {"value": key, "label": rule["label"], "why": rule.get("why")}
        for key, rule in occupancies().items()
    ]


#: Words that make a goal a candidate for the property question. **Not a classifier and never a
#: substitute for `Goal.occupancy`** — matching one of these only means the member is ASKED, and the
#: assessment reports `could_not_be_determined` until they answer. Deliberately generous: a false positive
#: costs a question, a false negative costs a member the only finding that would have answered them.
_PROPERTY_WORDS = ("eigenheim", "wohneigentum", "eigentum", "immobilie", "haus", "wohnung", "ferienhaus")

#: A goal that is about living off capital rather than buying something with it. Matched on the name the
#: way property goals are, because `Goal.template` is nullable and every goal named before the templates
#: existed carries no kind at all.
_RETIREMENT_WORDS = ("rente", "pension", "ruhestand", "ab 65", "aufhören", "aufhoren",
                     "frühpension", "fruehpension", "nicht mehr arbeiten", "ausgaben ab")


def _looks_like_a_retirement_goal(goal: Goal) -> bool:
    name = (goal.name or "").lower()
    return any(word in name for word in _RETIREMENT_WORDS)


def _pillar2_balance(session: Session, member_id: str) -> float | None:
    """The member's occupational pension balance, or `None` where no position names one.

    Same label-reading weakness as `_capital_by_eligibility` and stated for the same reason: the plan has
    no field saying "this position is pillar 2". `None` here means no position was recognised, which is
    NOT the same as a balance of zero — a member who is insured and has never looked would produce the
    first, and one who has just started work the second. The projection reports them differently.
    """
    found = None
    for position in session.execute(
        select(Position).where(
            Position.member_id == member_id,
            Position.active.is_(True),
            Position.magnitude.is_not(None),
        )
    ).scalars():
        label = (position.label or "").lower()
        if "pensionskasse" in label or "pk-" in label or "2. säule" in label or "freizügigkeit" in label:
            found = (found or 0) + position.magnitude
    return found


def retirement_finding(session: Session, goal: Goal, *, member: object | None = None) -> dict | None:
    """What the first two pillars pay against a goal that means to live off capital.

    **Why this exists.** The Befund could say what a member holds and never what the state and their
    employer will pay them, so every retirement goal read as though it had to be funded entirely from
    savings. For most members most of the floor is the two pillars, and leaving them out overstated the
    gap by an amount nobody could see.

    Mirrors `property_finding`: the tests live in their own modules, the figures live in content records,
    every refusal comes back as a reason rather than an exception, and a goal payload never fails to
    render because a record is unapproved.

    **The AHV figure is an illustration and the payload says so in three places** — the caveat list, the
    `basis` field, and the reason the levers carry. It is keyed on current income where a revalued
    lifetime average belongs, because that average is not something a submission can hold.
    """
    from . import ahv as ahv_service
    from . import pension_projection as projection_service

    if goal.template != "retirement" and not _looks_like_a_retirement_goal(goal):
        return None

    payload: dict = {
        "goal_id": goal.id,
        "verdict": ahv_service.COULD_NOT_BE_DETERMINED,
        "needs_per_year": goal.target_amount,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "undetermined_because": [],
        "caveats": [],
        "ahv": None,
        "pillar2": None,
        "covered_per_year": None,
        "shortfall_per_year": None,
        "conventions": ["ahv-pension.json", "bvg-projection.json"],
    }

    age = getattr(member, "age_at_registration", None) if member is not None else None
    income = _household_income(session, goal)

    if income is None:
        payload["undetermined_because"].append("no_income_is_recorded_for_the_household")
    if age is None:
        payload["undetermined_because"].append("the_members_age_is_not_recorded")
    if goal.target_amount is None:
        payload["undetermined_because"].append("the_goal_names_no_yearly_amount")

    covered = 0
    reached = False

    if income is not None:
        try:
            first = ahv_service.illustration_for(current_income=income)
        except ahv_service.ScaleNotApproved:
            payload["undetermined_because"].append("the_ahv_table_is_not_approved")
        else:
            reached = True
            covered += first.yearly
            payload["caveats"].extend(first.caveats)
            payload["ahv"] = {
                "basis": "current_income_as_a_stand_in_for_the_lifetime_average",
                "monthly": first.monthly, "yearly": first.yearly,
                "at_minimum": first.at_minimum, "at_maximum": first.at_maximum,
                "levers": ahv_service.levers(first),
            }

    if age is not None and income is not None:
        try:
            second = projection_service.project(
                current_age=age, opening_balance=_pillar2_balance(session, goal.member_id) or 0,
                gross_salary=income,
            )
        except projection_service.ProjectionNotApproved:
            payload["undetermined_because"].append("the_pension_projection_record_is_not_approved")
        else:
            reached = True
            yearly = second.monthly_pension * 12
            covered += yearly
            payload["caveats"].extend(second.caveats)
            if _pillar2_balance(session, goal.member_id) is None:
                payload["caveats"].append("no_position_names_a_pension_fund_so_the_opening_balance_is_zero")
            payload["pillar2"] = {
                "opening_balance": second.opening_balance,
                "coordinated_salary": second.coordinated,
                "closing_balance": second.closing_balance,
                "monthly": second.monthly_pension, "yearly": yearly,
                "from_age": second.from_age, "to_age": second.to_age,
                "levers": projection_service.levers(second),
            }

    if reached and goal.target_amount:
        payload["covered_per_year"] = covered
        payload["shortfall_per_year"] = max(0, goal.target_amount - covered)
        payload["verdict"] = (
            ahv_service.MEETS if covered >= goal.target_amount else ahv_service.DOES_NOT_MEET
        )
    return payload




def _looks_like_a_property_goal(goal: Goal) -> bool:
    name = (goal.name or "").lower()
    return any(word in name for word in _PROPERTY_WORDS)


def _capital_by_eligibility(goal: Goal) -> tuple[float | None, float, float]:
    """The funding split three ways, because the property rules treat the three differently.

    Reads `Position.label` for the Vorsorge vessels, which is the weakest part of this and is stated
    rather than hidden: the plan has no field saying "this position is pillar 2". `role == protection`
    is not it either — a protection holding may be an insurance policy. Until a vessel field exists, a
    position the member named themselves cannot be classified, and anything unrecognised counts as hard
    equity, which is the conservative direction for the eligibility test and the wrong one for a member
    who typed «PK-Guthaben». Reported as a limitation in the payload rather than presented as complete.
    """
    if not goal.funded_by:
        # None, not zero. See `property.assess`: no link is "nobody has said", and zero would report a
        # shortfall against a deposit the member may well have.
        return None, 0, 0

    hard = pillar2 = pillar3a = 0
    for position in goal.funded_by:
        if position.magnitude is None or position.magnitude_unit not in STOCK_UNITS:
            continue
        label = (position.label or "").lower()
        if "3a" in label or "säule 3" in label or "saule 3" in label:
            pillar3a += position.magnitude
        elif "pensionskasse" in label or "pk-" in label or "2. säule" in label or "freizügigkeit" in label:
            pillar2 += position.magnitude
        else:
            hard += position.magnitude
    return hard, pillar2, pillar3a


def _household_income(session: Session, goal: Goal) -> float | None:
    """Gross household income per year, or `None`.

    The affordability test is a household test — `property-funding.json` says so at
    `max_share_of_gross_income` — and one of the six real cases is reachable on joint income and absurd on
    one income. Where the member has a household with more than one adult and only their own income is
    recorded, this returns `None`: the honest answer is that the household's income is not known, not that
    it equals the one figure on file.
    """
    from .household import adults, current as current_household

    total = 0
    for position in session.execute(
        select(Position).where(
            Position.member_id == goal.member_id,
            Position.active.is_(True),
            Position.role == "income",
            Position.magnitude.is_not(None),
            Position.magnitude_unit == FLOW_UNIT,
        )
    ).scalars():
        total += position.magnitude

    household = current_household(session, member_id=goal.member_id)
    if household is not None and len(adults(household)) > 1:
        # More than one adult, and this build has no way to reach another member's income — a household
        # member row carries a label, not an account. Returning this member's income alone would answer
        # the affordability test for a household that does not exist.
        return None

    return total or None


def list_goals(session: Session, *, member_id: str, today: date | None = None) -> dict:
    rows = session.execute(select(Goal).where(Goal.member_id == member_id)).scalars().all()
    # The member row, for the one figure a retirement finding needs and a goal cannot carry: an age. Read
    # once here rather than per goal, and passed rather than looked up inside the finding, so that
    # `retirement_finding` stays callable from a test with no member at all.
    from ..models import Member

    member = session.get(Member, member_id)
    return {
        "member_id": member_id,
        "goals": [goal_payload(session, goal, today=today, member=member) for goal in rows],
        "templates": list(GOAL_TEMPLATES.values()),
        "five_parameters": list(FIVE_PARAMETERS),
        # R-030 stated in the payload itself, so a client author reads it before designing a screen that
        # implies separate pots.
        "funding_may_overlap": True,
        # A goal can be changed after it is named, and the payload says so rather than leaving a client to
        # discover it. The owner's report was "if I have a Ziel, I can not change it afterwards" — see
        # `revise_goal` below for what changing one means here.
        "goals_may_be_revised": True,
        # A108. Stated in the payload so a client author reads it before building a form with six fields.
        "goal_fields": ["name", "target_amount", "target_date", *FIVE_PARAMETERS, "owners"],
        # NO totals, NO funded percentage, NO "on track". R-113 and R-006, and a "72% funded" is the
        # completion meter this product exists without.
    }


# ================================================================ changing a goal after it is named


#: Everything a member may change about a goal after naming it. Funding is handled separately, because it
#: is a collection rather than a column.
#:
#: `member_id` is not here and neither is `id`: a goal does not move between members and does not get a new
#: identity, and a field list that could express either is one typo from doing it.
#: A129. Revisable like the rest, and validated unlike the rest — the five parameters have no published
#: vocabulary yet and are stored as the member's words, while `occupancy` decides a legal eligibility and
#: has a closed set in `client/content/property-funding.json`. A value outside it would make
#: `services/property.assess` raise for that goal on every read.
REVISABLE_FIELDS = (
    "name", "template", "target_amount", "target_date", "occupancy", *FIVE_PARAMETERS
)


def check_occupancy(value: object) -> str | None:
    """The occupancy as it will be stored, or a refusal. `None` clears it back to unanswered.

    Clearing is a real answer: a member who said they would live in a property and now is not sure should
    be able to withdraw that rather than leave a legal eligibility standing on a guess. An unanswered
    occupancy makes the property finding report `could_not_be_determined`, which is the honest state.
    """
    from .property import occupancies

    if value is None or value == "":
        return None
    declared = occupancies()
    if value not in declared:
        raise UnknownOccupancy(
            f"{value!r} is not an occupancy the record declares. Known: {sorted(declared)}. It decides "
            f"whether pension capital may fund this goal, so it is not a free-text field."
        )
    return str(value)


class UnknownOccupancy(ValueError):
    """A goal was given an occupancy `client/content/property-funding.json` does not declare."""


class GoalNotFound(LookupError):
    """No goal by that id for this member.

    One exception for both "no such goal" and "not yours", for the same reason `login` has one refusal for
    a wrong address and a wrong password: the caller learns whether they own a goal, never whether one
    exists. The route turns this into a 404.
    """


class GoalIsFrozen(ValueError):
    """This goal may not be revised.

    Raised rather than silently ignoring the change, and raised at the service rather than checked by the
    caller: a freeze enforced only where somebody remembered to look is a freeze that stops holding the
    first time a new route is added. A112 froze it because the goal is owned by both members of a
    household that has closed, and dividing it is a decision with real consequences and emotional load
    that a curator handles.
    """


class NothingToChange(ValueError):
    """A revision that changes nothing.

    Refused rather than accepted as a no-op, because accepting it would write a Decision saying a change
    was made when none was. R-040 makes that Decision permanent and undeletable, so the cheapest place to
    stop is before it exists. S-07 has to stay worth reading.
    """


def _current_values(goal: Goal) -> dict:
    return {name: getattr(goal, name) for name in REVISABLE_FIELDS}


def _statable(value: object) -> object:
    """A value in a form the Decision's JSON can hold. Dates become ISO strings; everything else is already
    JSON-native."""
    return value.isoformat() if isinstance(value, date) else value


def revise_goal(
    session: Session,
    *,
    member_id: str,
    goal_id: str,
    changes: dict,
    question: str,
    choice: str,
    reasoning: str | None = None,
    funded_by_position_ids: list[str] | None = None,
) -> dict:
    """Change a goal a member has already named. **An in-place UPDATE, plus a correcting Decision.**

    The owner's report was that a goal could not be changed after it was created, and it could not: there
    was no route and no service function. What "changing" should mean was a real choice, because the estate
    guarantees two things that pull in different directions, and this docstring is where the choice is
    argued rather than implied.

    **The two candidates.**

    *Append-only, like the vault.* R-150 makes a new version of a vault item a new row (`supersedes_id`),
    and one could do the same here: never touch the old goal, write a second one pointing back at it.

    *In place, with the correction recorded on the Decision.* Update the row; write a new `Decision` whose
    `corrects_id` names the last Decision that touched this goal.

    **The second was chosen, for four reasons.**

    1. **The model already says a goal is mutable, and says it deliberately.** `db.py`'s own module
       docstring reads: "`positions` and `goals` carry no append-only trigger (they are legitimately
       mutable, which is the point of C-09)". Making a goal append-only would reverse a recorded decision
       — and C-09 exists *because* these two are the mutable things. An append-only Goal would leave C-09
       guarding nothing.
    2. **R-040 is a property of `Decision`, not of every table.** "A correction is a new record referencing
       the prior one" is honoured exactly where R-040 puts it: `corrects_id` on the new Decision, and the
       prior Decision untouched and undeletable at the storage layer. The audit trail is the Decision
       chain, and that chain is complete after this call.
    3. **A superseding-row scheme has a failure mode nobody would see.** Every read path would have to
       filter for the current version — `list_goals`, the export (R-154), the curator's view, the engine
       inputs, `observations`. One that forgot would silently show a member two of every goal they had ever
       edited, and `goal_funding` links point at a goal id, so the funding of a superseded row would have
       to be copied forward correctly every time. That is a migration, a filter in six places, and a class
       of bug that presents as "eigentliCH has doubled my plan".
    4. **The member asked to change a goal, not to keep two.** A vault item is a document: the earlier
       version is evidence and has to survive. A goal is an intention, and an intention that was revised
       has one current form. What has to survive is the *record that it was revised*, which is a Decision.

    **What that costs, and how it is paid.** An UPDATE loses the prior values, and "the record of what was
    decided" is thin if it cannot say what the goal used to be. So the prior and the new values are written
    into the Decision itself, in `options_considered`, in C-06's own label/consequence shape — the two
    options a member actually weighed (leave it as it stands, or change it) with what follows from each,
    plus a machine-readable `values` map so the earlier state can be read back rather than parsed out of a
    sentence. `services/settings.py` sets the same precedent for a request that is not a plan mutation.

    **C-09 is satisfied by construction, not by care.** The write goes through `mutate_plan`, so the
    Decision is in the same transaction and the goal is linked to it; and `before_flush` sees the goal in
    `session.dirty` (A72 put the second guard at statement level for the paths that never get there). A
    revision that forgot the Decision would raise `PlanMutationWithoutDecision` rather than persist.

    Refuses a revision that changes nothing — see `NothingToChange`.
    """
    goal = session.get(Goal, goal_id)
    if goal is None or goal.member_id != member_id:
        raise GoalNotFound(f"no goal {goal_id!r} for this member")

    # Before the field check, so a frozen goal reports the freeze rather than an unrelated complaint
    # about which fields are revisable.
    if goal.frozen_at is not None:
        raise GoalIsFrozen(
            f"goal {goal_id!r} has been frozen since {goal.frozen_at.isoformat()} and cannot be revised. "
            f"It is owned by more than one member of a household that has closed, so dividing it is a "
            f"curator's decision (A112) — nothing here splits it by a rule."
        )

    if "occupancy" in changes:
        changes = {**changes, "occupancy": check_occupancy(changes["occupancy"])}

    if unknown := sorted(set(changes) - set(REVISABLE_FIELDS)):
        raise ValueError(f"not a revisable field: {unknown}. Expected one of {list(REVISABLE_FIELDS)}")
    if "template" in changes and changes["template"] is not None:
        if changes["template"] not in GOAL_TEMPLATES:
            raise ValueError(f"unknown template; expected one of {sorted(GOAL_TEMPLATES)}")

    before = _current_values(goal)
    changed = sorted(name for name, value in changes.items() if before[name] != value)

    # Funding is a collection, so "changed" is a set comparison rather than a value comparison. `None`
    # means the caller did not state it, which is different from an empty list meaning "nothing funds this
    # any more" — R-030 makes an unfunded goal a legitimate state, so clearing the funding has to be
    # expressible.
    funding_before = [p.id for p in goal.funded_by]
    funding_after = funding_before
    # Bound before the branch. `funding_moved` can only be true when the caller stated the funding, so the
    # empty list is never read — but "can only be" is the shape of argument A72 found to be wrong three
    # times in one file, and a name that might not exist is cheaper to bind than to reason about.
    positions: list[Position] = []
    if funded_by_position_ids is not None:
        for position_id in funded_by_position_ids:
            position = session.get(Position, position_id)
            if position is None or position.member_id != member_id:
                raise GoalNotFound(f"no position {position_id!r} for this member")
            positions.append(position)
        funding_after = [p.id for p in positions]

    funding_moved = set(funding_after) != set(funding_before)
    if not changed and not funding_moved:
        raise NothingToChange(
            f"goal {goal_id!r} is already in the state this revision asks for. Nothing was written, and "
            f"no Decision was recorded — a Decision saying a change was made when none was is permanent "
            f"(R-040) and would make S-07 less true, not more complete."
        )

    stated = {name: _statable(changes[name]) for name in changed}
    kept = {name: _statable(before[name]) for name in changed}
    if funding_moved:
        kept["funded_by"] = funding_before
        stated["funded_by"] = funding_after

    with mutate_plan(
        session,
        member_id=member_id,
        question=question,
        choice=choice,
        reasoning=reasoning,
        # R-040 in the shape R-040 asks for: the new record references the prior one and the prior one is
        # left as it was written. `None` when this is the first change to a goal that arrived without a
        # Decision of its own, which the append-only table makes impossible to fake.
        corrects_id=_last_decision_id_for(session, goal),
        options_considered=[
            {
                "label": "Ziel unverändert lassen",
                "consequence": "Das Ziel behält die Angaben, die bisher festgehalten waren.",
                "values": kept,
            },
            {
                "label": "Ziel ändern",
                "consequence": "Das Ziel wird mit den neuen Angaben festgehalten. Die bisherigen Angaben "
                               "bleiben in diesem Entscheid nachlesbar.",
                "values": stated,
            },
        ],
    ) as decision:
        for name in changed:
            setattr(goal, name, changes[name])
        if funding_moved:
            goal.funded_by = positions
            decision.linked_positions.extend(positions)
        decision.linked_goals.append(goal)

    return {
        "goal": goal,
        "decision": decision,
        "changed": changed + (["funded_by"] if funding_moved else []),
    }


def _last_decision_id_for(session: Session, goal: Goal) -> str | None:
    """The most recent Decision this goal is linked to, or None.

    Read from the join rather than kept on the goal, because a column holding "the last decision" is a
    column that goes stale the first time anyone writes a Decision without updating it — and it would be a
    second source of truth for something the append-only table already knows.

    `created_at` carries microseconds, so two Decisions about one goal effectively cannot tie. The `id`
    tiebreak is there so the query is deterministic and is **not** chronological — an id is a random uuid.
    If a tie ever mattered, the fix is a sequence, not a better sort on this column.
    """
    row = session.execute(
        select(Decision)
        .join(Decision.linked_goals)
        .where(Goal.id == goal.id)
        .order_by(Decision.created_at.desc(), Decision.id.desc())
    ).scalars().first()
    return row.id if row is not None else None
