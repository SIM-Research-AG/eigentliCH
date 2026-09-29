"""One number between 0 and 1 per household, and the mandate parameters it interpolates to.

**Why this exists.** Ten members went through the Optimiser and came back with two portfolios. Not because
the objective is weak — because everything that could distinguish them was held constant: one role-bounds
block for everybody, one universe, one curve slope. This module is what varies.

**The code holds the interpolation and nothing else.** Every number it moves between lives in
`client/content/risk-profile.json`. The owner chose a continuous profile over named bands, and the
objection to continuous is that the reasoning ends up in code — so the answer is that the code contributes
a straight line and no judgement. A reader checks the two anchors; there is nothing else to check.

**Capacity is the primary signal and what the member says only caps it.** The owner reversed the first
draft on 6 September, and the data is why: with the stated figure deciding, it decided nine of ten cases,
and three members who each wrote «10 %» received identical mandates although one had held through a real
fall, one had sold everything and one had never been invested. A number typed in a calm room was
overriding everything known about them.

**Behaviour moves the claim in both directions.** Selling everything caps it; holding through a fall, or
buying more, puts a floor under it. That cuts both ways deliberately: one answer about 2008 or 2022 can
now override what somebody says about themselves today, upward as well as down.

**Nothing computes from an unapproved record.**
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..content import _load

COULD_NOT_BE_DETERMINED = "could_not_be_determined"
BY_WILLINGNESS = "willingness"
BY_CAPACITY = "capacity"
BY_BOTH = "both"


class ProfileNotApproved(Exception):
    """The risk-profile record carries no owner's name, so no profile may be computed from it."""


def _record() -> dict:
    return _load("risk-profile")


def parameters() -> dict:
    """The approved record, or a refusal."""
    record = _record()
    about = record["_about"]
    if about.get("provisional", True):
        raise ProfileNotApproved(
            "client/content/risk-profile.json is marked provisional and carries no publisher. Every "
            "figure in it is a stated judgement of this house rather than a measured or regulatory one, "
            "which is exactly why it may not be applied to a member unsigned. Its own `_for_review` names "
            "four things to settle, and the first — the two anchor bound sets — is the whole of what a "
            "profile means."
        )
    if not about.get("published_by"):
        raise ProfileNotApproved("risk-profile.json is not provisional and names no `published_by`.")
    return record


def _between(value: float, low: dict, high: dict, low_key: str, high_key: str,
             out_low: float, out_high: float) -> float:
    """Straight line between two published points, clamped at both ends."""
    a, b = float(low[low_key]), float(high[high_key])
    if b == a:
        return out_high
    t = (float(value) - a) / (b - a)
    t = min(1, max(0, t))
    return out_low + t * (out_high - out_low)


def lerp(low, high, t: float):
    """Interpolate two published numbers, or two dicts of them, by `t`.

    **Prose passes through untouched.** Every content record in this build annotates its own numbers —
    a `why` beside a bound, an `_about` above a block — and a mapper that tried to interpolate those
    would fail on the first record written in the house style. A key that is not a number or a nested
    dict is carried from `low` unchanged, and a key absent from `high` is carried too: an annotation is
    not data to be blended.
    """
    # **Exact at the ends, deliberately.** `low + (high - low) * 1` is not `high` in floating point --
    # 0.70 + (0.25 - 0.70) came back as 0.25000000000000006 -- and the whole claim this module makes is
    # that a profile of 0 reproduces the cautious anchor and a profile of 1 the aggressive one. An anchor
    # is a number somebody reviewed and signed; it must come back as the number they signed.
    if t <= 0:
        return low
    if t >= 1:
        return high
    if isinstance(low, dict):
        out = {}
        for key, value in low.items():
            if key not in high:
                out[key] = value
            elif isinstance(value, dict) or isinstance(value, (int, float)):
                out[key] = lerp(value, high[key], t)
            else:
                out[key] = value
        return out
    return float(low) + (float(high) - float(low)) * t


