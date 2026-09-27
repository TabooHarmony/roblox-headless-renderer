"""Launch, render and close a browser many times; run before a release.

    python scripts/browser_stress.py [browser path ...] [--runs N]

With no path, every browser RHR can find (rhr.browsers.candidates) is tried. Each gets
N launch/render/close cycles through rhr.cdp, two at once in the middle, while a
watcher looks for visible windows (Windows only). Prints one JSON line per browser:
failures, timings, windows seen, profile folders left behind. Exit code 1 on any
failure, window or leftover.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rhr import browsers  # noqa: E402
from rhr.browser_render import launch_args  # noqa: E402
from rhr.cdp import PROFILE_PREFIX, READY, Browser  # noqa: E402

PAGE = Path(tempfile.gettempdir()) / "rhr-stress.html"
PAGE.write_text("""<canvas id=c width=64 height=64></canvas><script>
const gl = document.getElementById('c').getContext('webgl2');
if (gl) { gl.clearColor(0.2, 0.4, 0.6, 1); gl.clear(gl.COLOR_BUFFER_BIT); document.documentElement.dataset.rhrReady = 'true'; }
else document.documentElement.dataset.rhrError = 'no webgl2';
</script>""")


def visible_windows() -> set[str]:
    """"<name> <pid>" of browser processes with a visible window."""
    if sys.platform != "win32":
        return set()
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | "
                          "ForEach-Object { \"$($_.ProcessName) $($_.Id)\" }"],
                         capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    names = {"chrome", "msedge", "brave", "chromium", "chrome-headless-shell"}
    return {line.strip() for line in out.splitlines() if line.split(" ")[0].lower() in names}


def one(candidate: browsers.Candidate, index: int, results: list) -> None:
    started = time.perf_counter()
    try:
        browser = Browser(candidate.path, launch_args(), headless_shell=candidate.headless_shell)
        try:
            page = browser.new_page(64, 64)
            page.goto(PAGE.as_uri(), timeout=30)
            page.wait_for(READY, timeout=30)
            error = page.evaluate("document.documentElement.dataset.rhrError || null")
            if error:
                raise RuntimeError(error)
            page.screenshot(Path(tempfile.gettempdir()) / f"rhr-stress-{index}.png")
        finally:
            browser.close()
        results.append(("ok", time.perf_counter() - started))
    except Exception as exc:  # noqa: BLE001 - every failure is a finding
        results.append((f"{type(exc).__name__}: {exc}"[:200], time.perf_counter() - started))


def stress(candidate: browsers.Candidate, runs: int) -> dict:
    profiles = lambda: set(Path(tempfile.gettempdir()).glob(PROFILE_PREFIX + "*"))  # noqa: E731
    before = profiles()
    results: list = []
    windows: set[str] = set()
    already_open = visible_windows()  # the user's own browser windows
    done = threading.Event()

    def watch():
        while not done.is_set():
            windows.update(visible_windows() - already_open)
            done.wait(0.3)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    for index in range(runs):
        if index == runs // 2:  # two at once
            pair = [threading.Thread(target=one, args=(candidate, 1000 + k, results)) for k in range(2)]
            for thread in pair:
                thread.start()
            for thread in pair:
                thread.join()
        one(candidate, index, results)
    done.set()
    watcher.join()
    time.sleep(1)
    failures = [r[0] for r in results if r[0] != "ok"]
    times = sorted(r[1] for r in results if r[0] == "ok")
    return {
        "browser": candidate.name, "path": candidate.path, "runs": len(results), "failures": len(failures),
        "first_failures": failures[:3],
        "median_s": round(times[len(times) // 2], 2) if times else None,
        "max_s": round(times[-1], 2) if times else None,
        "visible_windows_seen": sorted(windows), "profiles_left": len(profiles() - before),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="browsers to test (default: every one RHR finds)")
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()
    found = ([browsers.Candidate(Path(p).stem, p, "argument") for p in args.paths]
             or browsers.candidates())
    bad = False
    for candidate in found:
        report = stress(candidate, args.runs)
        print(json.dumps(report), flush=True)
        bad |= bool(report["failures"] or report["visible_windows_seen"] or report["profiles_left"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
