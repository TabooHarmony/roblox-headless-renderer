"""The checks that let a build fail: eight model smells, one dump, no opinions.

Every check reads the Task 2.1 dump (build_dump) and nothing else — the same
converted objects and rect map the paint pass used, never a re-derived
geometry. Each exists because a real model had the problem; each reports the
least severity that is honest:

  1. text-wider-than-box    warning — TextWrapped makes the overflow benign
                            (the text breaks instead of spilling), so it can
                            be a deliberate look. Width is estimated with the
                            engine's own run splitter and font metrics
                            (_split_font_runs / skia measureText via
                            _measure_mixed on a bundled Montserrat), not a
                            char-count guess.
  2. zero-size-grid-cell    error   — a cell resolved to <= 0 px collapses to
                            nothing; nothing a designer does with a 0x0 cell
                            is intentional. Honest limit (documented in
                            layout_dump._grid_cell_px): a UIPadding on the
                            holder shrinks the engine's actual reference, which
                            the dump's rect does not show, so only the model's
                            own px is checked.
  3. child-outside-clip     warning — content entirely outside the parent rect
                            is very often intentional scroll or canvas
                            content, and only flagged when the parent clips.
  4. text-size-below-2px    error   — a font under 2 px is unreadable at any
                            zoom; no deliberate render wants it.
  5. invisible-content      warning — a visible node carrying text or an
                            opaque-design background at full transparency is
                            usually a leftover, but a template scaffold is a
                            legitimate authoring choice.
  6. duplicate-zindex       warning — overlapping siblings with equal ZIndex
                            leave the paint order to tree luck; that ambiguity
                            is legal, so it warns. Sibling identity is the
                            dump's paintOrder, not the path (paths collide).
  7. text-truncated         warning — TextTruncate is a deliberate authoring
                            choice; flagged only when the text actually
                            overflows the box (same width test as check 1).
  8. max-visible-graphemes  warning, NOT an error — per Roblox docs the
                            layout is computed as if every grapheme were
                            visible (it is a typewriter window over the same
                            layout), so nothing is broken; the check only
                            surfaces an effect a reader of the dump might not
                            know is on.

Output shape: {"model": ..., "findings": [{"check", "severity", "path(s)",
"detail"}...]}, sorted by (severity, path, check) — severity error first — with
no set or dict iteration anywhere, so two runs are byte-identical.
"""

from __future__ import annotations

from rhr.schema import stamp

import sys
from pathlib import Path

from rhr.paths import IR_DIR


TRUNCATE_OVERFLOW_MODES = {"AtEnd", "SplitWord"}
# _load_typeface's own ladder ends at Montserrat (bundled with the engine), so
# a plain model without a Font property measures with exactly this face.
_DEFAULT_FONT_FILE = "Montserrat-Regular.ttf"


def _resolve_text(entry: dict) -> dict | None:
    """The dump's text dict, or None (entry carries no text)."""
    text = entry.get("text")
    return text if isinstance(text, dict) else None


def _measure_text_width(content: str, text: dict) -> float:
    """Estimated width in px: the engine's run splitter, a bundled font.

    Reuses the vendored engine's own mixed-run measurement (text_runs.py:
    _split_font_runs picks the face per char, _measure_run_text sums skia's
    advances) on the engine's default bundled face. Roblox renders with its own
    licensed faces, so this is an estimate with a known face, not a char count.
    """
    import skia

    from rhr.pipeline import FONTS_DIR

    from ui_engine.text_fonts import _typeface_from_file

    typeface = _typeface_from_file(str(FONTS_DIR / _DEFAULT_FONT_FILE))
    if typeface is None:
        typeface = skia.Typeface()  # skia's default face; better than guessing by chars
    font = skia.Font(typeface, float(text.get("size", 14)))
    from ui_engine.text_runs import _measure_mixed

    return _measure_mixed(content, font, None, ())


def _overflows(entry: dict) -> bool:
    """The same width test for checks 1 and 7: unwrapped text wider than the rect."""
    text = _resolve_text(entry)
    if text is None or text.get("wrapped"):
        return False
    content = text.get("content") or ""
    if not content.strip():
        return False
    width = _measure_text_width(content, text)
    return width > entry["rect"]["w"]


