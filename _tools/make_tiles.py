"""Generate Dawnline's BUILTIN art set: media/tileart/builtin/ (sheet.png + manifest.json).

The mission names shared keys only (`fig:crew_eva`, `prop:hauler`, ground looks like
`dirt`); an art set
says what they look like, and a media pack can redraw any of them (see
`sbs_utils/procedural/tilemap_art.py`). This is the set the mission always has, so it runs
with no pack installed: every key the mission uses must be here.

Procedural stand-in art, drawn well enough to read at a glance: tileable ground in a few
variants per kind (so a field does not repeat in a grid), shaded top-down figures and
props with a drop shadow, lit from the top left, and the hint badges the map draws over
anything still worth a look. Everything is drawn at 4x and shrunk, so edges are smooth.

KEYS below is the whole set: each logical key -> the drawing it uses (several keys may
share one: every named colonist is the colonist figure with a tint of its own), and
GROUND says which keys dress which tile kind. The packer lays the drawings out and writes
the manifest, so nothing else keeps positions in step.

Two rules the engine imposes:
* A figure is TINTED by multiplying (crew get a color each), so anything tinted is drawn
  light - white multiplies to the tint, and shading survives as darker tint.
* Ground of one kind meets its own variants, so a variant only changes DETAILS kept away
  from the cell edge; the base texture is the same tileable noise in every variant.

Dev tool: needs Pillow and numpy.  python _tools/make_tiles.py
"""
import json
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "media", "tileart", "builtin")
COLS = 16
C = 128                 # cell, in the atlas
S = 4                   # supersampling
B = C * S               # cell, while drawing
LIGHT = np.array([-0.45, -0.55, 0.70])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


# --- noise and color -------------------------------------------------------------------

def periodic_noise(period, seed, size=B):
    """Value noise that tiles: a random grid, wrapped 3x3, smoothly enlarged, center cut."""
    rng = np.random.default_rng(seed)
    grid = (rng.random((period, period)) * 255).astype(np.uint8)
    big = Image.fromarray(np.tile(grid, (3, 3))).resize((size * 3, size * 3), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32)[size:2 * size, size:2 * size] / 255.0


def fbm(seed, periods=(3, 6, 12, 24), gain=0.55):
    total, amp, norm = 0.0, 1.0, 0.0
    for i, p in enumerate(periods):
        total = total + amp * periodic_noise(p, seed * 31 + i)
        norm += amp
        amp *= gain
    n = total / norm
    return (n - n.min()) / max(1e-6, n.max() - n.min())


def ramp(n, *stops):
    """Map 0..1 through color stops -> HxWx3."""
    stops = [np.array(s, dtype=np.float32) for s in stops]
    k = len(stops) - 1
    t = np.clip(n, 0, 1) * k
    i = np.minimum(t.astype(int), k - 1)
    f = (t - i)[..., None]
    lo = np.stack(stops)[i]
    hi = np.stack(stops)[i + 1]
    return lo * (1 - f) + hi * f


