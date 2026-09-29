"""Wall-clock benchmark of `rhr` commands as an agent runs them: one process per command.

    python scripts/bench.py                       # examples/shop (UI) and examples/tower (3D)
    python scripts/bench.py --place big.rbxl      # add a place: layout, check, scene, scene-dump
    python scripts/bench.py --reps 7 --json out.json
    python scripts/bench.py --compare before.json after.json

Two modes per case:
- warm: the file is unchanged since the last command (the IR, assets and the browser
  worker are warm). This is most of an agent's loop.
- edit: the file was just changed: each run uses a fresh copy under a new name, so it
  is converted again (assets stay cached).

Runs are interleaved across cases, and the median is reported, because the machine
this runs on is rarely idle.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rhr() -> list[str]:
    exe = Path(sys.executable).with_name("rhr.exe" if os.name == "nt" else "rhr")
    return [str(exe)] if exe.exists() else [sys.executable, "-m", "rhr"]


def cases(ui: list[Path], scene: list[Path], place: list[Path], out: Path) -> list[tuple[str, Path, list[str]]]:
    found = []
    for path in ui:
        for command in (["layout"], ["check"], ["hitmap"], ["ui", "--out", str(out / "ui.png")]):
            found.append((f"{command[0]:10} {path.name}", path, command))
    for path in scene:
        for command in (["scene", "--out", str(out / "scene.png")], ["scene-dump"]):
            found.append((f"{command[0]:10} {path.name}", path, command))
    for path in place:
        for command in (["layout"], ["check"], ["scene", "--out", str(out / "place.png")], ["scene-dump"]):
            found.append((f"{command[0]:10} {path.name}", path, command))
    return found


def run(argv: list[str]) -> tuple[float, int, str]:
    started = time.perf_counter()
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return time.perf_counter() - started, proc.returncode, proc.stderr[-400:]


def measure(found, reps: int, modes: list[str], work: Path) -> dict:
    results: dict[str, list[float]] = {}
    rhr = _rhr()
    if "warm" in modes:
        for label, path, command in found:  # prime: convert, download, start the worker
            run([*rhr, command[0], str(path), *command[1:]])
        for rep in range(reps):
            for label, path, command in found:
                seconds, code, err = run([*rhr, command[0], str(path), *command[1:]])
                if code not in (0, 1):
                    print(f"FAILED {label}: {err}", file=sys.stderr)
                results.setdefault(f"warm {label}", []).append(seconds)
    if "edit" in modes:
        for rep in range(reps):
            for index, (label, path, command) in enumerate(found):
                copy = work / f"edit{rep}-{index}" / path.name
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
                seconds, code, err = run([*rhr, command[0], str(copy), *command[1:]])
                if code not in (0, 1):
                    print(f"FAILED {label}: {err}", file=sys.stderr)
                results.setdefault(f"edit {label}", []).append(seconds)
    return results


def report(results: dict[str, list[float]]) -> None:
    print(f"{'case':52} {'median':>8} {'min':>8}")
    for label, times in results.items():
        print(f"{label:52} {statistics.median(times) * 1000:7.0f}ms {min(times) * 1000:7.0f}ms")


def compare(before: dict, after: dict) -> None:
    print(f"{'case':52} {'before':>8} {'after':>8} {'x':>6}")
    for label in after:
        if label not in before:
            continue
        b, a = statistics.median(before[label]), statistics.median(after[label])
        print(f"{label:52} {b * 1000:7.0f}ms {a * 1000:7.0f}ms {b / a:5.1f}x")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="append", type=Path, default=[])
    parser.add_argument("--scene", action="append", type=Path, default=[])
    parser.add_argument("--place", action="append", type=Path, default=[])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--modes", default="warm,edit")
    parser.add_argument("--json", type=Path, help="write the raw times here")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if args.compare:
        compare(*(json.loads(p.read_text()) for p in args.compare))
        return 0
    if not (args.ui or args.scene or args.place):
        args.ui = [ROOT / "examples" / "shop.rbxmx"]
        args.scene = [ROOT / "examples" / "tower.rbxmx"]
    with tempfile.TemporaryDirectory(prefix="rhr-bench-") as tmp:
        work = Path(tmp)
        results = measure(cases(args.ui, args.scene, args.place, work), args.reps,
                          args.modes.split(","), work)
    report(results)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
