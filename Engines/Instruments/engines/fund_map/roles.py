"""The four role profiles: Gain, Income, Stabilisation, Protection.

These are the stored calibration artefact. The eight block profiles are computed on the
way here and retained as a diagnostic -- manual section 11.3 encodes six statements about
block shapes as regression assertions, and those cannot run against roles -- but what the
engine publishes, and what an instrument borrows from, is the four.

**A role is an equal-weight composite of its blocks, aggregated at the phase level.**
Two details in that sentence are load-bearing:

*Equal weight*, because nothing in the record says otherwise. A capitalisation or
liquidity weighting would be a judgement smuggled in as arithmetic. The weights are data
on :class:`RoleSpec` so a CIO override is a configuration change carrying a reason and a
date, exactly as section 11.4 requires of the role mapping itself.

*At the phase level, not the state level.* The five phase means are averaged first and the
composite is then interpolated onto the 25-state axis. Averaging the 25-state profiles
instead would give a different answer, because pchip is not linear in its ordinates -- its
slope limiter depends on the data it is given. Averaging first is also the one with a
meaning: it is what an equal-weight holding of those blocks actually returned in that
phase.

**Long rate carries no role and is excluded.** It is a rate, not a holding; government
bond total return is what an investor actually earned.
"""

from __future__ import annotations

from dataclasses import dataclass

from engines.fund_map import numerics as num
from engines.fund_map.calibrate import (
    METHOD_STRENGTH,
    PHASE_KNOTS,
    BlockProfile,
    Method,
    state_axis,
    state_methods,
    state_observation_counts,
)
from engines.fund_map.phases import PHASE_NAMES

#: The four roles, in the order the manual lists them.
ROLE_NAMES: tuple[str, ...] = ("gain", "income", "stabilisation", "protection")


@dataclass(frozen=True)
class RoleSpec:
    """Which blocks make up a role, and in what proportion."""

    role: str
    weights: dict[str, float]
    basis: str

    def normalised(self) -> dict[str, float]:
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError(f"role {self.role!r} has non-positive total weight")
        return {k: v / total for k, v in self.weights.items()}


#: The mapping from manual section 11.4, which derives it from the measured phase
#: profiles. The evidence sets the default; a CIO override replaces an entry here and
#: carries its reason in ``basis``.
#:
#: **Income is a CIO override** (review R-001, owner 29.09.2026): real estate 75 %, equity
#: 25 % (candidate A of :data:`INCOME_CANDIDATES`). The role map enters the calibration's
#: parameter hash, so this moved the calibration from `CAL-092efd097adb0b26` (real
#: estate alone, :data:`ROLE_MAP_BEFORE_R001`) to `CAL-69d9d1ee5245ac71`; the earlier one
#: stays in the live store for comparison and is reproduced from the earlier map by the
#: suite.
ROLE_MAP: tuple[RoleSpec, ...] = (
    RoleSpec("gain", {"equity": 1.0},
             "Equity is nearly linear in the environment. Gain, and nothing else."),
    RoleSpec("income", {"real_estate": 0.75, "equity": 0.25},
             "CIO override, review R-001, owner 29.09.2026: real estate 75 %, equity 25 %. "
             "Real estate pays a distribution on the let share, the equity quarter is the "
             "dividend-paying share of an income sleeve. Real estate alone sat within 0.2 "
             "to 0.3 points of Stabilisation in expansion and boom; with the equity quarter "
             "Income is clearly above Stabilisation there and further below it in crisis. "
             "Not Stabilisation: it fails in precisely the state a stabiliser exists for."),
    RoleSpec("stabilisation", {"short_rate": 1.0, "commodities": 1.0, "agriculture": 1.0},
             "All three peak or hold up in contraction: they pay before the damage, not "
             "during it. The short rate is also the risk-free proxy in the optimiser."),
    RoleSpec("protection", {"gov_bonds": 1.0, "gold": 1.0},
             "Both pay in crisis. Government bonds for the flight-to-safety jump rather "
             "than the coupon; gold because it peaks in crisis and is negative in boom."),
)

#: The role map before review R-001: Income was real estate alone. It produced
#: `CAL-092efd097adb0b26`, the calibration every id up to 28 September 2026 was built on.
#: Kept so that calibration can be reproduced and compared (``tests/test_role_map.py``);
#: nothing publishes from it.
ROLE_MAP_BEFORE_R001: tuple[RoleSpec, ...] = tuple(
    RoleSpec("income", {"real_estate": 1.0},
             "Real estate pays a distribution on the let share. Not Stabilisation -- it "
             "fails in precisely the state a stabiliser exists for.")
    if spec.role == "income" else spec
    for spec in ROLE_MAP
)

ROLE_BY_NAME = {r.role: r for r in ROLE_MAP}


