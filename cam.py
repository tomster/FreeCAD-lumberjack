# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - cam.py

Generate a FreeCAD CAM Job (with operations, hold-down tabs and G-code) for drawers
created by drawers.py.

Workflow
--------
1. Select one or more drawers (the drawer App::Part or anything inside it).
2. Run "Drawer CAM Job". A dialog asks for the tool bit (from the CAM toolbit library),
   the machine bed size, the post processor and the cutting parameters. All values are
   remembered between invocations.
3. One CAM Job per drawer is created. Every panel body becomes a model in the Job, laid
   flat with its pocketed face up and its top face at Z = 0, all panels in a row along X.
   Operations: Slot passes for the bottom groove, the half-lap rabbets and the bottom's
   perimeter rabbet; an outside Profile per panel with a Tags dress-up (2 tabs per edge).
   Finally the Job is post-processed to <docdir>/<Doc>_<Drawer>.nc.
4. Arrange the panels manually in the Job if needed and run the command again on the
   drawer: the layout is kept, the stock, operations, tabs and G-code are regenerated
   from the current placements.

Geometry
--------
All pockets are computed in the *body-local* frame of each panel (each body is a slab
centered on its own origin, see drawers.py) and mapped into job coordinates through the
model clone's Placement. That is what makes the regeneration follow manual moves.
The half-lap rabbets are not modelled in the drawer bodies; they are synthesised here:
the full-length panels (Front/Back without a drawer front, SideL/SideR with one) get a
rabbet t_side wide x t_side/2 deep on their inner face at both ends. No rabbets are cut
when overlap_box is set.

Verified against the FreeCAD 1.1.3 CAM API.
"""

import math
import os
import re

import FreeCAD

try:
    import FreeCADGui
except ImportError:  # pragma: no cover - headless without Gui module
    FreeCADGui = None

import drawers as _drawers
from drawers import _get_last_bool, _get_last_str, _set_last_bool, _set_last_str

Vector = FreeCAD.Vector


# =============================================================================
# CONSTANTS (deliberately not user-configurable in this iteration)
# =============================================================================

ROLES = _drawers.PANEL_ROLES
WALL_ROLES = ("SideL", "SideR", "Back", "Front")

THROUGH_OVERCUT = 0.2  # mm cut past the panel bottom on through cuts
TAB_WIDTH = 10.0  # mm
TAB_HEIGHT = 3.0  # mm (capped at half the panel thickness)
TABS_PER_EDGE = 2
TAB_FRACTIONS = (1.0 / 3.0, 2.0 / 3.0)
STOCK_MARGIN_EXTRA = 5.0  # mm added to the tool diameter for the stock margin
PASS_OVERLAP = 0.5  # step-over between parallel slot passes as fraction of tool diameter
PASS_EXTENSION_EXTRA = 1.0  # mm beyond the tool radius that open-ended passes overshoot
RAPID_DEFAULT = "1200 mm/min"

PREF_PREFIX = "cam_"


class ToolTooWide(Exception):
    """Raised when a pocket region is narrower than the tool."""


# =============================================================================
# DRAWER DISCOVERY (shared with drawers.py)
# =============================================================================

# Re-exported so existing callers/tests keep working.
drawer_holder = _drawers.drawer_holder
find_drawer_part = _drawers.find_drawer_part
selected_drawers = _drawers.selected_drawers
drawer_panels = _drawers.drawer_panels


def _qty(v):
    return float(getattr(v, "Value", v))


class DrawerParams:
    """Evaluated drawer parameters read from the holder."""

    def __init__(self, holder):
        self.width = _qty(holder.width)
        self.height = _qty(holder.height)
        self.depth = _qty(holder.depth)
        self.t_side = _qty(holder.t_side)
        self.t_bottom = _qty(holder.t_bottom)
        self.bottom_v_offset = _qty(holder.bottom_v_offset)
        self.width_front = _qty(holder.width_front)
        self.height_front = _qty(holder.height_front)
        self.t_front = _qty(holder.t_front)
        self.overlap_box = bool(holder.overlap_box)
        self.has_front = bool(holder.has_front)

    # Same derivations as drawers.create_drawer().
    @property
    def side_len(self):
        if self.has_front:
            return self.depth
        return self.depth if self.overlap_box else self.depth - self.t_side

    @property
    def fb_len(self):
        if self.has_front:
            return self.width if self.overlap_box else self.width - self.t_side
        return self.width

    @property
    def bottom_x(self):
        return self.width - self.t_side

    @property
    def bottom_y(self):
        return self.depth - self.t_side

    @property
    def full_length_roles(self):
        return ("SideL", "SideR") if self.has_front else ("Front", "Back")

    def thickness(self, role):
        if role == "Bottom":
            return self.t_bottom
        if role == "DrawerFront":
            return self.t_front
        return self.t_side

    # Bottom joint (mirrors the expressions in drawers.create_drawer):
    #   inserted (t_bottom < t_side): full-thickness bottom in a t_bottom wide groove
    #   starting t_bottom above the box bottom, no rabbet on the bottom.
    #   captured (otherwise): t_bottom / 2 groove starting t_bottom / 2 up, rabbeted bottom.
    @property
    def bottom_inserted(self):
        return self.t_bottom < self.t_side

    @property
    def groove_width(self):
        return self.t_bottom if self.bottom_inserted else self.t_bottom / 2.0

    @property
    def groove_offset(self):
        """Distance from a wall's bottom edge to the lower edge of the groove."""
        return self.bottom_v_offset + self.groove_width


