"""The data need: what this engine requires, per economy, in the T5 format. Pure.

This is the specification the Data Feed engine is built against (sim-tech task T5). One row per
series and economy, marked ``in_snapshot`` or ``missing`` against a loaded snapshot, plus the
series the model's own definitions call for that no snapshot holds yet. It is served at
``GET /data-need`` and exported to ``data_need.csv`` for the T5 register.

A missing row names a candidate source to close the gap. Those candidates are proposals for the
Data Feed engine to evaluate, not sources this engine has checked.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import Calibration, DataNeed, DataNeedRow, EconomySpec
from .sources import CATALOGUE, SeriesDef

#: Years of history a series needs: five is the fit's floor, thirty gives a calibration that
#: spans more than one credit cycle (about 18 years).
REQUIRED_HISTORY_YEARS = 30

_CANDIDATE = {
    "bundesbank": "Deutsche Bundesbank time series API, dataflow BBBK1 (keyless)",
    "imf": "IMF DataMapper API (keyless): WEO and Global Debt Database panels",
    "jst": ("Jorda-Schularick-Taylor Macrohistory Database R6 (keyless; licence CC BY-NC-SA 4.0, "
            "non-commercial: check before commercial use)"),
    "world_bank": "World Bank WDI (keyless API)",
    "bis": "BIS total credit statistics, WS_TC bulk file (keyless)",
    "pwt": "Penn World Table 10.01 (Groningen, DOI 10.34894/QT5BCC)",
}

#: Where a row is missing because the default source does not publish it for that economy.
_GAP_CANDIDATE = {
    "bis.total_credit": ("IMF Global Debt Database (private plus public debt, % of GDP), or "
                         "the national central bank's credit statistics"),
    "pwt.cn": "AMECO net capital stock (OKND) for the euro area, or national accounts",
    "pwt.cgdpo": "AMECO GDP at current prices for the euro area, or national accounts",
    "pwt.delta": "AMECO consumption of fixed capital over net capital stock",
    "wb.GC.NLD.TOTL.GD.ZS": ("IMF World Economic Outlook general government net lending "
                             "(GGXCNL_NGDP), or OECD Economic Outlook"),
}

#: Series the model's definitions call for that no snapshot supplies yet.
_NOT_YET_SOURCED = (
    DataNeedRow(
        proposed_series_id="oecd.consolidated_financial_assets",
        index_block="K_I primary measure (book section 10.4): consolidated gross financial "
                    "assets, 400 to 600 per cent of GDP for advanced economies. Calibration "
                    "1.0.0 uses BIS credit times the uplift instead",
        country_or_scope="all",
        description="Financial balance sheets, total economy, consolidated financial assets",
        native_frequency="A", required_history_years=REQUIRED_HISTORY_YEARS,
        leading_concurrent_lagging="concurrent", scale_critical=True,
        candidate_source="OECD SDMX financial balance sheets (DF_T7PS1S2)",
        already_in_catalogue=False, status="missing"),
    DataNeedRow(
        proposed_series_id="bis.credit_financial_sector",
        index_block="Replaces the 1.4 credit uplift with a measured value: credit to the "
                    "financial sector, which BIS non-financial credit omits",
        country_or_scope="all",
        description="Debt of financial corporations, % of GDP",
        native_frequency="Q", required_history_years=REQUIRED_HISTORY_YEARS,
        leading_concurrent_lagging="leading", scale_critical=True,
        candidate_source="Federal Reserve Z.1 (US), ECB QSA, national flow of funds",
        already_in_catalogue=False, status="missing"),
)


def _area(spec: EconomySpec, series: SeriesDef) -> str | None:
    return {"world_bank": spec.world_bank, "bis": spec.bis, "pwt": spec.pwt,
            "bundesbank": spec.bank_area, "jst": spec.world_bank,
            "imf": spec.world_bank}[series.source]


_BANK_ONLY = {"bbk.OU0308", "bbk.OU0115", "wb.NY.GDP.MKTP.CN", "jst.gdp"}


def _used(spec: EconomySpec, series: SeriesDef) -> bool:
    """Whether this economy's configuration reads the series at all."""
    if series.series_id == "wb.GC.NLD.TOTL.GD.ZS":
        return spec.stimulus_proxy == "fiscal_balance" and spec.fiscal_source == "world_bank"
    if series.series_id == "imf.GGXCNL_NGDP":
        return spec.stimulus_proxy == "fiscal_balance" and spec.fiscal_source == "imf_weo"
    if series.series_id in ("imf.PVD_LS", "imf.GG_DEBT_GDP", "imf.GGXWDG_NGDP"):
        return spec.saturation_source == "imf_debt"
    if series.source == "pwt" and spec.pwt_members:
        return False     # rows for the members are added separately
    bank = spec.saturation_source == "bank_balance_sheet"
    if series.series_id in _BANK_ONLY:
        return bank and (series.series_id != "jst.gdp" or spec.gdp_splice_year is not None)
    if series.series_id == "bis.total_credit":
        return spec.saturation_source == "bis_credit" or spec.stimulus_proxy == "net_new_credit"
    return True


def build(cal: Calibration, present: Iterable[tuple[str, str]]) -> DataNeed:
    """``present`` is the (series_id, area) pairs a snapshot holds with at least one value."""
    have = set(present)
    rows: list[DataNeedRow] = []
    for spec in cal.economies:
        for series in CATALOGUE:
            if not _used(spec, series):
                continue
            area = _area(spec, series)
            found = area is not None and (series.series_id, area) in have
            candidate = _CANDIDATE[series.source]
            if not found:
                candidate = _GAP_CANDIDATE.get(series.series_id, candidate)
            if series.series_id in ("imf.GG_DEBT_GDP", "imf.GGXWDG_NGDP"):
                # One of the two government-debt sources suffices.
                other = "imf.GGXWDG_NGDP" if series.series_id == "imf.GG_DEBT_GDP" else "imf.GG_DEBT_GDP"
                if not found and area is not None and (other, area) in have:
                    continue
            rows.append(DataNeedRow(
                proposed_series_id=series.series_id,
                index_block=series.index_block,
                country_or_scope=spec.code,
                description=f"{series.description} ({series.units})",
                native_frequency=series.native_frequency,
                required_history_years=REQUIRED_HISTORY_YEARS,
                leading_concurrent_lagging=series.leading_concurrent_lagging,
                scale_critical=series.scale_critical,
                candidate_source=candidate,
                already_in_catalogue=False,
                status="in_snapshot" if found else "missing",
            ))
        for member in spec.pwt_members:
            for series in CATALOGUE:
                if series.source != "pwt":
                    continue
                found = (series.series_id, member) in have
                rows.append(DataNeedRow(
                    proposed_series_id=series.series_id, index_block=series.index_block,
                    country_or_scope=f"{spec.code}:{member}",
                    description=f"{series.description} ({series.units}), aggregate member",
                    native_frequency=series.native_frequency,
                    required_history_years=REQUIRED_HISTORY_YEARS,
                    leading_concurrent_lagging=series.leading_concurrent_lagging,
                    scale_critical=series.scale_critical,
                    candidate_source=_CANDIDATE["pwt"], already_in_catalogue=False,
                    status="in_snapshot" if found else "missing"))
    return DataNeed(rows=tuple(rows) + _NOT_YET_SOURCED)


CSV_COLUMNS = ("proposed_series_id", "model", "index_block", "country_or_scope", "description",
               "native_frequency", "required_history_years", "leading_concurrent_lagging",
               "scale_critical", "candidate_source", "already_in_catalogue", "status")
