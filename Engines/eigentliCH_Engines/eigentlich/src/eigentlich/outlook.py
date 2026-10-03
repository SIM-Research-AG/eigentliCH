"""lbsim's outlook as the client reads it (EIG-68): one language, names instead of ids, figures in words.

Pure: ``shape`` takes the outlook lbsim published (``GET /outlook``, checked by ``contracts.LbsimOutlook``), the
names the client gave the things lbsim refers to by id, the house's role names and the questionnaires' questions,
and returns what the "Aussichten" page and the home card show. Nothing is computed that lbsim did not compute: the
real figures are lbsim's own derived views (LBSIM-10), a chance is one per goal and Regime in the goal's own basis
(LBSIM-09), and the plan's figures for this period are framed as what the calculation assumes (owner, 29.09.2026),
never as a recommendation. No artefact id, run id, question key or reason key is in what this returns for people;
only the keys the page translates travel (severity, urgency, the kind of action, the Regime's key for the selector,
a goal's key of this page).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from . import rounding as rnd
from .pictures import capitals_over_time

SEVERITY_ORDER = {"blocking": 0, "high": 1, "medium": 2, "note": 3}
URGENCY_ORDER = {"now": 0, "months": 1, "year": 2, "watch": 3}

#: Where a finding's answering question is, for the draft's input names that are not the app's question keys.
ANSWER_ALIASES = {
    "legal_docs": "legal_will", "legal_documents": "legal_will", "savings": "annual_contribution",
    "amortisation": "properties", "amortisation_mode": "properties", "mortgage_fixed_until": "properties",
    "own_use_pct": "properties", "own_use_share": "properties", "stop_work_age": "work_until_age",
    "spend": "spend_now", "income_expected_full": "income_expected_full", "hours": "employment_time_basis",
}

#: The house's role names for pcp's role titles (the Allocation's roles are financial capital).
ROLE_KEYS = {"Gain": "growth", "Income": "income", "Stabilisation": "stabilisation", "Protection": "protection"}

_UNIT_WORDS = {
    "de": {"years": "Jahre", "hours_per_week": "Std./Woche", "per_year": "pro Jahr"},
    "en": {"years": "years", "hours_per_week": "hours a week", "per_year": "a year"},
}


def _w(value: Any, lang: str) -> Optional[str]:
    """One side of a ``{de, en}`` pair, never the other language's."""
    if isinstance(value, dict):
        text = value.get(lang)
        return text if isinstance(text, str) and text.strip() else None
    return value if isinstance(value, str) else None


def chf(value: Optional[float], lang: str = "de") -> Optional[str]:
    """An amount in words, rounded for display (ROUNDING.md, EIG-73): CHF 61’000, CHF 1.35 Mio."""
    return rnd.money(value, lang)


def figure_text(fig: dict[str, Any], lang: str, basis: str) -> str:
    """A finding's figure in words, rounded for display (ROUNDING.md, EIG-73): CHF 61’000, 40 %, 3 Jahre. A
    nominal figure on a page shown in today's francs says so (lbsim states its findings nominal, REP-36 reads them
    the same way)."""
    value, unit = fig.get("value"), fig.get("unit")
    if value is None:
        return "offen" if lang == "de" else "open"
    if unit in ("chf", "chf_per_year"):
        text = chf(value, lang)
    elif unit == "share":
        text = rnd.share(value, lang)
    elif unit == "years":
        text = f"{rnd.count(value, lang)} {_UNIT_WORDS[lang]['years']}"
    elif unit == "hours_per_week":
        text = f"{rnd.count(value, lang)} {_UNIT_WORDS[lang]['hours_per_week']}"
    else:
        text = rnd.count(value, lang)
    if basis == "real" and fig.get("basis") == "nominal":
        text += " (nominal)"
    return text


