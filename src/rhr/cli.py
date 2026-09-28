"""rhr: the command line for this renderer.

    rhr ui      <file>   the ScreenGuis (2D UI) to PNG
    rhr scene   <file>   the 3D world to PNG
    rhr preview <file>   the 3D world with the UI over it, to PNG
    rhr view    <file>   the 3D world in a local page to move around in, kept up to date
    rhr icons   <files or folders>   square icon PNGs of models, transparent background
    rhr inspect <file>   JSON: classes, scripts, assets, and risky script code
    rhr layout | check | hitmap | scene-dump <file>   JSON
    rhr compare <before.png> <after.png>              JSON
    rhr ir <file> --out ir.json                       RHR's internal format (not stable)

Input is a Roblox model or place (.rbxm/.rbxmx/.rbxl/.rbxlx), a Rojo project, an
IR JSON file, or a Roblox asset id or link (downloaded first: rhr.remote). The public interface is listed in docs/interface-1.0.md.

Output rules: data commands print one JSON document on stdout (or write it with
`--out`); picture commands print the PNG's path, or with `--json` a report
(`rhr.render/1`). Progress and notes go to stderr, for people. Exit codes: 0 done,
1 only from `check` (error findings), 2 the command failed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from rhr.paths import IR_DIR
from rhr.schema import dumps, stamp


# The reference viewport: upstream pinevex's reference renders and this project's
# early Studio captures are 1615x1080. Override with --viewport.
DEFAULT_VIEWPORT = (1615, 1080)

MODEL_SUFFIXES = {".rbxm", ".rbxmx", ".rbxl", ".rbxlx"}


def _die(message: str) -> int:
    print(f"rhr: {message}", file=sys.stderr)
    return 2


def parse_viewport(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        width, height = int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"viewport must be WxH, got {text!r}") from None
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"viewport must be positive, got {text!r}")
    return width, height


def parse_vector3(text: str) -> tuple[float, float, float]:
    try:
        values = tuple(float(part.strip()) for part in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"vector must be X,Y,Z, got {text!r}") from None
    if len(values) != 3 or any(not math.isfinite(value) for value in values):
        raise argparse.ArgumentTypeError(f"vector must be three finite numbers X,Y,Z, got {text!r}")
    return values


def parse_fov(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"FOV must be a number, got {text!r}") from None
    if not math.isfinite(value) or value <= 1 or value >= 179:
        raise argparse.ArgumentTypeError(f"FOV must be between 1 and 179 degrees, got {text!r}")
    return value


def parse_background(text: str) -> tuple[int, int, int, int]:
    raw = text.lstrip("#")
    if len(raw) == 8:  # RRGGBBAA
        r, g, b, a = (int(raw[i : i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a)
    if len(raw) == 6:
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, 255)
    raise argparse.ArgumentTypeError(f"background must be RRGGBB or RRGGBBAA, got {text!r}")


def ir_for(source: Path, *, profile: str = "full", viewport: tuple[int, int] = DEFAULT_VIEWPORT) -> Path:
    """IR JSON for `source`: the file itself if it is IR, else the cached conversion
    (made again when the file changed).

    `source` may also be a Rojo project (a *.project.json file or a directory with
    default.project.json), which is built with `rojo build` first, or a story file
    (*.story.luau), which is run at `viewport` and the UI it builds read (rhr.story).
    """
    from rhr.ir import cached_ir, load_ir
    from rhr import rojo, story

    if story.is_story(source):
        # UI that code builds: the story is run in its Rojo project (rhr.story).
        source = story.build(source, width=viewport[0], height=viewport[1],
                             log=lambda message: print(message, file=sys.stderr))
    project = rojo.project_file(source)
    if project is not None:
        source = rojo.build(project, IR_DIR)
    elif source.suffix == ".json":
        load_ir(source)  # fail here, with a clear message, not deeper in the render
        return source
    if source.suffix not in MODEL_SUFFIXES:
        raise ValueError(
            f"{source} is neither a Roblox file ({', '.join(sorted(MODEL_SUFFIXES))}), "
            "a Rojo project, nor an IR .json file"
        )
    return cached_ir(source, profile=profile)


def _stored_gui_note(ir_path) -> str | None:
    """Which ScreenGuis a place keeps outside StarterGui and so were not drawn (printed
    to stderr, and returned for the --json report)."""
    from rhr.adapter import ir_to_raw_nodes
    from rhr.ir import load_ir
    from rhr.pipeline import shown_ui_roots

    _, hidden = shown_ui_roots(ir_to_raw_nodes(load_ir(ir_path)))
    if not hidden:
        return None
    names = ", ".join(hidden[:4]) + (f", +{len(hidden) - 4} more" if len(hidden) > 4 else "")
    note = (f"{len(hidden)} ScreenGui(s) stored outside StarterGui not drawn "
            f"(scripts clone them in at run time; --all-guis draws them): {names}")
    print(f"note   {note}", file=sys.stderr)
    return note


def _finish_picture(args, report: dict) -> int:
    """A picture command's stdout: the PNG's path, or with --json the whole report."""
    from rhr import browsers

    # {name, version, path} of the browser that drew it; null when none was needed.
    report.setdefault("browser", browsers.used)
    if args.json:
        print(dumps(stamp("render", report)))
    else:
        print(report["out"])
    return 0


def _camera_json(state: dict) -> dict | None:
    """The camera a 3D render used: position, the direction it looks and its vertical
    field of view. None when the page did not report it."""
    try:
        x, y, z, w = (float(v) for v in state["quaternion"])
        # The camera looks along its -Z axis, rotated by the quaternion.
        look = [-(2 * (x * z + w * y)), -(2 * (y * z - w * x)), -(1 - 2 * (x * x + y * y))]
        return {
            "position": [round(float(v), 4) for v in state["position"]],
            "lookDirection": [round(v, 6) + 0.0 for v in look],  # + 0.0: no -0.0
            "fieldOfView": round(float(state["fov"]), 4),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _world_report(scene_dump: dict) -> dict:
    """What a 3D render approximated or could not draw, from its scene dump."""
    return {
        "fallbacks": scene_dump["fallbacks"],
        "materialFallbacks": scene_dump["materialFallbacks"],
        "unsupportedVisualClasses": scene_dump["unsupportedVisualClasses"],
        "experimental": scene_dump["experimental"],
        "missingAssets": [
            {"path": item["path"], "class": item["class"], "uri": item.get("uri")}
            for item in scene_dump["assetReferences"] if not item["available"]
        ],
    }


def rect_to_dict(rect) -> dict:
    """The engine's RRect as plain JSON: ui_engine.layout.Rect(x, y, w, h)."""
    x, y = getattr(rect, "x", getattr(rect, "left", None)), getattr(rect, "y", getattr(rect, "top", None))
    w, h = getattr(rect, "w", None), getattr(rect, "h", None)
    if None in (x, y, w, h):
        raise TypeError(f"cannot read x/y/w/h out of {rect!r}")
    return {"x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3)}


def _inset_json(inset) -> dict:
    return {"mode": inset.mode, "top": inset.top, "left": inset.left, "right": inset.right,
            "bottom": inset.bottom}


def _ui(args) -> int:
    from rhr.pipeline import load_screens, render_screens

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    bg = (0, 0, 0, 0) if args.transparent else args.background
    out = Path(args.out) if args.out else Path(f"{source.stem}-ui.png")
    rect_map: dict = {} if args.dump_layout else None

    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, profile="ui", viewport=(width, height))
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))
    _prepare_ui_images(ir_path, args.offline)
    t_ir = time.perf_counter()

    try:
        screens = load_screens(str(ir_path), width, height, args.topbar_height)
        png = render_screens(
            screens, out, width, height, bg_color=bg, rect_map=rect_map, source_ir=ir_path
        )
    except ValueError as exc:
        return _die(str(exc))
    t_render = time.perf_counter()

    print(f"ir     {ir_path}  {int((t_ir - t0) * 1000)}ms", file=sys.stderr)
    for _, _, inset, name in screens:
        label = f"{name}: " if len(screens) > 1 else ""
        print(f"inset  {label}{inset.describe()}", file=sys.stderr)
    if len(screens) > 1:
        print(f"panes  {len(screens)} ScreenGuis rendered in paint order", file=sys.stderr)
    print(
        f"ui     {png}  {width}x{height}  {int((t_render - t_ir) * 1000)}ms",
        file=sys.stderr,
    )
    print(f"total  {int((t_render - t0) * 1000)}ms", file=sys.stderr)
    stored = _stored_gui_note(ir_path)

    if rect_map is not None:
        layout = {path: rect_to_dict(rect) for path, rect in rect_map.items()}
        document = stamp("layout", {"viewport": [width, height], "rects": layout})
        Path(args.dump_layout).parent.mkdir(parents=True, exist_ok=True)
        Path(args.dump_layout).write_text(dumps(document), encoding="utf-8")
        print(f"layout {args.dump_layout}  {len(layout)} rects", file=sys.stderr)
        if not layout and screens:
            return _die("the layout dump is empty. That is a bug in the pipeline, not an "
                        "empty UI: nodes reach the renderer without a _path.")
    return _finish_picture(args, {
        "command": "ui",
        "source": str(source),
        "out": str(png),
        "size": [width, height],
        "screens": [{"name": name, "inset": _inset_json(inset)} for _, _, inset, name in screens],
        "notes": [stored] if stored else [],
    })


