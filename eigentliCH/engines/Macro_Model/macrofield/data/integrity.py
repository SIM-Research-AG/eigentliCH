"""Integrity checks that keep invented values out of the model.

Brief section 2 requires a check that fails the build if any placeholder, dummy, or obviously synthetic
value reaches the model inputs, and brief section 13 forbids fabricating, silently interpolating, or
synthesising figures to fill a series.

Two layers, because neither alone is sufficient:

1. **Declared reliability.** Every series carries a `Reliability` in its provenance. Anything marked
   `SYNTHETIC` is refused outright, and `INTERPOLATED` or `DERIVED` values are refused unless the
   caller has explicitly opted into them. This layer is exact and is the one that matters.

2. **Heuristic detection.** A set of tests for values that look manufactured: a series that never
   moves, a perfectly arithmetic sequence, repeated sentinel values such as 999 or -9999, an
   implausible share of round numbers, or a series that is exactly zero throughout. This layer is
   advisory and can produce false positives on genuinely smooth published data, so it reports findings
   with a severity and the caller decides. It exists to catch a placeholder that someone forgot to
   mark, which is exactly the case layer one cannot see.

The heuristics are deliberately conservative about what they call a failure. A false negative here
means a fabricated number reaches a diagnostic; a false positive means a real series is questioned.
The second is cheap and the first is not, so borderline cases are reported rather than passed, but only
the unambiguous ones raise.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from macrofield.data.provenance import Basis, Reliability, Series, Valuation

#: Values that appear in published data as missing-value sentinels rather than as observations.
SENTINEL_VALUES = (-9999.0, -999.0, -99.0, 9999.0, 999.0, 99999.0, 1e30, -1e30)

#: Sequences that betray hand-typed placeholder data.
PLACEHOLDER_SEQUENCES = (
    (1.0, 2.0, 3.0, 4.0, 5.0),
    (0.0, 1.0, 2.0, 3.0, 4.0),
    (100.0, 200.0, 300.0, 400.0),
    (1.0, 1.0, 1.0, 1.0, 1.0),
    (12345.0,),
    (42.0, 42.0, 42.0, 42.0),
)

#: Minimum observations before the statistical heuristics are meaningful.
MINIMUM_FOR_HEURISTICS = 6


class Severity(enum.Enum):
    """How seriously a finding should be taken."""

    #: Unambiguously not published data. Raises.
    FAIL = "fail"
    #: Suspicious. Reported, and raises only under strict mode.
    WARN = "warn"
    #: Worth recording in the manifest, not a problem in itself.
    INFO = "info"


class SyntheticDataError(ValueError):
    """Raised when a series that must be published data is not."""


@dataclass(frozen=True)
class Finding:
    """One integrity finding about a series."""

    series: str
    check: str
    severity: Severity
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.series}: {self.check}. {self.detail}"


@dataclass
class IntegrityReport:
    """The findings for one or more series."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.FAIL]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]

    @property
    def ok(self) -> bool:
        """Whether nothing failed. Warnings do not make a report unusable."""
        return not self.failures

    def raise_if_failed(self, strict: bool = False) -> None:
        """Raise if anything failed, or if anything at all was found under strict mode.

        Args:
            strict: Treat warnings as failures. The end-to-end calibration test uses this, so that a
                suspicious series cannot reach a published diagnostic unnoticed.

        Raises:
            SyntheticDataError: If the report fails.
        """
        blocking = self.failures + (self.warnings if strict else [])
        if blocking:
            lines = "\n".join(f"  {finding}" for finding in blocking)
            raise SyntheticDataError(
                f"{len(blocking)} integrity problem(s) would reach the model inputs:\n{lines}\n"
                f"The brief forbids fabricated, placeholder or silently interpolated values as model "
                f"inputs. Fix the source or mark the series explicitly and opt into it."
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failures": [str(f) for f in self.failures],
            "warnings": [str(f) for f in self.warnings],
            "info": [str(f) for f in self.findings if f.severity is Severity.INFO],
        }

    def extend(self, other: "IntegrityReport") -> "IntegrityReport":
        self.findings.extend(other.findings)
        return self


def _clean(values: pd.Series) -> np.ndarray:
    """Return the finite observations of a series as an array."""
    array = values.to_numpy(dtype=float)
    return array[np.isfinite(array)]


