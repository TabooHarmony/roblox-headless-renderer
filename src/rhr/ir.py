"""Our IR: the full-fidelity tree extracted by lune + rbx-dom, as JSON on disk.

Shape (written by src/rhr/luau/rhr-ir.luau):

    {"sourcePath": "...", "roots": [node, ...]}
    node = {"className", "name", "props": {prop: {"_t": <datatype>, ...}}, "children": [...]}

The point of this file, versus pinevex's bundled Python parser, is that rbx-dom
knows every property and its real datatype, so nothing is silently dropped and
enums arrive as names instead of raw ints.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from rhr.paths import LUAU_IR_SCRIPT

LUNE_VERSION = "0.10.5"
LUNE_MISSING = (
    "`lune` was not found on PATH. RHR needs Lune {v} to read Roblox files. Install it with "
    "Rokit (`rokit add --global lune-org/lune@{v}`) or download it from "
    "https://github.com/lune-org/lune/releases/tag/v{v} and put it on PATH."
).format(v=LUNE_VERSION)


def lune_executable() -> str:
    """Path to `lune`, or a RuntimeError that says how to install it."""
    found = shutil.which("lune")
    if found is None:
        raise RuntimeError(LUNE_MISSING)
    return found


def load_ir(path) -> dict:
    """Read an IR JSON file produced by src/rhr/luau/rhr-ir.luau."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "roots" not in data:
        raise ValueError(f"{path} is not an IR file: no 'roots' key")
    ensure_paths(data["roots"])
    return data


def _segment(node: dict) -> str:
    return node.get("name") or node.get("className") or "?"


def ensure_paths(nodes: list[dict], parent: str = "") -> None:
    """Give every node a unique slash `path`, as the emitter does.

    Siblings that share a name are all indexed (`Card[1]`, `Card[2]`), so a bare
    name always means exactly one node. The emitter writes these paths itself; this
    fills them in for IR written by hand or by an older emitter, with the same rule.
    """
    counts: dict[str, int] = {}
    for node in nodes:
        counts[_segment(node)] = counts.get(_segment(node), 0) + 1
    seen: dict[str, int] = {}
    for node in nodes:
        name = _segment(node)
        if "path" not in node:
            segment = name
            if counts[name] > 1:
                seen[name] = seen.get(name, 0) + 1
                segment = f"{name}[{seen[name]}]"
            node["path"] = f"{parent}/{segment}" if parent else segment
        ensure_paths(node.get("children") or [], node["path"])


def resolve_path(roots: list[dict], wanted: str) -> dict:
    """The node at `wanted`, or a ValueError that names the candidates.

    A bare name that matches several indexed siblings (`Card` when the file has
    `Card[1]` and `Card[2]`) is an error listing them, never a silent pick.
    """
    by_path: dict[str, dict] = {}

    def walk(node: dict) -> None:
        by_path[node["path"]] = node
        for child in node.get("children") or []:
            walk(child)

    ensure_paths(roots)
    for root in roots:
        walk(root)
    if wanted in by_path:
        return by_path[wanted]
    indexed = sorted(p for p in by_path if p.startswith(wanted + "[") and "/" not in p[len(wanted):])
    if indexed:
        raise ValueError(f"path is ambiguous: {wanted} matches {', '.join(indexed)}")
    raise ValueError(f"path not found in IR: {wanted}")


def emit_ir(source_path, out_path, *, profile: str = "full") -> Path:
    """Run the lune dumper on a .rbxm/.rbxmx/.rbxl file and write IR JSON.

    Needs `lune` on PATH. rbx-dom detects binary versus XML by content, so both
    extension flavours go through the same call.
    """
    if profile not in {"full", "visual", "static"}:
        raise ValueError(f"unknown IR profile: {profile}")
    source_path, out_path = Path(source_path).resolve(), Path(out_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"no such file: {source_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [lune_executable(), "run", str(LUAU_IR_SCRIPT), str(source_path), str(out_path)]
    if profile != "full":
        command.append(profile)
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 and "Failed to find tool 'lune'" in proc.stderr:
        # Rokit's shim only resolves tools listed in a rokit.toml above the cwd.
        raise RuntimeError(
            "`lune` is a Rokit shim, but no rokit.toml here lists it. Install it for every "
            f"directory with `rokit add --global lune-org/lune@{LUNE_VERSION}`."
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