"""The data tester: where every number came from, and what was done to it.

This exists because a profile is only as believable as the chain behind it, and that chain
crosses four files, two frequencies and a spreadsheet nobody reading the API will ever
open. The endpoints here expose each link with live numbers rather than prose:

============================  =================================================
``/v1/data/method``           the formulas, as data, so the page and the code
                              cannot drift apart
``/v1/data/sources``          every source file, its hash, and what it feeds
``/v1/data/series``           the raw annual record, as loaded
``/v1/data/indicators``       one year, taken from raw quantity to ``ec_cycle``
                              through every intermediate stage
``/v1/data/trace``            one block, taken from raw series to 25 states
``/v1/data/bridge``           one month, taken from the signal row to a
                              calibration state
============================  =================================================

Nothing here computes anything the engine does not already compute. It re-runs the same
functions on the same inputs and shows the intermediate values, which is the only honest
way to document a pipeline: if this page is wrong, it is wrong because the engine is.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_conn
from engines.fund_map import numerics as num
from engines.fund_map import service
from engines.fund_map.calibrate import BLOCKS, BLOCKS_BY_KEY, PHASE_KNOTS, state_axis
from engines.fund_map.indicators import (
    FIRST_YEAR,
    INDICATOR_ORDER,
    INDICATOR_SIGNS,
    LAST_YEAR,
    SENTIMENT_WEIGHTS,
    VOLATILITY_LOOKBACK,
)
from engines.fund_map.phases import (
    BOUND_BUSINESS,
    BOUND_INNOVATION,
    BOUND_RECESSION,
    PHASE_NAMES,
    PHASE_VALUES,
    classify,
)
from engines.fund_map.state_map import cycle_sigma_to_axis
from store import db
from store.etl.long_record import SERIES

router = APIRouter(prefix="/v1/data", tags=["data"])


# ---------------------------------------------------------------------------
# Where a file came from
# ---------------------------------------------------------------------------

#: Classification of every byte the store was built from.
#:
#: **Nothing in this engine was downloaded.** There is no network call in the ETL, no
#: cached API response, no scraped table. Every figure traces to a file that was already
#: on the NAS before this build started, and the classification below is derived from the
#: path so it cannot drift from where the file actually sits. The distinction matters for
#: the reliability ladder: a house series with a named author and a thesis behind it is
#: not the same evidence as something pulled from a public endpoint, and a reader should
#: not have to guess which they are looking at.
ORIGIN_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "Knowledge_Center",
        "nas:house-research",
        "SIM Research / Knowledge_Center. Steiner (2021), Dynamic Investment -- the "
        "thesis, its MATLAB model and its 19 source workbooks. Authored in-house, with a "
        "published reference this engine reproduces to 5e-16.",
    ),
    (
        "andersCH-prototype_old",
        "nas:prototype",
        "The previous build's own files. The monthly andersCH report and the published "
        "54-instrument register. Supplied to the project; upstream owner and refresh "
        "cadence were never recorded, which caps how far it can be trusted.",
    ),
)

UNCLASSIFIED_ORIGIN = (
    "unclassified",
    "Not under a known NAS root. Check before trusting it.",
)


def classify_origin(origin: str) -> tuple[str, str]:
    for marker, kind, note in ORIGIN_RULES:
        if marker.lower() in (origin or "").lower():
            return kind, note
    return UNCLASSIFIED_ORIGIN


# ---------------------------------------------------------------------------
# The method, as data
# ---------------------------------------------------------------------------

#: Every step of the chain, in order. Held here rather than in the page so that the
#: documentation and the endpoints are served from one place.
METHOD_STEPS: tuple[dict[str, Any], ...] = (
    {
        "step": 1,
        "name": "Build each raw indicator quantity",
        "frequency": "annual, 1871-2020",
        "what": (
            "Eight economic indicators, each assembled from the stitched source columns. "
            "Debt saturation is a ratio; the rest are rates, spreads or log differences."
        ),
        "formulas": [
            "debt(t)         = (gov_debt(t) + loans(t)) / gdp(t)",
            "yield_curve(t)  = lrate(t) - srate(t)",
            "monetary(t)     = dlog broad(t) - dlog narrow(t)",
            "sentiment(t)    = 0.10*bill(t) + 0.50*bond(t) + 0.40*dlog spx(t)",
            "earnings(t)     = dlog erng(t)",
            "unemployment(t) = ump(t)",
            "inflation(t)    = cpi(t)",
            "volatility(t)   = movstd( detrended sentiment, trailing 3 )",
        ],
        "why": (
            "Volatility is computed from the *de-trended* sentiment residual, not the raw "
            "blend, and the window is backward-looking, so the indicator never sees the "
            "future."
        ),
    },
    {
        "step": 2,
        "name": "De-trend each indicator to residuals",
        "frequency": "annual",
        "what": "Debt saturation exponentially; the other seven linearly.",
        "formulas": [
            "debt:   fit y = a*exp(b*t) by nonlinear least squares;  e(t) = y(t) - a*exp(b*t)",
            "others: fit y = alpha + beta*t by OLS;                  e(t) = y(t) - (alpha + beta*t)",
        ],
        "why": (
            "What the model wants is the deviation from each series' own long-run path, "
            "not its level. A debt ratio that has risen for a century is not evidence that "
            "every recent year is a crisis, and a raw level would say exactly that. Debt "
            "is exponential because a debt ratio compounds; a straight line would leave a "
            "curved residual and manufacture a trend in the cycle."
        ),
    },
    {
        "step": 3,
        "name": "Sign, standardise, average, standardise again",
        "frequency": "annual",
        "what": "The eight residuals become one number per year, in standard deviations.",
        "formulas": [
            "z_j(t)  = ( s_j * e_j(t) - mean_t[s_j * e_j] ) / sd_t[s_j * e_j]      (sd uses N-1)",
            "c(t)    = ( 1/8 ) * sum_j z_j(t)                                       (plain mean)",
            "ec(t)   = ( c(t) - mean_t c ) / sd_t c",
        ],
        "why": (
            "Four indicators carry s_j = -1 -- debt saturation, unemployment, inflation "
            "and volatility -- so that higher always means better. The average is "
            "unweighted: the manual's word 'weighted' refers to those signs, not to "
            "differing importance."
        ),
    },
    {
        "step": 4,
        "name": "Classify the year into one of five phases",
        "frequency": "annual",
        "what": "Cut ec_cycle at three thresholds, symmetric about zero.",
        "formulas": [
            f"ec >= +{BOUND_BUSINESS:.2f}                 -> boom          (phase value {PHASE_VALUES[4]:+.3f})",
            f"+{BOUND_RECESSION:.2f} <  ec <  +{BOUND_BUSINESS:.2f}   -> expansion     (phase value {PHASE_VALUES[3]:+.3f})",
            f"-{BOUND_RECESSION:.2f} <= ec <= +{BOUND_RECESSION:.2f}  -> stagnation    (phase value {PHASE_VALUES[2]:+.3f})",
            f"-{BOUND_BUSINESS:.2f} <  ec <  -{BOUND_RECESSION:.2f}   -> contraction   (phase value {PHASE_VALUES[1]:+.3f})",
            f"ec <= -{BOUND_BUSINESS:.2f}                 -> crisis        (phase value {PHASE_VALUES[0]:+.3f})",
        ],
        "why": (
            f"The thresholds come from the cycle's own tail frequency: {BOUND_INNOVATION} "
            f"sigma is where the leverage cycle shows up in the 150-year record, "
            f"{BOUND_BUSINESS} sigma is the business-cycle bound, {BOUND_RECESSION} the "
            f"recession bound. The phase *value* is the midpoint of the bounds that "
            f"enclose it, which is what the published workbook labels its rows with."
        ),
    },
    {
        "step": 5,
        "name": "Build the eight block return series",
        "frequency": "annual, nominal",
        "what": "What an investor actually earned, per asset class, per year.",
        "formulas": [
            "short_rate   = bill(t)                          a rate, read straight through",
            "long_rate    = bond(t)                          a rate, not a holding",
            "equity       = dlog spx(t)",
            "gov_bonds    = bondtr(t)                        already a total return, 1871-2015",
            "commodities  = 0.5*dlog oil(t) + 0.5*dlog wheat(t)",
            "gold         = dlog gold(t)",
            "agriculture  = dlog ag(t)                       1911-2020",
            "real_estate  = dlog house(t)                    1891-2020",
        ],
        "why": (
            "The series are nominal and are **not** de-trended. The reference computes "
            "de-trended residuals for them and then deliberately does not use them. Real "
            "is obtained by subtracting current inflation at the point of use, so that a "
            "figure cannot silently over- or under-state the expected return. Three blocks "
            "are shorter than the timeline and are matched only where they exist -- never "
            "back-filled."
        ),
    },
    {
        "step": 6,
        "name": "Average each block within each phase",
        "frequency": "annual",
        "what": "Five numbers per block. This is the entire estimation step.",
        "formulas": [
            "mu(b, p) = mean{ r_b(t) : phase(t) = p }",
            "n(b, p)  = count of those years",
        ],
        "why": (
            "A plain mean at every count, which is what the reference does and what the "
            "published figures were produced under. The manual specifies a sufficiency "
            "floor of 6 and a 20 % trimmed mean at 20 or more; both are implemented and "
            "the choice is stamped on the calibration, but the default reproduces the "
            "reference. Every phase clears the floor on the full-length blocks, so no "
            "phase knot needed the cascade."
        ),
    },
    {
        "step": 7,
        "name": "Interpolate the five estimates onto the 25-state axis",
        "frequency": "-",
        "what": "Shape-preserving monotone cubic interpolation, evaluated on a fixed grid.",
        "formulas": [
            "knots   x = [1, 2, 3, 4, 5]          the five phases, in order",
            "grid    q = 0.6, 0.8, ... , 5.4      25 points, five per phase band",
            "profile = pchip(x, mu(b, .))(q)",
        ],
        "why": (
            "**Five of the twenty-five states carry a measured number** -- states 3, 8, "
            "13, 18 and 23, the middle of each band. Sixteen are interpolated between "
            "them. Four (1, 2, 24, 25) fall outside the hull of the knots and are "
            "extrapolated; they are labelled as such. pchip rather than a cubic spline "
            "because a spline through sparse knots overshoots and can invent a return "
            "reversal between two states that never reverses in the data."
        ),
    },
    {
        "step": 8,
        "name": "Compose the four role profiles",
        "frequency": "-",
        "what": "Equal-weight composites of the blocks, aggregated at the phase level.",
        "formulas": [
            "mu(role, p) = sum_b w_b * mu(b, p)     w equal across the role's members",
            "profile     = pchip(x, mu(role, .))(q)",
        ],
        "why": (
            "Averaged at the phase level and interpolated afterwards, not the other way "
            "round: pchip is not linear in its ordinates, so the two differ. Averaging "
            "first is also the one with a meaning -- it is what an equal-weight holding of "
            "those blocks actually returned in that phase."
        ),
    },
    {
        "step": 9,
        "name": "Bridge the monthly signal onto the calibration axis",
        "frequency": "monthly",
        "what": "Map each Market Risk Signal column to a position on the phase axis.",
        "formulas": [
            "q_s   = mean over months of pi_s(t)                 unconditional mass on column s",
            "c_s   = 100 * ( sum_{k<s} q_k + q_s / 2 )           that column's centile",
            "sig_s = percentile( ec_cycle, c_s )                 the cycle at the same centile",
            "a_s   = piecewise-linear sig -> [1..5] through the five phase values",
            "state = nearest point of the 25-grid to a_s",
        ],
        "why": (
            "The two axes both happen to have 25 positions and that is a coincidence. The "
            "signal's columns are named bands of a technical reading; the calibration axis "
            "is derived from a 150-year macro cycle. Mapping column n to state n would "
            "assert they are calibrated the same way, which nobody has shown. Matching by "
            "quantile asserts only that both spend the same share of their history at or "
            "below a given point."
        ),
    },
)


@router.get("/method")
def method() -> dict[str, Any]:
    """The whole transformation, step by step, with the formulas and the constants."""
    return {
        "window": {"first_year": FIRST_YEAR, "last_year": LAST_YEAR,
                   "observations": LAST_YEAR - FIRST_YEAR + 1},
        "indicators": [
            {"name": n, "sign": INDICATOR_SIGNS[n],
             "detrend": "exp1" if n == "debt" else "poly1"}
            for n in INDICATOR_ORDER
        ],
        "sentiment_weights": SENTIMENT_WEIGHTS,
        "volatility_lookback": VOLATILITY_LOOKBACK,
        "phase_bounds": {"innovation": BOUND_INNOVATION, "business": BOUND_BUSINESS,
                         "recession": BOUND_RECESSION},
        "phase_names": list(PHASE_NAMES),
        "phase_values": list(PHASE_VALUES),
        "state_grid": state_axis(),
        "phase_knots": list(PHASE_KNOTS),
        "measured_states": [3, 8, 13, 18, 23],
        "extrapolated_states": [1, 2, 24, 25],
        "blocks": [
            {"key": b.key, "label": b.label, "role": b.role, "kind": b.kind, "note": b.note}
            for b in BLOCKS
        ],
        "steps": list(METHOD_STEPS),
    }


# ---------------------------------------------------------------------------
# Provenance and raw data
# ---------------------------------------------------------------------------


@router.get("/sources")
def sources(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Every file the store was built from, with its hash and what it feeds."""
    feeds: dict[str, list[str]] = {}
    for spec in SERIES:
        feeds.setdefault(spec.filename, []).append(spec.key)
    notes = {s.filename: s.note for s in SERIES}
    columns = {s.filename: s.column for s in SERIES}

    rows = conn.execute(
        "SELECT name, sha256, byte_size, loaded_at, origin, note FROM source_file ORDER BY name"
    ).fetchall()
    counts = {
        r["series_key"]: (r["n"], r["lo"], r["hi"])
        for r in conn.execute(
            "SELECT series_key, COUNT(*) AS n, MIN(year) AS lo, MAX(year) AS hi "
            "FROM long_series GROUP BY series_key"
        )
    }
    out = []
    for r in rows:
        keys = feeds.get(r["name"], [])
        kind, origin_note = classify_origin(r["origin"])
        out.append({
            "file": r["name"],
            "origin_kind": kind,
            "origin_note": origin_note,
            "sha256": r["sha256"],
            "byte_size": r["byte_size"],
            "loaded_at": r["loaded_at"],
            "origin": r["origin"],
            "note": r["note"] or notes.get(r["name"], ""),
            "column": columns.get(r["name"]),
            "series": [
                {"key": k, "observations": counts.get(k, (0, None, None))[0],
                 "first_year": counts.get(k, (0, None, None))[1],
                 "last_year": counts.get(k, (0, None, None))[2]}
                for k in keys
            ],
        })

    kinds: dict[str, int] = {}
    for item in out:
        kinds[item["origin_kind"]] = kinds.get(item["origin_kind"], 0) + 1

    # Downloaded series are a feed, not a file, so they are counted from the rows they
    # wrote rather than from source_file. Leaving them out of this endpoint would make the
    # provenance statement true of the files and false of the store.
    feeds = []
    downloaded = 0
    for row in conn.execute(
        "SELECT source, COUNT(*) AS rows, COUNT(DISTINCT instrument_id) AS instruments, "
        "       MIN(period) AS lo, MAX(period) AS hi, MAX(ingested_at) AS ingested "
        "FROM instrument_return GROUP BY source ORDER BY source"
    ):
        parts = row["source"].split(":")
        kind = (f"internet:{parts[0]}" if parts[0] in ("yahoo", "cboe")
                else "nas:prototype")
        if kind.startswith("internet"):
            downloaded += row["rows"]
        feeds.append({
            "source": row["source"],
            "origin_kind": kind,
            "symbol": parts[1] if len(parts) > 1 else None,
            "proxy_grade": parts[2] if len(parts) > 2 else None,
            "rows": row["rows"],
            "instruments": row["instruments"],
            "span": [row["lo"], row["hi"]],
            "ingested_at": row["ingested"],
        })
        kinds[kind] = kinds.get(kind, 0) + 1

    return {
        "sources": out,
        "count": len(out),
        "feeds": feeds,
        "by_origin": kinds,
        "downloaded_rows": downloaded,
        "provenance_statement": (
            "Two kinds of origin, and the difference matters. **Files** -- the long annual "
            "record and the monthly report -- were already on the NAS before this engine "
            "existed and were never downloaded: Knowledge_Center (house research, Steiner "
            "2021) and the previous build's own directory. **Feeds** are downloaded, and "
            "as of the proxy import there are now some: public ETF histories standing in "
            "for instruments the register names by Bloomberg ticker. Every downloaded row "
            "is labelled internet:yahoo and carries the grade of the proxy it came from. "
            "A proxy is not the instrument."
        ),
    }


