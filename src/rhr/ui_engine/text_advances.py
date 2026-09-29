"""Studio-measured per-character advance tables (task 0.2a).

Roblox's rasterizer quantizes glyph advances independently of the TTF's raw
metrics: for FredokaOne, Studio's advances are about 1.1x the byte-identical
font binary's skia advances at RHR's em (roblox_em_px), its glyphs are drawn
that much larger in both axes (ink width == TextBounds.X), and it fits
single-line TextScaled size <= box height exactly (TextBounds.Y == fitted size). The tables here are
captured from live Studio TextBounds probes (see
scripts/groundtruth/*probe.luau in the RHR repo and plan task 0.2a).

Per-char TextBounds rounds each glyph's fractional advance up, so table sums
are a slight upper bound on string width (0-8px over a 30-char string);
no kerning exists at small sizes (adjacent pairs sum exactly).
"""
import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CACHE: dict[tuple[str, int, str], dict | None] = {}


def _table_path(family: str, weight: int, style: str) -> Path:
    safe = "".join(c for c in family if c.isalnum())
    # Weight-specific tables carry a -<weight> suffix; the original
    # FredokaOne capture (weight 400) keeps the un-suffixed name.
    if weight != 400:
        return _DATA_DIR / f"font_advances_{safe}-{weight}.json"
    return _DATA_DIR / f"font_advances_{safe}.json"


def load_advance_table(family: str, weight: int, style: str) -> dict | None:
    """Return {'sizes': {int: {'chars': [94 ints], 'space': int}}} or None."""
    key = (family, int(weight), style)
    if key in _CACHE:
        return _CACHE[key]
    table = None
    path = _table_path(family, weight, style)
    if path.exists() and style == "normal":
        try:
            raw = json.loads(path.read_text())
            if raw.get("family") == family and int(raw.get("weight", 400)) == int(weight):
                table = {
                    "family": family,
                    "weight": int(weight),
                    "sizes": {int(k): v for k, v in raw["sizes"].items()},
                    "min_size": min(int(k) for k in raw["sizes"]),
                    "max_size": max(int(k) for k in raw["sizes"]),
                }
        except Exception:
            table = None
    _CACHE[key] = table
    return table


def char_advance(table: dict, ch: str, size: float) -> float:
    """Interpolated Studio advance for one char at a fractional size."""
    if ch == " ":
        return _interp_space(table, size)
    code = ord(ch)
    if not (33 <= code <= 126):
        # Outside the captured ASCII range: callers fall back to skia metrics.
        return -1.0
    return _interp_chars(table, size, code - 33)


def _interp_chars(table: dict, size: float, idx: int) -> float:
    sizes = table["sizes"]
    lo = table["min_size"]
    hi = table["max_size"]
    if size <= lo:
        return float(sizes[lo]["chars"][idx])
    if size >= hi:
        return float(sizes[hi]["chars"][idx])
    import math
    f = math.floor(size)
    c = math.ceil(size)
    if f == c:
        return float(sizes[f]["chars"][idx])
    a = sizes[f]["chars"][idx]
    b = sizes[c]["chars"][idx]
    t = (size - f) / (c - f)
    return a + (b - a) * t


def _interp_space(table: dict, size: float) -> float:
    sizes = table["sizes"]
    lo = table["min_size"]
    hi = table["max_size"]
    if size <= lo:
        return float(sizes[lo]["space"])
    if size >= hi:
        return float(sizes[hi]["space"])
    import math
    f = math.floor(size)
    c = math.ceil(size)
    if f == c:
        return float(sizes[f]["space"])
    a = sizes[f]["space"]
    b = sizes[c]["space"]
    t = (size - f) / (c - f)
    return a + (b - a) * t


def has_full_ascii(table: dict, text: str) -> bool:
    """True when every char of text is covered by the table (or is a space)."""
    return all(ch == " " or 33 <= ord(ch) <= 126 for ch in text)


def string_width(table: dict, text: str, size: float) -> float | None:
    """Studio-model string width, or None when the table can't measure it."""
    if not has_full_ascii(table, text):
        return None
    return sum(char_advance(table, ch, size) for ch in text)


def draw_line_table(canvas, text: str, x: float, baseline_y: float,
                    font, paint, table: dict, size: float | None = None) -> None:
    """Draw one line at Studio-measured advances.

    Studio draws this family's glyphs uniformly larger than the raw TTF outlines
    at RHR's em, by the ratio of its advances to skia's: measured in Studio 2026-09,
    "Sample Price" at TextSize 26 has 137x22 px of ink for TextBounds 138 wide,
    1.10x skia's ink both ways, and table/skia advances over the string are 1.10.
    One scale per line (the per-glyph ratio is noisy: the table rounds each
    advance up to a whole pixel); each glyph still sits at its measured advance.
    Chars outside the table's ASCII range keep the font's natural advance and size.
    `size` is the Roblox TextSize the table is indexed by (the font's own size is
    the em, which is smaller).
    """
    size = float(font.getSize()) if size is None else float(size)
    measured = [(char_advance(table, ch, size), float(font.measureText(ch))) for ch in text]
    table_sum = sum(t for t, a in measured if t >= 0 and a > 0)
    skia_sum = sum(a for t, a in measured if t >= 0 and a > 0)
    scale = table_sum / skia_sum if skia_sum > 0 else 1.0
    cursor = x
    for ch, (tadv, skia_adv) in zip(text, measured):
        if tadv < 0 or skia_adv <= 0:
            canvas.drawString(ch, cursor, baseline_y, font, paint)
            cursor += skia_adv
            continue
        if abs(scale - 1.0) < 1e-3:
            canvas.drawString(ch, cursor, baseline_y, font, paint)
        else:
            canvas.save()
            canvas.translate(cursor, baseline_y)
            canvas.scale(scale, scale)
            canvas.drawString(ch, 0.0, 0.0, font, paint)
            canvas.restore()
        cursor += tadv
