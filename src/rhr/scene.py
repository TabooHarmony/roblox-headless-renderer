"""Browser-backed 3D scene rendering for the RHR CLI."""

from __future__ import annotations

import http.server
import json
import os
import re
import struct
import threading
from pathlib import Path
from urllib.parse import urlencode, urlparse

from rhr.listing import listing as _listing
from rhr.paths import ICON_CACHE, MESH_CACHE, PACKAGE

_LOCAL_HOST = re.compile(r"^(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$", re.IGNORECASE)
_LOCAL_ORIGIN = re.compile(r"^http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$", re.IGNORECASE)


class _SceneHandler(http.server.SimpleHTTPRequestHandler):
    ir_path: Path
    metadata_sink: dict | None = None
    camera_log: list | None = None
    asset_manifest_payload: bytes = b"{}"
    mesh_manifest_payload: bytes = b"{}"
    asset_files: dict[str, Path] = {}
    mesh_files: dict[str, Path] = {}
    union_files: dict[str, Path] = {}
    material_files: dict[str, Path] = {}
    studio_files: dict[str, Path] = {}
    extras_manifest_payload: bytes = b"{}"
    ir_cache: dict | None = None

    def __init__(self, *args, **kwargs):
        kwargs["directory"] = str(PACKAGE)
        super().__init__(*args, **kwargs)

    def parse_request(self):
        # Pages on this machine only: a web page open in the user's browser, or one that
        # points its own name at 127.0.0.1 (DNS rebinding), must not read the scene.
        if not super().parse_request():
            return False
        if not _LOCAL_HOST.match(self.headers.get("Host", "")):
            self.send_error(421, "RHR serves pages on this machine only")
            return False
        return True

    def end_headers(self):
        # The warm worker's page is on another local address (see rhr.browser_daemon)
        # and fetches this render's data from here; no other origin may.
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin", "") if headers is not None else ""
        if _LOCAL_ORIGIN.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):  # noqa: N802 - CORS preflight for the page's JSON POSTs
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802, required by SimpleHTTPRequestHandler
        request_path = urlparse(self.path).path
        if request_path == "/__rhr_ir__.json":
            payload = self.ir_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if request_path == "/__rhr_terrain__.json":
            # Voxel terrain from the source place (rhr.terrain); `null` without any.
            from rhr.terrain import terrain_payload

            from rhr.ir import load_ir

            source = load_ir(self.ir_path).get("sourcePath")
            terrain = terrain_payload(Path(source)) if source and Path(source).is_file() else None
            payload = json.dumps(terrain).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if request_path == "/__rhr_assets__.json":
            payload = self.asset_manifest_payload
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if request_path == "/__rhr_meshes__.json":
            payload = self.mesh_manifest_payload
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if request_path == "/__rhr_extras__.json":
            payload = self.extras_manifest_payload
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        prefixes = {
            "/__rhr_mesh__/": "mesh_files", "/__rhr_asset__/": "asset_files",
            "/__rhr_union__/": "union_files", "/__rhr_material__/": "material_files",
            "/__rhr_studio__/": "studio_files",
        }
        prefix = next((p for p in prefixes if request_path.startswith(p)), None)
        if prefix is not None:
            files = getattr(self, prefixes[prefix])
            asset_id = request_path.rsplit("/", 1)[-1]
            path = files.get(asset_id)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            payload = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802, required by SimpleHTTPRequestHandler
        if urlparse(self.path).path == "/__rhr_gui__.png":
            self._render_gui()
            return
        if urlparse(self.path).path == "/__rhr_notes__.json":
            # Human-readable notes the page wants printed (e.g. what framing left out).
            try:
                length = int(self.headers.get("Content-Length", "0"))
                self.page_notes.extend(str(n) for n in json.loads(self.rfile.read(length) or b"[]"))
                self.send_response(204)
                self.end_headers()
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_error(400)
            return
        if urlparse(self.path).path == "/__rhr_timing__.json":
            # Steps of the page itself, for RHR_PROFILE: [[name, milliseconds], ...].
            try:
                from rhr.profile import add

                length = int(self.headers.get("Content-Length", "0"))
                for name, ms in json.loads(self.rfile.read(length) or b"[]"):
                    add(f"    page: {name}", float(ms) / 1000)
                self.send_response(204)
                self.end_headers()
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_error(400)
            return
        if urlparse(self.path).path == "/__rhr_camera__.json" and self.metadata_sink is not None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self.metadata_sink.clear()
                self.metadata_sink.update(payload)
                if self.camera_log is not None:
                    self.camera_log.append(payload)
                self.send_response(204)
                self.end_headers()
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
            return
        self.send_error(404)

    def _render_gui(self) -> None:
        """Draw an in-world GUI subtree with the 2D engine at the size the page asks for."""
        import tempfile

        from rhr.ir import load_ir
        from rhr.pipeline import render_gui_node

        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            if self.ir_cache is None:
                type(self).ir_cache = load_ir(self.ir_path)
            # Kept while the IR is loaded (rhr.ir.derived) and the image cache unchanged:
            # a warm render of the same place does not draw its hundred SurfaceGuis again.
            from rhr.ir import derived
            from rhr.paths import ICON_CACHE

            try:
                images_stamp = ICON_CACHE.stat().st_mtime_ns
            except OSError:
                images_stamp = None
            drawn = derived(self.ir_cache, "in_world_gui", lambda _: {})
            key = (str(request["path"]), int(request["width"]), int(request["height"]), images_stamp)
            payload = drawn.get(key)
            if payload is None:
                with tempfile.TemporaryDirectory(prefix="rhr-gui-") as tmp:
                    out = render_gui_node(
                        self.ir_cache, str(request["path"]), int(request["width"]), int(request["height"]),
                        Path(tmp) / "gui.png",
                    )
                    payload = drawn[key] = out.read_bytes()
        except Exception as exc:  # reported to the page, which fails the render loudly
            body = f"{type(exc).__name__}: {exc}".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *_args):
        return


