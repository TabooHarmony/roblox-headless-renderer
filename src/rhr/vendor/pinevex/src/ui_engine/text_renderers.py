from .text_rich import *
from .text_advances import (
    load_advance_table,
    has_full_ascii as _table_covers_text,
    string_width as _string_width,
    draw_line_table,
)


def _truncate_ellipsis(text: str, font: skia.Font, max_width: float,
                       emoji_font=None, fallback_fonts=(), split_word: bool = False) -> str:
    """Trim text so it plus an ellipsis fits max_width, per TextTruncate mode.

    Roblox (Enum.TextTruncate docs, Studio-checked in tests/studio): AtEnd backs
    up to the end of the last complete word that fits, when there is one;
    SplitWord cuts inside the word at whatever character boundary fits. Widths
    are measured with the same mixed-run measurement drawing uses.
    """
    if not text:
        return text
    ellipsis = "…"

    def width(s: str) -> float:
        return _measure_mixed(s, font, emoji_font, fallback_fonts)

    if width(text + ellipsis) <= max_width:
        return text + ellipsis
    # Binary search the longest prefix that fits with the ellipsis appended.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width(text[:mid] + ellipsis) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    cut = text[:lo]
    if not split_word and cut and not cut[-1].isspace() and not text[len(cut):len(cut) + 1].isspace():
        # Back up to the last word boundary, if one leaves something.
        stripped = cut.rstrip()
        last_break = max(stripped.rfind(" "), stripped.rfind("\t"))
        if last_break > 0:
            cut = stripped[: last_break + 1]
    trimmed = cut.rstrip() + ellipsis
    # A single grapheme plus ellipsis can still overflow a tiny box; the
    # ellipsis itself is then the whole output, never an empty string.
    return trimmed if width(trimmed) <= max_width or lo == 0 else ellipsis


def _text_stroke_thickness_scale(font_family: str | None) -> float:
    """Calibrate text-outline heft for pixel-like faces."""
    family = (font_family or "").strip().lower()
    if family in {"pressstart2p", "pressstart"}:
        return 0.8
    return 1.0


