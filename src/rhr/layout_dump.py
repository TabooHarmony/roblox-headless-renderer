"""The structured layout dump: what each pane is made of, not just where it sits.

`rhr layout` (Phase 1) reports the rect the paint pass resolved per node path.
Task 2.1 extends that to the node's *content*: zIndex,
visibility, resolved background/stroke/gradient colours, text, font size and
clip state, written as stable sorted JSON so two builds diff cleanly.

Determinism is the point: `diff layout-a.json layout-b.json` must show only
real changes. Two properties serve that —

  * the per-node list is sorted by `path`, and every dict key is emitted in
    sorted order (json.dumps(sort_keys=True));
  * everything reported is read off the same converted objects and rect map a
    second build produces, so nothing depends on wall-clock, dict order or
    filesystem state.

How each field is resolved (and what is honestly not resolvable):

  rect          the engine's own rect map (render_json(rect_map=...)), the
                geometry the paint pass actually used — never re-derived.
  path          the adapter's name-segment path (`Name/Child/Grandchild`). Two
                siblings with the same Name collide, in the rect map too (the
                engine overwrites by key); the dump inherits that behaviour and
                documents it rather than inventing a second path scheme.
  class         flatten_node's `type` (the Roblox className).
  zIndex        the engine's `zIndex` (Roblox default 1, reported explicitly).
  visible       False only when the node itself says so; an ancestor's
                `Visible=false` removes the subtree from the paint pass
                entirely, so such nodes are absent from the dump, not marked
                invisible.
  background    the converted `bg` ([r, g, b] 0-255) plus `bgTransparency`.
                Visual classes get the engine's default white when the model
                does not set BackgroundColor3 — that is what paints.
  strokes       the converted UIStroke list: colour, thickness, transparency,
                per stroke, in engine order.
  gradient      the converted UIGradient: stops as (time, #rrggbb) sorted by
                time, transparency stops as (time, value), rotation, offset.
                The *interpolated* colour at an arbitrary point of the rect is
                a draw-time fact; sample it with verify_pixels() rather than
                expecting it here.
  paintOrder    the composite order build_dump walked the panes in (bottom
                pane first, tree order within a pane): later paints over
                earlier. Emitted because `nodes` is sorted by path for clean
                diffs, and path order is not paint order.
  text          `text` (content), `textColor`, and the font size. TextScaled's
                fitted size is computed only at draw time (text_renderers.py /
                text_fit.py) and is not recoverable from the object, so the
                dump reports the specified `textSize` plus the `textScaled`
                flag and does not guess a fitted number.
  clipsDescendants  the converted flag (ScroppingFrames also force-clip their
                children at draw time, which the flag does not say; that extra
                state lives in the engine, not in any node).
  gridCellPx    a UIGridLayout holder's CellSize resolved to pixels by the
                engine's own `_grid_axis` rule (Task 2.2: the zero-size-cell
                check reads it). Only on nodes that carry a grid, and only as
                an honest reference-size reading: a UIPadding on the holder
                shrinks the engine's actual size_ref, which the dump's rect
                (padding excluded) does not show — the check documents that.
  text.truncate / text.maxVisibleGraphemes    Task 2.2: the model's
                TextTruncate mode (name of the enum item, absent for None)
                and typewriter window (absent for -1, the no-effect default),
                read off the converted object like every other text field.

collect_layout_info() (the engine's no-rasterize variant) was considered for
this and rejected: its rect map omits zero-area nodes that the paint pass
records (patches/0002), so it can disagree with rendered pixels. The dump
therefore uses the paint pass's rect map, exactly as `rhr layout` does.
"""

from __future__ import annotations

from rhr.schema import stamp

import json
import sys
from pathlib import Path

from rhr.paths import IR_DIR


