# Vendored third-party code

Copies of upstream code RHR ships unmodified. (The UI engine, once vendored here as
pinevex-renderer, is RHR's own fork since 2026-09-27: `src/rhr/ui_engine/`,
docs/ui-engine.md.)

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
