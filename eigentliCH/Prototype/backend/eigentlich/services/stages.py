"""S-05, the stage map, and S-09, the life-event modules. The Planner's two content-record screens.

**One module for two screens, because they are the same kind of thing.** Neither has a table: both read a
content file, both compose a payload, and neither computes anything about a member that a member could be
graded on. S-13 and S-14 each own state and get their own module; these two own none.

**R-140 and R-006 are held by what this module cannot produce.** There is no current stage, no completed
stage, no next stage, no share of stages opened, and no comparison between a member's age and a stage's
`age_marker`. None of that is withheld from the payload — none of it is computed anywhere, so a client has
nothing to render it from. `stage_map` returns five descriptions and says out loud that they are not a
sequence a member is somewhere on.

**R-141 is held by an absent parameter.** `stage` takes a key and a language and nothing else. There is no
age argument to pass and therefore no age check to forget to remove, which is the same move `models/access.py`
makes by not naming its table `Event`.

**R-142 is enforced at load, not by the file's good behaviour.** `NG-02` is the reason there is no stage
after 50, and a sixth record with `age_marker: 65` would be decumulation content arriving through a JSON
edit. `_stages()` raises on it.

**R-183 is why the life-event half of this module reads as if it were unfinished.** It is not unfinished.
Seven modules exist, all with the shape R-180 names, and every authored field on every one of them is
empty. The retrieval R-181 asks for is built and tested; it simply has nothing to retrieve *by* until
someone authors the `vault_kinds` of a module. `module_payload` states that reason explicitly rather than
returning an empty list that would read as "your vault has nothing relevant" — a materially different, and
false, statement to make to somebody in the week their partner died.
"""

from __future__ import annotations

import json
from functools import lru_cache

from sqlalchemy.orm import Session

from ..content import CONTENT, DEFAULT_LANGUAGE, ContentMissing
from ..models import Member
from .vault import current_items

#: The two content records this module reads. Loaded the way `services/learning.py` loads its own — same
#: root, same exception, no literal fallback — rather than through `content.py`, because adding accessors
#: there is an edit to a file this change does not own. They belong there once it does.
STAGES = "stages"
LIFE_EVENTS = "life-events"

#: R-142 / NG-02. The last stage. A record beyond this is drawdown content, which is out of scope for the
#: whole product and not only for this screen.
NO_STAGE_AFTER = 50

#: S-09's seven, in the specification's own order. Named here as well as in the file so that a module
#: quietly disappearing from the content record is a failure rather than a shorter list.
LIFE_EVENT_KEYS = (
    "separation",
    "job_loss",
    "illness_and_incapacity",
    "death_of_a_partner",
    "inheritance",
    "caring_for_parents",
    "move_abroad_or_return",
)

#: R-180. The four things a module says. Checked as a shape on every record, because "the same shape" is
#: only a property of the file while something asserts it.
MODULE_FIELDS = ("first_steps", "do_not_sign", "vault_kinds", "curator_role")

#: R-183, said once. Every unauthored payload carries this rather than a different phrasing per field.
NOT_AUTHORED = "not_authored_r183"


class StageAfterTheLast(Exception):
    """R-142 / NG-02. A stage beyond 50 reached the content file.

    Raised at load rather than filtered out silently: a filtered record is a piece of drawdown content
    somebody wrote, believing it would ship, and finding out on the day it does not is later than finding
    out now.
    """


class ModuleShapeDiffers(Exception):
    """R-180. A life-event module missing one of the four fields the others carry.

    Seven records that differ in shape are seven screens, and S-09 is one screen shown seven times.
    """


# ---------------------------------------------------------------- content


@lru_cache(maxsize=1)
def _stages() -> dict:
    path = CONTENT / f"{STAGES}.json"
    if not path.exists():
        raise ContentMissing(
            f"stage content not found at {path}. S-05's five stages are content records; there is "
            f"deliberately no literal to fall back to."
        )
    data = json.loads(path.read_text(encoding="utf-8"))

    beyond = [s["key"] for s in data["stages"] if int(s["age_marker"]) > NO_STAGE_AFTER]
    if beyond:
        raise StageAfterTheLast(
            f"R-142: no stage after {NO_STAGE_AFTER}. Found {beyond}. Living from assets, capital against "
            f"annuity and AHV timing are NG-02 — a later scope, not a later stage."
        )
    return data


