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
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api import access_log
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

#: The basis of the figures (owner, 29.09.2026). Omitted or ``nominal``: the published set,
#: byte for byte; ``real``: each profile minus ln(1 + inflation) per state.
BASIS_PATTERN = r"^(nominal|real)$"

#: The estimator choice. Omitted, the configured default (``service.DEFAULT_PROFILE_METHOD``,
#: the 12 month forward measurement lightly smoothed, FMRE-22); ``cascade`` without a
#: currency reads the stored profiles back unchanged.
METHOD_PATTERN = r"^(cascade|shape_scaled|forward_12m|forward_12m_smoothed)$"

log = logging.getLogger("fmre")

#: The tables ``/v1/health`` counts. All of them exist once ``schema.sql`` has been applied.
HEALTH_TABLES = ("long_series", "market_risk_signal", "instrument",
                 "instrument_return", "calibration", "run_manifest")

# Successful health probes stay out of uvicorn's access log (FMRE-42).
access_log.install()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Apply the schema at start-up, as every other engine does (FMRE-42).

    :func:`store.db.initialise` is idempotent, so on a store that already holds the tables
    it changes nothing that is published. A failure here (the server not up yet, a role
    without the right to create) is logged and the engine starts anyway: ``/v1/health``
    then says what is missing, which is more use than a process that exits.
    """
    try:
        db.initialise()
    except Exception as exc:  # noqa: BLE001 - reported, and health shows the state
        log.warning("fmre: the schema could not be applied at start-up: %s", exc)
    yield


app = FastAPI(
    title="sim-tech Instruments -- Fund Map",
    version=service.ENGINE_VERSION,
    description=(
        "Per-state return profiles for the instrument universe. Publishes a 25-state profile "
        "per role and per instrument, every value carrying the method that produced it. "
        "Deliberately publishes no mean, variance or covariance."
    ),
    lifespan=lifespan,
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
    # PUT for the cockpit's inflation-beta override (FMRE-35).
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
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

    On a schema without fmre's tables it answers 200 with ``"status": "uninitialised"`` and
    names the missing tables, rather than a 500 (FMRE-42). The start-up hook applies the
    schema, so this is seen only when that failed or the tables were dropped since.
    """
    schema = conn.config.schema
    missing = [
        table for table in HEALTH_TABLES
        if conn.execute("SELECT to_regclass(%s) AS t", (f"{schema}.{table}",)).fetchone()["t"]
        is None
    ]
    if missing:
        return {
            "status": "uninitialised",
            "engine": service.ENGINE,
            "engine_version": service.ENGINE_VERSION,
            "calibration_id": None,
            "store": db.describe(),
            "missing_tables": missing,
            "note": (
                f"schema {schema} lacks fmre's tables. Restart the engine to apply them, or "
                f"run python -m store.etl.bootstrap"
            ),
        }
    calibration_id = service.latest_calibration_id(conn)
    counts = {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in HEALTH_TABLES
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


def confirm_regime(regime_id: str) -> dict[str, Any]:
    """Refuse to stamp a ``regime_id`` that aggregation does not serve.

    Standard library only, like the rest of the client path. An unknown id is the caller's
    error (422); an aggregation that cannot be reached is not, and says so (503). Stamping
    an unconfirmed id would pass a Regime that does not exist straight on to the optimiser.

    Returns aggregation's ``/regime/{id}/current`` body: a scenario Regime carries its
    ``scenario`` there (AGG-21), which the inflation pass-through reads (FMRE-33).
    """
    url = f"{AGGREGATION_URL.rstrip('/')}/regime/{urllib.parse.quote(regime_id)}/current"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = json.loads(response.read())
            served = body.get("regime_id")
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
    return body


def fetch_regime(regime_id: str) -> dict[str, Any]:
    """The Regime aggregation serves under ``regime_id`` (``GET /regime/{id}``).

    Read for the real view only: a scenario Regime carries its policy's inflation in
    ``provenance.scenario`` (decision 2). An unknown id is the caller's error (422), an
    unreachable aggregation is not (503), as in :func:`confirm_regime`.
    """
    url = f"{AGGREGATION_URL.rstrip('/')}/regime/{urllib.parse.quote(regime_id)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                status_code=422, detail=f"aggregation serves no Regime {regime_id!r}",
            ) from exc
        raise HTTPException(
            status_code=503, detail=f"aggregation answered {exc.code} for {regime_id!r}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"cannot read Regime {regime_id!r}: aggregation at {AGGREGATION_URL} "
                   f"unreachable",
        ) from exc
    if body.get("regime_id") != regime_id:
        raise HTTPException(
            status_code=503,
            detail=f"aggregation answered for {body.get('regime_id')!r} when asked for "
                   f"{regime_id!r}",
        )
    return body


