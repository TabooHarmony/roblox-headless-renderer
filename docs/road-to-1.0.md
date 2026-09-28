# RHR: review and road to 1.0

**Status: agreed, 2026-09-28.** Written as a proposal after reading all of the code and
docs, running RHR on the maintainer's real files (the Downloads places, the story spike,
the ProjectA game repo), and looking at what else exists; the maintainer accepted every
recommendation in section 8 the same day. This is now the plan to 1.0: where it and
docs/plan-1.0.md or docs/GOAL.md disagree, this document wins.

## In short

- **The engine is ahead of the product.** RHR already does what nothing else does
  without Studio: UI layout measured against Studio within 2 px, a real 3D renderer with
  Roblox's own materials, terrain, unions, characters and effects, and now UI that code
  builds (React-lua and Fusion stories). The gaps before 1.0 are not about fidelity.
  They are about what an agent is *told*.
- **It is silently empty on the most common real layout.** On ProjectA (code in Rojo,
  UI and maps saved in Studio: a common layout, and the one Roblox's own Script Sync
  produces), `rhr ui .` exits 0 with a blank white PNG and `rhr check .` reports 0
  findings. Screens that code opens by setting `Enabled` cannot be drawn at all.
- **The checks are not yet trustworthy.** On four real files, half of the
  `text-wider-than-box` warnings are wrong by RHR's own layout engine (12 of 24), and one
  real game file gets 101 warnings, mostly intentional patterns. A probe UI with six
  deliberate mistakes (text spilling out of its box, a button off screen, one half off,
  a 12 px close button, unreadable grey-on-white text, a missing image) got no finding,
  and the two labels that were fine got flagged.
- **Some outputs are too big for an agent.** `scene-dump` prints 16 MB and 52 MB on two
  real places; `hitmap` is 294 KB on one game's UI. Claude Code, for one, cuts command
  output at 30,000 characters.
- **Small commands are mostly Python starting.** A warm `rhr check` does about 50 ms of
  work in the server, inside a 0.4 s command on an idle machine and a 3 s one while a
  game runs.
- **Proposed ordering rule:** anything that changes JSON shapes, defaults, flag meanings
  or exit codes happens before the freeze. Everything additive or internal (the native
  client, speed-ups, new commands) can land after 1.0 without breaking anyone.
- **Plan:** (0) finish the story runner, clean up, push, CI on three systems, publish a
  0.9 beta to PyPI; (1) never silently wrong; (2) output an agent can use; (3) speed the
  agent feels; (4) dogfood on real projects, freeze, tag 1.0.
- **Biggest new use cases:** visual regression of UI stories in CI (nothing like it
  exists for Roblox), a structural diff of Roblox files (also as a `git diff` driver),
  device and mobile checks, cropped and annotated renders for agents, and place-by-id
  previews for teams whose UI lives in Studio.

## 1. What RHR is

### One sentence

RHR turns any Roblox file (model, place, Rojo project, story, asset id) into pictures
and facts (layout, findings, what is clickable, what is where, what was approximated)
in about a second, without Studio, an account or a GPU. Built for agents and
automation; just as useful for a person who wants a quick look.

### Who it serves

| Who | Their job | Today | Gap |
| --- | --- | --- | --- |
| An agent in a fully managed Rojo repo (UI as `.rbxmx` / `.model.json`, or React/Fusion code) | see and verify UI and builds after each edit | `ui`, `layout`, `check`, `hitmap`, `scene`; stories (work in progress) | check noise; story tests and batching; output size |
| An agent in a partially managed repo (code in git; UI and maps saved in Studio, like ProjectA) | check the Studio-made UI that its code drives | nothing useful from the repo; the place file or place id works if you know to use it | silent empty result; no way to show screens code opens; place ids reused for 10 minutes |
| Cloud and CI agents (Linux, no Studio: Claude Code on the web, Codex, Copilot agent) | the same, in a sandbox | works with an API key and software WebGL | never run on Linux or macOS since the rewrite; system libraries; blocked downloads |
| Teams reviewing pull requests | catch UI regressions; review changes to binary files | `compare` (pixels only) | stories in batch, baselines, a report; structural diff |
| Asset pipelines | shop and inventory icons, thumbnails | `icons` | several angles, contact sheets, lighting presets |
| Anyone about to insert a free model | look before inserting; spot backdoors | `scene <id>`, `inspect` | `inspect` matches patterns line by line (a `require` through a variable slips past) |
| People without Studio open | a quick look; commissions; sharing | `view`, `scene` | a shareable export (later) |

