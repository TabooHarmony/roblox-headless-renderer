# Known approximations

RHR aims for a useful preview, not a copy of Studio's renderer. This page lists
where its output differs from Roblox, or has not been checked against it. When a
command approximates something at run time, it also says so in its own output
(`notes` on stderr, `fallbacks` / `experimental` in `scene-dump`), so an agent does
not need this page to avoid being misled. It is here so you know what to expect.

"Measured" below means compared with numbers Roblox Studio recorded for the same
file (`tests/studio/`, see its README). Everything else is RHR's best reading of
Roblox's documentation.

## UI layout

**Measured.** Every GuiObject's rectangle comes from RHR's own layout pass
(`src/rhr/ui_layout.py`), checked against Studio on about 450 objects: all within
2 px, except text-sized objects, which get 2 px + 4%.

Covered: UDim2 size and position, AnchorPoint, SizeConstraint, UIPadding,
UISizeConstraint, UIAspectRatioConstraint, UIScale, AutomaticSize (from text and
from children), UIListLayout (sorting, alignment, Wraps, flex, UIFlexItem,
ItemLineAlignment), UIGridLayout (FillDirectionMaxCells, StartCorner, alignment),
UITableLayout, ScrollingFrame canvas and CanvasPosition.

Not yet measured against Studio: UIPageLayout (laid out like a list, no page
animation), UITableLayout `FillEmptySpace*`, flex shrink with wrapping, and
ItemLineAlignment Stretch.

**The top bar.** Screen UI is laid out below Roblox's 58 px top bar
(`ScreenInsets = CoreUISafeInsets`, the default), as in a running game. Studio's
edit view has no top bar: pass `--topbar-height 0` to match it. `None` and
`DeviceSafeInsets` use the whole viewport (a desktop has no notch).
`TopbarSafeInsets` is not modelled; it falls back to `CoreUISafeInsets` with a
note on stderr. Mobile safe areas are not modelled.