def scenario_inflation(regime_id: str) -> dict[str, Any] | None:
    """The scenario's inflation for the real view, or ``None`` for a base Regime.

    A scenario Regime must carry ``provenance.scenario.inflation_final_12m`` (aggregation
    AGG-24): the average annual inflation over months 49 to 60 of its policy's path. One
    without it is refused loudly (503): the historical per-state inflation is never a
    stand-in for a scenario's own (decision 2).
    """
    regime = fetch_regime(regime_id)
    return _scenario_of(regime_id, (regime.get("provenance") or {}).get("scenario"))


def scenario_of_current(regime_id: str, current: dict[str, Any] | None) -> dict[str, Any] | None:
    """The scenario of a Regime from aggregation's ``/current`` body (``confirm_regime``).

    What the **nominal** view under a scenario reads for the inflation pass-through
    (FMRE-33): a base Regime's body carries no ``scenario`` and is left exactly as it was.
    """
    return _scenario_of(regime_id, (current or {}).get("scenario"), nominal=True)


def _scenario_of(regime_id: str, scenario: dict[str, Any] | None, *,
                 nominal: bool = False) -> dict[str, Any] | None:
    if not scenario:
        return None
    value = scenario.get("inflation_final_12m")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        what = ("The nominal view under a scenario carries each instrument to the "
                "scenario's inflation by its pass-through beta (FMRE-33) and needs it"
                if nominal else
                "The real view under a scenario uses the policy's own inflation (decision 2) "
                "and never the historical per-state inflation")
        raise HTTPException(
            status_code=503,
            detail=(
                f"Regime {regime_id!r} is a scenario Regime (policy "
                f"{scenario.get('policy')!r}) but aggregation serves no "
                f"provenance.scenario.inflation_final_12m for it. {what}, so nothing was "
                f"deflated. Restart aggregation on a build that derives the field (AGG-24)."),
        )
    return {"regime_id": regime_id, "policy": scenario.get("policy"),
            "inflation_final_12m": float(value),
            "inflation_path_months": len(scenario.get("inflation_path") or ())}


def _pass_through_context(conn: db.Connection, instruments: list[dict], map_id: str | None,
                          scenario: dict[str, Any],
                          currency: str | None = None) -> dict[str, Any]:
    """What a scenario set carries its instruments with (FMRE-33): the stored house table,
    the betas in force, and the historical deflator of every currency.

    ``currency`` is the currency the set is measured in; None (source currency) takes each
    view's own, as the real view does (an instrument without history: USD).
    """
    from engines.fund_map.inflation import NotComputable
    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")
    try:
        cal = service.ensure_pass_through_calibration(conn)
        curves = service.historical_inflation_curves(
            conn, service.modal_signal_by_period(conn), service.load_state_map(conn, map_id))
    except service.PassThroughError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except NotComputable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"cal": cal, "curves": curves, "scenario": scenario, "currency": currency,
            "betas": service.effective_betas(conn, instruments), "applied": {}, "roles": {}}


def _carry(ctx: dict[str, Any], view: dict, instrument_id: str) -> dict:
    """One view carried to the scenario, nominal; the beta used is recorded in ``ctx``."""
    from contracts.return_set import PassThroughInstrument
    from engines.fund_map.inflation import NotComputable
    entry = ctx["betas"][instrument_id]
    currency = ctx["currency"] or _source_deflator_currency(view)
    try:
        carried = service.pass_through_view(
            view, entry, ctx["scenario"]["inflation_final_12m"], ctx["curves"], currency)
    except NotComputable as exc:
        raise _not_computable(exc) from exc
    ctx["applied"][instrument_id] = PassThroughInstrument(
        instrument_id=instrument_id, type=entry["type"], beta=entry["beta"],
        source=entry["source"], duration=entry["duration"],
        duration_source=entry["duration_source"],
        override_version=(entry["override"]["version"] if entry["override"] else None),
        deflator_currency=currency)
    return carried


def _carry_roles(ctx: dict[str, Any], role_profiles: tuple[Profile, ...]
                 ) -> tuple[Profile, ...]:
    """The role profiles carried to the scenario, nominal, by their blended beta (FMRE-40).

    Each role takes the weighted beta (and bond duration) of its long-record blocks, as the
    stored calibration ``ipt@1.1.0`` states it; the composition is recorded in ``ctx``.
    """
    from contracts.return_set import PassThroughBlock, PassThroughRole
    from engines.fund_map.inflation import NotComputable
    blends = ctx["cal"]["payload"]["roles"]
    out = []
    for profile in role_profiles:
        blend = blends[profile.key]
        try:
            values = service.pass_through_role(
                [st.value for st in profile.states], blend,
                ctx["scenario"]["inflation_final_12m"], ctx["curves"])
        except NotComputable as exc:
            raise _not_computable(exc) from exc
        out.append(profile.model_copy(update={"states": tuple(
            st.model_copy(update={"value": v}) for st, v in zip(profile.states, values))}))
        ctx["roles"][profile.key] = PassThroughRole(
            role=profile.key, beta=blend["beta"], duration=blend["duration"],
            deflator_currency="USD",
            composition=tuple(PassThroughBlock(**c) for c in blend["composition"]))
    return tuple(out)


