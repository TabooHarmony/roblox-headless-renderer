#!/usr/bin/env python3
"""Bounded directional shadows are opt-in, deterministic, and respect GlobalShadows."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests/fixtures/scene_lighting.rbxmx"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(RHR), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


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


def mean_delta(a: Path, b: Path) -> float:
    with Image.open(a).convert("RGB") as first, Image.open(b).convert("RGB") as second:
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-shadows-") as directory:
        tmp = Path(directory)
        ir = tmp / "lighting.json"
        proc = run("ir", str(FIXTURE), "--out", str(ir))
        assert proc.returncode == 0, proc.stderr

        plain = tmp / "plain.png"
        shadowed = tmp / "shadowed.png"
        shadowed2 = tmp / "shadowed2.png"
        base = ["scene", str(ir), "--viewport", "360x240", "--view", "iso"]

        proc = run(*base, "--out", str(plain))
        assert proc.returncode == 0, proc.stderr
        for output in (shadowed, shadowed2):
            proc = run(*base, "--shadows", "--out", str(output))
            assert proc.returncode == 0, proc.stderr
        assert shadowed.read_bytes() == shadowed2.read_bytes(), "shadow pass is not deterministic"

        delta = mean_delta(plain, shadowed)
        assert delta > 0.25, f"shadow pass had no visible effect ({delta})"

        disabled_data = json.loads(ir.read_text())
        lighting = next(find_class(root, "Lighting") for root in disabled_data["roots"] if find_class(root, "Lighting"))
        lighting["props"]["GlobalShadows"] = False
        disabled_ir = tmp / "disabled.json"
        disabled_ir.write_text(json.dumps(disabled_data))
        disabled_png = tmp / "disabled.png"
        proc = run("scene", str(disabled_ir), "--viewport", "360x240", "--view", "iso", "--shadows", "--out", str(disabled_png))
        assert proc.returncode == 0, proc.stderr
        disabled_delta = mean_delta(plain, disabled_png)
        assert disabled_delta < 0.02, f"GlobalShadows=false still changed the frame ({disabled_delta})"

    print(f"scene shadows: visible delta={delta:.2f}, disabled delta={disabled_delta:.3f}")


if __name__ == "__main__":
    main()
