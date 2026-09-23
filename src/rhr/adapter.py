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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Vendored helpers we reuse rather than re-derive: asset URL normalization and the
# built-in font asset table. Imported lazily so the module stays importable in
# environments without requests installed.
_WEB_DEMO = REPO / "vendor" / "pinevex" / "web_demo"


def _vendored_adapter():
    if str(_WEB_DEMO) not in sys.path:
        sys.path.insert(0, str(_WEB_DEMO))
    from rbxm_parser_component import rbxm_adapter

    return rbxm_adapter


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
            family = _vendored_adapter()._resolve_font_family(family)
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


def ir_node_to_raw(node: dict, path: str = "") -> dict:
    """Convert one IR node (and its subtree) to the raw node shape."""
    name = node.get("name") or node.get("className", "Frame")
    here = f"{path}/{name}" if path else name

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
        "children": [ir_node_to_raw(child, here) for child in node.get("children") or []],
    }


def ir_to_raw_nodes(ir: dict) -> list[dict]:
    """Roots in paint order: highest `ScreenGui.DisplayOrder` first.

    Roblox draws a higher DisplayOrder on top, and pinevex has no DisplayOrder
    handling at all, so a multi-ScreenGui file would stack in whatever order the file
    happens to list them. pinevex draws one root, so "first" is the pane you end up
    seeing: the top one. Ties keep file order (fixture: display_order).
    """
    nodes = [ir_node_to_raw(root) for root in ir["roots"]]
    nodes.sort(key=_display_order, reverse=True)
    return nodes


def _display_order(node: dict) -> float:
    """ScreenGui.DisplayOrder, from a raw node's properties (0 when absent)."""
    props = node.get("properties") or node.get("props") or {}
    value = props.get("DisplayOrder")
    return float(value) if isinstance(value, (int, float)) else 0.0