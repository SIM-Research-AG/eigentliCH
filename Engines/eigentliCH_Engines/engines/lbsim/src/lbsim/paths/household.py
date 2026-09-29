"""The stated plan (spec 3.3 ``policy``): the household the Monte Carlo simulates, read from the sheet once.

Everything comes from what the findings already read (LBSIM-05): the adapter's submission, the draft's
``Params`` for it, the findings' income path and its saving needs. Nothing about the household is read twice.

* **State.** The submission's balance sheet (free wealth, pillars, property, debt) and the principal's E, N, H
  (the draft's mid-scale defaults where lbs states none, as the findings do); the habit starts at the spending.
* **Income.** The chosen income path of the findings (``income_path``; default ``education`` when an education
  is planned or in progress and the path exists, else ``today``), gross in today's francs, until the stop age
  (the stated one, else the reference age: port note P-1). The AHV from the reference age on the path's own
  averaged income, as the fast half computes it.
* **Controls.** The path's pensum and hours on the draft's 100-hour productive week (``tau_Y = pensum * 42 /
  100``, learning and network hours over 100, rest at the draft's reference share), the stated spending
  (indexed), the stated direct amortisation (nominal). Education budgets are read as part of the stated
  spending, as the findings' ledger reads them, so they are not paid twice.
* **Spending not stated.** With a stated saving (the mandate's annual contribution) the spending is what the
  first year's cash flow leaves after that saving (``saving_source: stated_contribution``); with neither, the
  household is taken to spend what it earns after tax (``cash_flow``, nothing saved from income). Both say so.
* **Goals.** Every dated goal of the path's saving needs within the horizon: home (the deposit, measure
  ``deposit_eligible``), retirement (the capital the flows from the reference age leave open, measure
  ``retirement_capital``), capital (a lump sum, measure ``drawable``). A goal in today's francs is judged in real
  terms on each path, one in future francs nominally (LBSIM-09). A reached home goal buys the home; a reached
  capital goal is paid out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import numpy as np

from .. import adapter as _adapter
from ..calibration import tables
from ..contracts import (Calibration, LbsRequest, LbsSheet, LifeBalanceFindings, Policy, Words)
from ..fast import gameplan as G
from ..fast import paths as FP
from ..model.params import Params
from .engine import CONTROL_NAMES, GoalEvent, Household
from .reference import derivatives

#: The draft's productive week: a time share is hours over 100 (spec 3.4 ``rest_hours_per_week``).
PRODUCTIVE_WEEK_HOURS = 100.0
#: onboarding ``_STATE_DEFAULTS``: mid-scale capitals where lbs states none (the findings use the same).
STATE_DEFAULTS = {"E": 0.5, "N": 0.5, "H": 0.8}
MEASURE_OF = {"home": "deposit_eligible", "retirement": "retirement_capital", "capital": "drawable"}


class PlanError(ValueError):
    """The request asks for something this sheet cannot give (a plain sentence for people)."""


@dataclass(frozen=True)
class GoalPlan:
    goal_id: str
    kind: str
    measure: str
    year: int
    date: date
    amount_basis: str                   # today | future
    target_real: float
    target_nominal: float               # at the sheet's inflation (the findings' figure)
    deposit_share: Optional[float] = None
    free_cash_real: float = 0.0         # the path's average yearly free cash until the goal, today's francs

    @property
    def basis(self) -> str:
        return "real" if self.amount_basis == "today" else "nominal"

    @property
    def target(self) -> float:
        return self.target_real if self.basis == "real" else self.target_nominal

    def event(self, execute: bool = True) -> GoalEvent:
        price = self.target / self.deposit_share if self.kind == "home" and self.deposit_share else None
        return GoalEvent(goal_id=self.goal_id, kind=self.kind, measure=self.measure, year=self.year,
                         basis=self.basis, target=self.target, execute=execute, price=price,
                         deposit_share=self.deposit_share)


@dataclass(frozen=True)
class StatedPlan:
    household: Household
    controls: np.ndarray
    policy: Policy
    goals: tuple[GoalPlan, ...]
    income_path: str
    horizon_years: int
    start_year: int
    params: Params
    stop_age: float
    submission: dict[str, Any]


def default_income_path(request: LbsRequest, principal: str, available: list[str]) -> str:
    person = next((p for p in (request.household.persons if request.household else ()) if p.person_id == principal),
                  None)
    ep = person.earning_power if person is not None else None
    if ep is not None and ep.education_status in ("in_progress", "planned") and "education" in available:
        return "education"
    return "today"


def resolve_horizon(requested: Optional[float], goal_years: list[float], age: Optional[float],
                    reference_age: float, cap: int) -> int:
    """LBSIM-18: the request's horizon, else the latest goal date, else the reference age; 1..cap years."""
    if requested is not None:
        years = float(requested)
    elif goal_years:
        years = max(goal_years)
    elif age is not None:
        years = reference_age - float(age)
    else:
        years = float(cap)
    return int(max(1, min(cap, math.ceil(years - 1e-9))))


