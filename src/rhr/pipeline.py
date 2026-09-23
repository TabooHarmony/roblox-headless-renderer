"""IR -> raw nodes -> pinevex object -> PNG.

The order mirrors the web demo's own pipeline (FLOW read out of
vendor/pinevex/web_demo/rbxm_parser_component/app.py):

    find the renderable root -> flatten_node() -> postprocess_pinevex_object() -> render_json()

Keeping that order is what makes a diff against pinevex's committed reference
render attributable: same renderer, same postprocess, only the parser differs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rhr.paths import ICONS_DIR, PINEVEX

ENGINE = PINEVEX / "src"
COMPONENT = PINEVEX / "web_demo" / "rbxm_parser_component"
PRODUCT_OUTPUT = PINEVEX / "vendor" / "product_output"

# The engine looks up faces by file name in these folders before its own bundled
# fonts (text_fonts.py): a local Roblox install first (rhr.paths.roblox_font_dirs),
# then RHR's own open-license copies of Roblox's builds (src/rhr/fonts).
if "PINEVEX_RENDERER_ROBLOX_FONT_DIRS" not in os.environ:
    from rhr.paths import FONTS, roblox_font_dirs

    os.environ["PINEVEX_RENDERER_ROBLOX_FONT_DIRS"] = os.pathsep.join(
        str(p) for p in [*roblox_font_dirs(), FONTS]
    )


def font_source() -> str:
    """One line for stderr: which fonts text is drawn with."""
    from rhr.paths import FONTS

    dirs = [p for p in os.environ.get("PINEVEX_RENDERER_ROBLOX_FONT_DIRS", "").split(os.pathsep) if p]
    install = [p for p in dirs if Path(p).resolve() != FONTS.resolve()]
    if install:
        return f"fonts  Roblox install: {install[0]}"
    return ("fonts  bundled (no Roblox install found): faces Roblox does not license for "
            "redistribution, such as Builder Sans, fall back to similar open fonts")


for _p in (ENGINE, COMPONENT, PRODUCT_OUTPUT.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FONTS_DIR = ENGINE / "ui_engine" / "fonts"
# The engine's icon root (rhr.paths.ICONS_DIR). The engine derives its image cache
# from the parent of this dir (`_asset_cache_dir`: <parent>/cache/icons/<asset_id>.png),
# which is rhr.paths.ICON_CACHE, where scripts/fetch_assets.py writes.

_SCREEN_GUI_CLASSES = {"ScreenGui", "SurfaceGui", "BillboardGui"}
_RENDERABLE_CLASSES = {
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


def _prop_is_false(value) -> bool:
    return value is False or (isinstance(value, str) and value.lower() == "false")


def find_renderable(nodes: list[dict]) -> dict | None:
    """Pick the pane to draw, the same way the demo does.

    A ScreenGui with a single child renders that child; with several it renders a
    full-viewport transparent wrapper around them. Without a ScreenGui, the first
    GUI object found anywhere is used.
    """
    for node in nodes:
        cls = node.get("className", "")
        if cls in _SCREEN_GUI_CLASSES:
            children = node.get("children") or []
            if not children:
                continue
            if len(children) == 1:
                return children[0]
            return {
                "className": "Frame",
                "name": node.get("name", "ScreenGui"),
                "properties": {
                    "Size": {"x": {"scale": 1, "offset": 0}, "y": {"scale": 1, "offset": 0}},
                    "BackgroundTransparency": 1,
                },
                "children": children,
            }
        if cls in _RENDERABLE_CLASSES:
            return node
        found = find_renderable(node.get("children") or [])
        if found:
            return found
    return None


def to_pinevex_object(raw_nodes: list[dict], postprocess: bool = True) -> dict:
    """flatten_node (+ the demo's postprocess) on the renderable root."""
    from tree_to_pinevexobject import flatten_node

    renderable = find_renderable(raw_nodes)
    if renderable is None:
        raise ValueError("no renderable ScreenGui or GuiObject found in this tree")
    obj = flatten_node(renderable)
    if not postprocess:
        return obj

    from product_output.pinevex_postprocess import postprocess_pinevex_object

    return postprocess_pinevex_object(obj)


def render_object(
    obj: dict,
    out_path,
    width: int,
    height: int,
    bg_color=(0, 0, 0, 0),
    rect_map: dict | None = None,
    icons_dir=None,
    root_rect=None,
) -> Path:
    from ui_engine.renderer import render_json

    layout_rects = obj.pop("_layoutRects", None) if isinstance(obj, dict) else None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    icons = Path(icons_dir) if icons_dir is not None else ICONS_DIR
    render_json(
        obj,
        str(out_path),
        width=width,
        height=height,
        icons_dir=icons,
        fonts_dir=FONTS_DIR,
        bg_color=bg_color,
        rect_map=rect_map,
        root_rect=root_rect,
        layout_rects=layout_rects,
    )
    return out_path


def _strip_screens(nodes: list[dict]) -> list[dict]:
    """The tree with every ScreenGui subtree removed: the UI that lives outside them.

    A Folder full of bare Frames is not a valid Roblox UI (a GuiObject outside a
    ScreenGui does not draw in the engine), but it is exactly what Studio's own built-in
    models look like: `AnimationEditorGUI.rbxm` keeps its whole editor panel as bare
    Frames under `GUIs`, with three small ScreenGuis for dialogs. The pipeline drew the
    first of those Frames before this change, and it still has to.
    """
    out = []
    for node in nodes:
        if node.get("className", "") in _SCREEN_GUI_CLASSES:
            continue
        kept = dict(node)
        kept["children"] = _strip_screens(node.get("children") or [])
        out.append(kept)
    return out


def _screen_nodes(
    nodes: list[dict],
    out: list[dict] | None = None,
    *,
    classes: set[str] | None = None,
) -> list[dict]:
    """Every ScreenGui-ish node in the tree, paint order: lowest DisplayOrder first.

    A file can hold several ScreenGuis and Roblox draws all of them, a higher
    DisplayOrder on top. The engine draws exactly one root, so the pipeline renders
    one per ScreenGui and composites (see render_ir); this is the list it walks.
    `ScreenGui.Enabled = false` means the pane does not render at all, and an empty
    ScreenGui has nothing to render, so both are dropped here rather than becoming a
    pane the engine would refuse.
    """
    if out is None:
        out = []
    wanted = _SCREEN_GUI_CLASSES if classes is None else classes
    for node in nodes:
        cls = node.get("className", "")
        if cls in wanted:
            if (node.get("children") or []) and not _prop_is_false(
                (node.get("properties") or {}).get("Enabled")
            ):
                out.append(node)
            continue
        # Containers (Folder, Model, Configuration) can wrap a ScreenGui in a saved
        # model; nothing else in a UI tree nests one.
        _screen_nodes(node.get("children") or [], out, classes=wanted)
    out.sort(key=_display_order_of)
    return out


def _display_order_of(node: dict) -> float:
    value = (node.get("properties") or {}).get("DisplayOrder")
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            pass
    return 0.0


def load_screens(
    ir_path,
    width: int,
    height: int,
    topbar_height: float | None = None,
    postprocess: bool = True,
    *,
    screen_gui_only: bool = False,
) -> list[tuple[dict, object, "rhr.insets.Inset", str]]:
    """IR on disk -> one (object, root rect, inset, name) per ScreenGui, bottom first.

    Each ScreenGui gets its own content area from its own `ScreenInsets` (Task 1.9),
    which is why this is per screen rather than one rect for the file. A tree with no
    ScreenGui is a single entry, the whole-viewport case.
    """
    from ui_engine.layout import Rect

    from rhr import insets
    from rhr.adapter import ir_to_raw_nodes
    from rhr.ir import load_ir

    topbar = insets.REFERENCE_TOPBAR_HEIGHT if topbar_height is None else topbar_height
    ir = load_ir(ir_path)
    ir_by_path = _index_paths(ir["roots"])
    raw = ir_to_raw_nodes(ir)
    screens = _screen_nodes(raw, classes={"ScreenGui"} if screen_gui_only else None)
    if not screens:
        if screen_gui_only:
            return []
        # Only disabled or empty ScreenGuis (if any): they draw nothing, so they must
        # not reach the layout, hitmap or checks either. What is left outside them is
        # the whole-viewport case; if nothing is left, there is no UI at all.
        raw = _strip_screens(raw)
        pane = find_renderable(raw)
        if pane is None:
            return []
        inset = insets.for_nodes(raw, topbar_height=topbar)
        x, y, w, h = inset.rect(width, height)
        obj = to_pinevex_object(raw, postprocess)
        _attach_layout(obj, pane, ir_by_path, (x, y, w, h))
        return [(obj, Rect(x, y, w, h), inset, Path(ir_path).stem)]

    # Bottom pane first: the UI outside the ScreenGuis (what a ScreenGui-less model has
    # always rendered), then each ScreenGui by DisplayOrder. A container pane has no
    # ScreenGui, so it gets no safe-area inset, unlike the dialogs above it.
    panes = []
    container = None if screen_gui_only else find_renderable(_strip_screens(raw))
    if container is not None:
        panes.append(container)
    panes += screens

    out = []
    for node in panes:
        inset = insets.for_nodes([node], topbar_height=topbar)
        x, y, w, h = inset.rect(width, height)
        obj = to_pinevex_object([node], postprocess)
        _attach_layout(obj, node, ir_by_path, (x, y, w, h))
        out.append((obj, Rect(x, y, w, h), inset, node.get("name", "ScreenGui")))
    return out


def _index_paths(roots: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}

    def walk(node: dict) -> None:
        found[node["path"]] = node
        for child in node.get("children") or []:
            walk(child)

    for root in roots:
        walk(root)
    return found


def _attach_layout(obj: dict, pane: dict | None, ir_by_path: dict[str, dict], rect) -> None:
    """Lay the pane out with rhr.ui_layout and hand the rects to the engine.

    The engine draws at these rects (obj["_layoutRects"], read by render_object); its
    own layout code only runs for objects this pass has no rect for. Under UIScale the
    drawn text size and outline thickness scale with the object, as in Roblox.
    """
    from ui_engine.layout import Rect

    from rhr.ui_layout import lay_out_pane

    ir_node = ir_by_path.get((pane or {}).get("_path"))
    if ir_node is None:
        return
    boxes = lay_out_pane(ir_node, rect)
    obj["_layoutRects"] = {path: Rect(b.x, b.y, b.w, b.h) for path, b in boxes.items()}
    scales = {path: b.scale for path, b in boxes.items() if abs(b.scale - 1.0) > 1e-9}
    if not scales:
        return

    def walk(node: dict) -> None:
        factor = scales.get(node.get("_path"))
        if factor is not None:
            if "textSize" in node:
                node["textSize"] = float(node["textSize"]) * factor
            for stroke in node.get("strokes") or []:
                if isinstance(stroke, dict) and "thickness" in stroke:
                    stroke["thickness"] = float(stroke["thickness"]) * factor
        for child in node.get("children") or []:
            walk(child)

    walk(obj)


def load_for_screen(
    ir_path,
    width: int,
    height: int,
    topbar_height: float | None = None,
) -> tuple[dict, object, "rhr.insets.Inset"]:
    """IR on disk -> (pinevex object, root rect, the inset it came from).

    The root rect is the ScreenGui's content area (rhr.insets), not the whole
    canvas: Roblox lays a ScreenGui's descendants out inside the safe area, so a
    child at 0,0 sits below the top bar. Passing it to the engine moves the tree
    and makes scale-sized children measure against the safe area, which is what
    `_viewport_rect` is for.
    """
    from ui_engine.layout import Rect

    from rhr.adapter import ir_to_raw_nodes
    from rhr import insets
    from rhr.ir import load_ir

    raw = ir_to_raw_nodes(load_ir(ir_path))
    inset = insets.for_nodes(
        raw,
        topbar_height=insets.REFERENCE_TOPBAR_HEIGHT if topbar_height is None else topbar_height,
    )
    x, y, w, h = inset.rect(width, height)
    return to_pinevex_object(raw), Rect(x, y, w, h), inset


def _viewport_nodes(obj: dict) -> list[dict]:
    found = []

    def walk(node: dict):
        if node.get("type") == "ViewportFrame":
            found.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(obj)
    return found


def _overlay_viewports(obj: dict, image_path: Path, rect_map: dict, source_ir) -> None:
    """Rasterize ViewportFrame 3D children and composite them into a UI pane."""
    viewports = _viewport_nodes(obj)
    if not viewports or source_ir is None:
        return

    from PIL import Image, ImageChops
    from rhr.scene import render_viewport

    temporary = []
    try:
        with Image.open(image_path).convert("RGBA") as base:
            for index, node in enumerate(viewports):
                rect = rect_map.get(node.get("_path"))
                if rect is None or rect.w <= 0 or rect.h <= 0:
                    continue
                width, height = max(1, round(rect.w)), max(1, round(rect.h))
                overlay_path = image_path.with_name(f".{image_path.stem}-viewport{index}.png")
                temporary.append(overlay_path)
                render_viewport(Path(source_ir), overlay_path, width, height, node["_path"])
                with Image.open(overlay_path).convert("RGBA") as overlay:
                    tint = node.get("imageColor")
                    if isinstance(tint, list) and len(tint) == 3:
                        color = Image.new("RGBA", overlay.size, tuple(tint) + (255,))
                        overlay = ImageChops.multiply(overlay, color)
                    transparency = float(node.get("imageTransparency", 0) or 0)
                    if transparency > 0:
                        alpha = overlay.getchannel("A").point(lambda value: round(value * max(0, 1 - transparency)))
                        overlay.putalpha(alpha)
                    base.alpha_composite(overlay, (round(rect.x), round(rect.y)))
            base.save(image_path)
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)

