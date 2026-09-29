"""Command-line entry points.

    pcp optimise --mandate <name> [--speed exact] [--optimiser curve|mv]
    pcp backtest --mandate <name> --months 240
    pcp report --mandate <name>
    pcp mandates
    pcp cockpit

Exit codes: 0 success, 1 a handled failure (an infeasible mandate, a regime_id mismatch, a missing
contract), 2 a usage error. A handled failure prints a reason a reader can act on rather than a traceback,
because the commonest causes (a Regime not yet published, a ReturnSet built under a different regime) are
build-order problems with a specific fix.

Every command that writes goes through `pcp.reporting.export`, so the stamps and the disclaimer are
attached at the write boundary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from pcp import ENGINE_VERSION, __version__
from pcp.config import ConfigError, load_config

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcp",
        description=(
            "Portfolio Creation Program: fits a client allocation to a mandate's target return curve "
            "over the live macro regime. Decision support and research tooling, not investment advice."
        ),
    )
    parser.add_argument("--version", action="version", version=f"pcp {__version__}")
    parser.add_argument("--config", type=Path, default=None, help="override config/defaults.yaml")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON, not prose")
    parser.add_argument(
        "--regime-dir", type=Path, default=None, help="directory of published Regime timelines"
    )
    parser.add_argument("--returnset", type=Path, default=None, help="path to the ReturnSet")
    parser.add_argument("--mandates-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None, help="directory for written results")

    sub = parser.add_subparsers(dest="command", metavar="command")

    def add_run_arguments(target: argparse.ArgumentParser) -> None:
        target.add_argument("--mandate", required=True, help="file stem, mandate name, or client/mandate")
        target.add_argument("--market", default=None, help="override the mandate's market scope")
        target.add_argument("--speed", choices=["fast", "exact"], default=None)
        target.add_argument(
            "--optimiser",
            choices=["curve", "mv"],
            default="curve",
            help="curve is the model of record; mv is a labelled comparison",
        )

    optimise = sub.add_parser("optimise", help="optimise a mandate for the current regime")
    add_run_arguments(optimise)
    optimise.add_argument("--no-write", action="store_true", help="print only, write nothing")
    optimise.set_defaults(handler=command_optimise)

    backtest = sub.add_parser("backtest", help="re-optimise over the trailing regime history")
    add_run_arguments(backtest)
    backtest.add_argument("--months", type=int, default=240)
    backtest.add_argument("--no-write", action="store_true")
    backtest.set_defaults(handler=command_backtest)

    report = sub.add_parser("report", help="optimise and write the full artefact set including the brief")
    add_run_arguments(report)
    report.add_argument("--months", type=int, default=0)
    report.set_defaults(handler=command_report)

    challenge = sub.add_parser(
        "challenge",
        help="score a proposed portfolio against the optimised one on the same objective and limits",
    )
    add_run_arguments(challenge)
    challenge.add_argument(
        "--portfolio",
        type=Path,
        default=None,
        help=(
            "the proposed portfolio: YAML, JSON or CSV mapping bb_id to weight. Omit to challenge an "
            "equal-weight reference over the mandate's universe."
        ),
    )
    challenge.add_argument("--no-write", action="store_true")
    challenge.set_defaults(handler=command_challenge)

    mandates = sub.add_parser("mandates", help="list the configured mandates")
    mandates.set_defaults(handler=command_mandates)

    cockpit = sub.add_parser("cockpit", help="serve the dashboard on a local port")
    cockpit.add_argument("--host", default=None)
    cockpit.add_argument("--port", type=int, default=None)
    cockpit.set_defaults(handler=command_cockpit)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _run(args: argparse.Namespace, months: int) -> tuple[Any, Any, Any, Any]:
    from pcp.pipeline import PipelineError, diagnostics as build_diagnostics, prepare, run

    config = load_config(args.config)
    if args.output is not None:
        config.raw["paths"]["output_dir"] = str(args.output)

    inputs = prepare(
        args.mandate,
        config,
        market=args.market,
        regime_dir=args.regime_dir,
        returnset_path=args.returnset,
        mandates_dir=args.mandates_dir,
    )
    result = run(
        args.mandate,
        config,
        market=args.market,
        speed=args.speed,
        optimiser=args.optimiser,
        backtest_months=months,
        inputs=inputs,
    )
    return config, inputs, result, build_diagnostics(inputs, result, config)


def command_optimise(args: argparse.Namespace) -> int:
    return _optimise_like(args, months=0, write_brief=False)


def command_backtest(args: argparse.Namespace) -> int:
    if args.months < 0:
        print("ERROR: --months cannot be negative", file=sys.stderr)
        return EXIT_USAGE
    return _optimise_like(args, months=args.months, write_brief=False)


def command_report(args: argparse.Namespace) -> int:
    args.no_write = False
    return _optimise_like(args, months=args.months, write_brief=True)


def _optimise_like(args: argparse.Namespace, months: int, write_brief: bool) -> int:
    from pcp.pipeline import PipelineError
    from pcp.reporting import export_result, result_payload

    try:
        config, inputs, result, diagnostics = _run(args, months)
    except PipelineError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_FAILED
    except ConfigError as error:
        print(f"ERROR: configuration problem: {error}", file=sys.stderr)
        return EXIT_USAGE

    written: dict[str, Path] = {}
    if not getattr(args, "no_write", False):
        written = export_result(
            result, config, diagnostics=diagnostics, write_brief=write_brief
        )

    if args.as_json:
        payload = result_payload(result, config, diagnostics)
        payload["written"] = {k: str(v) for k, v in written.items()}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render(result, inputs, diagnostics, written))

    # An infeasible mandate is a handled failure, not a success with a caveat.
    return EXIT_OK if result.ok else EXIT_FAILED


def command_challenge(args: argparse.Namespace) -> int:
    """Score a proposed portfolio against the optimised allocation."""
    from pcp.model.challenge import (
        ChallengeError,
        challenge as run_challenge,
        equal_weight_proposal,
        load_proposal,
    )
    from pcp.pipeline import PipelineError
    from pcp.reporting.challenge_report import challenge_payload, render_challenge

    try:
        config, inputs, result, _ = _run(args, months=0)
    except PipelineError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_FAILED
    except ConfigError as error:
        print(f"ERROR: configuration problem: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if args.portfolio is not None:
            proposal = load_proposal(args.portfolio)
            label = args.portfolio.stem
        else:
            proposal = equal_weight_proposal(inputs.mandate)
            label = "equal weight"
        comparison = run_challenge(
            proposal,
            inputs.mandate,
            inputs.returnset,
            result.current.weights,
            result.current.bb_ids,
            result.current.regime,
            config,
            proposal_label=label,
        )
    except ChallengeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_FAILED

    written: dict[str, Path] = {}
    if not args.no_write:
        import json as _json

        from pcp.reporting.export import _default_output

        root = _default_output(config)
        root.mkdir(parents=True, exist_ok=True)
        stem = f"{result.mandate.client}_{result.mandate.name}_challenge".replace(" ", "_")
        payload = challenge_payload(comparison, result, config)
        target = root / f"{stem}.json"
        target.write_text(
            _json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
        )
        written["json"] = target
        brief = root / f"{stem}_brief.md"
        brief.write_text(render_challenge(comparison, result, config), encoding="utf-8")
        written["brief"] = brief

    if args.as_json:
        payload = challenge_payload(comparison, result, config)
        payload["written"] = {k: str(v) for k, v in written.items()}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_challenge(comparison, result, label, written))

    # An inadmissible proposal is a finding, not a program failure: the comparison succeeded and its
    # answer is "this breaches the mandate". Exit 0 so a caller can distinguish that from a broken run.
    return EXIT_OK


def _render_challenge(comparison: Any, result: Any, label: str, written: dict[str, Path]) -> str:
    mandate = result.mandate
    lines: list[str] = []
    lines.append(f"{mandate.client} / {mandate.name}   challenge: {label} against optimised")
    lines.append(f"  regime      {result.regime_id}  as at {result.as_of}")
    lines.append("")

    if comparison.admissible:
        lines.append("  ADMISSIBLE: the proposal respects every mandate limit.")
    else:
        lines.append(f"  NOT ADMISSIBLE: {len(comparison.breaches)} mandate limit(s) breached.")
        for breach in comparison.breaches[:14]:
            lines.append(f"    {breach.describe()}")
        if len(comparison.breaches) > 14:
            lines.append(f"    and {len(comparison.breaches) - 14} more")
    lines.append("")

    ratio = comparison.objective_ratio
    lines.append(
        f"  objective   proposed {comparison.proposed.objective_value:.6g}   "
        f"optimised {comparison.optimised.objective_value:.6g}"
    )
    if ratio is not None:
        lines.append(f"              the proposal carries {ratio:.2f}x the achievable shortfall")
    lines.append(
        f"  esg         proposed {comparison.proposed.esg:.2f}   "
        f"optimised {comparison.optimised.esg:.2f}   floor {mandate.esg_min:.2f}"
    )
    lines.append("")

    worst = comparison.worst_states(4)
    if worst:
        lines.append("  where the gap is:")
        for row in worst:
            tail = "  (crisis tail)" if row["state"] <= 5 else ""
            lines.append(
                f"    state {row['state']:>2}  proposed {row['proposed_shortfall']:.4f}  "
                f"optimised {row['optimised_shortfall']:.4f}  gap {row['gap']:+.4f}{tail}"
            )
        lines.append("")

    rows = [r for r in comparison.weight_differences() if abs(r["difference"]) >= 5e-4]
    if rows:
        lines.append("  largest weight differences:")
        for row in rows[:14]:
            flag = "" if row["in_universe"] else " *outside universe*"
            lines.append(
                f"    {row['difference']:>+8.2%}  {str(row['name'])[:32]:<32} "
                f"proposed {row['proposed']:>7.2%}  optimised {row['optimised']:>7.2%}{flag}"
            )
        lines.append("")

    lines.append("  by role:")
    for role, proposed in comparison.proposed.role_allocation.items():
        optimised = comparison.optimised.role_allocation[role]
        lines.append(
            f"    {role:<16}proposed {proposed:>7.2%}  optimised {optimised:>7.2%}  "
            f"{proposed - optimised:>+7.2%}"
        )
    lines.append("")

    if comparison.notes:
        lines.append("  notes:")
        for note in comparison.notes:
            lines.append(f"    - {note}")
        lines.append("")

    if written:
        lines.append("  written:")
        for kind, path in written.items():
            lines.append(f"    {kind:<6} {path}")
        lines.append("")

    lines.append(
        "  A worse objective means a worse fit to the mandate curve, which is the mandate's own "
        "definition of good. It is not by itself a reason to change a holding."
    )
    lines.append("  Model-derived, not a forecast. Not investment advice.")
    return "\n".join(lines)


def command_mandates(args: argparse.Namespace) -> int:
    from pcp.ingest import list_mandates

    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_USAGE

    rows = list_mandates(directory=args.mandates_dir, config=config)
    if not rows:
        print(
            "no mandates configured. Seed them from the legacy workbook with "
            "'python -m tools.seed_mandates'.",
            file=sys.stderr,
        )
        return EXIT_FAILED

    if args.as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return EXIT_OK

    good = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    print(f"{len(good)} mandate(s) configured:")
    print()
    print(f"  {'client':<12}{'mandate':<20}{'market':<10}{'ccy':<6}{'universe':>9}")
    for row in sorted(good, key=lambda r: (str(r['client']), str(r['mandate']))):
        print(
            f"  {str(row['client']):<12}{str(row['mandate']):<20}{str(row['market']):<10}"
            f"{str(row['currency']):<6}{row['universe_size']:>9}"
        )
    if bad:
        print()
        print(f"{len(bad)} file(s) could not be read:")
        for row in bad:
            print(f"  {row['path']}: {row.get('error')}")
    return EXIT_OK


def command_cockpit(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        from pcp.cockpit.server import serve
    except ImportError as error:
        print(
            f"ERROR: the cockpit needs its optional dependencies: {error}. Install them with "
            f"'pip install fastapi uvicorn'.",
            file=sys.stderr,
        )
        return EXIT_FAILED

    host = args.host or str(config.get("cockpit.host"))
    port = args.port or int(config.get("cockpit.port"))
    serve(
        host=host,
        port=port,
        config_path=args.config,
        regime_dir=args.regime_dir,
        returnset_path=args.returnset,
        mandates_dir=args.mandates_dir,
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Prose rendering
# ---------------------------------------------------------------------------


def _render(result: Any, inputs: Any, diagnostics: dict[str, Any], written: dict[str, Path]) -> str:
    current = result.current
    mandate = result.mandate
    lines: list[str] = []

    lines.append(f"{mandate.client} / {mandate.name}   {mandate.market}, {mandate.currency}")
    lines.append(
        f"  regime      {result.regime_id}  as at {result.as_of}  crisis tail "
        f"{result.crisis_tail:.1%}"
    )
    lines.append(f"  returnset   {result.return_set_id}  ({result.returnset_model_version})")
    lines.append(
        f"  engine      {result.engine_version}  {result.optimiser}  {result.speed}  "
        f"trace {result.trace_id}"
    )
    window = diagnostics.get("regime_window", {})
    if window:
        lines.append(
            f"  window      {window.get('first')} to {window.get('last')} "
            f"({window.get('months')} months)"
        )
    lines.append("")

    if current.conditions_met != "yes":
        lines.append("  CONDITIONS NOT MET: the budget equality was not satisfied within tolerance.")
        lines.append("  The weights below are renormalised and may satisfy no constraint set.")
        lines.append("")

    lines.append(f"  objective   {current.objective_value:.8g}   solver {current.solver_method}")
    lines.append(
        f"  esg         {current.esg:.2f} against a floor of {mandate.esg_min:.2f}"
    )
    lines.append("")

    if current.binding:
        lines.append(f"  {len(current.binding)} binding constraint(s):")
        for binding in current.binding[:12]:
            lines.append(
                f"    {binding.dimension}.{binding.category} {binding.side} "
                f"{binding.bound:.4f}, realised {binding.realised:.4f}"
            )
        if len(current.binding) > 12:
            lines.append(f"    and {len(current.binding) - 12} more")
    else:
        lines.append("  no constraint binds; every exposure was chosen by the fit")
    lines.append("")

    lines.append("  allocation:")
    rows = sorted(
        diagnostics.get("instruments", []), key=lambda r: -float(r["weight"])
    )
    for row in rows:
        weight = float(row["weight"])
        if weight < 5e-5:
            continue
        bar = "#" * max(1, int(round(weight * 40)))
        lines.append(
            f"    {weight:>7.2%}  {str(row['name'])[:34]:<34} {str(row['role']):<14}"
            f"{str(row['region_geo']):<15}{bar}"
        )
    omitted = sum(1 for r in rows if float(r["weight"]) < 5e-5)
    if omitted:
        lines.append(f"    ({omitted} position(s) below 0.005 percent omitted)")
    lines.append("")

    lines.append("  by role:")
    for role, weight in current.role_allocation.items():
        lines.append(f"    {role:<16}{weight:>7.2%}")
    lines.append("")

    if len(result.allocations) > 1:
        infeasible = sum(1 for a in result.allocations if a.conditions_met != "yes")
        lines.append(
            f"  backtest    {len(result.allocations)} periods, "
            f"{result.allocations[0].period} to {result.allocations[-1].period}, model-derived"
        )
        if infeasible:
            lines.append(f"              {infeasible} period(s) did not meet the budget equality")
        lines.append("")

    if result.notes:
        lines.append("  notes:")
        for note in result.notes:
            lines.append(f"    - {note}")
        lines.append("")

    if written:
        lines.append("  written:")
        for kind, path in written.items():
            lines.append(f"    {kind:<6} {path}")
        lines.append("")

    lines.append("  Model-derived, not a forecast. Not investment advice.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
