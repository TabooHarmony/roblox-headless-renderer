# What RHR is for

This is the source of truth for the project's direction. If another document
disagrees with it, this one wins. The step-by-step plan to 1.0 is
docs/road-to-1.0.md (agreed 2026-09-28); the history of earlier roadmaps is in the
CHANGELOG and in this file's git history.

## The goal

RHR lets an agent **see** Roblox content without Studio: headless, parallel, on any
OS, with the numbers behind the picture. Point it at a model, a place, a Rojo
project, a UI story or an asset id, and in about a second get pictures and facts:
where every UI element is, what is clickable, what looks broken, where every part
is, and what was approximated. Built for agents and automation; just as useful for a
person who wants a quick look without Studio's 20-30 s start.

Speed and size are part of the product: RHR runs inside an agent's edit loop, so every
second and every kilobyte of output is paid on every command.

Next to Roblox Studio's own MCP server (screenshots and live Luau in a running Studio
with the place open, one Studio shared by every agent), RHR is what works without
Studio: in CI, on Linux, in cloud sandboxes, many at once, with the file as the source
of truth and structured findings rather than only pixels.

## Who it serves

- **Agents in Rojo repos**: UI saved as files, or built by React-lua / Fusion code
  (stories); 3D builds as models.
- **Agents in partially managed repos**: code in git, UI and maps saved in Studio.
  RHR works from the place file or its id.
- **Cloud and CI agents** (Linux, no Studio), with an Open Cloud API key.
- **Teams reviewing changes**, asset pipelines (icons), anyone vetting a Creator Store
  model before inserting it, and people without Studio open.

## Scope

- **Inputs:** `.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx`; Rojo projects (built with
  `rojo build`); UI stories (`*.story.luau`, run in their Rojo project); asset ids and
  Creator Store, library, catalog and game links.
- **Interface:** the `rhr` command line only, with docs/AGENTS.md as the agent's
  guide. No MCP server (decided 2026-09-26): an MCP server's tool descriptions cost
  context on every turn; a command costs nothing until it runs.
- **Platforms:** Windows and macOS first class (macOS once a real Mac run is written
  up); Linux tested in CI and supported for cloud agents.
- **Assets, in order:** the Studio login on the machine (most users); an Open Cloud
  API key (`RHR_ROBLOX_API_KEY`); what Roblox serves without either; honest
  stand-ins. Nothing from Roblox ships in RHR.
- **Accuracy bar:** a useful preview. UI layout is measured against Studio (within
  2 px); 3D pictures are close approximations. RHR must never be **silently** wrong:
  anything it could not draw faithfully is reported in its output.

## What it is not

- Not an editor: RHR looks and never changes a file (not in 1.0).
- Not a Roblox engine: no physics, gameplay or animation playback. The one input
  where RHR runs code is a story, which it runs to see the UI the code builds.
- Not a Studio companion: no live connection to a running Studio. Reading the
  install's files and its saved login is not one; Studio need not be running.
- Not a pixel-perfect copy of Studio's renderer.

## Feature status

| Feature | Commands | Status |
| --- | --- | --- |
| UI picture, layout numbers, findings, clickable regions | `ui`, `layout`, `check`, `hitmap` | Core (layout within 2 px of Studio; findings being tuned for precision in Phase 1) |
| UI built by code | stories through the UI commands | **Experimental in 1.0** |
| 3D picture, camera controls | `scene` | Core |
| 3D facts | `scene-dump` | Core (output size reworked before 1.0) |
| World, in-world UI and screen UI together | `preview` | Core |
| Roblox materials, sky, surfaces, unions, terrain, characters | `scene`, `preview` | Core (checked side by side with Studio) |
| Particles, Beams, Trails, Atmosphere, lights | `scene`, `preview` | Approximate, one still frame |
| Before/after comparison | `compare` | Core |
| A page to fly around a build | `view` | Core, for people |
| Icons for many models | `icons` | Core |
| What a file holds; risky script code | `inspect` | Core ("reasons to look": pattern matching) |

## Road to 1.0 (agreed 2026-09-28)

Detail, findings and numbers: docs/road-to-1.0.md. In short:

0. **Clean slate:** finish stories, cache and memory hygiene, security hardening,
   these docs; push, CI on three systems, publish **0.9.0b1** to PyPI.
1. **Never silently wrong:** no command exits 0 with an empty result; UI screens that
   code opens can be shown (`--show`, `--only`); checks at least 95% right on a
   reviewed corpus of real games.
2. **Output an agent can use:** every default JSON within a size budget
   (`scene-dump` a summary by default), `--device` and a 1920x1080 default viewport,
   `hitmap --at`, AGENTS.md and a `SKILL.md`. Then **1.0.0rc1**.
3. **Speed the agent feels:** a native `rhr` client, `rhr batch`, several views of
   one built scene.
4. **Dogfood and freeze:** daily use from agents on real projects, the Studio
   side-by-side, a real Mac and a cloud agent; then **1.0.0**.

**Decided 2026-09-28:** `--view front` means Roblox's Front (-Z), and with `--focus`
the model's own front; findings gain an `info` severity; nothing to draw exits 2 with
a hint; hit map semantics follow a Studio measurement; the native client ships in 1.0
if CI is green.

**The ordering rule:** anything that changes JSON shapes, defaults, flag meanings or
exit codes happens before the freeze. Anything additive or internal can land after
1.0 without breaking anyone.

**After 1.0:** visual regression of stories in CI, a structural diff of Roblox files
(also as a `git diff` driver), place versions, pseudo-localisation; later a compact
IR, instanced geometry for huge places, glTF export, animated effects. A native
renderer only if Chromium ever blocks a platform.

## Standing decisions

- **Chromium stays**, with three.js, driven by RHR's own DevTools client (no
  Playwright). A browser already installed is used; the pinned headless shell is
  downloaded only when none is found. A native renderer was investigated and is not
  worth it (docs/renderer-options.md).
- **The UI engine is RHR's own code** (a fork of pinevex-renderer).
- **A resident server** runs commands so Python and loaded files stay warm; the
  native client comes in Phase 3.
- **No pushes, CI runs or releases until the maintainer agrees**, each time. Work
  lands as local commits on `main`.

## Rules for new work

- A feature is worth adding when it helps an agent (or a person) see and check what
  they are making, quickly and cheaply.
- "Done" means the tests pass in CI on a clean machine, not only where the work was
  written, and wall-clock times were measured on small and big files.
- Anything approximated or skipped is reported in the output and listed in
  docs/known-approximations.md.
- Output sizes matter: a default output must fit an agent's context.
