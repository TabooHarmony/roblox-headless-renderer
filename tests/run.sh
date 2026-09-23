#!/bin/sh
# Test entry point. One line per check, non-zero exit if any check fails.
#
#   tests/test_fixtures.py            one fixture per vendored fix: the layout rule
#                                     each fix restores, measured from the PNG
#   tests/test_scroll_scale.py        ScrollingFrame child Scale resolves against the
#                                     window, not the canvas extent
#   tests/test_assets.py              an ImageLabel paints from the icon cache in
#                                     assets/cache/icons (and only from there)
#   tests/test_ir_props.py            nothing vanishes from the IR unnamed: unreadable
#                                     properties and name-occluded reads are reported
#   tests/test_layout_dump.py         the renderer hands back the rects it resolved,
#                                     per node path
#   tests/test_layout_dump_rich.py    Task 2.1's structured dump: content per node,
#                                     measured determinism, pixels vs the dump
#   tests/test_checks.py              Task 2.2's checks: every fixture trips its check,
#                                     exit contract, the truncation follow-up draws
#   tests/test_cli.py                 bin/rhr ir / render / layout, run for real
#   tests/test_insets.py              a ScreenGui's content area: the top bar inset
#                                     moves both the rects and the pixels
#   tests/test_screens.py             every ScreenGui renders, in DisplayOrder paint
#                                     order; a disabled ScreenGui does not
#   tests/test_textscaled.py          TextScaled semantics: the box fits the text
#                                     only when the label asks for it, TextSize rules
#                                     otherwise, wrapping is implicit, constraints cap
#   tests/test_textscaled_stroke.py   outlines never shrink scaled glyphs (Studio
#                                     fixed-box probe), painted fill independent of
#                                     outline thickness, plain and RTL fit paths
#   tests/test_hitmap.py              Task 2.3's interactive regions: Active,
#                                     Selectable, TextBox flags, hidden capture,
#                                     and topmost overlap targets
#   tests/test_groundtruth_diff.py     Studio/RHR diff metric and bbox contract
#   tests/test_project.py             BillboardGui pinhole projection contract
#   tests/test_billboard.py           BillboardGui scene overlay placement
#   tests/test_surface.py            SurfaceGui face projection baseline
#   tests/test_studio_smoke.py        real Studio UI models render without failing
#                                     (skips with a note when none are installed)
#   tests/test_scene.py                the headless Chromium 3D scene is visible
#   tests/test_ir_profiles.py          fast full/visual/static IR profile contract
#   tests/test_scene_primitives.py     Ball/Cylinder size and axis silhouettes
#   tests/test_scene_foundation.py     real emitted multi-view geometry/depth contract
#   tests/test_scene_model_pivot.py    Model.Scale around authored WorldPivot
#   tests/test_scene_model_default_pivot.py  default bounding-box pivot
#   tests/test_scene_model_primary_part.py   PrimaryPart pivot precedence
#   tests/test_scene_model_pivot_offset.py    rotated PrimaryPart.PivotOffset
#   tests/test_scene_model_nested.py         nested Model.Scale composition
#   tests/test_scene_model_nested_asymmetric.py  nested pivot after inner scale
#   tests/test_scene_model_wedge_pivot.py  rotated Wedge/CornerWedge bounds
#   tests/test_scene_model_mesh_pivot.py  loaded MeshPart vertex bounds
#   tests/test_scene_model_primitive_pivot.py  rotated Ball/Cylinder analytic bounds
#   tests/test_scene_controls.py       camera/focus controls and loud scene errors
#   tests/test_scene_dump.py           machine-readable 3D paths/bounds/fallbacks
#   tests/test_scene_materials.py      material table, determinism, fallback reporting
#   tests/test_scene_lighting.py       saved Lighting service drives full-scene lights
#   tests/test_scene_shadows.py        opt-in bounded shadows and GlobalShadows contract
#   tests/test_scene_decal.py          local Decal assets and missing-asset reporting
#   tests/test_scene_texture.py        tiled Texture face mapping
#   tests/test_scene_lights.py         Point/Spot/Surface local light illumination
#   tests/test_scene_atmosphere.py     Atmosphere tint/fog baseline
#   tests/test_scene_sky.py            local six-face Sky cube map orientation
#   tests/test_rbxl_raw.py             raw hidden PROP extraction + Terrain diagnostics
#   tests/test_scene_beam.py           static Attachment-to-Attachment Beam baseline
#   tests/test_scene_trail.py          timed linear-motion Trail ribbon baseline
#   tests/test_scene_specialmesh.py    built-in SpecialMesh geometry; FileMesh explicit
#   tests/test_scene_meshpart.py       cached Roblox v1/v2/v4 MeshPart geometry
#   tests/test_mesh_assets.py          local mesh cache ID discovery (no network)
#   tests/test_preview.py              unified world + ScreenGui static preview
#   tests/test_preview_particles.py    transparent synchronized particle preview layer
#   tests/test_compare.py              before/after pixel + silhouette iteration metrics
#   tests/test_visual_gallery.py       representative 3D visual-quality sanity gate
#   tests/test_browser_session.py      persistent Chromium reuse and pixel identity
#   tests/test_mcp_adapter.py          host stdio MCP discovery + preview image payload
#   tests/test_particle_data.py         ParticleEmitter properties stay typed
#   tests/test_particles.py              fixed-step particle simulation is reproducible
#
cd "$(dirname "$0")/.." || exit 2

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "no venv at $PY: python3.12 -m venv .venv && .venv/bin/pip install skia-python pillow numpy"
    exit 2
