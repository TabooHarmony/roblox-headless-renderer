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

Downloads take two steps: Roblox's asset delivery batch endpoint says where each file
is (a short-lived signed link on its CDN, up to 256 assets per request), then the
files come from the CDN in parallel. The signed-in step runs a Lune script
(luau/fetch-locations.luau) that reads Studio's saved login and sends it only to
Roblox's asset delivery, the same service Studio asks; RHR never sees, prints or
stores the login, only the links. Without a login RHR asks the same endpoint without
signing in: Roblox serves some meshes, images and material textures that way, never
unions or models. Images it still cannot get fall back to thumbnails and the rest are
reported missing: meshes draw as boxes, unions as their bounding boxes, materials as
look-alike textures.

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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rhr.paths import CACHE, ICON_CACHE, ICONS_DIR, MATERIAL_CACHE, MESH_CACHE, PACKAGE, UNION_CACHE

IMAGE_PROPERTIES = {
    "Image", "HoverImage", "PressedImage", "Texture", "TextureID", "TextureId",
    "SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp",
    "MoonTextureId", "SunTextureId", "ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap",
    "ShirtTemplate", "PantsTemplate", "Graphic", "BaseTextureId", "OverlayTextureId",
}
MATERIAL_TABLE = PACKAGE / "scene" / "roblox_materials.json"
FAILURES = CACHE / "cache" / "fetch_failures.json"
ORIGINALS = CACHE / "cache" / "icons_original.json"
RETRY_AFTER = 24 * 3600
NO_LOGIN_RECHECK = 10 * 60

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
    """Every node of an IR (or of one node's subtree), parents first."""
    stack = list(reversed(ir.get("roots") or [])) if "className" not in ir and "props" not in ir else [ir]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        yield node
        children = node.get("children") or ()
        if isinstance(children, dict):
            children = list(children.values())
        stack.extend(reversed(children))


def collect_refs(ir: dict, nodes=None) -> tuple[set[str], set[str]]:
    """(image ids, mesh ids) referenced anywhere in an RHR IR (or in `nodes` of it)."""
    images: set[str] = set()
    meshes: set[str] = set()
    for node in _nodes(ir) if nodes is None else nodes:
        props = node.get("props") or node.get("properties") or {}
        if not isinstance(props, dict):
            continue
        for key, value in props.items():
            # A CharacterMesh's texture ids are plain numbers, not asset URLs.
            if key in IMAGE_PROPERTIES and isinstance(value, (str, int)) and not isinstance(value, bool):
                ref = asset_id(str(value))
                if ref:
                    images.add(ref)
        cls = node.get("className")
        if cls in ("MeshPart", "CharacterMesh") or (
            cls == "SpecialMesh" and _prop_value(props.get("MeshType")) == "FileMesh"
        ):
            ref = asset_id(props.get("MeshId"))
            if ref:
                meshes.add(ref)
        if cls in ("WrapLayer", "WrapTarget"):  # layered clothing cages
            for key in ("CageMeshId", "ReferenceMeshId"):
                ref = asset_id(props.get(key))
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


def scene_refs(ir: dict) -> dict[str, set[str]]:
    """collect_scene_refs, once per loaded IR (rhr.ir.derived)."""
    from rhr.ir import derived

    return derived(ir, "scene_refs", collect_scene_refs)


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


_SUFFIX = {"images": "png", "meshes": "mesh", "unions": "json", "materials": "png"}


def _cached(kind: str, asset: str) -> bool:
    """Whether the cache has a non-empty file for the asset (from the folder listing:
    no stat per asset)."""
    from rhr.listing import listing

    destination = _destination(kind, asset)
    if kind == "images":
        _sweep_placeholders(destination.parent)
    entry = listing(destination.parent).get(_SUFFIX[kind], {}).get(asset)
    return entry is not None and entry[1] > 0


_SWEPT: set[str] = set()


