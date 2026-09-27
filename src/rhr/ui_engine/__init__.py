"""RHR's 2D UI engine: layout, text and painting of ScreenGuis with skia.

A fork of pinevex-renderer (https://github.com/whutdev/pinevex-renderer, commit
db292ac, Apache-2.0; see LICENSE and THIRD_PARTY_NOTICES.md here). It is RHR's own
code now: docs/ui-engine.md says where it came from and patches/ why it differs.

    converter.flatten_node      raw Roblox UI nodes -> the engine's object schema
    postprocess                 clean-ups on that object before drawing
    renderer.render_json        draw it (and record each node's rect)
    layout, hit_test, text_*    the layout pass, hit testing, text
"""
