"""The IR of a binary Roblox file, as luau/rhr-ir.luau writes it through Lune.

A port of that emitter onto rhr.rbx.binary: the same instances, ids, paths, profiles
and property values, with each property read the way Lune's `instance[name]` reads it
(lune-roblox 0.3.5: the stored value, else the class default, else an error), and the
emitter's fallbacks after a failed read (the `...Content` name, then the property's
text in the instance's XML form) reproduced from what rbx-dom stores. Same output,
without a property-by-property trip through Luau: a 116k-part place reads in seconds
instead of minutes.
"""

from __future__ import annotations

import base64
import math

import numpy as np

from rhr.rbx.binary import Document, Instance, V
from rhr.rbx.props import (ATTRIBUTE_CLASSES, CONTENT_PROPERTY_ALIASES, GUI_CLASSES, PROPS, VISUAL_CLASSES,
                           VISUAL_XML_RECOVERY)
from rhr.rbx.reflection import Reflection, reflection

PROPS_SET = frozenset(PROPS)


# Lune's Color3 from a byte: the 32-bit float byte / 255.
_BYTE_TO_UNIT = [float(np.float32(i) / np.float32(255.0)) for i in range(256)]
_SKIP = object()  # a direct column value that leaves the property out (an empty Content)


class ReadError(Exception):
    """What a failed `instance[name]` raises in Lune."""


class _Child:
    """`instance[name]` answered with a child of that name (typeof "Instance")."""

    def __init__(self, instance: Instance):
        self.instance = instance


class _Ref:
    """A Ref property's target instance (typeof "Instance")."""

    def __init__(self, instance: Instance):
        self.instance = instance


def _f32(value: float) -> float:
    return float(np.float32(value))


def _nn(n):
    """A number as Lune's JSON writes it: infinity and NaN become null."""
    if isinstance(n, float) and (n != n or n in (math.inf, -math.inf)):
        return None
    return n


def _finite(n: float) -> float:
    if n != n or n in (math.inf, -math.inf):
        return 1e6
    return n


