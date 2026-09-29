"""Recommendation and AdviceRelease: the regulated pair, and the wall between them.

The manual's two boundaries: the *privacy* boundary is where user data first appears (the Snapshot); the
*regulatory* wall is where advice first appears. This module is that wall.

**A Recommendation is not advice until a Curator confirms it.** It is produced by the Optimiser as analysis
and carries `RegulatedStatus.REGULATED`, meaning it may not reach a client on its own. The only route across
is: control-plane pre-check, Curator confirm or override, Decision Record written, then and only then a
client sees it. `Recommendation.released` is False on construction and there is no method here that sets it,
because a contract must not be able to release itself.

**The Decision Record is the wall's evidence.** It is immutable, it carries the originating `trace_id`, and
it records who decided what and why. A confirm and an override both write one: an override without a record
would be an unreviewable departure from policy, which is the failure the whole structure exists to prevent.

**Why this class is called `AdviceRelease` while the prose still says "Decision Record".** Renamed on
30 August 2026 (Prototype/DECISIONS.md, A7 and A17). The member application being built against
the build specification has its own `Decision`: keyed on `member_id`, written in the same transaction as
every plan mutation under constraint C-09. That is a different object doing a different job, and two
different objects sharing one name in one system is the more expensive mistake — so the identifier moved and
the member-facing one took the name.

The *concept* is still "Decision Record" in roughly fifty places of prose across thirty files, including
engine internals that section 9 of the specification forbids refactoring, generated HTML surfaces, and two
test assertions that match on the phrase. Renaming the prose is a deliberate follow-on cleanup, not
something to do halfway. Until it happens: **`AdviceRelease` is the identifier, "Decision Record" is the
concept, and they are the same thing.** The member application's `Decision` is not.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.base import (
    Contract,
    Provenance,
    RegulatedStatus,
    Role,
    Scenario,
    content_id,
    require_length,
)
from contracts.references import RegimeRef, ReturnSetRef, require_regime_match

STATE_GRID: int = 25


class WallBreach(RuntimeError):
    """Raised on an attempt to deliver a Recommendation that has not crossed the wall.

    A distinct exception type so the control plane can treat it as the compliance event it is, rather than as
    a generic error.
    """


class Holding(BaseModel):
    """One position in a recommended portfolio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bb_id: int
    name: str
    weight: float
    role: Role
    region_geo: str
    currency: str
    asset_class: str
    #: The bound that set this weight, where one did. Named so a reader learns why a position is the size it
    #: is, rather than assuming the fit chose it.
    set_by: str | None = None


class BindingConstraint(BaseModel):
    """A limit that was active at the optimum, with where it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    category: str
    side: str
    bound: float
    realised: float
    #: derived, policy, or curator_override. A reader must be able to tell the household's own economics
    #: from house policy.
    source: str = "policy"


class FitQuality(BaseModel):
    """How much of the answer the optimisation actually decided.

    Carried because the objective's level is dominated by a floor set by the universe size, so a reader who
    sees only the objective value cannot tell a well-fitted portfolio from a constraint-driven one. See
    PCP decisions.md D28 and D29.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    objective_value: float
    #: The objective with nothing allocated: the part no weighting can reach.
    objective_floor: float
    #: (floor - achieved) / floor. Small means the constraints settled the allocation.
    weight_leverage: float | None = None
    conditions_met: bool = True

    @model_validator(mode="after")
    def _leverage_is_consistent(self) -> "FitQuality":
        if self.weight_leverage is None and self.objective_floor > 0:
            raise ValueError(
                "weight_leverage must be supplied when the objective floor is positive. Omitting it hides "
                "whether the fit or the constraints decided the allocation."
            )
        return self

    @property
    def constraint_driven(self) -> bool:
        return self.weight_leverage is not None and self.weight_leverage < 0.05


