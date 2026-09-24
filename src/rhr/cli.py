"""rhr: the command line for this renderer.

    rhr ir     <model>                 --out ir.json
    rhr render <model|ir.json>         [--out out.png] [--viewport 1615x1080]
                                       [--transparent] [--background RRGGBB]
                                       [--ir out.json] [--dump-layout layout.json]
    rhr layout <model|ir.json>         [--viewport 1615x1080] [--out layout.json]
                                       [--rich]
    rhr hitmap <model|ir.json>         [--viewport 1615x1080] [--out hitmap.json]
    rhr scene  <model|ir.json>         [--out out.png] [--viewport 1615x1080]
    rhr scene-dump <model|ir.json>      [--out scene.json]
    rhr preview <model|ir.json>         [--out preview.png] [scene camera options]
    rhr particles <model|ir.json>      [--times 0,0.5,1] [--out sheet.png]

Everything the test harness does, a human can do from here: real files, real
timings, and the layout dump is the measurement the renderer exists to get right.

Input is either a Roblox model (.rbxm/.rbxmx/.rbxl/.rbxlx), which is dumped to our
IR with lune + rbx-dom first, or an IR JSON file already on disk. Reasoning about
an IR file twice does not need to re-run rbx-dom, so `--ir` (and `render` on a
.json) lets a caller cache it.

Machine-readable habit: JSON goes to stdout, progress and timings to stderr, so
`rhr layout model.rbxm > layout.json` is safe.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

from rhr.paths import IR_DIR
from rhr.schema import stamp


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


def parse_times(text: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"times must be comma-separated numbers, got {text!r}") from None
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise argparse.ArgumentTypeError(f"times must contain non-negative finite numbers, got {text!r}")
    return values


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


def parse_nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text!r}")
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


def ir_for(source: Path, ir_out: Path | None, *, profile: str = "full") -> Path:
    """IR JSON for `source`: the file itself if it is IR, else a fresh lune dump.

    `source` may also be a Rojo project (a *.project.json file or a directory with
    default.project.json), which is built with `rojo build` first.
    """
    from rhr.ir import cached_ir, emit_ir, load_ir
    from rhr import rojo

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
    if ir_out is None:
        return cached_ir(source, profile=profile)
    return emit_ir(source, ir_out, profile=profile)


def rect_to_dict(rect) -> dict:
    """The engine's RRect as plain JSON: ui_engine.layout.Rect(x, y, w, h)."""
    x, y = getattr(rect, "x", getattr(rect, "left", None)), getattr(rect, "y", getattr(rect, "top", None))
    w, h = getattr(rect, "w", None), getattr(rect, "h", None)
    if None in (x, y, w, h):
        raise TypeError(f"cannot read x/y/w/h out of {rect!r}")
    return {"x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3)}


def _render(args) -> int:
    from rhr.pipeline import load_screens, render_screens

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    bg = (0, 0, 0, 0) if args.transparent else args.background
    out = Path(args.out) if args.out else Path(f"{source.stem}.png")
    rect_map: dict = {} if args.dump_layout else None

    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, Path(args.ir) if args.ir else None)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))
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
        f"render {png}  {width}x{height}  {int((t_render - t_ir) * 1000)}ms",
        file=sys.stderr,
    )
    print(f"total  {int((t_render - t0) * 1000)}ms", file=sys.stderr)

    if rect_map is not None:
        layout = {path: rect_to_dict(rect) for path, rect in rect_map.items()}
        document = stamp("layout", {"viewport": [width, height], "rects": layout})
        Path(args.dump_layout).parent.mkdir(parents=True, exist_ok=True)
        Path(args.dump_layout).write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        print(f"layout {args.dump_layout}  {len(layout)} rects", file=sys.stderr)
        if not layout and screens:
            print(
                "rhr: the layout dump is empty. That is a bug in the pipeline, not an "
                "empty UI: nodes reach the renderer without a _path.",
                file=sys.stderr,
            )
            return 1
    print(png)
    return 0


