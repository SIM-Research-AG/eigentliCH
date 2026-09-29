"""Tests for the calibration, section 4.

The fixture is a synthetic trajectory generated from known parameters, which is legitimate here and
nowhere else: these are tests of the fitting machinery, not model inputs, so no published data is
involved and nothing generated here can reach a diagnostic.
"""

from typing import Any

import numpy as np
import pytest

from macrofield.calibration.fit import (
    DIVERGENCE_PENALTY,
    FREE_PARAMETERS,
    IDENTITY_CORRECTIONS,
    CalibrationError,
    ObservedPath,
    calibrate,
    compute_identity_parameters,
)
from macrofield.model.edm import ClosureMode


#: Iteration cap used throughout this module.
#:
#: Far below the production default. Each residual evaluation integrates a stiff system, so a full-effort
#: search costs tens of seconds and this file calls the calibration dozens of times. These tests check the
#: machinery, the bounds and the reporting, none of which need a converged optimum, so the effort is cut
#: here rather than in the production default where it would degrade real results.
TEST_MAX_ITERATIONS = 24


#: A plausible population growth rate, supplied so p_b is a rate rather than the flow ratio.
#:
#: Without it `compute_identity_parameters` falls back to the formula section 0.2 writes, which computes to
#: about 5.65 on this fixture and makes the output equation imply 544 per cent annual growth. That fallback
#: is correct behaviour and is tested for separately; it is simply not the configuration in which the rest
#: of the machinery can be exercised, and the real pipeline always supplies population growth.
TEST_POPULATION_GROWTH = 0.008


def fit(path: ObservedPath, **kwargs) -> Any:
    """Calibrate with the test iteration cap and a population growth series, unless overridden."""
    kwargs.setdefault("max_iterations", TEST_MAX_ITERATIONS)
    kwargs.setdefault(
        "population_growth", np.full(path.length, TEST_POPULATION_GROWTH)
    )
    return calibrate("test", path, **kwargs)


def balanced_path(periods: int = 14, growth: float = 0.03, start: int = 2000) -> ObservedPath:
    """A single-rate trajectory with real capital equal to output, so the investment share is zero.

    Note that this is *not* internally consistent with the section 0.2 definitions, and it cannot be:
    on this path the definitions give p_p near 0.06 while p_b is near 0.95, which no trajectory
    satisfies simultaneously. That is the over-determination, and it is why the calibration carries
    multiplicative corrections on the identity paths. See FREE_PARAMETERS.
    """
    years = np.arange(start, start + periods)
    factor = np.exp(growth * (years - years[0]))
    return ObservedPath(
        periods=years,
        output=100.0 * factor,
        real_capital=100.0 * factor,
        financial_capital=210.0 * factor,
        savings_rate=np.full(periods, 0.21),
        stimulus_proxy=np.zeros(periods),
    )


def realistic_path(periods: int = 30, start: int = 1995) -> ObservedPath:
    """A late-cycle trajectory with real capital above output and financial capital growing faster."""
    years = np.arange(start, start + periods)
    t = years - years[0]
    return ObservedPath(
        periods=years,
        output=100.0 * np.exp(0.022 * t),
        real_capital=320.0 * np.exp(0.019 * t),
        financial_capital=250.0 * np.exp(0.041 * t),
        savings_rate=np.full(periods, 0.21),
        stimulus_proxy=3.0 * np.exp(0.02 * t),
    )


