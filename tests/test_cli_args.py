#!/usr/bin/env python3
"""A vector whose first coordinate is negative is taken as a value, on every Python.

Before Python 3.13, argparse read `--camera -10,5,3` as two options and failed; CI's
Python 3.12 caught it in tests/test_scene_sun_rays.py. `rhr` (and the MCP server,
which goes through the same `main`) joins such values to their option first.

    python tests/test_cli_args.py
"""

from __future__ import annotations


def main() -> int:
    from rhr.cli import _join_negative_lists, build_parser

    parser = build_parser()
    for command in ("scene", "preview"):
        args = parser.parse_args(_join_negative_lists(
            [command, "place.rbxl", "--camera", "-10,5,3", "--look-at", "-47.5,132.1,-31.2", "--seed", "-3"]))
        assert (args.camera, args.look_at, args.seed) == ((-10, 5, 3), (-47.5, 132.1, -31.2), -3), args
        print(f"  ok   {command}: --camera {args.camera}, --look-at {args.look_at}")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
