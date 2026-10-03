r"""Build the eigentliCH demonstration set: 20 clients showing the whole suite (owner, 29.09.2026).

Re-runnable and idempotent: every step compares what the store holds with what the use case states and writes
only the difference. Every write goes through the consumer app's API (answers naming their content version,
plan changes under a decision, a stated fact restated through ``PUT .../facts/{key}`` since EIG-54), the
store's documented function ``erase_client``, or the cockpit's curator routes (parameter sets, pcp runs,
curator answers, approvals). No row is edited directly and no code of the app, the engines or the cockpit is
changed.

    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py select              # the 20 and why
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py erase [--apply]     # everyone else, one at a time
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py enrich [--only simon,miriam]
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py partners            # partners and saving shares (EIG-53, 59)
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py basis               # today's or future francs, indexed saving (EIG-60, 61)
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py earning             # lbsim's earning-power answers (EIG-65)
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py mandates [--refresh]  # lbs, parameter set, pcp runs
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py outlook [--refresh]   # lbsim's findings, paths and plan (EIG-66)
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py threads | curate | reports [--refresh] | updates | approvals
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py revision            # the revision that was a copy (Regula)
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py check [--plans]     # --plans: wait until every plan is there
    ..\.venv\Scripts\python -X utf8 dev\build_use_cases.py all                 # enrich to check, in order

The lbsim refresh (29.09.2026), in order: ``earning``, ``mandates --refresh`` (lbs 1.4.0 makes new sheets, and
lbsim runs by itself on each new sheet), ``outlook``, ``reports --refresh``, ``check`` (``check --plans`` waits for
the plan calculations, about 50 minutes each on three workers).

Needs the app (8017), lbs (8013), lbsim (8014), chatbot (8016), report (8015), pcp (8007), fmre (8006), aggregation (8004)
and a cockpit serving its curator routes (``USE_CASES_COCKPIT``, default http://127.0.0.1:8098; start it with
``set COCKPIT_PORT=8098 && ..\Macro\.venv\Scripts\python -X utf8 -m cockpit serve`` in ``Engines\cockpit``).
The erasure refuses to run without the backup ``USE_CASES_BACKUP``. Reports go to ``dev/reports/``.

The catalogue of the 20 is ``docs/USE_CASES.md``.

Data conventions (the ``CLIENTS`` list below): every client is an existing record kept from the migration and
enriched, fictional but plausible Swiss figures in German. ``P(...)`` is a plan position, ``G(...)`` a goal;
``match`` lists labels or names an existing row may carry. Goals are written in the order given, after the
migrated ones: lbs takes the first active goal with an amount and a date that is not a retirement goal as the
mandate goal, so the goal that carries the mandate comes first among the new ones (or is the migrated goal it
enriches). ``hc`` holds the human-capital answers asked in both questionnaires; ``chain`` what the curator does
and what the client asks. Model-derived research output. Not investment advice.
"""

from __future__ import annotations

from typing import Any, Optional


def P(role: str, cap: str, label: str, mag: Optional[float] = None, *, unit: Optional[str] = None,
      kind: Optional[str] = None, liq: Optional[str] = None, vessel: Optional[str] = None, match: tuple = (),
      desc: Optional[str] = None, time: Optional[str] = None, owner: Optional[str] = None) -> dict[str, Any]:
    if mag is not None and unit is None:
        unit = "chf" if kind else "chf_per_year"
    return {"role": role, "capital_type": cap, "label": label, "magnitude": mag, "magnitude_unit": unit,
            "stock_kind": kind, "liquidity": liq, "vessel": vessel, "match": tuple(match) + (label,),
            "description": desc, "time_basis": time, "owner": owner}


def G(name: str, amount: Optional[float], date: Optional[str], *, match: tuple = (), template: Optional[str] = None,
      occupancy: Optional[str] = None, funded: tuple = (), kind: str = "other", why: Optional[str] = None) -> dict[str, Any]:
    """``kind`` is what the app's name rule must read (checked by the build): property, retirement or other."""
    return {"name": name, "target_amount": amount, "target_date": date, "match": tuple(match) + (name,),
            "template": template, "occupancy": occupancy, "funded": tuple(funded), "kind": kind, "why": why}


CASH, SEC, PK, P3A = "Bargeld und Kontoguthaben", "Wertschriften", "Pensionskasse", "Säule 3a"
TAX = "Offene Steuern 2026"

