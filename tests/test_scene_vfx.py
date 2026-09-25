#!/usr/bin/env python3
"""Particles are drawn inside the 3D scene, played from their EmitCount/EmitDelay attributes.

Fixture (scripts/make_vfx_fixture.luau): two disabled red emitters that a script would
play (EmitCount 40 at EmitDelay 0.5), the left one behind a black wall; a running green
emitter on an attachment turned to fire along +X; a disabled emitter with no
attributes, which is reported and not drawn.
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
FIXTURE = ROOT / "tests" / "fixtures" / "vfx_played.rbxm"
CAMERA = ["--viewport", "480x320", "--camera", "0,5,30", "--look-at", "0,8,0"]


def run(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    return proc


def pixels(path: Path, test) -> list[tuple[int, int]]:
    with Image.open(path).convert("RGB") as image:
        width, height = image.size
        data = image.load()
        return [(x, y) for y in range(height) for x in range(width) if test(*data[x, y])]


def red(r, g, b):
    return r > 150 and g < 120 and b < 120


def green(r, g, b):
    return g > 150 and r < 150 and b < 150


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-vfx-") as directory:
        tmp = Path(directory)
        ir = tmp / "vfx.json"
        run("ir", str(FIXTURE), "--out", str(ir))
        nodes = [node for root in json.loads(ir.read_text(encoding="utf-8"))["roots"] for node in walk(root)]
        bursts = [node for node in nodes if node.get("name") == "Burst"]
        assert len(bursts) == 2 and all(node.get("attributes") == {"EmitCount": 40, "EmitDelay": 0.5} for node in bursts), bursts

        auto = tmp / "auto.png"
        proc = run("scene", str(FIXTURE), *CAMERA, "--out", str(auto))
        # A burst is fullest from the moment it is emitted until it dies (0.5 to 1.5 s);
        # the middle of that stretch is shown, not the instant every particle sits on one spot.
        assert "played from their EmitCount/EmitDelay/EmitDuration attributes, at 1.00 s" in proc.stderr, proc.stderr
        assert "1 ParticleEmitter(s) are disabled and have no EmitCount/EmitDuration" in proc.stderr, proc.stderr
        assert "PlayedByScript" in proc.stderr, proc.stderr

        reds = pixels(auto, red)
        assert len(reds) > 40, f"the played burst is not drawn ({len(reds)} red pixels)"
        # The camera looks at x = 0: the right burst is right of centre; the left one
        # is behind the wall, so nothing red shows left of centre.
        left = [p for p in reds if p[0] < 240]
        assert not left, f"{len(left)} red pixels show through the wall"

        greens = pixels(auto, green)
        assert len(greens) > 40, f"the running stream is not drawn ({len(greens)} green pixels)"
        xs = [p[0] for p in greens]
        ys = [p[1] for p in greens]
        assert max(xs) - min(xs) > 3 * (max(ys) - min(ys)), "the stream does not run sideways"
        assert sum(xs) / len(xs) > 240, "the stream does not follow its attachment's turn toward +X"

        early = tmp / "early.png"
        run("scene", str(FIXTURE), *CAMERA, "--effect-time", "0.2", "--out", str(early))
        assert not pixels(early, red), "the burst shows before its EmitDelay"
        assert pixels(early, green), "a running emitter is already full at the start"

        off = tmp / "off.png"
        run("scene", str(FIXTURE), *CAMERA, "--no-effects", "--out", str(off))
        assert not pixels(off, red) and not pixels(off, green), "--no-effects still draws particles"

    print(
        f"vfx: played burst {len(reds)} px (none through the wall), sideways stream "
        f"{max(xs) - min(xs)}x{max(ys) - min(ys)} px, nothing before EmitDelay, --no-effects clean"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
