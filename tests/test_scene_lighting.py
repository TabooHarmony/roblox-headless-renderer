#!/usr/bin/env python3
"""Saved Lighting service properties reach the full-scene renderer."""

from __future__ import annotations

import sys
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests/fixtures/scene_lighting.rbxmx"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def find_class(node: dict, class_name: str) -> dict | None:
    if node.get("className") == class_name:
        return node
    children = node.get("children") or []
    if isinstance(children, dict):
        children = children.values()
    for child in children:
        found = find_class(child, class_name)
        if found:
            return found
    return None


def foreground_means(first: Path, second: Path) -> tuple[float, float]:
    """Mean brightness of the geometry in two renders of the same scene.

    The backdrop (Roblox's default sky for a place with Lighting) does not depend on
    Brightness, so pixels identical in both renders are the backdrop and excluded.
    """
    with Image.open(first).convert("RGB") as a, Image.open(second).convert("RGB") as b:
        pairs = [
            (sum(pa) / 3, sum(pb) / 3)
            for pa, pb in zip(a.get_flattened_data(), b.get_flattened_data())
            if pa != pb
        ]
    assert pairs
    return statistics.mean(x for x, _ in pairs), statistics.mean(y for _, y in pairs)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-lighting-") as directory:
        tmp = Path(directory)
        ir = tmp / "lighting.json"
        proc = run("ir", str(FIXTURE), "--out", str(ir))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(ir.read_text())
        lighting = next((find_class(root, "Lighting") for root in data["roots"] if find_class(root, "Lighting")), None)
        assert lighting is not None
        props = lighting["props"]
        assert props["GlobalShadows"] is True
        assert abs(props["ClockTime"] - 6) < 1e-6
        assert abs(props["GeographicLatitude"] - 35) < 1e-6
        assert "OutdoorAmbient" in props
        assert abs(props["ShadowSoftness"] - 0.35) < 1e-5

        dawn = tmp / "dawn.png"
        proc = run("scene", str(ir), "--viewport", "360x240", "--view", "iso", "--out", str(dawn))
        assert proc.returncode == 0, proc.stderr

        evening_data = json.loads(ir.read_text())
        evening_lighting = next(find_class(root, "Lighting") for root in evening_data["roots"] if find_class(root, "Lighting"))
        evening_lighting["props"]["ClockTime"] = 18
        evening = tmp / "evening.json"
        evening.write_text(json.dumps(evening_data))
        dusk = tmp / "dusk.png"
        proc = run("scene", str(evening), "--viewport", "360x240", "--view", "iso", "--out", str(dusk))
        assert proc.returncode == 0, proc.stderr

        with Image.open(dawn).convert("RGB") as a, Image.open(dusk).convert("RGB") as b:
            diff = ImageChops.difference(a, b)
            mean_delta = sum(ImageStat.Stat(diff).mean) / 3
        assert mean_delta > 1.0, mean_delta

        dark_data = json.loads(ir.read_text())
        dark_lighting = next(find_class(root, "Lighting") for root in dark_data["roots"] if find_class(root, "Lighting"))
        dark_lighting["props"]["Brightness"] = 0
        dark = tmp / "dark.json"
        dark.write_text(json.dumps(dark_data))
        dark_png = tmp / "dark.png"
        proc = run("scene", str(dark), "--viewport", "360x240", "--view", "iso", "--out", str(dark_png))
        assert proc.returncode == 0, proc.stderr
        normal_mean, dark_mean = foreground_means(dawn, dark_png)
        assert normal_mean > dark_mean + 10, (normal_mean, dark_mean)

        proc = run("scene-dump", str(ir))
        assert proc.returncode == 0
        dumped = json.loads(proc.stdout)["lighting"]
        assert dumped["path"] == "Lighting"
        assert dumped["globalShadows"] is True
        assert abs(dumped["clockTime"] - 6) < 1e-6

    print(f"scene lighting: clock delta={mean_delta:.2f}, brightness {dark_mean:.1f}->{normal_mean:.1f}")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
