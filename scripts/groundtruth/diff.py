#!/usr/bin/env python3
"""Compare two same-sized captures with explicit pixel tolerances."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from PIL import Image


RGB = tuple[int, int, int]
def load(path: Path, background: RGB) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    bg = Image.new("RGBA", image.size, (*background, 255))
    return Image.alpha_composite(bg, image).convert("RGB")


def compare(a: Image.Image, b: Image.Image) -> dict:
    if a.size != b.size:
        raise ValueError(f"image sizes differ: {a.width}x{a.height} vs {b.width}x{b.height}")
    width, height = a.size
    pixels_a = [a.getpixel((x, y)) for y in range(height) for x in range(width)]
    pixels_b = [b.getpixel((x, y)) for y in range(height) for x in range(width)]
    deltas = [tuple(abs(x - y) for x, y in zip(cast(RGB, left), cast(RGB, right))) for left, right in zip(pixels_a, pixels_b)]
    differing = [index for index, delta in enumerate(deltas) if any(delta)]
    max_delta = max((max(delta) for delta in deltas), default=0)
    width, height = a.size
    bbox = None
    if differing:
        xs = [index % width for index in differing]
        ys = [index // width for index in differing]
        bbox = {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1}
    total = len(deltas)
    return {
        "size": {"width": width, "height": height},
        "pixels": total,
        "exact_match_percent": round(100 * sum(not any(delta) for delta in deltas) / total, 6),
        "within_2_percent": round(100 * sum(max(delta) <= 2 for delta in deltas) / total, 6),
        "within_8_percent": round(100 * sum(max(delta) <= 8 for delta in deltas) / total, 6),
        "differing_pixels": len(differing),
        "max_channel_delta": max_delta,
        "difference_bbox": bbox,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("studio", type=Path, help="Studio PNG")
    parser.add_argument("rhr", type=Path, help="RHR PNG")
    parser.add_argument("--background", default="20242b", help="RRGGBB used to flatten alpha")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args()
    raw = args.background.lstrip("#")
    if len(raw) != 6:
        parser.error("background must be RRGGBB")
    try:
        background: RGB = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        result = compare(load(args.studio, background), load(args.rhr, background))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"size              {result['size']['width']}x{result['size']['height']}")
        print(f"exact match       {result['exact_match_percent']:.6f}%")
        print(f"within 2/255      {result['within_2_percent']:.6f}%")
        print(f"within 8/255      {result['within_8_percent']:.6f}%")
        print(f"differing pixels  {result['differing_pixels']}")
        print(f"max channel delta {result['max_channel_delta']}")
        print(f"difference bbox   {result['difference_bbox']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
