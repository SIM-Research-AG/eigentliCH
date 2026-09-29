"""Whether the answers can all be true at once, checked before anything is computed from them.

**This is a different question from the findings, and mixing the two would weaken both.** A finding says
something true about a household: the pillar 3a is empty, the goal is out of reach. A plausibility check says
the report cannot yet be trusted, because two of the answers contradict each other and at least one of them is
wrong. The first is a result. The second invalidates results.

The case that prompted it: a household stated a saving of 30 000 a year against a gross income of 24 000. Both
figures were carried into the report, one of them silently won, and the whole plan -- required return, mandate,
feasibility -- rested on a number nobody had reconciled. Nothing in the report said "these two cannot both be
right"; the reader had to notice.

Three rules the checks here follow:

  **Name both figures.** A warning that says "the income looks implausible" is unanswerable. One that says
  "24 000 gross at 16.8 hours implies 60 000 at a full Pensum" can be confirmed or corrected in a sentence.

  **Ask, do not correct.** Nothing here changes an input. A converter that quietly repairs an answer produces a
  report about a household that does not exist, and the correction is invisible in the output.

  **Separate the impossible from the unlikely.** Two figures that cannot both be true are a different state
  from two that rarely go together, and a reader who cannot tell them apart learns to ignore both.
"""

from __future__ import annotations

from typing import Any

from ..model.params import Params

SCHEMA = "plausibility@0.1.0"

#: Full-time hours a week, shared with `app.paths` so a Pensum means one thing in both.
from .paths import FULL_TIME_HOURS  # noqa: E402

#: The band a full-time Swiss salary is expected to fall in, used only to ask a question.
#:
#: **Deliberately wide, and it is a prompt rather than a judgement.** The point is not to police what somebody
#: earns; it is that an income far outside this band, once divided by the stated Pensum, usually means the
#: hours and the income describe different things -- a monthly figure entered as an annual one, a household
#: income entered as a personal one, a part-time salary already grossed up by the client.
FULLTIME_INCOME_LOW = 30_000.0
FULLTIME_INCOME_HIGH = 600_000.0

#: Hours at or above which a stated Pensum is treated as full time regardless of what was ticked.
FULLTIME_HOURS_FLOOR = 38.0


def _chf(x: float) -> str:
    """A franc figure in Swiss grouping.

    **Only the number is formatted, never the sentence around it.** Scrubbing commas out of a whole f-string
    is how "16.8 Stunden pro Woche, also rund 40 %" became "16.8 Stunden pro Woche  also rund 40 %": a
    thousands separator and a German comma are the same character. That bug was found and fixed once in
    `desktop/allocation.py`, then written again here, which is what a shared helper is for.
    """
    return f"{x:,.0f}".replace(",", " ")


