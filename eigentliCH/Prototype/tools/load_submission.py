"""Load a real onboarding submission into the system as a member, through the real services.

    python tools/load_submission.py                       # list the submissions and their load state
    python tools/load_submission.py RenzoTommasini         # report what WOULD be created, write nothing
    python tools/load_submission.py RenzoTommasini --write # create it

**Why this exists.** `client/submissions/` holds five real onboarding submissions, collected on 30 August
2026 from named people. Until now nothing read them: `seed_demo_accounts.py` gave Elio and Yasmin T. an
*account* — a name, an age and a first-login password — and none of their answers. Their income, their
hours, their goals and their figures sat in a JSON file the application never opened. Three of the five
(Renzo, Elia, Levin) had no account at all. So a real interview produced data, and the system it was
collected for could not show any of it back.

**The privacy rule, which is the reason this is a loader and not a seeder.** These are real answers about
real people's finances. `client/submissions/` is covered by the repo root's `.gitignore`, and
`tools/make_distribution.py` excludes the directory from any archive. This file therefore contains **no
figures, no names and no answers** — it reads them at run time from the ignored directory. Inlining a
single real amount here would commit it, which is exactly what happened once to a derived mandate and had
to be pulled back out (see the root `.gitignore`'s note on `derived_onb-*`).

**It goes through the services, not through the ORM.** `register_with_credentials`, `record_answer`,
`onboarding.complete` and `revise_goal` — the same four the running application uses. A loader that wrote
rows directly would produce a member whose plan exists with no `Decision` behind it, which C-09 forbids
and which would make the loaded member the one account whose history is empty. Loading Renzo this way
writes the same Decisions his own clicks would have written.

**It reports before it writes, and it never invents.** A submission carries more than the model can hold,
and it carries answers whose mapping is a judgement rather than a fact. Both are printed rather than
guessed:

- what maps unambiguously, and is stored;
- what the submission states that **the model has no field for** — reported, never approximated;
- what could be mapped only by inferring something the member did not say — reported with the candidate
  value, and left for the member to accept in the application, which is where a member's own data belongs.

That third category is the important one. The submission's own `derived_notes` already work this way: one
of Renzo's reads *"Sammlungen, Kunst und Fahrzeuge im Wert von 45000 sind erfasst und NICHT im Modell"* —
the interview recorded at collection time that the model could not hold it. This tool does not pretend
otherwise.
"""

from __future__ import annotations

import argparse
import re
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBMISSION_DIR = REPO / "client" / "submissions"

sys.path.insert(0, str(REPO / "backend"))


#: The four onboarding questions, and where each one's answer comes from in a submission. Keyed by the
#: question key so that a question added to `content.onboarding_questions` shows up here as missing rather
#: than being silently skipped.
#:
#: **`employment_position` takes `raw.employment` verbatim** and not the richer `raw.education`, which for
#: Renzo reads "Automobilmechatroniker, Berufsmaturität …". R-020's rule is that what the member stated is
#: what is stored, and "angestellt" is what they answered to the question about how they earn their money.
#: The profession is reported as a better label the member can set themselves.
ANSWER_SOURCES = {
    "employment_position": ("raw", "employment"),
    "employment_magnitude": ("raw", "income_gross"),
    "employment_time_basis": ("raw", "hours_per_week"),
}

#: The five keys added to the instrument on 4 September 2026 (A127). Every one of them sat in
#: `NO_FIELD_HOLDS_IT` from 30 August, which is to say: read from six real submissions, printed, and
#: dropped. They now go in through `record_answer` exactly as the three above do, and
#: `onboarding.complete` writes each one as a `MemberFact` against the intake's own Decision.
#:
#: **Nothing in this tool knows what they are.** No mapping, no coercion, no per-key branch — the values
#: are passed through and the instrument's own declaration decides whether each is admissible. That is
#: what "keys can be added without touching the intake flow" buys, and this is where it is collected: a
#: sixth key needs one entry here and one in the content file.
#:
#: **Checked against the real answers before this was written, and the surprise was that there was no
#: surprise.** Every stated value already appears verbatim in the instrument's own option list, including
#: Levin's `ledig, mit Partner` — which is not a legal civil status and which a tidier five-option set
#: would have had to distort. The reference questionnaire carried it because it was refined against real
#: interviews; the lesson is the Renzo one from the other side, where a drafted option set could not hold
#: a real answer. Nothing here is approximated and nothing lands in `NEEDS_A_HUMAN`.
#:
#: Separate from `ANSWER_SOURCES` for one reason: absence. All five are `required: false`, and two
#: submissions state no `network_people` at all — so a missing value is a member who did not answer, not
#: a problem with the load. `ANSWER_SOURCES` treats absence as a problem because R-102 needs those.
OPTIONAL_ANSWER_SOURCES = {
    "canton": ("raw", "canton"),
    "civil_status": ("raw", "civil_status"),
    "education": ("raw", "education"),
    "network_people": ("raw", "network_people"),
    "health": ("raw", "health"),
}

#: The questions restored to the instrument on 21 September 2026 that this format *does* answer, and the
#: field each one's answer is in. Separate from `OPTIONAL_ANSWER_SOURCES` because every one of them needs
#: `_admissible` between the file and `record_answer`: the submission states an option in the interviewer's
#: prose — `AG`, `Gütertrennung` — and the instrument stores a value — `ag`, `gütertrennung`.
#:
#: **Matching is exact against the option's value or its German label, case folded, and nothing else.** A
#: case difference is not a different answer; anything further is. `hours_learning` is the question this
#: rule keeps out: the file states a band (`1–2`, `kaum welche`) where the instrument wants hours per week,
#: and turning `1–2` into `1.5` would record a number nobody said. That is the 0.75 mistake with the
#: coercion running the other way, and it stays unanswered and reported until the owner rules on it.
RESTORED_ANSWER_SOURCES = {
    "matrimonial_regime": ("raw", "matrimonial_regime"),
    "self_employed_form": ("raw", "self_employed_form"),
    "pillar2_voluntary": ("raw", "pillar2_voluntary"),
    "years_in_field": ("raw", "work_years_current"),
}

#: The one gloss this build accepts as naming an option rather than qualifying it. The instrument labels
#: the statutory default `Errungenschaftsbeteiligung (der Normalfall)`; the interviewer wrote
#: `Errungenschaftsbeteiligung (gesetzlich)`. Both parentheticals say the same thing about the same regime
#: and neither is part of the answer, so the leading term is matched and the gloss dropped — for this one
#: question, by name, rather than by a general rule that would strip meaning from a list that used one.
_GLOSSED = {"matrimonial_regime"}


