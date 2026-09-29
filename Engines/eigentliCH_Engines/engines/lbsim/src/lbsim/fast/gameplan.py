"""Task P5: the deterministic half of a gameplan, computed rather than written by hand.

**Why this exists.** Five dossiers were assembled by reading a submission, doing the arithmetic in a scratch
script and typing the results into HTML. Every figure in them is a rule applied to the intake, and
`architecture/manual-gameplan.html` is the written form of those rules. A manual that specifies a computation
completely is a specification, so this module *is* the manual, executed.

**The report does not need the optimiser.** Everything here runs in about a second on the intake alone. That is
not an optimisation, it is the point: measured runtimes are 40 minutes at a ten-year horizon and over seventy at
twenty, against a one-hour cap in `desktop/server.py`, so a long-horizon household has never been able to reach
a report through the product path. It can now reach every section but one. `facts` is optional throughout, and
where it is absent the affected section says so rather than vanishing.

**Nothing here is a Recommendation.** G7 reserves those for a named Curator with a Decision Record. Findings
carry an `action` because a Befund that names a problem and no response is half a Befund, but the actions are of
the form "ask this", "quantify that", "decide between these" -- never "buy this". The severities and urgencies
rank the reader's attention; they authorise nothing.

**Constants are imported, never restated (M67).** Two exceptions, both declared rather than hidden:
`PILLAR2_CONVERSION_RATE`, which is not a `Params` field and must appear in every dossier footer, and the
withdrawal rates shown alongside `p.swr`, which exist precisely to show the reader that the capital requirement
rests on an assumption. Nothing else here is a literal that also lives in `Params`.

**No number without a source.** Every entry is derived from an intake answer or an engine constant. Where an
answer is missing the field is `None` and the omission is reported -- never zero, because a zero reads as a
measurement.

**M74 holds by construction.** Like `ReportFacts`, nothing in this module's output can hold a second household:
there is no field for a peer, an average or a comparison, and the findings are evaluated against this
household's own figures and the engine's own constants only.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..model import bvg as _bvg
from ..model.dynamics import (
    _ahv_individual,
    ahv_pension,
    network_effect,
    child_cost_level,
    child_costs,
    delta_H,
    earning_power,
    income_tax,
    learning_effect,
    rest_effect,
    wealth_tax,
)
from ..model.params import Params
from ..model.state import HouseholdWealth

#: The converter's aliases (`app/onboarding.py`'s `_PARAM_ALIASES`), restated here. **lbsim port (LBSIM-03):** the
#: draft imported them from `app.onboarding`, which imports `cases`, which imports `optim.problem` and so `casadi`:
#: the fast half could not load without the optimiser. The one entry is copied, and a test holds it equal to the
#: draft's.
_ALIASES: dict[str, str] = {"mortgage_rate": "i"}

# Imported under a private name so a rule module cannot shadow a section function above.
from . import asks as _asks
from . import findings as _findings

SCHEMA = "gp@0.1.0"

#: The pillar-2 conversion rate. **Not a `Params` field, and deliberately not made one**: it is an
#: administrative parameter of a pension fund, not a property of this model, and a real pension certificate
#: replaces it. It is carried identically across every dossier so they stay comparable, and it must appear in
#: the footer of any report that quotes a pillar-2 annuity.
PILLAR2_CONVERSION_RATE = 0.0525

#: Withdrawal rates shown side by side. `p.swr` is the model's own; the other two exist so the reader sees the
#: spread. The manual is explicit that showing one rate hides that the capital requirement rests on an
#: assumption rather than on a fact.
WITHDRAWAL_RATES = (0.030, 0.035, 0.040)

#: Multiples of the household's own saving rate at which the required return is solved.
SAVING_MULTIPLES = (1.0, 1.5, 2.0)

#: Hours per week at which the health decay is tabulated. The household's own hours are inserted into this
#: ladder; the threshold row is always present because it is the comparison the reader needs.
HOURS_LADDER = (40.0, 50.0, 55.0, 60.0, 70.0, 75.0)

#: How many years of an AHV record a full entitlement takes. Not a `Params` field -- it is the divisor implied
#: by `ahv_record_share` being a share, and `_ahv_individual` never needs it because it receives the share
#: already computed. Stated here because "one missing year costs 1/44 of the pension" is a sentence a dossier
#: has to be able to write.
AHV_FULL_RECORD_YEARS = 44.0

#: Goal kinds whose `amount_chf` is a CAPITAL sum, and those whose `amount_chf` is an amount PER YEAR. The two
#: are not interchangeable and the schema does not distinguish them by type, only by kind. `app/onboarding.py`
#: encodes the same split in `_SHORTFALL_IS_RELATIVE` for a different purpose; the shared truth is that an `fi`
#: or `retirement` amount is a flow the household wants covered, while a `home` or `company` amount is a sum it
#: wants to hold.
#: The banded answer to "how many hours a week do you study" as a number, one band to its midpoint.
#:
#: **Module level because two callers need it.** It was written inline in `levers`, and `app/paths` -- which
#: projects the same education over a whole career rather than five years -- silently read every band as zero
#: and dropped its education paths entirely. One definition, imported (M67), rather than two that agree until
#: somebody edits one.
EDUCATION_HOURS_BANDS: dict[str, float] = {"keine": 0.0, "1–2": 1.5, "3–5": 4.0, "6–10": 8.0,
                                           "mehr als 10": 12.0}

#: Weekly hours a network lever assumes, at the model's own knee: `tau_N_scale = 0.10` is documented as
#: "10 h/week: anything more is useless". Shared with `app/paths` so the lever and the path price the same
#: decision -- a lever costed at one intensity and a path at another are not the same offer.
NETWORK_KNEE_HOURS = 10.0


def expertise_after(E0: float, p: Params, *, years: float, learning_hours: float, budget: float) -> float:
    """Expertise after `years` at a given weekly learning intensity and annual budget.

    **`beta_E * E` is autonomous growth: expertise compounds whether or not anybody enrols in anything.** At
    E = 0.78 it contributes 0.117 of the first year's 0.154, which is why every caller compares an educated
    path against a NOT-educated one rather than against today. Measured before that correction: an education
    credited with 191 968 on a real household, against a true effect a fraction of that.

    `learning_hours` is hours a week; the model's control is a share of time, so it is divided by 100 here --
    the same convention `tau_E_scale = 0.20` is written in.
    """
    e = float(E0)
    for _ in range(int(round(max(0.0, years)))):
        e = max(0.0, e + p.alpha_E * learning_effect(learning_hours / 100.0, p)
                + p.kappa_E * budget + p.beta_E * e)
    return e


def network_after(N0: float, p: Params, *, years: float, hours: float) -> float:
    """Network after `years` at a given weekly networking intensity, saturating toward the base ceiling.

    The ceiling is `K_N0` and not `dynamics.network_ceiling`, which lifts with expertise and wealth. Two
    reasons, and the second is the one that matters: the paths this shares with run at zero return with no
    portfolio, so a wealth-lifted ceiling would credit the exercise with the very thing it excludes; and a
    lever priced against one ceiling in the lever list and another in the paths table is not comparable to
    itself.
    """
    n = float(N0)
    for _ in range(int(round(max(0.0, years)))):
        room = max(0.0, p.K_N0 - n)
        n = n + p.alpha_N * network_effect(hours / 100.0, p) * (room / max(p.K_N0, 1e-9))
    return n


def education_hours(raw: dict) -> float | None:
    """Weekly study hours: the free number where one was given, else the band's midpoint."""
    hours = _num(raw, "education_hours_num")
    if hours is None:
        hours = EDUCATION_HOURS_BANDS.get(_str(raw, "education_hours"))
    return hours


#: lbsim (LBSIM-19): `capital`, a lump sum on drawable wealth, is the kind a lbs goal of kind `other` with an
#: amount and a date maps to. A draft submission never carries it.
_CAPITAL_GOAL_KINDS = frozenset({"home", "company", "capital"})

