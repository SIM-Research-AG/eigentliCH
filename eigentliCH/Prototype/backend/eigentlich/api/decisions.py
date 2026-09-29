"""S-07 Decisions over HTTP. The screen the specification calls the thing that survives a change of adviser.

**Why this module did not exist until now.** `Decision` rows have been written correctly and immutably
since phase 1 — `services/plan.py::mutate_plan` writes one inside every plan mutation and `db.py` refuses
an UPDATE or a DELETE in `before_flush` and again by trigger. They have been readable as one section of the
Befund since phase 5. What was missing was R-160's actual content: a way to see a member's decisions and
filter them by the position, goal or vault item they touched. A90 records the audit that found it, and that
R-160 was the only identifier in the whole specification with no reference anywhere in the code.

**Nothing here composes a sentence of its own.** Every sentence in these payloads comes from
`services/befund.py::_decision_facts`, the same function that renders the Befund's decisions section. That
is deliberate and it is tested rather than asserted: `tests/test_decisions.py` compares the sentence this
route returns for a decision against the sentence the Befund returns for the same decision, so the two
cannot drift. Reusing a private name across a module boundary is the cost, and it is the cheaper cost — a
second vocabulary for the same object is how a report and a screen come to disagree about what a decision
is, and the vocabulary in `befund.py` is the one that has been reviewed.

It also means C-01 runs on every sentence that leaves here: `Fact.__post_init__` puts `check_answer` in the
constructor, so a sentence that advises cannot be constructed, let alone serialised.

**Where this route and the Befund DO disagree, and it is a finding, not a fix.** R-161 asks S-07 to show
"author and whether a curator was involved". The Befund's decisions section shows the author, and drops
`curator_session_id` entirely — it is in neither `values` nor `quoted`. So a decision the *member* recorded
while sitting with a curator is indistinguishable, in the Befund, from one they recorded alone. The
curator's own view of the same rows (`services/curator.py::curator_view_decisions`) carries the field. The
member-facing report is the half that cannot answer R-161's second clause. This route carries
`curator_session_id` and a derived `curator_involved`, which is why its payload is wider than the Befund
fact it reuses; `befund.py` is not edited here because a change to the report is a change to a reviewed
document. Two smaller disagreements are recorded in `DECISIONS.md` terms in the report that accompanies
this module: the Befund's `decision_correction` sentence *replaces* the author sentence, so a correction
recorded by a curator reads as attributed to nobody (R-212), and the Befund omits `options_considered`.

**C-04.** `question`, `choice` and `reasoning` are the member's or the curator's own prose, and they travel
in `quoted` — never interpolated into a sentence, exactly as the Befund separates them. Nothing in this
module logs anything at all; it imports no logger, and `services/know.py`'s docstring explains the
obligation that makes that the rule rather than an accident.

**R-231.** An erased member's `question` and `choice` are overwritten with a redaction marker and
`reasoning` is nulled, and the row's `member_id` is nulled too — so an erased decision is unreachable from
this route, which scopes every query to the token's member. `_quoted` still handles a null on all three,
because "unreachable today" is not a guarantee about the next migration.

**A81 / A91.** There is no `member_id` parameter and no `member_id` field on the request model. The member
is the token's, and a route that never receives one cannot be aimed at anybody else. A filter naming
another member's position returns an empty list rather than a refusal, because the query is scoped to the
member's own decisions first: there is no version of these routes that reports on whether an id exists.

**`get_session` is defined here and delegates to `main`'s at request time**, and this module never imports
`main` at module scope — the cycle it would create fails only in the order FastAPI happens to load things.
`api/befund.py` and `api/remainder.py` both carry the same note.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..content import DEFAULT_LANGUAGE
from ..models import DataClass, Decision, Goal, Member, Position, VaultItem
from ..services.befund import UnknownLanguage, _decision_facts, _language
from ..services.plan import record_correction
from .auth import current_member

router = APIRouter(prefix="/api", tags=["decisions"])

#: K2. `positions`, `goals`, `decisions` and `action_items` are personal and substantive; the vault is the
#: K3 tier and nothing documentary is copied into these payloads. See `_linked` on why the vault links are
#: ids and nothing else.
DATA_CLASS = int(DataClass.K2)

#: The one refusal for a decision id that is not this member's. A wrong id and somebody else's decision are
#: the same answer, on A81's reasoning: the response cannot be used to find out who owns what.
DECISION_NOT_FOUND = (
    "no decision with this id is recorded for this member. A decision belonging to somebody else and an "
    "id that was never written get this same answer, so the response says nothing about who owns what."
)

#: R-040 in the shape goals.py already established for a revision that revises nothing: a permanent record
#: stating that a correction happened when none did makes S-07 less true, not more complete.
CORRECTION_CHANGES_NOTHING = (
    "this states the same choice and the same reasoning as the record it would correct. A Decision is "
    "permanent under R-040, so a record saying something was corrected when nothing was is not written."
)

#: A blank choice would be a permanent record with nothing in it.
CHOICE_IS_BLANK = (
    "a correction records what now stands as the choice, so it cannot be blank. Under R-040 the record "
    "is permanent and there is no later edit that could fill it in."
)


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import."""
    from .main import get_session as application_session

    yield from application_session()