# =============================================================================
# PURE GEOMETRY
# =============================================================================


class PanelFrame:
    """
    Orientation of a panel in its body-local frame.

    N: unit normal of the featured (pocketed) face, this face ends up pointing +Z.
    V: panel-frame "up" direction (ends up +Y in the job).
    U: panel length direction (ends up +X in the job), U = V x N.
    L, W, t: panel length (along U), width (along V) and thickness.
    """

    def __init__(self, role, U, V, N, L, W, t):
        self.role = role
        self.U = U
        self.V = V
        self.N = N
        self.L = L
        self.W = W
        self.t = t

    def to_local(self, u, v, n=None):
        """Map panel-frame (u, v) on the featured face to a body-local point."""
        if n is None:
            n = self.t / 2.0
        return self.U * u + self.V * v + self.N * n

    def rotation(self):
        """Rotation mapping U -> +X, V -> +Y, N -> +Z."""
        U, V, N = self.U, self.V, self.N
        m = FreeCAD.Matrix(
            U.x, U.y, U.z, 0,
            V.x, V.y, V.z, 0,
            N.x, N.y, N.z, 0,
            0, 0, 0, 1,
        )
        return FreeCAD.Rotation(m)

    def corners(self):
        """Panel-frame corners of the featured face, counter-clockwise."""
        hl, hw = self.L / 2.0, self.W / 2.0
        return [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]


def panel_frame(role, p):
    """Build the PanelFrame for a role from the drawer parameters."""
    X, Y, Z = Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1)
    if role in WALL_ROLES:
        N = {"SideL": X, "SideR": -X, "Back": Y, "Front": -Y}[role]
        V = Z
        U = V.cross(N)
        L = p.side_len if role in ("SideL", "SideR") else p.fb_len
        return PanelFrame(role, U, V, N, L, p.height, p.t_side)
    if role == "Bottom":
        N = -Z  # rabbet is on the underside
        if p.bottom_x >= p.bottom_y:
            U, L, W = X, p.bottom_x, p.bottom_y
        else:
            U, L, W = Y, p.bottom_y, p.bottom_x
        V = N.cross(U)
        return PanelFrame(role, U, V, N, L, W, p.t_bottom)
    if role == "DrawerFront":
        N = -Y  # back face up, visible face down on the spoilboard
        V = Z
        U = V.cross(N)
        return PanelFrame(role, U, V, N, p.width_front, p.height_front, p.t_front)
    raise ValueError("unknown drawer panel role: {}".format(role))


class Region:
    """A rectangular pocket in the panel frame, machined with parallel slot passes."""

    def __init__(self, name, u0, u1, v0, v1, depth, along):
        self.name = name
        self.u0, self.u1 = min(u0, u1), max(u0, u1)
        self.v0, self.v1 = min(v0, v1), max(v0, v1)
        self.depth = depth
        self.along = along  # "u" or "v": direction of the passes

    @property
    def width_across(self):
        return (self.v1 - self.v0) if self.along == "u" else (self.u1 - self.u0)


def pocket_regions(role, p, frame):
    """Pocket regions (panel frame) for a role."""
    regions = []
    L, W = frame.L, frame.W
    if role in WALL_ROLES:
        ts = p.t_side
        g0 = -W / 2.0 + p.groove_offset
        regions.append(Region("Groove", -L / 2.0, L / 2.0, g0, g0 + p.groove_width, ts / 2.0, "u"))
        if role in p.full_length_roles and not p.overlap_box:
            regions.append(Region("RabbetEnd1", L / 2.0 - ts, L / 2.0, -W / 2.0, W / 2.0, ts / 2.0, "v"))
            regions.append(Region("RabbetEnd2", -L / 2.0, -L / 2.0 + ts, -W / 2.0, W / 2.0, ts / 2.0, "v"))
    elif role == "Bottom" and not p.bottom_inserted:
        w = p.t_side / 2.0
        d = p.t_bottom / 2.0
        regions.append(Region("RabbetTop", -L / 2.0, L / 2.0, W / 2.0 - w, W / 2.0, d, "u"))
        regions.append(Region("RabbetBottom", -L / 2.0, L / 2.0, -W / 2.0, -W / 2.0 + w, d, "u"))
        regions.append(Region("RabbetRight", L / 2.0 - w, L / 2.0, -W / 2.0, W / 2.0, d, "v"))
        regions.append(Region("RabbetLeft", -L / 2.0, -L / 2.0 + w, -W / 2.0, W / 2.0, d, "v"))
    return regions