_ASSET_EXTENSIONS = ("png", "webp", "jpg", "jpeg", "svg")


def _files_with(roots: list[Path], suffixes) -> dict[str, tuple[Path, int, int]]:
    """asset id -> (path, size, mtime_ns), the first root and suffix that has it winning."""
    found: dict[str, tuple[Path, int, int]] = {}
    for root in roots:
        listing = _listing(root)
        for suffix in suffixes:
            for stem, entry in listing.get(suffix, {}).items():
                found.setdefault(stem, entry)
    return found


def _asset_files(roots: list[Path]) -> dict[str, tuple[Path, int, int]]:
    """Return asset-id -> local image file, preserving root/extension priority."""
    return _files_with(roots, _ASSET_EXTENSIONS)


def _mesh_files(roots: list[Path]) -> dict[str, tuple[Path, int, int]]:
    """Return asset-id -> local decompressed Roblox mesh file, in root priority order."""
    return _files_with(roots, ("mesh",))


def _inline_unions(ir_path: Path) -> dict[str, Path]:
    """IR path -> decoded mesh file, for unions that carry their mesh in the file (MeshData2).

    Decoded once per distinct mesh into the union cache, named by the bytes' hash.
    """
    from rhr.ir import derived, load_ir

    try:
        ir = load_ir(ir_path)
    except (OSError, ValueError):
        return {}
    found = derived(ir, "inline_unions", _decode_inline_unions)
    if all(path.is_file() for path in found.values()):
        return found
    return _decode_inline_unions(ir)  # the union cache was cleared since


def _decode_inline_unions(ir: dict) -> dict[str, Path]:
    import base64
    import hashlib

    from rhr import unions
    from rhr.paths import UNION_CACHE

    found: dict[str, Path] = {}

    def visit(node: dict, parent: str) -> None:
        path = node.get("path") or (f"{parent}/{node.get('name')}" if parent else str(node.get("name")))
        encoded = (node.get("props") or {}).get("MeshData2")
        if node.get("className") == "UnionOperation" and isinstance(encoded, str) and encoded:
            try:
                blob = base64.b64decode(encoded)
                target = UNION_CACHE / f"inline-{hashlib.sha1(blob).hexdigest()[:20]}.json"
                if not target.is_file():
                    payload = unions.to_payload(unions.decode(blob))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(".tmp")
                    temporary.write_text(json.dumps(payload), encoding="utf-8")
                    temporary.replace(target)  # never half a file in the cache
                found[target.stem] = target
            except (ValueError, unions.UnionFormatError):
                pass
        children = node.get("children") or {}
        for child in (children.values() if isinstance(children, dict) else children):
            visit(child, path)

    for root in ir.get("roots", []):
        visit(root, "")
    return found


