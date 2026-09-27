"""Roblox's binary model/place format (.rbxm, .rbxl), decoded as rbx-dom does.

A port of rbx_binary's deserializer (rbx_binary 3.0.0, with rbx_types 3.1.0 and the
reflection database Lune 0.10.5 uses), so a file reads here exactly as it reads in
Lune: the same instances, the same property names after aliases and migrations, the
same values. The format is columnar (one PROP chunk holds one property of every
instance of a class), so values decode a column at a time with numpy.

The result is a `Document`: instances in file order, each with its class, name,
children, and the properties the file stores, under their canonical names.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from rhr.rbx.reflection import Reflection, reflection
from rhr.rbxl_raw import _HEADER_BYTES, MAGIC, SIGNATURE, BinaryRbxError, _decode, _header_end, _raw_chunks


# --- values ---------------------------------------------------------------------------
# Plain tuples tagged with the rbx_types variant name. Floats are 32-bit values held
# as Python floats (exactly what Lune hands Lua).

@dataclass(frozen=True)
class V:
    """A typed value: `kind` is the rbx_types variant (Vector3, CFrame, Enum, ...)."""
    kind: str
    value: object


# --- low-level readers ----------------------------------------------------------------

class Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.o = offset

    def u8(self) -> int:
        value = self.data[self.o]
        self.o += 1
        return value

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.data, self.o)[0]
        self.o += 2
        return value

    def i16(self) -> int:
        value = struct.unpack_from("<h", self.data, self.o)[0]
        self.o += 2
        return value

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.data, self.o)[0]
        self.o += 4
        return value

    def f32(self) -> float:
        value = struct.unpack_from("<f", self.data, self.o)[0]
        self.o += 4
        return value

    def f64(self) -> float:
        value = struct.unpack_from("<d", self.data, self.o)[0]
        self.o += 8
        return value

    def f32s(self, n: int) -> list[float]:
        values = struct.unpack_from(f"<{n}f", self.data, self.o)
        self.o += 4 * n
        return list(values)

    def bytes_(self) -> bytes:
        n = self.u32()
        value = bytes(self.data[self.o:self.o + n])
        if len(value) != n:
            raise BinaryRbxError("truncated string")
        self.o += n
        return value

    def string(self) -> str:
        return self.bytes_().decode("utf-8", errors="replace")

    def _planes(self, count: int, width: int) -> np.ndarray:
        size = count * width
        if self.o + size > len(self.data):
            raise BinaryRbxError("truncated interleaved array")
        planes = np.frombuffer(self.data, dtype=np.uint8, count=size, offset=self.o).reshape(width, count)
        self.o += size
        return planes

    def interleaved_u32(self, count: int) -> np.ndarray:
        p = self._planes(count, 4).astype(np.uint32)
        return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]

    def interleaved_i32(self, count: int) -> np.ndarray:
        raw = self.interleaved_u32(count).astype(np.int64)
        return (raw >> 1) ^ -(raw & 1)

    def interleaved_f32(self, count: int) -> np.ndarray:
        raw = self.interleaved_u32(count)
        return ((raw >> 1) | ((raw & 1) << 31)).astype(np.uint32).view(np.float32)

    def interleaved_i64(self, count: int) -> np.ndarray:
        p = self._planes(count, 8).astype(np.uint64)
        raw = np.zeros(count, dtype=np.uint64)
        for i in range(8):
            raw = (raw << np.uint64(8)) | p[i]
        signed = raw.view(np.int64)
        return (raw >> np.uint64(1)).view(np.int64) ^ -(signed & 1)

    def referents(self, count: int) -> np.ndarray:
        return np.cumsum(self.interleaved_i32(count))


def _f(values) -> list[float]:
    """float32 numpy values as Python floats (the doubles Lune's numbers are)."""
    return np.asarray(values, dtype=np.float32).astype(np.float64).tolist()


# Axis-aligned rotations by id (rbx_types Matrix3::from_basic_rotation_id): the rows'
# x axis is normal (id - 1) // 6 and the y axis normal (id - 1) % 6, of +X +Y +Z -X -Y -Z.
_NORMALS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
BASIC_ROTATIONS: dict[int, tuple] = {}
for _rid in range(1, 37):
    _x, _y = _NORMALS[(_rid - 1) // 6], _NORMALS[(_rid - 1) % 6]
    if abs(sum(a * b for a, b in zip(_x, _y))) > 0.5:
        continue  # parallel axes: not a rotation, and not a valid id
    _z = (_x[1] * _y[2] - _x[2] * _y[1], _x[2] * _y[0] - _x[0] * _y[2], _x[0] * _y[1] - _x[1] * _y[0])
    BASIC_ROTATIONS[_rid] = (_x[0], _y[0], _z[0] + 0.0, _x[1], _y[1], _z[1] + 0.0, _x[2], _y[2], _z[2] + 0.0)

FONT_WEIGHTS = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
                600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Heavy"}
FONT_STYLES = {0: "Normal", 1: "Italic"}


def _rotations(r: Reader, n: int) -> list[tuple]:
    out = []
    for _ in range(n):
        rid = r.u8()
        if rid == 0:
            out.append(tuple(r.f32s(9)))
        elif rid in BASIC_ROTATIONS:
            out.append(BASIC_ROTATIONS[rid])
        else:
            raise BinaryRbxError(f"bad CFrame rotation id {rid}")
    return out


# --- binary type ids -> default variant for properties the database does not know ----

TYPES = {
    0x01: "String", 0x02: "Bool", 0x03: "Int32", 0x04: "Float32", 0x05: "Float64", 0x06: "UDim",
    0x07: "UDim2", 0x08: "Ray", 0x09: "Faces", 0x0A: "Axes", 0x0B: "BrickColor", 0x0C: "Color3",
    0x0D: "Vector2", 0x0E: "Vector3", 0x10: "CFrame", 0x12: "Enum", 0x13: "Ref", 0x14: "Vector3int16",
    0x15: "NumberSequence", 0x16: "ColorSequence", 0x17: "NumberRange", 0x18: "Rect",
    0x19: "PhysicalProperties", 0x1A: "Color3uint8", 0x1B: "Int64", 0x1C: "SharedString",
    0x1E: "OptionalCFrame", 0x1F: "UniqueId", 0x20: "Font", 0x21: "SecurityCapabilities", 0x22: "Content",
}
# rbx_binary's Type::to_default_rbx_type: String -> BinaryString, Color3uint8 -> Color3.
DEFAULT_VARIANT = {**{name: name for name in TYPES.values()}, "String": "BinaryString", "Color3uint8": "Color3"}


# --- the document ---------------------------------------------------------------------

class Column:
    """One property of every instance of a class, decoded the first time it is read.

    A place stores hundreds of properties per class; the IR reads a few dozen, so the
    rest stay compressed.
    """

    __slots__ = ("chunk", "offset", "binary", "kind", "n", "doc", "source", "operation", "_values", "_raw")

    def __init__(self, chunk, offset, binary, kind, n, doc, source=None, operation=None):
        self.chunk, self.offset, self.binary, self.kind, self.n = chunk, offset, binary, kind, n
        self.doc, self.source, self.operation = doc, source, operation
        self._values = None
        self._raw = None

    def raw(self):
        """(value kind, plain values) of a stored column, or None for a migrated one."""
        if self.source is not None:
            return None
        if self._raw is None:
            name, body, comp, uncomp = self.chunk
            r = Reader(_decode(name, body, comp, uncomp), self.offset)
            self._raw = _decode_column(r, self.binary, self.kind, self.n, self.doc.shared, self.doc.by_referent)
            self.chunk = None
        return self._raw

    def get(self, position: int) -> V:
        if self.source is not None:
            return self.values()[position]
        kind, values = self.raw()
        return V(kind, values[position])

    def values(self) -> list:
        if self._values is None:
            if self.source is not None:  # a migration of another column
                self._values = [_migrate(value, self.operation) for value in self.source.values()]
            else:
                kind, values = self.raw()
                self._values = [V(kind, value) for value in values]
        return self._values


@dataclass
class ClassGroup:
    name: str
    instances: list
    columns: dict = field(default_factory=dict)


@dataclass
class Instance:
    index: int
    class_name: str
    referent: int
    name: str
    group: "ClassGroup | None" = None
    position: int = 0
    children: list = field(default_factory=list)
    parent: "Instance | None" = None

    def get(self, name: str):
        """The value the file stores for canonical property `name`, or None."""
        column = self.group.columns.get(name)
        return None if column is None else column.get(self.position)

    def names(self):
        return self.group.columns.keys()


@dataclass
class Document:
    instances: list[Instance]
    roots: list[Instance]
    by_referent: dict[int, Instance]
    shared: list[bytes] = field(default_factory=list)


def _decode_column(r: Reader, binary: str, canonical: str, n: int, shared: list[bytes], by_ref: dict) -> list[V]:
    """One PROP chunk's values, as rbx_binary's decode_prop_chunk reads them."""
    def same(values, kind=canonical):
        return kind, list(values)

    if binary == "String":
        raw = [r.bytes_() for _ in range(n)]
        if canonical == "String":
            return same([value.decode("utf-8", errors="replace") for value in raw])
        if canonical == "ContentId":
            return same([value.decode("utf-8", errors="replace") for value in raw])
        if canonical in ("BinaryString", "Tags", "Attributes", "MaterialColors"):
            return same(raw)
    elif binary == "Bool" and canonical == "Bool":
        return same([r.u8() != 0 for _ in range(n)])
    elif binary == "Int32" and canonical in ("Int32", "Int64"):
        return same(r.interleaved_i32(n).tolist())
    elif binary == "Float32" and canonical == "Float32":
        return same(_f(r.interleaved_f32(n)))
    elif binary == "Float64":
        if canonical == "Float64":
            return same([r.f64() for _ in range(n)])
        if canonical == "Float32":
            return same(_f(r.interleaved_f32(n)))
    elif binary == "UDim" and canonical == "UDim":
        scales = _f(r.interleaved_f32(n))
        offsets = r.interleaved_i32(n).tolist()
        return same(list(zip(scales, offsets)))
    elif binary == "UDim2" and canonical == "UDim2":
        sx, sy = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        ox, oy = r.interleaved_i32(n).tolist(), r.interleaved_i32(n).tolist()
        return same(list(zip(sx, ox, sy, oy)))
    elif binary == "Ray" and canonical == "Ray":
        return same([tuple(r.f32s(6)) for _ in range(n)])
    elif binary == "Faces" and canonical == "Faces":
        return same([r.u8() for _ in range(n)])
    elif binary == "Axes" and canonical == "Axes":
        return same([r.u8() for _ in range(n)])
    elif binary == "BrickColor" and canonical == "BrickColor":
        return same(r.interleaved_u32(n).tolist())
    elif binary == "Color3" and canonical == "Color3":
        cr, cg, cb = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        return same(list(zip(cr, cg, cb)))
    elif binary == "Vector2" and canonical == "Vector2":
        x, y = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        return same(list(zip(x, y)))
    elif binary == "Vector3" and canonical == "Vector3":
        x, y, z = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        return same(list(zip(x, y, z)))
    elif binary == "CFrame" and canonical == "CFrame":
        rotations = _rotations(r, n)
        x, y, z = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        return same([(px, py, pz, *[float(np.float32(v)) for v in rot]) for px, py, pz, rot in zip(x, y, z, rotations)])
    elif binary == "Enum" and canonical == "Enum":
        return same(r.interleaved_u32(n).tolist())
    elif binary == "Ref" and canonical == "Ref":
        return same([ref if ref in by_ref else None for ref in r.referents(n).tolist()])
    elif binary == "Vector3int16" and canonical == "Vector3int16":
        return same([(r.i16(), r.i16(), r.i16()) for _ in range(n)])
    elif binary == "Font" and canonical == "Font":
        out = []
        for _ in range(n):
            family = r.string()
            weight = FONT_WEIGHTS.get(r.u16(), "Regular")
            style = FONT_STYLES.get(r.u8(), "Normal")
            r.string()  # cached face id
            out.append((family, weight, style))
        return same(out)
    elif binary == "NumberSequence" and canonical == "NumberSequence":
        out = []
        for _ in range(n):
            count = r.u32()
            out.append(tuple(tuple(r.f32s(3)) for _ in range(count)))  # time, value, envelope
        return same(out)
    elif binary == "ColorSequence" and canonical == "ColorSequence":
        out = []
        for _ in range(n):
            count = r.u32()
            keys = []
            for _ in range(count):
                t, cr, cg, cb, _envelope = r.f32s(5)
                keys.append((t, cr, cg, cb))
            out.append(tuple(keys))
        return same(out)
    elif binary == "NumberRange" and canonical == "NumberRange":
        return same([tuple(r.f32s(2)) for _ in range(n)])
    elif binary == "Rect" and canonical == "Rect":
        a, b, c, d = (_f(r.interleaved_f32(n)) for _ in range(4))
        return same(list(zip(a, b, c, d)))
    elif binary == "PhysicalProperties" and canonical == "PhysicalProperties":
        out = []
        for _ in range(n):
            flag = r.u8()
            if flag in (0, 2):
                out.append(None)
            elif flag == 1:
                out.append((*r.f32s(5), 1.0))
            elif flag == 3:
                out.append(tuple(r.f32s(6)))
            else:
                raise BinaryRbxError(f"bad PhysicalProperties type {flag}")
        return same(out)
    elif binary == "Color3uint8" and canonical == "Color3":
        planes = np.frombuffer(r.data, dtype=np.uint8, count=3 * n, offset=r.o).reshape(3, n)
        r.o += 3 * n
        return "Color3uint8", list(zip(*planes.tolist()))
    elif binary == "Int64" and canonical == "Int64":
        return same(r.interleaved_i64(n).tolist())
    elif binary == "SharedString":
        indices = r.interleaved_u32(n).tolist()
        try:
            values = [shared[i] for i in indices]
        except IndexError:
            raise BinaryRbxError("SharedString index out of range") from None
        if canonical in ("SharedString", "NetAssetRef", "Tags"):
            return same(values)
    elif binary == "OptionalCFrame" and canonical == "OptionalCFrame":
        if r.u8() != 0x10:
            raise BinaryRbxError("bad OptionalCFrame format")
        rotations = _rotations(r, n)
        x, y, z = _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n)), _f(r.interleaved_f32(n))
        if r.u8() != 0x02:
            raise BinaryRbxError("bad OptionalCFrame format")
        out = []
        for px, py, pz, rot in zip(x, y, z, rotations):
            present = r.u8() != 0
            out.append((px, py, pz, *[float(np.float32(v)) for v in rot]) if present else None)
        return same(out)
    elif binary == "UniqueId" and canonical == "UniqueId":
        planes = r._planes(n, 16)
        return same([bytes(planes[:, i]) for i in range(n)])
    elif binary == "SecurityCapabilities" and canonical == "SecurityCapabilities":
        return same(r.interleaved_i64(n).tolist())
    elif binary == "Content" and canonical == "Content":
        kinds = r.interleaved_i32(n).tolist()
        uris = [r.string() for _ in range(r.u32())]
        objects = r.referents(r.u32()).tolist()
        out = []
        ui = oi = 0
        for kind in kinds:
            if kind == 0:
                out.append(None)
            elif kind == 1:
                out.append(("uri", uris[ui]))
                ui += 1
            elif kind == 2:
                ref = objects[oi]
                oi += 1
                out.append(("object", ref) if ref in by_ref else None)
            else:
                raise BinaryRbxError(f"bad Content type {kind}")
        return same(out)
    raise BinaryRbxError(f"property stored as {binary} cannot be read as {canonical}")


