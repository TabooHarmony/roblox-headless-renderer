#!/usr/bin/env python3
"""ParticleEmitter IR coverage: typed properties must survive the bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

FIXTURE = REPO / "tests" / "fixtures" / "particle_scene.rbxmx"


def find(node: dict, class_name: str) -> dict | None:
    if node.get("className") == class_name:
        return node
    for child in node.get("children") or []:
        found = find(child, class_name)
        if found is not None:
            return found
    return None


def main() -> int:
    from test_fixtures import emit_ir

    ir = json.loads(emit_ir(FIXTURE).read_text())
    emitter = find(ir["roots"][0], "ParticleEmitter")
    if emitter is None:
        print("particle data: FAIL: emitter missing")
        return 1
    props = emitter["props"]
    required = {
        "Acceleration", "Brightness", "Color", "Drag", "EmissionDirection", "Enabled",
        "Lifetime", "LightEmission", "LightInfluence", "LockedToPart", "Orientation", "Rate",
        "Rotation", "RotSpeed", "Shape", "Size", "Speed", "SpreadAngle", "Squash", "Texture",
        "TimeScale", "Transparency", "VelocityInheritance", "WindAffectsDrag", "ZOffset",
    }
    checks = [
        (required <= props.keys(), "the emitter property surface is present"),
        (not emitter.get("unreadable") and not emitter.get("unmapped"),
         "no emitter property is unreadable or unmapped"),
        (props["Lifetime"] == {"Min": 1, "Max": 2, "_t": "NumberRange"},
         "Lifetime is a typed NumberRange"),
        (props["Speed"] == {"Min": 4, "Max": 8, "_t": "NumberRange"},
         "Speed is a typed NumberRange"),
        (props["SpreadAngle"] == {"X": 15, "Y": 25, "_t": "Vector2"},
         "SpreadAngle is a typed Vector2"),
        (props["Acceleration"] == {"X": 0, "Y": -4, "Z": 0, "_t": "Vector3"},
         "Acceleration is a typed Vector3"),
        (props["Texture"] == "rbxassetid://1266170131", "Texture keeps its asset URI"),
        (len(props["Color"]["keypoints"]) == 2 and len(props["Size"]["keypoints"]) == 2,
         "Color and Size keep their sequence keypoints"),
        (props["Enabled"] is True and props["Rate"] == 12, "runtime enable and rate survive"),
    ]
    for ok, message in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    failed = sum(not ok for ok, _ in checks)
    print("particle data: ok" if not failed else f"particle data: {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
