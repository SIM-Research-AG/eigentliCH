"""The cockpit server.

Three conventions, inherited from the macro programme's cockpit.

**The server sends data, the browser draws.** Endpoints return JSON traces; the front end renders them
with Plotly loaded from a CDN. No server-side plotting dependency.

**Every response carries its provenance.** The regime vintage, the ReturnSet vintage, the mandate
identity and the binding constraints travel with the numbers, because a weight without its binding
condition is not interpretable.

**Failures come back as results, not as HTTP 500s.** An infeasible mandate, an unpublished Regime or a
mismatched `regime_id` are ordinary answers to a reasonable question, so they return `ok: false` with a
readable reason and the front end shows it. A 500 would make a build-order problem look like a crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcp.config import Config, ConfigError, load_config

STATIC = Path(__file__).resolve().parent / "static"


def create_app(
    config_path: Path | str | None = None,
    regime_dir: Path | str | None = None,
    returnset_path: Path | str | None = None,
    mandates_dir: Path | str | None = None,
):
    from fastapi import FastAPI, Response
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(
        title="Portfolio Creation Program cockpit",
        description="Decision support and research tooling, not investment advice.",
        docs_url="/api/docs",
    )

    def _config() -> Config:
        return load_config(config_path)

    def _paths() -> dict[str, Any]:
        return {
            "regime_dir": regime_dir,
            "returnset_path": returnset_path,
            "mandates_dir": mandates_dir,
        }

    # -- the page ----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        target = STATIC / "index.html"
        if not target.exists():
            return (
                "<h1>Cockpit front end missing</h1>"
                f"<p>Expected {target}. The API is still available under /api.</p>"
            )
        return target.read_text(encoding="utf-8")

    @app.get("/static/{name}")
    def static_asset(name: str) -> Response:
        """Serve a vendored asset beside the page.

        Added 2026-08-02 so the charting library can be local. The page used to load Plotly from
        `cdn.plot.ly`, which meant the cockpit drew blank charts on any machine without internet — and it was
        run on exactly such a machine for a day before anyone noticed, because the tables kept working. A
        research tool that silently loses its charts when offline is worse than one that has none.

        `name` is resolved and checked to be inside `STATIC`, so a crafted path cannot walk out of it. Only
        the two suffixes the page actually uses are served: a static route that will hand over anything is a
        file-disclosure bug waiting for someone to drop a stray file in the directory.
        """
        if Path(name).suffix.lower() not in {".js", ".css"}:
            return Response(status_code=404)
        target = (STATIC / name).resolve()
        if not target.is_file() or STATIC.resolve() not in target.parents:
            return Response(status_code=404)
        media = "text/javascript" if target.suffix.lower() == ".js" else "text/css"
        return Response(
            content=target.read_bytes(),
            media_type=media,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # -- metadata ----------------------------------------------------------

    @app.get("/api/context")
    def context() -> JSONResponse:
        """What the run panel needs to offer, and what this programme is."""
        from pcp import __version__
        from pcp.ingest import list_mandates

        try:
            config = _config()
        except ConfigError as error:
            return JSONResponse({"ok": False, "reason": str(error), "stage": "config"})

        mandates = [m for m in list_mandates(directory=mandates_dir, config=config) if m.get("ok")]
        scopes = [s for s in dict(config.get("country_weights.presets")) if s != "equal"]
        published = _published_scopes(config, regime_dir)

        return JSONResponse(
            {
                "ok": True,
                "engine_version": config.engine_version,
                "version": __version__,
                "disclaimer": config.disclaimer,
                "mandates": [
                    {
                        "id": Path(m["path"]).stem,
                        "client": m["client"],
                        "mandate": m["mandate"],
                        "market": m["market"],
                        "currency": m["currency"],
                        "universe_size": m["universe_size"],
                    }
                    for m in mandates
                ],
                "market_scopes": scopes,
                "published_regimes": published,
                "speeds": sorted(dict(config.get("solver.speeds"))),
                "optimisers": [
                    {"id": "curve", "label": "curve fit (model of record)"},
                    {"id": "mv", "label": "mean-variance (comparison only)"},
                ],
                "max_backtest_months": int(config.get("run.max_backtest_months")),
                "vocabularies": {
                    "roles": list(config.vocabularies.roles.labels),
                    "scenarios": list(config.vocabularies.scenarios.labels),
                },
            }
        )

    # -- the run -----------------------------------------------------------

    @app.post("/api/run")
    def api_run(
        mandate: str,
        market: str | None = None,
        speed: str | None = None,
        optimiser: str = "curve",
        backtest_months: int = 0,
    ) -> JSONResponse:
        """Run the optimiser and return everything the seven views need.

        Calls the same `prepare` and `run` the CLI calls, so nothing here can diverge from a written
        result.
        """
        from pcp.pipeline import PipelineError, diagnostics as build_diagnostics, prepare, run
        from pcp.reporting import result_payload

        try:
            config = _config()
        except ConfigError as error:
            return JSONResponse({"ok": False, "reason": str(error), "stage": "config"})

        try:
            inputs = prepare(
                mandate,
                config,
                market=market,
                regime_dir=regime_dir,
                returnset_path=returnset_path,
                mandates_dir=mandates_dir,
            )
        except PipelineError as error:
            # A build-order problem, not a crash. Returned so the front end can show the fix.
            return JSONResponse(
                {
                    "ok": False,
                    "reason": str(error),
                    "stage": "inputs",
                    "mandate": mandate,
                    "market": market,
                }
            )

        try:
            result = run(
                mandate,
                config,
                market=market,
                speed=speed,
                optimiser=optimiser,
                backtest_months=int(backtest_months),
                inputs=inputs,
            )
        except (PipelineError, ValueError) as error:
            return JSONResponse(
                {
                    "ok": False,
                    "reason": str(error),
                    "stage": "solve",
                    "mandate": mandate,
                    "feasibility_notes": list(inputs.feasibility_notes),
                }
            )

        diagnostics = build_diagnostics(inputs, result, config)
        payload = result_payload(result, config, diagnostics)
        payload["ok"] = True
        # `conditions_met: no` is a result, not an error: the numbers exist and are reportable, but the
        # front end must show the warning above them.
        payload["feasible"] = result.ok
        payload["views"] = _views(inputs, result, config, diagnostics)
        return JSONResponse(payload)

    @app.get("/api/mandate/{name}")
    def api_mandate(name: str) -> JSONResponse:
        """One mandate's target curve and bounds, so the panel can show what is being asked for."""
        from pcp.ingest import load_mandate

        try:
            config = _config()
            loaded = load_mandate(name, directory=mandates_dir, config=config)
        except Exception as error:
            return JSONResponse({"ok": False, "reason": str(error)})

        return JSONResponse(
            {
                "ok": True,
                "client": loaded.client,
                "mandate": loaded.name,
                "market": loaded.market,
                "currency": loaded.currency,
                "benchmark": loaded.benchmark,
                "max_single_position": loaded.max_single_position,
                "esg_min": loaded.esg_min,
                "horizon_years": loaded.horizon_years,
                "target_curve": [float(v) for v in loaded.target_curve],
                "universe": list(loaded.universe),
                "fixed_allocations": {str(k): v for k, v in loaded.fixed_allocations.items()},
                "bounds": {
                    dimension: {
                        label: {"lower": b.lower, "upper": b.upper}
                        for label, b in categories.items()
                    }
                    for dimension, categories in loaded.bounds.items()
                },
            }
        )

    @app.post("/api/export")
    def api_export(
        mandate: str,
        market: str | None = None,
        speed: str | None = None,
        optimiser: str = "curve",
        backtest_months: int = 0,
    ) -> JSONResponse:
        """Write the artefact set through the same boundary the CLI writes through."""
        from pcp.pipeline import PipelineError, diagnostics as build_diagnostics, prepare, run
        from pcp.reporting import export_result

        try:
            config = _config()
            inputs = prepare(
                mandate, config, market=market, regime_dir=regime_dir,
                returnset_path=returnset_path, mandates_dir=mandates_dir,
            )
            result = run(
                mandate, config, market=market, speed=speed, optimiser=optimiser,
                backtest_months=int(backtest_months), inputs=inputs,
            )
            written = export_result(
                result, config, diagnostics=build_diagnostics(inputs, result, config)
            )
        except (PipelineError, ConfigError, ValueError) as error:
            return JSONResponse({"ok": False, "reason": str(error)})

        return JSONResponse(
            {"ok": True, "written": {k: str(v) for k, v in written.items()}}
        )

    return app


