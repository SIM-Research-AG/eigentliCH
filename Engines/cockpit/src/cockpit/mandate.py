"""The Parameters form and pcp's Mandate: unit conversion and assembly, in plain Python (C-21).

The curator fills the form in the units people read: percent of the portfolio for every weight and
bound, percent per year for the target curve. pcp's Mandate (``pcp-mandate@1.0.0``) takes fractions
and the curve as annualised log returns. This module converts between the two and nothing else:

* percent to fraction: ``p / 100``; fraction to percent: ``f * 100``;
* a curve point of ``p`` percent per year is stored as ``ln(1 + p / 100)`` (``math.log1p``), the
  unit lbs publishes its proposal in; back again ``(exp(v) - 1) * 100`` (``math.expm1``);
* a preset curve adjusted by a level shift of ``s`` percentage points and a slope tilt of ``t``
  percentage points: point ``i`` (1..25) becomes ``base_i + s + t * (i - 13) / 12``, so the tilt adds
  ``t`` at state 25 (boom), takes ``t`` off at state 1 (crisis) and leaves state 13 and the curve's
  mean over the states unchanged;
* matching lbs's required return (decimal, the equal-weighted mean of lbs's own ramp): the shift is
  ``required * 100 - preset mean``, the preset's mean being stored with the preset (data, not
  computed here).

The form's ``basis`` (``nominal``, the default, or ``real``) is the basis of the target curve (C-31).
It is written into the Mandate only when it is ``real``: a Mandate without ``basis`` is nominal in pcp's
contract, so a nominal mandate stays byte for byte what it was (its idempotency key does not move). The
cockpit converts nothing between the two: a curve read as real is the same numbers, and pcp asks fmre
for the real ReturnSet (C-07).

These are unit conversions of numbers the curator typed or a preset stores, not model figures: no
engine publishes them and no estimate enters (C-07 holds; ``math`` is the standard library and no
numerics package is imported). pcp remains the judge of the mandate: ``/validate`` answers for it.

What pcp checks is mirrored here only as far as the form needs it to name a field: the bound
dimensions and their buckets (calibration 1.1.0), the fixed source of each dimension (Manual 14.2),
and the shape rules that a form can break (25 points, bounds ordered, weights summing to 100 %).
Mirrored, never imported (Engine Building Guide section 1).
"""

from __future__ import annotations

import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CONTRACT = "pcp-mandate@1.0.0"
N_STATES = 25
#: The seven bounded dimensions and their buckets, in pcp's constraint-block order (calibration 1.1.0).
BUCKETS: dict[str, tuple[str, ...]] = {
    "currency": ("CHF", "USD", "EUR", "RMB", "GBP", "JPY", "HKD", "AUD", "INR", "Others"),
    "region": ("Switzerland", "Europe", "East Asia", "South Asia", "North America", "South Pacific", "Others"),
    "role": ("Gain", "Income", "Stabilisation", "Protection"),
    "capital_type": ("Financial", "Real", "Others"),
    "liquidity": ("Daily", "Quarterly", "Yearly", "Decade"),
    "phase": ("Foundation", "Build-up", "Optimisation", "Saturation"),
    "asset_class": ("Cash", "Fixed Income", "Equity", "Real Assets", "Alternative"),
}
DIMENSIONS = tuple(BUCKETS)
#: Manual section 14.2 as pcp enforces it: the household's bounds are "derived", the house's "policy".
BOUND_SOURCE: dict[str, str] = {
    "currency": "derived", "liquidity": "derived", "role": "derived",
    "asset_class": "policy", "capital_type": "policy", "phase": "policy", "region": "policy",
}
CURRENCIES = ("CHF", "EUR", "USD")
#: The bases of the target curve (C-31); ``nominal`` unless the curator switches.
BASES = ("nominal", "real")
DEFAULT_BASIS = "nominal"
PRESET_KEYS = {"curves": "reference/target-curve-presets", "mandates": "reference/mandate-presets"}
CONVERSION = ("Target curve: entered and shown in percent per year; stored as the annualised log return "
              "ln(1 + p/100) (curve_unit annualised_log_return). Weights and bounds: entered in percent, "
              "stored as fractions (p/100).")
