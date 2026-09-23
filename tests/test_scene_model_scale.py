#!/usr/bin/env python3
"""Model.Scale is metadata: a saved model's parts render at their stored sizes.

Roblox's Model:ScaleTo() rewrites every descendant part's Size and CFrame; the
Model's `Scale` property only records the factor. A saved file therefore already
holds the scaled geometry, and applying Scale again would scale it twice. Evidence
from Roblox's own content (Studio ExtraContent/models/Photobooth/AbyssBlue.rbxm):
the Model saved with Scale=8 holds a MeshPart of Size 8 x 0.008 x 8, i.e. a
1 x 0.001 x 1 plane (0.001 is the minimum part thickness) already scaled by 8.

The fixture is a Model with Scale=1.5 and an authored WorldPivot. It must render
exactly like the same scene with that metadata removed, and scene-dump must report
the stored positions and sizes unchanged.

    python tests/test_scene_model_scale.py
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_scale.rbxmx"


def run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc


def walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def render(source: Path, out: Path) -> bytes:
    run(["scene", str(source), "--viewport", "480x360", "--camera", "0,0,16",
         "--look-at", "0,0,0", "--fov", "50", "--out", str(out)])
    return out.read_bytes()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-model-scale-") as directory:
        tmp = Path(directory)
        ir_path = tmp / "scaled.json"
        run(["ir", str(FIXTURE), "--out", str(ir_path)])
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        model = next(node for root in ir["roots"] for node in walk(root) if node["className"] == "Model")
        assert float(model["props"]["Scale"]) == 1.5, model["props"].get("Scale")

        plain = copy.deepcopy(ir)
        for node in (n for root in plain["roots"] for n in walk(root)):
            if node["className"] == "Model":
                for name in ("Scale", "WorldPivot", "PrimaryPart"):
                    node["props"].pop(name, None)
        plain_path = tmp / "plain.json"
        plain_path.write_text(json.dumps(plain), encoding="utf-8")

        scaled_png = render(ir_path, tmp / "scaled.png")
        plain_png = render(plain_path, tmp / "plain.png")
        assert scaled_png == plain_png, "Model.Scale changed the render; stored parts must render as-is"

        dump = json.loads(run(["scene-dump", str(ir_path)]).stdout)
        stored = {
            node["path"]: node["props"]
            for root in ir["roots"] for node in walk(root) if node["className"] == "Part"
        }
        compared = 0
        for entry in dump["parts"]:
            props = stored.get(entry["path"])
            if props is None:
                continue
            compared += 1
            expected_size = [props["Size"][axis] for axis in ("X", "Y", "Z")]
            expected_position = [props["CFrame"][axis] for axis in ("X", "Y", "Z")]
            assert entry["size"] == [round(value, 6) for value in expected_size], entry
            assert entry["position"] == [round(value, 6) for value in expected_position], entry
        assert compared == len(stored) == 2, (compared, sorted(stored))

    print(f"scene model scale: metadata only, {len(stored)} parts at stored size and position")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
