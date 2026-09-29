from .text_runs import *
from .text_advances import char_advance, string_width

def _has_pua(text: str) -> bool:
    return any(ch in _PUA_CHARS for ch in text)


def _should_prefer_tight_height(text: str) -> bool:
    """Use tight-height TextScaled only for text likely to benefit from it.

    Tight bounds over-scale normal word labels in Studio parity tests.
    Restrict this mode to symbol-only labels.
    """
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return False
    return all(not ch.isalnum() for ch in stripped)


def _is_symbol_only_text(text: str) -> bool:
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return False
    return all(not ch.isalnum() for ch in stripped)


def _wrap_lines(text: str, font: skia.Font, max_width: float,
                emoji_font: skia.Font | None = None,
                fallback_fonts: tuple[skia.Font, ...] | None = None) -> list[str]:
    """Word-wrap text into lines that fit within max_width."""
    if max_width <= 0:
        return [text]
    lines: list[str] = []
    # Explicit newlines are mandatory breaks, including empty paragraphs.
    # Keep the existing word wrapping within each paragraph.
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if _measure_mixed(candidate, font, emoji_font, fallback_fonts) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def wrap_lines_table(text: str, table: dict, size: float, max_w: float, wrapped: bool) -> list[str] | None:
    """Lines as Roblox breaks them, with widths from a Studio advance table.

    Greedy at spaces (explicit newlines always break); None when the table does
    not cover a character, so the caller falls back to font measurement.
    """
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            width = string_width(table, candidate, size)
            if width is None:
                return None
            if wrapped and width > max_w:
                lines.append(current)
                current = word
            else:
                current = candidate
        if string_width(table, current, size) is None:
            return None
        lines.append(current)
    return lines


def _fit_font_size(text: str, typeface: skia.Typeface, max_w: float, max_h: float,
                   wrapped: bool, emoji_typeface: skia.Typeface | None = None,
                   fallback_typefaces: list[skia.Typeface] | None = None,
                   requested_weight: int = 400,
                   italic: bool = False,
                   prefer_tight_height: bool = False,
                   tight_height_line_floor: float = 0.0,
                   min_size: float = _TEXTSCALED_DEFAULT_MIN,
                   max_size: float = _TEXTSCALED_DEFAULT_MAX,
                   line_height_mult: float = 1.0,
                   advance_table: dict | None = None) -> float:
    """Binary search for the largest font size where text fits in the rect.

    With an advance_table (Studio-measured per-char advances, plan 0.2a) and
    unwrapped single-line text, apply the measured Studio rules: fitted size
    is bounded by the box height exactly (TextBounds.Y == fitted size) and
    the width bound uses the table instead of skia's raw advances.
    """
    lo = max(0.1, float(min_size))
    hi = max(lo, float(max_size))
    best = lo
    for _ in range(30):
        mid = (lo + hi) / 2
        font = roblox_font(typeface, mid)
        _apply_font_draw_style(font, typeface, requested_weight, italic=italic)
        ef = roblox_font(emoji_typeface, mid) if emoji_typeface else None
        if ef:
            _apply_font_draw_style(ef, emoji_typeface, requested_weight)
        fallback_fonts = _build_fallback_fonts(fallback_typefaces or [], mid)
        metrics = font.getMetrics()
        line_h = -metrics.fAscent + metrics.fDescent
        if advance_table is not None:
            # Studio rules for TextScaled (measured, plan 0.2a; tests/studio):
            # each line box is the size itself, widths come from the captured
            # table, and Roblox takes the largest integer size at which the
            # WRAPPED text fits (172x96 box: "Scaled text" on 2 lines at 48).
            size_i = float(int(mid))
            table_lines = wrap_lines_table(text, advance_table, size_i, max_w, wrapped)
            if table_lines is not None:
                widest = max(string_width(advance_table, line, size_i) or 0.0 for line in table_lines)
                total = size_i + size_i * line_height_mult * (len(table_lines) - 1)
                fits = total <= max_h and widest <= max_w
                if fits:
                    if size_i > best:
                        best = size_i
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 0.5:
                    break
                continue
        if wrapped:
            lines = _wrap_lines(text, font, max_w, ef, fallback_fonts)
            if prefer_tight_height and len(lines) == 1 and not _has_pua(lines[0]):
                total_h = (
                    _measure_mixed_tight_height(lines[0], font, ef, fallback_fonts)
                    * _GRADIENT_TIGHT_HEIGHT_SCALE
                )
                if tight_height_line_floor > 0:
                    total_h = max(total_h, line_h * tight_height_line_floor)
            else:
                # Match drawing: LineHeight scales the step between baselines,
                # not the first line. Studio shrinks height-limited scaled text
                # when this multiplier grows.
                # Roblox steps lines by TextSize x LineHeight, no font line gap.
                step = line_h * line_height_mult
                total_h = line_h + step * (len(lines) - 1)
            max_line_w = max((_measure_mixed(ln, font, ef, fallback_fonts) for ln in lines), default=0)
            fits = max_line_w <= max_w and total_h <= max_h
        else:
            if not prefer_tight_height or _has_pua(text):
                text_h = line_h
            else:
                text_h = (
                    _measure_mixed_tight_height(text, font, ef, fallback_fonts)
                    * _GRADIENT_TIGHT_HEIGHT_SCALE
                )
                if tight_height_line_floor > 0:
                    text_h = max(text_h, line_h * tight_height_line_floor)
            fits = _measure_mixed(text, font, ef, fallback_fonts) <= max_w and text_h <= max_h
        if fits:
            best = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.5:
            break
    return best


def _measure_mixed_tight_height(
    text: str,
    font: skia.Font,
    emoji_font: skia.Font | None = None,
    fallback_fonts: tuple[skia.Font, ...] | None = None,
) -> float:
    """Measure rendered glyph tight height for mixed runs.

    Falls back to line metrics when path bounds are unavailable.
    """
    if not text:
        return 0.0

    cursor = 0.0
    top = None
    bottom = None
    has_bounds = False
    for run_text, run_font in _split_font_runs(text, font, emoji_font, fallback_fonts):
        if not run_text:
            continue
        glyph_path = _text_path(run_text, run_font, cursor, 0.0)
        if glyph_path is not None:
            b = glyph_path.computeTightBounds()
            bt = float(b.top())
            bb = float(b.bottom())
            top = bt if top is None else min(top, bt)
            bottom = bb if bottom is None else max(bottom, bb)
            has_bounds = True
        cursor += _measure_run_text(run_text, run_font)

    if has_bounds and top is not None and bottom is not None:
        return max(0.0, bottom - top)

    m = font.getMetrics()
    return -m.fAscent + m.fDescent


# ---------------------------------------------------------------------------
# Rich text parsing and layout
# ---------------------------------------------------------------------------


_JOIN_MAP = {
    "round": skia.Paint.Join.kRound_Join,
    "bevel": skia.Paint.Join.kBevel_Join,
    "miter": skia.Paint.Join.kMiter_Join,
}


__all__ = [name for name in globals() if not name.startswith("__")]
