# Third-party notices

Pinevex-authored source code in this repository is licensed under the Apache License, Version 2.0. Third-party components included in the repository retain their original licenses.

This notice is not a replacement for the upstream license texts. If you redistribute this repository, keep this file and preserve upstream copyright/license notices.

This upstream notice is retained for attribution. In this reduced public source distribution,
`vendor/native/` and `RobloxEmoji.ttf` are deliberately **not included**; font
licence texts are in the repository's `third_party_licenses/` directory.

## Upstream native libraries (omitted from this distribution)

The upstream tree's `vendor/native/` contained Linux shared libraries for hosted rendering (Mesa/libglvnd, X.Org/XCB, and Expat). This public cut does not include or use them.

## Vendored fonts

`src/ui_engine/fonts/` contains bundled typefaces used so render output is stable across local and serverless environments.

The bundled font families include fonts under SIL Open Font License 1.1, Apache License 2.0, and Ubuntu Font License 1.0. `TwemojiMozilla.ttf` is from Mozilla's [`twemoji-colr`](https://github.com/mozilla/twemoji-colr) package; its code is Apache-2.0 and its Twemoji visual artwork is CC BY 4.0. The generated `RobloxEmoji.ttf` compatibility font in upstream is **not included** in this distribution; see `vendor/REMOVED.md`.

Font files are not relicensed by Pinevex Renderer. Preserve their embedded copyright metadata and the licence texts in `third_party_licenses/` when redistributing this repository.

## Runtime dependencies

Python dependencies installed from `requirements.txt` are not vendored. Their package metadata and upstream repositories define their license terms.