def _sweep_placeholders(folder: Path) -> None:
    """Remove "image unavailable" placeholders an RHR before 0.7 cached as images
    (thumbnails are checked when downloaded since), once per cache folder."""
    if str(folder) in _SWEPT:
        return
    _SWEPT.add(str(folder))
    marker = folder / ".placeholders-swept"
    if marker.exists() or not folder.is_dir():
        return
    for path in folder.glob("*.png"):
        if _is_unavailable(path):
            path.unlink(missing_ok=True)
    try:
        marker.write_text("", encoding="utf-8")
    except OSError:
        pass


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
#
# Two steps. Roblox's asset delivery batch endpoint turns up to 256 asset ids into
# short-lived signed links on its CDN in one request (as the Studio user, or without
# a sign-in for what Roblox serves to anyone); the files then come from the CDN in
# parallel. One asset at a time cost about 0.7 s each (83 assets: 55 s; now 1.6 s).

BATCH_URL = "https://assetdelivery.roblox.com/v2/assets/batch"
BATCH_SIZE = 256  # the endpoint refuses more assets per request
DOWNLOAD_WORKERS = 16
_NO_LOGIN = "missing (no Roblox Studio login found on this machine)"
_USER_AGENT = "roblox-headless-renderer"


def _refused(code: int, message: str, *, signed_in: bool) -> str:
    if signed_in:
        return f"missing (signed in: HTTP {code}: {message})" if code else f"missing (signed in: {message})"
    if code in (401, 403):
        return f"missing (Roblox serves this asset only to a signed-in account: HTTP {code})"
    return f"missing (HTTP {code}: {message})" if code else f"missing ({message})"


def _locations(answers: dict, ids: list[str], *, signed_in: bool) -> dict[str, str]:
    """id -> CDN link ('https://...') or 'missing (why)', from the batch answers."""
    out = {}
    for asset in ids:
        answer = answers.get(asset) or {}
        location = answer.get("location")
        if isinstance(location, str) and location.startswith("https://"):
            out[asset] = location
        else:
            out[asset] = _refused(int(answer.get("code") or 0), str(answer.get("message") or "no answer"),
                                  signed_in=signed_in)
    return out


def locate_public(ids: list[str], *, timeout: float = 30.0) -> dict[str, str]:
    """Where to download each asset without a sign-in: id -> link or 'missing (why)'."""
    return _locations(answers_public(ids, timeout=timeout), ids, signed_in=False)


