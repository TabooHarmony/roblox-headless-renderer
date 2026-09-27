"""Which browser RHR draws 3D with, and the pinned headless shell it downloads.

RHR needs one Chromium-family browser. In order, it uses:

1. `RHR_BROWSER` (a path; `RHR_CHROME` is read too, for one release);
2. Chrome for Testing's headless shell at the pinned version, if already downloaded
   (the tests and CI use it: the same build draws the same pixels everywhere);
3. Chrome, Edge, Brave or Chromium installed on the machine;
4. otherwise the pinned headless shell, downloaded once into RHR's cache (about
   100 MB; `RHR_BROWSER_DOWNLOAD=0` forbids it, `rhr setup --browser` does it ahead).

A browser that fails to start (a company policy can turn remote debugging off) is
skipped for the next one; `rhr doctor` says why.
"""

from __future__ import annotations

import base64
import hashlib
import os
import platform
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from rhr.paths import CACHE

# Chrome for Testing's headless shell: the build Playwright 1.58 used before RHR had
# its own client, so pictures stayed the same. (url platform, size in bytes, MD5).
SHELL_VERSION = "145.0.7632.6"
SHELL_DOWNLOADS = {
    "win64": (114_056_639, "C7A/EXVw6y5PT2O7YmfJ0w=="),
    "mac-arm64": (95_530_994, "1bC4PFzkAQVHDSrA8Sz4Lg=="),
    "mac-x64": (99_890_653, "DvEph6HYOeFTjqMYZ7LBqw=="),
    "linux64": (116_288_461, "4krD50Uqqx5NuHHxwVMYDg=="),
}
SHELL_URL = "https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform}/chrome-headless-shell-{platform}.zip"
BROWSER_DIR = CACHE / "browser"

# The browser the last render in this process used ({name, version, path}), for the
# --json report; None when no browser was needed.
used: dict | None = None


@dataclass(frozen=True)
class Candidate:
    name: str       # "Chrome", "Edge", "headless shell", ...
    path: str
    source: str     # "RHR_BROWSER", "downloaded", "installed"

    @property
    def headless_shell(self) -> bool:
        return "headless-shell" in Path(self.path).name or "headless_shell" in Path(self.path).name


def shell_platform() -> str | None:
    """Chrome for Testing's name for this machine, or None where it has no build."""
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if sys.platform == "win32":
        return None if arm else "win64"  # Windows on ARM runs the x64 build, but slowly: prefer Edge
    if sys.platform == "darwin":
        return "mac-arm64" if arm else "mac-x64"
    if sys.platform.startswith("linux"):
        return None if arm else "linux64"  # no Linux ARM build: a system Chromium is needed
    return None


def shell_path(plat: str | None = None) -> Path | None:
    """Where the pinned shell's executable is (or would be) in the cache."""
    plat = plat or shell_platform()
    if plat is None:
        return None
    exe = "chrome-headless-shell.exe" if plat.startswith("win") else "chrome-headless-shell"
    return BROWSER_DIR / f"chrome-headless-shell-{SHELL_VERSION}" / f"chrome-headless-shell-{plat}" / exe


