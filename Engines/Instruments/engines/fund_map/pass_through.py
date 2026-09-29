"""Inflation pass-through (beta) under a scenario Regime (owner, 29 September 2026).

**The problem it fixes.** Under a scenario Regime the real view deflated the historical
nominal profiles, measured in normal inflation, by the scenario's own inflation (decision
2 of the real view). Under hyperinflation, 63.6 % a year, that put gold at about -34 % real
in crisis: an inflation hedge whose nominal return does not rise with prices. That is
wrong; in a hyperinflation an inflation hedge's nominal return rises with prices.

**The rule** (owner: "inflation pass-through beta"), per instrument ``i`` and state ``s``,
for a *scenario* Regime with scenario inflation ``pi_s`` (its ``inflation_final_12m``)::

    historical real      r_real(i, s) = nominal(i, s) - ln(1 + pi_hist(s))
    scenario nominal     r_real(i, s) + beta_i * ln(1 + pi_s)   [+ bond price change]
    scenario real        r_real(i, s) + (beta_i - 1) * ln(1 + pi_s)   [+ bond price change]

``pi_hist(s)`` is the historical per-state deflator of the currency the profile is measured
in (``inflation.state_curve``). A nominal bond adds the price change of a rate rise over the
12 month horizon **in log form** (owner, 29.09.2026, FMRE-38)::

    bond price change    -D_i * (ln(1 + pi_s) - ln(1 + pi_hist(s)))   a log return

with the duration ``D_i`` of its type. A log return never takes the price below zero, so
there is no cap (``ipt@1.0.0`` measured the change as a simple return and capped the loss at
99 % of the price; every bond with duration 6 or 7 sat at the cap under hyperinflation).
Base (non-scenario) Regimes are unchanged: beta plays no role there.

**Role profiles** (FMRE-40) are carried by the same rule with a **blended beta**: the
weighted beta of their blocks (:data:`BLOCK_TYPES`, weights from ``roles.ROLE_MAP``), and
the weighted duration of their bond blocks. In log form the duration loss is linear in the
duration, so the blended duration gives exactly the weighted sum of the blocks' losses.

**The house table** (:data:`HOUSE_TABLE`) gives beta and duration per instrument type; the
register maps onto the types by asset class, refined by name and price proxy
(:func:`classify`). It is a versioned calibration (:data:`CALIBRATION_VERSION`), stored by
``service.ensure_pass_through_calibration`` with its source line. The CIO overrides an
instrument through ``PUT /v1/inflation-beta/{id}`` (append-only, in the store).

Pure functions; no storage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

#: The calibration version. **A change to anything in** :func:`calibration_payload` **is a
#: new version**: the store refuses the same version with different content.
CALIBRATION_VERSION = "ipt@1.1.0"

#: Earlier versions, kept in ``inflation_beta_calibration`` (append-only) and named here so
#: an earlier set's ``calibration_id`` can be read back. ``ipt@1.0.0``: cash beta 0.4, the
#: bond price change a simple return capped at 99 % of the price, roles without
#: pass-through (FMRE-33, FMRE-34).
EARLIER_VERSIONS: dict[str, str] = {"ipt@1.0.0": "IPT-a6426b5352de9e3e"}

SOURCE = (
    "House table, owner decision of 29.09.2026 ('inflation pass-through beta'): beta per "
    "instrument type, gold and precious metals 1.0, commodities 1.0, inflation-linked bonds "
    "1.0, real estate 0.8, equities 0.6, cash 0.0 (owner, 29.09.2026: cash loses the full "
    "inflation, no duration), nominal bonds 0.0 plus a duration loss in log form, no cap "
    "(owner, 29.09.2026), hedge funds / alternatives 0.5, digital assets 0.5, volatility "
    "0.5; durations (house assumption): aggregate bonds 6, government bonds 7, short-dated "
    "bonds 0.25. Register mapping by asset class, refined by name and price proxy (FMRE-34); "
    "confirmed by the owner on 29.09.2026: infrastructure as real estate, corporate, high "
    "yield and Asian credit duration 6, Private Debt short-dated. Role profiles take the "
    "weighted beta of their long-record blocks (owner, 29.09.2026; block types FMRE-40)."
)

#: No floor since ``ipt@1.1.0``: the log-form duration loss keeps every price above zero.
#: ``ipt@1.0.0`` had 0.01 (the loss capped at 99 % of the price).
PRICE_FLOOR = None

#: The contract's bounds on a beta a CIO may set.
BETA_MIN, BETA_MAX = 0.0, 1.5
#: And on a duration, in years.
DURATION_MIN, DURATION_MAX = 0.0, 30.0

FORMULA = (
    "scenario nominal = (nominal - ln(1 + pi_hist(s))) + beta * ln(1 + pi_s) "
    "- D * (ln(1 + pi_s) - ln(1 + pi_hist(s))) for a nominal bond (a log return, no cap); "
    "scenario real = scenario nominal - ln(1 + pi_s); pi_hist(s) the historical per-state "
    "inflation of the currency the profile is measured in (USD for a role profile), pi_s "
    "the scenario Regime's inflation_final_12m; a role profile takes beta = sum(w_b * "
    "beta_b) and D = sum(w_b * D_b) over its blocks"
)


@dataclass(frozen=True)
class InstrumentType:
    key: str
    label: str
    beta: float
    #: Years; set only for a nominal bond type, the price change of a rate rise.
    duration: float | None = None

    @property
    def nominal_bond(self) -> bool:
        return self.duration is not None


HOUSE_TABLE: tuple[InstrumentType, ...] = (
    InstrumentType("precious_metals", "gold and precious metals", 1.0),
    InstrumentType("commodities", "commodities", 1.0),
    InstrumentType("inflation_linked_bonds", "inflation-linked bonds", 1.0),
    InstrumentType("real_estate", "real estate and real assets", 0.8),
    InstrumentType("equities", "equities", 0.6),
    InstrumentType("cash", "cash", 0.0),
    InstrumentType("nominal_bonds_aggregate", "nominal bonds, aggregate", 0.0, 6.0),
    InstrumentType("nominal_bonds_government", "nominal bonds, government", 0.0, 7.0),
    InstrumentType("nominal_bonds_short", "nominal bonds, short-dated or floating", 0.0, 0.25),
    InstrumentType("hedge_funds_alternatives", "hedge funds and alternatives", 0.5),
    InstrumentType("digital_assets", "digital assets", 0.5),
    InstrumentType("volatility", "volatility", 0.5),
)
TYPES: dict[str, InstrumentType] = {t.key: t for t in HOUSE_TABLE}

#: How the register maps onto the types, in the order the rules are tried. Each rule is
#: ``(type, what it matches, why)``; the first match wins.
RULES: tuple[tuple[str, str, str], ...] = (
    ("inflation_linked_bonds", "name mentions inflation-linked, linker or TIPS",
     "the coupon and principal are indexed to prices"),
    ("precious_metals", "price proxy GLD, IAU, SLV or name mentions precious metals or gold",
     "a store of value priced in money"),
    ("commodities", "name mentions commodities, or price proxy GSG or DBC",
     "the prices that make up inflation"),
    ("volatility", "price proxy VXTH or VIXY, or name mentions volatility",
     "the tail hedge, as the protection types read it (FMRE-24)"),
    ("digital_assets", "name mentions digital assets, or price proxy BTC-USD", ""),
    ("real_estate", "name mentions infrastructure",
     "real assets whose revenues are largely indexed; registered as Alternative "
     "(confirmed by the owner, 29.09.2026)"),
    ("real_estate", "asset class Real Estate", ""),
    ("cash", "asset class Cash",
     "owner, 29.09.2026: beta 0, cash loses the full inflation; no duration, no price loss"),
    ("equities", "asset class Equity",
     "includes Mining Equities, Private Equity and Structured Products"),
    ("nominal_bonds_government", "asset class Fixed Income and name mentions government or "
     "treasury", ""),
    ("nominal_bonds_short", "asset class Fixed Income and name mentions private debt, or "
     "price proxy BKLN", "leveraged loans: floating coupons, a short rate duration "
     "(confirmed by the owner, 29.09.2026)"),
    ("nominal_bonds_aggregate", "asset class Fixed Income, otherwise",
     "aggregates, corporate, high yield and Asian credit take the aggregate duration "
     "(confirmed by the owner, 29.09.2026)"),
    ("hedge_funds_alternatives", "asset class Alternative, otherwise", ""),
    ("hedge_funds_alternatives", "any other asset class (default)",
     "an unmapped asset class; the CIO should set it"),
)


#: The house type of every long-record block (``calibrate.BLOCKS``) a role is made of, from
#: which a role profile's blended beta is composed (owner, 29.09.2026; FMRE-40). Each entry
#: is ``(type, why)``; the beta and the duration are the type's in :data:`HOUSE_TABLE`.
#: ``long_rate`` is a yield, not a holding, and belongs to no role: it has no type.
BLOCK_TYPES: dict[str, tuple[str, str]] = {
    "equity": ("equities", "the US equity index (spx), log changes"),
    "real_estate": ("real_estate", "the US house price index, log changes"),
    "gov_bonds": ("nominal_bonds_government",
                  "US government bond total return, a long bond: the government duration 7"),
    "gold": ("precious_metals", "gold"),
    "commodities": ("commodities", "oil and wheat, half each"),
    "agriculture": ("commodities", "agricultural prices, as commodities (owner, 29.09.2026)"),
    "short_rate": ("cash", "the 1-year bill rate, a cash return: beta 0, no duration"),
}


def role_blend(weights: Mapping[str, float]) -> dict:
    """A role's blended beta and duration from its block weights, and the composition.

    ``beta = sum(w_b * beta_b)``, ``duration = sum(w_b * D_b)`` (``D_b`` 0 for a block that
    is not a nominal bond) over the normalised weights; the duration is None when no block
    carries one. In log form the duration loss is linear in ``D``, so the blended duration
    is exactly the weighted sum of the blocks' losses.
    """
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("a role needs a positive total weight")
    composition = []
    beta = duration = 0.0
    has_duration = False
    for block in sorted(weights):
        if block not in BLOCK_TYPES:
            raise KeyError(f"block {block!r} has no pass-through type (BLOCK_TYPES)")
        w = weights[block] / total
        kind = TYPES[BLOCK_TYPES[block][0]]
        beta += w * kind.beta
        if kind.duration is not None:
            duration += w * kind.duration
            has_duration = True
        composition.append({"block": block, "weight": w, "type": kind.key,
                            "beta": kind.beta, "duration": kind.duration})
    return {"beta": beta, "duration": duration if has_duration else None,
            "composition": composition}


def role_blends() -> dict[str, dict]:
    """The blended beta of each published role (``roles.ROLE_MAP``)."""
    from engines.fund_map.roles import ROLE_MAP
    return {spec.role: role_blend(spec.weights) for spec in ROLE_MAP}


def _has(name: str, *words: str) -> bool:
    lowered = name.lower()
    return any(w in lowered for w in words)


def classify(instrument: Mapping) -> tuple[str, int]:
    """The house type of a register row, and the index of the rule in :data:`RULES`.

    Reads ``name``, ``asset_class`` and ``proxy_symbol``.
    """
    name = str(instrument.get("name") or "")
    asset = str(instrument.get("asset_class") or "")
    proxy = str(instrument.get("proxy_symbol") or "").upper()
    tests = (
        _has(name, "inflation-linked", "inflation linked", "linker")
        or "tips" in name.lower().replace("(", " ").replace(")", " ").split(),
        proxy in {"GLD", "IAU", "SLV"} or _has(name, "precious", "gold"),
        _has(name, "commodit") or proxy in {"GSG", "DBC"},
        proxy in {"VXTH", "VIXY"} or _has(name, "vola"),
        _has(name, "digital") or proxy == "BTC-USD",
        _has(name, "infrastructure"),
        asset == "Real Estate",
        asset == "Cash",
        asset == "Equity",
        asset == "Fixed Income" and _has(name, "government", "governmental", "treasury"),
        asset == "Fixed Income" and (_has(name, "private debt") or proxy == "BKLN"),
        asset == "Fixed Income",
        asset == "Alternative",
        True,
    )
    for index, hit in enumerate(tests):
        if hit:
            return RULES[index][0], index
    raise AssertionError("unreachable: the last rule matches everything")


def calibration_payload() -> dict:
    """Everything the pass-through depends on: what the calibration id hashes."""
    return {
        "version": CALIBRATION_VERSION,
        "source": SOURCE,
        "types": {t.key: {"label": t.label, "beta": t.beta, "duration": t.duration}
                  for t in HOUSE_TABLE},
        "rules": [list(r) for r in RULES],
        "blocks": {k: {"type": t, "why": why} for k, (t, why) in BLOCK_TYPES.items()},
        "roles": role_blends(),
        "formula": FORMULA,
    }


def bond_price_log(duration: float, log_pi_s: float, log_pi_hist: float) -> float:
    """``-D * (ln(1 + pi_s) - ln(1 + pi_hist))``: the rate-rise price change, a log return.

    Takes both inflations as ``ln(1 + pi)``. A fall in inflation is a price gain. No cap:
    ``exp`` of any log return is a price above zero.
    """
    return -duration * (log_pi_s - log_pi_hist)


def scenario_nominal(values: Sequence[float], hist_log: Sequence[float], pi_s: float,
                     beta: float, duration: float | None) -> list[float]:
    """One profile under the scenario, nominal: historical real plus the pass-through.

    ``hist_log`` is ``ln(1 + pi_hist(s))`` per state.
    """
    if len(values) != len(hist_log):
        raise ValueError("a profile and its deflator must have the same states")
    if pi_s <= -1.0:
        raise ValueError(f"scenario inflation {pi_s!r} is not a rate")
    log_s = math.log1p(pi_s)
    out = []
    for v, lh in zip(values, hist_log):
        x = (v - lh) + beta * log_s
        if duration:
            x += bond_price_log(duration, log_s, lh)
        out.append(x)
    return out