def _layout(args) -> int:
    from rhr.pipeline import load_screens, render_screens

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    try:
        ir_path = ir_for(source, Path(args.ir) if args.ir else None)
        screens = load_screens(str(ir_path), width, height, args.topbar_height)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))

    # --rich is Task 2.1's structured dump: the same paint pass, plus what each
    # node is made of (zIndex, visibility, resolved colours, text, clip state).
    # Plain `rhr layout` stays exactly what Phase 1 shipped.
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
            print(
                "rhr: the structured dump is empty. That is a bug in the pipeline, "
                "not an empty UI: nodes reached the renderer without a _path.",
                file=sys.stderr,
            )
            return 1
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(args.out, file=sys.stderr)
        else:
            print(text)
        print(f"dump {count} nodes  {elapsed}ms", file=sys.stderr)
        return 0

    # A rect is resolved by laying the tree out, which is what rendering does, so
    # this draws once and keeps the geometry. The PNG is never shown: it is the
    # side effect that produces the map (see render_json(rect_map=...) upstream).
    # Every ScreenGui is laid out, so the dump is the whole UI, not the top pane.
    rect_map: dict = {}
    render_screens(
        screens,
        IR_DIR / f"{source.stem}-layout.png",
        width,
        height,
        bg_color=(0, 0, 0, 0),
        rect_map=rect_map,
    )
    for _, _, inset, name in screens:
        label = f"{name}: " if len(screens) > 1 else ""
        print(f"inset  {label}{inset.describe()}", file=sys.stderr)
    layout = {path: rect_to_dict(rect) for path, rect in rect_map.items()}
    if not layout and screens:
        print("rhr: no rects resolved: nodes reached the renderer without a _path", file=sys.stderr)
        return 1
    # JSON on stdout, the count on stderr, so `rhr layout model.rbxm | jq` works.
    print(f"layout {len(layout)} rects", file=sys.stderr)
    document = stamp("layout", {"viewport": [width, height], "rects": layout})
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        print(args.out, file=sys.stderr)
    else:
        print(json.dumps(document, indent=2, sort_keys=True))
    return 0


def _fetch(args) -> int:
    from rhr import fetch

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    try:
        ir_path = ir_for(source, None)
    except (ValueError, RuntimeError) as exc:
        return _die(str(exc))
    return fetch.run(ir_path, images=not args.meshes_only, meshes=not args.images_only)


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
        result = check_model(ir_for(source, None), width, height, topbar_height=args.topbar_height)
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
    print(json.dumps(stamp("browser", result), sort_keys=True))
    return 0


def _compare(args) -> int:
    from rhr.diff import compare, format_report

    before = Path(args.before)
    after = Path(args.after)
    for path in (before, after):
        if not path.exists():
            return _die(f"no such file: {path}")
    metrics = compare(before, after, bg=args.background[:3], silhouette_threshold=args.silhouette_threshold)
    if args.json:
        print(json.dumps(stamp("compare", metrics), indent=2, sort_keys=True))
    else:
        print(format_report(metrics))
    return 0 if metrics.get("size_match") else 2


def _hitmap(args) -> int:
    from rhr.hitmap import build_hitmap, dump_json

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, Path(args.ir) if args.ir else None)
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
        ir_path = ir_for(source, Path(args.ir) if args.ir else None, profile="static")
        page_notes: list[str] = []
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
            shadows=args.shadows,
            flat_materials=args.flat_materials,
            texture_dir=texture_dir,
            mesh_dir=mesh_dir,
            notes_out=page_notes,
        )
        from rhr.scene_dump import build_scene_dump, notes_line

        notes = notes_line(build_scene_dump(ir_path, texture_dir=texture_dir, mesh_dir=mesh_dir))
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"ir     {ir_path}", file=sys.stderr)
    print(f"scene  {out}  {actual[0]}x{actual[1]}  {elapsed}ms", file=sys.stderr)
    print(notes, file=sys.stderr)
    for note in page_notes:
        print(f"note   {note}", file=sys.stderr)
    print(out)
    return 0


