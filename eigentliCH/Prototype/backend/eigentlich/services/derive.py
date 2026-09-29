"""R-152's other sources: action items derived from the plan the member has actually recorded.

**The defect this closes.** R-152 says expiry dates are *the primary* source of action items. Until now
they were the only one: `services/vault.py` calls `action_item_for_expiry` when a document is stored with
an expiry date, and nothing else in the system ever created an item. A member who had entered positions
and goals and uploaded no dated document had an empty `/api/actions` forever — they filled in a plan and
the product said nothing back. This module is the rest of R-152.

**Every derivation reads; none of them writes the plan.** An observation about a plan is not a change to
it, so nothing here needs a Decision under C-09 — and nothing here touches a `PlanMutable`, which is what
makes that a fact rather than a claim. `ActionItem` is not `PlanMutable`; the guard in `db.py` is not
being avoided, it is not being triggered.

**C-06 is the sharp constraint and it shapes every one of these.** An item exists only if it carries at
least two options, each with a stated consequence. So a derivation that cannot name two things that
actually happen is not a derivation this module is allowed to make, and two of the six candidates were
rejected on exactly that test rather than on taste. The options are phrased as *consequences* rather than
as verbs, for the reason `action_item_for_expiry` gives: a verb is an instruction, and C-01 forbids
recommending either branch.

**No figures anywhere, and no thresholds.** C-02: a figure needs a published `assumption_set_id`, and a
threshold is a figure wearing a selection rule. `store_item` already refused to gate the expiry items on a
horizon — "within how many months is an expiry worth surfacing" is an assumption nobody has published —
and the same reasoning binds here. It is why `unrevised_before` is a parameter with no default rather than
a constant: the caller supplies the date, exactly as `expiring_items` makes the caller supply
`on_or_before`. A derivation with no date supplied is not made, and its existing items are not touched.

**R-175: nothing is proactive.** These are derived when the list is read and listed when asked for. There
is no notification, no badge and no count; `know.action_items` returns a list for that reason and this
returns what it created rather than a total.

----------------------------------------------------------------------------------------------------
What was rejected, and why

**A concentration warning across correlation tags — forbidden, not deferred.** D-02 was answered on
31 August 2026 (A82): positions are never aggregated as risk, the five tags stay stored and uninterpreted,
and this closes as a decision not to build the inference at all. Several positions sharing a tag is not a
finding here and no code in this module reads `Position.tags`.

**An item per empty cell of the role grid — rejected on R-113 and S-02's own acceptance test.** R-110's
principle is that an empty cell states what would go there, and the grid is where it states it. A member
with one position has seven empty cells; seven action items saying so is a completion meter written as a
list, and S-02 accepts only a screen where "no element implies eight positions is the goal". The *role*
half of that candidate is therefore not built. The *capital type* half is, because it is at most one item
ever, and because it says something the grid cannot: R-114 pairs the two kinds of capital wherever both
exist, and "nothing recorded here is financial" is a fact about the member's plan rather than a gap in a
matrix.

**A goal whose target date is CLOSE — rejected on C-02.** "Close" is a horizon. `store_item` refused to
gate the expiry items on one and said why; a threshold invented here would be the same unpublished
assumption with a different owner. A date that has *passed* needs no number, so that is the half built.

**A consent never given or withdrawn — rejected because the second half of the requirement cannot be
met.** The candidate is "where something depends on it". Nothing in this build depends on a consent:
`Consent.purpose` is a free-text string supplied at registration, no code path reads it, and no registry
of purposes exists. An item would therefore have to state a consequence that is not true — "nothing that
needs this permission will run" — and C-06 asks for the options *and their consequences*, not for two
plausible sentences. Building it would mean inventing the purpose registry and the dependency first. That
is a real gap and it is reported as one rather than filled in.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import onboarding_questions
from . import submissions
from ..models import ActionItem, CAPITAL_TYPES, Decision, Goal, Member, OnboardingAnswer, Position, utcnow

# ---------------------------------------------------------------- the trigger kinds
#
# Prefixed `plan_` so a reader of the table can tell a derived item from `vault_expiry` at a glance, and so
# that R-152's primary source stays identifiable as the primary source.

GOAL_UNFUNDED = "plan_goal_unfunded"
GOAL_TARGET_DATE_PASSED = "plan_goal_target_date_passed"
POSITION_UNREVISED = "plan_position_unrevised"
CAPITAL_TYPE_EMPTY = "plan_capital_type_empty"
ONBOARDING_ANSWER_SKIPPED = "plan_onboarding_answer_skipped"

#: Item 6. The household composition has passed its published validity horizon, so the annual review's
#: structured confirmation is due. STATE-based like every other kind here — the cause is the household
#: itself, so confirming closes the item and the next expiry reopens it, which is the annual cadence
#: falling out of the derivation rather than being scheduled anywhere.
HOUSEHOLD_CONFIRMATION_DUE = "plan_household_confirmation_due"

#: Item 6's inferred half. **The one kind in this module whose cause is an EVENT, not a state**, and that
#: asymmetry is load-bearing enough to state here rather than in a comment further down.
#:
#: A visible event — a partner invited or removed, a goal's owner changed, a step change in a salary line,
#: a new dated obligation — sets a flag for confirmation rather than changing anything. Nothing in the
#: member's record afterwards distinguishes "a signal fired last week" from "no signal ever fired", so
#: `derive_action_items` cannot compute this cause and therefore never creates, closes or reopens it. It
#: is created by `services/household.flag_inferred_change` and closed by `confirm()` or `state()` — the
#: question having been answered is what resolves it.
#:
#: It is in `DERIVED_TRIGGER_KINDS` anyway, and deliberately: that tuple is what
#: `every_member_facing_string` walks, so its options go through C-01's outbound gate with the rest. A
#: kind excluded from the tuple would have unscanned copy, which is the A20 shape.
HOUSEHOLD_CHANGE_INFERRED = "plan_household_change_inferred"

#: A112. A goal owned by both members of a household that has closed. State-based: the cause is the goal,
#: and it holds for as long as the goal is frozen — so a curator completing the division unfreezes it and
#: the item closes on the next derivation, with nobody having to remember to close it.
GOAL_FROZEN_FOR_DIVISION = "plan_goal_frozen_for_division"

#: Every kind this module owns. `derive_action_items` will only ever create, close or reopen these, so an
#: expiry item — or anything a later module adds — cannot be closed by a derivation that does not know
#: what caused it.
DERIVED_TRIGGER_KINDS = (
    GOAL_UNFUNDED,
    GOAL_TARGET_DATE_PASSED,
    POSITION_UNREVISED,
    CAPITAL_TYPE_EMPTY,
    ONBOARDING_ANSWER_SKIPPED,
    HOUSEHOLD_CONFIRMATION_DUE,
    HOUSEHOLD_CHANGE_INFERRED,
    GOAL_FROZEN_FOR_DIVISION,
)

#: The kinds `derive_action_items` computes from the member's record. Every kind above except the inferred
#: household flag, whose cause is an event nothing can recompute — see `HOUSEHOLD_CHANGE_INFERRED`.
#:
#: Named as its own tuple rather than left implicit in the `causes` dict, so
#: `test_every_derived_kind_is_either_computed_or_explained` can assert that the difference between the
#: two tuples is exactly the kinds that carry a written reason for not being computed.
COMPUTED_TRIGGER_KINDS = tuple(
    kind for kind in DERIVED_TRIGGER_KINDS if kind != HOUSEHOLD_CHANGE_INFERRED
)

#: Set on an item whose cause has stopped holding. Not `acted`: marking it acted would assert the member
#: did something, and they may simply have changed their plan for another reason. `know.py` makes the same
#: distinction when a vault item is superseded and says so at length.
CAUSE_NO_LONGER_HOLDS = "expired"

#: Statuses the member has spoken through. A derivation never reopens one of these — a member who
#: dismissed an item and finds it back tomorrow is being nagged, and R-175 is the requirement that forbids
#: it. Only an item this module itself closed is ever reopened.
MEMBER_HAS_SPOKEN = frozenset({"acted", "dismissed"})


# ---------------------------------------------------------------- the prepared options (C-06, C-01)
#
# Two options each, each with a consequence, neither of them a recommendation. Written as German because
# German is the authored language (A12) and because `action_item_for_expiry` is, and a list where one item
# is translated and the next is not reads as a bug.
#
# **No digits, in any of them.** `action_item_for_expiry` carries no figure because a figure needs an
# `assumption_set_id` (C-02); the same holds here, and the absence of digits is asserted by a test rather
# than left to review. A `due_date` is different: it is a date the MEMBER recorded, copied across, and it
# is a structured field rather than a sentence.
#
# **Every string below passes `boundary.check_answer` with `requires_curator` False**, and a test walks
# every item this module can build and re-checks it. Not one draft was refused — and that is a finding
# about the gate, not a compliment to the drafting.
#
# ---------------------------------------------------------------------------------------------------
# C-01's outbound gate cannot police this register, and the passing test must not be read as saying it
# can.
#
# `check_answer` is a per-sentence CO-OCCURRENCE rule. **Rules 2, 4, 5 and 7** require the sentence to
# land on "something financial" — an instrument from the lexicon, an amount, or a verb of moving money.
# Rules 1 and 3 do not: rule 1 is a list of advisory constructs and rule 3 is a comparison drawn
# explicitly for this member, and both fire alone.
#
# A derived plan item carries no financial object by construction: C-02 forbids the figures, and the
# subjects are goals, positions, dates and grid columns, which are not instruments. So the four
# conjunction rules are structurally unable to fire on anything this module can write. Probed on the real
# gate — every sentence below is a recommendation and every one comes back with `requires_curator` False:
#
#     "Sie sollten ein neues Datum festhalten."              rule 2, no financial object
#     "Am besten setzen Sie ein neues Datum."                rule 2 again; `am besten` is a directive
#     "Eine Position ohne Betrag ist die sinnvollste Wahl."  superlative selecting a Wahl, rule 2
#     "Ein Ziel ohne Zuordnung ist für Sie geeignet."        rule 5, no third conjunct
#     "Warum nicht die Spalte jetzt ausfüllen?"              advice wearing a question mark, rule 2
#
# Rules 1 and 3 do their job here and are the half of the gate that is load-bearing in this register:
# "Wir empfehlen …", "An Ihrer Stelle …" and "besser für Sie als …" are all refused.
#
# That is not a defect in `boundary.py`: refusing "Sie sollten die Steuererklärung bis März einreichen"
# would make the product a wall, and the conjunction is what stops it. It is a statement about SCOPE. The
# gate is kept — it is the estate's shared floor and a later editor of these strings may well reach for a
# word the lexicon does know — but the guard with teeth in this module is
# `test_no_derived_string_carries_a_recommending_shape`, which reads the same shapes with the financial
# conjunct removed and is proved able to fire by planting each one. A test that cannot fail is A20's
# hazard, and a green `check_answer` here would have been exactly that.

_GOAL_UNFUNDED_OPTIONS = [
    {
        "label": "Eine Position diesem Ziel zuordnen",
        "consequence": "Das Ziel nennt danach, was es tragen soll. Dieselbe Position darf weitere Ziele "
                       "nennen; Ihr Vermögen wird dadurch nicht aufgeteilt.",
    },
    {
        "label": "Das Ziel ohne Zuordnung führen",
        "consequence": "Das Ziel bleibt erfasst, und keine Position nennt es. Ein Ziel ohne Zuordnung ist "
                       "ein vollständiges Ziel; es wird daraus nichts abgeleitet und nichts geschätzt.",
    },
]

_GOAL_TARGET_DATE_PASSED_OPTIONS = [
    {
        "label": "Ein neues Datum festhalten",
        "consequence": "Das Ziel trägt danach das neue Datum. Das bisherige bleibt im Verlauf erhalten, "
                       "weil ein Entscheid hier nichts überschreibt.",
    },
    {
        "label": "Das Datum stehen lassen",
        "consequence": "Das Ziel behält das vergangene Datum und erscheint weiterhin damit in der Liste. "
                       "Es wird kein Ersatzdatum eingesetzt.",
    },
]

_POSITION_UNREVISED_OPTIONS = [
    {
        "label": "Die Position durchgehen und festhalten, was gilt",
        "consequence": "Der Durchgang wird als Entscheid erfasst, auch wenn sich nichts ändert. Danach ist "
                       "im Verlauf sichtbar, wann Sie sie zuletzt angesehen haben.",
    },
    {
        "label": "Die Position unverändert weiterführen",
        "consequence": "Die Position bleibt aktiv und unverändert. Als letzter festgehaltener Stand bleibt "
                       "das eingetragene Startdatum.",
    },
]

#: One per capital type. The wording differs because the column differs, and a member should read which
#: column is meant rather than derive it from an identifier in the payload.
_CAPITAL_TYPE_EMPTY_OPTIONS = {
    "human": [
        {
            "label": "Eine Position beim menschlichen Kapital erfassen",
            "consequence": "Das Raster zeigt danach beide Kapitalarten nebeneinander, wo für beide etwas "
                           "erfasst ist.",
        },
        {
            "label": "Die Spalte leer lassen",
            "consequence": "Die Spalte nennt weiterhin, was dort stehen würde. Eine leere Spalte ist kein "
                           "Rückstand, und es wird nichts daraus geschlossen.",
        },
    ],
    "financial": [
        {
            "label": "Eine Position beim finanziellen Kapital erfassen",
            "consequence": "Das Raster zeigt danach beide Kapitalarten nebeneinander, wo für beide etwas "
                           "erfasst ist.",
        },
        {
            "label": "Die Spalte leer lassen",
            "consequence": "Die Spalte nennt weiterhin, was dort stehen würde. Eine leere Spalte ist kein "
                           "Rückstand, und es wird nichts daraus geschlossen.",
        },
    ],
}

_ONBOARDING_ANSWER_SKIPPED_OPTIONS = [
    {
        "label": "Die Frage jetzt beantworten",
        "consequence": "Die Antwort kommt zum Erstgespräch hinzu, und das Feld, das sie füllt, trägt sie "
                       "danach.",
    },
    {
        "label": "Die Frage offen lassen",
        "consequence": "Das Feld bleibt leer. Eine Position ohne diese Angabe ist eine vollständige "
                       "Position; es wird nichts geschätzt und nichts ergänzt.",
    },
]


_HOUSEHOLD_CONFIRMATION_DUE_OPTIONS = [
    {
        "label": "Bestätigen, dass der Haushalt unverändert ist",
        "consequence": "Dieselben Personen werden mit dem heutigen Datum neu festgehalten. Die Angabe "
                       "gilt danach wieder zwölf Monate, und der bisherige Stand bleibt in den "
                       "Entscheiden erhalten.",
    },
    {
        "label": "Den Haushalt neu erfassen",
        "consequence": "Die Zusammensetzung wird von vorne aufgenommen. Aus einer Ja-Antwort allein wird "
                       "nichts abgeleitet: wer dazugekommen ist und in welcher Rolle, steht in keiner "
                       "Ja-Nein-Antwort.",
    },
]

#: Deliberately the same two options as above. The member's choice is identical whether the app noticed
#: the horizon or noticed an event — confirm what stands, or restate it — and giving the inferred flag its
#: own wording would imply the app knows something about the change that it does not. What differs is the
#: `derived_from` cause, which names the signal.
_HOUSEHOLD_CHANGE_INFERRED_OPTIONS = [
    {
        "label": "Bestätigen, dass der Haushalt unverändert ist",
        "consequence": "Dieselben Personen werden mit dem heutigen Datum neu festgehalten. Am Hinweis, "
                       "der dazu geführt hat, ändert das nichts; er bleibt als Ereignis erfasst.",
    },
    {
        "label": "Den Haushalt neu erfassen",
        "consequence": "Die Zusammensetzung wird von vorne aufgenommen. Der Hinweis hat nichts verändert "
                       "und nichts vorausgesetzt — festgehalten wird, was Sie sagen.",
    },
]


#: A112. Two options, and neither of them divides anything. The first names the route to a person; the
#: second is a real choice — a frozen goal is a complete record of what the household wanted, and leaving
#: it frozen costs nothing but the ability to revise it.
_GOAL_FROZEN_FOR_DIVISION_OPTIONS = [
    {
        "label": "Die Aufteilung mit einer Kuratorin oder einem Kurator besprechen",
        "consequence": "Ein Mensch geht das Ziel mit Ihnen durch und hält fest, was gilt. Solange nichts "
                       "festgehalten ist, bleibt das Ziel unverändert erfasst.",
    },
    {
        "label": "Das Ziel eingefroren stehen lassen",
        "consequence": "Das Ziel bleibt mit dem Stand vom Schliessungsdatum erfasst und lässt sich nicht "
                       "ändern. Es verschwindet nicht und es wird nichts daraus abgeleitet.",
    },
]


def prepared_options_for(trigger_kind: str, cause: str) -> list[dict]:
    """The two options one derived item carries. Exposed so a test can walk every one of them.

    A test that only checked the items a fixture happens to produce would check whichever branches that
    fixture reached. This is the whole surface, keyed the way the store keys it.
    """
    if trigger_kind == GOAL_UNFUNDED:
        return [dict(option) for option in _GOAL_UNFUNDED_OPTIONS]
    if trigger_kind == GOAL_TARGET_DATE_PASSED:
        return [dict(option) for option in _GOAL_TARGET_DATE_PASSED_OPTIONS]
    if trigger_kind == POSITION_UNREVISED:
        return [dict(option) for option in _POSITION_UNREVISED_OPTIONS]
    if trigger_kind == CAPITAL_TYPE_EMPTY:
        return [dict(option) for option in _CAPITAL_TYPE_EMPTY_OPTIONS[cause]]
    if trigger_kind == ONBOARDING_ANSWER_SKIPPED:
        return [dict(option) for option in _ONBOARDING_ANSWER_SKIPPED_OPTIONS]
    if trigger_kind == HOUSEHOLD_CONFIRMATION_DUE:
        return [dict(option) for option in _HOUSEHOLD_CONFIRMATION_DUE_OPTIONS]
    if trigger_kind == HOUSEHOLD_CHANGE_INFERRED:
        return [dict(option) for option in _HOUSEHOLD_CHANGE_INFERRED_OPTIONS]
    if trigger_kind == GOAL_FROZEN_FOR_DIVISION:
        return [dict(option) for option in _GOAL_FROZEN_FOR_DIVISION_OPTIONS]
    raise ValueError(f"{trigger_kind!r} is not a derived trigger kind. Known: {DERIVED_TRIGGER_KINDS}")


def every_member_facing_string() -> list[tuple[str, str, str]]:
    """`(trigger_kind, field, text)` for every label and consequence this module can put in front of a
    member.

    Enumerated from the templates rather than from a run, so C-01's outbound gate is applied to the branch
    nobody's fixture reached as well as to the ones they did. A20's lesson in one function: a check that
    only sees what a test happened to construct is a check with an unknown scope.
    """
    found: list[tuple[str, str, str]] = []
    causes: dict[str, tuple[str, ...]] = {CAPITAL_TYPE_EMPTY: CAPITAL_TYPES}
    for kind in DERIVED_TRIGGER_KINDS:
        for cause in causes.get(kind, ("",)):
            for option in prepared_options_for(kind, cause):
                found.append((kind, "label", option["label"]))
                found.append((kind, "consequence", option["consequence"]))
    return found


# ---------------------------------------------------------------- the derivations themselves


def _unfunded_goals(session: Session, *, member_id: str) -> set[str]:
    """R-030 permits an unfunded goal, so this is an observation and never an error.

    Active funding only: a goal funded solely by a position the member has deactivated has nothing
    carrying it *now*, and R-122 keeps the deactivated position in history rather than pretending it is
    still working.
    """
    goals = session.execute(select(Goal).where(Goal.member_id == member_id)).scalars().all()
    return {goal.id for goal in goals if not any(p.active for p in goal.funded_by)}


def _goals_past_their_date(session: Session, *, member_id: str, today: date) -> set[str]:
    """A target date behind us with no decision recorded since it passed.

    The second half is what keeps this from being a nag: a member who looked at the goal after the date
    went by and recorded what they concluded has already answered, and S-07's Decision record is where
    that answer lives. Only *linked* decisions count — a decision about something else is not an answer
    about this goal.

    No horizon, no "approaching". See the module docstring: that would be a threshold, and a threshold is
    an unpublished assumption under C-02.
    """
    goals = session.execute(
        select(Goal).where(Goal.member_id == member_id, Goal.target_date.is_not(None))
    ).scalars().all()

    found: set[str] = set()
    for goal in goals:
        if goal.target_date >= today:
            continue
        recorded = session.execute(
            select(Decision.created_at).join(Decision.linked_goals).where(Goal.id == goal.id)
        ).scalars().all()
        if any(stamp.date() >= goal.target_date for stamp in recorded if stamp is not None):
            continue
        found.add(goal.id)
    return found


def _unrevised_positions(session: Session, *, member_id: str, before: date) -> set[str]:
    """A position still marked active whose start is behind `before` and which no later decision names.

    **`before` is the caller's date and there is no default.** "Long past" is a horizon, and C-02 does not
    let this module invent one — `expiring_items` has the same shape for the same reason, taking
    `on_or_before` from whoever asks. A caller who supplies nothing gets no derivation of this kind, and
    the items of this kind that already exist are left exactly as they are: not having asked the question
    is not an answer to it.

    "Never revised" is read off the Decision record rather than off `updated_at`, because there is no
    `updated_at` — R-040's append-only Decision *is* this estate's revision history, and a position the
    member has revisited has a decision naming it.
    """
    positions = session.execute(
        select(Position).where(
            Position.member_id == member_id,
            Position.active.is_(True),
            Position.started_on.is_not(None),
        )
    ).scalars().all()

    found: set[str] = set()
    for position in positions:
        if position.started_on >= before:
            continue
        recorded = session.execute(
            select(Decision.created_at).join(Decision.linked_positions).where(Position.id == position.id)
        ).scalars().all()
        if any(stamp.date() >= before for stamp in recorded if stamp is not None):
            continue
        found.add(position.id)
    return found


def _empty_capital_types(session: Session, *, member_id: str) -> set[str]:
    """A kind of capital with nothing active in it, where the member has recorded something somewhere.

    R-110's principle without R-113's failure mode: at most one item can ever come out of this, because
    firing needs at least one active position and a capital type with none — and there are two capital
    types. A member with an empty plan gets nothing, which is right: they are mid-onboarding, and telling
    someone their empty plan is empty is the interruption R-175 forbids.

    Roles are deliberately not derived this way. See the module docstring.
    """
    positions = session.execute(
        select(Position).where(Position.member_id == member_id, Position.active.is_(True))
    ).scalars().all()
    if not positions:
        return set()
    filled = {position.capital_type for position in positions}
    return {kind for kind in CAPITAL_TYPES if kind not in filled}


def _skipped_onboarding_answers(session: Session, *, member_id: str) -> set[str]:
    """An optional onboarding question left unanswered by a member who has finished onboarding.

    **Only after `onboarding_completed_at`.** Before it, an unanswered question is not skipped, it is
    next — and `resume_point` is what names it. An item raised mid-questionnaire would be the product
    interrupting a member who is in the middle of answering.

    Required questions are not derived: onboarding cannot complete without `employment_position`, so an
    item about it could only ever describe an impossible state.
    """
    member = session.get(Member, member_id)
    if member is None or member.onboarding_completed_at is None:
        return set()

    given = {
        row.question_key: row.value
        for row in session.execute(
            select(OnboardingAnswer).where(OnboardingAnswer.member_id == member_id)
        ).scalars()
    }
    # Questions this member was never shown. A member who completed onboarding in the application saw all
    # of them; a member loaded from an interview file was asked whatever that interview asked, and the
    # unanswered remainder is the format's shape rather than their choice. Both end with
    # `onboarding_completed_at` set, so without this the derivation reports the loader as the member —
    # which it did, 659 times across fifty clients, twelve identical questions each, for 86% of every
    # worklist in the run of 20 September 2026.
    never_asked: set[str] = set()
    for submission in submissions.for_member(session, member_id=member_id):
        never_asked |= submissions.not_presented(submission)

    skipped: set[str] = set()
    for record in onboarding_questions():
        if record.get("required"):
            continue
        if record["key"] in never_asked:
            continue
        value = given.get(record["key"])
        # A row holding None or an empty string is a question the member passed over, not one they
        # answered. `record_answer` writes the row either way, so absence is not the only shape of a skip.
        if value is None or (isinstance(value, str) and not value.strip()):
            skipped.add(record["key"])
    return skipped


# ---------------------------------------------------------------- the pass over all of them


def _frozen_goals(session: Session, *, member_id: str) -> set[str]:
    """A112. Goals frozen for division. The cause is the goal, so unfreezing closes the item."""
    return {
        goal_id
        for (goal_id,) in session.execute(
            select(Goal.id).where(Goal.member_id == member_id, Goal.frozen_at.is_not(None))
        )
    }


def _household_confirmation_due(session: Session, *, member_id: str, today: date) -> set[str]:
    """Item 6. The household whose stated composition has passed its published validity horizon.

    **The cause is the household's id, not a marker like "expired".** That is what makes the annual
    cadence fall out of the store rather than out of a scheduler: confirming updates
    `composition_as_of` on the same row, the cause stops holding, the item closes; twelve months later it
    holds again and `derive_action_items` reopens the same row. One row per household, forever, which is
    what the unique index on (member, kind, cause) already promises.

    **No horizon is read here.** `services/currency` reads the published one and raises if nobody has
    published it — and that refusal is allowed to propagate. A build with no published horizon cannot
    judge whether a confirmation is due, and inventing "twelve" locally to keep the derivation quiet is
    the defect C-02 exists to stop.
    """
    from .currency import of as currency_of
    from .household import current as current_household

    household = current_household(session, member_id=member_id)
    if household is None:
        # Nothing to confirm. A member who has never stated a composition is not overdue to re-state one,
        # and raising an item here would ask them to confirm something they never said.
        return set()

    judgement = currency_of(
        "household_composition", household.composition_as_of, today=today
    )
    return {household.id} if judgement.expired else set()


def _existing(session: Session, *, member_id: str, trigger_kind: str) -> dict[str, ActionItem]:
    """Every item of one kind for one member, keyed by cause, whatever its status.

    Keyed across all statuses on purpose. Reading only the open ones would make a dismissed item
    invisible to the derivation, which would create a second row for the same cause — and the unique index
    would then refuse the write. The index is the backstop; this is the path that should never reach it.
    """
    rows = session.execute(
        select(ActionItem).where(
            ActionItem.member_id == member_id,
            ActionItem.trigger_kind == trigger_kind,
            ActionItem.derived_from.is_not(None),
        )
    ).scalars().all()
    return {row.derived_from: row for row in rows}


def derive_action_items(
    session: Session,
    *,
    member_id: str,
    today: date | None = None,
    unrevised_before: date | None = None,
) -> dict:
    """R-152's other sources. Returns what changed; writes nothing to the plan.

    Idempotent by construction and by the store: one row per (member, kind, cause), forever. Called twice
    with the same plan, the second call creates nothing, closes nothing and reopens nothing.

        derive_action_items(session, member_id=m.id)              # every threshold-free derivation
        derive_action_items(session, member_id=m.id,
                            unrevised_before=date(2020, 1, 1))    # plus the quiet positions, the
                                                                  # caller's date, not this module's

    Three things happen to an item, and the third is the one that is easy to leave out:

      * a cause that holds with no row yet gets one;
      * a row whose cause has stopped holding is closed, so the member is not read a sentence about their
        plan that their plan no longer supports;
      * a row this module closed whose cause holds again is reopened. Without this the unique index would
        make a returning cause permanently unspeakable, since there can be no second row for it. An item
        the MEMBER closed — acted, dismissed — is never reopened.

    `session.flush()` is not called and nothing is committed: the caller decides the transaction, exactly
    as `store_item` leaves the expiry item to the caller's commit.
    """
    on = today or utcnow().date()

    causes: dict[str, set[str]] = {
        GOAL_UNFUNDED: _unfunded_goals(session, member_id=member_id),
        GOAL_TARGET_DATE_PASSED: _goals_past_their_date(session, member_id=member_id, today=on),
        CAPITAL_TYPE_EMPTY: _empty_capital_types(session, member_id=member_id),
        ONBOARDING_ANSWER_SKIPPED: _skipped_onboarding_answers(session, member_id=member_id),
        HOUSEHOLD_CONFIRMATION_DUE: _household_confirmation_due(
            session, member_id=member_id, today=on
        ),
        GOAL_FROZEN_FOR_DIVISION: _frozen_goals(session, member_id=member_id),
    }
    # `HOUSEHOLD_CHANGE_INFERRED` is absent from `causes` on purpose and not by omission. Its cause is an
    # event, so there is nothing to recompute; being absent means the loop below neither creates nor
    # closes one, which is exactly right — `services/household` owns both ends of that kind's life.
    # Evaluated only when the caller supplies the date. An unevaluated kind is absent from `causes`, and
    # the loop below therefore neither creates nor closes anything of that kind — see `_unrevised_positions`.
    if unrevised_before is not None:
        causes[POSITION_UNREVISED] = _unrevised_positions(
            session, member_id=member_id, before=unrevised_before
        )

    created: list[ActionItem] = []
    closed: list[ActionItem] = []
    reopened: list[ActionItem] = []

    for kind, holding in causes.items():
        existing = _existing(session, member_id=member_id, trigger_kind=kind)

        for cause in sorted(holding):
            row = existing.get(cause)
            if row is None:
                item = ActionItem(
                    member_id=member_id,
                    trigger_kind=kind,
                    # No due date. These are not deadlines: R-152's expiry items are the ones with a date,
                    # and `know.action_items` sorts a null due date last — so the primary source stays at
                    # the top of the list without anyone ordering it there by hand.
                    due_date=None,
                    derived_from=cause,
                    prepared_options=prepared_options_for(kind, cause),
                )
                session.add(item)
                created.append(item)
            elif row.status == CAUSE_NO_LONGER_HOLDS:
                row.status = "open"
                reopened.append(row)

        for cause, row in existing.items():
            if cause in holding or row.status != "open":
                continue
            if row.status in MEMBER_HAS_SPOKEN:  # unreachable while the line above stands; kept explicit
                continue
            row.status = CAUSE_NO_LONGER_HOLDS
            closed.append(row)

    return {"created": created, "closed": closed, "reopened": reopened}


def causes_by_item_id(session: Session, *, member_id: str) -> dict[str, str | None]:
    """`{action_item_id: derived_from}` — what in the member's record caused each item.

    R-174 asks for items expandable to their options and their consequences, and an item that says a goal
    has no funding position without naming the goal is not expandable to anything. `know.action_items`
    builds its own payload and does not carry this column, so the route joins it on rather than the read
    path being rewritten to know about derivations it does not own.
    """
    rows = session.execute(
        select(ActionItem.id, ActionItem.derived_from).where(ActionItem.member_id == member_id)
    ).all()
    return {row.id: row.derived_from for row in rows}
