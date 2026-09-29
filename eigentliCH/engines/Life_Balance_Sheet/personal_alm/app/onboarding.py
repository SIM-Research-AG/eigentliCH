"""Task P2: turn an `onb@0.1.x` onboarding submission into a `Case` the engine can run.

**Why this is a module and not three lines of `replace()`.** The schema's `params` block is not a `Params`
patch. It mixes four different kinds of thing, and only the first belongs in `param_overrides`:

    Params fields      G, swr, ahv_record_share, pension_contribution_rate, pillar3a_contribution,
                       has_partner, partner_income, partner_age_offset, partner_ahv_record_share,
                       ahv_couple_cap_multiple, tax_split_factor
    goal params        epsilon, years_in_retirement          -> GoalSpec, not Params
    controls           p_A                                    -> the optimiser CHOOSES this
    hints / mandate    tau_H_hint, max_loss_pct, expected_return_pct

Six of the seventeen keys are not `Params` fields at all, so `replace(Params(), **payload["params"])` raises —
which is the good failure. The bad one would be a converter that quietly filtered them out and returned a case
whose amortisation, confidence and mandate conditions had all been dropped without saying so.

**Nothing is silently dropped.** Every input this converter cannot express is returned in `Conversion.deferred`
with the reason, and every value it had to assume is returned in `Conversion.assumed`. A caller that ignores both
gets a runnable case; a caller that reports them tells the client what was and was not used. The three hand-built
dossiers were assembled by reading a submission and making these decisions in someone's head, which is precisely
what made them unauditable.

**`age` reaches the state.** `app/inputs.py` passed it only to `Case.age` and the persona string until 4 August
2026, so a client who typed 60 was modelled at 40 with every age-dependent term reading the wrong age (M76). The
same mistake is one line away here, so `_build_state` is the only place that constructs the state and it takes
`age` as a required argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields, replace
from datetime import date
from typing import Any

from ..cases import Case
from ..goals.spec import GoalSpec
from ..model.params import Params
from ..model.state import State

#: Versions this converter understands. **A 0.1.1 reader consuming a 0.1.0 payload is safe** — 0.1.0 simply has no
#: partner fields, and their absence correctly means "single household", which is what the defaults encode. The
#: hazard the schema warns about is the other direction: a reader pinned to 0.1.0 consuming 0.1.1 would drop
#: `has_partner` and `tax_split_factor` and model a couple as one person. Anything else is refused rather than
#: guessed, as the schema requires.
SUPPORTED_VERSIONS: frozenset[str] = frozenset({"onb@0.1.0", "onb@0.1.1", "onb@0.1.2",
                                                 "onb@0.1.3"})

#: `params` keys that arrive as JSON arrays and must reach `Params` as tuples. `Params` is a dataclass whose
#: defaults are tuples, and a list assigned over one is not merely untidy: `replace()` accepts it silently, and
#: the field then differs in type from the default in a way nothing checks. Converting here keeps the type a
#: property of the parameter rather than of the transport that happened to carry it.
_TUPLE_PARAMS: frozenset[str] = frozenset({"child_ages"})

#: Schema keys that ARE `Params` fields under a different name. **`mortgage_rate` is the one that matters and
#: its absence was a live defect.** `onb@0.1.3` asks for the mortgage's actual rate and the question's own help
#: text says the answer "ersetzt in Ihrer Rechnung die Annahme von 2 %" -- and nothing consumed it, so every
#: household was modelled at `Params.i` whatever they answered. That is the same class of fault as H1 (a
#: parameter with no question) read the other way round: a question with no mapping is inert, and neither shows
#: up as an error. The schema uses the client's word and the engine uses its own, so the mapping is stated here
#: rather than either side renaming itself.
_PARAM_ALIASES: dict[str, str] = {"mortgage_rate": "i"}

#: Schema goal kinds the engine has a `GoalSpec` for. The other four are real client intentions that this model
#: expresses somewhere OTHER than as a goal, so converting them would misrepresent them:
#:
#:   holiday_home  a CONSUMPTION good, not an investment goal. It belongs in `W_hol` (which carries a negative net
#:                 yield) and in the spending path. The author was explicit: the question is whether the household
#:                 can afford it, not whether it "achieves" it.
#:   education     enters through the controls `tau_E` and `m_E`, which the optimiser chooses. A goal would double
#:                 count it.
#:   legacy        enters the objective as `bequest_weight`, not as a dated constraint.
#:   other         unresolved by definition.
_ENGINE_GOAL_KINDS: frozenset[str] = frozenset({"fi", "retirement", "home", "company"})

_NON_GOAL_KIND_REASONS: dict[str, str] = {
    "holiday_home": "a consumption good: belongs in W_hol and the spending path, not as a goal the optimiser funds",
    "education": "enters through the controls tau_E and m_E, which the optimiser chooses; a goal would double-count",
    "legacy": "enters the objective as bequest_weight, not as a dated constraint",
    "other": "unresolved at intake; needs a human pass before it can be a goal",
}

#: Defaults for state components the schema marks optional. Each is a modelling assumption, so each is REPORTED
#: in `Conversion.assumed` rather than applied quietly. The capitals are the ones worth arguing about: 0.5 is
#: mid-scale on a 0..2 expertise range and 0.5 on the network scale, chosen because they bias neither toward "this
#: household has nothing" nor toward "this household is exceptional".
_STATE_DEFAULTS: dict[str, float] = {"E": 0.5, "N": 0.5, "H": 0.8}


@dataclass
class Conversion:
    """A `Case` plus an honest account of what the conversion could not do."""

    case: Case
    #: Inputs the engine cannot express, as (what, why). Report these to the client: they are the difference
    #: between "we modelled your situation" and "we modelled the part of it this engine covers".
    deferred: list[tuple[str, str]] = field(default_factory=list)
    #: Values not supplied and therefore assumed, as (field, value, why).
    assumed: list[tuple[str, Any, str]] = field(default_factory=list)


class SubmissionError(ValueError):
    """A submission this converter refuses. Refusing beats guessing — the schema says so explicitly."""


def _params_field_names() -> frozenset[str]:
    return frozenset(f.name for f in dataclass_fields(Params))


def _build_state(state: dict, *, age: float, assumed: list) -> State:
    """The ONLY place a state is constructed here, and `age` is required rather than defaulted.

    `State.individual` defaults `age` to 40.0 so that step 1's state addition was provably a no-op. That default
    outlived its purpose and became the answer for every case in the repo (M76). Making `age` a required keyword
    of this function is the cheapest way to ensure this path can never repeat it.
    """
    caps = {}
    for k, default in _STATE_DEFAULTS.items():
        v = state.get(k)
        if v is None:
            caps[k] = default
            assumed.append((k, default, "not collected; mid-scale default that biases neither way"))
        else:
            caps[k] = float(v)
    return State.individual(
        W_L=float(state["W_L"]), W_R=float(state["W_R"]), D=float(state["D"]),
        E=caps["E"], N=caps["N"], H=caps["H"], age=age,
        W_res=float(state["W_res"]), W_hol=float(state["W_hol"]),
        W_P=float(state["W_P"]), W_3a=float(state["W_3a"]),
    )


def _horizon_years(target_year: int | None, collected: str | None) -> float | None:
    """Years from collection to the goal's target year. `None` if it cannot be determined."""
    if target_year is None:
        return None
    base = None
    if collected:
        try:
            base = date.fromisoformat(collected).year
        except ValueError:
            base = None
    if base is None:
        base = date.today().year
    return float(target_year - base)


