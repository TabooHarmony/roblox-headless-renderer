"""UI that code builds: run a story file and draw what it made.

`rhr ui Shop.story.luau` (and `layout`, `check`, `hitmap`): the story is a
ModuleScript in a Rojo project, in any of the usual forms: a function(target)
(Hoarcekat, UI Labs), a UI Labs table (react + reactRoblox, roact, fusion, vide, or a
generic render), a Flipbook table. RHR builds the project with Rojo, finds the story's
ModuleScript with `rojo sourcemap`, runs it in Lune with a copy of the Roblox side
(luau/story-runtime.luau: instances, events, the services UI code touches,
instance-based require), and saves the UI it built as a model file, which the
command then reads like any other. Nothing about a UI library is special-cased: they
all end in Instance.new and property sets.

What does not carry over: sizes read while the story runs (AbsoluteSize,
AbsolutePosition) are zero, since RHR lays the UI out afterwards; tweens end at their
goal; the story's controls take their defaults; nothing is clicked.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from rhr.paths import IR_DIR, PACKAGE

SUFFIXES = (".story.luau", ".story.lua")
TIMEOUT_S = 120


def is_story(path: Path) -> bool:
    return path.name.lower().endswith(SUFFIXES)


def story_name(path: Path) -> str:
    name = path.name
    for suffix in SUFFIXES:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def find_project(story: Path) -> Path:
    """The default.project.json nearest above the story."""
    for folder in story.resolve().parents:
        candidate = folder / "default.project.json"
        if candidate.is_file():
            return candidate
    raise ValueError(f"{story} is not inside a Rojo project (no default.project.json above it): a story "
                     "runs in its project, where its require() calls lead")


def _same(a: Path, b: Path) -> bool:
    return str(a).casefold() == str(b).casefold() if __import__("os").name == "nt" else a == b


def module_path(project: Path, story: Path) -> tuple[list[str], dict[str, str]]:
    """The story's ModuleScript as names from the built file's root, and every script's
    full name -> file (to point errors at files)."""
    from rhr.procs import no_window
    from rhr.tools import require

    rojo = require("rojo", "to run a story in its Rojo project")
    proc = subprocess.run([rojo, "sourcemap", "--absolute", str(project)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=project.parent, stdin=subprocess.DEVNULL,
                          timeout=TIMEOUT_S, **no_window())
    if proc.returncode != 0:
        raise RuntimeError(f"rojo sourcemap failed for {project}:\n{(proc.stderr or proc.stdout).strip()}")
    tree = json.loads(proc.stdout or "null")
    if not tree:
        raise ValueError(f"{project} has no scripts, so no story to run")
    place = tree.get("className") == "DataModel"
    target = story.resolve()
    found: list[str] | None = None
    files: dict[str, str] = {}

    def walk(node: dict, names: list[str]) -> None:
        nonlocal found
        full = ".".join(names)
        for file in node.get("filePaths") or []:
            # (On Windows Rojo writes verbatim paths: //?/C:/...)
            path = Path(re.sub(r"^(?://|\\\\)\?[/\\]", "", file))
            if path.suffix in (".luau", ".lua"):
                files[full] = str(path)
            if found is None and _same(path.resolve(), target):
                found = list(names)
        for child in node.get("children") or []:
            walk(child, [*names, child["name"]])

    # A place's scripts hang from its services; a model's root is kept in ReplicatedStorage.
    walk(tree, [] if place else ["ReplicatedStorage", tree["name"]])
    if found is None:
        raise ValueError(f"{story} is not part of the Rojo project {project} (rojo sourcemap does not list it)")
    return found, files


def _point_at_files(text: str, files: dict[str, str], root: Path) -> str:
    """Instance full names in an error -> the files they come from."""
    for full in sorted(files, key=len, reverse=True):
        if full and full in text:
            try:
                shown = str(Path(files[full]).relative_to(root))
            except ValueError:
                shown = files[full]
            text = re.sub(rf"(?<![\w.]){re.escape(full)}(?![\w])", shown.replace("\\", "\\\\"), text)
    return text


def _tidy(text: str) -> str:
    """The error and the lines of the project's own files it went through; not Lune's
    internals or the runtime's."""
    message: list[str] = []
    frames: list[str] = []
    for line in text.splitlines():
        frame = re.search(r'\[string "([^"]+)"\]:(\d+)(?::\s*(.+))?', line)
        if frame:
            if frame.group(3) and not message and not frames:  # `[string "x"]:3: the error`
                message.append(frame.group(3))
            where = f"  at {frame.group(1)}:{frame.group(2)}"
            if where not in frames:
                frames.append(where)
        elif line.strip() and not line.startswith((" ", "\t", "stack traceback")) and not frames and not re.match(
                r"^(?:__mlua|\[C\]|[A-Za-z]:\\)", line):
            message.append(re.sub(r"^(?:runtime|syntax) error: ", "", line))
    return "\n".join(message + frames) or text


def build(story: Path, *, width: int = 1920, height: int = 1080, log=None) -> Path:
    """Run `story` and return the model file with the UI it built."""
    from rhr import rojo
    from rhr.ir import lune_executable
    from rhr.procs import no_window

    from rhr.profile import phase

    project = find_project(story)
    with phase("story: rojo build"):
        built = rojo.build(project, IR_DIR)
    with phase("story: rojo sourcemap"):
        names, files = module_path(project, story)
    name = story_name(story)
    key = hashlib.sha1(str(story.resolve()).encode("utf-8")).hexdigest()[:12]
    # One folder per story, the file named after it: documents name their source by
    # this file's name ("model": "Shop.story.json").
    out = IR_DIR / "stories" / key / f"{name}.story.rbxm"
    out.parent.mkdir(parents=True, exist_ok=True)
    with phase("story: run (Lune)"):
        proc = subprocess.run(
            [lune_executable(), "run", str(PACKAGE / "luau" / "story-runtime.luau"), str(built), json.dumps(names),
             str(out), str(width), str(height), name],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_S, **no_window())
    problems = _tidy(_point_at_files(proc.stderr.strip(), files, project.parent))
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"the story {story.name} failed:\n{problems or proc.stdout.strip() or 'no output'}")
    if log is not None:
        count = proc.stdout.strip().rpartition(" ")[2]
        log(f"story  {story.name}: ran it in its Rojo project, {count} instances built")
        for line in problems.splitlines()[:10]:
            log(f"story  {line}")
    return out
