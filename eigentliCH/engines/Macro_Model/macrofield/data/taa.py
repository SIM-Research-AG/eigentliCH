"""Reader for the operational TAA market risk signal, and its forward decay.

Phase 0.3 and part of phase 5 of docs/BATTLE_PLAN.md.

The signal is the short-term technical half of the pair the PCP consumes:

    TAA (technical, monthly)  +  SAA (macrofield, this programme)  ->  market risk signal  ->  PCP

It is read from the `MARKET RISK SIGNAL` block of `market_risk_signal.csv`, which carries monthly
distributions over the 25-bin axis from 2006-08 to the file's last month, in per cent. The axis is ordered
1 cautious to 25 aggressive and its five blocks of five are labelled Cautious, Careful, Neutral, Bold and
Aggressive, which is the same partition as `regime.five_regime_bins`.

**The forward decay, and why it is not a hold.** The SAA projects fifteen years; the TAA ends at the last
month in the file. Carrying the last reading forward flat would assert that today's technical signal
describes 2039, which it does not: a technical signal is a statement about the current market, and its
information decays. The author settled this on 2026-07-28: decay exponentially toward the signal's own
long-run average, on a configurable half-life. Beyond roughly two years the merged signal is the SAA alone,
which is the intended division of labour between the two horizons.

Everything read here is `OBSERVED`; everything past the last month is `EXTRAPOLATED`, and the boundary is
reported rather than left to be inferred.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from macrofield.control import Provenance, Segment, Traced

#: The section header that introduces the distribution block.
SECTION = "MARKET RISK SIGNAL"

#: The axis width.
STATES = 25

#: Default location, in the project root.
DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "market_risk_signal.csv"

#: How far a row's total may sit from 100 per cent and still be treated as rounding. Twenty-five values
#: rounded to two decimals can only drift about 0.125, and the observed median across the published file is
#: 0.11 with a 95th percentile of 0.14, so this covers rounding with room to spare.
TOTAL_TOLERANCE = 0.25

#: Beyond this, something structural is wrong with the file rather than with one row.
#:
#: A row past the tolerance is **dropped**, not normalised, on the author's instruction of 2026-07-28: only
#: use a month when it is a full set. The published file has five such rows, three of them about nine points
#: out (2013-11, 2013-12, 2014-02) and two smaller (2009-04, 2008-11), against a median deviation of 0.11
#: across 240 rows. Normalising them would put a shape into the long-run average that the publisher did not
#: assert; dropping them loses five months of a twenty-year history, which costs nothing.
TOTAL_REFUSAL = 15.0

#: Month abbreviations as the file writes them, for parsing "2026-Jul".
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}


class TAAError(ValueError):
    """Raised when the TAA signal cannot be read or does not have the expected shape."""


@dataclass
class TAASignal:
    """The observed TAA history.

    Attributes:
        path: Where it was read from.
        labels: The 25 column headers as published, which carry the stance names.
        months: One `(year, month)` per row, ascending.
        distribution: Rows by 25 states, each row normalised to sum to one.
        rows_dropped: Published rows left out for not totalling 100, with the total as published. Named so
            the gap in the history is visible rather than discovered later.
        notes: Anything a reader must know.
    """

    path: Path
    labels: list[str]
    months: list[tuple[int, int]]
    distribution: np.ndarray
    rows_dropped: list[tuple[str, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def latest_month(self) -> tuple[int, int]:
        return self.months[-1]

    @property
    def latest(self) -> np.ndarray:
        """The most recent distribution, normalised."""
        return self.distribution[-1]

    def as_of(self, year: int, month: int = 12) -> np.ndarray:
        """The last distribution at or before a given month.

        Used to align the monthly TAA with the programme's annual periods: the reading for a year is the
        last month of it that the file carries.
        """
        wanted = (int(year), int(month))
        eligible = [i for i, m in enumerate(self.months) if m <= wanted]
        if not eligible:
            raise TAAError(
                f"the signal starts in {self.months[0][0]}-{self.months[0][1]:02d}, which is after "
                f"{year}-{month:02d}"
            )
        return self.distribution[eligible[-1]]

    def long_run_average(self, months: int | None = None) -> np.ndarray:
        """The unconditional distribution the forward path decays toward.

        Args:
            months: Trailing window. Defaults to the whole history, which is the least arbitrary choice
                and spans several cycles.
        """
        window = self.distribution if months is None else self.distribution[-int(months) :]
        average = window.mean(axis=0)
        total = average.sum()
        return average / total if total else average

    def annual(self, periods: Sequence[int]) -> np.ndarray:
        """One distribution per annual period, taking each year's last available month."""
        return np.vstack([self.as_of(int(p)) for p in periods])


