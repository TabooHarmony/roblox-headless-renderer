"""Client/manager for RHR's optional long-lived browser worker."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SESSION_ROOT = Path("/tmp/rhr-browser-session")
PID_FILE = SESSION_ROOT / "pid"
PORT_FILE = SESSION_ROOT / "port"
TOKEN_FILE = SESSION_ROOT / "token"
LOG_FILE = SESSION_ROOT / "daemon.log"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


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
    timeout: float = 50,
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
    }


def _host_python() -> str:
    configured = os.environ.get("RHR_BROWSER_PYTHON")
    candidates = [
        configured,
        shutil.which("python3"),
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        probe = subprocess.run(
            [str(path), "-c", "import playwright.sync_api"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if probe.returncode == 0:
            return str(path)
    raise RuntimeError(
        "persistent browser needs a host Python with Playwright; "
        "set RHR_BROWSER_PYTHON or use the normal one-shot renderer"
    )


def _cleanup_stale() -> None:
    state = _read_state()
    if state is not None:
        pid, port, token = state
        try:
            _request(port, token, "POST", "/shutdown", {}, timeout=1)
        except OSError:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.05)
    shutil.rmtree(SESSION_ROOT, ignore_errors=True)


def ensure(chrome: str) -> tuple[dict, bool]:
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
    host_python = _host_python()
    log = LOG_FILE.open("ab", buffering=0)
    process = subprocess.Popen(
        [
            host_python,
            str(REPO / "src/rhr/browser_daemon.py"),
            "--chrome",
            chrome,
            "--port-file",
            str(PORT_FILE),
            "--token",
            token,
        ],
        cwd=REPO,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
    )
    PID_FILE.write_text(str(process.pid))

    deadline = time.monotonic() + 12
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
    raise RuntimeError("persistent browser daemon did not become ready within 12s")


def render(
    chrome: str,
    *,
    url: str,
    out: Path,
    width: int,
    height: int,
    transparent: bool,
) -> bool:
    """Render via the shared worker. Returns whether the worker was newly started."""
    state, started = ensure(chrome)
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
        },
    )
    if code != 200 or not payload.get("ok"):
        raise RuntimeError(
            "persistent browser render failed: " + str(payload.get("error", payload))
        )
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
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    for _ in range(40):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    shutil.rmtree(SESSION_ROOT, ignore_errors=True)
    return was_alive
