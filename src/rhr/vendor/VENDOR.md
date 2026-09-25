# Vendored upstream: pinevex-renderer

- Upstream: https://github.com/whutdev/pinevex-renderer
- Commit vendored: `db292aca2b319c7204f494175c59ed9bd9552930` (2026-05-05, "Bundle Twemoji font for Unicode emoji rendering")
- Vendored: 2026-09-14
- Location: `src/rhr/vendor/pinevex/` (plain copy, upstream `.git` removed)
- Upstream license: Apache License 2.0, see the top-level `LICENSE`

A frozen copy, not a submodule. Reasons: we patch defects in place, and
we need a tree we can modify without an upstream remote silently changing under
us. Upstream commits are refreshed by hand, on purpose, and recorded here.

## Changes we have made to this copy

One patch per defect, listed with rationale and fixtures in `patches/README.md`
(the single index, so it is not duplicated here).

Line numbers are not recorded here, because they rot. `python3 scripts/make_patches.py`
rebuilds this tree from the pristine upstream copy and fails if the patch set no longer
reproduces it byte for byte. `vendor/product_output/pinevex_postprocess.py` is upstream's
own nested vendored copy; it is patched in place for the same reason as the engine.

## Removals

See `REMOVED.md` for the one font removed. We also leave out what RHR does not run
or cannot redistribute: upstream's README and its screenshots, `api/` (the Vercel
API), `vercel.json`, `examples/` (demo models), `vendor/native/` (prebuilt Linux
libraries) and all of `web_demo/` except `rbxm_parser_component/`, which is the
binary model parser RHR uses.

## Upstreaming

We intend to offer the fixes upstream as pull requests. Nothing is pushed
to any remote from this repository without the user showing the PR body and
getting an explicit yes first.

## THREE.js

- Upstream: https://github.com/mrdoob/three.js
- Version: `0.186.0`, obtained from the npm package
- Location: `src/rhr/vendor/three/`
- License: MIT, see `src/rhr/vendor/three/LICENSE`
- Files used: `three.module.js` and its local `three.core.js` companion, and the
  `lights/SunLight.js` / `lights/SunLightShadow.js` add-ons from `examples/jsm/lights/`
  (cascaded sun shadows), with their `import 'three'` pointed at `../three.module.js`

The browser scene uses this local bundle only. It does not load JavaScript from
CDNs or install npm packages at render time.

## Draco decoder

- Upstream: https://github.com/google/draco, the WebAssembly build three.js `0.186.0`
  ships in `examples/jsm/libs/draco/` (fetched from that npm package, unmodified)
- Location: `src/rhr/vendor/draco/`
- License: Apache License 2.0, see `src/rhr/vendor/draco/LICENSE`
- Files used: `draco_wasm_wrapper.js` and `draco_decoder.wasm`, loaded by the scene
  page only when a version 7 Roblox mesh (Draco-compressed geometry) is drawn
