#!/usr/bin/env python3
"""`rhr view`: the local server behind the page (rhr.view).

Runs `rhr view <copy of examples/tower.rbxmx> --no-open` and talks to it over HTTP
as the page does: the address is printed on stdout, the page and the scene's IR are
served, `/__rhr_version__` moves on when the file changes, a broken file is reported
there without stopping the server, and a fixed one is drawn again. The drawing and
the controls are the scene page's own (checked by hand and by the scene tests); no
browser is needed here.

    python tests/test_view.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def version(base: str) -> dict:
    return json.loads(get(base + "/__rhr_version__"))


def wait_version(base: str, before: int, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = version(base)
        if state["version"] != before:
            return state
        time.sleep(0.2)
    return version(base)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-view-") as directory:
        model = Path(directory) / "tower.rbxmx"
        shutil.copy(REPO / "examples" / "tower.rbxmx", model)
        env = {**os.environ, "RHR_SERVER": "0"}
        proc = subprocess.Popen([sys.executable, "-m", "rhr", "view", str(model), "--no-open", "--offline"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                env=env, cwd=directory)
        try:
            url = proc.stdout.readline().strip()
            check(url.startswith("http://127.0.0.1:") and "interactive=1" in url, f"the address is printed: {url}")
            base = url.split("/scene/")[0]
            check(b"scene.js" in get(url.split("?")[0]), "the scene page is served")
            ir = json.loads(get(base + "/__rhr_ir__.json"))
            check(bool(ir.get("roots")), "the scene's IR is served")
            first = version(base)
            check(first == {"version": 0, "error": None}, f"version starts at 0: {first}")

            text = model.read_text(encoding="utf-8")
            model.write_text(text.replace("<R>0.4196</R>", "<R>0.9</R>", 1), encoding="utf-8")
            state = wait_version(base, 0)
            check(state == {"version": 1, "error": None}, f"a change moves the version on: {state}")

            model.write_text("<roblox>broken", encoding="utf-8")
            state = wait_version(base, 1)
            check(state["version"] == 2 and bool(state["error"]), f"a broken file is reported: {state}")
            check(proc.poll() is None, "the server keeps running")

            model.write_text(text, encoding="utf-8")
            state = wait_version(base, 2)
            check(state == {"version": 3, "error": None}, f"a fixed file is drawn again: {state}")
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("view: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
