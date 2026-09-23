#!/usr/bin/env python3
"""Rebuild patches/*.patch from the vendor edits, and verify them.

Splits the edits in src/rhr/vendor/pinevex into one patch per defect by classifying each
diff hunk, then applies all patches to a clean copy of the pristine upstream tree
and compares the result with src/rhr/vendor/pinevex byte for byte. A patch set that does
not reconstruct the vendored tree exactly is a bug in the patch set.

    python3 scripts/make_patches.py [pristine-tree]

The pristine tree is a clone of upstream at the commit in src/rhr/vendor/VENDOR.md,
with its .git intact so the tree can be reset and re-diffed. The vendored copy omits
upstream's demo site, API and example models (VENDOR.md); only patched files are compared.
"""
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if len(sys.argv) < 2:
    sys.exit("usage: python scripts/make_patches.py <pristine-upstream-clone>")
PRISTINE = Path(sys.argv[1])
VENDOR = REPO / "src" / "rhr" / "vendor" / "pinevex"
PATCHES = REPO / "patches"
CHECK = Path(tempfile.gettempdir()) / "rhr-patch-check"

FILES = [
    "src/ui_engine/renderer.py",
    "src/ui_engine/hit_test.py",
    "src/ui_engine/layout.py",
    "src/ui_engine/assets.py",
    "web_demo/rbxm_parser_component/tree_to_pinevexobject.py",
    "src/ui_engine/text_renderers.py",
    "src/ui_engine/text_fit.py",
    "src/ui_engine/text_rich.py",
    "src/ui_engine/text_advances.py",
    "src/ui_engine/text_runs.py",
    "src/ui_engine/text_fonts.py",
    "src/ui_engine/data/font_advances_FredokaOne.json",
    "vendor/product_output/pinevex_postprocess.py",
]

