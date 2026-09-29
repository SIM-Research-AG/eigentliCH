"""The versioned HTTP surface for the Fund Map engine.

Everything is under ``/v1``. The App -- and, for now, the test bench in ``testbench/`` --
is generated against the OpenAPI document this produces, which is the only contract
between them; manual section 7 is explicit that the front end is a separate deliverable
and the boundary is an OpenAPI document rather than a shared repository.

**The endpoints divide into four groups, and the division is the data flow.**

``/v1/calibration/*``   the one-off scientific calibration: what the long record says
``/v1/roles`` and ``/v1/return-set``
                        the published contract -- four role profiles, no moments
``/v1/instruments/*``   the expandable register and each instrument's estimated profile
``/v1/diagnostics/*``   the checks that say whether any of the above should be believed

Nothing here writes advice, and nothing here is per-user. The Fund Map sits on the
population side of the privacy boundary: it carries no household data, it is cached once
and read by reference, and that is both a privacy guarantee and the caching design.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.data import router as data_router
from api.datafeed import router as datafeed_router
from api.integrity import router as integrity_router
from api.deps import get_conn
from contracts.instrument import InstrumentIn, InstrumentOut, ReturnsIn
from contracts.return_set import (
    ContractError,
    Profile,
    Provenance,
    ReturnSet,
    StateValue,
    reject_moments,
)
from engines.fund_map import service
from engines.fund_map.calibrate import BLOCKS, PHASE_KNOTS, state_axis
from engines.fund_map.currency import CurrencyError
from engines.fund_map.estimate import ProfileMethod
from engines.fund_map.phases import PHASE_NAMES, PHASE_VALUES
from engines.fund_map.state_map import expected_return
from store import db
from store.etl.bootstrap import slug

TESTBENCH = Path(__file__).resolve().parent.parent / "testbench"

#: D-01: the currencies a reader may ask for. Every currency parameter is opt-in; omitted,
#: each series stays in the currency it was measured in, which is what is published.
CURRENCY_PATTERN = r"^(CHF|EUR|USD)$"

#: The estimator choice. Omitted, the configured default (``service.DEFAULT_PROFILE_METHOD``,
#: the 12 month forward measurement lightly smoothed, FMRE-22); ``cascade`` without a
#: currency reads the stored profiles back unchanged.
METHOD_PATTERN = r"^(cascade|shape_scaled|forward_12m|forward_12m_smoothed)$"

app = FastAPI(
    title="sim-tech Instruments -- Fund Map",
    version=service.ENGINE_VERSION,
    description=(
        "Per-state return profiles for the instrument universe. Publishes a 25-state profile "
        "per role and per instrument, every value carrying the method that produced it. "
        "Deliberately publishes no mean, variance or covariance."
    ),
)


#: Origins allowed to call this API from a browser. The default is permissive because the
#: test bench is routinely opened straight off disk, and a page loaded from ``file://``
#: sends ``Origin: null`` -- without a wildcard the browser refuses every call and the
#: symptom is an unhelpful "Failed to fetch".
#:
#: **This is a development default and must be narrowed before deployment.** Set
#: ``INSTRUMENTS_CORS_ORIGINS`` to a comma-separated list to do that. It is safe as it
#: stands only because the engine binds to localhost, holds no user data (the Fund Map is
#: on the population side of the privacy boundary) and carries no authentication to steal.
#: The moment any of those three stops being true, this has to change.
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("INSTRUMENTS_CORS_ORIGINS", "*").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    # Credentials must stay off: a wildcard origin with credentials is rejected by every
    # browser, and this API has no session to send anyway.
    allow_credentials=False,
)




app.include_router(data_router)
app.include_router(integrity_router)
app.include_router(datafeed_router)


def _require_calibration(conn: db.Connection) -> str:
    calibration_id = service.latest_calibration_id(conn)
    if calibration_id is None:
        raise HTTPException(
            status_code=503,
            detail="no calibration in the store. Run: python -m store.etl.bootstrap",
        )
    return calibration_id


def _profile_payload(key: str, kind: str, role: str | None, profile: list[float],
                     methods: list[str], n_obs: list[int], *, coverage: str,
                     borrowed_from: str | None = None,
                     match_score: float | None = None) -> Profile:
    return Profile(
        key=key,
        kind=kind,
        role=role,
        coverage=coverage,  # type: ignore[arg-type]
        borrowed_from=borrowed_from,
        match_score=match_score,
        states=tuple(
            StateValue(state=i + 1, value=profile[i], method=methods[i],  # type: ignore[arg-type]
                       n_obs=n_obs[i])
            for i in range(len(profile))
        ),
    )


def _weakest(methods: list[str]) -> str:
    from engines.fund_map.calibrate import METHOD_STRENGTH, Method
    return min((Method(m) for m in methods), key=METHOD_STRENGTH.index).value


# ---------------------------------------------------------------------------
# Health and metadata
# ---------------------------------------------------------------------------


@app.get("/v1/health", tags=["meta"])
def health(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Whether the store is populated, what it holds, and which store it is.

    ``store`` reports the backend and its target. It never carries the password -- the
    summary is built by :func:`store.db.describe`, which reports only whether one is set.
    Which database answered is worth surfacing: the same engine against an empty schema
    looks identical to one against a stale one, and "which server am I actually on?" is
    the first question when a figure looks wrong.
    """
    calibration_id = service.latest_calibration_id(conn)
    counts = {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("long_series", "market_risk_signal", "instrument",
                      "instrument_return", "calibration", "run_manifest")
    }
    return {
        "status": "ok" if calibration_id else "uncalibrated",
        "engine": service.ENGINE,
        "engine_version": service.ENGINE_VERSION,
        "calibration_id": calibration_id,
        "store": db.describe(),
        "counts": counts,
    }


