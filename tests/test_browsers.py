#!/usr/bin/env python3
"""Which browser RHR picks (rhr.browsers), and the headless shell download.

Fake installs in temp folders stand in for Chrome and Edge; the download is served
from a local HTTP server, so nothing here needs a browser or the network.

    python tests/test_browsers.py
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import io
import os
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


class Env:
    """Set environment variables for a block, and put them back after."""

    def __init__(self, **values: str | None):
        self.values = values
        self.saved: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, *_exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def fake_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#!/bin/sh\nexit 1\n")
    path.chmod(0o755)
    return path


def discovery(tmp: Path) -> None:
    from rhr import browsers

    with Env(RHR_BROWSER=None, RHR_CHROME=None):
        if sys.platform == "win32":
            program_files = tmp / "pf"
            local = tmp / "local"
            fake_exe(program_files / r"Microsoft\Edge\Application\msedge.exe")
            fake_exe(local / r"Google\Chrome\Application\chrome.exe")
            real_app_path = browsers._app_path
            browsers._app_path = lambda _exe: None  # the machine's registry is not part of the test
            try:
                with Env(PROGRAMFILES=str(program_files), **{"PROGRAMFILES(X86)": str(tmp / "none")},
                         LOCALAPPDATA=str(local)):
                    found = browsers.installed()
            finally:
                browsers._app_path = real_app_path
            names = [c.name for c in found]
            check(names == ["Chrome", "Edge"], f"Windows installs found in order Chrome, Edge ({names})")
            check(all(c.source == "installed" and os.path.isfile(c.path) for c in found),
                  "each found browser is an existing file")
        elif sys.platform.startswith("linux"):
            bin_dir = tmp / "bin"
            fake_exe(bin_dir / "chromium")
            fake_exe(bin_dir / "microsoft-edge")
            with Env(PATH=str(bin_dir)):
                names = [c.name for c in browsers.installed()]
            check(names == ["Edge", "Chromium"], f"Linux browsers on PATH found in order ({names})")
        else:
            real_home = Path.home
            Path.home = classmethod(lambda _cls: tmp)  # type: ignore[method-assign]
            try:
                fake_exe(tmp / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
                names = [c.name for c in browsers.installed() if c.path.startswith(str(tmp))]
            finally:
                Path.home = real_home  # type: ignore[method-assign]
            check(names == ["Brave"], f"a browser in ~/Applications is found ({names})")

    # RHR_BROWSER is the only candidate, even when it does not exist: a wrong path
    # fails instead of quietly drawing with another browser.
    missing = str(tmp / "no-such-browser.exe")
    with Env(RHR_BROWSER=missing, RHR_CHROME=None):
        found = browsers.candidates()
        check([c.path for c in found] == [missing], "RHR_BROWSER is the only candidate")
        check("does not exist" in browsers.none_found_message(), "a missing RHR_BROWSER is named as missing")
    with Env(RHR_BROWSER=None, RHR_CHROME=missing):
        check([c.path for c in browsers.candidates()] == [missing], "RHR_CHROME is still read")

    # The pinned shell, once in the cache, comes before installed browsers.
    shell = browsers.shell_path()
    if shell is not None:
        real_dir = browsers.BROWSER_DIR
        browsers.BROWSER_DIR = tmp / "cache-browser"
        try:
            fake_exe(browsers.shell_path())
            with Env(RHR_BROWSER=None, RHR_CHROME=None):
                first = browsers.candidates()[0]
            check(first.source == "downloaded" and first.headless_shell,
                  "a downloaded headless shell is tried first")
        finally:
            browsers.BROWSER_DIR = real_dir


def launch_failures(tmp: Path) -> None:
    from rhr import browser_render, browsers

    # A "browser" that exits at start (Python does not know --headless).
    with Env(RHR_BROWSER=sys.executable):
        before = set(Path(tempfile.gettempdir()).glob("rhr-browser-*"))
        try:
            browser_render.launch()
            check(False, "a browser that exits at start fails the launch")
        except RuntimeError as exc:
            check("RHR_BROWSER did not start" in str(exc), f"a browser that exits at start is reported ({exc})")
        after = set(Path(tempfile.gettempdir()).glob("rhr-browser-*"))
        check(after <= before, "a failed start leaves no profile folder behind")

    # With no browser and downloads forbidden, the message says what to do.
    real = browsers.candidates
    browsers.candidates = lambda: []
    try:
        with Env(RHR_BROWSER=None, RHR_CHROME=None, RHR_BROWSER_DOWNLOAD="0"):
            try:
                browser_render.launch()
                check(False, "no browser and no download fails")
            except RuntimeError as exc:
                check("Install Chrome, Edge" in str(exc) and "RHR_BROWSER_DOWNLOAD=0" in str(exc),
                      "no browser and no download says what to install")
    finally:
        browsers.candidates = real


def download(tmp: Path) -> None:
    from rhr import browsers

    plat = browsers.shell_platform()
    if plat is None:
        print("  skip download: no headless shell for this machine")
        return
    exe = "chrome-headless-shell.exe" if plat.startswith("win") else "chrome-headless-shell"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(f"chrome-headless-shell-{plat}/{exe}")
        info.external_attr = 0o755 << 16
        archive.writestr(info, b"fake browser")
        archive.writestr(f"chrome-headless-shell-{plat}/resources.pak", b"data")
    payload = buffer.getvalue()

    class Handler(http.server.BaseHTTPRequestHandler):
        body = payload

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.body)))
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *_args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    saved = (browsers.BROWSER_DIR, browsers.SHELL_URL, dict(browsers.SHELL_DOWNLOADS))
    try:
        browsers.SHELL_URL = f"http://127.0.0.1:{server.server_port}/{{version}}/{{platform}}.zip"
        md5 = base64.b64encode(hashlib.md5(payload).digest()).decode()

        browsers.BROWSER_DIR = tmp / "dl-good"
        browsers.SHELL_DOWNLOADS[plat] = (len(payload), md5)
        path = browsers.download_shell(quiet=True)
        check(path == browsers.shell_path() and path.read_bytes() == b"fake browser",
              "the shell is downloaded and unpacked where RHR looks for it")
        if sys.platform != "win32":
            check(os.access(path, os.X_OK), "the downloaded shell is executable")
        check(not list(browsers.BROWSER_DIR.glob("download-*")), "no download leftovers")
        check(browsers.download_shell(quiet=True) == path, "a second download is not needed")

        browsers.BROWSER_DIR = tmp / "dl-bad"
        browsers.SHELL_DOWNLOADS[plat] = (len(payload), base64.b64encode(b"x" * 16).decode())
        try:
            browsers.download_shell(quiet=True)
            check(False, "a damaged download is refused")
        except RuntimeError as exc:
            check("damaged" in str(exc), "a damaged download is refused")
        check(not browsers.shell_path().exists(), "a damaged download leaves no shell behind")
    finally:
        browsers.BROWSER_DIR, browsers.SHELL_URL = saved[0], saved[1]
        browsers.SHELL_DOWNLOADS.clear()
        browsers.SHELL_DOWNLOADS.update(saved[2])
        server.shutdown()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-browsers-") as directory:
        tmp = Path(directory)
        discovery(tmp)
        launch_failures(tmp)
        download(tmp)
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("browsers: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