def check_text_wider_than_box(nodes: list[dict]) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _resolve_text(entry)
        if text is None:
            continue
        if _overflows(entry):
            findings.append(
                {
                    "check": "text-wider-than-box",
                    "severity": "warning",
                    "paths": [entry["path"]],
                    "detail": (
                        f"text estimated {_measure_text_width(text.get('content') or '', text):.0f}px wide "
                        f"in a {entry['rect']['w']:.0f}px box with TextWrapped off"
                    ),
                }
            )
    return findings


def check_zero_size_grid_cell(nodes: list[dict]) -> list[dict]:
    findings = []
    for entry in nodes:
        cell = entry.get("gridCellPx")
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            continue
        w, h = float(cell[0]), float(cell[1])
        if w <= 0 or h <= 0:
            findings.append(
                {
                    "check": "zero-size-grid-cell",
                    "severity": "error",
                    "paths": [entry["path"]],
                    "detail": f"grid CellSize resolves to {w:.0f}x{h:.0f}px: cells collapse to nothing",
                }
            )
    return findings


def check_child_outside_clip(nodes: list[dict]) -> list[dict]:
    """A child entirely outside the parent's rect, when the parent clips."""
    findings = []
    by_path = {entry["path"]: entry for entry in nodes}
    for entry in nodes:
        if not entry.get("clipsDescendants"):
            continue
        parent = entry["rect"]
        for child in nodes:
            if child is entry:
                continue
            # A direct child: its path extends this parent's path by one segment.
            if not child["path"].startswith(entry["path"] + "/"):
                continue
            if "/" in child["path"][len(entry["path"]) + 1 :]:
                continue
            if by_path.get(child["path"]) is not child:
                continue
            rect = child["rect"]
            if (
                rect["x"] + rect["w"] <= parent["x"]
                or rect["x"] >= parent["x"] + parent["w"]
                or rect["y"] + rect["h"] <= parent["y"]
                or rect["y"] >= parent["y"] + parent["h"]
            ):
                findings.append(
                    {
                        "check": "child-outside-clip",
                        "severity": "warning",
                        "paths": [child["path"]],
                        "detail": (
                            f"rect ({rect['x']:.0f},{rect['y']:.0f} {rect['w']:.0f}x{rect['h']:.0f}) is entirely "
                            f"outside clipping parent {entry['path']} "
                            f"({parent['x']:.0f},{parent['y']:.0f} {parent['w']:.0f}x{parent['h']:.0f})"
                        ),
                    }
                )
    return findings


def check_text_size_below_2px(nodes: list[dict]) -> list[dict]:
    """A font under 2 px is unreadable at any zoom; no deliberate render wants it.

    Skipped for TextScaled labels: their specified TextSize is ignored by the
    engine (the box drives the size, Task 1.10), so a scaled label carrying
    TextSize 1 is a authoring leftover in the FILE, not in the RENDER — RTL2's
    shop labels all carry TextSize 1 + TextScaled and render at 20+ px. The
    model's real rendered size is a draw-time fact; flagging the specified
    number would be a false alarm on every scaled label in real UI.
    """
    findings = []
    for entry in nodes:
        text = _resolve_text(entry)
        if text is None or text.get("scaled"):
            continue
        if float(text.get("size", 14)) < 2:
            findings.append(
                {
                    "check": "text-size-below-2px",
                    "severity": "error",
                    "paths": [entry["path"]],
                    "detail": f"TextSize {text.get('size')} is unreadable",
                }
            )
    return findings