def _parse_month(text: str) -> tuple[int, int] | None:
    """Read '2026-Jul' into (2026, 7). Returns None for anything that is not a month label."""
    parts = str(text).strip().split("-")
    if len(parts) != 2:
        return None
    year_text, month_text = parts
    try:
        year = int(year_text)
    except ValueError:
        return None
    month = _MONTHS.get(month_text.strip()[:3].title())
    if month is None:
        try:
            month = int(month_text)
        except ValueError:
            return None
    if not 1 <= month <= 12:
        return None
    return year, month


def load_signal(path: Path | None = None) -> TAASignal:
    """Read the `MARKET RISK SIGNAL` block.

    Args:
        path: Override the location. Defaults to `market_risk_signal.csv` in the project root.

    Returns:
        The signal, with every row normalised to sum to one.

    Raises:
        TAAError: If the file or the section is missing, the width is not 25, or a row's published total is
            further from 100 than the rounding tolerance. A row that does not total 100 is not a
            distribution, and renormalising it silently would hide whatever produced it.
    """
    source = Path(path) if path is not None else DEFAULT_PATH
    if not source.exists():
        raise TAAError(
            f"the TAA signal was not found at {source}. It is the short-term half of the market risk "
            f"signal and the merge cannot run without it."
        )

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    start = None
    for index, row in enumerate(rows):
        if row and row[0].strip().upper() == SECTION:
            start = index
            break
    if start is None:
        sections = sorted({r[0].strip() for r in rows if r and r[0].strip() and len(r) == 1})
        raise TAAError(
            f"{source.name} has no {SECTION!r} section. Sections found: {', '.join(sections)}"
        )

    # The header is the next row carrying more than one column.
    header_index = None
    for index in range(start + 1, len(rows)):
        if len(rows[index]) > 1:
            header_index = index
            break
    if header_index is None:
        raise TAAError(f"the {SECTION} section in {source.name} carries no header row")

    header = rows[header_index]
    labels = [cell.strip() for cell in header[1 : STATES + 1]]
    if len(labels) != STATES:
        raise TAAError(
            f"the {SECTION} header has {len(labels)} state columns, expected {STATES}. The axis width is "
            f"the interface the PCP consumes, so a different width is a change to be made deliberately."
        )

    months: list[tuple[int, int]] = []
    values: list[np.ndarray] = []
    notes: list[str] = []
    dropped: list[tuple[str, float]] = []

    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip():
            # A blank line ends the block; the next section header follows.
            if months:
                break
            continue
        month = _parse_month(row[0])
        if month is None:
            break

        cells = row[1 : STATES + 1]
        if len(cells) < STATES:
            raise TAAError(f"row {row[0]!r} has {len(cells)} state columns, expected {STATES}")
        try:
            numbers = np.array([float(c) if str(c).strip() else 0.0 for c in cells], dtype=float)
        except ValueError as error:
            raise TAAError(f"row {row[0]!r} carries a non-numeric state value: {error}") from error

        total = float(numbers.sum())
        deviation = abs(total - 100.0)
        if deviation > TOTAL_REFUSAL:
            raise TAAError(
                f"row {row[0]!r} totals {total:.2f} rather than 100, which is past the point where this "
                f"is one bad row rather than a misread file. Check that the {SECTION} block still has "
                f"{STATES} state columns in the same positions."
            )
        if deviation > TOTAL_TOLERANCE:
            # Dropped, not normalised: a month is used only when it is a full set. Named so the gap is
            # visible rather than discovered later as a hole in the history.
            dropped.append((row[0].strip(), total))
            continue
        months.append(month)
        values.append(numbers / total if total else numbers)

    if not months:
        raise TAAError(f"the {SECTION} section in {source.name} carries no data rows")

    ordered = sorted(range(len(months)), key=lambda i: months[i])
    if ordered != list(range(len(months))):
        notes.append("the published rows were not in date order and have been sorted")
        months = [months[i] for i in ordered]
        values = [values[i] for i in ordered]

    notes.append(
        f"read {len(months)} monthly distributions from {months[0][0]}-{months[0][1]:02d} to "
        f"{months[-1][0]}-{months[-1][1]:02d}, normalised from published per cent."
    )
    if dropped:
        worst = ", ".join(
            f"{name} at {total:.2f}"
            for name, total in sorted(dropped, key=lambda x: -abs(x[1] - 100))[:5]
        )
        notes.append(
            f"{len(dropped)} published rows were dropped for not totalling 100 within "
            f"{TOTAL_TOLERANCE}: {worst}. A month is used only when it is a full set, so these are absent "
            f"from the history rather than normalised into it. The remaining months are unaffected and the "
            f"long-run average is taken over the full sets only."
        )

    return TAASignal(
        path=source,
        labels=labels,
        months=months,
        distribution=np.vstack(values),
        rows_dropped=dropped,
        notes=notes,
    )