PATCHES_DEF = {
    "0001-grid-cell-offsets.patch": {
        "title": "UIGridLayout CellSize/CellPadding offsets are kept and read",
        "files": ["src/ui_engine/renderer.py", "src/ui_engine/hit_test.py",
                  "web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
        # The `_path` hunk in the same file is patch 0004's; its context lines
        # mention _udim2_to_full too, so exclude it here.
        "classify": lambda h: ("_grid_axis" in h or "_udim2_to_full" in h) and "_path" not in h,
    },
    "0002-zero-size-parent-subtree.patch": {
        "title": "Children of a zero-area node are still laid out and drawn",
        "files": ["src/ui_engine/renderer.py"],
        "classify": lambda h: "degenerate" in h or "_render_children_only" in h,
    },
    "0003-autosize-padding.patch": {
        "title": "AutomaticSize includes the node's own UIPadding",
        "files": ["src/ui_engine/layout.py"],
        "classify": lambda h: True,
    },
    "0005-root-rect.patch": {
        "title": "render_json/collect_layout_info take the root rect, not always the canvas",
        "files": ["src/ui_engine/renderer.py"],
        # The engine hardcoded Rect(0, 0, width, height) as the root and as the
        # sizing viewport, so a ScreenGui's content area could not be inset. The
        # default is unchanged, so upstream behaviour is byte-identical without it.
        "classify": lambda h: "root_rect" in h,
    },
    "0004-path-passthrough.patch": {
        "title": "flatten_node keeps the caller's _path so a rect map can be read back",
        "files": ["web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
        # The renderer already stores every resolved rect under _path when handed a
        # rect_map; the demo's converter was the only thing dropping the label.
        "classify": lambda h: 'result["_path"]' in h,
    },
    "0006-textscaled-honesty.patch": {
        "title": "TextScaled comes from the model, and TextScaled implies TextWrapped",
        "files": ["src/ui_engine/text_renderers.py", "src/ui_engine/text_rich.py",
                  "vendor/product_output/pinevex_postprocess.py"],
        # The postprocess forced textScaled=True on every TextLabel, so TextSize
        # was ignored everywhere and every label's font was fitted to its rect.
        # Case-insensitive because the renderer keys are lowercase while the
        # converter reads the property's own "TextScaled".
        # (Its converter hunk moved to 0007: the two edits sit in one diff hunk
        # now that TextTruncate passes through the same lines, so no per-hunk
        # split is possible. The RTL/plain textscaled-fit hunks moved to 0010
        # the same way: the stroke-fit edit sits inside them.)
        "classify": lambda h: (
            ("extScaled" in h or "textWrapped" in h)
            and "outlines never" not in h and "_max_text_outline_thickness" not in h
            # Advance-table hunks (0014) also mention TextWrapped; keep them out.
            and "adv_table" not in h and "table_single_line" not in h
            and "text_advances" not in h
        ),
    },
    "0007-text-truncate.patch": {
        "title": "TextTruncate (AtEnd/SplitWord) passes through and draws with an "
                 "ellipsis; its unwrapped-line hunk also carries unwrapped "
                 "explicit newlines and the converter carries LineHeight",
        "files": ["src/ui_engine/text_renderers.py",
                  "web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
        # The converter dropped TextTruncate/MaxVisibleGraphemes entirely and the
        # renderer ignored them, so a model asking for truncation spilled its
        # full string into the clip instead of trimming with an ellipsis.
        #
        # In the converter the 0006 and 0007 edits sit in ONE diff hunk
        # (textScaled / textWrapped / TextTruncate are adjacent), so no
        # per-hunk split is possible: this patch carries the whole hunk, and
        # 0006's classify is tightened to only its own renderer/postprocess
        # hunks in the files the two no longer share.
        "classify": lambda h: (
            "textTruncate" in h or "_truncate_ellipsis" in h
            or "maxVisibleGraphemes" in h or "Graphemes" in h
        ) or ("textScaled" in h and "textTruncate" in h),
    },
    "0009-group-transparency.patch": {
        "title": "CanvasGroup GroupTransparency and GroupColor3 apply to the whole group",
        "files": ["src/ui_engine/renderer.py",
                  "web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
        "classify": lambda h: "group_layer" in h or "groupTransparency" in h,
    },
    "0010-textscaled-stroke-fit.patch": {
        "title": "TextScaled fits the full content box: outlines never shrink glyphs "
                 "(Studio fixed-box probe); its plain-fit hunk also passes LineHeight "
                 "to the fit (adjacent edit, one diff hunk)",
        "files": ["src/ui_engine/text_renderers.py"],
        "classify": lambda h: "outlines never" in h or "_max_text_outline_thickness" in h,
    },
}

PATCHES_DEF["0011-image-resampling.patch"] = {
    "title": "Preserve ResampleMode and smooth ordinary image draws by default",
    "files": ["src/ui_engine/assets.py",
              "web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
    "classify": lambda h: any(key in h for key in (
        "ResampleMode", "resampleMode", "sampling", "SAMPLING")),
}

PATCHES_DEF["0012-text-newlines.patch"] = {
    "title": "Preserve explicit line breaks; the plain fit applies the LineHeight step",
    "files": ["src/ui_engine/text_fit.py"],
    # The advance-table fit hunks belong to 0014 (its classify matches); everything
    # else in text_fit.py is newline/LineHeight work.
    "classify": lambda h: ("advance_table" not in h and "TABLE" not in h
                           and "text_advances" not in h),
}

PATCHES_DEF["0014-font-advance-tables.patch"] = {
    "title": "Studio-measured per-family glyph advance tables drive fit and draw (plan 0.2a)",
    "files": ["src/ui_engine/text_fit.py", "src/ui_engine/text_renderers.py",
              "src/ui_engine/text_advances.py", "src/ui_engine/text_runs.py",
              "vendor/product_output/pinevex_postprocess.py",
              "src/ui_engine/data/font_advances_FredokaOne.json"],
    "classify": lambda h: (
        # Hunks carrying 0007's truncate edits (the combined line-1 hunk and
        # the Build-lines hunk) stay in 0007.
        "_truncate_ellipsis" not in h
        # 0010's stroke-fit removal hunk carries the advance_table= call site
        # in its vendor-side lines; it stays in 0010.
        and "stroke_pad" not in h and "_max_text_outline_thickness" not in h
        and ("advance_table" in h or "TABLE" in h
             or "table_mode" in h or "adv_table" in h
             or "table_single_line" in h or "_table_covers_text" in h
             or "text_advances" in h or "string_width" in h
             or "draw_line_table" in h
             or "font_advances_FredokaOne" in h
             or "TextBounds probe" in h or "FredokaOne" in h
             # Pixel-font advance work (0.2b): Press Start 2P advances 1em/glyph
             # in Roblox; TTF advance is 0.56em. Spans text_runs measure/draw,
             # the paragraph letter-spacing bridge, and the postprocess font
             # allowlist that keeps the family from defaulting to GothamSSm.
             or "_is_pixel_font" in h or "_PIXEL_FONT" in h
             or "pixel" in h.lower() or "PressStart2P" in h
             or "letterSpacing" in h or "letter spacing" in h)),
}

PATCHES_DEF["0013-rich-newlines.patch"] = {
    "title": "Rich literal newlines reuse mandatory br line breaks",
    "files": ["src/ui_engine/text_rich.py"],
    "classify": lambda h: "Literal newlines" in h,
}

PATCHES_DEF["0015-scroll-scale-window.patch"] = {
    "title": "ScrollingFrame children resolve Scale against the window, not the canvas",
    "files": ["src/ui_engine/renderer.py"],
    # The canvas-rect child_parent fix carries the comment line "window size"
    # and the Rect(canvas_rect.x, ...) shape; everything else in renderer.py
    # belongs to the earlier patches (0001/0002/0005/0009/0011 classify first
    # or via their own keys).
    "classify": lambda h: "WINDOW size" in h or "Rect(canvas_rect.x" in h,
}
PATCHES_DEF["0018-roblox-text-size-and-layout-rects.patch"] = {
    "title": "Draw text at Roblox's size and let RHR's layout pass supply the rects",
    "files": ["src/ui_engine/text_fonts.py", "src/ui_engine/text_fit.py", "src/ui_engine/text_renderers.py",
              "src/ui_engine/text_rich.py", "src/ui_engine/text_runs.py", "src/ui_engine/renderer.py"],
    "classify": lambda h: any(key in h for key in (
        "roblox_font", "roblox_em_px", "wrap_lines_table", "_textLayout", "_layout_rects",
        "layout_rects", "no font line gap", "last complete word",
    )),
}
PATCHES_DEF["0017-studio-measured-layout.patch"] = {
    "title": "Studio-measured UI fixes: UISizeConstraint, SortOrder.Name, measured AutomaticSize text, fonts kept as authored",
    "files": ["src/ui_engine/layout.py", "src/ui_engine/renderer.py", "src/ui_engine/hit_test.py",
              "src/ui_engine/text_fonts.py", "vendor/product_output/pinevex_postprocess.py",
              "web_demo/rbxm_parser_component/tree_to_pinevexobject.py"],
    # Classify before 0016 (text_fonts.py hunks) by their own markers.
    "classify": lambda h: any(key in h for key in (
        "sizeLimits", "sortOrder", "layout_order_key", "_measured_text_lines",
        "roblox_em_scale", "BuilderSans", "GothamSSm", "Keep the model's own family",
    )),
}
PATCHES_DEF["0016-freetype-font-manager.patch"] = {
    "title": "Load every bundled font through one FreeType font manager, not the platform default",
    "files": ["src/ui_engine/text_fonts.py"],
    # skia.Typeface.MakeFromFile uses DirectWrite on Windows and CoreText on macOS,
    # so the same TTF rasterized differently per OS (96.7% identical Windows vs
    # Linux on the frozen baseline). Every hunk in text_fonts.py is this change.
    "classify": lambda h: True,
}

EXTRA_PATCHES = ["0008-grid-alignment.patch"]
PINNED_PATCHES = {
    "0001-grid-cell-offsets.patch",
    "0002-zero-size-parent-subtree.patch",
    "0005-root-rect.patch",
}


def hunks_of(rel: str):
    """(header, [hunk]) for one file, diffed against the pristine tree."""
    pristine_rel = PRISTINE / rel
    # New files have no pristine counterpart: diff against the empty file so
    # the whole content arrives as one hunk with valid a/ labels.
    from_ = str(pristine_rel) if pristine_rel.exists() else "/dev/null"
    out = subprocess.run(
        ["diff", "-u", "--label", f"a/{rel}", "--label", f"b/{rel}",
         from_, str(VENDOR / rel)],
        capture_output=True, text=True,
    ).stdout
    if not out:
        return [], []
    lines = out.splitlines(keepends=True)
    hunks, cur = [], None
    for line in lines[2:]:
        if line.startswith("@@"):
            if cur:
                hunks.append("".join(cur))
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur:
        hunks.append("".join(cur))
    return lines[:2], hunks


def main() -> int:
    if not (PRISTINE / "src" / "ui_engine" / "renderer.py").exists():
        raise SystemExit(f"pristine tree not found at {PRISTINE}")
    if CHECK.exists():
        shutil.rmtree(CHECK)

    for name, spec in PATCHES_DEF.items():
        if name in PINNED_PATCHES:
            continue
        body, count = [], 0
        for rel in spec["files"]:
            header, hunks = hunks_of(rel)
            keep = [h for h in hunks if spec["classify"](h)]
            if not keep:
                raise SystemExit(f"{name}: no matching hunks in {rel}")
            count += len(keep)
            body.append("".join(header + keep))
        text = (f"# {spec['title']}\n#\n"
                f"# Apply from src/rhr/vendor/pinevex:  git apply -p1 < patches/{name}\n"
                + "".join(body))
        (PATCHES / name).write_text(text)
        print(f"wrote {name}: {count} hunks, {len(text.splitlines())} lines")

    shutil.copytree(PRISTINE, CHECK, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    apply_order = [*PATCHES_DEF, *EXTRA_PATCHES]
    for name in apply_order:
        if name not in PATCHES_DEF and not (PATCHES / name).exists():
            raise SystemExit(f"missing extra patch: {name}")
        r = subprocess.run(["git", "apply", "-p1", str(PATCHES / name)],
                           cwd=CHECK, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"APPLY FAILED {name}\n{r.stdout}{r.stderr}")
            return 1

    bad = [rel for rel in FILES if not filecmp.cmp(CHECK / rel, VENDOR / rel, shallow=False)]
    print("reconstruct check:", "identical" if not bad else f"MISMATCH {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())