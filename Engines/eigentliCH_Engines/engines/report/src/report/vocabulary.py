"""What the upstream engines say, in the reader's language (REP-19, REP-20). Pure.

lbs and pcp explain themselves in English and in their own keys: a gap names an input (``composition_as_of``),
a finding a reason (``the_goal_does_not_say_whether_the_member_will_live_in_it``), a not-available section a
sentence written for engineers, pcp's coverage warnings a sentence with its diagnostics. A reader of a report
sees none of that. Each key and each reason lbs and pcp can emit has a short plain sentence here, in German
and in English; the artefact keeps the upstream text as the fact's value (it is what the path resolves to),
the page prints the sentence.

Objects are named for readers, never by id: a person as "Person 1", a goal by its kind ("Ihr
Wohneigentumsziel"), or by the name the caller sends as a display fact (``person.<person_id>``,
``goal.<goal_id>``, REP-20). The generic names are what the model sees; the caller's names reach the page only.

``tests/test_vocabulary.py`` reads the lbs and pcp sources and fails when either can emit a key or a reason
this module has no sentence for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Pattern

Texts = Mapping[str, str]

#: What a reader must never see: a 32-hex id, a UUID, a snake_case key.
HEX32 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])")
UUID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
#: An engine's artefact, run, key or request id (``LBS-``, ``PCP-``, ``REP-``, ``RUN-``, ``IDK-``, ``RRQ-``, ...),
#: and any bare 16-hex run such as a checksum prefix (REP-23).
PREFIXED = re.compile(r"\b[A-Z]{2,5}-[0-9A-Fa-f]{12,}\b")
HEX16 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16,}(?![0-9A-Fa-f])")


def looks_internal(text: str) -> bool:
    """Whether ``text`` carries something only an engine should read: an id or a key."""
    return bool(HEX32.search(text) or UUID.search(text) or SNAKE.search(text) or PREFIXED.search(text)
                or HEX16.search(text))


@dataclass(frozen=True)
class Entry:
    key: str
    #: Matched against the upstream text (``search``, case-insensitive).
    pattern: Pattern[str]
    text: Texts


def _e(key: str, pattern: str, de: str, en: str) -> Entry:
    return Entry(key=key, pattern=re.compile(pattern, re.IGNORECASE), text={"de": de, "en": en})


# ---------------------------------------------------------------------------
# lbs: the reasons of a section it could not compute, and why a capital is absent
# ---------------------------------------------------------------------------

_COMPOSITION = ("Die Angaben zum Haushalt sind älter als ihre Gültigkeitsdauer und müssen bestätigt werden.",
                "The household details are older than their period of validity and need confirming.")
_PROPERTY_RULES = ("Die Regeln zur Finanzierung von Wohneigentum sind noch nicht freigegeben.",
                   "The rules for financing home ownership are not yet approved.")
_NO_HOUSEHOLD_INCOME = ("Für den Haushalt ist kein Einkommen erfasst.", "No income is recorded for the household.")
_POSITION_VESSEL = ("Bei einer Finanzierungsposition ist nicht angegeben, um welche Art Vermögen es sich handelt; "
                    "es könnte Vorsorgekapital sein.",
                    "A funding position does not say what kind of asset it is; it may be pension capital.")

#: Upstream reasons, after the "not available" prefix lbs puts in front of them. Order matters: first match.
REASONS: tuple[Entry, ...] = (
    _e("record_not_approved", r"record not approved",
       "Die Berechnungsgrundlagen dafür sind noch nicht freigegeben, deshalb steht hier keine Zahl.",
       "The basis for this calculation is not yet approved, so no figure is shown."),
    _e("earning_power_elsewhere", r"earning power",
       "Die Erwerbskraft berechnet ein anderes Modell; dieser Bericht enthält sie nicht.",
       "Earning power is computed by another model; this report does not contain it."),
    _e("no_mdje_no_income", r"neither an mdje nor",
       "Weder ein massgebendes durchschnittliches Jahreseinkommen noch ein Einkommen ist erfasst.",
       "Neither an average annual income for the AHV nor an income is recorded."),
    _e("age_not_stated", r"age is not stated", "Das Alter der Person ist nicht erfasst.",
       "The person's age is not recorded."),
    _e("no_gross_income", r"no gross income is stated", "Für die Person ist kein Bruttoeinkommen erfasst.",
       "No gross income is recorded for the person."),
    _e("civil_status_not_stated", r"civil status is not stated", "Der Zivilstand ist nicht erfasst.",
       "The civil status is not recorded."),
    _e("cap_married_only", r"married couple only", "Die Plafonierung gilt nur für Ehepaare.",
       "The cap applies to married couples only."),
    _e("both_pensions_needed", r"both pensions are needed", "Dafür werden beide Renten benötigt.",
       "Both pensions are needed for this."),
    _e("composition_expired", r"composition is past its validity horizon", *_COMPOSITION),
    _e("no_mandate_goal", r"no goal is designated for the mandate",
       "Für den Mandatsvorschlag ist kein Ziel bestimmt.", "No goal is designated for the mandate proposal."),
    _e("property_goal_no_price", r"property goal names no price", "Das Ziel nennt keinen Kaufpreis.",
       "The goal names no purchase price."),
    _e("goal_no_amount", r"goal names no amount", "Das Ziel nennt keinen Betrag.", "The goal names no amount."),
    _e("needs_withdrawal_rate", r"withdrawal rate",
       "Ein jährlicher Bedarf wird erst mit einer noch nicht veröffentlichten Entnahmerate zu einem Kapitalbedarf.",
       "A yearly need becomes a capital requirement only at a withdrawal rate that is not yet published."),
    # Why a capital (E, N, H) is absent: lbs's constants NOT_ASKED, NOT_ANSWERED, WITHHELD.
    _e("not_asked", r"intake does not ask", "Das Erstgespräch fragt nicht danach.",
       "The intake does not ask about this."),
    _e("not_answered", r"asked and left blank", "Die Frage wurde gestellt und nicht beantwortet.",
       "The question was asked and left unanswered."),
    _e("withheld", r"filtered or erased", "Die Angabe wurde aus Datenschutzgründen entfernt.",
       "The information was removed for data protection."),
)

FALLBACK_REASON = {"de": "Dazu liegt keine Angabe vor.", "en": "No information is available on this."}

_NA_PREFIX = re.compile(r"^\s*not available(?:\s+in\s+[A-Za-z0-9_.@-]+)?\s*:?\s*", re.IGNORECASE)


def reason_entry(reason: str) -> Optional[Entry]:
    body = _NA_PREFIX.sub("", reason or "")
    return next((e for e in REASONS if e.pattern.search(body)), None)


def reason_text(reason: str, lang: str) -> str:
    """A sentence for why lbs could not compute something."""
    entry = reason_entry(reason)
    return entry.text[lang] if entry else FALLBACK_REASON[lang]


# ---------------------------------------------------------------------------
# lbs: gaps (section, input, kind, reason) and finding reasons
# ---------------------------------------------------------------------------

#: A gap's ``input``: the key of what is missing. Some carry an id (``p1.E``, ``<position>.vessel``); their
#: pattern matches the shape. The finding reasons of retirement and property findings are gap inputs too
#: (lbs names the gap after the reason), so they are here as well.
GAP_INPUTS: tuple[Entry, ...] = (
    _e("household", r"^household$", "Die Zusammensetzung des Haushalts ist nicht erfasst.",
       "The household composition is not recorded."),
    _e("civil_status", r"^civil_status$",
       "Der Zivilstand ist nicht erfasst; davon hängt die AHV-Plafonierung für Paare ab.",
       "The civil status is not recorded; the AHV cap for couples depends on it."),
    _e("composition_as_of", r"^composition_as_of$",
       "Die Angaben zum Haushalt sind veraltet; was darauf beruht, konnte nicht bestimmt werden.",
       "The household details are out of date; what rests on them could not be determined."),
    _e("household_income", r"^household_income$",
       "Das Haushaltseinkommen ist nicht bekannt: nicht für jede erwachsene Person ist ein Einkommen erfasst.",
       "The household income is not known: an income is not recorded for every adult."),
    _e("liabilities", r"^liabilities$",
       "Es sind keine Schulden erfasst. Das heisst nicht, dass keine bestehen; das Reinvermögen bleibt offen, "
       "bis Schulden erfasst oder ausdrücklich verneint sind.",
       "No debt is recorded. That does not mean there is none; net worth stays open until debts are recorded "
       "or expressly ruled out."),
    _e("assets", r"^assets$", "Es ist kein Vermögen erfasst.", "No assets are recorded."),
    _e("position_vessel", r"^.+\.vessel$", *_POSITION_VESSEL),
    _e("position_capital_type", r"^.+\.capital_type$",
       "Eine Position aus Humankapital ist diesem Ziel zugeordnet; Humankapital ist kein verfügbares Vermögen und "
       "zählt nicht als Eigenmittel.",
       "A human-capital position is assigned to this goal; human capital is not drawable wealth and does not count "
       "as equity."),
    _e("contribution_share", r"^contribution_share$",
       "Der Anteil des jährlichen Sparbetrags für dieses Ziel ist nicht angegeben; die erforderliche Rendite ist "
       "deshalb eine Untergrenze.",
       "This goal's share of the yearly saving is not stated, so the required return is a lower bound."),
    _e("vessel", r"^vessel$",
       "Bei einigen Vermögenswerten ist nicht angegeben, ob sie frei verfügbar, in der 2. Säule, in der Säule 3a "
       "oder Realwerte sind; sie zählen nicht zum frei verfügbaren Vermögen.",
       "Some assets do not say whether they are freely available, in the 2nd pillar, in pillar 3a or real "
       "assets; they are not counted as freely available."),
    _e("drawable", r"^drawable$", "Es ist kein frei verfügbares Finanzvermögen erfasst.",
       "No freely available financial assets are recorded."),
    _e("capital", r"^.+\.(?-i:[ENH])$", "{capital}: {why}", "{capital}: {why}"),
    _e("earning_power", r"^earning_power$", "Die Erwerbskraft berechnet ein anderes Modell; dieser Bericht "
       "enthält sie nicht.", "Earning power is computed by another model; this report does not contain it."),
    _e("ahv", r"^ahv$", "Die Grundlagen der AHV-Berechnung sind noch nicht freigegeben; es wird keine AHV-Rente "
       "gezeigt.", "The basis of the AHV calculation is not yet approved; no AHV pension is shown."),
    _e("mdje", r"^mdje$", "Weder ein massgebendes durchschnittliches Jahreseinkommen noch ein Bruttoeinkommen ist "
       "erfasst.", "Neither an average annual income for the AHV nor a gross income is recorded."),
    _e("bvg", r"^bvg$", "Die Grundlagen der Pensionskassen-Projektion sind noch nicht freigegeben.",
       "The basis of the pension fund projection is not yet approved."),
    _e("age", r"^age$", "Das Alter der Person ist nicht erfasst; die Pensionskassen-Projektion geht davon aus.",
       "The person's age is not recorded; the pension fund projection starts from it."),
    _e("gross_income", r"^gross_income$",
       "Für die Person ist kein Bruttolohn erfasst; die Pensionskassen-Projektion braucht ihn.",
       "No gross salary is recorded for the person; the pension fund projection needs it."),
    _e("pillar_2_balance", r"^pillar_2_balance$",
       "Für die Person ist kein Pensionskassenguthaben erfasst; die Projektion beginnt bei null.",
       "No pension fund balance is recorded for the person; the projection starts at zero."),
    _e("property-funding", r"^property-funding$", *_PROPERTY_RULES),
    _e("occupancy", r"^occupancy$",
       "Es ist nicht verständlich angegeben, ob das Wohneigentum selbst bewohnt oder vermietet wird.",
       "It is not clearly stated whether the property will be lived in or let."),
    _e("the_goal_names_no_amount", r"^the_goal_names_no_amount$", "Das Ziel nennt keinen Betrag.",
       "The goal names no amount."),
    _e("the_goal_does_not_say_whether_the_member_will_live_in_it",
       r"^the_goal_does_not_say_whether_the_member_will_live_in_it$",
       "Das Ziel sagt nicht, ob Sie selbst darin wohnen werden.",
       "The goal does not say whether you will live in the property yourself."),
    _e("the_goal_names_an_occupancy_the_record_does_not_declare",
       r"^the_goal_names_an_occupancy_the_record_does_not_declare$",
       "Es ist nicht verständlich angegeben, ob das Wohneigentum selbst bewohnt oder vermietet wird.",
       "It is not clearly stated whether the property will be lived in or let."),
    _e("no_position_is_linked_to_this_goal", r"^no_position_is_linked_to_this_goal$",
       "Mit diesem Ziel ist keine Vermögensposition verknüpft.", "No asset is linked to this goal."),
    _e("a_funding_position_states_no_vessel", r"^a_funding_position_states_no_vessel$", *_POSITION_VESSEL),
    _e("rental_income_is_not_modelled_for_a_let_property", r"^rental_income_is_not_modelled_for_a_let_property$",
       "Mieteinnahmen aus vermietetem Wohneigentum werden nicht berechnet.",
       "Rental income from a let property is not calculated."),
    _e("no_income_is_recorded_for_the_household", r"^no_income_is_recorded_for_the_household$",
       *_NO_HOUSEHOLD_INCOME),
    _e("the_household_composition_is_past_its_validity_horizon",
       r"^the_household_composition_is_past_its_validity_horizon$", *_COMPOSITION),
    _e("the_property_conventions_are_not_approved", r"^the_property_conventions_are_not_approved$",
       *_PROPERTY_RULES),
    _e("the_members_age_is_not_recorded", r"^the_members_age_is_not_recorded$", "Ihr Alter ist nicht erfasst.",
       "Your age is not recorded."),
    _e("the_goal_names_no_yearly_amount", r"^the_goal_names_no_yearly_amount$",
       "Das Ziel nennt keinen jährlichen Betrag.", "The goal names no yearly amount."),
    _e("the_ahv_table_is_not_approved", r"^the_ahv_table_is_not_approved$",
       "Die AHV-Rententabelle ist noch nicht freigegeben.", "The AHV pension table is not yet approved."),
    _e("the_pension_projection_record_is_not_approved", r"^the_pension_projection_record_is_not_approved$",
       "Die Grundlagen der Pensionskassen-Projektion sind noch nicht freigegeben.",
       "The basis of the pension fund projection is not yet approved."),
    _e("horizon_years", r"^horizon_years$",
       "Kein Ziel ist datiert, und ohne das Alter lässt sich der Anlagehorizont nicht bestimmen.",
       "No goal is dated, and without the age the investment horizon cannot be determined."),
    _e("risk-profile", r"^risk-profile$",
       "Die Regeln des Risikoprofils sind noch nicht freigegeben; es wird kein Profil abgeleitet.",
       "The rules of the risk profile are not yet approved; no profile is derived."),
    _e("profile", r"^profile$",
       "Weder die Vermögenslage noch eine angegebene Risikobereitschaft konnte gelesen werden.",
       "Neither the financial position nor a stated willingness to take risk could be read."),
    _e("mandate.goal_id", r"^mandate\.goal_id$",
       "Für den Mandatsvorschlag ist kein Ziel bestimmt; welchem Ziel das Portfolio dient, ist Ihre Entscheidung.",
       "No goal is designated for the mandate proposal; which goal the portfolio serves is your decision."),
    _e("target_amount", r"^target_amount$", "Das Ziel nennt keinen Betrag oder Kaufpreis.",
       "The goal names no amount or purchase price."),
    _e("target_capital", r"^target_capital$",
       "Ein jährlicher Bedarf wird erst mit einer noch nicht veröffentlichten Entnahmerate zu einem Kapitalbedarf.",
       "A yearly need becomes a capital requirement only at a withdrawal rate that is not yet published."),
    _e("target_date", r"^target_date$",
       "Das Ziel hat kein Datum in der Zukunft; ein Anlagehorizont lässt sich nicht bestimmen.",
       "The goal has no date in the future; an investment horizon cannot be determined."),
    _e("annual_contribution", r"^annual_contribution$", "Der jährliche Sparbetrag für das Ziel ist nicht angegeben.",
       "The yearly contribution towards the goal is not stated."),
    # The real view (lbs LBS-31, REP-27).
    _e("amount_basis", r"^amount_basis$",
       "Der Betrag des Ziels ist in künftigen Franken angegeben, aber das Ziel hat kein Datum; in heutigen Franken "
       "lässt er sich nicht lesen.",
       "The goal’s amount is stated in future francs, but the goal has no date; it cannot be read in today’s "
       "francs."),
    _e("the_need_is_in_future_francs_and_the_goal_has_no_date_to_read_it_in_todays_francs",
       r"^the_need_is_in_future_francs_and_the_goal_has_no_date_to_read_it_in_todays_francs$",
       "Der Bedarf ist in künftigen Franken angegeben, aber das Ziel hat kein Datum; in heutigen Franken lässt er "
       "sich nicht lesen.",
       "The need is stated in future francs, but the goal has no date; it cannot be read in today’s francs."),
    _e("required_return", r"^required_return$",
       "Das Ziel ist mit keiner plausiblen Rendite erreichbar; die Hebel sind Zeithorizont, Sparbeiträge, "
       "Startvermögen und Zielgrösse, nicht die Allokation.",
       "The goal cannot be reached at any plausible return; the levers are the horizon, the contributions, the "
       "starting wealth and the size of the goal, not the allocation."),
)

#: A gap's ``kind``: the fallback sentence when its input is not known here.
GAP_KINDS: dict[str, Texts] = {
    "not_in_the_request": {"de": "Eine Angabe dazu fehlt.", "en": "Some information on this is missing."},
    "past_its_validity_horizon": {"de": "Eine Angabe dazu ist veraltet und muss bestätigt werden.",
                                  "en": "Some information on this is out of date and needs confirming."},
    "owned_by_another_engine": {"de": "Dies berechnet ein anderes Modell; dieser Bericht enthält es nicht.",
                                "en": "This is computed by another model; this report does not contain it."},
    "record_not_approved": {"de": "Die Berechnungsgrundlagen dazu sind noch nicht freigegeben.",
                            "en": "The basis for this calculation is not yet approved."},
    "needs_an_unpublished_assumption": {"de": "Dafür fehlt eine Annahme, die noch nicht veröffentlicht ist.",
                                        "en": "This needs an assumption that is not yet published."},
}
FALLBACK_GAP = {"de": "Dazu fehlt eine Angabe.", "en": "Some information is missing here."}

CAPITAL_NAMES = {"de": {"E": "Expertise (E)", "N": "Netzwerk (N)", "H": "Gesundheit (H)"},
                 "en": {"E": "Expertise (E)", "N": "Network (N)", "H": "Health (H)"}}


def gap_entry(input_: str) -> Optional[Entry]:
    return next((e for e in GAP_INPUTS if e.pattern.search(input_ or "")), None)


def gap_text(input_: str, kind: str, reason: str, lang: str) -> str:
    """A sentence for one lbs gap."""
    entry = gap_entry(input_)
    if entry is None:
        return GAP_KINDS.get(kind, FALLBACK_GAP)[lang]
    if entry.key == "capital":
        cap = input_.rsplit(".", 1)[1]
        return entry.text[lang].format(capital=CAPITAL_NAMES[lang][cap], why=reason_text(reason, lang))
    return entry.text[lang]


#: A liquidity finding's reason, and the lever reasons of lbs's liquidity analysis.
FINDING_REASONS: dict[str, Texts] = {
    "funding_is_illiquid": {"de": "Das Ziel wird aus Vermögen finanziert, das bis zum Fälligkeitsdatum nicht "
                                  "verfügbar ist.",
                            "en": "The goal is funded from assets that are not available by its due date."},
    "vorsorge_capital_only_for_an_owner_occupied_primary_residence": {
        "de": "Vorsorgekapital darf nur für selbst bewohntes Wohneigentum eingesetzt werden.",
        "en": "Pension capital may be used only for a home you live in yourself."},
    "no_single_lever_closes_the_gap": {"de": "Keine einzelne Massnahme schliesst die Lücke.",
                                       "en": "No single measure closes the gap."},
    "a_lever_could_not_be_determined": {"de": "Eine der möglichen Massnahmen konnte nicht bestimmt werden.",
                                        "en": "One of the possible measures could not be determined."},
}
FALLBACK_FINDING = {"de": "Für dieses Ziel besteht ein Hinweis zur Liquidität.",
                    "en": "There is a note on liquidity for this goal."}


def finding_text(reason: str, lang: str) -> str:
    return FINDING_REASONS.get(reason, FALLBACK_FINDING)[lang]


#: What binds a risk profile or a property finding.
BINDS: dict[str, Texts] = {
    "both": {"de": "Risikobereitschaft und Risikofähigkeit", "en": "willingness and capacity to take risk"},
    "willingness": {"de": "Risikobereitschaft", "en": "willingness to take risk"},
    "capacity": {"de": "Risikofähigkeit", "en": "capacity to take risk"},
    "equity": {"de": "Eigenmittel", "en": "equity"},
    "affordability": {"de": "Tragbarkeit", "en": "affordability"},
}


def binds_text(value: str, lang: str) -> str:
    return BINDS.get(value, {"de": "nicht angegeben", "en": "not stated"})[lang]


# ---------------------------------------------------------------------------
# pcp: the coverage warnings of an Allocation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PcpWarning:
    key: str
    #: The literal start of the sentence in pcp's source (``tests/test_vocabulary.py`` finds each there).
    source_prefix: str
    pattern: Pattern[str]
    text: Texts


_REAL_NOTE = "real basis: the target curve and every profile are net of inflation"
_REAL_TEXT = ("Die Renditen dieser Allokation sind real: die Zielkurve und alle Profile sind um die Teuerung "
              "bereinigt.",
              "The returns of this allocation are real: the target curve and every profile are net of "
              "inflation.")

PCP_WARNINGS: tuple[PcpWarning, ...] = (
    PcpWarning("same_esg", "every instrument carries the same ESG score", re.compile(r"same ESG score"),
               {"de": "Alle Bausteine haben dieselbe ESG-Bewertung, deshalb unterscheidet die ESG-Vorgabe nicht "
                      "zwischen ihnen.",
                "en": "Every building block has the same ESG score, so the ESG requirement does not tell them "
                      "apart."}),
    PcpWarning("constraints_drive", "the weights control", re.compile(r"^the weights control"),
               {"de": "Die Gewichte bestimmen nur einen kleinen Teil der Zielfunktion: die Allokation folgt vor "
                      "allem den Vorgaben des Mandats.",
                "en": "The weights decide only a small part of the objective: the allocation follows mainly the "
                      "mandate's constraints."}),
    PcpWarning("weak_profiles", "of the weight is on instruments whose profiles rest on borrowed",
               re.compile(r"of the weight is on instruments whose profiles rest on borrowed"),
               {"de": "Ein Teil des Gewichts liegt auf Bausteinen, deren Profile auf geliehenen oder gesetzten "
                      "Werten beruhen.",
                "en": "Part of the weight is on building blocks whose profiles rest on borrowed or seeded "
                      "values."}),
    PcpWarning("feasible_start_converged", "from a feasible start with the exact settings, on the",
               re.compile(r"from a feasible start with the exact settings, on the"),
               {"de": "Die Optimierung hat von einem zulässigen Startpunkt aus mit den genauen Einstellungen zu "
                      "einer Lösung gefunden.",
                "en": "The optimiser reached a solution from a feasible starting point with the exact settings."}),
    PcpWarning("feasible_start_unsettled", "from a feasible start with the exact settings did not settle",
               re.compile(r"from a feasible start with the exact settings did not settle"),
               {"de": "Von einem zulässigen Startpunkt aus hat die Optimierung mit den genauen Einstellungen "
                      "keine Lösung gefunden.",
                "en": "From a feasible starting point with the exact settings the optimiser did not reach a "
                      "solution."}),
    PcpWarning("fallback_failed", "did not converge either", re.compile(r"did not converge either"),
               {"de": "Auch das Ersatzverfahren der Optimierung hat nicht zu einer Lösung gefunden.",
                "en": "The optimiser's fallback method did not reach a solution either."}),
    PcpWarning("not_converged", "did not converge (", re.compile(r"did not converge \("),
               {"de": "Das erste Verfahren der Optimierung hat nicht zu einer Lösung gefunden; ein Ersatzverfahren "
                      "wurde eingesetzt.",
                "en": "The optimiser's first method did not reach a solution; a fallback method was used."}),
    # The real view (pcp PCP-22, REP-28): most specific first, the deflator's labels read from pcp's note.
    PcpWarning("real_basis_hard_currency", _REAL_NOTE, re.compile(r"^real basis: .*hard-currency fallback"),
               {"de": _REAL_TEXT[0] + " Für einen Teil der Marktlagen ist in einer harten Währung gerechnet, weil "
                      "die Teuerung dort ausserhalb des berechenbaren Bereichs liegt.",
                "en": _REAL_TEXT[1] + " For some market states the figures are computed in a hard currency, because "
                      "inflation there lies outside the computable band."}),
    PcpWarning("real_basis_estimated", _REAL_NOTE,
               re.compile(r"^real basis: .*\b(extrapolated|fallback|not_computable)\b"),
               {"de": _REAL_TEXT[0] + " Für einen Teil der Marktlagen ist die Teuerung geschätzt, nicht gemessen.",
                "en": _REAL_TEXT[1] + " For some market states the inflation is estimated, not measured."}),
    PcpWarning("real_basis", _REAL_NOTE, re.compile(r"^real basis: the target curve"),
               {"de": _REAL_TEXT[0], "en": _REAL_TEXT[1]}),
)
FALLBACK_PCP = {"de": "Die Optimierung meldet einen weiteren Hinweis zu dieser Allokation.",
                "en": "The optimiser reports a further note on this allocation."}


def pcp_warning_text(warning: str, lang: str) -> str:
    entry = next((w for w in PCP_WARNINGS if w.pattern.search(warning or "")), None)
    return entry.text[lang] if entry else FALLBACK_PCP[lang]


# ---------------------------------------------------------------------------
# The four roles, by the house's names (REP-24)
# ---------------------------------------------------------------------------

#: The display names the house fixed in the content record ``reference/roles``
#: (``Projects/eigentliCH/Prototype/client/content/roles.json``, reviewed by the owner on 30.08.2026), per role
#: and capital type. The financial side of ``gain`` is "Wertsteigerung" / "Gain", its human side "Wachstum" /
#: "Growth"; "Einkommen" (not "Ertrag") and "Absicherung" (not "Schutz") on both sides. A copy, not an import:
#: engines share contracts, not files; ``tests/test_vocabulary.py`` compares it with the record when it is there.
ROLE_NAMES: dict[str, dict[str, Texts]] = {
    "gain": {"human": {"de": "Wachstum", "en": "Growth"},
             "financial": {"de": "Wertsteigerung", "en": "Gain"}},
    "income": {"human": {"de": "Einkommen", "en": "Income"},
               "financial": {"de": "Einkommen", "en": "Income"}},
    "stabilisation": {"human": {"de": "Stabilisierung", "en": "Stabilisation"},
                      "financial": {"de": "Stabilisierung", "en": "Stabilisation"}},
    "protection": {"human": {"de": "Absicherung", "en": "Protection"},
                   "financial": {"de": "Absicherung", "en": "Protection"}},
}
#: The record's stored key for the first role is ``growth``; lbs and pcp say ``gain`` (``Gain``).
ROLE_ALIASES = {"growth": "gain"}


def role_name(role: str, lang: str, capital_type: str = "financial") -> str:
    """The house's name of a role in the reader's language. pcp's roles are financial; an lbs grid cell names
    its capital type. An unknown role is shown as given (the vocabulary test keeps the known ones complete)."""
    key = ROLE_ALIASES.get(role.lower(), role.lower())
    names = ROLE_NAMES.get(key)
    if names is None:
        return role
    return names.get(capital_type, names["financial"])[lang]


# ---------------------------------------------------------------------------
# Subjects: persons and goals named for readers (REP-20)
# ---------------------------------------------------------------------------

PERSON = {"de": "Person {n}", "en": "Person {n}"}
GOAL = {
    "property": {"de": "Ihr Wohneigentumsziel", "en": "Your home ownership goal"},
    "retirement": {"de": "Ihr Ruhestandsziel", "en": "Your retirement goal"},
    "goal": {"de": "Ihr Ziel", "en": "Your goal"},
}
#: A topic, for a note that names no person and no goal.
TOPIC = {
    "household": {"de": "Haushalt", "en": "Household"},
    "totals": {"de": "Bilanz", "en": "Balance sheet"},
    "human_capital": {"de": "Humankapital", "en": "Human capital"},
    "pensions": {"de": "Renten", "en": "Pensions"},
    "retirement": {"de": "Ruhestand", "en": "Retirement"},
    "property": {"de": "Wohneigentum", "en": "Home ownership"},
    "liquidity": {"de": "Liquidität", "en": "Liquidity"},
    "risk_profile": {"de": "Risikoprofil", "en": "Risk profile"},
    "mandate_proposal": {"de": "Mandatsvorschlag", "en": "Mandate proposal"},
    "allocation": {"de": "Allokation", "en": "Allocation"},
    "other": {"de": "Hinweis", "en": "Note"},
}
UNNAMED = {"de": "ohne eigenen Namen", "en": "without a name of its own"}


def goal_kind(kind: Optional[str]) -> str:
    k = (kind or "").lower()
    return "property" if k.startswith("propert") else "retirement" if k.startswith("retire") else "goal"


def subjects(persons: list[str], goals: list[tuple[str, str]], lang: str) -> dict[str, str]:
    """``person:<id>`` and ``goal:<id>`` to a generic name: persons numbered in household order, goals by kind,
    numbered only when a kind occurs more than once."""
    out = {f"person:{pid}": PERSON[lang].format(n=n) for n, pid in enumerate(dict.fromkeys(persons), start=1)}
    kinds: dict[str, str] = {}
    for gid, kind in goals:
        kinds.setdefault(gid, goal_kind(kind))
    counts: dict[str, int] = {}
    for kind in kinds.values():
        counts[kind] = counts.get(kind, 0) + 1
    seen: dict[str, int] = {}
    for gid, kind in kinds.items():
        base = GOAL[kind][lang]
        if counts[kind] > 1:
            seen[kind] = seen.get(kind, 0) + 1
            base = f"{base} {seen[kind]}"
        out[f"goal:{gid}"] = base
    return out


#: Display-fact keys that name a subject instead of being shown in the header (REP-20).
NAMING_KEY = re.compile(r"^(person|goal)\.(.+)$")


def display_names(display_facts, subject_names: Mapping[str, str]) -> dict[str, str]:
    """Generic name to the caller's name, for the subjects the caller named (``person.<id>``, ``goal.<id>``)."""
    out: dict[str, str] = {}
    for f in display_facts:
        m = NAMING_KEY.match(f.key)
        if m and isinstance(f.value, str) and f.value.strip():
            generic = subject_names.get(f"{m.group(1)}:{m.group(2)}")
            if generic:
                out[generic] = f.value.strip()
    return out


