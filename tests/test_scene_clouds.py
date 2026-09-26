#!/usr/bin/env python3
"""Clouds (Terrain.Clouds) are drawn in the sky: an overcast Cover greys it out, and
disabled clouds leave the sky as it was. Needs the Studio install (the cloud tile).

    python tests/test_scene_clouds.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def place(cover: float, enabled: bool) -> str:
    return f'''<roblox version="4">
  <Item class="Workspace" referent="W"><Properties><string name="Name">Workspace</string></Properties>
    <Item class="Terrain" referent="T"><Properties><string name="Name">Terrain</string></Properties>
      <Item class="Clouds" referent="C"><Properties><string name="Name">Clouds</string>
        <float name="Cover">{cover}</float><float name="Density">0.7</float>
        <bool name="Enabled">{"true" if enabled else "false"}</bool></Properties></Item>
    </Item>
  </Item>
  <Item class="Lighting" referent="L"><Properties><string name="Name">Lighting</string></Properties></Item>
</roblox>
'''


def main() -> int:
    from rhr.studio import studio_install

    if studio_install() is None:
        print("clouds: skipped (no Roblox Studio install: the cloud tile comes from it)")
        return 0
    from PIL import Image
    import numpy as np

    saturation = {}
    with tempfile.TemporaryDirectory(prefix="rhr-clouds-") as directory:
        for name, cover, enabled in (("overcast", 0.9, True), ("off", 0.9, False)):
            path = Path(directory) / f"{name}.rbxlx"
            path.write_text(place(cover, enabled), encoding="utf-8")
            png = Path(directory) / f"{name}.png"
            proc = subprocess.run([sys.executable, "-m", "rhr", "scene", str(path), "--viewport", "320x200",
                                   "--camera", "0,50,0", "--look-at", "0,120,-100", "--fov", "60", "--out", str(png)],
                                  capture_output=True, text=True, cwd=str(REPO), timeout=300)
            check(proc.returncode == 0, f"scene renders the sky with clouds {name} ({proc.stderr.strip()[-120:]})")
            if proc.returncode != 0:
                continue
            noted = "clouds drawn as one still layer" in proc.stderr
            check(noted == enabled, f"the clouds note is there only when they are enabled ({name})")
            with Image.open(png).convert("RGB") as img:
                rgb = np.asarray(img).astype(float)
            sky = rgb[: rgb.shape[0] // 2]
            saturation[name] = float((sky.max(axis=2) - sky.min(axis=2)).mean())
    if len(saturation) == 2:
        check(saturation["overcast"] < 20 < saturation["off"],
              f"overcast clouds grey the sky out (colourfulness {saturation['overcast']:.0f} vs {saturation['off']:.0f} without)")

    print("clouds: ok" if not failures else f"clouds: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
