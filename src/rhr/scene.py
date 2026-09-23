"""Browser-backed 3D scene rendering for the RHR CLI."""

from __future__ import annotations

import http.server
import html
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

REPO = Path(__file__).resolve().parents[2]


class _SceneHandler(http.server.SimpleHTTPRequestHandler):
    ir_path: Path
    metadata_sink: dict | None = None
    asset_manifest_payload: bytes = b"{}"
    mesh_manifest_payload: bytes = b"{}"
    mesh_files: dict[str, Path] = {}

    def __init__(self, *args, **kwargs):
        kwargs["directory"] = str(REPO)
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
        if request_path.startswith("/__rhr_mesh__/"):
            asset_id = request_path.rsplit("/", 1)[-1]
            path = self.mesh_files.get(asset_id)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            payload = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802, required by SimpleHTTPRequestHandler
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

    def log_message(self, format, *_args):
        return


def _chrome_path() -> str:
    candidates = [
        os.environ.get("RHR_CHROME"),
        str(Path.home() / ".cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell"),
        str(Path.home() / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("no Chromium executable found; set RHR_CHROME to a headless Chrome binary")


_ASSET_EXTENSIONS = ("png", "webp", "jpg", "jpeg", "svg")


def _asset_manifest(roots: list[Path]) -> dict[str, str]:
    """Return asset-id -> repo-relative URL, preserving root/extension priority."""
    manifest: dict[str, str] = {}
    repo = REPO.resolve()
    for root in roots:
        resolved = root.resolve()
        if not resolved.is_dir():
            continue
        try:
            relative_root = resolved.relative_to(repo)
        except ValueError as exc:
            raise ValueError("asset directory must be inside the repository") from exc
        for extension in _ASSET_EXTENSIONS:
            for path in sorted(resolved.glob(f"*.{extension}")):
                if not path.stem.isdigit() or path.stem in manifest:
                    continue
                manifest[path.stem] = "/" + (relative_root / path.name).as_posix()
    return manifest


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
    asset_manifest: dict[str, str] | None = None,
    mesh_files: dict[str, Path] | None = None,
) -> tuple[int, int]:
    """Render one local browser page and return its verified PNG dimensions."""
    chrome = _chrome_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    handler = type(
        "RHRSceneHandler",
        (_SceneHandler,),
        {
            "ir_path": ir_path,
            "metadata_sink": metadata_sink,
            "asset_manifest_payload": json.dumps(asset_manifest or {}).encode(),
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
    try:
        persistent_setting = os.environ.get("RHR_PERSISTENT_BROWSER")
        if persistent_setting is None:
            from rhr.browser_session import status as browser_status

            persistent = bool(browser_status().get("running"))
        else:
            persistent = persistent_setting.lower() in {"1", "true", "yes", "on"}
        if persistent:
            from rhr.browser_session import render as render_persistent

            render_persistent(
                chrome,
                url=url,
                out=out,
                width=width,
                height=height,
                transparent=("mode=viewport" in query or "effectsOnly=1" in query),
            )
        else:
            profile = tempfile.mkdtemp(prefix="rhr-chrome-")
            try:
                command = [
                    chrome,
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile}",
                    f"--window-size={width},{height}",
                    "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=2000",
                    "--dump-dom",
                    f"--screenshot={out}",
                    url,
                ]
                if not chrome.endswith("chrome-headless-shell"):
                    command.insert(1, "--headless=new")
                if "mode=viewport" in query or "effectsOnly=1" in query:
                    command.insert(1, "--default-background-color=00000000")
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("Chromium scene render timed out after 45s") from exc
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip().splitlines()[-5:]
                    raise RuntimeError("Chromium scene render failed: " + " | ".join(detail))
                error_match = re.search(r'data-rhr-error="([^"]*)"', result.stdout or "")
                if error_match:
                    raise RuntimeError(
                        "browser page error: " + html.unescape(error_match.group(1))
                    )
            finally:
                shutil.rmtree(profile, ignore_errors=True)
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


def _ir_has_path(ir_path: Path, wanted: str) -> bool:
    """Return whether the emitted IR contains the exact slash-separated node path."""
    from rhr.ir import load_ir

    data = load_ir(ir_path)

    def descend(node: dict, current: str) -> bool:
        if current == wanted:
            return True
        for child in (node.get("children") or {}).values() if isinstance(node.get("children"), dict) else node.get("children") or []:
            name = child.get("name") or child.get("className")
            if descend(child, f"{current}/{name}"):
                return True
        return False

    for root in data.get("roots", []):
        if descend(root, root.get("name") or root.get("className")):
            return True
    return False


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
        if not _ir_has_path(ir_path, focus):
            raise ValueError(f"focus path not found in IR: {focus}")
        query_values["focus"] = focus
    if view:
        query_values["view"] = view
    if shadows:
        query_values["shadows"] = "1"
    if camera_state_out is not None:
        query_values["reportCamera"] = "1"
    if texture_dir is not None:
        resolved = texture_dir.resolve()
        try:
            texture_root = resolved.relative_to(REPO.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("texture directory must be inside the repository") from exc
        if not resolved.is_dir():
            raise ValueError(f"no such texture directory: {texture_dir}")
        query_values["textureDir"] = texture_root
        asset_roots.append(resolved)
    asset_roots.append(REPO / "assets/cache/icons")
    mesh_roots = []
    if mesh_dir is not None:
        resolved_mesh_dir = mesh_dir.resolve()
        if not resolved_mesh_dir.is_dir():
            raise ValueError(f"no such mesh directory: {mesh_dir}")
        mesh_roots.append(resolved_mesh_dir)
    mesh_roots.append(REPO / "assets/cache/meshes")
    cached_meshes = _mesh_files(mesh_roots)
    return _render_browser(
        ir_path,
        out,
        width,
        height,
        "src/rhr/scene/index.html",
        urlencode(query_values),
        metadata_sink=camera_state_out,
        asset_manifest=_asset_manifest(asset_roots),
        mesh_files=cached_meshes,
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
    if not _ir_has_path(ir_path, node_path):
        raise ValueError(f"ViewportFrame path not found in IR: {node_path}")
    return _render_browser(
        ir_path,
        out,
        width,
        height,
        "src/rhr/scene/index.html",
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
        try:
            texture_root = resolved.relative_to(REPO.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("texture directory must be inside the repository") from exc
        if not resolved.is_dir():
            raise ValueError(f"no such texture directory: {texture_dir}")
    else:
        texture_root = None
    asset_roots = [
        resolved if texture_dir is not None else REPO / "assets/cache/particles",
        REPO / "assets/cache/icons",
    ]
    query_values = {
        "width": width,
        "height": height,
        "times": ",".join(str(time) for time in times),
        "seed": seed,
        "burst": burst,
    }
    if texture_root:
        query_values["textureDir"] = texture_root
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
        "src/rhr/particles/index.html",
        query,
        asset_manifest=_asset_manifest(asset_roots),
    )