def _content_refs(ir_path: Path) -> set[str]:
    """Every `rbxasset://` file the IR names (see rhr.studio.content_path)."""
    from rhr.ir import derived, load_ir

    try:
        ir = load_ir(ir_path)
    except (OSError, ValueError):
        return set()
    return derived(ir, "content_refs", _find_content_refs)


def _find_content_refs(ir: dict) -> set[str]:
    from rhr.studio import content_path

    found: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value[:11].lower() == "rbxasset://":
            key = content_path(value)
            if key:
                found.add(key)

    visit(ir.get("roots", []))
    return found


def _extras(ir_path: Path | None = None) -> dict:
    """Union meshes, Roblox material maps and Studio textures the page may use."""
    import hashlib

    from rhr.paths import MATERIAL_CACHE, UNION_CACHE
    from rhr.studio import AVATAR_CONTENT, SKY_CONTENT, studio_content, studio_install, studio_textures

    unions: dict = dict(_listing(UNION_CACHE).get("json", {}))
    if ir_path is not None:
        unions.update(_inline_unions(ir_path))
    materials = _listing(MATERIAL_CACHE).get("png", {})
    studio = studio_textures()
    # Files the client ships with (rbxasset://), by path: what the IR names plus what
    # characters are drawn with. Served next to the Studio textures under a name
    # without slashes.
    content = studio_content(sorted((_content_refs(ir_path) if ir_path else set()) | set(AVATAR_CONTENT) | set(SKY_CONTENT)))
    content_names = {key: "content-" + hashlib.sha1(key.encode()).hexdigest()[:16] + path.suffix.lower()
                     for key, path in content.items()}
    manifest = {
        "unions": {k: _versioned("/__rhr_union__/", k, v) for k, v in unions.items()},
        "materials": {k: _versioned("/__rhr_material__/", k, v) for k, v in materials.items()},
        "studio": {k: _versioned("/__rhr_studio__/", k, v) for k, v in studio.items()},
        "content": {key: _versioned("/__rhr_studio__/", content_names[key], path) for key, path in content.items()},
        "studioInstalled": studio_install() is not None,
    }
    return {
        "union_files": _paths(unions),
        "material_files": _paths(materials),
        "studio_files": {**studio, **{content_names[key]: path for key, path in content.items()}},
        "extras_manifest_payload": json.dumps(manifest).encode(),
    }


def _versioned(prefix: str, key: str, path) -> str:
    """`prefix/key?v=<size>-<mtime>`: the page keeps what it loaded from an address
    between renders, so a file that changed must get another address. `path` is a
    Path, or a (path, size, mtime_ns) listing entry."""
    if isinstance(path, tuple):
        return f"{prefix}{key}?v={path[1]}-{path[2]}"
    try:
        info = path.stat()
        return f"{prefix}{key}?v={info.st_size}-{info.st_mtime_ns}"
    except OSError:
        return f"{prefix}{key}"


def _paths(files: dict) -> dict[str, Path]:
    return {key: value[0] if isinstance(value, tuple) else value for key, value in files.items()}


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError(f"browser output is not a PNG: {path}")
    return struct.unpack(">II", header[16:24])


def scene_handler(ir_path: Path, asset_files: dict | None = None, mesh_files: dict | None = None, *,
                  metadata_sink: dict | None = None, notes_out: list[str] | None = None, base=None,
                  camera_log: list | None = None) -> type:
    """The request handler that serves the scene page and one scene's data."""
    return type(
        "RHRSceneHandler",
        (base or _SceneHandler,),
        {
            "ir_path": ir_path,
            "metadata_sink": metadata_sink,
            "camera_log": camera_log,
            "page_notes": notes_out if notes_out is not None else [],
            "asset_manifest_payload": json.dumps({
                asset_id: _versioned("/__rhr_asset__/", asset_id, path)
                for asset_id, path in (asset_files or {}).items()
            }).encode(),
            "asset_files": _paths(asset_files or {}),
            "mesh_manifest_payload": json.dumps({
                asset_id: _versioned("/__rhr_mesh__/", asset_id, path)
                for asset_id, path in (mesh_files or {}).items()
            }).encode(),
            "mesh_files": _paths(mesh_files or {}),
            **_extras(ir_path),
        },
    )


