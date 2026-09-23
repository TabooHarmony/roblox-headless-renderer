"""Smoke test: does the vendored pinevex renderer run on this box's skia-python?

Not a unit test. This is the Phase 1 go/no-go check that skia-python 144 can
draw, write a PNG, and that the vendored renderer imports and renders a
minimal ScreenGui without needing the Vercel API, a display, or a GPU.

Usage: .venv/bin/python scripts/smoke_skia.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR_SRC = REPO / "vendor" / "pinevex" / "src"
FONTS = VENDOR_SRC / "ui_engine" / "fonts"
OUT = REPO / "out"

sys.path.insert(0, str(VENDOR_SRC))


def main() -> int:
    import skia

    print(f"skia-python {skia.__version__}")

    OUT.mkdir(exist_ok=True)

    # 1. Bare skia: draw a rect and read the pixel back.
    surface = skia.Surface(64, 32)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color(0, 0, 0, 0))
    paint = skia.Paint(Color=skia.Color(255, 0, 0, 255), AntiAlias=False)
    canvas.drawRect(skia.Rect.MakeXYWH(8, 8, 16, 16), paint)
    image = surface.makeImageSnapshot()
    # skia's default N32 colortype is BGRA on little-endian, so toarray() gives
    # B,G,R,A. Check the channel order explicitly instead of assuming RGBA.
    px = list(surface.makeImageSnapshot().toarray()[12, 12])
    print(f"raw toarray at (12,12) = {px} (N32 is BGRA, so this should be blue-last)")
    bare = OUT / "smoke_skia_bare.png"
    image.save(str(bare), skia.kPNG)
    print(f"wrote {bare}")

    # The PNG is the artifact that matters; read the saved bytes back through
    # PIL so the check does not depend on skia's in-memory channel order.
    from PIL import Image

    with Image.open(bare) as im:
        rgba = im.convert("RGBA").getpixel((12, 12))
    print(f"PNG pixel at (12,12) = {rgba}")
    assert rgba == (255, 0, 0, 255), f"expected red in the PNG, got {rgba}"

    # 2. The real question: does the vendored renderer import and render?
    from ui_engine.renderer import render_json

    tree = {
        "type": "Frame",
        "name": "Root",
        "size": [1.0, 1.0],
        "sizeRef": "parent",
        "bg": [255, 255, 255],
        "children": [
            {
                "type": "TextLabel",
                "name": "Hello",
                "size": [0.5, 0.25],
                "position": [0.25, 0.25],
                "bg": [0, 0, 0],
                "text": "pinevex on skia 144",
                "textSize": 18,
                "textColor": [255, 255, 255],
                "_path": "Root/Hello",
            }
        ],
        "_path": "Root",
    }
    rects: dict = {}
    tool_png = OUT / "smoke_pinevex.png"
    render_json(
        tree,
        str(tool_png),
        width=400,
        height=200,
        fonts_dir=FONTS,
        bg_color=(255, 255, 255),
        rect_map=rects,
    )
    print(f"wrote {tool_png}")
    print(f"rect_map = { {k: (v.x, v.y, v.w, v.h) for k, v in rects.items()} }")

    from PIL import Image

    for p in (bare, tool_png):
        with Image.open(p) as im:
            ex = im.convert("RGB").getextrema()
        print(f"{p.name}: {im.size} {im.mode} extrema={ex}")
        assert im.size[0] > 0 and im.size[1] > 0

    # The label must actually have painted; a blank render is the failure we
    # care about, and "it returned without raising" is not evidence.
    with Image.open(tool_png) as im:
        colors = im.convert("RGB").getcolors(maxcolors=1 << 24)
    print(f"distinct colors in render: {len(colors)}")
    assert len(colors) > 1, "render is a single flat color: nothing drew"

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())