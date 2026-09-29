"""The pure core: facts from artefacts, the sections, the changes, the prose prompt and its checks.

No I/O, no HTTP, no clock. ``service.py`` fetches, calls the model and stores; nothing here calls out.

**The code owns every figure** (prior art ``befund.py``, ``dossier.py``): each figure the report states is a
:class:`Fact` read from a published artefact, with the engine, the artefact id and the JSON path it was read
from, or derived by the code (a count, a change) with the sources it was derived from. The model is handed one
section's facts at a time and writes the connecting sentences for that section only; every number in what it
writes is checked against **that section's** facts (``desktop/sectionprose.py``: a correct figure under the
wrong label is the failure observed, and a narrow allowed set is what catches it). A draft that advises, names
another currency, echoes the prompt, shouts, or is too short or too long is rejected before it is checked.

**Adding an engine** is one :class:`Extractor`: a mirror contract, the path its artefacts are read from, and a
function from the artefact to facts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Iterable, Optional, Sequence

from pydantic import BaseModel

from . import vocabulary as voc
from .contracts import (
    Allocation,
    Calibration,
    DisplayFact,
    Fact,
    FactSource,
    LbsAhv,
    LbsBvg,
    LbsCoupleCap,
    LbsMandateProposal,
    LbsRiskProfile,
    LifeBalanceFindings,
    LifeBalancePaths,
    LifeBalancePlan,
    LifeBalanceSheet,
    Report,
)


class EngineError(ValueError):
    """The inputs cannot be reported as given. The message says why."""


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Formatting: the house style of dossier.py (thin-space thousands, decimal comma, "−")
# ---------------------------------------------------------------------------

def _money(x: float, lang: str) -> str:
    text = f"{abs(x):,.0f}"
    text = text.replace(",", " ") if lang == "de" else text
    return ("−" if x < 0 else "") + "CHF " + text


def _share(x: float, lang: str, digits: int = 1) -> str:
    text = f"{abs(x) * 100:.{digits}f}"
    sign = "−" if x < 0 else ""
    return f"{sign}{text.replace('.', ',')} %" if lang == "de" else f"{sign}{text}%"


def _number(x: float, lang: str, digits: int = 2) -> str:
    text = f"{abs(x):.{digits}f}"
    sign = "−" if x < 0 else ""
    return sign + (text.replace(".", ",") if lang == "de" else text)


_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")


def _date(iso: str, lang: str) -> str:
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day:02d}.{d.month:02d}.{d.year}" if lang == "de" else f"{d.day} {_MONTHS_EN[d.month - 1]} {d.year}"


def fmt(value: Any, unit: str, lang: str) -> str:
    """How a fact is printed. Every figure on the page goes through here."""
    if value is None:
        return "–"
    if unit == "flag":
        return ("ja" if value else "nein") if lang == "de" else ("yes" if value else "no")
    if unit == "chf":
        return _money(float(value), lang)
    if unit == "chf_per_year":
        return _money(float(value), lang) + (" pro Jahr" if lang == "de" else " a year")
    if unit == "share":
        return _share(float(value), lang)
    if unit == "count":
        return str(int(value))
    if unit == "number":
        return _number(float(value), lang)
    if unit == "date":
        return _date(str(value), lang)
    return str(value)


def fmt_change(value: float, unit: str, lang: str) -> str:
    """A signed difference: CHF amounts in francs, shares in percentage points."""
    sign = "+" if value > 0 else ""
    if unit == "share":
        pts = f"{abs(value) * 100:.1f}"
        pts = pts.replace(".", ",") if lang == "de" else pts
        head = "+" if value > 0 else "−" if value < 0 else ""
        return f"{head}{pts} " + ("Prozentpunkte" if lang == "de" else "percentage points")
    if unit in ("chf", "chf_per_year"):
        return (sign if value > 0 else "") + _money(value, lang)
    if unit == "count":
        return f"{sign}{int(value)}"
    return sign + _number(value, lang)


# ---------------------------------------------------------------------------
# Vocabulary: the data keeps its keys, only the rendering is translated (dossier.py)
# ---------------------------------------------------------------------------

CAPITAL = {"de": {"human": "Humankapital", "financial": "Finanzkapital"},
           "en": {"human": "human capital", "financial": "financial capital"}}
VESSEL = {
    "de": {"free": "frei verfügbar", "pillar_2": "2. Säule", "pillar_3a": "Säule 3a", "real_asset": "Realwerte",
           "not_stated": "ohne Angabe"},
    "en": {"free": "freely available", "pillar_2": "2nd pillar", "pillar_3a": "pillar 3a", "real_asset": "real assets",
           "not_stated": "not stated"},
}
RELEASE = {"de": {"unreleased": "nicht freigegeben"}, "en": {"unreleased": "not released"}}


def role_label(role: str, lang: str, capital_type: str = "financial") -> str:
    """The house's name of a role (``vocabulary.ROLE_NAMES``, REP-24)."""
    return voc.role_name(role, lang, capital_type)


LABELS: dict[str, dict[str, str]] = {
    "pcp.mandate_name": {"de": "Mandat", "en": "Mandate"},
    "pcp.date": {"de": "Stichtag der Allokation", "en": "Allocation date"},
    "pcp.release_state": {"de": "Status", "en": "Status"},
    "pcp.budget_met": {"de": "Budget eingehalten (Summe der Gewichte)", "en": "Budget met (weights sum to one)"},
    "pcp.positions_held": {"de": "Bausteine mit Gewicht", "en": "Building blocks with weight"},
    "pcp.universe_size": {"de": "Bausteine im Universum", "en": "Building blocks in the universe"},
    "pcp.objective": {"de": "Zielfunktion", "en": "Objective"},
    "pcp.objective_floor": {"de": "Zielfunktion ohne Allokation", "en": "Objective with nothing allocated"},
    "pcp.weight_leverage": {"de": "Anteil, den die Gewichte bewegen", "en": "Share the weights move"},
    "pcp.solver_method": {"de": "Verfahren", "en": "Method"},
    "pcp.solver_converged": {"de": "Lösung konvergiert", "en": "Solve converged"},
    "pcp.constraint_rows": {"de": "Nebenbedingungen", "en": "Constraint rows"},
    "pcp.binding_rows": {"de": "davon bindend", "en": "of which binding"},
    "pcp.weak_share": {"de": "Gewicht auf geliehenen oder gesetzten Profilen",
                       "en": "Weight on borrowed or seeded profiles"},
    "lbs.totals.total_assets": {"de": "Vermögen gesamt", "en": "Total assets"},
    "lbs.totals.financial_assets": {"de": "Finanzvermögen", "en": "Financial assets"},
    "lbs.totals.human_assets": {"de": "Humanvermögen", "en": "Human assets"},
    "lbs.totals.liabilities": {"de": "Verbindlichkeiten", "en": "Liabilities"},
    "lbs.totals.net_worth": {"de": "Reinvermögen", "en": "Net worth"},
    "lbs.totals.drawable": {"de": "Entnahmefähig", "en": "Drawable"},
    "lbs.totals.identity_holds": {"de": "Bilanzgleichung erfüllt", "en": "Balance identity holds"},
    "lbs.totals.household_income": {"de": "Haushaltseinkommen", "en": "Household income"},
    "lbs.household.adults": {"de": "Erwachsene", "en": "Adults"},
    "lbs.household.dependants": {"de": "Abhängige", "en": "Dependants"},
    "lbs.household.composition_as_of": {"de": "Zusammensetzung erfasst am", "en": "Composition recorded on"},
    "sources.as_of": {"de": "Stand", "en": "As of"},
    "changes.unchanged": {"de": "Unveränderte Zahlen", "en": "Figures unchanged"},
    "changes.added": {"de": "Neu im Bericht", "en": "New in this report"},
    "changes.removed": {"de": "Nicht mehr im Bericht", "en": "No longer in this report"},
}


def label(fact_id: str, lang: str) -> str:
    return LABELS.get(fact_id, {}).get(lang, fact_id)


# ---------------------------------------------------------------------------
# Sections: the order is fixed and is an argument (dossier.py)
# ---------------------------------------------------------------------------

#: Where the household stands, what it has coming in, what arrives without a decision (pensions), what its
#: goals need, the proposal lbs derives, then what the allocation is and how it came about, then what the
#: report cannot say and where every figure came from. An update states its changes first.
SECTIONS: tuple[tuple[str, dict[str, str]], ...] = (
    ("changes", {"de": "Was sich verändert hat", "en": "What has changed"}),
    ("household", {"de": "Der Haushalt", "en": "The household"}),
    ("balance_sheet", {"de": "Die Bilanz", "en": "The balance sheet"}),
    ("grid", {"de": "Die Rollen der Bilanz", "en": "The roles of the balance sheet"}),
    ("income", {"de": "Das Einkommen", "en": "Income"}),
    ("human_capital", {"de": "Das Humankapital", "en": "Human capital"}),
    ("earning_power", {"de": "Die Erwerbskraft", "en": "Earning power"}),
    ("income_paths", {"de": "Einkommenspfade und Sparbedarf", "en": "Income paths and the saving they need"}),
    ("pensions", {"de": "Die Renten", "en": "Pensions"}),
    ("retirement", {"de": "Der Ruhestand", "en": "Retirement"}),
    ("property", {"de": "Wohneigentum", "en": "Home ownership"}),
    ("liquidity", {"de": "Liquidität", "en": "Liquidity"}),
    ("risk", {"de": "Das Risikoprofil", "en": "The risk profile"}),
    ("mandate", {"de": "Der Mandatsvorschlag", "en": "The mandate proposal"}),
    ("allocation", {"de": "Die Allokation", "en": "The allocation"}),
    ("roles", {"de": "Gewicht nach Rolle", "en": "Weight by role"}),
    ("positions", {"de": "Die Bausteine", "en": "The building blocks"}),
    ("fit", {"de": "Wie die Allokation zustande kam", "en": "How the allocation came about"}),
    ("outlook", {"de": "Die Aussichten", "en": "The outlook"}),
    ("plan", {"de": "Was die Planrechnung ergibt", "en": "What the plan calculation shows"}),
    ("findings", {"de": "Befunde und nächste Schritte", "en": "Findings and next steps"}),
    ("limits", {"de": "Was dieser Bericht nicht sagen kann", "en": "What this report cannot say"}),
    ("sources", {"de": "Die Quellen", "en": "Sources"}),
)
SECTION_KEYS = tuple(k for k, _ in SECTIONS)


