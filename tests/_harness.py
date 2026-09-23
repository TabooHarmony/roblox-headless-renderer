"""Run a test script's `main()` under pytest.

Every `tests/test_*.py` is also a standalone script: `main()` returns (or raises
SystemExit with) 0 on success and non-zero on failure, printing one line per check.
Each file exposes `test_main()`, which calls `run_main(main)` so pytest sees the same
verdict the script would give on its own.
"""

from __future__ import annotations


def run_main(main) -> None:
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    if code not in (0, None):
        raise AssertionError(f"{main.__module__}.main() reported failure (exit {code!r}); see captured output")
