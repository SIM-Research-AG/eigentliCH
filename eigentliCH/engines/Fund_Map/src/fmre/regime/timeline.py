"""Regime timeline contract (spec 3.4).

Read-only input produced by the macro field-model programme. This module
loads, validates, and exposes it. It never invents states: if the file is
missing or the scope does not match, callers refuse to proceed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

STATE_GRID: int = 25


class TimelineValidationError(ValueError):
    """Raised when a Regime timeline fails schema or invariant checks."""


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    """The ``current`` block of the timeline (spec 3.4)."""

    regime_id: str
    state: int
    phase: int | None = None
    saturation_pct: float | None = None


@dataclass(frozen=True, slots=True)
class RegimeTimeline:
    regime_timeline_id: str
    economy_scope: str
    model_version: str
    as_of: str
    period: str                  # "M" | "Q" | "A"
    state_grid: int
    path: pd.Series              # DatetimeIndex (period-end), values = state int
    current: RegimeSnapshot
    provenance: dict[str, Any]

    def state_at(self, when) -> int:
        """State active in the period containing ``when``.

        Accepts a datetime-like or ISO string. Snaps to period-end matching
        this timeline's ``period`` before lookup.
        """
        ts = pd.Timestamp(when)
        ts = _snap_period_end(ts, self.period)
        if ts not in self.path.index:
            raise KeyError(f"state_at: no state for {ts.date()} in timeline {self.regime_timeline_id}")
        return int(self.path.loc[ts])

    def state_frequencies(self, window: tuple[str, str] | None = None) -> pd.Series:
        """Empirical state frequencies ``pi_s`` over an optional window.

        Returns a Series indexed 0..state_grid-1 that sums to 1 (unless the
        window is empty, in which case a KeyError is raised).
        """
        if window is not None:
            start = pd.Timestamp(window[0])
            end = pd.Timestamp(window[1])
            sub = self.path.loc[start:end]
        else:
            sub = self.path
        if sub.empty:
            raise KeyError(f"state_frequencies: window {window!r} contains no observations")
        counts = sub.value_counts(normalize=True)
        out = pd.Series(0.0, index=range(self.state_grid), name="pi_s")
        for s, p in counts.items():
            out.loc[int(s)] = float(p)
        return out

    def align_returns(self, returns: pd.Series) -> pd.DataFrame:
        """Tag each period-return with the state active in that period.

        Inner-join semantics: only returns whose period is present in the
        timeline appear in the output. Returns a DataFrame with columns
        ``return`` and ``state``.
        """
        r = returns.copy()
        r.index = pd.DatetimeIndex([_snap_period_end(pd.Timestamp(d), self.period) for d in r.index])
        r.name = "return"
        out = r.to_frame().join(self.path.rename("state"), how="inner")
        return out

    @property
    def n_observations(self) -> int:
        return int(self.path.shape[0])


def _snap_period_end(ts: pd.Timestamp, period: str) -> pd.Timestamp:
    if period == "M":
        return ts.to_period("M").to_timestamp("M")
    if period == "Q":
        return ts.to_period("Q").to_timestamp("Q")
    if period == "A":
        return ts.to_period("A").to_timestamp("A")
    raise TimelineValidationError(f"unknown period {period!r}")


def _require(d: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise TimelineValidationError(f"missing required field(s): {missing}")


def timeline_from_dict(data: dict[str, Any]) -> RegimeTimeline:
    """Validate a spec 3.4 dict payload and return a typed RegimeTimeline."""
    _require(
        data,
        "regime_timeline_id",
        "economy_scope",
        "model_version",
        "as_of",
        "period",
        "state_grid",
        "path",
        "current",
        "provenance",
    )
    if data["state_grid"] != STATE_GRID:
        raise TimelineValidationError(f"state_grid must be {STATE_GRID}, got {data['state_grid']}")
    period = data["period"]
    if period not in {"M", "Q", "A"}:
        raise TimelineValidationError(f"period must be one of M/Q/A, got {period!r}")

    path_records = list(data["path"])
    if not path_records:
        raise TimelineValidationError("path must be non-empty")

    dates: list[pd.Timestamp] = []
    states: list[int] = []
    for i, rec in enumerate(path_records):
        _require(rec, "date", "state")
        s = rec["state"]
        if not isinstance(s, int) or not (0 <= s < STATE_GRID):
            raise TimelineValidationError(
                f"path[{i}]: state={s!r} not an int in 0..{STATE_GRID - 1}"
            )
        try:
            ts = _snap_period_end(pd.Timestamp(rec["date"]), period)
        except Exception as exc:
            raise TimelineValidationError(f"path[{i}]: unparseable date {rec['date']!r}") from exc
        dates.append(ts)
        states.append(int(s))

    if len(set(dates)) != len(dates):
        raise TimelineValidationError("path has duplicate dates after period snap")

    ser = pd.Series(states, index=pd.DatetimeIndex(dates), name="state")
    if not ser.index.is_monotonic_increasing:
        raise TimelineValidationError("path dates are not monotonically increasing")

    cur = data["current"]
    _require(cur, "regime_id", "state")
    if not (0 <= cur["state"] < STATE_GRID):
        raise TimelineValidationError(
            f"current.state={cur['state']} not in 0..{STATE_GRID - 1}"
        )

    return RegimeTimeline(
        regime_timeline_id=str(data["regime_timeline_id"]),
        economy_scope=str(data["economy_scope"]),
        model_version=str(data["model_version"]),
        as_of=str(data["as_of"]),
        period=period,
        state_grid=int(data["state_grid"]),
        path=ser,
        current=RegimeSnapshot(
            regime_id=str(cur["regime_id"]),
            state=int(cur["state"]),
            phase=cur.get("phase"),
            saturation_pct=cur.get("saturation_pct"),
        ),
        provenance=dict(data["provenance"]),
    )


def load_timeline(path: Path | str) -> RegimeTimeline:
    p = Path(path)
    if not p.exists():
        raise TimelineValidationError(f"regime timeline file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return timeline_from_dict(data)


def require_scope(timeline: RegimeTimeline, expected_scope: str) -> None:
    """Refuse to proceed on a scope mismatch (spec 3.4).

    Return Estimation calls this before emitting a ReturnSet. A mismatch is
    a build-order violation, not a soft warning.
    """
    if timeline.economy_scope != expected_scope:
        raise TimelineValidationError(
            f"scope mismatch: timeline economy_scope={timeline.economy_scope!r}, "
            f"expected {expected_scope!r}. Refusing to proceed."
        )
