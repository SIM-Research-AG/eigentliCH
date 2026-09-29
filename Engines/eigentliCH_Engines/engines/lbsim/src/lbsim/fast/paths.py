"""What has to be saved each year, on each of several income paths, at a return of zero.

**The design flaw this answers.** The report froze today's salary and carried it for forty-one years. For a
twenty-four-year-old earning 24 000 at a reduced Pensum *because he is in education*, that is not a
conservative assumption -- it is the wrong question. It produced a required return of 17,50 % a year, which
says nothing except that the arithmetic was fed a salary nobody expects him to keep. Optimising a portfolio
against it is precision applied to the wrong number.

So this runs first, and it runs without the optimiser:

  **The return is zero.** Not pessimistic -- deliberate. Setting it to zero removes the one lever the household
  does not control from an exercise about the levers it does: hours, education, Pensum, network, spending.
  Whatever a path shows here, an invested portfolio can only improve on. A path that fails at zero return is
  not a portfolio problem, and a path that works at zero return does not depend on markets to work.

  **The model supplies the shape, the client supplies the level.** Expertise, network and the age profile
  already exist in `model/dynamics`, calibrated, and the levers section already prices this household's
  education with them. What they cannot supply is a credible absolute salary for one person: `earning_power`
  is bounded to a range spanning a factor of ten. So the client is asked one number -- what they expect to
  earn at a full Pensum once the education is done -- and the model's own curve is anchored on it. Where that
  answer is missing the model's own level is used and the path says so, because a stated level and a modelled
  one are different claims.

  **Every goal, on its own date.** A young household's plan is not a forty-year run to 65 with one number at
  the end. The property in 2037 and the retirement in 2067 are different questions with different horizons,
  and the second is the less interesting of the two. Retirement is one row here like any other.

  **The retirement target moves with the path.** AHV is a function of averaged lifetime income and the second
  pillar accrues on the coordinated salary year by year, so a path that raises income also raises what arrives
  from 65 and *lowers* the capital the household must build. The old single-salary arithmetic could not
  express that at all: it computed one gap and one target regardless of what anybody did.

What it deliberately does not do is choose. It reports what each path demands per year against what each path
frees, and which of those a household is willing to live is not an optimisation.
"""

from __future__ import annotations

from typing import Any, Callable

from ..model import bvg as _bvg
from ..model.dynamics import ahv_pension, earning_power, income_tax, learning_effect, network_effect
from .gameplan import NETWORK_KNEE_HOURS as _KNEE
from .gameplan import education_hours as _education_hours
from .gameplan import expertise_after as _expertise_after
from .gameplan import network_after as _network_after
from ..model.params import Params

SCHEMA = "paths@0.1.0"


# --- lbsim extensions -------------------------------------------------------------------------------------
#
# A submission built by `lbsim.adapter` may carry an `lbsim` block; a draft submission never does, and without
# it every function below computes exactly what the draft computes (golden layer A holds that to 1e-9). The
# block carries two of the calibration's decisions:
#
#   `inflation`          LBSIM-08: the sheet's own inflation, a simple annual rate. Wages and spending pass it
#                        through at 1.0, the pillar-2 accrual is nominal, and every goal is read in the francs of
#                        its date. At 0.0 each factor below is exactly 1.0.
#   `model_level_factor` LBSIM-11: where no income is stated at all, the level is the one earning-power
#                        computation's full-time income (the responsibility multiplier times the BFS 40-hour
#                        share of the 100-hour productive week). 1.0 is the draft's reading.

def _ext(submission: dict) -> dict:
    return submission.get("lbsim") or {}


def _inflation(submission: dict) -> float:
    return float(_ext(submission).get("inflation") or 0.0)


def _price(submission: dict, years: float) -> float:
    """The price level `years` from now at the submission's inflation; exactly 1.0 without one."""
    pi = _inflation(submission)
    return (1.0 + pi) ** years if pi else 1.0

#: Full-time hours a week. The health section already uses 50 as the threshold above which overwork begins;
#: this is the different quantity of what a 100 % Pensum means, and 42 is the ordinary Swiss full-time week.
#: Only ever used as a RATIO against the household's stated hours, so a household working 21 hours reads as a
#: half Pensum whatever the exact convention.
FULL_TIME_HOURS = 42.0