### What else exists (checked 2026-09-28)

| Tool | Needs | Gives | Next to RHR |
| --- | --- | --- | --- |
| Roblox Studio's built-in MCP server (March 2026) | Studio running with the place open; Windows or macOS; one Studio shared by every agent (ProjectA's AGENTS.md: "ask before using it: another session may be using it") | viewport screenshots, `execute_luau` (so exact `AbsolutePosition` if asked), playtests, simulated input, asset generation | exact pixels and live edits; not headless, not parallel, no Linux or CI, no findings |
| Open Cloud Luau Execution | an API key and a published place | Luau run on a server copy of a place version (tests, data) | no rendering; a server has no GUI layout |
| Roblox thumbnails API | a published asset | 420 px pictures | no files, no UI, no numbers |
| Studio Lite (MIT, 34 stars) | a browser; assets downloaded by hand | a three.js viewer of binary files | no materials, terrain, unions, UI or CLI |
| UI Labs, Flipbook | Studio | story plugins | inside Studio only; RHR runs the same story formats headlessly |

Roblox's roadmap plans, for late 2026, to offer its Open Cloud APIs as tools that
agents call from MCP clients such as Claude Code and Cursor. Worth watching; nothing
announced renders content without Studio.

**Positioning (proposed for GOAL.md and the README):** "Lets an agent *see* Roblox
content without Studio: headless, parallel, on any OS, with the numbers behind the
picture." The earlier "not unique, convenient and light" undersells it: nothing else
found gives Studio-measured UI layout, UI findings, a hit map or story rendering outside
Studio, and Studio's MCP needs a running Studio with the place open, so it cannot run in
CI or on Linux, and agents share that one Studio.

## 2. Where it stands

### Built

Commands: `ui`, `layout` (`--rich`), `check`, `hitmap`, `scene`, `scene-dump`,
`preview`, `view`, `icons`, `inspect`, `compare`, plus `fetch`, `setup`, `doctor`,
`cache`, `browser`, `ir`. Inputs: `.rbxm/.rbxmx/.rbxl/.rbxlx`, Rojo projects, asset ids
and links, and `*.story.luau` (committed as work in progress). Fidelity measured against
Studio: UI rects within 2 px on about 450 objects, text widths within 1.3% on average,
part geometry exact, lighting within about 8/255, particle blending 9/255 RMS. Speed
architecture: a resident server, a warm browser page, RHR's own binary reader (10 to 60
times faster than Lune). Honesty: fallbacks, experimental features and missing assets in
the 3D JSON; every document carries a schema version; shape tests guard the interface.

### Measured this session

The machine was idle at first, then ran Cyberpunk 2077 and Studio for most of the
session, so read the ratios. Bare `python -c pass` from the venv went from 0.2 s to
about 2 s under that load.

| What | Idle | Under load | Server's own work |
| --- | ---: | ---: | ---: |
| `rhr check examples/shop.rbxmx`, warm | 0.39-0.48 s | 2.0-3.1 s | about 50 ms |
| `rhr layout` shop, warm | 0.34-0.45 s | 2.0-3.1 s | about 50 ms |
| `rhr ui` shop, warm | 0.66-0.82 s | 2.4-3.4 s | about 0.2 s |
| `rhr --version` (runs in-process) | 0.56-0.96 s | 2.7 s | |
| `rhr scene` tower, warm | | 2.9-3.8 s | 0.69 s (page 0.28 s, screenshot 0.25 s) |
| `rhr scene`, a 1.3 MB place, warm / after an edit | | 4.8 s / 7.6 s | |
| `rhr scene-dump`, same place | | 12-14 s | |
| a React-lua story through `rhr ui` | | 2.6 s | 1.3 s (rojo build, sourcemap, Lune) |

