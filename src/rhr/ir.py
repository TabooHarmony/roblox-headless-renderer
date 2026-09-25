"""Our IR: the full-fidelity tree extracted by lune + rbx-dom, as JSON on disk.

Shape (written by src/rhr/luau/rhr-ir.luau):

    {"sourcePath": "...", "roots": [node, ...]}
    node = {"className", "name", "props": {prop: {"_t": <datatype>, ...}}, "children": [...]}

The point of this file, versus pinevex's bundled Python parser, is that rbx-dom
knows every property and its real datatype, so nothing is silently dropped and
enums arrive as names instead of raw ints.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from rhr.paths import LUAU_IR_SCRIPT

def lune_executable() -> str:
    """Path to `lune`, or a RuntimeError that says how to install it."""
    from rhr.profile import phase
    from rhr.tools import find_tool, missing_message

    with phase("find lune"):
        found = find_tool("lune")
    if found is None:
        raise RuntimeError(missing_message("lune", "to read Roblox files"))
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


def cached_ir(source_path, *, profile: str = "full") -> Path:
    """IR for a Roblox file, reusing the last conversion of the same bytes.

    An agent runs several commands on one unchanged file (layout, then render, then
    check); converting it through Lune each time costs about a second. The cache key
    is the file's content and location plus the converter script and the Lune
    binary, so an edited or moved file, a new RHR or a new Lune always converts
    again. Each key has its own folder, which also keeps two different files that
    share a name apart.
    """
    from rhr.paths import IR_DIR

    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"no such file: {source_path}")
    lune = Path(lune_executable())
    digest = hashlib.sha256()
    digest.update(source_path.read_bytes())
    digest.update(LUAU_IR_SCRIPT.read_bytes())
    digest.update(f"{profile}|{lune}|{lune.stat().st_size}|{lune.stat().st_mtime_ns}".encode())
    # The IR records where it came from (sourcePath, read again for terrain); the same
    # bytes in another folder are a different entry, so that path is never stale.
    digest.update(str(source_path).encode("utf-8"))
    folder = IR_DIR / digest.hexdigest()[:20]
    suffix = ".json" if profile == "full" else f".{profile}.json"
    target = folder / f"{source_path.stem}{suffix}"
    report = target.with_name(target.name + ".report.txt")
    if target.is_file() and report.is_file():
        # Replay the reader's report (what it could not read), minus its "wrote" line.
        lines = report.read_text(encoding="utf-8").splitlines()
        text = "\n".join(line for line in lines if not line.startswith("wrote "))
        if text.strip():
            print(text.strip(), file=sys.stderr)
        print(f"ir     reused {target} (file unchanged)", file=sys.stderr)
        return target
    emit_ir(source_path, target, profile=profile, report_path=report)
    return target


def emit_ir(source_path, out_path, *, profile: str = "full", report_path=None) -> Path:
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
            "directory with `rokit add --global lune-org/lune@0.10.5`, or run `rhr setup`."
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
    if report_path is not None:
        # Written last: a cached IR counts only once its report exists too.
        Path(report_path).write_text(proc.stdout, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m rhr.ir <source.rbxm> <out.json>")
    print(emit_ir(sys.argv[1], sys.argv[2]))