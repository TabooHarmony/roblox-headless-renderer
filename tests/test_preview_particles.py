#!/usr/bin/env python3
"""preview draws particles inside the 3D scene by default; --no-effects leaves them out."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests/fixtures/particle_scene.rbxmx"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-preview-particles-") as directory:
        tmp = Path(directory)
        common = [
            "preview", str(FIXTURE),
            "--viewport", "320x240",
            "--camera", "0,4,14",
            "--look-at", "0,1,0",
            "--fov", "70",
            # The fixture's particle texture (a texture that cannot be loaded draws nothing).
            "--texture-dir", str(ROOT / "tests" / "fixtures" / "particle-textures"),
        ]
        plain = tmp / "plain.png"
        effects = tmp / "effects.png"
        legacy = tmp / "legacy.png"
        proc = run(*common, "--no-effects", "--out", str(plain))
        assert proc.returncode == 0, proc.stderr
        proc = run(*common, "--seed", "7", "--out", str(effects))
        assert proc.returncode == 0, proc.stderr
        assert "particles:" in proc.stderr, proc.stderr
        # --time is the old spelling of --effect-time.
        proc = run(*common, "--seed", "7", "--time", "0.5", "--out", str(legacy))
        assert proc.returncode == 0, proc.stderr

        with Image.open(plain).convert("RGB") as a, Image.open(effects).convert("RGB") as b:
            mean_delta = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
        assert mean_delta > 0.1, mean_delta

    print(f"preview particles: in-scene by default, composite delta={mean_delta:.2f}, --time still accepted")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
