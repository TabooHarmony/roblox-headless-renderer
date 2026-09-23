#!/usr/bin/env python3
"""Narrow raw Roblox property extraction for hidden Terrain data."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rhr.rbxl_raw import (  # noqa: E402
    EMPTY_TERRAIN_SMOOTH_GRID,
    BinaryRbxError,
    extract_serialized_string_property,
    extract_string_property,
)
from rhr.scene_dump import build_scene_dump  # noqa: E402


def lp(value: bytes) -> bytes:
    return struct.pack("<I", len(value)) + value


def literal_lz4(payload: bytes) -> bytes:
    """Valid final-literal-only LZ4 block for hermetic chunk tests."""
    if len(payload) < 15:
        return bytes([len(payload) << 4]) + payload
    remaining = len(payload) - 15
    extensions = bytearray()
    while remaining >= 255:
        extensions.append(255)
        remaining -= 255
    extensions.append(remaining)
    return b"\xf0" + bytes(extensions) + payload


def chunk(name: bytes, payload: bytes, *, compressed: bool) -> bytes:
    if compressed:
        body = literal_lz4(payload)
        return name + struct.pack("<II", len(body), len(payload)) + b"\0" * 4 + body
    return name + struct.pack("<II", 0, len(payload)) + b"\0" * 4 + payload


def fake_binary(smooth_grid: bytes) -> bytes:
    inst = (
        struct.pack("<I", 7)
        + lp(b"Terrain")
        + b"\0"
        + struct.pack("<I", 1)
        + b"\0" * 4
    )
    prop = (
        struct.pack("<I", 7)
        + lp(b"SmoothGrid")
        + b"\x01"
        + lp(smooth_grid)
    )
    end = b"</roblox>"
    header = (
        b"<roblox!"
        + b"\x89\xff\r\n\x1a\n"
        + struct.pack("<HII", 0, 1, 1)
        + b"\0" * 8
    )
    return (
        header
        + chunk(b"INST", inst, compressed=True)
        + chunk(b"PROP", prop, compressed=True)
        + chunk(b"END\0", end, compressed=False)
    )


def terrain_ir(source: Path) -> dict:
    return {
        "sourcePath": str(source),
        "roots": [
            {
                "className": "Workspace",
                "name": "Workspace",
                "props": {},
                "children": [
                    {
                        "className": "Terrain",
                        "name": "Terrain",
                        "props": {
                            "Size": {"_t": "Vector3", "X": 2044, "Y": 252, "Z": 2044},
                        },
                        "children": [],
                    }
                ],
            }
        ],
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-rbxl-raw-") as directory:
        tmp = Path(directory)

        binary = tmp / "terrain.rbxl"
        binary.write_bytes(fake_binary(EMPTY_TERRAIN_SMOOTH_GRID))
        values = extract_string_property(binary, "Terrain", "SmoothGrid")
        assert values == [EMPTY_TERRAIN_SMOOTH_GRID], values
        assert extract_serialized_string_property(binary, "Terrain", "SmoothGrid") == values

        xml = tmp / "terrain.rbxmx"
        xml.write_text(
            '<roblox version="4"><Item class="Terrain" referent="R">'
            '<Properties><BinaryString name="SmoothGrid"><![CDATA[AQU=]]></BinaryString>'
            '</Properties></Item></roblox>'
        )
        assert extract_serialized_string_property(xml, "Terrain", "SmoothGrid") == [
            EMPTY_TERRAIN_SMOOTH_GRID
        ]

        ir = tmp / "empty.json"
        ir.write_text(json.dumps(terrain_ir(binary)))
        dump = build_scene_dump(ir)
        assert dump["terrain"] == [{
            "path": "Workspace/Terrain",
            "rawAvailable": True,
            "smoothGridBytes": 2,
            "empty": True,
        }]
        assert "Terrain" not in dump["unsupportedVisualClasses"]

        nonempty_binary = tmp / "nonempty.rbxl"
        nonempty_binary.write_bytes(fake_binary(b"\x01\x05\x99"))
        nonempty_ir = tmp / "nonempty.json"
        nonempty_ir.write_text(json.dumps(terrain_ir(nonempty_binary)))
        nonempty_dump = build_scene_dump(nonempty_ir)
        assert nonempty_dump["terrain"][0]["empty"] is False
        assert nonempty_dump["unsupportedVisualClasses"]["Terrain"] == 1

        unknown_ir = tmp / "unknown.json"
        unknown_data = terrain_ir(tmp / "missing.rbxl")
        unknown_ir.write_text(json.dumps(unknown_data))
        unknown_dump = build_scene_dump(unknown_ir)
        assert unknown_dump["terrain"][0]["rawAvailable"] is False
        assert unknown_dump["terrain"][0]["empty"] is None
        assert unknown_dump["unsupportedVisualClasses"]["Terrain"] == 1

        bad = tmp / "bad.rbxl"
        bad.write_bytes(b"not roblox")
        try:
            extract_string_property(bad, "Terrain", "SmoothGrid")
        except BinaryRbxError:
            pass
        else:
            raise AssertionError("invalid binary was accepted")

    print("rbxl raw: LZ4 PROP extraction + empty/nonempty Terrain diagnostics ok")


if __name__ == "__main__":
    main()