def section_title(key: str, lang: str) -> str:
    return dict(SECTIONS)[key][lang]


def sections_for(facts: Sequence[Fact]) -> list[tuple[str, tuple[str, ...]]]:
    """The sections that have facts, in the fixed order. A section without facts is left out rather than
    printed empty, so the numbering is assigned at render time (dossier.py)."""
    by: dict[str, list[str]] = {}
    for f in facts:
        if f.section not in SECTION_KEYS:
            raise EngineError(f"fact {f.fact_id} names unknown section {f.section!r}")
        by.setdefault(f.section, []).append(f.fact_id)
    return [(k, tuple(by[k])) for k in SECTION_KEYS if k in by]


# ---------------------------------------------------------------------------
# Facts from artefacts
# ---------------------------------------------------------------------------

def _pointer(*parts: Any) -> str:
    """RFC 6901 JSON pointer."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class _Maker:
    def __init__(self, engine: str, artefact_id: str, contract: str, lang: str):
        self.engine, self.artefact_id, self.contract, self.lang = engine, artefact_id, contract, lang
        self.facts: list[Fact] = []

    def src(self, *path: Any) -> FactSource:
        return FactSource(engine=self.engine, artefact_id=self.artefact_id, contract_version=self.contract,
                          path=_pointer(*path))

    def add(self, fact_id: str, section: str, value: Any, unit: str, path: Sequence[Any], *,
            text: Optional[str] = None, display: Optional[str] = None, derivation: Optional[str] = None,
            basis: Optional[str] = None) -> None:
        if value is None:
            return
        if isinstance(value, float) and not math.isfinite(value):
            raise EngineError(f"{self.engine} {self.artefact_id}: {_pointer(*path)} is not finite")
        self.facts.append(Fact(fact_id=fact_id, section=section, label=text or label(fact_id, self.lang),
                               value=value, unit=unit, display=display or fmt(value, unit, self.lang),
                               sources=(self.src(*path),), derivation=derivation, basis=basis))


def allocation_basis(a: Allocation) -> str:
    """The basis of an Allocation's returns: its ``basis``, or ``nominal`` for one without it (REP-28)."""
    return a.basis or "nominal"


def extract_pcp(a: Allocation, cal: Calibration, lang: str, basis: str = "nominal") -> list[Fact]:
    """pcp's figures. ``basis`` is the report's; the service has refused an Allocation of another basis before
    this is called (REP-28), so here it is only checked again."""
    if allocation_basis(a) != basis:
        raise EngineError(f"pcp allocation {a.artefact_id} is {allocation_basis(a)}, the report is asked in {basis}")
    m = _Maker("pcp", a.artefact_id, a.contract_version, lang)
    generated = a.mandate_name.startswith("lbs-") or voc.looks_internal(a.mandate_name)
    m.add("pcp.mandate_name", "allocation", a.mandate_name, "text", ["mandate_name"],
          display=voc.UNNAMED[lang] if generated else None)
    m.add("pcp.date", "allocation", a.date, "date", ["date"])
    m.add("pcp.release_state", "allocation", a.release_state, "text", ["release_state"],
          display=RELEASE[lang].get(a.release_state, a.release_state))
    m.add("pcp.budget_met", "allocation", a.budget_met, "flag", ["budget_met"])
    if a.basis is not None:
        m.add("pcp.basis", "allocation", a.basis, "text", ["basis"], text=voc.BASIS_ALLOCATION_LABEL[lang],
              display=voc.BASIS_ALLOCATION[a.basis][lang])
    held = [i for i in a.instruments if i.weight >= cal.position_min_weight]
    m.add("pcp.positions_held", "allocation", float(len(held)), "count", ["instruments"],
          derivation=f"count of instruments with weight >= {cal.position_min_weight}")
    m.add("pcp.universe_size", "allocation", float(len(a.instruments)), "count", ["instruments"],
          derivation="count of instruments in the allocation")
    for r in a.portfolio_map.roles:
        if r in a.weights_by_role:
            m.add(f"pcp.role.{r}", "roles", float(a.weights_by_role[r]), "share", ["weights_by_role", r],
                  text=role_label(r, lang))
    order = sorted(((j, i) for j, i in enumerate(a.instruments) if i.weight >= cal.position_min_weight),
                   key=lambda t: (-round(t[1].weight, 9), t[1].name))
    for j, i in order:
        m.add(f"pcp.position.{i.instrument_id}", "positions", float(i.weight), "share", ["instruments", j, "weight"],
              text=i.name)
        m.add(f"pcp.position_role.{i.instrument_id}", "positions", i.role, "text", ["instruments", j, "role"],
              text=i.name, display=role_label(i.role, lang))
    d = a.diagnostics
    m.add("pcp.objective", "fit", float(d.objective), "number", ["diagnostics", "objective"])
    m.add("pcp.objective_floor", "fit", float(d.objective_floor), "number", ["diagnostics", "objective_floor"])
    if d.weight_leverage is not None:
        m.add("pcp.weight_leverage", "fit", float(d.weight_leverage), "share", ["diagnostics", "weight_leverage"],
              display=_share(float(d.weight_leverage), lang, 2))
    m.add("pcp.solver_method", "fit", d.solver_method, "text", ["diagnostics", "solver_method"])
    m.add("pcp.solver_converged", "fit", d.success, "flag", ["diagnostics", "success"])
    m.add("pcp.constraint_rows", "fit", float(d.constraint_rows), "count", ["diagnostics", "constraint_rows"])
    m.add("pcp.binding_rows", "fit", float(len(d.binding)), "count", ["diagnostics", "binding"],
          derivation="count of binding constraint rows")
    m.add("pcp.weak_share", "fit", float(a.coverage.weight_on_weak_profiles), "share",
          ["coverage", "weight_on_weak_profiles"])
    for n, w in enumerate(a.coverage.warnings):
        m.add(f"pcp.warning.{n}", "limits", w, "text", ["coverage", "warnings", n],
              text=voc.TOPIC["allocation"][lang], display=voc.pcp_warning_text(w, lang))
    return m.facts


NOT_AVAILABLE = {"de": "nicht verfügbar", "en": "not available"}
VERDICT = {
    "de": {"meets": "erfüllt", "does_not_meet": "nicht erfüllt", "could_not_be_determined": "nicht bestimmbar"},
    "en": {"meets": "met", "does_not_meet": "not met", "could_not_be_determined": "could not be determined"},
}
CAPITAL_KEY = {"de": {"E": "Expertise (E)", "N": "Netzwerk (N)", "H": "Gesundheit (H)"},
               "en": {"E": "Expertise (E)", "N": "Network (N)", "H": "Health (H)"}}
WORDS_LBS = {
    "de": {"person": "Person", "ahv_yearly": "AHV-Rente pro Jahr", "ahv_monthly": "AHV-Rente pro Monat",
           "ahv": "AHV-Rente", "bvg_closing": "Pensionskassenguthaben im Rentenalter",
           "bvg_to_age": "Rentenalter der Projektion",
           "bvg_opening": "Pensionskassenguthaben heute", "bvg_yearly": "BVG-Rente pro Jahr",
           "bvg_conversion": "Umwandlungssatz", "bvg_interest": "Verzinsung (Annahme)", "bvg": "BVG-Rente",
           "cap": "AHV-Paarplafonierung", "cap_yearly": "AHV-Renten des Paares pro Jahr, plafoniert",
           "cap_binds": "Plafonierung greift", "earning_power": "Erwerbskraft",
           "price": "Kaufpreis", "target_date": "Zieldatum", "verdict": "Befund", "gap": "Fehlbetrag",
           "due": "fällig am", "needs": "Bedarf", "covered": "gedeckt", "shortfall": "Lücke",
           "risk": "Risikoprofil", "risk_value": "Risikoprofil (Wert)", "risk_binds": "bindend durch",
           "mandate": "Mandatsvorschlag", "m_name": "Mandatsvorschlag", "m_target": "Zielbetrag",
           "m_horizon": "Horizont in Jahren", "m_drawable": "Entnahmefähig", "m_contribution": "Beitrag pro Jahr",
           "m_required": "Nötige Rendite pro Jahr", "m_feasible": "Erreichbar", "m_complete": "Vollständig",
           "m_release": "Status", "goal": "Ziel"},
    "en": {"person": "Person", "ahv_yearly": "AHV pension a year", "ahv_monthly": "AHV pension a month",
           "ahv": "AHV pension", "bvg_closing": "Pension fund balance at retirement",
           "bvg_to_age": "Retirement age of the projection",
           "bvg_opening": "Pension fund balance today", "bvg_yearly": "BVG pension a year",
           "bvg_conversion": "Conversion rate", "bvg_interest": "Interest (assumed)", "bvg": "BVG pension",
           "cap": "AHV couple cap", "cap_yearly": "The couple's AHV pensions a year, capped",
           "cap_binds": "Cap binds", "earning_power": "Earning power",
           "price": "Purchase price", "target_date": "Target date", "verdict": "Finding", "gap": "Shortfall",
           "due": "due on", "needs": "Need", "covered": "Covered", "shortfall": "Gap",
           "risk": "Risk profile", "risk_value": "Risk profile (value)", "risk_binds": "bound by",
           "mandate": "Mandate proposal", "m_name": "Mandate proposal", "m_target": "Target amount",
           "m_horizon": "Horizon in years", "m_drawable": "Drawable", "m_contribution": "Contribution a year",
           "m_required": "Required return a year", "m_feasible": "Reachable", "m_complete": "Complete",
           "m_release": "Status", "goal": "Goal"},
}


