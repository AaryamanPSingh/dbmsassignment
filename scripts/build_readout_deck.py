#!/usr/bin/env python3
"""Build the deliverable 5 readout deck.

8-slide readout for the Product Director, followed by 7 appendix slides
covering deliverables 1-4b. Uses the figures already produced by the
per-deliverable chart scripts. No numbers are computed here; every value is
transcribed from the checked outputs in outputs/deliverable*/.

Run:
    python3 scripts/build_readout_deck.py
Output:
    outputs/deliverable5/readout.pptx
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "deliverable5" / "readout.pptx"

# ---------------------------------------------------------------- palette ---
NAVY = RGBColor(0x14, 0x21, 0x3D)
INK = RGBColor(0x1F, 0x29, 0x37)
GRAY = RGBColor(0x5C, 0x67, 0x73)
MUTED = RGBColor(0x8A, 0x94, 0xA6)
LIGHT = RGBColor(0xF2, 0xF4, 0xF7)
MID = RGBColor(0xE4, 0xE8, 0xEE)
LINE = RGBColor(0xD5, 0xDB, 0xE3)
TEAL = RGBColor(0x13, 0x7D, 0x76)
ORANGE = RGBColor(0xB8, 0x4A, 0x2A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE_TEAL = RGBColor(0xE6, 0xF2, 0xF0)
PALE_ORANGE = RGBColor(0xFB, 0xEC, 0xE7)

SW, SH = 13.333, 7.5
L = 0.7
CW = 11.933
FONT = "Arial"

FIG = ROOT / "outputs"


def figpath(*parts: str) -> str:
    return str(FIG.joinpath(*parts))


def blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def style_run(run, size=13, bold=False, color=INK, italic=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def textbox(
    slide,
    l,
    t,
    w,
    h,
    text="",
    size=13,
    bold=False,
    color=INK,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    line_spacing=1.0,
    space_after=0,
    italic=False,
):
    box = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = line
        style_run(r, size, bold, color, italic)
    return box


def bullets(slide, l, t, w, h, items, size=12.5, color=INK, gap=7, marker="•", marker_color=TEAL):
    box = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, item in enumerate(items):
        if isinstance(item, tuple):
            head, rest = item
        else:
            head, rest = None, item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.05
        p.space_after = Pt(gap)
        r = p.add_run()
        r.text = f"{marker}  "
        style_run(r, size, True, marker_color)
        if head:
            r = p.add_run()
            r.text = head
            style_run(r, size, True, color)
        r = p.add_run()
        r.text = rest
        style_run(r, size, False, color)
    return box


def kicker(slide, text, color=TEAL):
    textbox(slide, L, 0.36, CW, 0.28, text.upper(), size=10.5, bold=True, color=color)


def title(slide, text):
    textbox(slide, L, 0.64, CW, 0.72, text, size=30, bold=True, color=NAVY)


def accent_bar(slide, color=TEAL):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(L), Inches(1.40), Inches(1.05), Inches(0.055)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False


def takeaway(slide, text):
    textbox(slide, L, 1.55, CW, 0.60, text, size=15, color=GRAY, line_spacing=1.08)


def footer(slide, page, label="Telemetry readout · 2026-01-01 → 2026-04-30"):
    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(L), Inches(6.93), Inches(CW), Inches(0.012)
    )
    line.fill.solid()
    line.fill.fore_color.rgb = LINE
    line.line.fill.background()
    line.shadow.inherit = False
    textbox(slide, L, 7.03, 9.2, 0.24, label, size=9, color=MUTED)
    textbox(
        slide, L + CW - 0.8, 7.03, 0.8, 0.24, str(page), size=9, color=MUTED,
        align=PP_ALIGN.RIGHT,
    )


def stat_card(slide, l, t, w, h, value, label, accent=TEAL, value_size=27):
    card = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h)
    )
    card.adjustments[0] = 0.06
    card.fill.solid()
    card.fill.fore_color.rgb = LIGHT
    card.line.fill.background()
    card.shadow.inherit = False
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(l), Inches(t + 0.14), Inches(0.055), Inches(h - 0.28)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False
    textbox(slide, l + 0.22, t + 0.15, w - 0.34, 0.52, value, size=value_size, bold=True, color=NAVY)
    textbox(slide, l + 0.22, t + 0.68, w - 0.34, h - 0.74, label, size=10.5, color=GRAY, line_spacing=1.0)


def add_table(
    slide,
    l,
    t,
    w,
    col_widths,
    rows,
    row_h=0.40,
    header_h=0.42,
    font=11,
    header_font=10.5,
    aligns=None,
    header_fill=NAVY,
    first_col_bold=False,
    highlight_last=False,
):
    nrows, ncols = len(rows), len(rows[0])
    shape = slide.shapes.add_table(
        nrows, ncols, Inches(l), Inches(t), Inches(w), Inches(header_h + row_h * (nrows - 1))
    )
    table = shape.table
    table.horz_banding = False
    table.vert_banding = False
    total = sum(col_widths)
    for j, cw in enumerate(col_widths):
        table.columns[j].width = Inches(w * cw / total)
    table.rows[0].height = Inches(header_h)
    for i in range(1, nrows):
        table.rows[i].height = Inches(row_h)
    if aligns is None:
        aligns = [PP_ALIGN.LEFT] + [PP_ALIGN.CENTER] * (ncols - 1)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if i == 0:
                cell.fill.fore_color.rgb = header_fill
                color, bold, size = WHITE, True, header_font
            else:
                fill = WHITE if i % 2 == 1 else RGBColor(0xF7, 0xF8, 0xFA)
                if highlight_last and i == nrows - 1:
                    fill = PALE_TEAL
                cell.fill.fore_color.rgb = fill
                color, bold, size = INK, (first_col_bold and j == 0), font
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = aligns[j]
            p.line_spacing = 0.95
            r = p.add_run()
            r.text = str(val)
            style_run(r, size, bold, color)
    return shape


def picture(slide, path, l, t, w, h, border=False):
    """Fit an image inside the box, preserving aspect ratio and centring it."""
    with Image.open(path) as im:
        iw, ih = im.size
    ratio = iw / ih
    box_ratio = w / h
    if ratio >= box_ratio:
        pw, ph = w, w / ratio
    else:
        ph, pw = h, h * ratio
    pl = l + (w - pw) / 2
    pt = t + (h - ph) / 2
    pic = slide.shapes.add_picture(path, Inches(pl), Inches(pt), Inches(pw), Inches(ph))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(0.75)
    return pic, (pl, pt, pw, ph)


def caption(slide, l, t, w, text):
    textbox(slide, l, t, w, 0.26, text, size=9, color=MUTED, italic=True)


def panel(slide, l, t, w, h, fill=LIGHT, accent=None):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h)
    )
    shape.adjustments[0] = 0.05
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    if accent:
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(l), Inches(t + 0.16), Inches(0.05), Inches(h - 0.32)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()
        bar.shadow.inherit = False
    return shape


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


# ------------------------------------------------------------------ deck ---
def build():
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)

    # ---------------------------------------------------------- slide 1 ----
    s = blank(prs)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = NAVY
    textbox(s, L, 0.75, CW, 0.3, "PRODUCT READOUT  ·  NOVEMBER 2026", size=11, bold=True, color=RGBColor(0x8F, 0xC9, 0xC2))
    textbox(s, L, 1.20, 11.4, 1.75, "Growth is real.\nThe ARPDAU alarm is not.", size=40, bold=True, color=WHITE, line_spacing=1.02)
    textbox(
        s, L, 3.12, 10.6, 0.75,
        "What 120 days of telemetry says about retention, monetisation and the channels we buy — and what to do next.",
        size=17, color=RGBColor(0xC9, 0xD1, 0xDD), line_spacing=1.15,
    )
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(L), Inches(4.18), Inches(CW), Inches(2.18))
    box.adjustments[0] = 0.04
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0x1D, 0x2C, 0x4C)
    box.line.color.rgb = RGBColor(0x33, 0x46, 0x6B)
    box.line.width = Pt(0.75)
    box.shadow.inherit = False
    textbox(s, L + 0.35, 4.36, 4.0, 0.28, "THE BOTTOM LINE", size=10.5, bold=True, color=RGBColor(0x8F, 0xC9, 0xC2))
    b = bullets(
        s, L + 0.35, 4.72, CW - 0.7, 1.45,
        [
            ("Revenue +187% ", "between the first and last 30-day windows; ARPDAU −16.5% is a mix artefact, not monetisation decay."),
            ("Every tier monetises better than in January. ", "At January's mix, ARPDAU is +6.4%."),
            ("The channel “quality” gap collapses ", "from +60% to +5% (p = 0.52) once tier mix is equalised."),
        ],
        size=12.5, color=WHITE, gap=6, marker_color=RGBColor(0x8F, 0xC9, 0xC2),
    )
    textbox(s, L, 6.55, CW, 0.25, "8-slide readout · appendix covers deliverables 1–4b · source: telemetry.db, 2026-01-01 → 2026-04-30", size=9, color=RGBColor(0x8A, 0x9A, 0xB5))
    notes(s, "The answer in one slide: growth is genuine, the ratio alarm is composition, and the channel comparison is a tier-targeting story. Everything that follows supports those three sentences. The appendix has the numbers, the judgement calls and the dead ends.")

    # ---------------------------------------------------------- slide 2 ----
    s = blank(prs)
    kicker(s, "The paradox")
    title(s, "Revenue nearly tripled. ARPDAU fell 16.5%.")
    accent_bar(s)
    takeaway(s, "Both numbers are true. Active device-days grew faster than revenue, so neither headline alone is the business.")
    stat_card(s, 0.70, 2.24, 3.78, 1.22, "+186.6%", "gross IAP revenue, first vs last 30 days")
    stat_card(s, 4.78, 2.24, 3.78, 1.22, "+243.1%", "active device-days", accent=ORANGE)
    stat_card(s, 8.86, 2.24, 3.78, 1.22, "−16.5%", "ARPDAU (revenue per active device-day)", accent=ORANGE)
    add_table(
        s, L, 3.76, 8.35, [2.6, 1.5, 1.5, 1.5],
        [
            ["", "Jan 1–30", "Apr 1–30", "change"],
            ["Active device-days", "82,694", "283,727", "+243.1%"],
            ["Gross IAP revenue", "$29,189", "$83,648", "+186.6%"],
            ["ARPDAU", "$0.3530", "$0.2948", "−16.5%"],
            ["Payer share", "2.40%", "2.07%", "−13.9% rel"],
            ["ARPPU (per purchasing day)", "$14.70", "$14.26", "−3.0%"],
        ],
        row_h=0.39, font=11.5,
        aligns=[PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
        first_col_bold=True,
    )
    panel(s, 9.35, 3.76, 3.28, 2.37, fill=PALE_TEAL, accent=TEAL)
    textbox(s, 9.58, 3.93, 2.85, 0.26, "THE RATIO TRAP", size=10, bold=True, color=TEAL)
    textbox(
        s, 9.58, 4.24, 2.85, 1.65,
        "ARPDAU = payer share × revenue per payer-day\n\n0.861 × 0.970 = 0.835\n\nMoney per player barely moved (−3%). The payer base diluted as the mix shifted.",
        size=11.5, color=INK, line_spacing=1.12,
    )
    footer(s, 2)
    notes(s, "January and April are the first and last 30-day windows. Revenue rose 187% but device-days rose 243%, so ARPDAU mechanically fell. Payer share fell 13.9% relative, while revenue per payer-day fell only 3%. That gap is the clue: the denominator, not monetisation, is doing the damage.")

    # ---------------------------------------------------------- slide 3 ----
    s = blank(prs)
    kicker(s, "Decomposition")
    title(s, "Every tier improved. The blend fell.")
    accent_bar(s)
    takeaway(s, "Textbook Simpson's paradox: within every tier, ARPDAU and payer share rose. Tier 4's share of device-days went from 17.6% to 45.9%.")
    add_table(
        s, L, 2.28, 6.55, [0.9, 1.75, 1.1, 1.6],
        [
            ["Tier", "ARPDAU Jan → Apr", "change", "share of device-days"],
            ["1", "$0.516 → $0.552", "+7.0%", "34.5% → 20.5%"],
            ["2", "$0.372 → $0.401", "+7.9%", "26.1% → 15.6%"],
            ["3", "$0.233 → $0.260", "+11.6%", "21.8% → 18.0%"],
            ["4", "$0.154 → $0.158", "+2.3%", "17.6% → 45.9%"],
        ],
        row_h=0.48, font=12, header_font=10.5,
        aligns=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
    )
    picture(s, figpath("deliverable2", "figs", "fig2a_waterfall.png"), 7.45, 2.28, 5.2, 2.73)
    caption(s, 7.45, 5.06, 5.2, "fig2a — mix and within effects on ARPDAU; bars sum to the headline, no residual.")
    panel(s, L, 5.28, 6.55, 1.32, fill=LIGHT, accent=ORANGE)
    textbox(
        s, 0.95, 5.42, 6.15, 1.05,
        "Tier 4 earns about 30% as much per device-day as tier 1. Tripling its weight lowers the blended rate even though every tier improved.",
        size=12.5, color=INK, line_spacing=1.12,
    )
    footer(s, 3)
    notes(s, "This is the core finding. Tier 4 went from 17.6% to 45.9% of device-days as paid_video scaled. Because tier 4 monetises at roughly a third of tier 1, the blend falls while all four tiers improve. The waterfall has no unexplained bar — mix plus within equals the headline exactly.")

    # ---------------------------------------------------------- slide 4 ----
    s = blank(prs)
    kicker(s, "The fix")
    title(s, "At January's mix, ARPDAU rose 6.4%.")
    accent_bar(s)
    takeaway(s, "Hold the tier mix constant and the decline disappears. The mix shift costs about $22.9k of IAP per 30 days.")
    picture(s, figpath("deliverable2", "figs", "fig2d_constant_mix.png"), L, 2.24, 8.55, 3.99, border=False)
    caption(s, L, 6.30, 8.55, "fig2d — observed ARPDAU vs ARPDAU held at January's tier mix. The gap is composition.")
    cards = [
        ("−$0.0806", "mix effect (−22.8% of January ARPDAU)", ORANGE, PALE_ORANGE),
        ("+$0.0224", "within-tier effect (+6.4%)", TEAL, PALE_TEAL),
        ("−$0.0582", "net change (−16.5%), exactly", NAVY, LIGHT),
        ("$0.3754", "Apr ARPDAU at Jan mix, vs $0.3530", TEAL, PALE_TEAL),
    ]
    y = 2.24
    for value, label, accent, fill in cards:
        panel(s, 9.55, y, 3.08, 0.92, fill=fill, accent=accent)
        textbox(s, 9.75, y + 0.10, 2.75, 0.34, value, size=18, bold=True, color=NAVY)
        textbox(s, 9.75, y + 0.45, 2.78, 0.40, label, size=9.5, color=GRAY, line_spacing=1.0)
        y += 1.02
    footer(s, 4)
    notes(s, "The mix effect is −$0.0806 and the within effect is +$0.0224; they sum to −$0.0582. If January's tier shares had held, April ARPDAU would have been $0.3754 — 6.4% above January, not 16.5% below. In revenue terms the mix shift costs about $22.9k per 30 days. This is a reporting fix, not a product fix.")

    # ---------------------------------------------------------- slide 5 ----
    s = blank(prs)
    kicker(s, "Acquisition")
    title(s, "The channel gap is a tier-targeting gap.")
    accent_bar(s)
    takeaway(s, "Naive, organic looks 60% better than paid_video. On the same tier mix, the gap is +5% and statistically indistinguishable from zero.")
    picture(s, figpath("deliverable3", "figs", "fig3c_forest.png"), L, 2.26, CW, 2.79)
    caption(s, L, 5.08, 11.5, "fig3c — naive vs tier-standardised differences; the revenue advantage vanishes after adjustment.")
    pills = [
        ("Revenue / install", "+$0.92 naive (+59.7%, p<1e-4)  →  +$0.10 adjusted (+5.0%, p=0.52)", ORANGE, PALE_ORANGE),
        ("Payer rate", "+4.45 pp naive  →  +0.72 pp adjusted [−0.20, +1.59], p=0.12", NAVY, LIGHT),
        ("Engagement", "+1.5 pp D7 and +0.7 min/day survive correction — real, but small", TEAL, PALE_TEAL),
    ]
    x = L
    for head, body, accent, fill in pills:
        panel(s, x, 5.42, 3.83, 1.06, fill=fill, accent=accent)
        textbox(s, x + 0.18, 5.51, 3.5, 0.24, head.upper(), size=9, bold=True, color=accent)
        textbox(s, x + 0.18, 5.78, 3.52, 0.64, body, size=10.5, color=INK, line_spacing=1.08)
        x += 3.98
    footer(s, 5)
    notes(s, "As bought, organic returns $2.46 per install and paid_video $1.54 — a real cash difference of 60% if CPIs are equal. But once every channel is scored on the same tier mix, the gap is $0.10, p=0.52. paid_video is not buying worse players; it is buying tier-4 players. The decision needs CPI, and the actionable test is re-targeting, not cutting the channel.")

    # ---------------------------------------------------------- slide 6 ----
    s = blank(prs)
    kicker(s, "Retention")
    title(s, "Retention held through a 13× install ramp.")
    accent_bar(s)
    takeaway(s, "D1, D7 and D30 sit within ±3 pp of their 16-cohort means through a 13× ramp. This is not a player-quality problem.")
    for i, (v, lab) in enumerate([("47.8%", "D1 retention"), ("25.6%", "D7 retention"), ("19.7%", "D14 retention"), ("14.2%", "D30 retention")]):
        stat_card(s, 0.70 + i * 3.03, 2.24, 2.86, 1.10, v, lab + ", 16-cohort mean")
    picture(s, figpath("deliverable1", "figs", "fig1b_retention.png"), L, 3.60, 6.50, 2.78)
    caption(s, L, 6.46, 6.50, "fig1b — install-week retention; cells are populated only where the full window is observed.")
    bullets(
        s, 7.72, 3.62, 4.9, 2.85,
        [
            ("Install volume: ", "507/week in December → 6,543/week in late April."),
            ("D1 spread: ", "46.2–50.4% with no trend in either direction."),
            ("D30 moves only ", "12.4–16.8% across the ramp."),
            ("Implication: ", "don't blame the ratio on retention; the base changed, not the players."),
        ],
        size=12, gap=8,
    )
    footer(s, 6)
    notes(s, "Retention is remarkably stable across a 13-fold install ramp. D1 is 47.8%, D7 25.6%, D30 14.2%, and no cohort sits more than 2.7 pp from its mean. That rules out a quality collapse as the explanation for ARPDAU and points squarely at composition.")

    # ---------------------------------------------------------- slide 7 ----
    s = blank(prs)
    kicker(s, "Recommendations")
    title(s, "Fix the KPI. Protect the growth. Test the models.")
    accent_bar(s)
    takeaway(s, "None of these needs new data science; two need data we don't have yet, and one needs a holdout.")
    cards = [
        ("1 · MEASURE", "Report a constant-mix ARPDAU",
         ["Publish ARPDAU alongside an index rebased to January's tier shares.",
          "Restate history at fixed weights so the ramp stops looking like decay.",
          "Do not run monetisation rescue promos for a ratio artefact."], TEAL, PALE_TEAL),
        ("2 · ACQUIRE", "Don't cut paid_video on ARPDAU",
         ["The as-bought gap is a real cash difference only if CPIs are equal.",
          "Pull CPI and ad revenue by channel; re-run the comparison against cost.",
          "Test re-targeting paid_video toward tiers 1–2 — that is where the gap lives."], ORANGE, PALE_ORANGE),
        ("3 · MODEL", "Pilot, don't price",
         ["Churn: top-10% pilot with a holdout; set p* = c/(e·V) per campaign.",
          "Value: rank installs, never quote per-install dollars.",
          "Retrain the value model on a representative cohort before bidding."], NAVY, LIGHT),
    ]
    x = L
    for tag, head, items, accent, fill in cards:
        panel(s, x, 2.26, 3.78, 3.62, fill=fill, accent=accent)
        textbox(s, x + 0.22, 2.44, 3.3, 0.24, tag, size=9.5, bold=True, color=accent)
        textbox(s, x + 0.22, 2.72, 3.35, 0.62, head, size=16, bold=True, color=NAVY, line_spacing=1.0)
        bullets(s, x + 0.22, 3.42, 3.34, 2.25, items, size=11.5, gap=7)
        x += 3.98
    panel(s, L, 6.04, CW, 0.66, fill=NAVY)
    textbox(
        s, L + 0.25, 6.18, CW - 0.5, 0.40,
        "The common thread: measure the mix, price the acquisition, and treat both models as ranking tools with a measured effect — not autonomous dollar machines.",
        size=12, color=WHITE,
    )
    footer(s, 7)
    notes(s, "Three workstreams. Measurement is free and immediate. Acquisition needs the CPI table before anyone cuts spend; the test is targeting, not a channel verdict. Modelling stays in pilot mode: the churn model only pays if the offer economics clear p*, and the value model cannot support per-install pricing.")

    # ---------------------------------------------------------- slide 8 ----
    s = blank(prs)
    kicker(s, "Uncertainty", color=ORANGE)
    title(s, "What we can't see — and what would change it.")
    accent_bar(s, color=ORANGE)
    takeaway(s, "The analysis is descriptive, not causal. Five gaps bound how far the recommendations can be pushed.")
    rows = [
        ("No CPI or spend by channel", "We can rank revenue per install; we cannot compute ROI. The as-bought gap is not a quality verdict."),
        ("No ad or subscription revenue", "IAP-only understates LTV, especially for tier 4, whose ad engagement is roughly 2× but unpriced."),
        ("No experiment", "Selection and incrementality are unidentified. Both models rank; neither proves that acting creates value."),
        ("A January-only value cohort", "9,494 of 64,295 in-window installs (14.8%) are labelable — January's organic-heavy traffic, not today's paid_video mix."),
        ("Data-quality gaps", "1,114 never-active installs, purchase-day coverage missing 16.4% of gross, and a 48-hour ad outage; bracketed, not removed."),
    ]
    y = 2.20
    for i, (head, body) in enumerate(rows, 1):
        textbox(s, L, y + 0.05, 0.45, 0.35, str(i), size=17, bold=True, color=ORANGE)
        textbox(s, L + 0.48, y + 0.02, 3.55, 0.62, head, size=13.5, bold=True, color=NAVY, line_spacing=1.02)
        textbox(s, 4.75, y + 0.03, 7.8, 0.62, body, size=12, color=INK, line_spacing=1.08)
        if i < len(rows):
            line = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(L), Inches(y + 0.76), Inches(CW), Inches(0.008))
            line.fill.solid()
            line.fill.fore_color.rgb = LINE
            line.line.fill.background()
            line.shadow.inherit = False
        y += 0.80
    panel(s, L, 6.10, CW, 0.60, fill=PALE_ORANGE, accent=ORANGE)
    textbox(
        s, L + 0.25, 6.21, CW - 0.5, 0.38,
        "One CPI table and one geo-holdout would change the answer more than another model iteration.",
        size=12.5, bold=True, color=NAVY,
    )
    footer(s, 8)
    notes(s, "The honest boundary. Revenue is IAP only; cost is absent; assignment is not random; the value model sees only January. State these before anyone turns the ranking into a budget. The two inputs that would most change the decision are CPI by channel and a geo-holdout.")

    # =========================================================== APPENDIX ==
    # ------------------------------------------------------------- A1 -----
    s = blank(prs)
    kicker(s, "Appendix · Data quality & judgements")
    title(s, "Three traps that make plausible numbers wrong")
    accent_bar(s)
    takeaway(s, "Eight issues found in profiling. Four would silently corrupt denominators or revenue; four are bracketed rather than smoothed.")
    left = [
        ("Q1 · timestamps. ", "13% of rows lack a leading zero hour; SQLite DATE() returns NULL and drops them silently. Zero-padded at load."),
        ("Q3 · duplicate purchases. ", "122 repeated purchase IDs; $1,815.82 (0.8% of revenue). Deduplicated by purchase_id."),
        ("Q4 · purchase days missing from player_day. ", "2,449 positive rows, $35,732.51 = 16.4% of gross. Active = player_day ∪ purchase days."),
        ("Q5 · ad clock offset. ", "Ad timestamps run 8 h ahead. Device-day match with player_day: 49.1% raw → 100% after shifting −8 h."),
    ]
    right = [
        ("Q2 · refunds. ", "228 rows, −$3,274.72. Gross counts positives only; refunds reported separately (1.5% of gross)."),
        ("Q6 · ad outage. ", "48 hours with zero ad rows (Mar 5–6) while play continued. Kept as explicit zeros; excluded from trend claims."),
        ("Q7 · install ramp. ", "507/week in December → 6,543/week in late April (13×). Cohort denominators and mix shift with it."),
        ("Q8 · censoring. ", "Never-paid: Jan 75.9% → Apr 93.7%. 110 payers pre-date install; 1,114 installs never active; subscriptions sit outside purchase."),
    ]
    bullets(s, L, 2.24, 5.55, 3.55, left, size=10.5, gap=9)
    bullets(s, 6.55, 2.24, 5.95, 3.55, right, size=10.5, gap=9)
    panel(s, L, 5.95, CW, 0.82, fill=NAVY)
    textbox(s, L + 0.22, 6.08, CW - 0.44, 0.58,
            "JUDGEMENT CALLS, applied to every deliverable:  zero-pad timestamps  ·  dedup purchase_id  ·  gross = positive usd_amount  ·  active = player_day ∪ purchase days  ·  ads shifted −8 h",
            size=10.5, color=WHITE, line_spacing=1.05)
    footer(s, "A1", "Appendix · data quality and judgement calls")
    notes(s, "Four issues change numbers if ignored: timestamp parsing, duplicate IDs, purchase days missing from player_day, and the ad clock offset. The other four are disclosed and bracketed. These definitions are carried unchanged through every deliverable, which is why the numbers reconcile.")

    # ------------------------------------------------------------- A2 -----
    s = blank(prs)
    kicker(s, "Appendix · Deliverable 1")
    title(s, "Retention is stable; spend is concentrated")
    accent_bar(s)
    picture(s, figpath("deliverable1", "figs", "fig1b_retention.png"), L, 2.24, 6.6, 3.55)
    caption(s, L, 5.88, 6.6, "fig1b — D1/D7/D14/D30 by install week; only fully observed cells are shown.")
    bullets(
        s, 7.55, 2.24, 5.05, 4.35,
        [
            ("Retention: ", "D1 47.8%, D7 25.6%, D14 19.7%, D30 14.2% across 16 cohorts; every cohort within ±3 pp of the mean."),
            ("Revenue concentration: ", "11,054 IAP payers. Top 1% = 9.3% of payer revenue; top 10% = 47.9%; bottom half = 9.8%."),
            ("First purchase: ", "median 13 days after install; 36.7% within 7 days; 12.9% of in-window installs ever pay."),
            ("Ads: ", "completed ads per 100 DAU rose 73 → 87; cap hit only 0.54% of watch days."),
            ("Two ad-dark days ", "(Mar 5–6) flagged, not smoothed."),
        ],
        size=11.5, gap=8,
    )
    footer(s, "A2", "Appendix · Deliverable 1")
    notes(s, "Deliverable 1 established the denominators and the stability of retention. It also showed that spend is concentrated: the top decile of payers is nearly half of payer revenue. The ad cap is almost never binding, so 'cap hit' is not the lever it looks like.")

    # ------------------------------------------------------------- A3 -----
    s = blank(prs)
    kicker(s, "Appendix · Deliverable 2")
    title(s, "The decomposition is exact — no residual")
    accent_bar(s)
    add_table(
        s, L, 2.24, 6.15, [0.7, 1.5, 1.5],
        [
            ["Tier", "mix effect", "within effect"],
            ["1", "−0.07472", "+0.00988"],
            ["2", "−0.04058", "+0.00608"],
            ["3", "−0.00934", "+0.00536"],
            ["4", "+0.04405", "+0.00110"],
            ["Total", "−0.08058", "+0.02243"],
        ],
        row_h=0.40, font=11.5, header_font=10.5,
        aligns=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
        highlight_last=True,
    )
    picture(s, figpath("deliverable2", "figs", "fig2c_install_mix.png"), 7.05, 2.24, 5.58, 2.36)
    caption(s, 7.05, 4.62, 5.58, "fig2c — install mix over time; paid_video is the tier-4 engine.")
    textbox(s, L, 5.02, 6.15, 1.55,
            "Counterfactual at April's 283,727 device-days:\n"
            "• No mix shift: $0.3754 ARPDAU, +$22,864 (+27.3%)\n"
            "• No within change: $0.2724, −$6,363 (−7.6%)\n"
            "• Actual: $0.2948, $83,648",
            size=11, color=INK, line_spacing=1.18)
    bullets(s, 7.05, 5.02, 5.58, 1.55,
            [("Checks 9/9. ", "Mix + within = headline to 6 dp; tier sums equal headline device-days and gross; 4/4 tiers improved."),
             ("Reconciles to D1: ", "$217,593.22 gross; January ARPDAU 0.3530 vs 0.3509 (31 vs 30 days).")],
            size=10.5, gap=7)
    footer(s, "A3", "Appendix · Deliverable 2")
    notes(s, "The shift-share identity is exact. Tier 4's positive mix term is the only one that pushes ARPDAU up — it is the weight moving toward the cheapest tier. The counterfactual translates that into $22.9k per 30 days. The checks reconcile the decomposition and the gross revenue with deliverable 1.")

    # ------------------------------------------------------------- A4 -----
    s = blank(prs)
    kicker(s, "Appendix · Deliverable 3")
    title(s, "Adjusted, the revenue gaps are not significant")
    accent_bar(s)
    add_table(
        s, L, 2.22, CW, [2.6, 2.55, 3.55, 1.1, 2.1],
        [
            ["comparison", "naive Δ revenue/install", "tier-standardised Δ [95% CI]", "p", "verdict"],
            ["organic − paid_video", "+$0.921  (+59.7%)", "+$0.103  [−0.212, +0.406]", "0.52", "no resolved difference"],
            ["paid_social − paid_video", "+$0.675  (+43.8%)", "−$0.088  [−0.406, +0.221]", "0.58", "no resolved difference"],
            ["organic − paid_social", "+$0.246  (+11.1%)", "+$0.191  [−0.063, +0.436]", "0.13", "underpowered"],
        ],
        row_h=0.52, font=10.5, header_font=9.5,
        aligns=[PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
        first_col_bold=True,
    )
    bullets(
        s, L, 4.55, 5.8, 2.25,
        [
            ("~89% of the naive revenue gap disappears ", "after tier standardisation."),
            ("Payer rate: ", "4.45 pp naive → 0.72 pp adjusted [−0.20, +1.59], p = 0.12."),
            ("Engagement is the only thing that survives: ", "+1.5 pp D7 and +0.7 min/day, robust to 18 tests (Bonferroni α = 0.0028)."),
        ],
        size=11, gap=8,
    )
    panel(s, 6.75, 4.55, 5.88, 2.10, fill=PALE_TEAL, accent=TEAL)
    textbox(s, 6.98, 4.72, 5.45, 0.26, "WHAT WOULD CHANGE THE ANSWER", size=9.5, bold=True, color=TEAL)
    textbox(
        s, 6.98, 5.02, 5.45, 1.50,
        "CPI and spend by channel. A channel returning half the revenue at a quarter of the CPI is the better buy. The defensible action is to pull cost data and test re-targeting paid_video to tiers 1–2 — not to switch channels on quality.",
        size=11, color=INK, line_spacing=1.15,
    )
    footer(s, "A4", "Appendix · Deliverable 3")
    notes(s, "All three pairwise revenue comparisons collapse after tier standardisation. The engagement edge for organic over paid_video is real but small; it survives multiple-comparison correction and still would not move LTV enough to offset a small CPI difference. The missing cost table is the decision-critical input.")

    # ------------------------------------------------------------- A5 -----
    s = blank(prs)
    kicker(s, "Appendix · Deliverable 4a")
    title(s, "Churn is mostly a tenure curve")
    accent_bar(s)
    add_table(
        s, L, 2.22, 6.35, [2.4, 1.6, 1.6],
        [
            ["test snapshot (Apr 8)", "estimate", "95% CI"],
            ["AUC", "0.742", "[0.728, 0.757]"],
            ["PR-AUC (base 14.55%)", "0.333", "[0.307, 0.359]"],
            ["Brier / log loss", "0.1124 / 0.3691", "—"],
            ["tenure-only AUC", "0.7409", "—"],
            ["full model AUC (22 predictors)", "0.7424", "—"],
        ],
        row_h=0.38, font=11, header_font=9.5,
        aligns=[PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
        first_col_bold=True,
    )
    bullets(
        s, L, 4.72, 6.35, 2.05,
        [
            ("Targeting: ", "top 5% = 46.9% precision, 3.23× lift; top 10% = 40.2%, 2.76×; top 20% = 33.9%, 2.33×."),
            ("Threshold: ", "p* = c/(e·V). At c=$1, e=5%, V=$50 → 40% ≈ top 10%; cost per save $49.80."),
            ("Caveat: ", "top decile is over-predicted (47.3% vs 40.2%); recalibrate before using probabilities in a budget."),
        ],
        size=10.5, gap=7,
    )
    picture(s, figpath("deliverable4", "figs", "fig4c_gain.png"), 7.35, 2.22, 5.28, 3.36)
    caption(s, 7.35, 5.63, 5.28, "fig4c — cumulative gain: the model finds churners early, but 60% of the top decile does not churn.")
    footer(s, "A5", "Appendix · Deliverable 4a")
    notes(s, "The churn model ranks at AUC 0.742, but a one-variable tenure logistic gets 0.7409. The other 21 predictors add 0.0015 of AUC and improve calibration. So the honest description is a well-calibrated tenure curve plus a little within-tenure ordering. The threshold economics, not the AUC, decide whether to deploy it.")

    # ------------------------------------------------------------- A6 -----
    s = blank(prs)
    kicker(s, "Appendix · Deliverable 4b (optional)")
    title(s, "90-day value is rankable; dollars are not")
    accent_bar(s)
    bullets(
        s, L, 2.22, 6.9, 4.3,
        [
            ("Labelable cohort: ", "9,494 installs (14.8% of 64,295 in-window). Train/validation/test 4,401 / 1,944 / 3,149."),
            ("Payer ranking: ", "test AUC 0.702 [0.676, 0.725], PR-AUC 0.549, top-10% revenue lift 4.34× [3.77, 4.98], capture 43.5%."),
            ("Amount model fails: ", "MAE $21.05, RMSE $36.46, within-payer Spearman 0.266; two-part score adds nothing over payer probability (43.5% vs 43.8% capture)."),
            ("Simple baseline is strong: ", "first-week spend alone has Spearman 0.475 and 41.0% top-10% capture; the model gains 2.5 pp of capture but ranks worse globally."),
            ("Bid ceiling at 30% margin: ", "top 5% $9.67, top 10% $5.88, top 20% $3.68 per install — a ceiling, not a target."),
        ],
        size=11, gap=8,
    )
    picture(s, figpath("deliverable4", "figs", "fig4b2_lift.png"), 7.95, 2.22, 4.68, 3.05)
    caption(s, 7.95, 5.36, 4.68, "fig4b2 — expected-value lift: top 10% returns 4.34× random.")
    panel(s, L, 6.02, CW, 0.62, fill=PALE_ORANGE, accent=ORANGE)
    textbox(s, L + 0.24, 6.14, CW - 0.48, 0.40,
            "Use it to rank who to bid on, not to price an install. Retrain on a representative cohort before touching live spend.",
            size=11.5, bold=True, color=NAVY)
    footer(s, "A6", "Appendix · Deliverable 4b")
    notes(s, "The optional deliverable is a negative result worth keeping: payer probability is predictable at AUC 0.70, but the amount stage is close to noise. A first-week-spend rule is a strong baseline. The only defensible output is a ranking and a bid ceiling from observed decile means.")

    # ------------------------------------------------------------- A7 -----
    s = blank(prs)
    kicker(s, "Appendix · Close")
    title(s, "Dead ends, limits, and the next week")
    accent_bar(s)
    textbox(s, L, 2.18, 5.6, 0.28, "DEAD ENDS — TESTED AND REJECTED", size=9.5, bold=True, color=ORANGE)
    bullets(
        s, L, 2.50, 5.55, 2.9,
        [
            "Single regression on 90-day dollars: 77% zeros, predicts near-zero for everyone.",
            "Two-part amount stage: does not rank within payers (Spearman 0.266).",
            "Per-install dollar pricing: expected-value top decile over-predicted by 31%.",
            "ARPDAU rescue promos: every tier improved; the ratio is composition.",
            "Channel quality verdict without CPI: adjusted gaps are indistinguishable from zero.",
            "“Never paid” as a lifetime rate: 75.9% (Jan) vs 93.7% (Apr) is follow-up length.",
        ],
        size=10.5, gap=6,
    )
    textbox(s, 6.7, 2.18, 5.8, 0.28, "WITH ANOTHER WEEK", size=9.5, bold=True, color=TEAL)
    bullets(
        s, 6.7, 2.50, 5.8, 2.9,
        [
            "Longer extract: representative install cohort and true 90-day LTV.",
            "CPI / spend by channel × tier × day: turns the revenue gap into ROI.",
            "Ad-revenue and subscription revenue joined to device_id.",
            "Geo-holdout to separate selection from incremental value.",
            "Recalibrate the churn top decile; ship the payer-only value score.",
        ],
        size=10.5, gap=6,
    )
    panel(s, L, 5.55, CW, 1.12, fill=NAVY)
    textbox(s, L + 0.24, 5.68, CW - 0.48, 0.9,
            "Reproduce:  python3 scripts/load_data.py  →  per-deliverable run_*.py / charts_*.py\n"
            "Checks:  D1 11/11   ·   D2 9/9   ·   D3 10/10   ·   D4a 11/11   ·   D4b 10/10        Deck built by scripts/build_readout_deck.py",
            size=10.5, color=WHITE, line_spacing=1.25)
    footer(s, "A7", "Appendix · close")
    notes(s, "Close with what failed and what we would do next. The highest-value additions are a longer extract and a cost table — not more modelling. Every deliverable has passing reconciliation checks, and the deck is generated by a script in the repo.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT} — {len(prs.slides)} slides")


if __name__ == "__main__":
    build()