class Emitter:
    def __init__(self, doc: Document, profile: str, db: Reflection):
        self.doc = doc
        self.profile = profile
        # "ui" is "full" for the nodes it keeps: GUI subtrees and what holds them.
        self.full = profile in ("full", "ui")
        self.db = db
        self.ids: dict[int, int] = {}
        self.paths: dict[int, str] = {}
        self.keep: dict[int, bool] = {}
        self._valid: dict[str, frozenset] = {}
        self._unknown: set[str] = set()
        self._xml_present: dict[str, frozenset] = {}
        self._plans: dict[str, list] = {}
        self._canonical_names: dict[tuple, str | None] = {}
        self.inside_ui: set[int] = set()  # "ui": instances in a GUI subtree (emitted whole)
        self.skeleton: set[int] = set()   # "world": stored nodes kept for their paths only
        self.gui_stubs: set[int] = set()  # "world": stored ScreenGuis, children as stubs
        self.stored_roots: list[Instance] = []
        self.unreadable_nodes = 0
        self.unreadable_names: dict[str, int] = {}
        self.unmapped_nodes = 0
        self.unmapped_names: dict[str, int] = {}
        self.collision_nodes = 0

    # --- identity and profiles ---------------------------------------------------

    def assign_identity(self) -> None:
        """Ids in pre-order from 1; paths with every shared sibling name indexed."""
        next_id = 0

        def run(instances, parent_path):
            nonlocal next_id
            counts: dict[str, int] = {}
            for inst in instances:
                name = inst.name if inst.name != "" else inst.class_name
                counts[name] = counts.get(name, 0) + 1
            seen: dict[str, int] = {}
            for inst in instances:
                name = inst.name if inst.name != "" else inst.class_name
                segment = name
                if counts[name] > 1:
                    seen[name] = seen.get(name, 0) + 1
                    segment = f"{name}[{seen[name]}]"
                next_id += 1
                self.ids[inst.index] = next_id
                here = segment if parent_path == "" else f"{parent_path}/{segment}"
                self.paths[inst.index] = here
                if inst.children:
                    run(inst.children, here)

        run(self.doc.roots, "")

    def mark(self) -> None:
        def rec(inst: Instance) -> bool:
            keep = inst.class_name in VISUAL_CLASSES
            for child in inst.children:
                keep = rec(child) or keep
            self.keep[inst.index] = keep
            return keep
        for root in self.doc.roots:
            rec(root)

    def mark_world(self) -> None:
        """The "world" profile: what a 3D view of a place draws. The world as "static"
        keeps it; of the storage services (maps in ServerStorage, templates) only their
        ScreenGuis, with stub children, for the note naming stored ScreenGuis. What the
        storage holds is summed up in the document's storedNote instead."""
        from rhr.ir import PLACE_ROOTS, STORED_SERVICES

        place = any(root.class_name in PLACE_ROOTS for root in self.doc.roots)

        def visual(inst: Instance) -> bool:
            keep = inst.class_name in VISUAL_CLASSES
            for child in inst.children:
                keep = visual(child) or keep
            self.keep[inst.index] = keep
            return keep

        def stored(inst: Instance) -> bool:
            if inst.class_name == "ScreenGui":
                self.keep[inst.index] = True
                self.gui_stubs.add(inst.index)
                return True
            keep = False
            for child in inst.children:
                keep = stored(child) or keep
            self.keep[inst.index] = keep
            self.skeleton.add(inst.index)
            return keep

        for root in self.doc.roots:
            if place and root.class_name in STORED_SERVICES:
                self.stored_roots.append(root)
                stored(root)
            else:
                visual(root)

    def stored_note(self) -> str | None:
        """rhr.ir.stored_note for the storage services the "world" profile left out."""
        from rhr.ir import stored_note

        # The same tree a "static" IR holds there (visual classes and what holds them),
        # so the note counts what it always counted.
        def light(inst: Instance) -> dict | None:
            children = [node for node in (light(child) for child in inst.children) if node is not None]
            if not children and inst.class_name not in VISUAL_CLASSES:
                return None
            return {"className": inst.class_name, "path": self.paths[inst.index], "children": children}

        return stored_note([node for node in (light(root) for root in self.stored_roots) if node is not None])

    def mark_ui(self) -> None:
        """Keep GUI nodes with everything below them, the nodes above them, and roots."""
        def rec(inst: Instance, inside: bool) -> bool:
            inside = inside or inst.class_name in GUI_CLASSES
            keep = inside
            if inside:
                self.inside_ui.add(inst.index)
            for child in inst.children:
                keep = rec(child, inside) or keep
            self.keep[inst.index] = keep
            return keep
        for root in self.doc.roots:
            rec(root, False)
            self.keep[root.index] = True

    # --- what the Luau emitter reads ------------------------------------------------

    def valid(self, class_name: str) -> frozenset:
        """class_property_set: the database's names for the class, or every allowlisted
        name for a class the database does not know."""
        cached = self._valid.get(class_name)
        if cached is None:
            names = self.db.property_names(class_name)
            chain = [name for name, _ in self.db.chain(class_name)]
            if not chain or chain[-1] not in ("Instance", "Object"):
                cached = PROPS_SET
                self._unknown.add(class_name)
            else:
                cached = frozenset(names)
            self._valid[class_name] = cached
        return cached

    def lune_get(self, inst: Instance, name: str):
        """lune-roblox's instance_property_get, for a property name."""
        if name == "Name":
            return inst.name
        info = self.db.property_info(inst.class_name, name)
        if info is not None:
            value = inst.get(name)
            if value is not None:
                return self._to_lua(inst, name, value, info.enum)
            if info.enum is not None:
                default = info.default
                if default is not None and default.kind == "Enum":
                    return self._enum_item(info.enum, default.value, name)
                raise ReadError("malformed property info")
            if info.default is not None:
                return self._to_lua(inst, name, info.default, None)
            if info.value_type is not None:
                if info.value_type == "Ref":
                    return None
                raise ReadError(f"Failed to get property '{name}' - missing default value")
            raise ReadError("malformed property info")
        for child in inst.children:
            if child.name == name:
                return _Child(child)
        raise ReadError(f"{name} is not a valid member")

    def _enum_item(self, enum: str, value: int, name: str):
        items = self.db.enum_names.get(enum)
        if items is None or value not in items:
            raise ReadError(f"Failed to get property '{name}' - Enum.{enum} does not contain numeric value {value}")
        return ("EnumItem", enum, items[value], value)

    def _to_lua(self, inst: Instance, name: str, value: V, enum: str | None):
        """LuaValue::dom_value_to_lua, as a tagged Python value."""
        kind = value.kind
        if kind == "Enum":
            if enum is None:
                raise ReadError(f"Failed to get property '{name}' - encountered unknown enum")
            return self._enum_item(enum, value.value, name)
        if kind == "Ref":
            target = self.doc.by_referent.get(value.value) if value.value is not None else None
            return _Ref(target) if target is not None else None
        if kind in ("Bool", "String", "ContentId", "BinaryString", "SharedString"):
            return value.value
        if kind in ("Int32", "Int64", "Float32", "Float64"):
            return value.value
        if kind == "OptionalCFrame":
            return None if value.value is None else V("CFrame", value.value)
        if kind == "PhysicalProperties":
            return None if value.value is None else value
        if kind in ("Tags", "Attributes", "MaterialColors", "NetAssetRef", "SecurityCapabilities"):
            raise ReadError(f"Failed to get property '{name}' - unsupported type {kind}")
        return value

    # --- conversion to the IR (conv) ---------------------------------------------

    def conv(self, v, depth: int = 0):
        if v is None or depth > 5:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return _nn(v)
        if isinstance(v, str):
            return v
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        if isinstance(v, tuple) and v and v[0] == "EnumItem":
            return {"enum": f"Enum.{v[1]}", "name": v[2], "value": v[3], "_t": "EnumItem"}
        if not isinstance(v, V):
            return None
        kind, x = v.kind, v.value
        if kind == "Vector2":
            return {"X": _finite(x[0]), "Y": _finite(x[1]), "_t": "Vector2"}
        if kind == "Vector3":
            return {"X": _finite(x[0]), "Y": _finite(x[1]), "Z": _finite(x[2]), "_t": "Vector3"}
        if kind == "CFrame":
            keys = ("X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
            return {**dict(zip(keys, map(_nn, x))), "_t": "CFrame"}
        if kind == "UDim":
            return {"Scale": _nn(x[0]), "Offset": x[1], "_t": "UDim"}
        if kind == "UDim2":
            return {"XS": _nn(x[0]), "XO": x[1], "YS": _nn(x[2]), "YO": x[3], "_t": "UDim2"}
        if kind == "Color3":
            return {"R": _nn(x[0]), "G": _nn(x[1]), "B": _nn(x[2]), "_t": "Color3"}
        if kind == "Color3uint8":
            return {"R": _BYTE_TO_UNIT[x[0]], "G": _BYTE_TO_UNIT[x[1]], "B": _BYTE_TO_UNIT[x[2]], "_t": "Color3"}
        if kind == "Rect":
            return {"Min": {"X": _finite(x[0]), "Y": _finite(x[1]), "_t": "Vector2"},
                    "Max": {"X": _finite(x[2]), "Y": _finite(x[3]), "_t": "Vector2"}, "_t": "Rect"}
        if kind == "NumberRange":
            return {"Min": _nn(x[0]), "Max": _nn(x[1]), "_t": "NumberRange"}
        if kind == "Font":
            family, weight, style = x[0], x[1], x[2]
            return {"family": family, "weight": f"Enum.FontWeight.{weight}",
                    "style": f"Enum.FontStyle.{style}", "_t": "Font"}
        if kind == "NumberSequence":
            return {"kind": "NumberSequence", "keypoints": [
                {"Time": _nn(t), "Value": _nn(val), "Envelope": _nn(env)} for t, val, env in x], "_t": "NumberSequence"}
        if kind == "ColorSequence":
            return {"kind": "ColorSequence", "keypoints": [
                {"Time": _nn(t), "Value": {"R": _nn(r), "G": _nn(g), "B": _nn(b), "_t": "Color3"}} for t, r, g, b in x],
                "_t": "ColorSequence"}
        if kind == "Content":
            if x is None or x[0] != "uri" or x[1] == "":
                return None
            return x[1]
        return None

    @staticmethod
    def lua_typeof(v) -> str:
        if isinstance(v, (_Child, _Ref)):
            return "Instance"
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, (str, bytes)):
            return "string"
        if isinstance(v, tuple) and v and v[0] == "EnumItem":
            return "EnumItem"
        if isinstance(v, V):
            return {"Color3uint8": "Color3"}.get(v.kind, v.kind)
        return "nil"

    # --- the XML view, for names the bridge will not hand over --------------------

    def xml_present(self, inst: Instance) -> frozenset:
        """The names an instance's XML form carries: its stored properties, each
        under the name it serializes as (one set per class in a binary file)."""
        cached = self._xml_present.get(inst.class_name)
        if cached is None:
            names = {"Name"}
            for canonical in inst.names():
                serialized = self.db.serialized_name(inst.class_name, canonical)
                if serialized is not None:
                    names.add(serialized)
            cached = frozenset(names)
            self._xml_present[inst.class_name] = cached
        return cached

    def xml_value(self, inst: Instance, name: str):
        """(found, present) for `name` in the instance's XML form: the recovered value
        as rhr-ir.luau's from_xml gives it, or None when the XML holds no plain text."""
        if name not in self.xml_present(inst):
            return None, False
        canonical = self._canonical_for_serialized(inst, name)
        if canonical is None:
            return None, True
        return _xml_found(inst.get(canonical), self.doc), True

    def _canonical_for_serialized(self, inst: Instance, serialized: str) -> str | None:
        if serialized == "Name":
            return None
        # The same for every instance of a class group (they share its columns).
        key = (id(inst.group), serialized)
        if key not in self._canonical_names:
            self._canonical_names[key] = next(
                (canonical for canonical in inst.names()
                 if self.db.serialized_name(inst.class_name, canonical) == serialized), None)
        return self._canonical_names[key]

    # --- the walk -------------------------------------------------------------------

    def resolve(self, inst: Instance, name: str, valid: frozenset, child_named: dict):
        """One allowlisted name, exactly as the Luau loop body handles it. Returns
        (action, value, ref id): "prop", "unmapped", "notprop", "unreadable" or None."""
        ok, value, child_fallback = False, None, None
        ref_id = None
        if name in valid:
            try:
                value = self.lune_get(inst, name)
                ok = True
            except ReadError:
                ok = False
        else:
            child_fallback = child_named.get(name)
        if value is not None and self.lua_typeof(value) == "Instance":
            if name in ("Adornee", "Attachment0", "Attachment1", "PrimaryPart"):
                target = value.instance
                ref_id = ("ref", self.ids.get(target.index))
                value = self._full_name(target)
            else:
                child_fallback = value.instance.class_name
                value = None
        if name in valid and (not ok or value is None):
            content_name = CONTENT_PROPERTY_ALIASES.get(name) or f"{name}Content"
            try:
                value2 = self.lune_get(inst, content_name)
                ok2 = True
            except ReadError:
                ok2 = False
            if ok2 and value2 is not None and self.lua_typeof(value2) != "Instance":
                ok, value, child_fallback = True, value2, None
        if ok and value is not None:
            converted = self.conv(value)
            if converted is None and isinstance(value, float) and not isinstance(value, bool):
                return "prop", None, ref_id  # a non-finite number: Lune writes null
            if converted is not None:
                return "prop", converted, ref_id
            if self.lua_typeof(value) != "Content":
                return "unmapped", f"{name} ({self.lua_typeof(value)})", ref_id
            return None, None, ref_id
        if child_fallback:
            return "notprop", f"{name} (child {child_fallback})", ref_id
        if self.full or name in VISUAL_XML_RECOVERY:
            found, present = self.xml_value(inst, name)
            if found is not None:
                return "prop", found, ref_id
            if self.full and present:
                return "unreadable", name, ref_id
        return None, None, ref_id

    def _direct_column(self, column, enum: str | None):
        """The IR values of a whole stored column, when every one of them goes the
        plain way (read, convert, keep): simple types Lune always hands over. Other
        columns (references, optional values, types that may fail) return None and are
        resolved one value at a time."""
        raw = column.raw()
        if raw is None:
            return None
        kind, values = raw
        if kind == "Enum":
            if enum is None:
                return None
            items = self.db.enum_names.get(enum) or {}
            cache = {}
            out = []
            for v in values:
                item = cache.get(v)
                if item is None:
                    if v not in items:
                        return None
                    item = cache[v] = {"enum": f"Enum.{enum}", "name": items[v], "value": v, "_t": "EnumItem"}
                out.append(item)
            return out
        if kind in ("Bool", "Int32", "Int64", "String", "ContentId"):
            return list(values)
        if kind in ("Float32", "Float64"):
            return [_nn(v) for v in values]
        if kind == "BinaryString":
            return [v.decode("utf-8", errors="replace") for v in values]
        if kind == "Content":
            return [v[1] if v is not None and v[0] == "uri" and v[1] != "" else _SKIP for v in values]
        if kind == "Vector3":
            return [{"X": _finite(x), "Y": _finite(y), "Z": _finite(z), "_t": "Vector3"} for x, y, z in values]
        if kind == "CFrame":
            nn = _nn
            isfinite = math.isfinite
            out = []
            for c in values:
                if not isfinite(sum(c)):
                    c = [nn(v) for v in c]
                out.append({"X": c[0], "Y": c[1], "Z": c[2], "R00": c[3], "R01": c[4], "R02": c[5],
                            "R10": c[6], "R11": c[7], "R12": c[8], "R20": c[9], "R21": c[10],
                            "R22": c[11], "_t": "CFrame"})
            return out
        if kind == "Color3uint8":
            t = _BYTE_TO_UNIT
            return [{"R": t[r], "G": t[g], "B": t[b], "_t": "Color3"} for r, g, b in values]
        if kind in ("Vector2", "UDim", "UDim2", "Color3", "Rect", "NumberRange", "Font",
                    "NumberSequence", "ColorSequence"):
            conv = self.conv
            return [conv(V(kind, v)) for v in values]
        return None

    def _direct_plan(self, inst: Instance, name: str, content_name: str, columns: dict, present: frozenset):
        """A whole column of IR values for `name` on this class, when the path the Luau
        loop takes is the same for every instance and ends in a stored column: the name
        itself; its `...Content` sibling when the name cannot be read (a legacy asset id,
        a velocity saved under its old name); or the text of the column it serializes
        from (a legacy alias such as `shape`). None: resolve instance by instance."""
        cls = inst.class_name
        info = self.db.property_info(cls, name)
        if info is None:
            return None
        if name in columns:
            return self._direct_column(columns[name], info.enum)
        # The name is not stored: its read is the same for every instance (a default,
        # nothing, or an error).
        try:
            first = self.lune_get(inst, name)
        except ReadError:
            first = None
        if first is not None:
            return None  # a default: constant, handled by the per-class cache
        content_info = self.db.property_info(cls, content_name)
        if content_info is not None:
            if content_name in columns:
                return self._direct_column(columns[content_name], content_info.enum)
            return None
        # Neither reads (the `...Content` name is not a property: without a child of
        # that name, an error): the XML fallback.
        if not (self.full or name in VISUAL_XML_RECOVERY) or name not in present:
            return None
        canonical = self._canonical_for_serialized(inst, name)
        if canonical is None or canonical not in columns:
            return None
        raw = columns[canonical].raw()
        if raw is None:
            return None
        kind, values = raw
        out = []
        for value in values:
            found = _xml_found(V(kind, value), self.doc)
            if found is None:
                return None  # would be unreadable for some: keep the exact path
            out.append(found)
        return out

    def plan(self, inst: Instance, valid: frozenset) -> list:
        """Per class: the allowlisted names worth visiting, in allowlist order, each with
        whether its outcome can differ between instances of the class. A name that is not
        a property and not in the class's XML form yields nothing (unless a child has
        that name: such instances take the full loop)."""
        cached = self._plans.get(inst.class_name)
        if cached is not None:
            return cached
        columns = inst.group.columns
        present = self.xml_present(inst)
        unknown = inst.class_name in self._unknown
        entries = []
        for name in PROPS:
            if name not in valid and not (self.full or name in VISUAL_XML_RECOVERY):
                continue
            if name not in valid and name not in present:
                continue
            content_name = CONTENT_PROPERTY_ALIASES.get(name) or f"{name}Content"
            # Name is not a stored column (the file keeps it apart), but differs per instance.
            varies = (unknown or name == "Name" or name in columns or content_name in columns
                      or (name in present and self._canonical_for_serialized(inst, name) in columns))
            direct = None
            if not unknown and name in valid:
                direct = self._direct_plan(inst, name, content_name, columns, present)
            entries.append([name, content_name, varies, None, direct])
        self._plans[inst.class_name] = entries
        return entries

    def walk(self, inst: Instance):
        if self.profile != "full" and not self.keep.get(inst.index):
            return None
        node = {"id": self.ids[inst.index], "path": self.paths[inst.index],
                "className": inst.class_name, "name": inst.name}
        if (not self.full and inst.class_name not in VISUAL_CLASSES) or (
                self.profile == "ui" and inst.index not in self.inside_ui) or inst.index in self.skeleton:
            # (a "ui" IR keeps what holds the UI for its paths only: a SurfaceGui's Part
            # would otherwise read every Part column of a 100k-part place)
            node["props"] = {}
            node["children"] = [c for c in (self.walk(child) for child in inst.children) if c is not None]
            return node
        valid = self.valid(inst.class_name)
        child_named = {}
        child_names = set()
        for child in inst.children:
            child_names.add(child.name)
            if child.name in PROPS_SET and child.name not in valid:
                child_named[child.name] = child.class_name
        props: dict = {}
        refs: dict = {}
        unmapped: list[str] = []
        not_a_property: list[str] = []
        unreadable: list[str] = []
        if child_named:
            steps = [(name, None) for name in PROPS]  # rare: the full loop, uncached
        else:
            steps = [(entry[0], entry) for entry in self.plan(inst, valid)]
        position = inst.position
        for name, entry in steps:
            if entry is not None and entry[4] is not None:
                value = entry[4][position]
                if value is not _SKIP:
                    props[name] = value
                continue
            if entry is not None and not entry[2] and entry[1] not in child_names:
                outcome = entry[3]
                if outcome is None:
                    outcome = entry[3] = self.resolve(inst, name, valid, child_named)
            else:
                outcome = self.resolve(inst, name, valid, child_named)
            action, value, ref = outcome
            if ref is not None:
                refs[name] = ref[1]
            if action == "prop":
                props[name] = value
            elif action == "unmapped":
                unmapped.append(value)
            elif action == "notprop":
                not_a_property.append(value)
            elif action == "unreadable":
                unreadable.append(value)
        if inst.class_name == "UnionOperation" and props.get("AssetId") in (None, ""):
            mesh = inst.get("MeshData2")
            if mesh is not None and isinstance(mesh.value, bytes) and 0 < len(mesh.value) < 16 * 1024 * 1024:
                props["MeshData2"] = base64.b64encode(mesh.value).decode("ascii")
        node["props"] = props
        node["children"] = []
        if refs:
            node["refs"] = refs
        if inst.class_name in ATTRIBUTE_CLASSES:
            kept = _attributes(inst)
            if kept:
                node["attributes"] = kept
        if unreadable:
            node["unreadable"] = unreadable
        if unmapped:
            node["unmapped"] = unmapped
        if not_a_property:
            node["not_a_property"] = not_a_property
        if inst.index in self.gui_stubs:
            node["children"] = [{"id": self.ids[child.index], "path": self.paths[child.index],
                                 "className": child.class_name, "name": child.name, "props": {}, "children": []}
                                for child in inst.children]
            return node
        for child in inst.children:
            child_node = self.walk(child)
            if child_node is not None:
                node["children"].append(child_node)
        return node

    def _full_name(self, inst: Instance) -> str:
        """GetFullName(): names joined by dots up to (not including) the DataModel."""
        parts = []
        while inst is not None:
            parts.append(inst.name)
            inst = inst.parent
        return ".".join(reversed(parts))


