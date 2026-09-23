"""TextScaled semantics: TextSize is ignored only when the label asks for it.

One fixture, five labels, same string, measured by glyph pixels:

    Small   box 100x20   TextScaled   TextSize 14
    Tall    box 100x200  TextScaled   TextSize 14
    Capped  box 100x200  TextScaled   TextSize 14 + UITextSizeConstraint MaxTextSize 20
    Fixed   box 100x200  TextScaled=false, TextSize 14
    Wrap    box 100x200  TextScaled, long text, no TextWrapped

Roblox's rules (creator-docs, TextLabel.TextScaled / TextLabel.TextSize): with
TextScaled on, TextSize is ignored, the font is fitted to the rect, wrapping is
implicitly enabled and the fit is capped at 100 or by a UITextSizeConstraint.
With TextScaled off, TextSize is the rendered line height regardless of the rect.

So: the box must drive Small vs Tall (same TextSize), the constraint must cap
Capped below Tall, Fixed must stay at 14px in a 200px-tall box, and Wrap must
break into several lines instead of shrinking to a smear.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

VIEWPORT = (600, 400)
FIXTURE = REPO / "tests" / "fixtures" / "textscaled.rbxmx"
OUT = REPO / "out" / "textscaled"

COLORS = {
    "Small": (255, 0, 0),
    "Tall": (0, 255, 0),
    "Capped": (0, 0, 255),
    "Fixed": (255, 255, 0),
    "Wrap": (255, 0, 255),
}
TEXT_SIZE = 14.0


def _kids(node):
    children = node.get("children") or []
    return children if isinstance(children, list) else list(children.values())


def _object():
    """The pinevex object the engine draws, plus its labels keyed by name."""
    from rhr.adapter import ir_to_raw_nodes
    from rhr.ir import load_ir
    from rhr.pipeline import to_pinevex_object

    from test_fixtures import emit_ir

    ir = emit_ir(FIXTURE, OUT / "textscaled.json")
    obj = to_pinevex_object(ir_to_raw_nodes(load_ir(ir)))
    return obj, {child.get("name"): child for child in _kids(obj)}


def _heights(obj) -> dict:
    from rhr.pipeline import render_object

    png = render_object(obj, OUT / "textscaled.png", *VIEWPORT, bg_color=(0, 0, 0, 0))
    img = np.asarray(Image.open(png).convert("RGBA")).astype(int)
    out = {}
    for name, rgb in COLORS.items():
        mask = (np.abs(img[..., :3] - np.array(rgb)).max(axis=2) <= 8) & (img[..., 3] > 200)
        ys, xs = np.where(mask)
        out[name] = None if len(ys) == 0 else (int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1))
    return out


def main() -> int:
    status = 0

    def check(ok: bool, label: str) -> None:
        nonlocal status
        status |= 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  {label}")

    obj, labels = _object()
    heights = _heights(obj)
    for name, held in heights.items():
        print(f"      {name:7} glyph box {'none' if held is None else f'{held[0]}x{held[1]}px'}")

    missing = [name for name, held in heights.items() if held is None]
    check(not missing, f"every label drew text (missing: {missing or 'none'})")
    if missing:
        print("\nFAIL  textscaled")
        return status

    small, tall = heights["Small"][0], heights["Tall"][0]
    capped, fixed = heights["Capped"][0], heights["Fixed"][0]
    wrap_h = heights["Wrap"][0]

    # 1. TextScaled off must not fit the text to the rect: TextSize rules instead.
    check(labels["Fixed"].get("textScaled") is False,
          "Fixed: explicit false survives the converter")
    check(fixed < tall, f"TextScaled=false renders at TextSize: {fixed}px < {tall}px (was fitted)")
    check(abs(fixed - TEXT_SIZE) <= 5, f"TextScaled=false glyph height near TextSize {TEXT_SIZE}: {fixed}px")

    # 2. TextScaled on: the rect decides, TextSize is 14 on both of these labels.
    check(labels["Tall"].get("textScaled") is True, "Tall: scaled flag reaches the renderer")
    check(tall > 1.4 * small, f"the box drives the size at equal TextSize: {tall}px vs {small}px")

    # 3. UITextSizeConstraint caps the fit, and the cap is read from the child.
    tsc = labels["Capped"].get("textSizeConstraint")
    check(tsc == {"min": 1, "max": 20}, f"Capped: constraint read as {tsc}")
    check(capped < 0.9 * tall, f"constraint caps the fit: {capped}px < {tall}px")
    check(capped > 0.9 * fixed, f"capped text is a 20px font, not a 14px one: {capped}px vs {fixed}px")

    # 4. TextScaled implies TextWrapped: long text breaks instead of shrinking.
    check(wrap_h > 3 * tall, f"long scaled text wraps: {wrap_h}px of glyphs over several lines")
    check(heights["Wrap"][1] <= 100, f"wrapped lines stay inside the 100px box width: {heights['Wrap'][1]}px")

    print(f"\n{'PASS' if status == 0 else 'FAIL'}  textscaled")
    return status


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())