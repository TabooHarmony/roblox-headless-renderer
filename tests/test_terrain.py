#!/usr/bin/env python3
"""Voxel terrain: Terrain.SmoothGrid decodes, and draws as a smooth surface where it is.

The decoder (rhr.terrain) was checked against Studio's Terrain:ReadVoxels on Roblox's
game template. Here a small terrain is encoded in the same format (a grass floor and
a water block), written into a place, and both decoded and rendered.

    python tests/test_terrain.py
"""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
failures: list[str] = []

GRASS, WATER = 2, 1


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def encode(chunks: dict[tuple[int, int, int], dict[tuple[int, int, int], tuple[int, int]]]) -> bytes:
    """The SmoothGrid format, from {chunk: {(x, y, z) in chunk: (material, occupancy)}}."""
    out = bytearray(b"\x01\x05")
    previous = (0, 0, 0)
    for position in sorted(chunks, key=lambda p: (p[0], p[1], p[2])):
        delta = [p - q for p, q in zip(position, previous)]
        previous = position
        raw = [d.to_bytes(4, "big", signed=True) for d in delta]
        out += bytes(raw[axis][k] for k in range(4) for axis in range(3))
        voxels = chunks[position]
        cells = []
        for y in range(32):
            for z in range(32):
                for x in range(32):
                    cells.append(voxels.get((x, y, z), (0, 0)))
        i = 0
        while i < len(cells):
            run = 1
            while i + run < len(cells) and cells[i + run] == cells[i] and run < 256:
                run += 1
            material, occ = cells[i]
            lead = material | (0x40 if material and occ != 255 else 0) | (0x80 if run > 1 else 0)
            out.append(lead)
            if lead & 0x40:
                out.append(occ)
            if run > 1:
                out.append(run - 1)
            i += run
    return bytes(out)


def main() -> int:
    from rhr.terrain import decode_smooth_grid, terrain_payload

    # A 3x3 grass floor, one voxel thick, in chunk (0, -1, 0) at the top (y just
    # below 0 studs), a half-filled top voxel, and a water voxel beside the floor.
    floor = {(x, 31, z): (GRASS, 255) for x in range(3) for z in range(3)}
    floor[(1, 30, 1)] = (GRASS, 255)
    floor[(0, 31, 0)] = (GRASS, 127)
    floor[(5, 31, 1)] = (WATER, 255)
    blob = encode({(0, -1, 0): floor, (-1, -1, -1): {(31, 31, 31): (GRASS, 255)}})

    chunks = {position: (m, o) for position, m, o in decode_smooth_grid(blob)}
    check(set(chunks) == {(0, -1, 0), (-1, -1, -1)}, f"chunk positions decode from deltas ({sorted(chunks)})")
    m, o = chunks[(0, -1, 0)]
    at = lambda x, y, z: x + 32 * z + 1024 * y  # noqa: E731
    check(m[at(2, 31, 2)] == GRASS and o[at(2, 31, 2)] == 255, "a full grass voxel decodes in x, z, y order")
    check(m[at(0, 31, 0)] == GRASS and o[at(0, 31, 0)] == 127, "a partly filled voxel keeps its occupancy")
    check(m[at(5, 31, 1)] == WATER and m[at(3, 31, 0)] == 0, "water, and air around it")

    with tempfile.TemporaryDirectory(prefix="rhr-terrain-") as directory:
        place = Path(directory) / "terrain.rbxlx"
        place.write_text(f'''<roblox version="4">
  <Item class="Workspace" referent="W"><Properties><string name="Name">Workspace</string></Properties>
    <Item class="Terrain" referent="T"><Properties><string name="Name">Terrain</string>
      <BinaryString name="SmoothGrid">{base64.b64encode(blob).decode()}</BinaryString></Properties></Item>
    <Item class="Camera" referent="C"><Properties><string name="Name">Camera</string>
      <CoordinateFrame name="CFrame"><X>6</X><Y>10</Y><Z>24</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>0.8</R11><R12>0.6</R12><R20>0</R20><R21>-0.6</R21><R22>0.8</R22></CoordinateFrame>
      <float name="FieldOfView">60</float></Properties></Item>
  </Item>
  <Item class="Lighting" referent="L"><Properties><string name="Name">Lighting</string></Properties></Item>
</roblox>
''', encoding="utf-8")
        payload = terrain_payload(place)
        check(payload is not None and len(payload["chunks"]) == 2, "the place's terrain is read from the file")

        png = Path(directory) / "terrain.png"
        proc = subprocess.run([sys.executable, "-m", "rhr", "scene", str(place), "--viewport", "320x240",
                               "--flat-materials", "--out", str(png)],
                              capture_output=True, text=True, cwd=str(REPO), timeout=300)
        check(proc.returncode == 0, f"scene renders a place with terrain ({proc.stderr.strip()[-120:]})")
        check("terrain drawn smooth" in proc.stderr, "a note says terrain is drawn smooth")
        if proc.returncode == 0:
            from PIL import Image
            import numpy as np

            with Image.open(png).convert("RGB") as img:
                rgb = np.asarray(img).astype(int)
            green = (rgb[..., 1] > rgb[..., 0] + 25) & (rgb[..., 1] > rgb[..., 2] + 10)
            check(green.mean() > 0.02, f"the grass floor is on screen ({green.mean():.1%} green pixels)")

    print("terrain: ok" if not failures else f"terrain: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
