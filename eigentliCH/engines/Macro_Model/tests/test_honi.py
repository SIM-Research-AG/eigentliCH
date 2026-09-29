"""Tests for the Health of Nations Indicator, section 0.6.

Note the direction throughout. Every score this module emits is on the canonical axis, where **5 is
healthiest and 1 least healthy**, matching the current export. The 2022 band table runs the other way
and declares that natively, so the fixtures below are written in the 2022 direction and their expected
scores are the converted values. `to_canonical` is the only place the reflection happens.
"""

import math
from pathlib import Path

import pytest

from macrofield import config as config_module
from macrofield.model.honi import (
    CANONICAL_DIRECTION,
    HIGHER_IS_HEALTHIER,
    LOWER_IS_HEALTHIER,
    SCALE_MAXIMUM,
    SCALE_MINIMUM,
    DimensionScore,
    HoNIError,
    HoNIScore,
    IndicatorBands,
    aggregate_composite,
    capital_saturation_percentage,
    classify_stage,
    load_bands,
    load_indicator_definitions,
    rank_panel,
    rescale_panel_min_max,
    score_dimension,
    score_economy,
    to_canonical,
)

ROOT = Path(__file__).resolve().parent.parent

# A simple negative band: lower raw values are healthier.
NEGATIVE_BANDS = IndicatorBands(
    key="npl",
    name="Non performing loans",
    intervals={1: [(0.0, 2.0)], 2: [(2.0, 5.0)], 3: [(5.0, 10.0)], 4: [(10.0, 15.0)], 5: [(15.0, math.inf)]},
)

# A union band, the inflation shape: an ideal interval with deviation either side worsening the score.
UNION_BANDS = IndicatorBands(
    key="inflation",
    name="Inflation",
    intervals={
        1: [(0.75, 1.25)],
        2: [(0.25, 0.75), (1.25, 2.25)],
        3: [(-0.5, 0.25), (2.25, 3.75)],
        4: [(-1.0, -0.5), (3.75, 7.0)],
        5: [(-math.inf, -1.0), (7.0, math.inf)],
    },
)

DIMENSION_MAP = {
    "financial": {"label": "Financial Economy", "indicators": ["a", "b"]},
    "international": {"label": "International Resilience", "indicators": ["c", "d"]},
    "real": {"label": "Real Economy", "indicators": ["e", "f"]},
}

FLAT_BANDS = {
    key: IndicatorBands(
        key=key,
        name=key,
        intervals={
            1: [(0.0, 1.0)],
            2: [(1.0, 2.0)],
            3: [(2.0, 3.0)],
            4: [(3.0, 4.0)],
            5: [(4.0, math.inf)],
        },
    )
    for key in "abcdef"
}

WEIGHTS = {"financial": 0.4, "international": 0.3, "real": 0.3}

# On the canonical axis 5 is healthiest, so Saturation sits at the bottom and Foundation at the top.
# Mirrors config/defaults.yaml.
STAGES = [
    {"name": "Saturation", "lower": 1.0, "upper": 2.2},
    {"name": "Optimisation", "lower": 2.2, "upper": 3.0},
    {"name": "Build-up", "lower": 3.0, "upper": 3.8},
    {"name": "Foundation", "lower": 3.8, "upper": 5.0},
]


class TestDirectionConversion:
    """The two HoNI vintages use opposite score directions. This is where that is reconciled."""

    @pytest.mark.parametrize(
        "native_level,expected", [(1, 5.0), (2, 4.0), (3, 3.0), (4, 2.0), (5, 1.0)]
    )
    def test_lower_is_healthier_reflects_about_the_midpoint(self, native_level, expected):
        assert to_canonical(native_level, LOWER_IS_HEALTHIER) == expected

    @pytest.mark.parametrize("native_level", [1, 2, 3, 4, 5])
    def test_higher_is_healthier_passes_through(self, native_level):
        assert to_canonical(native_level, HIGHER_IS_HEALTHIER) == float(native_level)

    def test_conversion_is_its_own_inverse(self):
        for level in (1, 2, 3, 4, 5):
            once = to_canonical(level, LOWER_IS_HEALTHIER)
            assert to_canonical(once, LOWER_IS_HEALTHIER) == float(level)

    def test_rejects_an_unknown_direction(self):
        with pytest.raises(HoNIError, match="unknown band direction"):
            to_canonical(1, "sideways")

    def test_canonical_direction_is_higher_is_healthier(self):
        assert CANONICAL_DIRECTION == HIGHER_IS_HEALTHIER

    def test_bands_reject_an_unknown_declared_direction(self):
        with pytest.raises(HoNIError, match="declares direction"):
            IndicatorBands(key="x", name="x", intervals={1: [(0.0, 1.0)]}, native_direction="up")


