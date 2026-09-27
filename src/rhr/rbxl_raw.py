"""Narrow Roblox binary-container reader for raw string properties.

This is intentionally *not* a second Roblox DOM. RHR uses Lune/rbx-dom for the
instance tree. Some serialized hidden properties (notably Terrain.SmoothGrid)
are preserved in binary .rbxl/.rbxm files but are not exposed by the Lune
Instance surface, so this module can recover one string/BinaryString PROP value
directly from the chunk container.

Only the small subset needed for raw string extraction is implemented:
- binary format v0 header/chunk framing
- uncompressed, LZ4-block and ZSTD chunks
- INST class id/name/count
- PROP type 0x01 (String/BinaryString/Content)
"""

from __future__ import annotations

import base64
import re
import struct
from pathlib import Path

MAGIC = b"<roblox!"
SIGNATURE = b"\x89\xff\r\n\x1a\n"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class BinaryRbxError(ValueError):
    pass


def _u32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise BinaryRbxError("truncated u32")
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _string(data: bytes, offset: int) -> tuple[bytes, int]:
    length, offset = _u32(data, offset)
    end = offset + length
    if end > len(data):
        raise BinaryRbxError("truncated string")
    return data[offset:end], end


def _lz4_block(data: bytes, expected_size: int, limit: int | None = None) -> bytes:
    """Decode an LZ4 block (no frame header), as used by Roblox chunks.

    With `limit`, stop once at least that many bytes are out and return them (a
    prefix, enough to read a chunk's header without decoding all of it).
    """
    source = 0
    out = bytearray()

    while source < len(data):
        token = data[source]
        source += 1

        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if source >= len(data):
                    raise BinaryRbxError("truncated LZ4 literal length")
                extra = data[source]
                source += 1
                literal_length += extra
                if extra != 255:
                    break

        literal_end = source + literal_length
        if literal_end > len(data):
            raise BinaryRbxError("truncated LZ4 literals")
        out += data[source:literal_end]
        source = literal_end
        if limit is not None and len(out) >= limit:
            return bytes(out)

        # A final literal run may end the block without a match.
        if source >= len(data):
            break

        if source + 2 > len(data):
            raise BinaryRbxError("truncated LZ4 match offset")
        match_offset = data[source] | (data[source + 1] << 8)
        source += 2
        if match_offset == 0 or match_offset > len(out):
            raise BinaryRbxError("invalid LZ4 match offset")

        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if source >= len(data):
                    raise BinaryRbxError("truncated LZ4 match length")
                extra = data[source]
                source += 1
                match_length += extra
                if extra != 255:
                    break
        match_length += 4

        start = len(out) - match_offset
        if match_offset >= match_length:
            out += out[start:start + match_length]
        else:
            # An overlapping match repeats the last `match_offset` bytes.
            pattern = out[start:]
            repeats, rest = divmod(match_length, match_offset)
            out += pattern * repeats + pattern[:rest]
        if limit is not None and len(out) >= limit:
            return bytes(out)

        if len(out) > expected_size:
            raise BinaryRbxError("LZ4 chunk expanded beyond declared size")

    if len(out) != expected_size:
        raise BinaryRbxError(
            f"LZ4 size mismatch: expected {expected_size}, got {len(out)}"
        )
    return bytes(out)


def _chunks(data: bytes):
    """(name, payload) for each chunk, decompressed."""
    for name, body, compressed, uncompressed in _raw_chunks(data):
        yield name, _decode(name, body, compressed, uncompressed)


def _raw_chunks(data: bytes):
    """(name, body, compressed size, uncompressed size) for each chunk, as stored."""
    if len(data) < 32 or data[:8] != MAGIC or data[8:14] != SIGNATURE:
        raise BinaryRbxError("not a Roblox binary model/place")
    version = struct.unpack_from("<H", data, 14)[0]
    if version != 0:
        raise BinaryRbxError(f"unsupported Roblox binary version {version}")

    offset = 32
    while offset + 16 <= len(data):
        name = data[offset : offset + 4]
        compressed, uncompressed = struct.unpack_from("<II", data, offset + 4)
        offset += 16
        body_length = compressed if compressed else uncompressed
        end = offset + body_length
        if end > len(data):
            raise BinaryRbxError(f"truncated {name!r} chunk")
        body = data[offset:end]
        offset = end
        yield name, body, compressed, uncompressed
        if name == b"END\x00":
            break


def _decode(name: bytes, body: bytes, compressed: int, uncompressed: int, limit: int | None = None) -> bytes:
    """A chunk's payload; with `limit`, possibly only its first `limit`-odd bytes."""
    if not compressed:
        if len(body) != uncompressed:
            raise BinaryRbxError(f"bad uncompressed length for {name!r}")
        return body
    if body.startswith(ZSTD_MAGIC):
        # Recent Studio builds save some places with ZSTD chunks.
        import zstandard

        try:
            body = zstandard.ZstdDecompressor().decompress(body, max_output_size=uncompressed)
        except zstandard.ZstdError as exc:
            raise BinaryRbxError(f"bad ZSTD {name!r} chunk: {exc}") from exc
        if len(body) != uncompressed:
            raise BinaryRbxError(f"ZSTD size mismatch in {name!r} chunk")
        return body
    return _lz4_block(body, uncompressed, limit)