def slot_passes(region, tool_d):
    """
    Parallel center-line passes covering a region.

    Returns a list of ((u, v), (u, v)) start/end pairs in the panel frame. Passes overshoot
    both ends (all regions are open-ended). Raises ToolTooWide if the tool does not fit.
    """
    if region.along == "u":
        a0, a1, b0, b1 = region.u0, region.u1, region.v0, region.v1
    else:
        a0, a1, b0, b1 = region.v0, region.v1, region.u0, region.u1
    w = b1 - b0
    eps = 1e-6
    if w < tool_d - eps:
        raise ToolTooWide(
            "{}: pocket is {:.2f} mm wide, tool is {:.2f} mm".format(region.name, w, tool_d)
        )
    if w <= tool_d + eps:
        centers = [(b0 + b1) / 2.0]
    else:
        n = int(math.ceil((w - tool_d) / (PASS_OVERLAP * tool_d))) + 1
        step = (w - tool_d) / (n - 1)
        centers = [b0 + tool_d / 2.0 + i * step for i in range(n)]
    ext = tool_d / 2.0 + PASS_EXTENSION_EXTRA
    passes = []
    for i, c in enumerate(centers):
        start, end = a0 - ext, a1 + ext
        if i % 2:
            start, end = end, start  # alternate direction between neighbouring passes
        if region.along == "u":
            passes.append(((start, c), (end, c)))
        else:
            passes.append(((c, start), (c, end)))
    return passes


def tab_positions(corners, tool_r):
    """
    Tab centers on the compensated toolpath for a convex polygon given as [(x, y)].

    TABS_PER_EDGE tabs per edge at TAB_FRACTIONS along the edge, pushed outward by the
    tool radius so they sit on the outside profile path.
    """
    n = len(corners)
    cx = sum(c[0] for c in corners) / n
    cy = sum(c[1] for c in corners) / n
    positions = []
    for i in range(n):
        x0, y0 = corners[i]
        x1, y1 = corners[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        if length < 1e-9:
            continue
        nx, ny = ey / length, -ex / length  # a perpendicular
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny  # make it point away from the centroid
        for f in TAB_FRACTIONS:
            positions.append((x0 + f * ex + nx * tool_r, y0 + f * ey + ny * tool_r))
    return positions


def footprint_fits(L, W, margin, bed_x, bed_y):
    """True if a panel plus stock margin fits the bed in either orientation."""
    l, w = L + 2 * margin, W + 2 * margin
    return (l <= bed_x and w <= bed_y) or (w <= bed_x and l <= bed_y)


def stock_margin(tool_d):
    return tool_d + STOCK_MARGIN_EXTRA


# =============================================================================
# SETTINGS AND VALIDATION
# =============================================================================


class CamSettings:
    """Values collected by the dialog."""

    def __init__(self):
        self.bit_id = ""
        self.bit_label = ""
        self.tool_d = 0.0
        self.cutting_edge_height = None
        self.bed_x = 0.0
        self.bed_y = 0.0
        self.post = ""
        self.spindle = 0.0
        self.feed_xy = 0.0
        self.feed_z = 0.0
        self.step_down = 0.0
        self.write_gcode = True

    @property
    def margin(self):
        return stock_margin(self.tool_d)


def validate_drawer(part, params, settings):
    """
    Return (problems, warnings) for a drawer given the settings.

    problems abort the run, warnings are only reported.
    """
    problems = []
    warnings = []
    d = settings.tool_d
    label = part.Label
    panels = drawer_panels(part)
    if not panels:
        problems.append("{}: no panel bodies found".format(label))
        return problems, warnings
    if d <= 0:
        problems.append("tool diameter must be > 0")
        return problems, warnings
    thicknesses = set()
    row_length = settings.margin
    for role, _body in panels:
        frame = panel_frame(role, params)
        thicknesses.add(round(frame.t, 3))
        for region in pocket_regions(role, params, frame):
            try:
                slot_passes(region, d)
            except ToolTooWide as e:
                problems.append("{} {}: {}".format(label, role, e))
        if not footprint_fits(frame.L, frame.W, settings.margin, settings.bed_x, settings.bed_y):
            problems.append(
                "{} {}: {:.0f} x {:.0f} mm (+{:.0f} mm margin) does not fit the bed "
                "{:.0f} x {:.0f} mm".format(
                    label, role, frame.L, frame.W, settings.margin, settings.bed_x, settings.bed_y
                )
            )
        ceh = settings.cutting_edge_height
        if ceh is not None and ceh < frame.t + THROUGH_OVERCUT:
            warnings.append(
                "{} {}: cutting edge {:.1f} mm is shorter than the panel thickness "
                "{:.1f} mm".format(label, role, ceh, frame.t)
            )
        row_length += frame.L + 2 * settings.margin
    if len(thicknesses) > 1:
        warnings.append(
            "{}: panels of different thickness ({}) share one Job; the stock is generated "
            "at the maximum thickness, every panel is cut to its own depth".format(
                label, ", ".join("{:g}".format(t) for t in sorted(thicknesses))
            )
        )
    if row_length > settings.bed_x:
        warnings.append(
            "{}: the panel row is {:.0f} mm long and exceeds the bed; arrange the panels in "
            "the Job manually, then run the command again".format(label, row_length)
        )
    return problems, warnings


# =============================================================================
# TOOL BIT LIBRARY
# =============================================================================


class ToolBitInfo:
    def __init__(self, lib_label, lib_id, number, label, bit_id, diameter, shape, edge_height):
        self.lib_label = lib_label
        self.lib_id = lib_id
        self.number = number
        self.label = label
        self.bit_id = bit_id
        self.diameter = diameter
        self.shape = shape
        self.edge_height = edge_height

    def text(self):
        nr = "#{} ".format(self.number) if self.number is not None else ""
        return "{}: {}{} (Ø {:g} mm, {})".format(
            self.lib_label, nr, self.label, self.diameter, self.shape
        )


def _bit_property(bit, name):
    try:
        return _qty(bit.get_property(name))
    except Exception:
        return None


def list_toolbits():
    """All bits of all local toolbit libraries, flat-bottom shapes first."""
    import Path.Tool  # noqa: F401  (registers the asset serializers)
    from Path.Tool.camassets import cam_assets, ensure_assets_initialized

    ensure_assets_initialized(cam_assets)
    infos = []
    for lib in cam_assets.fetch("toolbitlibrary", store="local", depth=1):
        for bit in lib:
            try:
                dia = _bit_property(bit, "Diameter")
                if dia is None:
                    continue
                shape = str(bit.get_shape_name()).replace(".fcstd", "")
                infos.append(
                    ToolBitInfo(
                        lib.label,
                        lib.get_id(),
                        lib.get_bit_no_from_bit(bit),
                        bit.label,
                        bit.get_id(),
                        dia,
                        shape,
                        _bit_property(bit, "CuttingEdgeHeight"),
                    )
                )
            except Exception as e:
                FreeCAD.Console.PrintWarning("Lumberjack: skipping tool bit: {}\n".format(e))

    def flat(info):
        return info.shape.lower().startswith(("endmill", "bullnose"))

    infos.sort(key=lambda i: (0 if flat(i) else 1, i.lib_label, i.number or 0, i.label))
    return infos


def load_toolbit(bit_id):
    """Load a fresh ToolBit asset instance by id (one instance per attached object)."""
    import Path.Tool  # noqa: F401
    from Path.Tool.assets import AssetUri
    from Path.Tool.camassets import cam_assets

    return cam_assets.get(AssetUri("toolbit://{}".format(bit_id)))


def available_post_processors():
    import Path.Preferences

    return list(Path.Preferences.allEnabledPostProcessors())


def _post_supports_flag(postname, flag):
    import Path.Preferences

    for folder in Path.Preferences.searchPathsPost():
        script = os.path.join(folder, postname + "_post.py")
        if os.path.exists(script):
            try:
                with open(script, "r", encoding="utf-8", errors="ignore") as f:
                    return flag in f.read()
            except OSError:
                return False
    return False


# =============================================================================
# CAM JOB CONSTRUCTION
# =============================================================================


def _gui():
    return bool(FreeCAD.GuiUp)


def find_existing_job(doc, part):
    for obj in doc.Objects:
        if getattr(obj, "LumberjackDrawer", None) == part.Name and hasattr(obj, "Operations"):
            return obj
    return None


def _union_bbox(objs):
    bb = None
    for o in objs:
        b = o.Shape.BoundBox
        if bb is None:
            bb = FreeCAD.BoundBox(b)
        else:
            bb.add(b)
    return bb


def _create_job(doc, part, bodies, settings):
    import Path.Main.Job as PathJob

    if _gui():
        import Path.Main.Gui.Job as PathJobGui

        job = PathJobGui.Create(bodies, None, openTaskPanel=False)
    else:
        job = PathJob.Create("Job", bodies, None)
    if job is None:
        raise RuntimeError("CAM Job creation failed (see report view)")
    job.Label = "CAM {}".format(part.Label)
    job.addProperty(
        "App::PropertyString",
        "LumberjackDrawer",
        "Lumberjack",
        "Name of the drawer Part this Job was generated from",
    )
    job.LumberjackDrawer = part.Name
    return job


def _configure_job(job, settings, out_path):
    posts = job.getEnumerationsOfProperty("PostProcessor")
    if settings.post in posts:
        job.PostProcessor = settings.post
    else:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: post processor '{}' not available, keeping '{}'\n".format(
                settings.post, job.PostProcessor
            )
        )
    args = job.PostProcessorArgs or ""
    if job.PostProcessor and "--no-show-editor" not in args:
        if _post_supports_flag(job.PostProcessor, "--no-show-editor"):
            job.PostProcessorArgs = (args + " --no-show-editor").strip()
    job.PostProcessorOutputFile = out_path
    sheet = job.SetupSheet
    for prop in ("HorizRapid", "VertRapid"):
        try:
            if _qty(getattr(sheet, prop)) <= 0:
                setattr(sheet, prop, RAPID_DEFAULT)
        except Exception:
            pass


