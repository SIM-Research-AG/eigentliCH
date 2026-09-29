"""Orchestration: run the calibration, persist it, read it back, estimate instruments.

This is the only module the API talks to. Everything above it is pure computation with no
knowledge of storage; everything below it is storage with no knowledge of the model. The
split is what lets the calibration be tested against the published reference without a
database, and the API be tested against a temp database without a spreadsheet.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from engines.fund_map.calibrate import (
    BLOCKS,
    STATE_COUNT,
    SUFFICIENCY_FLOOR,
    TRIM_FRACTION,
    TRIM_SWITCH,
    BlockProfile,
    Estimator,
    Method,
    build_block_returns,
    calibrate_all,
    state_axis,
)
from engines.fund_map.estimate import (
    Candidate,
    EstimatedProfile,
    MonthlyReturn,
    estimate_instrument,
    ProfileMethod,
)
from engines.fund_map.indicators import (
    FIRST_YEAR,
    INDICATOR_ORDER,
    LAST_YEAR,
    SENTIMENT_WEIGHTS,
    build_indicators,
)
from engines.fund_map.phases import (
    BOUND_BUSINESS,
    BOUND_INNOVATION,
    BOUND_RECESSION,
    PHASE_NAMES,
    PhaseTimeline,
    classify_series,
)
from engines.fund_map.roles import ROLE_MAP, RoleProfile, RoleSpec, build_role_profiles
from engines.fund_map.state_map import StateMap, StateMapEntry, build_state_map
from store import db

ENGINE = "fund_map"
ENGINE_VERSION = "fm@1.0.0"
UNIVERSE_VERSION = "u@1.0.0"


def calibration_parameters(estimator: Estimator,
                           role_map: tuple[RoleSpec, ...] = ROLE_MAP) -> dict[str, object]:
    """Every constant the calibration depends on, for the manifest.

    A run is reproducible only if the parameters are recorded alongside the result. This
    is the parameter hash's input, and anything that changes a published figure must
    appear here or the hash is a lie.
    """
    return {
        "estimator": estimator.value,
        "state_grid": STATE_COUNT,
        "state_axis": state_axis(),
        "phase_bounds": {
            "innovation": BOUND_INNOVATION,
            "business": BOUND_BUSINESS,
            "recession": BOUND_RECESSION,
        },
        "sufficiency_floor": SUFFICIENCY_FLOOR,
        "trim_switch": TRIM_SWITCH,
        "trim_fraction": TRIM_FRACTION,
        "sentiment_weights": SENTIMENT_WEIGHTS,
        "indicator_order": list(INDICATOR_ORDER),
        "role_map": {r.role: r.weights for r in role_map},
        "window": [FIRST_YEAR, LAST_YEAR],
    }


@dataclass(frozen=True)
class CalibrationResult:
    calibration_id: str
    blocks: dict[str, BlockProfile]
    roles: dict[str, RoleProfile]
    timeline: PhaseTimeline
    parameters: dict[str, object]
    sources: dict[str, str]


def run_calibration(
    record: dict,
    *,
    estimator: Estimator = Estimator.PLAIN_MEAN,
    role_map: tuple[RoleSpec, ...] = ROLE_MAP,
) -> CalibrationResult:
    """Build the market environment, the phase timeline and every profile.

    ``role_map`` is the published one unless an earlier calibration is being reproduced
    for comparison (``roles.ROLE_MAP_BEFORE_R001`` gives `CAL-092efd097adb0b26`).
    """
    environment = build_indicators(record)
    timeline = PhaseTimeline(
        first_year=environment.first_year,
        phases=tuple(classify_series(environment.cycle)),
    )
    blocks = calibrate_all(build_block_returns(record), timeline, estimator=estimator)
    roles = build_role_profiles(blocks, role_map)
    parameters = calibration_parameters(estimator, role_map)
    sources = {k: v.source_sha256 for k, v in record.items()}

    calibration_id = db.content_id(
        "CAL",
        {
            "parameters": parameters,
            "sources": sources,
            "roles": {k: list(v.profile_by_state) for k, v in roles.items()},
        },
    )
    return CalibrationResult(calibration_id, blocks, roles, timeline, parameters, sources)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_calibration(conn: db.Connection, result: CalibrationResult,
                     environment_rows: Sequence[tuple]) -> None:
    """Write a calibration and everything needed to explain it."""
    conn.execute(
        db.upsert(
            "calibration",
            (
                "calibration_id", "created_at", "estimator", "first_year", "last_year",
                "state_grid", "params_json", "sources_json", "phase_counts_json",
            ),
            ("calibration_id",),
        ),
        (
            result.calibration_id,
            db.utc_now(),
            str(result.parameters["estimator"]),
            result.timeline.first_year,
            result.timeline.last_year,
            STATE_COUNT,
            db.dumps(result.parameters),
            db.dumps(result.sources),
            db.dumps(result.timeline.counts()),
        ),
    )

    conn.executemany(
        db.upsert(
            "calibration_block",
            (
                "calibration_id", "block_key", "label", "role", "first_year", "last_year",
                "n_obs_total", "phase_json", "profile_json", "methods_json", "n_obs_json",
            ),
            ("calibration_id", "block_key",),
        ),
        [
            (
                result.calibration_id, p.key, p.label, p.role, p.first_year, p.last_year,
                p.n_obs_total,
                db.dumps([
                    {"phase": e.phase, "n_obs": e.n_obs, "central": e.mean,
                     "spread": e.std, "method": e.method.value}
                    for e in p.phase_estimates
                ]),
                db.dumps(list(p.profile_by_state)),
                db.dumps([m.value for m in p.methods_by_state]),
                db.dumps(list(p.n_obs_by_state)),
            )
            for p in result.blocks.values()
        ],
    )

    conn.executemany(
        db.upsert(
            "calibration_role",
            (
                "calibration_id", "role", "basis", "members_json", "weights_json",
                "phase_means_json", "profile_json", "methods_json", "n_obs_json",
                "n_obs_phase_json",
            ),
            ("calibration_id", "role",),
        ),
        [
            (
                result.calibration_id, r.role, r.basis, db.dumps(list(r.members)),
                db.dumps(r.weights), db.dumps(list(r.phase_means)),
                db.dumps(list(r.profile_by_state)),
                db.dumps([m.value for m in r.methods_by_state]),
                db.dumps(list(r.n_obs_by_state)),
                db.dumps(list(r.n_obs_by_phase)),
            )
            for r in result.roles.values()
        ],
    )

    conn.executemany(
        db.upsert("market_environment", ("year", "cycle", "phase", "inflation",), ("year",)),
        environment_rows,
    )


def save_state_map(conn: db.Connection, state_map: StateMap, calibration_id: str) -> str:
    map_id = db.content_id(
        "MAP",
        {
            "method": state_map.method,
            "calibration": calibration_id,
            "entries": state_map.as_rows(),
        },
    )
    conn.execute(
        db.upsert(
            "state_map_meta",
            (
                "map_id", "created_at", "calibration_id", "signal_first", "signal_last",
                "method", "note",
            ),
            ("map_id",),
        ),
        (
            map_id, db.utc_now(), calibration_id, state_map.signal_first,
            state_map.signal_last, state_map.method,
            "Signal columns located by their share of the signal's own history, then read off "
            "the economic cycle at the same share. Column n is not assumed to be state n.",
        ),
    )
    conn.executemany(
        db.upsert(
            "state_map",
            (
                "map_id", "signal_state", "centile", "cycle_value", "axis_value", "calib_state",
            ),
            ("map_id", "signal_state",),
        ),
        [
            (map_id, e.signal_state, e.centile, e.cycle_value, e.axis_value, e.calib_state)
            for e in state_map.entries
        ],
    )
    return map_id


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def latest_calibration_id(conn: db.Connection) -> str | None:
    row = conn.execute(
        "SELECT calibration_id FROM calibration ORDER BY created_at DESC, calibration_id LIMIT "
        "1"
    ).fetchone()
    return row["calibration_id"] if row else None


def load_role_profiles(conn: db.Connection, calibration_id: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM calibration_role WHERE calibration_id = %s", (calibration_id,)
    ).fetchall()
    return {
        r["role"]: {
            "role": r["role"],
            "basis": r["basis"],
            "members": db.loads(r["members_json"]),
            "weights": db.loads(r["weights_json"]),
            "phase_means": db.loads(r["phase_means_json"]),
            "profile": db.loads(r["profile_json"]),
            "methods": db.loads(r["methods_json"]),
            "n_obs": db.loads(r["n_obs_json"]),
            "n_obs_phase": db.loads(r["n_obs_phase_json"]),
        }
        for r in rows
    }


def load_block_profiles(conn: db.Connection, calibration_id: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM calibration_block WHERE calibration_id = %s", (calibration_id,)
    ).fetchall()
    return {
        r["block_key"]: {
            "key": r["block_key"],
            "label": r["label"],
            "role": r["role"],
            "first_year": r["first_year"],
            "last_year": r["last_year"],
            "n_obs_total": r["n_obs_total"],
            "phases": db.loads(r["phase_json"]),
            "profile": db.loads(r["profile_json"]),
            "methods": db.loads(r["methods_json"]),
            "n_obs": db.loads(r["n_obs_json"]),
        }
        for r in rows
    }


def load_state_map(conn: db.Connection, map_id: str) -> StateMap:
    meta = conn.execute(
        "SELECT * FROM state_map_meta WHERE map_id = %s", (map_id,)
    ).fetchone()
    if meta is None:
        raise KeyError(f"no state map {map_id!r}")
    rows = conn.execute(
        "SELECT * FROM state_map WHERE map_id = %s ORDER BY signal_state", (map_id,)
    ).fetchall()
    return StateMap(
        method=meta["method"],
        signal_first=meta["signal_first"],
        signal_last=meta["signal_last"],
        entries=tuple(
            StateMapEntry(r["signal_state"], r["centile"], r["cycle_value"],
                          r["axis_value"], r["calib_state"])
            for r in rows
        ),
    )


def latest_state_map_id(conn: db.Connection, calibration_id: str) -> str | None:
    row = conn.execute(
        "SELECT map_id FROM state_map_meta WHERE calibration_id = %s ORDER BY created_at DESC, "
        "map_id LIMIT 1",
        (calibration_id,),
    ).fetchone()
    return row["map_id"] if row else None


def modal_signal_by_period(conn: db.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT period, modal_state FROM market_risk_month").fetchall()
    return {r["period"]: r["modal_state"] for r in rows}


def instrument_returns(conn: db.Connection, instrument_id: str) -> list[MonthlyReturn]:
    rows = conn.execute(
        "SELECT period, value FROM instrument_return WHERE instrument_id = %s ORDER BY period",
        (instrument_id,),
    ).fetchall()
    return [MonthlyReturn(r["period"], r["value"]) for r in rows]


def build_candidates(
    conn: db.Connection, calibration_id: str, *, exclude: str
) -> list[Candidate]:
    """Every other instrument that already has a stored profile, as a borrowing source."""
    rows = conn.execute(
        "SELECT i.instrument_id, i.role, i.region_scope, p.profile_json FROM instrument i JOIN "
        "instrument_profile p ON p.instrument_id = i.instrument_id AND p.calibration_id = %s "
        "WHERE i.instrument_id != %s AND i.active = 1",
        (calibration_id, exclude),
    ).fetchall()
    out: list[Candidate] = []
    for row in rows:
        returns = {
            r["period"]: r["value"]
            for r in conn.execute(
                "SELECT period, value FROM instrument_return WHERE instrument_id = %s",
                (row["instrument_id"],),
            )
        }
        out.append(
            Candidate(
                instrument_id=row["instrument_id"],
                role=row["role"],
                region_scope=row["region_scope"],
                returns=returns,
                profile_by_state=db.loads(row["profile_json"]),
            )
        )
    return out


#: Which estimator builds the instrument profiles the engine serves -- the ReturnSet, the
#: instrument profile endpoint and the diagnostics -- unless a caller names another with
#: ``profile_method=`` / ``method=``. `INSTRUMENTS_PROFILE_METHOD` overrides it for the
#: whole engine.
#:
#: **The 12 month forward measurement, lightly smoothed, since 29 September 2026**
#: (owner's decision on review R-002, FMRE-22). Until then it was the cascade, which read
#: Precious Metals at about -5 % in crisis from a role seed and jumped 9 % between
#: neighbouring states on average. The served default is computed on request from the
#: stored histories and the public proxies, in every currency; nothing it produces is
#: stored.
DEFAULT_PROFILE_METHOD = ProfileMethod.FORWARD_12M_SMOOTHED

#: The estimator whose profiles are *stored* in ``instrument_profile``: the cascade,
#: always. They are the cascade's peer basis for borrowing, and ``profile_method=cascade``
#: reads them back unchanged; storing another estimator's profiles there would silently
#: change what the cascade borrows.
STORED_PROFILE_METHOD = ProfileMethod.CASCADE

PROFILE_METHOD_VAR = "INSTRUMENTS_PROFILE_METHOD"


def configured_profile_method() -> ProfileMethod:
    """The estimator this engine serves by default, and why it is not simply a constant."""
    raw = os.environ.get(PROFILE_METHOD_VAR, "").strip().lower()
    if not raw:
        return DEFAULT_PROFILE_METHOD
    try:
        return ProfileMethod(raw)
    except ValueError:
        raise ValueError(
            f"{PROFILE_METHOD_VAR}={raw!r} is not a profile method. "
            f"Choose one of {[m.value for m in ProfileMethod]}."
        ) from None


def estimate_and_save(
    conn: db.Connection,
    instrument_id: str,
    calibration_id: str,
    *,
    profile_method: ProfileMethod | None = None,
) -> EstimatedProfile:
    """Re-estimate one instrument and store the result (the cascade, see
    :data:`STORED_PROFILE_METHOD`, unless a caller names another)."""
    started = time.perf_counter()
    row = conn.execute(
        "SELECT * FROM instrument WHERE instrument_id = %s", (instrument_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no instrument {instrument_id!r}")

    map_id = latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise RuntimeError(
            "no state map for this calibration; the monthly signal has not been loaded"
        )

    roles = load_role_profiles(conn, calibration_id)
    role_row = roles[row["role"]]
    role_profile = RoleProfile(
        role=role_row["role"],
        basis=role_row["basis"],
        members=tuple(role_row["members"]),
        weights=role_row["weights"],
        phase_means=tuple(role_row["phase_means"]),
        profile_by_state=tuple(role_row["profile"]),
        methods_by_state=tuple(Method(m) for m in role_row["methods"]),
        n_obs_by_state=tuple(role_row["n_obs"]),
        n_obs_by_phase=tuple(role_row["n_obs_phase"]),
    )

    profile = estimate_instrument(
        instrument_id=instrument_id,
        role=row["role"],
        returns=instrument_returns(conn, instrument_id),
        signal_by_period=modal_signal_by_period(conn),
        state_map=load_state_map(conn, map_id),
        role_profile=role_profile,
        candidates=build_candidates(conn, calibration_id, exclude=instrument_id),
        region_scope=row["region_scope"],
        profile_method=profile_method or STORED_PROFILE_METHOD,
    )

    return_set_id = db.content_id(
        "RS",
        {
            "instrument": instrument_id,
            "calibration": calibration_id,
            "state_map": map_id,
            "profile": list(profile.profile_by_state),
        },
    )
    conn.execute(
        db.upsert(
            "instrument_profile",
            (
                "instrument_id", "calibration_id", "return_set_id", "computed_at", "coverage",
                "n_obs_total", "borrowed_from", "match_score", "profile_json", "methods_json",
                "n_obs_json", "n_obs_discarded_json",
            ),
            ("instrument_id", "calibration_id",),
        ),
        (
            instrument_id, calibration_id, return_set_id, db.utc_now(),
            profile.coverage.value, profile.n_obs_total, profile.borrowed_from,
            profile.match_score, db.dumps(list(profile.profile_by_state)),
            db.dumps([m.value for m in profile.methods_by_state]),
            db.dumps(list(profile.n_obs_by_state)),
            db.dumps(list(profile.n_obs_discarded_by_state)),
        ),
    )

    record_run(
        conn,
        engine=ENGINE,
        inputs={"instrument_id": instrument_id, "calibration_id": calibration_id,
                "state_map_id": map_id},
        outputs={"return_set_id": return_set_id, "coverage": profile.coverage.value},
        started=started,
    )
    return profile


# ---------------------------------------------------------------------------
# Opt-in views: another estimator, another currency (reviews R-002, R-003; D-01, D-02)
#
# Nothing below writes a profile. The stored profiles are the cascade's in each series'
# source currency; these functions compute every other view on request, in memory -- the
# served default (the forward measurement, smoothed, FMRE-22) included.
# ---------------------------------------------------------------------------


@dataclass
class Universe:
    """Everything the estimators read, loaded once rather than once per instrument."""

    calibration_id: str
    map_id: str
    state_map: StateMap
    signal: dict[str, int]
    roles: dict[str, RoleProfile]
    instruments: list[dict]
    returns: dict[str, dict[str, float]]
    return_source: dict[str, str | None]
    stored: dict[str, dict]
    proxies: dict[str, dict[str, float]]
    in_chf: dict[str, dict[str, float]] | None


def role_profile_objects(conn: db.Connection, calibration_id: str) -> dict[str, RoleProfile]:
    return {
        role: RoleProfile(
            role=r["role"], basis=r["basis"], members=tuple(r["members"]),
            weights=r["weights"], phase_means=tuple(r["phase_means"]),
            profile_by_state=tuple(r["profile"]),
            methods_by_state=tuple(Method(m) for m in r["methods"]),
            n_obs_by_state=tuple(r["n_obs"]), n_obs_by_phase=tuple(r["n_obs_phase"]),
        )
        for role, r in load_role_profiles(conn, calibration_id).items()
    }


def load_fx(conn: db.Connection) -> dict[str, dict[str, float]] | None:
    """The stored exchange rates as CHF values per currency, or ``None`` if not loaded."""
    from engines.fund_map.currency import FX_SERIES, cross_rates
    feed = conn.config.datafeed_schema
    levels: dict[str, dict[str, float]] = {}
    for series_id in FX_SERIES:
        levels[series_id] = {
            r["period"]: r["value"]
            for r in conn.execute(
                f"SELECT period, value FROM {feed}.observation WHERE series_id = %s",
                (series_id,))
        }
    if not all(levels.values()):
        return None
    return cross_rates(levels)


def load_universe(conn: db.Connection, calibration_id: str) -> Universe:
    map_id = latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise RuntimeError("no state map for this calibration; load the monthly signal")
    instruments = [dict(r) for r in conn.execute(
        "SELECT instrument_id, name, role, asset_class, region_scope, currency, proxy_symbol, "
        "proxy_grade FROM instrument WHERE active = 1 ORDER BY name").fetchall()]
    returns: dict[str, dict[str, float]] = {i["instrument_id"]: {} for i in instruments}
    source: dict[str, str | None] = {i["instrument_id"]: None for i in instruments}
    for r in conn.execute("SELECT instrument_id, period, value, source FROM instrument_return"):
        if r["instrument_id"] in returns:
            returns[r["instrument_id"]][r["period"]] = r["value"]
            source[r["instrument_id"]] = source[r["instrument_id"]] or r["source"]
    stored = {
        r["instrument_id"]: {
            "profile": db.loads(r["profile_json"]), "methods": db.loads(r["methods_json"]),
            "n_obs": db.loads(r["n_obs_json"]), "coverage": r["coverage"],
            "borrowed_from": r["borrowed_from"], "match_score": r["match_score"],
            "n_obs_total": r["n_obs_total"],
        }
        for r in conn.execute(
            "SELECT * FROM instrument_profile WHERE calibration_id = %s", (calibration_id,))
    }
    from feeds.proxy_map import feed_series_id
    feed = conn.config.datafeed_schema
    wanted = sorted({i["proxy_symbol"] for i in instruments if i["proxy_symbol"]})
    proxies: dict[str, dict[str, float]] = {}
    for symbol in wanted:
        values = {
            r["period"]: r["value"]
            for r in conn.execute(
                f"SELECT period, value FROM {feed}.observation WHERE series_id = %s",
                (feed_series_id(symbol),))
        }
        if values:
            proxies[symbol] = values
    return Universe(
        calibration_id=calibration_id, map_id=map_id,
        state_map=load_state_map(conn, map_id), signal=modal_signal_by_period(conn),
        roles=role_profile_objects(conn, calibration_id), instruments=instruments,
        returns=returns, return_source=source, stored=stored, proxies=proxies,
        in_chf=load_fx(conn),
    )


@dataclass(frozen=True)
class SeriesChoice:
    """Which monthly history an estimator reads for one instrument, and in what currency."""

    returns: dict[str, float]
    label: str | None          # the stored source label, or <feed>:<symbol>:<grade>
    currency: str              # the currency the history is measured in
    origin: str                # "own" or "proxy"


def choose_forward_series(universe: Universe, instrument: dict) -> SeriesChoice:
    """The history the 12 month forward measurement reads.

    **A forward window needs twelve consecutive months, and a recovered series has holes.**
    The returns recovered from the andersCH report exist only in the months the manager
    held the position -- Precious Metals has 147 of 239 -- so most 12 month windows are
    incomplete and are dropped. Where the register maps the instrument to a public proxy
    that is in the feed, the measurement compares the two and reads whichever gives more
    complete windows; ties go to the instrument's own history. The proxy is also the
    *unconditional* asset, which removes the selection bias README "What is not yet true"
    describes. The choice is reported on every result.
    """
    from engines.fund_map.currency import source_currency
    from engines.fund_map.forward import forward_windows
    from feeds.proxy_map import source_of

    iid = instrument["instrument_id"]
    own = universe.returns.get(iid, {})
    own_label = universe.return_source.get(iid)
    best = SeriesChoice(own, own_label,
                        source_currency(own_label, instrument["currency"]), "own")
    symbol = instrument.get("proxy_symbol")
    grade = instrument.get("proxy_grade")
    if symbol and grade and grade != "none" and symbol in universe.proxies:
        proxy = universe.proxies[symbol]
        own_n = len(forward_windows(own, universe.signal, universe.state_map))
        proxy_n = len(forward_windows(proxy, universe.signal, universe.state_map))
        if proxy_n > own_n:
            best = SeriesChoice(proxy, f"{source_of(symbol)}:{symbol}:{grade}", "USD",
                                "proxy")
    return best


def _converted(universe: Universe, returns: dict[str, float], source: str,
               currency: str | None) -> dict[str, float]:
    from engines.fund_map.currency import CurrencyError, convert_returns
    # An instrument without history has nothing to convert, whatever its register
    # currency; asking for an AUD rate it would never use refused the whole set.
    if currency is None or currency == source or not returns:
        return returns
    if universe.in_chf is None:
        raise CurrencyError(
            "the exchange rates are not loaded, so no return can be converted. "
            "Run: python -m store.etl.fx")
    return convert_returns(returns, source, currency, universe.in_chf)


def _own_series(universe: Universe, instrument: dict) -> SeriesChoice:
    from engines.fund_map.currency import source_currency
    iid = instrument["instrument_id"]
    label = universe.return_source.get(iid)
    return SeriesChoice(universe.returns.get(iid, {}), label,
                        source_currency(label, instrument["currency"]), "own")


def _candidates(universe: Universe, currency: str | None,
                cache: dict) -> list[Candidate]:
    """Every instrument with a stored profile, its returns converted to ``currency``.

    Peer *profiles* stay as stored: the cascade borrows a peer's shape and, in the default
    shape-anchored mode, re-levels it on the target's own converted returns, so the level
    it publishes is the target's in the chosen currency. D2 reads only peers' volatility.
    """
    key = ("candidates", currency)
    if key not in cache:
        out = []
        for inst in universe.instruments:
            iid = inst["instrument_id"]
            if iid not in universe.stored:
                continue
            own = _own_series(universe, inst)
            out.append(Candidate(
                instrument_id=iid, role=inst["role"], region_scope=inst["region_scope"],
                returns=_converted(universe, own.returns, own.currency, currency),
                profile_by_state=universe.stored[iid]["profile"],
            ))
        cache[key] = out
    return cache[key]


def estimate_view(
    universe: Universe,
    instrument: dict,
    method: ProfileMethod,
    currency: str | None,
    cache: dict | None = None,
) -> dict:
    """One instrument's profile under ``method`` in ``currency``, computed on request.

    With the cascade and no currency this is the stored cascade profile, read back
    unchanged. Anything else, the served default included, is computed in memory and
    never stored.
    """
    from engines.fund_map.forward import KNOT_INDEX, estimate_forward, smooth_forward
    from engines.fund_map.estimate import fit_shape

    cache = cache if cache is not None else {}
    iid = instrument["instrument_id"]
    role = universe.roles[instrument["role"]]
    extra: dict = {}

    if method is ProfileMethod.CASCADE and currency is None and iid in universe.stored:
        s = universe.stored[iid]
        own = _own_series(universe, instrument)
        return {
            "profile": list(s["profile"]), "methods": list(s["methods"]),
            "n_obs": list(s["n_obs"]), "coverage": s["coverage"],
            "borrowed_from": s["borrowed_from"], "match_score": s["match_score"],
            "n_obs_total": s["n_obs_total"], "series": own.label,
            "series_currency": own.currency, "currency": own.currency, "stored": True,
        }

    peers = [c for c in _candidates(universe, currency, cache) if c.instrument_id != iid]
    forward = method in (ProfileMethod.FORWARD_12M, ProfileMethod.FORWARD_12M_SMOOTHED)
    if forward:
        choice = choose_forward_series(universe, instrument)
    else:
        choice = _own_series(universe, instrument)
    series = _converted(universe, choice.returns, choice.currency, currency)
    monthly = [MonthlyReturn(p, v) for p, v in sorted(series.items())]

    if forward:
        result = estimate_forward(
            iid, instrument["role"], series, universe.signal, universe.state_map, role,
            fit=fit_shape(monthly, peers, role=instrument["role"]))
        if method is ProfileMethod.FORWARD_12M_SMOOTHED:
            result = smooth_forward(result)
        profile = result.profile
        extra = {
            "phases": [
                {"phase": PHASE_NAMES[p.phase], "windows": p.windows, "n_eff": p.n_eff,
                 "value": p.value, "method": p.method.value}
                for p in result.phases
            ],
            "after_stress": [
                {"start": w.start, "state": w.state, "phase": PHASE_NAMES[w.phase],
                 "forward_12m": w.value}
                for w in result.windows if w.phase <= 1
            ],
            "amplitude": result.amplitude,
            # The crisis-tagged months' *own* returns, in the view's currency: what a tail
            # hedge is judged on (FMRE-24), since a forward window starts the month after.
            "crisis_months": [
                {"period": period, "state": state, "return": series[period]}
                for period, state in (
                    (period, universe.state_map.state_for(universe.signal[period]))
                    for period in sorted(series) if period in universe.signal)
                if state in CRISIS_STATES
            ],
        }
        if result.smoothing is not None and result.unsmoothed is not None:
            # The measured values stay available beside the smoothed ones.
            extra["unsmoothed"] = {
                "profile": list(result.unsmoothed.profile_by_state),
                "methods": [m.value for m in result.unsmoothed.methods_by_state],
            }
            extra["smoothing"] = {
                "passes": result.smoothing.passes,
                "tolerance": result.smoothing.tolerance,
                "knot_states": [k + 1 for k in KNOT_INDEX],
                "knot_shift": list(result.smoothing.knot_shift),
                "held_for_sign": list(result.smoothing.held),
            }
    else:
        profile = estimate_instrument(
            instrument_id=iid, role=instrument["role"], returns=monthly,
            signal_by_period=universe.signal, state_map=universe.state_map,
            role_profile=role, candidates=peers, region_scope=instrument["region_scope"],
            profile_method=method,
        )
    return {
        "profile": list(profile.profile_by_state),
        "methods": [m.value for m in profile.methods_by_state],
        "n_obs": list(profile.n_obs_by_state),
        "coverage": profile.coverage.value,
        "borrowed_from": profile.borrowed_from,
        "match_score": profile.match_score,
        "n_obs_total": profile.n_obs_total,
        "series": choice.label,
        "series_currency": choice.currency,
        "currency": currency or choice.currency,
        "stored": False,
        **extra,
    }


#: The crisis band and the boom band on the 25-state grid, 1-based.
CRISIS_STATES = range(1, 6)
BOOM_STATES = range(21, 26)


#: The phase knots of crisis and boom (states 3 and 23), zero-based.
CRISIS_KNOT, BOOM_KNOT = 2, 22


class ProtectionType(str, Enum):
    """Which rule a protection instrument is judged by (owner, 29.09.2026, FMRE-24)."""

    #: A tail hedge pays inside the shock: judged on the crisis months themselves.
    TAIL_HEDGE = "tail_hedge"
    #: Cash does not pay in a crisis, it does not fall: judged on never being negative.
    CASH = "cash"
    #: Everything else: the 12 month forward rule of FMRE-19.
    FORWARD = "forward"


#: How the type is read from the register, by what an instrument *is* rather than by its
#: name. Cash by its asset class; a tail hedge by the volatility index its price proxy
#: tracks (the Cboe VIX Tail Hedge index, or short-term VIX futures).
CASH_ASSET_CLASSES = frozenset({"Cash"})
TAIL_HEDGE_PROXIES = frozenset({"VXTH", "VIXY"})

#: The rule of each type, as the owner stated it, for reports and the bench.
PROTECTION_RULES = {
    ProtectionType.TAIL_HEDGE: "pays in the crisis month itself: the mean log return of "
                               "the months tagged crisis (states 1 to 5) is above zero",
    ProtectionType.CASH: "never negative: every one of the 25 states at or above zero",
    ProtectionType.FORWARD: "12 month forward: every crisis state (1 to 5) above zero in "
                            "CHF, EUR and USD; the profile's maximum in states 1 to 5 in "
                            "the source currency",
}


def protection_type(instrument: dict) -> ProtectionType:
    """The protection type of a register row (``asset_class``, ``proxy_symbol``)."""
    if instrument.get("asset_class") in CASH_ASSET_CLASSES:
        return ProtectionType.CASH
    if instrument.get("proxy_symbol") in TAIL_HEDGE_PROXIES:
        return ProtectionType.TAIL_HEDGE
    return ProtectionType.FORWARD


def protection_check(view: dict,
                     kind: ProtectionType = ProtectionType.FORWARD) -> dict:
    """R-003 acceptance, per protection type (FMRE-24), on one computed view.

    ``kind`` selects the rule (:data:`PROTECTION_RULES`). The forward-rule fields are
    reported for every type, so a reader can see how a tail hedge or cash reads on it;
    ``passed`` is the verdict under the instrument's own rule.

    **The forward rule** is R-003's acceptance as restated by the owner on 29.09.2026
    (FMRE-19), below.

    **Positive in crisis in every currency; highest in the crisis states in the source
    currency.** Positivity is required of all five crisis states, the extrapolated tail
    included. "Highest in the crisis states" means the profile's maximum over the 25
    states lies in states 1 to 5, and it is required only where the view is measured in
    the currency its series is quoted in (``series_currency``): read in another currency,
    the exchange rate's own move after crisis months is part of the profile, and the owner
    accepted that currency effect rather than asking the asset to beat it.

    ``crisis_above_boom`` (the crisis knot, state 3, above the boom knot, state 23) was the
    second leg of the acceptance before the restatement and is still reported.
    """
    import math

    p = view["profile"]
    crisis = [p[s - 1] for s in CRISIS_STATES]
    boom = [p[s - 1] for s in BOOM_STATES]
    positive = min(crisis) > 0
    above = p[CRISIS_KNOT] > p[BOOM_KNOT]
    highest = max(range(25), key=lambda i: p[i]) + 1 in CRISIS_STATES
    in_source = view.get("currency") == view.get("series_currency")
    out = {
        "type": kind.value, "rule": PROTECTION_RULES[kind],
        "crisis_min": min(crisis), "crisis_knot": p[CRISIS_KNOT],
        "crisis_method": view["methods"][CRISIS_KNOT],
        "boom_max": max(boom), "boom_knot": p[BOOM_KNOT],
        "boom_method": view["methods"][BOOM_KNOT],
        "positive_in_crisis": positive, "crisis_above_boom": above,
        "highest_in_crisis": highest, "in_source_currency": in_source,
        "profile_min": min(p),
    }
    if kind is ProtectionType.FORWARD:
        out["passed"] = positive and (highest or not in_source)
    elif kind is ProtectionType.CASH:
        out["passed"] = min(p) >= 0
    else:
        months = [m["return"] for m in view.get("crisis_months", []) if m["return"] > -1.0]
        mean_log = (math.fsum(math.log1p(r) for r in months) / len(months)
                    if months else None)
        out.update(crisis_months=len(months), crisis_month_mean_log=mean_log,
                   crisis_months_positive=sum(r > 0 for r in months))
        out["passed"] = mean_log is not None and mean_log > 0
    return out


def estimator_comparison(conn: db.Connection, calibration_id: str, *,
                         currency: str | None = None) -> dict:
    """Cascade, D2 and the 12 month forward measurement side by side (R-002).

    Over the instruments that have their own history; one without history has nothing
    for any estimator to measure and would only dilute the comparison with seeds.
    """
    universe = load_universe(conn, calibration_id)
    cache: dict = {}
    methods = (ProfileMethod.CASCADE, ProfileMethod.SHAPE_SCALED, ProfileMethod.FORWARD_12M,
               ProfileMethod.FORWARD_12M_SMOOTHED)
    rows = []
    for inst in universe.instruments:
        if not universe.returns.get(inst["instrument_id"]):
            continue
        views = {m.value: estimate_view(universe, inst, m, currency, cache) for m in methods}
        rows.append({
            "instrument_id": inst["instrument_id"], "name": inst["name"],
            "role": inst["role"], "register_currency": inst["currency"],
            "protection_type": (protection_type(inst).value
                                if inst["role"] == "protection" else None),
            "views": views,
        })

    summary = {}
    for m in methods:
        jumps, largest, labels, negative, failing, shifts = [], [], {}, [], [], []
        for r in rows:
            v = r["views"][m.value]
            p = v["profile"]
            jumps.append(sum(abs(b - a) for a, b in zip(p, p[1:])) / (len(p) - 1))
            largest.append(max(abs(b - a) for a, b in zip(p, p[1:])))
            if "smoothing" in v:
                shifts.extend(abs(x) for x in v["smoothing"]["knot_shift"])
            for label in v["methods"]:
                labels[label] = labels.get(label, 0) + 1
            if r["role"] == "protection":
                check = protection_check(v, ProtectionType(r["protection_type"]))
                v["protection_check"] = check
                if p[2] < 0:
                    negative.append(r["name"])
                if not check["passed"]:
                    failing.append(r["name"])
        total = sum(labels.values()) or 1
        summary[m.value] = {
            "instruments": len(rows),
            "mean_abs_jump": sum(jumps) / len(jumps) if jumps else None,
            # The largest step between neighbouring states, averaged over instruments.
            "mean_largest_jump": sum(largest) / len(largest) if largest else None,
            # Smoothed method only: the largest move the smoother made to a phase value.
            "max_knot_shift": max(shifts) if shifts else None,
            "protection_negative_in_crisis": negative,
            "protection_failing_acceptance": failing,
            "state_share_by_label": {k: labels[k] / total for k in sorted(labels)},
        }
    return {
        "calibration_id": calibration_id,
        "state_map_id": universe.map_id,
        "currency": currency,
        "fx_loaded": universe.in_chf is not None,
        "summary": summary,
        "instruments": rows,
        "roles": {k: list(v.profile_by_state) for k, v in universe.roles.items()},
    }


# ---------------------------------------------------------------------------
# The deflator: inflation per regime state and currency (nominal and real view)
# ---------------------------------------------------------------------------

#: Engine 01's shared schema, where ``inflation.cpi_yoy`` lives (read-only; the role holds
#: ``SELECT`` there). Not ``config.datafeed_schema``, which is this engine's private copy
#: ``fmre_feed`` and holds no monthly CPI.
CPI_SCHEMA = os.environ.get("INSTRUMENTS_CPI_SCHEMA", "datafeed")


@dataclass(frozen=True)
class CpiSeries:
    """One currency's year-on-year inflation by month, and where it came from."""

    currency: str
    yoy: dict[str, float]          # YYYY-MM -> simple rate
    index: str
    source: str
    snapshot_id: str | None


