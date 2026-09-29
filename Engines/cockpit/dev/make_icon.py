"""Writes src/cockpit/static/cockpit.ico (and cockpit.png) with the standard library only.

A rounded blue square with three rising bars and an accent dot: a plain "dashboard" sign.
Run once after changing the design: ``python dev/make_icon.py``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "cockpit" / "static"
BG, FG, ACCENT = (24, 79, 149), (255, 255, 255), (235, 104, 52)
SS = 4  # supersampling per axis


def inside_rounded(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def shade(u: float, v: float) -> tuple[int, int, int, int]:
    """Colour at unit coordinates (0..1), with alpha."""
    if not inside_rounded(u, v, 0.02, 0.02, 0.98, 0.98, 0.2):
        return (0, 0, 0, 0)
    for x0, top in ((0.20, 0.58), (0.42, 0.42), (0.64, 0.26)):
        if inside_rounded(u, v, x0, top, x0 + 0.15, 0.80, 0.03):
            return (*FG, 255)
    if (u - 0.78) ** 2 + (v - 0.18) ** 2 <= 0.075 ** 2:
        return (*ACCENT, 255)
    return (*BG, 255)


def render(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter type none
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    c = shade((x + (sx + 0.5) / SS) / size, (y + (sy + 0.5) / SS) / size)
                    a = c[3]
                    acc[0] += c[0] * a
                    acc[1] += c[1] * a
                    acc[2] += c[2] * a
                    acc[3] += a
            n = SS * SS
            alpha = acc[3] / n
            rgb = [int(round(acc[i] / acc[3])) if acc[3] else 0 for i in range(3)]
            row += bytes([*rgb, int(round(alpha))])
        rows.append(bytes(row))
    return png(size, b"".join(rows))


def png(size: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return head + entries + blobs


if __name__ == "__main__":
    images = [(s, render(s)) for s in (16, 24, 32, 48, 64, 256)]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cockpit.ico").write_bytes(ico(images))
    (OUT / "cockpit.png").write_bytes(images[-1][1])
    print(f"wrote {OUT / 'cockpit.ico'}")
