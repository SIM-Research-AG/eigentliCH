"""Adapter: the Score engine behind the standard interface, returning a Score."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from contracts.analysis import Score as ScoreContract
from contracts.analysis import ScoreComponent
from contracts.fdt import EventKind, EventStream, FDTEvent
from contracts.references import RegimeRef
from engines.base import EngineResult, NativeEngineAdapter, register
from engines.score.engine import (
    MINIMUM_EVENTS,
    NotEnoughHistory,
    SCALE_MAX,
    SCALE_MIN,
    score,
)


class ScoreAdapter(NativeEngineAdapter):
    name = "score_engine"
    produces = "Score"
    model_version = "score@0.1.0"

    def run(
        self,
        household_id: str,
        stream: EventStream | Sequence[FDTEvent] | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
        months_observed: int = 12,
        regime: RegimeRef | None = None,
        weights: Mapping[str, float] | None = None,
        as_of: str = "2024-12-31",
        **_: Any,
    ) -> EngineResult:
        """Score a household from its event stream.

        Accepts an `EventStream`, a sequence of `FDTEvent`, or plain mappings. When given a stream it uses
        `live()`, so a correction is not counted alongside the event it corrects.

        Raises:
            NotEnoughHistory: Below the event floor. Deliberately propagated rather than caught: "not yet
                scored" is the correct answer for a thin stream, and the caller should say so rather than being
                handed a number.
        """
        rows = self._rows(household_id, stream, events)

        scored = score(
            rows,
            months_observed=months_observed,
            crisis_tail=regime.crisis_tail if regime else None,
            weights=weights,
        )

        contract = ScoreContract(
            as_of=as_of,
            model_version=self.model_version,
            household_id=household_id,
            value=scored.value,
            scale_min=SCALE_MIN,
            scale_max=SCALE_MAX,
            components=tuple(
                ScoreComponent(name=c.name, value=c.value, weight=c.weight, note=c.note)
                for c in scored.components
            ),
            tier=scored.tier,
            regime=regime,
            events_considered=scored.events_considered,
        )

        notes = list(scored.notes)
        if regime is None:
            notes.append(
                "no Regime was supplied, so conduct maintained against an adverse macro state received no "
                "credit. The score is comparable across households but not across regimes."
            )

        return self.result(
            contract=contract,
            call=self.native_call(),
            inputs={
                "household_id": household_id,
                "events": [
                    {"kind": r.get("kind"), "occurred_at": r.get("occurred_at")} for r in rows
                ],
                "months_observed": months_observed,
                "crisis_tail": regime.crisis_tail if regime else None,
                "weights": dict(weights) if weights else None,
            },
            as_of=as_of,
            notes=notes,
            raw={
                "tier": scored.tier,
                "regime_adjustment": scored.regime_adjustment,
                "events_considered": scored.events_considered,
                "components": {c.name: round(c.value, 2) for c in scored.components},
            },
        )

    @staticmethod
    def _rows(
        household_id: str,
        stream: EventStream | Sequence[FDTEvent] | None,
        events: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if stream is not None:
            live = stream.live() if isinstance(stream, EventStream) else tuple(stream)
            wrong = [e.event_id() for e in live if e.household_id != household_id]
            if wrong:
                raise ValueError(
                    f"{len(wrong)} event(s) in the stream belong to another household. Scoring a mixed stream "
                    f"would attribute one person's conduct to another."
                )
            return [
                {"kind": e.kind, "occurred_at": e.occurred_at, "body": dict(e.body)} for e in live
            ]
        if events is not None:
            return [dict(e) for e in events]
        raise ValueError("the Score engine needs either a stream or a sequence of events")

    def smoke(self) -> EngineResult:
        """A household with a year of steady behaviour, built from real FDTEvent objects.

        Constructed through the contract rather than as loose dicts, so the smoke run exercises the event
        envelope's own validation too.
        """
        events: list[FDTEvent] = []
        sequence = 0
        for month in range(1, 13):
            events.append(
                FDTEvent(
                    as_of="2024-12-31",
                    model_version="fdt@0.1.0",
                    household_id="smoke-household",
                    sequence=sequence,
                    kind=EventKind.CONTRIBUTION_MADE,
                    occurred_at=f"2024-{month:02d}-01T09:00:00Z",
                    body={"amount": 3_000, "currency": "CHF"},
                )
            )
            sequence += 1

        events.append(
            FDTEvent(
                as_of="2024-12-31", model_version="fdt@0.1.0", household_id="smoke-household",
                sequence=sequence, kind=EventKind.GOAL_SET,
                occurred_at="2024-01-05T09:00:00Z",
                body={"kind": "fi", "target": 2_000_000, "horizon_years": 10},
            )
        )
        sequence += 1
        events.append(
            FDTEvent(
                as_of="2024-12-31", model_version="fdt@0.1.0", household_id="smoke-household",
                sequence=sequence, kind=EventKind.LIABILITY_REPAID,
                occurred_at="2024-06-30T09:00:00Z", body={"amount": 20_000, "currency": "CHF"},
            )
        )

        return self.run(
            household_id="smoke-household",
            stream=EventStream(household_id="smoke-household", events=tuple(events)),
            months_observed=12,
        )


register(ScoreAdapter())
