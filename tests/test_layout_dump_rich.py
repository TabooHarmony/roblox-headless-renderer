#!/usr/bin/env python3
"""The rich layout dump: what each node is made of, not just where it sits.

Task 2.1: a per-node dump of path, class, rect, zIndex, visible,
resolved background/stroke/gradient colours, text, computed font size and clip
state, written as stable sorted JSON so two builds diff cleanly. Two things are
measured here, not claimed:

  * determinism — the dump is produced twice and byte-compared;
  * pixel agreement — the dump's rects are sampled at the rect centre in the
    PNG the same pass produced, and compared against the colours the dump
    reports (Task 2.1 step 3, five nodes on grid_offset).

Run: python tests/test_layout_dump_rich.py
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
RHR = [sys.executable, "-m", "rhr"]
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "out" / "layout_dump_rich"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def dump_for(fixture: str, png: Path | None = None) -> dict:
    from rhr.layout_dump import build_dump

    from test_fixtures import emit_ir

    return build_dump(
        emit_ir(FIXTURES / f"{fixture}.rbxmx"),
        400,
        300,
        png_path=png or (OUT / f"{fixture}.png"),
    )


def node(dump: dict, path: str) -> dict | None:
    for entry in dump["nodes"]:
        if entry["path"] == path:
            return entry
    return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("layout dump (rich): structure, determinism, pixel agreement")

    # --- grid_offset: the 5-node fixture the plan's step 3 names ----------
    dump = dump_for("grid_offset")
    check(len(dump["nodes"]) == 5, f"grid_offset reports 5 nodes ({len(dump['nodes'])})")
    paths = [n["path"] for n in dump["nodes"]]
    check(paths == sorted(paths), "nodes are sorted by path")
    check(
        paths == [
            "GridOffset/Root",
            "GridOffset/Root/Cell1",
            "GridOffset/Root/Cell2",
            "GridOffset/Root/Cell3",
            "GridOffset/Root/Cell4",
        ],
        f"every node is present under its path ({paths[:2]}...)",
    )
    root = dump["nodes"][0]
    check(root["class"] == "Frame", "the root reports its class")
    check(root["zIndex"] == 1 and root["visible"] is True, "zIndex and visible are reported")
    check(root["rect"] == {"x": 0.0, "y": 58.0, "w": 400.0, "h": 300.0},
          f"the rect is the paint pass's resolved rect ({root['rect']})")
    check(root["background"]["color"] == [255, 255, 255],
          "the root's resolved background is the engine default white")
    cell = node(dump, "GridOffset/Root/Cell1")
    check(cell is not None and cell["background"]["color"] == [255, 0, 0],
          "Cell1's resolved background is red")

    # --- determinism, measured: two builds, byte-compared -----------------
    dump2 = dump_for("grid_offset")
    from rhr.layout_dump import dump_json

    check(
        dump_json(dump) == dump_json(dump2),
        "two builds of the same model dump byte-identical JSON",
    )

    # --- pixel agreement (plan step 3): 5 rect centres vs the PNG ---------
    from rhr.layout_dump import verify_pixels

    png = OUT / "grid_offset.png"
    results = verify_pixels(dump, png)
    for path, ok, detail in results:
        check(ok, f"pixel agrees at {path}'s rect centre ({detail})")
    check(len(results) == 5, f"all 5 nodes were pixel-checked ({len(results)})")
    from PIL import Image

    with Image.open(png) as img:
        r = cell["rect"] if cell else {"x": 0, "y": 0, "w": 0, "h": 0}
        px = img.convert("RGBA").getpixel((int(r["x"] + r["w"] / 2), int(r["y"] + r["h"] / 2)))
    check(px == (255, 0, 0, 255), f"Cell1 really is red at its rect centre ({px})")

    # --- every pane is covered --------------------------------------------
    two = dump_for("two_screen_guis")
    two_paths = {n["path"] for n in two["nodes"]}
    check(
        {"Under/RedPane", "Under/GreenStrip", "Over/BluePane"} <= two_paths,
        f"nodes from both ScreenGui panes are dumped ({sorted(two_paths)})",
    )

    # --- occlusion: verify_pixels skips what a later pane covers ----------
    from rhr.layout_dump import verify_pixels

    occ = verify_pixels(two, OUT / "two_screen_guis.png")
    detail = {path: (ok, why) for path, ok, why in occ}
    over_ok, over_why = detail["Over/BluePane"]
    check(over_ok and "occluded" not in over_why,
          f"the top pane's node is pixel-checked ({over_why})")
    under_ok, under_why = detail["Under/RedPane"]
    check(under_ok and "occluded by" in under_why,
          f"the covered node is skipped as occluded, not failed ({under_why})")

    # --- text: honest about what is resolvable ----------------------------
    scaled = dump_for("textscaled")
    small = node(scaled, "TextScaled/Root/Small")
    fixed = node(scaled, "TextScaled/Root/Fixed")
    check(small is not None and small["text"]["content"] == "SCALE", "the text is dumped")
    check(small["text"]["size"] == 14 and small["text"]["scaled"] is True,
          f"a TextScaled label reports its specified size + flag ({small['text']})")
    check("fitted" not in small["text"], "no invented fitted font size")
    check(fixed["text"]["scaled"] is False, "TextScaled=false survives the dump")

    # --- gradient, stroke, clip: resolved visual state --------------------
    panel = dump_for("panel_styles")
    box = node(panel, "PanelStyles/Box")
    check(box["gradient"]["colors"] == [[0.0, "#ffffff"], [0.5, "#808080"], [1.0, "#0000ff"]],
          f"the gradient's stops are dumped ({box.get('gradient')})")
    check(box["gradient"]["rotation"] == 90.0, "the gradient's rotation is dumped")
    check(box["strokes"] == [{"color": [255, 0, 0], "thickness": 2.0, "transparency": 0.0}],
          f"the stroke is resolved ({box.get('strokes')})")
    check(box["clipsDescendants"] is True, "clip state is reported")
    label = node(panel, "PanelStyles/Box/Label")
    check(label["text"]["color"] == [27, 42, 53], f"the text colour is resolved ({label['text']})")

    panel_png = OUT / "panel_styles.png"
    results = verify_pixels(panel, panel_png, paths=["PanelStyles/Box"])
    path_, ok_, detail_ = results[0]
    # The dump predicts white->blue through (128,128,128) at t=0.5; skia's own
    # shader maths lands within ±1 per channel. Anything beyond that is a real
    # disagreement between dump and pixels. The detail carries the tolerance
    # the checker itself applied ("(±N)"): parse the two RGBA tuples out.
    m = re.search(r"expected \((\d+), (\d+), (\d+), (\d+)\).*got \((\d+), (\d+), (\d+), (\d+)\)", detail_)
    if m:
        want = tuple(int(m.group(i)) for i in range(1, 5))
        got = tuple(int(m.group(i)) for i in range(5, 9))
        close = all(abs(a - b) <= 1 for a, b in zip(want, got))
        check(close, f"the gradient's centre pixel matches the interpolated stop ({detail_})")
    else:
        check(ok_, f"the gradient's centre pixel matches the interpolated stop ({detail_})")
    with Image.open(panel_png) as img:
        r = dump["nodes"][0]["rect"]
        edge = img.convert("RGBA").getpixel((int(r["x"] + r["w"] / 2), int(r["y"]) + 1))
    check(edge[0] >= 200 and edge[1] <= 140 and edge[2] <= 140,
          f"the reported stroke colour agrees with the drawn border ({edge})")

    # --- the CLI: rhr layout --rich ---------------------------------------
    proc = subprocess.run(
        [*RHR, "layout", str(FIXTURES / "grid_offset.rbxmx"), "--viewport", "400x300", "--rich"],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    check(proc.returncode == 0, f"rhr layout --rich exits 0 ({proc.stderr.strip()[-120:] or 'clean'})")
    check(
        any(line.startswith("dump ") and "nodes" in line for line in proc.stderr.splitlines()),
        f"the node count goes to stderr ({proc.stderr.strip()[:60]})",
    )
    cli_dump = None
    try:
        cli_dump = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    check(isinstance(cli_dump, dict) and len(cli_dump.get("nodes", [])) == 5,
          "the dump is valid JSON on stdout")
    if cli_dump is not None:
        check(dump_json(cli_dump) == dump_json(dump),
              "the CLI dump matches the library dump byte for byte")
        proc2 = subprocess.run(
            [*RHR, "layout", str(FIXTURES / "grid_offset.rbxmx"), "--viewport", "400x300", "--rich"],
            capture_output=True, text=True, cwd=str(REPO), timeout=300,
        )
        check(proc2.stdout == proc.stdout, "two CLI runs are byte-identical (determinism)")

    # --- gradient transparency stops: reported, not dropped ----------------
    gt = dump_for("gradient_transparency")
    box = node(gt, "GradT/Box")
    check(box is not None and box["gradient"].get("transparency") == [[0.0, 0.5], [1.0, 0.5]],
          f"the gradient's transparency stops are dumped ({(box or {}).get('gradient')})")
    gt_png = OUT / "gradient_transparency.png"
    gt_results = verify_pixels(gt, gt_png)
    check(len(gt_results) == 1 and gt_results[0][1],
          f"the transparency-carrying gradient's centre pixel agrees ({gt_results})")
    check("±2" in gt_results[0][2],
          f"the transparent fill is held to the premultiplied-space tolerance ({gt_results[0][2]})")

    # --- an empty dump is a pipeline bug: the CLI refuses ------------------
    empty = subprocess.run(
        [*RHR, "layout", str(REPO / "out" / "ir" / "unknown_class_values.json"), "--rich"],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    check(empty.returncode == 1, f"an empty structured dump exits 1 (exit {empty.returncode})")
    check("empty" in empty.stderr, f"the refusal says why on stderr ({empty.stderr.strip()[-80:]})")

    print("layout dump (rich): ok" if not failures else f"layout dump (rich): {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
