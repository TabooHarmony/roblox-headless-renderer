"""Studio-measured per-character advance tables (task 0.2a).

Roblox's rasterizer quantizes glyph advances independently of the TTF's raw
metrics: for FredokaOne, Studio draws advances at 0.75-0.80x of the
byte-identical font binary's skia advances, and fits single-line TextScaled
size <= box height exactly (TextBounds.Y == fitted size). The tables here are
captured from live Studio TextBounds probes (see
scripts/groundtruth/*probe.luau in the RHR repo and plan task 0.2a).

Per-char TextBounds rounds each glyph's fractional advance up, so table sums
are a slight upper bound on string width (0-8px over a 30-char string);
no kerning exists at small sizes (adjacent pairs sum exactly).
"""
import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CACHE: dict[tuple[str, int, str], dict | None] = {}
# Vertical glyph scale for table mode: Studio's rasterizer draws these glyphs
# smaller than the raw TTF outlines in BOTH axes; the advance ratio models x,
# this constant models y (Studio ink height / skia ink height at the fitted
# size). Calibrated on the RTL2PCParts title band.
TABLE_Y_SCALE = float(os.environ.get("RHR_TABLE_Y_SCALE", "0.87"))


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


def _draw_enabled_for(table: dict) -> bool:
    """Calibration switch: disable table-driven drawing per family."""
    fam = str(table.get("family", ""))
    if os.environ.get(f"RHR_TABLE_NODRAW_{fam.upper()}"):
        return False
    return True


def _y_scale_for(table: dict) -> float:
    """Per-family vertical scale override for calibration sweeps."""
    fam = str(table.get("family", ""))
    for env_name in (f"RHR_TABLE_Y_SCALE_{fam.upper()}-{table.get('weight', 400)}",
                     f"RHR_TABLE_Y_SCALE_{fam.upper()}"):
        v = os.environ.get(env_name)
        if v:
            return float(v)
    return TABLE_Y_SCALE


def draw_line_table(canvas, text: str, x: float, baseline_y: float,
                    font, paint, table: dict, y_scale: float | None = None) -> None:
    """Draw one line at Studio-measured advances with per-glyph y scale.

    Studio's rasterizer draws this family's glyphs narrower than the raw TTF
    outlines; each glyph keeps the measured advance (x) and is scaled
    vertically by y_scale about the baseline. Chars outside the table's ASCII
    range fall back to the font's natural advance with no scale.
    """
    if y_scale is None:
        y_scale = _y_scale_for(table)
    if not _draw_enabled_for(table):
        canvas.drawString(text, x, baseline_y, font, paint)
        return
    cursor = x
    for ch in text:
        skia_adv = float(font.measureText(ch))
        tadv = char_advance(table, ch, float(font.getSize()))
        if tadv < 0 or skia_adv <= 0:
            canvas.drawString(ch, cursor, baseline_y, font, paint)
            cursor += skia_adv
            continue
        sx = tadv / skia_adv
        if abs(sx - 1.0) < 1e-3 and abs(y_scale - 1.0) < 1e-3:
            canvas.drawString(ch, cursor, baseline_y, font, paint)
        else:
            canvas.save()
            canvas.translate(cursor, baseline_y)
            canvas.scale(sx, y_scale)
            canvas.drawString(ch, 0.0, 0.0, font, paint)
            canvas.restore()
        cursor += tadv
