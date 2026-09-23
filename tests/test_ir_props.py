#!/usr/bin/env python3
"""IR checks: nothing may vanish without being named.

Two ways a property disappears between the file and the renderer, both of which
used to happen in silence: the bridge refuses to read it, or we have no mapping for
its datatype. The emitter now lists both per node, and this check keeps them listed
(and keeps the one trap that produced wrong values rather than missing ones closed:
a property name that is also a child's name).

Run: .venv/bin/python tests/test_ir_props.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

FIXTURES = REPO / "tests" / "fixtures"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def find(node: dict, name: str):
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        hit = find(child, name)
        if hit:
            return hit
    return None


def main() -> int:
    from test_fixtures import emit_ir

    print("ir props: name collisions and named drops")
    ir = json.loads(emit_ir(FIXTURES / "child_name_collision.rbxmx").read_text())
    card = find(ir["roots"][0], "Card")
    label = find(ir["roots"][0], "Text")

    check(card is not None, "fixture parses (Card found)")
    if card is None:
        return 1

    # The bridge answers `frame.Text` / `frame.Padding` with the *child* of that
    # name, not a property. Those must not reach the IR as property values.
    check("Text" not in card["props"], "parent does not inherit the child named 'Text'")
    check("Padding" not in card["props"], "parent does not take the child named 'Padding'")
    check(
        all(v != "Instance" for v in card["props"].values()),
        "no property value is the string 'Instance'",
    )
    check(card.get("unmapped") is None, "no datatype went unmapped on this fixture")
    reported = " ".join(card.get("not_a_property", []))
    check("Text (child TextLabel)" in reported, "the collision is named on the node")
    check("Padding (child Frame)" in reported, "the second collision is named too")

    # The child itself keeps its own real property.
    check(label is not None and label["props"].get("Text") == "hello",
          "the TextLabel keeps its own Text")

    # Nothing in the fixtures should be silently unreadable.
    def collect(node: dict, key: str) -> list[str]:
        out = node.get(key, [])
        for child in node.get("children", []):
            out += collect(child, key)
        return out

    # A class the reflection database does not have cannot be read through the
    # bridge at all, so its typed properties are named `unreadable` rather than
    # recovered (docs/known-approximations.md). That is the one fixture where an
    # unreadable entry is the expected, correct result.
    named_drops_ok = {"unknown_class.rbxmx", "unknown_class_values.rbxmx"}

    unknown = json.loads(emit_ir(FIXTURES / "unknown_class.rbxmx").read_text())
    mystery = find(unknown["roots"][0], "Mystery")
    check(mystery is not None and mystery["className"] == "ZzzNotAClass",
          "unknown-class fixture parses")
    if mystery is not None:
        # A class the bridge has no metadata for yields the file's *text* for the
        # properties the XML pass understands (a string, not a typed value), and
        # names the rest. It is a poor IR, but it is a named one.
        check(mystery["props"].get("Name") == "Mystery",
              f"a class the database lacks still recovers its string properties "
              f"({mystery['props'].get('Name')!r})")
        named = " ".join(mystery.get("unreadable", []))
        check("Size" in named and "BackgroundColor3" in named,
              f"its typed properties are named, not silently dropped ({mystery.get('unreadable')})")

    # A recovered value keeps the datatype its tag names. Two cold-audit findings, both
    # reproduced before they were fixed: the escaped text of a value reached the IR as
    # `&amp;`, and `Visible` came back as the string "false", which is truthy everywhere
    # downstream (flatten_node hides a node only on a real boolean false), so a hidden
    # object rendered visible with no signal anywhere.
    values = json.loads(emit_ir(FIXTURES / "unknown_class_values.rbxmx").read_text())
    hidden = find(values["roots"][0], "HiddenThing")
    check(hidden is not None, "unknown-class values fixture parses")
    if hidden is not None:
        props = hidden["props"]
        check(props.get("Visible") is False,
              f"a recovered bool is a bool, not the string 'false' ({props.get('Visible')!r})")
        check(props.get("DisplayOrder") == 7 and isinstance(props.get("DisplayOrder"), int),
              f"a recovered int is a number ({props.get('DisplayOrder')!r})")
        check(props.get("Text") == "cheap & cheerful <tag> 5 > 3",
              f"escaped text is decoded ({props.get('Text')!r})")
        check("Size" in " ".join(hidden.get("unreadable", [])),
              f"a struct the bridge cannot read is still named, not guessed ({hidden.get('unreadable')})")

    # The XML recovery is per instance, not per class: the first ImageLabel has no
    # Image at all and the later ImageButton carries only HoverImage, so an answer
    # cached per class would lose the middle one.
    later = json.loads(emit_ir(FIXTURES / "image_on_later_instance.rbxmx").read_text())
    bare = find(later["roots"][0], "Bare")
    carries = find(later["roots"][0], "CarriesImage")
    hover = find(later["roots"][0], "HoverOnly")
    check(carries is not None and carries["props"].get("Image") == "rbxassetid://900000002",
          f"an Image set on a later instance is still recovered ({carries and carries['props'].get('Image')})")
    check(bare is not None and "Image" not in bare["props"],
          "an ImageLabel without an Image does not borrow one")
    check(hover is not None and hover["props"].get("HoverImage") == "rbxassetid://900000003",
          f"HoverImage is recovered under its own name ({hover and hover['props'].get('HoverImage')})")

    group_ir = json.loads(emit_ir(FIXTURES / "canvas_group_transparency.rbxmx").read_text())
    group = find(group_ir["roots"][0], "HiddenGroup")
    check(group is not None and group["props"].get("GroupTransparency") == 1,
          f"CanvasGroup GroupTransparency survives ({group and group['props'].get('GroupTransparency')!r})")

    scene = json.loads(emit_ir(FIXTURES / "scene_geometry.rbxmx").read_text())
    workspace = scene["roots"][0]
    model = find(workspace, "Props")
    block = find(workspace, "RedBlock")
    camera = find(workspace, "SceneCamera")
    check(workspace["className"] == "Workspace" and model["className"] == "Model",
          "geometry fixture preserves Workspace -> Model nesting")
    check(block is not None and block["props"].get("Size") == {"X": 4, "Y": 2, "Z": 6, "_t": "Vector3"},
          f"Part Size survives as Vector3 ({block and block['props'].get('Size')})")
    cf = block and block["props"].get("CFrame")
    check(cf is not None and (cf["X"], cf["Y"], cf["Z"]) == (2, 3, -4),
          f"Part CFrame position survives ({cf and (cf['X'], cf['Y'], cf['Z'])})")
    check(cf is not None and (cf["R02"], cf["R20"]) == (-1, 1),
          f"Part CFrame rotation matrix survives ({cf and (cf['R02'], cf['R20'])})")
    check(block is not None and block["props"].get("Color", {}).get("R") == 1
          and abs(block["props"].get("Transparency", 1) - 0.2) < 1e-6,
          f"Part Color and Transparency survive ({block and (block['props'].get('Color'), block['props'].get('Transparency'))})")
    check(block is not None and "Material" in block["props"] and "Shape" in block["props"],
          f"Part Material and Shape survive ({block and (block['props'].get('Material'), block['props'].get('Shape'))})")
    camera_cf = camera and camera["props"].get("CFrame")
    check(camera is not None and camera["props"].get("FieldOfView") == 70,
          f"Camera FieldOfView survives ({camera and camera['props'].get('FieldOfView')})")
    check(camera_cf is not None and (camera_cf["X"], camera_cf["Y"], camera_cf["Z"]) == (0, 5, 12),
          f"Camera CFrame survives ({camera_cf and (camera_cf['X'], camera_cf['Y'], camera_cf['Z'])})")

    for fixture in sorted(FIXTURES.glob("*.rbxmx")):
        if fixture.name in named_drops_ok:
            continue
        ir_data = json.loads(emit_ir(fixture).read_text())
        bad = []
        for root in ir_data["roots"]:
            bad += [f"unreadable {n}" for n in collect(root, "unreadable")]
            bad += [f"unmapped {n}" for n in collect(root, "unmapped")]
        check(not bad, f"{fixture.name}: nothing unreadable, nothing unmapped ({bad or 'clean'})")

    print("ir props: ok" if not failures else f"ir props: {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())