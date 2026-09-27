#!/usr/bin/env python3
"""No browser outlives the RHR process that started it.

A child Python starts a browser through rhr.cdp and is then killed outright (no
cleanup code runs); every process started with that browser's profile must be gone
within a few seconds. Also: a normal close removes the profile folder.

    python tests/test_browser_lifetime.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []

CHILD = """
import json, sys, time
from rhr import browser_render
browser, info = browser_render.launch()
page = browser.new_page(200, 100)
page.goto("about:blank", 30)
time.sleep(1)  # let the helper processes start
print(json.dumps({"pid": browser.proc.pid, "profile": browser.profile}), flush=True)
time.sleep(600)
"""


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def process_table() -> dict[int, int]:
    """{pid: parent pid} of every running process."""
    if sys.platform == "win32":
        script = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                             text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    else:
        out = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True, timeout=30).stdout
    table = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = int(parts[1])
    return table


def tree(root: int) -> set[int]:
    """`root` and every process below it."""
    table = process_table()
    found = {root} if root in table else set()
    grew = True
    while grew:
        more = {pid for pid, parent in table.items() if parent in found} - found
        found |= more
        grew = bool(more)
    return found


def main() -> int:
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True,
                             cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    line = child.stdout.readline()
    try:
        started = json.loads(line)
    except json.JSONDecodeError:
        child.kill()
        check(False, f"the child started a browser ({line!r})")
        return 1
    running = tree(started["pid"])
    check(len(running) >= 2, f"the browser runs, with its helper processes ({len(running)} processes)")

    child.kill()  # TerminateProcess / SIGKILL: no atexit, no finally
    child.wait(10)
    deadline = time.monotonic() + 15
    left = running
    while time.monotonic() < deadline:
        left = running & set(process_table())
        if not left:
            break
        time.sleep(0.5)
    check(not left, f"every browser process ends with the process that started it ({len(left)} left)")

    # The killed process could not remove its profile; the next launch does.
    from rhr import cdp

    cdp.remove_stale_profiles(min_age_s=0)
    check(not os.path.exists(started["profile"]), "a killed RHR's profile is removed by the next launch")

    # A normal close ends the browser and removes its profile.
    from rhr import browser_render

    browser, info = browser_render.launch()
    profile = browser.profile
    browser.close()
    check(browser.proc.poll() is not None, f"close ends the browser ({info['name']} {info['version']})")
    check(not os.path.exists(profile), "close removes the profile folder")
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("browser lifetime: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
