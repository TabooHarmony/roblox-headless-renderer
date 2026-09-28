"""What an agent looks at: a picture cut to what matters, small, with numbered boxes.

An agent pays for every pixel of every look. A row of cards drawn in a 1920x1080
canvas costs as much as a full screen; these shrink the picture without changing the
layout: `--crop <path>` (one element and a margin), `--fit` (what was drawn),
`--max-size N` (the longer side at most N px), and `--annotate` (numbered boxes on the
buttons, the numbers mapped to paths in the JSON report, so an agent can say "3" and
mean one element). Order: crop, then shrink, then the boxes (so their numbers stay
readable).
"""

from __future__ import annotations

from pathlib import Path

MARGIN_PX = 16


def _clamp(box: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(size[0], int(box[0] + box[2] + 0.999)), min(size[1], int(box[1] + box[3] + 0.999))
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def element_box(rect: dict, size: tuple[int, int], margin: int = MARGIN_PX) -> tuple[int, int, int, int] | None:
    """The crop around one element (a layout rect) with a margin, inside the picture."""
    return _clamp((rect["x"] - margin, rect["y"] - margin, rect["w"] + 2 * margin, rect["h"] + 2 * margin), size)


def drawn_box(png: Path, background: tuple[int, int, int, int], margin: int = MARGIN_PX):
    """The crop around everything drawn: pixels that differ from the background. When
    the four corners share a colour (a UI with its own full-screen backdrop), that
    colour is the background: the uniform border goes."""
    from PIL import Image, ImageChops

    with Image.open(png) as image:
        image = image.convert("RGBA")
        corners = {image.getpixel((x, y)) for x in (0, image.width - 1) for y in (0, image.height - 1)}
        if len(corners) == 1:
            background = corners.pop()
        if background[3] == 0:
            found = image.getchannel("A").getbbox()
        else:
            found = ImageChops.difference(image, Image.new("RGBA", image.size, background)).convert("L").getbbox()
        if found is None:
            return None
        x0, y0, x1, y1 = found
        return _clamp((x0 - margin, y0 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin), image.size)


def finish(png: Path, *, crop=None, max_size: int | None = None, boxes: list[dict] | None = None) -> dict:
    """Crop, shrink and number the PNG in place. Returns what the report says about it:
    {"crop": {x, y, w, h} in screen pixels or None, "scale", "size", "annotations"}."""
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(png) as source:
        image = source.convert("RGBA")
    if crop is not None:
        x, y, w, h = crop
        image = image.crop((x, y, x + w, y + h))
    scale = 1.0
    if max_size and max(image.size) > max_size:
        scale = max_size / max(image.size)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.Resampling.LANCZOS)
    annotations = []
    if boxes:
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:  # Pillow before 10.1
            font = ImageFont.load_default()
        ox, oy = (crop[0], crop[1]) if crop is not None else (0, 0)
        for number, item in enumerate(boxes, start=1):
            r = item["rect"]
            x0, y0 = (r["x"] - ox) * scale, (r["y"] - oy) * scale
            x1, y1 = x0 + r["w"] * scale, y0 + r["h"] * scale
            if x1 < 0 or y1 < 0 or x0 > image.width or y0 > image.height:
                continue
            draw.rectangle((x0, y0, x1, y1), outline=(255, 0, 170, 255), width=2)
            label = str(number)
            tw, th = draw.textbbox((0, 0), label, font=font)[2:]
            lx, ly = max(0, x0), max(0, y0 - th - 4) if y0 - th - 4 >= 0 else max(0, y0)
            draw.rectangle((lx, ly, lx + tw + 6, ly + th + 4), fill=(255, 0, 170, 255))
            draw.text((lx + 3, ly + 1), label, fill=(255, 255, 255, 255), font=font)
            annotations.append({"n": number, "path": item["path"], "class": item.get("class"), "rect": r})
    if image.mode == "RGBA" and image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    image.save(png)
    return {
        "crop": dict(zip(("x", "y", "w", "h"), crop)) if crop is not None else None,
        "scale": round(scale, 4),
        "size": [image.width, image.height],
        "annotations": annotations,
    }
