"""ReturnSet contract (spec 3.5).

Builds, validates, and serialises the versioned per-block scenario profile
that Return Estimation emits to downstream consumers. Contract rules:

- No ``mu``, ``sigma``, ``cov``, ``covariance``, or ``variance`` keys anywhere.
- ``state_grid`` must be 25; the ``state_to_scenario`` map is a partition of
  0..24 into exactly the 5 scenarios; ``scenarios`` matches the partition.
- ``house_view`` sums to 1 with a strictly positive crisis weight
  (non-zero tail per spec 5.6).
- ``regime_id`` stamps the regime under which the estimation was performed.
- ``return_set_id`` is a deterministic hash of the payload. Two runs on the
  same inputs must produce byte-identical canonical JSON and identical ids
  (spec section 8, test 8).
- Values are emitted as annualised decimals (spec 3.5 example convention),
  converting from the estimator's internal annualised-percent unit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fmre.estimate.aggregate import aggregate_to_scenarios
from fmre.estimate.block import BlockEstimate
from fmre.regime import RegimeTimeline, StateToScenario, require_scope
from fmre.registers.building_blocks import BuildingBlock
from fmre.version import (
    ESTIMATOR_VERSION,
    STATE_TO_SCENARIO_VERSION,
    UNIVERSE_VERSION,
)


CANONICAL_ROLES: tuple[str, ...] = ("gain", "income", "stabilisation", "protection")

#: The seven-value geographic vocabulary the consumer's regional allocation constraint is built over.
#: Published as `region_geo`. Order is load-bearing downstream, so it is a tuple rather than a set.
ALLOWED_REGION_GEO: tuple[str, ...] = (
    "Switzerland",
    "Europe",
    "East Asia",
    "South Asia",
    "North America",
    "South Pacific",
    "Others",
)

#: The regime signal scope, published as `region_scope`. Which Regime applies to a block, not where it
#: is. Kept strictly separate from `region_geo`.
ALLOWED_REGION_SCOPE: tuple[str, ...] = ("Europe", "Americas", "Asia", "Sino", "Global")

#: The block's home scenario, capitalised as the register authors it. `Boom` is permitted although the
#: seed universe does not use it, so the downstream role by scenario grid keeps a stable width.
ALLOWED_HOME_SCENARIO: tuple[str, ...] = (
    "Crisis",
    "Contraction",
    "Stagnation",
    "Expansion",
    "Boom",
)

#: The fallback house view, used only when no Regime distributions are available to derive one from.
#:
#: **Superseded as the normal path on 3 August 2026 (DECISIONS.md M64).** It was the house view every published
#: ReturnSet carried, and it disagreed with the model that produced the Regime it was weighting: 35% on
#: crisis-plus-contraction against the Regime's own 43.9% through the cycle and 51.4% spot. The system was
#: carrying two macro views and reconciling them nowhere. `house_view_from_regime` below now derives it, and this
#: constant survives only for a synthetic timeline that publishes no distributions.
#:
#: Kept rather than deleted because it is still the shape a hand-authored Investment-Committee view would take,
#: and the IC is entitled to state one that differs from the model — see D5. What is no longer acceptable is a
#: divergence nobody declared.
DEFAULT_HOUSE_VIEW: dict[str, float] = {
    "crisis": 0.15,
    "contraction": 0.20,
    "stagnation": 0.25,
    "expansion": 0.30,
    "boom": 0.10,
}
# Sums to 1.0; crisis weight > 0 (spec 5.6). Investment-Committee input per D5.


def house_view_from_regime(
    regime_payload: dict[str, Any],
    state_to_scenario: dict[str, str],
) -> dict[str, float]:
    """Derive the house view from the Regime's own distributions, averaged through the cycle.

    `omega_g = mean over dates of (sum of the 25-bin weights falling in scenario g)`.

    **Why the soft distributions and not the path.** The Regime publishes both: `path` gives one hard state per
    month, `distributions` gives the full 25-bin belief. Counting the path instead would put **1.69%** on boom
    against the distributions' 12.27%, because a hard assignment rarely lands in the extreme bins even when the
    model holds real mass there. M57 established that the hard reading is the unstable one — the argmax moved ten
    bins on a 0.4pp margin — so the distribution is the object to trust.

    **Why averaged and not spot.** The 2024-12 reading is `bimodal` on a 0.55pp mode margin, and it puts 51.4% on
    the downside against the through-cycle 43.9%. A house view weighting a one-year ReturnSet is a strategic
    input; deriving it from a single knife-edge month would import that instability into every published expected
    return, every goal buffer and every mandate. The average over the published window is the reproducible
    strategic version of the same reading. Decided by the CIO on 3 August 2026 from three measured options.

    Raises:
        ValueError: If the payload carries no distributions, or a state has no scenario, or the result does not
            sum to one. A silently wrong house view would misprice every block in the register.
    """
    distributions = regime_payload.get("distributions") or []
    if not distributions:
        raise ValueError(
            "the Regime carries no distributions, so no house view can be derived from it. Pass one explicitly "
            "or fall back to DEFAULT_HOUSE_VIEW, deliberately and visibly."
        )
    out: dict[str, float] = {}
    for entry in distributions:
        weights = entry["weights"]
        for index, weight in enumerate(weights):
            scenario = state_to_scenario.get(str(index))
            if scenario is None:
                raise ValueError(
                    f"state {index} has no scenario in the state_to_scenario map, so the Regime's distribution "
                    f"cannot be aggregated to a house view"
                )
            out[scenario] = out.get(scenario, 0.0) + float(weight) / len(distributions)
    total = sum(out.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            f"the derived house view sums to {total!r} rather than one. The Regime's distributions are expected "
            f"to be probability vectors, so this is an upstream break rather than something to normalise here."
        )
    return out

_FORBIDDEN_MOMENT_KEYS: frozenset[str] = frozenset(
    {"mu", "sigma", "cov", "covariance", "variance"}
)


class ReturnSetValidationError(ValueError):
    """Raised on any ReturnSet schema or invariant violation."""


@dataclass(frozen=True, slots=True)
class ReturnSet:
    return_set_id: str
    regime_id: str
    as_of: str
    model_version: str
    universe_version: str
    state_to_scenario_version: str
    horizon_years: float
    state_grid: int
    scenarios: tuple[str, ...]
    state_to_scenario: dict[str, str]
    house_view: dict[str, float]
    role_profiles: dict[str, dict[str, float]]
    building_blocks: list[dict[str, Any]]
    provenance: dict[str, Any]
    values_unit: str = "annualised_decimal"

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh, deeply-copied payload. Deep copy is required so
        that callers can mutate the returned dict (e.g. in validation tests)
        without corrupting the frozen ReturnSet's internal state.
        """
        return copy.deepcopy({
            "return_set_id": self.return_set_id,
            "regime_id": self.regime_id,
            "as_of": self.as_of,
            "model_version": self.model_version,
            "universe_version": self.universe_version,
            "state_to_scenario_version": self.state_to_scenario_version,
            "horizon_years": self.horizon_years,
            "state_grid": self.state_grid,
            "scenarios": list(self.scenarios),
            "state_to_scenario": self.state_to_scenario,
            "house_view": self.house_view,
            "role_profiles": self.role_profiles,
            "building_blocks": self.building_blocks,
            "provenance": self.provenance,
            "values_unit": self.values_unit,
        })


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_returnset(
    estimates: dict[int, BlockEstimate],
    blocks_by_id: dict[int, BuildingBlock],
    state_to_scenario: StateToScenario,
    timeline: RegimeTimeline,
    house_view: dict[str, float] | None = None,
    horizon_years: float = 1.0,
    universe_version: str = UNIVERSE_VERSION,
    model_version: str = ESTIMATOR_VERSION,
    calibration_window: tuple[str, str] | None = None,
    scope: str | None = None,
) -> ReturnSet:
    """Assemble a ReturnSet from block estimates, the timeline, and the map.

    ``estimates`` must be keyed by block_id, ``blocks_by_id`` by the same.
    ``scope``, when provided, is validated against ``timeline.economy_scope``
    via ``require_scope``; a mismatch raises ``TimelineValidationError``.
    """
    if scope is not None:
        require_scope(timeline, scope)

    hv = _validate_house_view(house_view or DEFAULT_HOUSE_VIEW, state_to_scenario)
    freq = timeline.state_frequencies(window=calibration_window) if calibration_window else timeline.state_frequencies()

    def _pct_to_decimal(v: float) -> float:
        return v / 100.0

    bb_list: list[dict[str, Any]] = []
    role_agg: dict[str, list[dict[str, float]]] = {r: [] for r in CANONICAL_ROLES}

    for bid in sorted(estimates.keys()):
        est = estimates[bid]
        sp = aggregate_to_scenarios(est, state_to_scenario, freq)

        profile_state_decimal = [_pct_to_decimal(v) for v in est.profile_by_state]
        profile_scen_decimal = {s: _pct_to_decimal(sp.profile_by_scenario[s]) for s in sp.scenario_order}

        # The block's register metadata travels with its profile.
        #
        # Downstream cannot assemble an allocation constraint without it: the regional, currency, role,
        # capital-type, liquidity, ESG, phase and asset-class blocks are all per-instrument
        # classifications, and the portfolio map is a role by home-scenario grid. Leaving them off the
        # contract forced the consumer either to read this programme's seed CSV directly, which is an
        # unversioned dependency on our internals, or to fabricate them. Both are worse than publishing.
        block = blocks_by_id.get(est.block_id)
        if block is None:
            raise ReturnSetValidationError(
                f"no register entry for block_id {est.block_id}, so its classification metadata cannot "
                f"be published. The ReturnSet does not carry a block it cannot describe."
            )

        bb_dict: dict[str, Any] = {
            "bb_id": est.block_id,
            "name": block.name_en,
            "ticker": est.ticker,
            "role": est.canonical_role.lower(),
            # Two distinct fields, deliberately. `region_geo` is where the exposure is and drives the
            # regional constraint; `region_scope` is which macro Regime applies and drives regime
            # selection. Conflating them is the defect that decisions.md D11 fixes.
            "region_geo": block.region_geo.value,
            "region_scope": block.region.value,
            "home_scenario": block.home_scenario.value,
            "currency": block.currency,
            "asset_class": block.asset_class.value,
            "economic_phase": block.economic_phase.value,
            "capital_type": block.capital_type.value,
            "liquidity": block.liquidity.value,
            "esg": int(block.esg),
            "profile_by_state": profile_state_decimal,
            "profile_by_scenario": profile_scen_decimal,
            "estimation": {
                "methods_by_state": list(est.methods),
                "n_obs_by_state": list(est.n_obs_by_state),
                "coverage": est.coverage,
                "label": "model-derived",
                "mu_unit_internal": est.mu_unit,
                "weighting_note": sp.weighting_note,
                "n_obs_total": est.n_obs_total,
            },
        }
        bb_list.append(bb_dict)
        role_agg[est.canonical_role.lower()].append(profile_scen_decimal)

    role_profiles: dict[str, dict[str, float]] = {}
    for role in CANONICAL_ROLES:
        profiles = role_agg[role]
        if not profiles:
            continue
        role_profiles[role] = {
            scen: sum(p[scen] for p in profiles) / len(profiles)
            for scen in state_to_scenario.scenario_order
        }

    sts_dict = {str(i): state_to_scenario.mapping[i] for i in range(state_to_scenario.state_grid)}

    provenance: dict[str, Any] = {
        "data_vintage": timeline.provenance.get("data_vintage", timeline.as_of),
        "series_sources": timeline.provenance.get("sources", []),
        "calibration_window": _fmt_window(calibration_window),
        "timeline_id": timeline.regime_timeline_id,
        "timeline_model_version": timeline.model_version,
        "current_state": timeline.current.state,
        "current_phase": timeline.current.phase,
        "current_saturation_pct": timeline.current.saturation_pct,
    }

    payload_for_hash = {
        "regime_id": timeline.current.regime_id,
        "as_of": timeline.as_of,
        "model_version": model_version,
        "universe_version": universe_version,
        "state_to_scenario_version": state_to_scenario.version,
        "horizon_years": horizon_years,
        "state_grid": state_to_scenario.state_grid,
        "scenarios": list(state_to_scenario.scenario_order),
        "state_to_scenario": sts_dict,
        "house_view": dict(hv),
        "role_profiles": role_profiles,
        "building_blocks": bb_list,
        "provenance": provenance,
        "values_unit": "annualised_decimal",
    }
    return_set_id = _hash_id(payload_for_hash)

    return ReturnSet(
        return_set_id=return_set_id,
        regime_id=timeline.current.regime_id,
        as_of=timeline.as_of,
        model_version=model_version,
        universe_version=universe_version,
        state_to_scenario_version=state_to_scenario.version,
        horizon_years=horizon_years,
        state_grid=state_to_scenario.state_grid,
        scenarios=state_to_scenario.scenario_order,
        state_to_scenario=sts_dict,
        house_view=hv,
        role_profiles=role_profiles,
        building_blocks=bb_list,
        provenance=provenance,
    )