def not_available_text(reason: str, lang: str) -> tuple[str, str]:
    """``(value, display)`` of a stated not-available fact. The value is lbs's reason as "not available:
    <reason>" (lbs's own leading "not available" is not doubled); the display is the reader's sentence for it
    (REP-19), never lbs's English."""
    r = reason.strip()
    display = f"{NOT_AVAILABLE[lang]}: {voc.reason_text(r, lang)}"
    if r.lower().startswith("not available"):
        return "not available" + r[len("not available"):], display
    return f"not available: {r}", display


def _not_available(m: "_Maker", fact_id: str, section: str, reason: str, path: Sequence[Any], text: str) -> None:
    """A section lbs could not compute becomes a stated fact, never a number."""
    value, display = not_available_text(reason, m.lang)
    m.add(fact_id, section, value, "text", path, text=text, display=display)


def lbs_subjects(s: LifeBalanceSheet, lang: str) -> dict[str, str]:
    """``person:<id>`` and ``goal:<id>`` of one sheet to their generic names (REP-20)."""
    persons = [p.person_id for p in s.household.adults + s.household.dependants]
    persons += [hc.person_id for hc in s.human_capital] + [p.person_id for p in s.pensions]
    goals: list[tuple[str, str]] = [(r.goal_id, "retirement") for r in s.retirement]
    goals += [(p.goal_id, "property") for p in s.property]
    if isinstance(s.mandate_proposal, LbsMandateProposal):
        goals.append((s.mandate_proposal.goal_id, s.mandate_proposal.goal_kind))
    goals += [(q.goal_id, "goal") for q in s.liquidity]
    for g in s.gaps:
        head, _, rest = g.section.partition(".")
        if head in ("property", "retirement") and rest:
            goals.append((rest, head))
        elif head == "pensions" and rest:
            persons.append(rest)
    return voc.subjects(persons, goals, lang)


def _gap_subject(section: str, input_: str, names: dict[str, str], lang: str) -> str:
    head, _, rest = section.partition(".")
    if head == "pensions" and f"person:{rest}" in names:
        return names[f"person:{rest}"]
    if head in ("property", "retirement") and f"goal:{rest}" in names:
        return names[f"goal:{rest}"]
    if head == "human_capital" and "." in input_ and f"person:{input_.split('.', 1)[0]}" in names:
        return names[f"person:{input_.split('.', 1)[0]}"]
    return voc.TOPIC.get(head, voc.TOPIC["other"])[lang]


#: One figure in one basis: ``(value, the basis lbs states for it, its path)``.
Figure = tuple[Optional[float], str, list[Any]]


def _goal_figure(m: "_Maker", fact_id: str, section: str, views: dict[str, Figure], unit: str, basis: str, *,
                 text: str, digits: Optional[int] = None) -> None:
    """A return or goal figure (REP-27), marked with its basis. ``views`` holds the figure in each basis lbs
    gives it in, each with the basis lbs states for it. In nominal, the nominal figure. In real, the real figure;
    a figure lbs has no real view of (a liquidity gap, a fixed contribution) is shown as lbs states it, nominal,
    and marked so. A figure whose stated basis is not the one it is read as is refused: a report never mixes
    nominal and real figures under one label."""
    want = basis if basis in views else "nominal"
    fig = views.get(want)
    if fig is None:
        if views:
            raise EngineError(f"lbs sheet {m.artefact_id} gives {fact_id} in {' and '.join(sorted(views))} only, "
                              f"not in {basis}")
        return
    value, stated, path = fig
    if stated != want:
        raise EngineError(f"lbs sheet {m.artefact_id}: {_pointer(*path)} is {stated}, read as {want}; a report "
                          "never mixes nominal and real figures")
    display = _share(value, m.lang, digits) if (digits is not None and value is not None) else None
    m.add(fact_id, section, value, unit, path, text=text, display=display, basis=stated)


def _views(top: Figure, more: Iterable[tuple[str, Figure]]) -> dict[str, Figure]:
    """The top-level figure first (so a nominal report cites the paths it always cited), then lbs's views."""
    out: dict[str, Figure] = {top[1]: top}
    for key, fig in more:
        out.setdefault(key, fig)
    return out


