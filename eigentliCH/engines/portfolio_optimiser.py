"""Portfolio Optimiser. Reads a Snapshot and the ReturnSet, writes a Recommendation.

Wraps `pcp`, unchanged. The Optimiser minimises the asymmetric squared shortfall of the mandate curve,
weighted by the live regime, and there is no covariance matrix in the objective.

**Two things the adapter must be honest about.**

The Optimiser as built reads a **mandate** (a target curve plus bounds from YAML), not a
`BalanceSheetSnapshot`. The derivation that closes that gap is specified in
architecture/DESIGN_snapshot_to_mandate.md but not yet implemented, so `run` takes a mandate name and
`from_snapshot` refuses rather than guessing. A snapshot silently reduced to a mandate would be the one thing
the design note exists to prevent.

Its output is a **Recommendation, which is regulated**. The adapter returns it unreleased, and nothing here
can release it: only a Decision Record can, via `contracts.release`.
"""

from __future__ import annotations

import json
from typing import Any

from contracts.advice import BindingConstraint, FitQuality, Holding, Recommendation
from contracts.base import Role
from contracts.references import RegimeRef, ReturnSetRef
from engines.base import EngineAdapter, EngineResult, register

#: The Optimiser reports roles in its own casing; map to the canonical vocabulary on the way in.
_ROLES = {r.value.lower(): r for r in Role}


