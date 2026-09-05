# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - sheetdraw.py

SVG generation for the TechDraw overview page of one nested sheet. Pure Python, no FreeCAD
imports; cam.py wraps the SVG strings into TechDraw::DrawViewSymbol views.

The page content is designed portrait (title on top, the sheet drawing below it, the
label legend underneath) in "portrait paper millimetres" with the origin at the top-left
corner and y pointing down. When the TechDraw page itself is landscape (the default A4
template), every view is rotated by 90 degrees so that the printed page is used turned
into portrait orientation. compose() returns the views with their TechDraw positions.
"""

import math
from xml.sax.saxutils import escape

MARGIN = 10.0  # mm around the portrait content
TITLE_SIZE = 5.0  # mm font
SUBTITLE_SIZE = 2.8
LEGEND_SIZE = 3.5
LEGEND_PITCH = 7.0  # mm per legend row (strip height)
LEGEND_COLUMNS_ABOVE = 16  # more rows than this: two columns
GAP = 6.0  # mm between title, drawing and legend
MIN_LABEL_SIZE = 1.6  # mm on paper
MAX_LABEL_SIZE = 6.0
FONT = "sans-serif"
CHAR_W = 0.62  # average glyph width / font size for sans-serif


class Panel:
    """A placed panel: layout rectangle (u0, v0, du, dv) plus label and dimensions text."""

    def __init__(self, u0, v0, du, dv, label, dims):
        self.u0, self.v0, self.du, self.dv = u0, v0, du, dv
        self.label = label
        self.dims = dims


class Cut:
    """A cut line: axis "h" (v = pos) or "v" (u = pos), span [a0, a1], tab centres."""

    def __init__(self, axis, pos, a0, a1, tabs):
        self.axis, self.pos, self.a0, self.a1, self.tabs = axis, pos, a0, a1, list(tabs)


class View:
    """One TechDraw symbol view: SVG text plus centre position on the page (mm, y up)."""

    def __init__(self, name, svg, x, y):
        self.name, self.svg, self.x, self.y = name, svg, x, y


def _fmt(v):
    return "{:.3f}".format(v).rstrip("0").rstrip(".")


def _text(x, y, size, s, anchor="start", rotate=None, weight=None):
    attrs = 'x="{}" y="{}" font-size="{}" font-family="{}" text-anchor="{}"'.format(
        _fmt(x), _fmt(y), _fmt(size), FONT, anchor
    )
    if weight:
        attrs += ' font-weight="{}"'.format(weight)
    if rotate is not None:
        attrs += ' transform="rotate({} {} {})"'.format(_fmt(rotate), _fmt(x), _fmt(y))
    return "<text {}>{}</text>".format(attrs, escape(s))


def label_font_size(du, dv, text, k):
    """Font size (sheet units) so that text runs along the long side and fits the panel."""
    long_side, short_side = max(du, dv), min(du, dv)
    n = max(len(text), 1)
    size = min(short_side * 0.55, long_side * 0.9 / (CHAR_W * n))
    return max(MIN_LABEL_SIZE / k, min(size, MAX_LABEL_SIZE / k))


def sheet_drawing(sheet_w, sheet_h, panels, cuts, tool_d, tab_width, top_left, box_w, box_h):
    """
    The sheet with its panels, cuts and tabs, scaled to fit box_w x box_h (paper mm).

    Layout u runs right; v runs down from the top edge (top_left) or up from the bottom
    edge (bottom-left origin). Returns (svg_body, width, height, scale).
    """
    k = min(box_w / sheet_w, box_h / sheet_h)
    w, h = sheet_w * k, sheet_h * k

    def y(v):
        return v if top_left else sheet_h - v

    def rect(u0, v0, du, dv, style):
        top = min(y(v0), y(v0 + dv))
        return '<rect x="{}" y="{}" width="{}" height="{}" {}/>'.format(
            _fmt(u0), _fmt(top), _fmt(du), _fmt(dv), style
        )

    out = ['<g transform="scale({})">'.format(_fmt(k))]
    out.append(rect(0, 0, sheet_w, sheet_h, 'fill="none" stroke="#000" stroke-width="{}"'.format(_fmt(0.6 / k))))
    for p in panels:
        out.append(rect(p.u0, p.v0, p.du, p.dv, 'fill="#e6e6e6" stroke="#000" stroke-width="{}"'.format(_fmt(0.3 / k))))
    for c in cuts:
        if c.axis == "h":
            x1, y1, x2, y2 = c.a0, y(c.pos), c.a1, y(c.pos)
        else:
            x1, y1, x2, y2 = c.pos, y(c.a0), c.pos, y(c.a1)
        out.append(
            '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#666" stroke-width="{}"/>'.format(
                _fmt(x1), _fmt(y1), _fmt(x2), _fmt(y2), _fmt(0.15 / k)
            )
        )
    across = max(tool_d, 1.2 / k)  # tabs stay visible at small scales
    for c in cuts:
        for t in c.tabs:
            if c.axis == "h":
                out.append(rect(t - tab_width / 2.0, c.pos - across / 2.0, tab_width, across, 'fill="#000"'))
            else:
                out.append(rect(c.pos - across / 2.0, t - tab_width / 2.0, across, tab_width, 'fill="#000"'))
    for p in panels:
        size = label_font_size(p.du, p.dv, p.label, k)
        cx = p.u0 + p.du / 2.0
        cy = min(y(p.v0), y(p.v0 + p.dv)) + p.dv / 2.0
        rotate = -90 if p.dv > p.du else None
        out.append(_text(cx, cy + size * 0.35, size, p.label, anchor="middle", rotate=rotate))
    out.append("</g>")
    return "\n".join(out), w, h, k


def title_block(title, subtitle, width):
    """Title (the G-code file name) and a smaller subtitle line."""
    h = TITLE_SIZE + (SUBTITLE_SIZE + 2.0 if subtitle else 0.0) + 2.0
    out = [_text(0, TITLE_SIZE, TITLE_SIZE, title, weight="bold")]
    if subtitle:
        out.append(_text(0, TITLE_SIZE + 2.0 + SUBTITLE_SIZE, SUBTITLE_SIZE, subtitle))
    return "\n".join(out), width, h


def legend(rows, width):
    """
    One line per panel, each in its own strip (dashed cut guides between them), so the
    printed rows can be cut off and taped to the physical parts.
    """
    n = len(rows)
    cols = 1 if n <= LEGEND_COLUMNS_ABOVE else 2
    per_col = int(math.ceil(n / float(cols)))
    col_w = width / cols
    h = per_col * LEGEND_PITCH
    out = []
    for i, (label, dims) in enumerate(rows):
        col, row = divmod(i, per_col)
        x0 = col * col_w
        y0 = row * LEGEND_PITCH
        out.append(
            '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#999" stroke-width="0.2" '
            'stroke-dasharray="1.5,1.5"/>'.format(_fmt(x0), _fmt(y0), _fmt(x0 + col_w), _fmt(y0))
        )
        base = y0 + LEGEND_PITCH / 2.0 + LEGEND_SIZE * 0.35
        out.append(_text(x0 + 2.0, base, LEGEND_SIZE, label, weight="bold"))
        out.append(_text(x0 + col_w - 2.0, base, LEGEND_SIZE * 0.85, dims, anchor="end"))
    out.append(
        '<line x1="0" y1="{0}" x2="{1}" y2="{0}" stroke="#999" stroke-width="0.2" '
        'stroke-dasharray="1.5,1.5"/>'.format(_fmt(h), _fmt(width))
    )
    return "\n".join(out), width, h


def _wrap(body, w, h, rotate):
    """Root SVG of exact size (mm) for a TechDraw symbol; rotated 90 deg when requested."""
    if rotate:
        root_w, root_h = h, w
        inner = '<g transform="translate({},0) rotate(90)">\n{}\n</g>'.format(_fmt(h), body)
    else:
        root_w, root_h = w, h
        inner = body
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{w}mm" height="{h}mm" '
        'viewBox="0 0 {w} {h}">\n{inner}\n</svg>'.format(w=_fmt(root_w), h=_fmt(root_h), inner=inner)
    )


def compose(page_w, page_h, title, subtitle, sheet_w, sheet_h, panels, cuts, tool_d, tab_width, top_left):
    """
    Lay the title, sheet drawing and legend out on a page of page_w x page_h mm.

    Returns [View]; view positions are TechDraw page coordinates (origin bottom-left,
    y up, view centre). Content is portrait; on a landscape page it is rotated 90 deg
    (turn the printout counter-clockwise to read it).
    """
    rotate = page_w > page_h
    pw, ph = (page_h, page_w) if rotate else (page_w, page_h)  # portrait paper size
    width = pw - 2 * MARGIN
    rows = [(p.label, p.dims) for p in panels]
    title_body, tw, th = title_block(title, subtitle, width)
    legend_body, lw, lh = legend(rows, width)
    box_h = ph - 2 * MARGIN - th - lh - 2 * GAP
    drawing_body, dw, dh, _k = sheet_drawing(
        sheet_w, sheet_h, panels, cuts, tool_d, tab_width, top_left, width, max(box_h, 20.0)
    )

    def place(name, body, w, h, px0, py0):
        # portrait rect (px0, py0, w, h) -> page position of its centre
        cx, cy = px0 + w / 2.0, py0 + h / 2.0
        if rotate:
            x, y = page_w - cy, page_h - cx
        else:
            x, y = cx, page_h - cy
        return View(name, _wrap(body, w, h, rotate), x, y)

    y_cursor = MARGIN
    views = [place("Title", title_body, tw, th, MARGIN, y_cursor)]
    y_cursor += th + GAP
    views.append(place("Sheet", drawing_body, dw, dh, MARGIN + (width - dw) / 2.0, y_cursor))
    y_cursor += dh + GAP
    views.append(place("Legend", legend_body, lw, lh, MARGIN, y_cursor))
    return views


if __name__ == "__main__":  # quick self-check: python3 sheetdraw.py > /tmp/sheet.svg
    import sys

    panels = [
        Panel(0, 0, 120, 500, "Drawer_SideL", "500 x 120 x 12 mm"),
        Panel(123.175, 0, 120, 500, "Drawer_SideR", "500 x 120 x 12 mm"),
        Panel(0, 503.175, 388, 120, "Drawer_Back", "388 x 120 x 12 mm"),
    ]
    cuts = [Cut("v", 121.6, -1.6, 501.6, [166, 333]), Cut("h", 501.6, -1.6, 389.6, [40, 80, 200, 300])]
    views = compose(297, 210, "test_Captured_Drawer_12mm_1.nc", "/tmp/lj_cam", 630, 1080, panels, cuts, 3.175, 10, True)
    for v in views:
        sys.stderr.write("{} at ({:.1f}, {:.1f})\n".format(v.name, v.x, v.y))
    # A combined preview of the whole landscape page.
    print('<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210">')
    print('<rect width="297" height="210" fill="#fff" stroke="#000" stroke-width="0.3"/>')
    for v in views:
        body = v.svg.split("\n", 1)[1].rsplit("\n", 1)[0]
        import re
        w = float(re.search(r'width="([\d.]+)mm"', v.svg).group(1))
        h = float(re.search(r'height="([\d.]+)mm"', v.svg).group(1))
        print('<g transform="translate({},{})">{}</g>'.format(v.x - w / 2, 210 - v.y - h / 2, body))
    print("</svg>")
