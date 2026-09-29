"""The findings artefact (``lbsim-findings@1.0.0``): the port's quantities, in lbsim's contract.

``build_findings`` runs the adapter, the draft's ``gameplan.assemble`` (which runs ``paths.ledger``,
``findings.evaluate/schedule``, ``plausibility``, ``search.frontier``, ``asks.rank`` and ``workflow.open_items``)
and the one earning-power computation, and states the result with the words of the calibration's
``findings-text`` record. Pure: no I/O, no clock; the same inputs give the same bytes.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Optional

from .. import ENGINE_VERSION
from .. import adapter as _adapter
from ..calibration import approved, calibration_hash, tables
from ..contracts import (CONTRACT_VERSIONS, FINDING_CODES, Assumption, Calibration, CurrentEarning, EarningInputs,
                         EarningPower, EducationPlan, Figure, Finding, FindingText, FindingWords, FrontierGoal,
                         FrontierMove, FrontierPlan, From65, Gate, GateItem, HealthCapacity, IncomePath,
                         IncomePathViews, IncomeYear, InflationUsed, InputCheck, LbsRequest, LbsSheet,
                         LbsUpstream, LifeBalanceFindings, ModelledEarningPower, NextQuestion, Provenance,
                         RealSavingView, RecordUse, Responsibility, SavingNeed, SavingNeedReal, ScheduleEntry,
                         StatedEarning, Unchecked, Words, ZeroReturn)
from ..ids import content_id
from ..model.params import Params
from . import earning as _earning
from . import gameplan as G
from .findings import SEVERITY_ORDER, URGENCY_ORDER

#: The draft reports ``wealth_that_cannot_work`` under ``drawable_thin``; lbsim under the rule's name.
_DRAFT_CODE = {"drawable_thin": "wealth_that_cannot_work"}

_ASSUMPTION_UNITS = {"withdrawal_rate": "rate", "conversion_rate": "rate", "pension_interest": "rate",
                     "rent_yield": "rate", "wealth_tax_rate": "rate", "income_tax": "rate", "mortgage_rate": "rate",
                     "inflation": "rate", "residence_is_all_property": "chf", "pillar3a_contribution":
                     "chf_per_year", "spending": "chf_per_year", "earning_level": None, "child_costs": None,
                     "ahv_record": "share", "capitals_mid_scale": None}


def _w(d: dict[str, str]) -> Words:
    return Words(de=d["de"], en=d["en"])


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _figures(text: dict[str, Any], code: str, values: dict[str, Any]) -> dict[str, Figure]:
    spec = text["findings"][code]["figures"]
    return {name: Figure(value=_f(values.get(name)), unit=unit, basis=basis)
            for name, (unit, basis) in spec.items()}


def _finding_values(code: str, f: dict[str, Any], q: dict[str, Any], p: Params,
                    adapted: _adapter.Adapted) -> dict[str, Any]:
    """The figures a finding's template names, from the draft finding and the quantities behind it."""
    fig = f["figures"]
    b, cf = q["balance"], q["cash_flow"]
    if code == "no_legal_documents":
        return {"documents": len(fig.get("documents") or []), "property_total": fig.get("property_total")}
    if code == "pension_too_small":
        return {"pillar2": fig["pillar2"], "income_gross": fig["income_gross"], "ratio": fig["ratio"]}
    if code == "positions_outside_model":
        return {"total": fig["total"], "drawable": fig["drawable"], "items": len(fig.get("items") or [])}
    if code == "rate_reset_near":
        return {"years_left": fig["fixed_until"] - fig["collected_year"], "debt": fig["debt"],
                "cost_per_point": fig["cost_per_point"]}
    if code == "goal_not_computed":
        return {"count": len(fig.get("deferred") or []), "largest_deferred": fig.get("largest_deferred"),
                "target_solved": fig.get("target_solved")}
    if code == "indirect_amortisation":
        return {"amount": fig.get("amount"), "debt": fig.get("debt")}
    if code == "wealth_that_cannot_work":
        return fig
    return dict(fig)


