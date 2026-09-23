#!/usr/bin/env python3
"""Regression tests for the Studio/RHR pixel comparison."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.groundtruth.diff import compare, load


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-groundtruth-") as directory:
        root = Path(directory)
        first = root / "first.png"
        second = root / "second.png"
        Image.new("RGBA", (4, 3), (10, 20, 30, 255)).save(first)
        Image.new("RGBA", (4, 3), (10, 20, 32, 255)).save(second)
        result = compare(load(first, (0, 0, 0)), load(second, (0, 0, 0)))
        assert result["pixels"] == 12
        assert result["exact_match_percent"] == 0.0
        assert result["within_2_percent"] == 100.0
        assert result["within_8_percent"] == 100.0
        assert result["max_channel_delta"] == 2
        assert result["difference_bbox"] == {"x": 0, "y": 0, "w": 4, "h": 3}
    print("groundtruth diff: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
