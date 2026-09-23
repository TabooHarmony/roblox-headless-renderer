#!/usr/bin/env python3
"""Smoke check: real Studio UI models render without blowing up.

These are Roblox's own Studio content models on this machine, not vendored into
this repo (they are Roblox's, and we do not redistribute them). Point the check at
another copy with `RHR_STUDIO_MODELS=/path/to/studiocontent-models`; with no models
present it prints a skip line instead of failing, so the repo stays testable
without a Studio install.

What it proves: the lune IR pass and the adapter survive real content (Content
properties, UDim, instances with hundreds of children) and the renderer paints
something. It does not prove layout correctness; the fixtures do that.

    .venv/bin/python tests/test_studio_smoke.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

MODELS_DIR = Path(os.environ["RHR_STUDIO_MODELS"]) if "RHR_STUDIO_MODELS" in os.environ else None
MODELS = [
    ("RigBuilderGUI", "RigBuilder"),
    ("AnimationEditorGUI", "AnimationEditor"),
    ("ViewSelector", "ViewSelector"),
]


def main() -> int:
    import numpy as np
    from PIL import Image

    from rhr.pipeline import render_ir
    from test_fixtures import emit_ir

    if MODELS_DIR is None:
        print("skip  studio smoke: set RHR_STUDIO_MODELS to a local Studio model directory")
        return 0
    status = 0
    checked = 0
    for name, folder in MODELS:
        model = MODELS_DIR / folder / f"{name}.rbxm"
        if not model.exists():
            continue
        checked += 1
        try:
            t0 = time.time()
            ir = emit_ir(model, REPO / "out" / "smoke" / f"{name}.json")
            t_ir = (time.time() - t0) * 1000
            t0 = time.time()
            png = render_ir(ir, REPO / "out" / "smoke" / f"{name}.png", 1615, 1080,
                            bg_color=(0, 0, 0, 0))
            t_render = (time.time() - t0) * 1000
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {name}: {type(exc).__name__}: {str(exc)[:200]}")
            status = 1
            continue
        img = np.asarray(Image.open(png).convert("RGBA"))
        painted = (img[..., 3] > 0).mean() * 100
        ok = painted > 0
        print(f"{'ok  ' if ok else 'FAIL'}  {name}: ir {t_ir:.0f}ms  render {t_render:.0f}ms  "
              f"painted {painted:.2f}%")
        if not ok:
            status = 1

    if checked == 0:
        print(f"skip  studio smoke: no models under {MODELS_DIR}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())