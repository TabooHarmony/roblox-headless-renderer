#!/usr/bin/env python3
"""RHR against ground truth that Roblox Studio recorded (docs/GOAL.md, Step 5).

Every place in tests/studio/ was built in Studio and carries ServerStorage.RHRTruth,
written there by scripts/studio/export_truth.luau: Studio's own AbsolutePosition /
AbsoluteSize for each GuiObject and position/size for each part. RHR must match it
"roughly" (within 2 px / 0.01 studs, scripts/studio/compare_truth.py).

Before the real places, a tooling self-check: a synthetic place (built with Rojo,
truth written by hand to match RHR) must pass, and the same place with one number
wrong must be reported, so a passing Studio comparison means something.

    python tests/test_studio_truth.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO_DIR = ROOT / "tests" / "studio"
sys.path.insert(0, str(ROOT / "scripts" / "studio"))

failures: list[str] = []

# Differences from Studio we know about and document (docs/known-approximations.md),
# keyed by place and reported path. They must keep failing: one that starts matching
# Studio fails this test until it is removed here, so the list cannot go stale.
KNOWN = {
    ("ui_text.rbxlx", "StarterGui/UIText/Backdrop/Roboto_Wrap (text)"):
        "18px Roboto measures ~6% narrower than Studio, so a line that overflows the "
        "172px label in Studio still fits in RHR and the label does not wrap",
}


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def synthetic_place(tmp: Path, truth: dict, name: str) -> Path:
    project = {
        "name": name,
        "tree": {
            "$className": "DataModel",
            "StarterGui": {
                "$className": "StarterGui",
                "HUD": {
                    "$className": "ScreenGui",
                    "Panel": {
                        "$className": "Frame",
                        "$properties": {
                            "Position": {"UDim2": [[0, 20], [0, 30]]},
                            "Size": {"UDim2": [[0, 200], [0, 100]]},
                        },
                    },
                },
            },
            "Workspace": {
                "$className": "Workspace",
                "Block": {"$className": "Part", "$properties": {"Size": {"Vector3": [2, 3, 4]}}},
            },
            "ServerStorage": {
                "$className": "ServerStorage",
                "RHRTruth": {"$className": "StringValue", "$properties": {"Value": {"String": json.dumps(truth)}}},
            },
        },
    }
    project_path = tmp / f"{name}.project.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    out = tmp / f"{name}.rbxlx"
    proc = subprocess.run([shutil.which("rojo") or "rojo", "build", str(project_path), "--output", str(out)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return out


def main() -> int:
    from compare_truth import compare

    truth = {
        "format": "rhr-studio-truth/1",
        "viewport": [400, 300],
        "guiInset": [0, 0],
        "gui": {"StarterGui/HUD/Panel": {"x": 20, "y": 30, "w": 200, "h": 100, "visible": True}},
        "parts": {"Workspace/Block": {"position": [0, 0, 0], "orientation": [0, 0, 0], "size": [2, 3, 4]}},
    }
    print("studio truth: comparison tooling self-check (synthetic place)")
    with tempfile.TemporaryDirectory(prefix="rhr-truth-") as directory:
        tmp = Path(directory)
        report = compare(synthetic_place(tmp, truth, "Matching"), 2.0, 0.01, 0.0)
        check(report["passed"] and report["gui"]["ok"] == 1 and report["parts"]["ok"] == 1,
              f"matching truth passes ({report['gui']}, {report['parts']})")

        wrong = json.loads(json.dumps(truth))
        wrong["gui"]["StarterGui/HUD/Panel"]["x"] = 26
        wrong["parts"]["Workspace/Block"]["size"] = [2, 3, 5]
        wrong["gui"]["StarterGui/HUD/Ghost"] = {"x": 0, "y": 0, "w": 1, "h": 1, "visible": True}
        report = compare(synthetic_place(tmp, wrong, "Wrong"), 2.0, 0.01, 0.0)
        statuses = {row["path"]: row["status"] for row in report["problems"]}
        check(not report["passed"], "wrong truth fails")
        check(statuses == {
            "StarterGui/HUD/Panel": "off",
            "Workspace/Block": "off",
            "StarterGui/HUD/Ghost": "missing",
        }, f"each problem is named: {statuses}")

    places = sorted(p for p in STUDIO_DIR.glob("*.rbxl*") if p.suffix in {".rbxl", ".rbxlx"}) if STUDIO_DIR.is_dir() else []
    print(f"studio truth: {len(places)} Studio-recorded place(s) in tests/studio/")
    for place in places:
        report = compare(place, 2.0, 0.01, 0.0)
        problems = {row["path"]: row for row in report["problems"]}
        known_here = {path for (name, path) in KNOWN if name == place.name}
        unexpected = sorted(set(problems) - known_here)
        fixed = sorted(known_here - set(problems))
        check(not unexpected, f"{place.name}: gui {report['gui']['ok']}/{report['gui']['checked']}, "
                              f"parts {report['parts']['ok']}/{report['parts']['checked']}"
                              f"{f', {len(known_here & set(problems))} known' if known_here else ''}")
        for path in unexpected[:10]:
            row = problems[path]
            print(f"       {row['status']} {path} {row.get('delta', '')} studio={row.get('studio')} rhr={row.get('rhr')}")
        for path in sorted(known_here & set(problems)):
            print(f"       known: {path}: {KNOWN[(place.name, path)]}")
        check(not fixed, f"{place.name}: no known difference has started matching Studio {fixed or ''}")

    print(f"studio truth: {len(failures)} failed" if failures else "studio truth: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
