"""What lbsim reads from pcp, aggregation and fmre, checked (spec 3.8, LBSIM-14, LBSIM-15). Pure: the payloads
come in as the engines served them (``lbsim.clients`` fetches them); the checks raise the refusals of 3.7.

Found on the live engines on 29.09.2026 and handled here:

* Only scenario ReturnSets carry ``provenance.inflation_pass_through``; the base (nominal) set carries none. The
  ``accept_ipt`` check therefore applies to scenario sets only.
* A pcp Allocation's ``currency`` may be absent (published before PCP-18): refused, since its currency cannot be
  known. Its hard-currency fallback (PCP-23) sits in ``provenance.hard_currency_fallback``: refused.
* ``GET /scenarios`` lists the scenarios of every base Regime; lbsim takes those whose ``base_regime_id`` is the
  Allocation's Regime, the newest per policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .contracts import (N_STATES, SCENARIOS, AggregationRegime, AggregationScenarioListed,
                        AggregationScenarioPolicy, FmreInflation, FmreReturnSet, LbsSheet, PcpAllocation, Words)
from .errors import Conflict, InvalidRequest
from .ids import sha256
from .paths.market import RegimeInputs, StateCurve, portfolio_curve, renormalised

BASE_LABEL = Words(de="Heutige Einschätzung", en="Current assessment")
#: LBSIM-15: the raw weights must reproduce the Allocation's achieved curve to this.
ACHIEVED_TOLERANCE = 1e-9
MOVED = ("The return figures have moved since this allocation was computed; run pcp again, then ask for the "
         "outlook again.")


def check_allocation(raw: dict[str, Any], *, client_ref: str, sheet: LbsSheet, currencies: tuple[str, ...]
                     ) -> PcpAllocation:
    """The Allocation's client, currency and basis (LBSIM-14)."""
    alloc = PcpAllocation.model_validate(raw)
    if alloc.client != sheet.client_ref or alloc.client != client_ref:
        raise Conflict("The allocation belongs to another client than this Life Balance Sheet, so the two cannot "
                       "be simulated together.")
    if alloc.currency is None:
        raise InvalidRequest("The allocation does not state its currency (it was computed before pcp recorded "
                             "one), so it cannot be simulated in Swiss francs. Run pcp again.")
    if alloc.currency not in currencies:
        raise InvalidRequest(f"The allocation is in {alloc.currency}; lbsim computes in Swiss francs only.")
    fallback = alloc.provenance.hard_currency_fallback
    if fallback:
        raise InvalidRequest("The allocation's real figures fell back to another currency's inflation, so they are "
                             "not Swiss-franc figures; lbsim cannot use it.")
    return alloc


def check_base_regime(raw: dict[str, Any], alloc: PcpAllocation) -> AggregationRegime:
    regime = AggregationRegime.model_validate(raw)
    if regime.regime_id != alloc.regime_id:
        raise Conflict("aggregation answered with another Regime than the one the allocation names.")
    if regime.provenance.scenario is not None:
        raise InvalidRequest("The allocation is computed on a scenario Regime. Scenarios are simulated beside the "
                             "current assessment, never as its base; use an allocation on the base Regime.")
    return regime


def choose_scenarios(listing: list[dict[str, Any]], base_regime_id: str,
                     requested: Optional[tuple[str, ...]]) -> dict[str, str]:
    """Policy -> scenario Regime id, in the order of ``SCENARIOS``: the newest per policy on this base."""
    rows = [AggregationScenarioListed.model_validate(r) for r in listing]
    created = {r["regime_id"]: str(r.get("created_at") or "") for r in listing}
    newest: dict[str, AggregationScenarioListed] = {}
    for r in rows:
        if r.base_regime_id != base_regime_id or r.policy not in SCENARIOS:
            continue
        if r.policy not in newest or created[r.regime_id] > created[newest[r.policy].regime_id]:
            newest[r.policy] = r
    wanted = SCENARIOS if requested is None else requested
    missing = [s for s in wanted if s not in newest]
    if requested is not None and missing:
        raise InvalidRequest(f"aggregation has no {', '.join(missing)} scenario for this allocation's Regime; leave "
                             "the scenarios open or ask aggregation for it first.")
    return {s: newest[s].regime_id for s in wanted if s in newest}


def blend(regime: AggregationRegime, weights: dict[str, float]) -> list[Optional[np.ndarray]]:
    """Per date, the economies' distributions blended with the Allocation's economy weights (renormalised over
    the economies assessed on that date); ``None`` where none of them was."""
    eco = {e.code: e for e in regime.economies}
    out: list[Optional[np.ndarray]] = []
    for i in range(len(regime.dates)):
        parts = [(w, eco[c].distribution[i]) for c, w in weights.items()
                 if w > 0 and c in eco and i < len(eco[c].distribution) and eco[c].distribution[i] is not None]
        if not parts:
            out.append(None)
            continue
        total = sum(w for w, _ in parts)
        out.append(sum((w / total) * np.asarray(d, dtype=float) for w, d in parts))
    return out