class TestIndicatorScoring:
    @pytest.mark.parametrize(
        "value,expected", [(0.5, 5.0), (2.0, 5.0), (3.0, 4.0), (7.0, 3.0), (12.0, 2.0), (40.0, 1.0)]
    )
    def test_negative_band_membership(self, value, expected):
        """Low non-performing loans are healthy, so they must score towards 5 on the canonical axis."""
        assert NEGATIVE_BANDS.score(value).score == expected

    @pytest.mark.parametrize(
        "value,expected",
        [(1.0, 5.0), (0.5, 4.0), (1.8, 4.0), (0.0, 3.0), (3.0, 3.0), (-0.8, 2.0), (5.0, 2.0), (-3.0, 1.0), (9.0, 1.0)],
    )
    def test_union_band_scores_both_sides(self, value, expected):
        """A union band must score deviation in either direction, which is the point of it. Inflation
        near the ideal 0.75 to 1.25 scores healthiest, and deviation either way worsens it."""
        assert UNION_BANDS.score(value).score == expected

    def test_a_table_in_the_canonical_direction_is_not_reflected(self):
        already_canonical = IndicatorBands(
            key="npl",
            name="Non performing loans",
            intervals=NEGATIVE_BANDS.intervals,
            native_direction=HIGHER_IS_HEALTHIER,
        )
        assert already_canonical.score(0.5).score == 1.0

    def test_missing_value_is_not_scored(self):
        result = NEGATIVE_BANDS.score(float("nan"))
        assert not result.scored
        assert "missing" in result.notes[0]

    def test_value_outside_every_band_is_not_scored(self):
        """A gap in the bands must withhold a score rather than guess the nearest level."""
        gapped = IndicatorBands(key="g", name="g", intervals={1: [(0.0, 1.0)], 5: [(10.0, 20.0)]})
        result = gapped.score(5.0)
        assert not result.scored
        assert "outside every band" in result.notes[-1]

    def test_overlapping_bands_take_the_healthiest_and_record_it(self):
        """The 2022 workbook contains a real overlap, so this path is exercised in practice. Native
        level 2 is healthier than 3, so the canonical result is 4.0."""
        overlapping = IndicatorBands(
            key="o", name="o", intervals={2: [(8.0, 15.0)], 3: [(10.0, 15.0)]}
        )
        result = overlapping.score(12.0)
        assert result.score == 4.0
        assert any("overlap" in note for note in result.notes)

    def test_extraction_problems_are_carried_onto_the_score(self):
        """A score computed from defective bands must arrive flagged."""
        defective = IndicatorBands(
            key="d",
            name="d",
            intervals={1: [(0.0, 1.0)]},
            problems=("score 4: interval [-1.0, -4.0] is inverted",),
        )
        result = defective.score(0.5)
        assert result.scored
        assert any("inverted" in note for note in result.notes)


class TestDimensionScoring:
    def test_equal_weighted_mean_of_scored_indicators(self):
        scores = {
            "a": FLAT_BANDS["a"].score(0.5),  # native 1, canonical 5
            "b": FLAT_BANDS["b"].score(2.5),  # native 3, canonical 3
        }
        dimension = score_dimension("financial", "Financial", ["a", "b"], scores, 0.5)
        assert dimension.score == pytest.approx(4.0)
        assert dimension.coverage == 1.0

    def test_missing_indicators_are_excluded_not_imputed(self):
        scores = {"a": FLAT_BANDS["a"].score(0.5)}  # native 1, canonical 5
        dimension = score_dimension("financial", "Financial", ["a", "b"], scores, 0.5)
        assert dimension.score == pytest.approx(5.0)
        assert dimension.coverage == 0.5
        assert dimension.missing_indicators == ["b"]

    def test_score_is_withheld_below_the_coverage_floor(self):
        scores = {"a": FLAT_BANDS["a"].score(0.5)}
        dimension = score_dimension("financial", "Financial", ["a", "b", "c", "d"], scores, 0.5)
        assert dimension.score is None
        assert any("below the floor" in note for note in dimension.notes)