def _draw_text_plain_rtl(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
                         node: dict, fonts_dir: Path | None = None,
                         gradient: dict | None = None) -> bool:
    text = node.get("text", "")
    if not text or not _TEXTLAYOUT_AVAILABLE:
        return False

    transparency = node.get("textTransparency", 0.0)
    if transparency >= 1.0:
        return True

    family, weight = _resolve_font(node.get("font"), node.get("fontWeight"))
    stroke_thickness_scale = _text_stroke_thickness_scale(family)
    italic = _is_italic_style(node.get("fontStyle"))
    typeface = _load_typeface(family, weight, fonts_dir, italic=italic)
    _get_emoji_typeface(fonts_dir)
    fallback_typefaces = _with_emoji_fallback_typefaces(
        _get_fallback_typefaces(fonts_dir), fonts_dir
    )
    slant = skia.FontStyle.Slant.kItalic_Slant if italic else skia.FontStyle.Slant.kUpright_Slant
    font_style = skia.FontStyle(weight, 5, slant)
    text_size = float(node.get("textSize", 14.0))

    main_family = typeface.getFamilyName() or family
    font_families, font_typefaces = _font_aliases_for_run(
        skia.Font(typeface, max(1.0, text_size)),
        tuple(skia.Font(tf, max(1.0, text_size)) for tf in fallback_typefaces),
    )
    if not font_families and main_family:
        font_families = [main_family]
        font_typefaces = []
    if not font_families:
        return False

    content_x, content_y, content_w, content_h = _resolve_text_content_rect(node, x, y, w, h)
    if content_w <= 0 or content_h <= 0:
        return True

    # TextScaled implies TextWrapped (Roblox docs, TextLabel.TextScaled).
    # Studio fits scaled text to the full content box: outlines never shrink
    # the glyphs (fixed-box probe: identical TextBounds at UIStroke 0/2/5),
    # so no outline thickness is reserved from the fit box.
    wrapped = bool(node.get("textWrapped", False)) or bool(node.get("textScaled", False))
    wrapped_effective = wrapped and _has_break_opportunities(text)
    if node.get("textScaled", False):
        min_size, max_size = _textscaled_size_limits(node)
        text_size = max(min_size, min(text_size, max_size))
        text_size = _fit_paragraph_font_size(
            text=text,
            font_families=font_families,
            font_typefaces=font_typefaces,
            font_style=font_style,
            max_w=content_w,
            max_h=content_h,
            wrapped=wrapped_effective,
            min_size=min_size,
            max_size=max_size,
        )

    color = node.get("textColor", [0, 0, 0])
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    alpha = int((1.0 - transparency) * 255)
    fill_paint = skia.Paint()
    fill_paint.setAntiAlias(True)
    if gradient:
        shader = make_gradient_shader(
            gradient, x, y, w, h,
            base_color=(r, g, b), base_transparency=transparency,
        )
        if shader:
            fill_paint.setShader(shader)
        else:
            fill_paint.setColor(skia.Color(r, g, b, alpha))
    else:
        fill_paint.setColor(skia.Color(r, g, b, alpha))

    x_align = node.get("textXAlignment", "Center")
    draw_align = _map_text_align(x_align) if wrapped_effective else skia.textlayout.TextAlign.kLeft

    measure_para = _build_paragraph(
        text=text,
        font_families=font_families,
        font_typefaces=font_typefaces,
        font_style=font_style,
        text_size=text_size,
        paint=fill_paint,
        text_align=draw_align,
        max_width=content_w,
        wrapped=wrapped_effective,
    )
    if measure_para is None:
        return False

    total_text_h = measure_para.Height
    node["_textLayout"] = {
        "size": float(text_size),
        # skia-python exposes no line count; each line box is TextSize tall.
        "lines": max(1, round(measure_para.Height / max(float(text_size), 1e-6))),
        "bounds": [float(measure_para.LongestLine), float(total_text_h)],
    }
    y_align = node.get("textYAlignment", "Center")
    if y_align == "Top":
        start_y = content_y
    elif y_align == "Bottom":
        start_y = content_y + content_h - total_text_h
    else:
        start_y = content_y + (content_h - total_text_h) / 2

    if wrapped_effective:
        draw_x = content_x
    else:
        line_w = measure_para.LongestLine
        if x_align == "Left":
            draw_x = content_x
        elif x_align == "Right":
            draw_x = content_x + content_w - line_w
        else:
            draw_x = content_x + (content_w - line_w) / 2

    stroke_paints: list[tuple[float, skia.Paint]] = []
    legacy_text_stroke = _build_legacy_text_stroke(node)
    if legacy_text_stroke is not None:
        stroke_paints.append(legacy_text_stroke)

    for s in node.get("strokes", []):
        if s.get("applyMode") == "Border":
            continue
        s_thickness = s.get("thickness", 1)
        if s.get("thicknessScale"):
            s_thickness = s_thickness * text_size
        s_thickness = s_thickness * stroke_thickness_scale
        if gradient:
            s_thickness = s_thickness * _GRADIENT_TEXT_STROKE_SCALE
        s_color = s.get("color", [0, 0, 0])
        s_trans = s.get("transparency", 0)
        if s_thickness <= 0 or s_trans >= 1:
            continue
        sp = skia.Paint()
        sp.setAntiAlias(True)
        sp.setStyle(skia.Paint.kStroke_Style)
        sp.setStrokeWidth(_stroke_width_from_thickness(float(s_thickness)))
        join = str(s.get("lineJoin", "Round")).lower()
        sp.setStrokeJoin(_JOIN_MAP.get(join, skia.Paint.Join.kRound_Join))
        sr, sg, sb = int(s_color[0]), int(s_color[1]), int(s_color[2])
        s_alpha = round((1.0 - s_trans) * 255)
        s_grad = s.get("gradient") or gradient
        if s_grad:
            s_shader = make_gradient_shader(
                s_grad, x, y, w, h,
                base_color=(sr, sg, sb), base_transparency=s_trans,
            )
            if s_shader:
                sp.setShader(s_shader)
            else:
                sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        else:
            sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        stroke_paints.append((s_thickness, sp))

    stroke_paints.sort(key=lambda t: t[0], reverse=True)
    max_stroke = max((t for t, _ in stroke_paints), default=0.0)
    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(
        content_x - max_stroke, content_y - max_stroke,
        content_w + max_stroke * 2, content_h + max_stroke * 2,
    ))

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    if stroke_paints:
        stroke_bounds = skia.Rect.MakeXYWH(
            content_x - max_stroke * 2, content_y - max_stroke * 2,
            content_w + max_stroke * 4, content_h + max_stroke * 4,
        )
        _annotate(canvas, f"Text stroke layer: {name}")
        canvas.saveLayer(stroke_bounds)
        for _, sp in stroke_paints:
            stroke_para = _build_paragraph(
                text=text,
                font_families=font_families,
                font_typefaces=font_typefaces,
                font_style=font_style,
                text_size=text_size,
                paint=sp,
                text_align=draw_align,
                max_width=content_w,
                wrapped=wrapped_effective,
            )
            if stroke_para is not None:
                _annotate(canvas, f"Text stroke: {name}")
                stroke_para.paint(canvas, draw_x, start_y)

        # Roblox icon PUA glyphs keep clearer inner contour lines without knockout clear.
        if not _has_pua(text):
            clear_paint = skia.Paint()
            clear_paint.setAntiAlias(True)
            clear_paint.setBlendMode(skia.BlendMode.kDstOut)
            clear_para = _build_paragraph(
                text=text,
                font_families=font_families,
                font_typefaces=font_typefaces,
                font_style=font_style,
                text_size=text_size,
                paint=clear_paint,
                text_align=draw_align,
                max_width=content_w,
                wrapped=wrapped_effective,
            )
            if clear_para is not None:
                clear_para.paint(canvas, draw_x, start_y)
        canvas.restore()

    fill_para = _build_paragraph(
        text=text,
        font_families=font_families,
        font_typefaces=font_typefaces,
        font_style=font_style,
        text_size=text_size,
        paint=fill_paint,
        text_align=draw_align,
        max_width=content_w,
        wrapped=wrapped_effective,
    )
    if fill_para is not None:
        _annotate(canvas, f"Text fill: {name}")
        fill_para.paint(canvas, draw_x, start_y)

    canvas.restore()
    return True