def check_invisible_content(nodes: list[dict]) -> list[dict]:
    """A visible node that paints nothing and whose subtree paints nothing.

    "Paints nothing" is about pixels, not one property: a label with a
    transparent background and opaque text is the most common Roblox pattern
    there is, and a Frame holding visible children is a layout scaffold —
    neither is a finding. An ImageLabel's image paints even when the dump
    carries no image field (the check cannot see assets), so any node the IR
    gave an Image is assumed to paint; the honest default is to stay silent
    rather than flag real UI as dead. The check fires only for a genuinely
    dead branch: the node's every channel transparent (text at 100% or
    absent, background at 100% or unset) AND no descendant that could paint
    either. The engine's converter-default grey counts as no background: the
    model did not set one.
    """
    findings = []
    for entry in nodes:
        if not entry.get("visible"):
            continue
        text = _resolve_text(entry)
        has_text = text is not None and bool((text.get("content") or "").strip())
        bg = entry.get("background")
        # An explicit background: the model set BackgroundColor3/Transparency
        # (the dump's default grey means the converter invented it).
        has_bg = bg is not None and list(bg.get("color", [])) != [163, 162, 165]
        text_trans = float(text.get("transparency", 0.0)) if text else 1.0
        bg_trans = float(bg.get("transparency", 1.0)) if bg else 1.0
        text_could_show = has_text and text_trans < 1.0
        bg_could_show = has_bg and bg_trans < 1.0
        if text_could_show or bg_could_show:
            continue
        subtree_paints = any(
            other is not entry
            and other["path"].startswith(entry["path"] + "/")
            and _could_paint(other)
            for other in nodes
        )
        if subtree_paints:
            continue
        if has_text:
            findings.append(
                {
                    "check": "invisible-content",
                    "severity": "warning",
                    "paths": [entry["path"]],
                    "detail": f"text at {text_trans:.0%} transparency: '"
                    + (text.get("content") or "")[:40]
                    + "'",
                }
            )
        elif has_bg:
            findings.append(
                {
                    "check": "invisible-content",
                    "severity": "warning",
                    "paths": [entry["path"]],
                    "detail": f"background at {bg_trans:.0%} transparency paints nothing",
                }
            )
    return findings


def _could_paint(entry: dict) -> bool:
    """The node itself could put a pixel on the canvas."""
    text = _resolve_text(entry)
    if text is not None and (text.get("content") or "").strip():
        if float(text.get("transparency", 0.0)) < 1.0:
            return True
    bg = entry.get("background")
    if bg is not None and list(bg.get("color", [])) != [163, 162, 165]:
        if float(bg.get("transparency", 1.0)) < 1.0:
            return True
    return False


def check_invisible_content_with_ir(nodes: list[dict], image_paths: set[str] | None = None) -> list[dict]:
    """check_invisible_content, minus nodes the IR says carry an Image.

    Library twin of check_model's IR-aware filtering, for callers that hold
    the dump and the IR separately.
    """
    if not image_paths:
        return check_invisible_content(nodes)

    def _has_image(entry: dict) -> bool:
        return any(
            p == entry["path"] or p.startswith(entry["path"] + "/") for p in image_paths
        )

    return [
        f
        for f in check_invisible_content(nodes)
        if not _has_image({"path": f["paths"][0]})
    ]


def check_duplicate_zindex(nodes: list[dict]) -> list[dict]:
    """Overlapping siblings with equal ZIndex: ambiguous paint order.

    Siblings are entries whose paths share a parent prefix. Identity within a
    pair is each entry's paintOrder (build_dump's composite walk order), not
    the path: two siblings with the same Name collide in the path space (the
    engine's rect map overwrites by key), but every dump entry still carries
    its own paintOrder, so colliding siblings stay two findings, not one.
    Reporting pairs, not clusters: a cluster of n expands to every overlapping
    pair, which is what a fix touches.
    """
    findings = []
    order = sorted(nodes, key=lambda entry: entry.get("paintOrder", 0))
    seen: set[tuple[int, int]] = set()
    for i, first in enumerate(order):
        for second in order[i + 1 :]:
            if first["path"] == second["path"]:
                # Two entries on one path: same-Name siblings the rect map's
                # key overwrote. They are siblings by construction (one path,
                # one parent), kept apart by paintOrder.
                parent = first["path"].rsplit("/", 1)[0] if "/" in first["path"] else ""
                if not parent:
                    continue
            else:
                parent = first["path"].rsplit("/", 1)[0] if "/" in first["path"] else ""
                second_parent = second["path"].rsplit("/", 1)[0] if "/" in second["path"] else ""
                if parent != second_parent or not parent:
                    continue
            if first["zIndex"] != second["zIndex"]:
                continue
            a, b = first["rect"], second["rect"]
            overlap_x = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            overlap_y = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            key = (first.get("paintOrder", 0), second.get("paintOrder", 0))
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "check": "duplicate-zindex",
                    "severity": "warning",
                    "paths": sorted([first["path"], second["path"]]),
                    "detail": (
                        f"overlapping rects both ZIndex {first['zIndex']} "
                        f"(paintOrder {key[0]} and {key[1]}): paint order is tree luck"
                    ),
                }
            )
    return findings


