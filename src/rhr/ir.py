"""Our IR: the full-fidelity tree extracted by lune + rbx-dom, as JSON on disk.

Shape (written by src/rhr/luau/rhr-ir.luau):

    {"sourcePath": "...", "roots": [node, ...]}
    node = {"className", "name", "props": {prop: {"_t": <datatype>, ...}}, "children": [...]}

The point of this file, versus pinevex's bundled Python parser, is that rbx-dom
knows every property and its real datatype, so nothing is silently dropped and
enums arrive as names instead of raw ints.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from rhr.paths import LUAU_IR_SCRIPT
from rhr.procs import no_window

def lune_executable() -> str:
    """Path to `lune` (downloaded the first time), or a RuntimeError that says how to
    install it."""
    from rhr.profile import phase
    from rhr.tools import require

    with phase("find lune"):
        return require("lune", "to read Roblox files")


# The IRs read in this process, most recent last: resolved path -> (path, size, mtime),
# the document, its size on disk. A render reads the same IR in several places
# (downloads, unions, content, notes, in-world UI), and the resident server answers
# command after command about the same few files (the "ui" IR for layout and check,
# the "world" IR for scene): a big place's IR is seconds to parse. Callers only read it.
# Kept: up to _KEEP files and _KEEP_BYTES of JSON (in memory about 4.5x that), the
# newest always.
_LOADED: dict[str, tuple[tuple, dict, int]] = {}
_KEEP = 4
_KEEP_BYTES = 450_000_000


def _ir_key(path) -> tuple:
    path = Path(path).resolve()
    info = path.stat()
    return (str(path), info.st_size, info.st_mtime_ns)


def load_ir(path) -> dict:
    """Read an IR JSON file (written by rhr.rbx or src/rhr/luau/rhr-ir.luau), once
    per process while the file is unchanged. The result is shared: do not modify it."""
    key = _ir_key(path)
    cached = _LOADED.get(key[0])
    if cached is not None and cached[0] == key:
        _LOADED[key[0]] = _LOADED.pop(key[0])  # most recent last
        return cached[1]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "roots" not in data:
        raise ValueError(f"{path} is not an IR file: no 'roots' key")
    ensure_paths(data["roots"])
    _keep(key, data)
    return data


def _remember_ir(path, document: dict) -> None:
    """Keep an IR this process just wrote, so reading it back costs nothing."""
    ensure_paths(document["roots"])
    _keep(_ir_key(path), document)


def _keep(key: tuple, document: dict) -> None:
    old = _LOADED.pop(key[0], None)
    if old is not None:
        _forget(old[1])
    _LOADED[key[0]] = (key, document, key[1])
    _DERIVED[(id(document), "paths")] = (document, None)
    while len(_LOADED) > 1 and (len(_LOADED) > _KEEP or sum(entry[2] for entry in _LOADED.values()) > _KEEP_BYTES):
        _forget(_LOADED.pop(next(iter(_LOADED)))[1])


def _forget(document: dict) -> None:
    for key in [key for key, (ir, _) in _DERIVED.items() if ir is document]:
        del _DERIVED[key]


def _loaded(ir: dict) -> bool:
    return any(entry[1] is ir for entry in _LOADED.values())


# What commands work out from a loaded IR (which branches hold UI, a path index...),
# kept while that IR is: (id(ir), name) -> (ir, value).
_DERIVED: dict[tuple[int, str], tuple[dict, object]] = {}


def derived(ir: dict, name: str, compute):
    """`compute(ir)`, once per loaded IR (load_ir). An IR built by the caller is not
    kept, so its value is computed every time."""
    key = (id(ir), name)
    hit = _DERIVED.get(key)
    if hit is not None and hit[0] is ir:
        return hit[1]
    value = compute(ir)
    if _loaded(ir):
        _DERIVED[key] = (ir, value)
    return value


def ensure_ir_paths(ir: dict) -> None:
    """ensure_paths on a whole IR, skipped for one load_ir already did."""
    derived(ir, "paths", lambda document: ensure_paths(document["roots"]))


def _segment(node: dict) -> str:
    return node.get("name") or node.get("className") or "?"


def ensure_paths(nodes: list[dict], parent: str = "") -> None:
    """Give every node a unique slash `path`, as the emitter does.

    Siblings that share a name are all indexed (`Card[1]`, `Card[2]`), so a bare
    name always means exactly one node. The emitter writes these paths itself; this
    fills them in for IR written by hand or by an older emitter, with the same rule.
    """
    counts: dict[str, int] = {}
    for node in nodes:
        counts[_segment(node)] = counts.get(_segment(node), 0) + 1
    seen: dict[str, int] = {}
    for node in nodes:
        name = _segment(node)
        if "path" not in node:
            segment = name
            if counts[name] > 1:
                seen[name] = seen.get(name, 0) + 1
                segment = f"{name}[{seen[name]}]"
            node["path"] = f"{parent}/{segment}" if parent else segment
        ensure_paths(node.get("children") or [], node["path"])


def resolve_path(roots: list[dict], wanted: str) -> dict:
    """The node at `wanted`, or a ValueError that names the candidates.

    A bare name that matches several indexed siblings (`Card` when the file has
    `Card[1]` and `Card[2]`) is an error listing them, never a silent pick.
    """
    if not any(entry[1].get("roots") is roots for entry in _LOADED.values()):
        ensure_paths(roots)  # load_ir did it for a loaded IR
    found = _find_path(roots, wanted)
    if found is not None:
        return found
    by_path: dict[str, dict] = {}

    def walk(node: dict) -> None:
        by_path[node["path"]] = node
        for child in node.get("children") or []:
            walk(child)

    for root in roots:
        walk(root)
    if wanted in by_path:
        return by_path[wanted]
    indexed = sorted(p for p in by_path if p.startswith(wanted + "[") and "/" not in p[len(wanted):])
    if indexed:
        raise ValueError(f"path is ambiguous: {wanted} matches {', '.join(indexed)}")
    raise ValueError(f"path not found in IR: {wanted}")


# Where a place keeps models out of the world until a script clones them in: a game's
# maps in ServerStorage, tools in StarterPack, templates in ReplicatedStorage. Roblox
# does not draw them, and drawing them all at once (often at the same spot) frames a
# 3D view on nothing useful. scene/scene.js keeps the same list (STORED_SERVICES).
STORED_SERVICES = frozenset({
    "ServerStorage", "ReplicatedStorage", "ReplicatedFirst", "ServerScriptService",
    "StarterPack", "StarterPlayer",
})
PLACE_ROOTS = STORED_SERVICES | {"Workspace", "Lighting", "StarterGui"}
_PART_CLASSES = frozenset({
    "Part", "MeshPart", "UnionOperation", "WedgePart", "CornerWedgePart", "TrussPart",
    "SpawnLocation", "Seat", "VehicleSeat",
})


def _find_path(nodes: list[dict], wanted: str) -> dict | None:
    for node in nodes:
        path = node.get("path", "")
        if path == wanted:
            return node
        if wanted.startswith(path + "/"):
            return _find_path(node.get("children") or [], wanted)
    return None


def world_roots(roots: list[dict], focus: str | None = None) -> tuple[list[dict], list[dict]]:
    """What a 3D view draws: (roots to draw, stored roots left out).

    In a place: everything but the storage services, plus the node `focus` names when
    it is stored (`--focus ServerStorage/Maps/Farmhouse` shows that map). A model file
    has no services and draws everything.
    """
    if not any(root.get("className") in PLACE_ROOTS for root in roots):
        return roots, []
    shown = [root for root in roots if root.get("className") not in STORED_SERVICES]
    stored = [root for root in roots if root.get("className") in STORED_SERVICES]
    if focus:
        target = _find_path(stored, focus)
        if target is not None:
            shown.append(target)
    return shown, stored


def _part_count(node: dict) -> int:
    count = 1 if node.get("className") in _PART_CLASSES else 0
    return count + sum(_part_count(child) for child in node.get("children") or [])


def stored_note(stored: list[dict], focus: str | None = None) -> str | None:
    """One line naming the stored parts a 3D view of a place did not draw, or None."""
    counts = [(root, _part_count(root)) for root in stored]
    counts = [(root, n) for root, n in counts if n]
    if not counts:
        return None
    total = sum(n for _, n in counts)
    where = ", ".join(f"{root.get('path')} {n}" for root, n in sorted(counts, key=lambda item: -item[1]))
    # An example to focus on: the biggest stored model, below any container that only
    # groups several (a Folder, or a Model of Models such as a game's Maps).
    node = max(counts, key=lambda item: item[1])[0]
    while True:
        children = [(child, _part_count(child)) for child in node.get("children") or []]
        children = [(child, n) for child, n in children if n]
        grouping = node.get("className") in STORED_SERVICES or node.get("className") == "Folder" or (
            len(children) >= 3 and all(child.get("className") in ("Model", "Folder") for child, _ in children))
        if not children or not grouping:
            break
        node = max(children, key=lambda item: item[1])[0]
    shown = f" (only {focus} is drawn)" if focus else ""
    return (f"{total} part(s) stored outside the world not drawn{shown} ({where}): scripts clone them "
            f"into Workspace at run time; --focus <path> draws one, e.g. {node.get('path')}")


def world_ir(ir_path, focus: str | None = None) -> Path:
    """The IR a 3D view of `ir_path` uses: only the roots it draws (world_roots), written
    once beside the IR. A place that keeps most of its parts in storage (a game's maps
    in ServerStorage) is otherwise read and sent to the page whole on every render: 110k
    stored parts, 230 MB, to draw 6k. The slice records what it left out (storedNote).
    A file with nothing stored is used as it is."""
    import hashlib as _hashlib
    import os

    ir_path = Path(ir_path)
    tag = "world" if not focus else "focus-" + _hashlib.sha1(focus.encode("utf-8")).hexdigest()[:10]
    target = ir_path.with_name(f"{ir_path.stem}.{tag}.json")
    marker = target.with_name(target.name + ".plain")  # "nothing stored: use the IR itself"
    if marker.is_file() and marker.stat().st_mtime_ns >= ir_path.stat().st_mtime_ns:
        return ir_path
    if target.is_file() and target.stat().st_mtime_ns >= ir_path.stat().st_mtime_ns:
        return target
    document = load_ir(ir_path)
    shown, stored = world_roots(document["roots"], focus)
    if not stored:
        marker.write_text("", encoding="utf-8")
        return ir_path
    # A "world" IR summed up its storage when it was read (it keeps none of its parts).
    note = document["storedNote"] if "storedNote" in document and not focus else stored_note(stored, focus)
    world = {**document, "roots": shown, "storedNote": note}
    partial = target.with_name(f"{target.name}.{os.getpid()}.part")
    partial.write_text(json.dumps(world, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(partial, target)
    _remember_ir(target, world)
    return target


def cached_ir(source_path, *, profile: str = "full") -> Path:
    """IR for a Roblox file, reusing the last conversion of the same bytes.

    An agent runs several commands on one unchanged file (layout, then render, then
    check); converting it through Lune each time costs about a second. The cache key
    is the file's content and location plus the converter script and the Lune
    binary, so an edited or moved file, a new RHR or a new Lune always converts
    again. Each key has its own folder, which also keeps two different files that
    share a name apart.
    """
    from rhr.paths import IR_DIR

    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"no such file: {source_path}")
    data = source_path.read_bytes()
    if not _own_reader(data):
        # Lune's script has no "ui" or "world" profile; these IRs hold what they would.
        profile = {"ui": "full", "world": "static"}.get(profile, profile)
    digest = hashlib.sha256()
    digest.update(data)
    digest.update(LUAU_IR_SCRIPT.read_bytes())
    if _own_reader(data):
        # RHR's own reader: the key covers its code and reflection data instead of Lune.
        digest.update(f"{profile}|rhr.rbx|{_own_reader_stamp()}".encode())
    else:
        lune = Path(lune_executable())
        digest.update(f"{profile}|{lune}|{lune.stat().st_size}|{lune.stat().st_mtime_ns}".encode())
    # The IR records where it came from (sourcePath, read again for terrain); the same
    # bytes in another folder are a different entry, so that path is never stale.
    digest.update(str(source_path).encode("utf-8"))
    folder = IR_DIR / digest.hexdigest()[:20]
    # (the folder is per profile: the "ui" IR keeps the plain name the reports show)
    suffix = ".json" if profile in ("full", "ui") else f".{profile}.json"
    target = folder / f"{source_path.stem}{suffix}"
    report = target.with_name(target.name + ".report.txt")
    if target.is_file() and report.is_file():
        # Replay the reader's report (what it could not read), minus its "wrote" line.
        lines = report.read_text(encoding="utf-8").splitlines()
        text = "\n".join(line for line in lines if not line.startswith("wrote "))
        if text.strip():
            print(text.strip(), file=sys.stderr)
        print(f"ir     reused {target} (file unchanged)", file=sys.stderr)
        return target
    emit_ir(source_path, target, profile=profile, report_path=report)
    return target


def _own_reader(data: bytes) -> bool:
    """Whether RHR reads this file itself (a binary .rbxm/.rbxl) rather than through
    Lune (XML files, or RHR_READER=lune)."""
    import os

    from rhr.rbxl_raw import MAGIC

    return data[:8] == MAGIC and os.environ.get("RHR_READER", "").strip().lower() != "lune"


def _own_reader_stamp() -> str:
    """What RHR's own reader is: its code and reflection data, for the cache key."""
    digest = hashlib.sha256()
    folder = Path(__file__).with_name("rbx")
    for path in sorted([*folder.glob("*.py"), *folder.glob("*.gz")]):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _emit_own(source_path: Path, data: bytes, out_path: Path, profile: str, report_path) -> bool:
    """Write the IR with rhr.rbx. False when the reader cannot read this file (the
    caller then uses Lune, and says so)."""
    import os

    from rhr.profile import phase
    from rhr.rbx import binary, emit

    try:
        with phase("file read (rhr.rbx)"):
            document, report = emit.emit(binary.read(data), profile=profile, source_path=str(source_path))
        with phase("IR written"):
            text = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except Exception as exc:  # noqa: BLE001 - any failure: the proven Lune path
        print(f"note   RHR's file reader could not read {source_path.name} ({type(exc).__name__}: "
              f"{str(exc)[:200]}); reading it with Lune instead", file=sys.stderr)
        return False
    partial = out_path.with_name(f"{out_path.name}.{os.getpid()}.part")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, out_path)
    _remember_ir(out_path, document)
    lines = [f"wrote {out_path} roots={len(document['roots'])}", *report]
    print("\n".join(lines), file=sys.stderr)
    if report_path is not None:
        Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# Set by the resident server (rhr.server): XML files go to one Lune process that stays
