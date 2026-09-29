#!/usr/bin/env python3
"""Pictures cut to what an agent needs: --crop, --fit, --max-size, --annotate (rhr.picture).

    python tests/test_picture.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
SHOP = ROOT / "examples" / "shop.rbxmx"


def ui(out: Path, *args: str) -> dict:
    proc = subprocess.run([*RHR, "ui", str(SHOP), "--json", "--out", str(out), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-500:]
    return json.loads(proc.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-picture-") as directory:
        tmp = Path(directory)
        layout = json.loads(subprocess.run([*RHR, "layout", str(SHOP)], cwd=ROOT, capture_output=True, text=True,
                                           timeout=300).stdout)["rects"]
        card = layout["ShopGui/Shop/Items/Item1"]

        report = ui(tmp / "crop.png", "--crop", "ShopGui/Shop/Items/Item1")
        crop = report["crop"]
        assert crop["x"] <= card["x"] and crop["x"] + crop["w"] >= card["x"] + card["w"], (crop, card)
        assert crop["w"] <= card["w"] + 33 and crop["h"] <= card["h"] + 33, (crop, card)  # the element and 16 px
        with Image.open(tmp / "crop.png") as image:
            assert list(image.size) == report["size"] == [crop["w"], crop["h"]], (image.size, report["size"])

        report = ui(tmp / "fit.png", "--fit")
        with Image.open(tmp / "fit.png") as image:
            assert image.width < 1920 and image.height < 1080, image.size

        report = ui(tmp / "small.png", "--max-size", "480")
        assert max(report["size"]) == 480 and report["scale"] == 0.25, report["size"]

        report = ui(tmp / "boxes.png", "--annotate")
        paths = [a["path"] for a in report["annotations"]]
        assert "ShopGui/Shop/Items/Item1/Buy" in paths and [a["n"] for a in report["annotations"]] == list(
            range(1, len(paths) + 1)), paths
        with Image.open(tmp / "boxes.png") as image:
            buy = next(a["rect"] for a in report["annotations"] if a["path"].endswith("Item1/Buy"))
            assert image.convert("RGB").getpixel((int(buy["x"]), int(buy["y"] + buy["h"] / 2))) == (255, 0, 170), \
                "the box's outline is drawn on the button's edge"

        proc = subprocess.run([*RHR, "ui", str(SHOP), "--crop", "Nope", "--out", str(tmp / "x.png")],
                              cwd=ROOT, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 2 and "Nope" in proc.stderr, proc.stderr
    print("picture: crop, fit, max-size and numbered boxes")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
