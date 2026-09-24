"""Union (CSG) render meshes: decode Roblox's CSGMDL format into plain arrays.

A UnionOperation's shape is computed by Studio when the union is made and saved as
a render mesh. Modern unions keep it in a separate asset (UnionOperation.AssetId: a
small model holding a PartOperationAsset whose MeshData is the mesh); older ones
carry it in the place itself (MeshData2). Either way the bytes are a CSGMDL mesh.
RHR decodes it rather than recomputing the boolean from the source parts, so a
union is drawn with exactly the shape and per-face colours Studio saved.

Format (versions 2, 4 and 5) as documented by rbx_mesh
(https://github.com/krakow10/rbx_mesh, MIT/Apache-2.0); this is an independent
Python implementation.

- The file starts with "CSGMDL" + a u32 version, XOR-obfuscated with a fixed 31-byte
  cycle. Versions 2 and 4 obfuscate the whole payload; version 5 only the 10-byte
  magic.
- v2/v4: 32-byte hash, u32 vertex count, u32 stride (84), vertices (position,
  normal, RGBA colour, u32 NormalId, uv, 16 zero bytes, tangent, 16 zero bytes),
  u32 index count, u32 indices. v4 appends a u32-counted list, unused here.
- v5: deinterleaved arrays with u16 counts: positions (f32x3), quantised normals
  (i16x3), colours (u8x4), NormalIds (u8), uvs (f32x2), quantised tangents; then
  delta-encoded indices with range markers, of which the first range is the
  render mesh.

Positions are in the union's own space at the size it was made (InitialSize); the
scene fits them to the part's current Size like any mesh.
"""

from __future__ import annotations

import base64
import struct

_XOR = bytes((86, 46, 110, 88, 49, 32, 48, 4, 52, 105, 12, 119, 12, 1, 94, 0,
              26, 96, 55, 105, 29, 82, 43, 7, 79, 36, 89, 101, 83, 4, 122))
_MAGIC = b"CSGMDL"
_OBFUSCATED_MAGIC = bytes(b ^ _XOR[i] for i, b in enumerate(_MAGIC))
_MAX_VERTICES = 4_000_000


class UnionFormatError(ValueError):
    pass


def _deobfuscate(blob: bytes) -> bytes:
    cycle = _XOR * (len(blob) // len(_XOR) + 1)
    return bytes(a ^ b for a, b in zip(blob, cycle))


class _Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    def take(self, count: int) -> bytes:
        end = self.offset + count
        if count < 0 or end > len(self.data):
            raise UnionFormatError("truncated union mesh")
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))


def decode(blob: bytes) -> dict:
    """CSGMDL bytes -> {positions, normals, colors, uvs, indices} as flat lists."""
    blob = bytes(blob)
    if len(blob) < 10 or blob[:6] != _OBFUSCATED_MAGIC:
        if blob[:4] == b"CSGK":
            raise UnionFormatError("CSGK union (a reference to another asset), not a mesh")
        raise UnionFormatError("not a CSGMDL union mesh")
    if blob[6] == 0x35:  # '5': only the magic is obfuscated
        return _decode_v5(blob)
    plain = _deobfuscate(blob)
    version = struct.unpack_from("<I", plain, 6)[0]
    if version not in (2, 4):
        raise UnionFormatError(f"unsupported CSGMDL version {version}")
    return _decode_v2(plain)


def _decode_v2(plain: bytes) -> dict:
    reader = _Reader(plain, 10 + 32)
    count, stride = reader.unpack("<II")
    if count > _MAX_VERTICES or stride < 84:
        raise UnionFormatError("bad CSGMDL vertex table")
    positions: list[float] = []
    normals: list[float] = []
    colors: list[int] = []
    uvs: list[float] = []
    block = reader.take(count * stride)
    for i in range(count):
        base = i * stride
        px, py, pz, nx, ny, nz = struct.unpack_from("<6f", block, base)
        positions += (px, py, pz)
        normals += (nx, ny, nz)
        colors += block[base + 24:base + 28]
        uvs += struct.unpack_from("<2f", block, base + 32)
    (index_count,) = reader.unpack("<I")
    if index_count % 3 or index_count > 3 * _MAX_VERTICES:
        raise UnionFormatError("bad CSGMDL index count")
    indices = list(struct.unpack(f"<{index_count}I", reader.take(index_count * 4)))
    if any(i >= count for i in indices):
        raise UnionFormatError("CSGMDL index out of range")
    return {"positions": positions, "normals": normals, "colors": colors, "uvs": uvs, "indices": indices}


