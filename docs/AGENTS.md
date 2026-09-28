# Using RHR from an agent

RHR lets you see Roblox UI and 3D builds without Studio: point a command at a file
(`.rbxm` `.rbxmx` `.rbxl` `.rbxlx`), a Rojo project, a UI story (`*.story.luau`) or a
Roblox asset id or link, and read back small JSON and, when you need to look, a PNG.
This page is the working guide: the loops for the usual setups, which command answers
which question, and how far to trust the output.

## First, where does the UI live?

| Your project | Point RHR at |
| --- | --- |
| UI saved as files in a Rojo repo (`.rbxmx`, `.model.json`) | the project folder, or the file |
| UI built by code (React-lua, Fusion, Roact, Vide, plain Luau) | a story per screen: `src/Shop.story.luau` (UI Labs, Hoarcekat or Flipbook form) |
| Code in Rojo, UI and maps saved in Studio (`$ignoreUnknownInstances`) | the place file (`Game.rbxl`) or its place id, not the project: the project holds only code, and RHR says so |
| A loose model, a Creator Store item, a commission | the file, or the asset id / link |

Screens a game opens by code are saved closed (`ScreenGui.Enabled = false`,
`Frame.Visible = false`) and are not drawn by default. `--only StarterGui/Shop` draws
one alone (best for checking a screen); `--show StarterGui/Shop` opens it on top of
what is open. A command with nothing to draw exits 2 and says which screens are closed
and how to open them.

## The loop

1. Edit.
2. `rhr check <target>` (`--only <screen>` for one screen). Exit 1 means an error
   finding: fix it. Then the warnings: text spilling out of its box, buttons off
   screen, too small, blocked or unreadable, images that could not be had. Before
   the first edit, `rhr check <target> --out before.json`; after each edit,
   `rhr check <target> --baseline before.json` shows only what the edit added.
3. `rhr layout <target> --path <screen>` and compare the rects you care about with
   what you meant, as numbers. Cheaper and more exact than reading pixels.
4. Look when numbers are not enough: `rhr ui <target> --only <screen> --fit
   --max-size 800 --out shot.png` (a small picture of just that screen). Add
   `--annotate --json` to number the buttons and get the numbers' paths.
5. Before calling it done: `rhr check <target> --devices all` (phone, tablet,
   console...: notches, touch controls, 44 px touch targets).

For 3D: `rhr scene <target> --view iso --max-size 800 --out build.png --json`, and
`rhr scene-dump <target>` for what a place holds. `rhr compare before.png after.png`
tells a geometry change from a colour change.

Commands are cheap to repeat: `rhr` hands them to a resident server that keeps the
files it read loaded, and one after an edit reads only what changed. Prefer the
cheapest command that answers the question (`check`, `layout`, `hitmap` before a
picture; a cropped picture before a full one).

## Which command

| You want to know | Run | Read |
| --- | --- | --- |
| Whether the UI has mistakes | `rhr check <file>` | `findings[]`: `check`, `severity`, `paths`, `detail`; exit 1 if any is an error |
| ... that an edit added | `rhr check <file> --baseline before.json` | only the new findings |
| ... on phones and tablets | `rhr check <file> --devices all` | findings with `devices` |
| Where every UI element is | `rhr layout <file>` (`--path <screen>`) | `rects[path]` = `{x, y, w, h}` in pixels |
| What each element is made of, how its text laid out | `rhr layout <file> --rich --path <screen>` | `nodes[]`: class, rect, zIndex, colours, `text.drawnSize`, `text.lines`, `text.bounds` in `text.box` |
| What a screen looks like | `rhr ui <file> --only <screen> --fit --out ui.png --json` | the PNG; `missingAssets` (images that draw as nothing, and why) |
| One element, small | `rhr ui <file> --crop <path> --max-size 400 --out el.png` | the PNG |
| What it looks like on a phone | `rhr ui <file> --device phone --out phone.png` | the PNG at 852x393 with the notch insets |
| What a player would click at a pixel | `rhr hitmap <file> --at X,Y` | `hitTests[0].target`, every interactive element under it |
| What is clickable, and who wins overlaps | `rhr hitmap <file> --path <screen>` | `nodes[]` (`capturesClicks`), `hitTests[]` (`target`, `targetIsButton` at each element's centre) |
| What a 3D build looks like | `rhr scene <file> --view iso --out build.png --json` | the PNG; `notes`, `missingAssets`, `fallbacks`, `camera` |
| What a place or model holds in 3D | `rhr scene-dump <file>` | a summary: `parts`, `bounds`, `models[]` (biggest groups, with part counts and bounds), `fallbacks`, `missingAssets`; `--path <models[].path>` for one of them |
| Where one model's parts are | `rhr scene-dump <file> --parts --path <model>` (`--class`, `--limit`) | `parts[]`, `partsTotal` |
| World, in-world UI and screen UI together | `rhr preview <file> --view iso --out frame.png --json` | the PNG and the same report |
| Whether an edit changed geometry or only colours | `rhr compare before.png after.png` | `changedPct`, `silhouette.iou` |
| Whether a model's scripts are safe to insert | `rhr inspect <file or id>` | `findings[]` (`require-by-id` is an error), the flagged `scripts[]`, `assetCounts` (`--all` for everything) |
| What a Creator Store model looks like | `rhr scene <id or link> --view iso --out model.png` | the PNG; stderr names the asset and its creator |
| Icons for a set of models | `rhr icons models/ --out-dir icons --size 512` | one `<stem>.png` per model |
| Show a person the build to fly around | `rhr view <file> --no-open`, in the background | the address it prints: give it to the person |

Standard views are Roblox's sides: `--view front` looks at the Front face (-Z, a car's
nose); with `--focus <path>` the model's own front.

