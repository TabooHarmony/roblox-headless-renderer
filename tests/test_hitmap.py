#!/usr/bin/env python3
"""Hit-region dump: interactive metadata, hidden capture, and stacking.

Task 2.3 is tested through the real IR -> adapter -> hit-test
path. The fixture has two equal overlapping buttons, with the invisible Active
button on top, plus a TextBox to pin its input flags. The rendered PNG proves
the hidden button is not painted while the hitmap still names it as the target.

Run: python tests/test_hitmap.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
FIXTURE = REPO / "tests" / "fixtures" / "hitmap_overlap.rbxmx"
RHR = [sys.executable, "-m", "rhr"]
OUT = REPO / "out" / "hitmap"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def main() -> int:
    from rhr.hitmap import build_hitmap, dump_json
    from test_fixtures import emit_ir

    OUT.mkdir(parents=True, exist_ok=True)
    ir = emit_ir(FIXTURE)
    hitmap = build_hitmap(ir, 400, 300)
    by_path = {entry["path"]: entry for entry in hitmap["nodes"]}

    expected_paths = {
        "HitMap/Root/VisibleBottom",
        "HitMap/Root/InvisibleTop",
        "HitMap/Root/Input",
    }
    check(set(by_path) == expected_paths, f"all interactive nodes are listed ({sorted(by_path)})")

    hidden = by_path["HitMap/Root/InvisibleTop"]
    check(hidden["visible"] is False, "the top button is reported invisible")
    check(hidden["active"] is True and hidden["capturesClicks"] is True,
          "invisible Active remains a click-capturing node")
    check(hidden["activatedTargetCandidate"] is True,
          "an Active TextButton is an Activated target candidate")

    bottom = by_path["HitMap/Root/VisibleBottom"]
    bottom_rect = bottom.get("rect")
    hidden_rect = hidden.get("rect")
    check(
        bottom["visible"] is True and bottom_rect is not None and bottom_rect == hidden_rect,
        f"the overlapping buttons have the same resolved rect ({bottom_rect})",
    )

    textbox = by_path["HitMap/Root/Input"]
    check(textbox["textEditable"] is True and textbox["clearTextOnFocus"] is False,
          "TextBox editing flags are reported")

    overlap = next(
        probe for probe in hitmap["hitTests"]
        if probe["point"] == {"x": 100.0, "y": 60.0}
    )
    check(
        overlap["stack"][:2] == [
            "HitMap/Root/InvisibleTop",
            "HitMap/Root/VisibleBottom",
        ],
        f"the overlap stack is topmost first ({overlap['stack']})",
    )
    check(
        overlap["target"] == "HitMap/Root/InvisibleTop"
        and overlap["targetVisible"] is False,
        f"the invisible top button is the reported click target ({overlap})",
    )

    # The renderer still paints only the visible lower button. This guards
    # against implementing the input overlay by mutating render visibility.
    from rhr.pipeline import render_ir
    from PIL import Image

    png = OUT / "hitmap_overlap.png"
    render_ir(ir, png, 400, 300, bg_color=(0, 0, 0, 0))
    with Image.open(png) as image:
        pixel = image.convert("RGBA").getpixel((25, 25))
    check(pixel[:3] == (255, 0, 0) and pixel[3] > 0,
          f"the hidden top button is not painted over the visible red button ({pixel})")

    # CLI contract: JSON is stable and diagnostics stay on stderr.
    cli_out = OUT / "hitmap_cli.json"
    proc = subprocess.run(
        [*RHR, "hitmap", str(FIXTURE), "--viewport", "400x300", "--out", str(cli_out)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=300,
    )
    check(proc.returncode == 0, f"rhr hitmap exits 0 ({proc.stderr.strip()[-120:]})")
    cli_data = json.loads(cli_out.read_text()) if cli_out.exists() else {}
    check(cli_data == json.loads(dump_json(hitmap)), "CLI output matches the library dump")
    check("hitmap 3 interactive nodes, 2 probe points" in proc.stderr,
          "CLI reports node and probe counts on stderr")

    # The canonical serialisation must not change between two builds.
    check(dump_json(hitmap) == dump_json(build_hitmap(ir, 400, 300)),
          "two hitmap builds are byte-identical")

    # Renderer/hitmap parity on a centered grid: the grid block is centered as a
    # whole and the short second row starts at the block's left edge, as in Studio.
    # Duplicate names are intentional, so compare the geometric multiset.
    grid_ir = emit_ir(REPO / "tests" / "fixtures" / "centered_grid_buttons.rbxmx")
    from rhr.hitmap import _paint_entries
    from rhr.ir import load_ir
    from rhr.pipeline import load_screens
    screens = load_screens(grid_ir, 400, 300)
    entries = _paint_entries(load_ir(grid_ir)["roots"][0], screens[0][1])
    grid_x = sorted(
        round(float(getattr(rect, "x")), 3)
        for node, rect in entries
        # Same-named cells are indexed (`Rare[1]`, `Rare[2]`); match any index.
        if re.fullmatch(r"Shop/Parts/(Mythic|Legendary|Epic|Common|Rare)(\[\d+\])?",
                        node.get("_path") or "")
        if node.get("type") == "TextButton"
    )
    check(
        grid_x == [85.0, 85.0, 145.0, 145.0, 205.0, 265.0],
        f"centered grid traversal matches the layout pass ({grid_x})",
    )

    print("hitmap: ok" if not failures else f"hitmap: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
