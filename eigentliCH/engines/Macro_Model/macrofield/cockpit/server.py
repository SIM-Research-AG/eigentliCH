"""The cockpit: a local dashboard for driving the model, browsing the data and exporting results.

Served on localhost by `macrofield cockpit`. It is a control surface over the same code paths the CLI
uses, not a second implementation: every endpoint calls `macrofield.pipeline`, `macrofield.calibration`
and `macrofield.reporting`, so a result seen here is the result the CLI would write.

Design decisions worth knowing:

- **The server sends data, the browser draws.** Traces are returned as JSON and plotted client-side with
  Plotly, rather than rendering figures server-side. That keeps the interactive charts independent of the
  matplotlib figures in `macrofield.reporting.charts`, which exist for the static book-quality outputs the
  brief asks for and are deliberately not reused here.
- **Assembling is separated from calibrating.** Assembly touches the network and can take a minute on a
  cold cache; calibration is pure computation. Splitting them means the front end can show the data and
  the algebraic diagnostics immediately, and only then wait for the fit.
- **Every response carries its provenance.** The window, the vintage, the adjustments and the notes travel
  with the numbers, for the same reason the CSV headers do: a figure that travels without its provenance
  gets quoted against the wrong vintage.
- **Failures are returned as results, not as 500s.** An economy that cannot be assembled is an expected
  outcome with a reason worth reading, so it comes back as a normal response with `ok: false` and the
  reason, and the front end shows it.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

import numpy as np

from macrofield import __version__, config as config_module

#: Where the single-page front end lives.
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


class CockpitError(RuntimeError):
    """Raised when the cockpit cannot start."""


def _jsonable(value: Any) -> Any:
    """Convert numpy and non-finite values into something JSON can carry."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    return value