#: Why a stated goal is not in the arithmetic, in the reader's language. The keys mirror the converter's
#: `_NON_GOAL_KIND_REASONS`, which says the same things in the engine's terms; `test_gameplan` holds the two
#: sets together so a kind that gains a slack function cannot leave a stale sentence here.
#:
#: **`other` is the one that cost a real report.** A household stated "Eigentum kaufen 2037 2 Mio", the
#: intake could not tell a Wohneigentum from a Ferienobjekt from a Firma -- he had ticked all three -- and the
#: dossier answered a different question at 17,50 % a year without mentioning his.
_DEFERRAL_REASONS: dict[str, str] = {
    "other": "Die Art dieses Ziels ist offen. Ein Ferienobjekt ist Konsum, Wohneigentum ist abgeschottetes "
             "Vermögen, eine Firma ist eine Investition — die drei rechnen sich unterschiedlich, und aus dem "
             "Wortlaut allein ist nicht zu entscheiden, welches gemeint ist.",
    "holiday_home": "Ein Ferienobjekt ist im Modell Konsum und kein Ziel, das der Optimierer finanziert: es "
                    "steht im Vermögensblock mit negativer Nettorendite und im Ausgabenpfad.",
    "education": "Ausbildung erreicht das Modell über die Steuergrössen für Zeit und Budget, die der "
                 "Optimierer selbst wählt. Als Ziel gerechnet, wäre sie doppelt gezählt.",
    "legacy": "Nachlass wirkt im Modell über das Gewicht des Endvermögens, nicht als datierte Bedingung.",
}
_FLOW_GOAL_KINDS = frozenset({"fi", "retirement"})


# --- reading the intake ---------------------------------------------------------------------------------
#
# `raw` is the interview's own answers, and several findings can be checked from nowhere else: the schema's
# `state` and `params` blocks are already reduced to what the engine consumes, and a reduction cannot be
# un-reduced. Reading `raw` is therefore not a way around the converter, it is reading a different thing.
# Every access goes through these helpers, which return None rather than zero for a missing answer.

def _num(raw: dict, key: str) -> float | None:
    v = raw.get(key)
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = (str(v).replace("%", "").replace("'", "").replace("’", "")
         .replace(" ", "").replace(" ", "").replace(",", "."))
    try:
        return float(s)
    except ValueError:
        return None


def _str(raw: dict, key: str) -> str:
    v = raw.get(key)
    return "" if v is None else str(v)


def _list(raw: dict, key: str) -> list[str]:
    v = raw.get(key)
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def _pct(raw: dict, key: str) -> float | None:
    """A percentage answer as a fraction. `'20 %'` becomes 0.20."""
    v = _num(raw, key)
    return None if v is None else v / 100.0


def _fmt(x: float | None, digits: int = 0) -> str:
    """Swiss thousands separation, for the strings a finding carries inside its own text."""
    if x is None:
        return "-"
    return f"{x:,.{digits}f}".replace(",", " ")


def _d(x: float | None, digits: int = 2) -> str:
    """A decimal number in German notation.

    **Not cosmetic.** These strings are read straight into a German dossier, and a trigger reading
    "4.75-fach" beside a table reading "4,75" tells the reader the two were produced by different hands --
    which was true, and is exactly what this layer exists to stop being true.
    """
    if x is None:
        return "-"
    return f"{x:.{digits}f}".replace(".", ",")


def _p(x: float | None, digits: int = 1) -> str:
    """A percentage in German notation. Plain space before the sign, matching `dossier.pc`."""
    if x is None:
        return "-"
    return f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def _params_from(submission: dict) -> Params:
    """`Params` with every intake value the schema carries applied, and nothing else.

    Only keys that are `Params` fields are applied. The rest of the `params` block is goal spec, controls and
    mandate hints, which `app/onboarding.py` documents at length: applying them would raise, and filtering them
    silently is the failure that module exists to prevent. So they are matched by name against the dataclass,
    which cannot drift from the dataclass.
    """
    fields = set(Params.__dataclass_fields__)
    block = submission.get("params") or {}
    given = {k: v for k, v in block.items() if k in fields and v is not None}
    # **The same aliases the converter applies, from the converter.** `mortgage_rate` is `Params.i` under the
    # schema's own name, and a report that filtered it out would print the model's 2 % beside a cash flow the
    # engine had computed at the household's real rate -- two different mortgages in one document. Imported
    # rather than restated for exactly the reason M67 gives.
    for key, target in _ALIASES.items():
        if block.get(key) is not None and target in fields:
            given[target] = block[key]
    for key in ("child_ages",):
        if isinstance(given.get(key), list):
            given[key] = tuple(float(a) for a in given[key])

    # **The canton, applied here as well as in the converter, because a report that says "calibrated" while
    # computing the national rate is worse than one that says nothing.** The two paths build `Params`
    # independently -- the converter for the engine, this for the arithmetic the client actually reads -- so
    # a factor applied in only one of them puts two different tax rates in one document. An explicit rate in
    # the submission still outranks the table: a figure somebody entered is about this household, and the
    # table is about a canton.
    name = str((submission.get("raw") or {}).get("canton") or "").strip()
    if name:
        try:
            from ..model import canton as _canton  # noqa: PLC0415
            cf = _canton.factors_for(name)
        except Exception:  # noqa: BLE001 - a missing or broken table leaves the national approximation
            cf = None
        if cf and cf["calibrated"]:
            base = Params()
            if "tax_rate_max" not in given:
                given["tax_rate_max"] = base.tax_rate_max * float(cf["income_factor"])
            if "wealth_tax_rate" not in given:
                given["wealth_tax_rate"] = base.wealth_tax_rate * float(cf["wealth_factor"])

    return replace(Params(), **given)


def _wealth(submission: dict) -> HouseholdWealth:
    s = submission.get("state") or {}

    def g(k: str) -> float:
        return float(s.get(k) or 0.0)

    return HouseholdWealth(W_L=g("W_L"), W_R=g("W_R"), D=g("D"),
                           W_res=g("W_res"), W_hol=g("W_hol"),
                           W_P=g("W_P"), W_3a=g("W_3a"))


def _stop_age(submission: dict, p: Params) -> float | None:
    """The age the household wants to stop earning, or None.

    **`onb@0.1.3` asks this for the first time, and its absence was a real defect.** Every bridge in every
    worked dossier was computed from a stop age read out of free text by hand -- "Ab 55 nicht mehr arbeiten zu
    muessen" -- because the interview asked what retirement should cost and until what age to compute, and never
    from what age. A computation that depends on an answer nobody is asked cannot be deterministic. Older
    submissions return None here and the bridge section says why it is absent rather than guessing a 55.
    """
    # `params` first, then `raw`. The interview emits it in both -- `raw` is its own record of the answer,
    # `params` is where a reader looks -- and reading only one of them would break on a submission written by
    # hand, which is how several of the worked cases arrived.
    v = _num(submission.get("params") or {}, "stop_work_age")
    if v is None:
        v = _num(submission.get("raw") or {}, "stop_work_age")
    # Above the reference age it is not an early stop and there is no bridge to price. Zero or negative is a
    # malformed answer, and both return None rather than a guess.
    if v is None or v <= 0 or v >= p.ahv_age:
        return None
    return v


# --- the sections --------------------------------------------------------------------------------------

def balance(submission: dict, p: Params) -> dict:
    """The balance sheet, its drawable share, and what the intake recorded outside it.

    **The omissions are part of the balance sheet, not an appendix to it.** Every worked case had positions the
    model has no line for, and in one they came to 530 000 against a drawable 130 000. A statement of net worth
    that does not name them is wrong by more than the amount.
    """
    raw = submission.get("raw") or {}
    w = _wealth(submission)
    dr = w.drawable(h_res=p.h_res, q_inv=p.q_inv, q_hol=p.q_hol)

    outside: list[dict] = []
    for key, label, why in (
        ("company_value", "Firmenbeteiligung",
         "das Modell führt keine Position für eine Unternehmensbeteiligung"),
        ("loans_given", "private Darlehen, gegeben",
         "eine Forderung mit ungewissem Eingang ist keine Vermögensposition des Modells"),
        ("collectibles_value", "Sammlungen, Kunst, Fahrzeuge",
         "ein illiquider Wert ohne Ertrag hat im Modell keine Zeile"),
        # lbsim port: a financial stock the Life Balance Sheet carries without a vessel (lbs LBS-24) has no line
        # here either. The key never occurs in a draft submission, so the draft's output is unchanged.
        ("unassigned_value", "Positionen ohne Gefäss",
         "eine Position ohne Angabe, ob frei, Vorsorge oder Liegenschaft, hat im Modell keine Zeile"),
    ):
        v = _num(raw, key)
        if v:
            outside.append({"label": label, "amount": v, "why": why})

    # Gold and crypto ARE modelled: the interview folds them into W_L because they trade daily. Saying so is
    # worth a line, because a reader who sees "Sammlungen nicht enthalten" will assume the same of the gold.
    inside = [lbl for key, lbl in (("gold_value", "Gold und Edelmetalle"),
                                   ("crypto_value", "Kryptowährungen"))
              if _num(raw, key)]

    return {
        "liquid": w.W_L,
        "property_total": w.W_R,
        "residence": w.W_res,
        "holiday": w.W_hol,
        "let": w.W_inv,
        "debt": w.D,
        "ltv": (w.D / w.W_R) if w.W_R else None,
        "pillar2": w.W_P,
        "pillar3a": w.W_3a,
        "net_worth": w.net_worth,
        "total_wealth": w.total_wealth,
        "drawable": dr,
        "drawable_share": (dr / w.total_wealth) if w.total_wealth else None,
        "outside_model": outside,
        "outside_total": sum(o["amount"] for o in outside),
        "inside_liquid": inside,
        "kinds_declared": _list(raw, "other_kinds"),
        "asset_scope": _str(raw, "asset_scope") or None,
        "why_walled": ("h_res = q_inv = q_hol = 0: die selbst bewohnte Liegenschaft ist vollständig "
                       "abgeschottet, die vermietete erreicht den Haushalt nur über den Ertrag. "
                       "Entnahmefähig ist deshalb in der Regel nur das liquide Vermögen."),
    }