def render_screens(
    screens,
    out_path,
    width: int,
    height: int,
    bg_color=(0, 0, 0, 0),
    rect_map: dict | None = None,
    icons_dir=None,
    source_ir=None,
) -> Path:
    """A load_screens() list -> one PNG.

    One ScreenGui is one engine render, which is the path the frozen gate measures and
    must not change. Several ScreenGuis are one render each, composited in paint order,
    because the engine draws exactly one root: a file that holds a HUD pane and a shop
    pane used to lose one of them entirely.
    """
    out_path = Path(out_path)
    if len(screens) == 1:
        obj, root_rect, _, _ = screens[0]
        render_map = rect_map if rect_map is not None else ({} if source_ir is not None else None)
        result = render_object(
            obj, out_path, width, height, bg_color, render_map, icons_dir, root_rect=root_rect
        )
        if render_map is not None:
            _overlay_viewports(obj, result, render_map, source_ir)
        return result

    from PIL import Image

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (width, height), tuple(bg_color))
    panes = []
    try:
        for index, (obj, root_rect, _, name) in enumerate(screens):
            pane = out_path.with_name(f".{out_path.stem}-pane{index}.png")
            panes.append(pane)
            pane_map = {} if rect_map is not None or source_ir is not None else None
            render_object(obj, pane, width, height, (0, 0, 0, 0), pane_map, icons_dir, root_rect=root_rect)
            if pane_map is not None:
                _overlay_viewports(obj, pane, pane_map, source_ir)
            with Image.open(pane).convert("RGBA") as image:
                canvas.alpha_composite(image)
            if rect_map is not None and pane_map is not None:
                rect_map.update(pane_map)
    finally:
        for pane in panes:
            pane.unlink(missing_ok=True)
    canvas.save(out_path)
    return out_path