@app.get("/v1/axis", tags=["meta"])
def axis() -> dict[str, Any]:
    """The 25-state axis and the five phases it interpolates between.

    Published because every consumer needs it to read a profile, and hard-coding 25 in two
    places is how the two places drift apart.
    """
    return {
        "state_grid": 25,
        "state_axis": state_axis(),
        "phase_knots": list(PHASE_KNOTS),
        "phase_names": list(PHASE_NAMES),
        "phase_cycle_values_sigma": list(PHASE_VALUES),
        "note": (
            "States sit at 0.6..5.4 in steps of 0.2 on a phase-ordinal axis. The five phase "
            "estimates land on states 3, 8, 13, 18 and 23; the rest are filled."
        ),
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@app.get("/v1/calibration", tags=["calibration"])
def calibration(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The current calibration's header: window, parameters, sources, phase counts."""
    calibration_id = _require_calibration(conn)
    row = conn.execute(
        "SELECT * FROM calibration WHERE calibration_id = %s", (calibration_id,)
    ).fetchone()
    return {
        "calibration_id": row["calibration_id"],
        "created_at": row["created_at"],
        "estimator": row["estimator"],
        "window": [row["first_year"], row["last_year"]],
        "state_grid": row["state_grid"],
        "parameters": db.loads(row["params_json"]),
        "source_sha256": db.loads(row["sources_json"]),
        "phase_counts": db.loads(row["phase_counts_json"]),
    }


@app.get("/v1/calibration/blocks", tags=["calibration"])
def calibration_blocks(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The eight long-record block profiles.

    Diagnostic, not contract. They are retained because the six shape assertions in manual
    section 11.3 are statements about blocks and cannot be checked against roles.
    """
    calibration_id = _require_calibration(conn)
    blocks = service.load_block_profiles(conn, calibration_id)
    return {
        "calibration_id": calibration_id,
        "blocks": [
            {
                **blocks[spec.key],
                "note": spec.note,
            }
            for spec in BLOCKS
            if spec.key in blocks
        ],
    }


@app.get("/v1/market-environment", tags=["calibration"])
def market_environment(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The annual economic cycle and the phase each year was classified into."""
    rows = conn.execute(
        "SELECT year, cycle, phase, inflation FROM market_environment ORDER BY year"
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=503, detail="the market environment has not been built")
    return {
        "first_year": rows[0]["year"],
        "last_year": rows[-1]["year"],
        "unit": "sigma",
        "years": [
            {
                "year": r["year"],
                "cycle": r["cycle"],
                "phase": PHASE_NAMES[r["phase"]],
                "phase_index": r["phase"],
                "inflation": r["inflation"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# The published contract
# ---------------------------------------------------------------------------


@app.get("/v1/roles", tags=["return-set"])
def roles(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The four role profiles -- the stored calibration artefact."""
    calibration_id = _require_calibration(conn)
    stored = service.load_role_profiles(conn, calibration_id)
    return {
        "calibration_id": calibration_id,
        "roles": [
            {
                "role": r["role"],
                "basis": r["basis"],
                "members": r["members"],
                "weights": r["weights"],
                "phase_names": list(PHASE_NAMES),
                "phase_values": r["phase_means"],
                "n_obs_by_phase": r["n_obs_phase"],
                "states": [
                    {"state": i + 1, "value": r["profile"][i],
                     "method": r["methods"][i], "n_obs": r["n_obs"][i]}
                    for i in range(len(r["profile"]))
                ],
            }
            for r in stored.values()
        ],
    }


#: Where the Regime is confirmed before it is stamped. ``aggregation`` alone issues the
#: ``regime_id`` (Engine Building Guide section 4); this engine only checks that the id it
#: is asked to stamp is one aggregation serves.
AGGREGATION_URL = os.environ.get("INSTRUMENTS_AGGREGATION_URL", "http://127.0.0.1:8004")


def confirm_regime(regime_id: str) -> None:
    """Refuse to stamp a ``regime_id`` that aggregation does not serve.

    Standard library only, like the rest of the client path. An unknown id is the caller's
    error (422); an aggregation that cannot be reached is not, and says so (503). Stamping
    an unconfirmed id would pass a Regime that does not exist straight on to the optimiser.
    """
    url = f"{AGGREGATION_URL.rstrip('/')}/regime/{urllib.parse.quote(regime_id)}/current"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            served = json.loads(response.read()).get("regime_id")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                status_code=422,
                detail=f"aggregation serves no Regime {regime_id!r}; nothing was stamped",
            ) from exc
        raise HTTPException(
            status_code=503, detail=f"aggregation answered {exc.code} for {regime_id!r}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"cannot confirm {regime_id!r}: aggregation at {AGGREGATION_URL} unreachable",
        ) from exc
    if served != regime_id:
        raise HTTPException(
            status_code=503,
            detail=f"aggregation answered for {served!r} when asked for {regime_id!r}",
        )


@app.get("/v1/return-set", tags=["return-set"])
def return_set(
    include_instruments: bool = Query(True),
    include_blocks: bool = Query(False, description="Diagnostic block profiles."),
    regime_id: str | None = Query(
        None, min_length=1,
        description="The Regime to stamp, confirmed with aggregation first. Omitted, the "
                    "set carries regime_id null and every consumer downstream refuses it.",
    ),
    profile_method: str | None = Query(
        None, pattern=METHOD_PATTERN,
        description="The estimator for the instrument profiles. Omitted, the default: "
                    "forward_12m_smoothed (FMRE-22). cascade without a currency is the "
                    "stored cascade profiles, unchanged."),
    currency: str | None = Query(
        None, pattern=CURRENCY_PATTERN,
        description="D-01: measure the instrument profiles in CHF, EUR or USD. "
                    "Omitted, each series in its source currency."),
    conn: db.Connection = Depends(get_conn),
) -> JSONResponse:
    """The ``ReturnSet`` artefact, validated and checked for moments before it leaves.

    A payload containing a mean or a covariance is refused here rather than ignored --
    manual section 11.7 test 4. The check runs in production, not only in the suite.

    With ``regime_id`` the set is stamped against that Regime, after aggregation has
    confirmed it, and the id enters ``return_set_id``: the same profiles stamped against
    two Regimes are two artefacts. Without it the id is what it always was.

    **The estimator and the currency are part of every set's identity** (FMRE-22): both
    enter ``return_set_id``, the provenance notes and the run manifest, whether named or
    defaulted, so no two estimators' sets can travel under one id. Omitted, the estimator
    is the default, the 12 month forward measurement lightly smoothed, computed on request
    from the stored histories and public proxies and never stored; ``cascade`` without a
    currency reads the stored cascade profiles back unchanged. The pinned ids are in
    ``tests/test_default_pin.py``. The role profiles are the long annual record's, US data
    in USD 1870-2020, and are **not** converted: there is no exchange rate back to 1870 in
    the store. The notes say so.
    """
    default_method = service.configured_profile_method()
    method = ProfileMethod(profile_method) if profile_method else default_method
    computed = currency is not None or method is not ProfileMethod.CASCADE
    if regime_id is not None:
        confirm_regime(regime_id)
    started = time.perf_counter()
    calibration_id = _require_calibration(conn)
    header = conn.execute(
        "SELECT * FROM calibration WHERE calibration_id = %s", (calibration_id,)
    ).fetchone()
    map_id = service.latest_state_map_id(conn, calibration_id)

    stored = service.load_role_profiles(conn, calibration_id)
    role_profiles = tuple(
        _profile_payload(r["role"], "role", r["role"], r["profile"], r["methods"],
                         r["n_obs"], coverage=_weakest(r["methods"]))
        for r in stored.values()
    )

    instrument_profiles: tuple[Profile, ...] = ()
    if include_instruments:
        rows = conn.execute(
            "SELECT i.instrument_id, i.role, p.profile_json, p.methods_json, p.n_obs_json,      "
            "p.coverage, p.borrowed_from, p.match_score FROM instrument i JOIN "
            "instrument_profile p USING (instrument_id) WHERE p.calibration_id = %s AND i.active "
            "= 1 ORDER BY i.name",
            (calibration_id,),
        ).fetchall()
        instrument_profiles = tuple(
            _profile_payload(
                r["instrument_id"], "instrument", r["role"], db.loads(r["profile_json"]),
                db.loads(r["methods_json"]), db.loads(r["n_obs_json"]),
                coverage=r["coverage"], borrowed_from=r["borrowed_from"],
                match_score=r["match_score"],
            )
            for r in rows
        )
        if computed:
            try:
                universe = service.load_universe(conn, calibration_id)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            by_id = {i["instrument_id"]: i for i in universe.instruments}
            cache: dict = {}
            computed = []
            for r in rows:
                try:
                    view = service.estimate_view(
                        universe, by_id[r["instrument_id"]], method, currency, cache)
                except CurrencyError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                computed.append(_profile_payload(
                    r["instrument_id"], "instrument", r["role"], view["profile"],
                    view["methods"], view["n_obs"], coverage=view["coverage"],
                    borrowed_from=view["borrowed_from"], match_score=view["match_score"],
                ))
            instrument_profiles = tuple(computed)

    block_profiles: tuple[Profile, ...] = ()
    if include_blocks:
        blocks = service.load_block_profiles(conn, calibration_id)
        block_profiles = tuple(
            _profile_payload(b["key"], "block", b["role"], b["profile"], b["methods"],
                             b["n_obs"], coverage=_weakest(b["methods"]))
            for b in blocks.values()
        )

    signal = conn.execute(
        "SELECT MIN(period) AS lo, MAX(period) AS hi FROM market_risk_month"
    ).fetchone()

    payload = {
        "role_profiles": role_profiles,
        "instrument_profiles": instrument_profiles,
        "block_profiles": block_profiles,
        "calibration_id": calibration_id,
    }
    identity: dict[str, Any] = {"c": calibration_id,
                                "i": [p.key for p in instrument_profiles],
                                "b": bool(include_blocks)}
    if regime_id is not None:
        identity["r"] = regime_id
    notes = (
        "Profiles are annual log returns per state. The mandate's horizon governs; the "
        "ReturnSet is a property of the world, not of a household.",
        "Series are nominal and not de-trended. Real is obtained by subtracting current "
        "inflation at the point of use.",
        "Four of the 25 states are extrapolated beyond the hull of the five phase "
        "estimates, reproducing the published reference. They are labelled.",
    )
    # FMRE-22: the estimator and the currency are in every set's identity, defaulted or not.
    identity["m"] = method.value
    identity["ccy"] = currency
    run_inputs: dict[str, Any] = {"calibration_id": calibration_id, "state_map_id": map_id,
                                  "profile_method": method.value, "currency": currency}
    if method is default_method:
        how = ("the default estimator: the 12 month forward return after each month, "
               "measured per phase, read onto the 25 states by pchip and lightly smoothed "
               "across neighbouring states; computed on request."
               if method is ProfileMethod.FORWARD_12M_SMOOTHED else "the default estimator.")
    else:
        how = ("the stored cascade profiles, not the default estimator."
               if not computed else
               "computed on request; not the default estimator.")
    notes = notes + (
        f"Instrument profiles: profile_method={method.value} in "
        f"currency={currency or 'source'}; {how}",
        "Currency: " + (
            f"instrument profiles measured in {currency}, converted monthly at the "
            f"point of use before estimation. Role profiles are the long annual "
            f"record in USD and are not converted." if currency else
            "each instrument series in its source currency (CHF for the andersCH "
            "recovered returns, USD for public proxies)."),
    )
    artefact = ReturnSet(
        return_set_id=db.content_id("RS", identity),
        engine_version=service.ENGINE_VERSION,
        as_of=f"{header['last_year']}-12-31",
        role_profiles=role_profiles,
        instrument_profiles=instrument_profiles,
        block_profiles=block_profiles,
        provenance=Provenance(
            calibration_id=calibration_id,
            state_map_id=map_id or "",
            regime_id=regime_id,
            universe_version=service.UNIVERSE_VERSION,
            calibration_window=f"{header['first_year']}..{header['last_year']}",
            signal_window=f"{signal['lo']}..{signal['hi']}" if signal["lo"] else "",
            estimator=header["estimator"],
            source_sha256=db.loads(header["sources_json"]),
            notes=notes,
            # D-01: the measurement currency of a converted set; null on the default.
            currency=currency,
        ),
        run_id=service.record_run(
            conn, engine=service.ENGINE,
            inputs=run_inputs,
            outputs={"roles": len(role_profiles), "instruments": len(instrument_profiles)},
            started=started,
        ),
    )
    try:
        return JSONResponse(artefact.checked_dump())
    except ContractError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/state-map", tags=["return-set"])
def state_map(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The quantile bridge from the monthly signal axis to the calibration axis."""
    calibration_id = _require_calibration(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")
    meta = conn.execute("SELECT * FROM state_map_meta WHERE map_id = %s", (map_id,)).fetchone()
    rows = conn.execute(
        "SELECT * FROM state_map WHERE map_id = %s ORDER BY signal_state", (map_id,)
    ).fetchall()
    reachable = sorted({r["calib_state"] for r in rows})
    return {
        "map_id": map_id,
        "method": meta["method"],
        "note": meta["note"],
        "signal_window": [meta["signal_first"], meta["signal_last"]],
        "entries": [dict(r) for r in rows],
        "reachable_states": reachable,
        "unreachable_states": [s for s in range(1, 26) if s not in reachable],
        "coverage_warning": (
            "The bridge is many-to-one, so some calibration states cannot be reached from any "
            "signal column and their buckets are always empty. Those states are filled by "
            "interpolation and labelled accordingly."
        ),
    }


@app.get("/v1/market-risk-signal", tags=["return-set"])
def market_risk_signal(
    limit: int = Query(24, ge=1, le=600),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The most recent monthly readings, newest last."""
    rows = conn.execute(
        "SELECT * FROM market_risk_month ORDER BY period DESC LIMIT %s", (limit,)
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=503, detail="the monthly signal has not been loaded")
    periods = [r["period"] for r in rows]
    dist: dict[str, list[float]] = {p: [0.0] * 25 for p in periods}
    placeholders = ",".join(["%s"] * len(periods))
    for r in conn.execute(
        f"SELECT period, state, probability FROM market_risk_signal "
        f"WHERE period IN ({placeholders})", periods
    ):
        dist[r["period"]][r["state"] - 1] = r["probability"]
    return {
        "months": [
            {
                "period": r["period"],
                "modal_state": r["modal_state"],
                "mean_state": r["mean_state"],
                "raw_sum": r["raw_sum"],
                "in_tolerance": bool(r["in_tolerance"]),
                "distribution": dist[r["period"]],
            }
            for r in reversed(rows)
        ]
    }


# ---------------------------------------------------------------------------
# The instrument register
# ---------------------------------------------------------------------------


@app.get("/v1/instruments", response_model=list[InstrumentOut], tags=["instruments"])
def list_instruments(
    active_only: bool = Query(True),
    conn: db.Connection = Depends(get_conn),
) -> list[InstrumentOut]:
    """The register, with each instrument's history coverage."""
    where = "WHERE i.active = 1" if active_only else ""
    rows = conn.execute(
        f"SELECT i.*, COUNT(r.period) AS months, MIN(r.period) AS lo, MAX(r.period) AS hi "
        f"FROM instrument i LEFT JOIN instrument_return r USING (instrument_id) "
        f"{where} GROUP BY i.instrument_id ORDER BY i.name"
    ).fetchall()
    return [
        InstrumentOut(
            instrument_id=r["instrument_id"], name=r["name"], role=r["role"],
            asset_class=r["asset_class"], ticker=r["ticker"],
            region_scope=r["region_scope"], region_geo=r["region_geo"],
            capital_type=r["capital_type"], currency=r["currency"],
            liquidity=r["liquidity"], countries=tuple(json.loads(r["countries_json"] or "[]")),
            active=bool(r["active"]),
            created_at=r["created_at"], updated_at=r["updated_at"], note=r["note"],
            months=r["months"], first_period=r["lo"], last_period=r["hi"],
        )
        for r in rows
    ]


@app.post("/v1/instruments", status_code=201, tags=["instruments"])
def create_instrument(
    payload: InstrumentIn,
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Register an instrument, or update one that already exists.

    The universe is a versioned input, so this is a data event with a timestamp rather
    than a code change -- which is what lets the register grow without a release.
    """
    instrument_id = slug(payload.name)
    now = db.utc_now()
    existing = conn.execute(
        "SELECT created_at FROM instrument WHERE instrument_id = %s", (instrument_id,)
    ).fetchone()
    created = existing["created_at"] if existing else now
    conn.execute(
        db.upsert(
            "instrument",
            (
                "instrument_id", "name", "ticker", "role", "asset_class", "region_scope",
                "region_geo", "capital_type", "currency", "liquidity", "countries_json", "active",
                "created_at", "updated_at", "note",
            ),
            ("instrument_id",),
        ),
        # `active` is bound rather than written as a literal 1: registering an instrument
        # re-activates a retired one, and that should be visible in the parameter list
        # rather than hidden in the SQL.
        (instrument_id, payload.name, payload.ticker, payload.role, payload.asset_class,
         payload.region_scope, payload.region_geo, payload.capital_type, payload.currency,
         payload.liquidity, json.dumps(list(payload.countries)), 1, created, now, payload.note),
    )
    return {"instrument_id": instrument_id, "created": existing is None, "updated_at": now}


@app.post("/v1/instruments/{instrument_id}/returns", tags=["instruments"])
def add_returns(
    instrument_id: str,
    payload: ReturnsIn,
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Append or replace monthly returns, then leave the profile stale until re-estimated.

    Estimation is a separate call on purpose. Loading five years of history one batch at a
    time should not trigger five re-estimates, and a caller that wants the profile refreshed
    says so.
    """
    if conn.execute(
        "SELECT 1 FROM instrument WHERE instrument_id = %s", (instrument_id,)
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")
    now = db.utc_now()
    conn.executemany(
        db.upsert(
            "instrument_return",
            (
                "instrument_id", "period", "value", "source", "ingested_at",
            ),
            ("instrument_id", "period",),
        ),
        [(instrument_id, p.period, p.value, payload.source, now) for p in payload.points],
    )
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM instrument_return WHERE instrument_id = %s", (instrument_id,)
    ).fetchone()["n"]
    return {"instrument_id": instrument_id, "accepted": len(payload.points), "months": total}


@app.post("/v1/instruments/{instrument_id}/estimate", tags=["instruments"])
def estimate(
    instrument_id: str,
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Re-run the cascade for one instrument against the current calibration."""
    calibration_id = _require_calibration(conn)
    try:
        profile = service.estimate_and_save(conn, instrument_id, calibration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "instrument_id": instrument_id,
        "calibration_id": calibration_id,
        "coverage": profile.coverage.value,
        "n_obs_total": profile.n_obs_total,
        "borrowed_from": profile.borrowed_from,
        "match_score": profile.match_score,
        "states": profile.as_state_rows(),
    }


@app.get("/v1/instruments/{instrument_id}/profile", tags=["instruments"])
def instrument_profile(
    instrument_id: str,
    method: str | None = Query(
        None, pattern=METHOD_PATTERN,
        description="Opt-in: compute the profile with this estimator instead of reading "
                    "the stored one."),
    currency: str | None = Query(
        None, pattern=CURRENCY_PATTERN,
        description="Opt-in (D-01): measure the profile in CHF, EUR or USD."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One instrument's 25-state profile under the default estimator, or another's.

    Without ``method`` this is the default estimator's profile (the 12 month forward
    measurement, lightly smoothed, FMRE-22), computed on request and never stored. The
    response names the method, the currency and the series it was measured from; for the
    forward measurement it carries the per-phase windows, the 12 month forward return after
    every crisis and contraction month, and, smoothed, the unsmoothed profile and what the
    smoother moved. ``method=cascade`` without a currency is the stored cascade profile,
    in the response shape it always had.
    """
    calibration_id = _require_calibration(conn)
    chosen = ProfileMethod(method) if method else service.configured_profile_method()
    if chosen is not ProfileMethod.CASCADE or currency is not None:
        try:
            universe = service.load_universe(conn, calibration_id)
            inst = next((i for i in universe.instruments
                         if i["instrument_id"] == instrument_id), None)
            if inst is None:
                raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")
            view = service.estimate_view(universe, inst, chosen, currency)
        except CurrencyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        states = [
            {"state": i + 1, "value": view["profile"][i], "method": view["methods"][i],
             "n_obs": view["n_obs"][i]}
            for i in range(len(view["profile"]))
        ]
        extra = {k: view[k] for k in ("phases", "after_stress", "amplitude", "unsmoothed",
                                      "smoothing", "crisis_months") if k in view}
        return {
            "instrument_id": instrument_id,
            "calibration_id": calibration_id,
            "profile_method": chosen.value,
            "currency": view["currency"],
            "series": view["series"],
            "series_currency": view["series_currency"],
            "stored": view["stored"],
            "coverage": view["coverage"],
            "n_obs_total": view["n_obs_total"],
            "borrowed_from": view["borrowed_from"],
            "match_score": view["match_score"],
            "unit": "annualised_log_return",
            "states": states,
            "protection_type": (service.protection_type(inst).value
                                if inst["role"] == "protection" else None),
            "protection_check": service.protection_check(view, service.protection_type(inst)),
            **extra,
        }
    row = conn.execute(
        "SELECT * FROM instrument_profile WHERE instrument_id = %s AND calibration_id = %s",
        (instrument_id, calibration_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"no profile for {instrument_id!r} under {calibration_id}; POST "
                   f"/v1/instruments/{instrument_id}/estimate first",
        )
    profile = db.loads(row["profile_json"])
    methods = db.loads(row["methods_json"])
    n_obs = db.loads(row["n_obs_json"])
    return {
        "instrument_id": instrument_id,
        "calibration_id": calibration_id,
        "profile_method": ProfileMethod.CASCADE.value,
        "return_set_id": row["return_set_id"],
        "computed_at": row["computed_at"],
        "coverage": row["coverage"],
        "n_obs_total": row["n_obs_total"],
        "borrowed_from": row["borrowed_from"],
        "match_score": row["match_score"],
        "unit": "annualised_log_return",
        "states": [
            {"state": i + 1, "value": profile[i], "method": methods[i], "n_obs": n_obs[i]}
            for i in range(len(profile))
        ],
    }


@app.get("/v1/instruments/{instrument_id}/returns", tags=["instruments"])
def get_returns(
    instrument_id: str,
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The stored monthly history for one instrument."""
    rows = conn.execute(
        "SELECT period, value, source FROM instrument_return WHERE instrument_id = %s ORDER BY "
        "period",
        (instrument_id,),
    ).fetchall()
    return {"instrument_id": instrument_id, "months": len(rows),
            "returns": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@app.get("/v1/diagnostics/coverage", tags=["diagnostics"])
def coverage(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """How much of the published set is measured and how much is filled.

    This is the coverage map from manual section 11.5, and it is the chart a reader should
    look at before any other. A profile that is 60 % filled is not wrong, but it is not a
    measurement either, and nothing else on the page says so.

    The instruments are read under the default estimator (FMRE-22), in their source
    currency, the same profiles the default ReturnSet publishes.
    """
    calibration_id = _require_calibration(conn)
    chosen = service.configured_profile_method()
    out: dict[str, Any] = {"calibration_id": calibration_id, "profile_method": chosen.value,
                           "roles": {}, "instruments": {}}
    for row in conn.execute(
        "SELECT role, methods_json FROM calibration_role WHERE calibration_id = %s",
        (calibration_id,),
    ):
        methods = db.loads(row["methods_json"])
        out["roles"][row["role"]] = {m: methods.count(m) for m in sorted(set(methods))}
    if chosen is ProfileMethod.CASCADE:
        for row in conn.execute(
            "SELECT i.name, p.methods_json, p.coverage FROM instrument i JOIN "
            "instrument_profile p USING (instrument_id) WHERE p.calibration_id = %s "
            "ORDER BY i.name",
            (calibration_id,),
        ):
            methods = db.loads(row["methods_json"])
            out["instruments"][row["name"]] = {
                "coverage": row["coverage"],
                "counts": {m: methods.count(m) for m in sorted(set(methods))},
            }
        return out
    try:
        universe = service.load_universe(conn, calibration_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    cache: dict = {}
    for inst in universe.instruments:
        view = service.estimate_view(universe, inst, chosen, None, cache)
        methods = view["methods"]
        out["instruments"][inst["name"]] = {
            "coverage": view["coverage"],
            "counts": {m: methods.count(m) for m in sorted(set(methods))},
        }
    return out


@app.get("/v1/diagnostics/shapes", tags=["diagnostics"])
def shapes(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The shape assertions from manual section 11.3, run against the live calibration.

    If an estimation run does not reproduce these, the state tagging and the return series
    have come apart -- the failure this engine is most likely to ship silently.
    """
    calibration_id = _require_calibration(conn)
    blocks = service.load_block_profiles(conn, calibration_id)
    means = {k: [p["central"] for p in v["phases"]] for k, v in blocks.items()}
    checks = service.shape_checks(means)
    results = [{"assertion": name, "passed": bool(ok)} for name, ok in checks]
    return {
        "calibration_id": calibration_id,
        "all_passed": all(r["passed"] for r in results),
        "checks": results,
        "phase_names": list(PHASE_NAMES),
        "phase_values": means,
    }


@app.get("/v1/diagnostics/estimators", tags=["diagnostics"])
def estimators(
    currency: str | None = Query(
        None, pattern=CURRENCY_PATTERN,
        description="CHF, EUR or USD. Omitted, each series stays in its source currency."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Cascade, D2, the 12 month forward measurement and its smoothed default side by side.

    **A diagnostic, not the contract** (reviews R-002, R-003; FMRE-22). The published
    profiles are the default estimator's (``default_method``); every method is computed in
    memory, for every instrument with history, with the summary the owner asked for: mean
    jump between neighbouring states, the largest one, protection instruments negative in
    crisis, the share of states by method label, and for the smoothed method the largest
    move the smoother made to a phase value.
    """
    calibration_id = _require_calibration(conn)
    try:
        body = service.estimator_comparison(conn, calibration_id, currency=currency)
    except CurrencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    body["default_method"] = service.configured_profile_method().value
    body["unit"] = "annualised_log_return"
    body["note"] = (
        "Not part of the ReturnSet. The default method is what the ReturnSet publishes; "
        "cascade in its source currency is the stored profile, everything else is "
        "computed on request and never stored. "
        "Chosen currency: " + (currency or "source currency of each series") + "."
    )
    return body


@app.get("/v1/diagnostics/income-candidates", tags=["diagnostics"])
def income_candidates(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """The Income compositions of review R-001 beside Stabilisation.

    The owner chose candidate A (real estate 75 %, equity 25 %, 29.09.2026), which is the
    published Income; the Income before R-001 and candidates B and C stay beside it.
    Nothing is stored. Each candidate carries the acceptance target, the eight shape
    checks, and the instruments whose nearest role curve would change.
    """
    calibration_id = _require_calibration(conn)
    try:
        return service.income_candidates(conn, calibration_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/diagnostics/recomposition", tags=["diagnostics"])
def recomposition(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Recompose the unconditional average from the profiles and the phase frequencies.

    **A diagnostic and not a way to produce anything.** If the recomposed figure drifts
    from the unconditional one, the state tagging and the return series have come out of
    alignment, which is the single most likely and most silent failure in this engine.

    The numbers it reports are moments, which is exactly why this lives behind its own
    endpoint and never inside a ``ReturnSet``.
    """
    calibration_id = _require_calibration(conn)
    header = conn.execute(
        "SELECT phase_counts_json FROM calibration WHERE calibration_id = %s", (calibration_id,)
    ).fetchone()
    counts = db.loads(header["phase_counts_json"])
    total = sum(counts.values())
    weights = [counts[name] / total for name in PHASE_NAMES]

    blocks = service.load_block_profiles(conn, calibration_id)
    rows = []
    for key, block in blocks.items():
        phase_means = [p["central"] for p in block["phases"]]
        phase_counts = [p["n_obs"] for p in block["phases"]]
        block_total = sum(phase_counts)
        # Recomposed two ways: against the full-record phase frequency, and against the
        # block's own coverage. They differ for a truncated block, and the difference is
        # the honest measure of what truncation costs.
        recomposed = sum(w * m for w, m in zip(weights, phase_means))
        own = sum((c / block_total) * m for c, m in zip(phase_counts, phase_means))
        rows.append({
            "block": key,
            "recomposed_on_full_record": recomposed,
            "recomposed_on_own_window": own,
            "drift": recomposed - own,
            "window": [block["first_year"], block["last_year"]],
            "truncated": block_total != total,
        })
    return {
        "calibration_id": calibration_id,
        "phase_weights": dict(zip(PHASE_NAMES, weights)),
        "blocks": rows,
        "note": "Diagnostic only. These are moments and never enter a ReturnSet.",
    }


@app.get("/v1/diagnostics/expected", tags=["diagnostics"])
def expected(
    period: str | None = Query(None, description="YYYY-MM; defaults to the latest month."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """What each role profile implies for one month, given that month's signal.

    **Deliberately outside the contract.** Integrating a profile against a regime
    distribution produces a single number -- a moment -- and manual section 11.1 refuses
    to put one in a ReturnSet. The test bench needs it to show what a month means, so it
    lives here, behind a name that says it is a consumer view.
    """
    calibration_id = _require_calibration(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")
    if period is None:
        row = conn.execute("SELECT MAX(period) AS p FROM market_risk_month").fetchone()
        period = row["p"]
    month = conn.execute(
        "SELECT * FROM market_risk_month WHERE period = %s", (period,)
    ).fetchone()
    if month is None:
        raise HTTPException(status_code=404, detail=f"no signal for {period}")

    distribution = [0.0] * 25
    for r in conn.execute(
        "SELECT state, probability FROM market_risk_signal WHERE period = %s", (period,)
    ):
        distribution[r["state"] - 1] = r["probability"]

    smap = service.load_state_map(conn, map_id)
    stored = service.load_role_profiles(conn, calibration_id)
    return {
        "period": period,
        "modal_state": month["modal_state"],
        "mean_state": month["mean_state"],
        "calibration_id": calibration_id,
        "state_map_id": map_id,
        "by_role": {
            role: expected_return(r["profile"], distribution, smap)
            for role, r in stored.items()
        },
        "unit": "annualised_log_return",
        "note": "A consumer view, computed at the point of use. Not part of the ReturnSet.",
    }


@app.get("/v1/runs", tags=["diagnostics"])
def runs(
    limit: int = Query(25, ge=1, le=200),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Recent run manifests. No figure leaves an engine without one."""
    rows = conn.execute(
        "SELECT run_id, engine, engine_version, finished_at, wall_clock_ms, inputs_json, "
        "outputs_json, status FROM run_manifest ORDER BY finished_at DESC LIMIT %s",
        (limit,)
    ).fetchall()
    return {
        "runs": [
            {
                "run_id": r["run_id"], "engine": r["engine"],
                "engine_version": r["engine_version"], "finished_at": r["finished_at"],
                "wall_clock_ms": r["wall_clock_ms"], "status": r["status"],
                "inputs": db.loads(r["inputs_json"]),
                "outputs": db.loads(r["outputs_json"]),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# The test bench. Not part of the system.
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def testbench_index() -> FileResponse:
    """Serve the standalone test bench.

    This is a development surface and is explicitly *not* the App. It exists so an engine
    can be examined in detail before anything is wired together, and it talks to the same
    ``/v1`` endpoints the App will. Nothing in ``engines/`` or ``contracts/`` knows it
    exists.
    """
    return FileResponse(TESTBENCH / "index.html")