def fill(template: str, figures: dict[str, Any], lang: str, basis: str) -> str:
    return re.sub(r"\{([a-z0-9_]+)\}", lambda m: figure_text(figures.get(m.group(1)) or {}, lang, basis)
                  if m.group(1) in figures else m.group(0), template or "")


class Questions:
    """The questionnaires' question keys and texts, for the links from a finding to the question answering it."""

    def __init__(self, bodies: dict[str, dict[str, Any]]):
        self.where: dict[str, tuple[str, dict[str, Any]]] = {}
        for name, body in bodies.items():
            for q in body.get("questions") or []:
                if q.get("scope") in (None, "client"):
                    self.where.setdefault(q["key"], (name, q))

    def link(self, key: str, lang: str) -> Optional[dict[str, Any]]:
        key = ANSWER_ALIASES.get(key, key)
        if key not in self.where:
            return None
        name, q = self.where[key]
        return {"href": f"#/q/{name}/sections/{key}", "question": _w(q.get("question"), lang)}

    def links(self, keys, lang: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for k in keys or ():
            link = self.link(k, lang)
            if link and link["href"] not in seen:
                seen.add(link["href"])
                out.append(link)
        return out


def _earning(ep: dict[str, Any], names: dict[str, str], lang: str) -> dict[str, Any]:
    modelled = ep.get("modelled") or {}
    resp = modelled.get("responsibility") or {}
    stated = ep.get("stated") or {}
    current = ep.get("current") or {}
    edu = ep.get("education") or {}
    return {
        "name": names.get(ep.get("person_id")) or None,
        "available": ep.get("status") == "available",
        "reason": _w(ep.get("reason"), lang),
        "level_basis": ep.get("level_basis"),
        "modelled_full_time_chf": modelled.get("full_time_chf_per_year"),
        "stated_chf": stated.get("expected_full_pensum_income_chf_per_year"),
        "stated_from_age": stated.get("from_age"),
        "current_income_chf": current.get("gross_income_chf_per_year"),
        "pensum": current.get("pensum"),
        "responsibility": _w(resp.get("label"), lang),
        "responsibility_stated": resp.get("stated"),
        "education": {"status": edu.get("status"), "end_year": edu.get("end_year")},
        "capacity_basis": (ep.get("health") or {}).get("capacity_basis"),
        "caveats": [t for t in (_w(c, lang) for c in ep.get("caveats") or []) if t],
    }


def _paths_rows(ip: dict[str, Any], goals: dict[str, str], lang: str) -> dict[str, Any]:
    real = {r["goal_id"]: r for r in (((ip.get("views") or {}).get("real") or {}).get("saving_need") or [])}
    rows = []
    for need in ip.get("saving_need") or []:
        r = real.get(need["goal_id"]) or {}
        rows.append({"goal": goals.get(need["goal_id"]), "date": need.get("target_date"), "holds": need.get("holds"),
                     "years": need.get("years"),
                     "nominal": {"target_chf": need.get("target_chf"),
                                 "saving_chf_per_year": need.get("zero_return_saving_chf_per_year"),
                                 "free_chf_per_year": need.get("free_cash_chf_per_year")},
                     "real": {"target_chf": r.get("target_chf"),
                              "saving_chf_per_year": r.get("zero_return_saving_chf_per_year"),
                              "free_chf_per_year": r.get("free_cash_chf_per_year")}})
    return {"name": _w(ip.get("name"), lang), "note": _w(ip.get("note"), lang), "level_basis": ip.get("level_basis"),
            "code": ip.get("code"), "goals": rows}


def _findings(f: dict[str, Any], q: Questions, lang: str, basis: str) -> list[dict[str, Any]]:
    out = []
    for x in f.get("findings") or []:
        words = (x.get("text") or {}).get(lang) or {}
        figures = x.get("figures") or {}
        out.append({"severity": x.get("severity"), "urgency": x.get("urgency"),
                    "action_kind": x.get("action_kind"),
                    **{part: fill(words.get(part) or "", figures, lang, basis) for part in ("title", "trigger", "why", "action")},
                    "links": q.links(x.get("answers"), lang)})
    out.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), URGENCY_ORDER.get(x["urgency"], 9)))
    return out


