"""Generate `eigentlich.ico` — the prototype2 desktop icon.

    python desktop/make_icon.py

**Reuses the estate's mark rather than drawing a second one.** `eigentliCH/desktop/make_icon.py` already
renders the rising-trajectory mark, in four sizes, with stdlib only. This loads that module by path and
re-runs it with a different palette, so the two icons are recognisably the same family and the drawing code
exists once. If the mark changes there, it changes here.

**Why a different colour and not the same icon.** Two shortcuts pointing at two different programs are going
to sit side by side on one desktop. An icon that does not distinguish them is a way to start the wrong one,
which for a program that opens a browser at a member's data is worth one colour change to avoid.

The estate's icon is indigo with a blue accent. This one is the same ground with a green accent, which is
the colour the build spec uses for `--ok` — prototype2 being the build that is meant to satisfy it.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ESTATE_ICON_MODULE = HERE.parent.parent / "desktop" / "make_icon.py"
OUT = HERE / "eigentlich.ico"

#: From the build spec's own palette: `--ok: #1F6B4E`, lightened for legibility at 16px.
ACCENT_P2 = (47, 150, 110, 255)


def _load_estate_renderer():
    if not ESTATE_ICON_MODULE.exists():
        raise SystemExit(
            f"the estate's icon renderer is missing: {ESTATE_ICON_MODULE}\n"
            "prototype2's icon is a recolour of it and has no drawing code of its own."
        )
    spec = importlib.util.spec_from_file_location("estate_make_icon", ESTATE_ICON_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    estate = _load_estate_renderer()
    estate.ACCENT = ACCENT_P2

    pngs = [(n, estate._png(n, estate._render(n))) for n in estate.SIZES]

    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = b""
    offset = 6 + 16 * len(pngs)
    body = b""
    for n, png in pngs:
        entries += struct.pack(
            "<BBBBHHII",
            0 if n >= 256 else n,
            0 if n >= 256 else n,
            0,
            0,
            1,
            32,
            len(png),
            offset,
        )
        body += png
        offset += len(png)

    OUT.write_bytes(header + entries + body)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes {list(estate.SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
