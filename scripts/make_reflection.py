"""Build src/rhr/rbx/reflection.json.gz from rbx-dom's reflection database.

    uvx --with msgpack python scripts/make_reflection.py <database.msgpack>

The database is `database.msgpack` from the rbx_reflection_database crate at the
version the pinned Lune uses (Lune 0.10.5: 3.0.0+roblox-728), so RHR's own file
reader (rhr.rbx) names, types and defaults properties exactly as Lune does. Get it
with:

    curl -L -o db.crate https://static.crates.io/crates/rbx_reflection_database/rbx_reflection_database-3.0.0%2Broblox-728.crate
    tar -xzf db.crate   # rbx_reflection_database-3.0.0+roblox-728/database.msgpack

Kept: every class with its superclass and every property's type and serialization
(so any property a file holds is named as Lune names it), defaults for the
properties RHR reads (rhr.rbx.props.PROPS and their `...Content` / migration
targets), and every enum.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import msgpack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rhr.rbx.props import CONTENT_PROPERTY_ALIASES, PROPS  # noqa: E402

OUT = ROOT / "src" / "rhr" / "rbx" / "reflection.json.gz"


def variant(value):
    """A default value, as {type: value} with JSON-friendly payloads."""
    (kind, payload), = value.items()
    return [kind, payload]


def main() -> int:
    raw = msgpack.unpackb(Path(sys.argv[1]).read_bytes(), raw=False, strict_map_key=False)
    version, classes, enums = raw[0], raw[1], raw[2]
    wanted_defaults = set(PROPS) | set(CONTENT_PROPERTY_ALIASES.values()) | {f"{name}Content" for name in PROPS}
    out_classes = {}
    for name, (_, tags, superclass, properties, defaults) in classes.items():
        props = {}
        for pname, (_, _scriptability, data_type, _ptags, kind) in properties.items():
            (dt_kind, dt_value), = data_type.items()
            ty = f"E:{dt_value}" if dt_kind == "Enum" else f"V:{dt_value}"
            if "Alias" in kind:
                ser = ["A", kind["Alias"][0]]
            else:
                serialization = kind["Canonical"][0]
                if serialization == "Serializes":
                    ser = ["S"]
                elif serialization == "DoesNotSerialize":
                    ser = ["N"]
                elif "SerializesAs" in serialization:
                    ser = ["AS", serialization["SerializesAs"]]
                elif "Migrate" in serialization:
                    ser = ["M", *serialization["Migrate"]]
                else:
                    raise ValueError(f"{name}.{pname}: unknown serialization {serialization!r}")
            props[pname] = [ty, *ser]
        kept_defaults = {p: variant(v) for p, v in (defaults or {}).items() if p in wanted_defaults}
        out_classes[name] = {"super": superclass, "tags": tags, "props": props, "defaults": kept_defaults}
    document = {
        "version": ".".join(str(part) for part in version),
        "classes": out_classes,
        "enums": {name: items for name, (_, items) in enums.items()},
    }
    data = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    OUT.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    print(f"{OUT}: {len(out_classes)} classes, {len(document['enums'])} enums, "
          f"{len(data) / 1e6:.1f} MB -> {OUT.stat().st_size / 1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