def _moves_from_labels(labels: list[str], goal: dict[str, Any], text: dict[str, Any]) -> list[FrontierMove]:
    """The draft's move labels (``search.Move.label``) read back into a dimension and a value, and worded from
    the record. The draft's formats are fixed in ``search.py``; an unknown label raises (it is a port defect)."""
    out = []
    for label in labels:
        m = re.match(r"^Pensum auf (\d+)%$", label)
        if m:
            dim, value, shown = "pensum", float(m.group(1)) / 100.0, f"{m.group(1)} %"
        elif (m := re.match(r"^Weiterbildung, (\d+) h/Woche$", label)):
            dim, value, shown = "learning", float(m.group(1)), m.group(1)
        elif (m := re.match(r"^Netzwerk, (\d+) h/Woche$", label)):
            dim, value, shown = "network", float(m.group(1)), m.group(1)
        elif (m := re.match(r"^Ausgaben (\d+)% tiefer$", label)):
            dim, value, shown = "spending", float(m.group(1)) / 100.0, f"{m.group(1)} %"
        elif (m := re.match(r"^Erwerbsende mit (\d+)$", label)):
            dim, value, shown = "stop_age", float(m.group(1)), m.group(1)
        elif (m := re.match(r"^Zieljahr (\d{4})$", label)):
            delay = int(m.group(1)) - int(goal["target_year"])
            dim, value, shown = "goal_year", float(delay), str(delay)
        elif (m := re.match(r"^Betrag auf (\d+)%$", label)):
            dim, value, shown = "goal_amount", float(m.group(1)) / 100.0, f"{m.group(1)} %"
        else:
            raise ValueError(f"the frontier move {label!r} has no reading in lbsim")
        tpl = text["moves"][dim]["change"]
        out.append(FrontierMove(dimension=dim, value=value,
                                label=Words(de=tpl["de"].replace("{value}", shown),
                                            en=tpl["en"].replace("{value}", shown))))
    return out


def _earning_power(adapted: _adapter.Adapted, person_id: str, record: dict[str, Any], cal: Calibration,
                   text: dict[str, Any], year_now: int) -> EarningPower:
    a = adapted.adults[person_id]
    person = a.person
    ep = person.earning_power
    qualification = person.human_capital.qualification_highest
    unit = _earning.at_unit(record) if cal.behaviour.earning_power == "record" else Params().earning_power_at_unit
    m = _earning.modelled(record, E=a.E, N=a.N, age=person.age, qualification=qualification,
                          responsibility_stated=ep.responsibility if ep else None,
                          sector=ep.sector if ep else None, unit=unit)
    words = text["earning"]
    caveats: list[Words] = []
    modelled = None
    reason = None
    if m is None:
        reason = _w(words["no_age"] if person.age is None else words["not_available"])
    else:
        t = m.tier
        modelled = ModelledEarningPower(
            full_time_chf_per_year=m.full_time_chf_per_year,
            at_full_productive_week_chf=m.at_full_productive_week_chf,
            monthly_standardised_chf=m.monthly_standardised_chf,
            before_responsibility_chf=m.before_responsibility_chf,
            responsibility=Responsibility(tier=t.key, label=Words(de=t.label.get("de", t.key),
                                                                   en=t.label.get("en", t.key)),
                                          multiplier=t.multiplier, stated=t.stated),
            inputs=EarningInputs(**m.inputs))
        if not (ep and ep.responsibility):
            caveats.append(_w(words["tier_not_stated"]))
        elif t.note and t.note.startswith("no qualification"):
            caveats.append(_w(words["tier_mean"]))
        elif t.note and ("no sector" in t.note or "has no published figure" in t.note):
            caveats.append(_w(words["sector_missing"]))
        elif t.note and "not a published tier" in t.note:
            caveats.append(_w(words["tier_unknown"]))
        elif t.note and t.key == "topmanagement" and qualification != "Universitäre Hochschule":
            caveats.append(_w(words["extrapolated"]))
    withheld = person.human_capital.health_withheld
    if a.H is None:
        caveats.append(_w(words["health_withheld" if withheld else "health_unknown"]))
    capacity = ep.health_work_capacity if ep else None
    if capacity is not None and capacity < 1.0:
        caveats.append(_w(words["capacity_below_pensum"]))
    status = ep.education_status if ep else None
    end_year = ep.education_end_year if ep else None
    end_age = (float(person.age + (end_year - year_now)) if end_year is not None and person.age is not None
               and status in ("in_progress", "planned") else None)
    hours = None
    if ep is not None and ep.education_hours is not None:
        hours = (G.EDUCATION_HOURS_BANDS.get(ep.education_hours) if isinstance(ep.education_hours, str)
                 else float(ep.education_hours))
    gross = a.gross_income
    pensum = _adapter.pensum(person.human_capital.hours_per_week)
    expected = ep.expected_full_pensum_income if ep else None
    return EarningPower(
        person_id=person_id, status="available" if modelled else "not_available", reason=reason,
        modelled=modelled,
        stated=StatedEarning(expected_full_pensum_income_chf_per_year=expected,
                             from_age=(end_age if end_age is not None else (float(person.age)
                                       if person.age is not None else None)) if expected is not None else None),
        level_basis="stated" if expected is not None else "modelled",
        current=CurrentEarning(gross_income_chf_per_year=gross, pensum=pensum,
                               full_pensum_equivalent_chf=(gross / pensum) if gross is not None and pensum
                               else None),
        education=EducationPlan(status=status, end_year=end_year, end_age=end_age, hours_per_week=hours,
                                budget_chf_per_year=ep.education_budget_per_year if ep else None),
        health=HealthCapacity(H=a.H, work_capacity=capacity,
                              capacity_basis="withheld" if withheld else ("stated" if capacity is not None
                                                                          else "modelled")),
        caveats=tuple(caveats))


