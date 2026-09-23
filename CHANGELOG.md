# Changelog

## 0.1.0 (alpha)

The first public release.

### What's in it

- **Screen UI:** `render` (PNG), `layout` (every element's rectangle, `--rich` for
  what each element is made of), `check` (common mistakes as findings), `hitmap`
  (clickable regions and what is on top). RHR does its own UI layout. It matches
  rectangles that Studio recorded within 2 px on every test place: lists, grids,
  tables, flex, UIScale, constraints, auto-size, scrolling. Text is sized the way
  Roblox sizes it (`TextSize` is the line height).
- **3D:** `scene` (PNG, with standard views, `--focus` and free cameras),
  `scene-dump` (part geometry as JSON) and `preview` (world, in-world UI and screen UI
  in one image). BillboardGui and SurfaceGui use the same UI engine as screen UI.
  Part geometry matches Studio; lighting and materials are approximations.
- **Inputs:** `.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx` and Rojo projects.
- **Never silently wrong:** each instance has a stable id and a unique path
  (`Card[1]`, `Card[2]`). Approximated or unsupported features are reported in the
  output. Every JSON document names its schema version.
- **Setup:** `pip install`, then `rhr setup` downloads Lune, Rojo and Chromium, and
  `rhr doctor` checks them. Runs on Windows, macOS and Linux.
- **Agents:** a usage guide (`docs/AGENTS.md`) and an MCP server (`rhr-mcp`).
- **Examples:** `examples/shop.rbxmx` and `examples/tower.rbxmx`.

### Experimental

Materials, lights, shadows, Sky, Atmosphere, Decals and Textures, MeshParts (from a
local cache), Beams, Trails and ParticleEmitters. They are rough approximations and
labelled as experimental in the output.

### Known limits

See [`docs/known-approximations.md`](docs/known-approximations.md). The main ones:
no Terrain or union geometry, no material textures, images and meshes only from a
local cache, and no scripts, physics or animation.
