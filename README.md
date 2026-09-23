# roblox-headless-renderer (rhr)

A command-line tool that lets an AI agent **see** the Roblox UI and 3D builds it is
making, with no Roblox Studio, GPU or display. Point it at a `.rbxm` / `.rbxmx` /
`.rbxl` / `.rbxlx` file or a Rojo project and get a preview PNG plus JSON: where
things are, how big they are, what overlaps, what is clickable, and what looks broken.

**Agents: start with [`docs/AGENTS.md`](docs/AGENTS.md)** (which command answers which
question, the edit loop, and how far to trust each output).

The goal is a **useful preview**, not a pixel-perfect copy of Studio. Anything the
tool cannot draw faithfully is reported in its output rather than silently dropped
or guessed. The full statement of what this project is and is not, and the path to
v1, is in [`docs/GOAL.md`](docs/GOAL.md).

## Status: pre-release, not ready for general use

- The test suite runs in CI on clean Ubuntu and Windows machines.
- It is not published to PyPI yet; install it from a clone (below).
- Every JSON output names its schema (`"schema": "rhr.layout/1"`, ...).
- Several 3D features are rough approximations and are marked experimental below.

## Commands

**Core**

| Command | What it gives you |
| --- | --- |
| `rhr render <file>` | PNG of every ScreenGui, in `DisplayOrder` paint order, including 3D content inside ViewportFrames |
| `rhr layout <file>` | JSON: the on-screen rectangle of every UI element (matches Studio within 2 px on the Studio fixtures). `--rich` adds class, z-index, colours and the laid-out text (drawn size, lines, bounds) |
| `rhr check <file>` | JSON findings for common UI mistakes (zero-size grid cells, unreadable or truncated text, dead branches, ambiguous z-order). Exits 1 on errors |
| `rhr hitmap <file>` | JSON: which regions are clickable or focusable, and which element is on top where they overlap |
| `rhr scene <file>` | PNG of the 3D parts from an authored camera or one you choose (`--camera`, `--look-at`, `--fov`, `--focus <path>`, `--view iso/front/back/left/right/top`) |
| `rhr scene-dump <file>` | JSON: paths, positions, sizes, bounds and materials of 3D parts, plus everything that was approximated or unsupported |
| `rhr preview <file>` | One PNG combining the 3D world, in-world UI and ScreenGuis |
| `rhr compare a.png b.png` | How much changed between two renders (pixels and silhouette), to tell a geometry change from a colour change |
| `rhr ir <file>` | The parsed model as JSON, including every property read and the ones that could not be |

**Experimental** (rough approximations; expect gaps)

- Materials, Lighting properties, `--shadows`, Sky and Atmosphere in `scene` / `preview`.
- Decal/Texture images and MeshPart/FileMesh geometry (need locally cached assets).
- Point/Spot/Surface lights, Beams and Trails.
- `rhr particles <file>` and `rhr preview --time T`: deterministic ParticleEmitter
  simulation.

**Other**

- `rhr browser start|status|stop` keeps one Chromium running so repeated 3D renders
  are faster.
- `rhr-mcp` is an MCP server exposing a small subset (scene inspection, preview,
  compare, browser control) for agent hosts. Install with the `mcp` extra.

## Install

Needs Python 3.12+ and [Lune](https://github.com/lune-org/lune) 0.10.5, which RHR
uses to read Roblox files.

    git clone https://github.com/TabooHarmony/roblox-headless-renderer
    cd roblox-headless-renderer
    python -m venv .venv
    # activate it: `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows)
    pip install -e .                     # add ".[mcp]" for the MCP server, ".[dev]" for tests
    python -m playwright install chromium

For Lune (and [Rojo](https://rojo.space) 7.7.0, needed only for Rojo projects),
either install [Rokit](https://github.com/rojo-rbx/rokit) and run
`rokit add --global lune-org/lune@0.10.5` (and `rojo-rbx/rojo@7.7.0`), or download
them from their releases pages and put them on `PATH`. Inside this clone,
`rokit install` reads `rokit.toml`. `rhr` tells you if it cannot find either.

## Usage

    rhr render  model.rbxm --out shot.png --viewport 1615x1080 --transparent
    rhr layout  model.rbxm --rich > layout.json
    rhr check   model.rbxm
    rhr scene   model.rbxm --focus Workspace/Build --view iso --out build.png
    rhr scene   model.rbxm --camera 30,20,30 --look-at 0,5,0 --fov 50 --out scene.png
    rhr preview model.rbxm --view iso --out preview.png
    rhr compare before.png after.png --json
    rhr render  path/to/rojo-project --out ui.png   # a folder with default.project.json, or a *.project.json

Run the tests with `pip install -e ".[dev]"` and then `python -m pytest`
(`-m "not browser"` skips the slower 3D checks).

Notes:

- UI layout assumes Roblox's default 58 px top bar (`ScreenInsets = CoreUISafeInsets`).
  Use `--topbar-height 0` to match a Studio edit-mode view.
- Rendering never needs network access. `scripts/fetch_assets.py` and
  `scripts/fetch_meshes.py` fill a local cache for images and meshes ahead of time;
  without them, images are skipped and meshes fall back to boxes, and the JSON says so.
- Caches and intermediate files go to a per-user cache directory
  (`%LOCALAPPDATA%\rhr\cache` on Windows, `~/.cache/rhr` on Linux,
  `~/Library/Caches/rhr` on macOS). Set `RHR_CACHE_DIR` to move it.
- Every known approximation is listed in `docs/known-approximations.md`.

## Repository layout

- `src/rhr/`: the package (parser bridge, UI pipeline, 3D scene, CLI, MCP server).
- `src/rhr/luau/rhr-ir.luau`: turns Roblox files into JSON using Lune and rbx-dom.
- `src/rhr/vendor/pinevex/`: the 2D UI renderer we build on (Apache-2.0), with our fixes
  applied. See `src/rhr/vendor/VENDOR.md` and `patches/`.
- `src/rhr/vendor/three/`: THREE.js 0.186.0 for the 3D preview, bundled so there are no CDN
  downloads.
- `tests/`: test scripts and hand-written fixtures. `tests/studio/` holds places built
  in Studio with Studio's own measurements saved inside.
- `scripts/studio/`: tools for recording ground truth in Studio and comparing to it.
- `docs/GOAL.md`: project direction (source of truth).

## Licensing

Apache License 2.0. Third-party components are listed in `THIRD_PARTY_NOTICES.md`.
Test fixtures are made for this repository (hand-written, or built in Studio for
`tests/studio/`); no third-party game content is included.