# ---------------------------------------------------------------- the shape of one record


def _quoted(decision: Decision) -> dict:
    """The member's own words, verbatim and separated from anything this application composed.

    Tolerates a null on all three fields. `question` and `choice` are NOT NULL in the schema and R-231's
    erasure overwrites them with a marker rather than nulling them, so this is insurance — said to be
    insurance, in A81's habit, rather than left looking load-bearing.
    """
    return {
        "question": decision.question,
        "choice": decision.choice,
        "reasoning": decision.reasoning,
    }


def _record(decision: Decision, *, sentence: str, key: str, corrected_by: Sequence[str]) -> dict:
    """One decision, in the shape a client renders.

    `sentence` and `key` are the Befund's, passed in rather than computed here so that there is exactly one
    place in the application that decides how a decision reads.
    """
    return {
        "id": decision.id,
        "recorded_at": decision.created_at.isoformat(),
        "recorded_on": decision.created_at.date().isoformat(),
        # -- R-161: who, and whether a curator was involved ----------------------------------------
        "author": decision.author,
        # R-212. "a curator" is not an attribution; this is which one.
        "author_ref": decision.author_ref,
        "curator_session_id": decision.curator_session_id,
        # The derived answer to R-161's second clause. True when a curator wrote it AND when the member
        # wrote it inside a curator session, which is the case the Befund cannot express at all.
        "curator_involved": decision.author == "curator" or decision.curator_session_id is not None,
        # -- R-040's chain, in both directions -----------------------------------------------------
        "corrects_id": decision.corrects_id,
        "corrected_by_ids": list(corrected_by),
        "is_correction": decision.corrects_id is not None,
        "was_corrected": bool(corrected_by),
        # -- R-160's filter targets, named on every record so a client can offer the filter ---------
        "linked_position_ids": decision.linked_position_ids,
        "linked_goal_ids": decision.linked_goal_ids,
        "linked_vault_item_ids": decision.linked_vault_item_ids,
        # -- what this application composed, and what the member wrote ------------------------------
        "key": key,
        "sentence": sentence,
        "quoted": _quoted(decision),
        # Which key of `quoted` a renderer puts in front of the sentence. The Befund's own answer.
        "subject": "question",
        "data_class": DATA_CLASS,
    }


