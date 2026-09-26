#!/usr/bin/env python3
"""Characters: clothing painted onto R6 and R15 bodies, the Head mesh, faces on meshes.

Roblox's own body meshes and clothing layouts come from the Studio install, which tests
never use (RHR_STUDIO_DIR=0). This test points RHR at a stand-in install holding tiny
synthetic versions of those files, with the same names and conventions:

- a clothing layout is a flat mesh whose positions are pixels of the body texture
  (R6: 1024x512, R15 torso: 388x272) and whose UVs point into the clothing template;
- a body mesh samples that texture with its own UVs.

Here every layout maps the whole template onto the whole texture and the body meshes
are unit boxes whose UVs span the whole texture, so a solid red Shirt template must
turn a blue torso red, while the same rig without the Shirt stays blue.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
SHIRT_ID = "7100000001"
BODY_MESH_ID = "7100000002"


def mesh_v2(vertices: list[tuple], faces: list[tuple]) -> bytes:
    """A Roblox mesh, version 2.00: 36-byte vertices (position, normal, UV + w)."""
    out = bytearray(b"version 2.00\n")
    out += struct.pack("<HBBII", 12, 36, 12, len(vertices), len(faces))
    for (x, y, z), (nx, ny, nz), (u, v) in vertices:
        out += struct.pack("<9f", x, y, z, nx, ny, nz, u, v, 0.0)
    for face in faces:
        out += struct.pack("<3I", *face)
    return bytes(out)


def unit_box() -> bytes:
    """A 1x1x1 box; each face's UVs span the whole texture (V from the top, as Roblox)."""
    vertices, faces = [], []
    for axis in range(3):
        for sign in (1, -1):
            normal = [0.0, 0.0, 0.0]
            normal[axis] = sign
            a, b = [i for i in range(3) if i != axis]
            base = len(vertices)
            for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                position = [0.0, 0.0, 0.0]
                position[axis] = 0.5 * sign
                position[a] = du - 0.5
                position[b] = dv - 0.5
                vertices.append((tuple(position), tuple(normal), (du, 1 - dv)))
            quad = [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            # Counter-clockwise seen from outside.
            flip = (sign > 0) != ((b - a) % 3 == 1)
            faces += [(i, k, j) for i, j, k in quad] if flip else quad
    return mesh_v2(vertices, faces)


def layout(width: int, height: int) -> bytes:
    """A layout covering the whole texture with the whole template."""
    vertices = [
        ((0, 0, 0), (0, 0, 1), (0, 1)),
        ((width, 0, 0), (0, 0, 1), (1, 1)),
        ((width, height, 0), (0, 0, 1), (1, 0)),
        ((0, height, 0), (0, 0, 1), (0, 0)),
    ]
    return mesh_v2(vertices, [(0, 1, 2), (0, 2, 3)])


def fake_install(root: Path) -> None:
    (root / "PlatformContent" / "pc" / "textures").mkdir(parents=True)
    content = root / "content"
    avatar = content / "avatar"
    for name in ("torso", "leftarm", "rightarm", "leftleg", "rightleg"):
        (avatar / "meshes").mkdir(parents=True, exist_ok=True)
        (avatar / "meshes" / f"{name}.mesh").write_bytes(unit_box())
    (avatar / "heads").mkdir(parents=True)
    (avatar / "heads" / "head.mesh").write_bytes(unit_box())
    (avatar / "compositing").mkdir(parents=True)
    for name in ("CompositShirtTemplate", "CompositPantsTemplate", "CompositTShirt"):
        (avatar / "compositing" / f"{name}.mesh").write_bytes(layout(1024, 512))
    (avatar / "compositing" / "R15CompositTorsoBase.mesh").write_bytes(layout(388, 272))
    for name in ("R15CompositLeftArmBase", "R15CompositRightArmBase"):
        (avatar / "compositing" / f"{name}.mesh").write_bytes(layout(264, 284))
    (content / "textures").mkdir(parents=True)
    # Like Roblox's face: transparent but for the features (here a dark centre).
    face = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    face.paste((0, 0, 0, 255), (5, 5, 11, 11))
    face.save(content / "textures" / "face.png")


def cframe(x: float, y: float, z: float = 0) -> dict:
    return {"_t": "CFrame", "X": x, "Y": y, "Z": z, "R00": 1, "R01": 0, "R02": 0,
            "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}


def color(r: float, g: float, b: float) -> dict:
    return {"_t": "Color3", "R": r, "G": g, "B": b}


def enum(name: str) -> dict:
    return {"_t": "EnumItem", "name": name, "value": 0}


def part(name: str, x: float, y: float, size: tuple, rgb: tuple, children=(), cls="Part", **props) -> dict:
    return {
        "className": cls, "name": name, "children": list(children),
        "props": {
            "CFrame": cframe(x, y), "Size": {"_t": "Vector3", "X": size[0], "Y": size[1], "Z": size[2]},
            "Color": color(*rgb), "Transparency": 0, "Material": enum("SmoothPlastic"), **props,
        },
    }


BLUE = (0.05, 0.4, 0.8)
YELLOW = (0.95, 0.8, 0.2)


def r6(name: str, x: float, shirt: bool) -> dict:
    face = {"className": "Decal", "name": "face", "children": [],
            "props": {"Texture": "rbxasset://textures/face.png", "Face": enum("Front")}}
    head_mesh = {"className": "SpecialMesh", "name": "Mesh", "children": [],
                 "props": {"MeshType": enum("Head"), "Scale": {"_t": "Vector3", "X": 1.25, "Y": 1.25, "Z": 1.25}}}
    children = [
        {"className": "Humanoid", "name": "Humanoid", "children": [], "props": {"RigType": enum("R6")}},
        part("Torso", x, 3, (2, 2, 1), BLUE),
        part("Head", x, 4.5, (2, 1, 1), YELLOW, [head_mesh, face]),
    ]
    if shirt:
        children.append({"className": "Shirt", "name": "Shirt", "children": [],
                         "props": {"ShirtTemplate": f"rbxassetid://{SHIRT_ID}"}})
    return {"className": "Model", "name": name, "props": {}, "children": children}


def r15(name: str, x: float) -> dict:
    return {"className": "Model", "name": name, "props": {}, "children": [
        {"className": "Humanoid", "name": "Humanoid", "children": [], "props": {"RigType": enum("R15")}},
        part("UpperTorso", x, 3, (2, 2, 1), BLUE, cls="MeshPart", MeshId=f"rbxassetid://{BODY_MESH_ID}"),
        {"className": "Shirt", "name": "Shirt", "children": [],
         "props": {"ShirtTemplate": f"rbxassetid://{SHIRT_ID}"}},
    ]}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-character-") as directory:
        tmp = Path(directory)
        install = tmp / "studio"
        fake_install(install)
        textures = tmp / "textures"
        textures.mkdir()
        Image.new("RGBA", (585, 559), (220, 20, 20, 255)).save(textures / f"{SHIRT_ID}.png")
        meshes = tmp / "meshes"
        meshes.mkdir()
        (meshes / f"{BODY_MESH_ID}.mesh").write_bytes(unit_box())
        ir = {"sourcePath": "characters", "roots": [{
            "className": "Workspace", "name": "Workspace", "props": {},
            "children": [r6("Dressed", -3, True), r6("Plain", 0, False), r15("Modern", 3)],
        }]}
        source = tmp / "characters.json"
        source.write_text(json.dumps(ir))
        out = tmp / "characters.png"
        env = dict(os.environ, RHR_STUDIO_DIR=str(install))
        proc = subprocess.run(
            [*RHR, "scene", str(source), "--viewport", "480x240", "--no-shadows",
             "--camera", "0,3.6,-12", "--look-at", "0,3.6,0", "--fov", "50",
             "--texture-dir", str(textures), "--mesh-dir", str(meshes), "--out", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=180, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        with Image.open(out) as image:
            image = image.convert("RGB")
            width, height = image.size

            def at(world_x: float, world_y: float) -> tuple[int, int, int]:
                # Looking along +Z from z=-12: world +X is on the image's left.
                scale = height / 2 / (12 * 0.46631)  # tan(25 deg)
                return image.getpixel((round(width / 2 - world_x * scale), round(height / 2 - (world_y - 3.6) * scale)))

            dressed, plain, modern = at(-3, 3), at(0, 3), at(3, 3)
            head_edge, face = at(0, 4.9), at(0, 4.5)
        # The Shirt paints the torso red over its blue body colour; without one it stays blue.
        assert dressed[0] > 70 and dressed[0] > 3 * max(dressed[1], dressed[2]), dressed
        assert plain[2] > plain[0] + 40, plain
        # R15: the same template through the torso's own layout, on the MeshPart's UVs.
        assert modern[0] > 70 and modern[0] > 3 * max(modern[1], modern[2]), modern
        # The Head mesh is drawn (yellow above the face), and the face decal lies on it.
        assert min(head_edge[0], head_edge[1]) > 2 * head_edge[2] + 20, head_edge
        assert sum(face) < 150, face

    print(f"scene character: dressed={dressed} plain={plain} r15={modern} face={face}")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