# running (rhr.lune_worker) instead of a new one per conversion.
USE_LUNE_WORKER = False


def emit_ir(source_path, out_path, *, profile: str = "full", report_path=None) -> Path:
    """Convert a .rbxm/.rbxmx/.rbxl file to IR JSON.

    Binary files are read by RHR itself (rhr.rbx: the same IR the Lune script writes,
    measured identical on 63 real files, 10-60x faster); XML files by the Lune script
    (rbx-dom detects binary versus XML by content, so both go through it).
    """
    if profile not in {"full", "visual", "static", "ui", "world"}:
        raise ValueError(f"unknown IR profile: {profile}")
    source_path, out_path = Path(source_path).resolve(), Path(out_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"no such file: {source_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = source_path.read_bytes()
    if _own_reader(data) and _emit_own(source_path, data, out_path, profile, report_path):
        return out_path
    # The Lune script has no "ui" or "world" profile: these IRs hold what they would.
    profile = {"ui": "full", "world": "static"}.get(profile, profile)
    lune = lune_executable()
    proc = None
    if USE_LUNE_WORKER:
        from rhr import lune_worker

        try:
            proc = subprocess.CompletedProcess([], *lune_worker.convert(lune, source_path, out_path, profile))
        except (OSError, ValueError):
            proc = None  # the worker could not run: once more on its own, for its message
    if proc is None:
        command = [lune, "run", str(LUAU_IR_SCRIPT), str(source_path), str(out_path)]
        if profile != "full":
            command.append(profile)
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            **no_window(),
        )
    if proc.returncode != 0 and "Failed to find tool 'lune'" in proc.stderr:
        # Rokit's shim only resolves tools listed in a rokit.toml above the cwd.
        raise RuntimeError(
            "`lune` is a Rokit shim, but no rokit.toml here lists it. Install it for every "
            "directory with `rokit add --global lune-org/lune@0.10.5`, or run `rhr setup`."
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"lune IR dump failed for {source_path} (exit {proc.returncode})\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    if not out_path.exists():
        raise RuntimeError(f"lune reported success but wrote no file: {out_path}")
    # The emitter's own report (unreadable, unmapped, child-name collisions, and
    # whether its class filter still agrees with the reflection database) is the
    # "nothing vanishes in silence" contract. It goes to stderr, with the rest of
    # the progress, so `rhr ir model --out ir.json` can stay pipeable on stdout.
    if proc.stdout.strip():
        print(proc.stdout.strip(), file=sys.stderr)
    if report_path is not None:
        # Written last: a cached IR counts only once its report exists too.
        Path(report_path).write_text(proc.stdout, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m rhr.ir <source.rbxm> <out.json>")
    print(emit_ir(sys.argv[1], sys.argv[2]))