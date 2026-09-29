"""`rhr view`: a build in a local page you can move around in, updated as it changes.

The scene page (scene/index.html, `interactive=1`) with the same drawing as
`rhr scene`, served from this process on 127.0.0.1 until Ctrl+C. The page asks for
`/__rhr_version__` about twice a second; when the source changes (the file, or any
file of a Rojo project) this process converts it again, fetches what it newly needs,
and bumps the version, and the page redraws with its camera where it was. An
agent's edit shows up in the open page without anyone touching it.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse

from rhr import scene as scene_module

POLL_S = 0.5
# Folders a Rojo project's own files never live in, or that change on every build.
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "out", "build", "dist"}


class _State:
    def __init__(self):
        self.version = 0
        self.error: str | None = None


def _stamp(source: Path) -> tuple:
    """What changes when the source does: the file's size and time, or a Rojo
    project folder's newest file."""
    if source.is_file() and not source.name.endswith(".project.json"):
        info = source.stat()
        return (info.st_size, info.st_mtime_ns)
    root = source if source.is_dir() else source.parent
    newest, count = 0, 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            try:
                newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime_ns)
                count += 1
            except OSError:
                pass
    return (newest, count)


def serve(source: Path, build: Callable[[], Path], *, query: dict, open_browser: bool = True,
          port: int = 0, log=None) -> int:
    """Serve the scene of `build()` (it returns the IR to draw) until Ctrl+C."""
    log = log or (lambda message: print(message, file=sys.stderr))
    state = _State()

    class Handler(scene_module._SceneHandler):
        def do_GET(self):  # noqa: N802
            if urlparse(self.path).path == "/__rhr_version__":
                payload = json.dumps({"version": state.version, "error": state.error}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

    def handler_for(ir_path: Path) -> type:
        images, meshes = scene_module.cached_asset_files()
        return scene_module.scene_handler(ir_path, images, meshes, base=Handler)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler_for(build()))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/scene/index.html?" + urlencode(
        {**query, "interactive": "1", "name": source.name or str(source)})
    stop = threading.Event()

    def watch() -> None:
        seen = _stamp(source)
        while not stop.wait(POLL_S):
            try:
                now = _stamp(source)
            except OSError:
                continue
            if now == seen:
                continue
            seen = now
            started = time.perf_counter()
            try:
                server.RequestHandlerClass = handler_for(build())
                state.error = None
                state.version += 1
                log(f"view   {source.name} changed: redrawn ({(time.perf_counter() - started) * 1000:.0f} ms)")
            except (ValueError, RuntimeError, OSError) as exc:
                state.error = f"the file changed but could not be read: {str(exc).splitlines()[0][:200]}"
                state.version += 1
                log(f"view   {state.error}")

    threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    print(url, flush=True)
    log(f"view   {url}")
    log(f"view   serving {source} on this machine only; the page updates when it changes. Ctrl+C stops.")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
    return 0
