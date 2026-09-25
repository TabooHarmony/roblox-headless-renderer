"""RHR's cache on disk: how big each part is, clearing it, and keeping it under a limit.

The cache holds downloaded images, meshes, unions and material maps, converted Studio
textures and IR conversions. It is only a cache: anything removed is downloaded or
converted again when needed. The pinned tools (`bin`) and the warm worker's session
are never pruned or cleared by `--clear all`.

At most once a day, a command checks the total; above `RHR_CACHE_LIMIT_MB` (default
2048, 0 = no limit) the least recently used files go first, until it is 80% of the
limit. Files used in the last hour stay.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from rhr.paths import CACHE

AREAS = {
    "images": CACHE / "cache" / "icons",
    "meshes": CACHE / "cache" / "meshes",
    "unions": CACHE / "cache" / "unions",
    "materials": CACHE / "cache" / "materials",
    "particles": CACHE / "cache" / "particles",
    "studio": CACHE / "cache" / "studio",
    "ir": CACHE / "ir",
}
PRUNE_STAMP = CACHE / "cache" / ".last-prune"
DAY = 24 * 3600


def _files(root: Path):
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                yield entry


def sizes() -> dict[str, int]:
    """Bytes held by each area (missing areas are 0)."""
    return {name: sum(entry.stat().st_size for entry in _files(path)) for name, path in AREAS.items()}


def clear(area: str) -> int:
    """Remove one area (or every area with "all"); returns the bytes freed."""
    names = list(AREAS) if area == "all" else [area]
    freed = 0
    for name in names:
        if name not in AREAS:
            raise ValueError(f"unknown cache area {name!r}; one of: all, {', '.join(AREAS)}")
        path = AREAS[name]
        freed += sum(entry.stat().st_size for entry in _files(path))
        shutil.rmtree(path, ignore_errors=True)
    return freed


def limit_bytes() -> int:
    try:
        return int(float(os.environ.get("RHR_CACHE_LIMIT_MB", "2048")) * 1024 * 1024)
    except ValueError:
        return 2048 * 1024 * 1024


def prune(limit: int | None = None, *, keep_recent_s: float = 3600) -> int:
    """Remove least recently used files until the total is under 80% of `limit`.

    Returns the bytes freed. "Used" is the later of a file's access and modification
    times; files used within `keep_recent_s` are never removed.
    """
    limit = limit_bytes() if limit is None else limit
    if limit <= 0:
        return 0
    entries = [entry for path in AREAS.values() for entry in _files(path)]
    total = sum(entry.stat().st_size for entry in entries)
    if total <= limit:
        return 0
    now = time.time()
    target = int(limit * 0.8)
    freed = 0
    for entry in sorted(entries, key=lambda e: max(e.stat().st_atime, e.stat().st_mtime)):
        if total - freed <= target:
            break
        info = entry.stat()
        if now - max(info.st_atime, info.st_mtime) < keep_recent_s:
            continue
        try:
            os.remove(entry.path)
            freed += info.st_size
        except OSError:
            pass
    return freed


def maybe_prune() -> None:
    """Prune at most once a day; never fails a command."""
    try:
        if PRUNE_STAMP.is_file() and time.time() - PRUNE_STAMP.stat().st_mtime < DAY:
            return
        PRUNE_STAMP.parent.mkdir(parents=True, exist_ok=True)
        PRUNE_STAMP.touch()
        prune()
    except OSError:
        pass
