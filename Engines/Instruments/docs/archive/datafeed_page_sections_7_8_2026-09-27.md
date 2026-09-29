# Archived from the Notion page 'Engine 01: Data Feed (datafeed)'

Sections 7 and 8, captured 2026-09-27 immediately before they were deleted from that
page at the owner's request, because the SQL Metadata catalogue now carries the series
and table inventory.

**Not everything below is in that catalogue.** The catalogue holds one row per series
and one row per table. It does not hold the per-country Bloomberg tickers (7.4), the
public-source fill fits (7.5), the gap and plausibility analysis (7.6), or the list of
still-unsourced needs (8.3). Those are kept here rather than lost.

Source: https://app.notion.com/p/3e50ba72543f8149a983fa9a8f69be97

---

## 7. Data in the store
### 7.1 Snapshots
<table header-row="true">
<tr>
<td>Snapshot</td>
<td>Contents</td>
<td>Cells</td>
<td>Checksum</td>
</tr>
<tr>
<td>`matlab-m_ts-2026-01-05`</td>
<td>Bloomberg pull by Web_Dataloader2.m, saved as M_TS.mat. Dates reconstructed from the loader's window; MATLAB's zeros turned back into gaps by rule. M_TS.mat sha256 082775a4d2895cd7efbdfa1f4a1651bf693e7a9a60c5005e452f3e58af44e2da.</td>
<td>78,424</td>
<td>`7f22f614dcadb4af...`</td>
</tr>
<tr>
<td>`matlab-m_ts-2026-01-05.public-5af69fd5`</td>
<td>matlab-m_ts-2026-01-05 with gaps filled from public sources where the fit holds (calibration 1.0.0). 5 of 12 candidates applied. Superseded; kept because snapshots are immutable.</td>
<td>79,079</td>
<td>`0394c09c69d95f9a...`</td>
</tr>
<tr>
<td>`matlab-m_ts-2026-01-05.public-8e90be47`</td>
<td>**Production.** Gaps filled where the fit holds, and household consumption for BR, DE, EU, GB, IN, TH replaced by World Bank share x Bloomberg GDP. 11 of 17 candidates applied.</td>
<td>79,078</td>
<td>`4fa931188809979e...`</td>
</tr>
</table>
Axis 2006-01-31 to 2026-01-31 (241 months), 16 countries, 21 series. In the production snapshot: 80,976 cells, 77,220 observed, 1,858 carried, 1,898 missing, 2,035 from public sources.
### 7.2 Countries (table `country`)
<table header-row="true">
<tr>
<td>Code</td>
<td>Name</td>
<td>ISO3 (public sources)</td>
<td>MATLAB field</td>
</tr>
<tr>
<td>`BR`</td>
<td>Brazil</td>
<td>`BRA`</td>
<td>`Brazil`</td>
</tr>
<tr>
<td>`CH`</td>
<td>Switzerland</td>
<td>`CHE`</td>
<td>`CH`</td>
</tr>
<tr>
<td>`CN`</td>
<td>China</td>
<td>`CHN`</td>
<td>`China`</td>
</tr>
<tr>
<td>`EU`</td>
<td>European Union</td>
<td>`EUU`</td>
<td>`EU`</td>
</tr>
<tr>
<td>`IN`</td>
<td>India</td>
<td>`IND`</td>
<td>`India`</td>
</tr>
<tr>
<td>`ID`</td>
<td>Indonesia</td>
<td>`IDN`</td>
<td>`Indonesia`</td>
</tr>
<tr>
<td>`MY`</td>
<td>Malaysia</td>
<td>`MYS`</td>
<td>`Malaysia`</td>
</tr>
<tr>
<td>`PH`</td>
<td>Philippines</td>
<td>`PHL`</td>
<td>`Philippines`</td>
</tr>
<tr>
<td>`TH`</td>
<td>Thailand</td>
<td>`THA`</td>
<td>`Thailand`</td>
</tr>
<tr>
<td>`GB`</td>
<td>United Kingdom</td>
<td>`GBR`</td>
<td>`UK`</td>
</tr>
<tr>
<td>`US`</td>
<td>United States</td>
<td>`USA`</td>
<td>`USA`</td>
</tr>
<tr>
<td>`JP`</td>
<td>Japan</td>
<td>`JPN`</td>
<td>`Japan`</td>
</tr>
<tr>
<td>`BD`</td>
<td>Bangladesh</td>
<td>`BGD`</td>
<td>`Bangladesh`</td>
</tr>
<tr>
<td>`VN`</td>
<td>Vietnam</td>
<td>`VNM`</td>
<td>`Vietnam`</td>
</tr>
<tr>
<td>`DE`</td>
<td>Germany</td>
<td>`DEU`</td>
<td>`Germany`</td>
</tr>
<tr>
<td>`ES`</td>
<td>Spain</td>
<td>`ESP`</td>
<td>`Spain`</td>
</tr>
</table>
### 7.3 Series registry (table `series`)
<table header-row="true">
<tr>
<td>Series</td>
<td>Category</td>
<td>Unit</td>
<td>Period</td>
<td>Used by HoNI index</td>
<td>M_TS sheet · column</td>
<td>Interior zero kept</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>consumer</td>
<td>index</td>
<td>annual</td>
<td>`corruption_freedom`</td>
<td>Consumer · 1</td>
<td>no</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>consumer</td>
<td>level</td>
<td>annual</td>
<td>`gdp_per_capita_growth`</td>
<td>Consumer · 2</td>
<td>no</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>consumer</td>
<td>level</td>
<td>annual</td>
<td>`population_growth`</td>
<td>Consumer · 3</td>
<td>no</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>consumer</td>
<td>ratio</td>
<td>monthly</td>
<td>`consumption_power`</td>
<td>Consumer · 5</td>
<td>yes</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>consumer</td>
<td>level</td>
<td>quarterly</td>
<td>`consumption_dependency`</td>
<td>Consumer · 7</td>
<td>no</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>consumer</td>
<td>ratio</td>
<td>annual</td>
<td>`labour_force`</td>
<td>Consumer · 8</td>
<td>no</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>debt</td>
<td>ratio</td>
<td>quarterly</td>
<td>capital saturation</td>
<td>Debt · 1</td>
<td>no</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>debt</td>
<td>level</td>
<td>quarterly</td>
<td>`external_debt_affordability`, `external_debt_exposure`</td>
<td>Debt · 2</td>
<td>no</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>debt</td>
<td>ratio</td>
<td>annual</td>
<td>`government_debt`</td>
<td>Debt · 3</td>
<td>no</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>debt</td>
<td>ratio</td>
<td>quarterly</td>
<td>capital saturation</td>
<td>Debt · 4</td>
<td>no</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>debt</td>
<td>level</td>
<td>quarterly</td>
<td>capital saturation</td>
<td>Debt · 5</td>
<td>no</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>equity</td>
<td>ratio</td>
<td>annual</td>
<td>`market_cap`</td>
<td>Equity · 2</td>
<td>no</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>fx</td>
<td>level</td>
<td>monthly</td>
<td>`external_debt_affordability`</td>
<td>FX · 1</td>
<td>yes</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>fx</td>
<td>index</td>
<td>monthly</td>
<td>`terms_of_trade`</td>
<td>FX · 2</td>
<td>yes</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>fx</td>
<td>level</td>
<td>monthly</td>
<td>`import_reserves`</td>
<td>FX · 3</td>
<td>no</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>inflation</td>
<td>ratio</td>
<td>monthly</td>
<td>`real_rate_10y`, `consumption_power`, `gdp_per_capita_growth`</td>
<td>Inflation · 1</td>
<td>yes</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>money</td>
<td>ratio</td>
<td>annual</td>
<td>`budget_balance`</td>
<td>Money · 1</td>
<td>yes</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>money</td>
<td>level</td>
<td>monthly</td>
<td>`monetary_supply`</td>
<td>Money · 2</td>
<td>no</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>production</td>
<td>level</td>
<td>annual</td>
<td>`monetary_supply`, `external_debt_exposure`, `consumption_dependency`</td>
<td>Production · 1</td>
<td>no</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>production</td>
<td>level</td>
<td>monthly</td>
<td>`import_reserves`</td>
<td>Production · 2</td>
<td>no</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>yields</td>
<td>ratio</td>
<td>daily</td>
<td>`real_rate_10y`</td>
<td>Yields · 1</td>
<td>yes</td>
</tr>
</table>
### 7.4 Tickers per country
Bloomberg ticker, scale applied by the MATLAB loader as `D * diag(scale)`, currency and description, from `Tickers/<Land>.xlsx`. Field is `PX_LAST` throughout. Also on `GET /series`.
#### Brazil (BR) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOBR Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNBRA Index`</td>
<td>1</td>
<td>BRL</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPBRA Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`BZGDWGSL Index`</td>
<td>0.001</td>
<td>BRL</td>
<td>Wage nominal (GDP)</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`BZGDFML$ Index`</td>
<td>0.001</td>
<td>BRL</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`BRLFPRTR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI223D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`BZEDTLEX Index`</td>
<td>0.001</td>
<td>BRL</td>
<td>External debt</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%BRA Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI223S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTABBR Index`</td>
<td>0.001</td>
<td>BRL</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDBRAZ Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBBRN Index`</td>
<td>1</td>
<td>BRL</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTBRL Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`223.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`BZPIIPCM Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBBR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`BZMS2 Index`</td>
<td>1</td>
<td>BRL</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`ECOXBRN Index`</td>
<td>1</td>
<td>BRL</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`223D1... Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GEBR10Y Index`</td>
<td>0.01</td>
<td>BRL</td>
<td>10Y Generic</td>
</tr>
	</table>
#### Switzerland (CH) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOCH Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPPGCHE Index`</td>
<td>1</td>
<td>CHF</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`EUPOCH Index`</td>
<td>1e-09</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`ENWGCHS Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>Wages nominal (GDP)</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`SZGNHHC Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOCHER Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI146D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDTLSWIT Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%CHE Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI146S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTABCH Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDSWIT Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBCHN Index`</td>
<td>1</td>
<td>CHF</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTCHF Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`146.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`SZCPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBCH Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`SZMSM2 Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`SZGNGDP Index`</td>
<td>0.001</td>
<td>CHF</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMCHN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GSWISS10 Index`</td>
<td>0.01</td>
<td>CHF</td>
<td>10Y Generic</td>
</tr>
	</table>
#### China (CN) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOCN Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNCHN Index`</td>
<td>1</td>
<td>CNY</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`CHPOP Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`CHTNTOTL Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`CNEXHOUS Index`</td>
<td>1</td>
<td>CNY</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOCHNR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI924D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`CNXLTOTC Index`</td>
<td>0.01</td>
<td>CNY</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`CHBGDGOP Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI924S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BCN Index`</td>
<td>0.001</td>
<td>CNY</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDCHIN Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBCNN Index`</td>
<td>0.001</td>
<td>CNY</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTCNY Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`924.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`CNCPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBCNY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`CNMSM2 Index`</td>
<td>1</td>
<td>CNY</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`CNEXTOTL Index`</td>
<td>1</td>
<td>CNY</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMCNN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GCNY10YR Index`</td>
<td>0.01</td>
<td>CNY</td>
<td>10Y Generic</td>
</tr>
	</table>
