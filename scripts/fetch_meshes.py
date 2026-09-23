#!/usr/bin/env python3
"""Populate RHR's local Roblox mesh cache.

Rendering never fetches mesh assets from the network. This helper discovers
MeshPart / SpecialMesh:FileMesh IDs in a model or RHR IR, downloads public asset
bytes when available, decompresses gzip transport, validates the Roblox mesh
version header, and writes assets/cache/meshes/<asset_id>.mesh.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rhr.ir import emit_ir  # noqa: E402

DEFAULT_CACHE = REPO / "assets" / "cache" / "meshes"


def asset_id(value) -> str | None:
    text = str(value or "")
    for pattern in (r"rbxassetid://(\d+)", r"[?&]id=(\d+)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    matches = re.findall(r"(\d+)", text)
    return matches[-1] if matches else None


def mesh_refs(obj) -> set[str]:
    """Return unique external mesh IDs required by a typed RHR IR."""
    found: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            class_name = value.get("className")
            props = value.get("props") or {}
            if class_name == "MeshPart":
                ref = asset_id(props.get("MeshId"))
                if ref:
                    found.add(ref)
            elif class_name == "SpecialMesh":
                mesh_type = props.get("MeshType")
                if isinstance(mesh_type, dict):
                    mesh_type = mesh_type.get("name")
                if mesh_type == "FileMesh":
                    ref = asset_id(props.get("MeshId"))
                    if ref:
                        found.add(ref)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(obj)
    return found


def load_source(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    with tempfile.TemporaryDirectory(prefix="rhr-fetch-meshes-") as directory:
        ir = Path(directory) / "model.static.json"
        emit_ir(path, ir, profile="static")
        return json.loads(ir.read_text())


def fetch_mesh(asset: str, cache_dir: Path, *, timeout: float = 20.0) -> tuple[str, str]:
    destination = cache_dir / f"{asset}.mesh"
    if destination.is_file() and destination.stat().st_size:
        return asset, f"cached {destination.stat().st_size} bytes"

    url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset}"
    request = urllib.request.Request(url, headers={"User-Agent": "RHR-mesh-cache/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return asset, f"missing ({exc})"

    try:
        raw = gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload
    except (gzip.BadGzipFile, EOFError) as exc:
        return asset, f"invalid gzip ({exc})"

    if not raw.startswith(b"version "):
        return asset, f"not a Roblox mesh ({raw[:24]!r})"

    version_line = raw.splitlines()[0].decode("ascii", errors="replace")
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".mesh.tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return asset, f"fetched {len(raw)} bytes {version_line}"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: python scripts/fetch_meshes.py <model|ir.json> [cache-dir]")
        return 0 if argv else 2

    source = Path(argv[0])
    if not source.is_file():
        print(f"fetch_meshes: no such file: {source}", file=sys.stderr)
        return 2
    cache_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_CACHE

    try:
        data = load_source(source)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"fetch_meshes: {exc}", file=sys.stderr)
        return 2

    ids = sorted(mesh_refs(data), key=int)
    print(f"cache dir : {cache_dir}")
    print(f"mesh ids  : {len(ids)}")
    if not ids:
        return 0

    workers = min(8, len(ids))
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_mesh, asset, cache_dir): asset for asset in ids}
        for future in as_completed(futures):
            asset, message = future.result()
            results[asset] = message

    good = 0
    for asset in ids:
        message = results[asset]
        if message.startswith(("cached ", "fetched ")):
            good += 1
        print(f"  {asset}: {message}")
    print(f"cached    : {good}/{len(ids)}")
    return 0 if good == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
