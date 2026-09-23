"""Browser-backed 3D scene rendering for the RHR CLI."""

from __future__ import annotations

import http.server
import json
import os
import struct
import threading
from pathlib import Path
from urllib.parse import urlencode, urlparse

from rhr.paths import ICON_CACHE, MESH_CACHE, PACKAGE, PARTICLE_CACHE



class _SceneHandler(http.server.SimpleHTTPRequestHandler):
    ir_path: Path
    metadata_sink: dict | None = None
    asset_manifest_payload: bytes = b"{}"
    mesh_manifest_payload: bytes = b"{}"
    asset_files: dict[str, Path] = {}
    mesh_files: dict[str, Path] = {}
    ir_cache: dict | None = None

    def __init__(self, *args, **kwargs):
        kwargs["directory"] = str(PACKAGE)
        super().__init__(*args, **kwargs)

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
        if request_path.startswith(("/__rhr_mesh__/", "/__rhr_asset__/")):
            files = self.mesh_files if request_path.startswith("/__rhr_mesh__/") else self.asset_files
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
        if urlparse(self.path).path == "/__rhr_camera__.json" and self.metadata_sink is not None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self.metadata_sink.clear()
                self.metadata_sink.update(payload)
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
            with tempfile.TemporaryDirectory(prefix="rhr-gui-") as tmp:
                out = render_gui_node(
                    self.ir_cache, str(request["path"]), int(request["width"]), int(request["height"]),
                    Path(tmp) / "gui.png",
                )
                payload = out.read_bytes()
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


def _asset_files(roots: list[Path]) -> dict[str, Path]:
    """Return asset-id -> local image file, preserving root/extension priority."""
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for extension in _ASSET_EXTENSIONS:
            for path in sorted(root.glob(f"*.{extension}")):
                if path.stem.isdigit() and path.stem not in found:
                    found[path.stem] = path.resolve()
    return found


def _mesh_files(roots: list[Path]) -> dict[str, Path]:
    """Return asset-id -> local decompressed Roblox mesh file, in root priority order."""
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.mesh")):
            if path.stem.isdigit() and path.stem not in found:
                found[path.stem] = path.resolve()
    return found


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError(f"browser output is not a PNG: {path}")
    return struct.unpack(">II", header[16:24])


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
) -> tuple[int, int]:
    """Render one local browser page and return its verified PNG dimensions."""
    out.parent.mkdir(parents=True, exist_ok=True)
    handler = type(
        "RHRSceneHandler",
        (_SceneHandler,),
        {
            "ir_path": ir_path,
            "metadata_sink": metadata_sink,
            "page_notes": notes_out if notes_out is not None else [],
            "asset_manifest_payload": json.dumps({
                asset_id: f"/__rhr_asset__/{asset_id}"
                for asset_id in (asset_files or {})
            }).encode(),
            "asset_files": asset_files or {},
            "mesh_manifest_payload": json.dumps({
                asset_id: f"/__rhr_mesh__/{asset_id}"
                for asset_id in (mesh_files or {})
            }).encode(),
            "mesh_files": mesh_files or {},
        },
    )
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
        persistent_setting = os.environ.get("RHR_PERSISTENT_BROWSER")
        if persistent_setting is None:
            from rhr.browser_session import status as browser_status

            persistent = bool(browser_status().get("running"))
        else:
            persistent = persistent_setting.lower() in {"1", "true", "yes", "on"}
        if persistent:
            from rhr.browser_session import render as render_persistent

            render_persistent(url=url, out=out, width=width, height=height, transparent=transparent)
        else:
            from rhr.browser_render import render_once

            render_once(url=url, out=out, width=width, height=height, transparent=transparent)
    finally:
        server.shutdown()
        thread.join(timeout=2)
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(f"Chromium did not write a screenshot: {out}")
    actual = _png_size(out)
    expected = (width, height)
    if actual != expected:
        raise RuntimeError(f"browser PNG is {actual[0]}x{actual[1]}, expected {expected[0]}x{expected[1]}")
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
    shadows: bool = False,
    texture_dir: Path | None = None,
    mesh_dir: Path | None = None,
    camera_state_out: dict | None = None,
    notes_out: list[str] | None = None,
) -> tuple[int, int]:
    query_values: dict[str, str | float] = {}
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
    if shadows:
        query_values["shadows"] = "1"
    if camera_state_out is not None:
        query_values["reportCamera"] = "1"
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


def render_particle_sheet(
    ir_path: Path,
    out: Path,
    width: int,
    height: int,
    times: list[float],
    seed: int,
    burst: int = 0,
    texture_dir: Path | None = None,
    *,
    effects_only: bool = False,
    camera: tuple[float, float, float] | None = None,
    look_at: tuple[float, float, float] | None = None,
    camera_quaternion: tuple[float, float, float, float] | None = None,
    fov: float | None = None,
) -> tuple[int, int]:
    if not times:
        raise ValueError("particle capture needs at least one time")
    if any(time < 0 for time in times):
        raise ValueError("particle capture times must be non-negative")
    if texture_dir is not None:
        resolved = texture_dir.resolve()
        if not resolved.is_dir():
            raise ValueError(f"no such texture directory: {texture_dir}")
    asset_roots = [
        resolved if texture_dir is not None else PARTICLE_CACHE,
        ICON_CACHE,
    ]
    query_values = {
        "width": width,
        "height": height,
        "times": ",".join(str(time) for time in times),
        "seed": seed,
        "burst": burst,
    }
    if effects_only:
        query_values["effectsOnly"] = "1"
    if camera is not None:
        query_values["camera"] = _vector_query(camera)
    if look_at is not None:
        query_values["lookAt"] = _vector_query(look_at)
    if camera_quaternion is not None:
        query_values["cameraQuaternion"] = ",".join(
            f"{component:.9g}" for component in camera_quaternion
        )
    if fov is not None:
        query_values["fov"] = fov
    query = urlencode(query_values)
    return _render_browser(
        ir_path,
        out,
        width,
        height * len(times),
        "particles/index.html",
        query,
        asset_files=_asset_files(asset_roots),
    )