def _records(
    decisions: Sequence[Decision], *, language: str, corrections: dict[str, list[str]]
) -> list[dict]:
    """The Befund's decisions section, re-projected as records. One `_decision_facts` call, zipped.

    The empty case is handled by the caller, because `_decision_facts` answers an empty list with its
    "nothing recorded yet" sentinel — which is a true sentence about a member with no decisions and a false
    one about a filter that matched none of them. See `list_decisions`.
    """
    if not decisions:
        return []
    facts = _decision_facts(list(decisions), language)
    if len(facts) != len(decisions):
        # Cannot happen while `_decision_facts` emits one fact per decision, and it is checked rather than
        # assumed: a silent mis-zip would attach one member's sentence to another decision's prose.
        raise RuntimeError(
            f"the Befund returned {len(facts)} facts for {len(decisions)} decisions; the reuse in "
            f"api/decisions.py has stopped lining up and the payload cannot be trusted"
        )
    return [
        _record(
            decision,
            sentence=fact.sentence,
            key=fact.key,
            corrected_by=corrections.get(decision.id, ()),
        )
        for decision, fact in zip(decisions, facts)
    ]


def _corrections_by_prior(session: Session, *, member_id: str) -> dict[str, list[str]]:
    """`{corrected_decision_id: [correcting_decision_id, ...]}` over ALL of this member's decisions.

    Deliberately not restricted to whatever the caller filtered to. A decision whose correction was filtered
    out of the list must still say that it was corrected — otherwise a filtered view of S-07 shows a
    superseded record with nothing marking it, which is the one reading R-040 exists to prevent.

    A list rather than a single id: nothing in the schema stops two corrections referencing one prior, and a
    shape that could not represent that would hide the second one.
    """
    rows = session.execute(
        select(Decision.id, Decision.corrects_id, Decision.created_at)
        .where(Decision.member_id == member_id, Decision.corrects_id.is_not(None))
        .order_by(Decision.created_at, Decision.id)
    ).all()
    by_prior: dict[str, list[str]] = {}
    for correction_id, prior_id, _ in rows:
        by_prior.setdefault(prior_id, []).append(correction_id)
    return by_prior


def _linked(decision: Decision) -> dict:
    """What this decision touched, named rather than left as bare ids.

    **The vault links are ids and nothing else, and that is C-04 rather than laziness.** A `VaultItem` is
    K3 as a whole (`models/vault.py`), so copying its title — or even its kind — into a decisions payload
    would raise this whole response from K2 to K3. The Befund makes the same call in the same place: its
    decisions fact is K2 and carries `linked_vault_item_ids`, while the title appears only in the expiries
    section, which declares itself K3. A client that wants the document asks the vault route, which is
    classified and store-guarded for it.

    Positions and goals are K2, the same class as the decision itself, so their member-authored names travel
    in `quoted` beside the decision's own.
    """
    return {
        "positions": [
            {
                "id": position.id,
                "role": position.role,
                "capital_type": position.capital_type,
                "quoted": {"label": position.label},
            }
            for position in decision.linked_positions
        ],
        "goals": [
            {
                "id": goal.id,
                "template": goal.template,
                "quoted": {"name": goal.name},
            }
            for goal in decision.linked_goals
        ],
        "vault_item_ids": decision.linked_vault_item_ids,
    }