CLIENTS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ 1
    dict(
        key="simon", name="Simon N.", id="6ad65af4bcd54af8939753e4e9d90857",
        why="28, ledig, Thurgau: der junge Angestellte mit Sparplan und dem ersten grossen Weiterbildungsentscheid.",
        household=dict(adults=["Simon N."], dependants=[]),
        onb=dict(employment_position="Angestellt, Treuhand Thurgau AG, Frauenfeld", employment_magnitude=84000,
                 employment_time_basis=42, matrimonial_regime=None, self_employed_form="nicht selbständig",
                 pillar2_voluntary="nein", annual_contribution=24000),
        hc=dict(qualification_highest="Höhere Berufsausbildung", qualification_year=2022, years_in_field=9,
                kader="Keine Führungsfunktion", network_people=6, network_reach="in der Branche", hours_learning=8,
                hours_network=2),
        health=1, rest_hours="20–30", mandates=1,
        education_recent="Eidg. Diplom Experte/Expertin in Rechnungslegung und Controlling, berufsbegleitend ab Oktober 2026 (zwei Jahre, veb.ch)",
        education_hours="5–10", education_budget=14000,
        intake=dict(
            birth_year=1998, canton="Thurgau", municipality="Frauenfeld", civil_status="ledig",
            household="Ich allein, Mietwohnung in Frauenfeld", nationality="Schweiz",
            permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Treuhand Thurgau AG, Frauenfeld",
            income_gross=84000, income_variable=3000, pensum=100, work_until_age=65, thirteenth_salary="ja",
            income_other="Kassier des Unihockeyclubs Frauenfeld, Spesenentschädigung 1 200 pro Jahr",
            ahv_years_missing=0, ahv_ik_requested="nein", care_credit_years=0,
            pillar2_fund="Pensionskasse Thurgau", pillar2=36000, pillar2_obligatory_part=31000, pillar2_buyin=18000,
            pillar2_voluntary="nein", pillar2_conversion_rate=5.6, pillar2_early_retirement_age=58,
            pillar2_survivor_cover=20000, pillar2_disability_cover=34000,
            pillar3a_total=29000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=21000,
            other_debt="Keine Kredite, kein Leasing. Offen sind die Steuern 2026 (etwa 9 800).",
            cash=38000, securities=72000, crypto_value=3500, inheritance_expected="nichts Bestimmtes",
            spend_now=46000, spend_later=62000, tax_paid=9800,
            one_off_planned="Diplomstudium 2026 bis 2028 (etwa 28 000), ein Sprachaufenthalt später vielleicht",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Telmed, Franchise 2 500",
            insurance_other="Privathaftpflicht, Hausrat",
            legal_will="nein", legal_cohabitation="nicht zutreffend", legal_power_of_attorney="nein",
            legal_patient_decree="nein", legal_beneficiary="weiss ich nicht",
            max_loss_pct=30, expected_return_pct=5, crisis_behaviour="nachgekauft",
            investment_experience="ETF-Sparplan seit 2019, drei Indexfonds, etwas Bitcoin", liquidity_reserve_months=6,
            esg_exclusions=["Waffen", "Tabak"], esg_minimum="wenn möglich",
            esg_why="Keine Waffen und kein Tabak, sonst möglichst günstig und breit.",
            goals="Mit 48 finanziell unabhängig sein, vorher das eidgenössische Diplom machen und im Treuhandbüro aufsteigen.",
            goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=24, tax_wealth=350, tax_deductions_used="Säule 3a, Berufskosten, Weiterbildung",
            tax_church="nein",
            planned_events="Diplomprüfung 2028, danach Teamleitung Rechnungswesen",
            investments_detail="Drei Indexfonds (Schweiz, Welt, Schwellenländer) über einen monatlichen Sparplan",
            banks="Thurgauer Kantonalbank, eine Neobank für den Sparplan, 3a bei einer App-Stiftung",
            advisors="niemand", documents_where="Ordner zu Hause und ein Cloud-Ordner",
            main_question="Lohnt sich das Diplom finanziell, und schaffe ich die Unabhängigkeit mit 48?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Treuhand Thurgau AG (100 %)", 84000, match=("angestellt",), time="42 Std./Woche"),
            P("growth", "human", "Weiterbildung: eidg. Diplom Rechnungslegung und Controlling (ab Oktober 2026)",
              desc="Zwei Jahre berufsbegleitend, rund 8 Stunden pro Woche", time="8 Std./Woche"),
            P("stabilisation", "human", "Kassier Unihockeyclub Frauenfeld", 1200, time="2 Std./Woche"),
            P("protection", "human", "Gesundheit und Sport: Unihockey zweimal pro Woche", time="25 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 38000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 72000, kind="asset", liq="immediate", vessel="free",
              desc="ETF-Sparplan, drei Indexfonds"),
            P("growth", "financial", "Kryptowährungen (Bitcoin)", 3500, kind="asset", liq="within_months", vessel="free"),
            P("protection", "financial", PK, 36000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 29000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 9800, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 62000, "2063-12-31", kind="retirement", funded=(PK, P3A)),
            G("Finanzielle Unabhängigkeit 2048", 1100000, "2048-12-31", template="financial_independence",
              funded=(CASH, SEC)),
            G("Weiterbildung: eidg. Diplom Rechnungslegung und Controlling bis 2028 (Ziel: +15 000 CHF Lohn, Netzwerk veb.ch)",
              28000, "2028-06-30", template="education", funded=(CASH,),
              why="Das Diplom öffnet die Teamleitung; der Arbeitgeber übernimmt vielleicht einen Teil."),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario="deferral",
                   threads=[
                       dict(key="diplom-3a", q="Ich beginne im Oktober das eidgenössische Diplom in Rechnungslegung und Controlling, es kostet rund 28 000 Franken. Soll ich die Kosten aus dem Ersparten zahlen oder lieber weiter voll in die Säule 3a einzahlen? Mein Arbeitgeber übernimmt vielleicht einen Teil.",
                            approval="approved"),
                       dict(key="diplom-lohn", q="Wie viel mehr Lohn ist nach dem Diplom realistisch, und wie finde ich heraus, ob sich die Investition über mein ganzes Berufsleben lohnt?"),
                   ],
                   update=dict(note="Nach dem ersten Modul zum Teamleiter Rechnungswesen befördert",
                               positions={"Lohn Treuhand Thurgau AG (100 %)": dict(magnitude=92000, label="Lohn Treuhand Thurgau AG, Teamleiter (100 %)")},
                               onb=dict(employment_magnitude=92000),
                               intake=dict(income_gross=92000, kader="Oberes oder mittleres Kader"),
                               hc=dict(kader="Oberes oder mittleres Kader"))),
    ),
    # ------------------------------------------------------------------ 2
    dict(
        key="miriam", name="Miriam S.", id="68dfcb41e2d6434e891d69ce004e3ee5",
        why="26, Doktorandin in Basel, Deutsche mit B-Bewilligung: der Expat-Fall in EUR und der Wechsel von der Uni in die Industrie.",
        household=dict(adults=["Miriam S."], dependants=[]),
        onb=dict(employment_position="Doktorandin, Departement Chemie, Universität Basel", employment_magnitude=54000,
                 employment_time_basis=50, self_employed_form="nicht selbständig", pillar2_voluntary="nein",
                 annual_contribution=7200),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=2023, years_in_field=3,
                kader="Keine Führungsfunktion", network_people=5, network_reach="in der Branche", hours_learning=6,
                hours_network=2),
        health=0.85, rest_hours="5–10", mandates=0,
        education_recent="Zertifikat Projektmanagement IPMA Level D und GMP-Grundkurs, geplant 2027 vor dem Wechsel in die Industrie",
        education_hours="3–5", education_budget=3500,
        intake=dict(
            birth_year=2000, canton="Basel-Stadt", municipality="Basel", civil_status="ledig",
            household="Ich allein, WG-Zimmer in Basel", nationality="Deutschland", permit="B (Aufenthalt)",
            years_in_switzerland=2021, plans_to_leave="vielleicht später",
            employment="in Ausbildung", self_employed_form="nicht selbständig", employer="Universität Basel (SNF-Projekt)",
            income_gross=54000, pensum=100, work_until_age=67, thirteenth_salary="kein 13. Monatslohn",
            ahv_years_missing=0, ahv_years_abroad=0, ahv_ik_requested="nein",
            pillar2_fund="Pensionskasse Basel-Stadt", pillar2=9000, pillar2_obligatory_part=9000, pillar2_voluntary="nein",
            pillar3a_total=4000, pillar3a_accounts=1, pillar3a_contribution=2400, pillar3a_in_securities=4000,
            other_debt="Keine. Offen sind die Steuern 2026 (etwa 4 200).",
            cash=16000, securities=6000, inheritance_expected="nichts Bestimmtes",
            spend_now=38000, spend_later=55000, tax_paid=4200,
            one_off_planned="Umzug nach der Promotion 2029, vielleicht nach Deutschland oder in die Region Basel",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell, Franchise 1 500",
            legal_will="nein", legal_cohabitation="nicht zutreffend", legal_power_of_attorney="nein",
            legal_patient_decree="nein", legal_beneficiary="weiss ich nicht",
            max_loss_pct=20, expected_return_pct=4, crisis_behaviour="ich war nicht investiert",
            investment_experience="Ein ETF-Sparplan in Euro seit 2024, sonst nichts", liquidity_reserve_months=4,
            esg_exclusions=["Waffen", "Fossile Energie", "Kinderarbeit in der Lieferkette"], esg_minimum="mehrheitlich",
            esg_why="Ich arbeite an grüner Chemie; mein Geld soll nicht das Gegenteil finanzieren.",
            goals="Promotion 2029 abschliessen, danach in die Industrie wechseln, vielleicht zurück nach Deutschland. Eine Reserve für den Übergang.",
            goal_confidence="70 % — ich kann nachjustieren", plan_until_age=90,
            tax_marginal_rate=18, tax_church="nein",
            planned_events="Promotion 2029, Stellenwechsel in die Industrie, möglicher Wegzug nach Deutschland",
            investments_detail="Ein Welt-ETF in Euro, monatlich 150 Euro",
            banks="Basler Kantonalbank, eine Neobank in Deutschland, 3a bei einer App-Stiftung",
            advisors="niemand", documents_where="Laptop und ein Ordner in der WG",
            main_question="Was passiert mit meiner Vorsorge, wenn ich zurückgehe, und in welcher Währung spare ich?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Doktorandin Universität Basel", 54000, match=("angestellt",), time="50 Std./Woche"),
            P("growth", "human", "Promotion in Chemie (Abschluss 2029)", time="45 Std./Woche im Labor"),
            P("growth", "human", "Weiterbildung: Projektmanagement IPMA D und GMP (geplant 2027)", time="3 Std./Woche"),
            P("protection", "human", "Berufliches Netzwerk: Swiss Chemical Society, Alumni", time="2 Std./Woche"),
            P("stabilisation", "financial", CASH, 16000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 6000, kind="asset", liq="immediate", vessel="free", desc="Welt-ETF in Euro"),
            P("protection", "financial", PK, 9000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 4000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 4200, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 65000, "2065-12-31", kind="retirement", funded=(PK, P3A)),
            G("Nach der Promotion 2030 in die Industrie", 30000, "2029-12-31", template="courage_money", funded=(CASH, SEC),
              why="Eine Reserve für Umzug, Übergang und eine allfällige Lücke zwischen Uni und erster Stelle."),
            G("Weiterbildung: Projektmanagement IPMA D und GMP-Kurs 2027 (Ziel: Einstieg Industrie mit 95 000 CHF, Netzwerk SCS)",
              6500, "2027-11-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="sustainable-balanced", currency="EUR", scenario=None,
                   currency_bounds={"EUR": (50, 100)},
                   threads=[
                       dict(key="wegzug", q="Ich bin Deutsche mit B-Bewilligung. Was passiert mit meinem Pensionskassengeld und meiner Säule 3a, wenn ich nach der Promotion nach Deutschland zurückgehe?",
                            approval="revision_sent",
                            revision="Eine Präzisierung zur Antwort von MiniMind: Beim Wegzug in einen EU- oder EFTA-Staat bleibt der obligatorische Teil Ihres Pensionskassenguthabens in der Schweiz, auf einem Freizügigkeitskonto, solange Sie in Deutschland obligatorisch rentenversichert sind. Bar beziehen können Sie nur den überobligatorischen Teil. Die Säule 3a können Sie beim definitiven Wegzug beziehen; sie wird an der Quelle besteuert, und je nach Kanton der Stiftung ist das deutlich günstiger. Bei Ihnen ist fast alles obligatorisch, also bleibt das Geld bis 60 auf dem Freizügigkeitskonto, und Sie wählen dafür am besten eine Stiftung mit Wertschriftenlösung. Nicolas"),
                       dict(key="waehrung", q="Soll ich mein Erspartes in Euro oder in Franken anlegen, wenn ich noch nicht weiss, wo ich in fünf Jahren lebe?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 3
    dict(
        key="fabienne", name="Fabienne G.", id="3da6b118ace046f0b505cd2004f319c4",
        why="33, verheiratet, zwei kleine Kinder, Bern: die Familie in Teilzeit mit dem ersten Wohneigentum.",
        household=dict(adults=["Fabienne G.", "Marco G."], dependants=["Lina (2021)", "Noah (2023)"]),
        onb=dict(employment_position="Primarlehrerin, Schule Köniz (60 %)", employment_magnitude=56000,
                 employment_time_basis=30, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=18000),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=2016, years_in_field=10,
                kader="Keine Führungsfunktion", network_people=8, network_reach="im eigenen Unternehmen",
                hours_learning=2, hours_network=1),
        health=0.85, rest_hours="5–10", mandates=0,
        education_recent="CAS Integrative Förderung an der PH Bern ab Februar 2027, danach vielleicht MAS Schulische Heilpädagogik",
        education_hours="1–2", education_budget=5000,
        intake=dict(
            birth_year=1993, canton="Bern", municipality="Köniz", civil_status="verheiratet", married_since=2019,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Marco (Polymechaniker, 100 %), Lina und Noah", children_birth_years="2021, 2023",
            child_costs=24000, nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Schule Köniz (Kanton Bern)",
            income_gross=56000, pensum=60, work_until_age=64, thirteenth_salary="ja",
            income_other="Marco verdient 92 000 brutto (100 %), sein Lohn ist nicht Teil meines Bogens",
            ahv_years_missing=0, ahv_ik_requested="nein", care_credit_years=5,
            pillar2_fund="Bernische Lehrerversicherungskasse (BLVK)", pillar2=61000, pillar2_obligatory_part=38000,
            pillar2_buyin=45000, pillar2_voluntary="nein", pillar2_conversion_rate=5.2,
            pillar2_early_retirement_age=60, pillar2_survivor_cover=22000, pillar2_disability_cover=30000,
            pillar3a_total=22000, pillar3a_accounts=1, pillar3a_contribution=7258, pillar3a_in_securities=15000,
            other_debt="Autoleasing bis 2028 (Restschuld etwa 14 000); Steuern 2026 offen (etwa 11 500)",
            cash=48000, securities=22000, inheritance_expected="später vielleicht von den Eltern, nichts Bestimmtes",
            spend_now=96000, spend_later=78000, tax_paid=11500,
            one_off_planned="Wohnungskauf 2032, ein neues Auto 2028",
            insurance_life=250000, insurance_disability=24000, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Hausarztmodell, Kinder mit Franchise 0",
            insurance_other="Risikolebensversicherung für beide seit Lina auf der Welt ist",
            legal_will="nein", legal_marriage_contract="nein", legal_power_of_attorney="nein",
            legal_patient_decree="nein", legal_beneficiary="nein",
            max_loss_pct=15, expected_return_pct=3.5, crisis_behaviour="teilweise verkauft",
            investment_experience="Fondsparplan der Bank seit 2020; 2022 die Hälfte verkauft", liquidity_reserve_months=6,
            esg_exclusions=["Waffen", "Kinderarbeit in der Lieferkette"], esg_minimum="wenn möglich",
            esg_why="Unsere Kinder sollen nicht erben, was wir kaputt gemacht haben.",
            goals="2032 eine Wohnung in der Region Bern kaufen, eine Reserve für die Ausbildung der Kinder, mit 64 aufhören.",
            goal_occupancy="Ich wohne selbst darin", goal_confidence="90 % — es muss halten", plan_until_age=90,
            tax_marginal_rate=26, tax_wealth=280, tax_deductions_used="Säule 3a, Kinderbetreuung, Berufskosten",
            tax_church="ja",
            planned_events="CAS 2027, Pensum vielleicht auf 70 % ab 2029, Wohnungskauf 2032",
            investments_detail="Ein Strategiefonds der Bank (Ausgewogen)",
            banks="Berner Kantonalbank, 3a bei der Bank", advisors="der Kundenberater der Bank, selten",
            documents_where="Ordner im Büro zu Hause",
            main_question="Reicht unser Eigenkapital für 2032, und wie teilen wir Sparen, Kinder und Teilzeit auf?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Primarlehrerin Schule Köniz (60 %)", 56000, match=("angestellt",), time="30 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Integrative Förderung (ab 2027)", time="2 Std./Woche"),
            P("protection", "human", "Familie und Erholung: zwei Kleinkinder, wenig freie Zeit", time="7 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 48000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 22000, kind="asset", liq="within_months", vessel="free",
              desc="Strategiefonds Ausgewogen"),
            P("protection", "financial", PK, 61000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 22000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Autoleasing (Restschuld)", 14000, kind="liability", liq="within_years", vessel="free"),
            P("stabilisation", "financial", TAX, 11500, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 84000, "2058-12-31", kind="retirement", funded=(PK, P3A)),
            G("Wohneigentum 2032 850000", 850000, "2032-12-31", template="home_ownership",
              occupancy="owner_occupied_primary", kind="property", funded=(CASH, SEC, P3A, PK)),
            G("Ausbildungsreserve für Lina und Noah bis 2039", 60000, "2039-08-31", funded=(SEC,)),
            G("Weiterbildung: CAS Integrative Förderung 2027–2028 (Ziel: Stufe Heilpädagogik, +9 000 CHF bei gleichem Pensum)",
              9800, "2028-07-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="eigenmittel", q="Wir möchten 2032 eine Wohnung für 850 000 Franken kaufen. Wie viel Eigenkapital brauchen wir, und dürfen wir dafür Geld aus der Pensionskasse und der Säule 3a nehmen?"),
                       dict(key="teilzeit", q="Ich arbeite 60 %. Wie stark schadet das meiner Rente, und lohnt es sich, nach dem CAS auf 70 % zu erhöhen?",
                            curator="Ergänzend zur Antwort von MiniMind: Bei Ihrer Kasse (BLVK) wird der Koordinationsabzug dem Pensum angepasst, darum trifft Sie die Teilzeit weniger als bei vielen anderen Kassen. Der grössere Hebel ist der Lohn: Mit der Stufe Heilpädagogik steigt er bei gleichem Pensum um rund 9 000 Franken, und das wirkt auf Lohn, AHV und Pensionskasse zugleich. Eine Erhöhung auf 70 % würde ich erst nach dem CAS prüfen, wenn Noah im Kindergarten ist. Wir können das im nächsten Bericht durchrechnen. Nicolas"),
                   ]),
    ),
    # ------------------------------------------------------------------ 4
    dict(
        key="lukas", name="Lukas M.", id="92977053c83545db8df155b3f0b48338",
        why="38, Zug, Konkubinat, Schweizer und US-Bürger mit Aktienlohn in USD: hohes Einkommen, der USD-Fall und der Kauf zu zweit ohne Trauschein.",
        household=dict(adults=["Lukas M.", "Sarah K."], dependants=[]),
        onb=dict(employment_position="Head of Product, US-Softwarefirma, Büro Zug", employment_magnitude=168000,
                 employment_time_basis=47, self_employed_form="nicht selbständig", pillar2_voluntary="ja",
                 annual_contribution=40000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=2012, years_in_field=13,
                kader="Oberes oder mittleres Kader", network_people=25, network_reach="über die Branche hinaus",
                hours_learning=3, hours_network=5),
        health=0.85, rest_hours="10–20", mandates=1,
        education_recent="Executive MBA (HSG oder IMD) ab 2027 geplant, berufsbegleitend",
        education_hours="3–5", education_budget=30000,
        intake=dict(
            birth_year=1988, canton="Zug", municipality="Baar", civil_status="ledig, mit Partner",
            household="Meine Partnerin Sarah (Ärztin, 80 %), keine Kinder", nationality="Schweiz und USA",
            permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="US-Softwarefirma, Niederlassung Zug",
            income_gross=168000, income_variable=45000, pensum=100, work_until_age=62, thirteenth_salary="nein",
            income_other="Mitarbeiteraktien (RSU) in USD, jährlich rund 45 000 CHF, vierteljährlich zugeteilt",
            ahv_years_missing=0, ahv_ik_requested="ja",
            pillar2_fund="Sammelstiftung der Firma (Kaderplan 1e)", pillar2=225000, pillar2_obligatory_part=110000,
            pillar2_buyin=160000, pillar2_voluntary="ja", pillar2_conversion_rate=5.0, pillar2_early_retirement_age=58,
            pillar2_survivor_cover=60000, pillar2_disability_cover=110000,
            pillar3a_total=68000, pillar3a_accounts=3, pillar3a_contribution=7258, pillar3a_in_securities=68000,
            other_debt="Keine. Steuern 2026 in der Schweiz und die US-Steuererklärung offen (etwa 38 000)",
            cash=85000, securities=195000, inheritance_expected="nichts Bestimmtes",
            spend_now=95000, spend_later=95000, tax_paid=38000, one_off_planned="Wohnungskauf 2030, EMBA 2027 bis 2029",
            insurance_life=500000, insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Standard, Franchise 2 500",
            legal_will="nein", legal_cohabitation="nein", legal_power_of_attorney="nein", legal_patient_decree="nein",
            legal_beneficiary="nein",
            max_loss_pct=35, expected_return_pct=6, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Einzeltitel und ETF bei einem US-Broker seit 2012, Mitarbeiteraktien", liquidity_reserve_months=6,
            esg_minimum="keine Vorgabe", esg_why="Ich will keine Vorgabe; Rendite und Streuung zählen.",
            goals="2030 mit Sarah eine Wohnung im Kanton Zug kaufen, das EMBA machen, mit 62 frei entscheiden können.",
            goal_occupancy="Ich wohne selbst darin", goal_confidence="80 %", plan_until_age=92,
            tax_marginal_rate=33, tax_wealth=2100, tax_deductions_used="Säule 3a, Pensionskasseneinkauf 2025",
            tax_church="nein",
            planned_events="EMBA 2027 bis 2029, Wohnungskauf 2030, vielleicht Heirat",
            investments_detail="US-Broker: ETF auf den S&P 500 und Weltaktien, rund 40 000 in Mitarbeiteraktien, alles in USD",
            banks="Zuger Kantonalbank, ein US-Broker, 3a bei drei Stiftungen", advisors="ein Steuerberater für die US-Steuer",
            documents_where="Cloud-Ordner, Kopien beim Steuerberater",
            main_question="Wie viel Dollar-Risiko trage ich, und was fehlt uns ohne Trauschein beim Kauf?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Head of Product (100 %)", 168000, match=("angestellt",), time="47 Std./Woche"),
            P("growth", "human", "Weiterbildung: Executive MBA (geplant 2027–2029)", time="4 Std./Woche"),
            P("stabilisation", "human", "Beirat eines Zuger Start-ups", 6000, time="1 Std./Woche"),
            P("protection", "human", "Berufliches Netzwerk: Produkt-Community Zürich und San Francisco", time="5 Std./Woche"),
            P("stabilisation", "financial", CASH, 85000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 195000, kind="asset", liq="immediate", vessel="free",
              desc="US-Broker, ETF in USD"),
            P("growth", "financial", "Mitarbeiteraktien (RSU, USD)", 62000, kind="asset", liq="within_months", vessel="free"),
            P("protection", "financial", PK, 225000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 68000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Offene Steuern 2026 (Schweiz und USA)", 38000, kind="liability",
              liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 105000, "2053-12-31", kind="retirement", funded=(PK, P3A)),
            G("Eigentum kaufen 2030 1.8 Mio", 1800000, "2030-12-31", template="home_ownership",
              occupancy="owner_occupied_primary", kind="property",
              funded=(CASH, SEC, "Mitarbeiteraktien (RSU, USD)", P3A, PK)),
            G("Weiterbildung: Executive MBA 2027–2029 (Ziel: Rolle VP Product, +40 000 CHF, internationales Netzwerk)",
              85000, "2029-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="growth-global", currency="USD", scenario="deferral",
                   currency_bounds={"USD": (30, 100), "CHF": (20, 100)},
                   threads=[
                       dict(key="konkubinat", q="Meine Partnerin und ich sind nicht verheiratet und wollen 2030 gemeinsam eine Wohnung kaufen. Was fehlt uns rechtlich, wenn einem von uns etwas passiert?",
                            followup="Danke. Reicht ein Konkubinatsvertrag, oder brauchen wir zusätzlich ein Testament und eine Begünstigung bei der Pensionskasse?"),
                       dict(key="rsu", q="Ein Teil meines Lohns kommt als Aktien meines Arbeitgebers in US-Dollar. Wie viel Klumpenrisiko ist das, und soll ich die Aktien laufend verkaufen?"),
                   ],
                   update=dict(note="Aktienzuteilung vom September und Bonus gutgeschrieben",
                               positions={"Mitarbeiteraktien (RSU, USD)": dict(magnitude=48000),
                                          SEC: dict(magnitude=231000)},
                               intake=dict(securities=231000))),
    ),
    # ------------------------------------------------------------------ 5
    dict(
        key="noemi", name="Noemi B.", id="5da43ed909f64d9ba7cec20ccb30294f",
        why="39, ledig, Schwyz, zwei Teilpensen als Physiotherapeutin: auf dem Weg in die Selbständigkeit, mit Rückenproblemen.",
        household=dict(adults=["Noemi B."], dependants=[]),
        onb=dict(employment_position="Physiotherapeutin, Praxis Lachen (50 %) und Klinik Wangen (40 %)",
                 employment_magnitude=71000, employment_time_basis=46, self_employed_form="nicht selbständig",
                 pillar2_voluntary="nein", annual_contribution=15000),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=2011, years_in_field=15,
                kader="Keine Führungsfunktion", network_people=12, network_reach="in der Branche", hours_learning=4,
                hours_network=2),
        health=0.7, rest_hours="10–20", mandates=0,
        education_recent="MAS Sportphysiotherapie (ZHAW) ab 2027, Voraussetzung für die spezialisierte eigene Praxis",
        education_hours="3–5", education_budget=8000,
        intake=dict(
            birth_year=1987, canton="Schwyz", municipality="Lachen", civil_status="ledig",
            household="Ich allein, Mietwohnung in Lachen", nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger",
            plans_to_leave="nein", employment="angestellt", self_employed_form="nicht selbständig",
            employer="Physiotherapie Lachen und Klinik Wangen", income_gross=71000, pensum=90, work_until_age=64,
            thirteenth_salary="ja", income_other="Kurse in Rückentraining, etwa 3 000 pro Jahr",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="zwei Kassen: Sammelstiftung der Praxis und Pensionskasse der Klinik", pillar2=58000,
            pillar2_obligatory_part=50000, pillar2_buyin=60000, pillar2_voluntary="nein", pillar2_conversion_rate=5.4,
            pillar2_survivor_cover=18000, pillar2_disability_cover=28000,
            pillar3a_total=19000, pillar3a_accounts=1, pillar3a_contribution=7258, pillar3a_in_securities=10000,
            other_debt="Keine. Steuern 2026 offen (etwa 7 400)", cash=38000, securities=24000,
            inheritance_expected="nichts Bestimmtes", spend_now=52000, spend_later=62000, tax_paid=7400,
            one_off_planned="MAS 2027 bis 2029, Praxiseinrichtung 2031 (etwa 250 000, der Rest über einen Bankkredit)",
            insurance_disability=0, insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell, Franchise 1 000",
            insurance_other="Keine private Erwerbsunfähigkeitsversicherung; für die Selbständigkeit fehlt sie",
            legal_will="nein", legal_cohabitation="nicht zutreffend", legal_power_of_attorney="nein",
            legal_patient_decree="ja", legal_beneficiary="weiss ich nicht",
            max_loss_pct=15, expected_return_pct=3, crisis_behaviour="ich war nicht investiert",
            investment_experience="Ein nachhaltiger Fonds seit 2023", liquidity_reserve_months=8,
            esg_exclusions=["Waffen", "Tabak", "Tierversuche"], esg_minimum="mehrheitlich",
            esg_why="Gesundheit ist mein Beruf; Tabak und Waffen passen nicht dazu.",
            goals="2031 eine eigene Praxis mit Schwerpunkt Sport, vorher das MAS, und eine Reserve, falls der Rücken wieder streikt.",
            goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=22, tax_church="ja", tax_deductions_used="Säule 3a, Weiterbildung",
            planned_events="MAS 2027 bis 2029, Selbständigkeit 2031", business_succession="nicht zutreffend",
            investments_detail="Ein nachhaltiger Strategiefonds", banks="Schwyzer Kantonalbank",
            advisors="niemand", documents_where="Ordner zu Hause",
            main_question="Wie sichere ich mich als Selbständige ab, und reicht das Geld für die Praxis?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Physiotherapie, zwei Teilpensen (90 %)", 71000, match=("mehrere Anstellungen",),
              time="46 Std./Woche"),
            P("growth", "human", "Weiterbildung: MAS Sportphysiotherapie (ab 2027)", time="4 Std./Woche"),
            P("stabilisation", "human", "Kurse Rückentraining (Nebenerwerb)", 3000, time="2 Std./Woche"),
            P("protection", "human", "Gesundheit: wiederkehrende Rückenprobleme, Training zweimal pro Woche",
              time="15 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 38000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 24000, kind="asset", liq="within_months", vessel="free", desc="Nachhaltiger Strategiefonds"),
            P("protection", "financial", "Pensionskasse (zwei Arbeitgeber)", 58000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 19000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 7400, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 62000, "2052-12-31", kind="retirement",
              funded=("Pensionskasse (zwei Arbeitgeber)", P3A)),
            G("Eigene Physiotherapie-Praxis 2031 (Eigenmittel 110 000)", 110000, "2031-06-30",
              match=("Eigene Praxis 2031 250000",), template="own_business", funded=(CASH, SEC),
              why="Die Einrichtung kostet rund 250 000; die Bank verlangt etwa 110 000 Eigenmittel."),
            G("Gesundheitsreserve: drei Monate Ausfall ohne Einkommen überbrücken", 18000, "2027-06-30", funded=(CASH,)),
            G("Weiterbildung: MAS Sportphysiotherapie 2027–2029 (Ziel: Spezialisierung, höherer Tarif, Netzwerk Sportphysio)",
              24000, "2029-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="conservative-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="selbstaendig", q="Ich will 2031 eine eigene Praxis eröffnen. Was ändert sich bei AHV und Pensionskasse, wenn ich selbständig werde?"),
                       dict(key="ruecken", q="Ich habe immer wieder Rückenprobleme. Wie sichere ich mich als künftige Selbständige gegen einen längeren Ausfall ab, und was kostet das ungefähr?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 6
    dict(
        key="celine", name="Céline B.", id="2fa7457296804fd1855c6f57ffeeea59",
        why="36, ledig, Lausanne, selbständige Grafikdesignerin ohne Pensionskasse: die Einzelfirma auf dem Weg zum Atelier mit Angestellten.",
        household=dict(adults=["Céline B."], dependants=[]),
        onb=dict(employment_position="Selbständig, Atelier Céline B. (Einzelfirma), Lausanne", employment_magnitude=96000,
                 employment_time_basis=48, self_employed_form="einzelfirma", pillar2_voluntary="nein",
                 annual_contribution=12000),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=2013, years_in_field=12,
                kader="Keine Führungsfunktion", network_people=20, network_reach="über die Branche hinaus",
                hours_learning=3, hours_network=6),
        health=0.85, rest_hours="10–20", mandates=1,
        education_recent="CAS Brand Strategy (HEIG-VD) 2027, um grössere Mandate zu führen",
        education_hours="3–5", education_budget=9000,
        intake=dict(
            birth_year=1990, canton="Waadt", municipality="Lausanne", civil_status="ledig",
            household="Ich allein, Wohnung und Atelier in Lausanne", nationality="Schweiz",
            permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein", employment="selbständig",
            self_employed_form="Einzelfirma", employer="eigenes Atelier, Kundschaft in der Westschweiz",
            income_gross=96000, pensum=100, work_until_age=65, thirteenth_salary="kein 13. Monatslohn",
            company_value=60000, company_income=96000,
            income_other="Lehrauftrag an der ECAL, etwa 8 000 pro Jahr",
            ahv_years_missing=1, ahv_ik_requested="ja",
            pillar2_voluntary="nein", pillar3a_total=64000, pillar3a_accounts=3, pillar3a_contribution=19000,
            pillar3a_in_securities=40000,
            other_debt="Keine Kredite. Offen: Steuern und AHV-Beiträge 2026 (etwa 16 500)",
            cash=52000, securities=8000, gold_value=22000,
            inheritance_expected="nichts Bestimmtes", spend_now=60000, spend_later=62000, tax_paid=12500,
            one_off_planned="Gründung einer GmbH 2027 (Stammkapital 20 000), Einrichtung für zwei Arbeitsplätze",
            insurance_disability=36000, insurance_ktg="ja, privat", insurance_health_model="Telmed, Franchise 2 500",
            insurance_other="Berufshaftpflicht, Betriebsunterbruch",
            legal_will="nein", legal_cohabitation="nicht zutreffend", legal_power_of_attorney="nein",
            legal_patient_decree="nein", legal_beneficiary="nein",
            max_loss_pct=25, expected_return_pct=4, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="3a in Wertschriften seit 2018, sonst wenig", liquidity_reserve_months=5,
            esg_exclusions=["Waffen", "Fossile Energie", "Tabak", "Kinderarbeit in der Lieferkette"],
            esg_minimum="vollständig", esg_why="Ich gestalte für nachhaltige Marken; mein Geld soll dazu passen.",
            goals="Bis 2032 ein Atelier mit zwei Angestellten, eine GmbH, und eine eigene Vorsorge ohne Pensionskasse.",
            goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=28, tax_wealth=420, tax_deductions_used="grosse Säule 3a, Geschäftsaufwand",
            tax_church="nein",
            planned_events="GmbH 2027, erste Angestellte 2028, zweite 2030", business_succession="noch kein Thema",
            investments_detail="3a in einem nachhaltigen Aktienfonds, eine Siebdruck-Sammlung",
            banks="Banque Cantonale Vaudoise, 3a bei drei Stiftungen", advisors="eine Treuhänderin für die Buchhaltung",
            documents_where="Atelier, Treuhänderin",
            main_question="Wie baue ich als Selbständige Vorsorge auf, und lohnt sich die GmbH?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Einkommen Atelier Céline B. (Einzelfirma)", 96000, match=("selbständig",),
              time="48 Std./Woche"),
            P("growth", "human", "Aufbau des Ateliers: zwei Angestellte bis 2032", time="10 Std./Woche"),
            P("stabilisation", "human", "Lehrauftrag ECAL", 8000, time="3 Std./Woche"),
            P("protection", "human", "Berufliches Netzwerk: Swiss Graphic Design, Westschweizer Agenturen", time="6 Std./Woche"),
            P("stabilisation", "financial", CASH, 52000, kind="asset", liq="immediate"),
            P("stabilisation", "financial", "Sammlungen, Kunst und Fahrzeuge", 22000, kind="asset", liq="within_years",
              vessel="real_asset", desc="Siebdruck-Sammlung und ein Lieferwagen"),
            P("growth", "financial", SEC, 8000, kind="asset", liq="immediate", vessel="free"),
            P("protection", "financial", P3A, 64000, kind="asset", liq="illiquid", vessel="pillar_3a",
              desc="Grosse Säule 3a für Selbständige ohne Pensionskasse"),
            P("protection", "financial", "Pensionskasse: keine (selbständig, nicht BVG-versichert)", 0, kind="asset",
              liq="illiquid", vessel="pillar_2"),
            P("stabilisation", "financial", "Offene Steuern und AHV-Beiträge 2026", 16500, kind="liability",
              liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 62000, "2055-12-31", kind="retirement", funded=(P3A,)),
            G("Atelier mit zwei Angestellten bis 2032", 80000, "2032-06-30", template="own_business", funded=(CASH, SEC),
              why="Eine Reserve für sechs Monatslöhne und die Einrichtung von zwei Arbeitsplätzen."),
            G("Weiterbildung: CAS Brand Strategy 2027 (Ziel: Mandate ab 50 000 CHF, Netzwerk Westschweizer Agenturen)",
              9500, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="sustainable-balanced", currency="CHF", scenario=None,
                   threads=[
                       dict(key="3a-gmbh", q="Ich bin selbständig ohne Pensionskasse. Wie viel darf ich in die Säule 3a einzahlen, und lohnt sich der Wechsel in eine GmbH für meine Vorsorge?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 7
    dict(
        key="isabelle", name="Isabelle C.", id="78cb9ace7ee746e9ae5ca82abaee1994",
        why="43, Genf, Oberärztin mit zwei Kindern und 54 Stunden: sehr hohes Einkommen, Praxiseinstieg und der Wunsch, weniger zu arbeiten.",
        household=dict(adults=["Isabelle C.", "Julien C."], dependants=["Emma (2014)", "Hugo (2017)"]),
        onb=dict(employment_position="Oberärztin Innere Medizin, Universitätsspital Genf", employment_magnitude=290000,
                 employment_time_basis=54, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=60000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=2009, years_in_field=17,
                kader="Oberes oder mittleres Kader", network_people=18, network_reach="in der Branche",
                hours_learning=5, hours_network=2),
        health=0.7, rest_hours="5–10", mandates=0,
        education_recent="Kurs Praxisführung und Management für Ärztinnen (2027) vor dem Einstieg in die Gruppenpraxis",
        education_hours="1–2", education_budget=12000,
        intake=dict(
            birth_year=1983, canton="Genf", municipality="Carouge", civil_status="verheiratet", married_since=2012,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Julien (Gymnasiallehrer, 80 %), Emma und Hugo", children_birth_years="2014, 2017",
            child_costs=30000, nationality="Schweiz und Frankreich", permit="Schweizer Bürgerin oder Bürger",
            plans_to_leave="nein", employment="angestellt", self_employed_form="nicht selbständig",
            employer="Hôpitaux Universitaires de Genève", income_gross=290000, income_variable=60000, pensum=100,
            work_until_age=63, thirteenth_salary="ja", income_other="Anteil am Privatpatienten-Pool, im Bruttolohn enthalten",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="CPEG (Caisse de prévoyance de l'État de Genève)", pillar2=340000, pillar2_obligatory_part=150000,
            pillar2_buyin=280000, pillar2_voluntary="nein", pillar2_conversion_rate=5.8, pillar2_early_retirement_age=58,
            pillar2_survivor_cover=90000, pillar2_disability_cover=150000,
            pillar3a_total=95000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=70000,
            other_debt="Keine. Steuern 2026 offen (etwa 62 000)", cash=120000, securities=180000,
            inheritance_expected="später von den Eltern in Annecy, eine Wohnung", spend_now=150000, spend_later=130000,
            tax_paid=62000, one_off_planned="Einkauf in die Gruppenpraxis 2030 (Anteil 600 000)",
            insurance_life=800000, insurance_disability=120000, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Standard, Franchise 2 500", legal_will="ja", legal_marriage_contract="nein",
            legal_power_of_attorney="nein", legal_patient_decree="ja", legal_beneficiary="ja, geprüft",
            max_loss_pct=25, expected_return_pct=4.5, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Vermögensverwaltungsmandat der Bank seit 2015", liquidity_reserve_months=6,
            esg_exclusions=["Waffen", "Tabak"], esg_minimum="wenn möglich",
            esg_why="Als Ärztin halte ich keinen Tabak.",
            goals="2030 Partnerin einer Gruppenpraxis werden, ab 2027 auf 80 % reduzieren, das Studium der Kinder sichern.",
            goal_confidence="90 % — es muss halten", plan_until_age=92,
            tax_marginal_rate=38, tax_wealth=3200, tax_deductions_used="Säule 3a, Kinderabzüge, Berufskosten",
            tax_church="nein", planned_events="Pensum 80 % ab 2027, Praxiseinstieg 2030",
            business_succession="Einstieg als Partnerin einer bestehenden Gruppenpraxis in Carouge",
            investments_detail="Ein ausgewogenes Verwaltungsmandat bei einer Genfer Privatbank",
            banks="Banque Cantonale de Genève, eine Privatbank", advisors="Kundenberater der Privatbank",
            documents_where="Arbeitszimmer, Kopien beim Notar",
            main_question="Was kostet mich die Reduktion auf 80 %, und wie finanziere ich den Praxisanteil?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Oberärztin HUG (100 %)", 290000, match=("angestellt",), time="54 Std./Woche"),
            P("growth", "human", "Einstieg als Partnerin einer Gruppenpraxis (2030)", time="3 Std./Woche Vorbereitung"),
            P("protection", "human", "Gesundheit: 54 Stunden pro Woche, wenig Schlaf in den Dienstwochen",
              time="7 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 120000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 180000, kind="asset", liq="within_months", vessel="free",
              desc="Ausgewogenes Verwaltungsmandat"),
            P("protection", "financial", PK, 340000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 95000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 62000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 150000, "2048-12-31", kind="retirement", funded=(PK, P3A)),
            G("Praxisanteil übernehmen 2030 (Eigenmittel 450 000)", 450000, "2030-06-30",
              match=("Praxisanteil übernehmen 2030 600000",), template="own_business", funded=(CASH, SEC),
              why="Der Anteil kostet 600 000; die Bank finanziert rund 150 000."),
            G("Pensum auf 80 % senken ab 2027 (Erholung und Familie)", 58000, "2027-01-31", funded=(CASH,),
              why="Der Lohnverzicht eines Jahres als Reserve."),
            G("Ausbildung Emma und Hugo (Studium ab 2032)", 120000, "2032-09-01", funded=(SEC,)),
            G("Weiterbildung: Praxisführung und Management 2027 (Ziel: Partnerin einer Gruppenpraxis, Netzwerk Zuweiser)",
              12000, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="pensum", q="Ich arbeite 54 Stunden und möchte ab 2027 auf 80 % reduzieren. Was kostet mich das bei der Pensionskasse, und wie kann ich die Lücke schliessen?",
                            curator="Ergänzend: Bei der CPEG sinkt mit 80 % auch der versicherte Lohn, die Lücke im Alter liegt bei Ihnen grob bei 8 bis 10 % der Rente. Sie haben ein Einkaufspotenzial von 280 000 Franken; ein gestaffelter Einkauf ab 2027 schliesst die Lücke und spart bei Ihrem Grenzsteuersatz viel Steuern. Wichtig: drei Jahre vor einem Kapitalbezug nicht mehr einkaufen. Den Praxiseinstieg 2030 rechne ich mit Ihnen getrennt, weil dann die Kasse wechselt. Nicolas"),
                   ]),
    ),
    # ------------------------------------------------------------------ 8
    dict(
        key="anita", name="Anita P.", id="5ff44a13887b4d74b5be47affcc07f3f",
        why="45, Luzern, nach zehn Jahren Familienzeit zurück in den Beruf: die Wiedereinsteigerin in Teilzeit mit kleinem Netzwerk.",
        household=dict(adults=["Anita P.", "Daniel P."], dependants=["Mia (2012)", "Jan (2014)"]),
        onb=dict(employment_position="Wiedereinstieg ab 2027 (derzeit ohne Erwerb)", employment_magnitude=0,
                 employment_time_basis=0, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="weiss ich nicht", annual_contribution=7000),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=2005, years_in_field=8,
                kader="Keine Führungsfunktion", network_people=3, network_reach="im eigenen Team", hours_learning=6,
                hours_network=3),
        health=1, rest_hours="10–20", mandates=1,
        education_recent="CAS Projektmanagement (Hochschule Luzern) seit August 2026, Abschluss Juni 2027",
        education_hours="5–10", education_budget=7500,
        intake=dict(
            birth_year=1981, canton="Luzern", municipality="Kriens", civil_status="verheiratet", married_since=2006,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Daniel (Bauingenieur, 100 %), Mia und Jan", children_birth_years="2012, 2014",
            child_costs=22000, nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="nicht erwerbstätig", self_employed_form="nicht selbständig",
            employer="ab Januar 2027: Projektleiterin bei einem Luzerner Energieversorger (Angebot liegt vor)",
            pensum=0, work_until_age=65, income_other="Daniel verdient 145 000 brutto",
            ahv_years_missing=0, ahv_ik_requested="ja", care_credit_years=10,
            pillar2_fund="Freizügigkeitsstiftung der Bank", pillar2=88000, pillar2_obligatory_part=70000,
            pillar2_voluntary="weiss ich nicht",
            pillar3a_total=36000, pillar3a_accounts=1, pillar3a_contribution=0, pillar3a_in_securities=0,
            other_debt="Keine. Steuern 2026 offen (etwa 14 000, gemeinsam)", cash=45000, securities=20000,
            inheritance_expected="von den Eltern, ein Anteil an einem Haus in Sursee, nicht vor 2035",
            spend_now=110000, spend_later=85000, tax_paid=14000,
            one_off_planned="CAS 2026 bis 2027, Lager und Musikschule der Kinder",
            insurance_life=300000, insurance_ktg="weiss ich nicht", insurance_health_model="Hausarztmodell",
            legal_will="nein", legal_marriage_contract="nein", legal_power_of_attorney="nein",
            legal_patient_decree="nein", legal_beneficiary="weiss ich nicht",
            max_loss_pct=10, expected_return_pct=3, crisis_behaviour="teilweise verkauft",
            investment_experience="Ein Anlagefonds seit 2015, 2020 teilweise verkauft", liquidity_reserve_months=6,
            esg_exclusions=["Waffen", "Glücksspiel"], esg_minimum="wenn möglich",
            goals="2027 mit 50 % wieder einsteigen, später 70 %, und eine eigene Vorsorge aufbauen, unabhängig von Daniel.",
            goal_confidence="80 %", plan_until_age=92,
            tax_marginal_rate=27, tax_church="ja", tax_deductions_used="Kinderabzüge",
            planned_events="Wiedereinstieg Januar 2027, Pensum 70 % ab 2029",
            investments_detail="Ein Anlagefonds Ausgewogen, das Freizügigkeitsgeld auf einem Zinskonto",
            banks="Luzerner Kantonalbank, Freizügigkeitsstiftung der Bank", advisors="niemand",
            documents_where="Ordner im Keller",
            main_question="Wie hole ich nach zehn Jahren Pause bei Vorsorge, Lohn und Netzwerk auf?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Wiedereinstieg ab 2027 (derzeit ohne Erwerb)", 0, match=("derzeit ohne Erwerb",),
              time="0 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Projektmanagement HSLU (seit August 2026)", time="6 Std./Woche"),
            P("stabilisation", "human", "Mitglied der Schulpflege Kriens", 4800, time="3 Std./Woche"),
            P("protection", "human", "Familie: zwei Kinder im Teenageralter", time="15 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 45000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 20000, kind="asset", liq="within_months", vessel="free"),
            P("protection", "financial", "Freizügigkeitskonto", 88000, kind="asset", liq="illiquid", vessel="pillar_2",
              match=(PK,)),
            P("protection", "financial", P3A, 36000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 14000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 110000, "2046-12-31", kind="retirement",
              funded=("Freizügigkeitskonto", P3A)),
            G("Wiedereinstieg 2027 und eigene Vorsorge aufbauen", 90000, "2035-12-31", funded=(CASH, SEC),
              why="Eigenes freies Vermögen und eine volle Säule 3a bis 2035."),
            G("Weiterbildung: CAS Projektmanagement HSLU 2026–2027 (Ziel: Wiedereinstieg als Projektleiterin, Netzwerk HSLU-Alumni)",
              7500, "2027-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="swiss-home-bias", currency="CHF", scenario=None,
                   threads=[
                       dict(key="ahv-luecke", q="Ich war zehn Jahre wegen der Kinder zu Hause und steige 2027 mit 50 % wieder ein. Habe ich Lücken bei der AHV, und was zählen die Erziehungsgutschriften?"),
                       dict(key="netzwerk", q="Wie komme ich nach so langer Pause wieder zu einem beruflichen Netzwerk und zu einem besseren Lohn?"),
                   ],
                   update=dict(note="Arbeitsvertrag unterschrieben: Projektleiterin 50 % ab Januar 2027",
                               positions={"Wiedereinstieg ab 2027 (derzeit ohne Erwerb)": dict(
                                   label="Lohn Projektleiterin Energieversorger Luzern (50 %, ab Januar 2027)",
                                   magnitude=46000, time_basis="21 Std./Woche")},
                               onb=dict(employment_magnitude=46000, employment_time_basis=21),
                               intake=dict(employment="angestellt", income_gross=46000, pensum=50,
                                           pillar3a_contribution=7258, thirteenth_salary="ja"),
                               approval="approved")),
    ),
    # ------------------------------------------------------------------ 9
    dict(
        key="corinne", name="Corinne B.", id="055aa80cf38c443ebaeea954ffe856d1",
        why="46, verwitwet, Baselland, ein Sohn vor dem Studium: die alleinerziehende Mutter mit Eigentumswohnung und Studiumsreserve.",
        household=dict(adults=["Corinne B."], dependants=["Jan (2009)"]),
        onb=dict(employment_position="Leiterin einer Apotheke in Liestal", employment_magnitude=92000,
                 employment_time_basis=38, self_employed_form="nicht selbständig", pillar2_voluntary="nein",
                 annual_contribution=6000),
        hc=dict(qualification_highest="Berufsausbildung (EFZ)", qualification_year=1999, years_in_field=26,
                kader="Oberes oder mittleres Kader", network_people=6, network_reach="im eigenen Unternehmen",
                hours_learning=1, hours_network=1),
        health=0.85, rest_hours="10–20", mandates=0,
        education_recent="keine",
        education_hours="1–2", education_budget=5000,
        intake=dict(
            birth_year=1980, canton="Basel-Landschaft", municipality="Liestal", civil_status="verwitwet",
            household="Mein Sohn Jan (17, Gymnasium)", children_birth_years="2009", child_costs=16000,
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Apotheke in Liestal (Kette)",
            income_gross=92000, pensum=90, work_until_age=65, thirteenth_salary="ja",
            income_other="Witwenrente AHV und Pensionskasse 21 600, Waisenrente für Jan 11 400 pro Jahr (bis 25, in Ausbildung)",
            ahv_years_missing=0, ahv_ik_requested="nein", care_credit_years=8,
            pillar2_fund="Sammelstiftung der Apothekenkette", pillar2=210000, pillar2_obligatory_part=150000,
            pillar2_buyin=90000, pillar2_voluntary="nein", pillar2_conversion_rate=5.4,
            pillar2_survivor_cover=40000, pillar2_disability_cover=55000,
            pillar3a_total=56000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=30000,
            properties=[dict(kind="Wohnung", place="Liestal", value=680000, occupancy="Ich wohne selbst darin",
                             own_share=100, mortgage=380000, rate=1.4, fixed_until=2030, amortisation=0,
                             amortisation_kind="keine", renovation_due="Küche in etwa fünf Jahren")],
            other_debt="Hypothek 380 000; Steuern 2026 offen (etwa 10 500)", cash=64000, securities=30000,
            inheritance_expected="nichts Bestimmtes", spend_now=78000, spend_later=65000, tax_paid=10500,
            one_off_planned="Studium von Jan ab 2028 (ETH, WG in Zürich)",
            insurance_life=300000, insurance_disability=0, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Hausarztmodell", insurance_other="Todesfallrisiko seit dem Tod meines Mannes versichert",
            legal_will="in Arbeit", legal_power_of_attorney="nein", legal_patient_decree="nein",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=12, expected_return_pct=3, crisis_behaviour="teilweise verkauft",
            investment_experience="Ein Fonds der Bank seit 2016", liquidity_reserve_months=8,
            esg_exclusions=["Waffen", "Tabak"], esg_minimum="wenn möglich",
            goals="Jans Studium sichern, die Wohnung behalten, mit 65 ohne Sorgen aufhören.",
            goal_occupancy="Ich wohne selbst darin", goal_confidence="90 % — es muss halten", plan_until_age=90,
            tax_marginal_rate=25, tax_church="ja", tax_deductions_used="Säule 3a, Schuldzinsen, Kinderabzug",
            planned_events="Jan beginnt 2028 an der ETH, Festhypothek läuft 2030 aus",
            investments_detail="Ein ausgewogener Fonds der Basellandschaftlichen Kantonalbank",
            banks="Basellandschaftliche Kantonalbank", advisors="die Kundenberaterin der Bank",
            documents_where="Ordner zu Hause, Testament beim Notar in Arbeit",
            main_question="Wer kümmert sich um Jan, wenn mir etwas passiert, und wie lege ich das Studiengeld an?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Apothekenleiterin (90 %)", 92000, match=("angestellt",), time="38 Std./Woche"),
            P("stabilisation", "human", "Witwen- und Waisenrenten (AHV und Pensionskasse)", 33000),
            P("protection", "human", "Gesundheit und Familie: allein mit Jan", time="15 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 64000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 30000, kind="asset", liq="within_months", vessel="free"),
            P("protection", "financial", PK, 210000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 56000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Eigentumswohnung Liestal (Liegenschaft)", 680000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("stabilisation", "financial", "Hypothek Eigentumswohnung Liestal", 380000, kind="liability",
              liq="illiquid", vessel="free"),
            P("stabilisation", "financial", TAX, 10500, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 76000, "2045-12-31", kind="retirement", funded=(PK, P3A)),
            G("Ausbildung des Sohnes gesichert bis 2034", 90000, "2028-08-31", funded=(CASH, SEC),
              why="Studium an der ETH ab 2028: rund 18 000 pro Jahr während fünf Jahren."),
            G("Weiterbildung: Führungsausbildung Apotheke 2027–2028 (Ziel: Geschäftsführung, +12 000 CHF, Netzwerk pharmaSuisse)",
              11000, "2028-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="conservative-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="vormund", q="Ich bin verwitwet und habe einen 17-jährigen Sohn. Was passiert, wenn mir etwas zustösst, bevor er volljährig ist, und brauche ich ein Testament?",
                            client_close=True),
                       dict(key="studiengeld", q="Mein Sohn beginnt 2028 an der ETH. Wie lege ich die 90 000 Franken für sein Studium an, die ich in zwei Jahren brauche?"),
                   ],
                   update=dict(note="Für die Führungsausbildung (eidg. Fachausweis) ab Januar 2027 angemeldet",
                               intake=dict(education_recent="Eidg. Fachausweis Führung Apotheke, angemeldet ab Januar 2027 (zwei Semester)",
                                           hours_learning=4),
                               onb=dict(hours_learning=4),
                               positions_new=[P("growth", "human", "Weiterbildung: Fachausweis Führung Apotheke (ab Januar 2027)",
                                                time="4 Std./Woche")])),
    ),
    # ------------------------------------------------------------------ 10
    dict(
        key="tanja", name="Tanja E.", id="769863770c4f4cd58dd0e8216926ee96",
        why="44, Zürich, Inhaberin einer Kommunikationsagentur (GmbH): die Unternehmerin mit Klumpenrisiko, die ein Sabbatical plant.",
        household=dict(adults=["Tanja E.", "Stefan R."], dependants=[]),
        onb=dict(employment_position="Inhaberin und Geschäftsführerin, Tanja E. Kommunikation GmbH", employment_magnitude=175000,
                 employment_time_basis=53, self_employed_form="gmbh", pillar2_voluntary="ja", annual_contribution=60000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=2006, years_in_field=18,
                kader="Oberste Führung", sector="andere Branche", network_people=40, network_reach="über die Branche hinaus",
                hours_learning=2, hours_network=8),
        health=0.7, rest_hours="5–10", mandates=2,
        education_recent="Verwaltungsrats-Ausbildung (Swiss Board School) 2027, um nach der Übergabe Mandate zu übernehmen",
        education_hours="1–2", education_budget=15000,
        intake=dict(
            birth_year=1982, canton="Zürich", municipality="Zürich", civil_status="ledig, mit Partner",
            household="Mein Partner Stefan (Architekt, selbständig), keine Kinder", nationality="Schweiz",
            permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein", employment="beides",
            self_employed_form="GmbH", employer="Tanja E. Kommunikation GmbH (12 Mitarbeitende)",
            income_gross=175000, income_variable=40000, pensum=100, work_until_age=60, thirteenth_salary="nein",
            company_value=1400000, company_income=40000,
            income_other="Verwaltungsratshonorar 18 000, Stiftungsrat unentgeltlich",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="BVG-Sammelstiftung der GmbH (Kaderlösung)", pillar2=150000, pillar2_obligatory_part=90000,
            pillar2_buyin=350000, pillar2_voluntary="ja", pillar2_conversion_rate=5.3,
            pillar2_survivor_cover=70000, pillar2_disability_cover=105000,
            pillar3a_total=96000, pillar3a_accounts=4, pillar3a_contribution=7258, pillar3a_in_securities=96000,
            other_debt="Keine privaten Schulden. Steuern 2026 offen (etwa 45 000)", cash=130000, securities=85000,
            inheritance_expected="nichts Bestimmtes", spend_now=120000, spend_later=110000, tax_paid=45000,
            one_off_planned="Sabbatical 2027 (drei Monate), Aufbau einer Geschäftsführerin 2026 bis 2028",
            insurance_life=400000, insurance_disability=120000, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Standard, Franchise 2 500", insurance_other="Schlüsselpersonenversicherung über die GmbH",
            legal_will="nein", legal_cohabitation="ja", legal_power_of_attorney="nein", legal_patient_decree="nein",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=30, expected_return_pct=5, crisis_behaviour="nachgekauft",
            investment_experience="Aktien und ETF selbst verwaltet seit 2010, 2020 nachgekauft", liquidity_reserve_months=12,
            esg_exclusions=["Waffen", "Tabak", "Glücksspiel"], esg_minimum="mehrheitlich",
            esg_why="Ich berate Firmen in Reputationskrisen und will keine eigene haben.",
            goals="Die Agentur bis 2033 so aufstellen, dass sie ohne mich läuft, 2027 ein Sabbatical, danach Verwaltungsratsmandate.",
            goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=36, tax_wealth=6500, tax_deductions_used="Säule 3a, Pensionskasseneinkauf",
            tax_church="nein",
            planned_events="Geschäftsführerin ab 2027, Sabbatical 2027, Übergabe der operativen Leitung 2033",
            business_succession="Operative Leitung an eine Geschäftsführerin, Beteiligung für das Kader ab 2030, ich bleibe im Verwaltungsrat",
            investments_detail="ETF und Schweizer Aktien selbst verwaltet, 3a in Wertschriften",
            banks="Zürcher Kantonalbank, ein Online-Broker, 3a bei vier Stiftungen",
            advisors="Treuhand der GmbH, ein Anwalt für den Gesellschaftsvertrag",
            documents_where="Büro der Agentur und ein Tresorfach",
            main_question="Wie baue ich neben der Firma genug privates Vermögen auf, und wann darf ich kürzertreten?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Geschäftsführerin Tanja E. Kommunikation GmbH", 175000, match=("selbständig",),
              time="53 Std./Woche"),
            P("growth", "human", "Zweite Führungsebene aufbauen: Geschäftsführerin ab 2027", time="6 Std./Woche"),
            P("stabilisation", "human", "Verwaltungsratsmandat (Honorar)", 18000, time="2 Std./Woche"),
            P("protection", "human", "Gesundheit: 53 Stunden pro Woche, wenig Erholung", time="7 Std. Erholung/Woche"),
            P("income", "financial", "Dividende Tanja E. Kommunikation GmbH", 40000),
            P("stabilisation", "financial", CASH, 130000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 85000, kind="asset", liq="immediate", vessel="free"),
            P("growth", "financial", "Beteiligung Tanja E. Kommunikation GmbH (100 %)", 1400000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("protection", "financial", PK, 150000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 96000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 45000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 110000, "2047-12-31", kind="retirement", funded=(PK, P3A)),
            G("Agentur unabhängig von mir machen bis 2033", 700000, "2033-12-31", template="own_business", funded=(CASH, SEC),
              why="Privates Vermögen von 700 000 ausserhalb der Firma, damit ich 2033 kürzertreten kann."),
            G("Sabbatical 2027: drei Monate Auszeit, die Agentur läuft ohne mich", 45000, "2027-07-01", funded=(CASH,)),
            G("Weiterbildung: Swiss Board School 2027 (Ziel: zwei Verwaltungsratsmandate nach der Übergabe)",
              15000, "2027-11-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="klumpen", q="Fast mein ganzes Vermögen steckt in meiner Agentur. Wie gefährlich ist das, und wie baue ich privates Vermögen daneben auf?"),
                       dict(key="sabbatical", q="Ich will 2027 drei Monate Sabbatical machen. Wie plane ich das finanziell, und was bedeutet es für meine Gesundheit und die Firma?"),
                   ],
                   report_approval="withdrawn"),
    ),
    # ------------------------------------------------------------------ 11
    dict(
        key="michele", name="Michele B.", id="68eaaf30235f48248a956e08b4391f13",
        why="47, Lugano, Architekt mit eigener AG und einer Renditeliegenschaft: das Tessin, Hypotheken und Amortisation unter steigenden Zinsen.",
        household=dict(adults=["Michele B.", "Chiara B."], dependants=["Luca (2008)", "Sofia (2011)"]),
        onb=dict(employment_position="Inhaber, Studio B. Architetti SA, Lugano", employment_magnitude=140000,
                 employment_time_basis=50, matrimonial_regime="gütertrennung", self_employed_form="ag",
                 pillar2_voluntary="ja", annual_contribution=20000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=2004, years_in_field=21,
                kader="Oberste Führung", sector="andere Branche", network_people=15, network_reach="in der Branche",
                hours_learning=2, hours_network=4),
        health=0.85, rest_hours="10–20", mandates=1,
        education_recent="CAS Bewertung von Liegenschaften (Hochschule Luzern) 2027, um Bewertungsmandate anzubieten",
        education_hours="1–2", education_budget=11000,
        intake=dict(
            birth_year=1979, canton="Tessin", municipality="Lugano", civil_status="verheiratet", married_since=2005,
            matrimonial_regime="Gütertrennung",
            household="Meine Frau Chiara (Lehrerin, 40 %), Luca und Sofia", children_birth_years="2008, 2011",
            child_costs=28000, nationality="Schweiz und Italien", permit="Schweizer Bürgerin oder Bürger",
            plans_to_leave="nein", employment="beides", self_employed_form="AG",
            employer="Studio B. Architetti SA (sechs Mitarbeitende)", income_gross=140000, income_variable=15000,
            pensum=100, work_until_age=65, company_value=450000, company_income=15000, thirteenth_salary="ja",
            income_other="Mieteinnahmen der Liegenschaft in Mendrisio, 96 000 brutto pro Jahr",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="BVG-Sammelstiftung der AG", pillar2=125000, pillar2_obligatory_part=95000, pillar2_buyin=210000,
            pillar2_voluntary="ja", pillar2_conversion_rate=5.4,
            pillar3a_total=38000, pillar3a_accounts=1, pillar3a_contribution=7258, pillar3a_in_securities=0,
            properties=[
                dict(kind="Einfamilienhaus", place="Lugano-Viganello", value=1350000, occupancy="Ich wohne selbst darin",
                     own_share=100, mortgage=780000, rate=1.7, fixed_until=2029, amortisation=10000, amortisation_kind="direkt"),
                dict(kind="anderes", place="Mendrisio (Mehrfamilienhaus, 4 Wohnungen)", value=1900000,
                     occupancy="Ich vermiete es", own_share=100, mortgage=1250000, rate=2.1, fixed_until=2027,
                     amortisation=20000, amortisation_kind="direkt", rent_income=96000,
                     renovation_due="Dach und Heizung bis 2030, etwa 180 000")],
            other_debt="Zwei Hypotheken (780 000 und 1 250 000); Steuern 2026 offen (etwa 24 000)",
            cash=22000, securities=6000, inheritance_expected="später von der Mutter, ein Rustico im Maggiatal",
            spend_now=135000, spend_later=110000, tax_paid=24000,
            one_off_planned="Dach und Heizung in Mendrisio bis 2030, Studium der Kinder ab 2027",
            insurance_life=600000, insurance_disability=90000, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Standard", legal_will="ja", legal_marriage_contract="ja",
            legal_power_of_attorney="nein", legal_patient_decree="nein", legal_beneficiary="ja, geprüft",
            max_loss_pct=20, expected_return_pct=4, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Fast alles in Immobilien; Aktien kaum", liquidity_reserve_months=3,
            esg_minimum="keine Vorgabe",
            goals="Die Renditeliegenschaft bis 2035 auf eine Hypothek von zwei Dritteln amortisieren, das Studium der Kinder zahlen, das Studio weiterführen.",
            goal_occupancy="Ich vermiete es", goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=31, tax_wealth=3800, tax_deductions_used="Liegenschaftsunterhalt, Schuldzinsen, Säule 3a",
            tax_church="ja",
            planned_events="Festhypothek Mendrisio läuft 2027 aus, Renovation bis 2030, Luca beginnt 2027 zu studieren",
            business_succession="Vielleicht übernimmt eine Mitarbeiterin in zehn Jahren; noch offen",
            investments_detail="Zwei Liegenschaften, das Studio, etwas Bargeld",
            banks="BancaStato, eine Raiffeisenbank für die Hypothek in Mendrisio", advisors="ein Treuhänder in Lugano",
            documents_where="Studio, Kopien beim Treuhänder",
            main_question="Amortisieren oder anlegen, und was passiert bei steigenden Zinsen?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Studio B. Architetti SA", 140000, match=("selbständig",), time="50 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Bewertung von Liegenschaften (2027)", time="2 Std./Woche",
              match=("Weiterbildung: CAS Immobilienbewertung (2027)",)),
            P("protection", "human", "Berufliches Netzwerk: SIA Ticino, Bauherrschaften", time="4 Std./Woche"),
            P("income", "financial", "Mieteinnahmen Renditeliegenschaft Mendrisio", 96000),
            P("stabilisation", "financial", CASH, 22000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 6000, kind="asset", liq="immediate", vessel="free"),
            P("growth", "financial", "Beteiligung Studio B. Architetti SA", 450000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("stabilisation", "financial", "Eigenheim Lugano (Liegenschaft)", 1350000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("income", "financial", "Renditeliegenschaft Mendrisio (Liegenschaft, 4 Wohnungen)", 1900000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("protection", "financial", PK, 125000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 38000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Hypothek Eigenheim Lugano", 780000, kind="liability", liq="illiquid", vessel="free"),
            P("income", "financial", "Hypothek Renditeliegenschaft Mendrisio", 1250000, kind="liability", liq="illiquid",
              vessel="free"),
            P("stabilisation", "financial", TAX, 24000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 120000, "2044-12-31", kind="retirement", funded=(PK, P3A)),
            G("Renditeobjekt halten und 2035 amortisiert haben", 250000, "2035-12-31",
              funded=(CASH, SEC, "Mieteinnahmen Renditeliegenschaft Mendrisio"),
              why="250 000 für die Amortisation der zweiten Hypothek in Mendrisio bis 2035."),
            G("Studium Luca und Sofia 2027–2034", 100000, "2027-09-01", funded=(CASH,)),
            G("Weiterbildung: CAS Bewertung von Liegenschaften 2027 (Ziel: Bewertungsmandate, +25 000 CHF pro Jahr, Netzwerk SIV)",
              11000, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="swiss-home-bias", currency="CHF", scenario="stagflation",
                   threads=[
                       dict(key="amortisieren", q="Soll ich die zweite Hypothek auf der Renditeliegenschaft in Mendrisio amortisieren oder das Geld lieber anlegen?",
                            curator="Ergänzend zur Antwort von MiniMind: Bei Ihnen spricht viel fürs Amortisieren, und zwar in Mendrisio zuerst, weil die Festhypothek 2027 ausläuft und dort der Zins höher ist. Anlegen lohnt sich nur, wenn die Rendite nach Steuern über dem Hypothekarzins liegt; mit Ihrer kleinen Reserve von drei Monaten ist das Risiko dafür zu gross. Mein Vorschlag: zuerst eine Reserve von sechs Monaten aufbauen, dann jährlich 20 000 amortisieren. Die Renovation bis 2030 nehmen wir in den nächsten Bericht auf. Nicolas"),
                       dict(key="zinsen", q="Was passiert mit meinen Mieteinnahmen und Hypotheken, wenn die Zinsen wegen Inflation stark steigen?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 12
    dict(
        key="reto", name="Reto S.", id="95c705f1559746458ee3eb7a8d61b22a",
        why="52, St. Gallen, Schreinermeister mit eigener AG und 25 Angestellten: der Unternehmer vor der Nachfolge, mit Knieproblemen.",
        household=dict(adults=["Reto S.", "Monika S."], dependants=[]),
        onb=dict(employment_position="Inhaber und Geschäftsführer, Schreinerei S. AG, Wil", employment_magnitude=155000,
                 employment_time_basis=55, matrimonial_regime="errungenschaftsbeteiligung", self_employed_form="ag",
                 pillar2_voluntary="ja", annual_contribution=50000),
        hc=dict(qualification_highest="Höhere Berufsausbildung", qualification_year=2002, years_in_field=30,
                kader="Oberste Führung", sector="andere Branche", network_people=12, network_reach="in der Branche",
                hours_learning=1, hours_network=3),
        health=0.7, rest_hours="5–10", mandates=2,
        education_recent="Kurs Unternehmensnachfolge (KMU-HSG) 2027",
        education_hours="1–2", education_budget=6000,
        intake=dict(
            birth_year=1974, canton="St. Gallen", municipality="Wil", civil_status="verheiratet", married_since=1998,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Meine Frau Monika (Buchhaltung in der Schreinerei, 40 %); die zwei Söhne sind ausgezogen",
            children_birth_years="1999, 2002", nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger",
            plans_to_leave="nein", employment="beides", self_employed_form="AG",
            employer="Schreinerei S. AG, Wil (25 Mitarbeitende)", income_gross=155000, income_variable=20000, pensum=100,
            work_until_age=63, company_value=1800000, company_income=20000, thirteenth_salary="ja",
            income_other="Prüfungsexperte Schreiner EFZ, etwa 4 000 pro Jahr",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="Pensionskasse des Gewerbes (Kaderplan)", pillar2=420000, pillar2_obligatory_part=260000,
            pillar2_buyin=240000, pillar2_voluntary="ja", pillar2_conversion_rate=5.4, pillar2_early_retirement_age=58,
            pillar3a_total=180000, pillar3a_accounts=4, pillar3a_contribution=7258, pillar3a_in_securities=60000,
            properties=[dict(kind="Einfamilienhaus", place="Wil", value=950000, occupancy="Ich wohne selbst darin",
                             own_share=50, mortgage=420000, rate=1.5, fixed_until=2031, amortisation=8000,
                             amortisation_kind="indirekt über Säule 3a")],
            other_debt="Hypothek 420 000; Steuern 2026 offen (etwa 38 000); die AG hat einen Betriebskredit",
            cash=95000, securities=20000, inheritance_expected="nichts Bestimmtes", spend_now=110000, spend_later=95000,
            tax_paid=38000, one_off_planned="Knieoperation 2027, Neubau der Spritzkabine in der Werkstatt",
            insurance_life=500000, insurance_disability=90000, insurance_ktg="ja, über Arbeitgeber",
            insurance_health_model="Standard", legal_will="ja", legal_marriage_contract="ja",
            legal_power_of_attorney="in Arbeit", legal_patient_decree="nein", legal_beneficiary="ja, geprüft",
            max_loss_pct=20, expected_return_pct=4, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Etwas Schweizer Aktien, sonst steckt alles in der Firma", liquidity_reserve_months=6,
            esg_exclusions=["Waffen"], esg_minimum="wenn möglich",
            goals="Die Schreinerei 2035 an meinen Vorarbeiter übergeben, bis dahin privates Vermögen aufbauen, mit 63 aufhören.",
            goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=33, tax_wealth=4200, tax_deductions_used="Säule 3a, Pensionskasseneinkauf, Schuldzinsen",
            tax_church="ja",
            planned_events="Knieoperation 2027, Nachfolger ab 2030 in der Geschäftsleitung, Übergabe 2035",
            business_succession="Verkauf an den Vorarbeiter (Management-Buy-out), Kaufpreis teils über ein Verkäuferdarlehen",
            investments_detail="Schweizer Blue Chips, 3a teils in Wertschriften", banks="St. Galler Kantonalbank",
            advisors="Treuhänder der AG, ein Nachfolgeberater ab 2027", documents_where="Büro in der Werkstatt, Tresor",
            main_question="Wie viel ist die Schreinerei wert, und was bleibt für mich, wenn der Nachfolger nicht alles zahlen kann?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Geschäftsführer Schreinerei S. AG", 155000, match=("selbständig",), time="55 Std./Woche"),
            P("growth", "human", "Nachfolger aufbauen: Vorarbeiter in die Geschäftsleitung ab 2030", time="3 Std./Woche"),
            P("stabilisation", "human", "Prüfungsexperte Schreiner EFZ", 4000, time="1 Std./Woche"),
            P("protection", "human", "Gesundheit: Knieprobleme, Operation 2027 geplant", time="7 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 95000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 20000, kind="asset", liq="immediate", vessel="free"),
            P("growth", "financial", "Beteiligung Schreinerei S. AG (100 %)", 1800000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("stabilisation", "financial", "Einfamilienhaus Wil (Liegenschaft, Anteil 50 %)", 475000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("protection", "financial", "Pensionskasse des Gewerbes", 420000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 180000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Hypothek Einfamilienhaus Wil (Anteil 50 %)", 210000, kind="liability",
              liq="illiquid", vessel="free"),
            P("stabilisation", "financial", TAX, 38000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 105000, "2039-12-31", kind="retirement",
              funded=("Pensionskasse des Gewerbes", P3A)),
            G("Werkstatt an Nachfolger übergeben 2035", 600000, "2035-06-30", template="own_business", funded=(CASH, SEC),
              why="Privates Vermögen von 600 000 ausserhalb der Firma, falls der Kaufpreis in Raten kommt."),
            G("Knieoperation 2027: vier Monate Ausfall überbrücken", 30000, "2027-03-31", funded=(CASH,)),
            G("Weiterbildung: Unternehmensnachfolge KMU-HSG 2027 (Ziel: Verkaufspreis sichern, Netzwerk Nachfolgeberater)",
              6000, "2027-10-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="income-focus", currency="CHF", scenario=None,
                   threads=[
                       dict(key="nachfolge", q="Ich will die Schreinerei 2035 meinem Vorarbeiter übergeben. Wie hängt der Verkaufspreis mit meiner Vorsorge zusammen, und was, wenn er den Preis nicht auf einmal zahlen kann?",
                            curator="Ergänzend: Rechnen Sie den Kaufpreis nicht als Vorsorge, solange er nicht bezahlt ist. Ein Verkäuferdarlehen an den Nachfolger ist ein Klumpen in derselben Firma, nur ohne Stimmrecht. Deshalb baut Ihr Plan bis 2035 600 000 privat auf, und den Einkauf in die Pensionskasse (240 000 möglich) sollten Sie vor dem Verkauf gestaffelt nutzen. Den Firmenwert lassen wir 2029 schätzen; bis dahin rechnen wir mit dem Wert, den Ihr Treuhänder nennt. Nicolas"),
                   ]),
    ),
    # ------------------------------------------------------------------ 13
    dict(
        key="claudia", name="Claudia I.", id="0ca16751470346cb9857db2ce520f636",
        why="53, Scuol, Hoteldirektorin mit Chalet und Hypothek: Amortisation, Festhypothek, und die Pflege der Mutter.",
        household=dict(adults=["Claudia I.", "Gian I."], dependants=[]),
        onb=dict(employment_position="Direktorin eines Hotels in Scuol", employment_magnitude=115000,
                 employment_time_basis=47, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=18000),
        hc=dict(qualification_highest="Höhere Berufsausbildung", qualification_year=1996, years_in_field=28,
                kader="Oberes oder mittleres Kader", network_people=10, network_reach="in der Branche", hours_learning=2,
                hours_network=3),
        health=0.85, rest_hours="10–20", mandates=1,
        education_recent="Nachdiplomstudium HF Hotelmanagement 2027, Ziel Generaldirektion",
        education_hours="3–5", education_budget=8000,
        intake=dict(
            birth_year=1973, canton="Graubünden", municipality="Scuol", civil_status="verheiratet", married_since=1996,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Gian (Bergführer, selbständig); die Tochter studiert in Zürich",
            children_birth_years="2002", dependants_other="Meine Mutter (84) in Scuol, zunehmend pflegebedürftig",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Hotel in Scuol (Saisonbetrieb, 40 Mitarbeitende)",
            income_gross=115000, income_variable=8000, pensum=100, work_until_age=64, thirteenth_salary="ja",
            income_other="Gian verdient als Bergführer etwa 60 000, stark schwankend",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="Hotela", pillar2=255000, pillar2_obligatory_part=180000, pillar2_buyin=85000,
            pillar2_voluntary="nein", pillar2_conversion_rate=5.6,
            pillar3a_total=68000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=20000,
            properties=[dict(kind="Einfamilienhaus", place="Scuol (Chalet)", value=1100000, occupancy="Ich wohne selbst darin",
                             own_share=100, mortgage=640000, rate=1.6, fixed_until=2029, amortisation=7258,
                             amortisation_kind="indirekt über Säule 3a", renovation_due="Fenster und Heizung 2028")],
            other_debt="Hypothek 640 000; Steuern 2026 offen (etwa 14 000)", cash=48000, securities=15000, gold_value=30000,
            inheritance_expected="Das Elternhaus in Scuol, geteilt mit dem Bruder", spend_now=90000, spend_later=80000,
            tax_paid=14000, one_off_planned="Fenster und Heizung 2028, Entlastung für die Pflege der Mutter",
            insurance_life=300000, insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell",
            legal_will="ja", legal_marriage_contract="nein", legal_power_of_attorney="nein", legal_patient_decree="ja",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=15, expected_return_pct=3, crisis_behaviour="teilweise verkauft",
            investment_experience="Ein Fonds seit 2012, 2022 teilweise verkauft", liquidity_reserve_months=5,
            esg_exclusions=["Fossile Energie"], esg_minimum="wenn möglich", esg_why="Ohne Schnee kein Tourismus im Engadin.",
            goals="Die Hypothek bis 2040 halbieren, die Mutter unterstützen, mit 64 aufhören.",
            goal_occupancy="Ich wohne selbst darin", goal_confidence="80 %", plan_until_age=90,
            tax_marginal_rate=25, tax_church="ja", tax_deductions_used="Säule 3a, Schuldzinsen, Liegenschaftsunterhalt",
            planned_events="Festhypothek läuft 2029 aus, Renovation 2028",
            investments_detail="Ein ausgewogener Fonds, Goldvreneli von der Grossmutter",
            banks="Graubündner Kantonalbank", advisors="die Kundenberaterin der Bank", documents_where="Chalet, Büroschrank",
            main_question="Wie amortisieren wir am besten, und wie helfe ich meiner Mutter, ohne mich zu übernehmen?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Hoteldirektorin Scuol", 115000, match=("angestellt",), time="47 Std./Woche"),
            P("growth", "human", "Weiterbildung: Nachdiplomstudium Hotelmanagement (2027)", time="3 Std./Woche"),
            P("stabilisation", "human", "Vorstand Tourismusverein Engiadina Scuol", time="2 Std./Woche"),
            P("protection", "human", "Betreuung der Mutter (84): zwei Nachmittage pro Woche", time="8 Std./Woche"),
            P("stabilisation", "financial", CASH, 48000, kind="asset", liq="immediate"),
            P("protection", "financial", "Sammlungen, Kunst und Fahrzeuge", 30000, kind="asset", liq="within_years",
              vessel="real_asset", desc="Goldvreneli"),
            P("growth", "financial", SEC, 15000, kind="asset", liq="within_months", vessel="free"),
            P("stabilisation", "financial", "Chalet Scuol (Liegenschaft, selbst bewohnt)", 1100000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("protection", "financial", PK, 255000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 68000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Hypothek Chalet Scuol (fest bis 2029)", 640000, kind="liability",
              liq="illiquid", vessel="free"),
            P("stabilisation", "financial", TAX, 14000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 100000, "2038-12-31", kind="retirement", funded=(PK, P3A)),
            G("Hypothek bis 2040 halbieren", 320000, "2040-12-31", funded=(CASH, SEC, P3A),
              why="Von 640 000 auf 320 000, indirekt über die Säule 3a und direkt."),
            G("Betreuung der Mutter in Scuol: Entlastungsdienst und Pflegekosten 2027–2029", 36000, "2027-12-31",
              funded=(CASH,)),
            G("Weiterbildung: NDS HF Hotelmanagement 2027 (Ziel: Generaldirektion, +20 000 CHF, Netzwerk HotellerieSuisse)",
              16000, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="income-focus", currency="CHF", scenario="stagflation",
                   threads=[
                       dict(key="festhypo", q="Unsere Festhypothek läuft 2029 aus. Sollen wir bis dahin indirekt über die Säule 3a amortisieren oder direkt?"),
                       dict(key="mutter", reask=True, q="Meine Mutter braucht zunehmend Pflege. Wie kann ich sie unterstützen, ohne meine eigene Vorsorge und meine Gesundheit zu gefährden?",
                            followup="Konkret: Wenn ich mein Pensum reduziere, um meine Mutter zu betreuen, was bedeutet das für meine Pensionskasse und meine AHV?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 14
    dict(
        key="yasmin", name="Yasmin T.", id="fed4280caf2c4afbb7ebd13d8cfc840e",
        why="53, Thurgau, Kindergärtnerin in Teilzeit, verheiratet mit Elio T.: die eine Hälfte des Ehepaars, mit eigenem Bogen und dem Ferienhaus.",
        household=dict(adults=["Yasmin T.", "Elio T."], dependants=[]),
        onb=dict(employment_position="Kindergärtnerin mit Schwerpunkt Förderbedarf (60 %)", employment_magnitude=70980,
                 employment_time_basis=24, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=30000),
        hc=dict(qualification_highest="Höhere Berufsausbildung", qualification_year=1995, years_in_field=28,
                kader="Keine Führungsfunktion", network_people=3, network_reach="im eigenen Team", hours_learning=3,
                hours_network=1),
        health=1, rest_hours="20–30", mandates=0,
        education_recent="CAS Heilpädagogische Früherziehung (Pädagogische Hochschule St. Gallen) ab 2027",
        education_hours="3–5", education_budget=6000,
        intake=dict(
            household_code="T-1998", person_label="Yasmin T.", filling_alone="nein, mein Partner füllt auch aus",
            birth_year=1973, canton="Thurgau", municipality="Kreuzlingen", civil_status="verheiratet", married_since=1998,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Elio; die zwei erwachsenen Kinder sind ausgezogen", children_birth_years="2002, 2005",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Primarschulgemeinde Kreuzlingen",
            income_gross=70980, pensum=60, work_until_age=64, thirteenth_salary="ja",
            ahv_years_missing=0, ahv_ik_requested="nein", care_credit_years=14,
            pillar2_fund="Pensionskasse Thurgau", pillar2=95000, pillar2_obligatory_part=80000, pillar2_buyin=120000,
            pillar2_voluntary="nein", pillar2_conversion_rate=5.3,
            pillar3a_total=77000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=40000,
            other_debt="Keine. Steuern 2026 offen (mein Anteil etwa 6 000)", cash=64000,
            inheritance_expected="nichts Bestimmtes", spend_now=120000, spend_later=100000, tax_paid=6000,
            one_off_planned="Ferienhaus im Tessin oder am Bodensee um 2036",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell",
            legal_will="nein", legal_marriage_contract="nein", legal_power_of_attorney="nein", legal_patient_decree="nein",
            legal_beneficiary="nein",
            max_loss_pct=10, expected_return_pct=3, crisis_behaviour="ich war nicht investiert",
            investment_experience="Nur Sparkonto und 3a", liquidity_reserve_months=12,
            esg_exclusions=["Waffen", "Kinderarbeit in der Lieferkette", "Tierversuche"], esg_minimum="mehrheitlich",
            esg_why="Ich arbeite mit Kindern; das soll mein Geld nicht verraten.",
            goals="2036 ein Ferienhaus mit Elio, vorher die Früherziehung als zweites Standbein, mit 64 aufhören.",
            goal_occupancy="Ein Zweit- oder Ferienobjekt", goal_confidence="70 % — ich kann nachjustieren",
            plan_until_age=92, tax_marginal_rate=27, tax_church="ja", tax_deductions_used="Säule 3a",
            planned_events="CAS ab 2027, Elio reduziert auf 80 % ab 2027",
            investments_detail="Sparkonto, 3a teils in einem Fonds", banks="Thurgauer Kantonalbank",
            advisors="niemand", documents_where="Ordner zu Hause",
            main_question="Wie finanzieren wir das Ferienhaus, und reicht es, wenn Elio reduziert?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Kindergärtnerin Kreuzlingen (60 %)", 70980, match=("angestellt",), time="24 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Heilpädagogische Früherziehung (ab 2027)", time="3 Std./Woche"),
            P("protection", "human", "Gesundheit: sehr gut, Wandern und Chor", time="25 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 64000, kind="asset", liq="immediate"),
            P("protection", "financial", P3A, 77000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("protection", "financial", PK, 95000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("stabilisation", "financial", "Offene Steuern 2026 (Anteil)", 6000, kind="liability", liq="within_months",
              vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 55000, "2038-12-31", kind="retirement", funded=(PK, P3A)),
            G("Ferienhaus kaufen 2036 1.5 Mio", 1500000, "2036-12-31", template="holiday_property",
              occupancy="second_or_holiday_home", kind="property", funded=(CASH,)),
            G("Weiterbildung: CAS Heilpädagogische Früherziehung 2027–2028 (Ziel: Stufe Früherziehung, +8 000 CHF, Netzwerk HfH)",
              8500, "2028-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario=None,
                   threads=[
                       dict(key="ferienhaus", q="Mein Mann und ich wollen 2036 ein Ferienhaus für 1,5 Millionen kaufen. Dürfen wir dafür Geld aus der Pensionskasse oder der Säule 3a nehmen, und wie viel Eigenkapital brauchen wir?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 15
    dict(
        key="elio", name="Elio T.", id="6b64ca98728a4c7998dce2fc6d72dfb0",
        why="58, Thurgau, Leiter Entwicklung, verheiratet mit Yasmin T.: nach einer Erschöpfung auf 80 %, mit der Frage Rente oder Kapital.",
        household=dict(adults=["Elio T.", "Yasmin T."], dependants=[]),
        onb=dict(employment_position="Leiter Entwicklung, Industriefirma in Arbon", employment_magnitude=214880,
                 employment_time_basis=50, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=45000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=1994, years_in_field=30,
                kader="Oberes oder mittleres Kader", network_people=3, network_reach="über die Branche hinaus",
                hours_learning=1, hours_network=1),
        health=0.5, rest_hours="kaum welche", mandates=0,
        education_recent="CAS Leadership Coaching (OST St. Gallen) 2027, um ab 60 als Mentor für Ingenieure zu arbeiten",
        education_hours="1–2", education_budget=9000,
        intake=dict(
            household_code="T-1998", person_label="Elio T.", filling_alone="nein, mein Partner füllt auch aus",
            birth_year=1968, canton="Thurgau", municipality="Kreuzlingen", civil_status="verheiratet", married_since=1998,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Meine Frau Yasmin; die zwei erwachsenen Kinder sind ausgezogen", children_birth_years="2002, 2005",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Industriefirma in Arbon (Maschinenbau)",
            income_gross=214880, income_variable=25000, pensum=100, work_until_age=63, thirteenth_salary="ja",
            ahv_years_missing=0, ahv_ik_requested="ja",
            pillar2_fund="Pensionskasse der Firma", pillar2=616000, pillar2_obligatory_part=280000, pillar2_buyin=180000,
            pillar2_voluntary="nein", pillar2_conversion_rate=5.4, pillar2_early_retirement_age=58,
            pillar2_survivor_cover=85000, pillar2_disability_cover=140000,
            pillar3a_total=7000, pillar3a_accounts=1, pillar3a_contribution=7258, pillar3a_in_securities=0,
            other_debt="Keine. Steuern 2026 offen (etwa 36 000)", cash=60000, securities=14000,
            inheritance_expected="nichts Bestimmtes", spend_now=120000, spend_later=100000, tax_paid=36000,
            one_off_planned="Ferienhaus mit Yasmin um 2036, Einkauf in die Pensionskasse gestaffelt",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Standard",
            legal_will="nein", legal_marriage_contract="nein", legal_power_of_attorney="nein", legal_patient_decree="nein",
            legal_beneficiary="nein",
            max_loss_pct=15, expected_return_pct=3, crisis_behaviour="alles verkauft",
            investment_experience="2008 alle Aktien verkauft, seither nur Konto und Pensionskasse",
            liquidity_reserve_months=6, esg_minimum="keine Vorgabe",
            goals="Ab 2027 auf 80 % reduzieren, gesund bleiben, mit 63 aufhören, Rente oder Kapital klug entscheiden.",
            goal_confidence="90 % — es muss halten", plan_until_age=90,
            tax_marginal_rate=34, tax_wealth=900, tax_church="ja", tax_deductions_used="Säule 3a",
            planned_events="Pensum 80 % ab 2027 nach einer Erschöpfung 2025, Pensionierung 2031",
            investments_detail="Konto, eine kleine 3a, die Pensionskasse", banks="Thurgauer Kantonalbank",
            advisors="niemand", documents_where="Ordner zu Hause",
            main_question="Rente oder Kapital, und lohnt sich vor der Reduktion noch ein Einkauf?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Leiter Entwicklung (100 %, ab 2027 80 %)", 214880, match=("angestellt",),
              time="50 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Leadership Coaching (2027)", time="1 Std./Woche"),
            P("protection", "human", "Gesundheit: Erschöpfung 2025, in Begleitung, kaum Erholung", time="3 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 60000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 14000, kind="asset", liq="immediate", vessel="free"),
            P("protection", "financial", P3A, 7000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("protection", "financial", PK, 616000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("stabilisation", "financial", TAX, 36000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 95000, "2033-12-31", kind="retirement", funded=(PK, P3A)),
            G("Pensum 80 % ab 2027: Reserve für die Lohneinbusse", 120000, "2027-12-31", funded=(CASH, SEC),
              why="Nach der Erschöpfung 2025: 80 % ab 2027, die Lohneinbusse bis zur Pensionierung aus einer Reserve."),
            G("Einkauf in die zweite Säule 2027–2030, gestaffelt", 150000, "2030-12-31", funded=(CASH,),
              why="Einkaufspotenzial 180 000; gestaffelt, damit jeder Einkauf zum hohen Grenzsteuersatz abgezogen wird."),
            G("Weiterbildung: CAS Leadership Coaching 2027 (Ziel: Mentoring-Mandate ab 60, 20 000 CHF pro Jahr, Netzwerk Swiss Engineering)",
              9000, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="crisis-resilient", currency="CHF", scenario=None,
                   threads=[
                       dict(key="rente-kapital", q="Rente oder Kapital: Ich habe 616 000 Franken in der Pensionskasse und gehe 2031 in Pension. Was spricht bei mir für die Rente, was für das Kapital?",
                            approval="approved"),
                       dict(key="reduktion", q="Nach einer Erschöpfung 2025 möchte ich auf 80 % reduzieren. Wie wirkt sich das auf meine Pensionskasse aus, und lohnt sich vorher noch ein Einkauf?"),
                   ]),
    ),
    # ------------------------------------------------------------------ 16
    dict(
        key="franziska", name="Franziska O.", id="3b31f3bd64814031a3033a36ca834437",
        why="56, Olten, geschieden, Stationsleiterin mit studierender Tochter: Scheidung und Vorsorgeausgleich, Erschöpfung und ein kleineres Pensum.",
        household=dict(adults=["Franziska O."], dependants=["Lea (2005)"]),
        onb=dict(employment_position="Stationsleiterin, Kantonsspital Olten", employment_magnitude=104000,
                 employment_time_basis=46, self_employed_form="nicht selbständig", pillar2_voluntary="nein",
                 annual_contribution=12000),
        hc=dict(qualification_highest="Höhere Berufsausbildung", qualification_year=1992, years_in_field=30,
                kader="Oberes oder mittleres Kader", network_people=8, network_reach="im eigenen Unternehmen",
                hours_learning=1, hours_network=1),
        health=0.5, rest_hours="kaum welche", mandates=0,
        education_recent="MAS Management im Gesundheitswesen (FHNW), Start 2027 mit reduziertem Pensum",
        education_hours="3–5", education_budget=10000,
        intake=dict(
            birth_year=1970, canton="Solothurn", municipality="Olten", civil_status="geschieden",
            household="Meine Tochter Lea (21, studiert in Bern, wohnt unter der Woche in einer WG)",
            children_birth_years="2005", child_costs=18000,
            alimony="Kein nachehelicher Unterhalt; Lea erhält vom Vater 900 im Monat bis zum Studienende",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Kantonsspital Olten",
            income_gross=104000, income_variable=4000, pensum=100, work_until_age=64, thirteenth_salary="ja",
            ahv_years_missing=0, ahv_ik_requested="ja", care_credit_years=12,
            pillar2_fund="Pensionskasse Kanton Solothurn", pillar2=245000, pillar2_obligatory_part=170000,
            pillar2_buyin=195000, pillar2_voluntary="nein", pillar2_conversion_rate=5.4, pillar2_early_retirement_age=58,
            pillar3a_total=62000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=25000,
            other_debt="Keine. Steuern 2026 offen (etwa 13 000)", cash=46000, securities=18000,
            inheritance_expected="nichts Bestimmtes", spend_now=72000, spend_later=62000, tax_paid=13000,
            one_off_planned="Studium von Lea bis 2031 (etwa 12 000 pro Jahr), MAS ab 2027",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell", legal_will="ja",
            legal_power_of_attorney="nein", legal_patient_decree="ja", legal_beneficiary="ja, geprüft",
            max_loss_pct=10, expected_return_pct=2.5, crisis_behaviour="teilweise verkauft",
            investment_experience="Ein Fonds seit 2014, 2022 teilweise verkauft", liquidity_reserve_months=6,
            esg_exclusions=["Waffen", "Tabak"], esg_minimum="mehrheitlich",
            goals="Leas Studium fertig finanzieren, ab 2027 auf 80 % reduzieren, das MAS machen, mit 64 aufhören.",
            goal_confidence="90 % — es muss halten", plan_until_age=90,
            tax_marginal_rate=26, tax_church="ja", tax_deductions_used="Säule 3a, Unterhalt für Lea",
            planned_events="Pensum 80 % ab Januar 2027, MAS 2027 bis 2029",
            investments_detail="Ein ausgewogener Fonds der Bank",
            banks="Solothurner Kantonalbank", advisors="niemand", documents_where="Ordner zu Hause, Scheidungskonvention beim Anwalt",
            main_question="Kann ich die Lücke aus der Scheidung schliessen, obwohl ich weniger arbeiten will?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Stationsleiterin Kantonsspital Olten (100 %)", 104000, match=("angestellt",),
              time="46 Std./Woche"),
            P("growth", "human", "Weiterbildung: MAS Management im Gesundheitswesen (ab 2027)", time="4 Std./Woche"),
            P("protection", "human", "Gesundheit: erschöpft, Schichtdienst und Überstunden", time="3 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 46000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 18000, kind="asset", liq="within_months", vessel="free"),
            P("protection", "financial", PK, 245000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 62000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", TAX, 13000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 74000, "2035-12-31", kind="retirement", funded=(PK, P3A)),
            G("Studium der Tochter finanzieren bis 2031", 45000, "2027-08-31", funded=(CASH,),
              why="Rund 12 000 pro Jahr bis 2031; die Reserve steht bis zum Herbst 2027."),
            G("Pensum auf 80 % reduzieren ab 2027 (Gesundheit): Lohneinbusse auffangen", 21000, "2027-01-31",
              funded=(CASH, SEC)),
            G("Weiterbildung: MAS Management im Gesundheitswesen 2027–2029 (Ziel: Pflegedirektion, +18 000 CHF, Netzwerk SBK)",
              24000, "2029-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="crisis-resilient", currency="CHF", scenario=None,
                   threads=[
                       dict(key="scheidung", q="Bei der Scheidung 2019 wurde meine Pensionskasse geteilt. Kann ich die Lücke mit Einkäufen wieder schliessen, und wann lohnt sich das?"),
                       dict(key="erschoepfung", q="Ich bin erschöpft und will ab 2027 auf 80 % reduzieren. Was bedeutet das für meine Rente, und wie schütze ich meine Gesundheit bis zur Pensionierung?",
                            approval="approved"),
                   ],
                   update=dict(note="Pensum ab Januar 2027 auf 80 % reduziert (mit der Spitalleitung vereinbart)",
                               positions={"Lohn Stationsleiterin Kantonsspital Olten (100 %)": dict(
                                   label="Lohn Stationsleiterin Kantonsspital Olten (80 % ab Januar 2027)",
                                   magnitude=83200, time_basis="36 Std./Woche")},
                               onb=dict(employment_magnitude=83200, employment_time_basis=36),
                               intake=dict(income_gross=83200, pensum=80, rest_hours="5–10"))),
    ),
    # ------------------------------------------------------------------ 17
    dict(
        key="regula", name="Regula A.", id="1eb449916f554a3ebe2dd8517408cde6",
        why="58, Thun, Notarin mit grossem Vermögen: Erbvorbezug, Pflichtteile, Vorsorgeauftrag und der Ausstieg 2034.",
        household=dict(adults=["Regula A.", "Hans A."], dependants=[]),
        onb=dict(employment_position="Notarin, Partnerin im Notariat A. & Partner, Thun", employment_magnitude=145000,
                 employment_time_basis=38, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="ja", annual_contribution=40000),
        hc=dict(qualification_highest="Universitäre Hochschule", qualification_year=1994, years_in_field=32,
                kader="Oberste Führung", sector="andere Branche", network_people=20, network_reach="über die Branche hinaus",
                hours_learning=2, hours_network=5),
        health=0.85, rest_hours="20–30", mandates=3,
        education_recent="CAS Mediation (Universität Bern) 2027: nach 2034 als Mediatorin in Erbstreitigkeiten tätig sein",
        education_hours="1–2", education_budget=12000,
        intake=dict(
            birth_year=1968, canton="Bern", municipality="Thun", civil_status="verheiratet", married_since=1992,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Mein Mann Hans (66, pensioniert); Andrea und Martin sind erwachsen und ausgezogen",
            children_birth_years="1994, 1997", nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger",
            plans_to_leave="nein", employment="angestellt", self_employed_form="nicht selbständig",
            employer="Notariat A. & Partner, Thun", income_gross=145000, income_variable=30000, pensum=80,
            work_until_age=66, thirteenth_salary="ja",
            income_other="Stiftungsratsmandate 12 000; Hans bezieht AHV und eine Pensionskassenrente (54 000)",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="Pensionskasse der Notariate (Kaderplan)", pillar2=640000, pillar2_obligatory_part=300000,
            pillar2_buyin=120000, pillar2_voluntary="ja", pillar2_conversion_rate=5.2, pillar2_early_retirement_age=60,
            pillar3a_total=185000, pillar3a_accounts=5, pillar3a_contribution=7258, pillar3a_in_securities=120000,
            properties=[dict(kind="Einfamilienhaus", place="Thun", value=1450000, occupancy="Ich wohne selbst darin",
                             own_share=100, mortgage=300000, rate=1.3, fixed_until=2030, amortisation=0,
                             amortisation_kind="keine")],
            other_debt="Hypothek 300 000; Steuern 2026 offen (etwa 42 000)", cash=165000, securities=320000,
            gold_value=60000,
            inheritance_expected="Von meiner Mutter (88): Anteil an einem Mehrfamilienhaus in Spiez, geschätzt 600 000",
            spend_now=115000, spend_later=120000, tax_paid=42000,
            one_off_planned="Erbvorbezug an die Kinder 2028 (je 100 000), eine längere Reise 2034",
            insurance_life=0, insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Standard, halbprivat",
            legal_will="ja", legal_marriage_contract="ja", legal_power_of_attorney="ja", legal_patient_decree="ja",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=20, expected_return_pct=3.5, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Verwaltungsmandat seit 2005, Anleihen und Schweizer Aktien", liquidity_reserve_months=12,
            esg_exclusions=["Waffen", "Tabak", "Glücksspiel"], esg_minimum="mehrheitlich",
            goals="Den Erbgang ordnen, den Kindern 2028 einen Erbvorbezug geben, 2034 aufhören und danach als Mediatorin arbeiten.",
            goal_confidence="90 % — es muss halten", plan_until_age=95,
            tax_marginal_rate=35, tax_wealth=7800, tax_deductions_used="Säule 3a, Pensionskasseneinkauf, Schuldzinsen",
            tax_church="ja",
            planned_events="Erbvorbezug 2028, Ausstieg aus dem Notariat 2034, Erbe der Mutter",
            business_succession="Meine Partnerschaft im Notariat geht 2034 an eine jüngere Kollegin",
            investments_detail="Verwaltungsmandat (Anleihen, Schweizer Aktien), Gold, Kunst",
            banks="Berner Kantonalbank, eine Privatbank für das Mandat", advisors="Privatbank, eine Steuerberaterin",
            documents_where="Tresor im Notariat, Kopien bei der Tochter",
            main_question="Wie viel dürfen wir den Kindern jetzt geben, ohne uns oder die Pflichtteile zu gefährden?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Notarin, Partnerin (80 %)", 145000, match=("angestellt",), time="38 Std./Woche"),
            P("growth", "human", "Weiterbildung: CAS Mediation (2027)", time="2 Std./Woche"),
            P("stabilisation", "human", "Drei Stiftungsratsmandate", 12000, time="3 Std./Woche"),
            P("protection", "human", "Gesundheit und Erholung: Wandern, Segeln auf dem Thunersee", time="25 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 165000, kind="asset", liq="immediate"),
            P("protection", "financial", "Sammlungen, Kunst und Fahrzeuge", 60000, kind="asset", liq="within_years",
              vessel="real_asset", desc="Kunst und Gold"),
            P("growth", "financial", SEC, 320000, kind="asset", liq="within_months", vessel="free", desc="Verwaltungsmandat"),
            P("stabilisation", "financial", "Einfamilienhaus Thun (Liegenschaft)", 1450000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("protection", "financial", PK, 640000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 185000, kind="asset", liq="illiquid", vessel="pillar_3a"),
            P("stabilisation", "financial", "Hypothek Einfamilienhaus Thun", 300000, kind="liability", liq="illiquid",
              vessel="free"),
            P("stabilisation", "financial", TAX, 42000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 140000, "2033-12-31", kind="retirement", funded=(PK, P3A)),
            G("Erbgang vorbereiten und 2034 aufhören", 120000, "2034-06-30", kind="retirement", template="estate",
              funded=(PK, P3A)),
            G("Freies Vermögen bis 2034 auf 900 000 aufbauen", 900000, "2034-06-30", funded=(CASH, SEC),
              why="Die Brücke von 2034 bis 65 und die Reserve für die Erbteilung."),
            G("Erbvorbezug an Andrea und Martin 2028 (je 80 000, Ausgleich im Testament)", 160000, "2028-06-30",
              match=("Erbvorbezug an Andrea und Martin 2028 (je 100 000, Ausgleich im Testament)",),
              template="estate", funded=(CASH, SEC)),
            G("Weiterbildung: CAS Mediation Uni Bern 2027 (Ziel: Mediationsmandate nach 2034, 40 000 CHF pro Jahr, Netzwerk SDM)",
              12000, "2027-12-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="balanced-chf", currency="CHF", scenario="depression",
                   threads=[
                       dict(key="pflichtteil", q="Wir wollen unseren beiden Kindern 2028 je 100 000 Franken als Erbvorbezug geben. Was müssen wir wegen der Pflichtteile beachten, und was gilt seit 2023?"),
                   ],
                   report_approval="revision_sent",
                   update=dict(note="Nach der Rückmeldung der Kuratorin: Erbvorbezug auf je 80 000 gesenkt, damit der Pflichtteil von Hans unberührt bleibt",
                               goals={"Erbvorbezug an Andrea und Martin 2028 (je 100 000, Ausgleich im Testament)": dict(
                                   name="Erbvorbezug an Andrea und Martin 2028 (je 80 000, Ausgleich im Testament)",
                                   target_amount=160000)},
                               approval="approved")),
    ),
    # ------------------------------------------------------------------ 18
    dict(
        key="kurt", name="Kurt W.", id="37fa2f4325a44ec2b75c9818e3f3e051",
        why="64, Baden, Leiter Einkauf ein Jahr vor der Pensionierung: Rente oder Kapital, gestaffelter 3a-Bezug, ein Depressionsszenario.",
        household=dict(adults=["Kurt W.", "Rosmarie W."], dependants=[]),
        onb=dict(employment_position="Leiter Einkauf, Industriekonzern in Baden", employment_magnitude=148000,
                 employment_time_basis=41, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=5000),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=1986, years_in_field=25,
                kader="Oberes oder mittleres Kader", network_people=10, network_reach="in der Branche", hours_learning=2,
                hours_network=2),
        health=0.85, rest_hours="20–30", mandates=0,
        education_recent="Kurs für Stiftungs- und Verwaltungsräte in KMU (2027), um nach der Pensionierung Mandate zu übernehmen",
        education_hours="1–2", education_budget=5000,
        intake=dict(
            birth_year=1962, canton="Aargau", municipality="Baden", civil_status="verheiratet", married_since=1988,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Meine Frau Rosmarie (63, pensioniert); drei erwachsene Kinder", children_birth_years="1990, 1992, 1995",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Industriekonzern in Baden",
            income_gross=148000, income_variable=12000, pensum=100, work_until_age=65, thirteenth_salary="ja",
            income_other="Rosmarie bezieht eine AHV-Rente und eine kleine Pensionskassenrente",
            ahv_years_missing=0, ahv_ik_requested="ja",
            pillar2_fund="Pensionskasse des Konzerns", pillar2=680000, pillar2_obligatory_part=320000, pillar2_buyin=0,
            pillar2_voluntary="nein", pillar2_conversion_rate=5.2, pillar2_early_retirement_age=58,
            pillar2_survivor_cover=24000,
            pillar3a_total=175000, pillar3a_accounts=3, pillar3a_contribution=7258, pillar3a_in_securities=90000,
            properties=[dict(kind="Wohnung", place="Baden", value=980000, occupancy="Ich wohne selbst darin",
                             own_share=100, mortgage=250000, rate=1.2, fixed_until=2028, amortisation=0,
                             amortisation_kind="keine")],
            other_debt="Hypothek 250 000; Steuern 2026 offen (etwa 26 000)", cash=90000, securities=140000,
            inheritance_expected="nichts", spend_now=96000, spend_later=88000, tax_paid=26000,
            one_off_planned="Wohnmobil 2028 (etwa 90 000), Hypothek allenfalls teilweise ablösen",
            insurance_ktg="ja, über Arbeitgeber", insurance_health_model="Hausarztmodell, halbprivat",
            legal_will="ja", legal_marriage_contract="ja", legal_power_of_attorney="ja", legal_patient_decree="ja",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=12, expected_return_pct=3, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Obligationen und Schweizer Aktien seit 1995", liquidity_reserve_months=12,
            esg_minimum="wenn möglich",
            goals="Ende 2027 in Pension, Rente oder Kapital entscheiden, die 3a gestaffelt beziehen, das freie Vermögen erhalten.",
            goal_confidence="90 % — es muss halten", plan_until_age=95,
            tax_marginal_rate=30, tax_wealth=2600, tax_deductions_used="Säule 3a, Schuldzinsen", tax_church="ja",
            planned_events="Pensionierung Ende 2027, Bezug der drei 3a-Konten 2026, 2027 und 2028",
            investments_detail="Obligationen, Schweizer Dividendentitel, 3a teils in Fonds", banks="Aargauische Kantonalbank",
            advisors="die Bank, selten", documents_where="Ordner zu Hause",
            main_question="Rente oder Kapital, und wie beziehe ich 3a und Pensionskasse steuerlich klug?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Lohn Leiter Einkauf (bis Ende 2027)", 148000, match=("angestellt",), time="41 Std./Woche"),
            P("growth", "human", "Weiterbildung: Kurs Stiftungs- und Verwaltungsrat (2027)", time="2 Std./Woche"),
            P("protection", "human", "Gesundheit und Erholung: Velo, Enkel", time="25 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 90000, kind="asset", liq="immediate"),
            P("income", "financial", SEC, 140000, kind="asset", liq="within_months", vessel="free",
              desc="Obligationen und Dividendentitel"),
            P("stabilisation", "financial", "Eigentumswohnung Baden (Liegenschaft)", 980000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("protection", "financial", PK, 680000, kind="asset", liq="illiquid", vessel="pillar_2"),
            P("protection", "financial", P3A, 175000, kind="asset", liq="within_years", vessel="pillar_3a",
              desc="Drei Konten, Bezug 2026, 2027, 2028"),
            P("stabilisation", "financial", "Hypothek Eigentumswohnung Baden", 250000, kind="liability", liq="illiquid",
              vessel="free"),
            P("stabilisation", "financial", TAX, 26000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben ab 65 aus eigenem Vermögen gedeckt", 88000, "2027-12-31", kind="retirement", funded=(PK, P3A)),
            G("Pensionierung 2027 planen: Rente oder Kapital", 88000, "2027-12-31", match=("Pensionierung 2027 planen",),
              kind="retirement", template="retirement", funded=(PK, P3A)),
            G("Freies Vermögen bis 2035 real erhalten", 280000, "2035-12-31", funded=(CASH, SEC),
              why="Das freie Vermögen soll seine Kaufkraft halten; Entnahmen kommen aus Rente und 3a."),
            G("Weiterbildung: Kurs Stiftungs- und Verwaltungsrat 2027 (Ziel: ein bis zwei Mandate, 15 000 CHF pro Jahr)",
              5000, "2027-10-31", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="conservative-chf", currency="CHF", scenario="depression",
                   threads=[
                       dict(key="rente-kapital", q="Ich werde Ende 2027 pensioniert. Meine Kasse bietet 5,2 % Umwandlungssatz auf 680 000 Franken. Wie entscheide ich zwischen Rente und Kapital?"),
                       dict(key="3a-bezug", q="Wie beziehe ich meine drei Säule-3a-Konten steuerlich am besten?"),
                   ],
                   report_approval="approved"),
    ),
    # ------------------------------------------------------------------ 19
    dict(
        key="esther", name="Esther W.", id="47527a1f652e4587a30abe7271a2e4c5",
        why="67, Winterthur, verwitwet, arbeitet noch 40 %: Vorsorgeauftrag, aufgeschobene Pensionskasse und Kaufkraft im Alter.",
        household=dict(adults=["Esther W."], dependants=[]),
        onb=dict(employment_position="Sekretärin der Schulleitung, Winterthur (40 %)", employment_magnitude=38000,
                 employment_time_basis=20, self_employed_form="nicht selbständig", pillar2_voluntary="nein",
                 annual_contribution=0),
        hc=dict(qualification_highest="Berufsausbildung (EFZ)", qualification_year=1978, years_in_field=40,
                kader="Keine Führungsfunktion", network_people=4, network_reach="im eigenen Team", hours_learning=1,
                hours_network=1),
        health=0.7, rest_hours="20–30", mandates=0,
        education_recent="Einführungskurs für private Beiständinnen und Beistände (KESB Winterthur) 2027 geplant",
        education_hours="1–2", education_budget=1200,
        intake=dict(
            birth_year=1959, canton="Zürich", municipality="Winterthur", civil_status="verwitwet",
            household="Ich allein; Daniel und Sabine wohnen in Zürich und Bern", children_birth_years="1985, 1988",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="angestellt", self_employed_form="nicht selbständig", employer="Stadt Winterthur, Schulsekretariat",
            income_gross=38000, pensum=40, work_until_age=68, thirteenth_salary="ja",
            income_other="AHV-Altersrente 2 520 im Monat seit 2024 (mit Verwitwetenzuschlag)",
            ahv_years_missing=0, ahv_ik_requested="nein", care_credit_years=10,
            pillar2_fund="Pensionskasse der Stadt Winterthur (Bezug aufgeschoben)", pillar2=340000,
            pillar2_obligatory_part=210000, pillar2_voluntary="nein", pillar2_conversion_rate=5.6,
            pillar3a_total=125000, pillar3a_accounts=2, pillar3a_contribution=7258, pillar3a_in_securities=50000,
            properties=[dict(kind="Wohnung", place="Winterthur", value=720000, occupancy="Ich wohne selbst darin",
                             own_share=100, mortgage=180000, rate=1.1, fixed_until=2028, amortisation=0,
                             amortisation_kind="keine", renovation_due="Bad altersgerecht umbauen")],
            other_debt="Hypothek 180 000; Steuern 2026 offen (etwa 9 000)", cash=110000, securities=85000,
            inheritance_expected="nichts", spend_now=64000, spend_later=62000, tax_paid=9000,
            one_off_planned="Bad altersgerecht umbauen (etwa 40 000), Reisen mit der Schwester",
            insurance_ktg="nein", insurance_health_model="Hausarztmodell, halbprivat",
            legal_will="ja", legal_power_of_attorney="in Arbeit", legal_patient_decree="nein",
            legal_beneficiary="ja, geprüft",
            max_loss_pct=8, expected_return_pct=2.5, crisis_behaviour="teilweise verkauft",
            investment_experience="Kassenobligationen früher, seit 2015 ein Fonds; 2022 teilweise verkauft",
            liquidity_reserve_months=18,
            esg_exclusions=["Waffen", "Tabak", "Kernkraft"], esg_minimum="mehrheitlich",
            goals="Ab 2027 nur noch vom Vermögen und den Renten leben, den Vorsorgeauftrag regeln, in der Wohnung bleiben können.",
            goal_confidence="95 % — kein Spielraum", plan_until_age=100,
            tax_marginal_rate=22, tax_wealth=1400, tax_church="ja", tax_deductions_used="Säule 3a, Schuldzinsen",
            planned_events="Ende der Anstellung Sommer 2027, Pensionskasse ab 2027 beziehen, 3a spätestens mit 70",
            investments_detail="Ein vorsichtiger Fonds, das Übrige auf dem Sparkonto", banks="Zürcher Kantonalbank",
            advisors="mein Sohn Daniel hilft", documents_where="Ordner im Wohnzimmer; eine Kopie hat Daniel",
            main_question="Wer entscheidet, wenn ich nicht mehr kann, und reicht das Geld bis 100?",
            involvement="Die wichtigsten Entscheide"),
        positions=[
            P("income", "human", "Lohn Schulsekretariat Winterthur (40 %, bis Sommer 2027)", 38000, match=("angestellt",),
              time="20 Std./Woche"),
            P("income", "financial", "AHV-Altersrente", 30240),
            P("growth", "human", "Weiterbildung: Kurs private Beiständin (2027)", time="1 Std./Woche"),
            P("protection", "human", "Gesundheit: Bluthochdruck, Wandergruppe, die Schwester in der Nähe",
              time="25 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 110000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 85000, kind="asset", liq="within_months", vessel="free", desc="Vorsichtiger Fonds"),
            P("stabilisation", "financial", "Eigentumswohnung Winterthur (Liegenschaft)", 720000, kind="asset",
              liq="illiquid", vessel="real_asset"),
            P("protection", "financial", "Pensionskasse (Bezug aufgeschoben)", 340000, kind="asset", liq="within_years",
              vessel="pillar_2", match=(PK,)),
            P("protection", "financial", P3A, 125000, kind="asset", liq="within_years", vessel="pillar_3a"),
            P("stabilisation", "financial", "Hypothek Eigentumswohnung Winterthur", 180000, kind="liability",
              liq="illiquid", vessel="free"),
            P("stabilisation", "financial", TAX, 9000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            # Owner, 03.10.2026: the retirement starts when the job ends in summer 2027, and the second goal is named
            # for what it measures (free wealth kept at 200 000 until 2031), not "live from wealth".
            G("Ausgaben im Ruhestand aus frei verfügbarem Vermögen gedeckt", 62000, "2027-07-31",
              match=("Ausgaben aus frei verfügbarem Vermögen gedeckt",), kind="retirement",
              funded=("Pensionskasse (Bezug aufgeschoben)", P3A)),
            G("Freies Vermögen bis 2031 bei 200 000 halten", 200000, "2031-12-31", funded=(CASH, SEC),
              match=("Ab 2027 vom Vermögen leben",),
              why="Das freie Vermögen soll bis 2031 bei 200 000 bleiben, Entnahmen kommen aus Renten und 3a."),
            G("Vorsorgeauftrag und Patientenverfügung beurkunden lassen", 1800, "2026-12-31", template="estate",
              funded=(CASH,)),
            G("Reserve für Spitex und einen barrierefreien Umbau", 60000, "2030-12-31", funded=(CASH,)),
            G("Weiterbildung: Kurs für private Beiständinnen 2027 (Ziel: zwei Mandate, 6 000 CHF pro Jahr, Kontakte im Quartier)",
              1200, "2027-06-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="conservative-chf", currency="CHF", scenario="hyperinflation",
                   threads=[
                       dict(key="vorsorgeauftrag", reask=True, q="Ich bin 67 und verwitwet. Wer entscheidet für mich, wenn ich nach einem Schlaganfall nicht mehr urteilsfähig bin, und was gehört in einen Vorsorgeauftrag?",
                            followup="Anders gefragt: Was regelt ein Vorsorgeauftrag, was eine Patientenverfügung, und wie errichte ich einen Vorsorgeauftrag gültig?",
                            curator="Ergänzend: Ohne Vorsorgeauftrag entscheidet bei Urteilsunfähigkeit die KESB, wer Sie vertritt; mit einem Vorsorgeauftrag bestimmen Sie das selbst, zum Beispiel Daniel für Bank und Wohnung und Sabine für die medizinischen Fragen. Er muss von Hand geschrieben, datiert und unterschrieben oder öffentlich beurkundet sein. Die Beurkundung (in Ihrem Plan mit 1 800 Franken eingesetzt) hat den Vorteil, dass der Auftrag beim Zivilstandsamt registriert wird. Die Patientenverfügung ergänzt ihn für die medizinischen Entscheide. Nicolas"),
                       dict(key="rente-kapital", q="Meine Pensionskasse ist aufgeschoben. Soll ich 2027 die Rente nehmen oder das Kapital, wenn ich allein lebe?"),
                   ],
                   report_approval="awaiting"),
    ),
    # ------------------------------------------------------------------ 20
    dict(
        key="peter", name="Peter S.", id="27e95563c12d41b3a051736f96e4c096",
        why="68, Bern, pensionierter Bauingenieur mit Ferienchalet: Übertragung an die Kinder zu Lebzeiten, Pflegereserve und ein Hyperinflationsszenario.",
        household=dict(adults=["Peter S.", "Margrit S."], dependants=[]),
        onb=dict(employment_position="Pensioniert (Bauingenieur), Gutachten ab 2027", employment_magnitude=0,
                 employment_time_basis=0, matrimonial_regime="errungenschaftsbeteiligung",
                 self_employed_form="nicht selbständig", pillar2_voluntary="nein", annual_contribution=0),
        hc=dict(qualification_highest="Fachhochschule FH", qualification_year=1982, years_in_field=40,
                kader="Keine Führungsfunktion", network_people=5, network_reach="in der Branche", hours_learning=2,
                hours_network=2),
        health=0.7, rest_hours="mehr als 30", mandates=1,
        education_recent="Zertifikatskurs Bauschadenexpertise (Hochschule Luzern) 2027, um als Gutachter zu arbeiten",
        education_hours="3–5", education_budget=6500,
        intake=dict(
            birth_year=1958, canton="Bern", municipality="Bern", civil_status="verheiratet", married_since=1983,
            matrimonial_regime="Errungenschaftsbeteiligung",
            household="Meine Frau Margrit (66); Thomas, Reto und Anna sind erwachsen", children_birth_years="1985, 1987, 1990",
            nationality="Schweiz", permit="Schweizer Bürgerin oder Bürger", plans_to_leave="nein",
            employment="pensioniert", self_employed_form="nicht selbständig", employer="pensioniert seit 2023",
            pensum=0, work_until_age=70,
            income_other="AHV-Ehepaarrente (plafoniert) 45 360 und Pensionskassenrente 40 800 pro Jahr",
            ahv_years_missing=0, ahv_ik_requested="nein",
            pillar2_fund="Pensionskasse (Rente seit 2023)", pillar2_voluntary="nein",
            pillar3a_total=0, pillar3a_accounts=0,
            properties=[
                dict(kind="Wohnung", place="Bern-Kirchenfeld", value=1100000, occupancy="Ich wohne selbst darin",
                     own_share=100, mortgage=0, amortisation_kind="keine"),
                dict(kind="Ferienobjekt", place="Adelboden (Chalet)", value=850000, occupancy="Ein Zweit- oder Ferienobjekt",
                     own_share=100, mortgage=200000, rate=1.5, fixed_until=2029, amortisation=0, amortisation_kind="keine",
                     renovation_due="Dach 2028")],
            other_debt="Hypothek auf dem Chalet 200 000; Steuern 2026 offen (etwa 21 000)", cash=140000, securities=210000,
            inheritance_expected="nichts", spend_now=96000, spend_later=96000, tax_paid=21000,
            one_off_planned="Übertragung des Chalets 2030, Dach 2028",
            insurance_health_model="Standard, halbprivat", insurance_other="Gebäudeversicherung, Privathaftpflicht",
            legal_will="in Arbeit", legal_marriage_contract="ja", legal_power_of_attorney="in Arbeit",
            legal_patient_decree="ja", legal_beneficiary="ja, geprüft",
            max_loss_pct=15, expected_return_pct=3, crisis_behaviour="nichts, ich blieb investiert",
            investment_experience="Schweizer Aktien und Obligationen seit 1990", liquidity_reserve_months=18,
            esg_exclusions=["Waffen"], esg_minimum="wenn möglich",
            goals="Das Chalet 2030 den Söhnen übertragen und Anna gerecht ausgleichen, eine Reserve für die Pflege, als Gutachter tätig bleiben.",
            goal_confidence="90 % — es muss halten", plan_until_age=98,
            tax_marginal_rate=28, tax_wealth=5200, tax_church="ja", tax_deductions_used="Liegenschaftsunterhalt, Schuldzinsen",
            planned_events="Zertifikat Bauschadenexpertise 2027, Übertragung des Chalets 2030",
            investments_detail="Schweizer Aktien und Obligationen, selbst verwaltet", banks="Berner Kantonalbank, Postfinance",
            advisors="ein Notar für die Übertragung", documents_where="Pult zu Hause, Testament beim Notar in Arbeit",
            main_question="Ist die Übertragung des Chalets gerecht für alle drei Kinder, und was gilt beim Pflichtteil?",
            involvement="Ich will alles verstehen"),
        positions=[
            P("income", "human", "Gutachten Bauschäden (ab 2027, derzeit ohne Erwerb)", 0, match=("derzeit ohne Erwerb",),
              time="0 Std./Woche"),
            P("income", "financial", "Renten AHV und Pensionskasse (Ehepaar)", 86160),
            P("growth", "human", "Weiterbildung: Zertifikat Bauschadenexpertise (2027)", time="3 Std./Woche"),
            P("stabilisation", "human", "Mitglied der Baukommission der Gemeinde Adelboden", 2500, time="2 Std./Woche"),
            P("protection", "human", "Gesundheit: Hüftoperation 2024, gute Erholung", time="35 Std. Erholung/Woche"),
            P("stabilisation", "financial", CASH, 140000, kind="asset", liq="immediate"),
            P("growth", "financial", SEC, 210000, kind="asset", liq="within_months", vessel="free"),
            P("stabilisation", "financial", "Eigentumswohnung Bern (Liegenschaft)", 1100000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("stabilisation", "financial", "Ferienchalet Adelboden (Liegenschaft)", 850000, kind="asset", liq="illiquid",
              vessel="real_asset"),
            P("protection", "financial", "Pensionskasse: seit 2023 als Rente bezogen", 0, kind="asset", liq="illiquid",
              vessel="pillar_2"),
            P("stabilisation", "financial", "Hypothek Ferienchalet Adelboden", 200000, kind="liability", liq="illiquid",
              vessel="free"),
            P("stabilisation", "financial", TAX, 21000, kind="liability", liq="within_months", vessel="free"),
        ],
        goals=[
            G("Ausgaben im Ruhestand aus frei verfügbarem Vermögen gedeckt", 96000, "2031-12-31",
              match=("Ausgaben aus frei verfügbarem Vermögen gedeckt",), kind="retirement",
              funded=(CASH, SEC, "Renten AHV und Pensionskasse (Ehepaar)")),
            G("Ferienchalet Adelboden an Thomas und Reto übertragen 2030 (Ausgleich an Anna 180 000)", 180000, "2030-06-30",
              match=("Ferienhaus an die Kinder übertragen 2030",), template="estate", funded=(CASH, SEC),
              why="Das Chalet geht an die Söhne; Anna erhält 180 000 als Ausgleich, damit alle drei gleich behandelt sind."),
            G("Reserve für Pflege und Betreuung von Margrit und mir ab 2030", 120000, "2030-12-31", funded=(CASH, SEC)),
            G("Weiterbildung: Zertifikat Bauschadenexpertise 2027 (Ziel: Gutachten für 20 000 CHF pro Jahr, Netzwerk SIA)",
              6500, "2027-09-30", template="education", funded=(CASH,)),
        ],
        chain=dict(preset="crisis-resilient", currency="CHF", scenario="hyperinflation",
                   threads=[
                       dict(key="chalet", q="Wir wollen das Ferienchalet 2030 unseren zwei Söhnen übertragen und unsere Tochter mit 180 000 Franken ausgleichen. Ist das im Sinne des Erbrechts gerecht, und was müssen wir beachten?",
                            followup="Anders gefragt: Wie funktionieren Pflichtteil und Ausgleichung im Erbrecht, wenn wir das Chalet schon zu Lebzeiten übertragen?",
                            curator="Ergänzend: Entscheidend ist, dass der Ausgleich zum Verkehrswert im Zeitpunkt des Erbgangs gerechnet wird, nicht zum heutigen. Wenn das Chalet bis dahin an Wert gewinnt, reicht der Ausgleich an Anna vielleicht nicht. Legen Sie deshalb im Erbvertrag fest, dass die Übertragung zum Wert von 2030 angerechnet wird, und dass die Hypothek von 200 000 mit übergeht. Den Notar sollten alle drei Kinder gemeinsam treffen. Nicolas", close=True),
                       # The chalet thread is closed (by the curator), so the refused question is asked again in a
                       # new thread (fix round: MiniMind 1.2.0 takes inheritance questions as in its domain).
                       dict(key="chalet-erneut", q="Meine erste Frage zum Chalet blieb damals ohne Antwort, darum noch einmal: Wir wollen das Ferienchalet 2030 unseren zwei Söhnen übertragen und unsere Tochter mit 180 000 Franken ausgleichen. Ist das im Sinne des Erbrechts gerecht, und was müssen wir beachten?"),
                   ]),
    ),
]


# =====================================================================================================
# The partners and the shares of the yearly saving (fix round of 29.09.2026, EIG-53 and EIG-59): step
# ``partners``. For each of the 13 clients with a partner, the intake's partner section (section 21, intake
# v3), the partner's income and pension-fund balance as positions the partner owns, so lbs sees two adults
# with age, income, human capital and a pension projection; for every client with more than one goal with an amount and a date, each goal's share of the
# yearly saving (``SHARES``, matched by the start of the goal's name). Figures fictional, consistent with
# docs/USE_CASES.md (the situation lines name each partner's job and workload).
# =====================================================================================================

HEALTH_1 = "1 — sehr gut"


def partner(age, income, hours, qual, year, years, network, reach, health, rest, *, edu="nein", mandates=0,
            ahv=0) -> dict[str, Any]:
    return {"partner_in_plan": "ja", "partner_age": age, "partner_income_gross": income,
            "partner_hours_per_week": hours, "partner_ahv_years_missing": ahv, "partner_qualification_highest": qual,
            "partner_qualification_year": year, "partner_years_in_field": years, "partner_education_recent": edu,
            "partner_network_people": network, "partner_network_reach": reach, "partner_mandates": mandates,
            "partner_health": health, "partner_rest_hours": rest}


def _income(label, amount, hours=None, cap="human"):
    return P("income", cap, label, amount, time=f"{hours} Std./Woche" if hours else None, owner="partner")


def _pk(label, amount):
    """The partner's pension-fund balance (0 when there is none or it is drawn as an annuity: a stated zero),
    so the partner's pension projection does not start from an unknown."""
    return P("protection", "financial", label, amount, kind="asset", liq="illiquid", vessel="pillar_2",
             owner="partner")


PARTNERS: dict[str, dict[str, Any]] = {
    "fabienne": dict(answers=partner(35, 92000, 42, "Berufsausbildung (EFZ)", 2011, 14, 6, "im eigenen Unternehmen",
                                     HEALTH_1, "10–20"),
                     positions=[_income("Lohn Marco G. (Polymechaniker, 100 %)", 92000, 42),
                                _pk("Pensionskasse Marco G.", 78000)]),
    "lukas": dict(answers=partner(36, 128000, 40, "Universitäre Hochschule", 2016, 10, 15, "in der Branche", "0.85",
                                  "10–20"),
                  positions=[_income("Lohn Sarah K. (Ärztin, 80 %)", 128000, 40), _pk("Pensionskasse Sarah K.", 145000)]),
    "isabelle": dict(answers=partner(45, 118000, 36, "Universitäre Hochschule", 2006, 18, 10, "in der Branche", HEALTH_1,
                                     "20–30", mandates=1),
                     positions=[_income("Lohn Julien C. (Gymnasiallehrer, 80 %)", 118000, 36),
                                _pk("Pensionskasse Julien C.", 265000)]),
    "anita": dict(answers=partner(47, 135000, 44, "Fachhochschule FH", 2003, 21, 20, "in der Branche", "0.85", "10–20",
                                  mandates=1),
                  positions=[_income("Lohn Daniel P. (Bauingenieur, 100 %)", 135000, 44),
                             _pk("Pensionskasse Daniel P.", 390000)]),
    "tanja": dict(answers=partner(46, 110000, 48, "Universitäre Hochschule", 2005, 19, 25, "über die Branche hinaus",
                                  "0.85", "10–20", mandates=2),
                  positions=[_income("Einkommen Stefan R. (Architekt, selbständig)", 110000, 48),
                             _pk("Pensionskasse Stefan R.: keine (selbständig)", 0)]),
    "michele": dict(answers=partner(45, 42000, 17, "Universitäre Hochschule", 2004, 20, 6, "im eigenen Unternehmen",
                                    HEALTH_1, "20–30"),
                    positions=[_income("Lohn Chiara B. (Lehrerin, 40 %)", 42000, 17), _pk("Pensionskasse Chiara B.", 120000)]),
    "reto": dict(answers=partner(51, 36000, 17, "Berufsausbildung (EFZ)", 1994, 25, 8, "in der Branche", "0.85",
                                 "10–20"),
                 positions=[_income("Lohn Monika S. (Buchhaltung Schreinerei S. AG, 40 %)", 36000, 17),
                            _pk("Pensionskasse Monika S.", 95000)]),
    "claudia": dict(answers=partner(55, 68000, 45, "Höhere Berufsausbildung", 1996, 29, 30, "über die Branche hinaus",
                                    "0.85", "20–30", mandates=1),
                    positions=[_income("Einkommen Gian I. (Bergführer, selbständig)", 68000, 45),
                               _pk("Pensionskasse Gian I.: keine (selbständig)", 0)]),
    "regula": dict(answers=partner(66, 0, 0, "Universitäre Hochschule", 1985, 35, 12, "in der Branche", "0.85",
                                   "mehr als 30", mandates=1),
                   positions=[_income("Renten AHV und Pensionskasse Hans A.", 62000, cap="financial"),
                              _pk("Pensionskasse Hans A.: als Rente bezogen", 0)]),
    "kurt": dict(answers=partner(63, 0, 0, "Berufsausbildung (EFZ)", 1981, 30, 4, "im eigenen Team", "0.85",
                                 "mehr als 30"),
                 positions=[_income("Rente Pensionskasse Rosmarie W. (AHV ab 2027)", 18000, cap="financial"),
                            _pk("Pensionskasse Rosmarie W.: als Rente bezogen", 0)]),
    # Peter's and Margrit's pensions were one position (the couple's, CHF 86 160 a year): split, the total kept.
    "peter": dict(answers=partner(66, 0, 0, "Berufsausbildung (EFZ)", 1978, 20, 5, "im eigenen Team", "0.85",
                                  "mehr als 30", mandates=1),
                  positions=[_income("AHV-Rente Margrit S.", 22680, cap="financial"),
                             _pk("Pensionskasse Margrit S.: keine", 0)],
                  split={"Renten AHV und Pensionskasse (Ehepaar)": dict(label="Renten AHV und Pensionskasse Peter S.",
                                                                          magnitude=63480)}),
    # Yasmin and Elio each keep a record: each states the other as the partner, from the other's own record.
    "yasmin": dict(of="elio", positions=[_income("Lohn Elio T. (Leiter Entwicklung, 100 %)", 214880, 50),
                                         _pk("Pensionskasse Elio T.", 616000)]),
    "elio": dict(of="yasmin", positions=[_income("Lohn Yasmin T. (Kindergärtnerin, 60 %)", 70980, 24),
                                       _pk("Pensionskasse Yasmin T.", 95000)]),
}

#: Each goal's share of the yearly saving, by the start of its name. Retirement goals rest on the pension
#: fund and the 3a (positions of their own), so none of the free saving goes to them.
SHARES: dict[str, dict[str, float]] = {
    "simon": {"Finanzielle Unabhängigkeit": 0.7, "Weiterbildung": 0.3, "Ausgaben ab 65": 0.0},
    "miriam": {"Nach der Promotion": 0.8, "Weiterbildung": 0.2, "Ausgaben ab 65": 0.0},
    "fabienne": {"Wohneigentum": 0.6, "Ausbildungsreserve": 0.25, "Weiterbildung": 0.15, "Ausgaben ab 65": 0.0},
    "lukas": {"Eigentum kaufen": 0.6, "Weiterbildung": 0.4, "Ausgaben ab 65": 0.0},
    "noemi": {"Eigene Physiotherapie": 0.6, "Gesundheitsreserve": 0.2, "Weiterbildung": 0.2, "Ausgaben ab 65": 0.0},
    "celine": {"Atelier": 0.7, "Weiterbildung": 0.3, "Ausgaben ab 65": 0.0},
    "isabelle": {"Praxisanteil": 0.5, "Pensum auf 80": 0.2, "Ausbildung Emma": 0.2, "Weiterbildung": 0.1,
                 "Ausgaben ab 65": 0.0},
    "anita": {"Wiedereinstieg": 0.7, "Weiterbildung": 0.3, "Ausgaben ab 65": 0.0},
    "corinne": {"Ausbildung des Sohnes": 0.7, "Weiterbildung": 0.3, "Ausgaben ab 65": 0.0},
    "tanja": {"Agentur unabhängig": 0.6, "Sabbatical": 0.3, "Weiterbildung": 0.1, "Ausgaben ab 65": 0.0},
    "michele": {"Renditeobjekt": 0.5, "Studium Luca": 0.4, "Weiterbildung": 0.1, "Ausgaben ab 65": 0.0},
    "reto": {"Werkstatt": 0.7, "Knieoperation": 0.2, "Weiterbildung": 0.1, "Ausgaben ab 65": 0.0},
    "claudia": {"Hypothek bis 2040": 0.5, "Betreuung der Mutter": 0.35, "Weiterbildung": 0.15, "Ausgaben ab 65": 0.0},
    "yasmin": {"Ferienhaus": 0.85, "Weiterbildung": 0.15, "Ausgaben ab 65": 0.0},
    "elio": {"Pensum 80": 0.5, "Einkauf": 0.4, "Weiterbildung": 0.1, "Ausgaben ab 65": 0.0},
    "franziska": {"Studium der Tochter": 0.5, "Pensum auf 80": 0.3, "Weiterbildung": 0.2, "Ausgaben ab 65": 0.0},
    "regula": {"Freies Vermögen": 0.6, "Erbvorbezug": 0.3, "Weiterbildung": 0.1, "Ausgaben ab 65": 0.0,
               "Erbgang": 0.0},
    "kurt": {"Freies Vermögen": 0.8, "Weiterbildung": 0.2, "Ausgaben ab 65": 0.0, "Pensionierung": 0.0},
    "esther": {"Ab 2027": 0.5, "Vorsorgeauftrag": 0.1, "Reserve für Spitex": 0.3, "Weiterbildung": 0.1,
               "Ausgaben im Ruhestand": 0.0},
    "peter": {"Ferienchalet": 0.4, "Reserve für Pflege": 0.5, "Weiterbildung": 0.1, "Ausgaben im Ruhestand": 0.0},
}
assert all(abs(sum(v.values())) <= 1 + 1e-9 for v in SHARES.values())

#: The nominal and real view (EIG-60, EIG-61). Every goal with an amount states whether the amount is in today's
#: francs; these are in the francs of their date, because the amount is fixed in francs: a mortgage to pay down,
#: a debt to amortise, a contract price, a sum promised in a will, a pension-fund buy-in from the fund's statement.
FUTURE_FRANCS: dict[str, tuple[str, ...]] = {
    "claudia": ("Hypothek bis 2040",),
    "michele": ("Renditeobjekt",),
    "isabelle": ("Praxisanteil",),
    "regula": ("Erbvorbezug",),
    "elio": ("Einkauf",),
}
#: Whether the yearly saving rises with prices: yes for the employed, whose salary follows the cost of living;
#: no for the self-employed, those between jobs and those who live on their assets.
INDEXED: dict[str, str] = {
    "simon": "ja", "miriam": "ja", "fabienne": "ja", "lukas": "ja", "noemi": "ja", "celine": "nein",
    "isabelle": "ja", "anita": "nein", "corinne": "ja", "tanja": "nein", "michele": "nein", "reto": "nein",
    "claudia": "ja", "yasmin": "ja", "elio": "ja", "franziska": "ja", "regula": "nein", "kurt": "nein",
    "esther": "nein", "peter": "nein",
}

#: lbsim's earning-power answers (EIG-65, intake v4): the gross salary expected at a full pensum once any education
#: is done (today's francs), whether an education is under way or planned and when it ends, and how far health
#: limits the working week (K3). Three leave the salary unanswered, so the outlook shows the model's own level
#: ("Modellwert"): Corinne (no education, no plan to change), Esther (a 40 % job at 67) and Peter (retired).
#: ``partner`` holds the partner's own, where the partner works; a retired partner leaves them unanswered too.
def E(income, status, end=None, capacity="nein", partner=None):
    out = {"income_expected_full": income, "education_status": status, "education_end_year": end,
           "health_work_capacity": capacity}
    return {"own": {k: v for k, v in out.items() if v is not None}, "partner": partner or {}}


def EP(income=None, status="keine", kader="Keine Führungsfunktion", capacity="nein", end=None):
    out = {"partner_income_expected_full": income, "partner_education_status": status,
           "partner_education_end_year": end, "partner_kader": kader, "partner_health_work_capacity": capacity}
    return {k: v for k, v in out.items() if v is not None}


EARNING: dict[str, dict[str, Any]] = {
    "simon": E(99000, "läuft", 2028),
    "miriam": E(95000, "geplant", 2027),
    "fabienne": E(96000, "geplant", 2028, partner=EP(92000)),
    "lukas": E(200000, "geplant", 2029, partner=EP(160000)),
    "noemi": E(92000, "geplant", 2029, "leicht"),
    "celine": E(110000, "geplant", 2027),
    "isabelle": E(310000, "geplant", 2027, "leicht", partner=EP(147500)),
    "anita": E(105000, "läuft", 2027, partner=EP(135000, kader="Oberes oder mittleres Kader")),
    "corinne": E(None, "keine"),
    "tanja": E(175000, "geplant", 2027, "leicht", partner=EP(110000)),
    "michele": E(150000, "geplant", 2027, partner=EP(105000)),
    "reto": E(155000, "geplant", 2027, "leicht", partner=EP(90000)),
    "claudia": E(135000, "geplant", 2028, partner=EP(68000)),
    "yasmin": E(120000, "geplant", 2028),
    "elio": E(214880, "geplant", 2027, "deutlich"),
    "franziska": E(125000, "geplant", 2029, "deutlich"),
    "regula": E(180000, "geplant", 2028, partner=EP(None)),
    "kurt": E(148000, "geplant", 2027, partner=EP(None)),
    "esther": E(None, "geplant", 2027, "leicht"),
    "peter": E(None, "geplant", 2027, "leicht", partner=EP(None)),
}
#: The couple with two records states each other from the other's own answers (as for the partner section).
EARNING_OF = {"yasmin": "elio", "elio": "yasmin"}
assert len(EARNING) == 20 and sum(1 for e in EARNING.values() if "income_expected_full" not in e["own"]) == 3


# =====================================================================================================
# The build: every write goes through the app's API, the store's documented functions or the cockpit's
# curator routes. Nothing here edits a row directly.
# =====================================================================================================

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eigentlich import inputs as lbs_inputs  # noqa: E402
from eigentlich import store  # noqa: E402
from eigentlich.settings import load  # noqa: E402
from eigentlich.store import Store  # noqa: E402

APP = os.environ.get("USE_CASES_APP", "http://127.0.0.1:8017")
COCKPIT = os.environ.get("USE_CASES_COCKPIT", "http://127.0.0.1:8098")
LBS = os.environ.get("USE_CASES_LBS", "http://127.0.0.1:8013")
PCP = os.environ.get("USE_CASES_PCP", "http://127.0.0.1:8007")
CURATOR = os.environ.get("USE_CASES_CURATOR", "ac586536e6be42c68446c8f8f80e4242")   # Nicolas
#: The Default Regime and the four scenarios aggregation derives from it (cockpit C-30: the Regime is the latest
#: succeeded one of the optimism level, default unless named). ``mandates`` asks the cockpit's own choice
#: (``GET /api/curator/regime``) and stops if it differs from these.
OPTIMISM = os.environ.get("USE_CASES_OPTIMISM", "default")
BASE_REGIME = os.environ.get("USE_CASES_REGIME", "RGM-e2658e8e9bbbc81e")
SCENARIOS = {"depression": "RGM-1af6968e287768c9", "hyperinflation": "RGM-59eebfaf7744d8ec",
             "stagflation": "RGM-6bb531998bfefc4d", "deferral": "RGM-c0ed086f1916984e"}
BACKUP = Path(os.environ.get("USE_CASES_BACKUP", r"C:\Users\nicol\Desktop\SIM_NAS\Projects\PostgreSQL\backups"
                                                 r"\eigentlich-before-use-cases-2026-09-29.sql"))
OUT = ROOT / "dev" / "reports"
HEALTH_OPTION = {1: "1 — sehr gut", 1.0: "1 — sehr gut", 0.85: "0.85", 0.7: "0.7", 0.5: "0.5"}
POLICY_BOUND_DIMS = ("region", "capital_type", "phase", "asset_class")

http = httpx.Client(timeout=httpx.Timeout(360.0, connect=10.0))


def log(*parts):
    print(datetime.now().strftime("%H:%M:%S"), *parts, flush=True)


def call(method, url, *, ok=(200, 201), retries=3, **kw):
    """One HTTP call; retries a refused connection (the report engine may be restarted once)."""
    for attempt in range(retries + 1):
        try:
            r = http.request(method, url, **kw)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            if attempt == retries:
                raise
            log("  retry after", type(exc).__name__, url)
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in ok:
            return r.json() if r.content else None
        if r.status_code in (502, 503) and attempt < retries:
            log("  retry after", r.status_code, url, r.text[:200])
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:1500]}")


def app(method, path, **kw):
    return call(method, APP + path, **kw)


def cockpit(method, path, **kw):
    return call(method, COCKPIT + path, **kw)


def by_key(key):
    for c in CLIENTS:
        if c["key"] == key or c["id"] == key or c["name"] == key:
            return c
    raise KeyError(key)


def selected(args):
    return [by_key(k) for k in args.only.split(",")] if getattr(args, "only", None) else CLIENTS


def the_store() -> Store:
    return Store(load().database)


# ----------------------------------------------------------------------------------------- selection

def cmd_select(args):
    ids = [c["id"] for c in CLIENTS]
    assert len(ids) == 20 and len(set(ids)) == 20, "exactly 20 distinct clients"
    with the_store().session() as conn:
        rows = {r["id"]: r for r in conn.execute("SELECT id, display_name, age_at_registration FROM client").fetchall()}
    for c in CLIENTS:
        row = rows.get(c["id"])
        assert row and row["display_name"] == c["name"], f"{c['name']}: not in the store as named"
        print(f"{c['name']:<14} {row['age_at_registration']:>3}  {c['why']}")
    print(f"\n{len(rows)} clients in the store, 20 kept, {len(set(rows) - set(ids))} to erase")


# ------------------------------------------------------------------------------------------ erasure

def _backup_ok() -> bool:
    if not BACKUP.is_file() or BACKUP.stat().st_size < 100_000:
        return False
    with BACKUP.open(encoding="utf-8", errors="replace") as f:
        return any(line.startswith("COPY eigentlich.client ") for line in f)


def _backup_rows():
    """Rows per table and the client ids in the backup (pg_dump COPY blocks): the state before the erasure."""
    counts, clients, table, cols = {}, [], None, []
    with BACKUP.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if table is None:
                if line.startswith("COPY eigentlich."):
                    table = line.split()[1].split(".", 1)[1]
                    cols = line[line.index("(") + 1:line.index(")")].split(", ")
                    counts[table] = 0
                continue
            if line.startswith("\\."):
                table = None
                continue
            counts[table] += 1
            if table == "client":
                clients.append(line.split("	")[cols.index("id")])
    return counts, clients


def cmd_erase(args):
    """Every client not among the 20, one at a time, through ``store.erase_client`` as the owning role; then the
    reconciliation against the backup (so it can be run again after the erasure)."""
    if not _backup_ok():
        sys.exit(f"no usable backup at {BACKUP}: nothing is erased without one")
    keep = {c["id"] for c in CLIENTS}
    st = the_store()
    with st.session() as conn:
        others = [r["id"] for r in conn.execute("SELECT id FROM client ORDER BY display_name").fetchall()
                  if r["id"] not in keep]
        names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM client").fetchall()}
    log(f"{len(others)} clients to erase, {len(keep)} kept")
    if others and not args.apply:
        for cid in others:
            print(" ", names[cid])
        print("dry run: add --apply to erase")
        return
    for cid in others:
        with st.session() as conn:
            removed = store.erase_client(conn, cid)
        log("erased", cid, sum(removed.values()), "rows")
    before, backup_clients = _backup_rows()
    erased = [cid for cid in backup_clients if cid not in keep]
    with st.session() as conn:
        after = store.table_counts(conn)
        tables = [r["table_name"] for r in conn.execute(
            "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t "
            "ON t.table_schema = c.table_schema AND t.table_name = c.table_name WHERE c.table_schema = %s "
            "AND c.column_name = 'client_id' AND t.table_type = 'BASE TABLE' ORDER BY 1", (st.config.schema,)).fetchall()]
        residue = {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE client_id = ANY(%s)", (erased,)).fetchone()["n"]
                   for t in tables}
        for label, sql_ in (("decision.author_ref", "SELECT count(*) AS n FROM decision WHERE author_ref = ANY(%s)"),
                            ("answer.answered_by_ref", "SELECT count(*) AS n FROM answer WHERE answered_by_ref = ANY(%s)"),
                            ("content_record.saved_by_ref", "SELECT count(*) AS n FROM content_record WHERE saved_by_ref = ANY(%s)"),
                            ("thread_message.author_ref", "SELECT count(*) AS n FROM thread_message WHERE author_ref = ANY(%s)"),
                            ("approval_event.actor_ref", "SELECT count(*) AS n FROM approval_event WHERE actor_ref = ANY(%s)"),
                            ("engine_run.requested_by_ref", "SELECT count(*) AS n FROM engine_run WHERE requested_by_ref = ANY(%s)"),
                            ("decision_* links to missing decisions",
                             "SELECT (SELECT count(*) FROM decision_position l WHERE NOT EXISTS (SELECT 1 FROM decision d WHERE d.id = l.decision_id))"
                             " + (SELECT count(*) FROM decision_goal l WHERE NOT EXISTS (SELECT 1 FROM decision d WHERE d.id = l.decision_id))"
                             " + (SELECT count(*) FROM decision_client_fact l WHERE NOT EXISTS (SELECT 1 FROM decision d WHERE d.id = l.decision_id))"
                             " + (SELECT count(*) FROM decision_household l WHERE NOT EXISTS (SELECT 1 FROM decision d WHERE d.id = l.decision_id))"
                             " + (SELECT count(*) FROM decision_household_member l WHERE NOT EXISTS (SELECT 1 FROM decision d WHERE d.id = l.decision_id))"
                             " + 0 * cardinality(%s::text[]) AS n")):
            residue[label] = conn.execute(sql_, (erased,)).fetchone()["n"]
        kept_rows = {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE client_id = ANY(%s)", (sorted(keep),)).fetchone()["n"]
                     for t in tables}
    report = {"at": datetime.now(timezone.utc).isoformat(), "backup": str(BACKUP),
              "clients_before": len(backup_clients), "clients_after": after["client"], "kept": sorted(keep),
              "erased": erased, "rows_before": before, "rows_now": after,
              "rows_gone": {t: before.get(t, 0) - after.get(t, 0) for t in before},
              "rows_of_the_kept_now": kept_rows, "residue_of_the_erased": residue,
              "reconciled": len(backup_clients) - len(erased) == after["client"] == 20 and not any(residue.values()),
              "note": "rows_now includes what the build wrote for the 20 after the erasure, when run later"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "use-cases-erasure.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log(f"clients {len(backup_clients)} -> {after['client']}; erased {len(erased)}; "
        f"residue {sum(residue.values())}; reconciled {report['reconciled']}")


# ------------------------------------------------------------------------------------------ enrichment

def _onboarding_answers(c, current):
    hc = c["hc"]
    it = c["intake"]
    want = {
        "household_composition": {"adults": c["household"]["adults"], "dependants": c["household"]["dependants"]},
        "canton": it["canton"], "civil_status": it["civil_status"],
        "network_people": hc["network_people"], "health": c["health"],
        "qualification_highest": hc["qualification_highest"], "qualification_year": hc["qualification_year"],
        "years_in_field": hc["years_in_field"], "kader": hc["kader"], "network_reach": hc["network_reach"],
        "hours_learning": hc["hours_learning"], "hours_network": hc["hours_network"],
    }
    if hc["kader"] == "Oberste Führung":
        want["sector"] = hc.get("sector") or "andere Branche"
    want.update({k: v for k, v in c["onb"].items() if v is not None})
    if "first_goal" not in current:
        want["first_goal"] = c["goals"][0]["name"]
    return want


def _intake_answers(c):
    hc = c["hc"]
    want = dict(person_label=c["name"], filling_alone="ja, ich plane allein")
    want.update(c["intake"])
    # hours_learning left the intake in version 3 (EIG-58); the onboarding still asks it.
    want.update({k: hc[k] for k in ("qualification_highest", "qualification_year", "years_in_field", "kader",
                                    "network_people", "network_reach", "hours_network")})
    if hc["kader"] == "Oberste Führung":
        want["sector"] = hc.get("sector") or "andere Branche"
    want.update(education_recent=c["education_recent"], education_hours=c["education_hours"],
                education_budget=c["education_budget"], mandates=c["mandates"],
                health=HEALTH_OPTION[c["health"]], rest_hours=c["rest_hours"])
    return {k: v for k, v in want.items() if v is not None}


def answer_all(cid, name, want):
    q = app("GET", f"/api/clients/{cid}/questionnaires/{name}")
    version = q["version"]
    keys = {x["key"] for x in q["questions"]}
    changed = []
    for key, value in want.items():
        if key not in keys:
            raise RuntimeError(f"{name} v{version} has no question {key}")
        have = (q["answers"].get(key) or {}).get("value", None)
        if have == value:
            continue
        if isinstance(have, list) and isinstance(value, list) and all(isinstance(x, str) for x in have + value)                 and sorted(have) == sorted(value):
            continue                                  # a multi_choice is stored in the questionnaire's order
        app("PUT", f"/api/clients/{cid}/questionnaires/{name}/answers/{key}",
            json={"content_version": version, "value": value})
        changed.append(key)
    return changed


def restate_facts(c, want_onb):
    """A stated fact wins over an answer (inputs.py). Since the fix round (EIG-54) the app restates a fact when
    the question that fills it is answered again; a fact that still differs from its answer (an answer given
    before that fix, so not answered again now) is restated through the app's own route, ``PUT .../facts/{key}``,
    under the client's decision (C-09)."""
    cid = c["id"]
    facts = {f["stated_key"]: f for f in app("GET", f"/api/clients/{cid}/plan")["facts"]}
    todo = {k: v for k, v in want_onb.items() if k in facts and facts[k]["stated_value"] != v}
    for k, v in todo.items():
        app("PUT", f"/api/clients/{cid}/facts/{k}",
            json={"value": v, "reasoning": "Im Erstgespräch neu beantwortet; die festgehaltene Angabe folgt."})
    return sorted(todo)


def _pos_fields(p):
    out = {k: p[k] for k in ("role", "capital_type", "label", "description", "magnitude", "magnitude_unit",
                             "stock_kind", "liquidity", "time_basis")}
    if p.get("owner"):                               # the partner's (EIG-53); the client's is stored as none
        out["owner"] = p["owner"]
    return out


def sync_positions(c, specs, reasoning_new="Aus dem Fragebogen übernommen.",
                   reasoning_change="Mit den Angaben im Fragebogen abgeglichen."):
    cid = c["id"]
    plan = app("GET", f"/api/clients/{cid}/plan")
    rows = plan["positions"]
    done = []
    for spec in specs:
        row = next((r for r in rows if r["label"] in spec["match"] and r["active"]), None) or \
            next((r for r in rows if r["label"] in spec["match"]), None)
        want = _pos_fields(spec)
        vessel = spec.get("vessel")
        if row is None:
            body = {k: v for k, v in want.items() if v is not None}
            if vessel:
                body["vessel"] = vessel
            body["reasoning"] = reasoning_new
            row = app("POST", f"/api/clients/{cid}/positions", json=body)
            rows.append({**row, "tags": row.get("tags") or {}})
            done.append(f"+{spec['label']}")
            continue
        diff = {k: v for k, v in want.items() if row.get(k) != v}
        if (row.get("tags") or {}).get("vessel") != vessel and (vessel or (row.get("tags") or {}).get("vessel")):
            diff["vessel"] = vessel
        if "magnitude" in diff or "magnitude_unit" in diff:
            diff["magnitude"], diff["magnitude_unit"] = want["magnitude"], want["magnitude_unit"]
            diff["stock_kind"] = want["stock_kind"]
        if diff:
            diff["reasoning"] = reasoning_change
            app("PATCH", f"/api/clients/{cid}/positions/{row['id']}", json=diff)
            done.append(f"~{spec['label']}")
        if not row["active"]:
            app("POST", f"/api/clients/{cid}/positions/{row['id']}/reactivate", json={"reasoning": reasoning_change})
    return done


def sync_goals(c):
    cid = c["id"]
    plan = app("GET", f"/api/clients/{cid}/plan")
    positions = {p["label"]: p["id"] for p in plan["positions"] if p["active"]}
    rows = plan["goals"]
    done = []
    for spec in c["goals"]:
        kind = lbs_inputs.goal_kind({"name": spec["name"], "template": spec["template"], "occupancy": spec["occupancy"]})
        assert kind == spec["kind"], f"{c['name']}: goal «{spec['name']}» reads as {kind}, not {spec['kind']}"
        funded = sorted(positions[label] for label in spec["funded"])
        row = next((g for g in rows if g["name"] in spec["match"]), None)
        want = {"name": spec["name"], "target_amount": spec["target_amount"], "target_date": spec["target_date"],
                "template": spec["template"], "occupancy": spec["occupancy"]}
        if row is None:
            body = {k: v for k, v in want.items() if v is not None}
            body["funded_by"] = funded
            body["reasoning"] = spec["why"] or "Ziel aus dem Fragebogen übernommen."
            app("POST", f"/api/clients/{cid}/goals", json=body)
            done.append(f"+{spec['name'][:50]}")
            continue
        have = {**row, "target_date": row["target_date"][:10] if row.get("target_date") else None}
        diff = {k: v for k, v in want.items() if have.get(k) != v}
        if sorted(row.get("funded_by") or []) != funded:
            diff["funded_by"] = funded
        if diff:
            diff["reasoning"] = spec["why"] or "Betrag, Datum und Finanzierung ergänzt."
            app("PATCH", f"/api/clients/{cid}/goals/{row['id']}", json=diff)
            done.append(f"~{spec['name'][:50]}")
        if not row["active"]:
            app("POST", f"/api/clients/{cid}/goals/{row['id']}/reactivate", json={"reasoning": "Wieder verfolgen."})
    return done


def sync_household(c):
    cid = c["id"]
    plan = app("GET", f"/api/clients/{cid}/plan")
    members = plan.get("members") or []
    adults = [m["label"] for m in members if m["kind"] == "adult"]
    dependants = [m["label"] for m in members if m["kind"] == "dependant"]
    want = c["household"]
    if plan.get("household") and adults[:1] == want["adults"][:1] and sorted(adults) == sorted(want["adults"]) \
            and sorted(dependants) == sorted(want["dependants"]):
        return False
    app("PUT", f"/api/clients/{cid}/household",
        json={"adults": want["adults"], "dependants": want["dependants"],
              "reasoning": "Haushalt aus dem Fragebogen übernommen."})
    return True


def effective(c):
    """The use case as the store should hold it now: after its update, once the update was asked for (so a
    re-run of enrich does not undo the change the update reports)."""
    import copy
    u = (c["chain"].get("update") or {})
    if not u or not any(r["kind"] == "update" for r in app("GET", f"/api/clients/{c['id']}/reports")):
        return c
    c = copy.deepcopy(c)
    for label, change in (u.get("positions") or {}).items():
        spec = next(p for p in c["positions"] if p["label"] == label)
        spec.update({k: v for k, v in change.items() if k in ("label", "magnitude", "time_basis")})
        spec["match"] = tuple(spec["match"]) + (label, spec["label"])
    c["positions"] = c["positions"] + list(u.get("positions_new") or [])
    for name, change in (u.get("goals") or {}).items():
        spec = next((g for g in c["goals"] if name in g["match"] or g["name"] == change.get("name")), None)
        if spec:
            spec.update({k: v for k, v in change.items() if k in ("name", "target_amount", "target_date")})
            spec["match"] = tuple(spec["match"]) + (name, spec["name"])
    c["onb"] = {**c["onb"], **(u.get("onb") or {})}
    c["hc"] = {**c["hc"], **(u.get("hc") or {})}
    intake = dict(u.get("intake") or {})
    for k in ("education_recent", "rest_hours", "mandates"):
        if k in intake:
            c[k] = intake.pop(k)
    for k in list(intake):
        if k in c["hc"]:
            c["hc"][k] = intake.pop(k)
    c["intake"] = {**c["intake"], **intake}
    return c


def with_split(c):
    """A position the partner shares (Peter's and Margrit's pensions) is split: the client's part keeps the
    position under a new label, the partner's is a position of its own (``PARTNERS[...]["split"]``). Applied
    to the spec, so ``enrich`` and ``partners`` write the same, and a goal funded by it follows the label."""
    import copy
    split = (PARTNERS.get(c["key"]) or {}).get("split")
    if not split:
        return c
    c = copy.deepcopy(c)
    for old, change in split.items():
        spec = next(x for x in c["positions"] if old in x["match"])
        spec.update(change)
        spec["match"] = tuple(spec["match"]) + (old, spec["label"])
        for g in c["goals"]:
            g["funded"] = tuple(spec["label"] if f == old else f for f in g["funded"])
    return c


def enrich_one(c):
    c = with_split(effective(c))
    cid = c["id"]
    q = app("GET", f"/api/clients/{cid}/questionnaires/onboarding")
    current = {k: v["value"] for k, v in q["answers"].items()}
    want_onb = _onboarding_answers(c, current)
    hh = sync_household(c)
    onb = answer_all(cid, "onboarding", want_onb)
    facts = restate_facts(c, want_onb)
    intake = answer_all(cid, "intake", _intake_answers(c))
    pos = sync_positions(c, c["positions"])
    goals = sync_goals(c)
    log(f"{c['name']:<14} household {'new' if hh else 'kept'}; onboarding {len(onb)}; facts {facts}; "
        f"intake {len(intake)}; positions {len(pos)}; goals {goals}")


def mandate_goal(c):
    with the_store().session() as conn:
        g = lbs_inputs.gather(conn, c["id"])
    request, dropped = lbs_inputs.build(g, date.today())
    name = next((x["name"] for x in g.goals if request.mandate and x["id"] == request.mandate.goal_id), None)
    return name, dropped


def cmd_enrich(args):
    for c in selected(args):
        enrich_one(c)
        name, dropped = mandate_goal(c)
        log(f"{'':<14} mandate goal: {name}; dropped: {dropped or 'nothing'}")


# ------------------------------------------------------------------------------------------ partners

def partner_answers(c):
    """The partner section's answers: stated for the use case, or, for a couple with two records, read from
    the other record's own use case (Yasmin's partner is Elio as Elio's record states him)."""
    spec = PARTNERS[c["key"]]
    if "answers" in spec:
        return dict(spec["answers"])
    o = effective(by_key(spec["of"]))
    age = date.today().year - o["intake"]["birth_year"]
    return partner(age, o["intake"]["income_gross"], o["onb"]["employment_time_basis"],
                   o["hc"]["qualification_highest"], o["hc"]["qualification_year"], o["hc"]["years_in_field"],
                   o["hc"]["network_people"], o["hc"]["network_reach"], HEALTH_OPTION[o["health"]], o["rest_hours"],
                   edu=o["education_recent"], mandates=o["mandates"], ahv=o["intake"].get("ahv_years_missing") or 0)


def sync_shares(c):
    """Each goal's share of the yearly saving, 0 to 1 (the page shows %); lowered ones first, so the running
    sum never passes 1 on the way (the app refuses that)."""
    cid = c["id"]
    want = SHARES.get(c["key"]) or {}
    goals = [g for g in app("GET", f"/api/clients/{cid}/plan")["goals"] if g["active"]]
    todo = []
    for g in goals:
        share = next((v for prefix, v in want.items() if g["name"].startswith(prefix)), None)
        if share is None or g.get("contribution_share") == share:
            continue
        todo.append((share - (g.get("contribution_share") or 0), g, share))
    for _, g, share in sorted(todo, key=lambda x: x[0]):
        app("PATCH", f"/api/clients/{cid}/goals/{g['id']}",
            json={"contribution_share": share, "reasoning": "Anteil am jährlichen Sparbetrag festgelegt."})
    return [f"{g['name'][:30]} {share:.0%}" for _, g, share in todo]


def cmd_partners(args):
    """The partner stated (EIG-53) and each goal's share of the saving (EIG-59), through the app's routes; then
    one lbs run per client, the curator's button (the app's route with Nicolas's id)."""
    summary = {}
    for c in selected(args):
        cid = c["id"]
        done = {}
        if c["key"] in PARTNERS:
            spec = PARTNERS[c["key"]]
            e = with_split(effective(c))
            done["answers"] = answer_all(cid, "intake", partner_answers(c))
            if spec.get("split"):
                labels = {v["label"] for v in spec["split"].values()}
                done["split"] = sync_positions(e, [x for x in e["positions"] if x["label"] in labels],
                                               reasoning_change="Renten auf beide Personen aufgeteilt.")
            done["positions"] = sync_positions(e, spec["positions"],
                                               reasoning_new="Einkommen der Partnerin oder des Partners erfasst.")
        done["shares"] = sync_shares(c)
        r = app("POST", f"/api/clients/{cid}/balance-sheet", json={"curator_id": CURATOR})
        missing = [m for m in (r.get("missing") or []) if m["group"] == "you"]
        done["missing"] = [f"{m['key']} ({m['name']})" if m.get("name") else m["key"] for m in missing]
        summary[c["name"]] = done
        log(f"{c['name']:<14} answers {len(done.get('answers', []))}; positions {done.get('positions', [])}"
            f"{'; split ' + str(done['split']) if done.get('split') else ''}; shares {len(done['shares'])}; "
            f"still missing: {done['missing'] or 'nothing'}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "use-cases-partners.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str),
                                                 encoding="utf-8")


def cmd_basis(args):
    """The nominal and real view's two answers (EIG-60, EIG-61), through the app's routes: each goal with an
    amount states whether the amount is in today's francs (``FUTURE_FRANCS`` names those that are not), and the
    onboarding's "Steigt der Betrag mit der Teuerung?" is answered (``INDEXED``); then one lbs run per client,
    the curator's button. Writes only what differs."""
    summary = {}
    for c in selected(args):
        cid = c["id"]
        done: dict[str, Any] = {}
        future = FUTURE_FRANCS.get(c["key"], ())
        changed = []
        for g in app("GET", f"/api/clients/{cid}/plan")["goals"]:
            if not g["active"] or g.get("target_amount") is None:
                continue
            want = "future" if any(g["name"].startswith(prefix) for prefix in future) else "today"
            if g.get("amount_basis") == want:
                continue
            app("PATCH", f"/api/clients/{cid}/goals/{g['id']}",
                json={"amount_basis": want, "reasoning": "Angegeben, ob der Betrag in heutigen Franken ist."})
            changed.append(f"{g['name'][:40]}: {want}")
        done["goals"] = changed
        done["answers"] = answer_all(cid, "onboarding", {"contribution_indexed": INDEXED[c["key"]]})
        r = call("POST", f"{APP}/api/clients/{cid}/balance-sheet", json={"curator_id": CURATOR}, ok=(200, 502, 503),
                 retries=0)
        views = (r or {}).get("views") or {}
        done["real_view"] = bool(views.get("available"))
        done["goals_real"] = {g.get("name"): (g.get("real") or {}).get("amount") for g in views.get("goals") or []}
        mandate = views.get("mandate") or {}
        done["required_return"] = {b: (mandate.get(b) or {}).get("required_return") for b in ("nominal", "real")}
        summary[c["name"]] = done
        log(f"{c['name']:<14} goals {changed or 'unchanged'}; indexed {INDEXED[c['key']]} "
            f"({'set' if done['answers'] else 'unchanged'}); real view {'yes' if done['real_view'] else 'NO'}; "
            f"required return {done['required_return']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "use-cases-basis.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str),
                                              encoding="utf-8")


def earning_answers(c):
    """The client's own earning-power answers and, with a partner in the plan, the partner's (EIG-65)."""
    spec = EARNING[c["key"]]
    want = dict(spec["own"])
    if c["key"] in EARNING_OF:
        o = by_key(EARNING_OF[c["key"]])
        other = EARNING[o["key"]]["own"]
        want.update({f"partner_{k}": v for k, v in other.items()})
        want["partner_kader"] = effective(o)["hc"]["kader"]
        want["partner_education_hours"], want["partner_education_budget"] = o["education_hours"], o["education_budget"]
    elif c["key"] in PARTNERS:
        want.update(spec["partner"])
    return want


def cmd_earning(args):
    """lbsim's earning-power answers for the 20 and their partners (EIG-65), through the app's routes; writes only
    what differs. The app then makes a new sheet by itself (lbs 1.4.0 reads the answers); ``mandates --refresh``
    presses the curator's button and lbsim follows each new sheet. Prints what the request now carries (read
    from the store, as the app builds it)."""
    summary = {}
    for c in selected(args):
        cid = c["id"]
        q = app("GET", f"/api/clients/{cid}/questionnaires/intake")
        if not {"income_expected_full", "partner_income_expected_full"} <= {x["key"] for x in q["questions"]}:
            raise RuntimeError(f"the intake is at version {q['version']}; run python -m eigentlich revise-content first")
        changed = answer_all(cid, "intake", earning_answers(c))
        with the_store().session() as conn:
            request, dropped = lbs_inputs.build(lbs_inputs.gather(conn, cid), date.today())
        persons = {p.person_id: (p.earning_power.model_dump(exclude_none=True) if p.earning_power else None)
                   for p in (request.household.persons if request.household else ())}
        facts = {k: v for k, v in request.facts.model_dump(mode="json").items()
                 if k not in ("canton", "civil_status", "has_no_liabilities") and v is not None}
        summary[c["name"]] = {"answered": changed, "earning_power": persons, "facts": facts, "dropped": dropped}
        level = "Ihre Angabe" if (persons.get("p1") or {}).get("expected_full_pensum_income") else "Modellwert"
        log(f"{c['name']:<14} answers {len(changed)}; principal {level}; persons {sorted(k for k, v in persons.items() if v)}; "
            f"facts {sorted(facts)}; dropped {dropped or 'nothing'}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "use-cases-earning.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str),
                                                encoding="utf-8")


def _latest_sheet(cid):
    with the_store().session() as conn:
        return conn.execute("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'lbs' AND status = "
                            "'succeeded' ORDER BY finished_at DESC LIMIT 1", (cid,)).fetchone()


def _lbsim_done(cid, sheet):
    with the_store().session() as conn:
        return conn.execute("SELECT 1 FROM engine_run WHERE client_id = %s AND engine = 'lbsim' AND status = 'succeeded' "
                            "AND request->>'life_balance_sheet_id' = %s LIMIT 1", (cid, sheet)).fetchone() is not None


def cmd_outlook(args):
    """lbsim's outlook for each client's newest sheet, asked as the curator (the cockpit's Parameters page asks the
    same after a base-Regime pcp run, C-34): the app's ``POST /api/clients/{c}/outlook`` with Nicolas's id, which
    builds the request from the sheet and the base-Regime Allocation of the current set and records the fast run
    and the plan run. Skipped where the newest sheet has its outlook already (lbsim followed the new sheet by
    itself), unless ``--refresh``."""
    summary = {}
    for c in selected(args):
        cid = c["id"]
        sheet = _latest_sheet(cid)
        if sheet is None:
            log(f"{c['name']:<14} no sheet: run mandates first")
            continue
        if args.refresh or not _lbsim_done(cid, sheet["artefact_id"]):
            page = call("POST", f"{APP}/api/clients/{cid}/outlook", json={"curator_id": CURATOR}, ok=(200,), retries=2)
        else:
            page = app("GET", f"/api/clients/{cid}/outlook")
        base = next((r for r in ((page.get("paths") or {}).get("regimes") or []) if r["key"] == "base"), None)
        designated = (page.get("paths") or {}).get("designated_goal_id")
        goal = next((g for g in (base or {}).get("goals") or [] if g["goal_id"] == designated), None)
        ep = page.get("earning_power") or []
        record = {"findings": len(page.get("findings") or []), "paths": page.get("paths") is not None,
                  "plan": (page.get("plan") or {}).get("state"),
                  "earning_power": [e.get("level_basis") for e in ep],
                  "goal": goal["name"] if goal else None, "chance_base": goal["chance"] if goal else None,
                  "chances": {r["label"]: {g["name"]: g["chance"] for g in r["goals"]}
                              for r in (page.get("paths") or {}).get("regimes") or []},
                  "no_allocation": page.get("no_allocation")}
        summary[c["name"]] = record
        log(f"{c['name']:<14} findings {record['findings']}; paths {record['paths']}; plan {record['plan']}; "
            f"earning {record['earning_power']}; {record['goal'] or '-'} {record['chance_base']}")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "use-cases-outlook.json"
    have = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    have.update(summary)
    path.write_text(json.dumps(have, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


# ------------------------------------------------------------------------------------------ the chain

def _presets():
    p = cockpit("GET", "/api/curator/presets")
    curves = {x["key"]: x for x in p["curves"]["body"]["presets"]}
    mandates = {x["key"]: x for x in p["mandates"]["body"]["presets"]}
    return curves, mandates, p["curves"]["version"], p["mandates"]["version"]


def curator_session(c):
    """C-10: the curator opened the client's material (once per day and client)."""
    with the_store().session() as conn:
        seen = conn.execute("SELECT 1 FROM curator_session WHERE client_id = %s AND curator_id = %s "
                            "AND opened_at::date = current_date", (c["id"], CURATOR)).fetchone()
    if not seen:
        cockpit("POST", f"/api/curator/clients/{c['id']}/sessions", json={"curator_id": CURATOR})


def lbs_now(c):
    """The curator's button: one lbs run through the app, recorded as Nicolas's; not pressed again while the
    latest sheet is newer than the client's latest change."""
    with the_store().session() as conn:
        row = conn.execute(
            "SELECT r.artefact_id FROM engine_run r WHERE r.client_id = %s AND r.engine = 'lbs' AND r.status = 'succeeded' "
            "AND r.requested_by_kind = 'curator' AND r.created_at >= greatest("
            "(SELECT max(created_at) FROM decision WHERE client_id = %s), (SELECT max(created_at) FROM answer WHERE client_id = %s)) "
            "ORDER BY r.finished_at DESC LIMIT 1", (c["id"], c["id"], c["id"])).fetchone()
    if row:
        return call("GET", f"{LBS}/artefacts/{row['artefact_id']}")
    r = cockpit("POST", f"/api/curator/clients/{c['id']}/balance-sheet", json={"curator_id": CURATOR})
    if r.get("error"):
        raise RuntimeError(f"{c['name']}: lbs: {r['error']}")
    aid = r["engine_run"]["artefact_id"]
    return call("GET", f"{LBS}/artefacts/{aid}")


def build_mandate(c, sheet, curves, mandates):
    ch = c["chain"]
    mp = mandates[ch["preset"]]
    cp = curves[mp["curve_preset"]]
    proposal = sheet.get("mandate_proposal") or {}
    form = cockpit("POST", "/api/curator/mandate/form", json={"mandate": {**mp["mandate"], "client": c["id"]}})
    kept, shift, adjusted_level = [], mp.get("curve_shift_pp") or 0.0, None
    if proposal.get("status") == "available":
        lbs_form = cockpit("POST", "/api/curator/mandate/form", json={"mandate": {
            "client": proposal["client"], "name": proposal["name"], "currency": proposal["currency"],
            "horizon_years": proposal["horizon_years"], "curve_unit": proposal["curve_unit"],
            "target_curve": proposal.get("target_curve") or [], "universe": proposal.get("universe") or [],
            "max_single_position": proposal.get("max_single_position"), "esg_min": proposal.get("esg_min") or 0,
            "fixed_allocations": proposal.get("fixed_allocations") or {},
            "bounds": {d: {k: {"lower": v["lower"], "upper": v["upper"]} for k, v in cats.items()}
                       for d, cats in (proposal.get("bounds") or {}).items()},
            "regime_weights": proposal.get("regime_weights"), "regime_market": proposal.get("regime_market")}})
        if proposal.get("currency"):
            form["currency"] = lbs_form["currency"]
            kept.append("Währung")
        if proposal.get("esg_min") is not None:
            form["esg_min"] = lbs_form["esg_min"]
            kept.append("ESG-Untergrenze")
        for dim in (proposal.get("bounds") or {}):
            form["bounds_pct"][dim] = lbs_form["bounds_pct"][dim]
            kept.append({"currency": "Währungsgrenzen", "liquidity": "Liquiditätsgrenzen",
                         "role": "Rollengrenzen"}.get(dim, dim))
        rr = proposal.get("required_return")
        if rr is not None and rr > 0:
            shift = round(rr * 100 - cp["mean_pct"], 2)
            kept.append(f"Kurvenniveau (verlangte Rendite {rr * 100:.2f} %)")
        elif rr is not None:
            # The goal is reached by saving alone: a curve levelled at 0 % would ask nothing of the portfolio.
            # The curator keeps the preset's level, which follows the house's view of the client's risk.
            adjusted_level = "Kurvenniveau der Vorlage beibehalten (das Ziel ist schon mit dem Sparen erreichbar)"
            kept.append("verlangte Rendite 0 % zur Kenntnis genommen")
    adjusted = [adjusted_level] if adjusted_level else []
    if ch["currency"] != form["currency"]:
        form["currency"] = ch["currency"]
        adjusted.append(f"Währung {ch['currency']}")
    if ch.get("currency_bounds"):
        form["bounds_pct"]["currency"] = {k: {"lower_pct": lo, "upper_pct": hi} for k, (lo, hi) in ch["currency_bounds"].items()}
        adjusted.append("Währungsgrenzen " + ", ".join(f"{k} ab {lo} %" for k, (lo, hi) in ch["currency_bounds"].items()))
    form["curve"] = {"base_pct": cp["points_pct"], "shift_pp": shift, "tilt_pp": mp.get("curve_tilt_pp") or 0.0,
                     "preset": cp["key"]}
    goal = next((g for g in c["goals"] if g["kind"] != "retirement" and g["target_amount"] and g["target_date"]), None)
    form["name"] = f"{mp['name']} ({form['currency']}): {goal['name'][:80] if goal else 'Vermögen'}"
    form["client"] = c["id"]
    return form, kept, adjusted, shift, mp, cp


def return_set(regime_id, currency):
    rs = cockpit("GET", "/api/fmre/v1/return-set", params={"regime_id": regime_id, "currency": currency,
                                                             "include_instruments": "true", "include_blocks": "false"})
    if (rs.get("provenance") or {}).get("regime_id") != regime_id:
        raise RuntimeError(f"fmre stamped {rs.get('provenance', {}).get('regime_id')} on {rs['return_set_id']}, not {regime_id}")
    return rs["return_set_id"]


def validate(mandate, regime_id, currency):
    rs = return_set(regime_id, currency)
    return cockpit("POST", "/api/pcp/validate", json={"regime_id": regime_id, "return_set_id": rs, "mandate": mandate})


ROLE_POOL: dict[str, list[str]] = {}


def _role_pool(mandates):
    """The house's own role classification of the instruments, as the presets carry it (universe_by_role)."""
    for mp in mandates.values():
        for role, ids in (mp.get("universe_by_role") or {}).items():
            pool = ROLE_POOL.setdefault(role, [])
            pool += [i for i in ids if i not in pool]


#: pcp 1.2.0's joint-feasibility check (PCP-21) names one smallest relaxation, row by row, e.g.
#: "asset_class Equity floor 0.2500 (row 41) misses by 0.0500".
RELAX_RE = r"(\w+) (.+?) (floor|ceiling) ([0-9.]+) \(row \d+\) misses by ([0-9.]+)"


def settle(c, form, trail):
    """Assemble the form into pcp's Mandate and check it with pcp's ``/validate`` until it passes. Where pcp
    refuses, the curator does what the Parameters page lets them do, and ``trail`` records it for the note:
    add an instrument for a role lbs puts a floor on but the preset's universe leaves empty; relax a row by the
    amount pcp's joint-feasibility message names (PCP-21); or, as a last resort, give up a policy bound of the
    house (never a bound of the household)."""
    import re
    mandate = cockpit("POST", "/api/curator/mandate/assemble", json=form)["mandate"]
    v = validate(mandate, BASE_REGIME, mandate["currency"])
    while not v["ok"]:
        missing, relax = [], []
        for problem in v["problems"]:
            m = re.search(r"role floor on \[(.*?)\], but no instrument of the universe", problem)
            if m:
                missing += [x.strip(" '").lower() for x in m.group(1).split(",")]
            if "infeasible as a whole" in problem:
                head = problem.split("One smallest relaxation:", 1)[-1].split("; at that point", 1)[0]
                relax += re.findall(RELAX_RE, head)
        loose = [d for d in POLICY_BOUND_DIMS if d in form["bounds_pct"]]
        if missing:
            for role in missing:
                extra = [i for i in ROLE_POOL.get(role, []) if i not in form["universe"]][:2]
                if not extra:
                    raise RuntimeError(f"{c['name']}: no instrument for the role {role}: {v['problems']}")
                form["universe"] += extra
                trail["added"].append(f"{role}: {', '.join(extra)}")
            log(f"  pcp: {v['problems'][:1]}; the universe gets {trail['added'][-len(missing):]}")
        elif relax and all(cat in (form["bounds_pct"].get(dim) or {}) for dim, cat, *_ in relax):
            for dim, cat, side, bound, miss in relax:
                row = form["bounds_pct"][dim][cat]
                step = float(miss) * 100 + 0.01          # just past pcp's smallest relaxation, in percent
                if side == "floor":
                    row["lower_pct"] = max(0.0, round(float(bound) * 100 - step, 2))
                    trail["relaxed"].append(f"{dim} {cat} Untergrenze auf {row['lower_pct']:.2f} %")
                else:
                    row["upper_pct"] = min(100.0, round(float(bound) * 100 + step, 2))
                    trail["relaxed"].append(f"{dim} {cat} Obergrenze auf {row['upper_pct']:.2f} %")
            log(f"  pcp: jointly infeasible; relaxed as pcp names it: {trail['relaxed'][-len(relax):]}")
        elif loose:
            form["bounds_pct"].pop(loose[-1])
            trail["dropped"].append(loose[-1])
            log(f"  pcp: {v['problems'][:2]}; the policy bound {loose[-1]} is left out")
        else:
            raise RuntimeError(f"{c['name']}: pcp refuses the mandate: {v['problems']}")
        mandate = cockpit("POST", "/api/curator/mandate/assemble", json=form)["mandate"]
        v = validate(mandate, BASE_REGIME, mandate["currency"])
    return mandate


def finalise(c, form, note, trail=None):
    """The Parameters page's save: the settled Mandate (``settle``) finalised as the client's parameter set
    unless the current one is the same, body and note (a note is part of what the curator finalises; the pages
    show it, so it names no ids)."""
    trail = trail if trail is not None else {"added": [], "dropped": [], "relaxed": []}
    mandate = settle(c, form, trail)
    current = cockpit("GET", f"/api/curator/clients/{c['id']}/parameter-sets")
    cur = next((p for p in current if p["current"]), None)
    if trail["added"]:
        note += " Universum ergänzt, weil lbs für jede Rolle eine Untergrenze setzt: " + "; ".join(trail["added"]) + "."
    if trail["relaxed"]:
        note += (" pcp fand die Grenzen zusammen nicht erfüllbar; gelockert, wie pcp es nennt: "
                 + "; ".join(trail["relaxed"]) + ".")
    if trail["dropped"]:
        note += " Ohne die Hausgrenzen " + ", ".join(trail["dropped"]) + ", die pcp mit den Haushaltsgrenzen nicht erfüllen konnte."
    if cur and cur["body"] == mandate and (cur.get("note") or "") == note:
        return cur, False
    row = cockpit("POST", f"/api/curator/clients/{c['id']}/parameter-sets",
                  json={"curator_id": CURATOR, "engine": "pcp", "contract_version": "pcp-mandate@1.0.0",
                        "body": mandate, "note": note})
    return row, True


def probe(c, mandate, regime_id, speed=None):
    """One solve in pcp's own store, not in the client's history (pcp caches by idempotency key, so a recorded
    run of the same mandate afterwards is the same solve): the allocation, or a RuntimeError naming pcp's
    reason."""
    rs = return_set(regime_id, mandate["currency"])
    body = {"regime_id": regime_id, "return_set_id": rs, "mandate": mandate, **({"speed_mode": speed} if speed else {})}
    answer = call("POST", f"{PCP}/run", json=body)
    for _ in range(120):
        if answer.get("status") in ("succeeded", "failed") or not answer.get("run_id"):
            break
        time.sleep(3)
        answer = call("GET", f"{PCP}/runs/{answer['run_id']}")
    if answer.get("status") != "succeeded":
        detail = call("GET", f"{PCP}/runs/{answer['run_id']}").get("error") if answer.get("run_id") else None
        raise RuntimeError(f"{c['name']}: pcp run failed (probe): {detail or answer}")
    return call("GET", f"{PCP}/artefacts/{answer['artefact_id']}")


def expected_pct(allocation, curve="achieved"):
    """A pcp curve (per state, log returns) as one yearly figure in percent: weighted by the Regime's state
    blend, as pcp weights the states in its objective (LBS-11)."""
    import math
    w, x = allocation["curves"]["regime"], allocation["curves"][curve]
    return sum(wi * math.expm1(xi) for wi, xi in zip(w, x)) / sum(w) * 100


#: The curator's judgement on a required return (fix round, 29.09.2026): lbs calls a goal feasible whenever its
#: search finds a return below its ceiling, however high. When the required return lies more than this many
#: points above what pcp's allocation within the household's bounds is expected to earn under the Default
#: Regime, the curator levels the curve at that expected return instead (rounded down to 0.1 point), and the
#: gap is left to the levers lbs names: the horizon, the saving, the goal's size.
REALISM_MARGIN_PP = 1.0
MANDATE_LOG: dict[str, dict[str, Any]] = {}


def run_pcp(c, pset, regime_id, policy=None, speed=None):
    currency = pset["body"]["currency"]
    rs = return_set(regime_id, currency)
    with the_store().session() as conn:
        done = conn.execute("SELECT id, artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                            "AND status = 'succeeded' AND parameter_set_id = %s AND request->>'regime_id' = %s "
                            "AND request->>'return_set_id' = %s",
                            (c["id"], pset["id"], regime_id, rs)).fetchone()
    if done:
        return done["artefact_id"], False
    # A probe in pcp's own store first: an unconverged attempt is then not written into the client's history.
    probe(c, pset["body"], regime_id, speed)
    body = {"curator_id": CURATOR, "engine": "pcp", "parameter_set_id": pset["id"], "regime_id": regime_id,
            "return_set_id": rs, "currency": currency, "optimism": OPTIMISM}
    if policy:
        body.update(regime_policy=policy, base_regime_id=BASE_REGIME)
    if speed:
        body["speed_mode"] = speed
    row = cockpit("POST", f"/api/curator/clients/{c['id']}/runs", json=body)
    for _ in range(120):
        if row["status"] in ("succeeded", "failed"):
            break
        time.sleep(5)
        row = cockpit("POST", f"/api/curator/runs/{row['id']}/refresh")
    if row["status"] != "succeeded":
        raise RuntimeError(f"{c['name']}: pcp run {row['status']}: {row.get('error')}")
    return row["artefact_id"], True


def check_regimes():
    """The cockpit's own choice of Regime (C-30) must be the one this build names, for the base and each scenario."""
    base = cockpit("GET", "/api/curator/regime", params={"optimism": OPTIMISM})
    if base["regime_id"] != BASE_REGIME:
        sys.exit(f"the cockpit chooses {base['regime_id']} at optimism {OPTIMISM}, not {BASE_REGIME}")
    for policy, rid in SCENARIOS.items():
        s = cockpit("GET", "/api/curator/regime", params={"optimism": OPTIMISM, "policy": policy})
        if s["regime_id"] != rid or s["base_regime_id"] != BASE_REGIME:
            sys.exit(f"the cockpit derives {policy} as {s['regime_id']} from {s['base_regime_id']}, not {rid}")
    log(f"Regime {BASE_REGIME} (optimism {OPTIMISM}); scenarios " + ", ".join(f"{k} {v}" for k, v in SCENARIOS.items()))


def realistic(c, form, trail, rr, cp):
    """The curator's check of a required return above zero: the expected return of pcp's allocation under the
    Default Regime for the curve lbs's required return asks (a probe, not recorded). Returns the shift to use and
    a note when the curve is set lower (``REALISM_MARGIN_PP``), and what was seen."""
    alloc = probe(c, settle(c, form, trail), BASE_REGIME)
    reach = expected_pct(alloc)
    seen = {"required_pct": round(rr * 100, 2), "reachable_pct": round(reach, 2),
            "probe_roles": {k: round(v, 3) for k, v in alloc["weights_by_role"].items()}}
    if rr * 100 <= reach + REALISM_MARGIN_PP:
        return None, None, seen
    level = int(reach * 10) / 10.0
    shift = round(level - cp["mean_pct"], 2)
    seen["level_pct"] = level
    note = (f"Die verlangte Rendite von {rr * 100:.2f} % liegt über dem, was ein Portfolio in den Grenzen des Haushalts "
            f"unter dem Default-Regime erwarten lässt (etwa {reach:.1f} %). Die Kurve ist darum auf {level:.1f} % gesetzt; "
            "die Lücke schliessen der Zeithorizont, der Sparbetrag oder die Höhe des Ziels, nicht die Anlage.")
    return shift, note, seen


def _allocation(aid, regime_id):
    art = call("GET", f"{PCP}/artefacts/{aid}")
    return {"artefact": aid, "regime": regime_id, "return_set": art["return_set_id"],
            "pcp": (art.get("provenance") or {}).get("engine_version"),
            "roles": {k: round(v, 3) for k, v in art["weights_by_role"].items()},
            "expected_pct": round(expected_pct(art), 2), "target_pct": round(expected_pct(art, "target"), 2),
            "instruments": sum(1 for i in art["instruments"] if i["weight"] > 0.005),
            "top": [(i["name"], round(i["weight"], 3)) for i in sorted(art["instruments"], key=lambda i: -i["weight"])[:4]]}


def cmd_mandates(args):
    check_regimes()
    curves, mandates, cv, mv = _presets()
    _role_pool(mandates)
    for c in selected(args):
        wanted = {BASE_REGIME} | ({SCENARIOS[c["chain"]["scenario"]]} if c["chain"].get("scenario") else set())
        if not args.refresh:
            with the_store().session() as conn:
                pset = conn.execute("SELECT id FROM parameter_set_current WHERE client_id = %s AND engine = 'pcp'",
                                    (c["id"],)).fetchone()
                regimes = {r["regime"] for r in conn.execute(
                    "SELECT request->>'regime_id' AS regime FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                    "AND status = 'succeeded' AND parameter_set_id = %s", (c["id"], pset["id"] if pset else "")).fetchall()}
            if pset and wanted <= regimes:
                log(f"{c['name']:<14} mandate finalised and run: kept (--refresh to derive it again)")
                continue
        curator_session(c)
        sheet = lbs_now(c)
        gaps = [f"{g['section']}:{g['input']}" for g in sheet.get("gaps") or []]
        form, kept, adjusted, shift, mp, cp = build_mandate(c, sheet, curves, mandates)
        prop = sheet.get("mandate_proposal") or {}
        rr = prop.get("required_return")
        trail = {"added": [], "dropped": [], "relaxed": []}
        record = {"lbs": sheet["artefact_id"], "required_return_pct": round(rr * 100, 2) if rr is not None else None,
                  "feasible_lbs": prop.get("feasible"), "preset": mp["key"], "curve_preset": cp["key"]}
        judgement = None
        if rr is not None and rr > 0:
            new_shift, judgement, seen = realistic(c, form, trail, rr, cp)
            record.update(seen)
            if new_shift is not None:
                shift = new_shift
                form["curve"]["shift_pp"] = shift
                kept = [k for k in kept if not k.startswith("Kurvenniveau")]
                kept.append(f"verlangte Rendite {rr * 100:.2f} % zur Kenntnis genommen")
                log(f"  {c['name']}: required {rr * 100:.2f} %, reachable about {seen['reachable_pct']:.2f} %: "
                    f"the curve is set at {seen['level_pct']:.1f} %")
        record["shift_pp"] = shift
        note = (f"Vorlage «{mp['name']}» (Vorlagen v{mv}), Kurve «{cp['name']}» um {shift:+.2f} Prozentpunkte verschoben. "
                f"Von lbs übernommen: {', '.join(kept) or 'nichts'}."
                + (f" Angepasst: {'; '.join(adjusted)}." if adjusted else "")
                + (f" {judgement}" if judgement else "")
                + f" Gerechnet auf dem Default-Regime (Optimismus-Stufe «{OPTIMISM}»).")
        loosened = []
        while True:
            pset, new = finalise(c, form, note + (" Nach einem nicht konvergierten Lauf ohne die Hausgrenzen "
                                                  + ", ".join(loosened) + "." if loosened else ""), trail)
            runs, allocations = [], {}
            try:
                todo = ([(SCENARIOS[c["chain"]["scenario"]], c["chain"]["scenario"])] if c["chain"].get("scenario") else [])
                # The base run last: the app's report takes the client's latest succeeded pcp run.
                for regime_id, pol in todo + [(BASE_REGIME, None)]:
                    try:
                        aid, fresh = run_pcp(c, pset, regime_id, pol)
                    except RuntimeError as exc:
                        if "did not converge" not in str(exc):
                            raise
                        log(f"  {c['name']}: {str(exc)[:100]}; run again in pcp's exact mode")
                        aid, fresh = run_pcp(c, pset, regime_id, pol, speed="exact")
                    runs.append(f"{pol or 'base'}:{aid}{'' if fresh else ' (had)'}")
                    allocations[pol or "base"] = _allocation(aid, regime_id)
                break
            except RuntimeError as exc:
                loose = [d for d in POLICY_BOUND_DIMS if d in form["bounds_pct"]]
                if "did not converge" not in str(exc) or not loose:
                    raise
                # The curator reads the failed run and gives up the house's bound that fights the household's.
                loosened.append(loose[-1])
                form["bounds_pct"].pop(loose[-1])
                log(f"  {c['name']}: {str(exc)[:120]}; the policy bound {loose[-1]} is left out and the set finalised again")
        record.update(parameter_set=pset["id"], new_set=new, trail=trail, loosened=loosened, runs=allocations,
                      currency=pset["body"]["currency"], note=note)
        MANDATE_LOG[c["name"]] = record
        log(f"{c['name']:<14} lbs {sheet['artefact_id']} rr={rr} feasible={prop.get('feasible')} "
            f"gaps={len(gaps)} | set {'new' if new else 'kept'} {pset['id'][:8]} | {' '.join(runs)}")
        if args.verbose:
            print("   gaps:", gaps)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "use-cases-mandates.json"
        have = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        have[c["name"]] = record
        path.write_text(json.dumps(have, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


# --------------------------------------------------------------------------------------------- threads

def _thread_by_question(cid, question):
    for t in app("GET", f"/api/clients/{cid}/threads"):
        full = app("GET", f"/api/clients/{cid}/threads/{t['id']}")
        msgs = full["messages"]
        if msgs and msgs[0]["author_kind"] == "client" and msgs[0]["body"] == question:
            return full
    return None


def _wait_answers(pending, timeout=2400):
    """pending: list of (client, thread_id, n_client_messages). Waits until each has a MiniMind answer to its last
    client message; a failed draft is tried again once."""
    t0, retried = time.time(), set()
    while pending and time.time() - t0 < timeout:
        rest = []
        for c, tid in pending:
            t = app("GET", f"/api/clients/{c['id']}/threads/{tid}")
            last = t["messages"][-1]
            if last["author_kind"] != "client":
                continue
            d = t.get("draft") or {}
            if d.get("state") == "failed":
                if tid in retried:
                    log(f"  {c['name']}: draft failed twice: {d.get('error')}")
                    continue
                retried.add(tid)
                log(f"  {c['name']}: draft failed ({(d.get('error') or '')[:120]}); trying again")
                app("POST", f"/api/clients/{c['id']}/threads/{tid}/draft")
            elif not d or d.get("state") == "done":
                app("POST", f"/api/clients/{c['id']}/threads/{tid}/draft")
            rest.append((c, tid))
        pending = rest
        if pending:
            time.sleep(15)
    return pending


def cmd_threads(args):
    """Each client asks; MiniMind drafts (in the app's background jobs, a few at a time); a follow-up where given."""
    todo = []
    for c in selected(args):
        for spec in c["chain"]["threads"]:
            t = _thread_by_question(c["id"], spec["q"])
            if t is None:
                r = app("POST", f"/api/clients/{c['id']}/threads", json={"question": spec["q"], "language": "de"})
                todo.append((c, r["thread_id"]))
                log(f"{c['name']:<14} asked «{spec['q'][:60]}…»")
                time.sleep(2)
            elif t["messages"][-1]["author_kind"] == "client":
                todo.append((c, t["id"]))
        if len(todo) >= args.batch:
            left = _wait_answers(todo)
            todo = left
    left = _wait_answers(todo)
    for c, tid in left:
        log(f"  no answer yet: {c['name']} {tid}")
    # follow-ups
    todo = []
    for c in selected(args):
        for spec in c["chain"]["threads"]:
            if not spec.get("followup"):
                continue
            t = _thread_by_question(c["id"], spec["q"])
            if t and not any(m["author_kind"] == "client" and m["body"] == spec["followup"] for m in t["messages"]):
                app("POST", f"/api/clients/{c['id']}/threads/{t['id']}/messages", json={"body": spec["followup"]})
                todo.append((c, t["id"]))
    _wait_answers(todo)
    # The questions MiniMind refused in the first build (care, incapacity, inheritance) are asked again, as
    # first asked, in their own threads (fix round: MiniMind 1.2.0's wider domain); the earlier turns stay.
    todo = []
    for c in selected(args):
        for spec in c["chain"]["threads"]:
            if not spec.get("reask"):
                continue
            t = _thread_by_question(c["id"], spec["q"])
            if t is None or t.get("closed_at"):
                log(f"{c['name']:<14} «{spec['key']}»: {'no thread' if t is None else 'the thread is closed'}")
                continue
            if not any(m["author_kind"] == "client" and m["body"] == spec["q"] for m in t["messages"][1:]):
                app("POST", f"/api/clients/{c['id']}/threads/{t['id']}/messages", json={"body": spec["q"]})
                log(f"{c['name']:<14} asked again «{spec['q'][:60]}…»")
                todo.append((c, t["id"]))
            elif t["messages"][-1]["author_kind"] == "client":
                todo.append((c, t["id"]))
    for c, tid in _wait_answers(todo):
        log(f"  no answer yet: {c['name']} {tid}")


def cmd_curate(args):
    """The curator answers where the use case says so; answer approvals are asked by the client and decided."""
    for c in selected(args):
        for spec in c["chain"]["threads"]:
            t = _thread_by_question(c["id"], spec["q"])
            if t is None:
                continue
            spark = [m for m in t["messages"] if m["author_kind"] == "spark7"]
            if spec.get("curator") and not any(m["author_kind"] == "curator" and m["body"] == spec["curator"]
                                               for m in t["messages"]):
                cockpit("POST", f"/api/curator/threads/{t['id']}/messages",
                        json={"curator_id": CURATOR, "body": spec["curator"], "close": bool(spec.get("close"))})
                log(f"{c['name']:<14} curator answered «{spec['key']}»")
            if spec.get("client_close") and t.get("closed_at") is None:
                app("POST", f"/api/clients/{c['id']}/threads/{t['id']}/close")
            wanted = spec.get("approval")
            if not wanted or not spark:
                continue
            item = spark[0]
            if item.get("approval") is None:
                a = app("POST", f"/api/clients/{c['id']}/approvals",
                        json={"item": "answer", "item_id": item["id"],
                              "note": "Bitte prüfen, bevor ich danach handle."})
            else:
                a = item["approval"]
            state = a.get("state") or "awaiting_curator"
            if state != "awaiting_curator":
                continue
            if wanted == "approved":
                cockpit("POST", f"/api/curator/approvals/{a['id']}/approve",
                        json={"curator_id": CURATOR, "note": "Geprüft: die Antwort trifft auf Ihre Lage zu."})
            elif wanted == "revision_sent":
                cockpit("POST", f"/api/curator/approvals/{a['id']}/revise",
                        json={"curator_id": CURATOR, "note": "Präzisiert: die Regeln beim Wegzug in die EU.",
                              "body": spec["revision"]})
            log(f"{c['name']:<14} answer approval: {wanted}")


# --------------------------------------------------------------------------------------------- reports

def _requests(cid, kind):
    return [r for r in app("GET", f"/api/clients/{cid}/reports") if r["kind"] == kind]


def _wait_reports(pending, timeout=3600):
    t0 = time.time()
    while pending and time.time() - t0 < timeout:
        rest = []
        for c, rid in pending:
            q = next(r for r in app("GET", f"/api/clients/{c['id']}/reports") if r["id"] == rid)
            if q["state"] == "fulfilled":
                log(f"{c['name']:<14} {q['kind']} ready")
                continue
            job = q.get("job") or {}
            if job.get("state") == "failed" or not job:
                log(f"  {c['name']}: {q['kind']} not produced ({(job.get('error') or 'no job')[:160]}); trying again")
                app("POST", f"/api/clients/{c['id']}/reports/{rid}/produce")
            rest.append((c, rid))
        pending = rest
        if pending:
            time.sleep(20)
    return pending


REPORT_NOTE = "Mein Gesamtbild: Ziele, Weiterbildung, Gesundheit und was der Plan dazu sagt."


def page(c, report_id):
    """A report's page as the app serves it (HTML)."""
    r = http.get(f"{APP}/api/clients/{c['id']}/report/{report_id}/html")
    r.raise_for_status()
    return r.text


def cmd_reports(args):
    """A report per client. With ``--refresh`` (the fix round): a new report request for every client none of
    whose reports rests on the allocation of its latest succeeded pcp run, so the report rests on the current
    sheet and allocation; the earlier reports and their approvals stay."""
    todo = []
    for c in selected(args):
        reqs = _requests(c["id"], "report")
        stale = False
        if args.refresh and reqs:
            with the_store().session() as conn:
                pcp = conn.execute("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                                   "AND status = 'succeeded' ORDER BY finished_at DESC LIMIT 1", (c["id"],)).fetchone()
            made = {r["allocation_artefact_id"] for q in reqs for r in q["reports"]}
            stale = pcp is not None and pcp["artefact_id"] not in made
            # lbsim (EIG-69): a report that draws on the outlook of the newest sheet (its findings and paths)
            stale = stale or not _report_has_outlook(c["id"])
        if not reqs or stale:
            note = REFRESH_NOTE if stale else REPORT_NOTE
            r = app("POST", f"/api/clients/{c['id']}/reports", json={"kind": "report", "language": "de", "note": note})
            todo.append((c, r["request_id"]))
            log(f"{c['name']:<14} report requested{' (on the new sheet and allocation)' if stale else ''}")
        elif reqs[0]["state"] == "open":
            todo.append((c, reqs[0]["id"]))
        if len(todo) >= args.batch:
            todo = _wait_reports(todo)
    for c, rid in _wait_reports(todo):
        log(f"  no report yet: {c['name']} {rid}")


def _report_has_outlook(cid):
    """Whether one of the client's reports drew on lbsim's findings of the newest sheet (the report engine_run's
    sources, as the app sent them), and on lbsim's newest paths when there are any: a new lbsim calibration makes
    new paths for the same sheet, and the report then rests on the old ones."""
    sheet = _latest_sheet(cid)
    if sheet is None:
        return True
    with the_store().session() as conn:
        found = conn.execute(
            "SELECT e.request FROM engine_run e JOIN report r ON r.report_artefact_id = e.artefact_id AND r.client_id = e.client_id "
            "WHERE e.client_id = %s AND e.engine = 'report' AND e.status = 'succeeded' ORDER BY e.finished_at DESC",
            (cid,)).fetchall()
        newest = conn.execute(
            "SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'lbsim' AND status = 'succeeded' "
            "AND artefact_id LIKE 'LSP-%%' ORDER BY finished_at DESC LIMIT 1", (cid,)).fetchone()
    paths = newest["artefact_id"] if newest else None
    for row in found:
        sources = (row["request"] or {}).get("sources") or []
        if any(s.get("engine") == "lbs" and s.get("artefact_id") == sheet["artefact_id"] for s in sources) and \
                any(s.get("engine") == "lbsim" for s in sources) and \
                (paths is None or any(s.get("artefact_id") == paths for s in sources)):
            return True
    return False


REFRESH_NOTE = ("Bitte ein neues Gesamtbild: mit meiner Partnerin oder meinem Partner, den Anteilen am Sparbetrag und "
                "der neuen Aufteilung.")
REVISION_NOTE = ("Überarbeitet mit dem nachgeführten Plan: Der Erbvorbezug an Andrea und Martin ist auf je 80 000 "
                 "gesenkt, damit der Pflichtteil von Hans unberührt bleibt, und die Aufteilung ist neu gerechnet. "
                 "Bitte lesen Sie diese Fassung; die erste Überarbeitung glich der ersten Fassung.")


def cmd_revision(args):
    """The report revision that was a copy (Regula, first build): the report engine answered the second
    production of the same request from its cache. Regula asks for approval of that copy; the curator sends a
    real revision (report 1.2.0: ``revision_of``, ``revision_note``, EIG-57) and names it in the event."""
    for c in selected(args):
        if c["chain"].get("report_approval") != "revision_sent":
            continue
        req = [r for r in _requests(c["id"], "report") if r["state"] == "fulfilled"][-1]      # the first
        reps = sorted(req["reports"], key=lambda r: r["seq"])
        if len(reps) >= 3:
            log(f"{c['name']:<14} revision: done ({len(reps)} reports in the request)")
            continue
        if len(reps) < 2:
            log(f"{c['name']:<14} revision: the first revision is not there yet (run approvals)")
            continue
        html = [page(c, r["id"]) for r in reps]
        copy = reps[1]
        if html[0] != html[1]:
            log(f"{c['name']:<14} revision: the first revision differs already; nothing to do")
            continue
        a = copy.get("approval") or app("POST", f"/api/clients/{c['id']}/approvals",
                                        json={"item": "report", "item_id": copy["id"],
                                              "note": "Die überarbeitete Fassung gleicht der ersten. Bitte prüfen Sie sie noch einmal."})
        app("POST", f"/api/clients/{c['id']}/reports/{req['id']}/produce", params={"revision": "true", "wait": "true"},
            json={"revision_note": REVISION_NOTE, "revision_of": copy["id"]})
        again = next(r for r in _requests(c["id"], "report") if r["id"] == req["id"])
        newest = max(again["reports"], key=lambda r: r["seq"])
        assert newest["id"] != copy["id"], "the revision is a new report"
        new_html = page(c, newest["id"])
        if new_html == html[1]:
            raise RuntimeError(f"{c['name']}: the revision is again a copy")
        if (a.get("state") or "awaiting_curator") == "awaiting_curator":
            cockpit("POST", f"/api/curator/approvals/{a['id']}/revise",
                    json={"curator_id": CURATOR, "revision_item_id": newest["id"],
                          "note": "Neu erstellt mit dem nachgeführten Plan und meiner Anmerkung; bitte die neue Fassung lesen."})
        log(f"{c['name']:<14} revision sent: {newest['id']} (note {'shown' if 'Pflichtteil von Hans' in new_html else 'NOT shown'})")


def apply_update(c):
    u = c["chain"]["update"]
    cid = c["id"]
    if u.get("positions"):
        plan = app("GET", f"/api/clients/{cid}/plan")
        for label, change in u["positions"].items():
            row = next((p for p in plan["positions"] if p["label"] in (label, change.get("label")) and p["active"]), None)
            if row is None:
                raise RuntimeError(f"{c['name']}: no position {label}")
            diff = {k: v for k, v in change.items() if row.get(k) != v}
            if "magnitude" in diff:
                diff["magnitude_unit"] = row["magnitude_unit"]
                if row["magnitude_unit"] == "chf":
                    diff["stock_kind"] = row["stock_kind"]
            if diff:
                diff["reasoning"] = u["note"]
                app("PATCH", f"/api/clients/{cid}/positions/{row['id']}", json=diff)
    if u.get("goals"):
        plan = app("GET", f"/api/clients/{cid}/plan")
        for name, change in u["goals"].items():
            row = next((g for g in plan["goals"] if g["name"] in (name, change.get("name")) and g["active"]), None)
            if row is None:
                raise RuntimeError(f"{c['name']}: no goal {name}")
            diff = {k: v for k, v in change.items() if row.get(k) != v}
            if diff:
                diff["reasoning"] = u["note"]
                app("PATCH", f"/api/clients/{cid}/goals/{row['id']}", json=diff)
    if u.get("positions_new"):
        sync_positions(c, u["positions_new"], reasoning_new=u["note"])
    if u.get("onb") or u.get("hc"):
        want = dict(u.get("onb") or {})
        want.update(u.get("hc") or {})
        answer_all(cid, "onboarding", want)
        restate_facts(c, want)
    if u.get("intake"):
        answer_all(cid, "intake", u["intake"])


def cmd_updates(args):
    todo = []
    for c in selected(args):
        if not c["chain"].get("update"):
            continue
        if not any(r["state"] == "fulfilled" for r in _requests(c["id"], "report")):
            log(f"{c['name']:<14} no report yet: the update waits")
            continue
        reqs = _requests(c["id"], "update")
        if not reqs:
            apply_update(c)
            time.sleep(7)          # the automatic lbs run after the change (debounced 5 s)
            r = app("POST", f"/api/clients/{c['id']}/reports",
                    json={"kind": "update", "language": "de", "note": c["chain"]["update"]["note"]})
            todo.append((c, r["request_id"]))
            log(f"{c['name']:<14} change applied, update requested")
        elif reqs[0]["state"] == "open":
            todo.append((c, reqs[0]["id"]))
    for c, rid in _wait_reports(todo):
        log(f"  no update yet: {c['name']} {rid}")


def cmd_approvals(args):
    """Report and update approvals: asked by the client in the app, decided by the curator in the cockpit (or
    withdrawn by the client, or left waiting)."""
    for c in selected(args):
        ch = c["chain"]
        plans = []
        if ch.get("report_approval"):
            plans.append(("report", ch["report_approval"]))
        if (ch.get("update") or {}).get("approval"):
            plans.append(("update", ch["update"]["approval"]))
        for kind, wanted in plans:
            # The first request of its kind carries the approval (the app lists the newest first; later reports,
            # such as the fix round's, are asked without one).
            reqs = [r for r in _requests(c["id"], kind) if r["state"] == "fulfilled"][::-1]
            if not reqs:
                log(f"{c['name']:<14} no {kind} to approve yet")
                continue
            first = sorted(reqs[0]["reports"], key=lambda r: r["seq"])[0]
            a = first.get("approval") or app("POST", f"/api/clients/{c['id']}/approvals",
                                             json={"item": kind, "item_id": first["id"],
                                                   "note": "Bitte prüfen Sie den Bericht, bevor ich ihn mit meiner Bank bespreche."})
            if a.get("state", "awaiting_curator") != "awaiting_curator":
                continue
            if wanted == "approved":
                cockpit("POST", f"/api/curator/approvals/{a['id']}/approve",
                        json={"curator_id": CURATOR, "note": "Geprüft und freigegeben."})
            elif wanted == "withdrawn":
                app("POST", f"/api/clients/{c['id']}/approvals/{a['id']}/withdraw")
            elif wanted == "revision_sent":
                app("POST", f"/api/clients/{c['id']}/reports/{reqs[0]['id']}/produce",
                    params={"revision": "true", "wait": "true"})
                again = next(r for r in _requests(c["id"], kind) if r["id"] == reqs[0]["id"])
                newest = max(again["reports"], key=lambda r: r["seq"])
                assert newest["id"] != first["id"], "the revision is a new report"
                cockpit("POST", f"/api/curator/approvals/{a['id']}/revise",
                        json={"curator_id": CURATOR, "revision_item_id": newest["id"],
                              "note": "Neu erstellt mit dem nachgeführten Plan; bitte die neue Fassung lesen."})
            log(f"{c['name']:<14} {kind} approval: {wanted}")


# --------------------------------------------------------------------------------------------- checks

#: Signs of text decoded in the wrong code page (EIG-46): UTF-8 read as Latin-1 or CP437, or a lost character.
GARBLED = ("Ã", "â€", "├", "┬", "�")
TEXT_COLUMNS = (("decision", "reasoning"), ("thread_message", "body"), ("thread", "subject"), ("goal", "name"),
                ("position", "label"), ("position", "description"), ("parameter_set", "note"), ("report", "body_html"),
                ("household_member", "label"), ("client", "display_name"), ("approval_request", "note"),
                ("approval_event", "note"), ("report_request", "note"))


def cmd_check(args):
    """Counts; per client a current sheet, a parameter set, a succeeded pcp run of the current set on the Default
    Regime with the ReturnSet fmre serves now (and on the client's scenario), a report on the latest allocation;
    no garbled text; the scoring binds."""
    st = the_store()
    out = {"regime": BASE_REGIME, "scenarios": SCENARIOS}
    sets = {cur: return_set(BASE_REGIME, cur) for cur in ("CHF", "EUR", "USD")}
    scen_sets = {}
    with st.session() as conn:
        out["counts"] = store.table_counts(conn)
        rows = []
        for c in CLIENTS:
            cid = c["id"]
            q = lambda sql, *p: conn.execute(sql, (cid, *p)).fetchone()  # noqa: E731
            changed = conn.execute("SELECT greatest((SELECT max(created_at) FROM decision WHERE client_id = %s), "
                                   "(SELECT max(created_at) FROM answer WHERE client_id = %s)) AS at",
                                   (cid, cid)).fetchone()["at"]
            lbs = q("SELECT artefact_id, created_at, finished_at FROM engine_run WHERE client_id = %s AND engine = 'lbs' "
                    "AND status = 'succeeded' ORDER BY finished_at DESC LIMIT 1")
            pset = q("SELECT id, body->>'currency' AS currency FROM parameter_set_current WHERE client_id = %s AND engine = 'pcp'")
            base = scen = None
            if pset:
                base = q("SELECT artefact_id, finished_at FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                         "AND status = 'succeeded' AND parameter_set_id = %s AND request->>'regime_id' = %s "
                         "AND request->>'return_set_id' = %s ORDER BY finished_at DESC LIMIT 1",
                         pset["id"], BASE_REGIME, sets[pset["currency"]])
                pol = c["chain"].get("scenario")
                if pol:
                    key = (pol, pset["currency"])
                    scen_sets.setdefault(key, return_set(SCENARIOS[pol], pset["currency"]))
                    scen = q("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                             "AND status = 'succeeded' AND parameter_set_id = %s AND request->>'regime_id' = %s "
                             "AND request->>'return_set_id' = %s LIMIT 1", pset["id"], SCENARIOS[pol], scen_sets[key])
            latest_pcp = q("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' AND status = 'succeeded' "
                           "ORDER BY finished_at DESC LIMIT 1")
            report = q("SELECT id, allocation_artefact_id, lbs_artefact_id, created_at FROM report WHERE client_id = %s "
                       "ORDER BY seq DESC LIMIT 1")
            rows.append({
                "client": c["name"],
                "lbs_current": bool(lbs and lbs["created_at"] >= changed),
                "lbs": lbs["artefact_id"] if lbs else None,
                "parameter_set": pset["id"] if pset else None,
                "pcp_default_regime": base["artefact_id"] if base else None,
                "scenario": c["chain"].get("scenario"),
                "pcp_scenario": scen["artefact_id"] if scen else None,
                "latest_pcp_is_base": bool(base and latest_pcp and latest_pcp["artefact_id"] == base["artefact_id"]),
                "report_on_it": bool(report and base and report["allocation_artefact_id"] == base["artefact_id"]),
                "pcp_succeeded": q("SELECT count(*) AS n FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                                   "AND status = 'succeeded'")["n"],
                "reports": q("SELECT count(*) AS n FROM report WHERE client_id = %s")["n"],
                "threads": q("SELECT count(*) AS n FROM thread WHERE client_id = %s")["n"],
                "approvals": q("SELECT count(*) AS n FROM approval_request WHERE client_id = %s")["n"],
                "failed_runs": q("SELECT count(*) AS n FROM engine_run WHERE client_id = %s AND status = 'failed'")["n"],
            })
        out["clients"] = rows
        ids = [c["id"] for c in CLIENTS]
        garbled = {}
        for table, col in TEXT_COLUMNS:
            key = "id" if table == "client" else "client_id"
            if table in ("thread_message", "approval_event"):
                continue
            # A decision is append-only: a garbled one counts only while no correcting decision names it (EIG-46).
            live = " AND NOT EXISTS (SELECT 1 FROM decision k WHERE k.corrects_id = decision.id)" if table == "decision" else ""
            n = conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {key} = ANY(%s){live} AND ("
                             + " OR ".join(f"{col} LIKE %s" for _ in GARBLED) + ")",
                             (ids, *[f"%{g}%" for g in GARBLED])).fetchone()["n"]
            garbled[f"{table}.{col}"] = n
        for table, join in (("thread_message", "JOIN thread t ON t.id = x.thread_id WHERE t.client_id = ANY(%s)"),
                            ("approval_event", "JOIN approval_request a ON a.id = x.request_id WHERE a.client_id = ANY(%s)")):
            col = "body" if table == "thread_message" else "note"
            garbled[f"{table}.{col}"] = conn.execute(
                f"SELECT count(*) AS n FROM {table} x {join} AND (" + " OR ".join(f"x.{col} LIKE %s" for _ in GARBLED) + ")",
                (ids, *[f"%{g}%" for g in GARBLED])).fetchone()["n"]
        answers = conn.execute("SELECT value::text AS v FROM answer WHERE client_id = ANY(%s)", (ids,)).fetchall()
        garbled["answer.value"] = sum(1 for a in answers if any(g in json.loads(a["v"]).__str__() for g in GARBLED))
        out["garbled"] = garbled
        out["bind_mismatches"] = conn.execute("SELECT count(*) AS n FROM scoring_bind_check WHERE status <> 'ok'").fetchone()["n"]
        out["approval_states"] = {r["state"]: r["n"] for r in conn.execute(
            "SELECT state, count(*) AS n FROM approval_state GROUP BY state").fetchall()}
        out["thread_states"] = {r["state"]: r["n"] for r in conn.execute(
            "SELECT state, count(*) AS n FROM thread_state GROUP BY state").fetchall()}
        out["basis"] = {str(r["basis"]): r["n"] for r in conn.execute(
            "SELECT basis, count(*) AS n FROM thread_message WHERE author_kind = 'spark7' GROUP BY basis").fetchall()}
        out["refusals_unanswered"] = conn.execute(
            "SELECT count(*) AS n FROM thread_message m WHERE m.author_kind = 'spark7' AND m.body LIKE %s AND NOT EXISTS "
            "(SELECT 1 FROM thread_message l WHERE l.thread_id = m.thread_id AND l.seq > m.seq AND l.author_kind = 'spark7' "
            "AND l.body NOT LIKE %s)", ("Diese Frage liegt ausserhalb%", "Diese Frage liegt ausserhalb%")).fetchone()["n"]
    lbsim = check_lbsim(wait_plans=getattr(args, "plans", False))
    for r in out["clients"]:
        r.update(lbsim.get(r["client"], {}))
    ok = all(r["lbs_current"] and r["parameter_set"] and r["pcp_default_regime"] and r["report_on_it"]
             and (r["pcp_scenario"] or not r["scenario"]) and r.get("lbsim_ok") for r in out["clients"])
    out["all_ok"] = ok and not any(out["garbled"].values()) and out["bind_mismatches"] == 0
    for r in out["clients"]:
        print(f"{r['client']:<14} lbs current {r['lbs_current']!s:<5} set {bool(r['parameter_set'])!s:<5} "
              f"default {r['pcp_default_regime'] or '-':<21} scenario {(r['scenario'] or '-'):<14} "
              f"{r['pcp_scenario'] or '-':<21} report on it {r['report_on_it']!s:<5} pcp {r['pcp_succeeded']} "
              f"reports {r['reports']} threads {r['threads']} approvals {r['approvals']} failed runs {r['failed_runs']}")
        print(f"{'':<14} lbsim: findings {r.get('lbsim_findings')!s:<5} paths {r.get('lbsim_paths')!s:<5} plan "
              f"{r.get('lbsim_plan') or '-':<10} report charts {r.get('report_charts')} ids on the page "
              f"{r.get('report_ids') or 'none'}")
    print(json.dumps({k: v for k, v in out.items() if k != "clients"}, indent=1, default=str))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "use-cases-check.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


ID_ON_PAGE = r"\b(?:LBS|LSF|LSP|LSO|PCP|RUN|RRQ|REP|RGM|RS|IDK|IPT)-[0-9a-f]{6,}|\b[0-9a-f]{32}\b"
CHARTS = ("roles", "positions", "fit", "outlook")


def check_lbsim(wait_plans=False, timeout_s=9 * 3600, step_s=300):
    """Per client: findings and paths on the newest sheet (lbsim's outlook through the app), the plan run queued,
    running or succeeded (``wait_plans``: until every one has succeeded or failed), and the newest report's page
    with the three charts (weights by role and by building block, target against reached, the fan) and no id."""
    import re as _re

    def one(c):
        cid = c["id"]
        view = app("GET", f"/api/clients/{cid}/outlook")
        sheet = _latest_sheet(cid)
        with the_store().session() as conn:
            plan = conn.execute(
                "SELECT status FROM engine_run WHERE client_id = %s AND engine = 'lbsim' AND run_id IS NOT NULL "
                "AND request->>'contract_version' IS DISTINCT FROM 'lbsim-request@1.0.0' ORDER BY created_at DESC LIMIT 1",
                (cid,)).fetchone()
            report = conn.execute("SELECT id FROM report WHERE client_id = %s ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
        html = page(c, report["id"]) if report else ""
        charts = [k for k in CHARTS if f'data-chart="{k}"' in html]
        ids = sorted(set(_re.findall(ID_ON_PAGE, html)))[:5]
        row = {"lbsim_findings": bool(view.get("available") and view.get("findings") is not None),
               "lbsim_paths": view.get("paths") is not None, "lbsim_plan": (view.get("plan") or {}).get("state"),
               "plan_run": plan["status"] if plan else None, "report_charts": len(charts), "report_ids": ids,
               "lbsim_sheet": sheet["artefact_id"] if sheet else None}
        row["lbsim_ok"] = (row["lbsim_findings"] and row["lbsim_paths"] and row["plan_run"] in ("queued", "running", "succeeded")
                           and len(charts) == len(CHARTS) and not ids)
        if not row["lbsim_ok"] and row["lbsim_findings"] and not row["lbsim_paths"] and not ids:
            # lbsim v1 simulates CHF allocations only (LBSIM-14): a client whose allocation is in another currency
            # gets findings and no paths, plan or fan, and that is the expected state, not a gap.
            with the_store().session() as conn:
                pcp = conn.execute("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                                   "AND status = 'succeeded' ORDER BY finished_at DESC LIMIT 1", (cid,)).fetchone()
            currency = call("GET", f"{PCP}/allocation/{pcp['artefact_id']}").get("currency") if pcp else None
            row["lbsim_not_chf"] = currency not in (None, "CHF")
            row["lbsim_ok"] = row["lbsim_not_chf"] and set(charts) >= set(CHARTS) - {"outlook"}
        return row

    t0 = time.time()
    while True:
        rows = {c["name"]: one(c) for c in CLIENTS}
        waiting = [n for n, r in rows.items() if r["plan_run"] in ("queued", "running")]
        if not wait_plans or not waiting or time.time() - t0 > timeout_s:
            return rows
        log(f"plans still calculating: {len(waiting)} ({', '.join(waiting[:6])}{' ...' if len(waiting) > 6 else ''})")
        time.sleep(step_s)


# --------------------------------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["select", "erase", "enrich", "partners", "basis", "earning", "mandates", "outlook",
                                    "threads", "curate", "reports", "updates", "approvals", "revision", "check", "all"])
    p.add_argument("--apply", action="store_true", help="erase: really erase (otherwise a dry run)")
    p.add_argument("--only", help="comma-separated client keys (simon, miriam, ...)")
    p.add_argument("--batch", type=int, default=6, help="threads and reports asked before waiting for them")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--plans", action="store_true", help="check: wait until every plan calculation has finished")
    p.add_argument("--refresh", action="store_true", help="mandates: derive and finalise again from the latest sheet; reports: a new report where "
                                                          "the latest is older than the latest pcp run or draws on no outlook "
                                                          "of the newest sheet; outlook: ask lbsim again")
    args = p.parse_args(argv)
    steps = {"select": cmd_select, "erase": cmd_erase, "enrich": cmd_enrich, "partners": cmd_partners,
             "basis": cmd_basis, "earning": cmd_earning,
             "mandates": cmd_mandates, "outlook": cmd_outlook,
             "threads": cmd_threads, "curate": cmd_curate, "reports": cmd_reports, "updates": cmd_updates,
             "approvals": cmd_approvals, "revision": cmd_revision, "check": cmd_check}
    if args.step == "all":
        for name in ("enrich", "partners", "basis", "earning", "mandates", "outlook", "threads", "curate", "reports",
                     "updates", "approvals", "revision", "check"):
            log(f"== {name}")
            steps[name](args)
    else:
        steps[args.step](args)


if __name__ == "__main__":
    main()
