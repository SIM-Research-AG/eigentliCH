"""Plausibility checks for series that are real but wrong.

`macrofield.data.integrity` catches data that was *manufactured*: placeholders, sentinels, generated
ramps, series that never move. It cannot catch data that a publisher genuinely produced and that is
nonetheless wrong for the purpose, because nothing about the numbers looks synthetic.

The gap was found in a live run. World Bank reported an equity market capitalisation of 267 per cent of
GDP for India where published figures are nearer 130. Every integrity check passed it: the series moves,
it is not round, it has no sentinels, and it is genuinely what the publisher returned. Only knowing what
the quantity ought to look like catches it.

This module therefore checks values against **documented expected ranges** and against **the source's
own history**. Both are advisory by design. A plausibility bound is a prior, not a fact, and an economy
genuinely can leave the range the literature describes, which is after all the framework's whole thesis.
So these produce warnings that a reviewer reads, and only physically impossible values fail.

Where a range comes from is recorded on the check, because a bound nobody can trace is worse than no
bound: it gets copied forward and hardens into a fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np

from macrofield.data.integrity import Finding, IntegrityReport, Severity
from macrofield.data.provenance import Series


@dataclass(frozen=True)
class ExpectedRange:
    """A documented plausible range for a ratio-type quantity.

    Attributes:
        quantity: The quantity key this applies to.
        low: Lower bound of the ordinary range.
        high: Upper bound of the ordinary range.
        impossible_below: Below this the value cannot be right at all, so it fails rather than warns.
        impossible_above: Above this the value cannot be right at all.
        source: Where the range comes from. Required, because an untraceable bound hardens into a fact.
        note: Anything a reviewer needs in order to judge a breach.
    """

    quantity: str
    low: float
    high: float
    source: str
    impossible_below: float | None = None
    impossible_above: float | None = None
    note: str = ""


#: Expected ranges for the ratio quantities the model consumes, each with its source.
#:
#: These are ordinary ranges, not hard limits. An economy outside one of them is the interesting case,
#: not necessarily the erroneous one, which is why a breach warns rather than fails.
EXPECTED_RANGES: tuple[ExpectedRange, ...] = (
    ExpectedRange(
        quantity="K_R_over_Y",
        low=1.5,
        high=6.5,
        impossible_below=0.0,
        impossible_above=25.0,
        source="Penn World Table 10.01 observed 2019 range across the panel, 3.36 to 5.66, widened",
        note=(
            "book section 10.3 states 2.5 to 3.5, which is narrower than its own nominated source "
            "reports, so the wider observed range is used"
        ),
    ),
    ExpectedRange(
        quantity="K_I_over_Y",
        low=1.0,
        high=8.0,
        impossible_below=0.0,
        impossible_above=40.0,
        source="book section 10.4, 400 to 600 per cent for advanced and 100 to 200 for developing",
        note="the fallback credit-plus-equity measure sits below the primary measure, so the low end is wide",
    ),
    ExpectedRange(
        quantity="saturation",
        low=0.3,
        high=4.5,
        impossible_below=0.0,
        impossible_above=20.0,
        source="BIS total credit to the non-financial sector, observed 1.86 to 3.54 across the panel",
    ),
    ExpectedRange(
        quantity="equity_market_cap_over_Y",
        low=0.05,
        high=2.5,
        impossible_below=0.0,
        impossible_above=10.0,
        source="World Bank CM.MKT.LCAP.CD against GDP; the United States is the panel maximum near 2.24",
        note=(
            "this is the check that would have caught the India reading of 2.67 that prompted this "
            "module"
        ),
    ),
    ExpectedRange(
        quantity="p_s",
        low=0.0,
        high=0.60,
        impossible_below=-1.0,
        impossible_above=1.0,
        source="World Bank NY.GNS.ICTR.ZS gross national savings, observed across the panel",
    ),
    ExpectedRange(
        quantity="depreciation_rate",
        low=0.02,
        high=0.10,
        impossible_below=0.0,
        impossible_above=1.0,
        source="Penn World Table 10.01 delta, observed 0.0379 to 0.0579 across the panel",
    ),
    ExpectedRange(
        quantity="investment_share",
        low=0.05,
        high=0.55,
        impossible_below=-0.5,
        impossible_above=1.5,
        source="World Bank NE.GDI.FTOT.ZS gross fixed capital formation as a share of GDP",
    ),
    ExpectedRange(
        quantity="output_growth",
        low=-0.15,
        high=0.15,
        impossible_below=-1.0,
        impossible_above=2.0,
        source="World Bank NY.GDP.MKTP.KD.ZG; the range covers ordinary recessions and recoveries",
    ),
)

RANGES_BY_QUANTITY: Mapping[str, ExpectedRange] = {r.quantity: r for r in EXPECTED_RANGES}

#: A period-on-period change larger than this multiple of the series' own typical change is reported.
DEFAULT_JUMP_MULTIPLE = 8.0

#: Minimum observations before the jump check is meaningful.
MINIMUM_FOR_JUMP_CHECK = 8


def check_expected_range(series: Series, expected: ExpectedRange | None = None) -> IntegrityReport:
    """Check a series against its documented expected range.

    Values outside the ordinary range warn. Values outside the impossible bounds fail, because those
    are not judgements about plausibility but about arithmetic: a negative capital stock or a savings
    rate above one cannot be right whatever the economy is doing.
    """
    report = IntegrityReport()
    bound = expected or RANGES_BY_QUANTITY.get(series.name)
    if bound is None:
        report.findings.append(
            Finding(
                series.name,
                "no expected range configured",
                Severity.INFO,
                f"no plausibility range is defined for {series.name!r}, so only the integrity checks "
                f"apply. Add one to EXPECTED_RANGES if this quantity should be bounded.",
            )
        )
        return report

    values = series.values.dropna()
    if values.empty:
        return report

    if bound.impossible_below is not None:
        breaches = values[values < bound.impossible_below]
        if not breaches.empty:
            report.findings.append(
                Finding(
                    series.name,
                    "impossible value",
                    Severity.FAIL,
                    f"{len(breaches)} value(s) below {bound.impossible_below:g}, the lowest being "
                    f"{breaches.min():g} at {breaches.idxmin()}. This is not a plausibility judgement: "
                    f"the quantity cannot take that value.",
                )
            )
    if bound.impossible_above is not None:
        breaches = values[values > bound.impossible_above]
        if not breaches.empty:
            report.findings.append(
                Finding(
                    series.name,
                    "impossible value",
                    Severity.FAIL,
                    f"{len(breaches)} value(s) above {bound.impossible_above:g}, the highest being "
                    f"{breaches.max():g} at {breaches.idxmax()}.",
                )
            )

    outside = values[(values < bound.low) | (values > bound.high)]
    if not outside.empty:
        detail = (
            f"{len(outside)} of {len(values)} value(s) outside the expected range "
            f"{bound.low:g} to {bound.high:g}, ranging {outside.min():g} to {outside.max():g}. "
            f"Range source: {bound.source}."
        )
        if bound.note:
            detail += f" {bound.note}"
        detail += (
            " This is a prior, not a limit. An economy genuinely outside the range is the interesting "
            "case, so confirm the value against a second source rather than discarding it."
        )
        report.findings.append(
            Finding(series.name, "outside the expected range", Severity.WARN, detail)
        )

    return report


def check_for_jumps(
    series: Series,
    jump_multiple: float = DEFAULT_JUMP_MULTIPLE,
) -> IntegrityReport:
    """Report period-on-period changes far larger than the series' own typical change.

    Catches a units change mid-series, a rebasing, or a splice between two vintages, none of which look
    synthetic and none of which breach a level range. Scaled by the series' own median absolute change
    rather than by an absolute threshold, so it works across quantities of very different magnitude.
    """
    report = IntegrityReport()
    values = series.values.dropna()
    if len(values) < MINIMUM_FOR_JUMP_CHECK:
        return report

    changes = values.diff().dropna()
    typical = float(np.median(np.abs(changes)))
    if typical <= 0.0:
        return report

    large = changes[np.abs(changes) > jump_multiple * typical]
    for period, change in large.items():
        report.findings.append(
            Finding(
                series.name,
                "abrupt level change",
                Severity.WARN,
                f"the change at {period} is {change:+g}, which is "
                f"{abs(change) / typical:.0f} times the typical period-on-period change of "
                f"{typical:g}. Check for a units change, a rebasing, or a splice between vintages.",
            )
        )
    return report


def check_ratio_against_components(
    ratio: Series,
    numerator: Series,
    denominator: Series,
    tolerance: float = 1e-6,
) -> IntegrityReport:
    """Verify that a ratio series really is its stated numerator over its stated denominator.

    Cheap, and it catches the mistake that no range check can: a ratio assembled from the wrong pair,
    or one whose components were revised after it was computed. Only the overlapping periods are
    compared, since a ratio may legitimately extend beyond its components after an extension.
    """
    report = IntegrityReport()
    shared = ratio.values.index.intersection(numerator.values.index).intersection(
        denominator.values.index
    )
    if len(shared) == 0:
        report.findings.append(
            Finding(
                ratio.name,
                "no overlap with its components",
                Severity.WARN,
                f"{ratio.name!r} shares no periods with {numerator.name!r} and {denominator.name!r}, "
                f"so the ratio cannot be verified against them",
            )
        )
        return report

    expected = numerator.values.loc[shared] / denominator.values.loc[shared]
    actual = ratio.values.loc[shared]
    difference = (actual - expected).abs()
    scale = expected.abs().clip(lower=1e-12)
    relative = (difference / scale).dropna()
    breaches = relative[relative > tolerance]

    if not breaches.empty:
        report.findings.append(
            Finding(
                ratio.name,
                "ratio does not match its components",
                Severity.FAIL,
                f"{len(breaches)} of {len(relative)} overlapping period(s) differ from "
                f"{numerator.name!r} over {denominator.name!r} by more than {tolerance:g} relative, "
                f"the worst being {breaches.max():g} at {breaches.idxmax()}. The ratio was built from "
                f"different inputs than it claims, or its components have since been revised.",
            )
        )
    return report


def check_plausibility(
    series: Iterable[Series],
    jump_multiple: float = DEFAULT_JUMP_MULTIPLE,
) -> IntegrityReport:
    """Run every plausibility check over a set of series.

    Returns the report without raising. Plausibility findings are for a reviewer to weigh, and only the
    impossible-value failures should stop a run, which the caller decides by calling
    `raise_if_failed` on the result.
    """
    report = IntegrityReport()
    for item in series:
        report.extend(check_expected_range(item))
        report.extend(check_for_jumps(item, jump_multiple))
    return report


def summarise(report: IntegrityReport) -> dict[str, object]:
    """Summarise a plausibility report for the calibration report and the manifest."""
    return {
        "impossible": [str(f) for f in report.failures],
        "questionable": [str(f) for f in report.warnings],
        "unbounded_quantities": [
            f.series for f in report.findings if f.check == "no expected range configured"
        ],
        "verdict": "no impossible values" if report.ok else "impossible values present",
    }
