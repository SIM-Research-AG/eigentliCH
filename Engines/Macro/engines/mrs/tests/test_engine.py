"""Unit and property tests on the pure model: segments to distribution, and the assembly.

Properties: every distribution sums to 1; states are valid; the same inputs always give the
same output; a higher reading never reads more aggressive; a gap is never read as a number;
the output validates against ``mrs-signal@1.0.0``.
"""

from __future__ import annotations

import calendar
import json
import math

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from mrs import calibration as seeds
from mrs.contracts import (INDICATORS, N_STATES, SEGMENTS, Calibration, MarketRiskSignal,
                           MRSRunRequest, Provenance)
from mrs.engine import (EconomyInput, EngineError, assess, binomial_pmf, column_for, grid,
                        kernel_matrix, modal_state, run_model)
from mrs.indicators import series_needed

CAL = seeds.PRODUCTION

maybe_reading = st.one_of(st.none(), st.floats(min_value=-8, max_value=8, allow_nan=False))


def mean_state(dist) -> float:
    return float(np.dot(np.arange(1, N_STATES + 1), dist))


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------

def test_binomial_pmf_sums_to_one():
    assert math.fsum(binomial_pmf(8, 0.5)) == pytest.approx(1.0, abs=1e-15)
    assert math.fsum(binomial_pmf(8, 0.1)) == pytest.approx(1.0, abs=1e-15)


@pytest.mark.parametrize("name", ["business_cycle", "investment", "market_behaviour"])
def test_band_columns_each_carry_unit_mass_and_move_cautious(name):
    k = kernel_matrix(CAL.segment(name), 11)
    np.testing.assert_allclose(k.sum(axis=0), 1.0, atol=1e-15)
    means = [mean_state(k[:, j]) for j in range(11)]
    assert all(b < a for a, b in zip(means, means[1:])), "higher column must be more cautious"
    assert means[0] > 20 and means[-1] < 4


def test_stress_tail_is_off_then_rises_on_the_cautious_states():
    k = kernel_matrix(CAL.segment("market_stress"), 11)
    assert np.all(k[:, :5] == 0.0)
    mass = k.sum(axis=0)
    assert all(b > a for a, b in zip(mass[5:], mass[6:]))
    assert mass[5] == pytest.approx(1 / 11) and mass[10] == pytest.approx(6 ** math.sqrt(2) / 11)
    assert np.all(k[9:, :] == 0.0), "the tail lives on states 1 to 9"


def test_column_bounds_at_zero_shift():
    edges = grid(CAL)
    assert column_for(-100.0, edges) == 1
    assert column_for(100.0, edges) == 11
    assert column_for(float(edges[5]) + 1e-9, edges) == 6
    # A stress reading of exactly 0 opens column 6, the first with the tail on (ruled: keep).
    assert column_for(0.0, edges) == 6


def test_modal_state_breaks_ties_cautious():
    d = np.zeros(N_STATES)
    d[[4, 20]] = 0.5
    assert modal_state(d) == 5


# ---------------------------------------------------------------------------
# One economy: properties
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None)
@given(data=st.lists(st.tuples(*(maybe_reading,) * 4), min_size=1, max_size=12))
def test_distributions_sum_to_one_and_states_are_valid(data):
    signals = {seg: [row[i] for row in data] for i, seg in enumerate(SEGMENTS)}
    a = assess(signals, len(data), CAL)
    for t, row in enumerate(data):
        present = sum(v is not None for v in row)
        if a.state[t] is None:
            assert a.distribution[t] is None and a.raw_mass[t] is None
            assert present < CAL.min_segments
            continue
        d = a.distribution[t]
        assert len(d) == N_STATES and min(d) >= 0.0
        assert abs(math.fsum(d) - 1.0) <= 1e-12
        assert 1 <= a.state[t] <= N_STATES
        assert a.state[t] == modal_state(np.array(d))
    for i, seg in enumerate(SEGMENTS):
        assert a.segment_gaps[seg] == sum(row[i] is None for row in data)
        assert all((c is None) == (row[i] is None) for c, row in zip(a.columns[seg], data))


@settings(max_examples=100, deadline=None)
@given(data=st.lists(st.tuples(*(maybe_reading,) * 4), min_size=1, max_size=8))
def test_deterministic(data):
    signals = {seg: [row[i] for row in data] for i, seg in enumerate(SEGMENTS)}
    a = assess(signals, len(data), CAL)
    b = assess(signals, len(data), CAL)
    assert a.distribution == b.distribution and a.state == b.state and a.columns == b.columns


@settings(max_examples=200, deadline=None)
@given(base=st.tuples(*(st.floats(-4, 4),) * 4), segment=st.sampled_from(SEGMENTS),
       bump=st.floats(0.0, 4.0))