def _windows_installs() -> list[tuple[str, str]]:
    roots = [os.environ.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    relative = [
        ("Chrome", r"Google\Chrome\Application\chrome.exe"),
        ("Edge", r"Microsoft\Edge\Application\msedge.exe"),
        ("Brave", r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        ("Chromium", r"Chromium\Application\chrome.exe"),
    ]
    found: list[tuple[str, str]] = []
    for name, rel in relative:
        for root in roots:
            if root:
                found.append((name, str(Path(root) / rel)))
        registry = _app_path(Path(rel).name)
        if registry:
            found.append((name, registry))
    return found


def _app_path(exe: str) -> str | None:
    """The `App Paths` registry entry for `exe` (how Windows itself finds browsers)."""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value:
                    return value.strip('"')
        except OSError:
            continue
    return None


def _mac_installs() -> list[tuple[str, str]]:
    apps = [("Chrome", "Google Chrome"), ("Edge", "Microsoft Edge"), ("Brave", "Brave Browser"),
            ("Chromium", "Chromium")]
    found = []
    for name, app in apps:
        for root in ("/Applications", str(Path.home() / "Applications")):
            found.append((name, f"{root}/{app}.app/Contents/MacOS/{app}"))
    return found


def _linux_installs() -> list[tuple[str, str]]:
    names = [("Chrome", "google-chrome"), ("Chrome", "google-chrome-stable"), ("Edge", "microsoft-edge"),
             ("Edge", "microsoft-edge-stable"), ("Brave", "brave-browser"), ("Chromium", "chromium"),
             ("Chromium", "chromium-browser")]
    found = []
    for name, command in names:
        path = shutil.which(command)
        if not path:
            continue
        # Snap's Chromium cannot use a profile under /tmp, so it cannot run for RHR.
        if "/snap/" in os.path.realpath(path) or path.startswith("/snap/"):
            continue
        found.append((name, path))
    return found


def installed() -> list[Candidate]:
    """Chromium-family browsers installed on this machine, in order of preference."""
    if sys.platform == "win32":
        pairs = _windows_installs()
    elif sys.platform == "darwin":
        pairs = _mac_installs()
    else:
        pairs = _linux_installs()
    seen: set[str] = set()
    out = []
    for name, path in pairs:
        key = os.path.normcase(os.path.realpath(path))
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        out.append(Candidate(name, path, "installed"))
    return out


def configured() -> str | None:
    return os.environ.get("RHR_BROWSER") or os.environ.get("RHR_CHROME") or None


def candidates() -> list[Candidate]:
    """Every browser RHR would try, in order (the download is not included).

    A set `RHR_BROWSER` is the only candidate: a wrong path fails instead of quietly
    drawing with another browser.
    """
    chosen = configured()
    if chosen:
        name = "headless shell" if "headless" in Path(chosen).name.lower() else Path(chosen).stem
        return [Candidate(name, chosen, "RHR_BROWSER")]
    out = []
    shell = shell_path()
    if shell is not None and shell.is_file():
        out.append(Candidate("headless shell", str(shell), "downloaded"))
    return out + installed()


def download_allowed() -> bool:
    return os.environ.get("RHR_BROWSER_DOWNLOAD", "").strip().lower() not in {"0", "false", "no", "off"}


def none_found_message() -> str:
    if configured():
        return f"RHR_BROWSER is set to {configured()}, which does not exist"
    advice = "Install Chrome, Edge, Brave or Chromium"
    if shell_platform() is None:
        return f"no Chromium-family browser found, and there is no headless shell to download for this machine. {advice}."
    return (f"no Chromium-family browser found and downloading the headless shell is turned off "
            f"(RHR_BROWSER_DOWNLOAD=0). {advice}, run `rhr setup --browser`, or set RHR_BROWSER.")


def download_shell(*, quiet: bool = False) -> Path:
    """Download and unpack the pinned headless shell into the cache; its executable path."""
    import requests

    plat = shell_platform()
    if plat is None:
        raise RuntimeError(none_found_message())
    target = shell_path(plat)
    assert target is not None
    if target.is_file():
        return target
    size, md5 = SHELL_DOWNLOADS[plat]
    url = SHELL_URL.format(version=SHELL_VERSION, platform=plat)
    if not quiet:
        print(f"rhr: downloading the headless browser for 3D (Chrome for Testing {SHELL_VERSION}, "
              f"about {size / 1e6:.0f} MB), once", file=sys.stderr, flush=True)
    BROWSER_DIR.mkdir(parents=True, exist_ok=True)
    version_dir = target.parents[1]
    with tempfile.TemporaryDirectory(prefix="download-", dir=BROWSER_DIR) as work:
        archive = Path(work) / "shell.zip"
        digest = hashlib.md5()
        received = 0
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_content(1 << 20):
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
        if received != size or base64.b64encode(digest.digest()).decode() != md5:
            raise RuntimeError(f"the headless shell download from {url} is damaged "
                               f"({received} bytes, expected {size}); try again")
        unpacked = Path(work) / "unpacked"
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                path = Path(zipped.extract(info, unpacked))
                mode = (info.external_attr >> 16) & 0o777
                if mode and not info.is_dir():
                    path.chmod(mode)
        if sys.platform != "win32":
            executable = unpacked / target.parent.name / target.name
            executable.chmod(executable.stat().st_mode | 0o111)
        try:
            os.replace(unpacked, version_dir)
        except OSError:
            if not target.is_file():  # not another RHR finishing the same download first
                raise
    if not target.is_file():
        raise RuntimeError(f"the headless shell archive did not contain {target.name}")
    if not quiet:
        print(f"rhr: headless browser ready at {target}", file=sys.stderr, flush=True)
    return target


def describe(candidate: Candidate, version: str) -> dict:
    return {"name": candidate.name, "version": version, "path": candidate.path}
