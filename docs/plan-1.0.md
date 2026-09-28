# Plan to 1.0

The working plan for the 1.0 release candidate, written 2026-09-27 at the end of a
session so the next one can start from here. docs/GOAL.md holds the decisions and the
order; this page holds the detail. Nothing here is pushed yet: work lands as local
commits on `main`, and pushing or running CI waits until we agree to release.

## Where it stands

| Step | State |
|---|---|
| 1. Interface review and freeze | **Done.** docs/interface-1.0.md (decided 2026-09-27); `rhr ui`, `--json` reports (`rhr.render/1`), `rhr.compare/2`, exit codes 0/1/2, dead flags removed. Commit 6e8b2cb. |
| 2. Drop the MCP server | **Done.** Commit 010f073. |
| 1b. Shape tests | **Done.** tests/test_contract.py and tests/contract/interface.json (`--update` after an intentional change). Commit 378ca64. |
| 3. Own browser client instead of Playwright | **Done locally** (CI jobs written, not yet run). Results below. |
| 4. pinevex becomes our own code | **Done.** `src/rhr/ui_engine/`, docs/ui-engine.md. |
| 5. PyPI, `uvx`, fresh-machine CI | **Done locally**; the CI jobs and the first PyPI upload wait for the release. Below. |
| 6. Basic large-place check | **Done.** Results below. |
| 6b. Performance pass | **Done (2026-09-27).** Resident server, work in proportion to what a command needs, profiles "ui" and "world", post-processing compiled once. docs/performance.md (design, numbers, what is left). |
| 7. Candidate period, tag 1.0 | **Next**, reshaped: see below. |

The full suite was green after step 1b (77 passed, 1 skipped: the Studio-models test
that needs `RHR_STUDIO_MODELS`), and after step 3 (79 passed, 1 skipped) with
Playwright uninstalled.

## 3. Own browser client (replaces Playwright)

**Goal:** RHR drives the browser itself over the Chrome DevTools Protocol (CDP). It
uses a Chromium-family browser already on the machine, and downloads the pinned
headless shell only when there is none. Same pixels, less to install (Playwright is
104 MB, 86 MB of it a bundled Node), faster cold renders (0.7-1 s less each), no Node
process. Measurements and reasons: docs/renderer-options.md (Option 2 and 3).

**Results (2026-09-27, step 3 done locally).** `src/rhr/cdp.py` (the client, the job
object, profiles), `src/rhr/browsers.py` (discovery, the pinned download),
`scripts/browser_stress.py`, tests/test_browsers.py and tests/test_browser_lifetime.py.
Measured on the maintainer's Windows machine:

- Pixels: eight scenes (place, lighting, materials, particles, VFX, world UI, tower, a
  ViewportFrame) rendered by the old Playwright code and the new client, software
  WebGL: **identical**, every pixel. The pinned shell is Chrome for Testing
  145.0.7632.6, byte for byte the build Playwright 1.58 installed.
- Time (8 interleaved runs each, tower at 800x600, GPU): cold render 6.37 s -> 4.63 s
  inside RHR (launch 1.7 s -> 0.3 s); warm render 768 ms both.
- Lifetime: a process holding a browser killed outright leaves no browser process (6
  processes checked; with the job object disabled all 6 survived); its profile is
  removed by the next launch. Stress (`scripts/browser_stress.py`): 22 cycles each on
  the shell, Chrome and Brave, two at once in the middle: no failure, no window, no
  profile left.
- Not yet checked: the CI jobs (Linux system libraries for the shell, the runner's own
  Chrome, Edge on Windows), lifetime on macOS and Linux (parent-death signal, process
  group), Edge locally (not installed here). The full suite also passes with
  `RHR_BROWSER` at the installed Chrome (81 passed, 1 skipped).

