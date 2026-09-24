#!/usr/bin/env python3
"""Roblox-asset plumbing that needs neither the network nor a browser.

- rhr.unions decodes CSGMDL union meshes (versions 2 and 5), built here in the
  documented layout, and packs them for the scene page.
- rhr.rbxl_raw reads ZSTD-compressed chunks and in-memory files (union assets).
- scene/roblox_materials.json has Roblox's material map ids for parts and terrain.
- rhr.fetch picks the current or pre-2022 material set the way Roblox does, asks
  only for the maps the file uses, and never touches the network offline.

    python tests/test_roblox_assets.py
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
os.environ["RHR_OFFLINE"] = "1"

failures: list[str] = []

XOR = bytes((86, 46, 110, 88, 49, 32, 48, 4, 52, 105, 12, 119, 12, 1, 94, 0,
             26, 96, 55, 105, 29, 82, 43, 7, 79, 36, 89, 101, 83, 4, 122))


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def obfuscate(data: bytes) -> bytes:
    return bytes(b ^ XOR[i % len(XOR)] for i, b in enumerate(data))


# One triangle: (0,0,0) (1,0,0) (0,1,0), red, blue, green.
POSITIONS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
COLORS = [(255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)]


def csgmdl_v2() -> bytes:
    body = b"CSGMDL" + struct.pack("<I", 2) + b"\x11" * 32 + struct.pack("<II", 3, 84)
    for position, color in zip(POSITIONS, COLORS):
        body += struct.pack("<3f", *position) + struct.pack("<3f", 0, 0, 1) + bytes(color)
        body += struct.pack("<I", 2) + struct.pack("<2f", position[0], position[1])
        body += b"\0" * 16 + struct.pack("<3f", 1, 0, 0) + b"\0" * 16
    body += struct.pack("<I", 3) + struct.pack("<3I", 0, 1, 2)
    return obfuscate(body)


def csgmdl_v5() -> bytes:
    magic = obfuscate(b"CSGMDL")[:6] + bytes((0x35, 0x04, 0x34, 0x69))
    out = bytearray(magic)
    out += struct.pack("<H", 3) + b"".join(struct.pack("<3f", *p) for p in POSITIONS)
    quantised = struct.pack("<3H", 0x7FFF, 0x7FFF, 0xFFFE)  # (0, 0, 1)
    out += struct.pack("<HI", 3, 18) + quantised * 3
    out += struct.pack("<H", 3) + b"".join(bytes(c) for c in COLORS)
    out += struct.pack("<H", 3) + bytes((2, 2, 2))
    out += struct.pack("<H", 3) + b"".join(struct.pack("<2f", p[0], p[1]) for p in POSITIONS)
    out += struct.pack("<HI", 0, 0)
    deltas = bytes((0, 1, 1))  # indices 0, 1, 2
    out += struct.pack("<II", 3, len(deltas)) + deltas + bytes((2,)) + struct.pack("<2I", 0, 3)
    return bytes(out)


def unions_checks() -> None:
    from rhr import unions

    for label, blob in (("v2", csgmdl_v2()), ("v5", csgmdl_v5())):
        try:
            mesh = unions.decode(blob)
        except unions.UnionFormatError as exc:
            check(f"CSGMDL {label} decodes", False, str(exc))
            continue
        check(f"CSGMDL {label} decodes positions", mesh["positions"] == [c for p in POSITIONS for c in p],
              repr(mesh["positions"]))
        check(f"CSGMDL {label} decodes per-vertex colours", mesh["colors"] == [c for rgba in COLORS for c in rgba])
        check(f"CSGMDL {label} decodes the triangle", mesh["indices"] == [0, 1, 2], repr(mesh["indices"]))
        normal = mesh["normals"][:3]
        check(f"CSGMDL {label} normals", [round(v, 3) for v in normal] == [0, 0, 1], repr(normal))
        payload = unions.to_payload(mesh)
        floats = struct.unpack("<9f", base64.b64decode(payload["positions"]))
        check(f"CSGMDL {label} packs for the page", list(floats) == mesh["positions"])
    try:
        unions.decode(b"CSGK" + b"\0" * 40)
        check("a CSGK reference is refused, not guessed", False)
    except unions.UnionFormatError:
        check("a CSGK reference is refused, not guessed", True)


def zstd_checks() -> None:
    import zstandard

    from rhr.rbxl_raw import extract_string_property
    from test_rbxl_raw import lp

    def zchunk(name: bytes, payload: bytes) -> bytes:
        body = zstandard.ZstdCompressor().compress(payload)
        return name + struct.pack("<II", len(body), len(payload)) + b"\0" * 4 + body

    inst = struct.pack("<I", 3) + lp(b"PartOperationAsset") + b"\0" + struct.pack("<I", 1) + b"\0" * 4
    prop = struct.pack("<I", 3) + lp(b"MeshData") + b"\x01" + lp(b"mesh-bytes")
    header = b"<roblox!" + b"\x89\xff\r\n\x1a\n" + struct.pack("<HII", 0, 1, 1) + b"\0" * 8
    end = b"END\0" + struct.pack("<II", 0, 9) + b"\0" * 4 + b"</roblox>"
    data = header + zchunk(b"INST", inst) + zchunk(b"PROP", prop) + end
    values = extract_string_property(data, "PartOperationAsset", "MeshData")
    check("ZSTD chunks and in-memory files are read", values == [b"mesh-bytes"], repr(values))


def material_checks() -> None:
    from rhr import fetch

    table = json.loads(fetch.MATERIAL_TABLE.read_text(encoding="utf-8"))
    brick = table["parts"].get("Brick", {})
    check("the table has Brick's colour, normal and roughness maps",
          all(brick.get(k, "").isdigit() for k in ("color", "normal", "roughness")), repr(brick))
    check("metals have a metalness map", table["parts"].get("Metal", {}).get("metalness", "").isdigit())
    check("Plastic has no texture maps", table["parts"].get("Plastic") == {})
    grass = table["terrain"].get("Grass", {})
    check("terrain Grass has its own top and side textures",
          {"top", "side"} <= set(grass) and grass["top"]["color"] != grass["side"]["color"], repr(sorted(grass)))
    check("pre-2022 sets are there", len(table["partsLegacy"]) >= 15 and len(table["terrainLegacy"]) >= 15)

    part = lambda material: {"className": "Part", "props": {"Material": {"name": material}}}  # noqa: E731
    model = {"roots": [part("Brick"), part("Plastic")]}
    place_old = {"roots": [{"className": "Workspace", "children": [part("Brick")]}, {"className": "Lighting"}]}
    place_new = {"roots": [*place_old["roots"],
                           {"className": "MaterialService", "props": {"Use2022MaterialsXml": True}}]}
    check("a model file uses the current material set", fetch.uses_2022_materials(model))
    check("a place that never turned it on keeps the pre-2022 set", not fetch.uses_2022_materials(place_old))
    check("Use2022Materials turns the current set on", fetch.uses_2022_materials(place_new))
    maps = fetch.material_maps(model)
    check("only the materials a file uses are asked for", set(maps) == {"Brick"}, repr(sorted(maps)))
    legacy = fetch.material_maps(place_old)["Brick"]
    check("a pre-2022 place asks for the pre-2022 Brick", legacy == table["partsLegacy"]["Brick"])

    union = {"className": "UnionOperation", "props": {"AssetId": "https://www.roblox.com//asset/?id=12345"}}
    refs = fetch.collect_scene_refs({"roots": [union, part("Wood")]})
    check("a union's asset id is collected", refs["unions"] == {"12345"}, repr(refs["unions"]))
    check("material maps are collected", table["parts"]["Wood"]["color"] in refs["materials"])

    results = fetch.ensure({"meshes": {"999999999999"}, "materials": {"999999999998"}})
    check("offline, nothing is fetched and the result says so",
          results["meshes"]["999999999999"] == "missing (offline)"
          and results["materials"]["999999999998"] == "missing (offline)", repr(results))


def main() -> int:
    unions_checks()
    zstd_checks()
    material_checks()
    print("roblox assets: ok" if not failures else f"roblox assets: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