def _income_paths(q: dict[str, Any], adapted: _adapter.Adapted, text: dict[str, Any], inflation: InflationUsed,
                  year_now: int) -> tuple[IncomePath, ...]:
    ledger = q.get("paths") or {}
    if ledger.get("error"):
        return ()
    pi = inflation.annual_rate
    liquid = float(adapted.submission["state"]["W_L"] or 0.0)
    age0 = float(adapted.submission["state"]["age"] or 0.0)
    out = []
    for run in ledger["paths"]:
        needs, reals = [], []
        for row in run["goals"]:
            gid = row["description"]
            years = float(row["years"])
            n = max(1, int(round(years)))
            level = (1.0 + pi) ** years
            window = [y for y in run["years"] if y["age"] < row["age_at_goal"]] or []
            real_free = (sum(y["free"] / (1.0 + pi) ** (y["age"] - age0) for y in window) / len(window)
                         if window else 0.0)
            growth = sum((1.0 + pi) ** k for k in range(n))
            target = float(row["target"])
            needs.append(SavingNeed(goal_id=gid, target_chf=target, target_date=adapted.goal_dates.get(gid),
                                    years=years, zero_return_saving_chf_per_year=float(row["required_saving"]),
                                    free_cash_chf_per_year=float(row["available_saving"]),
                                    holds=bool(row["reachable"])))
            reals.append(SavingNeedReal(goal_id=gid, target_chf=target / level,
                                        zero_return_saving_chf_per_year=(max(0.0, target - liquid) / growth
                                                                         if pi else float(row["required_saving"])),
                                        free_cash_chf_per_year=real_free if pi else float(row["available_saving"])))
        words = text["income_paths"][run["code"]]
        out.append(IncomePath(
            code=run["code"], person_id=adapted.principal, name=_w(words["name"]), note=_w(words["note"]),
            level_basis=run["basis"], pensum_now=float(run["pensum_now"]), pensum_after=float(run["pensum_after"]),
            education_end_age=run["education_end_age"],
            learning_hours=_learning(run, q),
            network_hours=_network(run),
            income=tuple(IncomeYear(year=year_now + int(round(y["age"] - age0)), age=float(y["age"]),
                                    gross_chf_per_year=float(y["gross"])) for y in run["years"]),
            from_65=From65(ahv_chf_per_year=float(run["flows_from_65"]["ahv"]),
                           bvg_chf_per_year=float(run["flows_from_65"]["pillar2_annuity"])),
            saving_need=tuple(needs),
            views=IncomePathViews(real=RealSavingView(deflator=inflation, saving_need=tuple(reals)))))
    return tuple(out)


def _learning(run: dict[str, Any], q: dict[str, Any]) -> float:
    if run["code"] == "today":
        return 0.0
    raw = q.get("_raw_for_hours") or {}
    return float(G.education_hours(raw) or 0.0)


def _network(run: dict[str, Any]) -> float:
    return float(G.NETWORK_KNEE_HOURS) if run["code"] == "network" else 0.0