def _num(raw: dict, key: str) -> float | None:
    v = raw.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v.replace("'", "").replace("’", "").replace(" ", "").replace("%", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _check(code: str, severity: str, title: str, conflict: str, why: str, ask: str,
           fields: tuple[str, ...], blocks: bool = False) -> dict[str, Any]:
    """One check. `fields` names the interview answers involved, so a surface can offer them back.

    `blocks` marks a check that must be answered before the report is shown even though it is not an
    arithmetic impossibility. The rule is the gate's: it blocks when answering it changes a number already in
    the report. A household that was asked and declined is never blocked by it -- the field lands in
    `pending_fields`, and `workflow.open_items` reads that.
    """
    return {"code": code, "severity": severity, "title": title, "conflict": conflict,
            "why": why, "ask": ask, "fields": list(fields), "blocks": blocks}


# --- the checks ------------------------------------------------------------------------------------------

def saving_exceeds_income(sub: dict, p: Params, raw: dict) -> dict | None:
    """A stated saving larger than the whole gross income. Arithmetic, not judgement."""
    saving, gross = _num(raw, "savings"), _num(raw, "income_gross")
    if saving is None or gross is None or saving <= gross:
        return None
    return _check(
        "saving_exceeds_income", "impossible",
        "Die angegebene Sparquote ist grösser als das ganze Einkommen",
        f"Sparquote {_chf(saving)} gegen ein Bruttoeinkommen von {_chf(gross)}",
        "Aus einem Einkommen kann nicht mehr gespart werden, als es gross ist. Eine der beiden Zahlen "
        "meint etwas anderes, als die Frage gemeint hat — meistens ist es angespartes Vermögen statt "
        "jährlicher Sparleistung, oder eine Zahl, die einen zweiten Haushalt einschliesst.",
        "Welche der beiden Zahlen ist die jährliche? Und gehört sie zu diesem Einkommen?",
        ("savings", "income_gross"))


def pensum_declaration_conflicts(sub: dict, p: Params, raw: dict) -> dict | None:
    """The stated hours and the declared Pensum disagree.

    **The household is asked both, and only one was being used.** `hours_per_week` drives every derived
    figure; `hours_is_fulltime` was collected and never read. Where they agree the second is redundant, and
    where they disagree it is the more reliable of the two -- somebody knows whether their own job is full
    time -- so the disagreement is worth more than either answer alone.
    """
    hours = _num(raw, "hours_per_week")
    declared = str(raw.get("hours_is_fulltime") or "")
    if hours is None or not declared:
        return None
    says_full = declared.strip().lower().startswith("vollpensum")
    looks_full = hours >= FULLTIME_HOURS_FLOOR
    if says_full == looks_full:
        return None
    return _check(
        "pensum_declaration_conflicts", "unlikely",
        "Stundenzahl und angegebenes Pensum passen nicht zusammen",
        f"{hours:.1f} Stunden pro Woche, angegeben als «{declared}»",
        "Bei einer Vollzeitwoche von rund 42 Stunden lesen sich diese beiden Angaben unterschiedlich. "
        "Davon hängt ab, ob Ihr heutiges Einkommen bereits Ihr volles ist oder ein Teil davon — und damit "
        "jede Aussage über Ihr künftiges Einkommen.",
        "Sind die genannten Stunden Ihr volles Pensum, oder arbeiten Sie reduziert?",
        ("hours_per_week", "hours_is_fulltime"))


def implied_fulltime_income_out_of_band(sub: dict, p: Params, raw: dict) -> dict | None:
    """Income divided by the Pensum lands somewhere a full-time salary rarely is.

    Asked rather than corrected: the usual causes are a monthly figure entered as an annual one and a
    part-time salary the client already grossed up, and those two need opposite corrections.
    """
    gross, hours = _num(raw, "income_gross"), _num(raw, "hours_per_week")
    if not gross or not hours or hours <= 0:
        return None
    pensum = max(0.05, min(1.5, hours / FULL_TIME_HOURS))
    if pensum >= 0.95:
        return None
    implied = gross / pensum
    if FULLTIME_INCOME_LOW <= implied <= FULLTIME_INCOME_HIGH:
        return None
    return _check(
        "implied_fulltime_income_out_of_band", "unlikely",
        "Auf ein volles Pensum hochgerechnet ergibt das Einkommen einen ungewöhnlichen Wert",
        f"{_chf(gross)} bei {hours:.1f} Stunden entspricht {_chf(implied)} bei vollem Pensum",
        "Das ist keine Aussage darüber, was jemand verdienen sollte. Es ist der Hinweis, dass Stunden und "
        "Einkommen hier verschiedene Dinge zu beschreiben scheinen — etwa ein Monatsbetrag als Jahresbetrag, "
        "oder ein Teilzeitlohn, der schon auf ein volles Pensum umgerechnet wurde.",
        "Ist das Einkommen der Jahresbetrag für die genannten Stunden?",
        ("income_gross", "hours_per_week"))


def reduced_pensum_without_an_anchor(sub: dict, p: Params, raw: dict) -> dict | None:
    """A reduced Pensum and no statement of what a full one would earn.

    Not an error, and reported anyway: without that one figure every income path in this report rests on the
    model's own level rather than on anything the household said, and a modelled level and a stated one are
    different claims.
    """
    hours = _num(raw, "hours_per_week")
    if hours is None or hours >= FULLTIME_HOURS_FLOOR:
        return None
    if _num(raw, "income_expected_full") is not None:
        return None
    gross = _num(raw, "income_gross") or 0.0
    pensum = max(0.05, min(1.5, hours / FULL_TIME_HOURS))
    return _check(
        "reduced_pensum_without_an_anchor", "unlikely",
        "Zum Einkommen bei vollem Pensum liegt keine Angabe vor",
        f"{hours:.1f} Stunden pro Woche, also rund {pensum:.0%} — heutiges Einkommen {_chf(gross)}",
        "Ihr heutiges Einkommen ist das eines reduzierten Pensums. Der Bericht rechnet die Wege mit einem "
        "Niveau, das aus dem Modell stammt und nicht aus Ihrer Angabe. Eine einzige Zahl von Ihnen ersetzt "
        "diese Annahme und macht die Rechnung zu Ihrer.",
        "Was erwarten Sie bei vollem Pensum zu verdienen, wenn die Ausbildung abgeschlossen ist?",
        ("income_expected_full",),
        # **Blocking, though not impossible.** Every income path in the report rests on this level, so the
        # figures are answers to a question the model asked itself rather than to one the household answered.
        # Declining is a real answer and does not block: the field then sits in `pending_fields`.
        blocks=True)


def age_and_birth_year_disagree(sub: dict, p: Params, raw: dict) -> dict | None:
    """The stated age and the birth year do not match the date of the interview."""
    age = float((sub.get("state") or {}).get("age") or 0.0)
    birth = _num(raw, "birth_year")
    collected = (sub.get("meta") or {}).get("collected") or ""
    year = int(collected[:4]) if collected[:4].isdigit() else None
    if not age or not birth or not year:
        return None
    implied = year - birth
    # A year either side is ordinary: the interview does not ask for a birthday.
    if abs(implied - age) <= 1:
        return None
    return _check(
        "age_and_birth_year_disagree", "impossible",
        "Alter und Jahrgang passen nicht zum Datum der Erhebung",
        f"Jahrgang {birth:.0f} ergibt {implied:.0f} Jahre, erfasst ist ein Alter von {age:.0f}",
        "Jede Frist in diesem Bericht — Referenzalter, Zieljahre, Beitragsdauer — hängt am Alter. Ein Fehler "
        "hier verschiebt alles gleichzeitig und fällt in keiner einzelnen Zahl auf.",
        "Welcher Jahrgang stimmt?",
        ("birth_year",))


def working_past_the_reference_age(sub: dict, p: Params, raw: dict) -> dict | None:
    """The stated further working years reach past the reference age.

    Not forbidden and worth naming: the model has no income after the reference age, so the years beyond it
    are collected and then dropped, and a household that meant them literally is planning on something this
    report does not contain.
    """
    age = float((sub.get("state") or {}).get("age") or 0.0)
    more = _num(raw, "work_years_current")
    if not age or more is None:
        return None
    end = age + more
    if end <= p.ahv_age + 1.0:
        return None
    return _check(
        "working_past_the_reference_age", "unlikely",
        "Die geplanten Arbeitsjahre reichen über das Referenzalter hinaus",
        f"{more:.0f} weitere Jahre ab Alter {age:.0f} enden mit {end:.0f}, "
        f"das Referenzalter ist {p.ahv_age:.0f}",
        "Das Modell führt kein Erwerbseinkommen über das Referenzalter hinaus. Die Jahre danach sind "
        "erfasst und gehen in keine Rechnung ein — was gewollt sein kann, aber nicht unbemerkt bleiben "
        "sollte.",
        "Sollen die Jahre nach dem Referenzalter mitgerechnet werden?",
        ("work_years_current", "stop_work_age"))


def pillar2_before_the_start_age(sub: dict, p: Params, raw: dict) -> dict | None:
    """Pension capital before Altersgutschriften can have built any."""
    from ..model import bvg as _bvg
    age = float((sub.get("state") or {}).get("age") or 0.0)
    capital = float((sub.get("state") or {}).get("W_P") or 0.0)
    if not age or capital <= 0:
        return None
    start = float(_bvg.load()["bvg"]["savings_start_age"])
    if age >= start:
        return None
    return _check(
        "pillar2_before_the_start_age", "unlikely",
        "Pensionskassenguthaben vor dem Beginn der Altersgutschriften",
        f"Alter {age:.0f}, Guthaben {_chf(capital)}, Gutschriften beginnen mit {start:.0f}",
        "Vor diesem Alter besteht die Versicherung nur für Tod und Invalidität, ohne Aufbau von "
        "Altersguthaben. Ein Guthaben ist deshalb entweder übertragenes Kapital aus einem früheren "
        "Arbeitsverhältnis oder eine Verwechslung mit der Säule 3a.",
        "Woher stammt dieses Guthaben?",
        ("pillar2",))


def spending_exceeds_income_without_cover(sub: dict, p: Params, raw: dict) -> dict | None:
    """More is spent than earned, and there is not enough wealth to be covering the difference."""
    gross, spend = _num(raw, "income_gross"), _num(raw, "spend_now")
    if not gross or not spend or spend <= gross:
        return None
    liquid = float((sub.get("state") or {}).get("W_L") or 0.0)
    shortfall = spend - gross
    if liquid >= shortfall * 3:
        return None
    return _check(
        "spending_exceeds_income_without_cover", "impossible",
        "Die Ausgaben übersteigen das Einkommen, und es ist kein Vermögen da, das die Differenz trägt",
        f"Ausgaben {_chf(spend)} gegen Einkommen {_chf(gross)}, frei verfügbar {_chf(liquid)}",
        "Diese drei Zahlen können nicht gleichzeitig stimmen und die Lage stabil sein. Entweder fliesst "
        "Einkommen, das hier nicht erfasst ist, oder die Ausgaben enthalten etwas, das kein laufender "
        "Aufwand ist.",
        "Gibt es weiteres Einkommen — Partner, Eltern, Unterstützung —, das im Fragebogen nicht steht?",
        ("spend_now", "income_gross"))


def a_goal_far_beyond_the_household(sub: dict, p: Params, raw: dict) -> dict | None:
    """A goal so large relative to income and horizon that it usually means a missing source.

    Deliberately not "this goal is unrealistic". The paths table already says what a goal demands per year;
    this asks the narrower question of whether something is missing from the intake -- an inheritance, a
    partner, a sale -- because a target twenty times an annual income in a short horizon usually has one.
    """
    gross = _num(raw, "income_gross")
    if not gross:
        return None
    collected = (sub.get("meta") or {}).get("collected") or ""
    year = int(collected[:4]) if collected[:4].isdigit() else None
    worst = None
    for g in (sub.get("goals") or []):
        amount, target_year = g.get("amount_chf"), g.get("target_year")
        if not amount or not target_year or not year:
            continue
        if str(g.get("kind")) in ("fi", "retirement"):
            continue  # a spend per year, not a capital sum
        years = max(1.0, float(target_year) - year)
        per_year = float(amount) / years
        if per_year > gross and (worst is None or per_year > worst[1]):
            worst = (g, per_year, years)
    if worst is None:
        return None
    g, per_year, years = worst
    return _check(
        "a_goal_far_beyond_the_household", "unlikely",
        "Ein Ziel verlangt pro Jahr mehr, als der Haushalt insgesamt einnimmt",
        f"«{g.get('description') or g.get('kind')}»: {_chf(float(g['amount_chf']))} in {years:.0f} "
        f"Jahren sind {_chf(per_year)} pro Jahr, gegen ein Einkommen von {_chf(gross)}",
        "Das ist keine Aussage darüber, ob das Ziel richtig ist. Es ist die Frage, ob dem Fragebogen etwas "
        "fehlt: eine Erbschaft, ein Verkauf, ein zweites Einkommen. Ohne eine solche Quelle beantwortet der "
        "Bericht dieses Ziel mit Sparen allein, und das trifft dann nicht, was Sie gemeint haben.",
        "Gibt es für dieses Ziel eine Quelle ausserhalb des laufenden Einkommens?",
        ("goals", "inheritance"))


CHECKS = (
    saving_exceeds_income,
    spending_exceeds_income_without_cover,
    age_and_birth_year_disagree,
    pensum_declaration_conflicts,
    implied_fulltime_income_out_of_band,
    reduced_pensum_without_an_anchor,
    working_past_the_reference_age,
    pillar2_before_the_start_age,
    a_goal_far_beyond_the_household,
)

#: Impossible first, then unlikely; within each, the order the checks are declared in.
_ORDER = {"impossible": 0, "unlikely": 1}


def evaluate(submission: dict, p: Params) -> dict[str, Any]:
    """Run every check. Returns what fired and what could not be checked.

    A check that raises is a defect in the check and is reported as unchecked rather than allowed to take the
    report down, the same rule `findings.evaluate` follows: the other eight are still worth having.
    """
    raw = submission.get("raw") or {}
    fired: list[dict[str, Any]] = []
    unchecked: list[str] = []
    for check in CHECKS:
        try:
            got = check(submission, p, raw)
        except (KeyError, TypeError, ValueError) as exc:
            unchecked.append(f"{check.__name__}: {type(exc).__name__}: {exc}")
            continue
        if got is not None:
            fired.append(got)
    fired.sort(key=lambda c: _ORDER.get(c["severity"], 9))
    return {
        "schema": SCHEMA,
        "checks": fired,
        "unchecked": unchecked,
        "impossible": sum(1 for c in fired if c["severity"] == "impossible"),
        "unlikely": sum(1 for c in fired if c["severity"] == "unlikely"),
    }
