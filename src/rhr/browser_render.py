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


def capture(browser, *, url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    """Load `url` in a fresh context, wait for the page's ready signal, save a PNG."""
    context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
    try:
        page = context.new_page()
        # What the page complained about, so a page that never gets ready says why.
        problems: list[str] = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        page.goto(url, wait_until="load", timeout=TIMEOUT_MS)
        try:
            page.wait_for_function(_READY, timeout=TIMEOUT_MS)
        except Exception as exc:  # playwright's TimeoutError
            if not problems:
                raise
            raise RuntimeError("browser page never got ready: " + " | ".join(problems[-3:])[:2000]) from exc
        error = page.evaluate("() => document.documentElement.dataset.rhrError || null")
        if error:
            raise RuntimeError(f"browser page error: {error}")
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), omit_background=transparent, animations="disabled", timeout=TIMEOUT_MS)
    finally:
        context.close()


def render_once(*, url: str, out: Path, width: int, height: int, transparent: bool) -> None:
    """Launch Chromium, capture one page, shut Chromium down."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright)
        try:
            capture(browser, url=url, out=out, width=width, height=height, transparent=transparent)
        finally:
            browser.close()
