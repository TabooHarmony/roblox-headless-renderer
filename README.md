<h1 align="center">roblox-headless-renderer</h1>

<p align="center">
  <b>See Roblox files without opening Studio.</b><br>
  Pictures and plain facts about your UI and 3D builds, in about a second, from the command line.
</p>

<p align="center">
  <a href="https://pypi.org/project/roblox-headless-renderer/"><img src="https://img.shields.io/pypi/v/roblox-headless-renderer?include_prereleases&label=pypi" alt="PyPI version"></a>
  <a href="https://github.com/TabooHarmony/roblox-headless-renderer/actions/workflows/ci.yml"><img src="https://github.com/TabooHarmony/roblox-headless-renderer/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Windows, macOS, Linux">
  <a href="https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

<p align="center">
  <img src="docs/images/hero.png" width="80%" alt="Speed banner: Roblox Studio takes 11.8 s from launch until the scene is drawn, rhr preview takes 4.5 s on a first run (3.6 s after that), 2.6 times faster. Studio needs to be open and logged in, with an MCP server for agents; rhr is one command with no Studio or MCP, runs on Windows, macOS, Linux and CI, and returns PNG and JSON for scripts and agents. Below it, one scene split down the middle: the left half is a Roblox Studio screenshot, the right half is rhr preview of the same file from the same camera: a purple explosion effect over two studded shops, a loud sample shop UI with image cards, and two rigs under Shop signs">
</p>

---

Point `rhr` at a Roblox file (`.rbxm`, `.rbxmx`, `.rbxl`, `.rbxlx`), a Rojo project, a UI
story or a Creator Store link, and it tells you what's there: **a PNG to look at, and JSON
that says where everything is, what's clickable, and what looks broken.**

It was built for **AI agents** that make Roblox games and need to check their own work,
and it's just as handy when **you** want a quick look at a file, a free model or a pull
request without starting Studio. It runs on Windows, macOS and Linux, including CI and
cloud sandboxes: no display, GPU or running Studio needed.

## Quick start

```sh
uv tool install roblox-headless-renderer     # or: pip install --pre roblox-headless-renderer
```

Then, on any file of yours:

```sh
rhr ui     MyGame.rbxl --out ui.png          # the screen UI, as a PNG
rhr scene  MyGame.rbxl --out world.png       # the 3D world, as a PNG
rhr check  MyGame.rbxl                       # UI mistakes a player would notice
```

