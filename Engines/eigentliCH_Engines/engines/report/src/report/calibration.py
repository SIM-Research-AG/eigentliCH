"""Calibration: prose generation, the number check, the reject rules, the listing threshold and the asks.

``1.0.0``
    The first production set. Temperature 0 and a fixed seed: the prose describes, it does not compose, and
    a creative model invents figures (prior art ``desktop/prose.py``). Two drafts per section, as
    ``desktop/sectionprose.ATTEMPTS``: fabrication is occasional and stochastic, so a failed check is
    redrafted, not published and not silently dropped. Twelve to 140 words, and the reject phrases, currencies
    and echoes of ``sectionprose._reject``, each earned by an observed draft there, with their English
    counterparts. Positions are listed from a weight of 0.05 % (``dossier.py`` prints ``weight > 0.0005``).

A seed can never be changed in place. To change a value, propose a new version through ``PUT /calibration``.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Calibration, NumberCheck, ProseGeneration, RejectRules

SLOTS: dict[str, dict[str, str]] = {
    "changes": {
        "de": "Beschreibe, was sich seit dem letzten Bericht verändert hat und was gleich geblieben ist. Nenne die "
              "grösste Veränderung zuerst.",
        "en": "Describe what has changed since the previous report and what has stayed the same. Name the largest "
              "change first.",
    },
    "balance_sheet": {
        "de": "Beschreibe, wie sich dieses Vermögen zusammensetzt und was davon tatsächlich verfügbar ist. Der Punkt "
              "ist der Unterschied zwischen Vermögen und entnahmefähigem Vermögen.",
        "en": "Describe how this wealth is made up and how much of it is actually available. The point is the "
              "difference between wealth and what can be drawn on.",
    },
    "income": {
        "de": "Beschreibe, welches Einkommen dieser Haushalt pro Jahr hat und woher es kommt.",
        "en": "Describe the yearly income of this household and where it comes from.",
    },
    "pensions": {
        "de": "Beschreibe, welche Renten ab der Referenzaltersgrenze bestehen, ohne dass jemand etwas entscheidet, "
              "und was davon nicht bestimmt werden konnte.",
        "en": "Describe which pensions exist from the reference age without anyone deciding anything, and what of "
              "them could not be determined.",
    },
    "property": {
        "de": "Beschreibe den Befund zum Wohneigentum: was verlangt ist und ob die Mittel es tragen.",
        "en": "Describe the finding on home ownership: what is asked for and whether the means carry it.",
    },
    "mandate": {
        "de": "Beschreibe, woraus der Mandatsvorschlag abgeleitet ist und was er vom Portfolio verlangt. Er ist ein "
              "Vorschlag, nicht freigegeben.",
        "en": "Describe what the mandate proposal is derived from and what it asks of the portfolio. It is a "
              "proposal, not released.",
    },
    "retirement": {
        "de": "Beschreibe das Verhältnis zwischen dem Bedarf im Ruhestand und dem, was ihn deckt. Wenn keine Lücke "
              "besteht, sage das.",
        "en": "Describe how the need in retirement compares with what covers it. If there is no gap, say so.",
    },
    "allocation": {
        "de": "Beschreibe, was diese Allokation ist: ein Modellergebnis für ein Mandat, noch nicht freigegeben. "
              "Nenne, auf wie viele Bausteine sich das Gewicht verteilt.",
        "en": "Describe what this allocation is: a model result for a mandate, not yet released. Say across how "
              "many building blocks the weight is spread.",
    },
    "roles": {
        "de": "Beschreibe, wie sich das Gewicht auf die vier Rollen verteilt und welche Rolle am meisten trägt.",
        "en": "Describe how the weight is spread across the four roles and which role carries the most.",
    },
    "fit": {
        "de": "Beschreibe, wie viel die Gewichte am Ergebnis des Optimierers ändern und was das über die Rolle der "
              "Schranken sagt. Keine Wertung.",
        "en": "Describe how much the weights change the optimiser's result and what that says about the role of "
              "the bounds. No judgement.",
    },
}

PRODUCTION = Calibration(
    version="1.0.0",
    note=("First production set: temperature 0, seed 7, 400 output tokens, two drafts per section, 12 to 140 words; "
          "numbers of two or more digits checked against the section's own facts; positions listed from 0.05 %."),
    prose=ProseGeneration(max_tokens=400, temperature=0.0, seed=7, attempts=2, min_words=12, max_words=140),
    number_check=NumberCheck(min_checked_digits=2, rounding_decimals=(0, 1, 2), relative_tolerance=1e-9),
    reject=RejectRules(
        advice={
            "de": ("sie sollten", "wir empfehlen", "ich empfehle", "empfehlenswert", "raten wir", "sie müssen",
                   "am besten wäre", "ratsam"),
            "en": ("you should", "we recommend", "i recommend", "is advisable", "we advise", "you must",
                   "it would be best"),
        },
        wrong_currency=("euro", "€", "eur ", "dollar", "usd", "us-dollar", "pfund", "pound", "gbp", "yen"),
        echoes=("abschnitt:", "aufgabe:", "die zahlen:", "regeln ohne ausnahme", "section:", "task:",
                "the figures:", "rules without exception"),
        max_upper_share=0.5,
    ),
    position_min_weight=0.0005,
    slots=SLOTS,
)

SEEDS: tuple[Calibration, ...] = (PRODUCTION,)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