# --- XML text of stored values (rbx_xml 3.0), for the fallback ------------------------

_XML_TAGS = {
    "String": "string", "Bool": "bool", "Int32": "int", "Int64": "int64", "Float32": "float",
    "Float64": "double", "Enum": "token", "Ref": "Ref", "BinaryString": "BinaryString",
    "Color3uint8": "Color3uint8", "BrickColor": "int", "SharedString": "SharedString",
    "ContentId": "Content",
}


def _xml_text(value: V | None, doc: Document) -> str | None:
    """A stored value's plain text in rbx_xml's output, or None for values written as
    nested elements (the emitter's pattern does not match those)."""
    if value is None:
        return None
    kind, x = value.kind, value.value
    if kind == "Enum":
        return str(x)
    if kind == "Ref":
        return "null" if x is None or x not in doc.by_referent else f"RBX{x}"
    if kind == "Bool":
        return "true" if x else "false"
    if kind in ("Int32", "Int64", "BrickColor"):
        return str(x)
    if kind in ("Float32", "Float64"):
        return repr(float(x))
    if kind == "String":
        return x
    if kind == "Color3uint8":
        r, g, b = x
        return str(0xFF000000 | (r << 16) | (g << 8) | b)
    # A BinaryString is written as base64 inside CDATA, which the emitter's
    # text pattern does not match: present, but no plain text.
    return None