def create_app():
    """Build the FastAPI application.

    Imported lazily inside the function so that the rest of the programme does not depend on FastAPI
    being installed. The CLI catches the ImportError and names the missing packages.
    """
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:  # pragma: no cover - exercised by the CLI path
        raise CockpitError(
            f"the cockpit needs FastAPI: {error}. Install with 'pip install fastapi uvicorn'."
        ) from error

    app = FastAPI(
        title="macrofield cockpit",
        version=__version__,
        description=(
            "Local control surface for the macroeconomic field model. Research and decision support, "
            "not investment advice."
        ),
    )

    # Assembled economies are cached in the process, because assembly hits the network and the front end
    # calls calibrate separately from assemble.
    assembled: dict[str, Any] = {}

    @app.get("/", include_in_schema=False)
    def index():
        page = STATIC_DIRECTORY / "index.html"
        if not page.exists():
            return JSONResponse(
                {"error": f"the cockpit front end is missing at {page}"}, status_code=500
            )
        return FileResponse(page)

    if STATIC_DIRECTORY.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Liveness plus the information a front end needs to render its header."""
        settings = config_module.load()
        return {
            "ok": True,
            "version": __version__,
            "economies": config_module.available_economies(),
            "saturation_band": [
                settings.get("saturation.balanced_band.lower"),
                settings.get("saturation.balanced_band.upper"),
            ],
            # Which optional panels the front end should offer at all. A panel that is switched off is
            # not rendered, rather than rendered and then failing when its endpoint refuses.
            "panels": {
                "stock_gold": bool(settings.get("stock_gold.enabled", default=True)),
            },
            "disclaimer": settings.get("reporting.disclaimer").strip(),
        }

    @app.get("/api/economies")
    def economies() -> dict[str, Any]:
        """Every configured economy and what is distinctive about it."""
        rows = []
        for code in config_module.available_economies():
            settings = config_module.load(code)
            rows.append(
                {
                    "code": code,
                    "name": settings.get("economy.name"),
                    "world_bank": settings.get("economy.world_bank"),
                    "bis": settings.get("economy.bis"),
                    "currency": settings.get("economy.currency"),
                    "stimulus_proxy": settings.get("data.stimulus.proxy"),
                    "notes": settings.get("notes", default=[]),
                }
            )
        return {"ok": True, "economies": rows}

    @app.get("/api/cache")
    def cache_status() -> dict[str, Any]:
        """What the data cache holds, how stale it is, and whether it still matches its digests."""
        from macrofield.data.manifest import Cache

        settings = config_module.load()
        directory = Path(settings.get("data.cache_directory"))
        staleness = int(settings.get("data.staleness_days"))
        cache = Cache(directory)
        keys = sorted(cache._index)  # noqa: SLF001 - the index is what is being inspected
        stale = cache.stale_keys(staleness)
        corrupt = [key for key in keys if not cache.verify(key)]
        return {
            "ok": not corrupt,
            "directory": str(directory),
            "entries": len(keys),
            "staleness_days": staleness,
            "stale": stale,
            "corrupt": corrupt,
            "note": (
                "a corrupt entry means the payload no longer matches the digest recorded when it was "
                "written, so an offline run cannot be guaranteed reproducible"
            ),
        }

    @app.post("/api/assemble/{code}")
    def assemble_economy(code: str, offline: bool = False) -> dict[str, Any]:
        """Assemble one economy and return its series and algebraic diagnostics.

        The diagnostics returned here do not require integrating the system, so they are available even
        when the calibration cannot produce a trajectory.
        """
        from macrofield.pipeline import PipelineError, assemble, build_sources

        if code not in config_module.available_economies():
            return {"ok": False, "error": f"unknown economy {code!r}"}

        try:
            settings = config_module.load(code)
            sources = build_sources(offline=offline, config=settings)
            economy = assemble(code, sources, config=settings)
        except PipelineError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "assemble"}
        except Exception as error:  # noqa: BLE001 - surfaced to the front end rather than a 500
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "assemble",
                "traceback": traceback.format_exc(limit=4),
            }

        assembled[code] = economy
        path = economy.path

        from macrofield.model.phases import classify_period
        from macrofield.model.quantity import unsecured_assets_ratio

        latest = economy.window[1]
        classification = classify_period(
            saturation=float(economy.saturation.values.loc[latest]),
            real_capital=float(path.real_capital[-1]),
            financial_capital=float(path.financial_capital[-1]),
            output=float(path.output[-1]),
        )
        unsecured = unsecured_assets_ratio(path.real_capital, path.financial_capital, path.output)

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "name": economy.name,
                "window": list(economy.window),
                "periods": path.periods,
                "series": {
                    "output": path.output,
                    "real_capital": path.real_capital,
                    "financial_capital": path.financial_capital,
                    "savings_rate": path.savings_rate,
                    "stimulus": path.stimulus_proxy,
                    "saturation": economy.saturation.values.loc[
                        economy.window[0] : economy.window[1]
                    ].reindex(path.periods).to_numpy(dtype=float),
                    "real_over_output": path.real_capital / path.output,
                    "financial_over_output": path.financial_capital / path.output,
                    "unsecured_over_output": unsecured,
                },
                "diagnostics": {
                    "phase": classification.phase.label,
                    "phase_rule": classification.rules_fired[0] if classification.rules_fired else None,
                    "saturation": classification.saturation,
                    "in_balanced_band": classification.in_balanced_band,
                    "real_to_financial": classification.real_to_financial,
                    "distance_to_boundaries": classification.distance_to_boundaries,
                    "saturated_conditions": classification.saturated_conditions,
                },
                "integrity": economy.integrity.as_dict(),
                "plausibility": economy.plausibility.as_dict(),
                "adjustments": economy.adjustments,
                "vintage": economy.vintage,
                "notes": economy.notes,
            }
        )

    @app.post("/api/calibrate/{code}")
    def calibrate_economy(code: str) -> dict[str, Any]:
        """Calibrate a previously assembled economy and judge it on turning points."""
        from macrofield.calibration.fit import calibrate
        from macrofield.calibration.validate import assess_trend

        economy = assembled.get(code)
        if economy is None:
            return {
                "ok": False,
                "error": f"{code!r} has not been assembled in this session. Assemble it first.",
                "stage": "calibrate",
            }

        try:
            result = calibrate(code, economy.path, population_growth=economy.population_growth)
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "calibrate",
                "traceback": traceback.format_exc(limit=4),
            }

        verdicts: dict[str, Any] = {}
        integrated = bool(result.simulated["Y"].size)
        if integrated:
            for name in ("Y", "K_R", "K_I"):
                verdict = assess_trend(
                    name,
                    result.observed[name],
                    result.simulated[name],
                    periods=economy.path.periods,
                )
                verdicts[name] = verdict.as_dict()

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "integrated": integrated,
                "report": result.report(),
                "simulated": {name: values for name, values in result.simulated.items()},
                "observed": {name: values for name, values in result.observed.items()},
                "periods": economy.path.periods,
                "trend": verdicts,
                "note": (
                    None
                    if integrated
                    else (
                        "the fitted parameters do not produce an integrable trajectory, so the "
                        "turning-point assessment is unavailable rather than negative. The algebraic "
                        "diagnostics from assembly are unaffected."
                    )
                ),
            }
        )

    @app.post("/api/export/{code}")
    def export_economy(code: str, directory: str = "output") -> dict[str, Any]:
        """Write the labelled CSV, JSON and prose brief for an assembled economy."""
        from macrofield.calibration.fit import calibrate
        from macrofield.reporting.brief import BriefInputs, render
        from macrofield.reporting.export import ResultBundle, state_frame, write_csv, write_json
        from macrofield.model.phases import classify_period
        from macrofield.model.quantity import unsecured_assets_ratio

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        try:
            result = calibrate(code, economy.path, population_growth=economy.population_growth)
            path = economy.path
            latest = economy.window[1]
            classification = classify_period(
                saturation=float(economy.saturation.values.loc[latest]),
                real_capital=float(path.real_capital[-1]),
                financial_capital=float(path.financial_capital[-1]),
                output=float(path.output[-1]),
            )
            unsecured = float(
                unsecured_assets_ratio(path.real_capital, path.financial_capital, path.output)[-1]
            )
            bundle = ResultBundle(
                economy=code,
                calibration_window=economy.window,
                data_vintage=economy.vintage,
                series={"state": state_frame(path.periods, result.observed, result.simulated)},
                diagnostics={
                    "phase": classification.phase.label,
                    "saturation": classification.saturation,
                    "calibration": result.report(),
                },
                adjustments=economy.adjustments,
                notes=economy.notes,
            )
            target = Path(directory)
            written = [write_json(bundle, target / f"{code}.json")]
            written.extend(write_csv(bundle, target))

            brief = render(
                BriefInputs(
                    economy=economy.name,
                    window=economy.window,
                    phase=classification.phase.label,
                    phase_rule=classification.rules_fired[0]
                    if classification.rules_fired
                    else None,
                    saturation=classification.saturation,
                    unsecured_ratio=unsecured,
                    caveats=economy.notes[:2],
                )
            )
            brief_path = target / f"{code}_brief.txt"
            brief_path.write_text(brief + "\n", encoding="utf-8")
            written.append(brief_path)
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "export",
            }

        return {
            "ok": True,
            "code": code,
            "written": [str(p) for p in written],
            "brief": brief,
        }

    @app.post("/api/derived/{code}")
    def derived_indicators(code: str) -> dict[str, Any]:
        """Every indicator derived from the observed state: price levels, inflation, interest.

        These are functions of the state rather than new data, so they need no extra fetch and a projected
        state yields projected indicators with no additional assumption.
        """
        from macrofield.model.derived import compute, summarise_latest

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        path = economy.path
        try:
            indicators = compute(
                path.periods, path.output, path.real_capital, path.financial_capital
            )
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "code": code, "error": f"{type(error).__name__}: {error}"}

        # The real view, as an overlay on the nominal reading rather than a replacement for it.
        #
        # The deflator is the model's own real-economy price level, from the quantity equation of book
        # chapter 7. That is the basis the programme can always produce, because the deflator is derived
        # from the state rather than fetched. Book chapter 11's own basis is gold, so this is the available
        # basis rather than the preferred one, and it says so.
        #
        # `consumer_prices` DOES reach `AssembledEconomy.series` (pipeline.py builds it into `adjusted` and
        # copies that wholesale), which is precisely why the loop below can read it back off `economy.series`.
        # What it never reaches is a published contract: it is excluded from the model's inner join, so no
        # value is persisted anywhere — only the provenance sentence in `data_vintage`. This handler is the
        # one and only numeric consumer, and it answers from an in-session dict and writes nothing. An
        # earlier version of this comment claimed the series was unwired, which was false and was read as
        # evidence that no CPI existed to use.
        from macrofield.model.derived import Indicator
        from macrofield.model.real_view import RealViewError, both_views

        # OUTPUT GETS NO REAL VIEW ON THIS BASIS, AND THE REASON IS NOT A DETAIL.
        #
        # The deflator is the real-economy price level, which chapter 7 derives as `P_R . H_R = Y` with the
        # transaction frequency held constant. So `P_R` is proportional to `Y`, and deflating `Y` by it is
        # circular: it returns a flat line by construction. On United States data output grows 22.9 times in
        # nominal terms and exactly 1.0 times on this basis. A flat line labelled "output, real" would be
        # read as fifty years without real growth, which is false and is an artefact of the deflator's own
        # definition.
        #
        # The two capital stocks are not in `P_R`'s definition, so deflating them by it is informative: it
        # says how capital grew against the real economy's price level. Output would need an *independent*
        # deflator, CPI or gold, which is the argument for fetching those series.
        state_views: dict[str, Any] = {}
        circular: dict[str, str] = {}
        try:
            deflator = np.asarray(indicators.series(Indicator.REAL_PRICE_LEVEL), dtype=float)

            # The independent deflators, where the data layer assembled them, aligned onto the model's own
            # periods. They matter because the model's own price level is proportional to output and so cannot
            # give output a real view at all; these can.
            #
            # A deflator that does not cover the whole window is refused rather than used for part of it:
            # deflating some periods and not others splices two bases into one series.
            external: dict[str, np.ndarray] = {}
            for key in ("consumer_prices", "gold_price"):
                series = economy.series.get(key)
                if series is None:
                    continue
                aligned = series.values.reindex(path.periods)
                if aligned.notna().all():
                    external[key] = aligned.to_numpy(dtype=float)
                else:
                    circular[key] = (
                        f"{key.replace('_', ' ')} does not cover the whole window, so it is not used as a "
                        f"deflator: {int(aligned.isna().sum())} of {len(aligned)} periods are missing. "
                        f"Deflating part of a series and not the rest would splice two bases together."
                    )

            for name, values in (
                ("output", path.output),
                ("real_capital", path.real_capital),
                ("financial_capital", path.financial_capital),
            ):
                # Output gets no model-deflated view: chapter 7 derives the real-economy price level as
                # proportional to output, so deflating output by it is circular and returns a flat line.
                views = both_views(
                    path.periods,
                    values,
                    model_price_level=None if name == "output" else deflator,
                    consumer_prices=external.get("consumer_prices"),
                    gold=external.get("gold_price"),
                )
                state_views[name] = {basis: view.as_dict() for basis, view in views.items()}

            circular["output"] = (
                "output has no view on the model's own basis. Chapter 7 derives the real-economy price level "
                "as proportional to output, so deflating output by it is circular and returns a flat line. "
                "Its real views use the independent deflators instead."
                if external
                else "output has no real view: the model's own deflator is proportional to output, which is "
                "circular, and no independent deflator was assembled."
            )
        except (RealViewError, Exception) as error:  # noqa: BLE001 - reported, never fatal to the panel
            state_views = {"error": f"{type(error).__name__}: {error}"}

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "derived": indicators.as_dict(),
                "latest": summarise_latest(indicators),
                "state_views": state_views,
                "state_views_circular": circular,
                "state_views_note": (
                    "the nominal reading is primary and the real view is an overlay on it. The deflator is "
                    "the model's own real-economy price level from the quantity equation, not CPI and not "
                    "gold: it is internally consistent, since the price level divided out is the same object "
                    "the model used to generate the series, but it is a model quantity and must not be "
                    "quoted as though it were an observed price index."
                ),
            }
        )

    @app.post("/api/stock-gold/{code}")
    def stock_gold_path(code: str) -> dict[str, Any]:
        """The three-driver gold path, its driver decomposition and the stance it selects.

        Every input is a derivative of the assembled state, so this needs no extra fetch. The weights are
        the configured seeds rather than a per-economy calibration, which is stated in the response: the
        *shape* of the decomposition and which driver dominates are what this endpoint is for, and both
        are robust to the weights in a way the level is not.
        """
        from macrofield.data.loaders import numeric_derivative
        from macrofield.model.stock_gold import (
            DRIVER_KEYS,
            DriverWeights,
            StockGoldError,
            driver_terms,
            evaluate,
        )

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        settings = config_module.load(code)
        if not bool(settings.get("stock_gold.enabled", default=True)):
            return {
                "ok": False,
                "code": code,
                "disabled": True,
                "error": (
                    "the stock-to-gold model is switched off (stock_gold.enabled is false). The module "
                    "and its tests are retained and correct; it is simply not part of the current "
                    "output. Set stock_gold.enabled to true to bring it back."
                ),
            }

        path = economy.path
        periods = np.asarray(path.periods, dtype=float)
        method = settings.get("model.derivatives.method")
        window = int(settings.get("model.derivatives.window_years"))
        polynomial = int(settings.get("model.derivatives.polynomial_order"))

        def d(values, order: int = 1):
            return numeric_derivative(
                np.asarray(values, dtype=float),
                periods,
                method=method,
                window_years=window,
                polynomial_order=polynomial,
                order=order,
            )

        anchor = int(settings.get("stock_gold.calibration_anchor_year"))
        try:
            terms = driver_terms(
                output=path.output,
                output_growth=d(path.output),
                real_capital_growth=d(path.real_capital),
                financial_capital=path.financial_capital,
                financial_capital_growth=d(path.financial_capital),
                financial_capital_acceleration=d(path.financial_capital, order=2),
            )
            # The anchor is configuration and may fall outside a short window, which is a legitimate
            # situation rather than an error: fall back to the last period and say so.
            anchor_note = None
            if anchor not in set(int(p) for p in path.periods):
                anchor_note = (
                    f"the configured calibration anchor {anchor} falls outside the assembled window "
                    f"{economy.window[0]} to {economy.window[1]}, so the path is anchored at "
                    f"{economy.window[1]} instead. The anchor fixes the level only; the change and the "
                    f"driver decomposition are unaffected."
                )
                anchor = int(economy.window[1])
            saturation = (
                economy.saturation.values.loc[economy.window[0] : economy.window[1]]
                .reindex(path.periods)
                .to_numpy(dtype=float)
            )
            result = evaluate(
                periods=path.periods,
                terms=terms,
                weights=DriverWeights.from_config(settings),
                anchor_period=anchor,
                capital_saturation=saturation,
                quantity_equation_validity_ceiling=float(
                    settings.get("stock_gold.quantity_equation_validity_ceiling")
                ),
            )
        except StockGoldError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "stock_gold"}
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "stock_gold",
                "traceback": traceback.format_exc(limit=4),
            }

        notes = list(result.notes)
        if anchor_note:
            notes.insert(0, anchor_note)
        notes.append(
            "the driver weights are the configured seeds, not a per-economy calibration, so the level of "
            "the ratio is indicative. Which driver dominates, and the sign of each contribution, do not "
            "depend on the weights being right."
        )

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "periods": path.periods,
                "gold_over_equity": result.gold_over_equity,
                "stock_to_gold": result.stock_to_gold,
                "ratio_change": result.ratio_change,
                "contributions": {key: result.contributions[key] for key in DRIVER_KEYS},
                "dominant_driver": result.dominant_driver,
                "stance": [stance.value for stance in result.stance],
                "quantity_equation_valid": result.quantity_equation_valid,
                "anchor": {"period": result.anchor_period, "value": result.anchor_value},
                "label": result.label,
                "signs": {
                    key: float(DriverWeights.from_config(settings).signs[key]) for key in DRIVER_KEYS
                },
                "notes": notes,
            }
        )

    @app.post("/api/cycles/{code}")
    def cycle_decomposition(code: str, series: str = "output") -> dict[str, Any]:
        """Decompose the sub-cycles of one series and report the synchronisation window.

        `model/cycles.py` reports a cycle as unidentifiable rather than estimating it when the sample is
        too short, which for the capital cycle at 90 years is every national-accounts series in
        existence. That verdict is returned per cycle rather than suppressed, because a cycle absent from
        a chart reads as absent from the economy.
        """
        from macrofield.model.cycles import (
            CycleError,
            anchored_from_config,
            bands_from_config,
            decompose,
            detect_synchrony,
            spectrum,
        )

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        path = economy.path
        available = {
            "output": path.output,
            "real_capital": path.real_capital,
            "financial_capital": path.financial_capital,
        }
        if series not in available:
            return {
                "ok": False,
                "error": f"unknown series {series!r}, expected one of {sorted(available)}",
            }

        settings = config_module.load(code)
        values = np.asarray(available[series], dtype=float)

        # Decompose the growth rate, not the level. Y, K_R and K_I are close to monotonically
        # increasing, and a band-pass of a trending level returns the trend's own leakage rather than a
        # cycle. This is the same reason section 10 of MODEL_SPEC detects turning points in growth.
        with np.errstate(divide="ignore", invalid="ignore"):
            growth = np.gradient(np.log(np.where(values > 0.0, values, np.nan)))
        if np.any(~np.isfinite(growth)):
            return {
                "ok": False,
                "code": code,
                "error": (
                    f"the {series} series is not strictly positive over the window, so its log growth "
                    f"is undefined and it cannot be band-passed"
                ),
            }

        saturation_axis = (
            economy.saturation.values.loc[economy.window[0] : economy.window[1]]
            .reindex(path.periods)
            .to_numpy(dtype=float)
        )

        try:
            bands = bands_from_config(settings)
            estimates = decompose(growth, bands, sampling_per_year=1.0)
            spectrum_periods, spectrum_power = spectrum(growth, sampling_per_year=1.0)

            # The two long cycles are anchored rather than estimated, and they join the estimated ones
            # so that synchrony is assessed across all four rather than across the two short ones only.
            anchored = anchored_from_config(settings, path.periods, saturation_axis)
            for name, cycle in anchored.items():
                estimates[name] = cycle.estimate

            synchrony = detect_synchrony(
                path.periods,
                estimates,
                phase_tolerance_radians=float(
                    settings.get("cycles.synchrony.phase_tolerance_radians")
                ),
                minimum_cycles_in_phase=int(
                    settings.get("cycles.synchrony.minimum_cycles_in_phase")
                ),
            )
        except CycleError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "cycles"}
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "cycles",
                "traceback": traceback.format_exc(limit=4),
            }

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "series": series,
                "periods": path.periods,
                "growth": growth,
                "spectrum": {"periods": spectrum_periods, "power": spectrum_power},
                "priors": settings.get("cycles.priors"),
                "cycles": {
                    name: {
                        "identifiable": estimate.identifiable,
                        "component": estimate.component,
                        "estimated_period": estimate.estimated_period,
                        "prior_period": estimate.band.prior_period,
                        "band": [estimate.band.low_period, estimate.band.high_period],
                        "amplitude": estimate.amplitude,
                        "phase": estimate.phase,
                        "sample_years": estimate.sample_years,
                        # How this cycle was positioned, which a reader must not have to infer. An
                        # anchored cycle is a supplied structural input; an estimated one came from the
                        # band-pass. They should not read as the same kind of number.
                        "source": "anchored" if name in anchored else "band_pass",
                        "notes": estimate.notes,
                    }
                    for name, estimate in estimates.items()
                },
                "anchored": {
                    name: {
                        "anchored": cycle.anchored,
                        "period_years": cycle.period_years,
                        "reference_year": cycle.reference_year,
                        "years_into_cycle": cycle.years_into_cycle,
                        "years_into_cycle_now": (
                            None
                            if cycle.years_into_cycle is None
                            else float(cycle.years_into_cycle[-1])
                        ),
                        # Signed distance from the latest observed period to the anchor: positive means
                        # the anchor is still ahead. This is the readable form of both anchors. For
                        # innovation it is the years to the 2032 low; for capital it is how far past the
                        # reordering point the economy already is, which goes negative once it is overdue.
                        "years_to_reference": (
                            None
                            if cycle.reference_year is None
                            else float(cycle.reference_year) - float(path.periods[-1])
                        ),
                        "notes": cycle.notes,
                    }
                    for name, cycle in anchored.items()
                },
                "synchrony": {
                    "windows": [
                        {
                            "start_period": window.start_period,
                            "end_period": window.end_period,
                            "cycles_in_phase": window.cycles_in_phase,
                            "mean_absolute_phase_spread": window.mean_absolute_phase_spread,
                        }
                        for window in synchrony.windows
                    ],
                    "current_window": (
                        None
                        if synchrony.current_window is None
                        else {
                            "start_period": synchrony.current_window.start_period,
                            "end_period": synchrony.current_window.end_period,
                            "cycles_in_phase": synchrony.current_window.cycles_in_phase,
                        }
                    ),
                    "excluded_cycles": synchrony.excluded_cycles,
                    "notes": synchrony.notes,
                },
                "note": (
                    "the business and credit cycles are decomposed from the log growth rate rather than "
                    "the level, because a band-pass of a trending level returns the trend rather than a "
                    "cycle. The innovation and capital cycles are anchored from supplied structure, since "
                    "no national-accounts sample is long enough to estimate them. The synchronisation "
                    "window is computed from the four phases together."
                ),
            }
        )

    @app.post("/api/scenario/{code}")
    def scenario(
        code: str,
        horizon: int = 15,
        stimulus: str = "1.0",
        savings: str = "1.0",
        credit_uplift: float | None = None,
        blend_weight: float | None = None,
        taa_half_life_months: float | None = None,
        innovation_trough_year: int | None = None,
        innovation_period_years: float | None = None,
        capital_anchor_saturation: float | None = None,
        assume_capital_crossing: bool = False,
        tilt_base: float | None = None,
        scenario_name: str | None = None,
        recovery_split: float | None = None,
    ) -> dict[str, Any]:
        """The control board: every lever, and everything that follows from them.

        This is one endpoint rather than several because the levers interact. Changing the stimulus path
        changes the trajectory, which changes the phase, which changes the regime weights, which changes the
        merged signal the PCP would consume. Splitting that across endpoints would let a front end show a
        state and a signal computed from different settings.

        Every lever is a query parameter, so a board state is a shareable link and a reproducible run. The
        two time-varying ones take the compact `ControlPath` form, for example
        `stimulus=pulse:1.0>1.5@2027-2030`.

        Provenance travels with every series: `OBSERVED` for the window, `INTEGRATED` where the model ran,
        `EXTRAPOLATED` past where it could, and `ASSUMED` for a capital-cycle anchor solved from a trend.
        """
        from macrofield.calibration.fit import calibrate
        from macrofield.control import ControlError, ControlPath, Provenance
        from macrofield.data.taa import TAAError, decay_forward, dispersion, load_signal
        from macrofield.model.cycles import (
            CycleError,
            anchored_from_config,
            bands_from_config,
            decompose,
            fixed_innovation_cycle,
            superpose,
        )
        from macrofield.model.quantity import unsecured_assets_ratio
        from macrofield.model.regime import RegimeKernels
        from macrofield.model.saa_signal import (
            SAASignalError,
            StateReading,
            merge,
            scenario_weights,
            signal_from_state,
        )
        from macrofield.projection import ProjectionError, project_resiliently

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        settings = config_module.load(code)
        path = economy.path
        observed_periods = np.asarray(path.periods)

        # ---------------------------------------------------------------- controls
        try:
            stimulus_path = ControlPath.from_spec(stimulus, label="stimulus multiplier")
            savings_path = ControlPath.from_spec(savings, label="savings multiplier")
        except ControlError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "controls"}

        band = (
            float(settings.get("saturation.balanced_band.lower")),
            float(settings.get("saturation.balanced_band.upper")),
        )
        blend = float(settings.get("saa.blend_weight") if blend_weight is None else blend_weight)
        half_life = float(
            settings.get("saa.taa.half_life_months")
            if taa_half_life_months is None
            else taa_half_life_months
        )
        split = float(settings.get("saa.recovery_split") if recovery_split is None else recovery_split)

        tilts = dict(settings.get("saa.tilts"))
        if tilt_base is not None:
            tilts["base"] = float(tilt_base)

        # The saturation axis carries a configured credit uplift. Overriding it is a multiplicative
        # rescaling of an already-scaled series, so the factor is divided out rather than reapplied.
        applied_uplift = float(
            (economy.adjustments.get("saturation") or {}).get("level_scale", 1.0)
        )
        uplift = applied_uplift if credit_uplift is None else float(credit_uplift)
        uplift_ratio = uplift / applied_uplift if applied_uplift else 1.0

        saturation = (
            economy.saturation.values.loc[economy.window[0] : economy.window[1]]
            .reindex(path.periods)
            .to_numpy(dtype=float)
        ) * uplift_ratio

        # ---------------------------------------------------------------- trajectory
        #
        # The levers act FORWARD, on the projected parameter paths, not on the observed window. A stimulus
        # programme is something to be done from a future date, so scaling the observed history instead would
        # answer a different question, and a future-dated control would multiply nothing at all because the
        # window ends before it starts. The observed path therefore goes into the calibration unmodified,
        # which also means the fit does not move when a lever moves.
        levered = path

        try:
            calibration = calibrate(code, levered, population_growth=economy.population_growth)
            share = float(saturation[-1] * levered.output[-1] / levered.financial_capital[-1])
            resilient = project_resiliently(
                code,
                levered,
                calibration,
                horizon=int(horizon),
                population_growth=economy.population_growth,
                credit_share_of_financial=share,
                forward_stimulus_control=None if stimulus_path.is_identity else stimulus_path,
                forward_savings_control=None if savings_path.is_identity else savings_path,
            )
        except ProjectionError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "project"}
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "project",
                "traceback": traceback.format_exc(limit=4),
            }

        projection = resilient.result
        projected_periods = np.asarray(projection.periods)
        all_periods = np.concatenate([observed_periods, projected_periods])

        # ---------------------------------------------------------------- cycles
        anchored_settings = dict(settings.get("cycles.anchored", default={}) or {})
        if innovation_trough_year is not None or innovation_period_years is not None:
            innovation = dict(anchored_settings.get("innovation") or {})
            if innovation_trough_year is not None:
                innovation["trough_year"] = int(innovation_trough_year)
            if innovation_period_years is not None:
                innovation["period_years"] = float(innovation_period_years)
            anchored_settings["innovation"] = innovation
        if capital_anchor_saturation is not None:
            capital = dict(anchored_settings.get("capital") or {})
            capital["anchor_saturation"] = float(capital_anchor_saturation)
            anchored_settings["capital"] = capital

        class CycleSettings:
            """A thin overlay so the cycle layer reads the board's values without mutating config."""

            def get(self, key, default=None):
                if key == "cycles.anchored":
                    return anchored_settings
                return settings.get(key, default=default) if default is not None else settings.get(key)

        cycle_config = CycleSettings()

        try:
            with np.errstate(divide="ignore", invalid="ignore"):
                growth = np.gradient(np.log(np.asarray(levered.output, dtype=float)))
            estimates = decompose(growth, bands_from_config(settings), sampling_per_year=1.0)
            anchored = anchored_from_config(
                cycle_config,
                path.periods,
                saturation,
                assume_capital_crossing=bool(assume_capital_crossing),
            )
            for name, cycle in anchored.items():
                estimates[name] = cycle.estimate

            weights = settings.get("cycles.superposition.weights")
            observed_superposition = superpose(path.periods, estimates, weights)

            # Over the projected periods only the two anchored cycles can be evaluated: they are analytic,
            # so they extend to any date, where a band-passed component cannot be extrapolated at all. The
            # forward interference is therefore a statement about the long cycles alone, and it says so.
            forward_anchored = anchored_from_config(
                cycle_config,
                all_periods,
                np.concatenate([saturation, np.asarray(projection.saturation, dtype=float)]),
                assume_capital_crossing=bool(assume_capital_crossing),
            )
            forward_estimates = {
                name: cycle.estimate for name, cycle in forward_anchored.items() if cycle.anchored
            }
            forward_superposition = (
                superpose(all_periods, forward_estimates, weights) if forward_estimates else None
            )
        except CycleError as error:
            return {"ok": False, "code": code, "error": str(error), "stage": "cycles"}

        capital_cycle = anchored.get("capital")
        innovation_cycle = anchored.get("innovation")

        # ---------------------------------------------------------------- the signal, per period
        unsecured = unsecured_assets_ratio(
            levered.real_capital, levered.financial_capital, levered.output
        )
        real_to_financial = np.asarray(levered.real_capital, dtype=float) / np.asarray(
            levered.financial_capital, dtype=float
        )

        full_saturation = np.concatenate([saturation, np.asarray(projection.saturation, dtype=float)])
        full_rf = np.concatenate([real_to_financial, np.asarray(projection.real_to_financial, dtype=float)])
        projected_unsecured = unsecured_assets_ratio(
            projection.real_capital, projection.financial_capital, projection.output
        )
        full_unsecured = np.concatenate([unsecured, projected_unsecured])
        full_unsecured_change = np.concatenate([[np.nan], np.diff(full_unsecured)])

        saturation_trace = resilient.traces.get("saturation")
        first_extrapolated = (
            saturation_trace.first_invented_index() if saturation_trace is not None else None
        )

        # The phase over the whole path, as one latched sequence. The exit from Phase 4 is held until
        # saturation reaches the Foundation level, so it cannot be recovered period by period.
        from macrofield.model.phases import Phase, PhaseThresholds, classify_sequence

        phase_thresholds = PhaseThresholds.from_config(settings)
        full_real = np.concatenate(
            [np.asarray(levered.real_capital, dtype=float), np.asarray(projection.real_capital, dtype=float)]
        )
        full_financial = np.concatenate(
            [
                np.asarray(levered.financial_capital, dtype=float),
                np.asarray(projection.financial_capital, dtype=float),
            ]
        )
        full_output = np.concatenate(
            [np.asarray(levered.output, dtype=float), np.asarray(projection.output, dtype=float)]
        )
        phase_sequence = classify_sequence(
            saturation=[float(v) for v in full_saturation],
            real_capital=[float(v) for v in full_real],
            financial_capital=[float(v) for v in full_financial],
            output=[float(v) for v in full_output],
            thresholds=phase_thresholds,
        )

        kernels = RegimeKernels.from_config(settings) if hasattr(RegimeKernels, "from_config") else None
        minimum_tail = float(settings.get("regime.minimum_tail_probability"))
        tail_bins = int(settings.get("regime.tail_bins"))

        # Where a completed reordering restarts the capital cycle.
        #
        # The phase rule of 2026-07-28 holds an economy in Saturation until saturation reaches the Foundation
        # level. Reaching it means the reordering is *finished*, and a finished reordering starts a new cycle:
        # from that period the count begins again at zero rather than going on past the old cycle's end. Without
        # this the anchor stayed at the last observed crossing and pushed weight to crisis in every period after
        # the correction was already behind the economy.
        from macrofield.model.cycles import reordering_end, years_into_capital_cycle

        capital_into_cycle = None
        restart_index = reordering_end([c.phase.label for c in phase_sequence])
        restart_year = None if restart_index is None else int(all_periods[restart_index])
        if capital_cycle is not None and capital_cycle.anchored:
            capital_into_cycle = years_into_capital_cycle(
                all_periods,
                reference_year=float(capital_cycle.reference_year),
                years_into_cycle_at_anchor=float(
                    anchored_settings.get("capital", {}).get("years_into_cycle_at_anchor", 90.0)
                ),
                period_years=float(capital_cycle.period_years),
                restart_year=restart_year,
            )

        signals: list[dict[str, Any]] = []
        saa_rows: list[np.ndarray] = []
        saa_provenance: list[Provenance] = []

        for index, period in enumerate(all_periods):
            is_projected = index >= observed_periods.size
            provenance = Provenance.OBSERVED
            if is_projected:
                offset = index - observed_periods.size
                provenance = (
                    Provenance.EXTRAPOLATED
                    if first_extrapolated is not None and offset >= first_extrapolated
                    else Provenance.INTEGRATED
                )

            interference = None
            alignment = None
            if not is_projected:
                interference = float(observed_superposition.total[index])
                value = float(observed_superposition.alignment[index])
                alignment = value if np.isfinite(value) else None
            elif forward_superposition is not None:
                interference = float(forward_superposition.total[index])
                value = float(forward_superposition.alignment[index])
                alignment = value if np.isfinite(value) else None

            overdue = None
            if capital_cycle is not None and capital_cycle.anchored:
                overdue = float(capital_into_cycle[index]) - float(capital_cycle.period_years)
                if capital_cycle.assumed:
                    provenance = Provenance.weakest_of([provenance, Provenance.ASSUMED])

            to_trough = None
            if innovation_cycle is not None and innovation_cycle.anchored:
                to_trough = float(innovation_cycle.reference_year) - float(period)

            reading = StateReading(
                period=int(period),
                saturation=float(full_saturation[index]),
                band=band,
                real_to_financial=float(full_rf[index]),
                unsecured_change=(
                    None if not np.isfinite(full_unsecured_change[index])
                    else float(full_unsecured_change[index])
                ),
                interference=interference,
                alignment=alignment,
                capital_years_overdue=overdue,
                innovation_years_to_trough=to_trough,
                provenance=provenance,
            )
            try:
                signal = signal_from_state(
                    reading,
                    kernels=kernels,
                    tilts=tilts,
                    minimum_tail_probability=minimum_tail,
                    tail_bins=tail_bins,
                )
            except SAASignalError as error:
                return {"ok": False, "code": code, "error": str(error), "stage": "signal"}

            saa_rows.append(signal.probabilities)
            saa_provenance.append(provenance)
            latest_reading = reading
            signals.append(
                {
                    "period": int(period),
                    "projected": is_projected,
                    "provenance": provenance.value,
                    "weights": signal.weights,
                    "five_regime": signal.distribution.aggregate_five_regime(),
                    "central_state": signal.distribution.central_state,
                    "tail_probability": signal.distribution.tail_probability,
                    "contributions": signal.contributions,
                }
            )

        saa_matrix = np.vstack(saa_rows)

        # The tilt sweep, on the latest state. Settled 2026-07-28: the coefficients stay a judgement call and
        # the spread is reported rather than one number, so the board quotes a range for the crisis weight and
        # names the tilt the answer rests on.
        from macrofield.model.saa_signal import sweep_tilts

        sweep = None
        try:
            sweep = sweep_tilts(
                latest_reading,
                tilts=tilts,
                scale_range=tuple(settings.get("validation.sensitivity.range")),
                steps=int(settings.get("validation.sensitivity.steps")),
                kernels=kernels,
                minimum_tail_probability=minimum_tail,
                tail_bins=tail_bins,
            ).as_dict()
        except SAASignalError as error:
            sweep = {"error": str(error)}

        # ---------------------------------------------------------------- the scenario target, if asked
        scenario_target = None
        if scenario_name:
            try:
                target = scenario_weights(scenario_name, recovery_split=split)
            except SAASignalError as error:
                return {"ok": False, "code": code, "error": str(error), "stage": "scenario"}
            target_reading = StateReading(
                period=int(all_periods[-1]), saturation=float(full_saturation[-1]),
                band=band, real_to_financial=float(full_rf[-1]),
            )
            target_signal = signal_from_state(
                target_reading, kernels=kernels,
                tilts={"base": 1.0}, minimum_tail_probability=minimum_tail, tail_bins=tail_bins,
            )
            # Spread the scenario's own weights rather than the state's.
            from macrofield.model.regime import SegmentAssessment, build_distribution

            spread = build_distribution(
                [SegmentAssessment(segment=scenario_name, **target)],
                kernels=kernels,
                minimum_tail_probability=minimum_tail,
                tail_bins=tail_bins,
            )
            scenario_target = {
                "name": scenario_name,
                "weights": target,
                "probabilities": [float(v) for v in spread.probabilities],
                "shape": dispersion(np.asarray(spread.probabilities, dtype=float), config=settings),
                "note": (
                    "the scenario's own target distribution, spread onto the axis with the five-regime "
                    "placements. Scenario_SAA.m spreads four weights at different offsets, so this does "
                    "not reproduce that file bin for bin. Hyperinflation maps entirely to Boom because "
                    "the source vector is nominal, which is worth holding in mind before acting on it."
                ),
            }
            del target_signal

        # ---------------------------------------------------------------- the merge
        merged_payload = None
        taa_notes: list[str] = []
        try:
            taa = load_signal()

            # The merge is only defined where both signals exist. The macro window starts decades before
            # the technical signal does, on United States data 1972 against 2006, so the merge covers the
            # overlap and says where it begins. Filling the earlier years with the technical signal's
            # long-run average would put a made-up technical reading against real macro history.
            taa_first_year = taa.months[0][0]
            merge_periods = [int(p) for p in all_periods if int(p) >= taa_first_year]
            if not merge_periods:
                raise TAAError(
                    f"no period overlaps the technical signal, which starts in {taa_first_year}"
                )
            offset = len(all_periods) - len(merge_periods)

            taa_rows, taa_traces = decay_forward(
                taa,
                merge_periods,
                half_life_months=half_life,
                average_window_months=settings.get("saa.taa.average_window_months", default=None),
            )
            merged = merge(
                merge_periods,
                saa_matrix[offset:],
                taa_rows,
                weight=blend,
                saa_provenance=saa_provenance[offset:],
                taa_provenance=[t.provenance for t in taa_traces],
                config=settings,
            )
            merged_payload = merged.as_dict()
            taa_notes = list(taa.notes)
            if offset:
                taa_notes.append(
                    f"the merge covers {merge_periods[0]} onward. The technical signal begins in "
                    f"{taa_first_year} and the macro window begins in {int(all_periods[0])}, so the "
                    f"{offset} earlier periods carry the macro signal alone rather than a fabricated "
                    f"technical one."
                )
        except TAAError as error:
            taa_notes = [f"the technical signal is unavailable, so no merge was produced: {error}"]

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "name": economy.name,
                "controls": {
                    "horizon": int(horizon),
                    "stimulus": stimulus_path.as_dict(),
                    "savings": savings_path.as_dict(),
                    "credit_uplift": uplift,
                    "credit_uplift_configured": applied_uplift,
                    "blend_weight": blend,
                    "taa_half_life_months": half_life,
                    "innovation_trough_year": anchored_settings.get("innovation", {}).get("trough_year"),
                    "innovation_period_years": anchored_settings.get("innovation", {}).get("period_years"),
                    "capital_anchor_saturation": anchored_settings.get("capital", {}).get(
                        "anchor_saturation"
                    ),
                    "assume_capital_crossing": bool(assume_capital_crossing),
                    "tilt_base": tilts["base"],
                    "scenario": scenario_name,
                    "recovery_split": split,
                },
                "window": list(economy.window),
                "periods": [int(p) for p in all_periods],
                "observed_count": int(observed_periods.size),
                "state": {
                    "saturation": full_saturation,
                    "real_to_financial": full_rf,
                    "unsecured_over_output": full_unsecured,
                    # The latched phase per period. The exit from Phase 4 is held until saturation reaches
                    # the Foundation level, so this cannot be recovered by classifying periods separately.
                    "phase": [c.phase.label for c in phase_sequence],
                },
                "band": list(band),
                "projection": {
                    "requested_horizon": resilient.requested_horizon,
                    "integrated_horizon": resilient.integrated_horizon,
                    "extrapolated_periods": resilient.extrapolated_periods,
                    "fully_integrated": resilient.fully_integrated,
                    "phase_at_end": projection.phase_at_end,
                    "transitions": [t.as_dict() for t in projection.transitions],
                    "attempts": resilient.attempts,
                    "label": projection.label,
                    "notes": resilient.notes,
                },
                "superposition": observed_superposition.as_dict(),
                "forward_superposition": (
                    None if forward_superposition is None else forward_superposition.as_dict()
                ),
                "cycles": {
                    name: {
                        "anchored": cycle.anchored,
                        "assumed": cycle.assumed,
                        "reference_year": cycle.reference_year,
                        "period_years": cycle.period_years,
                        "provenance": cycle.provenance.value,
                        "notes": cycle.notes,
                    }
                    for name, cycle in anchored.items()
                },
                "signals": signals,
                "tilt_sweep": sweep,
                "saa": [[float(v) for v in row] for row in saa_matrix],
                "scenario_target": scenario_target,
                "merged": merged_payload,
                "taa_notes": taa_notes,
                "capital_reanchor": (
                    None
                    if restart_year is None
                    else {
                        "restart_year": restart_year,
                        "original_reference_year": (
                            None if capital_cycle is None else capital_cycle.reference_year
                        ),
                        "detail": (
                            f"the projection reaches the Foundation level in {restart_year}, so the "
                            f"reordering is complete and the capital cycle restarts there. From that period "
                            f"the count begins again at zero rather than continuing past the old cycle's "
                            f"end, so the economy reads as early in a new cycle instead of decades late for "
                            f"a correction it has already been through."
                        ),
                    }
                ),
                "notes": [
                    "every lever is a query parameter, so this board state is a shareable link and a "
                    "reproducible run.",
                    "the forward interference uses the two anchored cycles only. They are analytic so they "
                    "extend to any date; a band-passed component cannot be extrapolated, so the business "
                    "and credit cycles are absent past the window.",
                ],
            }
        )

    @app.get("/api/honi")
    def honi_panel(period: int | None = None) -> dict[str, Any]:
        """Score the whole HoNI panel for one year, latest by default.

        This needs no assembled economy: the indicator set comes from the published export and is
        independent of the three-body state. It is therefore a GET and works from a cold start.

        Both readings are returned. `absolute` is the programme's own, a weighted mean on the fixed 1 to 5
        axis, which is comparable across years and is what the four-stage taxonomy requires. `published` is
        the export's own composite, which rescales each year's panel so the healthiest economy is exactly 1
        and the least healthy exactly 5. The second is a ranking rather than a score, and it is returned so
        the difference is visible rather than argued about. See docs/MODEL_SPEC.md section 4.
        """
        from macrofield.data.honi_export import (
            HoNIExportError,
            load_export,
            score_from_export,
            sheet_for_economy,
        )

        settings = config_module.load()
        try:
            export = load_export(settings)
        except HoNIExportError as error:
            return {"ok": False, "error": str(error), "stage": "honi_export"}

        rows: list[dict[str, Any]] = []
        absent: list[dict[str, str]] = []
        for code in config_module.available_economies():
            sheet = sheet_for_economy(settings, code)
            if sheet is None:
                absent.append(
                    {
                        "code": code,
                        "reason": (
                            "the export's panel does not include this economy, and substituting a "
                            "different one would be wrong in a way a reader could not see"
                        ),
                    }
                )
                continue
            try:
                score = score_from_export(settings, code, export=export, period=period)
            except HoNIExportError as error:
                absent.append({"code": code, "reason": str(error)})
                continue

            reading = export.for_sheet(sheet)
            rows.append(
                {
                    "code": code,
                    "sheet": sheet,
                    "period": score.period,
                    "composite": score.composite,
                    "stage": score.stage,
                    "dimensions": {
                        key: {
                            "label": dimension.label,
                            "score": dimension.score,
                            "coverage": dimension.coverage,
                            "missing": dimension.missing_indicators,
                        }
                        for key, dimension in score.dimensions.items()
                    },
                    "indicators": reading.indicator_values(score.period),
                    "published_composite": reading.published_composite.get(score.period),
                    "published_dimensions": {
                        key: series.get(score.period)
                        for key, series in reading.published_dimensions.items()
                    },
                    "notes": score.notes,
                }
            )

        # Rank on the absolute composite, least healthy first, since that is the diagnostic direction.
        ranked = sorted(
            [r for r in rows if r["composite"] is not None], key=lambda r: r["composite"]
        )
        for position, row in enumerate(ranked, start=1):
            row["rank"] = position

        years = sorted({y for e in export.economies.values() for y in e.years})
        return _jsonable(
            {
                "ok": True,
                "period": rows[0]["period"] if rows else period,
                "available_years": years,
                "direction": settings.get("honi.scale.direction"),
                "scale": [settings.get("honi.scale.minimum"), settings.get("honi.scale.maximum")],
                "stages": settings.get("honi.stages"),
                "strategy": settings.get("honi.aggregation.strategy"),
                "economies": rows,
                "absent": absent,
                "source": {
                    "path": str(export.path),
                    "panel_size": len(export.economies),
                },
                "note": (
                    "the composite shown is the absolute reading on the fixed 1 to 5 axis, which is "
                    "comparable across years. The export's own composite is returned beside it and is a "
                    "within-year ranking, not a score."
                ),
            }
        )

    @app.get("/api/unwired")
    def unwired() -> dict[str, Any]:
        """What the model computes that the dashboard cannot chart yet, and precisely why.

        This endpoint exists so that a missing panel is an explicit, readable statement rather than a
        silence a reader has to notice. Both entries are blocked on inputs that do not exist, and neither
        could be filled without inventing the input, which brief section 2 forbids.
        """
        return {
            "ok": True,
            "unwired": [
                {
                    "module": "model/regime.py",
                    "panel": "25-state regime distribution",
                    "blocked_on": (
                        "a per-segment probability vector over the five regimes. The module spreads those "
                        "onto the 25 bins correctly, but nothing assesses the four segments (business "
                        "cycle, investment environment, market behaviour, market stress) from indicators "
                        "yet. Charting it would mean inventing the segment assessments, which would make "
                        "the distribution a picture of the kernels rather than of the economy."
                    ),
                    "computable_now": None,
                },
            ],
        }

    @app.post("/api/project/{code}")
    def project_economy(
        code: str,
        horizon: int = 15,
        stimulus_multiplier: float = 1.0,
        savings_multiplier: float = 1.0,
        credit_uplift: float | None = None,
    ) -> dict[str, Any]:
        """Project the economy forward, with policy levers.

        The levers are the point of this endpoint. `stimulus_multiplier` scales the injection S, which is
        the fiscal and monetary channel; `savings_multiplier` scales p_s. Both are applied to the observed
        path before calibrating, so the projection answers what a different policy stance would imply
        rather than merely rescaling an existing answer.

        A lever of 1.0 leaves the observed path untouched, so the default response is the base case.
        """
        from dataclasses import replace as dataclass_replace

        from macrofield.calibration.fit import calibrate
        from macrofield.model.derived import compute, summarise_latest
        from macrofield.projection import ProjectionError, project

        economy = assembled.get(code)
        if economy is None:
            return {"ok": False, "error": f"{code!r} has not been assembled in this session."}

        path = economy.path
        if stimulus_multiplier != 1.0 or savings_multiplier != 1.0:
            path = dataclass_replace(
                path,
                stimulus_proxy=np.asarray(path.stimulus_proxy, dtype=float) * stimulus_multiplier,
                savings_rate=np.asarray(path.savings_rate, dtype=float) * savings_multiplier,
            )

        try:
            calibration = calibrate(code, path, population_growth=economy.population_growth)
            share = float(
                economy.saturation.values.loc[economy.window[1]]
                * economy.path.output[-1]
                / economy.path.financial_capital[-1]
            )
            if credit_uplift is not None:
                share = share * float(credit_uplift)
            result = project(
                code,
                path,
                calibration,
                horizon=int(horizon),
                population_growth=economy.population_growth,
                credit_share_of_financial=share,
            )
        except ProjectionError as error:
            return {
                "ok": False,
                "code": code,
                "error": str(error),
                "stage": "project",
                "levers": {
                    "stimulus_multiplier": stimulus_multiplier,
                    "savings_multiplier": savings_multiplier,
                    "horizon": horizon,
                },
            }
        except Exception as error:  # noqa: BLE001
            return {
                "ok": False,
                "code": code,
                "error": f"{type(error).__name__}: {error}",
                "stage": "project",
                "traceback": traceback.format_exc(limit=4),
            }

        # Derived indicators over the OBSERVED AND PROJECTED state together, as one series.
        #
        # Computing them over the projected state alone does not work, and the reason is easy to miss:
        # the price levels are indices rebased to the first period of whatever series they are given, so a
        # projection-only computation restarts the index at 100 in the first projected year. Against an
        # observed index that has reached several thousand by then, the projected path plots as a collapse
        # to zero, and the price-divergence ratio restarts at one. Both are artefacts of the rebasing.
        #
        # Computing once over the joined path gives every indicator a single base, so the observed and
        # projected portions are directly comparable and the growth rates are right across the join. The
        # front end splits the result at `projection_start_index` to draw the two portions differently.
        joined_derived = compute(
            np.concatenate([np.asarray(path.periods), np.asarray(result.periods)]),
            np.concatenate([np.asarray(path.output, dtype=float), result.output]),
            np.concatenate([np.asarray(path.real_capital, dtype=float), result.real_capital]),
            np.concatenate(
                [np.asarray(path.financial_capital, dtype=float), result.financial_capital]
            ),
        )
        projection_start_index = int(np.asarray(path.periods).size)

        # Where does the projection start, and does it show?
        #
        # The projection integrates forward from the calibrated model's own final state, not from the last
        # observation, so it carries the calibration's level residual as an offset. That is the right
        # default: continuing the model's trajectory is self-consistent, where rebasing onto the
        # observation would silently discard the fit.
        #
        # It is reported anyway, because observed and projected share one axis and a reader who takes them
        # for one continuous series would misread the offset as a crash in the first period. This says what
        # the reader is looking at. It is NOT a warning that something is wrong. See section 12b of
        # docs/MODEL_SPEC.md, where an earlier reading of this as a defect is retracted.
        observed_saturation = float(
            economy.saturation.values.loc[economy.window[1]]
        )
        first_projected = float(result.saturation[0]) if len(result.saturation) else float("nan")
        join_break = None
        if np.isfinite(first_projected) and observed_saturation:
            relative = first_projected / observed_saturation - 1.0
            if abs(relative) > 0.10:
                join_break = {
                    "last_observed_period": economy.window[1],
                    "last_observed_saturation": observed_saturation,
                    "first_projected_period": result.periods[0],
                    "first_projected_saturation": first_projected,
                    "relative_change": relative,
                    "detail": (
                        f"the projected path starts at {first_projected:.2f} in {result.periods[0]}, "
                        f"against {observed_saturation:.2f} observed in {economy.window[1]}, an offset of "
                        f"{relative:+.1%}. The projection continues the calibrated model's own trajectory "
                        f"rather than the observed series, so it carries the calibration's level residual "
                        f"as a step at the join. Read the projected path's shape and its phase sequence, "
                        f"not the size of the step."
                    ),
                }

        return _jsonable(
            {
                "ok": True,
                "code": code,
                "projection": result.as_dict(),
                "join_break": join_break,
                "derived": joined_derived.as_dict(),
                # Where the projected portion of the derived series begins. Everything before this index
                # is observed, everything from it on is projected.
                "projection_start_index": projection_start_index,
                "latest_derived": summarise_latest(joined_derived),
                "levers": {
                    "stimulus_multiplier": stimulus_multiplier,
                    "savings_multiplier": savings_multiplier,
                    "credit_uplift": credit_uplift,
                    "horizon": horizon,
                },
                "lever_note": (
                    "levers scale the observed path before calibration, so the projection answers what a "
                    "different policy stance implies rather than rescaling an existing answer. A lever of "
                    "1.0 is the base case."
                ),
            }
        )

    @app.get("/api/compare")
    def compare(codes: str = "") -> dict[str, Any]:
        """Compare every economy already assembled in this session, or a named subset."""
        wanted = [c.strip() for c in codes.split(",") if c.strip()] or list(assembled)
        rows = []
        for code in wanted:
            economy = assembled.get(code)
            if economy is None:
                continue
            from macrofield.model.phases import classify_period

            path = economy.path
            latest = economy.window[1]
            classification = classify_period(
                saturation=float(economy.saturation.values.loc[latest]),
                real_capital=float(path.real_capital[-1]),
                financial_capital=float(path.financial_capital[-1]),
                output=float(path.output[-1]),
            )
            rows.append(
                {
                    "code": code,
                    "name": economy.name,
                    "window": list(economy.window),
                    "saturation": classification.saturation,
                    "phase": classification.phase.label,
                    "in_balanced_band": classification.in_balanced_band,
                    "real_to_financial": classification.real_to_financial,
                }
            )
        rows.sort(key=lambda row: row["saturation"], reverse=True)
        return _jsonable(
            {
                "ok": True,
                "economies": rows,
                "note": (
                    "windows differ between economies because the source coverage does, so this is a "
                    "cross-section at each economy's latest period rather than a common date"
                ),
            }
        )

    return app


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the cockpit until interrupted.

    Bound to the loopback interface by default. The cockpit exposes endpoints that write files and fetch
    from the network, so it is not something to put on a routable address without thinking about it.
    """
    import uvicorn

    app = create_app()
    print(f"macrofield cockpit on http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
