"""BalanceSheetSnapshot: the household's position, and the mandate derived from it.

This contract is the privacy boundary made concrete. Everything upstream of it is population-level;
everything from here on is one person's.

**Why the mandate lives here.** Decided 2026-07-28, see architecture/DESIGN_snapshot_to_mandate.md. The
Portfolio Optimiser needs a target return curve and allocation bounds. Those are not free parameters to be
typed in: the required return is what makes the household's goal attainable at its stated confidence, and
the position cap follows from the buffer between projected and required wealth. Both are properties of the
household, so the engine that owns the household's economics derives them and emits them here. No adapter
sits between the two engines, and the DAG stays as the manual draws it.

**What is derived and what is not, kept visible.** Liquidity, currency and position caps derive from the
goal. Region, role, capital type, phase and asset class do not, and are investment policy owned by the CIO.
Every bound therefore carries a `source`, because which limits are the household's own economics and which
are house policy are different kinds of fact and must not be presented identically.

**The curve varies by state, and the two halves of it have different owners.**
`MandateCurve.state_dependent` records whether the 25 points vary by regime state. Since M50 they do, and the
distinction the flag used to carry has moved inside the curve rather than disappearing:

- The curve's **level** is derived. Its expectation under the ReturnSet's house view equals the household's
  required return exactly, so the goal still determines what the portfolio must earn.
- The curve's **slope** is CIO policy and is derived from nothing. The household model still carries a no-op
  regime seam (`Params.at()` returns `self`, M5), so a slope claimed as the household's own would be
  manufactured. It lives in `TARGET_CURVE_FLOOR`/`TARGET_CURVE_CEILING` beside the other policy bounds, and
  `derivation` says which half is which in the artefact itself.

So M5 has not been resolved, only routed around: this contract no longer needs the household model to read the
Regime in order to carry a state-varying curve, because the varying part is not claiming to be the household's.
See DECISIONS.md M5 and M50.
"""

from __future__ import annotations

from typing import Any, ClassVar, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.base import (
    BoundSource,
    Contract,
    Phase,
    RegulatedStatus,
    Role,
    Scenario,
    Sourced,
    content_id,
    require_length,
)
from contracts.references import RegimeRef, ReturnSetRef, require_regime_match

STATE_GRID: int = 25

#: The bound dimensions the Optimiser assembles, and whether the household can derive them.
DERIVABLE_DIMENSIONS: frozenset[str] = frozenset({"currency", "liquidity"})
POLICY_DIMENSIONS: frozenset[str] = frozenset(
    {"region", "role", "capital_type", "phase", "asset_class"}
)
ALL_DIMENSIONS: frozenset[str] = DERIVABLE_DIMENSIONS | POLICY_DIMENSIONS


class Bound(BaseModel):
    """One allocation bound, with where it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lower: float = 0.0
    upper: float = 1.0
    source: BoundSource = BoundSource.POLICY
    #: Why this bound has this value. Required for an override, so a departure from policy is never silent.
    rationale: str | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "Bound":
        if self.lower > self.upper + 1e-12:
            raise ValueError(f"bound lower={self.lower} exceeds upper={self.upper}")
        if self.lower < -1e-12:
            raise ValueError(f"bound lower={self.lower} is negative; the mandate forbids shorts")
        if self.source is BoundSource.CURATOR_OVERRIDE and not self.rationale:
            raise ValueError(
                "a curator override must carry a rationale. An unexplained departure from investment "
                "policy cannot be reviewed, and the Decision Record would have nothing to record."
            )
        return self


class PositionCap(BaseModel):
    """The maximum weight one building block may carry.

    Per instrument, not one scalar. Severity is read from each block's published crisis-state return rather
    than assumed, so cash needs no cap while an equity block losing 35 percent in crisis gets a tight one.
    See DESIGN_snapshot_to_mandate.md section 3.4.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: bb_id to cap. Empty means the policy default applies to everything.
    per_instrument: dict[int, float] = Field(default_factory=dict)
    #: Bounds the derived caps from above. Investment policy: the goal cannot see why concentration is
    #: imprudent for reasons beyond itself.
    #:
    #: **Default raised 0.25 -> 1.0 on 2026-08-02, by CIO decision (DECISIONS.md M60).** See
    #: `engines.lbs.derive.DEFAULT_POLICY_CAP` for the measurement: over eight instruments a 0.25 cap forced
    #: at least four positions to exactly the cap, which made the curve fit and the mean-variance comparison
    #: return identical weights. The validator below still refuses 0 and anything above 1, so this remains a
    #: bounded field rather than an unchecked one; 1.0 means "policy adds no ceiling", not "no ceiling exists"
    #: — the derived per-instrument caps in `per_instrument` are unaffected and still bind.
    policy_cap: float = 1.0
    #: False when the goal buffer is negative, in which case the caps are policy rather than derived and the
    #: goal is unreachable from this position.
    derived: bool = True

    @field_validator("policy_cap")
    @classmethod
    def _in_range(cls, value: float) -> float:
        if not 0.0 < value <= 1.0:
            raise ValueError(f"policy_cap={value} must lie in (0, 1]")
        return value

    def for_instrument(self, bb_id: int) -> float:
        """The effective cap: the derived one bounded by policy."""
        return min(self.per_instrument.get(bb_id, self.policy_cap), self.policy_cap)


