"""Minimal CLI for the Fund Map and Return Estimation programme.

Commands:
    fmre ingest <ticker> [--source csv|synthetic] [--data-root PATH] [--out PATH]
    fmre build-returnset --timeline PATH --tickers T1 T2 ... [--source csv|synthetic]
                         [--data-root PATH] [--calibration START,END] --out PATH
    fmre validate <path>

Uses argparse (stdlib) so no extra dependency is required.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from fmre.contracts import (
    build_returnset,
    house_view_from_regime,
    load_returnset,
    to_canonical_json,
    validate_returnset,
    write_returnset,
)
from fmre.estimate import estimate_block
from fmre.ingest.pipeline import ingest_ticker, write_parquet
from fmre.ingest.sources import CsvSource, SeriesSource, SyntheticSource, seed_state_conditional_hints
from fmre.regime import (
    StateToScenario,
    TimelineValidationError,
    build_synthetic_timeline,
    load_timeline,
)
from fmre.registers.building_blocks import load_seed
from fmre.registers.data_series import build_default_register


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _resolve_source(
    source: str,
    data_root: Path | None,
    timeline=None,
    blocks=None,
) -> SeriesSource:
    if source == "csv":
        if data_root is None:
            raise ValueError("CsvSource requires --data-root")
        return CsvSource(root=data_root)
    if source == "synthetic":
        return SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    if source == "seed-aware-synthetic":
        if timeline is None or blocks is None:
            raise ValueError("seed-aware-synthetic requires a timeline and the seed blocks")
        # The range comes from the timeline, not from a fixed pair of dates. This source conditions each
        # month's draw on the state active that month, so generating a month the timeline does not cover
        # asks for a state that does not exist. A real timeline starts where its two signal halves
        # overlap, which is later than the synthetic builder's 1998.
        return SyntheticSource(
            start=timeline.path.index[0].date(),
            end=timeline.path.index[-1].date(),
            timeline=timeline,
            state_hints=seed_state_conditional_hints(blocks),
        )
    raise ValueError(f"unknown source {source!r}")


# ---------------------------------------------------------------------------
# Subcommand: ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> int:
    blocks = load_seed()
    register = build_default_register(blocks)
    timeline = build_synthetic_timeline() if args.source == "seed-aware-synthetic" else None
    src = _resolve_source(args.source, args.data_root, timeline=timeline, blocks=blocks)
    if args.ticker not in register:
        print(f"ERROR: ticker {args.ticker!r} not in default register", file=sys.stderr)
        return 2
    harmonised = ingest_ticker(args.ticker, src, register)
    if args.out is not None:
        path = write_parquet(harmonised, args.out)
        print(str(path))
    else:
        print(f"ingested {args.ticker}: {harmonised.n_obs_returns()} return obs, "
              f"vintage {harmonised.provenance.data_vintage}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: build-returnset
# ---------------------------------------------------------------------------


def _parse_calibration(spec: str | None) -> tuple[str, str] | None:
    if spec is None:
        return None
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 2:
        raise ValueError(f"--calibration expects 'START,END', got {spec!r}")
    return parts[0], parts[1]


def cmd_build_returnset(args: argparse.Namespace) -> int:
    blocks = load_seed()
    blocks_by_id = {b.id: b for b in blocks}
    tickers = list(args.tickers) if args.tickers else [b.ticker for b in blocks]
    # Filter blocks to those matching supplied tickers
    selected = [b for b in blocks if b.ticker in set(tickers)]
    if not selected:
        print(f"ERROR: none of the supplied tickers match the register", file=sys.stderr)
        return 2

    register = build_default_register(blocks)

    # The Regime is an input, not something this programme invents. The synthetic builder exists so the
    # estimator could be developed before a real timeline existed, and it stamps a `REG-SYNTHETIC-...`
    # regime_id. Now that the macro programme publishes real timelines, using the stand-in has to be an
    # explicit request: a ReturnSet carrying a synthetic regime_id would be rejected by the downstream
    # optimiser anyway, and silently defaulting to it turns that into a confusing failure rather than a
    # clear one here.
    if args.timeline is not None:
        timeline = load_timeline(args.timeline)
    elif args.synthetic_timeline:
        timeline = build_synthetic_timeline()
        print(
            "WARNING: building against the synthetic stand-in timeline. The ReturnSet will carry a "
            "REG-SYNTHETIC regime_id and must not be used for allocation.",
            file=sys.stderr,
        )
    else:
        print(
            "ERROR: no Regime timeline supplied. Pass --timeline PATH with a timeline published by the "
            "macro programme (macrofield regime <economy> writes them to output/regime/<economy>.json), "
            "or pass --synthetic-timeline to build against the stand-in for testing.",
            file=sys.stderr,
        )
        return 2

    src = _resolve_source(args.source, args.data_root, timeline=timeline, blocks=blocks)
    sts = StateToScenario.load()
    calibration = _parse_calibration(args.calibration)

    estimates: dict = {}
    for b in selected:
        h = ingest_ticker(b.ticker, src, register)
        aligned = timeline.align_returns(h.returns)
        estimates[b.id] = estimate_block(
            b, aligned,
            all_estimates=estimates,     # accumulate for peer borrow
            all_blocks=blocks_by_id,
            calibration_window=calibration,
        )

    # Derive the house view from the Regime this ReturnSet is being weighted against (DECISIONS.md M64).
    # Falls back to DEFAULT_HOUSE_VIEW only for a synthetic timeline, which publishes no distributions, and says
    # so on stderr rather than substituting quietly.
    house_view = None
    if args.timeline is not None:
        import json as _json
        regime_payload = _json.loads(Path(args.timeline).read_text(encoding="utf-8"))
        house_view = house_view_from_regime(
            regime_payload, {str(i): s for i, s in enumerate(sts.mapping)}
        )
        print(
            "house view derived from the Regime, averaged through the cycle: "
            + ", ".join(f"{g} {w:.2%}" for g, w in sorted(house_view.items())),
            file=sys.stderr,
        )
    else:
        print(
            "WARNING: no real timeline, so the house view falls back to DEFAULT_HOUSE_VIEW. That view "
            "disagrees with any published Regime by construction; see DECISIONS.md M64.",
            file=sys.stderr,
        )

    rs = build_returnset(
        estimates=estimates,
        blocks_by_id=blocks_by_id,
        state_to_scenario=sts,
        timeline=timeline,
        house_view=house_view,
        calibration_window=calibration,
        horizon_years=args.horizon_years,
    )
    path = write_returnset(rs, args.out)
    print(str(path))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        payload = load_returnset(args.path)
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {payload['return_set_id']} state_grid={payload['state_grid']} "
          f"blocks={len(payload['building_blocks'])}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: doc
# ---------------------------------------------------------------------------


def cmd_doc(args: argparse.Namespace) -> int:
    from tools.build_fundmap import render_document
    path = render_document(args.returnset, args.out)
    print(str(path))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: stats
# ---------------------------------------------------------------------------


def cmd_stats(args: argparse.Namespace) -> int:
    """Human-readable summary of a ReturnSet: coverage histogram, role
    expectations under the stamped house view, resilience against the
    reference mandate."""
    from tools.build_fundmap import (
        DEFAULT_MANDATE, DEFAULT_WEIGHTS, _compute_resilience, _superpose_role_from_payload,
    )
    payload = load_returnset(args.path)

    print(f"ReturnSet  {payload['return_set_id']}")
    print(f"Regime     {payload['regime_id']}")
    print(f"Vintage    {payload['provenance'].get('data_vintage', 'n/a')}")
    print(f"Universe   {len(payload['building_blocks'])} building blocks - state grid {payload['state_grid']}")
    print(f"Window     {payload['provenance'].get('calibration_window') or 'not specified'}")
    print()

    # Coverage histogram
    counts: dict[str, int] = {"full": 0, "partial": 0, "borrowed": 0, "seed": 0}
    for bb in payload["building_blocks"]:
        counts[bb["estimation"]["coverage"]] += 1
    print("Coverage")
    for grade in ("full", "partial", "borrowed", "seed"):
        n = counts[grade]
        bar = "#" * min(50, n)
        print(f"  {grade:<10} {n:>3}  {bar}")
    print()

    # Role expectations under house_view
    role_exp = _superpose_role_from_payload(payload)
    print("Role expectations under stamped house view (annualised, decimal)")
    for role in ("gain", "income", "stabilisation", "protection"):
        if role in role_exp:
            print(f"  {role:<14} {role_exp[role]:+.4f}   ({role_exp[role] * 100:+.2f}%)")
    print()

    # Resilience against reference mandate
    ref_weights = {bid: w for bid, w in DEFAULT_WEIGHTS.items()
                   if bid in {int(bb["bb_id"]) for bb in payload["building_blocks"]}}
    if ref_weights and abs(sum(ref_weights.values()) - 1.0) < 1e-6:
        r_val, failing, r_p, margins = _compute_resilience(payload, ref_weights, DEFAULT_MANDATE)
        print("Reference book (30/20/30/20 Gain/Income/Protection/Cash) vs default mandate")
        print(f"  {'scenario':<14} {'R_P':>9} {'R_E':>9} {'margin':>9}")
        for scen in payload["scenarios"]:
            mark = "  clears" if margins[scen] >= 0 else "  FAILS"
            print(f"  {scen:<14} {r_p[scen]:>+9.4f} {DEFAULT_MANDATE[scen]:>+9.4f} {margins[scen]:>+9.4f}{mark}")
        print()
        verdict = "PASSES" if r_val >= 0 else f"FAILS ({failing})"
        print(f"Resilience R = {r_val:+.4f}   {verdict}")
    else:
        print("Reference book weights do not sum to 1 given available blocks; skipping resilience.")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fmre", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    _sources = ["csv", "synthetic", "seed-aware-synthetic"]

    p_ingest = sub.add_parser("ingest", help="Ingest one ticker end-to-end")
    p_ingest.add_argument("ticker", help="Bloomberg ticker as in the seed register")
    p_ingest.add_argument("--source", choices=_sources, default="synthetic")
    p_ingest.add_argument("--data-root", type=Path, default=None)
    p_ingest.add_argument("--out", type=Path, default=None, help="Parquet output directory")
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build-returnset", help="Build and emit a ReturnSet JSON")
    p_build.add_argument("--timeline", type=Path, default=None,
                         help="Path to a RegimeTimeline JSON published by the macro programme.")
    p_build.add_argument("--synthetic-timeline", action="store_true",
                         help=("Build against the synthetic stand-in timeline instead of a real one. For "
                               "testing only: the ReturnSet carries a REG-SYNTHETIC regime_id, which a "
                               "downstream optimiser will reject."))
    p_build.add_argument("--tickers", nargs="+", default=None,
                         help="Restrict to these tickers. If omitted, uses the full seed register.")
    p_build.add_argument("--source", choices=_sources, default="synthetic",
                         help="synthetic = uniform GBM; seed-aware-synthetic = state-conditional means from the seed.")
    p_build.add_argument("--data-root", type=Path, default=None)
    p_build.add_argument("--calibration", type=str, default=None, help="'START,END' dates (ISO)")
    p_build.add_argument("--horizon-years", type=float, default=1.0)
    p_build.add_argument("--out", type=Path, required=True)
    p_build.set_defaults(func=cmd_build_returnset)

    p_validate = sub.add_parser("validate", help="Validate a ReturnSet JSON on disk")
    p_validate.add_argument("path", type=Path)
    p_validate.set_defaults(func=cmd_validate)

    p_doc = sub.add_parser("doc", help="Regenerate the worked reading document")
    p_doc.add_argument("returnset", type=Path, help="Path to a validated ReturnSet JSON")
    p_doc.add_argument("--out", type=Path, required=True, help="Output HTML path")
    p_doc.set_defaults(func=cmd_doc)

    p_stats = sub.add_parser("stats", help="Print a human-readable summary of a ReturnSet")
    p_stats.add_argument("path", type=Path, help="Path to a validated ReturnSet JSON")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, TimelineValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