def _hash_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"RS-{digest}"


def _validate_house_view(hv: dict[str, float], sts: StateToScenario) -> dict[str, float]:
    expected = set(sts.scenario_order)
    got = set(hv.keys())
    missing = expected - got
    extras = got - expected
    if missing:
        raise ReturnSetValidationError(f"house_view missing scenarios: {sorted(missing)}")
    if extras:
        raise ReturnSetValidationError(f"house_view has unknown scenarios: {sorted(extras)}")
    for scen, w in hv.items():
        if w < 0:
            raise ReturnSetValidationError(f"house_view[{scen}] is negative: {w}")
    total = sum(hv.values())
    if abs(total - 1.0) > 1e-9:
        raise ReturnSetValidationError(f"house_view must sum to 1, got {total}")
    if hv.get("crisis", 0.0) <= 0.0:
        raise ReturnSetValidationError("house_view crisis weight must be > 0 (spec 5.6 non-zero tail)")
    return {scen: float(hv[scen]) for scen in sts.scenario_order}


def _fmt_window(window: tuple[str, str] | None) -> str | None:
    if window is None:
        return None
    return f"{window[0]} to {window[1]}"


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate_returnset(payload: dict[str, Any]) -> None:
    """Validate a ReturnSet payload. Raises ``ReturnSetValidationError`` on
    the first violation with a targeted message."""
    required = {
        "return_set_id", "regime_id", "as_of", "model_version", "universe_version",
        "state_to_scenario_version", "horizon_years", "state_grid", "scenarios",
        "state_to_scenario", "house_view", "role_profiles", "building_blocks",
        "provenance", "values_unit",
    }
    missing = required - set(payload.keys())
    if missing:
        raise ReturnSetValidationError(f"missing required top-level fields: {sorted(missing)}")

    if payload["state_grid"] != 25:
        raise ReturnSetValidationError(f"state_grid must be 25, got {payload['state_grid']!r}")

    scenarios = payload["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != 5:
        raise ReturnSetValidationError(f"scenarios must be a list of 5 entries, got {scenarios!r}")
    allowed_scenarios = {"crisis", "contraction", "stagnation", "expansion", "boom"}
    if set(scenarios) != allowed_scenarios:
        raise ReturnSetValidationError(f"scenarios must be exactly {sorted(allowed_scenarios)}, got {sorted(set(scenarios))}")

    sts = payload["state_to_scenario"]
    keys = sorted(int(k) for k in sts.keys())
    if keys != list(range(25)):
        raise ReturnSetValidationError("state_to_scenario keys must be exactly 0..24")
    for k, v in sts.items():
        if v not in allowed_scenarios:
            raise ReturnSetValidationError(f"state_to_scenario[{k}] = {v!r} is not a known scenario")

    hv = payload["house_view"]
    if set(hv.keys()) != allowed_scenarios:
        raise ReturnSetValidationError("house_view must have exactly all 5 scenarios")
    total = sum(hv.values())
    if abs(total - 1.0) > 1e-6:
        raise ReturnSetValidationError(f"house_view weights must sum to 1, got {total}")
    if hv.get("crisis", 0.0) <= 0.0:
        raise ReturnSetValidationError("house_view crisis weight must be > 0 (non-zero tail)")

    rp = payload["role_profiles"]
    expected_roles = set(CANONICAL_ROLES)
    if not set(rp.keys()).issubset(expected_roles):
        raise ReturnSetValidationError(
            f"role_profiles has unknown roles: {sorted(set(rp.keys()) - expected_roles)}"
        )
    for role, prof in rp.items():
        if set(prof.keys()) != allowed_scenarios:
            raise ReturnSetValidationError(f"role_profiles[{role}] scenarios must match the 5 scenarios")

    for i, bb in enumerate(payload["building_blocks"]):
        for k in (
            "bb_id", "name", "ticker", "role", "region_geo", "region_scope", "home_scenario",
            "currency", "asset_class", "economic_phase", "capital_type", "liquidity", "esg",
            "profile_by_state", "profile_by_scenario", "estimation",
        ):
            if k not in bb:
                raise ReturnSetValidationError(f"building_blocks[{i}] missing field {k!r}")
        if bb["role"] not in expected_roles:
            raise ReturnSetValidationError(f"building_blocks[{i}].role={bb['role']!r} not canonical")
        if bb["region_geo"] not in ALLOWED_REGION_GEO:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].region_geo={bb['region_geo']!r} is not one of "
                f"{sorted(ALLOWED_REGION_GEO)}. The consumer's regional constraint is assembled over "
                f"exactly this vocabulary, so an unknown value would silently drop the block's exposure."
            )
        if bb["region_scope"] not in ALLOWED_REGION_SCOPE:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].region_scope={bb['region_scope']!r} is not one of "
                f"{sorted(ALLOWED_REGION_SCOPE)}"
            )
        if bb["home_scenario"] not in ALLOWED_HOME_SCENARIO:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].home_scenario={bb['home_scenario']!r} is not one of "
                f"{sorted(ALLOWED_HOME_SCENARIO)}"
            )
        if not isinstance(bb["esg"], int) or isinstance(bb["esg"], bool):
            raise ReturnSetValidationError(
                f"building_blocks[{i}].esg must be an integer score, got {bb['esg']!r}"
            )
        if len(bb["profile_by_state"]) != 25:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].profile_by_state length={len(bb['profile_by_state'])}, expected 25"
            )
        if set(bb["profile_by_scenario"].keys()) != allowed_scenarios:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].profile_by_scenario scenarios mismatch"
            )
        est = bb["estimation"]
        for k in ("methods_by_state", "n_obs_by_state", "coverage", "label"):
            if k not in est:
                raise ReturnSetValidationError(f"building_blocks[{i}].estimation missing {k!r}")
        if len(est["n_obs_by_state"]) != 25:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].estimation.n_obs_by_state length != 25"
            )
        if len(est["methods_by_state"]) != 25:
            raise ReturnSetValidationError(
                f"building_blocks[{i}].estimation.methods_by_state length != 25"
            )
        if est["label"] != "model-derived":
            raise ReturnSetValidationError(
                f"building_blocks[{i}].estimation.label must be 'model-derived' (spec house rules)"
            )
        if est["coverage"] not in ("full", "partial", "borrowed", "seed"):
            raise ReturnSetValidationError(
                f"building_blocks[{i}].estimation.coverage={est['coverage']!r} unknown"
            )

    _assert_no_moment_keys(payload)


