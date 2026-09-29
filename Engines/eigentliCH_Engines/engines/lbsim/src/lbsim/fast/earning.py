"""The one earning-power computation (LBSIM-11): the prototype's ``services/human_capital.earning_power``, ported.

The prototype called the draft's ``dynamics.earning_power(E, N, age)`` at the ``human-capital`` record's
``earning_power.calibration.earning_power_at_unit`` (0.7207) and multiplied it by the responsibility tier (the
Kaderfunktion, and for top management the sector). lbsim does exactly that, on the E and N of lbs's sheet, with
the record from the lbs calibration named in the sheet's provenance. ``golden/earning`` holds the prototype's own
figures for lbs's golden households and this module reproduces them to 1e-9.

What differs from the prototype is only where the inputs come from: E and N are read off the sheet (lbs computed
them with the prototype's ``capitals``), not recomputed here, and the tier and sector are the answers of the new
``persons[].earning_power`` block (lbs@1.4.0) rather than the intake's ``kader`` and ``sector``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from ..model.dynamics import earning_power as engine_earning_power
from ..model.params import Params

#: The tier nobody stated: no management function, the modest reading (the prototype's).
DEFAULT_TIER = "ohne Kaderfunktion"


@dataclass(frozen=True)
class Tier:
    key: str
    multiplier: float
    stated: bool
    #: The prototype's caveat for this tier, in its own words (English), or None.
    note: Optional[str]
    label: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Modelled:
    """The prototype's ``EarningPower``, with the names of lbsim's contract."""

    at_full_productive_week_chf: float
    full_time_chf_per_year: float
    monthly_standardised_chf: float
    before_responsibility_chf: float
    tier: Tier
    inputs: dict[str, Any]
    caveats: tuple[str, ...]


def tiers(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = (record.get("responsibility") or {}).get("tiers") or {}
    return {k: v for k, v in raw.items() if not str(k).startswith("_") and isinstance(v, dict)}


def responsibility(record: dict[str, Any], stated: Optional[str], *, qualification: Optional[str],
                   sector: Optional[str]) -> Tier:
    """The prototype's ``responsibility_multiplier``: a stated tier by its key or either label."""
    stated = (stated or "").strip()
    sector = (sector or "").strip() or None
    for key, tier in tiers(record).items():
        labels = {key} | {str(v) for v in (tier.get("label") or {}).values()}
        label = {k: str(v) for k, v in (tier.get("label") or {}).items()}
        if not stated or stated not in labels:
            continue
        if "multiplier_by_qualification" in tier:
            by_qual = tier["multiplier_by_qualification"]
            if qualification in by_qual:
                return Tier(key, float(by_qual[qualification]), True, None, label)
            mean = sum(float(v) for v in by_qual.values()) / len(by_qual)
            return Tier(key, mean, True, ("no qualification was given, so the mean of the published multipliers "
                                          "was used rather than the one for this education"), label)
        by_sector = tier.get("multiplier_by_sector") or {}
        if by_sector:
            if sector in by_sector:
                note = None
                if qualification and qualification != "Universitäre Hochschule":
                    note = tier.get("extrapolation_named")
                return Tier(key, float(by_sector[sector]), True, note, label)
            reason = "no sector was given" if sector is None else f"{sector!r} has no published figure"
            return Tier(key, float(tier["multiplier"]), True, (
                f"{reason}, so the whole-economy figure was used — and it is not a middle value: it "
                f"sits next to Maschinenbau and far below banking, pharma and insurance"), label)
        return Tier(key, float(tier["multiplier"]), True, tier.get("warning"), label)
    default = tiers(record).get(DEFAULT_TIER) or {}
    label = {k: str(v) for k, v in (default.get("label") or {}).items()}
    return Tier(DEFAULT_TIER, 1.0, bool(stated),
                None if not stated else f"{stated!r} is not a published tier; no uplift was applied", label)


def at_unit(record: dict[str, Any]) -> float:
    return float(record["earning_power"]["calibration"]["earning_power_at_unit"])


def working_time(record: dict[str, Any]) -> tuple[float, float, float]:
    """``(factor, bfs_full_time_hours_per_week, model_productive_week_hours)`` of the record (30, 40, 100)."""
    w = record["earning_power"]["working_time"]
    return float(w["factor"]), float(w["bfs_full_time_hours_per_week"]), float(w["model_productive_week_hours"])


def full_time_share(record: dict[str, Any]) -> float:
    """The BFS full-time week as a share of the model's productive week (40 / 100)."""
    _, bfs, week = working_time(record)
    return bfs / week


def modelled(record: dict[str, Any], *, E: Optional[float], N: Optional[float], age: Optional[float],
             qualification: Optional[str], responsibility_stated: Optional[str], sector: Optional[str],
             caveats: tuple[str, ...] = (), unit: Optional[float] = None,
             params: Optional[Params] = None) -> Optional[Modelled]:
    """The prototype's ``earning_power``: ``None`` where E, N or the age is unknown (never a guess).

    ``unit`` overrides the record's ``earning_power_at_unit`` (calibration 1.0.0 reads the draft's 0.75)."""
    if E is None or N is None or age is None:
        return None
    u = at_unit(record) if unit is None else float(unit)
    p = replace(params or Params(), earning_power_at_unit=u)
    base = float(engine_earning_power(float(E), float(N), float(age), p))
    tier = responsibility(record, responsibility_stated, qualification=qualification, sector=sector)
    full = base * tier.multiplier
    factor, bfs, week = working_time(record)
    notes = list(caveats)
    if tier.note:
        notes.append(tier.note)
    if not responsibility_stated:
        notes.append("no management function was stated, so none was assumed — the BFS table shows that is worth "
                     "more than the qualification")
    return Modelled(
        at_full_productive_week_chf=full,
        full_time_chf_per_year=full * (bfs / week),
        monthly_standardised_chf=full / factor,
        before_responsibility_chf=base,
        tier=tier,
        inputs={"E": float(E), "N": float(N), "age": float(age), "qualification": qualification,
                "earning_power_at_unit": u},
        caveats=tuple(notes),
    )
