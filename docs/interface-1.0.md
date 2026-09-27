# The 1.0 interface: review

What RHR promises from 1.0 on, and what changes before then. After 1.0, anything
listed as **contract** here changes only in a major version; everything else may change
in any release. Status: **proposal, 2026-09-26**, for the maintainer to decide. Items
marked **Decide** need an answer; the rest are proposed as written.

Taken from the code as of v0.7.0 (argparse, `rhr.schema.VERSIONS`, real outputs on the
test fixtures).

## Rules for the whole interface

1. **JSON is the contract; pictures and stderr are not.** A PNG may change in any
   minor version to get closer to Studio. Text on stderr is for people and may change
   any time. Every fact an agent needs (fallbacks, missing assets, particles drawn,
   which browser drew it) is also available as JSON.
2. **Two kinds of command.** *Data* commands (`layout`, `check`, `hitmap`,
   `scene-dump`, `compare`) print one JSON document to stdout, or write it with
   `--out`. *Picture* commands (`ui`, `scene`, `preview`) print the PNG's path on
   stdout; with `--json` they print a JSON report instead (the path, the size, the
   notes, the browser used, the camera). Today `compare` prints text unless `--json`
   is given, and picture commands have no JSON report at all.
3. **Exit codes:** 0 success; 1 only from `check`, meaning error-class findings; 2 the
   command failed (bad arguments, unreadable file, render error). Today three internal
   error paths in the UI commands return 1, which an agent would read as "check found
   errors"; they become 2.
4. **JSON style:** camelCase keys everywhere, every document stamped
   `"schema": "rhr.<kind>/<n>"`, adding a field never changes `<n>`, renaming or
   removing one does. Today `compare` uses snake_case (`changed_pct`, `diff_bbox`):
   renamed, so it becomes `rhr.compare/2`.
5. **Paths:** one format everywhere, `Model/Child/Grandchild`, the same in `layout`,
   `hitmap`, `scene-dump` and `--focus` (checked: it already is). Contract.
6. **Units:** UI rects in pixels `{x, y, w, h}` from the viewport's top-left; 3D
   positions and sizes in studs as `[x, y, z]`, orientations in degrees. Contract.

## Commands

| Now | Proposal | Why |
|---|---|---|
| `render` (UI to PNG) | **Decide:** rename to `ui` | `render` sounds like "draw anything", but it draws only the ScreenGuis. `ui` / `scene` / `preview` says what each draws. No alias: few users before 1.0, and the upgrade note covers it. |
| `scene` (3D to PNG) | keep | |
| `preview` (3D + UI) | keep | The one to reach for when unsure; docs/AGENTS.md says so. |
| `layout` | keep | |
| `layout --rich` | keep; fix its help text (it says "Task 2.1") | |
| `check` | keep | |
| `hitmap` | keep | |
| `scene-dump` | keep | |
| `compare` | keep; JSON by default (rule 2), `--json` becomes a hidden no-op for one release | |
| `fetch` | keep | |
| `setup` | keep, now optional: pre-downloads Lune, Rojo and, with `--browser`, the pinned browser (for CI and offline machines) | No longer a required step. |
| `doctor` | keep; names the browser RHR would use | |
| `cache` | keep | |
| `browser start/status/stop` | keep as advanced | The warm worker starts by itself; this is for scripts that want control. |
| `ir` | keep, but **not contract**: its JSON may change in any release | It is RHR's internal format; agents should use `scene-dump`/`layout`. |
| `particles` (contact sheet) | **Decide:** remove (move to `scripts/`) | A calibration tool; `--effect-time` covers "show another moment". Not used by any test. |

## Flags to remove or change

- **Remove hidden leftovers:** `scene --shadows`, `preview --shadows` (on by
  default), `scene --coverage` (a no-op), `preview --time` (old name of
  `--effect-time`), `fetch --use-studio-login` (the default), `particles --burst`.
- **`--ir PATH`** (on `render`, `layout`, `hitmap`, `scene`, `scene-dump`, `preview`,
  `particles`): **Decide:** remove. It saves the internal IR next to the output, a
  debugging aid; `rhr ir` does the same, and the IR is not contract.
- **`--texture-dir`, `--mesh-dir`**: keep working (the tests use them) but hide from
  `--help` and leave out of the contract. They are test hooks.
- **`--no-effects`**: leaves out only particles today; make it leave out Beams and
  Trails too, as its name says.
- **`--offline`**: stays on the commands that download before drawing (`ui`,
  `scene`, `preview`). The data commands never download, so they do not need it.
- **`render --dump-layout`**: keep (one run gives the picture and the numbers).
- **Defaults kept as contract:** `--viewport 1615x1080`, `--topbar-height 58`, shadows
  on, effects on at their fullest moment, `--seed 0`.

## JSON outputs

| Schema | Today | Proposal |
|---|---|---|
| `rhr.layout/1` | `{viewport, rects: {path: {x,y,w,h}}}` | keep |
| `rhr.layout-rich/1` | `{model, viewport, nodes: [{path, class, rect, zIndex, paintOrder, visible, clipsDescendants, background, gradient, strokes, ...}]}` | keep |
| `rhr.check/1` | `{model, findings: [{check, severity, path(s), detail}]}` | keep; list every `check` id in docs/AGENTS.md as contract (new checks may be added) |
| `rhr.hitmap/1` | `{model, viewport, panes, nodes, hitTests}` | keep |
| `rhr.scene-dump/1` | `{source, bounds, parts, cameras, lights, beams, trails, terrain, lighting, sky, atmosphere, fallbacks, unsupportedVisualClasses, experimental, ...}` | keep; **drop `experimental`** (always `{}` since 0.6) |
| `rhr.compare/1` | snake_case keys | `rhr.compare/2`, camelCase |
| `rhr.browser/1` | `{running}` | keep; add the browser used |
| new: `rhr.render/1` | none | the `--json` report of `ui`, `scene`, `preview` (rule 2) |
| `rhr.ir/1` | internal format | not contract |

Each kept schema gets a shape test: a fixture's output checked key by key, so a
renamed or dropped field fails the suite.

## Environment variables

| Variable | Proposal |
|---|---|
| `RHR_OFFLINE`, `RHR_CACHE_DIR`, `RHR_CACHE_LIMIT_MB`, `RHR_WEBGL`, `RHR_PERSISTENT_BROWSER`, `RHR_BROWSER_IDLE_S`, `RHR_PROFILE`, `RHR_STUDIO_DIR` | contract, documented in the README |
| `RHR_CHROME` | becomes **`RHR_BROWSER`** (any Chromium-family browser); `RHR_CHROME` still read for one release |
| new: `RHR_BROWSER_DOWNLOAD=0` | never download a browser; fail with a clear message instead |
| `RHR_ROBLOX_FONTS`, `RHR_SYSTEM_FONT_FALLBACK` | test switches: work, not contract |
| `RHR_SCENE_TUNE`, `RHR_EFFECTS_UNDER`, `RHR_TABLE_Y_SCALE*`, `RHR_TABLE_NODRAW_*` | calibration hooks: not contract; `RHR_TABLE_*` removed with the pinevex fork unless still used |
| `RHR_MCP_WORKER` | removed with the MCP server |
| `RHR_NEEDS_FRESH_PAGE` | not a variable: an internal error marker |

## Decisions needed

1. Rename `render` to `ui`?
2. Remove the `particles` command?
3. Remove `--ir` from the render and data commands?
4. Picture commands' `--json` report (`rhr.render/1`): add it? (Proposed: yes; it is
   how the notes become contract instead of stderr text.)
