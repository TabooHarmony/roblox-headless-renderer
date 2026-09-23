"""Screen insets: the offset a ScreenGui's content area gets from the top bar.

Two fixtures, identical but for `ScreenInsets`: anything different between their
rects and pixels is the inset, and if nothing is different the feature is not wired.
The default (a ScreenGui with no ScreenInsets property) must behave like
CoreUISafeInsets, which is what Roblox itself does.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

VIEWPORT = (1615, 1080)
FIXTURES = REPO / "tests" / "fixtures"
TOPBAR = 58.0


def _rects(name: str) -> dict:
    from rhr.pipeline import load_for_screen

    from test_fixtures import emit_ir

    ir = emit_ir(FIXTURES / f"{name}.rbxmx", REPO / "out" / "insets" / f"{name}.json")
    obj, root_rect, inset = load_for_screen(ir, *VIEWPORT)
    return {"obj": obj, "root": root_rect, "inset": inset}


def main() -> int:
    from rhr.pipeline import render_object

    status = 0
    core = _rects("screen_insets_coreui")
    none = _rects("screen_insets_none")

    # 1. the root rect itself: the ScreenGui's content area
    expected = {
        "coreui": (0.0, TOPBAR, 1615.0, 1080.0 - TOPBAR),
        "none": (0.0, 0.0, 1615.0, 1080.0),
    }
    for label, held in (("coreui", core), ("none", none)):
        got = (held["root"].x, held["root"].y, held["root"].w, held["root"].h)
        ok = got == expected[label]
        status |= 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  {label}: content area {got} "
              f"(expected {expected[label]})")

    if (core["root"].x, core["root"].y) == (none["root"].x, none["root"].y):
        print("FAIL  both modes resolve to the same origin: the inset is not wired")
        status |= 1

    # 2. mode selection, including the two cases the file cannot express directly
    from rhr.insets import mode_of, resolve

    cases = [
        ({"ScreenInsets": {"_t": "EnumItem", "name": "None", "value": 0}}, "None"),
        ({"ScreenInsets": {"name": "CoreUISafeInsets", "value": 2}}, "CoreUISafeInsets"),
        ({"ScreenInsets": "Enum.ScreenInsets.TopbarSafeInsets"}, "TopbarSafeInsets"),
        ({"ScreenInsets": 1}, "DeviceSafeInsets"),
        ({}, "CoreUISafeInsets"),  # absent property: Roblox's own default
        ({"ScreenInsets": {"name": "CoreUISafeInsets"}, "IgnoreGuiInset": "true"},
         "DeviceSafeInsets"),  # the legacy flag's documented meaning
    ]
    for props, want in cases:
        got = mode_of(props)
        ok = got == want
        status |= 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  mode_of({props}) -> {got} (expected {want})")

    # 3. TopbarSafeInsets is documented as unmodelled, not silently wrong
    topbar = resolve("TopbarSafeInsets")
    ok = topbar.note and "not modelled" in topbar.note and topbar.top == TOPBAR
    status |= 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  TopbarSafeInsets falls back with a note: "
          f"{topbar.describe()}")

    # 4. pixels: the inset moves what is drawn, not only what is measured
    pngs = {}
    for label, held in (("coreui", core), ("none", none)):
        out = REPO / "out" / "insets" / f"{label}.png"
        render_object(
            held["obj"],
            out,
            *VIEWPORT,
            bg_color=(0, 0, 0, 0),
            root_rect=held["root"],
        )
        pngs[label] = out

    from PIL import Image

    probe = (10, 20)
    with Image.open(pngs["coreui"]) as img:
        a = img.convert("RGBA").getpixel(probe)
    with Image.open(pngs["none"]) as img:
        b = img.convert("RGBA").getpixel(probe)
    ok = a != b
    status |= 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  pixel {probe} differs between modes: "
          f"coreui {a} vs none {b}")

    # 5. and the reason it differs is the shift, not a different paint: the same
    #    content must appear 58px lower in the CoreUISafeInsets render.
    with Image.open(pngs["coreui"]) as img:
        shifted = img.convert("RGBA").getpixel((probe[0], probe[1] + int(TOPBAR)))
    with Image.open(pngs["none"]) as img:
        unshifted = img.convert("RGBA").getpixel(probe)
    ok = shifted == unshifted
    status |= 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  coreui at y+{int(TOPBAR)} matches none at y: "
          f"{shifted} vs {unshifted}")

    print(f"\n{'PASS' if status == 0 else 'FAIL'}  insets")
    return status


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())