def render_ir(
    ir_path,
    out_path,
    width: int,
    height: int,
    bg_color=(0, 0, 0, 0),
    postprocess: bool = True,
    rect_map: dict | None = None,
    icons_dir=None,
    topbar_height: float | None = None,
) -> Path:
    """Full path: IR JSON on disk -> PNG, laid out in each ScreenGui's own safe area."""
    screens = load_screens(ir_path, width, height, topbar_height, postprocess)
    return render_screens(screens, out_path, width, height, bg_color, rect_map, icons_dir, source_ir=ir_path)


MAX_GUI_CANVAS = 4096


def render_gui_node(ir, node_path: str, width: int, height: int, out_path) -> Path:
    """Render one BillboardGui/SurfaceGui subtree with the 2D engine at width x height.

    In-world UI goes through the same renderer as ScreenGuis, laid out on the canvas
    size Roblox would give it (the scene page computes that: camera distance for a
    BillboardGui, face size x PixelsPerStud or CanvasSize for a SurfaceGui). Canvases
    larger than MAX_GUI_CANVAS per side are clamped (see known-approximations).
    """
    from rhr.adapter import ir_node_to_raw
    from rhr.ir import resolve_path

    node = resolve_path(ir["roots"], node_path)
    if node.get("className") not in {"BillboardGui", "SurfaceGui"}:
        raise ValueError(f"{node_path} is a {node.get('className')}, not a BillboardGui or SurfaceGui")
    width = max(1, min(int(width), MAX_GUI_CANVAS))
    height = max(1, min(int(height), MAX_GUI_CANVAS))
    return render_object(to_pinevex_object([ir_node_to_raw(node)]), out_path, width, height, (0, 0, 0, 0))


def render_pinevex_json(
    json_path,
    out_path,
    width: int,
    height: int,
    bg_color=(0, 0, 0, 0),
    icons_dir=None,
) -> Path:
    """Render an object already in the engine's own schema: no IR, no adapter.

    This is the vendored engine's native input (what its committed reference render
    was made from), so it pins renderer behaviour without our parsing path in the
    way. Used by the regression baseline.
    """
    return render_object(
        json.loads(Path(json_path).read_text(encoding="utf-8")),
        out_path,
        width,
        height,
        bg_color,
        icons_dir=icons_dir,
    )