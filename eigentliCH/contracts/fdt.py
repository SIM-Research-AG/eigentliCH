"""The FDT event envelope: the Financial Digital Twin's append-only input.

The twin is event-sourced, so the envelope is the only way anything enters a household's history. Everything
per-user is ultimately derived from a stream of these.

**Append-only, and the envelope enforces it.** An event is frozen and content-addressed, so it cannot be
edited after the fact. A correction is a *new* event that supersedes an earlier one by reference
(`supersedes`), never an edit. That is what makes a household's history reconstructible: the state at any past
moment is the fold of the events up to it, and an edited event would silently rewrite every state after it.

**Sequence, not wall-clock, orders the stream.** `sequence` is a monotonic integer per household. Two events
recorded in the same second still have a definite order, and replay does not depend on clock resolution or on
clocks agreeing between machines. `occurred_at` is when the thing happened in the world, which is data.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.base import Contract, Provenance, RegulatedStatus, content_id


class EventKind:
    """The event vocabulary, as constants rather than an enum.

    Deliberately open: a new wealth entity or habit should not require a contract version bump. What is
    closed is the *envelope*; what is carried is extensible.
    """

    GOAL_SET = "goal.set"
    GOAL_REACHED = "goal.reached"
    ASSET_ADDED = "asset.added"
    ASSET_VALUED = "asset.valued"
    LIABILITY_ADDED = "liability.added"
    LIABILITY_REPAID = "liability.repaid"
    ACTION_TAKEN = "action.taken"
    HABIT_RECORDED = "habit.recorded"
    INCOME_RECORDED = "income.recorded"
    CONTRIBUTION_MADE = "contribution.made"
    PROFILE_UPDATED = "profile.updated"
    CONSENT_GRANTED = "consent.granted"
    CONSENT_WITHDRAWN = "consent.withdrawn"

    ALL: frozenset[str] = frozenset(
        {
            GOAL_SET, GOAL_REACHED, ASSET_ADDED, ASSET_VALUED, LIABILITY_ADDED,
            LIABILITY_REPAID, ACTION_TAKEN, HABIT_RECORDED, INCOME_RECORDED,
            CONTRIBUTION_MADE, PROFILE_UPDATED, CONSENT_GRANTED, CONSENT_WITHDRAWN,
        }
    )


class FDTEvent(Contract):
    """One event in a household's history.

    Frozen and content-addressed. A correction supersedes rather than edits.
    """

    CONTRACT_NAME: ClassVar[str] = "FDTEvent"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.NOT_APPLICABLE

    #: Pseudonymous. Never a name: events cross process boundaries and are retained.
    household_id: str
    #: Monotonic per household. What orders the stream.
    sequence: int
    kind: str
    #: When it happened in the world, supplied by the caller. Not a reading taken at serialisation.
    occurred_at: str
    #: The event's own fields. Shape depends on `kind`, deliberately.
    body: dict[str, Any] = Field(default_factory=dict)
    #: The event this one corrects, if any. A correction is a new event, never an edit.
    supersedes: str | None = None
    #: Where the event came from: client capture, an integration, or a curator.
    origin: str = "client"
    provenance: Provenance | None = None

    @field_validator("sequence")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"sequence={value} must be non-negative")
        return value

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in EventKind.ALL:
            raise ValueError(
                f"unknown event kind {value!r}. Known: {sorted(EventKind.ALL)}. Add it to EventKind rather "
                f"than passing an unrecognised string, so the stream stays interpretable."
            )
        return value

    @model_validator(mode="after")
    def _origin_and_consent_are_coherent(self) -> "FDTEvent":
        if self.origin not in {"client", "integration", "curator", "system"}:
            raise ValueError(f"unknown origin {self.origin!r}")
        # A consent event decides what may be processed, so it must be attributable to the person. A system
        # or integration granting consent on a client's behalf is exactly the thing consent exists to prevent.
        if self.kind in {EventKind.CONSENT_GRANTED, EventKind.CONSENT_WITHDRAWN}:
            if self.origin != "client":
                raise ValueError(
                    f"a {self.kind!r} event must originate from the client, not from {self.origin!r}. "
                    f"Consent granted on a person's behalf by a system is not consent."
                )
        return self

    def event_id(self) -> str:
        return content_id("EVT", self.model_dump(mode="json"))


class EventStream(BaseModel):
    """An ordered slice of one household's events.

    Not a `Contract`: it is a *view* over events rather than a promise between engines. The events themselves
    are the contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    household_id: str
    events: tuple[FDTEvent, ...]

    @model_validator(mode="after")
    def _one_household_strictly_ordered(self) -> "EventStream":
        wrong = [e.event_id() for e in self.events if e.household_id != self.household_id]
        if wrong:
            raise ValueError(
                f"the stream is for household {self.household_id!r} but carries {len(wrong)} event(s) "
                f"belonging to another. Mixing households would corrupt every derived state."
            )
        sequences = [e.sequence for e in self.events]
        if sequences != sorted(sequences):
            raise ValueError("events must be in ascending sequence order")
        duplicates = {s for s in sequences if sequences.count(s) > 1}
        if duplicates:
            raise ValueError(
                f"duplicate sequence number(s) {sorted(duplicates)}. Sequence is what orders the stream, so "
                f"a repeat makes the order ambiguous and replay non-deterministic."
            )
        return self

    def superseded_ids(self) -> frozenset[str]:
        return frozenset(e.supersedes for e in self.events if e.supersedes)

    def live(self) -> tuple[FDTEvent, ...]:
        """The events that have not been superseded.

        A fold over the stream should use this rather than every event, or a correction would be applied
        alongside the thing it corrects.
        """
        superseded = self.superseded_ids()
        return tuple(e for e in self.events if e.event_id() not in superseded)

    def next_sequence(self) -> int:
        return (max((e.sequence for e in self.events), default=-1)) + 1
