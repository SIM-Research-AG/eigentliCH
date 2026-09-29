"""Read the ReturnSet contract into the `BB` matrix and the per-instrument metadata.

The ReturnSet is produced by the Fund Map and Return Estimation programme and consumed here read-only.
It carries, per building block, a 25-length return profile ordered crisis-low to boom-high, plus the
register classification the constraints and the portfolio map need.

Label normalisation happens once, here, so that upstream spelling never reaches the optimiser. The
mappings are configuration, not code: `Growth` becomes `Gain`, `Stabilization` becomes `Stabilisation`,
`Maturing` becomes `Build-up`, `Optimizing` becomes `Optimisation`, `Real Estate` becomes `Real Assets`.
See decisions.md D3, D5 and D7.

Two fields that must never be confused: `region_geo` is where the exposure is and drives the regional
constraint; `region_scope` is which macro Regime applies and drives nothing here except provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from pcp.config import Config
from pcp.contracts import STATE_GRID, BuildingBlock, ContractError, ReturnSet

#: Fields the consumer cannot proceed without. A ReturnSet lacking any of them predates the re@0.2.0
#: contract, and the fix is to republish it rather than to substitute a value here.
REQUIRED_BLOCK_FIELDS: tuple[str, ...] = (
    "bb_id",
    "name",
    "ticker",
    "role",
    "region_geo",
    "region_scope",
    "home_scenario",
    "currency",
    "asset_class",
    "economic_phase",
    "capital_type",
    "liquidity",
    "esg",
    "profile_by_state",
)

#: Keys whose presence means the payload carries moments rather than profiles. The curve fit has no use
#: for them and their presence signals a producer that has drifted off the contract.
FORBIDDEN_KEYS: frozenset[str] = frozenset({"mu", "sigma", "cov", "covariance", "variance"})


def load_returnset(path: Path | str, config: Config) -> ReturnSet:
    """Read and normalise a ReturnSet.

    Raises:
        ContractError: If the file is absent, malformed, carries moments, or predates the contract
            version that publishes per-instrument classification.
    """
    source = Path(path)
    if not source.exists():
        raise ContractError(
            f"ReturnSet not found: {source}. Publish it with 'fmre build-returnset --timeline ...'."
        )
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return returnset_from_payload(payload, config, source=source)


def returnset_from_payload(
    payload: Mapping[str, Any],
    config: Config,
    source: Path | str | None = None,
) -> ReturnSet:
    where = f" in {source}" if source else ""

    required = (
        "return_set_id", "regime_id", "as_of", "model_version", "universe_version",
        "state_grid", "scenarios", "building_blocks", "values_unit",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ContractError(f"ReturnSet is missing field(s) {missing}{where}")

    _refuse_moments(payload, where)

    if int(payload["state_grid"]) != STATE_GRID:
        raise ContractError(
            f"ReturnSet{where} declares state_grid={payload['state_grid']}, expected {STATE_GRID}"
        )

    blocks = tuple(
        _block_from_payload(entry, index, config, where)
        for index, entry in enumerate(payload["building_blocks"])
    )
    if not blocks:
        raise ContractError(f"ReturnSet{where} carries no building blocks")

    state_to_scenario = {
        int(key): str(value) for key, value in dict(payload.get("state_to_scenario", {})).items()
    }

    return ReturnSet(
        return_set_id=str(payload["return_set_id"]),
        regime_id=str(payload["regime_id"]),
        as_of=str(payload["as_of"]),
        model_version=str(payload["model_version"]),
        universe_version=str(payload["universe_version"]),
        state_to_scenario_version=str(payload.get("state_to_scenario_version", "unknown")),
        horizon_years=float(payload.get("horizon_years", 1.0)),
        values_unit=str(payload["values_unit"]),
        state_grid=int(payload["state_grid"]),
        scenarios=tuple(str(s) for s in payload["scenarios"]),
        state_to_scenario=state_to_scenario,
        house_view={str(k): float(v) for k, v in dict(payload.get("house_view", {})).items()},
        blocks=blocks,
        provenance=dict(payload.get("provenance", {})),
    )


def _block_from_payload(
    entry: Mapping[str, Any],
    index: int,
    config: Config,
    where: str,
) -> BuildingBlock:
    absent = [field for field in REQUIRED_BLOCK_FIELDS if field not in entry]
    if absent:
        # Name the likely cause. The commonest reason for this failure is a ReturnSet built by an older
        # producer, and saying so saves the reader working it out from a field list.
        hint = ""
        if "region" in entry and "region_geo" not in entry:
            hint = (
                " This payload carries the old ambiguous 'region' field, so it was produced before "
                "re@0.2.0. Rebuild it: the PCP cannot infer geography from a regime signal scope."
            )
        raise ContractError(
            f"building_blocks[{index}]{where} is missing field(s) {absent}.{hint}"
        )

    profile = np.asarray([float(v) for v in entry["profile_by_state"]], dtype=float)
    if profile.shape != (STATE_GRID,):
        raise ContractError(
            f"building_blocks[{index}] (bb_id {entry['bb_id']}){where} has a profile of length "
            f"{profile.shape[0]}, expected {STATE_GRID}"
        )

    role = config.map_label("role", _canonical_case(str(entry["role"])))
    phase = config.map_label("phase", str(entry["economic_phase"]))
    asset_class = config.map_label("asset_class", str(entry["asset_class"]))

    vocabularies = config.vocabularies
    _require_in(vocabularies.roles.labels, role, "role", index, entry, where)
    _require_in(vocabularies.phases.labels, phase, "economic_phase", index, entry, where)
    _require_in(vocabularies.asset_classes.labels, asset_class, "asset_class", index, entry, where)
    _require_in(
        vocabularies.scenarios.labels, str(entry["home_scenario"]), "home_scenario", index, entry, where
    )
    _require_in(vocabularies.liquidity.labels, str(entry["liquidity"]), "liquidity", index, entry, where)
    _require_in(vocabularies.regions.labels, str(entry["region_geo"]), "region_geo", index, entry, where)

    return BuildingBlock(
        bb_id=int(entry["bb_id"]),
        name=str(entry["name"]),
        ticker=str(entry["ticker"]),
        role=role,
        home_scenario=str(entry["home_scenario"]),
        region_geo=str(entry["region_geo"]),
        region_scope=str(entry["region_scope"]),
        currency=str(entry["currency"]),
        asset_class=asset_class,
        economic_phase=phase,
        capital_type=str(entry["capital_type"]),
        liquidity=str(entry["liquidity"]),
        esg=float(entry["esg"]),
        profile_by_state=profile,
        estimation=dict(entry.get("estimation", {})),
    )


def _canonical_case(label: str) -> str:
    """Title-case a contract label so it matches the vocabularies.

    The ReturnSet publishes roles in lower case (`gain`), while the constraint vocabularies are the
    framework's title-case names (`Gain`). Only the first letter is raised, so a multi-word label keeps
    its own casing rather than being mangled by `str.title`.
    """
    return label[:1].upper() + label[1:] if label else label


def _require_in(
    allowed: tuple[str, ...],
    value: str,
    field: str,
    index: int,
    entry: Mapping[str, Any],
    where: str,
) -> None:
    if value not in allowed:
        raise ContractError(
            f"building_blocks[{index}] (bb_id {entry.get('bb_id')}, {entry.get('name')!r}){where} has "
            f"{field}={value!r}, which is not in the vocabulary {list(allowed)}. Correct it upstream or "
            f"add a mapping under ingest_maps: the PCP does not bucket an unrecognised classification, "
            f"because that would move the block's weight against a bound the mandate never set."
        )


def _refuse_moments(payload: Any, where: str, path: str = "") -> None:
    """Refuse a payload carrying mu, sigma, or a covariance anywhere.

    The model of record integrates profiles and has no use for moments. Their presence means the producer
    has drifted off the contract, and accepting the payload would let a mean-variance quantity reach a
    programme that deliberately does not use one.
    """
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                raise ContractError(
                    f"ReturnSet{where} carries the forbidden key {key!r} at {path or '<root>'}. The "
                    f"contract carries profiles, not moments."
                )
            _refuse_moments(value, where, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for position, value in enumerate(payload):
            _refuse_moments(value, where, f"{path}[{position}]")