class TestCompositeAggregation:
    def test_weighted_mean_with_the_financial_dimension_dominant(self):
        dimensions = {
            "financial": DimensionScore("financial", "F", 4.0, 1.0),
            "international": DimensionScore("international", "I", 2.0, 1.0),
            "real": DimensionScore("real", "R", 2.0, 1.0),
        }
        composite, _ = aggregate_composite(dimensions, WEIGHTS, 0.6)
        assert composite == pytest.approx(0.4 * 4.0 + 0.3 * 2.0 + 0.3 * 2.0)

    def test_weights_are_renormalised_over_available_dimensions(self):
        """A missing dimension must not drag the composite towards a scale endpoint."""
        dimensions = {
            "financial": DimensionScore("financial", "F", 4.0, 1.0),
            "international": DimensionScore("international", "I", 2.0, 1.0),
            "real": DimensionScore("real", "R", None, 0.0),
        }
        composite, notes = aggregate_composite(dimensions, WEIGHTS, 0.6)
        # Renormalised over 0.4 and 0.3, not divided by the full 1.0.
        assert composite == pytest.approx((0.4 * 4.0 + 0.3 * 2.0) / 0.7)
        assert any("renormalised" in note for note in notes)

    def test_composite_withheld_below_the_coverage_floor(self):
        dimensions = {
            "financial": DimensionScore("financial", "F", 4.0, 1.0),
            "international": DimensionScore("international", "I", None, 0.0),
            "real": DimensionScore("real", "R", None, 0.0),
        }
        composite, notes = aggregate_composite(dimensions, WEIGHTS, 0.6)
        assert composite is None
        assert any("withheld" in note for note in notes)


class TestStageClassification:
    @pytest.mark.parametrize(
        "composite,expected",
        [
            (1.0, "Saturation"),
            (2.1, "Saturation"),
            (2.2, "Optimisation"),
            (2.9, "Optimisation"),
            (3.0, "Build-up"),
            (3.7, "Build-up"),
            (3.8, "Foundation"),
            (5.0, "Foundation"),
        ],
    )
    def test_bands_from_config(self, composite, expected):
        assert classify_stage(composite, STAGES) == expected

    def test_healthiest_score_is_the_foundation_stage(self):
        """Direction check: 5 is healthiest, so it must land in Foundation, and 1 in Saturation."""
        assert classify_stage(SCALE_MAXIMUM, STAGES) == "Foundation"
        assert classify_stage(SCALE_MINIMUM, STAGES) == "Saturation"

    def test_loads_the_stages_from_defaults(self):
        stages = config_module.load().get("honi.stages")
        assert [s["name"] for s in stages] == [
            "Saturation",
            "Optimisation",
            "Build-up",
            "Foundation",
        ]
        assert classify_stage(2.5, stages) == "Optimisation"

    def test_config_stages_partition_the_axis(self):
        """The bands must tile 1.0 to 5.0 with no gap and no overlap."""
        stages = config_module.load().get("honi.stages")
        assert stages[0]["lower"] == SCALE_MINIMUM
        assert stages[-1]["upper"] == SCALE_MAXIMUM
        for earlier, later in zip(stages, stages[1:]):
            assert earlier["upper"] == later["lower"]