def load_cpi_yoy(conn: db.Connection, currency: str) -> CpiSeries:
    """The monthly year-on-year CPI of a currency's index (decision 3), from datafeed.

    Read from the latest snapshot of Engine 01. EUR takes the euro-area HICP from 1999 and
    German CPI before, month by month, only where German data reaches (in the snapshot of
    January 2026 both start in 2006, so EUR is HICP throughout).
    """
    from engines.fund_map.inflation import CPI_SERIES, EUR_HICP_FROM, INDEX

    if currency not in INDEX:
        raise ValueError(f"{currency!r} has no inflation index; one of {sorted(INDEX)}")
    schema = CPI_SCHEMA
    snap = conn.execute(
        f"SELECT snapshot_id FROM {schema}.snapshot ORDER BY built_at DESC, snapshot_id DESC "
        f"LIMIT 1").fetchone()
    snapshot_id = snap["snapshot_id"] if snap else None
    series: dict[str, dict[str, float]] = {}
    for country, _, _ in INDEX[currency]:
        series[country] = {
            r["date"][:7]: r["value"]
            for r in conn.execute(
                f"SELECT date, value FROM {schema}.observation WHERE series_id = %s AND "
                f"country = %s AND snapshot_id = %s AND value IS NOT NULL",
                (CPI_SERIES, country, snapshot_id))
        }
    if currency == "EUR":
        eu, de = series["EU"], series["DE"]
        yoy = {p: v for p, v in de.items() if p < EUR_HICP_FROM}
        yoy.update({p: v for p, v in eu.items() if p >= EUR_HICP_FROM})
    else:
        yoy = series[INDEX[currency][0][0]]
    index = "; ".join(f"{name} ({code}, datafeed {CPI_SERIES} {country})"
                      for country, code, name in INDEX[currency])
    return CpiSeries(currency, yoy, index,
                     f"datafeed:{CPI_SERIES}@{snapshot_id}", snapshot_id)


