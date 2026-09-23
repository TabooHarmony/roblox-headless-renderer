"""Studio-proven rule: outlines do not shrink TextScaled glyphs.

Fixed-box Studio probe 47cf5c3ab6d2425094477563e094c2bf returned
TextBounds 150x12 at UIStroke thickness 0, 2 and 5, after two frames.
Exercise actual painted fill, separately from the blue outline, and both
plain and RTL fit entrypoints. No screenshot baseline is generated here.
"""
from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from rhr.pipeline import render_object
from ui_engine import text_renderers as text

OUT = REPO / "out" / "textscaled-stroke"


def main():
    status = 0

    def check(ok, message):
        nonlocal status
        status |= not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {message}")

    base = {
        "type": "TextLabel", "name": "StrokeFit", "size": [0, 200, 0, 40],
        "position": [0, 20, 0, 20], "bgTransparency": 1,
        "text": "Hello world", "font": "FredokaOne", "textSize": 14,
        "textScaled": True, "textColor": [255, 0, 0],
        "textStrokeTransparency": 1,
    }
    for mode, string in (("plain", "Hello world"), ("rtl", "Hello world\u200f")):
        masks, sizes, pictures = [], [], []
        fit_name = "_fit_font_size" if mode == "plain" else "_fit_paragraph_font_size"
        original = getattr(text, fit_name)
        for thickness in (0, 2, 5):
            node = deepcopy(base)
            node["text"] = string
            if thickness:
                node["strokes"] = [{"thickness": thickness, "color": [0, 0, 255],
                                    "transparency": 0, "applyMode": "Contextual"}]
            with patch.object(text, fit_name, wraps=original) as fitting:
                png = render_object(node, OUT / f"{mode}-{thickness}.png", 240, 80)
            check(fitting.call_count > 0, f"{mode}/{thickness}: fit path executed")
            if fitting.call_count:
                call = fitting.call_args
                size = ((call.args[2], call.args[3]) if mode == "plain"
                        else (call.kwargs["max_w"], call.kwargs["max_h"]))
                sizes.append(size)
            image = np.array(Image.open(png).convert("RGBA"))
            mask = (image[:, :, 0] > 200) & (image[:, :, 1] < 40) & (image[:, :, 2] < 40) & (image[:, :, 3] > 200)
            yy, xx = np.where(mask)
            check(bool(len(xx)), f"{mode}/{thickness}: visible red glyph fill")
            masks.append(None if not len(xx) else (int(xx.min()), int(yy.min()), int(xx.max()), int(yy.max())))
            pictures.append(png.read_bytes())
            repeat = render_object(node, OUT / f"{mode}-{thickness}-repeat.png", 240, 80)
            check(png.read_bytes() == repeat.read_bytes(), f"{mode}/{thickness}: deterministic PNG bytes")
        check(len(sizes) == 3 and sizes == [(200.0, 40.0)] * 3,
              f"{mode}: full content box regardless of outline: {sizes}")
        check(masks[0] is not None and masks[0] == masks[1] == masks[2],
              f"{mode}: glyph-fill bbox independent of outline: {masks}")
        check(len(set(pictures)) == 3, f"{mode}: outlines still change painted output")
    return int(status)


if __name__ == "__main__":
    raise SystemExit(main())
