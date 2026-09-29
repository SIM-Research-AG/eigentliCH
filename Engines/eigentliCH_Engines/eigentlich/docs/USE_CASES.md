# Use cases: 20 clients

The demonstration set of eigentliCH (owner, 29.09.2026): twenty clients who together show the whole suite, from
the first conversation to the curator's approval. Each is an existing client record kept from the migration and
enriched with fictional but plausible Swiss figures. The other 63 records were erased through the store's erasure
path (`store.erase_client`, one client at a time, owner role), after a full backup of schema `eigentlich`
(`Projects/PostgreSQL/backups/eigentlich-before-use-cases-2026-09-29.sql`).

The set is built, and can be rebuilt, by `dev/build_use_cases.py` (steps `select`, `erase`, `enrich`,
`partners`, `mandates`, `threads`, `curate`, `reports`, `updates`, `approvals`, `revision`, `check`; every step
is idempotent; `mandates --refresh` and `reports --refresh` derive again from the latest sheet). Every write goes
through the app's API, the store's documented functions or the cockpit's curator routes: every plan change has its
decision, every answer names its content version (onboarding v2 `onb2@0.2.0`, intake v2 `intake@1.2` and, for the
partner section, v3 `intake@1.3`). The acting curator is Nicolas.

The figures are as the engines published them on 29.09.2026. The **lbs** lines are the sheets lbs@1.2.0 made
with calibration 1.3.0 (EIG-53, EIG-59): the partner stated, each goal's share of the yearly saving stated. The
**Mandate and pcp** lines are the parameter sets derived from those sheets, finalised by the curator from the
mandate presets v2 (`mp@1.1.0`, every role held by at least two instruments; all eight validated with pcp 1.2.0
against the Default Regime on 29.09.2026), and the pcp@1.2.0 runs on the **Default Regime**
`RGM-e2658e8e9bbbc81e` (optimism level default, as the cockpit chooses it, C-30) with the ReturnSet fmre serves
for it in the mandate's currency (CHF `RS-c472e411e39645f5`, EUR `RS-dd496e3d3e72affe`, USD
`RS-76d1a29edc752997`), and on the scenario Regimes aggregation derives from it (deferral `RGM-c0ed086f1916984e`,
stagflation `RGM-6bb531998bfefc4d`, depression `RGM-1af6968e287768c9`, hyperinflation `RGM-59eebfaf7744d8ec`).
Allocations are by role (Gain, Income, Stabilisation, Protection), rounded to the percent. Every client has a
second report, made by report@1.2.0 on that sheet and that allocation; the reports and threads of the first build
stay, and MiniMind (chatbot@1.2.0) answered the three questions it had refused. Model-derived research output.
Not investment advice.

## How to read a section

* **Situation** and **goals** as the client states them (goal names are quoted as they appear in the plan).
* **Demonstrates**: what the case shows that others do not, or shows best.
* **lbs**: net worth, the free (drawable) wealth, human capital E (expertise), N (network), H (health) of the
  client on a 0 to 1 scale, the risk profile, and the mandate proposal (the goal it rests on, the required return).
* **Mandate and pcp**: the preset the curator started from, what was kept from lbs, how the curve was levelled
  (to lbs's required return, to the preset's level when it is 0 %, or to what the household's bounds can earn when
  the required return is out of reach), the currency, the Regimes run, and the allocation by role (Gain, Income,
  Stabilisation, Protection).
* **Threads and reports**: what the client asked MiniMind, how it answered (from the reviewed notes, "mixed", or
  as a marked general assessment), what the curator did, and the reports and approvals.