def inflation_curve(conn: db.Connection, signal: dict[str, int], state_map: StateMap,
                    currency: str):
    """``pi(s, c)``: the historical deflator of one currency (decision 1)."""
    from engines.fund_map.inflation import state_curve
    cpi = load_cpi_yoy(conn, currency)
    return state_curve(currency, cpi.yoy, signal, state_map,
                       index=cpi.index, source=cpi.source)


def inflation_curves(conn: db.Connection, signal: dict[str, int], state_map: StateMap,
                     scenario: dict | None = None,
                     currencies: Sequence[str] = ("CHF", "EUR", "USD")) -> dict:
    """The deflator of every currency: historical, or the scenario's (decision 2).

    ``scenario`` is ``{"policy", "inflation_final_12m", "regime_id"}`` of a scenario Regime;
    its inflation applies to every state and, being the policy's path rather than a
    currency's, to every currency alike.
    """
    from engines.fund_map.inflation import scenario_curve
    if scenario is not None:
        return {c: scenario_curve(c, scenario["inflation_final_12m"],
                                  policy=scenario["policy"], regime_id=scenario["regime_id"])
                for c in currencies}
    return {c: inflation_curve(conn, signal, state_map, c) for c in currencies}


# ---------------------------------------------------------------------------
# Inflation pass-through (beta) under a scenario Regime (owner, 29.09.2026; FMRE-33..37)
# ---------------------------------------------------------------------------


