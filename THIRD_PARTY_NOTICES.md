# Third-party notices

This repository vendors third-party code. This file lists what is vendored, the
license it carries, and what was removed. It is not a substitute for the
upstream license texts.

## pinevex-renderer (vendored, patched)

- Location: `vendor/pinevex/`
- Upstream: https://github.com/whutdev/pinevex-renderer at commit `db292ac`
- License: Apache License 2.0 (copy at the repository root, plus upstream's own
  `vendor/pinevex/LICENSE`)
- We modify it. Modifications are recorded in `vendor/VENDOR.md` and mirrored as
  patch files in `patches/`.

## Fonts (vendored inside `vendor/pinevex/src/ui_engine/fonts/`)

Bundled typefaces come from several families under the SIL Open Font License
1.1, Apache License 2.0, and the Ubuntu Font License 1.0.

- `TwemojiMozilla.ttf` is from Mozilla's
  [twemoji-colr](https://github.com/mozilla/twemoji-colr): Apache License 2.0
  code, Twemoji artwork under CC BY 4.0.
- Font files are not relicensed here. Their individual licence texts and attribution
  are in [`third_party_licenses/`](third_party_licenses/README.md); preserve embedded
  copyright and licence metadata on redistribution.

## Removed: RobloxEmoji.ttf

Upstream bundles `src/ui_engine/fonts/RobloxEmoji.ttf`, a generated
private-use-area compatibility font whose artwork derives from Roblox's emoji
set, with no license covering that artwork. We do not redistribute it; see
`vendor/REMOVED.md` for why removal is inert.

## Deliberately omitted upstream material

The public source cut excludes upstream demo places, renders, and web frontend
assets with unverified redistribution rights, along with its unused native
libraries and Vercel API. The local parser and renderer code remain bundled.
Do not copy the original upstream examples into this release by default.

## THREE.js

Phase 3 vendors THREE.js locally for the browser scene. MIT license. The local
copy and its license file land with that phase.