def income_from_65(submission: dict, p: Params, stop_age: float | None = None) -> dict:
    """AHV, pillar 2 as an annuity, and net rent: the flows that exist at 65 without a decision."""
    raw = submission.get("raw") or {}
    w = _wealth(submission)
    age = float((submission.get("state") or {}).get("age") or 0.0)
    gross = _num(raw, "income_gross")
    ref = p.ahv_age

    ahv_own = _ahv_individual(gross, ref, p.ahv_record_share, p) if gross is not None else None
    ahv_hh = ahv_pension(gross, ref, p) if gross is not None else None

    # **Pillar 2 forward, built the way the law builds it.** Contributions run to the age the household says
    # it stops, not to 65 -- a household that stops at 55 contributes for ten fewer years, and that difference
    # is the permanent cost the manual insists on naming -- and what is already accrued keeps earning interest
    # to the reference age either way.
    #
    # What changed, and it changed by an order of magnitude on the household that prompted it: the credit is a
    # statutory percentage of the COORDINATED salary and starts at 25, not a flat 15 % of full income from
    # whatever age the client happens to be. A twenty-four-year-old on 24 000 was credited 3 600 a year from
    # today, reaching 172 824 by 65 and an annuity of 9 073 -- a third of the income the report promised him
    # from 65, out of years he is not legally accruing in. The same figures under the law: 19 697 and 1 034.
    #
    # `income_at` is a function of age because that is the seam the path simulation needs. It returns one
    # constant today; a household whose education finishes and whose Pensum rises accrues differently, and the
    # closed-form annuity factor this replaces could only ever express a flat salary.
    years_to_ref = max(0.0, ref - age)
    n_contrib = max(0.0, (stop_age if stop_age is not None else ref) - age)
    r = p.pension_interest
    accrual = _bvg.accrue(
        age_now=age, age_stop=(stop_age if stop_age is not None else ref), age_reference=ref,
        start_capital=w.W_P, interest=r, income_at=lambda _age: (gross or 0.0))
    capital = accrual["capital"]
    annuity = capital * PILLAR2_CONVERSION_RATE

    rent = p.y_R * w.W_inv
    holiday = p.y_hol * w.W_hol
    parts = [x for x in (ahv_hh, annuity, rent, holiday) if x is not None]
    return {
        "reference_age": ref,
        "years_to_reference": years_to_ref,
        "ahv_own": ahv_own,
        "ahv_household": ahv_hh,
        "ahv_max_single": p.ahv_full_single,
        "ahv_income_for_max": p.ahv_income_for_max,
        "ahv_record_share": p.ahv_record_share,
        "ahv_couple_cap": p.ahv_full_single * p.ahv_couple_cap_multiple,
        "ahv_is_regressive": (gross is not None and gross > p.ahv_income_for_max),
        "ahv_partner_gated": (p.has_partner and (p.partner_age_offset or 0) > 0),
        "pillar2_today": w.W_P,
        # The sourced mechanism behind the figure, so the report can state it rather than assert a number.
        "pillar2_credited_total": accrual["contributed"],
        "pillar2_entry_threshold": accrual["entry_threshold"],
        "pillar2_coordination_deduction": accrual["coordination_deduction"],
        "pillar2_min_coordinated": accrual["min_coordinated"],
        "pillar2_savings_start_age": accrual["savings_start_age"],
        "pillar2_coordinated_now": _bvg.coordinated_salary(gross or 0.0, _bvg.load()),
        "pillar2_rate_now": _bvg.savings_rate(age, _bvg.load()),
        "pillar2_below_entry": (gross or 0.0) < accrual["entry_threshold"],
        "pillar2_not_yet_accruing": age < accrual["savings_start_age"],
        "pillar2_table_as_of": accrual["as_of"],
        "pillar2_table_source": accrual["source"],
        "pillar2_capital": capital,
        "pillar2_annuity": annuity,
        "pillar2_years_contributing": n_contrib,
        "pillar2_interest": r,
        "pillar2_contribution_rate": p.pension_contribution_rate,
        "conversion_rate": PILLAR2_CONVERSION_RATE,
        "rent_net": rent,
        "rent_yield": p.y_R,
        "holiday_yield_net": holiday,
        "total": sum(parts),
        # The gate is smooth: at exactly 65 the entitlement pays about 98 %, settling shortly after. The value
        # at 65 is quoted for consistency with the earlier dossiers, and the 2 % is not economic.
        "gate_note": ("Die Altersschwelle ist im Modell weich. Bei genau 65 zahlt der Anspruch rund 98 %, "
                      "kurz danach 100 %. Die 2 % sind eine Eigenschaft der Glättung und keine "
                      "wirtschaftliche Aussage."),
    }


def gap_and_capital(p: Params, flows: float) -> dict:
    """The shortfall against the target spend, and the capital it implies at three withdrawal rates."""
    gap = p.G - flows
    return {
        "target_spend": p.G,
        "flows": flows,
        "gap": gap,
        "model_rate": p.swr,
        "capital": {f"{r:.3f}": (gap / r if gap > 0 else 0.0) for r in WITHDRAWAL_RATES},
        "annuity_beats_withdrawal": PILLAR2_CONVERSION_RATE > max(WITHDRAWAL_RATES),
        "annuity_note": ("Der Vergleich folgt aus diesen Sätzen und ist keine allgemeine Regel: "
                         f"{_p(PILLAR2_CONVERSION_RATE, 2)} Umwandlung gegen höchstens "
                         f"{_p(max(WITHDRAWAL_RATES), 1)} Entnahme."),
    }