def _load(session: Session, *, member_id: str, decision_id: str) -> Decision:
    """One of this member's decisions, or a 404 that says nothing about whose it might be."""
    decision = session.execute(
        select(Decision)
        .where(Decision.id == decision_id, Decision.member_id == member_id)
        .options(
            selectinload(Decision.linked_positions),
            selectinload(Decision.linked_goals),
            selectinload(Decision.linked_vault_items),
        )
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(404, DECISION_NOT_FOUND)
    return decision


def _resolve_language(language: str) -> str:
    try:
        return _language(language)
    except UnknownLanguage as unknown:
        # 422 and no fallback, for A12's reason: a payload half in the wrong language is worse than a
        # refused one. `api/befund.py` refuses the same way on the same service exception.
        raise HTTPException(422, str(unknown)) from unknown


# ---------------------------------------------------------------- R-160, the list


@router.get("/decisions")
def list_decisions(
    position_id: str | None = Query(
        None,
        description=(
            "R-160. Only decisions linked to this position. An id that is not this member's matches "
            "nothing and returns an empty list; it is not a refusal, because the query is scoped to the "
            "member's own decisions before the filter is applied."
        ),
    ),
    goal_id: str | None = Query(None, description="R-160. Only decisions linked to this goal."),
    vault_item_id: str | None = Query(
        None, description="R-160. Only decisions linked to this vault item."
    ),
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """The member's own decisions, newest first, filterable by what they touched (R-160, R-161).

    **Newest first, where the Befund is oldest first, and both are right.** The Befund reads as a document
    and a document runs forwards; a screen answers "what has happened lately" and `order` says which this
    is rather than leaving a client to infer it from two timestamps.

    **Several filters are AND, not OR.** A decision that touched this position *and* this goal is a
    narrower question than one that touched either, and it is the question a member asks when they arrived
    here from one screen and want the overlap. `filters` echoes what was applied so a client can render the
    state it is in without holding it separately.

    **The empty case is answered twice over, and the distinction is the point.** `empty_reason` is
    `no_decisions_recorded` when this member has recorded nothing at all, and
    `no_decision_matched_the_filter` when a filter excluded everything. Only the first carries a
    `sentence`: the Befund's own "nothing has been recorded yet" phrase is a true statement about an empty
    record and a false one about a filter that matched none of it, and no new German or English prose is
    authored here to cover the second — the wording for a filter that matched nothing belongs in the
    client's own i18n, beside the control that set the filter.
    """
    language = _resolve_language(language)

    statement = (
        select(Decision)
        .where(Decision.member_id == member.id)
        .options(
            selectinload(Decision.linked_positions),
            selectinload(Decision.linked_goals),
            selectinload(Decision.linked_vault_items),
        )
        # `created_at` is a Python-side default with microsecond resolution, so a tie is unlikely rather
        # than impossible. The id breaks it, and the order is total either way.
        .order_by(Decision.created_at.desc(), Decision.id.desc())
    )
    if position_id is not None:
        statement = statement.where(Decision.linked_positions.any(Position.id == position_id))
    if goal_id is not None:
        statement = statement.where(Decision.linked_goals.any(Goal.id == goal_id))
    if vault_item_id is not None:
        statement = statement.where(Decision.linked_vault_items.any(VaultItem.id == vault_item_id))

    decisions = list(session.execute(statement).scalars().unique())
    corrections = _corrections_by_prior(session, member_id=member.id)
    records = _records(decisions, language=language, corrections=corrections)

    filters = {"position_id": position_id, "goal_id": goal_id, "vault_item_id": vault_item_id}
    filtered = any(value is not None for value in filters.values())

    empty_reason = None
    empty_sentence = None
    if not records:
        if filtered:
            empty_reason = "no_decision_matched_the_filter"
        else:
            empty_reason = "no_decisions_recorded"
            # The Befund's sentinel, reused verbatim: the one case where its wording is true here.
            empty_sentence = _decision_facts([], language)[0].sentence

    return {
        "language": language,
        "order": "newest_first",
        "filters": filters,
        "filtered": filtered,
        "empty_reason": empty_reason,
        "empty_sentence": empty_sentence,
        "data_class": DATA_CLASS,
        # A list. No count, no total, no "you have made N decisions" — C-07 and R-003, and S-07 is
        # exactly the screen a completion figure would ruin.
        "decisions": records,
    }


# ---------------------------------------------------------------- R-161, one decision and its chain


def _chain(session: Session, *, member_id: str, decision: Decision, language: str) -> dict:
    """R-040's lineage, oldest first, with this decision inside it.

    Oldest first and not newest, because `services/curator.py::curator_view_decisions` already settled that
    question for the same rows: "a correction arriving without the record it corrects would read as a
    contradiction."

    Walks up through `corrects_id` to the root and then down through every correction that references
    anything in the lineage, so a correction of a correction is in the chain and so are two corrections of
    one record. Records rather than bare ids: the whole reason to look at a chain is to see what changed,
    and that is in `quoted`.
    """
    by_id = {
        row.id: row
        for row in session.execute(
            select(Decision)
            .where(Decision.member_id == member_id)
            .options(
                selectinload(Decision.linked_positions),
                selectinload(Decision.linked_goals),
                selectinload(Decision.linked_vault_items),
            )
        )
        .scalars()
        .unique()
    }

    root_id = decision.id
    seen_upwards = set()
    while True:
        current = by_id.get(root_id)
        if current is None or current.corrects_id is None or current.corrects_id in seen_upwards:
            break
        seen_upwards.add(root_id)
        root_id = current.corrects_id

    children: dict[str, list[str]] = {}
    for row in by_id.values():
        if row.corrects_id is not None:
            children.setdefault(row.corrects_id, []).append(row.id)

    # **Order by the lineage, not by the clock.** This sorted on `(created_at, id)`, and three decisions
    # written inside one microsecond — which is every test and any fast correction — tie on `created_at`
    # and fall through to `id`, which is random hex. So the chain came back in a different order on
    # different runs: a flaky test, and on a real database a member's correction history that reshuffles
    # between two page loads.
    #
    # A correction chain already carries its own order: each record corrects the one before it. `depth`
    # counts links from the root, so it is exact and cannot tie. `created_at` then orders two corrections
    # OF THE SAME record — genuinely concurrent, and the only place a clock is the right answer — and `id`
    # remains last so the result is total rather than merely usually total.
    lineage_ids: list[str] = []
    depth: dict[str, int] = {root_id: 0}
    frontier = [root_id]
    while frontier:
        current_id = frontier.pop(0)
        if current_id in lineage_ids or current_id not in by_id:
            continue
        lineage_ids.append(current_id)
        for child_id in children.get(current_id, ()):
            depth.setdefault(child_id, depth[current_id] + 1)
            frontier.append(child_id)

    lineage = sorted(
        (by_id[one] for one in lineage_ids),
        key=lambda row: (depth.get(row.id, 0), row.created_at, row.id),
    )
    corrections = _corrections_by_prior(session, member_id=member_id)
    records = _records(lineage, language=language, corrections=corrections)
    for record in records:
        record["is_the_one_asked_for"] = record["id"] == decision.id

    return {
        # A chain of one is not a chain, and saying so saves a client from counting.
        "is_part_of_a_chain": len(records) > 1,
        "root_id": root_id,
        "records": records,
    }


@router.get("/decisions/{decision_id}")
def read_decision(
    decision_id: str,
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """One decision, what it linked to, and the correction chain it sits in (R-161, R-040).

    404 for a decision that is not this member's, on A81's reasoning — see `DECISION_NOT_FOUND`.

    `options_considered` appears here and not in the list: it is C-06's label-and-consequence shape and it
    is the material a member reads when they open one record, not when they scan twenty. The Befund omits it
    from its decisions section altogether, which is the third of the three disagreements this module's own
    docstring records.
    """
    language = _resolve_language(language)
    decision = _load(session, member_id=member.id, decision_id=decision_id)

    corrections = _corrections_by_prior(session, member_id=member.id)
    record = _records([decision], language=language, corrections=corrections)[0]
    # C-06's shape, and authored by whoever recorded the decision — so it sits in `quoted` with the rest of
    # their prose rather than beside the computed fields.
    record["quoted"]["options_considered"] = list(decision.options_considered or [])

    return {
        "language": language,
        "data_class": DATA_CLASS,
        "decision": record,
        "linked": _linked(decision),
        "chain": _chain(session, member_id=member.id, decision=decision, language=language),
    }


# ---------------------------------------------------------------- R-162, record a correction


class CorrectionRequest(BaseModel):
    """What a correction states. No `question`, and no `member_id`.

    **No `question`, deliberately.** R-040 makes the prior record permanent, and the question that stood is
    part of what stood. `record_correction` copies it, so a correction answers the same question differently
    rather than quietly becoming a record of a different question having been asked.

    **No `member_id`** — A81 and A91. The member is the token's.

    Bare `str` with no length rule, matching the three request models in `main.py` that already carry a
    member's decision prose. A blank choice is refused in the route rather than by the schema, so the
    refusal can say why in R-040's terms.
    """

    choice: str
    reasoning: str | None = None


@router.post("/decisions/{decision_id}/correction", status_code=201)
def correct_decision(
    decision_id: str,
    body: CorrectionRequest,
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-162. Records a correction as a new Decision referencing the prior one. Never an edit.

    **This route cannot update a Decision, and not because it is careful.** It calls
    `services/plan.py::record_correction`, which writes a new row and sets `corrects_id` on it; `db.py`
    refuses an UPDATE to `decisions` in `before_flush` and the `trg_decisions_no_update` trigger refuses it
    again underneath the ORM. There is no second implementation here — the function this calls is the one
    `tests/test_constraints.py::test_decision_correction_creates_new_record` has always guarded, which until
    now had no caller outside the tests.

    **C-09 is not engaged, and that is worth stating.** A correction touches no `Position` and no `Goal`; it
    creates a `Decision` and the association rows that copy the prior record's links. The guard fires on a
    plan object written without a Decision, so there is nothing here for it to catch and nothing here that
    goes around it.

    **The correction is attributed to the member, not to whoever wrote the record it corrects.** That is a
    change to `record_correction`'s defaults, argued in its docstring: this route is member-guarded, so the
    person recording the correction is always the member, and copying a curator's `author_ref` onto a record
    the member wrote would be a false attribution — R-212's exact complaint, in the direction that names the
    wrong person rather than nobody. The prior record keeps its own author, untouched.

    **A correction that corrects nothing is refused (422).** `services/goals.py` settled the same question
    for a revision that revises nothing: under R-040 the record is permanent, and one asserting that a
    correction happened when none did makes S-07 less true rather than more complete.

    201 with the new record's id. The prior record's id comes back beside it so a client can show the chain
    without a second call.
    """
    language = _resolve_language(language)
    prior = _load(session, member_id=member.id, decision_id=decision_id)

    choice = body.choice.strip()
    if not choice:
        raise HTTPException(422, CHOICE_IS_BLANK)

    reasoning = body.reasoning.strip() if body.reasoning is not None else None
    reasoning = reasoning or None
    if choice == (prior.choice or "").strip() and reasoning == (prior.reasoning or None):
        raise HTTPException(422, CORRECTION_CHANGES_NOTHING)

    correction = record_correction(
        session,
        prior=prior,
        choice=choice,
        reasoning=reasoning,
        author="member",
    )
    session.commit()

    corrections = _corrections_by_prior(session, member_id=member.id)
    record = _records([correction], language=language, corrections=corrections)[0]
    return {
        "language": language,
        "data_class": DATA_CLASS,
        "decision": record,
        # R-040's mechanism, named in the response so a client can show "this corrects an earlier record"
        # rather than having to know that it does. `api/main.py`'s goal revision route says the same thing
        # with the same key.
        "corrects_decision_id": correction.corrects_id,
        # Said in the payload rather than left to a client author to trust: the prior row was read and not
        # written. Its own `choice` is echoed back from the object the ORM still holds.
        "prior": {
            "id": prior.id,
            "recorded_at": prior.created_at.isoformat(),
            "author": prior.author,
            "author_ref": prior.author_ref,
            "quoted": _quoted(prior),
            "unchanged": True,
        },
    }


__all__ = [
    "CHOICE_IS_BLANK",
    "CORRECTION_CHANGES_NOTHING",
    "CorrectionRequest",
    "DECISION_NOT_FOUND",
    "get_session",
    "router",
]