def read(data: bytes, db: Reflection | None = None) -> Document:
    """Decode a binary .rbxm/.rbxl file's bytes."""
    db = db or reflection()
    if data[:8] != MAGIC or data[8:14] != SIGNATURE:
        raise BinaryRbxError("not a Roblox binary model/place")
    doc = Document([], [], {})
    types: dict[int, ClassGroup] = {}
    parents = None
    chunks = list(_raw_chunks(data))

    # INST first: a PROP can reference instances of any class (Ref, Content objects).
    for chunk in chunks:
        name, body, comp, uncomp = chunk
        if name == b"SSTR":
            r = Reader(_decode(name, body, comp, uncomp))
            r.u32()  # version
            for _ in range(r.u32()):
                r.o += 16  # hash
                doc.shared.append(r.bytes_())
        elif name == b"INST":
            r = Reader(_decode(name, body, comp, uncomp))
            type_id = r.u32()
            class_name = r.string()
            r.u8()  # object format (service markers follow; not needed)
            count = r.u32()
            group = ClassGroup(class_name, [])
            for position, referent in enumerate(r.referents(count).tolist()):
                if referent in doc.by_referent:
                    raise BinaryRbxError(f"duplicate referent {referent}")
                instance = Instance(len(doc.instances), class_name, referent, class_name, group, position)
                doc.instances.append(instance)
                doc.by_referent[referent] = instance
                group.instances.append(instance)
            types[type_id] = group

    for chunk in chunks:
        name, body, comp, uncomp = chunk
        if name == b"PROP":
            head = _decode(name, body, comp, uncomp, _HEADER_BYTES)
            if len(head) < uncomp and _header_end(head) is None:
                head = _decode(name, body, comp, uncomp)
            r = Reader(head)
            type_id = r.u32()
            prop_name = r.string()
            if r.o >= uncomp:
                continue  # a PROP chunk with no type byte is ignored, as Roblox does
            binary = TYPES.get(r.u8())
            if binary is None:
                continue  # unknown value type: skipped with a warning in rbx-dom
            group = types.get(type_id)
            if group is None:
                raise BinaryRbxError(f"PROP for unknown type id {type_id}")
            n = len(group.instances)
            if prop_name == "Name":
                r = Reader(_decode(name, body, comp, uncomp), r.o)
                for instance in group.instances:
                    instance.name = r.bytes_().decode("utf-8", errors="replace")
                continue
            canonical = db.canonical(group.name, prop_name)
            if canonical is None:
                target, kind, migration = prop_name, DEFAULT_VARIANT[binary], None
            elif canonical is False:
                continue  # known, and not supposed to serialize: skipped
            else:
                target, kind, migration = canonical
            column = Column(chunk, r.o, binary, kind, n, doc)
            if migration is None:
                group.columns[target] = column
            else:
                # Every instance of a class holds the same stored properties, so rbx-dom's
                # "only if the new property is not set yet" is decided per class.
                new_names, operation = migration
                for new_name in new_names:
                    if new_name not in group.columns:
                        group.columns[new_name] = Column(None, 0, binary, kind, n, doc, column, operation)
        elif name == b"PRNT":
            r = Reader(_decode(name, body, comp, uncomp))
            r.u8()  # version
            count = r.u32()
            parents = (r.referents(count).tolist(), r.referents(count).tolist())

    if parents is not None:
        for child_ref, parent_ref in zip(*parents):
            child = doc.by_referent.get(child_ref)
            if child is None:
                continue
            parent = doc.by_referent.get(parent_ref)
            if parent_ref == -1 or parent is None:
                doc.roots.append(child)
            else:
                child.parent = parent
                parent.children.append(child)
    return doc


