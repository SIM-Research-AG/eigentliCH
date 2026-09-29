"""Scenario Regimes (AGG-19 to AGG-22): the Scenario_SAA.m port, the scenario Regime, and what must not move.

* Kernels, targets and the stepping against the frozen literal transcription of the .m file
  (``golden/scenario_saa/scenario_saa.json``, ``golden/build_scenario_golden.py``), and the policy
  ids and mixes against macrofield's freeze of the same template (TB-21).
* The scenario Regime: its shape, that every distribution sums to 1 in every month and economy, that
  its last month is the target and the month a consumer reads by default, idempotent ids.
* pcp's mirror of ``aggregation-regime@1.0.0`` reads a scenario Regime unchanged.
* The Default Regime ``RGM-e2658e8e9bbbc81e`` keeps its id, and every base Regime serialises as before.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Optional

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from pydantic import BaseModel, ConfigDict

from aggregation import ENGINE_VERSION, calibration as seeds
from aggregation import scenario as sc
from aggregation.contracts import CONTRACT_VERSIONS, DERIVED_SCENARIO_FIELDS, N_STATES, STORED, Regime
from aggregation.service import Service, build_regime, build_scenario_regime, content_id, regime_id_for

from .conftest import GOLDEN

FROZEN = json.loads((GOLDEN / "scenario_saa" / "scenario_saa.json").read_text(encoding="utf-8"))
ACTIVE = next(c for c in seeds.SEEDS if c.version == "1.2.0")
DEFAULT_REGIME_ID = "RGM-e2658e8e9bbbc81e"
PCP_CONTRACTS = (Path(__file__).resolve().parents[4] / "Optimizer" / "engines" / "pcp" / "src" / "pcp"
                 / "contracts.py")
#: macrofield's freeze of the same template (TB-21), read only.
MACROFIELD_FROZEN = (Path(__file__).resolve().parents[2] / "macrofield" / "golden" / "scenario_saa"
                     / "scenario_saa.json")
#: The scenario Regimes on the Default, as stored on 29.09.2026 (deferral as replaced under AGG-23).
ISSUED_ON_DEFAULT = {
    "depression": ("RGM-1af6968e287768c9", "AGG-451c8d2ee5fb0bac"),
    "hyperinflation": ("RGM-59eebfaf7744d8ec", "AGG-36fb373718f6ecbb"),
    "stagflation": ("RGM-6bb531998bfefc4d", "AGG-33dc16356adc24ff"),
    "deferral": ("RGM-c0ed086f1916984e", "AGG-91e2e05e126ae47d"),
}


def _default_key(mrs, cycle, macro) -> str:
    """The idempotency key ``Service.idempotency_key`` gives the Default request of 28.09.2026."""
    return content_id("IDK", {
        "mrs_artefact_id": mrs.artefact_id, "cycle_artefact_id": cycle.artefact_id,
        "macro_artefact_id": macro.artefact_id, "optimism_scale": "default", "economies": None,
        "calibration_hash": seeds.calibration_hash(ACTIVE), "engine_version": ENGINE_VERSION,
        "contract_versions": CONTRACT_VERSIONS,
    })


@pytest.fixture(scope="module")
def base(mrs, cycle, macro) -> Regime:
    key = _default_key(mrs, cycle, macro)
    return build_regime(mrs, cycle, macro, ACTIVE, "default", key, regime_id_for(key))


@pytest.fixture(scope="module")
def scenarios(base) -> dict[str, Regime]:
    out = {}
    for policy in sc.SCENARIO_POLICIES:
        key = Service.scenario_key(base, policy)
        out[policy] = build_scenario_regime(base, policy, ACTIVE.reading, key, regime_id_for(key))
    return out


# ---------------------------------------------------------------------------
# The port of Scenario_SAA.m
# ---------------------------------------------------------------------------

def test_the_template_copy_is_v0_1():
    raw = (GOLDEN / "scenario_saa" / "Scenario_SAA.m").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sc.TEMPLATE_SHA256 == FROZEN["sha256"]


def test_ids_kernels_and_mixes_are_the_templates_and_macrofields():
    assert FROZEN["months"] == sc.HORIZON_MONTHS == 60
    assert list(sc.BINOM) == FROZEN["kernels"]["binom"] and list(sc.BINOM_BUST) == FROZEN["kernels"]["binom_bust"]
    assert tuple(FROZEN["policies"]) == sc.SCENARIO_POLICIES
    for policy, spec in sc.POLICIES.items():
        assert spec.case == FROZEN["policies"][policy]["case"]
        assert list(spec.target_mix) == FROZEN["policies"][policy]["target_mix"]
    mf = FROZEN["macrofield"]                                    # TB-21: the same ids and values
    assert mf["sha256_of_template"] == sc.TEMPLATE_SHA256
    assert mf["kernels"] == FROZEN["kernels"]
    assert {k: v["target_mix"] for k, v in mf["policies"].items()} == \
        {k: list(v.target_mix) for k, v in sc.POLICIES.items()}
    k = sc.kernels()
    assert np.array_equal(k["binom_boom"], k["binom_bust"][::-1])
    assert math.isclose(k["binom"].sum(), 0.99) and math.isclose(k["binom_bust"].sum(), 0.99)


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_target_is_the_templates(policy):
    want = np.asarray(FROZEN["policies"][policy]["target"])
    got = sc.target_distribution(policy)
    assert got.shape == (N_STATES,) and np.array_equal(got, want)
    assert math.isclose(got.sum(), 0.99)                          # the .m file does not normalise


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
@pytest.mark.parametrize("start", ["uniform", "ramp", "rand"])
def test_stepping_is_the_templates(policy, start):
    want = np.asarray(FROZEN["policies"][policy]["paths"][start])
    got = sc.step_path(np.asarray(FROZEN["starts"][start]), sc.target_distribution(policy))
    assert got.shape == (60, N_STATES)
    assert np.max(np.abs(got - want)) == 0.0
    # the last month is the target, normalised, whatever the start
    assert np.max(np.abs(got[-1] - want[-1])) == 0.0
    assert np.allclose(got[-1], sc.target_distribution(policy) / 0.99, atol=1e-15)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(0.0, 1.0), min_size=N_STATES, max_size=N_STATES).filter(lambda v: sum(v) > 1e-6),
       st.sampled_from(sc.SCENARIO_POLICIES), st.integers(1, 120))
def test_every_stepped_month_is_a_distribution(raw, policy, months):
    start = np.asarray(raw) / sum(raw)
    rows = sc.step_path(start, sc.target_distribution(policy), months)
    assert rows.shape == (months, N_STATES)
    assert np.all(rows >= 0.0)
    assert np.all(np.abs(rows.sum(axis=1) - 1.0) <= 1e-12)
    assert np.allclose(rows[-1], sc.target_distribution(policy) / sc.target_distribution(policy).sum())


def test_month_ends():
    assert sc.month_ends_after("2026-01-31", 3) == ["2026-02-28", "2026-03-31", "2026-04-30"]
    assert sc.month_ends_after("2027-12-31", 3) == ["2028-01-31", "2028-02-29", "2028-03-31"]
    assert len(sc.month_ends_after("2026-01-31", 60)) == 60


# ---------------------------------------------------------------------------
# The scenario Regime
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_scenario_regime_shape(base, scenarios, policy):
    r = scenarios[policy]
    s = r.provenance.scenario
    cut = base.dates.index(base.provenance.as_of) + 1
    assert r.contract_version == "aggregation-regime@1.0.0"
    assert r.dates[:cut] == base.dates[:cut] and len(r.dates) == cut + 60
    assert s.policy == policy and s.base_regime_id == base.regime_id and s.horizon_months == 60
    assert s.template_sha256 == sc.TEMPLATE_SHA256
    assert s.projected_from == r.dates[cut] == "2026-02-28"
    assert s.scenario_date == r.dates[-1] == r.provenance.as_of == "2031-01-31"
    assert r.optimism_scale == base.optimism_scale
    target = sc.target_distribution(policy) / sc.target_distribution(policy).sum()
    for e, b in zip(r.economies, base.economies):
        assert e.code == b.code
        assert e.distribution[:cut] == b.distribution[:cut] and e.state[:cut] == b.state[:cut]
        # the start is the economy's latest distribution; the path is the .m file's stepping from it
        last = max(k for k in range(cut) if b.distribution[k] is not None)
        path = sc.step_path(np.asarray(b.distribution[last]), sc.target_distribution(policy))
        assert np.max(np.abs(np.asarray(e.distribution[cut:]) - path)) == 0.0
        assert np.allclose(e.distribution[-1], target, atol=1e-15)
        assert e.current.date == r.dates[-1]
        assert all(y is None for y in e.macro_year[cut:])
    for m in r.markets:
        assert m.distribution[-1] is not None and np.allclose(m.distribution[-1], target, atol=1e-12)


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_every_distribution_of_a_scenario_regime_sums_to_one(scenarios, policy):
    r = Regime.model_validate_json(scenarios[policy].model_dump_json())     # the round trip validates
    for rows in [e.distribution for e in r.economies] + [m.distribution for m in r.markets]:
        for d in rows:
            if d is not None:
                assert len(d) == N_STATES and min(d) >= 0.0 and abs(math.fsum(d) - 1.0) <= 1e-12
    assert r == scenarios[policy]


def test_scenario_ids_are_idempotent_and_distinct(base, scenarios):
    ids = {p: r.regime_id for p, r in scenarios.items()}
    assert len(set(ids.values())) == 4 and all(i.startswith("RGM-") for i in ids.values())
    for policy in sc.SCENARIO_POLICIES:
        key = Service.scenario_key(base, policy)
        again = build_scenario_regime(base, policy, ACTIVE.reading, key, regime_id_for(key))
        assert (again.regime_id, again.artefact_id) == (ids[policy], scenarios[policy].artefact_id)
        assert again.provenance.idempotency_key == key
    other = base.model_copy(update={"regime_id": "RGM-1111111111111111"})
    assert Service.scenario_key(other, "depression") != Service.scenario_key(base, "depression")


def test_a_scenario_of_a_scenario_is_refused(scenarios):
    from aggregation.engine import EngineError

    with pytest.raises(EngineError):
        build_scenario_regime(scenarios["depression"], "stagflation", ACTIVE.reading, "IDK-x", "RGM-x")


# ---------------------------------------------------------------------------
# The policy's inflation path (AGG-24)
# ---------------------------------------------------------------------------

def _macrofield_frozen() -> dict:
    if not MACROFIELD_FROZEN.is_file():
        pytest.skip("macrofield's golden freeze is not on disk (a deploy folder)")
    return json.loads(MACROFIELD_FROZEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_inflation_path_is_macrofields_tb21_path(policy):
    mf = _macrofield_frozen()
    assert mf["sha256"] == sc.TEMPLATE_SHA256
    want = np.asarray(mf["policies"][policy]["inflation"])
    got = sc.inflation_path(policy)
    assert got.shape == want.shape == (60,)
    assert np.max(np.abs(got - want)) <= 1e-15


def test_inflation_paths_have_the_templates_shapes():
    dep, hyp, stag, dfr = (sc.inflation_path(p) for p in sc.SCENARIO_POLICIES)
    assert math.isclose(dep[0], 0.02, abs_tol=1e-5) and math.isclose(dep[-1], -0.04, abs_tol=1e-5)
    assert np.all(np.diff(dep) <= 0)                               # sigmoid, falling
    assert hyp[0] == 0.2 and math.isclose(hyp[-1], 1.0) and np.all(np.diff(hyp) >= 0)
    assert math.isclose(stag[-1], 0.10, abs_tol=1e-4) and np.all(np.diff(stag) >= 0)
    assert dfr[0] == dfr[-1] and 0.059 < dfr.max() <= 0.06          # hump from 2 % to 6 % and back


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_inflation_final_12m_is_the_mean_of_months_49_to_60(policy):
    path = sc.inflation_path(policy)
    assert sc.inflation_final_12m(path) == math.fsum(path[48:60]) / 12


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_a_scenario_regime_serves_its_inflation_path(scenarios, policy):
    s = scenarios[policy].provenance.scenario
    assert s.inflation_path == tuple(sc.inflation_path(policy))
    assert s.inflation_final_12m == sc.inflation_final_12m(sc.inflation_path(policy))
    served = json.loads(scenarios[policy].model_dump_json())["provenance"]["scenario"]
    assert len(served["inflation_path"]) == 60 and served["inflation_final_12m"] == s.inflation_final_12m
    stored = json.loads(scenarios[policy].model_dump_json(context=STORED))["provenance"]["scenario"]
    assert not set(DERIVED_SCENARIO_FIELDS) & set(stored)
    # the stored form reads back with the fields derived; a value that is not the policy's is refused
    assert Regime.model_validate_json(scenarios[policy].model_dump_json(context=STORED)) == scenarios[policy]
    body = json.loads(scenarios[policy].model_dump_json())
    body["provenance"]["scenario"]["inflation_final_12m"] += 0.01
    with pytest.raises(ValueError):
        Regime.model_validate(body)


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_the_inflation_path_moves_no_scenario_regime_id(scenarios, policy):
    # the artefact ids are checked against the store below: the in-process base differs from the
    # stored Default in its artefact_id (its inputs were served in-process), which enters the hash
    assert scenarios[policy].regime_id == ISSUED_ON_DEFAULT[policy][0]


def test_a_base_regime_carries_no_inflation_path(base):
    assert base.provenance.scenario is None
    assert base.model_dump_json() == base.model_dump_json(context=STORED)
    assert "inflation_path" not in base.model_dump_json()


def test_the_stored_scenario_regimes_read_back_with_their_inflation_path():
    """The real store, read only: every stored scenario Regime reads with the derived fields, and
    its stored form is the stored payload byte for byte, under its own artefact id."""
    import psycopg

    from aggregation.settings import load

    db = load().database
    try:
        with psycopg.connect(db.conninfo(), connect_timeout=5) as conn:
            conn.execute(f"SET search_path TO {db.schema}")
            rows = conn.execute("SELECT a.artefact_id, a.regime_id, a.payload_json FROM scenario s "
                                "JOIN artefact a USING (artefact_id)").fetchall()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"real store not reachable: {exc}")
    if not rows:
        pytest.skip("no scenario Regime in the real store")
    for artefact_id, regime_id, payload in rows:
        r = Regime.model_validate_json(payload)
        s = r.provenance.scenario
        assert r.regime_id == regime_id and r.artefact_id == artefact_id
        assert s.inflation_path == tuple(sc.inflation_path(s.policy)) and len(s.inflation_path) == 60
        assert (r.model_dump_json(context=STORED) == payload) is True      # no 5 MB diff on failure
        draft = r.model_copy(update={"artefact_id": ""})
        assert content_id("AGG", draft.model_dump(mode="json", context=STORED)) == artefact_id
    # rebuilt from the stored Default, every scenario keeps its regime_id and artefact_id
    by_regime = {regime_id: payload for _, regime_id, payload in rows}
    with psycopg.connect(db.conninfo(), connect_timeout=5) as conn:
        conn.execute(f"SET search_path TO {db.schema}")
        row = conn.execute("SELECT payload_json FROM artefact WHERE regime_id = %s", (DEFAULT_REGIME_ID,)).fetchone()
    if row is None:
        pytest.skip(f"{DEFAULT_REGIME_ID} is not in the real store")
    base = Regime.model_validate_json(row[0])
    for policy, (regime_id, artefact_id) in ISSUED_ON_DEFAULT.items():
        key = Service.scenario_key(base, policy)
        again = build_scenario_regime(base, policy, ACTIVE.reading, key, regime_id_for(key))
        assert (again.regime_id, again.artefact_id) == (regime_id, artefact_id)
        assert regime_id in by_regime


# ---------------------------------------------------------------------------
# pcp's mirror
# ---------------------------------------------------------------------------

class _PcpUpstream(BaseModel):
    """A copy of pcp's ``Regime`` mirror (``pcp/contracts.py``, read 29.09.2026), used only where
    pcp's own file is not on disk (a deploy folder): extra fields ignored, the version pinned."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class _PcpRegimeEconomy(_PcpUpstream):
    code: str
    name: str = ""
    distribution: tuple[Optional[tuple[float, ...]], ...]


