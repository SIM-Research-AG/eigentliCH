"""The questionnaires aligned to the scoring maps (owner decision of 29.09.2026, EIG-44 and EIG-45).

The seed reported 19 of 169 binds that did not meet their question (``scoring_bind_check``). The owner
decided to change the **questionnaires**, never the maps: every string a map scores must be an answer the
bound question can produce. ``align`` saves the aligned questionnaires as new content versions, saved by a
curator (``saved_by_kind = 'curator'``) with the note ``NOTE``. The changes are patches on the current
version, so a wording edit made since is kept, and a second run writes nothing.

Two small additions to the questionnaire format carry it (SCHEMA.md section 6):

* ``multi_choice``: several options at once; the answer is the list of chosen option values.
* ``offered: false`` on an option: a value that stays a valid answer (earlier answers, the offline intake
  form's files, the onboarding's numeric answers) but is not offered for a new answer. Used where the maps
  score two vocabularies for one question and offering both would show overlapping bands.

What changes (each item names the binds it resolves):

intake ``goal_confidence`` (3)
    options are the four the map scores, as the original questionnaire (onb 0.1.3) worded them: ``70 %``,
    ``80 %``, ``90 %``, ``95 %``; ``fest`` and ``eine Idee`` (the offline form's words, not scored) stay
    valid, not offered. The question is the original's wording.
intake ``education_hours`` (5)
    a new choice question in section 16, after ``education_recent``, with the map's five bands; question
    and why carried from onb 0.1.3.
intake ``esg_exclusions`` (7)
    ``multi_choice`` over the seven exclusions the map offers, instead of free text.
intake ``health`` (1)
    option ``1`` added, not offered: the value the onboarding's numeric health answer gives for full
    health; ``1 — sehr gut`` stays the offered option for it.
intake ``rest_hours`` (3)
    offered: the map's five non-overlapping bands (``kaum welche``, ``5–10``, ``10–20``, ``20–30``,
    ``mehr als 30``, as onb 0.1.3); the offline form's ``unter 10`` and ``über 30`` stay valid, not offered.
onboarding ``annual_contribution`` (EIG-45)
    a new number question, CHF per year, min 0, after every existing question.

After the use cases (``revise``, EIG-53 and EIG-58; ``python -m eigentlich revise-content``), the intake's next
version ``intake@1.3``:

intake section ``21``, the partner (EIG-53)
    ``partner_in_plan`` (ja / nein) and, asked when it is ``ja``: the partner's age, gross salary, working hours,
    missing AHV years and human-capital answers (qualification, its year, years in the field, training,
    network and its reach, mandates, health as K3, rest), on the scales of the client's own questions. Placed
    after section 16 (the client's own human capital). ``inputs.py`` sends them as the partner's person.
intake ``hours_learning`` dropped (EIG-58)
    ``education_hours`` (the band) stays; answers given to earlier versions stay and are still read.

For the nominal and real view (``revise_basis``, EIG-60 and EIG-61; also run by ``revise-content``), the
onboarding's next version ``onb2@0.3.0``:

onboarding ``contribution_indexed`` (EIG-61)
    "Steigt der Betrag mit der Teuerung?" after ``annual_contribution``: ``nein`` (the default, owner decision 9:
    fixed in francs) or ``ja``. ``inputs.py`` sends it as ``mandate.contribution_indexed``.
onboarding ``goal_amount_basis`` (EIG-60)
    "Ist der Betrag in heutigen Franken?", asked per goal (``scope: goal``), not in the sequence: the plan page's
    goal form and the onboarding's completion read its wording. ``today`` (the default, owner decision 7) or
    ``future``; stored on the goal (``goal.amount_basis``), sent as ``goals[].amount_basis``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from . import store

ONBOARDING = "questionnaire/onboarding"
INTAKE = "questionnaire/intake"

NOTE = "aligned to scoring maps, owner 29.09.2026"

DASH = "—"      # the maps' em dash, as in "90 % — es muss halten"
EN = "–"        # the maps' en dash, as in "5–10"


def _opt(value: str, label: Optional[str] = None, offered: bool = True) -> dict[str, Any]:
    o: dict[str, Any] = {"value": value, "label": {"de": label or value}}
    if not offered:
        o["offered"] = False
    return o


GOAL_CONFIDENCE_OPTIONS = [
    _opt(f"70 % {DASH} ich kann nachjustieren"),
    _opt("80 %"),
    _opt(f"90 % {DASH} es muss halten"),
    _opt(f"95 % {DASH} kein Spielraum"),
    _opt("fest", offered=False),
    _opt("eine Idee", offered=False),
]

EDUCATION_HOURS = {
    "key": "education_hours", "type": "choice", "section": "16", "required": False,
    "question": {"de": "Wie viele Stunden pro Woche könnten Sie realistisch fürs Lernen aufwenden?"},
    "why": {"de": f"Die Rendite auf Lernzeit sättigt bei etwa 20 Stunden pro Woche {DASH} darunter zählt jede "
                  "Stunde deutlich, darüber kaum noch."},
    "options": [_opt("kaum welche"), _opt(f"1{EN}2"), _opt(f"3{EN}5"), _opt(f"5{EN}10"), _opt("mehr als 10")],
    "provenance": "carried from questions-onb-0.1.3.json; bands as scoring/intake-scales learning_commitment.hours",
}

ESG_EXCLUSIONS_OPTIONS = [_opt(v) for v in (
    "Waffen", "Fossile Energie", "Tabak", "Kernkraft", "Glücksspiel", "Tierversuche",
    "Kinderarbeit in der Lieferkette")]

ESG_EXCLUSIONS_WHY = ("Wählen Sie, was für Sie nicht in Frage kommt; mehrere Angaben sind möglich. Eine "
                      "Ausschlussliste verkleinert die Auswahl und kann ein Ziel schwerer erreichbar machen; "
                      "das wird Ihnen dann gesagt und nicht stillschweigend gelockert.")

REST_HOURS_OPTIONS = [
    _opt("kaum welche"),
    _opt("unter 10", offered=False),
    _opt(f"5{EN}10"),
    _opt(f"10{EN}20"),
    _opt(f"20{EN}30"),
    _opt("über 30", offered=False),
    _opt("mehr als 30"),
]

ANNUAL_CONTRIBUTION = {
    "key": "annual_contribution", "type": "number", "unit": "chf_per_year", "min": 0, "required": False,
    "question": {"de": "Wie viel können Sie pro Jahr zur Seite legen?",
                 "en": "How much can you put aside each year?"},
    "why": {"de": "Mit einem jährlichen Betrag berechnet die Bilanz, welche Rendite Ihr Ziel verlangt und wie der "
                  "Weg dorthin aussieht. Ohne ihn bleibt das offen.",
            "en": "With a yearly amount the balance sheet works out what return your goal requires and what the "
                  "path there looks like. Without it, that stays open.", "en_draft": True},
    "provenance": "new",
    "_note": "Owner decision 29.09.2026 (EIG-45): read into lbs-request mandate.annual_contribution. Ordered "
             "after every existing question, as the five_keys were, so the light-intake floor does not move.",
}


def _question(body: dict[str, Any], key: str) -> Optional[dict[str, Any]]:
    return next((q for q in body.get("questions") or [] if q.get("key") == key), None)


def _set_options(body: dict[str, Any], key: str, options: list[dict[str, Any]]) -> None:
    q = _question(body, key)
    if q is None:
        raise ValueError(f"the questionnaire has no question {key!r} to align")
    q["options"] = copy.deepcopy(options)


def _insert_after(body: dict[str, Any], after: Optional[str], question: dict[str, Any]) -> None:
    """Add ``question`` once, ordered right after ``after`` (at the end when None). A fractional order keeps
    every existing question's order as it is (answers and scoring refer to keys, the order is display)."""
    if _question(body, question["key"]) is not None:
        return
    orders = [q.get("order", 0) for q in body.get("questions") or []]
    if after is None:
        order: float = (max(orders) if orders else 0) + 1
    else:
        anchor = _question(body, after)
        if anchor is None:
            raise ValueError(f"the questionnaire has no question {after!r} to place {question['key']!r} after")
        later = sorted(o for o in orders if o > anchor.get("order", 0))
        order = (anchor.get("order", 0) + later[0]) / 2 if later else anchor.get("order", 0) + 1
    q = copy.deepcopy(question)
    q["order"] = int(order) if float(order).is_integer() else order
    body["questions"].append(q)


