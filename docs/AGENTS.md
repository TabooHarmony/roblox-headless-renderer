# Using RHR from an agent

RHR lets you check Roblox UI and 3D builds without driving Studio: point a command at a
`.rbxm` / `.rbxmx` / `.rbxl` / `.rbxlx` file or a Rojo project and read back a PNG
and JSON. This page is the working guide: which command answers which question,
the edit loop, and how to read the output without being misled.

## Which command

| You want to know | Run | Read |
| --- | --- | --- |
| What the UI looks like | `rhr render <file> --out ui.png` | the PNG |
| Where every UI element is | `rhr layout <file>` | `rects[path]` = `{x, y, w, h}` in pixels |
| What each element is made of, and how its text laid out | `rhr layout <file> --rich` | `nodes[]`: class, rect, zIndex, colours, `text.drawnSize`, `text.lines`, `text.bounds` |
| Whether the UI has obvious mistakes | `rhr check <file>` | `findings[]`; exit code 1 if any is an error |
| What is clickable, and what is on top where things overlap | `rhr hitmap <file>` | `nodes[]` (interactive elements), `hitTests[]` (topmost target at each element's centre) |
| What a 3D build looks like | `rhr scene <file> --view iso --out build.png` | the PNG, plus the `notes` line on stderr |
| Where every part is, and what was approximated | `rhr scene-dump <file>` | `parts[]`, `bounds`, `fallbacks`, `unsupportedVisualClasses`, `experimental` |
| World, in-world UI and screen UI together | `rhr preview <file> --view iso --out frame.png` | the PNG |
| Whether an edit changed geometry or only colours | `rhr compare before.png after.png --json` | `changed_pct`, `silhouette.iou` |

Every JSON document has a `schema` field (`rhr.layout/1`, `rhr.check/1`, ...). Check
it: a different version means the shape changed.

## The loop

1. Edit the model (or the Rojo project).
2. `rhr check` it. Fix error findings first; they are real mistakes (zero-size grid
   cells, unreadable text, text that cannot fit).
3. `rhr layout` it and compare the rects you care about with what you intended,
   numerically. This is cheaper and more exact than reading pixels.
4. `rhr render` (UI) or `rhr scene` / `rhr preview` (3D) and look at the picture.
5. After the next edit, `rhr compare` the two PNGs to confirm only what you meant to
   change moved.

The first 3D render starts a warm Chromium worker; later renders reuse its loaded
page and take well under a second inside RHR on a machine with a GPU. It stops by
itself after 10 idle minutes. Through `rhr-mcp`, every tool call also skips starting
Python. `RHR_PROFILE=1` prints where a command's time went.

## Reading paths

A path is the instance's names from the root, joined with `/`:
`StarterGui/Shop/Main/BuyButton`. Siblings that share a name are all numbered in
child order: `Card[1]`, `Card[2]`. A bare `Card` where there are several is an
error, not a guess. Use the exact path from RHR's own output when you pass one back
(`--focus`).

## How far to trust the output

RHR's goal is a useful preview, not a pixel-exact copy of Studio. What has been
measured against Studio (tests/studio/):

- **UI rects** (`rhr layout`, and therefore the render and the hit map) match Studio
  within 2 px on every fixture, including a complete game UI and a stress test of
  flex/grid/table layouts, UIScale, scrolling and auto-sized containers.
- **Text**: sizes and line breaks follow Roblox's rules; text widths are within a
  few percent. A line that only just overflows its box can wrap differently.
- **3D part positions, sizes and rotations** (`rhr scene-dump`) match Studio exactly.
- **3D pictures** are approximations: lighting, fog and shadows are fitted to Studio screenshots and look
  plausible, not identical.

What RHR tells you it did not do exactly:

- `scene` / `preview` print a `notes` line: geometry fallbacks (meshes drawn as boxes),
  unsupported visual classes, missing assets and **experimental** features (Beams,
  Trails, particles, Atmosphere, lights, decals).
  Treat experimental output as a rough sketch.
- `scene-dump` lists the same under `fallbacks`, `unsupportedVisualClasses` and
  `experimental`.
- RHR expects Roblox Studio installed and signed in on the machine. `render`, `scene`
  and `preview` download what the file uses and the cache lacks (images, meshes,
  unions, Roblox's material textures) as that Studio user before drawing; the first
  render of a big place can take a minute, later ones reuse the cache. The login is
  handled by Lune and sent only to Roblox. `--offline` skips downloading. Without
  Studio, stderr says the preview will look less like Roblox (thumbnails, box
  meshes, look-alike materials).
- Effects (particles, Beams, Trails) are one still frame: a `note` says how many
  particles were drawn and at which moment of the effect. Effects a script plays are
  played from their `EmitCount` / `EmitDelay` / `EmitDuration` attributes; an emitter
  a script plays without them is named, not drawn. Judge presence, place, size,
  colour and glow; not motion or exact particle positions. `--effect-time T` shows
  another moment, `--focus <path>` frames one effect in a pack of several.
- Terrain is drawn smooth with Roblox's textures; materials meet with a hard edge.
- In a place file, a ScreenGui outside StarterGui (a template in ReplicatedStorage)
  is not drawn or checked; a `note` names it. Pass `--all-guis` to include it.
- Material textures are Roblox's own (look-alikes without Studio). When you only care
  about colours, `--flat-materials` draws plain colours.
- `docs/known-approximations.md` lists every known difference.

What RHR does not do at all: run scripts, physics or animation. A UI that a script
builds or moves at runtime is previewed as saved in the file.

## Setup reminders

- `rhr doctor` says whether everything RHR needs is installed; `rhr setup` downloads
  what is missing (Lune 0.10.5, Rojo 7.7.0, Chromium).
- A standard `--view` frames the build, not the Baseplate: a thin ground slab much
  larger than everything else is left out of the framing (still drawn), and a `note`
  line says so. `--focus <path>` frames exactly what you name.
- Running several commands on an unchanged file reads it once; stderr says
  `ir reused ...` when a command used the earlier conversion.
- Screen UI assumes Roblox's default 58 px top bar. Use `--topbar-height 0` to match
  what Studio shows in edit mode.
- With a local Roblox or Studio install, RHR uses its fonts (stderr says which); without
  one it uses bundled open fonts, and a few proprietary faces fall back to look-alikes.
- `rhr-mcp` exposes `scene-dump`, `preview`, `compare` and the browser worker as MCP
  tools, for hosts that prefer tools to shell commands.
