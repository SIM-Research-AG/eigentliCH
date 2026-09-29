"""Golden reconciliation (Engine Building Guide section 6.1): the eigentliCH prototype's own outputs.

``golden/`` was frozen by ``dev/build_golden.py`` under the prototype's interpreter, from eight members of its
database (``db-*``) and seven constructed cases (``syn-*``), each under the records as shipped (``seed``) and
with ``ahv-pension`` and ``risk-profile`` approved by a fixture (``approved``). They run here under the real
seeds: ``seed`` under 1.0.0 and ``approved`` under 1.1.0, the owner's approval of 29.09.2026 (LBS-23), which
differs from the fixture only in the publisher's name. This is the reference for the reproduction mode; the
corrected behaviour (1.2.0) is golden layer B (``test_golden_corrected.py``, LBS-26).

Declared tolerance: every figure to 1e-9 relative (and 1e-9 absolute near zero); every verdict, reason key,
lever and caveat exactly. The same arithmetic in the same order reproduces the prototype bit for bit; the
measured maximum deviation is asserted below as well, so a drift inside the tolerance is still visible.

Divergences, each classified in DECISIONS.md and asserted here rather than hidden:

* LBS-15: the prototype's ``observations`` never reports ``funding_shared_with_other_goals`` (it reads an
  attribute nothing sets); lbs reports it. Compared without that kind, and asserted present where it applies.
* LBS-15: the prototype's property payload shows ``price_chf`` 0 for a goal with no amount; lbs shows null.
  ``price_chf`` is not compared.
* ``has_no_liabilities`` is an lbs fact the prototype does not have: where a case states it, lbs's
  liabilities are 0 and the net worth is compared with the prototype's ``W_R + W_L - D`` reading.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from lbs.contracts import LifeBalanceSheetRequest, NotAvailable
from lbs.service import build_sheet

from .conftest import CALIBRATIONS, golden_expected, golden_names, golden_request

TOL = 1e-9
MEASURED: list[float] = []


def close(ours: Any, theirs: Any, where: str) -> None:
    """Numbers to TOL, containers recursively, everything else exactly."""
    if isinstance(theirs, bool) or theirs is None or isinstance(theirs, str):
        assert ours == theirs, f"{where}: {ours!r} != {theirs!r}"
        return
    if isinstance(theirs, (int, float)):
        assert isinstance(ours, (int, float)) and not isinstance(ours, bool), f"{where}: {ours!r} is not a number"
        scale = max(1.0, abs(theirs))
        dev = abs(float(ours) - float(theirs)) / scale
        MEASURED.append(dev)
        assert dev <= TOL, f"{where}: {ours!r} != {theirs!r} (relative {dev:.3g})"
        return
    if isinstance(theirs, dict):
        assert isinstance(ours, dict), f"{where}: {ours!r} is not a mapping"
        assert set(ours) == set(theirs), f"{where}: keys {sorted(ours)} != {sorted(theirs)}"
        for k in theirs:
            close(ours[k], theirs[k], f"{where}.{k}")
        return
    if isinstance(theirs, (list, tuple)):
        assert len(ours) == len(theirs), f"{where}: length {len(ours)} != {len(theirs)}"
        for i, (a, b) in enumerate(zip(ours, theirs)):
            close(a, b, f"{where}[{i}]")
        return
    raise AssertionError(f"{where}: cannot compare {type(theirs)}")


def dump(model: Any) -> Any:
    return model.model_dump(mode="json")


CASES = [(name, variant) for name in golden_names() for variant in ("seed", "approved")]


@pytest.fixture(scope="module")
def sheets() -> dict:
    return {(n, v): build_sheet(LifeBalanceSheetRequest.model_validate(golden_request(n)), CALIBRATIONS[v])
            for n, v in CASES}


@pytest.mark.parametrize("name,variant", CASES)
def test_reproduces_the_prototype(sheets, name, variant):
    e = golden_expected(name)[variant]
    req = golden_request(name)
    s = sheets[(name, variant)]

    if "stocks" in e:
        close(s.totals.financial_assets, e["stocks"]["financial_assets"], "financial_assets")
        close(s.totals.human_assets, e["stocks"]["human_assets"], "human_assets")
        if req.get("facts", {}).get("has_no_liabilities"):
            assert s.totals.liabilities == 0.0
        else:
            close(s.totals.liabilities, e["stocks"]["liabilities"], "liabilities")
    if "net_worth" in e:
        close(s.totals.net_worth, e["net_worth"], "net_worth")
        assert s.totals.identity_holds
    if "household_income" in e:
        close(s.totals.household_income, e["household_income"], "household_income")

    for pid, hc in e.get("human_capital", {}).items():
        ours = next(h for h in s.human_capital if h.person_id == pid)
        for key in ("E", "N", "H"):
            cap = getattr(ours, key)
            close({"value": cap.value, "source": cap.source, "absent_because": cap.absent_because}, hc[key], key)
        close(list(ours.caveats), hc["caveats"], "caveats")
        tb = ours.time_budget
        close({"tau_Y": tb.tau_Y, "tau_E": tb.tau_E, "tau_N": tb.tau_N, "tau_H": tb.tau_H, "leisure": tb.leisure,
               "caveats": list(tb.caveats)}, hc["time_budget"], "time_budget")

    for pid, bvg in e.get("bvg", {}).items():
        ours = next(p for p in s.pensions if p.person_id == pid).bvg
        if bvg["status"] == "not_available":
            assert isinstance(ours, NotAvailable), f"bvg {pid}: {ours}"
            continue
        assert not isinstance(ours, NotAvailable), ours
        for key in ("closing_balance", "yearly_pension", "opening_balance", "gross_salary", "total_credited",
                    "total_interest"):
            if key in bvg:
                close(getattr(ours, key), bvg[key], f"bvg.{pid}.{key}")

    for pid, ahv in e.get("ahv", {}).items():
        ours = next(p for p in s.pensions if p.person_id == pid).ahv
        if ahv["status"] == "not_available":
            assert isinstance(ours, NotAvailable), ours
            if ahv.get("refused") == "ScaleNotApproved":
                assert ours.record == "ahv-pension" and "record not approved" in ours.reason
            continue
        close({k: getattr(ours, k) for k in ("monthly", "yearly", "full_monthly", "factor")},
              {k: ahv[k] for k in ("monthly", "yearly", "full_monthly", "factor")}, f"ahv.{pid}")
        close(list(ours.caveats), ahv["caveats"], f"ahv.{pid}.caveats")

    if "couple" in e:
        c = e["couple"]
        if c.get("status") == "not_available":
            assert isinstance(s.couple_cap, NotAvailable)
        else:
            close({k: getattr(s.couple_cap, k) for k in c}, c, "couple")

    for gid, p in e.get("property", {}).items():
        ours = next(f for f in s.property if f.goal_id == gid)
        mine = {"verdict": ours.verdict, "binds_on": list(ours.binds_on),
                "undetermined_because": list(ours.undetermined_because),
                "ineligible_funding": list(ours.ineligible_funding), "levers": list(ours.levers),
                "equity": ours.equity, "affordability": ours.affordability}
        if p["levers"] is None:  # the refusal paths carry no levers in the prototype
            mine["levers"] = None
        close(mine, p, f"property.{gid}")

    for gid, r in e.get("retirement", {}).items():
        ours = next(f for f in s.retirement if f.goal_id == gid)
        close({"verdict": ours.verdict, "undetermined_because": list(ours.undetermined_because),
               "covered_per_year": ours.covered_per_year, "shortfall_per_year": ours.shortfall_per_year,
               "needs_per_year": ours.needs_per_year, "ahv_yearly": (ours.ahv or {}).get("yearly"),
               "pillar2_closing": (ours.pillar2 or {}).get("closing_balance"),
               "pillar2_yearly": (ours.pillar2 or {}).get("yearly")}, r, f"retirement.{gid}")

    for gid, liq in e.get("liquidity", {}).items():
        ours = next((f for f in s.liquidity if f.goal_id == gid), None)
        if liq is None:
            assert ours is None, f"liquidity.{gid}: lbs reports {ours}"
            continue
        assert ours is not None, f"liquidity.{gid}: the prototype reports a finding"
        close({"gap_chf": ours.gap_chf, "due_date": ours.due_date.isoformat(), "reason": ours.reason,
               "lever": ours.prepared["lever"], "requires_curator": ours.prepared["requires_curator"],
               "considered": ours.prepared["considered"]}, liq, f"liquidity.{gid}")

    for gid, kinds in e.get("observations", {}).items():
        ours = next(o for o in s.observations if o.goal_id == gid)
        mine = sorted(o["kind"] for o in ours.observations if o["kind"] != "funding_shared_with_other_goals")
        assert mine == kinds, f"observations.{gid}: {mine} != {kinds}"

    rp = e.get("risk_profile")
    if rp is not None:
        if rp["status"] == "not_available":
            assert isinstance(s.risk_profile, NotAvailable) and s.risk_profile.record == "risk-profile"
        else:
            ours = s.risk_profile
            assert not isinstance(ours, NotAvailable), ours
            close({"value": ours.value, "binds_on": ours.binds_on, "capacity": ours.capacity["value"],
                   "willingness": ours.willingness["value"], "role_bounds": ours.role_bounds,
                   "curve_slope": ours.curve_slope, "esg_min": ours.sustainability["esg_min"],
                   "capacity_inputs": {k: v for k, v in ours.capacity_inputs.items() if k != "sources"}},
                  _risk(rp), "risk_profile")

    m = e.get("mandate")
    if m is not None:
        ours = s.mandate_proposal
        assert not isinstance(ours, NotAvailable), ours
        close(ours.target_chf, m["target"], "mandate.target")
        if "horizon_years" in m:
            close(ours.goal_horizon_years, m["horizon_years"], "mandate.horizon")
        if "required_return" in m:
            close(ours.required_return, m["required_return"], "mandate.required_return")
            assert ours.target_curve is not None and len(ours.target_curve) == 25
        else:
            assert ours.required_return is None and ours.target_curve is None

    if e.get("composition_expired"):
        assert s.household.currency.expired and s.household.currency.determination == "could_not_be_determined"


def _risk(rp: dict) -> dict:
    """The prototype's profile in the shape lbs publishes: numeric anchor entries only."""
    out = {k: rp[k] for k in ("value", "binds_on", "capacity", "willingness", "esg_min", "capacity_inputs")}
    out["role_bounds"] = {k: {kk: float(vv) for kk, vv in v.items() if isinstance(vv, (int, float))}
                          for k, v in (rp["role_bounds"] or {}).items() if isinstance(v, dict)}
    out["curve_slope"] = {k: float(v) for k, v in (rp["curve_slope"] or {}).items() if isinstance(v, (int, float))}
    return out


def test_shared_funding_is_reported_where_the_prototype_cannot(sheets):
    """LBS-15: 'art' funds g1 and g4 in syn-liquidity."""
    obs = {o.goal_id: o.observations for o in sheets[("syn-liquidity", "seed")].observations}
    assert any(o["kind"] == "funding_shared_with_other_goals" and "art" in o["position_ids"] for o in obs["g1"])


def test_the_refusals_are_golden_too(sheets):
    """Under the records as shipped, no case shows an AHV figure or a risk profile, and every one says why."""
    for (name, variant), s in sheets.items():
        if variant != "seed":
            continue
        assert isinstance(s.risk_profile, NotAvailable), name
        for p in s.pensions:
            assert isinstance(p.ahv, NotAvailable) and p.ahv.record == "ahv-pension", name
        assert any(g.kind == "record_not_approved" and g.input == "risk-profile" for g in s.gaps), name


def test_measured_deviation_is_reported():
    """Runs last in this module: the largest relative deviation over every compared figure."""
    assert MEASURED, "no figure was compared"
    worst = max(MEASURED)
    print(f"\ngolden: {len(MEASURED)} figures compared, largest relative deviation {worst:.3g}")
    assert worst <= TOL and not math.isnan(worst)
