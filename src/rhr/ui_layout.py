"""RHR's UI layout pass: every GuiObject's absolute rect, computed once.

Pinevex (the 2D renderer) used to lay out while drawing, with separate copies of that
logic for hit-testing, so the picture, `rhr layout` and `rhr hitmap` could disagree and
several Roblox layout features were missing. This module computes the rects from the
IR with Roblox's rules, checked against rects Studio itself recorded (tests/studio/),
and everything else reads them: Pinevex draws at these rects, the layout dump reports
them, the hit map tests against them.

Semantics, each pinned by a Studio fixture (tests/studio/ui_*.rbxlx):
  * Size/Position UDim2 against the parent's content box (its rect minus UIPadding);
    SizeConstraint RelativeXX/YY; AnchorPoint.
  * UISizeConstraint clamps, then UIAspectRatioConstraint fits the ratio inside the
    object's own size (FitWithinMaxSize) or its parent's (ScaleWithParentSize).
  * UIScale scales the object's size around its anchor point and every pixel offset
    below it (nested scales multiply).
  * AutomaticSize grows an object to its text (measured with the drawing fonts) or to
    its children's extent, plus its own UIPadding; the authored size is the minimum.
  * UIListLayout: sort order, padding, alignment, Wraps, HorizontalFlex/VerticalFlex
    (Fill, SpaceBetween, SpaceAround, SpaceEvenly), ItemLineAlignment and UIFlexItem.
  * UIGridLayout: cell size/padding, FillDirection, FillDirectionMaxCells, StartCorner,
    alignment of the cell block.
  * UITableLayout: rows of cells, column widths and row heights from the largest cell.
  * ScrollingFrame: CanvasSize (+ AutomaticCanvasSize), CanvasPosition (clamped),
    children's Scale against the window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

GUI_OBJECT_CLASSES = {
    "Frame", "CanvasGroup", "ScrollingFrame", "TextLabel", "TextButton", "TextBox",
    "ImageLabel", "ImageButton", "ViewportFrame", "VideoFrame",
}
TEXT_CLASSES = {"TextLabel", "TextButton", "TextBox"}
LAYOUT_CLASSES = ("UIListLayout", "UIGridLayout", "UITableLayout", "UIPageLayout")
# Containers that are not GuiObjects but whose GuiObject children still draw in the
# enclosing canvas (a Folder inside a ScreenGui, a Model inside a SurfaceGui, ...).
PASS_THROUGH_CLASSES = {"Folder", "Model", "Configuration"}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    scale: float = 1.0  # cumulative UIScale applied to this object's pixel offsets


# ---------------------------------------------------------------- property access

def _props(node: dict) -> dict:
    return node.get("props") or {}


def _num(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _enum(node: dict, name: str, default: str) -> str:
    value = _props(node).get(name)
    if isinstance(value, dict):
        return str(value.get("name", default))
    if isinstance(value, str):
        return value.rsplit(".", 1)[-1]
    return default


def _bool(node: dict, name: str, default: bool) -> bool:
    value = _props(node).get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return default


def _udim2(node: dict, name: str, default=(0.0, 0.0, 0.0, 0.0)) -> tuple[float, float, float, float]:
    value = _props(node).get(name)
    if not isinstance(value, dict):
        return default
    return (_num(value.get("XS")), _num(value.get("XO")), _num(value.get("YS")), _num(value.get("YO")))


def _udim(node: dict, name: str) -> tuple[float, float]:
    value = _props(node).get(name)
    if not isinstance(value, dict):
        return (0.0, 0.0)
    return (_num(value.get("Scale")), _num(value.get("Offset")))


def _vec2(node: dict, name: str, default=(0.0, 0.0)) -> tuple[float, float]:
    value = _props(node).get(name)
    if not isinstance(value, dict):
        return default
    return (_num(value.get("X"), default[0]), _num(value.get("Y"), default[1]))


def _children(node: dict) -> list[dict]:
    return list(node.get("children") or [])


def _modifier(node: dict, class_name: str) -> dict | None:
    return next((child for child in _children(node) if child.get("className") == class_name), None)


def _layout_object(node: dict) -> dict | None:
    return next((child for child in _children(node) if child.get("className") in LAYOUT_CLASSES), None)


def _gui_children(node: dict) -> list[dict]:
    """GuiObject children, looking through pass-through containers (Folders)."""
    out: list[dict] = []
    for child in _children(node):
        cls = child.get("className")
        if cls in GUI_OBJECT_CLASSES:
            out.append(child)
        elif cls in PASS_THROUGH_CLASSES:
            out.extend(_gui_children(child))
    return out


def _visible(node: dict) -> bool:
    return _bool(node, "Visible", True)


def _sorted(children: list[dict], layout: dict | None) -> list[dict]:
    if layout is not None and _enum(layout, "SortOrder", "LayoutOrder") == "Name":
        return sorted(children, key=lambda child: str(child.get("name", "")))
    return sorted(children, key=lambda child: _num(_props(child).get("LayoutOrder")))


def _padding(node: dict, w: float, h: float, k: float) -> tuple[float, float, float, float]:
    pad = _modifier(node, "UIPadding")
    if pad is None:
        return (0.0, 0.0, 0.0, 0.0)

    def side(name: str, ref: float) -> float:
        scale, offset = _udim(pad, name)
        return scale * ref + offset * k

    return (side("PaddingLeft", w), side("PaddingTop", h), side("PaddingRight", w), side("PaddingBottom", h))


# ---------------------------------------------------------------- sizing

def _fit_ratio(w: float, h: float, ratio: float) -> tuple[float, float]:
    if ratio <= 0 or w <= 0 or h <= 0:
        return w, h
    if w / h > ratio:
        return h * ratio, h
    return w, w / ratio


def _apply_constraints(node: dict, w: float, h: float, parent: Box, k: float) -> tuple[float, float]:
    limits = _modifier(node, "UISizeConstraint")
    if limits is not None:
        low = _vec2(limits, "MinSize", (0.0, 0.0))
        high = _vec2(limits, "MaxSize", (math.inf, math.inf))
        w = min(max(w, low[0] * k), high[0] * k)
        h = min(max(h, low[1] * k), high[1] * k)
    aspect = _modifier(node, "UIAspectRatioConstraint")
    if aspect is not None:
        ratio = _num(_props(aspect).get("AspectRatio"), 1.0)
        if _enum(aspect, "AspectType", "FitWithinMaxSize") == "ScaleWithParentSize":
            w, h = _fit_ratio(parent.w, parent.h, ratio)
        else:
            w, h = _fit_ratio(w, h, ratio)
    return w, h


def _own_scale(node: dict) -> float:
    scale = _modifier(node, "UIScale")
    return _num(_props(scale).get("Scale"), 1.0) if scale is not None else 1.0


def _base_size(node: dict, parent: Box, k: float) -> tuple[float, float]:
    xs, xo, ys, yo = _udim2(node, "Size", (0.0, 100.0, 0.0, 100.0))
    constraint = _enum(node, "SizeConstraint", "RelativeXY")
    ref_w, ref_h = parent.w, parent.h
    if constraint == "RelativeXX":
        ref_h = parent.w
    elif constraint == "RelativeYY":
        ref_w = parent.h
    return xs * ref_w + xo * k, ys * ref_h + yo * k


def _text_extent(node: dict, wrap_width: float | None) -> tuple[float, float] | None:
    """(width, height) of a text object's text, measured with the drawing fonts."""
    try:
        from rhr.adapter import ir_node_to_raw
        from rhr import pipeline  # noqa: F401  (puts the engine on sys.path)
        from tree_to_pinevexobject import flatten_node
        from ui_engine.layout import _measured_text_lines
    except Exception:
        return None
    shallow = dict(node, children=[child for child in _children(node) if child.get("className") not in GUI_OBJECT_CLASSES])
    engine_node = flatten_node(ir_node_to_raw(shallow))
    if not engine_node.get("text"):
        return (0.0, 0.0)
    engine_node["textWrapped"] = _bool(node, "TextWrapped", False)
    lines = _measured_text_lines(engine_node, wrap_width=wrap_width)
    if lines is None:
        return None
    size = _num(_props(node).get("TextSize"), 14.0)
    line_height = _num(_props(node).get("LineHeight"), 1.0) or 1.0
    return (max(lines, default=0.0), size * line_height * len(lines))