#### European Union (EU) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCODE Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom DE</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`GDCCPEUU Index`</td>
<td>1</td>
<td>USD</td>
<td>GDP per cap. PPP WB</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`EUPOEU Index`</td>
<td>1e-09</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`EUCEEA Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Wages nominal (GDP)</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`ENHHEAS Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOEMUR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI134D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDTLEURO Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`EUDBEURO Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI134S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`WDTLEURO Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Financial Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`WBMREMU Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBEUS Index`</td>
<td>1</td>
<td>EUR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTEUR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`EUCURS Index`</td>
<td>1</td>
<td>EUR</td>
<td>International reserves NET</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`EHPIEU Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBEUY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`ECMSM2 Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`EUAC27 Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ITTSEEAT Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GECU10YR Index`</td>
<td>0.01</td>
<td>EUR</td>
<td>10Y Generic</td>
</tr>
	</table>
#### India (IN) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOIN Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNIND Index`</td>
<td>1</td>
<td>INR</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPIND Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`INBGRIWG Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`IGQNPFC Index`</td>
<td>0.01</td>
<td>INR</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOINDR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI534D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`INDEBT Index`</td>
<td>0.001</td>
<td>INR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%IND Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI534S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTCBIN Index`</td>
<td>0.001</td>
<td>INR</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDINDI Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBINN Index`</td>
<td>1</td>
<td>INR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTINR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`534.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`EHPIIN Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBINY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`inmsm3 Index`</td>
<td>0.01</td>
<td>INR</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`INBGGDNA Index`</td>
<td>1</td>
<td>INR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMINN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GIND10YR Index`</td>
<td>0.01</td>
<td>INR</td>
<td>10Y Generic</td>
</tr>
	</table>
