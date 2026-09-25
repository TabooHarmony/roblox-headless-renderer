# What RHR is for

This is the source of truth for the project's direction. If another document
disagrees with it, this one wins.

## The goal

RHR is a command-line tool that lets an AI agent **see** the Roblox UI and 3D builds
it is making, without driving Roblox Studio. The agent points it at a file and gets a
preview image plus numbers: where things are, how big they are, what overlaps, what
is clickable, and what looks broken.

- **Who it is for:** Roblox developers and their agents. It is meant to be a public
  tool, so it has to install and run on other people's machines, Windows included.
- **What it covers:** UI (ScreenGuis) and 3D builds equally, including one combined
  "whole scene" preview.
- **Accuracy bar:** a *useful preview*. Roughly right is fine. It has to catch
  obvious mistakes and must never be **silently** wrong: anything it cannot draw
  faithfully is reported in its output. Matching Studio pixel for pixel is not a goal.
- **Interface:** the CLI (`rhr`) comes first. The MCP server is a thin wrapper
  over the same commands.
- **Inputs:** `.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx` files, and Rojo projects (built
  with `rojo build`).
- **Studio's role:** RHR assumes the person using it has Roblox Studio installed and
  signed in (anyone making Roblox content does), and uses both by default, with no
  switch to turn on: the install's own files (default sky, surface textures, fonts)
  and the Studio login, to download the meshes, unions and Roblox material textures
  a render needs. Nothing from Roblox is shipped in RHR itself. Without Studio every
  command still works, with stand-ins, and says clearly that the result will look
  less like Roblox. The maintainer also uses Studio to calibrate previews against.

## What it is not

- Not a Roblox engine: it does not run scripts, physics or gameplay.
- Not a Studio companion: there is no live connection to a running Studio. That
  would defeat the point of a headless tool. (Reading the install's files and its
  saved login is not a live connection: Studio does not have to be running.)
- Not a pixel-perfect replica of Studio's renderer.

## Feature status

