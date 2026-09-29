"""Validate the HoNI score direction against the published export.

This exists because the direction is the single assumption in the HoNI module that inverts every
conclusion if wrong, and because the two HoNI vintages state opposite conventions in their headers. It
is therefore established from data rather than from a header, and pinned here.

The export lives on the NAS rather than in this repository, so these tests skip when it is not
reachable. They are validation, not unit tests: they check the implemented convention against real
published output.
"""

from pathlib import Path

import pytest

from macrofield import config as config_module
from macrofield.model.honi import HIGHER_IS_HEALTHIER, classify_stage

EXPORT = Path(
    r"c:\Users\nicol\Desktop\SIM_NAS\Knowledge_Center\Marianne Work Folder"
    r"\LaTex Documents\HoNI\HoNI_Export 11-25.xlsx"
)

pytestmark = pytest.mark.skipif(
    not EXPORT.exists(), reason=f"HoNI export not reachable at {EXPORT}"
)

INDICATOR_COLUMNS = range(2, 17)
GOV_DEBT_COLUMN = 4


@pytest.fixture(scope="module")
def workbook():
    from openpyxl import load_workbook

    return load_workbook(EXPORT, data_only=True, read_only=True)


def rows_of(workbook, sheet):
    return [r for r in workbook[sheet].iter_rows(values_only=True)]


def scores_by_year(workbook, sheet):
    return {r[0]: r for r in rows_of(workbook, sheet) if isinstance(r[0], int)}


def raw_rows(workbook, sheet, column):
    return [
        r
        for r in rows_of(workbook, sheet)
        if r[0] is None and isinstance(r[column - 1], (int, float))
    ]


class TestDirectionEstablishedFromData:
    def test_rising_us_government_debt_scores_towards_the_unhealthy_end(self, workbook):
        """The decisive observation. United States government debt rises from roughly 109 to 122
        percent of GDP between 2019 and 2024 while its Gov_Debt score falls towards 1. On a
        higher-is-healthier axis that is correct. On a lower-is-healthier axis it would mean rising
        debt made the economy healthier."""
        scores = scores_by_year(workbook, "USA")
        raws = raw_rows(workbook, "USA", GOV_DEBT_COLUMN)
        years = sorted(scores)
        assert len(raws) == len(years), "expected one raw row per scored year"

        first_raw, last_raw = raws[-6][GOV_DEBT_COLUMN - 1], raws[-1][GOV_DEBT_COLUMN - 1]
        first_score = scores[years[-6]][GOV_DEBT_COLUMN - 1]
        last_score = scores[years[-1]][GOV_DEBT_COLUMN - 1]

        assert last_raw > first_raw, "United States government debt should have risen"
        assert last_score < first_score, (
            "the score should move towards the unhealthy end as debt rises, which on this axis is "
            "towards 1"
        )

    def test_gov_debt_correlates_negatively_with_score_across_the_panel(self, workbook):
        """Higher government debt must score less healthy in every economy, not only the US."""
        from statistics import correlation

        raws, scores = [], []
        for sheet in workbook.sheetnames:
            if sheet in ("HoNI", "HoNI Score"):
                continue
            by_year = scores_by_year(workbook, sheet)
            raw = raw_rows(workbook, sheet, GOV_DEBT_COLUMN)
            if not by_year or not raw:
                continue
            score = by_year[max(by_year)][GOV_DEBT_COLUMN - 1]
            if isinstance(score, (int, float)):
                raws.append(float(raw[-1][GOV_DEBT_COLUMN - 1]))
                scores.append(float(score))

        assert len(raws) >= 10
        assert correlation(raws, scores) < -0.5, (
            "government debt and its score must move in opposite directions on a "
            "higher-is-healthier axis"
        )

    def test_japan_carries_the_heaviest_debt_and_the_least_healthy_debt_score(self, workbook):
        """Japan's government debt is the highest of the panel, so its Gov_Debt score must sit at or
        near the unhealthy end of the axis."""
        by_year = scores_by_year(workbook, "Japan")
        latest = by_year[max(by_year)][GOV_DEBT_COLUMN - 1]
        assert latest == pytest.approx(1.0, abs=0.25)


class TestPublishedCompositeUnderTheCorrectedDirection:
    def _composites(self, workbook, year):
        rows = rows_of(workbook, "HoNI Score")
        countries = [c for c in rows[0][1:] if c is not None]
        for row in rows[1:]:
            if row[0] == year:
                return {
                    c: row[1 + i]
                    for i, c in enumerate(countries)
                    if isinstance(row[1 + i], (int, float))
                }
        raise AssertionError(f"year {year} not found in the export")

    def test_the_united_states_reads_as_least_healthy_in_the_final_year(self, workbook):
        """The reading that prompted the correction. Under the corrected direction the United States
        at 1.0 is the least healthy of the panel, which is what the framework's thesis of late
        saturation predicts."""
        composites = self._composites(workbook, 2024)
        assert composites["USA"] == pytest.approx(1.0)
        assert min(composites, key=composites.get) == "USA"

    def test_the_united_states_classifies_as_saturation(self, workbook):
        """End to end: the published composite, read on the corrected axis and banded with the
        configured stages, must place the United States in the Saturation stage."""
        composites = self._composites(workbook, 2024)
        stages = config_module.load().get("honi.stages")
        assert classify_stage(float(composites["USA"]), stages) == "Saturation"

    def test_japan_also_classifies_as_saturation(self, workbook):
        composites = self._composites(workbook, 2024)
        stages = config_module.load().get("honi.stages")
        assert classify_stage(float(composites["Japan"]), stages) == "Saturation"

    def test_every_year_carries_exactly_one_extreme_at_each_end(self, workbook):
        """Evidence for the panel min-max rescaling. If this ever stops holding, the export's
        aggregation has changed and honi.aggregation.strategy should be revisited."""
        rows = rows_of(workbook, "HoNI Score")
        countries = [c for c in rows[0][1:] if c is not None]
        years_checked = 0
        for row in rows[1:]:
            if not isinstance(row[0], int):
                continue
            values = [
                row[1 + i] for i in range(len(countries)) if isinstance(row[1 + i], (int, float))
            ]
            if not values:
                continue
            years_checked += 1
            assert sum(1 for v in values if v == pytest.approx(1.0)) == 1
            assert sum(1 for v in values if v == pytest.approx(5.0)) == 1
        assert years_checked >= 20


class TestConfigMatchesTheEstablishedDirection:
    def test_config_declares_higher_is_healthier(self):
        assert config_module.load().get("honi.scale.direction") == HIGHER_IS_HEALTHIER

    def test_saturation_sits_at_the_bottom_of_the_configured_axis(self):
        stages = config_module.load().get("honi.stages")
        assert stages[0]["name"] == "Saturation"
        assert stages[-1]["name"] == "Foundation"
