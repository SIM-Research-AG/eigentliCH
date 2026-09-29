"""Phase 2 of the workflow: what can be computed from what we have, and what is missing to compute the rest.

**Why this is a phase and not an appendix.** The report used to be produced first and its gaps listed at the
end, which is the wrong way round: a client answers questions to make a calculation possible, so the questions
that make it possible have to come before the calculation. This module is what makes that ordering expressible.
It takes a submission and answers, without computing anything expensive and without raising:

    what is BLOCKED       and by which single answer
    what is COMPUTABLE    section by section
    what is ASSUMED       computable, but on a model value rather than the household's own

`app/onboarding.py` already refuses a submission that cannot be converted, and refusing is right there -- a
converter that guesses a missing target spend invents the answer. But a refusal is a poor way to run an
interview: it names the first problem and stops, so a client fixes one thing, resubmits, and discovers the
second. This names all of them at once, in the order that unblocks the most.

**`BLOCKING` is a superset of the converter's refusals, and the asymmetry is deliberate.** Two of its entries
are conditions `case_from_submission` raises on -- a missing target spend, a missing age. The other two are
not: the converter never reads the `raw` block at all, so it accepts a submission with no income and no
current spending. It is right to, in its own terms; the report would still compute. But it would compute with
an income of zero, which makes every tax figure, the whole AHV entitlement and the entire saving rate come out
zero or negative, and the client would be shown them as findings. That is not a degraded answer, it is a wrong
one, so the interview insists.

The invariant that matters therefore runs one way only, and `tests/test_workflow.py` asserts that direction:

    every condition the converter refuses on IS in BLOCKING   -- `ready` never promises what it cannot keep
    not every BLOCKING entry is a converter refusal           -- some make the answer useless, not impossible

The reverse assertion would be the wrong test to write. A submission this module calls blocked and the
converter would accept costs one extra question; a submission it calls ready and the converter refuses costs
the client a completed interview and a refusal, which is the failure worth a test.
"""

from __future__ import annotations

from typing import Any, Callable

#: What makes a submission unrunnable or its answer worthless, and the interview field that fixes it.
#: `refused_by_converter` records which is which: True where `case_from_submission` raises, so the two can be
#: checked against each other without the table pretending to be a copy of something it is a superset of.
BLOCKING: tuple[dict[str, Any], ...] = (
    {
        "code": "no_target_spend",
        "refused_by_converter": True,
        "field": "spend_later",
        "why": "Ohne Ausgabenziel gibt es keine Unabhängigkeitsrechnung. Der Kapitalbedarf ist die Differenz "
               "zweier grosser Zahlen geteilt durch einen kleinen Satz — eine fehlende Angabe verschlechtert "
               "das Ergebnis nicht, sie erfindet es.",
        "test": lambda sub, raw: (sub.get("params") or {}).get("G") is None,
    },
    {
        "code": "no_age",
        "refused_by_converter": True,
        "field": "birth_year",
        "why": "Das Alter treibt die AHV, beide Vorsorgeschwellen und den Rückgang der Ertragskraft. Ohne "
               "Jahrgang rechnet das Modell einen anderen Menschen.",
        "test": lambda sub, raw: (sub.get("state") or {}).get("age") is None,
    },
    {
        "code": "no_income",
        "refused_by_converter": False,
        "field": "income_gross",
        "why": "Ohne Einkommen gibt es keinen Cashflow, keine Steuer, keine Sparquote und keine AHV-Rente. "
               "Fast jede Zahl des Berichts hängt daran.",
        "test": lambda sub, raw: raw.get("income_gross") is None,
    },
    {
        "code": "no_spending",
        "refused_by_converter": False,
        "field": "spend_now",
        "why": "Ohne heutige Lebenskosten lässt sich nicht sagen, was übrig bleibt — und die Sparquote ist "
               "genau das, was übrig bleibt.",
        "test": lambda sub, raw: raw.get("spend_now") is None,
    },
)

