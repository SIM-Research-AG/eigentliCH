"""The second pillar as the law builds it: a coordinated salary, an age band, and a start at 25.

**What this replaces, and why it was wrong in the direction that matters most.** `Params.pension_contribution_rate`
is a flat 15 % of FULL income with a gate that closes at retirement and never opens at the bottom. Its own
comment is honest about the simplification -- it says it errs high for low earners -- but the size of the error
only became visible on a real household: a twenty-four-year-old earning 24 000 at a reduced Pensum was credited
3 600 a year from today, accumulating to 172 824 by 65 and an annuity of 9 073, which was **a third of the
entire income the report promised him from 65**. He cannot be accruing any of it. Two independent rules say so
and both cut the same way:

  *Nothing before 25.* Altersgutschriften run from the calendar year the insured person turns 25. Before that
  the employment is insured for death and disability only, and no Altersguthaben is built at all.

  *The coordinated salary, not the salary.* Contributions apply to the salary less the Koordinationsabzug,
  floored at a minimum and capped at an upper limit. At 24 000 that deduction exceeds the salary itself, so
  what remains is the statutory minimum -- a small fraction of the figure a flat rate on full income produces.

The figures live in `data/social_insurance.json` with their source and vintage, for the same reason the canton
table does: a threshold written from memory is a number nobody can check, and every forward-looking figure in
a report inherits the vintage of the table behind it.

**Applied in the converter and the report, not in the dynamics.** `model/dynamics.py` and `optim/symbolic.py`
must stay one transcription of one model or the parity tests stop meaning anything, and an age-banded step
function is exactly the kind of thing CasADi cannot carry. So this module computes the accrual the report
states, and the optimiser keeps its smooth approximation -- with the difference between them named in the
assumptions rather than left for a reader to discover.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

#: The sourced table. Outside the package because it is data with a vintage rather than model structure.
TABLE = Path(__file__).resolve().parents[4] / "data" / "social_insurance.json"


class TableError(ValueError):
    """The table is missing or cannot be trusted. There is no silent fallback: see `load`."""


def load(path: Path | None = None) -> dict[str, Any]:
    """The table, or an error naming what is wrong with it.

    **Unlike the canton table, absence is not tolerated here.** A missing cantonal factor means the national
    approximation stands, which is a defensible degradation. A missing BVG table would mean falling back to a
    flat rate on full income -- the very thing this module exists to remove -- and doing that quietly would
    reintroduce the defect for exactly the households it was found on.
    """
    p = path or TABLE
    if not p.is_file():
        raise TableError(
            f"{p} is missing. It carries the BVG Grenzbeträge and Altersgutschriftensätze with their source "
            f"and vintage; without it the second pillar cannot be computed from anything checkable."
        )
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise TableError(f"{p.name} is not valid JSON: {exc}") from exc

    if not raw.get("source") or not raw.get("as_of"):
        raise TableError(f"{p.name} must carry `source` and `as_of`. A table without a vintage cannot be "
                         f"checked against anything, and every figure derived from it inherits that.")
    bvg = raw.get("bvg") or {}
    needed = ("entry_threshold_yearly", "coordination_deduction_yearly", "min_coordinated_salary_yearly",
              "upper_limit_yearly", "savings_start_age", "savings_rates")
    missing = [k for k in needed if bvg.get(k) is None]
    if missing:
        raise TableError(f"{p.name}: the bvg block is missing {', '.join(missing)}")
    bands = bvg["savings_rates"]
    if not bands or any(b.get("rate") is None or b.get("from_age") is None for b in bands):
        raise TableError(f"{p.name}: every savings_rates entry needs from_age, to_age and rate")
    return raw


def coordinated_salary(gross: float, table: dict[str, Any]) -> float:
    """The insured salary: gross less the coordination deduction, floored and capped.

    Zero below the entry threshold, because below it there is no mandatory insurance at all -- which is a
    different statement from "a small coordinated salary" and produces a different plan.
    """
    b = table["bvg"]
    if gross is None or gross < float(b["entry_threshold_yearly"]):
        return 0.0
    capped = min(float(gross), float(b["upper_limit_yearly"]))
    coordinated = capped - float(b["coordination_deduction_yearly"])
    return max(coordinated, float(b["min_coordinated_salary_yearly"]))


def savings_rate(age: float, table: dict[str, Any]) -> float:
    """The Altersgutschrift for this age, as a share of the coordinated salary. Zero before the start age.

    The bands are read from the table rather than interpolated: they are a step function in law, and smoothing
    them here would produce a number that is not the one any pension fund will credit.
    """
    b = table["bvg"]
    if age < float(b["savings_start_age"]):
        return 0.0
    for band in b["savings_rates"]:
        lo, hi = float(band["from_age"]), float(band.get("to_age") or 200.0)
        if lo <= age <= hi:
            return float(band["rate"])
    # Past the last band: contributions have stopped, which the caller's own retirement age also governs.
    return 0.0


def accrue(*, age_now: float, age_stop: float, age_reference: float, start_capital: float,
           interest: float, income_at: Callable[[float], float],
           table: dict[str, Any] | None = None) -> dict[str, Any]:
    """Roll the Altersguthaben forward year by year to the reference age.

    `income_at` is a function of age rather than a number, which is the point of doing this as a loop: a
    household whose income changes -- an education finishing, a Pensum rising -- accrues differently, and the
    closed-form annuity factor this replaces could only express a constant salary. A young household is
    precisely the case where that assumption is furthest from the truth.

    Contributions run to `age_stop` and the capital keeps earning interest to `age_reference`, so stopping work
    early costs the contributions of the missing years and not the growth on what is already there.

    Returns the capital and the year-by-year trace, because a household reading "172 824" is entitled to see
    which years produced it -- and on the case that prompted this module, the answer was "years he is not
    legally accruing in".
    """
    t = table or load()
    years = []
    capital = float(start_capital or 0.0)
    age = float(age_now)
    contributed = 0.0
    while age < float(age_reference):
        gross = float(income_at(age) or 0.0)
        contributing = age < float(age_stop)
        coordinated = coordinated_salary(gross, t) if contributing else 0.0
        rate = savings_rate(age, t) if contributing else 0.0
        credit = coordinated * rate
        capital = capital * (1.0 + float(interest)) + credit
        contributed += credit
        years.append({"age": round(age, 1), "gross": gross, "coordinated": coordinated,
                      "rate": rate, "credit": credit, "capital": capital})
        age += 1.0
    return {
        "capital": capital,
        "contributed": contributed,
        "years": years,
        "as_of": t["as_of"],
        "source": t["source"],
        "entry_threshold": float(t["bvg"]["entry_threshold_yearly"]),
        "coordination_deduction": float(t["bvg"]["coordination_deduction_yearly"]),
        "min_coordinated": float(t["bvg"]["min_coordinated_salary_yearly"]),
        "upper_limit": float(t["bvg"]["upper_limit_yearly"]),
        "savings_start_age": float(t["bvg"]["savings_start_age"]),
    }


def ahv_annual_from_monthly(monthly: float, table: dict[str, Any] | None = None) -> float:
    """A monthly AHV pension as an annual sum, at the number of payments the table records.

    **Thirteen, not twelve, since the 13. AHV-Altersrente.** The BSV publishes the pension per month with the
    note «13 Auszahlungen», so an annual figure built by multiplying by twelve understates a full pension by
    one month of it. The model's own `ahv_full_single` was 30 240 -- twelve times the maximum -- which is the
    figure this function exists to stop being written by hand.
    """
    t = table or load()
    return float(monthly) * float(t["ahv"]["payments_per_year"])
