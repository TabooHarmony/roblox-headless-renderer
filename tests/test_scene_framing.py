#!/usr/bin/env python3
"""Standard views frame the build, not the Baseplate under it.

Nearly every place has a 2048-stud Baseplate. Framing it with `--view iso` left the
build a few pixels wide in the middle of a grey slab. A thin slab whose footprint
dwarfs everything else is left out of the framing (still drawn), the command says
so, and `--focus` on the slab itself still frames it.

    python tests/test_scene_framing.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = REPO / "tests" / "fixtures" / "scene_baseplate.rbxmx"
OUT = REPO / "out" / "scene-framing"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def red_share(png: Path) -> float:
    from PIL import Image

    import numpy as np

    with Image.open(png).convert("RGB") as img:
        rgb = np.asarray(img).astype(int)
    red = (rgb[..., 0] > 120) & (rgb[..., 1] < 80) & (rgb[..., 2] < 80)
    return float(red.mean())


def scene(name: str, *args: str) -> tuple[Path, subprocess.CompletedProcess]:
    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / f"{name}.png"
    proc = subprocess.run([*RHR, "scene", str(FIXTURE), "--viewport", "320x240", "--out", str(png), *args],
                          capture_output=True, text=True, cwd=str(REPO), timeout=300)
    assert proc.returncode == 0, proc.stderr
    return png, proc


def main() -> int:
    png, proc = scene("iso", "--view", "iso")
    share = red_share(png)
    check(share > 0.05, f"--view iso frames the build, not the Baseplate ({share:.1%} of pixels)")
    check("framing left out ground Workspace/Baseplate" in proc.stderr,
          "the command says the Baseplate was left out of the framing")

    png, proc = scene("focus-baseplate", "--focus", "Workspace/Baseplate")
    share = red_share(png)
    check(share < 0.01, f"--focus on the Baseplate still frames the whole slab ({share:.1%})")
    check("framing left out" not in proc.stderr, "no framing note when --focus is given")

    print("scene framing: ok" if not failures else f"scene framing: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
