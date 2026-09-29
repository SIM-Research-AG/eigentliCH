"""The three person-scoped capitals, from what the member actually said.

`E` expertise, `N` network, `H` health — the trio `HouseholdPosition` has carried since the Life Balance
Sheet was wired in, and that nothing has ever read. They arrive here from the intake rather than from a
state block someone filled in by hand, and every one of them comes back with its provenance.

**The three are not equally derivable, and this module refuses to pretend otherwise.**

    H   read directly. The intake question already asks for the number the engine wants — checked
        against all ten members on 6 September 2026 and matched every one.
    N   **computed by `services/identities.net_scale`**, which has always computed it. This module
        adds one thing the owner asked for and nothing else: a reach multiplier on the people count.
    E   derived from the BFS Lohnstrukturerhebung's own education categories. Each rung is the value
        that makes the engine reproduce that qualification's published median wage.

**E was ABSENT here until the BFS source landed, and the reason it stopped being absent is worth
keeping.** Nothing about the method changed — a free-text education answer still cannot be mapped, and
fitting the six hand-scored members against their own text still produces no rule. What changed is that
there is now a published median behind every rung, so the ladder is quoted instead of judged. The five
categories are the BFS's verbatim; a member whose answer has no published median is ABSENT rather than
placed on a neighbouring rung.

**And the calibration found the real gap.** The engine's shipped `earning_power_at_unit` of 0.75 puts a
person at E = N = 1 on 9'372 francs a month; the BFS median for a university graduate *without a
management function* is 8'645. The engine was already calibrated to the non-Kader population and nobody
knew. What was missing was never expertise — it was **responsibility**, which the BFS table shows moves
a wage more than the qualification does, and which is why three real members could not be reached at
any E and N.

An absent capital is dropped along with its weight and is never scored zero (A110). A person whose
expertise nobody has recorded is not a person without expertise, and the difference decides whether this
tells someone the truth or an insult.

**Two expertise numbers exist and they are not the same quantity.** `identities.expertise_scale` scores
commitment to learning over published credits and is a frozen port of the original prototype, tested
against its reference cases; it produced the values stored for five members. `expertise` here scores
qualification level against published median wages, which is why it is what reaches `earning_power`.
Neither may be turned into the other, and only this module reaches the engine.

**`health` is K3 and now drives a financial number.** That is permitted, on one condition the record
states and this module enforces by shape: every consumer must survive H's removal. `capitals()` returns
`H=None` under a K3 filter or after erasure, and the direction of the resulting error is named rather
than hoped for — without H the income equation loses its efficiency multiplier and OVERSTATES earning
power, which surfaces as an unmet goal rather than as false reassurance.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..content import _load

#: The Life Balance Sheet engine is a separate programme in the same repository, not a dependency of
#: this package. It is reached by path rather than installed, the way `desktop/allocation.py` reaches
#: the Optimiser — the difference being that this one needs only numpy, so it can be imported in
#: process instead of shelled out to its own interpreter.
#:
#: **Resolved once, and a failure here is not an error.** `earning_power` returns None when the engine
#: is absent, because a build without it should still compute the three capitals.
_ENGINE_ROOT = Path(__file__).resolve().parents[4] / "engines" / "Life_Balance_Sheet"


def _engine():
    """`(earning_power, Params)` from the engine, or `(None, None)` if it is not reachable."""
    if str(_ENGINE_ROOT) not in sys.path and _ENGINE_ROOT.exists():
        sys.path.append(str(_ENGINE_ROOT))
    try:
        from personal_alm.model.dynamics import earning_power as engine_earning_power
        from personal_alm.model.params import Params
    except ImportError:
        return None, None
    return engine_earning_power, Params

#: Where a value came from. Same vocabulary as `profile_inputs`, on purpose — a reader should not have to
#: learn two provenance schemes to read one member.
FROM_SUBMISSION = "submission"
FROM_PLAN = "plan"
FROM_CURATOR = "curator"
ABSENT = "absent"

#: Why a capital is absent. `NOT_ASKED` and `NOT_ANSWERED` are different failures with different fixes:
#: one is ours and one is the member's.
NOT_ASKED = "the intake does not ask a question this could be derived from"
NOT_ANSWERED = "the question was asked and left blank"
WITHHELD = "K3 data was filtered or erased"


class HumanCapitalNotApproved(Exception):
    """The human-capital record carries no owner's name, so no capital may be computed from it."""