class PassThroughError(ValueError):
    """Raised on a stored calibration that disagrees with the code, or a bad override."""


def pass_through_calibration() -> dict:
    """The house table as code states it: version, id, source and payload."""
    from engines.fund_map import pass_through as pt
    payload = pt.calibration_payload()
    return {"version": pt.CALIBRATION_VERSION,
            "calibration_id": db.content_id("IPT", payload),
            "source": pt.SOURCE, "payload": payload}


def ensure_pass_through_calibration(conn: db.Connection) -> dict:
    """Store the house table under its version (once), and check the stored one agrees.

    Append-only: a version is written once and never changed (the table's trigger refuses
    an UPDATE). Code that changes the table without a new version is refused here, loudly,
    instead of serving figures under a version whose stored content says otherwise.
    """
    cal = pass_through_calibration()
    conn.execute(
        "INSERT INTO inflation_beta_calibration (version, calibration_id, created_at, source, "
        "payload_json) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
        (cal["version"], cal["calibration_id"], db.utc_now(), cal["source"],
         db.dumps(cal["payload"])))
    row = conn.execute(
        "SELECT calibration_id, created_at FROM inflation_beta_calibration WHERE version = %s",
        (cal["version"],)).fetchone()
    if row["calibration_id"] != cal["calibration_id"]:
        raise PassThroughError(
            f"the stored inflation pass-through calibration {cal['version']} is "
            f"{row['calibration_id']}, the code's is {cal['calibration_id']}: the house table "
            f"changed without a new version. Bump pass_through.CALIBRATION_VERSION.")
    return dict(cal, created_at=row["created_at"])