# ---------------------------------------------------------------- the pass

class UILayout:
    """Lay out every GuiObject under the given roots; `boxes` maps node path -> Box."""

    def __init__(self) -> None:
        self.boxes: dict[str, Box] = {}
        # Nodes an ancestor's layout already placed (UITableLayout cells): their own
        # parent's pass must not re-resolve them from Position/Size.
        self.placed_by_ancestor: set[str] = set()

    # A node's own rect, before its children are placed.
    def _resolve(self, node: dict, parent: Box, k: float, *, position: bool = True) -> Box:
        w, h = _base_size(node, parent, k)
        w, h = self._automatic(node, w, h, parent, k)
        w, h = _apply_constraints(node, w, h, parent, k)
        own = _own_scale(node)
        w, h = w * own, h * own
        if not position:
            return Box(parent.x, parent.y, w, h, k * own)
        xs, xo, ys, yo = _udim2(node, "Position")
        ax, ay = _vec2(node, "AnchorPoint")
        px = parent.x + xs * parent.w + xo * k
        py = parent.y + ys * parent.h + yo * k
        return Box(px - ax * w, py - ay * h, w, h, k * own)

    def _automatic(self, node: dict, w: float, h: float, parent: Box, k: float) -> tuple[float, float]:
        mode = _enum(node, "AutomaticSize", "None")
        if mode == "None":
            return w, h
        grow_x, grow_y = mode in ("X", "XY"), mode in ("Y", "XY")
        left, top, right, bottom = _padding(node, w, h, k)
        content_w = content_h = 0.0
        if node.get("className") in TEXT_CLASSES:
            wrap = None if grow_x else max(0.0, w - left - right)
            extent = _text_extent(node, wrap)
            if extent is not None:
                content_w, content_h = extent[0] * k, extent[1] * k
        # Children count too (a label with an icon child, a frame with rows).
        probe = UILayout()
        inner = Box(0.0, 0.0, max(0.0, w - left - right), max(0.0, h - top - bottom), k)
        probe._place_children(node, inner, k * _own_scale(node), measuring=True)
        for child in _gui_children(node):
            box = probe.boxes.get(child["path"])
            if box is None or not _visible(child):
                continue
            xs, _, ys, _ = _udim2(child, "Size")
            if grow_x and xs == 0:
                content_w = max(content_w, box.x + box.w)
            if grow_y and ys == 0:
                content_h = max(content_h, box.y + box.h)
        if grow_x:
            w = max(w, content_w + left + right)
        if grow_y:
            h = max(h, content_h + top + bottom)
        return w, h

    def lay_out(self, node: dict, parent: Box, k: float = 1.0) -> Box:
        box = self._resolve(node, parent, k)
        self._finish(node, box)
        return box

    def _finish(self, node: dict, box: Box) -> None:
        """Record a placed node and lay out its children inside it."""
        self.boxes[node["path"]] = box
        left, top, right, bottom = _padding(node, box.w, box.h, box.scale)
        content = Box(box.x + left, box.y + top, max(0.0, box.w - left - right),
                      max(0.0, box.h - top - bottom), box.scale)
        if node.get("className") == "ScrollingFrame":
            content = self._canvas(node, box, content)
        self._place_children(node, content, box.scale)

    def _canvas(self, node: dict, window: Box, content: Box) -> Box:
        cxs, cxo, cys, cyo = _udim2(node, "CanvasSize")
        canvas_w = cxs * window.w + cxo * window.scale
        canvas_h = cys * window.h + cyo * window.scale
        automatic = _enum(node, "AutomaticCanvasSize", "None")
        if automatic != "None":
            probe = UILayout()
            probe._place_children(node, Box(0.0, 0.0, content.w, content.h, window.scale), window.scale, measuring=True)
            extent_w = extent_h = 0.0
            for child in _gui_children(node):
                child_box = probe.boxes.get(child["path"])
                if child_box is not None and _visible(child):
                    extent_w = max(extent_w, child_box.x + child_box.w)
                    extent_h = max(extent_h, child_box.y + child_box.h)
            left, top, right, bottom = _padding(node, window.w, window.h, window.scale)
            if automatic in ("X", "XY"):
                canvas_w = max(canvas_w, extent_w + left + right)
            if automatic in ("Y", "XY"):
                canvas_h = max(canvas_h, extent_h + top + bottom)
        cx, cy = _vec2(node, "CanvasPosition")
        cx = min(max(cx, 0.0), max(0.0, canvas_w - window.w))
        cy = min(max(cy, 0.0), max(0.0, canvas_h - window.h))
        # Children's Scale resolves against the window (patch 0015, Studio-measured);
        # their origin is the scrolled canvas.
        return Box(content.x - cx, content.y - cy, content.w, content.h, content.scale)

    def _place_children(self, node: dict, content: Box, k: float, measuring: bool = False) -> None:
        layout = _layout_object(node)
        children = _gui_children(node)
        kind = layout.get("className") if layout is not None else None
        if kind in ("UIListLayout", "UIPageLayout"):
            self._list(layout, children, content, k)
        elif kind == "UIGridLayout":
            self._grid(layout, children, content, k)
        elif kind == "UITableLayout":
            self._table(layout, children, content, k)
        else:
            for child in children:
                if child["path"] in self.placed_by_ancestor:
                    continue
                box = self._resolve(child, content, k)
                self.boxes[child["path"]] = box
        if measuring:
            return
        for child in children:
            self._finish(child, self.boxes[child["path"]])

    # ------------------------------------------------------------ UIListLayout

    def _list(self, layout: dict, children: list[dict], content: Box, k: float) -> None:
        horizontal = _enum(layout, "FillDirection", "Vertical") == "Horizontal"
        items = [child for child in _sorted(children, layout)]
        main_size = content.w if horizontal else content.h
        cross_size = content.h if horizontal else content.w
        pad_scale, pad_offset = _udim(layout, "Padding")
        padding = pad_scale * main_size + pad_offset * k
        h_align = _enum(layout, "HorizontalAlignment", "Left")
        v_align = _enum(layout, "VerticalAlignment", "Top")
        main_align = h_align if horizontal else v_align
        cross_align = v_align if horizontal else h_align
        flex = _enum(layout, "HorizontalFlex" if horizontal else "VerticalFlex", "None")
        line_align = _enum(layout, "ItemLineAlignment", "Automatic")
        wraps = _bool(layout, "Wraps", False)

        sized: list[tuple[dict, Box]] = []
        for child in items:
            box = self._resolve(child, content, k, position=False)
            if not _visible(child):
                # Invisible items take no space; keep a rect for reporting.
                self.boxes[child["path"]] = Box(content.x, content.y, box.w, box.h, box.scale)
                continue
            sized.append((child, box))

        def main(box: Box) -> float:
            return box.w if horizontal else box.h

        def cross(box: Box) -> float:
            return box.h if horizontal else box.w

        lines: list[list[tuple[dict, Box]]] = []
        current: list[tuple[dict, Box]] = []
        used = 0.0
        for child, box in sized:
            extra = main(box) + (padding if current else 0.0)
            if wraps and current and used + extra > main_size + 1e-6:
                lines.append(current)
                current, used = [], 0.0
                extra = main(box)
            current.append((child, box))
            used += extra
        if current:
            lines.append(current)

        line_cross = [max((cross(box) for _, box in line), default=0.0) for line in lines]
        cross_padding = pad_scale * cross_size + pad_offset * k
        if wraps:
            block = sum(line_cross) + cross_padding * max(0, len(lines) - 1)
            cross_cursor = _align(cross_align, cross_size, block)
        else:
            cross_cursor = 0.0

        for line, line_extent in zip(lines, line_cross):
            if not wraps:
                line_extent = cross_size
            mains = [main(box) for _, box in line]
            free = main_size - sum(mains) - padding * max(0, len(line) - 1)
            grow = [self._flex_ratio(child, flex, "grow") for child, _ in line]
            shrink = [self._flex_ratio(child, flex, "shrink") for child, _ in line]
            if free > 1e-6 and sum(grow) > 0:
                mains = [m + free * g / sum(grow) for m, g in zip(mains, grow)]
                free = 0.0
            elif free < -1e-6 and sum(shrink) > 0:
                weights = [s * m for s, m in zip(shrink, mains)]
                total = sum(weights) or 1.0
                mains = [max(0.0, m + free * wgt / total) for m, wgt in zip(mains, weights)]
                free = 0.0
            gap = padding
            start = 0.0
            count = len(line)
            if free > 1e-6 and flex == "SpaceBetween" and count > 1:
                gap += free / (count - 1)
            elif free > 1e-6 and flex == "SpaceAround" and count > 0:
                gap += free / count
                start = free / count / 2
            elif free > 1e-6 and flex == "SpaceEvenly":
                gap += free / (count + 1)
                start = free / (count + 1)
            else:
                start = _align(main_align, main_size, main_size - free)
            cursor = start
            for (child, box), size_main in zip(line, mains):
                item_cross = cross(box)
                align = self._item_line_alignment(child, line_align)
                if align == "Stretch":
                    item_cross = line_extent
                    offset = 0.0
                elif align in ("Start", "Center", "End"):
                    offset = {"Start": 0.0, "Center": (line_extent - item_cross) / 2,
                              "End": line_extent - item_cross}[align]
                else:
                    offset = _align(cross_align, line_extent, item_cross)
                if horizontal:
                    placed = Box(content.x + cursor, content.y + cross_cursor + offset, size_main, item_cross, box.scale)
                else:
                    placed = Box(content.x + cross_cursor + offset, content.y + cursor, item_cross, size_main, box.scale)
                self.boxes[child["path"]] = placed
                cursor += size_main + gap
            cross_cursor += line_extent + cross_padding

    @staticmethod
    def _flex_ratio(child: dict, container_flex: str, kind: str) -> float:
        item = _modifier(child, "UIFlexItem")
        mode = _enum(item, "FlexMode", "None") if item is not None else "None"
        if mode == "Custom":
            return max(0.0, _num(_props(item).get("GrowRatio" if kind == "grow" else "ShrinkRatio")))
        if mode == "Fill" or (mode == "None" and container_flex == "Fill"):
            return 1.0
        if mode == "Grow":
            return 1.0 if kind == "grow" else 0.0
        if mode == "Shrink":
            return 1.0 if kind == "shrink" else 0.0
        return 0.0

    @staticmethod
    def _item_line_alignment(child: dict, container: str) -> str:
        item = _modifier(child, "UIFlexItem")
        own = _enum(item, "ItemLineAlignment", "Automatic") if item is not None else "Automatic"
        return own if own != "Automatic" else container

    # ------------------------------------------------------------ UIGridLayout

    def _grid(self, layout: dict, children: list[dict], content: Box, k: float) -> None:
        items = [child for child in _sorted(children, layout) if _visible(child)]
        for child in children:
            if not _visible(child):
                box = self._resolve(child, content, k)
                self.boxes[child["path"]] = box
        cxs, cxo, cys, cyo = _udim2(layout, "CellSize", (0.0, 100.0, 0.0, 100.0))
        pxs, pxo, pys, pyo = _udim2(layout, "CellPadding", (0.0, 5.0, 0.0, 5.0))
        cell_w, cell_h = cxs * content.w + cxo * k, cys * content.h + cyo * k
        aspect = _modifier(layout, "UIAspectRatioConstraint")
        if aspect is not None:
            cell_w, cell_h = _fit_ratio(cell_w, cell_h, _num(_props(aspect).get("AspectRatio"), 1.0))
        pad_x, pad_y = pxs * content.w + pxo * k, pys * content.h + pyo * k
        horizontal = _enum(layout, "FillDirection", "Horizontal") == "Horizontal"
        along, gap = (cell_w, pad_x) if horizontal else (cell_h, pad_y)
        room = content.w if horizontal else content.h
        per_line = max(1, int(math.floor((room + gap + 1e-6) / (along + gap)))) if along + gap > 0 else 1
        cap = int(_num(_props(layout).get("FillDirectionMaxCells")))
        if cap > 0:
            per_line = min(per_line, cap)
        count = len(items)
        if not count:
            return
        lines = math.ceil(count / per_line)
        cols, rows = (min(count, per_line), lines) if horizontal else (lines, min(count, per_line))
        block_w = cols * cell_w + max(0, cols - 1) * pad_x
        block_h = rows * cell_h + max(0, rows - 1) * pad_y
        origin_x = content.x + _align(_enum(layout, "HorizontalAlignment", "Left"), content.w, block_w)
        origin_y = content.y + _align(_enum(layout, "VerticalAlignment", "Top"), content.h, block_h)
        corner = _enum(layout, "StartCorner", "TopLeft")
        for index, child in enumerate(items):
            along_index, line_index = index % per_line, index // per_line
            col, row = (along_index, line_index) if horizontal else (line_index, along_index)
            if corner in ("TopRight", "BottomRight"):
                col = cols - 1 - col
            if corner in ("BottomLeft", "BottomRight"):
                row = rows - 1 - row
            # The grid sets the cell size; the child's own constraints and UIScale
            # still apply inside it (Studio: square cells from a cell's own
            # UIAspectRatioConstraint, tests/studio/rtl2pcparts).
            # A child its constraints shrink inside the cell is centred in it,
            # whatever its AnchorPoint (Studio: square cards in 110.8x128.5 cells sit
            # 8.84px down, tests/studio/rtl2pcparts).
            w, h = _apply_constraints(child, cell_w, cell_h, content, k)
            own = _own_scale(child)
            w, h = w * own, h * own
            cell_x = origin_x + col * (cell_w + pad_x)
            cell_y = origin_y + row * (cell_h + pad_y)
            self.boxes[child["path"]] = Box(cell_x + (cell_w - w) / 2, cell_y + (cell_h - h) / 2, w, h, k * own)

    # ------------------------------------------------------------ UITableLayout

    def _table(self, layout: dict, children: list[dict], content: Box, k: float) -> None:
        rows = [child for child in _sorted(children, layout) if _visible(child)]
        pxs, pxo, pys, pyo = _udim2(layout, "Padding")
        pad_x, pad_y = pxs * content.w + pxo * k, pys * content.h + pyo * k
        horizontal = _enum(layout, "FillDirection", "Vertical") == "Horizontal"
        grid: list[list[tuple[dict, Box]]] = []
        for row in rows:
            cells = [cell for cell in _sorted(_gui_children(row), layout) if _visible(cell)]
            grid.append([(cell, self._resolve(cell, content, k, position=False)) for cell in cells])
        if horizontal:  # each child is a column; transpose so rows are rows
            width = max((len(column) for column in grid), default=0)
            grid = [[column[i] for column in grid if i < len(column)] for i in range(width)]
        column_count = max((len(line) for line in grid), default=0)
        col_w = [max((line[c][1].w for line in grid if c < len(line)), default=0.0) for c in range(column_count)]
        row_h = [max((box.h for _, box in line), default=0.0) for line in grid]
        y = content.y
        for index, (line, height) in enumerate(zip(grid, row_h)):
            x = content.x
            for c, (cell, _) in enumerate(line):
                self.boxes[cell["path"]] = Box(x, y, col_w[c], height, k)
                self.placed_by_ancestor.add(cell["path"])
                x += col_w[c] + pad_x
            if not horizontal and index < len(rows):
                total_w = sum(col_w) + pad_x * max(0, column_count - 1)
                self.boxes[rows[index]["path"]] = Box(content.x, y, total_w, height, k)
            y += height + pad_y
        if horizontal:
            x = content.x
            total_h = sum(row_h) + pad_y * max(0, len(row_h) - 1)
            for c, column in enumerate(rows):
                self.boxes[column["path"]] = Box(x, content.y, col_w[c] if c < len(col_w) else 0.0, total_h, k)
                x += (col_w[c] if c < len(col_w) else 0.0) + pad_x
        for row in children:
            if row["path"] not in self.boxes:
                self.boxes[row["path"]] = self._resolve(row, content, k)


