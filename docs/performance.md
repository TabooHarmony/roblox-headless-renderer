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