def stated_plan(sheet: LbsSheet, request: LbsRequest, lbs_records: dict[str, dict[str, Any]],
                calibration: Calibration, findings: LifeBalanceFindings, *, income_path: Optional[str],
                horizon_years: Optional[float], max_horizon_years: int, reference_age: float,
                steps_per_year: int = 12) -> StatedPlan:
    adapted = _adapter.adapt(sheet, request, lbs_records, calibration)
    sub = adapted.submission
    state = sub["state"]
    if state.get("age") is None:
        raise PlanError("The sheet states no age for the person the plan is for, so no path can be simulated.")
    with tables(calibration):
        p = G._params_from(sub)
        runs = {r["code"]: r for r in FP.income_paths(sub, p)}
        stop = G._stop_age(sub, p)
        stop_age = float(stop) if stop is not None else float(p.ahv_age)
        pensions = calibration.behaviour.paths_household == "pensions"
        stated_stop = sub["params"].get("stop_work_age")
        if pensions and stated_stop is not None:
            # The draft reads a stop age only as an early exit and drops one above the reference age; the paths
            # read it as stated (DECISIONS P-21).
            stop_age = float(stated_stop)
        codes = [ip.code for ip in findings.income_paths]
        code = income_path or default_income_path(request, adapted.principal, codes)
        if code not in runs or code not in codes:
            raise PlanError(f"The income path '{code}' does not exist for this household (no education is planned "
                            "or stated), so it cannot be simulated. Leave it open or choose another.")
        path = runs[code]
        flows = FP._flows_from_65(sub, p, path, stop_age=stop)
    ip = next(i for i in findings.income_paths if i.code == code)

    age0 = float(state["age"])
    goal_kinds = {g["description"]: g.get("kind") for g in sub["goals"]}
    needs = [n for n in ip.saving_need if goal_kinds.get(n.goal_id) in MEASURE_OF and n.target_date is not None]
    horizon = resolve_horizon(horizon_years, [n.years for n in needs], age0, reference_age, max_horizon_years)
    n_steps = horizon * steps_per_year
    dt = 1.0 / steps_per_year

    # -- controls and income, month by month, at the ages the engine steps through
    raw = sub["raw"]
    spend = raw.get("spend_now")
    pA = float(sub["params"].get("p_A") or 0.0)
    ages = []
    a = age0
    for _ in range(n_steps):
        ages.append(a)
        a = a + 1.0 * dt
    edu_end = path["education_end_age"]
    pensum_after = path["pensum_after"]
    income = np.zeros(n_steps)
    ctl = np.zeros((n_steps, len(CONTROL_NAMES)))
    for m, age in enumerate(ages):
        working = age < stop_age
        if pensum_after is not None and edu_end is not None and age >= edu_end:
            share = float(pensum_after)
        else:
            share = float(path["pensum_now"])
        learning = path["learning_hours"] if (edu_end is None or age < edu_end) else 0.0
        income[m] = float(path["income_at"](age)) if working else 0.0
        ctl[m] = (share * FP.FULL_TIME_HOURS / PRODUCTIVE_WEEK_HOURS if working else 0.0,
                  learning / PRODUCTIVE_WEEK_HOURS if working else 0.0,
                  path["network_hours"] / PRODUCTIVE_WEEK_HOURS if working else 0.0,
                  p.tau_H_ref, 0.0, 0.0, 0.0, pA)

    x0 = {"W_L": float(state["W_L"] or 0.0), "W_R": float(state["W_R"] or 0.0), "D": float(state["D"] or 0.0),
          "E": float(state["E"]) if state.get("E") is not None else STATE_DEFAULTS["E"],
          "N": float(state["N"]) if state.get("N") is not None else STATE_DEFAULTS["N"],
          "H": float(state["H"]) if state.get("H") is not None else STATE_DEFAULTS["H"],
          "age": age0, "W_res": float(state.get("W_res") or 0.0), "W_hol": float(state.get("W_hol") or 0.0),
          "W_P": float(state.get("W_P") or 0.0), "W_3a": float(state.get("W_3a") or 0.0), "kappa": 0.0}
    ahv_income = float(flows["own_lifetime_income"])

    # -- the spending, or the fallback that says so
    fallback = None
    saving_source = "cash_flow"
    if spend is not None:
        C0 = float(spend)
    else:
        u0 = dict(zip(CONTROL_NAMES, ctl[0]))
        u0["C"] = 0.0
        net0 = derivatives({**x0, "kappa": 0.0}, u0, p, P=1.0, income=float(income[0]), ahv_income=ahv_income)["net"]
        contribution = raw.get("savings")
        if contribution is not None:
            saving_source = "stated_contribution"
            C0 = max(0.0, net0 - float(contribution))
            fallback = Words(
                de=("Die Ausgaben sind nicht angegeben. Die Verläufe nehmen an, dass der Haushalt ausgibt, was nach "
                    "Steuern und der angegebenen jährlichen Sparsumme übrig bleibt."),
                en=("Spending is not stated. The paths assume the household spends what is left after tax and the "
                    "stated yearly saving."))
        else:
            C0 = max(0.0, net0)
            fallback = Words(
                de=("Weder Ausgaben noch eine Sparsumme sind angegeben. Die Verläufe nehmen an, dass der Haushalt "
                    "ausgibt, was er nach Steuern verdient, und aus dem Einkommen nichts spart."),
                en=("Neither spending nor a saving is stated. The paths assume the household spends what it earns "
                    "after tax and saves nothing from income."))
    ctl[:, CONTROL_NAMES.index("C")] = C0
    x0["kappa"] = C0

    # -- the goals
    reals = {n.goal_id: n for n in ip.views.real.saving_need}
    goals = []
    occupancy = {g.goal_id: g.occupancy for g in request.goals}
    for n in needs:
        year = int(max(1, round(n.years)))
        if year > horizon:
            continue
        kind = goal_kinds[n.goal_id]
        amounts = adapted.goal_amounts.get(n.goal_id) or {}
        share = None
        if kind == "home":
            share = _adapter.deposit(lbs_records, 1.0, occupancy.get(n.goal_id))[0]
        goals.append(GoalPlan(goal_id=n.goal_id, kind=kind, measure=MEASURE_OF[kind], year=year,
                              date=n.target_date, amount_basis=amounts.get("basis") or "today",
                              target_real=float(reals[n.goal_id].target_chf), target_nominal=float(n.target_chf),
                              deposit_share=share, free_cash_real=float(reals[n.goal_id].free_cash_chf_per_year)))
    if pensions:
        household = Household(x0=x0, p=p, income=income, ahv_income=ahv_income,
                              events=tuple(g.event(execute=g.kind == "home") for g in goals), p2_cash_share=0.5,
                              pension_at_age=max(stop_age, float(p.pension_age)),
                              annuity_rate=G.PILLAR2_CONVERSION_RATE)
    else:
        household = Household(x0=x0, p=p, income=income, ahv_income=ahv_income,
                              events=tuple(g.event() for g in goals))
    policy = Policy(spending_chf_per_year=C0, pensum=float(path["pensum_now"]), saving_source=saving_source,
                    fallback=fallback)
    return StatedPlan(household=household, controls=ctl, policy=policy, goals=tuple(goals), income_path=code,
                      horizon_years=horizon, start_year=sheet.as_of.year, params=p, stop_age=stop_age,
                      submission=sub)
