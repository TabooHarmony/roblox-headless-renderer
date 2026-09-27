"""A small Chrome DevTools Protocol client: RHR drives the browser itself.

Standard library only. It starts a Chromium-family browser (Chrome, Edge, Brave,
Chromium, or Chrome for Testing's headless shell) with a throwaway profile, talks to
it over the WebSocket the browser opens on a port of its own choosing, and does only
what RHR needs: open a page at a size, wait for the page's ready flag, take a PNG.

Every browser is tied to the life of the process that started it: on Windows it runs
in a job object that kills it when that process ends (even on a crash); on Linux it
gets a parent-death signal; everywhere it has a process group of its own that `close`
kills. Its profile folder is removed on close, and left-over ones from a crash are
removed by the next launch.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

PROFILE_PREFIX = "rhr-browser-"

# A page sets one of these when it is done (rhr/scene/scene.js, the particle sheet).
READY = ("document.documentElement.dataset.rhrReady === 'true'"
         " || Boolean(document.documentElement.dataset.rhrError)")


class BrowserError(RuntimeError):
    """The browser failed, closed, or did not answer in time."""


class WebSocket:
    """Just enough RFC 6455 for a local debugging endpoint: text frames, no extensions."""

    def __init__(self, url: str, timeout: float = 30.0):
        parts = urlparse(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserError("the browser closed the connection during the handshake")
            head += chunk
        status, _, rest = head.partition(b"\r\n\r\n")
        if b" 101 " not in status.split(b"\r\n")[0]:
            raise BrowserError(f"the browser refused the connection: {status[:200]!r}")
        self.buffer = bytearray(rest)
        self.closed = False

    def _read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(max(1 << 20, n - len(self.buffer)))
            if not chunk:
                self.closed = True
                raise BrowserError("the browser closed the connection")
            self.buffer += chunk
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        return out

    def _frame(self, opcode: int, data: bytes) -> None:
        head = bytearray([0x80 | opcode])
        if len(data) < 126:
            head.append(0x80 | len(data))
        elif len(data) < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(data))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
        # Client frames must be masked; a zero mask leaves the data as it is.
        head += b"\0\0\0\0"
        self.sock.sendall(bytes(head) + data)

    def send(self, text: str) -> None:
        self._frame(0x1, text.encode())

    def recv(self, timeout: float | None) -> str:
        """The next text message; socket.timeout if none arrives in `timeout` seconds."""
        self.sock.settimeout(timeout)
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                self.closed = True
                raise BrowserError("the browser closed the connection")
            if opcode == 0x9:  # ping
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts).decode("utf-8", errors="replace")

    def close(self) -> None:
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


class Connection:
    """Numbered requests over one WebSocket; events are routed as they arrive.

    Requests are made one at a time (RHR renders one page at a time per browser).
    Page problems (exceptions, console errors) are kept per session, so a page that
    never gets ready can say why; other events wait in `events` until asked for.
    """

    MAX_PROBLEMS = 50

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.next_id = 0
        self.events: list[dict] = []
        self.problems: dict[str, list[str]] = {}

    def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        session = message.get("sessionId", "")
        params = message.get("params", {})
        problem = None
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            problem = (details.get("exception", {}).get("description") or details.get("text") or "exception")
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            problem = " ".join(str(arg.get("value", arg.get("description", ""))) for arg in params.get("args", []))
        elif method == "Inspector.targetCrashed":
            problem = "the page crashed"
        if problem is not None:
            kept = self.problems.setdefault(session, [])
            kept.append(problem.strip()[:1000])
            del kept[:-self.MAX_PROBLEMS]
            if method != "Inspector.targetCrashed":
                return
        if method in ("Page.loadEventFired", "Inspector.targetCrashed", "Target.detachedFromTarget"):
            self.events.append(message)
            del self.events[:-200]

    def _next(self, deadline: float, what: str) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(what)
        try:
            return json.loads(self.ws.recv(remaining))
        except socket.timeout:
            raise TimeoutError(what) from None
        except OSError as exc:
            raise BrowserError(f"lost the connection to the browser: {exc}") from exc

    def call(self, method: str, params: dict | None = None, *, session: str | None = None,
             timeout: float = 30.0) -> dict:
        self.next_id += 1
        wanted = self.next_id
        message = {"id": wanted, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            self.ws.send(json.dumps(message))
        except OSError as exc:
            raise BrowserError(f"lost the connection to the browser: {exc}") from exc
        deadline = time.monotonic() + timeout
        while True:
            reply = self._next(deadline, f"the browser did not answer {method} within {timeout:.0f} s")
            if "id" not in reply:
                self._dispatch(reply)
                continue
            if reply["id"] != wanted:
                continue  # the late answer to a request that already timed out
            if "error" in reply:
                raise BrowserError(f"{method}: {reply['error'].get('message', reply['error'])}")
            return reply.get("result", {})

    def wait_event(self, method: str, *, session: str | None, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            for index, event in enumerate(self.events):
                if event.get("method") == method and event.get("sessionId") == session:
                    return self.events.pop(index)
                if event.get("method") == "Inspector.targetCrashed" and event.get("sessionId") == session:
                    self.events.pop(index)
                    raise BrowserError("the page crashed")
            message = self._next(deadline, f"no {method} within {timeout:.0f} s")
            if "id" not in message:
                self._dispatch(message)

    def close(self) -> None:
        self.ws.close()


# --- starting and stopping browsers --------------------------------------------------

def _creation_flags(job: bool) -> int:
    """Windows: a hidden console (see rhr.procs), a process group of its own, and, with
    a job object, suspended so it joins the job before it can start any child process."""
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | (0x00000004 if job else 0)


def _linux_parent_death():
    """A function for the browser's process to run before it starts (Linux): die when
    the thread that started it does. libc is loaded here, in RHR's process: after the
    fork only the prctl call runs, which is safe even though RHR has other threads."""
    try:
        import ctypes

        prctl = ctypes.CDLL("libc.so.6", use_errno=True).prctl
    except (OSError, AttributeError):
        return None
    return lambda: prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


class _Job:
    """A Windows job object that kills everything in it when RHR's process ends."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.handle = self.kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

    def add_and_resume(self, proc: subprocess.Popen) -> None:
        import ctypes

        handle = int(proc._handle)  # noqa: SLF001 - Popen keeps the process handle here
        try:
            if not self.kernel32.AssignProcessToJobObject(self.handle, handle):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            ctypes.WinDLL("ntdll").NtResumeProcess(handle)

    def kill(self) -> None:
        if self.handle:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def _read_port_file(path: Path, proc: subprocess.Popen, timeout: float) -> tuple[int, str]:
    """(port, WebSocket path) from the profile's DevToolsActivePort, once complete.

    Some browsers (Brave on Windows) hold the file locked for a moment after creating it.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        if len(lines) >= 2 and lines[0].strip().isdigit():
            return int(lines[0]), lines[1].strip()
        if proc.poll() is not None:
            raise BrowserError(f"the browser exited during start (exit code {proc.returncode})")
        time.sleep(0.02)
    raise BrowserError(f"the browser did not open its debugging port within {timeout:.0f} s")


def _remove_profile(profile: str, patience: float = 10.0) -> None:
    """Delete a profile folder, retrying while the browser's last processes let go of it."""
    deadline = time.monotonic() + patience
    while True:
        shutil.rmtree(profile, ignore_errors=True)
        if not os.path.exists(profile) or time.monotonic() > deadline:
            return
        time.sleep(0.1)