class TestObservedPath:
    def test_accepts_a_well_formed_path(self):
        assert balanced_path().length == 14

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(CalibrationError, match="share a length"):
            ObservedPath(
                periods=np.arange(2000, 2010),
                output=np.ones(10),
                real_capital=np.ones(9),
                financial_capital=np.ones(10),
                savings_rate=np.ones(10),
                stimulus_proxy=np.ones(10),
            )

    def test_rejects_too_short_a_window(self):
        with pytest.raises(CalibrationError, match="at least five periods"):
            ObservedPath(
                periods=np.arange(2000, 2003),
                output=np.ones(3),
                real_capital=np.ones(3),
                financial_capital=np.ones(3),
                savings_rate=np.ones(3),
                stimulus_proxy=np.ones(3),
            )

    def test_rejects_gaps(self):
        """Gaps belong to the data layer, where they are reported."""
        output = np.ones(10)
        output[3] = np.nan
        with pytest.raises(CalibrationError, match="contains gaps"):
            ObservedPath(
                periods=np.arange(2000, 2010),
                output=output,
                real_capital=np.ones(10),
                financial_capital=np.ones(10),
                savings_rate=np.ones(10),
                stimulus_proxy=np.ones(10),
            )

    def test_rejects_non_positive_states(self):
        with pytest.raises(CalibrationError, match="strictly positive"):
            ObservedPath(
                periods=np.arange(2000, 2010),
                output=np.zeros(10),
                real_capital=np.ones(10),
                financial_capital=np.ones(10),
                savings_rate=np.ones(10),
                stimulus_proxy=np.ones(10),
            )

    def test_time_is_measured_from_the_window_start(self):
        path = balanced_path(start=1980)
        assert path.time[0] == 0.0
        assert path.time[-1] == pytest.approx(13.0)


class TestIdentityParameters:
    def test_investment_share_matches_its_definition(self):
        path = realistic_path()
        identities = compute_identity_parameters(path)
        expected = 1.0 - path.real_capital / path.output
        assert np.allclose(identities.r, expected)

    def test_investment_share_is_negative_for_a_financial_economy(self):
        """Real capital above output means r < 0, which is the sign flip that drives Phase IV."""
        identities = compute_identity_parameters(realistic_path())
        assert np.all(identities.r < 0.0)

    def test_recovers_a_known_growth_rate(self):
        path = balanced_path(growth=0.03)
        identities = compute_identity_parameters(path)
        # Y_dot / Y must equal the injected growth rate.
        implied = identities.output_growth / path.output
        # Interior points only. Savitzky-Golay fits a local polynomial, which has a known bias at the
        # window edges, and the brief requires smoothing, so the edge bias is a cost that comes with it.
        assert np.allclose(implied[3:-3], 0.03, rtol=1e-3)

    def test_the_smoothing_bias_is_confined_to_the_edges(self):
        """Recorded because an edge artefact in a derivative propagates into p_p, p_b and alpha, and
        therefore into the first and last periods of every calibration."""
        identities = compute_identity_parameters(balanced_path(growth=0.03))
        implied = identities.output_growth / balanced_path(growth=0.03).output
        interior_error = float(np.max(np.abs(implied[3:-3] / 0.03 - 1.0)))
        edge_error = float(np.max(np.abs(implied[[0, -1]] / 0.03 - 1.0)))
        assert edge_error > interior_error

    def test_p_p_follows_its_definition(self):
        path = realistic_path()
        identities = compute_identity_parameters(path)
        expected = (identities.output_growth + identities.real_capital_growth) / path.real_capital
        assert np.allclose(identities.p_p, expected)

    def test_smoothing_choice_is_recorded(self):
        identities = compute_identity_parameters(realistic_path(), window_years=7)
        assert identities.smoothing["window_years"] == 7
        assert "propagates" in identities.smoothing["note"]

    def test_smoothing_window_changes_the_parameters(self):
        """Recorded because it is the reason the choice must be documented rather than defaulted."""
        path = realistic_path()
        narrow = compute_identity_parameters(path, window_years=5)
        wide = compute_identity_parameters(path, window_years=11)
        assert not np.allclose(narrow.p_p, wide.p_p)


