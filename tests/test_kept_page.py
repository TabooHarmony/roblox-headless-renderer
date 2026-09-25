#!/usr/bin/env python3
"""The warm worker's kept 3D page leaves nothing behind between renders.

Several scenes go through one kept page in turn (parts, particles, Highlights, then
the first ones again); every picture must match a render on a fresh page pixel for
pixel, and the kept page (not the fresh-page fallback) must have drawn them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURES = ROOT / "tests" / "fixtures"
TEXTURES = ["--texture-dir", str(FIXTURES / "particle-textures")]
SCENES = [
    ("geometry", [str(FIXTURES / "scene_geometry.rbxmx")]),
    ("vfx", [str(FIXTURES / "vfx_played.rbxm"), *TEXTURES, "--camera", "0,5,30", "--look-at", "0,8,0"]),
    ("highlight", [str(FIXTURES / "highlight.rbxm"), "--camera", "0,5,30", "--look-at", "0,5,0"]),
]


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180,
                          env=dict(os.environ, **(env or {})))
    assert proc.returncode == 0, proc.stderr
    return proc


def main() -> None:
    run("browser", "stop")
    with tempfile.TemporaryDirectory(prefix="rhr-kept-page-") as directory:
        tmp = Path(directory)
        fresh = {}
        for name, args in SCENES:
            fresh[name] = tmp / f"fresh-{name}.png"
            run("scene", *args, "--viewport", "400x300", "--out", str(fresh[name]),
                env={"RHR_PERSISTENT_BROWSER": "0"})

        started = json.loads(run("browser", "start").stdout)
        assert started["running"] is True
        try:
            order = [*SCENES, SCENES[0], SCENES[1]]
            for i, (name, args) in enumerate(order):
                out = tmp / f"kept-{i}-{name}.png"
                proc = run("scene", *args, "--viewport", "400x300", "--out", str(out),
                           env={"RHR_PROFILE": "1"})
                assert "kept page" in proc.stderr and "fresh page used" not in proc.stderr, \
                    f"{name}: not drawn on the kept page\n{proc.stderr[-800:]}"
                with Image.open(fresh[name]).convert("RGBA") as a, Image.open(out).convert("RGBA") as b:
                    assert ImageChops.difference(a, b).getbbox() is None, f"{name} (render {i}) differs from a fresh page"
        finally:
            run("browser", "stop")

    print(f"kept page: {len(order)} renders of {len(SCENES)} scenes, each identical to a fresh page")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