That's it: no setup step. The first run fetches anything missing (see
[what gets downloaded](#details)). Just want to try it once? `uvx roblox-headless-renderer ui MyGui.rbxmx --out gui.png`
runs it without installing anything.

> **This is the 1.0 release candidate.** It's fast and ready to use, and we'd love your
> feedback before the final 1.0: [open an issue](https://github.com/TabooHarmony/roblox-headless-renderer/issues),
> ideally with a small file that shows the problem.

## What it can tell you

| You want to know… | Run |
| --- | --- |
| What does my UI look like? | `rhr ui game.rbxl --out ui.png` |
| …just the shop screen, cropped? | `rhr ui game.rbxl --only StarterGui/Shop --fit --out shop.png` |
| …on a phone? | `rhr ui game.rbxl --device phone --out phone.png` |
| Is anything broken? Text spilling out, buttons off screen, unreadable colours? | `rhr check game.rbxl` |
| Where exactly is every element? | `rhr layout game.rbxl` |
| What gets clicked at this pixel? | `rhr hitmap game.rbxl --at 960,540` |
| What does my build look like? | `rhr scene game.rbxl --view iso --out build.png` |
| …from several sides at once? | `rhr scene game.rbxl --views iso,front,top --out build.png` |
| The world, in-world UI and screen UI together? | `rhr preview game.rbxl --out frame.png` |
| Can I fly around it? | `rhr view game.rbxl` (opens a page that redraws when the file changes) |
| Is this free model safe to insert? | `rhr inspect <asset id or link>` (flags backdoors, `loadstring`, webhooks…) |
| Icons for a folder of pets or items? | `rhr icons models/ --out-dir icons` |
| UI built with React-lua, Fusion or plain Luau? | `rhr ui src/Shop.story.luau` (any UI Labs, Hoarcekat or Flipbook story) |

Anywhere a file goes, you can also pass a **Rojo project** folder or a **Roblox asset id
or link**. `rhr --help` and `rhr <command> --help` list every option.

### An example

The repo's [`examples/shop.rbxmx`](https://github.com/TabooHarmony/roblox-headless-renderer/tree/main/examples/)
has one deliberate mistake. `rhr check examples/shop.rbxmx` finds it:

```json
{
  "check": "text-wider-than-box",
  "detail": "text is 413px wide in a 148px box with TextWrapped off: it spills out",
  "paths": ["ShopGui/Shop/Items/Item5/ItemName"],
  "severity": "warning"
}
```

## For AI agents

`rhr` is a plain command-line tool: an agent runs it from its shell, and it costs nothing
in the agent's context until it's used. Every JSON output is small, carries a `schema`
name, and uses the same paths you pass back in.

**Claude Code and Codex:** install the skill, and the agent knows when and how to use it.

```sh
rhr skill --install .claude/skills      # this project; ~/.claude/skills for all of them
```

**Any other agent:** paste this into your project's `AGENTS.md`.

```markdown
## Seeing the UI and builds
Use `rhr` (roblox-headless-renderer) to check Roblox UI and 3D work without Studio:
`rhr check <target>` after each edit (exit 1 = error findings; `--baseline before.json`
for only what the edit added), `rhr layout <target> --path <screen>` for rects,
`rhr ui <target> --only <screen> --fit --max-size 800 --out shot.png` to look, and
`rhr check <target> --devices all` before done. The target is the project, a
`*.story.luau`, or the place file when the UI is saved in Studio. `rhr skill` prints
the full guide.
```

The full agent guide, with which command answers which question and how far to trust
each one, is [`docs/AGENTS.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/AGENTS.md).

## How accurate is it?

- **UI layout matches Studio.** Positions and sizes are within 2 px of Studio's on every test place.
- **Pictures are previews.** They're close enough to spot mistakes, not a pixel copy of
  Roblox. Anything `rhr` can't draw faithfully, it **says so** in its output instead of
  guessing quietly. Here's [what's approximated](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/known-approximations.md).
- **It doesn't run your game.** Scripts, physics and animation don't run, so you see
  files as they're saved. (Effects are the exception: `rhr` plays common VFX setups
  itself and shows them at their fullest moment.)

## Details

<details>
<summary><b>Setup details: what gets downloaded, and the Studio login</b></summary>

<br>

You need **Python 3.12+**. The first command that needs one of these downloads it once
into `rhr`'s cache and says so:

- **Lune** (reads XML files and fetches assets) and **Rojo** (for Rojo projects). Copies
  already on your `PATH` are used first.
- **A browser for 3D.** `rhr` uses the Chrome, Edge, Brave or Chromium you already have,
  or downloads a small headless one (about 100 MB).

`rhr setup` fetches the tools ahead of time (`--browser` for the browser too), and
`rhr doctor` shows what was found. `--offline` or `RHR_OFFLINE=1` never downloads anything.

**Studio login.** If Roblox Studio is installed and signed in (it doesn't have to be
running), `rhr` uses it to download the meshes, images and material textures a file
needs, the same way Studio does. Your login never leaves the machine except to Roblox,
and `rhr` never prints or stores it.

**No Studio** (CI, a cloud agent)? Set `RHR_ROBLOX_API_KEY` to an Open Cloud *user* key
with the `legacy-asset:manage` permission. With neither, everything still works; some
meshes become boxes and materials use look-alike textures, and `rhr` tells you.

**Bare Linux** needs a few system libraries. On Ubuntu:
`libegl1 libgl1`, plus for the downloaded browser `libnss3 libatk-bridge2.0-0t64 libgbm1
libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libcups2t64 libasound2t64 libpango-1.0-0`.

</details>

<details>
<summary><b>Good to know: closed screens, place files, stories and more</b></summary>

<br>

- **Screens your code opens.** UI is drawn as saved, so a shop that starts hidden isn't
  drawn. `--show <path>` opens one, and `--only <path>` draws it alone.
- **Place files.** Only StarterGui's screens are drawn; templates kept in
  ReplicatedStorage are listed, and `--all-guis` draws them too.
- **The top bar.** UI is laid out below Roblox's 58 px top bar, as in a running game.
  `--topbar-height 0` matches Studio's edit view.
- **Stories run your code**, with your project's modules. That's fine for your own
  project; don't run stories from untrusted pull requests in CI outside a sandbox.
- **Rojo projects that only map code** hold no UI; point `rhr` at the place file instead.
  The error says so.
- **Exit codes:** `0` done, `1` only from `check` (error findings), `2` failed or had
  nothing to draw, with the reason on stderr.
- **Cache:** everything goes to one folder, kept under 2 GB. `rhr cache` shows it,
  `RHR_CACHE_DIR` moves it.

</details>

<details>
<summary><b>Speed: why it's quick, and how to make it quicker</b></summary>

<br>

The first command starts a small background server that keeps everything loaded, so
later commands on the same file cost little more than the work itself. It updates
itself when `rhr` is upgraded and stops after 20 idle minutes (`rhr server stop` stops
it now). 3D renders reuse a warm browser the same way.

- `rhr batch check a.rbxl + layout a.rbxl + ui a.rbxl` runs several commands in one go.
- `rhr scene --views iso,front,top` draws several views from one build.
- `RHR_PROFILE=1` prints where the time went.

More in [`docs/performance.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/performance.md).

</details>

## Contributing

Bug reports with a small file attached are the most useful thing you can send.
To work on `rhr` itself:

```sh
git clone https://github.com/TabooHarmony/roblox-headless-renderer && cd roblox-headless-renderer
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && rhr setup
python -m pytest -m smoke                           # a quick check; drop -m smoke for everything
```

[`docs/GOAL.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/GOAL.md) describes where the project is heading, and
[`docs/interface-1.0.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/docs/interface-1.0.md) is the full list of commands, outputs and settings.

## License

Apache 2.0. Bundled third-party code and fonts are listed in
[`THIRD_PARTY_NOTICES.md`](https://github.com/TabooHarmony/roblox-headless-renderer/blob/main/THIRD_PARTY_NOTICES.md).
Not affiliated with or endorsed by Roblox Corporation. Roblox is a trademark of Roblox Corporation.
