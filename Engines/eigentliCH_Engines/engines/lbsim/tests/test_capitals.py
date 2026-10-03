"""The principal's capitals on the paths (``RegimePaths.capitals``, DECISIONS P-26, engine 1.1.0): determinism, ordered
bands within their scales, the median at sigma 0 against the deterministic model path, and artefacts made before
the field still read with their bytes and ids unchanged."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import GOLDEN, load_json
from stub import Stub, bundle, stated

from lbsim import ENGINE_VERSION
from lbsim.calibration import ACTIVE_SEED
from lbsim.contracts import CAPITAL_QUANTILES, CAPITALS, LifeBalancePaths
from lbsim.ids import content_id
from lbsim.paths import reference as R
from lbsim.paths.build import CAPITAL_STATE, build_paths, capitals_block, simulate_regimes

CASE = "lbsim-sample"
_STUB = Stub((CASE,))
SHEET, REQUEST, RECORDS, FINDINGS, PLAN = stated(CASE)
FULL = bundle(_STUB, SHEET)


def _paths(seed=7, n=300) -> LifeBalancePaths:
    return build_paths(FINDINGS, PLAN, FULL, ACTIVE_SEED, n_paths=n, seed=seed)


def test_the_engine_version_moved_with_the_field():
    assert ENGINE_VERSION == "lbsim@1.1.0"
    assert _paths().provenance.engine_version == "lbsim@1.1.0"


def test_every_regime_carries_the_principals_capitals_as_the_spec_defines_them():
    p = _paths()
    for r in p.regimes:
        c = r.capitals
        assert c is not None and c.person_id == FINDINGS.principal
        dumped = c.model_dump(mode="json")
        assert set(dumped) == {"person_id", "expertise", "network", "health", "scale", "labels"}
        for name in CAPITALS:
            assert set(dumped[name]) == set(CAPITAL_QUANTILES)
            assert all(len(dumped[name][q]) == p.horizon_years + 1 for q in CAPITAL_QUANTILES)
            assert dumped["scale"][name]["min"] == 0.0
        assert dumped["labels"] == {"expertise": {"de": "Wissen und Ausbildung", "en": "Expertise and education"},
                                    "network": {"de": "Netzwerk", "en": "Network"},
                                    "health": {"de": "Gesundheit", "en": "Health"}}
        assert dumped["scale"]["expertise"]["max"] == PLAN.params.K_E
        assert dumped["scale"]["health"]["max"] == PLAN.params.K_H
    # The network's scale is the Regime's own: a Regime's block does not depend on the Regimes beside it.
    for r in p.regimes:
        top = max(max(getattr(r.capitals.network, "p90")), 1.0)
        assert r.capitals.scale.network.max == top


def test_same_seed_same_bytes():
    one, two = _paths(seed=5), _paths(seed=5)
    assert json.dumps(one.model_dump(mode="json")) == json.dumps(two.model_dump(mode="json"))
    assert one.artefact_id == two.artefact_id
    assert _paths(seed=6).regimes[0].capitals != one.regimes[0].capitals


@pytest.mark.parametrize("seed", [1, 7, 20260929])
def test_the_bands_are_ordered_and_within_their_scales(seed):
    p = _paths(seed=seed)
    for r in p.regimes:
        for name in CAPITALS:
            band = getattr(r.capitals, name)
            qs = np.array([getattr(band, q) for q in CAPITAL_QUANTILES])
            assert np.all(np.diff(qs, axis=0) >= 0.0), (r.key, name)
            sc = getattr(r.capitals.scale, name)
            assert np.all(qs >= sc.min) and np.all(qs <= sc.max), (r.key, name)
        assert r.capitals.scale.network.max >= 1.0


def test_the_capitals_come_from_the_same_draws_as_the_wealth_bands():
    raw = simulate_regimes(PLAN, FULL, ACTIVE_SEED, n_paths=300, seed=7)
    p = _paths(seed=7)
    for r in p.regimes:
        states = raw[r.key].states
        for name in CAPITALS:
            want = np.percentile(states[CAPITAL_STATE[name]], [10, 25, 50, 75, 90], axis=1)
            got = np.array([getattr(getattr(r.capitals, name), q) for q in CAPITAL_QUANTILES])
            assert np.array_equal(want, got)
        nw = states["W_L"] + states["W_R"] + states["W_P"] + states["W_3a"] - states["D"]
        assert np.array_equal(np.percentile(nw, 50, axis=1), np.array(r.bands["net_worth"].nominal.p50))


def test_at_sigma_zero_the_median_is_the_deterministic_model_path():
    """One fixed state path in every Regime and no property noise: every path is the same, and the median of each
    capital is the reference's scalar path to 1e-9."""
    cal = ACTIVE_SEED.model_copy(update={"property": ACTIVE_SEED.property.model_copy(update={"sigma": 0.0})})
    n, years = 40, PLAN.horizon_years
    fixed = np.tile(np.arange(years) % 25, (n, 1))
    raw = simulate_regimes(PLAN, FULL, cal, n_paths=n, seed=3, states={r.key: fixed for r in FULL.regimes})
    h = PLAN.household
    for r in FULL.regimes:
        res = raw[r.key]
        pm = res.path_market  # type: ignore[attr-defined]
        ref = R.simulate_path(h.x0, PLAN.controls, h.p, market="allocation",
                              path=R.PathInputs(pm.log_return[0], pm.log_inflation[0], pm.property_growth[0]),
                              income=h.income, ahv_income=h.ahv_income, events=h.events,
                              p2_cash_share=h.p2_cash_share, pension_at_age=h.pension_at_age,
                              annuity_rate=h.annuity_rate)
        block = capitals_block(res, FINDINGS.principal, PLAN)
        for name in CAPITALS:
            want = np.asarray(ref[CAPITAL_STATE[name]])
            for q in CAPITAL_QUANTILES:
                assert np.max(np.abs(np.asarray(block[name][q]) - want)) <= 1e-9, (r.key, name, q)


def test_an_artefact_made_before_the_field_still_reads_with_its_bytes_and_id():
    raw = load_json(GOLDEN / "legacy" / "paths.engine-1.0.0.json")
    assert raw["provenance"]["engine_version"] == "lbsim@1.0.0"
    old = LifeBalancePaths.model_validate(raw)
    assert all(r.capitals is None for r in old.regimes)
    again = old.model_dump(mode="json")
    assert again == raw
    assert all("capitals" not in r for r in again["regimes"])
    assert content_id("LSP", {k: v for k, v in again.items() if k != "artefact_id"}) == old.artefact_id
    assert LifeBalancePaths.model_validate_json(old.model_dump_json()) == old


def test_a_band_of_the_wrong_length_is_refused():
    body = _paths().model_dump(mode="json")
    body["regimes"][0]["capitals"]["health"]["p50"] = body["regimes"][0]["capitals"]["health"]["p50"][:-1]
    with pytest.raises(ValueError):
        LifeBalancePaths.model_validate(body)
