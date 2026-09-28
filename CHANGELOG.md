# Changelog

## Unreleased (1.0)

### When upgrading

- **`rhr check` severities:** `duplicate-zindex`, `invisible-content`,
  `child-outside-clip` and `max-visible-graphemes` are now `info`, not printed by
  default (`--min-severity info`). `text-wider-than-box` no longer fires on TextScaled
  or wrapped labels; wrapped text that does not fit is `text-taller-than-box`.
- **Nothing to draw is an error.** `ui`, `layout`, `check` and `hitmap` on a file
  with no UI to draw exit 2 with the reason and what would draw something (a closed
  screen to `--show`, templates stored outside StarterGui, a Rojo project that maps
  only code: use the place file), instead of exiting 0 with a blank PNG or an empty
  document.
- **`rhr` runs commands in a resident server.** The first command starts it in the
  background; later ones hand it their command line and get the output back, with
  Python, RHR and the converted files already loaded. Output, exit codes and files
  are the same as before. It replaces itself when RHR is upgraded, stops after 20 idle
  minutes (`RHR_SERVER_IDLE_S`) or with `rhr server stop`; `RHR_SERVER=0` runs every
  command in its own process as before.
- **JSON output is compact**: the same documents (same keys, sorted, same values),
  without indentation, and non-ASCII text written as UTF-8 rather than escaped. Parse
  it as JSON; do not rely on its whitespace.
- The MCP server (`rhr-mcp`, the `mcp` extra) is gone: RHR is a command-line tool only.
  An agent runs `rhr` from its shell, which costs nothing in its context until it is
  run; docs/AGENTS.md is its guide.
- The interface is settled for 1.0 (docs/interface-1.0.md):
  - `rhr render` is now **`rhr ui`**, and its default output is `<stem>-ui.png`.
  - `ui`, `scene` and `preview` take **`--json`**: a report (`rhr.render/1`) with the
    PNG's path and size, the camera used, what was approximated or missing, and the
    notes that were only on stderr before.
  - **`rhr compare`** prints JSON by default, with camelCase keys and `before`/`after`
    in place of `ref`/`out`: `rhr.compare/2`. Its summary for people is on stderr.
  - Removed: `rhr particles` (the contact sheet; `--effect-time` shows other moments),
    `--ir PATH` (use `rhr ir`), and the leftover `--shadows`, `--coverage`, `--time`
    (use `--effect-time`) and `fetch --use-studio-login`.
  - `--no-effects` leaves out Beams and Trails too, not only particles.
  - A command that fails exits 2; 1 now only ever means `check` found errors.
  - `--texture-dir` and `--mesh-dir` are test hooks, hidden from `--help`.
- **Playwright is gone.** RHR drives the browser itself over the DevTools protocol,
  with a browser you already have: Chrome, Edge, Brave or Chromium. With none, the
  first 3D render downloads Chrome for Testing's headless shell once (about 100 MB,
  the same build as before, so pictures are unchanged); `rhr setup --browser` does
  that ahead of time and `RHR_BROWSER_DOWNLOAD=0` forbids it. `RHR_CHROME` is now
  **`RHR_BROWSER`** (the old name still works in this release). The old Playwright
  Chromium in `ms-playwright` is no longer used and can be deleted.
- The UI engine is RHR's own code (`rhr.ui_engine`, a fork of pinevex-renderer):
  nothing changes in what it draws. RHR no longer adds the engine's folders to
  `sys.path`, so the top-level modules `ui_engine`, `tree_to_pinevexobject`,
  `product_output` and `rbxm_parser_component` are gone. The calibration switches
  `RHR_TABLE_Y_SCALE*` / `RHR_TABLE_NODRAW_*` are removed.
- The `--json` report and `rhr browser status` name the browser used (`browser`:
  name, version, path); `rhr doctor` names the browser it will use and why any other
  was skipped.

- **Install from PyPI**: `uvx roblox-headless-renderer ...` runs it once, `uv tool
  install roblox-headless-renderer` (or `pip install`) puts `rhr` on `PATH`. The
  package also has a `roblox-headless-renderer` command, the same as `rhr`.
