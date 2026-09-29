#!/usr/bin/env python3
"""`rhr scene --views` draws several standard views on one build of the scene.

Each view must match `rhr scene --view <that view>` pixel for pixel (the views after
the first undo what the one before drew for its camera: particles, beams, pruned
lights, fog, the sky visibility grid, in-world GUIs), the JSON report lists every
view with its own camera, and --views refuses a camera of its own.

    python tests/test_scene_views.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURES = ROOT / "tests" / "fixtures"
SCENES = {
    "geometry": [str(FIXTURES / "scene_geometry.rbxmx")],
    "vfx": [str(FIXTURES / "vfx_played.rbxm"), "--texture-dir", str(FIXTURES / "particle-textures")],
    "highlight": [str(FIXTURES / "highlight.rbxm")],
}
VIEWS = ["iso", "front", "top", "right"]


def run(*args: str, ok: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    if ok:
        assert proc.returncode == 0, proc.stderr
    return proc


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-views-") as directory:
        tmp = Path(directory)
        for name, args in SCENES.items():
            report = json.loads(run("scene", *args, "--viewport", "400x300", "--views", ",".join(VIEWS),
                                    "--out", str(tmp / f"{name}.png"), "--json").stdout)
            assert [view["view"] for view in report["views"]] == VIEWS, report["views"]
            assert report["out"] == report["views"][0]["out"]
            directions = {tuple(view["camera"]["lookDirection"]) for view in report["views"]}
            assert len(directions) == len(VIEWS), f"{name}: the views share a camera"
            for view in report["views"]:
                one = tmp / f"{name}-one-{view['view']}.png"
                single = json.loads(run("scene", *args, "--viewport", "400x300", "--view", view["view"],
                                        "--out", str(one), "--json").stdout)
                assert single["camera"] == view["camera"], f"{name} {view['view']}: another camera"
                with Image.open(one).convert("RGBA") as a, Image.open(view["out"]).convert("RGBA") as b:
                    assert ImageChops.difference(a, b).getbbox() is None, \
                        f"{name} {view['view']}: differs from a render of that view alone"
        refused = run("scene", *SCENES["geometry"], "--views", "iso,top", "--view", "front", ok=False)
        assert refused.returncode == 2 and "--views" in refused.stderr, refused.stderr
        bad = run("scene", *SCENES["geometry"], "--views", "iso,sideways", ok=False)
        assert bad.returncode == 2 and "sideways" in bad.stderr, bad.stderr
    print(f"scene --views: {len(SCENES)} scenes x {len(VIEWS)} views, each identical to a render of its own")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
