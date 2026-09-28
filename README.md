# roblox-headless-renderer (rhr)

**See Roblox UI and 3D builds from the command line.** Point `rhr` at a `.rbxm`,
`.rbxmx`, `.rbxl` or `.rbxlx` file, or a Rojo project, and get a preview PNG plus
JSON: where everything is, how big it is, what overlaps, what is clickable, and what
looks broken. It is built for AI agents that make Roblox content and need to check
their work. It also works for people who just want a quick look from the command
line or in CI. No GPU or display is needed.

<p align="center">
  <img src="https://raw.githubusercontent.com/TabooHarmony/roblox-headless-renderer/main/docs/images/build.png" width="98%" alt="Roblox's game template rendered by rhr scene: a pastel tower of platforms and stairs with shadows, plants, a floating sphere and cube, under a cloudy sky">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/TabooHarmony/roblox-headless-renderer/main/docs/images/shop.png" width="40%" alt="A shop ScreenGui rendered by rhr ui: item cards in a grid with rarity colours, rounded corners and price buttons">
  <img src="https://raw.githubusercontent.com/TabooHarmony/roblox-headless-renderer/main/docs/images/vfx.png" width="57%" alt="Three glowing shooting stars, orange, green and violet, with wavy tails, rendered by rhr scene from a particle and beam effect">
</p>

<p align="center"><sub>A 3D build (<code>rhr scene</code> on Roblox's game template), a UI (<code>rhr ui examples/shop.rbxmx</code>) and an effect frozen at its fullest moment (<code>rhr scene</code> on Jaxelos's open-source star VFX).</sub></p>

> **Status: v0.7, an early alpha.** The UI layout numbers are solid: they match
> Studio within 2 px on every test place. The pictures are *previews*: close enough
> to spot mistakes, not a copy of Studio's renderer. Anything RHR can't draw
> faithfully, it says so in its output instead of guessing quietly. See
> [what is approximated](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/known-approximations.md). Bug reports with a small
> file attached are very welcome.

## Install