class Recommendation(Contract):
    """A proposed allocation. Regulated: not advice until a Curator confirms it."""

    CONTRACT_NAME: ClassVar[str] = "Recommendation"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.REGULATED

    household_id: str
    #: The snapshot this was optimised against, by reference.
    snapshot_id: str
    regime: RegimeRef
    returnset: ReturnSetRef

    holdings: tuple[Holding, ...]
    #: The achieved portfolio profile across the 25 states.
    return_profile: tuple[float, ...]
    #: The mandate curve it was fitted to, carried so the two can be read together.
    target_curve: tuple[float, ...]
    role_allocation: dict[Role, float] = Field(default_factory=dict)
    portfolio_map: tuple[tuple[float, ...], ...] = ()

    binding: tuple[BindingConstraint, ...] = ()
    fit: FitQuality
    esg: float | None = None

    #: False until a Curator confirms. Nothing in this module sets it: only a AdviceRelease can, and it does
    #: so by being written, not by mutating this object.
    released: bool = False
    #: The Decision Record that released it, once one exists.
    decision_record_id: str | None = None

    @field_validator("return_profile", "target_curve")
    @classmethod
    def _twenty_five(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return require_length(value, STATE_GRID, "a 25-state profile")

    @model_validator(mode="after")
    def _weights_and_release_are_coherent(self) -> "Recommendation":
        if self.holdings:
            total = sum(h.weight for h in self.holdings)
            if abs(total - 1.0) > 1e-4:
                raise ValueError(
                    f"the recommended weights sum to {total:.6f}, not 1. A Recommendation that does not "
                    f"allocate the portfolio is not a recommendation."
                )
        if self.released and not self.decision_record_id:
            raise ValueError(
                "a Recommendation cannot be released without the Decision Record that released it. The "
                "record is the wall's evidence; a release without one is a bypass."
            )
        if self.portfolio_map and (
            len(self.portfolio_map) != 4 or any(len(row) != 5 for row in self.portfolio_map)
        ):
            raise ValueError("the portfolio map must be 4 roles by 5 scenarios")
        return self

    def recommendation_id(self) -> str:
        return content_id("REC", self.model_dump(mode="json"))

    def require_deliverable(self) -> None:
        """Raise unless this may be shown to a client as advice.

        Called at the delivery boundary. The check is here, on the contract, rather than in each surface,
        because a rule enforced in several places is a rule that will eventually be enforced in only some.
        """
        if not self.released:
            raise WallBreach(
                f"Recommendation {self.recommendation_id()} has not crossed the regulated wall. It is "
                f"analysis, not advice. Route it through the control-plane pre-check and a Curator "
                f"confirmation, which writes a Decision Record, before delivery."
            )
        if not self.decision_record_id:
            raise WallBreach(
                f"Recommendation {self.recommendation_id()} claims release with no Decision Record."
            )

    def consistency_check(self) -> None:
        """The manual's invariant, checked from the Recommendation's side."""
        require_regime_match(self.returnset.regime_id, self.regime.regime_id)


class Decision(BaseModel):
    """What a Curator decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(description="confirm | override | reject")
    #: Role label, not a person's name. Real names are an overlay to add later.
    decided_by_role: str
    #: The moment of decision, supplied by the caller. A genuine event time, so it is data rather than a
    #: reading taken during serialisation.
    decided_at: str
    rationale: str
    #: Present for an override: what was changed and to what.
    changes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _rationale_and_changes_match_the_action(self) -> "Decision":
        if self.action not in {"confirm", "override", "reject"}:
            raise ValueError(f"unknown action {self.action!r}")
        if not self.rationale.strip():
            raise ValueError(
                "every decision needs a rationale. A confirmation without one cannot be reviewed, and an "
                "override without one is an unexplained departure from policy."
            )
        if self.action == "override" and not self.changes:
            raise ValueError("an override must record what it changed")
        if self.action != "override" and self.changes:
            raise ValueError(f"a {self.action!r} decision must not carry changes")
        return self


class AdviceRelease(Contract):
    """The immutable evidence that a Recommendation crossed the wall.

    Carries the originating `trace_id`, so the whole computation behind a piece of advice can be replayed
    from the record. That is what makes the audit trail real rather than nominal.
    """

    CONTRACT_NAME: ClassVar[str] = "AdviceRelease"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.REGULATED

    household_id: str
    #: What was decided upon.
    recommendation_id: str
    snapshot_id: str
    #: The trace of the computation that produced the Recommendation. The replay handle.
    originating_trace_id: str
    decision: Decision
    #: The control-plane pre-check result that preceded the decision.
    pre_check_passed: bool
    pre_check_findings: tuple[str, ...] = ()
    #: Provenance of every value the Curator was shown, so a decision can be audited against what was
    #: actually visible at the time.
    evidence: dict[str, Provenance] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _a_record_cannot_authorise_what_failed_the_pre_check(self) -> "AdviceRelease":
        if self.decision.action == "confirm" and not self.pre_check_passed:
            raise ValueError(
                "a Recommendation that failed the control-plane pre-check cannot be confirmed. Findings: "
                f"{list(self.pre_check_findings)}. Override it deliberately, with a rationale, or reject it."
            )
        if not self.originating_trace_id:
            raise ValueError(
                "a Decision Record without the originating trace_id cannot be replayed, which makes the "
                "audit trail nominal rather than real."
            )
        return self

    def record_id(self) -> str:
        return content_id("DR", self.model_dump(mode="json"))

    def releases(self) -> bool:
        """Whether this record releases the Recommendation to the client."""
        return self.decision.action in {"confirm", "override"}


def release(recommendation: Recommendation, record: AdviceRelease) -> Recommendation:
    """Return the Recommendation as released by a Decision Record.

    The only route across the wall. A copy is returned rather than the original mutated, so an unreleased
    Recommendation and a released one are different objects and cannot be confused.
    """
    if record.recommendation_id != recommendation.recommendation_id():
        raise WallBreach(
            f"Decision Record {record.record_id()} refers to Recommendation "
            f"{record.recommendation_id}, not {recommendation.recommendation_id()}. A record cannot "
            f"release a different Recommendation from the one it reviewed."
        )
    if record.household_id != recommendation.household_id:
        raise WallBreach("the Decision Record and the Recommendation belong to different households")
    if not record.releases():
        raise WallBreach(
            f"Decision Record {record.record_id()} records a {record.decision.action!r}, which does not "
            f"release the Recommendation."
        )
    return recommendation.model_copy(
        update={"released": True, "decision_record_id": record.record_id()}
    )