def build_findings(sheet: LbsSheet, request: LbsRequest, lbs_records: dict[str, dict[str, Any]],
                   calibration: Calibration, *, sheet_sha256: str, lbs_url: Optional[str] = None) -> LifeBalanceFindings:
    """The findings artefact for one sheet under one calibration."""
    adapted = _adapter.adapt(sheet, request, lbs_records, calibration)
    text = calibration.records["findings-text"]
    sub = adapted.submission
    with tables(calibration):
        q = G.assemble(sub)
        p = G._params_from(sub)
    q["_raw_for_hours"] = sub["raw"]
    year_now = sheet.as_of.year
    pi = adapted.inflation
    inflation = InflationUsed(
        currency=(sheet.real_view.currency if sheet.real_view else "CHF"), annual_rate=pi, log_rate=math.log1p(pi),
        source=(f"the Life Balance Sheet's own assumption ({sheet.real_view.inflation.index}), lbs calibration "
                f"{sheet.calibration_version}" if pi and sheet.real_view else
                "none: calibration 1.0.0 reproduces the draft, which carries no inflation"))

    # -- findings, with a rule resting on a missing answer reported unchecked rather than passed or fired
    fired, unchecked = [], []
    fired_codes = set()
    for f in q["findings"]:
        code = _DRAFT_CODE.get(f["code"], f["code"])
        if code in adapted.missing:
            continue
        spec = text["findings"][code]
        words = spec["text"]
        fired.append(Finding(
            code=code, severity=f["severity"], urgency=f["urgency"], action_kind=spec["action_kind"],
            figures=_figures(text, code, _finding_values(code, f, q, p, adapted)),
            text=FindingText(de=FindingWords(**words["de"]), en=FindingWords(**words["en"])),
            answers=tuple(spec["answers"])))
        fired_codes.add(code)
    fired.sort(key=lambda x: (URGENCY_ORDER[x.urgency], SEVERITY_ORDER[x.severity], x.code))
    failed = {s.split(":")[0] for s in q.get("findings_unchecked") or []}
    for code in FINDING_CODES:
        if code in fired_codes:
            continue
        if code == "goal_not_fundable":
            unchecked.append(Unchecked(code=code, reason=_w(text["unchecked"][code]), answered_by="plan"))
        elif code in adapted.missing:
            unchecked.append(Unchecked(code=code, reason=_w(text["unchecked"][code]),
                                       missing=tuple(adapted.missing[code])))
        elif code in failed:
            unchecked.append(Unchecked(code=code, reason=_w(text["unchecked"]["_rule_failed"]),
                                       missing=tuple(text["findings"][code]["answers"]) or ("goals",)))
    schedule = tuple(ScheduleEntry(when=k, label=_w(text["schedule"][k]),
                                   codes=tuple(f.code for f in fired if f.urgency == k))
                     for k in URGENCY_ORDER if any(f.urgency == k for f in fired))

    # -- input checks
    checks = tuple(InputCheck(code=c["code"], severity=c["severity"], blocks=bool(c.get("blocks")),
                              title=_w(text["input_checks"][c["code"]]["title"]),
                              question=_w(text["input_checks"][c["code"]]["question"]), fields=tuple(c["fields"]))
                   for c in (q.get("plausibility") or {}).get("checks") or [])

    # -- the frontier (at zero; lbs carries no stated expectation of a return)
    frontier = []
    search = q.get("search") or {}
    goals_by_id = {g["description"]: g for g in sub["goals"]}
    for rate_key, result in search.items():
        if not isinstance(result, dict) or "goals" not in result:
            continue
        rate = float(result["rate"])
        for g in result["goals"]:
            gid = g["description"]
            goal = goals_by_id.get(gid) or {"target_year": g["target_year"]}

            def plan(best: Optional[dict[str, Any]]) -> Optional[FrontierPlan]:
                if best is None:
                    return None
                return FrontierPlan(moves=tuple(_moves_from_labels(best["moves"], goal, text)),
                                    target_date_year=int(best["goal_year"]), target_chf=float(best["target"]),
                                    required_chf_per_year=float(best["required"]),
                                    available_chf_per_year=float(best["available"]))

            frontier.append(FrontierGoal(
                goal_id=gid, rate_basis="zero" if rate == 0.0 else "stated", rate=rate,
                holds_today=bool(g["holds_today"]), required_today_chf_per_year=_f(g.get("required_today")),
                available_today_chf_per_year=_f(g.get("available_today")),
                cheapest_effort=plan(g.get("cheapest_effort")), cheapest_goal_change=plan(g.get("cheapest_goal_change")),
                cheapest_combination=plan(g.get("cheapest_combination")),
                combinations_tried=int(g.get("combinations_tried") or 0),
                refused=_w(text["frontier_refused"]) if g.get("refused") else None))

    # -- what to ask next
    headlines = text["headlines"]
    nexts = tuple(NextQuestion(question_key=a.get("field") or a["code"], spread_chf=_f(a.get("impact")),
                               headline=headlines.get(a.get("impact_of")) if a.get("impact_of") else None,
                               question=_w(text["questions"][a["code"]]))
                  for a in q.get("asks_ranked") or [])

    # -- the gate
    gq = q.get("gate") or {}

    def item(i: dict[str, Any]) -> GateItem:
        return GateItem(code=i["code"], kind=i["kind"], title=_w(text["gate"][i["kind"]]),
                        fields=tuple(i.get("fields") or []))

    gate = Gate(stage=gq.get("stage", "report"), blocking=tuple(item(i) for i in gq.get("blocking") or []),
                optional=tuple(item(i) for i in gq.get("optional") or []), open_count=int(gq.get("open_count", 0)),
                optional_count=int(gq.get("optional_count", 0)))

    # -- assumptions and limits
    values: dict[str, Optional[float]] = {"withdrawal_rate": p.swr, "conversion_rate": G.PILLAR2_CONVERSION_RATE,
                                          "pension_interest": p.pension_interest, "wealth_tax_rate": p.wealth_tax_rate,
                                          "income_tax": p.tax_rate_max}
    if q["balance"]["let"]:
        values["rent_yield"] = p.y_R
    for key, v in adapted.assumptions.items():
        values[key] = v if key != "mortgage_rate" else p.i
    assumptions = tuple(Assumption(key=k, value=_f(v), unit=_ASSUMPTION_UNITS.get(k),
                                   text=_w(text["assumptions"][k]["text"]),
                                   replaced_by=_w(text["assumptions"][k]["replaced_by"]))
                        for k, v in values.items())
    lim = text["limits"]
    limits = [_w(lim["no_plan"])]
    if q.get("stop_work_age") is None and sub["raw"].get("work_plan"):
        limits.append(_w(lim["bridge"]))
    limits.append(_w(lim["retirement_span"]))
    if sub["params"].get("child_ages"):
        limits.append(_w(lim["child_price_base"]))
    if adapted.partner:
        limits.append(_w(lim["single_subject"]))
    limits.append(_w(lim["no_recommendation"]))

    # -- provenance
    hc_record = lbs_records["human-capital"]
    records = [RecordUse(record=name, source="lbs", version=sheet.calibration_version,
                         approved=approved(lbs_records[name]),
                         published_by=(lbs_records[name].get("_about") or {}).get("published_by"),
                         read_without_gate=not approved(lbs_records[name]))
               for name in ("human-capital", "property-funding") if name in lbs_records]
    records += [RecordUse(record=name, source="lbsim", version=calibration.version,
                          approved=approved(calibration.records[name]),
                          published_by=(calibration.records[name].get("_about") or {}).get("published_by"),
                          read_without_gate=not approved(calibration.records[name]))
                for name in ("social-insurance", "canton-tax", "findings-text")]
    cal_hash = calibration_hash(calibration)
    key = content_id("IDK", {"kind": "findings", "life_balance_sheet_id": sheet.artefact_id,
                             "calibration_hash": cal_hash, "engine_version": ENGINE_VERSION,
                             "contract_versions": CONTRACT_VERSIONS})
    provenance = Provenance(
        engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS, calibration_version=calibration.version,
        calibration_hash=cal_hash, idempotency_key=key,
        upstream={"lbs": LbsUpstream(artefact_id=sheet.artefact_id, request_hash=sheet.provenance.request_hash,
                                     calibration_version=sheet.calibration_version, sha256=sheet_sha256,
                                     url=lbs_url).model_dump(mode="json")},
        records=tuple(records))

    fields = dict(
        client_ref=sheet.client_ref, life_balance_sheet_id=sheet.artefact_id, as_of=sheet.as_of,
        calibration_version=calibration.version, inflation=inflation, principal=adapted.principal,
        earning_power=tuple(_earning_power(adapted, pid, hc_record, calibration, text, year_now)
                            for pid in adapted.adults),
        income_paths=_income_paths(q, adapted, text, inflation, year_now),
        zero_return=ZeroReturn(rate=0.0, note=_w(text["zero_return"])),
        findings=tuple(fired), schedule=schedule, unchecked=tuple(unchecked), input_checks=checks,
        frontier=tuple(frontier), next_questions=nexts, gate=gate, assumptions=assumptions, limits=tuple(limits),
        provenance=provenance)
    draft = LifeBalanceFindings(artefact_id="LSF-" + "0" * 16, **fields)
    body = draft.model_dump(mode="json", exclude={"artefact_id"})
    return LifeBalanceFindings(artefact_id=content_id("LSF", body), **fields)


def quantities(sheet: LbsSheet, request: LbsRequest, lbs_records: dict[str, dict[str, Any]],
               calibration: Calibration) -> tuple[_adapter.Adapted, dict[str, Any]]:
    """The adapter's submission and the port's raw quantities (for tests and the golden builders)."""
    adapted = _adapter.adapt(sheet, request, lbs_records, calibration)
    with tables(calibration):
        q = G.assemble(adapted.submission)
    return adapted, q
