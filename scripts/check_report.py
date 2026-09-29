"""Check an `rhr ui|scene|preview --json` report read from stdin (used by CI).

    rhr scene x.rbxmx --json | python scripts/check_report.py [--shell | --installed | --browser NAME]

Fails unless the report is `rhr.render/1` and its PNG exists and is not empty.
`--shell`: the picture was drawn by the downloaded headless shell; `--installed`: by
an installed browser; `--browser NAME`: by the browser of that name; `--particles`:
some particles were drawn. Prints the
report's browser and notes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--shell", action="store_true")
    group.add_argument("--installed", action="store_true")
    group.add_argument("--browser")
    parser.add_argument("--particles", action="store_true", help="some particles must be drawn")
    args = parser.parse_args()
    report = json.load(sys.stdin)
    problems = []
    if report.get("schema") != "rhr.render/1":
        problems.append(f"schema is {report.get('schema')!r}")
    out = Path(report.get("out", ""))
    if not out.is_file() or out.stat().st_size == 0:
        problems.append(f"no picture at {out}")
    browser = report.get("browser") or {}
    name = browser.get("name")
    if args.shell and name != "headless shell":
        problems.append(f"drawn by {name!r}, not the downloaded headless shell")
    if args.installed and (not name or name == "headless shell"):
        problems.append(f"drawn by {name!r}, not an installed browser")
    if args.browser and name != args.browser:
        problems.append(f"drawn by {name!r}, not {args.browser!r}")
    if args.particles:
        import re

        drawn = [int(m.group(1)) for n in report.get("notes", []) for m in [re.search(r"particles: (\d+) drawn", n)] if m]
        if not drawn or not max(drawn):
            problems.append("no particles were drawn")
    print(f"{report.get('command')}: {out.name} {report.get('size')} browser={browser or None}")
    for note in report.get("notes", []):
        print(f"  note: {note}")
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
