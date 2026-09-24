# Changelog

## 0.5.0 (alpha)

RHR now assumes Roblox Studio is installed and signed in on the machine (anyone
making Roblox content has it) and uses it by default. Checked side by side with
Studio on a swatch of materials, a union and terrain, and on real game places.

### Added

- **Automatic downloads.** `render`, `scene` and `preview` download what the file
  uses and the cache lacks, as the Roblox Studio user, before drawing: meshes, unions,
  Roblox's material textures and images at full size (no more 420 px thumbnails,
  which also misplaced sprite-sheet crops). Cached assets are never downloaded again;
  assets Roblox refuses are not asked for again for a day. `--offline` /
  `RHR_OFFLINE=1` skips it. `rhr fetch` uses the login by default
  (`--no-studio-login` to not). Without Studio, stderr says the preview will look less
  like Roblox.
- **Roblox's own material textures**, by the asset ids Roblox publishes: colour,
  normal, roughness and metalness maps, tinted the way Roblox does it (the colour
  map's alpha says where the part colour applies: Brick's mortar keeps its own
  colour), 10 studs per tile, with the current or pre-2022 set per
  `MaterialService.Use2022Materials`. Metals follow `EnvironmentSpecularScale`.
- **Unions** are drawn with the render mesh Studio saved (downloaded by AssetId, or
  read from the file for older places), with each source part's colour unless
  UsePartColor is set. Previously a bounding box.
- **Smooth terrain**, meshed from the voxels the way Roblox does it, with Roblox's
  terrain textures for top, side and bottom faces and its colouring. Previously
  4-stud blocks.
- **From the Studio install:** the default sky, Plastic's surface relief, and legacy
  surfaces (a Baseplate's studs; Inlet, Weld, Glue, Universal).
- **SurfaceAppearance and MaterialVariant** normal, roughness and metalness maps.
- Metals and glass reflect the sky.

### Fixed

- Skies whose face images are not square (1023x682 and the like) drew black.
- A Sky's left and right faces were swapped, leaving seams at the sides.
- Places saved with ZSTD-compressed chunks lost their terrain.

## 0.4.0 (alpha)

### Added

- **Terrain** is drawn, as 4-stud blocks. RHR decodes the place's saved voxels (the
  format has no public spec; it was worked out and checked voxel by voxel against
  Studio) and colours each block by material, or with the MaterialVariant image the
  place assigns to that material. Builds no longer float.
- **`rhr fetch --use-studio-login`** downloads the meshes Roblox serves only to
  signed-in accounts (most of them) as the user signed in to Roblox Studio on the
  machine. The login is read and sent to roblox.com by Lune; RHR never sees or
  stores it. On Roblox's game template this took real meshes from 0 to 47 of 47.
- **SurfaceAppearance images** are drawn on real meshes (foliage cut-outs, Overlay
  colour), and MaterialService's per-material overrides are applied to parts and
  terrain.

## 0.3.0 (alpha)

Found by running RHR on Roblox's own game template (2,800 instances, 800 MeshParts,
Terrain, 120 lights, MaterialVariants), and fixed:

### Fixed

- **Every UI command crashed on a UI using Builder Sans**, Roblox's default UI font
  (a font given by asset id needed the undeclared `zstandard` package).
- **Place files drew ScreenGuis stored in ReplicatedStorage** on top of the real HUD
  (templates that scripts clone in), and `check` warned about them. Only StarterGui is
  drawn now; the rest are named in a note, and `--all-guis` draws them.
- **3D was far too hazy and the sky grey**: Atmosphere fog is about 4x thinner for
  light atmospheres, leaves the sky blue overhead, and is capped in automatic views.
- **Scenes were too dark**: `EnvironmentDiffuseScale` (sky light) is applied, and the
  material textures no longer darken parts.
- **A place with ~100 lights took 20 s a frame**: the 16 most relevant local lights
  are drawn and a note counts the rest (6 s for the template).

### Added

- **MaterialVariants** draw with their own ColorMap image (`rhr fetch` caches it),
  tinted and tiled like Roblox's.
- **Placeholder MeshParts** (mesh not cached, which is most of them: Roblox serves
  meshes only to signed-in accounts) are outlined boxes coloured from their
  SurfaceAppearance, casting no shadow, instead of white blocks.

## 0.2.0 (alpha)

### Added

- **Material textures.** Brick, Wood, WoodPlanks, Grass, Cobblestone, Slate, Concrete
  and 30 more materials now have look-alike textures in 3D. They are public-domain
  (CC0) materials from ambientCG, tinted by each part's colour the way Roblox tints
  its own and tiled at a fixed size in studs. `--flat-materials` turns them off.
  Roblox's own material images are not redistributable, so these read as the right
  material rather than Roblox's exact pattern.
- **`rhr fetch <file>`** downloads the images and meshes a model uses into the local
  cache, and names any it could not get (Roblox serves some meshes only to signed-in
  accounts). It replaces `scripts/fetch_assets.py` and `scripts/fetch_meshes.py`,
  which only existed in a git checkout.

## 0.1.0 (alpha)

The first public release.

### What's in it

- **Screen UI:** `render` (PNG), `layout` (every element's rectangle, `--rich` for
  what each element is made of), `check` (common mistakes as findings), `hitmap`
  (clickable regions and what is on top). RHR does its own UI layout. It matches
  rectangles that Studio recorded within 2 px on every test place: lists, grids,
  tables, flex, UIScale, constraints, auto-size, scrolling. Text is sized the way
  Roblox sizes it (`TextSize` is the line height).
- **3D:** `scene` (PNG, with standard views, `--focus` and free cameras),
  `scene-dump` (part geometry as JSON) and `preview` (world, in-world UI and screen UI
  in one image). BillboardGui and SurfaceGui use the same UI engine as screen UI.
  Part geometry matches Studio; lighting and materials are approximations.
- **Inputs:** `.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx` and Rojo projects.
- **Never silently wrong:** each instance has a stable id and a unique path
  (`Card[1]`, `Card[2]`). Approximated or unsupported features are reported in the
  output. Every JSON document names its schema version.
- **Setup:** `pip install`, then `rhr setup` downloads Lune, Rojo and Chromium, and
  `rhr doctor` checks them. Runs on Windows, macOS and Linux.
- **Agents:** a usage guide (`docs/AGENTS.md`) and an MCP server (`rhr-mcp`).
- **Examples:** `examples/shop.rbxmx` and `examples/tower.rbxmx`.

### Experimental

Materials, lights, shadows, Sky, Atmosphere, Decals and Textures, MeshParts (from a
local cache), Beams, Trails and ParticleEmitters. They are rough approximations and
labelled as experimental in the output.

### Known limits

See [`docs/known-approximations.md`](docs/known-approximations.md). The main ones:
no Terrain or union geometry, no material textures, images and meshes only from a
local cache, and no scripts, physics or animation.