**Several ScreenGuis** are drawn one per pass and stacked by `DisplayOrder`. A
disabled or empty ScreenGui is skipped by every command. UI outside any ScreenGui
(Studio's own plugin models are built that way) is drawn as a bottom layer with no
top-bar inset.

## Text

**Measured:** Roblox makes `TextSize` the full line height (ascent + descent), not
the font's em size, and RHR does the same for drawing, TextScaled fitting,
wrapping, truncation and AutomaticSize. Heights match Studio exactly; widths within
a few percent.

Known differences:

- At small sizes (around 20 px) Roblox's text runs 2-6% wider than the rule above,
  from its own glyph rounding. A line that only just overflows its box in Studio can
  still fit in RHR, so it may wrap differently.
- TextTruncate draws a one-character ellipsis (`…`) where Roblox's docs show `...`,
  a 1-5 px difference. Where exactly Roblox cuts has not been measured.
- `MaxVisibleGraphemes` is not drawn (it is a typewriter effect over time);
  `rhr check` reports it instead.
- Right-to-left text with a non-default `LineHeight` keeps the default spacing.
- A symbol no bundled font has (`✕`, `✓`, `★`, `▶` and their neighbours) is drawn
  from the operating system's fonts, as Roblox does, so its exact shape depends on
  the machine. On a machine without such a font it draws as an empty box. Set
  `RHR_SYSTEM_FONT_FALLBACK=0` to never use system fonts.
- Fonts: RHR uses the fonts of a local Roblox or Studio install when there is one
  (stderr says which), then bundled open-licence copies of the builds Roblox ships
  (Source Sans Pro, Roboto, and others), then look-alikes. Builder Sans and other
  faces that cannot be redistributed fall back to a look-alike without an install.
  Set `RHR_ROBLOX_FONTS=0` to always use the bundled fonts.

## Images

Images are drawn only from the local cache (`scripts/fetch_assets.py` fills it for
the asset ids in your model). Rendering never downloads anything. A missing image
leaves its area empty and is listed as a missing asset. Private assets usually
cannot be fetched without being signed in.

`ResampleMode` (Default = smooth, Pixelated = nearest) is honoured for Stretch, Fit
and Crop. Tile and Slice filtering, and whether Roblox uses a thumbnail or the
original resolution, have not been checked.

## Clickable regions (`rhr hitmap`)

Uses the same rectangles as `rhr layout`. An element counts as interactive when it
is a button, a TextBox, or has `Active` or `Selectable` set. Each report probes the
centre of every interactive element and names the topmost `Active` element as the
target. A hidden (`Visible = false`) `Active` element is kept on purpose: an
invisible element that swallows clicks is exactly the bug this command is for.

## 3D scenes

`rhr scene` and `rhr preview` draw a static authoring preview with THREE.js in
headless Chromium.

**Measured:** part positions, sizes and rotations (`rhr scene-dump`) match Studio.
Compared with Studio screenshots of the same scene, geometry, camera framing,
shadow direction and the default sky match.

**Model.Scale** is recorded, not applied. `Model:ScaleTo()` rewrites every part's
size and position, so a saved file already holds the scaled geometry (checked on a
scaled model that ships with Studio).

**Approximate, by eye:**

- Materials are roughness/metalness values per material, with no textures (no
  grass, wood or baseplate studs). Neon glows; glass-like materials are see-through.
  Unknown materials draw as Plastic and are counted as `materialFallbacks`.
- Lighting: Ambient, OutdoorAmbient, Brightness, ClockTime and GeographicLatitude
  drive the sun and sky light; intensities are tuned by eye. Shadows are off unless
  you pass `--shadows` (Studio draws them by default).
- Point, Spot and Surface lights: colour, brightness, range and angle are used;
  intensity is not calibrated.
- Atmosphere is simple fog; `Glare` is not drawn. A Sky needs all six faces in the
  local image cache; the sun, moon and stars are not drawn.
- Decals and Textures need their images cached. Face orientation was checked in
  Studio.

**Drawn as stand-ins, and reported as such:**

- MeshParts and FileMeshes use cached mesh files (`scripts/fetch_meshes.py`); without
  one, the part is drawn as a box and counted as a geometry fallback. Skinned meshes,
  bones, LOD and SurfaceAppearance are not modelled.
- Unions (`UnionOperation`) are drawn as their bounding box.
- Terrain is not drawn. `scene-dump` reports whether a place has any.

## In-world UI (BillboardGui, SurfaceGui)

The GUI inside them is drawn by the same engine as screen UI, on the canvas size
Roblox would give it. BillboardGui placement and size match Studio's camera
projection (measured in play mode). SurfaceGui face orientation was measured in
Studio for every face.

Approximate: a panel partly hidden behind geometry is drawn whole or not at all (one
ray to its anchor decides). Canvases larger than 4096 px per side are clamped.
`LightInfluence` and `Brightness` are not applied.

## ViewportFrame

The 3D content is drawn with the same scene renderer and placed at the frame's
rectangle. Supported: parts, the frame's own `CameraCFrame` or a child Camera,
Ambient, LightColor, LightDirection, ImageColor3 and ImageTransparency. Not
supported: shadows, Sky, post-processing and GUI objects inside the frame. Not yet
compared with Studio.

## Effects (experimental)

These are rough sketches, useful for checking that an effect is there and roughly
where, not how it looks:

- **ParticleEmitter** (`rhr particles`, `rhr preview --time T`): a deterministic
  simulation with a fixed timestep and seeded randomness. Scripts are not run, so
  `Emit()` calls do not happen; `--burst N` stands in for them. Parent rotation is
  not followed.
- **Beam**: curve, widths, segments, colour and texture are drawn. Texture motion,
  LightEmission and LightInfluence are not.
- **Trail**: built from the parent part's saved velocity. A trail with no saved
  motion is reported as unsupported rather than guessed.

## Reading files

RHR reads files with Lune and rbx-dom. A class that rbx-dom's database does not know
(newer than its build, or plugin-only) is read from the file's XML: simple values
(booleans, numbers, text) are recovered; enums, references and structured values
such as UDim2 and Color3 are listed in that node's `unreadable` list, so the element
may draw without its size or colour and the output says which properties are
missing.

## Not done at all

Scripts, physics, animation and anything else that happens at run time. A UI that a
script builds or moves is previewed as it is saved in the file.
