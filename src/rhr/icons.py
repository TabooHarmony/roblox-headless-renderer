"""`rhr icons`: many models to icons: square PNGs, the model alone on a transparent
background, cropped to it with the same margin on every icon.

Each model is drawn by the scene page in icon mode (`icon=1`: no sky, clouds or fog)
on one page kept loaded for the whole batch, at 1024 px, then cropped to what was
drawn, padded to a square and scaled to `size`. The first icon pays for starting a
browser; the rest cost the scene itself (about half a second for a small model).
"""

from __future__ import annotations

import http.server
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

RENDER_PX = 1024
MODEL_SUFFIXES = {".rbxm", ".rbxmx"}


def inputs(items: list[str]) -> list[str]:
    """Files, folders (their .rbxm/.rbxmx files, sorted) and asset references, in order."""
    out: list[str] = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            out += [str(p) for p in sorted(path.rglob("*")) if p.suffix.lower() in MODEL_SUFFIXES]
        else:
            out.append(item)
    return out


def finish(raw: Path, out: Path, size: int, margin: float, background: tuple[int, int, int, int] | None) -> bool:
    """Crop the render to what was drawn, pad to a square, scale to `size`. False when
    nothing was drawn."""
    from PIL import Image

    with Image.open(raw) as image:
        image = image.convert("RGBA")
        box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if box is None:
            return False
        cropped = image.crop(box)
    side = max(cropped.size)
    pad = round(side * margin)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.paste(cropped, (pad + (side - cropped.width) // 2, pad + (side - cropped.height) // 2))
    icon = canvas.resize((size, size), Image.LANCZOS)
    if background is not None:
        flat = Image.new("RGBA", icon.size, background)
        flat.alpha_composite(icon)
        icon = flat
    out.parent.mkdir(parents=True, exist_ok=True)
    icon.save(out)
    return True


class Renderer:
    """One browser and one kept, see-through scene page for the whole batch."""

    def __init__(self):
        self.browser = None
        self.kept = None

    def draw(self, ir_path: Path, out: Path, query: dict) -> None:
        from rhr import scene as scene_module
        from rhr.browser_render import KeptScenePage, launch

        if self.browser is None:
            self.browser, _ = launch()
            self.kept = KeptScenePage(self.browser, page_query="persistent=1&alpha=1", transparent=True)
        images, meshes = scene_module.cached_asset_files()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), scene_module.scene_handler(ir_path, images, meshes))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            self.kept.render(query=urlencode(query), base=f"http://127.0.0.1:{server.server_port}",
                             out=out, width=RENDER_PX, height=RENDER_PX)
        except (RuntimeError, OSError, TimeoutError):
            self.kept.close()  # a fresh page for the next one
            raise
        finally:
            server.shutdown()
            thread.join(timeout=2)

    def close(self) -> None:
        if self.kept is not None:
            self.kept.close()
        if self.browser is not None:
            self.browser.close()


def run(items: list[str], *, out_dir: Path, size: int, view: str, margin: float, fov: float,
        background, shadows: bool, effects: bool, prepare, resolve, log=None) -> int:
    """Draw an icon for every input; `prepare(source) -> ir_path` converts one and fetches
    its assets, `resolve(item) -> Path` turns an asset id or link into a file. Exit code."""
    import tempfile

    log = log or (lambda message: print(message, file=sys.stderr))
    query = {"icon": "1", "view": view, "fov": fov, "shadows": "1" if shadows else "0"}
    if not effects:
        query["effects"] = "0"
    renderer = Renderer()
    done, failed = 0, 0
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="rhr-icons-") as scratch:
            for item in inputs(items):
                begun = time.perf_counter()
                try:
                    source = resolve(item)
                    out = out_dir / f"{source.stem}.png"
                    raw = Path(scratch) / f"{source.stem}.raw.png"
                    renderer.draw(prepare(source), raw, query)
                    if not finish(raw, out, size, margin, background):
                        raise RuntimeError("nothing to draw (no visible 3D geometry)")
                except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                    failed += 1
                    log(f"icon   {item}: {str(exc).splitlines()[0]}")
                    continue
                done += 1
                print(out, flush=True)
                log(f"icon   {out}  {(time.perf_counter() - begun) * 1000:.0f}ms")
    finally:
        renderer.close()
    log(f"icons  {done} drawn" + (f", {failed} failed" if failed else "")
        + f" in {time.perf_counter() - started:.1f}s")
    return 0 if done and not failed else 2