**Starting point:** a working prototype, standard library only, outside the repo in
`C:\Users\taboo\Desktop\Files\rhr-browser-proto\`:

- `rhrcdp.py`: a minimal WebSocket client, CDP for the Chromium family (and a WebDriver
  BiDi class for Firefox, which is **not** to be ported: Firefox is out), launch with a
  throwaway profile and `--remote-debugging-port=0`, render one page, shut down.
- `run_matrix.py`: swaps `rhr.browser_render.render_once` for the prototype and renders
  nine scenes through the real `rhr scene` / `rhr preview`; `diff.py` compares runs.
- `stress.py`: 22 launch/render/close cycles per browser, two at once in the middle,
  watching for visible windows and left-over profiles.

### What to build

1. **`src/rhr/cdp.py`**: the client. From the prototype: WebSocket (text frames,
   64-bit lengths for large screenshots, ping handling), numbered requests with events
   kept aside, `Target.createTarget` + `Target.attachToTarget {flatten: true}`,
   `Emulation.setDeviceMetricsOverride`, `Page.navigate`, a `Runtime.evaluate` promise
   that resolves on `data-rhr-ready` / `data-rhr-error`, `Page.captureScreenshot`
   (`optimizeForSpeed`), `Emulation.setDefaultBackgroundColorOverride` for transparent
   renders, `Runtime.exceptionThrown` and console errors collected so a page that never
   gets ready says why (today's `problems` list), a timeout on every wait (today:
   150 s one-shot, 60 s kept page).
2. **Launch** (keep today's flags from `browser_render._COMMON_ARGS`, plus
   `--use-angle=swiftshader` for `RHR_WEBGL=software`): `--headless` for full browsers
   (not for `chrome-headless-shell`), `--remote-debugging-port=0`, own
   `--user-data-dir` in the temp folder, `--no-first-run --no-default-browser-check
   --disable-extensions --disable-component-update --disable-sync --mute-audio`,
   `about:blank`; hidden console (`rhr.procs.no_window`). Read the port from
   `<profile>/DevToolsActivePort`.
3. **Lifetime, from the stress test's findings:**
   - Retry reading `DevToolsActivePort` while it is locked or has fewer than two lines
     (Brave keeps it locked for a moment on Windows).
   - Any failure during start kills the browser's whole process tree and removes the
     profile (one headless Brave was left running before this was handled).
   - Tie every browser to RHR's life: on Windows a job object with
     `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes), so the browser dies with the
     process that started it even on a crash; elsewhere a new process group, killed on
     exit. Close: `Browser.close`, wait, then kill the tree, then delete the profile
     with retries.
4. **Which browser** (`rhr/browsers.py`), in order: `RHR_BROWSER` (a path; also read
   `RHR_CHROME` for one release), the pinned shell if already downloaded, Chrome, Edge,
   Brave, Chromium, else download the pinned shell.
   - Windows: `Program Files`, `Program Files (x86)` and `%LOCALAPPDATA%` installs, and
     the `App Paths` registry keys (HKLM and HKCU) for `chrome.exe`, `msedge.exe`,
     `brave.exe`.
   - macOS: `/Applications/<name>.app/Contents/MacOS/<name>` and the same under `~`.
   - Linux: `google-chrome`, `google-chrome-stable`, `microsoft-edge`,
     `brave-browser`, `chromium`, `chromium-browser` on `PATH`. Skip snap Chromium
     (`/snap/`): it cannot use a profile under `/tmp`.
   - A browser that fails to start (for example a company policy that turns remote
     debugging off) falls through to the next one, and the reason is kept for
     `rhr doctor`.