OWNER_FILE = "rhr-owner"


def remove_stale_profiles(min_age_s: float = 60.0) -> None:
    """Remove profiles a killed RHR left in the temp folder: those whose owner (the
    process that started the browser, written in the profile) is no longer running."""
    from rhr.browser_session import _pid_alive

    now = time.time()
    try:
        entries = list(Path(tempfile.gettempdir()).glob(PROFILE_PREFIX + "*"))
    except OSError:
        return
    for entry in entries:
        try:
            if not entry.is_dir() or now - entry.stat().st_mtime < min_age_s:
                continue
            owner = (entry / OWNER_FILE).read_text().strip()
            if owner.isdigit() and _pid_alive(int(owner)):
                continue
        except OSError:
            pass  # no owner file: not a profile this version of RHR left
        shutil.rmtree(entry, ignore_errors=True)


class Browser:
    """One running browser, started headless with a throwaway profile."""

    def __init__(self, executable: str, args: list[str], *, headless_shell: bool, start_timeout: float = 30.0):
        self.executable = executable
        self.profile = tempfile.mkdtemp(prefix=PROFILE_PREFIX)
        Path(self.profile, OWNER_FILE).write_text(str(os.getpid()))
        self.job = None
        self.conn = None
        command = [
            executable,
            *([] if headless_shell else ["--headless"]),
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-component-update", "--disable-sync", "--mute-audio",
            *args,
            "about:blank",
        ]
        options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            try:
                self.job = _Job()
            except OSError:
                self.job = None  # no job objects here: close() still kills the tree
            options["creationflags"] = _creation_flags(self.job is not None)
        else:
            options["start_new_session"] = True
            hook = _linux_parent_death() if sys.platform.startswith("linux") else None
            if hook is not None:
                options["preexec_fn"] = hook
        try:
            self.proc = subprocess.Popen(command, **options)
        except BaseException:
            if self.job is not None:
                self.job.close()
            _remove_profile(self.profile, 0)
            raise
        try:
            if self.job is not None:
                self.job.add_and_resume(self.proc)
            port, path = _read_port_file(Path(self.profile) / "DevToolsActivePort", self.proc, start_timeout)
            self.conn = Connection(WebSocket(f"ws://127.0.0.1:{port}{path}"))
            product = self.conn.call("Browser.getVersion").get("product", "")
        except BaseException:
            self._kill()
            _remove_profile(self.profile)
            if self.job is not None:
                self.job.close()
            raise
        # "HeadlessChrome/145.0.7632.6", "Chrome/140.0.0.0" (Edge, Brave report Chrome's)
        self.version = product.split("/", 1)[-1]

    def is_connected(self) -> bool:
        return self.proc.poll() is None and self.conn is not None and not self.conn.ws.closed

    def _kill(self) -> None:
        """Kill the browser and every process it started."""
        if self.job is not None:
            self.job.kill()
        elif sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        elif self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                self.proc.kill()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.call("Browser.close", timeout=3)
            except (BrowserError, TimeoutError):
                pass
            self.conn.close()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        # Browser.close ends the main process; this ends any child still exiting.
        self._kill()
        if self.job is not None:
            self.job.close()
            self.job = None
        _remove_profile(self.profile)

    def new_page(self, width: int, height: int) -> Page:
        return Page(self, width, height)


