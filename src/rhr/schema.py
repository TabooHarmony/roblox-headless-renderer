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
    "compare": 2,       # rhr compare (2: camelCase keys, before/after instead of ref/out)
    "browser": 1,       # rhr browser start|status|stop
    "render": 1,        # rhr ui|scene|preview --json: the picture's report
    "inspect": 1,       # rhr inspect: what a file holds, its scripts and findings
}


def name(kind: str) -> str:
    return f"rhr.{kind}/{VERSIONS[kind]}"


def dumps(document: dict) -> str:
    """How every JSON document is written: compact (agents read it; whitespace only
    costs time and tokens), sorted keys so two runs diff cleanly, UTF-8 text."""
    import json

    return json.dumps(document, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def stamp(kind: str, payload: dict) -> dict:
    """`payload` with its schema name as the first key."""
    return {"schema": name(kind), **{key: value for key, value in payload.items() if key != "schema"}}
