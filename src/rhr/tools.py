"""The external programs RHR runs, where it finds them, and `rhr setup` / `rhr doctor`.

RHR needs Lune (to read Roblox files) and Chromium (for 3D); Rojo only for Rojo
projects. A program on PATH wins; otherwise RHR looks in <cache>/bin, which is
where `rhr setup` puts the exact versions it is tested with. Nothing is downloaded
unless the user runs `rhr setup`.
"""

from __future__ import annotations

import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

from rhr.paths import CACHE

BIN_DIR = CACHE / "bin"

# (GitHub repo, version) of each tool `rhr setup` installs.
TOOLS = {
    "lune": ("lune-org/lune", "0.10.5"),
    "rojo": ("rojo-rbx/rojo", "7.7.0"),
}


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _is_rokit_shim(path: str) -> bool:
    return any(part.lower() == ".rokit" for part in Path(path).parts)


def _runs_here(path: str) -> bool:
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def find_tool(name: str) -> str | None:
    """Path to a working `name`: on PATH, else in <cache>/bin, else None.

    A Rokit shim on PATH only runs inside a folder whose rokit.toml lists the tool
    (unless it was added with `rokit add --global`). Roblox developers commonly have
    Lune and Rojo that way, and run RHR from their own project, so a shim that cannot
    run here is skipped in favour of the copy `rhr setup` downloads.
    """
    path, usable = tool_status(name)
    return path if usable else None


def tool_status(name: str) -> tuple[str | None, bool]:
    """(path, runs here) for `name`. An unusable Rokit shim is (its path, False)."""
    found = shutil.which(name)
    if found and (not _is_rokit_shim(found) or _runs_here(found)):
        return found, True
    local = BIN_DIR / _exe(name)
    if local.is_file():
        return str(local), True
    return found, False


def missing_message(name: str, purpose: str) -> str:
    repo, version = TOOLS[name]
    found, _ = tool_status(name)
    if found:  # a Rokit shim that does not run outside a project listing it
        return (
            f"`{name}` at {found} is a Rokit shim that does not run in this folder (no "
            f"rokit.toml here lists it). Run `rhr setup` to download {name.capitalize()} "
            f"{version} for RHR, or `rokit add --global {repo}@{version}`."
        )
    return (
        f"`{name}` was not found. RHR needs {name.capitalize()} {version} {purpose}. "
        f"Run `rhr setup` to download it, or install it yourself "
        f"(https://github.com/{repo}/releases/tag/v{version}) and put it on PATH."
    )


def _release_target() -> str:
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if sys.platform == "win32":
        system = "windows"
    elif sys.platform == "darwin":
        system = "macos"
    elif sys.platform.startswith("linux"):
        system = "linux"
    else:
        raise RuntimeError(f"no prebuilt Lune/Rojo for {sys.platform}; install them yourself")
    return f"{system}-{arch}"


def download_tool(name: str) -> Path:
    """Download the pinned release of `name` into <cache>/bin and return its path."""
    import requests

    repo, version = TOOLS[name]
    tool = repo.split("/")[1]
    url = (
        f"https://github.com/{repo}/releases/download/v{version}/"
        f"{tool}-{version}-{_release_target()}.zip"
    )
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / _exe(name)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        member = next(
            (m for m in archive.namelist() if Path(m).name == _exe(name)), None
        )
        if member is None:
            raise RuntimeError(f"{url} has no {_exe(name)} inside")
        target.write_bytes(archive.read(member))
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def _tool_version(path: str) -> str:
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    except OSError as exc:
        return f"cannot run ({exc})"
    return (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.returncode == 0 else "cannot run"


def chromium_path() -> str | None:
    """Playwright's Chromium executable if it is installed, else None."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception:
        return None
    return path if path and Path(path).exists() else None


def _install_chromium() -> int:
    args = [sys.executable, "-m", "playwright", "install", "chromium"]
    if sys.platform.startswith("linux") and os.geteuid() == 0:
        args.insert(-1, "--with-deps")
    return subprocess.run(args).returncode


def setup(*, rojo: bool = True) -> int:
    """`rhr setup`: fetch what is missing. Returns a process exit code."""
    failed = False
    for name in ["lune", "rojo"] if rojo else ["lune"]:
        found = find_tool(name)
        if found:
            print(f"{name:9} ok       {found}")
            continue
        print(f"{name:9} ...      downloading {TOOLS[name][0]} v{TOOLS[name][1]}", flush=True)
        try:
            print(f"{name:9} ok       {download_tool(name)}")
        except Exception as exc:  # network, HTTP, unsupported platform
            print(f"{name:9} FAILED   {exc}")
            failed = True
    if chromium_path():
        print(f"{'chromium':9} ok       {chromium_path()}")
    else:
        print(f"{'chromium':9} ...      python -m playwright install chromium", flush=True)
        if _install_chromium() != 0:
            print(f"{'chromium':9} FAILED   run `python -m playwright install --with-deps chromium`")
            failed = True
    if sys.platform.startswith("linux") and not failed:
        print("On a bare Linux machine Chromium may also need system libraries: "
              "`python -m playwright install-deps chromium` (needs sudo).")
    return 1 if failed else 0


def doctor() -> int:
    """`rhr doctor`: what RHR can find, what it will use, and what is missing."""
    from rhr import __version__

    problems = 0
    print(f"rhr       {__version__}  (Python {platform.python_version()}, {sys.platform})")
    for name, purpose, required in (
        ("lune", "to read Roblox files", True),
        ("rojo", "for Rojo projects only", False),
    ):
        path, usable = tool_status(name)
        if usable:
            print(f"{name:9} ok       {_tool_version(path)}  {path}")
        elif path:
            print(f"{name:9} {'BROKEN' if required else 'broken'}   {path} is a Rokit shim that "
                  "does not run in this folder")
            problems += required
        else:
            print(f"{name:9} {'MISSING' if required else 'missing'}  needed {purpose}")
            problems += required
    try:
        import skia

        print(f"{'skia':9} ok       {skia.__version__}")
    except Exception as exc:  # a missing libEGL/libGL on Linux shows up here
        print(f"{'skia':9} BROKEN   {exc}")
        if sys.platform.startswith("linux"):
            print("          install libegl1 and libgl1 (apt) or mesa-libEGL/mesa-libGL")
        problems += 1
    chromium = chromium_path()
    if chromium:
        print(f"{'chromium':9} ok       {chromium}")
    else:
        print(f"{'chromium':9} MISSING  needed for 3D (scene, preview, ViewportFrame)")
        problems += 1
    from rhr.studio import studio_install

    studio = studio_install()
    if studio is not None:
        print(f"{'studio':9} ok       {studio}  (its login is used to download assets; "
              "`rhr fetch` says if it is signed out)")
    else:
        print(f"{'studio':9} missing  Roblox Studio is expected: without it previews use stand-in "
              "textures, meshes and unions")
    print(f"{'cache':9}          {CACHE}")
    if problems:
        print("\nRun `rhr setup` to download what is missing.")
    return 1 if problems else 0
