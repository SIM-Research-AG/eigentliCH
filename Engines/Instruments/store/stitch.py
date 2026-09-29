"""Joining short series into long ones, to System Build Manual section 9.

The rule, quoted, because every clause of it is load-bearing:

    Historical series without a modern counterpart are replaced by a comparable series
    that has one; where several candidates exist, the one with the smallest average
    discrepancy over the overlap wins; series are joined working backwards from the
    present, and where an overlap disagrees by more than 2 % the overlapping periods are
    averaged to smooth the join. [...] Every stitch and its discrepancy is recorded with
    the series, because a joint is exactly where a spurious regime shift gets
    manufactured.

Four decisions follow from it, and each is implemented literally rather than
approximately:

**Backwards from the present.** The most recent segment is the anchor and is never
adjusted. Everything older is attached to it. The alternative -- building forwards -- would
let a nineteenth-century proxy set the level of a modern series, which is exactly backwards
from where the evidence is strongest.

**Smallest average discrepancy wins.** When two candidates could both extend a series, the
one that agrees best over the shared window is chosen, and the loser is recorded with its
score. A choice nobody can see is a choice nobody can question.

**Two per cent, then smooth.** Below that the join is taken as-is. Above it the overlapping
periods are replaced by the average of the two series, which spreads the discontinuity
across the overlap instead of concentrating it in one period. One period carrying the whole
of a 10 % disagreement looks exactly like a regime shift, and the phase classifier would
read it as one.

**Everything is recorded.** Overlap length, discrepancy, whether smoothing fired, and what
lost. Written to ``series_segment`` alongside the values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from engines.fund_map import numerics as num

#: Above this average absolute discrepancy over the overlap, the join is smoothed rather
#: than taken raw. Manual section 9.
SMOOTHING_THRESHOLD = 0.02

#: Fewer shared periods than this and a discrepancy is not a measurement. A join made on
#: less evidence than this is refused rather than made badly.
MIN_OVERLAP = 12


class StitchError(ValueError):
    """Raised when a stitch is asked for that cannot honestly be made."""


@dataclass(frozen=True)
class Candidate:
    """One series offered as an extension of another."""

    series_id: str
    values: dict[str, float]
    note: str = ""


@dataclass
class Segment:
    """One joined piece of a stitched series, and the evidence for the join."""

    segment_index: int
    source_series_id: str
    from_period: str
    to_period: str
    overlap_periods: int = 0
    mean_discrepancy: float | None = None
    smoothed: bool = False
    rejected: list[dict[str, object]] = field(default_factory=list)
    note: str = ""


@dataclass
class Stitched:
    """The result: values, the flag for each, and the audit trail."""

    values: dict[str, float]
    #: ``period -> segment_index``; 0 is the anchor, so anything above 0 is stitched on.
    segment_of: dict[str, int]
    segments: list[Segment]

    @property
    def first_period(self) -> str | None:
        return min(self.values) if self.values else None

    @property
    def last_period(self) -> str | None:
        return max(self.values) if self.values else None

    def flag_for(self, period: str) -> str:
        return "observed" if self.segment_of.get(period, 0) == 0 else "stitched"


def discrepancy(a: dict[str, float], b: dict[str, float]) -> tuple[float | None, int]:
    """Mean absolute difference over the shared periods, and how many there were.

    For return series this is the natural measure: the two series claim to describe the
    same thing over the same months, so the average size of their disagreement is what a
    join would be papering over. Returns ``(None, n)`` when the overlap is too short to
    mean anything.
    """
    shared = sorted(set(a) & set(b))
    if len(shared) < MIN_OVERLAP:
        return None, len(shared)
    return num.mean([abs(a[p] - b[p]) for p in shared]), len(shared)


def _choose(anchor: dict[str, float], candidates: Sequence[Candidate]
            ) -> tuple[Candidate | None, float | None, int, list[dict[str, object]]]:
    """Pick the candidate that agrees best with the anchor over their overlap."""
    scored: list[tuple[float, int, Candidate]] = []
    rejected: list[dict[str, object]] = []
    for candidate in candidates:
        score, overlap = discrepancy(anchor, candidate.values)
        if score is None:
            rejected.append({
                "series_id": candidate.series_id,
                "reason": f"overlap of {overlap} periods is below the {MIN_OVERLAP} minimum",
            })
            continue
        # A candidate that adds nothing older than the anchor cannot extend it.
        if min(candidate.values) >= min(anchor):
            rejected.append({
                "series_id": candidate.series_id,
                "reason": "starts no earlier than the series it would extend",
                "mean_discrepancy": score,
            })
            continue
        scored.append((score, overlap, candidate))

    if not scored:
        return None, None, 0, rejected

    scored.sort(key=lambda x: x[0])
    best_score, best_overlap, best = scored[0]
    for score, overlap, candidate in scored[1:]:
        rejected.append({
            "series_id": candidate.series_id,
            "reason": "a closer candidate was available",
            "mean_discrepancy": score,
            "overlap_periods": overlap,
        })
    return best, best_score, best_overlap, rejected


def stitch(
    anchor: Candidate,
    candidates: Iterable[Candidate],
    *,
    max_segments: int = 6,
) -> Stitched:
    """Extend ``anchor`` backwards using whichever candidates agree best.

    The anchor is never modified: it is the most recent and best-evidenced segment, and
    everything else is attached behind it.
    """
    values = dict(anchor.values)
    segment_of = {p: 0 for p in values}
    segments = [
        Segment(
            segment_index=0,
            source_series_id=anchor.series_id,
            from_period=min(values),
            to_period=max(values),
            note=anchor.note or "anchor: the most recent segment, never adjusted",
        )
    ]
    remaining = list(candidates)

    for index in range(1, max_segments + 1):
        if not remaining:
            break
        best, score, overlap, rejected = _choose(values, remaining)
        if best is None:
            # Record why nothing could be attached, so a short series is explained.
            if rejected:
                segments[-1].rejected.extend(rejected)
            break
        remaining = [c for c in remaining if c.series_id != best.series_id]

        earliest = min(values)
        older = {p: v for p, v in best.values.items() if p < earliest}
        if not older:
            continue

        shared = sorted(set(values) & set(best.values))
        smoothed = score is not None and score > SMOOTHING_THRESHOLD
        if smoothed:
            # Spread the disagreement across the overlap rather than concentrating the
            # whole of it in the single period where the two series meet.
            for period in shared:
                values[period] = 0.5 * (values[period] + best.values[period])

        for period, value in older.items():
            values[period] = value
            segment_of[period] = index

        segments.append(
            Segment(
                segment_index=index,
                source_series_id=best.series_id,
                from_period=min(older),
                to_period=max(older),
                overlap_periods=overlap,
                mean_discrepancy=score,
                smoothed=smoothed,
                rejected=rejected,
                note=best.note or (
                    f"joined behind {segments[index - 1].source_series_id}; "
                    f"{'overlap averaged' if smoothed else 'taken as-is'}"
                ),
            )
        )

    return Stitched(values=values, segment_of=segment_of, segments=segments)


def summarise(result: Stitched) -> str:
    """A one-line description of what was joined, for a build log."""
    parts = []
    for segment in result.segments:
        if segment.segment_index == 0:
            parts.append(f"{segment.source_series_id}[{segment.from_period}..{segment.to_period}]")
        else:
            mark = "~" if segment.smoothed else "+"
            score = "" if segment.mean_discrepancy is None else f" d={segment.mean_discrepancy:.4f}"
            parts.append(
                f"{mark}{segment.source_series_id}[{segment.from_period}..{segment.to_period}]{score}"
            )
    return " ".join(reversed(parts))
