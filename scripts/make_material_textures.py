#!/usr/bin/env python3
"""Build RHR's material textures from CC0 ambientCG materials.

    python scripts/make_material_textures.py [download-cache-dir]

Roblox's own material images cannot be redistributed, so RHR ships look-alikes:
one public-domain (CC0) material from https://ambientcg.com per Roblox material.
Each colour map becomes a greyscale detail tile whose average is fixed, so the
part's own Color tints it the way Roblox tints its materials; the normal map is
kept for relief. Output: src/rhr/scene/materials/<Material>.jpg, <Material>_n.jpg
and credits.json (which asset each one came from).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "rhr" / "scene" / "materials"
SIZE = 512

# Roblox material -> ambientCG asset id. Picked for an even look that tints well.
SOURCES = {
    "Brick": "Bricks104",
    "Wood": "Wood095",
    "WoodPlanks": "WoodFloor040",
    "Concrete": "Concrete034",
    "Cobblestone": "PavingStones150",
    "Grass": "Grass001",
    "LeafyGrass": "Grass004",
    "Sand": "Ground079S",
    "Slate": "Rock030",
    "Granite": "Granite002A",
    "Marble": "Marble012",
    "Pebble": "Gravel043",
    "DiamondPlate": "DiamondPlate008C",
    "CorrodedMetal": "Metal041B",
    "Metal": "Metal055A",
    "Fabric": "Fabric061",
    "Foil": "Foil003",
    "Snow": "Snow010A",
    "Ice": "Ice003",
    "Glacier": "Ice003",
    "Asphalt": "Asphalt031",
    "Ground": "Ground048",
    "Mud": "Ground071",
    "Rock": "Rock023",
    "Limestone": "Concrete047A",
    "Pavement": "PavingStones128",
    "Plaster": "Plaster001",
    "Carpet": "Carpet012",
    "CeramicTiles": "Tiles141",
    "ClayRoofTiles": "RoofingTiles012A",
    "RoofShingles": "RoofingTiles001",
    "Leather": "Leather030",
    "Rubber": "Rubber001",
    "Cardboard": "Cardboard002",
    "Sandstone": "Rock061",
    "Basalt": "Rock028",
    "CrackedLava": "Lava004",
}

# The detail tile's average brightness and spread. Roblox's materials darken a
# part's colour a little and add texture on top; every tile is brought to the same
# spread so a faint source still reads and a harsh one does not blotch the part.
MEAN = 0.82
SPREAD = 0.10


def fetch(asset: str, cache: Path) -> zipfile.ZipFile:
    path = cache / f"{asset}_1K-JPG.zip"
    if not path.is_file():
        url = f"https://ambientcg.com/get?file={asset}_1K-JPG.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "roblox-headless-renderer"})
        path.write_bytes(urllib.request.urlopen(request, timeout=120).read())
    return zipfile.ZipFile(path)


def member(archive: zipfile.ZipFile, suffix: str) -> Image.Image | None:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), None)
    return Image.open(io.BytesIO(archive.read(name))) if name else None


def detail_tile(color: Image.Image) -> Image.Image:
    grey = ImageOps.grayscale(color.convert("RGB")).resize((SIZE, SIZE), Image.LANCZOS)
    stat = ImageStat.Stat(grey)
    mean, std = stat.mean[0] / 255, max(stat.stddev[0] / 255, 1e-3)
    # Keep the pattern; fix the average and the spread (see MEAN, SPREAD).
    gain = max(0.3, min(2.5, SPREAD / std))
    lut = [max(0, min(255, round(255 * (MEAN + (v / 255 - mean) * gain)))) for v in range(256)]
    return grey.point(lut)


def main() -> int:
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "rhr-ambientcg"
    cache.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    credits = {}
    for material, asset in SOURCES.items():
        archive = fetch(asset, cache)
        color = member(archive, "_Color.jpg")
        normal = member(archive, "_NormalGL.jpg")
        if color is None:
            print(f"{material:14} {asset}: no colour map, skipped")
            continue
        detail_tile(color).save(OUT / f"{material}.jpg", quality=82, optimize=True)
        if normal is not None:
            normal.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(
                OUT / f"{material}_n.jpg", quality=82, optimize=True)
        credits[material] = {
            "asset": asset,
            "url": f"https://ambientcg.com/view?id={asset}",
            "license": "CC0 1.0",
            "normalMap": normal is not None,
        }
        print(f"{material:14} {asset}")
    (OUT / "credits.json").write_text(json.dumps({
        "source": "ambientCG (https://ambientcg.com), CC0 1.0 Universal",
        "note": "Colour maps converted to greyscale detail tiles and resized; normal maps resized.",
        "materials": credits,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