class PortfolioOptimiserAdapter(EngineAdapter):
    name = "portfolio_optimiser"
    produces = "Recommendation"
    model_version = "pcp@0.1.0"

    def run(
        self,
        mandate: str,
        market: str | None = None,
        speed: str = "exact",
        optimiser: str = "curve",
        household_id: str | None = None,
        snapshot_id: str | None = None,
        **_: Any,
    ) -> EngineResult:
        """Optimise one mandate and return an unreleased Recommendation."""
        arguments = [
            "-m", "pcp.cli", "--json", "optimise", "--mandate", mandate,
            "--speed", speed, "--optimiser", optimiser, "--no-write",
        ]
        if market:
            arguments += ["--market", market]

        # Exit code 1 is a handled failure in the PCP: an infeasible mandate or a missing contract. That is a
        # result to report, not a crash, so it is allowed through and surfaced in the notes.
        call, stdout, stderr = self.invoke(arguments, timeout=900, allow_handled_failure=True)

        if call.handled_failure and not stdout.strip():
            from engines.base import EngineFailed

            raise EngineFailed(
                f"the Optimiser refused mandate {mandate!r}: {stderr.strip()[:400]}",
                call.command, stdout, stderr,
            )

        payload = self._parse(stdout, call, stderr)
        header = payload["header"]
        notes = list(payload.get("notes", []))

        recommendation = Recommendation(
            as_of=header["as_of"],
            model_version=header["engine_version"],
            idempotency_key=header.get("idempotency_key"),
            trace_id=header.get("trace_id"),
            household_id=household_id or f"mandate:{header['client']}/{header['mandate']}",
            snapshot_id=snapshot_id or "not-from-a-snapshot",
            regime=RegimeRef(
                regime_id=header["regime_id"],
                regime_timeline_id=header.get("regime_timeline_id", header["regime_id"]),
                scope=header["market"],
                as_of=header["as_of"],
                model_version=header.get("regime_model_version", "unknown"),
                crisis_tail=header.get("crisis_tail"),
            ),
            returnset=ReturnSetRef(
                return_set_id=header["return_set_id"],
                regime_id=header["regime_id"],
                scope=header["market"],
                horizon_years=float(header.get("horizon_years", 1.0)),
                as_of=header["as_of"],
                model_version=header.get("returnset_model_version", "unknown"),
                universe_version=header.get("universe_version", "unknown"),
                values_unit=header.get("values_unit", "annualised_decimal"),
            ),
            holdings=tuple(self._holdings(payload)),
            return_profile=tuple(float(v) for v in payload["return_dist_final"]),
            target_curve=tuple(float(v) for v in payload["return_dist_target"]),
            role_allocation={
                _ROLES[k.lower()]: float(v)
                for k, v in (payload.get("role_allocation") or {}).items()
                if k.lower() in _ROLES
            },
            portfolio_map=tuple(tuple(float(v) for v in row) for row in payload.get("portfolio_map", [])),
            binding=tuple(
                BindingConstraint(
                    dimension=b["dimension"], category=b["category"], side=b["side"],
                    bound=float(b["bound"]), realised=float(b["realised"]),
                    # The Optimiser does not yet carry each bound's origin. Until the mandate comes from a
                    # snapshot, every bound is authored policy, and saying 'policy' is accurate rather than
                    # a guess.
                    source="policy",
                )
                for b in payload.get("binding_constraints", [])
            ),
            fit=self._fit(payload, header),
            esg=payload.get("esg"),
        )

        if header.get("conditions_met") != "yes":
            notes.insert(
                0,
                "the budget equality was not met within tolerance, so this mandate is infeasible as stated. "
                "The weights are renormalised, which does not make it feasible.",
            )
        if recommendation.fit.constraint_driven:
            notes.append(
                f"the weights control only {recommendation.fit.weight_leverage:.2%} of the objective's "
                f"level, so this allocation was settled mainly by the constraints with the curve fit acting "
                f"as a tie-breaker. An accepted property of the current model, see PCP decisions.md D28, D29."
            )

        recommendation.consistency_check()

        return self.result(
            contract=recommendation,
            call=call,
            inputs={
                "mandate": mandate, "market": market, "speed": speed, "optimiser": optimiser,
            },
            as_of=header["as_of"],
            notes=notes,
            raw={"conditions_met": header.get("conditions_met"), "optimiser": optimiser},
        )

    def from_snapshot(self, snapshot: Any, returnset: ReturnSetRef) -> EngineResult:
        """Not implemented, deliberately.

        The Optimiser reads a mandate; a Snapshot is a state of affairs. The derivation between them is
        specified in architecture/DESIGN_snapshot_to_mandate.md and is Life Balance Sheet work. Reducing a
        snapshot to a mandate here would put the derivation in an adapter, hidden between two engines, which
        is exactly what that note rejects.
        """
        raise NotImplementedError(
            "the Snapshot to mandate derivation belongs in the Life Balance Sheet and is not built yet. See "
            "architecture/DESIGN_snapshot_to_mandate.md and DECISIONS.md M4. Until then call run() with a "
            "mandate name."
        )

    @staticmethod
    def _parse(stdout: str, call: Any, stderr: str) -> dict[str, Any]:
        from engines.base import EngineFailed

        start = stdout.find("{")
        if start < 0:
            raise EngineFailed(
                "the Optimiser produced no JSON payload", call.command, stdout, stderr
            )
        try:
            return json.loads(stdout[start:])
        except json.JSONDecodeError as error:
            raise EngineFailed(
                f"the Optimiser's JSON could not be parsed: {error}", call.command, stdout, stderr
            ) from error

    @staticmethod
    def _holdings(payload: dict[str, Any]) -> list[Holding]:
        out: list[Holding] = []
        for row in payload.get("allocation", []):
            role = _ROLES.get(str(row.get("role", "")).lower())
            if role is None:
                continue
            out.append(
                Holding(
                    bb_id=int(row["bb_id"]),
                    name=str(row.get("name", f"bb_id {row['bb_id']}")),
                    weight=float(row["weight"]),
                    role=role,
                    region_geo=str(row.get("region_geo", "Others")),
                    currency=str(row.get("currency", "Others")),
                    asset_class=str(row.get("asset_class", "Alternative")),
                )
            )
        return out

    @staticmethod
    def _fit(payload: dict[str, Any], header: dict[str, Any]) -> FitQuality:
        floor = header.get("objective_floor")
        leverage = header.get("weight_leverage")
        objective = float(payload.get("objective_value", 0.0))
        if floor is None:
            # An older Optimiser that does not report its floor. Report the objective and say the leverage is
            # unknown by setting the floor to zero, rather than inventing a number.
            return FitQuality(
                objective_value=objective, objective_floor=0.0, weight_leverage=None,
                conditions_met=header.get("conditions_met") == "yes",
            )
        return FitQuality(
            objective_value=objective,
            objective_floor=float(floor),
            weight_leverage=None if leverage is None else float(leverage),
            conditions_met=header.get("conditions_met") == "yes",
        )

    def smoke(self) -> EngineResult:
        """Optimise the mandate that exercises the constraint machinery.

        `fixture_balanced` since 2026-08-02, and hand-authored for exactly this purpose. It was
        `Beisheim_Beisheim_Mandate`, one of the legacy institutional mandates; when those were deleted this
        smoke and seven engine tests failed with it. A smoke test that depends on a demo artefact fails the
        moment the demo changes, which is what happened — the fixture is owned by the suite and does not move
        when the Regime is republished or the roster is replaced.
        """
        return self.run(mandate="fixture_balanced")


register(PortfolioOptimiserAdapter())