5. **The pinned shell download**: Chrome for Testing `chrome-headless-shell` at a
   pinned version (the JSON endpoints under
   `https://googlechromelabs.github.io/chrome-for-testing/`), platforms `win64`,
   `mac-arm64`, `mac-x64`, `linux64` (there is no Linux ARM build: on Linux ARM a system
   Chromium is required, and the message says so). Downloaded into the RHR cache the
   first time a 3D render needs it, with one line on stderr ("downloading the
   headless browser, about N MB, once"); `RHR_BROWSER_DOWNLOAD=0` forbids it and fails
   with a message that says what to install instead. Atomic write, checksum or size
   check, extract, mark executable on POSIX. `rhr setup --browser` downloads it ahead
   of time (CI, offline machines).
6. **Wire it in:**
   - `browser_render.py`: `launch()` and `capture()` on the new client; `render_once`
     unchanged for callers.
   - `browser_daemon.py` and `KeptScenePage`: the warm worker keeps one browser and one
     kept page over the new client (today it uses Playwright's `page.evaluate`,
     `wait_for_function`, `set_viewport_size`).
   - `browser_session.py`: `code_stamp()` so an old worker is replaced; status adds
     the browser used.
   - `tools.py`: replace `chromium_path()` / `_install_chromium()` (Playwright's
     install) with the new discovery and download; `rhr doctor` names the browser it
     would use and why others were skipped.
   - Add `browser` (name, version, path) to the `rhr.render/1` report and to
     `rhr browser status` (additive; refresh tests/contract/interface.json).
   - `pyproject.toml`: drop `playwright`.
   - CI (`.github/workflows/ci.yml`): drop `python -m playwright install`; on Linux
     install the shell's system libraries (what `--with-deps` did: `libnss3`,
     `libatk-bridge2.0-0`, `libgbm1`, ... check the list against a fresh runner); run
     the suite with `rhr setup --browser` so tests use the pinned shell; add one job
     that uses the runner's own Chrome and one with Edge (`RHR_BROWSER`).
   - Docs: README install section, docs/AGENTS.md, tests/run.sh, the conftest marker
     text, docs/known-approximations.md if it names Playwright.
7. **Tests:**
   - The whole suite must pass unchanged with the pinned shell, in software mode, with
     **identical pixels** to today (the prototype showed it: same page, same
     SwiftShader).
   - Unit tests for browser discovery with fake installs (temp folders, a fake
     `PATH`, an `RHR_BROWSER` that does not exist, a browser that exits at start).
   - A lifetime test: start a render, kill the RHR process, and check no browser
     process with RHR's profile prefix remains; a start failure leaves nothing behind.
   - The prototype's stress run (launch cycles, two at once) as a slow test or a
     script, run before a release.
8. **Done when:** Playwright is gone from `pyproject.toml`; the suite passes with the
   pinned shell and with `RHR_BROWSER` pointing at Chrome; a fresh machine with Chrome
   or Edge renders 3D with no download; one without downloads the shell once; no
   browser process or profile is ever left behind; cold and warm timings are no worse
   than today (warm small scene about 1 s, cold about 0.7-1 s faster).

## 4. pinevex becomes our own code

Today `src/rhr/vendor/pinevex/` is rebuilt from the pristine upstream copy plus
`patches/NNNN-*.patch` by `scripts/make_patches.py`, which must reproduce it byte for
byte (src/rhr/vendor/VENDOR.md, patches/README.md). As a fork:

- Keep the code where it is (or move it to `src/rhr/ui_engine/`; decide in the step,
  moving touches every import and the package-data list).
- Drop `scripts/make_patches.py` and the pristine copy; keep `patches/` and its README
  as the history of why the code differs from upstream (or fold that into one
  `docs/ui-engine.md`).
- VENDOR.md says it is a fork of upstream commit db292ac, Apache-2.0, with the
  licence and third-party notices kept.
- Remove what RHR never runs, now that there is no upstream tree to match.
- Remove the calibration hooks `RHR_TABLE_Y_SCALE*` / `RHR_TABLE_NODRAW_*` in
  `ui_engine/text_advances.py` unless still needed.
- Done when: the suite passes, no script rebuilds the engine, and a UI fix is an
  ordinary edit.