def answers_public(ids: list[str], *, timeout: float = 30.0) -> dict[str, dict]:
    """The batch endpoint's answers without a sign-in: id -> {location, type} or {code, message}."""
    def ask(chunk: list[str]) -> dict:
        body = json.dumps([{"assetId": int(i), "requestId": i} for i in chunk]).encode()
        request = urllib.request.Request(BATCH_URL, data=body, headers={
            "User-Agent": _USER_AGENT, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                items = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return {i: {"code": exc.code, "message": "batch refused"} for i in chunk}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return {i: {"code": 0, "message": str(exc)} for i in chunk}
        answers = {}
        for item in items if isinstance(items, list) else []:
            found = [entry.get("location") for entry in item.get("locations") or [] if entry.get("location")]
            error = (item.get("errors") or [{}])[0]
            answers[str(item.get("requestId"))] = ({"location": found[0], "type": item.get("assetTypeId")} if found else
                                                   {"code": error.get("code"), "message": error.get("message")})
        return answers

    answers: dict = {}
    chunks = [ids[start:start + BATCH_SIZE] for start in range(0, len(ids), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(ask, chunks):
            answers.update(result)
    return answers


def locate_signed_in(ids: list[str]) -> dict[str, str]:
    """Where to download each asset as the Roblox Studio user on this machine:
    id -> link or 'missing (why)'; every id is _NO_LOGIN when there is no login."""
    answers = answers_signed_in(ids)
    if isinstance(answers, str):
        return {i: answers for i in ids}
    return _locations(answers, ids, signed_in=True)


def answers_signed_in(ids: list[str]) -> dict[str, dict] | str:
    """The batch endpoint's answers as the Studio user: id -> {location, type} or
    {code, message}; or one 'missing (why)' for all (no login, no Lune, ...)."""
    import subprocess

    from rhr.ir import lune_executable
    from rhr.procs import no_window

    if not ids:
        return {}
    try:
        lune = lune_executable()
    except (RuntimeError, OSError) as exc:
        return f"missing (signed-in download needs Lune: {exc})"
    script = PACKAGE / "luau" / "fetch-locations.luau"
    try:
        proc = subprocess.run([lune, "run", str(script)], input=json.dumps(ids), capture_output=True,
                              text=True, encoding="utf-8", timeout=300, **no_window())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"missing (signed in: {exc})"
    out = proc.stdout.strip()
    if out == "nologin":
        return _NO_LOGIN
    try:
        answers = json.loads(out)
    except ValueError:
        return f"missing (signed in: {(proc.stderr.strip().splitlines() or ['no answer'])[-1]})"
    return answers if isinstance(answers, dict) else {}


def _download(location: str, *, timeout: float = 60.0) -> bytes | str:
    """One file from Roblox's CDN: its bytes, or 'missing (why)'."""
    request = urllib.request.Request(location, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
            return payload
    except urllib.error.HTTPError as exc:
        return f"missing (download: HTTP {exc.code})"
    except (urllib.error.URLError, TimeoutError, OSError, EOFError, gzip.BadGzipFile) as exc:
        return f"missing (download: {exc})"


def _thumbnails(ids: set[str], log) -> dict[str, str]:
    """Images from Roblox's thumbnail service (no sign-in, at most 420 px)."""
    from rhr.ui_engine.asset_fetcher import fetch_icons
    from rhr.ui_engine.assets import _asset_cache_dir

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
    login_off = not login  # turned off by the caller (--no-studio-login)
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

    # Where each file is: as the Studio user, then without a sign-in for whatever that
    # could not answer (no login found, Lune missing, or the login turned off).
    order = [(kind, asset) for kind, ids in wanted.items() for asset in ids]
    ids = sorted({asset for _, asset in order}, key=lambda value: (len(value), value))
    no_login = ("missing (needs a signed-in account; rhr fetch without --no-studio-login uses the "
                "Roblox Studio login)") if login_off else _NO_LOGIN
    located = locate_signed_in(ids) if login else {i: no_login for i in ids}
    unanswered = [i for i in ids if not located[i].startswith(("https://", "missing (signed in: HTTP"))]
    if unanswered:
        for asset, where in locate_public(unanswered).items():
            if where.startswith("https://") or "signed-in account: HTTP" not in where:
                located[asset] = where  # (else keep why there was no signed-in answer)

    def download(item: tuple[str, str]) -> tuple[str, str, str]:
        kind, asset = item
        where = located[asset]
        payload = _download(where) if where.startswith("https://") else where
        return kind, asset, _store(kind, asset, payload) if isinstance(payload, bytes) else payload

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        for kind, asset, status in executor.map(download, order):
            if kind == "images" and status == "fetched":
                originals[asset] = True
            if kind == "images" and status != "fetched" and _cached(kind, asset):
                if status not in (_NO_LOGIN, no_login):
                    failures[f"original:{asset}"] = {"status": status, "time": now}
                status = "cached"  # the earlier thumbnail stays
            results[kind][asset] = status

    # Images nothing else could get: thumbnails, which need no sign-in.
    thumbs = {a for a, s in results.get("images", {}).items() if s.startswith("missing")}
    if thumbs:
        for asset, status in _thumbnails(thumbs, log).items():
            results["images"][asset] = status

    for kind, statuses in results.items():
        for asset, status in statuses.items():
            key = f"{kind}:{asset}"
            # (Not what a login would get: signing in must not wait a day to count.)
            if (status.startswith("missing") and "Lune" not in status
                    and status not in (_NO_LOGIN, no_login)):
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


def ensure_for_ir(ir_path: Path, *, log=None, focus: str | None = None) -> dict[str, dict[str, str]]:
    """`ensure` everything a 3D render of the IR at `ir_path` can use: what it draws,
    not the models a place stores out of the world (rhr.ir.world_roots)."""
    from rhr.ir import load_ir, world_roots

    ir = load_ir(ir_path)
    roots = ir.get("roots") or []
    shown = world_roots(roots, focus)[0]
    if len(shown) != len(roots) or any(a is not b for a, b in zip(shown, roots)):
        ir = {**ir, "roots": shown}  # (a world slice, rhr.ir.world_ir, draws all its roots)
    return ensure(scene_refs(ir), log=log)


def run(ir_path: Path, *, images: bool = True, meshes: bool = True, studio_login: bool = True) -> int:
    """`rhr fetch`: fetch everything the IR at `ir_path` references; print a summary. Exit code."""
    from rhr.ir import load_ir

    ir = load_ir(ir_path)
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