def _mark_laid_out(clone):
    if "LumberjackLaidOut" not in clone.PropertiesList:
        clone.addProperty(
            "App::PropertyBool",
            "LumberjackLaidOut",
            "Lumberjack",
            "Set once the panel has been placed flat in the Job",
        )
    clone.LumberjackLaidOut = True


def _sync_models(job, doc, panels, frames, margin):
    """
    Make sure every panel body has a model clone in the Job.

    Clones already laid out keep their Placement (user layout). New clones are laid flat
    and appended to the right of the current layout. Clones of vanished bodies are removed.
    Returns {role: clone}.
    """
    import Path.Main.Job as PathJob

    body_names = {body.Name: role for role, body in panels}
    existing = {}
    for clone in list(job.Model.Group):
        src = clone.Objects[0] if getattr(clone, "Objects", None) else None
        if src is None or src.Name not in body_names:
            job.Proxy.removeBase(job, clone, True)
            continue
        existing[src.Name] = clone

    laid_out = [c for c in existing.values() if getattr(c, "LumberjackLaidOut", False)]
    cursor_x = margin
    if laid_out:
        doc.recompute()
        cursor_x = _union_bbox(laid_out).XMax + 2 * margin

    clones = {}
    for role, body in panels:
        clone = existing.get(body.Name)
        if clone is None:
            clone = PathJob.createModelResourceClone(job, body)
            job.Model.addObject(clone)
        if not getattr(clone, "LumberjackLaidOut", False):
            frame = frames[role]
            clone.Placement = FreeCAD.Placement(Vector(0, 0, 0), frame.rotation())
            doc.recompute()
            bb = clone.Shape.BoundBox
            pl = clone.Placement
            pl.Base = pl.Base + Vector(cursor_x - bb.XMin, margin - bb.YMin, -bb.ZMax)
            clone.Placement = pl
            doc.recompute()
            cursor_x += clone.Shape.BoundBox.XLength + 2 * margin
            _mark_laid_out(clone)
        clones[role] = clone
    return clones


