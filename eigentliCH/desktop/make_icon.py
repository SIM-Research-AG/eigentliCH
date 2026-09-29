"""Generate `andersCH.ico` — the desktop icon. Standard library only.

Run once; the `.ico` is committed. Regenerate with:

    python desktop/make_icon.py

**Why hand-rolled rather than a system icon or a dependency.** Pointing a shortcut at `shell32.dll,13` gives a
generic folder and teaches the user nothing; adding Pillow to the root environment breaks the no-new-dependency
rule the subprocess bridge depends on. PNG needs only `zlib` and `struct`, both stdlib, and Windows has accepted
PNG-in-ICO since Vista — so a real icon costs nothing but this file.

**The mark** is a rising trajectory over a dark ground: the one picture that is actually about this model, whose
whole subject is a path through time rather than a balance at a point. Four sizes, because Windows picks per
context (16 in the taskbar, 32 on the desktop, 48 in dialogs, 256 in large-icon view) and scaling one badly is
what makes an icon look amateur.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "andersCH.ico"
SIZES = (16, 32, 48, 256)

# The page's own palette, so the icon and the program look like one thing.
BG = (20, 18, 37, 255)        # deep indigo, as on the onboarding page
LINE = (245, 243, 255, 255)   # near-white
ACCENT = (122, 162, 247, 255)  # the accent blue


def _blend(dst: tuple, src: tuple, a: float) -> tuple:
    """Composite `src` over `dst` at coverage `a`. Anti-aliasing is the difference between a drawn icon and a
    pixelated one, and coverage is cheap to compute analytically for the shapes used here."""
    a = max(0.0, min(1.0, a))
    return tuple(round(d + (s - d) * a) for d, s in zip(dst[:3], src[:3])) + (255,)


def _rounded_mask(x: float, y: float, n: int) -> float:
    """Coverage of a rounded square at pixel centre (x, y), in [0, 1]."""
    r = n * 0.22
    cx = min(max(x, r), n - r)
    cy = min(max(y, r), n - r)
    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    return max(0.0, min(1.0, (r - d) + 0.5)) if (x < r or x > n - r) and (y < r or y > n - r) else 1.0


def _curve_y(t: float) -> float:
    """The trajectory, in unit coordinates: slow, then steep, then flattening — an S-curve, which is the shape
    the model's capitals actually follow."""
    return t * t * (3 - 2 * t)  # smoothstep


def _render(n: int) -> bytes:
    """One RGBA image of side `n`, as raw rows."""
    pad = n * 0.16
    span = n - 2 * pad
    thick = max(1.0, n * 0.085)

    # Sample the curve densely so distance-to-curve is accurate enough for anti-aliasing.
    pts = []
    steps = max(64, n * 4)
    for i in range(steps + 1):
        t = i / steps
        pts.append((pad + t * span, (n - pad) - _curve_y(t) * span))

    rows = bytearray()
    for py in range(n):
        for px in range(n):
            x, y = px + 0.5, py + 0.5
            cov = _rounded_mask(x, y, n)
            if cov <= 0.0:
                rows += bytes((0, 0, 0, 0))
                continue
            col = BG
            # Distance to the polyline, for the stroke.
            best = 1e9
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                dx, dy = x2 - x1, y2 - y1
                L2 = dx * dx + dy * dy
                t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
                d = ((x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2) ** 0.5
                if d < best:
                    best = d
            stroke = max(0.0, min(1.0, (thick / 2 - best) + 0.5))
            if stroke > 0:
                col = _blend(col, LINE, stroke)
            # A dot at the end of the path: where the household is heading.
            ex, ey = pts[-1]
            dr = ((x - ex) ** 2 + (y - ey) ** 2) ** 0.5
            dot = max(0.0, min(1.0, (thick * 0.95 - dr) + 0.5))
            if dot > 0:
                col = _blend(col, ACCENT, dot)
            rows += bytes(col[:3]) + bytes((round(255 * cov),))
    return bytes(rows)


def _png(n: int, raw: bytes) -> bytes:
    """Minimal RGBA PNG. `zlib` does the only hard part."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    scan = bytearray()
    stride = n * 4
    for y in range(n):
        scan.append(0)                      # filter: none
        scan += raw[y * stride:(y + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(scan), 9))
            + chunk(b"IEND", b""))


def main() -> int:
    pngs = [(n, _png(n, _render(n))) for n in SIZES]
    # ICO container: header, one directory entry per image, then the image data.
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = bytearray(), bytearray()
    for n, data in pngs:
        entries += struct.pack("<BBBBHHII",
                               0 if n >= 256 else n,   # 0 means 256 in the ICO format
                               0 if n >= 256 else n,
                               0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    OUT.write_bytes(header + bytes(entries) + bytes(blobs))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes {list(SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
