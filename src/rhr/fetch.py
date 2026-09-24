"""`rhr fetch`: download the images and meshes a model uses into RHR's local cache.

Rendering never touches the network; this is the one explicit step that does. It
reads the model (or its IR), collects image asset ids (ImageLabel/ImageButton
images, Decals, Textures, Sky faces, particle and beam textures) and mesh ids
(MeshPart, SpecialMesh FileMesh), and fills:

    <rhr cache>/cache/icons/<asset_id>.png    images, via Roblox's thumbnail service
    <rhr cache>/cache/meshes/<asset_id>.mesh  meshes, via Roblox's asset delivery

Images come from the thumbnail service, which needs no sign-in but serves a
thumbnail (up to 420 px) rather than the original file. Roblox's asset delivery
serves some meshes only to a signed-in account; those are reported, not guessed.
Only fetch assets you have the right to use.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rhr.paths import ICONS_DIR, MESH_CACHE

IMAGE_PROPERTIES = {
    "Image", "HoverImage", "PressedImage", "Texture", "TextureID", "TextureId",
    "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
    "MoonTextureId", "SunTextureId", "ColorMap",
}


def asset_id(value) -> str | None:
    text = str(value or "")
    for pattern in (r"rbxassetid://(\d+)", r"[?&]id=(\d+)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if text.startswith(("rbxasset://", "rbxthumb://")):
        return None  # built into the client, or a thumbnail URL: not an asset id
    matches = re.findall(r"(\d{3,})", text)
    return matches[-1] if matches else None


def _prop_value(value):
    return value.get("name") if isinstance(value, dict) and "name" in value else value


def collect_refs(ir: dict) -> tuple[set[str], set[str]]:
    """(image ids, mesh ids) referenced anywhere in an RHR IR."""
    images: set[str] = set()
    meshes: set[str] = set()

    def visit(node) -> None:
        if isinstance(node, dict):
            props = node.get("props") or node.get("properties") or {}
            if isinstance(props, dict):
                for key, value in props.items():
                    if key in IMAGE_PROPERTIES and isinstance(value, str):
                        ref = asset_id(value)
                        if ref:
                            images.add(ref)
                cls = node.get("className")
                if cls == "MeshPart" or (cls == "SpecialMesh"
                                         and _prop_value(props.get("MeshType")) == "FileMesh"):
                    ref = asset_id(props.get("MeshId"))
                    if ref:
                        meshes.add(ref)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(ir)
    return images, meshes


def fetch_images(ids: set[str], log=print) -> dict[str, str]:
    """Fetch images with the vendored engine's own fetcher, into the cache it reads."""
    from rhr import pipeline  # noqa: F401  (puts the vendored engine on sys.path)
    from ui_engine.asset_fetcher import fetch_icons
    from ui_engine.assets import _asset_cache_dir

    cache_dir = _asset_cache_dir(ICONS_DIR)
    for message in fetch_icons(ids, cache_dir):
        log(f"  {message}")
    have = {p.stem for p in cache_dir.glob("*.png")}
    return {i: ("cached" if i in have else "missing") for i in ids}


def fetch_mesh(asset: str, cache_dir: Path = MESH_CACHE, *, timeout: float = 20.0) -> str:
    destination = cache_dir / f"{asset}.mesh"
    if destination.is_file() and destination.stat().st_size:
        return "cached"
    url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset}"
    request = urllib.request.Request(url, headers={"User-Agent": "roblox-headless-renderer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return f"missing (Roblox serves this asset only to a signed-in account: HTTP {exc.code})"
        return f"missing (HTTP {exc.code})"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"missing ({exc})"
    try:
        raw = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
    except (gzip.BadGzipFile, EOFError) as exc:
        return f"missing (invalid gzip: {exc})"
    if not raw.startswith(b"version "):
        return f"missing (not a Roblox mesh: {raw[:16]!r})"
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".mesh.tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return "fetched"


def fetch_meshes(ids: set[str], cache_dir: Path = MESH_CACHE) -> dict[str, str]:
    if not ids:
        return {}
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as executor:
        futures = {executor.submit(fetch_mesh, i, cache_dir): i for i in ids}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results


def run(ir_path: Path, *, images: bool = True, meshes: bool = True) -> int:
    """Fetch everything the IR at `ir_path` references; print a summary. Exit code."""
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    image_ids, mesh_ids = collect_refs(ir)
    missing = 0
    if images:
        print(f"images  {len(image_ids)} referenced", file=sys.stderr)
        if image_ids:
            results = fetch_images(image_ids, log=lambda m: print(m, file=sys.stderr))
            gone = sorted(i for i, r in results.items() if r != "cached")
            missing += len(gone)
            print(f"images  {len(image_ids) - len(gone)}/{len(image_ids)} in the cache"
                  + (f"; missing: {', '.join(gone)}" if gone else ""), file=sys.stderr)
    if meshes:
        print(f"meshes  {len(mesh_ids)} referenced", file=sys.stderr)
        results = fetch_meshes(mesh_ids)
        for asset in sorted(results, key=int):
            if results[asset].startswith("missing"):
                print(f"  {asset}: {results[asset]}", file=sys.stderr)
        gone = [a for a, r in results.items() if r.startswith("missing")]
        missing += len(gone)
        if mesh_ids:
            print(f"meshes  {len(mesh_ids) - len(gone)}/{len(mesh_ids)} in the cache", file=sys.stderr)
    return 1 if missing else 0