- **No setup step**: Lune and Rojo download themselves the first time a command needs
  them (a line on stderr says so), like the browser. `rhr setup` still does it ahead
  of time. `RHR_TOOL_DOWNLOAD=0` turns that off; `--offline` / `RHR_OFFLINE=1` now
  turns off every download (tools, the browser, font names), not only assets. A
  missing tool with downloads off is an error that says to run `rhr setup`.

### Changes

- **`rhr check` finds what players see, and less noise.** Text checks read what the
  engine laid out instead of measuring again with another font (half of the old
  `text-wider-than-box` warnings on real games were wrong: TextScaled labels, other
  fonts). New checks: `text-taller-than-box` (wrapped text spilling out),
  `off-screen` and `partly-off-screen`, `small-target`, `low-contrast`. A third
  severity, `info`, for patterns that are often intended (`duplicate-zindex`,
  `invisible-content`, `child-outside-clip`, `max-visible-graphemes`), left out
  unless `--min-severity info`. `--ignore <check>`, `--baseline old.json` (only
  what an edit added) and an `RhrIgnore` attribute in the file leave findings out.
  Text in an uploaded font RHR cannot load, and UI collapsed to nothing (a menu a
  tween grows open), is not judged. On four real games: 101 warnings on one became 1;
  the review's probe UI went from 0 of 6 mistakes found (and 2 fine labels flagged)
  to 5 of 6, with the sixth (a missing image) next.
- **Missing images are reported.** `rhr ui --json` lists the images it could not get
  in `missingAssets` (path, class, uri, and why: refused, unavailable, offline), and
  says so on stderr; `rhr check` reports `image-missing` for images Roblox refused the
  last time RHR asked. A second kind of Roblox "image unavailable" placeholder (a
  question mark on two cards) was drawn as if it were the image; it is recognised now.
- **Screens code opens: `--show <path>` and `--only <path>`** on `ui`, `layout`,
  `check`, `hitmap` and `preview`. A screen saved closed (`ScreenGui.Enabled` or
  `Visible` false, as games save the screens their code opens) is drawn with
  `--show` (repeatable), or alone with `--only`, every other screen closed. A path
  into a place's storage (a template in ReplicatedStorage) works too.
- **UI that code builds: stories (experimental).** `ui`, `layout`, `check` and
  `hitmap` take a story file (`*.story.luau`, in the UI Labs, Hoarcekat or
  Flipbook forms). RHR builds the story's Rojo project, runs the story in Lune with a
  copy of the Roblox side UI code touches (instances, events, services, `require` by
  instance) and draws what it built, like a file: React-lua, Fusion and plain Luau
  alike, nothing library-specific. Code that reads the screen size gets `--viewport`;
  tweens end at their goal; controls take their defaults. A story that fails exits 2
  with the error pointed at the project's files and lines. A story runs the
  project's code: do not run untrusted ones outside a sandbox. About 0.9 s warm.
- **The cache keeps to its limit.** Converting an edited file now drops that file's
  earlier conversion (a place's is about 25 times the file, and every edit made a new
  one: 10 GB in a day of work on big places, against a 2 GB limit). The limit is
  checked every hour instead of once a day, and right after writing a big conversion.
- **The resident server lets go of big files.** After 3 idle minutes it keeps only
  what fits in `RHR_SERVER_MEMORY_MB` (default 512): a small UI stays warm, a big
  place's conversion is read again when next asked for. On a 116k-part place the
  server went from 916 MB to 392 MB.
- **Hardening.** The headless browser keeps Chromium's sandbox (it decodes images
  and meshes from the internet); only Linux as root turns it off, as Chromium
  requires, and `RHR_BROWSER_SANDBOX=0` where it fails for another reason. RHR's
  local servers (renders, `rhr view`) answer only requests addressed to this machine
  and share data only with local pages, so a web page cannot read a scene through
  them. A binary file whose chunks claim impossible sizes is refused before anything
  is allocated. A story cannot use `getfenv`/`setfenv` (they led to Lune's own
  `require`).
