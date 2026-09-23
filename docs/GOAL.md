# What RHR is for

This is the source of truth for the project's direction. If another document
disagrees with it, this one wins.

## The goal

RHR is a command-line tool that lets an AI agent **see** the Roblox UI and 3D builds
it is making, without Roblox Studio open. The agent points it at a file and gets a
preview image plus numbers: where things are, how big they are, what overlaps, what
is clickable, and what looks broken.

- **Who it is for:** Roblox developers and their agents. It is meant to be a public
  tool, so it has to install and run on other people's machines, Windows included.
- **What it covers:** UI (ScreenGuis) and 3D builds equally, including one combined
  "whole scene" preview.
- **Accuracy bar:** a *useful preview*. Roughly right is fine. It has to catch
  obvious mistakes and must never be **silently** wrong: anything it cannot draw
  faithfully is reported in its output. Matching Studio pixel for pixel is not a goal.
- **Interface:** the CLI (`rhr`) comes first. The MCP server is a thin wrapper
  over the same commands.
- **Inputs:** `.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx` files, and Rojo projects (built
  with `rojo build`).
- **Studio's role:** occasional spot-checks by the maintainer to confirm previews are
  roughly right. Studio is never needed to *use* the tool.

## What it is not

- Not a Roblox engine: it does not run scripts, physics or gameplay.
- Not a Studio companion: there is no live connection to a running Studio. That
  would defeat the point of a headless tool.
- Not a pixel-perfect replica of Studio's renderer.

## Feature status

| Feature | Commands | Status |
| --- | --- | --- |
| UI preview | `render` | Core (layout by RHR's own pass, checked against Studio) |
| UI layout numbers, build checks, clickable regions | `layout`, `check`, `hitmap` | Core |
| 3D preview and camera controls | `scene` | Core (needs reliability work) |
| 3D geometry as JSON | `scene-dump` | Core |
| Combined world + UI preview | `preview` | Core |
| Before/after comparison | `compare` | Core |
| ViewportFrame | inside `render` | Core (slow) |
| BillboardGui / SurfaceGui | inside `scene` / `preview` | Core (drawn by the UI renderer; placement approximated) |
| Particles, Beams, Trails, Sky, Atmosphere, shadows, MeshParts | `particles`, `scene`, `preview` | **Experimental**: rough approximations |
| MCP server | `rhr-mcp` | Thin wrapper |

## Path to v1

1. **One source of truth:** this document, and a README that matches it.
2. **Tests you can trust:** pytest, with CI green on clean Ubuntu and Windows
   runners, not just the development machine.
3. **Installs and runs anywhere:** `pip install` gives an `rhr` command, with clear
   errors when `lune` or Chromium are missing, and Windows support.
4. **Never silently wrong:** stable per-instance IDs instead of name lookups,
   duplicate-name paths disambiguated, the `Model.Scale` behaviour verified in
   Studio, in-world UI drawn with the same renderer as ScreenGuis, and experimental
   and approximated output flagged in the JSON.
5. **Studio spot-check:** a handful of fixtures made in Studio, checked for
   "roughly right" positions and sizes, not pixel identity.
6. **Rojo input and release polish:** Rojo projects, a supported-feature table, a
   usage guide for agents, and versioned JSON output. (Third-party game files were
   removed from the test data on 2026-09-22.)

**After v1:** terrain, unions/CSG, better visual fidelity.

## Rules for new work

- A feature is worth adding when it helps an agent's edit → preview → fix loop.
- "Done" means the tests pass in CI on a clean machine, not only on the machine
  where the work was written.
- Anything approximated or skipped is reported in the output, and listed in
  `docs/known-approximations.md`.
