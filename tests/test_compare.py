#!/usr/bin/env python3
"""Agent-facing render comparison separates shading changes from silhouette movement."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=60)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-compare-") as directory:
        tmp = Path(directory)
        before = tmp / "before.png"
        recolor = tmp / "recolor.png"
        moved = tmp / "moved.png"

        def make(path: Path, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
            image = Image.new("RGB", (100, 80), (32, 36, 43))
            ImageDraw.Draw(image).rectangle(rect, fill=color)
            image.save(path)

        make(before, (20, 20, 49, 49), (220, 40, 30))
        make(recolor, (20, 20, 49, 49), (30, 120, 240))
        make(moved, (35, 20, 64, 49), (220, 40, 30))

        proc = run("compare", str(before), str(recolor), "--json")
        assert proc.returncode == 0, proc.stderr
        color = json.loads(proc.stdout)
        assert color["changed_pct"] > 0
        assert color["silhouette"]["iou"] == 1.0, color["silhouette"]

        proc = run("compare", str(before), str(moved), "--json")
        assert proc.returncode == 0, proc.stderr
        geometry = json.loads(proc.stdout)
        assert 0 < geometry["silhouette"]["iou"] < 1, geometry["silhouette"]
        assert geometry["silhouette"]["iou"] < color["silhouette"]["iou"]
        assert geometry["diff_bbox"] is not None

        mismatch = tmp / "mismatch.png"
        Image.new("RGB", (10, 10), (0, 0, 0)).save(mismatch)
        proc = run("compare", str(before), str(mismatch), "--json")
        assert proc.returncode != 0

    print(
        f"compare: recolor IoU={color['silhouette']['iou']:.3f}, "
        f"moved IoU={geometry['silhouette']['iou']:.3f}, "
        f"moved changed={geometry['changed_pct']:.2f}%"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