def _migrate(value: V, operation: str) -> V | None:
    """rbx_reflection 7.0.0's property migrations. None: the migration fails (rbx-dom
    logs a warning and the property is dropped)."""
    if operation == "ContentIdToContent":
        if value.kind != "ContentId":
            return None
        return V("Content", ("uri", value.value) if value.value else None)
    if operation == "Int64ToContent":
        if value.kind != "Int64":
            return None
        return V("Content", ("uri", f"rbxassetid://{value.value}") if value.value else None)
    if operation == "BrickColorToColor":
        from rhr.rbx.tables import BRICK_COLORS

        rgb = BRICK_COLORS.get(value.value) if value.kind == "BrickColor" else None
        return V("Color3uint8", rgb) if rgb is not None else None
    if operation == "FontToFontFace":
        from rhr.rbx.tables import LEGACY_FONTS

        font = LEGACY_FONTS.get(value.value) if value.kind == "Enum" else None
        return V("Font", font) if font is not None else None
    if operation == "IgnoreGuiInsetToScreenInsets":
        return V("Enum", 1 if value.value else 2) if value.kind == "Bool" else None
    if operation == "CornerRadiusToCornerRadii":
        return value if value.kind == "UDim" else None
    raise BinaryRbxError(f"unknown property migration {operation}")
