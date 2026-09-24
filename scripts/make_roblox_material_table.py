"""Write src/rhr/scene/roblox_materials.json from Roblox's creator documentation.

    python scripts/make_roblox_material_table.py <creator-docs checkout>

Roblox publishes the asset ids of its built-in material textures (colour, normal,
metalness and roughness maps, for parts and for terrain faces, current and pre-2022)
and each material's default colour in `content/en-us/parts/materials.md` of
https://github.com/Roblox/creator-docs (CC BY 4.0). RHR ships only these ids and
colours; the images themselves are downloaded to the user's own cache when a scene
needs them (rhr.fetch), never committed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "rhr" / "scene" / "roblox_materials.json"
TAB = re.compile(r'<TabItem label="([^"]+)">(.*?)</TabItem>', re.DOTALL)
ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
CELL = re.compile(r"<td([^>]*)>(.*?)</td>", re.DOTALL)
NAME = re.compile(r"Enum\.Material\.(\w+)")
DIGITS = re.compile(r"(\d+)")


def _cells(row: str) -> list[tuple[str, str]]:
    return [(attrs, text.strip()) for attrs, text in CELL.findall(row)]


def _asset(text: str) -> str | None:
    match = DIGITS.search(text)
    return match.group(1) if match else None


def parse_parts(body: str) -> dict:
    """Material -> {color, normal, metalness, roughness} asset ids (parts)."""
    table = {}
    for row in ROW.findall(body):
        cells = _cells(row)
        if len(cells) < 5 or not NAME.search(cells[0][1]):
            continue
        name = NAME.search(cells[0][1]).group(1)
        color, normal, metalness, roughness = (_asset(text) for _, text in cells[1:5])
        table[name] = {key: value for key, value in (
            ("color", color), ("normal", normal), ("metalness", metalness), ("roughness", roughness),
        ) if value}
    return table


def parse_terrain(body: str) -> dict:
    """Material -> {face: {color, normal, roughness}}, face in all/top/side/bottom."""
    table: dict = {}
    current = None
    for row in ROW.findall(body):
        cells = _cells(row)
        if cells and NAME.search(cells[0][1]):
            current = NAME.search(cells[0][1]).group(1)
            cells = cells[1:]
        if current is None or len(cells) < 4:
            continue
        face = cells[0][1].strip("()").lower()
        color, normal, roughness = (_asset(text) for _, text in cells[1:4])
        table.setdefault(current, {})[face] = {key: value for key, value in (
            ("color", color), ("normal", normal), ("roughness", roughness),
        ) if value}
    return table


def parse_default_colors(text: str) -> dict:
    section = text.split("### Default colors", 1)[1].split("###", 1)[0]
    colors = {}
    for row in ROW.findall(section):
        cells = _cells(row)
        if len(cells) >= 2 and NAME.search(cells[0][1]):
            rgb = [int(v) for v in re.findall(r"\d+", cells[1][1])[:3]]
            if len(rgb) == 3:
                colors[NAME.search(cells[0][1]).group(1)] = rgb
    return colors


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    checkout = Path(argv[0])
    source = checkout / "content" / "en-us" / "parts" / "materials.md"
    text = source.read_text(encoding="utf-8")
    tabs = {label: body for label, body in TAB.findall(text)}
    try:
        commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    document = {
        "source": "https://github.com/Roblox/creator-docs/blob/main/content/en-us/parts/materials.md",
        "sourceCommit": commit,
        "license": "CC-BY-4.0 (Roblox Corporation); asset ids and colours only",
        "parts": parse_parts(tabs["Current Base"]),
        "partsLegacy": parse_parts(tabs["Pre-2022 Base"]),
        "terrain": parse_terrain(tabs["Current Terrain"]),
        "terrainLegacy": parse_terrain(tabs["Pre-2022 Terrain"]),
        "defaultColors": parse_default_colors(text),
    }
    OUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    counts = {key: len(value) for key, value in document.items() if isinstance(value, dict)}
    print(f"wrote {OUT}  {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
