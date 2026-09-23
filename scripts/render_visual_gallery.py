#!/usr/bin/env python3
"""Render a representative RHR 3D visual-quality gallery and contact sheet."""

from __future__ import annotations

import sys
import json
import struct
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
OUT = ROOT / "out" / "visual-gallery"
ASSETS = ROOT / "tests" / "fixtures" / "assets"
GALLERY_MESH_ID = "900000002"


def vec3(x: float, y: float, z: float) -> dict:
    return {"_t": "Vector3", "X": x, "Y": y, "Z": z}


def color(r: float, g: float, b: float) -> dict:
    return {"_t": "Color3", "R": r, "G": g, "B": b}


def enum(name: str, enum_name: str = "Enum.Material") -> dict:
    return {"_t": "EnumItem", "enum": enum_name, "name": name, "value": 0}


def cframe(x: float, y: float, z: float) -> dict:
    return {
        "_t": "CFrame",
        "X": x, "Y": y, "Z": z,
        "R00": 1, "R01": 0, "R02": 0,
        "R10": 0, "R11": 1, "R12": 0,
        "R20": 0, "R21": 0, "R22": 1,
    }


def node(class_name: str, name: str, props: dict | None = None, children: list[dict] | None = None) -> dict:
    return {
        "className": class_name,
        "name": name,
        "props": props or {},
        "children": children or [],
    }


def part(
    name: str,
    position: tuple[float, float, float],
    size: tuple[float, float, float],
    rgb: tuple[float, float, float],
    material: str = "Plastic",
    *,
    transparency: float = 0,
    reflectance: float = 0,
    shape: str = "Block",
    children: list[dict] | None = None,
    class_name: str = "Part",
) -> dict:
    return node(
        class_name,
        name,
        {
            "CFrame": cframe(*position),
            "Size": vec3(*size),
            "Color": color(*rgb),
            "Transparency": transparency,
            "Reflectance": reflectance,
            "CastShadow": True,
            "Material": enum(material),
            "Shape": enum(shape, "Enum.PartType"),
        },
        children,
    )


def attachment(name: str, position: tuple[float, float, float]) -> dict:
    return node("Attachment", name, {"Position": vec3(*position)})


def gallery_mesh_bytes() -> bytes:
    """Small asymmetric Roblox v2 mesh used by the visual gate.

    Keeping this hermetic means visual-quality validation never depends on
    Roblox asset delivery or a warmed cache.
    """
    vertices = [
        (-1.0, -1.0, -0.55),
        (1.0, -1.0, -0.55),
        (0.35, 1.0, -0.55),
        (-0.55, 0.20, 1.45),
        (0.75, -0.15, 0.95),
    ]
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (2, 3, 4),
        (2, 4, 1),
        (1, 4, 0),
        (0, 4, 3),
    ]

    def record(position: tuple[float, float, float]) -> bytes:
        return struct.pack(
            "<8f4b4B",
            position[0], position[1], position[2],
            0.0, 0.0, 1.0,
            0.0, 0.0,
            0, 0, 0, 0,
            255, 255, 255, 255,
        )

    header = struct.pack("<HBBII", 12, 40, 12, len(vertices), len(faces))
    payload = b"".join(record(position) for position in vertices)
    payload += b"".join(struct.pack("<III", *face) for face in faces)
    return b"version 2.00\n" + header + payload


