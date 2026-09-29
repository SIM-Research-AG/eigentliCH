"""Tests for the HoNI export reader, phase 7 of the battle plan.

The export lives on the NAS, so every test that needs it skips when it is unreachable, exactly as
tests/test_honi_export_direction.py already does. The column-map guard is the one worth reading: a silent
mismatch between the recorded map and the workbook's headers would attribute one indicator's scores to
another, which is the worst failure this reader can have.
"""

import pytest

from macrofield import config as config_module
from macrofield.data.honi_export import (
    HoNIExportError,
    load_export,
    locate_export,
    score_from_export,
    sheet_for_economy,
)


def available() -> bool:
    try:
        locate_export()
        return True
    except HoNIExportError:
        return False


pytestmark = pytest.mark.skipif(not available(), reason="the HoNI export is not reachable")


@pytest.fixture(scope="module")
def settings():
    return config_module.load()


@pytest.fixture(scope="module")
def export(settings):
    return load_export(settings)


class TestLocate:
    def test_it_finds_the_export(self):
        assert locate_export().exists()

    def test_a_missing_export_names_every_path_tried(self):
        from pathlib import Path

        with pytest.raises(HoNIExportError, match="Paths tried"):
            locate_export((Path("nowhere/a.xlsx"), Path("nowhere/b.xlsx")))


class TestExportShape:
    def test_the_panel_is_the_sixteen_economies_recorded_in_config(self, export, settings):
        from pathlib import Path

        from macrofield.model.honi import load_indicator_definitions

        document = load_indicator_definitions(Path(settings.get("honi.indicators_config")))
        recorded = set(document["provenance"]["panel_countries"])
        assert set(export.economies) == recorded

    def test_every_economy_carries_the_full_year_range(self, export, settings):
        from pathlib import Path

        from macrofield.model.honi import load_indicator_definitions

        document = load_indicator_definitions(Path(settings.get("honi.indicators_config")))
        first, last = document["provenance"]["panel_years"]
        for name, reading in export.economies.items():
            assert reading.years[0] == first, name
            assert reading.years[-1] == last, name

    def test_all_fifteen_indicators_are_read(self, export):
        for name, reading in export.economies.items():
            populated = [k for k, series in reading.scores.items() if series]
            assert len(populated) == 15, f"{name} has {len(populated)} populated indicators"

    def test_the_raw_block_beneath_the_scores_is_read(self, export):
        """The export carries raw values under the scores. They are read for the record, not re-scored."""
        reading = export.for_sheet("USA")
        assert any(series for series in reading.raw.values())

    def test_scores_sit_on_the_one_to_five_axis(self, export):
        for name, reading in export.economies.items():
            for key, series in reading.scores.items():
                for year, value in series.items():
                    assert 1.0 <= value <= 5.0, f"{name} {key} {year} is {value}"

    def test_the_reader_says_that_the_scores_are_the_publishers(self, export):
        assert any("export's own" in note for note in export.notes)


class TestColumnMapGuard:
    def test_a_column_map_mismatch_is_refused(self, settings, tmp_path, monkeypatch):
        """The guard that matters. A moved column must fail loudly, not silently mislabel.

        The config is edited rather than the workbook, since the config is the thing that would be wrong.
        """
        from pathlib import Path

        import yaml

        from macrofield.model.honi import load_indicator_definitions

        source = Path(settings.get("honi.indicators_config"))
        document = load_indicator_definitions(source)
        # Swap two indicators' columns, which is exactly the failure the guard exists for.
        document["indicators"]["gov_debt"]["export_column"] = 5
        document["indicators"]["real_10y"]["export_column"] = 4

        broken = tmp_path / "honi_indicators.yaml"
        broken.write_text(yaml.safe_dump(document), encoding="utf-8")

        class Patched:
            def get(self, key, default=None):
                if key == "honi.indicators_config":
                    return str(broken)
                return settings.get(key, default=default) if default is not None else settings.get(key)

        with pytest.raises(HoNIExportError, match="does not match the recorded column map"):
            load_export(Patched())


class TestSheetMapping:
    @pytest.mark.parametrize(
        "code,sheet",
        [("us", "USA"), ("cn", "China"), ("jp", "Japan"), ("de", "Germany"),
         ("gb", "UK"), ("in", "India"), ("eurozone", "EU")],
    )
    def test_each_economy_maps_to_its_sheet(self, settings, code, sheet):
        assert sheet_for_economy(settings, code) == sheet

    def test_france_is_absent_rather_than_substituted(self, settings):
        """The export's panel has no France. Substituting the euro area would be invisible to a reader."""
        assert sheet_for_economy(settings, "fr") is None

    def test_scoring_an_absent_economy_explains_itself(self, settings, export):
        with pytest.raises(HoNIExportError, match="does not include"):
            score_from_export(settings, "fr", export=export)


class TestScoring:
    def test_the_composite_lands_on_the_axis_with_a_stage(self, settings, export):
        for code in ("us", "cn", "jp", "de", "gb", "in", "eurozone"):
            score = score_from_export(settings, code, export=export)
            assert score.composite is not None, code
            assert 1.0 <= score.composite <= 5.0, code
            assert score.stage, code

    def test_every_dimension_has_full_coverage_on_this_export(self, settings, export):
        score = score_from_export(settings, "us", export=export)
        for key, dimension in score.dimensions.items():
            assert dimension.coverage == pytest.approx(1.0), key
            assert dimension.score is not None, key

    def test_the_latest_year_is_used_by_default(self, settings, export):
        assert score_from_export(settings, "us", export=export).period == 2024

    def test_an_earlier_year_can_be_asked_for(self, settings, export):
        assert score_from_export(settings, "us", export=export, period=2010).period == 2010

    def test_the_united_states_reads_as_least_healthy_of_the_panel(self, settings, export):
        """The framework's own thesis, and the check that the direction convention survived the wiring.

        MODEL_SPEC section 4 records that under the correct direction the United States reads as least
        healthy. If the direction were inverted this would fail, which is why it is asserted here rather
        than left to the direction test on the raw export.
        """
        composites = {
            code: score_from_export(settings, code, export=export).composite
            for code in ("us", "cn", "jp", "de", "gb", "in", "eurozone")
        }
        assert min(composites, key=composites.get) == "us"

    def test_the_published_composite_is_reported_as_a_cross_check_not_used(self, settings, export):
        """The export's composite is a within-year rescaling, so it must not become the composite."""
        score = score_from_export(settings, "us", export=export)
        published = export.for_sheet("USA").published_composite[2024]
        assert published == pytest.approx(1.0), "the export puts the USA at the panel floor in 2024"
        assert score.composite != pytest.approx(published)
        assert any("not expected to agree" in note for note in score.notes)

    def test_the_strategy_and_direction_travel_with_the_score(self, settings, export):
        score = score_from_export(settings, "us", export=export)
        assert score.direction == settings.get("honi.scale.direction")
        assert score.strategy == settings.get("honi.aggregation.strategy")