def _layout(args) -> int:
    from rhr.pipeline import load_screens, render_screens

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    try:
        ir_path = ir_for(source, profile="ui", viewport=(width, height))
        screens = load_screens(str(ir_path), width, height, args.topbar_height)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))

    # --rich: the same paint pass, plus what each node is made of (zIndex,
    # visibility, resolved colours, text, clip state). Plain `rhr layout` is rects only.
    if args.rich:
        from rhr.layout_dump import build_dump, dump_json

        t0 = time.perf_counter()
        dump = build_dump(ir_path, width, height, topbar_height=args.topbar_height)
        text = dump_json(dump)
        elapsed = int((time.perf_counter() - t0) * 1000)
        count = len(dump["nodes"])
        # Same guard as the plain path: an empty dump is a pipeline bug, not an
        # empty UI — nodes reached the renderer without a _path.
        if not count and screens:
            return _die("the structured dump is empty. That is a bug in the pipeline, "
                        "not an empty UI: nodes reached the renderer without a _path.")
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(args.out, file=sys.stderr)
        else:
            print(text)
        print(f"dump {count} nodes  {elapsed}ms", file=sys.stderr)
        return 0

    # A rect is resolved by the paint pass, run on a null canvas: the same geometry
    # as a render, with nothing drawn. Every ScreenGui is laid out, so the dump is
    # the whole UI, not the top pane.
    rect_map: dict = {}
    render_screens(screens, None, width, height, rect_map=rect_map, draw=False)
    for _, _, inset, name in screens:
        label = f"{name}: " if len(screens) > 1 else ""
        print(f"inset  {label}{inset.describe()}", file=sys.stderr)
    layout = {path: rect_to_dict(rect) for path, rect in rect_map.items()}
    if not layout and screens:
        return _die("no rects resolved: nodes reached the renderer without a _path")
    # JSON on stdout, the count on stderr, so `rhr layout model.rbxm | jq` works.
    print(f"layout {len(layout)} rects", file=sys.stderr)
    _stored_gui_note(ir_path)
    document = stamp("layout", {"viewport": [width, height], "rects": layout})
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(dumps(document), encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(dumps(document))
    return 0


def _prepare_scene_assets(ir_path: Path, offline: bool, focus: str | None = None) -> None:
    """Before a 3D render: fetch what it needs and is not cached, and say what is missing.

    RHR expects Roblox Studio on the machine and signed in; the download runs as that
    Studio user (rhr.fetch). Nothing is downloaded that is already cached.
    """
    from rhr import fetch
    from rhr.studio import studio_install

    def say(message: str) -> None:
        print(message, file=sys.stderr)

    if studio_install() is None:
        say("note   Roblox Studio is not installed on this machine: the default sky, material "
            "textures, meshes and unions use stand-ins, so this looks less like Roblox than it "
            "would with Studio (docs/known-approximations.md)")
    if offline or fetch.offline():
        return
    try:
        fetch.ensure_for_ir(ir_path, log=say, focus=focus)
    except Exception as exc:  # noqa: BLE001 - a failed download must not fail the render
        say(f"note   fetching assets failed ({type(exc).__name__}: {exc}); drawing with what is cached")


def _prepare_ui_images(ir_path: Path, offline: bool) -> None:
    """Before a UI render: download the images it uses that are not cached (rhr.fetch)."""
    from rhr import fetch

    if offline or fetch.offline():
        return
    try:
        from rhr.adapter import ui_nodes
        from rhr.ir import load_ir

        ir = load_ir(ir_path)
        images, _ = fetch.collect_refs(ir, ui_nodes(ir))  # the UI's images, not the 3D world's
        fetch.ensure({"images": images}, log=lambda message: print(message, file=sys.stderr))
    except Exception as exc:  # noqa: BLE001 - a failed download must not fail the render
        print(f"note   fetching images failed ({type(exc).__name__}: {exc}); drawing with what is cached",
              file=sys.stderr)


def _fetch(args) -> int:
    from rhr import fetch

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    try:
        ir_path = ir_for(source)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))
    return fetch.run(ir_path, images=not args.meshes_only, meshes=not args.images_only,
                     studio_login=not args.no_studio_login)


