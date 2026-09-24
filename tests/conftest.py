"""Test markers, applied by file so each script stays a plain `main()` script.

    browser  renders through headless Chromium (Playwright)
    lune     converts .rbxm/.rbxmx files to IR through `lune`
    studio   needs local Roblox Studio model files (RHR_STUDIO_MODELS)

`pytest -m "not browser"` runs the quick 2D/IR checks only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Hermetic fonts: tests use RHR's bundled faces only, never a Roblox install that
# happens to be on the machine, so results match CI. Subprocesses inherit this.
os.environ["RHR_ROBLOX_FONTS"] = "0"
os.environ["RHR_SYSTEM_FONT_FALLBACK"] = "0"
os.environ.pop("PINEVEX_RENDERER_ROBLOX_FONT_DIRS", None)

BROWSER = {
    "test_billboard", "test_browser_session", "test_mcp_adapter", "test_particles",
    "test_preview", "test_preview_particles", "test_surface", "test_viewport_frame",
    "test_visual_gallery", "test_place_realism", "test_terrain",
}
NOT_LUNE = {
    "test_compare", "test_groundtruth_diff", "test_mesh_assets", "test_project",
    "test_scroll_scale", "test_text_newlines", "test_textscaled_stroke",
}
STUDIO = {"test_studio_smoke"}


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: renders through headless Chromium")
    config.addinivalue_line("markers", "lune: converts Roblox files through lune")
    config.addinivalue_line("markers", "studio: needs local Roblox Studio model files")


def pytest_collection_modifyitems(items):
    for item in items:
        name = Path(str(item.fspath)).stem
        is_scene = name.startswith("test_scene") and name != "test_scene_dump"
        if name in BROWSER or is_scene:
            item.add_marker(pytest.mark.browser)
        if name not in NOT_LUNE:
            item.add_marker(pytest.mark.lune)
        if name in STUDIO:
            item.add_marker(pytest.mark.studio)