def _xml_found(value: V | None, doc: Document):
    """A stored value as rhr-ir.luau's from_xml recovers it from its XML text, or None
    when the XML holds no plain text for it (or an empty one)."""
    text = _xml_text(value, doc)
    if text is None or text == "":
        return None
    tag = _XML_TAGS.get(value.kind)
    if tag == "bool":
        return text == "true"
    if tag in ("int", "int64", "float", "double"):
        try:
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            return None
    return text


def _attributes(inst: Instance) -> dict:
    """GetAttributes(), numbers and switches only (the effect-playing convention)."""
    stored = inst.get("Attributes")
    if stored is None or not isinstance(stored.value, bytes):
        return {}
    try:
        values = decode_attributes(stored.value)
    except (ValueError, IndexError, UnicodeDecodeError):
        return {}
    kept = {}
    for key, value in values.items():
        if isinstance(value, bool):
            kept[key] = value
        elif isinstance(value, (int, float)):
            kept[key] = _finite(value)
    return kept


def decode_attributes(data: bytes) -> dict:
    """rbx_types' attribute encoding; numbers and booleans as Python values, the rest
    as None (they are read past, not kept)."""
    import struct

    o = 0

    def take(fmt):
        nonlocal o
        value = struct.unpack_from(fmt, data, o)
        o += struct.calcsize(fmt)
        return value

    def string():
        nonlocal o
        (n,) = take("<I")
        s = data[o:o + n]
        o += n
        return s

    out: dict = {}
    if len(data) < 4:
        return out
    (count,) = take("<I")
    for _ in range(count):
        key = string().decode("utf-8")
        (ty,) = take("<B")
        if ty == 0x02:
            string(); value = None
        elif ty == 0x03:
            value = take("<B")[0] != 0
        elif ty == 0x04:
            value = take("<i")[0]
        elif ty == 0x05:
            value = _f32(take("<f")[0])
        elif ty == 0x06:
            value = take("<d")[0]
        elif ty == 0x09:
            take("<fi"); value = None
        elif ty == 0x0A:
            take("<fifi"); value = None
        elif ty == 0x0E:
            take("<I"); value = None
        elif ty == 0x0F:
            take("<fff"); value = None
        elif ty == 0x10:
            take("<ff"); value = None
        elif ty == 0x11:
            take("<fff"); value = None
        elif ty == 0x14:
            take("<fff")
            (rid,) = take("<B")
            if rid == 0:
                take("<9f")
            value = None
        elif ty == 0x15:
            string(); take("<I"); value = None
        elif ty == 0x17:
            (n,) = take("<I"); take(f"<{3 * n}f"); value = None
        elif ty == 0x19:
            (n,) = take("<I"); take(f"<{5 * n}f"); value = None
        elif ty == 0x1B:
            take("<ff"); value = None
        elif ty == 0x1C:
            take("<ffff"); value = None
        elif ty == 0x21:
            take("<HB"); string(); string(); value = None
        else:
            raise ValueError(f"unknown attribute type {ty}")
        out[key] = value
    return out


