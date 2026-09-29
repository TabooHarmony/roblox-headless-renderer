"""One way to turn an RHR browser page into a PNG, shared by every render path.

Both the one-shot renderer (a fresh browser per call) and the persistent worker
(`rhr browser start`) go through `launch()` and `capture()`, so the two can only
differ in how long the browser lives, never in how a page is drawn or captured.
RHR drives the browser itself over the DevTools protocol (rhr.cdp); which browser it
uses is decided in rhr.browsers.

A page is captured once it sets `data-rhr-ready` (or fails with `data-rhr-error`),
not after a fixed time budget, so a slow machine waits instead of screenshotting a
half-built scene. WebGL runs on the machine's GPU, or on SwiftShader (software)
with `RHR_WEBGL=software` so pixels do not depend on the host GPU or driver.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from rhr.cdp import READY, Browser, BrowserError

_COMMON_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--hide-scrollbars",
    "--ignore-gpu-blocklist",
    # Lets WebGL fall back to software on a machine without a usable GPU.
    "--enable-unsafe-swiftshader",
    # A page in a background tab of a full browser must still draw at full speed.
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
]


def webgl_mode() -> str:
    """'gpu' (default: the machine's GPU, about 8x faster) or 'software' (SwiftShader).

    `RHR_WEBGL=software` draws on the CPU, so pixels do not depend on the GPU or its
    driver; tests and CI use it. A GPU render differs from a software one by well under
    1% of pixels, by a shade or two.
    """
    value = os.environ.get("RHR_WEBGL", "").strip().lower()
    return "software" if value in {"software", "swiftshader", "cpu"} else "gpu"


def _userns_blocked() -> bool:
    """Whether Linux keeps unprivileged processes out of user namespaces, which the
    sandbox of a browser without its own permission (the downloaded headless shell)
    needs: Ubuntu 23.10+ does this through AppArmor, and the shell then exits at start."""
    for path, blocked in (("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", "1"),
                          ("/proc/sys/kernel/unprivileged_userns_clone", "0")):
        try:
            if Path(path).read_text().strip() == blocked:
                return True
        except OSError:
            pass
    return False


def sandboxed(headless_shell: bool = False) -> bool:
    """Whether the browser keeps its sandbox: it decodes images and meshes from the
    internet. Chromium's sandbox cannot start as root on Linux (containers, CI images),
    nor for the headless shell where user namespaces are blocked (Ubuntu 24.04);
    `RHR_BROWSER_SANDBOX=0` turns it off where it fails for another reason."""
    if os.environ.get("RHR_BROWSER_SANDBOX", "").strip().lower() in {"0", "no", "off", "false"}:
        return False
    if not sys.platform.startswith("linux"):
        return True
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return False
    return not (headless_shell and _userns_blocked())


def launch_args(headless_shell: bool = False) -> list[str]:
    args = _COMMON_ARGS if sandboxed(headless_shell) else [*_COMMON_ARGS, "--no-sandbox"]
    if webgl_mode() == "software":
        return [*args, "--use-angle=swiftshader"]
    return [*args, "--enable-gpu"]


# A slow machine drawing WebGL in software needs well over the old 45 s.
TIMEOUT_S = 150


def launch() -> tuple[Browser, dict]:
    """Start the first browser that works (rhr.browsers), headless.

    Returns the browser and what it is ({name, version, path}). A browser that fails
    to start is skipped; with none left, the pinned headless shell is downloaded
    (unless RHR_BROWSER_DOWNLOAD=0 or RHR_BROWSER is set).
    """
    from rhr import browsers, cdp

    cdp.remove_stale_profiles()
    failures = []
    for candidate in browsers.candidates():
        try:
            browser = Browser(candidate.path, launch_args(candidate.headless_shell), headless_shell=candidate.headless_shell)
        except (BrowserError, OSError) as exc:
            failures.append(f"{candidate.name} ({candidate.path}): {exc}")
            continue
        return browser, browsers.describe(candidate, browser.version)
    if browsers.configured():
        raise RuntimeError(f"the browser in RHR_BROWSER did not start: {'; '.join(failures)}"
                           if failures else browsers.none_found_message())
    if not browsers.download_allowed():
        raise RuntimeError(browsers.none_found_message()
                           + (f" Tried: {'; '.join(failures)}" if failures else ""))
    path = browsers.download_shell()
    candidate = browsers.Candidate("headless shell", str(path), "downloaded")
    browser = Browser(candidate.path, launch_args(True), headless_shell=True)
    return browser, browsers.describe(candidate, browser.version)


def _problems(page) -> str:
    return " | ".join(page.problems[-3:])[:2000]


def capture(browser: Browser, *, url: str, out: Path, width: int, height: int, transparent: bool) -> dict:
    """Load `url` in a fresh tab, wait for the page's ready signal, save a PNG.

    Returns how long each step took, in seconds (for RHR_PROFILE).
    """
    timings: dict[str, float] = {}
    started = time.perf_counter()
    page = browser.new_page(width, height)
    try:
        timings["new page"] = time.perf_counter() - started
        step = time.perf_counter()
        page.goto(url, timeout=TIMEOUT_S)
        timings["page load (scripts)"] = time.perf_counter() - step
        step = time.perf_counter()
        try:
            page.wait_for(READY, timeout=TIMEOUT_S)
        except TimeoutError as exc:
            if not page.problems:
                raise RuntimeError(str(exc)) from exc
            raise RuntimeError("browser page never got ready: " + _problems(page)) from exc
        error = page.evaluate("document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"browser page error: {error}")
        timings["page work until ready"] = time.perf_counter() - step
        step = time.perf_counter()
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(out, transparent=transparent)
        timings["screenshot"] = time.perf_counter() - step
    finally:
        page.close()
    return timings


class KeptScenePage:
    """The warm worker's 3D page, loaded once and asked for one scene after another.

    The page (rhr/scene/scene.js with `persistent=1`) keeps its scripts, compiled shaders
    and decoded textures between renders and resets everything about the scene; each
    render's data comes from that render's own local server (`base`). Static files
    (the page, three.js, look-alike materials) are served from here, at an address that
    stays the same for the worker's life.
    """

    RENDER_TIMEOUT_S = 60

    def __init__(self, browser: Browser, *, page_query: str = "persistent=1", transparent: bool = False):
        self.browser = browser
        self.static = None
        self.page = None
        self.renders = 0
        # `rhr icons`: a page whose canvas can be see-through, saved with its alpha.
        self.page_query = page_query
        self.transparent = transparent

    def _serve_static(self) -> int:
        if self.static is None:
            import functools
            import http.server
            import threading

            from rhr.paths import PACKAGE

            class Static(http.server.SimpleHTTPRequestHandler):
                extensions_map = {
                    **http.server.SimpleHTTPRequestHandler.extensions_map,
                    ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm",
                    ".json": "application/json",
                }

                def log_message(self, *_args):
                    return

            handler = functools.partial(Static, directory=str(PACKAGE))
            self.static = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=self.static.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self.static.server_address[1]

    def _open(self, width: int, height: int) -> None:
        port = self._serve_static()
        self.page = self.browser.new_page(width, height)
        self.page.goto(f"http://127.0.0.1:{port}/scene/index.html?{self.page_query}", timeout=TIMEOUT_S)
        self.page.wait_for("document.documentElement.dataset.rhrPersistent === 'ready'", timeout=TIMEOUT_S)
        self.renders = 0

    def close(self) -> None:
        if self.page is not None:
            try:
                self.page.close()
            except Exception:  # noqa: BLE001 - closing a broken page must not fail
                pass
        self.page = None

    def render(self, *, query: str, base: str, out: Path, width: int, height: int) -> dict:
        """Draw one scene; raise on any failure (the caller then uses a fresh page)."""
        import json

        timings: dict[str, float] = {}
        started = time.perf_counter()
        if self.page is None:
            self._open(width, height)
            timings["kept page opened"] = time.perf_counter() - started
        else:
            self.page.set_size(width, height)
        self.page.problems.clear()
        step = time.perf_counter()
        # Started without waiting on it, so the wait below can time out.
        args = json.dumps({"query": query, "base": base, "width": width, "height": height})
        self.page.evaluate(f"void window.rhrRender({args})")
        try:
            self.page.wait_for(READY, timeout=self.RENDER_TIMEOUT_S)
        except TimeoutError as exc:
            raise RuntimeError("kept page never got ready: " + _problems(self.page)) from exc
        error = self.page.evaluate("document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"kept page error: {error}")
        timings["page work until ready (kept page)"] = time.perf_counter() - step
        step = time.perf_counter()
        out.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(out, transparent=self.transparent)
        timings["screenshot"] = time.perf_counter() - step
        self.renders += 1
        return timings

    def view(self, *, query: str, out: Path) -> dict:
        """Another view of the scene the last render built (rhrView on the page): only
        the camera and what is drawn for it change. Raise on any failure."""
        import json

        if self.page is None:
            raise RuntimeError("no kept scene to draw another view of")
        timings: dict[str, float] = {}
        self.page.problems.clear()
        step = time.perf_counter()
        self.page.evaluate(f"void window.rhrView({json.dumps({'query': query})})")
        try:
            self.page.wait_for(READY, timeout=self.RENDER_TIMEOUT_S)
        except TimeoutError as exc:
            raise RuntimeError("kept page never got ready for another view: " + _problems(self.page)) from exc
        error = self.page.evaluate("document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"kept page error: {error}")
        timings["another view until ready (kept page)"] = time.perf_counter() - step
        step = time.perf_counter()
        out.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(out, transparent=self.transparent)
        timings["screenshot"] = time.perf_counter() - step
        return timings


def render_once(*, url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    """Launch a browser, capture one page, shut the browser down."""
    from rhr import browsers
    from rhr.profile import add

    started = time.perf_counter()
    browser, info = launch()
    browsers.used = info
    add(f"browser launch (one-shot, {info['name']})", time.perf_counter() - started)
    try:
        for name, seconds in capture(browser, url=url, out=out, width=width, height=height, transparent=transparent).items():
            add(f"  {name}", seconds)
    finally:
        browser.close()
