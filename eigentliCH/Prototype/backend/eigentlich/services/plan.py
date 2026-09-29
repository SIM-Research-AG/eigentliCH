"""Writing the plan, which under C-09 means writing a Decision at the same time.

`mutate_plan` is the convenient path. The guard in `db.py` is the enforcement — this function exists so
that doing the right thing is easier than working around the guard, not so that the guard can be relaxed.

**The second half of this module is changing a position that already exists** (R-122, R-123). Until 31
August 2026 there was none: `Position.active` was honoured by `services/grid.py`, `services/befund.py`,
`services/illustration.py`, `services/derive.py`, `services/engine_inputs.py` and `services/goals.py`, and
rendered by the client — and **nothing anywhere set it to `False`.** §6 of the specification names
`PATCH /api/positions/:id` and it did not exist, which also left R-123 half-enforced: "creating *or
editing* a position writes a Decision" was held on creation and there was no editing for it to be held on.

See `revise_position` for the argument, which follows A86's for goals rather than restating it, and
`set_position_active` for why deactivating is its own act and not a boolean on a form.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Iterator, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CAPITAL_TYPES,
    CORRELATION_TAGS,
    Decision,
    Goal,
    LIQUIDITY,
    MAGNITUDE_UNITS,
    PlanMutable,
    Position,
    ROLES,
    STOCK_KINDS,
    STOCK_UNITS,
)


@contextmanager
def mutate_plan(
    session: Session,
    *,
    member_id: str,
    question: str,
    choice: str,
    author: str = "member",
    author_ref: str | None = None,
    reasoning: str | None = None,
    options_considered: Sequence[dict] | None = None,
    curator_session_id: str | None = None,
    corrects_id: str | None = None,
) -> Iterator[Decision]:
    """Open a plan mutation. Yield the Decision; attach the objects you touch to it.

        with mutate_plan(session, member_id=m.id,
                         question="Record employment as a human-capital income position?",
                         choice="Yes, at 92,000 CHF/year") as decision:
            position = Position(member_id=m.id, role="income", capital_type="human", ...)
            session.add(position)
            decision.linked_positions.append(position)

    The Decision is added to the session up front so that the `before_flush` guard sees it in `session.new`
    alongside whatever the caller creates. Nothing is flushed here: the caller's `commit` is what makes the
    mutation and its record one transaction, which is the whole of C-09.
    """
    decision = Decision(
        member_id=member_id,
        author=author,
        author_ref=author_ref,
        question=question,
        choice=choice,
        reasoning=reasoning,
        options_considered=list(options_considered or []),
        curator_session_id=curator_session_id,
        corrects_id=corrects_id,
    )
    session.add(decision)
    yield decision


def record_correction(
    session: Session,
    *,
    prior: Decision,
    choice: str,
    reasoning: str | None = None,
    author: str | None = None,
    author_ref: str | None = None,
) -> Decision:
    """R-040 / R-162: a correction is a new record referencing the prior one. The prior one is untouched.

    Deliberately not named `amend` or `update`. The name of this function is the same statement the UI
    makes to the member.

    **`author` defaults to the prior record's, and the caller that must not take that default is the
    member-facing one.** Copying the attribution forward is right when the same party corrects their own
    record, and wrong the moment a member corrects something a curator wrote: the new row would carry
    `author="curator"` and the curator's `author_ref`, attributing to a named person a record they did not
    write. R-212's complaint is that "a curator" is not an attribution; this would be worse than that,
    because it is a wrong one rather than an absent one. `api/decisions.py` passes `author="member"`.

    Passing `author` without `author_ref` clears the reference rather than carrying the prior one over,
    because a reference that survives a change of author names the wrong party — which is the defect this
    parameter exists to prevent.
    """
    correction = Decision(
        member_id=prior.member_id,
        author=prior.author if author is None else author,
        author_ref=prior.author_ref if author is None else author_ref,
        question=prior.question,
        choice=choice,
        reasoning=reasoning,
        options_considered=list(prior.options_considered),
        corrects_id=prior.id,
    )
    correction.linked_positions = list(prior.linked_positions)
    correction.linked_goals = list(prior.linked_goals)
    correction.linked_vault_items = list(prior.linked_vault_items)
    session.add(correction)
    return correction


def plan_objects_touched(session: Session) -> list[PlanMutable]:
    """Diagnostic: what the C-09 guard would currently consider a pending plan mutation."""
    touched: list[PlanMutable] = []
    for bucket in (session.new, session.dirty, session.deleted):
        for obj in bucket:
            if isinstance(obj, (Position, Goal)):
                touched.append(obj)
    return touched


# ================================================================ changing a position (R-122, R-123)


#: Everything a member may change about a position after recording it.
#:
#: **`active` is deliberately not here.** Marking a position inactive is R-122's own act, it goes through
#: `set_position_active`, and its Decision reads differently — see that function. A boolean in the middle
#: of an edit form is how a member deactivates half their plan without noticing.
#:
#: **`member_id` and `id` are not here either**, for `REVISABLE_FIELDS`'s reason in `services/goals.py`: a
#: position does not move between members and does not get a new identity, and a field list that could
#: express either is one typo away from doing it.
#:
#: **`liquidity` and `started_on` are here although `POST /api/positions` cannot set them.** That is not
#: an inconsistency to tidy up later, it is the same defect one field over: `goals.observations` reports
#: `liquidity_not_stated` as a fact about a member's own plan under R-031, and until this list existed
#: there was no route by which a member could answer it.
POSITION_REVISABLE_FIELDS = (
    "role",
    "capital_type",
    "label",
    "description",
    "magnitude",
    "magnitude_unit",
    #: 1 September 2026, with the stock unit. It travels with `magnitude_unit` rather than being a separate
    #: act: a member correcting "45,000 in collectibles" to "45,000 owed" is stating one fact, and a route
    #: that made them clear the unit first would leave the position in a state
    #: `ck_positions_stock_kind_iff_stock` refuses. `validate_position_state` checks the merged state for
    #: exactly that reason.
    "stock_kind",
    "time_basis",
    "liquidity",
    "started_on",
    "tags",
)


class PositionNotFound(LookupError):
    """No position by that id for this member.

    One exception for both "no such position" and "not yours", for `GoalNotFound`'s reason: the caller
    learns whether they own a position, never whether one exists. The route turns this into a 404.
    """


class PositionUnchanged(ValueError):
    """A change that changes nothing.

    Refused rather than accepted as a no-op — including deactivating a position that is already inactive.
    A Decision saying a change was made when none was is permanent under R-040, so the cheapest place to
    stop is before it exists. Same reasoning as `services/goals.NothingToChange`, and a separate class
    because `plan.py` cannot import `goals.py` without a cycle.
    """


def _statable(value: object) -> object:
    """A value in a form the Decision's JSON can hold. Dates become ISO strings, everything else is
    already JSON-native."""
    return value.isoformat() if isinstance(value, date) else value


def last_decision_id_for_position(session: Session, position: Position) -> str | None:
    """The most recent Decision this position is linked to, or None. R-040's chain.

    Read from the join rather than kept on the row, for the reason `goals._last_decision_id_for` gives: a
    column holding "the last decision" goes stale the first time anybody writes a Decision without
    updating it, and it would be a second source of truth for something the append-only table knows.

    The `id` tiebreak is determinism, **not** chronology — an id is a random uuid. `created_at` carries
    microseconds, so two Decisions about one position effectively cannot tie; if one ever did, the fix is
    a sequence rather than a better sort on this column.
    """
    row = session.execute(
        select(Decision)
        .join(Decision.linked_positions)
        .where(Position.id == position.id)
        .order_by(Decision.created_at.desc(), Decision.id.desc())
    ).scalars().first()
    return row.id if row is not None else None


def _owned_position(session: Session, member_id: str, position_id: str) -> Position:
    position = session.get(Position, position_id)
    if position is None or position.member_id != member_id:
        raise PositionNotFound(f"no position {position_id!r} for this member")
    return position


def _validate_stock(after: dict) -> None:
    """The three rules the stock unit brings, checked here so every write path shares one implementation.

    **They are the same three the two CHECK constraints on `positions` hold**, and both layers exist for
    the reason `api/main.py` and this module both used to carry a copy of the unit list: a member gets a
    sentence, and a caller that went round the service gets refused by the store. If these ever disagree,
    the store wins and the member sees a constraint name — which is the failure this function is the fix
    for, not an argument for dropping either half.

      1. a franc **stock** must say which side of the balance sheet it is on. There is no default: an
         unstated side would make every unmarked debt an asset, silently, which is precisely the ambiguity
         `Position.stock_kind` was chosen over a negative magnitude to prevent.
      2. nothing else may carry one. A flow or a share is not on a balance sheet at all, and a
         `stock_kind` sitting beside `share_of_total` would be read by something eventually.
      3. a franc stock is **not negative**. A liability is a positive amount owed with
         `stock_kind='liability'`; allowing a minus sign would restore the second encoding this design
         exists to remove.
    """
    unit = after.get("magnitude_unit")
    kind = after.get("stock_kind")

    if kind is not None and kind not in STOCK_KINDS:
        raise ValueError(f"unknown stock_kind {kind!r}; expected one of {list(STOCK_KINDS)}")

    if unit in STOCK_UNITS:
        if kind is None:
            raise ValueError(
                f"a magnitude in {unit!r} is a balance, and a balance is either owned or owed. State "
                f"stock_kind as one of {list(STOCK_KINDS)}. There is no default: an unstated side would "
                f"file every debt as an asset without anybody being told."
            )
        if after.get("magnitude") is not None and after["magnitude"] < 0:
            raise ValueError(
                f"a magnitude in {unit!r} is not negative. A liability is the amount owed with "
                f"stock_kind='liability' — one representation, so that a minus sign cannot become a "
                f"second, silent one."
            )
    elif kind is not None:
        raise ValueError(
            f"stock_kind belongs to a magnitude stated in {list(STOCK_UNITS)}; this one is "
            f"{unit!r}. A flow of francs per year and a share of a total are not on a balance sheet, so "
            f"neither has a side to be on."
        )


def validate_position_state(after: dict) -> None:
    """The rules R-120 and R-121 put on a position, checked against the state it would be left in.

    **Against the resulting state, not against the request**, because a partial edit can break an
    invariant without naming the field that breaks it: moving `capital_type` from human to financial
    leaves behind a `time_basis` that R-121 says belongs to human capital, and clearing `magnitude_unit`
    alone leaves a magnitude whose unit was silently dropped. Checking only the stated fields passes both.

    **Against a mapping rather than against the row, and that matters.** Applying the changes to the
    `Position` first and validating afterwards would leave a rejected edit sitting in `session.dirty`,
    where the *next* commit on that session — a legitimate one, somewhere else entirely — would flush it
    and then be refused by C-09 for a mutation its caller never made. So the merged state is computed as a
    dict, checked, and only then written.
    """
    if after["role"] not in ROLES:
        raise ValueError(f"unknown role {after['role']!r}; expected one of {list(ROLES)}")
    if after["capital_type"] not in CAPITAL_TYPES:
        raise ValueError(
            f"unknown capital_type {after['capital_type']!r}; expected one of {list(CAPITAL_TYPES)}"
        )
    if not (after["label"] or "").strip():
        raise ValueError("a position has a label; R-110 renders the grid from it")
    if (after["magnitude"] is None) != (after["magnitude_unit"] is None):
        raise ValueError(
            "a magnitude needs an explicit unit and a unit needs a magnitude. An annualised amount, a "
            "share of total and a balance in francs are not interchangeable, and a guessed unit is worse "
            "than no figure (R-120)."
        )
    if after["magnitude_unit"] is not None and after["magnitude_unit"] not in MAGNITUDE_UNITS:
        raise ValueError(
            f"unknown magnitude_unit {after['magnitude_unit']!r}; expected one of {list(MAGNITUDE_UNITS)}"
        )
    _validate_stock(after)
    if after["liquidity"] is not None and after["liquidity"] not in LIQUIDITY:
        raise ValueError(
            f"unknown liquidity {after['liquidity']!r}; expected one of {list(LIQUIDITY)}. Bands, not "
            f"numbers: a threshold in years would be an assumption under C-02 and nobody has published one."
        )
    if after["time_basis"] and after["capital_type"] != "human":
        raise ValueError(
            "R-121: a time basis belongs to human capital, where hours are the binding constraint. Clear "
            "it in the same request that moves this position to financial capital."
        )
    if not isinstance(after["tags"], dict):
        raise ValueError("tags is a mapping of the five correlation tags (R-021)")
    if unknown := sorted(set(after["tags"]) - set(CORRELATION_TAGS)):
        raise ValueError(
            f"not one of the five correlation tags: {unknown}. Expected keys from "
            f"{list(CORRELATION_TAGS)} — D-02 stores them and reads none of them."
        )


def revise_position(
    session: Session,
    *,
    member_id: str,
    position_id: str,
    changes: dict,
    question: str,
    choice: str,
    reasoning: str | None = None,
) -> dict:
    """Change a position a member has already recorded. **An in-place UPDATE, plus a correcting Decision.**

    **A86 is the precedent and this follows it rather than re-deciding it.** That entry weighed an
    append-only superseding row against an in-place update with the correction recorded on the Decision,
    and chose the second, for four reasons that apply to `positions` at least as strongly as to `goals` —
    A86 argued them for `goals` because that was the route the owner asked for, but every one of them is
    written about both tables:

    1. **`db.py` says these two tables are mutable, and says it deliberately:** "`positions` and `goals`
       carry no append-only trigger (they are legitimately mutable, which is the point of C-09)." An
       append-only `Position` would leave C-09 guarding nothing.
    2. **R-040 is a property of `Decision`, not of every table.** "A correction is a new record
       referencing the prior one" is honoured where R-040 puts it: `corrects_id` on the new Decision, the
       prior one untouched and undeletable at the storage layer.
    3. **A superseding-row scheme fails invisibly, and worse here than for goals.** `positions` is read by
       `grid.py`, `befund.py`, `illustration.py`, `derive.py`, `engine_inputs.py`, `goals.py`, the export
       and the curator's view; `goal_funding` and `decision_positions` both point at a position id, so
       funding and every Decision link would have to be carried forward on every edit. The read path that
       forgot the current-version filter presents as "eigentliCH has doubled my plan" — and on the role
       grid it presents as eight cells of duplicates, which is R-113's meter arriving by accident.
    4. **A position is a holding, not a document.** A vault item's earlier version is evidence and has to
       survive (R-150, `supersedes_id`). A position is what the member has now; what has to survive is
       the record *that it changed*, which is a Decision.

    **The cost is paid the same way.** An UPDATE loses the prior values, so both states go into the
    Decision in C-06's own label/consequence shape — the two options the member actually weighed — plus a
    machine-readable `values` map so the earlier state is readable rather than reconstructable.

    **A revision that changes nothing is refused** (`PositionUnchanged`), for A86's reason: a Decision
    claiming a change that did not happen is permanent under R-040 and makes S-07 less true.

    **C-09 by construction, not by care.** The write goes through `mutate_plan`, so the Decision is in the
    same transaction and the position is linked to it; `before_flush` sees the position in `session.dirty`
    and `_refuse_unvetted_plan_dml` covers the paths that never reach a flush (A72). An edit that forgot
    the Decision raises `PlanMutationWithoutDecision` rather than persisting. That is R-123's second half
    — "creating **or editing** a position writes a Decision in the same transaction" — which had no
    editing to be enforced on until this function existed.
    """
    position = _owned_position(session, member_id, position_id)

    if unknown := sorted(set(changes) - set(POSITION_REVISABLE_FIELDS)):
        if "active" in unknown:
            raise ValueError(
                "R-122: `active` is not revised here. Marking a position inactive is its own act and its "
                "own route, because its Decision says something different from an edit's — see "
                "`set_position_active`."
            )
        raise ValueError(
            f"not a revisable field: {unknown}. Expected one of {list(POSITION_REVISABLE_FIELDS)}"
        )

    before = {name: getattr(position, name) for name in POSITION_REVISABLE_FIELDS}
    # Before anything is written, and before a Decision exists to be thrown away. See
    # `validate_position_state` for why this is a mapping rather than the row.
    validate_position_state({**before, **changes})

    changed = sorted(name for name, value in changes.items() if before[name] != value)
    if not changed:
        raise PositionUnchanged(
            f"position {position_id!r} is already in the state this revision asks for. Nothing was "
            f"written and no Decision was recorded — a Decision saying a change was made when none was "
            f"is permanent (R-040) and would make S-07 less true, not more complete."
        )

    kept = {name: _statable(before[name]) for name in changed}
    stated = {name: _statable(changes[name]) for name in changed}

    with mutate_plan(
        session,
        member_id=member_id,
        question=question,
        choice=choice,
        reasoning=reasoning,
        # R-040 in the shape R-040 asks for. `None` where this position arrived without a Decision of its
        # own, which the append-only table makes impossible to fake.
        corrects_id=last_decision_id_for_position(session, position),
        options_considered=[
            {
                "label": "Position unverändert lassen",
                "consequence": "Die Position behält die Angaben, die bisher festgehalten waren.",
                "values": kept,
            },
            {
                "label": "Position ändern",
                "consequence": "Die Position wird mit den neuen Angaben festgehalten. Die bisherigen "
                               "Angaben bleiben in diesem Entscheid nachlesbar.",
                "values": stated,
            },
        ],
    ) as decision:
        for name in changed:
            setattr(position, name, changes[name])
        decision.linked_positions.append(position)

    return {"position": position, "decision": decision, "changed": changed}


def set_position_active(
    session: Session,
    *,
    member_id: str,
    position_id: str,
    active: bool,
    question: str,
    choice: str,
    reasoning: str | None = None,
) -> dict:
    """R-122. Mark a position inactive, or active again. **Deactivating is not deleting.**

    R-122's own word is *inactive*: "a position may be marked inactive. Inactive positions remain in
    history and in decisions." So this sets a boolean and removes nothing. `services/grid.py` returns
    inactive positions flagged rather than filtered, and `services/befund.py` has a whole sentence for the
    case — *"hier steht nur Stillgelegtes. Stillgelegtes bleibt in der Geschichte"* — which only means
    anything if something can put a position in that state. Until this function existed, nothing could:
    `Position.active` was honoured on six read paths and written by no code at all.

    **Its own act rather than a field on `revise_position`**, and that is a decision:

      * The Decision it writes says something different. An edit corrects what a position *is*; this
        changes what the member's **live plan** is — the Befund stops counting the cell as filled, the
        illustration stops projecting it, `derive.py` stops deriving action items from it. Both options in
        `options_considered` have to name that, and they cannot if the same function also has to describe
        a label being retyped.
      * A boolean in an edit form is how a member deactivates a position by accident. `record_correction`
        is "deliberately not named `amend` or `update`" for the same reason: the name of the operation is
        the statement the interface makes.

    **Reactivation exists, and that is also a decision.** R-122 does not say the mark is one-way, and
    making it one-way would make a mis-click permanent on a table `db.py` calls legitimately mutable.
    A86 declined to build a *delete* because nothing says what removing a goal means for the Decisions
    that reference it — that argument does not reach here, because deactivating references nothing and
    destroys nothing. So one function takes the direction as an argument and the two routes name the two
    acts; setting it to the value it already holds raises `PositionUnchanged`.

    **C-09: deactivating is a material change to the plan**, so it goes through `mutate_plan` like every
    other one and the guard in `db.py` would refuse it without a Decision.
    """
    position = _owned_position(session, member_id, position_id)

    if position.active == active:
        state = "aktiv" if active else "stillgelegt"
        raise PositionUnchanged(
            f"position {position_id!r} is already {state}. Nothing was written and no Decision was "
            f"recorded — a Decision saying a change was made when none was is permanent (R-040)."
        )

    # R-122 in the member's own words, in C-06's label/consequence shape. Both options describe what
    # follows for the live plan, because that is what is actually being decided; the values map carries
    # the boolean so the earlier state is readable rather than inferred from which label was chosen.
    stillgelegt = {
        "label": "Position stilllegen",
        "consequence": "Die Position gehört nicht mehr zum laufenden Plan. Sie bleibt in der Geschichte "
                       "und in den Entscheiden, in denen sie vorkommt, und ist weiterhin nachlesbar.",
        "values": {"active": False},
    }
    laufend = {
        "label": "Position im laufenden Plan behalten",
        "consequence": "Die Position gehört zum laufenden Plan und erscheint in der Rollenmatrix, im "
                       "Befund und in den Illustrationen.",
        "values": {"active": True},
    }
    # The option the member is choosing goes second, so the pair reads as "what stands now, and what is
    # being decided" in both directions rather than only in one.
    options = [laufend, stillgelegt] if not active else [stillgelegt, laufend]

    with mutate_plan(
        session,
        member_id=member_id,
        question=question,
        choice=choice,
        reasoning=reasoning,
        corrects_id=last_decision_id_for_position(session, position),
        options_considered=options,
    ) as decision:
        position.active = active
        decision.linked_positions.append(position)

    return {"position": position, "decision": decision, "changed": ["active"]}
