"""State variables (spec §3).

SEAM 2: wealth/capital separation. The wealth block {W_L, W_R, D} is
household-scoped; the capitals {E, N, H} are person-scoped. v1 holds exactly one
person, so the households extension (Chapter 20 §2) becomes "append a PersonState"
rather than a rewrite of every equation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .expertise import Expertise
from .venture import Venture


@dataclass
class HouseholdWealth:
    """Financial wealth, split three ways because one scalar cannot tell an
    honest financial story (spec §3): liquid, real/illiquid, and debt."""

    W_L: float  # liquid financial wealth (cash + marketable portfolio), CHF ≥ 0
    W_R: float  # real / illiquid assets, TOTAL (property, private stakes), CHF ≥ 0
    D: float    # debt (mortgage etc.), CHF ≥ 0
    #: The residence's share of `W_R` — the part lived in rather than let. Added 3 August 2026 (step 3 of
    #: the state-vector revision). `W_R` stays the total and `W_inv` is derived, rather than splitting into
    #: two peers, because `W_R` means what it always meant and ~130 references keep working; only the six
    #: places where `y_R` meets the stock change. See `PLAN_2026-08.md` §0B.
    #:
    #: **`None` means "all of it is the residence", not "none of it is".** Defaulting to `0.0` would have
    #: reclassified every existing household's home as let property — earning it rent it does not produce and
    #: making it fully drawable, which is the exact error this step removes, inverted. The conservative default
    #: is the one that assumes a real asset is lived in until someone says otherwise.
    W_res: float | None = None
    #: Second homes — a holiday apartment and the like. **A third category, added 3 August 2026 on the author's
    #: direction, and the only one with a NEGATIVE net yield**: it carries costs and produces no income, so it
    #: is an asset that consumes cash rather than generating it. Defaults to zero, so a household that has not
    #: declared one has none.
    W_hol: float = 0.0
    #: Pillar-2 capital: the accrued occupational-pension balance. Added 3 August 2026 (step 4).
    #:
    #: **Deliberately outside `W_R` and outside `net_worth`'s spendable reading.** It is not a real asset, not
    #: liquid, and not drawable before `pension_age` — but it is not nothing either, because Swiss law lets it
    #: part-fund an owner-occupied home. That single permitted use is why it earns a state rather than sitting in
    #: a note: no haircut on another stock can express "unavailable for everything except one specific purchase".
    #:
    #: Household-scoped like the rest of this block, which is a simplification: in Switzerland each working
    #: person has their own fund. For the single-person v1 the distinction is invisible; when the households
    #: extension lands this wants moving to `PersonState` beside `E`, `N` and `H`.
    W_P: float = 0.0
    #: Pillar-3a capital. Added 3 August 2026 (step 4b). Like `W_P` it is wealth-tax exempt and therefore outside
    #: `net_worth`; unlike `W_P` its *contributions* reduce taxable income, which makes it the only stock here
    #: that touches the tax function rather than only the wealth block.
    W_3a: float = 0.0

    def __post_init__(self) -> None:
        if self.W_res is None:
            # Everything not declared as holiday property is the residence. The conservative reading stays
            # conservative with three categories: undeclared means lived in, never let.
            self.W_res = max(0.0, self.W_R - self.W_hol)

    @classmethod
    def from_shares(cls, *, W_L: float, W_R: float, D: float,
                    own_use_share: float = 1.0, holiday_share: float = 0.0) -> "HouseholdWealth":
        """Build from *fractions* of `W_R` rather than amounts — how a multi-unit property is actually described.

        "A five-unit building and I live in one" is `own_use_share = 0.2`, and it stays right as the property
        appreciates because `mu_R` moves all parts together. **Amounts are what the state carries and shares are
        what a human declares**, which is both options rather than a choice between them: the composition has to
        be able to change — buying a holiday apartment moves `W_L → W_hol`, letting a unit moves `W_res → W_inv`
        — and a goal that fires has to change something.

        The let share is the remainder, `1 − own_use − holiday`, deliberately: three shares that must sum to one
        cannot drift apart if only two are stored.
        """
        if own_use_share < 0.0 or holiday_share < 0.0 or own_use_share + holiday_share > 1.0 + 1e-9:
            raise ValueError(
                f"own_use_share={own_use_share} and holiday_share={holiday_share} must each be >= 0 and sum to "
                f"<= 1 — the let share is the remainder and cannot be negative."
            )
        return cls(W_L=W_L, W_R=W_R, D=D,
                   W_res=own_use_share * W_R, W_hol=holiday_share * W_R)

    @property
    def W_inv(self) -> float:
        """Income-producing real assets: the LET share, `W_R − W_res − W_hol`.

        The book already had this as `W_R^inv` in its notation table and at eq. 29.15 — and then computed its
        flagship case without it, crediting a lived-in residence with rent. This property is what stops that.

        Derived as the remainder rather than stored, so the three categories sum to `W_R` by construction and no
        constraint is needed to hold them consistent. Clamped at zero so a `W_res` and `W_hol` that together
        exceed `W_R` cannot manufacture negative rent.
        """
        return max(0.0, self.W_R - float(self.W_res or 0.0) - self.W_hol)

    @property
    def net_worth(self) -> float:
        """Ω = W_L + W_R − D (spec §3, eq. 3.2). Unaffected by the split: a home is worth what it is worth.

        **`W_P` is deliberately excluded, and the reason is fiscal rather than conceptual.** This property feeds
        `dynamics.wealth_tax`, and Swiss pillar-2 capital is **exempt from wealth tax**. Including it here would
        levy a tax that does not exist, every year, on the largest asset a mid-career household owns — a
        systematic overstatement of the tax burden that would look like prudence.

        For the household's economic position including pension provision, use `total_wealth`.
        """
        return self.W_L + self.W_R - self.D

    @property
    def total_wealth(self) -> float:
        """Everything the household owns, pillar-2 capital included, net of debt.

        Not a tax base and not spendable — see `net_worth` for the first and `drawable` for the second. This is
        the figure a client means by "what am I worth", and it is the one a retirement funding ratio should
        compare against, because pension provision is precisely what retirement is funded from.

        Both privileged pillars are included. Neither is in `net_worth`, because both are exempt from Swiss
        wealth tax and that property is the tax base.
        """
        return self.W_L + self.W_R + self.W_P + self.W_3a - self.D

    def pension_available_for_deposit(self, share: float) -> float:
        """How much pillar-2 capital may go toward an owner-occupied home deposit.

        Swiss rules permit withdrawal or pledge for owner-occupied property only, capped after age 50 at the
        higher of the balance at 50 or half the current balance — so `share = 0.50` is the conservative reading
        for a household at or past that age. `share` is passed in rather than read from `Params` here because
        this object holds no parameters; `Params.pension_deposit_share` is the policy value.

        **A holiday home cannot be financed from pillar 2 at all.** Since step 3 gave second homes their own
        state, that restriction is now expressible rather than merely true — a caller funding `W_hol` must not
        call this.
        """
        return max(0.0, share) * max(0.0, self.W_P)

    def drawable(self, h_res: float = 0.0, q_inv: float = 0.0, q_hol: float = 0.0) -> float:
        """Drawable wealth: W_L plus each real category at its own haircut, net of its share of debt (book eq. 29.15).

        **THREE haircuts, one per category, since 3 August 2026** — `h_res` the residence, `q_inv` let property,
        `q_hol` second homes. It began as one. This was `W_L + h_res·(W_R − D)` — a single haircut on
        the whole real stock, shipping at `h_res = 0.0`, which made *no* real asset drawable. That could not
        hold a residence at zero and let property above it, which is the distinction the split exists to draw.
        `h_res` keeps its meaning (the residence, ≈ 0: the illiquidity trap that separates net worth from
        independence) and `q_inv` carries the let share, which is genuinely sellable.

        **Debt is apportioned pro rata across the two parts, and the first two attempts at this were wrong.**

        Attempt one attached all debt to the residence: `h_res·(W_res − D)`. `test_state.py` caught it —
        `drawable(h_res=1.0)` returned **−200 000**, because the debt (1.8m) exceeds the residence (1.0m) and the
        term went negative. The old single-haircut form never did that: it netted debt against the *whole* stock.

        So each part carries its share of the debt, `D·W_res/W_R` and `D·W_inv/W_R`. Three properties follow, and
        all three are the point:

        - `W_res = W_R` (so `W_inv = 0`) reduces to `W_L + h_res·(W_R − D)` — the pre-split formula, to the franc.
        - `h_res = q_inv = 1.0` gives `W_L + W_R − D` — full net worth, which is what "no haircut" should mean.
        - neither term can go negative from debt alone, because each is netted only against its own share.

        The book's own form is cleaner and needs a state this does not have: `Ω_draw = W_L + q_R·W_R^inv −
        D_unsecured` with `q_home = 0`, where the home and its mortgage drop out *together*. Pro rata is the
        closest honest approximation with a single `D`; a real `D_res`/`D_unsecured` split is a later step.

        **`q_inv` defaults to 0.0, not 1.0, and that was a third error caught by the same test.** At 1.0 any
        caller who did not pass it treated the entire let stock as spendable cash — 4 600 000 drawable where the
        pre-split code gave 600 000. Both haircuts now default to "not drawable", so the conservative reading is
        what you get by saying nothing and every relaxation is explicit at the call site.

        **All three ship at 0.0**, so only `W_L` is drawable. `q_inv` was 0.85 for about an hour before the CIO
        set it to zero: the FI test is `y_R·W_inv + swr·Ω_draw >= G`, so counting `q_inv·W_inv` inside `Ω_draw`
        claims the rent *and* a withdrawal against the sale value of the same asset. See `Params.q_inv`.
        """
        W_res = float(self.W_res or 0.0)
        if self.W_R <= 0.0:
            # No real assets, so there are no shares to apportion. The old formula gave `W_L + h_res·(0 − D)`
            # here, and this reproduces it rather than inventing a different answer for the degenerate case.
            return self.W_L - h_res * self.D
        res_share = W_res / self.W_R
        inv_share = self.W_inv / self.W_R
        hol_share = self.W_hol / self.W_R
        return (self.W_L
                + q_inv * (self.W_inv - self.D * inv_share)
                + q_hol * (self.W_hol - self.D * hol_share)
                + h_res * (W_res - self.D * res_share))

    def copy(self) -> "HouseholdWealth":
        return HouseholdWealth(self.W_L, self.W_R, self.D, self.W_res, self.W_hol)


@dataclass
class PersonState:
    """Per-person saturating capitals (spec §3): expertise, network, health, and age.

    **`age` joined the state on 3 August 2026 (step 1 of the state-vector revision).** It lived on `Case` only, so
    the dynamics could not see it — which made an age-dependent earning profile impossible to express. Nothing
    reads it yet: this step is deliberately inert, so that the state-vector surgery can be verified on a change
    whose correct outcome is "every published number identical". See `PLAN_2026-08.md` §0B.

    It evolves trivially — `d(age)/dt = 1` — so it is a state in the bookkeeping sense rather than a dynamical one.
    It is here rather than on `HouseholdWealth` because age is a property of a person, and the model is built to
    take more than one person later.
    """

    E: Expertise  # expertise / human capital (index ≥ 0)
    N: float      # network / social capital (index ≥ 0)
    H: float      # health / energy capital (index ∈ [0, 1])
    #: Years. Defaults to 40 so every existing construction site keeps working unchanged; a caller who cares
    #: passes it. The default is deliberately a plausible mid-career figure rather than 0.0, because a silent
    #: zero would make an age-dependent income function produce nonsense the moment step 2 lands.
    age: float = 40.0
    #: The standard-of-living habit, in CHF a year. **A stock, and deliberately NOT a capital** (book
    #: Definition 31.2): it carries across periods and shapes both the objective and the network ceiling, but
    #: it yields no flow return and cannot be drawn on. It tracks recent consumption through
    #: `d(kappa) = alpha_kappa * (C - kappa) dt`, book eq. 29.10.
    #:
    #: **`None` means "start at the household's own consumption", not "start at zero".** A zero habit would
    #: hand the optimiser a free lunch in its first years -- `z = C - h*kappa` would equal `C` -- and then
    #: charge for it later, which is the opposite of what a habit is. Callers that know the household's
    #: spending pass it; `cases`/`onboarding` do.
    kappa: float | None = None
    ventures: list[Venture] = field(default_factory=list)  # active ventures (Q2)

    def copy(self) -> "PersonState":
        return PersonState(
            E=self.E.copy(), N=self.N, H=self.H, age=self.age, kappa=self.kappa,
            ventures=[v.copy() for v in self.ventures],
        )


@dataclass
class State:
    """Full state x(t): a shared wealth block plus one or more persons."""

    wealth: HouseholdWealth
    persons: list[PersonState] = field(default_factory=list)

    @classmethod
    def individual(
        cls,
        *,
        W_L: float,
        W_R: float,
        D: float,
        E: float,
        N: float,
        H: float,
        age: float = 40.0,
        kappa: float | None = None,
        W_res: float | None = None,
        W_hol: float = 0.0,
        W_P: float = 0.0,
        W_3a: float = 0.0,
        own_use_share: float | None = None,
        holiday_share: float | None = None,
    ) -> "State":
        """Convenience constructor for the v1 single-person case.

        `age` is optional and defaults to 40 so that every existing call site is unaffected — which is what makes
        step 1 of the state-vector revision verifiable as a no-op.

        `W_res` is optional and `None` means "all of `W_R` is the residence", which is the *conservative* reading
        and preserves pre-split behaviour exactly. See `HouseholdWealth.W_res` for why the other default would
        have been the original bug inverted.

        `W_P` and `W_3a` were added on 4 August 2026, when task P2 found that this constructor could not express
        two of the eight state fields the onboarding schema *requires*. They joined the state vector in steps 4 and
        4b and this convenience constructor was never widened, so every caller silently got zero pension capital —
        harmless for the worked lives, which have their own figures, and wrong for any real submission. Both
        default to 0.0, so every pre-existing call site is unaffected.

        Pass **either** amounts (`W_res`, `W_hol`) **or** shares (`own_use_share`, `holiday_share`), not both.
        Shares are the natural way to describe a multi-unit property; amounts are what the state carries.
        """
        if own_use_share is not None or holiday_share is not None:
            if W_res is not None or W_hol:
                raise ValueError(
                    "pass either amounts (W_res, W_hol) or shares (own_use_share, holiday_share), not both — "
                    "two descriptions of one split is how they drift apart."
                )
            wealth = HouseholdWealth.from_shares(
                W_L=W_L, W_R=W_R, D=D,
                own_use_share=1.0 if own_use_share is None else own_use_share,
                holiday_share=0.0 if holiday_share is None else holiday_share,
            )
            # `from_shares` describes the PROPERTY split and knows nothing about the pension stocks, so they are
            # attached afterwards. Both default to 0.0, which is what every pre-existing call site produced.
            wealth = replace(wealth, W_P=W_P, W_3a=W_3a)
        else:
            wealth = HouseholdWealth(W_L=W_L, W_R=W_R, D=D, W_res=W_res, W_hol=W_hol,
                                     W_P=W_P, W_3a=W_3a)
        return cls(
            wealth=wealth,
            persons=[PersonState(E=Expertise.scalar(E), N=N, H=H, age=age, kappa=kappa)],
        )

    @property
    def person(self) -> PersonState:
        """The sole person (v1). Raises if the household is not a single individual."""
        if len(self.persons) != 1:
            raise ValueError(
                f"State.person is v1 single-person sugar; household has "
                f"{len(self.persons)} persons — index self.persons directly."
            )
        return self.persons[0]

    @property
    def net_worth(self) -> float:
        return self.wealth.net_worth

    @property
    def total_wealth(self) -> float:
        """Pension-inclusive wealth. Proxied here because `net_worth` is, and a caller reaching for one will
        reach for the other — leaving it only on `HouseholdWealth` cost an `AttributeError` on first use."""
        return self.wealth.total_wealth

    def copy(self) -> "State":
        return State(
            wealth=self.wealth.copy(),
            persons=[p.copy() for p in self.persons],
        )
