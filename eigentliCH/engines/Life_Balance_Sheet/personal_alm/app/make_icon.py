"""Generate icon.ico for the desktop shortcut — a small teal emblem with three
ascending bars (a balance sheet growing). Pure numpy + struct, no image libs.

    python -m personal_alm.app.make_icon
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

TEAL = (107, 110, 15)     # BGR of #0F6E6B
OCHRE = (42, 135, 192)    # BGR of #C0872A
WHITE = (250, 250, 250)


def _draw(S: int) -> np.ndarray:
    """Return an (S, S, 4) BGRA image, top row first."""
    img = np.zeros((S, S, 4), dtype=np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2], img[:, :, 3] = (*TEAL, 255)

    base = int(round(S * 0.80))
    # three ascending white bars
    heights = (0.34, 0.52, 0.70)
    centers = (0.30, 0.50, 0.70)
    bw = max(1, int(round(S * 0.15)))
    for cx, h in zip(centers, heights):
        x0 = int(round(S * cx - bw / 2))
        top = base - int(round(S * h))
        img[max(0, top):base, max(0, x0):x0 + bw] = (*WHITE, 255)
    # ochre baseline
    img[base:base + max(1, int(round(S * 0.05))), int(S * 0.14):int(S * 0.86)] = (*OCHRE, 255)
    return img


def _image_blob(S: int) -> bytes:
    img = _draw(S)
    # BITMAPINFOHEADER: height doubled for XOR+AND masks.
    header = struct.pack("<IiiHHIIiiII", 40, S, S * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(S - 1, -1, -1):           # bottom-up
        for x in range(S):
            b, g, r, a = img[y, x]
            xor += bytes((b, g, r, a))
    and_row = ((S + 31) // 32) * 4
    and_mask = bytes(and_row * S)             # all zero → alpha governs
    return header + bytes(xor) + and_mask


def make_icon(path: Path | None = None) -> Path:
    path = path or (Path(__file__).parent / "icon.ico")
    sizes = (16, 32, 48)
    blobs = [_image_blob(s) for s in sizes]
    offset = 6 + 16 * len(sizes)
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for s, blob in zip(sizes, blobs):
        w = 0 if s == 256 else s
        out += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for blob in blobs:
        out += blob
    path.write_bytes(out)
    return path


if __name__ == "__main__":
    p = make_icon()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