def apply_names(text: str, names: Mapping[str, str]) -> str:
    """``text`` with each generic subject name replaced by the caller's name (longest first, whole words)."""
    for generic in sorted(names, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(generic) + r"(?![\w])", lambda _m, g=generic: names[g], text)
    return text


# ---------------------------------------------------------------------------
# The engine's own notes on the page, in the reader's language
# ---------------------------------------------------------------------------

PAGE_NOTES: dict[str, Texts] = {
    "prose_withheld": {"de": "Der verbindende Text zum Abschnitt «{title}» ist zurückgehalten: er nannte eine Zahl, "
                             "die in den Fakten des Abschnitts nicht vorkommt.",
                       "en": "The connecting text for the section “{title}” is withheld: it named a figure that is "
                             "not among the section's facts."},
    "prose_missing": {"de": "Die verbindenden Sätze fehlen, weil {assistant} gerade nicht erreichbar war. Der Bericht "
                            "steht ohne sie; eine neue Anfrage versucht es erneut.",
                      "en": "The connecting sentences are missing because {assistant} could not be reached. The "
                            "report stands without them; asking again tries again."},
}


def page_note(key: str, lang: str, **values: str) -> str:
    return PAGE_NOTES[key][lang].format(**values)


# ---------------------------------------------------------------------------
# The basis of return and goal figures (REP-27): nominal or real, always shown
# ---------------------------------------------------------------------------

