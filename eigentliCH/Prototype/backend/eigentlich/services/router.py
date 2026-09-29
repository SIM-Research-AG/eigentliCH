"""The two-branch router. Update script item 1, and the first boundary of Journey & Design page 3.

Every question the ask field takes is classified into exactly one of two branches, and **the split is by
whose data answers it**:

| Branch | Example | What happens | Boundary |
| --- | --- | --- | --- |
| population fact | "How does the AHV household cap work?" | Answered freely. No member data touched. | Below it |
| member situation | "What does that mean for us?" | Requires the Vault. Per-member computation begins. | Crossed |

===========================================================================================================
THERE WERE THREE BRANCHES UNTIL 20 SEPTEMBER 2026
===========================================================================================================

The third was `REGULATED_ADVICE`: a question asking what to do was refused and routed to a curator without
an answer, decided by C-01's inbound classifier. C-01 was withdrawn by the owner (A160) and branch 3 went
with it (A165).

**The split that remains is not the one that was deleted, and the difference matters.** Branch 3 asked
"is this regulated advice" — a question about licensing, answered by a pattern layer that four rounds of
audit could not make converge. The surviving split asks "is this question about the person asking it",
which governs whether their vault may be read. That is C-04 and C-05: data protection, a different law
and a different argument, and it would be just as necessary in a product nobody regulated.

So a question that asks what to do is now simply routed on whether it is about the member, answered like
any other, and nothing in this module refuses it. `requires_curator` survives on the `Route` as a
permanent `False`; the routing to a human that remains in this build is A122's undecidable-lever rule in
`services/liquidity.py`, which is a product decision about a computation that cannot be made, not a
statement about who is licensed.

===========================================================================================================
ADDING A THIRD BRANCH TOUCHES ONE PLACE
===========================================================================================================

That is item 1's acceptance criterion, so it is enforced rather than intended. A branch is an enum member
plus a `BranchSpec`, and `_check_every_branch_is_specified()` runs at import: a `Branch` with no spec, or a
spec naming an unknown boundary, fails the module rather than the request. Everything downstream —
whether member data may be read, which boundary has been crossed, what the client is told — is read off the
spec, so there is no second table to update and forget.

===========================================================================================================
PRECEDENCE, AND WHY IT IS NOT A SCORE
===========================================================================================================

The branches are tried in a fixed order and the first that matches wins:

1. **The member's own situation**, decided by `boundary.asks_about_the_member` — first-person markers.
2. **A population fact**, which is what is left.

There is no confidence, no score and no tie-break. A router that returned "0.7 personal" would leave every
caller to pick a threshold, and the thresholds would disagree.

===========================================================================================================
WHAT THIS MODULE DOES NOT DO
===========================================================================================================

It does not answer anything, read the corpus, touch a session, or phrase anything a member reads.

`services/know.ask` is the only caller that matters, and it reads `reads_member_data` off the route rather
than deciding for itself. That is what makes "no member data touched" on the population branch a property
of the code rather than of the caller's care, and it is the guarantee this module exists for now that the
regulatory branch is gone.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from ..boundary import asks_about_the_member


class Branch(enum.Enum):
    """The two branches. Values are the strings that travel in a payload and must not change lightly."""

    POPULATION_FACT = "population_fact"
    MEMBER_SITUATION = "member_situation"


#: The boundary of Journey & Design page 3, plus the ground below it. Named here so a payload can say
#: which one a question crossed without a client inferring it from the branch.
#:
#: `regulated_advice` was the third, and was removed with C-01 (A165). It is not left as an unreachable
#: value: a boundary nothing can return is a thing the next reader has to work out is dead.
#:
#:   below_both               the regime and the return profiles: population-level, no member data at all
#:   per_member_computation   the boundary. Begins at the Life Balance Sheet
BOUNDARIES = ("below_both", "per_member_computation")


@dataclass(frozen=True)
class BranchSpec:
    """Everything that follows from a branch. One place, so a third branch is one entry."""

    #: Whether the member's own material may be read while answering. **The only reader of this is
    #: `know.ask`**, and it is a permission rather than a hint: the population branch answers without ever
    #: selecting a vault item, which is what "no member data touched" means when written down.
    reads_member_data: bool
    boundary: str
    #: Whether an answer is produced at all. True for both branches since A165 — the branch that did not
    #: answer was the advice refusal. Kept rather than removed because it is what `requires_curator` reads,
    #: and a third branch that routes somewhere without answering is a thing this build may want again.
    answers: bool


SPECS: dict[Branch, BranchSpec] = {
    Branch.POPULATION_FACT: BranchSpec(
        reads_member_data=False, boundary="below_both", answers=True
    ),
    Branch.MEMBER_SITUATION: BranchSpec(
        reads_member_data=True, boundary="per_member_computation", answers=True
    ),
}


def _check_every_branch_is_specified() -> None:
    """Item 1: adding a branch requires touching one place. This is what enforces it."""
    missing = [branch.name for branch in Branch if branch not in SPECS]
    if missing:  # pragma: no cover - an import-time contract
        raise RuntimeError(
            f"branch(es) {missing} have no BranchSpec. Everything downstream reads the spec, so a branch "
            f"without one would silently inherit whatever the caller happened to do."
        )
    unknown = sorted(
        {spec.boundary for spec in SPECS.values()} - set(BOUNDARIES)
    )
    if unknown:  # pragma: no cover - an import-time contract
        raise RuntimeError(f"BranchSpec names unknown boundaries: {unknown}")
    extra = [branch for branch in SPECS if branch not in set(Branch)]
    if extra:  # pragma: no cover - an import-time contract
        raise RuntimeError(f"SPECS has entries that are not branches: {extra}")


_check_every_branch_is_specified()


@dataclass(frozen=True)
class Route:
    """Where one question goes, and why."""

    branch: Branch
    #: What matched. Present so a route is inspectable — "because you wrote 'unsere'" rather than "true".
    matched: tuple[str, ...] = ()

    @property
    def spec(self) -> BranchSpec:
        return SPECS[self.branch]

    @property
    def reads_member_data(self) -> bool:
        return self.spec.reads_member_data

    @property
    def boundary(self) -> str:
        return self.spec.boundary

    @property
    def requires_curator(self) -> bool:
        """False on every route since A165. See the module docstring.

        Kept on the payload rather than removed from it because `client/surfaces/ask.js` and
        `client/surfaces/know.js` both read the field, and an answer path that stops sending a key the
        client reads is a silent `undefined` rather than a visible change. It is now a constant, and
        the constant is the honest statement of what this router decides about curators: nothing.
        """
        return not self.spec.answers

    def as_dict(self) -> dict:
        return {
            "branch": self.branch.value,
            "boundary": self.boundary,
            "reads_member_data": self.reads_member_data,
            "requires_curator": self.requires_curator,
            # The patterns, not the question. A route travels in a payload and a log line; the member's own
            # words do not (C-04's habit, applied to something that is not a stored field).
            "matched": list(self.matched),
        }


def route(question: str) -> Route:
    """Classify one question. Pure: no session, no corpus, no model, no I/O.

    An empty question routes to `POPULATION_FACT` rather than raising. Nothing has been asked, so nothing
    has crossed a boundary, and the caller's own emptiness check is a better place to complain than a
    classifier's.
    """
    text = (question or "").strip()

    # 1. The member's own situation. This is the whole of the decision now, and it decides one thing:
    #    whether the vault may be opened to answer.
    personal = asks_about_the_member(text)
    if personal:
        return Route(branch=Branch.MEMBER_SITUATION, matched=tuple(personal))

    # 2. What is left is a fact about the world.
    return Route(branch=Branch.POPULATION_FACT)


__all__ = [
    "BOUNDARIES",
    "Branch",
    "BranchSpec",
    "Route",
    "SPECS",
    "route",
]
