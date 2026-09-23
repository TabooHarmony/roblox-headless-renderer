#!/usr/bin/env python3
"""Thin stdio MCP adapter for RHR's stable agent iteration loop.

The renderer remains the source of truth in bin/rhr. This host-side process only
maps MCP tools to those tested CLI contracts and returns structured results plus
image content where useful.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

REPO = Path(__file__).resolve().parents[1]
RHR = REPO / "bin" / "rhr"
MCP_OUT = REPO / "out" / "mcp"

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
        [str(RHR), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
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
        "and optionally deterministic particles at a fixed time. Returns metadata and "
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
    time_s: float | None = None,
    seed: int = 0,
    burst: int = 0,
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
        _run(["browser", "start"], timeout=30)

    args = ["preview", file, "--viewport", viewport, "--out", str(out_path)]
    _append(args, "--camera", camera)
    _append(args, "--look-at", look_at)
    _append(args, "--fov", fov)
    _append(args, "--focus", focus)
    _append(args, "--view", view)
    if shadows:
        args.append("--shadows")
    _append(args, "--texture-dir", texture_dir)
    _append(args, "--time", time_s)
    if time_s is not None:
        args.extend(["--seed", str(seed), "--burst", str(burst)])
    _append(args, "--topbar-height", topbar_height)

    result = _run(args)
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
    status = browser("status")
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "authored-fixture.png"
        _run(["render", str(REPO / "tests/fixtures/grid_offset.rbxmx"),
              "--out", str(png), "--viewport", "400x300"])
        comparison = compare(str(png), str(png))
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
