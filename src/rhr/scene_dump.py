"""Machine-readable static 3D scene summary for agent iteration."""

from __future__ import annotations

from rhr.schema import stamp

import json
import math
import re
from pathlib import Path

from rhr.paths import ICON_CACHE, MESH_CACHE, UNION_CACHE

from rhr.ir import load_ir
from rhr.rbxl_raw import EMPTY_TERRAIN_SMOOTH_GRID, BinaryRbxError, extract_serialized_string_property

ASSET_EXTENSIONS = ("png", "webp", "jpg", "jpeg", "svg")
DEFAULT_MESH_DIR = MESH_CACHE

PART_CLASSES = {"Part", "WedgePart", "CornerWedgePart", "MeshPart", "UnionOperation"}
BOX_FALLBACK_CLASSES = {"MeshPart", "UnionOperation"}
SUPPORTED_MATERIALS = {
    "Plastic", "SmoothPlastic", "Neon", "Glass", "Metal", "CorrodedMetal",
    "DiamondPlate", "Foil", "Wood", "WoodPlanks", "Concrete", "Brick", "Slate",
    "Granite", "Marble", "Pebble", "Cobblestone", "Ice", "Fabric", "Grass",
    "LeafyGrass", "Ground", "Sand", "Snow", "Mud", "Rock", "Basalt",
    "CrackedLava", "Limestone", "Pavement", "Asphalt", "Salt", "Sandstone",
    "Glacier", "ForceField", "Cardboard", "Carpet", "CeramicTiles",
    "ClayRoofTiles", "Leather", "Plaster", "RoofShingles", "Rubber",
}


def _children(node: dict) -> list[dict]:
    children = node.get("children") or []
    if isinstance(children, dict):
        return list(children.values())
    return list(children)


def _enum_name(value, default=None):
    if isinstance(value, dict):
        return value.get("name", default)
    return value if value is not None else default


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _vec3(value: dict | None, default: float = 0.0) -> list[float]:
    value = value or {}
    return [
        _number(value.get("X"), default),
        _number(value.get("Y"), default),
        _number(value.get("Z"), default),
    ]


def _color3(value: dict | None, default: float = 0.5) -> list[float]:
    value = value or {}
    return [
        _number(value.get("R"), default),
        _number(value.get("G"), default),
        _number(value.get("B"), default),
    ]


