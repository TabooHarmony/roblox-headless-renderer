"""The external programs RHR runs, where it finds them, and `rhr setup` / `rhr doctor`.

RHR needs Lune (to read Roblox files) and a Chromium-family browser (for 3D,
found or downloaded by rhr.browsers); Rojo only for Rojo projects. A program on PATH
wins; otherwise RHR looks in <cache>/bin, which is where `rhr setup` puts the exact
versions it is tested with. When neither has it, the first command that needs it
downloads the pinned version there (one line on stderr), unless RHR_TOOL_DOWNLOAD=0
or RHR_OFFLINE=1; `rhr setup` does it ahead of time.
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
from rhr.procs import no_window

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
                              stdin=subprocess.DEVNULL, **no_window())
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
    """(path, runs here) for `name`. An unusable Rokit shim is (its path, False).

    A Rokit shim is only tried when `rhr setup` has not put the pinned copy in
    <cache>/bin: finding out whether a shim runs here means starting it, which costs
    about half a second on every command.
    """
    found = shutil.which(name)
    local = BIN_DIR / _exe(name)
    if found and not _is_rokit_shim(found):
        return found, True
    if local.is_file():
        return str(local), True
    if found and _runs_here(found):
        return found, True
    return found, False


def network_allowed(switch: str) -> bool:
    """Whether RHR may download something by itself: not with RHR_OFFLINE=1 (or
    `--offline`), nor with the thing's own switch (`RHR_TOOL_DOWNLOAD`, ...) set to 0."""
    off = {"0", "false", "no", "off"}
    if os.environ.get("RHR_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return os.environ.get(switch, "").strip().lower() not in off


def require(name: str, purpose: str) -> str:
    """Path to a working `name`, downloading the pinned release the first time.

    Raises RuntimeError with what to do when it is missing and cannot be downloaded.
    """
    found = find_tool(name)
    if found:
        return found
    if not network_allowed("RHR_TOOL_DOWNLOAD"):
        raise RuntimeError(missing_message(name, purpose))
    repo, version = TOOLS[name]
    print(f"rhr: downloading {name.capitalize()} {version} ({purpose}), once", file=sys.stderr, flush=True)
    try:
        return str(download_tool(name))
    except Exception as exc:  # network, HTTP, unsupported platform
        raise RuntimeError(f"downloading {name.capitalize()} {version} failed ({exc}). "
                           + missing_message(name, purpose)) from exc


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
        # Written beside the target and renamed, so an interrupted download never
        # leaves a broken tool where RHR looks for it.
        partial = target.with_name(f"{target.name}.{os.getpid()}.part")
        partial.write_bytes(archive.read(member))
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, target)
    return target


def _tool_version(path: str) -> str:
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL, **no_window())
    except OSError as exc:
        return f"cannot run ({exc})"
    return (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.returncode == 0 else "cannot run"


def browser_report() -> tuple[dict | None, list[str]]:
    """The browser a 3D render would use ({name, version, path}, found by starting it),
    and why each browser before it was skipped."""
    from rhr import browsers
    from rhr.browser_render import launch_args
    from rhr.cdp import Browser, BrowserError

    skipped = []
    for candidate in browsers.candidates():
        try:
            browser = Browser(candidate.path, launch_args(), headless_shell=candidate.headless_shell)
        except (BrowserError, OSError) as exc:
            skipped.append(f"{candidate.name} ({candidate.path}): {exc}")
            continue
        try:
            return {**browsers.describe(candidate, browser.version), "source": candidate.source}, skipped
        finally:
            browser.close()
    return None, skipped


def setup(*, rojo: bool = True, browser: bool = False) -> int:
    """`rhr setup`: fetch what is missing. Returns a process exit code.

    The headless shell is downloaded when no browser is found, or always with
    `browser` (`--browser`: CI and offline machines that should use the pinned build).
    """
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
    from rhr import browsers

    shell = browsers.shell_path()
    if browser or not browsers.candidates():
        if shell is not None and shell.is_file():
            print(f"{'browser':9} ok       headless shell {browsers.SHELL_VERSION}  {shell}")
        elif shell is None:
            print(f"{'browser':9} FAILED   {browsers.none_found_message()}")
            failed = True
        else:
            print(f"{'browser':9} ...      downloading Chrome for Testing's headless shell "
                  f"{browsers.SHELL_VERSION}", flush=True)
            try:
                print(f"{'browser':9} ok       {browsers.download_shell(quiet=True)}")
            except Exception as exc:  # network, HTTP, a damaged download
                print(f"{'browser':9} FAILED   {exc}")
                failed = True
    else:
        found = browsers.candidates()[0]
        print(f"{'browser':9} ok       {found.name}  {found.path}  (`rhr setup --browser` downloads "
              "the pinned headless shell anyway)")
    if sys.platform.startswith("linux") and not failed:
        print("On a bare Linux machine the browser may also need system libraries "
              "(libnss3, libatk-bridge2.0-0, libgbm1, ...): see the README.")
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
        elif network_allowed("RHR_TOOL_DOWNLOAD"):
            print(f"{name:9} none     {name.capitalize()} {TOOLS[name][1]} is downloaded the first time it is "
                  f"needed ({purpose}; `rhr setup` does it now)")
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
    found, skipped = browser_report()
    for reason in skipped:
        print(f"{'browser':9} skipped  {reason}")
    if found:
        print(f"{'browser':9} ok       {found['name']} {found['version']}  {found['path']}")
    else:
        from rhr import browsers

        if browsers.configured() or not browsers.download_allowed() or browsers.shell_platform() is None:
            print(f"{'browser':9} MISSING  needed for 3D (scene, preview, ViewportFrame): "
                  f"{browsers.none_found_message()}")
            problems += 1
        else:
            print(f"{'browser':9} none     the first 3D render downloads Chrome for Testing's headless "
                  f"shell (about 100 MB, once; `rhr setup --browser` does it now)")
    from rhr.studio import studio_install

    studio = studio_install()
    if studio is not None:
        print(f"{'studio':9} ok       {studio}  (its login is used to download assets; "
              "`rhr fetch` says if it is signed out)")
    else:
        print(f"{'studio':9} missing  Roblox Studio is expected: without it previews use stand-in "
              "textures, meshes and unions")
    from rhr.fetch import API_KEY_ENV, api_key

    if api_key():
        print(f"{'apikey':9} set      {API_KEY_ENV}: used for assets the Studio login cannot get")
    else:
        print(f"{'apikey':9} none     without Studio (cloud agents, CI), set {API_KEY_ENV} to an Open "
              "Cloud API key (a user key with legacy-asset:manage) to download assets")
    from rhr import cache

    held = sum(cache.sizes().values())
    print(f"{'cache':9} {held / 1e6:6.0f} MB  {CACHE}  (limit {cache.limit_bytes() / 1e6:.0f} MB; `rhr cache`)")
    from rhr.browser_session import status as worker_status

    worker = worker_status()
    if worker.get("running"):
        print(f"{'worker':9} running  pid {worker.get('pid')}, {worker.get('webgl')} WebGL (warm 3D renders; "
              "stops after 10 idle minutes)")
    else:
        print(f"{'worker':9} stopped  starts on the next 3D render (RHR_PERSISTENT_BROWSER=0 turns it off)")
    if problems:
        print("\nRun `rhr setup` to download what is missing.")
    return 1 if problems else 0
