"""Download the assets a model uses into RHR's local cache.

RHR expects the person using it to have Roblox Studio installed and signed in, and
downloads what a render needs as that Studio user by default: `rhr scene` and
`rhr preview` fetch whatever is missing before they draw (`ensure`), and
`rhr fetch` does the same on its own. Only missing assets are requested; what is
cached is never downloaded again, and an asset Roblox refused is not asked for
again for a day.

What is fetched, and where it goes (<rhr cache>/cache/...):

    icons/<id>.png       images (decals, textures, UI images, sky faces). The original
                         file with a Studio login; else a thumbnail of at most 420 px
                         from Roblox's thumbnail service, which needs no sign-in
    meshes/<id>.mesh     MeshPart and FileMesh meshes
    unions/<id>.json     union (CSG) render meshes, decoded (rhr.unions)
    materials/<id>.png   Roblox's own texture maps for the built-in materials, by the
                         asset ids Roblox publishes (scene/roblox_materials.json)

The signed-in download runs a Lune script (luau/fetch-signed-in.luau) that reads
Studio's saved login and sends it only to Roblox's asset delivery, the same request
Studio makes to show the asset; RHR never sees, prints or stores the login. Without
a login, images fall back to thumbnails and the rest are reported missing: meshes
draw as boxes, unions as their bounding boxes, materials as look-alike textures.

`RHR_OFFLINE=1` (or `--offline`) never touches the network; tests set it.
`rhr fetch --no-studio-login` fetches only what Roblox serves without signing in.
Only fetch assets you have the right to use.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rhr.paths import CACHE, ICON_CACHE, ICONS_DIR, MATERIAL_CACHE, MESH_CACHE, PACKAGE, UNION_CACHE

IMAGE_PROPERTIES = {
    "Image", "HoverImage", "PressedImage", "Texture", "TextureID", "TextureId",
    "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
    "MoonTextureId", "SunTextureId", "ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap",
}
MATERIAL_TABLE = PACKAGE / "scene" / "roblox_materials.json"
FAILURES = CACHE / "cache" / "fetch_failures.json"
ORIGINALS = CACHE / "cache" / "icons_original.json"
RETRY_AFTER = 24 * 3600
NO_LOGIN_RECHECK = 10 * 60
SIGNED_IN_BATCH = 40
SIGNED_IN_WORKERS = 4

__all__ = ["asset_id", "collect_refs", "collect_scene_refs", "ensure", "run", "ICONS_DIR"]


def offline() -> bool:
    return os.environ.get("RHR_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}


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


def _nodes(ir: dict):
    def visit(node):
        if isinstance(node, dict):
            if "className" in node or "props" in node or "properties" in node:
                yield node
            for child in node.values():
                yield from visit(child)
        elif isinstance(node, list):
            for child in node:
                yield from visit(child)

    yield from visit(ir.get("roots", ir) if "className" not in ir and "props" not in ir else ir)


def collect_refs(ir: dict) -> tuple[set[str], set[str]]:
    """(image ids, mesh ids) referenced anywhere in an RHR IR."""
    images: set[str] = set()
    meshes: set[str] = set()
    for node in _nodes(ir):
        props = node.get("props") or node.get("properties") or {}
        if not isinstance(props, dict):
            continue
        for key, value in props.items():
            if key in IMAGE_PROPERTIES and isinstance(value, str):
                ref = asset_id(value)
                if ref:
                    images.add(ref)
        cls = node.get("className")
        if cls == "MeshPart" or (cls == "SpecialMesh" and _prop_value(props.get("MeshType")) == "FileMesh"):
            ref = asset_id(props.get("MeshId"))
            if ref:
                meshes.add(ref)
    return images, meshes


def uses_2022_materials(ir: dict) -> bool:
    """Whether parts and terrain use Roblox's current material textures.

    A place saves MaterialService.Use2022Materials (as Use2022MaterialsXml); a place
    that never turned it on keeps the pre-2022 set. A model file has no
    MaterialService and lands in whatever place uses it: today that is the current set.
    """
    services = [n for n in _nodes(ir) if n.get("className") == "MaterialService"]
    places = any(n.get("className") in ("Lighting", "Workspace") for n in _nodes(ir))
    if services:
        props = services[0].get("props") or {}
        return bool(props.get("Use2022MaterialsXml", props.get("Use2022Materials", False)))
    return not places


def material_maps(ir: dict, terrain_materials: set[str] = frozenset()) -> dict[str, dict]:
    """Material name -> its Roblox texture map ids (parts), for the materials `ir` uses.

    Terrain materials are listed under "terrain:<Name>" with a {face: maps} value.
    """
    try:
        table = json.loads(MATERIAL_TABLE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    current = uses_2022_materials(ir)
    parts = table["parts"] if current else {**table["parts"], **table["partsLegacy"]}
    terrain = table["terrain"] if current else {**table["terrain"], **table["terrainLegacy"]}
    used: set[str] = set()
    for node in _nodes(ir):
        if node.get("className") in ("Part", "WedgePart", "CornerWedgePart", "MeshPart", "UnionOperation", "TrussPart"):
            if node.get("className") == "MeshPart" and any(
                child.get("className") == "SurfaceAppearance" for child in _children(node)
            ):
                continue
            used.add(_prop_value((node.get("props") or {}).get("Material")) or "Plastic")
    maps: dict[str, dict] = {name: parts[name] for name in used if parts.get(name)}
    for name in terrain_materials:
        if terrain.get(name):
            maps[f"terrain:{name}"] = terrain[name]
    return maps


def _children(node: dict) -> list[dict]:
    children = node.get("children") or {}
    return list(children.values()) if isinstance(children, dict) else list(children)


def _map_ids(maps: dict[str, dict]) -> set[str]:
    ids: set[str] = set()
    for name, entry in maps.items():
        faces = entry.values() if name.startswith("terrain:") else [entry]
        for face in faces:
            ids.update(v for v in face.values() if v)
    return ids


def terrain_materials(ir: dict) -> set[str]:
    source = ir.get("sourcePath")
    if not source or not any(n.get("className") == "Terrain" for n in _nodes(ir)):
        return set()
    try:
        from rhr.terrain import used_materials

        return used_materials(Path(source))
    except (OSError, ValueError):
        return set()


def collect_scene_refs(ir: dict) -> dict[str, set[str]]:
    """Everything a 3D render of `ir` can use: images, meshes, unions, material maps."""
    images, meshes = collect_refs(ir)
    unions: set[str] = set()
    for node in _nodes(ir):
        if node.get("className") == "UnionOperation":
            ref = asset_id((node.get("props") or {}).get("AssetId"))
            if ref:
                unions.add(ref)
    materials = _map_ids(material_maps(ir, terrain_materials(ir)))
    return {"images": images, "meshes": meshes, "unions": unions, "materials": materials}


# -- the cache -------------------------------------------------------------------

def _destination(kind: str, asset: str) -> Path:
    return {
        "images": ICON_CACHE / f"{asset}.png",
        "meshes": MESH_CACHE / f"{asset}.mesh",
        "unions": UNION_CACHE / f"{asset}.json",
        "materials": MATERIAL_CACHE / f"{asset}.png",
    }[kind]


# Roblox's thumbnail service answers an image it will not show (deleted, private,
# moderated) with a grey "image unavailable" icon on white, marked Completed like any
# other. Drawn as a texture it becomes a white square; Studio draws nothing there.
UNAVAILABLE_THUMBNAILS = {"e5bef3179d5ce82a42fdc8ddc83a2ba9"}


def _is_unavailable(path: Path) -> bool:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest() in UNAVAILABLE_THUMBNAILS
    except OSError:
        return False


def _cached(kind: str, asset: str) -> bool:
    path = _destination(kind, asset)
    if not (path.is_file() and path.stat().st_size > 0):
        return False
    if kind == "images" and _is_unavailable(path):
        path.unlink(missing_ok=True)  # a placeholder cached by an earlier RHR
        return False
    return True


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _write(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)


def _store(kind: str, asset: str, payload: bytes) -> str:
    """Validate and write one downloaded asset; 'fetched' or 'missing (why)'."""
    destination = _destination(kind, asset)
    if kind == "meshes":
        return _store_mesh(payload, destination)
    if kind == "unions":
        from rhr import unions

        try:
            mesh = unions.decode(unions.mesh_from_asset(payload))
        except unions.UnionFormatError as exc:
            return f"missing ({exc})"
        _write(destination, json.dumps(unions.to_payload(mesh)).encode())
        return "fetched"
    # images and material maps: stored as PNG whatever Roblox served
    try:
        from io import BytesIO

        from PIL import Image

        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            with Image.open(BytesIO(payload)) as image:
                image.verify()
            _write(destination, payload)
        else:
            with Image.open(BytesIO(payload)) as image:
                buffer = BytesIO()
                image.save(buffer, "PNG")
            _write(destination, buffer.getvalue())
    except Exception as exc:  # noqa: BLE001 - any undecodable payload is just "not an image"
        return f"missing (not an image: {type(exc).__name__})"
    return "fetched"


def _store_mesh(payload: bytes, destination: Path) -> str:
    try:
        raw = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
    except (gzip.BadGzipFile, EOFError) as exc:
        return f"missing (invalid gzip: {exc})"
    if not raw.startswith(b"version "):
        return f"missing (not a Roblox mesh: {raw[:16]!r})"
    _write(destination, raw)
    return "fetched"


# -- downloads -------------------------------------------------------------------

def _public(asset: str, *, timeout: float = 20.0) -> bytes | str:
    url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset}"
    request = urllib.request.Request(url, headers={"User-Agent": "roblox-headless-renderer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return f"missing (Roblox serves this asset only to a signed-in account: HTTP {exc.code})"
        return f"missing (HTTP {exc.code})"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"missing ({exc})"


_NO_LOGIN = "missing (no Roblox Studio login found on this machine)"


def signed_in(ids: list[str]) -> dict[str, bytes | str]:
    """Download assets as the Roblox Studio user on this machine: id -> bytes or 'missing (...)'."""
    import subprocess
    import tempfile

    from rhr.ir import lune_executable

    if not ids:
        return {}
    script = PACKAGE / "luau" / "fetch-signed-in.luau"
    results: dict[str, bytes | str] = {}
    try:
        lune = lune_executable()
    except (RuntimeError, OSError) as exc:
        return {i: f"missing (signed-in download needs Lune: {exc})" for i in ids}

    with tempfile.TemporaryDirectory(prefix="rhr-signed-in-") as directory:
        def batch(chunk: list[str]) -> dict[str, bytes | str]:
            out: dict[str, bytes | str] = {}
            try:
                proc = subprocess.run([lune, "run", str(script), directory, *chunk], capture_output=True,
                                      text=True, timeout=600, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {i: f"missing (signed in: {exc})" for i in chunk}
            if proc.stdout.strip() == "nologin":
                return {i: _NO_LOGIN for i in chunk}
            for line in proc.stdout.splitlines():
                asset, _, status = line.partition(" ")
                if status == "ok":
                    path = Path(directory) / f"{asset}.bin"
                    out[asset] = path.read_bytes()
                    path.unlink(missing_ok=True)
                elif asset:
                    out[asset] = f"missing (signed in: {status})"
            return out

        chunks = [ids[start:start + SIGNED_IN_BATCH] for start in range(0, len(ids), SIGNED_IN_BATCH)]
        # The first batch alone: without a login the rest need not start.
        first = batch(chunks[0])
        results.update(first)
        if any(value == _NO_LOGIN for value in first.values()):
            return {i: _NO_LOGIN for i in ids}
        with ThreadPoolExecutor(max_workers=SIGNED_IN_WORKERS) as executor:
            for result in executor.map(batch, chunks[1:]):
                results.update(result)
    return {i: results.get(i, "missing (signed in: no answer)") for i in ids}


def _thumbnails(ids: set[str], log) -> dict[str, str]:
    """Images from Roblox's thumbnail service (no sign-in, at most 420 px)."""
    from rhr import pipeline  # noqa: F401  (puts the vendored engine on sys.path)
    from ui_engine.asset_fetcher import fetch_icons
    from ui_engine.assets import _asset_cache_dir

    cache_dir = _asset_cache_dir(ICONS_DIR)
    for message in fetch_icons(ids, cache_dir):
        log(f"  {message}")
    results = {}
    for asset in ids:
        path = cache_dir / f"{asset}.png"
        if path.is_file() and _is_unavailable(path):
            path.unlink(missing_ok=True)
            results[asset] = "missing (Roblox shows it as unavailable)"
        else:
            results[asset] = "fetched" if path.is_file() else "missing (no thumbnail)"
    return results