def _preview(args) -> int:
    from PIL import Image
    from rhr.pipeline import load_screens, render_screens
    from rhr.scene import render_particle_sheet, render_scene

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    out = Path(args.out) if args.out else Path(f"{source.stem}-preview.png")
    texture_dir = Path(args.texture_dir) if args.texture_dir else None
    mesh_dir = Path(args.mesh_dir) if args.mesh_dir else None
    t0 = time.perf_counter()
    try:
        profile = "visual" if args.time is not None else "static"
        ir_path = ir_for(source, Path(args.ir) if args.ir else None, profile=profile)
        with tempfile.TemporaryDirectory(prefix="rhr-preview-") as directory:
            tmp = Path(directory)
            world = tmp / "world.png"
            effects = tmp / "effects.png"
            ui = tmp / "ui.png"
            resolved_camera: dict = {}
            page_notes: list[str] = []
            render_scene(
                ir_path,
                world,
                width,
                height,
                camera=args.camera,
                look_at=args.look_at,
                fov=args.fov,
                focus=args.focus,
                view=args.view,
                shadows=args.shadows,
                flat_materials=args.flat_materials,
                texture_dir=texture_dir,
                mesh_dir=mesh_dir,
                camera_state_out=resolved_camera if args.time is not None else None,
                notes_out=page_notes,
            )
            screens = load_screens(
                str(ir_path),
                width,
                height,
                args.topbar_height,
                screen_gui_only=True,
            )
            with Image.open(world).convert("RGBA") as composite:
                if args.time is not None:
                    position = resolved_camera.get("position")
                    quaternion = resolved_camera.get("quaternion")
                    resolved_fov = resolved_camera.get("fov")
                    if not (
                        isinstance(position, list) and len(position) == 3
                        and isinstance(quaternion, list) and len(quaternion) == 4
                        and isinstance(resolved_fov, (int, float))
                    ):
                        raise RuntimeError("scene renderer did not report its resolved camera for particle composition")
                    render_particle_sheet(
                        ir_path,
                        effects,
                        width,
                        height,
                        [args.time],
                        args.seed,
                        args.burst,
                        texture_dir,
                        effects_only=True,
                        camera=tuple(position),
                        camera_quaternion=tuple(quaternion),
                        fov=float(resolved_fov),
                    )
                    with Image.open(effects).convert("RGBA") as particle_layer:
                        composite.alpha_composite(particle_layer)
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
    try:
        from rhr.scene_dump import build_scene_dump, notes_line

        print(notes_line(build_scene_dump(ir_path)), file=sys.stderr)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"notes  unavailable: {exc}", file=sys.stderr)
    for note in page_notes:
        print(f"note    {note}", file=sys.stderr)
    print(out)
    return 0