# ---------------------------------------------------------------- willingness


@dataclass(frozen=True)
class Willingness:
    """What the member says, and what their behaviour says about the saying."""

    stated_loss: float | None
    crisis_behaviour: str | None
    #: The figure the stated loss alone would give. `None` when nothing was stated.
    from_stated: float | None
    #: The ceiling the crisis answer imposes. Always present — an unanswered crisis question caps too.
    cap: float
    #: The floor demonstrated behaviour puts under the claim. Zero unless the member held or bought more.
    floor: float
    cap_reason: str
    value: float | None
    #: True where the cap decided the figure rather than the stated loss.
    capped: bool
    #: True where the floor did — the member is credited with more than they claimed.
    lifted: bool


def willingness(*, stated_loss: float | None, crisis_behaviour: str | None) -> Willingness:
    """From the two answers the member gave, one of which is about behaviour rather than opinion."""
    record = parameters()["willingness"]
    behaviour = record["crisis_behaviour"]
    caps, floors = behaviour["caps"], behaviour["floors"]

    key = (crisis_behaviour or "").strip() or "_unanswered"
    cap = float(caps.get(key, caps["_unanswered"]))
    # Only two answers are evidence of anything. Never having been invested is not, and neither is
    # leaving the question blank — those cap and do not lift.
    floor = float(floors.get(key, 0))
    reason = ("no crisis behaviour was stated, which is not evidence of composure"
              if key == "_unanswered" else f"stated behaviour: {key}")

    if stated_loss is None:
        # Nothing claimed, so nothing to cap — but demonstrated behaviour still says something.
        return Willingness(None, crisis_behaviour, None, cap, floor, reason,
                           floor or None, False, bool(floor))

    scale = record["from_stated_loss"]
    raw = _between(stated_loss, scale["at_or_below"], scale["at_or_above"],
                   "loss", "loss", float(scale["at_or_below"]["profile"]),
                   float(scale["at_or_above"]["profile"]))
    value = min(max(raw, floor), cap)
    return Willingness(stated_loss, crisis_behaviour, raw, cap, floor, reason,
                       value, cap < raw, floor > raw)


# ---------------------------------------------------------------- capacity


@dataclass(frozen=True)
class Capacity:
    """What the position can absorb, computed rather than asked."""

    #: Per component: the input, the 0..1 value, and its weight.
    components: dict
    value: float | None
    #: Components whose input was absent. Their weight is redistributed over the rest.
    missing: list = field(default_factory=list)


def capacity(*, horizon_years: float | None = None, reserve_months: float | None = None,
             employment: str | None = None, variable_share: float | None = None,
             mandates: int | None = None, free_share: float | None = None,
             debt_service_share: float | None = None) -> Capacity:
    """The weighted mean of five components, each 0 to 1.

    **A missing input drops its component and its weight**, rather than scoring zero. Scoring zero would
    say "this household has no reserve" when what happened is that nobody asked, and it would pull every
    incomplete record toward cautious for a reason that is about the form and not the person.
    """
    spec = parameters()["capacity"]["components"]
    out: dict = {}
    missing: list = []

    def line(name, value, key):
        c = spec[name]
        if value is None:
            missing.append(name)
            return
        v = _between(value, c["at_or_below"], c["at_or_above"], key, key,
                     float(c["at_or_below"]["value"]), float(c["at_or_above"]["value"]))
        out[name] = {"input": value, "value": v, "weight": float(c["weight"])}

    line("horizon", horizon_years, "years")
    line("reserve", reserve_months, "months")
    line("free_share", free_share, "share")
    line("debt_service", debt_service_share, "share")

    stability = spec["income_stability"]
    if employment is None and variable_share is None and mandates is None:
        missing.append("income_stability")
    else:
        base = float(stability["base"].get((employment or "").strip(),
                                           stability["base_unknown"]))
        if variable_share:
            base -= min(1, max(0, float(variable_share))) * float(
                stability["variable_share_subtracts_up_to"])
        if mandates:
            base += min(int(mandates) * float(stability["each_mandate_adds"]),
                        float(stability["mandates_add_at_most"]))
        out["income_stability"] = {
            "input": {"employment": employment, "variable_share": variable_share,
                      "mandates": mandates},
            "value": min(1, max(0, base)),
            "weight": float(stability["weight"]),
        }

    total = sum(c["weight"] for c in out.values())
    value = None if not total else sum(c["value"] * c["weight"] for c in out.values()) / total
    return Capacity(components=out, value=value, missing=missing)