#: Each report section, the fields it needs, and what it costs the reader when they are absent. A section with
#: no missing field is computable; one with a missing field is named along with the field, which is what turns
#: a gap into a question.
SECTIONS: tuple[dict[str, Any], ...] = (
    {"key": "balance", "title": "Wo Sie heute stehen", "needs": (),
     "without": "Die Bilanz steht immer: sie folgt aus den Vermögensangaben."},
    {"key": "cash_flow", "title": "Was der Haushalt erzeugt", "needs": ("income_gross", "spend_now"),
     "without": "Ohne Einkommen und Lebenskosten gibt es keine Sparquote."},
    {"key": "income_65", "title": "Was ab 65 zufliesst", "needs": ("income_gross",),
     "without": "Die AHV-Rente folgt aus dem durchschnittlichen Einkommen."},
    {"key": "gap", "title": "Die Lücke und das Kapital", "needs": ("spend_later", "income_gross"),
     "without": "Ohne Ausgabenziel gibt es keine Lücke und keinen Kapitalbedarf."},
    {"key": "health", "title": "Die Arbeitszeit als Finanzgrösse", "needs": ("hours_per_week",),
     "without": "Ohne Wochenstunden ist der Gesundheitsverlauf nicht berechenbar."},
    # `applies` is the household condition, as against `needs`, which is the answer condition. A childless
    # household is not MISSING the child section; it does not have one. Phase 3 turns every gap into a
    # question, so conflating the two produces questions nobody should be asked.
    {"key": "children", "title": "Kinder als Kostenverlauf", "needs": ("children_ages",),
     "applies": lambda raw, sub: float(raw.get("children_count") or 0) > 0,
     "without": "Ohne Jahrgänge der Kinder wird ihre Kostenreihe nicht gerechnet."},
    {"key": "bridge", "title": "Die Brücke bis 65", "needs": ("stop_work_age",),
     # Only where an early exit is actually wanted. `goal_kinds` says so directly since 21 August 2026; the
     # free-text goal is read too, because the older submissions have no goal_kinds at all.
     "applies": lambda raw, sub: (
         "Früher aufhören zu arbeiten" in (raw.get("goal_kinds") or [])
         or "Finanzielle Unabhängigkeit" in (raw.get("goal_kinds") or [])
         or any(t in str(raw.get("goals") or "").lower()
                for t in ("nicht mehr arbeiten", "frühpension", "fruehpension", "aufhören"))),
     "without": "Ohne Ausstiegsalter ist die teuerste Phase eines Frühpensionierungsplans nicht gerechnet."},
    {"key": "required_return", "title": "Die nötige Rendite", "needs": ("spend_later",),
     "without": "Ohne Kapitalbedarf gibt es keine Renditeanforderung."},
    {"key": "allocation", "title": "Die Anlageallokation", "needs": ("max_loss_pct",),
     "without": "Die Allokation wird aus Ihrer Lage abgeleitet; die Verlustgrenze setzt eine ihrer Schranken."},
)

#: Fields that reach an equation only through a model default. Present in the interview, and where unanswered
#: the report computes anyway and states the substitution. Distinguished from a blocking gap because the
#: consequence is different: a caveat, not a missing section.
ASSUMED_WHEN_ABSENT: tuple[tuple[str, str], ...] = (
    ("mortgage_rate", "Es wird mit dem Modellsatz gerechnet statt mit Ihrem Vertrag."),
    ("ahv_years_missing", "Es wird eine vollständige Beitragsdauer angenommen."),
    ("pillar3a_contribution", "Es wird kein laufender Beitrag angenommen."),
    ("rest_hours", "Die Erholungszeit wird aus dem Modellwert gesetzt."),
    ("civil_status", "Es wird der Einzeltarif angenommen."),
)


def _has(raw: dict, sub: dict, field: str) -> bool:
    """Whether the interview has an answer for `field`, wherever the schema carries it.

    `spend_later` reaches the engine as `params.G` and `birth_year` as `state.age`, so a check that looked only
    at `raw` would report a gap for a household that answered. The mapping lives in the questionnaire; the two
    places it lands are checked here rather than reimplemented.
    """
    if raw.get(field) is not None:
        return True
    if field == "spend_later":
        return (sub.get("params") or {}).get("G") is not None
    if field == "birth_year":
        return (sub.get("state") or {}).get("age") is not None
    if field == "stop_work_age":
        return (sub.get("params") or {}).get("stop_work_age") is not None
    if field == "children_ages":
        return bool((sub.get("params") or {}).get("child_ages"))
    return False


def readiness(submission: dict) -> dict:
    """What this submission can and cannot produce. Cheap, and never raises.

    Returns `blocking`, `sections` and `assumed`. `ready` is True when nothing blocks -- which does NOT mean
    every section is computable, only that the calculation can run and say what it could not cover.
    """
    raw = submission.get("raw") or {}

    blocking = []
    for b in BLOCKING:
        try:
            hit = bool(b["test"](submission, raw))
        except (KeyError, TypeError, ValueError):
            hit = False
        if hit:
            blocking.append({"code": b["code"], "field": b["field"], "why": b["why"]})

    sections = []
    for s in SECTIONS:
        applies = s.get("applies")
        try:
            relevant = True if applies is None else bool(applies(raw, submission))
        except (KeyError, TypeError, ValueError):
            relevant = True
        missing = [f for f in s["needs"] if not _has(raw, submission, f)] if relevant else []
        sections.append({"key": s["key"], "title": s["title"], "applies": relevant,
                         "computable": relevant and not missing,
                         "missing": missing, "without": s["without"] if missing else ""})

    assumed = [{"field": f, "consequence": c} for f, c in ASSUMED_WHEN_ABSENT
               if not _has(raw, submission, f)]

    return {
        "ready": not blocking,
        "blocking": blocking,
        "sections": sections,
        "assumed": assumed,
        # Counted over the sections that APPLY. A childless household reporting "7 of 9" invites the reader
        # to look for two missing things, one of which was never theirs.
        "computable_count": sum(1 for s in sections if s["computable"]),
        "section_count": sum(1 for s in sections if s["applies"]),
        "not_applicable": [s["key"] for s in sections if not s["applies"]],
    }


#: The three stages, in the order a household passes through them.
STAGES = ("open", "report", "risk")


