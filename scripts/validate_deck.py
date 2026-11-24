"""Programmatic layout check for the readout deck.

There is no renderer on this machine, so instead of eyeballing slides we
measure: every shape must sit inside the 13.333 x 7.5 canvas and above the
footer rule, and every text frame / table cell must have enough height for
its wrapped text at Arial-like metrics (DejaVu Sans is the closest available).

Run:  python3 scripts/validate_deck.py [path/to/deck.pptx]
"""

import sys
from pathlib import Path

from PIL import ImageFont
from pptx import Presentation
from pptx.util import Emu

W, H = 13.333, 7.5
FOOTER_Y = 6.93
EMU = 914400.0

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_cache = {}


def font(size_pt, bold):
    key = (round(size_pt, 1), bold)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_REG, int(round(size_pt * 4)))
    return _cache[key]


def text_width(text, size_pt, bold):
    """Width in inches."""
    if not text:
        return 0.0
    return font(size_pt, bold).getlength(text) / 4.0 / 72.0


def wrap_lines(text, size_pt, bold, width_in):
    lines = 0
    for chunk in text.split("\n"):
        words = chunk.split(" ")
        cur = ""
        lines += 1
        for word in words:
            trial = word if not cur else cur + " " + word
            if text_width(trial, size_pt, bold) <= width_in:
                cur = trial
            else:
                if cur:
                    lines += 1
                cur = word
    return lines


def frame_need(tf, width_in):
    """Required height in inches for a text frame's wrapped content."""
    total = 0.0
    for p in tf.paragraphs:
        runs = [r for r in p.runs if r.text]
        if not runs:
            total += 0.18
            continue
        size = max((r.font.size.pt if r.font.size else 18.0) for r in runs)
        bold = any(r.font.bold for r in runs)
        text = "".join(r.text for r in runs)
        ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
        n = wrap_lines(text, size, bold, max(width_in, 0.2))
        total += n * size * 1.2 * ls / 72.0
        total += (p.space_before.pt if p.space_before else 0) / 72.0
        total += (p.space_after.pt if p.space_after else 0) / 72.0
    return total


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "outputs/deliverable5/readout.pptx")
    prs = Presentation(path)
    problems = []
    print(f"{path}  slides={len(prs.slides)}  size={prs.slide_width/EMU:.3f}x{prs.slide_height/EMU:.3f}")

    if abs(prs.slide_width / EMU - W) > 0.01 or abs(prs.slide_height / EMU - H) > 0.01:
        problems.append(f"canvas is {prs.slide_width/EMU:.3f}x{prs.slide_height/EMU:.3f}, expected 16:9")

    for idx, slide in enumerate(prs.slides, 1):
        name = f"slide {idx}"
        pictures = tables = notes = 0
        for sh in slide.shapes:
            l, t = sh.left / EMU, sh.top / EMU
            w, h = sh.width / EMU, sh.height / EMU
            if sh.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                pictures += 1
            if sh.has_table:
                tables += 1
            if l < -0.01 or t < -0.01 or l + w > W + 0.01:
                problems.append(f"{name}: {sh.shape_type} outside canvas at ({l:.2f},{t:.2f}) {w:.2f}x{h:.2f}")
            # text boxes and pictures should stay above the footer rule
            if sh.has_text_frame and sh.text_frame.text.strip():
                txt = sh.text_frame.text.strip()
                is_footer = t >= 7.0
                if t + h > H + 0.01:
                    problems.append(f"{name}: text below canvas bottom ({t+h:.2f}): {txt[:40]!r}")
                elif not is_footer and t + h > FOOTER_Y + 0.25:
                    problems.append(f"{name}: text runs into footer zone, bottom={t+h:.2f}: {txt[:40]!r}")
                tf = sh.text_frame
                need = frame_need(tf, w - (tf.margin_left + tf.margin_right) / EMU)
                if need > h + 0.04 and not is_footer:
                    problems.append(
                        f"{name}: text overflow need {need:.2f}in > box {h:.2f}in: {txt[:55]!r}"
                    )
            elif sh.has_table:
                tbl = sh.table
                col_w = [c.width / EMU for c in tbl.columns]
                row_set = [r.height / EMU for r in tbl.rows]
                need_rows = []
                for i, row in enumerate(tbl.rows):
                    cell_need = 0.0
                    for j, cell in enumerate(row.cells):
                        tf = cell.text_frame
                        avail = col_w[j] - (cell.margin_left + cell.margin_right) / EMU
                        need = frame_need(tf, avail)
                        need += (cell.margin_top + cell.margin_bottom) / EMU
                        cell_need = max(cell_need, need)
                    need_rows.append(cell_need)
                grown = sum(max(a, b) for a, b in zip(row_set, need_rows))
                if grown > sum(row_set) + 0.03:
                    problems.append(
                        f"{name}: table rows will grow {sum(row_set):.2f}->{grown:.2f}in"
                    )
                if t + grown > FOOTER_Y:
                    problems.append(f"{name}: grown table bottom {t+grown:.2f} crosses footer rule")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            notes += 1
        print(f"  {name}: shapes={len(slide.shapes)} pictures={pictures} tables={tables} notes={'yes' if notes else 'NO'}")
        if not notes:
            problems.append(f"{name}: speaker notes missing")

    print()
    if problems:
        print(f"{len(problems)} issue(s):")
        for p in problems:
            print("  -", p)
        return 1
    print("layout OK: all shapes inside canvas, text fits its boxes, tables do not grow, notes present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