def _draw_text_plain(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
                     node: dict, fonts_dir: Path | None = None,
                     gradient: dict | None = None) -> None:
    text = node.get("text", "")
    if not text:
        return

    transparency = node.get("textTransparency", 0.0)
    if transparency >= 1.0:
        return

    if _contains_rtl(text):
        if _draw_text_plain_rtl(canvas, x, y, w, h, node, fonts_dir, gradient):
            return

    content_x, content_y, content_w, content_h = _resolve_text_content_rect(node, x, y, w, h)
    if content_w <= 0 or content_h <= 0:
        return

    # Font setup
    family, weight = _resolve_font(node.get("font"), node.get("fontWeight"))
    stroke_thickness_scale = _text_stroke_thickness_scale(family)
    italic = _is_italic_style(node.get("fontStyle"))
    typeface = _load_typeface(family, weight, fonts_dir, italic=italic)
    emoji_typeface = _get_emoji_typeface(fonts_dir)
    fallback_typefaces = _with_emoji_fallback_typefaces(
        _get_fallback_typefaces(fonts_dir), fonts_dir
    )
    text_size = node.get("textSize", 14.0)
    wrapped = node.get("textWrapped", False) or node.get("textScaled", False)
    use_tight_height = bool(gradient) and _should_prefer_tight_height(text)
    symbol_floor = 0.0
    if bool(gradient) and _is_symbol_only_text(text):
        use_tight_height = True
        symbol_floor = _SYMBOL_TIGHT_HEIGHT_LINE_FLOOR

    if node.get("textScaled", False):
        min_size, max_size = _textscaled_size_limits(node)
        text_size = max(float(min_size), min(float(text_size), float(max_size)))
        # Studio fits scaled text to the full content box: outlines never
        # shrink the glyphs (fixed-box probe: identical TextBounds at UIStroke
        # 0/2/5), so no outline thickness is reserved from the fit box.
        text_size = _fit_font_size(
            text,
            typeface,
            content_w,
            content_h,
            wrapped,
            emoji_typeface,
            fallback_typefaces,
            requested_weight=weight,
            italic=italic,
            prefer_tight_height=use_tight_height,
            tight_height_line_floor=symbol_floor,
            min_size=min_size,
            max_size=max_size,
            line_height_mult=float(node.get("lineHeight", 1.0)),
            advance_table=load_advance_table(family, weight, "normal" if not italic else "italic"),
        )

    font = roblox_font(typeface, text_size)
    _apply_font_draw_style(font, typeface, weight, italic=italic)
    emoji_font = roblox_font(emoji_typeface, text_size) if emoji_typeface else None
    if emoji_font:
        _apply_font_draw_style(emoji_font, emoji_typeface, weight)
    fallback_fonts = _build_fallback_fonts(fallback_typefaces, text_size)

    # Paint
    color = node.get("textColor", [0, 0, 0])
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    alpha = int((1.0 - transparency) * 255)
    paint = skia.Paint()
    paint.setAntiAlias(True)
    if gradient:
        shader = make_gradient_shader(
            gradient, x, y, w, h,
            base_color=(r, g, b), base_transparency=transparency,
        )
        if shader:
            paint.setShader(shader)
        else:
            paint.setColor(skia.Color(r, g, b, alpha))
    else:
        paint.setColor(skia.Color(r, g, b, alpha))

    # Build lines
    # Studio model (plan 0.2a): a TextScaled label whose string fits the
    # content width at the fitted size by the advance table stays on ONE
    # line even though TextWrapped is implied — the skia measure would wrap
    # it because skia advances run ~1.3x wide.
    adv_table_early = load_advance_table(family, weight, "normal" if not italic else "italic")
    table_single_line = (
        adv_table_early is not None
        and "\n" not in text
        and _table_covers_text(adv_table_early, text)
        and (_string_width(adv_table_early, text, float(text_size)) or 1e9) <= content_w
    )
    table_lines = (
        wrap_lines_table(text, adv_table_early, float(text_size), content_w, True)
        if wrapped and adv_table_early is not None else None
    )
    if wrapped and table_single_line:
        lines = [text]
    elif table_lines is not None:
        lines = table_lines
    elif wrapped:
        lines = _wrap_lines(text, font, content_w, emoji_font, fallback_fonts)
    else:
        # Explicit newlines are mandatory breaks in unwrapped text too
        # (Studio probe: Hello\nworld at fixed TextSize draws two lines).
        # TextTruncate (Enum.TextTruncate: AtEnd / SplitWord) then trims each
        # unwrapped line that exceeds the content width, with an ellipsis.
        # None (the default) never touches the string.
        truncate = node.get("textTruncate")
        lines = []
        for line in text.split("\n"):
            if (truncate in ("AtEnd", "SplitWord") and
                    _measure_mixed(line, font, emoji_font, fallback_fonts) > content_w):
                line = _truncate_ellipsis(line, font, content_w, emoji_font, fallback_fonts,
                                          split_word=(truncate == "SplitWord"))
            lines.append(line)

    # Metrics
    metrics = font.getMetrics()
    ascent = -metrics.fAscent
    descent = metrics.fDescent
    # Roblox steps lines by TextSize x LineHeight with no font line gap (Studio:
    # two 18px lines are 36px tall in every family measured, tests/studio).
    leading = 0.0
    line_height_mult = node.get("lineHeight", 1.0)
    single_line_h = ascent + descent
    # Studio-measured model (plan 0.2a): when the family has an advance
    # table and this is a single unwrapped line, Roblox's line box is the
    # TextSize itself (TextBounds.Y == size) and glyphs draw at the table's
    # narrower advances.
    adv_table = load_advance_table(family, weight, "normal" if not italic else "italic")
    table_mode = (
        adv_table is not None and "\n" not in text
        and len(lines) == 1
        # The drawn line, not the source text: a truncated line ends in an
        # ellipsis the table may not cover.
        and _table_covers_text(adv_table, lines[0])
        # TextScaled implies TextWrapped; table mode still applies when the
        # line fits the content width at the fitted size (Studio keeps it
        # on one line and draws it at the table's advances).
        and (not wrapped
             or (string_width_at := _string_width(adv_table, text, float(text_size))) is None
             or string_width_at <= content_w)
    )
    if table_mode or family not in _PIXEL_FONT_FAMILIES:
        # Roblox's line box is TextSize itself (TextBounds.Y == TextSize); the
        # rasterized em is rounded up to whole pixels, so its metrics run a
        # little taller. Keep the baseline at the font's ascent/descent split.
        ascent_share = ascent / (ascent + descent) if ascent + descent > 0 else 0.8
        single_line_h = float(text_size)
        ascent, descent = single_line_h * ascent_share, single_line_h * (1 - ascent_share)
    # Pixel faces (Press Start 2P): Roblox's cell sits ON the baseline — the
    # ink fills the cell upward and the baseline is the cell's bottom edge
    # (measured, suite Winner pair: box top 143.8 + cell 54 -> ink 176-223,
    # baseline 223). Skia's font metrics (ascent 45.3 / descent 10.0 at size
    # 54) place the baseline 14px too high, so for pixel faces the whole line
    # box hangs below the baseline: ascent = the line box, descent = 0.
    if family in _PIXEL_FONT_FAMILIES:
        # 1.04: measured Winner baseline 223 = box_top 143.8 + (100-54)/2 + 56.2;
        # 56.2/54 = 1.0407. Skia's own metrics put the baseline 14px higher.
        ascent = single_line_h * 1.04
        descent = 0.0
        leading = 0.0
    line_step = single_line_h * line_height_mult + leading
    total_text_h = single_line_h + line_step * (len(lines) - 1) if lines else 0
    # What was laid out, like Roblox's TextBounds: read back by the layout dump.
    if table_mode:
        line_widths = [_string_width(adv_table, line, float(text_size)) or 0.0 for line in lines]
    else:
        line_widths = [_measure_mixed(line, font, emoji_font, fallback_fonts) for line in lines]
    node["_textLayout"] = {
        "size": float(text_size),
        "lines": len(lines),
        "bounds": [max(line_widths, default=0.0), float(total_text_h)],
    }

    # Vertical alignment
    y_align = node.get("textYAlignment", "Center")
    if y_align == "Top":
        start_y = content_y + ascent
    elif y_align == "Bottom":
        start_y = content_y + content_h - total_text_h + ascent
    else:  # Center
        start_y = content_y + (content_h - total_text_h) / 2 + ascent

    # Horizontal alignment
    x_align = node.get("textXAlignment", "Center")

    # Text strokes (contextual UIStrokes — outlines behind the fill)
    stroke_paints: list[tuple[float, skia.Paint]] = []
    legacy_text_stroke = _build_legacy_text_stroke(node)
    if legacy_text_stroke is not None:
        stroke_paints.append(legacy_text_stroke)

    for s in node.get("strokes", []):
        if s.get("applyMode") == "Border":
            continue
        s_thickness = s.get("thickness", 1)
        if s.get("thicknessScale"):
            s_thickness = s_thickness * text_size
        s_thickness = s_thickness * stroke_thickness_scale
        s_color = s.get("color", [0, 0, 0])
        s_trans = s.get("transparency", 0)
        if s_thickness <= 0 or s_trans >= 1:
            continue
        sp = skia.Paint()
        sp.setAntiAlias(True)
        sp.setStyle(skia.Paint.kStroke_Style)
        sp.setStrokeWidth(_stroke_width_from_thickness(float(s_thickness)))
        join = str(s.get("lineJoin", "Round")).lower()
        sp.setStrokeJoin(_JOIN_MAP.get(join, skia.Paint.Join.kRound_Join))
        sr, sg, sb = int(s_color[0]), int(s_color[1]), int(s_color[2])
        s_alpha = round((1.0 - s_trans) * 255)
        s_grad = s.get("gradient") or gradient
        if s_grad:
            s_shader = make_gradient_shader(
                s_grad, x, y, w, h,
                base_color=(sr, sg, sb), base_transparency=s_trans,
            )
            if s_shader:
                sp.setShader(s_shader)
            else:
                sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        else:
            sp.setColor(skia.Color(sr, sg, sb, s_alpha))
        stroke_paints.append((s_thickness, sp))

    stroke_paints.sort(key=lambda t: t[0], reverse=True)

    max_stroke = max((t for t, _ in stroke_paints), default=0)
    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(
        content_x - max_stroke, content_y - max_stroke,
        content_w + max_stroke * 2, content_h + max_stroke * 2,
    ))

    name = node.get("_debug_path") or node.get("name") or node.get("type", "?")

    for i, line in enumerate(lines):
        baseline_y = start_y + i * line_step
        if table_mode:
            line_w = _string_width(adv_table, line, float(text_size)) or 0.0
        else:
            line_w = _measure_mixed(line, font, emoji_font, fallback_fonts)
        if x_align == "Left":
            line_x = content_x
        elif x_align == "Right":
            line_x = content_x + content_w - line_w
        else:  # Center
            line_x = content_x + (content_w - line_w) / 2

        if stroke_paints:
            stroke_bounds = skia.Rect.MakeXYWH(
                content_x - max_stroke * 2, content_y - max_stroke * 2,
                content_w + max_stroke * 4, content_h + max_stroke * 4,
            )
            _annotate(canvas, f"Text stroke layer: {name}")
            canvas.saveLayer(stroke_bounds)
            for _, sp in stroke_paints:
                _annotate(canvas, f"Text stroke: {name}")
                if table_mode:
                    draw_line_table(canvas, line, line_x, baseline_y, font, sp, adv_table)
                else:
                    _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, sp, fallback_fonts)
            # Roblox icon PUA glyphs keep clearer inner contour lines without knockout clear.
            if not _has_pua(line):
                clear_paint = skia.Paint()
                clear_paint.setAntiAlias(True)
                clear_paint.setBlendMode(skia.BlendMode.kDstOut)
                if table_mode:
                    draw_line_table(canvas, line, line_x, baseline_y, font, clear_paint, adv_table)
                else:
                    _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, clear_paint, fallback_fonts)
            canvas.restore()

        _annotate(canvas, f"Text fill: {name}")
        if table_mode:
            draw_line_table(canvas, line, line_x, baseline_y, font, paint, adv_table)
        else:
            _draw_mixed(canvas, line, line_x, baseline_y, font, emoji_font, paint, fallback_fonts)

    canvas.restore()


def draw_text(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
              node: dict, fonts_dir: Path | None = None,
              gradient: dict | None = None) -> None:
    """Render text within the given rect based on node properties."""
    if w <= 0 or h <= 0:
        return

    text = node.get("text", "")
    if not text:
        return

    text_gradient = gradient
    if gradient is not None:
        text_gradient = dict(gradient)
        text_gradient["rotation"] = (
            float(gradient.get("rotation", 0.0)) + _TEXT_GRADIENT_ROTATION_OFFSET_DEG
        )

    if node.get("richText"):
        _draw_text_rich(canvas, x, y, w, h, node, fonts_dir, text_gradient)
    else:
        _draw_text_plain(canvas, x, y, w, h, node, fonts_dir, text_gradient)


__all__ = [name for name in globals() if not name.startswith("__")]