def decay_forward(
    signal: TAASignal,
    periods: Sequence[int],
    half_life_months: float = 6.0,
    average_window_months: int | None = None,
) -> tuple[np.ndarray, list[Traced]]:
    """Extend the TAA over annual periods, decaying toward its long-run average.

    The weight on the last observed reading is `0.5 ** (elapsed_months / half_life)`, and the remainder
    goes to the long-run average. For a period the file already covers, the observed row is used at full
    weight and no decay applies.

    Args:
        signal: The observed history.
        periods: The annual periods to produce, ascending.
        half_life_months: Months for the observed reading to lose half its weight. The author's default is
            six, which leaves roughly a fortieth of the technical reading after three years.
        average_window_months: Trailing window for the long-run average. Defaults to the whole history.

    Returns:
        A `len(periods) x 25` array, each row normalised, and one `Traced` per period recording whether
        that row is observed or extrapolated.

    Raises:
        TAAError: If the half-life is not positive.
    """
    if half_life_months <= 0:
        raise TAAError(f"the half-life must be positive, got {half_life_months}")

    average = signal.long_run_average(average_window_months)
    last_year, last_month = signal.latest_month
    latest = signal.latest

    out: list[np.ndarray] = []
    traces: list[Traced] = []

    for index, period in enumerate(periods):
        year = int(period)
        if (year, 12) <= (last_year, last_month) or year <= last_year:
            row = signal.as_of(year)
            provenance = Provenance.OBSERVED
            detail = f"published reading for {year}"
            weight = 1.0
        else:
            elapsed = (year - last_year) * 12 + (12 - last_month)
            weight = 0.5 ** (elapsed / float(half_life_months))
            row = weight * latest + (1.0 - weight) * average
            provenance = Provenance.EXTRAPOLATED
            detail = (
                f"decayed from the {last_year}-{last_month:02d} reading toward the long-run average, "
                f"{weight:.1%} weight on the observed signal after {elapsed} months"
            )

        total = row.sum()
        row = row / total if total else row
        out.append(row)
        traces.append(Traced(values=row, segments=[Segment(0, STATES - 1, provenance, detail)]))

    return np.vstack(out), traces


def stance_blocks(labels: Sequence[str]) -> dict[str, tuple[int, int]]:
    """The five stance names and the one-based inclusive bin range each covers.

    Derived from the published headers rather than assumed, so a relabelled export is followed rather than
    silently mismatched. The published form is `(1): Cautious`.
    """
    blocks: dict[str, list[int]] = {}
    for position, label in enumerate(labels, start=1):
        name = str(label).split(":", 1)[-1].strip() or str(label).strip()
        blocks.setdefault(name, []).append(position)
    return {name: (min(bins), max(bins)) for name, bins in blocks.items()}


#: Fallback shape thresholds, used when no config is passed. The values of record live in
#: `config/defaults.yaml` under `regime.shape`, per the rule that every threshold is configuration; these
#: exist so `dispersion` stays callable as a pure function in a test.
MODE_PROMINENCE = 0.25
LEAN_BINS = 2.0


