"""Generate the placeholder tile atlas for Mereth: media/lp_tiles.png, 8x8 cells of 64 px.

Stand-in art so the world can be played before real tiles exist (Synty top-down renders
or a CC0 set later). The ORDER of NAMES is the atlas layout - `lp_world.py` registers the
same list, so change both together or every tile shifts by a cell.

Dev tool: needs Pillow.  python _tools/make_tiles.py
"""
import os
import random

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "media", "lp_tiles.png")
C = 64

# Keep in step with lp_world.py LP_TILE_NAMES.
NAMES = [
    "dust", "scrub", "salt", "path", "floor", "deck", "cave", "glyphfloor",
    "rock", "cliff", "brine", "crystal", "wall", "pwall", "hull", "vent",
    "crew", "colonist", "skaraan", "glassback", "sentinel", "vhesk", "youngster", "survivor",
    "drone", "crate", "hauler", "door_shut", "door_open", "rockfall", "panel", "terminal",
    "marker", "marker_set", "tent", "beacon", "pedestal", "pedestal_lit", "part", "key",
    "medkit", "datapad", "bones", "drop", "sample", "console", "bed", "heat",
    "exit",
]

rnd = random.Random(11)
im = Image.new("RGBA", (C * 8, C * 8), (0, 0, 0, 0))
d = ImageDraw.Draw(im)


def origin(i):
    return (i % 8) * C, (i // 8) * C


def ground(i, base, speck, n=60, size=2):
    x0, y0 = origin(i)
    d.rectangle([x0, y0, x0 + C - 1, y0 + C - 1], fill=base)
    for _ in range(n):
        x, y = x0 + rnd.randrange(C), y0 + rnd.randrange(C)
        d.rectangle([x, y, x + size, y + size], fill=speck)


def token(i, fill, outline=(0, 0, 0, 255), shape="circle", letter=None):
    x0, y0 = origin(i)
    box = [x0 + 10, y0 + 10, x0 + C - 10, y0 + C - 10]
    if shape == "circle":
        d.ellipse(box, fill=fill, outline=outline, width=3)
    elif shape == "diamond":
        cx, cy = x0 + C // 2, y0 + C // 2
        d.polygon([(cx, y0 + 8), (x0 + C - 8, cy), (cx, y0 + C - 8), (x0 + 8, cy)],
                  fill=fill, outline=outline)
    else:
        d.rectangle(box, fill=fill, outline=outline, width=3)
    if letter:
        d.text((x0 + C // 2 - 4, y0 + C // 2 - 6), letter, fill=(0, 0, 0, 255))


G = {
    "dust": ((96, 82, 62), (116, 100, 76)), "scrub": ((72, 86, 56), (92, 108, 70)),
    "salt": ((196, 190, 176), (214, 208, 196)), "path": ((128, 106, 76), (140, 118, 88)),
    "floor": ((82, 84, 90), (98, 100, 106)), "deck": ((70, 74, 84), (90, 94, 104)),
    "cave": ((58, 48, 44), (72, 60, 54)), "glyphfloor": ((52, 64, 78), (90, 150, 170)),
    "rock": ((40, 36, 34), (58, 52, 48)), "cliff": ((24, 22, 26), (40, 36, 40)),
    "brine": ((34, 70, 96), (60, 110, 140)), "crystal": ((70, 40, 90), (170, 120, 220)),
    "wall": ((46, 48, 54), (60, 62, 70)), "pwall": ((30, 40, 50), (70, 120, 140)),
    "hull": ((60, 30, 30), (90, 50, 44)), "vent": ((80, 60, 50), (230, 120, 60)),
    "heat": ((150, 60, 30), (240, 170, 60)),
}
for i, name in enumerate(NAMES):
    if name in G:
        base, speck = G[name]
        ground(i, base + (255,), speck + (255,),
               n=120 if name in ("rock", "cliff", "crystal") else 60)

TOKENS = {
    "crew": ((255, 255, 255, 255), "circle", None),
    "colonist": ((230, 200, 150, 255), "circle", "c"),
    "skaraan": ((200, 70, 60, 255), "diamond", "S"),
    "glassback": ((150, 230, 230, 255), "diamond", "g"),
    "sentinel": ((120, 170, 255, 255), "square", "X"),
    "vhesk": ((240, 60, 40, 255), "diamond", "V"),
    "youngster": ((240, 140, 120, 255), "circle", "y"),
    "survivor": ((230, 230, 160, 255), "circle", "s"),
    "drone": ((150, 150, 160, 255), "square", "d"),
    "crate": ((150, 110, 60, 255), "square", None),
    "hauler": ((180, 180, 190, 255), "square", "P"),
    "door_shut": ((150, 90, 40, 255), "square", "#"),
    "door_open": ((70, 60, 50, 255), "square", "_"),
    "rockfall": ((70, 64, 60, 255), "diamond", None),
    "panel": ((60, 160, 190, 255), "square", "="),
    "terminal": ((60, 180, 90, 255), "square", "t"),
    "marker": ((230, 200, 60, 255), "diamond", None),
    "marker_set": ((120, 240, 100, 255), "diamond", "+"),
    "tent": ((170, 150, 110, 255), "diamond", "^"),
    "beacon": ((240, 80, 200, 255), "circle", "!"),
    "pedestal": ((90, 110, 130, 255), "square", "o"),
    "pedestal_lit": ((140, 230, 255, 255), "square", "O"),
    "part": ((200, 200, 90, 255), "circle", "p"),
    "key": ((250, 220, 90, 255), "circle", "k"),
    "medkit": ((240, 240, 240, 255), "square", "+"),
    "datapad": ((90, 200, 230, 255), "square", "i"),
    "bones": ((210, 200, 180, 255), "diamond", None),
    "drop": ((250, 250, 120, 255), "circle", "*"),
    "sample": ((170, 250, 200, 255), "circle", "v"),
    "console": ((80, 80, 120, 255), "square", "c"),
    "bed": ((120, 120, 150, 255), "square", "b"),
}
for i, name in enumerate(NAMES):
    if name in TOKENS:
        fill, shape, letter = TOKENS[name]
        token(i, fill, shape=shape, letter=letter)

# EXIT: a way out must read as one at a glance - bright chevrons on the ground.
_x0, _y0 = origin(NAMES.index("exit"))
d.rectangle([_x0, _y0, _x0 + C - 1, _y0 + C - 1], fill=(70, 90, 70, 255))
for _i in range(3):
    _cy = _y0 + 12 + _i * 16
    d.polygon([(_x0 + 12, _cy), (_x0 + C // 2, _cy + 12), (_x0 + C - 12, _cy),
               (_x0 + C - 12, _cy + 5), (_x0 + C // 2, _cy + 17), (_x0 + 12, _cy + 5)],
              fill=(150, 255, 150, 255))
d.rectangle([_x0, _y0, _x0 + C - 1, _y0 + C - 1], outline=(150, 255, 150, 255), width=2)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
im.save(OUT)
print("wrote", OUT, len(NAMES), "cells")
