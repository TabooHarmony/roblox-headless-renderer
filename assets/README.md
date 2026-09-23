# Local asset caches

`assets/icon_library/` is the icon root passed to the 2D engine. Downloaded images are stored under `assets/cache/icons/<asset_id>.png` (gitignored) and do not ship in the source release. The render path never fetches them automatically.

To populate the cache for a model you own:

```sh
bin/rhr ir model.rbxm --out model.json
.venv/bin/python scripts/fetch_assets.py model.json
.venv/bin/python scripts/fetch_meshes.py model.json
```

The fetcher uses the vendored engine's asset-ID lookup and may be unable to retrieve private Roblox assets. Particle textures may also be supplied through `--texture-dir`. Do not redistribute downloaded assets merely because a URL was publicly reachable.
