#!/usr/bin/env python3
"""Default outputs stay small enough for an agent to read, whatever the file's size.

An agent's shell tool cuts output (Claude Code at 30,000 characters) and every
kilobyte is paid in context. The full scene dump of a 116k-part place was 52 MB and
`inspect` of a real game 424 KB; the defaults are summaries, and the flags give the
detail. Generated here: a scene of 12,000 parts in 120 models, and a model with 600
scripts and 600 images.

    python tests/test_output_budget.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
BUDGET = 50_000  # bytes of JSON on stdout


def part(name: str, x: float, y: float) -> dict:
    return {"className": "Part", "name": name, "props": {
        "CFrame": {"_t": "CFrame", "X": x, "Y": y, "Z": 0, "R00": 1, "R01": 0, "R02": 0,
                   "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1},
        "Size": {"_t": "Vector3", "X": 2, "Y": 1, "Z": 2},
        "Color": {"_t": "Color3", "R": 0.5, "G": 0.5, "B": 0.5}, "Transparency": 0,
        "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
        "Shape": {"_t": "EnumItem", "name": "Block", "value": 1}}, "children": []}


def big_scene(path: Path) -> None:
    models = [{"className": "Model", "name": f"House{m}", "props": {},
               "children": [part(f"Brick{p}", m * 30 + (p % 10) * 2, (p // 10) * 1.0) for p in range(100)]}
              for m in range(120)]
    path.write_text(json.dumps({"sourcePath": "budget", "roots": [
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": models}]}), encoding="utf-8")


def many_scripts(path: Path) -> None:
    items = []
    for i in range(600):
        items.append(f'<Item class="ModuleScript" referent="S{i}"><Properties><string name="Name">Module{i}</string>'
                     f'<ProtectedString name="Source"><![CDATA[return {{ value = {i} }}\n]]></ProtectedString>'
                     f'</Properties></Item><Item class="Decal" referent="D{i}"><Properties><string name="Name">'
                     f'Decal{i}</string><Content name="Texture"><url>rbxassetid://{1000000 + i}</url></Content>'
                     f'</Properties></Item>')
    path.write_text('<roblox version="4"><Item class="Model" referent="M"><Properties><string name="Name">Big'
                    '</string></Properties>' + "".join(items) + '</Item></roblox>', encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-500:]
    return proc


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-budget-") as directory:
        tmp = Path(directory)
        scene = tmp / "scene.json"
        big_scene(scene)
        summary = run("scene-dump", str(scene)).stdout
        assert len(summary) < BUDGET, ("scene-dump summary", len(summary))
        doc = json.loads(summary)
        assert doc["schema"] == "rhr.scene-summary/1" and doc["parts"] == 12000, doc["parts"]
        assert doc["models"][0]["parts"] == 100 and doc["moreModels"] > 0, doc["models"][:2]
        one = json.loads(run("scene-dump", str(scene), "--path", "Workspace/House7").stdout)
        assert one["parts"] == 100 and one["models"][0]["path"].startswith("Workspace/House7/"), one["models"][:1]
        limited = json.loads(run("scene-dump", str(scene), "--parts", "--limit", "5").stdout)
        assert limited["schema"] == "rhr.scene-dump/1" and len(limited["parts"]) == 5
        assert limited["partsTotal"] == 12000, limited["partsTotal"]
        full = run("scene-dump", str(scene), "--parts").stdout
        assert len(full) > BUDGET and len(json.loads(full)["parts"]) == 12000, "--parts gives every part"

        model = tmp / "scripts.rbxmx"
        many_scripts(model)
        report = run("inspect", str(model)).stdout
        assert len(report) < BUDGET, ("inspect", len(report))
        doc = json.loads(report)
        assert doc["scriptsTotal"]["count"] == 600 and doc["assetCounts"]["images"] == 600, doc.get("scriptsTotal")
        everything = json.loads(run("inspect", str(model), "--all").stdout)
        assert len(everything["scripts"]) == 600 and len(everything["assets"]["images"]) == 600
    print("output budget: scene-dump and inspect stay under 50 KB by default; the flags give everything")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