BASIS_NOTE = ("Basis: nominal unless switched. In real, the target curve is read as a real return (after the "
              "inflation of the mandate's currency) and the level shift and tilt apply in real terms; the presets "
              "are nominal data, read as real, and the cockpit converts nothing. pcp fetches fmre's real ReturnSet "
              "(basis=real), which deflates by the per-state inflation fmre measures.")
#: Decimals kept when converting, so 35 % is stored as 0.35 and not 0.35000000000000003.
_DIGITS = 12


class Problem(ValueError):
    """The form cannot become a Mandate; ``problems`` names each field and what is wrong."""

    def __init__(self, problems: list[dict[str, str]]):
        super().__init__("; ".join(f"{p['field']}: {p['message']}" for p in problems))
        self.problems = problems


class CurveIn(BaseModel):
    """The target curve as the form holds it: either the 25 points in percent per year, or a
    preset's 25 points with a level shift and a slope tilt (both in percentage points)."""

    model_config = ConfigDict(extra="forbid")
    points_pct: Optional[list[float]] = None
    base_pct: Optional[list[float]] = None
    shift_pp: float = 0.0
    tilt_pp: float = 0.0
    preset: Optional[str] = None
    preset_version: Optional[int] = None


class BoundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lower_pct: Optional[float] = None
    upper_pct: Optional[float] = None


class MandateForm(BaseModel):
    """What the Parameters form sends: every weight in percent, the curve in percent per year."""

    model_config = ConfigDict(extra="forbid")
    client: str = ""
    name: str = ""
    currency: str = "CHF"
    #: The basis of the target curve (C-31): nominal (default) or real.
    basis: Literal["nominal", "real"] = DEFAULT_BASIS
    horizon_years: float = 1.0
    curve: CurveIn
    universe: list[str] = Field(default_factory=list)
    max_single_position_pct: Optional[float] = None
    esg_min: float = 0.0
    fixed_allocations_pct: dict[str, float] = Field(default_factory=dict)
    bounds_pct: dict[str, dict[str, BoundIn]] = Field(default_factory=dict)
    regime_market: Optional[str] = None
    regime_weights_pct: Optional[dict[str, float]] = None


def _r(x: float) -> float:
    return round(x, _DIGITS) + 0.0   # + 0.0 turns -0.0 into 0.0


def pct_to_log(points_pct: list[float]) -> list[float]:
    """Percent per year to the stored unit, ``ln(1 + p/100)``."""
    return [_r(math.log1p(p / 100.0)) for p in points_pct]


def log_to_pct(points: list[float]) -> list[float]:
    """The stored unit back to percent per year, ``(exp(v) - 1) * 100``."""
    return [_r(math.expm1(v) * 100.0) for v in points]


def adjust(base_pct: list[float], shift_pp: float = 0.0, tilt_pp: float = 0.0) -> list[float]:
    """A preset shifted by ``shift_pp`` and tilted by ``tilt_pp`` (+t at boom, -t at crisis, 0 at state 13)."""
    mid = (len(base_pct) + 1) / 2.0
    half = (len(base_pct) - 1) / 2.0 or 1.0
    return [_r(p + shift_pp + tilt_pp * ((i + 1) - mid) / half) for i, p in enumerate(base_pct)]


def match_shift(required_return: float, preset_mean_pct: float) -> float:
    """The shift that sets the curve's equal-weighted mean to lbs's required return (a decimal)."""
    return _r(required_return * 100.0 - preset_mean_pct)


def curve_points(curve: CurveIn) -> list[float]:
    if curve.points_pct is not None:
        return [_r(p) for p in curve.points_pct]
    if curve.base_pct is None:
        raise Problem([{"field": "target_curve", "message": "choose a preset or enter the 25 points"}])
    return adjust(curve.base_pct, curve.shift_pp, curve.tilt_pp)


