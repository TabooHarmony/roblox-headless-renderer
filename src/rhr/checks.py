"""The checks that let a build fail: UI mistakes found from one layout dump.

Every check reads the rich layout dump (rhr.layout_dump.build_dump) and nothing else:
the same objects and rects the paint pass used, and for text what the engine laid out
(`text.bounds` in `text.box`, the size it drew at). A check never measures again with
other rules than the drawing did; that is how half of the old text warnings were
wrong (a TextScaled label measured at its nominal size, another font's widths).

Severities, least honest one wins:

  error    a real mistake nothing intends: fails the build (`rhr check` exits 1).
  warning  very likely a mistake a player would see; worth a look.
  info     a pattern that is often intended (layout holders, text a script fades in,
           equal ZIndex siblings); not printed unless `--min-severity info`.

The checks, by id (the ids are part of the interface):

  text-wider-than-box    warning  unwrapped text wider than its box (it spills out)
                                  (the text checks skip text in a font RHR lacks, and
                                  anything collapsed to nothing, as a tween starts)
  text-taller-than-box   warning  wrapped text with more lines than its box holds
  text-truncated         warning  TextTruncate cut the text short
  text-size-below-2px    error    a font under 2 px
  low-contrast           warning  text hardly distinguishable from its background
                                  (info between 1.5:1 and 3:1)
  off-screen             warning  a button entirely outside the screen (info for
                                  a panel: games park panels there to slide in)
  partly-off-screen      warning  a button, part of which is outside the screen
  small-target           warning  a button under 24 px on a side
  button-blocked         error    a button whose clicks an Active element in a
                                  ScreenGui above swallows (even a transparent one):
                                  it cannot be clicked there (rules measured in Studio,
                                  rhr.hitmap)
  button-covered         info     a button under another button at its centre
  image-missing          warning  an image Roblox refused the last time RHR asked for
                                  it (`rhr check` never downloads; `rhr ui` does)
  zero-size-grid-cell    error    a UIGridLayout cell that resolves to nothing
  child-outside-clip     info     content entirely outside a clipping parent
  invisible-content      info     a visible element that paints nothing
  duplicate-zindex       info     overlapping siblings with equal ZIndex
  max-visible-graphemes  info     a typewriter window over the text

Leaving findings out: `--ignore <check>`; `--min-severity`; `--baseline old.json`
(only findings not in an earlier `rhr check` output: "did my edit add a problem?");
and in the file, a string attribute `RhrIgnore` on any instance, "all" or check ids
separated by commas, for that instance and everything in it.

Output shape: {"model": ..., "findings": [{"check", "severity", "paths",
"detail"}...]}, sorted by (severity, path, check), with no set or dict iteration, so
two runs are byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from rhr.schema import stamp

SEVERITIES = ("error", "warning", "info")
_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}
TRUNCATE_OVERFLOW_MODES = {"AtEnd", "SplitWord"}
BUTTON_CLASSES = {"TextButton", "ImageButton", "TextBox"}
# A comfortable pointer target; touch needs more (Phase 2: --device).
MIN_TARGET_PX = 24
# The engine's grey for a background the model did not set.
_DEFAULT_GREY = [163, 162, 165]
# Rounding slack: a box the text fills to the pixel is not an overflow.
_SLACK_PX = 1.0


def _text(entry: dict) -> dict | None:
    text = entry.get("text")
    return text if isinstance(text, dict) and (text.get("content") or "").strip() else None


def _measured(entry: dict, ctx: dict) -> dict | None:
    """The entry's text when its laid-out size can be trusted: drawn in the face the
    model asks for (not an uploaded font RHR could not load, whose words may be one
    icon glyph in Roblox) and not inside something collapsed to nothing."""
    text = _text(entry)
    if text is None or "bounds" not in text or text.get("fontSubstituted") or _collapsed(entry, ctx):
        return None
    return text


def _collapsed(entry: dict, ctx: dict) -> bool:
    """Under 2 px on a side, or inside something that is: sized to nothing on purpose
    (a menu a tween grows open), not a UI to judge."""
    memo = ctx.setdefault("collapsed", {})
    path = entry["path"]
    if path not in memo:
        rect = entry["rect"]
        parent = ctx["by_path"].get(path.rpartition("/")[0])
        memo[path] = min(rect["w"], rect["h"]) < 2 or (parent is not None and _collapsed(parent, ctx))
    return memo[path]


def _finding(check: str, severity: str, entry: dict, detail: str) -> dict:
    return {"check": check, "severity": severity, "paths": [entry["path"]], "detail": detail}


def check_text_wider_than_box(nodes: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _measured(entry, ctx)
        if (text is None or text.get("wrapped") or text.get("scaled") or text.get("truncated")
                or not entry.get("visible")):
            continue
        width, box = text["bounds"][0], text["box"][0]
        if width > box + _SLACK_PX:
            findings.append(_finding(
                "text-wider-than-box", "warning", entry,
                f"text is {width:.0f}px wide in a {box:.0f}px box with TextWrapped off: it spills out"))
    return findings


def check_text_taller_than_box(nodes: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _measured(entry, ctx)
        if text is None or not (text.get("wrapped") or text.get("scaled")):
            continue
        if not entry.get("visible"):
            continue
        height, box = text["bounds"][1], text["box"][1]
        if height > box + _SLACK_PX:
            lines = text.get("lines", 1)
            findings.append(_finding(
                "text-taller-than-box", "warning", entry,
                f"text wraps to {lines} line(s), {height:.0f}px tall, in a {box:.0f}px box: lines spill out "
                f"(at TextSize {text.get('drawnSize', text.get('size'))})"))
    return findings


def check_text_truncated(nodes: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for entry in nodes:
        text = _text(entry)
        if text is None or not text.get("truncated") or _collapsed(entry, ctx):
            continue
        findings.append(_finding(
            "text-truncated", "warning", entry,
            f"TextTruncate {text.get('truncate')} cuts the text short in the {text['box'][0]:.0f}px box"))
    return findings


def check_text_size_below_2px(nodes: list[dict], ctx: dict) -> list[dict]:
    """A font under 2 px is unreadable at any zoom. A TextScaled label's TextSize is
    ignored by the engine (the box drives the size), so its drawn size is used."""
    findings = []
    for entry in nodes:
        text = _text(entry)
        if text is None or _collapsed(entry, ctx):
            continue
        size = float(text.get("drawnSize", text.get("size", 14))) if text.get("scaled") else float(text.get("size", 14))
        if size < 2:
            findings.append(_finding("text-size-below-2px", "error", entry, f"text drawn at {size:g}px is unreadable"))
    return findings


def _luminance(color) -> float:
    def channel(value: float) -> float:
        c = float(value) / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in list(color)[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_low_contrast(nodes: list[dict], ctx: dict) -> list[dict]:
    """Text against what is painted right under it: its own background, else the last
    element painted before it that covers the text's centre (its frame, or a sibling
    image laid behind it). Silent when that is unknown: an image, a gradient, a colour
    the model did not set, or text with an outline."""
    images = ctx["image_paths"]
    order = sorted(nodes, key=lambda e: e.get("paintOrder", 0))
    index = {id(entry): i for i, entry in enumerate(order)}
    findings = []
    for entry in nodes:
        text = _text(entry)
        if (text is None or not entry.get("visible") or float(text.get("transparency", 0)) > 0.5
                or _collapsed(entry, ctx)):
            continue
        if entry.get("gradient") or any(float(s.get("transparency", 0)) < 1 for s in entry.get("strokes") or []):
            continue
        rect = entry["rect"]
        cx, cy = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
        behind = _painted_under(entry, cx, cy, order, index[id(entry)], images, ctx)
        if behind is None:
            continue
        ratio = contrast_ratio(text.get("color", [0, 0, 0]), behind)
        if ratio < 3:
            findings.append(_finding(
                "low-contrast", "warning" if ratio < 1.5 else "info", entry,
                f"text contrast {ratio:.2f}:1 against its background (3:1 is the least for large text)"))
    return findings


def _painted_under(entry: dict, cx: float, cy: float, order: list[dict], start: int, images: set[str],
                   ctx: dict) -> list | None:
    """The solid colour under a text's centre, or None when it is not a known colour."""
    for i in range(start, max(-1, start - 4000), -1):
        other = order[i]
        if other is not entry:
            r = other["rect"]
            if (not other.get("visible") or _collapsed(other, ctx)
                    or not (r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"])):
                continue
            if other["path"] in images:
                return None
        bg = other.get("background")
        if other.get("gradient") and bg and float(bg.get("transparency", 1)) < 1:
            return None
        if bg and float(bg.get("transparency", 1)) < 0.05:
            return list(bg["color"]) if list(bg.get("color", [])) != _DEFAULT_GREY else None
    return None


def _clipped(entry: dict, by_path: dict) -> bool:
    """Whether something above `entry` clips it (ScrollingFrame, ClipsDescendants):
    content outside the screen there is hidden or scrolled to, not lost."""
    path = entry["path"].rpartition("/")[0]
    while path:
        holder = by_path.get(path)
        if holder is not None and (holder.get("clipsDescendants") or holder.get("class") == "ScrollingFrame"):
            return True
        path = path.rpartition("/")[0]
    return False


def check_off_screen(nodes: list[dict], ctx: dict) -> list[dict]:
    width, height = ctx["viewport"]
    by_path = ctx["by_path"]

    def outside(rect: dict) -> bool:
        return (rect["x"] + rect["w"] <= 0 or rect["y"] + rect["h"] <= 0
                or rect["x"] >= width or rect["y"] >= height)

    findings = []
    for entry in nodes:
        rect = entry["rect"]
        if not entry.get("visible") or _collapsed(entry, ctx) or _clipped(entry, by_path):
            continue
        if outside(rect):
            parent = by_path.get(entry["path"].rpartition("/")[0])
            if parent is not None and parent.get("visible") and outside(parent["rect"]):
                continue  # reported once, at the outermost element
            # A panel parked outside the screen is how many games slide one in: a
            # note. A button out there on its own is more likely a mistake.
            button = entry.get("class") in BUTTON_CLASSES
            findings.append(_finding(
                "off-screen", "warning" if button else "info", entry,
                f"entirely outside the {width}x{height} screen at ({rect['x']:.0f},{rect['y']:.0f}): "
                "no player sees it (a start position for a tween, or a mistake)"))
        elif entry.get("class") in BUTTON_CLASSES:
            seen_w = min(rect["x"] + rect["w"], width) - max(rect["x"], 0)
            seen_h = min(rect["y"] + rect["h"], height) - max(rect["y"], 0)
            shown = (seen_w * seen_h) / (rect["w"] * rect["h"])
            if shown < 0.99:
                findings.append(_finding(
                    "partly-off-screen", "warning", entry,
                    f"{(1 - shown):.0%} of this {entry['class']} is outside the {width}x{height} screen"))
    return findings


def check_small_target(nodes: list[dict], ctx: dict) -> list[dict]:
    findings = []
    for entry in nodes:
        rect = entry["rect"]
        if entry.get("class") not in BUTTON_CLASSES or not entry.get("visible") or _collapsed(entry, ctx):
            continue
        if 0 < min(rect["w"], rect["h"]) < MIN_TARGET_PX:
            findings.append(_finding(
                "small-target", "warning", entry,
                f"a {rect['w']:.0f}x{rect['h']:.0f}px {entry['class']} is hard to hit "
                f"(at least {MIN_TARGET_PX}px with a mouse, more on touch)"))
    return findings


def check_image_missing(nodes: list[dict], ctx: dict) -> list[dict]:
    missing = ctx.get("missing_images") or {}
    findings = []
    for entry in nodes:
        known = missing.get(entry["path"])
        if known is None or not entry.get("visible"):
            continue
        uri, why = known
        findings.append(_finding("image-missing", "warning", entry,
                                 f"{uri} could not be downloaded ({why}): it draws as nothing"))
    return findings


def check_zero_size_grid_cell(nodes: list[dict], _ctx: dict) -> list[dict]:
    """A UIGridLayout cell resolved to <= 0 px collapses its items to nothing. (A
    UIPadding on the holder shrinks the engine's reference, which the dump's rect does
    not show, so only the model's own px is checked; layout_dump._grid_cell_px.)"""
    findings = []
    for entry in nodes:
        cell = entry.get("gridCellPx")
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            continue
        w, h = float(cell[0]), float(cell[1])
        if w <= 0 or h <= 0:
            findings.append(_finding("zero-size-grid-cell", "error", entry,
                                     f"grid CellSize resolves to {w:.0f}x{h:.0f}px: cells collapse to nothing"))
    return findings


def check_child_outside_clip(nodes: list[dict], ctx: dict) -> list[dict]:
    """A child entirely outside a parent that clips (not a ScrollingFrame, whose
    content outside its window is scrolled to): not seen now. Often intended (a
    ticker scrolling through a banner, a page sliding in), so a note."""
    by_path = ctx["by_path"]
    findings = []
    for child in nodes:
        parent = by_path.get(child["path"].rpartition("/")[0])
        if parent is None or not parent.get("clipsDescendants") or parent.get("class") == "ScrollingFrame":
            continue
        if by_path.get(child["path"]) is not child or not child.get("visible"):
            continue
        rect, box = child["rect"], parent["rect"]
        if (rect["x"] + rect["w"] <= box["x"] or rect["x"] >= box["x"] + box["w"]
                or rect["y"] + rect["h"] <= box["y"] or rect["y"] >= box["y"] + box["h"]):
            findings.append(_finding(
                "child-outside-clip", "info", child,
                f"rect ({rect['x']:.0f},{rect['y']:.0f} {rect['w']:.0f}x{rect['h']:.0f}) is entirely outside "
                f"clipping parent {parent['path']} "
                f"({box['x']:.0f},{box['y']:.0f} {box['w']:.0f}x{box['h']:.0f})"))
    return findings


def _could_paint(entry: dict) -> bool:
    """The node itself could put a pixel on the canvas."""
    text = _text(entry)
    if text is not None and float(text.get("transparency", 0.0)) < 1.0:
        return True
    bg = entry.get("background")
    return bool(bg and list(bg.get("color", [])) != _DEFAULT_GREY and float(bg.get("transparency", 1.0)) < 1.0)


def check_invisible_content(nodes: list[dict], ctx: dict) -> list[dict]:
    """A visible element that paints nothing, nor does anything in it: a leftover, or
    (often) a holder or text a script fades in. Anything with an image is assumed to
    paint (the dump does not see images)."""
    images = ctx["image_paths"]
    painting: set[str] = set()
    for entry in nodes:
        if _could_paint(entry) or entry["path"] in images:
            path = entry["path"]
            while path and path not in painting:
                painting.add(path)
                path = path.rpartition("/")[0]
    findings = []
    for entry in nodes:
        if not entry.get("visible") or entry["path"] in painting:
            continue
        if any(p.startswith(entry["path"] + "/") for p in images):
            continue
        text = entry.get("text") if isinstance(entry.get("text"), dict) else None
        bg = entry.get("background")
        if text and (text.get("content") or "").strip():
            findings.append(_finding(
                "invisible-content", "info", entry,
                f"text at {float(text.get('transparency', 0)):.0%} transparency: '{(text.get('content') or '')[:40]}'"))
        elif bg is not None and list(bg.get("color", [])) != _DEFAULT_GREY:
            findings.append(_finding(
                "invisible-content", "info", entry,
                f"background at {float(bg.get('transparency', 1)):.0%} transparency paints nothing"))
    return findings


def check_duplicate_zindex(nodes: list[dict], _ctx: dict) -> list[dict]:
    """Overlapping siblings with equal ZIndex: which is on top follows their order in
    the file. Legal and usually fine; worth knowing when one must be on top. Pairs are
    kept apart by paintOrder (same-named siblings share a path)."""
    siblings: dict[str, list[dict]] = {}
    for entry in sorted(nodes, key=lambda e: e.get("paintOrder", 0)):
        parent = entry["path"].rpartition("/")[0]
        if parent:
            siblings.setdefault(parent, []).append(entry)
    findings = []
    for group in siblings.values():
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if first["zIndex"] != second["zIndex"]:
                    continue
                a, b = first["rect"], second["rect"]
                if (min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) <= 0
                        or min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]) <= 0):
                    continue
                findings.append({
                    "check": "duplicate-zindex", "severity": "info",
                    "paths": sorted([first["path"], second["path"]]),
                    "detail": (f"overlapping rects both ZIndex {first['zIndex']} (paintOrder "
                               f"{first.get('paintOrder', 0)} and {second.get('paintOrder', 0)}): "
                               "the later one in the file is on top"),
                })
    return findings