def latest_beta_overrides(conn: db.Connection) -> dict[str, dict]:
    """The override in force per instrument: its latest version."""
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id) * FROM inflation_beta_override "
        "ORDER BY instrument_id, version DESC").fetchall()
    return {r["instrument_id"]: dict(r) for r in rows}


def effective_beta(instrument: dict, override: dict | None) -> dict:
    """House type, house beta and duration, the override, and what is in force."""
    from engines.fund_map import pass_through as pt
    key, rule = pt.classify(instrument)
    kind = pt.TYPES[key]
    beta, source = kind.beta, "house"
    duration = kind.duration
    duration_source = "house" if duration is not None else None
    if override is not None:
        if override["beta"] is not None:
            beta, source = override["beta"], "override"
        if override["duration"] is not None:
            duration, duration_source = override["duration"], "override"
    return {
        "type": key, "type_label": kind.label, "rule": pt.RULES[rule][1],
        "house_beta": kind.beta, "house_duration": kind.duration,
        "override": ({k: override[k] for k in ("version", "beta", "duration", "reason",
                                               "set_by", "set_at", "calibration_version")}
                     if override is not None else None),
        "beta": beta, "source": source,
        "duration": duration, "duration_source": duration_source,
    }


def effective_betas(conn: db.Connection, instruments: Sequence[dict]) -> dict[str, dict]:
    overrides = latest_beta_overrides(conn)
    return {i["instrument_id"]: effective_beta(i, overrides.get(i["instrument_id"]))
            for i in instruments}