def cash_flow(submission: dict, p: Params) -> dict:
    """The surplus, in both readings, with the tax correction the manual requires.

    **Two readings, always.** Where a partner's income sits in the household total, the surplus is computed once
    with both incomes and once with the subject's alone bearing every cost. The honest range persuades where the
    flattering number invites the objection.

    **The unmarried-couple correction.** For `ledig, mit Partner` the converter sets no splitting factor, which
    is right, but the partner's income still joins the taxable base and is taxed at the single tariff. In reality
    they are assessed separately. Both figures are computed, the corrected one is used, and the difference is
    reported -- on a professional two-income household it is a five-figure sum.
    """
    raw = submission.get("raw") or {}
    params_block = submission.get("params") or {}
    w = _wealth(submission)
    gross = _num(raw, "income_gross") or 0.0
    partner = float(p.partner_income or 0.0)
    rent = p.y_R * w.W_inv
    company = _num(raw, "company_income") or 0.0
    other = _num(raw, "other_income") or 0.0
    interest = p.i * w.D
    spending = _num(raw, "spend_now")
    if spending is None:
        spending = p.G
    amort_direct = float(params_block.get("p_A") or 0.0)
    amort_indirect = float(params_block.get("amortisation_indirect") or 0.0)

    # `pillar3a_contribution` is a FRACTION of income in `Params`, as `pillar3a_flow` reads it, but the
    # interview asks for francs. The schema carries whatever the interview sent, so both readings have to be
    # tolerated: a value at or below 1 is a share, anything larger is already francs.
    raw3a = p.pillar3a_contribution
    p3a = raw3a * gross if 0.0 < raw3a <= 1.0 else raw3a
    p3a = min(p3a, p.pillar3a_cap)

    # Mortgage interest is deductible, and so is the 3a contribution.
    deductions = interest + p3a
    taxable_joint = max(0.0, gross + partner + rent + company + other - deductions)
    taxable_alone = max(0.0, gross + rent + company + other - deductions)
    tax_joint = income_tax(taxable_joint, p)
    single = replace(p, tax_split_factor=1.0)
    tax_separate = income_tax(taxable_alone, single) + (income_tax(partner, single) if partner else 0.0)
    unmarried = bool(p.has_partner) and float(p.tax_split_factor or 1.0) == 1.0 and partner > 0
    tax_used = tax_separate if unmarried else tax_joint
    wtax = wealth_tax(w.net_worth, p)

    # Maintenance, in whichever direction it runs. Asked since the beginning and subtracted nowhere until
    # now, so a household paying it had a free cash flow overstated by the whole amount.
    alimony = _num(raw, "alimony_amount") or 0.0
    paying = str(raw.get("alimony_direction") or "").startswith("ich zahle")
    alimony_out = alimony if paying else 0.0
    alimony_in = alimony if (alimony and not paying) else 0.0

    # **What LEAVES the household, as against what it relocates.** Amortisation and the pillar-3a
    # contribution are destinations for saving, not expenses: the money is still the household's. Counting
    # them here would make the same franc an outflow or an investment depending only on where it was sent.
    income_both = gross + rent + company + other + partner + alimony_in
    income_alone = gross + rent + company + other + alimony_in
    outflows = wtax + interest + spending + alimony_out
    free_both = income_both - tax_used - outflows
    free_alone = income_alone - income_tax(taxable_alone, single) - outflows

    # Saving that already has a destination. **Indirect amortisation IS the pillar-3a payment** -- the
    # interview says so where it emits them, "dieselbe Zahlung wie der 3a-Beitrag, also nur einmal zu
    # zaehlen" -- so the two are one payment reported under two names and the larger is taken rather than
    # the sum. Direct amortisation is a separate payment and adds.
    committed = amort_direct + max(amort_indirect, p3a)

    stated = _num(raw, "savings")
    marginal = ((income_tax(taxable_alone, single)
                 - income_tax(max(0.0, taxable_alone - 10_000.0), single)) / 10_000.0
                if taxable_alone else None)
    return {
        "gross": gross,
        "partner_income": partner or None,
        "rent_net": rent,
        "company_income": company or None,
        "other_income": other or None,
        "income_tax": tax_used,
        "income_tax_joint_base": tax_joint,
        "income_tax_separate": tax_separate,
        "tax_overstatement": (tax_joint - tax_separate) if unmarried else None,
        "unmarried_correction_applied": unmarried,
        "wealth_tax": wtax,
        "wealth_tax_rate": p.wealth_tax_rate,
        "taxable": taxable_alone if unmarried else taxable_joint,
        "split_factor": float(p.tax_split_factor or 1.0),
        "marginal_rate": marginal,
        "mortgage_interest": interest,
        "mortgage_rate": p.i,
        # Whether the rate is the household's or the model's. The figure alone cannot say, and a report that
        # quotes an assumed rate as a fact is wrong about the most sensitive number in the cash flow.
        "mortgage_rate_is_stated": (params_block.get("mortgage_rate") is not None
                                    or raw.get("mortgage_rate") is not None),
        "spending": spending,
        "amortisation_direct": amort_direct or None,
        "amortisation_indirect": amort_indirect or None,
        "pillar3a_contribution": p3a or None,
        "pillar3a_cap": p.pillar3a_cap,
        "alimony_paid": alimony_out or None,
        "alimony_received": alimony_in or None,
        "free": free_both,
        "free_subject_alone": free_alone if partner else None,
        #: Saving that already has a destination, and what is left without one. `free` is what could be
        #: directed; `committed` is what already is; `undirected` is the difference. The stated saving is a
        #: cross-check against `free`, not the definition of it -- which is the change of 21 August 2026.
        "committed": committed,
        "committed_amortisation": amort_direct or None,
        "committed_pillar3a": p3a or None,
        "stated_saving": stated,
        "undirected": free_both - committed,
        #: The client's own figure, kept only to be compared. None where they did not give one, which is now
        #: the normal case rather than a gap.
        "stated_vs_free": (stated - free_both) if stated is not None else None,
    }


def health(submission: dict, p: Params, stop_age: float | None = None) -> dict:
    """The decay rate at the household's hours, and the trajectory to its own horizon.

    A rate on its own means nothing to a reader. Two paths to their own horizon, with the endpoint converted
    into a share of earning power, turns a coefficient into a sentence a person can act on.
    """
    raw = submission.get("raw") or {}
    hours = _num(raw, "hours_per_week")
    H0 = float((submission.get("state") or {}).get("H") or 0.0)
    threshold = p.tau_Y_star * 100.0
    base_rate = delta_H(p.tau_Y_star, p)
    ladder = [{"hours": h, "decay": delta_H(h / 100.0, p),
               "multiple": delta_H(h / 100.0, p) / base_rate}
              for h in sorted(set(HOURS_LADDER) | ({hours} if hours else set()))]
    if hours is None:
        return {"hours": None, "threshold_hours": threshold, "H0": H0 or None, "ladder": ladder,
                "why_absent": "Keine Wochenstunden erfasst: der Verlauf ist nicht berechenbar."}

    d_own = delta_H(hours / 100.0, p)
    d_base = delta_H(min(hours, threshold) / 100.0, p)
    age = float((submission.get("state") or {}).get("age") or 0.0)
    horizon = max(1.0, (stop_age if stop_age is not None else p.ahv_age) - age)

    def path(rate: float) -> list[float]:
        h, out = H0, [H0]
        for _ in range(int(round(horizon))):
            h = max(0.0, h - rate * h)
            out.append(h)
        return out

    own, base = path(d_own), path(d_base)
    return {
        "hours": hours,
        "hours_is_fulltime": _str(raw, "hours_is_fulltime") or None,
        "threshold_hours": threshold,
        "eta": p.eta,
        "delta_H0": p.delta_H0,
        "c": p.c,
        "H0": H0,
        "decay_own": d_own,
        "decay_at_threshold": d_base,
        "multiple": (d_own / d_base) if d_base else None,
        "horizon_years": horizon,
        "path_own": own,
        "path_at_threshold": base,
        "endpoint_own": own[-1],
        "endpoint_at_threshold": base[-1],
        # Earning power scales with H ** c and c = 1.0, so a health ratio IS an earning-power ratio. Naming the
        # exponent is what makes that step legible rather than asserted.
        "earning_power_ratio": (own[-1] / base[-1]) if base[-1] else None,
        "ladder": ladder,
    }


def children(submission: dict, p: Params) -> dict | None:
    """The child cost the engine actually charges, with the three properties that must travel with it."""
    if not p.child_ages:
        return None
    young, older = child_cost_level(p)
    age = float((submission.get("state") or {}).get("age") or 0.0)
    path, a = [], age
    while a < p.ahv_age:
        c = child_costs(a, p)
        if c <= 1.0 and path:
            break
        path.append({"age": a, "cost": c})
        a += 1.0
    return {
        "ages": [float(x) for x in p.child_ages],
        "reference_age": p.child_reference_age,
        "level_young": young,
        "level_older": older,
        "stated_total": p.child_costs_stated,
        "end_age": p.child_cost_end_age,
        "split_age": p.child_cost_age_split,
        "is_couple": p.child_household_is_couple,
        "cost_now": child_costs(age, p),
        "path": path,
        "total_remaining": sum(x["cost"] for x in path),
        "uprating": p.child_cost_uprating,
        "source": ("BFS / Büro BASS, Kinderkosten in der Schweiz, 2009, Tab. 11 und 12. "
                   "Preisbasis 2000–2005; kein Indexfaktor ist belegt, deshalb Faktor 1,0."),
        "caveats": [
            "Nur direkter Konsum: Krankenkassenprämien und bezahlte Kinderbetreuung sind nicht "
            "enthalten. Die Zahl unterschätzt also, am stärksten bei kleinen Kindern.",
            "Die Altersaufteilung ist nur für Paare mit höchstens zwei Kindern geschätzt.",
        ],
    }


