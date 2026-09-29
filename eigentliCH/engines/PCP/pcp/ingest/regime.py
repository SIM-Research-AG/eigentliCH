"""Read published Regime timelines and blend them into the single `M` a mandate optimises against.

Two jobs.

**Read.** A Regime timeline is produced by the macro programme and consumed here by reference. It
carries a 25-length probability vector per month, ordered crisis-low to boom-high, plus the modal state
path and a `regime_id`. Nothing here recomputes it.

**Blend.** A mandate names a market scope (Americas, Europe, Asia, Sino, Global), which selects a
seven-slot country-weight vector `cw` over (China, EU, India, US, Switzerland, Brazil, UK). The blended
regime for a period is `M = sum_k cw[k] * M_k`, the weighted sum of the per-economy distributions. This
reproduces `Dataloader.m` line 18, where the same blend was formed from the per-country `CRS.Signal_*`
matrices.

Why this adapter lives here rather than in the Regime producer: the weights are selected by the
mandate's scope, so they are a mandate-side concern. The producer publishes one timeline per economy and
takes no view on how a client portfolio should weight them (decisions.md D10).

**A missing economy is a failure, not a renormalisation.** If a slot carries weight and its Regime is not
published, the blend cannot represent the scope the mandate asked for. Dropping the slot and
renormalising would silently answer a different question: a Global mandate missing China would become a
Global-without-China mandate while still reporting itself as Global.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from pcp.config import Config
from pcp.contracts import STATE_GRID, ContractError, RegimeTimeline


class RegimeNotFound(ContractError):
    """Raised when a required Regime timeline has not been published."""


# ---------------------------------------------------------------------------
# Read one timeline
# ---------------------------------------------------------------------------


def load_regime(path: Path | str) -> RegimeTimeline:
    """Read one published Regime timeline.

    Requires the `distributions` block. A timeline carrying only the integer state path would force this
    programme to expand a path into a distribution, and the shape of that expansion (one-hot, or a kernel,
    and how wide) is a modelling decision the macro programme owns. Refusing is the honest response.
    """
    source = Path(path)
    if not source.exists():
        raise RegimeNotFound(
            f"regime timeline not found: {source}. Publish it with 'macrofield regime <economy>'."
        )
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return regime_from_payload(payload, source=source)


def regime_from_payload(payload: Mapping[str, Any], source: Path | str | None = None) -> RegimeTimeline:
    """Validate a timeline payload and return the typed object."""
    where = f" in {source}" if source else ""
    required = (
        "regime_timeline_id", "economy_scope", "model_version", "as_of", "period", "state_grid",
        "current", "provenance",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ContractError(f"regime timeline is missing field(s) {missing}{where}")

    if "distributions" not in payload:
        raise ContractError(
            f"the regime timeline{where} carries no 'distributions' block, only a state path. The "
            f"objective integrates a 25-length distribution per period, and expanding a path into one is "
            f"a modelling decision this programme will not make on the producer's behalf. Republish with "
            f"distributions."
        )

    rows = list(payload["distributions"])
    if not rows:
        raise ContractError(f"the regime timeline{where} carries an empty distributions block")

    dates: list[str] = []
    weights: list[list[float]] = []
    for index, row in enumerate(rows):
        if "date" not in row or "weights" not in row:
            raise ContractError(
                f"distributions[{index}]{where} needs both 'date' and 'weights'"
            )
        vector = list(row["weights"])
        if len(vector) != STATE_GRID:
            raise ContractError(
                f"distributions[{index}] ({row['date']}){where} has {len(vector)} weights, expected "
                f"{STATE_GRID}"
            )
        dates.append(str(row["date"]))
        weights.append([float(v) for v in vector])

    if dates != sorted(dates):
        raise ContractError(f"the regime timeline{where} is not in ascending date order")

    current = payload["current"]
    if "regime_id" not in current or "state" not in current:
        raise ContractError(f"regime timeline 'current' block{where} needs regime_id and state")

    return RegimeTimeline(
        regime_timeline_id=str(payload["regime_timeline_id"]),
        economy_scope=str(payload["economy_scope"]),
        model_version=str(payload["model_version"]),
        as_of=str(payload["as_of"]),
        period=str(payload["period"]),
        state_grid=int(payload["state_grid"]),
        dates=tuple(dates),
        distributions=np.asarray(weights, dtype=float),
        regime_id=str(current["regime_id"]),
        current_state=int(current["state"]),
        phase=current.get("phase"),
        saturation_pct=current.get("saturation_pct"),
        provenance=dict(payload["provenance"]),
    )


# ---------------------------------------------------------------------------
# The country-weight adapter
# ---------------------------------------------------------------------------


def resolve_country_weights(market: str, config: Config) -> dict[str, float]:
    """The seven-slot weight vector for a market scope, as a slot-to-weight mapping.

    An explicit `country_weights.overwrite` takes precedence, reproducing the Market_Settings overwrite
    flag. A scope with no preset falls back to the configured `equal` vector, as the reference
    implementation's else-branch did, and the fallback is reported by the caller rather than hidden.
    """
    slots = list(config.get("country_weights.order"))
    overwrite = config.get_or("country_weights.overwrite", None)
    if overwrite is not None:
        return {slot: float(w) for slot, w in zip(slots, overwrite)}

    presets = dict(config.get("country_weights.presets"))
    vector = presets.get(market)
    if vector is None:
        vector = presets["equal"]
    return {slot: float(w) for slot, w in zip(slots, vector)}


def expand_to_economies(
    slot_weights: Mapping[str, float],
    config: Config,
) -> dict[str, float]:
    """Flatten slot weights onto economy weights.

    A slot may name several economies (the EU slot has no Regime of its own, so it is its members
    weighted by GDP). Flattening is exact: a slot at weight `w` whose members carry `m_i` contributes
    `w * m_i` to each. Zero-weight slots are dropped, so an unpublished economy behind a slot the mandate
    does not use never becomes a problem.
    """
    members_by_slot = dict(config.get("country_weights.economies_for_slot"))
    economy_weights: dict[str, float] = {}
    for slot, weight in slot_weights.items():
        if weight <= 0.0:
            continue
        for economy, share in members_by_slot[slot].items():
            economy_weights[economy] = economy_weights.get(economy, 0.0) + weight * float(share)
    return economy_weights


@dataclass(frozen=True, slots=True)
class RegimeBlend:
    """The blended Regime a mandate is optimised against.

    Attributes:
        distributions: Rows by 25, one per period common to every contributing economy.
        dates: One label per row.
        regime_id: Identifies the blend. Derived from the contributing regime_ids and the weights, so a
            change in either produces a different id and a stamped allocation cannot be misattributed.
        regime_timeline_id: Likewise for the timeline.
        economy_weights: The flattened economy weights actually applied.
        slot_weights: The seven-slot vector the market scope selected.
        contributors: Per economy, its timeline and regime identifiers and its window.
        market: The mandate market scope.
        as_of: The last period covered.
        model_version: The producer version, where every contributor agrees on it.
        notes: Anything a reader must know, including any window truncation.
    """

    distributions: np.ndarray
    dates: tuple[str, ...]
    regime_id: str
    regime_timeline_id: str
    economy_weights: dict[str, float]
    slot_weights: dict[str, float]
    contributors: dict[str, dict[str, Any]]
    market: str
    as_of: str
    model_version: str
    notes: tuple[str, ...] = ()

    def as_timeline(self) -> RegimeTimeline:
        """The blend as a RegimeTimeline, which is what the optimiser consumes."""
        latest = np.asarray(self.distributions, dtype=float)[-1]
        return RegimeTimeline(
            regime_timeline_id=self.regime_timeline_id,
            economy_scope=self.market,
            model_version=self.model_version,
            as_of=self.as_of,
            period="M",
            state_grid=STATE_GRID,
            dates=self.dates,
            distributions=np.asarray(self.distributions, dtype=float),
            regime_id=self.regime_id,
            current_state=int(np.argmax(latest)),
            phase=self._agreed("phase"),
            saturation_pct=None,
            provenance={
                "market": self.market,
                "slot_weights": dict(self.slot_weights),
                "economy_weights": dict(self.economy_weights),
                "contributors": dict(self.contributors),
                "blend": "weighted sum of per-economy distributions, reproducing Dataloader.m line 18",
                "notes": list(self.notes),
            },
        )

    def _agreed(self, key: str) -> Any:
        """A contributor field where every contributor agrees, else None.

        A blend of economies in different capital-cycle phases has no single phase, and reporting one
        would assert an agreement that does not exist.
        """
        values = {c.get(key) for c in self.contributors.values()}
        if len(values) == 1:
            return values.pop()
        return None


def blend_regimes(
    market: str,
    config: Config,
    directory: Path | str | None = None,
    timelines: Mapping[str, RegimeTimeline] | None = None,
) -> RegimeBlend:
    """Blend the published per-economy Regimes into the single `M` for a market scope.

    Args:
        market: The mandate's market scope.
        config: Loaded configuration, for the presets and the slot membership.
        directory: Where the published timelines live. Defaults to `contracts.regime_timeline_dir`.
        timelines: Pre-loaded timelines by economy code, for tests and for the cockpit's cache.

    Returns:
        The blend.

    Raises:
        RegimeNotFound: If a weighted slot's economy has no published timeline.
        ContractError: If the contributing timelines share no period.
    """
    slot_weights = resolve_country_weights(market, config)
    economy_weights = expand_to_economies(slot_weights, config)
    if not economy_weights:
        raise ContractError(
            f"market scope {market!r} resolves to no weighted economy, so no Regime can be blended"
        )

    notes: list[str] = []
    presets = dict(config.get("country_weights.presets"))
    if config.get_or("country_weights.overwrite", None) is not None:
        notes.append(
            "the country weights came from the configured overwrite, not from the market scope's preset."
        )
    elif market not in presets:
        notes.append(
            f"market scope {market!r} has no preset, so the equal-weight fallback was used, reproducing "
            f"the reference implementation's else-branch. The blend is not scoped to {market!r}."
        )

    # ---- load every contributor ------------------------------------------
    root = Path(directory) if directory is not None else _default_directory(config)
    loaded: dict[str, RegimeTimeline] = {}
    for economy in sorted(economy_weights):
        if timelines is not None and economy in timelines:
            loaded[economy] = timelines[economy]
            continue
        candidate = root / f"{economy}.json"
        if not candidate.exists():
            raise RegimeNotFound(
                f"market scope {market!r} puts weight {economy_weights[economy]:.4f} on economy "
                f"{economy!r}, but no Regime timeline is published at {candidate}. The blend is not "
                f"renormalised over the economies that happen to be available, because that would "
                f"answer a differently scoped question while still reporting itself as {market!r}. "
                f"Publish it with 'macrofield regime {economy}'."
            )
        loaded[economy] = load_regime(candidate)

    # ---- the common window ------------------------------------------------
    #
    # Intersected, not unioned. A period one economy does not cover cannot be blended, and substituting
    # its long-run average or holding its last reading would put a value into the blend that the producer
    # never published for that period.
    common = set(loaded[next(iter(loaded))].dates)
    for timeline in loaded.values():
        common &= set(timeline.dates)
    if not common:
        spans = ", ".join(
            f"{code} {t.dates[0]} to {t.dates[-1]}" for code, t in sorted(loaded.items())
        )
        raise ContractError(
            f"the Regimes contributing to market scope {market!r} share no period, so no blend exists. "
            f"Spans: {spans}."
        )
    dates = tuple(sorted(common))

    widest = max((len(t.dates) for t in loaded.values()), default=0)
    if len(dates) < widest:
        limiting = sorted(
            loaded.items(), key=lambda kv: (kv[1].dates[0], -len(kv[1].dates))
        )
        narrowest = min(loaded.items(), key=lambda kv: len(kv[1].dates))
        notes.append(
            f"the blend spans {dates[0]} to {dates[-1]} ({len(dates)} months), the overlap of "
            f"{len(loaded)} contributing Regimes. The narrowest contributor is {narrowest[0]} "
            f"({narrowest[1].dates[0]} to {narrowest[1].dates[-1]}), which sets the window. A backtest "
            f"cannot run longer than this."
        )
        del limiting

    # ---- the weighted sum -------------------------------------------------
    total_weight = float(sum(economy_weights.values()))
    if abs(total_weight - 1.0) > 1e-9:
        raise ContractError(
            f"the economy weights for market scope {market!r} sum to {total_weight}, not 1, so the blend "
            f"would rescale every distribution"
        )

    blended = np.zeros((len(dates), STATE_GRID), dtype=float)
    for economy, weight in economy_weights.items():
        timeline = loaded[economy]
        index = {date: position for position, date in enumerate(timeline.dates)}
        rows = np.asarray(timeline.distributions, dtype=float)
        blended += weight * np.vstack([rows[index[date]] for date in dates])

    # Each contributing row sums to one and the weights sum to one, so each blended row does too. Checked
    # rather than assumed, because a silent renormalisation here would mask an upstream contract breach.
    sums = blended.sum(axis=1)
    worst = int(np.argmax(np.abs(sums - 1.0)))
    if abs(sums[worst] - 1.0) > 1e-9:
        raise ContractError(
            f"the blended distribution for {dates[worst]} sums to {sums[worst]:.12f}, not 1, although "
            f"every contributor and the weights do. This indicates a malformed contributing timeline."
        )

    contributors = {
        code: {
            "regime_id": timeline.regime_id,
            "regime_timeline_id": timeline.regime_timeline_id,
            "model_version": timeline.model_version,
            "weight": economy_weights[code],
            "as_of": timeline.as_of,
            "first": timeline.dates[0],
            "last": timeline.dates[-1],
            "months": len(timeline.dates),
            "phase": timeline.phase,
            "saturation_pct": timeline.saturation_pct,
        }
        for code, timeline in sorted(loaded.items())
    }

    versions = {t.model_version for t in loaded.values()}
    if len(versions) > 1:
        notes.append(
            f"the contributing Regimes were produced by more than one model version ({sorted(versions)}), "
            f"so the blend carries the set rather than a single version."
        )
    model_version = versions.pop() if len(versions) == 1 else "mixed(" + ",".join(sorted(versions)) + ")"

    digest = _blend_digest(market, economy_weights, contributors, dates)
    return RegimeBlend(
        distributions=blended,
        dates=dates,
        regime_id=f"REG-BLEND-{digest[:16]}",
        regime_timeline_id=f"RTL-BLEND-{digest[:16]}",
        economy_weights=dict(sorted(economy_weights.items())),
        slot_weights=dict(slot_weights),
        contributors=contributors,
        market=market,
        as_of=max(t.as_of for t in loaded.values()),
        model_version=model_version,
        notes=tuple(notes),
    )


def load_regime_for_market(
    market: str,
    config: Config,
    directory: Path | str | None = None,
    timelines: Mapping[str, RegimeTimeline] | None = None,
) -> tuple[RegimeTimeline, RegimeBlend | None]:
    """The published timeline a mandate optimises against.

    **A published scope is read, not recomputed.** The Regime producer publishes a blended timeline per
    market scope, with its own `regime_id`, and the Return Estimation programme estimates its profiles
    against that same file. Blending here instead would give the optimiser a distribution whose identifier
    no ReturnSet could ever carry, and the binding regime_id check would reject every run. So a market
    scope is looked up as a published timeline first, and the blend below is only a fallback for a scope
    that names one economy directly.

    Returns the timeline and, when the fallback blend was used, the blend that produced it.
    """
    root = Path(directory) if directory is not None else _default_directory(config)

    # A scope published under its own name: the normal path.
    published = root / f"{market}.json"
    if published.exists():
        return load_regime(published), None

    # A market naming a single economy directly, for example a mandate scoped to `us`.
    single = root / f"{market}.json"
    del single  # same path; kept explicit that the lookup above already covered it

    presets = dict(config.get("country_weights.presets"))
    if market not in presets:
        # Not a configured scope and not published, so it may be an economy code.
        raise RegimeNotFound(
            f"no Regime timeline is published for market scope {market!r} at {published}, and it is not a "
            f"configured scope ({sorted(k for k in presets if k != 'equal')}). Publish it with "
            f"'macrofield regime <economies> --scope {market}'."
        )

    raise RegimeNotFound(
        f"market scope {market!r} is configured but no timeline is published at {published}. The Regime "
        f"producer owns the blend, because a ReturnSet is estimated against one timeline and a blend "
        f"computed here would carry an identifier no ReturnSet could match. Publish it with "
        f"'macrofield regime cn in us ch br gb de fr --scope {market}'."
    )


def _default_directory(config: Config) -> Path:
    configured = Path(str(config.get("contracts.regime_timeline_dir")))
    if configured.is_absolute():
        return configured
    # Relative paths resolve against the project root, which is the parent of the package, so a run works
    # from any working directory.
    return (Path(__file__).resolve().parent.parent.parent / configured).resolve()


def _blend_digest(
    market: str,
    economy_weights: Mapping[str, float],
    contributors: Mapping[str, Mapping[str, Any]],
    dates: Sequence[str],
) -> str:
    import hashlib

    payload = {
        "market": market,
        "economy_weights": {k: round(float(v), 12) for k, v in sorted(economy_weights.items())},
        "contributors": {
            code: {
                "regime_id": info["regime_id"],
                "regime_timeline_id": info["regime_timeline_id"],
            }
            for code, info in sorted(contributors.items())
        },
        "first": dates[0],
        "last": dates[-1],
        "months": len(dates),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
