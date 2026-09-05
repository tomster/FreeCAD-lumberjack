# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - nesting.py

Pure-Python nesting of rectangular panels on rectangular sheets for CNC cutting.
No FreeCAD imports, so it can be exercised with plain python3.

Layout frame
------------
The sheet's reference corner is its top-left corner: u runs to the right along the sheet
width, v runs *down* along the sheet height (both >= 0). Panels hug the top (v = 0) and
left (u = 0) edges, which are assumed to be cut straight and square: edges flush with them
need no cut, and those two sheet edges stay free of toolpaths so the sheet can be clamped
there.

Strategy
--------
Guillotine packing anchored at the top-left corner, largest panels first. Each placement
splits its free rectangle into a strip below the panel (as wide as the panel, so panels
stack in columns) and the remainder to the right; the leftmost, then topmost free space is
used first. Panels are oriented so that their long side runs vertically whenever that fits
(the work area is taller than wide), otherwise horizontally. Neighbouring panels are
separated by exactly one tool diameter, so a single centre-line cut separates both and
its tabs hold both. Everything that does not fit goes to the next sheet.

Cut lines
---------
Each panel edge that is not flush with the sheet's top/left edge yields a cut line offset
outward by the tool radius, extended by the tool radius past the corners. Coincident lines
(neighbours) are merged. Tabs are placed at 1/3 and 2/3 of every served panel edge and
merged when closer than a tab width plus a tool diameter.
"""

class DoesNotFit(Exception):
    """A panel does not fit the sheet in any orientation."""


class Item:
    """A rectangular panel to nest. length x width, `key` identifies it."""

    def __init__(self, key, length, width, thickness, allow_rotate=True, data=None):
        self.key = key
        self.length = float(length)
        self.width = float(width)
        self.thickness = float(thickness)
        self.allow_rotate = allow_rotate
        self.data = data

    @property
    def area(self):
        return self.length * self.width


class Placed:
    """An item placed on a sheet: top-left corner (u0, v0), extents du (right), dv (down)."""

    def __init__(self, item, u0, v0, du, dv, rotated):
        self.item = item
        self.u0 = u0
        self.v0 = v0
        self.du = du
        self.dv = dv
        self.rotated = rotated  # True: the item's length runs along v (vertical)

    @property
    def u1(self):
        return self.u0 + self.du

    @property
    def v1(self):
        return self.v0 + self.dv


class CutLine:
    """
    A straight cut. axis "h": horizontal at v = pos spanning u in [a0, a1];
    axis "v": vertical at u = pos spanning v in [a0, a1]. `edges` holds the served panel
    edges as (a_start, a_end, item_key, edge_name); `tabs` the tab centres along the line.
    """

    def __init__(self, axis, pos, a0, a1):
        self.axis = axis
        self.pos = pos
        self.a0 = min(a0, a1)
        self.a1 = max(a0, a1)
        self.edges = []
        self.tabs = []

    @property
    def length(self):
        return self.a1 - self.a0

    def touches_top(self):
        return self.axis == "v" and self.a0 <= 1e-6

    def touches_left(self):
        return self.axis == "h" and self.a0 <= 1e-6


class Sheet:
    def __init__(self, index, sheet_w, sheet_h):
        self.index = index
        self.sheet_w = sheet_w
        self.sheet_h = sheet_h
        self.items = []  # [Placed]
        self.lines = []  # [CutLine]

    @property
    def used_w(self):
        return max((p.u1 for p in self.items), default=0.0)

    @property
    def used_h(self):
        return max((p.v1 for p in self.items), default=0.0)

    def top_edge_cuts(self):
        """u positions where a cut reaches the top edge (do not clamp there)."""
        return sorted(l.pos for l in self.lines if l.touches_top())

    def left_edge_cuts(self):
        """v positions where a cut reaches the left edge (do not clamp there)."""
        return sorted(l.pos for l in self.lines if l.touches_left())


class _Free:
    """A free rectangle on the sheet (layout frame)."""

    def __init__(self, u0, v0, du, dv):
        self.u0, self.v0, self.du, self.dv = u0, v0, du, dv

    @property
    def u1(self):
        return self.u0 + self.du

    @property
    def v1(self):
        return self.v0 + self.dv


def orientations(item, max_u, max_v):
    """
    Feasible (du, dv, rotated) orientations of an item within max_u x max_v,
    preferred first: long side vertical, then the narrower footprint.
    """
    cands = []
    for rotated in ((False, True) if item.allow_rotate else (False,)):
        du, dv = (item.width, item.length) if rotated else (item.length, item.width)
        if du <= max_u + 1e-9 and dv <= max_v + 1e-9:
            cands.append((du, dv, rotated))
    cands.sort(key=lambda c: (0 if c[1] >= c[0] else 1, c[0]))
    return cands


def edge_clearance(tool_d):
    """Room needed between a cut panel edge and the sheet's right/bottom edge."""
    return tool_d + 1.0