@lru_cache(maxsize=1)
def _life_events() -> dict:
    path = CONTENT / f"{LIFE_EVENTS}.json"
    if not path.exists():
        raise ContentMissing(
            f"life-event modules not found at {path}. S-09's seven modules are content records; there is "
            f"deliberately no literal to fall back to, and generating one would be R-183 exactly."
        )
    data = json.loads(path.read_text(encoding="utf-8"))

    for record in data["modules"]:
        missing = [name for name in MODULE_FIELDS if name not in record]
        if missing:
            raise ModuleShapeDiffers(
                f"R-180: life-event module {record['key']!r} is missing {missing}. Every module carries "
                f"the same four fields, empty or not."
            )
    return data


def stages() -> list[dict]:
    """The five, in file order. File order is the order of the `age_marker`s and nothing more."""
    return _stages()["stages"]


def stage(key: str) -> dict:
    """One stage record.

    **No age parameter, and that is R-141.** A member may open any stage regardless of age, so there is
    nothing here to compare an age against.
    """
    for record in stages():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no stage {key!r}")


def stages_are_reviewed() -> bool:
    """False until someone reads the German and clears the flag in the file. See A42 for the precedent."""
    return bool(_stages().get("reviewed", False))


def modules() -> list[dict]:
    return _life_events()["modules"]


def module(key: str) -> dict:
    for record in modules():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no life-event module {key!r}")


def module_is_authored(key: str) -> bool:
    """R-183. False on all seven, and it is meant to be.

    This is the function whose answer changing is the news: it turns true when a person has written a
    module, never when a model has.
    """
    return bool(module(key).get("authored", False))


def _localised(block: dict | None, language: str) -> str | None:
    """A member-facing string in one language, or None. Never a placeholder, never the other language."""
    if not block:
        return None
    return block.get(language) or None


# ---------------------------------------------------------------- S-05


def stage_payload(record: dict, language: str = DEFAULT_LANGUAGE) -> dict:
    """One stage: a situation and the questions it raises. Nothing about the member reading it."""
    return {
        "key": record["key"],
        # R-141 / R-140. The age at which this situation typically arrives — never a condition of entry
        # and never compared to anybody's age.
        "age_marker": record["age_marker"],
        "age_marker_is_not_an_entry_condition": True,
        "title": _localised(record["title"], language),
        # R-140. A description of circumstances. Not a level, not a target, not an assessment.
        "situation": _localised(record["situation"], language),
        # Content navigation (R-006): the questions the situation raises, with no answers attached. An
        # answer here would be a recommendation, and C-01 puts those behind a licensed human.
        "questions": [q for q in (_localised(q, language) for q in record["questions"]) if q],
        # A12 / A42's precedent: the German has not been read by its owner yet, and the payload says so
        # rather than letting a draft pass as reviewed.
        "reviewed": stages_are_reviewed(),
    }


def stage_map(
    session: Session | None = None,
    *,
    member_id: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """S-05. All five stages, all open, in age-marker order.

    `member_id` is optional and buys exactly one thing: `opens_at`, the member's `stage_hint`, which the
    model layer describes as content routing only. It is where the map opens, not where the member is —
    the payload denies that reading in a field of its own, because it is the reading an interface would
    otherwise invite.

    **What this deliberately does not return:** a current stage, a completed count, a share of stages
    opened, a next stage, or any comparison between `age_at_registration` and an `age_marker`. R-140 and
    R-006. None of it is filtered out at the end; none of it is computed at all.
    """
    opens_at = None
    if member_id is not None and session is not None:
        member = session.get(Member, member_id)
        hint = getattr(member, "stage_hint", None)
        if hint and any(record["key"] == hint for record in stages()):
            opens_at = hint

    return {
        "member_id": member_id,
        "language": language,
        "stages": [stage_payload(record, language) for record in stages()],
        # R-141, stated in the payload so a client author meets it before designing a locked row.
        "any_stage_may_be_opened": True,
        # R-140. Where the map opens. Not a position, not a score, not an achievement.
        "opens_at": opens_at,
        "opens_at_is_not_a_position": True,
        # R-142 / NG-02, in the payload rather than only in the file: a client that renders "and then?"
        # after the last stage should read this first.
        "no_stage_after": NO_STAGE_AFTER,
        "no_stage_after_reason": "NG-02",
        # NO progress, NO completed count, NO percentage, NO rank — R-006. There is nothing to filter out
        # here because there is nothing computed above.
    }


# ---------------------------------------------------------------- S-09


def relevant_vault_items(
    session: Session, *, member_id: str, kinds: tuple[str, ...] | list[str]
) -> list[dict]:
    """R-181. The member's own vault items of the given kinds, retrieved rather than asked for.

    Current versions only: a superseded contract is history, and R-041 keeps it, but it is not the
    document somebody needs in the first week of a life event.

    Returns titles and ids — never contents. `VaultItem` is K3 (C-04), and a life-event payload travels
    to a browser; what it carries is the fact that a document exists and where it is, which is what
    "retrieve these" means.
    """
    if not kinds:
        return []
    wanted = set(kinds)
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "title": item.title,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        }
        for item in current_items(session, member_id=member_id)
        if item.kind in wanted
    ]


