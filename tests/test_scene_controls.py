#!/usr/bin/env python3
"""Agent-facing scene camera controls and loud failure behavior."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RHR = ROOT / "bin" / "rhr"
SCENE = ROOT / "tests/fixtures/scene_geometry.rbxmx"
CAMERAS = ROOT / "tests/fixtures/scene_two_cameras.rbxmx"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(RHR), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def red_pixels(path: Path) -> list[tuple[int, int]]:
    pixels: list[tuple[int, int]] = []
    with Image.open(path).convert("RGB") as image:
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = image.getpixel((x, y))
                if r > 100 and r > g * 1.5 and r > b * 1.5:
                    pixels.append((x, y))
    return pixels


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-controls-") as directory:
        tmp = Path(directory)

        preferred = tmp / "preferred.png"
        proc = run("scene", str(CAMERAS), "--viewport", "320x240", "--out", str(preferred))
        assert proc.returncode == 0, proc.stderr
        red = red_pixels(preferred)
        assert red, "Workspace.CurrentCamera preference produced no visible target"
        xs = [point[0] for point in red]
        ys = [point[1] for point in red]
        center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        assert abs(center[0] - 160) < 35 and abs(center[1] - 120) < 35, center

        iso = tmp / "iso.png"
        proc = run(
            "scene",
            str(SCENE),
            "--viewport",
            "320x240",
            "--focus",
            "Scene/Props/RedBlock",
            "--view",
            "iso",
            "--out",
            str(iso),
        )
        assert proc.returncode == 0, proc.stderr
        assert red_pixels(iso), "focused iso view produced no target pixels"

        custom = tmp / "custom.png"
        proc = run(
            "scene",
            str(SCENE),
            "--viewport",
            "320x240",
            "--camera",
            "15,10,15",
            "--look-at",
            "2,3,-4",
            "--fov",
            "50",
            "--out",
            str(custom),
        )
        assert proc.returncode == 0, proc.stderr
        assert custom.read_bytes() != iso.read_bytes(), "camera override should change the render"

        proc = run("scene", str(SCENE), "--focus", "Scene/NoSuchNode", "--out", str(tmp / "bad.png"))
        assert proc.returncode != 0
        assert "focus path not found" in proc.stderr

        # ViewportFrame path validation now happens before Chromium, so a typo is
        # an explicit error instead of a successful transparent PNG.
        from rhr.scene import render_viewport
        from rhr.ir import emit_ir

        ir = tmp / "scene.json"
        emit_ir(SCENE, ir)
        try:
            render_viewport(ir, tmp / "missing.png", 160, 120, "Scene/NoSuchViewport")
        except ValueError as exc:
            assert "ViewportFrame path not found" in str(exc)
        else:
            raise AssertionError("missing ViewportFrame path rendered successfully")

    print("scene controls: ok")


if __name__ == "__main__":
    main()