# ---------------------------------------------------------------- the profile


@dataclass(frozen=True)
class Profile:
    """One number, what bound it, and the mandate parameters it produces."""

    willingness: Willingness
    capacity: Capacity
    value: float | None
    binds_on: str | None
    role_bounds: dict | None
    asset_class_bounds: dict | None
    curve_slope: dict | None
    universe_rules: dict | None
    caveats: list = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return COULD_NOT_BE_DETERMINED if self.value is None else "meets"


def profile(*, stated_loss: float | None, crisis_behaviour: str | None, **capacity_inputs) -> Profile:
    """Willingness, capacity, and the lower of the two.

    Where only one side can be computed, that side is the profile and a caveat says so — refusing outright
    would leave a member with the identical block that this module exists to replace, which is worse than
    a profile resting on one leg and saying so.
    """
    record = parameters()
    w = willingness(stated_loss=stated_loss, crisis_behaviour=crisis_behaviour)
    c = capacity(**capacity_inputs)

    caveats: list[str] = []
    if c.missing:
        caveats.append(f"capacity was computed without: {', '.join(sorted(c.missing))}")
    if w.capped:
        caveats.append("stated tolerance was capped by the crisis answer")

    if w.lifted:
        caveats.append("demonstrated behaviour raised the claim above the stated tolerance")

    # **Capacity decides and the claim caps it.** Arithmetically still the lower of the two; what changed
    # is which is the signal and which the restraint — visible in the reporting, and in what happens when
    # one of them is missing.
    both = [x for x in (w.value, c.value) if x is not None]
    if not both:
        return Profile(w, c, None, None, None, None, None, None,
                       caveats + ["neither the position nor a stated tolerance could be read"])

    value = min(both)
    if c.value is None:
        binds, note = BY_WILLINGNESS, (
            "nothing was known of the position, so the stated tolerance alone decides — the case this "
            "design exists to avoid, reported rather than hidden")
    elif w.value is None:
        binds, note = BY_CAPACITY, "no tolerance was stated, so the position decides unrestrained"
    elif w.value == c.value:
        binds, note = BY_BOTH, None
    else:
        binds = BY_WILLINGNESS if w.value < c.value else BY_CAPACITY
        note = None
    if note:
        caveats.append(note)

    anchors = record["anchors"]
    return Profile(
        willingness=w, capacity=c, value=value, binds_on=binds,
        role_bounds=lerp(anchors["role_bounds"]["cautious"],
                         anchors["role_bounds"]["aggressive"], value),
        asset_class_bounds=lerp(anchors["asset_class_bounds"]["cautious"],
                                anchors["asset_class_bounds"]["aggressive"], value),
        curve_slope=lerp(anchors["curve_slope"]["cautious"],
                         anchors["curve_slope"]["aggressive"], value),
        universe_rules=None,
        caveats=caveats,
    )


