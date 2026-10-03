"""The life balance sheet and the four capitals as the pages draw them (VISUALS_INTERFACES.md, EIG-70 to EIG-72).

Pure. Nothing is computed that the engines did not compute: the parts of the picture are lbs's own figures
(``totals.by_vessel``, ``totals.human_assets``, ``totals.liabilities``, ``totals.net_worth``, the goals' amounts of
``real_view``), the capitals today are lbs's ``human_capital[]`` values, and the capitals over time are lbsim's
``regimes[].capitals`` bands as published. What this adds is the names the client gave (never an id), the page's
one language, and the K3 rule: when an adult's health is withheld, the health figure and the health band do not
leave the server, and the page says that it is withheld instead of drawing it.
"""

from __future__ import annotations

from typing import Any, Optional

#: lbs's ``engine.WITHHELD``: the reason an ``H`` is absent when K3 data was filtered or erased.
LBS_WITHHELD = "K3 data was filtered or erased"

#: The parts of the asset column, in the order they are stacked: lbs's vessels, then what states no vessel.
VESSEL_PARTS = ("free", "pillar_2", "pillar_3a", "real_asset", "not_stated")

#: The three model levels and their keys on each side (lbs ``E``/``N``/``H``; lbsim ``expertise``/...).
CAPITALS = (("expertise", "E"), ("network", "N"), ("health", "H"))

#: lbs's scales for today's levels: the human-capital record puts E under a ceiling of 1.0 and reads N and H
#: as stocks in [0, 1] (``seed_records/human-capital.json``).
LBS_SCALE = {"min": 0.0, "max": 1.0}

QUANTILES = ("p10", "p25", "p50", "p75", "p90")


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def withheld_persons(request: Optional[dict[str, Any]]) -> set[str]:
    """The persons whose health the client withheld (K3), from the lbs request the app sent."""
    persons = (((request or {}).get("household") or {}).get("persons")) or []
    return {str(p.get("person_id")) for p in persons
            if isinstance(p, dict) and ((p.get("human_capital") or {}).get("health_withheld") is True)}


def balance(sheet: dict[str, Any], goal_names: dict[str, str]) -> dict[str, Any]:
    """The balance sheet as a graph: the assets by vessel and the human capital against the debts, the net
    worth, and the goals' claims in both bases (lbs's real view). A part lbs left open is left out, never
    drawn as zero; a goal stated a year (retirement) is named, not stacked with the stocks."""
    totals = sheet.get("totals") or {}
    by_vessel = totals.get("by_vessel") or {}
    assets = [{"part": part, "chf": _num(by_vessel.get(part))} for part in VESSEL_PARTS
              if _num(by_vessel.get(part))]
    if _num(totals.get("human_assets")):
        assets.append({"part": "human", "chf": _num(totals.get("human_assets"))})
    rv = sheet.get("real_view") if isinstance(sheet.get("real_view"), dict) else None
    claims, yearly = [], []
    for g in (rv or {}).get("goals") or []:
        if not isinstance(g, dict):
            continue
        name = goal_names.get(g.get("goal_id"))
        if g.get("unit") == "chf_per_year":
            yearly.append(name)
            continue
        nominal, real = g.get("nominal") or {}, g.get("real") or {}
        if _num(nominal.get("amount")) is None and _num(real.get("amount")) is None:
            continue
        claims.append({"name": name, "nominal": _num(nominal.get("amount")), "real": _num(real.get("amount")),
                       "date": nominal.get("as_at")})
    return {"assets": assets, "financial_assets": _num(totals.get("financial_assets")),
            "human_assets": _num(totals.get("human_assets")), "total_assets": _num(totals.get("total_assets")),
            "liabilities": _num(totals.get("liabilities")), "net_worth": _num(totals.get("net_worth")),
            "claims": claims, "yearly_goals": yearly, "claims_available": rv is not None}


def capitals_today(sheet: dict[str, Any], persons: dict[str, str], withheld: set[str]) -> dict[str, Any]:
    """Today's capitals per adult from lbs: expertise, network and health on lbs's scale of 0 to 1, with the
    household's wealth beside them (lbs states wealth for the household, not per adult). A withheld health is
    ``None`` with ``health_withheld`` true; an unknown one is ``None`` alone."""
    adults = []
    for hc in sheet.get("human_capital") or []:
        if not isinstance(hc, dict):
            continue
        pid = str(hc.get("person_id"))
        held = pid in withheld or (hc.get("H") or {}).get("absent_because") == LBS_WITHHELD
        row: dict[str, Any] = {"name": persons.get(pid), "health_withheld": held}
        for name, key in CAPITALS:
            row[name] = None if (name == "health" and held) else _num((hc.get(key) or {}).get("value"))
        adults.append(row)
    totals = sheet.get("totals") or {}
    return {"adults": adults, "scale": dict(LBS_SCALE),
            "wealth": {"net_worth": _num(totals.get("net_worth")),
                       "financial_assets": _num(totals.get("financial_assets"))}}


def capitals_over_time(raw: Any, persons: dict[str, str], lang: str, withheld: set[str]) -> Optional[dict[str, Any]]:
    """lbsim's ``regimes[].capitals`` for the page: the principal's name instead of the id, the labels in the
    page's language, each band with its scale. ``None`` when lbsim sent none (an artefact made before the field).
    The health band is dropped when the principal's health is withheld (K3)."""
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("person_id"))
    held = pid in withheld
    labels = raw.get("labels") or {}
    scale = raw.get("scale") or {}
    series = {}
    for name, _ in CAPITALS:
        bands = raw.get(name)
        if name == "health" and held:
            continue
        if not isinstance(bands, dict) or not isinstance(bands.get("p50"), list):
            continue
        sc = scale.get(name) or {}
        label = labels.get(name) or {}
        series[name] = {"bands": {q: bands.get(q) for q in QUANTILES if isinstance(bands.get(q), list)},
                        "scale": {"min": _num(sc.get("min")) if _num(sc.get("min")) is not None else 0.0,
                                  "max": _num(sc.get("max"))},
                        "label": label.get(lang) if isinstance(label, dict) else None}
    return {"name": persons.get(pid), "health_withheld": held, "series": series}