def _record() -> dict:
    return _load("human-capital")


def parameters() -> dict:
    """The approved record, or a refusal.

    Same gate as `risk_profile.parameters`, and for the same reason: the network scale was recovered by
    fitting six hand-set values, the mandate weight rests on one member, and the expertise ladder
    describes a question that does not exist. None of that may reach a member unsigned.
    """
    record = _record()
    about = record["_about"]
    if about.get("provisional", True):
        raise HumanCapitalNotApproved(
            "client/content/human-capital.json is marked provisional and carries no publisher. Every "
            "figure in it is either a published median or a stated judgement of this house, and the "
            "second kind may not be applied to a member unsigned. Its own `_for_review` names what is "
            "outstanding."
        )
    if not about.get("published_by"):
        raise HumanCapitalNotApproved("human-capital.json is not provisional and names no `published_by`.")
    return record


# ============================================================ the shapes


@dataclass(frozen=True)
class Capital:
    """One capital, its provenance, and what it was computed from."""

    key: str
    value: float | None
    source: str
    #: The inputs that produced it, for a reader who wants to check the arithmetic.
    inputs: dict = field(default_factory=dict)
    #: Present only when `value` is None. Says which kind of absence this is.
    absent_because: str | None = None
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Capitals:
    """E, N and H together, plus what a caller must know to use them honestly."""

    E: Capital
    N: Capital
    H: Capital
    caveats: list = field(default_factory=list)

    def as_kwargs(self) -> dict:
        """Exactly what `HouseholdPosition` and `DerivationInputs` take."""
        return {"E": self.E.value, "N": self.N.value, "H": self.H.value}

    @property
    def missing(self) -> list:
        return [c.key for c in (self.E, self.N, self.H) if not c.known]

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class TimeBudget:
    """The four shares and the residual, in hours a week and as fractions of the productive week."""

    productive_week_hours: float
    tau_Y: float | None = None
    tau_E: float | None = None
    tau_N: float | None = None
    tau_H: float | None = None
    sources: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)

    @property
    def leisure(self) -> float | None:
        """The residual. `None` where any share is unknown — a residual computed over holes is a lie."""
        shares = (self.tau_Y, self.tau_E, self.tau_N, self.tau_H)
        if any(s is None for s in shares):
            return None
        return 1 - sum(shares)

    def hours(self, share: float | None) -> float | None:
        return None if share is None else share * self.productive_week_hours