def emit(doc: Document, *, profile: str = "full", source_path: str = "", db: Reflection | None = None):
    """(IR document, report lines) for a decoded binary file."""
    import sys

    db = db or reflection()
    emitter = Emitter(doc, profile, db)
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 50_000))  # trees are walked recursively, as in Luau
    try:
        emitter.assign_identity()
        if profile == "ui":
            emitter.mark_ui()
        elif profile == "world":
            emitter.mark_world()
        elif profile != "full":
            emitter.mark()
        nodes = [n for n in (emitter.walk(root) for root in doc.roots) if n is not None]
        document = {"schema": "rhr.ir/1", "sourcePath": source_path, "roots": nodes}
        if profile == "world":
            document["storedNote"] = emitter.stored_note()
    finally:
        sys.setrecursionlimit(limit)
    report = _report(nodes, emitter, len(emitter.ids))
    return document, report


def _report(nodes: list[dict], emitter: Emitter, instance_count: int) -> list[str]:
    names: dict[str, int] = {}
    unmapped_names: dict[str, int] = {}
    affected = unmapped_nodes = collisions = 0
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if node.get("unreadable"):
            affected += 1
            for name in node["unreadable"]:
                names[name] = names.get(name, 0) + 1
        if node.get("unmapped"):
            unmapped_nodes += 1
            for name in node["unmapped"]:
                unmapped_names[name] = unmapped_names.get(name, 0) + 1
        if node.get("not_a_property"):
            collisions += 1
        stack.extend(node.get("children") or [])

    def tally(counts):
        return ", ".join(sorted(f"{name}x{n}" for name, n in counts.items()))

    unknown = len(emitter._unknown)
    return [
        f"unreadable: {affected} nodes" + (f", {tally(names)}" if names else ""),
        f"unmapped: {unmapped_nodes} nodes" + (f", {tally(unmapped_names)}" if unmapped_names else ""),
        f"name collisions: {collisions} nodes",
        f"class filter: {instance_count} instances over 0 database mismatches"
        + (f", {unknown} class(es) not in the database read in full" if unknown else ""),
    ]