def open_items(quantities: dict, submission: dict) -> dict[str, Any]:
    """What is still open, split into what blocks the report and what merely improves it.

    The rule for blocking is one sentence: answering it changes a number that is already in the report. That
    is why a contradiction blocks and a ranked ask does not -- the ask would make the report better, the
    contradiction makes it about a household that may not exist.
    """
    blocking: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []

    # 1. Answers that cannot both be true, and the ones the report cannot compute around.
    #
    # A field the household was asked and declined never blocks. It lands in `pending_fields`, which is a
    # recorded decision rather than a gap -- and a gate that kept demanding an answer somebody has already
    # refused would be a gate nobody could pass.
    declined = set(quantities.get("pending_fields") or [])
    for c in ((quantities.get("plausibility") or {}).get("checks") or []):
        item = {"code": c["code"], "kind": "contradiction", "title": c["title"],
                "detail": c["conflict"], "question": c["ask"], "fields": c.get("fields") or [],
                "why": c["why"]}
        blocks = (c["severity"] == "impossible" or c.get("blocks")) and not (
            set(c.get("fields") or []) & declined)
        (blocking if blocks else optional).append(item)

    # 2. What the converter itself refuses to run without.
    for b in (readiness(submission).get("blocking") or []):
        blocking.append({"code": b["code"], "kind": "blocking_field", "title": "Fehlende Angabe",
                         "detail": b["why"], "question": b["why"],
                         "fields": [b["field"]] if b.get("field") else [], "why": b["why"]})

    # 3. A goal whose kind is unresolved. It is priced -- what must be saved by a date follows from the
    #    amount and the date -- and what the purchase then does to the balance sheet does not.
    seen: set[str] = set()
    for run in ((quantities.get("paths") or {}).get("paths") or []):
        for g in run.get("goals") or []:
            key = f"{g.get('kind')}|{g.get('target_year')}"
            if not g.get("kind_unresolved") or key in seen:
                continue
            seen.add(key)
            blocking.append({
                "code": f"goal_kind:{key}", "kind": "unresolved_goal",
                "title": "Die Art dieses Ziels ist offen",
                "detail": f"«{g.get('description')}» — {g.get('target_year')}",
                "question": "Ist das selbst bewohntes Wohneigentum, ein Ferienobjekt oder eine Firma?",
                "fields": ["goal_kinds"],
                "why": "Was bis zum Datum zu sparen ist, steht schon fest — es folgt aus Betrag und Jahr. "
                       "Was der Kauf danach mit Ihrer Bilanz macht, hängt an der Art: selbst bewohntes "
                       "Eigentum ist abgeschottetes Vermögen, ein Ferienobjekt ist Konsum mit negativer "
                       "Nettorendite, eine Firma ist eine Investition. Jede Zahl nach dem Kaufjahr hängt "
                       "daran."})

    # 4. Deliberately left open by the household. Recorded, never blocking: they were asked and declined.
    for field in (quantities.get("pending_fields") or []):
        optional.append({"code": f"pending:{field}", "kind": "pending", "title": "Bewusst offen gelassen",
                         "detail": field, "question": "", "fields": [field],
                         "why": "Das Modell rechnet dafür mit seinen Standardwerten."})

    # 5. Measured improvements. Never blocking: there is no end to them, and a gate that waited for them
    #    would never open.
    for ask in (quantities.get("asks_ranked") or [])[:5]:
        optional.append({"code": f"ask:{ask.get('code')}", "kind": "ask",
                         "title": ask.get("headline") or "Eine Angabe, die etwas bewegt",
                         "detail": ask.get("effect_label") or "", "question": ask.get("question") or "",
                         "fields": [ask["field"]] if ask.get("field") else [],
                         "why": ask.get("why") or ""})

    return {
        "stage": "open" if blocking else "report",
        "blocking": blocking,
        "optional": optional,
        "open_count": len(blocking),
        "optional_count": len(optional),
    }


def follow_ups(submission: dict, params: Any, assemble: Callable[..., dict]) -> dict:
    """Phase 3, in two rounds, and the order is the point.

    **First what blocks, then what moves.** A blocking gap has no franc figure -- there is nothing to measure
    the effect of, because without it there is no answer to move -- so it cannot be ranked alongside the rest
    and must not be. Once nothing blocks, the ranking is by measured effect, which `app/asks.py` computes by
    recomputing the report at a plausible low and high for each unknown.

    Returns both rounds separately so an interview can finish the first before starting the second.
    """
    r = readiness(submission)
    out: dict[str, Any] = {"round": 1 if r["blocking"] else 2, "readiness": r,
                           "blocking": r["blocking"], "ranked": []}
    if r["blocking"]:
        # No measurement while a blocking gap stands: the probes would be measuring a report that cannot be
        # produced, and a franc figure derived from that is worse than no figure.
        return out
    from . import asks as _asks  # noqa: PLC0415 - imported here to keep the cheap path cheap
    ranked = _asks.rank(submission, params, assemble)
    out["ranked"] = ranked
    out["summary"] = _asks.summarise(ranked)
    return out
