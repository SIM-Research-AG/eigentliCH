"""Author the Life Balance Sheet desktop icon (multi-resolution .ico).

A balance scale on a teal->emerald gradient tile: reads as both "balance" and
"balance sheet". Two artworks are drawn -- a detailed one for >=48px and a
heavier, simplified one for the 16/24/32px sizes where thin strokes turn to mush.
Everything is drawn supersampled and downsampled with LANCZOS for clean edges.
"""
from PIL import Image, ImageDraw, ImageFilter

C_TOP = (56, 220, 196)   # bright teal
C_BOT = (4, 72, 56)      # deep emerald
WHITE = (255, 255, 255, 255)

SS = 8                   # supersample factor


def gradient_tile(n, detailed, radius_frac=0.22):
    """Rounded-square tile with a diagonal gradient + restrained top-left sheen."""
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = img.load()
    denom = max(1, 2 * (n - 1))
    for y in range(n):
        for x in range(n):
            t = (x + y) / denom
            px[x, y] = (
                round(C_TOP[0] + (C_BOT[0] - C_TOP[0]) * t),
                round(C_TOP[1] + (C_BOT[1] - C_TOP[1]) * t),
                round(C_TOP[2] + (C_BOT[2] - C_TOP[2]) * t),
                255,
            )

    # sheen in the upper-left: kept low so the gradient keeps its saturation
    sheen = Image.new("L", (n, n), 0)
    ImageDraw.Draw(sheen).ellipse(
        [-0.40 * n, -0.70 * n, 0.88 * n, 0.36 * n], fill=30
    )
    sheen = sheen.filter(ImageFilter.GaussianBlur(n * 0.13))
    img = Image.composite(Image.new("RGBA", (n, n), (255, 255, 255, 255)), img, sheen)

    # full-bleed at small sizes: an inset + hairline only turns to mush at 16px
    inset = (0.02 if detailed else 0.0) * n
    r = radius_frac * n
    box = [inset, inset, n - 1 - inset, n - 1 - inset]
    if detailed:
        ImageDraw.Draw(img).rounded_rectangle(
            box, radius=r, outline=(255, 255, 255, 60), width=max(1, int(n * 0.006))
        )

    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=r, fill=255)
    img.putalpha(mask)
    return img


def draw_scale(d, n, detailed):
    """Balance scale, normalized coords scaled by n."""
    def s(v):
        return v * n

    beam_y = 0.345 if detailed else 0.315
    beam_x0, beam_x1 = 0.155, 0.845
    beam_th = 0.052 if detailed else 0.068
    # a narrower post at small sizes keeps air between post and pans
    post_w = 0.056 if detailed else 0.062
    # small sizes: hang the pans lower so beam/hanger/pan don't fuse into a blob
    pan_top = 0.500 if detailed else 0.510
    pan_half = 0.135 if detailed else 0.132
    pan_depth = 0.115 if detailed else 0.095
    hang_w = 0.022 if detailed else 0.028

    cx = 0.5
    beam_bot = beam_y + beam_th / 2

    # hanger loop above the beam -- a detail only large sizes can hold
    if detailed:
        r = 0.052
        d.ellipse(
            [s(cx - r), s(0.268 - r), s(cx + r), s(0.268 + r)],
            outline=WHITE, width=max(1, int(s(0.026))),
        )

    # pans + their hangers
    for pcx in (0.25, 0.75):
        d.line([s(pcx), s(beam_bot), s(pcx), s(pan_top)], fill=WHITE,
               width=max(1, int(s(hang_w))))
        d.pieslice(
            [s(pcx - pan_half), s(pan_top - pan_depth),
             s(pcx + pan_half), s(pan_top + pan_depth)],
            0, 180, fill=WHITE,
        )

    # beam (level == balanced)
    d.rounded_rectangle(
        [s(beam_x0), s(beam_y - beam_th / 2), s(beam_x1), s(beam_y + beam_th / 2)],
        radius=s(beam_th / 2), fill=WHITE,
    )

    # post
    d.rectangle([s(cx - post_w / 2), s(beam_y), s(cx + post_w / 2), s(0.742)], fill=WHITE)

    # pedestal: flared foot + bar (tightened at small sizes)
    foot = 0.660 if detailed else 0.630
    d.polygon(
        [(s(0.435), s(0.742)), (s(0.565), s(0.742)),
         (s(foot), s(0.792)), (s(1 - foot), s(0.792))],
        fill=WHITE,
    )
    bar_th = 0.044 if detailed else 0.050
    bar_x = 0.300 if detailed else 0.325
    d.rounded_rectangle(
        [s(bar_x), s(0.792), s(1 - bar_x), s(0.792 + bar_th)],
        radius=s(bar_th / 2), fill=WHITE,
    )


def render(size, detailed):
    n = size * SS
    tile = gradient_tile(n, detailed)

    # drop a soft dark shadow under the glyph for depth, then the glyph itself
    if detailed:
        sh = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        draw_scale(ImageDraw.Draw(sh), n, detailed)
        alpha = sh.split()[3].filter(ImageFilter.GaussianBlur(n * 0.012))
        shadow = Image.new("RGBA", (n, n), (2, 44, 40, 255))
        shadow.putalpha(alpha.point(lambda v: int(v * 0.45)))
        tile.alpha_composite(shadow, (0, int(n * 0.014)))

    glyph = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw_scale(ImageDraw.Draw(glyph), n, detailed)
    tile.alpha_composite(glyph)

    # re-clip: shadow/glyph must not bleed past the rounded tile
    inset = (0.02 if detailed else 0.0) * n
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, n - 1 - inset, n - 1 - inset], radius=0.22 * n, fill=255,
    )
    tile.putalpha(Image.composite(tile.split()[3], Image.new("L", (n, n), 0), mask))

    return tile.resize((size, size), Image.LANCZOS)


SIZES = [16, 24, 32, 48, 64, 128, 256]
frames = [render(sz, detailed=sz >= 48) for sz in SIZES]

import sys
ico_path, png_path = sys.argv[1], sys.argv[2]
frames[-1].save(ico_path, format="ICO",
                sizes=[(s, s) for s in SIZES],
                append_images=frames[:-1])

# preview strip on a neutral backdrop, small sizes pixel-doubled to be inspectable
scale = {16: 8, 24: 6, 32: 5, 48: 3, 64: 3, 128: 2, 256: 1}
pad = 16
widths = [SIZES[i] * scale[SIZES[i]] for i in range(len(SIZES))]
W = sum(widths) + pad * (len(SIZES) + 1)
H = max(widths) + pad * 2
strip = Image.new("RGBA", (W, H), (130, 136, 148, 255))
x = pad
for img, sz in zip(frames, SIZES):
    big = img.resize((sz * scale[sz], sz * scale[sz]), Image.NEAREST)
    strip.alpha_composite(big, (x, pad))
    x += big.width + pad
strip.convert("RGB").save(png_path)
print("wrote", ico_path)
print("wrote", png_path)
