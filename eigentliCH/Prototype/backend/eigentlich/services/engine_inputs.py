"""A39 — the mapping layer. `Position` and `Goal` translated into each engine's own input names.

**Why this file exists at all.** A13 rewrote the onboarding questions against `Position` and `Goal` and in
doing so removed the direct route the old onboarding schema gave into the Life Balance Sheet's `state` and
`params` field names. So the translation is now explicit rather than implicit — which is better: the mapping
is a file someone can read, and every place it stops is written down instead of being discovered later.

**Anything the plan cannot fill is left ABSENT, never defaulted.** A defaulted input is an invented input
one layer down, and §12 calls that a defect rather than a gap-fill. So a builder here never writes a
placeholder wealth, a placeholder rate or a plausible-looking horizon. It omits the key and records why in
`EnginePlan.absent`, where a caller — a screen, a queue worker, a test — can see it.

**A gap has a kind, because "could not be filled" hides four different situations** and treating them alike
would make the list useless:

  * `not_in_the_plan` — prototype2 records nothing that answers this. The honest fix is a new field and a
    question that earns it, not a guess here.
  * `needs_an_unpublished_assumption` — the value exists but is an assumption under C-02. It comes from a
    published `AssumptionSet` and from nowhere else, and certainly not from a service module.
  * `owned_by_the_engine` — the engine publishes its own considered default (Macro_Model's seven-economy
    blend, the Fund Map's estimation source). Omitting the key lets the engine's own decision stand;
    writing one here would silently re-decide it from a household's plan.
  * `supplied_by_the_caller` — a genuine parameter of the request rather than a property of the member: a
    what-if change, a `regime_id` from the run that just produced it.

Only the first two are gaps in the plan. The last two are gaps in this call, and a complete plan may still
carry them — which is why `complete` is defined against the first two and `missing()` returns all four.

**Nothing here calls an engine.** It builds payloads. `eigentlich.engines.call_engine` runs them, off the
request thread (R-301).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Sequence

from ..engines import (
    DAYS_PER_YEAR,
    DEFAULT_MARKET_SCOPE,
    DEFAULT_RETURNSET_HORIZON_YEARS,
    OPTIMISER_ALGORITHM,
    OPTIMISER_SPEED,
    load_manifest,
)
from ..models import ASSET, Goal, LIABILITY, Position, STOCK_UNITS

#: The four reasons an input can be missing. Named once so a caller can branch on them and a test can
#: assert that no builder invented a fifth.
GAP_KINDS = (
    "not_in_the_plan",
    "needs_an_unpublished_assumption",
    "owned_by_the_engine",
    "supplied_by_the_caller",
)

#: The two kinds that mean the member's plan does not answer the question. `complete` is defined against
#: these, so a payload waiting only on a caller's what-if does not read as an incomplete plan.
PLAN_GAP_KINDS = ("not_in_the_plan", "needs_an_unpublished_assumption")

# ---------------------------------------------------------------------------
# The reasons that recur, written once so they read identically wherever they apply
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# WEALTH AS A STOCK — rewritten 1 September 2026, and the constant renamed with it
# ---------------------------------------------------------------------------
#
# **`NO_WEALTH_STOCK` was this module's largest gap and it is gone.** It read: "the plan records
# Position.magnitude as chf_per_year (a flow) or share_of_total (a fraction), never a stock in francs.
# Capitalising a flow needs a discount rate and resolving a share needs a total; both are assumptions under
# C-02 and neither is published." Every clause of that was true, and the conclusion was still the wrong one
# — because the reason no stock was recorded was that **nobody had offered the member a unit for one**.
# `MAGNITUDE_UNITS` held a flow and a fraction, and the argument about capitalisation rates was doing the
# work that a third entry in a tuple should have been doing. A member could not say "I have CHF 45,000 in
# collectibles". Four engine inputs — `W_R`, `W_L`, `initial_wealth`, `D` — and the whole Life Balance Sheet
# hung on that.
#
# `chf` exists now (`models/plan.py`), so a stock is **stated, not derived**: no rate is applied, nothing is
# capitalised, nothing is resolved against a total the plan does not hold. The C-02 argument above is
# untouched and still forbids what it always forbade — it is simply no longer the reason there is no number.
#
# **What is still refused, and this is the part that has to survive the good news:**
#
#   * a flow is never turned into a stock. `chf_per_year` still needs a capitalisation rate and there still
#     is not one. `stated_stocks` reads `magnitude_unit in STOCK_UNITS` and nothing else.
#   * a share is never resolved. `share_of_total` still needs a total.
#   * **nothing is defaulted to zero.** A member who has stated no liability has not stated that they have
#     no debt, and `D = 0.0` is a claim about a household, not an absence. Absent stays absent.
#   * **assets and liabilities are never netted.** They are two engine inputs and they stay two numbers —
#     see the essay on `Position.stock_kind` for why that decided the field over a negative magnitude.

#: The completeness caveat, which did NOT go away and now travels on `notes` beside a filled value instead
#: of on a gap instead of a value. R-020 makes a plan of one position valid, so a sum over stated stocks is
#: the total the member has *stated* and is not an audited household balance sheet. An engine receiving
#: `W_R` cannot tell the difference, so the note says it in the one place a reader of the payload will look.
STOCK_IS_WHAT_THE_MEMBER_STATED = (
    "wealth figures below are the sum of the stocks this member has stated in chf, on active positions. "
    "R-020 makes a plan of one position valid, so this is what they said they hold and not an audited "
    "total; nothing here searches for what they did not mention."
)

#: What a stock gap says now. The unit exists, so the honest sentence is "this member has not stated one",
#: which is a fact about their plan rather than about the schema — and it is the sentence that would have
#: been false yesterday and would be a lie tomorrow if it still blamed the vocabulary.
_STOCK_ROUTE = (
    "Position.magnitude in the unit `chf` with stock_kind set, on an active position, is the route: it is "
    "stated by the member and never derived. `chf_per_year` is a flow and `share_of_total` is a fraction, "
    "and neither substitutes — capitalising a flow needs a discount rate and resolving a share needs a "
    "total the plan does not hold, both assumptions under C-02 and neither published. Nor is this "
    "defaulted to zero: a member who has stated nothing has not stated that they hold nothing."
)

#: A return is the assumption C-02 was written about. It never comes from this layer.
#:
#: **Updated 31 August 2026, because the first half stopped being the reason.** A set IS published now
#: (A69: `2024-12-31+REG-38d91c1a+RS-874b03c9`), so "no set exists" would be false — and a gap whose stated
#: reason has quietly gone stale is the same defect `services/goals.py` was carrying. The gap is still
#: real and the kind is still right: what the set publishes is an expected return per portfolio role per
#: macro scenario, with the scenario probabilities beside them and **nothing multiplying the two**. A
#: single `annual_return` needs that multiplication, and which probabilities weight which horizon is a
#: decision with an owner (A69). So what is unpublished is not the set; it is a blended annual rate.
RETURN_IS_AN_ASSUMPTION = (
    "a return is an assumption under C-02. It comes from a published AssumptionSet, stamped on the "
    "illustration that used it, and never from the plan or from application code. A set is published, and "
    "it deliberately carries no single blended rate: expected returns sit per role per macro scenario with "
    "the scenario probabilities beside them, and which probabilities weight which horizon is a decision "
    "with an owner (A69). Composing one here would make that decision inside a service module."
)


@dataclass(frozen=True)
class AbsentInput:
    """One input the plan could not fill, and why. A39's "gaps left visible", as data."""

    engine: str
    name: str
    declared_as: str
    kind: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in GAP_KINDS:
            raise ValueError(f"unknown gap kind {self.kind!r}; expected one of {', '.join(GAP_KINDS)}")

    @property
    def blocks_the_plan(self) -> bool:
        return self.kind in PLAN_GAP_KINDS

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "input": self.name,
            "declared_as": self.declared_as,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EnginePlan:
    """What can be sent to one engine, and what could not be filled.

    `payload` holds only inputs that were actually answered. It is never padded to the manifest's full
    input list: an absent key and a key holding an invented value are the same length on a screen and
    entirely different facts.
    """

    engine: str
    payload: dict[str, Any]
    absent: tuple[AbsentInput, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether the member's plan answers everything this engine needs from it.

        False while any gap is `not_in_the_plan` or `needs_an_unpublished_assumption`. A gap the engine or
        the caller owns does not make the *plan* incomplete.
        """
        return not any(gap.blocks_the_plan for gap in self.absent)

    def missing(self, kind: str | None = None) -> list[str]:
        """The names that could not be filled, optionally of one kind."""
        return [gap.name for gap in self.absent if kind is None or gap.kind == kind]

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "payload": dict(self.payload),
            "complete": self.complete,
            "absent": [gap.as_dict() for gap in self.absent],
            "notes": list(self.notes),
        }


@dataclass
class _Builder:
    """Accumulates a payload and its gaps, so a builder reads as a list of decisions rather than as
    bookkeeping. `fill` and `leave_absent` are the only two things that ever happen to an input."""

    engine: str
    payload: dict[str, Any] = field(default_factory=dict)
    absent: list[AbsentInput] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fill(self, name: str, value: Any) -> None:
        self.payload[name] = value

    def leave_absent(self, name: str, kind: str, reason: str) -> None:
        declared = load_manifest(self.engine).inputs
        if name not in declared:
            raise KeyError(f"{self.engine!r} declares no input {name!r}; the manifest is the authority")
        self.absent.append(
            AbsentInput(engine=self.engine, name=name, declared_as=declared[name], kind=kind, reason=reason)
        )

    def done(self) -> EnginePlan:
        return EnginePlan(
            engine=self.engine,
            payload=dict(self.payload),
            absent=tuple(self.absent),
            notes=tuple(self.notes),
        )


# ---------------------------------------------------------------------------
# Things that can honestly be read off the plan
# ---------------------------------------------------------------------------


def horizon_years(goal: Goal, *, today: date) -> float | None:
    """A goal's own horizon, in the years an engine asks for. None when the member has not given a date.

    Arithmetic over a date the member typed, not an assumption: `DAYS_PER_YEAR` is a calendar fact and
    lives with the engine config so no float literal sits in a service (C-02).

    A date already past returns a negative number rather than being clamped to zero. Clamping would tell an
    engine the goal is due today, which is not what the member said.
    """
    if goal.target_date is None:
        return None
    return (goal.target_date - today).days / DAYS_PER_YEAR


def funding_liquidity(goal: Goal) -> dict[str, int]:
    """How the active positions funding a goal are marked for liquidity, counted by band.

    Reported rather than scored. R-031's thresholds do not exist, so this is a fact about the plan and not
    an input any engine takes — it travels on `EnginePlan.notes` where a screen can show it beside a gap.
    """
    counts: dict[str, int] = {}
    for position in goal.funded_by:
        if not position.active:
            continue
        band = position.liquidity or "not_stated"
        counts[band] = counts.get(band, 0) + 1
    return counts


@dataclass(frozen=True)
class StatedStocks:
    """The balances in francs a member has stated, kept apart the way the engines ask for them.

    **Three numbers and never two.** `life_balance_sheet` declares `W_R`, `W_L` and `D` separately, so this
    keeps them separate: financial assets, human-capital assets, and everything owed. A single "net wealth"
    would be the netting error `Position.stock_kind` was chosen to prevent, arriving one layer up instead.

    **`liabilities` crosses the capital-type split on purpose.** A franc owed is owed whichever column the
    member filed it in — a student loan under human capital is a member classifying their own life
    correctly, not a data error — so it lands in `D` either way, and never in `W_R` or `W_L`.

    Every field is `None` when the member has stated nothing of that kind, which is different from `0.0` and
    has to stay different: zero is a claim about a household and absence is the absence of one.
    """

    financial_assets: float | None
    human_assets: float | None
    liabilities: float | None
    stated_by: dict[str, int]

    @property
    def any_stated(self) -> bool:
        return any(
            value is not None
            for value in (self.financial_assets, self.human_assets, self.liabilities)
        )


def stated_stocks(positions: Sequence[Position]) -> StatedStocks:
    """Sum the stated balances. **The only place in this module that reads a magnitude as an amount.**

    Four filters, and each one is a defect if it is missing:

      * `active` — R-122 keeps a stood-down position in history; counting it as wealth would read a
        member's record back to them wrong.
      * `magnitude_unit in STOCK_UNITS` — a flow and a share are not balances. This is the filter, and
        `STOCK_UNITS` rather than a literal because `chf` is a prefix of `chf_per_year` and a `startswith`
        here would sum a salary into somebody's savings.
      * `magnitude is not None` — held by a CHECK constraint too, and checked anyway.
      * `stock_kind` — asset to `W_R`/`W_L`, liability to `D`. A stock with neither cannot exist
        (`ck_positions_stock_kind_iff_stock`), and if one somehow did it is skipped rather than guessed at:
        filing an unmarked balance as an asset is exactly the silent default the field exists to refuse.
    """
    # Ints, not `0.0`. C-02's scan for float literals in application code is blunt on purpose and it is
    # right to be: an accumulator seed is not a rate, and adding francs to it promotes it anyway.
    financial = human = owed = 0
    counted = {"financial_assets": 0, "human_assets": 0, "liabilities": 0}

    for position in positions:
        if not position.active:
            continue
        if position.magnitude_unit not in STOCK_UNITS or position.magnitude is None:
            continue
        if position.stock_kind == LIABILITY:
            owed += position.magnitude
            counted["liabilities"] += 1
        elif position.stock_kind == ASSET:
            if position.capital_type == "human":
                human += position.magnitude
                counted["human_assets"] += 1
            else:
                financial += position.magnitude
                counted["financial_assets"] += 1

    return StatedStocks(
        financial_assets=financial if counted["financial_assets"] else None,
        human_assets=human if counted["human_assets"] else None,
        liabilities=owed if counted["liabilities"] else None,
        stated_by=counted,
    )


def _describe_positions(positions: Sequence[Position]) -> str:
    active = [p for p in positions if p.active]
    human = sum(1 for p in active if p.capital_type == "human")
    stocks = sum(1 for p in active if p.magnitude_unit in STOCK_UNITS)
    return (
        f"{len(active)} active position(s): {human} human capital, {len(active) - human} financial. "
        f"{sum(1 for p in active if p.magnitude is not None)} carry a magnitude with an explicit unit, "
        f"of which {stocks} state a balance in chf."
    )


# ---------------------------------------------------------------------------
# The builders, one per engine
# ---------------------------------------------------------------------------


def _fill_initial_wealth(builder: _Builder, positions: Sequence[Position]) -> None:
    """`initial_wealth` for the two engines that start a projection from a balance.

    **Financial assets only, and liabilities are not subtracted.** Both engines project a portfolio
    forward under a return; a mortgage is not part of a portfolio and a rate does not apply to it. Netting
    the debt out first would produce a smaller balance that then grows at a market rate - a claim that debt
    compounds like equity, which nobody published. `life_balance_sheet` is the engine that takes `D`, and
    it takes it as its own input for exactly this reason.

    **Human capital is not included either.** It is bounded by hours rather than by price (R-121) and it is
    `W_L` where an engine wants it. A trajectory engine starting from a member's own labour valued as a
    balance and growing it at a market rate is the A105 defect with an extra step.

    Shared by two builders so the two cannot answer the question differently; the note travels with the
    value because an engine receiving a number cannot see R-020.
    """
    stocks = stated_stocks(positions)
    if stocks.financial_assets is None:
        builder.leave_absent(
            "initial_wealth",
            "not_in_the_plan",
            "the balance a projection starts from. The plan can hold one - financial-capital positions "
            "with magnitude_unit `chf` and stock_kind `asset` - and this member has stated none. "
            + _STOCK_ROUTE,
        )
        return
    builder.fill("initial_wealth", stocks.financial_assets)
    builder.notes.append(STOCK_IS_WHAT_THE_MEMBER_STATED)
    builder.notes.append(
        "initial_wealth is financial assets only. Human capital is W_L and is bounded by hours (R-121); "
        "liabilities are D and are not subtracted here, because a debt does not grow at a market rate."
    )


def _market_signal(*, scope: str, publish: bool, **_: Any) -> EnginePlan:
    """Macro_Model. A property of the world: nothing about a member enters here.

    That is exactly why A35 seeds the first AssumptionSet from it — a Regime is real, computed and
    reproducible without anyone's plan.
    """
    builder = _Builder("market_signal")
    builder.fill("scope", scope)
    builder.fill("publish", publish)
    builder.leave_absent(
        "economies",
        "owned_by_the_engine",
        "Macro_Model publishes the seven-economy blend and its GDP weights itself (BLEND_ECONOMIES). "
        "Re-listing them here would produce a Regime the estate never published, under an id no ReturnSet "
        "could match.",
    )
    builder.leave_absent(
        "blend_weight",
        "owned_by_the_engine",
        "the country-weight blend belongs to the engine, and a blend computed after the fact carries an id "
        "no downstream artefact can be checked against.",
    )
    builder.notes.append("household-independent: this engine reads no member data at all")
    return builder.done()


def _return_estimation(*, scope: str, publish: bool, regime_id: str | None, **_: Any) -> EnginePlan:
    """Fund_Map. Also a property of the world, and estimated under exactly one Regime."""
    builder = _Builder("return_estimation")
    builder.fill("scope", scope)
    builder.fill("horizon_years", DEFAULT_RETURNSET_HORIZON_YEARS)
    builder.fill("publish", publish)
    if regime_id is None:
        builder.leave_absent(
            "regime_id",
            "supplied_by_the_caller",
            "the id of the Regime this ReturnSet must be checked against. It comes from the market_signal "
            "run in the same sequence; passing a remembered one would check against the wrong vintage.",
        )
    else:
        builder.fill("regime_id", regime_id)
    builder.leave_absent(
        "source",
        "owned_by_the_engine",
        "which series the estimation reads (`csv` for measured data, otherwise the seed-aware synthetic "
        "default) is the Fund Map's own decision and is stamped on what it publishes.",
    )
    builder.notes.append("household-independent: this engine reads no member data at all")
    return builder.done()


def _life_balance_sheet(*, member_id: str | None, positions: Sequence[Position], **_: Any) -> EnginePlan:
    """Life_Balance_Sheet. The engine whose `state` field names the old onboarding schema used to fill.

    **Rewritten 1 September 2026.** Every one of its wealth inputs used to be absent, and the finding was
    that the plan recorded what a position is FOR and how quickly it becomes money but not what it is
    worth - "reconstructing a balance sheet from it would be four assumptions in a trench coat". That was
    the right refusal of the wrong question. The plan now records what a position is worth, because the
    member can say so: `magnitude` in `chf`, with `stock_kind` naming which side of the sheet it is on.

    So `W_R`, `W_L` and `D` are **read** here, not reconstructed. No rate is applied and nothing is
    capitalised - the arithmetic is addition over figures the member typed, and the completeness caveat
    R-020 forces travels on `notes` rather than being buried. `E` stays absent, because it is a state
    variable of `personal_alm`'s own model with no counterpart in the plan and no unit that would fix that.
    """
    builder = _Builder("life_balance_sheet")
    if member_id is None:
        builder.leave_absent(
            "household_id",
            "supplied_by_the_caller",
            "no member was given to this mapping call, so there is nobody for this engine to run for. "
            "Pass member_id to fill it.",
        )
    else:
        builder.fill("household_id", member_id)

    stocks = stated_stocks(positions)

    if stocks.human_assets is None:
        builder.leave_absent(
            "W_L",
            "not_in_the_plan",
            "human capital as a stock in francs. The plan marks human-capital positions "
            "(Position.capital_type == 'human') and can now hold a balance for them, and this member has "
            "stated none. " + _STOCK_ROUTE,
        )
    else:
        builder.fill("W_L", stocks.human_assets)

    if stocks.financial_assets is None:
        builder.leave_absent(
            "W_R",
            "not_in_the_plan",
            "financial capital as a stock in francs. The plan can hold one and this member has stated "
            "none. " + _STOCK_ROUTE,
        )
    else:
        builder.fill("W_R", stocks.financial_assets)

    if stocks.liabilities is None:
        builder.leave_absent(
            "D",
            "not_in_the_plan",
            "debt. `Position.stock_kind = 'liability'` is the field that holds one — added 1 September "
            "2026, because until then no field on Position did and this gap said so. It is a field rather "
            "than a negative magnitude precisely so that D and W_R stay two numbers instead of netting "
            "into one. This member has stated no liability, which is NOT the same as stating that they "
            "have no debt: D is left absent rather than set to zero. " + _STOCK_ROUTE,
        )
    else:
        builder.fill("D", stocks.liabilities)

    if stocks.any_stated:
        builder.notes.append(STOCK_IS_WHAT_THE_MEMBER_STATED)
        builder.notes.append(
            f"stocks read from {stocks.stated_by['financial_assets']} financial asset, "
            f"{stocks.stated_by['human_assets']} human-capital asset and "
            f"{stocks.stated_by['liabilities']} liability position(s). Assets and liabilities are NOT "
            f"netted: W_R/W_L and D are separate inputs and stay separate numbers."
        )
    builder.leave_absent(
        "E",
        "not_in_the_plan",
        "a state variable of personal_alm's own model with no counterpart in Position or Goal. §9 says wrap "
        "the engine, not reinterpret it, and reading a member's answer as this variable would be the "
        "second thing.",
    )
    if positions:
        builder.notes.append(_describe_positions(positions))
    return builder.done()


def _s_curve_trajectory(
    *,
    member_id: str | None,
    goal: Goal | None,
    positions: Sequence[Position],
    today: date,
    **_: Any,
) -> EnginePlan:
    """The native trajectory engine. The one place a Goal genuinely fills engine inputs.

    `horizon_years` and `target` are the member's own date and amount. `initial_wealth` and `annual_return`
    are not, and no arrangement of the plan makes them so.
    """
    builder = _Builder("s_curve_trajectory")
    if member_id is None:
        builder.leave_absent(
            "household_id",
            "supplied_by_the_caller",
            "no member was given to this mapping call, so there is nobody for this engine to run for. "
            "Pass member_id to fill it.",
        )
    else:
        builder.fill("household_id", member_id)

    if goal is None:
        builder.leave_absent(
            "horizon_years",
            "supplied_by_the_caller",
            "no goal was given to this mapping call, so there is no target date to read a horizon from. "
            "Pass one to fill it.",
        )
        builder.leave_absent(
            "target",
            "supplied_by_the_caller",
            "no goal was given to this mapping call, so there is no target amount to read. Pass one to "
            "fill it.",
        )
    else:
        years = horizon_years(goal, today=today)
        if years is None:
            builder.leave_absent(
                "horizon_years",
                "not_in_the_plan",
                "the member has not dated this goal. R-030 makes an undated goal a legitimate state, so "
                "this is a plan that is finished rather than a plan that is missing something — and any "
                "horizon written here would be this layer deciding when the member needs the money.",
            )
        else:
            builder.fill("horizon_years", years)

        if goal.target_amount is None:
            builder.leave_absent(
                "target",
                "not_in_the_plan",
                "the member has not put an amount on this goal. A goal with a purpose and no number is the "
                "normal case for courage money (R-132), not an incomplete record.",
            )
        else:
            builder.fill("target", goal.target_amount)
        builder.notes.append(f"funding liquidity as marked: {funding_liquidity(goal) or 'no funding named'}")

    _fill_initial_wealth(builder, positions)
    builder.leave_absent("annual_return", "needs_an_unpublished_assumption", RETURN_IS_AN_ASSUMPTION)
    return builder.done()


def _scenario_generator(
    *,
    member_id: str | None,
    positions: Sequence[Position],
    base_snapshot_id: str | None = None,
    **_: Any,
) -> EnginePlan:
    """The native what-if engine. Its subject is a change, and a change is asked for rather than derived."""
    builder = _Builder("scenario_generator")
    if member_id is None:
        builder.leave_absent(
            "household_id",
            "supplied_by_the_caller",
            "no member was given to this mapping call, so there is nobody for this engine to run for. "
            "Pass member_id to fill it.",
        )
    else:
        builder.fill("household_id", member_id)

    # A numbered baseline EXISTS now (`PlanVersion`, added 3 September 2026 for item 6), so the reason
    # recorded here until then — "prototype2 has no Snapshot ... a history rather than a numbered
    # baseline" — became false the moment that table landed. A reason that outlives its truth is the
    # defect A85 and A105 both are: the member is told something that is no longer so, and nothing fails.
    # Hence two distinct absences below rather than one permanent one.
    if base_snapshot_id is not None:
        builder.fill("base_snapshot_id", base_snapshot_id)
    else:
        builder.leave_absent(
            "base_snapshot_id",
            "supplied_by_the_caller",
            "the numbered plan version to simulate against. `PlanVersion` holds these; a member with no "
            "standing plan has none yet, and the caller passes the id of the one to use rather than this "
            "module choosing — picking a baseline for the member would decide what their what-if is "
            "measured against.",
        )
    builder.leave_absent(
        "field",
        "supplied_by_the_caller",
        "which input the member wants changed. The engine applies a change and reports the consequence; it "
        "does not search for a better one, because searching would be advice (C-01).",
    )
    builder.leave_absent(
        "to_value",
        "supplied_by_the_caller",
        "the value the member wants to try. Theirs to name, and a value proposed here would be the engine "
        "recommending a change rather than costing one (C-01).",
    )
    _fill_initial_wealth(builder, positions)
    return builder.done()


def _score_engine(*, member_id: str | None, regime: dict | None, **_: Any) -> EnginePlan:
    """The analytical Score. A6: not a game mechanic, and C-07 forbids it ever rendering as one."""
    builder = _Builder("score_engine")
    if member_id is None:
        builder.leave_absent(
            "household_id",
            "supplied_by_the_caller",
            "no member was given to this mapping call, so there is nobody for this engine to run for. "
            "Pass member_id to fill it.",
        )
    else:
        builder.fill("household_id", member_id)

    builder.leave_absent(
        "stream",
        "not_in_the_plan",
        "the estate's EventStream contract. prototype2 records Decisions, which are a different shape: a "
        "Decision is a question, a choice and what it touched, not a dated flow of household events.",
    )
    builder.leave_absent(
        "events",
        "not_in_the_plan",
        "as above. Projecting Decisions into the engine's event vocabulary would be an inference nobody "
        "has specified, and D-02's neighbours are the standing warning about exactly that.",
    )
    builder.leave_absent(
        "months_observed",
        "not_in_the_plan",
        "months of observed conduct. It could be computed from the earliest Position.started_on, and that "
        "is the substitution to refuse: months since a position began and months of observed saving are "
        "different quantities, and the engine weights the second at 35 per cent.",
    )
    if regime is None:
        builder.leave_absent(
            "regime",
            "supplied_by_the_caller",
            "the Regime the household's conduct is judged against — the whole RegimeRef contract, not its "
            "id, because the engine reads `crisis_tail` off it. Without one the engine applies no regime "
            "adjustment and says so in its own notes, which is the honest degradation.",
        )
    else:
        builder.fill("regime", regime)
    builder.notes.append(
        "C-07 / R-006 / R-113: this output must never reach a member as a level, a rank or a progress meter"
    )
    builder.notes.append(
        "this plan is never complete, and that is the protection: the engine defaults months_observed to 12 "
        "and would score a household on a history nobody supplied. Do not run it on an incomplete plan."
    )
    return builder.done()


def _portfolio_optimiser(*, member_id: str | None, scope: str, **_: Any) -> EnginePlan:
    """PCP. Produces a Recommendation — ranked instruments — so C-01 gates every call site."""
    builder = _Builder("portfolio_optimiser")
    if member_id is None:
        builder.leave_absent(
            "household_id",
            "supplied_by_the_caller",
            "no member was given to this mapping call, so there is nobody for this engine to run for. "
            "Pass member_id to fill it.",
        )
    else:
        builder.fill("household_id", member_id)

    builder.fill("market", scope)
    builder.fill("speed", OPTIMISER_SPEED)
    builder.fill("optimiser", OPTIMISER_ALGORITHM)
    builder.leave_absent(
        "mandate",
        "not_in_the_plan",
        "PCP solves against a named mandate in PCP/mandates/: bounds per currency, region and asset class, "
        "and a policy floor. A Goal carries five qualitative parameters (R-131) and a purpose. Writing a "
        "mandate from a goal would be inventing an investment policy for the member and then optimising "
        "against it. That was recorded as the C-01 boundary crossed twice over; C-01 is withdrawn (A164) "
        "and the objection survives it unchanged, because inventing a policy and then solving against it "
        "is a fabrication regardless of who is licensed. The gap stays and nothing fills it.",
    )
    builder.notes.append(
        "The output ranks instruments. Until 20 September 2026 the API refused this engine to a member "
        "outright under C-01; C-01 is withdrawn (A164, A166) and nothing now stands between this "
        "computation and the member who queued it."
    )
    return builder.done()


_BUILDERS = {
    "life_balance_sheet": _life_balance_sheet,
    "market_signal": _market_signal,
    "portfolio_optimiser": _portfolio_optimiser,
    "return_estimation": _return_estimation,
    "s_curve_trajectory": _s_curve_trajectory,
    "scenario_generator": _scenario_generator,
    "score_engine": _score_engine,
}


def plan_for(
    engine: str,
    *,
    member_id: str | None = None,
    goal: Goal | None = None,
    positions: Iterable[Position] = (),
    scope: str = DEFAULT_MARKET_SCOPE,
    regime_id: str | None = None,
    regime: dict | None = None,
    publish: bool = False,
    today: date | None = None,
    base_snapshot_id: str | None = None,
) -> EnginePlan:
    """Translate the plan into one engine's declared input names. A39.

    Every key in the returned payload was answered by the member, by the caller, or by engine config. Every
    key that was not is in `absent` with a reason. There is no third category and there is no default.

    `regime_id` and `regime` are both a Regime from an earlier `market_signal` run and are not
    interchangeable: `return_estimation` checks an id, `score_engine` reads `crisis_tail` off the whole
    contract. Two parameters rather than one, so neither call site can be handed the wrong shape.
    """
    if engine not in _BUILDERS:
        raise KeyError(f"no mapping for engine {engine!r}. Known: {', '.join(sorted(_BUILDERS))}")
    return _BUILDERS[engine](
        member_id=member_id,
        goal=goal,
        positions=list(positions),
        scope=scope,
        regime_id=regime_id,
        regime=regime,
        publish=publish,
        today=today or date.today(),
        # Passed in rather than looked up: this module takes no session, by design — every mapper reads
        # the plan through the `positions` and `goal` it is handed. The caller that has a session
        # (`services/runs.py`, or a route) reads the standing version and passes its id.
        base_snapshot_id=base_snapshot_id,
    )


def plan_all(**kwargs: Any) -> dict[str, EnginePlan]:
    """Every engine at once. For a health board, and for reading the whole gap list in one place."""
    return {name: plan_for(name, **kwargs) for name in sorted(_BUILDERS)}


def gap_report(**kwargs: Any) -> list[dict]:
    """Every gap across every engine, flattened. A39's "gaps left visible", made easy to print."""
    return [gap.as_dict() for plan in plan_all(**kwargs).values() for gap in plan.absent]
