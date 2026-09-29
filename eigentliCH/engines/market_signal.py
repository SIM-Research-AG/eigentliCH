"""Market Signal: the macro field-model engine. Reads the macro feed and the TAA, writes the Regime.

Wraps `macrofield`, unchanged. Publishing a Regime is `macrofield regime <economies> --scope <scope>`, which
writes `output/regime/<scope>.json`, and the adapter returns a typed `RegimeRef` to it.

**A blended scope is a Regime in its own right.** The country-weight blend lives here rather than downstream,
because a ReturnSet is estimated under exactly one Regime and stamps its identifier: a blend computed after
the fact would carry an id no ReturnSet could match. See architecture/DECISIONS.md M3.
"""

from __future__ import annotations

from typing import Any, Sequence

from contracts.references import RegimeRef, load_regime
from engines.base import EngineAdapter, EngineResult, register

#: The economies the seven-slot country-weight blend needs. `eurozone` is absent deliberately: the Penn World
#: Table publishes no capital stock for the EMU aggregate, so the EU slot is its members weighted by GDP.
BLEND_ECONOMIES: tuple[str, ...] = ("cn", "in", "us", "ch", "br", "gb", "de", "fr")


class MarketSignalAdapter(EngineAdapter):
    name = "market_signal"
    produces = "Regime"
    model_version = "ms@0.1.0"

    def run(
        self,
        scope: str = "Global",
        economies: Sequence[str] = BLEND_ECONOMIES,
        publish: bool = False,
        blend_weight: float | None = None,
        **_: Any,
    ) -> EngineResult:
        """Return a reference to the Regime for `scope`, publishing it first if asked.

        `publish=False` by default. Republishing on every read would make the Regime move under a consumer
        mid-run, and the Regime is meant to be a vintage that downstream artefacts stamp.
        """
        notes: list[str] = []
        call = None

        if publish:
            arguments = ["-m", "macrofield.cli", "regime", *economies, "--scope", scope]
            if blend_weight is not None:
                arguments += ["--blend-weight", str(blend_weight)]
            call, stdout, _ = self.invoke(arguments, timeout=1800)
            notes.append(f"published {scope} from {len(economies)} economies")
            if "could not be published" in stdout:
                notes.append(
                    "at least one economy could not be published; the blend is not renormalised over "
                    "whichever economies happen to be available, so check the engine output"
                )

        payload = load_regime(scope)
        reference = RegimeRef.from_payload(payload, scope=scope)

        provenance = payload.get("provenance") or {}
        if provenance.get("macro_to_monthly"):
            notes.append(
                f"macro half is {provenance.get('macro_frequency', 'annual')}, "
                f"{provenance['macro_to_monthly']}; all intra-year variation is technical"
            )
        contributors = provenance.get("contributors") or {}
        if contributors:
            notes.append(
                "blended over: "
                + ", ".join(f"{c} {info.get('weight', 0):.0%}" for c, info in sorted(contributors.items()))
            )

        if call is None:
            call = self._read_only_call(scope)

        return self.result(
            contract=reference,
            call=call,
            inputs={"scope": scope, "economies": list(economies), "blend_weight": blend_weight},
            as_of=reference.as_of,
            notes=notes,
            raw={
                "months": len(payload.get("distributions", [])),
                "first": (payload.get("distributions") or [{}])[0].get("date"),
                "last": (payload.get("distributions") or [{}])[-1].get("date"),
                "crisis_tail": reference.crisis_tail,
            },
        )

    def _read_only_call(self, scope: str):
        from engines.base import EngineCall

        return EngineCall(
            engine=self.name,
            command=("<read>", f"output/regime/{scope}.json"),
            cwd=str(self.home),
            returncode=0,
        )

    def smoke(self) -> EngineResult:
        """Read the published Global Regime. Does not republish: that takes minutes and hits the network."""
        return self.run(scope="Global", publish=False)


register(MarketSignalAdapter())
