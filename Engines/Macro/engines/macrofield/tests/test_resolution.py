"""R-005: the soft saturation ceiling, the four resolution policies, crisis, reset, 2080.

* The policies reproduce ``Scenario_SAA.m`` (frozen in ``golden/scenario_saa/scenario_saa.json`` by
  ``dev/freeze_scenario_saa.py``): parameters exactly, the monthly inflation, defaults and
  valuations paths to 1e-15, and the ids Engine 09 (``scenario``) is to use.
* The ceiling bends the path and never lets it above the band, for any start and growth path
  (property test) and for random draws of the fitted parameters of real economies.
* Calibration 1.4.0 leaves every observed-period output unchanged against 1.3.0, and earlier
  calibrations and artefacts serialise exactly as before the new fields existed.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from macrofield import calibration as seeds
from macrofield import projection as P
from macrofield import resolution
from macrofield.calibration import V1_3_0, V1_4_0
from macrofield.contracts import RESOLUTION_POLICIES, Projection
from macrofield.engine import run_economy

from .conftest import GOLDEN

SAA = GOLDEN / "scenario_saa"
G = json.loads((SAA / "scenario_saa.json").read_text(encoding="utf-8"))
CRISIS = V1_4_0.projection.crisis
CEILING = V1_4_0.projection.saturation_ceiling


# ---------------------------------------------------------------------------
# Scenario_SAA.m, frozen
# ---------------------------------------------------------------------------

def test_the_golden_copy_is_the_frozen_template():
    assert hashlib.sha256((SAA / "Scenario_SAA.m").read_bytes()).hexdigest() == G["sha256"]
    assert G["months"] == CRISIS.months == 60


def test_policy_ids_are_the_templates_four_cases():
    assert tuple(G["policies"]) == RESOLUTION_POLICIES == tuple(CRISIS.policies)
    assert [G["policies"][p]["case"] for p in RESOLUTION_POLICIES] == [1, 2, 3, 4]


@pytest.mark.parametrize("pid", RESOLUTION_POLICIES)
def test_policy_parameters_are_the_templates_literals(pid):
    g, spec = G["policies"][pid], CRISIS.policies[pid]
    assert list(spec.target_mix) == g["target_mix"]
    inf, gp = spec.inflation, g["inflation_parameters"]
    form = {"sigmoid_reversed": ("sigmoid", True), "sigmoid": ("sigmoid", False),
            "exponential": ("exponential", False), "hump": ("hump", False)}[g["inflation_form"]]
    assert (inf.form, inf.reverse) == form
    if inf.form == "sigmoid":
        assert (inf.start, inf.end, inf.midpoint, inf.steepness) == (
            gp["startVal"], gp["endVal"], gp["midpoint"], gp["steepness"])
    elif inf.form == "exponential":
        assert (inf.start, inf.end, inf.power) == (gp["startVal"], gp["endVal"], gp["power"])
    else:
        assert (inf.start, inf.end, inf.midpoint, inf.width_divisor) == (
            gp["startVal"], gp["peakVal"], gp["peakPosition"], 2.5)
    d, gd = spec.defaults, g["defaults_parameters"]
    if gd is None:                                   # defaults = ones(size(times))
        assert d.start == d.end == 1.0
    else:
        assert (d.start, d.end, d.inflection, d.steepness, d.first_leg_share) == (
            gd["startVal"], gd["endVal"], gd["inflectionPoint"], gd["steepness"], 0.3)
    v, gv = spec.valuations, g["valuations_parameters"]
    assert (v.start, v.end, v.ramp_months) == (gv["start"], gv["end"], gv["ramp_months"])


@pytest.mark.parametrize("pid", RESOLUTION_POLICIES)
def test_policy_paths_reproduce_the_template(pid):
    got = resolution.paths(CRISIS.policies[pid], CRISIS.months)
    for name in ("inflation", "defaults", "valuations"):
        np.testing.assert_allclose(got[name], G["policies"][pid][name], rtol=0.0, atol=1e-15)
    price = np.cumprod((1.0 + np.asarray(G["policies"][pid]["inflation"])) ** (1.0 / 12.0))
    np.testing.assert_allclose(got["price_level"], price, rtol=1e-15)


def test_template_endpoints_as_the_review_states_them():
    p = {k: resolution.paths(CRISIS.policies[k], 60) for k in RESOLUTION_POLICIES}
    assert p["depression"]["inflation"][0] == pytest.approx(0.02, abs=1e-4)
    assert p["depression"]["inflation"][-1] == pytest.approx(-0.04, abs=1e-4)
    assert p["depression"]["defaults"][-1] == pytest.approx(0.6)
    assert np.all(p["depression"]["valuations"][29:] == 0.5)
    assert p["hyperinflation"]["inflation"][0] == pytest.approx(0.2)
    assert p["hyperinflation"]["inflation"][-1] == pytest.approx(1.0)
    assert np.all(p["hyperinflation"]["defaults"] == 1.0) and np.all(p["hyperinflation"]["valuations"] == 1.0)
    assert p["stagflation"]["inflation"][-1] == pytest.approx(0.10, abs=1e-3)
    assert p["stagflation"]["defaults"][-1] == pytest.approx(0.8) and p["stagflation"]["valuations"][19] == 0.7
    assert max(p["deferral"]["inflation"]) == pytest.approx(0.06, abs=1e-3)
    assert p["deferral"]["defaults"][-1] == pytest.approx(0.9) and p["deferral"]["valuations"][49] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# the soft ceiling
# ---------------------------------------------------------------------------

growth = st.floats(min_value=-0.3, max_value=3.0, allow_nan=False, allow_infinity=False)


@settings(max_examples=400, deadline=None)
@given(start=st.floats(min_value=0.2, max_value=CEILING.upper), steps=st.lists(growth, min_size=1, max_size=60),
       position=st.floats(min_value=0.0, max_value=1.0))
def test_the_ceiling_bends_and_never_lets_the_path_above_its_turn_level(start, steps, position):
    level = CEILING.turn_level(position)
    raw = start * np.exp(np.cumsum(steps))
    bent, turn = P.bend(start, raw, CEILING.damping_onset, level)
    assert np.all(np.isfinite(bent)) and np.all(bent > 0)
    assert bent.max() <= max(level, start) * (1 + 1e-12) <= CEILING.upper * (1 + 1e-12)
    if turn is not None:
        assert len(bent) == turn + 1
        assert bent[-1] == pytest.approx(level) or start >= level
    else:
        assert len(bent) == len(raw)
    # Damped, never amplified: each year's rise is at most the unbounded one.
    x = np.log(np.concatenate(([start], bent)))
    assert np.all(np.diff(x) <= np.asarray(steps[:len(bent)]) + 1e-12)


def test_the_ceiling_arrives_with_zero_slope_rather_than_a_kink():
    raw = 3.0 * np.exp(0.02 * np.arange(1, 200))
    bent, turn = P.bend(3.0, raw, CEILING.damping_onset, 5.0)
    assert turn is not None and bent[-1] == pytest.approx(5.0)
    g = np.diff(np.log(bent))
    assert g[-2] < 0.25 * 0.02                     # the last full year rises at a quarter of the pace
    assert np.all(np.diff(g[np.log(bent[1:]) > math.log(3.6)]) <= 1e-12)   # growth only slows


# ---------------------------------------------------------------------------
# real economies under 1.4.0
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def states(raw_observations):
    """US (integrates) and CH (weak evidence, runs into the singularity), under 1.3.0 and 1.4.0."""
    return {(code, v.version): run_economy(v.economy(code), raw_observations[code], v)
            for code in ("US", "CH") for v in (V1_3_0, V1_4_0)}


def test_observed_period_outputs_are_identical_to_1_3_0(states):
    for code in ("US", "CH"):
        old = states[(code, "1.3.0")].model_dump(mode="json", exclude={"projection"})
        new = states[(code, "1.4.0")].model_dump(mode="json", exclude={"projection"})
        assert old == new


def test_the_default_1_4_0_projection_runs_to_2080_and_is_labelled(states):
    pr = states[("CH", "1.4.0")].projection
    assert pr.status == "ok" and pr.years[-1] == 2080 and pr.display_until == 2039
    assert pr.resolution_policy == CRISIS.default_policy
    assert max(pr.saturation) <= CEILING.upper
    assert pr.lower_confidence == tuple(y > 2039 for y in pr.years)
    t = pr.turns[0]
    assert CEILING.lower <= t.level <= CEILING.upper and t.reset_years == 35
    i = pr.years.index(t.year)
    crisis = [k for k, s in enumerate(pr.segment) if s == "crisis"]
    reset = [k for k, s in enumerate(pr.segment) if s == "reset"]
    assert crisis == list(range(i + 1, i + 6)) and reset == list(range(i + 6, i + 41))
    assert all(pr.phase[k] == 4 for k in crisis + reset)
    assert all(not pr.extrapolated[k] for k in crisis + reset)             # not extrapolation
    assert all(pr.segment_label[k] == f"crisis and reset ({pr.resolution_policy})" for k in crisis + reset)
    assert all(label is None for label in pr.segment_label[:i + 1])
    assert pr.saturation[reset[-1]] == pytest.approx(t.reset_target)
    post = [k for k, s in enumerate(pr.segment) if s.startswith("post_reset")]
    assert post and pr.phase[post[0]] == 1                                 # 4, the reset, then 1
    assert {s.name for s in pr.scenarios} == set(RESOLUTION_POLICIES)
    for sc in pr.scenarios:
        assert sc.turn is not None and len(sc.inflation) == len(sc.defaults) == 60
        assert max(sc.saturation) <= CEILING.upper


def test_policies_turn_at_their_own_place_in_the_band(states):
    e = states[("CH", "1.4.0")]
    levels = {}
    for pid in RESOLUTION_POLICIES:
        pr = P.project(e, V1_4_0, P.settings_from(V1_4_0, resolution_policy=pid))
        levels[pid] = pr.turns[0].level
        assert pr.turns[0].policy == pid and pr.resolution_policy == pid
    assert levels["depression"] < levels["stagflation"] < levels["hyperinflation"] < levels["deferral"]
    assert levels["deferral"] <= CEILING.upper and levels["depression"] >= CEILING.lower


def test_a_1_3_0_projection_serialises_without_the_new_fields(states):
    dumped = states[("US", "1.3.0")].projection.model_dump(mode="json")
    for key in ("resolution_policy", "segment", "segment_label", "lower_confidence", "turns",
                "ceiling", "display_until", "unbounded_saturation"):
        assert key not in dumped
    assert Projection.model_validate(dumped) == states[("US", "1.3.0")].projection


def test_earlier_calibrations_hash_exactly_as_stored():
    assert {c.version: seeds.calibration_hash(c) for c in seeds.SEEDS[:4]} == {
        "1.0.0": "CAL-14bb78d4a370c1a9", "1.1.0": "CAL-9291eec75a1c576c",
        "1.2.0": "CAL-1c56efc28c55f75a", "1.3.0": "CAL-67f0a5716a41b2d6"}
    assert "crisis" not in json.loads(seeds.canonical_json(V1_3_0))["projection"]


def test_a_reset_override_needs_a_reason_and_is_used(states):
    from macrofield.contracts import ResetOverride

    with pytest.raises(ValueError):
        ResetOverride(level=1.5, reason="")
    reset = CRISIS.reset.model_copy(update={"overrides": {"CH": ResetOverride(
        level=1.5, years=30, reason="test: a shallower reset")}})
    cal = V1_4_0.model_copy(update={"projection": V1_4_0.projection.model_copy(update={
        "crisis": CRISIS.model_copy(update={"reset": reset})})})
    pr = P.project(states[("CH", "1.4.0")], cal, P.settings_from(cal))
    t = pr.turns[0]
    assert t.reset_years == 30 and t.reset_target == pytest.approx(1.5)
    assert "test: a shallower reset" in t.reset_target_source


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(code=st.sampled_from(["US", "CH"]), policy=st.sampled_from(RESOLUTION_POLICIES),
       factors=st.lists(st.floats(min_value=0.7, max_value=1.3), min_size=5, max_size=5))
def test_random_parameter_draws_stay_inside_the_band(states, code, policy, factors):
    e = states[(code, "1.4.0")]
    names = ("p_p_scale", "p_b_scale", "alpha_scale", "savings_scale", "stimulus_scale")
    free = dict(e.fit.free_parameters)
    for name, f in zip(names, factors):
        free[name] = free[name] * f
    drawn = e.model_copy(update={"fit": e.fit.model_copy(update={"free_parameters": free})})
    pr = P.project(drawn, V1_4_0, P.settings_from(V1_4_0, resolution_policy=policy))
    assert pr.status == "ok"
    assert max(pr.saturation) <= CEILING.upper * (1 + 1e-12)
    for t in pr.turns:
        assert CEILING.lower <= t.level <= CEILING.upper
    for sc in pr.scenarios:
        assert not sc.saturation or max(sc.saturation) <= CEILING.upper * (1 + 1e-12)
