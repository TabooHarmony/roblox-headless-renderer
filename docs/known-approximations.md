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
disabled or empty ScreenGui is skipped by every command. In a place file, only
StarterGui's ScreenGuis are on screen: ones kept in ReplicatedStorage, ServerStorage
and the like are templates that scripts clone in at run time, so they are left out
and named on stderr (`--all-guis` draws them). A model file draws every ScreenGui. UI outside any ScreenGui
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
  from a symbol font that comes with the operating system (Segoe UI Symbol, Apple
  Symbols, DejaVu Sans), as Roblox uses the system's fonts, so its exact shape
  depends on the machine. On a machine without such a font it draws as an empty box. Set
  `RHR_SYSTEM_FONT_FALLBACK=0` to never use system fonts.
- Fonts: RHR uses the fonts of a local Roblox or Studio install when there is one
  (stderr says which), then bundled open-licence copies of the builds Roblox ships
  (Source Sans Pro, Roboto, and others), then look-alikes. Builder Sans and other
  faces that cannot be redistributed fall back to a look-alike without an install.
  Set `RHR_ROBLOX_FONTS=0` to always use the bundled fonts.

## Images

Images are drawn from the local cache. `render`, `scene` and `preview` first download
the ones the file uses that are not cached, as the Roblox Studio user (the original
file, at full size); `--offline` skips that. Without a Studio login an image comes
from Roblox's thumbnail service instead, at most 420 px, which puts sprite-sheet
crops (`ImageRectOffset`, measured in the original's pixels) in the wrong place. A
missing image leaves its area empty and is listed as a missing asset.

`ResampleMode` (Default = smooth, Pixelated = nearest) is honoured for Stretch, Fit
and Crop. Tile and Slice filtering have not been checked.

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

**Compared side by side with Studio** (a swatch of 16 materials, a brick wall, a
union and terrain, same camera, default lighting; with Roblox Studio installed and
signed in, see below):

- Materials use Roblox's own texture maps (colour, normal, roughness, metalness),
  downloaded by the asset ids Roblox publishes (`src/rhr/scene/roblox_materials.json`,
  from its creator docs). The colour map's alpha says where the part's Color applies:
  Brick's bricks take the colour and the mortar keeps its own, as in Studio. Textures
  tile every 10 studs. `MaterialService.Use2022Materials` picks the current or the
  pre-2022 set; a model file (no MaterialService) uses the current one. Metals follow
  `Lighting.EnvironmentSpecularScale`: at 0 they read as their colour, as in Studio; at
  1 they reflect the sky. A part's MaterialVariant uses its own maps, tinted by the
  part's Color and tiled at its StudsPerTile, once they are cached. Glass-like
  materials are see-through.
- Neon is unlit and drawn about 3x brighter than its colour; bright Neon glows in its
  own colour (a blurred quarter-resolution copy added over the picture, as Roblox
  does it) and dim Neon does not. Transparent Neon is see-through by its
  Transparency, with less glow. (In Studio a strongly transparent Neon part reads
  more solid than that; RHR keeps what is behind it visible.) Compared with Studio at
  its highest quality level; at low quality levels Studio draws no glow at all. Unknown materials draw as Plastic and are
  counted as `materialFallbacks`. `--flat-materials` draws plain colours.
- Plastic has Roblox's faint surface relief, and legacy surfaces (`TopSurface =
  Studs`, Inlet, Weld, Glue, Universal on block Parts of Plastic or SmoothPlastic) are
  drawn with the install's surface textures, 2 studs per tile.
- With no Sky, the sky is Roblox's default one from the install. A Sky's faces are
  stretched onto squares as Roblox does, whatever the images' own sizes.
- Unions are drawn with the render mesh Studio saved: downloaded by the union's
  AssetId (modern places) or read from the file (older ones), with each source part's
  colour unless UsePartColor is set. A union made in a Studio session and exported
  before the place was saved has neither; it is drawn as its outlined bounding box
  and counted as a geometry fallback.
- Terrain is meshed smooth from the place's voxels (surface nets: the surface crosses
  between a solid and an empty voxel as far as the solid one's occupancy reaches),
  with Roblox's terrain textures for each face direction (top, side, bottom), 8 studs
  per tile, coloured by the material's base colour and the place's MaterialColors.
  Where two materials meet the edge is hard; Roblox blends them. Grass came out a
  little brighter and yellower than Studio's, rock a little lighter. Terrain
  decorations (grass blades) and water waves are not drawn.

**Without Roblox Studio** on the machine (or signed out): images are 420 px
thumbnails, meshes and unions are outlined boxes, materials use public-domain (CC0)
ambientCG look-alikes (`src/rhr/scene/materials/credits.json`) at 4-10 studs per
tile, the default sky is a gradient, and there is no plastic relief or stud texture.
stderr says so on every 3D render.

**Approximate, by eye:**

- Lighting in modern places (`EnvironmentDiffuseScale` above 0, as every current
  Roblox template has) is fitted to Studio: a calibration rig (white, grey, dark and
  coloured blocks, a pillar, an overhang, panels 25 to 800 studs away) built under a
  Roblox template's lighting, captured in Studio at its highest quality level and
  rendered by RHR at the same cameras; the sun strength, sky light, ambient, sky
  brightness, fog colour, exposure and tone curve were searched to minimise the
  difference (on average about 8/255 per channel over 35 sampled regions, from 22
  before). The model: the sun with shadows; light from the sky as drawn (Atmosphere
  veil included), which gives shadows and shaded faces Roblox's sky-blue colour;
  sky visibility on a 4-stud voxel grid, as Roblox computes it, so the floor under an
  overhang, the wall behind a pillar or the inside of a room get less sky light than
  open ground; Ambient / OutdoorAmbient as a little flat light; and a per-channel
  tone curve, so very bright colours drift toward white as Roblox's do. Sky
  visibility treats a part as covering the cells it overlaps (meshes and unions by
  their bounding box, weighted down), so thin or open meshes block more sky than they
  should, and a room lower than about 4 studs is too coarse for the grid.
  `ExposureCompensation` is applied.
- Older places (`EnvironmentDiffuseScale` 0) keep the earlier model, set by eye and
  matched against Studio's legacy lighting: ambient plus a sky-coloured hemisphere
  light and the sun.
- Shadows from the sun are on by default, as in Studio (`--no-shadows` turns them
  off). Two shadow cascades cover the view out to 500 studs from the camera: sharp
  near it, coarser further away; nothing casts shadows beyond that. On the GPU they
  cost a few percent of render time.
- Post-processing (experimental): `BloomEffect` (what is brighter than its Threshold,
  blurred by its Size, added at its Intensity) and `ColorCorrectionEffect` (Brightness,
  Contrast, Saturation, TintColor) are drawn, set by eye; Studio's own at low quality
  levels draws neither. `SunRaysEffect`, `DepthOfFieldEffect`, `BlurEffect` and
  `Clouds` are not drawn and are listed under `unsupportedVisualClasses`.
- Point, Spot and Surface lights: colour, brightness, range and angle are used;
  intensity is not calibrated. At most the 16 most relevant (nearest the camera,
  weighted by range and brightness) are drawn, because each light costs every pixel;
  a note says how many were left out.
- Atmosphere, measured in Studio with black and white panels 25 to 800 studs away at
  Density 0.2, 0.375 and 0.6 and Haze 0, 2 and 5: geometry fades as
  exp(-(depth / L)^p), with L and p rising steeply with Density (at 0.2 almost
  nothing fades, at 0.6 everything is gone by 200 studs); other densities are
  interpolated. Haze veils the sky: everything below the horizon once Haze reaches
  1, a band above the horizon that widens with Haze, the whole sky from Haze 5.
  `Offset` and `Glare` are not drawn. In an automatic view (`--view`, `--focus`),
  which stands far back from a whole map, the fog is capped so the build stays
  readable. A Sky whose six faces are not all cached draws the default sky.
  The sun, moon and stars are not drawn. With several Sky objects the first one is
  used; which one Roblox picks has not been checked.
- Decals and Textures need their images cached. Face orientation was checked in
  Studio.

**Drawn as stand-ins, and reported as such:**

- MeshParts and FileMeshes use cached mesh files, downloaded before a render with
  the Studio login (Roblox serves most meshes only to a signed-in account). Every mesh
  format is read, including versions 6 and 7 (version 7 is Draco-compressed; RHR
  ships Google's decoder); only the most detailed level of detail is drawn. A mesh file
  that cannot be read is drawn as a box and a note says so. A MeshPart
  with its mesh is drawn with its SurfaceAppearance maps through the mesh's UVs
  (AlphaMode Transparency cuts out, Overlay shows the part colour through; normal,
  roughness and metalness maps are used). Without the mesh it is a placeholder: its
  bounding box with an outline, no shadow, coloured from the SurfaceAppearance image,
  counted as a geometry fallback. Skinned meshes, bones and LOD are not modelled.

## Rendering speed and the GPU

3D renders use the machine's GPU through Chromium's WebGL, which is about eight
times faster than software rendering (a textured test scene: 2 s instead of 17 s).
Pixels can then differ slightly between GPUs: on the development machine a GPU render
differed from a software one on 0.13% of pixels, by 0.4/255 on average.
`RHR_WEBGL=software` draws on the CPU (SwiftShader) for identical pixels everywhere;
the tests and CI use it. A machine without a usable GPU falls back to software by
itself.

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

## Effects

Particles, Beams and Trails are drawn inside the 3D scene as one still frame. The aim
is that an agent sees whether an effect is there, where, how big, what colour and
whether it glows; not the exact particles Roblox would draw.

- **Playing an effect.** Scripts are not run. Most VFX keep their emitters disabled
  and a script plays them with `:Emit()`; the community convention stores how in
  attributes: `EmitCount` (emitted at once), `EmitDelay` (seconds after the start) and
  `EmitDuration` (seconds switched on at `Rate`). RHR reads these and plays the effect
  itself. An Enabled emitter runs the whole time, already full at the start. A
  disabled emitter without these attributes is not drawn and is named in the output.
  Other attributes (tweened sizes, `TimeScale_*` curves and the like) are ignored.
- **Which moment.** By default, the middle of the stretch where the most particle area
  is on show (the output says which moment); `--effect-time T` picks another.
- **Randomness** is seeded per emitter (`--seed`), so the same file gives the same
  picture, but particle positions are not the ones Roblox would pick.
- **Size and shape**, measured in Studio: a particle is 2 x `Size` across; `Squash` s
  stretches one axis by 1 + |s| and shrinks the other as much (taller for s > 0,
  wider for s < 0). `SpreadAngle` X turns the direction about the part's X axis and Y
  about the axis across X and the direction (a Back emitter with (0, 60) fans out
  flat). A Disc's `ShapePartial` is how much of the radius emits, from the rim in. An
  emitter without a `Texture`, or whose texture cannot be loaded, draws nothing, and a
  particle aligned to its velocity (`VelocityParallel` / `VelocityPerpendicular`) draws
  nothing while it has none, as in Roblox. Transparency sequences are clamped to 0..1.
- **Blending and brightness**, fitted to a sweep of flat particles in Studio
  (`LightEmission` -2..1, `Brightness` 1/5/25, transparency 0/0.5/0.75, over black and
  white; 9/255 RMS end to end): each colour channel is capped softly near 2.5, alpha
  acts as alpha^1.45, `LightEmission` 1 adds light and below 0 darkens what is behind
  hard, and the result goes through Studio's tone curve, which turns very bright
  colours toward white (bright orange turns yellow, then white). In a scene without
  Lighting, the particles alone are blended this way and put back over the picture.
  The fit is to a default Baseplate in Studio; other Lighting shifts it. `ZOffset`
  moves particles toward the camera, keeping their size on screen.
- **LightInfluence** is not applied. In Studio's default daylight it brightens a
  particle by 10-30% at most.
- **Framing**: without a Camera or `--view`, the view covers visible parts and the
  bulk of the particles (5th to 95th percentile), not invisible holder parts or a few
  sparks flung far away.
- **Drawn**: emission from parts (Box, Sphere, Cylinder, Disc shapes) and attachments
  (a point), following their rotation; `EmissionDirection`, `SpreadAngle`, `Speed`,
  `Acceleration`, `Drag`, `TimeScale`, rotation, size, colour, transparency and
  `Squash` over lifetime, flipbooks, and every `Orientation`.
- **Not applied**: `LightInfluence` (particles are drawn as if it were 0, which most
  VFX use), size and transparency envelopes, `LockedToPart`, wind, `VelocityInheritance`
  (parts do not move in a still frame). Built-in `rbxasset://` particle textures are not
  read from the Studio install yet; like a texture that could not be downloaded, they
  are drawn as soft dots, and the output says so. Fire, Smoke, Sparkles and Explosion
  are not drawn.
- **Beam**: curve, widths, segments, colour, texture and `LightEmission` are drawn.
  The texture's vertical axis runs along the beam; `Stretch` repeats it `TextureLength`
  times, `Wrap` every `TextureLength` studs (measured in Studio). Texture motion
  (`TextureSpeed`) and `LightInfluence` are not drawn, so a still frame shows the
  texture at its starting offset.
- **Highlight**: the fill and the outline (about 3 px) are drawn, over everything
  (`AlwaysOnTop`) or only where seen (`Occluded`); fills first in order, then every
  outline, as Studio does. Only the front faces make the shape, so holes in a mesh get
  their own outline. The first four Highlights are exact; later ones get a plain fill.
- **Trail**: built from the parent part's saved velocity. A trail with no saved
  motion is reported as unsupported rather than guessed.

## Reading files

RHR reads files with Lune and rbx-dom. A class that rbx-dom's database does not know
(newer than its build, or plugin-only) is read from the file's XML: simple values
(booleans, numbers, text) are recovered; enums, references and structured values
such as UDim2 and Color3 are listed in that node's `unreadable` list, so the element
may draw without its size or colour and the output says which properties are
missing.

A part that is fully transparent (Transparency 1) is not drawn at all, so it does not
hide effects behind or inside it. A Sky or Atmosphere counts only inside Lighting, as
in Roblox; one saved elsewhere in a model changes nothing.

## Not done at all

Scripts, physics, animation and anything else that happens at run time. A UI that a
script builds or moves is previewed as it is saved in the file.