def _goal_params(kind: str, g: dict, params: dict, assumed: list) -> dict:
    """Per-kind goal parameters, drawn from the goal and from the shared `params` block."""
    amount = g.get("amount_chf")
    if kind == "fi":
        out = {"G": float(params["G"]), "swr": float(params.get("swr") or Params().swr)}
        # `h_res` is the share of the residence treated as drawable. Nothing in the schema asks it, and the safe
        # reading is 0.0 -- a home someone lives in is not a withdrawal source. Counting it would inflate
        # drawable wealth by the value of the roof over their head.
        out["h_res"] = 0.0
        assumed.append(("h_res", 0.0, "not collected; the residence is walled off from drawable wealth"))
        if params.get("swr") is None:
            assumed.append(("swr", out["swr"], "not collected; engine default"))
        return out
    if kind == "retirement":
        years = params.get("years_in_retirement")
        if years is None:
            years = 25
            assumed.append(("years_in_retirement", 25, "not collected; the figure the first dossier assumed"))
        return {"G_ret": float(params["G"]), "years_in_retirement": float(years), "r_disc": 0.02}
    if kind == "home":
        if amount is None:
            raise SubmissionError("a home goal needs amount_chf (the purchase price)")
        return {"price": float(amount)}
    if kind == "company":
        if amount is None:
            raise SubmissionError("a company goal needs amount_chf (the buffer to reach)")
        # N_min/E_min are conditions on network and expertise at the deadline. Nothing collects them, and the
        # engine's own worked case uses 0.7 for both.
        assumed.append(("N_min/E_min", 0.7, "not collected; the value the engine's company case uses"))
        return {"B_buffer": float(amount), "N_min": 0.7, "E_min": 0.7}
    raise SubmissionError(f"unhandled engine goal kind {kind!r}")