#: The Income compositions put to the owner on review R-001 ("income and stabilisation
#: nearly identical"), evaluated on request by ``service.income_candidates`` beside the
#: stored Stabilisation. The owner chose **A**, which is now ROLE_MAP's Income; the others
#: stay here so the choice can be re-read against its alternatives. Nothing here is
#: published.
#:
#: The 10-year Treasury block (``long_rate``) is absent from every candidate for the same
#: reason it is absent from ROLE_MAP: it is a yield, not a return an investor earned. The
#: holding is ``gov_bonds``, which is offered here as a component.
INCOME_CANDIDATES: tuple[RoleSpec, ...] = (
    RoleSpec("income", {"real_estate": 1.0},
             "Before R-001: real estate alone (calibration CAL-092efd097adb0b26)."),
    RoleSpec("income", {"real_estate": 0.75, "equity": 0.25},
             "A (chosen, owner 29.09.2026, now ROLE_MAP): real estate with a quarter "
             "equity, the dividend-paying share of an income sleeve."),
    RoleSpec("income", {"real_estate": 0.5, "equity": 0.5},
             "B: real estate and equity in equal weight."),
    RoleSpec("income", {"real_estate": 0.5, "equity": 0.25, "gov_bonds": 0.25},
             "C: real estate half, equity and government bonds a quarter each: property, "
             "dividends and coupons."),
)


def compose_phase_means(block_phase_means: dict[str, list[float]],
                        weights: dict[str, float]) -> list[float]:
    """A role's five phase values from block phase values, equal to ``build_role_profiles``.

    Phase level first, then interpolation -- the same order and the same arithmetic as
    the stored calibration, so the current composition reproduces the stored Income curve.
    """
    total = sum(weights.values())
    return [
        sum((w / total) * block_phase_means[k][p] for k, w in weights.items())
        for p in range(len(PHASE_NAMES))
    ]


def role_curve(phase_means: list[float]) -> list[float]:
    """Read five phase values onto the 25 states, exactly as the calibration does."""
    return num.pchip_eval(list(PHASE_KNOTS), phase_means, state_axis())


@dataclass(frozen=True)
class RoleProfile:
    """One role's 25-state return profile and its provenance."""

    role: str
    basis: str
    members: tuple[str, ...]
    weights: dict[str, float]
    phase_means: tuple[float, ...]
    profile_by_state: tuple[float, ...]
    methods_by_state: tuple[Method, ...]
    n_obs_by_state: tuple[int, ...]
    #: Per phase, the smallest member-block observation count. A composite is only as
    #: well observed as its scarcest constituent, so the minimum is the honest figure --
    #: summing would claim support the composite does not have.
    n_obs_by_phase: tuple[int, ...]

    def as_state_rows(self) -> list[dict[str, object]]:
        return [
            {
                "state": i + 1,
                "value": self.profile_by_state[i],
                "method": self.methods_by_state[i].value,
                "n_obs": self.n_obs_by_state[i],
            }
            for i in range(len(self.profile_by_state))
        ]


def _weakest_method(methods: list[Method]) -> Method:
    """The least-supported method among a composite's members governs the composite."""
    return min(methods, key=METHOD_STRENGTH.index)


def build_role_profiles(blocks: dict[str, BlockProfile],
                        role_map: tuple[RoleSpec, ...] = ROLE_MAP) -> dict[str, RoleProfile]:
    """Aggregate the block profiles into the four role profiles.

    ``role_map`` defaults to the published one; another is passed only to reproduce an
    earlier calibration (:data:`ROLE_MAP_BEFORE_R001`).
    """
    out: dict[str, RoleProfile] = {}
    for spec in role_map:
        weights = spec.normalised()
        missing = [k for k in weights if k not in blocks]
        if missing:
            raise KeyError(f"role {spec.role!r} needs block(s) {missing} which were not calibrated")

        members = tuple(sorted(weights))
        phase_means: list[float] = []
        phase_methods: list[Method] = []
        phase_counts: list[int] = []
        for p in range(len(PHASE_NAMES)):
            value = 0.0
            for key, w in weights.items():
                estimate = blocks[key].phase_estimates[p]
                if estimate.mean is None:
                    raise ValueError(
                        f"block {key!r} has no estimate for phase {PHASE_NAMES[p]!r}; "
                        f"role {spec.role!r} cannot be composed"
                    )
                value += w * estimate.mean
            phase_means.append(value)
            phase_methods.append(
                _weakest_method([blocks[k].phase_estimates[p].method for k in weights])
            )
            phase_counts.append(min(blocks[k].phase_estimates[p].n_obs for k in weights))

        profile = num.pchip_eval(list(PHASE_KNOTS), phase_means, state_axis())
        out[spec.role] = RoleProfile(
            role=spec.role,
            basis=spec.basis,
            members=members,
            weights=weights,
            phase_means=tuple(phase_means),
            profile_by_state=tuple(profile),
            methods_by_state=tuple(state_methods(phase_methods)),
            n_obs_by_state=tuple(state_observation_counts(phase_counts)),
            n_obs_by_phase=tuple(phase_counts),
        )
    return out


def protection_beats_gain_in_crisis(roles: dict[str, RoleProfile]) -> bool:
    """The sanity check manual section 11 puts in a red callout.

    On seed-derived profiles Protection out-earns Gain everywhere, which is backwards:
    Protection exists to lose least in a crisis, not to be the highest-returning sleeve.
    This asserts the shape that should hold -- Protection above Gain **in crisis** -- and
    :func:`gain_beats_protection_in_boom` asserts the other half.
    """
    return roles["protection"].phase_means[0] > roles["gain"].phase_means[0]


def gain_beats_protection_in_boom(roles: dict[str, RoleProfile]) -> bool:
    """Gain must out-earn Protection when conditions are good, or the roles are inverted."""
    return roles["gain"].phase_means[4] > roles["protection"].phase_means[4]