| Output | Size |
| --- | ---: |
| `scene-dump`, 37k-part place | 16 MB |
| `scene-dump`, 116k-part place | 52 MB |
| `hitmap`, "Steal An Egg" UI | 294 KB |
| `layout --rich`, same | 130 KB |
| `check`, same (101 warnings) | 25 KB |

Tests: the non-browser half passed (47 passed, 1 skipped, 4 min 17 s under load). The
browser half was not run: it draws in software and would have competed with the game.
The cache held 11.3 GB against a 2.1 GB limit, 10.65 GB of it IR in 1,340 folders,
including at least a dozen copies of the same 238 MB IR of one 9.4 MB place. The
resident server held about 690 MB after the big-place commands; the headless browser
about 220 MB.

## 3. Strong suits

- **Measured, not guessed.** Studio ground truth in `tests/studio/`, fitted lighting and
  VFX, text rules taken from Roblox's own behaviour (`TextSize` as line height, advances
  rounded up). Few community tools have ever done this.
- **Discipline on changes.** Speed work is proven by byte-identical outputs over the
  fixtures and 63 real files. Shape tests freeze the interface. Atomic cache writes, job
  objects, no leaked browsers.
- **The right architecture for an edit loop.** Resident server, warm page, profiles that
  read only what a command needs, and a binary reader that made big places practical
  (668 s to 36 s for a first render of a 116k-part place).
- **Breadth of inputs.** Files, Rojo projects, asset links and, uniquely, stories run in
  a Roblox emulation with no library special-cased: React-lua 17 and Fusion 0.3 both
  draw.
- **Honesty built in** for 3D: what was approximated is in the JSON, and
  `docs/known-approximations.md` is unusually candid.
- **Real 3D quality.** The tower renders with Roblox's materials, sun shadows, a lit
  BillboardGui and a glowing lamp; it reads as Roblox.

## 4. Findings

