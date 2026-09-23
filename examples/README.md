# Examples

Two small files made for this repository, free to reuse. `scripts/make_examples.py`
writes them.

| File | What it shows | Try |
| --- | --- | --- |
| `shop.rbxmx` | A shop ScreenGui: grid and list layouts, gradients, strokes, rounded corners, text. One item name is deliberately too long for its label. | `rhr render examples/shop.rbxmx --out shop.png`, then `rhr check examples/shop.rbxmx` |
| `tower.rbxmx` | A small 3D build on a Baseplate: materials, Lighting, a neon lamp with a PointLight, a SurfaceGui sign and a BillboardGui name tag. | `rhr scene examples/tower.rbxmx --view iso --shadows --out tower.png`, or `rhr preview` for the world and UI together |