class MandateCurve(BaseModel):
    """The target return curve the Optimiser fits to: 25 points, annualised decimals.

    `required_return` is the scalar the curve was built from, kept alongside because it is the interpretable
    quantity: the return that makes the goal attainable at the stated confidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    points: tuple[float, ...]
    required_return: float
    #: The CVaR level the household problem was solved at. Recorded, never re-applied: confidence is handled
    #: once, by the engine that owns it. See DESIGN section 5.1.
    epsilon: float
    horizon_years: float
    #: False while the household model is regime-invariant. See DECISIONS.md M5.
    state_dependent: bool = False
    derivation: str = "required return that clears the goal at the solved confidence level"

    @field_validator("points")
    @classmethod
    def _twenty_five(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return require_length(value, STATE_GRID, "mandate curve")

    @model_validator(mode="after")
    def _flat_curve_is_actually_flat(self) -> "MandateCurve":
        """A curve declared state-independent must be constant.

        Without this the flag could claim one thing while the numbers said another, and a reader could not
        trust either.
        """
        if not self.state_dependent:
            spread = max(self.points) - min(self.points)
            if spread > 1e-12:
                raise ValueError(
                    f"the curve is declared state-independent but varies by {spread:.6g} across states. "
                    f"Either set state_dependent=True or emit a constant curve."
                )
        if not 0.0 < self.epsilon < 1.0:
            raise ValueError(f"epsilon={self.epsilon} must lie in (0, 1)")
        return self


class DerivedMandate(BaseModel):
    """What the Optimiser needs, derived from the household where possible.

    The `esg_min` is a household preference rather than a derived quantity, and says so.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    curve: MandateCurve
    position_cap: PositionCap
    #: dimension -> category -> Bound. Only the dimensions actually constrained need appear.
    bounds: dict[str, dict[str, Bound]] = Field(default_factory=dict)
    esg_min: float = 0.0
    reporting_currency: str = "CHF"
    #: bb_ids the household may hold. Empty means the policy universe applies.
    universe: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _dimensions_are_known_and_sourced_honestly(self) -> "DerivedMandate":
        unknown = sorted(set(self.bounds) - ALL_DIMENSIONS)
        if unknown:
            raise ValueError(
                f"bounds names unknown dimension(s) {unknown}. Known: {sorted(ALL_DIMENSIONS)}."
            )
        # A dimension the household cannot derive must not claim to have been derived. This is the check
        # that keeps the honest labelling of section 5.5 from decaying into a rubber stamp.
        for dimension in POLICY_DIMENSIONS & set(self.bounds):
            for category, bound in self.bounds[dimension].items():
                if bound.source is BoundSource.DERIVED:
                    raise ValueError(
                        f"bounds.{dimension}.{category} claims source 'derived', but {dimension} cannot be "
                        f"derived from the household model. It is investment policy: mark it 'policy' or "
                        f"'curator_override'."
                    )
        return self

    def sources_in_use(self) -> dict[str, int]:
        """How many bounds came from each source. For the Recommendation's explanation."""
        counts: dict[str, int] = {}
        for categories in self.bounds.values():
            for bound in categories.values():
                counts[bound.source.value] = counts.get(bound.source.value, 0) + 1
        return dict(sorted(counts.items()))


