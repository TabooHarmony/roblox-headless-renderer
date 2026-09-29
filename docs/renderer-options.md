# Replacing Chromium: is it worth it?

Investigated 2026-09-25 and 2026-09-26, before planning v1. Short answer: **keep
Chromium and three.js; drop Playwright**. Drive the browser directly over the Chrome
DevTools Protocol: a Chromium-family browser already installed when there is one
(same pixels, measured below), else a pinned headless shell downloaded on first use.

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

## Option 2: the browser already installed (measured 2026-09-26: adopted, with Option 3)

A prototype DevTools client (standard library only, no Playwright) drove RHR's real 3D
page through `rhr scene` and `rhr preview` on nine scenes (a place, lighting,
materials, particles, played VFX, beams, in-world UI, the tower example, terrain
hills), on the maintainer's Windows machine. Baseline: today's Playwright path with
the pinned headless shell (Chromium 145).

| Browser | Pixels, software (tests) | Pixels, GPU (normal use) | Warm render, small scene | Launch | 22 launch cycles, 2 at once |
|---|---|---|---|---|---|
| Pinned headless shell, own client | identical | reference | ~1 s | 0.4 s | no failures, 0.8 s each |
| Chrome 154 | identical | within 1-2 shades | ~1 s | 0.8-1.0 s | no failures |
| Brave 154 | identical (1 shade, 1% of one image) | as Chrome | ~1 s | 0.6-2 s | no failures |
| Firefox 156 (WebDriver BiDi) | < 1 shade mean | within 1-2 shades | 20-30% slower | 3.3 s | 1 timeout, ~13 s to shut down |

- **Pixels do not need a pinned browser.** In software mode Chrome 154 and Brave draw
  exactly what the pinned build 145 draws. On the GPU every browser is within a shade
  or two of the others, less than the GPU-vs-software difference RHR already accepts.
- **Warm, the browsers are equally fast**; the worker pays the launch once. Driving
  the pinned shell without Playwright is itself 0.7-1 s faster per cold render.
- **Safe beside the user's own browser**: each run has its own throwaway profile and
  `--remote-debugging-port=0` (the port is read from `DevToolsActivePort`). The
  maintainer's own Brave window stayed open throughout, untouched; no window
  appeared; every profile was removed.
- **Found by the stress test, to handle in the real client:** Brave can still hold
  `DevToolsActivePort` locked when it is first read (retry); a failed start must kill
  the browser's whole process tree (one headless Brave was left running); tie every
  browser to RHR's life (a job object on Windows).
- **Firefox is not supported**: it no longer speaks CDP, so it needs a second protocol,
  and it was slow to start and stop and timed out once.
- **Studio's WebView2 is no substitute.** Studio ships no Chromium of its own; it uses
  Microsoft's WebView2 runtime (and ships its installer). `msedgewebview2.exe` started
  on its own with `--headless` exits without opening a debugging port: it only runs
  inside a host application.
- **Not measured here** (no Edge on this machine; Windows only): Edge is Chromium with
  the same flags; CI runners on all three systems have Chrome and Edge. Known
  gotchas: snap-packaged Chromium on Linux cannot use a profile under `/tmp`; Chrome
  for Testing has no Linux ARM build; a company policy can turn off remote debugging
  (then fall back to the download).

**Order:** `RHR_BROWSER` if set; the pinned shell if already downloaded; Chrome, Edge,
Brave, Chromium; otherwise download the pinned shell the first time a 3D render needs
it, with a notice (and a switch to forbid it). The output and `rhr doctor` name the
browser used.

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

Planned for 1.0, together with Option 2 (see docs/GOAL.md).
