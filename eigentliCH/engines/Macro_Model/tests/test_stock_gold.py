"""Tests for the three-driver stock-to-gold model, section 0.7."""

import numpy as np
import pytest

from macrofield import config as config_module
from macrofield.model.stock_gold import (
    DRIVER_KEYS,
    SOURCE_DRIVER_SIGNS,
    AssetStance,
    DriverWeights,
    StockGoldError,
    dominant_driver_summary,
    driver_terms,
    evaluate,
)

PERIODS = np.arange(2015, 2025)
N = PERIODS.size


def flat_terms(**overrides):
    """Zero terms except where overridden, so one driver can be isolated."""
    terms = {key: np.zeros(N) for key in DRIVER_KEYS}
    terms.update({key: np.asarray(value, dtype=float) for key, value in overrides.items()})
    return terms


class TestDriverWeights:
    def test_default_signs_are_the_source_signs(self):
        """The authoritative equation carries `+, -, -`: driver one is positive.

        An earlier revision made all three negative, on the reasoning that a credit impulse is a
        confidence reading. It is a liquidity impulse; confidence is driver three.
        """
        weights = DriverWeights()
        assert np.allclose(weights.as_array(), [1.0, -1.0, -1.0])

    def test_source_signs_cover_every_driver(self):
        assert set(SOURCE_DRIVER_SIGNS) == set(DRIVER_KEYS)

    def test_config_signs_match_the_source_equation(self):
        """Config is where the signs live, so it is config that must agree with the source."""
        weights = DriverWeights.from_config(config_module.load())
        assert np.allclose(
            weights.as_array(), [SOURCE_DRIVER_SIGNS[key] for key in DRIVER_KEYS]
        )

    def test_rejects_a_negative_weight(self):
        """A driver's direction belongs in its configured sign, so a fitted weight cannot flip it."""
        with pytest.raises(StockGoldError, match="non-negative"):
            DriverWeights(liquidity_credit_impulse=-1.0)

    def test_requires_a_sign_for_every_driver(self):
        with pytest.raises(StockGoldError, match="no sign configured"):
            DriverWeights(signs={"innovation_growth": -1.0})

    def test_signed_array_follows_driver_key_order(self):
        weights = DriverWeights(
            liquidity_credit_impulse=1.0,
            innovation_growth=2.0,
            capital_cycle_currency_stability=3.0,
            signs={key: -1.0 for key in DRIVER_KEYS},
        )
        assert np.allclose(weights.as_array(), [-1.0, -2.0, -3.0])


class TestDriverTerms:
    def test_terms_match_the_source_definitions(self):
        y = np.full(N, 100.0)
        y_dot = np.full(N, 2.0)
        k_r_dot = np.full(N, 3.0)
        k_i = np.full(N, 200.0)
        k_i_dot = np.full(N, 5.0)
        k_i_ddot = np.full(N, 1.0)

        terms = driver_terms(y, y_dot, k_r_dot, k_i, k_i_dot, k_i_ddot)
        assert np.allclose(terms["liquidity_credit_impulse"], 1.0 / 100.0)
        assert np.allclose(terms["innovation_growth"], 2.0 / 200.0)
        # (K_R_dot + K_I_dot - Y_dot) / K_I, the unsecured-asset derivative over K_I.
        assert np.allclose(terms["capital_cycle_currency_stability"], (3.0 + 5.0 - 2.0) / 200.0)

    def test_driver_three_numerator_is_the_unsecured_asset_derivative(self):
        """Documented equivalence with section 0.4, pinned so the docstring cannot drift."""
        y_dot, k_r_dot, k_i_dot = 2.0, 3.0, 5.0
        k_i = 200.0
        terms = driver_terms(
            np.array([100.0]),
            np.array([y_dot]),
            np.array([k_r_dot]),
            np.array([k_i]),
            np.array([k_i_dot]),
            np.array([0.0]),
        )
        unsecured_derivative = k_r_dot + k_i_dot - y_dot
        assert terms["capital_cycle_currency_stability"][0] == pytest.approx(
            unsecured_derivative / k_i
        )

    def test_rejects_mismatched_shapes(self):
        with pytest.raises(StockGoldError, match="share a shape"):
            driver_terms(
                np.ones(3), np.ones(2), np.ones(3), np.ones(3), np.ones(3), np.ones(3)
            )

    def test_rejects_zero_output(self):
        with pytest.raises(StockGoldError, match="Y is zero"):
            driver_terms(
                np.zeros(2), np.ones(2), np.ones(2), np.ones(2), np.ones(2), np.ones(2)
            )

    def test_rejects_zero_financial_capital(self):
        with pytest.raises(StockGoldError, match="K_I is zero"):
            driver_terms(
                np.ones(2), np.ones(2), np.ones(2), np.zeros(2), np.ones(2), np.ones(2)
            )


