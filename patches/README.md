# patches/

One `.patch` file per change we make to `src/rhr/vendor/pinevex/`, so a human can read a
fix without diffing two trees, and so the fixes can be offered upstream as clean
pull requests.

Rules:

- One defect per patch. No drive-by edits.
- The patch file must reproduce the change against the vendored upstream commit
  recorded in `src/rhr/vendor/VENDOR.md`.
- Every patch ships with a fixture under `tests/fixtures/` or in a focused test that fails before the
  patch and passes after it. A patch with no failing fixture is not a fix, it is
  a preference.
- Regenerate and verify with `python3 scripts/make_patches.py`, which diffs
  `src/rhr/vendor/pinevex` against the pristine tree (`/root/pinevex-recon`, upstream at
  the vendored commit), writes the .patch files, then applies all of them to a
  clean copy of that tree and checks the result is byte-identical to the vendored
  tree. A patch set that cannot reconstruct `src/rhr/vendor/pinevex` is a broken patch set.

## Applied

| patch | defect | files | fixture |
| --- | --- | --- | --- |
| 0001-grid-cell-offsets.patch | CellSize/CellPadding offsets were dropped by the emitter and read as zero by the renderer, so the most common grid rendered blank | renderer.py, hit_test.py, tree_to_pinevexobject.py | grid_offset |
| 0002-zero-size-parent-subtree.patch | a zero-area node returned early and took its whole subtree with it, losing offset-positioned children of 0x0 holders | renderer.py | zero_size_parent |
| 0003-autosize-padding.patch | AutomaticSize ignored the node's own UIPadding, so autosized text clipped by the padding amount | layout.py | autosize_padding |
| 0005-root-rect.patch | the engine hardcoded the root rect and the sizing viewport to the whole canvas, so a ScreenGui's content area could not be inset (Roblox's default `CoreUISafeInsets` reserves the top bar) | renderer.py | screen_insets |
| 0004-path-passthrough.patch | flatten_node dropped the caller's `_path`, so the renderer's rect map (its documented way to read the resolved layout back out) was always empty | tree_to_pinevexobject.py | layout_dump |
| 0006-textscaled-honesty.patch | the postprocess forced `textScaled=True` on every TextLabel, so `TextScaled=false` was ignored (every font fitted to its rect) and a scaled label's long text shrank to fit one line instead of wrapping | text_renderers.py, text_rich.py, pinevex_postprocess.py, tree_to_pinevexobject.py | textscaled |
| 0008-grid-alignment.patch | centered and right-aligned UIGridLayout cells started at the parent's left edge, shifting hit regions and rendered cells | renderer.py, hit_test.py | RTL2PCParts |
| 0010-textscaled-stroke-fit.patch | outlined TextScaled glyphs were fitted to an artificially smaller box; Studio fits without reserving outline thickness | text_renderers.py | test_textscaled_stroke.py (plain/RTL, thickness 0/2/5) |
| 0016-freetype-font-manager.patch | bundled fonts loaded with `skia.Typeface.MakeFromFile` went through the platform font engine (DirectWrite on Windows), so the same TTF rasterized differently per OS: 96.7% identical Windows vs Linux on the frozen baseline, 99.6% after (the rest is edge anti-aliasing) | text_fonts.py | test_render_regression.py, test_checks.py (truncation ink) |
| 0017-studio-measured-layout.patch | found by Studio-recorded fixtures (tests/studio/): UISizeConstraint was dropped by the converter; UIListLayout/UIGridLayout SortOrder.Name was ignored; AutomaticSize text used a per-character guess and a 1.2x line box; the postprocess coerced every font outside a 4-family allowlist to GothamSSm. Measured with the real face at Roblox's TextSize scale (roblox_em_scale), line box = TextSize | tree_to_pinevexobject.py, layout.py, renderer.py, hit_test.py, text_fonts.py, pinevex_postprocess.py | test_studio_truth.py (ui_layouts), test_fixtures.py, test_layout_dump.py |
| 0018-roblox-text-size-and-layout-rects.patch | text drew with TextSize as the em; Roblox makes TextSize the line box (ascent+descent), so most faces drew 15-25% large (roblox_font everywhere, line step = TextSize with no font line gap, TextScaled fits the largest size at which the WRAPPED text fits, table wrap for advance-table faces); TextTruncate AtEnd/SplitWord were swapped; the paint pass records each label's laid-out text for `layout --rich`; the renderer draws at rects RHR's layout pass supplies (ctx `_layout_rects`) | text_fonts.py, text_fit.py, text_renderers.py, text_rich.py, text_runs.py, renderer.py | test_studio_truth.py (ui_text, rtl2pcparts, ui_stress), test_checks.py, test_render_regression.py (re-frozen) |

0012-text-newlines.patch preserves explicit paragraph breaks in plain wrapping
and TextScaled fitting; `test_text_newlines.py` checks painted lines and empty
paragraphs. `text_fit.py` is included in byte-identical reconstruction. The
unwrapped branch's newline split lives in patch 0007 (adjacent TextTruncate
edits share one vendored diff hunk); the same focused test covers unwrapped
drawing and per-line truncation.

0009-group-transparency.patch also carries GroupColor3 in the adjacent layer
and converter hunks. It reuses the layer restore paint for color modulation;
`test_group_color.py` covers nested groups, alpha, identity, and Global mode.

0013-rich-newlines.patch converts literal newlines into the existing rich hard-break
runs, matching `<br/>`, including blank and edge lines. The focused newline test
covers wrapped, unwrapped, scaled, and mixed-style rendering.

The 0007 converter hunk also carries non-default LineHeight. Its full-path
fixture `line_height.rbxmx` and `test_line_height.py` cover plain and rich spacing.

0011-image-resampling.patch preserves ResampleMode through flatten_node and
uses smooth default sampling for ordinary image draws. The two-color fixture
`_resample_repro.rbxmx` and `test_resample_mode.py` cover both modes and gradients.
The empty-icon-root baseline is unchanged; assets.py is now included in the
reconstruction file list.

0010 also carries the overlapping plain/RTL TextScaled semantics hunks formerly
in 0006. Patch 0007's offsets change with the deleted helper. Together the set
reconstructs the vendor tree byte-for-byte. The corrected output has a separate
exact regression reference; the historical PNG is retained unchanged.

Patches 0001–0007 do not change the render of upstream's RTL2PCParts example (which
is not redistributed here). 0004 only adds a rect-map key, 0005 is inert unless a root
rect is passed, and 0006 is invisible on that model because all 63 of its labels
are genuinely `TextScaled` (measured: 0 differing pixels). 0008 changes its centered
grid placement to match Studio.