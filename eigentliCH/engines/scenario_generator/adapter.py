"""Adapter: the Scenario Generator behind the standard interface, returning a Scenario."""

from __future__ import annotations

from typing import Any

from contracts.analysis import ScenarioChange
from contracts.analysis import Scenario as ScenarioContract
from contracts.analysis import Trajectory, TrajectoryPoint
from contracts.base import Provenance, Reliability, Sourced
from contracts.references import RegimeRef
from engines.base import EngineResult, NativeEngineAdapter, register
from engines.s_curve_trajectory.engine import STEPS_PER_YEAR
from engines.scenario_generator.engine import Baseline, ChangeRefused, apply_change


class ScenarioGeneratorAdapter(NativeEngineAdapter):
    name = "scenario_generator"
    produces = "Scenario"
    model_version = "scenario@0.1.0"

    def run(
        self,
        household_id: str,
        base_snapshot_id: str,
        field: str,
        to_value: Any,
        initial_wealth: float,
        horizon_years: float,
        annual_return: float,
        target: float | None = None,
        annual_contribution: float = 0.0,
        annual_volatility: float | None = None,
        change_origin: str = "client",
        description: str | None = None,
        as_of: str = "2024-12-31",
        regime: RegimeRef | None = None,
        **_: Any,
    ) -> EngineResult:
        """Apply one client-originated change and report what it did.

        `change_origin` defaults to and should remain `client`. The contract refuses `system`, because a change
        the system proposed is a recommendation and belongs behind the wall.
        """
        baseline = Baseline(
            initial_wealth=initial_wealth,
            target=target,
            horizon_years=horizon_years,
            annual_return=annual_return,
            annual_contribution=annual_contribution,
            annual_volatility=annual_volatility,
        )
        outcome = apply_change(baseline, field, to_value)

        provenance = Provenance(
            source=f"{self.name} (Master_Model)",
            as_of=as_of,
            model_version=self.model_version,
            reliability=Reliability.DERIVED,
            note="projected under the client's proposed change",
        )

        measured: dict[str, Sourced] = {
            "final_value": Sourced(value=outcome.changed.final_value, provenance=provenance),
            "final_value_delta": Sourced(value=outcome.final_value_delta, provenance=provenance),
            "contributed_delta": Sourced(value=outcome.contributed_delta, provenance=provenance),
        }
        if outcome.funded_at_delta is not None:
            measured["funds_years_sooner"] = Sourced(
                value=outcome.funded_at_delta, provenance=provenance
            )
        if outcome.required_return_delta is not None:
            measured["required_return_delta"] = Sourced(
                value=outcome.required_return_delta, provenance=provenance
            )
        efficiency = outcome.efficiency()
        if efficiency is not None:
            measured["wealth_per_franc_contributed"] = Sourced(
                value=efficiency, provenance=provenance
            )

        trajectory = Trajectory(
            as_of=as_of,
            model_version=self.model_version,
            household_id=household_id,
            goal_kind="fi",
            goal_ref=f"scenario-{field}",
            horizon_years=float(outcome.changed.horizon_years),
            epsilon=0.10,
            points=tuple(
                TrajectoryPoint(t_years=p.t_years, value=p.value, lower=p.lower, upper=p.upper)
                for p in outcome.changed.points
                if abs(p.t_years * STEPS_PER_YEAR % STEPS_PER_YEAR) < 1e-9
            ),
            target=outcome.changed.target,
            on_track=outcome.changed.on_track,
            regime=regime,
        )

        scenario = ScenarioContract(
            as_of=as_of,
            model_version=self.model_version,
            household_id=household_id,
            base_snapshot_id=base_snapshot_id,
            change=ScenarioChange(
                field=field,
                from_value=outcome.from_value,
                to_value=to_value,
                description=description
                or f"{field} from {outcome.from_value} to {to_value}",
            ),
            change_origin=change_origin,
            outcome=measured,
            trajectory=trajectory,
            regime=regime,
        )

        notes = list(outcome.notes()) + list(outcome.changed.notes)
        notes.append(
            "this is a what-if, not a proposal. The change came from the client; the engine applied it and "
            "reported the consequence. It does not search for a better change, because that would be advice."
        )

        return self.result(
            contract=scenario,
            call=self.native_call(),
            inputs={
                "base_snapshot_id": base_snapshot_id,
                "field": field,
                "to_value": to_value,
                "baseline": {
                    "initial_wealth": initial_wealth,
                    "target": target,
                    "horizon_years": horizon_years,
                    "annual_return": annual_return,
                    "annual_contribution": annual_contribution,
                },
            },
            as_of=as_of,
            notes=notes,
            raw={
                "final_value_delta": outcome.final_value_delta,
                "flips_on_track": outcome.flips_on_track,
                "base_funded_at": outcome.base.funded_at_years,
                "changed_funded_at": outcome.changed.funded_at_years,
            },
        )

    def smoke(self) -> EngineResult:
        """The commonest question a client asks: what if I saved a thousand a month more."""
        return self.run(
            household_id="smoke-household",
            base_snapshot_id="BSS-smoke",
            field="annual_contribution",
            to_value=48_000,
            initial_wealth=450_000,
            target=2_000_000,
            horizon_years=10.0,
            annual_return=0.05,
            annual_contribution=36_000,
            annual_volatility=0.12,
            description="Raise the monthly contribution by one thousand.",
        )


register(ScenarioGeneratorAdapter())
