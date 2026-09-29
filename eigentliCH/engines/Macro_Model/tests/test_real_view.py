"""Tests for the nominal and real views, phase 6 of the battle plan."""

import numpy as np
import pytest

from macrofield.model.real_view import (
    REGIME_TRANSITION,
    Basis,
    RealViewError,
    both_views,
    check_regime_span,
    deflate,
    deflate_rate,
    nominal_view,
)

YEARS = np.arange(2000, 2011)


class TestBasis:
    def test_only_nominal_is_undeflated(self):
        assert not Basis.NOMINAL.is_deflated
        assert Basis.REAL_GOLD.is_deflated
        assert Basis.REAL_CPI.is_deflated

    def test_each_deflated_basis_names_the_series_it_needs(self):
        assert Basis.REAL_GOLD.deflator_series == "gold_price"
        assert Basis.REAL_CPI.deflator_series == "consumer_prices"
        assert Basis.NOMINAL.deflator_series is None

    def test_every_basis_has_a_label_that_says_what_it_is(self):
        """A number whose basis is ambiguous is worse than no number."""
        for basis in Basis:
            assert basis.label
            assert ("real" in basis.label) is basis.is_deflated


class TestDeflate:
    def test_a_series_growing_with_its_deflator_is_flat_in_real_terms(self):
        nominal = 100.0 * 1.05 ** np.arange(YEARS.size)
        result = deflate(YEARS, nominal, nominal.copy(), Basis.REAL_GOLD)
        assert np.allclose(result.values, result.values[0])

    def test_the_base_period_carries_the_nominal_level(self):
        nominal = np.linspace(100.0, 200.0, YEARS.size)
        deflator = np.linspace(1.0, 4.0, YEARS.size)
        result = deflate(YEARS, nominal, deflator, Basis.REAL_CPI, base_period=2005)
        at_base = int(np.flatnonzero(YEARS == 2005)[0])
        assert result.values[at_base] == pytest.approx(nominal[at_base])

    def test_the_base_period_defaults_to_the_last(self):
        nominal = np.linspace(100.0, 200.0, YEARS.size)
        result = deflate(YEARS, nominal, np.linspace(1.0, 4.0, YEARS.size), Basis.REAL_CPI)
        assert result.base_period == YEARS[-1]
        assert result.values[-1] == pytest.approx(nominal[-1])

    def test_deflating_preserves_nothing_about_the_nominal_growth_rate(self):
        """The point of the exercise: a real series is a different series, not a rescaling."""
        nominal = 100.0 * 1.10 ** np.arange(YEARS.size)
        deflator = 1.0 * 1.04 ** np.arange(YEARS.size)
        result = deflate(YEARS, nominal, deflator, Basis.REAL_CPI)
        real_growth = result.growth()[1:]
        assert np.allclose(real_growth, 1.10 / 1.04 - 1.0)
        assert not np.allclose(real_growth, 0.10)

    def test_the_gold_basis_says_it_is_not_the_conventional_one(self):
        """A reader expecting CPI has to be told which this is."""
        result = deflate(YEARS, np.ones(YEARS.size), np.ones(YEARS.size), Basis.REAL_GOLD)
        assert any("not the conventional basis" in note for note in result.notes)

    def test_the_nominal_basis_is_refused_here(self):
        with pytest.raises(RealViewError, match="needs no deflator"):
            deflate(YEARS, np.ones(YEARS.size), np.ones(YEARS.size), Basis.NOMINAL)

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(RealViewError, match="share a length"):
            deflate(YEARS, np.ones(3), np.ones(YEARS.size), Basis.REAL_CPI)

    def test_an_absent_base_period_is_refused(self):
        with pytest.raises(RealViewError, match="not in the range"):
            deflate(YEARS, np.ones(YEARS.size), np.ones(YEARS.size), Basis.REAL_CPI, base_period=1980)

    def test_a_non_positive_deflator_at_the_base_is_refused(self):
        deflator = np.ones(YEARS.size)
        deflator[-1] = 0.0
        with pytest.raises(RealViewError, match="cannot be indexed"):
            deflate(YEARS, np.ones(YEARS.size), deflator, Basis.REAL_CPI)


class TestNominalView:
    def test_it_leaves_the_series_alone_but_states_the_basis(self):
        values = np.linspace(1.0, 2.0, YEARS.size)
        result = nominal_view(YEARS, values)
        assert np.allclose(result.values, values)
        assert result.basis is Basis.NOMINAL
        assert any("undeflated" in note for note in result.notes)