def _clear_tools(job, doc):
    import Path.Base.Util as PathUtil

    tcs = list(job.Tools.Group)
    job.Tools.Group = []
    for tc in tcs:
        tool = getattr(tc, "Tool", None)
        PathUtil.clearExpressionEngine(tc)
        doc.removeObject(tc.Name)
        if tool is not None and not tool.InList:
            doc.removeObject(tool.Name)


def _setup_tool(job, doc, settings):
    import Path.Tool.Controller as PathToolController

    _clear_tools(job, doc)
    bit = load_toolbit(settings.bit_id)
    tool_obj = bit.attach_to_doc(doc)
    if tool_obj.ViewObject:
        tool_obj.ViewObject.Visibility = False
    name = "TC: {}".format(bit.label)
    if _gui():
        import Path.Tool.Gui.Controller as PathToolControllerGui

        tc = PathToolControllerGui.Create(name, tool_obj, 1)
    else:
        tc = PathToolController.Create(name, tool_obj, 1)
    job.Proxy.addToolController(tc)
    tc.HorizFeed = "{} mm/min".format(settings.feed_xy)
    tc.VertFeed = "{} mm/min".format(settings.feed_z)
    tc.SpindleSpeed = float(settings.spindle)
    return tc


def _clear_operations(job, doc):
    import Path.Base.Util as PathUtil

    ops = list(job.Operations.Group)
    job.Operations.Group = []
    # Collect dress-up chains too (their base ops are no longer in the group).
    all_ops = []
    stack = list(ops)
    while stack:
        op = stack.pop()
        if op in all_ops:
            continue
        all_ops.append(op)
        base = getattr(op, "Base", None)
        if base is not None and not isinstance(base, list) and hasattr(base, "Path"):
            stack.append(base)
    # Dress-ups first (they link to their base), then everything else.
    all_ops.sort(key=lambda o: 0 if _is_dressup(o) else 1)
    for op in all_ops:
        PathUtil.clearExpressionEngine(op)
        try:
            doc.removeObject(op.Name)
        except Exception as e:
            FreeCAD.Console.PrintWarning("Lumberjack: could not remove {}: {}\n".format(op.Name, e))
    job.Operations.Group = []


def _is_dressup(op):
    base = getattr(op, "Base", None)
    return base is not None and not isinstance(base, list) and hasattr(base, "Path")


def _setup_stock(job, doc, clones, margin):
    import Path.Main.Stock as PathStock

    doc.recompute()
    bb = _union_bbox(clones)
    old = job.Stock
    stock = PathStock.CreateBox(
        job,
        extent=Vector(bb.XLength + 2 * margin, bb.YLength + 2 * margin, bb.ZLength),
        placement=FreeCAD.Placement(
            Vector(bb.XMin - margin, bb.YMin - margin, bb.ZMin), FreeCAD.Rotation()
        ),
    )
    job.Stock = stock
    if old is not None:
        try:
            doc.removeObject(old.Name)
        except Exception:
            pass
    doc.recompute()
    return stock


def _attach_op_viewprovider(op, kind):
    if not _gui() or op.ViewObject is None:
        return
    import Path.Op.Gui.Base as PathOpGui

    if kind == "Slot":
        import Path.Op.Gui.Slot as OpGui
    else:
        import Path.Op.Gui.Profile as OpGui
    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, OpGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False
    op.ViewObject.Visibility = True


def _set_depths(op, start, final, step_down):
    for prop in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(prop, None)
    op.StartDepth = start
    op.FinalDepth = final
    op.StepDown = step_down


def _make_slot(job, name, tc, p1, p2, z_top, depth, step_down):
    import Path.Op.Slot as PathSlot

    op = PathSlot.Create(name, parentJob=job)
    _attach_op_viewprovider(op, "Slot")
    op.ToolController = tc
    op.Base = []
    op.CustomPoint1 = p1
    op.CustomPoint2 = Vector(p2.x, p2.y, p1.z)  # exact equality required by the Slot op
    op.LayerMode = "Multi-pass"
    op.CutPattern = "Line"
    op.ExtendPathStart = 0.0
    op.ExtendPathEnd = 0.0
    _set_depths(op, z_top, z_top - depth, step_down)
    return op