def module_payload(
    session: Session,
    *,
    key: str,
    member_id: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """S-09. One module, in the shape R-180 names, with the member's relevant vault items attached.

    **Every authored field comes back null or empty, and the payload says why.** R-183: module content is
    authored, not generated, and the framework ships empty rather than filled with generated text. So
    `first_steps`, `do_not_sign` and `curator_role` are empty and carry `NOT_AUTHORED`, and a client is
    expected to render that as "not written yet" rather than as "nothing to do".

    **`vault_items` is empty for a reason that is not "your vault is empty".** Retrieval works; it selects
    by the kinds a module names, and an unauthored module names none. Those are different facts and the
    payload keeps them apart — `retrieval_unavailable_reason` is set exactly when the module is unauthored.
    """
    record = module(key)
    authored = bool(record.get("authored", False))

    kinds = list(record.get("vault_kinds") or [])
    items: list[dict] = []
    if member_id is not None and kinds:
        items = relevant_vault_items(session, member_id=member_id, kinds=kinds)

    return {
        "key": record["key"],
        "member_id": member_id,
        "language": language,
        # R-183. The marker, first, so nothing below it can be mistaken for content.
        "authored": authored,
        "unauthored_reason": None if authored else NOT_AUTHORED,
        "authored_by": record.get("authored_by"),
        "title": _localised(record.get("title"), language),
        # R-180's four fields, present on every module whether or not anything has been written into them.
        "first_steps": [s for s in (_localised(s, language) for s in record["first_steps"]) if s],
        "do_not_sign": [s for s in (_localised(s, language) for s in record["do_not_sign"]) if s],
        "vault_kinds": kinds,
        "vault_items": items,
        # The distinction that matters: nothing was retrieved because nothing has been named to retrieve,
        # not because the member holds nothing.
        "retrieval_unavailable_reason": None if kinds else NOT_AUTHORED,
        "curator_role": record.get("curator_role"),
        # R-182. The key is the address. The Know opens a module directly rather than through a menu, and
        # this is the identifier it opens.
        "opened_by_key": record["key"],
    }


def life_event_modules(
    session: Session | None = None,
    *,
    member_id: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """S-09. All seven modules, in the specification's own order.

    Listed even though none is authored: the framework existing is the deliverable of this phase, and a
    list that hid the unauthored ones would be an empty screen with no explanation on it.
    """
    payloads = []
    for key in LIFE_EVENT_KEYS:
        record = module(key)
        payloads.append(
            {
                "key": key,
                "authored": bool(record.get("authored", False)),
                "unauthored_reason": None if record.get("authored") else NOT_AUTHORED,
                "title": _localised(record.get("title"), language),
            }
        )

    return {
        "member_id": member_id,
        "language": language,
        "modules": payloads,
        # R-183 at the file level, so a caller reading the list meets the rule before the records.
        "authored": bool(_life_events().get("authored", False)),
        "unauthored_reason": _life_events().get("unauthored_reason"),
        # R-180. The shape all seven share, named so that a client builds one renderer rather than seven.
        "module_fields": list(MODULE_FIELDS),
    }
