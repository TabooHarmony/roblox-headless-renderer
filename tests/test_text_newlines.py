"""Explicit line breaks survive plain wrapped and TextScaled rendering.

Studio probe 5fbfe0f40ec6468aab515aa9e330c033: FredokaOne Hello\nworld
at 240x60 yields TextBounds 47x40 at fixed20 and 70x60 when scaled.
We pin line structure, not Skia glyph metrics as exact Studio metrics.
"""
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from rhr.pipeline import render_object
from ui_engine import text_fit, text_renderers


def main():
    status = 0
    def check(ok, message):
        nonlocal status
        status |= not ok
        print(f"{'ok' if ok else 'FAIL'} {message}")
    out = REPO / 'out' / 'text-newlines'
    base = dict(type='TextLabel', name='Newlines', size=[0,240,0,60],
                bgTransparency=1, font='FredokaOne', textSize=20,
                textWrapped=True, textColor=[255,0,0], textStrokeTransparency=1)
    for scaled in (False, True):
        images = []
        for text in ('Hello world', 'Hello\nworld'):
            node = dict(base, text=text, textScaled=scaled)
            target = out / f'{scaled}-{len(images)}.png'
            with patch.object(text_renderers, '_wrap_lines', wraps=text_fit._wrap_lines) as wrap:
                render_object(node, target, 240, 60)
            # Advance-table mode (plan 0.2a) skips the wrapper for a
            # no-newline string the table proves fits one line: measured
            # Studio keeps it on one line at the table's narrower advances.
            # Explicit newlines always reach the wrapper.
            if '\n' in text:
                check(wrap.called, f'{scaled}/{text!r}: plain wrapped path executed')
            pixels = np.array(Image.open(target).convert('RGBA'))
            occupied = (pixels[:,:,3] > 128).any(axis=1)
            bands = int(np.count_nonzero(occupied & ~np.r_[False, occupied[:-1]]))
            check(bands == (2 if '\n' in text else 1), f'{scaled}/{text!r}: painted row bands={bands}')
            images.append(target.read_bytes())
            again = out / 'repeat.png'
            render_object(node, again, 240, 60)
            check(again.read_bytes() == images[-1], f'{scaled}/{text!r}: deterministic bytes')
        check(images[0] != images[1], f'{scaled}: explicit break changes output')
    # Same wrapper is used by font fitting; preserve blank and edge paragraphs.
    import skia
    font = skia.Font(skia.Typeface.MakeFromFile(str(REPO / "vendor/pinevex/src/ui_engine/fonts/FredokaOne-Regular.ttf")), 20)
    for text, expected in [('A\n\nB', ['A','','B']), ('\nA\n', ['', 'A', '']),
                           ('A B\nC D', ['A B','C D']), ('', [''])]:
        check(text_fit._wrap_lines(text, font, 1000) == expected, f'paragraphs {text!r}')

    # Unwrapped plain text also preserves explicit newlines, including per-line
    # TextTruncate (Studio probe 9890cc77... / c066790a..., fixed 240x60 box,
    # TextSize 20, TextWrapped=false: Hello\nworld TextBounds 47x40 two lines).
    ubase = dict(base, textWrapped=False)
    for text, expect_bands in (('Hello world', 1), ('Hello\nworld', 2),
                               ('Hello\nX\nworld', 3)):
        node = dict(ubase, text=text)
        target = out / f'unwrapped-{expect_bands}.png'
        render_object(node, target, 240, 60)
        pixels = np.array(Image.open(target).convert('RGBA'))
        occupied = (pixels[:,:,3] > 128).any(axis=1)
        bands = int(np.count_nonzero(occupied & ~np.r_[False, occupied[:-1]]))
        check(bands == expect_bands, f'unwrapped {text!r}: painted row bands={bands}')
    # Per-line truncation: a narrow box trims each unwrapped line separately,
    # so a two-line string still paints two ellipsised bands, not one.
    narrow = dict(ubase, text='AAAAAAAA\nBBBBBBBB', textTruncate='AtEnd',
                  size=[0,40,0,60])
    target = out / 'unwrapped-truncate.png'
    render_object(narrow, target, 40, 60)
    pixels = np.array(Image.open(target).convert('RGBA'))
    occupied = (pixels[:,:,3] > 128).any(axis=1)
    bands = int(np.count_nonzero(occupied & ~np.r_[False, occupied[:-1]]))
    check(bands == 2, f'unwrapped truncated: painted row bands={bands}')
    again = out / 'unwrapped-truncate-repeat.png'
    render_object(narrow, again, 40, 60)
    check(again.read_bytes() == target.read_bytes(), 'unwrapped truncated: deterministic bytes')
    # Studio 5a860760: literal newlines and <br/> produce identical rich
    # line bounds, including blank lines, with wrapping on or off.
    for wrapped, scaled in ((False, False), (True, False), (False, True)):
        for text in ('<b>Hello\nworld</b>', '<b>Hello\n\nworld</b>',
                     '\n<b>Hello</b>\n', '<b>Hello</b>\n<i>world</i>'):
            node = dict(base, richText=True, textWrapped=wrapped,
                        textScaled=scaled, size=[0,240,0,160], text=text)
            literal = out / 'rich-literal.png'
            explicit = out / 'rich-explicit.png'
            repeat = out / 'rich-repeat.png'
            render_object(node, literal, 240, 160)
            render_object(dict(node, text=text.replace('\n', '<br/>')),
                          explicit, 240, 160)
            check(literal.read_bytes() == explicit.read_bytes(),
                  f'rich wrapped={wrapped} scaled={scaled} {text!r}: newline equals br')
            render_object(node, repeat, 240, 160)
            check(literal.read_bytes() == repeat.read_bytes(), 'rich deterministic bytes')
    return int(status)


if __name__ == '__main__':
    raise SystemExit(main())
