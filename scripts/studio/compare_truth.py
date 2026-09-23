#!/usr/bin/env python3
"""Compare RHR against the ground truth Studio recorded in a saved place.

    python scripts/studio/compare_truth.py tests/studio/<place>.rbxlx [--json]

The place must carry ServerStorage.RHRTruth, written by
scripts/studio/export_truth.luau. RHR lays the place out on the same viewport
(edit mode has no top bar, so --topbar-height defaults to 0) and every visible
GuiObject's rect must match Studio's AbsolutePosition/AbsoluteSize within
--tolerance pixels; every part's position and size must match within
--stud-tolerance. The bar is "roughly right" (docs/GOAL.md), not pixel identity.

Text objects sized by their text (AutomaticSize on a TextLabel/TextButton/TextBox)
also get --text-tolerance (a fraction of the rect's larger side): glyph widths at
small sizes differ from Roblox's by a few percent (docs/known-approximations.md).
When Studio recorded a text object's TextBounds, RHR's laid-out text extent
(`layout --rich` text.bounds) must match it within 2px + --text-tolerance x 2.
Exit 0 when everything matches, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
READ_TRUTH = HERE / "read_truth.luau"


def read_truth(place: Path) -> dict:
    lune = shutil.which("lune")
    if lune is None:
        raise RuntimeError("`lune` is not on PATH")
    proc = subprocess.run(
        [lune, "run", str(READ_TRUTH), str(place)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    truth = json.loads(proc.stdout)
    if truth.get("format") != "rhr-studio-truth/1":
        raise RuntimeError(f"unknown truth format: {truth.get('format')!r}")
    # Roblox's JSONEncode writes an empty table as [], not {}.
    for key in ("gui", "parts"):
        if not truth.get(key):
            truth[key] = {}
    return truth


def rhr_json(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "rhr", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rhr {args[0]} failed: {proc.stderr.strip()[-500:]}")
    return json.loads(proc.stdout)


def _hidden(path: str, gui: dict) -> bool:
    """A node is hidden when it or any recorded ancestor has Visible=false."""
    parts = path.split("/")
    return any(gui.get("/".join(parts[:end]), {}).get("visible") is False for end in range(1, len(parts) + 1))


TEXT_CLASSES = {"TextLabel", "TextButton", "TextBox"}


def _text_sized_paths(place: Path) -> set[str]:
    """Paths of text objects whose size comes from measuring their text."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rhr-truth-ir-") as tmp:
        out = Path(tmp) / "ir.json"
        proc = subprocess.run(
            [sys.executable, "-m", "rhr", "ir", str(place), "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"rhr ir failed: {proc.stderr.strip()[-500:]}")
        from rhr.ir import load_ir

        found: set[str] = set()

        def walk(node: dict) -> None:
            automatic = (node.get("props") or {}).get("AutomaticSize")
            name = automatic.get("name") if isinstance(automatic, dict) else automatic
            if node.get("className") in TEXT_CLASSES and name not in (None, "None"):
                found.add(node["path"])
            for child in node.get("children") or []:
                walk(child)

        for root in load_ir(out)["roots"]:
            walk(root)
        return found


def compare(place: Path, tolerance: float, stud_tolerance: float, topbar_height: float,
            text_tolerance: float = 0.04) -> dict:
    truth = read_truth(place)
    text_sized = _text_sized_paths(place)
    width, height = (int(round(value)) for value in truth["viewport"])
    rich = rhr_json(["layout", str(place), "--rich", "--viewport", f"{width}x{height}",
                     "--topbar-height", str(topbar_height)]) if truth["gui"] else {"nodes": []}
    layout = {node["path"]: node["rect"] for node in rich["nodes"]}
    laid_out_text = {node["path"]: (node.get("text") or {}).get("bounds") for node in rich["nodes"]}
    gui_rows = []
    for path, want in sorted(truth["gui"].items()):
        if _hidden(path, truth["gui"]):
            continue
        got = layout.get(path)
        if got is None:
            gui_rows.append({"path": path, "status": "missing", "studio": want})
            continue
        delta = max(abs(got[key] - want[key]) for key in ("x", "y", "w", "h"))
        allowed = tolerance + (text_tolerance * max(want["w"], want["h"]) if path in text_sized else 0.0)
        text_row = None
        if want.get("text") and want["text"][0] >= 1:
            bounds = laid_out_text.get(path)
            if bounds is None:
                text_row = {"status": "missing"}
            else:
                text_delta = max(abs(a - b) for a, b in zip(bounds, want["text"]))
                text_allowed = 2.0 + 2 * text_tolerance * max(want["text"])
                text_row = {
                    "status": "ok" if text_delta <= text_allowed else "off",
                    "delta": round(text_delta, 2), "studio": want["text"], "rhr": bounds,
                }
        if text_row is not None and text_row["status"] != "ok":
            gui_rows.append({"path": path + " (text)", "status": text_row["status"],
                             "delta": text_row.get("delta", 0.0), "studio": text_row.get("studio"),
                             "rhr": text_row.get("rhr")})
        elif text_row is not None:
            gui_rows.append({"path": path + " (text)", "status": "ok", "delta": text_row["delta"]})
        gui_rows.append({
            "path": path,
            "status": "ok" if delta <= allowed else "off",
            "delta": round(delta, 3),
            "allowed": round(allowed, 3),
            "textSized": path in text_sized,
            "studio": {key: want[key] for key in ("x", "y", "w", "h")},
            "rhr": got,
        })

    dump = rhr_json(["scene-dump", str(place)]) if truth["parts"] else {"parts": []}
    rhr_parts = {part["path"]: part for part in dump["parts"]}
    part_rows = []
    for path, want in sorted(truth["parts"].items()):
        got = rhr_parts.get(path)
        if got is None:
            part_rows.append({"path": path, "status": "missing", "studio": want})
            continue
        delta = max(
            max(abs(a - b) for a, b in zip(got["position"], want["position"])),
            max(abs(a - b) for a, b in zip(got["size"], want["size"])),
        )
        # Angles compare modulo 360; 0.05 degrees absorbs Studio's 3-decimal rounding.
        angle = max(abs((a - b + 180.0) % 360.0 - 180.0) for a, b in zip(got["orientation"], want["orientation"]))
        part_rows.append({
            "path": path,
            "status": "ok" if delta <= stud_tolerance and angle <= 0.05 else "off",
            "delta": round(max(delta, angle / 1000.0), 4),
            "angleDelta": round(angle, 4),
            "studio": {key: want[key] for key in ("position", "orientation", "size")},
            "rhr": {key: got[key] for key in ("position", "orientation", "size")},
        })

    rows = gui_rows + part_rows
    return {
        "place": place.name,
        "viewport": [width, height],
        "tolerance": {"px": tolerance, "studs": stud_tolerance, "text": text_tolerance},
        "textSized": sorted(text_sized & set(truth["gui"])),
        "gui": {"checked": len(gui_rows), "ok": sum(r["status"] == "ok" for r in gui_rows)},
        "parts": {"checked": len(part_rows), "ok": sum(r["status"] == "ok" for r in part_rows)},
        "passed": all(r["status"] == "ok" for r in rows),
        "problems": [r for r in rows if r["status"] != "ok"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("place", type=Path)
    parser.add_argument("--tolerance", type=float, default=2.0, help="max GUI rect error in pixels")
    parser.add_argument("--stud-tolerance", type=float, default=0.01, help="max part error in studs")
    parser.add_argument("--text-tolerance", type=float, default=0.04,
                        help="extra allowance for text-sized objects, as a fraction of their larger side")
    parser.add_argument("--topbar-height", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = compare(args.place, args.tolerance, args.stud_tolerance, args.topbar_height, args.text_tolerance)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"compare_truth: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['place']}: viewport {report['viewport'][0]}x{report['viewport'][1]}  "
              f"gui {report['gui']['ok']}/{report['gui']['checked']} within {args.tolerance}px  "
              f"parts {report['parts']['ok']}/{report['parts']['checked']} within {args.stud_tolerance} studs  "
              f"({len(report['textSized'])} text-sized, +{args.text_tolerance:.0%})")
        for row in sorted(report["problems"], key=lambda r: -r.get("delta", float("inf")))[:20]:
            detail = f"off by {row['delta']}" if row["status"] == "off" else "not in RHR output"
            print(f"  {row['status']:7} {row['path']}  {detail}  studio={row['studio']}  rhr={row.get('rhr')}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
