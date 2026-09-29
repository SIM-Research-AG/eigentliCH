"""Tests for the static charts, section 6.

The tests concentrate on the requirements rather than on appearance: every chart must carry the
calibration window, the data vintage, the disclaimer, and the projection label where the path is
projected. Appearance is not testable and is not what the brief mandates.
"""

import numpy as np
import pytest

from macrofield.reporting.charts import (
    ChartContext,
    ChartError,
    comparative_chart,
    cycle_chart,
    honi_chart,
    phase_timeline_chart,
    regime_chart,
    save,
    stock_gold_chart,
    trajectory_chart,
    unsecured_assets_chart,
)
from macrofield.reporting.export import DISCLAIMER, PROJECTION_LABEL

PERIODS = list(range(2000, 2025))
N = len(PERIODS)


def context(**overrides) -> ChartContext:
    payload = {
        "economy": "United States",
        "calibration_window": (2000, 2024),
        "data_vintage": "PWT 10.01, BIS 2026-07",
    }
    payload.update(overrides)
    return ChartContext(**payload)


@pytest.fixture(autouse=True)
def close_figures():
    """Close every figure after each test.

    Without this the parametrised provenance tests accumulate figures, which matplotlib warns about at
    twenty and which would eventually exhaust memory in a long comparative run.
    """
    yield
    import matplotlib.pyplot as plt

    plt.close("all")


def figure_text(figure) -> str:
    """Collect every string drawn on a figure, including tick labels.

    Tick labels matter here: the comparative chart carries its economy names as x tick labels rather
    than as annotations, so a helper that skipped them would report the names as absent.
    """
    collected = [t.get_text() for t in figure.texts]
    for axes in figure.axes:
        collected.append(axes.get_title())
        collected.append(axes.get_xlabel())
        collected.append(axes.get_ylabel())
        collected.extend(t.get_text() for t in axes.texts)
        collected.extend(label.get_text() for label in axes.get_xticklabels())
        collected.extend(label.get_text() for label in axes.get_yticklabels())
        legend = axes.get_legend()
        if legend is not None:
            collected.extend(t.get_text() for t in legend.get_texts())
    return " ".join(collected)


def growing(scale: float = 100.0, rate: float = 0.03) -> np.ndarray:
    t = np.arange(N, dtype=float)
    return scale * np.exp(rate * t) * (1.0 + 0.05 * np.sin(2.0 * np.pi * t / 8.0))


class TestChartContext:
    def test_requires_a_data_vintage(self):
        with pytest.raises(ChartError, match="data vintage"):
            ChartContext("us", (2000, 2024), "   ")

    def test_rejects_a_backwards_window(self):
        with pytest.raises(ChartError, match="runs backwards"):
            ChartContext("us", (2024, 2000), "vintage")

    def test_footer_states_the_window_and_vintage(self):
        footer = context().footer(projected=False)
        assert "2000 to 2024" in footer
        assert "PWT 10.01" in footer
        assert DISCLAIMER in footer

    def test_footer_adds_the_label_only_when_projected(self):
        assert PROJECTION_LABEL not in context().footer(projected=False)
        assert PROJECTION_LABEL in context().footer(projected=True)

    def test_footer_discloses_an_adjustment(self):
        footer = context(adjustments_applied=True).footer(projected=False)
        assert "not published levels" in footer
        assert "turning points unaffected" in footer


class TestEveryChartCarriesItsProvenance:
    """The section 6 requirement, checked on every chart rather than on a sample."""

    def _charts(self):
        rng = np.random.default_rng(20260727)
        return {
            "trajectory": trajectory_chart(
                context(),
                PERIODS,
                {"Y": growing(), "K_R": growing(320.0, 0.02), "K_I": growing(250.0, 0.05)},
                {"Y": growing() * 1.02},
            ),
            "phase": phase_timeline_chart(
                context(),
                PERIODS,
                np.linspace(1.8, 3.2, N),
                [2] * 12 + [3] * 13,
            ),
            "unsecured": unsecured_assets_chart(
                context(),
                PERIODS,
                np.linspace(2.0, 4.5, N),
                accelerating=[False] * 15 + [True] * 10,
                collapsing=[False] * N,
            ),
            "honi": honi_chart(
                context(),
                {"financial": 1.8, "international": 2.4, "real": 3.1},
                composite=2.4,
                stage="Optimisation",
                saturation_percentage=251.0,
            ),
            "stock_gold": stock_gold_chart(
                context(),
                PERIODS,
                {
                    "liquidity_credit_impulse": rng.normal(0, 0.01, N),
                    "innovation_growth": rng.normal(0, 0.01, N),
                    "capital_cycle_currency_stability": rng.normal(0, 0.01, N),
                },
                np.linspace(1.0, 1.4, N),
                dominant_driver="capital_cycle_currency_stability",
            ),
            "regime": regime_chart(
                context(),
                np.full(25, 0.04),
                five_regime={"Crisis": 0.2, "Contraction": 0.2, "Stagnation": 0.2, "Expansion": 0.2, "Boom": 0.2},
            ),
            "cycles": cycle_chart(
                context(),
                np.geomspace(2.0, 120.0, 60),
                rng.random(60),
                priors={"credit": 18.0, "capital": 90.0},
            ),
            "comparative": comparative_chart(
                context(), {"Japan": 3.54, "France": 3.24, "United States": 2.51, "India": 1.86}
            ),
        }

    @pytest.mark.parametrize(
        "name",
        [
            "trajectory",
            "phase",
            "unsecured",
            "honi",
            "stock_gold",
            "regime",
            "cycles",
            "comparative",
        ],
    )
    def test_chart_carries_window_vintage_and_disclaimer(self, name):
        figure = self._charts()[name]
        text = figure_text(figure)
        assert "2000 to 2024" in text
        assert "PWT 10.01" in text
        assert DISCLAIMER in text

    def test_the_projected_chart_carries_the_label(self):
        """The gold path is integrated forward from an anchor, so it is a projection."""
        assert PROJECTION_LABEL in figure_text(self._charts()["stock_gold"])

    def test_a_non_projected_chart_does_not_claim_to_be_one(self):
        assert PROJECTION_LABEL not in figure_text(self._charts()["trajectory"])