class Page:
    """A tab of its own, at a fixed size, with its problems collected."""

    def __init__(self, browser: Browser, width: int, height: int):
        self.conn = browser.conn
        self.target = self.conn.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        try:
            self.session = self.conn.call("Target.attachToTarget", {"targetId": self.target, "flatten": True})["sessionId"]
            self.call("Page.enable")
            self.call("Runtime.enable")
            self.call("Inspector.enable")
            self.set_size(width, height)
        except BaseException:
            self.close()
            raise

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return self.conn.call(method, params, session=getattr(self, "session", None), timeout=timeout)

    @property
    def problems(self) -> list[str]:
        return self.conn.problems.setdefault(self.session, [])

    def set_size(self, width: int, height: int) -> None:
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def goto(self, url: str, timeout: float) -> None:
        """Open `url` and wait for its load event."""
        self.conn.events = [e for e in self.conn.events if e.get("sessionId") != self.session]
        result = self.call("Page.navigate", {"url": url}, timeout=timeout)
        if result.get("errorText"):
            raise BrowserError(f"could not open {url}: {result['errorText']}")
        self.conn.wait_event("Page.loadEventFired", session=self.session, timeout=timeout)

    def evaluate(self, expression: str, *, timeout: float = 30.0, await_promise: bool = False):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": await_promise,
        }, timeout=timeout)
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            raise BrowserError("page script failed: "
                               + (details.get("exception", {}).get("description") or details.get("text", "")))
        return result.get("result", {}).get("value")

    def wait_for(self, condition: str, timeout: float) -> None:
        """Wait until the JavaScript expression `condition` is true in the page.

        Polled inside the page, so there is one round trip; the page's own timer
        gives up first, so a stuck page answers instead of leaving a request open.
        """
        limit_ms = int(timeout * 1000)
        expression = f"""new Promise(resolve => {{
            const end = performance.now() + {limit_ms};
            const check = () => {{
                if ({condition}) resolve(true);
                else if (performance.now() > end) resolve(false);
                else setTimeout(check, 10);
            }};
            check();
        }})"""
        if not self.evaluate(expression, timeout=timeout + 10, await_promise=True):
            raise TimeoutError(f"the page did not get ready within {timeout:.0f} s")

    def screenshot(self, out: Path, *, transparent: bool = False) -> None:
        """Save the viewport as a PNG, with Chromium's fast PNG encoder."""
        if transparent:
            self.call("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
        shot = self.call("Page.captureScreenshot",
                         {"format": "png", "optimizeForSpeed": True, "captureBeyondViewport": False},
                         timeout=60)
        out.write_bytes(base64.b64decode(shot["data"]))

    def close(self) -> None:
        session = getattr(self, "session", None)
        try:
            self.conn.call("Target.closeTarget", {"targetId": self.target}, timeout=5)
        except (BrowserError, TimeoutError):
            pass
        if session:
            self.conn.problems.pop(session, None)
            self.conn.events = [e for e in self.conn.events if e.get("sessionId") != session]