def assemble(form: MandateForm) -> dict[str, Any]:
    """The form as pcp's Mandate: fractions, the curve as annualised log returns, each bounded
    dimension labelled with its fixed source. Raises :class:`Problem` naming every field it cannot
    convert; pcp's ``/validate`` judges the rest."""
    problems: list[dict[str, str]] = []

    def bad(field: str, message: str) -> None:
        problems.append({"field": field, "message": message})

    if not form.client.strip():
        bad("client", "the client is missing")
    if not form.name.strip():
        bad("name", "give the mandate a name")
    currency = form.currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        bad("currency", f"{form.currency!r} is not a three-letter currency code")
    if not form.horizon_years > 0:
        bad("horizon_years", "the horizon must be more than 0 years")

    points: list[float] = []
    try:
        points = curve_points(form.curve)
    except Problem as exc:
        problems += exc.problems
    if points:
        if len(points) != N_STATES:
            bad("target_curve", f"the curve has {len(points)} points; it needs {N_STATES}, one per state")
        elif not all(math.isfinite(p) for p in points):
            bad("target_curve", "the curve holds a value that is not a number")
        elif any(p <= -100.0 for p in points):
            bad("target_curve", "a point at -100 % or below is a loss of the whole portfolio")

    universe = [u.strip() for u in form.universe if u.strip()]
    if not universe:
        bad("universe", "choose at least one instrument")
    if len(set(universe)) != len(universe):
        bad("universe", "an instrument is chosen twice")

    cap = form.max_single_position_pct
    if cap is None:
        bad("max_single_position", "set the largest share one instrument may hold")
    elif not 0 < cap <= 100:
        bad("max_single_position", f"{cap:g} % is outside (0, 100]")
    if form.esg_min < 0:
        bad("esg_min", "the ESG floor cannot be negative")

    fixed: dict[str, float] = {}
    for key, value in form.fixed_allocations_pct.items():
        if key not in universe:
            bad("fixed_allocations", f"{key} is pinned but not in the universe")
        elif not 0 <= value <= 100:
            bad("fixed_allocations", f"{key} is pinned at {value:g} %, outside 0 to 100 %")
        else:
            fixed[key] = _r(value / 100.0)
    if sum(form.fixed_allocations_pct.values()) > 100 + 1e-7:
        bad("fixed_allocations", "the pinned shares add up to more than 100 %")

    bounds: dict[str, dict[str, dict[str, float]]] = {}
    for dim, rows in form.bounds_pct.items():
        if dim not in BUCKETS:
            bad("bounds", f"{dim!r} is not a bound dimension")
            continue
        for bucket, b in rows.items():
            if bucket not in BUCKETS[dim]:
                bad(f"bounds.{dim}", f"{bucket!r} is not a {dim.replace('_', ' ')} bucket")
                continue
            lo = 0.0 if b.lower_pct is None else b.lower_pct
            hi = 100.0 if b.upper_pct is None else b.upper_pct
            if not (0 <= lo <= 100 and 0 <= hi <= 100):
                bad(f"bounds.{dim}", f"{bucket}: bounds must lie between 0 and 100 %")
            elif lo > hi:
                bad(f"bounds.{dim}", f"{bucket}: the lower bound {lo:g} % is above the upper {hi:g} %")
            elif lo > 0 or hi < 100:   # 0 to 100 % constrains nothing: left out
                bounds.setdefault(dim, {})[bucket] = {"lower": _r(lo / 100.0), "upper": _r(hi / 100.0)}
        if dim in bounds:
            if sum(v["lower"] for v in bounds[dim].values()) > 1 + 1e-9:
                bad(f"bounds.{dim}", "the lower bounds add up to more than 100 %")

    mandate: dict[str, Any] = {
        "contract_version": CONTRACT, "client": form.client.strip(), "name": form.name.strip(),
        "currency": currency, "horizon_years": form.horizon_years, "curve_unit": "annualised_log_return",
        "target_curve": pct_to_log(points) if len(points) == N_STATES and not any(p <= -100 for p in points) else [],
        "universe": universe, "max_single_position": None if cap is None else _r(cap / 100.0),
        "esg_min": form.esg_min, "fixed_allocations": fixed, "bounds": bounds,
        "bound_sources": {d: BOUND_SOURCE[d] for d in bounds},
    }
    if form.basis != DEFAULT_BASIS:   # only a real mandate says so; absent means nominal (C-31)
        mandate["basis"] = form.basis
    market = (form.regime_market or "").strip()
    weights = form.regime_weights_pct
    if market and weights:
        bad("regime", "choose a market or economy weights, not both")
    elif market:
        mandate["regime_market"] = market
    elif weights:
        if any(w < 0 or not math.isfinite(w) for w in weights.values()):
            bad("regime_weights", "economy weights must be 0 % or more")
        elif abs(sum(weights.values()) - 100.0) > 1e-6:
            bad("regime_weights", f"the economy weights add up to {sum(weights.values()):g} %, not 100 %")
        else:
            kept = {k: _r(v / 100.0) for k, v in weights.items() if v > 0}
            # the fractions of weights that sum to 100 % sum to 1 within pcp's 1e-9
            mandate["regime_weights"] = kept
    else:
        bad("regime", "choose a market or give economy weights")
    if problems:
        raise Problem(problems)
    return mandate


