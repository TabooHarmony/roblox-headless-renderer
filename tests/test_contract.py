#!/usr/bin/env python3
"""The public interface keeps its shape (docs/interface-1.0.md).

Rebuilds, from real runs on fixtures, every public command with its flags, every JSON
output's structure (each field's place and type) and the exit codes, and compares them
with tests/contract/interface.json:

- a command, flag, choice or default that is gone or changed fails;
- a JSON field that is gone, or has a new type, fails; a new field is allowed (the
  schema rule: adding a field does not change the version) and is printed;
- a schema version must match the snapshot.

After an intentional change (a new schema version, a new command), refresh the
snapshot and review its diff:

    python tests/test_contract.py --update
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Offline and without Studio even when run by hand (`--update`): otherwise assets
# download, the missing-asset lists come out empty, and their fields leave the snapshot.
import _harness  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
SNAPSHOT = ROOT / "tests" / "contract" / "interface.json"
FIX = ROOT / "tests" / "fixtures"

# Objects keyed by names that depend on the file (instance paths, class names,
# material names): their keys are "*" in the snapshot.
DYNAMIC = {
    "layout": {"rects"},
    "scene-dump": {"classCounts", "fallbacks", "materialFallbacks", "unsupportedVisualClasses", "experimental"},
    "scene-summary": {"classCounts", "fallbacks", "materialFallbacks", "unsupportedVisualClasses", "experimental"},
    "render": {"fallbacks", "materialFallbacks", "unsupportedVisualClasses", "experimental"},
}


def json_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def shape(value, kind: str, path: str, out: dict[str, set[str]]) -> None:
    out.setdefault(path or ".", set()).add(json_type(value))
    if isinstance(value, dict):
        dynamic = path in DYNAMIC.get(kind, set())
        for key, item in value.items():
            shape(item, kind, f"{path}.{'*' if dynamic else key}".lstrip("."), out)
    elif isinstance(value, list):
        for item in value:
            shape(item, kind, f"{path}[]", out)


def contract_scene() -> dict:
    """An IR scene that fills every list in scene-dump and the render report: a decal
    and a special mesh whose assets are missing, a local light, terrain, and Lighting
    with an Atmosphere and a Sky."""
    identity = {"R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}

    def part(name: str, x: float, children: list[dict]) -> dict:
        return {"className": "Part", "name": name, "children": children, "props": {
            "CFrame": {"_t": "CFrame", "X": x, "Y": 2, "Z": 0, **identity},
            "Size": {"_t": "Vector3", "X": 4, "Y": 4, "Z": 4},
            "Color": {"_t": "Color3", "R": 0.6, "G": 0.6, "B": 0.6}, "Anchored": True}}

    def child(class_name: str, props: dict) -> dict:
        return {"className": class_name, "name": class_name, "props": props, "children": []}

    face = {"_t": "EnumItem", "enum": "Enum.NormalId", "name": "Front"}
    world = [
        part("Decorated", -5, [child("Decal", {"Texture": "rbxassetid://999999991", "Face": face}),
                               child("PointLight", {"Range": 12, "Brightness": 2})]),
        part("Meshed", 5, [child("SpecialMesh", {"MeshType": {"_t": "EnumItem", "name": "FileMesh"},
                                                 "MeshId": "rbxassetid://999999992"})]),
        {**part("OddMaterial", 0, []), "props": {**part("OddMaterial", 0, [])["props"],
                                                  "Material": {"_t": "EnumItem", "name": "NotAMaterial"}}},
        {"className": "Terrain", "name": "Terrain", "props": {}, "children": []},
    ]
    sky_faces = {name: "rbxassetid://999999993" for name in
                 ("SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp")}
    lighting = {"className": "Lighting", "name": "Lighting", "props": {"ClockTime": 14}, "children": [
        child("Atmosphere", {"Density": 0.3}), child("Sky", sky_faces)]}
    return {"sourcePath": "contract", "roots": [
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": world}, lighting]}


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], capture_output=True, text=True, cwd=ROOT, timeout=300)


def json_outputs(tmp: Path) -> tuple[dict[str, dict], dict[str, int]]:
    """{schema kind: {"version": n, "fields": {path: [types]}}}, and the exit codes seen."""
    shapes: dict[str, dict[str, set[str]]] = {}
    versions: dict[str, str] = {}
    exits: dict[str, int] = {}

    def record(label: str, proc: subprocess.CompletedProcess, expect: int = 0) -> None:
        exits[label] = proc.returncode
        assert proc.returncode == expect, f"{label}: exit {proc.returncode}\n{proc.stderr[-800:]}"
        document = json.loads(proc.stdout)
        name, version = document["schema"].removeprefix("rhr.").split("/")
        versions.setdefault(name, version)
        assert versions[name] == version, (label, versions[name], version)
        shape(document, name, "", shapes.setdefault(name, {}))

    shop = ROOT / "examples" / "shop.rbxmx"
    record("layout", run("layout", str(shop)))
    record("layout --rich", run("layout", str(shop), "--rich"))
    record("check (warnings only)", run("check", str(shop)))
    record("check (error finding)", run("check", str(FIX / "zero_grid_cell.rbxmx")), expect=1)
    record("hitmap", run("hitmap", str(FIX / "hitmap_overlap.rbxmx")))
    record("hitmap --at", run("hitmap", str(FIX / "hitmap_overlap.rbxmx"), "--at", "100,60"))
    for name in ("scene_lighting", "beam_transparency", "trail_motion", "particle_scene",
                 "scene_material_textures", "preview_world_ui", "scene_two_cameras"):
        record(f"scene-dump {name}", run("scene-dump", "--parts", str(FIX / f"{name}.rbxmx")))
    record("scene-dump (placeholder meshes)", run("scene-dump", "--parts", str(FIX / "scene_variants_placeholders.rbxlx")))
    ui_png, other_png = tmp / "ui.png", tmp / "other.png"
    record("ui --json", run("ui", str(shop), "--viewport", "400x300", "--out", str(ui_png), "--json"))
    record("ui --json (second)", run("ui", str(FIX / "panel_styles.rbxmx"), "--viewport", "400x300",
                                     "--out", str(other_png), "--json"))
    record("scene --json", run("scene", str(FIX / "particle_scene.rbxmx"), "--viewport", "320x200",
                               "--out", str(tmp / "scene.png"), "--json"))
    record("preview --json", run("preview", str(FIX / "preview_world_ui.rbxmx"), "--viewport", "320x200",
                                 "--out", str(tmp / "preview.png"), "--json"))
    scene_ir = tmp / "contract.json"
    scene_ir.write_text(json.dumps(contract_scene()), encoding="utf-8")
    record("scene-dump (contract scene)", run("scene-dump", "--parts", str(scene_ir)))
    record("scene-dump summary (contract scene)", run("scene-dump", str(scene_ir)))
    record("scene-dump summary (placeholder meshes)", run("scene-dump", str(FIX / "scene_variants_placeholders.rbxlx")))
    record("scene --json (contract scene)", run("scene", str(scene_ir), "--viewport", "320x200",
                                                "--out", str(tmp / "contract.png"), "--json"))
    record("scene --json (placeholder meshes)", run("scene", str(FIX / "scene_variants_placeholders.rbxlx"),
                                                    "--viewport", "320x200", "--out", str(tmp / "placeholders.png"),
                                                    "--json"))
    record("compare", run("compare", str(ui_png), str(other_png)))
    # Stopped first, so the status has the same shape whether or not a worker ran.
    record("browser stop", run("browser", "stop"))
    record("browser status", run("browser", "status"))

    # Failures: a missing file and a bad flag both exit 2.
    exits["missing file"] = run("layout", str(tmp / "nope.rbxmx")).returncode
    exits["bad flag"] = run("scene", str(shop), "--view", "sideways").returncode
    documents = {
        name: {"version": int(versions[name]), "fields": {path: sorted(types) for path, types in sorted(fields.items())}}
        for name, fields in sorted(shapes.items())
    }
    return documents, exits


def cli_surface() -> dict:
    """Every public command: its positional arguments and its visible flags."""
    from rhr.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    commands = {}
    for name, command in sorted(sub.choices.items()):
        positionals, flags = [], {}
        for action in command._actions:
            if isinstance(action, argparse._HelpAction) or action.help == argparse.SUPPRESS:
                continue
            if not action.option_strings:
                positionals.append({"name": action.dest, "choices": list(action.choices or [])})
                continue
            default = action.default
            flags[action.option_strings[0]] = {
                "takesValue": action.nargs != 0,
                "choices": list(action.choices or []),
                "default": list(default) if isinstance(default, tuple) else default,
            }
        commands[name] = {"positionals": positionals, "flags": dict(sorted(flags.items()))}
    return commands


def build() -> dict:
    with tempfile.TemporaryDirectory(prefix="rhr-contract-") as directory:
        documents, exits = json_outputs(Path(directory))
    return {"commands": cli_surface(), "json": documents, "exitCodes": exits}


def compare_with(snapshot: dict, current: dict) -> tuple[list[str], list[str]]:
    failures, additions = [], []
    old_commands, new_commands = snapshot["commands"], current["commands"]
    for name, spec in old_commands.items():
        if name not in new_commands:
            failures.append(f"command removed: {name}")
            continue
        if spec["positionals"] != new_commands[name]["positionals"]:
            failures.append(f"{name}: positional arguments changed")
        for flag, flag_spec in spec["flags"].items():
            now = new_commands[name]["flags"].get(flag)
            if now is None:
                failures.append(f"{name} {flag}: flag removed")
            elif now != flag_spec:
                failures.append(f"{name} {flag}: changed from {flag_spec} to {now}")
        additions += [f"{name} {flag}: new flag" for flag in new_commands[name]["flags"]
                      if flag not in spec["flags"]]
    additions += [f"new command: {name}" for name in new_commands if name not in old_commands]

    for kind, spec in snapshot["json"].items():
        now = current["json"].get(kind)
        if now is None:
            failures.append(f"rhr.{kind}: no longer produced")
            continue
        if now["version"] != spec["version"]:
            failures.append(f"rhr.{kind}: version {spec['version']} -> {now['version']} (update the snapshot on purpose)")
        for path, types in spec["fields"].items():
            if path not in now["fields"]:
                failures.append(f"rhr.{kind}: field {path} is gone")
            elif not set(now["fields"][path]) <= set(types):
                failures.append(f"rhr.{kind}: field {path} was {types}, now {now['fields'][path]}")
        additions += [f"rhr.{kind}: new field {path}" for path in now["fields"] if path not in spec["fields"]]
    additions += [f"new schema: rhr.{kind}" for kind in current["json"] if kind not in snapshot["json"]]

    for label, code in snapshot["exitCodes"].items():
        if current["exitCodes"].get(label) != code:
            failures.append(f"exit code for {label}: {code} -> {current['exitCodes'].get(label)}")
    return failures, additions


def main(argv: list[str] | None = None) -> int:
    update = "--update" in (argv if argv is not None else sys.argv[1:])
    current = build()
    if update or not SNAPSHOT.is_file():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"contract: snapshot written to {SNAPSHOT.relative_to(ROOT)}")
        return 0
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    failures, additions = compare_with(snapshot, current)
    for line in additions:
        print(f"  new  {line} (allowed; refresh the snapshot to keep it)")
    for line in failures:
        print(f"  FAIL {line}")
    assert not failures, failures
    print(f"contract: {len(current['commands'])} commands, {len(current['json'])} JSON schemas, "
          f"{len(current['exitCodes'])} exit codes unchanged")
    return 0


def test_main():
    from _harness import run_main

    run_main(lambda: main([]))


if __name__ == "__main__":
    raise SystemExit(main())