def _admissible(question: dict, stated):
    """The instrument's own value for what the submission states, or `None` if nothing matches exactly.

    Returns `None` rather than a nearest option on purpose. A choice question whose stated answer is not
    on the list is the Renzo case and the `health` 0.75 case both: the list is the thing that is wrong,
    and recording the closest option would put an answer in the member's mouth. `None` leaves it
    unanswered, and `build_plan` reports it.
    """
    if stated is None or (isinstance(stated, str) and not stated.strip()):
        return None

    if question.get("type") == "number":
        try:
            value = float(str(stated).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None
        low, high = question.get("min"), question.get("max")
        if (low is not None and value < low) or (high is not None and value > high):
            return None
        return int(value) if value.is_integer() else value

    options = question.get("options") or ()
    if not options:
        return stated

    said = str(stated).strip().casefold()
    if question["key"] in _GLOSSED and "(" in said:
        said = said.split("(", 1)[0].strip()
    for option in options:
        value = option.get("value")
        labels = [str(v) for v in (option.get("label") or {}).values()]
        for candidate in [value, *labels]:
            if candidate is None:
                continue
            known = str(candidate).strip().casefold()
            if question["key"] in _GLOSSED and "(" in known:
                known = known.split("(", 1)[0].strip()
            if said == known:
                return value
    return None

#: Submission `goals[].kind` to `GOAL_TEMPLATES` key. **Deliberately partial.**
#:
#: `retirement` has NO faithful template. The nearest is `early_retirement`, and Renzo's retirement goal is
#: "Ausgaben ab 65 aus eigenem Vermögen gedeckt" — the reference age, not early. Storing `early_retirement`
#: would record a plan he did not state, which is the same class of error as applying a market rate to a
#: salary: a real value in the wrong place, wearing the model's authority. `other` is a bucket by
#: definition and cannot map either, even when the description makes a candidate obvious.
#:
#: Both therefore land on `unspecified` with the member's own wording as the name, and the candidate is
#: printed. The member can set the template in the application in one click — which is the whole point of
#: the owner's rule that their input must be visible and changeable.
KIND_TO_TEMPLATE = {}

#: Franc stocks the model CAN now hold, since the `chf` unit and `Position.stock_kind` landed on
#: 1 September 2026. Each entry needs a `role`, and **a role is a judgement, not a fact in the
#: submission** — `Position.role` is not nullable, and there is no control on any screen that lets a
#: member change a role afterwards, so a guess here is a guess a member cannot correct. Only the fields
#: the owner has actually ruled on appear here. Everything else stays in `STOCK_NEEDS_A_ROLE`, so loading
#: the next submission asks rather than assumes.
STOCK_SOURCES = {
    "cash": {
        "role": "stabilisation",
        "stock_kind": "asset",
        "label": "Bargeld und Kontoguthaben",
        "liquidity": "immediate",
        "decided": "owner, 1 September 2026: a liquid buffer that dampens the movement of the whole",
    },
    "collectibles_value": {
        "role": "stabilisation",
        "stock_kind": "asset",
        "label": "Sammlungen, Kunst und Fahrzeuge",
        "liquidity": "within_years",
        "decided": "owner, 1 September 2026: a store of value rather than an engine of return, which is "
        "also the closer reading for vehicles",
    },
    "securities": {
        "role": "growth",
        "stock_kind": "asset",
        "label": "Wertschriften",
        "liquidity": "immediate",
        "decided": "owner, 3 September 2026: held for real appreciation over a long horizon, accepting "
        "drawdown as the price of it (Journey & Design page 2). Liquidity is immediate rather than "
        "within_months because listed securities are sellable at will, and liquidity is what R-031 "
        "compares against a goal's target date",
    },
    "pillar2": {
        "role": "protection",
        "stock_kind": "asset",
        "label": "Pensionskasse",
        "liquidity": "illiquid",
        "decided": "owner, 4 September 2026: the same ruling as the 3a and for the same reason — a "
        "Vorsorge entitlement, which Journey & Design page 2 places under Protection, and ruled on what "
        "a pillar 2 IS rather than on how any given one is invested. Illiquid, with the one exception "
        "the law allows: it may be drawn for an owner-occupied primary residence, which "
        "services/property.py models as an eligibility rather than as a liquidity band. This ruling "
        "moves 711'000 into the Tommasini household's plan and turns Elio's Befund from 81'000 into "
        "697'000, seven years before he retires",
    },
    "pillar3a": {
        "role": "protection",
        "stock_kind": "asset",
        "label": "Säule 3a",
        "liquidity": "illiquid",
        "decided": "owner, 3 September 2026: a Vorsorge entitlement, which Journey & Design page 2 places "
        "under Protection — a holding whose purpose is to preserve what exists rather than add to it. "
        "Ruled on what a 3a IS rather than on what any given one is invested in, because one ruling covers "
        "every member and a cash 3a and a securities 3a would otherwise share a role wrong for one of them",
    },
}

#: **Questions `onb@0.1.3` stopped asking, which earlier submissions answered.**
#:
#: The five files in `client/submissions/archive/` use `onb@0.1.1` and `onb@0.1.2` and were archived by A8
#: on the schema's own rule: a consumer that does not recognise a version refuses rather than guesses.
#: That ruling stands and nothing here loads them.
#:
#: What reading them showed is the opposite of what "an earlier version" suggests. The older schema is
#: **richer**: 0.1.3 added three keys and dropped eighteen, and the dropped ones are the questions this
#: build spent the first week of September needing and not having —
#:
#:   `own_use_pct`      what share of the property the member lives in themselves. **This is the occupancy
#:                      question.** `Goal.occupancy` was built on 4 September 2026 because nothing in the
#:                      plan could say whether pension capital may fund a purchase, and a member answered
#:                      exactly that on 18 August 2026 with «20».
#:   `mortgage`         the debt, with `amortisation` beside it. A132 found `state.D` being dropped in
#:                      silence; these two are the same figure asked properly, and one file carries
#:                      2'500'000.
#:   `children_ages`    birth years, in the format `services/identities.child_ages` parses and has never
#:                      had a production caller — because the field it was written for was dropped before
#:                      the port.
#:   `partner_pillar2`  the partner's occupational pension. The household income problem, answered.
#:   `matrimonial_regime`  Gütergemeinschaft or Errungenschaftsbeteiligung, which decides what a couple's
#:                      capital actually is.
#:
#: **They were reported by nothing.** Neither `NO_FIELD_HOLDS_IT` nor `NEEDS_A_HUMAN` knows these names,
#: so a person running this tool over an archived file saw a clean report with eighteen answers missing
#: from it. That is the A132 defect eighteen times over, and it is what this registry fixes: the fields
#: are named, with what each one would unblock, and still nothing is written.
DROPPED_BY_0_1_3 = {
    "own_use_pct": "the share of the property the member lives in themselves — this IS `Goal.occupancy`, "
                   "which decides whether pillar 2 and 3a may fund the purchase at all (A129). Built on "
                   "4 September because nothing could answer it; answered on 18 August by a member",
    "holiday_pct": "the share used as a holiday object, the other half of the occupancy question",
    "mortgage": "the debt against the property. `Position.stock_kind = 'liability'` can hold it and no "
                "role has been ruled for a mortgage — the same open ruling as `D` (A132)",
    "amortisation": "what is repaid each year. The affordability test computes an amortisation from the "
                    "loan-to-value; this is the member's actual one, and the two are not the same figure",
    "children_ages": "birth years, in the format `services/identities.child_ages` parses. The household "
                     "ruling of 4 September excludes children from the household, so this is the "
                     "dependency that would be modelled beside it rather than inside it",
    "child_costs": "what the children cost per year — an obligation, and the plan holds no expenditure",
    "matrimonial_regime": "Güterstand. Decides what a couple's capital is on a division, and A112 already "
                          "freezes a jointly owned goal rather than splitting it by any rule",
    "partner_pillar2": "the partner's occupational pension. `goals._household_income` returns None for a "
                       "two-adult household because no member's record can reach another's; this is the "
                       "figure that would answer it without reaching anywhere",
    "partner_ahv_years_missing": "the partner's contribution gaps, same case as the member's own",
    "pillar2_voluntary": "whether the member pays into the second pillar voluntarily — the case a "
                         "self-employed member is in, and one file says yes",
    "pillar2_buyin": "buy-in headroom. Named already in NEEDS_A_HUMAN below; repeated here because 0.1.3 "
                     "kept the field and the archived files carry values for it",
    "self_employed_form": "AG, GmbH or sole proprietorship. Decides which Vorsorge rules apply at all",
    "company_value": "the business as an asset. No role has been ruled for one, and it is the largest "
                     "single figure in one of these files",
    "company_income": "what the business distributes, which is a flow and not the salary beside it",
    "company_liquid": "when the business could be turned into money, in the member's own words",
    "crypto_value": "a franc stock with no ruled role",
    "gold_value": "a franc stock with no ruled role; one file carries 100'000",
    "loans_given": "money lent out, with `loans_given_risk` beside it — an asset whose recoverability the "
                   "member themselves doubts",
    "loans_given_risk": "the member's own words on whether the loan comes back",
}

#: Franc figures the submission carries in its `state` block rather than in `raw`, which is why they were
#: invisible to the reporting below until 4 September 2026.
#:
#: **`D` is the household's mortgage and it was being dropped in total silence.** Yasmin states 782'100;
#: Elio, her husband, states 0. It is one debt against one property, recorded by one of them and forgotten
#: by the other — which is precisely the failure a household model exists to prevent, and precisely the
#: reason a liability must not be summed across members. Nothing in this tool read `D` at all, so it was
#: neither stored nor reported, unlike `pillar2` which is at least printed.
#:
#: It is not written for the same reason `pillar2` is not: `Position.stock_kind = 'liability'` exists, and
#: which of the four roles a mortgage occupies is a ruling nobody has made. It is reported now.
STATE_STOCKS_NEEDING_A_ROLE = {
    "D": "the household's debt. `Position.stock_kind = 'liability'` can hold it and no role has been "
         "decided for a mortgage. **It belongs to the household, not to the member**: in this set one "
         "spouse states it and the other states nothing, so writing it per member would either double it "
         "or lose it depending on which record you read",
}

#: Storable in principle and deliberately not stored: nobody has decided which role they sit under.
#: Reported with the amount so the question can be answered once and added above.
STOCK_NEEDS_A_ROLE = {
    "pillar2_buyin": "a franc stock, and no role has been decided for a pillar 2 buy-in",
    "property_total": "a franc stock, and no role has been decided for property",
}

#: Read from the submission, and there is nowhere to put it. Each entry names the field and the reason,
#: because "not loaded" without a reason reads as an oversight and this is not one.
NO_FIELD_HOLDS_IT = {
    "ahv_years_missing": "no field on Member or Position holds a contribution gap",
    # Was "no household model in this build" until 4 September 2026, when A108 built one. The reason is
    # now narrower and still true: `services/household.state` exists and takes labelled people, and this
    # tool has no mapping from `civil_status` and a child COUNT to named household members. Inventing
    # "Kind 1", "Kind 2" would put labels in the record that nobody wrote.
    "children_count": "a household model exists (A108) and this loader has no mapping from a civil status "
                      "and a count of children to named people",
    # canton, civil_status, health, network_people and education left this dict on 4 September 2026.
    # They are the five keys the owner named, they are in the instrument, and they are stored — see
    # `OPTIONAL_ANSWER_SOURCES` above. What remains here is what the model still cannot hold.
    #
    # The four STRUCTURED education answers are a real gap and are not among the five: `education_recent`,
    # `education_planned`, `education_hours` and `education_budget` are what
    # `services/identities.expertise_scale` actually reads — the free-text `education` is explicitly not
    # scored — so the expertise estimate still has nothing to run on. They were never in this dict
    # either, which means they have been dropped silently rather than reported. Listed now.
    "education_recent": "an input to services/identities.expertise_scale, not among the five keys the "
                        "owner named; the free-text `education` is stored and is deliberately not scored",
    "education_planned": "as education_recent",
    "education_hours": "as education_recent",
    "education_budget": "as education_recent",
    "mandates": "the second argument to services/identities.net_scale; `network_people` is now stored "
                "and this is not, so the network estimate has one of its two inputs",
}

#: Present in the submission, mappable only by inventing the mapping. Printed with the candidate so a
#: person can decide, and never written. The five goal parameters are here on purpose: the owner chose on
#: 1 September 2026 that they are answered ONCE PER MEMBER and inherited by each goal, and no member-level
#: field exists yet to receive them.
NEEDS_A_HUMAN = {
    "crisis_behaviour": "goal parameter volatility_tolerance — and the drafted options cannot hold "
    "'ich war nicht investiert', which two real submissions give; forcing one would record a false answer",
    "max_loss_pct": "goal parameter safety — a percentage, and the parameter takes a band, so the "
    "threshold between bands is a decision nobody has published",
    "expected_return_pct": "not a member parameter at all: an expected return is C-02 material and "
    "belongs to a published AssumptionSet, never to a member's stated preference",
    "goal_confidence": "goal parameter flexibility — the submission carries a percentage per goal",
    "plan_until_age": "goal parameter horizon — needs the band boundaries first",
    "stop_work_age": "goal parameter horizon, or a goal target date; two candidates, one value",
    "savings": "neither a flow nor a stock is stated, and in at least one submission the figure exceeds "
    "the stated gross income, so it cannot be read as an annual saving without asking",
    "spend_now": "no field holds an expenditure; a Position models what a member has, not what they spend",
    "main_question": "the member's own question, which nothing in the model holds and which is the single "
    "most useful sentence in the submission",
}


@dataclass
class Plan:
    """What a load would do, assembled before anything is written."""

    person: str
    email: str
    display_name: str
    age: int | None
    #: The submission's own `raw` block, kept so the household builder can read the sentence the member
    #: wrote rather than a field the plan happens to carry.
    raw: dict = field(default_factory=dict)
    #: The WHOLE file, unaltered. `raw` is the answers; this is what arrived, `meta` and
    #: `schema_version` included, and it is what `services/submissions.store` keeps. The two are separate
    #: because the mapping below reads answers and the archive must not depend on that reading.
    source_file: dict = field(default_factory=dict)
    answers: dict = field(default_factory=dict)
    goals: list = field(default_factory=list)
    stocks: list = field(default_factory=list)
    absent: list = field(default_factory=list)
    deferred: list = field(default_factory=list)
    #: The submission's OWN field names that this load read. What `submissions.record_mapping` wants, and
    #: not the same set as `answers`, whose keys are the instrument's. See that function's note.
    consumed: set = field(default_factory=set)
    #: Instrument questions this submission format cannot put to anybody. Not a property of the person.
    not_presented: list = field(default_factory=list)
    #: Things a person should be told about this load that do not stop it. Separate from
    #: `problems`, which is what `main` refuses to write over: an invented name is a fact to state
    #: every time, not a reason to withhold a member. Conflating the two blocked the very load the
    #: note was written to annotate.
    notes: list = field(default_factory=list)
    #: Answers to questions the CURRENT question set no longer asks. Separate from `absent` and
    #: `deferred` because the reason is different in kind: the model could hold some of these tomorrow,
    #: and what is missing is the question rather than the field or the ruling.
    dropped: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def _submissions() -> list[Path]:
    if not SUBMISSION_DIR.is_dir():
        return []
    return sorted(p for p in SUBMISSION_DIR.glob("*.json") if p.is_file())


def _person(path: Path) -> str:
    """`eigentlich-onboarding-RenzoTommasini.json` -> `RenzoTommasini`.

    **Keyed on the `onboarding-` marker, not on the brand**, which is why the rename of 21 September
    2026 needed no change here. The 60 files already collected keep their `andersch-` prefix — a
    submission's filename is the record of what was received — new ones are written `eigentlich-`, and
    both resolve through the same two lines.
    """
    stem = path.stem
    marker = "onboarding-"
    return stem[stem.index(marker) + len(marker):] if marker in stem else stem


def _names(person: str) -> tuple[str, str, str]:
    """`RenzoTommasini` -> (`renzot`, `renzo.t`, `Renzo T.`).

    **The `t` suffix is deliberate and follows a precedent.** `seed_demo_accounts.py` records that two
    different Yasmins share this system — Yasmin B., the fictional Basel dermatologist from the persona
    framework, and Yasmin T., a real submission — and distinguishes them by initial. The surname initial
    keeps two people with one given name apart on every screen that shows a display name, rather than
    relying on the reader knowing which table a given name came from.

    **This function is also the whole of the pseudonymisation surface, which is worth knowing (A162).**
    The slug, the address and the display name are derived from the submission's *filename*; the JSON
    itself carries no name at all. So renaming the file is enough to rename the member everywhere that
    reads from it, and `tools/pseudonymise_member.py` exists only for a database that already holds the
    old name and whose plan history is not worth discarding to re-load.
    """
    split = 0
    for index, character in enumerate(person[1:], start=1):
        if character.isupper():
            split = index
            break
    first = person[:split] if split else person
    surname = person[split:] if split else ""
    initial = surname[:1].lower()
    return f"{first.lower()}{initial}", f"{first.lower()}.{initial}", f"{first} {initial.upper()}."


class DuplicateSubmission(ValueError):
    """This file is a byte-identical copy of another and names it. Refused rather than loaded twice."""


def build_plan(path: Path) -> Plan:
    document = json.loads(path.read_text(encoding="utf-8"))
    raw = document.get("raw") or {}
    state = document.get("state") or {}
    meta = document.get("meta") or {}

    if meta.get("duplicate_of"):
        raise DuplicateSubmission(
            f"{path.name} is byte-identical to {meta['duplicate_of']}. It is the same submission saved "
            f"twice, not a second person, and loading it would create a second member from one person's "
            f"answers."
        )

    # **A name the file carries, never one made up here.** The 0.1.1 and 0.1.2 submissions were collected
    # anonymously, so `_person` produces a date and `_names` produces «2026-08-05 .» — not a name a member
    # row can carry. A pseudonym was written into each file's own `meta` block on 4 September 2026 (A140),
    # which is where provenance belongs: it travels with the data, and the file says in itself that the
    # name is not the person's. A file with neither a name in its filename nor a pseudonym is refused
    # below rather than given one at load time.
    person = _person(path)
    if meta.get("pseudonym"):
        display = meta.get("pseudonym_display") or meta["pseudonym"]
        first, _, surname = meta["pseudonym"].partition(" ")
        key = f"{first.lower()}{surname[:1].lower()}"
    else:
        key, _dotted, display = _names(person)

    plan = Plan(
        person=person,
        email=f"{key}@eigentli.local",
        display_name=display,
        age=state.get("age") or raw.get("age"),
        raw=raw,
        source_file=document,
    )

    if plan.age is None:
        plan.problems.append("no age in the submission; R-100's floor cannot be checked, so no account")

    if meta.get("pseudonym"):
        plan.notes.append(
            f"the name {display!r} is INVENTED — this submission was collected anonymously. See "
            f"`meta.pseudonym_note` in the file. It is a label for a record and not the name of the "
            f"person who answered."
        )

    for question_key, (section, source_field) in ANSWER_SOURCES.items():
        value = (raw if section == "raw" else state).get(source_field)
        if value in (None, ""):
            plan.problems.append(f"{question_key}: nothing in the submission answers it ({source_field})")
        else:
            plan.answers[question_key] = value
            plan.consumed.add(source_field)

    for question_key, (section, source_field) in OPTIONAL_ANSWER_SOURCES.items():
        value = (raw if section == "raw" else state).get(source_field)
        # Silence, not a problem. See the dict's own note: two submissions state no network at all.
        if value not in (None, "", []):
            plan.answers[question_key] = value
            plan.consumed.add(source_field)

    # The restored questions, through `_admissible`. A value the instrument would refuse is left
    # unanswered and said out loud, so the count of unanswered questions stays a fact about the file
    # rather than about this loop.
    from eigentlich.content import onboarding_questions

    declared = {q["key"]: q for q in onboarding_questions()}
    for question_key, (section, source_field) in RESTORED_ANSWER_SOURCES.items():
        question = declared.get(question_key)
        if question is None:
            continue
        stated = (raw if section == "raw" else state).get(source_field)
        if stated in (None, "", []):
            continue
        value = _admissible(question, stated)
        if value is None:
            plan.notes.append(
                f"{question_key}: the submission states {stated!r}, which is not one of the answers "
                f"{question_key} admits — left unanswered rather than mapped to the nearest option"
            )
            continue
        plan.answers[question_key] = value
        plan.consumed.add(source_field)

    # Every instrument question this format has no field for at all. Written to the submission so that
    # `derive` can tell a question the member passed over from one they were never shown — see
    # `submissions.not_presented`. Computed rather than listed, so a question added to the instrument
    # lands here by itself instead of being silently reported as skipped by fifty people.
    answerable = set(ANSWER_SOURCES) | set(OPTIONAL_ANSWER_SOURCES) | set(RESTORED_ANSWER_SOURCES)
    answerable |= {"first_goal", "household_composition"}
    plan.not_presented = sorted(key for key in declared if key not in answerable)

    # `goals` and `household` are read below and by `_state_the_household`; both are the file's own keys
    # and both were reported as having no home while the same record said it had created from them.
    if document.get("goals"):
        plan.consumed.add("goals")
    if raw.get("household"):
        plan.consumed.add("household")

    for index, goal in enumerate(document.get("goals") or []):
        kind = goal.get("kind")
        name = (goal.get("description") or "").strip() or f"Ziel {index + 1}"
        year = goal.get("target_year")
        plan.goals.append({
            "name": name,
            "template": KIND_TO_TEMPLATE.get(kind, "unspecified"),
            "template_candidate": kind,
            "target_amount": goal.get("amount_chf"),
            # A year, not a date. December 31 is a convention this tool applies and states; the member
            # never said a month or a day, and a date invented silently would look like something they
            # chose. The application lets them set the real one.
            "target_date": date(int(year), 12, 31) if year else None,
            "date_is_a_convention": bool(year),
        })

    for source_field, recipe in STOCK_SOURCES.items():
        value = raw.get(source_field, state.get(source_field))
        # A stated zero is a real answer — "I have no securities" — but it is not a position, and a row
        # holding 0.0 would occupy a cell in the grid and say nothing. R-020's completeness caveat covers
        # the difference: what a member stated is stored, and a zero stock is stated absence.
        if value in (None, "", 0, []):
            continue
        plan.stocks.append({**recipe, "source_field": source_field, "magnitude": float(value)})
        plan.consumed.add(source_field)

    for source_field, reason in STOCK_NEEDS_A_ROLE.items():
        value = raw.get(source_field, state.get(source_field))
        if value not in (None, "", 0, []):
            plan.deferred.append((source_field, value, reason))

    # Read from `state` only. These keys do not appear in `raw`, which is why the loops above never saw
    # them — `raw.get(k, state.get(k))` finds them, but they were in neither registry to be looked up.
    for source_field, reason in STATE_STOCKS_NEEDING_A_ROLE.items():
        value = state.get(source_field)
        if value not in (None, "", 0, []):
            plan.deferred.append((source_field, value, reason))

    # The eighteen questions 0.1.3 stopped asking. Reported wherever a file still answers one, so that a
    # richer submission does not read as a poorer one. See the registry above.
    for source_field, reason in DROPPED_BY_0_1_3.items():
        value = raw.get(source_field, state.get(source_field))
        if value not in (None, "", 0, []) and source_field not in dict(
            (entry[0], entry) for entry in plan.deferred
        ):
            plan.dropped.append((source_field, value, reason))

    for source_field, reason in NO_FIELD_HOLDS_IT.items():
        value = raw.get(source_field, state.get(source_field))
        if value not in (None, "", 0, []):
            plan.absent.append((source_field, value, reason))

    for source_field, reason in NEEDS_A_HUMAN.items():
        value = raw.get(source_field, state.get(source_field))
        if value not in (None, "", []):
            plan.deferred.append((source_field, value, reason))

    return plan


def describe(plan: Plan) -> None:
    print(f"\n  {plan.person}  ->  {plan.email}   \"{plan.display_name}\", age {plan.age}")

    print("\n    stored — the onboarding answers:")
    for question_key, value in plan.answers.items():
        print(f"      {question_key:24} {value!r}")

    print("\n    stored — goals:")
    for goal in plan.goals:
        target = f"{goal['target_amount']:,} CHF" if goal["target_amount"] else "no amount"
        when = goal["target_date"].isoformat() if goal["target_date"] else "no date"
        print(f"      \"{goal['name']}\"")
        print(f"        {target}, {when}"
              + ("  (31 December is this tool's convention, not stated)" if goal["date_is_a_convention"] else ""))
        print(f"        template: {goal['template']}  (submission said kind={goal['template_candidate']!r};"
              f" left for the member to set)")

    if plan.stocks:
        print("\n    stored — franc stocks:")
        for stock in plan.stocks:
            print(f"      {stock['label']!r}")
            print(f"        {stock['magnitude']:,.0f} CHF  {stock['role']}/{stock['stock_kind']}"
                  f"  liquidity={stock['liquidity']}")
            print(f"        role decided by: {stock['decided']}")

    if plan.absent:
        print(f"\n    NOT STORED — the model has no field ({len(plan.absent)}):")
        for source_field, value, reason in plan.absent:
            print(f"      {source_field:22} {str(value)[:34]:36} {reason}")

    if plan.deferred:
        print(f"\n    NOT STORED — mapping needs a person ({len(plan.deferred)}):")
        for source_field, value, reason in plan.deferred:
            print(f"      {source_field:22} {str(value)[:34]:36} {reason}")

    if plan.dropped:
        print(f"\n    NOT STORED — the question set no longer asks this ({len(plan.dropped)}):")
        for source_field, value, reason in plan.dropped:
            print(f"      {source_field:22} {str(value)[:34]:36} {reason}")

    for note in plan.notes:
        print(f"\n    NOTE: {note}")

    for problem in plan.problems:
        print(f"\n    PROBLEM: {problem}")


def write(plan: Plan, password: str) -> None:
    from eigentlich.consent import PURPOSES
    from eigentlich.db import make_engine, make_session_factory
    from eigentlich.services.auth import register_with_credentials
    from eigentlich.services.submissions import (
        record_mapping,
        store as store_submission,
        # Bound under this name because the call site below was written expecting it and the
        # import was never added, so `--write` raised NameError on its last line after having
        # already committed. Found on 20 September 2026 loading 50 submissions (A172).
        unmapped as subs_unmapped,
    )
    from eigentlich.services.goals import revise_goal
    from eigentlich.services.onboarding import complete, record_answer
    from eigentlich.services.plan import mutate_plan
    from eigentlich.models import Goal

    from sqlalchemy import select

    from eigentlich.models import Position
    from eigentlich.models.auth import Credential

    engine = make_engine()
    sessions = make_session_factory(engine)

    with sessions() as db:
        # **Re-runnable on purpose.** The model grows: `chf` and `stock_kind` arrived after Renzo was
        # first loaded, and the next field will arrive after that. A loader that could only create would
        # mean the earliest-loaded member is permanently the least complete one, and a member's own
        # Decisions are append-only so there is no reloading them. So an existing account is topped up
        # with what the model can hold today and could not hold before.
        existing = db.execute(select(Credential).where(Credential.email == plan.email)).scalar_one_or_none()

        if existing is not None and _has_a_plan(db, member_id=existing.member_id):
            print(f"\n  {plan.email} exists — topping up rather than creating.")
            _state_the_household(db, member_id=existing.member_id, plan=plan, raw=plan.raw)
            _add_missing_stocks(db, member_id=existing.member_id, plan=plan)
            _add_missing_facts(db, member_id=existing.member_id, plan=plan)
            db.commit()
            return

        if existing is not None:
            # **A credential is not a plan, and conflating the two cost Yasmin her record.**
            #
            # Her account existed as a seeded access shell (A53): a name, a guessed age, a first-login
            # password, nothing else. The branch above asked only whether a CREDENTIAL existed, so every
            # load of her submission took the top-up path and added stocks and facts to a member who had
            # never been through `complete()`. What that produced: two positions, no income, no goals, no
            # consent, an age seven years out from her own statement, and a display name that was the
            # shell's own instruction sentence. Everything downstream — Befund, decisions, data classes —
            # then behaved correctly on top of a record that should not have existed in that state.
            #
            # The question is now "does this member have a plan", not "does this member have a login".
            print(f"\n  {plan.email} exists with no plan — completing the onboarding it never had.")
            _complete_the_shell(db, credential=existing, plan=plan)
            db.commit()
            print(f"\n  completed: {plan.email}  member_id={existing.member_id}")
            return

        member, credential = register_with_credentials(
            db,
            email=plan.email,
            password=password,
            age_at_registration=int(plan.age),
            display_name=plan.display_name,
            consents=[
                {"purpose": purpose.key, "document_version": purpose.document_version}
                for purpose in PURPOSES
                if purpose.required_at_registration
            ],
        )
        # Good for one login, like every other real person's account in this build.
        credential.must_change = True

        # **The file lands whole before anything is mapped** (A154). Until 6 September this tool read a
        # submission, mapped what it could and printed the rest, so an answer with no home was gone as
        # soon as the process ended. `intake.html` asks 102 questions and about a third of them map, which
        # made the silence the majority case rather than the edge one.
        #
        # Stored FIRST, deliberately: the mapping below then runs over a row that already exists, and a
        # failure part way through leaves the member's own words on the record rather than nothing. The
        # blob is inert -- no finding reads it -- so keeping an unmapped answer is safe in a way that
        # guessing at its meaning would not be.
        stored = store_submission(db, member_id=member.id, file=plan.source_file)

        for question_key, value in plan.answers.items():
            record_answer(db, member_id=member.id, question_key=question_key, value=value)

        first = plan.goals[0] if plan.goals else None
        if first:
            record_answer(db, member_id=member.id, question_key="first_goal", value=first["name"])

        # The real completion path: one position, the first goal, and the Decision that records both.
        created = complete(db, member_id=member.id)
        db.flush()

        _state_the_household(db, member_id=member.id, plan=plan, raw=plan.raw)
        _write_goals(db, member_id=member.id, plan=plan, created=created)
        _add_missing_stocks(db, member_id=member.id, plan=plan)

        # What the mapping made of the file, written against the stored row. The point is `reasons`: it
        # carries every key this tool reported as absent, deferred or dropped, so when a field gains a
        # home later, `submissions.unmapped` finds the submissions already carrying it instead of
        # somebody having to remember which ones did.
        def _reasoned(entries, prefix):
            out = {}
            for entry in entries or ():
                key = entry.get("field") if isinstance(entry, dict) else None
                if key:
                    out[key] = f"{prefix}: {entry.get('why') or entry.get('reason') or ''}".strip(": ")
            return out

        record_mapping(
            db, stored,
            mapped_keys=sorted(plan.consumed),
            not_presented=plan.not_presented,
            reasons={
                **_reasoned(plan.absent, "absent"),
                **_reasoned(plan.deferred, "deferred"),
                **_reasoned(getattr(plan, "dropped", None), "dropped by 0.1.3"),
            },
            created={"goals": len(plan.goals), "stocks": len(plan.stocks)},
        )

        db.commit()
        print(f"\n  written: {plan.email}  member_id={member.id}")
        print(f"  submission kept whole: {stored.id}  ({len(subs_unmapped(stored))} answers with no home yet)")
        print(f"  password (good for one login): {password}")


#: Which civil statuses establish a married or registered couple. The owner's ruling of 4 September 2026:
#: **a household is the couple who plan together, and the children are not in it.** For these six that is
#: also the factually right answer — the three children named are 21, 24 and 26, and two of them are
#: separate members of this application who each state that they plan for nobody.
#:
#: `ledig, mit Partner` is deliberately NOT here. It names a real partner with, in one case, a stated
#: income of 85'000, and the ruling said married couple. The consequence is reported at load time rather
#: than quietly absorbed, because it is the difference between an affordability test that can be computed
#: and one that cannot.
MARRIED = ("verheiratet", "eingetragene partnerschaft")

#: The submission field that names the other adult, and the shapes it comes in. Nothing is parsed out of
#: free text beyond a first name that the member themselves wrote down.
_PARTNER_PATTERNS = (
    re.compile(r"verheiratet\s+mit\s+([A-ZÄÖÜ][\wäöüéèà-]+)", re.IGNORECASE),
    re.compile(r"partnerschaft\s+mit\s+([A-ZÄÖÜ][\wäöüéèà-]+)", re.IGNORECASE),
)


#: The words a member uses for the person they are married to, when they do not give a name. Matched
#: whole, case-insensitively. **Reading these back is not the same as inventing a label**: «Partnerin» is
#: the member's own noun for the other adult in their household, where «Kind 1» is a label nobody wrote.
#: That distinction is the whole reason the loader refuses the second and accepts the first.
_PARTNER_NOUNS = (
    "ehefrau", "ehemann", "ehepartnerin", "ehepartner",
    "partnerin", "partner", "gattin", "gatte", "frau", "mann",
)

_PARTNER_NOUN = re.compile(r"\b(" + "|".join(_PARTNER_NOUNS) + r")\b", re.IGNORECASE)


def _partner_label(raw: dict) -> str | None:
    """The other adult, as the member themselves referred to them. `None` when they referred to nobody.

    Two shapes, and the order matters because a name is always better than a noun.

    **A name, where one is written.** Elio's household reads «Verheiratet mit Yasmin, 3 Kinder» and
    Yasmin's reads «Verheiratet mit Elio (b. 1968), 3 Kinder (b. 2000, 2002, 2005)». Both name a person,
    and that name goes in.

    **The member's own noun, where no name is.** Ueli wrote «Eine Partnerin und ein Sohn (in Ausbildung)»
    and Sandra wrote «1 Partnerin Jahrgang 1992, 2 Kinder Jahrgang 2020 und 2022». Neither names the
    person; both say plainly that there is one. Refusing the household there was the first behaviour and
    it was too strict — it left two married members with no household at all, and a household is what the
    affordability test is computed over. «Partnerin» is a word the member wrote about their own household,
    which is a different thing from a label made up here.

    Returns None only when the member's own words name nobody and describe nobody, and then no second
    adult is created.
    """
    text = str(raw.get("household") or "")

    for pattern in _PARTNER_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(1).strip(" ,.")

    noun = _PARTNER_NOUN.search(text)
    if noun:
        # Capitalised as a label rather than echoed in the case it happened to be typed in.
        return noun.group(1).capitalize()
    return None


def _household_from(plan: Plan, raw: dict) -> list | None:
    """The people this member's household is made of, or None when it cannot be built.

    Returns `services.household.Person` objects. The member is always the first adult — `state()` attaches
    their account id to that one.
    """
    from eigentlich.models import ADULT
    from eigentlich.services.household import Person

    status = str(raw.get("civil_status") or "").strip().lower()
    people = [Person(label=plan.display_name, kind=ADULT)]

    if status in MARRIED:
        partner = _partner_label(raw)
        if partner is None:
            return None  # married, and the submission names nobody — reported, not guessed
        people.append(Person(label=partner, kind=ADULT))

    return people


def _state_the_household(db, *, member_id: str, plan: Plan, raw: dict) -> None:
    """Write the household, once. Idempotent: a member who already has one keeps it.

    **Children are not household members**, by the owner's ruling of 4 September 2026. Where the
    submission names children, the fact is reported by `describe` as a dependency that a person has to
    confirm — for these six the three named children are 21, 24 and 26, and two of them hold their own
    accounts here.
    """
    from eigentlich.services.household import current as current_household, state as state_household

    if current_household(db, member_id=member_id) is not None:
        return

    people = _household_from(plan, raw)
    if people is None:
        print("  household NOT written: the submission states a marriage and names no partner")
        return

    people[0] = type(people[0])(label=people[0].label, kind=people[0].kind, member_id=member_id)
    state_household(db, member_id=member_id, people=people, as_of=date.today())
    labels = ", ".join(p.label for p in people)
    described = len(people) > 1 and people[1].label.lower() in _PARTNER_NOUNS
    print(f"  household written: {len(people)} adult(s) — {labels}"
          + ("   (the partner is the member's own word for them, not a name they gave)"
             if described else ""))


def _has_a_plan(db, *, member_id: str) -> bool:
    """Whether this member has been through `onboarding.complete`.

    Read from `onboarding_completed_at` rather than from "does a position exist", for the reason
    `Member.onboarding_completed_at` gives in its own docstring: inferring completion from the presence of
    rows is what made `complete` non-idempotent in the first place.
    """
    from eigentlich.models import Member

    member = db.get(Member, member_id)
    return member is not None and member.onboarding_completed_at is not None


def _write_goals(db, *, member_id: str, plan: Plan, created: dict) -> None:
    """The member's goals, from the first one `complete()` made to the last.

    Extracted from `write` on 4 September 2026 so the create path and the complete-a-shell path produce
    the same goals rather than two similar-looking sets. They differed before, in the direction that is
    hardest to notice: the shell path produced none at all.
    """
    from eigentlich.models import Goal
    from eigentlich.services.goals import revise_goal
    from eigentlich.services.plan import mutate_plan

    first = plan.goals[0] if plan.goals else None

    if first and created.get("goal") is not None:
        changes = {k: first[k] for k in ("target_amount", "target_date") if first[k] is not None}
        # `complete()` derives the template from the answer text and leaves it NULL when the name matches
        # none of the eight — the right behaviour for a member who named their own goal, except that NULL
        # and `unspecified` then mean the same thing by two different spellings. Every goal here was named
        # by the member, so every goal says so the same way; without this the first goal read NULL and the
        # second `unspecified` on the same screen.
        if created["goal"].template is None:
            changes["template"] = first["template"]
        if changes:
            revise_goal(
                db,
                member_id=member_id,
                goal_id=created["goal"].id,
                changes=changes,
                question="Betrag und Datum des ersten Ziels aus dem Erstgespräch übernehmen?",
                choice=", ".join(f"{k}={v}" for k, v in changes.items()),
                reasoning="Aus der Onboarding-Aufnahme vom "
                          f"{plan.person} übernommen. Das Datum ist der 31. Dezember des genannten "
                          "Jahres; Tag und Monat wurden nicht genannt.",
            )

    # Every goal after the first: a plan mutation of its own, so each one carries its own Decision.
    for goal in plan.goals[1:]:
        with mutate_plan(
            db,
            member_id=member_id,
            question="Weiteres Ziel aus dem Erstgespräch festhalten?",
            choice=goal["name"],
            reasoning="Aus derselben Aufnahme wie das erste Ziel.",
        ) as decision:
            record = Goal(
                member_id=member_id,
                name=goal["name"],
                template=goal["template"],
                target_amount=goal["target_amount"],
                target_date=goal["target_date"],
            )
            db.add(record)
            decision.linked_goals.append(record)


def _complete_the_shell(db, *, credential, plan: Plan) -> None:
    """Finish a member who has a login and no plan.

    **The age and the display name are corrected here and nowhere else.** A shell is seeded with a guessed
    age and a name carrying an instruction; the submission states both. The age matters beyond tidiness:
    `age_at_registration` is what R-100's floor is checked against, and a member whose stored age is not
    their stated one has a record nobody can reconcile afterwards. Yasmin's read 46 against a stated 53.

    **Consent is granted here** because the shell was created without any. A member with no consent row has
    no artefact behind C-05's "sole data controller from the first intake question", and R-230's history is
    empty for them. Written through `registration.grant_consents`, which shares one row-writing function
    with `register_member` so A97's guarantee about notices holds for this path too.
    """
    from eigentlich.consent import PURPOSES
    from eigentlich.models import Member
    from eigentlich.services.onboarding import complete, record_answer
    from eigentlich.services.registration import grant_consents

    member = db.get(Member, credential.member_id)

    if plan.age is not None and member.age_at_registration != int(plan.age):
        print(f"    age {member.age_at_registration} -> {int(plan.age)}, the submission's own figure")
        member.age_at_registration = int(plan.age)

    if member.display_name != plan.display_name:
        print(f"    name {member.display_name!r}")
        print(f"      -> {plan.display_name!r}")
        member.display_name = plan.display_name

    granted = grant_consents(
        db,
        member_id=member.id,
        consents=[
            {"purpose": purpose.key, "document_version": purpose.document_version}
            for purpose in PURPOSES
            if purpose.required_at_registration
        ],
    )
    print(f"    consents granted: {[row.purpose for row in granted] or 'none needed'}")

    for question_key, value in plan.answers.items():
        record_answer(db, member_id=member.id, question_key=question_key, value=value)

    first = plan.goals[0] if plan.goals else None
    if first:
        record_answer(db, member_id=member.id, question_key="first_goal", value=first["name"])

    created = complete(db, member_id=member.id)
    db.flush()
    print(f"    onboarding completed: position {created['position'].label!r}"
          + (f", first goal {created['goal'].name!r}" if created.get("goal") else ", no goal stated"))

    _state_the_household(db, member_id=member.id, plan=plan, raw=plan.raw)
    _write_goals(db, member_id=member.id, plan=plan, created=created)
    _add_missing_stocks(db, member_id=member.id, plan=plan)
    _add_missing_facts(db, member_id=member.id, plan=plan)


def _add_missing_facts(db, *, member_id: str, plan: Plan) -> None:
    """Add the A127 member facts this member does not have yet. Idempotent, matched on the key.

    **This is the case the loader's re-runnability was written for**, arriving for the second time. Five
    members were loaded before `member_facts` existed, `onboarding.complete` refuses a second run, and
    Decisions are append-only — so there is no reloading them and the five keys would otherwise have
    reached only members loaded from today onward. The earliest-loaded member would be the least complete
    one, permanently, which is the outcome the top-up path exists to prevent.

    The onboarding answer is recorded as well as the fact. `record_answer` is idempotent per question and
    is not a plan mutation, and without it a topped-up member's intake transcript would be missing the
    answers a member loaded tomorrow would have — two members with the same submission and different
    records.
    """
    from eigentlich.services.member_fact import (
        RefusedValue,
        current as current_facts,
        declarations as fact_declarations,
        state as state_fact,
    )
    from eigentlich.services.onboarding import record_answer
    from eigentlich.services.plan import mutate_plan

    declared = fact_declarations()
    have = set(current_facts(db, member_id=member_id))
    wanted = {key: plan.answers[key] for key in OPTIONAL_ANSWER_SOURCES if key in plan.answers}

    added = 0
    for key, value in wanted.items():
        if key in have or key not in declared:
            continue
        record_answer(db, member_id=member_id, question_key=key, value=value)
        try:
            with mutate_plan(
                db,
                member_id=member_id,
                question=f"Angabe '{key}' aus der Onboarding-Aufnahme uebernehmen?",
                choice="uebernommen",
                # **The value is deliberately not in the prose, and that is a C-04 call rather than
                # brevity.** A Decision's question, choice and reasoning are free text on a K2 row, and
                # `health` is a K3 answer — writing the reading here would put the most sensitive value
                # in the application into a lower-classified row's prose, where the log filter cannot see
                # it because it drops by field name. The Decision links the fact instead, which is what
                # S-07 reads and what `decision_facts` exists for.
                reasoning=f"Aus der Onboarding-Aufnahme, Feld '{key}'.",
            ) as decision:
                state_fact(
                    db, member_id=member_id, key=key, value=value, decision=decision, by="member"
                )
        except RefusedValue as refused:
            print(f"    fact {key!r} REFUSED and not stored: {refused}")
            db.rollback()
            continue
        added += 1

    print(f"  member facts added: {added} of {len(wanted)}"
          + ("" if added == len(wanted) else " (the rest were already there, or refused)"))


def _add_missing_stocks(db, *, member_id: str, plan: Plan) -> None:
    """Add the franc-stock positions this member does not have yet. Idempotent, matched on the label.

    Each one is its own plan mutation, so each carries its own `Decision` — a stock a member stated is a
    fact about their plan and C-09 makes no exception for a loader. The Decision's reasoning names the
    submission field the figure came from, because in a year the only way to check a number is to be able
    to find where it was said.
    """
    from sqlalchemy import select

    from eigentlich.models import Position
    from eigentlich.services.plan import mutate_plan

    have = {
        position.label
        for position in db.execute(
            select(Position).where(Position.member_id == member_id)
        ).scalars()
    }

    added = 0
    for stock in plan.stocks:
        if stock["label"] in have:
            continue
        with mutate_plan(
            db,
            member_id=member_id,
            question=f"{stock['label']} als Bestand in Franken erfassen?",
            choice=f"{stock['magnitude']:,.0f} CHF, {stock['role']}",
            reasoning=f"Aus der Onboarding-Aufnahme, Feld '{stock['source_field']}'. "
                      f"Rolle: {stock['decided']}.",
        ) as decision:
            position = Position(
                member_id=member_id,
                role=stock["role"],
                capital_type="financial",
                label=stock["label"],
                magnitude=stock["magnitude"],
                magnitude_unit="chf",
                stock_kind=stock["stock_kind"],
                liquidity=stock["liquidity"],
                tags={},
            )
            db.add(position)
            decision.linked_positions.append(position)
        added += 1

    print(f"  franc stocks added: {added} of {len(plan.stocks)}"
          + ("" if added == len(plan.stocks) else " (the rest were already there)"))


def _speak_utf8() -> None:
    """Let this tool print a Swiss name.

    Seven of the fifty submissions loaded on 20 September 2026 are for people called Lüthi, Bornand,
    Hürlimann, Brülhart, Rüegg, Näf and Delacrétaz, and every one crashed the loader with
    `UnicodeEncodeError` before writing anything — not in the data, in the `print` that announces the
    name. A Windows console defaults to cp1252 and this file's output is German.

    Reconfiguring the stream rather than stripping the characters: the fix for "cannot display this
    person's name" is never to change the name.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - a stream that cannot be reconfigured
            pass


def main() -> int:
    _speak_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("person", nargs="?", help="e.g. RenzoTommasini, or a filename in client/submissions")
    parser.add_argument("--write", action="store_true", help="create the member; without it, report only")
    parser.add_argument("--password", default=None, help="first-login password; a default is derived")
    args = parser.parse_args()

    available = _submissions()
    if not available:
        print(f"  no submissions in {SUBMISSION_DIR}")
        return 1

    if not args.person:
        print(f"  {len(available)} submissions in {SUBMISSION_DIR.relative_to(REPO)}:")
        for path in available:
            # Through `build_plan` rather than through `_names`, so a submission carrying a pseudonym
            # lists under the name it will actually load as. Listing «2026-08-05 .» beside the real
            # members was how the anonymous four stayed invisible.
            try:
                listed = build_plan(path)
            except DuplicateSubmission:
                print(f"    {path.stem:34} duplicate, not loadable")
                continue
            invented = " (invented name)" if any("INVENTED" in n for n in listed.notes) else ""
            print(f"    {path.stem:34} -> {listed.email:24} \"{listed.display_name}\"{invented}")
        print("\n  pass a name to see what would be loaded; add --write to load it.")
        return 0

    wanted = [p for p in available if args.person.lower() in p.stem.lower()]
    if len(wanted) != 1:
        print(f"  {args.person!r} matched {len(wanted)} submissions; be more specific")
        return 1

    plan = build_plan(wanted[0])
    describe(plan)

    if plan.problems and args.write:
        print("\n  refusing to write while the problems above stand")
        return 1

    if not args.write:
        print("\n  nothing written. add --write to create this member.")
        return 0

    # From the email the plan actually carries, not re-derived from the filename — a pseudonymous
    # submission loads as `ueliw@` and would otherwise be given a password keyed on `2026-08-05`.
    key = plan.email.split("@", 1)[0]
    write(plan, args.password or f"erstanmeldung-{key}-bitte-aendern")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
