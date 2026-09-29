"""Return Estimation, including the Fund Map. Reads the Regime and the instrument universe, writes the
ReturnSet.

Wraps `fmre`, unchanged. The ReturnSet carries per-block return profiles across the 25 regime states and
**no mean-variance moments**: the check for that is in `contracts.references.load_returnset` and runs on every
read, because their absence is an invariant of the architecture rather than of one engine.

**Keyed on (scope, horizon).** A ten-year per-state return is not a one-year return compounded, because the
regime does not persist for ten years, so each horizon is separately estimated. See
architecture/DESIGN_snapshot_to_mandate.md section 5.2. The Fund Map does not yet key its artefacts that way,
so the resolver prefers the keyed path and falls back to today's flat `artifacts/rs.json`.
"""

from __future__ import annotations

from typing import Any

from contracts.references import ReturnSetRef, load_returnset, require_regime_match, returnset_path
from engines.base import EngineAdapter, EngineResult, register


class ReturnEstimationAdapter(EngineAdapter):
    name = "return_estimation"
    produces = "ReturnSet"
    model_version = "re@0.2.0"

    def run(
        self,
        scope: str = "Global",
        horizon_years: float = 1.0,
        publish: bool = False,
        source: str = "seed-aware-synthetic",
        regime_id: str | None = None,
        **_: Any,
    ) -> EngineResult:
        """Return a reference to the ReturnSet for `scope` and `horizon_years`.

        When `regime_id` is given, the loaded ReturnSet is checked against it. That is the manual's invariant,
        applied here so a mismatch surfaces at the engine boundary rather than deep inside the Optimiser.
        """
        notes: list[str] = []
        call = None

        if publish:
            timeline = f"../Macro_Model/output/regime/{scope}.json"
            arguments = [
                "-m", "fmre.cli", "build-returnset",
                "--timeline", timeline,
                "--source", source,
                "--horizon-years", str(horizon_years),
                "--out", "artifacts/rs.json",
            ]
            call, _, _ = self.invoke(
                arguments, timeout=1800, extra_env={"PYTHONPATH": "src"}
            )
            notes.append(f"estimated against {timeline} at {horizon_years}y from source {source!r}")
            if source != "csv":
                notes.append(
                    "the instrument series are synthetic, generated to reproduce the seed's per-state means. "
                    "The profiles are therefore structurally sound and economically illustrative, not "
                    "measured. Real data needs --source csv."
                )

        payload = load_returnset(scope, horizon_years)
        reference = ReturnSetRef.from_payload(payload, scope=scope)

        if regime_id is not None:
            require_regime_match(reference.regime_id, regime_id)

        if reference.regime_id.startswith("REG-SYNTHETIC"):
            notes.append(
                "this ReturnSet was estimated against the synthetic stand-in Regime, so it must not be used "
                "for an allocation. Rebuild it against a published Regime."
            )

        coverage: dict[str, int] = {}
        for block in payload.get("building_blocks", []):
            grade = (block.get("estimation") or {}).get("coverage", "unknown")
            coverage[grade] = coverage.get(grade, 0) + 1

        if call is None:
            call = self._read_only_call(scope, horizon_years)

        return self.result(
            contract=reference,
            call=call,
            inputs={"scope": scope, "horizon_years": horizon_years, "source": source},
            as_of=reference.as_of,
            notes=notes,
            raw={
                "blocks": len(payload.get("building_blocks", [])),
                "coverage": dict(sorted(coverage.items())),
                "values_unit": reference.values_unit,
                "universe_version": reference.universe_version,
            },
        )

    def _read_only_call(self, scope: str, horizon_years: float):
        from engines.base import EngineCall

        return EngineCall(
            engine=self.name,
            command=("<read>", str(returnset_path(scope, horizon_years))),
            cwd=str(self.home),
            returncode=0,
        )

    def smoke(self) -> EngineResult:
        """Read the published ReturnSet and check it against the published Regime."""
        from engines.base import get

        regime = get("market_signal").run(scope="Global", publish=False)
        return self.run(
            scope="Global", horizon_years=1.0, publish=False, regime_id=regime.contract.regime_id
        )


register(ReturnEstimationAdapter())