**Done (2026-09-27).** Moved to `src/rhr/ui_engine/` as a real subpackage with
package-relative imports: RHR no longer puts the engine's folders on `sys.path`
(which had put generic top-level names such as `ui_engine` on every user's import
path). `converter.py` and `postprocess.py` are upstream's `tree_to_pinevexobject.py`
and `pinevex_postprocess.py`; the one function RHR used from upstream's binary-parser
adapter is `font_assets.py`. Removed: the parser, the web demo, the Luau exporter, the
debug stepper, the icon manifest, `scripts/make_patches.py`, `RHR_TABLE_*`. `patches/`
stays as history. Suite unchanged, render baselines identical.

## 5. PyPI, `uvx`, fresh-machine CI

- **Install story:** `uvx roblox-headless-renderer ...` runs the tool once; for an
  agent that runs it all day, `uv tool install roblox-headless-renderer` puts `rhr` on
  `PATH` (no resolution per call). `pip install roblox-headless-renderer` still works.
  `uvx <package>` runs the command named like the package, so add a second console
  script `roblox-headless-renderer = "rhr.cli:main"` next to `rhr`, or document
  `uvx --from roblox-headless-renderer rhr`. **Decide** which the README leads with.
- **No setup step on the usual path:** Lune (needed for every model file) and Rojo
  (Rojo projects only) download themselves on first use, like the browser, with a
  notice and the same `RHR_*_DOWNLOAD=0`-style switch; `rhr setup` stays for doing it
  ahead of time. Check what happens today when Lune is missing (`tools.missing_message`).
- **Publishing:** check the name is free on PyPI; a release workflow using PyPI
  trusted publishing on a tag; the wheel's contents (package-data: vendored fonts,
  three.js, draco) and size; an upgrade note per release in the CHANGELOG.
- **Fresh-machine CI:** on Windows, macOS and Linux runners, install from the built
  wheel with `uvx`/`pip` in a clean environment, then render a UI, a place and an
  effect: once with the runner's installed browser, once with none (download path).
  Run the suite on the lowest supported Python (3.12) too: it already caught one bug
  (`--camera -10,5,3`).

**Done locally (2026-09-27).**

- The README leads with `uvx roblox-headless-renderer ...` (a second console script
  of that name) and `uv tool install` for agents; `pip install` works too. Its links
  and images are absolute GitHub URLs so they work on PyPI's page.
- `tools.require()`: Lune and Rojo download on first use with a notice;
  `RHR_TOOL_DOWNLOAD=0` forbids it. `--offline` now sets `RHR_OFFLINE` for the whole
  command, and every download checks it (tools, browser, the font-name lookup, which
  used to call Roblox's API even offline). Tool downloads are atomic.
- PyPI name `roblox-headless-renderer` is free (checked 2026-09-27). Package metadata
  (URLs, classifiers, keywords). `.github/workflows/release.yml`: on a `v*` tag, checks
  the tag equals the version and the CHANGELOG has its section, builds, `twine check
  --strict`, publishes by trusted publishing (environment `pypi`). **The maintainer
  must add the pending publisher on pypi.org and the `pypi` environment on GitHub**
  (the steps are at the top of release.yml).
- Wheel 12 MB (193 files, the 28 engine fonts, three.js, draco); the sdist builds the
  same wheel; both pass `twine check`.
- `.github/workflows/ci.yml` job `fresh-install`: three systems x {installed browser,
  every browser hidden}, the built wheel with `uv tool install` and `uvx` on Python
  3.12, no Lune/Rojo/setup; renders `examples/shop.rbxmx`, a place and a particle
  effect and checks each `--json` report (`scripts/check_report.py`: schema, PNG,
  which browser, particles drawn), and that Lune was downloaded.
- Simulated locally (Windows): the wheel installed with `uv tool` into empty folders,
  empty cache, no Lune on `PATH`: Lune downloaded itself on the first command; the
  UI, the place and the effect rendered with the installed Chrome 154; `uvx ...
  roblox-headless-renderer --version` runs. Not checked locally: the download-browser
  variant with browsers hidden (the download itself was checked with `rhr setup
  --browser`), macOS, Linux. The full suite passes on Python 3.12.14 (81 passed, 1
  skipped).

## 6. Basic large-place check

Render one or two real places with tens of thousands of parts (the maintainer's own
games, kept outside the repo like the other benches), with `RHR_PROFILE=1`: time and
memory for the IR conversion, the scene dump, the page and the screenshot. Fix only
what breaks (a timeout, running out of memory, a crash). No streaming or geometry
merging unless the check shows it is needed.

**Done (2026-09-27)**, on places from the maintainer's Downloads (kept there, not in the
repo): `Heartsmm2 1.rbxl` (116k parts, 180k instances, terrain) and `+1 Speed V2!
(1).rbxl` (40k parts, a model file). Measured while a game ran on the same machine, so
times are pessimistic. Nothing crashed or timed out; what broke was the picture.