def test_higher_readings_never_read_more_aggressive(base, segment, bump):
    """Every segment is oriented so a higher reading means more risk: raising any one of
    them never raises the expected state."""
    readings = dict(zip(SEGMENTS, base))
    lo = assess({k: [v] for k, v in readings.items()}, 1, CAL)
    readings[segment] += bump
    hi = assess({k: [v] for k, v in readings.items()}, 1, CAL)
    assert mean_state(hi.distribution[0]) <= mean_state(lo.distribution[0]) + 1e-12


def test_a_gap_is_reweighted_not_read_as_a_number():
    full = {"business_cycle": [0.5], "investment": [0.5], "market_behaviour": [-1.0],
            "market_stress": [2.5]}
    gap = dict(full, investment=[None])
    a = assess(gap, 1, CAL)
    assert a.segment_gaps["investment"] == 1 and a.columns["investment"] == (None,)
    edges = grid(CAL)
    expected = sum(kernel_matrix(CAL.segment(s), 11)[:, column_for(full[s][0], edges) - 1]
                   * CAL.segment(s).weight
                   for s in ("business_cycle", "market_behaviour", "market_stress")) / 0.75
    np.testing.assert_allclose(np.array(a.distribution[0]) * a.raw_mass[0], expected, atol=1e-15)
    zero = assess(dict(full, investment=[0.0]), 1, CAL)
    assert zero.distribution[0] != a.distribution[0]


def test_nan_is_a_gap_too():
    a = assess({"business_cycle": [math.nan], "investment": [0.1], "market_behaviour": [0.1],
                "market_stress": [0.1]}, 1, CAL)
    assert a.segment_gaps["business_cycle"] == 1 and a.columns["business_cycle"] == (None,)


def test_too_few_segments_leaves_the_date_unassessed():
    a = assess({"business_cycle": [0.1], "investment": [None], "market_behaviour": [None],
                "market_stress": [0.0]}, 1, CAL)
    assert a.state == (None,) and a.dates_unassessed == 1


def test_fail_policy_raises():
    cal = Calibration.model_validate({**CAL.model_dump(), "version": "9.0.0", "missing_policy": "fail"})
    with pytest.raises(EngineError, match="no reading"):
        assess({"business_cycle": [None], "investment": [0.0], "market_behaviour": [0.0],
                "market_stress": [0.0]}, 1, cal)


def test_matlab_policy_reads_a_gap_as_column_one():
    a = assess({"business_cycle": [None], "investment": [0.0], "market_behaviour": [0.0],
                "market_stress": [0.0]}, 1, seeds.MATLAB)
    assert a.columns["business_cycle"] == (1,) and a.state[0] is not None


# ---------------------------------------------------------------------------
# The whole model
# ---------------------------------------------------------------------------

def month_ends(n: int, year: int = 2020) -> list[str]:
    out = []
    for i in range(n):
        y, m = year + i // 12, 1 + i % 12
        out.append(f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}")
    return out


def synthetic(n: int = 60, codes=("US", "CH"), gaps: bool = True) -> list[EconomyInput]:
    """Random-walk inputs for every series the production calibration reads."""
    rng = np.random.default_rng(7)
    out = []
    for code in codes:
        series = {}
        for sid in series_needed(CAL.indicators):
            x = 100.0 + np.cumsum(rng.normal(0, 1, n))
            if sid in ("fx.ois_1y", "yields.govt_10y", "yields.govt_2y", "volatility.implied"):
                x = np.abs(x) / 2000.0
            series[sid] = x
        if gaps and code == "CH":
            series["yields.high_yield_ytw"] = np.full(n, np.nan)     # no HY data at all
            series["equity.total_return"][30:33] = np.nan             # an interior gap
        out.append(EconomyInput(code=code, name=f"name of {code}", series=series))
    return out


@pytest.fixture(scope="module")
def output():
    return run_model(month_ends(60), synthetic(), CAL)


def _signal(output, dates) -> MarketRiskSignal:
    prov = Provenance(snapshot_id="s", as_of=dates[-1], upstream={"datafeed": "x"},
                      engine_version="mrs@1.0.0", contract_versions={},
                      calibration_version=CAL.version, calibration_hash="CAL-x",
                      idempotency_key="IDK-x")
    return MarketRiskSignal(artefact_id="MRS-0123456789abcdef", dates=dates,
                            economies=output.economies, coverage=output.coverage,
                            provenance=prov)


def test_output_validates_and_is_json(output):
    dates = month_ends(60)
    s = _signal(output, dates)
    again = MarketRiskSignal.model_validate_json(s.model_dump_json())
    assert again == s and s.provenance.regime_id is None
    blob = json.loads(s.model_dump_json())
    assert blob["contract_version"] == "mrs-signal@1.0.0" and blob["n_states"] == 25
    assert blob["indicator_names"] == list(INDICATORS) and blob["segment_names"] == list(SEGMENTS)
    assert "NaN" not in s.model_dump_json()


