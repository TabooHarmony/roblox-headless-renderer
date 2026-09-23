"""Interactive GUI hit-region dump on RHR's layout pass.

Rects, clipping and paint order come from ``rhr.ui_layout`` (the same pass the
renderer draws at and ``rhr layout`` reports), so a hit region can never disagree
with the picture. The IR is the source for Roblox interaction properties.

Output shape::

    {
      "model": "fixture.json",
      "viewport": [400, 300],
      "nodes": [
        {
          "path": "Gui/Panel/Button",
          "class": "TextButton",
          "rect": {"x": 10, "y": 20, "w": 100, "h": 40},
          "visible": false,
          "active": true,
          "selectable": false,
          "activatedTargetCandidate": true,
          "capturesClicks": true
        }
      ],
      "hitTests": [
        {
          "point": {"x": 60, "y": 40},
          "stack": ["Gui/Panel/Button", "Gui/Panel/Behind"],
          "target": "Gui/Panel/Button",
          "targetVisible": false
        }
      ]
    }

``nodes`` is sorted by path. ``hitTests`` contains one deterministic probe at
the centre of each unique interactive region. ``stack`` is topmost first and
contains only interactive nodes whose effective clipped rectangles contain the
probe. ``target`` is the first node in that stack that captures pointer input;
therefore an invisible-but-Active node is reported when it wins the stack.
A node with no positive effective rect is still listed with ``rect: null`` but
cannot appear in a hit test.
"""

from __future__ import annotations

from rhr.schema import stamp

import json
import sys
from pathlib import Path


_GUI_CLASSES = {
    "Frame",
    "CanvasGroup",
    "ScrollingFrame",
    "TextLabel",
    "TextButton",
    "TextBox",
    "ImageLabel",
    "ImageButton",
    "ViewportFrame",
    "VideoFrame",
}
_BUTTON_CLASSES = {"TextButton", "ImageButton"}


def _bool_prop(props: dict, name: str, default: bool = False) -> bool:
    value = props.get(name, default)
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _path_index(raw: dict) -> dict[str, list[dict]]:
    """Index raw-node interaction properties, retaining same-name collisions."""
    out: dict[str, list[dict]] = {}

    def walk(node: dict, inherited_visible: bool = True) -> None:
        path = node.get("_path")
        props = node.get("properties") or {}
        visible = inherited_visible and not (
            props.get("Visible") is False
            or (isinstance(props.get("Visible"), str) and props["Visible"].lower() == "false")
        )
        if path:
            cls = node.get("className", "")
            text_editable = _bool_prop(props, "TextEditable", True) if cls == "TextBox" else None
            clear_on_focus = _bool_prop(props, "ClearTextOnFocus", True) if cls == "TextBox" else None
            active = _bool_prop(props, "Active")
            selectable = _bool_prop(props, "Selectable")
            interactive = active or selectable or cls in _BUTTON_CLASSES or cls == "TextBox"
            out.setdefault(path, []).append(
                {
                    "class": cls,
                    "visible": visible,
                    "active": active,
                    "selectable": selectable,
                    "interactive": interactive,
                    "textEditable": text_editable,
                    "clearTextOnFocus": clear_on_focus,
                }
            )
        for child in node.get("children") or []:
            walk(child, visible)

    walk(raw)
    return out


def _inside(rect, x: float, y: float) -> bool:
    return rect.x <= x < rect.x + rect.w and rect.y <= y < rect.y + rect.h


def _paint_entries(ir_pane: dict, root_rect) -> list[tuple[dict, object]]:
    """All GuiObjects of a pane bottom-to-top, as (engine-style node, clipped rect)."""
    from rhr.ui_layout import paint_entries

    rect = (root_rect.x, root_rect.y, root_rect.w, root_rect.h)
    return [
        ({"_path": node["path"], "type": node.get("className")}, box)
        for node, box in paint_entries(ir_pane, rect)
    ]


def _pane_raw_nodes(raw_nodes: list[dict]) -> list[dict]:
    """Mirror pipeline.load_screens' pane selection for metadata indexing."""
    from rhr.pipeline import _screen_nodes, _strip_screens, find_renderable

    screens = _screen_nodes(raw_nodes)
    if not screens:
        pane = find_renderable(_strip_screens(raw_nodes))
        return [pane] if pane is not None else []
    panes: list[dict] = []
    container = find_renderable(_strip_screens(raw_nodes))
    if container is not None:
        panes.append(container)
    panes.extend(screens)
    return panes


def _round(value) -> float:
    return round(float(value), 3)


def _rect_dict(rect) -> dict:
    return {"x": _round(rect.x), "y": _round(rect.y), "w": _round(rect.w), "h": _round(rect.h)}


def _raw_pane_metadata(raw_pane: dict) -> dict[str, list[dict]]:
    return _path_index(raw_pane)


