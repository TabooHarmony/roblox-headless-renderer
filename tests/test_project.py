#!/usr/bin/env python3
"""Hand-computed tests for the in-world pinhole projection."""

from __future__ import annotations

from math import isclose
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rhr.project import Camera, Vec3, camera_from_cframe, project_billboard, project_point


def identity_camera() -> Camera:
    return camera_from_cframe(
        {
            "X": 0,
            "Y": 0,
            "Z": 10,
            "R00": 1,
            "R01": 0,
            "R02": 0,
            "R10": 0,
            "R11": 1,
            "R12": 0,
            "R20": 0,
            "R21": 0,
            "R22": 1,
        },
        90,
    )


def main() -> None:
    camera = identity_camera()
    point = project_point(Vec3(2, 2, 0), camera, (100, 100))
    assert point is not None
    assert isclose(point.x, 60) and isclose(point.y, 40) and isclose(point.depth, 10)

    rect = project_billboard(Vec3(0, 0, 0), (2, 4), camera, (100, 100))
    assert rect is not None
    assert isclose(rect.x, 45) and isclose(rect.y, 40)
    assert isclose(rect.width, 10) and isclose(rect.height, 20)

    assert project_point(Vec3(0, 0, 11), camera, (100, 100)) is None
    assert project_billboard(Vec3(0, 0, 0), (2, 2), camera, (100, 100), max_distance=9) is None

    clipped = project_billboard(Vec3(9, 0, 0), (2, 2), camera, (100, 100))
    assert clipped is not None
    assert isclose(clipped.x, 90) and isclose(clipped.width, 10)
    assert project_billboard(Vec3(20, 0, 0), (2, 2), camera, (100, 100)) is None
    print("projection: ok")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