class TestChartContent:
    def test_trajectory_rebases_so_the_smallest_series_is_visible(self):
        figure = trajectory_chart(
            context(),
            PERIODS,
            {"Y": growing(100.0), "K_I": growing(250000.0)},
        )
        axes = figure.axes[0]
        # After rebasing both start at 100, so neither is a flat line at the bottom.
        starts = [line.get_ydata()[0] for line in axes.get_lines()]
        assert all(abs(start - 100.0) < 1e-6 for start in starts)

    def test_phase_chart_reports_the_distance_to_the_ceiling(self):
        figure = phase_timeline_chart(
            context(), PERIODS, np.linspace(1.8, 2.6, N), [2] * N, ceiling=3.0
        )
        text = figure_text(figure)
        assert "Phase 3 ceiling" in text
        assert "0.40" in text  # 3.0 minus the final 2.60

    def test_phase_chart_marks_a_transition(self):
        figure = phase_timeline_chart(
            context(), PERIODS, np.linspace(1.8, 3.2, N), [2] * 12 + [3] * 13
        )
        assert "to phase 3" in figure_text(figure)

    def test_honi_chart_states_the_scale_direction(self):
        """Five being healthiest is counter-intuitive, and a chart is where a score gets misread."""
        figure = honi_chart(
            context(), {"financial": 1.8, "real": 3.1}, composite=2.4, stage="Optimisation"
        )
        assert "5 healthiest" in figure_text(figure)

    def test_honi_chart_handles_missing_saturation(self):
        figure = honi_chart(context(), {"financial": 1.8}, composite=None, stage=None)
        assert "not available" in figure_text(figure)

    def test_regime_chart_annotates_the_tail_mass(self):
        figure = regime_chart(context(), np.full(25, 0.04), tail_bins=5)
        assert "crisis tail" in figure_text(figure)
        assert "20.0%" in figure_text(figure)

    def test_stock_gold_chart_names_the_dominant_driver(self):
        figure = stock_gold_chart(
            context(),
            PERIODS,
            {"innovation_growth": np.zeros(N)},
            np.ones(N),
            dominant_driver="innovation_growth",
        )
        assert "dominant driver: innovation growth" in figure_text(figure)

    def test_cycle_chart_marks_the_priors(self):
        figure = cycle_chart(
            context(), np.geomspace(2.0, 120.0, 60), np.ones(60), priors={"credit": 18.0}
        )
        assert "credit 18y" in figure_text(figure)

    def test_cycle_chart_labels_a_detected_window_as_a_projection(self):
        figure = cycle_chart(
            context(),
            np.geomspace(2.0, 120.0, 60),
            np.ones(60),
            synchronisation_window=(2031, 2035),
        )
        text = figure_text(figure)
        assert "2031 to 2035" in text
        assert PROJECTION_LABEL in text

    def test_comparative_chart_orders_and_labels_every_economy(self):
        figure = comparative_chart(context(), {"Japan": 3.54, "India": 1.86, "United States": 2.51})
        text = figure_text(figure)
        for name in ("Japan", "India", "United States"):
            assert name in text
        assert "3.54" in text


class TestSave:
    def test_writes_a_file_and_creates_the_directory(self, tmp_path):
        figure = comparative_chart(context(), {"Japan": 3.54})
        path = save(figure, tmp_path / "nested" / "chart.png")
        assert path.exists()
        assert path.stat().st_size > 0

    def test_closes_the_figure_so_a_long_run_does_not_accumulate_them(self, tmp_path):
        import matplotlib.pyplot as plt

        before = len(plt.get_fignums())
        save(comparative_chart(context(), {"Japan": 3.54}), tmp_path / "chart.png")
        assert len(plt.get_fignums()) <= before