def check_declared_reliability(
    series: Series,
    allow_derived: bool = False,
    allow_interpolated: bool = False,
) -> IntegrityReport:
    """Check the series' declared reliability against what the caller permits.

    This is the exact layer. A series marked synthetic always fails; derived and interpolated series
    fail unless explicitly permitted, so that opting into a computed input is a visible decision at the
    call site rather than a default.
    """
    report = IntegrityReport()
    reliability = series.provenance.reliability

    if reliability is Reliability.SYNTHETIC:
        report.findings.append(
            Finding(
                series.name,
                "declared synthetic",
                Severity.FAIL,
                f"the provenance of {series.provenance.identifier!r} declares the values synthetic, "
                f"so they must not reach a model input",
            )
        )
    elif reliability is Reliability.INTERPOLATED and not allow_interpolated:
        report.findings.append(
            Finding(
                series.name,
                "contains interpolated values",
                Severity.FAIL,
                f"{series.provenance.identifier!r} contains interpolated values. Pass "
                f"allow_interpolated to accept them, which records the choice.",
            )
        )
    elif reliability is Reliability.DERIVED and not allow_derived:
        report.findings.append(
            Finding(
                series.name,
                "computed rather than published",
                Severity.FAIL,
                f"{series.provenance.identifier!r} is derived by this programme rather than published. "
                f"Pass allow_derived to accept it, which records the choice.",
            )
        )
    elif reliability is Reliability.DERIVED:
        report.findings.append(
            Finding(
                series.name,
                "computed rather than published",
                Severity.INFO,
                "accepted as a derived series. The method is in the transformation log and must appear "
                "on any output that uses it.",
            )
        )

    return report