def _ir(args) -> int:
    from rhr import rojo
    from rhr.ir import emit_ir

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    t0 = time.perf_counter()
    try:
        project = rojo.project_file(source)
        if project is not None:
            source = rojo.build(project, IR_DIR)
        out = emit_ir(source, Path(args.out))
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)
    data = json.loads(Path(out).read_text(encoding="utf-8"))

    def count(node: dict) -> int:
        return 1 + sum(count(c) for c in node.get("children") or [])

    nodes = sum(count(r) for r in data["roots"])
    print(f"ir     {out}  {nodes} nodes  {elapsed}ms", file=sys.stderr)
    print(out)
    return 0


def _check(args) -> int:
    from rhr.checks import check_model, findings_json

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, profile="ui", viewport=(width, height))
        result = check_model(ir_path, width, height, topbar_height=args.topbar_height)
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)

    findings = result["findings"]
    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = len(findings) - errors
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(findings_json(result), encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(findings_json(result))
    print(f"check {len(findings)} findings ({errors} error, {warnings} warning)  {elapsed}ms", file=sys.stderr)
    # A build loop refuses to ship on error-class findings; warnings do not
    # block (they are visible reality, not defects).
    return 1 if errors else 0


def _browser(args) -> int:
    from rhr.browser_session import ensure, status, stop

    try:
        if args.action == "start":
            state, started = ensure()
            result = {
                "running": True,
                "started": started,
                "pid": state["pid"],
                "port": state["port"],
            }
        elif args.action == "stop":
            result = {"stopped": stop(), "running": False}
        else:
            result = status()
    except (OSError, RuntimeError) as exc:
        return _die(str(exc))
    print(dumps(stamp("browser", result)))
    return 0


def _compare(args) -> int:
    from rhr.diff import compare, format_report

    before = Path(args.before)
    after = Path(args.after)
    for path in (before, after):
        if not path.exists():
            return _die(f"no such file: {path}")
    metrics = compare(before, after, bg=args.background[:3], silhouette_threshold=args.silhouette_threshold)
    print(dumps(stamp("compare", metrics)))
    print(format_report(metrics), file=sys.stderr)
    return 0 if metrics.get("sizeMatch") else 2


def _hitmap(args) -> int:
    from rhr.hitmap import build_hitmap, dump_json

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, profile="ui", viewport=(width, height))
        hitmap = build_hitmap(ir_path, width, height, topbar_height=args.topbar_height)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))
    text = dump_json(hitmap)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(text)
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(
        f"hitmap {len(hitmap['nodes'])} interactive nodes, "
        f"{len(hitmap['hitTests'])} probe points  {elapsed}ms",
        file=sys.stderr,
    )
    return 0


