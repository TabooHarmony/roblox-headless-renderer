#!/usr/bin/env python3
"""What a real place needs, found by running RHR on Roblox's own game template.

- In a place, only StarterGui's ScreenGuis are drawn; ScreenGuis kept elsewhere
  (ReplicatedStorage templates that scripts clone in) are named in a note and left
  out, unless `--all-guis`. The template stacked five such GUIs on its HUD.
- A part's MaterialVariant draws with the variant's own ColorMap when it is cached.
- A MeshPart whose mesh is not cached is a placeholder box coloured by its
  SurfaceAppearance's ColorMap (the part itself is usually white), not a white block.
- Only the most relevant local lights are drawn (a hundred SpotLights made one frame
  take 20 s in software); the rest are counted in a note.

    python tests/test_place_realism.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
GUIS = FIXTURES / "place_stored_guis.rbxlx"
SCENE = FIXTURES / "scene_variants_placeholders.rbxlx"
TEXTURES = FIXTURES / "variant-textures"
OUT = REPO / "out" / "place-realism"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def rhr(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "rhr", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(REPO), timeout=300)


def main() -> int:
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)

    proc = rhr("layout", str(GUIS), "--viewport", "300x200")
    rects = json.loads(proc.stdout)["rects"] if proc.returncode == 0 else {}
    check("StarterGui/Hud/Bar" in rects, "StarterGui's ScreenGui is laid out")
    check(not any(p.startswith("ReplicatedStorage/") for p in rects),
          "a ScreenGui stored in ReplicatedStorage is not laid out")
    check("ReplicatedStorage/VictoryTemplate" in proc.stderr and "--all-guis" in proc.stderr,
          "the left-out ScreenGui is named, with the flag that draws it")

    proc = rhr("layout", str(GUIS), "--viewport", "300x200", "--all-guis")
    rects = json.loads(proc.stdout)["rects"] if proc.returncode == 0 else {}
    check("ReplicatedStorage/VictoryTemplate/Cover" in rects, "--all-guis lays out the stored ScreenGui too")

    png = OUT / "gui.png"
    proc = rhr("render", str(GUIS), "--viewport", "300x200", "--transparent", "--out", str(png))
    with Image.open(png).convert("RGBA") as img:
        check(proc.returncode == 0 and img.getpixel((150, 150))[3] == 0,
              f"the stored full-screen template does not cover the render ({img.getpixel((150, 150))})")
    for command in ("hitmap", "check"):
        proc = rhr(command, str(GUIS))
        check(proc.returncode == 0 and "ReplicatedStorage" not in proc.stdout,
              f"{command} ignores the stored ScreenGui too")

    png = OUT / "scene.png"
    proc = rhr("scene", str(SCENE), "--viewport", "400x240", "--texture-dir", str(TEXTURES), "--out", str(png))
    check(proc.returncode == 0, f"scene renders ({proc.stderr.strip()[-120:]})")
    with Image.open(png).convert("RGB") as img:
        wall, bush = img.getpixel((140, 120)), img.getpixel((260, 120))
    check(wall[1] > wall[0] + 40 and wall[1] > wall[2] + 40,
          f"the white wall draws its MaterialVariant's green ColorMap ({wall})")
    check(bush[0] > bush[1] + 60 and bush[0] > bush[2] + 60,
          f"the uncached MeshPart takes its SurfaceAppearance's red, not white ({bush})")
    check("16 most relevant local lights; 4 farther ones were left out" in proc.stderr,
          "20 PointLights: 16 drawn, and a note counts the 4 left out")

    print("place realism: ok" if not failures else f"place realism: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
