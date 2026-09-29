"""The Health of Nations Indicator.

Brief section 0.6 and book chapter 12. Capital saturation is total capital over GDP expressed as a
percentage, with a balanced band of 250 to 350 percent. Each economy is scored on three sub-indices,
Financial, International (resilience) and Real, on a 1.0 to 5.0 scale, and a composite is produced.
Economies are grouped into four saturation categories, and the scorer is comparative across
economies.

Three points about the scale and the aggregation, because they determine what a score means.

**Direction.** On the 1 to 5 axis, **5 is healthiest and 1 least healthy**. This is the canonical
direction throughout this module, and it matches the current export dated 2026-04-27 and book section
12.2, whose 0 to 100 axis also runs higher-is-healthier.

The direction changed between HoNI vintages, and the headers cannot be trusted over the data. The 2022
methodology workbook states "Key: 1 most healthy; 5 least healthy" and its bands bear that out, but
the current export runs the other way. Established from the export's own values:

- USA `Gov_Debt` raw rises from 1.0875 to 1.2232 of GDP between 2019 and 2024 while its score falls
  from 1.844 to 1.000. Across the panel, `corr(raw, score) = -0.888`.
- Japan, which carries the highest government debt of the panel, sits at `Gov_Debt = 1.000` throughout.
- 13 of the 15 indicators align: higher debt, larger financialised market capitalisation and higher
  external exposure push towards 1, while higher labour-force participation (`corr +0.963`), GDP
  growth per capita (`+0.940`) and institutional quality (`+0.996`) push towards 5.

Under this direction the export's USA composite of 1.000 in 2024 reads as least healthy of the 16
economies, which is what the framework's thesis of United States late saturation predicts.

A band table declares its own native direction and this module converts into the canonical one, so
the two conventions are never mixed silently. Every score emitted carries the direction with it, so a
consumer cannot read it the wrong way round.

**Indicator set.** The current model uses 15 indicators in three groups of five, from the HoNI export
dated 2026-04-27. That supersedes the 83-indicator methodology workbook dated 2022-01-16. The older
workbook is retained only as a band reference, and its extraction reported real defects in it (an
inverted interval, an overlap between two score levels, and four label-versus-cell contradictions),
which is a further reason not to treat it as current.

**Aggregation.** Two strategies, selected in config, because the sources disagree and the choice
changes what the number means:

- `absolute` weights the three sub-indices on the fixed 1 to 5 axis. The score means the same thing
  in every year and for every panel, which is what a timeline reading and the four-stage taxonomy
  both require. This is the default.
- `panel_min_max` reproduces the current export, which rescales each year's panel so that the
  healthiest economy scores exactly 1.0 and the least healthy exactly 5.0. It was identified from the
  export directly: every one of its 21 years contains exactly one 1.0 and exactly one 5.0. It gives a
  clean relative ranking, but the resulting score is not comparable across years, it moves when the
  panel membership changes, and one economy always reads as perfectly healthy even in a year when
  every economy in the panel is saturated. The four-stage taxonomy is therefore not applied to it,
  and this module refuses to do so rather than emitting a meaningless category.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

#: The scale endpoints. Fixed by the source convention, not configurable, because the four-stage
#: bands and the band tables are both expressed against it.
SCALE_MINIMUM = 1.0
SCALE_MAXIMUM = 5.0

#: Score levels a band table assigns, as integers. Which end is healthy depends on the table's
#: declared native direction, not on this ordering.
SCORE_LEVELS = (1, 2, 3, 4, 5)

#: The canonical direction of every score this module emits.
CANONICAL_DIRECTION = "higher_is_healthier"

DIRECTION_NOTE = "5 is healthiest, 1 is least healthy"

#: Direction a band table may declare for its own score levels.
LOWER_IS_HEALTHIER = "lower_is_healthier"
HIGHER_IS_HEALTHIER = "higher_is_healthier"
VALID_DIRECTIONS = (LOWER_IS_HEALTHIER, HIGHER_IS_HEALTHIER)


def to_canonical(level: float, native_direction: str) -> float:
    """Convert a band-table score level into the canonical higher-is-healthier direction.

    A table whose level 1 means healthiest is reflected about the midpoint of the axis, so level 1
    becomes 5 and level 5 becomes 1. A table already in the canonical direction passes through.

    This function is the only place the reflection happens, so a convention mismatch cannot leak in
    through an aggregation path that forgot to convert.
    """
    if native_direction == HIGHER_IS_HEALTHIER:
        return float(level)
    if native_direction == LOWER_IS_HEALTHIER:
        return float(SCALE_MINIMUM + SCALE_MAXIMUM - level)
    raise HoNIError(
        f"unknown band direction {native_direction!r}, expected one of {VALID_DIRECTIONS}"
    )


class HoNIError(ValueError):
    """Raised when a HoNI input or configuration is unusable."""


def _parse_boundary(value: Any) -> float:
    """Return a band boundary, mapping the config's infinity strings to float infinities."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().lower()
    if text in {"inf", "+inf", "∞", "+∞"}:
        return math.inf
    if text in {"-inf", "-∞"}:
        return -math.inf
    try:
        return float(text)
    except ValueError as error:
        raise HoNIError(f"cannot read band boundary {value!r}") from error


