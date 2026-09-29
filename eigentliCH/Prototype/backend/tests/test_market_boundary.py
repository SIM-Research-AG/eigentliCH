"""Item 7's two hard rules, enforced in code rather than by convention.

    "**Market has no read access to Vault data.** Enforce this in code, not by convention."
    "**Private altitude and public standing are two distinct objects and are never joined.** No query,
     view or render may combine them."

===========================================================================================================
THE FIRST RULE, AS THE OWNER NARROWED IT
===========================================================================================================

Taken literally the first rule collides with R-201 and with item 7's own sentence two paragraphs earlier —
"Index supply by the four roles rather than by profession, so **the member's own role grid tells them which
entry is relevant**." `services/marketplace._member_role_grid` reads `Position.role` to pre-filter, which
is what R-201 asks for.

**Ruled on 4 September 2026: keep the server-side read and narrow the rule.** It means no access to
balances, goals, documents or decisions; *which roles are filled* is too thin to count as Vault data.

That narrowing is only worth having if it is a line rather than a judgement, so this file draws it:

  * the market layer may import `Position` and read `role`, `member_id` and `active`;
  * it may not import `Goal`, `VaultItem`, `Decision`, `Household` or `PlanVersion`;
  * it may not read a magnitude, a label, a target or a date off a position.

A test that only said "no Vault access" would have had to be deleted the first time somebody looked at
R-201. This one survives the narrowing and still refuses the thing the rule is about: a member's money
reaching a screen that lists other people's services.

===========================================================================================================
THE SECOND RULE IS CURRENTLY VACUOUS, AND THAT IS WORTH PINNING
===========================================================================================================

There is no altitude object in this build. A2 excluded it deliberately — "the altitude ring, `alt.score`,
the 'n of m answered' line, the stage progression, and `altitude` as a data key ... are C-07, R-113 and
R-143 violations and the reason the newest client was not adopted wholesale".

So the rule holds today because the object does not exist, which is the weakest possible reason for a rule
to hold. These tests make the absence explicit, so that reintroducing a private progression measure fails
here rather than quietly satisfying nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

#: Every module that composes or serves the Market Place.
MARKET_LAYER = (
    "eigentlich/services/marketplace.py",
    "eigentlich/api/marketplace.py",
)

#: Plan and vault models the Market may not touch at all. `Position` is deliberately absent — see the
#: module docstring and the owner's narrowing.
FORBIDDEN_MODELS = ("Goal", "VaultItem", "Decision", "Household", "HouseholdMember", "PlanVersion")

#: What may be read off a `Position` here: which roles are filled, and for whom. Not what they are worth.
PERMITTED_POSITION_FIELDS = {"role", "member_id", "active", "id"}

#: Words that would name a private progression measure. None of them exists (A2); the point is that they
#: go on not existing.
ALTITUDE_WORDS = ("altitude", "alt_score", "progression_score", "level_score", "rank_score")


def _source(name: str) -> str:
    return (BACKEND / name).read_text(encoding="utf-8")


def _tree(name: str) -> ast.AST:
    return ast.parse(_source(name), filename=name)


# ============================================================ rule 1, as narrowed


@pytest.mark.parametrize("module", MARKET_LAYER)
def test_the_market_imports_no_plan_or_vault_model(module):
    """**Planted violation:** added `Goal` to `services/marketplace.py`'s model import. Failed naming it.

    An import is the right place to check: a module that cannot name `Goal` cannot query it, and no later
    author has to remember a rule.
    """
    imported: set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)

    forbidden = sorted(imported & set(FORBIDDEN_MODELS))
    assert not forbidden, (
        f"{module} imports {forbidden}. Item 7: the Market has no read access to Vault data — balances, "
        f"goals, documents and decisions. Which roles are filled is the one thing it may read."
    )


@pytest.mark.parametrize("module", MARKET_LAYER)
def test_the_market_reads_no_figure_off_a_position(module):
    """The narrowing has a floor: which roles are filled, never what they are worth.

    Asserted over attribute access rather than over imports, because `Position` IS importable here — so
    the line has to be drawn one level in.
    """
    read: set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "Position":
                read.add(node.attr)

    over = sorted(read - PERMITTED_POSITION_FIELDS)
    assert not over, (
        f"{module} reads Position.{over} — a member's money on a screen that lists other people's "
        f"services. Permitted: {sorted(PERMITTED_POSITION_FIELDS)}."
    )


def test_the_permitted_fields_are_actually_used_so_this_is_not_vacuous():
    """A20's shape. A rule about what may be read proves nothing if nothing is read."""
    source = _source("eigentlich/services/marketplace.py")
    assert "Position.role" in source, (
        "nothing reads Position.role any more, so the two tests above forbid an empty set"
    )


def test_no_market_payload_carries_a_franc_figure(session, member):
    """The rule made behavioural rather than structural, because an import check cannot see a join that
    arrives through a service call.

    **Planted violation:** added the member's stated stocks to the browse payload. Failed on the amount.
    """
    from eigentlich.services.marketplace import browse

    payload = browse(session, member_id=member.id, language="de")
    blob = str(payload)
    for forbidden in ("magnitude", "amount_chf", "target_amount", "net_worth", "balance"):
        assert forbidden not in blob, f"a Market payload carries {forbidden!r}"


# ============================================================ rule 2, pinned while it is vacuous


@pytest.mark.parametrize("module", MARKET_LAYER)
def test_no_private_progression_measure_exists_to_be_joined(module):
    """A2 excluded the altitude ring and `alt.score` as C-07, R-113 and R-143 violations.

    The second hard rule therefore holds because the object does not exist — the weakest reason a rule can
    hold. This makes the absence explicit, so reintroducing one fails here rather than quietly satisfying
    nothing.
    """
    source = _source(module).lower()
    found = [word for word in ALTITUDE_WORDS if word in source]
    assert not found, (
        f"{module} names {found}. Item 7: private altitude and public standing are two distinct objects "
        f"and are never joined — and A2 kept the first one out of this build entirely."
    )


def test_public_standing_is_earned_evidence_and_never_the_members_own_plan(session, member):
    """What `member_standing` may be built from, checked at the source.

    Capability assertions and attendance are things the member did in public. A member's own plan is not,
    and a standing computed partly from it would be the join item 7 forbids — with the member's balances
    deciding where they rank among other people.
    """
    import inspect

    from eigentlich.services import marketplace

    source = inspect.getsource(marketplace.member_standing)
    for permitted in ("CapabilityAssertion", "Attendance"):
        assert permitted in source
    for forbidden in ("Position", "Goal", "VaultItem", "Decision"):
        assert forbidden not in source, (
            f"member_standing reads {forbidden}: public standing built from a private record"
        )


def test_standing_and_the_role_filter_are_about_different_people(session, member):
    """The two reads this module makes are not a join, and the reason is who they are about.

    `_member_role_grid` is about the BROWSING member; `member_standing` is about an OFFERING member. Two
    facts about two people in one page is not two facts about one person combined — which is what the rule
    forbids. Asserted so that a future change making them about the same person fails.
    """
    import inspect

    from eigentlich.services import marketplace

    grid = inspect.signature(marketplace._member_role_grid).parameters
    standing = inspect.signature(marketplace.member_standing).parameters
    assert "member_id" in grid and "member_id" in standing
    # Neither function takes both, which is the shape a join would need.
    assert not {"viewer_id", "browsing_member_id"} & set(standing)
    assert not {"offering_member_id", "provider_id"} & set(grid)