def _published_scopes(config: Config, directory: Path | str | None) -> list[str]:
    from pcp.ingest.regime import _default_directory

    root = Path(directory) if directory is not None else _default_directory(config)
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.json"))


def _views(inputs, result, config: Config, diagnostics: dict[str, Any]) -> dict[str, Any]:
    """The traces the seven views draw, assembled once so the browser does no arithmetic."""
    import numpy as np

    from pcp.model.pfmap import for_display

    current = result.current
    scenarios = list(config.vocabularies.scenarios.labels)
    roles = list(config.vocabularies.roles.labels)

    instruments = sorted(
        diagnostics["instruments"], key=lambda row: -float(row["weight"])
    )
    held = [row for row in instruments if float(row["weight"]) >= 5e-5]

    def grouped(key: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in instruments:
            out[str(row[key])] = out.get(str(row[key]), 0.0) + float(row["weight"])
        return {k: v for k, v in sorted(out.items(), key=lambda kv: -kv[1]) if v > 1e-12}

    return {
        # 2. Allocation
        "allocation": {
            "labels": [row["name"] for row in held],
            "weights": [float(row["weight"]) for row in held],
            "roles": [row["role"] for row in held],
            "omitted": len(instruments) - len(held),
            "by_role": grouped("role"),
            "by_region": grouped("region_geo"),
            "by_currency": grouped("currency"),
            "by_asset_class": grouped("asset_class"),
        },
        # 3. Portfolio map, boom-first for the axis only
        "portfolio_map": {
            "z": for_display(current.portfolio_map).tolist(),
            "x": list(reversed(scenarios)),
            "y": roles,
            "note": (
                "displayed boom-first to match the reference figure; the underlying matrix is ordered "
                "crisis-low to boom-high"
            ),
        },
        # 4. Return curve fit
        "curve_fit": {
            "states": list(range(1, 26)),
            "target": [float(v) for v in np.asarray(inputs.mandate.target_curve)],
            "achieved": [float(v) for v in np.asarray(current.return_dist_final)],
            "shortfall": diagnostics["shortfall_by_state"],
            "note": (
                "the achieved profile is the portfolio's own per-state return. The objective compares the "
                "regime-scaled contribution of each instrument against the target, so the two can differ "
                "while the fit is optimal for this regime."
            ),
        },
        # 5. Regime tilt
        "regime": {
            "states": list(range(1, 26)),
            "weights": [float(v) for v in np.asarray(current.regime)],
            "regime_id": result.regime_id,
            "crisis_tail": result.crisis_tail,
            "contributors": diagnostics["regime_contributors"],
            "window": diagnostics["regime_window"],
        },
        # 6. Backtest
        "backtest": (
            {
                "periods": [a.period for a in result.allocations],
                "labels": [row["name"] for row in instruments],
                "series": [
                    [float(a.weights[list(a.bb_ids).index(int(row["bb_id"]))]) for a in result.allocations]
                    for row in instruments
                ],
                "conditions_met": [a.conditions_met for a in result.allocations],
                "objective": [a.objective_value for a in result.allocations],
                "label": "model-derived",
            }
            if len(result.allocations) > 1
            else None
        ),
        # 7. Constraints and feasibility
        "constraints": {
            "realised": diagnostics["realised_exposures"],
            "bounds": {
                dimension: {
                    label: {"lower": b.lower, "upper": b.upper}
                    for label, b in categories.items()
                }
                for dimension, categories in inputs.mandate.bounds.items()
            },
            "binding": [
                {
                    "dimension": b.dimension,
                    "category": b.category,
                    "side": b.side,
                    "bound": b.bound,
                    "realised": b.realised,
                }
                for b in current.binding
            ],
            "conditions_met": current.conditions_met,
            "feasibility_notes": list(inputs.feasibility_notes),
            "rows": inputs.system.n_rows,
        },
    }


def serve(
    host: str = "127.0.0.1",
    port: int = 8010,
    config_path: Path | str | None = None,
    regime_dir: Path | str | None = None,
    returnset_path: Path | str | None = None,
    mandates_dir: Path | str | None = None,
) -> None:
    import uvicorn

    app = create_app(
        config_path=config_path,
        regime_dir=regime_dir,
        returnset_path=returnset_path,
        mandates_dir=mandates_dir,
    )
    print(f"cockpit on http://{host}:{port}   (decision support, not investment advice)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
