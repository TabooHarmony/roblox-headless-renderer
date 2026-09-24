#!/usr/bin/env python3
"""Material textures add detail without changing a part's colour.

RHR ships CC0 look-alike textures (src/rhr/scene/materials, credits.json) because
Roblox's own cannot be redistributed. A Brick or WoodPlanks part shows a pattern
tinted by its Color; Plastic stays plain; `--flat-materials` turns textures off.

    python tests/test_scene_material_textures.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "scene_material_textures.rbxmx"
MATERIALS = REPO / "src" / "rhr" / "scene" / "materials"
OUT = REPO / "out" / "scene-material-textures"
# The camera looks from -Z, so the parts appear right to left: Brick, WoodPlanks, Plastic.
REGIONS = {"Plastic": (140, 75, 190, 125), "WoodPlanks": (215, 75, 265, 125), "Brick": (290, 75, 340, 125)}

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def render(name: str, *extra: str):
    import numpy as np
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / f"{name}.png"
    proc = subprocess.run([sys.executable, "-m", "rhr", "scene", str(FIXTURE), "--viewport", "480x200",
                           "--out", str(png), *extra], capture_output=True, text=True, cwd=str(REPO), timeout=300)
    assert proc.returncode == 0, proc.stderr
    with Image.open(png).convert("RGB") as img:
        return np.asarray(img).astype(float)


def stats(image, region):
    x0, y0, x1, y1 = region
    crop = image[y0:y1, x0:x1]
    return crop.reshape(-1, 3).mean(axis=0), float(crop.mean(axis=2).std())


def main() -> int:
    credits = json.loads((MATERIALS / "credits.json").read_text(encoding="utf-8"))["materials"]
    check(all((MATERIALS / f"{name}.jpg").is_file() for name in credits),
          f"every credited material has its texture ({len(credits)} materials)")
    check(all(entry["license"] == "CC0 1.0" for entry in credits.values()), "every texture is CC0")

    textured, flat = render("textured"), render("flat", "--flat-materials")
    for name, region in REGIONS.items():
        (mean_t, std_t), (mean_f, std_f) = stats(textured, region), stats(flat, region)
        if name == "Plastic":
            check(abs(std_t - std_f) < 0.5 and abs(mean_t - mean_f).max() < 1.0,
                  f"Plastic stays plain (std {std_t:.1f} vs {std_f:.1f})")
            continue
        check(std_t > std_f + 1.5, f"{name} shows a pattern (std {std_t:.1f} vs flat {std_f:.1f})")
        # Tinted, not recoloured: the average stays near the flat colour, per channel.
        ratio = (mean_t + 1) / (mean_f + 1)
        check(bool((ratio > 0.6).all() and (ratio < 1.25).all()),
              f"{name} keeps its colour (textured/flat per channel {ratio.round(2).tolist()})")

    print("material textures: ok" if not failures else f"material textures: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
