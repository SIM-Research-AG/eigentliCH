"""The mean-variance comparison branch. Not the model of record.

Exists so a curve-fit allocation can be set against the conventional answer. It reintroduces exactly the
objects the framework's method does without: an expected-return vector and a covariance matrix. Every
output that comes from this branch is labelled a comparison, and nothing here feeds the curve fit.

**Where the covariance comes from, and how that differs from the reference.** `translate_PCP_MV.m` built a
24-month rolling covariance from the instrument price history in the Controller workbook. The PCP consumes
no price history: the ReturnSet carries per-state profiles, not time series, and reading a price file
directly would be an unversioned dependency of exactly the kind section 3 forbids.

So the covariance here is the covariance of the per-state profiles under the live regime distribution.
With state probabilities `M` and profiles `BB` (instruments by states):

    mu_j    = sum_i M[i] * BB[j,i]
    Sigma   = sum_i M[i] * (BB[:,i] - mu) (BB[:,i] - mu)'

That is a genuine second moment, and it is the dispersion of outcomes across regime states rather than
across time. The two are not the same quantity and a number from this branch must not be compared against
a realised tracking error. The distinction is recorded on every result this branch produces.

**Risk aversion**, from spec section 4.4:

    M_MV = 5 / mean( argmax(regime) + mean((1:25) * regime) )
    if risk_aversion:   M_MV = 1.25 * ( M_MV - 2.5 * std(C) / (-min(C)) )
    if not market_risk: M_MV = 10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import LinearConstraint, minimize

from pcp.config import Config
from pcp.model.optimiser_curve import SolveResult

if TYPE_CHECKING:  # pragma: no cover
    from pcp.pipeline import RunInputs


def risk_aversion(
    regime: np.ndarray,
    target_curve: np.ndarray,
    config: Config,
    use_risk_aversion: bool = False,
    use_market_risk: bool = True,
) -> float:
    """The risk-aversion scalar, per spec section 4.4.

    `argmax` is reported one-based to match the reference implementation's state numbering, where the axis
    runs 1 to 25. Using a zero-based index would shift the scalar for every regime.
    """
    if not use_market_risk:
        return float(config.get("mean_variance.no_market_risk_value"))

    weights = np.asarray(regime, dtype=float).ravel()
    states = np.arange(1, weights.size + 1, dtype=float)
    modal = float(np.argmax(weights) + 1)
    central = float((states * weights).sum())
    denominator = float(np.mean([modal, central]))
    if denominator == 0.0:
        raise ValueError(
            "the regime distribution gives a zero denominator for the risk-aversion scalar, so it cannot "
            "be formed"
        )
    scalar = float(config.get("mean_variance.risk_aversion_numerator")) / denominator

    if use_risk_aversion:
        curve = np.asarray(target_curve, dtype=float).ravel()
        worst = float(-np.min(curve))
        if worst <= 0.0:
            raise ValueError(
                "the risk-aversion adjustment divides by the mandate curve's worst point, which is not "
                "negative, so the adjustment is undefined for this mandate"
            )

        scale = float(config.get("mean_variance.risk_aversion_scale"))
        multiple = float(config.get("mean_variance.risk_aversion_shortfall_multiple"))
        scalar = scale * (scalar - multiple * float(np.std(curve)) / worst)
    return scalar


def regime_moments(bb: np.ndarray, regime: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The expected-return vector and covariance across regime states.

    See the module docstring: this is dispersion across states, not across time.
    """
    profiles = np.asarray(bb, dtype=float)
    weights = np.asarray(regime, dtype=float).ravel()
    if profiles.shape[1] != weights.size:
        raise ValueError(
            f"BB has {profiles.shape[1]} states against a regime vector of {weights.size}"
        )
    total = float(weights.sum())
    if total <= 0.0:
        raise ValueError("the regime distribution carries no mass, so no moments can be formed")
    probabilities = weights / total

    mu = profiles @ probabilities
    centred = profiles - mu[:, None]
    sigma = (centred * probabilities[None, :]) @ centred.T
    # Symmetrise against floating-point drift, so the quadratic form is well behaved.
    return mu, 0.5 * (sigma + sigma.T)


def solve_mean_variance(
    inputs: "RunInputs",
    regime: np.ndarray,
    period_index: int,
    config: Config,
    speed: str = "exact",
) -> SolveResult:
    """Maximise `mu' x - (1 / M_MV) x' Sigma x` under the mandate's constraints.

    Uses the same constraint system and the same fixed start as the curve fit, so the two branches differ
    only in their objective and a comparison isolates that.
    """
    system = inputs.system
    mu, sigma = regime_moments(inputs.bb, regime)

    scalar = risk_aversion(
        regime,
        inputs.mandate.target_curve,
        config,
        use_risk_aversion=bool(config.get("expert.mv_risk_aversion")),
        use_market_risk=bool(config.get("expert.mv_market_risk")),
    )
    if scalar == 0.0:
        raise ValueError("the risk-aversion scalar is zero, so the variance term would be unbounded")
    penalty = 1.0 / scalar

    def objective(x: np.ndarray) -> float:
        return float(-(mu @ x) + penalty * (x @ sigma @ x))

    def gradient(x: np.ndarray) -> np.ndarray:
        return -mu + 2.0 * penalty * (sigma @ x)

    speeds = dict(config.get("solver.speeds"))
    settings = speeds[speed]
    n = inputs.bb.shape[0]
    x0 = np.full(n, float(config.get("solver.start_value")), dtype=float)

    outcome = minimize(
        objective,
        x0,
        jac=gradient,
        method=str(config.get("solver.method")),
        bounds=list(zip(system.lower_bounds.tolist(), system.upper_bounds.tolist())),
        constraints=[
            {"type": "eq", "fun": lambda x: float(np.sum(x) - 1.0), "jac": lambda x: np.ones_like(x)},
            {"type": "ineq", "fun": lambda x: system.b - system.a @ x, "jac": lambda x: -system.a},
        ],
        options={"ftol": float(settings["ftol"]), "maxiter": int(settings["maxiter"])},
    )

    raw = np.asarray(outcome.x, dtype=float)
    total = float(raw.sum())
    if total <= 0.0:
        raise ValueError(
            "the mean-variance branch returned weights summing to zero or less, so they cannot be "
            "normalised"
        )

    decimals = int(config.get("solver.conditions_met_decimals"))
    conditions_met = "yes" if round(total, decimals) == 1 else "no"

    notes = [
        "the covariance is the dispersion of the per-state profiles under the live regime, not a realised "
        "time-series covariance. The reference implementation used a 24-month rolling covariance from "
        "price history, which no contract this programme consumes carries. The two are different "
        "quantities and must not be compared against one another.",
        f"risk-aversion scalar M_MV = {scalar:.6f}.",
    ]
    if not outcome.success:
        notes.append(
            f"the mean-variance solve did not converge ({str(outcome.message).strip()}). As a comparison "
            f"branch it has no fallback; treat the allocation as indicative only."
        )

    return SolveResult(
        weights=raw / total,
        raw_weights=raw,
        # Reported as the mean-variance objective, which is not comparable with the curve-fit objective.
        objective_value=float(outcome.fun),
        conditions_met=conditions_met,
        status=str(outcome.message).strip(),
        method=f"{config.get('solver.method')} (mean-variance comparison)",
        iterations=int(getattr(outcome, "nit", 0) or 0),
        success=bool(outcome.success),
        notes=tuple(notes),
    )
