#!/usr/bin/env python3
"""Unified preview can add a transparent, camera-synchronized particle layer."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests/fixtures/particle_scene.rbxmx"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def main() -> None:
    from rhr.ir import emit_ir
    from rhr.scene import render_particle_sheet, render_scene

    with tempfile.TemporaryDirectory(prefix="rhr-preview-particles-") as directory:
        tmp = Path(directory)
        ir = tmp / "particle.json"
        emit_ir(FIXTURE, ir)

        resolved: dict = {}
        world = tmp / "world.png"
        render_scene(ir, world, 320, 240, view="iso", camera_state_out=resolved)
        assert len(resolved.get("position", [])) == 3, resolved
        assert len(resolved.get("quaternion", [])) == 4, resolved
        assert isinstance(resolved.get("fov"), (int, float)), resolved

        layer = tmp / "layer.png"
        render_particle_sheet(
            ir,
            layer,
            320,
            240,
            [0.5],
            7,
            20,
            effects_only=True,
            camera=(0, 4, 14),
            look_at=(0, 1, 0),
            fov=70,
        )
        with Image.open(layer).convert("RGBA") as image:
            alpha = image.getchannel("A")
            lo, hi = alpha.getextrema()
            assert lo == 0, (lo, hi)
            assert hi > 0, (lo, hi)

        plain = tmp / "plain.png"
        effects = tmp / "effects.png"
        common = [
            "preview", str(ir),
            "--viewport", "320x240",
            "--camera", "0,4,14",
            "--look-at", "0,1,0",
            "--fov", "70",
        ]
        proc = run(*common, "--out", str(plain))
        assert proc.returncode == 0, proc.stderr
        proc = run(
            *common,
            "--time", "0.5",
            "--seed", "7",
            "--burst", "20",
            "--out", str(effects),
        )
        assert proc.returncode == 0, proc.stderr

        with Image.open(plain).convert("RGB") as a, Image.open(effects).convert("RGB") as b:
            mean_delta = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
        assert mean_delta > 0.1, mean_delta

        auto = tmp / "auto.png"
        proc = run(
            "preview", str(ir),
            "--viewport", "320x240",
            "--view", "iso",
            "--time", "0.5",
            "--seed", "7",
            "--burst", "20",
            "--out", str(auto),
        )
        assert proc.returncode == 0, proc.stderr
        assert auto.is_file()

    print(
        f"preview particles: transparent layer alpha={lo}..{hi}, "
        f"composite delta={mean_delta:.2f}, auto-view camera shared"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
