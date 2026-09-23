"""Long-lived browser worker used by RHR's optional persistent render path.

This module is launched by a host Python that has Playwright available. It is not
imported by the project venv. The caller sends local HTTP requests containing an
already-running RHR page URL; this worker owns Chromium and captures the page once
its explicit data-rhr-ready contract is satisfied.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import signal
import threading
from pathlib import Path


class RenderServer(http.server.HTTPServer):
    browser = None
    token: str
    port_file: Path


class Handler(http.server.BaseHTTPRequestHandler):
    server: RenderServer

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-RHR-Token") == self.server.token

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True, "pid": os.getpid()})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._json(403, {"error": "forbidden"})
            return
        if self.path == "/render":
            self._render()
            return
        if self.path == "/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json(404, {"error": "not found"})

    def _render(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            url = str(request["url"])
            out = Path(request["out"])
            width = int(request["width"])
            height = int(request["height"])
            transparent = bool(request.get("transparent", False))
            if width <= 0 or height <= 0:
                raise ValueError("render dimensions must be positive")

            context = self.server.browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            try:
                page = context.new_page()
                page.goto(url, wait_until="load", timeout=45_000)
                page.wait_for_function(
                    """() => document.documentElement.dataset.rhrReady === 'true'
                       || Boolean(document.documentElement.dataset.rhrError)""",
                    timeout=45_000,
                )
                error = page.evaluate(
                    "() => document.documentElement.dataset.rhrError || null"
                )
                if error:
                    raise RuntimeError(f"browser page error: {error}")
                out.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(out),
                    omit_background=transparent,
                    animations="disabled",
                    timeout=45_000,
                )
            finally:
                context.close()
            self._json(200, {"ok": True})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def log_message(self, _format, *_args):
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        executable_path=args.chrome,
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--hide-scrollbars",
        ],
    )
    server = RenderServer(("127.0.0.1", 0), Handler)
    server.browser = browser
    server.token = args.token
    server.port_file = args.port_file
    args.port_file.parent.mkdir(parents=True, exist_ok=True)
    args.port_file.write_text(str(server.server_port))

    def terminate(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        server.serve_forever()
    finally:
        args.port_file.unlink(missing_ok=True)
        browser.close()
        playwright.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
