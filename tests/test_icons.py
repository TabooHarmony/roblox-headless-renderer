#!/usr/bin/env python3
"""`rhr icons`: square, transparent icons cropped to the model (rhr.icons).

The crop and padding are checked on a made-up image; then two fixture models are
drawn as one batch: each icon is square, has see-through corners, is not empty, and
leaves the same empty border on its widest side.

    python tests/test_icons.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

failures: list[str] = []
MODELS = [REPO / "tests" / "fixtures" / "scene_geometry.rbxmx", REPO / "tests" / "fixtures" / "scene_model_scale.rbxmx"]


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def border(image) -> tuple[int, int, int, int]:
    box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return (box[0], box[1], image.width - box[2], image.height - box[3]) if box else (0, 0, 0, 0)


def cropping(tmp: Path) -> None:
    from PIL import Image
    from rhr import icons

    print("the crop: what was drawn, padded to a square")
    raw = tmp / "raw.png"
    image = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (100, 100, 300, 150))  # 200 x 50
    image.save(raw)
    out = tmp / "icon.png"
    check(icons.finish(raw, out, 100, 0.1, None), "something was drawn")
    with Image.open(out) as icon:
        check(icon.size == (100, 100), f"square at the asked size: {icon.size}")
        left, top, right, bottom = border(icon)
        check(abs(left - 8) <= 1 and abs(right - 8) <= 1, f"the widest side keeps the margin: {left}, {right}")
        check(abs(top - bottom) <= 1 and top > 30, f"centred the other way: {top}, {bottom}")
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(raw)
    check(not icons.finish(raw, out, 64, 0.1, None), "an empty render is reported, not saved as an icon")


def batch(tmp: Path) -> None:
    from PIL import Image

    print("a batch of two fixture models")
    proc = subprocess.run([sys.executable, "-m", "rhr", "icons", *map(str, MODELS), "--out-dir", str(tmp / "icons"),
                           "--size", "256", "--offline"], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(proc.returncode == 0, f"exit code {proc.returncode}: {proc.stderr.strip().splitlines()[-1:]}")
    for model in MODELS:
        path = tmp / "icons" / f"{model.stem}.png"
        check(path.is_file(), f"{path.name} written")
        if not path.is_file():
            continue
        with Image.open(path) as icon:
            icon = icon.convert("RGBA")
            check(icon.size == (256, 256), f"{path.name}: 256 x 256")
            check(icon.getpixel((0, 0))[3] == 0 and icon.getpixel((255, 255))[3] == 0, f"{path.name}: see-through corners")
            opaque = icon.getchannel("A").point(lambda a: 255 if a > 8 else 0).histogram()[255]
            check(opaque > 256 * 256 * 0.1, f"{path.name}: the model fills the icon ({opaque} px)")
            left, top, right, bottom = border(icon)
            check(min(left, right) <= 18 or min(top, bottom) <= 18, f"{path.name}: cropped close: {left, top, right, bottom}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-icons-test-") as directory:
        cropping(Path(directory))
        batch(Path(directory))
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("icons: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