Each finding says when it must be done: **before the freeze** (it changes what the JSON
says, a default, a flag's meaning or an exit code), or **any time**. Sizes: S about half
a day, M about a day, L several days.

### 4.1 Silently wrong or empty (the first priority)

**F1. Empty results look like success.** `rhr ui .` in ProjectA: exit 0, a white PNG,
`"screens": []`, `"notes": []`; `layout` gives `{}`, `check` 0 findings. The project maps
only code (`$ignoreUnknownInstances` everywhere), so its UI is in the place file. `scene`
on the same project fails with "no renderable 3D geometry", which is right but says
nothing about why. Fix: a UI command with nothing to draw exits 2, like `scene`, with a
hint: the project ignores unknown instances, so UI saved in Studio is not in it; pass the
place file, or the place id (read `servePlaceIds` from the project when it is there).
*Before the freeze. S.*

**F2. Screens that code opens cannot be drawn.** A ScreenGui saved with `Enabled =
false` is skipped by every command, and nothing shows a `Visible = false` frame.
ProjectA's `UIController` opens every screen by setting `Enabled`, so every closed screen
is invisible to RHR. Fix: `--show <path>` (repeatable: turns on `Enabled`/`Visible` for
that node and its ancestors) and `--only <path>` (draw one ScreenGui or subtree alone,
not stacked under every other screen that happens to be enabled). *Before the freeze. M.*

**F3. A missing image is not in the JSON.** A UI with an image RHR could not get draws an
empty area; `ui --json` says nothing (`notes: []`). The interface's first rule is that
every fact an agent needs is in the JSON; 3D reports already carry `missingAssets`. Fix:
`missingAssets` in `ui` and `preview` reports, with the reason (offline, refused,
moderated), and an `image-missing` finding in `check`. *Before the freeze. S.*

**F4. Place ids are reused for 10 minutes.** For a Creator Store model that is fine; for
a place someone is editing (Team Create saves continuously) it shows an old version.
Fix: `--refresh`, and a shorter reuse window for places. *Any time. S.*

### 4.2 Checks: precision and coverage

**F5. `text-wider-than-box` measures the wrong text.** It re-measures every label with
bundled Montserrat at the label's nominal `TextSize`, ignoring its font and `TextScaled`.
The layout engine that drew the label already knows the real width (`text.bounds` in
`layout --rich`, not clamped: the shop example's long name is 413 px there, 460 px in
`check`'s message). Measured on four real files: 12 of 24 warnings are false by the
engine's own numbers (TextScaled labels, auto-sized labels, other fonts). A probe
`TextScaled` "PLAY NOW" drawn at 27.7 px in its 120 px box was reported as 570 px wide.
Fix: read `bounds` and `drawnSize` from the dump. *Before the freeze. S.*

**F6. Too many findings on real games, mostly intentional.** "Steal An Egg": 101
warnings; "GAG But Everything Is Free": 86. Most are `duplicate-zindex` (41,
47) and `invisible-content` (25, 37): layout slots, holder frames, labels a script fades
in, equal-`ZIndex` siblings whose order is fixed by the saved file (the message's "tree
luck" overstates it). An agent shown 100 warnings learns to ignore all of them. Fix: an
`info` severity that is not printed by default (`--min-severity`), `--ignore <check>`, a
per-instance suppression (an attribute such as `RhrIgnore = "invisible-content"`), and
`--baseline old.json` to report only new findings: exactly what an edit loop wants
("did my edit add a problem?"). Demote `duplicate-zindex` and `invisible-content` to
`info`. *Severity values before the freeze. M.*

**F7. The mistakes that matter most are not checked.** Everything below can be derived
from data RHR already computes:

| Check | From | Severity |
| --- | --- | --- |
| wrapped text taller than its box (lines spill out) | `text.lines`, `text.bounds` | warning |
| element fully or partly off screen | rects vs the viewport or safe area | warning / error for a button |
| button whose centre another element takes (blocked) | the hit map | error |
| tap target too small on a touch device | rects, `--device` | warning |
| low text contrast | text colour against the painted background | info |
| input under the Roblox top bar when insets are ignored | insets | warning |
| input under the mobile thumbstick or jump button | `--device`, zones from Roblox's PlayerModule | warning |
| image missing or refused | the fetch result (F3) | warning |

The IDs of the first set go into the contract; later checks are additive. *First set
before the freeze. M.*

**F8. The hit map's rules are unverified.** Every `Active` element captures clicks,
visible or not; `Interactable = false` is ignored. On "Steal An Egg", 12 of 19 visible
buttons have their centre taken by another element, many of them hidden. Roblox's docs
describe `Active` as sinking input to the 3D world and firing `Activated`; they say
nothing about hidden objects taking clicks. Fix: measure in Studio with the MCP's input
simulation (a hidden `Active` frame over a button; `Interactable`; `Modal`; a disabled
ScreenGui), then follow what Studio does. *Before the freeze. S-M.*

### 4.3 Output an agent can use

**F9. Unbounded outputs.** `scene-dump` prints every part (16 MB, 52 MB on real
places), and the AGENTS.md table sends agents to it for "where every part is"; `hitmap`
and `layout --rich` run to hundreds of KB on one game's UI; nothing selects a subtree.
Fix: `scene-dump` prints a summary by default (counts by class, bounds, top-level models
with their part counts, fallbacks, missing assets) and takes `--path`, `--class`,
`--limit`, `--parts` for detail; `--path <subtree>` on `layout`, `hitmap` and `check`;
`hitmap --at X,Y` for "what is at this pixel". Add a test that fails when a default
output on a big fixture passes a size budget. *Before the freeze. M.*

**F10. Every picture is the full viewport.** A story's 720x155 row of cards sits in a
1615x1080 canvas. An agent pays a couple of thousand image tokens per look whatever the
content. Fix, all additive: `--crop <path>` or `--fit` (crop the PNG to an element or to
what was drawn, plus a margin), `--scale` or `--max-size` (shrink the PNG without
changing the layout), and `--annotate` (numbered boxes on elements, the numbers mapped
to paths in the JSON, so an agent can say which box it means; for 3D, labels on
models). *Any time; recommended for 1.0. M.*

**F11. One size of screen.** The default viewport is 1615x1080 (3:2, inherited from
pinevex's reference renders); players have 16:9 desktops and phones near 19.5:9 in
landscape, with notches and touch controls. Fix: `--device phone|tablet|desktop|console`
presets (viewport, safe area, top bar, touch zones) and `check --devices all`; decide
whether the default becomes 1920x1080 while defaults can still change. *Before the
freeze (the default). M.*

### 4.4 Speed the agent feels

**F12. Python's start is most of a small command.** The server answers `check` in about
50 ms; the command takes 0.4 s idle and 3 s under load. On Windows each `rhr` is three
processes: `rhr.exe` (the pip launcher), the venv's `python.exe` (a redirector), then
the real interpreter. `rhr --version` imports the CLI to print a version (0.6-0.9 s
idle). Fix: a native client of a few hundred lines (Rust or Go) speaking the existing
wire format, shipped in platform wheels with the Python client as fallback; meanwhile the
Python client answers `--version` and `--help` itself, and `rhr batch` runs several
commands in one call (`check`, `layout`, `ui` of the same file is the usual trio). Not
interface: can follow 1.0; recommended for 1.0 if the platform wheels are green in CI.
*M-L.*

**F13. The server runs one command at a time.** A second command while one runs goes
cold in its own process: full imports, and big files read again. Agents run sub-agents
and parallel tool calls. Fix: wait for the running command up to a few seconds before
falling back; later, a small pool of warm workers. *Any time. S.*

**F14. Every view rebuilds the scene.** Four views of a model are four full builds.
Fix: `--views iso,front,top,right` draws several cameras on one built scene, as files or
one contact sheet; `icons` can then offer several angles cheaply. The screenshot is 36%
of a small render's server time (0.25 of 0.69 s), so `--crop`/`--scale` also save time.
*Any time. M.*

**F15. Stories build the whole project each run.** `rojo build` and `rojo sourcemap` run
for every story (about 1.3 s with React-lua). Fix: one build, one Lune process, many
stories (`rhr stories`, see §6). *Any time. M.*

### 4.5 Resource hygiene

**F16. The cache grows far past its limit.** Pruning runs once a day and spares anything
used in the last hour; every edit or upgrade writes a new IR folder; a place's IR is
about 25 times the file (238 MB for 9.4 MB). Fix: keep only the newest IR per source path
and profile (drop the older one when writing), and check the limit after writing, not
daily. *Any time. S.*

**F17. The server keeps big files in memory for 20 idle minutes.** Up to 450 MB of JSON
(roughly 2 GB as Python objects); 690 MB measured after the big-place commands. Fix:
drop IRs above a size after a few idle minutes; `RHR_SERVER_MEMORY_MB`. *Any time. S.*

### 4.6 Meanings to settle before the freeze

**F18. `--view front` shows the back.** It looks from +Z; Roblox's Front face is -Z, so
cars and icons show their rear. Views are also world-axis: a car turned 90 degrees in a
place is not seen from its front with `--focus`. Fix: Roblox's meaning, and with `--focus`
the model's own pivot orientation. *Before the freeze. S.*

**F19. Exit codes and notes for "nothing to do".** Decide once, for every command: empty
input (F1), no world in a place, a story that builds nothing. Proposal: exit 2 with a
reason and a hint, never exit 0 with an empty document.

### 4.7 Platforms and outside dependencies

**F20. Nothing since 0.7 has run off this Windows machine.** The DevTools client, job
control, the resident server, the fresh install and the story runner have not run on
macOS or Linux; the Studio login has never been tried on macOS; on Linux, skia needs
`libegl1` and `libgl1` just to import (the README lists only the browser's libraries);
cloud sandboxes often block downloads, and a blocked download waits for its timeout on
every render. Fix: CI on three
systems, one real Mac session, a `python:3.12-slim` container, one cloud agent with an
API key; `rhr doctor` checks libraries and reachability, and downloads fail fast once a
host is known unreachable. *Before 1.0. M.*

**F21. The login path depends on Roblox's cookie.** Asset Delivery has required
authentication since April 2025, and Roblox enforces a new `.ROBLOSECURITY` format and
rotation from May 2026. RHR sends Studio's saved cookie through Lune and never takes back
a rotated one. It works today; check that using it never signs Studio out, and keep the
API key path first-class (Roblox recommends Open Cloud credentials for tools). *Watch.*

### 4.8 Security hardening (all S, any time before 1.0)

- Chromium runs with `--no-sandbox` everywhere; only Linux-as-root needs it, and the
  page decodes images and meshes from the internet.
- `rhr view` and the per-render data servers send `Access-Control-Allow-Origin: *` and
  do not check the `Host` header: a web page open in the user's browser (or a
  DNS-rebinding one) could read the served place. Check `Host`, drop the header on
  `view`, and put a random token in the data server's paths.
- Chunk decompression trusts the declared size (up to 4 GB per chunk); `inspect` exists
  to open untrusted free models. Cap it relative to the file's size.
- Stories run the project's code in Lune with Lune's full powers: checked this session,
  a story reaches Lune's own `require` through `getfenv(0)` and loads `@lune/process`.
  Fine for your own code; the docs should stop saying RHR never runs code, and say not to
  run stories from untrusted pull requests in CI outside a sandbox. (Removing `getfenv`
  and friends from the story environment narrows it; it will never be a real sandbox.)

### 4.9 Docs and process

- GOAL.md still lists the MCP server, `render`, and an old feature table; the README
  says "v0.7, early alpha"; the scope decided on 2026-09-27 is only in plan-1.0.md.
- AGENTS.md needs the new loops: Rojo repo, partially managed repo with a place id,
  stories, CI. Ship it as an agent skill too (`SKILL.md` for Claude Code and Codex, the
  way ProjectA already loads its Roblox skills), and a copy-paste snippet for a project's
  AGENTS.md.
- The story runner has no tests yet; `tests/test_server.py` is flaky; no real-game
  corpus measures the checks' precision; `inspect` is pattern matching (a `require`
  through a variable or a built string slips past): fine as "reasons to look" if the docs
  say so.

## 5. Architecture

**The ordering rule.** 1.0 freezes the interface, not the internals. So: settle every
default, JSON shape, flag meaning and exit code first; then everything that only makes
RHR faster or adds commands can ship in 1.x. This puts F1-F3, F5-F9, F11, F18, F19
before the freeze and lets the native client, multi-view, the story batch runner, diff
and the rest land when ready.

**Process model.** `rhr` (client) -> resident server -> warm browser worker -> the kept
page, which fetches the scene from a data server in the resident server. Keep it. Two
changes: the server waits briefly instead of going cold when busy (F13), and the client
becomes native (F12). Do not fold the browser worker into the server: being its own
process is what lets several RHR processes, and a future pool, share one warm browser.

**The IR.** JSON with typed properties, about 25 times the size of a big place's file,
parsed once per server. Good enough for 1.0 because it is internal. After 1.0: a compact
binary or columnar form (or at least a faster JSON parser), and IR per source kept once
(F16).

**Readers.** RHR's own binary reader plus Lune for XML. A Python XML reader (after 1.0)
would leave Lune only for the signed-in download and stories, and remove a download for
anyone working in `.rbxmx`.

**Contract tests.** Add output-size budgets (F9) and the list of check IDs. Mark
stories, `icons` and `view` experimental in the contract for 1.0 so their details can
still move.

**What not to change.** Chromium with three.js, the own DevTools client, the own binary
reader, skia for 2D, the equivalence discipline, the resident server. All measured and
right.

## 6. Use cases not yet served, ranked

1. **Visual regression for UI stories in CI.** `rhr stories [project]` renders every
   story once (one build, one Lune process) to PNG, layout and findings; against a
   baseline folder it reports what changed, as JSON and a Markdown or HTML page for a pull
   request comment; a GitHub Action wraps it. This is Chromatic for Roblox; nothing like
   it exists (UI Labs and Flipbook run only inside Studio). *1.1; design the output in
   1.0.*
2. **A structural diff of Roblox files.** `rhr diff a b`: instances added, removed,
   moved or changed (by path and property), rects that moved, parts that moved, plus
   before and after crops. An agent confirms "only what I meant changed" far better than
   with pixel IoU, and a `textconv` mode makes `git diff` readable on `.rbxm`/`.rbxl`,
   which no Roblox tool does. Combined with place versions (`<placeId>@<version>`), it
   answers "what changed since the last publish". *1.1, earlier if dogfooding asks.*
3. **Devices and mobile.** `--device` and the checks that go with it (F7, F11). Most
   Roblox players are on phones. *1.0.*
4. **Grounding for agents.** Crops, annotations, `--at` / pick (F9, F10). *1.0.*
5. **Teams whose UI lives in Studio.** Place ids with `--refresh`, the F1 hint, and a
   recipe for UI built at run time: during a playtest, the Studio MCP's `execute_luau`
   serialises `PlayerGui` to a file, and RHR checks it (findings and hit map Studio does
   not give). *Recipe: docs only.*
6. **A place audit.** `rhr stats`: counts by class, mesh triangles, unique textures and
   their bytes, lights, particle rates, unanchored parts, total asset download. What an
   agent needs for "why does my game load slowly or lag". *1.1. S-M.*
7. **Pseudo-localisation.** `check --expand-text 1.4` lengthens every string and reports
   what overflows: Roblox translates games automatically, and German text is about 30%
   longer. *1.1. S.*
8. **Contact sheets.** Icons in one grid image to review 50 at a glance; several 3D
   views in one image (F14). *1.x. S-M.*
9. **Export for people.** glTF from the built three.js scene (Blender round trips;
   ProjectA already has a Blender MCP), and `rhr view --export build.html`, one file to
   send a client. Mind asset licences. *Later.*
10. **Motion.** A pose from an Animation at time t; VFX as a GIF or a strip of moments.
    *Later (already on the after-1.0 list).*

## 7. The plan

### Phase 0: clean slate (1-2 days)

- Finish the story runner: tests over `tests/fixtures/rojo_stories`, a profile phase,
  the `model` name in `check`, `--viewport` passed to the story, docs, CHANGELOG.
- Cache (F16) and server memory (F17); the security items in 4.8; fix
  `tests/test_server.py`.
- Rewrite GOAL.md and the README around the scope and positioning in §1.
- Push. CI on Windows, macOS, Linux. Publish **0.9.0b1** to PyPI by trusted publishing
  (not 1.0.0rc1: Phases 1 and 2 change the interface).
- Exit: CI green on three systems; `uvx roblox-headless-renderer` from PyPI works on a
  clean Windows and in a `python:3.12-slim` container.

### Phase 1: never silently wrong (2-3 days)

- F1, F2, F3, F5, F6, F7 (first set), F8 (after the Studio measurement), F18, F19.
- Build a small private corpus next to the benches: ProjectA's place, the story spike
  and four real games, with every finding reviewed by hand; keep the probe fixture from
  this review as a test.
- Exit: the probe's six mistakes are found and its two correct labels are not flagged;
  at least 95% of error and warning findings on the corpus judged right; no command
  exits 0 with an empty result.

### Phase 2: output an agent can use (2-3 days)

- F9, F10, F11 (`--device`, the default viewport decided), `hitmap --at`.
- AGENTS.md rewritten around the real loops; `SKILL.md`; the contract snapshot updated
  and reviewed.
- Exit: every default output on the 116k-part place within its budget (proposed 50 KB);
  an agent can answer "what is at this pixel" and "show me only the shop screen" in one
  command each.

### Phase 3: speed the agent feels (2-4 days, alongside Phase 2)

- F13 (wait instead of going cold), client-side `--version` and `--help`, `rhr batch`.
- The native client in platform wheels, with the Python client as fallback (F12).
- Several views on one built scene (F14); stories in one build (F15).
- Exit, on an idle machine: warm `check` of a small UI at most 0.1 s wall with the native
  client (0.45 s without it); four views of a model in at most 1.5 times one view.

### Phase 4: dogfood and freeze (1-2 weeks, mostly elapsed time)

- Use RHR from agents every day: ProjectA (through its place), a story project, a
  Creator Store vetting session. Log each awkward moment as an issue; fix before the
  freeze.
- The Studio side-by-side on a handful of real games (plan-1.0.md step 7.4).
- Platform proof: a real Mac (Studio login included), the Linux container, one cloud
  agent with an API key.
- Freeze: final contract snapshot, **1.0.0rc1**, a stretch with no interface change,
  **1.0.0**. Announce on the DevForum with the skill and examples.

### 1.0 is done when

1. No command exits 0 with a blank or empty result, for any input kind: files, full and
   partial Rojo projects, stories, asset and place ids.
2. At least 95% of error and warning findings are right on the reviewed corpus.
3. Every picture command reports missing and approximated assets in its JSON.
4. Every default JSON output stays within its size budget on a 100k-part place.
5. CI is green on Windows, macOS and Linux, including the fresh install from PyPI; one
   real Mac and one cloud agent run are written up.
6. GOAL.md, the README, AGENTS.md and the skill agree.
7. Two weeks of daily agent use without an interface change.
8. Warm small-command wall times recorded on an idle machine.

### After 1.0

1.1: `rhr stories` and visual regression in CI; `rhr diff` and the `git` driver; place
versions; `rhr stats`; pseudo-localisation. 1.2 and later: the Python XML reader, a
compact IR, instancing opaque parts in heavy scenes, glTF and a shareable viewer, poses
and animated effects. A native renderer only if Chromium ever blocks a platform.

## 8. Decisions (all recommendations accepted 2026-09-28)

| Decision | Decided | Why |
| --- | --- | --- |
| First PyPI version | 0.9.0b1 now; 1.0.0rc1 after Phase 2 | the interface still changes in Phases 1-2; "rc" should mean nearly final |
| `--view front` | Roblox's Front (-Z); model-relative with `--focus` | icons and previews show the back today |
| `scene-dump` default | a summary; `--parts` for every part | 52 MB on a real place |
| Severities | add `info`; demote `duplicate-zindex` and `invisible-content` | 100 warnings per game |
| Nothing to draw | exit 2 with a hint | an empty success misleads an agent |
| Default viewport | 1920x1080, plus `--device` | it is what players have; decide once, before the freeze |
| Hidden screens | `--show` and `--only` | ProjectA's screens open by code |
| Hit map semantics | follow a Studio measurement | today's rule marks many real buttons blocked |
| Native client | build in Phase 3; ship in 1.0 if CI is green | biggest wall-clock win; not interface |
| Stories in 1.0 | yes, marked experimental | how code-first agents make UI |
| macOS first class | only after a real Mac run | it has never run there since 0.7 |

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Roblox changes how Studio's login works, or RHR's use of it signs Studio out | verify after the 2026 cookie change; keep the API key path first-class; consider OAuth later |
| Roblox ships headless previews or agent-facing rendering | lean on what Studio cannot do: CI, Linux, parallel, files as the source of truth, structured checks, stories |
| Too much surface for one maintainer before a freeze | the ordering rule; experimental labels for `view`, `icons`, stories |
| Surprises on macOS and Linux | Phase 0 before new features |
| Agents stop trusting findings | the precision corpus and the 95% bar |
| Lune or Chrome for Testing change | pinned versions; fewer Lune uses after the XML reader |
| "Roblox" in the package name | community tools often carry the name; keep `rhr` ready as the fallback name |

## Appendix: how the numbers were taken

- Timings: `scripts/bench.py --reps 3` (shop, CRATES GUI, tower, Jaxelos star VFX, Build
  A Plane Template) and a small harness running each command as its own process; the
  server's own time from `RHR_PROFILE=1`. The machine ran a game for most of the session.
- Check precision: `rhr check` against `rhr layout --rich` on "Steal An Egg", "GAG But
  Everything Is Free", "Heartsmm2" and "CRATES GUI" (Downloads); a finding counts as false
  when the engine's own `text.bounds` fits the box.
- Blocked buttons: visible `TextButton`/`ImageButton` nodes whose centre's hit test names
  another target, from `rhr hitmap`.
- Probe: a hand-made `.rbxmx` with a TextScaled label, wrapped text too tall for its box,
  an off-screen and a half off-screen button, a 12 px button, grey text on white, a
  missing image and a wide font. Kept with the story sandbox test and the raw bench times
  in `C:\Users\taboo\Desktop\Files\rhr-review\` (private, like the other benches); add the
  probe to `tests/fixtures/` with its test in Phase 1.
- Outside tools: Roblox's Studio MCP documentation and March 2026 announcement, the Luau
  Execution API, the 2026 `.ROBLOSECURITY` change, Studio Script Sync (scripts only),
  Studio Lite, UI Labs and Flipbook.
