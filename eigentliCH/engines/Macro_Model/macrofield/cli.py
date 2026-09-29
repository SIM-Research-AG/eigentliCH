"""Command-line entry points.

Brief section 7 asks for these commands:

    macrofield calibrate --economy us
    macrofield report --economy us
    macrofield compare us cn jp de
    macrofield cycles --economy us

Plus a few the brief implies rather than names: `data` for refreshing and inspecting the cache, `economies`
for listing what is configured, and `cockpit` for the interactive dashboard.

Every command that writes results writes through `macrofield.reporting`, so the calibration window, the
data vintage, the projection label and the disclaimer are attached at the write boundary rather than
depending on each command remembering them.

Exit codes: 0 on success, 1 on a handled failure (an unavailable input, a failed integrity check), and 2
on a usage error. A run that needs an unavailable input fails loudly with exit 1, per brief section 2,
rather than proceeding on a guess.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from macrofield import __version__, config as config_module

#: Exit codes.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

#: Default directory for written results.
DEFAULT_OUTPUT = Path("output")


@dataclass
class CommandResult:
    """What a command produced, so the entry point can report it uniformly."""

    exit_code: int
    message: str
    payload: dict[str, Any] | None = None


def build_parser() -> argparse.ArgumentParser:
    """Assemble the argument parser."""
    parser = argparse.ArgumentParser(
        prog="macrofield",
        description=(
            "Calibratable macroeconomic field model. Research and decision support, not investment "
            "advice."
        ),
    )
    parser.add_argument("--version", action="version", version=f"macrofield {__version__}")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run from the cached, manifested data only, with no network access",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"directory for written results (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the result as JSON rather than as prose",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    economies = subparsers.add_parser(
        "economies", help="list the configured economies and what is distinctive about each"
    )
    economies.set_defaults(handler=command_economies)

    calibrate = subparsers.add_parser(
        "calibrate", help="calibrate one economy and report the fit and identifiability"
    )
    calibrate.add_argument("--economy", required=True, help="economy code, for example us")
    calibrate.add_argument(
        "--window-start", type=int, default=None, help="override the first calibration period"
    )
    calibrate.add_argument(
        "--window-end", type=int, default=None, help="override the last calibration period"
    )
    calibrate.set_defaults(handler=command_calibrate)

    report = subparsers.add_parser(
        "report", help="produce the full per-economy report, charts, exports and brief"
    )
    report.add_argument("--economy", required=True)
    report.add_argument(
        "--no-charts", action="store_true", help="skip the figures and write only the data"
    )
    report.set_defaults(handler=command_report)

    compare = subparsers.add_parser(
        "compare", help="compare several economies on the saturation axis and HoNI"
    )
    compare.add_argument("economies", nargs="+", help="two or more economy codes")
    compare.add_argument(
        "--include-aggregates",
        action="store_true",
        help=(
            "include aggregate economies such as the euro area alongside their members. Off by default "
            "because a ranking containing both double counts them."
        ),
    )
    compare.set_defaults(handler=command_compare)

    cycles = subparsers.add_parser(
        "cycles", help="decompose the sub-cycles and report the synchronisation window"
    )
    cycles.add_argument("--economy", required=True)
    cycles.set_defaults(handler=command_cycles)

    data = subparsers.add_parser("data", help="inspect or refresh the data cache")
    data.add_argument(
        "--refresh", action="store_true", help="re-fetch every series, ignoring the cache"
    )
    data.add_argument(
        "--check-stale",
        action="store_true",
        help="report cached pulls older than the configured staleness threshold",
    )
    data.set_defaults(handler=command_data)

    regime = subparsers.add_parser(
        "regime",
        help="publish the monthly Regime timeline contract that downstream programmes consume",
    )
    regime.add_argument(
        "economies",
        nargs="+",
        help="one or more economy codes, or 'all' for every configured economy",
    )
    regime.add_argument(
        "--blend-weight",
        type=float,
        default=None,
        help=(
            "weight on the macro half of the signal, 0 to 1. Defaults to the configured "
            "saa.blend_weight."
        ),
    )
    regime.add_argument(
        "--scope",
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "also publish a blended market scope (Americas, Europe, Asia, Sino, Global), built from the "
            "economies it weights. Repeatable, or 'all' for every configured scope. A downstream "
            "ReturnSet must be estimated against the same scope the optimiser reads, so a blended "
            "mandate needs its scope published here."
        ),
    )
    regime.set_defaults(handler=command_regime)

    cockpit = subparsers.add_parser(
        "cockpit", help="serve the interactive dashboard on a local port"
    )
    cockpit.add_argument("--port", type=int, default=8765)
    cockpit.add_argument("--host", default="127.0.0.1")
    cockpit.set_defaults(handler=command_cockpit)

    return parser


def _resolve_economy(code: str) -> config_module.Config:
    """Load an economy's configuration, with a useful error when the code is unknown.

    Raises:
        SystemExit: With the usage exit code, listing what is available, because a typo in an economy code
            is the single most likely usage error here.
    """
    available = config_module.available_economies()
    if code not in available:
        raise SystemExit(
            f"unknown economy {code!r}. Configured economies: {', '.join(available) or 'none'}. "
            f"Adding one is a configuration change, not a code change: create "
            f"macrofield/economies/{code}.yaml."
        )
    return config_module.load(code)


def command_economies(args: argparse.Namespace) -> CommandResult:
    """List the configured economies."""
    rows: list[dict[str, Any]] = []
    for code in config_module.available_economies():
        config = config_module.load(code)
        rows.append(
            {
                "code": code,
                "name": config.get("economy.name"),
                "world_bank": config.get("economy.world_bank"),
                "bis": config.get("economy.bis"),
                "currency": config.get("economy.currency"),
                "stimulus_proxy": config.get("data.stimulus.proxy"),
                "financial_capital_measure": config.get("data.financial_capital.primary"),
            }
        )

    lines = [f"{len(rows)} configured economies:", ""]
    lines.append(f"{'code':<10}{'name':<18}{'WB':<6}{'BIS':<5}{'ccy':<5}stimulus proxy")
    for row in rows:
        lines.append(
            f"{row['code']:<10}{str(row['name'])[:17]:<18}{str(row['world_bank']):<6}"
            f"{str(row['bis']):<5}{str(row['currency']):<5}{row['stimulus_proxy']}"
        )
    return CommandResult(EXIT_OK, "\n".join(lines), {"economies": rows})


def _assemble(code: str, args: argparse.Namespace):
    """Assemble one economy, converting a pipeline failure into a clean command failure."""
    from macrofield.pipeline import PipelineError, assemble, build_sources

    config = _resolve_economy(code)
    sources = build_sources(offline=args.offline, config=config)
    try:
        return assemble(
            code,
            sources,
            config=config,
            window_start=getattr(args, "window_start", None),
            window_end=getattr(args, "window_end", None),
        )
    except PipelineError as error:
        raise SystemExit(str(error)) from error


def _diagnose(economy) -> dict[str, Any]:
    """Compute the diagnostics that do not depend on integrating the system.

    Separated deliberately. The phase, the saturation reading and the unsecured-asset gap are all
    algebraic functions of the observed state, so they are available whether or not the calibrated
    trajectory integrates. The turning-point assessment is not, and reporting the two together without
    distinguishing them would let an unavailable result read as a null one.
    """
    from macrofield.model.phases import PhaseThresholds, classify_period
    from macrofield.model.quantity import unsecured_assets_ratio

    path = economy.path
    latest = economy.window[1]
    saturation = float(economy.saturation.values.loc[latest])
    # Thresholds from configuration, not the dataclass defaults. Leaving them to the defaults silently
    # ignored the configured Phase 3 ceiling.
    classification = classify_period(
        saturation=saturation,
        real_capital=float(path.real_capital[-1]),
        financial_capital=float(path.financial_capital[-1]),
        output=float(path.output[-1]),
        thresholds=PhaseThresholds.from_config(config_module.load()),
    )
    unsecured = unsecured_assets_ratio(path.real_capital, path.financial_capital, path.output)
    return {
        "phase": classification.phase.label,
        "phase_rule": classification.rules_fired[0] if classification.rules_fired else None,
        "saturation": saturation,
        "in_balanced_band": classification.in_balanced_band,
        "real_capital_over_output": float(path.real_capital[-1] / path.output[-1]),
        "financial_capital_over_output": float(path.financial_capital[-1] / path.output[-1]),
        "real_to_financial": classification.real_to_financial,
        "unsecured_assets_over_output": float(unsecured[-1]),
        "distance_to_boundaries": classification.distance_to_boundaries,
        "saturated_conditions": classification.saturated_conditions,
    }


def command_calibrate(args: argparse.Namespace) -> CommandResult:
    """Assemble one economy, calibrate it, and report the fit and identifiability."""
    from macrofield.calibration.fit import calibrate as run_calibration

    economy = _assemble(args.economy, args)
    diagnostics = _diagnose(economy)
    result = run_calibration(args.economy, economy.path)

    lines = [
        f"{economy.name}: calibrated over {economy.window[0]} to {economy.window[1]} "
        f"({economy.path.length} periods)",
        "",
        f"  phase                    {diagnostics['phase']}",
        f"  selected by              {diagnostics['phase_rule']}",
        f"  credit saturation        {diagnostics['saturation']:.3f} "
        f"({'inside' if diagnostics['in_balanced_band'] else 'outside'} the balanced band)",
        f"  real capital over output {diagnostics['real_capital_over_output']:.2f}",
        f"  financial over output    {diagnostics['financial_capital_over_output']:.2f}",
        f"  K_R over K_I             {diagnostics['real_to_financial']:.3f}",
        f"  unsecured over output    {diagnostics['unsecured_assets_over_output']:.2f}",
        "",
        f"  optimiser converged      {result.converged}",
        f"  integration accuracy     {result.integration_accuracy}",
        f"  level residual           "
        + ("not available, the fitted path does not integrate" if result.fit_quality == float("inf") else f"{result.fit_quality:.2f}"),
        f"  weakly identified        {', '.join(result.weakly_identified) or 'none'}",
        "",
        f"  integrity                {'passed' if economy.integrity.ok else 'FAILED'}",
        f"  plausibility warnings    {len(economy.plausibility.warnings)}",
    ]

    if not result.simulated["Y"].size:
        lines.extend(
            [
                "",
                "  The turning-point assessment needs a simulated path and none was produced, so it is "
                "unavailable rather than negative. The diagnostics above are algebraic functions of the "
                "observed state and do not depend on integrating the system, so they stand.",
            ]
        )
    for note in result.notes:
        lines.append(f"  note: {note}")
    for note in economy.notes:
        lines.append(f"  data: {note}")

    return CommandResult(
        EXIT_OK,
        "\n".join(lines),
        {"diagnostics": diagnostics, "calibration": result.report(), "notes": economy.notes},
    )


def command_report(args: argparse.Namespace) -> CommandResult:
    """Produce the full per-economy report: exports, charts and the prose brief."""
    from macrofield.calibration.fit import calibrate as run_calibration
    from macrofield.reporting.brief import BriefInputs, render
    from macrofield.reporting.export import ResultBundle, state_frame, write_csv, write_json

    economy = _assemble(args.economy, args)
    diagnostics = _diagnose(economy)
    result = run_calibration(args.economy, economy.path)

    bundle = ResultBundle(
        economy=args.economy,
        calibration_window=economy.window,
        data_vintage=economy.vintage,
        series={
            "state": state_frame(economy.path.periods, result.observed, result.simulated),
        },
        diagnostics={**diagnostics, "calibration": result.report()},
        adjustments=economy.adjustments,
        notes=economy.notes,
    )

    directory = Path(args.output)
    written = [write_json(bundle, directory / f"{args.economy}.json")]
    written.extend(write_csv(bundle, directory))

    brief_text = render(
        BriefInputs(
            economy=economy.name,
            window=economy.window,
            phase=diagnostics["phase"],
            phase_rule=diagnostics["phase_rule"],
            saturation=diagnostics["saturation"],
            unsecured_ratio=diagnostics["unsecured_assets_over_output"],
            adjustments_applied=any(
                not entry.get("level_scale", 1.0) == 1.0 for entry in economy.adjustments.values()
            ),
            caveats=economy.notes[:2],
        )
    )
    brief_path = directory / f"{args.economy}_brief.txt"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(brief_text + "\n", encoding="utf-8")
    written.append(brief_path)

    if not args.no_charts:
        from macrofield.reporting.charts import ChartContext, phase_timeline_chart, save

        context = ChartContext(
            economy=economy.name,
            calibration_window=economy.window,
            data_vintage=", ".join(sorted(set(economy.vintage.values())))[:90],
        )
        saturation_path = economy.saturation.values.loc[economy.window[0] : economy.window[1]].dropna()
        figure = phase_timeline_chart(
            context,
            list(saturation_path.index),
            saturation_path.to_numpy(dtype=float),
            [0] * len(saturation_path),
        )
        written.append(save(figure, directory / f"{args.economy}_phase.png"))

    lines = [f"{economy.name}: wrote {len(written)} artefact(s) to {directory}"]
    lines.extend(f"  {path.name}" for path in written)
    lines.extend(["", brief_text])
    return CommandResult(EXIT_OK, "\n".join(lines), {"written": [str(p) for p in written]})


def command_compare(args: argparse.Namespace) -> CommandResult:
    """Compare several economies."""
    if len(args.economies) < 2:
        return CommandResult(EXIT_USAGE, "compare needs at least two economies")

    codes = list(args.economies)
    aggregates = [code for code in codes if code == "eurozone"]
    if aggregates and not args.include_aggregates:
        members = [code for code in codes if code in ("de", "fr")]
        if members:
            return CommandResult(
                EXIT_USAGE,
                (
                    f"the comparison includes the euro area aggregate alongside its members "
                    f"({', '.join(members)}), which double counts them. Drop one, or pass "
                    f"--include-aggregates to override deliberately."
                ),
            )

    from macrofield.pipeline import PipelineError, cross_section

    economies = []
    failures: list[str] = []
    for code in codes:
        try:
            economies.append(_assemble(code, args))
        except SystemExit as error:
            failures.append(f"{code}: {error}")

    if not economies:
        return CommandResult(EXIT_FAILED, "no economy could be assembled:\n" + "\n".join(failures))

    try:
        section = cross_section(economies, exclude_aggregates=not args.include_aggregates)
    except PipelineError as error:
        return CommandResult(EXIT_FAILED, str(error))

    lines = [
        f"Cross-section of {len(section.rows)} economies at {section.year}, ordered by credit saturation.",
        "Balanced band 2.50 to 3.50, derived from the bifurcation analysis.",
        "",
        f"{'economy':<18}{'sat':>7}{'band':>9}{'K_R/K_I':>9}{'stimulus':>10}  phase",
    ]
    for row in section.rows:
        position = (
            "above" if row["saturation"] > 3.5 else "inside" if row["saturation"] >= 2.5 else "below"
        )
        lines.append(
            f"{str(row['name'])[:17]:<18}"
            f"{row['saturation']:>7.2f}{position:>9}"
            f"{row['real_to_financial']:>9.2f}"
            f"{row['stimulus_over_output'] * 100:>9.1f}%"
            f"  {row['phase']}"
        )

    if section.excluded:
        lines.extend(["", "excluded:"])
        lines.extend(f"  {reason}" for reason in section.excluded)
    if failures:
        lines.extend(["", "could not be assembled:"])
        lines.extend(f"  {failure}" for failure in failures)

    lines.append("")
    lines.extend(f"Note: {note}" for note in section.notes)
    return CommandResult(
        EXIT_OK,
        "\n".join(lines),
        {"year": section.year, "economies": section.rows, "failures": failures},
    )


def command_cycles(args: argparse.Namespace) -> CommandResult:
    """Decompose the sub-cycles for one economy."""
    config = _resolve_economy(args.economy)
    priors = config.get("cycles.priors")
    wanted = config.get("cycles.decompose")

    lines = [
        f"{config.get('economy.name')}: cycles configured for decomposition",
        "",
        f"{'cycle':<14}{'prior period':>14}{'sample needed':>16}",
    ]
    for name in wanted:
        if name == "innovation":
            low, high = priors["innovation_observed_band_years"]
            period = (low + high) / 2.0
            shown = f"{low:g} to {high:g}y"
        else:
            period = float(priors[f"{name}_years"])
            shown = f"{period:g}y"
        lines.append(f"{name:<14}{shown:>14}{f'{2 * period:g} years':>16}")

    lines.extend(
        [
            "",
            "A cycle needs a sample spanning about two of its periods to be identifiable. The capital "
            "cycle at 90 years therefore needs roughly two centuries of annual data, which no national "
            "accounts series provides, so it will be reported as unidentifiable rather than estimated.",
            "",
            "Decomposition itself is not yet wired end to end and needs the pipeline. The module is "
            "complete and tested: model/cycles.py extracts the bands, estimates the periods, and detects "
            "the synchronisation window from the estimated phases.",
        ]
    )
    return CommandResult(EXIT_FAILED, "\n".join(lines), {"priors": priors, "decompose": wanted})


def command_data(args: argparse.Namespace) -> CommandResult:
    """Inspect or refresh the data cache."""
    from macrofield.data.manifest import Cache

    config = config_module.load()
    cache_directory = Path(config.get("data.cache_directory"))
    staleness = int(config.get("data.staleness_days"))
    cache = Cache(cache_directory, offline=args.offline)

    if args.refresh:
        return CommandResult(
            EXIT_USAGE,
            (
                "refresh needs the pipeline to know which series to fetch. Until then, a cold cache is "
                "populated by the first live run of a command that loads data."
            ),
        )

    entries = sorted(cache._index)  # noqa: SLF001 - the index is the thing being inspected
    stale = cache.stale_keys(staleness)
    corrupt = [key for key in entries if not cache.verify(key)]

    lines = [
        f"cache: {cache_directory}",
        f"entries: {len(entries)}",
        f"stale beyond {staleness} days: {len(stale)}",
        f"failing their recorded digest: {len(corrupt)}",
    ]
    if args.check_stale and stale:
        lines.append("")
        lines.append("stale entries:")
        lines.extend(f"  {key}" for key in stale)
    if corrupt:
        lines.append("")
        lines.append(
            "these payloads no longer match the digest recorded when they were written, so an offline "
            "run cannot be guaranteed reproducible. Delete them and re-fetch:"
        )
        lines.extend(f"  {key}" for key in corrupt)

    exit_code = EXIT_FAILED if corrupt else EXIT_OK
    return CommandResult(
        exit_code,
        "\n".join(lines),
        {"entries": len(entries), "stale": stale, "corrupt": corrupt},
    )


def command_regime(args: argparse.Namespace) -> CommandResult:
    """Publish the monthly Regime timeline contract for one or more economies.

    This is the boundary at which the Fund Map and the Portfolio Creation Program are allowed to depend
    on this programme. What is written carries the full 25-length distribution per month, the modal state
    path alongside it, and a `regime_id` that downstream artefacts stamp so a consumer can refuse to mix
    vintages.
    """
    from macrofield.contracts.regime_timeline import (
        RegimeTimelineError,
        build_timeline,
        write_timeline,
    )
    from macrofield.data.sources import SourceError
    from macrofield.data.taa import TAAError, load_signal
    from macrofield.pipeline import PipelineError

    codes = list(args.economies)
    if len(codes) == 1 and codes[0] == "all":
        codes = config_module.available_economies()

    if args.blend_weight is not None and not 0.0 <= float(args.blend_weight) <= 1.0:
        return CommandResult(
            EXIT_USAGE, f"--blend-weight must lie in [0, 1], got {args.blend_weight}"
        )

    try:
        taa = load_signal()
    except TAAError as error:
        return CommandResult(
            EXIT_FAILED,
            (
                f"the technical half of the signal is unavailable: {error}. The Regime is the blend of "
                f"both halves, so it is not published from the macro half alone."
            ),
        )

    directory = Path(args.output) / "regime"
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    built: dict[str, Any] = {}

    for code in codes:
        settings = _resolve_economy(code)
        try:
            economy = _assemble(code, args)
            contract = build_timeline(
                economy, taa, settings=settings, blend_weight=args.blend_weight
            )
        # One economy failing must not lose the others: a mandate blending seven scopes needs to know
        # which of them are publishable and which are not. SourceError is caught explicitly because
        # `_assemble` only converts PipelineError, so a missing source would otherwise abort the batch.
        except (SystemExit, RegimeTimelineError, PipelineError, SourceError) as error:
            failures.append(f"{code}: {error}")
            continue

        written = write_timeline(contract, directory)
        built[code] = contract
        rows.append(
            {
                "economy": code,
                "regime_id": contract.regime_id,
                "regime_timeline_id": contract.regime_timeline_id,
                "as_of": contract.as_of,
                "months": contract.n_periods,
                "first": contract.dates[0],
                "last": contract.dates[-1],
                "current_state": contract.current_state,
                "phase": contract.current_phase,
                "saturation_pct": contract.current_saturation_pct,
                "crisis_tail": contract.crisis_tail,
                "path": str(written),
            }
        )

    if not rows:
        return CommandResult(
            EXIT_FAILED,
            "no Regime timeline could be published:\n  " + "\n  ".join(failures),
            {"failures": failures},
        )

    # Blended market scopes, from the per-economy contracts just built.
    scope_rows: list[dict[str, Any]] = []
    if args.scope:
        from macrofield.contracts.regime_timeline import blend_scope

        settings = config_module.load()
        wanted = list(args.scope)
        if len(wanted) == 1 and wanted[0] == "all":
            wanted = [s for s in dict(settings.get("regime.scopes.presets")) if s != "equal"]
        for scope in wanted:
            try:
                blended = blend_scope(scope, built, settings=settings)
            except RegimeTimelineError as error:
                failures.append(f"scope {scope}: {error}")
                continue
            written = write_timeline(blended, directory)
            scope_rows.append(
                {
                    "scope": scope,
                    "regime_id": blended.regime_id,
                    "months": blended.n_periods,
                    "first": blended.dates[0],
                    "last": blended.dates[-1],
                    "current_state": blended.current_state,
                    "crisis_tail": blended.crisis_tail,
                    "economies": blended.provenance["economy_weights"],
                    "path": str(written),
                }
            )

    lines = [f"published {len(rows)} Regime timeline(s) to {directory}:", ""]
    lines.append(
        f"  {'economy':<10}{'months':>7}  {'window':<18}{'state':>6}{'phase':>6}"
        f"{'tail':>8}  regime_id"
    )
    for row in rows:
        window = f"{row['first']} to {row['last']}"
        phase = "n/a" if row["phase"] is None else str(row["phase"])
        lines.append(
            f"  {row['economy']:<10}{row['months']:>7}  {window:<18}{row['current_state']:>6}"
            f"{phase:>6}{row['crisis_tail']:>8.3f}  {row['regime_id']}"
        )
    if scope_rows:
        lines.append("")
        lines.append(f"  blended market scope(s):")
        lines.append(
            f"  {'scope':<12}{'months':>7}  {'window':<18}{'state':>6}{'tail':>8}  regime_id"
        )
        for row in scope_rows:
            window = f"{row['first']} to {row['last']}"
            lines.append(
                f"  {row['scope']:<12}{row['months']:>7}  {window:<18}{row['current_state']:>6}"
                f"{row['crisis_tail']:>8.3f}  {row['regime_id']}"
            )
        lines.append("")
        lines.append(
            "  A ReturnSet must be estimated against the same timeline the optimiser reads, so a mandate "
            "scoped to a blend needs that scope's file, not the per-economy ones."
        )

    lines.append("")
    lines.append(
        "  The distribution is what downstream integrates; the state path is the modal reading. The "
        "macro half is annual and held flat within each year, so intra-year movement is technical."
    )
    if failures:
        lines.append("")
        lines.append(f"  {len(failures)} item(s) could not be published:")
        lines.extend(f"    {f}" for f in failures)

    exit_code = EXIT_OK if not failures else EXIT_FAILED
    return CommandResult(
        exit_code,
        "\n".join(lines),
        {"timelines": rows, "scopes": scope_rows, "failures": failures},
    )


def command_cockpit(args: argparse.Namespace) -> CommandResult:
    """Serve the interactive dashboard."""
    try:
        from macrofield.cockpit.server import serve
    except ImportError as error:
        return CommandResult(
            EXIT_FAILED,
            (
                f"the cockpit needs its optional dependencies: {error}. Install them with "
                f"'pip install fastapi uvicorn plotly'."
            ),
        )
    serve(host=args.host, port=args.port)
    return CommandResult(EXIT_OK, "cockpit stopped")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Returns:
        The exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE

    try:
        result = args.handler(args)
    except SystemExit as error:
        message = str(error)
        if message and message not in ("0", "1", "2"):
            print(message, file=sys.stderr)
            return EXIT_USAGE
        raise

    if args.as_json:
        print(json.dumps({"message": result.message, **(result.payload or {})}, indent=2, default=str))
    else:
        stream = sys.stdout if result.exit_code == EXIT_OK else sys.stderr
        print(result.message, file=stream)

    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