def to_form(mandate: dict[str, Any]) -> dict[str, Any]:
    """A stored Mandate (a parameter set, a preset, an lbs proposal) in the form's units."""
    unit = mandate.get("curve_unit", "annualised_log_return")
    curve = list(mandate.get("target_curve") or [])
    points = (log_to_pct(curve) if unit == "annualised_log_return" else [_r(v * 100.0) for v in curve]) if curve else None
    pct = lambda v: None if v is None else _r(float(v) * 100.0)  # noqa: E731
    bounds = {dim: {k: {"lower_pct": pct(v.get("lower", 0.0)), "upper_pct": pct(v.get("upper", 1.0))}
                    for k, v in (rows or {}).items()}
              for dim, rows in (mandate.get("bounds") or {}).items()}
    weights = mandate.get("regime_weights")
    return {
        "client": mandate.get("client") or "", "name": mandate.get("name") or "",
        "currency": mandate.get("currency") or "CHF", "basis": mandate.get("basis") or DEFAULT_BASIS,
        "horizon_years": mandate.get("horizon_years") or 1.0,
        "curve": {"points_pct": points}, "universe": list(mandate.get("universe") or []),
        "max_single_position_pct": pct(mandate.get("max_single_position")),
        "esg_min": mandate.get("esg_min") or 0.0,
        "fixed_allocations_pct": {k: pct(v) for k, v in (mandate.get("fixed_allocations") or {}).items()},
        "bounds_pct": bounds, "regime_market": mandate.get("regime_market"),
        "regime_weights_pct": None if weights is None else {k: pct(v) for k, v in weights.items()},
    }


def vocabulary() -> dict[str, Any]:
    """What the form lays out: dimensions, buckets, the fixed source of each, the currencies."""
    return {"contract_version": CONTRACT, "n_states": N_STATES, "dimensions": list(DIMENSIONS),
            "buckets": {k: list(v) for k, v in BUCKETS.items()}, "bound_source": BOUND_SOURCE,
            "currencies": list(CURRENCIES), "bases": list(BASES), "default_basis": DEFAULT_BASIS,
            "basis_note": BASIS_NOTE, "preset_keys": PRESET_KEYS, "conversion": CONVERSION,
            "tilt": "point i (1..25) = preset_i + shift + tilt * (i - 13) / 12",
            "match": "shift = lbs required return x 100 - preset mean"}
