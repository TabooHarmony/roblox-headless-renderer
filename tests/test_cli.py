#!/usr/bin/env python3
"""CLI checks: the three subcommands a human (or an agent) actually types.

These run the real `rhr` CLI (`python -m rhr`), not the functions behind it: an argument parser that
silently drops a flag, or a shim that does not find the venv, has to fail here.

Run: python tests/test_cli.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = REPO / "tests" / "fixtures" / "grid_offset.rbxmx"
OUT = REPO / "out" / "cli"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*RHR, *args], capture_output=True, text=True, cwd=str(REPO), timeout=300
    )


def main() -> int:
    print("cli: ir / render / layout")
    OUT.mkdir(parents=True, exist_ok=True)

    # A font given by asset id (Builder Sans, Roblox's default UI font, is
    # rbxassetid://16658221428) goes through the vendored parser's font table, which
    # needs `zstandard`: it once crashed every UI command on a new Studio template.
    font_fixture = FIXTURE.parent / "font_by_asset_id.rbxmx"
    for command in ("layout", "render", "check", "hitmap"):
        extra = ["--out", str(OUT / "font_by_asset_id.png")] if command == "render" else []
        proc = run(command, str(font_fixture), *extra)
        check(proc.returncode == 0, f"rhr {command} handles a font given by asset id "
                                    f"({proc.stderr.strip()[-120:] or 'clean'})")

    ir_out = OUT / "grid.json"
    proc = run("ir", str(FIXTURE), "--out", str(ir_out))
    check(proc.returncode == 0, f"rhr ir exits 0 ({proc.stderr.strip()[:120] or 'clean'})")
    check(ir_out.exists(), "rhr ir writes the IR file")
    check(re.search(r"ir\s+.*\d+ms", proc.stderr) is not None, "rhr ir prints elapsed ms")
    # The emitter reads only the properties a class really has (roblox
    # reflection database). Its own check of that claim, against a full read of
    # the first instance of every class, has to stay clean.
    check(
        re.search(r"class filter: \d+ instances over 0 database mismatches", proc.stderr)
        is not None,
        "the class filter agrees with the reflection database",
    )
    if ir_out.exists():
        data = json.loads(ir_out.read_text())
        check(len(data["roots"]) == 1, "the IR has one root")

    png = OUT / "grid.png"
    proc = run("render", str(FIXTURE), "--out", str(png), "--viewport", "400x300", "--transparent")
    check(proc.returncode == 0, f"rhr render exits 0 ({proc.stderr.strip()[:120] or 'clean'})")
    check(
        re.search(r"render\s+\S+\s+400x300\s+\d+ms", proc.stderr) is not None,
        "rhr render reports the viewport and elapsed ms (stderr)",
    )
    check(re.search(r"total\s+\d+ms", proc.stderr) is not None, "rhr render reports a total")
    if png.exists():
        from PIL import Image

        img = Image.open(png)
        check(img.size == (400, 300), f"the PNG is the requested viewport ({img.size})")

    # Backdrop: use a fixture whose content does not fill the viewport, so there is
    # an unpainted corner to look at (grid_offset's root covers all 400x300).
    sparse = REPO / "tests" / "fixtures" / "zero_size_parent.rbxmx"
    clear = OUT / "sparse-clear.png"
    solid = OUT / "sparse-solid.png"
    run("render", str(sparse), "--out", str(clear), "--viewport", "400x300", "--transparent")
    run("render", str(sparse), "--out", str(solid), "--viewport", "400x300")
    from PIL import Image

    check(
        Image.open(clear).convert("RGBA").getpixel((399, 299))[3] == 0,
        "--transparent leaves no backdrop",
    )
    check(
        Image.open(solid).convert("RGBA").getpixel((399, 299))[3] == 255,
        "without --transparent the backdrop is opaque",
    )

    layout_out = OUT / "grid-layout.json"
    proc = run("layout", str(FIXTURE), "--viewport", "400x300", "--out", str(layout_out))
    check(proc.returncode == 0, f"rhr layout exits 0 ({proc.stderr.strip()[:120] or 'clean'})")
    if layout_out.exists():
        document = json.loads(layout_out.read_text())
        dump = document["rects"]
        check(len(dump) == 5, f"the layout dump has every drawn node ({len(dump)})")
        # Two independent outputs must agree: the inset the CLI reports on stderr
        # and the root rect in the dump. Neither is asserted against a constant.
        inset = re.search(r"^inset\s+.*?top (\d+(?:\.\d+)?)", proc.stderr, re.M)
        top = float(inset.group(1)) if inset else None
        root = dump.get("GridOffset/Root")
        # The fixture's Root frame is 400x300 of its own, so only the origin moves
        # with the inset: that is the cross-check between the two outputs.
        check(
            root == {"x": 0.0, "y": top, "w": 400.0, "h": 300.0} if top else False,
            f"the dump carries resolved rects ({root}, inset top {top})",
        )
    check(
        any(line.startswith("layout ") for line in proc.stderr.splitlines()),
        f"the count line goes to stderr, JSON to stdout ({proc.stderr.strip()[:60]})",
    )

    proc = run()
    check(proc.returncode != 0 and "usage" in (proc.stdout + proc.stderr).lower(),
          "no subcommand: usage and a non-zero exit")

    print("cli: ok" if not failures else f"cli: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())