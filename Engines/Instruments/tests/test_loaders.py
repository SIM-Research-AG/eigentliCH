"""The ETL, tested against the real source files.

These tests make a different claim from the rest of the suite. The arithmetic tests say
"the model is implemented correctly"; these say "the loaders still read the actual files
correctly", which is the thing that breaks when somebody re-exports a spreadsheet. They
skip when the sources are not present rather than failing.
"""

from __future__ import annotations

import pytest

from tests.conftest import needs_feed, needs_sources


@needs_sources
class TestLongRecord:
    def test_every_registered_series_loads_dense(self, long_record):
        from store.etl.long_record import SERIES
        assert set(long_record) == {s.key for s in SERIES}
        for key, series in long_record.items():
            expected = series.last_year - series.first_year + 1
            assert len(series.values) == expected, f"{key} has a hole"

    def test_the_truncated_series_report_their_real_windows(self, long_record):
        assert (long_record["house"].first_year, long_record["house"].last_year) == (1890, 2020)
        assert (long_record["bondtr"].first_year, long_record["bondtr"].last_year) == (1871, 2015)
        # Agriculture is sparse before 1910 and is sliced rather than back-filled.
        assert long_record["ag"].first_year == 1910

    def test_each_series_carries_the_hash_of_the_file_it_came_from(self, long_record):
        for series in long_record.values():
            assert len(series.source_sha256) == 64

    def test_a_relabelled_column_is_refused_rather_than_read(self, tmp_path, long_record):
        """The header guard is the whole point of the register.

        These workbooks carry two or three candidate vintages side by side. Reading the
        wrong column would change every figure downstream and nothing would look wrong.
        """
        import openpyxl
        from store.etl.long_record import LongRecordError, SERIES, _read_column
        from tests.conftest import ECN_DIR

        spec = next(s for s in SERIES if s.key == "gold")
        book = openpyxl.load_workbook(ECN_DIR / spec.filename)
        book.worksheets[0].cell(row=1, column=spec.column, value="something else entirely")
        broken = tmp_path / spec.filename
        book.save(broken)
        with pytest.raises(LongRecordError, match="layout has changed"):
            _read_column(broken, spec)


@needs_feed
class TestMarketSignal:
    def test_all_nine_sections_are_found(self, sections):
        assert set(sections) == {
            "PERFORMANCE SUMMARY", "DRAWDOWN PERFORMANCE", "DOWNSIDE PERFORMANCE",
            "UPSIDE PERFORMANCE", "PERFORMANCE CONTRIBUTION", "ALLOCATION GROUPS",
            "MARKET RISK SIGNAL", "INSTRUMENT ALLOCATION", "3-MONTH PERFORMANCE",
        }

    def test_a_title_beginning_with_a_digit_is_still_a_title(self, sections):
        """`3-MONTH PERFORMANCE` once leaked its rows into INSTRUMENT ALLOCATION."""
        assert len(sections["INSTRUMENT ALLOCATION"].rows) == 240
        assert len(sections["3-MONTH PERFORMANCE"].rows) == 240

    def test_the_signal_is_normalised_and_out_of_tolerance_months_are_flagged(self, sections):
        from store.etl.market_signal import read_market_risk_signal
        months = read_market_risk_signal(sections)
        assert len(months) == 240
        for m in months:
            assert abs(sum(m.probabilities) - 1.0) < 1e-12
        flagged = sorted(m.period for m in months if not m.in_tolerance)
        # The same five months `taa.py` independently identified in the correctly-dated
        # copy -- which is what confirms the one-month date correction is right.
        assert flagged == ["2008-11", "2009-04", "2013-11", "2013-12", "2014-02"]

    @pytest.mark.parametrize("period,expected", [
        ("2008-10", -0.2130),   # the GFC crash month
        ("2020-03", -0.1370),   # COVID
        ("2020-02", -0.0817),
    ])
    def test_recovered_returns_match_market_history(self, sections, period, expected):
        from store.etl.market_signal import recover_instrument_returns
        kept, dropped = recover_instrument_returns(sections)
        found = [r.value for r in kept + dropped
                 if r.instrument == "Global Equities" and r.period == period]
        assert found, f"no Global Equities observation for {period}"
        assert found[0] == pytest.approx(expected, abs=6e-4)

    def test_the_weight_filter_is_strict(self, sections):
        """A weight of exactly 5.00 is excluded, reproducing the M9 census.

        With an inclusive comparison, Global Equities gains 2011-07 and the census can no
        longer be reproduced -- and a census that cannot be reproduced cannot be audited.
        """
        from store.etl.market_signal import MIN_WEIGHT_PCT, recover_instrument_returns
        kept, dropped = recover_instrument_returns(sections)
        assert all(r.weight_pct > MIN_WEIGHT_PCT for r in kept)
        assert any(r.weight_pct == MIN_WEIGHT_PCT for r in dropped)

    def test_a_broken_date_shift_is_caught_on_load(self, sections):
        from store.etl.market_signal import MarketSignalError, recover_instrument_returns
        with pytest.raises(MarketSignalError, match="date-shift check"):
            recover_instrument_returns(sections, shift=0)
