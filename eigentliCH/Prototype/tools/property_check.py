"""The four property goals, computed the way a Swiss lender computes them.

The previous pass treated a property goal as a savings target for the full purchase price. That is the
wrong model: property is bought with a mortgage, so a price of 1.5 million is not 1.5 million of saving.
Two tests decide it, and they bind in different places:

  EQUITY (Eigenmittel)     at least 20 % of the price, of which at least 10 % of the price must NOT come
                           from pillar 2 ("harte Eigenmittel", SBVg self-regulation). Pillar 3a counts as
                           hard equity. So pillar 2 may cover at most half the equity requirement.

  AFFORDABILITY            imputed interest on the mortgage + maintenance + amortisation of the portion
  (Tragbarkeit)            above two thirds, all of it at most one third of gross income. Computed at a
                           CALCULATORY rate, not the market rate — that is the whole point of the test.

And an eligibility rule that is not a matter of degree at all:

  OCCUPANCY                pillar 2 and pillar 3a may be drawn only for a property the member LIVES IN as
                           their primary residence. Not for a buy-to-let. Not for a holiday home. Two of
                           the four goals here are exactly those, so for those two the pension money is
                           not "illiquid", it is unavailable.

Every constant below is a banking convention or a self-regulatory floor, NOT a market assumption. They are
gathered in one block because that is where they would live as a published content record with an owner —
`services/` may not carry them as literals for the same reason C-02 exists.
"""

# --- the conventions, in one place, as a content record would hold them -----------------------------
EQUITY_MIN = 0.20            # of purchase price, owner-occupied primary residence
HARD_EQUITY_MIN = 0.10       # of purchase price, may not come from pillar 2
FIRST_MORTGAGE_MAX = 2 / 3   # amortise down to this
AMORTISATION_YEARS = 15      # the portion above two thirds, within this many years
IMPUTED_RATE = 0.05          # kalkulatorischer Zinssatz — a test convention, not a forecast
MAINTENANCE = 0.01           # of purchase price per year
AFFORDABILITY_MAX = 1 / 3    # of gross income

NOW = 2026


def annual_cost_fraction(loan_to_value=1 - EQUITY_MIN):
    """Annual housing cost as a fraction of purchase price, under the affordability test."""
    interest = loan_to_value * IMPUTED_RATE
    amortisation = max(0.0, loan_to_value - FIRST_MORTGAGE_MAX) / AMORTISATION_YEARS
    return interest + MAINTENANCE + amortisation


COST_FRACTION = annual_cost_fraction()


def max_price(income):
    """The most expensive property this income carries. The familiar 'about 5-6x gross'."""
    return AFFORDABILITY_MAX * income / COST_FRACTION


def income_needed(price):
    return price * COST_FRACTION / AFFORDABILITY_MAX


def m(x):
    return f"{x:,.0f}".replace(",", "'")


print(f"convention check: annual cost is {COST_FRACTION:.4%} of price; "
      f"max price is {AFFORDABILITY_MAX / COST_FRACTION:.2f}x gross income\n")

CASES = [
    dict(
        who="Marvin M.", age=23, income=69_550, year=2038, price=1_500_000,
        occupancy="stated as Wohneigentum; his own question asks about subletting",
        hard_today=205_000, pillar3a=17_750, pillar2=0, saving=22_550,
        other_income=0, existing_debt=0,
    ),
    dict(
        who="Renzo T.", age=24, income=24_000, year=2037, price=2_000_000,
        occupancy="owner-occupied assumed",
        hard_today=2_000, pillar3a=0, pillar2=0, saving=30_000,
        other_income=0, existing_debt=0, note="collectibles 45'000 at within_years liquidity, excluded from hard equity",
    ),
    dict(
        who="Elia T.", age=21, income=70_200, year=2040, price=1_500_000,
        occupancy="owner-occupied assumed",
        hard_today=51_000, pillar3a=0, pillar2=0, saving=30_000,
        other_income=0, existing_debt=0,
    ),
    dict(
        who="Levin S.", age=25, income=90_000, year=2034, price=1_100_000,
        occupancy="owner-occupied assumed",
        hard_today=28_000, pillar3a=8_600, pillar2=0, saving=30_000,
        other_income=85_000, existing_debt=0,
        note="partner income 85'000; unmarried, so joint liability without statutory inheritance rights",
    ),
    dict(
        who="Yasmin T.", age=53, income=70_980, year=2036, price=1_500_000,
        occupancy="FERIENHAUS — not a primary residence",
        hard_today=64_000, pillar3a=77_000, pillar2=95_000, saving=0,
        other_income=214_880, existing_debt=782_100,
        note="Elio retires 2033, three years before the target date",
    ),
]

