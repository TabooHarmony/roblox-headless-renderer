"""RHR's resident server: one long-lived process that runs `rhr` commands.

An agent runs many short commands on the same few files. Run one by one, each would
start Python, import RHR (numpy, skia, the UI engine), read the converted file again
(a big place's is hundreds of MB of JSON) and work out the same things about it. The
server keeps all of that between commands: `rhr` (rhr.client) sends it the command
line and working folder, and gets back stdout, stderr and the exit code.

- One request at a time. A command that arrives while another runs is told the
  server is busy and runs in its own process instead.
- The server belongs to one install and one configuration (rhr.client.session_dir):
  another Python, another copy of RHR or other RHR_* settings get their own.
- When RHR's code changes (an upgrade, an edit), the next request is refused as
  stale and the server exits; the client starts a new one.
- It stops by itself after RHR_SERVER_IDLE_S seconds without a command (default 20
  minutes), and any time with `rhr server stop`.
- After TRIM_AFTER_S idle seconds it lets go of the files it read beyond
  RHR_SERVER_MEMORY_MB (default 512): a small UI stays warm, a big place (about a
  gigabyte in memory) is read again when it is next asked for.

Wire format, over a local TCP socket: the request is rhr.client.encode_request (a
length, then NUL-separated fields: token, cwd, tty flags, argv, settings); the reply is
frames of one type byte and a 4-byte big-endian length: `o` stdout bytes, `e` stderr
bytes, `x` the exit code (as text), `b` busy, `s` stale.
"""

from __future__ import annotations

import io
import os
import socket
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

IDLE_S = float(os.environ.get("RHR_SERVER_IDLE_S", "1200") or 0)
TRIM_AFTER_S = float(os.environ.get("RHR_SERVER_TRIM_S", "180") or 180)
try:
    MEMORY_MB = float(os.environ.get("RHR_SERVER_MEMORY_MB", "512"))
except ValueError:
    MEMORY_MB = 512.0
# A loaded IR takes about 4.5 times its JSON's size in memory (rhr.ir._LOADED).
IR_MEMORY_FACTOR = 4.5
# Read while a command runs, so each request sets them (rhr.client.REQUEST_ENV); the
# rest of RHR_* chose the server.
REQUEST_ENV = ("RHR_PROFILE", "RHR_OFFLINE", "NO_COLOR", "FORCE_COLOR", "PYTHON_COLORS", "TERM")


