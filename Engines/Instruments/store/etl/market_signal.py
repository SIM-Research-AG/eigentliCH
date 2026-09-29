"""Read the monthly andersCH report: the Market Risk Signal and ten instrument series.

The feed is a single CSV of nine stacked sections, each headed by an upper-case title, a
blank line, a ``Date,...`` header and 240 monthly rows. Two sections matter here and a
third is read as a cross-check.

**This file's dates are one month late, and the loader corrects them.** The prototype's
provenance note establishes it four independent ways -- the GFC's worst months, the COVID
crash, the best month of 2020 and the best month of 2009 all land one month after the
event. The correction is applied on load, recorded in :data:`DATE_SHIFT_MONTHS`, and is
the single most dangerous line in this module: if a future export fixes the bug upstream
and this shift stays, twenty years of history silently move the other way. The loader
therefore re-runs the GFC check on every load and refuses the file if it does not hold.

**Recovering instrument returns.** ``PERFORMANCE CONTRIBUTION`` is not a return series; it
is a cumulated contribution index rebased to 100. The period contribution is its own
growth rate, and contribution is weight times return, so::

    r_i(t) = (index_i(t) / index_i(t-1) - 1) / w_i(t)

with the weight taken from ``INSTRUMENT ALLOCATION`` in the same month. Checked against
market history on load: Global Equities comes back at -21.30 % for October 2008.

**The weight filter, and the bias it does not fix.** Below a 5 % weight the division
amplifies rounding into noise, so months under that threshold are dropped. What the filter
cannot fix is that this is a tactically managed portfolio: an instrument is held when the
signal likes conditions, so a recovered return describes *the asset when it was liked*,
not the asset in that state. Every return this module produces is stored with
``source = 'andersch-report:recovered'`` so that nothing downstream can mistake it for an
unconditional index series.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

#: Months to add to every date in the file to correct the export's off-by-one.
DATE_SHIFT_MONTHS = -1

#: At or below this weight (in per cent) a recovered return is rounding noise rather than
#: a measurement, and the month is dropped. The comparison is **strict** -- a weight of
#: exactly 5.00 is excluded -- which is the convention the M9 census used. Reproducing it
#: matters: on the regime path, strict comparison reproduces that census exactly for all
#: ten instruments, and inclusive comparison puts Global Equities one month out (2011-07
#: sits exactly on the threshold). A census that cannot be reproduced cannot be audited.
MIN_WEIGHT_PCT = 5.0

#: A Market Risk Signal row should sum to 100. The feed is a distribution in intent but
#: not exactly normalised; rows further out than this are flagged, not silently rescaled.
SUM_TOLERANCE_PCT = 0.5

STATE_COUNT = 25

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


class MarketSignalError(ValueError):
    """Raised when the feed does not look the way this loader expects."""


def _parse_period(label: str, shift: int) -> str:
    """``2008-Oct`` plus a month shift, out as ``YYYY-MM``."""
    try:
        year_text, month_text = label.strip().split("-")
        year, month = int(year_text), MONTHS[month_text]
    except (ValueError, KeyError) as exc:
        raise MarketSignalError(f"cannot read the date {label!r}") from exc
    index = (year * 12 + (month - 1)) + shift
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _is_period(label: str) -> bool:
    """Whether a cell reads as a ``YYYY-Mon`` date, without raising if it does not."""
    parts = label.strip().split("-")
    return len(parts) == 2 and parts[0].isdigit() and parts[1] in MONTHS


def _to_float(text: str) -> float | None:
    text = (text or "").strip()
    if not text or text.upper() == "NAN":
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class Section:
    """One block of the stacked CSV."""

    title: str
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)


def split_sections(path: Path) -> dict[str, Section]:
    """Split the stacked CSV into its titled sections."""
    sections: dict[str, Section] = {}
    current: Section | None = None
    awaiting_header = False

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.reader(handle):
            cells = [c.strip() for c in raw]
            if not any(cells):
                continue
            first = cells[0]
            # A title row is a single upper-case cell with nothing beside it, which does
            # not parse as a date. The date test is what keeps `3-MONTH PERFORMANCE` --
            # a title that begins with a digit -- from being read as data and appended to
            # whichever section happens to precede it.
            if first and first.upper() == first and not any(cells[1:]) and not _is_period(first):
                current = Section(title=first, header=[])
                sections[first] = current
                awaiting_header = True
                continue
            if current is None:
                continue
            if awaiting_header:
                current.header = cells
                awaiting_header = False
                continue
            current.rows.append(cells)
    if not sections:
        raise MarketSignalError(f"{path} contained no recognisable sections")
    return sections


@dataclass(frozen=True)
class SignalMonth:
    period: str
    probabilities: tuple[float, ...]   # normalised, 25 long, sums to 1
    raw_sum: float
    in_tolerance: bool

    @property
    def modal_state(self) -> int:
        return 1 + max(range(STATE_COUNT), key=lambda i: self.probabilities[i])

    @property
    def mean_state(self) -> float:
        return sum((i + 1) * p for i, p in enumerate(self.probabilities))


def read_market_risk_signal(sections: dict[str, Section], *, shift: int = DATE_SHIFT_MONTHS
                            ) -> list[SignalMonth]:
    """Read ``MARKET RISK SIGNAL`` into normalised monthly distributions.

    The 25 columns are labelled ``(1): Cautious`` through ``(25): Aggressive``. They are
    taken in their printed order as states 1..25, most cautious first. That correspondence
    is an assumption -- five named bands against a crisis-to-boom ordering -- and it is
    *not* the assumption that the calibration axis is mapped by. The quantile bridge in
    ``engines.fund_map.state_map`` does that mapping, precisely so this loader does not
    have to claim the two axes mean the same thing.
    """
    section = sections.get("MARKET RISK SIGNAL")
    if section is None:
        raise MarketSignalError("the feed has no MARKET RISK SIGNAL section")
    if len(section.header) != STATE_COUNT + 1:
        raise MarketSignalError(
            f"MARKET RISK SIGNAL has {len(section.header) - 1} state columns, expected {STATE_COUNT}"
        )

    out: list[SignalMonth] = []
    for row in section.rows:
        values = [_to_float(c) for c in row[1 : STATE_COUNT + 1]]
        if any(v is None for v in values):
            continue  # an incomplete month is dropped, never part-normalised
        raw = [float(v) for v in values]  # type: ignore[arg-type]
        total = sum(raw)
        if total <= 0:
            continue
        out.append(
            SignalMonth(
                period=_parse_period(row[0], shift),
                probabilities=tuple(v / total for v in raw),
                raw_sum=total,
                in_tolerance=abs(total - 100.0) <= SUM_TOLERANCE_PCT,
            )
        )
    if not out:
        raise MarketSignalError("MARKET RISK SIGNAL yielded no usable months")
    return out


@dataclass(frozen=True)
class RecoveredReturn:
    instrument: str
    period: str
    value: float
    weight_pct: float


#: A GFC checkpoint the loader re-runs on every load, so that a future export which fixes
#: the date bug upstream fails here instead of relabelling twenty years of history.
GFC_CHECK = ("Global Equities", "2008-10", -0.2130, 0.0005)


def recover_instrument_returns(
    sections: dict[str, Section],
    *,
    shift: int = DATE_SHIFT_MONTHS,
    min_weight_pct: float = MIN_WEIGHT_PCT,
) -> tuple[list[RecoveredReturn], list[RecoveredReturn]]:
    """Recover monthly returns from contribution and allocation.

    Returns ``(kept, dropped)`` -- the second list is every month that failed the weight
    filter, carried so the coverage can be reported rather than quietly shrinking.
    """
    contribution = sections.get("PERFORMANCE CONTRIBUTION")
    allocation = sections.get("INSTRUMENT ALLOCATION")
    if contribution is None or allocation is None:
        raise MarketSignalError(
            "recovering returns needs both PERFORMANCE CONTRIBUTION and INSTRUMENT ALLOCATION"
        )
    names = contribution.header[1:]
    if allocation.header[1:] != names:
        raise MarketSignalError(
            "PERFORMANCE CONTRIBUTION and INSTRUMENT ALLOCATION list different instruments"
        )

    weights: dict[str, dict[str, float]] = {n: {} for n in names}
    for row in allocation.rows:
        period = _parse_period(row[0], shift)
        for name, cell in zip(names, row[1:]):
            value = _to_float(cell)
            if value is not None:
                weights[name][period] = value

    kept: list[RecoveredReturn] = []
    dropped: list[RecoveredReturn] = []
    previous: dict[str, float] = {}
    for row in contribution.rows:
        period = _parse_period(row[0], shift)
        for name, cell in zip(names, row[1:]):
            index = _to_float(cell)
            if index is None or index <= 0:
                previous.pop(name, None)
                continue
            prior = previous.get(name)
            previous[name] = index
            if prior is None or prior <= 0:
                continue
            weight = weights[name].get(period)
            if weight is None or weight == 0:
                continue
            contrib = index / prior - 1.0
            recovered = RecoveredReturn(name, period, contrib / (weight / 100.0), weight)
            (kept if weight > min_weight_pct else dropped).append(recovered)

    _assert_gfc(kept + dropped)
    return kept, dropped


def _assert_gfc(recovered: Iterable[RecoveredReturn]) -> None:
    name, period, expected, tolerance = GFC_CHECK
    for item in recovered:
        if item.instrument == name and item.period == period:
            if abs(item.value - expected) > tolerance:
                raise MarketSignalError(
                    f"the date-shift check failed: {name} in {period} recovered as "
                    f"{item.value:.4%}, expected about {expected:.2%}. Either the export's "
                    f"off-by-one has been fixed upstream (in which case set "
                    f"DATE_SHIFT_MONTHS to 0) or the contribution formula no longer holds. "
                    f"Do not load this file until it is understood."
                )
            return
    raise MarketSignalError(
        f"the date-shift check could not run: no {name} observation for {period}"
    )


def instrument_names(sections: dict[str, Section]) -> list[str]:
    section = sections.get("PERFORMANCE CONTRIBUTION")
    if section is None:
        raise MarketSignalError("the feed has no PERFORMANCE CONTRIBUTION section")
    return list(section.header[1:])


def iter_signal_rows(months: Iterable[SignalMonth]) -> Iterator[tuple[str, int, float]]:
    for month in months:
        for index, probability in enumerate(month.probabilities):
            yield month.period, index + 1, probability
