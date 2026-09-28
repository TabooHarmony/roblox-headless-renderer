"""Our IR -> the raw node shape that pinevex's flatten_node() consumes.

Why go through the raw shape at all, instead of emitting pinevex's flat schema
directly: flatten_node() is the code that produced pinevex's own reference
renders. Reusing it means our pipeline differs from upstream only where our IR
is more complete, and every remaining difference is attributable and testable.

Contract expected by flatten_node() (read out of vendor/.../rbxm_adapter.py):
    {"className", "name", "properties": {...}, "children": [...]}
with property dicts shaped as
    Color3 {"r","g","b"} floats | UDim2 {"x":{"scale","offset"},"y":{...}}
    Vector2 {"x","y"} | UDim {"scale","offset"} | Rect {"min","max"}
    FontFace {"family","weight","style"} strings | enums as "Enum.Type.Item"
"""

from __future__ import annotations

import re

_RBXASSETID_RE = re.compile(r"rbxassetid://(\d+)")

# UICorner keeps its radius as four per-corner UDims in current place files. The
# unified `CornerRadius` property they replaced cannot be read through the Lua
# bridge (no default value in its reflection snapshot), so the IR carries the four
# and `_collapse_corner_radius()` below merges them for flatten_node, which reads
# `CornerRadius` and else substitutes a hardcoded 8px radius.


_PER_CORNER = ("TopLeftRadius", "TopRightRadius", "BottomLeftRadius", "BottomRightRadius")


def _collapse_corner_radius(props: dict):
    """One radius for the engine, from UICorner's four per-corner UDims.

    The engine clips with a single rounded rect, so unequal corners collapse to the
    top-left value (the only case where this loses information).
    """
    present = [props[name] for name in _PER_CORNER if name in props]
    if not present:
        return None
    if any(v != present[0] for v in present):
        return props.get("TopLeftRadius", present[0])
    return present[0]


def _scale_offset(src: dict, scale_key: str, offset_key: str) -> dict:
    return {"scale": float(src.get(scale_key, 0) or 0), "offset": int(src.get(offset_key, 0) or 0)}


def _convert(prop: str, v):
    """Convert one IR value to the raw-node value flatten_node() expects."""
    if not isinstance(v, dict) or "_t" not in v:
        # Plain scalars (str/bool/float/int) and anything untyped pass through.
        return v

    t = v["_t"]
    if t == "Vector2":
        return {"x": float(v["X"]), "y": float(v["Y"])}
    if t == "Vector3":
        return {"x": float(v["X"]), "y": float(v["Y"]), "z": float(v["Z"])}
    if t == "UDim2":
        return {
            "x": _scale_offset(v, "XS", "XO"),
            "y": _scale_offset(v, "YS", "YO"),
        }
    if t == "UDim":
        return _scale_offset(v, "Scale", "Offset")
    if t == "Color3":
        return {"r": float(v["R"]), "g": float(v["G"]), "b": float(v["B"])}
    if t == "EnumItem":
        enum_type = str(v["enum"]).removeprefix("Enum.")
        return f"Enum.{enum_type}.{v['name']}"
    if t == "Font":
        family = str(v["family"])
        if _RBXASSETID_RE.search(family):
            from rhr.ui_engine.font_assets import resolve_font_family

            family = resolve_font_family(family)
        return {"family": family, "weight": str(v["weight"]), "style": str(v["style"])}
    if t == "Rect":
        lo, hi = v["Min"], v["Max"]
        return {
            "min": {"x": float(lo["X"]), "y": float(lo["Y"])},
            "max": {"x": float(hi["X"]), "y": float(hi["Y"])},
        }
    if t == "ColorSequence":
        return [
            {
                "time": float(kp["Time"]),
                "color": _convert(prop, kp["Value"]),
            }
            for kp in v["keypoints"]
        ]
    if t == "NumberSequence":
        return [
            {
                "time": float(kp["Time"]),
                "value": float(kp["Value"]),
                "envelope": float(kp.get("Envelope") or 0),
            }
            for kp in v["keypoints"]
        ]
    if t == "NumberRange":
        return {"min": float(v["Min"]), "max": float(v["Max"])}
    return v


def ir_node_to_raw(node: dict) -> dict:
    """Convert one IR node (and its subtree) to the raw node shape.

    `_path` is the IR's unique node path (rhr.ir.ensure_paths), so same-named
    siblings keep separate rects in the layout dump and hit map.
    """
    name = node.get("name") or node.get("className", "Frame")
    here = node["path"]

    props = {}
    for prop, value in (node.get("props") or {}).items():
        if prop == "Name":
            continue
        converted = _convert(prop, value)
        if converted is not None:
            props[prop] = converted

    if node.get("className") == "UICorner" and "CornerRadius" not in props:
        collapsed = _collapse_corner_radius(props)
        if collapsed is not None:
            props["CornerRadius"] = collapsed

    return {
        "className": node.get("className", "Frame"),
        "name": name,
        "_path": here,
        "properties": props,
        "children": [ir_node_to_raw(child) for child in node.get("children") or []],
    }