def code_stamp() -> str:
    """What RHR's code is: every source file's size and mtime."""
    import hashlib

    package = Path(__file__).resolve().parent
    digest = hashlib.sha1()
    for pattern in ("**/*.py", "scene/*.js", "particles/*.js", "luau/*.luau"):
        for path in sorted(package.glob(pattern)):
            try:
                info = path.stat()
            except OSError:
                continue
            digest.update(f"{path.relative_to(package)}:{info.st_size}:{info.st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


class _Stream(io.TextIOBase):
    """stdout or stderr of the current request, sent to the client as frames."""

    def __init__(self, connection: socket.socket, kind: bytes, line_buffered: bool, tty: bool = False):
        self.connection = connection
        self.kind = kind
        self.line_buffered = line_buffered
        self.tty = tty
        self.pending = bytearray()
        self.broken = False

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return self.tty  # the client's stream: a terminal or not

    def write(self, text: str) -> int:
        self.pending += text.encode("utf-8", "replace")
        if len(self.pending) >= 1 << 16 or (self.line_buffered and b"\n" in self.pending):
            self.flush()
        return len(text)

    def flush(self) -> None:
        if not self.pending or self.broken:
            self.pending.clear()
            return
        try:
            _send(self.connection, self.kind, bytes(self.pending))
        except OSError:
            self.broken = True  # the client went away: finish quietly
        self.pending.clear()


def _send(connection: socket.socket, kind: bytes, payload: bytes) -> None:
    connection.sendall(kind + struct.pack(">I", len(payload)) + payload)


def _read_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(min(size - len(data), 65536))
        if not chunk:
            raise ConnectionError("request cut short")
        data += chunk
    return bytes(data)


def _read_request(connection: socket.socket) -> dict:
    size = int.from_bytes(_read_exact(connection, 4), "big")
    if size > 1 << 20:
        raise ValueError("request too large")
    return decode_request(_read_exact(connection, size))


def decode_request(payload: bytes) -> dict:
    """rhr.client.encode_request, read back."""
    fields = payload.decode("utf-8", "surrogateescape").split("\0")
    if fields[0] != "RHR1":
        raise ValueError("not an RHR request")
    count = int(fields[4])
    return {"token": fields[1], "cwd": fields[2], "tty": [flag == "1" for flag in fields[3]],
            "argv": fields[5:5 + count], "env": dict(field.split("=", 1) for field in fields[5 + count:])}


def _warm() -> None:
    """Import what commands use, so the first one does not pay for it."""
    import rhr.adapter  # noqa: F401
    import rhr.checks  # noqa: F401
    import rhr.cli  # noqa: F401
    import rhr.hitmap  # noqa: F401
    import rhr.layout_dump  # noqa: F401
    import rhr.pipeline  # noqa: F401
    import rhr.scene  # noqa: F401
    import rhr.scene_dump  # noqa: F401
    import rhr.ui_engine.renderer  # noqa: F401
    from rhr import __version__  # noqa: F401  (importlib.metadata)


class Server:
    def __init__(self, session: Path):
        self.session = session
        self.token = (session / "token").read_text(encoding="utf-8").strip()
        self.stamp = code_stamp()
        self.busy = threading.Lock()
        self.last_used = time.monotonic()
        self.trimmed = True
        self.stopping = False
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(1.0)

    def publish(self) -> None:
        """Say where the server listens: written last, so a client that finds it can connect."""
        port = self.session / "port"
        partial = self.session / f"port.{os.getpid()}.part"
        partial.write_text(f"{self.listener.getsockname()[1]} {os.getpid()}", encoding="utf-8")
        os.replace(partial, port)

    def serve(self) -> None:
        try:
            while not self.stopping:
                try:
                    connection, _ = self.listener.accept()
                except TimeoutError:
                    idle = time.monotonic() - self.last_used
                    if IDLE_S > 0 and not self.busy.locked() and idle > IDLE_S:
                        break
                    if not self.trimmed and idle > TRIM_AFTER_S:
                        self.trim()
                    continue
                except OSError:  # closed by stop()
                    break
                threading.Thread(target=self._accept, args=(connection,), daemon=True).start()
        finally:
            self._unpublish()
            # A command still running (stopped mid-way) finishes before the process ends.
            with self.busy:
                pass

    def trim(self) -> None:
        """Let go of loaded files beyond the memory budget, between commands."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            import gc

            from rhr import ir

            if ir.trim_loaded(int(MEMORY_MB * 1024 * 1024 / IR_MEMORY_FACTOR)):
                gc.collect()
            self.trimmed = True
        finally:
            self.busy.release()

    def stop(self) -> None:
        """Take no more commands: unpublished and closed at once (one running finishes)."""
        self.stopping = True
        self._unpublish()
        try:
            self.listener.close()
        except OSError:
            pass

    def _unpublish(self) -> None:
        port = self.session / "port"
        try:
            if port.read_text(encoding="utf-8").split()[1] == str(os.getpid()):
                port.unlink()
        except (OSError, IndexError):
            pass

    def _accept(self, connection: socket.socket) -> None:
        with connection:
            try:
                connection.settimeout(10)
                request = _read_request(connection)
                if request.get("token") != self.token:
                    return
                if request.get("argv") == ["server", "stop"]:
                    self.stop()
                    _send(connection, b"x", b"0")
                    return
                if not self.busy.acquire(blocking=False):
                    _send(connection, b"b", b"")
                    return
                try:
                    if code_stamp() != self.stamp:
                        self.stop()
                        _send(connection, b"s", b"")
                        return
                    connection.settimeout(None)
                    self._run(connection, request)
                finally:
                    self.last_used = time.monotonic()
                    self.trimmed = False
                    self.busy.release()
            except (OSError, ValueError):
                return

    def _run(self, connection: socket.socket, request: dict) -> None:
        from rhr import browsers, pipeline, profile
        from rhr.cli import main

        tty = list(request.get("tty") or [False, False]) + [False, False]
        out = _Stream(connection, b"o", line_buffered=False, tty=bool(tty[0]))
        err = _Stream(connection, b"e", line_buffered=True, tty=bool(tty[1]))
        saved_env = dict(os.environ)
        saved_cwd = os.getcwd()
        saved_streams = sys.stdout, sys.stderr, sys.argv
        argv = [str(arg) for arg in request.get("argv") or []]
        code = 2
        try:
            for name in REQUEST_ENV:
                value = (request.get("env") or {}).get(name)
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = str(value)
            os.chdir(request["cwd"])
            sys.stdout, sys.stderr, sys.argv = out, err, ["rhr", *argv]
            profile.begin()
            try:
                code = main(argv)
            except SystemExit as exc:  # argparse: --help, a bad option
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
                if not isinstance(exc.code, (int, type(None))):
                    print(exc.code, file=sys.stderr)
            except KeyboardInterrupt:
                code = 130
            except Exception:  # noqa: BLE001 - what an uncaught error prints in a process of its own
                traceback.print_exc()
                code = 1
            profile.end()
        finally:
            sys.stdout, sys.stderr, sys.argv = saved_streams
            os.chdir(saved_cwd)
            os.environ.clear()
            os.environ.update(saved_env)
            pipeline.reset_options()
            browsers.used = None
            out.flush()
            err.flush()
        if not out.broken:
            try:
                _send(connection, b"x", str(code if code is not None else 0).encode())
            except OSError:
                pass


def main() -> int:
    session = Path(sys.argv[1])
    _warm()
    import rhr.ir

    rhr.ir.USE_LUNE_WORKER = True
    server = Server(session)
    server.publish()
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