def bridge(submission: dict, p: Params, f65: dict, cf: dict, stop_age: float | None) -> dict | None:
    """The span between stopping and 65, priced. The most under-estimated part of an early-retirement plan."""
    if stop_age is None or stop_age >= p.ahv_age:
        return None
    w = _wealth(submission)
    age = float((submission.get("state") or {}).get("age") or 0.0)
    years = p.ahv_age - stop_age
    spending = p.G
    interest = cf["mortgage_interest"]
    rent = cf["rent_net"]

    # Pillar 2 is gated at 65 and pillar 3a at 60, so what funds the bridge is liquid wealth plus whatever the
    # 3a has become by the stop age -- and the latter only if the stop is at or after 60.
    saving = max(0.0, cf["free"])
    liquid_at_stop = w.W_L + saving * max(0.0, stop_age - age)
    p3a_at_stop = (w.W_3a * (1.0 + p.pillar3a_interest) ** max(0.0, stop_age - age)
                   if stop_age >= p.pillar3a_age else 0.0)
    available = liquid_at_stop + p3a_at_stop
    need = (spending + interest - rent) * years

    # The permanent cost: contributions stop early, so the capital at 65 is smaller. Expressed as an annual
    # pension difference for life, which is far more legible than a capital shortfall.
    full = income_from_65(submission, p, stop_age=None)
    return {
        "stop_age": stop_age,
        "years": years,
        "spending": spending,
        "mortgage_interest": interest,
        "rent_offset": rent,
        "need": need,
        "need_without_rent": (spending + interest) * years,
        "liquid_today": w.W_L,
        "liquid_at_stop": liquid_at_stop,
        "saving_assumed": saving,
        "pillar3a_at_stop": p3a_at_stop,
        "pillar3a_age": p.pillar3a_age,
        "available": available,
        "shortfall": max(0.0, need - available),
        "pillar2_gated_at": p.pension_age,
        "ahv_gated_at": p.ahv_age,
        "pension_full": full["pillar2_annuity"],
        "pension_early": f65["pillar2_annuity"],
        "permanent_pension_cost": full["pillar2_annuity"] - f65["pillar2_annuity"],
        "permanent_note": ("Die Beiträge enden früher, also ist das Kapital mit 65 kleiner. "
                           "Der Unterschied ist eine Rentendifferenz auf Lebenszeit."),
    }


def _fv(pv: float, pmt: float, r: float, n: float) -> float:
    if abs(r) < 1e-12:
        return pv + pmt * n
    return pv * (1.0 + r) ** n + pmt * (((1.0 + r) ** n - 1.0) / r)


def required_return(submission: dict, target: float, years: float,
                    liquid: float, saving: float | None) -> dict:
    """The rate that makes the plan work, at the stated saving rate and above it.

    **This reframes almost every case.** Where the stated rate implied an impossible return, raising the saving
    rate brought the requirement to something ordinary. That converts "your goal is unreachable" into "your goal
    is not a returns problem", which is both truer and actionable.
    """
    raw = submission.get("raw") or {}
    expected = _pct(raw, "expected_return_pct")

    #: The floor of the bracket. A requirement that is met at a NEGATIVE return is met without the portfolio
    #: doing anything, and printing "-50 %" as the required return would be arithmetically true and completely
    #: misleading. Below this floor the rung reports `covered` instead of a rate.
    floor = -0.20

    def solve(pmt: float) -> tuple[float | None, str]:
        """The rate, and how the bracket closed. `('covered'|'unreachable'|'ok')`."""
        if target <= 0:
            return None, "covered"
        lo, hi = floor, 1.00
        if _fv(liquid, pmt, hi, years) < target:
            return None, "unreachable"
        if _fv(liquid, pmt, lo, years) >= target:
            return None, "covered"
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _fv(liquid, pmt, mid, years) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi), "ok"

    # The ladder starts at what the household actually frees and asks what a higher saving rate would do.
    # Above 1.0 that means spending less, which is why the levers section prices it rather than this table.
    base = saving if saving is not None and saving > 0 else 0.0
    rungs = []
    for m in SAVING_MULTIPLES:
        rate, how = solve(base * m)
        rungs.append({"saving": base * m, "multiple": m, "rate": rate, "outcome": how})
    stated = rungs[0]["rate"]
    return {
        "target": target,
        "years": years,
        "liquid_today": liquid,
        "stated_saving": saving,
        "rungs": rungs,
        "expected_return": expected,
        "loss_tolerance": _pct(raw, "max_loss_pct"),
        "crisis_behaviour": _str(raw, "crisis_behaviour") or None,
        "exceeds_expectation": bool(stated is not None and expected is not None and stated > expected),
        "unreachable_at_stated": rungs[0]["outcome"] == "unreachable",
        "covered_without_return": rungs[0]["outcome"] == "covered",
        "floor": floor,
        "solved_by_saving": next((r for r in rungs[1:]
                                  if r["outcome"] == "covered"
                                  or (r["rate"] is not None and expected is not None
                                      and r["rate"] <= expected)), None),
    }


