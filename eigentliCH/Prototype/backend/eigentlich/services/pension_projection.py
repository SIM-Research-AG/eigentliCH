"""The second pillar to the reference age, credited by age band the way the law credits it.

**Why by age.** The Altersgutschriften step up — 7, 10, 15, 18 percent of the coordinated salary — so a
23-year-old and a 55-year-old on the same salary accrue at very different rates, and a projection that
used one average rate would be wrong for everybody. The bands are BVG Art. 16 and they live in
`client/content/bvg-projection.json`, not here.

**Two things this gets right that a naive projection gets wrong.**

Credits start at 25. Below that the obligatory scheme insures death and invalidity only, so a balance of
zero at 23 is consistent with being correctly insured, and the projection must credit nothing for those
years rather than quietly starting early.

The coordinated salary is not the salary. It is the AHV salary capped at the upper limit and reduced by a
fixed deduction, which is why a part-time pensum is hit harder than proportionally — the deduction removes
the same amount from a small salary as from a large one.

**Interest is the Mindestzinssatz, and that is the owner's choice of three.** Asked on 5 September 2026
whether to project at zero, at the statutory minimum, or as a band, the owner chose the minimum. It is the
only citable figure of the three. It is also a floor set for ONE year and revisited annually, so every
result carries `interest_is_a_statutory_minimum_not_a_return` and callers must render it.

**Nothing computes from an unapproved record.**
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..content import _load

COULD_NOT_BE_DETERMINED = "could_not_be_determined"


class ProjectionNotApproved(Exception):
    """The projection record has no owner's name on it, so no balance may be computed from it."""


def _record() -> dict:
    return _load("bvg-projection")


def parameters() -> dict:
    """The approved record, or a refusal."""
    record = _record()
    about = record["_about"]
    if about.get("provisional", True):
        raise ProjectionNotApproved(
            "client/content/bvg-projection.json is marked provisional and carries no publisher. It "
            "projects decades forward at one year's statutory minimum interest, which the record's own "
            "`_for_review` names as the first thing to check. Approving is `published_by`, `decided_on`, "
            "`effective_from` and `provisional: false`."
        )
    if not about.get("published_by"):
        raise ProjectionNotApproved(
            "bvg-projection.json is not provisional and names no `published_by`."
        )
    return record


def bands() -> list[dict]:
    """The four credit rates, readable without approval — the shape of the rule puts no figure on anybody."""
    return list(_record()["credits"]["bands"])


def credit_rate(age: int) -> float:
    """The statutory credit rate at an age, or zero below the starting age."""
    credits = _record()["credits"]
    if age < int(credits["starts_at_age"]):
        return 0
    for band in credits["bands"]:
        if band["from_age"] <= age <= band["to_age"]:
            return float(band["rate"])
    return 0


def coordinated_salary(gross: float) -> float | None:
    """The insured slice of a salary, or `None` where the salary is below the entry threshold.

    `None` and not zero: below the threshold there is no obligatory insurance at all, which is a different
    statement from being insured on nothing, and the two lead to different conversations.
    """
    c = _record()["coordination"]
    if gross <= c["entry_threshold"]:
        return None
    capped = min(gross, c["upper_limit"])
    coordinated = capped - c["deduction"]
    if coordinated <= 0:
        return float(c["minimum_coordinated"])
    return float(max(coordinated, c["minimum_coordinated"]))


@dataclass(frozen=True)
class Projection:
    """A balance carried to the reference age, and the pension the statutory rate turns it into."""

    from_age: int
    to_age: int
    opening_balance: float
    gross_salary: float
    coordinated: float | None
    interest_rate: float
    #: One entry per year: age, the rate applied, the credit, the interest, the closing balance.
    years: list[dict]
    closing_balance: float
    total_credited: float
    total_interest: float
    conversion_rate: float
    #: The obligatory pension the closing balance converts to, monthly and yearly.
    monthly_pension: float
    caveats: list[str] = field(default_factory=list)


def project(*, current_age: int, opening_balance: float, gross_salary: float,
            to_age: int | None = None) -> Projection:
    """Carry a balance forward year by year, crediting at the rate for each age reached.

    Year by year rather than in closed form, deliberately: the rate changes three times on the way and the
    year-by-year table is the thing a member can check a line of. Interest is credited on the opening
    balance of each year, which is the conservative reading — a fund that credits on the average would
    give slightly more.
    """
    record = parameters()
    rate = float(record["interest"]["minimum_rate"])
    conversion = float(record["conversion"]["minimum_rate"])
    end = int(to_age if to_age is not None else record["conversion"]["at_reference_age"])
    coordinated = coordinated_salary(gross_salary)

    caveats = [
        "interest_is_a_statutory_minimum_not_a_return",
        "the_obligatory_portion_only_the_ueberobligatorium_is_not_visible_here",
        "the_salary_is_assumed_unchanged_to_the_reference_age",
    ]
    if coordinated is None:
        caveats.append("the_salary_is_below_the_entry_threshold_so_nothing_is_credited")

    balance = float(opening_balance)
    years: list[dict] = []
    credited = interest_total = 0
    for age in range(int(current_age), end):
        band_rate = credit_rate(age)
        credit = (coordinated or 0) * band_rate
        interest = balance * rate
        balance = balance + credit + interest
        credited += credit
        interest_total += interest
        years.append({
            "age": age, "credit_rate": band_rate, "credit": credit,
            "interest": interest, "closing": balance,
        })

    return Projection(
        from_age=int(current_age), to_age=end,
        opening_balance=float(opening_balance), gross_salary=float(gross_salary),
        coordinated=coordinated, interest_rate=rate, years=years,
        closing_balance=balance, total_credited=credited, total_interest=interest_total,
        conversion_rate=conversion, monthly_pension=balance * conversion / 12,
        caveats=caveats,
    )


def levers(result: Projection) -> list[dict]:
    """The dimensions that move the balance, with the arithmetic. Never prose."""
    record = parameters()
    out: list[dict] = [
        {"dimension": "coordinated_salary", "stands_at": result.coordinated,
         "gross": result.gross_salary, "deduction": record["coordination"]["deduction"]},
        {"dimension": "years_remaining", "stands_at": result.to_age - result.from_age},
        {"dimension": "opening_balance", "stands_at": result.opening_balance,
         "grows_to": result.closing_balance,
         "of_which_interest": result.total_interest, "of_which_credits": result.total_credited},
    ]
    for item in record["not_modelled"]["items"]:
        out.append({"dimension": "not_modelled", "note": item})
    return out


__all__ = [
    "COULD_NOT_BE_DETERMINED",
    "Projection",
    "ProjectionNotApproved",
    "bands",
    "coordinated_salary",
    "credit_rate",
    "levers",
    "parameters",
    "project",
]
