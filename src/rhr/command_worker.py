"""A long-lived `rhr` for callers that run many commands (the MCP server).

Starting Python costs 1-3 s on some Windows machines (a virtual environment's launcher,
antivirus scans), more than a warm 3D render takes. This process starts once and runs
each command in-process: the caller writes one JSON line per command,
`{"args": ["scene", ...]}`, and reads one back, `{"code", "stdout", "stderr"}`.

Its own stdout carries only those replies: at start it is moved to a private file
descriptor, and descriptor 1 is pointed at stderr, so anything a library prints there
cannot break a reply.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout


def _run(args: list[str]) -> dict:
    from rhr import cli, pipeline

    out, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(args) or 0
        except SystemExit as exit_:
            code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
            if not isinstance(exit_.code, int) and exit_.code is not None:
                print(exit_.code, file=sys.stderr)
        except Exception:  # noqa: BLE001 - reported to the caller like a failed command
            traceback.print_exc()
            code = 1
        finally:
            # Options that set module state for one command must not carry over.
            pipeline.INCLUDE_STORED_GUIS = False
    return {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}


def main() -> int:
    replies = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            reply = _run([str(a) for a in request["args"]])
        except Exception as exc:  # noqa: BLE001 - a malformed request
            reply = {"code": 2, "stdout": "", "stderr": f"command worker: bad request: {exc}"}
        replies.write(json.dumps(reply) + "\n")
        replies.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
