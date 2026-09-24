"""Roblox Studio on this machine: where it is installed, and what RHR reads from it.

RHR expects the person using it to have Roblox Studio installed and signed in, and
uses both by default:

- the install's own textures (the default sky, Plastic's surface detail), converted
  once into RHR's cache as PNGs (`studio_textures`);
- the Studio login, to download the assets a scene needs (rhr.fetch).

Nothing from the install is copied into RHR itself. Without Studio every command
still works, with look-alike textures and a note on stderr saying the result will
look less like Roblox.

`RHR_STUDIO_DIR` points at an install (the folder holding PlatformContent), or `0`
turns the install off; tests set `0` so results do not depend on the machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rhr.paths import CACHE

STUDIO_TEXTURES = CACHE / "cache" / "studio"

# Output name -> path inside the install's PlatformContent/pc/textures.
_SKY_FACES = {f"sky_{face}": f"sky/sky512_{face}.tex" for face in ("bk", "dn", "ft", "lf", "rt", "up")}
_TEXTURES = {**_SKY_FACES, "plastic_normaldetail": "plastic/normaldetail.dds"}
# Legacy part surfaces: studs.dds is a strip of 128 px tiles, 2x2 studs each, a grey
# detail the part colour is multiplied by. Tile index per SurfaceType.
_SURFACE_TILES = {"surface_studs": 0, "surface_weld": 4, "surface_inlet": 8, "surface_universal": 12}


def _disabled(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"", "0", "false", "no", "off"}


def studio_install() -> Path | None:
    """The newest Roblox Studio install on this machine (its content root), or None."""
    configured = os.environ.get("RHR_STUDIO_DIR")
    if configured is not None:
        if _disabled(configured):
            return None
        path = Path(configured).expanduser()
        return path if (path / "PlatformContent").is_dir() else None
    candidates: list[Path] = []
    if sys.platform == "win32":
        versions = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Roblox" / "Versions"
        if versions.is_dir():
            candidates.extend(v for v in versions.iterdir() if (v / "RobloxStudioBeta.exe").is_file())
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/RobloxStudio.app/Contents/Resources"))
    found = [c for c in candidates if (c / "PlatformContent" / "pc" / "textures").is_dir()]
    if not found:
        return None
    return max(found, key=lambda path: (path / "PlatformContent").stat().st_mtime)


def studio_textures() -> dict[str, Path]:
    """Name -> PNG in RHR's cache, converted from the Studio install; {} without one.

    Names: sky_bk/dn/ft/lf/rt/up (Roblox's default sky, used when a place has no
    Sky of its own) and plastic_normaldetail (Plastic's fine surface relief).
    """
    install = studio_install()
    if install is None:
        return {}
    source_root = install / "PlatformContent" / "pc" / "textures"
    target = STUDIO_TEXTURES / install.name
    out: dict[str, Path] = {}
    for name, relative in _TEXTURES.items():
        destination = target / f"{name}.png"
        if not destination.is_file():
            source = source_root / relative
            if not source.is_file():
                continue
            try:
                _convert(source, destination)
            except (OSError, ValueError):
                continue
        out[name] = destination
    studs = source_root / "studs.dds"
    for name, tile in _SURFACE_TILES.items():
        destination = target / f"{name}.png"
        if not destination.is_file() and studs.is_file():
            try:
                _crop_tile(studs, tile, destination)
            except (OSError, ValueError):
                continue
        if destination.is_file():
            out[name] = destination
    return out


def terrain_base_colors() -> dict[str, list[int]]:
    """Terrain material -> the colour Roblox multiplies its terrain texture by.

    From the install's materials2022.json; a place's Terrain.MaterialColors scales it
    by its ratio to the default colour (rhr.terrain.DEFAULT_MATERIAL_COLORS).
    """
    import json

    install = studio_install()
    if install is None:
        return {}
    try:
        data = json.loads((install / "PlatformContent" / "pc" / "terrain" / "materials2022.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {m["name"]: m["base_color"] for m in data.get("materials", []) if "base_color" in m}


def _crop_tile(source: Path, tile: int, destination: Path) -> None:
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.load()
        size = image.width
        image.crop((0, tile * size, size, (tile + 1) * size)).convert("RGB").save(destination)


def _convert(source: Path, destination: Path) -> None:
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.png")
    with Image.open(source) as image:
        image.load()
        if destination.stem.endswith("normaldetail"):
            image = _unpack_normal(image)
        image.save(temporary)
    temporary.replace(destination)


def _unpack_normal(image):
    """A two-channel normal map (X in alpha, Y in green) as an ordinary RGB normal map."""
    import numpy as np
    from PIL import Image

    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    x = rgba[..., 3] * 2 - 1
    y = rgba[..., 1] * 2 - 1
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
    rgb = np.stack([x, y, z], axis=-1) * 0.5 + 0.5
    return Image.fromarray((rgb * 255 + 0.5).astype(np.uint8), "RGB")