def _prominent_modes(probability: np.ndarray, prominence: float) -> list[int]:
    """The one-based bins of genuinely separate modes, by topographic prominence.

    **Height is not prominence, and using height was a defect.** An earlier version counted any local
    maximum taller than a fraction of the tallest, which counts a shoulder on the side of a big peak. That
    matters here more than it would elsewhere, because the 25-bin axis is built by summing five overlapping
    kernels: the shape is lumpy *by construction*, and a height test reported three to five modes on every
    merged signal, which would have made "a swing market" mean nothing.

    Topographic prominence is the standard definition: a peak's prominence is its height above the lowest
    valley that separates it from any higher peak. A shoulder has almost none, however tall it is. Two peaks
    with a real valley between them both survive, which is exactly the swing-market case the Master Deck
    describes.

    The tallest peak is always a mode; the rest must clear `prominence` times the tallest peak's height.
    """
    values = np.asarray(probability, dtype=float)
    if values.size < 3:
        return [int(np.argmax(values)) + 1] if values.size else []

    is_peak = np.zeros(values.size, dtype=bool)
    is_peak[1:-1] = (values[1:-1] >= values[:-2]) & (values[1:-1] >= values[2:])
    is_peak[0] = values[0] >= values[1]
    is_peak[-1] = values[-1] >= values[-2]
    candidates = [int(i) for i in np.flatnonzero(is_peak)]
    if not candidates:
        return [int(np.argmax(values)) + 1]

    tallest = int(max(candidates, key=lambda i: values[i]))
    floor = prominence * float(values[tallest])

    kept = [tallest]
    for index in candidates:
        if index == tallest:
            continue
        # The lowest valley between this peak and the nearest higher ground on either side.
        higher_left = [j for j in range(index - 1, -1, -1) if values[j] > values[index]]
        higher_right = [j for j in range(index + 1, values.size) if values[j] > values[index]]

        # No higher ground on either side means this ties the global maximum, which happens on a plateau
        # and on a perfectly flat distribution. Only one such point is a mode: without this guard a flat
        # 25-bin distribution reported 25 modes, since every point is trivially a local maximum and none
        # has a saddle to measure against.
        if not higher_left and not higher_right:
            continue

        saddles = []
        if higher_left:
            saddles.append(float(values[higher_left[0] : index + 1].min()))
        if higher_right:
            saddles.append(float(values[index : higher_right[0] + 1].min()))
        key_saddle = max(saddles)
        if float(values[index]) - key_saddle >= floor:
            kept.append(index)

    return sorted(int(i) + 1 for i in kept)


def dispersion(distribution: np.ndarray, config=None) -> dict[str, Any]:
    """Summarise the shape of a 25-bin distribution.

    The Master Deck reads the *shape* and not only the centre: mass at the cautious end is a risky market,
    at the aggressive end an opportunistic one, and a dispersed or bimodal distribution is a swing market,
    where participants disagree about direction. Merging TAA and SAA can produce exactly that, and the
    author settled on 2026-07-28 that it is a finding rather than an artefact. So it has to be measured.

    Args:
        distribution: The 25 bin masses. Need not be normalised.
        config: A loaded Config, for `regime.shape.mode_prominence` and `regime.shape.lean_bins`. Where it
            is omitted the module fallbacks are used, so this stays callable without configuration.

    Returns:
        The mean bin, the standard deviation in bins, the share of mass in the two extreme quintiles, and
        the number of prominent local maxima, which is what distinguishes a swing market from a wide
        unimodal one.
    """
    prominence = MODE_PROMINENCE
    lean = LEAN_BINS
    if config is not None:
        prominence = float(config.get("regime.shape.mode_prominence", default=MODE_PROMINENCE))
        lean = float(config.get("regime.shape.lean_bins", default=LEAN_BINS))

    values = np.asarray(distribution, dtype=float)
    total = values.sum()
    if total <= 0:
        raise TAAError("cannot summarise an empty distribution")
    probability = values / total
    bins = np.arange(1, values.size + 1, dtype=float)

    mean = float((probability * bins).sum())
    variance = float((probability * (bins - mean) ** 2).sum())

    peak_bins = _prominent_modes(probability, prominence)
    peaks = len(peak_bins)

    fifth = max(1, values.size // 5)
    centre = (values.size + 1) / 2.0
    return {
        "mean_bin": mean,
        "standard_deviation_bins": float(np.sqrt(variance)),
        "cautious_tail": float(probability[:fifth].sum()),
        "aggressive_tail": float(probability[-fifth:].sum()),
        "modes": peaks,
        "mode_bins": peak_bins,
        "shape": (
            "swing, participants disagree on direction"
            if peaks > 1
            else "risky, mass at the cautious end"
            if mean < centre - lean
            else "opportunistic, mass at the aggressive end"
            if mean > centre + lean
            else "balanced"
        ),
    }