@router.get("/series")
def series(
    key: str | None = Query(None, description="Omit to list what is available."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """The long annual record exactly as loaded -- no transformation applied."""
    if key is None:
        rows = conn.execute(
            "SELECT series_key, COUNT(*) AS n, MIN(year) AS lo, MAX(year) AS hi, "
            "       MIN(value) AS vmin, MAX(value) AS vmax "
            "FROM long_series GROUP BY series_key ORDER BY series_key"
        ).fetchall()
        notes = {s.key: s.note for s in SERIES}
        return {"series": [{**dict(r), "note": notes.get(r["series_key"], "")} for r in rows]}

    rows = conn.execute(
        "SELECT year, value, source_file FROM long_series WHERE series_key = %s ORDER BY year",
        (key,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"no series {key!r}")
    spec = next((s for s in SERIES if s.key == key), None)
    return {
        "key": key,
        "note": spec.note if spec else "",
        "source_file": rows[0]["source_file"],
        "source_column": spec.column if spec else None,
        "observations": len(rows),
        "values": [{"year": r["year"], "value": r["value"]} for r in rows],
    }


# ---------------------------------------------------------------------------
# Traces: the same computation, with its working shown
# ---------------------------------------------------------------------------


@router.get("/indicators")
def indicators(
    year: int = Query(2008, ge=FIRST_YEAR, le=LAST_YEAR),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One year, from raw indicator residual to ``ec_cycle`` and a phase.

    Reads the stored residual and standardised value for each indicator, so what is shown
    is what the calibration used rather than a re-derivation that might differ.
    """
    rows = conn.execute(
        "SELECT name, residual, standardised FROM environment_indicator "
        "WHERE year = %s ORDER BY name", (year,)
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"no indicators for {year}")
    env = conn.execute(
        "SELECT cycle, phase, inflation FROM market_environment WHERE year = %s", (year,)
    ).fetchone()

    standardised = {r["name"]: r["standardised"] for r in rows}
    ordered = [n for n in INDICATOR_ORDER if n in standardised]
    mean_z = num.mean([standardised[n] for n in ordered])

    return {
        "year": year,
        "indicators": [
            {
                "name": n,
                "sign": INDICATOR_SIGNS[n],
                "detrend": "exp1" if n == "debt" else "poly1",
                "residual": next(r["residual"] for r in rows if r["name"] == n),
                "standardised": standardised[n],
            }
            for n in ordered
        ],
        "mean_of_standardised": mean_z,
        "cycle": env["cycle"],
        "cycle_note": (
            "ec_cycle is the mean above, standardised a second time across all 150 years. "
            "It is therefore not equal to the mean shown, except by coincidence."
        ),
        "phase": PHASE_NAMES[env["phase"]],
        "phase_index": env["phase"],
        "classification": (
            f"ec = {env['cycle']:+.4f} sigma -> {PHASE_NAMES[classify(env['cycle'])]}"
        ),
        "inflation": env["inflation"],
    }


@router.get("/trace")
def trace(
    block: str = Query("gold"),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One block, from its raw source series to its 25-state profile."""
    if block not in BLOCKS_BY_KEY:
        raise HTTPException(
            status_code=404,
            detail=f"no block {block!r}; expected one of {sorted(BLOCKS_BY_KEY)}",
        )
    spec = BLOCKS_BY_KEY[block]
    calibration_id = service.latest_calibration_id(conn)
    row = conn.execute(
        "SELECT * FROM calibration_block WHERE calibration_id = %s AND block_key = %s",
        (calibration_id, block),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"block {block!r} is not calibrated")

    phases = db.loads(row["phase_json"])
    profile = db.loads(row["profile_json"])
    methods = db.loads(row["methods_json"])
    n_obs = db.loads(row["n_obs_json"])

    # The years behind each phase bucket, so a reader can check the bucketing itself.
    years = conn.execute(
        "SELECT year, phase, cycle FROM market_environment "
        "WHERE year BETWEEN %s AND %s ORDER BY year",
        (row["first_year"], row["last_year"]),
    ).fetchall()
    by_phase: dict[str, list[int]] = {p: [] for p in PHASE_NAMES}
    for y in years:
        by_phase[PHASE_NAMES[y["phase"]]].append(y["year"])

    return {
        "block": block,
        "label": spec.label,
        "role": spec.role,
        "note": spec.note,
        "kind": spec.kind,
        "window": [row["first_year"], row["last_year"]],
        "n_obs_total": row["n_obs_total"],
        "truncated": row["n_obs_total"] != (LAST_YEAR - FIRST_YEAR + 1),
        "phase_estimates": [
            {**p, "years": by_phase.get(p["phase"], [])} for p in phases
        ],
        "knots": list(PHASE_KNOTS),
        "grid": state_axis(),
        "states": [
            {"state": i + 1, "axis": state_axis()[i], "value": profile[i],
             "method": methods[i], "n_obs": n_obs[i]}
            for i in range(len(profile))
        ],
    }


@router.get("/bridge")
def bridge(
    period: str | None = Query(None, description="YYYY-MM; defaults to the latest month."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One month, from its raw signal row to a calibration state."""
    calibration_id = service.latest_calibration_id(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    if map_id is None:
        raise HTTPException(status_code=503, detail="no state map; load the monthly signal")

    if period is None:
        period = conn.execute("SELECT MAX(period) AS p FROM market_risk_month").fetchone()["p"]
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
    modal = month["modal_state"]
    entry = smap.entries[modal - 1]

    return {
        "period": period,
        "raw_sum": month["raw_sum"],
        "in_tolerance": bool(month["in_tolerance"]),
        "normalisation": (
            "The feed's row sums to %.4f rather than 100, so it is normalised per row. "
            "Five months in the record are more than 0.5 out and are flagged rather than "
            "silently rescaled." % month["raw_sum"]
        ),
        "distribution": distribution,
        "modal_state": modal,
        "mean_state": month["mean_state"],
        "bridge": {
            "signal_state": entry.signal_state,
            "centile": entry.centile,
            "cycle_value": entry.cycle_value,
            "axis_value": entry.axis_value,
            "calibration_state": entry.calib_state,
            "axis_from_sigma": cycle_sigma_to_axis(entry.cycle_value),
        },
        "map": smap.as_rows(),
        "map_id": map_id,
        "note": (
            "The modal column is used rather than the whole distribution because bucketing "
            "needs one label per month. That is the same reason the Regime contract "
            "publishes an integer path alongside its distributions."
        ),
    }


@router.get("/instrument-trace")
def instrument_trace(
    instrument_id: str = Query("INS-precious-metals"),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """One instrument, from monthly returns to state buckets -- and the horizon check.

    **This endpoint is where the instrument estimator's weakness is visible.** It reports
    each bucket's estimate next to its standard error, and the same crisis months measured
    over one month and over the following twelve. For a crisis hedge the two disagree in
    sign, because the payoff is an annual-horizon phenomenon and a monthly bucket splits
    the drawdown from the recovery.
    """
    row = conn.execute(
        "SELECT * FROM instrument WHERE instrument_id = %s", (instrument_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")

    calibration_id = service.latest_calibration_id(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    smap = service.load_state_map(conn, map_id)
    modal = service.modal_signal_by_period(conn)

    returns = {
        r["period"]: r["value"]
        for r in conn.execute(
            "SELECT period, value FROM instrument_return WHERE instrument_id = %s "
            "ORDER BY period", (instrument_id,)
        )
    }
    months = sorted(returns)
    index = {p: i for i, p in enumerate(months)}

    buckets: dict[int, list[str]] = {}
    for period in months:
        signal = modal.get(period)
        if signal is None:
            continue
        buckets.setdefault(smap.state_for(signal), []).append(period)

    bucket_rows = []
    for state in sorted(buckets):
        periods = buckets[state]
        logs = [math.log1p(returns[p]) for p in periods if returns[p] > -1]
        if len(logs) < 2:
            continue
        estimate = 12 * num.mean(logs)
        std_error = 12 * num.std(logs) / math.sqrt(len(logs))
        bucket_rows.append({
            "state": state,
            "n_obs": len(logs),
            "estimate": estimate,
            "std_error": std_error,
            "ci_low": estimate - 1.96 * std_error,
            "ci_high": estimate + 1.96 * std_error,
            "periods": periods,
        })

    # The horizon comparison, for the crisis bucket.
    def compound(period: str, k: int) -> float | None:
        i = index[period]
        window = months[i:i + k]
        if len(window) < k:
            return None
        total = 1.0
        for m in window:
            total *= 1 + returns[m]
        return total - 1

    crisis = buckets.get(1, [])
    horizon = []
    for period in crisis:
        horizon.append({
            "period": period,
            "that_month": returns[period],
            "next_6m": compound(period, 6),
            "next_12m": compound(period, 12),
        })
    monthly_logs = [math.log1p(returns[p]) for p in crisis if returns[p] > -1]
    twelve = [h["next_12m"] for h in horizon if h["next_12m"] is not None]

    return {
        "instrument_id": instrument_id,
        "name": row["name"],
        "role": row["role"],
        "months": len(months),
        "window": [months[0], months[-1]] if months else None,
        "recovery_formula": (
            "r(t) = ( contribution_index(t) / contribution_index(t-1) - 1 ) / weight(t), "
            "dropped where weight <= 5 %"
        ),
        "recovery_caveat": (
            "Recovered from a tactically managed portfolio, so a return describes the "
            "asset *when the manager chose to hold it*, not the asset in that state. Only "
            "unconditional index series remove this."
        ),
        "buckets": bucket_rows,
        "noise": {
            "mean_abs_jump": num.mean([
                abs(b["estimate"] - a["estimate"])
                for a, b in zip(bucket_rows, bucket_rows[1:])
            ]) if len(bucket_rows) > 1 else None,
            "mean_std_error": num.mean([b["std_error"] for b in bucket_rows])
            if bucket_rows else None,
            "reading": (
                "If the mean jump between adjacent states is about the same size as the "
                "standard error of one bucket, the shape between measured states is "
                "sampling noise rather than signal."
            ),
        },
        "horizon_check": {
            "state": 1,
            "label": "crisis",
            "rows": horizon,
            "mean_that_month_annualised": 12 * num.mean(monthly_logs) if monthly_logs else None,
            "mean_next_12m": num.mean(twelve) if twelve else None,
            "reading": (
                "The calibration measures annual returns in crisis *years*. The instrument "
                "estimator measures monthly returns in crisis *months*. Where these two "
                "disagree in sign, the instrument profile is not a weaker version of the "
                "block profile -- it is an answer to a different question."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Level 3: instrument performance
# ---------------------------------------------------------------------------


def _performance(returns: dict[str, float]) -> dict[str, Any]:
    """Descriptive statistics for one monthly return series.

    **These are moments, and that is why they live here and not in a ``ReturnSet``.**
    Manual section 11.1 refuses to publish a mean or a variance in the contract, because a
    moment is a summary over states and summarising over states destroys the information
    everything downstream runs on. Computing them for a human looking at a diagnostic page
    is a different act from shipping them to an engine, and the two are kept apart by
    which endpoint they come out of.
    """
    months = sorted(returns)
    values = [returns[m] for m in months]
    if len(values) < 2:
        return {"months": len(values), "insufficient": True}

    logs = [math.log1p(v) for v in values if v > -1]
    growth = 1.0
    curve, peak, drawdown, trough_at = [], 1.0, 0.0, None
    for m, v in zip(months, values):
        growth *= 1 + v
        curve.append({"period": m, "index": growth})
        peak = max(peak, growth)
        dd = growth / peak - 1
        if dd < drawdown:
            drawdown, trough_at = dd, m

    # Per calendar year, so a reader can see which years carry the average.
    by_year: dict[str, float] = {}
    for m, v in zip(months, values):
        y = m[:4]
        by_year[y] = (1 + by_year.get(y, 0.0)) * (1 + v) - 1

    positive = sum(1 for v in values if v > 0)
    annualised = 12 * num.mean(logs)
    volatility = num.std(logs) * math.sqrt(12)

    return {
        "months": len(values),
        "first_period": months[0],
        "last_period": months[-1],
        "cumulative": growth - 1,
        "annualised_log_return": annualised,
        "annualised_volatility": volatility,
        # Reported as a ratio of the two figures above, with no risk-free rate subtracted.
        # It is not a Sharpe ratio and is not labelled one.
        "return_over_volatility": annualised / volatility if volatility else None,
        "max_drawdown": drawdown,
        "max_drawdown_trough": trough_at,
        "best_month": max(values),
        "worst_month": min(values),
        "hit_rate": positive / len(values),
        "curve": curve,
        "by_year": [{"year": y, "return": r} for y, r in sorted(by_year.items())],
    }


@router.get("/performance")
def performance(
    instrument_id: str | None = Query(None, description="Omit for the whole register."),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """How each instrument actually performed, from its recovered monthly returns.

    Descriptive only. Nothing here feeds the calibration or the contract -- it exists so
    that a profile can be read next to the history it was estimated from, which is the
    only way to judge whether the profile is plausible.
    """
    calibration_id = service.latest_calibration_id(conn)
    where = "WHERE i.instrument_id = %s" if instrument_id else ""
    params = (instrument_id,) if instrument_id else ()
    rows = conn.execute(
        f"SELECT i.instrument_id, i.name, i.role, i.asset_class, i.currency, i.ticker, "
        f"       i.region_scope, i.liquidity, i.proxy_symbol, i.proxy_grade, i.proxy_note, "
        f"       p.coverage, p.n_obs_total, p.borrowed_from "
        f"FROM instrument i "
        f"LEFT JOIN instrument_profile p "
        f"  ON p.instrument_id = i.instrument_id AND p.calibration_id = %s "
        f"{where} ORDER BY i.name",
        (calibration_id, *params),
    ).fetchall()
    if instrument_id and not rows:
        raise HTTPException(status_code=404, detail=f"no instrument {instrument_id!r}")

    out = []
    for r in rows:
        returns = {
            x["period"]: x["value"]
            for x in conn.execute(
                "SELECT period, value FROM instrument_return WHERE instrument_id = %s",
                (r["instrument_id"],),
            )
        }
        stats = _performance(returns)
        if instrument_id is None:
            stats.pop("curve", None)
            stats.pop("by_year", None)
        out.append({
            "instrument_id": r["instrument_id"],
            "name": r["name"],
            "role": r["role"],
            "asset_class": r["asset_class"],
            "currency": r["currency"],
            "ticker": r["ticker"],
            "region_scope": r["region_scope"],
            "liquidity": r["liquidity"],
            "proxy_symbol": r["proxy_symbol"],
            "proxy_grade": r["proxy_grade"],
            "proxy_note": r["proxy_note"],
            "coverage": r["coverage"],
            "borrowed_from": r["borrowed_from"],
            "has_history": bool(returns),
            "performance": stats,
        })

    with_history = [o for o in out if o["has_history"]]
    return {
        "calibration_id": calibration_id,
        "registered": len(out),
        "with_history": len(with_history),
        "without_history": len(out) - len(with_history),
        "unit_note": (
            "Monthly simple returns; annualised figures are 12 x the mean log return, and "
            "volatility is the log-return standard deviation scaled by sqrt(12)."
        ),
        "caveat": (
            "Recovered as contribution/weight from a tactically managed book, so a series "
            "describes the asset *while it was held*. Gaps are months the manager was out "
            "or under the 5 % weight floor, and the curve compounds across those gaps as "
            "though they were flat. Read it as the manager's experience of the "
            "instrument, not as the instrument's own track record."
        ),
        "instruments": out,
    }
