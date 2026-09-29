"""TB-08 / TB-27: the bounded investment share and integrability (calibration 1.5.0).

* The bounded share is the written r = 1 - K_R/Y wherever K_R <= Y, and zero past it.
* With it the right-hand side grows at most linearly in the state, and every random draw of
  parameters inside their meaningful ranges and of initial states (real capital far above
  output included) integrates over 60 years at reporting tolerance with every state positive.
  The written share runs into its finite-time singularity on the same kind of draw.
* On real economies whose 1.4.0 fit did not integrate (BR, CH, ES), 1.5.0 fits the window at
  reporting tolerance and projects to 2080 without a log-linear tail, also under random draws of
  the fitted parameters; everything aggregation and cycle read is identical to 1.4.0.
* 1.4.0 and earlier serialise and hash exactly as stored; the new fields appear in 1.5.0 only.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from macrofield import calibration as seeds
from macrofield import projection as P
from macrofield.calibration import V1_4_0, V1_5_0
from macrofield.contracts import RESOLUTION_POLICIES
from macrofield.dynamics import Parameters, derivatives, investment_share, simulate
from macrofield.engine import run_economy

RANGES = V1_5_0.parameter_ranges
REPORTING = V1_5_0.integrator


def constant(value: float):
    return lambda _t: value


def params(p_s: float, p_p: float, p_b: float, alpha: float, stimulus: float) -> Parameters:
    return Parameters(p_s=constant(p_s), p_p=constant(p_p), p_b=constant(p_b),
                      alpha=constant(alpha), stimulus=constant(stimulus))


def rng(name: str):
    b = RANGES[name]
    return st.floats(min_value=b.lower, max_value=b.upper, allow_nan=False)


positive = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False)


# ---------------------------------------------------------------------------
# The share itself
# ---------------------------------------------------------------------------

@given(y=positive, ratio=st.floats(min_value=0.0, max_value=50.0, allow_nan=False))
def test_the_bounded_share_is_the_written_one_up_to_output_and_zero_past_it(y, ratio):
    k_r = ratio * y
    written, bounded = investment_share(y, k_r), investment_share(y, k_r, "bounded")
    if k_r <= y:
        assert bounded == written
    else:
        assert bounded == 0.0 and written < 0.0
    assert 0.0 <= bounded <= 1.0


@given(state=st.tuples(st.floats(min_value=1e-9, max_value=1e3), positive, positive),
       p_s=rng("p_s"), p_p=rng("p_p"), p_b=rng("p_b"), alpha=rng("alpha"),
       stimulus=st.floats(min_value=-10.0, max_value=10.0, allow_nan=False))
def test_the_bounded_right_hand_side_grows_at_most_linearly(state, p_s, p_p, p_b, alpha, stimulus):
    """|f(x)|_1 <= C |x|_1 + 2 |S| with C independent of the state: no finite-time blow-up."""
    f = derivatives(0.0, state, params(p_s, p_p, p_b, alpha, stimulus), share="bounded")
    c = abs(p_b) + 3.0 * p_s + abs(p_p) + 3.0
    assert np.sum(np.abs(f)) <= c * sum(state) * (1 + 1e-12) + 2.0 * abs(stimulus) + 1e-12


def test_the_written_right_hand_side_has_no_such_bound():
    """As Y falls with K_R and K_I held, r K_I grows without limit relative to the state."""
    p = params(0.05, 0.03, 0.01, 0.3, 0.0)
    for y in (1e-2, 1e-4, 1e-6):
        state = (y, 1.0, 1.0)
        written = np.sum(np.abs(derivatives(0.0, state, p))) / sum(state)
        bounded = np.sum(np.abs(derivatives(0.0, state, p, share="bounded"))) / sum(state)
        assert written > 0.4 / y and bounded < 2.0


# ---------------------------------------------------------------------------
# Integrability over random draws
# ---------------------------------------------------------------------------

@settings(max_examples=60, deadline=None)
@given(p_s=rng("p_s"), p_p=rng("p_p"), p_b=rng("p_b"), alpha=rng("alpha"),
       stimulus_share=st.floats(min_value=0.0, max_value=0.15),
       real_ratio=st.floats(min_value=0.2, max_value=3.0),
       financial_ratio=st.floats(min_value=0.01, max_value=10.0))
def test_every_draw_in_range_integrates_60_years_and_stays_positive(
        p_s, p_p, p_b, alpha, stimulus_share, real_ratio, financial_ratio):
    y0 = 1.0
    initial = (y0, real_ratio * y0, financial_ratio * y0)
    t = np.arange(0.0, 61.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        sim = simulate(initial, params(p_s, p_p, p_b, alpha, stimulus_share * y0), (0.0, 60.0),
                       t_eval=t, method=REPORTING.method, rtol=REPORTING.rtol,
                       atol=REPORTING.atol, share="bounded")
    assert sim.success and sim.reached == t.size
    for series in (sim.Y, sim.K_R, sim.K_I):
        assert np.all(np.isfinite(series)) and np.all(series > 0.0)


def test_the_written_share_runs_into_its_singularity_on_a_typical_draw():
    """Real capital outgrows output (p_p + p_s > p_b), passes it, and Y reaches zero."""
    initial = (1.0, 0.9, 0.7)
    p = params(0.05, 0.03, 0.01, 0.3, 0.02)
    t = np.arange(0.0, 61.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        written = simulate(initial, p, (0.0, 60.0), t_eval=t, method=REPORTING.method,
                           rtol=REPORTING.rtol, atol=REPORTING.atol)
        bounded = simulate(initial, p, (0.0, 60.0), t_eval=t, method=REPORTING.method,
                           rtol=REPORTING.rtol, atol=REPORTING.atol, share="bounded")
    assert not (written.success and written.reached == t.size
                and np.all(written.Y > 0.0) and np.all(written.K_I > 0.0))
    assert bounded.success and bounded.reached == t.size and np.all(bounded.Y > 0.0)


def test_parameters_are_held_inside_their_ranges_and_named():
    (p_s, p_p, p_b, alpha), held = P.within_ranges(
        V1_5_0, np.array([0.01]), np.array([-0.04]), np.array([0.08]), np.array([-3.0]))
    assert (p_s[0], p_p[0], p_b[0], alpha[0]) == (RANGES["p_s"].lower, RANGES["p_p"].lower,
                                                  RANGES["p_b"].upper, RANGES["alpha"].lower)
    assert set(held) == {"p_s", "p_p", "p_b", "alpha"} and held["alpha"] == (-3.0, 0.0)
    unchanged, none = P.within_ranges(V1_4_0, np.array([0.01]), np.array([-0.04]),
                                      np.array([0.08]), np.array([-3.0]))
    assert none == {} and unchanged[3][0] == -3.0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_1_4_0_and_earlier_hash_as_stored_and_the_new_fields_are_1_5_0_only():
    assert seeds.calibration_hash(V1_4_0) == "CAL-2e9d7cda67bd4ae4"
    old = json.loads(seeds.canonical_json(V1_4_0))
    new = json.loads(seeds.canonical_json(V1_5_0))
    assert "investment_share" not in old and "parameters_within_ranges" not in old["projection"]
    assert new["investment_share"] == "bounded"
    assert new["projection"]["parameters_within_ranges"] is True
    assert new["contract_version"] == "macrofield-calibration@1.5.0"
    assert V1_4_0.share_form == "as_written" and V1_5_0.share_form == "bounded"
    # Everything else is 1.4.0's: the soft ceiling and the policies (TB-20, confirmed) included.
    for key in ("investment_share", "version", "parent_version", "note", "contract_version"):
        new.pop(key), old.pop(key, None)
    new["projection"].pop("parameters_within_ranges")
    assert new == old


# ---------------------------------------------------------------------------
# Real economies whose 1.4.0 fit does not integrate
# ---------------------------------------------------------------------------

CODES = ("BR", "CH", "ES")
#: What aggregation (inputs.saturation, diagnostics, current) and cycle (observed.Y, years,
#: projection.years) read, and the rest of the observed period except the fit.
DOWNSTREAM = ("status", "years", "dropped_years", "inputs", "observed", "identities",
              "capital_normalisation", "diagnostics", "current", "phase_history")


@pytest.fixture(scope="module")
def states(raw_observations):
    return {(code, v.version): run_economy(v.economy(code), raw_observations[code], v)
            for code in CODES for v in (V1_4_0, V1_5_0)}



@pytest.mark.slow
@pytest.mark.parametrize("code", CODES)
def test_fits_that_did_not_integrate_now_integrate_at_reporting_tolerance(states, code):
    old, new = states[(code, "1.4.0")], states[(code, "1.5.0")]
    assert old.fit.integration_accuracy == "none" and old.simulated is None
    assert new.fit.integration_accuracy == "reporting" and new.simulated is not None
    assert all(np.isfinite(v) for v in new.fit.residuals.values())


@pytest.mark.slow
@pytest.mark.parametrize("code", CODES)
def test_the_projection_integrates_to_2080_and_no_turn_is_in_a_tail(states, code):
    old, new = states[(code, "1.4.0")].projection, states[(code, "1.5.0")].projection
    assert old.integrated_years < old.requested_horizon
    assert new.integrated_years == new.requested_horizon and new.years[-1] == 2080
    assert "extrapolated" not in new.segment and "post_reset_extrapolated" not in new.segment
    assert not any(new.extrapolated)
    for policy in RESOLUTION_POLICIES:
        pr = P.project(states[(code, "1.5.0")], V1_5_0,
                       P.settings_from(V1_5_0, resolution_policy=policy))
        assert not any(t.in_extrapolation for t in pr.turns)


@pytest.mark.slow
@pytest.mark.parametrize("code", CODES)
def test_what_aggregation_and_cycle_read_is_identical_to_1_4_0(states, code):
    old, new = states[(code, "1.4.0")], states[(code, "1.5.0")]
    for name in DOWNSTREAM:
        assert getattr(old, name) == getattr(new, name), name
    assert old.projection.years == new.projection.years
    assert old.fit != new.fit    # the fit does change: 1.5.0 is not activated on this check


@pytest.mark.slow
@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(code=st.sampled_from(CODES), policy=st.sampled_from(RESOLUTION_POLICIES),
       factors=st.lists(st.floats(min_value=0.7, max_value=1.3), min_size=5, max_size=5))
def test_random_draws_of_the_fitted_parameters_integrate_to_the_horizon(states, code, policy,
                                                                          factors):
    e = states[(code, "1.5.0")]
    names = ("p_p_scale", "p_b_scale", "alpha_scale", "savings_scale", "stimulus_scale")
    free = dict(e.fit.free_parameters)
    for name, f in zip(names, factors):
        free[name] = free[name] * f
    drawn = e.model_copy(update={"fit": e.fit.model_copy(update={"free_parameters": free})})
    pr = P.project(drawn, V1_5_0, P.settings_from(V1_5_0, resolution_policy=policy))
    assert pr.status == "ok"
    assert pr.integrated_years == pr.requested_horizon
    assert "extrapolated" not in pr.segment and "post_reset_extrapolated" not in pr.segment
