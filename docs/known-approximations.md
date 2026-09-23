# Known approximations

Every number here is an assumption we could not measure directly yet. Each entry
says what we assume, where the number came from, and how to prove it wrong. If a
ground-truth diff against Studio disagrees with one of these, fix it here rather
than in the renderer.

## Screen insets — the top bar (Task 1.9)

Roblox's `ScreenGui.ScreenInsets` (docs: `Enum.ScreenInsets`) moves and shrinks
the area a ScreenGui's descendants are laid out in. Modes:

- `None` (0) — the whole viewport
- `DeviceSafeInsets` (1) — the viewport minus notch/home-indicator insets
- `CoreUISafeInsets` (2) — the viewport minus the top bar and those insets (the
  default when the property is unset, which is what Roblox itself does)
- `TopbarSafeInsets` (3) — the free space *inside* the top bar

**Assumed reference environment:** Roblox desktop, current top bar, viewport
1615x1080. Content area = `(0, 58, W, H - 58)` for `CoreUISafeInsets`, and
`(0, 0, W, H)` for `None` and `DeviceSafeInsets`.

**Where 58 comes from:** the Roblox docs' `GuiService:GetInsetArea` example shows
the `None` area as 58 px above the top-left corner of the core-UI area, and
`GuiService.TopbarInset.Height` reports 58 for the top bar introduced in 2023 (the
pre-2023 top bar was 36 px, which is what older posts about the "36 px inset"
mean). Both were read from the docs in September 2026, not measured here.

**How to correct it:** `rhr render <model> --topbar-height N` (and `layout`).
The default lives in `src/rhr/insets.py` as `REFERENCE_TOPBAR_HEIGHT` and is pinned
by `tests/test_insets.py`; the other tests assert layout rules relative to the
content area so only that one test has to change.

**Unverified.** No Studio round-trip has confirmed 58 px on this machine, so this
remains a documented approximation, not a measured fact. Measured since (2026-09-19,
real-game captures): Studio's *edit-view* screenshots have no top bar at all —
parity renders of edit-view captures must pass `--topbar-height 0` (history/results.md
§0.2b). The 58 px runtime value is still untested against a running-game capture.

**Desktop makes `None` and `DeviceSafeInsets` identical** (no notch, no home
indicator), so any portability differences in `ClipToDeviceSafeArea`,
`SafeAreaCompatibility`/`FullscreenExtension` do not change pixels in the
reference environment. A mobile or notched-device profile would need real device
insets; none are modelled, and the resolve note says so on stderr.

**`TopbarSafeInsets` is not modelled.** It is the top bar's free region, whose left
edge moves with the top bar's own controls (the docs' example starts at x = 164).
It falls back to `CoreUISafeInsets` and prints a note; do not invent a width for it.

**`IgnoreGuiInset`** is Roblox's deprecated flag, documented as setting
`ScreenInsets` to `DeviceSafeInsets` when true. It is honoured only when the file
does not override the mode, and it is what old place files mean.

**Do not build this twice:** the runtime reads of the same numbers are
`GuiService:GetGuiInset()`, `GuiService.TopbarInset`, and
`GuiService:GetInsetArea(mode)`. The Task 0.2 probe should print all four modes'
areas plus `TopbarInset.Height` and compare them to this file.

## Interactive hit regions (Task 2.3)

`rhr hitmap` reports GUI objects that are input-relevant because they are
`Active`, `Selectable`, `TextButton`, `ImageButton`, or `TextBox`. Geometry and
z-order come from the vendored `ui_engine.hit_test` traversal, using the same
ScreenGui pane root rectangle as rendering. Interaction properties come from the
IR because they are not painter fields: `Active`, `Selectable`, and for
`TextBox`, `TextEditable` plus `ClearTextOnFocus`.