#### Indonesia (ID) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOID Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNIDN Index`</td>
<td>1</td>
<td>IDR</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`IDPQTOTL Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`IDWGFDN Index`</td>
<td>1</td>
<td>IDR</td>
<td>Wages nominal (median)</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`IDCGRH Index`</td>
<td>1</td>
<td>IDR</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`IDEMLAB% Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI536D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`IDEDTOTL Index`</td>
<td>0.001</td>
<td>IDR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%IDN Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI536S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTABID Index`</td>
<td>0.001</td>
<td>IDR</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDINDO Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBIDN Index`</td>
<td>1</td>
<td>IDR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTIDR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`536.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`IDCPIY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`IDBB%GDP Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`IDM2INDX Index`</td>
<td>1</td>
<td>IDR</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`IDGRP Index`</td>
<td>1</td>
<td>IDR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMIDN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GIDU10YR Index`</td>
<td>0.01</td>
<td>IDR</td>
<td>10Y Generic</td>
</tr>
	</table>
#### Malaysia (MY) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOMY Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNMYS Index`</td>
<td>1</td>
<td>MYR</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPMYS Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`MAMNSYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`5489B24 Index`</td>
<td>0.001</td>
<td>MYR</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOMYSR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI548D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`MAEDTOTL Index`</td>
<td>0.001</td>
<td>MYR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%MYS Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI548S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BMY Index`</td>
<td>0.001</td>
<td>MYR</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDMALA Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBMYN Index`</td>
<td>1</td>
<td>MYR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTMYR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`548.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`MACPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBMYY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`MAMS2TOT Index`</td>
<td>1</td>
<td>MYR</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`MAGRTOTL Index`</td>
<td>0.001</td>
<td>MYR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMMYN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`MAGY10YR Index`</td>
<td>0.01</td>
<td>MYR</td>
<td>10Y Bond Yield</td>
</tr>
	</table>
#### Philippines (PH) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOPH Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNPHL Index`</td>
<td>1</td>
<td>PHP</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPPHL Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`PHDWNNAN Index`</td>
<td>1</td>
<td>PHP</td>
<td>Wages nominal</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`5669B24 Index`</td>
<td>1</td>
<td>PHP</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`PHLFPRTE Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`USD BGN Curncy`</td>
<td>1</td>
<td>USD</td>
<td>Corp Debt%GDP **(placeholder ticker: no data)**</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`PHEDTOTL Index`</td>
<td>0.001</td>
<td>PHP</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%PHL Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI566L Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp + HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTCBPH Index`</td>
<td>0.001</td>
<td>PHP</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDPHIL Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBPHN Index`</td>
<td>1</td>
<td>PHP</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTPHP Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`566.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`PHC2II Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBPHY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`PHMSRBM3 Index`</td>
<td>1</td>
<td>PHP</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`PHGDPC$ Index`</td>
<td>0.001</td>
<td>PHP</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMPHN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`I10510Y Index`</td>
<td>0.01</td>
<td>PHP</td>
<td>10Y Bond Yield</td>
</tr>
	</table>
#### Thailand (TH) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOTH Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNTHA Index`</td>
<td>1</td>
<td>THB</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPTHA Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`THWGTLY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`5789B24 Index`</td>
<td>1</td>
<td>THB</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOTHAR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI578D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDTLTHAI Index`</td>
<td>0.001</td>
<td>THB</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%THA Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI578S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BTH Index`</td>
<td>0.001</td>
<td>THB</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDTHAI Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBTHN Index`</td>
<td>1</td>
<td>THB</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTTHB Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`578.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`THCPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`ECOGBTHN Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`THMM2 Index`</td>
<td>1</td>
<td>THB</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`THG PC$Q Index`</td>
<td>0.001</td>
<td>THB</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMTHN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`F12210Y Index`</td>
<td>0.01</td>
<td>THB</td>
<td>10Y Bond Yield</td>
</tr>
	</table>
#### United Kingdom (GB) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOGB Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNGBR Index`</td>
<td>1</td>
<td>GBP</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPGBR Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`UKAWMWHO Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`EUZHUK Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`UKLFMGWG Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI112D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`HELDGBGD Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%GBR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI112S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BGB Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDUK Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`UKTBTTBA Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTGBP Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`112.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`UKRPCJYR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBGBY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`OEGBMBAH Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`UKGRYBHA Index`</td>
<td>0.001</td>
<td>GBP</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`UKTBTTIM Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GUKG10 Index`</td>
<td>0.01</td>
<td>GBP</td>
<td>10Y Bond</td>
</tr>
	</table>
