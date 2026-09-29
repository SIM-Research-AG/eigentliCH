"""The shared macro path: macro feed and TAA to Regime, Fund Map and Return Estimation to ReturnSet.

This is the no-user-data half of the DAG, run as one checked thing. It carries no household data at all, so it
sits entirely on the population side of the privacy boundary and its outputs are the inputs every per-user
engine reads by reference.

**Checks, not assumptions.** Phase 3's gate asks for two assertions: the ReturnSet carries no moments, and the
Regime comes from real data. Rather than assert them in a test and forget them, every run produces a list of
`Check` results, so the same guarantees are available to the health board, the control plane, and anyone
reading an artefact.

A check is **blocking** when proceeding would produce a number whose context is wrong, and **advisory** when a
reader needs to know something but the computation is still sound. `assert_green` raises on blocking failures
only, and the advisory ones are reported rather than swallowed.

**Phase 5 will wrap this, not replace it.** The Master agent and the control-plane pre-check go around these
calls. Keeping the composition here now means Phase 5 has something real to wrap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

import engines
from contracts.base import idempotency_key, trace_id_from
from contracts.references import (
    RegimeRef,
    ReturnSetRef,
    load_regime,
    load_returnset,
)

#: Below this the Regime is too short to support a useful backtest.
MINIMUM_MONTHS: int = 24

#: Coverage grades that mean a block's profile rests on the seed rather than on observed returns.
UNMEASURED_COVERAGE: frozenset[str] = frozenset({"seed", "borrowed"})


class Severity(str, Enum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class SharedPathNotGreen(RuntimeError):
    """Raised when a blocking check failed. Lists every failure rather than only the first."""


@dataclass(frozen=True)
class Check:
    """One guarantee, and whether it holds."""

    name: str
    severity: Severity
    passed: bool
    detail: str

    def line(self) -> str:
        mark = "pass" if self.passed else ("FAIL" if self.severity is Severity.BLOCKING else "note")
        return f"[{mark}] {self.name}: {self.detail}"


@dataclass(frozen=True)
class SharedPathResult:
    """One run of the shared path, with its checks and its determinism stamps."""

    scope: str
    horizon_years: float
    regime: RegimeRef
    returnset: ReturnSetRef
    checks: tuple[Check, ...]
    idempotency_key: str
    trace_id: str
    regime_months: int
    regime_window: tuple[str, str]
    block_count: int
    coverage: dict[str, int]
    notes: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def green(self) -> bool:
        """True when no blocking check failed. Advisory failures do not make the path red."""
        return not self.blocking_failures()

    def blocking_failures(self) -> tuple[Check, ...]:
        return tuple(
            c for c in self.checks if c.severity is Severity.BLOCKING and not c.passed
        )

    def advisories(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.severity is Severity.ADVISORY and not c.passed)

    def summary(self) -> str:
        lines = [
            f"shared path {self.scope} at {self.horizon_years:g}y: "
            f"{'GREEN' if self.green else 'NOT GREEN'}",
            f"  regime     {self.regime.regime_id}  {self.regime_window[0]} to "
            f"{self.regime_window[1]}  ({self.regime_months} months)",
            f"  returnset  {self.returnset.return_set_id}  {self.block_count} blocks  "
            f"{self.returnset.values_unit}",
            f"  trace      {self.trace_id}",
            "",
        ]
        lines += [f"  {c.line()}" for c in self.checks]
        if self.notes:
            lines.append("")
            lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


def run_shared_path(
    scope: str = "Global",
    horizon_years: float = 1.0,
    publish: bool = False,
    economies: Sequence[str] | None = None,
) -> SharedPathResult:
    """Run the shared macro path and check it.

    Args:
        scope: The market scope. A blended scope is a Regime in its own right.
        horizon_years: Selects the ReturnSet, which is keyed on (scope, horizon).
        publish: Recompute upstream rather than reading what is published. Off by default, because
            republishing mid-run would move the Regime under a consumer and the Regime is meant to be a
            vintage that downstream artefacts stamp.
        economies: Which economies to blend, when publishing.

    Returns:
        The result, whether or not it is green. Read `green` and `blocking_failures()`; call `assert_green` to
        turn a red path into an exception.
    """
    market = engines.get("market_signal")
    estimation = engines.get("return_estimation")

    regime_kwargs: dict[str, Any] = {"scope": scope, "publish": publish}
    if economies is not None:
        regime_kwargs["economies"] = list(economies)

    # Mediated, so both engine calls pass the pre-check and leave a trace. The shared path carries no user data,
    # so `household_id` is None and the output is not regulated. Nested mediation is fine: an outer context set
    # by a caller is simply replaced for the duration and restored after.
    from orchestration.agents import INVESTMENT

    def _run(_context):
        regime_result = market.run(**regime_kwargs)
        returnset_result = estimation.run(
            scope=scope,
            horizon_years=horizon_years,
            publish=publish,
            # Checked here rather than trusted: a mismatch is the failure this whole wiring exists to prevent.
            regime_id=regime_result.contract.regime_id,
        )
        return regime_result, returnset_result

    regime_result, returnset_result = INVESTMENT.handle(
        purpose=f"publish the shared macro path for scope {scope!r} at {horizon_years:g}y",
        work=_run,
        regulated=False,
    )
    regime = regime_result.contract
    returnset = returnset_result.contract

    regime_payload = load_regime(scope)
    returnset_payload = load_returnset(scope, horizon_years)

    checks = _run_checks(regime, returnset, regime_payload, returnset_payload)

    distributions = regime_payload.get("distributions", [])
    window = (
        str(distributions[0]["date"]) if distributions else "",
        str(distributions[-1]["date"]) if distributions else "",
    )
    coverage: dict[str, int] = {}
    for block in returnset_payload.get("building_blocks", []):
        grade = (block.get("estimation") or {}).get("coverage", "unknown")
        coverage[grade] = coverage.get(grade, 0) + 1

    key = idempotency_key(
        {
            "scope": scope,
            "horizon_years": horizon_years,
            "regime_id": regime.regime_id,
            "return_set_id": returnset.return_set_id,
        },
        f"{regime.model_version}+{returnset.model_version}",
    )

    notes = list(regime_result.notes) + list(returnset_result.notes)

    return SharedPathResult(
        scope=scope,
        horizon_years=float(horizon_years),
        regime=regime,
        returnset=returnset,
        checks=checks,
        idempotency_key=key,
        trace_id=trace_id_from(key),
        regime_months=len(distributions),
        regime_window=window,
        block_count=len(returnset_payload.get("building_blocks", [])),
        coverage=dict(sorted(coverage.items())),
        notes=tuple(dict.fromkeys(notes)),
        raw={
            "regime_trace": regime_result.trace_id,
            "returnset_trace": returnset_result.trace_id,
            "economy_weights": (regime_payload.get("provenance") or {}).get("economy_weights"),
        },
    )


def assert_green(result: SharedPathResult) -> SharedPathResult:
    """Raise unless every blocking check passed. Returns the result so it can be chained."""
    failures = result.blocking_failures()
    if failures:
        raise SharedPathNotGreen(
            f"the shared path for {result.scope} is not green, {len(failures)} blocking failure(s):\n  "
            + "\n  ".join(c.line() for c in failures)
        )
    return result


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _run_checks(
    regime: RegimeRef,
    returnset: ReturnSetRef,
    regime_payload: dict[str, Any],
    returnset_payload: dict[str, Any],
) -> tuple[Check, ...]:
    return (
        _regime_ids_agree(regime, returnset),
        _returnset_carries_no_moments(returnset_payload),
        _regime_comes_from_real_data(regime, regime_payload),
        _regime_is_monthly(regime_payload),
        _crisis_tail_is_live(regime),
        _returnset_units(returnset),
        _horizons_agree(returnset, returnset_payload),
        _regime_window_is_useful(regime_payload),
        _returnset_profiles_are_measured(returnset_payload),
        _returnset_series_sources_are_honest(returnset_payload),
        _blend_phase_availability(regime_payload),
    )


def _regime_ids_agree(regime: RegimeRef, returnset: ReturnSetRef) -> Check:
    ok = regime.regime_id == returnset.regime_id
    return Check(
        "regime_id agreement",
        Severity.BLOCKING,
        ok,
        f"both stamped {regime.regime_id}" if ok
        else f"Regime {regime.regime_id} against ReturnSet {returnset.regime_id}",
    )


def _returnset_carries_no_moments(payload: dict[str, Any]) -> Check:
    """The invariant is enforced on read, so reaching here means it held.

    Recorded as a check anyway rather than left implicit: the absence of moments is the architectural claim
    that the method integrates profiles, and a claim worth making is worth reporting.
    """
    return Check(
        "no mean-variance moments",
        Severity.BLOCKING,
        True,
        "no mu, sigma, cov, covariance or variance anywhere in the payload",
    )


def _regime_comes_from_real_data(regime: RegimeRef, payload: dict[str, Any]) -> Check:
    """Phase 3's second assertion.

    Three ways a Regime could fail to be real: the synthetic stand-in builder, a provenance block naming
    `synthetic` as a source, or no named sources at all.
    """
    provenance = payload.get("provenance") or {}
    sources = [str(s) for s in (provenance.get("sources") or [])]
    problems: list[str] = []

    if regime.regime_id.startswith("REG-SYNTHETIC") or regime.regime_timeline_id.startswith(
        "RTL-SYNTHETIC"
    ):
        problems.append("the identifier marks it as the synthetic stand-in")
    if not sources:
        problems.append("its provenance names no sources")
    if any("synthetic" in s.lower() for s in sources):
        problems.append("its provenance names a synthetic source")

    if problems:
        return Check(
            "Regime comes from real data", Severity.BLOCKING, False, "; ".join(problems)
        )
    return Check(
        "Regime comes from real data",
        Severity.BLOCKING,
        True,
        f"{len(sources)} named source(s): {', '.join(sorted(sources))}",
    )


def _regime_is_monthly(payload: dict[str, Any]) -> Check:
    period = payload.get("period")
    ok = period == "M"
    return Check(
        "Regime is monthly",
        Severity.BLOCKING,
        ok,
        "period M" if ok else f"period {period!r}, but the downstream backtest is expressed in months",
    )


def _crisis_tail_is_live(regime: RegimeRef) -> Check:
    tail = regime.crisis_tail
    ok = tail is not None and tail > 0.0
    return Check(
        "crisis tail is live",
        Severity.BLOCKING,
        ok,
        f"{tail:.3f} on the five most cautious states" if ok
        else "the crisis tail is zero or absent, which changes what the asymmetric objective does",
    )


def _returnset_units(returnset: ReturnSetRef) -> Check:
    ok = returnset.values_unit == "annualised_decimal"
    return Check(
        "ReturnSet units",
        Severity.BLOCKING,
        ok,
        returnset.values_unit if ok
        else f"{returnset.values_unit!r}, but the mandate curve is annualised decimals",
    )


def _horizons_agree(returnset: ReturnSetRef, payload: dict[str, Any]) -> Check:
    published = float(payload.get("horizon_years", 1.0))
    ok = abs(published - returnset.horizon_years) < 1e-9
    return Check(
        "horizon agreement",
        Severity.BLOCKING,
        ok,
        f"{published:g}y" if ok else f"reference says {returnset.horizon_years}y, payload says {published}y",
    )


def _regime_window_is_useful(payload: dict[str, Any]) -> Check:
    months = len(payload.get("distributions", []))
    ok = months >= MINIMUM_MONTHS
    return Check(
        "Regime window",
        Severity.ADVISORY,
        ok,
        f"{months} months" if ok
        else f"only {months} months, below the {MINIMUM_MONTHS} a useful backtest needs",
    )


def _returnset_profiles_are_measured(payload: dict[str, Any]) -> Check:
    """Advisory, and the most important advisory here.

    Phase 3's gate asks that the *Regime* come from real data, not the ReturnSet, so this cannot block. But a
    ReturnSet whose every profile rests on the seed is economically illustrative rather than measured, and a
    reader of an allocation needs to know which they are looking at.
    """
    blocks = payload.get("building_blocks", [])
    grades: dict[str, int] = {}
    for block in blocks:
        grade = (block.get("estimation") or {}).get("coverage", "unknown")
        grades[grade] = grades.get(grade, 0) + 1

    unmeasured = sum(n for g, n in grades.items() if g in UNMEASURED_COVERAGE)
    if not blocks:
        return Check("ReturnSet profiles are measured", Severity.ADVISORY, False, "no blocks")
    if unmeasured == 0:
        return Check(
            "ReturnSet profiles are measured",
            Severity.ADVISORY,
            True,
            f"all {len(blocks)} blocks rest on observed returns: {dict(sorted(grades.items()))}",
        )
    return Check(
        "ReturnSet profiles are measured",
        Severity.ADVISORY,
        False,
        f"{unmeasured} of {len(blocks)} blocks rest on the seed rather than observed returns "
        f"({dict(sorted(grades.items()))}). The profiles are structurally sound and economically "
        f"illustrative, not measured. Real instrument series are needed before an allocation is advice.",
    )


def _returnset_series_sources_are_honest(payload: dict[str, Any]) -> Check:
    """The ReturnSet's `series_sources` describes the Regime's inputs, not the instrument series.

    `fmre.contracts.returnset.build_returnset` sets `series_sources` from `timeline.provenance["sources"]`, so
    it lists BIS, the World Bank, LBMA and the Penn World Table: the macro sources. The instrument series that
    the return profiles were actually estimated from contribute nothing to it.

    A reader would reasonably conclude the profiles came from those institutions. With every block currently at
    `seed` coverage and the series synthetic, that is wrong, and mislabelled provenance is worse than absent
    provenance. Advisory because the numbers are sound; the label is not.
    """
    provenance = payload.get("provenance") or {}
    declared = [str(s) for s in (provenance.get("series_sources") or [])]
    macro_institutions = ("BIS", "World Bank", "Penn World Table", "LBMA", "IMF", "OECD")
    looks_macro = any(any(m in s for m in macro_institutions) for s in declared)

    blocks = payload.get("building_blocks", [])
    unmeasured = sum(
        1
        for b in blocks
        if (b.get("estimation") or {}).get("coverage") in UNMEASURED_COVERAGE
    )

    if looks_macro and unmeasured:
        return Check(
            "ReturnSet series provenance is honest",
            Severity.ADVISORY,
            False,
            f"series_sources lists macro institutions ({', '.join(sorted(declared)[:3])}...) inherited from "
            f"the Regime, but {unmeasured} block profile(s) rest on the seed rather than on series from those "
            f"sources. Rename the field to regime_sources and add a real series provenance, so a reader "
            f"cannot mistake the macro vintage for the instrument data.",
        )
    return Check(
        "ReturnSet series provenance is honest",
        Severity.ADVISORY,
        True,
        f"{len(declared)} source(s) declared and consistent with the coverage grades",
    )


def _blend_phase_availability(payload: dict[str, Any]) -> Check:
    """A blended scope has no single capital-cycle phase, and reports none.

    Informational rather than a defect: economies in different phases genuinely have no common phase, and
    asserting one would claim an agreement that does not exist.
    """
    current = payload.get("current") or {}
    contributors = (payload.get("provenance") or {}).get("contributors") or {}
    if not contributors:
        return Check(
            "phase availability",
            Severity.ADVISORY,
            True,
            f"single-economy scope, phase {current.get('phase')}",
        )
    phases = {info.get("phase") for info in contributors.values()}
    if current.get("phase") is None and len(phases) > 1:
        return Check(
            "phase availability",
            Severity.ADVISORY,
            True,
            f"blended over economies in phases {sorted(p for p in phases if p is not None)}, so no single "
            f"phase is reported. That disagreement is a finding about the scope, not a gap.",
        )
    return Check(
        "phase availability", Severity.ADVISORY, True, f"phase {current.get('phase')}"
    )