class TestBothViews:
    def test_it_returns_every_view_the_deflators_allow(self):
        views = both_views(
            YEARS,
            np.linspace(100.0, 200.0, YEARS.size),
            gold=np.linspace(1.0, 2.0, YEARS.size),
            consumer_prices=np.linspace(1.0, 1.3, YEARS.size),
        )
        assert set(views) == {"nominal", "real_gold", "real_cpi"}

    def test_a_missing_deflator_produces_no_view_rather_than_a_substitute(self):
        """Substituting one deflator for another changes the meaning and leaves the label intact."""
        views = both_views(YEARS, np.ones(YEARS.size), consumer_prices=np.ones(YEARS.size))
        assert set(views) == {"nominal", "real_cpi"}

    def test_nominal_is_always_present(self):
        assert set(both_views(YEARS, np.ones(YEARS.size))) == {"nominal"}

    def test_the_two_deflators_disagree_which_is_the_reason_to_report_both(self):
        nominal = np.full(YEARS.size, 100.0)
        views = both_views(
            YEARS,
            nominal,
            gold=1.0 * 1.08 ** np.arange(YEARS.size),
            consumer_prices=1.0 * 1.02 ** np.arange(YEARS.size),
            base_period=2000,
        )
        assert not np.allclose(views["real_gold"].values, views["real_cpi"].values)


class TestRegimeSpan:
    def test_a_window_spanning_the_whole_transition_is_flagged(self):
        notes = check_regime_span(np.arange(1900, 1990))
        assert notes and "two regimes spliced together" in notes[0]

    def test_a_window_overlapping_the_transition_is_flagged_more_mildly(self):
        notes = check_regime_span(np.arange(1950, 1990))
        assert notes and "overlaps" in notes[0]

    def test_a_modern_window_is_not_flagged(self):
        assert check_regime_span(np.arange(1980, 2025)) == []

    def test_an_empty_window_is_not_flagged(self):
        assert check_regime_span([]) == []

    def test_the_caution_travels_with_a_deflated_series(self):
        years = np.arange(1900, 1990)
        result = deflate(years, np.ones(years.size), np.ones(years.size), Basis.REAL_CPI)
        assert any("regime" in note for note in result.notes)

    def test_the_transition_is_the_books_dates(self):
        assert REGIME_TRANSITION == (1914, 1971)


class TestDeflateRate:
    def test_it_is_the_ratio_not_the_difference(self):
        """At low rates the two agree; the exact form is used so that at high rates it stays right."""
        exact = deflate_rate([0.02], [0.01])[0]
        assert exact == pytest.approx(1.02 / 1.01 - 1.0)
        assert exact != pytest.approx(0.01, abs=1e-6)

    def test_subtraction_would_be_badly_wrong_in_a_hyperinflation(self):
        """The case the framework cares about, where the second-order term is the whole answer."""
        nominal, inflation = 1.0, 1.0
        exact = float(deflate_rate([nominal], [inflation])[0])
        assert exact == pytest.approx(0.0)
        assert abs((nominal - inflation) - exact) < 1e-12
        # And where they differ, the subtraction overstates badly.
        exact_2 = float(deflate_rate([2.0], [1.0])[0])
        assert exact_2 == pytest.approx(0.5)
        assert (2.0 - 1.0) == pytest.approx(1.0), "subtraction would say 100 per cent, not 50"

    def test_a_deflator_at_minus_one_is_undefined_rather_than_infinite(self):
        assert not np.isfinite(deflate_rate([0.05], [-1.0])[0])

    def test_mismatched_shapes_are_refused(self):
        with pytest.raises(RealViewError, match="share a shape"):
            deflate_rate([0.01, 0.02], [0.01])


class TestModelBasis:
    """The basis the programme can always produce, because its deflator is derived rather than fetched."""

    def test_it_needs_no_fetched_series(self):
        assert Basis.REAL_MODEL.deflator_series is None
        assert Basis.REAL_MODEL.is_deflated

    def test_it_says_the_deflator_is_a_model_quantity(self):
        """It must not be mistaken for CPI, which is what a reader will assume 'real' means."""
        result = deflate(YEARS, np.ones(YEARS.size), np.linspace(1.0, 2.0, YEARS.size), Basis.REAL_MODEL)
        joined = " ".join(result.notes)
        assert "model quantity" in joined
        assert "not CPI" in joined

    def test_both_views_includes_it_when_the_price_level_is_supplied(self):
        views = both_views(
            YEARS, np.ones(YEARS.size), model_price_level=np.linspace(1.0, 2.0, YEARS.size)
        )
        assert set(views) == {"nominal", "real_model"}

    def test_deflating_a_series_by_something_proportional_to_it_is_circular(self):
        """Why output gets no real view on this basis.

        Chapter 7 derives the real-economy price level as proportional to output, so deflating output by it
        returns a flat line by construction. On United States data output grows 22.9 times nominally and
        exactly 1.0 times on this basis, and a flat line labelled "output, real" would read as fifty years
        without real growth.
        """
        output = 100.0 * 1.07 ** np.arange(YEARS.size)
        price_level = output * 3.0  # proportional, as P_R is to Y
        result = deflate(YEARS, output, price_level, Basis.REAL_MODEL)
        assert np.allclose(result.values, result.values[0]), "the circular case must be flat"

    def test_deflating_an_independent_series_is_not_circular(self):
        """The capital stocks are not in the price level's definition, so their real view is informative."""
        output = 100.0 * 1.07 ** np.arange(YEARS.size)
        capital = 100.0 * 1.03 ** np.arange(YEARS.size)
        result = deflate(YEARS, capital, output * 3.0, Basis.REAL_MODEL)
        assert not np.allclose(result.values, result.values[0])
        # Growing slower than the deflator means shrinking in real terms.
        assert result.values[-1] < result.values[0]


