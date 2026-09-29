"""Golden layer B, the corrected behaviour (LBS-24, LBS-28): shared by ``dev/build_golden_corrected.py``
(which freezes it) and ``tests/test_golden_corrected.py`` (which checks it).

Layer A (``golden/cases``, ``golden/expected``) is the prototype's own output and stays the reference for the
reproduction mode (calibrations 1.0.0 and 1.1.0). Layer B has no outside reference: it is lbs's own output,
frozen as a regression reference, in two steps, each with the exact list of figures that differ from the step
before and which correction moves each of them:

* ``golden/corrected/``: calibration 1.2.0 against the reproduction 1.1.0 (the four corrections of LBS-24),
  over the layer-A cases and the quirk cases ``q-*``;
* ``golden/corrected/1.3.0/``: calibration 1.3.0 against 1.2.0 (the three corrections of LBS-28), over the
  layer-A cases, the quirk cases and the cases ``r-*`` of that step;
* ``golden/corrected/1.4.0/``: calibration 1.4.0 against 1.3.0 (the nominal and real view, LBS-31 to LBS-35),
  over every earlier case and the cases ``v-*`` of that step. Its changes are attributed by what the leaf is
  (``classify_14``), since the real view is one block, not a set of flags;
* ``golden/corrected/1.5.0/``: calibration 1.5.0 against 1.4.0 (the owner's CHF inflation of 1.0 % and the
  approved plausibility table, LBS-36 to LBS-38), over every earlier case. Every changed leaf is moved by one of
  the two decisions (``classify_15``), and named by the kind of figure it is.

A sheet is compared as a flat map from a path to a leaf: everything except ``artefact_id``, ``provenance`` and
``calibration_version`` (which name the build, not the household), lists of persons and goals keyed by their
id, the grid by role and capital type, and the gaps by section, input and kind.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lbs.calibration import APPROVED, CORRECTED, CORRECTED_1_3, CORRECTED_1_4, CORRECTED_1_5
from lbs.contracts import LATER_CORRECTIONS, Calibration, Corrections, LifeBalanceSheetRequest
from lbs.service import build_sheet

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden"
LAYER_B = GOLDEN / "corrected"
LAYER_B13 = LAYER_B / "1.3.0"
LAYER_B14 = LAYER_B / "1.4.0"
LAYER_B15 = LAYER_B / "1.5.0"
TOL = 1e-9

#: The four corrections of 1.2.0 (LBS-24), by their field names on ``Corrections``.
QUIRKS: tuple[str, ...] = tuple(n for n in Corrections.model_fields if n not in LATER_CORRECTIONS)
#: The three of 1.3.0 (LBS-28).
LATER: tuple[str, ...] = LATER_CORRECTIONS

#: What each quirk case is for; the reason every changed figure carries.
CASE_ABOUT = {
    "q-ceiling": ("the goal needs 850 percent a year: above the prototype's effective 800 percent, below the "
                  "stated 1000 percent ceiling; the contribution is stated as 0"),
    "q-horizon": "no goal is dated; plan_until_age 65 at age 55 is a 10-year horizon, not one of 65 years",
    "q-zero-income": "an income position of 0 is a stated zero (unpaid leave), not an unknown income",
    "q-no-vessel": "a funding stock of 100'000 states no vessel: neither hard equity nor free wealth",
}

#: What each case of the 1.3.0 step is for.
CASE_ABOUT_13 = {
    "r-human-capital": ("a human-capital stock of 150'000 in chf (a training claim) funds the property goal: "
                        "neither free wealth for the capacity nor equity for the deposit"),
    "r-paid-mortgage": "a stated mortgage of 0 is a paid-off mortgage: a debt service of 0, not an unknown one",
    "r-share-stated": ("one yearly saving of 30'000 for three goals, the designated goal's stated share 0.4: "
                       "12'000 a year toward it"),
    "r-share-missing": ("one yearly saving of 30'000 for three goals, the designated goal's share not stated and "
                        "the others' 0.25 and 0.35: at most 40 percent, a lower bound on the required return, "
                        "and a gap"),
}

#: What each case of the 1.4.0 step is for.
CASE_ABOUT_14 = {
    "v-worked-example": ("the design note's worked example: CHF 400'000 in today's francs (not stated, decision 7) "
                         "in 20 years, 150'000 now, 12'000 a year fixed; under 1.4.0 at the calibrated CHF inflation"),
    "v-future": "the same goal stated in future francs: the nominal figures of 1.3.0, and a real view beside them",
    "v-indexed": ("the same goal stated in today's francs with the contribution indexed: the real required return is "
                  "the one of the problem without inflation"),
    "v-not-realistic": ("125'000 in future francs in 1.25 years from 100'000 and 4'000 a year: about 15 % a year, "
                        "feasible and not realistic, with the levers"),
    "v-retirement": ("a need of 60'000 a year in today's francs against AHV and a nominal BVG pension, compared in "
                     "today's francs"),
}

#: The four kinds of change of the 1.4.0 step (LBS-31 to LBS-35), in the order ``classify_14`` tries them.
WHY_14 = {
    "plausibility": "the plausibility judgement of the required return (LBS-34), new",
    "real_view": "the real view and the basis of each figure, new and additive (LBS-31, LBS-35)",
    "retirement_in_todays_francs": ("the retirement comparison in today's francs: the need read in today's francs "
                                    "and the nominal BVG pension deflated from its first year (LBS-33)"),
    "amounts_in_todays_francs": ("a goal amount in today's francs unless stated (decision 7), inflated to its date, "
                                 "and a contribution fixed or indexed (decision 9): the mandate's target, required "
                                 "return, curve and notes in francs of the target date (LBS-31)"),
}

#: The two decisions of the 1.5.0 step (LBS-36, LBS-37), in the order ``classify_15`` tries them.
WHY_15 = {
    "plausibility_table_approved": ("the plausibility table approved by the owner unchanged (LBS-37): the source "
                                    "line of the ceiling says so; no ceiling moves"),
    "chf_inflation_1_percent": ("the CHF long-run inflation of 1.0 % a year, the midpoint of the SNB's 0 to 2 % "
                                "range, in place of the measured 0.50 % (LBS-36): every figure converted between "
                                "today's francs and francs of a date moves with it"),
}

#: The kind of figure a changed leaf of the 1.5.0 step is, for the reader of ``changes.json``.
FIGURE_15 = {
    "inflation_assumption": "the assumption itself: rate, log rate, source (real_view.inflation)",
    "goal_amounts": "a goal's amount in the other basis and its price level (real_view.goals)",
    "required_return": "the mandate's target, required return (nominal and real), curve and notes",
    "plausibility": "the plausibility judgement: the nominal ceiling, the real required return, the levers",
    "retirement": "the retirement comparison in today's francs (the BVG pension deflated) and its nominal view",
    "property": "a property price stated in future francs, deflated to today",
    "other": "anything else",
}

WHY = {
    "required_return_search_reaches_its_ceiling": (
        "the required-return search now tests its stated 1000 percent ceiling; the prototype stopped at 800"),
    "capacity_horizon_is_years_to_the_planned_age": (
        "without a dated goal the capacity horizon is plan_until_age less the age, in years; the prototype used "
        "the age itself"),
    "zero_income_is_a_stated_zero": (
        "a stated zero income is zero; the prototype read it as no income"),
    "unstated_vessel_is_a_gap": (
        "a stock without a vessel is a named gap, neither hard equity nor free wealth; the prototype counted it "
        "as both"),
}

WHY_13 = {
    "human_capital_is_never_free_wealth": (
        "a human-capital stock in chf is human capital only, never free wealth or equity; before, the capacity "
        "counted it as free"),
    "zero_mortgage_is_a_stated_zero": (
        "a stated mortgage of 0 is a paid-off mortgage, a debt service of 0; before, it read as no answer"),
    "contribution_is_split_by_goal_share": (
        "the yearly saving is split between the goals by their stated shares, and the designated goal's missing "
        "share, with other goals in the request, is a gap; before, all of it went to the designated goal"),
}


def layer_a_names() -> list[str]:
    return sorted(p.stem for p in (GOLDEN / "cases").glob("*.json"))


def layer_b_names() -> list[str]:
    return sorted(p.stem for p in (LAYER_B / "cases").glob("*.json"))


def layer_b13_names() -> list[str]:
    return sorted(p.stem for p in (LAYER_B13 / "cases").glob("*.json"))


def layer_b14_names() -> list[str]:
    return sorted(p.stem for p in (LAYER_B14 / "cases").glob("*.json"))


def layer_b15_names() -> list[str]:
    """Every case of the earlier steps; the 1.5.0 step adds none (the worked example is ``v-worked-example``)."""
    return layer_a_names() + layer_b_names() + layer_b13_names() + layer_b14_names()


def request_of(name: str) -> dict:
    folder = {"q-": LAYER_B / "cases", "r-": LAYER_B13 / "cases", "v-": LAYER_B14 / "cases"}.get(name[:2],
                                                                                                  GOLDEN / "cases")
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


def only(quirk: str) -> Calibration:
    """The step's base with a single correction switched on: which figures that correction alone moves. A 1.2.0
    correction on 1.1.0; a 1.3.0 correction (LBS-28) on 1.2.0."""
    if quirk in LATER:
        flags = {**CORRECTED.corrections.model_dump(), **{q: q == quirk for q in LATER}}
        return Calibration.model_validate({**CORRECTED.model_dump(), "contract_version": "lbs-calibration@1.2.0",
                                           "version": f"1.2.0-only.{LATER.index(quirk)}",
                                           "parent_version": CORRECTED.version, "corrections": flags})
    flags = {q: q == quirk for q in QUIRKS}
    return Calibration.model_validate({**APPROVED.model_dump(), "version": f"1.1.0-only.{QUIRKS.index(quirk)}",
                                       "parent_version": APPROVED.version, "corrections": flags})


def _key(item: dict, index: int) -> str:
    if "person_id" in item:
        return item["person_id"]
    if "goal_id" in item:
        return item["goal_id"]
    if "field" in item:
        return item["field"]
    if "age" in item and "credit_rate" in item:
        return f"age {item['age']}"
    if "role" in item and "capital_type" in item:
        return f"{item['role']}.{item['capital_type']}"
    return str(index)


def _walk(value: Any, path: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if not value:
            out[path] = {}
        for k in sorted(value):
            _walk(value[k], f"{path}.{k}" if path else k, out)
    elif isinstance(value, list):
        if not value:
            out[path] = []
        for i, item in enumerate(value):
            key = _key(item, i) if isinstance(item, dict) else str(i)
            _walk(item, f"{path}[{key}]", out)
    else:
        out[path] = value


def flatten(sheet: Any) -> dict[str, Any]:
    d = sheet.model_dump(mode="json")
    for k in ("artefact_id", "provenance", "calibration_version"):
        d.pop(k)
    gaps = d.pop("gaps")
    out: dict[str, Any] = {}
    _walk(d, "", out)
    for g in gaps:
        out[f"gaps[{g['section']}|{g['input']}|{g['kind']}]"] = g["reason"]
    return out


def same(a: Any, b: Any) -> bool:
    """Numbers to TOL relative (absolute near zero), everything else exactly."""
    def number(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if number(a) and number(b):
        return abs(float(a) - float(b)) <= TOL * max(1.0, abs(float(b)))
    return type(a) is type(b) and a == b


def sheet_of(name: str, cal: Calibration) -> dict[str, Any]:
    return flatten(build_sheet(LifeBalanceSheetRequest.model_validate(request_of(name)), cal))


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(k for k in set(a) | set(b) if k not in a or k not in b or not same(a[k], b[k]))


def changes(name: str, step: str = "1.2.0") -> list[dict[str, Any]]:
    """Every path whose leaf differs between a step's base and its calibration, with the correction or
    corrections that move it on their own: step ``1.2.0`` is 1.1.0 (the reproduction) to 1.2.0, step ``1.3.0``
    is 1.2.0 to 1.3.0. The before and after are named ``reproduction`` and ``corrected`` in step 1.2.0 and
    ``before`` (1.2.0) and ``after`` (1.3.0) in step 1.3.0."""
    base, cal, flags = (APPROVED, CORRECTED, QUIRKS) if step == "1.2.0" else (CORRECTED, CORRECTED_1_3, LATER)
    first, second = step_keys(step)
    before, after = sheet_of(name, base), sheet_of(name, cal)
    alone = {q: set(diff(before, sheet_of(name, only(q)))) for q in flags}
    out = []
    for path in diff(before, after):
        by = [q for q in flags if path in alone[q]]
        out.append({"path": path, first: before.get(path, "<absent>"), second: after.get(path, "<absent>"),
                    "by": by or ["the corrections together"]})
    return out


def step_keys(step: str) -> tuple[str, str]:
    return ("reproduction", "corrected") if step == "1.2.0" else ("before", "after")


def classify_14(path: str, before: dict[str, Any]) -> str:
    """Which part of the 1.4.0 step moves a leaf. A leaf new in 1.4.0 is the plausibility judgement or the real
    view; a changed retirement leaf is the comparison in today's francs; every other changed leaf (the mandate's
    target, required return, curve and notes, a property price stated in future francs) is decision 7 and 9."""
    if path.startswith("mandate_proposal.plausibility"):
        return "plausibility"
    if path not in before:
        return "real_view"
    if path.startswith("retirement[") or path.startswith("gaps[retirement."):
        return "retirement_in_todays_francs"
    return "amounts_in_todays_francs"


def changes_14(name: str) -> list[dict[str, Any]]:
    """Every path whose leaf differs between 1.3.0 and 1.4.0, with the part of the step that moves it."""
    before, after = sheet_of(name, CORRECTED_1_3), sheet_of(name, CORRECTED_1_4)
    return [{"path": path, "before": before.get(path, "<absent>"), "after": after.get(path, "<absent>"),
             "by": [classify_14(path, before)]} for path in diff(before, after)]


def classify_15(path: str) -> str:
    """Which decision of the 1.5.0 step moves a leaf: the approval moves only the ceiling's source line, the CHF
    inflation everything else."""
    if path.endswith("plausibility.ceiling_source"):
        return "plausibility_table_approved"
    return "chf_inflation_1_percent"


def figure_15(path: str) -> str:
    if path.startswith("real_view.inflation"):
        return "inflation_assumption"
    if path.startswith("real_view.goals"):
        return "goal_amounts"
    if path.startswith("mandate_proposal.plausibility"):
        return "plausibility"
    if path.startswith("mandate_proposal"):
        return "required_return"
    if path.startswith("retirement[") or path.startswith("gaps[retirement."):
        return "retirement"
    if path.startswith("property[") or path.startswith("gaps[property."):
        return "property"
    return "other"


def changes_15(name: str) -> list[dict[str, Any]]:
    """Every path whose leaf differs between 1.4.0 and 1.5.0, with the decision that moves it and the kind of
    figure it is."""
    before, after = sheet_of(name, CORRECTED_1_4), sheet_of(name, CORRECTED_1_5)
    return [{"path": path, "before": before.get(path, "<absent>"), "after": after.get(path, "<absent>"),
             "by": [classify_15(path)], "figure": figure_15(path)} for path in diff(before, after)]


def required_returns_15(name: str) -> dict[str, Any] | None:
    """The designated goal's required return under 1.4.0 and 1.5.0, nominal and real, with the move in points;
    ``None`` where the case has no required return."""
    before, after = sheet_of(name, CORRECTED_1_4), sheet_of(name, CORRECTED_1_5)
    keys = {"nominal": "mandate_proposal.required_return", "real": "mandate_proposal.views.real.required_return",
            "target_chf": "mandate_proposal.target_chf"}
    if not isinstance(before.get(keys["nominal"]), (int, float)):
        return None
    out: dict[str, Any] = {}
    for view in ("nominal", "real", "target_chf"):
        b, a = before.get(keys[view]), after.get(keys[view])
        out[view] = {"1.4.0": b, "1.5.0": a,
                     ("move_points" if view != "target_chf" else "move_chf"):
                         (a - b) * (100 if view != "target_chf" else 1)}
    goal = before.get("mandate_proposal.goal_id")
    out["goal_id"] = goal
    out["amount_basis"] = after.get(f"real_view.goals[{goal}].amount_basis")
    out["contribution_indexed"] = after.get("real_view.contribution_indexed")
    out["judgement"] = {"1.4.0": before.get("mandate_proposal.plausibility.judgement"),
                        "1.5.0": after.get("mandate_proposal.plausibility.judgement")}
    return out