The dump probes the centre of each positive interactive region. Each `hitTests`
entry lists the overlapping interactive paths topmost first and names the first
`Active` node as `target`. An `Active` node with `Visible=false` is intentionally
kept in the stack and can be named as the target, because invisible input sinks
are the diagnostic case this command is meant to expose. The fixture
`tests/fixtures/hitmap_overlap.rbxmx` measures that the hidden button is not
painted but still wins the reported overlap.

**Studio round-trip measured 2026-09-15.** The real `RTL2PCParts.rbxm` GUI was
captured in Studio at 676x336. Its 20 interactive paths and 23 interactive
entries matched `rhr hitmap` rectangle multisets exactly at 0.001 px after patch
0008 added UIGridLayout alignment offsets. The screenshot showed the complete
GUI with no blank regions. This verifies visible geometry and grid placement;
the hidden-but-Active overlap remains a diagnostic-only fixture until a real
input-sink model is captured in Studio. **Measured screen baseline:** the attached Studio session reports a 676x336 canvas.
A temporary opaque white backing frame removes the environment sky for a UI-focused
comparison. Current numbers for that pair live in `docs/history/results.md` §0.2 (84.65%
within 8/255 at HEAD); the white-backing baseline was the first score, superseded
by the stroke-fit, resampling and advance-table fixes. The 1615x1080 fixed-canvas
Studio screenshot is still not captured, so the standard-viewport parity number
remains open.

## LineHeight handoff

Non-default LineHeight now survives conversion into the existing plain and rich
spacing code, and height-limited plain TextScaled fitting applies the same step
it paints (Studio probe 76feb87d: 77x60 -> 52x60 TextBounds at LineHeight 1 -> 2
for two scaled lines). These are Skia measurements, not exact Studio glyph
metrics. Fitting is width-then-height, so a width-limited fit is unaffected by
spacing, matching the probe. RTL plain fitting with non-default spacing remains
open: the installed Skia paragraph bindings expose neither TextStyle height
control nor per-line metrics. StrutStyle exposes only leading/enabled, not
font-size or height control. A faithful RTL spacing change needs a separately
validated layout approach; no guessed per-line replacement has been shipped.
The rich fit already applied the multiplier. Rich literal newlines now
use the same mandatory breaks as `<br/>`; blank and edge lines are preserved.

## UI layout (rhr.ui_layout)

Every GuiObject's rect comes from RHR's own layout pass, computed from the IR and
checked against rects Studio recorded (tests/studio/: ~450 checks, all within 2px
except text-sized objects, which get 2px + 4%). Pinevex only draws at those rects;
`rhr layout` reports them. Covered: UDim2 sizing and positioning, AnchorPoint,
SizeConstraint, UIPadding, UISizeConstraint, UIAspectRatioConstraint (both
AspectTypes), UIScale, AutomaticSize (text and children), UIListLayout (sorting,
alignment, Wraps, HorizontalFlex/VerticalFlex, UIFlexItem, ItemLineAlignment),
UIGridLayout (FillDirectionMaxCells, StartCorner, constrained cells centred in their
cell), UITableLayout, ScrollingFrame canvas and CanvasPosition. UIPageLayout lays pages
out like a list (no page animation). Not yet measured against Studio: UIPageLayout,
UITableLayout FillEmptySpace*, flex Shrink with wrapping, ItemLineAlignment Stretch.

## Text sizing (Task 1.10)

**Measured against Studio (2026-09-22, tests/studio/, patch 0017):**

- Roblox scales every face so its full line box (ascent + descent) is `TextSize`
  tall, not its em. Across 41 font families, Studio's `GetTextBoundsAsync` widths at
  TextSize 100 match `width x 1/(ascent+descent)` within 1.3%; heights equal TextSize
  (LegacyArial: 1.5x). `roblox_em_scale` applies this to AutomaticSize measurement.
  Press Start 2P and FredokaOne keep their own Studio-measured handling.
