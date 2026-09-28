"""Rojo projects as input: build them with `rojo build`, then read the result.

`rhr <command> <project>` accepts a `*.project.json` file, or a directory that holds
`default.project.json`, anywhere a .rbxm/.rbxl file is accepted. The project is built
into the RHR cache (a place when its tree root is a DataModel, a model otherwise)
and everything after that is the normal Roblox-file path.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from rhr.procs import no_window

def project_file(source: Path) -> Path | None:
    """The project file `source` names, or None when it is not a Rojo project."""
    if source.is_dir():
        candidate = source / "default.project.json"
        return candidate if candidate.is_file() else None
    if source.name.endswith(".project.json") and source.is_file():
        return source
    return None


def inputs_digest(project: Path) -> str:
    """What `rojo build` of `project` reads, as one digest: the project file and every
    file under its $path entries (nested project files followed), by path, size and
    modification time. Unchanged digest, unchanged build."""
    digest = hashlib.sha1()
    seen: set[str] = set()

    def add_file(path: Path) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return
        seen.add(key)
        try:
            info = os.stat(path)
        except OSError:
            digest.update(f"{key}|missing\n".encode("utf-8", "surrogateescape"))
            return
        digest.update(f"{key}|{info.st_size}|{info.st_mtime_ns}\n".encode("utf-8", "surrogateescape"))
        if path.name.endswith(".project.json"):
            add_project(path)

    def add_tree(path: Path) -> None:
        if path.is_dir():
            try:
                entries = sorted(os.scandir(path), key=lambda entry: entry.name)
            except OSError:
                return
            digest.update(f"{os.path.normcase(os.path.abspath(path))}/\n".encode("utf-8", "surrogateescape"))
            for entry in entries:
                add_tree(Path(entry.path))
        else:
            add_file(path)

    def add_project(path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        def visit(node) -> None:
            if not isinstance(node, dict):
                return
            if isinstance(node.get("$path"), str):
                add_tree(path.parent / node["$path"])
            for key, value in node.items():
                if not key.startswith("$"):
                    visit(value)

        visit(data.get("tree") or {})

    add_file(project)
    return digest.hexdigest()


def build(project: Path, out_dir: Path) -> Path:
    """Run `rojo build` on `project` and return the built .rbxl or .rbxm file; the last
    build again while nothing it reads has changed (inputs_digest)."""
    from rhr.tools import require

    try:
        data = json.loads(project.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{project} is not valid JSON: {exc}") from None
    tree = data.get("tree") or {}
    is_place = tree.get("$className") == "DataModel"
    name = data.get("name") or project.name.removesuffix(".project.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.rojo{'.rbxl' if is_place else '.rbxm'}"
    stamp = out.with_name(out.name + ".inputs")
    inputs = f"{os.path.normcase(os.path.abspath(project))}|{inputs_digest(project)}"
    try:
        if out.is_file() and stamp.read_text(encoding="utf-8") == inputs:
            return out
    except OSError:
        pass
    rojo = require("rojo", "to build Rojo projects")
    stamp.unlink(missing_ok=True)
    proc = subprocess.run(
        [rojo, "build", str(project), "--output", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        **no_window(),
    )
    if proc.returncode != 0 and "Failed to find tool 'rojo'" in proc.stderr:
        raise RuntimeError(
            "`rojo` is a Rokit shim, but no rokit.toml here lists it. Install it for every "
            "directory with `rokit add --global rojo-rbx/rojo@7.7.0`, or run `rhr setup`."
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"rojo build failed for {project}:\n{detail}")
    if not out.is_file():
        raise RuntimeError(f"rojo build reported success but wrote no file: {out}")
    stamp.write_text(inputs, encoding="utf-8")
    return out
