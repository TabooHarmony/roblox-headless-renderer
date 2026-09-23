# RobloxEmoji.ttf was removed from the vendored copy.

Upstream ships `src/ui_engine/fonts/RobloxEmoji.ttf`, a generated
private-use-area compatibility font whose glyph artwork derives from Roblox's
emoji set. Upstream's own notices describe it as generated and disclaim any
Roblox endorsement or trademark grant, but no license covers the artwork.

We do not redistribute it. `src/ui_engine/text_fonts.py` loads typefaces with
`_load_first`, which skips missing paths, so the removal is inert: Twemoji
(`TwemojiMozilla.ttf`, kept) is the primary emoji face either way.

If PUA emoji parity is ever needed, generate or license a font with clear
provenance and record it here instead of restoring this file.