## Output

- Every JSON document has a `schema` field (`rhr.check/1`, `rhr.scene-summary/1`, ...).
  A different version means the shape changed.
- Default outputs stay small (tens of KB even for a 100k-part place). Narrow with
  `--path`; ask for everything only when needed (`scene-dump --parts`, `hitmap --all`,
  `inspect --all`).
- `ui`, `scene` and `preview` print the PNG's path, or with `--json` a report
  (`rhr.render/1`).
- Exit codes: 0 done; 1 only from `check` (an error finding); 2 the command failed or
  had nothing to work on, with the reason and what to try on stderr.
- A path is the names from the root joined with `/`: `StarterGui/Shop/Main/Buy`.
  Same-named siblings are numbered in child order, `Card[1]`, `Card[2]`; a bare `Card`
  where there are several is an error, not a guess. Pass paths back exactly as RHR
  printed them.

## Stories (experimental in 1.0)

A story is run in the Rojo project above it, with the project's modules (it needs
`rojo`; RHR downloads it). It is the one input where RHR runs code: fine for your own
project; do not run stories from untrusted pull requests outside a sandbox. Code that
reads the screen size gets the viewport (`--viewport`, `--device`); other sizes read
while the story runs are estimates; tweens end at their goal; controls take their
defaults; nothing is clicked. A story that fails exits 2 with the error pointed at
your files and lines.

## How far to trust the output

Measured against Studio:

- **UI rects** (`layout`, and so the picture and the hit map): within 2 px on every
  fixture, including a complete game UI and flex, grid, table, scaling, scrolling and
  auto-sized layouts.
- **Text**: sizes and line breaks follow Roblox's rules; widths within a few percent.
  Text in a font uploaded by id that RHR cannot load is drawn in a stand-in face,
  marked `fontSubstituted`, and not judged by the text checks.
- **Who gets a click** (`hitmap`, `button-blocked`): Roblox's rules, measured with
  simulated clicks in Studio.
- **Devices** (`--device`): viewports, notches, home bars and touch controls from
  Studio's device emulator.
- **3D part positions, sizes and rotations**: exact. **3D pictures** are close
  approximations (lighting, fog and shadows fitted to Studio).

What RHR tells you it did not do exactly: `missingAssets` (images, meshes, unions it
could not get), `fallbacks` (meshes drawn as boxes), `unsupportedVisualClasses`,
`experimental` (Atmosphere, post effects, local lights, decals; materials without
Studio) and `notes`, in the `--json` reports and `scene-dump`; the same on stderr for
people. Effects are one still frame (`--effect-time T` for another moment). In a
place, 3D draws the world, not models stored in ServerStorage or ReplicatedStorage; a
note names them and `--focus <path>` draws one. docs/known-approximations.md lists
every known difference.

`check` findings: fix `error`; weigh `warning`; `info` (`--min-severity info`) are
patterns that are often intended. An instance the maintainer wants left alone can
carry an `RhrIgnore` string attribute ("all", or check ids separated by commas).

RHR does not run a game's scripts, physics or animation: a UI a script builds or
moves at run time is shown as saved; for UI built by code, use a story.

## Setup

- No setup step: the first command that needs Lune (every Roblox file), Rojo (Rojo
  projects, stories) or, for 3D, a headless browser downloads it once. `rhr doctor`
  shows what RHR found; `--offline` downloads nothing.
- Assets download with the Studio login on the machine. Without Studio (a cloud
  sandbox, CI), ask the person for an Open Cloud API key (a user key with
  `legacy-asset:manage`) and set it as `RHR_ROBLOX_API_KEY` from their secrets, never
  in a file you commit. Without either, pictures use stand-ins and the notes say so.
- Screen UI is laid out below Roblox's 58 px top bar, on a 1920x1080 screen unless
  `--viewport` or `--device` says otherwise; `--topbar-height 0` matches Studio's edit
  view.
