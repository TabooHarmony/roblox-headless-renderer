# Vendored renderer provenance

- Pinevex Renderer: https://github.com/whutdev/pinevex-renderer, pinned at `db292aca2b319c7204f494175c59ed9bd9552930` (Apache-2.0, license in `vendor/pinevex/LICENSE`). The 2D engine, parser/converter and supporting fonts are bundled and modified. The source edits are documented as numbered diffs in `patches/`.
- This **public source cut is a subset** of the original upstream tree: demo model files, generated demo screenshots, web frontend assets, native server libraries and hosted API were left out. The parser components under `web_demo/rbxm_parser_component/` remain bundled. Consequently the private repo's byte-for-byte full-tree reconstruction procedure does not apply to this distribution. Compare patches against the pinned upstream source when updating the engine; keep the same omissions.
- `RobloxEmoji.ttf` is deliberately omitted because the underlying artwork has no redistribution license; see `REMOVED.md`. Bundled font license texts and credits are in `../third_party_licenses/`.
- THREE.js: https://github.com/mrdoob/three.js, version `0.186.0` (MIT, `vendor/three/LICENSE`), bundled locally for 3D previews.