def _dequantise(values) -> list[float]:
    out = []
    for value in values:
        value = (value - 0x7FFF) & 0xFFFF
        if value >= 0x8000:
            value -= 0x10000
        out.append(value / 32767.0)
    return out


def _decode_v5(blob: bytes) -> dict:
    reader = _Reader(blob, 10)
    (count,) = reader.unpack("<H")
    positions = list(struct.unpack(f"<{count * 3}f", reader.take(count * 12)))
    (normal_count,) = reader.unpack("<H")
    reader.take(4)
    normals = _dequantise(struct.unpack(f"<{normal_count * 3}H", reader.take(normal_count * 6)))
    (color_count,) = reader.unpack("<H")
    colors = list(reader.take(color_count * 4))
    (normal_id_count,) = reader.unpack("<H")
    reader.take(normal_id_count)
    (uv_count,) = reader.unpack("<H")
    uvs = list(struct.unpack(f"<{uv_count * 2}f", reader.take(uv_count * 8)))
    (tangent_count,) = reader.unpack("<H")
    reader.take(4)
    reader.take(tangent_count * 6)
    index_count, data_length = reader.unpack("<II")
    data = reader.take(data_length)
    (marker_count,) = reader.unpack("<B")
    markers = list(reader.unpack(f"<{marker_count}I")) if marker_count else []

    indices: list[int] = []
    position = 0
    current = 0
    for _ in range(index_count):
        if position >= len(data):
            raise UnionFormatError("truncated CSGMDL index stream")
        v0 = data[position]
        position += 1
        if v0 < 64:
            offset = v0
        elif v0 < 128:
            offset = v0 - 128
        else:
            if position + 2 > len(data):
                raise UnionFormatError("truncated CSGMDL index stream")
            offset = data[position + 1] | (data[position] << 8) | ((v0 - 128) << 16)
            position += 2
        current = (current + offset) & 0xFFFFFFFF
        indices.append(current & 0x007FFFFF)
    if markers:
        start = markers[0]
        end = markers[1] if len(markers) > 1 else len(indices)
        indices = indices[start:end]
    if len(indices) % 3 or any(i >= count for i in indices):
        raise UnionFormatError("bad CSGMDL v5 indices")
    if len(normals) != len(positions):
        normals = []
    if len(colors) != count * 4:
        colors = []
    if len(uvs) != count * 2:
        uvs = []
    return {"positions": positions, "normals": normals, "colors": colors, "uvs": uvs, "indices": indices}


def mesh_from_asset(payload: bytes) -> bytes:
    """The CSGMDL bytes inside a union asset (a model holding a PartOperationAsset)."""
    from rhr.rbxl_raw import BinaryRbxError, extract_string_property

    if payload[:4] == _OBFUSCATED_MAGIC[:4] or payload[:6] == _OBFUSCATED_MAGIC:
        return payload  # already a bare mesh
    try:
        values = extract_string_property(payload, "PartOperationAsset", "MeshData")
    except BinaryRbxError as exc:
        raise UnionFormatError(f"not a union asset: {exc}") from exc
    values = [v for v in values if v]
    if not values:
        raise UnionFormatError("union asset has no MeshData")
    return values[0]


def to_payload(mesh: dict) -> dict:
    """Decoded mesh -> the JSON the scene page reads (little-endian base64 arrays)."""
    def pack(fmt: str, values) -> str:
        return base64.b64encode(struct.pack(f"<{len(values)}{fmt}", *values)).decode("ascii")

    return {
        "positions": pack("f", mesh["positions"]),
        "normals": pack("f", mesh["normals"]),
        "colors": base64.b64encode(bytes(mesh["colors"])).decode("ascii"),
        "uvs": pack("f", mesh["uvs"]),
        "indices": pack("I", mesh["indices"]),
    }