class TestEndpointGuardsTheCircularCase:
    @staticmethod
    def source() -> str:
        import inspect

        from macrofield.cockpit import server

        return inspect.getsource(server.create_app)

    def test_the_derived_endpoint_omits_the_circular_view_and_says_why(self):
        source = self.source()
        assert "state_views_circular" in source
        assert "deflating output by it is circular" in source

    def test_output_is_denied_the_model_deflator_specifically(self):
        """Not denied a real view altogether: denied the one that is circular for it."""
        assert 'model_price_level=None if name == "output" else deflator' in self.source()

    def test_the_independent_deflators_are_used_where_they_cover_the_window(self):
        source = self.source()
        assert 'for key in ("consumer_prices", "gold_price")' in source
        assert 'consumer_prices=external.get("consumer_prices")' in source

    def test_a_partial_cpi_series_is_refused_rather_than_spliced(self):
        """Deflating part of a series and not the rest would splice two bases together."""
        assert "splice two bases together" in self.source()


class TestCPIIsFetched:
    """The independent deflator, which is the whole reason to fetch it.

    Without it output has no real view at all, because the model's own price level is proportional to output.
    """

    def test_consumer_prices_are_in_the_world_bank_map(self):
        from macrofield.pipeline import WORLD_BANK

        assert WORLD_BANK["consumer_prices"] == "FP.CPI.TOTL"

    def test_it_is_optional_and_says_what_is_lost_without_it(self):
        import inspect

        from macrofield import pipeline

        source = inspect.getsource(pipeline.assemble)
        assert "consumer prices are unavailable" in source
        assert "output has no real view at all" in source

    def test_a_deflator_carries_no_level_adjustment(self):
        """Scaling a deflator rescales every deflated series by the same constant, changing no comparison."""
        import inspect

        from macrofield import pipeline

        assert "a deflator carries no level adjustment" in inspect.getsource(pipeline.assemble)


class TestGoldIsTheBooksBasis:
    """Chapter 11 computes its real-rate series with the gold price, not CPI.

    So gold is not an alternative to CPI here, it is the framework's own basis, and the front end prefers it.
    """

    def test_gold_is_fetched_as_an_optional_series(self):
        import inspect

        from macrofield import pipeline

        source = inspect.getsource(pipeline.assemble)
        assert "sources.lbma.annual_gold_price()" in source
        assert "the gold price is unavailable" in source

    def test_it_says_why_gold_rather_than_cpi(self):
        import inspect

        from macrofield import pipeline

        source = inspect.getsource(pipeline.assemble)
        assert "price-of-money instrument" in source
        assert "Chapter 11's own basis is gold" in source

    def test_the_endpoint_offers_it_as_a_deflator(self):
        import inspect

        from macrofield.cockpit import server

        source = inspect.getsource(server.create_app)
        assert 'for key in ("consumer_prices", "gold_price")' in source
        assert 'gold=external.get("gold_price")' in source

    def test_the_front_end_prefers_gold_then_cpi_then_the_model(self):
        """The order is the argument: the book's basis, then a measured index, then a model quantity."""
        from macrofield.cockpit.server import STATIC_DIRECTORY

        page = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        order = page.index('["real_gold"'), page.index('["real_cpi"'), page.index('["real_model"')
        assert order == tuple(sorted(order)), "gold must be preferred, the model's own basis last"

    def test_the_two_independent_bases_can_disagree_and_both_are_kept(self):
        """A quantity can grow in CPI terms and shrink against gold, which is the reason to report both."""
        years = np.arange(1972, 2025)
        nominal = 100.0 * 1.06 ** np.arange(years.size)
        views = both_views(
            years,
            nominal,
            consumer_prices=1.0 * 1.04 ** np.arange(years.size),
            gold=1.0 * 1.08 ** np.arange(years.size),
        )
        cpi = views["real_cpi"].values
        gold = views["real_gold"].values
        assert cpi[-1] > cpi[0], "it grows against consumer prices"
        assert gold[-1] < gold[0], "and shrinks against gold"


class TestTerminologyIsDisambiguated:
    """The collision that had to be settled before anything else in phase 6.

    `derived.py` uses `real_*` for the real economy against the financial economy. That is a statement about
    which *sector*, not about inflation adjustment, and the two axes are orthogonal.
    """

    def test_the_two_axes_are_named_apart(self):
        from macrofield.model.real_view import BASIS_AXIS, SECTOR_AXIS

        assert "real economy" in SECTOR_AXIS and "financial economy" in SECTOR_AXIS
        assert "nominal" in BASIS_AXIS and "deflated" in BASIS_AXIS

    def test_the_sector_prefixes_of_derived_are_not_a_basis(self):
        """A financial-sector price level can be expressed in real terms, which is the whole point."""
        from macrofield.model.derived import Indicator

        sector_prefixed = [i for i in Indicator if i.value.startswith(("real_", "financial_"))]
        assert sector_prefixed, "derived.py still uses sector prefixes"
        for indicator in sector_prefixed:
            assert indicator.value not in {b.value for b in Basis}
