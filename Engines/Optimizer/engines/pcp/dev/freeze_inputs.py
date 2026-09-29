"""Freeze the upstream inputs the tests run on, over HTTP like any consumer. Development only.

Run from the engine folder, with ``aggregation`` (8004) and ``fmre`` (8006) running::

    python dev/freeze_inputs.py [--regime RGM-e2658e8e9bbbc81e] [--currency CHF]

Writes ``golden/inputs/``: the Regime (``GET /regime/{id}``), the ReturnSet (``GET /v1/return-set``) and the
instrument register (``GET /v1/instruments``), exactly as served, the ReturnSet in ``--currency`` (CHF by
default, the currency the golden cases are read in, PCP-20) and unstamped (the tests stamp the Regime), and
``manifest.json`` with the sha256 of each. The tests serve these files back through ``httpx.MockTransport``, so they run anywhere.

Model-derived research output. Not investment advice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "golden" / "inputs"
DEFAULT_REGIME = "RGM-e2658e8e9bbbc81e"   # aggregation calibration 1.2.0, Default optimism


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regime", default=DEFAULT_REGIME)
    parser.add_argument("--aggregation", default="http://127.0.0.1:8004")
    parser.add_argument("--fmre", default="http://127.0.0.1:8006")
    parser.add_argument("--currency", default="CHF", choices=("CHF", "EUR", "USD"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fetches = {
        "regime.json": (args.aggregation, f"/regime/{args.regime}", None),
        "return_set.json": (args.fmre, "/v1/return-set", {"include_instruments": "true", "include_blocks": "false",
                                                             "currency": args.currency}),
        "instruments.json": (args.fmre, "/v1/instruments", {"active_only": "true"}),
    }
    manifest = {"_note": "Frozen upstream inputs for pcp's tests (dev/freeze_inputs.py).", "files": {}}
    for name, (base, path, params) in fetches.items():
        response = httpx.get(base + path, params=params, timeout=120)
        response.raise_for_status()
        (OUT / name).write_bytes(response.content)
        manifest["files"][name] = {"url": str(response.url), "sha256": hashlib.sha256(response.content).hexdigest(),
                                   "bytes": len(response.content)}
        print(f"froze {name}: {len(response.content):,} bytes from {response.url}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