def ensure(refs: dict[str, set[str]], *, login: bool = True, log=None) -> dict[str, dict[str, str]]:
    """Fetch every asset in `refs` that is not cached yet. kind -> {id: status}.

    status is 'cached', 'fetched' or 'missing (why)'. Assets Roblox refused in the
    last day are skipped ('missing (...)' from the record) rather than asked again.
    """
    log = log or (lambda message: None)
    failures = _load_json(FAILURES)
    originals = _load_json(ORIGINALS)
    now = time.time()
    if login and now - failures.get("login", {}).get("time", 0) < NO_LOGIN_RECHECK:
        login = False  # no Studio login a few minutes ago: do not start Lune for every render
    results: dict[str, dict[str, str]] = {kind: {} for kind in refs}
    wanted: dict[str, list[str]] = {}
    for kind, ids in refs.items():
        for asset in sorted(ids, key=lambda value: (len(value), value)):
            record = failures.get(f"{kind}:{asset}")
            # An image cached as a thumbnail is fetched again as the original once
            # a login can get it (sprite sheets are cut in original-size pixels).
            upgrade = (kind == "images" and login and not originals.get(asset)
                       and now - failures.get(f"original:{asset}", {}).get("time", 0) >= RETRY_AFTER)
            if _cached(kind, asset) and not upgrade:
                results[kind][asset] = "cached"
            elif record and now - record.get("time", 0) < RETRY_AFTER:
                results[kind][asset] = "cached" if _cached(kind, asset) else record.get("status", "missing")
            else:
                wanted.setdefault(kind, []).append(asset)
    if not wanted or offline():
        for kind, ids in wanted.items():
            for asset in ids:
                results[kind][asset] = "cached" if _cached(kind, asset) else "missing (offline)"
        return results

    total = sum(len(ids) for ids in wanted.values())
    log(f"fetch  {total} assets not in the cache yet ("
        + ", ".join(f"{len(ids)} {kind}" for kind, ids in wanted.items()) + ")")

    # Meshes: Roblox serves some without a sign-in; try those first, in parallel.
    need_login: dict[str, list[str]] = {kind: list(ids) for kind, ids in wanted.items()}
    if wanted.get("meshes"):
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_public, asset): asset for asset in wanted["meshes"]}
            still = []
            for future in as_completed(futures):
                asset = futures[future]
                payload = future.result()
                status = _store("meshes", asset, payload) if isinstance(payload, bytes) else payload
                if status == "fetched":
                    results["meshes"][asset] = status
                else:
                    still.append(asset)
            need_login["meshes"] = still

    if login:
        order = [(kind, asset) for kind, ids in need_login.items() for asset in ids]
        downloads = signed_in(sorted({asset for _, asset in order}))
        for kind, asset in order:
            payload = downloads.get(asset, "missing (signed in: no answer)")
            status = _store(kind, asset, payload) if isinstance(payload, bytes) else payload
            if kind == "images" and status == "fetched":
                originals[asset] = True
            if kind == "images" and status != "fetched" and _cached(kind, asset):
                if status != _NO_LOGIN:
                    failures[f"original:{asset}"] = {"status": status, "time": now}
                status = "cached"  # the earlier thumbnail stays
            results[kind][asset] = status
    else:
        for kind, ids in need_login.items():
            for asset in ids:
                results[kind][asset] = ("missing (needs a signed-in account; "
                                        "rhr fetch without --no-studio-login uses the Roblox Studio login)")

    # Images nothing else could get: thumbnails, which need no sign-in.
    thumbs = {a for a, s in results.get("images", {}).items() if s.startswith("missing")}
    if thumbs:
        for asset, status in _thumbnails(thumbs, log).items():
            results["images"][asset] = status

    for kind, statuses in results.items():
        for asset, status in statuses.items():
            key = f"{kind}:{asset}"
            if status.startswith("missing") and "no Roblox Studio login" not in status and "Lune" not in status:
                failures[key] = {"status": status, "time": now}
            else:
                failures.pop(key, None)
    if any(v == _NO_LOGIN for s in results.values() for v in s.values()):
        failures["login"] = {"time": now}
    else:
        failures.pop("login", None)
    _save_json(FAILURES, failures)
    _save_json(ORIGINALS, originals)
    fetched = sum(1 for s in results.values() for v in s.values() if v == "fetched")
    missing = sum(1 for s in results.values() for v in s.values() if v.startswith("missing"))
    log(f"fetch  {fetched} downloaded" + (f", {missing} unavailable" if missing else ""))
    if any(v == _NO_LOGIN for s in results.values() for v in s.values()):
        log("note   no Roblox Studio login found: sign in to Roblox Studio so RHR can download "
            "meshes, unions and Roblox's material textures")
    return results