class TestPanelMinMax:
    def test_maps_the_extremes_onto_the_full_axis(self):
        """Reproduces the current export, where each year has exactly one 1.0 and one 5.0."""
        rescaled = rescale_panel_min_max({"a": 2.0, "b": 3.0, "c": 4.0})
        assert rescaled["a"] == pytest.approx(SCALE_MINIMUM)
        assert rescaled["c"] == pytest.approx(SCALE_MAXIMUM)
        assert rescaled["b"] == pytest.approx(3.0)

    def test_is_not_comparable_across_periods(self):
        """The same economy, unchanged, scores differently when the rest of the panel moves. This is
        the property that makes the rescaled score unusable for a timeline reading."""
        # The United States holds still at 3.0 while Japan deteriorates from 4.0 to 6.0.
        first = rescale_panel_min_max({"us": 3.0, "cn": 2.0, "jp": 4.0})
        second = rescale_panel_min_max({"us": 3.0, "cn": 2.0, "jp": 6.0})
        assert first["us"] == pytest.approx(3.0)
        assert second["us"] == pytest.approx(2.0)
        assert first["us"] != pytest.approx(second["us"])

    def test_one_economy_always_reads_healthiest_even_when_all_are_saturated(self):
        """Every economy at 4.8 on the absolute axis is deep in Saturation, yet one still reads 1.0."""
        rescaled = rescale_panel_min_max({"a": 4.8, "b": 4.9, "c": 5.0})
        assert rescaled["a"] == pytest.approx(SCALE_MINIMUM)

    def test_a_panel_with_no_spread_returns_the_midpoint(self):
        rescaled = rescale_panel_min_max({"a": 3.0, "b": 3.0})
        assert rescaled["a"] == pytest.approx(3.0)
        assert rescaled["b"] == pytest.approx(3.0)

    def test_empty_panel(self):
        assert rescale_panel_min_max({}) == {}


class TestCapitalSaturation:
    def test_percentage_of_gdp(self):
        assert capital_saturation_percentage(90.0, 210.0, 100.0) == pytest.approx(300.0)

    def test_rejects_zero_output(self):
        with pytest.raises(HoNIError):
            capital_saturation_percentage(90.0, 210.0, 0.0)


class TestScoreEconomy:
    def _values(self, value: float) -> dict[str, float]:
        return {key: value for key in "abcdef"}

    def test_end_to_end_absolute_strategy(self):
        result = score_economy(
            economy="us",
            period=2024,
            indicator_values=self._values(3.5),  # native level 4, canonical 2
            bands=FLAT_BANDS,
            dimension_map=DIMENSION_MAP,
            weights=WEIGHTS,
            stages=STAGES,
            capital_saturation=300.0,
        )
        assert result.composite == pytest.approx(2.0)
        assert result.stage == "Saturation"
        assert result.in_balanced_band is True
        assert result.direction == "5 is healthiest, 1 is least healthy"

    def test_a_healthy_economy_lands_in_foundation(self):
        """The opposite end, so the direction is pinned from both sides."""
        result = score_economy(
            economy="vn",
            period=2024,
            indicator_values={key: 0.5 for key in "abcdef"},  # native level 1, canonical 5
            bands=FLAT_BANDS,
            dimension_map=DIMENSION_MAP,
            weights=WEIGHTS,
            stages=STAGES,
        )
        assert result.composite == pytest.approx(5.0)
        assert result.stage == "Foundation"

    def test_stage_withheld_under_panel_min_max(self):
        result = score_economy(
            economy="us",
            period=2024,
            indicator_values=self._values(3.5),
            bands=FLAT_BANDS,
            dimension_map=DIMENSION_MAP,
            weights=WEIGHTS,
            stages=STAGES,
            strategy="panel_min_max",
        )
        assert result.composite is not None
        assert result.stage is None
        assert any("withheld" in note for note in result.notes)

    def test_unconfigured_indicator_is_flagged_not_dropped(self):
        values = self._values(3.5)
        values["unknown"] = 1.0
        result = score_economy(
            economy="us",
            period=2024,
            indicator_values=values,
            bands=FLAT_BANDS,
            dimension_map=DIMENSION_MAP,
            weights=WEIGHTS,
            stages=STAGES,
        )
        # The unknown indicator belongs to no dimension, so it cannot corrupt a sub-index.
        assert result.composite == pytest.approx(2.0)

    def test_out_of_band_saturation_is_reported(self):
        result = score_economy(
            economy="jp",
            period=2024,
            indicator_values=self._values(3.5),
            bands=FLAT_BANDS,
            dimension_map=DIMENSION_MAP,
            weights=WEIGHTS,
            stages=STAGES,
            capital_saturation=420.0,
        )
        assert result.in_balanced_band is False


