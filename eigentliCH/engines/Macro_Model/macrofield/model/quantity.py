"""The extended quantity equation and the unsecured-asset gap.

Brief section 0.4. The quantity equation M V = P H, split into a real sector (R) and a financial
sector (I), is

    M_R V_R + M_I V_I = P_R H_R + P_I H_I

Under the framework's simplifications (velocities approximated at one, money supply approximated by
the relevant capital stock, and real-economy price times volume set equal to Y) the fundamental
relation becomes

    K_R + K_I = Y + P_I H_I

from which the financial value not covered by the productive economy is

    Unsecured Assets = K_R + K_I - Y

This is the core fragility diagnostic. Its ideal-typical shape is slow growth, then acceleration
from Phase III, then collapse in Phase IV.

The module also exposes the stability-of-financial-prices check. The K_I definition is expected to
hold from full capitalisation until the feeding ends, and to diverge in Phase IV. That divergence is
surfaced as a fragility signal rather than smoothed away.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def unsecured_assets(
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
) -> np.ndarray:
    """Return the unsecured-asset gap, K_R + K_I - Y.

    The financial value not covered by the productive economy, in the currency units of the inputs.

    Args:
        real_capital: The K_R path.
        financial_capital: The K_I path.
        output: The Y path.

    Returns:
        The unsecured-asset path.

    Raises:
        ValueError: If the inputs do not share a shape, since a silent broadcast would produce a
            diagnostic that looks plausible and means nothing.
    """
    k_r = np.asarray(real_capital, dtype=float)
    k_i = np.asarray(financial_capital, dtype=float)
    y = np.asarray(output, dtype=float)
    if not (k_r.shape == k_i.shape == y.shape):
        raise ValueError(
            f"K_R, K_I and Y must share a shape, got {k_r.shape}, {k_i.shape} and {y.shape}"
        )
    return k_r + k_i - y


def unsecured_assets_ratio(
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
) -> np.ndarray:
    """Return the unsecured-asset gap as a ratio to output.

    Scale-free, so it is comparable across economies and across time within one economy.
    """
    y = np.asarray(output, dtype=float)
    if np.any(y == 0.0):
        raise ZeroDivisionError("the unsecured-asset ratio is undefined where Y is zero")
    return unsecured_assets(real_capital, financial_capital, output) / y


def implied_financial_price_volume(
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
) -> np.ndarray:
    """Return P_I H_I implied by the fundamental relation K_R + K_I = Y + P_I H_I.

    Identical to the unsecured-asset gap by construction. Exposed under its own name because the two
    read differently: this is the financial sector's price times volume, and the diagnostic below
    compares it against the observed financial-asset stock.
    """
    return unsecured_assets(real_capital, financial_capital, output)


@dataclass
class UnsecuredAssetDiagnostics:
    """The unsecured-asset diagnostics over a path.

    Attributes:
        level: The gap K_R + K_I - Y at each period.
        ratio: The gap as a ratio to output at each period.
        growth: The first difference of the level, period on period.
        acceleration: The second difference of the level. The Phase III signature is a sustained
            positive acceleration.
        accelerating: Boolean mask, true where acceleration has been positive for the configured
            number of consecutive periods.
        collapsing: Boolean mask, true where the level is falling. The Phase IV signature.
        first_acceleration_index: Index at which the acceleration signature first fires, or None.
        first_collapse_index: Index at which the collapse signature first fires, or None.
    """

    level: np.ndarray
    ratio: np.ndarray
    growth: np.ndarray
    acceleration: np.ndarray
    accelerating: np.ndarray
    collapsing: np.ndarray
    first_acceleration_index: int | None
    first_collapse_index: int | None


def _consecutive_run_mask(condition: np.ndarray, periods: int) -> np.ndarray:
    """Return a mask true where condition has held for `periods` consecutive entries.

    Used so that a single noisy period does not fire a transition indicator.
    """
    mask = np.zeros(condition.shape, dtype=bool)
    if periods <= 0:
        return condition.astype(bool)
    run = 0
    for i, value in enumerate(condition):
        run = run + 1 if value else 0
        mask[i] = run >= periods
    return mask


def _first_true(mask: np.ndarray) -> int | None:
    """Return the index of the first true entry, or None if there is none."""
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def diagnose_unsecured_assets(
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
    acceleration_periods: int = 3,
) -> UnsecuredAssetDiagnostics:
    """Return the acceleration and collapse signatures of the unsecured-asset gap.

    Brief section 0.4: the ideal-typical shape is slow growth, then acceleration from Phase III, then
    collapse in Phase IV. This function locates those two signatures rather than asserting them.

    Args:
        real_capital: The K_R path.
        financial_capital: The K_I path.
        output: The Y path.
        acceleration_periods: Consecutive periods of positive acceleration required before the
            acceleration indicator fires. From config, `phases.unsecured_acceleration_periods`.

    Returns:
        The diagnostics. Difference arrays are padded at the front with NaN so that every array
        shares the length of the input and indices line up with the input periods.
    """
    level = unsecured_assets(real_capital, financial_capital, output)
    ratio = unsecured_assets_ratio(real_capital, financial_capital, output)

    growth = np.full_like(level, np.nan)
    growth[1:] = np.diff(level)

    acceleration = np.full_like(level, np.nan)
    acceleration[2:] = np.diff(level, n=2)

    accelerating = _consecutive_run_mask(
        np.nan_to_num(acceleration, nan=-np.inf) > 0.0, acceleration_periods
    )
    collapsing = np.nan_to_num(growth, nan=np.inf) < 0.0

    return UnsecuredAssetDiagnostics(
        level=level,
        ratio=ratio,
        growth=growth,
        acceleration=acceleration,
        accelerating=accelerating,
        collapsing=collapsing,
        first_acceleration_index=_first_true(accelerating),
        first_collapse_index=_first_true(collapsing),
    )


@dataclass
class FinancialPriceStability:
    """The stability-of-financial-prices check of brief section 0.4.

    The K_I definition is expected to hold from full capitalisation until the feeding ends, and to
    diverge in Phase IV. The divergence is the fragility signal.

    Attributes:
        implied: P_I H_I implied by the fundamental relation.
        observed: The observed financial-asset stock, K_I.
        divergence: observed minus implied, in currency units.
        relative_divergence: The divergence as a share of the observed stock, so it is comparable
            across economies.
        diverging: Boolean mask, true where the relative divergence exceeds the tolerance.
        first_divergence_index: Index at which the divergence first exceeds the tolerance, or None.
        tolerance: The relative tolerance applied.
    """

    implied: np.ndarray
    observed: np.ndarray
    divergence: np.ndarray
    relative_divergence: np.ndarray
    diverging: np.ndarray
    first_divergence_index: int | None
    tolerance: float


def check_financial_price_stability(
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
    tolerance: float = 0.1,
) -> FinancialPriceStability:
    """Compare the observed financial-asset stock against the value the relation implies.

    The fundamental relation K_R + K_I = Y + P_I H_I gives an implied financial price times volume.
    Where the observed K_I diverges from it the financial sector is carrying value the productive
    economy does not support, which is the Phase IV signature.

    Note the structure of the comparison. Because the implied quantity is itself K_R + K_I - Y, the
    divergence reduces to Y - K_R, so this check is equivalent to asking whether real capital covers
    output. That is worth stating plainly rather than dressing up: the relation is an identity under
    the framework's simplifications, and the informative content is the sign and trend of Y - K_R,
    which is the investment share r of section 0.2 scaled by Y. The check is retained under the name
    the brief gives it, with this equivalence documented so nobody reads more into it than it holds.

    Args:
        real_capital: The K_R path.
        financial_capital: The K_I path.
        output: The Y path.
        tolerance: Relative divergence above which the fragility signal fires.

    Returns:
        The stability check.
    """
    implied = implied_financial_price_volume(real_capital, financial_capital, output)
    observed = np.asarray(financial_capital, dtype=float)
    divergence = observed - implied

    scale = np.where(np.abs(observed) > 0.0, np.abs(observed), np.nan)
    relative = divergence / scale
    diverging = np.nan_to_num(np.abs(relative), nan=0.0) > tolerance

    return FinancialPriceStability(
        implied=implied,
        observed=observed,
        divergence=divergence,
        relative_divergence=relative,
        diverging=diverging,
        first_divergence_index=_first_true(diverging),
        tolerance=float(tolerance),
    )