def _assert_no_moment_keys(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _FORBIDDEN_MOMENT_KEYS:
                raise ReturnSetValidationError(
                    f"forbidden moment key '{k}' at {path or '<root>'}. "
                    f"ReturnSet must carry profiles, not moments (spec 3.5)."
                )
            _assert_no_moment_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_moment_keys(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Serialise / deserialise
# ---------------------------------------------------------------------------


def to_canonical_json(rs: ReturnSet) -> str:
    """Canonical JSON: sorted keys, compact separators, ASCII-safe.

    Determinism relies on this: same inputs produce byte-identical output.
    """
    return json.dumps(rs.to_dict(), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def write_returnset(rs: ReturnSet, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_canonical_json(rs), encoding="utf-8")
    return p


def load_returnset(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    validate_returnset(data)
    return data


# ---------------------------------------------------------------------------
# House-view superposition (spec 5.6)
# ---------------------------------------------------------------------------


def superpose_role_expectations(returnset: ReturnSet) -> dict[str, float]:
    """Collapse the 5-scenario role profiles into per-role scalars via the
    house-view weights.

    ``E[R_role] = sum_s omega_s * role_profile[role][s]``

    Emitted as a diagnostic; downstream consumers may compute this
    themselves from the ReturnSet payload.
    """
    hv = returnset.house_view
    return {
        role: float(sum(hv[s] * prof[s] for s in returnset.scenarios))
        for role, prof in returnset.role_profiles.items()
    }


def superpose_block_expectations(returnset: ReturnSet) -> dict[int, float]:
    """Per-block scalar expected return: ``E[R_b] = sum_s omega_s * P_{b,s}``."""
    hv = returnset.house_view
    return {
        int(bb["bb_id"]): float(sum(hv[s] * bb["profile_by_scenario"][s] for s in returnset.scenarios))
        for bb in returnset.building_blocks
    }