#: The header line: what every amount on the page is.
BASIS_HEADER: dict[str, Texts] = {
    "nominal": {"de": "Alle Beträge nominal.", "en": "All amounts nominal."},
    "real": {"de": "Alle Beträge in heutigen Franken (real).", "en": "All amounts in today’s francs (real)."},
}
#: The word printed next to every return and goal figure.
BASIS_MARK: dict[str, Texts] = {
    "nominal": {"de": "nominal", "en": "nominal"},
    "real": {"de": "real", "en": "real"},
}
#: The header's second line in a real report that still carries a figure lbs gives in nominal terms only (a
#: BVG projection, a liquidity gap, a contribution fixed in francs).
BASIS_NOMINAL_KEPT: Texts = {
    "de": "Wo «nominal» steht, ist die Zahl nicht teuerungsbereinigt.",
    "en": "A figure marked “nominal” is not adjusted for inflation.",
}
#: The basis of an Allocation's returns, as the allocation section states it.
BASIS_ALLOCATION: dict[str, Texts] = {
    "nominal": {"de": "nominal", "en": "nominal"},
    "real": {"de": "real, teuerungsbereinigt", "en": "real, net of inflation"},
}
BASIS_ALLOCATION_LABEL: Texts = {"de": "Grundlage der Renditen", "en": "Basis of the returns"}
#: What the model is told about the marked figures (part of the prompt and its hash).
BASIS_PROMPT: dict[str, Texts] = {
    "nominal": {"de": " Zahlen mit dem Vermerk «nominal» sind nicht teuerungsbereinigt.",
                "en": " Figures marked “nominal” are not adjusted for inflation."},
    "real": {"de": " Zahlen mit dem Vermerk «real» sind teuerungsbereinigt, in heutigen Franken; nenne sie so.",
             "en": " Figures marked “real” are adjusted for inflation, in today's francs; call them that."},
}


def basis_mark(basis: str, lang: str) -> str:
    return BASIS_MARK[basis][lang]
#: The words of lbs's real view (REP-27): its inflation assumption, the contribution, the plausibility.
BASIS_WORDS: dict[str, Texts] = {
    "inflation": {"de": "Teuerungsannahme pro Jahr", "en": "Inflation assumed a year"},
    "inflation_label": {"de": "Teuerungsannahme", "en": "Inflation assumption"},
    "measured": {"de": "gemessen", "en": "measured"},
    "extrapolated": {"de": "über den gemessenen Bereich hinaus geschätzt", "en": "estimated beyond the measured range"},
    "indexed": {"de": "Beitrag steigt mit der Teuerung", "en": "Contribution rises with prices"},
    "plausibility": {"de": "Nötige Rendite, gemessen am Risikoprofil", "en": "Required return, given the risk profile"},
}
JUDGEMENT: dict[str, Texts] = {
    "realistic": {"de": "realistisch", "en": "realistic"},
    "not_realistic": {"de": "nicht realistisch", "en": "not realistic"},
    "could_not_be_determined": {"de": "nicht bestimmbar", "en": "could not be determined"},
}