def cached_asset_files() -> tuple[dict, dict]:
    """(images, meshes) in the cache, for a scene page: id -> listing entry."""
    return _asset_files([ICON_CACHE]), _mesh_files([MESH_CACHE])


def _render_browser(
    ir_path: Path,
    out: Path,
    width: int,
    height: int,
    page: str,
    query: str = "",
    metadata_sink: dict | None = None,
    asset_files: dict[str, Path] | None = None,
    mesh_files: dict[str, Path] | None = None,
    notes_out: list[str] | None = None,
    more_views: list[tuple[str, Path]] = (),
    camera_log: list | None = None,
) -> tuple[int, int]:
    """Render one local browser page and return its verified PNG dimensions.

    `more_views` ([(query, out)]) are more pictures of the same 3D scene from other
    cameras: drawn on the one built scene when the warm worker's kept page can, else
    one by one.
    """
    # Absolute: the warm worker writes the file, and its working folder is not ours.
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    more_views = [(view_query, Path(view_out).resolve()) for view_query, view_out in more_views]
    for _, view_out in more_views:
        view_out.parent.mkdir(parents=True, exist_ok=True)
    drawn = 0
    handler = scene_handler(ir_path, asset_files, mesh_files, metadata_sink=metadata_sink, notes_out=notes_out,
                            camera_log=camera_log)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01),
        daemon=True,
    )
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/{page}"
    if query:
        url += "?" + query
    transparent = "mode=viewport" in query or "effectsOnly=1" in query
    try:
        from rhr.browser_session import usable_worker

        # The warm worker, started on first use (see usable_worker).
        persistent = usable_worker()
        if persistent:
            from rhr.browser_session import render as render_persistent

            # A 3D scene can go to the worker's kept page; ViewportFrames and the particle
            # contact sheet always load a page of their own.
            reuse = None
            if page == "scene/index.html" and not transparent:
                reuse = {"query": query, "base": f"http://127.0.0.1:{server.server_port}",
                         "views": [{"query": q, "out": str(o)} for q, o in more_views]}
            try:
                drawn = render_persistent(url=url, out=out, width=width, height=height, transparent=transparent,
                                          reuse=reuse)
            except (RuntimeError, OSError) as exc:
                # The worker failed (or crashed): draw this one in a browser of its own.
                from rhr.browser_render import render_once

                if notes_out is not None:
                    notes_out.append(f"the warm browser worker failed ({str(exc)[:160]}); drew with a fresh browser")
                render_once(url=url, out=out, width=width, height=height, transparent=transparent)
        else:
            from rhr.browser_render import render_once

            render_once(url=url, out=out, width=width, height=height, transparent=transparent)
    finally:
        server.shutdown()
        thread.join(timeout=2)
    if camera_log is not None:
        del camera_log[1 + drawn:]  # a view that failed part way may have reported its camera
    for view_query, view_out in more_views[drawn:]:
        _render_browser(ir_path, view_out, width, height, page, view_query, asset_files=asset_files,
                        mesh_files=mesh_files, notes_out=notes_out, camera_log=camera_log)
    for picture in [out, *(view_out for _, view_out in more_views)]:
        if not picture.is_file() or picture.stat().st_size == 0:
            raise RuntimeError(f"the browser did not write a screenshot: {picture}")
        actual = _png_size(picture)
        if actual != (width, height):
            raise RuntimeError(f"browser PNG is {actual[0]}x{actual[1]}, expected {width}x{height}")
    return actual


def _check_path(ir_path: Path, wanted: str) -> None:
    """Raise unless `wanted` names exactly one node in the IR (see rhr.ir.resolve_path)."""
    from rhr.ir import load_ir, resolve_path

    resolve_path(load_ir(ir_path)["roots"], wanted)


def _vector_query(value: tuple[float, float, float] | None) -> str | None:
    if value is None:
        return None
    return ",".join(f"{component:.9g}" for component in value)


