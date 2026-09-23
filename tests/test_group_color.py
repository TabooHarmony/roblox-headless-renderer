"""CanvasGroup GroupColor3 survives Lune -> adapter -> converter -> renderer."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
from test_fixtures import emit_ir  # noqa: E402
from rhr.adapter import ir_to_raw_nodes  # noqa: E402
from rhr.pipeline import to_pinevex_object, render_object  # noqa: E402

FAILURES = []


def check(ok, message):
    print(f"{'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        FAILURES.append(message)


def find(node, name):
    if node.get("name") == name:
        return node
    for child in node.get("children") or []:
        hit = find(child, name)
        if hit:
            return hit
    return None


def main():
    # 1. IR: the typed property survives the emitter on a synthetic fixture.
    ir = json.loads(emit_ir(REPO / "tests/fixtures/canvas_group_color.rbxmx").read_text())
    group = find(ir["roots"][0], "TintedGroup")
    check(group is not None, "fixture parses (TintedGroup found)")
    if group is None:
        return 1
    gc = group["props"].get("GroupColor3")
    check(isinstance(gc, dict) and (gc.get("R"), gc.get("G"), gc.get("B")) == (1, 0, 0),
          f"IR preserves GroupColor3 ({gc})")
    check(group["props"].get("GroupTransparency") == 0.5,
          f"IR preserves GroupTransparency alongside ({group['props'].get('GroupTransparency')})")
    identity = find(ir["roots"][0], "WhiteGroup")
    check(identity is not None and identity["props"].get("GroupColor3", {}).get("R") == 1
          and identity["props"].get("GroupColor3", {}).get("G") == 1,
          "the nested identity group keeps its default white GroupColor3")
    plain = find(ir["roots"][0], "PlainFrame")
    check(plain is not None and "GroupColor3" not in plain["props"],
          "a plain Frame carries no GroupColor3")

    # 2. Converter: the tint reaches the pinevex object the engine renders.
    node = to_pinevex_object(ir_to_raw_nodes(ir))
    tinted = find(node, "TintedGroup")
    check(tinted is not None and tinted.get("groupColor") == [255, 0, 0],
          f"converter emits groupColor for the tinted group ({tinted and tinted.get('groupColor')})")
    check(tinted is not None and tinted.get("groupTransparency") == 0.5,
          "converter still emits groupTransparency on the same node")
    white = find(node, "WhiteGroup")
    check(white is not None and "groupColor" not in white,
          "the default white tint is omitted (identity, engine byte-identical)")
    check(find(node, "PlainFrame") is not None and "groupColor" not in (find(node, "PlainFrame") or {}),
          "a plain Frame gets no groupColor")

    # Multiplication is channel-wise: red times green/blue is black, not red.
    # RGBA stores straight color; group alpha does not halve its RGB channels.
    from copy import deepcopy
    out = REPO / "out/group-color"
    def render(obj, name):
        target = out / f'{name}.png'
        render_object(obj, target, 300, 300)
        return np.asarray(Image.open(target).convert('RGBA')).astype(int), target
    def pixel(img, x, y, expected, label):
        actual = img[y, x]
        check(np.max(np.abs(actual - expected)) <= 2, f'{label}: {actual.tolist()}')
    img, target = render(node, 'red')
    pixel(img, 130, 70, [0, 0, 0, 128], 'red times green')
    pixel(img, 70, 70, [0, 0, 0, 128], 'red times blue overlap, alpha applied once')
    pixel(img, 120, 120, [255, 0, 0, 128], 'red times nested yellow')
    pixel(img, 220, 70, [255, 255, 255, 255], 'unrelated sibling untouched')
    _, repeat = render(node, 'repeat')
    check(target.read_bytes() == repeat.read_bytes(), 'deterministic bytes')
    variant = deepcopy(node)
    find(variant, 'TintedGroup')['groupColor'] = [128, 64, 255]
    find(variant, 'TintedGroup')['groupTransparency'] = 0
    img, _ = render(variant, 'multicolor')
    pixel(img, 130, 70, [0, 64, 0, 255], 'tint works without group transparency')
    pixel(img, 70, 70, [0, 0, 255, 255], 'blue channel preserved')
    pixel(img, 120, 120, [128, 64, 0, 255], 'nested identity preserves parent tint')
    find(variant, 'WhiteGroup')['groupColor'] = [128, 255, 255]
    img, _ = render(variant, 'nested')
    pixel(img, 120, 120, [64, 64, 0, 255], 'nested tints multiply')
    find(variant, 'TintedGroup')['groupColor'] = [255, 255, 255]
    _, white_path = render(variant, 'identity')
    del find(variant, 'TintedGroup')['groupColor']
    _, omitted_path = render(variant, 'omitted')
    check(white_path.read_bytes() == omitted_path.read_bytes(), 'white equals omitted tint')
    # A transparent area must not color the opaque pane behind the group.
    isolated = dict(type='Frame', size=[0,100,0,100], bg=[255,255,255], children=[
        dict(type='CanvasGroup', size=[0,100,0,100], bgTransparency=1,
             groupColor=[255,0,0], children=[
                 dict(type='Frame', size=[0,20,0,20], bg=[255,255,255])])])
    img, _ = render(isolated, 'isolation')
    pixel(img, 10, 10, [255,0,0,255], 'group child tinted')
    pixel(img, 50, 50, [255,255,255,255], 'pane behind transparent group untouched')
    # Exercise layout-placed nodes (_render_node_at), not just render_node.
    isolated['list'] = {'direction':'Vertical', 'spacing':0}
    img, _ = render(isolated, 'list')
    pixel(img, 10, 10, [255,0,0,255], 'layout-placed group tinted')
    pixel(img, 50, 50, [255,255,255,255], 'layout-placed group isolated')
    # Global mode does not flatten groups, per CanvasGroup documentation.
    from ui_engine.renderer import render_json
    global_path = out / 'global.png'
    render_json(node, global_path, 300, 300, z_index_behavior='Global')
    img = np.asarray(Image.open(global_path).convert('RGBA')).astype(int)
    pixel(img, 130, 70, [0,255,0,255], 'Global does not apply group tint')
    pixel(img, 70, 70, [0,0,255,255], 'Global overlap keeps child color')
    # Non-group objects must ignore a stray engine-schema groupColor key.
    frame = dict(type='Frame', size=[0,100,0,100], bg=[255,255,255], groupColor=[0,0,0])
    img, _ = render(frame, 'plain-frame')
    pixel(img, 10, 10, [255,255,255,255], 'Frame cannot apply group tint')
    find(variant, 'TintedGroup')['groupTransparency'] = 1
    img, _ = render(variant, 'hidden')
    pixel(img, 70, 70, [0,0,0,0], 'fully transparent group stays hidden')
    # Continuous tint combines correctly with fractional group alpha.
    find(variant, 'TintedGroup')['groupTransparency'] = 0.5
    find(variant, 'TintedGroup')['groupColor'] = [128,64,255]
    img, _ = render(variant, 'fractional')
    pixel(img, 130, 70, [0,64,0,128], 'color and alpha independent')
    # Group gradient shares the compositor without double tint or lost alpha.
    find(variant, 'TintedGroup')['gradient'] = {
        'colors': [(0, '#ffffff'), (1, '#ffffff')],
        'transparency': [(0, 0), (1, 0)], 'rotation': 0}
    img, _ = render(variant, 'gradient')
    pixel(img, 130, 70, [0,64,0,128], 'identity gradient and tint compose')
    _, repeat = render(variant, 'gradient-repeat')
    check((out / 'gradient.png').read_bytes() == repeat.read_bytes(), 'gradient/tint deterministic')
    # Counterfactual: removing tint changes these pixels, proving sensitivity.
    find(variant, 'TintedGroup').pop('groupColor')
    img, _ = render(variant, 'no-tint')
    pixel(img, 130, 70, [0,255,0,128], 'untinted control differs')
    # The fixture covers real emission; the variants isolate renderer semantics.
    check(len(FAILURES) == 0, 'all group-color checks passed')
    return int(bool(FAILURES))


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
