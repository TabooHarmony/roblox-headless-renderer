#!/usr/bin/env python3
"""Host-side MCP adapter: protocol discovery + preview image content.

The core project venv intentionally does not depend on the MCP SDK. This test
uses the host python when the SDK exists and cleanly skips otherwise.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_PYTHON = shutil.which("python3")

CLIENT = r'''
import anyio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

async def main():
    params = StdioServerParameters(command="./bin/rhr-mcp", cwd=".")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            expected = ["rhr_inspect_scene", "rhr_preview", "rhr_compare", "rhr_browser"]
            if names != expected:
                raise SystemExit(f"unexpected tools: {names}")
            result = await session.call_tool(
                "rhr_preview",
                {
                    "file": "tests/fixtures/preview_world_ui.rbxmx",
                    "viewport": "320x200",
                    "view": "iso",
                },
            )
            if result.isError:
                raise SystemExit("preview tool returned an MCP error")
            types = [block.type for block in result.content]
            if types != ["text", "image"]:
                raise SystemExit(f"unexpected preview content: {types}")
            image = result.content[1]
            if image.mimeType != "image/png" or len(image.data) < 100:
                raise SystemExit("preview image payload is missing/too small")
            print("mcp tools:", ",".join(names))
            print("mcp preview:", types, image.mimeType, len(image.data))

anyio.run(main)
'''


def main() -> int:
    if HOST_PYTHON is None:
        print("mcp adapter: SKIP (no host python3)")
        return 0
    probe = subprocess.run(
        [HOST_PYTHON, "-c", "import mcp.server.fastmcp"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode:
        print("mcp adapter: SKIP (host MCP SDK unavailable)")
        return 0

    check = subprocess.run(
        [str(ROOT / "bin/rhr-mcp"), "--self-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check.returncode:
        print(check.stdout, end="")
        print(check.stderr, end="", file=sys.stderr)
        return check.returncode

    result = subprocess.run(
        [HOST_PYTHON, "-c", CLIENT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Always leave the optional shared worker stopped after this test.
    subprocess.run(
        [str(ROOT / "bin/rhr"), "browser", "stop"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    if result.returncode:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    print(result.stdout.strip())
    print("mcp adapter: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