- **`rhr inspect <file>`**: what a file holds (classes, scripts with their lines, the
  asset ids it uses), and findings for script code worth a look before inserting a
  model: `require(<id>)` (the classic backdoor: code loaded from Roblox at run time),
  `getfenv`/`setfenv`, `loadstring`, obfuscated code, webhooks and HTTP posts,
  `InsertService:LoadAsset`, purchase prompts, teleports, virus-named scripts. It
  reads the scripts and never runs them; JSON `rhr.inspect/1`. A 180k-instance place
  takes about 4 s, a model a few milliseconds.
- **Assets without Studio: `RHR_ROBLOX_API_KEY`.** An Open Cloud API key (a user key
  with `legacy-asset:manage`) downloads what the Studio login would, for cloud agents
  and CI; it is asked for what the login could not get, before asking without either.
  `rhr doctor` says whether one is set.
- **`rhr icons`**: square icon PNGs of models on a transparent background, cropped to
  the model with the same margin on every icon (`--size`, `--margin`, `--view`,
  `--background`). Give it files, folders or asset ids; one page stays loaded for the
  batch, so after the first each icon costs about a second.
- **`rhr view <file>`**: the 3D world in a local page you move around in: drag to
  orbit, right-drag to pan, wheel to zoom, WASD/QE to fly, double-click to aim, F to
  frame everything; pinch and two-finger drag on a touch screen. It keeps up with the
  source: when the file (or any file of a Rojo project) changes, the page redraws in
  about a second with the camera where it was, so an agent's edits appear while you
  look. Served on this machine only (127.0.0.1); the address is printed on stdout.
- **Preview any Roblox asset by id or link**: `rhr scene 2810302648`, or a Creator
  Store, library, catalog or game link, anywhere a file goes. RHR downloads the model
  with the Studio login into its cache (the `models` area of `rhr cache`) and names
  it on stderr (`asset  2810302648  "a CAR" by CS_GO2321`). Used again without asking
  Roblox for 10 minutes, then downloaded again only when it changed. Meshes, images
  and others' places are refused with what they are and why.
- **Assets download about 15x faster.** RHR asks Roblox where up to 256 assets are in
  one request, then downloads the files in parallel, instead of one asset at a time
  (204 assets from three Creator Store models: 50.8 s -> 3.4 s; the first render of a
  new car model: 55 s of downloads -> 2.2 s). The files are the same, byte for byte.
  Without a Studio login RHR now asks for everything Roblox serves without one (some
  meshes, images and material textures), not only meshes. Moderated images no longer
  cost seconds of polling on every render, and an asset refused for lack of a login
  is asked again as soon as there is one (it used to wait a day after
  `rhr fetch --no-studio-login`).
- **Much faster in an agent's loop** (numbers in docs/performance.md, measured one
  process per command as an agent runs them). The main changes:
  - the resident server (above): no Python start-up, imports or re-reading of the
    converted file per command;
  - UI commands (`ui`, `layout`, `check`, `hitmap`) read only a file's UI, and
    `layout`/`check` no longer paint a picture to measure it: on a 40k-instance model
    `layout` went from a minute to under a second;
  - `scene` and `preview` on a place read only its world, not its storage;
  - 3D renders no longer list the whole asset cache, re-check every asset, recompile
    shaders or rebuild the sky each time;
  - XML files convert in a Lune process that stays running (4x faster per edit).
- **XML files with an XML declaration** (`<?xml version="1.0"?>` before `<roblox>`)
  now read; Lune refused them ("Unknown document format").
- **Big places are fast.** RHR reads binary files (`.rbxm`, `.rbxl`) itself instead of
  asking Lune for every property of every instance: the same result (checked
  identical on 63 real files and every fixture), 10-60x faster. On a 22k-part map a
  render after an edit went from 124 s to 26 s, and a second render from 34 s to 7 s;
  on a 116k-part place from 668 s to 36 s and from 75 s to 8 s. A render now reads its
  converted file once instead of six times, and a place's 3D view reads only what it
  draws (its stored maps are left in the cache, not re-read each time). Binary files
  no longer need Lune at all. `RHR_READER=lune` reads them with Lune as before.