class TestCalibrate:
    def test_the_calibration_completes_and_integrates(self):
        """The machinery must produce a usable path, which is a lower bar than fitting it well and is
        the bar that matters for the pipeline. Fit quality is a finding, tested separately below."""
        result = fit(balanced_path())
        assert result.simulated["Y"].size == balanced_path().length
        assert all(np.isfinite(v) for v in result.residuals_by_series.values())

    def test_reports_every_free_parameter(self):
        result = fit(balanced_path())
        assert set(result.free_parameters) == set(FREE_PARAMETERS)
        assert set(result.standard_errors) == set(FREE_PARAMETERS)
        assert set(result.identifiability) == set(FREE_PARAMETERS)

    def test_initial_state_stays_near_the_observation(self):
        """Calibrating to an observed trajectory means the initial state is not a free-for-all."""
        path = balanced_path()
        result = fit(path)
        assert result.free_parameters["initial_output"] == pytest.approx(path.output[0], rel=0.5)

    def test_reports_per_series_residuals(self):
        result = fit(balanced_path())
        assert set(result.residuals_by_series) == {"Y", "K_R", "K_I"}
        assert all(np.isfinite(v) for v in result.residuals_by_series.values())

    def test_identifiability_verdict_is_explanatory(self):
        result = fit(balanced_path())
        for name, verdict in result.identifiability.items():
            assert any(
                token in verdict
                for token in ("identified", "not identified", "undefined")
            ), (name, verdict)

    def test_weakly_identified_parameters_are_flagged_and_noted(self):
        result = fit(balanced_path())
        if result.weakly_identified:
            assert any("weakly identified" in note for note in result.notes)

    def test_report_is_serialisable_and_complete(self):
        report = fit(balanced_path()).report()
        for key in (
            "economy",
            "window",
            "converged",
            "fit_quality",
            "free_parameters",
            "weakly_identified",
            "identity_diagnostics",
            "derivative_smoothing",
            "notes",
        ):
            assert key in report
        assert report["window"]["periods"] == 14

    def test_records_the_smoothing_used(self):
        report = fit(balanced_path(), window_years=9).report()
        assert report["derivative_smoothing"]["window_years"] == 9


class TestFitQualityIsAFinding:
    """The model as specified does not fit an observed *level* closely, and that is a result about the
    model rather than a defect in the fitting code.

    Note what this class does and does not claim. Level residual is the **secondary** criterion. The
    model is judged primarily on trend and turning points, in `tests/test_validate.py`, because a path
    with the right turns and the wrong level is useful while the reverse is worse than useless. These
    tests exist to pin the level finding so it cannot be quietly lost, and so that a change which
    genuinely alters it shows up here and gets investigated rather than absorbed.
    """

    def test_the_fit_is_imperfect_but_bounded(self):
        """The level fit is imperfect, and that is expected rather than alarming.

        History worth keeping, because this assertion has already earned its place twice. It originally
        asserted the fit was *poor* (above 0.05) as a guard against the finding being quietly lost. It then
        fired, correctly, when three changes genuinely improved matters: taking p_b from population growth
        rather than the dimensionally inconsistent flow ratio, grading the divergence penalty so the
        optimiser has a gradient out of the infeasible region, and bounding every parameter to its
        economically meaningful range. On real United States data the level residual fell from about 1e47
        to 0.30.

        So the assertion now brackets rather than floors: the fit should be neither perfect (which would
        suggest the structural tension had vanished, and that would need explaining) nor explosive.
        """
        result = fit(balanced_path())
        assert result.fit_quality > 1e-6, (
            "a near-perfect fit would mean the over-determination documented in FREE_PARAMETERS had gone "
            "away. Investigate rather than relaxing this assertion."
        )

    def test_the_residual_is_bounded_rather_than_explosive(self):
        """Poor is not the same as unbounded, and the distinction is the whole point of fitting in log
        space.

        Measured at about 6.5 on this fixture. Before the log-space change the same fit reached a
        relative residual of order 1e9, because the identity value of p_b against the observed savings
        rate implies roughly 74 per cent annual output growth. The bound here is set well above the
        measured value and far below the explosive one, so it catches a regression to the old behaviour
        without pinning a number that ordinary tuning would trip.
        """
        result = fit(balanced_path())
        assert result.fit_quality < 25.0

    def test_the_report_carries_the_fit_quality_so_it_cannot_be_overlooked(self):
        report = fit(balanced_path()).report()
        assert "mean_relative_residual" in report["fit_quality"]
        assert report["fit_quality"]["mean_relative_residual"] > 0.0