def check_text_truncated(nodes: list[dict]) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _resolve_text(entry)
        if text is None:
            continue
        mode = text.get("truncate")
        if mode not in TRUNCATE_OVERFLOW_MODES:
            continue
        if _overflows(entry):
            findings.append(
                {
                    "check": "text-truncated",
                    "severity": "warning",
                    "paths": [entry["path"]],
                    "detail": (
                        f"TextTruncate {mode} trims text wider than the {entry['rect']['w']:.0f}px box"
                    ),
                }
            )
    return findings


def check_max_visible_graphemes(nodes: list[dict]) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _resolve_text(entry)
        if text is None:
            continue
        window = text.get("maxVisibleGraphemes")
        if window is None:
            continue
        content = text.get("content") or ""
        if window < len(content):
            findings.append(
                {
                    "check": "max-visible-graphemes",
                    "severity": "warning",
                    "paths": [entry["path"]],
                    "detail": (
                        f"typewriter window shows {window} of {len(content)} graphemes "
                        "(layout still computes all of them)"
                    ),
                }
            )
    return findings


CHECKS = [
    check_text_wider_than_box,
    check_zero_size_grid_cell,
    check_child_outside_clip,
    check_text_size_below_2px,
    check_invisible_content,
    check_duplicate_zindex,
    check_text_truncated,
    check_max_visible_graphemes,
]


def run_checks(dump: dict) -> list[dict]:
    """The dump's findings, sorted by (severity, path, check) for determinism."""
    nodes = dump.get("nodes") or []
    findings: list[dict] = []
    for check in CHECKS:
        findings += check(nodes)
    findings.sort(key=lambda f: (f["severity"] != "error", f["paths"][0], f["check"]))
    return findings


def check_model(ir_path, width: int, height: int, topbar_height: float | None = None) -> dict:
    """build_dump + run_checks: the wrapper a caller (the CLI) uses.

    Accepts a Roblox model (IR emitted first, exactly as build_dump's callers
    do) or an IR .json. `rhr check model.rbxm` and `rhr check ir.json` are
    both real, matching render/layout.
    """
    from rhr.ir import emit_ir, load_ir
    from rhr.layout_dump import build_dump

    ir_path = Path(ir_path)
    if ir_path.suffix != ".json":
        ir_path = emit_ir(ir_path, IR_DIR / f"{ir_path.stem}.json")
    dump = build_dump(ir_path, width, height, topbar_height=topbar_height)
    findings = run_checks(dump)
    # The dump cannot see image assets; the IR can. An ImageLabel whose
    # background is transparent paints its Image, so the invisible-content
    # check stays silent about any path whose IR subtree carries an Image.
    image_paths = _image_paths(load_ir(ir_path))
    if image_paths:
        findings = [
            f
            for f in findings
            if f["check"] != "invisible-content"
            or not any(
                p == f["paths"][0] or p.startswith(f["paths"][0] + "/") or f["paths"][0].startswith(p + "/")
                for p in image_paths
            )
        ]
        findings.sort(key=lambda f: (f["severity"] != "error", f["paths"][0], f["check"]))
    return stamp("check", {"model": dump["model"], "findings": findings})


def _image_paths(ir: dict) -> set[str]:
    """Every node path whose IR subtree carries an Image/ImageContent property."""
    out: set[str] = set()

    def walk(node: dict, prefix: str) -> None:
        here = f"{prefix}/{node['name']}" if prefix else node["name"]
        props = node.get("props") or {}
        if props.get("Image") or props.get("ImageContent"):
            out.add(here)
        for child in node.get("children") or []:
            walk(child, here)

    for root in ir.get("roots") or []:
        walk(root, "")
    return out


def findings_json(result: dict) -> str:
    """The canonical serialisation: sorted keys, deterministic."""
    import json

    return json.dumps(result, indent=2, sort_keys=True)