def extract_lbs(s: LifeBalanceSheet, cal: Calibration, lang: str, basis: str = "nominal") -> list[Fact]:
    m = _Maker("lbs", s.artefact_id, s.contract_version, lang)
    rv = s.real_view
    if basis == "real" and rv is None:
        raise EngineError(f"lbs sheet {s.artefact_id} has no real view; a real report needs one")
    goal_views = {g.goal_id: (k, g) for k, g in enumerate(rv.goals)} if rv is not None else {}
    w = WORDS_LBS[lang]
    names = lbs_subjects(s, lang)
    h = s.household
    if h.stated:
        m.add("lbs.household.adults", "household", float(len(h.adults)), "count", ["household", "adults"],
              derivation="count of adults")
        m.add("lbs.household.dependants", "household", float(len(h.dependants)), "count",
              ["household", "dependants"], derivation="count of dependants")
        m.add("lbs.household.composition_as_of", "household", h.composition_as_of, "date",
              ["household", "composition_as_of"])
    t = s.totals
    for key in ("total_assets", "financial_assets", "human_assets", "liabilities", "net_worth", "drawable"):
        m.add(f"lbs.totals.{key}", "balance_sheet", getattr(t, key), "chf", ["totals", key])
    m.add("lbs.totals.identity_holds", "balance_sheet", t.identity_holds, "flag", ["totals", "identity_holds"])
    for key, value in t.by_vessel.items():
        m.add(f"lbs.vessel.{key}", "balance_sheet", value, "chf", ["totals", "by_vessel", key],
              text=VESSEL[lang].get(key, key))
    for j, cell in enumerate(s.grid):
        capital = CAPITAL[lang].get(cell.capital_type, cell.capital_type)
        name = f"{role_label(cell.role, lang, cell.capital_type)}, {capital}"
        base = f"lbs.cell.{cell.role}.{cell.capital_type}"
        m.add(f"{base}.assets", "grid", cell.assets_chf, "chf", ["grid", j, "assets_chf"], text=name)
        m.add(f"{base}.liabilities", "grid", cell.liabilities_chf, "chf", ["grid", j, "liabilities_chf"], text=name)
        m.add(f"{base}.flows", "income", cell.flows_chf_per_year, "chf_per_year", ["grid", j, "flows_chf_per_year"],
              text=name)
    m.add("lbs.totals.household_income", "income", t.household_income, "chf_per_year", ["totals", "household_income"])

    for j, hc in enumerate(s.human_capital):
        who = names[f"person:{hc.person_id}"]
        for key in ("E", "N", "H"):
            cap = getattr(hc, key)
            fid = f"lbs.human.{hc.person_id}.{key}"
            text = f"{who}: {CAPITAL_KEY[lang][key]}"
            if cap.value is not None:
                m.add(fid, "human_capital", float(cap.value), "number", ["human_capital", j, key, "value"], text=text)
            elif cap.absent_because:
                _not_available(m, fid, "human_capital", cap.absent_because,
                               ["human_capital", j, key, "absent_because"], text)
        _not_available(m, f"lbs.human.{hc.person_id}.earning_power", "human_capital", hc.earning_power.reason,
                       ["human_capital", j, "earning_power", "reason"], f"{who}: {w['earning_power']}")

    for j, p in enumerate(s.pensions):
        who = names[f"person:{p.person_id}"]
        base = f"lbs.pension.{p.person_id}"
        if isinstance(p.ahv, LbsAhv):
            m.add(f"{base}.ahv.yearly", "pensions", p.ahv.yearly, "chf_per_year", ["pensions", j, "ahv", "yearly"],
                  text=f"{who}: {w['ahv_yearly']}")
        else:
            _not_available(m, f"{base}.ahv", "pensions", p.ahv.reason, ["pensions", j, "ahv", "reason"],
                           f"{who}: {w['ahv']}")
        if isinstance(p.bvg, LbsBvg):
            b = p.bvg
            m.add(f"{base}.bvg.opening", "pensions", b.opening_balance, "chf", ["pensions", j, "bvg", "opening_balance"],
                  text=f"{who}: {w['bvg_opening']}")
            m.add(f"{base}.bvg.to_age", "pensions", float(b.to_age), "count", ["pensions", j, "bvg", "to_age"],
                  text=f"{who}: {w['bvg_to_age']}")
            # A projection lbs makes in nominal terms only: marked nominal in either basis (REP-27).
            m.add(f"{base}.bvg.closing", "pensions", b.closing_balance, "chf", ["pensions", j, "bvg", "closing_balance"],
                  text=f"{who}: {w['bvg_closing']}", basis="nominal")
            m.add(f"{base}.bvg.conversion", "pensions", b.conversion_rate, "share",
                  ["pensions", j, "bvg", "conversion_rate"], text=f"{who}: {w['bvg_conversion']}",
                  display=_share(b.conversion_rate, lang, 2))
            m.add(f"{base}.bvg.yearly", "pensions", b.yearly_pension, "chf_per_year",
                  ["pensions", j, "bvg", "yearly_pension"], text=f"{who}: {w['bvg_yearly']}", basis="nominal")
        else:
            _not_available(m, f"{base}.bvg", "pensions", p.bvg.reason, ["pensions", j, "bvg", "reason"],
                           f"{who}: {w['bvg']}")
    if isinstance(s.couple_cap, LbsCoupleCap):
        m.add("lbs.couple_cap.yearly", "pensions", s.couple_cap.yearly, "chf_per_year", ["couple_cap", "yearly"],
              text=w["cap_yearly"])
        m.add("lbs.couple_cap.binds", "pensions", s.couple_cap.cap_binds, "flag", ["couple_cap", "cap_binds"],
              text=w["cap_binds"])
    elif len(s.household.adults) > 1:
        _not_available(m, "lbs.couple_cap", "pensions", s.couple_cap.reason, ["couple_cap", "reason"], w["cap"])

    for j, r in enumerate(s.retirement):
        base = f"lbs.retirement.{r.goal_id}"
        goal = names[f"goal:{r.goal_id}"]
        m.add(f"{base}.verdict", "retirement", r.verdict, "text", ["retirement", j, "verdict"],
              text=f"{goal}: {w['verdict']}", display=VERDICT[lang].get(r.verdict, r.verdict))
        for key, field in (("needs", "needs_per_year"), ("covered", "covered_per_year"),
                           ("shortfall", "shortfall_per_year")):
            # From lbs calibration 1.4.0 the top-level figures are real and ``views`` carries both bases.
            top = "real" if r.basis == "real" else "nominal"
            views = _views((getattr(r, field), top, ["retirement", j, field]),
                           ((b, (getattr(v, field), v.basis, ["retirement", j, "views", b, field]))
                            for b, v in (r.views or {}).items()))
            _goal_figure(m, f"{base}.{key}", "retirement", views, "chf_per_year", basis, text=f"{goal}: {w[key]}")

    for j, p in enumerate(s.property):
        base = f"lbs.property.{p.goal_id}"
        goal = names[f"goal:{p.goal_id}"]
        m.add(f"{base}.verdict", "property", p.verdict, "text", ["property", j, "verdict"],
              text=f"{goal}: {w['verdict']}", display=VERDICT[lang].get(p.verdict, p.verdict))
        top = "real" if p.basis == "real" else "nominal"
        k, gv = goal_views.get(p.goal_id, (None, None))
        views = _views((p.price_chf, top, ["property", j, "price_chf"]),
                       ((b, (getattr(gv, b).amount, getattr(gv, b).basis, ["real_view", "goals", k, b, "amount"]))
                        for b in (("nominal", "real") if gv is not None else ())))
        _goal_figure(m, f"{base}.price", "property", views, "chf", basis, text=f"{goal}: {w['price']}")
        m.add(f"{base}.target_date", "property", p.target_date, "date", ["property", j, "target_date"],
              text=f"{goal}: {w['target_date']}")

    for j, q in enumerate(s.liquidity):
        base = f"lbs.liquidity.{q.goal_id}"
        goal = names[f"goal:{q.goal_id}"]
        _goal_figure(m, f"{base}.gap", "liquidity", {"nominal": (q.gap_chf, "nominal", ["liquidity", j, "gap_chf"])},
                     "chf", basis, text=f"{goal}: {w['gap']}")
        m.add(f"{base}.due", "liquidity", q.due_date, "date", ["liquidity", j, "due_date"], text=f"{goal}: {w['due']}")
        m.add(f"{base}.reason", "liquidity", q.reason, "text", ["liquidity", j, "reason"], text=goal,
              display=voc.finding_text(q.reason, lang))

    if isinstance(s.risk_profile, LbsRiskProfile):
        m.add("lbs.risk.value", "risk", s.risk_profile.value, "number", ["risk_profile", "value"], text=w["risk_value"])
        m.add("lbs.risk.binds_on", "risk", s.risk_profile.binds_on, "text", ["risk_profile", "binds_on"],
              text=w["risk_binds"], display=voc.binds_text(s.risk_profile.binds_on or "", lang))
    else:
        _not_available(m, "lbs.risk", "risk", s.risk_profile.reason, ["risk_profile", "reason"], w["risk"])

    mp = s.mandate_proposal
    if isinstance(mp, LbsMandateProposal):
        generated = mp.name == f"lbs-{mp.goal_id}" or voc.looks_internal(mp.name)
        m.add("lbs.mandate.name", "mandate", mp.name, "text", ["mandate_proposal", "name"], text=w["m_name"],
              display=names.get(f"goal:{mp.goal_id}", voc.UNNAMED[lang]) if generated else None)
        def mandate_views(field: str) -> dict[str, Figure]:
            return _views((getattr(mp, field), "nominal", ["mandate_proposal", field]),
                          ((b, (getattr(v, field), v.basis, ["mandate_proposal", "views", b, field]))
                           for b, v in (mp.views or {}).items()))

        _goal_figure(m, "lbs.mandate.target", "mandate", mandate_views("target_chf"), "chf", basis, text=w["m_target"])
        m.add("lbs.mandate.horizon", "mandate", mp.goal_horizon_years, "number",
              ["mandate_proposal", "goal_horizon_years"], text=w["m_horizon"])
        m.add("lbs.mandate.drawable", "mandate", mp.drawable_chf, "chf", ["mandate_proposal", "drawable_chf"],
              text=w["m_drawable"])
        # The contribution is this year's francs; it stays constant in today's francs only when it rises with
        # prices (lbs ``contribution_indexed``), so it is real then and nominal otherwise. An indexed
        # contribution's first payment is the same amount in both views, so it is stated in the report's basis.
        indexed = rv is not None and rv.contribution_indexed
        paid_basis = basis if indexed else "nominal"
        paid: Figure = (mp.annual_contribution, paid_basis, ["mandate_proposal", "annual_contribution"])
        _goal_figure(m, "lbs.mandate.contribution", "mandate", {paid_basis: paid}, "chf_per_year",
                     paid_basis, text=w["m_contribution"])
        _goal_figure(m, "lbs.mandate.required_return", "mandate", mandate_views("required_return"), "share", basis,
                     text=w["m_required"], digits=2)
        if mp.plausibility is not None:
            judged = mp.plausibility.judgement
            m.add("lbs.mandate.plausibility", "mandate", judged, "text",
                  ["mandate_proposal", "plausibility", "judgement"], text=voc.BASIS_WORDS["plausibility"][lang],
                  display=voc.JUDGEMENT.get(judged, voc.JUDGEMENT["could_not_be_determined"])[lang])
        m.add("lbs.mandate.feasible", "mandate", mp.feasible, "flag", ["mandate_proposal", "feasible"],
              text=w["m_feasible"])
        m.add("lbs.mandate.complete", "mandate", mp.complete, "flag", ["mandate_proposal", "complete"],
              text=w["m_complete"])
        m.add("lbs.mandate.release_state", "mandate", mp.release_state, "text", ["mandate_proposal", "release_state"],
              text=w["m_release"], display=RELEASE[lang].get(mp.release_state, mp.release_state))
    else:
        _not_available(m, "lbs.mandate", "mandate", mp.reason, ["mandate_proposal", "reason"], w["mandate"])
    if basis == "real" and rv is not None:
        # What the real figures rest on (REP-27): lbs's inflation assumption and whether the saving rises with it.
        bw = voc.BASIS_WORDS
        m.add("lbs.real.inflation", "mandate", rv.inflation.annual_rate, "share",
              ["real_view", "inflation", "annual_rate"], text=bw["inflation"][lang],
              display=_share(rv.inflation.annual_rate, lang, 2))
        m.add("lbs.real.inflation_label", "mandate", rv.inflation.label, "text", ["real_view", "inflation", "label"],
              text=bw["inflation_label"][lang], display=bw[rv.inflation.label][lang])
        m.add("lbs.real.contribution_indexed", "mandate", rv.contribution_indexed, "flag",
              ["real_view", "contribution_indexed"], text=bw["indexed"][lang])

    for n, g in enumerate(s.gaps):
        m.add(f"lbs.gap.{n}", "limits", f"{g.input}: {g.reason}", "text", ["gaps", n, "reason"],
              text=_gap_subject(g.section, g.input, names, lang), display=voc.gap_text(g.input, g.kind, g.reason, lang))
    return m.facts


# ---------------------------------------------------------------------------
# lbsim (REP-32 to REP-36): findings, paths and plan, read together
# ---------------------------------------------------------------------------

_LS_MEASURE_KIND = {"home": "property", "retirement": "retirement", "capital": "goal"}


def lbsim_subjects(findings: Optional[LifeBalanceFindings], paths: Optional[LifeBalancePaths],
                   plan: Optional[LifeBalancePlan], known: dict[str, str], lang: str) -> dict[str, str]:
    """The generic names of lbsim's persons and goals (REP-20): the lbs sheet's names where the sheet names them
    (``known``), numbered after them otherwise."""
    out = dict(known)
    persons = [e.person_id for e in findings.earning_power] if findings else []
    persons += [p.person_id for p in findings.income_paths] if findings else []
    new_persons = [p for p in dict.fromkeys(persons) if f"person:{p}" not in out]
    n0 = sum(1 for k in out if k.startswith("person:"))
    for n, pid in enumerate(new_persons, start=n0 + 1):
        out[f"person:{pid}"] = voc.PERSON[lang].format(n=n)
    goals: list[tuple[str, str]] = []
    for r in (paths.regimes if paths else ()):
        goals += [(g.goal_id, _LS_MEASURE_KIND.get(g.kind, "goal")) for g in r.goals]
    if plan is not None:
        goals.append((plan.goal.goal_id, _LS_MEASURE_KIND.get(plan.goal.kind, "goal")))
    for p in (findings.income_paths if findings else ()):
        goals += [(s.goal_id, "goal") for s in p.saving_need]
    missing = [(g, k) for g, k in dict(goals).items() if f"goal:{g}" not in out]
    if missing:
        out.update(voc.subjects([], missing, lang))
    return out


def designated_goal(paths: Optional[LifeBalancePaths], plan: Optional[LifeBalancePlan],
                    sheet: Optional[LifeBalanceSheet]) -> Optional[str]:
    """The goal the outlook's fan is drawn for: the plan's goal, else the lbs mandate proposal's, else the first."""
    if paths is None or not paths.regimes:
        return None
    ids = [g.goal_id for g in paths.regimes[0].goals]
    if plan is not None and plan.goal.goal_id in ids:
        return plan.goal.goal_id
    if sheet is not None and isinstance(sheet.mandate_proposal, LbsMandateProposal) \
            and sheet.mandate_proposal.goal_id in ids:
        return sheet.mandate_proposal.goal_id
    return ids[0] if ids else None


def fan_window(paths: LifeBalancePaths, goal_id: Optional[str]) -> tuple[str, int, Optional[int]]:
    """``(series, last index, goal index in the base Regime)``: the goal's measure up to its date, or net worth
    over the whole horizon when there is no goal. Index k is the end of year ``start_year + k``; 0 is today."""
    base = paths.regimes[0]
    for j, g in enumerate(base.goals):
        if g.goal_id == goal_id and g.measure in base.bands:
            year = int(g.target.date[:4])
            return g.measure, max(1, min(paths.horizon_years, year - paths.start_year)), j
    return "net_worth", paths.horizon_years, None


