"""Versioned JSON outputs.

Every JSON document RHR emits carries `"schema": "rhr.<kind>/<version>"`, so an agent
can check the shape it parses. The version changes whenever a field changes meaning
or is removed; adding a field does not change it.
"""

from __future__ import annotations

VERSIONS = {
    "ir": 1,            # rhr ir (written by src/rhr/luau/rhr-ir.luau)
    "layout": 1,        # rhr layout: {"viewport", "rects": {path: rect}}
    "layout-rich": 1,   # rhr layout --rich
    "check": 1,         # rhr check
    "hitmap": 1,        # rhr hitmap
    "scene-dump": 1,    # rhr scene-dump
    "compare": 1,       # rhr compare --json
    "browser": 1,       # rhr browser start|status|stop
}


def name(kind: str) -> str:
    return f"rhr.{kind}/{VERSIONS[kind]}"


def stamp(kind: str, payload: dict) -> dict:
    """`payload` with its schema name as the first key."""
    return {"schema": name(kind), **{key: value for key, value in payload.items() if key != "schema"}}