You need Python 3.12 or newer, on Windows, macOS or Linux. With
[uv](https://docs.astral.sh/uv/):

```sh
uvx roblox-headless-renderer ui MyGui.rbxmx --out gui.png   # run it once, nothing to install
uv tool install roblox-headless-renderer                     # or keep `rhr` on PATH
rhr doctor                                                   # what RHR found, and what it will download
```

`pip install roblox-headless-renderer` works too. An agent that runs RHR all day
should use `uv tool install`: `uvx` resolves the package again on every call.

There is no setup step. The first command that needs one of these downloads it once
into RHR's cache (one line on stderr says so):

- **Lune** 0.10.5, which reads XML files (`.rbxmx`, `.rbxlx`) and runs the signed-in
  asset download, and **Rojo** 7.7.0, for Rojo projects only. Copies already on your
  `PATH` are used first. Binary files (`.rbxm`, `.rbxl`, what Studio saves by default)
  RHR reads itself.
- **A browser for 3D.** RHR drives one you already have: Chrome, Edge, Brave or
  Chromium, in that order (`RHR_BROWSER=<path>` picks one). With none installed it
  downloads Chrome for Testing's headless shell (about 100 MB).

`rhr setup` downloads Lune and Rojo ahead of time, `rhr setup --browser` the headless
shell too (CI, offline machines). `--offline` or `RHR_OFFLINE=1` never downloads
anything; `RHR_TOOL_DOWNLOAD=0` and `RHR_BROWSER_DOWNLOAD=0` turn off one kind. On a
bare Linux machine the headless shell also needs system libraries (on Ubuntu:
`libnss3 libatk-bridge2.0-0t64 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1
libxrandr2 libcups2t64 libasound2t64 libpango-1.0-0`).

## Try it

The repository has two example files ([`examples/`](https://github.com/TabooHarmony/roblox-headless-renderer/tree/main/examples/)):

```sh
git clone https://github.com/TabooHarmony/roblox-headless-renderer && cd roblox-headless-renderer
rhr ui     examples/shop.rbxmx --out shop.png         # the UI as a PNG
rhr check  examples/shop.rbxmx                        # obvious mistakes
rhr scene  examples/tower.rbxmx --view iso --out tower.png
```

The shop has one deliberate mistake, and `rhr check` finds it:

```json
{
  "check": "text-wider-than-box",
  "detail": "text estimated 461px wide in a 148px box with TextWrapped off",
  "paths": ["ShopGui/Shop/Items/Item5/ItemName"],
  "severity": "warning"
}
```

## Commands

| Command | What you get |
| --- | --- |
| `rhr ui <file>` | PNG of the screen UI (every ScreenGui, in `DisplayOrder`), including ViewportFrames |
| `rhr layout <file>` | JSON: the on-screen rectangle of every UI element. `--rich` adds class, z-index, colours and how each text laid out |
| `rhr check <file>` | JSON findings for common UI mistakes: text that doesn't fit, zero-size grid cells, invisible content, ambiguous overlaps. Exits 1 on errors |
| `rhr hitmap <file>` | JSON: what is clickable, and which element is on top where things overlap |
| `rhr scene <file>` | PNG of the 3D build. Standard views (`--view iso/front/back/left/right/top`), `--focus <path>`, or your own `--camera` / `--look-at` / `--fov` |
| `rhr scene-dump <file>` | JSON: position, size, bounds and material of every part, plus everything that was approximated |
| `rhr preview <file>` | One PNG with the 3D world, in-world UI (BillboardGui, SurfaceGui) and screen UI together |
| `rhr view <file>` | Opens the 3D world in a local page you can fly around in (drag, wheel, WASD). It stays up to date: when the file or Rojo project changes, the page redraws with the camera where it was. For a person looking at an agent's work; Ctrl+C stops it |
| `rhr icons <files or folders>` | Square icon PNGs (512 px by default) of models on a transparent background, cropped to each model with the same margin: shop and inventory icons for a folder of pets or items, in about a second each. Takes asset ids too |
| `rhr compare a.png b.png` | JSON: how much changed between two renders, to tell a geometry change from a colour change |
| `rhr scene 2810302648` | Any command also takes a Roblox asset id or link (Creator Store, library, catalog) in place of a file: it downloads the model once, with your Studio login, and previews it |
| `rhr ir <file>` | RHR's internal form of the file, for debugging (its shape may change in any release) |
| `rhr fetch <file>` | Download the images, meshes, unions and Roblox material textures a model uses into the local cache, as your Roblox Studio user. `scene` and `preview` do this themselves for whatever they are missing |
| `rhr setup` / `rhr doctor` | Install the external tools / check them |
| `rhr cache` | What the cache holds (`--clear` to empty part of it) |
| `rhr browser status/start/stop` | The warm 3D worker (it starts and stops by itself; this is for checking) |

Every JSON output carries a `schema` name (`rhr.layout/1`, `rhr.check/1`, ...), so a
change in shape is never silent. `ui`, `scene` and `preview` print the PNG's path, or
with `--json` a report (`rhr.render/1`): the path, the camera, and what was
approximated or missing. Exit codes: 0 done, 1 only from `check` (error findings), 2
the command failed. The full interface is in
[`docs/interface-1.0.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/interface-1.0.md). A Rojo project works anywhere a file does: pass the
folder with `default.project.json`, or the `*.project.json` file.

**Effects.** `scene` and `preview` draw ParticleEmitters, Beams and Trails inside the
3D scene as a still frame: hidden by walls, glowing where `LightEmission` says so.
Most VFX are played by a script; RHR runs no scripts, but reads the widely used
`EmitCount` / `EmitDelay` / `EmitDuration` attributes and plays the effect itself,
showing its fullest moment (`--effect-time T` for another, `--no-effects` to leave
them out). Emitters a script plays without those attributes are listed, not guessed.
Highlights (fill and outline) are drawn too. How particles blend and how bright they
look is fitted to measurements in Studio; see
[what is approximated](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/known-approximations.md#effects).

**Experimental** (rough sketches, and labelled as such in the output): local lights,
Decals and Textures, Atmosphere and post effects.

## For agents

Start with [`docs/AGENTS.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/AGENTS.md): which command answers which question,
an edit → check → preview loop, and how far to trust each output. RHR is a command-line
tool only: an agent runs it from its shell, and it costs nothing in the agent's context
until it is run.

`rhr` hands each command to a resident RHR server, started by the first command, which
keeps Python, RHR and the files it read loaded: a command on an unchanged file costs
little more than the work itself. It replaces itself when RHR is upgraded and stops
after 20 idle minutes (`rhr server stop` stops it now; `RHR_SERVER=0` runs each command
in its own process). 3D renders use the GPU (about 8x faster than software rendering;
set `RHR_WEBGL=software` for identical pixels on every machine, as the tests do). The
first 3D render also starts a warm browser worker, which keeps the 3D page loaded;
later renders reuse it and it stops itself after 10 idle minutes
(`RHR_PERSISTENT_BROWSER=0` turns it off). How RHR is built to be fast:
[`docs/performance.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/performance.md).

Measured on a Windows machine with a GPU (`RHR_PROFILE=1` prints the same breakdown
for any command): once the worker is warm, a small 3D scene takes about 0.7 s inside
RHR, a 4,400-particle effect about 1.5 s, and a 2D UI render about 0.3 s. Starting
Python itself adds 0.1-3 s per command depending on the machine. `rhr cache` shows what the cache holds (it stays under 2 GB,
`RHR_CACHE_LIMIT_MB`).

## Good to know

- **Top bar.** Screen UI is laid out below Roblox's 58 px top bar, as in a running
  game. Studio's edit view has none: pass `--topbar-height 0` to match it.
- **Roblox Studio is expected.** RHR is for people making Roblox content, so it
  assumes Roblox Studio is installed and signed in on the machine (it does not have to
  be running), and uses it by default:
  - **Downloads.** Before drawing, `scene` and `preview` download whatever the file
    uses that is not cached yet (meshes, unions, images at full size, and Roblox's
    own material textures), as the user signed in to Studio. Lune reads the login
    Studio saved and sends it only to Roblox's asset delivery, the same request
    Studio makes; RHR never sees, prints, logs or stores it. Anything already cached
    is never downloaded again. `--offline` (or `RHR_OFFLINE=1`) skips the download.
  - **The install's files.** The default sky, Plastic's surface relief and legacy
    surfaces (a Baseplate's studs) come from the Studio install, and RHR uses its fonts.
  - **Without Studio** every command still works: images come as 420 px thumbnails,
    meshes and unions are outlined boxes, materials use public-domain look-alike
    textures, and the sky is a gradient. RHR says so on stderr, because the result
    looks noticeably less like Roblox.
- **Terrain** is drawn smooth, meshed from the place's voxels the way Roblox does it,
  with Roblox's terrain textures (top, side and bottom), blended where materials meet
  as in Studio, and grass blades (drawn still) when the place turns Decoration on.
- **Clouds** (Terrain.Clouds) are drawn as a still layer from Roblox's cloud tile.
  Water waves are not drawn.
- **Unions** are drawn with the exact shape and per-part colours Studio saved for them.
- **Place files.** In a `.rbxl`, only StarterGui's ScreenGuis are drawn; templates
  stored in ReplicatedStorage and elsewhere are named on stderr (`--all-guis` draws
  them).
- **Material textures** are Roblox's own, downloaded by the asset ids Roblox
  publishes in its documentation, tinted by the part's colour the way Roblox does it
  (Brick's mortar keeps its own colour), with their relief, roughness and metalness.
  `MaterialService.Use2022Materials` picks the current or pre-2022 set.
  `--flat-materials` draws plain colours.
- **Fonts.** With a Roblox or Studio install on the machine, RHR uses its fonts.
  Without one it uses bundled open-licence fonts, and a few Roblox-only faces are
  replaced by look-alikes.
- **Not an engine.** Scripts, physics and animation don't run. A UI that a script
  builds or moves at run time is shown as it is saved in the file.
- **Cache.** Everything RHR writes goes to one folder (`%LOCALAPPDATA%\rhr\cache`,
  `~/Library/Caches/rhr` or `~/.cache/rhr`). Set `RHR_CACHE_DIR` to move it.

## Development

```sh
git clone https://github.com/TabooHarmony/roblox-headless-renderer && cd roblox-headless-renderer
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && rhr setup
python -m pytest                                    # -m smoke: a quick check; -m "not browser": no 3D
```

CI runs the suite on Ubuntu, Windows and macOS. [`docs/GOAL.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/GOAL.md) is the
project's direction and scope. `tests/studio/` holds places built in Studio with
Studio's own measurements saved inside; its README explains how to add one.

- `src/rhr/`: the package (file reading, UI layout and drawing, 3D scene, CLI).
- `src/rhr/ui_engine/`: the 2D UI engine, a fork of pinevex-renderer (Apache-2.0);
  [`docs/ui-engine.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/ui-engine.md) and `patches/` say how it differs.
- `src/rhr/vendor/three/`: THREE.js for the 3D preview, bundled, so nothing is loaded
  from a CDN.

## License

Apache License 2.0. Bundled third-party code and fonts are listed in
[`THIRD_PARTY_NOTICES.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/THIRD_PARTY_NOTICES.md). Test fixtures and examples are
made for this repository; no third-party game content is included.

RHR is an independent project, not affiliated with or endorsed by Roblox
Corporation. Roblox is a trademark of Roblox Corporation.