- **Stored models drawn (fixed).** The 116k place keeps 110k of its parts in
  ServerStorage (every map, at the same spot). They were drawn, fetched (3,100 assets,
  8 minutes) and framed: a view of fog. Now a place draws its world only
  (`rhr.ir.world_roots`, and `worldRoots` in scene.js), with a note; `--focus` on a
  stored model draws it. The first render took 668 s (conversion 99 s, downloads
  479 s); after the fix a render takes about 75 s once converted, and a first run
  fetches only the world's assets (not re-measured cold).
- **Framing (fixed).** A rig a plugin left in Workspace.Camera, 126k studs out, set the
  camera 160k studs away. `withoutStrays` in frameScene leaves out parts more than 4x
  the build's spread from its median, when they are under 5% of it; a note names them.
- **Conversion memory (reduced).** Lune peaked at 5.5 GB (static) / 7.0 GB (full).
  The whole-place XML pass is gone unless needed, and the IR is written node by node:
  3.9 / 5.7 GB. Output identical on 77 fixtures and 28 real files in both profiles.
  Still costly: about 100 s of the conversion is 5M property reads through Lune's
  bridge (20 us each); cutting it means reading fewer properties, left for after 1.0.
- **Also faster:** raw terrain/union reads 40x; scene-dump 22 -> 17 s warm.
- **Then made fast (same day, "optimization is the #2 priority").** A render was
  worse than opening Studio: the 22k map took 20 s to convert after every edit and 34 s
  to re-render. Measured causes: Lune hands each property to Luau in its own call (5M
  calls, ~20 us each), and each render parsed the converted file six times. Fixed:
  - `src/rhr/rbx/`: RHR's own reader for binary files, a port of rbx_binary 3.0.0 and
    of luau/rhr-ir.luau on top of the reflection database Lune 0.10.5 bundles
    (`scripts/make_reflection.py`). Columnar with numpy, lazy per property. Same IR,
    proven: 63 real binary files (benches and the maintainer's Downloads, up to 116k
    parts) and every fixture in both profiles, identical documents and reports
    (tests/test_rbx_reader.py re-saves XML fixtures as binary through Lune and compares).
    Any failure falls back to Lune with a note. Binary files no longer need Lune.
  - `rhr.ir.load_ir` keeps the parsed IR for the process (was parsed 6x per render).
  - `rhr.ir.world_ir`: a place's 3D view reads a slice with only what it draws
    (13 MB instead of 230 MB on the 116k place).
  - Results (Windows, a game running): 22k map convert 20 s -> 3.5 s, first render
    124 s -> 26 s, second 34 s -> 7 s; 116k place convert 100-230 s -> 14.5 s, first
    render 668 s -> 36 s, second 75 s -> 8 s. Pictures byte-identical.
- **Left for after 1.0:** reading XML files (`.rbxmx`) with RHR's reader too (they
  still go through Lune: usually small); the browser page's own time on big scenes
  (shader compile, in-world UI; 4-6 s); Python start-up on this machine (1-2 s).

## 7. Candidate period

A handful of the maintainer's real game files checked once against Studio, CI green on
all three systems, no open issue that would mislead an agent. Then tag 1.0 and publish
to PyPI.