| Feature | Commands | Status |
| --- | --- | --- |
| UI preview | `render` | Core (layout by RHR's own pass, checked against Studio) |
| UI layout numbers, build checks, clickable regions | `layout`, `check`, `hitmap` | Core |
| 3D preview and camera controls | `scene` | Core (needs reliability work) |
| 3D geometry as JSON | `scene-dump` | Core |
| Combined world + UI preview | `preview` | Core |
| Before/after comparison | `compare` | Core |
| ViewportFrame | inside `render` | Core (slow) |
| BillboardGui / SurfaceGui | inside `scene` / `preview` | Core (drawn by the UI renderer; placement approximated) |
| Roblox materials, default sky, surfaces, unions, smooth terrain | `scene`, `preview` | Core (checked side by side with Studio) |
| Particles, Beams, Trails, Atmosphere, shadows, lights | `particles`, `scene`, `preview` | **Experimental**: rough approximations |
| MCP server | `rhr-mcp` | Thin wrapper |

## Path to v1

1. **One source of truth:** this document, and a README that matches it.
2. **Tests you can trust:** pytest, with CI green on clean Ubuntu and Windows
   runners, not just the development machine.
3. **Installs and runs anywhere:** `pip install` gives an `rhr` command, with clear
   errors when `lune` or Chromium are missing, and Windows support.
4. **Never silently wrong:** stable per-instance IDs instead of name lookups,
   duplicate-name paths disambiguated, the `Model.Scale` behaviour verified in
   Studio, in-world UI drawn with the same renderer as ScreenGuis, and experimental
   and approximated output flagged in the JSON.
5. **Studio spot-check:** a handful of fixtures made in Studio, checked for
   "roughly right" positions and sizes, not pixel identity.
6. **Rojo input and release polish:** Rojo projects, a supported-feature table, a
   usage guide for agents, and versioned JSON output. (Third-party game files were
   removed from the test data on 2026-09-22.)

## Release roadmap (agreed 2026-09-25)

The aim for the release is **fast, cheap and agent-friendly**, not closer and closer
to Studio. Lighting and shadows are "good enough" as of 0.5: when an agent needs
exact visuals, Studio's own MCP is the tool for that.

**In the release:**

1. **VFX as a still frame (done, 2026-09-25).** Particles, Beams and Trails drawn inside `scene` and
   `preview`, frozen at one moment of the effect playing. Most real VFX are played by
   a script (`:Emit()` on disabled emitters); RHR reads the community's `EmitCount` /
   `EmitDelay` / `EmitDuration` attributes and plays them itself, then shows the
   fullest moment. The line between useful and detail work: fix what would make an
   agent edit differently (is the effect there, where, how big, what colour, does it
   glow, is it hidden), not what a still frame cannot show (motion, exact randomness,
   exact brightness). Checked against a local collection of community VFX that stays
   off GitHub:
   - particles inside the 3D scene (hidden by walls), playing from attributes,
     framing that includes effects, emitter rotation, flipbooks, every `Orientation`;
   - measured in Studio and matched: particle size (2 x `Size`), `Squash`,
     `SpreadAngle` axes, Disc `ShapePartial`, Beam and Trail texture direction and
     repeat, Highlight fill and outline, and particle brightness, blending and tone
     (fitted to a 108-particle sweep, 9/255 RMS);
   - side by side with Studio on ten community effects: five match, five close, none
     misleading. Left for after the release: `TextureSpeed`, `LightInfluence`,
     Roblox's built-in `rbxasset://` particle textures, fire saturation in very dense
     effects.
2. **Optimization: lighter, leaner, faster, more dependable** (agreed 2026-09-25).
   Measured on the maintainer's Windows machine before starting: `rhr --version`
   1.4-2.4 s (Python alone starts in 1.1 s there), a 2D UI render 3.4 s, a small 3D
   scene 7.9 s with a fresh Chromium and 5.8 s with the warm worker (2.5 s of it in the
   page, 0.6 s re-checking Lune), two Chromium builds installed (650 MB), 350 MB of
   caches with no limit, an 18-minute test suite. In order:
   - **Measure**: `RHR_PROFILE=1` prints the time of each phase (start-up, file
     conversion, downloads, page load, scene build, frame, screenshot, notes); record
     numbers here and on the three CI machines, so every change shows its gain.
   - **Faster**: the warm worker keeps the page loaded and takes each render as a
     message instead of reloading ~2 MB of script; it starts on the first render and
     stops after some idle minutes; per-render overheads go (the Lune check is
     remembered, heavy modules imported only when needed, the IR read once). A resident
     `rhr serve` process with a thin CLI is decided after measuring. The test suite
     shares one browser and runs in parallel (target: under 5 minutes).
   - **More dependable**: a watchdog on every browser render (fail within ~20 s with
     the page's own error, restart the worker once, retry); stale workers, lock files
     and half-written cache files are cleaned up instead of failing; `rhr doctor`
     checks more; a one-minute smoke test group for every commit.
   - **Lighter**: `rhr setup` installs only Chromium's headless shell; caches get a
     size limit (least recently used first) and `rhr cache`; unused vendored fonts
     and rarely needed libraries leave the default install. Drawing the 2D UI in the
     browser (dropping skia-python) is evaluated and written up, not done, in this
     pass.

   Results (2026-09-25, same Windows machine): inside RHR, a warm small 3D scene
   2.4 s -> 0.72 s (page kept loaded in the worker, Lune lookup 0.6 s -> 10 ms,
   screenshot 0.41 -> 0.20 s), a 4,400-particle effect 4.0 s -> 1.5 s (simulation
   1,160 -> 220 ms), a 2D UI render 0.3 s; the worker starts on the first 3D render and
   stops when idle; MCP tool calls run in one long-lived process (a warm 3D render
   0.8 s per call, from ~4.4 s). Test suite 18 -> ~5 minutes (own cache, own worker);
   `-m smoke` in about a minute. `rhr setup` installs only the headless shell
   (-394 MB); the cache stays under 2 GB (`rhr cache`). Dependability: the worker
   falls back to a fresh page, relaunches a crashed Chromium, and the CLI falls back to
   a one-shot Chromium; cache writes are atomic; `rhr doctor` shows the cache and the
   worker. Decided: no `rhr serve` for the CLI. What is left per command is Python
   starting (1-3 s on this machine: a venv launcher and antivirus, 0.1 s elsewhere),
   which a Python client cannot avoid; the MCP server avoids it. Evaluated, not done:
   drawing the 2D UI in the browser to drop skia-python. It would make UI-only use need
   Chromium (~260 MB) instead of skia (15 MB) and mean re-writing painting that is
   tuned to Studio within 2 px, so skia stays. The vendored fonts all back Roblox font
   families, and numpy is used throughout the UI engine: nothing to trim there.
3. **Release.** Docs brought up to date, a check on a fresh machine, tag and publish.

**Not in this release (not ruled out; picked up after it):**

- Animated VFX in 3D renders (GIFs, timelines). `rhr particles` still gives a
  contact sheet over time.
- Special effects: Clouds, SunRays, depth of field, custom shader tricks. These stay
  reported as not drawn. (Highlight is drawn since the VFX pass.)
- Replacing Chromium. It is the first candidate after the release if speed is still
  the main complaint.
- Further lighting and shadow tuning. Shadows stay on (they cost almost nothing on the
  GPU); `--no-shadows` turns them off.
- Particle positions that match Roblox's random ones exactly.

**Out of scope for good:** running scripts, physics or animation playback (see
"What it is not").

**After the release, roughly in order:** replacing Chromium (if speed is still the
complaint), terrain material blending and decorations, Clouds, SunRays, animated VFX,
the VFX details listed above, other special effects.

## Rules for new work

- A feature is worth adding when it helps an agent's edit → preview → fix loop.
- "Done" means the tests pass in CI on a clean machine, not only on the machine
  where the work was written.
- Anything approximated or skipped is reported in the output, and listed in
  `docs/known-approximations.md`.
