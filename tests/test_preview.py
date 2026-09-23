#!/usr/bin/env python3
"""Unified preview composes the 3D scene with ScreenGui in one PNG."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests/fixtures/preview_world_ui.rbxmx"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-preview-test-") as directory:
        out = Path(directory) / "preview.png"
        proc = subprocess.run(
            [
                str(RHR), "preview", str(FIXTURE),
                "--viewport", "360x240",
                "--camera", "0,0,-14",
                "--look-at", "0,0,0",
                "--topbar-height", "0",
                "--out", str(out),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert out.is_file()
        red = 0
        green = 0
        with Image.open(out).convert("RGB") as image:
            assert image.size == (360, 240)
            for r, g, b in image.get_flattened_data():
                if r > 120 and r > g * 1.5 and r > b * 1.5:
                    red += 1
                if g > 150 and g > r * 1.5 and g > b * 1.5:
                    green += 1
        assert red > 1500, red
        assert green > 3000, green
        assert "preview " in proc.stderr

    print(f"preview: red world pixels={red}, green ScreenGui pixels={green}")


if __name__ == "__main__":
    main()
