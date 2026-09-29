"""Seed mandate YAML from the legacy Controller workbook. Read-only, run once.

This is the only code in the programme that opens `Controller_Test.xlsx`, and it opens it read-only. It
exists so the real mandates can be carried into the new build without hand-transcribing four target
curves and seven bound blocks each. After running it, the YAML is the mandate and the workbook is
history (decisions.md D1).

**Positional, and deliberately so, but named on the way out.** The workbook's blocks are read by row
offset because that is the only structure it has. Each block's category labels are checked against the
canonical vocabulary as they are read, so a positional read that has drifted is caught rather than
silently producing bounds against the wrong categories. What is written is named: every bound carries its
category and an explicit `lower` and `upper`.

**Two label inconsistencies inside the workbook are normalised here** (decisions.md D25):
the `Client` sheet's phase labels are `Foundation, Build up, Optimization, Maturity` while the
`Investment` sheet's instrument values are `Foundation, Maturing, Optimization, Saturation`. Both are
mapped onto the canonical four. The `Client` sheet's `Maturity` is position 4 and is *not* the same thing
as the register's `Maturing`, which is position 2.

Usage:
    python -m tools.seed_mandates [--workbook PATH] [--out DIR] [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pcp.config import Config, load_config  # noqa: E402

DEFAULT_WORKBOOK = Path(
    r"c:\Users\nicol\Desktop\SIM_NAS\SIM_Tech\Master_Controller\Controller_Test.xlsx"
)

#: Row spans per bound block, from Dataloader.m lines 35 to 41. The header sits one row above each span
#: and is deliberately not read: the Capital Type header is mislabelled `UB | LB` while its values are
#: ordered like every other block's, so trusting the header would transpose that block's bounds
#: (decisions.md D6).
BLOCK_ROWS: dict[str, range] = {
    "currency": range(35, 45),
    "region": range(47, 54),
    "phase": range(56, 60),
    "capital_type": range(62, 65),
    "liquidity": range(67, 71),
    "role": range(73, 77),
    "asset_class": range(79, 84),
}

#: Which config vocabulary each block is checked against.
BLOCK_VOCABULARY: dict[str, str] = {
    "currency": "currency",
    "region": "region",
    "phase": "phase",
    "capital_type": "capital_type",
    "liquidity": "liquidity",
    "role": "role",
    "asset_class": "asset_class",
}

#: Workbook label to canonical label. Only where they differ.
LABEL_ALIASES: dict[str, str] = {
    "Build up": "Build-up",
    "Optimization": "Optimisation",
    # `Client` sheet position 4. Not the register's `Maturing`, which is position 2. See D25.
    "Maturity": "Saturation",
    "Stabilization": "Stabilisation",
    "Switerland": "Switzerland",
}

TARGET_CURVE_ROWS = range(8, 33)
ROW_CLIENT = 1
ROW_MANDATE = 2
ROW_MAX_POSITION = 4
ROW_ESG = 5

#: Investment sheet columns, from Dataloader.m lines 74 to 86.
INV_COL_ID = 38
INV_COL_FIXED_ALLOCATION = 39
INV_FIRST_UNIVERSE_COL = 40


class SeedError(RuntimeError):
    """Raised when the workbook cannot be read in the shape this tool expects."""


def _canonical(label: str) -> str:
    return LABEL_ALIASES.get(label.strip(), label.strip())


def _cell(rows: Sequence[Sequence[Any]], row: int, col: int) -> Any:
    """One cell, one-based, or None when outside the sheet."""
    if row - 1 >= len(rows):
        return None
    line = rows[row - 1]
    if col - 1 >= len(line):
        return None
    return line[col - 1]


def _number(value: Any, what: str) -> float:
    if value is None or value == "":
        raise SeedError(f"{what} is empty in the workbook, and this tool does not substitute a default")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SeedError(f"{what} is not a number: {value!r}") from error


def read_mandates(workbook: Path, config: Config) -> tuple[list[dict[str, Any]], list[str]]:
    """Read every (client, mandate) pair the workbook defines.

    Returns the mandate payloads and the warnings raised while reading.
    """
    from openpyxl import load_workbook

    if not workbook.exists():
        raise SeedError(f"workbook not found: {workbook}")

    book = load_workbook(workbook, data_only=True, read_only=True)
    try:
        if "Client" not in book.sheetnames or "Investment" not in book.sheetnames:
            raise SeedError(
                f"{workbook.name} needs both a 'Client' and an 'Investment' sheet; found "
                f"{book.sheetnames}"
            )
        client_rows = list(
            book["Client"].iter_rows(min_row=1, max_row=83, max_col=40, values_only=True)
        )
        investment = book["Investment"]
        investment_rows = list(
            investment.iter_rows(
                min_row=1, max_row=investment.max_row, max_col=investment.max_column, values_only=True
            )
        )
    finally:
        book.close()

    warnings: list[str] = []
    payloads: list[dict[str, Any]] = []

    # Mandate columns come in threes, matching `for q = 3:3:size(Clientsheet, 2)` in Dataloader.m.
    for column in range(3, 40, 3):
        client = _cell(client_rows, ROW_CLIENT, column)
        mandate = _cell(client_rows, ROW_MANDATE, column)
        if not client or not mandate:
            continue
        payload, block_warnings = _read_one(
            client_rows, investment_rows, column, str(client).strip(), str(mandate).strip(), config
        )
        payloads.append(payload)
        warnings.extend(block_warnings)

    if not payloads:
        raise SeedError(
            f"no (client, mandate) pair found in {workbook.name}. Rows 1 and 2 of the Client sheet "
            f"should name them, in columns 3, 6, 9 and so on."
        )
    return payloads, warnings


def _read_one(
    client_rows: Sequence[Sequence[Any]],
    investment_rows: Sequence[Sequence[Any]],
    column: int,
    client: str,
    mandate: str,
    config: Config,
) -> tuple[dict[str, Any], list[str]]:
    identity = f"{client}/{mandate}"
    warnings: list[str] = []

    curve = [
        _number(_cell(client_rows, row, column), f"{identity} target curve row {row}")
        for row in TARGET_CURVE_ROWS
    ]

    bounds: dict[str, dict[str, dict[str, float]]] = {}
    for dimension, rows in BLOCK_ROWS.items():
        vocabulary = config.vocabularies.by_name(BLOCK_VOCABULARY[dimension])
        if len(rows) != len(vocabulary):
            raise SeedError(
                f"{identity}: the workbook's {dimension} block spans {len(rows)} rows but the "
                f"vocabulary has {len(vocabulary)} categories. The read is positional, so it cannot "
                f"proceed."
            )
        per_category: dict[str, dict[str, float]] = {}
        for offset, row in enumerate(rows):
            expected = vocabulary.labels[offset]
            found = _canonical(str(_cell(client_rows, row, 2) or ""))
            if found != expected:
                warnings.append(
                    f"{identity}: row {row} of the {dimension} block is labelled {found!r} where the "
                    f"vocabulary expects {expected!r} at that position. The bound was read positionally "
                    f"and assigned to {expected!r}. Check it."
                )
            lower = _number(
                _cell(client_rows, row, column), f"{identity} {dimension} {expected} lower"
            )
            upper = _number(
                _cell(client_rows, row, column + 1), f"{identity} {dimension} {expected} upper"
            )
            if lower > upper:
                warnings.append(
                    f"{identity}: the {dimension} bound for {expected!r} reads lower={lower} above "
                    f"upper={upper}. The workbook's Capital Type header is known to be mislabelled "
                    f"(decisions.md D6); the values were still read as (lower, upper) positionally, and "
                    f"this pair needs checking."
                )
            per_category[expected] = {"lower": lower, "upper": upper}
        bounds[dimension] = per_category

    universe, fixed, universe_warnings = _read_universe(investment_rows, mandate, identity)
    warnings.extend(universe_warnings)

    payload: dict[str, Any] = {
        "client": client,
        "mandate": mandate,
        # The workbook holds no market, currency or benchmark per mandate: those were Main_Controller
        # cells chosen per run rather than mandate properties. The run defaults are written here so the
        # mandate is self-contained, and they are overridable per run.
        "market": str(config.get("run.market")),
        "currency": str(config.get("run.currency")),
        "benchmark": str(config.get("run.benchmark")),
        "horizon_years": float(config.get("contracts.expected_horizon_years")),
        "max_single_position": _number(
            _cell(client_rows, ROW_MAX_POSITION, column), f"{identity} max single position"
        ),
        "esg_min": _number(_cell(client_rows, ROW_ESG, column), f"{identity} ESG minimum"),
        "target_curve": curve,
        "universe": universe,
        "fixed_allocations": fixed,
        "bounds": bounds,
    }
    return payload, warnings


def _read_universe(
    investment_rows: Sequence[Sequence[Any]],
    mandate: str,
    identity: str,
) -> tuple[list[int], dict[int, float], list[str]]:
    """The investable universe: block ids flagged 'x' under the mandate's column."""
    warnings: list[str] = []
    header = investment_rows[0] if investment_rows else []

    matches = [
        col
        for col in range(INV_FIRST_UNIVERSE_COL, len(header) + 1)
        if str(header[col - 1] or "").strip() == mandate
    ]
    if not matches:
        available = sorted(
            str(header[col - 1]).strip()
            for col in range(INV_FIRST_UNIVERSE_COL, len(header) + 1)
            if header[col - 1]
        )
        raise SeedError(
            f"{identity}: no universe column headed {mandate!r} in the Investment sheet from column "
            f"{INV_FIRST_UNIVERSE_COL} onward. Available: {available}."
        )
    if len(matches) > 1:
        warnings.append(
            f"{identity}: the Investment sheet has {len(matches)} columns headed {mandate!r}; the first "
            f"(column {matches[0]}) was used."
        )
    column = matches[0]

    universe: list[int] = []
    fixed: dict[int, float] = {}
    for row in investment_rows[1:]:
        if column - 1 >= len(row):
            continue
        if str(row[column - 1] or "").strip().lower() != "x":
            continue
        raw_id = row[INV_COL_ID - 1] if INV_COL_ID - 1 < len(row) else None
        if raw_id is None:
            warnings.append(f"{identity}: an instrument flagged for this mandate has no ID; skipped.")
            continue
        block_id = int(raw_id)
        universe.append(block_id)
        pinned = row[INV_COL_FIXED_ALLOCATION - 1] if INV_COL_FIXED_ALLOCATION - 1 < len(row) else None
        if pinned not in (None, "", 0, 0.0):
            fixed[block_id] = float(pinned)

    if not universe:
        raise SeedError(
            f"{identity}: no instrument is flagged 'x' in column {column} of the Investment sheet, so "
            f"the mandate has an empty universe."
        )
    return universe, fixed, warnings


