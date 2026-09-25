"""One way to turn an RHR browser page into a PNG, shared by every render path.

Both the one-shot renderer (a fresh Chromium per call) and the persistent worker
(`rhr browser start`) go through `launch()` and `capture()`, so the two can only
differ in how long Chromium lives, never in how a page is drawn or captured.

A page is captured once it sets `data-rhr-ready` (or fails with `data-rhr-error`),
not after a fixed time budget, so a slow machine waits instead of screenshotting a
half-built scene. WebGL runs on the machine's GPU, or on SwiftShader (software)
with `RHR_WEBGL=software` so pixels do not depend on the host GPU or driver.
"""

from __future__ import annotations

import os
from pathlib import Path

_COMMON_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--hide-scrollbars",
    "--ignore-gpu-blocklist",
    # Lets WebGL fall back to software on a machine without a usable GPU.
    "--enable-unsafe-swiftshader",
]


def webgl_mode() -> str:
    """'gpu' (default: the machine's GPU, about 8x faster) or 'software' (SwiftShader).

    `RHR_WEBGL=software` draws on the CPU, so pixels do not depend on the GPU or its
    driver; tests and CI use it. A GPU render differs from a software one by well under
    1% of pixels, by a shade or two.
    """
    value = os.environ.get("RHR_WEBGL", "").strip().lower()
    return "software" if value in {"software", "swiftshader", "cpu"} else "gpu"


def launch_args() -> list[str]:
    if webgl_mode() == "software":
        return [*_COMMON_ARGS, "--use-angle=swiftshader"]
    return [*_COMMON_ARGS, "--enable-gpu"]


# A slow machine drawing WebGL in software needs well over the old 45 s.
TIMEOUT_MS = 150_000

_READY = """() => document.documentElement.dataset.rhrReady === 'true'
             || Boolean(document.documentElement.dataset.rhrError)"""


def launch(playwright):
    """Start headless Chromium: Playwright's managed build, or `RHR_CHROME` if set."""
    executable = os.environ.get("RHR_CHROME") or None
    try:
        return playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=launch_args(),
        )
    except Exception as exc:  # playwright raises its own Error type
        if executable is None and "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Chromium for Playwright is not installed; run "
                "`python -m playwright install chromium` (or set RHR_CHROME)"
            ) from exc
        raise


def _screenshot(context, page, out: Path, transparent: bool) -> None:
    """Save the page as a PNG: Chromium's own capture with its fast PNG encoder.

    Same pixels as Playwright's screenshot, lighter compression, and about a third of
    the time on a full-size frame. Falls back to Playwright's if the command fails.
    """
    import base64

    try:
        session = context.new_cdp_session(page)
        try:
            if transparent:
                session.send("Emulation.setDefaultBackgroundColorOverride",
                             {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
            result = session.send("Page.captureScreenshot", {
                "format": "png", "optimizeForSpeed": True, "captureBeyondViewport": False,
            })
        finally:
            session.detach()
        out.write_bytes(base64.b64decode(result["data"]))
    except Exception:  # noqa: BLE001 - any failure: the slower, always-available path
        page.screenshot(path=str(out), omit_background=transparent, animations="disabled", timeout=TIMEOUT_MS)


def capture(browser, *, url: str, out: Path, width: int, height: int, transparent: bool) -> dict:
    """Load `url` in a fresh context, wait for the page's ready signal, save a PNG.

    Returns how long each step took, in seconds (for RHR_PROFILE).
    """
    import time

    timings: dict[str, float] = {}
    started = time.perf_counter()
    context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
    try:
        page = context.new_page()
        # What the page complained about, so a page that never gets ready says why.
        problems: list[str] = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        timings["new page"] = time.perf_counter() - started
        step = time.perf_counter()
        page.goto(url, wait_until="load", timeout=TIMEOUT_MS)
        timings["page load (scripts)"] = time.perf_counter() - step
        step = time.perf_counter()
        try:
            page.wait_for_function(_READY, timeout=TIMEOUT_MS)
        except Exception as exc:  # playwright's TimeoutError
            if not problems:
                raise
            raise RuntimeError("browser page never got ready: " + " | ".join(problems[-3:])[:2000]) from exc
        error = page.evaluate("() => document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"browser page error: {error}")
        timings["page work until ready"] = time.perf_counter() - step
        step = time.perf_counter()
        out.parent.mkdir(parents=True, exist_ok=True)
        _screenshot(context, page, out, transparent)
        timings["screenshot"] = time.perf_counter() - step
    finally:
        context.close()
    return timings


class KeptScenePage:
    """The warm worker's 3D page, loaded once and asked for one scene after another.

    The page (rhr/scene/scene.js with `persistent=1`) keeps its scripts, compiled shaders
    and decoded textures between renders and resets everything about the scene; each
    render's data comes from that render's own local server (`base`). Static files
    (the page, three.js, look-alike materials) are served from here, at an address that
    stays the same for the worker's life.
    """

    RENDER_TIMEOUT_MS = 60_000

    def __init__(self, browser):
        self.browser = browser
        self.static = None
        self.context = None
        self.page = None
        self.problems: list[str] = []
        self.renders = 0

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
        self.context = self.browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
        self.page = self.context.new_page()
        self.problems = []
        self.page.on("pageerror", lambda error: self.problems.append(str(error)))
        self.page.on("console", lambda message: self.problems.append(message.text) if message.type == "error" else None)
        self.page.goto(f"http://127.0.0.1:{port}/scene/index.html?persistent=1", wait_until="load", timeout=TIMEOUT_MS)
        self.page.wait_for_function("() => document.documentElement.dataset.rhrPersistent === 'ready'", timeout=TIMEOUT_MS)
        self.renders = 0

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:  # noqa: BLE001 - closing a broken page must not fail
                pass
        self.context = None
        self.page = None

    def render(self, *, query: str, base: str, out: Path, width: int, height: int) -> dict:
        """Draw one scene; raise on any failure (the caller then uses a fresh page)."""
        import time

        timings: dict[str, float] = {}
        started = time.perf_counter()
        if self.page is None:
            self._open(width, height)
            timings["kept page opened"] = time.perf_counter() - started
        else:
            self.page.set_viewport_size({"width": width, "height": height})
        self.problems = []
        step = time.perf_counter()
        # Started without waiting on it, so the wait below can time out.
        self.page.evaluate(
            "args => { window.rhrRender(args); }",
            {"query": query, "base": base, "width": width, "height": height},
        )
        try:
            self.page.wait_for_function(_READY, timeout=self.RENDER_TIMEOUT_MS)
        except Exception as exc:  # playwright's TimeoutError
            raise RuntimeError("kept page never got ready: " + " | ".join(self.problems[-3:])[:2000]) from exc
        error = self.page.evaluate("() => document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"kept page error: {error}")
        timings["page work until ready (kept page)"] = time.perf_counter() - step
        step = time.perf_counter()
        out.parent.mkdir(parents=True, exist_ok=True)
        _screenshot(self.context, self.page, out, False)
        timings["screenshot"] = time.perf_counter() - step
        self.renders += 1
        return timings


def render_once(*, url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    """Launch Chromium, capture one page, shut Chromium down."""
    from playwright.sync_api import sync_playwright

    import time

    from rhr.profile import add

    started = time.perf_counter()
    with sync_playwright() as playwright:
        browser = launch(playwright)
        add("chromium launch (one-shot)", time.perf_counter() - started)
        try:
            for name, seconds in capture(browser, url=url, out=out, width=width, height=height, transparent=transparent).items():
                add(f"  {name}", seconds)
        finally:
            browser.close()
