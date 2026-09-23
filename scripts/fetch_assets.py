"""Populate the engine's icon cache from the model's asset ids.

Uses the vendored engine's own fetcher (`ui_engine.asset_fetcher.fetch_icons`) and
its own cache location (`ui_engine.assets._asset_cache_dir`), so the images the
renderer looks for are the ones this writes. No new download code.

    rhr ir model.rbxm --out model.json
    python scripts/fetch_assets.py model.json

Writes into <rhr cache>/cache/icons/<asset_id>.png (see rhr.paths) and prints a count. Not a test.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PINEVEX = REPO / "src" / "rhr" / "vendor" / "pinevex"
sys.path.insert(0, str(PINEVEX / "src"))
sys.path.insert(0, str(REPO / "src"))

# Same icon root the pipeline hands the engine, so the cache this fills is the cache
# the renderer reads (rhr.paths.ICON_CACHE).
from rhr.pipeline import ICONS_DIR  # noqa: E402


ASSET_PROPERTY_NAMES = {
    "Image", "HoverImage", "PressedImage", "Texture", "TextureID",
    "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
    "MoonTextureId", "SunTextureId",
}


def _asset_id(value: str) -> str | None:
    for pattern in (r"rbxassetid://(\d+)", r"[?&]id=(\d+)"):
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    matches = re.findall(r"(\d+)", value)
    return matches[-1] if matches else None


def _generic_asset_refs(value) -> set[str]:
    """Collect image-like Roblox content IDs from either our IR or Pinevex JSON."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ASSET_PROPERTY_NAMES and isinstance(child, str):
                found_id = _asset_id(child)
                if found_id:
                    found.add(found_id)
            found.update(_generic_asset_refs(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_generic_asset_refs(child))
    return found


def asset_refs(obj) -> set[str]:
    from ui_engine.asset_fetcher import collect_asset_ids

    # Upstream knows its own normalized GUI object shape. The generic pass adds
    # our typed IR's static-world image surfaces and particle/mesh texture IDs.
    return set(collect_asset_ids(obj)) | _generic_asset_refs(obj)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/fetch_assets.py <ir.json>  (make one with `rhr ir model.rbxm --out ir.json`)",
              file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    obj = json.loads(src.read_text())

    from ui_engine.asset_fetcher import fetch_icons
    from ui_engine.assets import _asset_cache_dir

    cache_dir = _asset_cache_dir(ICONS_DIR)
    ids = asset_refs(obj)
    print(f"cache dir : {cache_dir}")
    print(f"asset ids : {len(ids)}")

    for msg in fetch_icons(ids, cache_dir):
        print("  " + str(msg))

    have = sorted(p.name for p in cache_dir.glob("*.png"))
    print(f"cached    : {len(have)}/{len(ids)}")
    missing = sorted(ids - {Path(n).stem for n in have})
    if missing:
        print("missing   :", ", ".join(missing))
    for n in have:
        print(f"  {n} {(cache_dir / n).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())