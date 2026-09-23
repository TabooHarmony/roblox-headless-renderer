#!/usr/bin/env python3
"""Mesh cache discovery stays separate from network fetching."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_meshes import asset_id, mesh_refs  # noqa: E402


def main() -> None:
    data = {
        "roots": [{
            "className": "Model",
            "name": "Root",
            "props": {},
            "children": [
                {
                    "className": "MeshPart",
                    "name": "Body",
                    "props": {"MeshId": "https://assetdelivery.roblox.com/v1/asset/?id=12345"},
                    "children": [],
                },
                {
                    "className": "Part",
                    "name": "Handle",
                    "props": {},
                    "children": [{
                        "className": "SpecialMesh",
                        "name": "Mesh",
                        "props": {
                            "MeshType": {"_t": "EnumItem", "name": "FileMesh", "value": 5},
                            "MeshId": "rbxassetid://67890",
                        },
                        "children": [],
                    }],
                },
                {
                    "className": "SpecialMesh",
                    "name": "BuiltIn",
                    "props": {
                        "MeshType": {"_t": "EnumItem", "name": "Sphere", "value": 3},
                        "MeshId": "rbxassetid://99999",
                    },
                    "children": [],
                },
            ],
        }],
    }

    assert asset_id("http://www.roblox.com/asset/?id=42") == "42"
    assert asset_id("rbxassetid://73") == "73"
    assert asset_id("") is None
    assert mesh_refs(data) == {"12345", "67890"}
    print("mesh assets: MeshPart/FileMesh IDs discovered; built-in mesh ignored")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
