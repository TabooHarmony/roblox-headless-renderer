#!/usr/bin/env python3
"""External tools: where RHR looks for them, and what it says when they are missing.

`rhr setup` downloads Lune and Rojo into <cache>/bin; RHR must find them there when
they are not on PATH, and a missing tool must name the fix (`rhr setup`). The
download itself is not run here (no network in tests).

    python tests/test_tools.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def rhr(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "rhr", *args], capture_output=True, text=True,
                          cwd=str(REPO), env=env, timeout=120)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-tools-") as directory:
        cache = Path(directory)
        # A PATH with Python's own folder only: no lune, no rojo.
        env = {**os.environ, "RHR_CACHE_DIR": str(cache), "PATH": str(Path(sys.executable).parent)}

        proc = rhr(["--version"], env)
        check(proc.returncode == 0 and proc.stdout.startswith("rhr "), f"--version ({proc.stdout.strip()})")

        proc = rhr(["doctor"], env)
        check(proc.returncode == 1, "doctor exits 1 when Lune is missing")
        check("lune      MISSING" in proc.stdout and "rhr setup" in proc.stdout,
              "doctor names Lune as missing and points at `rhr setup`")

        proc = rhr(["ir", str(REPO / "tests" / "fixtures" / "two_screen_guis.rbxmx"),
                    "--out", str(cache / "ir.json")], env)
        check(proc.returncode != 0 and "rhr setup" in proc.stderr,
              f"a command that needs Lune says to run `rhr setup` ({proc.stderr.strip()[-100:]})")

        # A tool in <cache>/bin is found without PATH.
        env_code = f"import os; os.environ['RHR_CACHE_DIR'] = {str(cache)!r}; os.environ['PATH'] = ''"
        name = "lune.exe" if sys.platform == "win32" else "lune"
        (cache / "bin").mkdir()
        (cache / "bin" / name).write_bytes(b"")
        proc = subprocess.run(
            [sys.executable, "-c", f"{env_code}\nfrom rhr.tools import find_tool; print(find_tool('lune'))"],
            capture_output=True, text=True, cwd=str(REPO), timeout=60,
        )
        check(Path(proc.stdout.strip()) == cache / "bin" / name,
              f"find_tool falls back to <cache>/bin ({proc.stdout.strip() or proc.stderr.strip()[-100:]})")

    # A Rokit shim that cannot run here (no rokit.toml lists it) is not a usable tool;
    # the message names the shim and both fixes. Simulated in-process.
    sys.path.insert(0, str(REPO / "src"))
    from rhr import tools

    shim = str(Path.home() / ".rokit" / "bin" / "lune")
    saved = (tools.shutil.which, tools._runs_here, tools.BIN_DIR)
    try:
        with tempfile.TemporaryDirectory(prefix="rhr-shim-") as empty:
            tools.shutil.which = lambda name: shim
            tools._runs_here = lambda path: False
            tools.BIN_DIR = Path(empty)
            check(tools.find_tool("lune") is None, "an unusable Rokit shim is not a usable Lune")
            message = tools.missing_message("lune", "to read Roblox files")
            check("Rokit shim" in message and "rhr setup" in message and "rokit add --global" in message,
                  f"the message names the shim and both fixes ({message[:80]}...)")
            tools._runs_here = lambda path: True
            check(tools.find_tool("lune") == shim, "a Rokit shim that runs here is used")
            # With the pinned copy present, the shim is not even started (it costs ~0.5 s).
            pinned = Path(empty) / tools._exe("lune")
            pinned.write_bytes(b"")
            tools._runs_here = lambda path: (_ for _ in ()).throw(AssertionError("shim was started"))
            check(tools.find_tool("lune") == str(pinned), "the pinned copy wins over a Rokit shim, unstarted")
    finally:
        tools.shutil.which, tools._runs_here, tools.BIN_DIR = saved

    # A missing tool is downloaded the first time a command needs it, unless offline
    # or RHR_TOOL_DOWNLOAD=0 (the download itself is stood in for: no network here).
    import contextlib
    import io

    saved_env = {key: os.environ.get(key) for key in ("RHR_OFFLINE", "RHR_TOOL_DOWNLOAD")}
    saved = (tools.find_tool, tools.download_tool)
    downloaded: list[str] = []
    try:
        tools.find_tool = lambda name: None
        tools.download_tool = lambda name: downloaded.append(name) or Path(f"/cache/bin/{name}")
        os.environ.pop("RHR_OFFLINE", None)
        os.environ.pop("RHR_TOOL_DOWNLOAD", None)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            path = tools.require("lune", "to read Roblox files")
        check(downloaded == ["lune"] and Path(path) == Path("/cache/bin/lune"),
              "a missing Lune is downloaded on first use")
        check("downloading Lune 0.10.5" in stderr.getvalue(), f"with a notice ({stderr.getvalue().strip()})")
        for key, value, why in (("RHR_OFFLINE", "1", "offline"), ("RHR_TOOL_DOWNLOAD", "0", "RHR_TOOL_DOWNLOAD=0")):
            os.environ.pop("RHR_OFFLINE", None)
            os.environ[key] = value
            downloaded.clear()
            try:
                tools.require("lune", "to read Roblox files")
                check(False, f"{why} forbids the download")
            except RuntimeError as exc:
                check(not downloaded and "rhr setup" in str(exc), f"{why} forbids the download and says what to do")
            os.environ.pop(key, None)
        tools.download_tool = lambda name: (_ for _ in ()).throw(OSError("no network"))
        try:
            tools.require("rojo", "to build Rojo projects")
            check(False, "a failed download is an error")
        except RuntimeError as exc:
            check("no network" in str(exc) and "rhr setup" in str(exc), "a failed download says why and what to do")
    finally:
        tools.find_tool, tools.download_tool = saved
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("tools: ok" if not failures else f"tools: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
