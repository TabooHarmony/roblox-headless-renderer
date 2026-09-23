# roblox-headless-renderer

An **unofficial, local static preview and inspection tool** for Roblox `.rbxm` / `.rbxmx` models and place files. It produces UI and 3D PNGs plus machine-readable layout, hit regions, checks, and scene geometry without opening Studio. It is not a Roblox client or a replacement for Studio: scripts, gameplay, physics, and many visual effects are not reproduced.

**Status: v0.1 alpha candidate.** 2D UI rendering and static 3D preview work end to end, but visual parity with Roblox Studio is incomplete. Materials, lighting, in-world UI, particles, and text are approximations. Missing or unsupported scene assets are reported in `scene-dump`; missing cached images can leave visible gaps. Validate final work in Studio.

## Setup (Linux, Python 3.12)

Requirements: Python 3.12, [Lune 0.10.5](https://github.com/lune-org/lune) on `PATH`, and Chromium via Playwright. No GPU or display is needed. From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install --with-deps chromium
sh tests/run.sh
```

The source tree is a CLI checkout, not a pip-installable package. The test suite uses authored fixtures and needs no private game captures. A fresh checkout contains no downloaded image or mesh cache; render-time network access is never required.

## Use

```sh
bin/rhr ir model.rbxm --out model.json
bin/rhr render model.rbxm --out ui.png --viewport 676x336
bin/rhr layout model.rbxm --rich
bin/rhr check model.rbxm
bin/rhr hitmap model.rbxm
bin/rhr scene-dump model.rbxm > scene.json
bin/rhr scene model.rbxm --view iso --out scene.png
bin/rhr preview model.rbxm --view iso --out preview.png
bin/rhr compare before.png after.png --json
```

`render` targets ScreenGui UI; `scene` targets static 3D, and `preview` composes both. `scene-dump` reports missing meshes, textures and unsupported visuals. For assets referenced by your own model, emit the IR first, then optionally populate the local caches:

```sh
bin/rhr ir model.rbxm --out model.json
.venv/bin/python scripts/fetch_assets.py model.json
.venv/bin/python scripts/fetch_meshes.py model.json
```

The fetch commands contact Roblox's asset service and may fail for private assets; downloaded content is gitignored and is **not** part of this release. `bin/rhr-mcp` is an optional stdio integration; it requires the separate Python `mcp` SDK in the host interpreter.

## Boundaries

- The default 58 px top-bar inset is an approximation for runtime UI. Pass `--topbar-height 0` when comparing to Studio edit-view captures.
- Text fitting and font rasterization can differ substantially from Studio. Cached thumbnail images may not match originals.
- Non-empty Terrain and unions have no full geometry render; skinned meshes, runtime animations, scripts and physics are outside the static preview. Lighting and material values are not Studio-calibrated.
- The public test suite checks deterministic behavior and authored fixture geometry. It does **not** establish a percentage of Studio pixel parity. Private third-party game captures and the upstream demo model are intentionally omitted from this source release.

`vendor/pinevex/` is a patched Apache-2.0 renderer; `vendor/three/` is MIT. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`third_party_licenses/`](third_party_licenses/README.md) for attribution and font licences. This project is independent and is not affiliated with or endorsed by Roblox Corporation. Roblox is a trademark of Roblox Corporation.
