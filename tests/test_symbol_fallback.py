#!/usr/bin/env python3
"""Symbols no bundled font has are drawn from the system's fonts, not as boxes.

`✕ ★ ✓` appear in many game UIs and are in no bundled or Roblox-shipped face.
With the system fallback on, they draw (so the render differs from the fallback-off
render only where those symbols are); with it off, nothing else changes. Skips when
the host has no font covering them (a bare container).

    python tests/test_symbol_fallback.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "symbol_glyphs.rbxmx"
PLAIN = REPO / "tests" / "fixtures" / "two_screen_guis.rbxmx"
OUT = REPO / "out" / "symbol-fallback"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def render(fixture: Path, name: str, fallback: bool):
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / f"{name}-{'on' if fallback else 'off'}.png"
    env = {**os.environ, "RHR_SYSTEM_FONT_FALLBACK": "1" if fallback else "0"}
    proc = subprocess.run([sys.executable, "-m", "rhr", "render", str(fixture), "--viewport", "300x250",
                           "--topbar-height", "0", "--out", str(png)],
                          capture_output=True, text=True, cwd=str(REPO), env=env, timeout=300)
    assert proc.returncode == 0, proc.stderr
    return Image.open(png).convert("RGB")  # getbbox on RGBA would look at alpha only


def main() -> int:
    import skia
    from PIL import ImageChops

    tf = skia.FontMgr().matchFamilyStyleCharacter("", skia.FontStyle(), [], 0x2715)
    if tf is None:
        print("  skip no system font has U+2715 here")
        return 0

    off, on = render(FIXTURE, "symbols", False), render(FIXTURE, "symbols", True)
    diff = ImageChops.difference(off, on).getbbox()
    check(diff is not None, "with the fallback on, the missing symbols draw differently (not as boxes)")
    # The first glyph, a plain "X" the bundled face has, is untouched.
    check(diff is not None and diff[0] > 30, f"characters the bundled face has do not change ({diff})")

    plain_off, plain_on = render(PLAIN, "plain", False), render(PLAIN, "plain", True)
    check(ImageChops.difference(plain_off, plain_on).getbbox() is None,
          "a UI without such symbols renders identically either way")

    print("symbol fallback: ok" if not failures else f"symbol fallback: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