for c in CASES:
    years = c["year"] - NOW
    price = c["price"]
    second_home = "FERIENHAUS" in c["occupancy"] or "subletting" in c["occupancy"]

    print("=" * 96)
    print(f"{c['who']}   goal: {m(price)} in {c['year']}  ({years} years)   income {m(c['income'])}")
    print(f"   occupancy: {c['occupancy']}")
    if c.get("note"):
        print(f"   note: {c['note']}")
    print("=" * 96)

    # ---- test 1: affordability
    own = max_price(c["income"])
    print(f"\n   AFFORDABILITY")
    print(f"     annual cost of a {m(price)} property, at the test's own convention: "
          f"{m(price * COST_FRACTION)}")
    print(f"     one third of their gross income:                                  {m(c['income'] * AFFORDABILITY_MAX)}")
    print(f"     -> income needed to carry {m(price)}: {m(income_needed(price))}  "
          f"({income_needed(price) / c['income']:.1f}x what they earn)")
    print(f"     -> most expensive property their income carries: {m(own)}")
    if c["other_income"]:
        joint = c["income"] + c["other_income"]
        joint_cap = max_price(joint)
        print(f"     -> on joint income {m(joint)}: carries {m(joint_cap)}"
              + (f"   ** {m(price - joint_cap)} SHORT ({price / joint_cap - 1:+.0%}) **" if joint_cap < price
                 else f"   ** SUFFICIENT, {m(joint_cap - price)} of headroom **"))
        if c["existing_debt"]:
            remaining = joint_cap - c["existing_debt"] / (1 - EQUITY_MIN)
            print(f"     -> they already carry {m(c['existing_debt'])} of mortgage, so remaining capacity "
                  f"is about {m(max(0, remaining))} of further property")

    # ---- test 2: equity
    equity_needed = price * EQUITY_MIN
    hard_needed = price * HARD_EQUITY_MIN
    print(f"\n   EQUITY")
    print(f"     required at {EQUITY_MIN:.0%} of price:            {m(equity_needed)}")
    print(f"     of which hard (not pillar 2), min {HARD_EQUITY_MIN:.0%}:  {m(hard_needed)}")

    if second_home:
        print(f"     pillar 2 ({m(c['pillar2'])}) and pillar 3a ({m(c['pillar3a'])}): "
              f"** NOT AVAILABLE — restricted to an owner-occupied primary residence **")
        hard_now = c["hard_today"]
        pension_usable = 0
    else:
        pension_usable = min(c["pillar2"], equity_needed - hard_needed)
        hard_now = c["hard_today"] + c["pillar3a"]
        print(f"     hard equity today (savings + 3a):    {m(hard_now)}")
        print(f"     pillar 2 usable toward equity:       {m(pension_usable)}"
              + (f"  (capped at half the requirement)" if c["pillar2"] > equity_needed - hard_needed else ""))

    hard_at_target = hard_now + c["saving"] * years
    print(f"     hard equity by {c['year']} at {m(c['saving'])}/yr, 0 % return: {m(hard_at_target)}")
    if hard_at_target >= hard_needed:
        # when does the hard-equity floor get met
        if c["saving"]:
            year_met = NOW + max(0, (hard_needed - hard_now) / c["saving"])
            print(f"     -> hard-equity floor met around {year_met:.0f}")
        else:
            print(f"     -> hard-equity floor already met")
    else:
        print(f"     -> hard-equity floor NOT met: {m(hard_needed - hard_at_target)} short")

    total_equity_at_target = hard_at_target + pension_usable
    gap = equity_needed - total_equity_at_target
    print(f"     total equity available by {c['year']}: {m(total_equity_at_target)}   "
          + (f"** {m(gap)} SHORT **" if gap > 0 else f"** {m(-gap)} of headroom **"))

    # ---- which test binds
    print(f"\n   WHICH TEST BINDS")
    equity_ok = gap <= 0
    afford_income = c["income"] + c["other_income"]
    afford_ok = max_price(afford_income) >= price
    if equity_ok and not afford_ok:
        print(f"     INCOME. The equity arrives; the property cannot be carried.")
        print(f"     price this income actually carries: {m(max_price(afford_income))}")
    elif afford_ok and not equity_ok:
        print(f"     EQUITY. The income carries it; the deposit is short by {m(gap)}.")
    elif not equity_ok and not afford_ok:
        print(f"     BOTH.")
        print(f"     price this income actually carries: {m(max_price(afford_income))}")
    else:
        print(f"     NEITHER — on these conventions the goal is reachable.")
    print()
