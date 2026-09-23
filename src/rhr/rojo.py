"""Rojo projects as input: build them with `rojo build`, then read the result.

`rhr <command> <project>` accepts a `*.project.json` file, or a directory that holds
`default.project.json`, anywhere a .rbxm/.rbxl file is accepted. The project is built
into the RHR cache (a place when its tree root is a DataModel, a model otherwise)
and everything after that is the normal Roblox-file path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

def project_file(source: Path) -> Path | None:
    """The project file `source` names, or None when it is not a Rojo project."""
    if source.is_dir():
        candidate = source / "default.project.json"
        return candidate if candidate.is_file() else None
    if source.name.endswith(".project.json") and source.is_file():
        return source
    return None


def build(project: Path, out_dir: Path) -> Path:
    """Run `rojo build` on `project` and return the built .rbxl or .rbxm file."""
    from rhr.tools import find_tool, missing_message

    rojo = find_tool("rojo")
    if rojo is None:
        raise RuntimeError(missing_message("rojo", "to build Rojo projects"))
    try:
        data = json.loads(project.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{project} is not valid JSON: {exc}") from None
    tree = data.get("tree") or {}
    is_place = tree.get("$className") == "DataModel"
    name = data.get("name") or project.name.removesuffix(".project.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.rojo{'.rbxl' if is_place else '.rbxm'}"
    proc = subprocess.run(
        [rojo, "build", str(project), "--output", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
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
    return out