#: Networking time a path invests, in hours a week: the model's own knee, imported from where the network
#: LEVER is priced rather than restated. A lever costed at one intensity and a path at another would be two
#: different offers wearing one name.
NETWORK_HOURS_AT_KNEE = _KNEE

#: How far a path is projected. Long enough to reach the reference age of a young household, and capped so a
#: submission with a broken birth year cannot produce a thousand-year loop.
MAX_YEARS = 60

#: How many years of skill growth a path credits before holding expertise and network fixed.
#:
#: **Measured, and the reason is a limit of the engine rather than a preference.** `beta_E` is autonomous
#: expertise growth of 15 % a year -- expertise compounds whether or not anybody studies -- and `earning_power`
#: is bounded at `earning_power_max`. Projected from E = 0.9 those two meet fast:
#:
#:     year  0   E 0.90   208 636 without study,  208 636 with
#:     year  5   E 1.81   379 196            ,   443 042
#:     year 10   E 3.64   500 000  ceiling  ,   500 000  ceiling
#:     year 41   E 277             ceiling  ,            ceiling
#:
#: After about seven years every path sits on the ceiling and the model can no longer tell an education from no
#: education. Projecting it to 65 anyway would produce four rows that look distinct and are identical, which is
#: worse than a shorter claim. Five years is the window `levers` already trusts for exactly this reason.
#:
#: Beyond it only the age profile moves, and the difference a path bought inside the window is carried forward.
#: That understates a long career of compounding skill -- stated in the assumptions rather than hidden -- and
#: it is the conservative direction: it credits no path with growth the engine cannot substantiate.
SKILL_PROJECTION_YEARS = 5


def _plain(x: Any) -> float:
    """A plain Python float.

    **The model's functions return numpy scalars and this crosses a process boundary.** `ahv_pension` and
    `earning_power` hand back `np.float64`, a comparison of two of them is `np.bool_`, and `json.dumps` refuses
    it -- so the whole report failed to serialise with "Object of type bool is not JSON serializable", far from
    the line that produced it. Coerced at the edge, where the values leave this module.
    """
    return float(x)


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


def _pensum_now(raw: dict) -> float:
    """Today's working share, from the stated hours. 1.0 when nothing is stated."""
    hours = _num(raw, "hours_per_week")
    if not hours or hours <= 0:
        return 1.0
    return max(0.05, min(1.5, hours / FULL_TIME_HOURS))


def _education_end_age(submission: dict, raw: dict) -> float | None:
    """The age at which the education in progress finishes, from the year the client named."""
    age = float((submission.get("state") or {}).get("age") or 0.0)
    collected = (submission.get("meta") or {}).get("collected") or ""
    year_now = int(collected[:4]) if collected[:4].isdigit() else None
    text = " ".join(str(raw.get(k) or "") for k in ("education_recent", "education_planned", "education"))
    years = [int(y) for y in _YEAR_RE.findall(text)] if text else []
    if not years or not year_now or not age:
        return None
    end = max(years)
    return age + max(0.0, float(end - year_now))


import re  # noqa: E402 - used only by the helper above, kept next to it rather than at the top

_YEAR_RE = re.compile(r"\b(20[2-9]\d)\b")


def _expertise_path(E0: float, p: Params, *, learning_hours: float, budget: float) -> Callable[[int], float]:
    """Expertise after n years, memoised. One recurrence, defined in `gameplan` and called from both."""
    cache: dict[int, float] = {}

    def at(n: int) -> float:
        n = max(0, int(n))
        if n not in cache:
            cache[n] = _expertise_after(E0, p, years=n, learning_hours=learning_hours, budget=budget)
        return cache[n]

    return at


def _network_path(N0: float, p: Params, *, hours: float) -> Callable[[int], float]:
    """Network after n years, memoised. Same recurrence the network lever is priced with."""
    cache: dict[int, float] = {}

    def at(n: int) -> float:
        n = max(0, int(n))
        if n not in cache:
            cache[n] = _network_after(N0, p, years=n, hours=hours)
        return cache[n]

    return at