def _align(mode: str, container: float, extent: float) -> float:
    if mode == "Center":
        return (container - extent) / 2
    if mode in ("Right", "Bottom", "End"):
        return container - extent
    return 0.0


def lay_out_pane(root: dict, rect: tuple[float, float, float, float]) -> dict[str, Box]:
    """Lay out one pane: a ScreenGui (or other canvas) node inside its content rect.

    `root` is a ScreenGui/SurfaceGui/BillboardGui whose GuiObject descendants are laid
    out inside `rect`, or a lone GuiObject laid out as if its parent were `rect`.
    """
    x, y, w, h = rect
    engine = UILayout()
    canvas = Box(x, y, w, h, 1.0)
    if root.get("className") in GUI_OBJECT_CLASSES:
        engine.lay_out(root, canvas)
    else:
        engine._place_children(root, canvas, 1.0)
    return engine.boxes


# ---------------------------------------------------------------- paint order and clipping

CLIPPING_CLASSES = {"ScrollingFrame", "CanvasGroup"}


def _intersect(a: Box, b: Box | None) -> Box:
    if b is None:
        return a
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    return Box(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0), a.scale)


def paint_entries(root: dict, rect: tuple[float, float, float, float]) -> list[tuple[dict, Box]]:
    """Every GuiObject of a pane, bottom to top, with its rect clipped by its ancestors.

    Hidden objects are included (visibility is the caller's concern: an invisible but
    Active object still captures input). Paint order follows the pane's
    ZIndexBehavior: Sibling (children above their parent, siblings by ZIndex then
    tree order) or Global (all objects by ZIndex, ties in tree order). Clipping comes
    from ClipsDescendants, ScrollingFrame windows and CanvasGroups.
    """
    boxes = lay_out_pane(root, rect)
    behavior = _enum(root, "ZIndexBehavior", "Sibling")
    ordered: list[tuple[float, int, dict, Box]] = []
    counter = [0]

    def zindex(node: dict) -> float:
        return _num(_props(node).get("ZIndex"), 1.0)

    def visit(node: dict, clip: Box | None) -> None:
        box = boxes.get(node["path"])
        if box is None:
            return
        counter[0] += 1
        ordered.append((zindex(node), counter[0], node, _intersect(box, clip)))
        inner = clip
        if node.get("className") in CLIPPING_CLASSES or _bool(node, "ClipsDescendants", False):
            inner = _intersect(box, clip)
        children = _gui_children(node)
        if behavior != "Global":
            children = sorted(children, key=zindex)  # stable: ties keep tree order
        for child in children:
            visit(child, inner)

    roots = [root] if root.get("className") in GUI_OBJECT_CLASSES else _gui_children(root)
    if behavior != "Global":
        roots = sorted(roots, key=zindex)
    for node in roots:
        visit(node, None)
    if behavior == "Global":
        ordered.sort(key=lambda item: (item[0], item[1]))
    return [(node, box) for _z, _order, node, box in ordered]