# Enough of a chunk to read its header: class id, a class or property name, and the
# bytes after it. A header that needs more is decoded in full.
_HEADER_BYTES = 512


def extract_xml_binary_string_property(
    path: str | Path,
    class_name: str,
    property_name: str,
) -> list[bytes]:
    """Recover base64 BinaryString values from an XML Roblox file.

    This intentionally uses a narrow textual scan instead of materializing a
    second DOM. It is only a companion to extract_string_property for hidden
    serialized values such as Terrain.SmoothGrid.
    """
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    results: list[bytes] = []
    item_pattern = re.compile(
        rf'<Item\s+class="{re.escape(class_name)}"(?:\s[^>]*)?>.*?</Item>',
        flags=re.DOTALL,
    )
    property_pattern = re.compile(
        rf'<BinaryString\s+name="{re.escape(property_name)}">(.*?)</BinaryString>',
        flags=re.DOTALL,
    )
    for item in item_pattern.finditer(text):
        match = property_pattern.search(item.group(0))
        if not match:
            continue
        encoded = re.sub(r"<!\[CDATA\[|\]\]>|\s+", "", match.group(1))
        try:
            results.append(base64.b64decode(encoded, validate=True) if encoded else b"")
        except ValueError as exc:
            raise BinaryRbxError(
                f"invalid base64 in {class_name}.{property_name}"
            ) from exc
    return results


def extract_serialized_string_property(
    path: str | Path,
    class_name: str,
    property_name: str,
) -> list[bytes]:
    """Extract a serialized string/BinaryString from binary or XML Roblox files."""
    source = Path(path)
    prefix = source.read_bytes()[:8]
    if prefix == MAGIC:
        return extract_string_property(source, class_name, property_name)
    return extract_xml_binary_string_property(source, class_name, property_name)


EMPTY_TERRAIN_SMOOTH_GRID = b"\x01\x05"


def _header_end(payload: bytes) -> int | None:
    """Where an INST/PROP header (class id, name, one more byte, plus INST's count)
    ends in `payload`, or None when the payload is too short to tell."""
    if len(payload) < 8:
        return None
    length = struct.unpack_from("<I", payload, 4)[0]
    end = 8 + length + 5
    return end if end <= len(payload) else None


def extract_string_property(
    path: str | Path | bytes,
    class_name: str,
    property_name: str,
) -> list[bytes]:
    """Return raw string/BinaryString values for one class/property.

    Values are returned in the class's INST order. Most services such as Terrain
    have exactly one value in a place file. `path` may also be the file's bytes.
    """
    data = bytes(path) if isinstance(path, (bytes, bytearray)) else Path(path).read_bytes()
    classes: dict[int, tuple[str, int]] = {}
    wanted_id: int | None = None
    results: list[bytes] | None = None

    # Only chunk headers are decoded, except for the one property wanted: a big place
    # has thousands of chunks, and decoding them all took most of a scene dump.
    for chunk_name, body, compressed, uncompressed in _raw_chunks(data):
        if chunk_name not in (b"INST", b"PROP"):
            continue
        payload = _decode(chunk_name, body, compressed, uncompressed, _HEADER_BYTES)
        if len(payload) < uncompressed and _header_end(payload) is None:
            payload = _decode(chunk_name, body, compressed, uncompressed)
        if chunk_name == b"INST":
            offset = 0
            class_id, offset = _u32(payload, offset)
            raw_name, offset = _string(payload, offset)
            try:
                decoded_name = raw_name.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BinaryRbxError("invalid UTF-8 class name") from exc
            if offset + 5 > len(payload):
                raise BinaryRbxError("truncated INST header")
            object_format = payload[offset]
            offset += 1
            instance_count, offset = _u32(payload, offset)
            classes[class_id] = (decoded_name, instance_count)
            if decoded_name == class_name:
                wanted_id = class_id

        elif chunk_name == b"PROP":
            offset = 0
            class_id, offset = _u32(payload, offset)
            raw_name, offset = _string(payload, offset)
            if offset >= len(payload):
                raise BinaryRbxError("truncated PROP type id")
            type_id = payload[offset]
            offset += 1
            if wanted_id is None or class_id != wanted_id:
                continue
            try:
                decoded_name = raw_name.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BinaryRbxError("invalid UTF-8 property name") from exc
            if decoded_name != property_name:
                continue
            if len(payload) < uncompressed:
                payload = _decode(chunk_name, body, compressed, uncompressed)
            if type_id != 0x01:
                raise BinaryRbxError(
                    f"{class_name}.{property_name} has type 0x{type_id:02x}, expected String/BinaryString"
                )
            class_info = classes.get(class_id)
            if class_info is None:
                raise BinaryRbxError("PROP appeared before matching INST")
            _, count = class_info
            values: list[bytes] = []
            for _ in range(count):
                value, offset = _string(payload, offset)
                values.append(value)
            results = values

    return results or []