#### United States (US) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOUS Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPPCUSA Index`</td>
<td>1</td>
<td>USD</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPUSA Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`WGTROVER Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`PRCEDPHC Index`</td>
<td>0.001</td>
<td>USD</td>
<td>HH consumption expenditures</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOUSAR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI111D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDTLUS Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%USA Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI111S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BUS Index`</td>
<td>0.001</td>
<td>USD</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDUS Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBUSS Index`</td>
<td>1</td>
<td>USD</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTUSD Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`REASTOTL Index`</td>
<td>1</td>
<td>USD</td>
<td>International reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`CPI YOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EHBBUSY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`OEUSMBAH Index`</td>
<td>1</td>
<td>USD</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`GDP CUR$ Index`</td>
<td>1</td>
<td>USD</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMUSS Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`USGG10YR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>10Y Generic</td>
</tr>
	</table>
#### Japan (JP) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOJP Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNJPN Index`</td>
<td>1</td>
<td>JPY</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WBPOPJPN Index`</td>
<td>1e-06</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`JNLSUCTL Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`JGDOSCH Index`</td>
<td>1</td>
<td>JPY</td>
<td>HH consumption expenditures</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`JNUNPRT Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI158N Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`JNEDGED Index`</td>
<td>1</td>
<td>JPY</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`GDDI158G Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI158H Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTCBJP Index`</td>
<td>0.001</td>
<td>JPY</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDJAPA Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBJPN Index`</td>
<td>1</td>
<td>JPY</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTJPY Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`158.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`JNCPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`G7BBJAPN Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`JMNSM2SA Index`</td>
<td>1000</td>
<td>JPY</td>
<td>M2 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`JGDOSGDP Index`</td>
<td>1</td>
<td>JPY</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`JNINMTOT Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GJGB10 Index`</td>
<td>0.01</td>
<td>USD</td>
<td>10Y Yield</td>
</tr>
	</table>
#### Bangladesh (BD) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOBD Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNBGD Index`</td>
<td>1</td>
<td>BDT</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WPOPBDT Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`BNWETOTL Index`</td>
<td>0.01</td>
<td>BDT</td>
<td>Wages remittance</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`5139B24 Index`</td>
<td>1</td>
<td>BDT</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOBGDR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI513D Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`HELDBDGD Index`</td>
<td>0.001</td>
<td>BDT</td>
<td>External debt</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`GDDI513C Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI513S Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`9AACICBD Index`</td>
<td>0.001</td>
<td>BDT</td>
<td>Financial Debt (International)</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`WBMRBGD Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`BDTRBOTR Index`</td>
<td>0.01</td>
<td>BDT</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`USD BGN Curncy`</td>
<td>1</td>
<td>USD</td>
<td>Terms of Trade **(placeholder ticker: no data)**</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`513.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`5136640 Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`BNBFTFGD Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`5135R002 Index`</td>
<td>0.001</td>
<td>BDT</td>
<td>M2 Nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`BNGCCUR Index`</td>
<td>0.001</td>
<td>BDT</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`513D1... Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`BDGB10YY Index`</td>
<td>0.01</td>
<td>BDT</td>
<td>10Y Bond Yield</td>
</tr>
	</table>
#### Vietnam (VN) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOVN Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNVNM Index`</td>
<td>1</td>
<td>VND</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`WPOPVIET Index`</td>
<td>0.001</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`USD BGN Curncy`</td>
<td>1</td>
<td>USD</td>
<td>Wage growth **(placeholder ticker: no data)**</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`5829B24 Index`</td>
<td>1</td>
<td>VND</td>
<td>HH final consumption</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSOVNMR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`USD BGN Curncy`</td>
<td>1</td>
<td>USD</td>
<td>Corp Debt%GDP **(placeholder ticker: no data)**</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`VEDETOTL Index`</td>
<td>0.001</td>
<td>VND</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`IGS%VNM Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI582L Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp + HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBTC1VN Index`</td>
<td>0.001</td>
<td>VND</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDVIET Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`ECOYBVNN Index`</td>
<td>1</td>
<td>VND</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTVND Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`582.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>IMF FX reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`VNCPIYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`VNBDBAT% Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`5821136 Index`</td>
<td>1</td>
<td>VND</td>
<td>Monetary base (M2)</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`WGDPVIET Index`</td>
<td>1</td>
<td>VND</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMVNN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`V10YAVE Index`</td>
<td>0.01</td>
<td>VND</td>
<td>10Y Bond Yield</td>
</tr>
	</table>
#### Germany (DE) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCODE Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNDEU Index`</td>
<td>1</td>
<td>EUR</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`EUPODE Index`</td>
<td>1e-09</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`GRHIWAYY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`EUZHDE Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>HH consumption expenditures</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`WBSODEUR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI134N Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDTLGERM Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`GRFIDEBT Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI134H Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BDE Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDGERM Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`GRBTBALE Index`</td>
<td>1</td>
<td>EUR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTEUR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`134.055 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>International reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`GRCP20YY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`GRFIFINB Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`DEMSM2 Index`</td>
<td>1</td>
<td>EUR</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`GDPBGDPE Index`</td>
<td>1</td>
<td>EUR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`GRTBIME Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GTDEM10Y Govt`</td>
<td>0.01</td>
<td>EUR</td>
<td>10Y Generic</td>
</tr>
	</table>
#### Spain (ES) {toggle="true"}
	<table header-row="true">
<tr>
<td>Series</td>
<td>Ticker</td>
<td>Scale</td>
<td>Ccy</td>
<td>Description</td>
</tr>
<tr>
<td>`consumer.corruption_freedom`</td>
<td>`EFCOES Index`</td>
<td>1</td>
<td>USD</td>
<td>Corruption freedom</td>
</tr>
<tr>
<td>`consumer.gdp_per_capita`</td>
<td>`IPCNESP Index`</td>
<td>1</td>
<td>EUR</td>
<td>GDP per cap. IMF current</td>
</tr>
<tr>
<td>`consumer.population`</td>
<td>`EUPOES Index`</td>
<td>1e-09</td>
<td>USD</td>
<td>Population</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>`SPLCSYY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Wage growth</td>
</tr>
<tr>
<td>`consumer.household_consumption`</td>
<td>`ENHHESN Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>HH consumption expenditures</td>
</tr>
<tr>
<td>`consumer.labour_force_participation`</td>
<td>`SPUNACTR Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Labour force participation</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>`GDDI184N Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Corp Debt%GDP</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>`WDBTSPAI Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Debt external</td>
</tr>
<tr>
<td>`debt.government_gdp`</td>
<td>`SGGDAPDP Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Gov debt %GDP</td>
</tr>
<tr>
<td>`debt.household_gdp`</td>
<td>`GDDI184H Index`</td>
<td>0.01</td>
<td>USD</td>
<td>HH Debt%GDP</td>
</tr>
<tr>
<td>`debt.financial_sector`</td>
<td>`BDBT1BES Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>BIS fin Debt</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>`MCGDSPAI Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Market Cap %GDP</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>`SPTBEUBL Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>Trade Balance</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>`CTOTEUR Index`</td>
<td>1</td>
<td>USD</td>
<td>Citi Terms of Trade Commodities</td>
</tr>
<tr>
<td>`fx.reserves`</td>
<td>`184.056 Index`</td>
<td>0.001</td>
<td>USD</td>
<td>International reserves</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>`SPIPCYOY Index`</td>
<td>0.01</td>
<td>USD</td>
<td>CPI YoY</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>`EUBDSPAI Index`</td>
<td>0.01</td>
<td>USD</td>
<td>Budget balance % GDP</td>
</tr>
<tr>
<td>`money.broad_money`</td>
<td>`ESMOM2 Index`</td>
<td>1</td>
<td>EUR</td>
<td>M3 nominal</td>
</tr>
<tr>
<td>`production.gdp_nominal`</td>
<td>`EUGDES Index`</td>
<td>0.001</td>
<td>EUR</td>
<td>GDP nominal</td>
</tr>
<tr>
<td>`production.imports`</td>
<td>`ECOYMESN Index`</td>
<td>1</td>
<td>USD</td>
<td>Import</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>`GTESP10Y Govt`</td>
<td>0.01</td>
<td>EUR</td>
<td>10Y Generic</td>
</tr>
	</table>