def levers(submission: dict, p: Params, cf: dict, hp: dict) -> list[dict]:
    """Every lever the intake supports, in francs a year, largest first.

    The ranking is the value of the section. A client asked to choose between four things they cannot compare
    will choose by feeling; these are comparable because they are francs.

    **But they are not all the same kind of franc, and the `unit` field is what keeps that honest.** The
    surplus, the tax effect and the AHV entitlement are francs a year, recurring. The hours lever is earning
    power at the END of the horizon, valued on today's gross income -- a stock effect, and printing it in the
    same column without a label would overstate it by the whole compounding. Levers whose effect is a rate
    rather than an amount carry `rate` and no amount, and sort last rather than as zero.
    """
    w = _wealth(submission)
    raw = submission.get("raw") or {}
    out: list[dict] = []

    if cf.get("undirected") is not None and cf["undirected"] > 0:
        out.append({"kind": "surplus", "name": "Den ungerichteten Überschuss richten",
                    "amount": cf["undirected"], "unit": "chf_per_year",
                    "unit_label": "CHF pro Jahr, wiederkehrend",
                    "note": (f"Frei nach allem Genannten {_fmt(cf['free'])}, davon gerichtet "
                             f"{_fmt(cf['stated_saving'])}. Die Differenz ist heute keiner Verwendung "
                             f"zugeordnet.")})

    room = p.pillar3a_cap - (cf.get("pillar3a_contribution") or 0.0)
    if room > 0 and (cf.get("marginal_rate") or 0.0) > 0:
        out.append({"kind": "pillar3a", "name": "Säule 3a ausschöpfen",
                    "amount": room * cf["marginal_rate"], "unit": "chf_per_year",
                    "unit_label": "CHF pro Jahr, wiederkehrend",
                    "note": (f"Einzahlungsraum {_fmt(room)} bei einem Grenzsteuersatz von "
                             f"{_p(cf['marginal_rate'], 1)}. Der Betrag ist die Steuerwirkung "
                             f"pro Jahr, nicht die Einzahlung.")})

    if hp.get("hours") and hp["hours"] > hp["threshold_hours"] and hp.get("earning_power_ratio"):
        lost = 1.0 - hp["earning_power_ratio"]
        if lost > 0 and cf.get("gross"):
            out.append({"kind": "hours", "name": "Stunden auf die Schwelle zurück",
                        "amount": lost * cf["gross"], "unit": "chf_at_horizon",
                        "unit_label": f"CHF Ertragskraft am Horizont ({hp['horizon_years']:.0f} Jahre), "
                                      f"bewertet auf dem heutigen Bruttoeinkommen",
                        "note": (f"{hp['hours']:.0f} h gegen {hp['threshold_hours']:.0f} h: am Ende "
                                 f"des Horizonts {_p(hp['earning_power_ratio'], 0)} der Ertragskraft "
                                 f"gegenüber dem Verlauf an der Schwelle, bewertet auf dem heutigen "
                                 f"Bruttoeinkommen.")})

    if p.ahv_record_share < 1.0:
        per_year = p.ahv_full_single / AHV_FULL_RECORD_YEARS
        missing = round((1.0 - p.ahv_record_share) * AHV_FULL_RECORD_YEARS)
        out.append({"kind": "ahv", "name": "AHV-Beitragslücken klären",
                    "amount": missing * per_year, "unit": "chf_per_year",
                    "unit_label": "CHF Rente pro Jahr, dauerhaft",
                    "note": (f"{missing} fehlende Jahre à rund {_fmt(per_year)} Rente, dauerhaft. "
                             f"Höchstens die letzten fünf Jahre sind nachzahlbar, und das ist eine "
                             f"Frage an die Ausgleichskasse, nicht an das Modell.")})

    if w.D > 0 and cf.get("marginal_rate"):
        after = p.i * (1.0 - cf["marginal_rate"])
        out.append({"kind": "amortisation", "name": "Hypothek amortisieren", "amount": None,
                    "unit": "rate", "unit_label": "Rendite nach Steuern", "rate": after,
                    "note": (f"Zins {_p(p.i, 1)}, nach Steuern {_p(after, 2)}: der Zins "
                             f"war abzugsfähig, und wer ihn tilgt, verliert den Abzug mit.")})

    # --- Kosten senken ---------------------------------------------------------------------------------
    #
    # The one lever with no model in it and the largest effect on most households: a franc not spent is a
    # franc free, and unlike a franc earned it carries no tax. Ten per cent is the step because it is the
    # smallest reduction a household can usually name without a budget in front of it.
    spending = cf.get("spending") or 0.0
    if spending > 0:
        out.append({"kind": "spending", "name": "Lebenskosten um 10 % senken",
                    "amount": 0.10 * spending, "unit": "chf_per_year",
                    "unit_label": "CHF pro Jahr, wiederkehrend",
                    "note": (f"Von {_fmt(spending)} auf {_fmt(0.9 * spending)}. Ein nicht ausgegebener "
                             f"Franken ist steuerfrei frei — um denselben Betrag zu verdienen, bräuchte es "
                             f"bei einem Grenzsatz von "
                             f"{_p(cf.get('marginal_rate')) if cf.get('marginal_rate') else 'Ihrem Satz'} "
                             f"deutlich mehr Bruttoeinkommen.")})

    # --- Mehr Erholung ---------------------------------------------------------------------------------
    #
    # The health equation runs both ways: overwork accelerates the decay and rest opposes it. The hours lever
    # above prices stopping the damage; this prices the repair, which is a different control (`tau_H`) and a
    # different question for the client.
    rest_now = _num(raw, "rest_hours")
    if hp.get("H0") and hp.get("horizon_years") and cf.get("gross"):
        tau_h_now = p.tau_H_ref if rest_now is None else max(0.02, min(0.35, rest_now / 100.0))
        tau_h_more = min(0.35, tau_h_now * 2.0)
        tau_y = (hp.get("hours") or (p.tau_Y_star * 100.0)) / 100.0

        def _health_at(tau_h: float) -> float:
            h = float(hp["H0"])
            for _ in range(int(round(hp["horizon_years"]))):
                dh = (p.alpha_H * rest_effect(tau_h, p) * (1.0 - h / p.K_H)
                      - delta_H(tau_y, p) * h)
                h = max(0.0, min(p.K_H, h + dh))
            return h

        h_now, h_more = _health_at(tau_h_now), _health_at(tau_h_more)
        if h_more > h_now + 1e-6:
            gain = (h_more / h_now - 1.0) if h_now > 0 else 0.0
            out.append({"kind": "rest", "name": "Erholungszeit verdoppeln",
                        "amount": gain * cf["gross"], "unit": "chf_at_horizon",
                        "unit_label": f"CHF Ertragskraft am Horizont "
                                      f"({hp['horizon_years']:.0f} Jahre)",
                        "note": (f"Von {tau_h_now * 100:.0f} auf {tau_h_more * 100:.0f} Wochenstunden "
                                 f"Erholung: Gesundheit am Horizont {_d(h_more)} statt {_d(h_now)}, also "
                                 f"{_p(gain)} mehr Ertragskraft. Die Gesundheit erholt sich mit "
                                 f"abnehmendem Ertrag — viermal so viel Ruhe bringt doppelt so viel "
                                 f"Erholung, nicht viermal.")})

    # --- Weiterbildung ---------------------------------------------------------------------------------
    #
    # Time and money both raise expertise, and expertise raises earning power. Priced at the hours and budget
    # the household itself named, so the figure answers "what would MY plan be worth" rather than a generic
    # one. Skipped where neither was given: an education lever costed on invented inputs is a made-up number.
    edu_hours = education_hours(raw)
    edu_budget = _num(raw, "education_budget")
    E0 = float((submission.get("state") or {}).get("E") or 0.0)
    if E0 > 0 and (edu_hours or edu_budget) and cf.get("gross") and hp.get("horizon_years"):
        years = max(1.0, min(5.0, hp["horizon_years"]))
        N0 = float((submission.get("state") or {}).get("N") or 0.5)
        age = float((submission.get("state") or {}).get("age") or 45.0)

        # **Against NOT educating, not against standing still.** `beta_E * E` is autonomous growth --
        # expertise compounds at 15 % a year whether or not anybody enrols in anything -- so comparing the
        # educated path to today's earning power credits the education with growth that was going to happen
        # anyway: measured at 191 968 on a real household, against a true effect a fraction of that.
        e_with = expertise_after(E0, p, years=years, learning_hours=edu_hours or 0.0,
                                 budget=edu_budget or 0.0)
        e_without = expertise_after(E0, p, years=years, learning_hours=0.0, budget=0.0)
        with_edu = earning_power(e_with, N0, age + years, p)
        without_edu = earning_power(e_without, N0, age + years, p)
        if with_edu > without_edu + 1.0:
            out.append({"kind": "education", "name": "Ihre geplante Weiterbildung",
                        "amount": with_edu - without_edu, "unit": "chf_at_horizon",
                        "unit_label": f"CHF Ertragskraft nach {years:.0f} Jahren, gegenüber ohne",
                        "note": (f"{(edu_hours or 0):.0f} Lernstunden pro Woche und "
                                 f"{_fmt(edu_budget)} Budget pro Jahr heben die Expertise in "
                                 f"{years:.0f} Jahren auf {_d(e_with)} statt {_d(e_without)}. Der Betrag "
                                 f"ist die Differenz zwischen beiden Wegen, nicht der Zuwachs gegenüber "
                                 f"heute: ein Teil davon wächst ohnehin. Gemessen wird die "
                                 f"<em>Ertragskraft</em> bei voller Arbeitszeit — für diesen Haushalt "
                                 f"{_fmt(without_edu)} ohne Weiterbildung, gegen ein heutiges "
                                 f"Bruttoeinkommen von {_fmt(cf.get('gross'))}.")})

    # **The network, priced the same way as the education and against the same counterfactual.**
    #
    # It was missing from this list while `app/paths` priced it, so a section headed "nach Wirkung geordnet"
    # ordered an incomplete set. Both are time the household chooses to spend and both raise earning power
    # through the same function; leaving one out makes the other look like the only thing that can be done.
    #
    # Valued at the model's own knee -- `network_effect` says anything past ten hours a week buys almost
    # nothing -- rather than at a number chosen to make the lever look large.
    N0 = float((submission.get("state") or {}).get("N") or 0.0)
    age_now = float((submission.get("state") or {}).get("age") or 0.0)
    if N0 > 0 and age_now and hp.get("horizon_years") and cf.get("gross"):
        years = max(1.0, min(5.0, hp["horizon_years"]))
        E_flat = float((submission.get("state") or {}).get("E") or 0.0)
        n_with = network_after(N0, p, years=years, hours=NETWORK_KNEE_HOURS)
        n_without = network_after(N0, p, years=years, hours=0.0)
        if n_with > n_without:
            with_net = earning_power(E_flat, n_with, age_now + years, p)
            without_net = earning_power(E_flat, n_without, age_now + years, p)
            if with_net > without_net + 1.0:
                out.append({"kind": "network", "name": "Netzwerk und Sichtbarkeit ausbauen",
                            "amount": with_net - without_net, "unit": "chf_at_horizon",
                            "unit_label": f"CHF Ertragskraft nach {years:.0f} Jahren, gegenüber ohne",
                            "note": (f"{NETWORK_KNEE_HOURS:.0f} Stunden pro Woche für Kontakte und "
                                     f"Sichtbarkeit heben das Netzwerk in {years:.0f} Jahren von "
                                     f"{_d(N0)} auf {_d(n_with)} statt {_d(n_without)}. Der Betrag ist "
                                     f"die Differenz zwischen beiden Wegen. Mehr als diese Stunden "
                                     f"bringt nach diesem Modell fast nichts — die Kurve hat dort ihren "
                                     f"Knick. Gemessen wird die <em>Ertragskraft</em> bei voller "
                                     f"Arbeitszeit, gegen ein heutiges Bruttoeinkommen von "
                                     f"{_fmt(cf.get('gross'))}.")})

    # Recurring francs first, then the stock effect, then rates. Sorting the three kinds into one list by
    # magnitude would put a horizon figure above a yearly one purely because it is bigger, which is the
    # comparison the `unit` field exists to prevent.
    order = {"chf_per_year": 0, "chf_at_horizon": 1, "rate": 2}
    return sorted(out, key=lambda d: (order.get(d.get("unit"), 9), -(d.get("amount") or 0.0)))


# --- assembling the whole ------------------------------------------------------------------------------

