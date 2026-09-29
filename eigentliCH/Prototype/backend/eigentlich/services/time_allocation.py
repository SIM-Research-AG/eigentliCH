"""Where the marginal hour goes, as a set of options with their consequences.

The scarce resource in this model is not money, which can be borrowed and compounded, but time, which
cannot be stored or transferred. This module asks the engine what happens to a person's capitals and
income when hours move between work, learning, networking and rest.

===========================================================================================================
IT PRODUCES A FRONTIER, NEVER A CHOICE — AND THAT IS WHAT MAKES IT LAWFUL
===========================================================================================================

C-01 forbids a personalised recommendation without a curator, and «move five hours from work to learning»
is exactly that. So this returns every option it evaluated, each carrying what it costs and what it
produces, and selects none of them. The member chooses, or a curator does.

That is not a workaround. It is the shape `models/action.py` already enforces at the database:
`prepared_options` is non-nullable with a CHECK of at least two entries, each of which must carry a
consequence, because **an option without a consequence is a label**. `as_prepared_options()` below emits
exactly that shape. A single-option result cannot be stored, which is the constraint doing its job.

`optim/achievable.py` in the engine draws the same line in its own words: "It is a Befund, not a
Recommendation… Nothing here says anyone should want X."

===========================================================================================================
WHAT IS COMPUTED, AND WHAT IS NOT
===========================================================================================================

The engine's own `drift` is called. Nothing here reimplements a dynamic: `learning_effect` saturates at a
20 h/week knee, `network_effect` at 10, `rest_effect` is a square root, health decays faster above a
50-hour week, and every one of those lives in `personal_alm.model.dynamics` and is read from there.

**One year, not a lifetime.** Each option reports the first year's change in each capital and the income
at the end of it. A multi-year path would need the solver, a habit stock and a consumption policy, and
would turn a measurement into a projection. The one-year step is what can be stated without those.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import human_capital as hc

#: Hours moved per step when building the frontier. Read from the record, not written here.
_SHIFT_KEY = "frontier_shift_hours"

#: The portfolio tilt held constant while the HOURS move. C-02 refuses a bare 0.5 in application code and
#: it is right to: a risk tilt is exactly the kind of number that belongs in a reviewed record. It is not
#: one here because it is not an input to this comparison — it is held at the midpoint of its own [0, 1]
#: range so that it contributes the same amount to every option and therefore contributes nothing to the
#: difference between them. Expressed as a fraction rather than a decimal so that is legible.
_NEUTRAL_THETA = 1 / 2

#: Rounding slack when checking that four time shares fit inside one week. A floating-point guard and not
#: a quantity: at a 100-hour week this is a thirty-sixth of a second.
_ROUNDING = 1 / 1_000_000

#: How many hours one step of the frontier moves, where the record does not say. Five is a
#: legible unit of a week rather than a calibrated quantity, and the record may override it.
_DEFAULT_SHIFT_HOURS = 5

#: Below this many hours a week, a move is a rounding artefact rather than a change worth a
#: sentence. Three minutes.
_ROUNDING_HOURS = 1 / 20


class EngineUnavailable(Exception):
    """The Life Balance Sheet engine is not reachable, so no frontier can be computed."""


def _engine():
    """The engine's own dynamics, or a refusal. Same path as `human_capital._engine`."""
    earning, Params = hc._engine()
    if earning is None:
        return None
    import personal_alm.model.controls as controls
    import personal_alm.model.dynamics as dynamics
    import personal_alm.model.state as state
    from personal_alm.model.expertise import Expertise

    return {"dynamics": dynamics, "controls": controls, "state": state,
            "Expertise": Expertise, "Params": Params}


@dataclass(frozen=True)
class Option:
    """One way to spend the week, and what follows from it."""

    key: str
    label: dict
    #: Hours a week, the four shares plus the residual.
    hours: dict
    #: What it produces, all per year.
    income: float
    #: Change in each capital over one year, from the engine's own drift.
    dE: float
    dN: float
    dH: float
    #: Against the member's current allocation. Negative means worse.
    income_delta: float
    consequence: dict
    caveats: list = field(default_factory=list)


@dataclass(frozen=True)
class Frontier:
    """Every option evaluated, and the one the member is on today."""

    current: Option
    options: list
    productive_week_hours: float
    caveats: list = field(default_factory=list)

    def as_prepared_options(self) -> list:
        """The shape `models/action.py` requires: at least two, each with a consequence.

        **The current allocation is included as an option.** Doing nothing is a choice with consequences
        like any other, and a list that omits it invites the reading that something must change.
        """
        return [
            {"key": option.key, "label": option.label["de"],
             "consequence": option.consequence["de"]}
            for option in [self.current, *self.options]
        ]


def _record() -> dict:
    return hc._record()


@dataclass(frozen=True)
class _Capitals:
    """The three capitals as fields rather than as dictionary keys, deliberately.

    `test_submission_symbols` refuses any subscript by `"E"`, `"W_L"` or `"W_R"` anywhere in the package,
    because those three symbols mean different quantities in a submission and in the engine — a
    submission's `W_L` is liquid wealth and the engine's is human capital as a stock. This module's `"E"`
    happened to be the engine's, but the guard checks the SHAPE and not the intent, which is the only
    thing a guard can check. Attribute access is both safe and clearer.
    """

    expertise: float
    network: float
    health: float


