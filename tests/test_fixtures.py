#!/usr/bin/env python3
"""Fixture checks: one fixture per vendored fix, failing before and passing after.

Each fixture is hand-written XML in tests/fixtures/ and travels the real path:
lune IR -> adapter -> flatten_node -> renderer. Assertions read the PNG, not
internal state: every element under test has a colour of its own, so the check
compares that colour's bounding box against Roblox's own layout rules. A wrong
rect cannot pass by accident and a dropped child cannot pass at all.

Run: .venv/bin/python tests/test_fixtures.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FIXTURES = REPO / "tests" / "fixtures"
VIEWPORT = (400, 300)

# fixture element colours
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
LABEL = (255, 204, 0)
BUTTON = (0, 102, 255)


def emit_ir(fixture: Path, out: Path | None = None) -> Path:
    """Emit our IR for a .rbxm/.rbxmx/.rbxl model via the in-repo lune script."""
    out = out or REPO / "out" / "ir" / f"{fixture.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["lune", "run", str(REPO / "scripts" / "rhr-ir.luau"), str(fixture), str(out)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"lune failed on {fixture.name}: {proc.stderr.strip()}")
    return out


_ORIGIN_CACHE: dict[str, tuple[int, int]] = {}


def _render(fixture_name: str):
    import numpy as np
    from PIL import Image

    from rhr.pipeline import render_ir

    fixture = FIXTURES / f"{fixture_name}.rbxmx"
    out = REPO / "out" / "fixtures" / f"{fixture_name}.png"
    render_ir(emit_ir(fixture), out, *VIEWPORT, bg_color=(0, 0, 0, 0))
    return np.asarray(Image.open(out).convert("RGBA")).astype(int)


def content_origin(fixture_name: str) -> tuple[int, int]:
    """The fixture ScreenGui's content-area origin: the top bar inset, in px.

    Roblox lays a ScreenGui's children out inside this area, so fixture assertions
    are written relative to it and the absolute inset numbers are pinned once, in
    tests/test_insets.py. A rule test therefore cannot drift with a changed
    constant without that test noticing.
    """
    from rhr.adapter import ir_to_raw_nodes
    from rhr.insets import for_nodes
    from rhr.ir import load_ir

    key = f"origin:{fixture_name}"
    if key in _ORIGIN_CACHE:
        return _ORIGIN_CACHE[key]
    ir = load_ir(emit_ir(FIXTURES / f"{fixture_name}.rbxmx"))
    inset = for_nodes(ir_to_raw_nodes(ir))
    x, y, _, _ = inset.rect(VIEWPORT[0], VIEWPORT[1])
    _ORIGIN_CACHE[key] = (int(round(x)), int(round(y)))
    return _ORIGIN_CACHE[key]


def rel(box, fixture_name: str):
    """A pixel rectangle, expressed inside the fixture's content area."""
    if box is None:
        return None
    ox, oy = content_origin(fixture_name)
    return (box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy)


def _painted_pct(img) -> float:
    return round(100.0 * float((img[..., 3] > 0).mean()), 3)


def _bbox(img, rgb, tol: int = 8):
    """Bounding box of pixels matching a colour, as (x0, y0, x1, y1)."""
    import numpy as np

    mask = (np.abs(img[..., :3] - np.array(rgb)).max(axis=2) <= tol) & (img[..., 3] > 200)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def check_grid_offset() -> str:
    img = _render("grid_offset")
    painted = _painted_pct(img)
    boxes = {name: _bbox(img, rgb) for name, rgb in
             [("Cell1", RED), ("Cell2", GREEN), ("Cell3", BLUE), ("Cell4", YELLOW)]}
    for i, name in enumerate(["Cell1", "Cell2", "Cell3", "Cell4"]):
        expected = (i * 40, 0, i * 40 + 31, 31)
        boxes[name] = rel(boxes[name], "grid_offset")
        assert boxes[name] == expected, (
            f"{name} at {boxes[name]}, expected {expected}"
            + (" (no cell drawn: cellSize offsets dropped)" if boxes[name] is None else "")
        )
    return f"painted {painted}%  " + "  ".join(f"{n}{b}" for n, b in boxes.items())


def check_zero_size_parent() -> str:
    img = _render("zero_size_parent")
    painted = _painted_pct(img)
    box = _bbox(img, BUTTON)
    assert box is not None, f"child of zero-size parent not drawn: painted {painted}%"
    assert rel(box, "zero_size_parent") == (20, 20, 119, 59), (
        f"button at {rel(box, 'zero_size_parent')} in the content area, expected (20, 20, 119, 59)"
    )
    return f"painted {painted}%  button{box}"


def check_autosize_padding() -> str:
    # Text is 14px, one unwrapped line in the vendored heuristic: 14 * 1.2 = 16.8.
    # With UIPadding 8 all round, Roblox grows the box to 16.8 + 8 + 8 = 32.8.
    img = _render("autosize_padding")
    box = _bbox(img, LABEL)
    assert box is not None, "label not drawn at all"
    height = box[3] - box[1] + 1
    assert 32 <= height <= 34, f"label height {height}px, expected ~33 (16.8 text + 16 padding)"
    return f"label{box}  height {height}px"


def check_display_order() -> str:
    # Two ScreenGuis over the same 100x100 rect, the file listing DisplayOrder 0
    # first and 5 second. pinevex renders one root, so plain file order would show
    # the blue pane: the DisplayOrder sort is what makes the red one the pane drawn.
    img = _render("display_order")
    front = rel(_bbox(img, RED), "display_order")
    behind = _bbox(img, BLUE)
    assert front == (0, 0, 99, 99), (
        f"the ScreenGui with DisplayOrder 5 was not the one drawn: red at {front}"
    )
    assert behind is None, f"the ScreenGui with DisplayOrder 0 is visible at {behind}"
    return f"DisplayOrder 5 pane drawn over the 0 pane: red{front}"


CHECKS = [
    ("grid_offset", check_grid_offset),
    ("zero_size_parent", check_zero_size_parent),
    ("autosize_padding", check_autosize_padding),
    ("display_order", check_display_order),
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
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} fixtures pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())