def _scene(args) -> int:
    from rhr.scene import render_scene

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    out = Path(args.out) if args.out else Path(f"{source.stem}-scene.png")
    t0 = time.perf_counter()
    texture_dir = Path(args.texture_dir) if args.texture_dir else None
    mesh_dir = Path(args.mesh_dir) if args.mesh_dir else None
    try:
        from rhr.profile import phase

        with phase("file conversion (IR)"):
            # A stored model (--focus ServerStorage/...) needs the storage read too.
            ir_path = ir_for(source, profile="static" if args.focus else "world")
        with phase("downloads check"):
            from rhr.ir import world_ir

            ir_path = world_ir(ir_path, args.focus)
            _prepare_scene_assets(ir_path, args.offline, args.focus)
        page_notes: list[str] = []
        camera_state: dict = {}
        with phase("browser render (total)"):
            actual = render_scene(
                ir_path,
                out,
                width,
                height,
                camera=args.camera,
                look_at=args.look_at,
                fov=args.fov,
                focus=args.focus,
                view=args.view,
                shadows=not args.no_shadows,
                flat_materials=args.flat_materials,
                texture_dir=texture_dir,
                mesh_dir=mesh_dir,
                camera_state_out=camera_state,
                notes_out=page_notes,
                effects=not args.no_effects,
                effect_time=args.effect_time,
                seed=args.seed,
            )
        from rhr.scene_dump import cached_scene_dump, notes_line

        with phase("notes (scene dump)"):
            scene_dump, _ = cached_scene_dump(ir_path, texture_dir=texture_dir, mesh_dir=mesh_dir,
                                          world=True, focus=args.focus, parts=False)
            if scene_dump.get("_storedNote"):
                page_notes.append(scene_dump["_storedNote"])
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"ir     {ir_path}", file=sys.stderr)
    print(f"scene  {out}  {actual[0]}x{actual[1]}  {elapsed}ms", file=sys.stderr)
    print(notes_line(scene_dump), file=sys.stderr)
    for note in page_notes:
        print(f"note   {note}", file=sys.stderr)
    return _finish_picture(args, {
        "command": "scene",
        "source": str(source),
        "out": str(out),
        "size": list(actual),
        "camera": _camera_json(camera_state),
        **_world_report(scene_dump),
        "notes": page_notes,
    })


def _inspect(args) -> int:
    from rhr import rojo
    from rhr.inspect import inspect
    from rhr.schema import dumps

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    t0 = time.perf_counter()
    try:
        project = rojo.project_file(source)
        report = inspect(rojo.build(project, IR_DIR) if project is not None else source)
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    text = dumps(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(text)
    counts = {}
    for finding in report["findings"]:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    print(f"inspect {report['instances']} instances, {len(report['scripts'])} scripts, findings: "
          + (", ".join(f"{n} {s}" for s, n in counts.items()) or "none")
          + f"  {int((time.perf_counter() - t0) * 1000)}ms", file=sys.stderr)
    return 0


def _icons(args) -> int:
    from rhr import icons, remote
    from rhr.ir import world_ir

    def resolve(item: str) -> Path:
        path = Path(item)
        if path.exists():
            return path
        if remote.asset_reference(item) is not None:
            return remote.resolve(item)
        raise ValueError(f"no such file: {item}")

    def prepare(source: Path) -> Path:
        ir_path = world_ir(ir_for(source, profile="world"), None)
        _prepare_scene_assets(ir_path, args.offline, None)
        return ir_path

    return icons.run(args.files, out_dir=Path(args.out_dir), size=args.size, view=args.view or "iso",
                     margin=args.margin, fov=args.fov, background=args.background,
                     shadows=not args.no_shadows, effects=not args.no_effects, prepare=prepare, resolve=resolve)


def _view(args) -> int:
    from rhr import view
    from rhr.ir import world_ir

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")

    def build() -> Path:
        ir_path = world_ir(ir_for(source, profile="static" if args.focus else "world"), args.focus)
        _prepare_scene_assets(ir_path, args.offline, args.focus)
        return ir_path

    query: dict[str, str] = {"view": args.view or "iso", "shadows": "0" if args.no_shadows else "1"}
    if args.focus:
        query["focus"] = args.focus
    if args.no_effects:
        query["effects"] = "0"
    if args.flat_materials:
        query["flatMaterials"] = "1"
    try:
        return view.serve(source, build, query=query, open_browser=not args.no_open, port=args.port)
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))