def put_beta_override(conn: db.Connection, instrument_id: str, *, beta: float | None,
                      duration: float | None, reason: str, set_by: str) -> dict:
    """Append the next override version of one instrument. Never updates a row."""
    from engines.fund_map import pass_through as pt
    if beta is not None and not (pt.BETA_MIN <= beta <= pt.BETA_MAX):
        raise PassThroughError(f"beta {beta!r} is outside {pt.BETA_MIN} .. {pt.BETA_MAX}")
    if duration is not None and not (pt.DURATION_MIN <= duration <= pt.DURATION_MAX):
        raise PassThroughError(
            f"duration {duration!r} is outside {pt.DURATION_MIN} .. {pt.DURATION_MAX} years")
    if not reason.strip():
        raise PassThroughError("a reason is required")
    if not set_by.strip():
        raise PassThroughError("set_by is required")
    cal = ensure_pass_through_calibration(conn)
    row = conn.execute(
        "INSERT INTO inflation_beta_override (instrument_id, version, beta, duration, reason, "
        "set_by, set_at, calibration_version) SELECT %s, COALESCE(MAX(version), 0) + 1, %s, "
        "%s, %s, %s, %s, %s FROM inflation_beta_override WHERE instrument_id = %s "
        "RETURNING *",
        (instrument_id, beta, duration, reason.strip(), set_by.strip(), db.utc_now(),
         cal["version"], instrument_id)).fetchone()
    return dict(row)