# ============================================================ the three capitals


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(str(value).replace("'", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def expertise(answers: dict, *, record: dict | None = None) -> Capital:
    """E — from the BFS education category, whose published median the rung reproduces.

    A free-text education answer is still not readable by a mapping, so `education` alone returns ABSENT
    with `NOT_ASKED`. What closes it is `qualification_highest`, and the five options are the BFS
    categories verbatim so that every one has a median behind it.
    """
    record = record or _record()
    section = record["expertise"]
    anchors = section["anchors"]

    level = (answers.get("qualification_highest") or "").strip() or None
    if level is None:
        return Capital(
            key="E", value=None, source=ABSENT, absent_because=NOT_ASKED,
            inputs={"education": answers.get("education")},
            note=("Education was given as free text, which a reader can judge and a mapping cannot. "
                  "`expertise.intake_question` in the record is the structured question that closes it."),
        )

    by_level = anchors["by_qualification"]
    if level not in by_level:
        return Capital(key="E", value=None, source=ABSENT, absent_because=NOT_ANSWERED,
                       inputs={"qualification_highest": level},
                       note=(f"{level!r} has no published median in the BFS table, so it is not a rung. "
                             f"Placing it on a neighbouring one would be the guessing the source removed."))

    base = float(by_level[level])
    inputs = {"qualification_highest": level, "base": base}

    # -- recency. Training under way clears it: that is the whole reason the question is asked.
    recency = anchors["recency"]
    penalty = 0
    ongoing = (answers.get("education_recent") or "").strip().lower()
    has_ongoing = bool(ongoing) and ongoing not in ("nein", "no", "keine", "none", "-")
    year = _number(answers.get("qualification_year"))
    today_year = _number(answers.get("_today_year")) or 2026
    if has_ongoing:
        inputs["recency_cleared_by"] = answers.get("education_recent")
    elif year is not None:
        elapsed = max(0, today_year - year)
        over = max(0, elapsed - float(recency["full_value_within_years"]))
        penalty = min(float(recency["maximum_penalty"]), over * float(recency["penalty_per_year_after"]))
        inputs["years_since_qualification"] = elapsed
        inputs["recency_penalty"] = penalty

    # -- experience, saturating on the same argument as the network scale.
    experience = anchors["experience"]
    addition = 0
    years = _number(answers.get("years_in_field"))
    if years is not None:
        scale = float(experience["scale_years"])
        addition = float(experience["maximum_addition"]) * (1 - math.exp(-max(0, years) / scale))
        inputs["years_in_field"] = years
        inputs["experience_addition"] = addition

    value = base - penalty + addition
    value = min(float(anchors["ceiling"]), max(float(anchors["floor"]), value))
    return Capital(key="E", value=value, source=FROM_SUBMISSION, inputs=inputs)


def network(answers: dict, *, record: dict | None = None) -> Capital:
    """N — from the people a member would be recommended by, and the mandates they hold.

    The formula is recovered rather than designed. Four members' hand-set values agree on a scale of eight
    people to within a third of a person; the fifth is the only one carrying mandates and determines the
    mandate weight entirely, which is why the record calls that figure a guess wearing a decimal point.
    """
    record = record or _record()
    section = record["network"]

    people = _number(answers.get("network_people"))
    mandates = _number(answers.get("mandates"))
    if people is None and mandates is None:
        return Capital(key="N", value=None, source=ABSENT, absent_because=NOT_ANSWERED,
                       note="Neither the number of people nor the number of mandates was given.")

    # -- reach. **Unanswered means 1.0, and that is load-bearing**: `net_scale` has always received the
    # bare count, so a member who does not answer the new question keeps precisely the N the application
    # already gave them. The multiplier only ever lifts.
    reach_section = section.get("reach") or {}
    multipliers = reach_section.get("multipliers") or {}
    stated_reach = (answers.get("network_reach") or "").strip() or None
    reach = float(multipliers.get(stated_reach, reach_section.get("default_when_unanswered", 1)))

    # **The convention is `identities`', not this module's.** A scale of 8 people and mandates worth 0.06
    # each to a ceiling of 0.18 are published in `intake-scales.json` with their own reasoning. Computing
    # them a second time here is what this module did until 6 September 2026, and it got the mandates
    # wrong -- see `network.correction` in the record.
    from . import identities

    effective_people = (people or 0) * reach
    value = identities.net_scale(effective_people, mandates)
    if value is None:  # pragma: no cover - guarded by the check above
        return Capital(key="N", value=None, source=ABSENT, absent_because=NOT_ANSWERED)

    inputs = {"network_people": people, "mandates": mandates, "network_reach": stated_reach,
              "reach_multiplier": reach, "effective_people": effective_people,
              "computed_by": "services/identities.net_scale"}
    notes = []
    if people is None:
        notes.append("Only mandates were given, so this rests entirely on the published mandate credit "
                     "of 0.06 each.")
    if stated_reach is None:
        notes.append("Reach was not stated, so the count is read at face value — which under-reads a "
                     "senior specialist who names few but far-reaching contacts.")
    elif stated_reach not in multipliers:
        notes.append(f"{stated_reach!r} is not a published reach, so the count is read at face value.")
    return Capital(key="N", value=value, source=FROM_SUBMISSION, inputs=inputs,
                   note=" ".join(notes) or None)


def health(answers: dict, *, record: dict | None = None, k3_permitted: bool = True) -> Capital:
    """H — read directly, because the question already asks for the number the engine wants.

    **`k3_permitted=False` is the erasure and filter path and it is not an error case.** It returns
    `None` with `WITHHELD`, and the caller is required to survive that. See the record's `health.k3`.
    """
    record = record or _record()
    section = record["health"]

    if not k3_permitted:
        return Capital(key="H", value=None, source=ABSENT, absent_because=WITHHELD,
                       note=("`health` is K3. Without it the income equation loses its efficiency "
                             "multiplier and reports earning power at full health, which OVERSTATES "
                             "income rather than understating it."))

    stated = answers.get("health")
    if stated is None or str(stated).strip() == "":
        return Capital(key="H", value=None, source=ABSENT, absent_because=NOT_ANSWERED)

    key = str(stated).strip()
    levels = section["levels"]
    if key in levels:
        return Capital(key="H", value=float(levels[key]), source=FROM_SUBMISSION,
                       inputs={"health": key})
    number = _number(stated)
    if number is not None and 0 <= number <= 1:
        return Capital(key="H", value=number, source=FROM_SUBMISSION,
                       inputs={"health": key}, note="Read as a bare number; not a published option.")
    return Capital(key="H", value=None, source=ABSENT, absent_because=NOT_ANSWERED,
                   inputs={"health": key}, note=f"{key!r} is not a published level.")


def capitals(answers: dict, *, record: dict | None = None, k3_permitted: bool = True) -> Capitals:
    """All three, with the caveats a caller has to carry."""
    record = record or _record()
    E = expertise(answers, record=record)
    N = network(answers, record=record)
    H = health(answers, record=record, k3_permitted=k3_permitted)

    caveats = []
    if not E.known:
        caveats.append("expertise is unknown, so earning power rests on the network alone")
    if not N.known:
        caveats.append("the network is unknown")
    if not H.known and H.absent_because == WITHHELD:
        caveats.append("health was withheld as K3 data; earning power is reported at full health "
                       "and is therefore overstated")
    elif not H.known:
        caveats.append("health is unknown; earning power is reported at full health and is overstated")
    return Capitals(E=E, N=N, H=H, caveats=caveats)


# ============================================================ earning power


@dataclass(frozen=True)
class EarningPower:
    """What the calibrated engine says a person could earn, and at what working time."""

    #: The engine's own quantity: annual income at `tau_Y = 1`, a 100-hour week nobody works.
    at_full_productive_week: float
    #: The same thing at the BFS convention, which is what a reader can recognise.
    annual_at_forty_hours: float
    monthly_standardised: float
    #: The tier applied, and what it multiplied.
    responsibility: str
    multiplier: float
    before_responsibility: float
    inputs: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)


def responsibility_multiplier(answers: dict, *, qualification: str | None = None,
                              record: dict | None = None) -> tuple:
    """The Kaderfunktion tier and its multiplier. Returns `(label, multiplier, note)`.

    **The dimension the model was missing.** At the same education the BFS step from no management
    function to upper or middle Kader is 5'764 francs a month, against 2'483 for the whole distance from
    EFZ to university. Unanswered means no management function, which is the modest reading.

    **The two upper tiers read different columns of the source, because the source is shaped that way.**
    Upper and middle Kader is published per education, so the multiplier comes from the qualification.
    Top management is published per SECTOR and not per education, so it comes from `sector` — a factor
    of six separates Gastronomie from Banken, and a single whole-economy figure hid that entirely.
    """
    record = record or _record()
    tiers = record["responsibility"]["tiers"]
    stated = (answers.get("kader") or "").strip()

    sector = (answers.get("sector") or "").strip() or None

    for key, tier in tiers.items():
        labels = {key} | {str(v) for v in (tier.get("label") or {}).values()}
        if not stated or stated not in labels:
            continue

        # -- upper and middle Kader: one multiplier per qualification, because the table gives one.
        if "multiplier_by_qualification" in tier:
            by_qual = tier["multiplier_by_qualification"]
            if qualification in by_qual:
                return key, float(by_qual[qualification]), None
            mean = sum(float(v) for v in by_qual.values()) / len(by_qual)
            return key, mean, ("no qualification was given, so the mean of the published multipliers "
                               "was used rather than the one for this education")

        # -- top management: one multiplier per SECTOR, because between Gastronomie and Banken lies a
        # factor of six and the whole-economy figure is close to meaningless.
        by_sector = tier.get("multiplier_by_sector") or {}
        if by_sector:
            if sector in by_sector:
                note = None
                if qualification and qualification != "Universitäre Hochschule":
                    note = tier.get("extrapolation_named")
                return key, float(by_sector[sector]), note
            reason = ("no sector was given" if sector is None
                      else f"{sector!r} has no published figure")
            return key, float(tier["multiplier"]), (
                f"{reason}, so the whole-economy figure was used — and it is not a middle value: it "
                f"sits next to Maschinenbau and far below banking, pharma and insurance")
        return key, float(tier["multiplier"]), tier.get("warning")

    return ("ohne Kaderfunktion", 1,
            None if not stated else f"{stated!r} is not a published tier; no uplift was applied")


def earning_power(answers: dict, *, record: dict | None = None, age: float | None = None,
                  k3_permitted: bool = True) -> EarningPower | None:
    """Annual earning power, from the calibrated engine, or `None` where a capital is missing.

    **The engine is called, not reimplemented.** `personal_alm.model.dynamics.earning_power` does the
    arithmetic; this supplies the calibrated `earning_power_at_unit` the record derived from the BFS
    table, and applies the responsibility tier the engine has no input for.

    Returns `None` rather than a guess when E or N is unknown. Health is different: it multiplies income
    rather than earning power, so its absence is a caveat here and not a refusal.
    """
    record = record or _record()
    caps = capitals(answers, record=record, k3_permitted=k3_permitted)
    if not caps.E.known or not caps.N.known:
        return None

    engine_earning_power, Params = _engine()
    if engine_earning_power is None:  # pragma: no cover - the engine is a separate programme
        return None

    calibration = record["earning_power"]["calibration"]
    params = Params(earning_power_at_unit=float(calibration["earning_power_at_unit"]))
    years = age if age is not None else _number(answers.get("age"))
    if years is None:
        return None

    base = float(engine_earning_power(caps.E.value, caps.N.value, float(years), params))
    qualification = (answers.get("qualification_highest") or "").strip() or None
    tier, multiplier, tier_note = responsibility_multiplier(
        answers, qualification=qualification, record=record)
    full = base * multiplier

    working = record["earning_power"]["working_time"]
    factor = float(working["factor"])
    caveats = list(caps.caveats)
    if tier_note:
        caveats.append(tier_note)
    if not answers.get("kader"):
        caveats.append("no management function was stated, so none was assumed — the BFS table shows "
                       "that is worth more than the qualification")

    return EarningPower(
        at_full_productive_week=full,
        annual_at_forty_hours=full * (float(working["bfs_full_time_hours_per_week"])
                                      / float(working["model_productive_week_hours"])),
        monthly_standardised=full / factor,
        responsibility=tier, multiplier=multiplier, before_responsibility=base,
        inputs={"E": caps.E.value, "N": caps.N.value, "age": years,
                "qualification_highest": qualification,
                "earning_power_at_unit": params.earning_power_at_unit},
        caveats=caveats,
    )


# ============================================================ the time budget


def _band_hours(value, record: dict) -> float | None:
    bands = record["rest_hours_bands"]
    key = str(value or "").strip()
    if key in bands and not key.startswith("_"):
        return float(bands[key])
    return _number(value)


def time_budget(answers: dict, *, record: dict | None = None) -> TimeBudget:
    """The four shares, and an honest account of the two that have no question behind them.

    All four are asked now. Where one is unanswered it comes back `None` rather than as a residual,
    because splitting the leftover between learning and networking would invent the one number the whole
    time-budget model turns on.
    """
    record = record or _record()
    section = record["time"]
    week = float(section["productive_week_hours"])
    sources, caveats = {}, []

    hours = _number(answers.get("hours_per_week"))
    tau_Y = (hours / week) if hours is not None else None
    sources["tau_Y"] = FROM_SUBMISSION if tau_Y is not None else ABSENT

    rest = _band_hours(answers.get("rest_hours"), record)
    tau_H = (rest / week) if rest is not None else None
    sources["tau_H"] = FROM_SUBMISSION if tau_H is not None else ABSENT
    if rest is not None and not _number(answers.get("rest_hours")):
        caveats.append(f"recovery was given as the band {answers.get('rest_hours')!r} and read at "
                       f"{rest:g} hours by the record's convention, not measured")

    # `hours_learning` and `hours_network` were added to the instrument on 6 September 2026 precisely so
    # these two stop being holes. A member who has not answered them yet still gets None — absent is
    # absent — but the questions now exist and this reads them.
    learning = _number(answers.get("hours_learning"))
    tau_E = (learning / week) if learning is not None else None
    sources["tau_E"] = FROM_SUBMISSION if tau_E is not None else ABSENT

    networking = _number(answers.get("hours_network"))
    tau_N = (networking / week) if networking is not None else None
    sources["tau_N"] = FROM_SUBMISSION if tau_N is not None else ABSENT

    unasked = [name for name, value in (("Lernen", tau_E), ("Netzwerk", tau_N)) if value is None]
    if unasked:
        caveats.append(f"no hours were stated for {' and '.join(unasked)}, so the leisure residual "
                       f"cannot be computed")

    bounds = section["bounds"]
    if tau_Y is not None and tau_Y > float(bounds["max_tau_Y"]):
        caveats.append(f"stated working hours are {hours:g} a week, above the model's hard ceiling of "
                       f"{float(bounds['max_tau_Y']) * week:g}")
    if tau_Y is not None and tau_Y > float(section["overwork_threshold"]):
        caveats.append(f"stated working hours are {hours:g} a week, above the {float(section['overwork_threshold']) * week:g}-hour "
                       f"threshold where the model accelerates health decay")
    if tau_H is not None and tau_H < float(bounds["min_tau_H"]):
        caveats.append(f"stated recovery is {rest:g} hours a week, below the model's floor of "
                       f"{float(bounds['min_tau_H']) * week:g}")

    total = sum(share for share in (tau_Y, tau_E, tau_N, tau_H) if share is not None)
    if total > 1:
        caveats.append(f"the stated hours add to {total * week:g} a week, which is more than the "
                       f"{week:g}-hour productive week the model allows")

    return TimeBudget(productive_week_hours=week, tau_Y=tau_Y, tau_E=tau_E, tau_N=tau_N, tau_H=tau_H,
                      sources=sources, caveats=caveats)


__all__ = [
    "ABSENT", "Capital", "Capitals", "EarningPower", "FROM_CURATOR", "FROM_PLAN", "FROM_SUBMISSION",
    "HumanCapitalNotApproved", "NOT_ANSWERED", "NOT_ASKED", "TimeBudget", "WITHHELD",
    "capitals", "earning_power", "expertise", "health", "network", "parameters",
    "responsibility_multiplier", "time_budget",
]