@dataclass(frozen=True)
class IndicatorBands:
    """The five score bands of a single indicator.

    Attributes:
        key: The indicator key.
        name: The indicator's name as published.
        intervals: Score level to the list of closed intervals that level covers. A simple band has
            one interval per level; a union band has two.
        native_direction: Which end of this table's own score levels means healthiest. The 2022
            methodology workbook is `lower_is_healthier`; the current export is
            `higher_is_healthier`. Scores are converted into the canonical direction on the way out.
        problems: Integrity problems recorded when the bands were extracted. Carried through so a
            score computed from defective bands can be flagged rather than trusted silently.
    """

    key: str
    name: str
    intervals: Mapping[int, Sequence[tuple[float, float]]]
    native_direction: str = LOWER_IS_HEALTHIER
    problems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.native_direction not in VALID_DIRECTIONS:
            raise HoNIError(
                f"indicator {self.key!r} declares direction {self.native_direction!r}, expected one "
                f"of {VALID_DIRECTIONS}"
            )

    @classmethod
    def from_config(
        cls, key: str, entry: Mapping[str, Any], native_direction: str = LOWER_IS_HEALTHIER
    ) -> "IndicatorBands":
        """Build from an entry of config/honi_bands.yaml.

        The direction comes from the band file's provenance block rather than being assumed, because
        the two HoNI vintages disagree about it.
        """
        intervals: dict[int, list[tuple[float, float]]] = {}
        for level, raw in (entry.get("bands") or {}).items():
            parsed = [
                (_parse_boundary(interval[0]), _parse_boundary(interval[1])) for interval in raw
            ]
            intervals[int(level)] = parsed
        return cls(
            key=key,
            name=str(entry.get("name", key)),
            intervals=intervals,
            native_direction=native_direction,
            problems=tuple(entry.get("problems") or ()),
        )

    def score(self, value: float) -> "IndicatorScore":
        """Score a raw value by interval membership.

        Membership is used rather than a reimplementation of the workbook's IFS formula chains. The
        HoNI manual states those chains must be edited by hand whenever a band changes direction or
        moves position, which makes them a derived artefact that can fall out of step with the bands
        themselves. Membership needs no direction inference and handles the positive, negative and
        every union variant uniformly.

        The returned score is in the canonical higher-is-healthier direction, converted from this
        table's native direction.

        Where a value falls in more than one level's intervals, the healthiest matching level wins
        and the ambiguity is recorded. Where it falls in none, no score is returned and the reason is
        recorded. Neither case is silently resolved.
        """
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return IndicatorScore(self.key, self.name, None, None, ("value is missing",))

        matches = [
            level
            for level in SCORE_LEVELS
            if any(lo <= value <= hi for lo, hi in self.intervals.get(level, ()))
        ]
        notes = list(self.problems)

        if not matches:
            covered = [
                f"{level}: {[(lo, hi) for lo, hi in self.intervals.get(level, ())]}"
                for level in SCORE_LEVELS
                if self.intervals.get(level)
            ]
            notes.append(
                f"value {value} falls outside every band, so it cannot be scored. Bands are "
                + "; ".join(covered)
            )
            return IndicatorScore(self.key, self.name, None, float(value), tuple(notes))

        canonical = [to_canonical(level, self.native_direction) for level in matches]
        # Healthiest wins, which on the canonical axis is the highest value.
        chosen = max(canonical)

        if len(matches) > 1:
            notes.append(
                f"value {value} falls in bands for native score levels {matches}; the healthiest was "
                f"used, giving {chosen} on the canonical axis where 5 is healthiest. The bands "
                f"overlap and should be corrected at source."
            )

        return IndicatorScore(self.key, self.name, float(chosen), float(value), tuple(notes))


