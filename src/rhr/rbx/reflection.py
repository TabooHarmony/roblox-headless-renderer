"""Roblox's reflection data, as rbx-dom (and so Lune) uses it.

reflection.json.gz is built by scripts/make_reflection.py from the rbx_reflection
database at the version the pinned Lune bundles. Two questions matter:

- `canonical(class, name)`: what a property stored in a file under `name` becomes when
  rbx-dom reads it (rbx_binary's find_canonical_property): its canonical name and type,
  a migration to newer properties, or skipped because it should not serialize.
- `property_info(class, name)`: what Lune's `instance[name]` sees (lune-roblox's
  find_property_info): the property's type or enum and its class default.
"""

from __future__ import annotations

import functools
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).with_name("reflection.json.gz")


@dataclass(frozen=True)
class PropertyInfo:
    enum: str | None          # enum name for an enum property
    value_type: str | None    # rbx_types variant name otherwise
    default: object           # the class default (a binary.V), or None


class Reflection:
    def __init__(self, document: dict):
        self.version = document["version"]
        self.classes = document["classes"]
        self.enums = document["enums"]
        self.enum_names = {name: {value: item for item, value in items.items()}
                           for name, items in self.enums.items()}
        self._canonical: dict = {}
        self._info: dict = {}
        self._found: dict = {}

    def chain(self, class_name: str):
        """The class and its superclasses that the database knows, nearest first."""
        seen = 0
        current = class_name
        while current and seen < 64:
            cls = self.classes.get(current)
            if cls is None:
                return
            yield current, cls
            current = cls.get("super")
            seen += 1

    def is_known(self, class_name: str) -> bool:
        return class_name in self.classes

    def _find(self, class_name: str, name: str):
        key = (class_name, name)
        found = self._found.get(key)
        if found is None:
            found = self._found[key] = self._search(class_name, name)
        return found

    def _search(self, class_name: str, name: str):
        for cname, cls in self.chain(class_name):
            entry = cls["props"].get(name)
            if entry is not None:
                return cname, entry
        return None, None

    def canonical(self, class_name: str, name: str):
        """None: unknown (kept under its own name); False: known but not serialized
        (skipped); else (canonical name, variant type, migration or None)."""
        key = (class_name, name)
        if key in self._canonical:
            return self._canonical[key]
        _, entry = self._find(class_name, name)
        result = None
        if entry is not None:
            canonical_name = name
            if entry[1] == "A":
                canonical_name = entry[2]
                _, entry = self._find(class_name, canonical_name)
            if entry is not None:
                kind = entry[1]
                ty = "Enum" if entry[0].startswith("E:") else entry[0][2:]
                if kind == "N":
                    result = False
                elif kind == "M":
                    targets = entry[2] if isinstance(entry[2], list) else [entry[2]]
                    result = (canonical_name, ty, (tuple(targets), entry[3]))
                else:
                    result = (canonical_name, ty, None)
        self._canonical[key] = result
        return result

    def property_info(self, class_name: str, name: str) -> PropertyInfo | None:
        """What Lune's property getter finds for `name` on `class_name`, or None."""
        key = (class_name, name)
        if key in self._info:
            return self._info[key]
        info = None
        if name not in ("Attributes", "Tags"):
            _, entry = self._find(class_name, name)
            if entry is not None:
                enum = entry[0][2:] if entry[0].startswith("E:") else None
                value_type = None if enum else entry[0][2:]
                default = None
                for _, cls in self.chain(class_name):
                    if name in cls["defaults"]:
                        default = cls["defaults"][name]
                        break
                info = PropertyInfo(enum, value_type, _default_value(default, enum) if default else None)
        self._info[key] = info
        return info

    def property_names(self, class_name: str) -> set[str]:
        """Every property name the class has (with superclasses), aliases included."""
        names: set[str] = set()
        for _, cls in self.chain(class_name):
            names.update(cls["props"])
        return names

    def serialized_name(self, class_name: str, name: str) -> str | None:
        """The name a canonical property is written under in XML, or None when it
        does not serialize (rbx_xml follows the same database)."""
        _, entry = self._find(class_name, name)
        if entry is None:
            return name  # unknown to the database: written under its own name
        kind = entry[1]
        if kind == "S":
            return name
        if kind == "AS":
            return entry[2]
        if kind == "M":
            return None  # migrated away on read: the instance never holds it
        return None


def _default_value(default, enum):
    """A database default ([variant, payload]) as the value binary.read would give."""
    from rhr.rbx.binary import V

    kind, payload = default
    if enum is not None:
        return V("Enum", int(payload)) if kind == "Enum" else None
    if kind in ("Vector3", "Vector2", "Color3"):
        return V(kind, tuple(float(v) for v in payload))
    if kind == "Color3uint8":
        return V(kind, tuple(int(v) for v in payload))
    if kind == "CFrame":
        (x, y, z), rows = payload
        return V(kind, (float(x), float(y), float(z), *[float(v) for row in rows for v in row]))
    if kind == "OptionalCFrame":
        if payload is None:
            return V(kind, None)
        (x, y, z), rows = payload
        return V(kind, (float(x), float(y), float(z), *[float(v) for row in rows for v in row]))
    if kind == "UDim":
        return V(kind, (float(payload[0]), int(payload[1])))
    if kind == "UDim2":
        (sx, ox), (sy, oy) = payload
        return V(kind, (float(sx), int(ox), float(sy), int(oy)))
    if kind == "Rect":
        (a, b), (c, d) = payload
        return V(kind, (float(a), float(b), float(c), float(d)))
    if kind == "NumberRange":
        return V(kind, (float(payload[0]), float(payload[1])))
    if kind in ("Float32", "Float64"):
        return V(kind, float(payload))
    if kind in ("Int32", "Int64"):
        return V(kind, int(payload))
    if kind == "Bool":
        return V(kind, bool(payload))
    if kind in ("String", "ContentId"):
        return V(kind, payload)
    if kind == "Content":
        return V(kind, _content_default(payload))
    if kind == "Font":
        family = payload.get("family") if isinstance(payload, dict) else payload[0]
        weight = payload.get("weight") if isinstance(payload, dict) else payload[1]
        style = payload.get("style") if isinstance(payload, dict) else payload[2]
        return V(kind, (family, str(weight), str(style)))
    if kind == "NumberSequence":
        keys = payload.get("keypoints") if isinstance(payload, dict) else payload[0]
        return V(kind, tuple((float(k[0]), float(k[1]), float(k[2])) for k in keys))
    if kind == "ColorSequence":
        keys = payload.get("keypoints") if isinstance(payload, dict) else payload[0]
        return V(kind, tuple((float(k[0]), *[float(c) for c in k[1]]) for k in keys))
    if kind == "PhysicalProperties":
        return V(kind, None if payload == "Default" else payload)
    if kind == "BrickColor":
        return V(kind, int(payload))
    if kind in ("Faces", "Axes"):
        return V(kind, payload)
    # Anything else keeps its raw form; the emitter names it as unmapped.
    return V(kind, payload)


def _content_default(payload):
    if payload in (None, "None") or payload == {"None": None}:
        return None
    if isinstance(payload, dict):
        if "Uri" in payload:
            return ("uri", payload["Uri"])
        if payload.get("value") in (None, "None"):
            return None
    return None


@functools.lru_cache(maxsize=1)
def reflection() -> Reflection:
    return Reflection(json.loads(gzip.decompress(DATA.read_bytes())))


def brick_color_rgb(number: int):
    from rhr.rbx.tables import BRICK_COLORS

    return BRICK_COLORS.get(number)
