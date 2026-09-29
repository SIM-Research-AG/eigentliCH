"""Content hooks. Item 5: what turns a piece of content into a statement about this member.

    "Each item in the Feed and Learning panes **declares the input or inputs that turn it personal.**
     Small sets are allowed — up to three.
       * The tap opens the chat with the declared inputs, asked **one at a time rather than as a form**.
       * Where a partial finding is computable after the first answer, show it before asking the next
         question, so the interaction keeps the feel of a tap rather than an intake.
       * Inputs already in the Vault are skipped; a member with a populated Vault goes straight to the
         finding.
       * An item that cannot be personalised within its declared inputs gets no tap. That is an editorial
         constraint, not an engineering one."

===========================================================================================================
THE DECLARATION IS CONTENT, AND IT IS INPUTS RATHER THAN A SENTENCE
===========================================================================================================

Item 5 is precise about this and it is the part most easily got wrong: "**What a content item declares is
which inputs are needed, not a prepared sentence** — the finding itself is composed on the go."

So a hook is a list of at most three input names on the content record, and nothing else. There is no
prepared text, no per-item template and no eligibility rule. What the member gets after answering is
`services/finding`, which composes against the Befund and verifies every figure afterwards — the same
implementation the first session uses, running in the other direction.

===========================================================================================================
NO TAP IS A REAL ANSWER
===========================================================================================================

An item with no declared inputs is not broken and is not incomplete: it is an item whose author decided it
says the same thing to everybody. `tappable` is False, and the surface renders it as reading rather than as
a disabled control — a greyed-out tap is a promise the product is not keeping.

The cap of three is enforced here rather than trusted to the file. An item declaring six inputs is an
intake wearing a tap, which is the thing this mechanism exists to avoid.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..content import ContentMissing, _load
from .inputs import INPUT_ORDER, missing as missing_inputs

#: Item 5: "Small sets are allowed — up to three."
MAX_DECLARED_INPUTS = 3

#: The content record's key for the declaration. Named once so the file, this module and the tests agree.
DECLARATION = "personalises_with"


class UndeclarableInput(ValueError):
    """A content item declares an input nothing can answer.

    Refused rather than ignored: an item declaring `favourite_colour` would offer a tap that can never
    complete, and the member would be asked a question the plan has nowhere to put.
    """


class TooManyInputs(ValueError):
    """More than three. An intake wearing a tap."""


def declared(item: dict) -> list[str]:
    """The inputs one content item declares, validated. `[]` when it declares none.

    Raises:
        UndeclarableInput, TooManyInputs: The declaration is not one this mechanism can honour.
    """
    wanted = list(item.get(DECLARATION) or [])
    if len(wanted) > MAX_DECLARED_INPUTS:
        raise TooManyInputs(
            f"{item.get('key')!r} declares {len(wanted)} inputs; item 5 allows up to "
            f"{MAX_DECLARED_INPUTS}. More than that is an intake wearing a tap."
        )
    unknown = [name for name in wanted if name not in INPUT_ORDER]
    if unknown:
        raise UndeclarableInput(
            f"{item.get('key')!r} declares {unknown}, which nothing can answer. Known inputs: "
            f"{', '.join(INPUT_ORDER)}."
        )
    return wanted


def hook(session: Session, *, member_id: str, item: dict) -> dict:
    """What tapping this item would ask for, for this member.

    `ready` means every declared input is already in the Vault — item 5: "a member with a populated Vault
    goes straight to the finding". `asks` is what is still missing, in a stable order, because the member
    is asked one at a time and two consecutive reads must not reorder the questions.
    """
    wanted = declared(item)
    if not wanted:
        # An editorial decision, not a gap. The item says the same thing to everybody.
        return {"tappable": False, "declares": [], "asks": [], "ready": False}

    asks = missing_inputs(session, member_id=member_id, wanted=wanted)
    return {
        "tappable": True,
        "declares": wanted,
        # One at a time: the surface asks `asks[0]` and comes back. The whole list travels so a client can
        # say how many remain without asking again — and never as a count of the member.
        "asks": asks,
        "ready": not asks,
    }


def learning_items(session: Session, *, member_id: str) -> list[dict]:
    """Every learning unit with its hook resolved for this member.

    The content is loaded from `learning.json`; the hook is computed. A unit that declares nothing comes
    back with `tappable: False` rather than being filtered out — item 5's "gets no tap" is about the
    control, not about the item's presence in the list.
    """
    units = _load("learning")["units"]
    return [
        {
            "key": unit["key"],
            "title": unit.get("title", {}),
            "summary": unit.get("summary", {}),
            "hook": hook(session, member_id=member_id, item=unit),
        }
        for unit in units
    ]


def every_declaration() -> dict[str, list[str]]:
    """`{item key: declared inputs}` for every learning unit, for a test that walks the whole file.

    Enumerated from the content rather than from a run, so an item nobody's fixture reaches is validated
    too — the same reason `derive.every_member_facing_string` exists.
    """
    try:
        units = _load("learning")["units"]
    except ContentMissing:  # pragma: no cover - the file ships with the build
        return {}
    return {unit["key"]: declared(unit) for unit in units}


__all__ = [
    "DECLARATION",
    "MAX_DECLARED_INPUTS",
    "TooManyInputs",
    "UndeclarableInput",
    "declared",
    "every_declaration",
    "hook",
    "learning_items",
]