def path_inputs(submission: dict, p: Params) -> dict[str, Any]:
    """Everything a path is built from, read off the submission once.

    Separated because `income_paths` and `app.search` need the same values and reading them twice is how two
    callers come to disagree about what a household said.
    """
    raw = submission.get("raw") or {}
    state = submission.get("state") or {}
    return {
        "age0": float(state.get("age") or 0.0),
        "E0": float(state.get("E") or 0.5),
        "N0": float(state.get("N") or 0.5),
        "gross_now": _num(raw, "income_gross") or 0.0,
        "pensum_now": _pensum_now(raw),
        # The banded answer through the shared parser: reading "mehr als 10" as zero dropped both education
        # paths from the table without saying so, which is the quietest way to overstate how much was explored.
        "edu_hours": _education_hours(raw) or 0.0,
        "edu_budget": _num(raw, "education_budget") or 0.0,
        "edu_end": _education_end_age(submission, raw),
        "anchor": _num(raw, "income_expected_full"),
    }


def build_path(submission: dict, p: Params, *, code: str, name: str, learning: float,
               network_hours: float, pensum_after: float | None, note: str = "",
               inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """One income path, from the three decisions that define it.

    **Public because the four presets are not the only points worth reaching.** This was a closure inside
    `income_paths`, which made those four the only paths obtainable and any fifth a hand-written entry in the
    same list. `app.search` walks a grid over the same three arguments plus spending and the stop age, so the
    builder had to become callable from outside.

    The level is anchored on the client's own expectation where they gave one: the model's curve says how
    earning power MOVES, the client says what it is worth at one point. Without that answer the model's own
    absolute level is used, and `basis` says which of the two it was, because a stated level and a modelled
    one are different claims.
    """
    i = inputs or path_inputs(submission, p)
    age0, edu_end, pensum_now, anchor = i["age0"], i["edu_end"], i["pensum_now"], i["anchor"]

    e_at = _expertise_path(i["E0"], p, learning_hours=learning,
                           budget=i["edu_budget"] if learning else 0.0)
    n_at = _network_path(i["N0"], p, hours=network_hours)
    corrected = _ext(submission).get("income_paths") == "corrected"
    if corrected:
        # lbsim (DECISIONS P-9, calibration 1.2.0): a path is credited only with what its OWN education and
        # networking add, measured against not doing them -- the counterfactual the draft's `levers` already uses.
        # The draft credited every path, `today` included, with `beta_E` autonomous expertise growth of 15 % a
        # year for five years, which roughly doubles the income of a household that changes nothing.
        e_with, e_without = e_at, _expertise_path(i["E0"], p, learning_hours=0.0, budget=0.0)
        n_with, n_without = n_at, _network_path(i["N0"], p, hours=0.0)
        E0, N0 = i["E0"], i["N0"]

        def e_at(n: int) -> float:  # noqa: F811
            return E0 + (e_with(n) - e_without(n))

        def n_at(n: int) -> float:  # noqa: F811
            return N0 + (n_with(n) - n_without(n))

    def shape(age: float) -> float:
        # Skill growth is credited for `SKILL_PROJECTION_YEARS` and then held; only the age profile moves
        # afterwards. See that constant for the measurement that forced it.
        n = min(int(max(0.0, age - age0)), SKILL_PROJECTION_YEARS)
        return earning_power(e_at(n), n_at(n), age, p)

    if anchor:
        base_age = edu_end if edu_end is not None else age0
        denom = shape(base_age) or 1.0
        def level(age: float) -> float:
            return anchor * shape(age) / denom
    elif i["gross_now"] and pensum_now:
        denom = shape(age0) or 1.0
        full_now = i["gross_now"] / pensum_now
        def level(age: float) -> float:
            return full_now * shape(age) / denom
    else:
        factor = float(_ext(submission).get("model_level_factor") or 1.0)
        if factor == 1.0:
            level = shape
        else:
            def level(age: float) -> float:
                return factor * shape(age)

    if _ext(submission).get("income_levels") == "stated":
        return _stated_levels(submission, p, i, shape, code=code, name=name, note=note, learning=learning,
                              network_hours=network_hours, pensum_after=pensum_after)

    def income_at(age: float) -> float:
        """Gross income at this age: full-time earning power scaled by the Pensum this path assumes."""
        if corrected and pensum_after is not None and edu_end is None:
            # lbsim (P-9): with no education to finish, a path's pensum applies from today. The draft applied it
            # only after an education's end, so without one `full_pensum` and `network` were `today` exactly.
            share = pensum_after
        elif pensum_after is None or edu_end is None or age < edu_end:
            share = pensum_now
        else:
            share = pensum_after
        return max(0.0, level(age) * share)

    return {"code": code, "name": name, "note": note, "income_at": income_at,
            "pensum_now": pensum_now, "pensum_after": pensum_after if pensum_after else pensum_now,
            "education_end_age": edu_end, "learning_hours": learning, "network_hours": network_hours,
            "basis": "stated" if anchor else "modelled", "anchor": anchor}


def _stated_levels(submission: dict, p: Params, i: dict[str, Any], shape: Callable[[float], float], *, code: str,
                   name: str, note: str, learning: float, network_hours: float,
                   pensum_after: float | None) -> dict[str, Any]:
    """lbsim (DECISIONS P-25, calibration 1.5.0): each stated figure where it belongs.

    The draft levelled every path, `today` included, on the stated expectation at a full pensum, from today, and
    multiplied it by today's pensum, so a person working 55 hours who expects 155 000 at a full pensum was shown
    203 000 in the first year. Here:

      before the change   today's stated income at today's pensum (today's income over today's pensum, moved by
                          the path's shape), on every path until an education ends, and on `today` always;
      after the change    from the education's end year (from today when none is stated) on a path that changes
                          something: the stated expectation at the path's pensum, and since the amount is stated
                          AT a full pensum, a pensum above 1 never raises it. Without an expectation today's level
                          carries on at the path's pensum.

    Where no income is stated today, the stated expectation (else the model level, also a full-time figure) is the
    level before the change too, never above a full pensum.
    """
    age0, edu_end, pensum_now, anchor = i["age0"], i["edu_end"], i["pensum_now"], i["anchor"]
    gross_now = i["gross_now"]
    changes = bool(learning > 0 or pensum_after is not None or network_hours > 0)
    start = edu_end if edu_end is not None else age0
    denom_now = shape(age0) or 1.0
    factor = float(_ext(submission).get("model_level_factor") or 1.0)

    if gross_now and pensum_now:
        full_now = gross_now / pensum_now

        def current(age: float) -> tuple[float, bool]:
            return full_now * shape(age) / denom_now, False
    elif anchor:
        def current(age: float) -> tuple[float, bool]:
            return anchor * shape(age) / denom_now, True
    else:
        def current(age: float) -> tuple[float, bool]:
            return factor * shape(age), True

    if anchor:
        denom_end = shape(start) or 1.0

        def after(age: float) -> tuple[float, bool]:
            return anchor * shape(age) / denom_end, True
    else:
        after = current

    def income_at(age: float) -> float:
        if changes and age >= start:
            amount, at_full_pensum = after(age)
            share = pensum_after if pensum_after is not None else pensum_now
        else:
            amount, at_full_pensum = current(age)
            share = pensum_now
        if at_full_pensum:
            share = min(share, 1.0)
        return max(0.0, amount * share)

    return {"code": code, "name": name, "note": note, "income_at": income_at,
            "pensum_now": pensum_now, "pensum_after": pensum_after if pensum_after else pensum_now,
            "education_end_age": edu_end, "learning_hours": learning, "network_hours": network_hours,
            "basis": "stated" if anchor else "modelled", "anchor": anchor}


def income_paths(submission: dict, p: Params) -> list[dict[str, Any]]:
    """The four named paths: a default table for a report, not the only reachable points.

    Each differs from the one before it by exactly one decision the household can make, so the rows read as
    the price of that decision rather than as four unrelated futures. `app.search` walks the whole space these
    four are drawn from, including spending and the stop age, which no preset varies.
    """
    i = path_inputs(submission, p)
    edu_hours = i["edu_hours"]

    def build(code: str, name: str, *, learning: float, network_hours: float,
              pensum_after: float | None, note: str) -> dict[str, Any]:
        return build_path(submission, p, code=code, name=name, learning=learning,
                          network_hours=network_hours, pensum_after=pensum_after, note=note, inputs=i)

    paths = [
        build("today", "Ohne Weiterbildung, Pensum bleibt", learning=0.0, network_hours=0.0,
              pensum_after=None,
              note="Keine zusätzliche Ausbildung, keine Änderung am Pensum. Das Einkommen steigt hier "
                   "trotzdem: Erfahrung wächst im Modell von selbst weiter, auch wenn niemand etwas dafür "
                   "tut. Im späten Erwerbsleben fällt es wieder. Das ist die Vergleichslinie, nicht "
                   "«das Einkommen bleibt, wie es ist»."),
        build("education", "Weiterbildung, Pensum bleibt", learning=edu_hours, network_hours=0.0,
              pensum_after=None,
              note="Die geplante Weiterbildung findet statt, das Pensum bleibt reduziert. Zeigt, was die "
                   "Ausbildung allein trägt — getrennt von der Arbeitszeit, mit der sie sonst verwechselt "
                   "wird."),
        build("full_pensum", "Weiterbildung und volles Pensum", learning=edu_hours, network_hours=0.0,
              pensum_after=1.0,
              note="Nach Abschluss volles Pensum. Für einen Haushalt, dessen Einkommen heute wegen der "
                   "Ausbildung tief ist, ist das meist der grösste einzelne Schritt — und keiner, den ein "
                   "Portfolio ersetzen kann."),
        build("network", "Weiterbildung, volles Pensum und Netzwerk", learning=edu_hours,
              network_hours=NETWORK_HOURS_AT_KNEE, pensum_after=1.0,
              note=f"Zusätzlich {NETWORK_HOURS_AT_KNEE:.0f} Stunden pro Woche für Sichtbarkeit und Kontakte — "
                   f"der Knick der Modellkurve. Mehr bringt nach diesem Modell fast nichts."),
    ]
    if not edu_hours:
        # Nothing to educate: the two education paths would be identical to the ones around them, and four
        # rows that are secretly two is a table that overstates how much was explored.
        paths = [paths[0], paths[2], paths[3]]
    if _ext(submission).get("income_paths") == "corrected":
        # lbsim (P-9): the same rule for the network path. Where the model's network ceiling leaves no room, ten
        # hours a week add nothing and the row would repeat `full_pensum`; it is left out rather than shown.
        with_n = _network_after(i["N0"], p, years=SKILL_PROJECTION_YEARS, hours=NETWORK_HOURS_AT_KNEE)
        without_n = _network_after(i["N0"], p, years=SKILL_PROJECTION_YEARS, hours=0.0)
        if with_n <= without_n:
            paths = [x for x in paths if x["code"] != "network"]
    return paths


def _working_until(stop_age: float | None, p: Params) -> float:
    """The age contributions stop.

    **None means "not stated", and the honest reading of that is the reference age, not a crash.** Only
    `onb@0.1.3` asks when a household wants to stop; older submissions and hand-written ones return None, and
    every arithmetic here then subtracted a float from it. The whole paths section raised, the exception was
    recorded in a field nothing renders, and the section simply vanished from those reports.
    """
    return float(stop_age) if stop_age is not None else float(p.ahv_age)


def _flows_from_65(submission: dict, p: Params, path: dict, *, stop_age: float | None) -> dict[str, float]:
    """AHV and the second pillar under this path's income, which is what makes the target move.

    AHV is taken on the average income of the contributing years rather than on today's salary, because that
    is the quantity the first pillar is a function of; a path that raises income for thirty years raises it.
    """
    state = submission.get("state") or {}
    age0 = float(state.get("age") or 0.0)
    ref = p.ahv_age
    stop_age = _working_until(stop_age, p)
    span = [age0 + i for i in range(int(max(1.0, min(MAX_YEARS, stop_age - age0))))]
    # **Named `own_lifetime_income` rather than an average, and the rename was forced by a test that was
    # right to force it.** This is one household's own income meaned over its own contributing years -- the
    # quantity the first pillar is a function of -- but M74's guard bans key names that could denote a figure
    # drawn from other households, and it bans them by word rather than by intent. A field called
    # `average_income` in a report about one household invites exactly the reading the rule exists to prevent.
    own_lifetime_income = sum(path["income_at"](a) for a in span) / max(1, len(span))
    ahv = ahv_pension(own_lifetime_income, ref, p)
    # lbsim (LBSIM-08): the accrual is nominal, with the coordination thresholds indexed. In today's francs that
    # is the draft's loop at the real credited rate; the draft's own rate where there is no inflation.
    pi = _inflation(submission)
    interest = p.pension_interest if not pi else (1.0 + p.pension_interest) / (1.0 + pi) - 1.0
    accrual = _bvg.accrue(age_now=age0, age_stop=stop_age, age_reference=ref,
                          start_capital=float(state.get("W_P") or 0.0), interest=interest,
                          income_at=path["income_at"])
    from .gameplan import PILLAR2_CONVERSION_RATE  # one conversion rate, not two
    annuity = accrual["capital"] * PILLAR2_CONVERSION_RATE
    return {"ahv": _plain(ahv), "own_lifetime_income": _plain(own_lifetime_income),
            "pillar2_capital": _plain(accrual["capital"]), "pillar2_annuity": _plain(annuity),
            "total": _plain(ahv + annuity)}


def _free_cash(submission: dict, p: Params, gross: float) -> float:
    """What a year of this income frees, at today's spending and today's commitments.

    Spending is held at the stated figure rather than grown with income, and that is an assumption worth
    naming: a household that spends every franc of a rise saves none of it. The table's job is to show what
    each path *can* free, and what is then done with it is the household's decision.
    """
    raw = submission.get("raw") or {}
    spending = _num(raw, "spend_now") or 0.0
    p3a = min(_num(raw, "pillar3a_contribution") or 0.0, p.pillar3a_cap)
    taxable = max(0.0, gross - p3a)
    return gross - income_tax(taxable, p) - spending - p3a


def _free_cash_at(submission: dict, p: Params, gross: float, *, p3a_scale: float) -> float:
    """`_free_cash` in today's francs with the fixed pillar-3a payment deflated by `p3a_scale` (lbsim only)."""
    raw = submission.get("raw") or {}
    spending = _num(raw, "spend_now") or 0.0
    p3a = min(_num(raw, "pillar3a_contribution") or 0.0, p.pillar3a_cap) * p3a_scale
    taxable = max(0.0, gross - p3a)
    partner = float(p.partner_income or 0.0) if p.has_partner else 0.0
    if _ext(submission).get("income_paths") == "corrected" and partner > 0:
        # lbsim (P-9): the household's spending is paid from both incomes, so the second adult's income (fixed in
        # today's francs, the draft's exogenous partner) joins what a year frees, taxed the way `gameplan.cash_flow`
        # taxes it: jointly with the splitting factor when married, separately when not. The draft's ledger set
        # the whole household's spending against the principal's income alone.
        married = float(p.tax_split_factor or 1.0) > 1.0
        if married:
            tax = income_tax(max(0.0, gross + partner - p3a), p)
        else:
            tax = income_tax(taxable, p) + income_tax(partner, p)
        return gross + partner - tax - spending - p3a
    return gross - income_tax(taxable, p) - spending - p3a


def _capital_targets(submission: dict, p: Params, flows: dict[str, float]) -> list[dict[str, Any]]:
    """Every goal as a capital sum and a date, retirement among them rather than above them."""
    goals = submission.get("goals") or []
    collected = (submission.get("meta") or {}).get("collected") or ""
    year_now = int(collected[:4]) if collected[:4].isdigit() else None
    age0 = float((submission.get("state") or {}).get("age") or 0.0)
    out: list[dict[str, Any]] = []
    for g in goals:
        kind = str(g.get("kind") or "")
        year = g.get("target_year")
        amount = g.get("amount_chf")
        if not year or not year_now:
            continue
        years = max(1.0, float(year) - year_now)
        if kind in ("fi", "retirement"):
            # A flow goal states a spend per year. What it needs as capital is the part the flows at 65 do not
            # cover, at the model's withdrawal rate -- and under this path those flows are different.
            # lbsim (LBSIM-08): the gap is taken in today's francs, where the flows are, and the capital is then
            # read in the francs of the goal's date.
            real_amount = g.get("amount_real_chf") if _inflation(submission) else None
            spend = float((real_amount if real_amount is not None else amount) or p.G or 0.0)
            gap = max(0.0, spend - flows["total"])
            target = gap / p.swr if gap > 0 else 0.0
            target = target * _price(submission, years)
            basis = (f"Ausgaben {spend:,.0f} abzüglich {flows['total']:,.0f} aus AHV und Pensionskasse, "
                     f"bei {p.swr:.1%} Entnahme").replace(",", " ")
        elif amount:
            target = float(amount)
            basis = "genannter Kapitalbetrag"
        else:
            continue
        # **Priced here even where `required_return` defers it, and the flag is why that is consistent.**
        # What must be saved by a date follows from the amount and the date. What the purchase then does to
        # the balance sheet -- consumption, walled-off wealth, or an investment -- follows from the kind, and
        # that is the part an unresolved kind genuinely blocks.
        # lbsim (LBSIM-19): `capital` is resolved, a lump sum on drawable wealth.
        unresolved = kind not in ("fi", "retirement", "home", "company", "capital")
        out.append({"kind": kind, "description": g.get("description") or kind,
                    "target_year": int(year), "years": _plain(years), "age_at_goal": _plain(age0 + years),
                    "target": _plain(target), "basis": basis, "kind_unresolved": unresolved})
    return sorted(out, key=lambda r: r["target_year"])


def saving_required(target: float, present: float, years: float, rate: float) -> float:
    """The constant annual saving that reaches `target` in `years`, given what is there and a return.

    At zero this is the trivial difference over the years, which is the whole reason the first pass uses zero:
    a household can check it. Above zero it is the ordinary annuity, and where what is already there grows into
    the target on its own the answer is nothing rather than a negative number dressed as a saving.
    """
    if years <= 0:
        return max(0.0, target - present)
    if rate <= 0:
        return max(0.0, (target - present) / years)
    grown = present * (1.0 + rate) ** years
    if grown >= target:
        return 0.0
    return (target - grown) * rate / ((1.0 + rate) ** years - 1.0)


def simulate(submission: dict, p: Params, path: dict, *, stop_age: float | None,
             rates: tuple[float, ...] = (0.0,)) -> dict[str, Any]:
    """One path: its income over time, what it frees, and what each goal then demands per year.

    At a return of zero the arithmetic is deliberately trivial -- capital needed, less what is there, divided
    by the years -- and that is the point. The comparison that matters is against what the path frees, and no
    discounting or compounding can rescue a required saving that exceeds it.
    """
    state = submission.get("state") or {}
    age0 = float(state.get("age") or 0.0)
    liquid = float(state.get("W_L") or 0.0)
    flows = _flows_from_65(submission, p, path, stop_age=stop_age)
    goals = _capital_targets(submission, p, flows)

    years_out = []
    age = age0
    while age < min(age0 + MAX_YEARS, p.ahv_age):
        gross = path["income_at"](age)
        if _inflation(submission) or _ext(submission).get("income_paths") == "corrected":
            # lbsim (LBSIM-08): the year in the francs of that year. Wages and spending move with prices, a fixed
            # pillar-3a payment does not, and the tax tariff is indexed (the cold progression is compensated).
            level = _price(submission, age - age0)
            real_free = _free_cash_at(submission, p, gross, p3a_scale=1.0 / level)
            years_out.append({"age": round(age, 1), "gross": _plain(gross * level),
                              "free": _plain(real_free * level)})
        else:
            years_out.append({"age": round(age, 1), "gross": _plain(gross),
                              "free": _plain(_free_cash(submission, p, gross))})
        age += 1.0

    def mean_free(until_age: float) -> float:
        window = [y["free"] for y in years_out if y["age"] < until_age] or [0.0]
        return sum(window) / len(window)

    rows = []
    for g in goals:
        available = mean_free(g["age_at_goal"])
        # **Zero first, then the returns.** The zero column is the overview: it says what the goal costs in
        # saving alone, which is a number a household can verify and which no market can be blamed for. The
        # further columns then ask the question the first pass deliberately set aside -- whether a return
        # closes what is left -- and they are labelled with whose expectation each rate is.
        by_rate = {f"{r:.4f}": _plain(saving_required(g["target"], liquid, g["years"], r)) for r in rates}
        required = by_rate[f"{0.0:.4f}"] if f"{0.0:.4f}" in by_rate else _plain(
            saving_required(g["target"], liquid, g["years"], 0.0))
        rows.append({**g,
                     "required_saving": _plain(required),
                     "required_by_rate": by_rate,
                     "reachable_by_rate": {k: bool(available >= v) for k, v in by_rate.items()},
                     "available_saving": _plain(available),
                     "shortfall_per_year": _plain(required - available),
                     # Stated as a fact about this path rather than as a verdict on the household: at zero
                     # return the two numbers are directly comparable, which is the whole reason for zero.
                     "reachable": bool(available >= required)})
    return {"code": path["code"], "name": path["name"], "note": path["note"], "basis": path["basis"],
            "anchor": path["anchor"], "pensum_now": path["pensum_now"], "pensum_after": path["pensum_after"],
            "education_end_age": path["education_end_age"],
            "income_now": _plain(years_out[0]["gross"]) if years_out else 0.0,
            "income_at_45": _plain(path["income_at"](45.0)),
            "free_now": _plain(years_out[0]["free"]) if years_out else 0.0,
            "flows_from_65": flows, "goals": rows, "years": years_out}


def return_rates(submission: dict, extra: tuple[float, ...] = ()) -> tuple[list[float], list[dict[str, str]]]:
    """The rates the goals are tested at, and whose expectation each one is.

    Zero is always first and is the report's own baseline. Any further rate belongs to somebody -- the client
    who stated it, or the mandate that derived it -- and is labelled with whose it is, because a return in a
    plan is a claim about the future and the report makes none of its own.
    """
    raw = submission.get("raw") or {}
    rates: list[float] = [0.0]
    labels: list[dict[str, str]] = [{"rate": "0.0000", "label": "ohne Rendite",
                                     "whose": "Grundlinie dieses Berichts"}]
    stated = _num(raw, "expected_return_pct")
    if stated is not None:
        r = stated / 100.0 if stated > 1.0 else stated
        if 0.0 < r < 0.30 and abs(r) > 1e-9:
            rates.append(r)
            labels.append({"rate": f"{r:.4f}", "label": f"{r:.1%} pro Jahr",
                           "whose": "Ihre eigene Renditeerwartung"})
    for r in extra:
        if r and 0.0 < r < 0.30 and f"{r:.4f}" not in {lab["rate"] for lab in labels}:
            rates.append(r)
            labels.append({"rate": f"{r:.4f}", "label": f"{r:.1%} pro Jahr",
                           "whose": "aus dem abgeleiteten Mandat"})
    return rates, labels


def ledger(submission: dict, p: Params, *, stop_age: float | None,
           extra_rates: tuple[float, ...] = ()) -> dict[str, Any]:
    """Every path against every goal, with the assumptions that hold the whole table up."""
    paths = income_paths(submission, p)
    rates, rate_labels = return_rates(submission, extra_rates)
    runs = [simulate(submission, p, path, stop_age=stop_age, rates=tuple(rates)) for path in paths]
    anchored = bool(runs and runs[0]["basis"] == "stated")
    return {
        "schema": SCHEMA,
        "return_assumed": 0.0,
        "rates": rate_labels,
        "paths": runs,
        "anchored": anchored,
        "assumptions": [
            "Die erste Spalte rechnet ohne Rendite. Das ist ein Überblick und keine Prognose: sie zeigt, "
            "was ein Ziel an reinem Sparen kostet, und diese Zahl hängt an Arbeitszeit, Ausbildung und "
            "Ausgaben statt am Markt. Die weiteren Spalten rechnen dann mit Rendite und beantworten die "
            "Frage, die der Überblick offenlässt: ob die Ziele damit erreicht werden. Was schon ohne "
            "Rendite trägt, braucht den Markt nicht; was auch mit Rendite nicht trägt, ist keine "
            "Anlagefrage.",
            ("Das Einkommensniveau stammt aus Ihrer eigenen Angabe zum vollen Pensum; die Form des Verlaufs "
             "aus dem Modell." if anchored else
             "Zum erwarteten Einkommen bei vollem Pensum liegt keine Angabe vor. Das Niveau stammt deshalb "
             "aus dem Modell selbst und ist eine Modellaussage, keine Ihrer Angaben."),
            "Die Ausgaben bleiben auf dem heutigen Stand. Ein Haushalt, der jede Erhöhung mitausgibt, spart "
            "von keinem dieser Wege etwas.",
            "AHV und Pensionskasse werden für jeden Weg neu gerechnet: ein höheres Einkommen hebt beide und "
            "senkt damit das Kapital, das für den Ruhestand aufzubauen ist.",
            "Kein Weg enthält Teuerung. Alle Beträge sind in heutigen Franken, und die Ziele ebenso.",
            f"Wissen und Netzwerk werden {SKILL_PROJECTION_YEARS} Jahre lang fortgeschrieben und danach "
            f"festgehalten; nur das Altersprofil bewegt sich weiter. Das Modell lässt Erfahrung mit 15 % pro "
            f"Jahr wachsen und die Ertragskraft ist nach oben begrenzt, sodass nach etwa sieben Jahren jeder "
            f"Weg an dieser Grenze liegt und die Wege ununterscheidbar würden. Der Verlauf ist damit eher zu "
            f"vorsichtig als zu günstig: eine lange Karriere baut mehr auf, als hier gerechnet ist.",
        ],
    }
