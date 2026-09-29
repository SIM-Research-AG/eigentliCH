"""Freeze mrs's golden input from datafeed, over HTTP like any consumer. Development only.

Run from the engine folder, with datafeed running::

    python golden/build_golden.py [--datafeed http://127.0.0.1:8001]

mrs reads no source data itself: its golden input is datafeed's raw snapshot, the Bloomberg
pull of 2026-01-05 exactly as ``M_TS.mat`` holds it (gaps as nulls, no public fills). The CIO
exports in ``cio_*_2026-09/`` come from a later pull and carry their own input (MRS-20). The tests
read the files written here, so they run anywhere.

Outputs, under ``golden/snapshot_2026-01-05/``:

``panel.json``
    ``GET /panel`` for the 29 M_TS series ``mrs`` reads (``panel@1.1.0``), as datafeed served it.
``conversions.json``
    ``GET /snapshots/{id}/conversions`` for those series: what datafeed's importer turned
    into gaps, and which series were placeholder tickers (MATLAB read them as 1.0). With
    ``panel.json`` this rebuilds MATLAB's own view of ``M_TS`` (``mrs.inputs.matlab_view``).
``countries.json``
    ``GET /countries``: the registry, with each country's field name in ``M_TS``.
``source.json``
    The snapshot id, datafeed's manifest checksum (over its full 44-series panel) and the
    sha256 of the 29-series panel above (``mrs.clients.panel_checksum``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mrs.clients import panel_checksum  # noqa: E402
from mrs.contracts import ImportConversion, Panel  # noqa: E402
from mrs.series import REQUIRED_SERIES  # noqa: E402

SNAPSHOT_ID = "matlab-m_ts-2026-01-05.r3"
FOLDER = HERE / "snapshot_2026-01-05"


def write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size // 1024} KiB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datafeed", default="http://127.0.0.1:8001",
                        help="datafeed to fetch the input from")
    args = parser.parse_args(argv)
    base = args.datafeed.rstrip("/")

    manifest = httpx.get(f"{base}/snapshots/{SNAPSHOT_ID}", timeout=60).raise_for_status().json()
    params = [("snapshot_id", SNAPSHOT_ID), ("freq", "M")] + [("series", s) for s in REQUIRED_SERIES]
    body = httpx.get(f"{base}/panel", params=params, timeout=120).raise_for_status()
    panel = Panel.model_validate_json(body.content)
    served = {s.series_id for s in panel.series}
    if served != set(REQUIRED_SERIES):
        print(f"datafeed does not serve {sorted(set(REQUIRED_SERIES) - served)}", file=sys.stderr)
        return 2
    conversions = [ImportConversion.model_validate(c).model_dump() for c in
                   httpx.get(f"{base}/snapshots/{SNAPSHOT_ID}/conversions", timeout=60)
                   .raise_for_status().json() if c["series_id"] in served]
    countries = httpx.get(f"{base}/countries", timeout=60).raise_for_status().json()

    FOLDER.mkdir(parents=True, exist_ok=True)
    (FOLDER / "panel.json").write_bytes(body.content)
    print(f"wrote {(FOLDER / 'panel.json').relative_to(HERE.parent)} from {base}")
    write(FOLDER / "conversions.json", conversions)
    write(FOLDER / "countries.json", countries)
    write(FOLDER / "source.json", {
        "_note": ("Frozen copy of datafeed's raw snapshot (r3) for the 29 M_TS series mrs reads, fetched "
                  "from GET /panel. datafeed_checksum is datafeed's manifest checksum over its "
                  "full panel; panel_sha256 is this copy's, checked by tests/test_input.py."),
        "snapshot_id": SNAPSHOT_ID,
        "datafeed_checksum": manifest["checksum"],
        "datafeed_source": manifest["source"],
        "panel_sha256": panel_checksum(panel),
        "series": list(REQUIRED_SERIES),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