def build_hitmap(ir_path, width: int, height: int, topbar_height: float | None = None) -> dict:
    """Build a deterministic hit-region dump from an IR JSON file."""
    from rhr.adapter import ir_to_raw_nodes
    from rhr.insets import REFERENCE_TOPBAR_HEIGHT, for_nodes
    from rhr.ir import load_ir
    from rhr.pipeline import load_screens

    ir = load_ir(ir_path)
    raw_nodes = ir_to_raw_nodes(ir)
    raw_panes = _pane_raw_nodes(raw_nodes)
    screens = load_screens(
        str(ir_path),
        width,
        height,
        REFERENCE_TOPBAR_HEIGHT if topbar_height is None else topbar_height,
    )
    if len(raw_panes) != len(screens):
        raise ValueError(
            f"hitmap pane mismatch: metadata found {len(raw_panes)}, renderer found {len(screens)}"
        )

    node_records: list[dict] = []
    probe_candidates: list[tuple[float, float, list[dict], int]] = []
    pane_records = []

    from rhr.pipeline import _index_paths

    ir_by_path = _index_paths(ir["roots"])
    for pane_index, ((obj, root_rect, inset, pane_name), raw_pane) in enumerate(zip(screens, raw_panes)):
        metadata = _raw_pane_metadata(raw_pane)
        ir_pane = ir_by_path.get(raw_pane.get("_path"))
        if ir_pane is None:
            raise ValueError(f"hitmap: pane {pane_name!r} has no IR node")
        entries = _paint_entries(ir_pane, root_rect)
        # The path index retains collisions, while the converted object is what
        # establishes the exact rendered class/path and effective clipped rect.
        occurrence: dict[str, int] = {}
        pane_nodes: list[dict] = []
        for draw_index, (engine_node, rect) in enumerate(entries):
            path = engine_node.get("_path")
            if not path or engine_node.get("type") not in _GUI_CLASSES:
                continue
            choices = metadata.get(path) or [{}]
            choice_index = occurrence.get(path, 0)
            meta = choices[min(choice_index, len(choices) - 1)]
            occurrence[path] = choice_index + 1
            if not meta.get("interactive"):
                continue
            record = {
                "path": path,
                "class": meta.get("class") or engine_node.get("type"),
                "rect": _rect_dict(rect) if rect.w > 0 and rect.h > 0 else None,
                "visible": bool(meta.get("visible", engine_node.get("visible") is not False)),
                "active": bool(meta.get("active", False)),
                "selectable": bool(meta.get("selectable", False)),
                "capturesClicks": bool(meta.get("active", False)),
                "activatedTargetCandidate": bool(
                    meta.get("class") in _BUTTON_CLASSES and meta.get("active", False)
                ),
                "zOrder": draw_index,
                "pane": pane_index,
            }
            if record["class"] == "TextBox":
                record["textEditable"] = bool(meta.get("textEditable", True))
                record["clearTextOnFocus"] = bool(meta.get("clearTextOnFocus", True))
            pane_nodes.append(record)
        node_records.extend(pane_nodes)

        # Include interactive nodes with no positive rect, including hidden or
        # zero-area nodes, so absence from hit testing is explicit rather than
        # silently dropping them. Their raw paths are also checked against the
        # engine tree to avoid inventing paths the renderer never sees.
        engine_paths = {node.get("_path") for node, _rect in entries}
        for path, choices in metadata.items():
            if path in engine_paths:
                continue
            for meta in choices:
                if not meta.get("interactive"):
                    continue
                record = {
                    "path": path,
                    "class": meta.get("class"),
                    "rect": None,
                    "visible": bool(meta.get("visible", False)),
                    "active": bool(meta.get("active", False)),
                    "selectable": bool(meta.get("selectable", False)),
                    "capturesClicks": bool(meta.get("active", False)),
                    "activatedTargetCandidate": bool(
                        meta.get("class") in _BUTTON_CLASSES and meta.get("active", False)
                    ),
                    "zOrder": None,
                    "pane": pane_index,
                }
                if record["class"] == "TextBox":
                    record["textEditable"] = bool(meta.get("textEditable", True))
                    record["clearTextOnFocus"] = bool(meta.get("clearTextOnFocus", True))
                pane_nodes.append(record)
        pane_records.append(
            {
                "index": pane_index,
                "name": pane_name,
                "inset": inset.describe(),
                "nodes": pane_nodes,
                "entries": entries,
            }
        )

        # Probe the centre of each positive interactive rect. De-duplicate
        # points so coincident buttons produce one useful stack.
        for record in pane_nodes:
            rect = record.get("rect")
            if rect is None:
                continue
            x = _round(rect["x"] + rect["w"] / 2)
            y = _round(rect["y"] + rect["h"] / 2)
            probe_candidates.append((x, y, pane_nodes, pane_index))

    # Cross-pane probing: a higher pane is later in screens and therefore wins.
    # Build one list of unique probe points, then query every pane at each
    # point. This matters when a lower pane's centre lies under a dialog.
    probe_points = sorted({(x, y) for x, y, _pane_nodes, _pane_index in probe_candidates})
    hit_tests: list[dict] = []
    for x, y in probe_points:
        stack: list[dict] = []
        for pane in pane_records:
            for record in pane["nodes"]:
                rect = record.get("rect")
                if rect is None:
                    continue
                if rect["x"] <= x < rect["x"] + rect["w"] and rect["y"] <= y < rect["y"] + rect["h"]:
                    stack.append(record)
        # Sort by pane first, then the traversal's bottom-to-top zOrder. A
        # later pane paints on top; within a pane the larger zOrder is on top.
        stack.sort(key=lambda record: (record["pane"], record["zOrder"] if record["zOrder"] is not None else -1), reverse=True)
        target_record = next((record for record in stack if record["capturesClicks"]), None)
        hit_tests.append(
            {
                "point": {"x": x, "y": y},
                "stack": [record["path"] for record in stack],
                "target": target_record["path"] if target_record else None,
                "targetVisible": target_record["visible"] if target_record else None,
            }
        )

    for pane in pane_records:
        pane.pop("nodes", None)
        pane.pop("entries", None)

    node_records.sort(key=lambda record: (record["path"], record["pane"], record["zOrder"] is None, record["zOrder"] or 0))
    return stamp("hitmap", {
        "model": Path(ir_path).name,
        "viewport": [width, height],
        "panes": pane_records,
        "nodes": node_records,
        "hitTests": hit_tests,
    })


def dump_json(hitmap: dict) -> str:
    """Canonical sorted JSON for stable diffs."""
    return json.dumps(hitmap, indent=2, sort_keys=True)
