"""The frozen sample artefacts in ``golden/samples`` (for B2, C, D, E): valid against the contracts, one sheet,
the findings sample reproducible by the engine, the hand-built ones marked as samples."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import GOLDEN, load_json

from lbsim.calibration import ACTIVE_SEED
from lbsim.contracts import (LbsRequest, LbsSheet, LifeBalanceFindings, LifeBalanceOutlook, LifeBalancePaths,
                             LifeBalancePlan, PcpAllocation, PlanOutlook)
from lbsim.fast.build import build_findings
from lbsim.ids import sha256

S = GOLDEN / "samples"


def _load():
    return (LifeBalanceFindings.model_validate(load_json(S / "findings.sample.json")),
            LifeBalancePaths.model_validate(load_json(S / "paths.sample.json")),
            LifeBalancePlan.model_validate(load_json(S / "plan.sample.json")))


def test_the_samples_validate_and_describe_one_sheet():
    f, p, plan = _load()
    assert f.life_balance_sheet_id == p.life_balance_sheet_id == plan.life_balance_sheet_id
    assert p.findings_artefact_id == f.artefact_id and plan.paths_artefact_id == p.artefact_id
    LifeBalanceOutlook(client_ref=f.client_ref, life_balance_sheet_id=f.life_balance_sheet_id, findings=f, paths=p,
                       plan=PlanOutlook(state="ready", artefact=plan))


def test_the_findings_sample_is_the_engines_own():
    f, _, _ = _load()
    assert f.provenance.made_by == "engine"
    case = GOLDEN / "lbs_cases" / "lbsim-sample"
    sheet = load_json(case / "sheet.json")
    records = load_json(GOLDEN / "lbs_cases" / "records.json")["records"]
    again = build_findings(LbsSheet.model_validate(sheet), LbsRequest.model_validate(load_json(case / "request.json")),
                           records, ACTIVE_SEED, sheet_sha256=sha256(sheet), lbs_url="http://127.0.0.1:8013")
    assert again.artefact_id == f.artefact_id


def test_the_hand_built_plan_says_so_and_the_paths_are_the_engines_own():
    """Since B2 (29.09.2026) the paths sample is the engine's Monte Carlo on the snapshot ``golden/upstream``, and
    a rebuild gives the same bytes; the plan sample stays hand-built until the optimiser runs (agent C)."""
    import sys  # noqa: PLC0415

    f, p, plan = _load()
    assert plan.provenance.made_by == "sample" and plan.provenance.sample_note
    assert p.provenance.made_by == "engine" and "bench" in p.provenance.sample_note
    sys.path.insert(0, str(GOLDEN.parent / "dev"))
    import build_samples  # noqa: PLC0415

    again = build_samples.paths_sample(f)
    assert again.model_dump(mode="json") == p.model_dump(mode="json")


def test_the_paths_sample_has_the_base_and_four_scenarios_and_ordered_bands():
    _, p, _ = _load()
    assert [r.key for r in p.regimes] == ["base", "depression", "hyperinflation", "stagflation", "deferral"]
    for r in p.regimes:
        assert {g.measure for g in r.goals} == {"deposit_eligible", "retirement_capital"}
        for band in r.bands.values():
            for part in (band.nominal, band.real):
                qs = np.array([part.p05, part.p10, part.p25, part.p50, part.p75, part.p90, part.p95])
                assert np.all(np.diff(qs, axis=0) >= -1e-6)


def test_the_allocation_view_names_real_instruments_and_reproduces_the_achieved_curve():
    _, p, _ = _load()
    alloc = PcpAllocation.model_validate(load_json(S / "upstream" / "allocation.json"))
    names = {i.instrument_id: (i.name, i.role) for i in alloc.instruments}
    for i in p.allocation_view.instruments:
        assert names[i.instrument_id] == (i.name, i.role)
    assert p.market_model.check.achieved_reproduced and p.market_model.check.max_abs_diff <= 1e-9
    v = p.allocation_view.curves
    assert v.real.derived and not v.nominal.derived
    assert v.real.achieved[0] == pytest.approx(v.nominal.achieved[0] - v.log_inflation[0])
