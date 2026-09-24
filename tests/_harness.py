"""Run a test script's `main()` under pytest.

Every `tests/test_*.py` is also a standalone script: `main()` returns (or raises
SystemExit with) 0 on success and non-zero on failure, printing one line per check.
Each file exposes `test_main()`, which calls `run_main(main)` so pytest sees the same
verdict the script would give on its own.
"""

from __future__ import annotations

import os

# Standalone runs are as hermetic as pytest's (see conftest.py): no downloads, never
# the Studio login, no textures from a local Studio install.
os.environ.setdefault("RHR_OFFLINE", "1")
os.environ.setdefault("RHR_STUDIO_DIR", "0")


def run_main(main) -> None:
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    if code not in (0, None):
        raise AssertionError(f"{main.__module__}.main() reported failure (exit {code!r}); see captured output")