@dataclass(frozen=True)
class IndicatorScore:
    """The score of one indicator for one economy in one period."""

    key: str
    name: str
    score: float | None
    raw_value: float | None
    notes: tuple[str, ...] = ()

    @property
    def scored(self) -> bool:
        """Whether a usable score was produced."""
        return self.score is not None


@dataclass
class DimensionScore:
    """One sub-index for one economy in one period.

    Attributes:
        key: The dimension key, one of financial, international, real.
        label: The dimension's published label.
        score: The dimension score on the 1 to 5 axis, or None where coverage fell below the floor.
        coverage: Share of the dimension's indicators that produced a score.
        scored_indicators: The indicators that contributed.
        missing_indicators: The indicators that did not.
        notes: Coverage and integrity notes.
    """

    key: str
    label: str
    score: float | None
    coverage: float
    scored_indicators: list[str] = field(default_factory=list)
    missing_indicators: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class HoNIScore:
    """The full HoNI reading for one economy in one period.

    Attributes:
        economy: The economy code.
        period: The period, normally a year.
        dimensions: The three sub-index scores, keyed by dimension.
        composite: The composite on the 1 to 5 axis, or None where coverage fell below the floor.
        stage: The four-stage category, or None where the composite is absent or the aggregation
            strategy makes the category meaningless.
        capital_saturation: Total capital over GDP as a percentage, where supplied.
        in_balanced_band: Whether capital saturation sits inside the 250 to 350 percent band.
        direction: The scale direction, carried so a consumer cannot misread the number.
        strategy: The aggregation strategy used.
        notes: Anything a reader must know to interpret the score.
    """

    economy: str
    period: Any
    dimensions: dict[str, DimensionScore]
    composite: float | None
    stage: str | None
    capital_saturation: float | None = None
    in_balanced_band: bool | None = None
    direction: str = DIRECTION_NOTE
    strategy: str = "absolute"
    notes: list[str] = field(default_factory=list)


def load_bands(path: Path) -> dict[str, IndicatorBands]:
    """Load the extracted band table produced by tools/extract_honi_bands.py.

    The table's native score direction is read from its provenance block. It is required rather than
    defaulted, because the two HoNI vintages use opposite directions and silently guessing would
    invert every score.
    """
    if not path.exists():
        raise HoNIError(
            f"band configuration not found at {path}. Generate it with "
            f"tools/extract_honi_bands.py."
        )
    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    provenance = document.get("provenance") or {}
    direction = provenance.get("scale_direction")
    if direction is None:
        raise HoNIError(
            f"{path} does not declare provenance.scale_direction. The 2022 methodology workbook and "
            f"the current export use opposite score directions, so the direction cannot be assumed. "
            f"Re-run tools/extract_honi_bands.py to regenerate the file."
        )
    if direction not in VALID_DIRECTIONS:
        raise HoNIError(
            f"{path} declares scale_direction {direction!r}, expected one of {VALID_DIRECTIONS}"
        )

    return {
        key: IndicatorBands.from_config(key, entry, native_direction=direction)
        for key, entry in (document.get("indicators") or {}).items()
    }


def load_indicator_definitions(path: Path) -> dict[str, Any]:
    """Load config/honi_indicators.yaml, the current indicator set and dimension mapping."""
    if not path.exists():
        raise HoNIError(f"indicator configuration not found at {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def score_dimension(
    key: str,
    label: str,
    indicator_keys: Iterable[str],
    scores: Mapping[str, IndicatorScore],
    coverage_floor: float,
) -> DimensionScore:
    """Aggregate an indicator group into a sub-index on the 1 to 5 axis.

    An equal-weighted mean of the indicators that scored. Indicators that did not score are excluded
    from the mean rather than imputed, and the coverage is reported so a thin dimension is visible.
    Where coverage falls below the floor the score is withheld: a sub-index computed from one
    indicator out of five is worse than no sub-index, because it looks like the others.
    """
    keys = list(indicator_keys)
    contributed = [k for k in keys if k in scores and scores[k].scored]
    missing = [k for k in keys if k not in contributed]
    coverage = len(contributed) / len(keys) if keys else 0.0

    notes: list[str] = []
    for k in contributed:
        notes.extend(f"{k}: {note}" for note in scores[k].notes)

    if not keys:
        return DimensionScore(key, label, None, 0.0, [], missing, ["dimension has no indicators"])

    if coverage < coverage_floor:
        notes.append(
            f"coverage {coverage:.0%} is below the floor of {coverage_floor:.0%}, so the score is "
            f"withheld. Missing: {', '.join(missing) or 'none'}."
        )
        return DimensionScore(key, label, None, coverage, contributed, missing, notes)

    value = sum(float(scores[k].score) for k in contributed) / len(contributed)
    if missing:
        notes.append(
            f"computed from {len(contributed)} of {len(keys)} indicators. Missing: "
            f"{', '.join(missing)}."
        )
    return DimensionScore(key, label, value, coverage, contributed, missing, notes)