def detect_synthetic_patterns(series: Series) -> IntegrityReport:
    """Look for values that appear manufactured rather than observed.

    The heuristic layer. Findings are reported with a severity; only unambiguous ones fail.
    """
    report = IntegrityReport()
    values = _clean(series.values)
    name = series.name

    if values.size == 0:
        report.findings.append(
            Finding(name, "no finite observations", Severity.FAIL, "the series is entirely missing")
        )
        return report

    # Sentinel values used by some publishers to mean "missing".
    hits = sorted({float(v) for v in values if float(v) in SENTINEL_VALUES})
    if hits:
        report.findings.append(
            Finding(
                name,
                "missing-value sentinels present",
                Severity.FAIL,
                f"the values {hits} are missing-value sentinels in several published datasets, not "
                f"observations. They must be converted to gaps before use.",
            )
        )

    # Exactly zero throughout.
    if np.all(values == 0.0):
        report.findings.append(
            Finding(name, "all zero", Severity.FAIL, "every observation is exactly zero")
        )
        return report

    # A hand-typed placeholder sequence.
    for sequence in PLACEHOLDER_SEQUENCES:
        window = len(sequence)
        if values.size >= window:
            for start in range(values.size - window + 1):
                if np.allclose(values[start : start + window], sequence):
                    report.findings.append(
                        Finding(
                            name,
                            "placeholder sequence present",
                            Severity.FAIL,
                            f"the sequence {list(sequence)} appears at position {start}, which is "
                            f"placeholder data rather than an observation",
                        )
                    )
                    break

    if values.size < MINIMUM_FOR_HEURISTICS:
        report.findings.append(
            Finding(
                name,
                "too short for the statistical checks",
                Severity.INFO,
                f"{values.size} observations, fewer than the {MINIMUM_FOR_HEURISTICS} needed for the "
                f"constant and linearity checks",
            )
        )
        return report

    # A macroeconomic series that never moves is not an observation of anything.
    if np.allclose(values, values[0]):
        report.findings.append(
            Finding(
                name,
                "constant throughout",
                Severity.FAIL,
                f"every one of {values.size} observations equals {values[0]:g}. No macroeconomic "
                f"quantity behaves this way over a calibration window.",
            )
        )
        return report

    # A perfectly arithmetic sequence indicates a generated ramp.
    differences = np.diff(values)
    if differences.size >= MINIMUM_FOR_HEURISTICS - 1 and np.allclose(
        differences, differences[0], rtol=1e-9, atol=1e-12
    ):
        report.findings.append(
            Finding(
                name,
                "perfectly linear",
                Severity.FAIL,
                f"the first difference is exactly {differences[0]:g} at every step, which is a "
                f"generated ramp rather than observed data",
            )
        )

    # A perfectly geometric sequence indicates a generated exponential.
    if np.all(values > 0.0):
        ratios = values[1:] / values[:-1]
        if ratios.size >= MINIMUM_FOR_HEURISTICS - 1 and np.allclose(
            ratios, ratios[0], rtol=1e-9, atol=1e-12
        ):
            report.findings.append(
                Finding(
                    name,
                    "perfectly exponential",
                    Severity.FAIL,
                    f"the growth factor is exactly {ratios[0]:g} at every step, which is a generated "
                    f"series rather than observed data",
                )
            )

    # An implausible share of round numbers.
    rounded = np.sum(np.isclose(values, np.round(values, 0)))
    share = rounded / values.size
    if share > 0.9 and values.size >= 10:
        report.findings.append(
            Finding(
                name,
                "implausibly round",
                Severity.WARN,
                f"{share:.0%} of observations are whole numbers. Published national accounts are "
                f"rarely this round, so check whether these are estimates typed by hand.",
            )
        )

    # Too few distinct values.
    distinct = np.unique(values).size
    if distinct <= max(2, values.size // 10) and values.size >= 10:
        report.findings.append(
            Finding(
                name,
                "few distinct values",
                Severity.WARN,
                f"only {distinct} distinct values across {values.size} observations",
            )
        )

    return report


def check_series(
    series: Series,
    allow_derived: bool = False,
    allow_interpolated: bool = False,
) -> IntegrityReport:
    """Run both layers over one series."""
    report = check_declared_reliability(series, allow_derived, allow_interpolated)
    report.extend(detect_synthetic_patterns(series))
    return report


def check_model_inputs(
    series: Iterable[Series],
    allow_derived: bool = False,
    allow_interpolated: bool = False,
    strict: bool = False,
) -> IntegrityReport:
    """Check every series destined for a model input, and raise if any fails.

    This is the function the brief's build check calls. It is deliberately the only sanctioned route
    from the data layer into the model, so that nothing reaches a diagnostic without passing it.

    Args:
        series: The series to check.
        allow_derived: Permit series computed by this programme, such as the extended capital stock.
        allow_interpolated: Permit series containing interpolated values.
        strict: Treat warnings as failures.

    Returns:
        The report, if it passed.

    Raises:
        SyntheticDataError: If any series fails.
    """
    report = IntegrityReport()
    for item in series:
        report.extend(check_series(item, allow_derived, allow_interpolated))
    report.raise_if_failed(strict=strict)
    return report


def check_consistency(series: Sequence[Series]) -> IntegrityReport:
    """Check that series intended to be combined share a currency, basis and frequency.

    Brief section 2 requires currency and real-versus-nominal consistency to be enforced. Adding a
    nominal series to a real one, or a euro series to a dollar one, produces a number that looks
    entirely plausible and means nothing, so it must fail rather than warn.
    """
    report = IntegrityReport()
    monetary = [s for s in series if s.provenance.currency is not None]
    if len(monetary) < 2:
        return report

    label = ", ".join(s.name for s in monetary)

    currencies = {s.provenance.currency for s in monetary}
    if len(currencies) > 1:
        report.findings.append(
            Finding(
                label,
                "mixed currencies",
                Severity.FAIL,
                f"these series are in {sorted(currencies)}. Convert explicitly with a rate series that "
                f"carries its own provenance before combining them.",
            )
        )

    bases = {s.provenance.basis for s in monetary}
    if len(bases) > 1:
        report.findings.append(
            Finding(
                label,
                "mixed nominal and real",
                Severity.FAIL,
                f"these series are on {sorted(b.value for b in bases)} bases. A nominal quantity and a "
                f"real quantity cannot be added.",
            )
        )

    # The hazard the currency and basis checks miss. Penn World Table capital stocks are in 2017 US
    # dollars at current PPPs; World Bank constant-price GDP is in 2015 US dollars at market rates.
    # Both are real US dollar series, so nothing above catches the mismatch, yet PPP and market
    # conversions differ by well over a factor of two for some economies.
    valuations = {s.provenance.valuation for s in monetary}
    if len(valuations) > 1:
        report.findings.append(
            Finding(
                label,
                "mixed PPP and market-rate valuation",
                Severity.FAIL,
                f"these series are converted on {sorted(v.value for v in valuations)} bases. They are "
                f"all real currency series, so the currency and basis checks pass, but a ratio built "
                f"from one PPP-converted and one market-rate series is meaningless. Take both from the "
                f"same source, or convert explicitly with a rate series that carries its own "
                f"provenance.",
            )
        )

    frequencies = {s.provenance.frequency for s in series}
    if len(frequencies) > 1:
        report.findings.append(
            Finding(
                ", ".join(s.name for s in series),
                "mixed frequencies",
                Severity.FAIL,
                f"these series are at {sorted(f.value for f in frequencies)} frequency. Resample "
                f"explicitly, recording the method, before combining them.",
            )
        )

    unknown = [s.name for s in series if s.provenance.basis is Basis.UNKNOWN]
    if unknown:
        report.findings.append(
            Finding(
                ", ".join(unknown),
                "basis not stated",
                Severity.FAIL,
                "the source does not state whether these are nominal or real, so they cannot be "
                "combined safely. Establish the basis and record it in the provenance.",
            )
        )

    return report