### 7.5 Public-source fills
Every candidate is fitted against the raw Bloomberg series on the overlap and applied to missing December cells only if the fit holds. Level: scale `k = median(bloomberg / public)`, accepted if every overlap ratio is within tolerance of `k`; via an anchor where the series has no Bloomberg values (fitted on GDP). Rate: offset `b = median(bloomberg - public)`, accepted if every residual is within tolerance. Share: public share of an anchor times the Bloomberg anchor, each share within the plausibility bounds; with `replace` the series' Bloomberg cells are removed first. The table is the production snapshot's manifest.
<table header-row="true">
<tr>
<td>Country</td>
<td>Series</td>
<td>Source</td>
<td>Mode</td>
<td>Overlap</td>
<td>Fit</td>
<td>Deviation / tolerance</td>
<td>Verdict</td>
</tr>
<tr>
<td>BD</td>
<td>`production.gdp_nominal`</td>
<td>`worldbank:NY.GDP.MKTP.CN`</td>
<td>level</td>
<td>10</td>
<td>scale 1e-09</td>
<td>0.7% / 10%</td>
<td>**filled 2006-2015** (10 observed, 110 carried)</td>
</tr>
<tr>
<td>BD</td>
<td>`consumer.household_consumption`</td>
<td>`worldbank:NE.CON.PRVT.CN`</td>
<td>level</td>
<td>10</td>
<td>scale 1e-09 (anchor `production.gdp_nominal`)</td>
<td>0.7% / 10%</td>
<td>**filled 2006-2025** (20 observed, 210 carried)</td>
</tr>
<tr>
<td>VN</td>
<td>`consumer.household_consumption`</td>
<td>`worldbank:NE.CON.PRVT.CN`</td>
<td>level</td>
<td>20</td>
<td>scale 1.015e-09 (anchor `production.gdp_nominal`)</td>
<td>6.9% / 10%</td>
<td>**filled 2006-2025** (20 observed, 210 carried)</td>
</tr>
<tr>
<td>BR, DE, EU, GB, TH</td>
<td>`consumer.household_consumption`</td>
<td>`worldbank:NE.CON.PRVT.ZS`</td>
<td>share x `production.gdp_nominal`, replace</td>
<td>20</td>
<td>share of Bloomberg GDP</td>
<td>within 0.2-0.9</td>
<td>**replaced 2006-2025** (20 observed, 210 carried; 241 Bloomberg cells removed each)</td>
</tr>
<tr>
<td>IN</td>
<td>`consumer.household_consumption`</td>
<td>`worldbank:NE.CON.PRVT.ZS`</td>
<td>share x `production.gdp_nominal`, replace</td>
<td>20</td>
<td>share of Bloomberg GDP</td>
<td>within 0.2-0.9</td>
<td>**replaced 2006-2025** (20 observed, 210 carried; 176 Bloomberg cells removed; the quarterly series)</td>
</tr>
<tr>
<td>BR</td>
<td>`consumer.labour_force_participation`</td>
<td>`worldbank:SL.TLF.CACT.ZS`</td>
<td>rate</td>
<td>14</td>
<td>offset -0.0145</td>
<td>0.0139 / 0.015</td>
<td>**filled 2006-2011** (6 observed, 57 carried)</td>
</tr>
<tr>
<td>JP</td>
<td>`money.budget_balance_gdp`</td>
<td>`imf:GGXCNL_NGDP`</td>
<td>rate</td>
<td>19</td>
<td>offset -0.0001</td>
<td>0.0031 / 0.01</td>
<td>**filled 2006** (1 observed, 11 carried)</td>
</tr>
<tr>
<td>IN</td>
<td>`money.budget_balance_gdp`</td>
<td>`imf:GGXCNL_NGDP`</td>
<td>rate</td>
<td>15</td>
<td>offset +0.0265</td>
<td>0.0452 / 0.01</td>
<td>refused: residual 0.0452 after the fitted offset (general vs central government)</td>
</tr>
<tr>
<td>CN</td>
<td>`debt.external`</td>
<td>`worldbank:DT.DOD.DECT.CD`</td>
<td>level x FX</td>
<td>12</td>
<td>scale 9.977e-11</td>
<td>49.7% / 10%</td>
<td>refused: overlap deviates 49.7%</td>
</tr>
<tr>
<td>ID</td>
<td>`debt.external`</td>
<td>`worldbank:DT.DOD.DECT.CD`</td>
<td>level x FX</td>
<td>17</td>
<td>scale 1.025e-09</td>
<td>14.5% / 10%</td>
<td>refused: overlap deviates 14.5%</td>
</tr>
<tr>
<td>BD</td>
<td>`debt.external`</td>
<td>`worldbank:DT.DOD.DECT.CD`</td>
<td>level x FX</td>
<td>14</td>
<td>scale 1.004e-09</td>
<td>13.6% / 10%</td>
<td>refused: overlap deviates 13.6%</td>
</tr>
<tr>
<td>BD</td>
<td>`fx.trade_balance`</td>
<td>`worldbank:NE.RSB.GNFS.CN`</td>
<td>level</td>
<td>12</td>
<td>scale 8.484e-11</td>
<td>85.2% / 10%</td>
<td>refused: overlap deviates 85.2% (goods vs goods and services)</td>
</tr>
<tr>
<td>VN</td>
<td>`equity.market_cap_gdp`</td>
<td>`worldbank:CM.MKT.LCAP.GD.ZS`</td>
<td>rate</td>
<td>18</td>
<td>offset +0.1223</td>
<td>0.2172 / 0.01</td>
<td>refused: residual 0.2172 after the fitted offset</td>
</tr>
</table>
Stored public responses, all fetched 2026-09-27 (each fill cites its fetch ids on the manifest; frozen in `golden/public_2026-09-27.json`):
<table header-row="true">
<tr>
<td>Provider</td>
<td>Code</td>
<td>Country</td>
<td>sha256</td>
</tr>
<tr>
<td>imf</td>
<td>`GGXCNL_NGDP`</td>
<td>IN, JP</td>
<td>`40be9d7f91bb...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`CM.MKT.LCAP.GD.ZS`</td>
<td>VN</td>
<td>`de6cb7d5f15b...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`DT.DOD.DECT.CD`</td>
<td>BD</td>
<td>`f050ccf3954e...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`DT.DOD.DECT.CD`</td>
<td>CN</td>
<td>`b307532a9038...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`DT.DOD.DECT.CD`</td>
<td>ID</td>
<td>`ef5bfa3ccf18...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.CN`</td>
<td>BD</td>
<td>`031a2b61c7f6...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.CN`</td>
<td>IN (stored, no longer used)</td>
<td>`e4eba0c48316...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>BR</td>
<td>`5edcdd46f9c6...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>DE</td>
<td>`d532c19534c5...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>EU</td>
<td>`56491a29fa62...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>GB</td>
<td>`9a67a74ecf24...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>IN</td>
<td>`d2090e138673...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.ZS`</td>
<td>TH</td>
<td>`93ac6473576c...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.CON.PRVT.CN`</td>
<td>VN</td>
<td>`df0e65c815b3...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NE.RSB.GNFS.CN`</td>
<td>BD</td>
<td>`6f1a5c7b6e51...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NY.GDP.MKTP.CN`</td>
<td>BD</td>
<td>`eb1f31c73066...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`NY.GDP.MKTP.CN`</td>
<td>VN</td>
<td>`18a45c9516e3...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`PA.NUS.FCRF`</td>
<td>BD</td>
<td>`24a393d73d01...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`PA.NUS.FCRF`</td>
<td>CN</td>
<td>`159bcd9b4b09...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`PA.NUS.FCRF`</td>
<td>ID</td>
<td>`b7522fed8726...`</td>
</tr>
<tr>
<td>worldbank</td>
<td>`SL.TLF.CACT.ZS`</td>
<td>BR</td>
<td>`320b01973d94...`</td>
</tr>
</table>
### 7.6 Remaining gaps and plausibility
Year-end values still missing in the filled snapshot (2006 to 2025). None has a public candidate that fits:
<table header-row="true">
<tr>
<td>Series</td>
<td>Missing (country: years)</td>
</tr>
<tr>
<td>`consumer.wage_growth`</td>
<td>BD: 2006-2014; BR: 2025; CH: 2025; ID: 2006, 2023-2025; PH: 2025; VN: 2006-2025 (placeholder)</td>
</tr>
<tr>
<td>`debt.corporate_gdp`</td>
<td>PH: 2006-2025; VN: 2006-2025 (placeholders)</td>
</tr>
<tr>
<td>`debt.external`</td>
<td>BD: 2006-2010; CN: 2006-2012; ID: 2006-2007; JP: 2006-2013; MY: 2006-2008</td>
</tr>
<tr>
<td>`equity.market_cap_gdp`</td>
<td>VN: 2006</td>
</tr>
<tr>
<td>`fx.terms_of_trade`</td>
<td>BD: 2006-2025 (placeholder)</td>
</tr>
<tr>
<td>`fx.trade_balance`</td>
<td>BD: 2006-2013</td>
</tr>
<tr>
<td>`inflation.cpi_yoy`</td>
<td>CH: 2025</td>
</tr>
<tr>
<td>`money.budget_balance_gdp`</td>
<td>IN: 2006-2010</td>
</tr>
<tr>
<td>`yields.govt_10y`</td>
<td>BR: 2006; ID: 2006</td>
</tr>
</table>
Plausibility findings on `/coverage` for the **raw** snapshot: household consumption over nominal GDP outside 0.2 to 0.9, meaning the two Bloomberg series are not in the same unit. The production snapshot replaces these six series (section 7.5) and has no finding.
<table header-row="true">
<tr>
<td>Country</td>
<td>Consumption / GDP</td>
<td>Likely cause</td>
</tr>
<tr>
<td>Brazil (BR)</td>
<td>0.266 to 0.931</td>
<td>unstable ratio, mixed units over time</td>
</tr>
<tr>
<td>Germany (DE)</td>
<td>1.91 to 2.2</td>
<td>consumption about twice GDP's unit</td>
</tr>
<tr>
<td>European Union (EU)</td>
<td>0.112 to 0.125</td>
<td>euro area consumption against EU27 GDP, different scale</td>
</tr>
<tr>
<td>United Kingdom (GB)</td>
<td>1.79 to 3.09</td>
<td>different unit (MATLAB applied x0.3)</td>
</tr>
<tr>
<td>India (IN)</td>
<td>0.165 to 0.204</td>
<td>quarterly consumption against annual GDP (MATLAB applied x3)</td>
</tr>
<tr>
<td>Thailand (TH)</td>
<td>4.75e+08 to 5.99e+08</td>
<td>scale factors of the two sheets differ by about 10\\^9</td>
</tr>
</table>
### 7.7 MATLAB zero rule and placeholders (table `series_conversion`)
Of the cells in the 336 imported series: 133 NaN, 1,407 leading zeros and 48 trailing zeros became missing; 279 interior zeros were kept in rate and balance series or became missing elsewhere; 964 cells (4 series x 241 months) of placeholder tickers were dropped. Per-series counts are in the table `series_conversion` (336 rows, `GET /snapshots/matlab-m_ts-2026-01-05/conversions`); `golden/snapshot_2026-01-05/zero_rule.json` is the frozen test reference.
## 8. Data need: three-body model (`threebody`)
Updated 27.09.2026 from the `threebody` build (Macro Engine, `Projects/Engines/Macro/engines/threebody`, port 8011, calibration 1.3.0). Until `datafeed` serves it, `threebody` runs on a frozen local snapshot (`data/raw`, SHA-256 manifest) loaded into its own PostgreSQL schema. The series ids below are the ids `threebody` keys on; if `datafeed` serves the same ids, nothing downstream changes. Machine-readable (T5 format, one row per series and economy, 226 rows): `data_need.csv` in the engine folder, and `GET /data-need` on the running engine.
### 8.1 Series registry
<table header-row="true">
<tr>
<td>series_id</td>
<td>Source and identifier</td>
<td>Unit</td>
<td>Freq.</td>
<td>Used for</td>
<td>Used by</td>
</tr>
<tr>
<td>`wb.NY.GDP.MKTP.CD`</td>
<td>World Bank WDI</td>
<td>current USD</td>
<td>A</td>
<td>Y, the level every quantity is expressed against</td>
<td>all</td>
</tr>
<tr>
<td>`wb.NE.GDI.FTOT.ZS`</td>
<td>World Bank WDI</td>
<td>% of GDP</td>
<td>A</td>
<td>K_R extension past PWT (perpetual inventory)</td>
<td>all</td>
</tr>
<tr>
<td>`wb.NY.GDP.MKTP.KD.ZG`</td>
<td>World Bank WDI</td>
<td>%</td>
<td>A</td>
<td>K_R extension past PWT</td>
<td>all</td>
</tr>
<tr>
<td>`wb.NY.GNS.ICTR.ZS`</td>
<td>World Bank WDI</td>
<td>% of GDP</td>
<td>A</td>
<td>p_s, savings rate</td>
<td>all</td>
</tr>
<tr>
<td>`wb.SP.POP.TOTL`</td>
<td>World Bank WDI</td>
<td>persons</td>
<td>A</td>
<td>p_b, population growth</td>
<td>all</td>
</tr>
<tr>
<td>`wb.GC.NLD.TOTL.GD.ZS`</td>
<td>World Bank WDI</td>
<td>% of GDP</td>
<td>A</td>
<td>S, stimulus proxy (sign reversed)</td>
<td>BR, CH, EU, IN, MY, PH, TH, GB, US, DE, ES</td>
</tr>
<tr>
<td>`imf.GGXCNL_NGDP`</td>
<td>IMF WEO via DataMapper, general government net lending; read to 2024 (later years are forecasts)</td>
<td>% of GDP</td>
<td>A</td>
<td>S where the World Bank series is absent or short</td>
<td>JP, ID, BD, VN</td>
</tr>
<tr>
<td>`bis.total_credit`</td>
<td>BIS WS_TC: borrowers C, lenders A, market value, % of GDP, break adjusted; Q4 value</td>
<td>% of GDP</td>
<td>Q</td>
<td>Saturation axis × 1.4 uplift, and K_I; net new credit for CN</td>
<td>BR, CH, CN, EU (XM), IN, ID, MY, TH, GB, US, ES</td>
</tr>
<tr>
<td>`imf.PVD_LS`</td>
<td>IMF Global Debt Database, private debt (loans and debt securities)</td>
<td>% of GDP</td>
<td>A</td>
<td>Saturation axis (with government debt) × 1.4 where BIS has none</td>
<td>PH, BD, VN</td>
</tr>
<tr>
<td>`imf.GG_DEBT_GDP`</td>
<td>IMF Global Debt Database, general government debt</td>
<td>% of GDP</td>
<td>A</td>
<td>Government part of the IMF saturation axis</td>
<td>PH, VN</td>
</tr>
<tr>
<td>`imf.GGXWDG_NGDP`</td>
<td>IMF WEO, general government gross debt</td>
<td>% of GDP</td>
<td>A</td>
<td>Government part where the Global Debt Database has none</td>
<td>BD</td>
</tr>
<tr>
<td>`bbk.OU0308`</td>
<td>Bundesbank `BBBK1.M.OU0308`, balance-sheet total of all banks (MFIs); December value; DM ÷ 1.95583 before 1999</td>
<td>EUR bn</td>
<td>M</td>
<td>Genreith's K: Germany's saturation axis (no uplift)</td>
<td>DE</td>
</tr>
<tr>
<td>`bbk.OU0115`</td>
<td>Bundesbank `BBBK1.M.OU0115`, lending to domestic non-banks; December value</td>
<td>EUR bn</td>
<td>M</td>
<td>Genreith's commercial-bank share (Phase IV below 50%)</td>
<td>DE</td>
</tr>
<tr>
<td>`wb.NY.GDP.MKTP.CN`</td>
<td>World Bank WDI, GDP in national currency</td>
<td>EUR</td>
<td>A</td>
<td>Denominator of Germany's K/Y from 1990</td>
<td>DE</td>
</tr>
<tr>
<td>`jst.gdp`</td>
<td>Jordà-Schularick-Taylor Macrohistory Database R6, nominal GDP (West German DM before 1990). Licence CC BY-NC-SA 4.0 (non-commercial)</td>
<td>DM bn</td>
<td>A</td>
<td>Denominator of Germany's K/Y before 1990 (territory of the bank statistics)</td>
<td>DE</td>
</tr>
<tr>
<td>`pwt.cn`, `pwt.cgdpo`, `pwt.delta`</td>
<td>Penn World Table 10.01</td>
<td>mn 2017 USD PPP; rate</td>
<td>A</td>
<td>K_R/Y = cn/cgdpo; delta for the extension</td>
<td>all; EU as the sum over its 20 members</td>
</tr>
</table>
The model is annual; these are the sources' own frequencies, not the monthly month-end panel of T5. Keys: World Bank, PWT, JST and IMF use ISO3 codes, BIS its two-letter code, Bundesbank area DE.
### 8.2 Coverage per economy (snapshot SNP-41f60149296357f8)
All 16 HoNI economies are complete and projectable.
<table header-row="true">
<tr>
<td>Economy</td>
<td>Saturation axis</td>
<td>Fiscal / stimulus</td>
<td>Window</td>
</tr>
<tr>
<td>BR, CH, IN, MY, TH, GB, US, ES</td>
<td>BIS credit × 1.4</td>
<td>World Bank fiscal</td>
<td>BR 2010, CH 1995, IN 1981 (to 2022), MY 1996, TH 1997, GB 1972, US 1972, ES 1995; to 2024</td>
</tr>
<tr>
<td>CN</td>
<td>BIS credit × 1.4</td>
<td>Net new credit (BIS × GDP)</td>
<td>1996 to 2024</td>
</tr>
<tr>
<td>EU (euro area)</td>
<td>BIS XM × 1.4</td>
<td>World Bank EMU fiscal</td>
<td>1999 to 2024; capital from 20 members' PWT</td>
</tr>
<tr>
<td>ID, JP</td>
<td>BIS credit × 1.4</td>
<td>IMF WEO fiscal</td>
<td>ID 2001, JP 1997; to 2024</td>
</tr>
<tr>
<td>PH</td>
<td>IMF private + government debt × 1.4</td>
<td>World Bank fiscal</td>
<td>1990 to 2024</td>
</tr>
<tr>
<td>BD, VN</td>
<td>IMF private + government debt × 1.4</td>
<td>IMF WEO fiscal</td>
<td>BD 2003 to 2024, VN 2000 to 2022</td>
</tr>
<tr>
<td>DE</td>
<td>Bundesbank bank balance sheet / GDP (Genreith), from 1950</td>
<td>World Bank fiscal</td>
<td>1972 to 2024; phase history 1950 to 2024</td>
</tr>
</table>
The IMF debt axis was checked against BIS where both exist: TH and BR identical, MY, ID, CN, US, DE within a few per cent, IN 8% lower.
### 8.3 Still unsourced
<table header-row="true">
<tr>
<td>Need</td>
<td>Would replace</td>
<td>Candidate source</td>
</tr>
<tr>
<td>OECD consolidated financial assets (book 10.4's primary K_I)</td>
<td>K_I from credit</td>
<td>OECD SDMX financial balance sheets (DF_T7PS1S2)</td>
</tr>
<tr>
<td>Credit to the financial sector</td>
<td>The 1.4 credit uplift</td>
<td>Federal Reserve Z.1, ECB QSA, national flow of funds</td>
</tr>
<tr>
<td>Bank balance-sheet totals for the other economies</td>
<td>Germany being the only economy on Genreith's measure</td>
<td>ECB BSI (euro area members), Fed H.8 / Z.1, SNB, national central banks</td>
</tr>
</table>
### 8.4 Snapshot
- `snapshot_id` **SNP-41f60149296357f8**, frozen 27.09.2026, 106 files, 78,132 observations. Earlier snapshots are archived unchanged (`data/archive/SNP-98ca1e0341dd1bdd`, `SNP-0aa2543e874272d5`); a changed file is always a new snapshot.
- Vintages are mixed and recorded per file: BIS, PWT and the World Bank files for BR, CH, CN, DE, GB, IN, JP, US come from the old macrofield cache (July 2026) so the golden reconciliation compares like with like; everything else was fetched on 27.09.2026.
- Published gaps are stored as NULL, never filled.