# The only nodes the 2D pipeline draws, lays out or checks (with their whole subtrees:
# a ViewportFrame's parts, UI modifiers): every GuiBase2d class.
from rhr.rbx.props import GUI_CLASSES  # noqa: E402


def _ui_branches(ir: dict) -> frozenset[int]:
    """id() of every node that is GUI or has GUI below it."""
    found: set[int] = set()

    def walk(node: dict) -> bool:
        has = node.get("className") in GUI_CLASSES
        for child in node.get("children") or []:
            has = walk(child) or has
        if has:
            found.add(id(node))
        return has

    for root in ir["roots"]:
        walk(root)
    return frozenset(found)


def ui_branches(ir: dict) -> frozenset[int]:
    from rhr.ir import derived

    return derived(ir, "ui_branches", _ui_branches)


def ui_nodes(ir: dict):
    """Every node the 2D pipeline can see: GUI nodes with their whole subtrees and the
    nodes above them. Skips the rest of a place (its 3D world)."""
    branches = ui_branches(ir)

    def walk(node: dict, inside: bool):
        yield node
        inside = inside or node.get("className") in GUI_CLASSES
        for child in node.get("children") or []:
            if inside or id(child) in branches:
                yield from walk(child, inside)

    for root in ir["roots"]:
        yield from walk(root, False)


def ui_index(ir: dict) -> dict[str, dict]:
    """path -> IR node, for ui_nodes()."""
    from rhr.ir import derived

    return derived(ir, "ui_index", lambda document: {node["path"]: node for node in ui_nodes(document)})


def _ui_skeleton(node: dict, branches: frozenset[int]) -> dict:
    """`ir_node_to_raw` of the UI in `node`'s subtree: GUI nodes whole, the nodes above
    them with only the children that lead to UI, nothing else. A place's 3D world
    (100k parts) is never converted for a UI command."""
    if node.get("className") in GUI_CLASSES:
        return ir_node_to_raw(node)
    raw = ir_node_to_raw({**node, "children": []})
    raw["children"] = [_ui_skeleton(child, branches) for child in node.get("children") or []
                       if id(child) in branches]
    return raw


def _screen_gui_branches(ir: dict) -> frozenset[int]:
    """id() of every node that is a ScreenGui or has one below it (not inside one)."""
    from rhr.ir import derived

    def compute(document: dict) -> frozenset[int]:
        found: set[int] = set()

        def walk(node: dict) -> bool:
            if node.get("className") == "ScreenGui":
                found.add(id(node))
                return True
            has = False
            for child in node.get("children") or []:
                has = walk(child) or has
            if has:
                found.add(id(node))
            return has

        for root in document["roots"]:
            walk(root)
        return frozenset(found)

    return derived(ir, "screen_gui_branches", compute)


def _screen_gui_skeleton(node: dict, branches: frozenset[int]) -> dict:
    """What a service a place does not draw holds for the note naming its ScreenGuis:
    the path to each ScreenGui, the ScreenGui with its own properties (Enabled), and
    stubs for its children (whether it has any)."""
    raw = ir_node_to_raw({**node, "children": []})
    if node.get("className") == "ScreenGui":
        raw["children"] = [{"className": child.get("className", "Frame"), "name": child.get("name"),
                            "_path": child["path"], "properties": {}, "children": []}
                           for child in node.get("children") or []]
        return raw
    raw["children"] = [_screen_gui_skeleton(child, branches) for child in node.get("children") or []
                       if id(child) in branches]
    return raw


def ir_to_raw_nodes(ir: dict) -> list[dict]:
    """The UI of the file (see _ui_skeleton), roots in paint order: highest
    `ScreenGui.DisplayOrder` first.

    Roblox draws a higher DisplayOrder on top, and pinevex has no DisplayOrder
    handling at all, so a multi-ScreenGui file would stack in whatever order the file
    happens to list them. pinevex draws one root, so "first" is the pane you end up
    seeing: the top one. Ties keep file order (fixture: display_order).
    """
    from rhr.ir import ensure_ir_paths

    from rhr import pipeline

    ensure_ir_paths(ir)
    branches = ui_branches(ir)
    # A place draws StarterGui's UI (and what is outside its services); of the other
    # services it only names the ScreenGuis (rhr.pipeline.shown_ui_roots), unless
    # --all-guis. Their UI (a game's templates: 18k nodes on a real one) is not converted.
    place = not pipeline.INCLUDE_STORED_GUIS and any(
        root.get("className") in pipeline.PLACE_SERVICES for root in ir["roots"])
    nodes = [_screen_gui_skeleton(root, _screen_gui_branches(ir))
             if place and root.get("className") in pipeline.PLACE_SERVICES and root.get("className") != "StarterGui"
             else _ui_skeleton(root, branches)
             for root in ir["roots"]]  # roots are always kept
    nodes.sort(key=_display_order, reverse=True)
    return nodes


def _display_order(node: dict) -> float:
    """ScreenGui.DisplayOrder, from a raw node's properties (0 when absent)."""
    props = node.get("properties") or node.get("props") or {}
    value = props.get("DisplayOrder")
    return float(value) if isinstance(value, (int, float)) else 0.0