def nest(items, sheet_w, sheet_h, tool_d):
    """
    Nest items (same thickness) on as many sheets as needed.

    Guillotine packing anchored at the top-left corner: every placement splits its free
    rectangle into a strip below the panel (as wide as the panel, so panels stack in
    columns) and the remainder to its right. Free rectangles start one tool diameter away
    from the placed panel, so neighbours share a single cut. Leftmost free space is used
    first, then topmost; the long side goes vertical when it fits.

    Returns a list of Sheet with placed items and cut lines. Raises DoesNotFit if an item
    does not fit an empty sheet in any orientation.
    """
    clearance = edge_clearance(tool_d)
    max_u = sheet_w - clearance
    max_v = sheet_h - clearance
    for item in items:
        if not orientations(item, max_u, max_v):
            raise DoesNotFit(
                "{}: {:g} x {:g} mm does not fit a {:g} x {:g} mm sheet "
                "(with {:g} mm clearance)".format(
                    item.key, item.length, item.width, sheet_w, sheet_h, clearance
                )
            )

    remaining = sorted(items, key=lambda it: (-it.area, -max(it.length, it.width)))
    sheets = []
    while remaining:
        sheet = Sheet(len(sheets), sheet_w, sheet_h)
        free = [_Free(0.0, 0.0, max_u, max_v)]
        for item in list(remaining):
            placed = _place(item, free, tool_d)
            if placed is None:
                continue
            sheet.items.append(placed)
            remaining.remove(item)
        if not sheet.items:
            raise DoesNotFit("could not place {}".format(remaining[0].key))
        sheet.lines = cut_lines(sheet.items, tool_d)
        sheets.append(sheet)
    return sheets


def _place(item, free, tool_d):
    """Place item into the leftmost/topmost fitting free rectangle and split it."""
    best = None
    for rect in free:
        for du, dv, rotated in orientations(item, rect.du, rect.dv):
            score = (rect.u0, rect.v0, 0 if dv >= du else 1)
            if best is None or score < best[0]:
                best = (score, rect, du, dv, rotated)
            break  # orientations are ordered by preference
    if best is None:
        return None
    _score, rect, du, dv, rotated = best
    placed = Placed(item, rect.u0, rect.v0, du, dv, rotated)
    free.remove(rect)
    below = _Free(rect.u0, rect.v0 + dv + tool_d, du, rect.v1 - (rect.v0 + dv + tool_d))
    right = _Free(rect.u0 + du + tool_d, rect.v0, rect.u1 - (rect.u0 + du + tool_d), rect.dv)
    for f in (below, right):
        if f.du > 1e-9 and f.dv > 1e-9:
            free.append(f)
    return placed