def check_max_visible_graphemes(nodes: list[dict], _ctx: dict) -> list[dict]:
    """A typewriter window: layout is computed as if every grapheme were visible."""
    findings = []
    for entry in nodes:
        text = _text(entry)
        window = text.get("maxVisibleGraphemes") if text else None
        if window is not None and window < len(text.get("content") or ""):
            findings.append(_finding(
                "max-visible-graphemes", "info", entry,
                f"typewriter window shows {window} of {len(text['content'])} graphemes "
                "(layout still computes all of them)"))
    return findings


CHECKS = [
    check_text_wider_than_box,
    check_text_taller_than_box,
    check_text_truncated,
    check_text_size_below_2px,
    check_low_contrast,
    check_off_screen,
    check_small_target,
    check_image_missing,
    check_zero_size_grid_cell,
    check_child_outside_clip,
    check_invisible_content,
    check_duplicate_zindex,
    check_max_visible_graphemes,
]
CHECK_IDS = (
    "text-wider-than-box", "text-taller-than-box", "text-truncated", "text-size-below-2px", "low-contrast",
    "off-screen", "partly-off-screen", "small-target", "button-blocked", "button-covered", "image-missing", "zero-size-grid-cell", "child-outside-clip",
    "invisible-content", "duplicate-zindex", "max-visible-graphemes",
)


