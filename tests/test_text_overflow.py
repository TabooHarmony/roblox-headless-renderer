#!/usr/bin/env python3
"""Unwrapped text longer than its label runs past the label, as in Studio.

tests/studio/ui_edge_cases.rbxlx has three 90x24 labels holding a 250px line, left-,
centre- and right-aligned (Studio's screenshot of the place: the text is not
clipped; it runs out to the right, both ways, and to the left). Here the dark text
pixels outside each label are counted on the side the text should run to.

    python tests/test_text_overflow.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLACE = REPO / "tests" / "studio" / "ui_edge_cases.rbxlx"
failures: list[str] = []

# Label rects in the place (x, y, w, h), from Studio's recorded truth.
LABELS = {"OverLeft": (20, 320, 90, 24), "OverCenter": (20, 360, 90, 24), "OverRight": (20, 400, 90, 24)}


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def main() -> int:
    from PIL import Image
    import numpy as np

    with tempfile.TemporaryDirectory(prefix="rhr-overflow-") as directory:
        png = Path(directory) / "overflow.png"
        proc = subprocess.run([sys.executable, "-m", "rhr", "ui", str(PLACE), "--viewport", "937x592",
                               "--topbar-height", "0", "--background", "#ffffff", "--out", str(png)],
                              capture_output=True, text=True, cwd=str(REPO), timeout=300)
        check(proc.returncode == 0, f"renders the edge-case place ({proc.stderr.strip()[-120:]})")
        if proc.returncode != 0:
            return 1
        with Image.open(png).convert("L") as img:
            grey = np.asarray(img).astype(int)

    def ink(x0: int, x1: int, y: int, h: int) -> int:
        x0, x1 = max(0, x0), max(0, x1)
        return int((grey[y:y + h, x0:x1] < 100).sum())

    x, y, w, h = LABELS["OverLeft"]
    check(ink(x + w + 2, x + w + 150, y, h) > 200, "left-aligned text runs past the label's right edge")
    x, y, w, h = LABELS["OverCenter"]
    check(ink(x + w + 2, x + w + 80, y, h) > 100 and ink(0, x - 2, y, h) > 20,
          "centred text runs past both edges")
    x, y, w, h = LABELS["OverRight"]
    check(ink(0, x - 2, y, h) > 20 and ink(x + w + 2, x + w + 80, y, h) < 10,
          "right-aligned text runs past the left edge only")

    print("text overflow: ok" if not failures else f"text overflow: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