class TestDriverEconomics:
    """Each driver must move the gold-over-equity ratio the way BOOK chapter 24.2 states.

    These assertions are the chapter's mechanism claims, not restatements of the code's own signs, so
    they are what would catch a reversal of the config signs.
    """

    def test_liquidity_impulse_supports_gold_against_equities(self):
        """Chapter 24.2: gold "responds positively to liquidity impulses in the financial system...
        as K_I grows, a portion of the growth seeks expression in gold positions, supporting gold's
        price." A positive credit impulse must therefore raise gold over equities."""
        terms = flat_terms(liquidity_credit_impulse=np.full(N, 0.01))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert np.all(result.ratio_change > 0.0)
        assert result.gold_over_equity[-1] > result.gold_over_equity[0]

    def test_growth_pushes_gold_down_against_equities(self):
        """Chapter 24.2: vigorous innovation creates competing real-asset investments, so the
        relative attractiveness of gold declines. Under normal growth equities outperform gold."""
        terms = flat_terms(innovation_growth=np.full(N, 0.01))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert np.all(result.ratio_change < 0.0)
        assert result.gold_over_equity[-1] < result.gold_over_equity[0]

    def test_collapsing_unsecured_assets_push_gold_up(self):
        """In Phase IV the unsecured-asset derivative turns negative, and the negative coefficient
        then contributes positively to gold. This is the mechanism that makes driver three dominate
        in a hyperinflationary phase."""
        terms = flat_terms(capital_cycle_currency_stability=np.full(N, -0.01))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert np.all(result.ratio_change > 0.0)
        assert result.gold_over_equity[-1] > result.gold_over_equity[0]

    def test_the_two_gold_supporting_drivers_are_distinguishable(self):
        """Drivers one and three both support gold, and they must not be the same term.

        Chapter 24 keeps liquidity and confidence separate, and the earlier all-negative sign set
        collapsed driver one onto driver three's direction. This pins them apart: a *rising*
        unsecured-asset gap is a loss of currency backing and pushes gold down, where a rising
        liquidity impulse pushes it up.
        """
        liquidity = evaluate(
            PERIODS,
            flat_terms(liquidity_credit_impulse=np.full(N, 0.01)),
            DriverWeights(),
            anchor_period=2015,
        )
        confidence = evaluate(
            PERIODS,
            flat_terms(capital_cycle_currency_stability=np.full(N, 0.01)),
            DriverWeights(),
            anchor_period=2015,
        )
        assert np.all(liquidity.ratio_change > 0.0)
        assert np.all(confidence.ratio_change < 0.0)


class TestEvaluate:
    def test_stock_to_gold_is_the_reciprocal_of_the_modelled_ratio(self):
        terms = flat_terms(innovation_growth=np.full(N, 0.005))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert np.allclose(result.stock_to_gold, 1.0 / result.gold_over_equity)

    def test_anchor_pins_the_level(self):
        terms = flat_terms(innovation_growth=np.full(N, 0.005))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2019, anchor_value=1.0)
        anchor_index = int(np.flatnonzero(PERIODS == 2019)[0])
        assert result.gold_over_equity[anchor_index] == pytest.approx(1.0)

    def test_the_anchor_is_reported_not_buried(self):
        """Brief section 0.7 requires the calibration anchor to be exposed."""
        terms = flat_terms()
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2019, anchor_value=1.5)
        assert result.anchor_period == 2019
        assert result.anchor_value == 1.5

    def test_default_anchor_year_comes_from_config(self):
        assert config_module.load().get("stock_gold.calibration_anchor_year") == 2019

    def test_rejects_an_anchor_outside_the_window(self):
        with pytest.raises(StockGoldError, match="not in the period range"):
            evaluate(PERIODS, flat_terms(), DriverWeights(), anchor_period=1999)

    def test_rejects_missing_driver_terms(self):
        with pytest.raises(StockGoldError, match="missing driver terms"):
            evaluate(PERIODS, {"innovation_growth": np.zeros(N)}, DriverWeights(), 2015)

    def test_rejects_terms_of_differing_lengths(self):
        """The error must name the drivers, not surface as a numpy concatenation failure."""
        with pytest.raises(StockGoldError, match="must share a shape"):
            evaluate(PERIODS, flat_terms(innovation_growth=np.zeros(3)), DriverWeights(), 2015)

    def test_rejects_terms_that_do_not_match_the_period_count(self):
        terms = {key: np.zeros(3) for key in DRIVER_KEYS}
        with pytest.raises(StockGoldError, match="periods were given"):
            evaluate(PERIODS, terms, DriverWeights(), 2015)

    def test_zero_change_leaves_the_ratio_flat(self):
        result = evaluate(PERIODS, flat_terms(), DriverWeights(), anchor_period=2015)
        assert np.allclose(result.gold_over_equity, 1.0)

    def test_warns_when_the_ratio_reaches_zero(self):
        """A ratio at or below zero makes the reciprocal undefined, which must be said."""
        terms = flat_terms(innovation_growth=np.full(N, 1.0))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015, anchor_value=1.0)
        assert any("zero or below" in note for note in result.notes)

    def test_carries_the_model_derived_label(self):
        """Brief section 6: every projected path is labelled."""
        result = evaluate(PERIODS, flat_terms(), DriverWeights(), anchor_period=2015)
        assert result.label == "illustrative, model-derived"


