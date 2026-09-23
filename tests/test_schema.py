#!/usr/bin/env python3
"""Every JSON document RHR emits names its schema ("rhr.<kind>/<version>").

Agents parse these outputs; a versioned name lets them check the shape they read
and lets a changed shape announce itself (rhr.schema).

    python tests/test_schema.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
UI = ROOT / "tests" / "fixtures" / "duplicate_names.rbxmx"
SCENE = ROOT / "tests" / "fixtures" / "scene_model_scale.rbxmx"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run_json(args: list[str]) -> dict:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert proc.returncode in (0, 1), proc.stderr  # rhr check exits 1 on error findings
    return json.loads(proc.stdout)


def main() -> int:
    from rhr.schema import name

    with tempfile.TemporaryDirectory(prefix="rhr-schema-") as directory:
        ir_path = Path(directory) / "ir.json"
        png = Path(directory) / "blank.png"
        from PIL import Image
        Image.new("RGBA", (8, 8), (40, 80, 120, 255)).save(png)
        subprocess.run([*RHR, "ir", str(UI), "--out", str(ir_path)], cwd=ROOT, capture_output=True, check=True)
        documents = {
            "ir": json.loads(ir_path.read_text(encoding="utf-8")),
            "layout": run_json(["layout", str(UI), "--viewport", "400x300"]),
            "layout-rich": run_json(["layout", str(UI), "--rich", "--viewport", "400x300"]),
            "check": run_json(["check", str(UI)]),
            "hitmap": run_json(["hitmap", str(UI)]),
            "scene-dump": run_json(["scene-dump", str(SCENE)]),
            "compare": run_json(["compare", str(png), str(png), "--json"]),
            "browser": run_json(["browser", "status"]),
        }
    for kind, document in documents.items():
        check(document.get("schema") == name(kind), f"{kind}: schema {document.get('schema')!r}")
    check("rects" in documents["layout"] and "viewport" in documents["layout"], "layout wraps its rects")

    print(f"schema: {len(failures)} failed" if failures else "schema: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