def _profiles(rs: FmreReturnSet) -> dict[str, np.ndarray]:
    out = {}
    for prof in rs.instrument_profiles:
        states = sorted(prof.states, key=lambda s: s.state)
        if len(states) != N_STATES:
            raise Conflict(f"fmre's profile of {prof.key} has {len(states)} states, not {N_STATES}.")
        out[prof.key] = np.array([s.value for s in states], dtype=float)
    return out


def _inflation(raw: dict[str, Any], what: str) -> tuple[FmreInflation, np.ndarray, tuple[str, ...]]:
    infl = FmreInflation.model_validate(raw)
    if infl.currency != "CHF":
        raise Conflict(f"fmre answered with {infl.currency} inflation for {what}, not Swiss francs.")
    states = sorted(infl.states, key=lambda s: s.state)
    if len(states) != N_STATES:
        raise Conflict(f"fmre's inflation for {what} has {len(states)} states, not {N_STATES}.")
    if any(s.label == "not_computable" for s in states):
        raise InvalidRequest(f"fmre cannot compute Swiss inflation in every market state for {what}, so the paths "
                             "cannot be deflated.")
    return infl, np.array([s.log_inflation for s in states], dtype=float), tuple(s.label for s in states)


def _labels_summary(labels: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for label in labels:
        out[label] = out.get(label, 0) + 1
    return dict(sorted(out.items()))


@dataclass(frozen=True)
class MarketBundle:
    allocation: PcpAllocation
    regimes: tuple[RegimeInputs, ...]          # base first, then the scenarios in SCENARIOS order
    max_abs_diff: float
    base_log_inflation: np.ndarray
    base_inflation_labels: tuple[str, ...]
    upstream: dict[str, Any]
    key_parts: dict[str, Any]
    ipt: dict[str, Any] = field(default_factory=dict)


def assemble(*, allocation: PcpAllocation, allocation_raw: dict[str, Any], base_regime: AggregationRegime,
             base_regime_raw: dict[str, Any], scenario_ids: dict[str, str], scenario_regimes_raw: dict[str, dict],
             policies_raw: list[dict[str, Any]], return_sets_raw: dict[str, dict], check_set_raw: dict[str, Any],
             inflation_raw: dict[str, dict], accept_ipt: tuple[str, ...]) -> MarketBundle:
    """Every Regime the Monte Carlo runs, from checked upstream payloads. ``return_sets_raw`` and
    ``inflation_raw`` are keyed ``base`` and by scenario policy; ``check_set_raw`` is the base set on the
    Allocation's own basis (the nominal base set when the Allocation is nominal)."""
    weights_by_economy = allocation.provenance.regime_weights
    if not weights_by_economy:
        raise InvalidRequest("The allocation does not say how it weighted the economies, so its state distribution "
                             "cannot be rebuilt over time. Run pcp again.")

    # -- LBSIM-15: the ReturnSet the Allocation was computed on, and its achieved curve
    check_set = FmreReturnSet.model_validate(check_set_raw)
    if check_set.return_set_id != allocation.return_set_id or check_set.provenance.regime_id != allocation.regime_id:
        raise Conflict(MOVED)
    check_profiles = _profiles(check_set)
    raw_w = {i.instrument_id: i.raw_weight for i in allocation.instruments}
    missing = [iid for iid, w in raw_w.items() if iid not in check_profiles and abs(w) > 0]
    if missing:
        raise Conflict(MOVED)
    achieved = portfolio_curve({k: v for k, v in raw_w.items() if k in check_profiles}, check_profiles)
    diff = float(np.max(np.abs(achieved - np.asarray(allocation.curves.achieved, dtype=float))))
    if not diff <= ACHIEVED_TOLERANCE:
        raise Conflict(MOVED)
    weights = renormalised(raw_w)

    # -- the base Regime
    base_rs = FmreReturnSet.model_validate(return_sets_raw["base"])
    if base_rs.provenance.regime_id != allocation.regime_id:
        raise Conflict("fmre answered with the return figures of another Regime than the allocation's.")
    if allocation.basis == "nominal" and base_rs.return_set_id != allocation.return_set_id:
        raise Conflict(MOVED)
    base_profiles = _profiles(base_rs)
    if any(k not in base_profiles for k, w in weights.items() if abs(w) > 0):
        raise Conflict(MOVED)
    base_infl, base_li, base_labels = _inflation(inflation_raw["base"], "the current assessment")
    blends = blend(base_regime, weights_by_economy)
    assessed = [b for b in blends if b is not None]
    if not assessed:
        raise Conflict("aggregation's Regime carries no assessed date for the allocation's economies.")
    latest = np.asarray(allocation.curves.regime, dtype=float)
    long_run = np.mean(np.array(assessed), axis=0)
    base_curve = StateCurve(log_return=portfolio_curve({k: v for k, v in weights.items() if k in base_profiles},
                                                       base_profiles), log_inflation=base_li)
    regimes = [RegimeInputs(key="base", regime_id=allocation.regime_id, kind="base", label=BASE_LABEL,
                            return_set_id=base_rs.return_set_id, curve=base_curve, latest=latest, long_run=long_run,
                            inflation_source=_source(base_infl, "fmre /v1/inflation, Swiss francs"),
                            labels_summary=_labels_summary(base_labels))]

    # -- the scenarios
    policies = {p["policy"]: AggregationScenarioPolicy.model_validate(p) for p in policies_raw}
    ipt: dict[str, Any] = {}
    for key, rid in scenario_ids.items():
        reg = AggregationRegime.model_validate(scenario_regimes_raw[key])
        if reg.regime_id != rid or reg.provenance.scenario is None:
            raise Conflict(f"aggregation answered with another Regime than the {key} scenario lbsim asked for.")
        if reg.provenance.scenario.base_regime_id != allocation.regime_id:
            raise Conflict(f"the {key} scenario is not built on the allocation's Regime.")
        rs = FmreReturnSet.model_validate(return_sets_raw[key])
        if rs.provenance.regime_id != rid:
            raise Conflict(f"fmre answered with the return figures of another Regime than the {key} scenario.")
        pt = rs.provenance.inflation_pass_through
        if pt is None or pt.calibration_version not in accept_ipt:
            raise Conflict(f"fmre's {key} figures carry the inflation pass-through "
                           f"{pt.calibration_version if pt else 'none'}, not the one lbsim accepts "
                           f"({', '.join(accept_ipt)}); fmre has moved on.")
        ipt[key] = {"calibration_version": pt.calibration_version, "calibration_id": pt.calibration_id}
        profiles = _profiles(rs)
        if any(k not in profiles for k, w in weights.items() if abs(w) > 0):
            raise Conflict(MOVED)
        infl, li, labels = _inflation(inflation_raw[key], f"the {key} scenario")
        months = int(reg.provenance.scenario.horizon_months)
        sb = blend(reg, weights_by_economy)
        start = reg.provenance.scenario.projected_from
        idx = [i for i, d in enumerate(reg.dates) if start is not None and d >= start] or \
            list(range(len(reg.dates) - months, len(reg.dates)))
        projected = [sb[i] for i in idx]
        if any(b is None for b in projected) or len(projected) < 12:
            raise Conflict(f"aggregation's {key} scenario lacks projected months for the allocation's economies.")
        pol = policies.get(key)
        label = Words(de=pol.label_de, en=pol.label_en) if pol else Words(de=key.capitalize(), en=key.capitalize())
        regimes.append(RegimeInputs(
            key=key, regime_id=rid, kind="scenario", label=label, return_set_id=rs.return_set_id,
            curve=StateCurve(log_return=portfolio_curve({k: v for k, v in weights.items() if k in profiles},
                                                        profiles), log_inflation=li),
            projected=np.array(projected), horizon_months=months, inflation_pass_through=pt.calibration_version,
            inflation_source=_source(infl, f"fmre /v1/inflation for the {key} scenario"),
            labels_summary=_labels_summary(labels)))

    ipt_ids = sorted({v["calibration_id"] for v in ipt.values()})
    upstream = {
        "pcp": {"artefact_id": allocation.artefact_id, "contract": allocation.contract_version,
                "sha256": sha256(allocation_raw)},
        "aggregation": {allocation.regime_id: sha256(base_regime_raw),
                        **{rid: sha256(scenario_regimes_raw[k]) for k, rid in scenario_ids.items()}},
        "fmre": {"return_set_ids": {r.key: r.return_set_id for r in regimes},
                 "inflation_sha256": {k: sha256(v) for k, v in inflation_raw.items() if k == "base" or k in ipt},
                 "ipt": ipt_ids[0] if len(ipt_ids) == 1 else (ipt_ids or None)},
    }
    key_parts = {"allocation_id": allocation.artefact_id,
                 "regimes": [[r.key, r.regime_id] for r in regimes],
                 "return_set_ids": upstream["fmre"]["return_set_ids"],
                 "inflation_sha256": upstream["fmre"]["inflation_sha256"],
                 "ipt_id": upstream["fmre"]["ipt"]}
    return MarketBundle(allocation=allocation, regimes=tuple(regimes), max_abs_diff=diff, base_log_inflation=base_li,
                        base_inflation_labels=base_labels, upstream=upstream, key_parts=key_parts, ipt=ipt)


def _source(infl: FmreInflation, default: str) -> str:
    return str(infl.source or default)
