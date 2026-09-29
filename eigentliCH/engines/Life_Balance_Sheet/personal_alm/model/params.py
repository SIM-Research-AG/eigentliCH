"""Model parameters and illustrative defaults (spec §17 / book Appendix B).

SEAM 4: regime-switching. Parameters are read through `Params.at(regime)` rather
than as bare constants, so returns/vols/growth-rates can later depend on a
slow-moving macro state. v1 is regime-invariant: `at()` returns self.

All defaults are illustrative and chosen to make the system runnable on day one —
NOT empirically fitted. Every value carries a `to_calibrate` intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def earning_ceiling_for_scale(
    legacy_w0: float,
    *,
    floor: float = 50_000.0,
    at_unit: float = 0.75,
) -> float:
    """The `earning_power_max` that reproduces a retired `w0` exactly at `E = N = 1`.

    Inverts `floor + (max − floor)·at_unit = w0`. Exists so the book's cases port by stating the earning scale they
    always meant rather than by four hand-computed ceilings that nobody could later check.

    **Worth noticing rather than burying: four of the five book lives had `w0` above the CIO's 250 000 ceiling** —
    280k, 300k, 340k and 450k against the old 250k ceiling. The ceiling was raised to 500k on 3 August 2026, whose
    lives were written around unusually high earners. Either the range is a statement about clients and the cases
    are deliberate outliers, or the range wants raising; that is a CIO question and this helper does not settle it,
    it just stops the conversion being silent.
    """
    return floor * (legacy_w0 / floor) ** (1.0 / at_unit)


@dataclass
class Params:
    # --- Income (spec §5.1) — redesigned 3 August 2026, step 2 of the state-vector revision ---
    #
    # `w0` is **retired**. It was a scale at `E=N=H=1` and full working time — a quantity nobody has an intuition
    # about — and it was `NO SOURCE` because there was nothing to source it against. Earning power is now derived
    # from the education and network scores and from age, bounded to a range the author can reason about:
    #
    #     earning_power = min · (max/min)^s(E, N) · age_factor(age),   clamped to [min, max]
    #     s(E, N)       = at_unit · E^a · N^b
    #     age_factor    = 1 for age <= peak, else (1 − decline)^(age − peak)
    #
    # **The interpolation is geometric, not additive, and that was a correction.** The first version was
    # `min + (max − min)·s`, which adds the floor unconditionally and therefore starts *everyone* at 50k and climbs:
    # an early-career state of `E = 0.2, N = 0.3` came out at **143 248**, which the author correctly called
    # unrealistic. A geometric interpolation between the same bounds is far more sensitive at the bottom while still
    # hitting both endpoints exactly, and gives a plausible Swiss arc:
    #
    #     near-empty  56k    early career  81k    a few years in 114k
    #     developing 180k    E = N = 1    281k    top of reachable N 444k
    #
    # The lesson is that a floor added to a scaled term is not a floor, it is a *base salary* — the state has to
    # multiply the bounds rather than sit on top of the lower one.
    #
    # `a` and `b` survive, now as exponents of the *skill score* rather than of income. `a + b = 0.9 < 1` still
    # gives mildly decreasing returns to combined human capital.
    earning_power_min: float = 50_000.0    # floor on annual earning power       [CHF/yr]
    earning_power_max: float = 500_000.0   # ceiling on annual earning power     [CHF/yr]
    #: **Ceiling raised 250k -> 500k on 3 August 2026 by CIO decision. `at_unit` stays 0.75, and the first attempt
    #: to "preserve continuity" by moving it to 1/3 was wrong.**
    #:
    #: The reasoning that failed: the raise was asked for because four book lives had earning scales above 250k, so
    #: it looked like an argument about the ceiling alone, and holding `E = N = 1` at the retired `w0`'s 200 000
    #: looked like the conservative choice. The arithmetic says otherwise. `at_unit` is what maps the reachable
    #: state space onto the range: with `E` capped near 1 and `N` reaching about 1.8, `E^a·N^b` peaks near 1.26, so
    #: at 1/3 the top of the range is **239k** and a 500k ceiling is unreachable — the raise would have done
    #: nothing at all.
    #:
    #: At 0.75 the top of the state space reaches about **475k**, which is what a 500k ceiling is for. The cost is
    #: real and is the point: the retired `w0` anchor at `E = N = 1` is not preserved. That anchor was inherited
    #: from `w0`'s semantics and was never the quantity worth preserving — `E = N = 1` is a mid-to-high person, not
    #: a typical one, since `N` reaches roughly twice that.
    #:
    #: **The figure here said 387 500 until 3 August 2026, which was the *additive* value at a 500k ceiling.**
    #: The shape became geometric later the same day (additive put an unrealistic 143k on an early career, a floor
    #: added to a scaled term being a base salary rather than a floor), so the live value is
    #: `50 000 · (500 000/50 000) ** 0.75` = **281 170.66**. Two calibration changes on one day, and the note
    #: describing the first was not revisited after the second — the same failure this file keeps recording.
    #: CIO accepted 281 170.66 on 3 August 2026 in preference to retuning `at_unit` to 0.602 to recover 200 000.
    earning_power_at_unit: float = 0.75
    #: Age at which earning power peaks, and its annual decline after. Age earns its place by capturing what the
    #: capitals structurally cannot: E and N saturate toward a ceiling but never fall, so no combination of them
    #: can produce a declining income. At 2%/yr: about 10% below peak by 60, 18% by 65.
    earning_peak_age: float = 55.0
    earning_decline: float = 0.02          # per year beyond the peak            [1/yr]
    a: float = 0.5          # skill-score exponent on E
    b: float = 0.4          # skill-score exponent on N
    c: float = 1.0          # health exponent in φ(H) = H^c

    # --- Expertise (spec §5.8) ---
    alpha_E: float = 0.30   # learning rate from time            [1/yr]
    beta_E: float = 0.15    # expertise self-compounding         [1/yr]
    kappa_E: float = 1e-6   # learning rate from money           [1/CHF]
    delta_E: float = 0.03   # expertise depreciation             [1/yr]
    K_E: float = 1.0        # expertise ceiling                  [index]

    # --- Network (spec §5.9, §6.1) ---
    alpha_N: float = 0.25   # networking rate from time          [1/yr]
    beta_N: float = 0.20    # network self-compounding           [1/yr]
    kappa_N: float = 1.5e-6  # networking rate from money        [1/CHF]
    delta_N: float = 0.08   # network depreciation (fades fast)  [1/yr]
    #: **The ceiling intercept, and the form around it changed on 25 August 2026 (M80 decision 1).**
    #:
    #: Was `K_N = K_N0 * (1 + lambda_E E + lambda_W W/W_scale)` -- multiplicative, on GROSS wealth, no habit.
    #: The book's eq. 29.11 and Appendix B give `N_bar = N_0 + lambda_E E + lambda_W Omega + lambda_kappa kappa`
    #: -- additive, on NET worth, with the habit term. These are not the same model: for a household with 2.5m
    #: of debt against 5m of property, gross wealth is twice net worth, so the ceiling differed by about a
    #: factor of two. Net worth is the better-motivated argument, because a mortgage does not buy social reach.
    N_0: float = 0.25       # network ceiling intercept          [index]  (Appendix C)
    #: Retained under its old name so nothing that reads it breaks, and equal to `N_0` so the two cannot
    #: disagree. Nothing in the model should use it: the ceiling is additive now, and a multiplicative base has
    #: no place in it.
    K_N0: float = 0.25      # deprecated alias of N_0            [index]
    lambda_E: float = 0.5   # ceiling lift from expertise
    # **Lowered 0.3 -> 0.10 on 3 August 2026 by CIO decision: expertise should dominate.**
    #
    # `K_N = K_N0·(1 + lambda_E·E + lambda_W·W/W_scale)` is what `dynamics.network_ceiling` calls "the single most
    # consequential coupling — competence and resources open doors". At 0.3 per million, wealth overtook *full*
    # expertise as a door-opener above about **1.7m**, which is inside this roster's range (1.1m to 3.0m) — so for
    # most households the model said capital mattered more than competence.
    #
    # The useful quantity is the crossover, not the coefficient. At 0.10 it moves to **5.0m**, so expertise
    # dominates across the whole book with margin: at `hh-0013`'s 3.0m, wealth contributes 0.30 against
    # expertise's 0.50. Wealth still opens doors, clearly and measurably; it is no longer the stronger lever for
    # anyone this system advises. Effect: `hh-0013`'s network ceiling falls 2.40 -> 1.80.
    #
    # Recorded as a *view*, not a measurement. The original ordering was defensible — capital does buy access to
    # rooms competence alone does not — and the choice between them is a claim about how professional networks
    # actually work, which nobody here can settle from data.
    #: **Back to the book's 0.3 on 25 August 2026, and the reason the 0.10 view no longer applies.**
    #:
    #: It was lowered 0.3 -> 0.10 on 3 August because, under the MULTIPLICATIVE form on GROSS wealth, wealth
    #: overtook full expertise as a door-opener at about 1.7m — inside the roster's range. Under the book's
    #: additive form on NET worth that crossover moves out on its own: the same household's mortgage no longer
    #: counts toward the lift. The 0.10 was a correction to a form that has been replaced, and carrying it
    #: forward would be correcting twice for one problem.
    lambda_W: float = 0.3   # ceiling lift from net worth, per W_scale   (Appendix C)
    #: Habit-to-ceiling lift. The least identifiable parameter in the model: §29.3 says it is held small, fixed
    #: from population priors and stress-tested rather than estimated, and §31.7 reports it as a named limit.
    #: It is what makes a spending cut cost something even when the goal is purely financial.
    lambda_kappa: float = 0.10  # ceiling lift from the habit, per swr*W_scale  (Appendix C)
    W_scale: float = 1e6    # wealth normaliser for the ceiling  [CHF]

    # --- The standard-of-living habit (book eq. 29.10, Definition 31.2) ---
    #
    # A stock that tracks recent consumption. NOT a capital: it carries across periods and shapes both the
    # objective and the network ceiling, but it yields no flow return and cannot be drawn on.
    #:
    #: `d(kappa) = alpha_kappa * (C - kappa) dt`. At 0.35 a year the habit closes about a third of the gap to
    #: current consumption annually, so a raise is felt as a new normal within roughly three years.
    alpha_kappa: float = 0.35   # habit adjustment speed toward consumption  [1/yr]  (Appendix C)
    #: Habit intensity in `z = C - h*kappa`, book eq. 30.4.
    #:
    #: **Not a free choice.** §30.3 shows that setting it to one makes the objective unbounded below along its
    #: own equilibrium path; 0.70 removes the singularity and keeps a floor of consumption enjoyed
    #: unconditionally. The book fixes it and reports sensitivity rather than claiming it is measured.
    habit_intensity: float = 0.70   # h in z = C - h*kappa       [dimensionless]  (Appendix C)

    # --- Health (spec §5.10, §5.11) ---
    alpha_H: float = 0.50   # recovery rate                      [1/yr]
    delta_H0: float = 0.02  # baseline health decay              [1/yr]
    eta: float = 0.30       # overwork penalty slope             [1/yr]
    tau_Y_star: float = 0.50  # overwork threshold               [share]
    K_H: float = 1.0        # health ceiling                     [index]

    # --- Returns to invested time (calibration round B, 3 August 2026) ---
    #
    # Time was linear in all three investable uses: 40 h/week of rest restored exactly four times what 10 h did,
    # and nothing capped learning or networking at all. Each now has a shape, and the three shapes differ because
    # the author's claims about the three activities differ (CALIBRATION_life_balance_sheet.md §0A).
    #
    # **Each shape function equals tau at its own reference point**, so the `alpha_*` rates above keep their
    # values and mean the same thing, and no rate had to be rescaled by hand.
    #
    # That pins the level *at* the reference and nowhere else, which is the whole point of a shape: below the
    # reference an hour is worth more than the linear version said, above it less. Measured on the roster when
    # this landed, household trajectories rose **2.4% to 4.9%** on four of five households, because the solver's
    # working point sits below the learning reference (tau_E near 0.05 against a 0.20 scale, where an hour is
    # 1.4x as productive). That is the shape doing what was asked of it, not a normalisation error — but it is a
    # level change, and an earlier draft of this comment wrongly claimed there was none.
    #
    # See `model/dynamics.py` for the three functions and `optim/symbolic.py` for their CasADi twins. The two
    # must agree or the solver optimises a different system from the one being simulated;
    # `tests/test_model_parity.py` is what enforces that, and it found a real bug the first time it ran.
    #
    # Shares are of a 100 h/week productive budget (`ui/output._PRODUCTIVE_WEEK_HOURS`).
    nu_H: float = 0.5         # recovery exponent: diminishing returns, no knee
    tau_H_ref: float = 0.20   # rest reference, 20 h/week, where the shape equals tau
    tau_N_scale: float = 0.10  # networking knee, 10 h/week: "anything more is useless"
    tau_E_scale: float = 0.20  # learning knee, 20 h/week: deep work absorbs more sustained hours

    # --- Markets & portfolio (spec §5.4–5.6) ---
    r_f: float = 0.01       # risk-free rate                     [1/yr]
    mu_M: float = 0.06      # risky expected return              [1/yr]
    sigma_M: float = 0.16   # risky volatility                   [1/√yr]
    # --- Property: the yield/appreciation decomposition, confirmed 3 August 2026 ---
    #
    # The author asked whether appreciation is double-counted against yield. It is not, and the check is worth
    # keeping because the answer is not obvious from either line alone: the two flow to **different stocks**.
    #
    #     dW_R        = mu_R · W_R    appreciation, grows the WHOLE real-asset stock, residence included
    #     asset_yield = y_R · W_inv   rent, from the LET share only, into net cash and thence W_L
    #
    # The asymmetry between those two lines is the substance of step 3 (3 August 2026), and it is deliberate:
    # a home you live in appreciates but does not pay you rent. The yield line read `y_R · W_R` until then.
    #
    # So the decomposition is: **gross yield about 5%, less about 3% of costs, gives the 2% NET yield in `y_R`;
    # appreciation of 3% is separate. Total economic return about 5%.** Confirmed as the intended reading — a 2%
    # *gross* yield would make Swiss property negative-yielding after costs, which it plainly is not.
    #
    # **`y_R` is net, and that is a trap for a later reader.** Adding an explicit ongoing maintenance cost to
    # `net_cash_to_liquid` would double-deduct, because those costs are already inside the 2%. Note `maint_rate`
    # (1% of price) exists but appears *only* in the home-purchase serviceability test, never in the ongoing cash
    # flow — so there is no double deduction today. The 1% there and the ~3% implied here are reconcilable: 1% is
    # maintenance alone, the rest is vacancy, management and property tax.
    mu_R: float = 0.03      # real-asset appreciation            [1/yr]
    sigma_R: float = 0.08   # real-asset volatility              [1/√yr]
    y_R: float = 0.02       # real-asset yield (rent)            [1/yr]
    i: float = 0.02         # mortgage interest                  [1/yr]

    # --- Home purchase / serviceability (spec §7.1) ---
    i_calc: float = 0.05    # stressed serviceability rate       [1/yr]
    xi: float = 0.20        # down-payment fraction

    # --- Pillar 2, the occupational pension (step 4 of the state-vector revision, 3 August 2026) ---
    #
    # **Why this is a state and not a parameter.** It is the largest single asset most Swiss households own by
    # their fifties, it is illiquid in a way no haircut on `W_R` describes, and Swiss law lets it do one thing
    # nothing else in this model can: part-fund a home deposit. The book has none of it — a scan of all 604
    # pages finds one mention of "pillar", in the HoNI material, nothing in Part VI — and its eq. 29.12 deposit
    # test therefore demands the whole down payment from liquid wealth, which is wrong for Switzerland.
    #
    # **Every figure below is an assumption and none is sourced.** They are ordinary-case Swiss values, not this
    # household's plan, and a real client's pension certificate overrides all of them.
    #: Combined employee + employer contribution, as a share of income. The BVG minimum is age-banded on the
    #: *coordinated* salary (7% at 25-34 rising to 18% at 55-65) and most funds exceed it, so a flat rate on full
    #: income is a deliberate simplification: it avoids carrying a coordination deduction and an age band for a
    #: quantity the onboarding will replace with a real figure. Errs high for low earners, low for high earners.
    pension_contribution_rate: float = 0.15   # of income, employee + employer   [1/yr]
    #: Interest credited to the accrued capital. The BVG minimum has been 1.25% since 2024; funds with surplus
    #: credit more. Deliberately NOT the portfolio return: pillar-2 capital earns what the fund credits, which is
    #: a political and actuarial number rather than a market one, and conflating them would let the optimiser
    #: "invest" pension capital it does not control.
    pension_interest: float = 0.0125          # credited interest                [1/yr]
    #: Share of a home deposit that pillar-2 capital may cover. Swiss rules allow withdrawal or pledge for
    #: owner-occupied property only, and **after age 50 the entitlement is capped** at the higher of the balance
    #: at 50 or half the current balance — which is why 0.50 is the conservative figure to carry for a household
    #: at or past that age. Before 50 the full balance is available in principle.
    #:
    #: It applies to an owner-occupied residence and NOT to a second home: a holiday property cannot be financed
    #: from pillar 2 at all. With `W_hol` now its own category (step 3), that distinction is expressible.
    pension_deposit_share: float = 0.50
    #: Age at which the capital becomes drawable as retirement provision. Early withdrawal is possible from 58 in
    #: most funds; 65 is the reference age this model plans against.
    pension_age: float = 65.0

    # --- Pillar 1: AHV, the state pension (added 4 August 2026 on the author's instruction) ---
    #
    # **Its absence made every retirement figure too pessimistic, and the gap was found by using the model on a
    # real household rather than by reading it.** For a single person the maximum AHV is roughly CHF 30 200 a
    # year — against the reference household's 72 000 of spending that is 42% of the whole requirement, so
    # omitting it did not shade an answer, it changed one. The first client dossier produced by this system
    # (Lucerne, Jahrgang 1974) had to carry a disclosure saying so.
    #
    # It is the first income stream in this model that does not descend from a stock. Pillars 2 and 3a are
    # capital that converts; AHV is a claim that pays, with no balance behind it. So there is deliberately no
    # `W_AHV` state — a state would imply drawable capital that does not exist.
    #: Full single pension at the reference age, for a complete contribution record.
    #:
    #: **Thirteen payments, not twelve, and the difference is a whole month of pension.** The BSV publishes the
    #: scale per month -- minimum 1 260, maximum 2 520 -- with the note «13 Auszahlungen» since the 13. AHV-
    #: Altersrente was introduced. This field carried 30 240, which is twelve times the maximum, so every
    #: household in every report was short one payment a year. The figure is now 13 x 2 520, and both it and
    #: the minimum live in `data/social_insurance.json` with their source and vintage; `model/bvg.py` reads
    #: them. It stays a Params field because `dynamics.py` and `optim/symbolic.py` need it as a constant, and
    #: a file read inside the transcription is how two transcriptions drift apart.
    #:
    #: A couple is capped at 150% of the maximum, which this single-person model does not express.
    ahv_full_single: float = 32_760.0         # maximum annual single pension     [CHF/yr]
    #: The minimum of the same scale, 13 x 1 260. Carried so the regressivity of the first pillar can be stated
    #: at both ends rather than only at the top.
    ahv_min_single: float = 16_380.0          # minimum annual single pension     [CHF/yr]
    #: Fraction of a full record the household will have. 1.0 assumes no contribution gaps. Gaps are common —
    #: study abroad, late immigration, unpaid years — and each missing year costs roughly 1/44 of the pension, so
    #: this is a figure worth asking about rather than assuming. The onboarding should read it off the
    #: individual account statement.
    ahv_record_share: float = 1.0
    #: The pension is a function of averaged lifetime income and is **strongly regressive**: it reaches the
    #: maximum at an average income near 90 000 and never exceeds it. So a household earning 149 000 and one
    #: earning 500 000 receive the same AHV. This flag makes that explicit rather than leaving a reader to infer
    #: that a higher income buys a higher first pillar.
    ahv_income_for_max: float = 90_720.0      # average income reaching the max   [CHF/yr]
    #: Reference age. Now 65 for both sexes under AHV 21; early draw from 63 with a permanent reduction, deferral
    #: to 70 with a permanent increase. Neither adjustment is modelled.
    ahv_age: float = 65.0

    # --- Task H1: the exogenous partner (4 August 2026, PLAN_2026-08.md) ---
    #
    # **The partner enters as PARAMETERS, not as a second person.** No new state, no new control, `NX` and `NU`
    # unchanged — which is the whole reason H1 comes before H2. It buys joint taxation, the AHV couple cap and
    # therefore *affordability*, which is the question the real cases keep asking ("can we afford the holiday
    # house"). It deliberately cannot answer who should step back, the care-time trade-off, or the value of the
    # partner's own education: the partner has no controls, so the model has no opinion about their choices. Any
    # report built on H1 must not imply otherwise.
    #
    # **Every default below reproduces the single-person answer exactly** — the M73 rule, which four defaults broke
    # in one revision. `has_partner=False` and a zero income leave every expression algebraically unchanged, and
    # `test_dynamics.py` asserts it rather than trusting it.
    #
    #: Whether a second adult is present at all. Gates the AHV cap; nothing else reads it directly.
    has_partner: bool = False
    #: The partner's gross annual earned income, EXOGENOUS: it is not chosen by the optimiser and does not respond
    #: to the plan. That is the H1 simplification, and it is the honest reading for a partner whose career is not
    #: the subject of the advice. It enters cash flow and the joint tax base, both of which it must.
    partner_income: float = 0.0
    #: The partner's age relative to the subject's, in years. The subject's age is a state that advances, so this
    #: offset is all that is needed to time the partner's AHV correctly. Zero means the same age.
    partner_age_offset: float = 0.0
    #: The partner's AHV record, on the same 0..1 scale and for the same reason.
    partner_ahv_record_share: float = 1.0
    #: Ceiling on the SUM of two married pensions, as a multiple of the maximum single pension. The Swiss rule is
    #: 150%, so summing two individual entitlements overstates a couple's first pillar by up to a third. Applied
    #: with a SMOOTH minimum (`_smooth_min`) rather than `min`, because unlike the earning-power clamp — which
    #: measurement showed never binds — **this ceiling binds by design** for any couple with two full records,
    #: and `symbolic.py` already warns that a clamp which binds often "wants a softmin instead".
    ahv_couple_cap_multiple: float = 1.5
    #: Divisor for joint taxation, expressing Swiss *Vollsplitting*: the couple's combined income is taxed as two
    #: halves at the single tariff, i.e. `factor * base(taxable / factor)`. At the default of 1.0 the expression is
    #: identical to the single-person one, so this is a no-op until a couple is declared. Real cantonal practice
    #: varies — full splitting, partial splitting, or a separate married tariff — so 2.0 is an approximation and a
    #: declared one, not a claim about any particular canton.
    tax_split_factor: float = 1.0

    # --- Pillar 3a, the voluntary tax-privileged pillar (step 4b, 3 August 2026) ---
    #
    # **The first state whose contributions reduce taxable income.** Every other stock in this model lives purely
    # in the wealth block; 3a reaches into `income_tax`, which is why it earns a state rather than being folded
    # into `W_L` with a note. Folding it in would lose all three things that make it worth holding: the
    # deduction, the annual ceiling, and the withdrawal restriction.
    #
    #: The annual ceiling for an employed person with a pension fund. CHF 7 258 in 2026. This is a **flow**
    #: ceiling, which nothing else in this model has — a stock can be any size, but only this much can enter it
    #: per year, and unused room does not carry forward. That is what makes "top up before 31 December" a dated
    #: action rather than a preference, and it is the kind of output the client surfaces already display and the
    #: engine could not previously produce.
    pillar3a_cap: float = 7_258.0             # annual contribution ceiling      [CHF/yr]
    #: What the household actually contributes, before the cap and the age gate bite.
    #:
    #: **Defaults to ZERO, and defaulting it to the ceiling was a real error that the solver suite caught.**
    #: The reasoning for 7 258 was that the deduction makes a full contribution rational for anyone who can
    #: afford it — true as advice, wrong as a default. It made the contribution *mandatory* for every household
    #: in the model, silently diverting 7 258 a year out of liquid wealth into a pot the FI test deliberately
    #: cannot see. On the flagship's five-year horizon that is about 36 000 of drawable wealth removed, and
    #: out-of-sample confidence fell from ~0.84 to between 0.11 and 0.67 depending on the scenario draw. The
    #: optimiser then began buying networking time to compensate, breaking a second test — a consistent
    #: response to a corrupted problem rather than a separate fault.
    #:
    #: This is the fourth unsafe default in this revision, after `W_res = 0.0`, `q_inv = 1.0` and
    #: all-debt-on-residence. The rule they all violate is the same one: **a parameter added to an existing
    #: calculation must default to reproducing the previous answer.** Opting in is the caller's business;
    #: `roster.py` and `cases.py` set it per household, and a real client's figure comes from onboarding.
    pillar3a_contribution: float = 0.0        # intended annual contribution     [CHF/yr]
    #: Credited interest. Bank 3a pays close to nothing; securities 3a earns a market return. 1.5% is a midpoint
    #: and is NOT the portfolio return, for the same reason pillar 2 is not: the household chooses a 3a product,
    #: not a portfolio, and letting the optimiser tilt it would overstate its freedom. NO SOURCE.
    pillar3a_interest: float = 0.015          # credited interest                [1/yr]
    #: Earliest ordinary withdrawal. Five years before reference age, so 60. Earlier withdrawal is permitted for
    #: an owner-occupied home, for self-employment, or on emigration — the same purpose-restricted list pillar 2
    #: carries, and like pillar 2 **not** for a second home.
    pillar3a_age: float = 60.0

    # --- Children as a dynamic cost (9 August 2026, on the author's instruction) ---
    #
    # **Why this is not just another number in `C`.** Before this, a household's children reached the engine only
    # if the client folded them into their own spending figure, which made them a constant for life. They are
    # not: a child costs a different amount at 4 than at 17, and then stops costing anything. The three dossiers
    # of 6 August 2026 all turned on that. The Bern household's whole result rests on 25 000 a year of education
    # ending in 2028 — a fact the engine could not see, so it was reconciled by hand in the report. The Zug
    # household has two children born 2020 and 2022, whose costs on a 26-year horizon rise for fifteen years and
    # then end inside the plan. A constant models neither.
    #
    # **The figures are the published Swiss ones, not estimates.** BFS / Büro BASS, *Kinderkosten in der
    # Schweiz*, Gerfin (Universität Bern), Stutz, Oesch, Strub (Büro BASS), Neuchâtel, March 2009, order number
    # 1053-0900-05. The age split is Tabelle 12, direct consumption costs per month for couple households; the
    # counts without an age split are Tabelle 11.
    #
    # **Three properties of the source travel with the numbers and must not be quietly dropped:**
    #
    #   - **Price base EVE 2000-2005, not 2026.** `child_cost_uprating` below is the single place that converts,
    #     and it defaults to 1.0 — i.e. to the source's own francs — because no index factor has been sourced.
    #     Defaulting it to a guess would put an unsourced number into every household's cash flow.
    #   - **Direct consumption costs only.** The study's basket excludes health-insurance premiums and paid
    #     childcare, which it accounts for separately, and excludes durable goods. So this understates the cash
    #     a household actually spends on a child, and it understates it most for young children in daycare.
    #   - **The age split is estimated only for couple households with at most two children.** The study says so
    #     explicitly. Beyond that it publishes a level and no profile, and this table does the same rather than
    #     extrapolating a shape the source does not support.
    #
    # A figure the household states for itself OVERRIDES all of this — see `child_costs_stated`. The published
    # average is what to use when nobody has said anything, not a correction to what they did say.
    #
    #: Direct consumption cost per child, CHF per MONTH, in the source's own price base, as
    #: (n_children, is_couple) -> (cost while under `child_cost_age_split`, cost from then on).
    #: A single value in both slots means the source gives a level and no age profile for that shape.
    #: Tabelle 12: 1 child 600 / 873; 2 children 1037 / 1911 total, i.e. 519 / 956 each.
    #: Tabelle 11: 3 children 1583 total, i.e. 528 each; lone parent with 1 child 1092.
    child_cost_table: tuple[tuple[int, bool, float, float], ...] = (
        (1, True, 600.0, 873.0),
        (2, True, 519.0, 956.0),
        (3, True, 528.0, 528.0),
        (1, False, 1_092.0, 1_092.0),
    )
    #: The age at which the source's cost band changes, in years. Tabelle 12 splits at 0-10 against 11-21.
    child_cost_age_split: float = 11.0
    #: The age at which a child stops costing the household anything, unless the household states otherwise.
    #: 21 is the upper edge of the source's own band, NOT a claim about when maintenance ends in law.
    child_cost_end_age: float = 21.0
    #: Multiplier from the source's price base to the money the household typed in. **1.0 means "the source's
    #: own francs", which is the honest default until an index factor is sourced.** The rest of this model is
    #: nominal and unindexed (see `pi`), so this converts a 2000-2005 figure once; it does not index over time.
    child_cost_uprating: float = 1.0
    #: Ages of the children at `child_reference_age`, in years. Empty means no children and every expression
    #: below is exactly zero, which is the M73 rule: a parameter added to an existing calculation must default
    #: to reproducing the previous answer.
    child_ages: tuple[float, ...] = ()
    #: The subject's age when `child_ages` was recorded. The children age with the subject, whose age is a state
    #: that advances, so this offset is all that is needed — no new state, `NX` unchanged.
    child_reference_age: float = 0.0
    #: What the household says its children cost, CHF per YEAR, TOTAL for all of them. Overrides the table when
    #: set: a stated figure beats a published average, always. The age profile still applies to it, so a stated
    #: level keeps the shape the source gives.
    child_costs_stated: float | None = None
    #: Whether the household has two adults, for selecting the row of `child_cost_table`. Distinct from
    #: `has_partner`, which gates the AHV couple cap and implies a *married* partner; a lone parent with a
    #: partner who is not a parent is a real shape and the cost table cares about the household, not the marriage.
    child_household_is_couple: bool = True

    # --- Financial independence (spec §7.4, §15.3) ---
    #: Lowered 120 000 -> 90 000 by CIO decision, 3 August 2026. The FI requirement is `(G − rent)/swr`, a small
    #: difference of two large numbers, so it is far more sensitive to `G` than it looks: for the flagship case
    #: at 80 000 of rent this moves the requirement from 1 142 857 to 285 714, i.e. from short by 543 000 to
    #: comfortably funded. Any figure quoted against the old 120 000 is stale.
    G: float = 90_000.0     # desired lifestyle spend (FI target) [CHF/yr]
    #: Net annual yield on a second home — negative, because it carries costs and earns nothing. **Its own
    #: assumption, not derived from `y_R`.** The obvious derivation (`y_R` is +2% net = ~5% gross less ~3%
    #: costs, so zero gross gives −3%) is wrong here: a holiday apartment avoids a let property's vacancy risk,
    #: letting agent and tenant churn, so its cost base is genuinely lighter. Set at −1.5% on the author's
    #: direction, 3 August 2026 — roughly half the let-property cost base. NO SOURCE; a reasoned estimate.
    y_hol: float = -0.015   # net yield on holiday / second homes   [1/yr]
    #: **0.035 -> 0.030 on 25 August 2026 (M80 decision 5).** At 3 % the book's §31.3 statement of "roughly
    #: thirty to one" is true again: 33.3x of required drawable wealth per franc of annual spending, against
    #: 28.6x at 3.5 %. Every requirement in the repo rises by a sixth with it, which is the point rather than a
    #: side effect: the earlier rate made independence look nearer than the book's own arithmetic says it is.
    swr: float = 0.030      # safe withdrawal rate on liquid wealth [1/yr]
    h_res: float = 0.0      # drawable haircut on RESIDENCE equity (the illiquidity trap)
    #: Drawable haircut on the LET share, added 3 August 2026 with the `W_R` split (step 3). `h_res` and this are
    #: the two haircuts that one parameter could not express: at `h_res = 0.0` alone, no real asset was drawable.
    #:
    #: **A participation fraction, like `h_res` — 0.0 means NOT drawable, not "fully drawable".** That reading
    #: has been got backwards in this project before, which is why it is written here rather than inferred.
    #:
    #: **Set to 0.0 by CIO decision, 3 August 2026, and it shipped at 0.85 for about an hour first.** The
    #: reasoning for 0.85 was that let property is genuinely sellable, so it should draw near par. The reasoning
    #: against is decisive and was missed: the FI test is `y_R·W_inv + swr·Ω_draw >= G`, so counting
    #: `q_inv·W_inv` inside `Ω_draw` claims **the rent from the property and a withdrawal against its sale value
    #: at the same time** — the same asset twice. And because `swr` (0.030 since M80 decision 5) exceeds `y_R` (0.02), selling strictly
    #: dominates letting, so there is no state of the world in which both are legitimately available.
    #:
    #: At 0.85 this made Nicolas work-optional immediately (drawable 2 776 000 against 1 142 857 required) where
    #: the book plans against 52-53, and it broke three tests. **Any** value above about 0.25 clears the
    #: requirement, so the choice was never a matter of tuning — it was whether the term belongs at all.
    #:
    #: Keeping it at 0.0 also preserves Definition 7.1's illiquidity trap, which is the reason the drawable
    #: concept exists. The alternative worth revisiting later is to swap the two: drop `y_R·W_inv` and count the
    #: sale value instead, which is coherent, arguably more realistic at `swr > y_R`, and a larger change than
    #: the phantom-rent correction step 3 was scoped for.
    q_inv: float = 0.0
    #: Drawable haircut on second homes. Zero for the same double-counting reason as `q_inv`, and additionally
    #: because a holiday apartment is the *least* likely real asset to be sold to fund a spending plan — it is
    #: held for use, not for yield. Added 3 August 2026 with the holiday category.
    q_hol: float = 0.0

    # --- Objective / macro (spec §9) ---
    # **Wired up and set to zero, deliberately, on 3 August 2026.**
    #
    # `pi` was defined here and **never read anywhere** — it appeared exactly once in the whole engine, on this
    # line. So nothing was inflation-indexed: consumption is a nominal control, `G` a nominal target, and `swr`
    # applies to nominal wealth. The consequence was not neutral. `fi_slack` compares *nominally grown* wealth
    # against a target in *today's* francs, so every FI and retirement test was systematically too easy and every
    # household appeared to reach independence earlier than it would.
    #
    # The author's decision separates the two questions: **build the mechanism, set the rate to zero.** The
    # indexing now exists in `goals.indexed_spend` and is applied on both the numpy and the symbolic paths, so
    # raising this number is a one-line change with working machinery behind it rather than a rewrite. At 0.0 no
    # published figure moves, so nothing had to be re-verified to land it.
    #
    # What it will do when raised: at 1% over `hh-0012`'s ten years its 4m target becomes about 4.4m; at 2%, about
    # 4.9m. This is the first correction in this round that moves *against* the households, which is worth noting
    # after five that moved for them.
    pi: float = 0.0         # spend indexing rate; mechanism live, rate set to zero   [1/yr]
    rho: float = 0.02       # utility discount rate              [1/yr]
    #: **2.0 -> 3.0 on 25 August 2026 (M80 decision 5).** The book chose gamma = 3 precisely so that the Merton
    #: unit test is interior, and that test is its only bridge to standard theory; shipping 2.0 was shipping the
    #: value the book rejects as uninformative.
    gamma: float = 3.0      # CRRA risk aversion
    # `psi`, the leisure-utility weight, was here as `None` and was never read. Deleted 3 August 2026: the live
    # weight is `optim.problem.solve_case(psi=...)`, fed from `Case.psi` and already calibrated per case at
    # 1.0–1.2 in `cases.py`. Two homes for one weight is what made it look uncalibrated when it was not.

    # --- Taxes (SEAM 3, Swiss-style; spec Ch.20 §3) ---
    # Smooth progressive effective income-tax rate: r_max·(1 − e^(−taxable/scale)).
    # Mortgage interest is deductible (taxable = labour + yield − i·D). Wealth tax is
    # a flat cantonal-style rate on net worth. Set rates to 0 to model a tax-free world.
    # Set by the author on 3 August 2026 (calibration round B): 0.20 / 120_000 / 0.002, replacing
    # 0.32 / 120_000 / 0.004. **The basis is the author's decision, not a canton's published rates** — the
    # jurisdiction question was put and answered with values instead, so these are deliberately a Swiss-shaped
    # tax the CIO owns rather than one that belongs to Zurich or Zug. Do not describe them as derived.
    #
    # Implied effective rates, so the choice is checkable rather than buried
    # (effective = r_max·(1 − e^(−t/scale)), on *taxable* income, i.e. after the mortgage-interest deduction):
    #
    #     taxable      effective     tax        was (r_max 0.32)
    #      60 000        7.87%      4 722         12.59%
    #     120 000       12.64%     15 171         20.23%
    #     300 000       18.36%     55 075         29.37%
    #     500 000       19.69%     98 450         31.50%
    #
    # Wealth tax halves: on a 3m net worth, 6 000/yr against 12 000/yr. That is the larger change for the
    # roster's households, several of whose annual contributions are the same order as their wealth tax.
    tax_rate_max: float = 0.20       # asymptotic effective income-tax rate
    tax_income_scale: float = 120_000  # income at which ~63% of r_max is reached [CHF]
    wealth_tax_rate: float = 0.002   # annual wealth tax on net worth [1/yr]

    # --- Correlation (spec §16.3, Q4) ---
    rho_WR: float = 0.30    # correlation ρ(dB_W, dB_R): market/property co-move

    # --- Liquidity floor (spec §4.3, §10) ---
    #
    # `None` means **derive three months of spending** — `0.25 · G` — rather than the previous flat 0.0, which
    # let the solve plan a household down to zero liquid wealth. Decided 3 August 2026. Derived rather than a flat
    # franc figure so it scales with the household: three months for someone spending 55 000 is not three months
    # for someone spending 120 000. A number here overrides it, which is how `cases.py`'s pre-positioned
    # 120 000 protection buffer still works.
    W_buffer: float | None = None   # liquidity floor on W_L; None → 0.25·G   [CHF]

    # --- Numerics (spec §16.3) ---
    dt: float = 1.0 / 12.0  # simulation step                    [yr]
    M: int = 200            # Monte-Carlo scenarios

    @property
    def liquidity_floor(self) -> float:
        """The liquid-wealth floor actually enforced: `W_buffer`, or three months of spending if unset."""
        return 0.25 * self.G if self.W_buffer is None else float(self.W_buffer)

    def at(self, regime: int = 0) -> "Params":
        """SEAM 4: resolve parameters for a macro regime. v1 is regime-invariant."""
        return self
