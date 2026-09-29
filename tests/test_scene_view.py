#!/usr/bin/env python3
"""Standard views are Roblox's sides: `front` looks at the Front face (-Z).

With `--focus`, the view follows the thing focused: a model turned a quarter in the
place (its PrimaryPart's CFrame) is still seen from its own front. Read from the
camera the `--json` report gives, not from pixels.

    python tests/test_scene_view.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def part(name: str, x: float, rotation: tuple[float, ...], ref: int) -> dict:
    r = rotation
    return {
        "className": "Part", "name": name, "id": ref,
        "props": {
            "CFrame": {"_t": "CFrame", "X": x, "Y": 2, "Z": 0,
                       "R00": r[0], "R01": r[1], "R02": r[2], "R10": r[3], "R11": r[4], "R12": r[5],
                       "R20": r[6], "R21": r[7], "R22": r[8]},
            "Size": {"_t": "Vector3", "X": 4, "Y": 2, "Z": 8},
            "Color": {"_t": "Color3", "R": 0.8, "G": 0.3, "B": 0.3},
            "Transparency": 0,
            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
        },
        "children": [],
    }


def write_ir(path: Path) -> None:
    straight = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    # A quarter turn about Y: the part's LookVector (-Z in its own frame) is world -X.
    turned = (0, 0, 1, 0, 1, 0, -1, 0, 0)
    path.write_text(json.dumps({"sourcePath": "view-test", "roots": [{
        "className": "Workspace", "name": "Workspace", "props": {}, "children": [
            {"className": "Model", "name": "Straight", "props": {}, "refs": {"PrimaryPart": 1},
             "children": [part("Body", -20, straight, 1)]},
            {"className": "Model", "name": "Turned", "props": {}, "refs": {"PrimaryPart": 2},
             "children": [part("Body", 20, turned, 2)]},
        ]}]}), encoding="utf-8")


def camera(ir: Path, out: Path, *args: str) -> list[float]:
    proc = subprocess.run([*RHR, "scene", str(ir), "--viewport", "240x180", "--json", "--out", str(out), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["camera"]["position"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-view-") as directory:
        tmp = Path(directory)
        ir = tmp / "view.json"
        write_ir(ir)
        x, _, z = camera(ir, tmp / "front.png", "--view", "front")
        assert z < -5 and abs(x - 1) < 1, ("front stands at -Z (Roblox's Front face)", x, z)  # (centre x=1)
        x, _, z = camera(ir, tmp / "back.png", "--view", "back")
        assert z > 5, ("back stands at +Z", x, z)
        x, _, z = camera(ir, tmp / "iso.png", "--view", "iso")
        assert x > 0 and z < 0, ("iso stands at the front right", x, z)
        x, _, z = camera(ir, tmp / "straight.png", "--focus", "Workspace/Straight", "--view", "front")
        assert z < -5 and abs(x + 20) < 1, ("a model facing -Z: seen from -Z", x, z)
        x, _, z = camera(ir, tmp / "turned.png", "--focus", "Workspace/Turned", "--view", "front")
        assert x < 20 - 5 and abs(z) < 1, ("a model turned to face -X: seen from its own front, at -X", x, z)
    print("scene view: front is Roblox's Front (-Z), and follows a focused model's PrimaryPart")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
