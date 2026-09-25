"""Test markers, applied by file so each script stays a plain `main()` script.

    browser  renders through headless Chromium (Playwright)
    lune     converts .rbxm/.rbxmx files to IR through `lune`
    studio   needs local Roblox Studio model files (RHR_STUDIO_MODELS)

`pytest -m "not browser"` runs the quick 2D/IR checks only.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Hermetic fonts: tests use RHR's bundled faces only, never a Roblox install that
# happens to be on the machine, so results match CI. Subprocesses inherit this.
os.environ["RHR_ROBLOX_FONTS"] = "0"
os.environ["RHR_SYSTEM_FONT_FALLBACK"] = "0"
# Hermetic 3D: no downloads (and never the Studio login), no Studio install textures.
os.environ["RHR_OFFLINE"] = "1"
os.environ["RHR_STUDIO_DIR"] = "0"
# Software WebGL: the same pixels on every machine, whatever its GPU.
os.environ["RHR_WEBGL"] = "software"
os.environ.pop("PINEVEX_RENDERER_ROBLOX_FONT_DIRS", None)


# Hermetic caches: the suite gets an empty cache of its own, so images, meshes and
# Roblox material maps the machine downloaded earlier cannot change results, and its
# warm browser worker (whose session lives in the cache) is not the user's. Only the
# pinned tools are copied in (<cache>/bin: Lune and Rojo), so nothing is downloaded.
def _real_cache() -> Path:
    from rhr.paths import CACHE

    return CACHE


if not os.environ.get("RHR_TEST_KEEP_CACHE"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    _bin = _real_cache() / "bin"
    _test_cache = Path(tempfile.mkdtemp(prefix="rhr-test-cache-"))
    if _bin.is_dir():
        shutil.copytree(_bin, _test_cache / "bin")
    os.environ["RHR_CACHE_DIR"] = str(_test_cache)

    def _cleanup_test_cache() -> None:
        subprocess.run([sys.executable, "-m", "rhr", "browser", "stop"], capture_output=True, timeout=60)
        shutil.rmtree(_test_cache, ignore_errors=True)

    atexit.register(_cleanup_test_cache)

BROWSER = {
    "test_billboard", "test_browser_session", "test_mcp_adapter", "test_particles",
    "test_preview", "test_preview_particles", "test_surface", "test_viewport_frame", "test_kept_page",
    "test_visual_gallery", "test_place_realism", "test_terrain",
}
NOT_LUNE = {
    "test_compare", "test_groundtruth_diff", "test_mesh_assets", "test_project", "test_roblox_assets",
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
