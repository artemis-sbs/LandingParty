"""Render an area the way the tile view draws it, with every prop and person in place.

    python _tools/preview_map.py colony                 # builtin art
    python _tools/preview_map.py colony --art synty     # builtin, then the synty set
    python _tools/preview_map.py flats --out flats.png --window 0,0,24,14

Same rules as `TileView`: ground looks from `tilemap_cell_look` (variants, edges, shade),
sprites placed by their footprint's anchor on the cell's bottom-center, drawn in row
order so what stands further south is on top. No fog - everything is shown. Art sets are
looked up in this mission's `media/tileart/` and in `__lib__/media/*/media/tileart/`
(unpacked packs), later sets overriding earlier ones key by key.

Dev tool: needs Pillow, and sbs_utils beside this mission.
"""
import argparse
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MISSIONS = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(MISSIONS, "sbs_utils"))
sys.path.insert(0, ROOT)

T_PX = 64          # preview pixels per tile


def find_set(name):
    """This mission first, then a mod repo checked out beside it (what you are iterating
    on), then the unpacked packs in __lib__/media (what the engine would load)."""
    here = os.path.join(ROOT, "media", "tileart", name)
    if os.path.exists(os.path.join(here, "manifest.json")):
        return here
    for repo in sorted(os.listdir(MISSIONS)):
        folder = os.path.join(MISSIONS, repo, "media", "tileart", name)
        if os.path.exists(os.path.join(folder, "manifest.json")):
            return folder
    lib = os.path.join(MISSIONS, "__lib__", "media")
    for pack in sorted(os.listdir(lib)):
        folder = os.path.join(lib, pack, "tileart", name)
        if os.path.exists(os.path.join(folder, "manifest.json")):
            return folder
    return None


def load_sets(names):
    """{key: (PIL image cropped, footprint, tint)} and the merged ground looks."""
    sprites, ground, sheets = {}, {}, {}
    for name in names:
        folder = find_set(name)
        if folder is None:
            print("art set not found:", name)
            continue
        m = json.load(open(os.path.join(folder, "manifest.json"), encoding="utf-8"))
        for key, spec in m.get("sprites", {}).items():
            sheet = m["sheets"].get(spec["sheet"], spec["sheet"])
            path = os.path.join(folder, sheet if sheet.endswith(".png") else sheet + ".png")
            if path not in sheets:
                sheets[path] = Image.open(path).convert("RGBA")
            cell = sheets[path].crop(tuple(spec["rect"]))
            w, h = (spec.get("cells") or (1, 1))
            ax, ay = (spec.get("anchor") or (0.5, 1.0))
            sprites[key] = (cell, (w, h, ax, ay), spec.get("color"))
        for kind, look in m.get("ground", {}).items():
            ground.setdefault(kind, {}).update(look)
        print("loaded", name, "from", folder)
    return sprites, ground


