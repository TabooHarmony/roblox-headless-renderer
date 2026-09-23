#!/usr/bin/env python3
"""ScrollingFrame scale resolution: a child's Scale resolves against the WINDOW.

Roblox lays a ScrollingFrame's direct children out against the ScrollingFrame's
absolute (window) size; CanvasSize only extends the scrollable range and the
clip. Patch 0015 fixed the vendored renderer, which resolved Scale against the
full canvas extent and pushed children (Trading's dark BackgroundFrame panels,
CanvasSize yScale 3) far below the visible window. On the (since removed)
real-game captures this fix moved Trading 85.74 -> 92.38 within8, EggRarity 92.69 -> 95.96.

Fixture: a ScrollingFrame (100x100 at 50,50 content coords, CanvasSize yScale 3)
with one blue child Panel at yScale 0.06, height yScale 10.067. Before the fix
the panel's top lands at content-y 0.06 * 300 (canvas height) = 18px too low and
its extent explodes; after, Scale uses the window and the clip still bounds it.

Run: python tests/test_scroll_scale.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from test_fixtures import _bbox, _render, rel  # noqa: E402

BLUE = (0, 0, 255)
RED = (255, 0, 0)


def check_panel_at_window_scale() -> str:
    """Panel's yScale 0.06 resolves against the 100px window, not the 300px canvas."""
    img = _render("scroll_scale")
    box = rel(_bbox(img, BLUE), "scroll_scale")
    # Window origin y=58 (top bar), frame at content (50,50). Panel top =
    # 0.06*100 = 6 inside the frame -> content y 56 (the origin is already
    # subtracted by rel()). The panel is 10.067*100 = 1006 tall, clipped by
    # the frame's bottom (content y 150): bbox bottom = 149.
    expected = (50, 56, 149, 149)
    assert box == expected, f"panel bbox {box}, expected {expected}"
    return f"panel bbox {box} (window-scale top 114, clipped at frame bottom)"


def check_frame_bg_visible() -> str:
    """The ScrollingFrame's own red background still paints outside the panel."""
    img = _render("scroll_scale")
    # The panel (top at content y 56, clipped at 150) covers the frame below
    # y=56; red shows only in the 0.06*100 = 6px band above it. The frame bg's
    # bbox is red-dominant there but PIL reports red only where it wins: 50..55.
    box = rel(_bbox(img, RED), "scroll_scale")
    expected = (50, 50, 149, 54)
    assert box == expected, f"frame bg bbox {box}, expected {expected}"
    return f"frame bg visible above the panel: {box}"


def check_canvas_does_not_escape_clip() -> str:
    """Nothing paints outside the 100x100 window even though CanvasSize is 3x."""
    img = _render("scroll_scale")
    box = rel(_bbox(img, BLUE), "scroll_scale")
    assert box[3] <= 207, f"panel leaks below the clip: bbox {box}"
    assert box[0] >= 50 and box[2] <= 149, f"panel leaks sideways: bbox {box}"
    return f"panel clipped to the window: {box}"


CHECKS = [
    ("scroll_scale: panel top at window yScale", check_panel_at_window_scale),
    ("scroll_scale: frame background intact", check_frame_bg_visible),
    ("scroll_scale: canvas stays inside the clip", check_canvas_does_not_escape_clip),
]


def main() -> int:
    failures = 0
    for name, fn in CHECKS:
        try:
            detail = fn()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")
        else:
            print(f"ok    {name}: {detail}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} scroll-scale checks pass")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
