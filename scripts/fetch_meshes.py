"""Kept for older instructions: use `rhr fetch <file> --meshes-only` instead."""

import sys

from rhr.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["fetch", *sys.argv[1:2], "--meshes-only"]))