def assemble(submission: dict, facts: dict | None = None, *, with_asks: bool = True) -> dict:
    """Everything a dossier states, computed from one submission.

    `facts` is the engine's `ReportFacts` as a dict, or None. **None is a supported outcome, not a degraded
    one.** The optimiser answers exactly one question -- whether the stated goal holds at the stated confidence,
    and what this period's action is -- and it needs tens of minutes to do it. Every other section is arithmetic
    on the intake. So a household whose solve times out still gets eleven of twelve sections, and section five
    says which question is unanswered and why, instead of the report not existing.
    """
    p = _params_from(submission)
    raw = submission.get("raw") or {}
    stop = _stop_age(submission, p)

    b = balance(submission, p)
    f65 = income_from_65(submission, p, stop_age=stop)
    cf = cash_flow(submission, p)
    hp = health(submission, p, stop_age=stop)
    kids = children(submission, p)
    gp = gap_and_capital(p, f65["total"])
    br = bridge(submission, p, f65, cf, stop)

    # The required return is solved against a CAPITAL target, and a goal's `amount_chf` is only sometimes one.
    #
    # **This distinction is the whole correctness of the section.** `fi` and `retirement` state an amount PER
    # YEAR -- the spend the household wants covered -- while `home` and `company` state a capital sum. Feeding
    # a retirement goal's 50 000 into the solve as a capital target asks what return turns 130 000 into 50 000
    # over twenty years, which is met by losing money and reported as a negative rate. Measured on the Schwyz
    # case before the fix: -50 %, printed as if it meant something.
    age = float((submission.get("state") or {}).get("age") or 0.0)
    collected = (submission.get("meta") or {}).get("collected") or ""
    year_now = int(collected[:4]) if collected[:4].isdigit() else None
    capital_goal = next((g for g in (submission.get("goals") or [])
                         if g.get("kind") in _CAPITAL_GOAL_KINDS
                         and g.get("amount_chf") and g.get("target_year")), None)
    flow_goal = next((g for g in (submission.get("goals") or [])
                      if g.get("kind") in _FLOW_GOAL_KINDS and g.get("target_year")), None)
    # **Every stated goal the arithmetic did not use is recorded, with what it says and why.** The section
    # below solves for ONE target; a household may have stated more than one, and the ones it does not solve
    # for were previously dropped without a word. A goal named in the client's own hand, absent from his
    # report, is the failure this list exists to prevent.
    used = {id(g) for g in (capital_goal, flow_goal) if g is not None}
    deferred = []
    for g in (submission.get("goals") or []):
        if id(g) in used:
            continue
        kind = str(g.get("kind") or "")
        deferred.append({
            "kind": kind or None,
            "description": g.get("description") or None,
            "target_year": g.get("target_year"),
            "amount_chf": g.get("amount_chf"),
            "reason": _DEFERRAL_REASONS.get(
                kind, "Für diese Zielart hat das Modell keine eigene Rechnung."),
        })

    if capital_goal and year_now:
        target = float(capital_goal["amount_chf"])
        years = max(1.0, float(capital_goal["target_year"]) - year_now)
        target_source = (f"Ziel {capital_goal.get('kind')}: {_fmt(target)} Kapital bis "
                         f"{capital_goal['target_year']}")
    else:
        # The capital the gap implies at the model's own withdrawal rate. Zero when the flows at 65 already
        # cover the target spend, and `required_return` reports that as covered rather than as a rate.
        target = gp["capital"][f"{p.swr:.3f}"]
        if flow_goal and year_now:
            years = max(1.0, float(flow_goal["target_year"]) - year_now)
            deadline = f"bis {flow_goal['target_year']}"
            # lbsim (LBSIM-08): the capital in the francs of the goal's date; a draft submission has no inflation.
            pi = float((submission.get("lbsim") or {}).get("inflation") or 0.0)
            if pi:
                target = target * (1.0 + pi) ** years
        else:
            years = max(1.0, p.ahv_age - age)
            deadline = f"bis Alter {p.ahv_age:.0f}"
        target_source = (f"Kapitalbedarf aus der Lücke von {_fmt(gp['gap'])} pro Jahr bei "
                         f"{_p(p.swr, 1)} Entnahme, {deadline}")
    # **Solved at the COMPUTED free cash flow, not at the stated saving.** A household that states 30 000
    # while its own income and outgoings free 14 078 would otherwise get a required return computed on money
    # it does not have. The stated figure travels alongside as a cross-check, because the difference between
    # the two is a finding in its own right in both directions.
    saving_basis = cf["free"] if cf["free"] > 0 else 0.0
    rr = required_return(submission, target, years, b["liquid"], saving_basis)
    rr["saving_stated"] = cf["stated_saving"]
    rr["saving_computed"] = cf["free"]
    rr["saving_basis"] = "computed"
    rr["target_source"] = target_source
    # Attached to the section that states the target, because that is where a reader asks "and my other goal?"
    rr["goals_deferred"] = deferred

    q: dict[str, Any] = {
        "schema": SCHEMA,
        "submission_schema": submission.get("schema_version"),
        "collected": collected,
        "canton": _str(raw, "canton") or None,
        "age": age or None,
        "birth_year": _num(raw, "birth_year"),
        "main_question": _str(raw, "main_question") or None,
        "goals_text": _str(raw, "goals") or None,
        "goals_deferred": deferred,
        "stop_work_age": stop,
        # Carried through so the report can offer these back. `limits()` already read them off the
        # submission, which is why their absence here went unnoticed: the sentence about them was correct
        # and the section that would let a client answer them never rendered.
        "pending_fields": [str(x) for x in (submission.get("pending_fields") or [])],
        "balance": b,
        "income_65": f65,
        "gap": gp,
        "cash_flow": cf,
        "health": hp,
        "children": kids,
        "bridge": br,
        "required_return": rr,
        "plan": facts,
    }
    # **The paths run before the optimiser and without it.** For a household whose income is low because it
    # is in education, freezing today's salary for forty years asks the wrong question, and no portfolio can
    # answer it. At a return of zero this says what each path demands per year against what each path frees.
    # Imported here rather than at the top: `app.paths` imports this module for the education bands and the
    # conversion rate, and a top-level import in both directions is a cycle.
    # **The input check runs before the findings, and is reported separately from them.** A finding says
    # something true about a household; a plausibility check says two answers contradict each other, so the
    # figures below may describe nobody. Mixing the two would let a data error read as a result.
    from . import plausibility as _plausibility
    try:
        q["plausibility"] = _plausibility.evaluate(submission, p)
    except (KeyError, TypeError, ValueError) as exc:  # noqa: BLE001
        q["plausibility"] = {"schema": _plausibility.SCHEMA, "checks": [], "unchecked": [],
                             "impossible": 0, "unlikely": 0,
                             "error": f"{type(exc).__name__}: {exc}"}

    from . import paths as _paths
    try:
        q["paths"] = _paths.ledger(submission, p, stop_age=stop)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:  # noqa: BLE001
        q["paths"] = {"schema": _paths.SCHEMA, "paths": [], "assumptions": [],
                      "error": f"{type(exc).__name__}: {exc}"}
    # **The frontier: the smallest change that makes each goal hold, searched rather than illustrated.**
    # Run at zero and again at the household's own stated expectation, because those two answer different
    # questions and the second is the one a reader asks after seeing the first. Skipped during the asks
    # probes for the same reason the paths are: a sensitivity probe that re-ran a grid search per candidate
    # would cost minutes to measure a question nobody asked yet.
    if with_asks:
        from . import search as _search
        try:
            rates, _labels = _paths.return_rates(submission)
            q["search"] = {r_label["rate"]: _search.frontier(submission, p, rate=r)
                           for r, r_label in zip(rates, _labels)}
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:  # noqa: BLE001
            q["search"] = {"error": f"{type(exc).__name__}: {exc}"}
    q["levers"] = levers(submission, p, cf, hp)
    fired, unchecked = _findings.evaluate(q, p, raw)
    q["findings"] = fired
    q["findings_unchecked"] = unchecked
    q["schedule"] = _findings.schedule(fired)
    # **The gate, last: it reads what every other layer produced.** Which stage a household is in is not a
    # rendering preference -- it is a fact about whether the figures above rest on answers that can all be
    # true at once. Computed here so the renderer decides nothing.
    from . import workflow as _workflow
    try:
        q["gate"] = _workflow.open_items(q, submission)
    except (KeyError, TypeError, ValueError) as exc:  # noqa: BLE001
        q["gate"] = {"stage": "report", "blocking": [], "optional": [], "open_count": 0,
                     "optional_count": 0, "error": f"{type(exc).__name__}: {exc}"}
    q["assumptions"] = assumptions(p, submission, facts)
    q["limits"] = limits(submission, p, facts, stop)
    # **What to ask next, measured on this household rather than taken from a list.** Each candidate gap is
    # probed by recomputing the report at a plausible low and high and reading the spread in the figures the
    # client actually sees. `with_asks=False` on those inner calls is what stops this recursing once per probe.
    if with_asks:
        try:
            q["asks_ranked"] = _asks.rank(submission, p, assemble, base=q)
            q["asks_summary"] = _asks.summarise(q["asks_ranked"])
        except Exception as exc:  # noqa: BLE001 - a report without its questions is still a report
            q["asks_ranked"] = []
            q["asks_summary"] = {"open": 0, "measured": 0, "unmeasured": 0,
                                 "by_headline": {}, "largest": None}
            q["asks_error"] = f"{type(exc).__name__}: {exc}"
    return q


