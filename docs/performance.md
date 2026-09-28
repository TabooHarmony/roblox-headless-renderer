# Performance

RHR runs inside an agent's edit loop: edit a file, `check` it, `layout` it, draw it,
`compare`, again. Every second a command takes is paid on every turn of that loop, so
speed is the second priority after not misleading the agent (docs/GOAL.md). This page
is how RHR is built to be fast, and how to keep it that way.

## Rules

1. **Work in proportion to what the command needs**, never to the size of the file or
   of the cache. A UI command on a 100k-part place reads the UI; a render of a small
   model does not list every asset ever downloaded.
2. **Do each thing once per version of the file.** Facts about a loaded file (which
   branches hold UI, the assets a scene uses, inline unions) are kept while it is
   loaded (`rhr.ir.derived`); the converted file is cached by content; folder listings
   by folder mtime (`rhr.listing`).
3. **Keep what is expensive to start warm**: the Python process with its imports and
   the loaded file (the resident server), the browser with its page, compiled shaders
   and decoded textures (the warm browser worker).
4. **Output for agents**: compact JSON (whitespace costs time and tokens), no side
   files nobody reads (`layout` used to write a PNG it never showed).
5. **Same answers.** A speed change must not change any output: compare the JSON
   documents and PNG bytes over the fixtures and real files before and after (the
   equivalence runs below). A change that does move pixels is a separate decision.

## How a command runs

```
rhr (rhr.client) ──socket──> rhr.server (resident) ──> rhr.cli.main
   imports os, sys,             modules imported, IR loaded,
   socket, json only            derived facts kept
                                        │ 3D
                                        ▼
                                rhr.browser_daemon (warm worker) ──CDP──> kept page
                                                                          (scene.js)
```

- **rhr.client** is the `rhr` command. It forwards argv, the working folder and the
  per-request settings (RHR_PROFILE, RHR_OFFLINE, colour switches) and writes back
  stdout, stderr and the exit code. The command runs in the client's own process
  instead when the server is busy, cannot start, or RHR_SERVER=0.
- **rhr.server** runs one command at a time with everything warm. One server per
  Python, copy of RHR and RHR_* configuration; it replaces itself when RHR's code
  changes and exits after 20 idle minutes (RHR_SERVER_IDLE_S).
- **Conversion profiles** (rhr.rbx for binary files; XML files still go through Lune
  and read in full):

  | profile | used by | keeps |
  | --- | --- | --- |
  | `ui` | ui, layout, check, hitmap | GUI subtrees in full; what holds them by path only |
  | `world` | scene, preview | the world's visual classes; of storage only stored ScreenGuis (stubs) and a note of what it holds |
  | `static` | scene/preview with --focus or --all-guis | visual classes everywhere |
  | `full` | scene-dump, ir, fetch | everything |

## Measuring

`scripts/bench.py` runs `rhr` commands as an agent does, one process per command,
interleaved, and reports medians: `warm` (the file unchanged since the last command)
and `edit` (a changed file, converted again). The maintainer's machine is rarely idle
(a game is often running), so compare runs made the same way, interleaved, and read
ratios rather than absolute times.

```
python scripts/bench.py --place big.rbxl --json after.json
python scripts/bench.py --compare before.json after.json
```

`RHR_PROFILE=1` prints where one command's time went, including the page's steps.

## Where it stands (2026-09-27)

The performance pass that set up this design, measured with `scripts/bench.py` on the
maintainer's Windows machine while a game ran (so read the ratios): medians of 3
interleaved runs, one process per command, before the pass and after it (the resident
server on; `+1 Speed V2` is a 40k-instance model, `Heartsmm2` a 116k-part place).

| command | file | warm before | warm after | after an edit, before | after |
| --- | --- | ---: | ---: | ---: | ---: |
| check | shop.rbxmx (UI) | 1.30 s | 0.35 s | 1.78 s | 0.32 s |
| layout | CRATES GUI.rbxm | 2.06 s | 0.48 s | 2.05 s | 0.24 s |
| ui | ui_edge_cases.rbxlx | 1.23 s | 0.42 s | 1.56 s | 0.43 s |
| scene | tower.rbxmx (3D) | 4.43 s | 0.94 s | 4.87 s | 0.79 s |
| layout | +1 Speed V2 | 67.8 s | 1.15 s | 66.6 s | 2.50 s |
| check | +1 Speed V2 | 64.2 s | 1.07 s | 71.2 s | 1.60 s |
| scene | +1 Speed V2 | 38.1 s | 36.7 s | 70.9 s | 24.2 s |
| layout | Heartsmm2 | 29.0 s | 4.72 s | 56.5 s | 10.8 s |
| scene | Heartsmm2 | 13.4 s | 7.99 s | 45.1 s | 14.1 s |
| scene-dump | Heartsmm2 | 33.9 s | 23.3 s | 46.8 s | 22.7 s |

Made after that run: a place's UI commands no longer convert the UI of services
they do not draw (warm `layout` on Heartsmm2 2.6 s -> ~0.3 s in the server), and
post-processing compiles once per page instead of every frame (12 renders of 6
places: 258 s -> 154 s). In-process, `layout`/`check`/`hitmap` over 99 files went
from 623 s to 29 s with every output unchanged.

What is left, largest first:

- **Heavy 3D scenes are GPU-bound.** `+1 Speed V2` draws 10,099 Decals, each its own
  mesh and material, in every pass of every frame. Batching decals (and parts) that
  share a texture would cut draw calls by orders of magnitude, but changes the order
  transparent surfaces blend in, so pixels move: a separate decision.
- **Process start is most of a small command.** The server answers `check` on a
  small UI in ~45 ms; starting Python and pip's `rhr.exe` launcher cost 150-200 ms
  (much more when the machine is loaded). Only a native client (a few-KB executable
  that talks to the server) would remove that.
- **A 3D render of an unchanged file rebuilds the scene.** Keeping the built scene on
  the warm page when only the camera changes (another `--view`) would make those
  renders a camera move and a frame.
- **The full conversion** (`scene-dump`, `ir`) of a 116k-part place is ~20 s after an
  edit, and its JSON is ~240 MB; `scene-dump` on such a place prints every part.
- **XML files** still convert through Lune (kept running in the server, ~55 ms for a
  small model); a Python reader like the binary one would make them as fast.
