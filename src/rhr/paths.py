"""Where RHR finds its bundled resources and where it writes caches.

Bundled resources (the vendored renderers, the Lune IR script, the browser pages)
live inside the `rhr` package, so an installed copy works without a git checkout.
Everything RHR writes on its own (downloaded images and meshes, intermediate IR)
goes to one per-user cache directory, never into the package or the caller's
working directory:

    <cache>/cache/icons/      image assets, <asset_id>.png
    <cache>/cache/meshes/     mesh assets, <asset_id>.mesh
    <cache>/cache/particles/  particle textures
    <cache>/cache/unions/     decoded union (CSG) meshes, <asset_id>.json
    <cache>/cache/materials/  Roblox's material texture maps, <asset_id>.png
    <cache>/cache/studio/     PNGs converted from the local Roblox Studio install
    <cache>/icon_library/     the 2D engine's icon root (its cache is ../cache/icons)
    <cache>/ir/               intermediate IR JSON from .rbxm/.rbxl conversions

`RHR_CACHE_DIR` overrides the cache location.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
VENDOR = PACKAGE / "vendor"
PINEVEX = VENDOR / "pinevex"
LUAU_IR_SCRIPT = PACKAGE / "luau" / "rhr-ir.luau"
# Open-license copies of the font builds Roblox ships (see fonts/OFL.txt).
FONTS = PACKAGE / "fonts"


def _default_cache() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "rhr" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "rhr"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "rhr"


CACHE = Path(os.environ["RHR_CACHE_DIR"]).expanduser() if os.environ.get("RHR_CACHE_DIR") else _default_cache()
ICONS_DIR = CACHE / "icon_library"
ICON_CACHE = CACHE / "cache" / "icons"
MESH_CACHE = CACHE / "cache" / "meshes"
PARTICLE_CACHE = CACHE / "cache" / "particles"
UNION_CACHE = CACHE / "cache" / "unions"
MATERIAL_CACHE = CACHE / "cache" / "materials"
IR_DIR = CACHE / "ir"


def roblox_font_dirs() -> list[Path]:
    """Font folders of a local Roblox/Studio install, newest first; [] when none.

    Roblox's own faces (Builder Sans, which now draws Gotham text, and Roblox's
    builds of the open fonts) measure closer to Studio than bundled substitutes,
    but they are not redistributable, so RHR only uses an install already on the
    machine. `RHR_ROBLOX_FONTS` overrides the search: a path list, or 0 to disable.
    """
    configured = os.environ.get("RHR_ROBLOX_FONTS")
    if configured is not None:
        if configured.strip().lower() in {"", "0", "false", "no", "off"}:
            return []
        return [Path(part) for part in configured.split(os.pathsep) if part.strip()]
    candidates: list[Path] = []
    if sys.platform == "win32":
        versions = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Roblox" / "Versions"
        if versions.is_dir():
            candidates.extend(version / "content" / "fonts" for version in versions.iterdir())
    elif sys.platform == "darwin":
        candidates.extend(
            Path(app) / "Contents" / "Resources" / "content" / "fonts"
            for app in ("/Applications/RobloxStudio.app", "/Applications/Roblox.app")
        )
    found = [path for path in candidates if (path / "BuilderSans-Regular.otf").is_file()]
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)[:1]