def historical_inflation_curves(conn: db.Connection, signal: dict[str, int],
                                state_map: StateMap) -> dict:
    """The historical deflator of every currency: ``pi_hist(s)`` of the pass-through."""
    return inflation_curves(conn, signal, state_map, None)


def pass_through_view(view: dict, entry: dict, pi_s: float, curves: dict,
                      currency: str) -> dict:
    """One computed view carried to the scenario, nominal (``pass_through.scenario_nominal``).

    ``currency`` names the historical deflator (the currency the view is measured in);
    the unsmoothed profile, where present, is carried the same way. Nothing else moves.
    """
    from engines.fund_map.inflation import NotComputable, curve_reason
    from engines.fund_map.pass_through import scenario_nominal
    curve = curves[currency]
    if not curve.computable():
        raise NotComputable("the historical deflator of the pass-through: "
                            + curve_reason(curve))
    hist_log = [s.log_inflation for s in curve.states]

    def carry(values):
        return scenario_nominal(values, hist_log, pi_s, entry["beta"], entry["duration"])

    out = dict(view, profile=carry(view["profile"]))
    if "unsmoothed" in view:
        out["unsmoothed"] = dict(view["unsmoothed"],
                                 profile=carry(view["unsmoothed"]["profile"]))
    return out


def pass_through_role(values: Sequence[float], blend: dict, pi_s: float,
                      curves: dict) -> list[float]:
    """One role profile carried to the scenario, nominal, by its blended beta (FMRE-40).

    A role profile is the long annual record in USD, so its historical real return is
    measured with the historical USD inflation; ``blend`` is ``pass_through.role_blend``.
    """
    from engines.fund_map.inflation import NotComputable, curve_reason
    from engines.fund_map.pass_through import scenario_nominal
    curve = curves["USD"]
    if not curve.computable():
        raise NotComputable("the historical deflator of the role pass-through (USD): "
                            + curve_reason(curve))
    return scenario_nominal(list(values), [s.log_inflation for s in curve.states], pi_s,
                            blend["beta"], blend["duration"])