def tint(img, color):
    if not color:
        return img
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    px = img.split()
    return Image.merge("RGBA", (px[0].point(lambda v: v * r // 255),
                                px[1].point(lambda v: v * g // 255),
                                px[2].point(lambda v: v * b // 255), px[3]))


def placements(area):
    """[(x, y, sprite key)] for every prop and person the world puts in this area."""
    from sbs_utils.procedural.amd_doc import amd_document, amd_section
    from sbs_utils.procedural.amd_mission import amd_mission_data
    from sbs_utils.procedural.tilemap import tilemap_mark_cells, _xy
    world = amd_document(open(os.path.join(ROOT, "world.amd"), encoding="utf-8").read(),
                         data_parser=amd_mission_data)
    out = []
    for section in ("props", "people", "hostiles"):
        for n in amd_section(world, section).get("children", []):
            d = n.get("data") or {}
            if str(d.get("area", "")).strip().lower() != area or not d.get("sprite"):
                continue
            if d.get("hidden_until"):
                continue
            at = d.get("mark") or d.get("at")
            cell = None
            if isinstance(at, str):
                cells = tilemap_mark_cells(area, at)
                cell = cells[0] if cells else None
            cell = cell or _xy(at)
            if cell:
                out.append((cell[0], cell[1], d["sprite"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--art", default="", help="comma list of sets after builtin")
    ap.add_argument("--out")
    ap.add_argument("--window", help="x,y,w,h in cells")
    ap.add_argument("--crew", default="", help="x,y;x,y... crew figures to stand")
    ap.add_argument("--facing", default="s")
    args = ap.parse_args()

    from sbs_utils.procedural import tilemap as T
    from sbs_utils.procedural.tilemap_art import tilemap_art_ground
    import lp_world as L
    names = ["builtin"] + [a.strip() for a in args.art.split(",") if a.strip()]
    sprites, ground = load_sets(names)
    T.tilemap_tileset_load(open(os.path.join(ROOT, L.LP_TILESET), encoding="utf-8").read())
    tilemap_art_ground("mereth", ground)
    T.tilemap_load(open(os.path.join(ROOT, "surface", args.area + ".tiles"),
                        encoding="utf-8").read())
    rec = T.tilemap_area(args.area)
    x0, y0, w, h = (0, 0, rec["w"], rec["h"])
    if args.window:
        x0, y0, w, h = (int(v) for v in args.window.split(","))
    img = Image.new("RGBA", (w * T_PX, h * T_PX), (0, 0, 0, 255))
    cache = {}

    def scaled(key, fw, fh):
        k = (key, fw, fh)
        if k not in cache:
            src, _, color = sprites[key]
            cache[k] = tint(src, color).resize((int(fw * T_PX), int(fh * T_PX)), Image.LANCZOS)
        return cache[k]

    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            kind = T.tilemap_kind(args.area, x, y)
            spec = T.tilemap_kind_spec(args.area, kind) if kind else None
            if not spec or not spec.get("cell"):
                continue
            key = T.tilemap_cell_look(spec, x, y, args.area)
            if key in sprites:
                img.alpha_composite(scaled(key, 1, 1), ((x - x0) * T_PX, (y - y0) * T_PX))
    # Fringes over the ground, before anything stands on it - as the view sends them.
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            for key in T.tilemap_cell_fringes(args.area, x, y):
                if key in sprites:
                    img.alpha_composite(scaled(key, 1, 1), ((x - x0) * T_PX, (y - y0) * T_PX))

    things = placements(args.area)
    colors = ["#4cf", "#fc4", "#f66", "#8f8", "#c8f", "#fa8"]
    for i, pair in enumerate([p for p in args.crew.split(";") if p.strip()]):
        bits = pair.split(",")
        cx, cy = int(bits[0]), int(bits[1])
        facing = bits[2] if len(bits) > 2 else args.facing
        things.append((cx, cy, "fig:crew_eva", facing, colors[i % len(colors)]))
    # Row order, as the view sends them.
    things = [t if len(t) == 5 else (t[0], t[1], t[2], args.facing, None) for t in things]
    for x, y, base, facing, color in sorted(things, key=lambda t: (t[1], t[0])):
        key = None
        for k in ("%s_%s_idle" % (base, facing), "%s_%s" % (base, facing), base):
            if k in sprites:
                key = k
                break
        if key is None:
            print("no art for", base)
            continue
        fw, fh, ax, ay = sprites[key][1]
        if color:
            src, fp, _ = sprites[key]
            sprites[key + "#" + color] = (src, fp, color)
            key = key + "#" + color
        foot_x = (x - x0 + 0.5) * T_PX
        foot_y = (y - y0 + 1) * T_PX
        left = int(round(foot_x - ax * fw * T_PX))
        top = int(round(foot_y - ay * fh * T_PX))
        img.alpha_composite(scaled(key, fw, fh), (left, top)) if left >= 0 and top >= 0 \
            else img.paste(scaled(key, fw, fh), (left, top), scaled(key, fw, fh))
    out = args.out or os.path.join(HERE, "preview_%s.png" % args.area)
    img.convert("RGB").save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
