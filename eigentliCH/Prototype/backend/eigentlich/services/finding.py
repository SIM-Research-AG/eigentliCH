"""The first-session finding. Principle 2, and the three things the build has to enforce.

Principle 2: "The first session produces one true, specific, surprising statement about the member's own
situation." What it rules out is stated just as plainly: **"onboarding that reflects back what was typed
in"**.

Item 3 leaves the form open — "composed fresh, drawn from a prepared template where one fits, or a mix of
the two ... authored or generated" — and forbids three specific things by name: a curated library, an
eligibility index, and a per-household-type selector. None of those is here. What is here is the Befund's
own facts, a rule for which of them can carry a finding, and the checks that run after a sentence exists.

===========================================================================================================
THE THREE RULES, AND WHY EACH IS STRUCTURAL RATHER THAN EDITORIAL
===========================================================================================================

**1. It must be about them.** Item 3: "The finding is made against the member's own figures, read from the
Befund. A general fact about Swiss mechanics does not satisfy Principle 2 however interesting it is." So
the candidate pool is drawn from the Befund and nowhere else, and a fact whose `source` is `content` — a
role definition, a template purpose — cannot be one.

**2. It must not reflect back what was typed in.** This is Principle 2's own exclusion, made checkable: a
candidate must be `computed_from_plan`, never `member_stated`. "You have CHF 103,500 in cash" is a
sentence the member could have written themselves; "your recorded financial assets come to CHF 222,750"
is one they could not, because they entered three balances and never the total. That is the whole of the
difference between a report and a finding, and it is one field.

**3. Every figure in it is present in the Befund, checked AFTER the sentence exists.** Item 3 says why, in
the same words it uses twice more elsewhere: "Instructing a model not to invent a number does not hold;
checking the number against the source does." So `unverifiable_figures` — the estate's existing check,
not a second one — runs over whatever came back, and a sentence carrying a figure the Befund does not
have is discarded rather than corrected.

And C-01 runs over it like every other sentence, because a finding is the single most personal thing this
product says: one sentence, about this member's own money, at the moment they are most likely to act on
it. `Fact.__post_init__` already refuses to construct a fact whose sentence would advise; this refuses one
the model wrote.

===========================================================================================================
WHY IT IS ALLOWED TO RETURN NOTHING
===========================================================================================================

`compose` returns `None` when no candidate exists, and the caller says nothing rather than saying
something weaker. A member who has stated one salary and no balances has given the app nothing to be
surprising about, and the light-intake floor is exactly the claim that enough has been said to ground
one — item 3 defines the floor as "household composition, one goal, and enough besides to ground one
finding". So a missing finding is the floor not being met, which is a true thing to report and not a
failure to paper over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from .. import llm
from .befund import render_befund
from .know import unverifiable_figures
from .currency import STANDS

#: A fact may carry a finding only if it was computed rather than stated. See rule 2.
FINDING_SOURCES = ("computed_from_plan",)

#: Facts that are computed but say nothing a member would find specific — they report the absence of
#: something rather than a fact about the member's own position. Excluded by KEY rather than by guessing
#: from the sentence, so the list is visible and arguable.
#:
#: **This is not the "curated library" item 3 forbids.** A library would be a set of prepared findings to
#: choose between; this is the opposite — the pool is everything computed about the member, minus the
#: handful that are structurally about nothing. Adding a fact to the Befund adds it to the pool.
#: Sections that carry no finding by construction. `not_known` is the report's list of what is ABSENT —
#: every fact in it is computed, and every one of them is about something the member has not said. A
#: finding drawn from there would tell them what is missing, which is `locked_findings`' job and is the
#: opposite of Principle 2's "surprising statement about the member's own situation".
NOT_A_FINDING_SECTION = frozenset({"not_known"})

#: **Every entry here has the same shape: "nothing of this kind is recorded".** They are computed, they
#: are about the member, and they say what is MISSING — which is `onboarding.locked_findings`' job and is
#: the opposite of a surprising statement about a member's own situation. Found by rendering a Befund for
#: a member who has said nothing and reading what came back, rather than by imagining the list.
NOT_A_FINDING = frozenset(
    {
        "no_goals_recorded",
        "no_decisions_recorded",
        "plan_is_empty",
        "cell_empty",
        "cell_filled",
        "cell_inactive_only",
        "household_not_stated",
        "goal_owner_not_recorded",
        "no_expiry_dates_recorded",
        "nothing_prepared",
    }
)


@dataclass(frozen=True)
class Finding:
    """One statement, and everything needed to check it."""

    sentence: str
    #: The Befund fact it rests on. A finding always names its source fact — R-171's rule, applied to the
    #: one sentence most likely to be quoted back.
    fact_key: str
    section: str
    #: `computed` when the Befund's own sentence was used, `model` when it was reworded and passed.
    origin: str
    #: The deterministic sentence, when the model's was used instead. Never None then, always None
    #: otherwise — the same biconditional `Fact` carries, for the same reason.
    computed_sentence: str | None = None

    def as_dict(self) -> dict:
        return {
            "sentence": self.sentence,
            "fact_key": self.fact_key,
            "section": self.section,
            "origin": self.origin,
            "computed_sentence": self.computed_sentence,
        }


def candidates(report: dict) -> list[dict]:
    """The facts in a Befund that could carry a finding, best first.

    "Best" is: a fact with a figure in it, before one without. Not a score and not a ranking of the member
    — a rule over the payload's own shape, so that "your recorded financial assets come to CHF 222,750"
    is offered ahead of "no position funds this goal" without anybody having to rate the two.
    """
    pool = [
        fact | {"section": section["key"]}
        for section in report["sections"]
        for fact in section["facts"]
        if fact["source"] in FINDING_SOURCES
        and section["key"] not in NOT_A_FINDING_SECTION
        and fact["key"] not in NOT_A_FINDING
        and fact["determination"] == STANDS
    ]
    # A figure is what makes a finding specific. `sorted` is stable, so within each group the Befund's own
    # editorial section order survives.
    return sorted(pool, key=lambda fact: not _has_figure(fact))


def _has_figure(fact: dict) -> bool:
    return any(isinstance(value, (int, float)) and not isinstance(value, bool)
               for value in fact.get("values", {}).values())


#: What the model is asked to do, and the whole of it. It rewords ONE sentence it is given; it does not
#: choose, does not compute, and is not shown the member's other facts. "Model chooses, code computes" is
#: the update script's tenth non-negotiable, and here the model does not even choose.
REWORD_SYSTEM = (
    "Du formulierst einen einzigen, bereits vollständigen Satz flüssiger um. "
    "Regeln: Gib genau einen Satz zurück. Übernimm jede Zahl unverändert. "
    "Füge nichts hinzu — keine Empfehlung, keine Einschätzung, keine Zahl, keinen zweiten Satz. "
    "Lass nichts weg. Antworte nur mit dem Satz."
)


def compose(
    session: Session,
    *,
    member_id: str,
    language: str = "de",
    today: date | None = None,
    model: str | None = None,
    reword: bool = False,
) -> Finding | None:
    """One finding, or None when the member has not said enough to ground one.

    `reword=False` by default, and the default is the honest one: the Befund's own sentence is already
    deterministic, sourced and C-01-checked, and item 3 permits a finding "drawn from a prepared template
    where one fits". Asking a model to improve a sentence that is already correct buys wording and risks
    meaning.

    With `reword=True` the model is handed the sentence and nothing else, and its answer is kept only if
    it survives both checks. A refusal falls back to the computed sentence rather than to nothing: the
    finding was true before the model saw it.
    """
    report = render_befund(session, member_id=member_id, language=language, today=today)
    pool = candidates(report)
    if not pool:
        return None

    chosen = pool[0]
    finding = Finding(
        sentence=chosen["sentence"],
        fact_key=chosen["key"],
        section=chosen["section"],
        origin="computed",
    )
    if not reword:
        return finding

    try:
        reply = llm.chat(
            chosen["sentence"],
            system=REWORD_SYSTEM,
            model=model or llm.DEFAULT_MODEL,
            temperature=0,
        )
    except llm.LocalModelUnavailable:
        # R-302's shape: not available, never a guess. The computed sentence is not a degraded answer —
        # it is the one the model was going to be asked to reword.
        return finding

    candidate = (reply.text or "").strip()
    if not candidate or not verify(candidate, report=report, against=chosen):
        return finding
    return Finding(
        sentence=candidate,
        fact_key=chosen["key"],
        section=chosen["section"],
        origin="model",
        computed_sentence=chosen["sentence"],
    )


def verify(sentence: str, *, report: dict, against: dict) -> bool:
    """The check that runs AFTER a sentence exists. It must pass for the sentence to be used.

    Deliberately a predicate over a finished sentence rather than an instruction given beforehand — item 3
    records why in the OGD portal's words, and this build has the same finding twice more (A114, and the
    `figure_not_in_sources` branch in `know.ask`).

    **There were two checks until 20 September 2026.** The first was C-01's outbound scan, on the grounds
    that this is a sentence about the member's own money at the moment they are most likely to act on it.
    C-01 was withdrawn (A164) and that check is gone. The figure check below is not C-01's and stays: a
    sentence carrying a number nobody can trace to the report is wrong whoever reads it.
    """
    # Every figure present in the Befund. Not "in the fact it came from": a reworded sentence may
    # legitimately carry a figure from elsewhere in the report, and the Befund is the closed object the
    # rule names. `unverifiable_figures` is the estate's existing check and is not reimplemented.
    return not unverifiable_figures(sentence, _passages(report))


class _ReportPassage:
    """The shape `unverifiable_figures` reads: anything with a `.text`.

    A tiny adapter rather than a change to that function's signature — it is used by `know.ask` over real
    passages and widening it to a union type would make both call sites harder to read than this is.
    """

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def _passages(report: dict) -> list[_ReportPassage]:
    """Every figure the Befund holds, as text. Both the sentences and the values behind them.

    The values matter: `_amount` renders 222750.0 as `222'750`, and a model that wrote `222750` would be
    quoting the same figure in a different hand. `unverifiable_figures` compares digits only, so both
    spellings verify against either.
    """
    out: list[_ReportPassage] = []
    for section in report["sections"]:
        for fact in section["facts"]:
            out.append(_ReportPassage(fact["sentence"]))
            out.append(_ReportPassage(" ".join(str(value) for value in fact["values"].values())))
    return out


__all__ = [
    "FINDING_SOURCES",
    "Finding",
    "NOT_A_FINDING",
    "NOT_A_FINDING_SECTION",
    "candidates",
    "compose",
    "verify",
]
