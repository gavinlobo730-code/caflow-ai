#!/usr/bin/env python3
"""Derive the hero's full-width deep-space field from the supplied artwork.

WHY THIS EXISTS. `public/hero/earth-network.webp` is the owner's own artwork and
it covers the right 62% of the hero. Everything left of it was a flat #010918,
so on a wide screen the composition read as half a picture on half a page.
Owner review, 17-09-2026: *"can we you know create the background image a bit
more universy like see the image is already right but only the right side it is
but the left is blank so i was thinking that the whole screen gets that look"*,
and then, on scope: *"there should be only one page and the page with the hero
that is the original page"* — the hero, not the site.

WHY NOT DRAW IT. The same brief that supplied the artwork says: *"Do not attempt
to recreate the globe, city lights, starfield, or card artwork with SVG, Canvas,
or CSS shapes."* A CSS or canvas starfield would be exactly that. So every pixel
this script emits is DERIVED FROM THE ARTWORK: the colour field is the artwork's
own palette and the stars are the artwork's own stars, moved.

WHY NOT TILE OR MIRROR IT. The obvious cheap version — mirror a patch of deep
space and repeat it — is detectable the moment anybody looks, because the eye
finds repeated constellations immediately. Instead:

the STARS are real star sprites cut out of the artwork's cleanest deep-space
tiles (chosen by measurement: darkest mean luminance, no large structures) and
then scattered at NEW positions with a fixed seed. Re-using a sprite is not the
same as repeating a pattern: each star is one of theirs, and no two are in the
same relative arrangement they were in.

WHY THE COLOUR WASH IS NOT IN THIS FILE, after two attempts that put it here.
Both were the artwork reduced to a tiny flipped thumbnail and scaled back up,
and both failed in ways worth not repeating. At 44x34 and 30% strength the
artwork's own bright limb SURVIVED the reduction as a diagonal streak across the
hero — which is a galaxy arm whatever it was derived from, and §12 of the brief
is explicit: "NO LARGE PURPLE GALAXY. This is explicitly prohibited." At 18x14
and 15% it had no structure left and then it BANDED: a smooth gradient held at
15% spans about twenty of the 256 levels available, so every step is wide enough
to see, and it rendered as concentric contour rings down the whole left of the
hero. Dithering cured the rings and took the file from 19KB to 194KB, because
noise is the one thing image compression can do nothing with.

So the wash is two CSS radial gradients in Hero.tsx at colours SAMPLED from this
artwork — #0c254b haze over #010817 deep space, each the mean of the artwork's
own pixels in that luminance band — and this file emits only the stars. A
gradient is not one of the four things the brief says not to recreate: the
globe, the city lights, the starfield and the cards are all still pixels the
owner drew. The browser also renders a gradient in more than 8-bit precision,
so it does not band, and it costs no bytes.

THE FADES ARE THE POINT OF THE FILE, not decoration. The field has to disappear
where the real artwork begins, or two overlapping star populations produce a
visible density step down the middle of the hero; and it has to fade at the top
and bottom or it draws a line against the section it sits in. Both live in the
alpha channel here rather than in CSS so the browser composites one image.

RUNNING IT. One-off; the output is committed. Needs Pillow.

    python3 scripts/build-space-field.py

Anything that changes `earth-network.webp` should re-run it, since the palette
and the stars both come from that file.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
ART = HERE.parent / "public" / "hero" / "earth-network.webp"
OUT = HERE.parent / "public" / "hero" / "space-field.webp"

# 1920x1080 so a 1080p screen shows it at its own resolution and the star
# points stay points. Larger buys nothing: it is behind the real artwork and
# upscaling a star field is what turns stars into smudges.
W, H = 1920, 1080

# Tiles of the artwork that are deep space and nothing else, at 96px, measured
# by mean luminance and bright-pixel count over the whole image. Each is dark
# (mean under 16 of 255) and carries stars rather than structure. Deliberately
# none from x < 192: the artwork's own left edge is a transparency ramp, so a
# patch taken there is half-faded and its stars are dimmer than they look.
CLEAN_TILES = ((384, 480), (288, 384), (192, 672), (192, 0), (960, 576))
TILE = 96

STAR_THRESHOLD = 96  # luminance at which a pixel is a star rather than dust
SEED = 20260917

# Two passes, because the left of the hero is where the HEADLINE is.
# `SPREAD` is a thin scatter across the whole visible band so the far left is
# not empty — the complaint this asset answers — and `CLUSTER` is the denser
# population in the gap between the copy's right edge and the artwork, where
# nothing is competing with it. One uniform density either leaves the left bare
# or puts stars behind white type and takes contrast off it.
SPREAD_COUNT = 240
CLUSTER_COUNT = 520


def _sprites(art: Image.Image) -> list[Image.Image]:
    """Cut every star out of the clean tiles, brightest first.

    A sprite is a square around a local maximum rather than a single pixel,
    because the artwork's stars have a glow and a bare pixel reads as dirt on
    the screen. The radius grows with brightness for the same reason: that is
    how the artwork draws them.
    """
    lum = art.convert("L")
    out: list[Image.Image] = []
    seen: set[tuple[int, int]] = set()
    for tx, ty in CLEAN_TILES:
        px = lum.load()
        for y in range(ty, ty + TILE):
            for x in range(tx, tx + TILE):
                v = px[x, y]
                if v < STAR_THRESHOLD:
                    continue
                # One sprite per star: skip anything adjacent to one taken.
                if any((x // 4, y // 4) == s for s in seen):
                    continue
                # A local maximum, so a wide glow is cut once around its core.
                if any(
                    px[min(max(x + dx, 0), art.width - 1), min(max(y + dy, 0), art.height - 1)] > v
                    for dx in (-1, 0, 1)
                    for dy in (-1, 0, 1)
                    if (dx, dy) != (0, 0)
                ):
                    continue
                seen.add((x // 4, y // 4))
                r = 3 if v < 150 else (5 if v < 210 else 7)
                box = (x - r, y - r, x + r + 1, y + r + 1)
                if box[0] < 0 or box[1] < 0 or box[2] > art.width or box[3] > art.height:
                    continue
                out.append(_as_light(art.crop(box)))
    # DIMMEST FIRST, and the order is load-bearing: the placement below picks
    # near index 0 most of the time, so sorting brightest-first fills the hero
    # with the artwork's handful of showpiece stars and the field reads as
    # tinsel. A real sky is mostly faint.
    out.sort(key=_brightness)
    return out


def _as_light(sprite: Image.Image) -> Image.Image:
    """Carry the star's LIGHT and not the square it was cut out of.

    The artwork is opaque everywhere past its left fade, so a crop of it is an
    opaque tile of deep space with a star in the middle. Compositing that over
    the nebula pastes the tile as well — visible as small dark squares punched
    through the colour field, which is exactly what the first render did.

    Taking the alpha FROM the luminance makes the surround transparent in
    proportion to how dark it is, so only the star and its own glow survive and
    it lands on whatever is behind it. The curve is squared because a linear
    ramp leaves a faint grey halo the size of the crop."""
    rgb = sprite.convert("RGB")
    lum = rgb.convert("L")
    alpha = Image.eval(lum, lambda v: min(255, int((v / 255.0) ** 1.5 * 255 * 1.7)))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _brightness(sprite: Image.Image) -> int:
    """Mean luminance of a sprite, for ordering them dim-to-bright."""
    px = sprite.convert("L").resize((1, 1), Image.Resampling.BILINEAR).load()
    return px[0, 0]


def _fade() -> Image.Image:
    """Where the field is allowed to be seen.

    Horizontally it is full strength to x=0.30W and gone by x=0.72W, so it is
    already absent under the artwork's own opaque half; the two star
    populations therefore never overlap and there is no density step. The last
    2% at the left edge and the first and last 6% vertically come off so the
    image cannot draw an edge against the section behind it.
    """
    mask = Image.new("L", (W, H), 0)
    px = mask.load()
    for x in range(W):
        fx = x / W
        if fx < 0.02:
            h = fx / 0.02
        elif fx < 0.30:
            h = 1.0
        elif fx < 0.72:
            h = 1.0 - (fx - 0.30) / 0.42
        else:
            h = 0.0
        h = h * h  # ease out, so the tail disappears rather than stopping
        for y in range(H):
            fy = y / H
            if fy < 0.06:
                v = fy / 0.06
            elif fy > 0.94:
                v = (1.0 - fy) / 0.06
            else:
                v = 1.0
            px[x, y] = int(255 * h * v)
    return mask


def main() -> None:
    art = Image.open(ART).convert("RGBA")
    random.seed(SEED)

    field = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sprites = _sprites(art)
    if len(sprites) < 40:
        raise SystemExit(
            f"only {len(sprites)} star sprites came out of the artwork; the "
            f"clean tiles or the threshold need re-measuring before this asset "
            f"can be trusted to look like the same picture"
        )

    def place(count: int, lo: float, hi: float, dimmest_only: bool) -> None:
        pool = sprites[: max(3, len(sprites) // 2)] if dimmest_only else sprites
        for _ in range(count):
            s = pool[min(int(abs(random.gauss(0, 0.40)) * len(pool)), len(pool) - 1)]
            x = int((lo + (hi - lo) * random.random()) * W)
            y = random.randrange(H)
            field.alpha_composite(s, (min(x, W - s.width), min(y, H - s.height)))

    # The spread reaches x=0.04W, which is under the headline, so it draws only
    # from the dimmest half — the far left has to stop being empty without
    # taking contrast off white type sitting on it.
    place(SPREAD_COUNT, 0.04, 0.74, dimmest_only=True)
    # The cluster sits in the gap between the copy's right edge (0.32W at 1920)
    # and the artwork's own opaque half, where nothing competes with it.
    place(CLUSTER_COUNT, 0.30, 0.74, dimmest_only=False)

    # MULTIPLY, never `putalpha`. Each star already carries its own alpha — the
    # whole point of `_as_light` — and replacing the channel would make the
    # transparent space between them opaque wherever the fade says "visible",
    # which is a dark rectangle over two thirds of the hero.
    field.putalpha(ImageChops.multiply(field.split()[3], _fade()))
    field.save(OUT, "WEBP", quality=92, method=6)
    print(f"{OUT.relative_to(HERE.parent)}  {W}x{H}  {OUT.stat().st_size // 1024} KB  "
          f"from {len(sprites)} star sprites")


if __name__ == "__main__":
    main()