def _ls_figure(value: float, unit: str, lang: str) -> tuple[str, str]:
    """``(fact unit, display)`` of a finding figure. The template carries the unit words ("pro Jahr"), so an
    amount a year prints as the amount."""
    if unit in ("chf", "chf_per_year"):
        return unit, _money(value, lang)
    if unit == "share":
        return "share", _share(value, lang)
    if unit == "count":
        return "count", str(int(round(value)))
    digits = 0 if float(value).is_integer() else 1
    return "number", _number(value, lang, digits)


def fill_template(template: str, figures: dict[str, str]) -> str:
    """A finding template with each ``{name}`` replaced (used for a title in a label, where no markup goes)."""
    return re.sub(r"\{([a-z0-9_]+)\}", lambda mm: figures.get(mm.group(1), mm.group(0)), template)


def extract_lbsim(findings: Optional[LifeBalanceFindings], paths: Optional[LifeBalancePaths],
                  plan: Optional[LifeBalancePlan], sheet: Optional[LifeBalanceSheet], names: dict[str, str],
                  lang: str, basis: str = "nominal", with_allocation: bool = True,
                  min_weight: float = 0.0005) -> list[Fact]:
    """lbsim's figures (REP-33). The service has refused inconsistent sources before this is called: every
    artefact on one sheet, the paths on the pcp source's Allocation, the plan on the paths (REP-32)."""
    W = voc.LBSIM_WORDS
    w = {k: v[lang] for k, v in W.items()}
    facts: list[Fact] = []

    def who(pid: str) -> str:
        return names.get(f"person:{pid}", voc.PERSON[lang].format(n="?"))

    def goal(gid: str) -> str:
        return names.get(f"goal:{gid}", voc.GOAL["goal"][lang])

    if findings is not None:
        m = _Maker("lbsim", findings.artefact_id, findings.contract_version, lang)
        for j, ep in enumerate(findings.earning_power):
            base, p = f"lbsim.earning_power.{ep.person_id}", who(ep.person_id)
            if ep.status == "not_available" or ep.modelled is None:
                reason = ep.reason.de if (ep.reason and lang == "de") else ep.reason.en if ep.reason else None
                m.add(f"{base}.status", "earning_power", reason or voc.FALLBACK_REASON[lang], "text",
                      ["earning_power", j, "reason", lang] if ep.reason else ["earning_power", j, "status"],
                      text=f"{p}: {w['ep_na']}")
            else:
                m.add(f"{base}.modelled", "earning_power", float(ep.modelled.full_time_chf_per_year), "chf_per_year",
                      ["earning_power", j, "modelled", "full_time_chf_per_year"], text=f"{p}: {w['ep_modelled']}")
                resp = ep.modelled.responsibility
                label_ = getattr(resp.label, lang)
                m.add(f"{base}.responsibility", "earning_power", label_, "text",
                      ["earning_power", j, "modelled", "responsibility", "label", lang],
                      text=f"{p}: {w['ep_responsibility']}",
                      display=label_ if resp.stated else f"{label_} ({w['ep_not_stated']})")
            m.add(f"{base}.stated", "earning_power", ep.stated.expected_full_pensum_income_chf_per_year,
                  "chf_per_year", ["earning_power", j, "stated", "expected_full_pensum_income_chf_per_year"],
                  text=f"{p}: {w['ep_stated']}")
            m.add(f"{base}.level_basis", "earning_power", ep.level_basis, "text", ["earning_power", j, "level_basis"],
                  text=f"{p}: {w['ep_level']}", display=w[f"ep_level_{ep.level_basis}"])
            m.add(f"{base}.current", "earning_power", ep.current.gross_income_chf_per_year, "chf_per_year",
                  ["earning_power", j, "current", "gross_income_chf_per_year"], text=f"{p}: {w['ep_current']}")
            if ep.current.pensum is not None:
                m.add(f"{base}.pensum", "earning_power", float(ep.current.pensum), "share",
                      ["earning_power", j, "current", "pensum"], text=f"{p}: {w['ep_pensum']}",
                      display=_share(float(ep.current.pensum), lang, 0))
            for n, c in enumerate(ep.caveats):
                m.add(f"{base}.caveat.{n}", "earning_power", getattr(c, lang), "text",
                      ["earning_power", j, "caveats", n, lang], text=f"{p}: {w['ep_caveat']}")

        m.add("lbsim.zero_return.note", "income_paths", getattr(findings.zero_return.note, lang), "text",
              ["zero_return", "note", lang], text=w["zero_return"])
        for i, path in enumerate(findings.income_paths):
            base, pname = f"lbsim.path.{path.code}", getattr(path.name, lang)
            m.add(f"{base}.name", "income_paths", pname, "text", ["income_paths", i, "name", lang], text=w["path"])
            m.add(f"{base}.note", "income_paths", getattr(path.note, lang), "text", ["income_paths", i, "note", lang],
                  text=f"{pname}: {w['path_note']}")
            real = {s.goal_id: (k, s) for k, s in enumerate(path.views.real.saving_need)}
            for k, need in enumerate(path.saving_need):
                g = goal(need.goal_id)
                if basis == "real" and need.goal_id in real:
                    rk, rs = real[need.goal_id]
                    at = ["income_paths", i, "views", "real", "saving_need", rk]
                    save, free, b = rs.zero_return_saving_chf_per_year, rs.free_cash_chf_per_year, "real"
                else:
                    at = ["income_paths", i, "saving_need", k]
                    save, free, b = need.zero_return_saving_chf_per_year, need.free_cash_chf_per_year, "nominal"
                m.add(f"{base}.saving_need.{need.goal_id}", "income_paths", float(save), "chf_per_year",
                      at + ["zero_return_saving_chf_per_year"], text=f"{pname}: {g}, {w['saving_need']}", basis=b)
                m.add(f"{base}.free_cash.{need.goal_id}", "income_paths", float(free), "chf_per_year",
                      at + ["free_cash_chf_per_year"], text=f"{pname}: {g}, {w['free_cash']}", basis=b)
                m.add(f"{base}.holds.{need.goal_id}", "income_paths", bool(need.holds), "flag",
                      ["income_paths", i, "saving_need", k, "holds"], text=f"{pname}: {g}, {w['holds']}")

        titles: dict[str, str] = {}
        for i, f in enumerate(findings.findings):
            base = f"lbsim.finding.{f.code}"
            shown = {name: _ls_figure(float(fig.value), fig.unit, lang) for name, fig in f.figures.items()
                     if fig.value is not None}
            words = getattr(f.text, lang)
            title = fill_template(words.title, {k: d for k, (_, d) in shown.items()})
            titles[f.code] = title
            # A figure is labelled by its finding and its place, never by its key (REP-19).
            for k, (name, (unit, display)) in enumerate(shown.items(), start=1):
                fig = f.figures[name]
                m.add(f"{base}.{name}", "findings", float(fig.value), unit, ["findings", i, "figures", name, "value"],
                      text=f"{title} · {k}", display=display, basis=fig.basis)
            shown = {k: d for k, (_, d) in shown.items()}
            for part in ("title", "trigger", "why", "action"):
                m.add(f"{base}.{part}", "findings", getattr(words, part), "text", ["findings", i, "text", lang, part],
                      text=title if part != "title" else w["finding"], display=fill_template(getattr(words, part), shown)
                      if part == "title" else getattr(words, part))
            m.add(f"{base}.urgency", "findings", f.urgency, "text", ["findings", i, "urgency"],
                  text=f"{title}: {w['urgency']}", display=voc.LBSIM_URGENCY[f.urgency][lang])
            m.add(f"{base}.severity", "findings", f.severity, "text", ["findings", i, "severity"],
                  text=f"{title}: {w['severity']}", display=voc.LBSIM_SEVERITY[f.severity][lang])
            m.add(f"{base}.action_kind", "findings", f.action_kind, "text", ["findings", i, "action_kind"],
                  text=f"{title}: {w['action_kind']}", display=voc.LBSIM_ACTION_KIND[f.action_kind][lang])
        for n, entry in enumerate(findings.schedule):
            m.add(f"lbsim.schedule.{n}", "findings", getattr(entry.label, lang), "text",
                  ["schedule", n, "label", lang], text=w["schedule"])
            for k, code in enumerate(entry.codes):
                if code in titles:
                    m.add(f"lbsim.schedule.{n}.{code}", "findings", code, "text", ["schedule", n, "codes", k],
                          text=getattr(entry.label, lang), display=titles[code])
        for n, u in enumerate(findings.unchecked):
            if u.answered_by == "plan" and plan is not None:
                continue
            m.add(f"lbsim.unchecked.{n}", "findings", getattr(u.reason, lang), "text", ["unchecked", n, "reason", lang],
                  text=w["unchecked"])
        for n, q in enumerate(findings.next_questions):
            m.add(f"lbsim.question.{n}", "findings", getattr(q.question, lang), "text",
                  ["next_questions", n, "question", lang], text=w["question"])
        if basis == "real" and not with_allocation and paths is None:
            # Without lbsim's paths a real report has no curve of the Allocation in today's francs (REP-38).
            m.add("lbsim.alloc.no_real_curve", "limits", w["no_real_curve"], "text", ["artefact_id"],
                  text=voc.TOPIC["allocation"][lang],
                  derivation="a real report without an lbsim paths source has no real curve of the Allocation")
        facts.extend(m.facts)

    if paths is not None and paths.regimes:
        m = _Maker("lbsim", paths.artefact_id, paths.contract_version, lang)
        m.add("lbsim.paths.n", "outlook", float(paths.n_paths), "count", ["n_paths"], text=w["n_paths"])
        m.add("lbsim.paths.horizon", "outlook", float(paths.horizon_years), "count", ["horizon_years"],
              text=w["horizon"])
        base = paths.regimes[0]
        for j, g in enumerate(base.goals):
            name = goal(g.goal_id)
            m.add(f"lbsim.goal.{g.goal_id}.name", "outlook", g.goal_id, "text", ["regimes", 0, "goals", j, "goal_id"],
                  text=w["goal"], display=name)
            field = "real_chf" if basis == "real" else "nominal_chf"
            m.add(f"lbsim.goal.{g.goal_id}.target", "outlook", float(getattr(g.target, field)), "chf",
                  ["regimes", 0, "goals", j, "target", field], text=f"{name}: {w['target']}", basis=basis)
            m.add(f"lbsim.goal.{g.goal_id}.date", "outlook", g.target.date, "date",
                  ["regimes", 0, "goals", j, "target", "date"], text=f"{name}: {w['target_date']}")
            m.add(f"lbsim.goal.{g.goal_id}.judged", "outlook", g.chance_basis, "text",
                  ["regimes", 0, "goals", j, "chance_basis"], text=f"{name}: {w['judged']}",
                  display=w[f"judged_{g.chance_basis}"])
        target_id = designated_goal(paths, plan, sheet)
        series, last, _ = fan_window(paths, target_id)
        what = voc.LBSIM_MEASURE.get(series, voc.LBSIM_MEASURE["net_worth"])[lang]
        m.add("lbsim.fan.series", "outlook", series, "text", ["regimes", 0, "bands"], text=w["fan_series"],
              display=f"{what} ({goal(target_id)})" if target_id else what,
              derivation="the band series of the designated goal's measure (its date bounds the fan)")
        for r, reg in enumerate(paths.regimes):
            label_ = getattr(reg.label, lang)
            m.add(f"lbsim.regime.{reg.key}", "outlook", label_, "text", ["regimes", r, "label", lang],
                  text=w["regime"])
            for j, g in enumerate(reg.goals):
                m.add(f"lbsim.chance.{reg.key}.{g.goal_id}", "outlook", float(g.chance), "share",
                      ["regimes", r, "goals", j, "chance"], text=f"{label_}: {goal(g.goal_id)}, {w['chance']}",
                      display=_share(float(g.chance), lang, 0))
            band = reg.bands.get(series)
            if band is None:
                continue
            q = getattr(band, basis)
            for key in ("p10", "p50", "p90"):
                m.add(f"lbsim.fan.{reg.key}.{key}.end", "outlook", float(getattr(q, key)[last]), "chf",
                      ["regimes", r, "bands", series, basis, key, last],
                      text=f"{label_}: {w[key]} {w['at_date']}", basis=basis)
        m.add("lbsim.fan.explained", "outlook", w["fan_explained_text"], "text", ["regimes", 0, "bands"],
              text=w["fan_explained"], derivation="the report's reading of the p10, p50 and p90 bands")
        av = paths.allocation_view
        if av is not None and not with_allocation:
            # Charts 1 and 2 from the Allocation the paths ran on, as lbsim states it (REP-38, owner 29.09.2026):
            # the weights carry no basis and the Allocation's basis is stated; the curves in the report's basis,
            # marked converted where lbsim derived them.
            generated = av.mandate_name.startswith("lbs-") or voc.looks_internal(av.mandate_name)
            m.add("lbsim.alloc.mandate_name", "allocation", av.mandate_name, "text", ["allocation_view", "mandate_name"],
                  text=label("pcp.mandate_name", lang), display=voc.UNNAMED[lang] if generated else None)
            m.add("lbsim.alloc.date", "allocation", av.date, "date", ["allocation_view", "date"],
                  text=label("pcp.date", lang))
            m.add("lbsim.alloc.basis", "allocation", av.allocation_basis, "text", ["allocation_view", "allocation_basis"],
                  text=voc.BASIS_ALLOCATION_LABEL[lang], display=voc.BASIS_ALLOCATION[av.allocation_basis][lang])
            for role, weight in av.by_role.items():
                m.add(f"lbsim.alloc.role.{role}", "roles", float(weight), "share", ["allocation_view", "by_role", role],
                      text=role_label(role, lang))
            held = sorted(((j, i) for j, i in enumerate(av.instruments) if i.weight >= min_weight),
                          key=lambda t: (-round(t[1].weight, 9), t[1].name))
            for j, i in held:
                m.add(f"lbsim.alloc.position.{i.instrument_id}", "positions", float(i.weight), "share",
                      ["allocation_view", "instruments", j, "weight"], text=i.name)
                m.add(f"lbsim.alloc.position_role.{i.instrument_id}", "positions", i.role, "text",
                      ["allocation_view", "instruments", j, "role"], text=i.name, display=role_label(i.role, lang))
            derived = getattr(av.curves, basis).derived
            m.add("lbsim.alloc.curves", "fit", derived, "flag", ["allocation_view", "curves", basis, "derived"],
                  text=w["curves"], display=w["curves_derived"] if derived else w["curves_own"])
        if plan is None:
            m.add("lbsim.plan.state", "plan", "calculating", "text", ["artefact_id"], text=w["plan"],
                  display=w["plan_calculating"],
                  derivation="no plan artefact among the sources: the plan calculation for these paths is still running")
        facts.extend(m.facts)

    if plan is not None:
        m = _Maker("lbsim", plan.artefact_id, plan.contract_version, lang)
        m.add("lbsim.plan.framing", "plan", getattr(plan.framing, lang), "text", ["framing", lang],
              text=w["plan_framing"])
        m.add("lbsim.plan.outcome", "plan", plan.outcome, "text", ["outcome"], text=w["plan_outcome"],
              display=voc.LBSIM_OUTCOME[plan.outcome][lang])
        m.add("lbsim.plan.goal", "plan", plan.goal.goal_id, "text", ["goal", "goal_id"], text=w["plan_goal"],
              display=goal(plan.goal.goal_id))
        m.add("lbsim.plan.confidence", "plan", float(plan.goal.confidence), "share", ["goal", "confidence"],
              text=w["plan_confidence"], display=_share(float(plan.goal.confidence), lang, 0))
        m.add("lbsim.plan.chance", "plan", float(plan.chance.out_of_sample), "share", ["chance", "out_of_sample"],
              text=w["plan_chance"], display=_share(float(plan.chance.out_of_sample), lang, 0))
        if plan.reachable is not None:
            m.add("lbsim.plan.reachable", "plan", float(plan.reachable.amount_chf), "chf", ["reachable", "amount_chf"],
                  text=w["plan_reachable"], basis="nominal")
        a = plan.action_now
        for field, words in voc.LBSIM_ACTION_NOW.items():
            value = float(getattr(a, field))
            if field == "work_share":
                unit, display = "share", _share(value, lang, 0)
            elif field.endswith("_hours_per_week"):
                unit, display = "number", f"{_number(value, lang, 0 if value.is_integer() else 1)} {w['hours_a_week']}"
            else:
                unit, display = "chf_per_year", None
            m.add(f"lbsim.plan.action_now.{field}", "plan", value, unit, ["action_now", field], text=words[lang],
                  display=display)
        m.add("lbsim.plan.horizon.solved", "plan", float(plan.horizon.solved_years), "count",
              ["horizon", "solved_years"], text=w["plan_solved_years"])
        m.add("lbsim.plan.horizon.total", "plan", float(plan.horizon.total_years), "count",
              ["horizon", "total_years"], text=w["plan_total_years"])
        if plan.horizon.beyond_cap_rule and plan.horizon.solved_years < plan.horizon.total_years:
            m.add("lbsim.plan.horizon.beyond", "plan", plan.horizon.beyond_cap_rule, "text",
                  ["horizon", "beyond_cap_rule"], text=w["plan_beyond"], display=w["plan_beyond_rule"])
        facts.extend(m.facts)
    return facts