class TestDominantDriverAndStance:
    @pytest.mark.parametrize(
        "driver,stance",
        [
            ("liquidity_credit_impulse", AssetStance.PARTICIPATORY),
            ("innovation_growth", AssetStance.VALUE_PRODUCING),
            ("capital_cycle_currency_stability", AssetStance.VALUE_PRESERVING),
        ],
    )
    def test_dominant_driver_selects_the_stance(self, driver, stance):
        terms = flat_terms(**{driver: np.full(N, 0.05)})
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert result.dominant_driver[-1] == driver
        assert result.stance[-1] is stance

    def test_dominance_is_by_absolute_contribution(self):
        """A large negative contribution dominates a small positive one."""
        terms = flat_terms(
            innovation_growth=np.full(N, 0.001),
            capital_cycle_currency_stability=np.full(N, -0.05),
        )
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        assert result.dominant_driver[-1] == "capital_cycle_currency_stability"

    def test_summary_reports_the_current_stance(self):
        terms = flat_terms(capital_cycle_currency_stability=np.full(N, -0.02))
        result = evaluate(PERIODS, terms, DriverWeights(), anchor_period=2015)
        summary = dominant_driver_summary(result)
        assert summary["stance"] == "value_preserving"
        assert summary["period"] == PERIODS[-1]
        assert summary["label"] == "illustrative, model-derived"


class TestQuantityEquationValidity:
    def test_flags_periods_above_the_validity_ceiling(self):
        saturation = np.linspace(2.0, 5.0, N)
        result = evaluate(
            PERIODS,
            flat_terms(),
            DriverWeights(),
            anchor_period=2015,
            capital_saturation=saturation,
            quantity_equation_validity_ceiling=3.5,
        )
        assert result.quantity_equation_valid is not None
        assert result.quantity_equation_valid[0]
        assert not result.quantity_equation_valid[-1]
        assert any("validity ceiling" in note for note in result.notes)

    def test_silent_when_saturation_stays_below_the_ceiling(self):
        result = evaluate(
            PERIODS,
            flat_terms(),
            DriverWeights(),
            anchor_period=2015,
            capital_saturation=np.full(N, 2.0),
            quantity_equation_validity_ceiling=3.5,
        )
        assert result.quantity_equation_valid is not None
        assert result.quantity_equation_valid.all()
        assert not any("validity ceiling" in note for note in result.notes)

    def test_rejects_a_saturation_shape_mismatch(self):
        with pytest.raises(StockGoldError, match="capital_saturation has shape"):
            evaluate(
                PERIODS,
                flat_terms(),
                DriverWeights(),
                anchor_period=2015,
                capital_saturation=np.ones(3),
                quantity_equation_validity_ceiling=3.5,
            )


class TestWeimarValidationTarget:
    """BOOK section 24.3.2 is the one concrete backtest the chapter supplies.

    The German series are not on disk, so the target is declared in config rather than run. What can
    be tested without them is that the implementation is *capable* of the episode's shape, and that
    the target's orientation has not been recorded upside down, which is the mistake the episode
    invites: the chapter's figure is equity-over-gold, the reciprocal of the modelled ratio.
    """

    @staticmethod
    def target():
        analogues = config_module.load().get("validation.analogues")
        (germany,) = [item for item in analogues if item["name"] == "germany_1920s"]
        return germany["target"]

    def test_the_target_is_recorded_against_the_stock_to_gold_orientation(self):
        target = self.target()
        assert target["quantity"] == "stock_to_gold"
        assert target["start_value"] > target["end_value"]

    def test_the_target_is_declared_as_unrun_while_its_data_is_absent(self):
        """A target nobody can run must not read as a passing backtest."""
        assert self.target()["data_available"] is False

    def test_a_collapse_of_currency_confidence_drives_stock_to_gold_towards_zero(self):
        """The episode's mechanism, in the model's own terms.

        Weimar is driver three dominating: currency confidence fails, the unsecured-asset gap
        derivative turns negative, gold over equities runs away and its reciprocal, the ratio the
        chapter plots, collapses towards zero from a high starting level.
        """
        target = self.target()
        terms = flat_terms(capital_cycle_currency_stability=np.full(N, -0.5))
        result = evaluate(
            PERIODS,
            terms,
            DriverWeights(),
            anchor_period=int(PERIODS[0]),
            anchor_value=1.0 / float(target["start_value"]),
        )
        assert result.stock_to_gold[0] == pytest.approx(target["start_value"])
        assert np.all(np.diff(result.stock_to_gold) < 0.0)
        assert result.stock_to_gold[-1] < 0.05 * result.stock_to_gold[0]
        assert result.stance[-1] is AssetStance.VALUE_PRESERVING


class TestNoDatedForecast:
    def test_no_legacy_forecast_dates_appear_in_config(self):
        """Brief section 0.14: the 2022 peak and the 2025 to 2028 window must not become constants."""
        section = config_module.load().section("stock_gold").as_dict()
        rendered = str(section)
        for forbidden in ("2022", "2025", "2028"):
            assert forbidden not in rendered
        # The calibration anchor is the one date that is legitimately configuration.
        assert section["calibration_anchor_year"] == 2019