def _preview(args) -> int:
    from PIL import Image
    from rhr.pipeline import load_screens, render_screens
    from rhr.scene import render_scene

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    out = Path(args.out) if args.out else Path(f"{source.stem}-preview.png")
    texture_dir = Path(args.texture_dir) if args.texture_dir else None
    mesh_dir = Path(args.mesh_dir) if args.mesh_dir else None
    t0 = time.perf_counter()
    try:
        # A stored model (--focus) or stored ScreenGuis (--all-guis) need the storage read too.
        ir_path = ir_for(source, profile="static" if args.focus or args.all_guis else "world",
                          viewport=(width, height))
        from rhr.ir import world_ir

        world_path = world_ir(ir_path, args.focus)
        _prepare_scene_assets(world_path, args.offline, args.focus)
        with tempfile.TemporaryDirectory(prefix="rhr-preview-") as directory:
            tmp = Path(directory)
            world = tmp / "world.png"
            ui = tmp / "ui.png"
            page_notes: list[str] = []
            camera_state: dict = {}
            render_scene(
                world_path,
                world,
                width,
                height,
                camera=args.camera,
                look_at=args.look_at,
                fov=args.fov,
                focus=args.focus,
                view=args.view,
                shadows=not args.no_shadows,
                flat_materials=args.flat_materials,
                texture_dir=texture_dir,
                mesh_dir=mesh_dir,
                camera_state_out=camera_state,
                notes_out=page_notes,
                effects=not args.no_effects,
                effect_time=args.effect_time,
                seed=args.seed,
            )
            screens = load_screens(
                str(ir_path),
                width,
                height,
                args.topbar_height,
                screen_gui_only=True,
            )
            with Image.open(world).convert("RGBA") as composite:
                if screens:
                    render_screens(
                        screens,
                        ui,
                        width,
                        height,
                        bg_color=(0, 0, 0, 0),
                        source_ir=ir_path,
                    )
                    with Image.open(ui).convert("RGBA") as overlay:
                        composite.alpha_composite(overlay)
                out.parent.mkdir(parents=True, exist_ok=True)
                composite.save(out)
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"ir      {ir_path}", file=sys.stderr)
    print(f"preview {out}  {width}x{height}  {elapsed}ms", file=sys.stderr)
    from rhr.scene_dump import cached_scene_dump, notes_line

    try:
        scene_dump, _ = cached_scene_dump(world_path, texture_dir=texture_dir, mesh_dir=mesh_dir,
                                      world=True, focus=args.focus, parts=False)
        if scene_dump.get("_storedNote"):
            page_notes.append(scene_dump["_storedNote"])
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(f"the picture was written, but reading back what it approximated failed: {exc}")
    print(notes_line(scene_dump), file=sys.stderr)
    for note in page_notes:
        print(f"note    {note}", file=sys.stderr)
    stored = _stored_gui_note(ir_path)
    return _finish_picture(args, {
        "command": "preview",
        "source": str(source),
        "out": str(out),
        "size": [width, height],
        "camera": _camera_json(camera_state),
        "screens": [{"name": name, "inset": _inset_json(inset)} for _, _, inset, name in screens],
        **_world_report(scene_dump),
        "notes": page_notes + ([stored] if stored else []),
    })


def _scene_dump(args) -> int:
    from rhr.scene_dump import cached_scene_dump

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source)
        scene_dump, text = cached_scene_dump(
            ir_path,
            texture_dir=Path(args.texture_dir) if args.texture_dir else None,
            mesh_dir=Path(args.mesh_dir) if args.mesh_dir else None,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(text)
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(
        f"scene-dump {len(scene_dump['parts'])} parts, "
        f"{sum(scene_dump['fallbacks'].values())} geometry fallbacks, "
        f"{sum(scene_dump['materialFallbacks'].values())} material fallbacks, "
        f"{sum(scene_dump['unsupportedVisualClasses'].values())} unsupported visuals, "
        f"{sum(1 for item in scene_dump['assetReferences'] if not item['available'])} missing assets  {elapsed}ms",
        file=sys.stderr,
    )
    return 0


def _effect_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--effect-time", type=float, metavar="T",
                        help="draw effects T seconds after they start playing: particles, and "
                             "how far Beam textures have scrolled (default: the moment "
                             "with the most particles on show)")
    parser.add_argument("--no-effects", action="store_true",
                        help="leave out particles, Beams and Trails")
    parser.add_argument("--seed", type=int, default=0, help="particle randomness seed")


def _picture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true",
                        help="print a JSON report (rhr.render/1: the PNG's path and size, the camera, "
                             "what was approximated or missing, notes) instead of the path")