@dataclass(frozen=True)
class Extractor:
    """How one engine's artefacts become facts. One entry per engine the report can draw on."""

    engine: str
    contract_version: str
    mirror: type[BaseModel]
    #: The upstream path an artefact is read from.
    path: Callable[[str], str]
    #: ``(artefact, calibration, language, basis)`` to facts (the basis since REP-27). ``None`` for lbsim's
    #: artefacts, which are read together (:func:`extract_lbsim`, REP-33).
    extract: Optional[Callable[[Any, Calibration, str, str], list[Fact]]]
    #: The client the artefact is about, when it says; checked against the request's client_ref.
    client_ref: Callable[[Any], Optional[str]]
    #: The artefact's own date, ``None`` for one that carries none (an lbsim plan).
    as_of: Callable[[Any], Optional[str]]
    #: The bases the artefact's figures can be read in: an Allocation has one (REP-28), an lbs sheet both when
    #: it carries a real view (REP-27).
    bases: Callable[[Any], frozenset[str]] = lambda a: frozenset({"nominal"})
    #: The source kind: the engine, or ``lbsim.findings``, ``lbsim.paths``, ``lbsim.plan`` (REP-32).
    kind: str = ""

    @property
    def source_kind(self) -> str:
        return self.kind or self.engine


EXTRACTORS: dict[str, Extractor] = {
    "pcp": Extractor(engine="pcp", contract_version="pcp-allocation@1.0.0", mirror=Allocation,
                     path=lambda aid: f"/allocation/{aid}", extract=extract_pcp,
                     # pcp's ``client`` is a free label on the mandate, not an identifier: not checked (REP-10).
                     client_ref=lambda a: None, as_of=lambda a: a.date,
                     bases=lambda a: frozenset({allocation_basis(a)})),
    "lbs": Extractor(engine="lbs", contract_version="lbs-balance-sheet@1.0.0", mirror=LifeBalanceSheet,
                     path=lambda aid: f"/artefacts/{aid}", extract=extract_lbs,
                     client_ref=lambda s: s.client_ref, as_of=lambda s: s.as_of,
                     bases=lambda s: frozenset({"nominal", "real"} if s.real_view is not None else {"nominal"})),
}

