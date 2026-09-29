"""The first pillar, from the statutory table rather than from an estimate.

**Why this exists.** Every Befund in the build said «Das Modell führt keine AHV-Rente», and for a member
asking whether their retirement is funded that is the largest missing number on the page: the first pillar
is most of the floor under every plan here, so leaving it out made every projection look worse than it is
by an amount nobody could see.

**It is a table lookup, not a formula.** The AHV publishes Skala 44 as 51 rows keyed on the
*Bestimmungsgrösse*, and the rows are upper bounds. Deriving a two-piece linear formula from them was
possible — the bend at 45'360 is visible in the data — and was not done: a formula I fitted is a figure
nobody published, and the table is the thing the Ausgleichskasse actually applies.

**The input nobody has is `mdje`.** The table is keyed on the *massgebendes durchschnittliches
Jahreseinkommen*: the revalued average of a whole working life. The build holds a member's CURRENT gross
income, which is a different number — usually higher for someone mid-career, lower for someone near the
end. This module therefore takes `mdje` explicitly and **never derives it from anything**. A caller that
passes current income is producing a real figure about a fictional person, and `illustration_for` exists
so that such a caller has to say so in the name of the function it called.

**Nothing computes from an unapproved record**, the way `property.conventions()` refuses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..content import _load

#: The same three words `property.py` and `liquidity.py` use.
MEETS = "meets"
DOES_NOT_MEET = "does_not_meet"
COULD_NOT_BE_DETERMINED = "could_not_be_determined"


class ScaleNotApproved(Exception):
    """The AHV table has no owner's name on it, so no pension may be computed from it.

    Raised rather than defaulted. A pension figure is the number a member will plan the rest of their life
    against, and one produced from an unsigned table is worse than none.
    """


def _record() -> dict:
    return _load("ahv-pension")


def scale() -> dict:
    """The approved table, or a refusal. Read on every call so approving needs no restart."""
    record = _record()
    about = record["_about"]
    if about.get("provisional", True):
        raise ScaleNotApproved(
            "client/content/ahv-pension.json is marked provisional and carries no publisher. The table is "
            "transcribed from the 2025 edition and used for 2026 on an inference the record names in its "
            "own `_for_review`; a member may not be shown a pension resting on that until somebody has "
            "checked it. Approving is `published_by`, `decided_on`, `effective_from` and "
            "`provisional: false`."
        )
    if not about.get("published_by"):
        raise ScaleNotApproved(
            "ahv-pension.json is not provisional and names no `published_by`. A value nobody stands "
            "behind is the defect C-02 exists to prevent, and this record carries fifty-one of them."
        )
    return record


def bounds() -> dict:
    """Minimum, maximum, the couple's cap and the number of payments, readable without approval.

    Separate from `scale()` for the reason `property.occupancies()` is separate: these four figures are
    what a member needs to understand the shape of the first pillar — that the maximum is exactly twice
    the minimum, and that a couple is capped at 150 percent rather than 200 — and none of them depends on
    the transcribed table being right for this year.
    """
    monthly = _record()["monthly"]
    return {
        "minimum": monthly["minimum"],
        "maximum": monthly["maximum"],
        "couple_cap": monthly["couple_cap"],
        "payments_per_year": monthly["payments_per_year"],
    }


@dataclass(frozen=True)
class Pension:
    """One person's AHV pension under the statutory table.

    `monthly` is what the table gives; `yearly` multiplies by the payments the record declares, which is
    thirteen from 2026 and not twelve. Reporting a yearly figure at twelve payments would understate it by
    a whole month, which is exactly the kind of quiet error a member cannot catch.
    """

    mdje: float
    #: Contribution years counted, and the cohort's maximum. `None` means the record was not stated.
    years: int | None
    full_scale: int
    #: The Skala 44 figure before any reduction.
    full_monthly: int
    #: `scale / 44`, or 1 where the record is complete or unknown.
    factor: float
    monthly: float
    yearly: float
    #: True where the table's own floor or ceiling decided the figure rather than the member's income.
    at_minimum: bool
    at_maximum: bool
    #: Reasons a caller must show alongside the figure.
    caveats: list[str] = field(default_factory=list)


def full_monthly(mdje: float) -> int:
    """The Skala 44 pension for an average income, straight off the published table.

    The `up_to` column is an upper bound, so the first row at or above `mdje` is the member's row. Below
    the first row the minimum applies; at or above the last, the maximum.
    """
    monthly = scale()["monthly"]
    if mdje <= 0:
        return int(monthly["minimum"])
    for row in monthly["scale_44"]:
        if mdje <= row["up_to"]:
            return int(row["monthly"])
    return int(monthly["maximum"])


def pension(*, mdje: float, contribution_years: int | None = None) -> Pension:
    """The pension for a stated average income and, where known, an incomplete record.

    `contribution_years` of `None` means nobody has said — which is not the same as a complete record, and
    is reported as a caveat rather than silently treated as full. Every member in the build states zero
    missing years, so the complete case is the common one; the caveat exists for the member who does not.
    """
    record = scale()
    monthly_record = record["monthly"]
    partial = record["partial"]
    full = full_monthly(mdje)
    full_scale = int(partial["full_scale"])

    caveats = ["mdje_is_a_lifetime_average_and_was_supplied_not_derived"]
    # `1` and not `1.0`: C-02 refuses a float literal in this layer. This is a ratio's identity,
    # not a rate, and an integer says so.
    factor = 1
    if contribution_years is None:
        caveats.append("the_contribution_record_was_not_stated_so_a_full_one_is_assumed")
    elif contribution_years < full_scale:
        factor = contribution_years / full_scale
        caveats.append("the_contribution_record_is_incomplete")

    monthly = full * factor
    return Pension(
        mdje=mdje,
        years=contribution_years,
        full_scale=full_scale,
        full_monthly=full,
        factor=factor,
        monthly=monthly,
        yearly=monthly * int(monthly_record["payments_per_year"]),
        at_minimum=full <= int(monthly_record["minimum"]),
        at_maximum=full >= int(monthly_record["maximum"]),
        caveats=caveats,
    )


def illustration_for(*, current_income: float, contribution_years: int | None = None) -> Pension:
    """The pension **as if** the member's current income were their lifetime average. It is not.

    **Named this way on purpose.** A caller reaching for a pension figure has only current income to hand,
    and the honest options are to refuse or to be loud. Refusing leaves the Befund saying the model holds
    no AHV pension, which is what this module was built to end. So the figure is produced and the
    substitution is carried in the return value as a caveat every caller must render — the name of the
    function is the first place a reader meets it and the caveat list is the second.

    For a member mid-career this overstates; for one near the end of a rising career it understates.
    """
    result = pension(mdje=current_income, contribution_years=contribution_years)
    result.caveats.insert(0, "current_income_was_used_where_a_lifetime_average_belongs")
    return result


def couple(*, first: Pension, second: Pension) -> dict:
    """Two pensions and the cap that applies to a married couple.

    The cap is 150 percent of the maximum and not 200. Two unmarried people with the same incomes receive
    more together than a married couple with those incomes, and that is a fact about the system a member
    is entitled to see rather than a rounding this module should hide.
    """
    monthly_record = _record()["monthly"]
    cap = int(monthly_record["couple_cap"])
    uncapped = first.monthly + second.monthly
    capped = min(uncapped, cap)
    payments = int(monthly_record["payments_per_year"])
    return {
        "uncapped_monthly": uncapped,
        "cap": cap,
        "monthly": capped,
        "yearly": capped * payments,
        "cap_binds": uncapped > cap,
        "lost_to_the_cap_monthly": max(0, uncapped - cap),
    }


def levers(result: Pension) -> list[dict]:
    """The dimensions that move this figure, with the arithmetic. Never prose, never ranked.

    Same contract as `property.levers`. Two of these move the number UP and are not modelled anywhere in
    the build, which is why they are named here rather than left out: a member reading a pension figure
    that omits Erziehungsgutschriften should meet that fact beside the figure and not in a footnote.
    """
    record = scale()
    partial = record["partial"]
    out: list[dict] = [
        {
            "dimension": "mdje",
            "stands_at": result.mdje,
            "gives_monthly": result.full_monthly,
            "at_minimum": result.at_minimum,
            "at_maximum": result.at_maximum,
        }
    ]
    if result.years is not None and result.years < result.full_scale:
        missing = result.full_scale - result.years
        out.append({
            "dimension": "contribution_years",
            "stands_at": result.years,
            "of": result.full_scale,
            "missing": missing,
            "costs_monthly": result.full_monthly * missing / result.full_scale,
            "may_be_paid_within_years": partial["gap_can_be_paid_within_years"],
        })
    for item in record["not_modelled"]["items"]:
        out.append({"dimension": "not_modelled", "note": item})
    return out


__all__ = [
    "COULD_NOT_BE_DETERMINED",
    "DOES_NOT_MEET",
    "MEETS",
    "Pension",
    "ScaleNotApproved",
    "bounds",
    "couple",
    "full_monthly",
    "illustration_for",
    "levers",
    "pension",
    "scale",
]
