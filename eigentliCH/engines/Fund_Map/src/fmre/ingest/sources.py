"""Series sources: CSV fallback, seeded synthetic generator, Bloomberg stub.

A source's contract is minimal: given a ticker, return a pandas Series of
levels indexed by DatetimeIndex, plus source metadata via ``series.attrs``.
Harmonisation (magnitude, currency, resample, returns) happens downstream.

Sources do not know about the DataSeries register or the building-block
register. They only understand tickers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from fmre.regime.timeline import RegimeTimeline
    from fmre.registers.building_blocks import BuildingBlock


class SeriesSource(Protocol):
    """Anything that can hand us a price/level series for a ticker."""

    name: str

    def fetch(self, ticker: str) -> pd.Series:
        ...


# ---------------------------------------------------------------------------
# CSV fallback source
# ---------------------------------------------------------------------------


def _safe_filename(ticker: str) -> str:
    """Bloomberg tickers contain spaces and occasionally '$' which are awkward
    on Windows. Map to filesystem-safe name: spaces -> '_', drop dollars."""
    return ticker.replace(" ", "_").replace("$", "_")


class CsvSource:
    """Reads ``<root>/<safe_ticker>.csv`` with columns ``date,close``.

    File format: header row ``date,close``; date in ISO ``YYYY-MM-DD``; close
    a float. Missing file raises ``FileNotFoundError`` with the ticker and the
    resolved path.
    """

    name = "csv"

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path_for(self, ticker: str) -> Path:
        return self.root / f"{_safe_filename(ticker)}.csv"

    def fetch(self, ticker: str) -> pd.Series:
        path = self._path_for(ticker)
        if not path.exists():
            raise FileNotFoundError(f"CsvSource: no series for ticker={ticker!r} at {path}")
        df = pd.read_csv(path, parse_dates=["date"])
        if not {"date", "close"}.issubset(df.columns):
            raise ValueError(f"CsvSource: {path} missing required columns date, close")
        series = pd.Series(df["close"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["date"]), name=ticker)
        series = series.sort_index()
        series.attrs = {"source": self.name, "source_path": str(path), "ticker": ticker}
        return series


# ---------------------------------------------------------------------------
# Synthetic source (deterministic per ticker)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyntheticParams:
    """Monthly geometric-Brownian parameters for a synthetic series.

    ``drift_annual`` and ``vol_annual`` are in decimal (0.07 = 7% pa).
    """

    drift_annual: float
    vol_annual: float
    start_level: float = 100.0


@dataclass(frozen=True, slots=True)
class StateConditionalHint:
    """Per-ticker state-conditional generation parameters.

    ``state_means_annual_pct``: length-25 array of annualised percent returns
    per regime state. Typically taken from the seed ``ret_distribution``.
    ``vol_annual_pct``: annualised vol in percent (e.g. 18.0 for equities).

    Passed to ``SyntheticSource`` alongside a ``RegimeTimeline`` to generate
    a price series whose sample per-state means recover ``state_means_annual_pct``
    exactly (up to noise). This makes the synthetic ingestion track the seed's
    role differentiation state-by-state — see D12 in decisions.md.
    """

    state_means_annual_pct: np.ndarray  # length 25
    vol_annual_pct: float
    start_level: float = 100.0


DEFAULT_SYNTHETIC = SyntheticParams(drift_annual=0.05, vol_annual=0.10)


def seed_state_conditional_hints(
    blocks: "list[BuildingBlock]",
) -> Callable[[str], StateConditionalHint | None]:
    """Build a ticker -> StateConditionalHint mapper from the seed register.

    Uses each block's ``ret_distribution`` as the state-conditional means,
    with a vol picked by role (and by asset class for Cash). Proxy tickers
    (multiple blocks sharing one ticker) collapse to the last block's hints
    per iteration order; since proxies share the ret_distribution, this is
    a non-issue in practice.
    """
    from fmre.registers.building_blocks import Role
    from fmre.registers.data_series import (
        Currency, Magnitude, Period, Unit, DataSeries, Status, build_default_register,
    )
    # AssetClass avoids a hard import cycle in type-checking
    from fmre.registers.building_blocks import AssetClass

    role_vol = {
        Role.GROWTH: 18.0,
        Role.INCOME: 5.0,
        Role.STABILIZATION: 4.0,
        Role.PROTECTION: 25.0,   # default for hedges; cash overrides below
    }
    ticker_map: dict[str, StateConditionalHint] = {}
    for b in blocks:
        vol = role_vol.get(b.role, 10.0)
        if b.asset_class is AssetClass.CASH:
            vol = 0.5
        ticker_map[b.ticker] = StateConditionalHint(
            state_means_annual_pct=np.array(b.ret_distribution, dtype=float),
            vol_annual_pct=vol,
        )
    return lambda ticker: ticker_map.get(ticker)


class SyntheticSource:
    """Seeded reproducible synthetic generator.

    Two modes:

    - **Plain GBM (default).** Constant per-ticker drift and vol from
      ``params_for``. Simple, stationary. Used by the majority of the tests.

    - **State-conditional.** When both ``timeline`` and ``state_hints`` are
      supplied and ``state_hints(ticker)`` returns a ``StateConditionalHint``,
      each month's return is drawn with the mean set by the seed's
      ret_distribution for the state active in that month. The sample
      per-state mean then recovers the seed value exactly, so the
      downstream estimator preserves role differentiation. See D12.

    The per-ticker RNG seed is derived deterministically from the ticker
    string, so the same ticker yields the same series across runs.
    """

    name = "synthetic"

    def __init__(
        self,
        start: date = date(1998, 1, 31),
        end: date = date(2024, 12, 31),
        params_for: "Callable[[str], SyntheticParams] | None" = None,
        master_seed: int = 20260728,
        timeline: "RegimeTimeline | None" = None,
        state_hints: "Callable[[str], StateConditionalHint | None] | None" = None,
    ):
        self.start = start
        self.end = end
        self.params_for = params_for or (lambda _t: DEFAULT_SYNTHETIC)
        self.master_seed = master_seed
        self.timeline = timeline
        self.state_hints = state_hints

    def _seed_for(self, ticker: str) -> int:
        # Stable 32-bit seed from ticker + master_seed. Digest, not hash(), so
        # it is deterministic across Python invocations.
        digest = hashlib.sha256(f"{self.master_seed}:{ticker}".encode()).digest()
        return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF

    def fetch(self, ticker: str) -> pd.Series:
        rng = np.random.default_rng(self._seed_for(ticker))
        hint = self.state_hints(ticker) if (self.timeline is not None and self.state_hints is not None) else None

        if hint is not None:
            # Generate on the timeline's own months, not on a continuous range.
            #
            # This mode conditions each month's draw on the state active that month, so a month the
            # timeline does not carry has no state to condition on. A published timeline can have
            # interior gaps, because a month its technical half did not cover is left absent rather than
            # interpolated. Building a continuous index would therefore ask for a state that does not
            # exist. Real price data needs no equivalent handling: the estimator inner-joins returns
            # against the timeline, so unmatched months simply drop out.
            index = self.timeline.path.index
            index = index[
                (index >= pd.Timestamp(self.start)) & (index <= pd.Timestamp(self.end))
            ]
            if len(index) == 0:
                raise ValueError(
                    f"SyntheticSource: the timeline covers no month between {self.start} and "
                    f"{self.end}, so no state-conditional series can be generated for {ticker!r}"
                )
        else:
            index = pd.date_range(self.start, self.end, freq="ME")
        n = len(index)

        if hint is not None:
            levels = self._state_conditional_levels(ticker, index, hint, rng)
            attrs = {
                "source": self.name,
                "generation": "state_conditional",
                "ticker": ticker,
                "vol_annual_pct": hint.vol_annual_pct,
                "master_seed": self.master_seed,
            }
        else:
            params = self.params_for(ticker)
            mu_m = (params.drift_annual - 0.5 * params.vol_annual ** 2) / 12.0
            sigma_m = params.vol_annual / np.sqrt(12.0)
            z = rng.standard_normal(n)
            log_r = mu_m + sigma_m * z
            levels = params.start_level * np.exp(np.cumsum(log_r))
            attrs = {
                "source": self.name,
                "generation": "gbm",
                "ticker": ticker,
                "drift_annual": params.drift_annual,
                "vol_annual": params.vol_annual,
                "master_seed": self.master_seed,
            }

        series = pd.Series(levels, index=index, name=ticker)
        series.attrs = attrs
        return series

    def _state_conditional_levels(
        self,
        ticker: str,
        index: pd.DatetimeIndex,
        hint: StateConditionalHint,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Draw simple monthly returns with mean set by the seed state means
        and vol set by the ticker's role. Convert to positive levels.

        For state ``s`` the target monthly simple mean is
        ``(1 + seed[s]/100)^(1/12) - 1`` so that the estimator's compound
        annualisation ``((1+mean_monthly)^12 - 1) * 100`` recovers ``seed[s]``.
        """
        assert self.timeline is not None
        state_means_decimal_annual = hint.state_means_annual_pct / 100.0
        target_monthly = (1.0 + state_means_decimal_annual) ** (1.0 / 12.0) - 1.0
        sigma_monthly = hint.vol_annual_pct / 100.0 / np.sqrt(12.0)

        n = len(index)
        states = np.empty(n, dtype=int)
        for t, d in enumerate(index):
            states[t] = self.timeline.state_at(d)

        z = rng.standard_normal(n)
        mus_per_period = target_monthly[states]
        r_simple = mus_per_period + sigma_monthly * z
        # Clamp to keep prices positive; -0.99 is a floor, not a fill (a real
        # -99% monthly outlier is a fat-tail event, but our synthetic vol is
        # small enough that this clip fires with astronomically small
        # probability under normal draws).
        r_simple = np.maximum(r_simple, -0.99)

        levels = np.empty(n, dtype=float)
        levels[0] = hint.start_level * (1.0 + r_simple[0])
        for t in range(1, n):
            levels[t] = levels[t - 1] * (1.0 + r_simple[t])
        return levels


# ---------------------------------------------------------------------------
# Bloomberg source: stub for v0.1.0. Wired later (D-Bloomberg).
# ---------------------------------------------------------------------------


class BloombergSource:
    name = "bloomberg"

    def fetch(self, ticker: str) -> pd.Series:  # pragma: no cover
        raise NotImplementedError(
            "BloombergSource is not wired in v0.1.0. Use CsvSource or SyntheticSource. "
            "See decisions.md and section 4.2 of the spec."
        )