def aligned_intake(body: dict[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(body)
    confidence = _question(new, "goal_confidence")
    if confidence is None:
        raise ValueError("the intake has no goal_confidence")
    confidence["question"] = {"de": "Falls Sie später eine Risikoprüfung wünschen: wie sicher müsste Ihr "
                                    "wichtigstes Ziel dann erreicht werden?"}
    _set_options(new, "goal_confidence", GOAL_CONFIDENCE_OPTIONS)
    _insert_after(new, "education_recent", EDUCATION_HOURS)
    esg = _question(new, "esg_exclusions")
    if esg is None:
        raise ValueError("the intake has no esg_exclusions")
    esg["type"] = "multi_choice"
    esg["why"] = {"de": ESG_EXCLUSIONS_WHY}
    esg.pop("multiline", None)
    esg.pop("placeholder", None)
    _set_options(new, "esg_exclusions", ESG_EXCLUSIONS_OPTIONS)
    health = _question(new, "health")
    if health is None:
        raise ValueError("the intake has no health")
    if not any(o.get("value") == "1" for o in health.get("options") or []):
        opts = list(health.get("options") or [])
        at = next((i + 1 for i, o in enumerate(opts) if str(o.get("value", "")).startswith("1 ")), 0)
        opts.insert(at, _opt("1", offered=False))
        health["options"] = opts
    _set_options(new, "rest_hours", REST_HOURS_OPTIONS)
    new["version"] = "intake@1.2"
    return new


def aligned_onboarding(body: dict[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(body)
    _insert_after(new, None, ANNUAL_CONTRIBUTION)
    if new.get("version") == "onb2@0.1.0":
        new["version"] = "onb2@0.2.0"
    return new


ALIGNMENTS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    INTAKE: aligned_intake,
    ONBOARDING: aligned_onboarding,
}


# ---------------------------------------------------------------------------------------------------------
# The owner's changes after the use cases (29.09.2026): the partner section (EIG-53), hours_learning dropped
# (EIG-58). Saved as the intake's next version by the owner's curator record, as the alignment was.
# ---------------------------------------------------------------------------------------------------------

REVISION_NOTE = "partner section added, hours_learning dropped, owner 29.09.2026"

PARTNER_SECTION = {
    "key": "21", "order": 16.5,
    "title": {"de": "Ihre Partnerin oder Ihr Partner", "en": "Your partner"},
    "lede": {"de": "Die Bilanz gilt für den ganzen Haushalt. Ohne diese Angaben bleiben Haushaltseinkommen, "
                   "Tragbarkeit und Rente offen.",
             "en": "The balance sheet is for the whole household. Without these details the household income, "
                   "affordability and the pension stay open.", "en_draft": True},
}

_ASKED = {"key": "partner_in_plan", "equals": "ja"}


def _pq(key: str, qtype: str, de: str, en: str, why_de: str, why_en: str, **extra: Any) -> dict[str, Any]:
    q: dict[str, Any] = {"key": key, "type": qtype, "section": "21", "required": False,
                         "question": {"de": de, "en": en},
                         "why": {"de": why_de, "en": why_en, "en_draft": True}, "provenance": "new (EIG-53)"}
    if key != "partner_in_plan":
        q["asked_when"] = dict(_ASKED)
    q.update(extra)
    return q


def _same_options(key: str) -> list[dict[str, Any]]:
    """The client's own question's options, offered ones only, so both people answer on the same scale."""
    return [_opt(v) for v in {
        "qualification_highest": ("Universitäre Hochschule", "Fachhochschule FH", "Höhere Berufsausbildung",
                                  "Berufsausbildung (EFZ)", "Unternehmensinterne Ausbildung"),
        "network_reach": ("im eigenen Team", "im eigenen Unternehmen", "in der Branche", "über die Branche hinaus"),
        "health": (f"1 {DASH} sehr gut", "0.85", "0.7", "0.5", "eingeschränkt"),
        "rest_hours": ("kaum welche", f"5{EN}10", f"10{EN}20", f"20{EN}30", "mehr als 30"),
    }[key]]


PARTNER_QUESTIONS: list[dict[str, Any]] = [
    _pq("partner_in_plan", "choice",
        "Gehört eine Partnerin oder ein Partner zu Ihrem Haushalt, deren Angaben in diesen Plan gehören?",
        "Does a partner belong to your household whose details belong in this plan?",
        "Wenn ja, fragen wir nach Alter, Einkommen und Humankapital Ihrer Partnerin oder Ihres Partners. Die Bilanz "
        "rechnet dann für zwei Erwachsene.",
        "If so, we ask for your partner's age, income and human capital. The balance sheet then counts two adults.",
        options=[_opt("ja"), _opt("nein")]),
    _pq("partner_age", "number", "Wie alt ist Ihre Partnerin oder Ihr Partner?", "How old is your partner?",
        "Das Alter bestimmt die Altersgutschriften der Pensionskasse und wann die AHV-Rente beginnt.",
        "Age sets the pension fund's retirement credits and when the AHV pension starts.",
        unit="Jahre", min=16, max=120),
    _pq("partner_income_gross", "number", "Bruttolohn Ihrer Partnerin oder Ihres Partners pro Jahr",
        "Your partner's gross salary per year",
        "Für die Hochrechnung von AHV und Pensionskasse. Das Haushaltseinkommen liest die Bilanz aus den "
        "Einkommenspositionen im Plan: erfassen Sie dort auch die Anstellung Ihrer Partnerin oder Ihres Partners, "
        "mit «Gehört zu: Partnerin oder Partner».",
        "For the AHV and pension-fund projection. The household income is read from the income positions in the "
        "plan: add your partner's employment there too, with «Belongs to: partner».",
        unit="CHF/Jahr", min=0),
    _pq("partner_hours_per_week", "number", "Wie viele Stunden pro Woche arbeitet Ihre Partnerin oder Ihr Partner?",
        "How many hours a week does your partner work?",
        "Arbeitszeit, Lernen und Erholung teilen sich dieselbe Woche.",
        "Work, learning and rest share the same week.", unit="Stunden/Woche", min=0, max=100),
    _pq("partner_ahv_years_missing", "number", "Fehlende AHV-Beitragsjahre Ihrer Partnerin oder Ihres Partners",
        "Your partner's missing AHV contribution years",
        "Ein fehlendes Jahr kostet in der Regel mindestens ein Vierundvierzigstel der Rente, lebenslang.",
        "A missing year usually costs at least one forty-fourth of the pension, for life.", unit="Jahre", min=0),
    _pq("partner_qualification_highest", "choice", "Höchster Abschluss Ihrer Partnerin oder Ihres Partners",
        "Your partner's highest qualification",
        "Die fünf Kategorien des Bundesamts für Statistik, wie bei Ihrer eigenen Antwort.",
        "The Federal Statistical Office's five categories, as in your own answer.",
        options=_same_options("qualification_highest")),
    _pq("partner_qualification_year", "number", "Jahr dieses Abschlusses", "Year of that qualification",
        "Eine laufende Weiterbildung setzt die Abnahme mit den Jahren zurück.",
        "Training under way resets the decline over the years.", unit="Jahr", min=1940, max=2100),
    _pq("partner_years_in_field", "number", "Jahre im heutigen Tätigkeitsfeld", "Years in the current field",
        "Erfahrung zählt und sättigt.", "Experience counts, and saturates.", unit="Jahre", min=0, max=80),
    _pq("partner_education_recent", "text", "Weiterbildung Ihrer Partnerin oder Ihres Partners, laufend oder geplant",
        "Your partner's training, under way or planned",
        "Schreiben Sie «nein», wenn keine läuft oder geplant ist.", "Write «no» if none is under way or planned.",
        multiline=True),
    _pq("partner_network_people", "number", "Menschen, die Ihre Partnerin oder Ihren Partner beruflich weiterempfehlen würden",
        "People who would recommend your partner professionally",
        "Ein Netzwerk ist die Absicherung des Einkommens, die keine Prämie kostet.",
        "A network is the income protection that costs no premium.", min=0),
    _pq("partner_network_reach", "choice", "Wie weit reichen diese Kontakte?", "How far do these contacts reach?",
        "Drei Namen aus der Geschäftsleitung sind ein anderes Netzwerk als drei aus dem eigenen Team.",
        "Three names from the executive floor are a different network from three in one's own team.",
        options=_same_options("network_reach")),
    _pq("partner_mandates", "number", "Mandate und Nebenerwerbe Ihrer Partnerin oder Ihres Partners",
        "Your partner's mandates and side incomes",
        "Mehrere kleine, voneinander unabhängige Einkommen sind stabiler als ein grosses.",
        "Several small, unrelated incomes are steadier than one large one.", min=0),
    _pq("partner_health", "choice", "Gesundheit Ihrer Partnerin oder Ihres Partners", "Your partner's health",
        "Im Modell eine Finanzgrösse: sie entscheidet, wie lange das Humankapital trägt. Besonders schützenswert "
        "(K3); nur beantworten, wenn Ihre Partnerin oder Ihr Partner einverstanden ist.",
        "In the model a financial quantity: it decides how long human capital lasts. Specially protected (K3); "
        "answer only if your partner agrees.",
        options=_same_options("health"), data_class="K3"),
    _pq("partner_rest_hours", "choice", "Erholung Ihrer Partnerin oder Ihres Partners pro Woche",
        "Your partner's rest per week", "Der Topf, aus dem eine Weiterbildung bezahlt wird.",
        "The pot a training is paid from.", options=_same_options("rest_hours")),
]

#: The partner section's question keys, in order.
PARTNER_KEYS = tuple(q["key"] for q in PARTNER_QUESTIONS)


def revised_intake(body: dict[str, Any]) -> dict[str, Any]:
    """The partner section after section 16 (the client's own human capital), and ``hours_learning`` dropped
    (owner: ``education_hours``, the band, stays; answers already given stay and are still read)."""
    new = copy.deepcopy(body)
    if not any(s.get("key") == "21" for s in new.get("sections") or []):
        new.setdefault("sections", []).append(copy.deepcopy(PARTNER_SECTION))
    if _question(new, PARTNER_KEYS[0]) is None:
        anchor = _question(new, "rest_hours")
        if anchor is None:
            raise ValueError("the intake has no rest_hours to place the partner section after")
        base = float(anchor.get("order", 0))
        later = sorted(float(q.get("order", 0)) for q in new["questions"] if float(q.get("order", 0)) > base)
        top = later[0] if later else base + 1
        step = (top - base) / (len(PARTNER_QUESTIONS) + 1)
        for i, question in enumerate(PARTNER_QUESTIONS, start=1):
            q = copy.deepcopy(question)
            q["order"] = round(base + i * step, 4)
            new["questions"].append(q)
    new["questions"] = [q for q in new["questions"] if q.get("key") != "hours_learning"]
    new["version"] = "intake@1.3"
    return new


REVISIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {INTAKE: revised_intake}


# ---------------------------------------------------------------------------------------------------------
# The nominal and real view (owner decisions 7 and 9 of 29.09.2026, EIG-60 and EIG-61): whether a goal's amount
# is in today's francs, and whether the yearly contribution rises with prices. The onboarding's next version.
# ---------------------------------------------------------------------------------------------------------

BASIS_NOTE = "goal amount in today's francs and indexed contribution asked (nominal and real view), owner 29.09.2026"

#: The key of the question asked per goal. ``scope: goal`` keeps it out of the questionnaire's sequence.
GOAL_AMOUNT_BASIS_KEY = "goal_amount_basis"

CONTRIBUTION_INDEXED = {
    "key": "contribution_indexed", "type": "choice", "required": False, "default": "nein",
    "question": {"de": "Steigt der Betrag mit der Teuerung?", "en": "Does the amount rise with prices?",
                 "en_draft": True},
    "why": {"de": "Wenn Sie den Betrag jedes Jahr der Teuerung anpassen, legen Sie später mehr Franken zur Seite. "
                  "Ohne Angabe rechnet die Bilanz mit einem festen Betrag in Franken.",
            "en": "If you raise the amount with prices every year, you put more francs aside later. Without an "
                  "answer the balance sheet counts a fixed amount in francs.", "en_draft": True},
    "options": [{"value": "nein", "label": {"de": "Nein, er bleibt in Franken gleich",
                                            "en": "No, it stays the same in francs"}},
                {"value": "ja", "label": {"de": "Ja, er steigt mit der Teuerung", "en": "Yes, it rises with prices"}}],
    "provenance": "new (EIG-61)",
    "_note": "Owner decision 9 of 29.09.2026: the default is fixed in francs. Read into lbs-request "
             "mandate.contribution_indexed (ja: true, nein: false); unanswered is left out of the request.",
}

GOAL_AMOUNT_BASIS = {
    "key": GOAL_AMOUNT_BASIS_KEY, "type": "choice", "scope": "goal", "required": False, "default": "today",
    "fills": {"entity": "goal", "field": "amount_basis"},
    "question": {"de": "Ist der Betrag in heutigen Franken?", "en": "Is the amount in today's francs?",
                 "en_draft": True},
    "why": {"de": "Ein Betrag in heutigen Franken meint, was er heute kaufen kann: die Bilanz rechnet ihn mit der "
                  "Teuerung bis zum Zieldatum hoch. Ein Betrag in Franken des Zieldatums bleibt, wie er ist.",
            "en": "An amount in today's francs means what it buys today: the balance sheet raises it with prices "
                  "to the target date. An amount in the francs of the target date stays as it is.",
            "en_draft": True},
    "options": [{"value": "today", "label": {"de": "Ja, in heutigen Franken", "en": "Yes, in today's francs"}},
                {"value": "future", "label": {"de": "Nein, in Franken des Zieldatums",
                                              "en": "No, in the francs of the target date"}}],
    "provenance": "new (EIG-60)",
    "_note": "Owner decision 7 of 29.09.2026: the default is today's francs. Asked per goal on the plan page "
             "(scope goal, never in the questionnaire's sequence); stored as goal.amount_basis and sent as "
             "lbs-request goals[].amount_basis.",
}


def basis_onboarding(body: dict[str, Any]) -> dict[str, Any]:
    """``contribution_indexed`` right after ``annual_contribution``, and the per-goal ``goal_amount_basis``."""
    new = copy.deepcopy(body)
    anchor = "annual_contribution" if _question(new, "annual_contribution") is not None else None
    _insert_after(new, anchor, CONTRIBUTION_INDEXED)
    _insert_after(new, None, GOAL_AMOUNT_BASIS)
    if new != body:
        new["version"] = "onb2@0.3.0"
    return new


BASIS_REVISIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {ONBOARDING: basis_onboarding}


def _changed_keys(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Keys added or changed, then ``-key`` for each question removed."""
    before = {q["key"]: q for q in old.get("questions") or []}
    after = {q["key"] for q in new.get("questions") or []}
    return ([q["key"] for q in new.get("questions") or [] if before.get(q["key"]) != q]
            + [f"-{k}" for k in before if k not in after])


def align(conn, *, curator_id: str, note: str = NOTE) -> dict[str, Any]:
    """Save the aligned questionnaires as new versions by ``curator_id``, in one transaction. A questionnaire
    already aligned is left as it is. Returns what was saved and the bind check afterwards."""
    return _save_all(conn, ALIGNMENTS, curator_id=curator_id, note=note)


def revise(conn, *, curator_id: str, note: str = REVISION_NOTE) -> dict[str, Any]:
    """The owner's content changes of 29.09.2026 after the use cases (EIG-53, EIG-58): the intake's partner
    section and ``hours_learning`` dropped, saved as a new version by ``curator_id``; nothing when done."""
    return _save_all(conn, REVISIONS, curator_id=curator_id, note=note)


def revise_basis(conn, *, curator_id: str, note: str = BASIS_NOTE) -> dict[str, Any]:
    """The nominal and real view's two questions (EIG-60, EIG-61) as the onboarding's next version, saved by
    ``curator_id``; nothing when done."""
    return _save_all(conn, BASIS_REVISIONS, curator_id=curator_id, note=note)


def _save_all(conn, changes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]], *, curator_id: str,
              note: str) -> dict[str, Any]:
    saved: dict[str, Any] = {}
    with conn.transaction():
        cur = conn.execute("SELECT id, revoked_at FROM curator WHERE id = %s", (curator_id,)).fetchone()
        if cur is None:
            raise ValueError(f"no curator {curator_id}")
        if cur["revoked_at"] is not None:
            raise ValueError(f"curator {curator_id} is revoked and cannot act (A161)")
        schema = conn.execute("SELECT current_schema() AS s").fetchone()["s"]
        for key, fn in changes.items():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s || '.content_record:' || %s, 0))",
                         (schema, key))
            current = store.content_current(conn, key)
            body = fn(current["body"])
            if body == current["body"]:
                saved[key] = {"status": "unchanged", "version": current["version"], "questions": []}
                continue
            version = store.save_content(conn, key=key, kind="questionnaire", body=body, saved_by_kind="curator",
                                         saved_by_ref=curator_id, note=note)
            saved[key] = {"status": "saved", "version": version, "from_version": current["version"],
                          "questions": _changed_keys(current["body"], body)}
    checks = conn.execute("SELECT status, count(*) AS n FROM scoring_bind_check GROUP BY status").fetchall()
    return {"saved": saved, "binds": {r["status"]: r["n"] for r in checks}}


def offered(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The options a new answer is offered."""
    return [o for o in options if o.get("offered", True) is not False]


__all__ = ["align", "aligned_intake", "aligned_onboarding", "NOTE", "offered", "revise", "revised_intake",
           "REVISION_NOTE", "PARTNER_KEYS", "revise_basis", "basis_onboarding", "BASIS_NOTE", "GOAL_AMOUNT_BASIS_KEY"]
