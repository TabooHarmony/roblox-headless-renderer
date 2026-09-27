#!/usr/bin/env python3
"""RHR's own reader (rhr.rbx) writes the same IR as the Lune script it replaces.

Every fixture is saved as a binary file by Lune (most fixtures are XML), then read by
both: rhr.rbx and luau/rhr-ir.luau through Lune, in both profiles. The IRs must be the
same document (numbers by value; an empty table is the same whether written {} or []),
and so must the reports. Also checks the shared lists and the pinned database.

    python tests/test_rbx_reader.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []

TO_BINARY = """
local roblox = require("@lune/roblox")
local fs = require("@lune/fs")
local process = require("@lune/process")
local data = fs.readFile(process.args[1])
local ok, roots = pcall(roblox.deserializeModel, data)
if ok then
  fs.writeFile(process.args[2], roblox.serializeModel(roots))
else
  fs.writeFile(process.args[2], roblox.serializePlace(roblox.deserializePlace(data)))
end
"""


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def norm(value):
    if isinstance(value, dict):
        return {k: norm(v) for k, v in value.items()} if value else ()
    if isinstance(value, list):
        return [norm(v) for v in value] if value else ()
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


def first_difference(a, b, where="") -> str | None:
    a, b = norm(a), norm(b)
    if type(a) is not type(b):
        return f"{where}: {str(a)[:80]} != {str(b)[:80]}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{where}.{key}: only in {'rhr.rbx' if key in b else 'lune'}"
            found = first_difference(a[key], b[key], f"{where}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{where}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{where}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{where}: {str(a)[:80]} != {str(b)[:80]}"


def shared_lists() -> None:
    from rhr.rbx import props

    luau = (REPO / "src" / "rhr" / "luau" / "rhr-ir.luau").read_text(encoding="utf-8")

    def block(start: str) -> str:
        i = luau.index(start)
        return re.sub(r"--[^\n]*", "", luau[i:luau.index("\n}", i)])

    check(tuple(re.findall(r'"([A-Za-z0-9]+)"', block("local PROPS = {"))) == props.PROPS,
          "PROPS is the Luau emitter's list, in order")
    check(dict(re.findall(r'(\w+) = "(\w+)"', block("local CONTENT_PROPERTY_ALIASES = {")))
          == props.CONTENT_PROPERTY_ALIASES, "CONTENT_PROPERTY_ALIASES matches")
    check(frozenset(re.findall(r"(\w+) = true", block("local VISUAL_CLASSES = {"))) == props.VISUAL_CLASSES,
          "VISUAL_CLASSES matches")
    check(frozenset(re.findall(r"(\w+) = true", block("local VISUAL_XML_RECOVERY = {")))
          == props.VISUAL_XML_RECOVERY, "VISUAL_XML_RECOVERY matches")

    from rhr.rbx.reflection import reflection
    from rhr.tools import TOOLS

    # The database is the one the pinned Lune bundles (scripts/make_reflection.py).
    check(TOOLS["lune"][1] == "0.10.5" and reflection().version.startswith("0.728."),
          f"reflection data {reflection().version} is Lune {TOOLS['lune'][1]}'s")


def identical(tmp: Path) -> None:
    from rhr.ir import emit_ir, lune_executable
    from rhr.rbx import binary, emit

    lune = lune_executable()
    script = tmp / "to_binary.luau"
    script.write_text(TO_BINARY, encoding="utf-8")
    sources = sorted([*REPO.glob("tests/fixtures/*.rbxm*"), *REPO.glob("tests/fixtures/*.rbxl*"),
                      *REPO.glob("tests/studio/**/*.rbxl*"), *REPO.glob("examples/*.rbxm*")])
    compared = same = skipped = 0
    for source in sources:
        data = source.read_bytes()
        if data[:8] == b"<roblox!":
            binary_file = source
        else:
            binary_file = tmp / (source.stem + ".rbxl")
            proc = subprocess.run([lune, "run", str(script), str(source), str(binary_file)],
                                  capture_output=True, text=True, timeout=120)
            if proc.returncode:
                # A hand-written fixture with a property of the wrong type (an enum where
                # Roblox has an int): rbx-dom will not save it as binary, and Studio never
                # writes such a file. Nothing to compare.
                skipped += 1
                continue
        for profile in ("full", "static"):
            reference = tmp / f"{source.stem}.{profile}.lune.json"
            import os

            os.environ["RHR_READER"] = "lune"
            try:
                emit_ir(binary_file, reference, profile=profile, report_path=tmp / "lune-report.txt")
            finally:
                os.environ.pop("RHR_READER", None)
            lune_report = [line for line in (tmp / "lune-report.txt").read_text(encoding="utf-8").splitlines()
                           if not line.startswith("wrote ")]
            document, report = emit.emit(binary.read(binary_file.read_bytes()), profile=profile,
                                         source_path=str(binary_file.resolve()))
            ours = json.loads(json.dumps(document))
            theirs = json.loads(reference.read_text(encoding="utf-8"))
            difference = first_difference(theirs["roots"], ours["roots"], "roots")
            if difference is None and report != lune_report:
                difference = f"report: {lune_report} != {report}"
            compared += 1
            if difference is None:
                same += 1
            else:
                check(False, f"{source.name} ({profile}): {difference}")
    print(f"  ({skipped} hand-written fixture(s) rbx-dom cannot save as binary were skipped)")
    check(compared >= 80 and same == compared, f"rhr.rbx and Lune write the same IR ({same}/{compared})")


def main() -> int:
    shared_lists()
    with tempfile.TemporaryDirectory(prefix="rhr-rbx-") as directory:
        identical(Path(directory))
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("rbx reader: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
