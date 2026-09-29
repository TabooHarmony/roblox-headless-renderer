---
name: rhr
description: "Use when making or changing Roblox UI or 3D builds (ScreenGuis, stories, models, places, Rojo projects) and you need to see the result or check it for mistakes without Roblox Studio: rhr draws pictures and reports layout, findings, clicks and 3D facts as JSON."
---

# rhr: see Roblox content without Studio

`rhr` (roblox-headless-renderer) turns a Roblox file, Rojo project, UI story or asset
id into small JSON and, when you need to look, a PNG. Run it from the shell; each
command takes about a second. Full guide: `rhr --help`, and the project's
docs/AGENTS.md.

## Where the UI lives decides the target

- UI saved as files in a Rojo repo: the project folder or the file.
- UI built by code (React-lua, Fusion, ...): a story, `src/Shop.story.luau`.
- Code in Rojo, UI saved in Studio: the place file (`Game.rbxl`) or its place id.
- Screens code opens are saved closed: `--only StarterGui/Shop` draws one alone.

## The loop

1. Edit.
2. `rhr check <target>` (exit 1 = an error finding; fix errors, then warnings).
   `rhr check <target> --baseline before.json` shows only what an edit added.
3. `rhr layout <target> --path <screen>`: rects as numbers; compare with what you meant.
4. Look only when needed, small: `rhr ui <target> --only <screen> --fit --max-size 800
   --out shot.png` (`--annotate --json` numbers the buttons).
5. Before done: `rhr check <target> --devices all` (phones, tablets, consoles).

3D: `rhr scene <target> --view iso --max-size 800 --out build.png --json` (`--views
iso,front,top` for several sides on one build);
`rhr scene-dump <target>` summarises a place (`--path <model>` to drill in).
Clicks: `rhr hitmap <target> --at X,Y`. Free models: `rhr inspect <id>`.
Several commands in one call: `rhr batch check <target> + layout <target>` (one JSON).

## Rules

- Pass paths back exactly as rhr printed them (`Card[2]`, not `Card`).
- Exit 2 means it failed or had nothing to draw; stderr says why and what to try.
- Findings: `error` fix, `warning` weigh, `info` (`--min-severity info`) often intended.
- `missingAssets`, `fallbacks` and `notes` in the JSON say what was not drawn exactly.
- Stories run the project's code: never on untrusted pull requests outside a sandbox.
- No Studio on the machine (cloud, CI): ask for an Open Cloud API key and set
  `RHR_ROBLOX_API_KEY` from secrets, never in a committed file.