def ensure_for_ir(ir_path: Path, *, log=None) -> dict[str, dict[str, str]]:
    """`ensure` everything a 3D render of the IR at `ir_path` can use."""
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    return ensure(collect_scene_refs(ir), log=log)


def run(ir_path: Path, *, images: bool = True, meshes: bool = True, studio_login: bool = True) -> int:
    """`rhr fetch`: fetch everything the IR at `ir_path` references; print a summary. Exit code."""
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    refs = collect_scene_refs(ir)
    if not images:
        refs = {k: v for k, v in refs.items() if k != "images"}
    if not meshes:
        refs = {k: v for k, v in refs.items() if k == "images"}
    say = lambda message: print(message, file=sys.stderr)  # noqa: E731
    for kind, ids in refs.items():
        say(f"{kind:<9} {len(ids)} referenced")
    results = ensure(refs, login=studio_login, log=say)
    missing = 0
    for kind in refs:
        gone = sorted((a for a, s in results[kind].items() if s.startswith("missing")), key=lambda v: (len(v), v))
        missing += len(gone)
        for asset in gone[:20]:
            say(f"  {kind} {asset}: {results[kind][asset]}")
        if len(gone) > 20:
            say(f"  ... and {len(gone) - 20} more {kind}")
        if refs[kind]:
            say(f"{kind:<9} {len(refs[kind]) - len(gone)}/{len(refs[kind])} in the cache")
    return 1 if missing else 0