def reconcile_with_universe(result: Profile, *, roles_available) -> Profile:
    """Zero the floor of any role the universe can no longer supply, and say so.

    **The defect this exists for.** The cautious anchor puts Gain's lower bound at 0.00 and the aggressive
    one at 0.40, so the interpolation gives a POSITIVE Gain floor at any profile above zero — 0.057 at a
    profile of 0.143. The universe rule removes equity below 0.35. Between those two numbers every mandate
    demanded Gain from a universe that had no Gain instrument left in it, because every Gain block in the
    register is an equity.

    The Optimiser caught it and said so in its own notes — *«the mandate sets a role floor on ['Gain'], but
    the universe has no instrument in those categories, so the floor cannot be met»* — then failed to
    converge and reported a fallback solution. Reading `role_allocation` without reading `notes` made that
    look like a considered allocation with no equity in it. It was an infeasible mandate.

    Two numbers in one record disagreeing is not something to paper over in code, so this does the minimum
    that makes the mandate answerable and reports it: a role with nothing to buy has no floor. The
    underlying question — whether an asset class should be removed at all, or only bounded — is the
    record's own first review item.
    """
    if result.role_bounds is None:
        return result
    available = {str(r).strip().lower() for r in roles_available}
    bounds = {role: dict(values) for role, values in result.role_bounds.items()}
    emptied = []
    for role, values in bounds.items():
        if role.lower() not in available and float(values.get("lower") or 0) > 0:
            emptied.append(role)
            values["lower"] = 0
            values["upper"] = 0
    if not emptied:
        return result
    return Profile(
        willingness=result.willingness, capacity=result.capacity, value=result.value,
        binds_on=result.binds_on, role_bounds=bounds,
        asset_class_bounds=result.asset_class_bounds, curve_slope=result.curve_slope,
        universe_rules=result.universe_rules,
        caveats=list(result.caveats) + [
            f"the universe has no instrument for {', '.join(sorted(emptied))}, so that role's floor was "
            f"set to zero rather than demanding weight nothing could supply"
        ],
    )


def admits(result: Profile, *, asset_class: str) -> bool:
    """Always true where a profile exists. **The profile no longer removes anything from the universe.**

    Kept as a function rather than deleted, because callers ask the question and the answer is worth
    stating once with its reason: removing an asset class emptied the Gain role while that role's own
    floor still demanded weight from it, the mandate became infeasible, and the fallback solution read
    like a considered allocation (A157). A ceiling of zero can never do that.

    So a cautious profile gets a low equity ceiling instead of no equity, and the only thing that can
    still empty a role is a sustainability exclusion — which is what `reconcile_with_universe` remains
    for.
    """
    return result.value is not None


# ---------------------------------------------------------------- sustainability


@dataclass(frozen=True)
class Sustainability:
    """Two separate answers: what is refused, and how much must qualify."""

    exclusions: list
    level: str | None
    esg_min: float
    unknown_exclusions: list = field(default_factory=list)


def sustainability(*, exclusions=None, level: str | None = None) -> Sustainability:
    """The member's two sustainability answers, validated against the record's own vocabulary.

    An exclusion the record does not offer is reported rather than silently dropped: a member who wrote
    something the build cannot match has said something, and a curator should see it.
    """
    spec = parameters()["sustainability"]
    offered = set(spec["exclusions"]["offered"])
    named = [str(x).strip() for x in (exclusions or []) if str(x).strip()]
    known = [x for x in named if x in offered]
    unknown = [x for x in named if x not in offered]

    esg_min = 0
    for entry in spec["minimum"]["levels"]:
        if entry["label"] == (level or "").strip():
            esg_min = float(entry["esg_min"])
            break
    return Sustainability(exclusions=known, level=level, esg_min=esg_min,
                          unknown_exclusions=unknown)


__all__ = [
    "BY_BOTH", "BY_CAPACITY", "BY_WILLINGNESS", "COULD_NOT_BE_DETERMINED",
    "Capacity", "Profile", "ProfileNotApproved", "Sustainability", "Willingness",
    "admits", "capacity", "lerp", "parameters", "profile", "reconcile_with_universe",
    "sustainability", "willingness",
]