_VISUAL_CLASSES = {
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
_TEXT_CLASSES = {"TextLabel", "TextButton", "TextBox"}

_FONT_TOKEN_RE = None  # set lazily; see _unwrap_text


def _round(value: float, places: int = 3) -> float:
    """One rounding policy everywhere, so 58.0 never shows up as 58.00001."""
    return round(float(value), places)


def _unwrap_text(value):
    """The postprocess wraps fonts in <|font:...|> tokens; the dump shows the text."""
    import re

    global _FONT_TOKEN_RE
    if _FONT_TOKEN_RE is None:
        _FONT_TOKEN_RE = re.compile(r"<\|font:[^|]*\|>")
    if not isinstance(value, str):
        return value
    return _FONT_TOKEN_RE.sub("", value)


def _gradient_of(node: dict) -> dict | None:
    gradient = node.get("gradient")
    if not isinstance(gradient, dict) or not gradient.get("colors"):
        return None
    stops = sorted(gradient["colors"], key=lambda stop: stop[0])
    out: dict = {
        "colors": [[_round(t), c] for t, c in stops],
        "rotation": _round(gradient.get("rotation", 0.0)),
    }
    if gradient.get("offset") is not None:
        out["offset"] = [_round(v) for v in gradient["offset"]]
    # Transparency stops are as much a part of the drawn output as the colour
    # stops (make_gradient_shader samples them into every pixel's alpha), so a
    # build that changes only UIGradient.Transparency must not dump identically.
    trans = gradient.get("transparency")
    if trans:
        out["transparency"] = [[_round(t), _round(v)] for t, v in sorted(trans, key=lambda s: s[0])]
    return out


def _strokes_of(node: dict) -> list[dict] | None:
    strokes = node.get("strokes")
    if not strokes:
        return None
    out: list[dict] = []
    for stroke in strokes:
        entry = {"color": list(stroke.get("color", [0, 0, 0]))}
        entry["thickness"] = _round(stroke.get("thickness", 1))
        if "thicknessScale" in stroke:
            entry["thicknessScale"] = bool(stroke["thicknessScale"])
        if stroke.get("applyMode"):
            entry["applyMode"] = stroke["applyMode"]
        entry["transparency"] = _round(stroke.get("transparency", 0.0))
        out.append(entry)
    return out


def _text_of(node: dict) -> dict | None:
    if node.get("type") not in _TEXT_CLASSES:
        return None
    content = _unwrap_text(node.get("text", ""))
    out = {
        "content": content,
        "color": list(node.get("textColor", [27, 42, 53])),
        "size": node.get("textSize", 14),
        "scaled": bool(node.get("textScaled", False)),
        "wrapped": bool(node.get("textWrapped", False)),
        "transparency": _round(node.get("textTransparency", 0.0)),
    }
    # Task 2.2: the truncation mode and the typewriter window are model
    # properties the checks consume, so they ride in the dump rather than a
    # second IR walk. Absent when the model does not set them (the engine
    # defaults are None / -1, i.e. no behaviour).
    truncate = node.get("textTruncate")
    if truncate:
        out["truncate"] = str(truncate).removeprefix("Enum.TextTruncate.")
    graphemes = node.get("maxVisibleGraphemes")
    if graphemes is not None and graphemes != -1:
        out["maxVisibleGraphemes"] = graphemes
    # What the paint pass laid out (plain text only), in Roblox units: the size
    # actually drawn (a TextScaled label's fitted size), the line count, and the
    # text's extent like TextLabel.TextBounds.
    laid_out = node.get("_textLayout")
    if laid_out:
        out["drawnSize"] = _round(laid_out["size"])
        out["lines"] = laid_out["lines"]
        out["bounds"] = [_round(value) for value in laid_out["bounds"]]
    return out


def _grid_cell_px(grid: dict, rect) -> list[float] | None:
    """The grid's CellSize resolved to pixels, by the engine's own rule.

    `_grid_axis` (renderer.py) reads a 2-slot spec as [xScale, yScale] and a
    4-slot one as [xScale, xOffset, yScale, yOffset], scaling against the
    parent-sized reference. The dump has the node's resolved rect, which is
    that reference exactly when the node carries no UIPadding (documented in
    checks.py, whose zero-cell check is the consumer).
    """
    spec = grid.get("cellSize")
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    if len(spec) >= 4:
        w = float(spec[0]) * rect.w + float(spec[1])
        h = float(spec[2]) * rect.h + float(spec[3])
    else:
        w = float(spec[0]) * rect.w
        h = float(spec[1]) * rect.h
    return [_round(w), _round(h)]


def _node_entry(obj: dict, rect) -> dict:
    """One dump entry from the converted pinevex object and its resolved rect."""
    visual = obj.get("type") in _VISUAL_CLASSES
    entry: dict = {
        "path": obj["_path"],
        "class": obj.get("type"),
        "rect": {
            "x": _round(rect.x),
            "y": _round(rect.y),
            "w": _round(rect.w),
            "h": _round(rect.h),
        },
        "zIndex": obj.get("zIndex", 1),
        "visible": obj.get("visible") is not False,
        "clipsDescendants": bool(obj.get("clipsDescendants", False)),
    }
    if visual:
        entry["background"] = {
            "color": list(obj.get("bg", [255, 255, 255])),
            "transparency": _round(obj.get("bgTransparency", 0.0)),
        }
        grid = obj.get("grid")
        if isinstance(grid, dict) and grid.get("cellSize"):
            cell = _grid_cell_px(grid, rect)
            if cell:
                entry["gridCellPx"] = cell
        gradient = _gradient_of(obj)
        if gradient:
            entry["gradient"] = gradient
        strokes = _strokes_of(obj)
        if strokes:
            entry["strokes"] = strokes
    text = _text_of(obj)
    if text:
        entry["text"] = text
    return entry


def _walk(obj: dict, rect_map: dict, out: list[dict]) -> None:
    rect = rect_map.get(obj.get("_path"))
    if rect is not None:
        out.append(_node_entry(obj, rect))
    for child in obj.get("children", []) or []:
        _walk(child, rect_map, out)


def build_dump(ir_path, width: int, height: int, png_path=None, topbar_height: float | None = None) -> dict:
    """IR file -> {model, viewport, nodes: [...]}: the whole structured dump.

    Every ScreenGui pane (Task 1.12 semantics) is laid out through the real
    paint pass, so the dump's rects are the geometry the pixels came from.
    When *png_path* is given, that pass's composited PNG is written there too,
    so a caller can verify the dump against the pixels (verify_pixels).
    """
    from rhr.pipeline import load_screens, render_screens

    rect_map: dict = {}
    screens = load_screens(str(ir_path), width, height, topbar_height)
    render_screens(
        screens,
        Path(png_path) if png_path else IR_DIR / f"{Path(ir_path).stem}-layout.png",
        width,
        height,
        bg_color=(0, 0, 0, 0),
        rect_map=rect_map,
    )

    nodes: list[dict] = []
    pane_index = 0
    for obj, _, _, _name in screens:
        pane_nodes: list[dict] = []
        _walk(obj, rect_map, pane_nodes)
        for entry in pane_nodes:
            # paintOrder is the composite order across panes (bottom pane
            # first) and tree order within a pane: later paints over earlier.
            # Emitted explicitly because `nodes` is sorted by path for
            # diffability, and path order is not paint order (a pane named
            # "Under" paints before one named "Over").
            entry["paintOrder"] = pane_index
            pane_index += 1
        nodes += pane_nodes
    nodes.sort(key=lambda entry: entry["path"])

    return stamp("layout-rich", {
        "model": str(Path(ir_path).name),
        "viewport": [width, height],
        "nodes": nodes,
    })


def dump_json(dump: dict) -> str:
    """The canonical serialisation: sorted keys, so two runs diff cleanly."""
    return json.dumps(dump, indent=2, sort_keys=True)


def _parse_hex_color(text: str) -> tuple[int, int, int]:
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def _gradient_color_at(gradient: dict, t: float) -> tuple[int, int, int]:
    """The same piecewise-linear interpolation make_gradient_shader uses."""
    stops = [(t_, _parse_hex_color(c)) for t_, c in gradient["colors"]]
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return c0
            f = (t - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return stops[-1][1]


def _gradient_transparency_at(gradient: dict, t: float) -> float:
    """The same transparency-stop sampling make_gradient_shader does (0.0 = opaque)."""
    stops = gradient.get("transparency") or []
    if not stops:
        return 0.0
    stops = sorted(stops, key=lambda s: s[0])
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for (t0, v0), (t1, v1) in zip(stops, stops[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return v0
            f = (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * f
    return 0.0


def _expected_center_color(entry: dict) -> tuple[int, int, int, int, int] | None:
    """The RGBA the dump predicts at a node's rect centre, plus a tolerance.

    Returns (r, g, b, a, tolerance) or None (no fill). The engine's own maths,
    not an approximation, read out of make_gradient_shader (visuals.py): a
    gradient's colour is pre-multiplied by the background colour ((r*br)//255),
    and skia interpolates the gradient's stops in PREMULTIPLIED space, which a
    PNG stores unpremultiplied. So for a fill whose alpha is below 255 the
    prediction unpremultiplies the halfway premultiplied colour:
    straight(t) = premul(t) * 255 / alpha. Skia's fixed-point shader adds up
    to ±2 of dithering there; opaque fills (alpha 255) interpolate in straight
    space exactly and the pixel tests hold them to an exact match.
    """
    bg = entry.get("background")
    if bg is None or bg["transparency"] >= 1:
        return None
    gradient = entry.get("gradient")
    if gradient:
        br, bgc, bb = bg["color"]
        grad_trans = _gradient_transparency_at(gradient, 0.5)

        def _premul(c: tuple[int, int, int], a: int) -> tuple[float, float, float]:
            return (c[0] * a / 255, c[1] * a / 255, c[2] * a / 255)

        def _stop_color(t: float) -> tuple[int, int, int]:
            rr, gg, bb_ = _gradient_color_at(gradient, t)
            return ((rr * br) // 255, (gg * bgc) // 255, (bb_ * bb) // 255)

        # Alpha at the sample t: stops may carry their own transparency.
        alpha = round((1.0 - bg["transparency"]) * (1.0 - grad_trans) * 255)
        alpha = max(0, min(255, alpha))
        if alpha <= 0:
            return None

        def _stop_alpha(t: float) -> int:
            a = round((1.0 - bg["transparency"]) * (1.0 - _gradient_transparency_at(gradient, t)) * 255)
            return max(0, min(255, a))

        # Skia interpolates the gradient's stops in PREMULTIPLIED space and a
        # PNG stores straight alpha, so the predicted pixel unpremultiplies
        # the premultiplied colour at the sample t. The engine interpolates
        # between the two stops bracketing t, alpha included:
        #   premul(t) = lerp(premul(c0, a0), premul(c1, a1), f)
        #   alpha(t) = lerp(a0, a1, f)          straight = premul * 255 / alpha
        times = sorted({t for t, _ in gradient["colors"]})
        t_sample = 0.5
        if t_sample <= times[0]:
            premul = _premul(_stop_color(times[0]), _stop_alpha(times[0]))
            alpha = _stop_alpha(times[0])
        elif t_sample >= times[-1]:
            premul = _premul(_stop_color(times[-1]), _stop_alpha(times[-1]))
            alpha = _stop_alpha(times[-1])
        else:
            for t0, t1 in zip(times, times[1:]):
                if t0 <= t_sample <= t1:
                    a0, a1 = _stop_alpha(t0), _stop_alpha(t1)
                    p0 = _premul(_stop_color(t0), a0)
                    p1 = _premul(_stop_color(t1), a1)
                    if t1 == t0:
                        f = 0.0
                    else:
                        f = (t_sample - t0) / (t1 - t0)
                    premul = tuple(p0[i] + (p1[i] - p0[i]) * f for i in range(3))
                    alpha = round(a0 + (a1 - a0) * f)
                    break
        if alpha <= 0:
            return None
        straight = tuple(round(p * 255 / alpha) for p in premul)
        # Skia's fixed-point shader and the pixel's half-pixel sample point
        # add dithering: ±2 in premultiplied space for a transparent fill,
        # ±1 for an opaque one. Plain fills are not interpolated and are held
        # to an exact match.
        return (straight[0], straight[1], straight[2], alpha, 2 if alpha < 255 else 1)
    alpha = round((1.0 - bg["transparency"]) * 255)
    return (*bg["color"], alpha, 0)


def verify_pixels(dump: dict, png_path, paths: list[str] | None = None) -> list[tuple[str, bool, str]]:
    """Sample the PNG at each node's rect centre and compare with the dump.

    Only nodes with an opaque resolved fill are checked: a transparent node
    predicts no colour, so asserting against the backdrop would be false
    agreement. A node whose rect centre a later-painted node covers is SKIPPED
    with "skipped: occluded by <path>" rather than failed — the covering pane
    really is what those pixels show, so the comparison would lie about the
    dump. Paint order is each node's `paintOrder` (build_dump emits it: pane
 composite order, then tree order), not path order. Results are returned
 in paint order; the `nodes` list itself stays sorted by path so two
 builds diff cleanly.
    """
    from PIL import Image

    def _covers(later: dict, earlier: dict) -> bool:
        """later's opaque fill covers earlier's rect centre (same stacking surface)."""
        bg = later.get("background")
        if not bg or bg.get("transparency", 1.0) >= 1.0:
            return False
        r, e = later["rect"], earlier["rect"]
        cx = e["x"] + e["w"] / 2
        cy = e["y"] + e["h"] / 2
        return (
            r["x"] <= cx <= r["x"] + r["w"]
            and r["y"] <= cy <= r["y"] + r["h"]
        )

    wanted = set(paths) if paths is not None else None
    nodes = sorted(dump["nodes"], key=lambda e: e.get("paintOrder", 0))
    results = []
    with Image.open(png_path) as img:
        rgba = img.convert("RGBA")
        for index, entry in enumerate(nodes):
            if wanted is not None and entry["path"] not in wanted:
                continue
            expected = _expected_center_color(entry)
            if expected is None:
                continue
            tolerance = expected[4]
            expected_rgba = (expected[0], expected[1], expected[2], expected[3])
            rect = entry["rect"]
            cx = int(rect["x"] + rect["w"] / 2)
            cy = int(rect["y"] + rect["h"] / 2)
            if not (0 <= cx < rgba.width and 0 <= cy < rgba.height):
                results.append((entry["path"], False, f"centre ({cx},{cy}) is outside the canvas"))
                continue
            # Occlusion: a later node on the SAME pane stack that covers this
            # centre wins the pixels. Pane membership is a path prefix at the
            # dump's top level: panes are emitted bottom-first, and within a
            # pane the subtree keeps tree order. The honest rule: any node
            # after this one in dump order whose opaque rect covers the centre
            # occludes it.
            occluder = next(
                (
                    later["path"]
                    for later in nodes[index + 1 :]
                    if later["path"] != entry["path"] and _covers(later, entry)
                ),
                None,
            )
            if occluder is not None:
                results.append((entry["path"], True, f"skipped: occluded by {occluder}"))
                continue
            got = rgba.getpixel((cx, cy))
            if tolerance:
                ok = all(abs(a - b) <= tolerance for a, b in zip(got[:3], expected_rgba[:3])) and got[3] == expected_rgba[3]
            else:
                ok = got == expected_rgba
            results.append((entry["path"], ok, f"expected {expected_rgba} (±{tolerance}), got {got}"))
    return results