def _bottom_face_name(clone):
    """Name of the largest planar face pointing -Z at the model's lowest Z."""
    import Part

    shape = clone.Shape
    zmin = shape.BoundBox.ZMin
    best, best_area = None, -1.0
    for i, face in enumerate(shape.Faces):
        if not isinstance(face.Surface, Part.Plane):
            continue
        if abs(face.BoundBox.ZMax - zmin) > 1e-4:
            continue
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        if normal.z > -0.99:
            continue
        if face.Area > best_area:
            best, best_area = i, face.Area
    if best is None:
        raise RuntimeError("no downward face found on {}".format(clone.Label))
    return "Face{}".format(best + 1)


def _make_profile(job, name, tc, clone, z_top, thickness, step_down):
    import Path.Op.Profile as PathProfile

    op = PathProfile.Create(name, parentJob=job)
    _attach_op_viewprovider(op, "Profile")
    op.ToolController = tc
    op.Base = [(clone, [_bottom_face_name(clone)])]
    op.Side = "Outside"
    op.UseComp = True
    op.Direction = "CW"
    op.HandleMultipleFeatures = "Individually"
    op.processPerimeter = True
    op.processHoles = False
    op.processCircles = False
    op.OffsetExtra = 0.0
    _set_depths(op, z_top, z_top - thickness - THROUGH_OVERCUT, step_down)
    return op


def _make_tags(job, doc, profile, positions, thickness, name):
    import Path.Dressup.Tags as PathDressupTag

    tags = PathDressupTag.Create(profile, name)
    if tags is None:
        raise RuntimeError("could not create tags for {}".format(profile.Label))
    if _gui() and tags.ViewObject is not None:
        import Path.Dressup.Gui.Tags as PathDressupTagGui

        tags.ViewObject.Proxy = PathDressupTagGui.PathDressupTagViewProvider(tags.ViewObject)
    # The dress-up replaces its base in the operation list (the GUI view provider does
    # this on attach, headless nothing does, so do it explicitly and idempotently).
    group = job.Operations.Group
    if profile in group:
        group.remove(profile)
        job.Operations.Group = group
    if profile.ViewObject is not None:
        profile.ViewObject.Visibility = False
    tags.Width = TAB_WIDTH
    tags.Height = min(TAB_HEIGHT, thickness / 2.0)
    tags.Angle = 90.0
    tags.Radius = 0.0
    tags.Proxy.setXyEnabled([(x, y, True) for x, y in positions])
    doc.recompute()
    return tags


def _sanitize(text):
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return text or "unnamed"


def output_path_for(doc, part):
    """<docdir>/<Doc>_<Drawer>.nc (falls back to the working directory if unsaved)."""
    folder = os.path.dirname(doc.FileName) if doc.FileName else ""
    if not folder:
        folder = os.getcwd()
        FreeCAD.Console.PrintWarning(
            "Lumberjack: document is not saved, writing G-code to {}\n".format(folder)
        )
    return os.path.join(folder, "{}_{}.nc".format(_sanitize(doc.Label), _sanitize(part.Label)))


def post_process(job, doc):
    """Post-process the Job with its configured post processor. Returns written paths."""
    from Path.Post.Processor import PostProcessorFactory

    doc.recompute()
    if not job.PostProcessor:
        raise RuntimeError("Job has no post processor set")
    pp = PostProcessorFactory.get_post_processor(job, job.PostProcessor)
    sections = pp.export() or []
    base, ext = os.path.splitext(job.PostProcessorOutputFile)
    written = []
    for subpart, gcode in sections:
        if gcode is None:
            continue
        if len(sections) == 1 or subpart in ("", "allitems"):
            path = base + ext
        else:
            path = "{}_{}{}".format(base, _sanitize(str(subpart)), ext)
        with open(path, "w", encoding="utf-8") as f:
            f.write(gcode)
        written.append(path)
    return written


class JobResult:
    def __init__(self, job):
        self.job = job
        self.created = False
        self.slots = 0
        self.profiles = 0
        self.disabled_tabs = []
        self.gcode_files = []


def build_or_update_job(part, holder, settings):
    """
    Create the CAM Job for a drawer or regenerate its operations.

    Returns a JobResult.
    """
    doc = part.Document
    params = DrawerParams(holder)
    panels = drawer_panels(part)
    frames = {role: panel_frame(role, params) for role, _b in panels}
    margin = settings.margin

    job = find_existing_job(doc, part)
    result = None
    if job is None:
        job = _create_job(doc, part, [body for _r, body in panels], settings)
        result = JobResult(job)
        result.created = True
    else:
        result = JobResult(job)
    _configure_job(job, settings, output_path_for(doc, part))

    clones = _sync_models(job, doc, panels, frames, margin)
    _clear_operations(job, doc)
    tc = _setup_tool(job, doc, settings)
    _setup_stock(job, doc, list(clones.values()), margin)

    tool_d = settings.tool_d
    z_tops = {}
    # Pockets first: parts stay attached to the blank while grooves and rabbets are cut.
    for role, _body in panels:
        clone = clones[role]
        frame = frames[role]
        pl = clone.Placement
        z_top = clone.Shape.BoundBox.ZMax
        z_tops[role] = z_top
        for region in pocket_regions(role, params, frame):
            for i, ((u0, v0), (u1, v1)) in enumerate(slot_passes(region, tool_d)):
                p1 = pl.multVec(frame.to_local(u0, v0))
                p2 = pl.multVec(frame.to_local(u1, v1))
                _make_slot(
                    job,
                    "{}_{}_{}".format(role, region.name, i + 1),
                    tc, p1, p2, z_top, region.depth, settings.step_down,
                )
                result.slots += 1
    doc.recompute()

    # Then the outside profiles, each with hold-down tabs.
    profiles = []
    for role, _body in panels:
        clone = clones[role]
        frame = frames[role]
        op = _make_profile(
            job, "{}_Profile".format(role), tc, clone, z_tops[role], frame.t, settings.step_down
        )
        profiles.append((role, op, clone, frame))
        result.profiles += 1
    doc.recompute()

    for role, op, clone, frame in profiles:
        pl = clone.Placement
        corners = []
        for u, v in frame.corners():
            w = pl.multVec(frame.to_local(u, v))
            corners.append((w.x, w.y))
        positions = tab_positions(corners, tool_d / 2.0)
        tags = _make_tags(job, doc, op, positions, frame.t, "{}_Tags".format(role))
        if tags.Disabled:
            result.disabled_tabs.append((role, list(tags.Disabled)))
    doc.recompute()

    if settings.write_gcode:
        result.gcode_files = post_process(job, doc)
    return result


