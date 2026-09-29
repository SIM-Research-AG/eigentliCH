"""A decision as a person reads it: plain sentences, the house's names, Swiss figures (EIG-64).

Decisions are append-only, and many were written with the store's own words: field keys ("label: a → b",
"time_basis"), role keys ("61,000 CHF, protection"), fact keys ("Ja: health, network_people") and English figures.
Nothing is rewritten in the store. ``render`` reads the stored text and says it again in the reader's language:
each field by its name, each value in words (a role by its name from ``reference/roles``, a date as 31.12.2055,
an amount as 61’000 CHF), and leaves a text it does not recognise as it is. ``changes`` writes a new decision's
change list in the same plain words, so new decisions need no reading-again.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Optional

APOSTROPHE = "’"   # the Swiss thousands mark, as the browser's de-CH format writes it

FIELDS: dict[str, dict[str, str]] = {
    "label": {"de": "Bezeichnung", "en": "Name"},
    "description": {"de": "Beschreibung", "en": "Description"},
    "magnitude": {"de": "Betrag", "en": "Amount"},
    "magnitude_unit": {"de": "Einheit", "en": "Unit"},
    "time_basis": {"de": "Zeitbasis", "en": "Time basis"},
    "started_on": {"de": "Beginn", "en": "Start"},
    "liquidity": {"de": "Verfügbarkeit", "en": "Availability"},
    "stock_kind": {"de": "Vermögen oder Schuld", "en": "Asset or liability"},
    "owner": {"de": "Gehört zu", "en": "Belongs to"},
    "role": {"de": "Rolle", "en": "Role"},
    "capital_type": {"de": "Art des Kapitals", "en": "Kind of capital"},
    "vessel": {"de": "Gefäss", "en": "Vessel"},
    "tags": {"de": "Gefäss", "en": "Vessel"},
    "name": {"de": "Name", "en": "Name"},
    "target_amount": {"de": "Betrag", "en": "Amount"},
    "target_date": {"de": "Bis wann", "en": "By when"},
    "template": {"de": "Vorlage", "en": "Template"},
    "occupancy": {"de": "Nutzung", "en": "Use"},
    "contribution_share": {"de": "Anteil am jährlichen Sparbetrag", "en": "Share of the yearly saving"},
    "amount_basis": {"de": "Betrag in", "en": "Amount in"},
    "safety": {"de": "Sicherheit", "en": "Safety"},
    "liquidity_need": {"de": "Liquiditätsbedarf", "en": "Liquidity need"},
    "volatility_tolerance": {"de": "Schwankungstoleranz", "en": "Volatility tolerance"},
    "horizon": {"de": "Horizont", "en": "Horizon"},
    "flexibility": {"de": "Flexibilität", "en": "Flexibility"},
    "active": {"de": "Im laufenden Plan", "en": "In the running plan"},
}

#: The facts the first conversation states, by the name a person knows them by.
FACTS: dict[str, dict[str, str]] = {
    "canton": {"de": "Wohnkanton", "en": "Canton"},
    "civil_status": {"de": "Zivilstand", "en": "Civil status"},
    "education": {"de": "Ausbildung", "en": "Education"},
    "network_people": {"de": "Berufliches Netzwerk", "en": "Professional network"},
    "health": {"de": "Belastbarkeit", "en": "Resilience"},
    "matrimonial_regime": {"de": "Güterstand", "en": "Marital property regime"},
    "self_employed_form": {"de": "Form der Selbständigkeit", "en": "Form of self-employment"},
    "pillar2_voluntary": {"de": "Freiwillige Einzahlung in die Pensionskasse", "en": "Voluntary pension-fund payments"},
    "qualification_highest": {"de": "Höchster Abschluss", "en": "Highest qualification"},
    "qualification_year": {"de": "Jahr des Abschlusses", "en": "Year of the qualification"},
    "years_in_field": {"de": "Jahre im Tätigkeitsfeld", "en": "Years in the field"},
    "kader": {"de": "Führungsfunktion", "en": "Management role"},
    "sector": {"de": "Branche", "en": "Sector"},
    "network_reach": {"de": "Reichweite des Netzwerks", "en": "Reach of the network"},
    "hours_learning": {"de": "Stunden für Weiterbildung", "en": "Hours of learning"},
    "hours_network": {"de": "Stunden für Kontakte", "en": "Hours of networking"},
    "annual_contribution": {"de": "Jährlicher Sparbetrag", "en": "Yearly saving"},
}

VALUES: dict[str, dict[str, dict[str, str]]] = {
    "liquidity": {"immediate": {"de": "sofort verfügbar", "en": "available at once"},
                  "within_months": {"de": "innert Monaten", "en": "within months"},
                  "within_years": {"de": "innert Jahren", "en": "within years"},
                  "illiquid": {"de": "gebunden", "en": "tied up"}},
    "stock_kind": {"asset": {"de": "Vermögen", "en": "asset"}, "liability": {"de": "Schuld", "en": "liability"}},
    "vessel": {"free": {"de": "frei", "en": "free"},
               "pillar_2": {"de": "Pensionskasse / Freizügigkeit", "en": "pension fund / vested benefits"},
               "pillar_3a": {"de": "Säule 3a", "en": "pillar 3a"}, "real_asset": {"de": "Sachwert", "en": "real asset"}},
    "occupancy": {"owner_occupied_primary": {"de": "selbst bewohnt", "en": "lived in by you"},
                  "second_or_holiday_home": {"de": "Zweit- oder Ferienobjekt", "en": "second or holiday home"},
                  "let_to_someone_else": {"de": "vermietet", "en": "let"}},
    "magnitude_unit": {"chf": {"de": "CHF (Bestand)", "en": "CHF (stock)"},
                       "chf_per_year": {"de": "CHF pro Jahr", "en": "CHF per year"},
                       "share_of_total": {"de": "Anteil am Ganzen", "en": "share of the total"}},
    "capital_type": {"human": {"de": "menschliches Kapital", "en": "human capital"},
                     "financial": {"de": "finanzielles Kapital", "en": "financial capital"}},
    "owner": {"client": {"de": "Ihnen", "en": "you"}, "partner": {"de": "Partnerin oder Partner", "en": "partner"}},
    "amount_basis": {"today": {"de": "heutigen Franken", "en": "today's francs"},
                     "future": {"de": "Franken des Zieldatums", "en": "francs of the target date"}},
    "active": {"True": {"de": "ja", "en": "yes"}, "False": {"de": "nein", "en": "no"}},
}

WORDS = {
    "new": {"de": "neu {v}", "en": "now {v}"},
    "changed": {"de": "neu {v}, bisher {old}", "en": "now {v}, was {old}"},
    "removed": {"de": "entfernt, bisher {old}", "en": "removed, was {old}"},
    "none": {"de": "keine Änderung", "en": "no change"},
    "funding": {"de": "Finanzierung angepasst", "en": "funding changed"},
}

_EMPTY = ("", "—", "None", "null", "{}", "[]")
_ROLES = ("growth", "gain", "income", "stabilisation", "protection")


def number(value: float, decimals: int = 0) -> str:
    """A Swiss figure: 61’000, 1’250.5; a negative with a minus sign."""
    if decimals == 0 and abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", APOSTROPHE)
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", APOSTROPHE)


def _as_number(text: str) -> Optional[float]:
    t = text.strip().replace(APOSTROPHE, "").replace("'", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):          # 61,000 (the English format)
        t = t.replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t)
    return None


class Renderer:
    """Renders values and decisions in ``lang``; ``roles`` maps a role key to ``{human, financial}`` names."""

    def __init__(self, lang: str = "de", roles: Optional[dict[str, dict[str, str]]] = None,
                 templates: Optional[dict[str, str]] = None, facts: Optional[dict[str, str]] = None):
        self.lang = lang if lang in ("de", "en") else "de"
        self.roles = roles or {}
        self.templates = templates or {}
        self.facts = facts or {}

    # ---------------------------------------------------------------- names

    def field(self, key: str) -> str:
        return (FIELDS.get(key) or {}).get(self.lang) or key.replace("_", " ")

    def fact(self, key: str) -> str:
        return self.facts.get(key) or (FACTS.get(key) or {}).get(self.lang) or key.replace("_", " ")

    def role(self, key: str, capital: Optional[str] = None) -> str:
        names = self.roles.get("growth" if key == "gain" else key) or {}
        if capital in ("human", "financial") and names.get(capital):
            return names[capital]
        unique = list(dict.fromkeys(v for v in (names.get("human"), names.get("financial")) if v))
        return " · ".join(unique) if unique else key

    # ---------------------------------------------------------------- values

    def value(self, field: str, raw: Any, capital: Optional[str] = None) -> Optional[str]:
        """A value in words; None for an empty one."""
        if raw is None:
            return None
        if isinstance(raw, dict):
            if field == "tags" or "vessel" in raw:
                return self.value("vessel", raw.get("vessel"))
            return None if not raw else ", ".join(f"{k}: {v}" for k, v in raw.items())
        text = str(raw).strip()
        if text in _EMPTY:
            return None
        if field == "tags":
            m = re.search(r"'vessel':\s*'([a-z_0-9]+)'", text)
            return self.value("vessel", m.group(1)) if m else None
        if field == "role":
            return self.role(text, capital)
        if field == "template":
            return self.templates.get(text) or text
        if field in VALUES:
            return (VALUES[field].get(text) or {}).get(self.lang) or text
        if field in ("target_date", "started_on"):
            try:
                return date.fromisoformat(text[:10]).strftime("%d.%m.%Y")
            except ValueError:
                return text
        n = _as_number(text) if not isinstance(raw, bool) else None
        if n is not None:
            if field == "contribution_share":
                return f"{number(n * 100, 1)} %"
            if field == "target_amount":
                return f"{number(n)} CHF"
            return number(n, 2)
        if field in ("label", "name", "description", "time_basis"):
            return f"«{text}»"
        return text

    def change(self, field: str, old: Any, new: Any, capital: Optional[str] = None) -> str:
        o, n = self.value(field, old, capital), self.value(field, new, capital)
        if o == n:
            return ""
        if n is None:
            what = WORDS["removed"][self.lang].format(old=o)
        elif o is None:
            what = WORDS["new"][self.lang].format(v=n)
        else:
            what = WORDS["changed"][self.lang].format(v=n, old=o)
        return f"{self.field(field)}: {what}"

    def changes(self, old: dict[str, Any], new: dict[str, Any], capital: Optional[str] = None) -> str:
        """A change list in plain words ("Bezeichnung: neu «Lohn», bisher «angestellt». Betrag: neu 96’000")."""
        parts = [self.change(k, old.get(k), v, capital) for k, v in new.items() if old.get(k) != v]
        parts = [p for p in parts if p]
        return ". ".join(parts) if parts else WORDS["none"][self.lang]

    # ---------------------------------------------------------------- stored texts

    def choice(self, text: Optional[str], capital: Optional[str] = None) -> Optional[str]:
        """A stored choice in plain words, or the text as it is when it is not one of the store's formats."""
        if not text:
            return text
        # "label: a → b; time_basis: — → 40 Std./Woche" (the app's change list before EIG-64)
        pairs = re.findall(r"(?:^|; )([a-z_]+): (.*?) → (.*?)(?=; [a-z_]+: |$)", text)
        if pairs and text.startswith(pairs[0][0] + ": "):
            parts = [self.change(k, o, n, capital) for k, o, n in pairs]
            return ". ".join(p for p in parts if p) or WORDS["none"][self.lang]
        # "target_amount=62000, target_date=2055-12-31, template=unspecified"
        kv = re.findall(r"(?:^|, )([a-z_]+)=([^,]*)", text)
        if kv and re.fullmatch(r"[a-z_]+=[^,]*(, [a-z_]+=[^,]*)*", text):
            parts = [f"{self.field(k)}: {self.value(k, v, capital) or '—'}" for k, v in kv]
            return ", ".join(parts)
        # "61,000 CHF, protection" (a stock in francs and its role)
        m = re.fullmatch(r"(-?[\d,.'’]+) CHF, ([a-z_]+)", text)
        if m and m.group(2) in _ROLES and _as_number(m.group(1)) is not None:
            return f"{number(_as_number(m.group(1)))} CHF, {self.role(m.group(2), capital or 'financial')}"
        # "Ja: health, network_people" (facts restated)
        m = re.fullmatch(r"(Ja|Nein|Yes|No): ([a-z_]+(?:, [a-z_]+)*)", text)
        if m and any(k in FACTS or k in self.facts for k in m.group(2).split(", ")):
            head = {"Ja": "Ja", "Nein": "Nein", "Yes": "Ja", "No": "Nein"}[m.group(1)] if self.lang == "de" else \
                {"Ja": "Yes", "Nein": "No", "Yes": "Yes", "No": "No"}[m.group(1)]
            return f"{head}: " + ", ".join(self.fact(k) for k in m.group(2).split(", "))
        return text

    def question(self, text: Optional[str]) -> Optional[str]:
        """A stored question with a fact key in guillemets («health») said by the fact's name."""
        if not text:
            return text
        return re.sub(r"«([a-z][a-z0-9_]*)»", lambda m: f"«{self.fact(m.group(1))}»"
                      if (m.group(1) in FACTS or m.group(1) in self.facts) else m.group(0), text)

    def decision(self, d: dict[str, Any], capital: Optional[str] = None) -> dict[str, Any]:
        return {**d, "question_text": self.question(d.get("question")), "choice_text": self.choice(d.get("choice"), capital),
                "reasoning_text": d.get("reasoning")}


def role_names(roles: dict[str, Any], lang: str, fallback: Callable[[str, str], Optional[str]]) -> dict[str, dict[str, str]]:
    """``reference/roles`` (``{key: spec}``) as ``{role: {human, financial}}`` names in ``lang``."""
    out: dict[str, dict[str, str]] = {}
    for key in ("growth", "income", "stabilisation", "protection"):
        spec = (roles.get(key) or {}).get("display") or {}
        out[key] = {}
        for cap in ("human", "financial"):
            name = (spec.get(cap) or {}).get(lang) if isinstance(spec.get(cap), dict) else None
            out[key][cap] = name or fallback(key, cap) or key
    return out