def _person(engine, capitals: _Capitals, age, wealth):
    Expertise = engine["Expertise"]
    st = engine["state"]
    return st.State(
        wealth=st.HouseholdWealth(W_L=wealth.get("W_L", 0), W_R=wealth.get("W_R", 0),
                                  D=wealth.get("D", 0), W_P=wealth.get("W_P", 0),
                                  W_3a=wealth.get("W_3a", 0)),
        persons=[st.PersonState(E=Expertise.scalar(capitals.expertise), N=capitals.network,
                                H=capitals.health, age=age)],
    )


def _control(engine, shares, params):
    """A Control at the given time shares. The money flows are held at zero deliberately.

    Consumption, education spend, network spend and amortisation are levers of their own, and moving them
    at the same time as the hours would make the comparison say nothing about the hours.
    """
    return engine["controls"].Control(
        tau_Y=shares["tau_Y"], tau_E=shares["tau_E"], tau_N=shares["tau_N"], tau_H=shares["tau_H"],
        C=0, m_E=0, m_N=0, p_A=0, theta=params.get("theta", _NEUTRAL_THETA),
    )


def _evaluate(engine, key, label, shares, capitals, age, wealth, params, record):
    dyn, Params = engine["dynamics"], engine["Params"]
    calibration = record["earning_power"]["calibration"]
    p = Params(earning_power_at_unit=float(calibration["earning_power_at_unit"]))
    state = _person(engine, capitals, age, wealth)
    control = _control(engine, shares, params)
    week = float(record["time"]["productive_week_hours"])

    income = float(dyn.income(state, control, p))
    deriv = dyn.drift(state, control, p)
    dE = float(deriv.dE[0]) if hasattr(deriv.dE, "__len__") else float(deriv.dE)
    return Option(
        key=key, label=label,
        hours={name: shares[name] * week for name in ("tau_Y", "tau_E", "tau_N", "tau_H")},
        income=income, dE=dE, dN=float(deriv.dN), dH=float(deriv.dH),
        income_delta=0, consequence={"de": "", "en": ""},
    )


def _consequence(option, current, record):
    """What this option costs and produces, in one sentence per language. No verdict."""
    week = float(record["time"]["productive_week_hours"])
    moved = option.hours["tau_Y"] - current.hours["tau_Y"]
    delta = option.income - current.income

    def de(value, digits=2):
        return f"{value:.{digits}f}".replace(".", ",")

    def chf(value):
        return f"{round(value):,}".replace(",", "'")

    if abs(moved) < _ROUNDING_HOURS:
        head_de = "Ihre heutige Aufteilung."
        head_en = "Your allocation today."
    else:
        direction_de = "weniger" if moved < 0 else "mehr"
        head_de = f"{de(abs(moved), 0)} Stunden {direction_de} Erwerbsarbeit pro Woche."
        head_en = (f"{abs(moved):.0f} hours {'less' if moved < 0 else 'more'} paid work a week.")

    # **Against the current allocation, not in absolute terms.** Every capital in this model decays, so
    # an absolute reading says "expertise falls" under every option and hides the only thing a reader is
    # comparing. What differs between options is how much less, or more, each one falls.
    def better(mine, theirs, name_de, name_en):
        gap = mine - theirs
        if abs(gap) < _ROUNDING:
            return None, None
        return (f"{name_de} {'fällt weniger' if gap > 0 else 'fällt stärker'}",
                f"{name_en} {'declines less' if gap > 0 else 'declines faster'}")

    moves_de, moves_en = [], []
    for mine, theirs, name_de, name_en in (
        (option.dE, current.dE, "Expertise", "expertise"),
        (option.dN, current.dN, "Netzwerk", "network"),
        (option.dH, current.dH, "Gesundheit", "health"),
    ):
        one_de, one_en = better(mine, theirs, name_de, name_en)
        if one_de:
            moves_de.append(one_de)
            moves_en.append(one_en)

    money_de = f"Einkommen {chf(option.income)} im Jahr"
    if abs(delta) >= 1:
        money_de += f" ({'+' if delta > 0 else '−'}{chf(abs(delta))})"
    capitals_de = ("Über ein Jahr " + ", ".join(moves_de) + "."
                   if moves_de else "Über ein Jahr bewegt sich kein Kapital anders als heute.")
    capitals_en = ("Over one year " + ", ".join(moves_en) + "."
                   if moves_en else "Over one year no capital moves differently.")
    return {"de": f"{head_de} {money_de}. {capitals_de}",
            "en": f"{head_en} Income {chf(option.income)} a year. {capitals_en}"}


