# Third-party notices

This repository vendors third-party code and fonts. This file lists what is
vendored, the licence it carries, and what was left out. It is not a substitute
for the upstream licence texts, which ship with the package.

## pinevex-renderer (vendored, patched)

- Location: `src/rhr/vendor/pinevex/`
- Upstream: https://github.com/whutdev/pinevex-renderer at commit `db292ac`
- License: Apache License 2.0 (copy at the repository root, plus upstream's own
  `src/rhr/vendor/pinevex/LICENSE`)
- We modify it. Modifications are recorded in `src/rhr/vendor/VENDOR.md` and
  mirrored as patch files in `patches/`.

## Fonts

- `src/rhr/vendor/pinevex/src/ui_engine/fonts/`: typefaces bundled by upstream,
  under the SIL Open Font License 1.1, Apache License 2.0 and Ubuntu Font Licence
  1.0. `TwemojiMozilla.ttf` is from Mozilla's
  [twemoji-colr](https://github.com/mozilla/twemoji-colr): Apache-2.0 code,
  Twemoji artwork under CC BY 4.0. Per-font licences and attribution are in
  [`src/rhr/vendor/licenses/`](src/rhr/vendor/licenses/README.md).
- `src/rhr/fonts/`: Source Sans Pro 2.021 (SIL OFL 1.1, `OFL.txt`) and Roboto
  2.137 (Apache 2.0, `Roboto-LICENSE.txt`), the builds Roblox ships, from Google
  Fonts, unmodified.

Font files are not relicensed here. Preserve their embedded copyright and licence
metadata on redistribution.

## THREE.js

- Location: `src/rhr/vendor/three/` (version 0.186.0, from the npm package)
- License: MIT, `src/rhr/vendor/three/LICENSE`

## Left out on purpose

- `RobloxEmoji.ttf`: upstream bundles a generated private-use-area font whose
  artwork derives from Roblox's emoji set, with no licence covering that artwork.
  We do not redistribute it; `src/rhr/vendor/REMOVED.md` explains why removing it
  changes nothing.
- Upstream's demo places, example models, renders, web frontend, Vercel API and
  prebuilt Linux native libraries: unused by RHR and, for the examples, with
  unverified redistribution rights. The parser and renderer code are kept.
- `src/rhr/vendor/pinevex/vendor/icon_library/manifest.json` lists 11 icon names
  whose artwork is Roblox's own. It is a name list; **no Roblox image files are
  bundled**. Images that you fetch for your own models with
  `scripts/fetch_assets.py` stay in your local cache and are not part of this
  project.
