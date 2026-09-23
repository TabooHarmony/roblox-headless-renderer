"""LineHeight survives Lune -> adapter -> converter -> existing renderer."""
import json
import sys
from copy import deepcopy
from pathlib import Path
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from test_fixtures import emit_ir
from rhr.adapter import ir_to_raw_nodes
from rhr.pipeline import to_pinevex_object, render_object


def main():
    failures = []
    def check(ok, message):
        print(f"{'ok' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)
    ir = json.loads(emit_ir(REPO / 'tests/fixtures/line_height.rbxmx').read_text())
    check(ir['roots'][0]['props']['LineHeight'] == 1.25, 'IR preserves LineHeight')
    out = REPO / 'out/line-height'
    for rich in (False, True):
        spacing = []
        for height in (1, 1.25):
            variant = deepcopy(ir)
            props = variant['roots'][0]['props']
            props['LineHeight'] = height
            props['RichText'] = rich
            props['Text'] = '<b>AAAA</b><br/>BBBB' if rich else 'AAAA\nBBBB'
            node = to_pinevex_object(ir_to_raw_nodes(variant))
            check(node.get('lineHeight', 1) == height, f'{rich}/{height}: converter preserves spacing')
            target = out / f'{rich}-{height}.png'
            render_object(node, target, 240, 200)
            image = np.array(Image.open(target).convert('RGBA'))
            rows = (image[:,:,3] > 128).any(axis=1)
            starts = np.flatnonzero(rows & ~np.r_[False, rows[:-1]])
            check(len(starts) == 2, f'{rich}/{height}: two painted lines')
            spacing.append(int(starts[1]-starts[0]) if len(starts) == 2 else 0)
            repeat = out / 'repeat.png'
            render_object(node, repeat, 240, 200)
            check(target.read_bytes() == repeat.read_bytes(), f'{rich}/{height}: deterministic bytes')
        check(spacing[1] > spacing[0] > 0, f'{rich}: spacing increases: {spacing}')
    # Height-limited plain TextScaled must fit the same line step it paints.
    from unittest.mock import patch
    from ui_engine import text_renderers
    for content in ('AAAA', 'AAAA\nBBBB'):
        sizes = []
        for height in (1, 2):
            node = dict(type='TextLabel', size=[0,240,0,60], text=content,
                        textScaled=True, textWrapped=False, font='FredokaOne',
                        lineHeight=height, textColor=[255,0,0], bgTransparency=1,
                        textStrokeTransparency=1)
            fitted = []
            original = text_renderers._fit_font_size
            def fit(*args, **kwargs):
                value = original(*args, **kwargs)
                fitted.append(value)
                return value
            target = out / f'scaled-{height}-{len(content)}.png'
            with patch.object(text_renderers, '_fit_font_size', side_effect=fit):
                render_object(node, target, 240, 60)
            check(len(fitted) == 1, f'{content!r}/{height}: fitting executed')
            sizes.append(fitted[0])
            pixels = np.array(Image.open(target).convert('RGBA'))
            occupied = (pixels[:,:,3] > 128).any(axis=1)
            bands = np.count_nonzero(occupied & ~np.r_[False, occupied[:-1]])
            check(bands == (2 if '\n' in content else 1), f'{content!r}/{height}: full line count painted')
            repeat = out / 'scaled-repeat.png'
            render_object(node, repeat, 240, 60)
            check(target.read_bytes() == repeat.read_bytes(), f'{content!r}/{height}: deterministic')
        check(sizes[1] < sizes[0] if '\n' in content else sizes[1] == sizes[0],
              f'{content!r}: spacing changes multiline fit only: {sizes}')
    return int(bool(failures))


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == '__main__':
    raise SystemExit(main())
