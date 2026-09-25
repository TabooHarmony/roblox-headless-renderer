"""Client/manager for RHR's optional long-lived browser worker."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

# The directory that contains the `rhr` package, so the worker imports this copy.
IMPORT_ROOT = Path(__file__).resolve().parents[1]
# In the cache, so a separate cache (RHR_CACHE_DIR, as the tests use) has its own worker.
from rhr.paths import CACHE  # noqa: E402

SESSION_ROOT = CACHE / "browser-session"
PID_FILE = SESSION_ROOT / "pid"
PORT_FILE = SESSION_ROOT / "port"
STARTUP_TIMEOUT_S = 60
TOKEN_FILE = SESSION_ROOT / "token"
LOG_FILE = SESSION_ROOT / "daemon.log"


def code_stamp() -> str:
    """What the worker's code is: RHR's version and the files its page and worker run.

    A worker keeps its page loaded between renders, so one started before RHR was
    updated (or edited) would keep drawing with the old code; a client that sees another
    stamp replaces the worker.
    """
    import hashlib

    from rhr import __version__

    digest = hashlib.sha1(__version__.encode())
    package = Path(__file__).resolve().parent
    files = [*sorted((package / "scene").glob("*.js")), *sorted((package / "particles").glob("*.js")),
             package / "browser_render.py", package / "browser_daemon.py"]
    for path in files:
        try:
            info = path.stat()
        except OSError:
            continue
        digest.update(f"{path.name}:{info.st_size}:{info.st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) sends CTRL_C_EVENT on Windows; ask the kernel instead.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _terminate(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass


def _read_state() -> tuple[int, int, str] | None:
    try:
        pid = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
        token = TOKEN_FILE.read_text().strip()
    except (OSError, ValueError):
        return None
    if not token or not _pid_alive(pid):
        return None
    return pid, port, token


def _request(
    port: int,
    token: str,
    method: str,
    path: str,
    payload: dict | None = None,
    timeout: float = 180,
) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-RHR-Token": token}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        data = json.loads(raw or b"{}")
        return response.status, data
    finally:
        connection.close()


def status() -> dict:
    state = _read_state()
    if state is None:
        return {"running": False}
    pid, port, token = state
    try:
        code, payload = _request(port, token, "GET", "/health", timeout=0.75)
    except OSError:
        return {"running": False, "pid": pid}
    return {
        "running": code == 200 and bool(payload.get("ok")),
        "pid": pid,
        "port": port,
        # How the worker draws WebGL (rhr.browser_render.webgl_mode); a worker from
        # before this field existed drew in software.
        "webgl": payload.get("webgl", "software"),
        "code": payload.get("code"),
    }


def usable_worker() -> bool:
    """Whether renders should go to the warm worker, starting it when none runs.

    RHR_PERSISTENT_BROWSER=0 never uses it, =1 always does (starting it as needed).
    Unset: a running worker drawing in this WebGL mode with this code is used; one
    running older code is replaced; one drawing in the other WebGL mode is left alone
    (a fresh Chromium draws this render); with none running, one is started.
    """
    from rhr.browser_render import webgl_mode

    setting = os.environ.get("RHR_PERSISTENT_BROWSER", "").strip().lower()
    if setting in {"0", "false", "no", "off"}:
        return False
    current = status()
    if current.get("running"):
        if current.get("webgl") != webgl_mode():
            return setting in {"1", "true", "yes", "on"}
        if current.get("code") == code_stamp():
            return True
        stop()  # older code: replace it
    try:
        ensure()
    except (RuntimeError, OSError):
        return False  # the one-shot path still works without it
    return True


def _cleanup_stale() -> None:
    state = _read_state()
    if state is not None:
        pid, port, token = state
        try:
            _request(port, token, "POST", "/shutdown", {}, timeout=1)
        except OSError:
            _terminate(pid)
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.05)
    shutil.rmtree(SESSION_ROOT, ignore_errors=True)


def _detached() -> dict:
    """Popen options that keep the worker alive after the calling `rhr` exits."""
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        return {"creationflags": flags}
    return {"start_new_session": True}


def ensure() -> tuple[dict, bool]:
    current = status()
    from rhr.browser_render import webgl_mode

    if current.get("running") and (current.get("webgl") != webgl_mode() or current.get("code") != code_stamp()):
        stop()  # another WebGL mode, or older code: restart it
        current = status()
    if current.get("running"):
        state = _read_state()
        assert state is not None
        pid, port, token = state
        return {"pid": pid, "port": port, "token": token}, False

    _cleanup_stale()
    SESSION_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(SESSION_ROOT, 0o700)
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token)
    os.chmod(TOKEN_FILE, 0o600)
    log = LOG_FILE.open("ab", buffering=0)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "rhr.browser_daemon",
            "--port-file",
            str(PORT_FILE),
            "--token",
            token,
        ],
        cwd=SESSION_ROOT,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(IMPORT_ROOT), os.environ.get("PYTHONPATH")]))),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        close_fds=True,
        **_detached(),
    )
    PID_FILE.write_text(str(process.pid))

    # Generous: software WebGL on a slow machine (a CI Mac) takes tens of seconds.
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = ""
            try:
                tail = "\n".join(LOG_FILE.read_text(errors="ignore").splitlines()[-10:])
            except OSError:
                pass
            raise RuntimeError(
                f"persistent browser daemon exited during startup ({process.returncode}): {tail}"
            )
        current = status()
        if current.get("running"):
            return {
                "pid": process.pid,
                "port": int(current["port"]),
                "token": token,
            }, True
        time.sleep(0.05)

    _cleanup_stale()
    raise RuntimeError(f"persistent browser daemon did not become ready within {STARTUP_TIMEOUT_S}s")


def render(
    *,
    url: str,
    out: Path,
    width: int,
    height: int,
    transparent: bool,
    reuse: dict | None = None,
) -> bool:
    """Render via the shared worker. Returns whether the worker was newly started.

    With `reuse` ({query, base}), a 3D scene is drawn on the worker's kept page;
    otherwise (or if that fails) `url` is loaded in a page of its own.
    """
    state, started = ensure()
    code, payload = _request(
        int(state["port"]),
        str(state["token"]),
        "POST",
        "/render",
        {
            "url": url,
            "out": str(out),
            "width": width,
            "height": height,
            "transparent": transparent,
            "reuse": reuse,
        },
    )
    if code != 200 or not payload.get("ok"):
        raise RuntimeError(
            "persistent browser render failed: " + str(payload.get("error", payload))
        )
    from rhr.profile import add

    for name, seconds in (payload.get("timings") or {}).items():
        add(f"  worker: {name}", seconds)
    return started


def stop() -> bool:
    state = _read_state()
    if state is None:
        shutil.rmtree(SESSION_ROOT, ignore_errors=True)
        return False
    pid, port, token = state
    was_alive = _pid_alive(pid)
    try:
        _request(port, token, "POST", "/shutdown", {}, timeout=2)
    except OSError:
        _terminate(pid)
    for _ in range(40):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    shutil.rmtree(SESSION_ROOT, ignore_errors=True)
    return was_alive
