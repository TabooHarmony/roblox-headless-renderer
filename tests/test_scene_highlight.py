#!/usr/bin/env python3
"""Highlight: an AlwaysOnTop fill and outline show through a wall; an Occluded one does not.

Fixture (scripts/make_highlight_fixture.luau): a grey wall in front of two cubes. The
left cube's Highlight is AlwaysOnTop with a blue fill and a yellow outline; the right
cube's is Occluded with a red fill.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests" / "fixtures" / "highlight.rbxm"


def pixels(path: Path, test) -> list[tuple[int, int]]:
    with Image.open(path).convert("RGB") as image:
        width, height = image.size
        data = image.load()
        return [(x, y) for y in range(height) for x in range(width) if test(*data[x, y])]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-highlight-") as directory:
        out = Path(directory) / "highlight.png"
        proc = subprocess.run(
            [*RHR, "scene", str(FIXTURE), "--viewport", "480x320",
             "--camera", "0,5,30", "--look-at", "0,5,0", "--out", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        blue = pixels(out, lambda r, g, b: b > 180 and r < 60 and g < 120)
        yellow = pixels(out, lambda r, g, b: r > 200 and g > 180 and b < 80)
        red = pixels(out, lambda r, g, b: r > 180 and g < 60 and b < 60)
        assert len(blue) > 500, f"the AlwaysOnTop fill does not show through the wall ({len(blue)} px)"
        assert all(x < 240 for x, _ in blue), "the blue fill is not on the left cube"
        assert len(yellow) > 50, f"the outline is not drawn ({len(yellow)} px)"
        # The outline sits outside the fill: its pixels ring the blue area.
        bx = [x for x, _ in blue]
        assert min(x for x, _ in yellow) < min(bx) and max(x for x, _ in yellow) > max(bx), "outline not around the fill"
        assert not red, f"the Occluded Highlight shows through the wall ({len(red)} px)"

    print(f"highlight: on-top fill {len(blue)} px with outline {len(yellow)} px through the wall, occluded one hidden")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