def cut_lines(placed_items, tool_d, tol=1e-6):
    """Merged cut lines (with served edges) for the placed items of one sheet."""
    r = tool_d / 2.0
    raw = []  # (axis, pos, a0, a1, edge_a0, edge_a1, key, name)
    for p in placed_items:
        k = p.item.key
        if p.v0 > tol:  # top edge not flush with the sheet top
            raw.append(("h", p.v0 - r, p.u0 - r, p.u1 + r, p.u0, p.u1, k, "top"))
        raw.append(("h", p.v1 + r, p.u0 - r, p.u1 + r, p.u0, p.u1, k, "bottom"))
        if p.u0 > tol:  # left edge not flush with the sheet's left edge
            raw.append(("v", p.u0 - r, p.v0 - r, p.v1 + r, p.v0, p.v1, k, "left"))
        raw.append(("v", p.u1 + r, p.v0 - r, p.v1 + r, p.v0, p.v1, k, "right"))

    lines = []
    groups = {}
    for entry in raw:
        axis, pos = entry[0], entry[1]
        key = (axis, round(pos, 4))
        groups.setdefault(key, []).append(entry)
    for (axis, _pos), entries in sorted(groups.items()):
        entries.sort(key=lambda e: e[2])
        current = None
        for axis_, pos, a0, a1, e0, e1, k, name in entries:
            if current is not None and a0 <= current.a1 + tol:
                current.a1 = max(current.a1, a1)
            else:
                current = CutLine(axis_, pos, a0, a1)
                lines.append(current)
            current.edges.append((e0, e1, k, name))
    for line in lines:
        line.tabs = tab_positions(line, tool_d)
    # Vertical lines left to right, then horizontal lines top to bottom.
    lines.sort(key=lambda l: (0 if l.axis == "v" else 1, l.pos, l.a0))
    return lines


TAB_WIDTH = 10.0
TABS_PER_EDGE_FRACTIONS = (1.0 / 3.0, 2.0 / 3.0)


def tab_positions(line, tool_d, tab_width=TAB_WIDTH):
    """
    Tab centres along a cut line: 1/3 and 2/3 of each served edge.

    CAM's tag solids are tab_width + tool_d wide, so tabs closer than that are merged
    (CAM would otherwise disable one of them) and tabs are kept clear of the line ends.
    """
    min_gap = tab_width + tool_d + 1.0
    end_clear = tab_width / 2.0 + tool_d + 1.0
    wanted = []
    for e0, e1, _k, _name in line.edges:
        length = e1 - e0
        if length >= 3 * tab_width:
            wanted.extend(e0 + f * length for f in TABS_PER_EDGE_FRACTIONS)
        elif length >= 1.5 * tab_width:
            wanted.append((e0 + e1) / 2.0)
    wanted = [w for w in wanted if line.a0 + end_clear <= w <= line.a1 - end_clear]
    wanted.sort()
    merged = []
    for pos in wanted:
        if merged and pos - merged[-1][-1] < min_gap:
            merged[-1].append(pos)
        else:
            merged.append([pos])
    return [sum(g) / len(g) for g in merged]


def summarize(sheets):
    """Human readable summary lines for a list of sheets."""
    out = []
    for s in sheets:
        out.append(
            "sheet {}: {} panels, blank at least {:.0f} x {:.0f} mm, {} cuts, {} tabs".format(
                s.index + 1,
                len(s.items),
                s.used_w,
                s.used_h,
                len(s.lines),
                sum(len(l.tabs) for l in s.lines),
            )
        )
        if s.top_edge_cuts():
            out.append(
                "  cuts reach the top edge at x = {} (keep clamps away)".format(
                    ", ".join("{:.0f}".format(u) for u in s.top_edge_cuts())
                )
            )
        if s.left_edge_cuts():
            out.append(
                "  cuts reach the left edge at y = {} (keep clamps away)".format(
                    ", ".join("{:.0f}".format(v) for v in s.left_edge_cuts())
                )
            )
    return out


if __name__ == "__main__":  # quick self-check: python3 nesting.py
    d = 6.0
    its = [
        Item("SideL", 500, 120, 12), Item("SideR", 500, 120, 12),
        Item("Front", 388, 120, 12), Item("Back", 388, 120, 12),
    ]
    for sh in nest(its, 630, 1080, d):
        for p in sh.items:
            print(p.item.key, p.u0, p.v0, p.du, p.dv, "rot" if p.rotated else "")
        for l in sh.lines:
            print(l.axis, l.pos, l.a0, l.a1, [round(t, 1) for t in l.tabs], [e[3] for e in l.edges])
    print("\n".join(summarize(nest(its, 630, 1080, d))))
