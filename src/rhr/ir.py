"""Our IR: the full-fidelity tree extracted by lune + rbx-dom, as JSON on disk.

Shape (written by scripts/rhr-ir.luau):

    {"sourcePath": "...", "roots": [node, ...]}
    node = {"className", "name", "props": {prop: {"_t": <datatype>, ...}}, "children": [...]}

The point of this file, versus pinevex's bundled Python parser, is that rbx-dom
knows every property and its real datatype, so nothing is silently dropped and
enums arrive as names instead of raw ints.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LUAU = REPO / "scripts" / "rhr-ir.luau"


def load_ir(path) -> dict:
    """Read an IR JSON file produced by scripts/rhr-ir.luau."""
    data = json.loads(Path(path).read_text())
    if "roots" not in data:
        raise ValueError(f"{path} is not an IR file: no 'roots' key")
    return data


def emit_ir(source_path, out_path, *, profile: str = "full") -> Path:
    """Run the lune dumper on a .rbxm/.rbxmx/.rbxl file and write IR JSON.

    Needs `lune` on PATH. rbx-dom detects binary versus XML by content, so both
    extension flavours go through the same call.
    """
    if profile not in {"full", "visual", "static"}:
        raise ValueError(f"unknown IR profile: {profile}")
    source_path, out_path = Path(source_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["lune", "run", str(LUAU), str(source_path), str(out_path)]
    if profile != "full":
        command.append(profile)
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lune IR dump failed for {source_path} (exit {proc.returncode})\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    if not out_path.exists():
        raise RuntimeError(f"lune reported success but wrote no file: {out_path}")
    # The emitter's own report (unreadable, unmapped, child-name collisions, and
    # whether its class filter still agrees with the reflection database) is the
    # "nothing vanishes in silence" contract. It goes to stderr, with the rest of
    # the progress, so `rhr ir model --out ir.json` can stay pipeable on stdout.
    if proc.stdout.strip():
        print(proc.stdout.strip(), file=sys.stderr)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m rhr.ir <source.rbxm> <out.json>")
    print(emit_ir(sys.argv[1], sys.argv[2]))