class TestIdentityCorrections:
    """The corrections that make the calibration possible, and what their size means."""

    def test_corrections_are_part_of_the_free_parameters(self):
        for name in IDENTITY_CORRECTIONS:
            assert name in FREE_PARAMETERS

    def test_the_departure_from_one_is_reported(self):
        result = fit(balanced_path())
        departures = result.identity_diagnostics.get("identity_correction_departures")
        assert departures is not None
        assert set(departures) == set(IDENTITY_CORRECTIONS)

    def test_the_worst_correction_is_named(self):
        result = fit(balanced_path())
        assert result.identity_diagnostics["worst_identity_correction"] in IDENTITY_CORRECTIONS

    def test_a_material_departure_is_explained(self):
        result = fit(balanced_path())
        departure = result.identity_diagnostics["worst_identity_correction_departure"]
        if departure > 0.10:
            assert any("definitions of section" in note for note in result.notes)
        else:
            assert any("close to consistent" in note for note in result.notes)

    def test_the_fixture_really_is_over_determined(self):
        """Pins the reason the corrections exist: the definitions disagree on this path."""
        identities = compute_identity_parameters(balanced_path())
        middle = len(identities.p_p) // 2
        assert not np.isclose(identities.p_p[middle], identities.p_b[middle], rtol=0.5)


class TestOverDeterminationIsReportedNotEnforced:
    def test_identity_residuals_are_reported(self):
        result = fit(balanced_path())
        if result.simulated["Y"].size:
            assert any("residual" in key for key in result.identity_diagnostics)

    def test_negative_implied_growth_is_explained_not_treated_as_a_finding(self):
        """For a production economy the p_p identity forces contraction. The calibration must say that
        this is the over-determination rather than a claim about the economy."""
        result = fit(balanced_path())
        implied = result.identity_diagnostics.get("p_p_identity_implied_mean_output_growth")
        if implied is not None and implied < 0.0:
            assert any("over-determination" in note for note in result.notes)

    def test_calibration_succeeds_despite_the_identity_residual(self):
        """The point: the identity is a diagnostic, so a large residual must not block the fit.

        Asserted as "a usable path was produced" rather than "the optimiser converged", because these
        tests run under a deliberately low iteration cap and therefore stop on the cap rather than on a
        convergence criterion. Convergence is a property of the search budget; not being blocked is the
        property this test is about.
        """
        result = fit(balanced_path())
        assert result.simulated["Y"].size == balanced_path().length
        assert np.isfinite(result.fit_quality)


class TestDivergenceIsScoredNotRaised:
    def test_a_diverging_path_produces_a_finite_result(self):
        """The finite-time singularity must present as a bad score, so the optimiser can move away from
        it, rather than crashing the calibration."""
        result = fit(realistic_path())
        # Whether or not a fitting set was found, the call must return rather than raise.
        assert isinstance(result.fit_quality, float)
        assert set(result.free_parameters) == set(FREE_PARAMETERS)

    def test_a_failed_integration_is_explained_in_the_notes(self):
        result = fit(realistic_path())
        if not result.simulated["Y"].size:
            assert any("singularity" in note for note in result.notes)
            assert all(np.isinf(v) for v in result.residuals_by_series.values())

    def test_the_penalty_is_finite(self):
        """An infinite penalty would stop the optimiser computing a gradient."""
        assert np.isfinite(DIVERGENCE_PENALTY)
        assert DIVERGENCE_PENALTY > 1.0


class TestClosureModes:
    @pytest.mark.parametrize("closure", list(ClosureMode))
    def test_both_closures_calibrate(self, closure):
        result = fit(balanced_path(), closure=closure)
        assert set(result.free_parameters) == set(FREE_PARAMETERS)

    def test_two_body_residual_stays_negligible(self):
        """The identity is exact by construction, so the fitted path must not drift from it."""
        result = fit(balanced_path())
        assert result.two_body_worst < 1e-6


class TestReproducibility:
    def test_the_same_inputs_give_the_same_answer(self):
        first = fit(balanced_path())
        second = fit(balanced_path())
        assert first.free_parameters == second.free_parameters
        assert first.residuals_by_series == second.residuals_by_series


