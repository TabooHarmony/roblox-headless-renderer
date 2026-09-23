#!/usr/bin/env python3
"""Machine-readable 3D scene dump contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests/fixtures/scene_geometry.rbxmx"


def main() -> None:
    proc = subprocess.run(
        [str(RHR), "scene-dump", str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert len(data["parts"]) == 1
    part = data["parts"][0]
    assert part["path"] == "Scene/Props/RedBlock"
    assert part["position"] == [2.0, 3.0, -4.0]
    assert part["size"] == [4.0, 2.0, 6.0]
    assert part["bounds"]["min"] == [-1.0, 2.0, -6.0], part["bounds"]
    assert part["bounds"]["max"] == [5.0, 4.0, -2.0], part["bounds"]
    assert data["bounds"]["center"] == [2.0, 3.0, -4.0]
    assert data["fallbacks"] == {}
    assert data["materialFallbacks"] == {}
    assert data["unsupportedVisualClasses"] == {}
    assert data["preferredCamera"] == "Scene/SceneCamera"
    assert "scene-dump 1 parts" in proc.stderr
    print("scene dump: ok")


if __name__ == "__main__":
    main()