def _sort(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: (_RANK[f["severity"]], f["paths"][0], f["check"], f["detail"]))


def run_checks(dump: dict, image_paths: set[str] | None = None,
               missing_images: dict[str, tuple[str, str]] | None = None) -> list[dict]:
    """Every finding in the dump, sorted by (severity, path, check). `missing_images`:
    path -> (uri, why) for images known to be unavailable."""
    nodes = dump.get("nodes") or []
    ctx = {
        "viewport": tuple(dump.get("viewport") or (0, 0)),
        "by_path": {entry["path"]: entry for entry in nodes},
        "image_paths": image_paths or set(),
        "missing_images": missing_images or {},
    }
    findings: list[dict] = []
    for check in CHECKS:
        findings += check(nodes, ctx)
    return _sort(findings)


def check_model(ir_path, width: int, height: int, topbar_height: float | None = None, *,
                min_severity: str = "warning", ignore: tuple[str, ...] = (), baseline: dict | None = None) -> dict:
    """The CLI's `rhr check`: the dump, its findings, and the ones left out.

    Returns the rhr.check/1 document plus `_left_out`: how many findings each rule
    left out (for the summary on stderr), popped by the caller.
    """
    from rhr.ir import cached_ir, load_ir
    from rhr.layout_dump import build_dump

    ir_path = Path(ir_path)
    if ir_path.suffix != ".json":
        ir_path = cached_ir(ir_path)
    dump = build_dump(ir_path, width, height, topbar_height=topbar_height)
    ir = load_ir(ir_path)
    findings = run_checks(dump, _image_paths(ir), _missing_images(ir))
    findings = _sort(findings + _blocked_buttons(ir_path, width, height, topbar_height, dump))

    left_out = {"severity": 0, "ignored": 0, "attribute": 0, "baseline": 0}
    suppressed = _suppressed(ir)
    known = {(f["check"], tuple(f["paths"])) for f in (baseline or {}).get("findings") or []}
    kept = []
    for finding in findings:
        if _RANK[finding["severity"]] > _RANK[min_severity]:
            left_out["severity"] += 1
        elif finding["check"] in ignore:
            left_out["ignored"] += 1
        elif _is_suppressed(finding, suppressed):
            left_out["attribute"] += 1
        elif (finding["check"], tuple(finding["paths"])) in known:
            left_out["baseline"] += 1
        else:
            kept.append(finding)
    document = stamp("check", {"model": dump["model"], "findings": kept})
    document["_left_out"] = left_out
    return document