**Reshaped (2026-09-27, after the maintainer asked whether 1.0 was premature).** Steps
1-6 all landed in one day and none has run anywhere but this Windows machine, and the
interface freezes at 1.0. Proposed order:

1. Push; CI green on Windows, macOS and Linux (the browser client, the fresh-install
   job and now the resident server have never run there). Publish a pre-release
   (`1.0.0rc1`) to PyPI, which exercises the install and download paths for real.
2. Hardening: the binary reader over every real file in both profiles plus damaged
   files; bad inputs (missing files, broken Rojo projects, no browser, no network);
   browser and server lifetime on Linux and macOS.
3. Use it from an agent on real projects for a while, the JSON still allowed to
   change; fix what is awkward before it freezes.
4. The Studio comparison on real games; tag 1.0 after a stretch with nothing new.

Open decisions from the performance pass (docs/performance.md, "What is left"): a
native `rhr` client, decal/part batching (pixels move), keeping the built scene for
camera-only renders, `scene-dump`'s size on big places, a Python XML reader.

## Notes for whoever picks this up

- Studio is connected through its MCP plugin for measurements; the scratch place is
  Place1. Private benches live outside the repo (`C:\Users\taboo\Desktop\Files\rhr-*-bench`,
  and the browser prototype in `C:\Users\taboo\Desktop\Files\rhr-browser-proto`); never
  commit their files. The repo is `C:\Users\taboo\Desktop\Files\roblox-headless-renderer`
  (moved there 2026-09-27; after a move, re-run `pip install -e ".[dev]"` in `.venv-win`).
- The machine has Chrome, Brave and Firefox installed for testing, no Edge; assume most
  Windows users have Edge.
- Local Python is 3.14, CI uses 3.12.
- Commits carry no Claude attribution.

## Pending for the next session (written 2026-09-27)

Start here. Agreed positioning (not yet in GOAL.md): RHR is **headless preview and
checks of Roblox files, for agents and automation**, not a Studio replacement. Studio
wins when a place is open and edited live (instant edits, exact pixels); RHR wins
where Studio cannot be driven (terminal/cloud/CI agents, Linux, Rojo repos where files
are the truth) and with structured answers (rects, findings, hit map) Studio does not
give. Unverified: what Roblox's Studio MCP returns today (screenshots? layout data?);
check before 1.0, it decides how much of RHR is unique.

1. **Scope conversation first**, then write it into GOAL.md and the README.
   - Core, must be excellent: UI check/layout/hitmap, UI pictures, 3D pictures of
     builds and models, compare, Rojo projects. Secondary: whole big places, effects,
     terrain. Out: scripts, gameplay, live editing, exact Studio pixels.
   - Open questions for the maintainer: main user is an agent in a Rojo repo, or also
     loose .rbxl files? Mac/Linux at 1.0 or Windows first? Should RHR ever edit files,
     or only look?
2. **Agent tooling** (changes the JSON interface: before the freeze): scene-dump
   summary by default (big places print tens of MB); targeted queries (what is at
   pixel X,Y; one subtree; checks for one frame); watch mode / check changed files in
   a Rojo repo; several viewports in one call; fix hints in check findings; rewrite
   AGENTS.md around real agent loops.
3. **Features:** more checks (off-screen, overlapping buttons, small tap targets,
   contrast, aspect-ratio breakage); a way to check script-built UI (agent snapshots
   the finished UI to a file); 3D gaps only where they mislead.
4. **Optimizations, ranked for the scope** (docs/performance.md, "What is left"):
   batch decals/parts (heavy scenes are GPU-bound; pixels move: decide); keep the
   built scene for camera-only renders; native `rhr` launcher (~0.3 s -> ~0.05 s per
   small command); Python XML reader; last, incremental re-reading of huge places.
5. **Then** step 7 above: pre-release + CI on three systems, hardening, a stretch of
   real agent use, freeze, tag 1.0.

Suggested order: 1, 2, 4 (first two items), 5.
