"""What a cache folder holds, cheaply: one scandir, repeated only when the folder changes."""

from __future__ import annotations

import os
from pathlib import Path

# A cache folder's files, by the folder's mtime (it changes when a file is added,
# removed or renamed): root -> (mtime_ns, {suffix: {stem: (path, size, mtime_ns)}}).
_LISTINGS: dict[str, tuple[int, dict]] = {}


def listing(root: Path) -> dict[str, dict[str, tuple[Path, int, int]]]:
    """The files in `root` named `<digits>.<suffix>`, by lower-case suffix then stem.

    One scandir (on Windows its entries carry size and mtime, so no stat per file),
    and none at all while the folder is unchanged. A render used to glob, resolve and
    stat every file of every cache folder: a second per render once the cache held a
    few thousand assets.
    """
    try:
        root = Path(os.path.abspath(root))  # (resolve() is a system call per use on Windows)
        stamp = os.stat(root).st_mtime_ns
    except OSError:
        return {}
    cached = _LISTINGS.get(str(root))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    found: dict[str, dict[str, tuple[Path, int, int]]] = {}
    with os.scandir(root) as entries:
        for entry in entries:
            stem, dot, suffix = entry.name.rpartition(".")
            if not dot or not stem.isdigit():
                continue
            try:
                if not entry.is_file():
                    continue
                info = entry.stat()
            except OSError:
                continue
            found.setdefault(suffix.lower(), {})[stem] = (root / entry.name, info.st_size, info.st_mtime_ns)
    _LISTINGS[str(root)] = (stamp, found)
    return found
