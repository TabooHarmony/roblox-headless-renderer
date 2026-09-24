"""Decode Roblox voxel terrain (Terrain.SmoothGrid) for a plain, blocky preview.

The format has no public spec. It was worked out from the one design write-up
(https://zeux.io/2017/03/27/voxel-terrain-storage/) and checked against Studio's own
Terrain:ReadVoxels on Roblox's game template: every one of its 15 chunks decodes to
the same per-material voxel counts Studio reports, and sampled voxels match in
material and occupancy.

    b"\\x01\\x05"                      version 1, chunks of 2**5 = 32 voxels a side
    then, per chunk:
      12 bytes                        chunk position as a delta from the previous
                                      chunk: three big-endian int32 (x, y, z) with
                                      their bytes interleaved (x0 y0 z0 x1 y1 z1 ...)
      runs until 32**3 voxels         lead byte: material id (bits 0-5), "occupancy
                                      byte follows" (bit 6), "run length byte follows"
                                      (bit 7); then the occupancy byte, then the run
                                      length minus one
    voxel order inside a chunk: x fastest, then z, then y

A voxel is 4 studs; chunk (cx, cy, cz) starts at stud (cx, cy, cz) * 128. Occupancy
is 0-255; a solid voxel with no occupancy byte is full.

Terrain.MaterialColors is 23 RGB triples in material-id order (checked against
Terrain:GetMaterialColor). White means "the texture's own colour" in modern Roblox
terrain, whose textures are coloured; RHR's textures are greyscale, so white is
replaced by a natural colour for the material.
"""

from __future__ import annotations

import base64
from pathlib import Path

CHUNK = 32
VOXEL_STUDS = 4

# Terrain material ids, in the order Roblox stores them (MaterialColors has one
# entry per id, Air and Water included).
MATERIALS = [
    "Air", "Water", "Grass", "Slate", "Concrete", "Brick", "Sand", "WoodPlanks", "Rock",
    "Glacier", "Snow", "Sandstone", "Mud", "Basalt", "Ground", "CrackedLava", "Asphalt",
    "Cobblestone", "Ice", "LeafyGrass", "Salt", "Limestone", "Pavement",
]

# Stand-in colours for materials a place leaves white (sRGB 0-255).
NATURAL_COLORS = {
    "Grass": (96, 134, 58), "Slate": (92, 98, 96), "Concrete": (150, 148, 142),
    "Brick": (138, 86, 62), "Sand": (206, 186, 140), "WoodPlanks": (139, 109, 79),
    "Rock": (110, 112, 114), "Glacier": (170, 210, 234), "Snow": (235, 238, 245),
    "Sandstone": (170, 128, 96), "Mud": (86, 66, 50), "Basalt": (58, 58, 64),
    "Ground": (112, 96, 66), "CrackedLava": (200, 96, 54), "Asphalt": (86, 90, 90),
    "Cobblestone": (132, 126, 110), "Ice": (180, 214, 232), "LeafyGrass": (98, 128, 60),
    "Salt": (210, 204, 196), "Limestone": (210, 196, 168), "Pavement": (148, 148, 140),
}


class TerrainFormatError(ValueError):
    pass


def decode_smooth_grid(data: bytes) -> list[tuple[tuple[int, int, int], bytes, bytes]]:
    """[(chunk position, materials, occupancies)], each 32**3 bytes in x, z, y order."""
    if len(data) < 2 or data[0] != 1 or data[1] != 5:
        raise TerrainFormatError(f"unknown SmoothGrid header {data[:2].hex()}")
    size = CHUNK ** 3
    chunks = []
    offset = 2
    position = [0, 0, 0]
    while offset < len(data):
        if offset + 12 > len(data):
            raise TerrainFormatError("truncated chunk header")
        header = data[offset:offset + 12]
        offset += 12
        for axis in range(3):
            value = int.from_bytes(bytes(header[axis + 3 * k] for k in range(4)), "big", signed=True)
            position[axis] += value
        materials = bytearray(size)
        occupancy = bytearray(size)
        count = 0
        while count < size:
            if offset >= len(data):
                raise TerrainFormatError("truncated voxel runs")
            lead = data[offset]
            offset += 1
            material = lead & 0x3F
            occ = 255 if material else 0
            if lead & 0x40:
                occ = data[offset]
                offset += 1
            run = 1
            if lead & 0x80:
                run = data[offset] + 1
                offset += 1
            if count + run > size or material >= len(MATERIALS):
                raise TerrainFormatError("voxel run past the chunk, or unknown material")
            materials[count:count + run] = bytes([material]) * run
            occupancy[count:count + run] = bytes([occ]) * run
            count += run
        chunks.append((tuple(position), bytes(materials), bytes(occupancy)))
    return chunks


def raw_material_colors(data: bytes | None) -> dict[str, tuple[int, int, int]]:
    """The place's own MaterialColors, white included (a MaterialVariant's image is tinted by it)."""
    if not data or len(data) < 3 * len(MATERIALS):
        return {}
    return {name: tuple(data[3 * i:3 * i + 3]) for i, name in enumerate(MATERIALS) if name in NATURAL_COLORS}


def material_colors(data: bytes | None) -> dict[str, tuple[int, int, int]]:
    """Colour per material: the place's own, or a natural stand-in where it is white."""
    colors = dict(NATURAL_COLORS)
    if data and len(data) >= 3 * len(MATERIALS):
        for index, name in enumerate(MATERIALS):
            rgb = tuple(data[3 * index:3 * index + 3])
            if name in colors and rgb != (255, 255, 255) and rgb != (0, 0, 0):
                colors[name] = rgb
    return colors


def terrain_payload(source: Path) -> dict | None:
    """What the scene page needs to draw the terrain of `source`, or None if it has none."""
    from rhr.rbxl_raw import EMPTY_TERRAIN_SMOOTH_GRID, BinaryRbxError, extract_serialized_string_property

    try:
        grids = extract_serialized_string_property(source, "Terrain", "SmoothGrid")
    except (OSError, BinaryRbxError, UnicodeError):
        return None
    grids = [g for g in grids if g and g != EMPTY_TERRAIN_SMOOTH_GRID]
    if not grids:
        return None
    try:
        chunks = decode_smooth_grid(grids[0])
        colors = extract_serialized_string_property(source, "Terrain", "MaterialColors")
    except (TerrainFormatError, OSError, BinaryRbxError, UnicodeError):
        return None
    return {
        "chunkSize": CHUNK,
        "voxelStuds": VOXEL_STUDS,
        "materials": MATERIALS,
        "colors": material_colors(colors[0] if colors else None),
        "rawColors": raw_material_colors(colors[0] if colors else None),
        "chunks": [
            {"position": list(position), "materials": base64.b64encode(m).decode("ascii"),
             "occupancy": base64.b64encode(o).decode("ascii")}
            for position, m, o in chunks
            if any(m)
        ],
    }