def _tax_source(submission: dict, what: str) -> str:
    """Where this household's tax rate came from: a cantonal calibration, or the national approximation.

    **Read rather than assumed, because the answer differs per household.** A canton in the table gets a
    measured factor and the report should say so with its vintage; a canton that is not gets the national
    curve and the report should say THAT, in the same place, rather than leaving a reader to guess which of
    the two they are holding.
    """
    name = str((submission.get("raw") or {}).get("canton") or "").strip()
    if not name:
        return "Modellparameter, eine glatte Näherung; kein Kanton erfasst"
    try:
        from ..model import canton as _canton  # noqa: PLC0415
        cf = _canton.factors_for(name)
    except Exception:  # noqa: BLE001 - a missing table is a degradation, not a failure of the report
        return "Modellparameter, eine glatte Näherung; keine kantonale Tabelle verfügbar"
    if not cf["calibrated"]:
        return f"Modellparameter, eine glatte Näherung; für {name} liegt kein Faktor vor"
    key = "income_factor" if what == "Einkommenssteuer" else "wealth_factor"
    return (f"auf {name} kalibriert, Faktor {cf[key]:.2f} auf den nationalen Näherungssatz "
            f"(gemessene Belastung im Hauptort, Stand {cf['as_of'][:4]})")


def assumptions(p: Params, submission: dict, facts: dict | None) -> list[dict]:
    """Every figure this report used that the household did not supply.

    A dossier that does not list these invites the reader to believe them measured. Each entry names the value,
    where it came from, and what would replace it.
    """
    raw = submission.get("raw") or {}
    out = [
        {"what": "Umwandlungssatz Pensionskasse", "field": None, "value": f"{_p(PILLAR2_CONVERSION_RATE, 2)}",
         "source": "erklärte Annahme, kein Modellparameter",
         "replaced_by": "ein Pensionskassenausweis"},
        {"what": "Verzinsung Pensionskassenguthaben", "field": None, "value": f"{_p(p.pension_interest, 2)}",
         "source": "Modellparameter pension_interest", "replaced_by": "der Ausweis der Kasse"},
        {"what": "Nettoertrag vermietete Liegenschaften", "field": None, "value": f"{_p(p.y_R, 1)}",
         "source": "Modellparameter y_R", "replaced_by": "die tatsächliche Nettorendite"},
        {"what": "Entnahmesatz", "field": None, "value": f"{_p(p.swr, 1)}",
         "source": "Modellparameter swr; daneben stehen "
                   + " und ".join(f"{_p(r, 1)}" for r in WITHDRAWAL_RATES),
         "replaced_by": "eine Entscheidung über die verlangte Sicherheit"},
        {"what": "Vermögenssteuersatz", "field": None, "value": f"{_p(p.wealth_tax_rate, 2)}",
         "source": _tax_source(submission, "Vermögenssteuer"),
         "replaced_by": "die effektive Veranlagung Ihrer Gemeinde"},
        {"what": "Einkommenssteuer", "field": None,
         "value": f"Höchstsatz {_p(p.tax_rate_max, 0)}, Skala {_fmt(p.tax_income_scale)}",
         "source": _tax_source(submission, "Einkommenssteuer"),
         # **Until 25 August 2026 this said the canton reaches no equation, and that was true.** The factors
         # are now measured per canton and applied in the converter, so the honest text depends on whether
         # THIS household's canton is in the table -- which `_tax_source` reads rather than assumes.
         "replaced_by": "die effektive Veranlagung Ihrer Gemeinde; der Faktor gilt für den Hauptort"},
    ]
    if raw.get("mortgage_rate") is None and (submission.get("state") or {}).get("D"):
        out.append({"what": "Hypothekarzins", "field": "mortgage_rate", "value": f"{_p(p.i, 1)}",
                    "source": "Modellparameter i, weil kein Satz erfasst wurde",
                    "replaced_by": "der Satz des Kreditvertrags"})
    if p.child_ages:
        out.append({"what": "Kinderkosten", "field": "child_costs",
                    "value": f"Preisbasis 2000–2005, Faktor {_d(p.child_cost_uprating, 1)}",
                    "source": "BFS / Büro BASS 2009, Tab. 11 und 12",
                    "replaced_by": "die tatsächlichen Kosten des Haushalts"})
    if facts:
        s = facts.get("engine_settings") or {}
        if s:
            out.append({"what": "Szenarien der Optimierung", "field": None,
                        "value": f"M_opt {s.get('M_opt')}, M_eval {s.get('M_eval')}, "
                                 f"Starts {s.get('n_starts')}, Seed {s.get('seed')}",
                        "source": "Voreinstellung der Engine",
                        "replaced_by": "eine bewusste Wahl bei mehr Rechenzeit"})
    return out


def limits(submission: dict, p: Params, facts: dict | None, stop: float | None) -> list[str]:
    """What this report cannot say. Written from what is absent, not from a fixed list.

    The known defects of the method are included, because a report that inherits a defect and does not name it
    passes it on as a result. `architecture/manual-gameplan.html` section 17 is their register.
    """
    raw = submission.get("raw") or {}
    out: list[str] = []
    if facts is None:
        out.append("Die Optimierung ist nicht gelaufen. Damit fehlt genau eine Aussage: ob das gestellte "
                   "Ziel bei der verlangten Sicherheit hält, und welche Handlung dieser Periode dazu "
                   "gehört. Jede andere Zahl dieses Berichts ist Arithmetik auf den Angaben und davon "
                   "unabhängig.")
    elif not facts.get("solver_converged", True):
        out.append("Der Solver ist nicht konvergiert. Ein nicht konvergierter Fehlbetrag ist gemessen "
                   "worden als um den Faktor vier falsch, deshalb steht hier keine Zahl aus der "
                   "Optimierung.")
    if stop is None and any(str(raw.get(k) or "") for k in ("goals", "work_plan")):
        out.append("Ohne erfasstes Ausstiegsalter ist die Brücke bis zur Referenzaltersgrenze nicht "
                   "gerechnet. Sie ist der am stärksten unterschätzte Teil einer "
                   "Frühpensionierung.")
    pend = submission.get("pending_fields") or []
    if pend:
        out.append(f"{len(pend)} Angabe(n) sind bewusst offen geblieben: {', '.join(map(str, pend))}. "
                   "Was daran hängt, ist entsprechend offen.")
    out.append("Die Rentendauer ist im Fragebogen an 65 gebunden: years_in_retirement wird als "
               "plan_until_age minus 65 gerechnet, auch wenn früher aufgehört werden soll. "
               "Für einen Ausstieg vor 65 ist die Spanne im Modell zu kurz.")
    if (submission.get("params") or {}).get("child_ages"):
        out.append("Die Kinderkosten stehen auf der Preisbasis 2000–2005. Kein Indexfaktor ist "
                   "belegt, also wird keiner angewendet. Die Zahl ist damit zu tief, und um wie viel, "
                   "ist nicht belegbar.")
    out.append("Nichts in diesem Bericht ist eine Empfehlung. Ein Befund ist Bildung; eine Empfehlung "
               "verlangt einen benannten Kurator und einen Entscheidungsnachweis.")
    return out


# --- the command line ----------------------------------------------------------------------------------
#
# JSON in, JSON out, on stdin and stdout, exactly like `app/befund.py`. This module runs inside the engine
# interpreter because that is where `Params` and `dynamics` live; the caller in `desktop/` reaches it by
# subprocess across the same seam every other tool in this repo uses.

def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Deterministic gameplan quantities and findings.")
    ap.add_argument("--in", dest="infile", help="submission JSON; default stdin")
    ap.add_argument("--facts", help="a ReportFacts JSON from app/befund, optional")
    args = ap.parse_args(argv)

    text = (open(args.infile, encoding="utf-8-sig").read() if args.infile else sys.stdin.read())
    submission = json.loads(text)
    facts = None
    if args.facts:
        loaded = json.loads(open(args.facts, encoding="utf-8-sig").read())
        # `app/befund` wraps the facts in an envelope; accept either shape.
        facts = loaded.get("facts", loaded) if isinstance(loaded, dict) else None

    out = assemble(submission, facts)
    sys.stdout.write(json.dumps(out, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