def test_production_warm_up_and_coverage(output):
    cov = {e.code: e for e in output.coverage.economies}
    us = output.economies[0]
    assert us.name == "name of US"
    # 24 months for inputs, then 12 for the indicator, then 12 for the segment.
    assert us.segments["business_cycle"][:24 + 12 + 12 - 3] == (None,) * 45
    assert cov["US"].first_assessed is not None and cov["US"].dates_unassessed > 0
    assert cov["CH"].inputs_missing == ("yields.high_yield_ytw",)
    assert cov["CH"].indicator_gaps["trend_osc"] > cov["US"].indicator_gaps["trend_osc"]
    assert output.coverage.indicator_mode == "production"
    for e in output.economies:
        for t, s in enumerate(e.state):
            present = sum(e.segments[k][t] is not None for k in SEGMENTS)
            assert (s is not None) == (present >= CAL.min_segments)


def test_contract_rejects_bad_payloads(output):
    dates = month_ends(60)
    s = _signal(output, dates)
    e = s.economies[0]
    t = next(i for i, d in enumerate(e.distribution) if d is not None)
    bad = list(e.distribution)
    bad[t] = tuple(p * 1.01 for p in bad[t])
    broken = e.model_copy(update={"distribution": tuple(bad)})
    with pytest.raises(ValidationError, match="sum to 1"):
        MarketRiskSignal.model_validate({**s.model_dump(), "economies": [broken.model_dump()]})
    with pytest.raises(ValidationError, match="16 hex"):
        MarketRiskSignal.model_validate({**s.model_dump(), "artefact_id": "RGM-1"})
    with pytest.raises(ValidationError, match="consecutive"):
        MarketRiskSignal.model_validate({**s.model_dump(), "dates": list(reversed(dates))})
    with pytest.raises(ValidationError):
        MarketRiskSignal.model_validate({**s.model_dump(), "markets": []})
    with pytest.raises(ValidationError):
        MarketRiskSignal.model_validate({**s.model_dump(),
                                         "provenance": {**s.provenance.model_dump(),
                                                        "regime_id": "RGM-x"}})


def test_empty_inputs_fail_loudly():
    with pytest.raises(EngineError, match="no economies"):
        run_model(month_ends(3), [], CAL)
    one = synthetic(3)[:1]
    series = dict(one[0].series)
    del series["fx.dxy"]
    with pytest.raises(EngineError, match="fx.dxy"):
        run_model(month_ends(3), [EconomyInput("US", "US", series)], CAL)


# ---------------------------------------------------------------------------
# Contracts and calibration
# ---------------------------------------------------------------------------

def test_calibration_validation():
    base = CAL.model_dump()
    with pytest.raises(ValidationError, match="sum to 1"):
        Calibration.model_validate({**base, "segments": [
            {**s, "weight": 0.3} for s in base["segments"]]})
    with pytest.raises(ValidationError, match="four segments"):
        Calibration.model_validate({**base, "segments": base["segments"][:3]})
    with pytest.raises(ValidationError):
        Calibration.model_validate({**base, "optimism": {"default": 0.4}})
    with pytest.raises(ValidationError):
        Calibration.model_validate({**base, "markets": {"x": {"US": 1.0}}})
    ind = base["indicators"]
    with pytest.raises(ValidationError, match="business_cycle"):
        Calibration.model_validate({**base, "indicators": {
            **ind, "weights": {**ind["weights"], "business_cycle": {"inflation": 1.0}}}})


def test_seeds_round_trip_hash_stably_and_carry_no_optimism():
    assert [c.version for c in seeds.SEEDS] == ["2.0.0-matlab", "2.0.0"]
    for cal in seeds.SEEDS:
        again = Calibration.model_validate_json(seeds.canonical_json(cal))
        assert seeds.calibration_hash(again) == seeds.calibration_hash(cal)
        dumped = json.loads(seeds.canonical_json(cal))
        assert "optimism" not in dumped and "markets" not in dumped
        assert all("optimism_sign" not in s for s in dumped["segments"])
    assert set(seeds.RETIRED) == {"0.1.0-matlab", "1.0.0", "1.1.0"}


def test_run_request_is_the_new_contract():
    assert MRSRunRequest().snapshot_id is None
    with pytest.raises(ValidationError):
        MRSRunRequest(macro_artefact_id="a", taa_artefact_id="b")
    with pytest.raises(ValidationError):
        MRSRunRequest(snapshot_id="s", optimism_scale="default")