def _blocked_buttons(ir_path, width: int, height: int, topbar_height, dump: dict) -> list[dict]:
    """Buttons whose centre another element takes a click from (rhr.hitmap's rules)."""
    from rhr.hitmap import build_hitmap

    hitmap = build_hitmap(ir_path, width, height, topbar_height=topbar_height)
    targets = {(test["point"]["x"], test["point"]["y"]): test for test in hitmap["hitTests"]}
    by_path = {entry["path"]: entry for entry in dump.get("nodes") or []}
    ctx = {"by_path": by_path}
    findings = []
    for node in hitmap["nodes"]:
        rect = node.get("rect")
        if not node.get("activatedTargetCandidate") or rect is None:
            continue
        entry = by_path.get(node["path"])
        if entry is not None and _collapsed(entry, ctx):
            continue
        test = targets.get((round(rect["x"] + rect["w"] / 2, 3), round(rect["y"] + rect["h"] / 2, 3)))
        if test is None or test["target"] in (None, node["path"]):
            continue
        finding = {"paths": [node["path"], test["target"]]}
        if test.get("targetIsButton"):
            findings.append({**finding, "check": "button-covered", "severity": "info",
                             "detail": f"{test['target']} is on top at this button's centre and gets the click"})
        else:
            findings.append({**finding, "check": "button-blocked", "severity": "error",
                             "detail": (f"{test['target']}, an Active element in a ScreenGui above, swallows the "
                                        "clicks at this button's centre (even when transparent): players cannot "
                                        "click it there")})
    return findings