_BOTH = frozenset({"nominal", "real"})
#: lbsim's three artefacts, by the prefix of their id (REP-32), all from ``GET /artefacts/{id}`` on 8014. They
#: carry both bases: nominal figures with real views (the saving need, the bands, the targets), and the plan's
#: figures for this period, which are the same amount in either.
LBSIM_EXTRACTORS: dict[str, Extractor] = {
    "LSF": Extractor(engine="lbsim", kind="lbsim.findings", contract_version="lbsim-findings@1.0.0",
                     mirror=LifeBalanceFindings, path=lambda aid: f"/artefacts/{aid}", extract=None,
                     client_ref=lambda a: a.client_ref, as_of=lambda a: a.as_of, bases=lambda a: _BOTH),
    "LSP": Extractor(engine="lbsim", kind="lbsim.paths", contract_version="lbsim-paths@1.0.0",
                     mirror=LifeBalancePaths, path=lambda aid: f"/artefacts/{aid}", extract=None,
                     client_ref=lambda a: a.client_ref, as_of=lambda a: a.as_of, bases=lambda a: _BOTH),
    "LSO": Extractor(engine="lbsim", kind="lbsim.plan", contract_version="lbsim-plan@1.0.0",
                     mirror=LifeBalancePlan, path=lambda aid: f"/artefacts/{aid}", extract=None,
                     client_ref=lambda a: a.client_ref, as_of=lambda a: None, bases=lambda a: _BOTH),
}


def extractor_for(engine_name: str, artefact_id: str) -> Extractor:
    """The extractor of one source: by engine, and for lbsim by the prefix of the id."""
    if engine_name == "lbsim":
        found = LBSIM_EXTRACTORS.get(artefact_id.split("-", 1)[0])
        if found is None:
            raise EngineError(f"lbsim has no artefact kind for {artefact_id!r} (LSF-, LSP- or LSO-)")
        return found
    return EXTRACTORS[engine_name]


def caller_facts(display: Sequence[DisplayFact], request_id: str, lang: str) -> list[Fact]:
    """Display facts, cited to the request that carried them. Shown in the header only; never to the model."""
    out = []
    for n, f in enumerate(display):
        unit = "number" if isinstance(f.value, float) else "text"
        out.append(Fact(fact_id=f"caller.{f.key}", section="sources", label=f.label, value=f.value, unit=unit,
                        display=(f"{f.value:g}" if isinstance(f.value, float) else f.value),
                        sources=(FactSource(engine="caller", artefact_id=request_id,
                                            contract_version="report-request@1.0.0",
                                            path=_pointer("display_facts", n, "value")),),
                        derivation=f"supplied by the caller ({f.source})"))
    return out


REVISION_LABEL = {"de": "Anmerkung der Kuratorin oder des Kurators", "en": "The curator's remark"}


def revision_facts(note: Optional[str], request_id: str, lang: str) -> list[Fact]:
    """The curator's remark on a revision (REP-25), cited to the request that carried it. Printed on the page
    in its own box, as written; never to the model (it is the caller's text, as a display fact, REP-06)."""
    if note is None:
        return []
    return [Fact(fact_id="caller.revision_note", section="sources", label=REVISION_LABEL[lang], value=note,
                 unit="text", display=note.strip(),
                 sources=(FactSource(engine="caller", artefact_id=request_id, contract_version="report-request@1.0.0",
                                     path=_pointer("revision_note")),),
                 derivation="supplied by the caller: the curator's remark asking for this revision")]


SOURCE_WORDS = {
    "de": {"pcp": "Ihre Portfolio-Allokation", "lbs": "Ihre Bilanz", "report": "Ihr vorheriger Bericht"},
    "en": {"pcp": "Your portfolio allocation", "lbs": "Your balance sheet", "report": "Your previous report"},
}


def _date_field(kind: str) -> str:
    return "date" if kind == "pcp" else "as_of"


def source_date_facts(dated: Sequence[tuple[str, str, str, str]], previous: Optional[Report], lang: str,
                      undated: Sequence[tuple[str, str, str, str]] = ()) -> list[Fact]:
    """One dated fact per source, named in words (REP-23): the sources table prints these, never an id. ``dated``
    and ``undated`` hold ``(date or value, kind, artefact_id, contract)``; the kind is the engine, or
    ``lbsim.<kind>`` for lbsim's artefacts (REP-32). An lbsim plan carries no date of its own: it is named with the
    paths it was calculated on."""
    out = []
    for as_of, kind, aid, contract in dated:
        engine_name, _, sub = kind.partition(".")
        words = voc.LBSIM_SOURCE_WORDS[sub][lang] if sub else SOURCE_WORDS[lang].get(kind, kind)
        out.append(Fact(fact_id=f"sources.date.{kind}", section="sources", label=words, value=as_of, unit="date",
                        display=fmt(as_of, "date", lang),
                        sources=(FactSource(engine=engine_name, artefact_id=aid, contract_version=contract,
                                            path=_pointer(_date_field(kind))),)))
    for value, kind, aid, contract in undated:
        engine_name, _, sub = kind.partition(".")
        out.append(Fact(fact_id=f"sources.date.{kind}", section="sources", label=voc.LBSIM_SOURCE_WORDS[sub][lang],
                        value=value, unit="text", display=voc.LBSIM_SOURCE_WORDS["plan_dated"][lang],
                        sources=(FactSource(engine=engine_name, artefact_id=aid, contract_version=contract,
                                            path=_pointer("paths_artefact_id")),)))
    if previous is not None and previous.as_of:
        out.append(Fact(fact_id="sources.date.report", section="sources", label=SOURCE_WORDS[lang]["report"],
                        value=previous.as_of, unit="date", display=fmt(previous.as_of, "date", lang),
                        sources=(FactSource(engine="report", artefact_id=previous.artefact_id,
                                            contract_version=previous.contract_version, path="/as_of"),)))
    return out


def as_of_fact(dated: Sequence[tuple[str, str, str, str]], lang: str) -> Fact:
    """``dated`` is (as_of, kind, artefact_id, contract) per source. The report speaks for the newest."""
    as_of, kind, aid, contract = max(dated)
    return Fact(fact_id="sources.as_of", section="sources", label=label("sources.as_of", lang), value=as_of,
                unit="date", display=fmt(as_of, "date", lang),
                sources=(FactSource(engine=kind.partition(".")[0], artefact_id=aid, contract_version=contract,
                                    path=_pointer(_date_field(kind))),),
                derivation="the newest as-of date among the sources")


# ---------------------------------------------------------------------------
# Changes against a previous report
# ---------------------------------------------------------------------------

_COMPARABLE = ("chf", "chf_per_year", "share", "count", "number")


def change_facts(previous: Report, current: Sequence[Fact], lang: str) -> list[Fact]:
    """What changed since ``previous``: one fact per figure whose value moved, carrying the previous value and
    citing both artefacts; the count of unchanged figures; what is new and what is gone."""
    before = {f.fact_id: (n, f) for n, f in enumerate(previous.facts)}
    out: list[Fact] = []
    unchanged = 0
    rel = (lambda a, b: abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b)))

    def prev_src(n: int) -> FactSource:
        return FactSource(engine="report", artefact_id=previous.artefact_id, contract_version=previous.contract_version,
                          path=_pointer("facts", n, "value"))

    for f in current:
        if f.unit not in _COMPARABLE or f.fact_id not in before or isinstance(f.value, bool):
            continue
        n, old = before[f.fact_id]
        if old.unit != f.unit or not isinstance(old.value, (int, float)) or isinstance(old.value, bool):
            continue
        new_v, old_v = float(f.value), float(old.value)  # type: ignore[arg-type]
        if rel(new_v, old_v):
            unchanged += 1
            continue
        arrow = f"{fmt(old_v, f.unit, lang)} → {fmt(new_v, f.unit, lang)}"
        out.append(Fact(fact_id=f"change.{f.fact_id}", section="changes", label=f.label, value=new_v, unit=f.unit,
                        display=arrow, previous=old_v, sources=(prev_src(n),) + f.sources,
                        derivation=f"current value against report {previous.artefact_id}", basis=f.basis))
        delta = new_v - old_v
        out.append(Fact(fact_id=f"delta.{f.fact_id}", section="changes", label=f.label, value=delta, previous=old_v,
                        unit=f.unit, display=fmt_change(delta, f.unit, lang), sources=(prev_src(n),) + f.sources,
                        derivation="current minus previous", basis=f.basis))
    whole = FactSource(engine="report", artefact_id=previous.artefact_id, contract_version=previous.contract_version,
                       path="/facts")
    out.append(Fact(fact_id="changes.unchanged", section="changes", label=label("changes.unchanged", lang),
                    value=float(unchanged), unit="count", display=str(unchanged), sources=(whole,),
                    derivation=f"count of figures equal in this report and in {previous.artefact_id}"))
    now = {f.fact_id: f for f in current}
    added = [now[i].label for i in now if i not in before and now[i].unit in _COMPARABLE]
    removed = [before[i][1].label for i in before if i not in now and before[i][1].unit in _COMPARABLE]
    for key, names in (("changes.added", added), ("changes.removed", removed)):
        if names:
            out.append(Fact(fact_id=key, section="changes", label=label(key, lang), value="; ".join(names),
                            unit="text", display="; ".join(names), sources=(whole,),
                            derivation="labels of figures in only one of the two reports"))
    return out


# ---------------------------------------------------------------------------
# Prose: the prompt. A change to any text here is a new PROMPT_VERSION; its hash enters the key.
# ---------------------------------------------------------------------------

PROMPT_VERSION = "report-prompt@1.1.0"