fi

status=0
"$PY" tests/test_fixtures.py || status=1
# ScrollingFrame children resolve Scale against the window, not the canvas (Trading fix).
"$PY" tests/test_scroll_scale.py || status=1
"$PY" tests/test_assets.py || status=1
# ResampleMode: smooth default vs pixelated, ordinary and gradient draws.
"$PY" tests/test_resample_mode.py || status=1
# GroupColor3 tints the flattened CanvasGroup, independently of group alpha.
"$PY" tests/test_group_color.py || status=1
"$PY" tests/test_ir_props.py || status=1
"$PY" tests/test_layout_dump.py || status=1
"$PY" tests/test_layout_dump_rich.py || status=1
"$PY" tests/test_checks.py || status=1
"$PY" tests/test_cli.py || status=1
"$PY" tests/test_insets.py || status=1
"$PY" tests/test_screens.py || status=1
"$PY" tests/test_textscaled.py || status=1
"$PY" tests/test_textscaled_stroke.py || status=1

# Explicit newlines survive plain wrapping, unwrapped drawing, TextScaled fitting.
"$PY" tests/test_text_newlines.py || status=1
# Preserve LineHeight through the converter for existing text renderers.
"$PY" tests/test_line_height.py || status=1
"$PY" tests/test_hitmap.py || status=1
"$PY" tests/test_groundtruth_diff.py || status=1
"$PY" tests/test_project.py || status=1
"$PY" tests/test_billboard.py || status=1
"$PY" tests/test_surface.py || status=1
"$PY" tests/test_studio_smoke.py || status=1
"$PY" tests/test_scene.py || status=1
"$PY" tests/test_ir_profiles.py || status=1
"$PY" tests/test_scene_primitives.py || status=1
"$PY" tests/test_scene_foundation.py || status=1
"$PY" tests/test_scene_model_pivot.py || status=1
"$PY" tests/test_scene_model_default_pivot.py || status=1
"$PY" tests/test_scene_model_primary_part.py || status=1
"$PY" tests/test_scene_model_pivot_offset.py || status=1
"$PY" tests/test_scene_model_nested.py || status=1
"$PY" tests/test_scene_model_nested_asymmetric.py || status=1
"$PY" tests/test_scene_model_wedge_pivot.py || status=1
"$PY" tests/test_scene_model_mesh_pivot.py || status=1
"$PY" tests/test_scene_model_primitive_pivot.py || status=1
"$PY" tests/test_scene_controls.py || status=1
"$PY" tests/test_scene_dump.py || status=1
"$PY" tests/test_scene_materials.py || status=1
"$PY" tests/test_scene_lighting.py || status=1
"$PY" tests/test_scene_shadows.py || status=1
"$PY" tests/test_scene_decal.py || status=1
"$PY" tests/test_scene_texture.py || status=1
"$PY" tests/test_scene_lights.py || status=1
"$PY" tests/test_scene_atmosphere.py || status=1
"$PY" tests/test_scene_sky.py || status=1
"$PY" tests/test_rbxl_raw.py || status=1
"$PY" tests/test_scene_beam.py || status=1
# Timed linear-motion Trail ribbon baseline with width/lifetime/facing semantics.
"$PY" tests/test_scene_trail.py || status=1
"$PY" tests/test_scene_specialmesh.py || status=1
"$PY" tests/test_scene_meshpart.py || status=1
"$PY" tests/test_mesh_assets.py || status=1
"$PY" tests/test_preview.py || status=1
"$PY" tests/test_preview_particles.py || status=1
"$PY" tests/test_compare.py || status=1
"$PY" tests/test_visual_gallery.py || status=1
"$PY" tests/test_browser_session.py || status=1
"$PY" tests/test_mcp_adapter.py || status=1
"$PY" tests/test_viewport_frame.py || status=1
"$PY" tests/test_particle_data.py || status=1
"$PY" tests/test_particles.py || status=1

if [ "$status" -eq 0 ]; then
    echo "all checks pass"
else
    echo "FAILURES above"
fi
exit "$status"