- At small sizes Roblox's widths run 2-6% wider than that rule (20px sample); the
  cause (hinting/advance rounding in Roblox's rasterizer) is not reproduced, so a
  20px AutomaticSize label can come out ~3px narrower. The Studio comparison allows
  text-sized objects 2px + 4%.
- The rule applies to drawing, TextScaled fitting, wrapping and truncation as well as
  AutomaticSize (patch 0018). Lines step by TextSize x LineHeight with no font line
  gap; TextScaled picks the largest size at which the wrapped text fits. Measured on
  RTL2PCParts in Studio: all 63 labels' TextBounds match (mean width error 2.7%).
- Rounding the em up to whole pixels fit the 20px averages better but made a real UI
  worse, so it is not done. Consequence: a line that only just overflows in Studio can
  still fit in RHR, so a label can wrap differently (tests/studio/ui_text, Roboto 18px,
  listed as a known difference in tests/test_studio_truth.py).
- TextTruncate: AtEnd keeps whole words when possible, SplitWord cuts inside the
  word (Enum.TextTruncate docs); RHR draws a single-character ellipsis where Roblox's
  docs show "...", a 1-5px difference.
- `GothamSSm` (retired Gotham) measures exactly like Montserrat in Studio and maps to it.
- Faces come from a local Roblox install when present (rhr.paths.roblox_font_dirs),
  then RHR's bundled open-license copies of Roblox's builds (src/rhr/fonts: Source Sans
  Pro 2.021, metrics identical to Roblox's), then Pinevex's bundled fonts. Builder Sans
  and other non-redistributable faces fall back to open fonts without an install. Tests
  force bundled fonts (`RHR_ROBLOX_FONTS=0`) so results match CI.

Which labels get their font fitted to the box is no longer an assumption: `TextScaled`
comes from the model, and `TextScaled` on implies `TextWrapped` (docs:
TextLabel.TextScaled). Before patch 0006 the vendored postprocess forced `textScaled=True`
on every TextLabel, so `TextSize` was decorative and a scaled label's long text shrank to
fit one line. `tests/fixtures/textscaled.rbxmx` + `tests/test_textscaled.py` pin all four
rules.

**Measured correction (2026-09-16):** Studio's fixed-box TextScaled label has
identical TextBounds at UIStroke thickness 0/2/5. Patch 0010 removes Pinevex's
outline reservation from the plain and RTL fit boxes. The matched white-backed
RTL2PCParts score improves from 83.488307% to 83.759069% within 8/255.
This closes stroke reservation, not the remaining glyph-metrics differences.
The historical PNG is retained; a separate corrected reference gates current
output exactly (`tests/baseline/README.md`).

**Assumed, still unmeasured:**

- glyph metrics for scaled text. pinevex fits with its own binary search over its own line
  metrics (min 1, max 100 unless the label carries a `UITextSizeConstraint`); Roblox uses
  its own ascent, descent and wrapping. The semantics now match the docs; the exact size a
  scaled label lands on may still differ from Studio by a little.
  **Measured 2026-09-17 (see history/results.md §0.2 frontier refinement):** the difference is not
  "a little". For FredokaOne, Roblox fits single-line size <= box height exactly (a 13px
  box fits size 13; our Skia line box forces 10.28), AND Roblox's rasterizer draws glyph
  advances at 0.75-0.80x of the identical TTF's raw skia advances (drifting with size, not
  a constant scale; binary verified byte-identical to the player client's). Both halves
  must land together; a per-family Studio-measured advance table is queued as plan work.
- a measured 14 px `TextSize` renders ~10 px of glyph pixels, so we treat `TextSize` as an
  em size. Roblox's docs call it the rendered line height. Same font, same reading, but the
  mapping was not measured against a Studio capture.
  **Measured 2026-09-17:** Studio TextBounds.Y == TextSize exactly at fixed sizes
  (8x8 .. 14x14), i.e. Roblox's line box IS the size; our Skia line box for the same
  binary is ~1.21 em. The em-size reading holds; the line-box mapping differs.
- wrapped line height uses pinevex's 1.17 em multiplier.
- `UITextSizeConstraint.MinTextSize` is read (default 1); no fixture pins its effect.

**The frozen reference cannot arbitrate text sizing.** All 63 of RTL2PCParts' labels are
genuinely `TextScaled`, so the forced-fit hack and the honest path render that model
identically (0 differing pixels; the regression gate is unchanged at 100.0000% / 99.5251%).
Studio ground truth for text has to come from a real UI model: the Studio builtin GUI
models change by 0.04-0.62% of pixels when the hack is removed.

## Browser 3D scene (Task 3.2, revised 2026-09-21)

`rhr scene` is a static authoring preview, not Roblox visual parity. It uses
THREE.js at a fixed pixel ratio. `WedgePart` and `CornerWedgePart` use native
deformed-box ramps. `MeshPart` and legacy `SpecialMesh:FileMesh` use cached Roblox
mesh bytes when available; missing mesh assets and `UnionOperation` remain explicit
geometry fallbacks in `scene-dump` / coverage notes.

The full-scene path now has deliberate agent camera controls (`--camera`,
`--look-at`, `--fov`, `--focus`, standard `--view` values) and a compact
`scene-dump` with world bounds and fallbacks. Missing focus/ViewportFrame paths
fail explicitly rather than producing a successful blank image.

### Compared with Studio screenshots (2026-09-22)

A scene built in Studio (shapes, materials, glass, neon, a sign, a billboard) was
rendered by RHR from Studio's camera and compared with Studio's screenshot:

- Geometry, camera framing, shadow direction and the default sky match.
- Fixed from that comparison: Roblox Color3 is sRGB (colours were washed out);
  WedgePart slopes along local Z (low at -Z) and CornerWedgePart's peak is over its
  (+X, -Z) corner (both were rotated 90 degrees; Studio raycasts); the sun follows
  Lighting:GetSunDirection (rises at +X, tilt sin(latitude - 23.5), sampled in
  Studio), and ClockTime/TimeOfDay now reach the scene (it had used a fixed sun);
  places without a Sky get a default-sky gradient; the shadow map covers the view,
  not the whole Baseplate; metals no longer render near-black without an environment.
- Still approximate: no material textures (grass, wood, baseplate studs); lighting
  intensities are calibrated by eye (Ambient/OutdoorAmbient fixed, sun and sky light
  scale with Brightness); shadows are opt-in (`--shadows`) while Studio draws them by
  default.
- In-world UI, checked in play mode: BillboardGui placement and size match Studio's
  camera projection exactly (Studio's screenshot tool never captures billboards, so
  this is compared by numbers). SurfaceGui content was mirrored on Front faces,
  rotated on Top/Bottom and drawn through the back of its part; each face's layout
  was measured in Studio and is now pinned by `tests/test_surface_gui_faces.py`.
- Decals and Textures: measured the same way with the Roblox logo on each face. Side
  faces were right; the Top image was drawn upright where Studio draws it upside
  down (viewed with screen-up = -Z), now fixed and pinned by `tests/test_decal_faces.py`.

### Model transforms

`Model.Scale` is **not applied**. Roblox's `Model:ScaleTo()` rewrites every
descendant part's `Size` and `CFrame`, and the Model's `Scale` property only records
the factor, so a saved file already holds the scaled geometry. Evidence: Studio's own
`ExtraContent/models/Photobooth/AbyssBlue.rbxm` saves a Model with `Scale = 8` whose
MeshPart is 8 x 0.008 x 8 studs, a 1 x 0.001 x 1 plane (0.001 is the minimum part
thickness) already scaled by 8. `tests/test_scene_model_scale.py` checks that a
scaled Model renders and dumps exactly like the same scene without the metadata.

An earlier version applied the scale around `WorldPivot` / `PrimaryPart` / the
geometry bounds on top of the stored values, which scaled saved models twice; that
code and its tests were removed (history: `docs/history/results.md`, 2026-09-22).

### Materials

Roblox materials are approximated with a data table of THREE
`MeshStandardMaterial` roughness/metalness values. Neon and CrackedLava add an
emissive approximation; Glass/Ice/Glacier/ForceField apply simple opacity
scales; `Reflectance` raises metalness. These values are internally measured
(`tests/test_scene_materials.py` proves distinct visible output and determinism)
but **have not been calibrated to Studio**. Unknown material names fall back to
Plastic and are counted as `materialFallbacks`; they never fail silently.

### Lighting and shadows

When a saved `Lighting` service exists, Ambient, OutdoorAmbient, Brightness,
ClockTime and GeographicLatitude drive the THREE hemisphere/directional-light
baseline. The sun path is deliberately simple: ClockTime supplies an hour angle
and latitude tilts the direction. It is useful for authoring previews, not a
claim about Roblox's astronomical model. Without a Lighting service, the old
deterministic hemisphere + key/fill defaults remain for compatibility.

Directional shadows are opt-in with `rhr scene --shadows`. They use a bounded
1024px PCF shadow map derived from scene bounds and respect `Lighting.GlobalShadows`
and each part's `CastShadow`. On the sampled 428-part Advanced Gun System place
at 676x336, six cached-IR runs measured median 1808ms without shadows and
1815.5ms with them; browser/startup and scene traversal dominate at that scale.
The visual result is deterministic but not Studio-calibrated, which is why
shadows remain explicit rather than silently changing every default render.

### Beam ribbons

Static `Beam` nodes now resolve Attachment0/Attachment1, evaluate Roblox's cubic
Bezier control points from `CurveSize0`/`CurveSize1` and each attachment's local X
axis, and generate a segmented ribbon. `Width0`/`Width1`, `Segments`, `FaceCamera`,
ColorSequence interpolation, Brightness, and local Texture assets are represented.
The ribbon is an authoring-preview approximation: runtime texture motion
(`TextureSpeed`), LightEmission/LightInfluence and ZOffset are not modelled, and
TextureMode UVs use a simplified length mapping.

### Trail ribbons

The static scene path synthesizes a bounded linear motion history from the parent
part's captured `AssemblyLinearVelocity`. It resolves Attachment0/Attachment1,
`Lifetime`, `MinLength`/`MaxLength`, `WidthScale`, ColorSequence, Transparency,
FaceCamera and basic TextureMode UVs into a ribbon. The fixture path is useful for authoring previews
and catches missing Trail coverage, but it is not runtime history: changing parent
poses, rotation, acceleration, `Clear()`, texture motion (`TextureSpeed`),
LightEmission/LightInfluence remain unmodelled. Trails
with no captured motion history stay explicitly unsupported in `scene-dump` rather
than rendering a guessed streak.

### Cached mesh geometry

`MeshPart` and `SpecialMesh:FileMesh` can resolve local decompressed `.mesh` files
from `--mesh-dir` and the shared `<rhr cache>/cache/meshes` directory. The render page
parses Roblox mesh versions 1.x through 5.x for the static vertex/face geometry used
by this preview path. The hermetic regression checks v1/v2/v3/v4/v5 against one
asymmetric silhouette and verifies that cached geometry visibly differs from the box
fallback; the representative 3D gallery also carries a cached MeshPart and requires
it to make a visible frame change.

For MeshPart, decoded geometry is fit to the authored Part `Size`. For legacy
FileMesh, the source mesh is transformed by `SpecialMesh.Scale` and `Offset`. This
baseline does **not** claim skinned/bone animation, mesh deformation, Roblox LOD
selection, SurfaceAppearance/PBR parity, or exact Studio normals/tangents. Mesh
rendering never reaches the network; `scripts/fetch_meshes.py` is a separate,
explicit cache-population helper. A missing/unsupported asset remains a reported
fallback instead of silently changing correctness based on network availability.

### Terrain raw-data status

Terrain voxel cells are serialized in the hidden `SmoothGrid` BinaryString, which
Lune/rbx-dom does not expose through the normal Instance property surface used by the
IR emitter. RHR now has a narrow raw Roblox binary/XML extractor that recovers that
single serialized property without introducing a second DOM implementation. Binary
files use the documented v0 chunk framing and LZ4 block compression; the extractor
only decodes INST metadata plus String/BinaryString PROP values and fails explicitly
on unsupported ZSTD chunks.

`scene-dump` reports each Terrain as `rawAvailable`, `smoothGridBytes`, and `empty`.
The standard two-byte SmoothGrid sentinel `01 05` (base64 `AQU=`) is treated as empty,
so an empty Workspace.Terrain is not counted as an unsupported visual. Non-empty or
unavailable raw terrain stays explicitly unsupported. RHR does **not** yet decode
SmoothGrid cells into materials/occupancy or render voxel terrain.

### Sky and Atmosphere

A saved `Atmosphere` under `Lighting` maps to a bounded authoring approximation:
`Color`/`Decay` tint the environment, while `Density`, `Haze` and `Offset` drive a
THREE `FogExp2` density. `Glare` is preserved in `scene-dump` but is not yet rendered
as sun-scattering/bloom. This is intentionally useful-for-framing fog, not a claim
that Roblox's atmospheric scattering equations are reproduced. The regression keeps
background tint and geometry-distance fog as separate visible effects.

A saved `Sky` under `Lighting` can install a local six-face cube map when all six
Skybox assets resolve from `--texture-dir` / `<rhr cache>/cache/icons`. The renderer never
fetches those faces during rendering; an incomplete sky remains visible in
`scene-dump.sky.complete=false` and each missing face appears in `assetReferences`.
`SkyboxOrientation` is applied through THREE's background rotation when available.
The six-color orientation fixture pins Roblox Right/Left/Up/Down/Back/Front mapping
independently. CelestialBodiesShown, StarCount and sun/moon angular sizes are reported,
but sun, moon and star sprites are not yet drawn as separate objects.

When copies of Sky/Atmosphere exist outside `Lighting`, the scene path and
`scene-dump` prefer descendants of the actual `Lighting` root; this matters in real
places that store template environment objects under Players or folders.

### Static surface images and local lights

Direct-Part `Decal` and tiled `Texture` surfaces resolve local image IDs from
`--texture-dir` first, then `<rhr cache>/cache/icons`. Missing files are listed in
`scene-dump.assetReferences` and summarized as `missing-assets=N` on scene
renders. Face mapping follows the same NormalId convention as the SurfaceGui
baseline. Texture supports StudsPerTileU/V and OffsetStudsU/V; filtering and
mipmap behavior are THREE defaults, not Roblox parity.

PointLight, SpotLight and SurfaceLight are approximated with THREE local lights
for direct Part parents and Attachment parents. Color/Brightness/Range are
preserved; Spot/Surface also use Face and Angle. Their intensity conversion is
an authoring-oriented approximation and has not been Studio-calibrated. Local
light shadows are only enabled when both the Roblox `Shadows` property and
`--shadows` are on.

The geometry/material/lighting fixtures prove deterministic visible behavior;
the next fidelity step is the controlled Studio scene calibration suite, not
further hand-tuning against THREE itself.

## In-world UI: BillboardGui and SurfaceGui

The GUI inside a BillboardGui or SurfaceGui is drawn by the same 2D engine as
ScreenGuis (full layout, fonts, images, UICorner/UIStroke, every GUI child), on the
canvas size Roblox would give it: for a BillboardGui, its `Size` scale in studs at
the camera distance plus the offset in pixels; for a SurfaceGui, `CanvasSize` in
`FixedSize` mode or the face size x `PixelsPerStud`. The scene page asks the local
server for that PNG and places it; a failed GUI render fails the whole render.

What is approximated:

- Placement. BillboardGui supports parent CFrame, `Adornee` (resolved by instance
  id), `StudsOffset`, `StudsOffsetWorldSpace`, `ExtentsOffset`,
  `ExtentsOffsetWorldSpace`, `SizeOffset`, `MaxDistance` and `AlwaysOnTop`; extents
  use the adornee Part's half-size. SurfaceGui picks the `Face` and maps the image
  onto the four projected corners with a CSS homography; `ZOffset` orders panels on
  the same face.
- Occlusion. Non-`AlwaysOnTop` panels are dropped when a camera-to-anchor ray hits
  closer geometry; there is no per-pixel depth against the 3D canvas, so a
  partially covered panel is drawn whole or not at all.
- Canvases larger than 4096 px per side are clamped to 4096.
- Lighting (`LightInfluence`, `Brightness`) is not applied.

## ViewportFrame (Task 3.3 baseline)

A ViewportFrame is rasterized as a transparent local THREE.js pass and composited
at the resolved 2D rect. The baseline supports direct Part descendants, a child
Camera's CFrame/FOV, the ViewportFrame's own `CameraCFrame` property (2026-09-19:
real-game saves store the authored pose there and carry no Camera node; before the
fix every extracted real-game viewport rendered its 3D content empty), Ambient,
LightColor, LightDirection, ImageColor3, and ImageTransparency. Mesh/union fidelity, shadows, Sky, post-processing, nested
GuiObjects, and exact Roblox lighting remain unsupported. The fixture
`tests/fixtures/viewport_frame.rbxmx` proves containment and clipping; Studio
pixel parity has not yet been measured for this fixture.


The particle preview is a deterministic approximation, not Roblox runtime
execution. It uses a fixed timestep, seeded random ranges, linear sequence
sampling, and a concurrent particle cap. Current rendering uses THREE billboard
sprites with local texture support from `--texture-dir` or the shared
`<rhr cache>/cache/icons` populated by the existing asset fetcher, Brightness color
scaling, and the documented LocalTransparencyModifier formula. Box, Sphere,
Cylinder, and Disc volume/surface spawn positions are supported, including
ShapePartial sphere caps, disc annuli, and cylinder top-radius taper. Squash curves
are applied as non-uniform billboard scaling. VelocityParallel and
VelocityPerpendicular project particle velocity into the camera plane. ZOffset
moves sprites along camera depth without changing screen size. `VelocityInheritance`
adds a clamped fraction of the nearest captured Part's
`AssemblyLinearVelocity` to new particles before drag and acceleration are applied.
`LockedToPart` adds the captured constant parent displacement to active particles
without changing their local velocity. This covers linear motion only; parent
rotation and changing pose trajectories are not yet modelled. LightEmission uses an
additive blend approximation. Remote asset acquisition and exact Roblox texture
filtering are not yet modelled. Scripts are not executed; `--burst N`
provides an explicit immediate burst for each emitter, while path-specific
script triggers remain outside the preview contract.

The contact-sheet fixture proves useful visible motion and repeatability. It
must not be used to claim Roblox visual parity until the Studio comparison gate
has a real matched capture.


Pinevex renders one root per engine pass; the pipeline runs one pass per ScreenGui
and composites them in DisplayOrder paint order (Task 1.12), so a file with
several ScreenGuis renders every pane. See the DisplayOrder note in `history/results.md`.

## A class the reflection database does not have (Task 1.11)

The emitter reads only the property names rbx-dom's bundled reflection database lists for a
class, which is what makes a dump fast enough to run per render. A class that database does
not have (newer than the bundled build, or a plugin-only class) falls back to reading every
allowlisted name, and the bridge cannot hand back the ones it has no metadata for, so those
values are recovered from the file's XML text instead:

- scalars convert by the datatype their tag names: `bool` to a boolean, `int`/`int64`/
  `float`/`double` to a number, `string` to decoded text. XML entities are decoded, so a
  value arrives as the string the model carries rather than its XML spelling.
- everything else the bridge cannot read is named in the node's `unreadable` list: `token`
  (enum) values, `Ref`, and the struct datatypes (`UDim2`, `Color3`, `Vector2`, `Rect`)
  whose XML nests child tags. Effect: an unknown class renders without its geometry and
  colours, and says which properties are missing.

Before 2026-09-15 that path was worse in two ways, both reproduced and fixed: text arrived
with its escape entities intact (`cheap &amp; cheerful`), and every recovered value was a
*string*, so `Visible = false` reached the renderer as the truthy string `"false"` and the
node drew anyway. Fixtures: `tests/fixtures/unknown_class.rbxmx` (typed properties named)
and `tests/fixtures/unknown_class_values.rbxmx` (bool, int, escaped text).

The related trap, now closed: a property whose datatype tag contains a digit (`UDim2`,
`Color3`, `Vector2`, `Color3uint8`) was invisible to that XML pass, because the tag pattern
was `[%a]+` and `%a` is letters only. Such a property was neither recovered nor named. The
pattern is `[%w]+` now.

## Compositing several ScreenGuis (Task 1.12)

pinevex draws exactly one root, so a file holding several ScreenGuis is rendered as one
engine pass per pane and composited in paint order, lowest `DisplayOrder` first, with plain
alpha-over. Two consequences, both worth remembering when a diff disagrees with what is on
screen:

- the composite is per pane, so a pane whose render would blend with the pane beneath it (a
  CanvasGroup with an unsupported blend mode) composites as if its render were already flat;
  `CanvasGroup.GroupTransparency` itself is preserved and applied to the group render layer;
- a GuiObject that is not inside a ScreenGui does not draw in Roblox, but Studio's own
  models keep their main panel exactly that way, so the tree outside the ScreenGuis is a
  pane of its own at the bottom of the stack, and it gets no safe-area inset because it has
  no ScreenGui to read one from.


## Image filtering (patch 0011)

Stretch/Fit/Crop now preserve ResampleMode: Default uses Skia bilinear filtering,
Pixelated uses nearest, including UIGradient image draws. The matched Studio
capture improves to 84.301476% within 8/255. Exact Roblox filtering, thumbnail
versus original image resolution, and mipmap behavior remain unverified.
The Mythic card's gradient properties reach the shader intact; its tint/alpha
ramp was checked independently. Original image bytes for assets 88932096662635
and 116138393948982 remain unavailable through unauthenticated delivery (HTTP
401 measured 2026-09-17). Authorized originals or authenticated delivery are
needed to isolate source-image differences from renderer differences.
Tile still uses nearest and Slice linear independently of ResampleMode; this
change does not validate those choices. They need separate Studio fixtures.

## Explicit text newlines (patch 0012, extended by 0007's unwrapped-line hunk)

Plain wrapped text, TextScaled fitting and unwrapped plain text now preserve
explicit newline and empty paragraph boundaries. Studio confirmed two lines for
Hello\nworld wrapped (fixed TextSize) and unwrapped, plus TextBounds 47x40
unwrapped at TextSize 20 in a fixed 240x60 box; tests measure painted line bands
and determinism, not exact Studio glyph metrics. Splitting long words remains
outside this correction.

## TextTruncate ellipsis placement (Task 2.2)

Patch 0007 draws `TextTruncate` = AtEnd/SplitWord: an unwrapped line wider than
its content box is cut so the line plus `…` fits, measured with the engine's own
mixed-run metrics (`_measure_mixed`); SplitWord backs up to the last word boundary
inside that. Truncation is applied per explicit-newline line, not to the whole
string. **Not measured against Studio:** where Roblox puts the ellipsis (and
whether it trims grapheme- or shape-cluster-wise) is a ground-truth question for a
Task 0.2 capture; the fixture pair (`text_truncate_at_end`, `text_truncate_split_word`)
pins OUR behaviour, not parity. `MaxVisibleGraphemes` is deliberately not drawn: a
typewriter window is a fact over time, not of a still layout, and the Roblox docs
say layout is computed as if every grapheme were visible — `rhr check` reports the
window instead.
