"""Emit a JSON Schema per contract.

The Phase 1 gate asks for typed schemas plus emitted JSON Schema. Emitting rather than hand-writing means the
schema cannot drift from the type, which is the failure mode a hand-written schema always eventually has.

Run: `python -m contracts.emit_schemas`
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts import CONTRACTS
from contracts.base import canonical_json

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def emit(directory: Path | str | None = None) -> dict[str, Path]:
    """Write one schema per contract and return the paths.

    Written canonically so an unchanged contract produces a byte-identical schema and a real change shows up
    as a diff rather than as reordered keys.
    """
    root = Path(directory) if directory is not None else SCHEMA_DIR
    root.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for contract in CONTRACTS:
        schema = contract.json_schema()
        target = root / f"{contract.CONTRACT_NAME}.schema.json"
        target.write_text(
            json.dumps(json.loads(canonical_json(schema)), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[contract.CONTRACT_NAME] = target
    return written


def main() -> int:
    written = emit()
    print(f"emitted {len(written)} contract schema(s) to {SCHEMA_DIR}:")
    for name, path in written.items():
        contract = next(c for c in CONTRACTS if c.CONTRACT_NAME == name)
        print(f"  {name:<22} v{contract.CONTRACT_VERSION:<8} {contract.REGULATED.value:<12} {path.name}")
    print()
    print(
        "  Regime and ReturnSet are not emitted here: they are produced and owned by macrofield and fmre, "
        "and are referenced rather than redefined."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