- **Places draw their world, not their storage.** In a place file, `scene` and
  `preview` no longer draw (or download, or count) the models kept in ServerStorage,
  ReplicatedStorage, StarterPack and the like: on a real game, 110k stored parts
  (every map, all at the same spot) had framed the view on fog. A note counts them
  and suggests `--focus <path>`, which draws one. Model files are unchanged.
- **Framing ignores far strays.** A standard view no longer backs off to include a
  few parts far from everything else (a plugin's rig 126k studs out); a note names
  them.
- **Big places convert with less memory.** On a 116k-part place the 3D conversion
  peaked at 3.9 GB instead of 5.5 GB (7.0 -> 5.7 GB for UI commands), without the
  whole-place XML pass, with identical output. Reading
  terrain and unions from binary files is 40x faster, and the scene dump 25%.
- `rhr doctor` no longer counts a missing Lune as a problem when it can be
  downloaded; it says it will be.
- Downloaded tools are written beside their final name and renamed, so an interrupted
  download never leaves a broken `lune` that RHR would then try to run.
- Cold 3D renders are about 1.7 s faster (no Node driver to start); warm renders are
  unchanged. Installing RHR no longer pulls in Playwright (104 MB).
- A browser never outlives RHR: on Windows it runs in a job object that ends it with
  the process that started it, even on a crash; on Linux it gets a parent-death
  signal. Profiles left by a killed RHR are removed on the next launch.

## 0.7.0 (alpha)

Coverage of common content: characters, terrain, the sky, UI edge cases and the last
VFX properties, each checked side by side with Studio (details in
docs/known-approximations.md).

### When upgrading

- Pictures of the same file can change where RHR now follows Studio: dressed
  characters, blended terrain and grass, clouds, the sun and sun rays in the sky,
  unclipped overflowing text, slightly wider small text, Beam textures (they were
  upside down), and effects with `LightInfluence` above 0 in dim or night lighting
  (they go dark, as in Studio).
- Trails from saved files are drawn: files keep a part's velocity as `Velocity`,
  which RHR never read, so every such trail was skipped before.
- `--effect-time` also sets how far Beam textures have scrolled (`TextureSpeed`).
- Clouds and `SunRaysEffect` are no longer listed as unsupported when drawn; part
  surfaces (studs, inlets) show on Plastic only.
- No command, flag or JSON schema changed.

### Characters

- Shirt, Pants and ShirtGraphic painted onto the body with Roblox's own layouts from
  the Studio install (R6 atlas on the install's body meshes or CharacterMesh
  packages, R15 per body part); T-shirts over shirts; BodyColors.
- Layered clothing fitted to the body through its cages and stacked in `Order`; R6
  and R15 body packages; heads with their own image show no face decal.
- `SpecialMesh` heads use the install's head mesh at Studio's measured size; mesh
  textures use the mesh's own UVs; decals on meshes are projected onto the surface;
  old version 1 meshes are textured the right way up.
- Fixed: a Block part with a SpecialMesh and non-smooth surfaces (every R6 head) was
  not drawn.

### Terrain and sky

- Terrain materials blend where they meet (the earlier material in Roblox's order
  reaches half a voxel into the other, measured on nine pairs) and fade from top to
  side texture by slope; one projection per face, so curved terrain no longer smears.
- Grass decoration (`Terrain.Decoration`, `GrassLength`) grows on Grass tops, fitted
  to Studio side and top views.
- `Terrain.Clouds` drawn as a still layer in the sky from Roblox's own cloud tile,
  cover, density and shading fitted to Studio.
- The sun drawn in the sky (`SunTextureId` or the default), `SunAngularSize` across;
  `SunRaysEffect` drawn and fitted to Studio.
- Fixed: the sky's top face was a quarter turn off; unknown voxel material ids no
  longer fail the whole terrain.

### UI

- `UITableLayout` `FillEmptySpaceColumns`/`Rows` and `UIPageLayout` spacing match
  Studio; overflowing text is not clipped to its label; glyph advances are rounded up
  as Roblox does (text width error 5.6% -> 1.3%). Checked on a new Studio fixture
  (tests/studio/ui_edge_cases, 52/52 rectangles).

### VFX

- `LightInfluence` on particles, Beams and Trails, measured under 15 lightings
  (1.7/255 RMS): the effect's `Brightness` blends toward the scene's light (ambient
  plus sun, the moon at night) by the square root of `LightInfluence`.
- Beam `TextureSpeed`: the texture scrolls toward `Attachment1` with the effect time.
- Beam textures the right way up (the image's top at `Attachment0`); `Wrap` Trail
  tiles start at the attachments.
- Roblox's built-in particle textures, `.dds` included, checked side by side with
  Studio: all drawn, fire's darker.

### Other

- Helper processes (Lune, Rojo, the MCP and browser workers) start without a console
  window on Windows.
- Fixed: without a Studio install, a file with Lighting and particles showed only the
  sky and the particles (parts, Beams and Trails vanished behind the flat sky).
- Fixed: on Python 3.12, `--camera` and `--look-at` rejected a vector whose first
  coordinate is negative (`--camera -10,5,3`).

## 0.6.0 (alpha)

0.5.0 was never released on its own; its changes (below) ship in this release too.

### When upgrading

- `scene` and `preview` draw particles by default (`--no-effects` leaves them out);
  `preview --burst` is gone and `--time` is now `--effect-time` (the old name works).
- The first 3D render starts a warm browser worker, which stops after 10 idle minutes
  (`RHR_PERSISTENT_BROWSER=0` turns it off). Its session files moved into the cache.
- `rhr setup` installs only Chromium's headless shell. An existing full Chromium from
  Playwright is no longer needed and can be deleted.
- A model without a Camera is framed as a whole instead of seen from a fixed spot.
- Particles, Beams, Trails and Highlights are no longer listed as `experimental` in
  `scene-dump`: they were checked against Studio and report their own notes.
- A particle texture that cannot be loaded draws nothing (it drew a soft dot).

### Faster, lighter, more dependable

- **Warm 3D renders are 3x faster**: the browser worker keeps the 3D page loaded
  between renders (scripts, compiled shaders, decoded images and meshes stay), starts
  on the first 3D render and stops after 10 idle minutes. Small scene: 2.4 s -> 0.7 s
  inside RHR. Screenshots use Chromium's fast PNG encoder; a Rokit Lune shim is no
  longer started on every command when `rhr setup`'s pinned Lune is there.
- **Heavy effects simulate 5x faster** (in-place stepping, a cheaper search for the
  fullest moment).
- **`rhr-mcp` runs every command in one long-lived process**: no Python start-up per
  tool call (0.8 s for a warm 3D render).
- **`RHR_PROFILE=1`** prints where a command's time goes, down to the page's steps.
- **`rhr setup` installs only Chromium's headless shell** (about 260 MB, not 650).
- **`rhr cache`** shows and clears the cache, which now stays under 2 GB
  (`RHR_CACHE_LIMIT_MB`, least recently used first).
- **Dependability**: a worker that fails falls back to a fresh page, a crashed
  Chromium is relaunched, the CLI falls back to a one-shot Chromium, a worker running
  older code is replaced, cache files are written atomically, and `rhr doctor` shows
  the cache and the worker.
- **Tests**: their own empty cache and worker (results no longer depend on what the
  machine downloaded), 18 -> ~5 minutes, and `pytest -m smoke` for a quick check.

### VFX in the 3D scene

- **Particles are drawn inside the scene** by `scene` and `preview`, by default: walls
  hide them, glass shows them, fog fades them, and they sort with other transparent
  things. They used to be a separate layer pasted on top, and only with `--time`.
- **Effects are played from their attributes.** Most VFX keep their emitters disabled
  for a script to `:Emit()`; RHR reads the community's `EmitCount` / `EmitDelay` /
  `EmitDuration` attributes and plays the effect itself, then shows its fullest moment
  (`--effect-time T` for another, `--no-effects` to leave particles out, `--seed` for
  other randomness). Emitters a script plays without those attributes are listed.
- **Glow**: `LightEmission` blends between ordinary transparency and added light, as in
  Roblox, for particles, Beams and Trails. `ZOffset` moves particles toward the camera.
- **Emitters follow their part's or attachment's rotation**, and `SpreadAngle` turns
  the direction by that many degrees.
- **A model without a Camera is framed as a whole**, particles included, instead of
  being seen from a fixed spot near the origin.

### Checked against Studio

Ten community effects, frozen at the same moment from the same camera in Studio and
RHR, led to these fixes: particles are 2 x `Size` across (they were half size);
negative `Squash` widens by 1 + |s| (it was up to 20x); emitters without a texture
and velocity-aligned particles with no velocity draw nothing; transparency is clamped
to 0..1; framing ignores invisible holder parts and stray far particles; a Sky or
Atmosphere outside Lighting no longer applies. Known difference: negative
`LightEmission` with a very high `Brightness` looks more solid than in Studio.

### Second pass against Studio

- **Particle brightness and blending fitted to Studio** (a measured sweep; 9/255 RMS):
  soft per-channel cap, alpha^1.45, negative `LightEmission` darkens behind, and
  Studio's tone curve, which turns very bright colours toward white. Megumin's glow is
  a translucent shell now, not solid red.
- **Beam and Trail textures run along their length**, repeating `TextureLength` times
  in Stretch mode (they were sideways and stretched once): Jaxelos's tails wave.
- **Highlight** is drawn: fill and outline, in Studio's order (tested: AlwaysOnTop shows through a wall, Occluded does not).
- **SpreadAngle axes** follow Roblox (Megumin's mushroom cloud spreads flat, not up).
- **Disc ShapePartial** emits from the rim inward (ColorOrb's smoke is a ring).
- **Roblox's "image unavailable" thumbnail** is no longer cached as a texture (it drew
  white squares); a particle texture that cannot be loaded draws nothing, as in Studio.
- A page that never gets ready now says why (the browser's own error) instead of only
  timing out.

### Fixed

- A fully transparent part hid whatever was drawn after it (effects usually sit in
  one); it is no longer drawn.
- A mesh with a vertex that is not a number made the framed camera invalid and the
  render blank.
- `preview --time` and `--burst` are replaced by `--effect-time`; `--time` still works.

## 0.5.0 (alpha, released as part of 0.6.0)

### Lighting parity (fitted to Studio)

- **Lighting in modern places is fitted to Studio screenshots** of a calibration rig
  under a Roblox template's lighting: sun with shadows, sky light taken from the sky
  itself (shadows and shaded faces get Roblox's sky-blue colour instead of flat
  grey), **sky visibility on a 4-stud voxel grid** as Roblox computes it (under
  overhangs, behind pillars and inside rooms is darker), and a tone curve. Average
  difference on the rig: 8/255 per channel, from 22. Places with
  EnvironmentDiffuseScale 0 keep the earlier model.
- **Shadows are on by default**, as in Studio (`--no-shadows` to turn them off), in
  two cascades out to 500 studs (three.js's SunLight add-on), so a close view is
  shadowed as far as it reaches. They cost a few percent of render time on the GPU.
- **Atmosphere measured in Studio**: the fade curve at Density 0.2 / 0.375 / 0.6, and
  Haze veiling the sky (below the horizon first, the whole sky at 5). Wide views used
  to wash out to pale blue.
- **Neon**: glows in its own colour, wider (Studio at high quality).

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
- **Neon glows** the way Roblox does it at high quality (checked in Studio): drawn
  about 3x brighter than its colour, and what passes white glows, blurred at quarter
  resolution. `BloomEffect` and `ColorCorrectionEffect` are drawn (experimental);
  SunRays, DepthOfField, Blur and Clouds are reported as not drawn.
- **Every mesh format**, including versions 6 and 7 (Draco-compressed; RHR ships
  Google's decoder). Many recently uploaded meshes are version 7 and were drawn as
  boxes. Only the most detailed level of detail is drawn now (all levels used to be
  drawn on top of each other).
- **3D renders use the GPU**: about 8x faster (a textured scene: 2 s instead of 17 s).
  `RHR_WEBGL=software` keeps software rendering, as tests and CI do.

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
