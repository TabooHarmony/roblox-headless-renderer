"""The `rhr` command: a thin client of RHR's resident server (rhr.server).

Kept small on purpose: it imports nothing of RHR's, so a command costs a Python start
and a local round trip, and the server does the work with everything already loaded.
Commands run in this process instead (rhr.cli) when the server is off
(RHR_SERVER=0), busy with another command, or cannot start, and for the commands
that manage RHR itself (setup, doctor, cache, browser).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import sys
import time

# The commands the server runs; everything else runs here.
SERVED = {"ui", "layout", "check", "hitmap", "scene", "preview", "scene-dump", "compare", "ir", "fetch"}
# Settings a request carries (rhr.server.REQUEST_ENV): read while the command runs, and
# the colour switches Python's own help output follows. Other RHR_* settings pick the server.
REQUEST_ENV = ("RHR_PROFILE", "RHR_OFFLINE", "NO_COLOR", "FORCE_COLOR", "PYTHON_COLORS", "TERM")
STARTUP_TIMEOUT_S = 30.0


class _Unavailable(Exception):
    """No answer from the server before any output: run the command here instead."""


def _off() -> bool:
    return os.environ.get("RHR_SERVER", "").strip().lower() in {"0", "false", "no", "off"}


def _cache_dir() -> str:
    # rhr.paths.CACHE, without importing pathlib.
    configured = os.environ.get("RHR_CACHE_DIR")
    if configured:
        return os.path.expanduser(configured)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "rhr", "cache")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", "rhr")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "rhr")


def session_dir() -> str:
    """Where this install's server keeps its port and token: one per Python, copy of
    RHR and RHR_* configuration."""
    package = os.path.dirname(os.path.abspath(__file__))
    settings = sorted((k, v) for k, v in os.environ.items()
                      if (k.startswith("RHR_") or k.startswith("PINEVEX_")) and k not in REQUEST_ENV)
    key = json.dumps([sys.executable, package, settings])
    return os.path.join(_cache_dir(), "server", hashlib.sha1(key.encode()).hexdigest()[:16])


def _read_state(session: str) -> tuple[int, str] | None:
    try:
        with open(os.path.join(session, "port"), encoding="utf-8") as handle:
            port = int(handle.read().split()[0])
        with open(os.path.join(session, "token"), encoding="utf-8") as handle:
            token = handle.read().strip()
    except (OSError, ValueError, IndexError):
        return None
    return port, token


def _start(session: str) -> None:
    """Start a server for this session unless one is starting already."""
    import secrets
    import subprocess

    os.makedirs(session, exist_ok=True)
    lock = os.path.join(session, "starting")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(lock) < STARTUP_TIMEOUT_S:
                return  # another client is starting it
            os.unlink(lock)
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return
    os.close(descriptor)
    token_path = os.path.join(session, "token")
    partial = f"{token_path}.{os.getpid()}.part"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_hex(24))
    try:
        os.chmod(partial, 0o600)
    except OSError:
        pass
    os.replace(partial, token_path)
    try:
        os.unlink(os.path.join(session, "port"))
    except OSError:
        pass
    if sys.platform == "win32":
        # A hidden console of its own (not DETACHED_PROCESS: then every console program
        # it starts would open a window), in its own group, outliving this process.
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    else:
        options = {"start_new_session": True}
    with open(os.path.join(session, "server.log"), "ab") as log:
        subprocess.Popen([sys.executable, "-m", "rhr.server", session], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, cwd=session, close_fds=True, **options)


def _connect(session: str, *, start: bool) -> tuple[socket.socket, str]:
    state = _read_state(session)
    if state is not None:
        try:
            return socket.create_connection(("127.0.0.1", state[0]), timeout=2), state[1]
        except OSError:
            pass
    if not start:
        raise _Unavailable
    _start(session)
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(0.02)
        state = _read_state(session)
        if state is None:
            continue
        try:
            connection = socket.create_connection(("127.0.0.1", state[0]), timeout=2)
        except OSError:
            continue
        try:
            os.unlink(os.path.join(session, "starting"))
        except OSError:
            pass
        return connection, state[1]
    raise _Unavailable


def _read_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(min(size - len(data), 1 << 20))
        if not chunk:
            raise ConnectionError("the server closed the connection")
        data += chunk
    return bytes(data)


def _remote(argv: list[str], session: str, *, start: bool = True) -> int:
    import codecs

    connection, token = _connect(session, start=start)
    started_output = False
    # Text written as this process would write it (rhr.cli: UTF-8, and on Windows
    # "\r\n" line ends), decoded incrementally since a frame can end inside a character.
    streams = {}
    for kind, stream in ((b"o", sys.stdout), (b"e", sys.stderr)):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
        streams[kind] = (stream, codecs.getincrementaldecoder("utf-8")("replace"))
    with connection:
        request = {"token": token, "argv": argv, "cwd": os.getcwd(),
                   "env": {name: os.environ[name] for name in REQUEST_ENV if name in os.environ},
                   "tty": [sys.stdout.isatty(), sys.stderr.isatty()]}
        try:
            connection.sendall(json.dumps(request).encode() + b"\n")
            connection.settimeout(None)
            while True:
                kind, size = struct.unpack(">cI", _read_exact(connection, 5))
                payload = _read_exact(connection, size)
                if kind in streams:
                    started_output = True
                    stream, decoder = streams[kind]
                    stream.write(decoder.decode(payload))
                    stream.flush()
                elif kind == b"x":
                    return int(payload or b"0")
                elif kind == b"s":  # RHR changed since the server started: a new one
                    if start:
                        _start(session)
                        return _remote(argv, session, start=True)
                    raise _Unavailable
                else:  # busy, or anything unexpected
                    raise _Unavailable
        except (OSError, ValueError, struct.error) as exc:
            if not started_output:
                raise _Unavailable from exc
            print(f"rhr: lost the RHR server during the command ({exc})", file=sys.stderr)
            return 2


def main() -> int:
    argv = sys.argv[1:]
    command = next((arg for arg in argv if not arg.startswith("-")), None)
    if argv == ["server", "stop"]:
        return _stop()
    if command in SERVED and not _off():
        try:
            return _remote(argv, session_dir())
        except _Unavailable:
            pass
    from rhr.cli import main as run_here

    return run_here(argv)


def _stop() -> int:
    try:
        _remote(["server", "stop"], session_dir(), start=False)
        print("rhr: server stopped", file=sys.stderr)
    except _Unavailable:
        print("rhr: no server running", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
