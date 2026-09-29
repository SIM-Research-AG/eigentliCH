"""Published series to one economy's observed path (Y, K_R, K_I). Pure.

The sources do not share a valuation: World Bank dollars are at market exchange rates, Penn
World Table at purchasing-power parities, BIS publishes ratios. So **one level series carries
the valuation and everything else enters as a ratio to it**: nominal GDP at market rates is Y,
K_R is the PWT ratio cn/cgdpo (unitless, so basis-free) times Y, and K_I is the BIS credit ratio
times Y. No PPP conversion factor enters anywhere.

The documented adjustments, each a calibration parameter:

* **Credit uplift** on the BIS ratio, so on the saturation axis and on K_I.
* **Real-capital extension.** PWT ends in 2019. The ratio k = K_R/Y is carried forward by
  perpetual inventory in ratio space, k(t) = (1 - delta) k(t-1) / (1 + g(t)) + i(t), from World
  Bank investment share i and real growth g and PWT's own delta (last published value carried,
  then the economy's prior). Extended years are flagged on the output. If an input is missing
  for any extension year, the ratio is not extended and the window ends at the PWT year.
* **Capital normalisation.** One common factor on K_R and K_I puts the window maximum of K_R/Y
  at ``capital_target``. It keeps r = 1 - K_R/Y positive, so the system integrates; being common
  to both stocks it leaves K_R/K_I, and so the Phase 4 test, untouched.

Nothing here fills a gap. The window is the overlap of the required series; a year inside it
with any required value missing is dropped and listed, never interpolated.

Follows ``Macro_Model/macrofield/pipeline.py`` (``assemble``) and ``Macro_Model/macrofield/data/loaders.py``, including
the order of floating-point operations, so the golden reconciliation can be exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

import numpy as np

from .contracts import Calibration, EconomySpec

Annual = Mapping[int, Optional[float]]

GDP = "wb.NY.GDP.MKTP.CD"
GFCF_SHARE = "wb.NE.GDI.FTOT.ZS"
REAL_GROWTH = "wb.NY.GDP.MKTP.KD.ZG"
SAVINGS = "wb.NY.GNS.ICTR.ZS"
FISCAL = "wb.GC.NLD.TOTL.GD.ZS"
POPULATION = "wb.SP.POP.TOTL"
CREDIT = "bis.total_credit"
PWT_CN, PWT_CGDPO, PWT_DELTA = "pwt.cn", "pwt.cgdpo", "pwt.delta"
BANK_TOTAL, BANK_LOANS = "bbk.OU0308", "bbk.OU0115"
GDP_LCU, JST_GDP = "wb.NY.GDP.MKTP.CN", "jst.gdp"
FISCAL_IMF = "imf.GGXCNL_NGDP"
IMF_PRIVATE, IMF_GOV_GDD, IMF_GOV_WEO = "imf.PVD_LS", "imf.GG_DEBT_GDP", "imf.GGXWDG_NGDP"


def member_key(series_id: str, member: str) -> str:
    """Observation key of one member's series for an aggregate economy (e.g. the euro area)."""
    return f"{series_id}@{member}"


class Unavailable(Exception):
    """The economy cannot be assembled. Carries the reason and the missing series ids."""

    def __init__(self, reason: str, missing: tuple[str, ...] = ()):
        super().__init__(reason)
        self.reason = reason
        self.missing = missing


