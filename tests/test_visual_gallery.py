#!/usr/bin/env python3
"""Representative 3D gallery stays visually populated and feature-complete."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_visual_gallery import GALLERY_MESH_ID, gallery_ir, gallery_mesh_bytes  # noqa: E402

RHR = [sys.executable, "-m", "rhr"]
ASSETS = ROOT / "tests" / "fixtures" / "assets"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*RHR, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def render(ir: Path, mesh_dir: Path, out: Path, *, shadows: bool) -> None:
    args = [
        "preview", str(ir),
        "--viewport", "640x400",
        "--camera", "0,7,-27",
        "--look-at", "0,2.8,1.2",
        "--fov", "48",
        "--texture-dir", str(ASSETS),
        "--mesh-dir", str(mesh_dir),
        "--topbar-height", "0",
    ]
    if shadows:
        args.append("--shadows")
    args.extend(["--out", str(out)])
    proc = run(*args)
    assert proc.returncode == 0, proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-visual-gallery-") as directory:
        tmp = Path(directory)
        ir = tmp / "gallery.json"
        ir.write_text(json.dumps(gallery_ir(), separators=(",", ":")))
        mesh_dir = tmp / "meshes"
        mesh_dir.mkdir()
        (mesh_dir / f"{GALLERY_MESH_ID}.mesh").write_bytes(gallery_mesh_bytes())

        shadowed = tmp / "shadowed.png"
        plain = tmp / "plain.png"
        mesh_fallback = tmp / "mesh-fallback.png"
        empty_mesh_dir = tmp / "empty-meshes"
        empty_mesh_dir.mkdir()
        render(ir, mesh_dir, shadowed, shadows=True)
        render(ir, mesh_dir, plain, shadows=False)
        render(ir, empty_mesh_dir, mesh_fallback, shadows=True)
        # The backdrop (default sky under the gallery's Lighting) varies by row, so
        # "background" means: identical to the same lighting with no geometry or UI.
        backdrop_ir = tmp / "backdrop.json"
        backdrop = json.loads(ir.read_text())
        for root in backdrop["roots"]:
            if root.get("className") != "Lighting":
                root["children"] = [child for child in root.get("children") or [] if child.get("className") == "Camera"]
        backdrop_ir.write_text(json.dumps(backdrop))
        backdrop_png = tmp / "backdrop.png"
        render(backdrop_ir, empty_mesh_dir, backdrop_png, shadows=False)
        with Image.open(backdrop_png).convert("RGB") as backdrop_image:
            background = list(backdrop_image.get_flattened_data())
            background_crop = list(backdrop_image.crop((0, 0, 190, 60)).get_flattened_data())

        with Image.open(shadowed).convert("RGB") as image:
            pixels = list(image.get_flattened_data())
            non_background = sum(pixel != base for pixel, base in zip(pixels, background))
            coverage = non_background / len(pixels)
            unique_colors = len(set(pixels))

            red = blue = cyan = purple = 0
            for r, g, b in pixels:
                if r > 150 and r > g * 1.5 and r > b * 1.5:
                    red += 1
                if b > 140 and b > r * 1.4 and b > g * 1.2:
                    blue += 1
                if g > 130 and b > 130 and r < 120:
                    cyan += 1
                if r > 100 and b > 100 and g < 100:
                    purple += 1

            assert 0.40 < coverage < 0.70, coverage
            assert unique_colors > 2500, unique_colors
            assert red > 500, red
            assert blue > 2000, blue
            assert cyan > 1000, cyan
            assert purple > 1000, purple

            # The composed ScreenGui title occupies this corner and must not vanish.
            hud_crop = image.crop((0, 0, 190, 60))
            hud_non_background = sum(
                pixel != base for pixel, base in zip(hud_crop.get_flattened_data(), background_crop)
            )
            assert hud_non_background > 900, hud_non_background

        with Image.open(shadowed).convert("RGB") as first, Image.open(plain).convert("RGB") as second:
            shadow_delta = sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3
            assert shadow_delta > 2.0, shadow_delta

        with Image.open(shadowed).convert("RGB") as first, Image.open(mesh_fallback).convert("RGB") as second:
            mesh_difference = ImageChops.difference(first, second)
            mesh_delta = sum(ImageStat.Stat(mesh_difference).mean) / 3
            mesh_bbox = mesh_difference.getbbox()
            assert mesh_bbox is not None, "cached mesh made no visible difference from box fallback"
            changed = sum(pixel != (0, 0, 0) for pixel in mesh_difference.get_flattened_data())
            assert changed > 600, changed
            assert mesh_delta > 0.10, mesh_delta

        proc = run(
            "scene-dump", str(ir),
            "--texture-dir", str(ASSETS),
            "--mesh-dir", str(mesh_dir),
        )
        assert proc.returncode == 0, proc.stderr
        dump = json.loads(proc.stdout)
        assert dump["unsupportedVisualClasses"] == {}
        assert dump["fallbacks"] == {}, dump["fallbacks"]
        assert dump["materialFallbacks"] == {}
        refs = dump["assetReferences"]
        assert refs and all(item["available"] for item in refs), refs
        assert len(dump["lights"]) == 2
        assert len(dump["beams"]) == 1
        mesh_refs = dump["meshReferences"]
        assert len(mesh_refs) == 1 and mesh_refs[0]["assetId"] == GALLERY_MESH_ID
        assert mesh_refs[0]["available"] is True

    print(
        "visual gallery: "
        f"coverage={coverage:.1%} colors={unique_colors} "
        f"red={red} blue={blue} cyan={cyan} purple={purple} "
        f"shadow_delta={shadow_delta:.2f} mesh_delta={mesh_delta:.2f} "
        f"mesh_changed={changed} mesh_bbox={mesh_bbox}"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
