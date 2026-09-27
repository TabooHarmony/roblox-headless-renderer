# The UI engine

`src/rhr/ui_engine/` lays out, measures and paints ScreenGuis with skia. It is RHR's
own code: a fork, since 2026-09-27, of pinevex-renderer.

## Where it came from

- Upstream: https://github.com/whutdev/pinevex-renderer, commit
  `db292aca2b319c7204f494175c59ed9bd9552930` (2026-05-05), vendored 2026-09-14.
- Licence: Apache License 2.0. Upstream's `LICENSE` and `THIRD_PARTY_NOTICES.md` are
  kept, unmodified, in `src/rhr/ui_engine/`; the fonts' licences are in
  `src/rhr/vendor/licenses/`.
- From 2026-09-14 to 2026-09-27 the code was a vendored copy rebuilt from upstream
  plus `patches/NNNN-*.patch`, byte for byte. Those patches stay in `patches/` as the
  record of **why** the code differs from upstream: each names the defect, the
  Studio measurement or fixture that showed it, and the test that covers it
  (`patches/README.md`). They are history now; they are not applied, and a later
  change is an ordinary edit with its own test.

## What is in it

| Module | From upstream | What it does |
| --- | --- | --- |
| `converter.py` | `web_demo/rbxm_parser_component/tree_to_pinevexobject.py` | raw Roblox UI nodes (`rhr.adapter`) -> the engine's object schema (`flatten_node`) |
| `postprocess.py` | `vendor/product_output/pinevex_postprocess.py` | clean-ups on that object before drawing |
| `renderer.py`, `layout.py`, `visuals.py`, `assets.py` | `src/ui_engine/` | the layout pass, painting, images |
| `hit_test.py` | `src/ui_engine/` | what is clickable, what is on top (`rhr hitmap`) |
| `text*.py`, `data/` | `src/ui_engine/` | fonts, measuring, wrapping, fitting, rich text, drawing |
| `asset_fetcher.py` | `src/ui_engine/` | image thumbnails for `rhr fetch` |
| `font_assets.py` | `_resolve_font_family` in `rbxm_adapter.py` | font asset id -> family name |
| `fonts/` | `src/ui_engine/fonts/` | open-licence faces the engine falls back to |

## What was left out

Upstream's binary model parser and its adapter (RHR reads files with Lune), the web
demo app and API, the Luau exporter and its layout helpers, the Tk debug stepper,
demo models, renders, screenshots, prebuilt Linux libraries, an icon manifest whose
images were never shipped, and `RobloxEmoji.ttf`: a generated private-use-area font
whose artwork derives from Roblox's emoji set, with no licence covering it (the
loader skips missing faces; Twemoji is the emoji face either way).

Also removed with the fork: the calibration switches `RHR_TABLE_Y_SCALE*` and
`RHR_TABLE_NODRAW_*` (the table-mode vertical scale is fixed at 0.87, the value they
defaulted to).

## Changing it

The engine is ordinary RHR code: fix it in place, with a fixture or focused test that
fails before the fix (the rule `patches/README.md` set, which still holds).
`tests/test_render_regression.py` and the Studio-measured fixtures in `tests/studio/`
catch unintended changes to layout and pixels.