def shape_checks(means: dict[str, list[float]]) -> list[tuple[str, bool]]:
    """The eight shape assertions of manual section 11.3, on block phase means.

    Statements about *blocks*, so no role composition can change them; they are rerun for
    every Income candidate only to show that.
    """
    def peak(key: str) -> str:
        values = means[key]
        return PHASE_NAMES[values.index(max(values))]

    return [
        ("equity is monotone in the environment",
         all(b >= a for a, b in zip(means["equity"], means["equity"][1:]))),
        ("government bonds jump from contraction into crisis",
         means["gov_bonds"][0] > means["gov_bonds"][1]),
        ("commodities peak in contraction", peak("commodities") == "contraction"),
        ("agriculture peaks in contraction", peak("agriculture") == "contraction"),
        ("gold peaks in crisis", peak("gold") == "crisis"),
        ("gold is negative in boom", means["gold"][4] < 0),
        ("real estate is at its worst in crisis",
         means["real_estate"][0] == min(means["real_estate"])),
        ("the short rate falls in crisis and rises as conditions improve",
         means["short_rate"][0] < means["short_rate"][2] < means["short_rate"][4]),
    ]


def _pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    from engines.fund_map.estimate import correlation
    return correlation(list(a), list(b))


def income_candidates(conn: db.Connection, calibration_id: str) -> dict:
    """Review R-001: the Income compositions beside Stabilisation.

    The owner chose candidate A on 29.09.2026 and it is now ROLE_MAP's Income; the others
    stay beside it so the choice can be re-read. Nothing here is stored. The first
    candidate ("before R-001") is not in the current calibration's role curves, so the
    role-change list compares every candidate against the curves as stored (A's Income).
    For each candidate: the phase values and the 25-state curve,
    the owner's acceptance target (Income above Stabilisation in expansion and boom and
    below it in crisis), the eight block shape checks, the two role checks, how far apart
    the two curves are, and which instruments would change role under a nearest-curve
    reading of their 12 month forward profiles.
    """
    from engines.fund_map.roles import INCOME_CANDIDATES, compose_phase_means, role_curve

    blocks = load_block_profiles(conn, calibration_id)
    means = {k: [p["central"] for p in v["phases"]] for k, v in blocks.items()}
    stored = load_role_profiles(conn, calibration_id)
    stab_phase = list(stored["stabilisation"]["phase_means"])
    stab_curve = list(stored["stabilisation"]["profile"])
    checks = shape_checks(means)

    # Nearest-curve role of every instrument with history, from its forward profile.
    universe = load_universe(conn, calibration_id)
    forward = {}
    cache: dict = {}
    for inst in universe.instruments:
        if universe.returns.get(inst["instrument_id"]):
            forward[inst["instrument_id"]] = (
                inst, estimate_view(universe, inst, ProfileMethod.FORWARD_12M, None, cache))

    def nearest(curves: dict[str, list[float]]) -> dict[str, str]:
        out = {}
        for iid, (_, view) in forward.items():
            scored = {r: _pearson(view["profile"], c) for r, c in curves.items()}
            out[iid] = max(scored, key=lambda r: -2 if scored[r] is None else scored[r])
        return out

    base_curves = {r: list(v["profile"]) for r, v in stored.items()}
    base_nearest = nearest(base_curves)

    rows = []
    for spec in INCOME_CANDIDATES:
        phase = compose_phase_means(means, spec.weights)
        curve = role_curve(phase)
        target = {
            "above_stabilisation_in_expansion": phase[3] > stab_phase[3],
            "above_stabilisation_in_boom": phase[4] > stab_phase[4],
            "below_stabilisation_in_crisis": phase[0] < stab_phase[0],
        }
        bands = {
            "crisis_states_below": sum(curve[i] < stab_curve[i] for i in range(0, 5)),
            "expansion_boom_states_above": sum(curve[i] > stab_curve[i] for i in range(15, 25)),
        }
        curves = dict(base_curves, income=curve)
        after = nearest(curves)
        changed = [
            {"instrument_id": iid, "name": forward[iid][0]["name"],
             "registered": forward[iid][0]["role"],
             "nearest_now": base_nearest[iid], "nearest_with_candidate": after[iid]}
            for iid in forward if after[iid] != base_nearest[iid]
        ]
        rows.append({
            "weights": spec.weights,
            "basis": spec.basis,
            "phase_names": list(PHASE_NAMES),
            "phase_values": phase,
            "curve": curve,
            "target": target,
            "target_met": all(target.values()),
            "state_bands": bands,
            "gap_to_stabilisation": {
                "mean_abs_by_state": sum(abs(a - b) for a, b in zip(curve, stab_curve)) / 25,
                "min_abs_by_phase": min(abs(a - b) for a, b in zip(phase, stab_phase)),
                "curve_correlation": _pearson(curve, stab_curve),
            },
            "shape_checks": [{"assertion": n, "passed": bool(ok)} for n, ok in checks],
            "shape_checks_passed": sum(1 for _, ok in checks if ok),
            "role_checks": {
                "protection_beats_gain_in_crisis":
                    stored["protection"]["phase_means"][0] > stored["gain"]["phase_means"][0],
                "gain_beats_protection_in_boom":
                    stored["gain"]["phase_means"][4] > stored["protection"]["phase_means"][4],
            },
            "role_changes_nearest_curve": changed,
        })
    income_with_history = [
        inst["name"] for inst, _ in forward.values() if inst["role"] == "income"]
    return {
        "calibration_id": calibration_id,
        "stabilisation": {"phase_values": stab_phase, "curve": stab_curve,
                          "weights": stored["stabilisation"]["weights"]},
        "candidates": rows,
        "income_instruments_reshaped_under_d2": income_with_history,
        "reading": (
            "Nothing here is published. The eight shape checks are statements about the "
            "blocks and pass identically under every candidate. /v1/data/classification "
            "flags on equity beta and crisis-month returns and does not read the role "
            "curves, so its flags cannot change with the Income composition; the "
            "role-change list is therefore a nearest-curve reading instead: each "
            "instrument's 12 month forward profile against the four role curves by "
            "correlation across the 25 states. Under D2 every Income instrument inherits "
            "the Income shape, so any change here re-shapes all of them."
        ),
    }


def record_run(
    conn: db.Connection,
    *,
    engine: str,
    inputs: dict,
    outputs: dict,
    started: float,
    status: str = "ok",
) -> str:
    """Write a RunManifest. No figure leaves an engine without one."""
    finished = time.perf_counter()
    run_id = db.content_id("RUN", {"engine": engine, "inputs": inputs, "outputs": outputs})
    conn.execute(
        db.upsert(
            "run_manifest",
            (
                "run_id", "engine", "engine_version", "started_at", "finished_at",
                "wall_clock_ms", "inputs_json", "params_hash", "outputs_json", "status",
            ),
            ("run_id",),
        ),
        (
            run_id, engine, ENGINE_VERSION, db.utc_now(), db.utc_now(),
            (finished - started) * 1000.0, db.dumps(inputs),
            db.content_id("PRM", inputs), db.dumps(outputs), status,
        ),
    )
    return run_id
