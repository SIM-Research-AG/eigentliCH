"""Publishing an AssumptionSet from the estate's own engines. A35, C-02, §12.

**Where the numbers come from, and why they are not invented.** `market_signal` (Macro_Model) computes a
Regime and `return_estimation` (Fund_Map) computes a ReturnSet under it. Both are properties of the world
rather than of a household: no member's data reaches either, and both are reproducible from a published
artefact carrying a `REG-` or `RS-` id. So the first AssumptionSet is *read off* two engine runs and
stamped with the ids they came from. Nothing in this module composes, averages, rounds or converts a rate.

**What "invent no number" costs here, stated plainly.** The engines publish per-scenario expected returns
by role and the scenario probabilities behind them. They do not publish one blended rate. Blending is one
multiplication away and it is deliberately not done: which probabilities weight which horizon is a
modelling decision with an owner, and doing it here would put that decision in a service module where
nobody would find it again. The AssumptionSet carries both halves; whoever illustrates does the arithmetic
and says so.

**`inflation` is published as NULL, and that is a finding rather than an omission.** Neither engine emits an
inflation figure — the string does not occur in either artefact — and the Fund Map stamps its values as
`annualised_decimal` without saying whether they are nominal or real. So there is nothing to read. A
plausible Swiss figure typed in here would be exactly the defect §12 describes, and any illustration in
real terms must refuse until somebody publishes one with their name against it.

**If an engine will not run, nothing is published.** `NothingToPublish` carries the reason. An empty
assumption-set table is the honest state, `NoAssumptionSet` already refuses every illustration over it
(C-02), and a half-filled set would be worse than none because it would look complete.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engines import (
    DEFAULT_MARKET_SCOPE,
    EngineNotAvailable,
    call_engine,
)
from ..models import AssumptionSet, NoAssumptionSet
from .engine_inputs import plan_for

#: A10: SIM Research owns all seven engines, declared 30 August 2026. The same name stands behind the
#: numbers they produce, and `published_by` is non-nullable precisely so it cannot go unrecorded.
OWNER = "SIM Research"

#: `AssumptionSet.version` is `String(40)` and unique. A version built from the two run ids in full would
#: not fit, so each is truncated to a prefix long enough to be unambiguous in practice; the ids in full are
#: in `rates["source"]`, which is what anyone actually traces a number through.
REGIME_ID_CHARS = 12
RETURN_SET_ID_CHARS = 11

#: Which engines seed the set, in the order they must run: the ReturnSet is estimated under exactly one
#: Regime and checks the id it was given.
WORLD_ENGINES = ("market_signal", "return_estimation")


class NothingToPublish(Exception):
    """No AssumptionSet was published, and why. R-302's shape applied to a publishing run.

    Raised rather than returning a partial set. C-02 and §12 both make a made-up rate a defect, and the
    only way to keep that true when an engine is down is to publish nothing and say so.
    """


def _run_world_engines(*, scope: str, publish_artefacts: bool, purpose: str) -> dict[str, dict]:
    """Run the two world engines and return their replies, artefacts included.

    `publish_artefacts=False` by default: republishing on every read would move the Regime under a consumer
    mid-run, and a Regime is meant to be a vintage that downstream artefacts stamp. Pass True to recompute,
    which takes minutes and reaches the network.

    Raises:
        NothingToPublish: When either engine will not run. Both or neither — a ReturnSet without the Regime
            it was estimated under is a set of numbers with no vintage.
    """
    regime_plan = plan_for("market_signal", scope=scope, publish=publish_artefacts)
    try:
        regime = call_engine(
            "market_signal", regime_plan.payload, purpose=purpose, include_artefact=True
        )
    except EngineNotAvailable as error:
        raise NothingToPublish(
            f"market_signal would not run ({error.reason}), so there is no Regime to publish an assumption "
            f"set under. Nothing was written."
        ) from error

    returnset_plan = plan_for(
        "return_estimation",
        scope=scope,
        publish=publish_artefacts,
        regime_id=regime["contract"]["regime_id"],
    )
    try:
        returnset = call_engine(
            "return_estimation", returnset_plan.payload, purpose=purpose, include_artefact=True
        )
    except EngineNotAvailable as error:
        raise NothingToPublish(
            f"return_estimation would not run ({error.reason}). The Regime "
            f"{regime['contract']['regime_id']} is published, but a Regime alone carries no rate — "
            f"nothing was written."
        ) from error

    return {"market_signal": regime, "return_estimation": returnset}


def compose(runs: dict[str, dict], *, run_date: date) -> dict:
    """Turn two engine replies into the fields of an AssumptionSet. Reads only; computes nothing.

    Every value below is copied from an engine's own output. The one place a value is *constructed* is
    `version`, which is an identifier rather than a quantity.
    """
    regime = runs["market_signal"]
    returnset = runs["return_estimation"]
    regime_contract = regime["contract"]
    returnset_contract = returnset["contract"]
    regime_artefact = regime["artefact"]
    returnset_artefact = returnset["artefact"]

    regime_id = regime_contract["regime_id"]
    return_set_id = returnset_contract["return_set_id"]

    if returnset_contract["regime_id"] != regime_id:
        # `require_regime_match` in the estate should already have raised. Checked again because this is
        # the boundary where the two ids are written down together and stamped on every illustration.
        raise NothingToPublish(
            f"the ReturnSet {return_set_id} was estimated under {returnset_contract['regime_id']}, not "
            f"under {regime_id}. An assumption set stamped with two vintages traces to neither."
        )

    as_of = regime_contract["as_of"]
    window = regime["raw"]

    return {
        "version": (
            f"{as_of}+{regime_id[:REGIME_ID_CHARS]}+{return_set_id[:RETURN_SET_ID_CHARS]}"
        ),
        # The vintage the numbers describe, not the day they were read. `as_of` is the data date both
        # engines stamp; the day of the run is recorded in `published_by`, where a reader looks for it.
        "effective_from": date.fromisoformat(as_of),
        # A35: SIM Research, and the run date.
        "published_by": f"{OWNER}, run {run_date.isoformat()}",
        "rates": {
            # Full ids, so a rate on a screen traces back to a run that can be replayed by hand.
            "source": {
                "market_signal": {
                    "regime_id": regime_id,
                    "regime_timeline_id": regime_contract["regime_timeline_id"],
                    "scope": regime_contract["scope"],
                    "as_of": regime_contract["as_of"],
                    "model_version": regime_contract["model_version"],
                    "trace_id": regime["trace_id"],
                    "idempotency_key": regime["idempotency_key"],
                    "replay": regime["replay"],
                },
                "return_estimation": {
                    "return_set_id": return_set_id,
                    "regime_id": returnset_contract["regime_id"],
                    "scope": returnset_contract["scope"],
                    "as_of": returnset_contract["as_of"],
                    "model_version": returnset_contract["model_version"],
                    "universe_version": returnset_contract["universe_version"],
                    "trace_id": returnset["trace_id"],
                    "idempotency_key": returnset["idempotency_key"],
                    "replay": returnset["replay"],
                },
            },
            #: The unit the Fund Map stamps on its own values. Copied, never assumed.
            "values_unit": returnset_contract["values_unit"],
            "scenarios": returnset_artefact["scenarios"],
            #: Expected return per portfolio role, per macro scenario. The Fund Map's own aggregation of
            #: its building blocks, at the granularity the plan speaks in.
            #:
            #: **The role names are the ENGINE's, and are left as it wrote them.** The estate calls the
            #: first role `gain`; §4 and `models.plan.ROLES` call it `growth`. The other three agree.
            #: Renaming here would make the AssumptionSet disagree with the artefact it was read from, and
            #: a silent rename inside a provenance record is worse than a mismatch anyone can see.
            "role_profiles_by_scenario": returnset_artefact["role_profiles"],
            #: The probability the Fund Map attaches to each scenario, from the Regime's own distribution.
            #: Published beside the profiles and never multiplied into them — see the module docstring.
            "scenario_probabilities": returnset_artefact["house_view"],
            "state_grid": returnset_artefact["state_grid"],
            "state_to_scenario": returnset_artefact["state_to_scenario"],
            "state_to_scenario_version": returnset_artefact["state_to_scenario_version"],
            #: What the Regime says about the world as at `as_of`.
            "regime_current": regime_artefact["current"],
            "series_sources": returnset_artefact["provenance"]["series_sources"],
        },
        "horizons": {
            #: ReturnSets are keyed on (scope, horizon): a ten-year per-state return is not a one-year
            #: return compounded, because the regime does not persist for ten years. So this set carries
            #: rates for ONE horizon, and an illustration over another needs its own published set.
            "return_estimation_years": returnset_contract["horizon_years"],
            "scope": returnset_contract["scope"],
            "regime_window": {
                "first": window.get("first"),
                "last": window.get("last"),
                "months": window.get("months"),
            },
        },
        #: NULL, deliberately. See the module docstring: neither engine publishes an inflation figure, and
        #: this is the field C-02 exists to stop somebody filling in from memory.
        "inflation": None,
        "notes": _notes(runs),
    }


def _notes(runs: dict[str, dict]) -> str:
    """The prose a reader needs before using any of these numbers.

    Every engine note is carried through verbatim. The engines say things about their own output that no
    downstream reader could reconstruct — that a ReturnSet is seed-based rather than measured, that a
    macro half is annual and stepped — and dropping them would leave the numbers looking better sourced
    than they are.
    """
    regime = runs["market_signal"]
    returnset = runs["return_estimation"]
    coverage = returnset["raw"].get("coverage", {})

    lines = [
        f"Seeded from two engine runs under {OWNER} (A10, A35). Nothing here was composed, blended or "
        f"rounded: every value is copied from what an engine published.",
        f"Regime {regime['contract']['regime_id']} ({regime['contract']['model_version']}), scope "
        f"{regime['contract']['scope']}, {regime['raw'].get('months')} months "
        f"{regime['raw'].get('first')} to {regime['raw'].get('last')}.",
        f"ReturnSet {returnset['contract']['return_set_id']} "
        f"({returnset['contract']['model_version']}, universe "
        f"{returnset['contract']['universe_version']}), {returnset['raw'].get('blocks')} building blocks, "
        f"estimation coverage {coverage}.",
        "inflation is NULL: neither engine publishes one, and none was inferred. An illustration in real "
        "terms must refuse rather than assume (C-02, §12).",
        "No blended rate is published. `role_profiles_by_scenario` and `scenario_probabilities` are given "
        "separately; whoever mixes them owns that decision and must state it.",
        "Role names are the engine's own: `gain` here is `growth` in §4 and in models.plan.ROLES. Left "
        "unrenamed so this record matches the artefact it was read from.",
    ]
    lines += [f"market_signal: {note}" for note in regime.get("notes", ())]
    lines += [f"return_estimation: {note}" for note in returnset.get("notes", ())]
    return "\n".join(lines)


def publish(
    session: Session,
    *,
    run_date: date | None = None,
    scope: str = DEFAULT_MARKET_SCOPE,
    publish_artefacts: bool = False,
    purpose: str = "publish the first AssumptionSet (A35)",
) -> AssumptionSet:
    """Run the two world engines and write one AssumptionSet from what they produced. A35, C-02.

    Idempotent by construction: `version` is derived from the two run ids, and the table's unique
    constraint is on `version`. Re-running against an unchanged Regime and ReturnSet returns the row that
    is already there rather than writing a second identical one.

    Raises:
        NothingToPublish: When either engine will not run. Nothing is written, and the caller should say
            "not available" rather than fall back on anything (R-302).
    """
    runs = _run_world_engines(scope=scope, publish_artefacts=publish_artefacts, purpose=purpose)
    fields = compose(runs, run_date=run_date or date.today())

    existing = session.execute(
        select(AssumptionSet).where(AssumptionSet.version == fields["version"])
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    assumption_set = AssumptionSet(**fields)
    session.add(assumption_set)
    session.flush()
    return assumption_set


def current(session: Session, *, on: date | None = None) -> AssumptionSet:
    """The AssumptionSet in effect on a date. C-02.

    Raises:
        NoAssumptionSet: When none is. The correct behaviour is to refuse the illustration; a default rate
            is an invented rate wearing a different hat.
    """
    when = on or date.today()
    found = session.execute(
        select(AssumptionSet)
        .where(AssumptionSet.effective_from <= when)
        .order_by(AssumptionSet.effective_from.desc(), AssumptionSet.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if found is None:
        raise NoAssumptionSet(
            f"no assumption set is in effect on {when.isoformat()}. No illustration may be produced: "
            f"C-02 requires a published set and §12 makes a stand-in rate a defect. Publish one with "
            f"`python tools/publish_assumption_set.py`."
        )
    return found


def describe(assumption_set: AssumptionSet) -> dict[str, Any]:
    """The set as a response payload, with the `assumption_set_id` every illustration must carry (C-02)."""
    return {
        "assumption_set_id": assumption_set.id,
        "version": assumption_set.version,
        "effective_from": assumption_set.effective_from.isoformat(),
        "published_by": assumption_set.published_by,
        "rates": assumption_set.rates,
        "horizons": assumption_set.horizons,
        "inflation": assumption_set.inflation,
        "notes": assumption_set.notes,
        # R-304 / C-03: the ids travel, the artefacts they came from never do. `rates["source"]` names the
        # run; it does not carry the Regime timeline or the ReturnSet payload, and must not be made to.
        "artefacts_served": False,
    }
