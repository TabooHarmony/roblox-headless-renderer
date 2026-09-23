"""ResampleMode survives parsing and changes real image pixels, offline."""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'src'), str(REPO / 'tests')]
from rhr.pipeline import render_ir
from test_fixtures import emit_ir


def main():
    failures = []

    def check(ok, message):
        print(f"{'ok' if ok else 'FAIL'}  {message}")
        if not ok:
            failures.append(message)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        icons = tmp / 'icon_library'
        cache = tmp / 'cache' / 'icons'
        cache.mkdir(parents=True)
        # Two source colors make interpolation distinguishable from nearest.
        source = Image.new('RGB', (2, 2), 'black')
        source.putpixel((1, 0), (255, 255, 255))
        source.putpixel((1, 1), (255, 255, 255))
        source.save(cache / '13581515352.png')
        ir_path = emit_ir(REPO / 'tests/fixtures/_resample_repro.rbxmx', tmp / 'ir.json')
        original = json.loads(Path(ir_path).read_text())
        labels = original['roots'][0]['children'][0]['children']
        check([n['props']['ResampleMode']['name'] for n in labels] == ['Default', 'Pixelated'],
              'IR preserves both ResampleMode values')
        for mode in ('Stretch', 'Fit', 'Crop'):
            for gradient in (False, True):
                data = json.loads(json.dumps(original))
                nodes = data['roots'][0]['children'][0]['children']
                for n in nodes:
                    n['props']['ScaleType'] = {'_t': 'EnumItem', 'enum': 'Enum.ScaleType', 'name': mode}
                    if gradient:
                        n['children'] = [{'className': 'UIGradient', 'name': 'White',
                                          'props': {'Enabled': True, 'Rotation': 0,
                                                    'Color': [{'time': 0, 'color': {'r': 1, 'g': 1, 'b': 1}},
                                                              {'time': 1, 'color': {'r': 1, 'g': 1, 'b': 1}}]},
                                          'children': []}]
                Path(ir_path).write_text(json.dumps(data))
                png = render_ir(ir_path, tmp / 'first.png', 200, 200, icons_dir=icons)
                image = np.array(Image.open(png).convert('RGB'))
                # Interior avoids background and antialiased rectangle edges.
                # The default desktop inset adds 58 to the authored y=12.
                a, b = image[114:122, 18:30], image[114:122, 170:182]
                name = f'{mode}/gradient={gradient}'
                check(bool(np.any((a > 0) & (a < 255))), name + ': Default blends colors')
                check(bool(np.all((b == 0) | (b == 255))), name + ': Pixelated preserves source colors')
                check(not np.array_equal(a, b), name + ': modes paint differently')
                repeat = render_ir(ir_path, tmp / 'repeat.png', 200, 200, icons_dir=icons)
                check(png.read_bytes() == repeat.read_bytes(), name + ': deterministic bytes')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