@dataclass(frozen=True)
class Assembled:
    years: np.ndarray
    output: np.ndarray
    real_capital: np.ndarray
    financial_capital: np.ndarray
    savings_rate: np.ndarray
    stimulus_share: np.ndarray
    stimulus: np.ndarray
    population_growth: Optional[np.ndarray]
    credit_published: np.ndarray
    saturation: np.ndarray
    real_capital_ratio: np.ndarray
    extended: np.ndarray
    normalisation_scale: float
    normalisation_max_ratio: float
    normalisation_max_year: int
    window: tuple[int, int]
    #: Every year with both a saturation value and a real-capital ratio, up to the window end:
    #: the history the Phase 4 latch can run over.
    history_years: np.ndarray
    history_saturation: np.ndarray
    history_ratio: np.ndarray
    #: Loans over the bank balance sheet (Genreith), NaN where not published.
    commercial_share: np.ndarray
    history_commercial_share: np.ndarray
    dropped_years: tuple[int, ...]
    extended_years: tuple[int, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Year-indexed helpers. A series is {year: float}, NaN for a published gap, sorted.
# ---------------------------------------------------------------------------

Series = dict[int, float]


def _series(raw: Optional[Annual]) -> Series:
    if not raw:
        return {}
    return {int(y): (math.nan if v is None else float(v)) for y, v in sorted(raw.items())}


def _scaled(s: Series, factor: float) -> Series:
    return {y: v * float(factor) for y, v in s.items()}


def _observed(s: Series) -> Series:
    return {y: v for y, v in s.items() if not math.isnan(v)}


def _has_values(raw: Optional[Annual]) -> bool:
    return bool(raw) and any(v is not None for v in raw.values())


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def _depreciation(published: Series, prior: float, year: int) -> tuple[float, str]:
    observed = _observed(published)
    if year in observed:
        return observed[year], f"PWT delta {year}"
    earlier = [y for y in observed if y <= year]
    if earlier:
        last = max(earlier)
        return observed[last], f"PWT delta {last} carried to {year}"
    return float(prior), "economy prior, no PWT delta"


def capital_ratio(obs: Mapping[str, Annual], prior: float) -> tuple[Series, tuple[int, ...], list[str]]:
    """K_R/Y from PWT, extended in ratio space where every input exists. (ratio, extended, notes)."""
    cn, cgdpo = _series(obs.get(PWT_CN)), _series(obs.get(PWT_CGDPO))
    # A zero output year would divide to infinity; it is treated as missing, never as a value.
    ratio = _observed({y: cn[y] / cgdpo[y] for y in cn if y in cgdpo and cgdpo[y] != 0.0})
    if not ratio:
        raise Unavailable("Penn World Table has no overlapping capital and output years",
                          (PWT_CN, PWT_CGDPO))
    last = max(ratio)
    notes: list[str] = []

    def unextended(why: str) -> tuple[Series, tuple[int, ...], list[str]]:
        notes.append(f"the real-capital ratio is not extended past {last}: {why}. The window "
                     f"therefore ends there rather than being filled")
        return ratio, (), notes

    if not (_has_values(obs.get(GFCF_SHARE)) and _has_values(obs.get(REAL_GROWTH))):
        return unextended("the investment share or real growth series is absent")
    shares = _observed(_scaled(_series(obs.get(GFCF_SHARE)), 0.01))
    growth = _observed(_scaled(_series(obs.get(REAL_GROWTH)), 0.01))
    available = sorted(set(shares) & set(growth))
    if not available:
        return unextended("the investment share and real growth share no years")
    target = max(available)
    if target <= last:
        return ratio, (), notes
    needed = list(range(last + 1, target + 1))
    missing = [y for y in needed if y not in shares or y not in growth]
    if missing:
        return unextended(f"investment share or real growth is missing for {missing}")

    delta = _series(obs.get(PWT_DELTA))
    extended = dict(ratio)
    level = ratio[last]
    for year in needed:
        rate, _ = _depreciation(delta, prior, year)
        if not 0.0 < rate < 1.0:
            return unextended(f"the depreciation rate for {year} resolved to {rate}")
        g = growth[year]
        if g <= -1.0:
            return unextended(f"real growth of {g} in {year} makes the recursion undefined")
        level = (1.0 - rate) * level / (1.0 + g) + shares[year]
        extended[year] = level
    notes.append(f"the real-capital ratio is published through {last} and extended to {target} "
                 f"by perpetual inventory in ratio space; extended years are flagged")
    return dict(sorted(extended.items())), tuple(needed), notes


def net_new_credit_share(credit_ratio: Series, output: Series) -> Series:
    """(c_t Y_t - c_{t-1} Y_{t-1}) / Y_t over the years both are published.

    From the unadjusted ratio: the uplift is a level scale and applying it here would scale the
    injection a second time. The first year has no prior and stays missing.
    """
    common = sorted(set(credit_ratio) & set(output))
    if len(common) < 2:
        raise Unavailable("net new credit needs two years with both credit and output",
                          (CREDIT, GDP))
    credit = [credit_ratio[y] * output[y] for y in common]
    share = {common[0]: math.nan}
    for i in range(1, len(common)):
        share[common[i]] = (credit[i] - credit[i - 1]) / output[common[i]]
    return share


def population_growth(population: Series) -> Series:
    """Year-on-year fractional change, x_t / x_{t-1} - 1 over consecutive rows, gaps dropped."""
    years = sorted(population)
    growth = {years[i]: population[years[i]] / population[years[i - 1]] - 1
              for i in range(1, len(years))}
    return _observed(growth)


def window(required: Mapping[str, Series], start: Optional[int],
           end: Optional[int]) -> tuple[int, int, list[str]]:
    """(first, last, notes): the overlap of the required series, narrowed by configured bounds."""
    firsts, lasts = {}, {}
    for name, s in required.items():
        observed = _observed(s)
        if not observed:
            raise Unavailable(f"{name} has no observations", (name,))
        firsts[name] = min(observed)
        lasts[name] = max(observed)
    lo, hi = max(firsts.values()), min(lasts.values())
    notes = []
    if hi < max(lasts.values()):
        binding = sorted(n for n, last in lasts.items() if last == hi)
        notes.append(f"the window ends in {hi} because {', '.join(binding)} ends there")
    if lo > hi:
        raise Unavailable("the required series do not overlap")
    if start is not None:
        if start > hi or start < lo:
            raise Unavailable(f"the configured window start {start} lies outside {lo} to {hi}")
        lo = start
    if end is not None:
        if end < lo or end > hi:
            raise Unavailable(f"the configured window end {end} lies outside {lo} to {hi}")
        hi = end
    return lo, hi, notes


# ---------------------------------------------------------------------------
# The economy
# ---------------------------------------------------------------------------

def bank_saturation(spec: EconomySpec, obs: Mapping[str, Annual]
                    ) -> tuple[Series, Series, list[str]]:
    """Genreith's K/Y and the commercial-bank share: (saturation, loans / balance sheet, notes).

    K is the year-end balance-sheet total of all banks, Y nominal GDP in the same currency. Before
    ``gdp_splice_year`` Y comes from JST (the territory of the bank statistics), from it on from
    the World Bank in national currency. Both bank series are in euro billions.
    """
    total = _series(obs[BANK_TOTAL])
    loans = _series(obs.get(BANK_LOANS))
    lcu = _series(obs[GDP_LCU])
    jst = _series(obs.get(JST_GDP))
    splice = spec.gdp_splice_year
    gdp: Series = {}
    for year in sorted(set(lcu) | set(jst)):
        if splice is not None and year < splice:
            if year in jst:
                gdp[year] = jst[year] * 1e9 / spec.jst_currency_divisor
        elif year in lcu:
            gdp[year] = lcu[year]
    saturation = _observed({y: total[y] * 1e9 / gdp[y] for y in total
                            if y in gdp and not math.isnan(gdp[y]) and gdp[y] != 0.0})
    share = _observed({y: loans[y] / total[y] for y in loans
                       if y in total and not math.isnan(total[y]) and total[y] != 0.0})
    notes = ["the saturation axis is Genreith's K/Y: the balance-sheet total of all banks over "
             "nominal GDP, without the credit uplift"]
    if splice is not None:
        notes.append(f"nominal GDP is JST before {splice} and World Bank from {splice}, so the "
                     "denominator covers the territory of the bank statistics")
    return saturation, share, notes


def aggregate_pwt(obs: Mapping[str, Annual], members: tuple[str, ...]) -> dict[str, Annual]:
    """``obs`` with pwt.cn, pwt.cgdpo and pwt.delta replaced by the members' aggregate.

    Capital and output are summed only in years every member publishes both (both are at
    current PPPs, so the sums are comparable and their ratio is the aggregate's K_R/Y). Delta is
    the capital-weighted mean, the depreciation rate of the summed stock. Nothing is filled: a
    year with any member missing is not an aggregate year.
    """
    per = {m: (_series(obs.get(member_key(PWT_CN, m))), _series(obs.get(member_key(PWT_CGDPO, m))),
               _series(obs.get(member_key(PWT_DELTA, m)))) for m in members}
    years = set.intersection(*(set(_observed(cn)) & set(_observed(cg)) for cn, cg, _ in per.values()))
    cn_sum = {y: sum(per[m][0][y] for m in members) for y in sorted(years)}
    cg_sum = {y: sum(per[m][1][y] for m in members) for y in sorted(years)}
    delta = {y: sum(per[m][2][y] * per[m][0][y] for m in members) / cn_sum[y]
             for y in sorted(years)
             if all(y in per[m][2] and not math.isnan(per[m][2][y]) for m in members)}
    merged = dict(obs)
    merged[PWT_CN], merged[PWT_CGDPO], merged[PWT_DELTA] = cn_sum, cg_sum, delta
    return merged


def _cut(raw: Optional[Annual], last_year: int) -> Series:
    return {y: v for y, v in _series(raw).items() if y <= last_year}


def imf_debt_ratio(obs: Mapping[str, Annual], last_year: int) -> tuple[Series, list[str]]:
    """IMF private debt plus general government debt over GDP, as a ratio (not per cent).

    Government debt from the Global Debt Database where the economy has it, otherwise from the
    WEO, one source per economy (never spliced year by year).
    """
    private = _cut(obs.get(IMF_PRIVATE), last_year)
    if _has_values(obs.get(IMF_GOV_GDD)):
        government, source = _cut(obs.get(IMF_GOV_GDD), last_year), "Global Debt Database"
    else:
        government, source = _cut(obs.get(IMF_GOV_WEO), last_year), "WEO"
    ratio = _observed({y: (private[y] + government[y]) / 100.0 for y in private
                       if y in government})
    return ratio, [f"the saturation axis is IMF private debt (Global Debt Database) plus general "
                   f"government debt ({source}) over GDP, times the credit uplift: BIS publishes "
                   f"no total credit series for this economy"]


def missing_inputs(spec: EconomySpec, obs: Mapping[str, Annual]) -> tuple[str, ...]:
    """Series the economy cannot do without that are absent or empty in the snapshot."""
    missing: list[str] = []
    if spec.saturation_source == "bank_balance_sheet":
        for series_id in (BANK_TOTAL, GDP_LCU) + ((JST_GDP,) if spec.gdp_splice_year else ()):
            if not _has_values(obs.get(series_id)):
                missing.append(series_id)
    elif spec.saturation_source == "imf_debt":
        if not _has_values(obs.get(IMF_PRIVATE)):
            missing.append(IMF_PRIVATE)
        if not (_has_values(obs.get(IMF_GOV_GDD)) or _has_values(obs.get(IMF_GOV_WEO))):
            missing.append(IMF_GOV_GDD)
    elif spec.bis is None or not _has_values(obs.get(CREDIT)):
        missing.append(CREDIT)
    if (spec.stimulus_proxy == "net_new_credit" and spec.saturation_source != "bis_credit"
            and not _has_values(obs.get(CREDIT))):
        missing.append(CREDIT)
    has_pwt = spec.pwt is not None or bool(spec.pwt_members)
    if not has_pwt or not _has_values(obs.get(PWT_CN)):
        missing.append(PWT_CN)
    if not has_pwt or not _has_values(obs.get(PWT_CGDPO)):
        missing.append(PWT_CGDPO)
    for series_id in (GDP, SAVINGS):
        if not _has_values(obs.get(series_id)):
            missing.append(series_id)
    fiscal = FISCAL_IMF if spec.fiscal_source == "imf_weo" else FISCAL
    if spec.stimulus_proxy == "fiscal_balance" and not _has_values(obs.get(fiscal)):
        missing.append(fiscal)
    return tuple(missing)


def assemble(spec: EconomySpec, obs: Mapping[str, Annual], cal: Calibration) -> Assembled:
    """Raises :class:`Unavailable` with the reason when the economy cannot be assembled."""
    notes: list[str] = []
    if spec.pwt_members:
        obs = aggregate_pwt(obs, spec.pwt_members)
        notes.append(f"the real-capital ratio is the aggregate of {len(spec.pwt_members)} PWT "
                     "members: summed capital over summed output, both at PPP, in years every "
                     "member publishes")
    missing = missing_inputs(spec, obs)
    if missing:
        raise Unavailable(f"required series absent from the snapshot: {', '.join(missing)}",
                          missing)

    output = _series(obs[GDP])
    credit = _scaled(_series(obs.get(CREDIT)), 0.01)
    ratio, extended_years, capital_notes = capital_ratio(obs, spec.depreciation_prior)
    notes.extend(capital_notes)
    savings = _scaled(_series(obs[SAVINGS]), 0.01)

    if spec.stimulus_proxy == "net_new_credit":
        stimulus_share = net_new_credit_share(credit, output)
        notes.append("the stimulus proxy is net new credit, derived from BIS credit and World "
                     "Bank output; it is not comparable with a fiscal-balance economy")
    elif spec.fiscal_source == "imf_weo":
        stimulus_share = _scaled(_cut(obs[FISCAL_IMF], cal.imf_last_actual_year), 0.01)
        notes.append(f"the fiscal balance is IMF WEO general government net lending, read to "
                     f"{cal.imf_last_actual_year} (later WEO years are forecasts)")
    else:
        stimulus_share = _scaled(_series(obs[FISCAL]), 0.01)
    if spec.stimulus_reverse_sign:
        stimulus_share = _scaled(stimulus_share, -1.0)

    pop_growth: Optional[Series] = None
    if _has_values(obs.get(POPULATION)):
        pop_growth = population_growth(_series(obs[POPULATION]))
    else:
        notes.append("population is absent, so p_b falls back to the flow-ratio formula, which "
                     "is dimensionally inconsistent with its use")

    commercial: Series = {}
    if spec.saturation_source == "bank_balance_sheet":
        published, commercial, bank_notes = bank_saturation(spec, obs)
        notes.extend(bank_notes)
        saturation, axis = published, BANK_TOTAL
    elif spec.saturation_source == "imf_debt":
        published, imf_notes = imf_debt_ratio(obs, cal.imf_last_actual_year)
        notes.extend(imf_notes)
        axis = IMF_PRIVATE
        saturation = published if cal.credit_uplift == 1.0 else _scaled(published, cal.credit_uplift)
    else:
        published, axis = credit, CREDIT
        saturation = credit if cal.credit_uplift == 1.0 else _scaled(credit, cal.credit_uplift)

    stimulus_source = (CREDIT if spec.stimulus_proxy == "net_new_credit"
                       else FISCAL_IMF if spec.fiscal_source == "imf_weo" else FISCAL)
    required = {f"{GDP} (output)": output, f"{axis} (saturation)": saturation,
                f"{PWT_CN}/{PWT_CGDPO} (real-capital ratio, extended)": ratio,
                f"{SAVINGS} (savings rate)": savings,
                f"{stimulus_source} (stimulus)": stimulus_share}
    lo, hi, window_notes = window(required, spec.window_start, spec.window_end)
    notes.extend(window_notes)
    columns = list(required.values()) + ([pop_growth] if pop_growth is not None else [])
    candidate = [y for y in range(lo, hi + 1)
                 if all(y in c and not math.isnan(c[y]) for c in columns)]
    if not candidate:
        raise Unavailable(f"no year inside {lo} to {hi} has every required value")
    years = np.array(candidate, dtype=int)
    dropped = tuple(y for y in range(lo, hi + 1) if y not in set(candidate))
    if dropped:
        notes.append(f"years dropped inside the window for a missing value: {list(dropped)}")

    def col(s: Series) -> np.ndarray:
        return np.array([s[y] for y in candidate], dtype=float)

    y_level = col(output)
    real_capital = col(ratio) * y_level
    financial_capital = col(saturation) * y_level

    peak = real_capital / y_level
    max_ratio = float(np.max(peak))
    if max_ratio <= 0.0:
        raise Unavailable(f"the capital-output ratio peaks at {max_ratio}, so no scale exists")
    scale = cal.capital_target / max_ratio

    sat = col(saturation)
    if float(np.max(sat)) > cal.refuse_above:
        worst = candidate[int(np.argmax(sat))]
        raise Unavailable(
            f"saturation reaches {float(np.max(sat)):.3f} in {worst}, above the refusal ceiling "
            f"of {cal.refuse_above}: treated as an ingestion fault, not classified")

    history = [y for y in sorted(saturation) if y <= candidate[-1]
               and not math.isnan(saturation[y]) and y in ratio]
    share = col(stimulus_share)
    return Assembled(
        years=years,
        output=y_level,
        real_capital=real_capital * scale,
        financial_capital=financial_capital * scale,
        savings_rate=col(savings),
        stimulus_share=share,
        stimulus=share * y_level,
        population_growth=col(pop_growth) if pop_growth is not None else None,
        credit_published=col(published),
        saturation=sat,
        real_capital_ratio=col(ratio),
        extended=np.array([y in set(extended_years) for y in candidate], dtype=bool),
        normalisation_scale=float(scale),
        normalisation_max_ratio=max_ratio,
        normalisation_max_year=int(candidate[int(np.argmax(peak))]),
        window=(int(candidate[0]), int(candidate[-1])),
        history_years=np.array(history, dtype=int),
        history_saturation=np.array([saturation[y] for y in history], dtype=float),
        history_ratio=np.array([ratio[y] for y in history], dtype=float),
        commercial_share=np.array([commercial.get(y, math.nan) for y in candidate], dtype=float),
        history_commercial_share=np.array([commercial.get(y, math.nan) for y in history],
                                          dtype=float),
        dropped_years=dropped,
        extended_years=tuple(y for y in extended_years if y in set(candidate)),
        notes=tuple(notes),
    )
