#!/usr/bin/env python3
"""Converted IR is reused for an unchanged file, and never for a changed one.

An agent runs several commands on one file; each used to convert it through Lune
again (about a second). The cache is keyed on the file's bytes, so an edit, however
small, converts again, and two different files with the same name never share IR.

    python tests/test_ir_cache.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "two_screen_guis.rbxmx"
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-ir-cache-") as directory:
        tmp = Path(directory)
        env = {**os.environ, "RHR_CACHE_DIR": str(tmp / "cache")}

        def layout(path: Path) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, "-m", "rhr", "layout", str(path), "--viewport", "400x300"],
                                  capture_output=True, text=True, cwd=str(REPO), env=env, timeout=180)

        model = tmp / "a" / "ui.rbxmx"
        model.parent.mkdir()
        shutil.copy(FIXTURE, model)
        first, second = layout(model), layout(model)
        check(first.returncode == 0 and "ir     reused" not in first.stderr, "the first run converts the file")
        check(second.returncode == 0 and "ir     reused" in second.stderr, "the second run reuses the conversion")
        check("unreadable:" in second.stderr, "a reused conversion still prints the reader's report")
        check(first.stdout == second.stdout, "reused and fresh conversions give the same layout")

        # The same name in another folder, with different content, is its own entry.
        other = tmp / "b" / "ui.rbxmx"
        other.parent.mkdir()
        other.write_text(FIXTURE.read_text(encoding="utf-8").replace("RedPane", "RenamedPane"), encoding="utf-8")
        third = layout(other)
        check("ir     reused" not in third.stderr, "a different file with the same name is converted")
        rects = json.loads(third.stdout)["rects"] if third.returncode == 0 else {}
        check("Under/RenamedPane" in rects and "Under/RedPane" not in rects,
              "and its layout is its own, not the other file's")

        # Editing the first file invalidates its entry.
        model.write_text(FIXTURE.read_text(encoding="utf-8").replace("GreenStrip", "EditedStrip"), encoding="utf-8")
        fourth = layout(model)
        rects = json.loads(fourth.stdout)["rects"] if fourth.returncode == 0 else {}
        check("ir     reused" not in fourth.stderr and "Under/EditedStrip" in rects,
              "an edited file is converted again")

    print("ir cache: ok" if not failures else f"ir cache: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