def _regime(r: dict[str, Any], goals: dict[str, str], lang: str, persons: Optional[dict[str, str]] = None,
            withheld: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
    return {"key": r.get("key"), "label": _w(r.get("label"), lang), "kind": r.get("kind"),
            "goals": [{"goal_id": g.get("goal_id"), "name": goals.get(g.get("goal_id")), "kind": g.get("kind"),
                       "measure": g.get("measure"), "chance": g.get("chance"), "chance_basis": g.get("chance_basis"),
                       "target": g.get("target"), "n_reached": g.get("n_reached"),
                       "median_shortfall_chf": g.get("median_shortfall_chf")} for g in r.get("goals") or []],
            "bands": r.get("bands") or {},
            # the principal's expertise, network and health over time (lbsim, EIG-71): the name, not the id; the
            # health band left out when health is withheld (K3)
            "capitals": capitals_over_time(r.get("capitals"), persons or {}, lang, set(withheld))}


def _allocation(av: dict[str, Any], role_name: Callable[[str], str]) -> dict[str, Any]:
    by_role = av.get("by_role") or {}
    return {"mandate_name": av.get("mandate_name"), "currency": av.get("currency"),
            "allocation_basis": av.get("allocation_basis"), "date": av.get("date"),
            "instruments": [{"name": i.get("name"), "role": role_name(i.get("role")), "weight": i.get("weight")}
                            for i in av.get("instruments") or []],
            "by_role": [{"role": role_name(k), "weight": by_role.get(k)} for k in ROLE_KEYS if k in by_role],
            "curves": {b: {"target": (av.get("curves") or {}).get(b, {}).get("target"),
                           "achieved": (av.get("curves") or {}).get(b, {}).get("achieved"),
                           "derived": bool((av.get("curves") or {}).get(b, {}).get("derived"))}
                       for b in ("nominal", "real")},
            "state_probability": av.get("state_probability")}


def _plan(plan: dict[str, Any], goals: dict[str, str], lang: str) -> dict[str, Any]:
    out: dict[str, Any] = {"state": plan.get("state"), "reason": _w(plan.get("reason"), lang),
                           "elapsed_s": plan.get("elapsed_s"), "budget_s": plan.get("budget_s")}
    art = plan.get("artefact")
    if plan.get("state") == "ready" and isinstance(art, dict):
        goal = art.get("goal") or {}
        chance = art.get("chance") or {}
        horizon = art.get("horizon") or {}
        reach = art.get("reachable") or None
        out["ready"] = {"framing": _w(art.get("framing"), lang), "action_now": art.get("action_now") or {},
                        "outcome": art.get("outcome"), "goal": goals.get(goal.get("goal_id")),
                        "goal_id": goal.get("goal_id"), "confidence": goal.get("confidence"),
                        "chance_out_of_sample": chance.get("out_of_sample"), "chance_in_sample": chance.get("in_sample"),
                        "reachable_chf": (reach or {}).get("amount_chf"),
                        "solved_years": horizon.get("solved_years"), "total_years": horizon.get("total_years")}
    return out


def shape(raw: dict[str, Any], *, language: str, basis: str, persons: dict[str, str], goals: dict[str, str],
          role_name: Callable[[str], str], questions: Questions, mandate_goal: Optional[str],
          withheld: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
    lang = "en" if language == "en" else "de"
    f = raw.get("findings") or {}
    p = raw.get("paths") or None
    plan = _plan(raw.get("plan") or {}, goals, lang)
    unchecked = []
    for u in f.get("unchecked") or []:
        if u.get("answered_by") == "plan" and plan.get("ready"):
            continue
        unchecked.append({"reason": _w(u.get("reason"), lang), "links": questions.links(u.get("missing"), lang)})
    out: dict[str, Any] = {
        "available": True, "language": lang, "basis": basis if basis in ("nominal", "real") else "nominal",
        "as_of": f.get("as_of"),
        "earning_power": [_earning(e, persons, lang) for e in f.get("earning_power") or []],
        "income_paths": [{**_paths_rows(ip, goals, lang), "person": persons.get(ip.get("person_id"))}
                         for ip in f.get("income_paths") or []],
        "zero_return_note": _w((f.get("zero_return") or {}).get("note"), lang),
        "findings": _findings(f, questions, lang, basis),
        "schedule": [{"when": s.get("when"), "label": _w(s.get("label"), lang),
                      "titles": [_w(((x.get("text") or {}).get(lang) or {}).get("title"), lang) or ""
                                 for x in f.get("findings") or [] if x.get("code") in (s.get("codes") or [])]}
                     for s in f.get("schedule") or []],
        "unchecked": unchecked,
        "assumptions": [{"text": _w(a.get("text"), lang), "value": a.get("value"), "unit": a.get("unit")}
                        for a in f.get("assumptions") or []],
        "limits": [t for t in (_w(x, lang) for x in f.get("limits") or []) if t],
        "paths": None,
        "plan": plan,
    }
    if p:
        regimes = [_regime(r, goals, lang, persons, withheld) for r in p.get("regimes") or []]
        base = next((r for r in regimes if r["key"] == "base"), regimes[0] if regimes else None)
        ids = [g["goal_id"] for g in (base or {}).get("goals") or []]
        designated = next((g for g in (plan.get("ready") or {}, {"goal_id": mandate_goal}) if g.get("goal_id") in ids),
                          None)
        chosen = designated["goal_id"] if designated else (ids[0] if ids else None)
        out["paths"] = {"start_year": p.get("start_year"), "horizon_years": p.get("horizon_years"),
                        "n_paths": p.get("n_paths"), "regimes": regimes, "designated_goal_id": chosen,
                        "allocation": _allocation(p.get("allocation_view") or {}, role_name),
                        "fallback": _w((p.get("policy") or {}).get("fallback"), lang)}
    # No id leaves: a goal is tied to its fan by a key of this page alone (goal1, goal2, ...).
    keys: dict[str, str] = {}

    def key(gid: Optional[str]) -> Optional[str]:
        if gid is None:
            return None
        return keys.setdefault(gid, f"goal{len(keys) + 1}")

    for r in (out["paths"] or {}).get("regimes") or []:
        for g in r["goals"]:
            g["goal_id"] = key(g["goal_id"])
    if out["paths"]:
        out["paths"]["designated_goal_id"] = key(out["paths"]["designated_goal_id"])
    if plan.get("ready"):
        plan["ready"]["goal_id"] = key(plan["ready"]["goal_id"])
    return out


def card(shaped: dict[str, Any]) -> dict[str, Any]:
    """The home page's card: the designated goal's chance under today's assessment, the top three actions, the
    plan's state."""
    p = shaped.get("paths") or {}
    base = next((r for r in p.get("regimes") or [] if r["key"] == "base"), None)
    goal = next((g for g in (base or {}).get("goals") or [] if g["goal_id"] == p.get("designated_goal_id")), None)
    return {"available": True,
            "goal": {"name": goal["name"], "chance": goal["chance"], "chance_basis": goal["chance_basis"]} if goal else None,
            "actions": [{"title": x["title"], "action": x["action"], "urgency": x["urgency"]}
                        for x in (shaped.get("findings") or [])[:3]],
            "plan": {"state": (shaped.get("plan") or {}).get("state"),
                     "elapsed_s": (shaped.get("plan") or {}).get("elapsed_s"),
                     "budget_s": (shaped.get("plan") or {}).get("budget_s")}}
