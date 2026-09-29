"""Trajectory, Scenario and Score: the education-side per-user contracts.

All three are `Education` rather than `Regulated`, so they may reach a client without a Curator. That is the
whole point of them: a client can see where they stand, run a what-if, and watch a goal approach, without any
of it constituting advice.

**The line that must not be crossed.** A Scenario says "if you did X, the model projects Y". A Recommendation
says "do X". The difference is not tone, it is whether the output names an action to take. So a Scenario
carries the change the *client* proposed, never one the system proposes, and `Scenario.change_origin` records
which. A system-originated change dressed as a what-if would be advice with the label filed off.

**Every projected path is labelled.** `model_derived=True` is not decoration: the ground rules require it,
and a trajectory read as a forecast is the commonest way a projection misleads.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.base import Contract, Provenance, RegulatedStatus, Sourced, content_id
from contracts.references import RegimeRef


class TrajectoryPoint(BaseModel):
    """One period on a projected path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    t_years: float
    #: Expected value at this point.
    value: float
    #: The confidence band, where the projection carries one.
    lower: float | None = None
    upper: float | None = None

    @model_validator(mode="after")
    def _band_is_ordered(self) -> "TrajectoryPoint":
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError(f"band lower={self.lower} exceeds upper={self.upper} at t={self.t_years}")
        return self


class Trajectory(Contract):
    """A goal's projected path: the S-curve.

    Model-derived, not a forecast. The `epsilon` the band is drawn at is recorded, because a band without its
    confidence level says nothing.
    """

    CONTRACT_NAME: ClassVar[str] = "Trajectory"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.EDUCATION

    household_id: str
    goal_kind: str
    #: One goal may have several; this identifies which.
    goal_ref: str
    horizon_years: float
    #: The confidence the band is drawn at, matching the household solve.
    epsilon: float
    points: tuple[TrajectoryPoint, ...]
    #: The requirement the path is measured against.
    target: float | None = None
    #: Whether the projection clears the target at the stated confidence.
    on_track: bool | None = None
    regime: RegimeRef | None = None
    model_derived: bool = True

    @field_validator("points")
    @classmethod
    def _ascending_and_non_empty(cls, value: tuple[TrajectoryPoint, ...]) -> tuple[TrajectoryPoint, ...]:
        if not value:
            raise ValueError("a trajectory needs at least one point")
        times = [p.t_years for p in value]
        if times != sorted(times):
            raise ValueError("trajectory points must be in ascending time order")
        return value

    @model_validator(mode="after")
    def _labelled(self) -> "Trajectory":
        if not self.model_derived:
            raise ValueError(
                "a Trajectory is a projection and must carry the model-derived label. Presenting one as an "
                "observation is the commonest way a projection misleads."
            )
        return self

    def trajectory_id(self) -> str:
        return content_id("TRJ", self.model_dump(mode="json"))


class ScenarioChange(BaseModel):
    """The change a scenario applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(description="What was changed, for example 'contributions' or 'horizon_years'")
    from_value: Any = None
    to_value: Any = None
    description: str


class Scenario(Contract):
    """A what-if: the household's position under a proposed change.

    Education, and it stays education only because the change is the client's. A change the *system* proposed,
    presented as a what-if, would be a recommendation with its label removed.
    """

    CONTRACT_NAME: ClassVar[str] = "Scenario"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.CONDITIONAL

    household_id: str
    #: The snapshot the change was applied to.
    base_snapshot_id: str
    change: ScenarioChange
    #: Who proposed the change. `client` keeps this educational; `system` makes it regulated.
    change_origin: str = "client"
    #: What the change did, as named quantities with provenance.
    outcome: dict[str, Sourced] = Field(default_factory=dict)
    #: The projected path under the change, where one was produced.
    trajectory: Trajectory | None = None
    regime: RegimeRef | None = None
    model_derived: bool = True

    @model_validator(mode="after")
    def _origin_governs_status(self) -> "Scenario":
        if self.change_origin not in {"client", "system", "curator"}:
            raise ValueError(f"unknown change_origin {self.change_origin!r}")
        if self.change_origin == "system":
            raise ValueError(
                "a system-originated change is not a what-if, it is a proposal, and a proposal is a "
                "Recommendation. Route it through the wall rather than presenting it as a Scenario. If the "
                "system is illustrating an option the client asked about, set change_origin='client'."
            )
        return self

    def scenario_id(self) -> str:
        return content_id("SCN", self.model_dump(mode="json"))


class ScoreComponent(BaseModel):
    """One contribution to a score, with its weight, so a score can be taken apart."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float
    weight: float
    note: str | None = None


class Score(Contract):
    """A household's standing, computed from its event stream and the Regime.

    Educational and deliberately decomposable: an opaque number a client cannot interrogate is not education.
    """

    CONTRACT_NAME: ClassVar[str] = "Score"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.EDUCATION

    household_id: str
    value: float
    #: The scale the value sits on, so a bare number cannot be misread.
    scale_min: float = 0.0
    scale_max: float = 100.0
    components: tuple[ScoreComponent, ...] = ()
    #: Tier or ladder position, where the programme defines one.
    tier: str | None = None
    regime: RegimeRef | None = None
    #: How many events the score was computed from. A score from three events is not a score from three
    #: hundred, and a reader should be able to tell.
    events_considered: int | None = None

    @model_validator(mode="after")
    def _in_scale_and_weights_sum(self) -> "Score":
        if not self.scale_min <= self.value <= self.scale_max:
            raise ValueError(
                f"score {self.value} lies outside its declared scale [{self.scale_min}, {self.scale_max}]"
            )
        if self.components:
            total = sum(c.weight for c in self.components)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"score component weights sum to {total:.6f}, not 1, so the decomposition does not "
                    f"account for the score"
                )
        return self

    def score_id(self) -> str:
        return content_id("SCR", self.model_dump(mode="json"))
