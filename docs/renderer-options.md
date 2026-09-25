# Replacing Chromium: is it worth it?

Investigated 2026-09-25, before planning v1. Short answer: **keep Chromium and
three.js; drop Playwright**. Drive Chromium's headless shell directly over the Chrome
DevTools Protocol, and download a pinned build of it in `rhr setup`.

## What Chromium costs RHR today

Measured on the maintainer's Windows machine (AMD RX 6800):

| Cost | Size or time |
|---|---|
| Chromium headless shell (what RHR launches) | 259 MB on disk |
| Playwright Python package | 104 MB, of which 86 MB is a bundled Node.js |
| Cold start: Playwright's Node driver | about 0.7 s |
| Cold start: Chromium launch through Playwright | about 0.1 s |
| Cold start: the headless shell started directly | 0.3-0.5 s |
| Per warm render, since the worker keeps the page loaded | ~0.1 s of browser overhead (new render call, screenshot 0.2 s) |

Speed is no longer the problem: with the kept page, Chromium adds little per render.
What is left is **weight** (about 360 MB) and **moving parts** (a Node process, local
HTTP servers, CORS between them).

## Option 1: a native renderer (wgpu-py + pygfx)

pygfx is a three.js-style scene library on wgpu-py (WebGPU on Vulkan, Metal or
DirectX 12). Tried in a throwaway environment:

- **Size**: wgpu 11 MB and pygfx 6.5 MB (numpy is already a dependency). About 25 MB
  instead of 360.
- **Adapters found here**: the GPU (Vulkan, D3D12, OpenGL), plus a **software** adapter
  (Microsoft's WARP, D3D12), the counterpart of today's SwiftShader.
- **Speed**, offscreen at 1615x1080 with 2,000 cubes:

  | | GPU | Software (WARP) |
  |---|---|---|
  | Building the scene | 3.9 s | 3.8 s |
  | First frame (pipelines and shaders compiled) | 3.1 s | 4.2 s |
  | Later frames | 0.03 s | 1.0 s |

  Compiled pipelines are not kept between processes, as Chromium's shader cache does,
  so it would need a warm worker too. That part of the design would not get simpler.
- **Cost of switching**: the 3D page (scene.js, about 4,000 lines) would be rewritten in
  Python and WGSL. That includes terrain, particles and their fitted blend, Highlights
  (stencil), the HDR composite, Neon glow, cascaded shadows, fog, the sky-visibility
  grid and in-world UI. **Every calibration against Studio would be redone**: the
  lighting fit, the VFX blend fit and the material work are all fitted to what three.js
  draws.
- **Tests would lose identical pixels across machines.** Today all three CI systems draw
  with SwiftShader, bit for bit alike. With wgpu, Windows uses WARP, Linux lavapipe
  (Mesa), and macOS has no software adapter at all, so each system would need its own
  baselines or tolerances.

Verdict: weeks of work and a full re-calibration, to save disk space. Not worth it
before 1.0. It is worth revisiting only if the Chromium dependency itself becomes a
blocker (a platform it cannot run on, or a user base that will not install it).

## Option 2: the system browser (Edge or Chrome already installed)

It would need no download, but it cannot be relied on: **neither is installed on the
maintainer's Windows machine**. Its version would also float, changing pixels between
users. It could be kept as an optional speed-up, never as the default.

## Option 3 (recommended): Chromium without Playwright

Keep the headless shell and three.js. Replace Playwright with a small Chrome DevTools
Protocol client that RHR owns: launch the shell with `--remote-debugging-pipe` (or a
port), then use `Target.createTarget`, `Page.navigate`, `Runtime.evaluate`,
`Emulation.setDeviceMetricsOverride`, `Page.captureScreenshot` and the console and
exception events. That is about everything RHR uses Playwright for today.
`rhr setup` downloads a pinned **Chrome for Testing** headless shell (the same build
family Playwright uses), so tests still draw identical pixels.

- Saves 104 MB and a Node process, and about 0.4 s on every cold start.
- Removes the Playwright pin; the Chromium version is pinned by RHR itself.
- Keeps every calibration and the identical-pixels CI.
- About a week of work, with low risk: same browser, same page, same pixels, and the
  current tests compare them.

Planned for the v1 contract milestone (see docs/GOAL.md).