SYSTEM = {
    "de": (
        "Du schreibst EINEN Absatz für einen Abschnitt eines Schweizer Finanzberichts.\n"
        "\n"
        "Der Abschnitt enthält bereits Tabellen und Zahlen. Deine Aufgabe ist der verbindende Text: was die Leserin "
        "oder der Leser hier sieht und warum es zählt. Zwei bis drei Sätze, Fliesstext, Deutsch, sachlich, "
        "Schweizer Rechtschreibung (ss statt ß).\n"
        "\n"
        "REGELN ohne Ausnahme:\n"
        "1. Nur die unten übergebenen Zahlen, und jede mit ihrer RICHTIGEN Bezeichnung. Schulden sind Schulden, "
        "nicht Eigenkapital. Eine Rente ist kein Kapital. Rechne nichts aus.\n"
        "2. Lieber ein Wort als eine Zahl: \"gut die Hälfte\", \"der grösste Teil\", \"knapp darunter\". Die Tabelle "
        "steht daneben.\n"
        "3. KEINE Empfehlung. Kein \"Sie sollten\", kein \"wir empfehlen\", keine Anlage, kein Produkt.\n"
        "4. Nur diese Kundin oder dieser Kunde. Kein Vergleich mit anderen Fällen, Durchschnitten oder Kunden.\n"
        "5. Behaupte nichts, was nicht dasteht: kein Beruf, keine Familie, keine Absicht, keine Nationalität.\n"
        "6. Keine Aufzählung, keine Nummerierung, keine Überschrift. Nur der Absatz."
    ),
    "en": (
        "You write ONE paragraph for one section of a Swiss financial report.\n"
        "\n"
        "The section already holds tables and figures. Your task is the connecting text: what the reader sees here "
        "and why it matters. Two to three sentences of plain prose, English, factual, British spelling.\n"
        "\n"
        "RULES without exception:\n"
        "1. Only the figures given below, each with its CORRECT label. Debt is debt, not equity. A pension is not "
        "capital. Do not calculate anything.\n"
        "2. Prefer a word to a figure: \"just over half\", \"the largest part\", \"slightly below\". The table is "
        "next to it.\n"
        "3. NO recommendation. No \"you should\", no \"we recommend\", no investment, no product.\n"
        "4. Only this client. No comparison with other cases, averages or clients.\n"
        "5. Claim nothing that is not there: no occupation, no family, no intention, no nationality.\n"
        "6. No list, no numbering, no heading. Only the paragraph."
    ),
}

PROMPT = {
    "de": ("{ask}\n\nAlle Beträge sind Schweizer Franken.{basis} Schreibe zwei bis drei Sätze Fliesstext, beginne direkt "
           "mit dem ersten Satz, ohne Überschrift und ohne diese Anweisung zu wiederholen.\n\nDie Zahlen zu "
           "\u00ab{title}\u00bb:\n{facts}\n"),
    "en": ("{ask}\n\nAll amounts are Swiss francs.{basis} Write two to three sentences of plain prose, start directly with "
           "the first sentence, with no heading and without repeating this instruction.\n\nThe figures for "
           "\u201c{title}\u201d:\n{facts}\n"),
}


def prompt_hash() -> str:
    return content_id("PRM", {"version": PROMPT_VERSION, "system": SYSTEM, "prompt": PROMPT,
                              "basis": voc.BASIS_PROMPT, "mark": voc.BASIS_MARK})


def fact_line(f: Fact, lang: str) -> str:
    """One figure as the model sees it: its label, its printed value and, for a return or goal figure, its
    basis in brackets (REP-27)."""
    mark = f" ({voc.basis_mark(f.basis, lang)})" if f.basis else ""
    return f"- {f.label}: {f.display}{mark}"


def prose_messages(title: str, facts: Sequence[Fact], ask: str, lang: str) -> list[dict[str, str]]:
    lines = "\n".join(fact_line(f, lang) for f in facts)
    bases = sorted({f.basis for f in facts if f.basis})
    basis = "".join(voc.BASIS_PROMPT[b][lang] for b in bases)
    return [{"role": "system", "content": SYSTEM[lang]},
            {"role": "user", "content": PROMPT[lang].format(ask=ask, title=title, facts=lines, basis=basis)}]


def clean(text: str, lang: str) -> str:
    """Presentation removed, never a word: headings, bullets, bold; Swiss orthography for German."""
    out = re.sub(r"^\s{0,3}#{1,6}\s*", "", text or "", flags=re.M)
    out = re.sub(r"^\s{0,4}[-*+\u2022]\s+", "", out, flags=re.M)
    out = out.replace("**", "").replace("__", "")
    if lang == "de":
        out = out.replace("ß", "ss")
    return " ".join(out.split())


_FOREIGN_SCRIPT = ((0x4E00, 0x9FFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF), (0x0400, 0x04FF),
                   (0x0600, 0x06FF), (0x0590, 0x05FF), (0x0900, 0x097F))


def reject_reason(text: str, lang: str, cal: Calibration) -> Optional[str]:
    """Why this draft cannot be used, or ``None``. The checks the number verifier cannot express, each earned
    by an observed draft in ``desktop/sectionprose.py``."""
    low = text.lower()
    rules = cal.reject
    hit = next((b for b in rules.advice[lang] if b in low), None)
    if hit:
        return f"the draft recommends ({hit!r})"
    cur = next((c for c in rules.wrong_currency if c in low + " "), None)
    if cur:
        return f"the draft names another currency ({cur.strip()!r}); every amount here is in francs"
    echo = next((e for e in rules.echoes if e in low), None)
    if echo:
        return f"the draft repeats the instruction ({echo!r})"
    if any(lo <= ord(ch) <= hi for ch in text for lo, hi in _FOREIGN_SCRIPT):
        return "the draft leaves the language"
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > rules.max_upper_share:
        return "the draft is in capitals"
    words = len(text.split())
    if words < cal.prose.min_words:
        return f"the draft is too short ({words} words)"
    if words > cal.prose.max_words:
        return f"the draft is too long ({words} words)"
    return None


# ---------------------------------------------------------------------------
# The number check (REP-03): as chatbot's, against one section's facts
# ---------------------------------------------------------------------------

_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMBER = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?(?!\d)|\d+(?:[.,'\u2019]\d+)*")
_SCALE = re.compile(r"\s*(Mrd\.?|Milliarden?|billion|Mio\.?|Millionen|Million|million|Tausend|thousand)(?![A-Za-z])",
                    re.IGNORECASE)
_SCALE_FACTOR = {"mrd": 1e9, "milliarde": 1e9, "milliarden": 1e9, "billion": 1e9, "mio": 1e6,
                 "millionen": 1e6, "million": 1e6, "tausend": 1e3, "thousand": 1e3}
#: Percent sign or word, and percentage points (a change in a share).
_PERCENT = re.compile(r"\s*(%|Prozentpunkte?\b|Prozent\b|Pp\.|percentage points?\b|percent\b|per cent\b)",
                      re.IGNORECASE)


@dataclass(frozen=True)
class Token:
    text: str
    readings: frozenset[float]
    digits: int
    scale: float = 1.0
    percent: bool = False
    date: Optional[str] = None


def readings(token: str) -> set[float]:
    t = token.strip()
    for ch in ("'", "\u2019", " ", "\u00a0", "\u202f"):
        t = t.replace(ch, "")
    t = t.strip(".,")
    out: set[float] = set()
    if not t:
        return out
    for variant in (t, t.replace(",", "."), t.replace(".", "").replace(",", "."),
                    t.replace(",", "").replace(".", ""), t.replace(",", "")):
        try:
            value = float(variant)
        except ValueError:
            continue
        if math.isfinite(value):
            out.add(value)
    return out


def tokens(text: str) -> list[Token]:
    out: list[Token] = []
    spans: list[tuple[int, int]] = []
    for m in _DATE.finditer(text):
        if m.group(1):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        out.append(Token(text=m.group(0), readings=frozenset(), digits=8, date=f"{y:04d}-{mo:02d}-{d:02d}"))
        spans.append(m.span())
    masked = list(text)
    for a, b in spans:
        masked[a:b] = " " * (b - a)
    rest = "".join(masked)
    for m in _NUMBER.finditer(rest):
        raw = m.group(0)
        values = readings(raw)
        if not values:
            continue
        scale = _SCALE.match(rest, m.end())
        factor = _SCALE_FACTOR[scale.group(1).rstrip(".").lower()] if scale else 1.0
        out.append(Token(text=raw.strip(), readings=frozenset(values), digits=sum(c.isdigit() for c in raw),
                         scale=factor, percent=bool(_PERCENT.match(rest, m.end()))))
    return out


def _rounded(f: float, decimals: Sequence[int]) -> set[float]:
    out = {f}
    for d in decimals:
        out.add(round(f, d))
        out.add(float(Decimal(repr(f)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)))
    return out


def matches(tok: Token, value: float, decimals: Sequence[int], tol: float) -> bool:
    """``tok`` is a legitimate rendering of ``value``: itself or rounded; scaled only with the scale word; as a
    percentage only with a percent sign and only for a share (a value of at most one)."""
    v = abs(float(value))
    targets = [v / tok.scale] if tok.scale > 1 else [v]
    if tok.percent and v <= 1.0:
        targets.append(100.0 * v)
    candidates: set[float] = set()
    for t in targets:
        candidates |= _rounded(t, decimals)
    return any(a == c or abs(a - c) <= tol * max(a, c) for a in (abs(r) for r in tok.readings) for c in candidates)


def allowed(facts: Iterable[Fact]) -> tuple[list[tuple[float, str]], list[tuple[str, str]]]:
    """The values and dates a section's prose may quote, each with its fact id."""
    values: list[tuple[float, str]] = []
    dates: list[tuple[str, str]] = []
    for f in facts:
        for v in (f.value, f.previous):
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                values.append((abs(float(v)), f.fact_id))
            elif f.unit == "date":
                dates.append((str(v)[:10], f.fact_id))
                values.append((float(str(v)[:4]), f.fact_id))
        for tok in tokens(f.display):
            if tok.date:
                dates.append((tok.date, f.fact_id))
            elif not tok.percent:
                # A printed percentage ("45,0 %") is the share already in ``value``, which matches only a
                # rendering with its percent sign; admitting the bare digits would let "45 Rollen" pass.
                values.extend((abs(r) * tok.scale, f.fact_id) for r in tok.readings)
    return values, dates


def unverified_numbers(text: str, facts: Sequence[Fact], cal: Calibration) -> tuple[str, ...]:
    """Numbers in ``text`` that match none of ``facts``. Empty means every figure came from the code."""
    nc = cal.number_check
    values, dates = allowed(facts)
    bad: list[str] = []
    for tok in tokens(text):
        if tok.date:
            if not any(d == tok.date for d, _ in dates):
                bad.append(tok.text)
            continue
        if tok.digits < nc.min_checked_digits:
            continue
        if not any(matches(tok, v, nc.rounding_decimals, nc.relative_tolerance) for v, _ in values):
            bad.append(tok.text)
    return tuple(dict.fromkeys(bad))
