#!/usr/bin/env python3
"""What a 3D view of a place draws and frames (found on real places of 20k-116k parts).

- Models a place stores out of the world (a game's maps in ServerStorage) are not
  drawn, downloaded or counted; a note names them; `--focus` on one draws it.
- A part parked far from the rest (a plugin's rig 100k studs out) does not drag a
  standard view's camera out with it; a note names it.

    python tests/test_large_place.py
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RHR = [sys.executable, "-m", "rhr"]
failures: list[str] = []

IDENTITY = {"R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def part(name: str, x: float, y: float, z: float, size: float = 4) -> dict:
    return {"className": "Part", "name": name, "children": [], "props": {
        "CFrame": {"_t": "CFrame", "X": x, "Y": y, "Z": z, **IDENTITY},
        "Size": {"_t": "Vector3", "X": size, "Y": size, "Z": size},
        "Color": {"_t": "Color3", "R": 0.8, "G": 0.3, "B": 0.2}, "Anchored": True}}


def model(name: str, children: list[dict]) -> dict:
    return {"className": "Model", "name": name, "props": {}, "children": children}


def place() -> dict:
    """A lobby of 80 parts near the origin, a rig parked 100k studs out in the
    camera (as animation plugins leave them), and three maps in ServerStorage."""
    lobby = [part(f"Block{i}", (i % 10) * 8, 2, (i // 10) * 8) for i in range(80)]
    rig = model("DummyR15", [part(f"Limb{i}", 100_000, 50 + i, 100_000, 1) for i in range(3)])
    camera = {"className": "Camera", "name": "Camera", "props": {}, "children": [rig]}
    maps = model("Maps", [model(name, [part(f"{name}{i}", 0, 2 + i * 4, 0, 6) for i in range(8)])
                          for name in ("Farm", "Hotel", "Bank")])
    return {"sourcePath": "large-place-test", "roots": [
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": [*lobby, camera]},
        {"className": "Lighting", "name": "Lighting", "props": {"ClockTime": 14}, "children": []},
        {"className": "ServerStorage", "name": "ServerStorage", "props": {}, "children": [maps]},
    ]}


def rules() -> None:
    from rhr.ir import ensure_paths, stored_note, world_roots

    ir = place()
    ensure_paths(ir["roots"])
    shown, stored = world_roots(ir["roots"])
    check([r["className"] for r in shown] == ["Workspace", "Lighting"], "a place draws its world, not ServerStorage")
    note = stored_note(stored) or ""
    check("24 part(s) stored outside the world" in note and "ServerStorage 24" in note,
          f"the note counts what was left out ({note[:70]}...)")
    check("--focus <path> draws one, e.g. ServerStorage/Maps/" in note,
          "the note suggests one stored map to focus on, not the folder of maps")
    shown, _ = world_roots(ir["roots"], "ServerStorage/Maps/Hotel")
    check(shown[-1].get("path") == "ServerStorage/Maps/Hotel", "--focus on a stored map draws that map")
    model_file = [model("Kit", [part("A", 0, 0, 0)])]
    check(world_roots(model_file)[0] == model_file, "a model file draws everything")


def render(tmp: Path) -> None:
    ir_path = tmp / "place.json"
    ir_path.write_text(json.dumps(place()), encoding="utf-8")
    proc = subprocess.run([*RHR, "scene", str(ir_path), "--view", "iso", "--viewport", "400x300",
                           "--out", str(tmp / "place.png"), "--json"],
                          capture_output=True, text=True, cwd=ROOT, timeout=300)
    check(proc.returncode == 0, f"the place renders ({proc.stderr.strip()[-200:]})")
    if proc.returncode:
        return
    report = json.loads(proc.stdout)
    notes = " | ".join(report["notes"])
    distance = math.dist(report["camera"]["position"], (36, 2, 28))
    check(distance < 500, f"the camera frames the lobby, not the far rig ({distance:.0f} studs away)")
    check("framing left out 3 part(s) far from the rest" in notes and "Workspace/Camera/DummyR15" in notes,
          "a note names the rig framing left out")
    check("stored outside the world not drawn" in notes, "a note names the stored maps")
    dump = subprocess.run([*RHR, "scene-dump", str(ir_path)], capture_output=True, text=True, cwd=ROOT, timeout=300)
    paths = [p["path"] for p in json.loads(dump.stdout)["parts"]]
    check(any(p.startswith("ServerStorage/") for p in paths), "scene-dump still describes the whole file")


def main() -> int:
    rules()
    with tempfile.TemporaryDirectory(prefix="rhr-large-place-") as directory:
        render(Path(directory))
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("large place: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