def _pass_through_provenance(ctx: dict[str, Any], keys: list[str]):
    from contracts.return_set import InflationPassThrough
    from engines.fund_map import pass_through as pt
    cal, scenario = ctx["cal"], ctx["scenario"]
    roles = tuple(ctx["roles"].values())
    return InflationPassThrough(
        calibration_version=cal["version"], calibration_id=cal["calibration_id"],
        source=cal["source"], scenario=scenario["regime_id"], policy=scenario["policy"],
        inflation_final_12m=scenario["inflation_final_12m"], price_floor=pt.PRICE_FLOOR,
        formula=pt.FORMULA,
        applied_to=("instruments", "roles") if roles else ("instruments",),
        instruments=tuple(ctx["applied"][k] for k in keys if k in ctx["applied"]),
        roles=roles)


def _pass_through_identity(ctx: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """The effective betas enter the id: an override is another artefact (FMRE-35); the
    roles' blended betas too (FMRE-40)."""
    applied = ctx["applied"]
    identity = {"cal": ctx["cal"]["calibration_id"],
                "pi_s": ctx["scenario"]["inflation_final_12m"],
                "b": {k: [applied[k].beta, applied[k].duration, applied[k].source]
                      for k in keys if k in applied}}
    if ctx["roles"]:
        identity["roles"] = {k: [r.beta, r.duration] for k, r in ctx["roles"].items()}
    return identity


def _pass_through_note(ctx: dict[str, Any]) -> str:
    s = ctx["scenario"]
    return (
        f"Inflation pass-through under the scenario Regime {s['regime_id']} "
        f"({s['policy']}: {s['inflation_final_12m']:.2%} a year): each instrument profile is "
        f"its historical real return (nominal minus the historical per-state inflation of "
        f"the currency it is measured in) plus beta * ln(1 + inflation), and a nominal bond "
        f"also takes the price change -duration * (ln(1 + scenario inflation) - ln(1 + "
        f"historical inflation)), a log return with no cap; beta per instrument and its "
        f"source (house or override) in provenance.inflation_pass_through, calibration "
        f"{ctx['cal']['version']}. "
        + ("Role profiles follow the same rule with the weighted beta and bond duration of "
           "their blocks, from the historical USD inflation (per role in "
           "provenance.inflation_pass_through.roles); block profiles carry no pass-through."
           if ctx["roles"] else "Role and block profiles carry no pass-through."))


def _view_payload(key: str, role: str, view: dict,
                  values: list[float] | None = None) -> Profile:
    return _profile_payload(
        key, "instrument", role, view["profile"] if values is None else values,
        view["methods"], view["n_obs"], coverage=view["coverage"],
        borrowed_from=view["borrowed_from"], match_score=view["match_score"])


def _deflated(profile: Profile, log_inflation: tuple[float, ...]) -> Profile:
    """``real = nominal - ln(1 + inflation)`` on a published profile; labels unchanged."""
    return profile.model_copy(update={"states": tuple(
        s.model_copy(update={"value": s.value - d})
        for s, d in zip(profile.states, log_inflation))})


def _source_deflator_currency(view: dict) -> str:
    """The currency an instrument is deflated in when the set is in source currency.

    The currency its series is measured in; an instrument without history is its role's
    seed, the long annual record in USD, and is deflated in USD like the role profiles.
    """
    return view["currency"] if view["series"] is not None else "USD"


def _resolve_currency(curves: dict, wanted: str) -> tuple[str, dict | None]:
    """Decision 5 for one currency, as an HTTP answer."""
    from engines.fund_map.inflation import NotComputable, hard_currency
    if wanted not in curves:
        raise HTTPException(status_code=422, detail=(
            f"no inflation index for {wanted}; basis=real needs CHF, EUR or USD"))
    try:
        return hard_currency(wanted, curves)
    except NotComputable as exc:
        raise _not_computable(exc) from exc


def _real_context(conn: db.Connection, map_id: str | None, scenario: dict | None,
                  currency: str | None) -> dict[str, Any]:
    """The deflators of a real set, and the currency it is computed in (decision 5).

    Resolved before any profile is measured, so a set that falls back to a hard currency
    is measured in it directly.
    """
    from engines.fund_map.inflation import NotComputable

    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")
    try:
        curves = service.inflation_curves(
            conn, service.modal_signal_by_period(conn), service.load_state_map(conn, map_id),
            scenario)
    except NotComputable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    set_currency, fallback = (currency, None)
    if currency is not None:
        set_currency, fallback = _resolve_currency(curves, currency)
    return {"curves": curves, "currency": set_currency,
            "fallbacks": [fallback] if fallback else []}


def _real_view(ctx: dict[str, Any], *,
               method: ProfileMethod, currency: str | None, scenario: dict | None,
               role_profiles: tuple[Profile, ...], block_profiles: tuple[Profile, ...],
               rows: list, views: dict[str, dict], universe,
               pt_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``basis=real`` set: every profile minus its currency's per-state log inflation.

    **Instruments** are deflated by the inflation of the currency they are measured in:
    ``currency=`` when given, otherwise each series' source currency (stated). **Role and
    block profiles** are the long annual record in USD and are deflated by USD inflation.
    Under a scenario Regime every curve is the scenario's (decision 2). A currency whose
    inflation leaves the band in any state gives way to CHF, then USD (decision 5): the
    affected profiles are re-measured in that currency and the fallback is named; if no
    currency is inside the band the set is ``not_computable`` (422, with the reason).
    """
    from contracts.return_set import Deflator, DeflatorCurve
    from engines.fund_map.inflation import (
        NotComputable, curve_reason, deflate, weakest_labels)

    curves = ctx["curves"]
    set_currency = ctx["currency"]
    fallbacks: list[dict] = list(ctx["fallbacks"])
    applied: dict[str, set[str]] = {}

    by_id = {i["instrument_id"]: i for i in universe.instruments} if universe else {}
    cache: dict = {}
    instrument_profiles = []
    for r in rows:
        iid = r["instrument_id"]
        view = views[iid]
        if set_currency is not None:
            target = set_currency
        else:
            target, fallback = _resolve_currency(curves, _source_deflator_currency(view))
            if fallback:
                fallbacks.append({**fallback, "instrument": iid})
        if target != view["currency"] and view["series"] is not None:
            try:
                view = service.estimate_view(universe, by_id[iid], method, target, cache)
            except CurrencyError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            if pt_ctx is not None:
                # Re-measured in another currency: carried to the scenario again.
                view = _carry(pt_ctx, view, iid)
        try:
            values = deflate(view["profile"], curves[target])
        except NotComputable as exc:
            raise _not_computable(exc) from exc
        applied.setdefault(target, set()).add("instruments")
        instrument_profiles.append(_view_payload(iid, r["role"], view, values))

    role_curve = curves["USD"]
    if not role_curve.computable():
        raise _not_computable(NotComputable(
            "the role profiles are the long annual record in USD: "
            + curve_reason(role_curve)))
    applied.setdefault("USD", set()).add("roles")
    roles = tuple(_deflated(p, role_curve.log_inflation) for p in role_profiles)
    blocks = tuple(_deflated(p, role_curve.log_inflation) for p in block_profiles)

    used = sorted(applied)
    instrument_curves = [curves[c] for c in used if "instruments" in applied[c]]
    labels = weakest_labels(instrument_curves or [role_curve])
    index = (curves[set_currency].index if set_currency is not None
             else "; ".join(f"{c}: {curves[c].index}" for c in used))
    if set_currency is not None:
        hard = fallbacks[0] if fallbacks else None
    else:
        hard = {"fallbacks": fallbacks} if fallbacks else None
    deflator = Deflator(
        currency=set_currency, index=index, method=role_curve.method, labels=labels,
        hard_currency_fallback=hard,
        scenario=scenario["regime_id"] if scenario else None,
        curves=tuple(
            DeflatorCurve(currency=c, index=curves[c].index, source=curves[c].source,
                          log_inflation=curves[c].log_inflation, labels=curves[c].labels,
                          applied_to=tuple(sorted(applied[c])))
            for c in used),
    )
    if scenario:
        what = (f"the scenario Regime {scenario['regime_id']}'s own inflation "
                f"({scenario['policy']}: {scenario['inflation_final_12m']:.2%} a year, the "
                f"average over months 49 to 60 of its policy path) in every state "
                f"(decision 2)")
    else:
        what = ("the inflation measured over the 12 months after each month in that "
                "regime state, per currency (GET /v1/inflation): " + index)
    note = (
        f"Basis: real in currency={set_currency or 'source'}: every profile is nominal "
        f"minus ln(1 + inflation) per state, {what}. "
        + ("Instruments are deflated in the currency their series is measured in (CHF for "
           "the andersCH recovered returns, USD for public proxies); an instrument without "
           "history is its role seed and is deflated in USD. " if set_currency is None
           else "")
        + "Role profiles are the long annual record in USD and are deflated by USD "
        "inflation. Everything is stored nominal; real is derived at the point of use. "
        "Per-state labels are in provenance.deflator."
        + (" Hard-currency view: " + "; ".join(f["reason"] for f in fallbacks) + "."
           if fallbacks else "")
    )
    identity = {
        "ccy": set_currency, "asked": currency,
        "src": sorted({curves[c].source for c in used}),
        "method": "scenario" if scenario else "forward_12m",
        "fallback": [[f["from"], f["to"], f.get("instrument")] for f in fallbacks],
        "scenario": ([scenario["regime_id"], scenario["policy"],
                      scenario["inflation_final_12m"]] if scenario else None),
    }
    return {"role_profiles": roles, "block_profiles": blocks,
            "instrument_profiles": tuple(instrument_profiles), "deflator": deflator,
            "note": note, "identity": identity, "currency": set_currency}


def _not_computable(exc: Exception) -> HTTPException:
    """Decision 5, no currency inside the band: a stated result with its reason."""
    return HTTPException(status_code=422, detail={
        "status": "not_computable", "basis": "real", "reason": str(exc)})


@app.get("/v1/inflation", tags=["return-set"])
def inflation(
    currency: str = Query(..., pattern=CURRENCY_PATTERN,
                          description="The reporting currency; its own index (decision 3)."),
    regime_id: str | None = Query(
        None, min_length=1,
        description="A scenario Regime: its policy's inflation in every state (decision 2). "
                    "A base Regime gives the historical per-state inflation."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Inflation over the following 12 months in each of the 25 regime states.

    The deflator of the real view (owner, 29.09.2026): per state, the inflation of the
    currency's index measured over the 12 months after each month in that state, per phase
    and read onto the states like a profile (``engines/fund_map/inflation.py``). Each state
    carries ``inflation`` (simple, annual), ``log_inflation`` (what a real log return
    subtracts: ``real = nominal - ln(1 + inflation)``), ``label`` (``measured`` inside
    -10 % .. +20 %, ``extrapolated`` in the rest of -20 % .. +100 %, ``fallback`` where the
    phase was too thin and today's year-on-year inflation stands in, ``not_computable``
    outside the band) and ``n_obs``. ``real_view`` says in which currency a real figure
    would be computed (decision 5).
    """
    from engines.fund_map.inflation import (
        CEILING, FLOOR, MEASURED_HIGH, MEASURED_LOW, NotComputable, hard_currency)

    scenario = scenario_inflation(regime_id) if regime_id is not None else None
    calibration_id = _require_calibration(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")
    state_map = service.load_state_map(conn, map_id)
    signal = service.modal_signal_by_period(conn)
    wanted = [currency] + [c for c in ("CHF", "USD") if c != currency]
    try:
        curves = service.inflation_curves(conn, signal, state_map, scenario, wanted)
    except NotComputable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    body = curves[currency].as_payload()
    try:
        eff, fallback = hard_currency(currency, curves)
        real_view: dict[str, Any] = {"status": "computable", "currency": eff,
                                     "hard_currency_fallback": fallback}
    except NotComputable as exc:
        real_view = {"status": "not_computable", "currency": None, "reason": str(exc)}
    body.update(
        regime_id=regime_id,
        regime_kind=None if regime_id is None else ("scenario" if scenario else "base"),
        calibration_id=calibration_id, state_map_id=map_id,
        unit="annual inflation (simple) and ln(1 + inflation)",
        ceiling={"floor": FLOOR, "measured_low": MEASURED_LOW,
                 "measured_high": MEASURED_HIGH, "ceiling": CEILING},
        real_view=real_view,
    )
    return body


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
    basis: str | None = Query(
        None, pattern=BASIS_PATTERN,
        description="nominal (the default, unchanged) or real: each profile minus "
                    "ln(1 + inflation) per state, the currency's inflation over the "
                    "following 12 months in that state, or a scenario Regime's own."),
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
    # ``basis=nominal`` is the default set, byte for byte: nothing below looks at it.
    real = basis == "real"
    current = confirm_regime(regime_id) if regime_id is not None else None
    # A scenario Regime: its inflation deflates a real set (decision 2) and carries every
    # instrument to the scenario by its pass-through beta, nominal and real (FMRE-33). A
    # base Regime is read for nothing more than the stamp, and its set is what it was.
    if regime_id is None:
        scenario = None
    elif real:
        scenario = scenario_inflation(regime_id)
    else:
        scenario = scenario_of_current(regime_id, current)
    started = time.perf_counter()
    calibration_id = _require_calibration(conn)
    header = conn.execute(
        "SELECT * FROM calibration WHERE calibration_id = %s", (calibration_id,)
    ).fetchone()
    map_id = service.latest_state_map_id(conn, calibration_id)
    real_ctx = _real_context(conn, map_id, scenario, currency) if real else None
    # A real set that fell back to a hard currency (decision 5) is measured in it.
    view_currency = real_ctx["currency"] if real_ctx is not None else currency

    stored = service.load_role_profiles(conn, calibration_id)
    role_profiles = tuple(
        _profile_payload(r["role"], "role", r["role"], r["profile"], r["methods"],
                         r["n_obs"], coverage=_weakest(r["methods"]))
        for r in stored.values()
    )

    instrument_profiles: tuple[Profile, ...] = ()
    rows: list = []
    views: dict[str, dict] = {}
    universe = None
    pt_ctx: dict[str, Any] | None = None
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
        if computed or real or scenario is not None:
            try:
                universe = service.load_universe(conn, calibration_id)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            by_id = {i["instrument_id"]: i for i in universe.instruments}
            cache: dict = {}
            for r in rows:
                try:
                    views[r["instrument_id"]] = service.estimate_view(
                        universe, by_id[r["instrument_id"]], method, view_currency, cache)
                except CurrencyError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
            if scenario is not None:
                pt_ctx = _pass_through_context(conn, universe.instruments, map_id, scenario,
                                               view_currency)
                for r in rows:
                    views[r["instrument_id"]] = _carry(
                        pt_ctx, views[r["instrument_id"]], r["instrument_id"])
            instrument_profiles = tuple(
                _view_payload(r["instrument_id"], r["role"], views[r["instrument_id"]])
                for r in rows
            )

    block_profiles: tuple[Profile, ...] = ()
    if include_blocks:
        blocks = service.load_block_profiles(conn, calibration_id)
        block_profiles = tuple(
            _profile_payload(b["key"], "block", b["role"], b["profile"], b["methods"],
                             b["n_obs"], coverage=_weakest(b["methods"]))
            for b in blocks.values()
        )

    if scenario is not None and pt_ctx is None:
        pt_ctx = _pass_through_context(conn, [], map_id, scenario)
    if pt_ctx is not None:
        # FMRE-40: the role profiles follow the same rule, with their blended beta.
        role_profiles = _carry_roles(pt_ctx, role_profiles)

    real_set = None
    if real:
        real_set = _real_view(
            real_ctx, method=method, currency=currency,
            scenario=scenario, role_profiles=role_profiles, block_profiles=block_profiles,
            rows=rows, views=views, universe=universe, pt_ctx=pt_ctx)
        role_profiles = real_set["role_profiles"]
        block_profiles = real_set["block_profiles"]
        instrument_profiles = real_set["instrument_profiles"]

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
    set_currency = currency
    pass_through = None
    if pt_ctx is not None:
        # FMRE-33/35: the effective betas and the scenario's inflation are in the id.
        keys = [p.key for p in instrument_profiles]
        identity["pt"] = _pass_through_identity(pt_ctx, keys)
        run_inputs["inflation_pass_through"] = identity["pt"]
        pass_through = _pass_through_provenance(pt_ctx, keys)
        if real_set is None:
            notes = (notes[0], "Basis: nominal. " + _pass_through_note(pt_ctx)) + notes[2:]
    if real_set is not None:
        # The basis enters the id, the run manifest and the notes; nominal never does.
        identity["basis"] = "real"
        identity["deflator"] = real_set["identity"]
        run_inputs["basis"] = "real"
        run_inputs["deflator"] = real_set["identity"]
        real_note = real_set["note"]
        if pt_ctx is not None:
            real_note += (" " + _pass_through_note(pt_ctx) + " Real is therefore the "
                          "historical real return plus (beta - 1) * ln(1 + inflation).")
        notes = (notes[0], real_note) + notes[2:]
        set_currency = real_set["currency"]
        if set_currency != currency:
            # Decision 5: the set is real in a hard currency, and says so where pcp reads.
            notes = notes[:3] + (
                f"Instrument profiles: profile_method={method.value} in "
                f"currency={set_currency}; {how} Hard-currency view: the request asked "
                f"for currency={currency}.",
                f"Currency: instrument profiles measured in {set_currency}, converted "
                f"monthly at the point of use before estimation. Role profiles are the "
                f"long annual record in USD and are not converted.",
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
            # The estimator that built the instrument profiles (FMRE-26). The calibration's
            # own estimator (plain_mean) stays on /v1/calibration.
            estimator=method.value,
            source_sha256=db.loads(header["sources_json"]),
            notes=notes,
            # D-01: the measurement currency of a converted set; null on the default.
            currency=set_currency,
            basis="real" if real_set is not None else None,
            deflator=real_set["deflator"] if real_set is not None else None,
            inflation_pass_through=pass_through,
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


def _real_profile(ctx: dict[str, Any], universe, inst: dict, method: ProfileMethod,
                  currency: str | None, scenario: dict | None,
                  view: dict, pt_ctx: dict[str, Any] | None = None
                  ) -> tuple[dict, dict[str, Any]]:
    """One instrument's profile on the real basis, and what it was deflated with."""
    curves = ctx["curves"]
    if ctx["currency"] is not None:
        target = ctx["currency"]
        fallback = ctx["fallbacks"][0] if ctx["fallbacks"] else None
    else:
        target, fallback = _resolve_currency(curves, _source_deflator_currency(view))
    if target != view["currency"] and view["series"] is not None:
        try:
            view = service.estimate_view(universe, inst, method, target)
        except CurrencyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if pt_ctx is not None:
            view = _carry(pt_ctx, view, inst["instrument_id"])
    curve = curves[target]
    d = curve.log_inflation
    real_view = dict(view, profile=[v - x for v, x in zip(view["profile"], d)])
    if "unsmoothed" in view:
        real_view["unsmoothed"] = dict(
            view["unsmoothed"],
            profile=[v - x for v, x in zip(view["unsmoothed"]["profile"], d)])
    return real_view, {
        "basis": "real",
        "deflator": {
            "currency": target, "asked_currency": currency, "index": curve.index,
            "method": curve.method, "source": curve.source,
            "log_inflation": list(d), "labels": list(curve.labels),
            "hard_currency_fallback": fallback,
            "scenario": scenario["regime_id"] if scenario else None,
            "note": ("real = nominal - ln(1 + inflation) per state, on states and "
                     "unsmoothed; phases, after_stress, crisis_months and "
                     "protection_check stay nominal"
                     + ("" if currency else "; currency=source: deflated in the currency "
                        "the series is measured in")),
        },
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
    basis: str | None = Query(
        None, pattern=BASIS_PATTERN,
        description="nominal (the default, unchanged) or real: the profile minus "
                    "ln(1 + inflation) per state."),
    regime_id: str | None = Query(
        None, min_length=1,
        description="A scenario Regime: the profile is carried to the scenario's inflation "
                    "by the instrument's pass-through beta (FMRE-33), and with basis=real "
                    "deflated by it (decision 2). A base Regime changes nothing."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One instrument's 25-state profile under the default estimator, or another's.

    ``basis=real`` subtracts ``ln(1 + inflation)`` per state from ``states`` and from the
    unsmoothed profile: the inflation of the currency the profile is measured in
    (``currency=``, or the series' source currency, stated), or with ``regime_id`` the
    scenario Regime's own. ``deflator`` names the index, the per-state labels and any
    hard-currency fallback (decision 5); ``phases``, ``after_stress``, ``crisis_months``
    and ``protection_check`` stay nominal. Without ``basis`` the response is unchanged.

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
    real = basis == "real"
    if regime_id is None:
        scenario = None
    elif real:
        scenario = scenario_inflation(regime_id)
    else:
        # Since FMRE-33 a scenario moves the nominal profile too (its pass-through); a base
        # Regime changes nothing and the response is the one without regime_id.
        scenario = scenario_of_current(regime_id, confirm_regime(regime_id))
    if (chosen is not ProfileMethod.CASCADE or currency is not None or real
            or scenario is not None):
        try:
            universe = service.load_universe(conn, calibration_id)
            inst = next((i for i in universe.instruments
                         if i["instrument_id"] == instrument_id), None)
            if inst is None:
                raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")
            real_ctx = (_real_context(conn, universe.map_id, scenario, currency)
                        if real else None)
            view = service.estimate_view(
                universe, inst, chosen,
                real_ctx["currency"] if real_ctx is not None else currency)
        except CurrencyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # The protection rules are statements about the historical nominal profile
        # (FMRE-32): judged before any scenario or deflator touches it.
        nominal_view = view
        real_extra: dict[str, Any] = {}
        pt_ctx = None
        if scenario is not None:
            pt_ctx = _pass_through_context(
                conn, [inst], universe.map_id, scenario,
                real_ctx["currency"] if real_ctx is not None else currency)
            view = _carry(pt_ctx, view, instrument_id)
        if real_ctx is not None:
            view, real_extra = _real_profile(real_ctx, universe, inst, chosen, currency,
                                             scenario, view, pt_ctx)
        if pt_ctx is not None:
            entry = pt_ctx["betas"][instrument_id]
            real_extra["inflation_pass_through"] = {
                **_pass_through_provenance(pt_ctx, [instrument_id]).model_dump(mode="json"),
                "house_beta": entry["house_beta"], "house_duration": entry["house_duration"],
                "rule": entry["rule"],
                "note": ("states and unsmoothed are carried to the scenario; phases, "
                         "after_stress, crisis_months and protection_check stay the "
                         "historical nominal ones"),
            }
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
            "protection_check": service.protection_check(nominal_view,
                                                         service.protection_type(inst)),
            **extra,
            **real_extra,
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


# ---------------------------------------------------------------------------
# Inflation pass-through beta: the house table and the CIO's overrides (FMRE-33..37)
# ---------------------------------------------------------------------------


class BetaOverrideIn(BaseModel):
    """``PUT /v1/inflation-beta/{instrument_id}``: one new override version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: 0 .. 1.5; null reverts to the house beta.
    beta: float | None = Field(..., ge=0.0, le=1.5)
    #: Years, 0 .. 30; null (or omitted) keeps the house duration.
    duration: float | None = Field(None, ge=0.0, le=30.0)
    reason: str = Field(..., min_length=1)
    set_by: str = Field(..., min_length=1)


def _beta_row(inst: dict, entry: dict) -> dict[str, Any]:
    return {"instrument_id": inst["instrument_id"], "name": inst["name"],
            "asset_class": inst["asset_class"], "role": inst["role"],
            "proxy_symbol": inst.get("proxy_symbol"), **entry}


def _active_instruments(conn: db.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT instrument_id, name, role, asset_class, proxy_symbol, active FROM instrument "
        "WHERE active = 1 ORDER BY name").fetchall()]


@app.get("/v1/inflation-beta", tags=["return-set"])
def inflation_beta(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Every active instrument's inflation pass-through: its house type, the house beta,
    the CIO's override if any, the beta in force, and the duration where relevant.

    Read under a scenario Regime only (FMRE-33): scenario nominal = historical real +
    beta * ln(1 + scenario inflation), a nominal bond also taking the duration loss. Base
    Regimes are not touched by it.
    """
    from engines.fund_map import pass_through as pt
    try:
        cal = service.ensure_pass_through_calibration(conn)
    except service.PassThroughError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    instruments = _active_instruments(conn)
    betas = service.effective_betas(conn, instruments)
    return {
        "calibration": {"version": cal["version"], "calibration_id": cal["calibration_id"],
                        "source": cal["source"], "created_at": cal["created_at"],
                        "types": cal["payload"]["types"], "rules": cal["payload"]["rules"],
                        "blocks": cal["payload"]["blocks"], "roles": cal["payload"]["roles"],
                        "formula": pt.FORMULA},
        "bounds": {"beta": [pt.BETA_MIN, pt.BETA_MAX],
                   "duration": [pt.DURATION_MIN, pt.DURATION_MAX]},
        "instruments": [_beta_row(i, betas[i["instrument_id"]]) for i in instruments],
    }


@app.get("/v1/inflation-beta/{instrument_id}/history", tags=["return-set"])
def inflation_beta_history(
    instrument_id: str,
    conn: db.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Every override version of one instrument, newest first (the first is in force).

    A revert is a version with ``beta: null`` (the house beta). An instrument never
    overridden answers ``[]``; an unknown one 404.
    """
    if conn.execute("SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")
    return [dict(r) for r in conn.execute(
        "SELECT version, beta, duration, reason, set_by, set_at FROM inflation_beta_override "
        "WHERE instrument_id = %s ORDER BY version DESC", (instrument_id,)).fetchall()]


@app.put("/v1/inflation-beta/{instrument_id}", tags=["return-set"])
def put_inflation_beta(
    instrument_id: str,
    payload: BetaOverrideIn,
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Set the CIO's override of one instrument's pass-through beta (and duration).

    Append-only: every call writes the next version, nothing is updated or deleted; a
    version with ``beta: null`` reverts to the house beta. The beta in force enters every
    scenario set's ``return_set_id`` and ``provenance.inflation_pass_through``.
    """
    import psycopg

    inst = conn.execute(
        "SELECT instrument_id, name, role, asset_class, proxy_symbol, active FROM instrument "
        "WHERE instrument_id = %s", (instrument_id,)).fetchone()
    if inst is None:
        raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")
    try:
        row = service.put_beta_override(
            conn, instrument_id, beta=payload.beta, duration=payload.duration,
            reason=payload.reason, set_by=payload.set_by)
    except service.PassThroughError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail=(
            f"another override of {instrument_id!r} was written at the same moment; "
            f"read GET /v1/inflation-beta and try again")) from exc
    inst = dict(inst)
    entry = service.effective_beta(inst, row)
    return {"written": {k: row[k] for k in ("instrument_id", "version", "beta", "duration",
                                            "reason", "set_by", "set_at",
                                            "calibration_version")},
            **_beta_row(inst, entry)}


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