def _asset_id(uri) -> str | None:
    text = str(uri or "")
    for pattern in (r"rbxassetid://(\d+)", r"[?&]id=(\d+)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    matches = re.findall(r"(\d+)", text)
    return matches[-1] if matches else None


def _mesh_available(asset_id: str | None, mesh_dir: Path | None) -> bool:
    if not asset_id:
        return False
    roots = []
    if mesh_dir is not None:
        roots.append(mesh_dir)
    roots.append(DEFAULT_MESH_DIR)
    return any((root / f"{asset_id}.mesh").is_file() for root in roots)


def _union_available(asset_id: str | None) -> bool:
    return bool(asset_id) and (UNION_CACHE / f"{asset_id}.json").is_file()


def _asset_available(asset_id: str | None, texture_dir: Path | None) -> bool:
    if not asset_id:
        return False
    roots = []
    if texture_dir is not None:
        roots.append(texture_dir)
    roots.append(ICON_CACHE)
    return any((root / f"{asset_id}.{extension}").is_file() for root in roots for extension in ASSET_EXTENSIONS)


def _orientation(cf: dict) -> list[float]:
    """Roblox `Orientation` in degrees (CFrame:ToOrientation: R = Ry * Rx * Rz)."""
    r = [[_number(cf.get(f"R{row}{col}"), 1.0 if row == col else 0.0) for col in range(3)] for row in range(3)]
    x = math.asin(max(-1.0, min(1.0, -r[1][2])))
    if abs(r[1][2]) < 0.999999:
        y = math.atan2(r[0][2], r[2][2])
        z = math.atan2(r[1][0], r[1][1])
    else:  # gimbal lock: fold Z into Y
        y = math.atan2(-r[2][0], r[0][0])
        z = 0.0
    return [round(math.degrees(value) + 0.0, 4) for value in (x, y, z)]


def _part_aabb(props: dict) -> tuple[list[float], list[float]] | None:
    cf = props.get("CFrame")
    size = props.get("Size")
    if not isinstance(cf, dict) or not isinstance(size, dict):
        return None

    position = [_number(cf.get(axis)) for axis in ("X", "Y", "Z")]
    sx, sy, sz = (_number(size.get(axis), 1.0) for axis in ("X", "Y", "Z"))
    half = [sx / 2, sy / 2, sz / 2]
    rotation = [
        [_number(cf.get("R00"), 1), _number(cf.get("R01")), _number(cf.get("R02"))],
        [_number(cf.get("R10")), _number(cf.get("R11"), 1), _number(cf.get("R12"))],
        [_number(cf.get("R20")), _number(cf.get("R21")), _number(cf.get("R22"), 1)],
    ]
    extents = [
        sum(abs(rotation[row][column]) * half[column] for column in range(3))
        for row in range(3)
    ]
    return (
        [round(position[i] - extents[i], 6) for i in range(3)],
        [round(position[i] + extents[i], 6) for i in range(3)],
    )


def build_scene_dump(
    ir_path: Path,
    texture_dir: Path | None = None,
    mesh_dir: Path | None = None,
) -> dict:
    data = load_ir(ir_path)
    path_by_id: dict[int, str] = {}
    path_by_full_name: dict[str, str | None] = {}

    def index_ids(node: dict, full_name: str) -> None:
        if "id" in node:
            path_by_id[node["id"]] = node["path"]
        # GetFullName() is dotted and not unique; a shared one resolves to None.
        path_by_full_name[full_name] = None if full_name in path_by_full_name else node["path"]
        for child in node.get("children") or []:
            index_ids(child, f"{full_name}.{child.get('name') or child.get('className')}")

    for root in data["roots"]:
        index_ids(root, root.get("name") or root.get("className"))

    def ref_path(node: dict, prop: str) -> str | None:
        """Unique path of a reference target: by id, else by an unambiguous full name."""
        target = (node.get("refs") or {}).get(prop)
        if target is not None:
            return path_by_id.get(target)
        full_name = (node.get("props") or {}).get(prop)
        return path_by_full_name.get(full_name) if isinstance(full_name, str) else None

    nodes: list[dict] = []
    cameras: list[dict] = []
    lights: list[dict] = []
    beams: list[dict] = []
    trails: list[dict] = []
    special_meshes: list[dict] = []
    lighting: dict | None = None
    atmosphere: dict | None = None
    sky: dict | None = None
    class_counts: dict[str, int] = {}
    experimental_materials = 0
    fallback_counts: dict[str, int] = {}
    material_fallback_counts: dict[str, int] = {}
    unsupported_counts: dict[str, int] = {}
    asset_references: list[dict] = []
    mesh_references: list[dict] = []
    overall_min = [math.inf, math.inf, math.inf]
    overall_max = [-math.inf, -math.inf, -math.inf]
    terrain_summaries: list[dict] = []
    parent_by_id: dict[int, dict] = {}
    terrain_payloads: list[bytes] = []
    source_path = data.get("sourcePath")
    if source_path:
        candidate = Path(source_path)
        if candidate.is_file():
            try:
                terrain_payloads = extract_serialized_string_property(
                    candidate, "Terrain", "SmoothGrid"
                )
            except (OSError, BinaryRbxError, UnicodeError):
                terrain_payloads = []
    terrain_index = 0

    def trail_history_source(node: dict) -> str | None:
        current = parent_by_id.get(id(node))
        while current is not None:
            if current.get("className") in PART_CLASSES:
                velocity = current.get("props", {}).get("AssemblyLinearVelocity") or {}
                if any(abs(_number(velocity.get(axis))) > 1e-6 for axis in ("X", "Y", "Z")):
                    return "AssemblyLinearVelocity"
                return None
            current = parent_by_id.get(id(current))
        return None

    def visit(
        node: dict,
        path: str,
        in_lighting: bool = False,
        parent: dict | None = None,
    ) -> None:
        if parent is not None:
            parent_by_id[id(node)] = parent
        nonlocal lighting, atmosphere, sky, terrain_index, experimental_materials
        class_name = node.get("className") or "Instance"
        props = node.get("props") or {}
        in_lighting = in_lighting or class_name == "Lighting"
        class_counts[class_name] = class_counts.get(class_name, 0) + 1

        # Model.Scale is not applied: saved parts already carry their scaled
        # CFrames and Sizes (ScaleTo rewrites them; Scale only records the factor).

        if class_name == "SpecialMesh":
            mesh_type = _enum_name(props.get("MeshType"), "FileMesh")
            mesh_id = _asset_id(props.get("MeshId")) if mesh_type == "FileMesh" else None
            mesh_cached = mesh_type == "FileMesh" and _mesh_available(mesh_id, mesh_dir)
            special_meshes.append({
                "path": path,
                "meshType": mesh_type,
                "meshId": props.get("MeshId"),
                "scale": _vec3(props.get("Scale"), 1.0),
                "offset": _vec3(props.get("Offset"), 0.0),
                "supported": mesh_type != "FileMesh" or mesh_cached,
            })
            if mesh_type == "FileMesh":
                mesh_references.append({
                    "path": path,
                    "class": class_name,
                    "property": "MeshId",
                    "uri": props.get("MeshId"),
                    "assetId": mesh_id,
                    "available": mesh_cached,
                })
                if not mesh_cached:
                    unsupported_counts["SpecialMesh:FileMesh"] = unsupported_counts.get("SpecialMesh:FileMesh", 0) + 1

        if class_name == "Beam":
            beams.append({
                "path": path,
                "attachment0": ref_path(node, "Attachment0"),
                "attachment1": ref_path(node, "Attachment1"),
                "width0": _number(props.get("Width0"), 0.2),
                "width1": _number(props.get("Width1"), 0.2),
                "curveSize0": _number(props.get("CurveSize0"), 0.0),
                "curveSize1": _number(props.get("CurveSize1"), 0.0),
                "segments": int(_number(props.get("Segments"), 10)),
                "enabled": props.get("Enabled", True),
            })

        if class_name == "Trail":
            history_source = trail_history_source(node)
            trails.append({
                "path": path,
                "attachment0": ref_path(node, "Attachment0"),
                "attachment1": ref_path(node, "Attachment1"),
                "lifetime": _number(props.get("Lifetime"), 2.0),
                "minLength": _number(props.get("MinLength"), 0.1),
                "maxLength": _number(props.get("MaxLength"), 0.0),
                "enabled": props.get("Enabled", True),
                "historySource": history_source,
                "supported": history_source is not None,
            })
            if history_source is None:
                unsupported_counts["Trail"] = unsupported_counts.get("Trail", 0) + 1

        if class_name in {"PointLight", "SpotLight", "SurfaceLight"}:
            lights.append({
                "path": path,
                "class": class_name,
                "color": _color3(props.get("Color"), 1.0),
                "brightness": _number(props.get("Brightness"), 1.0),
                "range": _number(props.get("Range"), 8.0),
                "shadows": props.get("Shadows", False),
                "angle": _number(props.get("Angle"), 90.0 if class_name == "SurfaceLight" else 45.0),
                "face": _enum_name(props.get("Face"), "Front"),
            })

        if class_name == "Terrain":
            payload = terrain_payloads[terrain_index] if terrain_index < len(terrain_payloads) else None
            terrain_index += 1
            empty = payload == EMPTY_TERRAIN_SMOOTH_GRID if payload is not None else None
            decodes = False
            if payload is not None and not empty:
                from rhr.terrain import TerrainFormatError, decode_smooth_grid

                try:
                    decodes = bool(decode_smooth_grid(payload))
                except TerrainFormatError:
                    decodes = False
            terrain_summaries.append({
                "path": path,
                "rawAvailable": payload is not None,
                "smoothGridBytes": len(payload) if payload is not None else None,
                "empty": empty,
                # Drawn as a smooth surface when its voxels decode.
                "drawn": "smooth" if decodes else None,
            })
            if empty is not True and not decodes:
                unsupported_counts["Terrain"] = unsupported_counts.get("Terrain", 0) + 1

        if class_name == "Sky" and (sky is None or in_lighting):
            face_properties = (
                "SkyboxBk", "SkyboxDn", "SkyboxFt",
                "SkyboxLf", "SkyboxRt", "SkyboxUp",
            )
            faces = {}
            for property_name in face_properties:
                uri = props.get(property_name)
                asset_id = _asset_id(uri)
                available = _asset_available(asset_id, texture_dir)
                faces[property_name] = {
                    "uri": uri,
                    "assetId": asset_id,
                    "available": available,
                }
                asset_references.append({
                    "path": path,
                    "class": class_name,
                    "property": property_name,
                    "uri": uri,
                    "assetId": asset_id,
                    "available": available,
                })
            sky = {
                "path": path,
                "faces": faces,
                "complete": all(face["available"] for face in faces.values()),
                "orientation": _vec3(props.get("SkyboxOrientation"), 0.0),
                "celestialBodiesShown": props.get("CelestialBodiesShown", True),
                "starCount": int(_number(props.get("StarCount"), 3000)),
                "sunAngularSize": _number(props.get("SunAngularSize"), 21.0),
                "moonAngularSize": _number(props.get("MoonAngularSize"), 11.0),
            }

        if class_name == "Atmosphere" and (atmosphere is None or in_lighting):
            atmosphere = {
                "path": path,
                "color": _color3(props.get("Color"), 1.0),
                "decay": _color3(props.get("Decay"), 1.0),
                "density": _number(props.get("Density"), 0.35),
                "haze": _number(props.get("Haze"), 0.0),
                "glare": _number(props.get("Glare"), 0.0),
                "offset": _number(props.get("Offset"), 0.0),
            }

        if class_name == "Lighting" and lighting is None:
            lighting = {
                "path": path,
                "ambient": _color3(props.get("Ambient"), 0.5),
                "outdoorAmbient": _color3(props.get("OutdoorAmbient"), 0.5),
                "brightness": _number(props.get("Brightness"), 1.0),
                "globalShadows": props.get("GlobalShadows", True),
                "clockTime": _number(props.get("ClockTime"), 14.0),
                "geographicLatitude": _number(props.get("GeographicLatitude"), 41.7),
                "shadowSoftness": _number(props.get("ShadowSoftness"), 0.5),
            }

        if class_name == "Camera":
            cf = props.get("CFrame") or {}
            cameras.append({
                "path": path,
                "name": node.get("name"),
                "position": [round(_number(cf.get(axis)), 6) for axis in ("X", "Y", "Z")],
                "fieldOfView": _number(props.get("FieldOfView"), 70.0),
                "preferred": node.get("name") == "CurrentCamera",
            })

        if class_name in PART_CLASSES:
            cf = props.get("CFrame") or {}
            bounds = _part_aabb(props)
            material_name = _enum_name(props.get("Material"), "Plastic")
            entry = {
                "path": path,
                "class": class_name,
                "name": node.get("name"),
                "position": [round(_number(cf.get(axis)), 6) for axis in ("X", "Y", "Z")],
                "orientation": _orientation(cf),
                "size": [round(value, 6) for value in _vec3(props.get("Size"), 1.0)],
                "material": material_name,
                "reflectance": _number(props.get("Reflectance"), 0.0),
                "transparency": _number(props.get("Transparency"), 0.0),
                "castShadow": props.get("CastShadow", True),
                "geometry": (
                    "mesh-asset"
                    if class_name == "MeshPart" and _mesh_available(_asset_id(props.get("MeshId")), mesh_dir)
                    else "union-mesh"
                    if class_name == "UnionOperation" and (
                        props.get("MeshData2") or _union_available(_asset_id(props.get("AssetId"))))
                    else "box-fallback"
                    if class_name in BOX_FALLBACK_CLASSES
                    else (_enum_name(props.get("Shape")) or class_name)
                ),
            }
            if bounds:
                entry["bounds"] = {"min": bounds[0], "max": bounds[1]}
                for i in range(3):
                    overall_min[i] = min(overall_min[i], bounds[0][i])
                    overall_max[i] = max(overall_max[i], bounds[1][i])
            nodes.append(entry)
            if class_name == "MeshPart":
                mesh_id = _asset_id(props.get("MeshId"))
                available = _mesh_available(mesh_id, mesh_dir)
                mesh_references.append({
                    "path": path,
                    "class": class_name,
                    "property": "MeshId",
                    "uri": props.get("MeshId"),
                    "assetId": mesh_id,
                    "available": available,
                })
                if not available:
                    fallback_counts[class_name] = fallback_counts.get(class_name, 0) + 1
            elif class_name == "UnionOperation":
                union_id = _asset_id(props.get("AssetId")) if props.get("AssetId") else None
                available = bool(props.get("MeshData2")) or _union_available(union_id)
                mesh_references.append({
                    "path": path,
                    "class": class_name,
                    "property": "AssetId",
                    "uri": props.get("AssetId"),
                    "assetId": union_id,
                    "available": available,
                })
                if not available:
                    fallback_counts[class_name] = fallback_counts.get(class_name, 0) + 1
            elif class_name in BOX_FALLBACK_CLASSES:
                fallback_counts[class_name] = fallback_counts.get(class_name, 0) + 1
            if material_name not in SUPPORTED_MATERIALS:
                material_fallback_counts[material_name] = material_fallback_counts.get(material_name, 0) + 1
            if material_name not in {"Plastic", "SmoothPlastic"}:
                experimental_materials += 1

        if class_name in {"Decal", "Texture"}:
            uri = props.get("Texture")
            asset_id = _asset_id(uri)
            asset_references.append({
                "path": path,
                "class": class_name,
                "property": "Texture",
                "uri": uri,
                "assetId": asset_id,
                "available": _asset_available(asset_id, texture_dir),
            })

        for child in _children(node):
            visit(child, child["path"], in_lighting, node)

    for root in data.get("roots", []):
        visit(root, root["path"], root.get("className") == "Lighting", None)

    bounds = None
    if nodes and all(math.isfinite(value) for value in overall_min + overall_max):
        bounds = {
            "min": [round(value, 6) for value in overall_min],
            "max": [round(value, 6) for value in overall_max],
            "center": [round((overall_min[i] + overall_max[i]) / 2, 6) for i in range(3)],
            "size": [round(overall_max[i] - overall_min[i], 6) for i in range(3)],
        }

    preferred = next((camera["path"] for camera in cameras if camera["preferred"]), None)
    if preferred is None and cameras:
        preferred = cameras[0]["path"]

    return stamp("scene-dump", {
        "source": data.get("sourcePath"),
        "bounds": bounds,
        "parts": nodes,
        "cameras": cameras,
        "preferredCamera": preferred,
        "lighting": lighting,
        "atmosphere": atmosphere,
        "sky": sky,
        "terrain": terrain_summaries,
        "lights": lights,
        "beams": beams,
        "trails": trails,
        "specialMeshes": special_meshes,
        "fallbacks": dict(sorted(fallback_counts.items())),
        "materialFallbacks": dict(sorted(material_fallback_counts.items())),
        "assetReferences": asset_references,
        "meshReferences": mesh_references,
        "unsupportedVisualClasses": dict(sorted(unsupported_counts.items())),
        "classCounts": dict(sorted(class_counts.items())),
        "experimental": _experimental(class_counts, experimental_materials),
    })


# Rough approximations (docs/GOAL.md): present in the render, but not to be trusted
# the way Part geometry, cameras and UI layout are. Meshes, unions, Sky and terrain
# are not listed: they are compared with Studio, and a missing mesh or union is a
# geometry fallback instead.
EXPERIMENTAL_CLASSES = (
    "Atmosphere", "Beam", "Decal", "ParticleEmitter", "PointLight",
    "SpotLight", "SurfaceLight", "Texture", "Trail",
)


def _experimental(class_counts: dict[str, int], materials: int) -> dict[str, int]:
    from rhr.studio import studio_install

    found = {name: class_counts[name] for name in EXPERIMENTAL_CLASSES if class_counts.get(name)}
    # Without Studio, materials are look-alike textures rather than Roblox's own.
    if materials and studio_install() is None:
        found["Material"] = materials
    return dict(sorted(found.items()))


def notes_line(scene_dump: dict) -> str:
    """One stderr line: what in this render is a fallback, unsupported, or experimental."""
    experimental = ",".join(f"{name}x{count}" for name, count in scene_dump["experimental"].items())
    missing_assets = sum(1 for item in scene_dump["assetReferences"] if not item["available"])
    return (
        f"notes  geometry-fallbacks={sum(scene_dump['fallbacks'].values())} "
        f"material-fallbacks={sum(scene_dump['materialFallbacks'].values())} "
        f"unsupported-visuals={sum(scene_dump['unsupportedVisualClasses'].values())} "
        f"missing-assets={missing_assets} experimental={experimental or 'none'}"
    )


def dump_json(scene_dump: dict) -> str:
    return json.dumps(scene_dump, indent=2, sort_keys=True)
