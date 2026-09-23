#!/usr/bin/env python3
"""Fast IR profiles prune runtime nodes without changing static preview pixels."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rhr.ir import emit_ir  # noqa: E402

RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests/fixtures/ir_profiles.rbxmx"


def classes(data: dict) -> Counter:
    counts: Counter = Counter()

    def visit(node: dict) -> None:
        counts[node["className"]] += 1
        children = node.get("children") or []
        if isinstance(children, dict):
            children = children.values()
        for child in children:
            visit(child)

    for root in data["roots"]:
        visit(root)
    return counts


def find_named(data: dict, name: str) -> dict:
    def visit(node: dict) -> dict | None:
        if node.get("name") == name:
            return node
        children = node.get("children") or []
        if isinstance(children, dict):
            children = children.values()
        for child in children:
            found = visit(child)
            if found:
                return found
        return None

    for root in data["roots"]:
        found = visit(root)
        if found:
            return found
    raise AssertionError(f"missing node {name}")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*RHR, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-ir-profiles-") as directory:
        tmp = Path(directory)
        paths = {}
        data = {}
        for profile in ("full", "visual", "static"):
            path = tmp / f"{profile}.json"
            emit_ir(FIXTURE, path, profile=profile)
            paths[profile] = path
            data[profile] = json.loads(path.read_text())

        full = classes(data["full"])
        visual = classes(data["visual"])
        static = classes(data["static"])

        assert full["Sound"] == 1 and full["IntValue"] == 1 and full["ParticleEmitter"] == 1
        assert visual["Sound"] == 0 and visual["IntValue"] == 0
        assert visual["ParticleEmitter"] == 1
        assert static["Sound"] == 0 and static["IntValue"] == 0 and static["ParticleEmitter"] == 0
        assert visual["Folder"] == 1 and static["Folder"] == 1, "visual ancestor path was dropped"
        assert static["Part"] == 1 and static["ScreenGui"] == 2 and static["Frame"] == 2

        high = find_named(data["static"], "HighGui")
        high_panel = find_named(data["static"], "HighPanel")
        assert float(high["props"]["DisplayOrder"]) == 10
        assert float(high_panel["props"]["BorderSizePixel"]) == 0

        full_png = tmp / "full.png"
        static_png = tmp / "static.png"
        for ir, out in ((paths["full"], full_png), (paths["static"], static_png)):
            proc = run(
                "preview",
                str(ir),
                "--viewport",
                "320x220",
                "--topbar-height",
                "0",
                "--out",
                str(out),
            )
            assert proc.returncode == 0, proc.stderr

        assert full_png.read_bytes() == static_png.read_bytes(), "static profile changed preview pixels"

        with Image.open(static_png).convert("RGB") as image:
            # HighGui appears first in the file, LowGui second. Correct DisplayOrder
            # sorting must paint the high-order green panel last.
            r, g, b = image.getpixel((30, 30))
            assert g > 180 and g > r * 2 and g > b * 2, (r, g, b)

        print(
            "ir profiles: "
            f"nodes full={sum(full.values())} visual={sum(visual.values())} static={sum(static.values())}, "
            "static pixels identical, DisplayOrder preserved"
        )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