def to_img(rgb, alpha=None):
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if alpha is None:
        alpha = np.full(rgb.shape[:2], 255, np.uint8)
    else:
        alpha = np.clip(alpha * 255 if alpha.dtype != np.uint8 else alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def shade(c, k):
    return tuple(int(max(0, min(255, v * k))) for v in c[:3]) + tuple(c[3:])


def blank():
    return Image.new("RGBA", (B, B), (0, 0, 0, 0))


# --- lit shapes --------------------------------------------------------------------------

YY, XX = np.mgrid[0:B, 0:B].astype(np.float32)


def dome(cx, cy, rx, ry, color, spec=0.35, rot=0.0, flat=0.0):
    """An ellipse lit as a dome from the top left. `flat` flattens the top (0..1)."""
    cs, sn = math.cos(rot), math.sin(rot)
    dx, dy = XX - cx, YY - cy
    u = (dx * cs + dy * sn) / rx
    v = (-dx * sn + dy * cs) / ry
    r2 = u * u + v * v
    inside = r2 <= 1.0
    z = np.sqrt(np.clip(1.0 - r2, 0, 1))
    # normal back in screen space
    nx = (u * cs - v * sn)
    ny = (u * sn + v * cs)
    nz = z + flat
    ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    lam = np.clip((nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / ln, 0, 1)
    k = 0.35 + 0.85 * lam
    rgb = np.array(color[:3], np.float32)[None, None, :] * k[..., None]
    hl = np.clip(lam, 0, 1) ** 18 * spec * 255
    rgb = rgb + hl[..., None]
    edge = np.clip((1.0 - np.sqrt(r2)) * max(rx, ry) / (1.5 * S), 0, 1)
    alpha = np.where(inside, edge, 0.0)
    return to_img(rgb, alpha)


def poly_layer(points, color, bevel=True, width=None):
    """A flat polygon with a lit top-left rim and a dark bottom-right rim."""
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon(points, fill=color)
    if bevel:
        w = width or 3 * S
        n = len(points)
        for i in range(n):
            a, b = points[i], points[(i + 1) % n]
            ex, ey = b[0] - a[0], b[1] - a[1]
            # outward normal for a clockwise polygon in screen coords
            nx, ny = ey, -ex
            ln = math.hypot(nx, ny) or 1
            lit = (nx * LIGHT[0] + ny * LIGHT[1]) / ln
            edge = shade(color, 1.35) if lit < 0 else shade(color, 0.55)
            d.line([a, b], fill=edge, width=w)
    return img


def shadow_of(layer, dx=5, dy=7, blur=5, strength=0.55):
    a = np.asarray(layer)[..., 3].astype(np.float32) / 255.0
    sh = Image.fromarray((a * 255 * strength).astype(np.uint8))
    sh = sh.filter(ImageFilter.GaussianBlur(blur * S))
    out = blank()
    out.paste(Image.new("RGBA", (B, B), (0, 0, 0, 255)), (dx * S, dy * S), sh)
    return out


def glow(cx, cy, r, color, strength=1.0):
    d = np.sqrt((XX - cx) ** 2 + (YY - cy) ** 2) / r
    a = np.clip(1.0 - d, 0, 1) ** 2 * strength
    rgb = np.broadcast_to(np.array(color[:3], np.float32), (B, B, 3))
    return to_img(rgb.copy(), a)


def stack(*layers):
    out = blank()
    for layer in layers:
        out = Image.alpha_composite(out, layer)
    return out


def with_shadow(*layers, **kw):
    body = stack(*layers)
    return Image.alpha_composite(shadow_of(body, **kw), body)


def drawn(fn):
    img = blank()
    fn(ImageDraw.Draw(img), img)
    return img


# --- ground ------------------------------------------------------------------------------

def speckle(img, rng, n, colors, rmin, rmax, margin=14):
    """Pebbles: little lit domes kept off the edges (variants must meet seamlessly)."""
    layers = []
    for _ in range(n):
        r = rng.uniform(rmin, rmax) * S
        cx = rng.uniform(margin * S + r, B - margin * S - r)
        cy = rng.uniform(margin * S + r, B - margin * S - r)
        col = colors[rng.randrange(len(colors))]
        layers.append(dome(cx, cy, r, r * rng.uniform(0.7, 1.0), col, spec=0.1,
                           rot=rng.uniform(0, 3.14)))
    if layers:
        pebbles = stack(*layers)
        img = Image.alpha_composite(img, shadow_of(pebbles, 1, 2, 1, 0.5))
        img = Image.alpha_composite(img, pebbles)
    return img


def ground_dust(v):
    # Fine octaves only, low contrast: a coarse one repeats cell to cell as banding.
    n = fbm(1, periods=(8, 16, 32), gain=0.7)
    img = to_img(ramp(n, (88, 70, 52), (104, 84, 62), (118, 96, 72)))
    rng = random.Random(100 + v)
    return speckle(img, rng, 7 + v * 2, [(120, 100, 80), (90, 74, 58), (140, 118, 92)], 2, 5)


def ground_scrub(v):
    n = fbm(2, periods=(8, 16, 32), gain=0.7)
    img = to_img(ramp(n, (78, 72, 48), (92, 86, 58), (104, 98, 66)))
    rng = random.Random(200 + v)
    d = ImageDraw.Draw(img)
    for _ in range(5 + v * 2):
        cx = rng.uniform(22, C - 22) * S
        cy = rng.uniform(22, C - 22) * S
        base = rng.choice([(96, 118, 58), (120, 130, 60), (80, 104, 56)])
        for k in range(14):
            a = rng.uniform(0, math.tau)
            ln = rng.uniform(5, 13) * S
            d.line([(cx, cy), (cx + math.cos(a) * ln, cy + math.sin(a) * ln)],
                   fill=shade(base, rng.uniform(0.8, 1.3)), width=2 * S)
    return img


def ground_salt(v):
    n = fbm(3, periods=(4, 8, 16))
    img = to_img(ramp(n, (184, 178, 164), (206, 200, 186), (224, 220, 208)))
    rng = random.Random(300 + v)
    d = ImageDraw.Draw(img)
    # Crack polygons: a jittered lattice; edge points pinned so tiles meet.
    pts = {}
    for gy in range(4):
        for gx in range(4):
            jx = 0 if gx in (0, 3) else rng.uniform(-10, 10)
            jy = 0 if gy in (0, 3) else rng.uniform(-10, 10)
            pts[gx, gy] = ((gx * C / 3 + jx) * S, (gy * C / 3 + jy) * S)
    for gy in range(4):
        for gx in range(4):
            for ox, oy in ((1, 0), (0, 1)):
                if (gx + ox, gy + oy) in pts:
                    a, b = pts[gx, gy], pts[gx + ox, gy + oy]
                    if (ox and gy in (0, 3)) or (oy and gx in (0, 3)):
                        continue            # no crack along the cell border
                    d.line([a, b], fill=(160, 150, 136, 255), width=3 * S)
                    d.line([(a[0] - S, a[1] - S), (b[0] - S, b[1] - S)],
                           fill=(236, 232, 222, 255), width=S)
    return img


def ground_path(v):
    n = fbm(4, periods=(8, 16, 32), gain=0.7)
    img = to_img(ramp(n, (126, 106, 80), (138, 118, 90), (150, 130, 100)))
    rng = random.Random(400 + v)
    d = ImageDraw.Draw(img)
    # Packed and lighter than dust, no direction: a path runs any way on the map.
    return speckle(img, rng, 5 + v * 2, [(160, 138, 108), (118, 98, 74), (150, 146, 136)], 2, 4)


def ground_floor(v):
    """Colony prefab floor: large panels, seams, rivets."""
    n = fbm(5, periods=(8, 16))
    img = to_img(ramp(n, (82, 86, 92), (96, 100, 106)))
    d = ImageDraw.Draw(img)
    for p in (0, B // 2):
        d.line([(p, 0), (p, B)], fill=(58, 60, 66, 255), width=2 * S)
        d.line([(0, p), (B, p)], fill=(58, 60, 66, 255), width=2 * S)
        d.line([(p + 2 * S, 0), (p + 2 * S, B)], fill=(118, 122, 128, 255), width=S)
        d.line([(0, p + 2 * S), (B, p + 2 * S)], fill=(118, 122, 128, 255), width=S)
    for qx in (0, B // 2):
        for qy in (0, B // 2):
            for rx, ry in ((10, 10), (54, 10), (10, 54), (54, 54)):
                x, y = qx + rx * S, qy + ry * S
                d.ellipse([x - 2 * S, y - 2 * S, x + 2 * S, y + 2 * S], fill=(126, 130, 136, 255))
    if v == 1:
        d.line([(20 * S, 90 * S), (60 * S, 110 * S)], fill=(70, 72, 78, 255), width=S)
    return img


def ground_deck(v):
    """Skaraan deck: dark grating."""
    img = to_img(ramp(fbm(6), (46, 40, 40), (62, 54, 52)))
    d = ImageDraw.Draw(img)
    step = 16 * S
    for i in range(0, B, step):
        d.line([(i, 0), (i, B)], fill=(30, 26, 26, 255), width=3 * S)
        d.line([(0, i), (B, i)], fill=(30, 26, 26, 255), width=3 * S)
        d.line([(i + 3 * S, 0), (i + 3 * S, B)], fill=(80, 70, 66, 255), width=S)
    return img


def ground_cave(v):
    n = fbm(7)
    img = to_img(ramp(n, (38, 32, 30), (56, 46, 42), (72, 60, 54)))
    rng = random.Random(700 + v)
    img = speckle(img, rng, 6 + v * 2, [(70, 58, 52), (50, 42, 40)], 2, 6)
    d = ImageDraw.Draw(img)
    for _ in range(3 + v * 2):           # mineral glints
        x, y = rng.uniform(16, C - 16) * S, rng.uniform(16, C - 16) * S
        d.ellipse([x - S, y - S, x + S, y + S], fill=(200, 150, 240, 255))
    return img


def ground_glyphfloor(v):
    img = to_img(ramp(fbm(8, periods=(6, 12)), (40, 50, 62), (54, 66, 80)))
    d = ImageDraw.Draw(img)
    d.rectangle([2 * S, 2 * S, B - 2 * S, B - 2 * S], outline=(30, 38, 48, 255), width=3 * S)
    c = B // 2
    for r in (20, 34):
        d.ellipse([c - r * S, c - r * S, c + r * S, c + r * S], outline=(70, 150, 170, 255),
                  width=2 * S)
    for k in range(6):
        a = k * math.tau / 6
        d.line([(c + math.cos(a) * 20 * S, c + math.sin(a) * 20 * S),
                (c + math.cos(a) * 34 * S, c + math.sin(a) * 34 * S)],
               fill=(90, 190, 210, 255), width=2 * S)
    return Image.alpha_composite(img, glow(c, c, 50 * S, (80, 200, 230), 0.25))


def ground_rock(v):
    """Boulders filling the cell over dark rubble."""
    img = to_img(ramp(fbm(9), (26, 24, 24), (40, 36, 34)))
    rng = random.Random(900 + v)
    layers = []
    for _ in range(4 + v):
        r = rng.uniform(22, 34) * S
        cx, cy = rng.uniform(26, C - 26) * S, rng.uniform(26, C - 26) * S
        layers.append(dome(cx, cy, r, r * rng.uniform(0.7, 0.95),
                           rng.choice([(92, 82, 74), (80, 72, 66), (104, 92, 82)]),
                           spec=0.08, rot=rng.uniform(0, 3.1), flat=0.4))
    rocks = stack(*layers)
    img = Image.alpha_composite(img, shadow_of(rocks, 3, 4, 3, 0.6))
    return Image.alpha_composite(img, rocks)


def ground_cliff(v):
    """A sheer drop seen from above: dark, stratified, visible across but not walkable."""
    n = fbm(10, periods=(3, 6, 24))
    strata = 0.5 + 0.5 * np.sin((YY / S) * 0.35 + n * 6.0)
    rgb = ramp(n * 0.6 + strata * 0.4, (16, 14, 18), (30, 28, 34), (46, 42, 48))
    return to_img(rgb)


def ground_brine(v):
    n = fbm(11, periods=(4, 8, 16))
    ripple = 0.5 + 0.5 * np.sin(XX / S * 0.4 + n * 8.0)
    img = to_img(ramp(n * 0.7 + ripple * 0.3, (22, 52, 76), (36, 82, 110), (70, 130, 160)))
    rng = random.Random(1100 + v)
    d = ImageDraw.Draw(img)
    for _ in range(4):
        x, y = rng.uniform(20, C - 30) * S, rng.uniform(20, C - 20) * S
        d.arc([x, y, x + 22 * S, y + 8 * S], 200, 340, fill=(150, 200, 220, 200), width=S)
    return img


def ground_crystal(v):
    img = to_img(ramp(fbm(12), (30, 22, 40), (46, 34, 60)))
    rng = random.Random(1200 + v)
    for _ in range(9):
        cx, cy = rng.uniform(16, C - 16) * S, rng.uniform(16, C - 16) * S
        a = rng.uniform(0, math.tau)
        ln, w = rng.uniform(18, 34) * S, rng.uniform(5, 9) * S
        tip = (cx + math.cos(a) * ln, cy + math.sin(a) * ln)
        l = (cx + math.cos(a + 1.57) * w, cy + math.sin(a + 1.57) * w)
        r = (cx + math.cos(a - 1.57) * w, cy + math.sin(a - 1.57) * w)
        shard = poly_layer([l, tip, r], rng.choice([(150, 100, 210, 255), (180, 130, 240, 255),
                                                    (120, 80, 190, 255)]), width=2 * S)
        img = Image.alpha_composite(img, shadow_of(shard, 2, 3, 2, 0.5))
        img = Image.alpha_composite(img, shard)
    return Image.alpha_composite(img, glow(B / 2, B / 2, 70 * S, (170, 120, 255), 0.18))


def ground_wall(v):
    """Colony wall seen from above: a poured top with a lit edge."""
    img = to_img(ramp(fbm(13, periods=(8, 16)), (58, 60, 66), (72, 74, 80)))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, B, 5 * S], fill=(96, 98, 106, 255))
    d.rectangle([0, B - 5 * S, B, B], fill=(34, 36, 40, 255))
    for x in (0, B // 2):
        d.line([(x, 0), (x, B)], fill=(44, 46, 50, 255), width=2 * S)
    return img


def ground_pwall(v):
    img = to_img(ramp(fbm(14, periods=(4, 8)), (24, 34, 42), (36, 48, 58)))
    d = ImageDraw.Draw(img)
    c = B // 2
    d.line([(0, c), (B, c)], fill=(60, 170, 190, 255), width=2 * S)
    d.line([(c, 0), (c, B)], fill=(40, 110, 130, 255), width=S)
    return Image.alpha_composite(img, glow(c, c, 40 * S, (80, 210, 230), 0.2))


def ground_hull(v):
    img = to_img(ramp(fbm(15, periods=(6, 12)), (66, 30, 28), (86, 44, 38)))
    d = ImageDraw.Draw(img)
    for i in range(0, B, 32 * S):
        d.line([(i, 0), (i, B)], fill=(46, 20, 20, 255), width=2 * S)
    for x, y in ((8, 8), (8, 120), (120, 8), (120, 120), (64, 8), (64, 120)):
        d.ellipse([(x - 2) * S, (y - 2) * S, (x + 2) * S, (y + 2) * S], fill=(120, 70, 60, 255))
    return img


def fissure(img, rng, color, glow_color, n=2):
    d = ImageDraw.Draw(img)
    for _ in range(n):
        x, y = rng.uniform(20, 50) * S, rng.uniform(20, 108) * S
        pts = [(x, y)]
        for _ in range(6):
            x += rng.uniform(8, 16) * S
            y += rng.uniform(-10, 10) * S
            pts.append((min(x, (C - 14) * S), max(14 * S, min(y, (C - 14) * S))))
        img = Image.alpha_composite(img, stack(*[glow(px, py, 16 * S, glow_color, 0.35)
                                                 for px, py in pts]))
        d = ImageDraw.Draw(img)
        d.line(pts, fill=color, width=3 * S, joint="curve")
    return img


def ground_vent(v):
    img = to_img(ramp(fbm(16), (70, 50, 40), (92, 66, 50)))
    img = fissure(img, random.Random(1600), (255, 170, 80, 255), (255, 110, 40), 2)
    return Image.alpha_composite(img, glow(B * 0.55, B * 0.45, 30 * S, (240, 240, 240), 0.25))


def ground_heat(v):
    n = fbm(17, periods=(3, 6, 12))
    img = to_img(ramp(n, (120, 44, 24), (170, 76, 30), (230, 150, 60)))
    return fissure(img, random.Random(1700), (255, 230, 150, 255), (255, 160, 60), 3)


def ground_exit(v):
    """A way out has to read as one at a glance: a lit pad with chevrons pointing out."""
    img = to_img(ramp(fbm(18), (54, 70, 58), (70, 90, 74)))
    img = Image.alpha_composite(img, glow(B / 2, B / 2, 60 * S, (120, 255, 150), 0.45))
    d = ImageDraw.Draw(img)
    c = B / 2
    d.ellipse([c - 20 * S, c - 20 * S, c + 20 * S, c + 20 * S], outline=(170, 255, 180, 255),
              width=3 * S)
    for k in range(4):
        a = k * math.pi / 2
        for rr in (32, 44):
            tip = (c + math.cos(a) * (rr + 8) * S, c + math.sin(a) * (rr + 8) * S)
            l = (c + math.cos(a + 0.35) * rr * S, c + math.sin(a + 0.35) * rr * S)
            r = (c + math.cos(a - 0.35) * rr * S, c + math.sin(a - 0.35) * rr * S)
            d.line([l, tip, r], fill=(190, 255, 200, 255), width=3 * S, joint="curve")
    return img


GROUND = {
    "dust": ground_dust, "scrub": ground_scrub, "salt": ground_salt, "path": ground_path,
    "floor": ground_floor, "deck": ground_deck, "cave": ground_cave,
    "glyphfloor": ground_glyphfloor, "rock": ground_rock, "cliff": ground_cliff,
    "brine": ground_brine, "crystal": ground_crystal, "wall": ground_wall,
    "pwall": ground_pwall, "hull": ground_hull, "vent": ground_vent, "heat": ground_heat,
    "exit": ground_exit,
}


# --- figures (top down, facing south) ---------------------------------------------------

M = B / 2


#: Figures stand inside their cell with room for a shadow, not edge to edge.
FIG = 0.92


def person(suit, head, pack=None, hair=None, visor=None, scale=1.0, extra=None):
    s = scale * FIG
    parts = []
    if pack:
        parts.append(poly_layer(rounded_rect(M, M - 34 * S * s, 60 * S * s, 30 * S * s), pack))
    parts.append(dome(M - 44 * S * s, M + 4 * S * s, 15 * S * s, 20 * S * s, suit, spec=0.15))
    parts.append(dome(M + 44 * S * s, M + 4 * S * s, 15 * S * s, 20 * S * s, suit, spec=0.15))
    parts.append(dome(M, M, 50 * S * s, 30 * S * s, suit, spec=0.2, flat=0.3))
    if extra:
        parts.extend(extra(s))
    parts.append(dome(M, M + 2 * S * s, 24 * S * s, 24 * S * s, head, spec=0.45))
    if hair:
        parts.append(dome(M, M - 6 * S * s, 22 * S * s, 17 * S * s, hair, spec=0.1))
    if visor:
        parts.append(dome(M, M + 12 * S * s, 17 * S * s, 10 * S * s, visor, spec=0.9))
    return with_shadow(*parts)


def rounded_rect(cx, cy, w, h, r=None):
    """A rounded rectangle as a polygon (clockwise)."""
    r = r if r is not None else min(w, h) * 0.3
    pts = []
    for (ox, oy, a0) in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0),
                         (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)):
        for k in range(7):
            a = math.radians(a0 + k * 15)
            pts.append((cx + ox + math.cos(a) * r, cy + oy + math.sin(a) * r))
    return pts


def fig_crew():
    # Drawn near-white: the map tints each crew member by multiplying.
    return person((236, 236, 240), (250, 250, 252), pack=(200, 200, 206, 255),
                  visor=(40, 60, 90))


def fig_colonist():
    return person((150, 110, 70), (214, 170, 130), hair=(70, 50, 36))


def skaraan(cloth, skin, scale=1.0, mantle=None, crest=(70, 90, 60)):
    def extra(s):
        out = []
        if mantle:
            out.append(dome(M, M - 4 * S * s, 56 * S * s, 24 * S * s, mantle, spec=0.6, flat=0.5))
        return out
    body = person(cloth, skin, scale=scale, extra=extra)
    s = scale * FIG
    snout = dome(M, M + 26 * S * s, 12 * S * s, 16 * S * s, skin, spec=0.3)
    ridge = []
    for k in range(4):
        ridge.append(dome(M, M - (4 + k * 9) * S * s, (7 - k) * S * s, 6 * S * s, crest, 0.2))
    eyes = drawn(lambda d, _: [d.ellipse([M + sx * 10 * S * s - 3 * S * s, M + 12 * S * s,
                                          M + sx * 10 * S * s + 3 * S * s, M + 18 * S * s],
                                         fill=(250, 200, 40, 255)) for sx in (-1, 1)])
    return stack(body, snout, *ridge, eyes)


def fig_glassback():
    parts = []
    legs = drawn(lambda d, _: [d.line([(M + sx * 20 * S, M + oy * S),
                                       (M + sx * 50 * S, M + (oy + sx * 0 - 14 + i * 14) * S),
                                       (M + sx * 58 * S, M + (oy + 6 + i * 16) * S)],
                                      fill=(40, 60, 70, 255), width=4 * S, joint="curve")
                               for sx in (-1, 1) for i, oy in enumerate((-20, 0, 20))])
    parts.append(legs)
    for i, (oy, r) in enumerate(((-30, 20), (-4, 26), (26, 18))):
        parts.append(dome(M, M + oy * S, r * 0.9 * S, r * S, (120, 210, 220), spec=0.9))
    mand = drawn(lambda d, _: [d.line([(M + sx * 8 * S, M + 40 * S), (M + sx * 14 * S, M + 54 * S),
                                       (M + sx * 4 * S, M + 60 * S)], fill=(30, 50, 60, 255),
                                      width=3 * S) for sx in (-1, 1)])
    parts.append(mand)
    parts.append(glow(M, M - 4 * S, 30 * S, (180, 255, 255), 0.35))
    return with_shadow(*parts)


def fig_sentinel():
    hexa = [(M + math.cos(math.radians(a)) * 46 * S, M + math.sin(math.radians(a)) * 46 * S)
            for a in range(-90, 270, 60)]
    arms = drawn(lambda d, _: [d.line([(M, M), (M + math.cos(a) * 60 * S, M + math.sin(a) * 60 * S)],
                                      fill=(60, 80, 90, 255), width=8 * S)
                               for a in (math.radians(30), math.radians(150), math.radians(270))])
    body = poly_layer(hexa, (70, 96, 104, 255), width=4 * S)
    core = dome(M, M, 16 * S, 16 * S, (140, 240, 255), spec=1.0)
    return with_shadow(arms, body, glow(M, M, 40 * S, (100, 230, 255), 0.7), core)


def fig_vhesk():
    return skaraan((150, 40, 36), (120, 140, 110), scale=1.12, mantle=(210, 170, 70),
                   crest=(170, 60, 50))


def fig_youngster():
    return skaraan((200, 120, 90), (150, 170, 130), scale=0.72, crest=(110, 130, 90))


def fig_survivor():
    def bandage(s):
        return [drawn(lambda d, _: d.line([(M - 40 * S, M - 6 * S), (M + 30 * S, M + 10 * S)],
                                          fill=(240, 240, 235, 255), width=8 * S))]
    return person((210, 110, 40), (200, 160, 124), hair=(90, 60, 40), extra=bandage)


# --- props --------------------------------------------------------------------------------

def prop_drone():
    scorch = glow(M + 6 * S, M + 8 * S, 58 * S, (10, 8, 6), 0.8)
    frame = drawn(lambda d, _: [d.line([(M - 38 * S, M - 38 * S), (M + 38 * S, M + 38 * S)],
                                       fill=(90, 94, 100, 255), width=7 * S),
                                d.line([(M + 38 * S, M - 38 * S), (M - 20 * S, M + 20 * S)],
                                       fill=(90, 94, 100, 255), width=7 * S)])
    rotors = [dome(M + x * S, M + y * S, 17 * S, 17 * S, (150, 156, 164), spec=0.4, flat=0.8)
              for x, y in ((-38, -38), (38, -38), (38, 38))]
    broken = drawn(lambda d, _: d.arc([M - 55 * S, M + 21 * S, M - 21 * S, M + 55 * S], 200, 330,
                                      fill=(120, 124, 130, 255), width=5 * S))
    body = poly_layer(rounded_rect(M, M, 40 * S, 30 * S), (200, 204, 210, 255), width=3 * S)
    lamp = glow(M, M, 14 * S, (255, 80, 60), 0.9)
    return stack(scorch, with_shadow(frame, *rotors, broken, body, lamp))


def prop_crate():
    box = poly_layer(rounded_rect(M, M, 84 * S, 84 * S, 6 * S), (150, 116, 72, 255), width=4 * S)

    def planks(d, _):
        for i in (-21, 0, 21):
            d.line([(M - 40 * S, M + i * S), (M + 40 * S, M + i * S)], fill=(110, 82, 50, 255),
                   width=2 * S)
        for x, y in ((-36, -36), (36, -36), (-36, 36), (36, 36)):
            d.rectangle([M + (x - 7) * S, M + (y - 7) * S, M + (x + 7) * S, M + (y + 7) * S],
                        fill=(90, 94, 100, 255))
        d.rectangle([M - 30 * S, M - 6 * S, M + 30 * S, M + 6 * S], fill=(210, 190, 60, 255))
    return with_shadow(box, drawn(planks))


def prop_hauler():
    hull = poly_layer([(M, M - 58 * S), (M + 34 * S, M - 20 * S), (M + 40 * S, M + 50 * S),
                       (M - 40 * S, M + 50 * S), (M - 34 * S, M - 20 * S)],
                      (170, 174, 184, 255), width=4 * S)
    cockpit = dome(M, M - 26 * S, 13 * S, 17 * S, (70, 120, 170), spec=0.9)
    engines = [glow(M + x * S, M + 56 * S, 16 * S, (120, 200, 255), 0.6) for x in (-22, 22)]
    stripe = drawn(lambda d, _: d.line([(M - 30 * S, M + 18 * S), (M + 30 * S, M + 18 * S)],
                                       fill=(220, 120, 40, 255), width=6 * S))
    return with_shadow(hull, stripe, cockpit, *engines)


def door(open_):
    def draw(d, _):
        d.rectangle([4 * S, M - 20 * S, B - 4 * S, M + 20 * S], fill=(40, 42, 46, 255))
        if open_:
            d.rectangle([4 * S, M - 16 * S, 30 * S, M + 16 * S], fill=(110, 112, 118, 255))
            d.rectangle([B - 30 * S, M - 16 * S, B - 4 * S, M + 16 * S], fill=(110, 112, 118, 255))
            d.rectangle([34 * S, M - 12 * S, B - 34 * S, M + 12 * S], fill=(0, 0, 0, 0))
            for x in range(40, C - 40, 12):
                d.line([(x * S, M), ((x + 5) * S, M)], fill=(120, 255, 150, 255), width=2 * S)
        else:
            d.rectangle([8 * S, M - 16 * S, B - 8 * S, M + 16 * S], fill=(120, 96, 50, 255))
            for x in range(-10, C, 14):
                d.polygon([(x * S, M - 16 * S), ((x + 7) * S, M - 16 * S),
                           ((x + 17) * S, M + 16 * S), ((x + 10) * S, M + 16 * S)],
                          fill=(30, 28, 24, 255))
            d.rectangle([8 * S, M - 16 * S, B - 8 * S, M + 16 * S], outline=(230, 190, 60, 255),
                        width=2 * S)
            d.line([(M, M - 16 * S), (M, M + 16 * S)], fill=(20, 20, 20, 255), width=3 * S)
            d.ellipse([M - 6 * S, M - 6 * S, M + 6 * S, M + 6 * S], fill=(255, 70, 50, 255))
    img = drawn(draw)
    if open_:
        a = np.asarray(img).copy()
        a[int(M - 12 * S):int(M + 12 * S), int(34 * S):int(B - 34 * S), 3] = 0
        img = Image.fromarray(a, "RGBA")
    return with_shadow(img, dx=3, dy=4)


def prop_rockfall():
    rng = random.Random(42)
    rocks = [dome(M + rng.uniform(-36, 36) * S, M + rng.uniform(-36, 36) * S,
                  rng.uniform(16, 26) * S, rng.uniform(13, 22) * S,
                  rng.choice([(110, 98, 88), (92, 84, 76), (124, 112, 100)]),
                  spec=0.1, rot=rng.uniform(0, 3), flat=0.3) for _ in range(9)]
    return with_shadow(*rocks)


def prop_panel():
    slab = poly_layer(rounded_rect(M, M, 90 * S, 38 * S, 4 * S), (70, 84, 96, 255), width=4 * S)

    def glyphs(d, _):
        for i, x in enumerate(range(-34, 40, 17)):
            y = M + (-8 if i % 2 else 6) * S
            d.line([(M + x * S, M - 12 * S), (M + x * S, y), (M + (x + 9) * S, y)],
                   fill=(110, 230, 250, 255), width=3 * S)
    return with_shadow(slab, glow(M, M, 50 * S, (90, 220, 250), 0.35), drawn(glyphs))


def prop_terminal():
    desk = poly_layer(rounded_rect(M, M + 6 * S, 76 * S, 46 * S, 6 * S), (70, 74, 82, 255),
                      width=3 * S)
    screen = drawn(lambda d, _: [d.rectangle([M - 28 * S, M - 8 * S, M + 28 * S, M + 14 * S],
                                             fill=(40, 170, 90, 255)),
                                 *[d.line([(M - 22 * S, M + y * S), (M + (8 + y) * S, M + y * S)],
                                          fill=(180, 255, 200, 255), width=2 * S)
                                   for y in (-3, 3, 9)]])
    return with_shadow(desk, glow(M, M + 2 * S, 40 * S, (80, 255, 140), 0.35), screen)


def marker(lit):
    legs = drawn(lambda d, _: [d.line([(M, M), (M + math.cos(a) * 40 * S, M + math.sin(a) * 40 * S)],
                                      fill=(150, 150, 150, 255), width=5 * S)
                               for a in (math.radians(90), math.radians(210), math.radians(330))])
    head = dome(M, M, 16 * S, 16 * S, (200, 200, 190), spec=0.5)
    parts = [legs, head]
    if lit:
        parts.insert(0, glow(M, M, 60 * S, (120, 255, 120), 0.6))
        parts.append(dome(M, M, 8 * S, 8 * S, (160, 255, 150), spec=1.0))
    else:
        parts.append(dome(M, M, 7 * S, 7 * S, (140, 40, 30), spec=0.3))
    return with_shadow(*parts)


def prop_tent():
    body = dome(M, M, 50 * S, 42 * S, (180, 150, 100), spec=0.15, flat=0.2)
    seams = drawn(lambda d, _: [d.line([(M - 48 * S, M), (M + 48 * S, M)], fill=(120, 96, 60, 255),
                                       width=3 * S),
                                d.line([(M, M - 42 * S), (M, M + 42 * S)], fill=(120, 96, 60, 255),
                                       width=3 * S),
                                d.rectangle([M - 10 * S, M + 30 * S, M + 10 * S, M + 44 * S],
                                            fill=(40, 30, 20, 255))])
    return with_shadow(body, seams)


def prop_beacon():
    return with_shadow(glow(M, M, 60 * S, (255, 70, 60), 0.5),
                       dome(M, M, 22 * S, 22 * S, (120, 120, 130), spec=0.4, flat=0.6),
                       dome(M, M, 10 * S, 10 * S, (255, 90, 70), spec=1.0))


def pedestal(lit):
    parts = [dome(M, M, 42 * S, 42 * S, (86, 100, 110), spec=0.2, flat=1.2)]
    ring = drawn(lambda d, _: d.ellipse([M - 30 * S, M - 30 * S, M + 30 * S, M + 30 * S],
                                        outline=(90, 190, 210, 255) if lit else (60, 80, 90, 255),
                                        width=3 * S))
    parts.append(ring)
    if lit:
        parts.insert(0, glow(M, M, 64 * S, (120, 230, 255), 0.8))
        parts.append(dome(M, M, 14 * S, 14 * S, (180, 250, 255), spec=1.0))
    else:
        parts.append(dome(M, M, 12 * S, 12 * S, (50, 62, 70), spec=0.2))
    return with_shadow(*parts)


def prop_part():
    body = dome(M, M, 44 * S, 16 * S, (170, 170, 150), spec=0.8, rot=0.6)
    bands = drawn(lambda d, _: [d.line([(M + (k - 18) * S * 0.8 - 12 * S, M + (k - 18) * S * 0.6 - 16 * S),
                                        (M + (k - 18) * S * 0.8 + 8 * S, M + (k - 18) * S * 0.6 + 12 * S)],
                                       fill=(90, 90, 80, 255), width=3 * S) for k in (0, 18, 36)])
    tip = glow(M + 34 * S, M + 24 * S, 20 * S, (255, 220, 100), 0.8)
    return with_shadow(body, bands, tip)


def prop_key():
    card = poly_layer(rounded_rect(M, M, 70 * S, 44 * S, 6 * S), (230, 190, 70, 255), width=3 * S)
    chip = drawn(lambda d, _: [d.rectangle([M - 26 * S, M - 12 * S, M - 8 * S, M + 4 * S],
                                           fill=(160, 120, 40, 255)),
                               d.line([(M, M + 10 * S), (M + 26 * S, M + 10 * S)],
                                      fill=(120, 90, 30, 255), width=3 * S)])
    return with_shadow(card.rotate(-18, center=(M, M)), chip.rotate(-18, center=(M, M)))


def prop_medkit():
    case = poly_layer(rounded_rect(M, M + 4 * S, 76 * S, 56 * S, 8 * S), (236, 236, 232, 255),
                      width=3 * S)
    cross = drawn(lambda d, _: [d.rectangle([M - 7 * S, M - 16 * S, M + 7 * S, M + 24 * S],
                                            fill=(210, 40, 40, 255)),
                                d.rectangle([M - 20 * S, M - 3 * S, M + 20 * S, M + 11 * S],
                                            fill=(210, 40, 40, 255)),
                                d.rounded_rectangle([M - 14 * S, M - 36 * S, M + 14 * S, M - 22 * S],
                                                    radius=5 * S, outline=(120, 120, 120, 255),
                                                    width=3 * S)])
    return with_shadow(case, cross)


def prop_datapad():
    pad = poly_layer(rounded_rect(M, M, 56 * S, 76 * S, 6 * S), (40, 44, 52, 255), width=3 * S)
    scr = drawn(lambda d, _: [d.rectangle([M - 22 * S, M - 30 * S, M + 22 * S, M + 26 * S],
                                          fill=(50, 160, 200, 255)),
                              *[d.line([(M - 16 * S, M + y * S), (M + 14 * S, M + y * S)],
                                       fill=(190, 240, 255, 255), width=2 * S)
                                for y in (-20, -10, 0, 10)]])
    return with_shadow(pad.rotate(12, center=(M, M)), scr.rotate(12, center=(M, M)),
                       glow(M, M, 40 * S, (90, 200, 255), 0.25))


def prop_bones():
    def draw(d, _):
        col = (220, 212, 190, 255)
        d.line([(M - 30 * S, M + 10 * S), (M + 30 * S, M + 10 * S)], fill=col, width=5 * S)
        for x in range(-24, 30, 10):
            d.arc([M + (x - 6) * S, M - 8 * S, M + (x + 6) * S, M + 28 * S], 180, 360, fill=col,
                  width=3 * S)
        d.line([(M + 30 * S, M + 30 * S), (M + 52 * S, M + 44 * S)], fill=col, width=4 * S)
    skull = dome(M - 42 * S, M - 16 * S, 14 * S, 12 * S, (224, 216, 196), spec=0.3)
    sockets = drawn(lambda d, _: [d.ellipse([M + (x - 3) * S, M - 18 * S, M + (x + 3) * S, M - 12 * S],
                                            fill=(40, 30, 20, 255)) for x in (-47, -37)])
    return with_shadow(drawn(draw), skull, sockets, dx=2, dy=3)


def prop_drop():
    bag = dome(M, M + 4 * S, 26 * S, 22 * S, (170, 140, 90), spec=0.2)
    tie = dome(M, M - 16 * S, 8 * S, 6 * S, (120, 96, 60), spec=0.1)
    return with_shadow(glow(M, M, 44 * S, (255, 250, 150), 0.6), bag, tie)


def prop_sample():
    vial = dome(M, M, 36 * S, 12 * S, (200, 230, 230), spec=1.0, rot=-0.7)
    liquid = dome(M + 10 * S, M - 10 * S, 20 * S, 8 * S, (120, 255, 170), spec=0.6, rot=-0.7)
    return with_shadow(glow(M, M, 44 * S, (120, 255, 170), 0.5), vial, liquid)


def prop_console():
    body = poly_layer([(M - 50 * S, M - 10 * S), (M, M - 36 * S), (M + 50 * S, M - 10 * S),
                       (M + 40 * S, M + 30 * S), (M - 40 * S, M + 30 * S)], (90, 40, 36, 255),
                      width=4 * S)
    screens = drawn(lambda d, _: [d.rectangle([M + (x - 12) * S, M - 8 * S, M + (x + 12) * S, M + 14 * S],
                                              fill=(255, 140, 50, 255)) for x in (-26, 0, 26)])
    return with_shadow(body, glow(M, M, 50 * S, (255, 120, 40), 0.35), screens)


def prop_bed():
    frame = poly_layer(rounded_rect(M, M, 56 * S, 100 * S, 5 * S), (100, 104, 116, 255),
                       width=3 * S)
    mattress = poly_layer(rounded_rect(M, M + 4 * S, 46 * S, 84 * S, 6 * S),
                          (150, 160, 190, 255), width=2 * S)
    pillow = dome(M, M - 34 * S, 18 * S, 9 * S, (236, 236, 240), spec=0.2)
    return with_shadow(frame, mattress, pillow)


# --- hint badges ---------------------------------------------------------------------------

def _font(px):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            pass
    return ImageFont.load_default(size=px)


def badge(fill, text=None, arrow=False):
    """A round badge that reads over any ground: dark rim, bright face, bold mark."""
    r = 54 * S
    rim = drawn(lambda d, _: d.ellipse([M - r, M - r, M + r, M + r], fill=(16, 16, 20, 255)))
    face = dome(M, M, r - 7 * S, r - 7 * S, fill, spec=0.5, flat=1.5)
    marks = blank()
    d = ImageDraw.Draw(marks)
    if text:
        f = _font(int(84 * S))
        box = d.textbbox((0, 0), text, font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text((M - w / 2 - box[0], M - h / 2 - box[1]), text, font=f, fill=(20, 16, 10, 255))
    if arrow:
        d.polygon([(M - 26 * S, M - 22 * S), (M + 4 * S, M - 22 * S), (M + 30 * S, M),
                   (M + 4 * S, M + 22 * S), (M - 26 * S, M + 22 * S), (M, M)],
                  fill=(10, 30, 36, 255))
    return with_shadow(rim, face, marks, dx=2, dy=3, blur=3)


SPRITES = {
    "crew": fig_crew, "colonist": fig_colonist,
    "skaraan": lambda: skaraan((150, 50, 44), (110, 130, 100)),
    "glassback": fig_glassback, "sentinel": fig_sentinel, "vhesk": fig_vhesk,
    "youngster": fig_youngster, "survivor": fig_survivor,
    "drone": prop_drone, "crate": prop_crate, "hauler": prop_hauler,
    "door_shut": lambda: door(False), "door_open": lambda: door(True),
    "rockfall": prop_rockfall, "panel": prop_panel, "terminal": prop_terminal,
    "marker": lambda: marker(False), "marker_set": lambda: marker(True), "tent": prop_tent,
    "beacon": prop_beacon, "pedestal": lambda: pedestal(False),
    "pedestal_lit": lambda: pedestal(True), "part": prop_part, "key": prop_key,
    "medkit": prop_medkit, "datapad": prop_datapad, "bones": prop_bones, "drop": prop_drop,
    "sample": prop_sample, "console": prop_console, "bed": prop_bed,
    "hint_new": lambda: badge((255, 214, 70), "?"),
    "hint_lead": lambda: badge((255, 140, 50), "!"),
    "hint_way": lambda: badge((90, 230, 255), arrow=True),
}


def draw_cell(name):
    base, _, variant = name.partition("_v")
    if base in GROUND and (not variant or variant.isdigit()):
        return GROUND[base](int(variant or 1) - 1)
    if name in SPRITES:
        return SPRITES[name]()
    raise SystemExit("no drawing for tile %r" % name)


# --- the set -------------------------------------------------------------------------

#: Ground drawings -> how many looks (variant n is drawing "<drawing>_v<n>").
VARIANTS = {"dust": 3, "scrub": 3, "salt": 3, "path": 2, "floor": 2, "cave": 3,
            "rock": 3, "brine": 2}

#: The shared ground LOOK names (what the mission's kinds wear, see surface/mereth.tileset)
#: -> the drawing that stands in for each in this builtin set.
GROUND_LOOKS = {
    "dirt": "dust", "dirt_grass": "scrub", "salt": "salt", "sand_pale": "path",
    "floor_metal": "floor", "floor_grate": "deck", "rock_floor": "cave",
    "stone_tiles": "glyphfloor", "vent": "vent", "rock": "rock", "cliff": "cliff",
    "water": "brine", "crystal": "crystal", "wall_metal": "wall",
    "wall_ancient": "pwall", "hull_metal": "hull", "exit": "exit", "lava": "heat",
    # the Gnaw's rooms: without a pack they are all just deck
    "floor_panel": "floor", "floor_corridor": "floor", "floor_tiles": "floor",
    "floor_hazard": "deck",
}

#: Shared key -> drawing, or (drawing, tint). The same vocabulary every Cosmos tile pack
#: uses (fig: people, prop: things, ui: badges), so a pack can redraw any of it and
#: anything a pack leaves out still has a picture here.
KEYS = {
    # people
    "fig:crew_eva": "crew", "fig:crew_f": "survivor", "fig:crew_m": "colonist",
    "fig:captain_f": ("colonist", "#fd8"), "fig:captain_m": ("colonist", "#fd8"),
    "fig:junker_m": ("colonist", "#f96"), "fig:junker_f": "colonist",
    "fig:medic_m": "survivor", "fig:soldier_m": ("colonist", "#9ab"),
    "fig:soldier_f": ("colonist", "#9ab"), "fig:hunter_f": "colonist",
    "fig:skaraan": "skaraan", "fig:skaraan_young": "youngster",
    "fig:skaraan_chief": "vhesk", "fig:alien": "skaraan", "fig:glassback": "glassback",
    "fig:robot_war": "sentinel", "fig:robot_f": "sentinel",
    # things, and their other states
    "prop:survey_marker": "marker", "prop:survey_marker_lit": "marker_set",
    "prop:crate": "crate", "prop:crate_medical": "medkit", "prop:hatch": "door_shut",
    "prop:doorframe": "door_open", "prop:terminal": "terminal", "prop:console": "console",
    "prop:machine_part": "part", "prop:beacon": "marker", "prop:beacon_lit": "marker_set",
    "prop:rubble": "rockfall", "prop:rubble_cleared": "path",
    "prop:crystal_seam": "crystal", "prop:crystal_seam_mined": "cave",
    "prop:drone_wreck": "drone", "prop:tent": "tent", "prop:tent_b": "tent",
    "prop:keycard": "key", "prop:scanner": "datapad", "prop:bones": "bones",
    "prop:bag": "drop", "prop:sample_tube": "sample", "prop:bed": "bed",
    "prop:hauler": "hauler", "prop:antenna_dish": "marker", "prop:obelisk": "panel",
    "prop:glyph_panel": "panel", "prop:pedestal": "pedestal",
    "prop:pedestal_lit": "pedestal_lit", "prop:ancient_console": "console",
    "prop:vault_door": "door_shut", "prop:vault_door_open": "glyphfloor",
    "prop:door_station": "door_shut",
    # the Gnaw's furnishings
    "prop:console_bank": "console", "prop:console_station": "console", "prop:bunk": "bed",
    "prop:desk": "terminal", "prop:crate_ammo": "crate", "prop:crate_shield": "crate",
    "prop:crate_wide": "crate", "prop:barrel": "crate", "prop:oxygen_tank": "part",
    "prop:oxygen_tank_large": "part", "prop:cart_loaded": "crate",
    # hint badges
    "ui:hint_new": "hint_new", "ui:hint_lead": "hint_lead", "ui:hint_way": "hint_way",
}


def build_set():
    """(drawings in sheet order, sprites {key: (drawing, tint)}, ground {kind: look})."""
    sprites, ground = {}, {}
    for name, drawing in GROUND_LOOKS.items():
        n_looks = VARIANTS.get(drawing, 1)
        looks = ["ground:%s" % name if n == 1 else "ground:%s_v%d" % (name, n)
                 for n in range(1, n_looks + 1)]
        for n, key in enumerate(looks, 1):
            sprites[key] = (drawing if n == 1 else "%s_v%d" % (drawing, n), None)
        ground[name] = {"cell": looks[0]}
        if len(looks) > 1:
            ground[name]["variants"] = looks[1:]
    for key, what in KEYS.items():
        drawing, tint = (what, None) if isinstance(what, str) else what
        sprites[key] = (drawing, tint)
    drawings = []
    for drawing, _ in sprites.values():
        if drawing not in drawings:
            drawings.append(drawing)
    return drawings, sprites, ground


def main():
    drawings, sprites, ground = build_set()
    rows = (len(drawings) + COLS - 1) // COLS
    sheet = Image.new("RGBA", (COLS * C, rows * C), (0, 0, 0, 0))
    rects = {}
    for i, name in enumerate(drawings):
        x, y = (i % COLS) * C, (i // COLS) * C
        sheet.paste(draw_cell(name).resize((C, C), Image.LANCZOS), (x, y))
        rects[name] = [x, y, x + C, y + C]
    manifest = {"sheets": {"sheet": "sheet.png"}, "sprites": {}, "ground": ground}
    for key, (drawing, tint) in sorted(sprites.items()):
        entry = {"sheet": "sheet", "rect": rects[drawing]}
        if tint:
            entry["color"] = tint
        manifest["sprites"][key] = entry
    os.makedirs(OUT_DIR, exist_ok=True)
    sheet.save(os.path.join(OUT_DIR, "sheet.png"), optimize=True)
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote", OUT_DIR, len(drawings), "drawings,", len(sprites), "keys")


if __name__ == "__main__":
    main()