Every client has: onboarding and intake answered in full (yearly contribution, education, network, health, rest
hours, ESG exclusions, risk willingness and crisis behaviour), a household, positions in all four roles on the
human and the financial side, an open tax liability (so net worth is stated), goals with amounts and dates, each
with its share of the yearly saving (retirement goals 0: they rest on the pension fund and the 3a), an education
goal that aims at income and network, a health dimension in the plan, a current lbs sheet with one gap only
(earning power, lbsim's), a parameter set finalised on that sheet, a succeeded pcp run of it on the Default Regime
(and on its scenario, for the eight scenario clients), and a report on that allocation. The 13 clients
with a partner have the intake's partner section answered and the partner's income and pension-fund balance as
positions the partner owns, so each sheet has two adults with age, income and human capital, a household income,
and a property and retirement verdict.

---

## 1. Simon N., 28, Frauenfeld (TG): the young saver's big education decision

**Situation.** Single, employed at a trust company (100 %, 42 hours), CHF 84 000, then 92 000 after a promotion.
Saves CHF 24 000 a year through an ETF plan, a little Bitcoin, plays floorball (rest 20 to 30 hours).
**Goals.** "Finanzielle Unabhängigkeit 2048" (CHF 1.1 million); the federal diploma in accounting and controlling
by 2028 (CHF 28 000, aim +15 000 salary and the veb.ch network); retirement need CHF 62 000 a year.
**Demonstrates.** A long horizon with a positive required return that levels the target curve; the deferral
scenario; an update after a raise; a MiniMind answer approved by the curator.
**lbs.** Net worth CHF 168 700, drawable CHF 113 500. E 0.98, N 0.91, H 1.00. Risk profile 0.53 (bound by
capacity). Required return **5.55 %** over 22.3 years with 70 % of the saving (CHF 16 800 a year; the diploma takes
30 %), reachable. One gap only (earning power, owned by lbsim).
Retirement: covered CHF 61 968 of 62 000 a year, a shortfall of CHF 32.
**Mandate and pcp.** Balanced CHF, curve shifted +2.05 points to the required return 5.55 % (the allocation within
the household's bounds is expected to earn about 5.7 %); currency, liquidity, role and ESG bounds from lbs. Default
Regime and **deferral**: Gain 50 %, Income 23 %, Stabilisation 12 %, Protection 15 % in both; global equities and
infrastructure lead on the Default Regime, US equities and precious metals under deferral.
**Threads and reports.** Two general assessments (no note covers education financing or salary growth): whether
to pay the diploma from savings or keep filling the 3a, and what the diploma is worth over a career; the first
**approved** by the curator. Report, then an **update** after the promotion to team lead (income 92 000, cadre).

## 2. Miriam S., 26, Basel (BS): the expat, in EUR

**Situation.** German, permit B since 2021, doctoral student in chemistry (CHF 54 000, 50 hours, rest only 5 to
10 hours). May return to Germany after the doctorate. Excludes weapons, fossil energy, child labour.
**Goals.** "Nach der Promotion 2030 in die Industrie" (a reserve of CHF 30 000 by 2029); project management IPMA D
and a GMP course in 2027 (CHF 6 500, aim: industry entry at CHF 95 000, the Swiss Chemical Society network).
**Demonstrates.** A mandate in **EUR** with a currency bound the curator sets (EUR from 50 %), the sustainable
preset, and a MiniMind answer **sent back with a revision**.
**lbs.** Net worth CHF 30 800, drawable CHF 22 000. E 1.00, N 0.79, H 0.85. Risk 0.39. The reserve is reached by
saving alone (required return 0 %, with 80 % of the saving): the curator keeps the preset's curve level.
**Mandate and pcp.** Sustainable balanced, EUR, EUR from 50 % (the curator's bound); required return 0 %, so the
preset's level is kept. Gain 45 %, Income 22 %, Stabilisation 14 %, Protection 18 %; EU and US equities on top.
**Threads and reports.** "What happens to my pension fund and 3a if I go back to Germany?" MiniMind answered as a
general assessment; the curator sent a **revision** with the EU rule (the mandatory part stays on a vested
benefits account, the 3a can be drawn on leaving). Second question: save in EUR or CHF. Report.

## 3. Fabienne G., 33, Köniz (BE): the young family buying a home

**Situation.** Married, Lina (2021) and Noah (2023); primary teacher at 60 %, CHF 56 000; her husband Marco
earns 92 000. Leasing, household saving CHF 18 000 a year, little rest.
**Goals.** "Wohneigentum 2032 850000" (owner-occupied); "Ausbildungsreserve für Lina und Noah bis 2039"
(CHF 60 000); a CAS in integrative education 2027 to 2028 (CHF 9 800, aim +9 000 at the same workload).
**Demonstrates.** A property goal with occupancy stated, the equity test, part-time work and its pension effect,
a child education reserve, a curator answer after MiniMind.
**lbs.** Net worth CHF 205 500 (with Marco's pension fund of CHF 78 000; liabilities CHF 25 500: leasing and
taxes). E 1.00, N 0.78, H 0.85; Marco (35, CHF 92 000) E 0.69, N 0.68, H 1.00. Household income CHF 148 000. Risk
0.29 (bound by willingness: she sold part in 2022). Deposit target CHF 170 000 (20 %); equity **does not meet**
today, affordability **does not meet** (CHF 150 167 of income needed; the income carries a price of about
CHF 838 000). Retirement shortfall CHF 14 177 a year. Required return **4.54 %** with 60 % of the saving.
**Mandate and pcp.** Balanced CHF, curve +1.04 points to 4.54 %, lbs's liquidity bound kept (goal in 6 years). Gain
39 %, Income 24 %, Stabilisation 16 %, Protection 21 %, 11 instruments.
**Threads and reports.** Equity and pension money for the flat (answered from the notes on equity and advance
withdrawal); "how much does 60 % cost my pension?", with the curator's answer on the BLVK rule and the salary
lever. Report.

## 4. Lukas M., 38, Baar (ZG): high income, USD shares, buying together without marriage

**Situation.** Swiss and US citizen, head of product at a US software company, CHF 168 000 plus RSUs of about
45 000 in USD; partner Sarah, not married, no cohabitation contract. A startup advisory seat.
**Goals.** "Eigentum kaufen 2030 1.8 Mio" (owner-occupied); an Executive MBA 2027 to 2029 (CHF 85 000, aim VP
Product, +40 000, an international network).
**Demonstrates.** A mandate in **USD** (growth preset), the deferral scenario, a parameter set **superseded**
after an unconverged solve, a two-turn MiniMind thread on the cohabitation gap, an update after an RSU vesting.
**lbs.** Net worth CHF 764 000 (with Sarah's pension fund), drawable CHF 364 000. E 1.00, N 0.98 (25 contacts
reaching beyond the industry), H 0.85; Sarah (36, doctor at 80 %, CHF 128 000) E 1.00, N 0.98, H 0.85. Household
income CHF 296 000. Risk 0.45. Deposit CHF 360 000: equity **meets**; affordability **does not meet** (CHF 318 000
needed). Retirement shortfall CHF 16 806 a year. Required return 0 % (60 % of the saving).
**Mandate and pcp.** Growth global, USD, currency bounds USD from 30 % and CHF from 20 %; required return 0 %, the
preset's level kept. Default Regime and **deferral**: Gain 49 %, Income 19 %, Stabilisation 15 %, Protection 16 % in
both; global real estate and US equities lead, mining equities under deferral. The chain shows the first build: a
set that did not converge under deferral and was superseded (the two failed runs stay in the history).
**Threads and reports.** "What is missing legally if something happens to one of us?" and the follow-up "is a
cohabitation contract enough?", both from the notes; the concentration risk of employer shares. Report and an
**update** (September vesting, securities up to CHF 231 000).

## 5. Noemi B., 39, Lachen (SZ): two part-time jobs, a practice of her own, a bad back

**Situation.** Single physiotherapist with two part-time positions (90 %, CHF 71 000, 46 hours with travel),
recurring back pain (H 0.7), no private disability cover.
**Goals.** "Eigene Physiotherapie-Praxis 2031 (Eigenmittel 110 000)"; "Gesundheitsreserve: drei Monate Ausfall
ohne Einkommen überbrücken" (CHF 18 000); an MAS in sports physiotherapy (CHF 24 000, a higher tariff).
**Demonstrates.** The step into self-employment, a health reserve as a goal, the conservative preset.
**lbs.** Net worth CHF 131 600. E 1.00, N 0.98, H 0.70. Risk 0.29. One gap only. Required return 1.30 % with 60 %
of the saving (the health reserve and the MAS take the rest). Retirement shortfall CHF 13 583 a year.
**Mandate and pcp.** Conservative CHF, curve +0.30 points to 1.30 %. Gain 30 %, Income 30 %, Stabilisation 19 %,
Protection 21 %; precious metals and the Swiss Performance Index at 20 % each.
**Threads and reports.** AHV and pension fund when becoming self-employed (from the notes); insuring a long
absence as a future self-employed person (mixed). Report.

## 6. Céline B., 36, Lausanne (VD): the sole trader without a pension fund

**Situation.** Graphic designer with her own business (sole trader, CHF 96 000, 48 hours), a teaching post at the
ECAL, a large 3a (CHF 64 000) and no pension fund, stated as a pension fund balance of 0. Full ESG.
**Goals.** "Atelier mit zwei Angestellten bis 2032" (CHF 80 000 for six months' wages and two workplaces); a CAS
in brand strategy 2027 (CHF 9 500, commissions from CHF 50 000).
**Demonstrates.** Self-employment without BVG, the large 3a, the sustainable preset held in CHF.
**lbs.** Net worth CHF 129 500. E 1.00, N 0.98, H 0.85. Risk 0.34. One gap only.
**Mandate and pcp.** Sustainable balanced, in CHF, the preset's level kept (required return 0 %). Gain 42 %, Income
18 %, Stabilisation 15 %, Protection 25 %.
**Threads and reports.** How much 3a without a pension fund, and whether a GmbH helps (mixed, from the 3a note).
Report.

## 7. Isabelle C., 43, Carouge (GE): the senior physician who wants to work less

**Situation.** Married, Emma (2014) and Hugo (2017); senior physician at the HUG, CHF 290 000, 54 hours, rest 5 to
10 hours (H 0.7). Buying into a group practice in 2030.
**Goals.** "Praxisanteil übernehmen 2030 (Eigenmittel 450 000)"; "Pensum auf 80 % senken ab 2027 (Erholung und
Familie)" (a year's income forgone, CHF 58 000); "Ausbildung Emma und Hugo (Studium ab 2032)" (CHF 120 000);
practice management training 2027 (CHF 12 000).
**Demonstrates.** A very high income, a health goal that costs income, Geneva, a curator answer on the buy-in.
**lbs.** Net worth CHF 938 000 (with Julien's pension fund), drawable CHF 300 000. E 1.00, N 0.98, H 0.70;
Julien (45, CHF 118 000) E 1.00, N 0.98, H 1.00. Household income CHF 408 000. Risk 0.38. Required return 2.72 % with
half the saving for the practice share. Retirement shortfall CHF 45 867 a year.
**Mandate and pcp.** Balanced CHF, curve -0.78 points to 2.72 %. Gain 44 %, Income 22 %, Stabilisation 14 %,
Protection 19 %.
**Threads and reports.** "What does 80 % cost me at the pension fund?" (from the part-time note), then the
curator: a staggered buy-in of up to CHF 280 000 closes the gap. Report.

## 8. Anita P., 45, Kriens (LU): back to work after ten years with the children

**Situation.** Married, Mia (2012) and Jan (2014); business economist, ten years at home, vested benefits of CHF
88 000, ten years of care credits. A small network (3 contacts in her own team: N 0.37). A CAS in project
management since August 2026.
**Goals.** "Wiedereinstieg 2027 und eigene Vorsorge aufbauen" (CHF 90 000 by 2035); the CAS (CHF 7 500, aim:
project lead at 50 %, the HSLU alumni network).
**Demonstrates.** The career changer, a stated zero income, the lowest network, an **update after signing a job
contract** (income 0 to CHF 46 000 at 50 %) **approved** by the curator; the swiss home bias preset, whose
universe now holds the Stabilisation role.
**lbs.** Net worth CHF 565 000 (with Daniel's pension fund of CHF 390 000). E 1.00, N 0.37, H 1.00; Daniel (47,
civil engineer, CHF 135 000) E 1.00, N 0.98, H 0.85. Household income CHF 181 000 after the update. Risk 0.14
(willingness). Retirement shortfall CHF 19 393 a year.
**Mandate and pcp.** Swiss home bias (its universe now holds two Stabilisation instruments of its own, the CHF
market-neutral and trend-following funds), the preset's level kept. Gain 29 %, Income 26 %, Stabilisation 18 %,
Protection 27 %; precious metals and trend following on top.
**Threads and reports.** AHV gaps and care credits (from the notes); "how do I get a network and a better salary
after the break?" (general). Report, **update approved**.

## 9. Corinne B., 46, Liestal (BL): widowed, a son about to study

**Situation.** Widowed since 2019, Jan (2009); pharmacy manager at 90 %, CHF 92 000, widow's and orphan's
pensions of CHF 33 000 a year; an owner-occupied flat with a CHF 380 000 mortgage. No further training yet
(expertise penalised for recency: E 0.66).
**Goals.** "Ausbildung des Sohnes gesichert bis 2034" (CHF 90 000 by 2028); management training for pharmacies
2027 to 2028 (CHF 11 000, aim: managing director, +12 000).
**Demonstrates.** The single parent, a short horizon, a will in progress, a thread closed by the client, and an
**update after enrolling**: E rises from 0.66 to 0.77 once further training is under way.
**lbs.** Net worth CHF 649 500 (liabilities CHF 390 500). E 0.77 after the update, N 0.68, H 0.85. Risk 0.20.
Required return 0 % (the reserve is already there).
**Mandate and pcp.** Conservative CHF, liquidity bound from lbs (goal in 1.9 years). The new sheet gives the same
mandate as the first build; it is finalised again with the current note and run on the Default Regime. Gain 30 %,
Income 29 %, Stabilisation 17 %, Protection 24 %.
**Threads and reports.** "What happens to my son if something happens to me?" (from the inheritance note; closed
by her); how to invest money needed in two years (general). Report and **update**.

## 10. Tanja E., 44, Zurich (ZH): the agency owner with a concentration risk and a sabbatical

**Situation.** Owner of a communications GmbH (12 staff), salary CHF 175 000 plus dividend 40 000, a stake valued
at CHF 1.4 million, 53 hours, rest 5 to 10 hours, two board seats; partner Stefan.
**Goals.** "Agentur unabhängig von mir machen bis 2033" (CHF 700 000 private wealth outside the firm); "Sabbatical
2027: drei Monate Auszeit, die Agentur läuft ohne mich" (CHF 45 000); Swiss Board School 2027 (CHF 15 000).
**Demonstrates.** The entrepreneur with a company, a sabbatical as a health goal, a required return above what
the bounds can earn, a chain of seven parameter sets, and an approval request **withdrawn** by the client.
**lbs.** Net worth CHF 1 816 000 (most of it the stake), drawable CHF 215 000. E 1.00, N 0.98, H 0.70; Stefan (46,
self-employed architect, CHF 110 000, no pension fund) E 1.00, N 0.98, H 0.85. Household income CHF 325 000. Risk
0.37. Required return **7.36 %** over 7.3 years with 60 % of the saving. Retirement shortfall CHF 47 263 a year.
**Mandate and pcp.** Balanced CHF. The required return of 7.36 % lies about two points above what the allocation
within the household's bounds is expected to earn (5.4 %), so the curator set the curve at **5.4 %** (+1.90 points)
and left the gap to the levers lbs names (horizon, saving, the goal's size). Gain 44 %, Income 23 %, Stabilisation
14 %, Protection 19 %. Of its seven sets, the first five show the presets tried in the first build.
**Threads and reports.** The concentration risk of her own firm (from the note); planning a sabbatical for money,
health and the firm (general). Report; she asked for approval and **withdrew** the request.

## 11. Michele B., 47, Lugano (TI): the architect with a rental building and rising rates

**Situation.** Married (separation of property), Luca (2008) and Sofia (2011); owns an architecture AG; his home
in Lugano and a four-flat building in Mendrisio (CHF 1.9 million, rent CHF 96 000), mortgages of CHF 2.03 million,
a reserve of only three months.
**Goals.** "Renditeobjekt halten und 2035 amortisiert haben" (CHF 250 000); "Studium Luca und Sofia 2027–2034"
(CHF 100 000); a CAS in property valuation 2027 (CHF 11 000, valuation mandates of +25 000 a year).
**Demonstrates.** Rental property, two mortgages, the **stagflation** scenario, a curator answer on amortising.
**lbs.** Net worth CHF 1 957 000 on assets of 4.01 million (with Chiara's pension fund). E 1.00, N 0.98, H 0.85;
Chiara (45, teacher at 40 %, CHF 42 000) E 1.00, N 0.68, H 1.00. Household income CHF 278 000. Risk 0.19 (capacity:
the reserve). Required return **12.51 %** over 9.3 years with half the saving (CHF 10 000 a year; the studies take
40 %). Retirement shortfall CHF 51 879 a year.
**Mandate and pcp.** Swiss home bias. The required return of 12.51 % is out of reach for a household bound by
capacity (risk 0.19): the allocation within its bounds is expected to earn about 4.0 %, so the curator set the curve
at **4.0 %** (+0.50 points). Default Regime: Gain 32 %, Income 18 %, Stabilisation 17 %, Protection 33 %;
**stagflation**: Gain 32 %, Income 26 %, Protection 24 %, Swiss dividend equity at 20 %.
**Threads and reports.** Amortise or invest (from the notes; the curator adds: build a six-month reserve first);
rents and mortgages under high inflation (general). Report.

## 12. Reto S., 52, Wil (SG): the master joiner before the succession

**Situation.** Owner of a joinery AG with 25 staff (stake CHF 1.8 million), salary CHF 155 000, 55 hours, knee
surgery due (H 0.7), exam expert and trade association board.
**Goals.** "Werkstatt an Nachfolger übergeben 2035" (CHF 600 000 private wealth); "Knieoperation 2027: vier
Monate Ausfall überbrücken" (CHF 30 000); succession training at KMU-HSG 2027 (CHF 6 000).
**Demonstrates.** Business succession by management buy-out, a health goal, a required return out of reach
for the bounds (the curve set at what they can earn), a curator answer.
**lbs.** Net worth CHF 2 837 000 (with Monika's pension fund). E 1.00, N 0.98, H 0.70; Monika (51, the joinery's
accounts at 40 %, CHF 36 000) E 0.63, N 0.92, H 0.85. Household income CHF 191 000. Risk 0.26. Required return
**6.30 %** with 70 % of the saving. Retirement shortfall CHF 20 505 a year.
**Mandate and pcp.** Income focus (its universe now holds world equities and two Stabilisation funds). The required
return of 6.30 % is above the 3.0 % the allocation within the bounds is expected to earn: the curve is set at
**2.9 %** (-0.10 points). Gain 30 %, Income 32 %, Stabilisation 16 %, Protection 22 %.
**Threads and reports.** How the sale price relates to his pension (from the concentration note), and the
curator: a vendor loan is the same cluster risk; use the pension fund buy-in before the sale. Report.

## 13. Claudia I., 53, Scuol (GR): mortgage, fixed rate ending, a mother who needs care

**Situation.** Hotel director (CHF 115 000, 47 hours, seasonal), husband a self-employed mountain guide; a chalet
with a CHF 640 000 fixed mortgage until 2029; her mother (84) needs increasing care.
**Goals.** "Hypothek bis 2040 halbieren" (CHF 320 000); "Betreuung der Mutter in Scuol: Entlastungsdienst und
Pflegekosten 2027–2029" (CHF 36 000); a postgraduate diploma in hotel management 2027 (CHF 16 000).
**Demonstrates.** Amortisation, direct or indirect through the 3a, care for a parent, the **stagflation**
scenario, and a MiniMind refusal answered after the client rephrased.
**lbs.** Net worth CHF 862 000. E 1.00, N 0.98, H 0.85; Gian (55, self-employed mountain guide, CHF 68 000, no
pension fund) E 0.90, N 0.98, H 0.85. Household income CHF 183 000. Risk 0.29. Required return 5.28 % over 14.3
years with half the saving (care for her mother takes 35 %). Retirement shortfall CHF 37 296 a year.
**Mandate and pcp.** Income focus. Required 5.28 %, expected about 3.0 % within the bounds: the curve is set at
**3.0 %** (no shift). Default Regime and **stagflation**: Gain 30 %, Income 33 %, Stabilisation 16 %, Protection
21 % in both; global high yields lead, with Swiss dividend equity on the Default Regime and global equities under
stagflation.
**Threads and reports.** Direct or indirect amortisation (from the notes). "How can I support my mother without
risking my pension?" was refused as outside MiniMind's domain; asked again as "what does a lower workload for
her care mean for my pension fund and AHV?", answered from the notes. Asked again as first put, in the same
thread, MiniMind now answers it (mixed: the AHV rule for part-time work from the notes, then a marked general
assessment: the employer, the pension fund's rules, care credits in Graubünden, a care advice service). Two reports.

## 14. Yasmin T., 53, Kreuzlingen (TG), and 15. Elio T., 58: one couple, two records

The couple keeps two client records (both partners were kept, none erased). Each names the other in the
household and answers her or his own questionnaires with the same household code.

**Yasmin.** Kindergarten teacher at 60 % (CHF 70 980), healthy (H 1.00), a small network (N 0.31). Goals: "Ferienhaus
kaufen 2036 1.5 Mio" (a second home: 30 % equity, no pension money allowed); a CAS in early education 2027 to 2028
(CHF 8 500). lbs: net worth CHF 846 000 (with Elio's pension fund); household income CHF 285 860; Elio as her
record states him E 1.00, N 0.78, H 0.50; equity for the holiday home **does not meet**, affordability **meets**;
retirement **meets**; required return **5.21 %** over 10.3 years with 85 % of the saving. Balanced CHF, curve +1.71
points to 5.21 % (the allocation is expected to earn about 4.7 %, within a point, so the curve follows lbs): Gain
29 %, Income 27 %, Stabilisation 18 %, Protection 26 %. Thread: may we use the pension fund or 3a for a holiday
home? (from the notes: no). Two reports.

**Elio.** Head of development (CHF 214 880, 50 hours), an exhaustion in 2025 (H 0.50, hardly any rest), CHF 616 000
in the pension fund, sold everything in 2008 (crisis behaviour caps his willingness: risk 0.20). Goals: "Pensum
80 % ab 2027: Reserve für die Lohneinbusse" (CHF 120 000, the mandate goal); a staggered buy-in into the second
pillar (CHF 150 000); a CAS in leadership coaching 2027 (mentoring mandates from 60). lbs: net worth CHF 756 000
(with Yasmin's pension fund); household income CHF 285 860; Yasmin as his record states her E 1.00, N 0.31, H 1.00;
required return **16.18 %** for the reserve by the end of 2027 with half the saving (the buy-in takes 40 %);
retirement shortfall CHF 3 783 a year. The reserve by the end of 2027 cannot be earned: 74 000 drawable and
22 500 a year would need 16 % a year for 1.25 years, and a household with risk 0.20 is expected to earn about 4.4 %
within its bounds. The curator set the curve at **4.3 %** (+0.80 points on the crisis-resilient curve) and left the
gap to the levers (a later date for the reduction, more of the saving than the 50 %, or a smaller reserve).
Crisis-resilient: Gain 12 %, Income 10 %, Stabilisation 17 %, Protection 61 %; the Bloomberg Multiverse bond index
(hedged in CHF) and precious metals at 20 % each. Threads: annuity or lump sum (from the note, **approved** by the
curator), and reducing to 80 % before a buy-in. Two reports.

**Demonstrates.** A couple with separate records, the second-home rule, burnout and reduced hours, "Rente oder
Kapital", the crisis-resilient preset, and a couple whose two records each state the other as the partner.

## 16. Franziska O., 56, Olten (SO): divorced, exhausted, a daughter at university

**Situation.** Divorced in 2019 (pension split), ward manager at the cantonal hospital, CHF 104 000, 46 hours with
overtime, H 0.50; daughter Lea (2005) studies in Bern.
**Goals.** "Studium der Tochter finanzieren bis 2031" (CHF 45 000 by 2027); "Pensum auf 80 % reduzieren ab 2027
(Gesundheit): Lohneinbusse auffangen" (CHF 21 000); an MAS in health care management 2027 to 2029 (CHF 24 000).
**Demonstrates.** Divorce and the pension split, reduced hours for health, an **update after the reduction**
(income CHF 83 200, 36 hours), an approved answer.
**lbs.** Net worth CHF 358 000. E 1.00, N 0.78, H 0.50. Risk 0.14. Retirement shortfall CHF 17 090 a year after
the reduction.
**Mandate and pcp.** Crisis-resilient (its universe now holds two Income instruments), the preset's level kept. Gain
14 %, Income 9 %, Stabilisation 18 %, Protection 59 %.
**Threads and reports.** Closing the divorce gap with buy-ins (from the divorce note); what 80 % means for her
pension and health (**approved**). Report and **update**.

## 17. Regula A., 58, Thun (BE): the notary, an advance on inheritance and the compulsory shares

**Situation.** Notary and partner (80 %, CHF 145 000), husband retired, two adult children; free wealth of CHF 485
000, pension fund 640 000, a house in Thun; an inheritance from her mother expected. Will, marriage contract,
advance directive and patient decree all in place; three foundation board seats.
**Goals.** "Erbgang vorbereiten und 2034 aufhören" (a retirement goal); "Freies Vermögen bis 2034 auf 900 000
aufbauen" (the mandate goal); "Erbvorbezug an Andrea und Martin 2028", lowered from 2 x 100 000 to 2 x 80 000
after the curator's revision; a CAS in mediation 2027 (CHF 12 000, mediation mandates after 2034).
**Demonstrates.** Inheritance law, the **depression** scenario, a report **sent back with a revision**, a change
the client makes in answer, and an **update approved**; also the longest parameter-set chain (nine).
**lbs.** Net worth CHF 2 478 000. E 1.00, N 0.98 (20 contacts beyond her field, three mandates), H 0.85; Hans (66,
retired, pensions of CHF 62 000) E 1.00, N 0.98, H 0.85. Household income CHF 207 000. Risk 0.43. Required return
**4.44 %** over 7.8 years with 60 % of the saving. Retirement shortfalls CHF 54 050 and CHF 34 050 a year (the two
retirement goals).
**Mandate and pcp.** Balanced CHF, curve +0.94 points to 4.44 %. Default Regime: Gain 48 %, Income 21 %,
Stabilisation 14 %, Protection 17 %; **depression**: Gain 30 %, Income 33 %, Stabilisation 20 %, Protection 17 %.
Seven of the nine sets and the nine failed runs are the first build's (the income preset under depression).
**Threads and reports.** The compulsory shares and what changed in 2023 (from the note). Report; the curator sent
a revision; Regula lowered the advance and asked for an update, which the curator **approved**. The first revision
had come back from the report engine's cache as a copy of the report; Regula asked for approval of it, and the
curator sent a real revision (report 1.2.0, `revision_of` and the curator's note: the advance at 2 x 80 000 so Hans's
compulsory share is untouched, the allocation computed again), which now differs from the first and shows the note.
A second report on the new sheet and allocation.

## 18. Kurt W., 64, Baden (AG): a year before retirement

**Situation.** Head of purchasing (CHF 148 000), retiring at the end of 2027; wife retired; pension fund CHF 680
000 at a 5.2 % conversion rate, three 3a accounts (CHF 175 000), a flat with a CHF 250 000 mortgage.
**Goals.** "Pensionierung 2027 planen: Rente oder Kapital" (CHF 88 000 a year); "Freies Vermögen bis 2035 real
erhalten" (CHF 280 000); a course for foundation and company boards 2027 (CHF 5 000).
**Demonstrates.** Annuity or lump sum, staggered 3a withdrawal, the **depression** scenario, a report
**approved** by the curator.
**lbs.** Net worth CHF 1 789 000, drawable CHF 230 000. E 1.00, N 0.96, H 0.85; Rosmarie (63, retired, a pension of
CHF 18 000) E 0.62, N 0.39, H 0.85. Household income CHF 166 000. Risk 0.40. Required return 0.55 % with 80 % of the
saving. Retirement shortfall CHF 7 635 a year.
**Mandate and pcp.** Conservative CHF, curve -0.45 points to 0.55 %. Default Regime: Gain 30 %, Income 30 %,
Stabilisation 20 %, Protection 20 %, 7 instruments; **depression**: Protection 40 %, the other roles at 20 %, 6
instruments.
**Threads and reports.** "How do I decide between annuity and lump sum?" and "how do I draw my three 3a accounts
for tax?" (both from the notes). Report, **approved**.

## 19. Esther W., 67, Winterthur (ZH): widowed, still working, the advance directive

**Situation.** Widowed, school secretary at 40 % until summer 2027, AHV since 2024, pension fund deferred (CHF
340 000), an owner-occupied flat. The lowest expertise and network in the set (E 0.78, N 0.39).
**Goals.** "Ausgaben im Ruhestand aus frei verfügbarem Vermögen gedeckt" (CHF 62 000 a year); "Ab 2027 vom Vermögen
leben" (keep CHF 200 000 until 2031); "Vorsorgeauftrag und Patientenverfügung beurkunden lassen" (CHF 1 800); a
reserve for Spitex and a barrier-free conversion (CHF 60 000); a course for private guardians 2027.
**Demonstrates.** Old age, care and incapacity, the **hyperinflation** scenario, a report **awaiting** the curator,
a MiniMind refusal followed by a rephrased question and a curator answer.
**lbs.** Net worth CHF 1 191 000. E 0.78, N 0.39, H 0.70. Risk 0.09 (the lowest). Required return 0.48 %.
Retirement shortfall CHF 9 786 a year.
**Mandate and pcp.** Conservative CHF, curve -0.52 points to 0.48 %; the same mandate as the first build, finalised
again with the current note and run on the Default Regime. Default Regime: Gain 26 %, Income 25 %, Stabilisation
19 %, Protection 31 %, 10 instruments; **hyperinflation**: Income 28 %, Protection 27 %, precious metals and global
high yields at 20 % each.
**Threads and reports.** "Who decides for me if I can no longer judge?" was refused as outside the domain; asked
again ("what does an advance directive regulate?") it was answered from the note, and the curator added how to
have it notarised. Asked again as first put, in the same thread, it is now answered (mixed: what an advance
directive regulates and the adult protection authority from the note, then a marked general assessment: no
spouse's statutory right of representation, handwritten or notarised, registration with the civil registry). Annuity
or lump sum while living alone. Report, **awaiting** approval; a second report.

## 20. Peter S., 68, Bern (BE): the retired engineer and the holiday chalet

**Situation.** Retired civil engineer and his wife; pensions of CHF 86 160 a year (the pension fund was taken as
an annuity: balance 0), a flat in Bern and a chalet in Adelboden with a CHF 200 000 mortgage; wants to work as a
building-damage expert.
**Goals.** "Ferienchalet Adelboden an Thomas und Reto übertragen 2030 (Ausgleich an Anna 180 000)"; "Reserve für
Pflege und Betreuung von Margrit und mir ab 2030" (CHF 120 000); a certificate in building-damage expertise 2027
(CHF 6 500, expert opinions worth CHF 20 000 a year).
**Demonstrates.** Transfer to the children in lifetime, equalisation between siblings, the **hyperinflation**
scenario, a thread the curator closes.
**lbs.** Net worth CHF 2 079 000, drawable CHF 350 000. E 1.00, N 0.85, H 0.70; Margrit (66) E 0.61, N 0.52,
H 0.85. The couple's pensions of CHF 86 160 a year are two positions now (Peter CHF 63 480, Margrit's AHV
CHF 22 680), so the household income is stated. Risk 0.38. Retirement: covered CHF 31 980 of 96 000 a year.
**Mandate and pcp.** Crisis-resilient, the preset's level kept (required return 0 %). Default Regime: Protection
53 %, Gain 20 %; **hyperinflation**: Gain 25 %, Income 21 %, Stabilisation 14 %, Protection 39 %, precious metals and
CHF corporate loans on top.
**Threads and reports.** The transfer and the compulsory share: refused first, answered from the note after the
rephrase, then the curator (value at the date of the inheritance, the mortgage passes with the chalet) and
**closed** the thread. A closed thread takes no message, so Peter asked the refused question again in a new
thread ("Meine erste Frage zum Chalet blieb damals ohne Antwort ..."); MiniMind now answers it (mixed: the
compulsory shares from the Erbrecht note, then a marked general assessment on the estate's value, the form of a
will or inheritance contract, and a specialist). Two reports.

---

## Coverage matrix

Columns: Si Simon, Mi Miriam, Fa Fabienne, Lu Lukas, No Noemi, Cé Céline, Is Isabelle, An Anita, Co Corinne,
Ta Tanja, Mc Michele, Re Reto, Cl Claudia, Ya Yasmin, El Elio, Fr Franziska, Rg Regula, Ku Kurt, Es Esther,
Pe Peter.

| Capability | Si | Mi | Fa | Lu | No | Cé | Is | An | Co | Ta | Mc | Re | Cl | Ya | El | Fr | Rg | Ku | Es | Pe | n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Onboarding v2 and intake v2 in full (yearly contribution, education, health, rest, ESG) | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| Education goal aiming at income and network | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| Health or care goal | | | | | x | | x | | | x | | x | x | | x | x | | | x | x | 9 |
| Household with a partner | | | x | x | | | x | x | | x | x | x | x | x | x | | x | x | | x | 13 |
| Children or dependants in the household | | | x | | | | x | x | x | | x | | | | | x | | | | | 6 |
| Single | x | x | | | x | x | | | | | | | | | | | | | x | | 5 |
| Single parent (widowed or divorced) | | | | | | | | | x | | | | | | | x | | | | | 2 |
| Couple with two client records | | | | | | | | | | | | | | x | x | | | | | | 2 |
| Retired or at retirement | | | | | | | | | | | | | | | | | | x | x | x | 3 |
| Self-employed or company owner | | | | | | x | | | | x | x | x | | | | | | | | | 4 |
| Part-time | | | x | | x | | | x | x | | | | | x | | x | x | | x | | 8 |
| Career change or re-entry | | x | | | | | | x | | | | | | | | | | | | | 2 |
| Cross-border or expat, mandate in EUR or USD | | x | | x | | | | | | | | | | | | | | | | | 2 |
| Property purchase (equity test) | | | x | x | | | | | | | | | | x | | | | | | | 3 |
| Mortgage amortisation | | | | | | | | | | | x | | x | | | | | | | | 2 |
| Annuity or lump sum | | | | | | | | | | | | | | | x | | | x | x | | 3 |
| Säule 3a question | x | x | | | | x | | | | | | | x | x | | | | x | | | 6 |
| Children's education goal | | | x | | | | x | | x | | x | | | | | x | | | | | 5 |
| Inheritance, advance directive, will | | | | x | | | | | x | | | | | | | | x | | x | x | 5 |
| Divorce, widowhood or another life event | | | | | | | | x | x | | | | | | x | x | | | | | 4 |
| Business succession or concentration in a firm | | | | x | | | | | | x | | x | | | | | | | | | 3 |
| lbs sheet with a single gap (earning power only) | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| Partner stated to lbs (age, income, human capital, own positions) | | | x | x | | | x | x | | x | x | x | x | x | x | | x | x | | x | 13 |
| Required return above 0 levels the curve | x | | x | | x | | x | | | | | | | x | | | x | x | x | | 8 |
| Required return 0: the preset's level kept | | x | | x | | x | | x | x | | | | | | | x | | | | x | 7 |
| Currency, liquidity and role bounds kept from lbs | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| Required return out of reach: the curve set at what the bounds can earn | | | | | | | | | | x | x | x | x | | x | | | | | | 5 |
| Parameter set superseded (a chain) | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| pcp run on the Default Regime (pcp 1.2.0) | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| pcp run under a scenario of the Default Regime | x | | | x | | | | | | | x | | x | | | | x | x | x | x | 8 |
| Scenario: deferral | x | | | x | | | | | | | | | | | | | | | | | 2 |
| Scenario: stagflation | | | | | | | | | | | x | | x | | | | | | | | 2 |
| Scenario: depression | | | | | | | | | | | | | | | | | x | x | | | 2 |
| Scenario: hyperinflation | | | | | | | | | | | | | | | | | | | x | x | 2 |
| A failed pcp run on record | | | | x | | | | x | | x | | | | x | | | x | | | | 5 |
| MiniMind answer from the notes (mixed) | | | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 18 |
| MiniMind general assessment, marked | x | x | | | | | | x | x | x | x | | | | | | | | | | 6 |
| MiniMind refusal, then a rephrased follow-up | | | | | | | | | | | | | x | | | | | | x | x | 3 |
| Refused question asked again and answered (MiniMind 1.2.0) | | | | | | | | | | | | | x | | | | | | x | x | 3 |
| Multi-turn thread | | | | x | | | | | | | | | x | | | | | | x | x | 4 |
| Curator answers in a thread | | | x | | | | x | | | | x | x | | | | | | | x | x | 6 |
| Thread closed (by the client or the curator) | | | | | | | | | x | | | | | | | | | | | x | 2 |
| Report | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| A second report, on the refreshed sheet and allocation | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | 20 |
| Update after a change | x | | | x | | | | x | x | | | | | | | x | x | | | | 6 |
| Approval: approved | x | | | | | | | x | | | | | | | x | x | x | x | | | 6 |
| Approval: revision sent | | x | | | | | | | | | | | | | | | x | | | | 2 |
| Approval: awaiting the curator | | | | | | | | | | | | | | | | | | | x | | 1 |
| Approval: withdrawn by the client | | | | | | | | | | x | | | | | | | | | | | 1 |

Every capability is shown at least twice, with two exceptions by design: exactly one approval is left awaiting
the curator (as asked), and one request withdrawn by the client (an extra, so the withdrawn state is on the
Approvals page too).

The human capital differs visibly across the set: E from 0.77 (Corinne; 0.66 before her update) and 0.78 (Esther)
to 1.00, N from 0.31 (Yasmin) and 0.37 (Anita) to 0.98, H from 0.50 (Elio, Franziska) to 1.00 (Simon, Anita,
Yasmin). Risk profiles run from 0.09 (Esther) to 0.53 (Simon).

## Where the set shows the suite's current limits

* **lbs calls a required return feasible whenever its search finds one below its ceiling**, however high. Five
  goals ask more than the household's bounds can earn: Elio's reserve 16.18 % in 1.25 years, Michele's
  amortisation 12.51 %, Tanja's private wealth 7.36 %, Reto's 6.30 % and Claudia's 5.28 %. The curator probes pcp
  with the curve lbs asks for, reads what the allocation within the household's bounds is expected to earn under
  the Default Regime (weighted by the Regime's state blend), and where the required return lies more than one point
  above it, sets the curve at that level (rounded down to 0.1 point) and says so in the parameter set's note: the gap
  is for the horizon, the saving or the goal's size, not for the allocation. Yasmin's 5.21 % against about 4.7 % is
  within the point and follows lbs.
* **The mandate presets hold every role** (v2, C-29) and validate against the Default Regime as they stand and with
  every role floor at 5, 10 and 15 %, so no universe had to be extended this time; pcp 1.2.0's joint feasibility
  check refused none of the 20 mandates, and every run succeeded at the first attempt.
* **The report takes the client's latest succeeded pcp run**, whatever its Regime: a report asked right after a
  scenario run would rest on the scenario's allocation. The build runs the scenario first and the Default Regime
  last.
* **MiniMind answers the questions it refused in the first build** (care for a parent, incapacity, inheritance);
  the refusals and the rephrased turns stay in the threads. A closed thread takes no message, so Peter asked in a
  new one.
* **Regula's first revision stays a copy on record**; the second, sent as a revision with the curator's note, is
  the one that differs.
* **The plan page's decision history names fields and roles by their keys** ("label", "time_basis", "health",
  "61,000 CHF, protection"), in English number format, on a German page; the migrated decisions carry the
  prototype's English reasoning.
* **The failed pcp runs** (Lukas 2, Anita 1, Tanja 4, Yasmin 1, Regula 9) are the first build's attempts that did
  not converge (SLSQP in pcp 1.1.0's fast mode, with the house's policy bounds against the household's). They stay
  in the history, as do the superseded parameter sets. For 18 clients the fix round finalised two sets with the
  same mandate: the first named the Regime by its id in the note, which the cockpit's set history shows as text;
  the current one names it by its optimism level.