def gallery_ir() -> dict:
    decal = node(
        "Decal",
        "WallArt",
        {
            "Texture": "rbxassetid://900000001",
            "Face": enum("Front", "Enum.NormalId"),
            "Color3": color(1, 1, 1),
            "Transparency": 0,
        },
    )

    lamp = node(
        "PointLight",
        "WarmLamp",
        {
            "Color": color(1.0, 0.58, 0.30),
            "Brightness": 3.5,
            "Range": 16,
            "Shadows": True,
        },
    )

    spotlight = node(
        "SpotLight",
        "CoolSpot",
        {
            "Color": color(0.35, 0.55, 1.0),
            "Brightness": 4.0,
            "Range": 20,
            "Angle": 65,
            "Face": enum("Front", "Enum.NormalId"),
            "Shadows": True,
        },
    )

    beam = node(
        "Beam",
        "GalleryBeam",
        {
            "Attachment0": "Workspace.BeamLeft.A0",
            "Attachment1": "Workspace.BeamRight.A1",
            "Width0": 0.20,
            "Width1": 0.20,
            "CurveSize0": 0,
            "CurveSize1": 0,
            "Segments": 10,
            "Enabled": True,
            "Brightness": 1.5,
            "Color": {
                "_t": "ColorSequence",
                "keypoints": [
                    {"Time": 0, "Value": color(0.1, 0.9, 1.0)},
                    {"Time": 1, "Value": color(0.1, 0.9, 1.0)},
                ],
            },
            "Transparency": {
                "_t": "NumberSequence",
                "keypoints": [
                    {"Time": 0, "Value": 0.05, "Envelope": 0},
                    {"Time": 1, "Value": 0.05, "Envelope": 0},
                ],
            },
        },
    )

    label = node(
        "BillboardGui",
        "Marker",
        {
            "Enabled": True,
            "Size": {"_t": "UDim2", "XS": 0, "XO": 130, "YS": 0, "YO": 34},
            "StudsOffset": vec3(0, 2.3, 0),
            "AlwaysOnTop": True,
        },
        [
            node(
                "TextLabel",
                "Caption",
                {
                    "Position": {"_t": "UDim2", "XS": 0, "XO": 0, "YS": 0, "YO": 0},
                    "Size": {"_t": "UDim2", "XS": 1, "XO": 0, "YS": 1, "YO": 0},
                    "BackgroundTransparency": 0.2,
                    "BackgroundColor3": color(0.03, 0.04, 0.06),
                    "Text": "MATERIAL GALLERY",
                    "TextColor3": color(1, 1, 1),
                    "TextSize": 15,
                    "TextTransparency": 0,
                    "Visible": True,
                    "ZIndex": 1,
                    "BorderSizePixel": 0,
                },
            )
        ],
    )

    special_sphere = node(
        "SpecialMesh",
        "SphereMesh",
        {
            "MeshType": enum("Sphere", "Enum.MeshType"),
            "Scale": vec3(1, 1, 1),
            "Offset": vec3(0, 0, 0),
        },
    )

    children = [
        # Room shell
        part("Floor", (0, -0.5, 0), (24, 1, 18), (0.34, 0.36, 0.39), "Concrete"),
        part("BackWall", (0, 4, 8.5), (24, 9, 1), (0.72, 0.68, 0.61), "Brick"),
        part("LeftWall", (-11.5, 4, 0), (1, 9, 16), (0.52, 0.54, 0.58), "Concrete"),
        part("RightWall", (11.5, 4, 0), (1, 9, 16), (0.52, 0.54, 0.58), "Concrete"),
        # Material plinths
        part("Wood", (-7.5, 1, 2.5), (3, 3, 3), (0.52, 0.27, 0.11), "WoodPlanks"),
        part("Metal", (-3.75, 1, 2.5), (3, 3, 3), (0.48, 0.50, 0.54), "Metal", reflectance=0.18),
        part("Neon", (0, 1, 2.5), (3, 3, 3), (0.15, 0.95, 0.85), "Neon"),
        part("Glass", (3.75, 1, 2.5), (3, 3, 3), (0.42, 0.72, 0.95), "Glass", transparency=0.28),
        part("Marble", (7.5, 1, 2.5), (3, 3, 3), (0.83, 0.78, 0.72), "Marble"),
        # Geometry variation
        part("Ramp", (-7.2, 1.0, -3.1), (5, 2.2, 5), (0.85, 0.48, 0.12), "Plastic", class_name="WedgePart"),
        part("Cylinder", (-1.8, 1.4, -3.4), (2.5, 3.8, 2.5), (0.70, 0.12, 0.13), "Metal", shape="Cylinder"),
        part("Sphere", (2.2, 1.4, -3.3), (3, 3, 3), (0.64, 0.20, 0.83), "SmoothPlastic", children=[special_sphere]),
        part(
            "CachedMesh",
            (7.0, 1.5, -3.2),
            (4.2, 3.2, 3.8),
            (0.18, 0.72, 0.34),
            "SmoothPlastic",
            class_name="MeshPart",
        ),
        # Sign/decal and local lighting
        part("Sign", (0, 4.7, 7.9), (8, 4, 0.3), (0.88, 0.88, 0.88), "SmoothPlastic", children=[decal]),
        part("Lamp", (7.5, 5.6, -4.7), (0.45, 0.45, 0.45), (1, 0.45, 0.15), "Neon", transparency=0.05, children=[lamp]),
        part("SpotAnchor", (-7.5, 5.8, -5.4), (0.4, 0.4, 0.4), (0.22, 0.35, 1), "Neon", transparency=0.05, children=[spotlight]),
        # Beam endpoints
        part("BeamLeft", (-7.8, 4.2, 0), (0.18, 0.18, 0.18), (0, 0, 0), transparency=1, children=[attachment("A0", (0, 0, 0)), beam]),
        part("BeamRight", (7.8, 4.2, 0), (0.18, 0.18, 0.18), (0, 0, 0), transparency=1, children=[attachment("A1", (0, 0, 0))]),
        # Billboard anchor
        part("LabelAnchor", (0, 3.2, 1.0), (0.2, 0.2, 0.2), (0, 0, 0), transparency=1, children=[label]),
    ]

    gallery = {
        "sourcePath": "visual-gallery",
        "roots": [
            node(
                "Lighting",
                "Lighting",
                {
                    "Ambient": color(0.16, 0.17, 0.20),
                    "OutdoorAmbient": color(0.22, 0.24, 0.30),
                    "Brightness": 2.0,
                    "GlobalShadows": True,
                    "ClockTime": 16.0,
                    "GeographicLatitude": 35,
                    "ShadowSoftness": 0.4,
                },
            ),
            node("Workspace", "Workspace", {}, children),
            node(
                "ScreenGui",
                "VisualGateHUD",
                {"Enabled": True, "DisplayOrder": 10},
                [
                    node(
                        "TextLabel",
                        "Title",
                        {
                            "Position": {"_t": "UDim2", "XS": 0, "XO": 16, "YS": 0, "YO": 16},
                            "Size": {"_t": "UDim2", "XS": 0, "XO": 230, "YS": 0, "YO": 40},
                            "BackgroundColor3": color(0.03, 0.04, 0.06),
                            "BackgroundTransparency": 0.12,
                            "BorderSizePixel": 0,
                            "Text": "RHR 3D VISUAL GATE",
                            "TextColor3": color(0.96, 0.98, 1.0),
                            "TextSize": 18,
                            "TextTransparency": 0,
                            "Visible": True,
                            "ZIndex": 2,
                        },
                    )
                ],
            ),
        ],
    }
    cached_mesh = next(
        child for child in gallery["roots"][1]["children"] if child["name"] == "CachedMesh"
    )
    cached_mesh["props"]["MeshId"] = f"rbxassetid://{GALLERY_MESH_ID}"
    return gallery


