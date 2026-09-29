"""Register integrity: are these 54 instruments distinct, and are they what they claim?

Two checks that the register cannot perform on itself, because both need price history:

* **Overlap** -- which entries are, in practice, the same instrument.
* **Classification** -- whether measured behaviour matches the assigned role.

Both became answerable only once the proxy histories were downloaded, and both found
something.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_conn
from engines.fund_map import numerics as num
from engines.fund_map import service
from engines.fund_map.estimate import correlation
from store import db
from store.etl.universe import read_universe

router = APIRouter(prefix="/v1/data", tags=["data"])

#: Above this, two monthly series are the same series for practical purposes.
DUPLICATE_THRESHOLD = 0.95

#: Fewer shared months than this and a correlation says nothing.
MIN_SHARED_MONTHS = 36

#: A Gain instrument below this beta, or a Protection instrument above it, is worth a look.
BETA_BOUND = 0.40

#: What equity beta is measured against: the longest broad developed-market series in the
#: register, so that most comparisons have a usable overlap.
BENCHMARK_ID = "INS-us-equities"


def _load(conn: db.Connection):
    rows = conn.execute(
        "SELECT instrument_id, name, role, asset_class, proxy_symbol, proxy_grade "
        "FROM instrument ORDER BY name"
    ).fetchall()
    series = {
        r["instrument_id"]: {
            x["period"]: x["value"]
            for x in conn.execute(
                "SELECT period, value FROM instrument_return WHERE instrument_id = %s",
                (r["instrument_id"],),
            )
        }
        for r in rows
    }
    return rows, series


@router.get("/overlap")
def overlap(
    threshold: float = Query(DUPLICATE_THRESHOLD, ge=0.5, le=1.0),
    conn: db.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """Which registered instruments are, in practice, the same instrument.

    Overlap matters beyond tidiness: the Portfolio Optimiser's objective has a floor that
    scales with the size of the universe, so two entries that are really one count twice
    and move measured leverage.

    **The causes are reported separately, because they need different fixes.** A shared
    Bloomberg ticker is a defect in the register. A shared *proxy* is a limitation of this
    build -- two genuinely different instruments with no distinct public stand-in.
    Reporting them together would blame the register for something this engine did.
    """
    tickers = {i.name: i.ticker for i in read_universe()}
    rows, series = _load(conn)
    usable = [r for r in rows if len(series[r["instrument_id"]]) >= MIN_SHARED_MONTHS]

    register_defect: list[dict[str, Any]] = []
    proxy_artefact: list[dict[str, Any]] = []
    economic: list[dict[str, Any]] = []

    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = usable[i], usable[j]
            sa, sb = series[a["instrument_id"]], series[b["instrument_id"]]
            shared = sorted(set(sa) & set(sb))
            if len(shared) < MIN_SHARED_MONTHS:
                continue
            r = correlation([sa[p] for p in shared], [sb[p] for p in shared])
            if r is None or r < threshold:
                continue
            item = {
                "a": a["name"], "b": b["name"], "correlation": r,
                "shared_months": len(shared),
                "a_ticker": tickers.get(a["name"]), "b_ticker": tickers.get(b["name"]),
                "proxy": a["proxy_symbol"],
            }
            same_ticker = bool(tickers.get(a["name"])) and tickers.get(a["name"]) == tickers.get(b["name"])
            same_proxy = bool(a["proxy_symbol"]) and a["proxy_symbol"] == b["proxy_symbol"]
            if same_ticker:
                register_defect.append(item)
            elif same_proxy:
                proxy_artefact.append(item)
            else:
                economic.append(item)

    # Ticker collisions are a register fact and need no price history to find.
    by_ticker: dict[str, list[str]] = {}
    for name, ticker in tickers.items():
        if ticker:
            by_ticker.setdefault(ticker, []).append(name)
    collisions = [
        {"ticker": t, "instruments": sorted(v)}
        for t, v in sorted(by_ticker.items()) if len(v) > 1
    ]

    for group in (register_defect, proxy_artefact, economic):
        group.sort(key=lambda x: -x["correlation"])

    return {
        "threshold": threshold,
        "min_shared_months": MIN_SHARED_MONTHS,
        "compared": len(usable),
        "ticker_collisions": collisions,
        "ticker_collision_instruments": sum(len(c["instruments"]) for c in collisions),
        "register_defect": register_defect,
        "proxy_artefact": proxy_artefact,
        "economic_overlap": economic,
        "reading": (
            "A ticker collision is a defect in the register and needs a decision about "
            "what the duplicated entry was meant to be. A proxy artefact is this build's "
            "limitation and disappears when the real series arrive. Economic overlap is "
            "neither: two distinct instruments can legitimately move together, and whether "
            "that is redundancy is a portfolio question rather than a data one."
        ),
    }


@router.get("/classification")
def classification(conn: db.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Does each instrument's measured behaviour match the role it is registered under?

    Manual section 11.4 derives a role from the measured profile: rising with the
    environment is Gain, paying in crisis is Protection, peaking in contraction is
    Stabilisation, paying a steady distribution is Income. The register assigns roles by
    name. This checks one against the other.

    Two measurements, both from the instrument's own returns: **equity beta** against the
    longest broad US series, and the **mean return in crisis months** on the state axis.

    Neither is conclusive alone. The crisis figure in particular is measured at a *monthly*
    horizon, which understates any hedge whose payoff is annual -- a known fault of the
    instrument estimator, not of the classification. A flag raised on that basis says so
    rather than accusing the register.
    """
    calibration_id = service.latest_calibration_id(conn)
    map_id = service.latest_state_map_id(conn, calibration_id)
    state_map = service.load_state_map(conn, map_id)
    modal = service.modal_signal_by_period(conn)
    crisis_months = {p for p, s in modal.items() if state_map.state_for(s) <= 5}

    rows, series = _load(conn)
    benchmark = series.get(BENCHMARK_ID, {})
    out: list[dict[str, Any]] = []

    for r in rows:
        own = series[r["instrument_id"]]
        if len(own) < MIN_SHARED_MONTHS:
            continue

        beta = None
        if r["instrument_id"] == BENCHMARK_ID:
            beta = 1.0
        else:
            shared = sorted(set(own) & set(benchmark))
            if len(shared) >= MIN_SHARED_MONTHS:
                rho = correlation([own[p] for p in shared], [benchmark[p] for p in shared])
                spread_b = num.std([benchmark[p] for p in shared])
                if rho is not None and spread_b:
                    beta = rho * num.std([own[p] for p in shared]) / spread_b

        in_crisis = [math.log1p(v) for p, v in own.items() if p in crisis_months and v > -1]
        crisis_mean = 12 * num.mean(in_crisis) if len(in_crisis) >= 6 else None

        role = r["role"]
        flag = None
        explanation = None
        if role == "gain" and beta is not None and beta < BETA_BOUND:
            flag = "low equity beta for a Gain instrument"
        elif role == "protection" and beta is not None and beta > BETA_BOUND:
            flag = "high equity beta for a Protection instrument"
        elif role == "protection" and crisis_mean is not None and crisis_mean < -0.05:
            flag = "loses in crisis while registered as Protection"
            explanation = (
                "Measured at a monthly horizon. A hedge whose payoff is annual reads "
                "negative here even when it is not -- see the instrument-estimator note."
            )
        elif role == "stabilisation" and beta is not None and beta > 0.8:
            flag = "moves with equities; not behaving as a stabiliser"
        elif role == "income" and beta is not None and beta > 1.0:
            flag = "higher beta than equities, for an Income instrument"

        if flag and r["proxy_grade"] == "weak":
            explanation = (explanation or "") + (
                " The proxy for this instrument is graded weak, so the measurement may "
                "describe the stand-in rather than the instrument."
            )

        out.append({
            "instrument_id": r["instrument_id"],
            "name": r["name"],
            "role": role,
            "asset_class": r["asset_class"],
            "proxy_symbol": r["proxy_symbol"],
            "proxy_grade": r["proxy_grade"],
            "months": len(own),
            "equity_beta": beta,
            "crisis_mean": crisis_mean,
            "volatility": num.std([math.log1p(v) for v in own.values() if v > -1]) * math.sqrt(12),
            "flag": flag,
            "explanation": explanation,
        })

    flagged = [o for o in out if o["flag"]]
    return {
        "benchmark": BENCHMARK_ID,
        "beta_bound": BETA_BOUND,
        "assessed": len(out),
        "flagged": len(flagged),
        "instruments": out,
        "reading": (
            "A flag is a question, not a verdict. Three things raise one: the role is "
            "genuinely wrong, the proxy is not the instrument, or the crisis figure is "
            "measured at the wrong horizon. The explanation says which is suspected."
        ),
    }