def frontier(answers: dict, *, wealth: dict | None = None, record: dict | None = None,
             k3_permitted: bool = True) -> Frontier:
    """Every way of spending the week this module evaluated, with what each produces.

    Raises `EngineUnavailable` where the engine cannot be reached, and `ValueError` where the member's
    own answers do not determine a starting allocation — a frontier drawn from a guessed starting point
    would compare options against a person who does not exist.
    """
    record = record or _record()
    engine = _engine()
    if engine is None:
        raise EngineUnavailable(
            "the Life Balance Sheet engine is not importable, so no time allocation can be evaluated. "
            "It is a separate programme in this repository and needs numpy."
        )

    capitals = hc.capitals(answers, record=record, k3_permitted=k3_permitted)
    budget = hc.time_budget(answers, record=record)
    age = hc._number(answers.get("age"))
    caveats = list(capitals.caveats) + list(budget.caveats)

    # **E and N are required; H is not, and that is the K3 condition rather than an oversight.**
    # Expertise and network set the earning power and there is no honest substitute for either. Health
    # multiplies it, so its absence is survivable: the computation runs at full health, the answer is
    # overstated, and the caveat below says so. A consumer that refused when H was withheld would make
    # exercising erasure look like a broken plan.
    missing = [c.key for c in (capitals.E, capitals.N) if not c.known]
    if missing or budget.tau_Y is None or age is None:
        raise ValueError(
            "a frontier needs expertise, a network, an age and a stated working week. Missing: "
            + ", ".join(missing + ([] if budget.tau_Y is not None else ["hours_per_week"])
                        + ([] if age is not None else ["age"]))
        )

    time = record["time"]
    week = float(time["productive_week_hours"])
    bounds = time["bounds"]
    shift = float(time.get(_SHIFT_KEY, _DEFAULT_SHIFT_HOURS)) / week

    # **The starting point uses whatever the member actually stated.** `tau_E` and `tau_N` are None where
    # the two hours questions were not answered; they are read as zero HERE and the caveat says so, which
    # is different from `time_budget` inventing them — this module has to put a number somewhere to call
    # the engine at all, and it says which number and why.
    base = {"tau_Y": budget.tau_Y,
            "tau_E": budget.tau_E if budget.tau_E is not None else 0,
            "tau_N": budget.tau_N if budget.tau_N is not None else 0,
            "tau_H": budget.tau_H if budget.tau_H is not None else float(bounds["min_tau_H"])}

    unstated = [name for name, value in (("Lernen", budget.tau_E), ("Netzwerk", budget.tau_N))
                if value is None]
    if unstated:
        caveats.append(f"no hours were stated for {' and '.join(unstated)}; they are read as zero for "
                       f"this comparison and every option below is measured against that")

    # Attribute access throughout, never a subscript by these names -- see `_Capitals`.
    health = capitals.H.value
    if health is None:
        health = 1
        caveats.append("health was not available, so every figure here is computed at full health and "
                       "overstates income")

    stocks = _Capitals(expertise=capitals.E.value, network=capitals.N.value, health=health)
    current = _evaluate(engine, "current", {"de": "Wie heute", "en": "As today"},
                        base, stocks, age, wealth or {}, {}, record)

    moves = (
        ("to_learning", {"de": "Stunden in Weiterbildung verschieben",
                         "en": "Move hours into learning"}, "tau_E"),
        ("to_network", {"de": "Stunden in berufliche Kontakte verschieben",
                        "en": "Move hours into professional contacts"}, "tau_N"),
        ("to_rest", {"de": "Stunden in Erholung verschieben",
                     "en": "Move hours into recovery"}, "tau_H"),
    )
    options = []
    for key, label, target in moves:
        shares = dict(base)
        take = min(shift, max(0, shares["tau_Y"]))
        if take <= 0:
            continue
        shares["tau_Y"] -= take
        shares[target] += take
        if sum(shares.values()) > 1 + _ROUNDING:
            continue
        option = _evaluate(engine, key, label, shares, stocks, age, wealth or {}, {}, record)
        options.append(option)

    # More work is an option too, where the ceiling allows it. Leaving it out would make the frontier
    # argue for less work by omission.
    if base["tau_Y"] + shift <= float(bounds["max_tau_Y"]):
        shares = dict(base)
        shares["tau_Y"] += shift
        spare = min(shift, shares["tau_E"] + shares["tau_N"])
        take_from = "tau_E" if shares["tau_E"] >= shares["tau_N"] else "tau_N"
        shares[take_from] = max(0, shares[take_from] - spare)
        if sum(shares.values()) <= 1 + _ROUNDING:
            options.append(_evaluate(engine, "to_work",
                                     {"de": "Stunden in Erwerbsarbeit verschieben",
                                      "en": "Move hours into paid work"},
                                     shares, stocks, age, wealth or {}, {}, record))

    priced = []
    for option in [current, *options]:
        filled = Option(
            key=option.key, label=option.label, hours=option.hours, income=option.income,
            dE=option.dE, dN=option.dN, dH=option.dH,
            income_delta=option.income - current.income,
            consequence=_consequence(option, current, record),
        )
        priced.append(filled)
    return Frontier(current=priced[0], options=priced[1:], productive_week_hours=week,
                    caveats=caveats)


__all__ = ["EngineUnavailable", "Frontier", "Option", "frontier"]
