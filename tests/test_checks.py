#!/usr/bin/env python3
"""The checks: eight model smells, each fixture that trips it, pixels not internals.

Task 2.2: `rhr check` runs eight checks over a model and reports
findings as JSON; a build loop refuses to ship on error-class findings. Three
things are measured here, not claimed:

  * every check's fixture actually trips it (right check, right path, right
    severity), and a clean fixture reports nothing;
  * the truncation follow-up draws: TextTruncate AtEnd/SplitWord renders a
    shorter ink extent than the same label untruncated, ending in an
    ellipsis (glyph pixels, not internals);
  * findings are deterministic: two runs byte-identical.

Run: python tests/test_checks.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
RHR = [sys.executable, "-m", "rhr"]
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "out" / "checks"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def findings_for(fixture: str, viewport=(400, 300)) -> list[dict]:
    from rhr.checks import check_model

    result = check_model(FIXTURES / f"{fixture}.rbxmx", *viewport)
    return result["findings"]


def checks_of(findings: list[dict]) -> set[str]:
    return {f["check"] for f in findings}


def glyph_extent(png: Path, x0: int, x1: int, y0: int, y1: int) -> tuple[int, int]:
    from PIL import Image

    img = Image.open(png).convert("RGBA")
    xs = [
        x
        for y in range(y0, y1)
        for x in range(x0, x1)
        if (p := img.getpixel((x, y)))[3] > 0 and p[:3] != (163, 162, 165)
    ]
    return (min(xs), max(xs)) if xs else (-1, -1)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("checks: every fixture trips its check, clean fixtures stay silent")

    f = findings_for("text_overflow")
    check(
        "text-wider-than-box" in checks_of(f)
        and any(f0["severity"] == "warning" and f0["paths"] == ["TextOverflow/Root/TooWide"] for f0 in f),
        f"text_overflow trips text-wider-than-box (warning) at TooWide ({f})",
    )

    f = findings_for("zero_grid_cell")
    check(
        any(f0["check"] == "zero-size-grid-cell" and f0["severity"] == "error" for f0 in f),
        f"zero_grid_cell trips zero-size-grid-cell (error) ({f})",
    )

    f = findings_for("child_outside_clip")
    check("child-outside-clip" in checks_of(f), f"child_outside_clip trips child-outside-clip ({f})")

    f = findings_for("tiny_text")
    check(
        any(f0["check"] == "text-size-below-2px" and f0["severity"] == "error" for f0 in f),
        f"tiny_text trips text-size-below-2px (error) ({f})",
    )

    f = findings_for("invisible_content")
    invis = [f0 for f0 in f if f0["check"] == "invisible-content"]
    paths = {p for f0 in invis for p in f0["paths"]}
    check(
        {"InvisibleContent/Root/GhostBox", "InvisibleContent/Root/GhostText"} <= paths,
        f"invisible_content trips invisible-content for GhostBox and GhostText ({paths})",
    )

    f = findings_for("duplicate_zindex")
    dup = [f0 for f0 in f if f0["check"] == "duplicate-zindex"]
    check(
        len(dup) == 1 and set(dup[0]["paths"]) == {"DuplicateZIndex/Root/Card", "DuplicateZIndex/Root/Shade"},
        f"duplicate_zindex reports the Card/Shade pair ({dup})",
    )

    for fx, mode in (("text_truncate_at_end", "AtEnd"), ("text_truncate_split_word", "SplitWord")):
        f = findings_for(fx)
        trunc = [f0 for f0 in f if f0["check"] == "text-truncated"]
        check(
            bool(trunc) and mode in trunc[0]["detail"],
            f"{fx} trips text-truncated ({mode}) ({trunc})",
        )

    f = findings_for("max_visible_graphemes")
    g = [f0 for f0 in f if f0["check"] == "max-visible-graphemes"]
    check(
        bool(g) and g[0]["severity"] == "warning" and "typewriter" in g[0]["detail"],
        f"max_visible_graphemes trips as a typewriter warning, NOT an error ({g})",
    )

    clean = findings_for("grid_offset") + findings_for("panel_styles")
    check(not clean, f"clean fixtures (grid_offset, panel_styles) report nothing ({clean})")

    print("checks: the exit contract")

    def cli_exit(fixture: str) -> int:
        proc = subprocess.run(
            [*RHR, "check", str(FIXTURES / f"{fixture}.rbxmx"), "--viewport", "400x300"],
            capture_output=True, text=True, cwd=str(REPO), timeout=300,
        )
        return proc.returncode

    check(cli_exit("zero_grid_cell") == 1, "rhr check exits 1 on an error-class finding")
    check(cli_exit("duplicate_zindex") == 0, "rhr check exits 0 when only warnings fire")
    check(cli_exit("grid_offset") == 0, "rhr check exits 0 on a clean model")

    print("checks: the truncation follow-up draws (pixels, not internals)")

    # Same label, only TextTruncate differs, with a multi-word text (Roblox docs,
    # Enum.TextTruncate): AtEnd backs up to the end of the last complete word that
    # fits, SplitWord cuts inside the word, so AtEnd's ink ends strictly left of
    # SplitWord's, and neither goes past the untruncated clip.
    at_end_png = OUT / "text_truncate_at_end.png"
    split_png = OUT / "text_truncate_split_word.png"
    none_png = OUT / "trunc_none.png"
    words = "Extra ordinarily unbreakable word"
    variants = {}
    for name in ("text_truncate_at_end", "text_truncate_split_word"):
        src = (FIXTURES / f"{name}.rbxmx").read_text()
        variants[name] = src.replace("ExtraordinarilyUnbreakableWord", words)
    (FIXTURES / "_trunc_at_end.rbxmx").write_text(variants["text_truncate_at_end"])
    (FIXTURES / "_trunc_split.rbxmx").write_text(variants["text_truncate_split_word"])
    (FIXTURES / "_trunc_none.rbxmx").write_text(
        "\n".join(line for line in variants["text_truncate_at_end"].splitlines() if "TextTruncate" not in line) + "\n"
    )
    from rhr.layout_dump import build_dump
    from test_fixtures import emit_ir

    try:
        build_dump(emit_ir(FIXTURES / "_trunc_none.rbxmx"), 400, 300, png_path=none_png)
        build_dump(emit_ir(FIXTURES / "_trunc_at_end.rbxmx"), 400, 300, png_path=at_end_png)
        build_dump(emit_ir(FIXTURES / "_trunc_split.rbxmx"), 400, 300, png_path=split_png)
    finally:
        for name in ("_trunc_none", "_trunc_at_end", "_trunc_split"):
            (FIXTURES / f"{name}.rbxmx").unlink(missing_ok=True)

    none_lo, none_hi = glyph_extent(none_png, 0, 260, 58, 88)
    end_lo, end_hi = glyph_extent(at_end_png, 0, 260, 58, 88)
    split_lo, split_hi = glyph_extent(split_png, 0, 260, 58, 88)
    check(split_hi <= none_hi, f"SplitWord's ink stays within the untruncated clip ({split_hi} <= {none_hi})")
    check(end_hi < split_hi, f"AtEnd's ink ends left of SplitWord's: it keeps whole words ({end_hi} < {split_hi})")

    print("checks: findings are deterministic")
    import hashlib

    from rhr.checks import findings_json

    h1 = hashlib.sha256(findings_json({"model": "x", "findings": findings_for("duplicate_zindex")}).encode()).hexdigest()
    h2 = hashlib.sha256(findings_json({"model": "x", "findings": findings_for("duplicate_zindex")}).encode()).hexdigest()
    check(h1 == h2, "two runs of run_checks serialise byte-identical")

    print("checks: ok" if not failures else f"checks: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