def _test_hooks(parser: argparse.ArgumentParser) -> None:
    """Local asset folders the tests use instead of downloads. Not part of the interface."""
    parser.add_argument("--texture-dir", help=argparse.SUPPRESS)
    parser.add_argument("--mesh-dir", help=argparse.SUPPRESS)


def _cache(args) -> int:
    from rhr import cache

    if args.clear:
        try:
            freed = cache.clear(args.clear)
        except ValueError as exc:
            return _die(str(exc))
        print(f"cache  cleared {args.clear}: {freed / 1e6:.1f} MB")
        return 0
    held = cache.sizes()
    for name, size in held.items():
        print(f"{name:10} {size / 1e6:8.1f} MB  {cache.AREAS[name]}")
    limit = cache.limit_bytes()
    print(f"{'total':10} {sum(held.values()) / 1e6:8.1f} MB  "
          f"(limit {limit / 1e6:.0f} MB, RHR_CACHE_LIMIT_MB; least recently used goes first)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from rhr import __version__

    parser = argparse.ArgumentParser(
        prog="rhr",
        description="Headless previews of Roblox UI and 3D builds: PNGs plus layout JSON.",
        epilog="New here? Run `rhr doctor` to check your setup, `rhr setup` to fix it.",
    )
    parser.add_argument("--version", action="version", version=f"rhr {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="download Lune, Rojo and a headless browser if they are missing")
    p_setup.add_argument("--no-rojo", action="store_true", help="skip Rojo (only needed for Rojo projects)")
    p_setup.add_argument("--browser", action="store_true",
                         help="download the pinned headless browser even when another browser is installed")
    p_setup.set_defaults(func=lambda a: __import__("rhr.tools").tools.setup(rojo=not a.no_rojo, browser=a.browser))

    p_fetch = sub.add_parser(
        "fetch", help="download the images, meshes, unions and Roblox material textures a model uses "
                      "into the local cache, as the Roblox Studio user (scene and preview do this themselves)")
    p_fetch.add_argument("file", help="Roblox model/place, Rojo project, IR .json, or a Roblox asset id or link")
    only = p_fetch.add_mutually_exclusive_group()
    only.add_argument("--images-only", action="store_true", help="fetch images only")
    only.add_argument("--meshes-only", action="store_true",
                      help="fetch everything but images (meshes, unions, material textures)")
    p_fetch.add_argument(
        "--no-studio-login", action="store_true",
        help="only fetch what Roblox serves without signing in (images as thumbnails, some meshes)")
    p_fetch.set_defaults(func=_fetch)

    p_doctor = sub.add_parser("doctor", help="check what RHR needs and say what is missing")
    p_doctor.set_defaults(func=lambda a: __import__("rhr.tools").tools.doctor())

    p_cache = sub.add_parser("cache", help="show how much RHR's cache holds, or clear part of it")
    p_cache.add_argument("--clear", metavar="AREA",
                         help="remove one area (images, meshes, unions, materials, studio, ir) "
                              "or all of them; it is downloaded or converted again when needed")
    p_cache.set_defaults(func=_cache)

    p_ir = sub.add_parser("ir", help="write RHR's internal form of a file (for debugging; its shape may change in any release)")
    p_ir.add_argument("file", help=".rbxm/.rbxmx/.rbxl/.rbxlx")
    p_ir.add_argument("--out", required=True, help="where to write the IR JSON")
    p_ir.set_defaults(func=_ir)

    p_ui = sub.add_parser("ui", help="draw the ScreenGuis (2D UI) to PNG")
    p_ui.add_argument("file", help="Roblox model/place, Rojo project, IR .json, a Roblox asset id or link, "
                  "or a UI story (*.story.luau, run in its Rojo project)")
    p_ui.add_argument("--out", help="PNG path (default: <input stem>-ui.png)")
    p_ui.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                      help="WxH (default: 1615x1080)")
    p_ui.add_argument("--transparent", action="store_true",
                      help="alpha background instead of an opaque one")
    p_ui.add_argument("--background", type=parse_background, default=(255, 255, 255, 255),
                      help="RRGGBB or RRGGBBAA (default: ffffff)")
    p_ui.add_argument("--dump-layout", metavar="PATH",
                      help="also write the resolved rects here (rhr.layout/1)")
    p_ui.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58, "
             "see docs/known-approximations.md)",
    )
    p_ui.add_argument("--all-guis", action="store_true",
                      help="in a place, also draw ScreenGuis stored outside StarterGui (templates scripts clone in)")
    p_ui.add_argument("--offline", action="store_true",
                      help="do not download missing images first (also: RHR_OFFLINE=1)")
    _picture_arguments(p_ui)
    p_ui.set_defaults(func=_ui)

    p_layout = sub.add_parser("layout", help="resolved rect per node, as JSON")
    p_layout.add_argument("file", help="Roblox model/place, Rojo project, IR .json, a Roblox asset id or link, "
                      "or a UI story (*.story.luau, run in its Rojo project)")
    p_layout.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                          help="WxH (default: 1615x1080)")
    p_layout.add_argument("--out", help="write JSON here instead of stdout")
    p_layout.add_argument(
        "--rich",
        action="store_true",
        help="per node also its class, zIndex, paint order, visibility, resolved colours, "
             "gradient, strokes, text and clip state (rhr.layout-rich/1)",
    )
    p_layout.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_layout.add_argument("--all-guis", action="store_true",
                          help="in a place, also draw ScreenGuis stored outside StarterGui (templates scripts clone in)")
    p_layout.set_defaults(func=_layout)

    p_check = sub.add_parser("check", help="model smells that should fail a build, as JSON findings "
                                          "(exit 1 when any is an error)")
    p_check.add_argument("file", help="Roblox model/place, Rojo project, IR .json, a Roblox asset id or link, "
                     "or a UI story (*.story.luau, run in its Rojo project)")
    p_check.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                         help="WxH (default: 1615x1080)")
    p_check.add_argument("--out", help="write JSON here instead of stdout")
    p_check.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_check.add_argument("--all-guis", action="store_true",
                         help="in a place, also draw ScreenGuis stored outside StarterGui (templates scripts clone in)")
    p_check.set_defaults(func=_check)

    p_browser = sub.add_parser("browser", help="start, stop or ask about the warm 3D browser worker "
                                              "(it starts by itself on the first 3D render)")
    p_browser.add_argument("action", choices=("start", "status", "stop"))
    p_browser.set_defaults(func=_browser)

    p_compare = sub.add_parser("compare", help="pixel and silhouette changes between two PNGs, as JSON")
    p_compare.add_argument("before", help="reference/before PNG")
    p_compare.add_argument("after", help="after PNG")
    p_compare.add_argument("--background", type=parse_background, default=(32, 36, 43, 255),
                           help="RRGGBB background used to flatten alpha (default: 20242b)")
    p_compare.add_argument("--silhouette-threshold", type=float, default=8.0,
                           help="max-channel distance from background that counts as silhouette (default: 8)")
    # JSON is the default since 1.0; the old switch is accepted and does nothing.
    p_compare.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p_compare.set_defaults(func=_compare)

    p_hitmap = sub.add_parser("hitmap", help="interactive GUI hit regions, as JSON")
    p_hitmap.add_argument("file", help="Roblox model/place, Rojo project, IR .json, a Roblox asset id or link, "
                      "or a UI story (*.story.luau, run in its Rojo project)")
    p_hitmap.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                          help="WxH (default: 1615x1080)")
    p_hitmap.add_argument("--out", help="write JSON here instead of stdout")
    p_hitmap.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_hitmap.add_argument("--all-guis", action="store_true",
                          help="in a place, also draw ScreenGuis stored outside StarterGui (templates scripts clone in)")
    p_hitmap.set_defaults(func=_hitmap)

    p_scene = sub.add_parser("scene", help="draw the 3D world to PNG")
    p_scene.add_argument("file", help="Roblox model/place, Rojo project, IR .json, or a Roblox asset id or link")
    p_scene.add_argument("--out", help="PNG path (default: <input stem>-scene.png)")
    p_scene.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                         help="WxH (default: 1615x1080)")
    _camera_arguments(p_scene)
    p_scene.add_argument("--offline", action="store_true",
                         help="do not download missing assets first (also: RHR_OFFLINE=1)")
    _effect_arguments(p_scene)
    _picture_arguments(p_scene)
    _test_hooks(p_scene)
    p_scene.set_defaults(func=_scene)

    p_inspect = sub.add_parser("inspect", help="JSON: what a file holds (classes, scripts, assets) and "
                                               "findings for risky script code (backdoors in free models)")
    p_inspect.add_argument("file", help="Roblox model/place, Rojo project, or a Roblox asset id or link")
    p_inspect.add_argument("--out", help="write JSON here instead of stdout")
    p_inspect.set_defaults(func=_inspect)

    p_icons = sub.add_parser("icons", help="square icon PNGs of models on a transparent background, "
                                           "one per file, folder entry or asset id")
    p_icons.add_argument("files", nargs="+",
                         help="models (.rbxm/.rbxmx), folders of them, or Roblox asset ids or links")
    p_icons.add_argument("--out-dir", default="icons", help="where the PNGs go, named <stem>.png (default: icons)")
    p_icons.add_argument("--size", type=int, default=512, help="icon side in px (default: 512)")
    p_icons.add_argument("--view", choices=("iso", "front", "back", "left", "right", "top"),
                         help="the side the model is seen from (default: iso)")
    p_icons.add_argument("--margin", type=float, default=0.06, help="empty border, as a share of the side (default: 0.06)")
    p_icons.add_argument("--fov", type=parse_fov, default=30.0, help="field of view in degrees (default: 30)")
    p_icons.add_argument("--background", type=parse_background, default=None,
                         help="RRGGBB or RRGGBBAA instead of transparent")
    p_icons.add_argument("--no-shadows", action="store_true", help="no sun shadows on the model")
    p_icons.add_argument("--no-effects", action="store_true", help="leave out particles, Beams and Trails")
    p_icons.add_argument("--offline", action="store_true",
                         help="do not download missing assets first (also: RHR_OFFLINE=1)")
    p_icons.set_defaults(func=_icons)

    p_view = sub.add_parser("view", help="open the 3D world in a local page to move around in; "
                                         "it updates when the file changes (Ctrl+C stops)")
    p_view.add_argument("file", help="Roblox model/place, Rojo project, IR .json, or a Roblox asset id or link")
    p_view.add_argument("--focus", metavar="PATH", help="start framed on this part or model")
    p_view.add_argument("--view", choices=("iso", "front", "back", "left", "right", "top"),
                        help="the side to start from (default: iso)")
    p_view.add_argument("--no-shadows", action="store_true", help="no sun shadows")
    p_view.add_argument("--flat-materials", action="store_true", help="plain colours: no material textures")
    p_view.add_argument("--no-effects", action="store_true", help="leave out particles, Beams and Trails")
    p_view.add_argument("--no-open", action="store_true", help="print the address; do not open a browser")
    p_view.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    p_view.add_argument("--offline", action="store_true",
                        help="do not download missing assets first (also: RHR_OFFLINE=1)")
    p_view.set_defaults(func=_view)

    p_scene_dump = sub.add_parser("scene-dump", help="the 3D world as JSON: parts, cameras, lights, "
                                                    "effects, and what is approximated or missing")
    p_scene_dump.add_argument("file", help="Roblox model/place, Rojo project, IR .json, or a Roblox asset id or link")
    p_scene_dump.add_argument("--out", help="write JSON here instead of stdout")
    _test_hooks(p_scene_dump)
    p_scene_dump.set_defaults(func=_scene_dump)

    p_preview = sub.add_parser("preview", help="draw the 3D world with in-world UI and the ScreenGuis "
                                              "over it, to PNG (the one to use when unsure)")
    p_preview.add_argument("file", help="Roblox model/place, Rojo project, IR .json, or a Roblox asset id or link")
    p_preview.add_argument("--out", help="PNG path (default: <input stem>-preview.png)")
    p_preview.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                           help="WxH (default: 1615x1080)")
    _camera_arguments(p_preview)
    _effect_arguments(p_preview)
    p_preview.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for ScreenGui composition (default: 58)",
    )
    p_preview.add_argument("--all-guis", action="store_true",
                           help="in a place, also draw ScreenGuis stored outside StarterGui (templates scripts clone in)")
    p_preview.add_argument("--offline", action="store_true",
                           help="do not download missing assets first (also: RHR_OFFLINE=1)")
    _picture_arguments(p_preview)
    _test_hooks(p_preview)
    p_preview.set_defaults(func=_preview)
    return parser


