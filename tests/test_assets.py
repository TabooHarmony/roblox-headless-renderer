#!/usr/bin/env python3
"""Asset-path checks: an ImageLabel only paints when its asset is in the icon cache.

Two things are asserted, both from real renders:
  * our IR keeps the asset reference (`Image`) on the node. The Lune bridge cannot
    read the legacy ContentId property, so the emitter reads the renamed
    `ImageContent` and reports it as `Image`; if that regression returns, images
    silently disappear again and this check fails.
  * the renderer paints that image from `<rhr cache>/cache/icons/<id>.png`, i.e. the
    location `rhr fetch` fills. The same render without the cache must
    paint nothing red, so a pass cannot come from some other element.

Run: python tests/test_assets.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

ASSET_ID = "900000001"
FIXTURE = REPO / "tests" / "fixtures" / "image_asset.rbxmx"
VIEWPORT = (400, 300)
RED = (255, 0, 0)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def emit_ir() -> Path:
    from rhr.ir import emit_ir as emit

    return emit(FIXTURE, REPO / "out" / "ir" / "image_asset.json")


def find_node(node: dict, name: str) -> dict | None:
    props = node.get("props") or node.get("properties") or {}
    if node.get("name") == name:
        return props
    for child in node.get("children") or []:
        found = find_node(child, name)
        if found is not None:
            return found
    return None


def image_node_props(ir_path: Path) -> dict:
    ir = json.loads(ir_path.read_text())
    roots = ir["roots"] if isinstance(ir, dict) and "roots" in ir else ir
    for root in roots:
        props = find_node(root, "Avatar")
        if props is not None:
            return props
    raise AssertionError("Avatar node missing from the IR")


def red_pixels(png: Path):
    import numpy as np
    from PIL import Image

    img = np.asarray(Image.open(png).convert("RGBA")).astype(int)
    mask = (np.abs(img[..., :3] - np.array(RED)).max(axis=2) <= 8) & (img[..., 3] > 200)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0, None
    return int(mask.sum()), (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def main() -> int:
    from rhr.pipeline import ICONS_DIR, render_ir

    ir_path = emit_ir()
    props = image_node_props(ir_path)
    check(
        "IR keeps the asset reference",
        props.get("Image") == f"rbxassetid://{ASSET_ID}",
        f"Image={props.get('Image')!r}",
    )

    # the cache the renderer reads must be the cache `rhr fetch` fills, and it
    # must live in the per-user cache, outside the package and the vendored tree
    from ui_engine.assets import _asset_cache_dir

    from rhr import paths

    cache_dir = _asset_cache_dir(ICONS_DIR)
    check(
        "icon root is <cache>/icon_library",
        ICONS_DIR == paths.CACHE / "icon_library",
        str(ICONS_DIR),
    )
    check(
        "asset cache resolves to rhr.paths.ICON_CACHE",
        cache_dir == paths.ICON_CACHE,
        str(cache_dir),
    )
    check(
        "asset cache is outside the package",
        paths.PACKAGE not in cache_dir.parents,
        str(cache_dir),
    )

    from rhr import fetch

    check(
        "rhr fetch writes to the renderer's icon root",
        fetch.ICONS_DIR == ICONS_DIR,
    )
    discovered, _ = fetch.collect_refs({
        "props": {
            "Image": "rbxassetid://41",
            "Texture": "rbxassetid://42",
            "TextureID": "rbxassetid://43",
            "SkyboxBk": "rbxassetid://44",
            "SkyboxUp": "rbxassetid://45",
        },
        "children": [],
    })
    check(
        "rhr fetch discovers world/particle texture IDs in typed IR",
        {"41", "42", "43", "44", "45"}.issubset(discovered),
        repr(sorted(discovered)),
    )

    with tempfile.TemporaryDirectory() as tmp:
        icons = Path(tmp) / "icon_library"
        (icons.parent / "cache" / "icons").mkdir(parents=True)
        # The production icon_library directory may be absent; the sibling cache
        # must still be reachable through the configured icon root.
        from PIL import Image

        Image.new("RGB", (32, 32), RED).save(cache_dir_path(tmp) / f"{ASSET_ID}.png")

        with_asset = REPO / "out" / "fixtures" / "image_asset.png"
        render_ir(ir_path, with_asset, *VIEWPORT, bg_color=(0, 0, 0, 0), icons_dir=icons)
        n, bbox = red_pixels(with_asset)
        check("cached asset paints", n > 0, f"{n}px bbox={bbox}")
        # Relative to the ScreenGui's content area: the inset moves the icon, the
        # ImageLabel's own 8px offset and 32px size are what this check is about.
        from test_fixtures import rel

        rel_bbox = rel(bbox, "image_asset")
        check(
            "painted rect matches Roblox's rules",
            rel_bbox == (8, 8, 39, 39),
            f"expected (8, 8, 39, 39) in the content area, got {rel_bbox}",
        )

        without = REPO / "out" / "fixtures" / "image_asset_no_cache.png"
        render_ir(ir_path, without, *VIEWPORT, bg_color=(0, 0, 0, 0))
        n0, _ = red_pixels(without)
        check("no cache, no image", n0 == 0, f"{n0}px red without a cache")

    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("asset path ok")
    return 0


def cache_dir_path(tmp: str) -> Path:
    return Path(tmp) / "cache" / "icons"


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())