def render(args: list[str], out: Path) -> None:
    command = [*RHR, *args, "--out", str(out)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ir = OUT / "gallery.json"
    ir.write_text(json.dumps(gallery_ir(), separators=(",", ":")))
    mesh_dir = OUT / "meshes"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    (mesh_dir / f"{GALLERY_MESH_ID}.mesh").write_bytes(gallery_mesh_bytes())

    common = [
        "preview", str(ir),
        "--viewport", "640x400",
        "--texture-dir", str(ASSETS),
        "--mesh-dir", str(mesh_dir),
        "--shadows",
        "--topbar-height", "0",
        "--fov", "48",
    ]
    views = [
        ("front", ["--camera", "0,7,-27", "--look-at", "0,2.8,1.2"]),
        ("iso", ["--camera", "20,14,-22", "--look-at", "0,2.6,1.2"]),
        ("top", ["--camera", "0,28,-1", "--look-at", "0,0.5,1.0"]),
        ("close", ["--camera", "12,8,-15", "--look-at", "0,2.5,2.0"]),
    ]

    rendered: list[tuple[str, Path]] = []
    for name, camera in views:
        output = OUT / f"{name}.png"
        render([*common, *camera], output)
        rendered.append((name, output))

    # One no-shadow control for a direct lighting/shadow comparison.
    no_shadow = OUT / "front-no-shadows.png"
    no_shadow_args = [arg for arg in common if arg != "--shadows"]
    render([*no_shadow_args, *views[0][1]], no_shadow)

    cell_w, cell_h = 640, 430
    sheet = Image.new("RGB", (cell_w * 2, cell_h * 2), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (name, path) in enumerate(rendered):
        with Image.open(path).convert("RGB") as image:
            x = (index % 2) * cell_w
            y = (index // 2) * cell_h
            sheet.paste(image, (x, y + 30))
            draw.text((x + 10, y + 8), name.upper(), fill=(235, 238, 244))
    contact = OUT / "contact-sheet.png"
    sheet.save(contact)
    preview = sheet.resize((640, 430), Image.Resampling.LANCZOS)
    preview_path = OUT / "contact-sheet-preview.jpg"
    preview.save(preview_path, quality=68, optimize=True)
    contact_thumb = sheet.resize((320, 215), Image.Resampling.LANCZOS)
    contact_thumb.save(OUT / "contact-sheet-thumb.jpg", quality=58, optimize=True)
    with Image.open(OUT / "front.png").convert("RGB") as front_image:
        front_preview = front_image.resize((320, 200), Image.Resampling.LANCZOS)
        front_preview.save(OUT / "front-preview.jpg", quality=60, optimize=True)
    print(contact)
    print(preview_path)


if __name__ == "__main__":
    main()