def _scene_dump(args) -> int:
    from rhr.scene_dump import build_scene_dump, dump_json

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, Path(args.ir) if args.ir else None)
        scene_dump = build_scene_dump(
            ir_path,
            texture_dir=Path(args.texture_dir) if args.texture_dir else None,
            mesh_dir=Path(args.mesh_dir) if args.mesh_dir else None,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    text = dump_json(scene_dump)
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


def _particles(args) -> int:
    from rhr.scene import render_particle_sheet

    source = Path(args.file)
    if not source.exists():
        return _die(f"no such file: {source}")
    width, height = args.viewport
    out = Path(args.out) if args.out else Path(f"{source.stem}-particles.png")
    t0 = time.perf_counter()
    try:
        ir_path = ir_for(source, Path(args.ir) if args.ir else None, profile="visual")
        actual = render_particle_sheet(
            ir_path, out, width, height, args.times, args.seed, args.burst,
            Path(args.texture_dir) if args.texture_dir else None,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return _die(str(exc))
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"ir       {ir_path}", file=sys.stderr)
    print(f"particles {out}  {actual[0]}x{actual[1]}  {len(args.times)} frames  burst={args.burst}  {elapsed}ms", file=sys.stderr)
    print(out)
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

    p_setup = sub.add_parser("setup", help="download Lune, Rojo and Chromium if they are missing")
    p_setup.add_argument("--no-rojo", action="store_true", help="skip Rojo (only needed for Rojo projects)")
    p_setup.set_defaults(func=lambda a: __import__("rhr.tools").tools.setup(rojo=not a.no_rojo))

    p_fetch = sub.add_parser(
        "fetch", help="download the images and meshes a model uses into the local cache (needs network)")
    p_fetch.add_argument("file", help="Roblox model/place, Rojo project, or IR .json")
    only = p_fetch.add_mutually_exclusive_group()
    only.add_argument("--images-only", action="store_true", help="fetch images only")
    only.add_argument("--meshes-only", action="store_true", help="fetch meshes only")
    p_fetch.set_defaults(func=_fetch)

    p_doctor = sub.add_parser("doctor", help="check what RHR needs and say what is missing")
    p_doctor.set_defaults(func=lambda a: __import__("rhr.tools").tools.doctor())

    p_ir = sub.add_parser("ir", help="dump our IR for a Roblox model")
    p_ir.add_argument("file", help=".rbxm/.rbxmx/.rbxl/.rbxlx")
    p_ir.add_argument("--out", required=True, help="where to write the IR JSON")
    p_ir.set_defaults(func=_ir)

    p_render = sub.add_parser("render", help="render a model or an IR file to PNG")
    p_render.add_argument("file", help="Roblox model or IR .json")
    p_render.add_argument("--out", help="PNG path (default: <input stem>.png)")
    p_render.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                          help="WxH (default: 1615x1080)")
    p_render.add_argument("--transparent", action="store_true",
                          help="alpha background instead of an opaque one")
    p_render.add_argument("--background", type=parse_background, default=(255, 255, 255, 255),
                          help="RRGGBB or RRGGBBAA (default: ffffff)")
    p_render.add_argument("--ir", help="where to write the IR when the input is a model")
    p_render.add_argument("--dump-layout", help="write resolved rects as JSON here")
    p_render.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58, "
             "see docs/known-approximations.md)",
    )
    p_render.set_defaults(func=_render)

    p_layout = sub.add_parser("layout", help="resolved rect per node, as JSON")
    p_layout.add_argument("file", help="Roblox model or IR .json")
    p_layout.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT)
    p_layout.add_argument("--out", help="write JSON here instead of stdout")
    p_layout.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_layout.add_argument(
        "--rich",
        action="store_true",
        help="the structured dump (Task 2.1): per node, class, rect, zIndex, "
             "visible, resolved colours, text, font size and clip state",
    )
    p_layout.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_layout.set_defaults(func=_layout)

    p_check = sub.add_parser("check", help="model smells that should fail a build, as JSON findings")
    p_check.add_argument("file", help="Roblox model or IR .json")
    p_check.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT)
    p_check.add_argument("--out", help="write JSON here instead of stdout")
    p_check.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_check.set_defaults(func=_check)

    p_browser = sub.add_parser("browser", help="manage the optional persistent Chromium render worker")
    p_browser.add_argument("action", choices=("start", "status", "stop"))
    p_browser.set_defaults(func=_browser)

    p_compare = sub.add_parser("compare", help="measure pixel and silhouette changes between two PNGs")
    p_compare.add_argument("before", help="reference/before PNG")
    p_compare.add_argument("after", help="after PNG")
    p_compare.add_argument("--background", type=parse_background, default=(32, 36, 43, 255),
                           help="RRGGBB background used to flatten alpha (default: 20242b)")
    p_compare.add_argument("--silhouette-threshold", type=float, default=8.0,
                           help="max-channel distance from background that counts as silhouette (default: 8)")
    p_compare.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_compare.set_defaults(func=_compare)

    p_hitmap = sub.add_parser("hitmap", help="interactive GUI hit regions, as JSON")
    p_hitmap.add_argument("file", help="Roblox model or IR .json")
    p_hitmap.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT)
    p_hitmap.add_argument("--out", help="write JSON here instead of stdout")
    p_hitmap.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_hitmap.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for a CoreUISafeInsets ScreenGui (default: 58)",
    )
    p_hitmap.set_defaults(func=_hitmap)

    p_scene = sub.add_parser("scene", help="render 3D Parts through headless Chromium")
    p_scene.add_argument("file", help="Roblox model or IR .json")
    p_scene.add_argument("--out", help="PNG path (default: <input stem>-scene.png)")
    p_scene.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                         help="WxH (default: 1615x1080)")
    p_scene.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_scene.add_argument("--camera", type=parse_vector3, metavar="X,Y,Z",
                         help="override camera world position")
    p_scene.add_argument("--look-at", type=parse_vector3, metavar="X,Y,Z",
                         help="aim the camera at this world point")
    p_scene.add_argument("--fov", type=parse_fov, help="override vertical field of view in degrees")
    p_scene.add_argument("--focus", metavar="PATH",
                         help="auto-frame this exact IR path (use scene-dump to discover paths)")
    p_scene.add_argument("--view", choices=("iso", "front", "back", "left", "right", "top"),
                         help="auto-frame the focus target, or the whole scene when --focus is omitted")
    p_scene.add_argument("--shadows", action="store_true",
                         help="enable bounded directional shadows (off by default; SwiftShader cost is measured)")
    p_scene.add_argument("--flat-materials", action="store_true",
                         help="plain colours: no material textures (brick, wood, grass...)")
    p_scene.add_argument("--texture-dir",
                         help="local directory containing <asset_id>.<ext> textures/decals")
    p_scene.add_argument("--mesh-dir",
                         help="local directory containing decompressed <asset_id>.mesh files")
    p_scene.add_argument("--coverage", action="store_true",
                         help="no-op: the fallback/experimental notes line is always printed")
    p_scene.set_defaults(func=_scene)

    p_scene_dump = sub.add_parser("scene-dump", help="machine-readable static 3D geometry and fallback summary")
    p_scene_dump.add_argument("file", help="Roblox model or IR .json")
    p_scene_dump.add_argument("--out", help="write JSON here instead of stdout")
    p_scene_dump.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_scene_dump.add_argument("--texture-dir",
                              help="local directory containing <asset_id>.<ext> textures/decals")
    p_scene_dump.add_argument("--mesh-dir",
                              help="local directory containing decompressed <asset_id>.mesh files")
    p_scene_dump.set_defaults(func=_scene_dump)

    p_preview = sub.add_parser("preview", help="compose static 3D world/in-world UI with ScreenGui")
    p_preview.add_argument("file", help="Roblox model or IR .json")
    p_preview.add_argument("--out", help="PNG path (default: <input stem>-preview.png)")
    p_preview.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                           help="WxH (default: 1615x1080)")
    p_preview.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_preview.add_argument("--camera", type=parse_vector3, metavar="X,Y,Z",
                           help="override camera world position")
    p_preview.add_argument("--look-at", type=parse_vector3, metavar="X,Y,Z",
                           help="aim the camera at this world point")
    p_preview.add_argument("--fov", type=parse_fov, help="override vertical field of view in degrees")
    p_preview.add_argument("--focus", metavar="PATH", help="auto-frame this exact IR path")
    p_preview.add_argument("--view", choices=("iso", "front", "back", "left", "right", "top"),
                           help="auto-frame the focus target or whole scene")
    p_preview.add_argument("--shadows", action="store_true", help="enable bounded directional shadows")
    p_preview.add_argument("--flat-materials", action="store_true",
                           help="plain colours: no material textures (brick, wood, grass...)")
    p_preview.add_argument("--texture-dir", help="local directory containing <asset_id>.<ext> textures/decals")
    p_preview.add_argument("--mesh-dir", help="local directory containing decompressed <asset_id>.mesh files")
    p_preview.add_argument("--time", type=float,
                           help="compose deterministic ParticleEmitters at this time in seconds")
    p_preview.add_argument("--seed", type=int, default=0,
                           help="particle simulation seed for --time")
    p_preview.add_argument("--burst", type=parse_nonnegative_int, default=0,
                           help="emit this many particles immediately per emitter for --time")
    p_preview.add_argument(
        "--topbar-height",
        type=float,
        default=None,
        help="top bar inset in px for ScreenGui composition (default: 58)",
    )
    p_preview.set_defaults(func=_preview)

    p_particles = sub.add_parser("particles", help="render a deterministic particle contact sheet")
    p_particles.add_argument("file", help="Roblox model or IR .json")
    p_particles.add_argument("--out", help="PNG contact sheet (default: <input stem>-particles.png)")
    p_particles.add_argument("--viewport", type=parse_viewport, default=DEFAULT_VIEWPORT,
                             help="tile WxH (default: 1615x1080)")
    p_particles.add_argument("--times", type=parse_times, default=[0.0, 0.5, 1.0],
                             help="comma-separated seconds (default: 0,0.5,1)")
    p_particles.add_argument("--seed", type=int, default=0, help="deterministic simulation seed")
    p_particles.add_argument("--burst", type=parse_nonnegative_int, default=0,
                             help="emit this many particles immediately per emitter")
    p_particles.add_argument("--texture-dir", help="local directory containing <asset_id>.<ext> particle textures")
    p_particles.add_argument("--ir", help="cache the IR dump here when the input is a model")
    p_particles.set_defaults(func=_particles)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Instance names can be any Unicode; a Windows console's code page must not crash output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())