class HouseholdPosition(BaseModel):
    """The wealth and capital stocks, as the Life Balance Sheet models them.

    Wealth is split three ways because one scalar cannot tell an honest financial story: the residence you
    live in is not spendable. `drawable` is the quantity a goal is actually tested against.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Liquid financial wealth: cash plus the marketable portfolio. The stock the Optimiser allocates.
    W_L: float
    #: Real and illiquid assets: property, private stakes.
    W_R: float
    #: Debt.
    D: float
    #: Haircut applied to (W_R - D) when computing drawable wealth. Near zero for a residence.
    h_res: float = 0.0
    #: Person-scoped saturating capitals.
    E: float | None = None
    N: float | None = None
    H: float | None = None

    @property
    def net_worth(self) -> float:
        """Omega = W_L + W_R - D."""
        return self.W_L + self.W_R - self.D

    @property
    def drawable(self) -> float:
        """Omega_draw = W_L + h_res * (W_R - D). The illiquidity trap, made explicit."""
        return self.W_L + self.h_res * (self.W_R - self.D)


class GoalRef(BaseModel):
    """The goal the mandate serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(description="fi | home | company | retirement")
    mode: str = Field(description="at_deadline | by_deadline")
    horizon_years: float
    epsilon: float
    target: float | None = None
    #: Projected wealth at the confidence level minus the requirement. Negative means unreachable.
    buffer: float | None = None
    feasible: bool = True

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in {"fi", "home", "company", "retirement"}:
            raise ValueError(f"unknown goal kind {value!r}")
        return value


class Costates(BaseModel):
    """The household problem's dual variables: the marginal value of each stock.

    `lam_W` is the costate on `W_L`, so it prices a franc of the marketable portfolio at the margin. The
    ratios against `lam_E` and `lam_N` are the household's own exchange rates between saving and
    self-investment, and they say how *ambitious* a mandate should be: a household whose expertise is worth
    far more at the margin than its portfolio is better served investing in itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lam_W: float
    lam_E: float | None = None
    lam_N: float | None = None

    def portfolio_over_expertise(self) -> float | None:
        if self.lam_E in (None, 0.0):
            return None
        return self.lam_W / self.lam_E


class BalanceSheetSnapshot(Contract):
    """One household's position at a point in time, plus the mandate derived from it.

    The first per-user contract, and therefore the privacy boundary. It references the Regime it was
    computed under rather than embedding it.
    """

    CONTRACT_NAME: ClassVar[str] = "BalanceSheetSnapshot"
    CONTRACT_VERSION: ClassVar[str] = "0.1.0"
    REGULATED: ClassVar[RegulatedStatus] = RegulatedStatus.EDUCATION

    #: Pseudonymous household identifier. Never a name: this contract crosses process boundaries.
    household_id: str
    position: HouseholdPosition
    goal: GoalRef
    costates: Costates
    mandate: DerivedMandate
    regime: RegimeRef
    #: Scalars a reader will see, each with its provenance.
    diagnostics: dict[str, Sourced] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _internally_consistent(self) -> "BalanceSheetSnapshot":
        if self.goal.epsilon != self.mandate.curve.epsilon:
            raise ValueError(
                f"the goal was solved at epsilon={self.goal.epsilon} but the mandate curve records "
                f"{self.mandate.curve.epsilon}. Confidence is handled once: the curve must carry the level "
                f"the household problem was actually solved at."
            )
        # The goal's deadline and the curve's horizon are different quantities, and an earlier version of this
        # validator wrongly required them to agree.
        #
        # `goal.horizon_years` is when the money is needed: ten years, say. `curve.horizon_years` is the basis
        # the *return* is expressed on, which must match the ReturnSet the Optimiser reads, and that is
        # annual. A ten-year goal is served by an annualised required return, so 10 and 1 are both correct and
        # describe different things. Requiring equality would have forced either a ten-year ReturnSet, which
        # does not exist, or a nonsensical ten-year mandate curve.
        if self.mandate.curve.horizon_years > self.goal.horizon_years + 1e-9:
            raise ValueError(
                f"the mandate curve is expressed on a {self.mandate.curve.horizon_years}y basis but the goal "
                f"falls due in {self.goal.horizon_years}y. A return basis longer than the goal's own deadline "
                f"cannot be what the goal requires."
            )
        if not self.goal.feasible and self.mandate.position_cap.derived:
            raise ValueError(
                "the goal is marked infeasible, so the position caps cannot be derived from its buffer. "
                "Set position_cap.derived=False and fall back to the policy cap."
            )
        return self

    def snapshot_id(self) -> str:
        """Content-addressed identity, so an unchanged household produces an unchanged id."""
        return content_id("BSS", self.model_dump(mode="json"))

    def require_returnset(self, returnset: ReturnSetRef) -> None:
        """Refuse a ReturnSet from a different Regime, or a different horizon.

        The manual's invariant, checked from the snapshot's side because the snapshot is what carries the
        household's own regime vintage.
        """
        require_regime_match(returnset.regime_id, self.regime.regime_id)
        if abs(returnset.horizon_years - self.mandate.curve.horizon_years) > 1e-9:
            raise ValueError(
                f"the mandate is on a {self.mandate.curve.horizon_years}y horizon but the ReturnSet is "
                f"estimated on {returnset.horizon_years}y. Use the ReturnSet published for this horizon: a "
                f"per-state return is not re-scaled across horizons."
            )
