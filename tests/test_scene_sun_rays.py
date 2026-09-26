#!/usr/bin/env python3
"""SunRaysEffect: looking at the sun, the rays brighten the sky around it, and a bar
in front of the sun casts a shadow through them (the far side of the bar stays
darker than the open side). Disabled rays change nothing.

    python tests/test_scene_sun_rays.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
failures: list[str] = []

# Lighting.ClockTime 14 at the default latitude: Studio's GetSunDirection().
SUN = (-0.47489210963249207, 0.8225368857383728, 0.3129066228866577)


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def place(enabled: bool) -> str:
    # A dark bar 60 studs toward the sun, covering the left half of it: its CFrame
    # looks back at the camera, shifted along its own X.
    import numpy as np

    eye = np.array([0.0, 50.0, 0.0])
    sun = np.array(SUN)
    back = -sun  # the bar faces the camera: its look vector points back along -sun
    right = np.cross([0.0, 1.0, 0.0], -back)
    right /= np.linalg.norm(right)
    up = np.cross(-back, right)
    centre = eye + sun * 60 + right * 3.5  # "right" points to the left of the screen here
    r = np.stack([right, up, back], axis=1)  # columns: X, Y, Z (Z = -look)
    cf = "".join(f"<R{i}{j}>{r[i, j]}</R{i}{j}>" for i in range(3) for j in range(3))
    return f'''<roblox version="4">
  <Item class="Workspace" referent="W"><Properties><string name="Name">Workspace</string></Properties>
    <Item class="Part" referent="P"><Properties><string name="Name">Bar</string>
      <bool name="Anchored">true</bool>
      <Vector3 name="size"><X>6</X><Y>40</Y><Z>1</Z></Vector3>
      <CoordinateFrame name="CFrame"><X>{centre[0]}</X><Y>{centre[1]}</Y><Z>{centre[2]}</Z>{cf}</CoordinateFrame>
      <Color3uint8 name="Color3uint8">4282137660</Color3uint8></Properties></Item>
  </Item>
  <Item class="Lighting" referent="L"><Properties><string name="Name">Lighting</string>
      <float name="ClockTime">14</float></Properties>
    <Item class="SunRaysEffect" referent="R"><Properties><string name="Name">SunRays</string>
      <bool name="Enabled">{"true" if enabled else "false"}</bool>
      <float name="Intensity">0.25</float><float name="Spread">0.3</float></Properties></Item>
  </Item>
</roblox>
'''


def main() -> int:
    from PIL import Image
    import numpy as np

    images = {}
    look = f"{SUN[0] * 100},{50 + SUN[1] * 100},{SUN[2] * 100}"
    with tempfile.TemporaryDirectory(prefix="rhr-rays-") as directory:
        for name, enabled in (("on", True), ("off", False)):
            path = Path(directory) / f"{name}.rbxlx"
            path.write_text(place(enabled), encoding="utf-8")
            png = Path(directory) / f"{name}.png"
            proc = subprocess.run([sys.executable, "-m", "rhr", "scene", str(path), "--viewport", "400x250",
                                   "--no-shadows", "--camera", "0,50,0", "--look-at", look, "--fov", "70",
                                   "--out", str(png)],
                                  capture_output=True, text=True, cwd=str(REPO), timeout=300)
            check(proc.returncode == 0, f"scene renders sun rays {name} ({proc.stderr.strip()[-120:]})")
            if proc.returncode != 0:
                return 1
            with Image.open(png).convert("L") as img:
                images[name] = np.asarray(img).astype(float)
    on, off = images["on"], images["off"]
    h, w = on.shape
    added = on - off
    open_side = added[h // 2 - 40:h // 2 + 40, w // 2 + 40:w // 2 + 90].mean()
    shadow_side = added[h // 2 - 40:h // 2 + 40, w // 2 - 110:w // 2 - 60].mean()
    check(open_side > 25, f"the rays brighten the sky beside the sun ({open_side:.0f} levels)")
    check(shadow_side < open_side - 10,
          f"the bar's side is in its shadow ({shadow_side:.0f} vs {open_side:.0f} levels added)")

    print("sun rays: ok" if not failures else f"sun rays: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