def render_scene(
    ir_path: Path,
    out: Path,
    width: int,
    height: int,
    *,
    camera: tuple[float, float, float] | None = None,
    look_at: tuple[float, float, float] | None = None,
    fov: float | None = None,
    focus: str | None = None,
    view: str | None = None,
    shadows: bool = True,
    flat_materials: bool = False,
    texture_dir: Path | None = None,
    mesh_dir: Path | None = None,
    camera_state_out: dict | None = None,
    notes_out: list[str] | None = None,
    effects: bool = True,
    effect_time: float | None = None,
    seed: int = 0,
    more_views: list[tuple[str, Path]] = (),
    camera_log: list | None = None,
) -> tuple[int, int]:
    """Render the 3D scene to a PNG through headless Chromium.

    Particles are drawn frozen at one moment of the effect playing: `effect_time`
    seconds after it starts, or the fullest moment when None. `effects=False` leaves
    out particles, Beams and Trails. `more_views` ([(view, out)]) draws the scene
    from other standard views too, on the same build when it can; `camera_log` gets
    each picture's camera in order.
    """
    query_values: dict[str, str | float] = {}
    if not effects:
        query_values["effects"] = "0"
    if effect_time is not None:
        if effect_time < 0:
            raise ValueError("effect time must be non-negative")
        query_values["effectTime"] = effect_time
    if seed:
        query_values["seed"] = seed
    asset_roots: list[Path] = []
    if camera is not None:
        query_values["camera"] = _vector_query(camera)
    if look_at is not None:
        query_values["lookAt"] = _vector_query(look_at)
    if fov is not None:
        query_values["fov"] = fov
    if focus:
        try:
            _check_path(ir_path, focus)
        except ValueError as exc:
            raise ValueError(f"focus {exc}") from None
        query_values["focus"] = focus
    if view:
        query_values["view"] = view
    query_values["shadows"] = "1" if shadows else "0"
    if os.environ.get("RHR_EFFECTS_UNDER"):
        query_values["effectsUnder"] = os.environ["RHR_EFFECTS_UNDER"]
    if os.environ.get("RHR_SCENE_TUNE"):
        query_values["tune"] = os.environ["RHR_SCENE_TUNE"]
    if flat_materials:
        query_values["flatMaterials"] = "1"
    if camera_state_out is not None:
        query_values["reportCamera"] = "1"
    from rhr.profile import ENABLED as profiling

    if profiling:
        query_values["profile"] = "1"
    if texture_dir is not None:
        resolved = texture_dir.resolve()
        if not resolved.is_dir():
            raise ValueError(f"no such texture directory: {texture_dir}")
        asset_roots.append(resolved)
    asset_roots.append(ICON_CACHE)
    mesh_roots = []
    if mesh_dir is not None:
        resolved_mesh_dir = mesh_dir.resolve()
        if not resolved_mesh_dir.is_dir():
            raise ValueError(f"no such mesh directory: {mesh_dir}")
        mesh_roots.append(resolved_mesh_dir)
    mesh_roots.append(MESH_CACHE)
    cached_meshes = _mesh_files(mesh_roots)
    return _render_browser(
        ir_path,
        out,
        width,
        height,
        "scene/index.html",
        urlencode(query_values),
        metadata_sink=camera_state_out,
        asset_files=_asset_files(asset_roots),
        mesh_files=cached_meshes,
        notes_out=notes_out,
        more_views=[(urlencode({**query_values, "view": name}), view_out) for name, view_out in more_views],
        camera_log=camera_log,
    )


def render_viewport(
    ir_path: Path,
    out: Path,
    width: int,
    height: int,
    node_path: str,
) -> tuple[int, int]:
    """Render one ViewportFrame subtree to a transparent PNG."""
    if width <= 0 or height <= 0:
        raise ValueError("ViewportFrame dimensions must be positive")
    try:
        _check_path(ir_path, node_path)
    except ValueError as exc:
        raise ValueError(f"ViewportFrame {exc}") from None
    return _render_browser(
        ir_path,
        out,
        width,
        height,
        "scene/index.html",
        urlencode({"mode": "viewport", "path": node_path}),
    )