# =============================================================================
# DIALOG
# =============================================================================

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    try:
        from PySide import QtCore
        from PySide import QtGui as QtWidgets
    except ImportError:
        QtCore = QtWidgets = None


def _pref(key):
    return PREF_PREFIX + key


class CreateDrawerCamDialog(QtWidgets.QDialog):
    """Dialog collecting the CAM settings for one or more drawers."""

    def __init__(self, drawers, parent=None):
        super(CreateDrawerCamDialog, self).__init__(parent)
        self.setWindowTitle("Drawer CAM Job")
        self.setMinimumWidth(460)
        self.drawers = drawers
        self.bits = []
        self._setup_ui()

    def _quantity_spinbox(self, key, default, unit="mm"):
        widget = FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("unit", unit)
        try:
            value = float(_get_last_str(_pref(key), str(default)))
        except ValueError:
            value = float(default)
        widget.setProperty("rawValue", value)
        return widget

    def _row(self, layout, text, widget):
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(text + ":")
        label.setMinimumWidth(150)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        doc = FreeCAD.ActiveDocument
        lines = []
        for part, _holder in self.drawers:
            existing = find_existing_job(doc, part) if doc else None
            if existing is not None:
                lines.append(
                    "{}: existing Job '{}' found, layout kept, operations regenerated".format(
                        part.Label, existing.Label
                    )
                )
            else:
                lines.append("{}: new Job".format(part.Label))
        info = QtWidgets.QLabel("\n".join(lines))
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Tool ---
        tool_group = QtWidgets.QGroupBox("Tool")
        tool_layout = QtWidgets.QVBoxLayout(tool_group)
        self.bit_combo = QtWidgets.QComboBox()
        try:
            self.bits = list_toolbits()
        except Exception as e:
            FreeCAD.Console.PrintError("Lumberjack: could not read toolbit library: {}\n".format(e))
            self.bits = []
        last_bit = _get_last_str(_pref("bit_id"), "")
        for i, info_ in enumerate(self.bits):
            self.bit_combo.addItem(info_.text())
            if info_.bit_id == last_bit:
                self.bit_combo.setCurrentIndex(i)
        if not self.bits:
            self.bit_combo.addItem("(no tool bits in the CAM library)")
            self.bit_combo.setEnabled(False)
        self._row(tool_layout, "Tool bit", self.bit_combo)
        self.spindle = QtWidgets.QSpinBox()
        self.spindle.setRange(1000, 60000)
        self.spindle.setSingleStep(500)
        self.spindle.setSuffix(" rpm")
        self.spindle.setValue(int(float(_get_last_str(_pref("spindle"), "16000"))))
        self._row(tool_layout, "Spindle speed", self.spindle)
        self.feed_xy = self._quantity_spinbox("feed_xy", 360.0, "mm/min")
        self._row(tool_layout, "Feed XY", self.feed_xy)
        self.feed_z = self._quantity_spinbox("feed_z", 360.0, "mm/min")
        self._row(tool_layout, "Feed Z (plunge)", self.feed_z)
        self.step_down = self._quantity_spinbox("step_down", 3.0)
        self._row(tool_layout, "Step down", self.step_down)
        layout.addWidget(tool_group)

        # --- Machine ---
        machine_group = QtWidgets.QGroupBox("Machine")
        machine_layout = QtWidgets.QVBoxLayout(machine_group)
        self.bed_x = self._quantity_spinbox("bed_x", 1200.0)
        self._row(machine_layout, "Bed size X", self.bed_x)
        self.bed_y = self._quantity_spinbox("bed_y", 800.0)
        self._row(machine_layout, "Bed size Y", self.bed_y)
        self.post_combo = QtWidgets.QComboBox()
        try:
            posts = available_post_processors()
        except Exception as e:
            FreeCAD.Console.PrintError("Lumberjack: could not list post processors: {}\n".format(e))
            posts = []
        self.post_combo.addItems(posts)
        last_post = _get_last_str(_pref("post"), "uccnc")
        if last_post in posts:
            self.post_combo.setCurrentIndex(posts.index(last_post))
        self._row(machine_layout, "Post processor", self.post_combo)
        layout.addWidget(machine_group)

        self.write_check = QtWidgets.QCheckBox("Write G-code files now")
        self.write_check.setChecked(_get_last_bool(_pref("write_gcode"), True))
        layout.addWidget(self.write_check)

        note = QtWidgets.QLabel(
            "Tabs: {} per edge, {:g} mm wide, {:g} mm high. Panels are laid out in a row; "
            "move them in the Job and run the command again to regenerate.".format(
                TABS_PER_EDGE, TAB_WIDTH, TAB_HEIGHT
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        button_row = QtWidgets.QHBoxLayout()
        self.ok_button = QtWidgets.QPushButton("Create")
        self.ok_button.setDefault(True)
        self.ok_button.setEnabled(bool(self.bits))
        cancel = QtWidgets.QPushButton("Cancel")
        button_row.addStretch()
        button_row.addWidget(self.ok_button)
        button_row.addWidget(cancel)
        layout.addLayout(button_row)
        self.ok_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

    def _raw(self, widget):
        return float(widget.property("rawValue"))

    def get_settings(self):
        s = CamSettings()
        info = self.bits[self.bit_combo.currentIndex()]
        s.bit_id = info.bit_id
        s.bit_label = info.label
        s.tool_d = info.diameter
        s.cutting_edge_height = info.edge_height
        s.bed_x = self._raw(self.bed_x)
        s.bed_y = self._raw(self.bed_y)
        s.post = self.post_combo.currentText()
        s.spindle = float(self.spindle.value())
        s.feed_xy = self._raw(self.feed_xy)
        s.feed_z = self._raw(self.feed_z)
        s.step_down = self._raw(self.step_down)
        s.write_gcode = self.write_check.isChecked()
        return s


def remember_settings(s):
    _set_last_str(_pref("bit_id"), s.bit_id)
    _set_last_str(_pref("bed_x"), str(s.bed_x))
    _set_last_str(_pref("bed_y"), str(s.bed_y))
    _set_last_str(_pref("post"), s.post)
    _set_last_str(_pref("spindle"), str(s.spindle))
    _set_last_str(_pref("feed_xy"), str(s.feed_xy))
    _set_last_str(_pref("feed_z"), str(s.feed_z))
    _set_last_str(_pref("step_down"), str(s.step_down))
    _set_last_bool(_pref("write_gcode"), s.write_gcode)


def _message(title, text, error=False):
    if error:
        FreeCAD.Console.PrintError("Lumberjack: {}\n".format(text.replace("\n", "\n  ")))
    else:
        FreeCAD.Console.PrintMessage("Lumberjack: {}\n".format(text.replace("\n", "\n  ")))
    if _gui() and QtWidgets is not None:
        box = QtWidgets.QMessageBox(FreeCADGui.getMainWindow())
        box.setWindowTitle(title)
        box.setIcon(QtWidgets.QMessageBox.Critical if error else QtWidgets.QMessageBox.Information)
        box.setText(text)
        box.exec_()


def run(drawers, settings):
    """
    Validate and build/update the Jobs for [(part, holder)] with the given settings.

    Returns (results, problems, warnings). Nothing is modified when problems is non-empty.
    """
    problems = []
    warnings = []
    params = {}
    for part, holder in drawers:
        p = DrawerParams(holder)
        params[part.Name] = p
        pr, wa = validate_drawer(part, p, settings)
        problems.extend(pr)
        warnings.extend(wa)
    if problems:
        return [], problems, warnings

    results = []
    for part, holder in drawers:
        results.append(build_or_update_job(part, holder, settings))
    return results, problems, warnings


def show_create_drawer_cam_dialog():
    """Entry point of the command."""
    doc = FreeCAD.ActiveDocument
    if doc is None:
        _message("Drawer CAM Job", "No active document.", error=True)
        return None
    drawers, rejected = selected_drawers()
    if rejected:
        _message(
            "Drawer CAM Job",
            "Only drawers created with Lumberjack are supported.\nNot a drawer: {}".format(
                ", ".join(rejected)
            ),
            error=True,
        )
        return None
    if not drawers:
        _message("Drawer CAM Job", "Select one or more drawers first.", error=True)
        return None

    dialog = CreateDrawerCamDialog(drawers, FreeCADGui.getMainWindow())
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None
    settings = dialog.get_settings()

    results, problems, warnings = run(drawers, settings)
    if problems:
        _message("Drawer CAM Job", "Cannot create the CAM Job:\n- " + "\n- ".join(problems), error=True)
        return None
    remember_settings(settings)

    lines = []
    for r in results:
        lines.append(
            "{} {}: {} slot passes, {} profiles{}".format(
                r.job.Label,
                "created" if r.created else "regenerated",
                r.slots,
                r.profiles,
                ", G-code: " + ", ".join(r.gcode_files) if r.gcode_files else "",
            )
        )
        for role, ids in r.disabled_tabs:
            lines.append("  WARNING {}: tabs {} were disabled by CAM, check the profile".format(role, ids))
    if warnings:
        lines.append("")
        lines.extend("Note: " + w for w in warnings)
    doc.recompute()
    _message("Drawer CAM Job", "\n".join(lines))
    return results