def classify_stage(composite: float, stages: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the four-stage category for a composite score on the 1 to 5 axis.

    Bands come from config. Book section 12.3 calls the ranges guidelines rather than sharp
    boundaries, so the bands are inclusive of the lower bound and the final band absorbs the top.
    """
    for index, stage in enumerate(stages):
        lower, upper = float(stage["lower"]), float(stage["upper"])
        last = index == len(stages) - 1
        if lower <= composite < upper or (last and composite <= upper):
            return str(stage["name"])
    return None


def aggregate_composite(
    dimensions: Mapping[str, DimensionScore],
    weights: Mapping[str, float],
    coverage_floor: float,
) -> tuple[float | None, list[str]]:
    """Combine the three sub-indices into a composite on the 1 to 5 axis.

    Weights are renormalised over the dimensions that produced a score, so a missing dimension does
    not silently drag the composite towards a scale endpoint. Where too few dimensions scored, the
    composite is withheld.

    Returns:
        The composite and any notes.
    """
    available = {k: d for k, d in dimensions.items() if d.score is not None}
    notes: list[str] = []

    if not dimensions:
        return None, ["no dimensions were supplied"]

    coverage = len(available) / len(dimensions)
    if coverage < coverage_floor:
        return None, [
            f"only {len(available)} of {len(dimensions)} dimensions scored, which is below the "
            f"composite coverage floor of {coverage_floor:.0%}, so the composite is withheld"
        ]

    total_weight = sum(float(weights.get(k, 0.0)) for k in available)
    if total_weight <= 0.0:
        return None, ["the available dimensions carry no weight, so the composite is undefined"]

    composite = sum(float(weights.get(k, 0.0)) * float(d.score) for k, d in available.items())
    composite /= total_weight

    if len(available) < len(dimensions):
        withheld = sorted(set(dimensions) - set(available))
        notes.append(
            f"composite computed from {len(available)} of {len(dimensions)} dimensions, with weights "
            f"renormalised. Withheld: {', '.join(withheld)}."
        )
    return composite, notes


def rescale_panel_min_max(values: Mapping[str, float]) -> dict[str, float]:
    """Rescale a panel of composites onto the full 1 to 5 axis, as the current export does.

    Within each period the healthiest economy takes exactly 1.0 and the least healthy exactly 5.0.

    This reproduces the published export, and it is offered because that is what downstream HoNI
    consumers currently expect. Its properties should be understood before it is relied upon:

    - The result is a relative ranking, so it is not comparable across periods.
    - It moves when the panel membership changes, without any economy having changed.
    - One economy always reads as perfectly healthy, even in a period when every economy in the
      panel is saturated.

    Where every economy has the same score the panel carries no spread, and the midpoint is returned
    for all of them rather than an arbitrary assignment of the endpoints.
    """
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if math.isclose(lo, hi):
        midpoint = (SCALE_MINIMUM + SCALE_MAXIMUM) / 2.0
        return {economy: midpoint for economy in values}
    span = hi - lo
    return {
        economy: SCALE_MINIMUM + (SCALE_MAXIMUM - SCALE_MINIMUM) * (value - lo) / span
        for economy, value in values.items()
    }


def capital_saturation_percentage(
    real_capital: float, financial_capital: float, output: float
) -> float:
    """Return total capital over GDP as a percentage, brief section 0.6."""
    if output <= 0.0:
        raise HoNIError(f"capital saturation is undefined at Y = {output}")
    return 100.0 * (real_capital + financial_capital) / output


def score_economy(
    economy: str,
    period: Any,
    indicator_values: Mapping[str, float],
    bands: Mapping[str, IndicatorBands],
    dimension_map: Mapping[str, Mapping[str, Any]],
    weights: Mapping[str, float],
    stages: Sequence[Mapping[str, Any]],
    dimension_coverage_floor: float = 0.5,
    composite_coverage_floor: float = 0.6,
    strategy: str = "absolute",
    capital_saturation: float | None = None,
    balanced_band: tuple[float, float] = (250.0, 350.0),
) -> HoNIScore:
    """Score one economy in one period.

    Args:
        economy: The economy code.
        period: The period, normally a year.
        indicator_values: Raw indicator values, keyed by indicator key.
        bands: The band table, from load_bands.
        dimension_map: The dimension definitions from config/honi_indicators.yaml.
        weights: Dimension weights.
        stages: The four-stage bands from config.
        dimension_coverage_floor: Minimum indicator coverage for a dimension score.
        composite_coverage_floor: Minimum dimension coverage for the composite.
        strategy: The aggregation strategy. Under `panel_min_max` the composite returned here is the
            unscaled absolute value, and rescale_panel_min_max must be applied across the panel
            afterwards; the stage is withheld because it is not meaningful on a rescaled axis.
        capital_saturation: Total capital over GDP as a percentage, where available.
        balanced_band: The balanced band in percentage points.

    Returns:
        The HoNI reading.
    """
    scores: dict[str, IndicatorScore] = {}
    for key, value in indicator_values.items():
        if key in bands:
            scores[key] = bands[key].score(value)
        else:
            scores[key] = IndicatorScore(
                key, key, None, value, (f"no bands are configured for indicator {key!r}",)
            )

    dimensions = {
        key: score_dimension(
            key=key,
            label=str(definition.get("label", key)),
            indicator_keys=definition.get("indicators", ()),
            scores=scores,
            coverage_floor=dimension_coverage_floor,
        )
        for key, definition in dimension_map.items()
    }

    composite, notes = aggregate_composite(dimensions, weights, composite_coverage_floor)

    stage: str | None = None
    if composite is not None:
        if strategy == "absolute":
            stage = classify_stage(composite, stages)
        else:
            notes.append(
                f"the four-stage category is withheld under the {strategy!r} aggregation, because a "
                f"panel-rescaled score has no absolute meaning to band against"
            )

    in_band: bool | None = None
    if capital_saturation is not None:
        in_band = balanced_band[0] <= capital_saturation <= balanced_band[1]

    return HoNIScore(
        economy=economy,
        period=period,
        dimensions=dimensions,
        composite=composite,
        stage=stage,
        capital_saturation=capital_saturation,
        in_balanced_band=in_band,
        strategy=strategy,
        notes=notes,
    )


@dataclass
class ComparativeRanking:
    """A comparative ranking across economies for one period.

    Brief section 0.6 requires the scorer to be comparative, and the HoNI reports pairwise
    comparisons such as the United States against China.
    """

    period: Any
    ranked: list[tuple[str, float]]
    strategy: str
    direction: str = DIRECTION_NOTE
    withheld: list[str] = field(default_factory=list)

    def rank_of(self, economy: str) -> int | None:
        """Return the one-based rank of an economy, healthiest first, or None if withheld."""
        for index, (code, _) in enumerate(self.ranked, start=1):
            if code == economy:
                return index
        return None

    def compare(self, first: str, second: str) -> dict[str, Any]:
        """Return a pairwise comparison of two economies."""
        scores = dict(self.ranked)
        for economy in (first, second):
            if economy not in scores:
                raise HoNIError(
                    f"{economy!r} has no score for period {self.period}, so it cannot be compared. "
                    f"Withheld economies: {', '.join(self.withheld) or 'none'}."
                )
        gap = scores[first] - scores[second]
        return {
            "period": self.period,
            "first": first,
            "second": second,
            "first_score": scores[first],
            "second_score": scores[second],
            "difference": gap,
            # On the canonical axis a higher score is healthier, so a positive difference favours the
            # first economy.
            "healthier": first if gap > 0 else (second if gap < 0 else None),
            "first_rank": self.rank_of(first),
            "second_rank": self.rank_of(second),
            "direction": self.direction,
        }


def rank_panel(
    scores: Mapping[str, HoNIScore], strategy: str = "absolute"
) -> ComparativeRanking:
    """Rank a panel of economies for one period, healthiest first.

    Under `panel_min_max` the composites are rescaled across the panel first, which is what the
    current export publishes.
    """
    if not scores:
        raise HoNIError("cannot rank an empty panel")
    periods = {s.period for s in scores.values()}
    if len(periods) != 1:
        raise HoNIError(f"a ranking covers one period, got {sorted(periods)}")
    period = periods.pop()

    available = {code: s.composite for code, s in scores.items() if s.composite is not None}
    withheld = sorted(set(scores) - set(available))

    if strategy == "panel_min_max":
        available = rescale_panel_min_max(available)

    # Healthiest first, which on the canonical axis means descending.
    ranked = sorted(available.items(), key=lambda item: item[1], reverse=True)
    return ComparativeRanking(
        period=period, ranked=ranked, strategy=strategy, withheld=withheld
    )
