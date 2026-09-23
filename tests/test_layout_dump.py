#!/usr/bin/env python3
"""Layout checks: the renderer hands back the rects it actually resolved.

The engine's renderer takes a rect_map and records every drawn node's resolved
rectangle under its `_path` label. That is the only honest layout output this
project has: it is the geometry the paint pass used, not a second implementation
that could disagree with it. tree_to_pinevexobject dropped the label, so the map
was always empty (patches/0004-path-passthrough.patch).

Rect values come from Roblox's layout rules and the fixture XML, so a wrong one
cannot pass: a UIGridLayout with CellSize 32 and CellPadding 8 puts cells at x =
0, 40, 80, 120 whatever order they are walked in.

Run: python tests/test_layout_dump.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

FIXTURES = REPO / "tests" / "fixtures"
VIEWPORT = (400, 300)

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def layout(fixture: str) -> dict:
    from rhr.ir import load_ir
    from rhr.pipeline import render_ir

    from test_fixtures import emit_ir

    rect_map: dict = {}
    render_ir(
        emit_ir(FIXTURES / f"{fixture}.rbxmx"),
        REPO / "out" / "layout" / f"{fixture}.png",
        *VIEWPORT,
        bg_color=(0, 0, 0, 0),
        rect_map=rect_map,
    )
    return rect_map


def rect(map_: dict, path: str, fixture: str | None = None) -> tuple[float, float, float, float]:
    """rect_map values are the engine's own Rect objects, straight out of render.

    With *fixture*, the rect is returned relative to that fixture's content area,
    so the expected numbers below stay the layout rule and not the inset.
    """
    r = map_[path]
    got = (round(r.x, 3), round(r.y, 3), round(r.w, 3), round(r.h, 3))
    if fixture is None:
        return got
    from test_fixtures import content_origin

    ox, oy = content_origin(fixture)
    return (got[0] - ox, got[1] - oy, got[2], got[3])


def main() -> int:
    print("layout dump: resolved rects come back per node path")

    grid = layout("grid_offset")
    check(len(grid) == 5, f"grid_offset reports every drawn node ({len(grid)} rects)")
    expected = {
        "GridOffset/Root": (0.0, 0.0, 400.0, 300.0),
        "GridOffset/Root/Cell1": (0, 0, 32, 32),
        "GridOffset/Root/Cell2": (40, 0, 32, 32),
        "GridOffset/Root/Cell3": (80, 0, 32, 32),
        "GridOffset/Root/Cell4": (120, 0, 32, 32),
    }
    for path, want in expected.items():
        got = rect(grid, path, "grid_offset") if path in grid else None
        check(got == want, f"{path} at {want} (got {got})")
    check(all(hasattr(r, "x") and hasattr(r, "h") for r in grid.values()), "every rect is a Rect")

    zero = layout("zero_size_parent")
    check(
        rect(zero, "ZeroSizeParent/Holder/Btn", "zero_size_parent") == (20, 20, 100, 40),
        "a child of a zero-size parent is still reported",
    )

    auto = layout("autosize_padding")
    # Label: 300 wide, text height 32.8 tall: AutomaticSize plus its own UIPadding.
    check(
        # 14px text is a 14px line box (Studio-measured) + 8 + 8 padding.
        rect(auto, "AutosizePadding/Card/Label", "autosize_padding") == (0, 0, 300, 30.0),
        "an autosized label reports its padded height",
    )

    collide = layout("child_name_collision")
    check(
        rect(collide, "ChildNames/Card", "child_name_collision") == (0, 0, 200, 100),
        "a parent with same-named children is laid out from its own Size",
    )

    print("layout dump: ok" if not failures else f"layout dump: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())