def case_from_submission(payload: dict, *, name: str | None = None) -> Conversion:
    """Convert an `onb@0.1.x` submission into a runnable `Case`.

    Raises `SubmissionError` on a version it does not recognise, on a missing required block, or on a goal that
    the engine supports but the payload underspecifies. Returns deferred inputs and assumed values rather than
    hiding either.
    """
    version = payload.get("schema_version")
    if version not in SUPPORTED_VERSIONS:
        raise SubmissionError(
            f"unrecognised schema_version {version!r}; this converter reads {sorted(SUPPORTED_VERSIONS)}. "
            f"Refusing rather than guessing, per the schema's own rule."
        )
    for block in ("state", "params"):
        if block not in payload:
            raise SubmissionError(f"submission has no {block!r} block")

    state, params = payload["state"], payload["params"]
    if params.get("G") is None:
        raise SubmissionError(
            "params.G (target annual spend) is required: the independence requirement is (G - yields) / swr, "
            "a difference of two large numbers, so a missing G does not degrade the answer, it invents one."
        )

    deferred: list[tuple[str, str]] = []
    assumed: list[tuple[str, Any, str]] = []

    if state.get("age") is None:
        raise SubmissionError("state.age is required; it drives AHV, both pension gates and the earning decline")
    x0 = _build_state(state, age=float(state["age"]), assumed=assumed)

    # --- params: route each key, never splat ------------------------------------------------------------
    known = _params_field_names()
    overrides: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        if k in known:
            overrides[k] = tuple(float(a) for a in v) if k in _TUPLE_PARAMS else v
        elif k in _PARAM_ALIASES:
            target = _PARAM_ALIASES[k]
            overrides[target] = v
            assumed.append((target, v, f"from the submission's {k!r}, which is the same quantity under "
                                       f"the schema's name"))
        elif k in ("epsilon", "years_in_retirement"):
            continue  # consumed by the goals below
        elif k == "p_A":
            deferred.append((f"params.p_A = {v}",
                             "amortisation is a CONTROL the optimiser chooses; a stated figure is current "
                             "behaviour, not a constraint, and is reported back rather than imposed"))
        elif k == "tau_H_hint":
            deferred.append((f"params.tau_H_hint = {v}",
                             "rest share is a control, not a parameter; it informs the warm start, not Params"))
        elif k in ("max_loss_pct", "expected_return_pct"):
            deferred.append((f"params.{k} = {v}",
                             "a mandate condition for the Optimiser, not a Life Balance Sheet parameter"))
        # --- the three keys onb@0.1.3 added that this engine cannot express ---------------------------
        elif k == "stop_work_age":
            deferred.append((f"params.stop_work_age = {v}",
                             "the engine's retirement span is computed from the reference age of 65 and has "
                             "no field for an earlier stop, so this cannot enter the equations. The report "
                             "prices the bridge from it, and names the limitation"))
        elif k == "mortgage_fixed_until":
            deferred.append((f"params.mortgage_fixed_until = {v}",
                             "the model has one mortgage rate for the whole horizon and no date on which "
                             "it resets, so a maturity cannot enter the equations. It is a finding for the "
                             "report, which is where it is used"))
        elif k == "amortisation_mode":
            deferred.append((f"params.amortisation_mode = {v!r}",
                             "whether amortisation is direct or indirect changes what the payment DOES, "
                             "not a parameter: direct reaches p_A, indirect is the pillar-3a contribution "
                             "and is counted there"))
        elif k == "amortisation_indirect":
            deferred.append((f"params.amortisation_indirect = {v}",
                             "an indirect amortisation pays into pillar 3a and leaves the debt standing. "
                             "Booking it as amortisation would retire a debt that is still outstanding and "
                             "double-count money already declared as a 3a contribution"))
        else:
            raise SubmissionError(f"params.{k!r} is not a Params field and has no documented route")

    # A declared partner with no splitting factor is still taxed jointly if married, and the payload may say one
    # without the other. Only `has_partner` is inferred here, and only from an explicit partner income.
    if overrides.get("has_partner") is None and overrides.get("partner_income"):
        overrides["has_partner"] = True
        assumed.append(("has_partner", True, "inferred from a non-zero partner_income"))

    # --- children: report what was assumed, because the assumptions here move the answer ---------------
    #
    # Two of them are worth stating to the household in as many words. The COST LEVEL, when the household did
    # not give one, is a published Swiss average in a 2000-2005 price base covering direct consumption only —
    # so it understates real outlay, most for young children in daycare. The END DATE, when not given, is 21,
    # and on the Bern submission that one number is the difference between a 749 000 capital gap and a 34 000
    # one. Neither belongs in a footnote.
    if overrides.get("child_ages"):
        if overrides.get("child_costs_stated") is None:
            assumed.append((
                "child cost level", "BFS / Buero BASS 2009, Tabellen 11 and 12",
                "no figure given, so the published Swiss average is used. Price base EVE 2000-2005 and direct "
                "consumption only: it excludes health-insurance premiums and paid childcare, so it understates "
                "what a household with young children actually spends"))
        if overrides.get("child_cost_end_age") is None:
            assumed.append((
                "child_cost_end_age", 21.0,
                "no end date given; 21 is the upper edge of the published band. A longer or shorter education "
                "changes the result materially and this is the cheapest question to answer exactly"))
        if overrides.get("child_reference_age") is None and state.get("age") is not None:
            overrides["child_reference_age"] = float(state["age"])
            assumed.append(("child_reference_age", float(state["age"]),
                            "not supplied; taken from the subject's age, which is when the ages were recorded"))

    # --- goals ------------------------------------------------------------------------------------------
    specs: list[GoalSpec] = []
    for g in payload.get("goals") or []:
        kind = g.get("kind")
        desc = g.get("description") or kind or "(unnamed)"
        if kind in _NON_GOAL_KIND_REASONS:
            deferred.append((f"goal {desc!r} ({kind})", _NON_GOAL_KIND_REASONS[kind]))
            continue
        if kind not in _ENGINE_GOAL_KINDS:
            deferred.append((f"goal {desc!r} ({kind})", "not a goal kind this engine has a slack function for"))
            continue
        horizon = _horizon_years(g.get("target_year"), (payload.get("meta") or {}).get("collected"))
        if horizon is None or horizon <= 0:
            deferred.append((f"goal {desc!r} ({kind})",
                             "no usable target_year, so it has no deadline; a goal without a date cannot be "
                             "scored by a chance constraint"))
            continue
        conf = g.get("confidence")
        eps = (1.0 - float(conf)) if conf is not None else params.get("epsilon")
        if eps is None:
            eps = 0.10
            assumed.append((f"epsilon for {desc!r}", 0.10, "no confidence given; the engine's usual target"))
        specs.append(GoalSpec(kind=kind, horizon_years=float(horizon),
                              epsilon=max(0.01, min(0.5, float(eps))),
                              params=_goal_params(kind, g, params, assumed)))

    if not specs:
        raise SubmissionError(
            "no runnable goal in this submission. Every goal was deferred or underspecified — see the deferred "
            "list. The engine optimises against a dated, quantified goal; without one there is nothing to solve."
        )

    # --- the canton, which until now was collected and reached no equation -----------------------------
    #
    # **Applied HERE and not in the dynamics, which is the same rule the second pillar follows.**
    # `model/dynamics.py` and `optim/symbolic.py` are one model in two transcriptions and the parity tests
    # exist to keep them that way; a per-canton factor belongs to the household, not to the model, so it
    # enters as a parameter override and both transcriptions stay untouched.
    #
    # The factors are measured rather than derived: BFS «Statistik der Schweizer Städte», the tax burden of a
    # single person in each cantonal capital, scaled onto the model's own national curve. Where the table has
    # no entry the factor is 1.0 and `calibrated` is False, which the report states rather than hiding.
    raw_block = payload.get("raw") or {}
    canton_name = str(raw_block.get("canton") or "").strip()
    if canton_name:
        try:
            from ..model import canton as _canton  # noqa: PLC0415 - only this branch needs the table
            cf = _canton.factors_for(canton_name)
        except Exception as exc:  # noqa: BLE001 - a broken table must not refuse the whole submission
            cf = None
            deferred.append((f"raw.canton = {canton_name!r}",
                             f"the cantonal tax table could not be read ({exc}); the national approximation "
                             f"stands"))
        if cf and cf["calibrated"]:
            base = Params()
            for field, key, label in (("tax_rate_max", "income_factor", "Einkommenssteuer"),
                                      ("wealth_tax_rate", "wealth_factor", "Vermögenssteuer")):
                if field in overrides:
                    continue  # an explicit figure in the submission outranks a table
                scaled = getattr(base, field) * float(cf[key])
                overrides[field] = scaled
                assumed.append((field, round(scaled, 6),
                                f"{label} kalibriert für {canton_name} (Faktor {cf[key]:.3f} auf den "
                                f"nationalen Näherungssatz, Quelle {cf['as_of']})"))
        elif cf:
            deferred.append((f"raw.canton = {canton_name!r}", cf["why_not"] or
                             "no factor for this canton; the national approximation stands"))

    primary, extras = specs[0], specs[1:]
    meta = payload.get("meta") or {}
    return Conversion(
        case=Case(
            name=name or meta.get("source") or "Onboarding submission",
            persona=f"age {x0.person.age:.0f} · from {version}",
            x0=x0, goal=primary, confidence=1.0 - primary.epsilon,
            param_overrides=overrides, extra_goals=extras,
            calibrated=False,  # a live submission is never a fitted case
            notes=meta.get("source", ""),
        ),
        deferred=deferred,
        assumed=assumed,
    )