def _suppressed(ir: dict) -> dict[str, set[str]]:
    """Path -> check ids its `RhrIgnore` attribute leaves out ({"all"} for every one)."""
    out: dict[str, set[str]] = {}

    def walk(node: dict) -> None:
        value = node.get("rhrIgnore")
        if isinstance(value, str) and value.strip():
            out[node["path"]] = {part.strip() for part in value.split(",") if part.strip()}
        for child in node.get("children") or []:
            walk(child)

    for root in ir.get("roots") or []:
        walk(root)
    return out


def _is_suppressed(finding: dict, suppressed: dict[str, set[str]]) -> bool:
    if not suppressed:
        return False
    for path in finding["paths"]:
        here = path
        while here:
            ids = suppressed.get(here)
            if ids is not None and ("all" in ids or finding["check"] in ids):
                return True
            here = here.rpartition("/")[0]
    return False


def _missing_images(ir: dict) -> dict[str, tuple[str, str]]:
    """Path -> (uri, why) for the UI's images Roblox refused when RHR last asked."""
    from rhr import fetch
    from rhr.adapter import ui_nodes

    uses = fetch.image_uses(ui_nodes(ir))
    refused = fetch.refused_recently("images", uses) if uses else {}
    return {use["path"]: (use["uri"], why) for asset, why in refused.items() for use in uses[asset]}


def _image_paths(ir: dict) -> set[str]:
    """Every UI node path that carries an Image (the dump does not see images)."""
    from rhr.adapter import GUI_CLASSES, ui_branches

    out: set[str] = set()
    branches = ui_branches(ir)  # only the UI: a place's 3D world is skipped

    def walk(node: dict, inside: bool = False) -> None:
        props = node.get("props") or {}
        if props.get("Image") or props.get("ImageContent"):
            out.add(node["path"])
        inside = inside or node.get("className") in GUI_CLASSES
        for child in node.get("children") or []:
            if inside or id(child) in branches:
                walk(child, inside)

    for root in ir.get("roots") or []:
        walk(root)
    return out


def load_baseline(path: Path) -> dict:
    """An earlier `rhr check` output, for --baseline."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read the baseline {path}: {exc}") from None
    if not str(document.get("schema", "")).startswith("rhr.check/"):
        raise ValueError(f"{path} is not an `rhr check` output (schema {document.get('schema')!r})")
    return document


def findings_json(result: dict) -> str:
    """The canonical serialisation: sorted keys, deterministic."""
    from rhr.schema import dumps

    return dumps({key: value for key, value in result.items() if not key.startswith("_")})
