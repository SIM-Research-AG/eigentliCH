"""The Befund — a written standing report a member can read, derived from what they have recorded.

**Why this module exists.** Every other member-facing surface is a capture form, a view of what was
captured, or authored content. Nothing synthesised. The owner's words: *"I can put all the information in
but I don't get anything out of it."* This is the missing piece, and it is a **report**, not an assessment.

**The division of labour is Reporting_Machine's, taken verbatim: code owns the figures and the structure,
the model only writes sentences.** Every value, every section, every ordering decision here is computed in
Python from the database and is reproducible. `prose=True` lets the local model *rephrase* one already
complete sentence and gives it no latitude at all: a rephrasing is accepted only if it carries exactly the
same figures, adds no sentence, and passes C-01 — otherwise the computed sentence stands. With the model
off, or absent, or slow, the report is unchanged. `render_befund` defaults to `prose=False`, so the
deterministic report is the product and the model is an option on top of it.

---

## The four constraints that shaped every design decision here

**C-07 — no gamification primitives, and R-113's specific form of it.** The role grid payload carries no
filled count, no total and no ratio, and `services/grid.py` explains why: a payload holding
`filled: 3, total: 8` is a completion meter that has not been drawn yet. The same reasoning governs a
report, which is why **this module counts nothing**. It does not say how many cells are empty, how many
goals are unfunded, or how many decisions have been recorded. It *names* each one, one fact at a time. A
member who reads three empty cells knows there are three; a member who is told "3 of 8" has been handed a
score. Naming is a list, counting is a meter, and the difference is the whole of R-113.

The estate's `score_engine` produces a `Score` and A6 scoped C-07's grep to the member layer deliberately,
because that Score is an analytical measure rather than a game mechanic. It is still never surfaced here —
see `ENGINES_WITHHELD_FROM_A_MEMBER`.

**C-01 — no personalised recommendation.** A report about someone's own plan is one sentence away from
advice, and this is the sharpest edge in the module. Two mechanisms:

  1. *Every sentence this module composes is checked by `boundary.check_answer` at the moment the `Fact`
     is constructed*, in `Fact.__post_init__`. Not in a review pass that a future section could forget to
     run — in the constructor, so a section that composes an advisory sentence cannot produce a `Fact` at
     all. A refusal raises `BefundWouldAdvise` and is never quietly reworded: A78's practice is that a
     refusal is a finding about the gate, and a report that silently rephrases itself past the gate
     destroys the evidence.
  2. *Member-authored text is never merged into a composed sentence.* A member may name a position
     `Fonds X für mich kaufen`; that is their prose about their own plan and C-01 has nothing to say about
     it. But if it were interpolated into a sentence eigentliCH composes, the composed sentence would fail
     the gate and the member's whole report would become unrenderable because of what they typed. So
     quoted material travels in `Fact.quoted`, beside the sentence and never inside it, and `Fact.subject`
     names which quoted key a renderer should put in front of the sentence. The sentence is the part
     eigentliCH says; the quotation is the part the member said.

**And a third mechanism, because the first two are not enough, and the reason is a finding.** C-01's
outbound rules conjoin directive force with *a financial object drawn from its instrument lexicon*. The
Befund's entire subject matter — `Position`, `Ziel`, `Deckung`, `Gefäss`, `Rolle`, `Beleg` — is the plan's
own vocabulary, and none of it is in that lexicon. Probed, not reasoned about (A76's instruction), and
every one of these **passes** the live gate:

    Sie sollten eine Position als Deckung dieses Ziels hinterlegen.        passes
    Für dieses Ziel wäre ein liquideres Gefäss besser.                    passes
    Von den beiden Möglichkeiten ist die erste für Sie die geeignetere.    passes

This is A76's recorded hole in a new place: the gate has nothing to conjoin with, exactly as it has
nothing to conjoin with a bare ticker. So `check_answer` passing is a **much weaker** guarantee for a
report about a plan than it is for an answer about instruments, and it must not be mistaken for the
whole of C-01 here.

The third mechanism is therefore local and closed: `FORBIDDEN_MOODS` scans this module's own copy table
for directive and evaluative constructions. A blacklist is unbounded over the space of sentences a model
might produce — A76's whole argument — but it is *exhaustive* over a table of fifty phrases one author
writes and a test reads. That is the one shape in which a word list is a real guard, and it is why the
copy lives in a table here rather than being composed at each call site.

**C-02 — no figure derived from an assumption without the `assumption_set_id` that produced it.** Every
`Fact` declares its provenance, and `Fact.__post_init__` enforces the biconditional: `source ==
"assumption"` if and only if `assumption_set_id` is set. The Befund as built computes **no** assumption-
derived figure — it projects nothing, it discounts nothing, it capitalises nothing — so no fact carries
that source and the envelope says so in `assumptions`. The machinery is here rather than deferred because
the day someone adds an illustration to this report, the invariant is already load-bearing.

**C-04 — every field read carries a data class.** Each `Fact` declares the highest class it read, and each
section declares the highest of its facts. Quoting a vault document's title is quoting K3, and the fact
that does it says K3 on its face rather than leaving a caller to work it out from the section it is in.

**R-175 — nothing is proactive.** The report is produced when it is asked for. It writes nothing, it
schedules nothing, and it notifies nobody. `delivered_on_request_only` is in the payload so a client
author reads it before building something that polls.

---

## What the report is allowed to say, and where the line runs

Stating a fact about the plan is allowed. Telling the member what to do about it is not.

    allowed    "this goal has no position recorded as funding it"
    allowed    "your plan does not record this, and an estimate would stand in place of what you did not say"
    refused    anything with a verb telling the member to change it

There is no summary judgement anywhere: no score, no grade, no percentage, no "your plan is 60% ready", no
"on track". Those were not omitted for want of room. A report that ends in a verdict is an assessment, and
an assessment of a member's plan by a machine is the thing this product exists instead of.

**The most valuable section is `not_known`.** `services/engine_inputs.py` already records, per engine,
exactly which inputs the plan cannot fill and why, in four kinds — A39's "gaps left visible". Two of those
kinds mean the member's plan does not answer the question, and those two are a ready-made honest account
of what eigentliCH does not know about them. It is read through that module rather than recomputed, and the
engine's own reason travels verbatim in `values["inputs"]` while the member-facing sentence is this
module's own copy: an English explanation of a `W_L` gap does not belong in a German report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..content import DEFAULT_LANGUAGE, LANGUAGES, role_definition, role_display
from ..models import (
    ADULT,
    CAPITAL_TYPES,
    DEPENDANT,
    DataClass,
    Decision,
    Position,
    ROLES,
    VaultItem,
)
from . import currency as currency_service
from . import engine_inputs
from .engine_inputs import stated_stocks
from .goals import list_goals
from .household import current as current_household
from .know import action_items
from .version import standing as standing_plan
from .vault import current_items

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The sections, in the order they are always rendered. Fixed here rather than sorted, because the order
#: is editorial — what the plan holds, then what it is for, then what was decided, then what carries a
#: date, then what is prepared, then what is not known — and an alphabetical report would open on
#: `decisions` for no reason a reader could name.
SECTIONS = (
    # First, because it is the frame the rest is read inside: the AHV path, the tax path and goal
    # ownership all follow from it, and a figure about a household of two means nothing to a reader who
    # has been told the household is one. It is also the only section that can degrade — see `Fact`.
    "household",
    "plan",
    "goals",
    "decisions",
    "expiries",
    "prepared_decisions",
    "not_known",
)

#: Where a fact's values came from. A closed list so a test can assert no section invented a fifth, and so
#: that C-02's condition is checkable rather than a matter of reading the sentence.
#:
#:   member_stated       the member typed it: a magnitude, a target date, a decision they recorded
#:   computed_from_plan  arithmetic or set logic over what the member typed, and nothing else
#:   content             a role definition or a template purpose, from `client/content/` (K0)
#:   assumption          derived from a published AssumptionSet — REQUIRES an assumption_set_id
PROVENANCE = ("member_stated", "computed_from_plan", "content", "assumption")

#: Engines whose gap list is never shown to a member, and the reason for each. Both are C- constraints
#: rather than taste.
#:
#: `score_engine` — A6 kept the name because the estate's `Score` is an analytical household-standing
#: measure, and scoped C-07's grep to the member layer accordingly. That narrowing is not a licence to
#: render it: listing the inputs the Score lacks invites exactly one question — "so what would my score
#: be" — and that question is the primitive C-07 forbids. Its own `EnginePlan.notes` say the output "must
#: never reach a member as a level, a rank or a progress meter".
#:
#: `portfolio_optimiser` — its single plan gap is a *mandate*, an investment policy. Telling a member
#: their plan lacks one is a sentence away from offering to write one, and the gap's own recorded reason
#: says writing one would be "the C-01 boundary crossed twice over". The gap is real and stays visible to
#: a curator through `engine_inputs.gap_report`; it is not member-facing material.
ENGINES_WITHHELD_FROM_A_MEMBER = ("portfolio_optimiser", "score_engine")

#: Engine input name -> the subject a member would recognise. The engines speak `W_L` and `initial_wealth`;
#: a member does not, and putting a manifest's field name in a report is a way of saying nothing.
#:
#: **A lookup that raises rather than skips.** If an engine declares a new plan-blocking input and nobody
#: writes a subject for it, the report must fail loudly, not quietly drop the gap — the whole value of
#: this section is that it is complete. `test_every_reportable_gap_has_a_member_facing_subject` is the
#: guard, and it walks the live manifests rather than this table.
GAP_SUBJECTS = {
    "W_L": "human_capital_amount",
    "W_R": "financial_capital_amount",
    "initial_wealth": "financial_capital_amount",
    "D": "debt",
    "E": "engine_state_variable",
    "annual_return": "return_assumption",
    "base_snapshot_id": "numbered_baseline",
}

#: Constructions this module's copy may not contain, in either language. Directive force and evaluative
#: comparison — the two things a report is not allowed to do about a member's own plan.
#:
#: **This is a closed-set guard and not a blacklist in A76's sense.** It is read against `PHRASE` and
#: `SECTION_TITLE`, which are fifty-odd strings one author writes; exhaustiveness over that is achievable
#: in a way exhaustiveness over "sentences a model might emit" is not. It exists because the live C-01
#: gate does not refuse plan-directed advice — see the module docstring's third mechanism, and the probes
#: recorded there.
#:
#: `sollen` is not here and `sollten` is: `was hier stehen soll` is a statement about the schema, and the
#: subjunctive is the one that addresses the member. `müssen` is not here either — a statement of what
#: the law obliges is admitted (A83), and this module states none anyway.
FORBIDDEN_MOODS = (
    # German — directive
    r"\bsie\s+sollten\b",
    r"\bsie\s+m(?:ü|ue)ssten\b",
    r"\bsie\s+k(?:ö|oe)nnten\b",
    r"\bwir\s+empfehlen\b",
    r"\bempfehlenswert\b",
    r"\bam\s+besten\b",
    r"\bratsam\b",
    r"\ban\s+ihrer\s+stelle\b",
    r"\bn(?:ä|ae)chster\s+schritt\b",
    # German — evaluative comparison about the member.
    #
    # **Across the clause, not adjacent, and that is what the probes taught.** The first version required
    # the comparative to follow the trigger word directly, and both
    # `Für dieses Ziel wäre ein liquideres Gefäss besser` and
    # `Von den beiden Möglichkeiten ist die erste für Sie die geeignetere` walked straight through it —
    # German puts the comparative at the end of the clause, which is precisely where an adjacency rule
    # cannot see it. A78 found the same shape in `boundary.py`'s own comparative patterns.
    #
    # Bounded to one clause by `[^.!?;]`, so a trigger in one sentence cannot marry a comparative in the
    # next. That is `boundary.py`'s own per-sentence discipline, for the same reason.
    r"\bf(?:ü|ue)r\s+sie\b[^.!?;]{0,60}?\b(?:besser|geeignet\w*|sinnvoll\w*|passend\w*|"
    r"g(?:ü|ue)nstiger|vorteilhaft\w*)\b",
    r"\bw(?:ä|ae)re\b[^.!?;]{0,60}?\b(?:besser|geeignet\w*|sinnvoll\w*|passend\w*|"
    r"vorteilhaft\w*)\b",
    r"\bgut\s+aufgestellt\b",
    r"\bauf\s+kurs\b",
    # English — directive
    r"\byou\s+should\b",
    r"\byou\s+ought\s+to\b",
    r"\bwe\s+recommend\b",
    r"\bwe\s+suggest\b",
    r"\bwe\s+advise\b",
    r"\bbest\s+to\b",
    r"\bnext\s+step\b",
    r"\bmake\s+sure\b",
    # English — evaluative comparison about the member, across the clause for the same reason.
    r"\bbetter\b[^.!?;]{0,40}?\bfor\s+you\b",
    r"\bfor\s+you\b[^.!?;]{0,40}?\b(?:better|more\s+suitable|preferable)\b",
    r"\bmore\s+suitable\b",
    r"\bpreferable\b",
    r"\bon\s+track\b",
    r"\bwell\s+positioned\b",
)

#: How much longer than the computed sentence a model rephrasing may be. An integer multiplier: a float
#: literal in a service is what C-02's structural test forbids, and it was right to (see `llm/__init__.py`
#: on where a tuning constant belongs).
PROSE_LENGTH_ALLOWANCE = 2


class BefundWouldAdvise(Exception):
    """A sentence this module composed was refused by C-01's outbound gate.

    **Raised, never swallowed and never worked around by rewording in place.** A78 records the practice
    and the reason: the author of the German knowledge content was told to report any sentence the gate
    refused rather than quietly rephrasing it, because a refusal of genuinely factual copy is a finding
    about the gate — and it reported a bypass nobody had asked it to look for. A module that rewrites
    itself past the gate throws that evidence away.
    """


class UnknownLanguage(ValueError):
    """A12. The report is bilingual; there is no silent fallback to German."""


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------
#
# Inline in the service, following `services/know.py::NOTICE` and `services/goals.py::GOAL_TEMPLATES`.
# The role definitions and the template purposes are content records under `client/content/` because
# R-111 and D-03 require those to be reviewable and provisional-markable; these are this module's own
# connective sentences, and both languages are written together so neither can quietly lag.

SECTION_TITLE = {
    "de": {
        "household": "Für welchen Haushalt dieser Plan gilt",
        "plan": "Was Ihr Plan festhält",
        "goals": "Ihre Ziele, und woraus sie gedeckt sind",
        "decisions": "Was festgehalten ist",
        "expiries": "Was ein Datum trägt",
        "prepared_decisions": "Was zur Entscheidung vorbereitet ist",
        "not_known": "Was nicht bekannt ist",
    },
    "en": {
        "household": "The household this plan is for",
        "plan": "What your plan records",
        "goals": "Your goals, and what funds them",
        "decisions": "What has been recorded",
        "expiries": "What carries a date",
        "prepared_decisions": "What is prepared for you to decide",
        "not_known": "What is not known",
    },
}

PHRASE = {
    "de": {
        # -- household ----------------------------------------------------------------------------
        "household_not_stated": "Zu Ihrem Haushalt ist nichts erfasst. Davon hängen der AHV-Weg, der "
        "Steuerweg und die Frage ab, wem ein Ziel gehört — hergeleitet wird nichts davon.",
        "household_stated": "Dieser Plan gilt für einen Haushalt mit {adults_display}, Stand {as_of}.",
        "household_with_dependants": "Dazu kommen {dependants_display}.",
        "household_one_adult": "einer erwachsenen Person",
        "household_adults": "{count} erwachsenen Personen",
        "household_one_dependant": "eine Person in Ihrer Obhut",
        "household_dependants": "{count} Personen in Ihrer Obhut",
        "household_closed": "Dieser Haushalt ist per {closed_on} geschlossen. Jede Planfassung aus der "
        "Zeit davor bleibt daran hängen.",
        # The degraded sentence. It states the date, the horizon and what follows — and nothing else.
        # No colour, no verb addressed to the member, no second sentence proposing anything.
        "household_could_not_be_determined": "Ihr Haushalt ist mit Stand {as_of} erfasst; diese Angabe "
        "gilt {horizon_months} Monate und war am {expires_on} zu Ende. Ob der Haushalt heute noch so "
        "besteht, ist damit nicht feststellbar.",
        "goal_owner_not_recorded": "Bei {goal_name} ist nicht festgehalten, wem das Ziel gehört.",
        "plan_version_assumes": "Ihre gültige Planfassung ist Nr. {number} und geht von dem Haushalt "
        "aus, der mit Stand {assumed_as_of} erfasst war.",
        "plan_version_assumption_could_not_be_determined": "Ihre gültige Planfassung ist Nr. {number} "
        "und geht von dem Haushalt mit Stand {assumed_as_of} aus. Diese Angabe gilt {horizon_months} "
        "Monate und war am {expires_on} zu Ende; ob die Fassung noch vom richtigen Haushalt ausgeht, ist "
        "damit nicht feststellbar.",
        "plan_version_assumption_is_older": "Seit dieser Fassung ist Ihr Haushalt neu erfasst worden, "
        "mit Stand {as_of}. Die Fassung selbst rechnet weiter mit dem Stand {assumed_as_of}.",
        # -- plan ---------------------------------------------------------------------------------
        "stock_financial": "Ihr erfasstes Finanzvermögen beträgt {amount}.",
        "stock_liabilities": "Ihre erfassten Verbindlichkeiten betragen {amount}.",
        "stock_net": "Nach Abzug der Verbindlichkeiten bleiben {amount}.",
        "plan_is_empty": "In Ihrem Plan ist noch keine Position erfasst. Die Felder darunter sagen, "
        "was in jedes davon gehört.",
        "capital_human": "Humankapital",
        "capital_financial": "Finanzkapital",
        "cell_filled": "{display} ({capital}): hier steht etwas in Ihrem Plan.",
        "cell_inactive_only": "{display} ({capital}): hier steht nur Stillgelegtes. Stillgelegtes bleibt in der "
        "Geschichte und in den Entscheidungen, die es betreffen.",
        "cell_empty": "{display} ({capital}): hier steht nichts. Was hier hingehört: {definition}",
        "cell_empty_without_definition": "{display} ({capital}): hier steht nichts. Die Definition dieser Rolle "
        "ist in dieser Sprache noch nicht erfasst.",
        # -- goals --------------------------------------------------------------------------------
        "no_goals_recorded": "Es ist kein Ziel erfasst. Ein Ziel hält fest, wofür ein Teil Ihres "
        "Vermögens da ist.",
        "goal_target_amount_and_date": "Dieses Ziel nennt {amount} Franken und den {target_date}.",
        "goal_target_amount_only": "Dieses Ziel nennt {amount} Franken und kein Datum.",
        "goal_target_date_only": "Dieses Ziel nennt den {target_date} und keinen Betrag.",
        "goal_no_target": "Dieses Ziel nennt weder einen Betrag noch ein Datum.",
        "goal_no_target_courage_money": "Dieses Ziel nennt weder einen Betrag noch ein Datum. Als "
        "Mutgeld ist das der gewöhnliche Fall: was es zu Mutgeld macht, ist, wofür es da ist.",
        "goal_is_courage_money": "Dieses Ziel ist als Mutgeld erfasst — Geld, das da ist, damit Sie "
        "nein sagen können.",
        "goal_unfunded": "Keine erfasste Position ist als Deckung dieses Ziels hinterlegt.",
        "goal_funded": "Dieses Ziel ist aus erfassten Positionen gedeckt; welche, steht daneben.",
        "goal_parameters_open": "Zu diesem Ziel sind einzelne der fünf Parameter noch offen; welche, "
        "steht daneben.",
        "goal_dated_but_funding_is_illiquid": "Dieses Ziel trägt ein Datum, und alles, was es deckt, "
        "ist als nicht verfügbar erfasst.",
        "goal_liquidity_not_stated": "Bei mindestens einer Position, die dieses Ziel deckt, ist nicht "
        "erfasst, wie schnell sie zu Geld wird. Ohne diese Angabe lässt sich das Datum nicht damit "
        "vergleichen.",
        "goal_funding_shared_with_other_goals": "Mindestens eine dieser Positionen deckt auch ein "
        "anderes Ziel. Ihr Vermögen ist dabei nicht aufgeteilt — dasselbe Geld kann für mehreres "
        "stehen.",
        # -- decisions ----------------------------------------------------------------------------
        "no_decisions_recorded": "Bisher ist keine Entscheidung festgehalten. Was hier stünde: die "
        "Frage, die zur Wahl stand, was gewählt wurde, und warum.",
        "decision_by_member": "Am {recorded_on} haben Sie eine Entscheidung festgehalten.",
        "decision_by_curator": "Am {recorded_on} hat eine Kuratorin oder ein Kurator eine Entscheidung "
        "festgehalten.",
        "decision_by_system": "Am {recorded_on} hat eigentliCH eine Entscheidung festgehalten.",
        "decision_correction": "Am {recorded_on} wurde eine frühere Entscheidung berichtigt. Die "
        "frühere steht unverändert da.",
        # -- expiries -----------------------------------------------------------------------------
        "no_expiry_dates_recorded": "Zu keinem Ihrer Dokumente ist ein Ablaufdatum erfasst.",
        "vault_item_expires_on": "Dieses Dokument trägt den {expiry_date} als Ablaufdatum.",
        "vault_item_expiry_passed": "Das Ablaufdatum dieses Dokuments, der {expiry_date}, liegt "
        "zurück.",
        # -- prepared decisions -------------------------------------------------------------------
        "nothing_prepared": "Es liegt nichts zur Entscheidung vor.",
        "prepared_decision_due": "Hierzu sind Möglichkeiten mit ihren Folgen erfasst, mit dem "
        "{due_date} als Termin. Welche, steht daneben.",
        "prepared_decision_undated": "Hierzu sind Möglichkeiten mit ihren Folgen erfasst, ohne "
        "Termin. Welche, steht daneben.",
        # -- not known ----------------------------------------------------------------------------
        "not_in_the_plan": "{subject} — das hält Ihr Plan nicht fest. Ein geschätzter Wert stünde hier "
        "anstelle einer Angabe, die Sie nicht gemacht haben; deshalb steht hier keine Zahl.",
        # **"Solange keine veröffentlicht ist" was false and had to go.** A set IS published
        # (`2024-12-31+REG-38d91c1a+RS-874b03c9`); what is missing is the *particular* assumption this
        # figure would need — chiefly a blended expected return, which A69 deliberately does not publish
        # because which scenario probabilities weight which horizon is a decision with an owner. Telling a
        # member no assumption exists, while the Befund elsewhere stamps figures with one, is the kind of
        # sentence that stops being true when something else lands and nobody re-reads it.
        "needs_an_unpublished_assumption": "{subject} — dafür braucht es eine veröffentlichte Annahme, "
        "und die dafür nötige ist nicht darunter. Deshalb steht hier keine Zahl.",
        "nothing_is_missing": "Zu den Rechnungen, die eigentliCH aus einem Plan aufbauen kann, fehlt "
        "nichts.",
        # -- gap subjects -------------------------------------------------------------------------
        "human_capital_amount": "Ihr Humankapital als Betrag in Franken",
        "financial_capital_amount": "Ihr Finanzvermögen als Betrag in Franken",
        "debt": "Ihre Schulden",
        "engine_state_variable": "eine Grösse aus dem Rechenmodell, für die es in Ihrem Plan keine "
        "Entsprechung gibt",
        "return_assumption": "eine Rendite",
        "numbered_baseline": "ein numerierter Ausgangsstand Ihres Plans",
        # -- envelope -----------------------------------------------------------------------------
        "assumptions_note": "In diesem Befund steht keine Zahl, die aus einer Annahme abgeleitet ist. "
        "Er hält fest, was Sie erfasst haben, und rechnet nichts fort.",
    },
    "en": {
        # -- household ----------------------------------------------------------------------------
        "household_not_stated": "Nothing is recorded about your household. The AHV path, the tax path "
        "and whose goal is whose all follow from it, and none of it is derived.",
        "household_stated": "This plan is for a household of {adults_display}, as of {as_of}.",
        "household_with_dependants": "There are also {dependants_display}.",
        "household_one_adult": "one adult",
        "household_adults": "{count} adults",
        "household_one_dependant": "one person in your care",
        "household_dependants": "{count} people in your care",
        "household_closed": "This household closed on {closed_on}. Every plan version made while it was "
        "open stays attached to it.",
        "household_could_not_be_determined": "Your household is recorded as of {as_of}; that statement "
        "holds for {horizon_months} months and ran out on {expires_on}. Whether the household is still "
        "as recorded could not be determined.",
        "goal_owner_not_recorded": "For {goal_name}, whose goal it is has not been recorded.",
        "plan_version_assumes": "Your standing plan is version {number}, and it assumes the household as "
        "recorded on {assumed_as_of}.",
        "plan_version_assumption_could_not_be_determined": "Your standing plan is version {number} and "
        "assumes the household as recorded on {assumed_as_of}. That statement holds for {horizon_months} "
        "months and ran out on {expires_on}; whether the version still assumes the right household could "
        "not be determined.",
        "plan_version_assumption_is_older": "Your household has been recorded again since that version, "
        "as of {as_of}. The version itself still works from the {assumed_as_of} record.",
        # -- plan ---------------------------------------------------------------------------------
        "stock_financial": "Your recorded financial assets come to {amount}.",
        "stock_liabilities": "Your recorded liabilities come to {amount}.",
        "stock_net": "After the liabilities, {amount} remains.",
        "plan_is_empty": "Your plan records no position yet. The fields below say what belongs in each "
        "of them.",
        "capital_human": "human capital",
        "capital_financial": "financial capital",
        "cell_filled": "{display} ({capital}): your plan records something here.",
        "cell_inactive_only": "{display} ({capital}): only inactive material here. Inactive material stays in the "
        "history and in the decisions that concern it.",
        "cell_empty": "{display} ({capital}): nothing here. What belongs here: {definition}",
        "cell_empty_without_definition": "{display} ({capital}): nothing here. The definition of this role has not "
        "been written in this language yet.",
        # -- goals --------------------------------------------------------------------------------
        "no_goals_recorded": "No goal is recorded. A goal states what a part of your wealth is for.",
        "goal_target_amount_and_date": "This goal names {amount} francs and {target_date}.",
        "goal_target_amount_only": "This goal names {amount} francs and no date.",
        "goal_target_date_only": "This goal names {target_date} and no amount.",
        "goal_no_target": "This goal names neither an amount nor a date.",
        "goal_no_target_courage_money": "This goal names neither an amount nor a date. For courage "
        "money that is the ordinary case: what makes it courage money is what it is for.",
        "goal_is_courage_money": "This goal is recorded as courage money — money that exists so you "
        "can say no.",
        "goal_unfunded": "No recorded position is named as funding this goal.",
        "goal_funded": "This goal is funded by recorded positions; which ones is shown beside it.",
        "goal_parameters_open": "Some of this goal's five parameters are still open; which ones is "
        "shown beside it.",
        "goal_dated_but_funding_is_illiquid": "This goal carries a date, and everything funding it is "
        "recorded as not readily available.",
        "goal_liquidity_not_stated": "For at least one position funding this goal, how quickly it "
        "becomes money is not recorded. Without that, the date cannot be compared against it.",
        "goal_funding_shared_with_other_goals": "At least one of these positions also funds another "
        "goal. Your wealth is not being divided up by that — the same money can stand for several "
        "things.",
        # -- decisions ----------------------------------------------------------------------------
        "no_decisions_recorded": "No decision has been recorded yet. What would stand here: the "
        "question that was open, what was chosen, and why.",
        "decision_by_member": "On {recorded_on} you recorded a decision.",
        "decision_by_curator": "On {recorded_on} a curator recorded a decision.",
        "decision_by_system": "On {recorded_on} eigentliCH recorded a decision.",
        "decision_correction": "On {recorded_on} an earlier decision was corrected. The earlier one "
        "stands exactly as it was written.",
        # -- expiries -----------------------------------------------------------------------------
        "no_expiry_dates_recorded": "None of your documents has an expiry date recorded.",
        "vault_item_expires_on": "This document carries {expiry_date} as its expiry date.",
        "vault_item_expiry_passed": "This document's expiry date, {expiry_date}, is in the past.",
        # -- prepared decisions -------------------------------------------------------------------
        "nothing_prepared": "There is nothing waiting to be decided.",
        "prepared_decision_due": "Options and their consequences are recorded for this, with "
        "{due_date} as the date. Which ones is shown beside it.",
        "prepared_decision_undated": "Options and their consequences are recorded for this, with no "
        "date. Which ones is shown beside it.",
        # -- not known ----------------------------------------------------------------------------
        "not_in_the_plan": "{subject} — your plan does not record this. An estimate would stand here "
        "in place of something you did not state, so there is no figure.",
        # See the German above: a set is published, and it is the particular assumption that is absent.
        "needs_an_unpublished_assumption": "{subject} — this needs a published assumption, and the one it "
        "would need is not among them. So there is no figure here.",
        "nothing_is_missing": "Nothing is absent from what eigentliCH can build out of a plan.",
        # -- gap subjects -------------------------------------------------------------------------
        "human_capital_amount": "Your human capital as an amount in francs",
        "financial_capital_amount": "Your financial capital as an amount in francs",
        "debt": "Your debt",
        "engine_state_variable": "a quantity in the calculation model with no counterpart in your plan",
        "return_assumption": "a rate of return",
        "numbered_baseline": "a numbered baseline of your plan",
        # -- envelope -----------------------------------------------------------------------------
        "assumptions_note": "No figure in this Befund is derived from an assumption. It records what "
        "you entered, and projects nothing forward.",
    },
}

#: What the model is allowed to do, and it is one thing. Written in both registers of the instruction —
#: what to do and what not to do — because a model that is told only the first invents the second.
#:
#: The prompt is not the enforcement. `_rephrase` checks the figures, the sentence count, the length and
#: C-01 on what comes back, and keeps the computed sentence when any of them fails. C-01's own rule is
#: that a model which ignores its instructions has to be caught by code, and that rule is not narrower
#: here just because the task is smaller.
PROSE_SYSTEM = (
    "Du formulierst einen einzigen, bereits vollständigen Satz flüssiger um. "
    "Regeln: Gib genau einen Satz zurück. Übernimm jede Zahl und jedes Datum unverändert. "
    "Füge nichts hinzu — keine Empfehlung, keine Einschätzung, keine Zahl, keinen zweiten Satz. "
    "Lass nichts weg. Ändere die Reihenfolge der Aussagen nicht. Antworte nur mit dem Satz."
)


def _say(key: str, language: str, **values: Any) -> str:
    """One phrase, in one language, with its computed values substituted.

    `KeyError` on an unknown key rather than a fallback: a missing phrase is a bug in this file, and a
    report that silently renders an empty sentence is worse than one that fails to render.
    """
    return PHRASE[language][key].format(**values)


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise UnknownLanguage(
            f"unknown language {language!r}; the Befund is written in {list(LANGUAGES)} (A12). There is "
            f"no fallback: a report half in the wrong language is worse than a refused one."
        )
    return language


# ---------------------------------------------------------------------------
# The unit of the report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """One statement the Befund makes, with everything needed to check it.

    **The C-01 gate and the C-02 invariant are both in the constructor**, so no section can be written
    that skips them. That placement is deliberate: A68's practice is that a guarantee enforced by a
    review pass is a guarantee that stops holding while the suite stays green, and a constructor is the
    one place every fact must pass through.
    """

    section: str
    key: str
    sentence: str
    source: str
    data_class: int
    #: Computed figures, ids and dates. Deterministic, and the whole of what the sentence asserts.
    values: dict[str, Any] = field(default_factory=dict)
    #: Member-authored or K3 text, verbatim. **Never interpolated into `sentence`** — see the module
    #: docstring on why a member's own wording must not be able to make their report unrenderable.
    quoted: dict[str, Any] = field(default_factory=dict)
    #: Which key of `quoted` a renderer should put in front of the sentence, if any.
    subject: str | None = None
    #: C-02. Set if and only if `source == "assumption"`.
    assumption_set_id: str | None = None
    #: `computed` always, unless the local model rephrased this sentence and every check passed.
    sentence_origin: str = "computed"
    #: The deterministic sentence, present only when `sentence_origin == "model"`. Never None otherwise:
    #: `sentence` IS the computed one then, and a duplicate key would invite a client to render both.
    computed_sentence: str | None = None
    #: Which stated input classes this fact rests on. Empty means the question does not arise — a role
    #: definition read from a content file has no age. Item 6.
    input_classes: tuple[str, ...] = ()
    #: `stands`, unless a load-bearing input it rests on has passed its published validity horizon, in
    #: which case `could_not_be_determined` — the Household Optimiser's own third answer, not a fourth
    #: vocabulary for staleness. See `services/currency.py`.
    determination: str = currency_service.STANDS
    #: The currency of each input class above, as `Currency.as_dict()`. Present so a reader can see WHY a
    #: fact could not be determined without recomputing it, and so a curator can see the age of an input
    #: that has not expired yet.
    currency: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if self.section not in SECTIONS:
            raise ValueError(f"unknown section {self.section!r}; expected one of {', '.join(SECTIONS)}")
        if self.source not in PROVENANCE:
            raise ValueError(f"unknown provenance {self.source!r}; expected one of {', '.join(PROVENANCE)}")
        if not self.sentence.strip():
            raise ValueError(f"fact {self.key!r} has no sentence; an empty statement is not a statement")
        if (self.sentence_origin == "model") != (self.computed_sentence is not None):
            raise ValueError(
                f"fact {self.key!r} declares sentence_origin {self.sentence_origin!r} with "
                f"computed_sentence={self.computed_sentence!r}. A model-written sentence carries the "
                f"deterministic one it replaced, and a computed sentence has nothing to carry."
            )

        # -- item 6: currency ---------------------------------------------------------------------
        unknown = [name for name in self.input_classes if name not in currency_service.INPUT_CLASSES]
        if unknown:
            raise ValueError(
                f"fact {self.key!r} rests on input class(es) {unknown} that this application cannot age; "
                f"expected a subset of {', '.join(currency_service.INPUT_CLASSES)}. A class nothing can "
                f"age is a currency guarantee that silently does not hold."
            )
        if self.determination not in currency_service.DETERMINATIONS:
            raise ValueError(
                f"fact {self.key!r} declares determination {self.determination!r}; expected one of "
                f"{', '.join(currency_service.DETERMINATIONS)}. There is deliberately no `stale`, "
                f"`expired` or `needs_review` state — see services/currency.py."
            )
        # A fact that could not be determined has to say which input made it so. Without this the state
        # is unfalsifiable: a caller could mark anything undeterminable and nothing would disagree.
        if self.determination == currency_service.COULD_NOT_BE_DETERMINED and not self.input_classes:
            raise ValueError(
                f"fact {self.key!r} could not be determined and names no input class it rests on. The "
                f"reason a figure is uncertifiable is part of the finding, not a mood."
            )

        # -- C-02 ---------------------------------------------------------------------------------
        # The biconditional, not the implication. A figure from an assumption without the id is the
        # violation C-02 names; an id attached to a figure that came from the member is a claim of
        # provenance that is not true, and it is the one that survives review.
        if (self.source == "assumption") != (self.assumption_set_id is not None):
            raise ValueError(
                f"C-02: fact {self.key!r} declares source {self.source!r} with "
                f"assumption_set_id={self.assumption_set_id!r}. A figure derived from an assumption "
                f"carries the id of the set that produced it, and nothing else carries one."
            )

        # C-01 ran here and refused a composed sentence that read as advice. Withdrawn (A164): every
        # sentence this module composes now reaches the report exactly as written. The two mechanisms
        # above it — composed sentences rather than templated ones, and member text kept in `quoted`
        # beside the sentence instead of interpolated into it — are unaffected, because neither was
        # about regulation: the first is how the report stays truthful about its own figures, and the
        # second is why a member naming a position cannot make their own report unrenderable.

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "sentence": self.sentence,
            "sentence_origin": self.sentence_origin,
            "computed_sentence": self.computed_sentence,
            "source": self.source,
            "assumption_set_id": self.assumption_set_id,
            "data_class": self.data_class,
            "values": dict(self.values),
            "quoted": dict(self.quoted),
            "subject": self.subject,
            "input_classes": list(self.input_classes),
            "determination": self.determination,
            "currency": [dict(one) for one in self.currency],
        }

    def rephrased(self, sentence: str) -> "Fact":
        """The same fact with a model-written sentence. Re-runs every constructor check on the new text.

        The deterministic sentence is carried along in `computed_sentence`, so the text code owns is
        still in the payload when the model has replaced it. "Code owns the figures and the structure"
        is a claim somebody has to be able to check after the fact.
        """
        return Fact(
            section=self.section,
            key=self.key,
            sentence=sentence,
            source=self.source,
            data_class=self.data_class,
            values=self.values,
            quoted=self.quoted,
            subject=self.subject,
            assumption_set_id=self.assumption_set_id,
            sentence_origin="model",
            computed_sentence=self.sentence,
            # Carried, not recomputed. A model rewrote the wording; it did not change what the sentence
            # rests on or whether that is still current.
            input_classes=self.input_classes,
            determination=self.determination,
            currency=self.currency,
        )


# ---------------------------------------------------------------------------
# Formatting the member's own figures
# ---------------------------------------------------------------------------


def _swiss_date(when: date) -> str:
    """`31.08.2026`. Not `strftime('%d.%m.%Y')`: that is locale- and platform-dependent for the day."""
    return f"{when.day:02d}.{when.month:02d}.{when.year:04d}"


def _amount(value: float) -> str:
    """A member-stated amount as Swiss prose: `92'000`, `1'500`, `12'500.50`.

    The member typed this. It is not rounded, not scaled and not converted — those would all be
    arithmetic this module has no mandate for, and the last one would need a rate.
    """
    whole = int(value)
    if value == whole:
        return f"{whole:,}".replace(",", "'")
    return f"{value:,.2f}".replace(",", "'")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _household_facts(
    household,
    goal_payloads: Sequence[dict],
    language: str,
    *,
    today: date,
    standing_version=None,
) -> list[Fact]:
    """The frame the rest of the report is read inside, and the only section that can degrade.

    **Not stated is a fact, not an empty section.** A member who has told the app nothing about their
    household gets a sentence saying so and saying what hangs on it. The alternative — treating an
    unstated composition as a household of one, since most members are single — would put a figure on the
    screen that nobody stated; see A108.

    **The degraded sentence replaces the composition, it does not annotate it.** When the twelve months
    are up the report does not say "2 adults as of March 2027 ⚠"; it says the statement ran out and
    whether the household is still as recorded could not be determined. A figure with a warning beside it
    is still a figure the member will act on, which is the failure item 6 names.
    """
    facts: list[Fact] = []

    if household is None:
        facts.append(
            Fact(
                section="household",
                key="household_not_stated",
                sentence=_say("household_not_stated", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        )
    else:
        as_of = household.composition_as_of
        present = [p for p in household.members if p.left_on is None]
        adults = [p for p in present if p.kind == ADULT]
        dependants = [p for p in present if p.kind == DEPENDANT]

        one = currency_service.of("household_composition", as_of, today=today)
        verdict = currency_service.determination([one])
        shared = {
            "section": "household",
            "source": "member_stated",
            "data_class": int(DataClass.K2),
            "input_classes": ("household_composition",),
            "currency": (one.as_dict(),),
        }

        if verdict == currency_service.COULD_NOT_BE_DETERMINED:
            facts.append(
                Fact(
                    key="household_could_not_be_determined",
                    sentence=_say(
                        "household_could_not_be_determined",
                        language,
                        as_of=_swiss_date(as_of),
                        horizon_months=one.horizon_months,
                        expires_on=_swiss_date(one.expires_on),
                    ),
                    # The composition itself is deliberately NOT in `values`. A client that wanted to
                    # render the stale figure anyway would have to go and fetch it, which is the point:
                    # this fact does not carry a number it cannot stand behind.
                    values={
                        "as_of": as_of.isoformat(),
                        "horizon_months": one.horizon_months,
                        "expires_on": one.expires_on.isoformat(),
                    },
                    determination=currency_service.COULD_NOT_BE_DETERMINED,
                    **shared,
                )
            )
        else:
            adults_display = (
                _say("household_one_adult", language)
                if len(adults) == 1
                else _say("household_adults", language, count=len(adults))
            )
            facts.append(
                Fact(
                    key="household_stated",
                    sentence=_say(
                        "household_stated",
                        language,
                        adults_display=adults_display,
                        as_of=_swiss_date(as_of),
                    ),
                    values={
                        "adults": len(adults),
                        "dependants": len(dependants),
                        "as_of": as_of.isoformat(),
                        "stated_by": household.stated_by,
                    },
                    **shared,
                )
            )
            if dependants:
                dependants_display = (
                    _say("household_one_dependant", language)
                    if len(dependants) == 1
                    else _say("household_dependants", language, count=len(dependants))
                )
                facts.append(
                    Fact(
                        key="household_with_dependants",
                        sentence=_say(
                            "household_with_dependants",
                            language,
                            dependants_display=dependants_display,
                        ),
                        values={"dependants": len(dependants)},
                        **shared,
                    )
                )

        if household.closed_on is not None:
            facts.append(
                Fact(
                    key="household_closed",
                    sentence=_say(
                        "household_closed", language, closed_on=_swiss_date(household.closed_on)
                    ),
                    values={"closed_on": household.closed_on.isoformat()},
                    # A closing is a dated event, not a statement whose currency can lapse: the household
                    # closed on that date and will not un-close. So no input class and no degradation.
                    section="household",
                    source="member_stated",
                    data_class=int(DataClass.K2),
                )
            )

    # Item 6's own sentence: "this plan assumes a two-member household as of March 2027." The version's
    # OWN stamp is what ages here, not the household's current record — that is the whole reason the stamp
    # is copied at capture. A member who restated their composition last week still has a standing plan
    # built on what it assumed, and it is that assumption whose currency matters.
    #
    # Stated only when there IS a standing plan. "You have no standing plan" is a true sentence and it is
    # not this section's: what the plan holds is the `plan` section's subject, and a member who has not
    # adopted a version has not failed at anything.
    if standing_version is not None and standing_version.household_as_of is not None:
        assumed = standing_version.household_as_of
        assumption = currency_service.of("household_composition", assumed, today=today)
        version_shared = {
            "section": "household",
            "source": "member_stated",
            "data_class": int(DataClass.K2),
            "input_classes": ("household_composition",),
            "currency": (assumption.as_dict(),),
        }
        if assumption.degrades:
            facts.append(
                Fact(
                    key="plan_version_assumption_could_not_be_determined",
                    sentence=_say(
                        "plan_version_assumption_could_not_be_determined",
                        language,
                        number=standing_version.number,
                        assumed_as_of=_swiss_date(assumed),
                        horizon_months=assumption.horizon_months,
                        expires_on=_swiss_date(assumption.expires_on),
                    ),
                    values={
                        "version_number": standing_version.number,
                        "assumed_as_of": assumed.isoformat(),
                        "horizon_months": assumption.horizon_months,
                        "expires_on": assumption.expires_on.isoformat(),
                    },
                    determination=currency_service.COULD_NOT_BE_DETERMINED,
                    **version_shared,
                )
            )
        else:
            facts.append(
                Fact(
                    key="plan_version_assumes",
                    sentence=_say(
                        "plan_version_assumes",
                        language,
                        number=standing_version.number,
                        assumed_as_of=_swiss_date(assumed),
                    ),
                    values={
                        "version_number": standing_version.number,
                        "assumed_as_of": assumed.isoformat(),
                    },
                    **version_shared,
                )
            )

        # The standing plan assumes one date and the household has since been recorded at another. Two
        # facts side by side, no verdict about which is right and nothing proposed — the re-solve that
        # would follow is the member's act (page 1), not a sentence in a report.
        if household is not None and household.composition_as_of != assumed:
            facts.append(
                Fact(
                    section="household",
                    key="plan_version_assumption_is_older",
                    sentence=_say(
                        "plan_version_assumption_is_older",
                        language,
                        as_of=_swiss_date(household.composition_as_of),
                        assumed_as_of=_swiss_date(assumed),
                    ),
                    source="computed_from_plan",
                    data_class=int(DataClass.K2),
                    values={
                        "as_of": household.composition_as_of.isoformat(),
                        "assumed_as_of": assumed.isoformat(),
                    },
                )
            )

    # A108: a household that never populated `owners` cannot be divided cleanly, so an unowned goal is
    # reported rather than left to be discovered at the moment it matters most.
    for payload in goal_payloads:
        if not payload.get("owner_recorded"):
            facts.append(
                Fact(
                    section="household",
                    key="goal_owner_not_recorded",
                    sentence=_say(
                        "goal_owner_not_recorded", language, goal_name=payload["name"]
                    ),
                    source="computed_from_plan",
                    data_class=int(DataClass.K2),
                    values={"goal_id": payload["id"]},
                    quoted={"goal_name": payload["name"]},
                    subject="goal_name",
                )
            )

    return facts


def _stock_facts(positions: Sequence[Position], language: str) -> list[Fact]:
    """The member's stated balances, summed. **The only figures in the Befund that nobody typed.**

    Until this existed the report carried no computed figure at all: every number in it was one the member
    had entered, and every other fact was structural — which cell is filled, which goal is unfunded, what
    is not known. That is a complete and honest report and it is not enough for Principle 2, whose whole
    point is a statement the member could not have made themselves. Principle 2's "what it rules out" is
    literally "onboarding that reflects back what was typed in".

    **Arithmetic over stated balances, and nothing else.** A sum is not an assumption: no rate is applied,
    nothing is projected, no horizon is used, and C-02 has nothing to bite on. `engine_inputs.stated_stocks`
    does the summing and is not reimplemented here — it already carries the four filters that make the sum
    correct (active only, stock units only, magnitude present, asset and liability apart), and each of
    those is a defect if it goes missing.

    **Absent rather than zero.** A member who has stated no balance gets no fact here, not a fact saying
    zero. `StatedStocks` returns None for a category nobody filled, and "you have nothing" is a different
    and wrong claim from "you have not said".
    """
    stocks = stated_stocks(positions)
    facts: list[Fact] = []
    shared = {
        "section": "plan",
        "source": "computed_from_plan",
        "data_class": int(DataClass.K2),
    }

    if stocks.financial_assets is not None:
        facts.append(
            Fact(
                key="stock_financial",
                sentence=_say("stock_financial", language, amount=_amount(stocks.financial_assets)),
                values={
                    "amount_chf": stocks.financial_assets,
                    "positions_counted": stocks.stated_by["financial_assets"],
                },
                **shared,
            )
        )
    if stocks.liabilities is not None:
        facts.append(
            Fact(
                key="stock_liabilities",
                sentence=_say("stock_liabilities", language, amount=_amount(stocks.liabilities)),
                values={
                    "amount_chf": stocks.liabilities,
                    "positions_counted": stocks.stated_by["liabilities"],
                },
                **shared,
            )
        )
    # Stated only when BOTH sides are, because a net figure over an unstated liability is a claim that
    # there is none. The member has not said that.
    if stocks.financial_assets is not None and stocks.liabilities is not None:
        facts.append(
            Fact(
                key="stock_net",
                sentence=_say(
                    "stock_net",
                    language,
                    amount=_amount(stocks.financial_assets - stocks.liabilities),
                ),
                values={"amount_chf": stocks.financial_assets - stocks.liabilities},
                **shared,
            )
        )
    return facts


def _plan_facts(positions: Sequence[Position], language: str) -> list[Fact]:
    """R-110's principle, applied to prose: an empty cell states what would go there.

    **No count, no total, no ratio** — R-113. Each cell gets its own fact, and a member who reads three
    empty ones knows there are three without being handed the number as a measurement of themselves.
    """
    facts: list[Fact] = []

    if not positions:
        facts.append(
            Fact(
                section="plan",
                key="plan_is_empty",
                sentence=_say("plan_is_empty", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        )

    for role_key in ROLES:
        for capital_type in CAPITAL_TYPES:
            display = role_display(role_key, capital_type, language)
            # R-114 / principle 9: both kinds of capital are always present, so the German displays
            # collide across the two columns ("Einkommen" is the label on both sides). Naming the
            # kind of capital in the sentence is what keeps a prose report legible where a grid had
            # two columns to tell them apart with.
            capital = _say(f"capital_{capital_type}", language)
            in_cell = [p for p in positions if p.role == role_key and p.capital_type == capital_type]
            active = [p for p in in_cell if p.active]
            common = {
                "section": "plan",
                "values": {
                    "role": role_key,
                    "capital_type": capital_type,
                    "display": display,
                    "capital_display": capital,
                },
                "data_class": int(DataClass.K2),
            }

            if active:
                facts.append(
                    Fact(
                        key="cell_filled",
                        sentence=_say("cell_filled", language, display=display, capital=capital),
                        source="computed_from_plan",
                        quoted={"position_labels": [p.label for p in active]},
                        **common,
                    )
                )
            elif in_cell:
                # R-122: inactive positions remain in history. A cell holding only inactive ones is
                # neither filled nor empty, and calling it either would misrepresent what the member did.
                facts.append(
                    Fact(
                        key="cell_inactive_only",
                        sentence=_say("cell_inactive_only", language, display=display, capital=capital),
                        source="computed_from_plan",
                        quoted={"position_labels": [p.label for p in in_cell]},
                        **common,
                    )
                )
            else:
                definition = role_definition(role_key, capital_type, language)
                if definition:
                    sentence = _say(
                        "cell_empty", language, display=display, capital=capital, definition=definition
                    )
                    # The definition is a content record (K0) rather than anything about this member,
                    # and it is the honest source for "what would go here" — the role's own words.
                    source = "content"
                else:
                    sentence = _say(
                        "cell_empty_without_definition", language, display=display, capital=capital
                    )
                    source = "computed_from_plan"
                facts.append(
                    Fact(key="cell_empty", sentence=sentence, source=source, **common)
                )

    return facts


#: Observation kinds from `services/goals.py` that this module renders, mapped to a phrase key.
#:
#: `dated_but_unfunded` is deliberately absent: `goal_unfunded` below already states that no position
#: funds the goal, for the dated and the undated case alike, and emitting both would say one thing twice
#: in a report whose whole claim is that every line is a distinct fact.
_GOAL_OBSERVATIONS = {
    "dated_but_funding_is_illiquid": "goal_dated_but_funding_is_illiquid",
    "liquidity_not_stated": "goal_liquidity_not_stated",
    "funding_shared_with_other_goals": "goal_funding_shared_with_other_goals",
}


def _goal_facts(goal_payloads: Sequence[dict], language: str) -> list[Fact]:
    """S-04 read through `services/goals.py`, never recomputed here.

    R-031's observations are that module's judgement about what can be compared without a threshold, and
    a second implementation of the same comparison in a report is how the two come to disagree.
    """
    facts: list[Fact] = []

    if not goal_payloads:
        return [
            Fact(
                section="goals",
                key="no_goals_recorded",
                sentence=_say("no_goals_recorded", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        ]

    for payload in goal_payloads:
        goal_id = payload["id"]
        quoted_name = {"goal_name": payload["name"]}
        common = {
            "section": "goals",
            "quoted": quoted_name,
            "subject": "goal_name",
            "data_class": int(DataClass.K2),
        }

        if payload["template"] == "courage_money":
            facts.append(
                Fact(
                    key="goal_is_courage_money",
                    sentence=_say("goal_is_courage_money", language),
                    source="member_stated",
                    values={"goal_id": goal_id, "template": payload["template"]},
                    **common,
                )
            )

        amount, target_date = payload["target_amount"], payload["target_date"]
        target_values = {"goal_id": goal_id, "target_amount": amount, "target_date": target_date}
        readable_date = _swiss_date(date.fromisoformat(target_date)) if target_date else None
        if amount is not None and target_date:
            key, text = "goal_target", _say(
                "goal_target_amount_and_date",
                language,
                amount=_amount(amount),
                target_date=readable_date,
            )
        elif amount is not None:
            key, text = "goal_target", _say("goal_target_amount_only", language, amount=_amount(amount))
        elif target_date:
            key, text = "goal_target", _say("goal_target_date_only", language, target_date=readable_date)
        elif payload["template"] == "courage_money":
            key, text = "goal_no_target", _say("goal_no_target_courage_money", language)
        else:
            key, text = "goal_no_target", _say("goal_no_target", language)
        facts.append(
            Fact(key=key, sentence=text, source="member_stated", values=target_values, **common)
        )

        funding = [f for f in payload["funded_by"]]
        if funding:
            facts.append(
                Fact(
                    key="goal_funded",
                    sentence=_say("goal_funded", language),
                    source="computed_from_plan",
                    values={"goal_id": goal_id, "position_ids": [f["id"] for f in funding]},
                    section="goals",
                    quoted={**quoted_name, "position_labels": [f["label"] for f in funding]},
                    subject="goal_name",
                    data_class=int(DataClass.K2),
                )
            )
        else:
            facts.append(
                Fact(
                    key="goal_unfunded",
                    sentence=_say("goal_unfunded", language),
                    source="computed_from_plan",
                    values={"goal_id": goal_id},
                    **common,
                )
            )

        open_parameters = [name for name, value in payload["parameters"].items() if value is None]
        if open_parameters:
            facts.append(
                Fact(
                    key="goal_parameters_open",
                    sentence=_say("goal_parameters_open", language),
                    source="computed_from_plan",
                    # A list of names, not a tally of how many are answered. R-113: the second is a
                    # completion meter over the member's own filling-in of a form.
                    values={"goal_id": goal_id, "parameters_not_answered": open_parameters},
                    **common,
                )
            )

        for observation in payload["observations"]:
            phrase_key = _GOAL_OBSERVATIONS.get(observation["kind"])
            if phrase_key is None:
                continue
            facts.append(
                Fact(
                    key=phrase_key,
                    sentence=_say(phrase_key, language),
                    source="computed_from_plan",
                    values={"goal_id": goal_id, **{k: v for k, v in observation.items() if k != "kind"}},
                    **common,
                )
            )

    return facts


_DECISION_AUTHORS = {
    "member": "decision_by_member",
    "curator": "decision_by_curator",
    "system": "decision_by_system",
}


def _decision_facts(decisions: Sequence[Decision], language: str) -> list[Fact]:
    """S-07. The most underused material in the system, and the thing that survives a change of adviser.

    Every plan mutation has one behind it (C-09), so this section is the member's own history of what they
    changed and why — read back to them in the order it happened.
    """
    if not decisions:
        return [
            Fact(
                section="decisions",
                key="no_decisions_recorded",
                sentence=_say("no_decisions_recorded", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        ]

    facts: list[Fact] = []
    for record in decisions:
        recorded_on = record.created_at.date()
        if record.corrects_id:
            key = "decision_correction"
        else:
            key = _DECISION_AUTHORS[record.author]
        facts.append(
            Fact(
                section="decisions",
                key=key,
                sentence=_say(key, language, recorded_on=_swiss_date(recorded_on)),
                source="member_stated",
                data_class=int(DataClass.K2),
                values={
                    "decision_id": record.id,
                    "recorded_on": recorded_on.isoformat(),
                    "author": record.author,
                    "author_ref": record.author_ref,
                    "corrects_id": record.corrects_id,
                    "linked_position_ids": record.linked_position_ids,
                    "linked_goal_ids": record.linked_goal_ids,
                    "linked_vault_item_ids": record.linked_vault_item_ids,
                },
                # The question, the choice and the reasoning are the member's or the curator's own words.
                # Quoted, never composed into a sentence.
                quoted={
                    "question": record.question,
                    "choice": record.choice,
                    "reasoning": record.reasoning,
                },
                subject="question",
            )
        )
    return facts


def _expiry_facts(items: Sequence[VaultItem], language: str, *, today: date) -> list[Fact]:
    """R-152. Expiry dates are first-class, so they are a section rather than a footnote.

    **These facts are K3 and say so.** A vault item is K3 as a whole (C-04), the title is what makes the
    line readable, and quoting it is quoting K3 — so the class is on the fact rather than left to be
    inferred from the section it happens to sit in.
    """
    dated = sorted(
        (item for item in items if item.expiry_date is not None),
        key=lambda item: (item.expiry_date, item.id),
    )
    if not dated:
        return [
            Fact(
                section="expiries",
                key="no_expiry_dates_recorded",
                sentence=_say("no_expiry_dates_recorded", language),
                source="computed_from_plan",
                data_class=int(DataClass.K3),
            )
        ]

    facts: list[Fact] = []
    for item in dated:
        passed = item.expiry_date < today
        key = "vault_item_expiry_passed" if passed else "vault_item_expires_on"
        facts.append(
            Fact(
                section="expiries",
                key=key,
                sentence=_say(key, language, expiry_date=_swiss_date(item.expiry_date)),
                source="member_stated",
                data_class=int(DataClass.K3),
                values={
                    "vault_item_id": item.id,
                    "kind": item.kind,
                    "expiry_date": item.expiry_date.isoformat(),
                    "version": item.version,
                },
                quoted={"title": item.title},
                subject="title",
            )
        )
    return facts


def _prepared_decision_facts(items: Sequence[dict], language: str) -> list[Fact]:
    """C-06 read back to the member: an item exists only if it carries the options and their consequences.

    This is the closest the Befund comes to the "action plan" the owner asked for, and it stays on the
    right side of C-01 for a structural reason rather than a careful one: the options are already stored,
    already paired with their consequences, and already written by a path (`services/vault.py`) that
    recommends neither. The report states that they exist and hands them over. It does not pick one.
    """
    if not items:
        return [
            Fact(
                section="prepared_decisions",
                key="nothing_prepared",
                sentence=_say("nothing_prepared", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        ]

    facts: list[Fact] = []
    for item in items:
        due = item["due_date"]
        if due:
            key = "prepared_decision_due"
            sentence = _say(key, language, due_date=_swiss_date(date.fromisoformat(due)))
        else:
            key = "prepared_decision_undated"
            sentence = _say(key, language)
        facts.append(
            Fact(
                section="prepared_decisions",
                key=key,
                sentence=sentence,
                source="computed_from_plan",
                data_class=int(DataClass.K2),
                values={
                    "action_item_id": item["id"],
                    "trigger_kind": item["trigger_kind"],
                    "due_date": due,
                    "source_vault_item_id": item["source_vault_item_id"],
                },
                # C-06's options, verbatim. eigentliCH wrote these, not the member, so they are held to
                # C-01 by `test_the_prepared_options_andersch_writes_pass_c01` — but they are still
                # quoted rather than composed, because they are not this module's sentences.
                quoted={"prepared_options": item["prepared_options"]},
                subject="prepared_options",
            )
        )
    return facts


def reportable_gaps(
    *, member_id: str, positions: Iterable[Position], today: date
) -> list[engine_inputs.AbsentInput]:
    """The plan gaps that are a member's business, grouped nowhere and sorted deterministically.

    Read through `services/engine_inputs.py` rather than recomputed: that module is A39's mapping layer and
    the authority on what each engine needs and why the plan cannot supply it.

    Filtered twice. `blocks_the_plan` keeps the two kinds that mean *the plan does not answer this* and
    drops the two that mean *this call did not supply it* — a what-if value nobody asked for yet is not a
    gap in the member's plan. `ENGINES_WITHHELD_FROM_A_MEMBER` drops the two engines whose gap lists are
    not member-facing at all, for the reasons recorded on that constant.
    """
    plans = engine_inputs.plan_all(member_id=member_id, positions=list(positions), today=today)
    gaps = [
        gap
        for engine, plan in plans.items()
        if engine not in ENGINES_WITHHELD_FROM_A_MEMBER
        for gap in plan.absent
        if gap.blocks_the_plan
    ]
    return sorted(gaps, key=lambda gap: (gap.kind, gap.name, gap.engine))


def _not_known_facts(gaps: Sequence[engine_inputs.AbsentInput], language: str) -> list[Fact]:
    """A39's gaps, as a member-facing account of what eigentliCH does not know.

    **One fact per subject, not per engine input.** `W_R` and `initial_wealth` are the same absence asked
    for by two engines; reported separately they read as two problems, and the member has one.

    The engine's own reason travels verbatim in `values["inputs"]`. It is English, technical, and written
    for whoever maintains the mapping layer — which is exactly why it is not in the sentence.
    """
    if not gaps:
        return [
            Fact(
                section="not_known",
                key="nothing_is_missing",
                sentence=_say("nothing_is_missing", language),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
            )
        ]

    grouped: dict[tuple[str, str], list[engine_inputs.AbsentInput]] = {}
    for gap in gaps:
        try:
            subject = GAP_SUBJECTS[gap.name]
        except KeyError:
            raise KeyError(
                f"engine {gap.engine!r} declares a plan-blocking input {gap.name!r} with no member-facing "
                f"subject in GAP_SUBJECTS. A gap with no subject would be silently dropped from the "
                f"Befund, and this section's whole value is that it is complete. Add a subject and its "
                f"copy in both languages."
            ) from None
        grouped.setdefault((gap.kind, subject), []).append(gap)

    facts: list[Fact] = []
    for (kind, subject), members in sorted(grouped.items()):
        facts.append(
            Fact(
                section="not_known",
                key=f"{kind}:{subject}",
                sentence=_say(kind, language, subject=_say(subject, language)),
                source="computed_from_plan",
                data_class=int(DataClass.K2),
                values={
                    "kind": kind,
                    "subject": subject,
                    # The engine, the input name and its declared type — enough for a curator to find
                    # the gap in `engine_inputs.gap_report`. **The engine's own `reason` is
                    # deliberately NOT here.** It is English implementation prose written for whoever
                    # maintains the mapping layer, it does not belong in a German report, and it drags
                    # words like "total" and "complete" into a member-facing payload that R-113
                    # forbids the concepts of. The member-facing explanation is the sentence.
                    "inputs": [
                        {"engine": gap.engine, "input": gap.name, "declared_as": gap.declared_as}
                        for gap in members
                    ],
                },
            )
        )
    return facts


# ---------------------------------------------------------------------------
# The model's one job
# ---------------------------------------------------------------------------


def _figures(text: str) -> list[str]:
    """Every run of digits, in order. `31.08.2026` gives `['31', '08', '2026']`; `92'000` gives `['92', '000']`.

    Compared as a *sequence*, so a rephrasing that reorders two dates is rejected as surely as one that
    invents a number. Reordering is exactly the latitude the model does not have.
    """
    runs, current = [], ""
    for character in text:
        if character.isdigit():
            current += character
        elif current:
            runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return runs


#: Sentence-ish, and the same shape `boundary.py` splits on. `—` is not a terminator: the copy uses an
#: em dash mid-sentence and treating it as a break would hand the model two fragments to rephrase.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


#: Words the model may add or drop freely. A closed list of German and English function words — a fact
#: about the two languages, not a policy about anything, which is why it can be written down here without
#: §12's warning applying. Everything NOT in it is a content word, and the model may introduce none.
#:
#: **This is the check that catches invented content, and nothing else does.** Measured against the real
#: apertus:8b: `Zu diesem Ziel sind einzelne der fünf Parameter noch offen` came back as `...die Parameter
#: für die Zielgruppe, den Zielmarkt, die Zielstrategie und den Zielzeitraum noch offen` — four invented
#: parameter names, none of which exists in `goals.FIVE_PARAMETERS`. It carried no figure, added no
#: sentence, stayed inside the length allowance and passed C-01. Every guard that existed at the time was
#: satisfied by a sentence that had made up the subject matter.
#:
#: **No threshold, deliberately.** "At most three new words" would be a number nobody published, which
#: §12 calls a defect rather than a gap-fill. Zero new content words is the only rule here that is not
#: invented, and it is what "no latitude to add" says in the first place.
_FUNCTION_WORDS = frozenset(
    # German — articles, pronouns, prepositions, conjunctions, particles, the copula and its auxiliaries
    """
    der die das den dem des ein eine einer eines einem einen kein keine keiner keines keinem keinen
    ich du er sie es wir ihr man sich mein dein sein ihre ihrer ihres ihrem ihren unser euer diese
    dieser dieses diesem diesen jene jener welche welcher was wer wo wie wann warum
    und oder aber denn sondern doch also dann noch nur auch schon nicht nichts etwas alle alles
    in im an am auf aus bei bis durch für gegen mit nach ohne seit um von vom vor zu zum zur über
    unter zwischen als wenn dass weil damit sowie beziehungsweise
    ist sind war waren sein wird werden wurde wurden hat haben hatte hatten kann können
    steht stehen stünde wäre gibt es da hier dort daneben darunter davon dafür dazu dabei
    ja nein sehr mehr weniger einzelne
    # English
    the a an of to in on at by for from with without and or but so then also not no none any all
    some this that these those it its is are was were be been has have had can could would will
    what which who where when why how here there beside below already still only your you we our
    yourself does do did each every neither nor as if because while than
    """.split()
) - {"#", "English"}  # the inline `# English` divider, which `.split()` picks up as two tokens


def _fold(word: str) -> str:
    """Lowercase, umlauts to their ASCII spelling, punctuation off. A78's transform, for the same reason:
    `Grösse` and `Groesse` are the same word, and a check that treats them as different is a check that
    fails on how German is actually typed."""
    folded = word.lower()
    for umlaut, ascii_form in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(umlaut, ascii_form)
    return "".join(character for character in folded if character.isalnum())


#: The function words, folded the same way a candidate's words are. Not folded, `für` becomes `fuer`
#: on one side of the comparison and stays `für` on the other, and the commonest preposition in German
#: reads as invented content. Caught by probing the check against the live model's own output.
_FOLDED_FUNCTION_WORDS = frozenset(_fold(word) for word in _FUNCTION_WORDS) - {""}

#: How much a word may change length and still be the same word. Two characters is a German inflection
#: ending — `Ziel`/`Ziels`, `Deckung`/`Deckungen`, `hinterlegt`/`hinterlegen` — and it is a fact about
#: the morphology rather than a threshold about anything. It is what separates an inflection from a
#: compound: `Entscheidung` to `Entscheidungsgegenstand` is eleven characters and a different word.
_INFLECTION_SLACK = 2

#: Below this, a shared prefix means nothing: three-letter prefixes collide constantly in German.
_STEM_FLOOR = 4


def _introduced_content_words(candidate: str, original: str) -> list[str]:
    """Content words in the model's sentence that are not in the one it was given.

    Empty is the only acceptable result.

    **Inflection passes, compounding does not, and getting that boundary right took two attempts.** A
    pure prefix rule made `Ziel` and `Zielgruppe` the same word, which is exactly the invention this
    check exists to catch; raising the prefix floor to fix that made `Ziel` and `Ziels` different words,
    which rejects an ordinary German case ending. The rule that separates them is the length difference:
    an inflection adds an ending, a compound adds a word.
    """
    known = {_fold(word) for word in original.split()}
    known.discard("")
    introduced = []
    for raw in candidate.split():
        word = _fold(raw)
        if not word or word in _FOLDED_FUNCTION_WORDS or word in known:
            continue
        if any(
            (word.startswith(other) or other.startswith(word))
            and min(len(word), len(other)) >= _STEM_FLOOR
            and abs(len(word) - len(other)) <= _INFLECTION_SLACK
            for other in known
        ):
            continue
        introduced.append(raw)
    return introduced


def _sentences_of(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _rephrase(fact: Fact, *, model: str | None) -> tuple[Fact, str | None]:
    """Ask the local model to say the same thing better. Return the fact, and why it was refused if it was.

    **One model call per sentence, not per fact, and that is the load-bearing choice.** Counting sentences
    on a whole-fact rephrasing does not catch an addition: a two-sentence computed fact came back as two
    sentences with the second one replaced by `Übrigens ist das ein guter Ausgangspunkt` — an opinion, no
    figures, within the length bound, and the count was satisfied. Found by a planted test, not by reading
    the code. Rephrasing sentence by sentence with a one-in-one-out contract makes an added sentence
    structurally impossible rather than merely improbable.

    **Six checks, and the computed sentence wins every tie:**

      1. exactly one sentence back for each one sent — nothing added, nothing merged away;
      2. the same figures in the same order, so a reordering is refused as surely as an invention;
      3. not materially longer than what it replaced;
      4. **the same content words, neither added nor dropped** — checked in both directions, because
         "no latitude to add, omit or reorder" is three verbs and a one-way containment check covers one
         of them. This is the check that catches invented subject matter, and the one the others did
         not. See `_FUNCTION_WORDS` for the two live-model outputs that made each direction necessary;
      5. C-01 on the reassembled result, via `Fact.rephrased` re-running the whole constructor;
      6. and the computed sentence is kept in the payload beside the model's, so the deterministic text
         is never lost — an auditor compares the two rather than taking the model's word for it.

    **What is left for the model to do is very little, and that is the finding rather than a defect.**
    Under check 4 it may reorder, re-punctuate, change inflection and swap function words, and nothing
    else. Measured against apertus:8b on a seeded plan, the large majority of rephrasings are rejected,
    and `content_introduced` is the commonest reason. "The model only writes sentences" turns out to be
    a licence with almost no content once it is enforced rather than requested — which is precisely the
    argument for the deterministic report being the product and this being an option on top of it.

    **What still gets through, stated rather than hidden.** Containment is over words, so a syntactic
    change that alters meaning without introducing a word survives it: the model turned an apposition
    (`... auf das künftige Einkommen — der Beruf, der aufgebaut wird`) into an assertion (`... ist der
    Beruf`), using only words it was given. Word-level checks cannot see that, and no bounded check
    this module could carry would. It is one more reason `prose` is off by default.
    """
    parts = _sentences_of(fact.sentence)
    rewritten: list[str] = []
    for part in parts:
        try:
            reply = llm.chat(
                part,
                system=PROSE_SYSTEM,
                model=model or llm.DEFAULT_MODEL,
                temperature=0,
            )
        except llm.LocalModelUnavailable:
            return fact, "model_unavailable"
        except llm.NotLocal:
            # Never caught and worked around anywhere else in this codebase either. A non-loopback host
            # is a configuration nobody is permitted to make, not a degradation to absorb.
            raise

        candidate = " ".join(reply.text.split()).strip().strip('"').strip()
        if not candidate:
            return fact, "empty"
        if len(_sentences_of(candidate)) != 1:
            return fact, "sentence_added"
        if _figures(candidate) != _figures(part):
            return fact, "figures_changed"
        if len(candidate) > len(part) * PROSE_LENGTH_ALLOWANCE:
            return fact, "too_long"
        if _introduced_content_words(candidate, part):
            # The check that catches invented subject matter. See `_FUNCTION_WORDS` for the sentence
            # that made it necessary and for why there is no allowance here.
            return fact, "content_introduced"
        if _introduced_content_words(part, candidate):
            # The same check with the arguments swapped, because the requirement is "no latitude to add,
            # omit or reorder" and the first call only covers the first verb.
            #
            # Also found in the live model's accepted output rather than by reasoning: it returned
            # `Stabilisierung (Humankapital): hier steht nichts. Kleinere, voneinander unabhängige
            # Einkommensquellen verringern die Schwankungen des Ganzen.` — which quietly dropped
            # `Was hier hingehört:`, and with it R-110's entire point, that an empty cell says what
            # would go there rather than that there is nothing.
            return fact, "content_omitted"
        rewritten.append(candidate)

    try:
        return fact.rephrased(" ".join(rewritten)), None
    except BefundWouldAdvise:
        # The model advised. Caught here rather than propagated: the model straying is the case C-01 says
        # code must catch, and it is not a defect in this module's own copy the way a raise from
        # `_plan_facts` would be.
        return fact, "refused_by_c01"


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def render_befund(
    session: Session,
    *,
    member_id: str,
    language: str = DEFAULT_LANGUAGE,
    today: date | None = None,
    prose: bool = False,
    model: str | None = None,
) -> dict:
    """The Befund: a standing report over what one member has recorded.

    Deterministic with `prose=False`, which is the default. Two calls on an unchanged database return
    byte-identical payloads, and a test pins that.

    R-175: this runs because somebody asked for it. It writes nothing to the database, raises no action
    item, and sends no notification.
    """
    language = _language(language)
    today = today or date.today()

    positions = list(
        session.execute(
            select(Position).where(Position.member_id == member_id).order_by(Position.id)
        ).scalars()
    )
    goal_payloads = list_goals(session, member_id=member_id, today=today)["goals"]
    decisions = list(
        session.execute(
            select(Decision)
            .where(Decision.member_id == member_id)
            .order_by(Decision.created_at, Decision.id)
        ).scalars()
    )
    vault_items = current_items(session, member_id=member_id)
    prepared = action_items(session, member_id=member_id, today=today)
    gaps = reportable_gaps(member_id=member_id, positions=positions, today=today)
    household = current_household(session, member_id=member_id)
    standing_version = standing_plan(session, member_id=member_id, missing_ok=True)

    by_section: dict[str, list[Fact]] = {
        "household": _household_facts(
            household, goal_payloads, language, today=today, standing_version=standing_version
        ),
        "plan": _stock_facts(positions, language) + _plan_facts(positions, language),
        "goals": _goal_facts(goal_payloads, language),
        "decisions": _decision_facts(decisions, language),
        "expiries": _expiry_facts(vault_items, language, today=today),
        "prepared_decisions": _prepared_decision_facts(prepared, language),
        "not_known": _not_known_facts(gaps, language),
    }

    refused: list[dict] = []
    if prose:
        for section_key, facts in by_section.items():
            rewritten = []
            for one in facts:
                replacement, reason = _rephrase(one, model=model)
                if reason:
                    refused.append({"section": section_key, "key": one.key, "reason": reason})
                rewritten.append(replacement)
            by_section[section_key] = rewritten

    sections = []
    for key in SECTIONS:
        facts = by_section[key]
        sections.append(
            {
                "key": key,
                "title": SECTION_TITLE[language][key],
                # C-04: the section's class is the highest any of its facts read, so a caller deciding
                # what may leave the server reads one number rather than walking the facts.
                "data_class": max(one.data_class for one in facts),
                "facts": [one.as_dict() for one in facts],
            }
        )

    return {
        "member_id": member_id,
        "language": language,
        "as_of": today.isoformat(),
        # R-175. Stated in the payload because a client author reads the payload before the docstring.
        "delivered_on_request_only": True,
        "sections": sections,
        # Item 6. Provenance is not currency: `assumptions` below says no figure came from an assumption,
        # and this says whether the figures that came from the member are still inside their published
        # validity horizon. A reader needs both, and neither implies the other.
        #
        # `horizons` carries the content record's own provenance because a content record has no
        # `assumption_set_id` to travel — it is what somebody traces a horizon through.
        "currency": {
            "any_finding_could_not_be_determined": any(
                one.determination == currency_service.COULD_NOT_BE_DETERMINED
                for facts in by_section.values()
                for one in facts
            ),
            "could_not_be_determined": [
                {"section": one.section, "key": one.key, "input_classes": list(one.input_classes)}
                for facts in by_section.values()
                for one in facts
                if one.determination == currency_service.COULD_NOT_BE_DETERMINED
            ],
            "horizons": currency_service.horizon_provenance_or_none(),
        },
        # C-02. The Befund projects nothing, so no figure in it is derived from an assumption and no
        # `assumption_set_id` is owed. Explicit rather than absent: a client should not have to infer
        # from a missing key that no illustration was attempted.
        "assumptions": {
            "any_figure_derived_from_an_assumption": False,
            "assumption_set_id": None,
            "note": _say("assumptions_note", language),
        },
        "prose": {
            "requested": prose,
            # Honest either way: `requested` and `used` differ whenever the model was off or strayed.
            "used": prose and any(
                one.sentence_origin == "model" for facts in by_section.values() for one in facts
            ),
            "model": (model or llm.DEFAULT_MODEL) if prose else None,
            # Which sentences the model was not allowed to replace, and why. A list, not a tally.
            "refused": refused,
        },
        # NO score. NO grade. NO percentage complete. NO filled count, total or ratio. NO "on track".
        # See this module's docstring: C-07, R-113, R-006, and the deliberate absence of a verdict.
    }


def sentences(report: dict) -> list[str]:
    """Every sentence the Befund composed, for a caller that wants to check them.

    Deliberately does not return the quoted material: `quoted` holds what the member wrote, and C-01 is a
    constraint on what eigentliCH says.
    """
    return [one["sentence"] for section in report["sections"] for one in section["facts"]]
