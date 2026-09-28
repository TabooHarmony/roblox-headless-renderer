#!/usr/bin/env python3
"""UI that code builds: a story file is run in its Rojo project and drawn.

`tests/fixtures/rojo_stories/` is a place project with a tiny UI helper standing in
for a UI library (Packages/Mini.luau) and one story per form: a function(target)
that reads sizes and tweens (Badge), a UI Labs table with controls (Panel), one that
sizes itself from the screen (Viewport), one that fails (Broken) and one that
reaches for Lune's own globals (Escape).

    python tests/test_story.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
STORIES = ROOT / "tests" / "fixtures" / "rojo_stories" / "src"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)


def layout(story: str, *extra: str) -> dict | None:
    proc = run(["layout", str(STORIES / story), "--viewport", "800x600", *extra])
    check(proc.returncode == 0, f"layout {story} exits 0 {proc.stderr[-400:] if proc.returncode else ''}")
    return json.loads(proc.stdout) if proc.returncode == 0 else None


def main() -> int:
    print("story: the function form (mounts into target, returns a cleanup)")
    doc = layout("Badge.story.luau")
    if doc:
        rects = doc["rects"]
        check(rects.get("Badge/Target/Badge") == {"x": 300.0, "y": 40.0, "w": 200.0, "h": 80.0},
              f"a module's component, drawn where its tween ends: {rects.get('Badge/Target/Badge')}")
        check("Badge/Target/Claim" in rects, "an instance the story made itself")
        check(doc["viewport"] == [800, 600], "drawn at --viewport")

    print("story: the UI Labs table form, controls at their defaults")
    doc = layout("Panel.story.luau", "--rich")
    if doc:
        nodes = {node["path"]: node for node in doc["nodes"]}
        panel = nodes.get("Panel/Target/Panel", {}).get("rect")
        check(panel is not None and panel["h"] == 180.0, f"a slider control's value (3 rows): {panel}")
        check(all(f"Panel/Target/Panel/Row{row}" in nodes for row in (1, 2, 3)), "one button per row")
        title = nodes.get("Panel/Target/Panel/Title", {}).get("text", {}).get("content")
        check(title == "Settings", f"a plain control's default: {title!r}")
        check(doc["model"] == "Panel.story.json", f"documents name the story: {doc['model']!r}")

    print("story: code that reads the screen size gets the viewport")
    doc = layout("Viewport.story.luau", "--rich")
    if doc:
        nodes = {node["path"]: node for node in doc["nodes"]}
        check(nodes.get("Viewport/Target/Bar", {}).get("rect", {}).get("w") == 400.0,
              f"target.AbsoluteSize: {nodes.get('Viewport/Target/Bar', {}).get('rect')}")
        size = nodes.get("Viewport/Target/Size", {}).get("text", {}).get("content")
        check(size == "800x600", f"CurrentCamera.ViewportSize: {size!r}")

    print("story: check, and a picture")
    proc = run(["check", str(STORIES / "Panel.story.luau")])
    check(proc.returncode in (0, 1) and json.loads(proc.stdout or "{}").get("model") == "Panel.story.json",
          f"check names the story {proc.stderr[-300:] if proc.returncode > 1 else ''}")
    with tempfile.TemporaryDirectory(prefix="rhr-story-") as directory:
        out = Path(directory) / "badge.png"
        proc = run(["ui", str(STORIES / "Badge.story.luau"), "--viewport", "800x600", "--out", str(out)])
        check(proc.returncode == 0 and out.is_file() and out.stat().st_size > 1000,
              f"ui draws the story {proc.stderr[-300:] if proc.returncode else ''}")

    print("story: run again only when something it runs on changed")
    first = run(["layout", str(STORIES / "Badge.story.luau"), "--viewport", "800x600"])
    again = run(["layout", str(STORIES / "Badge.story.luau"), "--viewport", "800x600"])
    check(again.returncode == 0 and "unchanged since its last run" in again.stderr and again.stdout == first.stdout,
          f"unchanged: the UI it built is reused {again.stderr[-300:]}")
    other = run(["layout", str(STORIES / "Badge.story.luau"), "--viewport", "640x480"])
    check("ran it in its Rojo project" in other.stderr, "another viewport runs it again")
    helper = next(path for path in sorted(STORIES.rglob("*.luau")) if not path.name.endswith(".story.luau"))
    os.utime(helper)
    edited = run(["layout", str(STORIES / "Badge.story.luau"), "--viewport", "800x600"])
    check("ran it in its Rojo project" in edited.stderr and edited.stdout == first.stdout,
          f"a project file changed ({helper.name}): run again")

    print("story: errors point at the project's files")
    proc = run(["layout", str(STORIES / "Broken.story.luau")])
    check(proc.returncode == 2, f"a failing story exits 2 (got {proc.returncode})")
    check("NotAProperty is not a valid member of Frame" in proc.stderr, f"the error: {proc.stderr.strip()[-300:]}")
    check(re.search(r"at src[\\/]Broken\.story\.luau:5", proc.stderr) is not None, "the line, in the story's file")
    check("story-runtime" not in proc.stderr, "not RHR's own runtime frames")

    print("story: no way to Lune's own globals through getfenv")
    proc = run(["layout", str(STORIES / "Escape.story.luau")])
    check(proc.returncode == 2 and "getfenv is not available" in proc.stderr,
          f"refused: {proc.stderr.strip()[-200:]}")

    print("story: outside a Rojo project")
    with tempfile.TemporaryDirectory(prefix="rhr-story-loose-") as directory:
        loose = Path(directory) / "Loose.story.luau"
        shutil.copy(STORIES / "Viewport.story.luau", loose)
        proc = run(["layout", str(loose)])
    check(proc.returncode == 2 and "Rojo project" in proc.stderr, f"says why: {proc.stderr.strip()[-200:]}")

    print(f"story: {len(failures)} failed" if failures else "story: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