def write_mandates(
    payloads: Iterable[dict[str, Any]],
    directory: Path,
    force: bool = False,
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for payload in payloads:
        stem = f"{payload['client']}_{payload['mandate']}".replace(" ", "_")
        target = directory / f"{stem}.yaml"
        if target.exists() and not force:
            raise SeedError(
                f"{target} already exists. Pass --force to overwrite. Refusing by default because a "
                f"mandate may have been edited by hand since it was seeded."
            )
        header = (
            f"# Mandate seeded from the legacy Controller workbook, read-only.\n"
            f"# {payload['client']} / {payload['mandate']}.\n"
            f"#\n"
            f"# The target curve is in annualised decimals, one point per regime state, ordered\n"
            f"# crisis-low (index 0) to boom-high (index 24). Bounds are fractions of the portfolio.\n"
            f"# A category absent from a bound block is unconstrained.\n"
        )
        with target.open("w", encoding="utf-8") as handle:
            handle.write(header)
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True, width=100)
        written.append(target)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seed_mandates",
        description=(
            "Seed mandate YAML from the legacy Controller workbook. Reads the workbook read-only and "
            "never writes to it."
        ),
    )
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--out", type=Path, default=None, help="output directory for the YAML")
    parser.add_argument("--force", action="store_true", help="overwrite existing mandate files")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    directory = args.out or (Path(__file__).resolve().parent.parent / str(config.get("paths.mandates_dir")))

    try:
        payloads, warnings = read_mandates(args.workbook, config)
        written = write_mandates(payloads, directory, force=args.force)
    except SeedError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"seeded {len(written)} mandate(s) from {args.workbook.name} into {directory}:")
    for payload, path in zip(payloads, written):
        pinned = f", {len(payload['fixed_allocations'])} pinned" if payload["fixed_allocations"] else ""
        print(
            f"  {payload['client']}/{payload['mandate']:<14} "
            f"{len(payload['universe']):>2} instruments{pinned}, "
            f"max position {payload['max_single_position']:.2f}, ESG floor {payload['esg_min']:.2f} "
            f"-> {path.name}"
        )

    if warnings:
        print(f"\n{len(warnings)} thing(s) to check:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\nEvery bound block matched the canonical vocabulary position for position.")

    print(
        "\nThe workbook was opened read-only and is not a runtime dependency. Edit the YAML from here on."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
