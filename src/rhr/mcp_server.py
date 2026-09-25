#!/usr/bin/env python3
"""Thin stdio MCP adapter for RHR's stable agent iteration loop.

The `rhr` CLI remains the source of truth. This process only maps MCP tools to
those tested CLI contracts and returns structured results plus image content where
useful. Needs the MCP SDK: `pip install "roblox-headless-renderer[mcp]"`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.types import Image
except ImportError as exc:  # pragma: no cover - depends on the optional extra
    raise SystemExit(
        'rhr-mcp needs the MCP SDK: pip install "roblox-headless-renderer[mcp]"'
    ) from exc

from rhr.paths import CACHE

RHR = [sys.executable, "-m", "rhr"]
MCP_OUT = CACHE / "mcp"

server = FastMCP(
    "roblox-headless-renderer",
    instructions=(
        "Use RHR for cheap local Roblox authoring iteration. Inspect scene geometry "
        "before rendering when paths/bounds matter; use preview for a composed static "
        "frame; use compare to quantify before/after changes. Studio is a calibration "
        "oracle, not part of this MCP inner loop."
    ),
)


def _run(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*RHR, *args],
        # Never hand the child our stdin: it is the MCP protocol pipe, and on Windows a
        # child inheriting a pipe another thread is reading hangs during startup.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"rhr {' '.join(args)} exited {result.returncode}")
    return result


def _json_command(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    result = _run(args, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"rhr command did not return JSON: {' '.join(args)}\n{result.stdout}"
        ) from exc


def _append(options: list[str], flag: str, value: Any) -> None:
    if value is not None:
        options.extend([flag, str(value)])


@server.tool(
    name="rhr_inspect_scene",
    description=(
        "Inspect a Roblox model/place or cached RHR IR as machine-readable static scene "
        "geometry: paths, bounds, cameras, materials, lights, beams, fallbacks, "
        "unsupported visuals, and local asset availability."
    ),
)
def inspect_scene(file: str, texture_dir: str | None = None) -> dict[str, Any]:
    args = ["scene-dump", file]
    _append(args, "--texture-dir", texture_dir)
    return _json_command(args)


@server.tool(
    name="rhr_preview",
    description=(
        "Render one composed Roblox authoring preview: 3D world, in-world UI, ScreenGui, "
        "and particle effects frozen at their fullest moment (effect_time picks another; "
        "effects=False leaves them out). Returns metadata and "
        "the PNG image itself. Persistent Chromium is warmed automatically."
    ),
    structured_output=False,
)
def preview(
    file: str,
    out: str | None = None,
    viewport: str = "676x336",
    camera: str | None = None,
    look_at: str | None = None,
    fov: float | None = None,
    focus: str | None = None,
    view: str | None = None,
    shadows: bool = False,
    texture_dir: str | None = None,
    effect_time: float | None = None,
    effects: bool = True,
    seed: int = 0,
    topbar_height: float | None = None,
    persistent_browser: bool = True,
) -> list[Any]:
    source = Path(file)
    if out is None:
        MCP_OUT.mkdir(parents=True, exist_ok=True)
        out_path = MCP_OUT / f"{source.stem}-preview.png"
    else:
        out_path = Path(out)

    if persistent_browser:
        # Only a speed-up: if the worker cannot start, render in a fresh Chromium.
        try:
            _run(["browser", "start"], timeout=90)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass

    args = ["preview", file, "--viewport", viewport, "--out", str(out_path)]
    _append(args, "--camera", camera)
    _append(args, "--look-at", look_at)
    _append(args, "--fov", fov)
    _append(args, "--focus", focus)
    _append(args, "--view", view)
    if shadows:
        args.append("--shadows")
    _append(args, "--texture-dir", texture_dir)
    _append(args, "--effect-time", effect_time)
    if not effects:
        args.append("--no-effects")
    if seed:
        args.extend(["--seed", str(seed)])
    _append(args, "--topbar-height", topbar_height)

    # The first preview of a big place also downloads its assets (rhr.fetch).
    result = _run(args, timeout=900)
    metadata = {
        "path": str(out_path),
        "viewport": viewport,
        "log": result.stderr.strip().splitlines(),
    }
    return [metadata, Image(path=out_path)]


@server.tool(
    name="rhr_compare",
    description=(
        "Compare two same-size PNG previews. Returns pixel-change metrics and silhouette "
        "IoU, useful for distinguishing geometry movement from styling/shading changes."
    ),
)
def compare(
    before: str,
    after: str,
    background: str = "20242b",
    silhouette_threshold: float = 8.0,
) -> dict[str, Any]:
    return _json_command(
        [
            "compare",
            before,
            after,
            "--background",
            background,
            "--silhouette-threshold",
            str(silhouette_threshold),
            "--json",
        ]
    )


@server.tool(
    name="rhr_browser",
    description=(
        "Manage RHR's persistent Chromium worker. Actions: start, status, stop. "
        "Normally preview starts it automatically."
    ),
)
def browser(action: str = "status") -> dict[str, Any]:
    if action not in {"start", "status", "stop"}:
        raise ValueError("action must be start, status, or stop")
    return _json_command(["browser", action], timeout=30)


def self_check() -> dict[str, Any]:
    """Cheap adapter smoke test used by the repository test suite."""
    from PIL import Image as PILImage

    status = browser("status")
    with tempfile.TemporaryDirectory(prefix="rhr-mcp-check-") as tmp:
        sample = Path(tmp) / "sample.png"
        PILImage.new("RGBA", (32, 32), (255, 0, 0, 255)).save(sample)
        comparison = compare(str(sample), str(sample))
    return {
        "browser_status_has_running": "running" in status,
        "self_compare_iou": comparison["silhouette"]["iou"],
        "self_compare_changed_pct": comparison["changed_pct"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-check", action="store_true")
    args, unknown = parser.parse_known_args()
    if args.self_check:
        print(json.dumps(self_check(), sort_keys=True))
        return 0
    if unknown:
        raise SystemExit(f"unknown arguments: {' '.join(unknown)}")
    server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