class TestComparativeRanking:
    def _panel(self) -> dict[str, HoNIScore]:
        return {
            code: HoNIScore(
                economy=code, period=2024, dimensions={}, composite=composite, stage=None
            )
            for code, composite in {"us": 3.9, "cn": 2.8, "jp": 4.4, "de": 3.1}.items()
        }

    def test_ranks_healthiest_first(self):
        """Healthiest first means descending on the canonical axis."""
        ranking = rank_panel(self._panel())
        assert [code for code, _ in ranking.ranked] == ["jp", "us", "de", "cn"]
        assert ranking.rank_of("jp") == 1

    def test_pairwise_comparison_names_the_healthier_economy(self):
        """Brief section 0.6: the HoNI reports pairwise comparisons such as the US against China."""
        comparison = rank_panel(self._panel()).compare("us", "cn")
        assert comparison["healthier"] == "us"
        assert comparison["difference"] == pytest.approx(3.9 - 2.8)

    def test_comparison_of_equal_scores_names_neither(self):
        panel = {
            code: HoNIScore(economy=code, period=2024, dimensions={}, composite=3.0, stage=None)
            for code in ("us", "cn")
        }
        assert rank_panel(panel).compare("us", "cn")["healthier"] is None

    def test_withheld_economies_are_listed_and_cannot_be_compared(self):
        panel = self._panel()
        panel["in"] = HoNIScore(
            economy="in", period=2024, dimensions={}, composite=None, stage=None
        )
        ranking = rank_panel(panel)
        assert ranking.withheld == ["in"]
        with pytest.raises(HoNIError, match="no score"):
            ranking.compare("us", "in")

    def test_panel_min_max_ranking_preserves_the_ordering(self):
        """Rescaling changes the numbers but must not reorder the panel."""
        absolute = rank_panel(self._panel(), strategy="absolute")
        rescaled = rank_panel(self._panel(), strategy="panel_min_max")
        assert [c for c, _ in absolute.ranked] == [c for c, _ in rescaled.ranked]
        # Healthiest first, so the leading entry takes the healthy end of the axis.
        assert rescaled.ranked[0][1] == pytest.approx(SCALE_MAXIMUM)
        assert rescaled.ranked[-1][1] == pytest.approx(SCALE_MINIMUM)

    def test_rejects_a_mixed_period_panel(self):
        panel = self._panel()
        panel["fr"] = HoNIScore(
            economy="fr", period=2023, dimensions={}, composite=3.0, stage=None
        )
        with pytest.raises(HoNIError, match="one period"):
            rank_panel(panel)

    def test_rejects_an_empty_panel(self):
        with pytest.raises(HoNIError, match="empty panel"):
            rank_panel({})


class TestGeneratedConfig:
    def test_band_config_loads_and_carries_provenance(self):
        bands = load_bands(ROOT / "config" / "honi_bands.yaml")
        assert len(bands) == 83
        assert all(isinstance(b, IndicatorBands) for b in bands.values())

    def test_extraction_recorded_the_known_workbook_defects(self):
        """These are real defects in the 2022 workbook. If the extractor stops reporting them, it has
        regressed, so the test pins them."""
        bands = load_bands(ROOT / "config" / "honi_bands.yaml")
        problems = {key: b.problems for key, b in bands.items() if b.problems}
        joined = " ".join(note for notes in problems.values() for note in notes)
        assert "is inverted" in joined
        assert "overlap" in joined

    def test_indicator_definitions_have_three_dimensions_of_five(self):
        definitions = load_indicator_definitions(ROOT / "config" / "honi_indicators.yaml")
        dimensions = definitions["dimensions"]
        assert set(dimensions) == {"financial", "international", "real"}
        for key, entry in dimensions.items():
            assert len(entry["indicators"]) == 5, key
        assert len(definitions["indicators"]) == 15

    def test_every_mapped_indicator_is_defined(self):
        definitions = load_indicator_definitions(ROOT / "config" / "honi_indicators.yaml")
        defined = set(definitions["indicators"])
        for key, entry in definitions["dimensions"].items():
            for indicator in entry["indicators"]:
                assert indicator in defined, f"{indicator} in {key} is not defined"
