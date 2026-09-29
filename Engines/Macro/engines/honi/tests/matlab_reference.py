"""A literal transliteration of the MATLAB indicator functions. Test reference only.

Line for line from ``Functions/HoNI/HN_*.m`` and ``HoNI2.m`` (Version 2.0), defects
included: zero -> NaN where the MATLAB does it, a first growth rate of 0 where the MATLAB
writes one, ``movmean`` with and without ``omitnan`` exactly where the MATLAB uses each,
and the India x3 / UK x0.3 patches. It is deliberately not reused by the engine: its only
job is to be obviously the same as the ``.m`` files, so that the engine can be reconciled
against it on the cells no defect touches.

Inputs are MATLAB's view of the annual data: every 12th row of ``M_TS``, with missing
values as the zeros MATLAB loaded them as.
"""

from __future__ import annotations

import warnings

import numpy as np


def _movmean(x: np.ndarray, omitnan: bool) -> np.ndarray:
    """movmean(x, [4 0]) along rows, shrinking at the start (MATLAB 'Endpoints','shrink')."""
    out = np.empty_like(x, dtype=float)
    for t in range(x.shape[0]):
        block = x[max(0, t - 4): t + 1]
        if omitnan:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)   # mean of an all-NaN window
                out[t] = np.nanmean(block, axis=0)
        else:
            out[t] = block.mean(axis=0)
    return out


def _zero_inf_to_nan(x: np.ndarray) -> np.ndarray:
    x = x.astype(float).copy()
    x[x == 0] = np.nan
    x[np.isinf(x)] = np.nan
    return x


def _growth(x: np.ndarray, first: float) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    out[0] = first
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = (x[1:] - x[:-1]) / x[:-1]
    return out


def indicators(s: dict[str, np.ndarray], countries: list[str]) -> dict[str, np.ndarray]:
    """HoNI2.m 'Create HoNI Structure', one entry per HN_*.m function."""
    with np.errstate(divide="ignore", invalid="ignore"):
        budget = s["money.budget_balance_gdp"].copy()                      # HN_budget_bal
        budget[budget == 0] = np.nan

        ag = _zero_inf_to_nan(_growth(s["money.broad_money"], np.nan))      # HN_money_supply
        bg = _zero_inf_to_nan(_growth(s["production.gdp_nominal"], np.nan))
        money = _movmean(ag - bg, omitnan=True)

        gov = s["debt.government_gdp"].copy()                              # HN_gov_debt
        real10 = _movmean(s["yields.govt_10y"] - s["inflation.cpi_yoy"], omitnan=False)  # HN_real_rates
        mcap = s["equity.market_cap_gdp"].copy()                           # HN_market_cap

        a = _zero_inf_to_nan(s["fx.trade_balance"])                         # HN_ext_afford
        b = _zero_inf_to_nan(s["debt.external"])
        afford = _movmean(a / b, omitnan=True)

        expo = _zero_inf_to_nan(s["debt.external"] / s["production.gdp_nominal"])  # HN_ext_expose
        tot = _movmean(s["fx.terms_of_trade"], omitnan=False)              # HN_terms_trade
        imp = _zero_inf_to_nan(s["fx.reserves"] / s["production.imports"])  # HN_imp_res
        corr = s["consumer.corruption_freedom"].copy()                     # HN_corrpt_frdm
        power = s["consumer.wage_growth"] - s["inflation.cpi_yoy"]         # HN_consump_pwr
        pop = _growth(s["consumer.population"], 0.0)                       # HN_pop_growth
        gdppc = _movmean(_growth(s["consumer.gdp_per_capita"], 0.0) - s["inflation.cpi_yoy"],
                         omitnan=True)                                     # HN_real_gdp
        depend = s["consumer.household_consumption"] / s["production.gdp_nominal"]  # HN_consump_depend
        for j, code in enumerate(countries):                               # HoNI2.m patches
            if code == "IN":
                depend[:, j] *= 3
            if code == "GB":
                depend[:, j] *= 0.3
        labour = s["consumer.labour_force_participation"].copy()           # HN_labour_force

    return {
        "budget_balance": budget, "monetary_supply": money, "government_debt": gov,
        "real_rate_10y": real10, "market_cap": mcap, "external_debt_affordability": afford,
        "external_debt_exposure": expo, "terms_of_trade": tot, "import_reserves": imp,
        "corruption_freedom": corr, "consumption_power": power, "population_growth": pop,
        "gdp_per_capita_growth": gdppc, "consumption_dependency": depend, "labour_force": labour,
    }


#: For each index: the series it reads, and how many prior years its value depends on
#: (1 for a growth rate, 4 for the trailing window, 5 for both). Used to find the cells no
#: defect can touch.
DEPENDENCIES: dict[str, tuple[tuple[str, ...], int]] = {
    "budget_balance": (("money.budget_balance_gdp",), 0),
    "monetary_supply": (("money.broad_money", "production.gdp_nominal"), 5),
    "government_debt": (("debt.government_gdp",), 0),
    "real_rate_10y": (("yields.govt_10y", "inflation.cpi_yoy"), 4),
    "market_cap": (("equity.market_cap_gdp",), 0),
    "external_debt_affordability": (("fx.trade_balance", "debt.external"), 4),
    "external_debt_exposure": (("debt.external", "production.gdp_nominal"), 0),
    "terms_of_trade": (("fx.terms_of_trade",), 4),
    "import_reserves": (("fx.reserves", "production.imports"), 0),
    "corruption_freedom": (("consumer.corruption_freedom",), 0),
    "consumption_power": (("consumer.wage_growth", "inflation.cpi_yoy"), 0),
    "population_growth": (("consumer.population",), 1),
    "gdp_per_capita_growth": (("consumer.gdp_per_capita", "inflation.cpi_yoy"), 5),
    "consumption_dependency": (("consumer.household_consumption", "production.gdp_nominal"), 0),
    "labour_force": (("consumer.labour_force_participation",), 0),
}

#: HN_money_supply.m also discards a growth rate of exactly 0 (``Ag(Ag==0)=nan``), which is
#: what a stale, carried-forward series produces. The engine keeps it (defect 9.2: zero is
#: a number), so those windows are a classified divergence, not a comparison.
ZERO_GROWTH_IS_MISSING: dict[str, tuple[str, ...]] = {
    "monetary_supply": ("money.broad_money", "production.gdp_nominal"),
}

#: Indices built on a growth rate. MATLAB writes 0 for (some of) their first year, the
#: engine writes a gap, so a window that reaches back to year 0 is not comparable.
GROWTH_BASED = {"monetary_supply", "population_growth", "gdp_per_capita_growth"}