class _PcpRegimeMarket(_PcpUpstream):
    code: str
    weights: dict[str, float]
    distribution: tuple[Optional[tuple[float, ...]], ...]


class _PcpRegimeProvenance(_PcpUpstream):
    snapshot_id: str
    as_of: str
    calibration_version: str
    regime_id: str
    optimism_scale: str


class _PcpRegime(_PcpUpstream):
    contract_version: Literal["aggregation-regime@1.0.0"]
    artefact_id: str
    regime_id: str
    optimism_scale: str
    n_states: Literal[25]
    dates: tuple[str, ...]
    economies: tuple[_PcpRegimeEconomy, ...]
    markets: tuple[_PcpRegimeMarket, ...] = ()
    provenance: _PcpRegimeProvenance


_PcpMirrorCopy = SimpleNamespace(Regime=_PcpRegime)


def _pcp_contracts():
    if not PCP_CONTRACTS.is_file():
        return _PcpMirrorCopy
    spec = importlib.util.spec_from_file_location("pcp_contracts_readonly", PCP_CONTRACTS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module                              # pydantic resolves annotations there
    spec.loader.exec_module(module)                              # read only: pcp is not edited
    return module


def _pcp_default_month(regime, weights: dict[str, float]) -> int:
    """pcp's rule (``pcp.engine``, date omitted): the latest month in which every weighted economy
    is assessed."""
    by = {e.code: e for e in regime.economies}
    return max(k for k in range(len(regime.dates)) if all(by[c].distribution[k] is not None for c in weights))


@pytest.mark.parametrize("policy", sc.SCENARIO_POLICIES)
def test_pcps_mirror_reads_a_scenario_regime_unchanged(scenarios, policy):
    pcp = _pcp_contracts()
    body = scenarios[policy].model_dump_json()
    mirrored = pcp.Regime.model_validate_json(body)
    assert mirrored.model_config.get("extra") == "ignore"
    assert mirrored.contract_version == "aggregation-regime@1.0.0"
    assert mirrored.regime_id == scenarios[policy].regime_id == mirrored.provenance.regime_id
    assert mirrored.provenance.as_of == scenarios[policy].provenance.scenario.scenario_date
    k = _pcp_default_month(mirrored, {"US": 0.5, "CH": 0.3, "IN": 0.2})
    assert mirrored.dates[k] == scenarios[policy].provenance.scenario.scenario_date
    assert _PcpMirrorCopy.Regime.model_validate_json(body).regime_id == mirrored.regime_id
    assert "inflation_path" in body                               # the served form, with AGG-24's fields


def test_pcps_mirror_still_reads_a_base_regime(base):
    pcp = _pcp_contracts()
    assert pcp.Regime.model_validate_json(base.model_dump_json()).regime_id == base.regime_id


# ---------------------------------------------------------------------------
# What must not move
# ---------------------------------------------------------------------------

def test_the_default_regime_keeps_its_id(mrs, cycle, macro, base):
    assert regime_id_for(_default_key(mrs, cycle, macro)) == DEFAULT_REGIME_ID == base.regime_id


def test_a_base_regime_serialises_without_the_scenario_field(base):
    dumped = json.loads(base.model_dump_json())
    assert "scenario" not in dumped["provenance"]
    assert "scenario" not in base.model_dump(mode="json")["provenance"]
    assert Regime.model_validate_json(base.model_dump_json()) == base


def test_the_stored_default_regime_reads_back_byte_for_byte():
    """The real store (schema ``aggregation``), read only. Skipped where the store or the Regime is
    not there; the id itself is checked above without a store."""
    import psycopg

    from aggregation.settings import load

    db = load().database
    try:
        with psycopg.connect(db.conninfo(), connect_timeout=5) as conn:
            conn.execute(f"SET search_path TO {db.schema}")
            row = conn.execute("SELECT artefact_id, payload_json FROM artefact WHERE regime_id = %s",
                               (DEFAULT_REGIME_ID,)).fetchone()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"real store not reachable: {exc}")
    if row is None:
        pytest.skip(f"{DEFAULT_REGIME_ID} is not in the real store")
    artefact_id, payload = row
    regime = Regime.model_validate_json(payload)
    assert regime.regime_id == DEFAULT_REGIME_ID and regime.artefact_id == artefact_id == "AGG-19e06ace80bd6cfb"
    assert regime.provenance.scenario is None
    assert regime.model_dump_json() == payload
