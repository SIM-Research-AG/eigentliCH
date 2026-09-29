"""Position and Goal — the two things C-09 calls "the plan", and the two the role grid is built from.

`PlanMutable` is the marker the C-09 guard looks for. It is a class, not a list of table names, so a future
plan entity is covered by inheriting rather than by someone remembering to add it to a tuple in the session
listener.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, Enum as SAEnum, Float, ForeignKey, JSON, String, Table, Column, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, new_id, Timestamped

#: The four roles. Spec §4. Their *definitions* on the financial-capital side are D-03 and are NOT here:
#: they are content records loaded from a file, marked provisional. These are identifiers only.
ROLES = ("growth", "income", "stabilisation", "protection")
CAPITAL_TYPES = ("human", "financial")
#: The three units a magnitude may be stated in, and the reason there are now three.
#:
#: ==========================================================================================================
#: THE STOCK UNIT — `chf`, added 1 September 2026
#: ==========================================================================================================
#:
#: **The gap.** Until this line changed, a member could state a flow (`chf_per_year`) or a fraction
#: (`share_of_total`) and **could not state what they have**. "CHF 45,000 in collectibles" and "CHF 2,000 in
#: cash" were unrepresentable, and four engine inputs hung on that absence: `W_R`, `W_L`, `initial_wealth`
#: and `D`. `services/engine_inputs.NO_WEALTH_STOCK` argued — correctly — that capitalising a flow needs an
#: unpublished rate, and that argument only ever bit because nobody had offered the member a stock unit.
#:
#: **Why `chf` and not `chf_stock`, `chf_balance` or `chf_now`.** This vocabulary is *dimensional*:
#: `chf_per_year` is francs per year and `share_of_total` is dimensionless. Francs, full stop, is `chf`.
#: Naming it `chf_balance` would put an interpretation word inside a unit and would immediately imply that
#: its sibling should be `chf_flow_per_year`; two conventions in a three-item list is how the list stops
#: being readable. The dimensional pair is also what makes the flow/stock error visible at the point of
#: reading — `per_year` is right there in the name of the one a rate may not be applied to.
#:
#: **The one hazard `chf` brings, named because it is real.** `chf` is a PREFIX of `chf_per_year`, so
#: `unit.startswith("chf")` and `"chf" in unit` both match the flow. Any site that means "a stock in francs"
#: and writes a prefix test gets the flow as well, which is the A105 defect (a market rate on a salary) in a
#: new coat. Two things guard it: `STOCK_UNITS` below, so no site has to write the literal, and
#: `tests/test_stock_unit.py::test_no_module_matches_a_unit_by_prefix`, which greps the package.
FLOW_UNIT = "chf_per_year"
SHARE_UNIT = "share_of_total"
STOCK_UNIT = "chf"
MAGNITUDE_UNITS = (FLOW_UNIT, SHARE_UNIT, STOCK_UNIT)

#: The units that denote an amount of money **at a point in time** — a balance. A published return rate may
#: be applied to one of these and to nothing else: multiplying a rate by a flow yields francs per year per
#: year, and multiplying it by a share yields a bare number.
#:
#: A tuple with one member on purpose. `unit in STOCK_UNITS` is the test every site uses, so a second stock
#: unit (`eur`, say) is one entry here rather than an `== "chf"` in nine modules — and, as the essay above
#: says, it keeps the `chf`-is-a-prefix-of-`chf_per_year` literal out of the call sites entirely.
STOCK_UNITS = (STOCK_UNIT,)

#: Which side of the balance sheet a stock sits on. See `Position.stock_kind` for the argument against the
#: alternative, which was a negative magnitude.
STOCK_KINDS = ("asset", "liability")
ASSET, LIABILITY = STOCK_KINDS

if len(set(MAGNITUDE_UNITS)) != len(MAGNITUDE_UNITS):  # pragma: no cover - an import-time contract
    raise RuntimeError("a magnitude unit is listed twice")
if not set(STOCK_UNITS) <= set(MAGNITUDE_UNITS):  # pragma: no cover - an import-time contract
    raise RuntimeError("STOCK_UNITS names a unit that is not a magnitude unit")

#: How quickly a position can become money. Added for R-031, which needs a funding liquidity profile to
#: compare against a goal's date and which §4 does not list — "field lists are the minimum, not the
#: maximum", so this is an extension rather than a departure.
#:
#: Bands, not numbers. A threshold in years would be an assumption under C-02 and nobody has published
#: one; these describe a kind of holding, which is a fact the member can state about their own position.
LIQUIDITY = ("immediate", "within_months", "within_years", "illiquid")

#: R-120. The five correlation tags, stored and not interpreted. D-02 forbids shipping the inference that
#: would read them, so this tuple is a shape check and nothing more.
CORRELATION_TAGS = ("client_type", "skill", "reputation_basis", "sector", "time_basis")


#: The stock units as a SQL literal list, so the two CHECK constraints on `positions` are generated from
#: `STOCK_UNITS` rather than repeating it. A constraint whose vocabulary drifts from the tuple is a
#: constraint that refuses a value the API accepts, and the migration that follows the model would inherit
#: the drift — which is landmine 1 of this build's schema history.
_STOCK_UNIT_SQL = ", ".join(f"'{unit}'" for unit in STOCK_UNITS)


class PlanMutable:
    """Marker: writing this entity is a plan mutation and requires a Decision in the same transaction (C-09)."""


#: Many-to-many, and deliberately not constrained to be disjoint across goals — R-030. A single portfolio
#: must be representable against many goals, so a holding funding both "house" and "courage money" is the
#: normal case rather than a data error. Principle 7 in §8 forbids the uniqueness constraint that would
#: force each holding into exactly one goal.
goal_funding = Table(
    "goal_funding",
    Base.metadata,
    Column("goal_id", ForeignKey("goals.id"), primary_key=True),
    Column("position_id", ForeignKey("positions.id"), primary_key=True),
)


#: The seventh field of a goal container: **whose goal it is**. Journey & Design page 2 states the five
#: parameters, then adds the name and the owner and says of the owner "that field is not optional".
#:
#: **A link table rather than a column, because ownership is genuinely plural.** A goal owned by both
#: partners is the normal case in a couple household, and it is the case with consequences: on a closing,
#: goals owned by one member follow that member into their new household, and goals owned by *both* are
#: frozen and flagged for division rather than split by any rule this product is entitled to apply. A
#: nullable `owner_id` column would have to encode "both" as a sentinel, and a sentinel in a foreign key is
#: how the division case ends up being discovered by a member rather than by a test.
#:
#: **It names a `household_member`, not a `member`.** The owner may be a partner with no account
#: (`HouseholdMember.member_id` is nullable), and a household is exactly the scope in which "whose" has an
#: answer. Pointing at `members.id` would have made an unregistered partner unable to own the goal that is
#: about them.
goal_owners = Table(
    "goal_owners",
    Base.metadata,
    Column("goal_id", ForeignKey("goals.id"), primary_key=True),
    Column("household_member_id", ForeignKey("household_members.id"), primary_key=True),
)


class Position(Base, Classified, Timestamped, PlanMutable):
    """A filled cell in the role grid.

    R-020: valid with one row filled. Nothing here is required in groups, and no constraint implies that a
    second position is expected.
    """

    __tablename__ = "positions"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    role: Mapped[str] = mapped_column(SAEnum(*ROLES, name="role"), nullable=False)
    capital_type: Mapped[str] = mapped_column(SAEnum(*CAPITAL_TYPES, name="capital_type"), nullable=False)

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    magnitude_unit: Mapped[str | None] = mapped_column(
        SAEnum(*MAGNITUDE_UNITS, name="magnitude_unit"),
        nullable=True,
        doc="Explicit unit, never inferred. An annualised amount, a share of total and a balance in "
        "francs are not interchangeable, and a magnitude whose unit was guessed is worse than a magnitude "
        "that is absent.",
    )

    stock_kind: Mapped[str | None] = mapped_column(
        SAEnum(*STOCK_KINDS, name="stock_kind"),
        nullable=True,
        doc="Asset or liability, for a magnitude stated in `chf`. Required for one, forbidden for anything "
        "else — see the essay below.",
    )

    tags: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="R-021 / D-02. The five correlation tags are STORED and not read. The rule that would decide "
        "whether two positions are really one is undecided, and shipping a heuristic in its place would "
        "make the decision by accident.",
    )

    #: R-121. Human capital is bounded by hours; financial capital is not. Present on both so the column
    #: exists, required on neither, and only ever collected for human-capital positions by the service layer.
    time_basis: Mapped[str | None] = mapped_column(String(80), nullable=True)

    liquidity: Mapped[str | None] = mapped_column(
        SAEnum(*LIQUIDITY, name="liquidity"),
        nullable=True,
        doc="R-031. Nullable: a member who has not said is not the same as one who said 'immediate', and "
        "guessing from the label would be an inference D-02's neighbours forbid.",
    )

    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="R-122. Inactive positions are never deleted: they remain in history and stay linked from the "
        "decisions that referenced them.",
    )

    # ======================================================================================================
    # DEBT: A LIABILITY IS ITS OWN FIELD, NOT A NEGATIVE MAGNITUDE — 1 September 2026
    # ======================================================================================================
    #
    # `D` is an input of `life_balance_sheet` and no field here held one. The two candidate answers were a
    # negative `magnitude` under the stock unit, and a field of its own. **This is the field, and the
    # negative magnitude is refused at the storage layer** so that there are not two ways to say one thing.
    # Four reasons, in the order they decided it:
    #
    # 1. **`W_R` and `D` are two separate engine inputs, and a sign nets them into one.** The moment
    #    anything sums the `magnitude` column — and `services/engine_inputs.py` now does, because that is
    #    the whole point of the stock unit — a negative liability disappears into the assets it cancels, and
    #    the two numbers the engine asks for cannot be recovered from the one number that comes back. A
    #    balance sheet that has already been netted is not a balance sheet.
    #
    # 2. **One column, three units, three incompatible sign conventions.** `magnitude` is shared with
    #    `chf_per_year`, where a negative plausibly reads as an outgoing payment, and with
    #    `share_of_total`, where a negative is meaningless. A reader of `-45000` would have to know the
    #    unit to know whether they are looking at a debt, an expense or a data-entry error. That is the
    #    inference R-120's "explicit unit, never inferred" exists to forbid, one level further down.
    #
    # 3. **A member can answer "do you owe it or own it"; they cannot be asked to encode a sign.** A minus
    #    key is a UI convention that has to be taught, and a mistyped one is silent — it turns a debt into
    #    an asset with no error anywhere. `stock_kind` makes the question a question.
    #
    # 4. **Two ways of saying the same thing IS the ambiguity.** So the constraints below close both ends:
    #    a franc stock cannot be stored without saying which side of the sheet it is on, a flow or a share
    #    cannot be marked as a liability at all, and a negative franc stock is refused outright. There is
    #    exactly one representation of "I owe 350,000 on the mortgage": `magnitude=350000.0`,
    #    `magnitude_unit='chf'`, `stock_kind='liability'`.
    #
    # **What is deliberately NOT constrained, and why.** Neither `role` nor `capital_type`. A liability
    # still occupies a cell of the grid, and the honest reading is that a debt sits under the role of what
    # it encumbers — a mortgage against the property that stabilises a household is stabilisation. Adding a
    # fifth role for debt would be a change to §4, which is not a decision a column comment gets to make.
    # And a student loan filed under human capital is a member classifying their own life correctly rather
    # than an error, so `capital_type` is left alone; `engine_inputs` sums liabilities across both columns
    # into `D` for exactly that reason, and never into `W_R` or `W_L`.
    __table_args__ = (
        CheckConstraint(
            "(magnitude IS NULL) = (magnitude_unit IS NULL)",
            name="ck_positions_magnitude_has_unit",
        ),
        # Both directions, and NULL-safe. `magnitude_unit = 'chf'` alone evaluates to NULL when the unit is
        # NULL, and SQLite treats a NULL CHECK as satisfied — which would leave `stock_kind` settable on a
        # position that has no magnitude at all. COALESCE forces a boolean on both sides.
        CheckConstraint(
            f"(stock_kind IS NOT NULL) = (COALESCE(magnitude_unit, '') IN ({_STOCK_UNIT_SQL}))",
            name="ck_positions_stock_kind_iff_stock",
        ),
        # Reason 4 above, enforced rather than documented. A liability is a positive amount owed with
        # `stock_kind='liability'`; there is no second encoding.
        CheckConstraint(
            f"COALESCE(magnitude_unit, '') NOT IN ({_STOCK_UNIT_SQL}) OR magnitude >= 0",
            name="ck_positions_stock_is_not_negative",
        ),
    )


class Goal(Base, Classified, Timestamped, PlanMutable):
    """A container: what each franc is for.

    S-04 and R-030 — a reporting and decision layer over whatever is actually held. It does not partition
    holdings and the UI must not imply separate accounts.
    """

    __tablename__ = "goals"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    target_amount: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="What the member says the goal needs. **For a property goal this is the PRICE, and the price "
        "is not what has to be accumulated** — the deposit is, and it is roughly a fifth of it. "
        "`services/property.py` derives the required amount from this and the occupancy; anything that "
        "treats this figure as the sum to save measures a member against a number about five times too "
        "large. `services/illustration.py` reads it as the amount needed and is corrected for property "
        "goals for exactly that reason.",
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The five parameters (S-04, R-131). Nullable: a goal a member has named but not yet characterised is a
    # real goal, and forcing five answers to record one is the onboarding failure this product is against.
    safety: Mapped[str | None] = mapped_column(String(40), nullable=True)
    liquidity_need: Mapped[str | None] = mapped_column(String(40), nullable=True)
    volatility_tolerance: Mapped[str | None] = mapped_column(String(40), nullable=True)
    horizon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    flexibility: Mapped[str | None] = mapped_column(String(40), nullable=True)

    template: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="R-132. 'courage_money' is a first-class template here, not a footnote in the copy.",
    )

    occupancy: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        doc="For a property goal: whether the member will live in it, hold it as a second home, or let "
        "it out. **The only thing that decides whether pension capital may fund the purchase**, and not "
        "derivable from anything else on this row — the six real submissions named property goals "
        "«Wohneigentum», «Eigenheim», «Eigentum kaufen» and «Ferienhaus kaufen», of which only the last "
        "is unambiguous, and one member's goal says Wohneigentum while their own question describes "
        "letting it out. Null on every non-property goal and on a property goal nobody has asked yet; "
        "`services/property.py` reports that it could not be determined rather than assuming the "
        "favourable case. The values are the keys of `occupancy` in "
        "`client/content/property-funding.json` — a String rather than an Enum for the reason A127 gives "
        "about `stated_key`: the closed set lives in the content record, and the service refuses a value "
        "the record does not declare.",
    )

    frozen_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        doc="Set when this goal may no longer be revised. Today the only thing that freezes a goal is a "
        "household closing (A112): a goal owned by BOTH members is frozen and flagged for division, "
        "never split by any rule this product is entitled to apply. `services/goals.revise_goal` refuses "
        "a frozen goal, which is what makes the freeze a fact rather than a label. Deliberately a DATE "
        "and not a boolean: 'frozen since the closing date' is the sentence a member needs, and a "
        "boolean would have to be read alongside the household to produce it.",
    )

    funded_by: Mapped[list[Position]] = relationship(
        secondary=goal_funding,
        doc="R-030. Nullable and overlapping by design — a goal may be unfunded, and two goals may name "
        "the same position.",
    )

    owners: Mapped[list["HouseholdMember"]] = relationship(  # noqa: F821 - resolved by the registry
        secondary=goal_owners,
        order_by="HouseholdMember.created_at, HouseholdMember.id",
        doc="The seventh field: whose goal it is. Empty is a real state and not a valid one — see "
        "`goal_owners` above, and `services/goals.py`, which refuses to create a goal without an owner "
        "once the member has a household. Goals recorded before households existed have none, and the "
        "Befund reports that rather than guessing, because a household that never populated this cannot "
        "be divided cleanly.",
    )
