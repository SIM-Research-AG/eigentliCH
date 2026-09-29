"""System Build Manual section 10.7, the acceptance tests of the Regime, numbered as the Manual
numbers them. Tests 1 to 4 belong to ``macrofield`` (the three-body field, closure modes, phase
classifier) and ``cycle`` (the five-component decomposition); test 5 (every pillar column sums
to its weight and is symmetric before folding) belongs to ``mrs``, which owns the pillar
matrices. A knowing departure is asserted by its test, with the reason in DECISIONS.md.
"""

from __future__ import annotations

import math

import httpx
import numpy as np
import pytest

from aggregation import ENGINE_VERSION, calibration as seeds
from aggregation.clients import UpstreamError, mrs_client
from aggregation.contracts import CONTRACT_VERSIONS, OPTIMISM_SCALES, AggregationRunRequest, MarketRiskSignal
from aggregation.engine import run_model
from aggregation.service import build_regime, content_id, regime_id_for

from .conftest import INPUTS

ACTIVE = seeds.TAIL_KEPT


@pytest.mark.parametrize("level", OPTIMISM_SCALES)
def test_manual_10_7_6_every_distribution_sums_to_one_with_live_crisis_mass(mrs, cycle, macro, level):
    """6. Every published distribution sums to one and carries non-zero mass in the crisis bins
    (the five most cautious states), at every optimism level (AGG-15)."""
    out = run_model(mrs, cycle, macro, ACTIVE, level)
    rows = [d for e in list(out.economies) + list(out.markets) for d in e.distribution if d is not None]
    assert rows
    for d in rows:
        assert abs(math.fsum(d) - 1.0) <= 1e-12
        assert sum(d[:ACTIVE.reading.tail_bins]) > 0.0


def test_manual_10_7_7_vintage_mismatch_is_warned_not_refused(mrs, cycle, macro):
    """7. The Manual refuses a vintage mismatch between the halves. Knowing departure (AGG-04,
    owner 28.09.2026): macrofield still runs on its own snapshot, so the mismatch is accepted,
    flagged in the coverage and named in the warnings; the vintages travel in provenance."""
    key = content_id("IDK", {"acceptance": 7})
    r = build_regime(mrs, cycle, macro, ACTIVE, "default", key, regime_id_for(key))
    assert r.coverage.snapshot_mismatch
    assert any("one datafeed snapshot" in w for w in r.coverage.warnings)
    up = r.provenance.upstream
    assert up["mrs:snapshot"] != up["macrofield:snapshot"]


def test_manual_10_7_8_an_input_that_is_not_what_was_asked_for_is_refused():
    """8. A stale feed entry fails its digest rather than being used: an upstream answer whose
    artefact id differs from the one requested, or that breaks the pinned contract, fails."""
    body = (INPUTS / "mrs.json").read_bytes()
    asked = "MRS-0000000000000000"

    client = mrs_client("http://mrs.test", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=body)))
    with pytest.raises(UpstreamError, match="asked mrs for"):
        client.artefact(asked)

    stale = body.replace(b'"mrs-signal@1.0.0"', b'"mrs-signal@0.9.0"')
    client = mrs_client("http://mrs.test", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=stale)))
    with pytest.raises(UpstreamError, match="breaks mrs-signal@1.0.0"):
        client.artefact(MarketRiskSignal.model_validate_json(body).artefact_id)


def _key(request: AggregationRunRequest, cal, engine=ENGINE_VERSION, contracts=CONTRACT_VERSIONS) -> str:
    return content_id("IDK", {
        "mrs_artefact_id": request.mrs_artefact_id, "cycle_artefact_id": request.cycle_artefact_id,
        "macro_artefact_id": request.macro_artefact_id, "optimism_scale": request.optimism_scale,
        "economies": None, "calibration_hash": seeds.calibration_hash(cal),
        "engine_version": engine, "contract_versions": contracts})


def test_manual_10_7_9_the_content_id_changes_with_any_input_and_not_otherwise(mrs, cycle, macro):
    """9. The content id (and the regime_id) changes when any input or the model version
    changes, and not otherwise."""
    base = AggregationRunRequest(mrs_artefact_id=mrs.artefact_id, cycle_artefact_id=cycle.artefact_id,
                                 macro_artefact_id=macro.artefact_id, optimism_scale="default")
    k0 = _key(base, ACTIVE)
    r0 = build_regime(mrs, cycle, macro, ACTIVE, "default", k0, regime_id_for(k0))
    again = build_regime(mrs, cycle, macro, ACTIVE, "default", k0, regime_id_for(k0))
    assert (again.artefact_id, again.regime_id) == (r0.artefact_id, r0.regime_id)

    variants = {
        "mrs input": _key(base.model_copy(update={"mrs_artefact_id": "MRS-1111111111111111"}), ACTIVE),
        "cycle input": _key(base.model_copy(update={"cycle_artefact_id": "CYS-1111111111111111"}), ACTIVE),
        "macro input": _key(base.model_copy(update={"macro_artefact_id": "MFS-1111111111111111"}), ACTIVE),
        "optimism": _key(base.model_copy(update={"optimism_scale": "rogue"}), ACTIVE),
        "calibration": _key(base, seeds.OPTIMISM_LEVELS),
        "engine version": _key(base, ACTIVE, engine="aggregation@9.9.9"),
        "contract version": _key(base, ACTIVE, contracts={**CONTRACT_VERSIONS, "Regime": "aggregation-regime@9.9.9"}),
    }
    ids = {name: regime_id_for(k) for name, k in variants.items()}
    assert len(set(ids.values())) == len(ids)
    assert regime_id_for(k0) not in ids.values()

    # A changed input value (same ids) changes the artefact id.
    data = mrs.model_dump(mode="json")
    t = next(i for i, d in enumerate(data["economies"][0]["distribution"]) if d is not None)
    row = np.asarray(data["economies"][0]["distribution"][t])
    data["economies"][0]["distribution"][t] = list(np.roll(row, 1))
    changed = build_regime(MarketRiskSignal.model_validate(data), cycle, macro, ACTIVE, "default",
                           k0, regime_id_for(k0))
    assert changed.artefact_id != r0.artefact_id