def _camera_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--camera", type=parse_vector3, metavar="X,Y,Z",
                        help="camera position in studs")
    parser.add_argument("--look-at", type=parse_vector3, metavar="X,Y,Z",
                        help="aim the camera at this point")
    parser.add_argument("--fov", type=parse_fov, help="vertical field of view in degrees")
    parser.add_argument("--focus", metavar="PATH",
                        help="frame this part or model (a path as scene-dump prints it)")
    parser.add_argument("--view", choices=("iso", "front", "back", "left", "right", "top"),
                        help="frame the --focus target, or the whole scene, from this side")
    parser.add_argument("--no-shadows", action="store_true",
                        help="no sun shadows (they are on by default, as in Studio)")
    parser.add_argument("--flat-materials", action="store_true",
                        help="plain colours: no material textures (brick, wood, grass...)")


_NEGATIVE_LIST = re.compile(r"^-(\d|\.\d)[\d.eE+-]*(,\s*-?[\d.eE+-]+)+$")


def _join_negative_lists(argv: list[str]) -> list[str]:
    """`--camera -10,5,3` -> `--camera=-10,5,3`. Before Python 3.13, argparse takes a
    value that starts with `-` for an option unless it is a single number, so a vector
    with a negative first coordinate was rejected."""
    out: list[str] = []
    for token in argv:
        if out and out[-1].startswith("--") and "=" not in out[-1] and _NEGATIVE_LIST.match(token):
            out[-1] = f"{out[-1]}={token}"
        else:
            out.append(token)
    return out


def main(argv: list[str] | None = None) -> int:
    # Instance names can be any Unicode; a Windows console's code page must not crash output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(_join_negative_lists(sys.argv[1:] if argv is None else list(argv)))
    if args.func is not _cache:
        from rhr.cache import maybe_prune

        maybe_prune()  # at most once a day: keeps the cache under its limit
    if getattr(args, "all_guis", False):
        from rhr import pipeline

        pipeline.INCLUDE_STORED_GUIS = True
    if getattr(args, "offline", False):
        # One switch for every download: assets, tools, the browser, font names.
        os.environ["RHR_OFFLINE"] = "1"
    file = getattr(args, "file", None)
    if file and not Path(file).exists():
        from rhr import remote

        if remote.asset_reference(file) is not None:
            # A Roblox asset id or link: downloaded into the cache, then used as a file.
            try:
                args.file = str(remote.resolve(file, login=not getattr(args, "no_studio_login", False)))
            except remote.AssetError as exc:
                return _die(str(exc))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())