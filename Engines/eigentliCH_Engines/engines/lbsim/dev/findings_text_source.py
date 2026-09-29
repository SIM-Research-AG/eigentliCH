"""The source of the seed record ``findings-text`` (LBSIM-17). ``python dev/findings_text_source.py`` writes
``src/lbsim/seed_records/findings-text.json``; the record, not this file, is what the engine reads.

Every template names its figures as ``{name}`` and carries no number of its own; a test renders each one and
scans it for the calibrated forbidden verbs and for any instrument or product name.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "lbsim" / "seed_records" / "findings-text.json"


def F(de_title, de_trigger, de_why, de_action, en_title, en_trigger, en_why, en_action):
    return {"de": {"title": de_title, "trigger": de_trigger, "why": de_why, "action": de_action},
            "en": {"title": en_title, "trigger": en_trigger, "why": en_why, "action": en_action}}


FINDINGS = {
    "goal_not_fundable": {
        "action_kind": "decide_between",
        "figures": {"p_goal": ["share", None], "required_confidence": ["share", None],
                    "achievable_amount": ["chf", "nominal"]},
        "answers": ["goals"],
        "text": F(
            "Dieses Ziel liegt nicht innerhalb dieser Mittel",
            "Die Planrechnung erreicht das Ziel in {p_goal} der Verläufe; verlangt sind {required_confidence}.",
            "Das ist ein Befund und keine Panne. Ein Plan, der das Ziel verfehlt, ist nicht der Plan, nach dem "
            "gefragt wurde. Was sich ändern lässt, ist das Ziel selbst, sein Betrag, sein Datum, die verlangte "
            "Sicherheit, oder die Mittel.",
            "Betrag, Datum und verlangte Sicherheit einzeln durchrechnen. Mit diesen Mitteln erreichbar sind "
            "{achievable_amount}; das ist eine Messung, kein Zielvorschlag.",
            "This goal lies outside these means",
            "The plan calculation reaches the goal in {p_goal} of the paths; {required_confidence} are required.",
            "This is a finding, not a fault. A plan that misses the goal is not the plan that was asked for. What "
            "can change is the goal itself, its amount, its date, the confidence asked of it, or the means.",
            "Work through the amount, the date and the confidence one at a time. These means reach "
            "{achievable_amount}; that is a measurement, not a proposed goal."),
    },
    "thin_liquidity": {
        "action_kind": "quantify",
        "figures": {"liquid": ["chf", "nominal"], "debt": ["chf", "nominal"], "share": ["share", None],
                    "threshold": ["share", None], "cost_of_two_points": ["chf_per_year", "nominal"]},
        "answers": ["cash"],
        "text": F(
            "Dünne Liquidität gegen grosse Schulden",
            "Liquide Mittel von {liquid} stehen Schulden von {debt} gegenüber, also {share}; die Schwelle des "
            "Befundes liegt bei {threshold}.",
            "Steigt der Zins, muss die Liegenschaft die fehlende Liquidität liefern, und zwar zu dem Zeitpunkt, "
            "den der Markt wählt, nicht der Haushalt. Zwei Prozentpunkte mehr Zins kosten {cost_of_two_points} "
            "pro Jahr.",
            "Eine Reserve festlegen und in Franken benennen, bevor über Anlage oder Amortisation entschieden wird.",
            "Thin liquidity against large debts",
            "Liquid assets of {liquid} stand against debts of {debt}, that is {share}; the finding's threshold is "
            "{threshold}.",
            "If the rate rises, the property has to supply the missing liquidity, at a moment the market "
            "chooses rather than the household. Two percentage points more interest cost {cost_of_two_points} a "
            "year.",
            "Set a reserve and name it in francs before any decision on investing or amortising."),
    },
    "no_legal_documents": {
        "action_kind": "ask",
        "figures": {"documents": ["count", None], "property_total": ["chf", "nominal"]},
        "answers": ["legal_documents"],
        "text": F(
            "Keine rechtlichen Instrumente",
            "Erfasst ist kein Testament und kein Erbvertrag, bei Liegenschaften von {property_total}.",
            "Ohne Testament folgt der Nachlass der gesetzlichen Erbfolge, und ohne Vorsorgeauftrag ist nicht "
            "bestimmt, wer bei fehlender Urteilsfähigkeit handeln darf. Beides kostet wenig und steht über jedem "
            "finanziellen Posten.",
            "Testament oder Erbvertrag, Vorsorgeauftrag und Patientenverfügung als eigenen Termin führen, getrennt "
            "von jeder Anlagefrage.",
            "No legal documents",
            "No will and no inheritance contract are recorded, with property of {property_total}.",
            "Without a will the estate follows the statutory order of succession, and without a power of attorney "
            "nobody is named to act if capacity is lost. Both cost little and rank above every financial item.",
            "Treat a will or inheritance contract, a power of attorney and an advance directive as an appointment "
            "of their own, apart from any investment question."),
    },
    "hours_above_threshold": {
        "action_kind": "quantify",
        "figures": {"hours": ["hours_per_week", None], "threshold_hours": ["hours_per_week", None],
                    "multiple": ["count", None], "horizon_years": ["years", None],
                    "earning_power_ratio": ["share", None]},
        "answers": ["hours_per_week"],
        "text": F(
            "Die Arbeitszeit liegt über der Schwelle des Modells",
            "{hours} Wochenstunden gegen eine Schwelle von {threshold_hours}: die Gesundheit nimmt {multiple}-mal "
            "so schnell ab wie an der Schwelle.",
            "Die Ertragskraft folgt im Modell der Gesundheit. Nach {horizon_years} Jahren bleibt auf diesem Weg "
            "{earning_power_ratio} der Ertragskraft, die der Weg an der Schwelle hätte: der Plan verbraucht, was "
            "ihn finanziert.",
            "Die Stunden als Finanzgrösse behandeln und eine Reduktion in denselben Franken bewerten wie jede "
            "andere Entscheidung.",
            "Working hours are above the model's threshold",
            "{hours} hours a week against a threshold of {threshold_hours}: health declines {multiple} times as "
            "fast as at the threshold.",
            "In the model, earning power follows health. After {horizon_years} years this path keeps "
            "{earning_power_ratio} of the earning power the path at the threshold would keep: the plan uses up "
            "what funds it.",
            "Treat the hours as a financial quantity and value a reduction in the same francs as any other "
            "decision."),
    },
    "undirected_surplus": {
        "action_kind": "quantify",
        "figures": {"free": ["chf_per_year", "nominal"], "committed": ["chf_per_year", "nominal"],
                    "undirected": ["chf_per_year", "nominal"]},
        "answers": ["savings", "amortisation", "pillar3a_contribution"],
        "text": F(
            "Ein Überschuss ohne Verwendung",
            "Frei verfügbar sind {free} pro Jahr, davon fest verplant {committed}: {undirected} pro Jahr haben "
            "keine Verwendung.",
            "Der Haushalt erzeugt mehr, als er lenkt. Die Frage ist dann nicht die Rendite, sondern die Verwendung "
            "des Überschusses.",
            "Den Betrag benennen und ihm eine Verwendung geben. Solange er nicht zugeordnet ist, wird er "
            "verbraucht.",
            "A surplus without a use",
            "{free} a year is free, of which {committed} is committed: {undirected} a year has no use.",
            "The household generates more than it directs. The question is then not the return but the use of "
            "the surplus.",
            "Name the amount and give it a use. As long as it is not assigned, it is spent."),
    },
    "debt_service_equals_spending": {
        "action_kind": "quantify",
        "figures": {"mortgage_interest": ["chf_per_year", "nominal"], "target_spend": ["chf_per_year", "real"],
                    "ratio": ["count", None], "debt": ["chf", "nominal"]},
        "answers": ["mortgage_rate"],
        "text": F(
            "Der Schuldendienst kostet, was der Haushalt lebt",
            "Der Hypothekarzins von {mortgage_interest} steht einem Ausgabenziel von {target_spend} gegenüber, "
            "im Verhältnis {ratio}.",
            "Damit wird die Amortisation zum Mechanismus des Ziels und nicht zu seinem Rivalen: jeder getilgte "
            "Franken senkt genau die Ausgabe, die das Ziel bestimmt.",
            "Die Amortisation als Teil der Zielrechnung rechnen und beide Wege nebeneinander in Franken pro Jahr "
            "stellen.",
            "Debt service costs what the household lives on",
            "Mortgage interest of {mortgage_interest} stands against a spending goal of {target_spend}, a ratio "
            "of {ratio}.",
            "Amortisation then becomes the mechanism of the goal rather than its rival: every franc repaid lowers "
            "exactly the spending the goal is about.",
            "Count amortisation as part of the goal and set both ways side by side in francs a year."),
    },
    "wealth_that_cannot_work": {
        "action_kind": "ask",
        "figures": {"drawable": ["chf", "nominal"], "total_wealth": ["chf", "nominal"],
                    "drawable_share": ["share", None], "threshold": ["share", None]},
        "answers": [],
        "text": F(
            "Vermögen, das nicht arbeiten kann",
            "Entnahmefähig sind {drawable} von {total_wealth} Gesamtvermögen, also {drawable_share}; die Schwelle "
            "des Befundes liegt bei {threshold}.",
            "Das Gespräch über die Anlage betrifft eine kleine Scheibe der Bilanz. Die Liegenschaft und die "
            "Vorsorge tragen das Gesamtvermögen, aber keine Ausgabe.",
            "Vor jeder Anlagefrage festhalten, worauf sie sich bezieht: auf das entnahmefähige Vermögen, nicht auf "
            "das Gesamtvermögen.",
            "Wealth that cannot work",
            "{drawable} of {total_wealth} total wealth can be drawn, that is {drawable_share}; the finding's "
            "threshold is {threshold}.",
            "The investment conversation concerns a thin slice of the balance sheet. Property and pensions carry "
            "the total wealth, but no spending.",
            "Before any investment question, record what it refers to: the drawable wealth, not the total."),
    },
    "pension_too_small": {
        "action_kind": "ask",
        "figures": {"pillar2": ["chf", "nominal"], "income_gross": ["chf_per_year", "nominal"],
                    "ratio": ["share", None]},
        "answers": ["pillar2"],
        "text": F(
            "Das Pensionskassenguthaben ist für die Vorgeschichte zu klein",
            "Ein Guthaben von {pillar2} steht einem Jahreseinkommen von {income_gross} gegenüber, nach einem "
            "langen Erwerbsleben.",
            "Die Vorwärtsrechnung stützt sich auf Beiträge, die die Vergangenheit nicht zeigt: ein Vorbezug, "
            "Beitragslücken oder Jahre der Selbständigkeit. In allen drei Fällen ist die Projektion zu "
            "zuversichtlich.",
            "Den Vorsorgeausweis beschaffen und die Differenz erklären, bevor die Rente ab dem Referenzalter als "
            "Grundlage dient.",
            "The pension balance is small for the career behind it",
            "A balance of {pillar2} stands against a yearly income of {income_gross}, after a long working life.",
            "The projection rests on contributions the past does not show: an early withdrawal, gaps in the "
            "record or years of self-employment. In all three cases the projection is too confident.",
            "Obtain the pension certificate and explain the difference before the pension from the reference age "
            "is relied on."),
    },
    "empty_pillar3a": {
        "action_kind": "quantify",
        "figures": {"cap": ["chf_per_year", "nominal"], "marginal_rate": ["share", None],
                    "annual_effect": ["chf_per_year", "nominal"], "available_from": ["years", None]},
        "answers": ["pillar3a_contribution"],
        "text": F(
            "Die Säule 3a ist leer, und sie ist leer geblieben",
            "Guthaben und Beitrag sind null, bei einem Grenzsteuersatz von {marginal_rate}.",
            "Ein wiederkehrender Abzug bleibt ungenutzt; er entspricht rund {annual_effect} Steuern pro Jahr. "
            "Anders als die meisten Befunde kostet dieser jedes Jahr erneut, in dem er offen bleibt.",
            "Den Einzahlungsraum von {cap} pro Jahr klären. Das Guthaben ist ab dem Alter von {available_from} "
            "Jahren verfügbar.",
            "Pillar 3a is empty and has stayed empty",
            "Balance and contribution are both zero, at a marginal tax rate of {marginal_rate}.",
            "A recurring deduction goes unused; it is worth about {annual_effect} of tax a year. Unlike most "
            "findings this one costs again every year it stays open.",
            "Clarify the contribution room of {cap} a year. The balance is available from the age of "
            "{available_from}."),
    },
    "spending_doubling": {
        "action_kind": "ask",
        "figures": {"spend_now": ["chf_per_year", "nominal"], "spend_later": ["chf_per_year", "real"],
                    "factor": ["count", None]},
        "answers": ["spend_later"],
        "text": F(
            "Das Ausgabenziel liegt deutlich über heute",
            "Das Ausgabenziel von {spend_later} liegt beim {factor}-fachen der heutigen Lebenskosten von "
            "{spend_now}.",
            "Hier scheitert das Ziel und nicht das Mittel: ein Ziel über dem heutigen Lebensstandard verlangt "
            "Kapital, das der heutige Standard nie brauchte.",
            "Prüfen, ob das Ziel den gewünschten Lebensstandard beschreibt oder eine Sicherheitsmarge enthält. "
            "Beides ist zulässig, aber es sind zwei verschiedene Zahlen.",
            "The spending goal is well above today",
            "The spending goal of {spend_later} is {factor} times today's living costs of {spend_now}.",
            "Here the goal fails, not the means: a goal above today's standard of living needs capital today's "
            "standard never needed.",
            "Check whether the goal describes the wanted standard of living or contains a safety margin. Both are "
            "legitimate, but they are two different figures."),
    },
    "positions_outside_model": {
        "action_kind": "decide_between",
        "figures": {"total": ["chf", "nominal"], "drawable": ["chf", "nominal"], "items": ["count", None]},
        "answers": ["positions"],
        "text": F(
            "Erfasste Positionen ohne Zeile im Modell",
            "{items} erfasste Positionen über zusammen {total} haben im Modell keine Zeile, gegen ein "
            "entnahmefähiges Vermögen von {drawable}.",
            "Diese Beträge stehen in keiner Rechnung dieses Berichts. Wo sie das entnahmefähige Vermögen "
            "übersteigen, sind sie die grösste Auslassung des Befundes.",
            "Für jede Position getrennt entscheiden, ob sie als Vermögen, als Ertragsquelle oder als nichts gelten "
            "soll.",
            "Recorded positions with no line in the model",
            "{items} recorded positions worth {total} together have no line in the model, against drawable wealth "
            "of {drawable}.",
            "These amounts enter no calculation of this report. Where they exceed the drawable wealth they are the "
            "largest omission of the findings.",
            "Decide for each position whether it counts as wealth, as a source of income or as nothing."),
    },
    "rate_reset_near": {
        "action_kind": "quantify",
        "figures": {"years_left": ["years", None], "debt": ["chf", "nominal"],
                    "cost_per_point": ["chf_per_year", "nominal"]},
        "answers": ["mortgage_fixed_until"],
        "text": F(
            "Die Zinsbindung läuft bald aus",
            "Die Zinsbindung endet in {years_left} Jahren, auf einer Schuld von {debt}.",
            "Bis dahin ist der Zins ein Faktum, danach ein Risiko. Ein Prozentpunkt auf dieser Schuld kostet "
            "{cost_per_point} pro Jahr.",
            "Die Anschlussfrage vor dem Ablauf klären und die Reserve auf den Zinsanstieg auslegen, den der "
            "Haushalt tragen können will.",
            "The fixed rate ends soon",
            "The fixed rate ends in {years_left} years, on a debt of {debt}.",
            "Until then the rate is a fact, afterwards a risk. One percentage point on this debt costs "
            "{cost_per_point} a year.",
            "Settle the follow-on question before it ends and size the reserve to the rate rise the household "
            "wants to be able to carry."),
    },
    "rate_not_recorded": {
        "action_kind": "ask",
        "figures": {"debt": ["chf", "nominal"], "rate_used": ["share", None],
                    "cost_per_point": ["chf_per_year", "nominal"]},
        "answers": ["mortgage_rate"],
        "text": F(
            "Kein Hypothekarzins erfasst",
            "Auf einer Schuld von {debt} ist kein Zinssatz erfasst: gerechnet wird mit {rate_used}.",
            "Jede Zahl des Cashflows hängt an diesem Satz. Ein Prozentpunkt entspricht {cost_per_point} pro Jahr.",
            "Den tatsächlichen Satz und die Zinsbindung nachtragen.",
            "No mortgage rate recorded",
            "No rate is recorded on a debt of {debt}: the calculation uses {rate_used}.",
            "Every figure of the cash flow depends on this rate. One percentage point is {cost_per_point} a year.",
            "Add the actual rate and the date the fixed rate ends."),
    },
    "goal_not_computed": {
        "action_kind": "decide_between",
        "figures": {"count": ["count", None], "largest_deferred": ["chf", "nominal"],
                    "target_solved": ["chf", "nominal"]},
        "answers": ["goals"],
        "text": F(
            "Ein genanntes Ziel ist in dieser Rechnung nicht enthalten",
            "{count} genannte Ziele sind nicht gerechnet; das grösste beträgt {largest_deferred}. Gerechnet wurde "
            "gegen {target_solved}.",
            "Ein Ziel, dessen Art offen ist, lässt sich nicht gegen die Bilanz rechnen: selbst bewohntes Eigentum, "
            "ein Ferienobjekt und eine Firma verhalten sich verschieden.",
            "Die Art des Ziels festlegen. Danach rechnet der Bericht dagegen.",
            "A stated goal is not in this calculation",
            "{count} stated goals are not computed; the largest is {largest_deferred}. The calculation ran "
            "against {target_solved}.",
            "A goal whose kind is open cannot be computed against the balance sheet: a home to live in, a holiday "
            "home and a company behave differently.",
            "Settle what kind of goal it is. The report then computes against it."),
    },
    "own_share_only": {
        "action_kind": "decide_between",
        "figures": {"net_worth": ["chf", "nominal"], "drawable": ["chf", "nominal"]},
        "answers": ["asset_scope"],
        "text": F(
            "Erfasst ist der eigene Anteil, nicht der Haushalt",
            "Die Bilanz beschreibt den eigenen Anteil mit einem Nettovermögen von {net_worth}.",
            "Das übrige Vermögen des Partners fehlt. Die Haushaltsbilanz ist entsprechend unvollständig.",
            "Entscheiden, ob der Bericht den eigenen Anteil oder den Haushalt beschreiben soll.",
            "Only the person's own share is recorded",
            "The balance sheet describes the person's own share, with a net worth of {net_worth}.",
            "The partner's other wealth is missing. The household's balance sheet is incomplete accordingly.",
            "Decide whether the report describes the person's own share or the household."),
    },
    "stop_age_missing": {
        "action_kind": "ask",
        "figures": {"reference_age": ["years", None], "pillar3a_age": ["years", None]},
        "answers": ["stop_work_age"],
        "text": F(
            "Das Wunschalter für den Ausstieg fehlt",
            "Die Ziele nennen einen Ausstieg vor dem Referenzalter von {reference_age}, ein Ausstiegsalter ist "
            "aber nicht erfasst.",
            "Ohne Ausstiegsalter ist die Brücke bis zum Referenzalter nicht berechenbar: AHV und Pensionskasse "
            "setzen erst dann ein, die Säule 3a ab {pillar3a_age}.",
            "Ein Alter für den Ausstieg festlegen. Danach ist die Brücke eine Rechnung und keine Schätzung.",
            "The wanted age of stopping work is missing",
            "The goals name a stop before the reference age of {reference_age}, but no stop age is recorded.",
            "Without it the bridge to the reference age cannot be computed: AHV and the pension fund start only "
            "then, pillar 3a from {pillar3a_age}.",
            "Set an age for stopping. The bridge is then a calculation rather than an estimate."),
    },
    "indirect_amortisation": {
        "action_kind": "quantify",
        "figures": {"amount": ["chf_per_year", "nominal"], "debt": ["chf", "nominal"]},
        "answers": ["amortisation_mode"],
        "text": F(
            "Indirekte Amortisation",
            "Die Hypothek von {debt} wird indirekt amortisiert, mit {amount} pro Jahr.",
            "Die Schuld sinkt nicht, das Guthaben in der Säule 3a wächst. Im Modell ist das Sparen, nicht Tilgung, "
            "und es ist dieselbe Zahlung wie der Beitrag in die Säule 3a.",
            "Bei jeder Aussage über die Verschuldung mitlesen, dass sie bis zur Pensionierung stehen bleibt.",
            "Indirect amortisation",
            "The mortgage of {debt} is amortised indirectly, with {amount} a year.",
            "The debt does not fall; the pillar 3a balance grows. In the model this is saving, not repayment, and "
            "it is the same payment as the pillar 3a contribution.",
            "Read every statement about the debt knowing it stays in place until retirement."),
    },
    "unmarried_tax_overstated": {
        "action_kind": "ask",
        "figures": {"joint_base": ["chf_per_year", "nominal"], "separate": ["chf_per_year", "nominal"],
                    "overstatement": ["chf_per_year", "nominal"]},
        "answers": ["civil_status"],
        "text": F(
            "Steuerkorrektur für die unverheiratete Partnerschaft",
            "Gemeinsam zum Einzeltarif bemessen ergäbe {joint_base}, getrennt veranlagt {separate}: der "
            "Unterschied beträgt {overstatement} pro Jahr.",
            "Unverheiratete Partner werden getrennt veranlagt. Eine gemeinsame Bemessung zum Einzeltarif würde "
            "die Steuer überzeichnen.",
            "Die getrennte Zahl gegen die Steuererklärung prüfen.",
            "Tax correction for an unmarried couple",
            "Assessed jointly at the single tariff the tax would be {joint_base}, assessed separately {separate}: "
            "a difference of {overstatement} a year.",
            "Unmarried partners are assessed separately. A joint assessment at the single tariff would overstate "
            "the tax.",
            "Check the separate figure against the tax return."),
    },
}

UNCHECKED = {
    "goal_not_fundable": {"de": "Das entscheidet die Planrechnung, die im Hintergrund läuft.",
                          "en": "The plan calculation decides this; it runs in the background."},
    "thin_liquidity": {"de": "Die Schulden des Haushalts sind nicht erfasst.",
                       "en": "The household's debts are not recorded."},
    "no_legal_documents": {"de": "Ob ein Testament oder ein Vorsorgeauftrag besteht, ist nicht erfasst.",
                           "en": "Whether there is a will or a power of attorney is not recorded."},
    "hours_above_threshold": {"de": "Die Wochenstunden sind nicht erfasst.",
                              "en": "The working hours are not recorded."},
    "undirected_surplus": {"de": "Einkommen oder heutige Lebenskosten sind nicht erfasst.",
                           "en": "The income or today's living costs are not recorded."},
    "debt_service_equals_spending": {"de": "Die Schulden oder das Ausgabenziel sind nicht erfasst.",
                                     "en": "The debts or the spending goal are not recorded."},
    "wealth_that_cannot_work": {"de": "Das Gesamtvermögen ist nicht bestimmbar.",
                                "en": "The total wealth cannot be determined."},
    "pension_too_small": {"de": "Einkommen oder Pensionskassenguthaben sind nicht erfasst.",
                          "en": "The income or the pension balance is not recorded."},
    "empty_pillar3a": {"de": "Der Beitrag in die Säule 3a ist nicht erfasst.",
                       "en": "The pillar 3a contribution is not recorded."},
    "spending_doubling": {"de": "Die heutigen Lebenskosten oder die Ausgaben im Ruhestand sind nicht erfasst.",
                          "en": "Today's living costs or the spending in retirement are not recorded."},
    "positions_outside_model": {"de": "Die Positionen sind nicht erfasst.",
                                "en": "The positions are not recorded."},
    "rate_reset_near": {"de": "Das Ende der Zinsbindung ist nicht erfasst.",
                        "en": "The date the fixed rate ends is not recorded."},
    "rate_not_recorded": {"de": "Die Schulden des Haushalts sind nicht erfasst.",
                          "en": "The household's debts are not recorded."},
    "goal_not_computed": {"de": "Es ist kein Ziel erfasst.", "en": "No goal is recorded."},
    "own_share_only": {"de": "Ob die Angaben den Haushalt oder den eigenen Anteil beschreiben, ist nicht erfasst.",
                       "en": "Whether the answers describe the household or the person's own share is not "
                             "recorded."},
    "stop_age_missing": {"de": "Es ist kein Ruhestandsziel mit Datum erfasst.",
                         "en": "No dated retirement goal is recorded."},
    "indirect_amortisation": {"de": "Die Art der Amortisation ist nicht erfasst.",
                              "en": "How the mortgage is amortised is not recorded."},
    "unmarried_tax_overstated": {"de": "Der Zivilstand ist nicht erfasst.",
                                 "en": "The civil status is not recorded."},
    "_rule_failed": {"de": "Die Regel konnte auf diesen Angaben nicht laufen.",
                     "en": "The rule could not run on these answers."},
}

SCHEDULE = {
    "now": {"de": "Jetzt, vor jeder Anlageentscheidung", "en": "Now, before any investment decision"},
    "months": {"de": "In den nächsten Monaten", "en": "In the coming months"},
    "year": {"de": "Im Verlauf des Jahres", "en": "In the course of the year"},
    "watch": {"de": "Mitlesen, kein Termin", "en": "To keep in mind, no date"},
}

INCOME_PATHS = {
    "today": {"name": {"de": "Ohne Weiterbildung, Pensum bleibt", "en": "No further education, same pensum"},
              "note": {"de": "Keine zusätzliche Ausbildung, keine Änderung am Pensum. Das Einkommen bewegt sich "
                             "trotzdem: Erfahrung wächst im Modell von selbst, und im späten Erwerbsleben fällt es "
                             "wieder. Das ist die Vergleichslinie.",
                       "en": "No further education, no change to the pensum. Income still moves: experience grows "
                             "by itself in the model, and late in the career it falls again. This is the line to "
                             "compare with."}},
    "education": {"name": {"de": "Weiterbildung, Pensum bleibt", "en": "Further education, same pensum"},
                  "note": {"de": "Die geplante Weiterbildung findet statt, das Pensum bleibt. Zeigt, was die "
                                 "Ausbildung allein trägt.",
                           "en": "The planned education takes place and the pensum stays. Shows what the education "
                                 "alone carries."}},
    "full_pensum": {"name": {"de": "Weiterbildung und volles Pensum", "en": "Further education and a full pensum"},
                    "note": {"de": "Nach Abschluss ein volles Pensum. Für einen Haushalt, dessen Einkommen heute "
                                   "wegen der Ausbildung tief ist, ist das meist der grösste einzelne Schritt.",
                             "en": "A full pensum once the education is done. For a household whose income is low "
                                   "today because of the education this is usually the largest single step."}},
    "network": {"name": {"de": "Weiterbildung, volles Pensum und Netzwerk",
                         "en": "Further education, a full pensum and networking"},
                "note": {"de": "Zusätzlich Zeit für Kontakte und Sichtbarkeit, bis zum Knick der Modellkurve. Mehr "
                               "bringt nach diesem Modell fast nichts.",
                         "en": "Time for contacts and visibility on top, up to the knee of the model's curve. More "
                               "than that brings almost nothing in this model."}},
}

ZERO_RETURN = {"de": "Die Sparrechnung rechnet ohne Rendite. Das ist ein Überblick und keine Prognose: sie zeigt, "
                     "was ein Ziel an reinem Sparen kostet. Was schon ohne Rendite trägt, braucht den Markt nicht.",
               "en": "The saving figures assume a return of zero. This is an overview, not a forecast: it shows "
                     "what a goal costs in saving alone. What holds without a return does not need the market."}

INPUT_CHECKS = {
    "saving_exceeds_income": {
        "title": {"de": "Die angegebene Sparquote ist grösser als das ganze Einkommen",
                  "en": "The stated saving is larger than the whole income"},
        "question": {"de": "Welche der beiden Zahlen ist die jährliche, und gehört sie zu diesem Einkommen?",
                     "en": "Which of the two figures is the yearly one, and does it belong to this income?"}},
    "spending_exceeds_income_without_cover": {
        "title": {"de": "Die Ausgaben übersteigen das Einkommen, ohne Vermögen, das die Differenz trägt",
                  "en": "Spending exceeds income, with no wealth to carry the difference"},
        "question": {"de": "Gibt es weiteres Einkommen, das nicht erfasst ist?",
                     "en": "Is there further income that is not recorded?"}},
    "age_and_birth_year_disagree": {
        "title": {"de": "Alter und Jahrgang passen nicht zusammen", "en": "Age and year of birth do not match"},
        "question": {"de": "Welcher Jahrgang stimmt?", "en": "Which year of birth is right?"}},
    "pensum_declaration_conflicts": {
        "title": {"de": "Stundenzahl und angegebenes Pensum passen nicht zusammen",
                  "en": "The hours and the stated pensum do not match"},
        "question": {"de": "Sind die genannten Stunden Ihr volles Pensum, oder arbeiten Sie reduziert?",
                     "en": "Are the stated hours your full pensum, or do you work reduced hours?"}},
    "implied_fulltime_income_out_of_band": {
        "title": {"de": "Auf ein volles Pensum hochgerechnet ergibt das Einkommen einen ungewöhnlichen Wert",
                  "en": "Scaled to a full pensum the income gives an unusual figure"},
        "question": {"de": "Ist das Einkommen der Jahresbetrag für die genannten Stunden?",
                     "en": "Is the income the yearly amount for the stated hours?"}},
    "reduced_pensum_without_an_anchor": {
        "title": {"de": "Zum Einkommen bei vollem Pensum liegt keine Angabe vor",
                  "en": "There is no answer on the income at a full pensum"},
        "question": {"de": "Welchen Bruttolohn erwarten Sie bei vollem Pensum, sobald eine laufende oder geplante "
                           "Ausbildung abgeschlossen ist?",
                     "en": "What gross salary do you expect at a full pensum once any education under way or "
                           "planned is done?"}},
    "working_past_the_reference_age": {
        "title": {"de": "Die geplanten Arbeitsjahre reichen über das Referenzalter hinaus",
                  "en": "The planned working years reach past the reference age"},
        "question": {"de": "Sollen die Jahre nach dem Referenzalter mitgerechnet werden?",
                     "en": "Should the years after the reference age be counted?"}},
    "pillar2_before_the_start_age": {
        "title": {"de": "Pensionskassenguthaben vor dem Beginn der Altersgutschriften",
                  "en": "A pension balance before retirement credits begin"},
        "question": {"de": "Woher stammt dieses Guthaben?", "en": "Where does this balance come from?"}},
    "a_goal_far_beyond_the_household": {
        "title": {"de": "Ein Ziel verlangt pro Jahr mehr, als der Haushalt einnimmt",
                  "en": "A goal needs more each year than the household earns"},
        "question": {"de": "Gibt es für dieses Ziel eine Quelle ausserhalb des laufenden Einkommens?",
                     "en": "Is there a source for this goal outside the current income?"}},
}

MOVES = {
    "pensum": {"baseline": {"de": "Pensum wie heute", "en": "Pensum as today"},
               "change": {"de": "Pensum auf {value}", "en": "Pensum raised to {value}"}},
    "learning": {"baseline": {"de": "Ohne Weiterbildung", "en": "No further education"},
                 "change": {"de": "Weiterbildung mit {value} Stunden pro Woche",
                            "en": "Further education, {value} hours a week"}},
    "network": {"baseline": {"de": "Ohne Netzwerkarbeit", "en": "No networking"},
                "change": {"de": "Netzwerk mit {value} Stunden pro Woche", "en": "Networking, {value} hours a week"}},
    "spending": {"baseline": {"de": "Ausgaben wie heute", "en": "Spending as today"},
                 "change": {"de": "Ausgaben um {value} tiefer", "en": "Spending lower by {value}"}},
    "stop_age": {"baseline": {"de": "Erwerbsende wie geplant", "en": "Stop working as planned"},
                 "change": {"de": "Erwerbsende mit {value}", "en": "Stop working at {value}"}},
    "goal_year": {"baseline": {"de": "Zieljahr wie genannt", "en": "Target year as stated"},
                  "change": {"de": "Zieljahr {value} Jahre später", "en": "Target year {value} years later"}},
    "goal_amount": {"baseline": {"de": "Betrag wie genannt", "en": "Amount as stated"},
                    "change": {"de": "Betrag auf {value}", "en": "Amount reduced to {value}"}},
}

FRONTIER_REFUSED = {"de": "Der Suchraum ist grösser, als hier vollständig geprüft wird; eine teilweise Suche würde "
                          "eine Antwort geben, die keine ist.",
                    "en": "The search space is larger than is checked here in full; a partial search would give an "
                          "answer that is not one."}

GATE = {
    "contradiction": {"de": "Zwei Angaben passen nicht zusammen", "en": "Two answers do not fit together"},
    "blocking_field": {"de": "Eine Angabe fehlt", "en": "An answer is missing"},
    "unresolved_goal": {"de": "Die Art eines Ziels ist offen", "en": "The kind of a goal is open"},
    "pending": {"de": "Bewusst offen gelassen", "en": "Left open on purpose"},
    "ask": {"de": "Eine Angabe, die etwas bewegt", "en": "An answer that moves the figures"},
}

QUESTIONS = {
    "residence_share": {"de": "Welcher Teil Ihrer Liegenschaften ist selbst bewohnt, und welcher vermietet?",
                        "en": "Which part of your property do you live in, and which part is let?"},
    "civil_status": {"de": "Sind Sie verheiratet, in eingetragener Partnerschaft, oder keines von beiden?",
                     "en": "Are you married, in a registered partnership, or neither?"},
    "pillar2_certificate": {"de": "Wie hoch ist Ihr Pensionskassenguthaben laut Vorsorgeausweis?",
                            "en": "What is your pension balance according to the pension certificate?"},
    "mortgage_rate": {"de": "Zu welchem Zinssatz läuft Ihre Hypothek, und bis wann ist er fixiert?",
                      "en": "At what rate does your mortgage run, and until when is it fixed?"},
    "stop_work_age": {"de": "Ab welchem Alter möchten Sie nicht mehr auf Erwerbseinkommen angewiesen sein?",
                      "en": "From what age do you want to stop depending on earned income?"},
    "spend_now": {"de": "Was kostet Ihr Leben heute, ohne Sparen und ohne Steuern?",
                  "en": "What does your life cost today, without saving and without taxes?"},
    "savings": {"de": "Wie viel bleibt bei Ihnen pro Jahr tatsächlich übrig?",
                "en": "How much is actually left over each year?"},
    "ahv_record": {"de": "Fehlen Ihnen AHV-Beitragsjahre, etwa durch Studium, Ausland oder Selbständigkeit?",
                   "en": "Are you missing AHV contribution years, for example from study, time abroad or "
                         "self-employment?"},
    "goal_amount_year": {"de": "Nennen Sie ein Ziel mit einem Betrag und einem Jahr.",
                         "en": "Name a goal with an amount and a year."},
}

ASSUMPTIONS = {
    "withdrawal_rate": {"text": {"de": "Entnahmesatz im Ruhestand: das nötige Kapital ist der jährliche Bedarf "
                                       "geteilt durch diesen Satz.",
                                 "en": "Withdrawal rate in retirement: the capital needed is the yearly need "
                                       "divided by this rate."},
                        "replaced_by": {"de": "eine Entscheidung über die verlangte Sicherheit",
                                        "en": "a decision on the safety required"}},
    "conversion_rate": {"text": {"de": "Umwandlungssatz der Pensionskasse", "en": "Pension fund conversion rate"},
                        "replaced_by": {"de": "der Vorsorgeausweis", "en": "the pension certificate"}},
    "pension_interest": {"text": {"de": "Verzinsung des Pensionskassenguthabens",
                                  "en": "Interest credited on the pension balance"},
                         "replaced_by": {"de": "der Ausweis der Kasse", "en": "the fund's certificate"}},
    "rent_yield": {"text": {"de": "Nettoertrag vermieteter Liegenschaften", "en": "Net yield of let property"},
                   "replaced_by": {"de": "die tatsächliche Nettorendite", "en": "the actual net yield"}},
    "wealth_tax_rate": {"text": {"de": "Vermögenssteuersatz", "en": "Wealth tax rate"},
                        "replaced_by": {"de": "die Veranlagung Ihrer Gemeinde",
                                        "en": "your municipality's assessment"}},
    "income_tax": {"text": {"de": "Einkommenssteuer als glatte Näherung, auf den Kanton skaliert, wo ein Faktor "
                                  "vorliegt",
                            "en": "Income tax as a smooth approximation, scaled to the canton where a factor "
                                  "exists"},
                   "replaced_by": {"de": "die Veranlagung Ihrer Gemeinde", "en": "your municipality's assessment"}},
    "mortgage_rate": {"text": {"de": "Hypothekarzins, weil kein Satz erfasst ist",
                               "en": "Mortgage rate, because none is recorded"},
                      "replaced_by": {"de": "der Satz des Kreditvertrags", "en": "the rate in the loan contract"}},
    "inflation": {"text": {"de": "Teuerung: die Annahme des Life Balance Sheet, mit der Löhne und Ausgaben "
                                 "steigen und die Ziele in Franken ihres Datums gelesen werden",
                           "en": "Inflation: the Life Balance Sheet's assumption, with which wages and spending "
                                 "rise and goals are read in the francs of their date"},
                  "replaced_by": {"de": "eine andere Annahme im Life Balance Sheet",
                                  "en": "a different assumption in the Life Balance Sheet"}},
    "residence_is_all_property": {"text": {"de": "Die Liegenschaften gelten als selbst bewohnt, weil der Anteil "
                                                 "nicht erfasst ist; das ist die vorsichtige Lesart.",
                                           "en": "All property counts as lived in, because the share is not "
                                                 "recorded; this is the cautious reading."},
                                  "replaced_by": {"de": "der selbst bewohnte Anteil", "en": "the share lived in"}},
    "pillar3a_contribution": {"text": {"de": "Kein laufender Beitrag in die Säule 3a, weil keiner erfasst ist",
                                       "en": "No running pillar 3a contribution, because none is recorded"},
                              "replaced_by": {"de": "der tatsächliche Beitrag", "en": "the actual contribution"}},
    "spending": {"text": {"de": "Lebenskosten: das Ausgabenziel des Modells, weil keine heutigen Kosten erfasst "
                                "sind",
                          "en": "Living costs: the model's spending goal, because today's costs are not recorded"},
                 "replaced_by": {"de": "die heutigen Lebenskosten", "en": "today's living costs"}},
    "earning_level": {"text": {"de": "Einkommensniveau aus dem Modell, weil keine Erwartung bei vollem Pensum "
                                     "erfasst ist",
                               "en": "Income level from the model, because no expectation at a full pensum is "
                                     "recorded"},
                      "replaced_by": {"de": "Ihre Erwartung bei vollem Pensum",
                                      "en": "your expectation at a full pensum"}},
    "child_costs": {"text": {"de": "Kinderkosten nach BFS und Büro BASS 2009, Preisbasis 2000 bis 2005",
                             "en": "Child costs after BFS and Büro BASS 2009, price base 2000 to 2005"},
                    "replaced_by": {"de": "die tatsächlichen Kosten des Haushalts",
                                    "en": "the household's actual costs"}},
    "capitals_mid_scale": {"text": {"de": "Ausbildung oder Netzwerk sind nicht erfasst; der Verlauf des "
                                          "Einkommens rechnet mit der Mitte der Skala.",
                                    "en": "Education or network are not recorded; the shape of the income path "
                                          "uses the middle of the scale."},
                           "replaced_by": {"de": "Ihre Angaben zu Ausbildung und Netzwerk",
                                           "en": "your answers on education and network"}},
    "ahv_record": {"text": {"de": "Eine vollständige AHV-Beitragsdauer", "en": "A complete AHV contribution record"},
                   "replaced_by": {"de": "der Auszug aus dem individuellen Konto",
                                   "en": "the individual account statement"}},
}

LIMITS = {
    "no_plan": {"de": "Die Planrechnung läuft getrennt davon. Ohne sie fehlt genau eine Aussage: ob das Ziel bei der "
                      "verlangten Sicherheit hält, und was die Rechnung für diese Periode annimmt.",
                "en": "The plan calculation runs separately. Without it exactly one statement is missing: whether "
                      "the goal holds at the confidence asked, and what the calculation assumes for this period."},
    "bridge": {"de": "Ohne erfasstes Ausstiegsalter ist die Brücke bis zum Referenzalter nicht gerechnet.",
               "en": "Without a recorded stop age the bridge to the reference age is not computed."},
    "retirement_span": {"de": "Die Rentendauer ist im Modell an das Referenzalter gebunden; für einen Ausstieg "
                              "davor ist die Spanne zu kurz.",
                        "en": "The span of retirement is tied to the reference age in the model; for an earlier "
                              "stop it is too short."},
    "child_price_base": {"de": "Die Kinderkosten stehen auf der Preisbasis 2000 bis 2005; kein Indexfaktor ist "
                               "belegt, die Zahl ist damit zu tief.",
                         "en": "The child costs are at the price base of 2000 to 2005; no index factor is sourced, "
                               "so the figure is too low."},
    "no_recommendation": {"de": "Nichts hier ist eine Empfehlung. Ein Befund ist Bildung; eine Empfehlung verlangt "
                                "einen benannten Kurator und einen Entscheidungsnachweis.",
                          "en": "Nothing here is a recommendation. A finding informs; a recommendation needs a "
                                "named curator and a decision record."},
    "single_subject": {"de": "Das Modell rechnet für eine Person; das Einkommen der zweiten erwachsenen Person geht "
                             "fest und ohne eigene Entscheidungen ein.",
                       "en": "The model computes for one person; the second adult's income enters as fixed, with "
                             "no choices of its own."},
}

EARNING = {
    "not_available": {"de": "Die Ertragskraft ist nicht berechenbar, weil Ausbildung oder Netzwerk nicht erfasst "
                            "sind.",
                      "en": "Earning power cannot be computed, because the education or the network is not "
                            "recorded."},
    "no_age": {"de": "Die Ertragskraft ist nicht berechenbar, weil das Alter nicht erfasst ist.",
               "en": "Earning power cannot be computed, because the age is not recorded."},
    "tier_not_stated": {"de": "Keine Führungsfunktion angegeben, also keine angenommen; nach der BFS-Tabelle ist "
                              "sie mehr wert als die Ausbildung.",
                        "en": "No management function was stated, so none was assumed; the BFS table shows it is "
                              "worth more than the qualification."},
    "tier_mean": {"de": "Ohne Ausbildungsangabe gilt der Mittelwert der veröffentlichten Faktoren.",
                  "en": "Without a qualification the mean of the published multipliers applies."},
    "sector_missing": {"de": "Ohne Branche gilt die Zahl der Gesamtwirtschaft; sie liegt nahe beim Maschinenbau "
                             "und weit unter Banken, Pharma und Versicherungen.",
                       "en": "Without a sector the whole-economy figure applies; it sits near mechanical "
                             "engineering and far below banking, pharma and insurance."},
    "extrapolated": {"de": "Für die oberste Führung ist die Zahl nach Branche veröffentlicht, nicht nach "
                           "Ausbildung; für andere Abschlüsse als die Universität ist sie hochgerechnet.",
                     "en": "For top management the figure is published by sector, not by qualification; for other "
                           "qualifications than a university degree it is extrapolated."},
    "tier_unknown": {"de": "Die angegebene Führungsfunktion ist keine veröffentlichte Stufe; es gilt kein "
                           "Zuschlag.",
                     "en": "The stated management function is not a published tier; no uplift applies."},
    "health_unknown": {"de": "Die Gesundheit ist nicht erfasst; die Ertragskraft gilt bei voller Gesundheit und ist "
                             "damit zu hoch.",
                       "en": "Health is not recorded; earning power is at full health and so too high."},
    "health_withheld": {"de": "Die Gesundheitsangabe ist zurückgehalten; die Ertragskraft gilt bei voller "
                              "Gesundheit und ist damit zu hoch.",
                        "en": "The health answer is withheld; earning power is at full health and so too high."},
    "capacity_below_pensum": {"de": "Ein Weg mit vollem Pensum geht über die angegebene Arbeitsfähigkeit hinaus.",
                              "en": "A path at a full pensum goes beyond the stated capacity to work."},
}

HEADLINES = {"Kapitalbedarf": "capital_need", "Deckungslücke pro Jahr": "gap_per_year",
             "freier Cashflow": "free_cash", "Steuern": "taxes", "Brückenbedarf": "bridge_need"}

POLICY = {
    "forbidden_verbs": ["kaufen", "kaufe", "kauft", "kauf", "verkaufen", "verkauf", "verkauft", "erwerben",
                        "investieren", "investiert", "anlegen in", "umschichten", "zeichnen",
                        "buy", "buying", "sell", "selling", "invest in", "invest", "purchase", "switch into",
                        "subscribe to", "acquire"],
    "product_words": ["ETF", "Fonds", "Anlagefonds", "investment fund", "mutual fund", "index fund",
                      "Zertifikat", "structured product", "strukturiertes Produkt", "Anleihe", "Obligation",
                      "bond", "bonds", "Aktie", "Aktien", "equities", "Derivat", "derivative", "Tracker",
                      "Kryptowährung", "crypto"],
    "note": ("Scanned in every template of this record by a test (LBSIM-17): whole words, case-insensitive. The "
             "instrument names of the pcp universe are scanned too; they come from the Allocation the samples "
             "were built on."),
}


def main() -> int:
    record = {
        "_about": {
            "what": ("The words of lbsim's findings, schedule, unchecked rules, income paths, input checks, "
                     "frontier moves, gate items, questions, assumptions, limits and earning-power caveats, in "
                     "German and English (LBSIM-17)."),
            "version": "1.0.0",
            "provisional": True,
            "published_by": None,
            "note": ("Written for lbsim on 29.09.2026 from the draft's German texts (app/findings.py and its "
                     "neighbours), without their numbers: every figure is a {placeholder}. Not approved by a "
                     "named person; findings are read without a gate and say so (provenance.records)."),
        },
        "findings": FINDINGS,
        "unchecked": UNCHECKED,
        "schedule": SCHEDULE,
        "income_paths": INCOME_PATHS,
        "zero_return": ZERO_RETURN,
        "input_checks": INPUT_CHECKS,
        "moves": MOVES,
        "frontier_refused": FRONTIER_REFUSED,
        "gate": GATE,
        "questions": QUESTIONS,
        "assumptions": ASSUMPTIONS,
        "limits": LIMITS,
        "earning": EARNING,
        "headlines": HEADLINES,
        "policy": POLICY,
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
