#!/bin/sh
# Test entry point: runs the pytest suite. Extra arguments go to pytest, e.g.
# `sh tests/run.sh -m "not browser"` for the quick checks only, `-m smoke` for one quick
# test per area (about a minute, before every commit).
#
# Setup (once): pip install -e ".[dev]" && python -m playwright install --only-shell chromium
# and Lune 0.10.5 on PATH (`rokit install` with Rokit, see rokit.toml).
#
# Each tests/test_*.py is also a standalone script (`python tests/test_x.py`).
cd "$(dirname "$0")/.." || exit 2
exec python -m pytest "$@"
