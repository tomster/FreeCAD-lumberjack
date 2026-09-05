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
3. The panels of all selected drawers are nested per thickness on sheets (nesting.py):
   panels hug the sheet's top-left corner, neighbours are one tool diameter apart so a
   single cut separates both. One CAM Job per sheet: the models are the panel bodies laid
   flat (pocketed face up, top face at Z = 0), the stock is the whole sheet with the
   chosen reference corner at the origin: top-left (X to the right, Y negative towards
   the operator) or bottom-left (Y positive). Panels hug the two edges at that corner.
   Operations: Slot passes for the bottom groove, the half-lap rabbets and the bottom's
   perimeter rabbet; one Slot per merged cut line with a Tags dress-up. Finally each Job
   is post-processed to <docdir>/<Doc>_CAM_<t>mm_<n>.nc.
4. Running the command again re-nests and replaces the Jobs of the selected drawers.

Geometry
--------
All pockets are computed in the *body-local* frame of each panel (each body is a slab
centered on its own origin, see drawers.py) and mapped into job coordinates through the
model clone's Placement, which is derived from the nest.
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
import nesting
import naming
import sheetdraw
from drawers import _get_last_bool, _get_last_str, _set_last_bool, _set_last_str

Vector = FreeCAD.Vector


# =============================================================================
# CONSTANTS (deliberately not user-configurable in this iteration)
# =============================================================================

ROLES = _drawers.PANEL_ROLES
WALL_ROLES = ("SideL", "SideR", "Back", "Front")

THROUGH_OVERCUT = 0.2  # mm cut past the panel bottom on through cuts
TAB_WIDTH = nesting.TAB_WIDTH  # mm
TAB_HEIGHT = 3.0  # mm (capped at half the panel thickness)
DEFAULT_SHEET_W = 630.0  # mm, machine work area X
DEFAULT_SHEET_H = 1080.0  # mm, machine work area Y
DEFAULT_CLAMP_H = 20.0  # mm, rapids clear this plus CLAMP_CLEARANCE_EXTRA
ORIGIN_TOP_LEFT = "top-left"  # zero at the far-left corner, Y negative towards the operator
ORIGIN_BOTTOM_LEFT = "bottom-left"  # zero at the near-left corner, Y positive
ORIGINS = (ORIGIN_TOP_LEFT, ORIGIN_BOTTOM_LEFT)
CLAMP_CLEARANCE_EXTRA = 2.0
PASS_OVERLAP = 0.5  # step-over between parallel slot passes as fraction of tool diameter
PASS_EXTENSION_EXTRA = 1.0  # mm beyond the tool radius that open-ended passes overshoot
JOB_GAP_FRACTION = 0.10  # gap between Jobs displayed side by side, as fraction of the sheet width
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
        self.sheet_w = 630.0
        self.sheet_h = 1080.0
        self.clamp_h = 20.0
        self.origin = ORIGIN_TOP_LEFT
        self.skip_drawer_front = True  # fronts are usually other material, plain rectangles
        self.post = ""
        self.spindle = 0.0
        self.feed_xy = 0.0
        self.feed_z = 0.0
        self.step_down = 0.0
        self.write_gcode = True


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
    clearance = nesting.edge_clearance(d)
    max_u, max_v = settings.sheet_w - clearance, settings.sheet_h - clearance
    for role, _body in panels:
        if role == "DrawerFront" and settings.skip_drawer_front:
            continue
        frame = panel_frame(role, params)
        for region in pocket_regions(role, params, frame):
            try:
                slot_passes(region, d)
            except ToolTooWide as e:
                problems.append("{} {}: {}".format(label, role, e))
        item = nesting.Item((label, role), frame.L, frame.W, frame.t)
        if not nesting.orientations(item, max_u, max_v):
            problems.append(
                "{} {}: {:.0f} x {:.0f} mm does not fit the {:.0f} x {:.0f} mm sheet "
                "(needs {:.0f} mm clearance at the right/bottom edges)".format(
                    label, role, frame.L, frame.W, settings.sheet_w, settings.sheet_h, clearance
                )
            )
        ceh = settings.cutting_edge_height
        if ceh is not None and ceh < frame.t + THROUGH_OVERCUT:
            warnings.append(
                "{} {}: cutting edge {:.1f} mm is shorter than the panel thickness "
                "{:.1f} mm".format(label, role, ceh, frame.t)
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


def find_lumberjack_jobs(doc, part_names):
    """Jobs generated by Lumberjack that involve any of the given drawer Part names."""
    names = set(part_names)
    jobs = []
    for obj in doc.Objects:
        if not hasattr(obj, "Operations"):
            continue
        involved = set(getattr(obj, "LumberjackDrawers", []) or [])
        single = getattr(obj, "LumberjackDrawer", None)  # jobs of the previous version
        if single:
            involved.add(single)
        if involved & names:
            jobs.append(obj)
    return jobs


CAM_GROUP_PROP = "LumberjackCamGroup"


def find_cam_groups(doc, part_names):
    """Lumberjack CAM containers (App::Part) involving any of the given drawer Part names."""
    names = set(part_names)
    return [
        obj
        for obj in doc.Objects
        if hasattr(obj, CAM_GROUP_PROP)
        and set(getattr(obj, "LumberjackDrawers", []) or []) & names
    ]


SHEET_FRAME_PROP = "LumberjackSheetFrame"


def _holding_groups(obj):
    """Groups whose Group list contains obj."""
    return [
        parent
        for parent in obj.InList
        if hasattr(parent, "Group") and obj in (parent.Group or [])
    ]


def sheet_frame_of(job):
    """The per-sheet App::Part that offsets the Job's display, or None."""
    for parent in _holding_groups(job):
        if hasattr(parent, SHEET_FRAME_PROP):
            return parent
    return None


def cam_group_of(job):
    """The Lumberjack CAM container holding the Job (directly or via its sheet frame)."""
    queue = list(_holding_groups(job))
    seen = set()
    while queue:
        parent = queue.pop(0)
        if parent.Name in seen:
            continue
        seen.add(parent.Name)
        if hasattr(parent, CAM_GROUP_PROP):
            return parent
        queue.extend(_holding_groups(parent))
    return None


def _create_sheet_frame(doc, container, label, x_offset):
    """
    An App::Part inside the container that shows one Job shifted along X.

    Only the display moves: the Job, its stock and operations keep machine coordinates,
    so the G-code is unaffected.
    """
    frame = doc.addObject("App::Part", "Sheet")
    frame.Label = label
    frame.addProperty(
        "App::PropertyBool", SHEET_FRAME_PROP, "Lumberjack", "Display frame of one sheet Job"
    )
    setattr(frame, SHEET_FRAME_PROP, True)
    frame.Placement = FreeCAD.Placement(FreeCAD.Vector(x_offset, 0, 0), FreeCAD.Rotation())
    container.addObject(frame)
    return frame


def cam_group_name(drawers):
    """Compact name for a collection of drawers [(part, holder)], see naming.group_name."""
    return naming.group_name([part.Label for part, _h in drawers])


def _create_cam_group(doc, drawers):
    """Create the App::Part container that collects the Jobs of one CAM run."""
    container = doc.addObject("App::Part", "CamJobs")
    container.Label = "CAM " + cam_group_name(drawers)
    container.addProperty(
        "App::PropertyBool", CAM_GROUP_PROP, "Lumberjack", "Container of Lumberjack CAM Jobs"
    )
    setattr(container, CAM_GROUP_PROP, True)
    container.addProperty(
        "App::PropertyStringList",
        "LumberjackDrawers",
        "Lumberjack",
        "Names of the drawer Parts whose Jobs live in this container",
    )
    container.LumberjackDrawers = sorted(part.Name for part, _h in drawers)
    return container


def _remove_cam_group_if_empty(container):
    doc = container.Document
    for child in list(container.Group):  # sheet frames whose Job is gone
        if hasattr(child, SHEET_FRAME_PROP) and not list(child.Group):
            doc.removeObject(child.Name)
    if list(container.Group):
        return False
    doc.removeObject(container.Name)
    return True


def delete_job(job):
    """Remove a CAM Job with all its resources (tools, bits, models, stock, operations)."""
    import Path.Base.Util as PathUtil

    doc = job.Document
    frame = sheet_frame_of(job)
    # Operations first, including dress-up bases (which are not in the Operations group
    # and would otherwise survive the Job's own teardown with dangling expressions).
    try:
        ops = list(job.Proxy.allOperations())
    except Exception:
        ops = list(job.Operations.Group) if getattr(job, "Operations", None) else []
    dressups = [o for o in ops if hasattr(o, "Base") and not isinstance(o.Base, list) and o.Base is not None]
    bases = [o for o in ops if o not in dressups]
    if getattr(job, "Operations", None):
        job.Operations.Group = []
    for op in dressups + bases:
        try:
            PathUtil.clearExpressionEngine(op)
            doc.removeObject(op.Name)
        except Exception as e:
            FreeCAD.Console.PrintWarning("Lumberjack: could not remove {}: {}\n".format(op.Name, e))
    try:
        _clear_tools(job, doc)
    except Exception as e:
        FreeCAD.Console.PrintWarning("Lumberjack: could not clear tools of {}: {}\n".format(job.Label, e))
    try:
        job.Proxy.onDelete(job, None)
    except Exception as e:
        FreeCAD.Console.PrintWarning("Lumberjack: job teardown of {} incomplete: {}\n".format(job.Label, e))
    for prop in ("Model", "Tools", "Operations", "SetupSheet"):
        child = getattr(job, prop, None)
        if child is not None:
            for sub in list(getattr(child, "Group", []) or []):
                try:
                    doc.removeObject(sub.Name)
                except Exception:
                    pass
            try:
                doc.removeObject(child.Name)
            except Exception:
                pass
    doc.removeObject(job.Name)
    if frame is not None:
        for obj in list(frame.Group):
            if obj.TypeId == "TechDraw::DrawPage":
                _remove_page(doc, obj)
        if not list(frame.Group):
            doc.removeObject(frame.Name)
    doc.recompute()


def _create_job(doc, bodies, label):
    import Path.Main.Job as PathJob

    if _gui():
        import Path.Main.Gui.Job as PathJobGui

        job = PathJobGui.Create(bodies, None, openTaskPanel=False)
    else:
        job = PathJob.Create("Job", bodies, None)
    if job is None:
        raise RuntimeError("CAM Job creation failed (see report view)")
    job.Label = label
    job.addProperty(
        "App::PropertyStringList",
        "LumberjackDrawers",
        "Lumberjack",
        "Names of the drawer Parts nested in this Job",
    )
    job.addProperty(
        "App::PropertyFloat", "LumberjackThickness", "Lumberjack", "Panel thickness of this sheet"
    )
    job.addProperty(
        "App::PropertyInteger", "LumberjackSheet", "Lumberjack", "Sheet number within its thickness"
    )
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
    # Rapids must clear the clamps on the top/left sheet edges.
    clear = settings.clamp_h + CLAMP_CLEARANCE_EXTRA
    sheet.ClearanceHeightOffset = "{} mm".format(clear)
    sheet.SafeHeightOffset = "{} mm".format(clear)


def _clear_tools(job, doc):
    import Path.Base.Util as PathUtil

    tcs = list(job.Tools.Group)
    job.Tools.Group = []
    for tc in tcs:
        tool = getattr(tc, "Tool", None)
        PathUtil.clearExpressionEngine(tc)
        doc.removeObject(tc.Name)
        if tool is not None and not _users_of(tool):
            _remove_toolbit(doc, tool)


def _users_of(obj):
    """Objects linking to obj other than the groups/containers that merely hold it."""
    return [
        o
        for o in obj.InList
        if not (hasattr(o, "Group") and obj in (o.Group or []) and not hasattr(o, "Tool"))
    ]


def _remove_toolbit(doc, tool):
    """Remove a ToolBit document object together with its imported shape geometry."""
    proxy = getattr(tool, "Proxy", None)
    if proxy is not None and hasattr(proxy, "onDelete"):
        try:
            proxy.onDelete(tool)  # removes BitBody (+ its features) and the tool object
            return
        except Exception as e:
            FreeCAD.Console.PrintWarning("Lumberjack: tool bit teardown incomplete: {}\n".format(e))
    body = getattr(tool, "BitBody", None)
    if body is not None:
        try:
            body.removeObjectsFromDocument()
            doc.removeObject(body.Name)
        except Exception:
            pass
    if doc.getObject(tool.Name) is not None:
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


def _setup_stock(job, doc, settings, thickness):
    """
    The stock is the whole sheet: X 0..sheet_w, Z -t..0 and Y -sheet_h..0 (top-left
    origin) or 0..sheet_h (bottom-left origin).
    """
    import Path.Main.Stock as PathStock

    y0 = -settings.sheet_h if settings.origin == ORIGIN_TOP_LEFT else 0.0
    old = job.Stock
    stock = PathStock.CreateBox(
        job,
        extent=Vector(settings.sheet_w, settings.sheet_h, thickness),
        placement=FreeCAD.Placement(Vector(0, y0, -thickness), FreeCAD.Rotation()),
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


def _make_tags(job, doc, base_op, positions, thickness, name):
    """Tags dress-up on a Slot cut; replaces the base op in the operation list."""
    import Path.Dressup.Tags as PathDressupTag

    tags = PathDressupTag.Create(base_op, name)
    if tags is None:
        raise RuntimeError("could not create tags for {}".format(base_op.Label))
    if _gui() and tags.ViewObject is not None:
        import Path.Dressup.Gui.Tags as PathDressupTagGui

        tags.ViewObject.Proxy = PathDressupTagGui.PathDressupTagViewProvider(tags.ViewObject)
    # The GUI view provider removes the base from the group on attach; headless nothing
    # does, so do it explicitly (idempotent) to avoid posting the cut twice.
    group = job.Operations.Group
    if base_op in group:
        group.remove(base_op)
        job.Operations.Group = group
    if base_op.ViewObject is not None:
        base_op.ViewObject.Visibility = False
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


def output_dir(doc):
    folder = os.path.dirname(doc.FileName) if doc.FileName else ""
    if not folder:
        folder = os.getcwd()
        FreeCAD.Console.PrintWarning(
            "Lumberjack: document is not saved, writing G-code to {}\n".format(folder)
        )
    return folder


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


# --- TechDraw overview page ---------------------------------------------------


PAGE_VIEW_PROP = "LumberjackView"


def page_view(page, role):
    """The page's view with the given role ("Title", "Sheet", "Legend"), or None."""
    for view in page.Views:
        if getattr(view, PAGE_VIEW_PROP, None) == role:
            return view
    return None


def default_template_path():
    """The TechDraw default template (user preference, else the shipped A4 landscape)."""
    pref = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files")
    path = pref.GetString("TemplateFile", "")
    if not path or not os.path.isfile(path):
        path = os.path.join(
            FreeCAD.getResourceDir(), "Mod", "TechDraw", "Templates", "Default_Template_A4_Landscape.svg"
        )
    return path


def _remove_page(doc, page):
    for view in list(getattr(page, "Views", []) or []):
        try:
            doc.removeObject(view.Name)
        except Exception:
            pass
    template = getattr(page, "Template", None)
    template_name = template.Name if template is not None else None
    doc.removeObject(page.Name)  # takes the template with it in recent versions
    if template_name and doc.getObject(template_name) is not None:
        doc.removeObject(template_name)


def make_sheet_page(doc, frame, sheet, refs, settings, title, subtitle):
    """
    A TechDraw page inside the sheet frame: title, the sheet with panels, cuts, tabs and
    inline labels, and a legend with one label strip per panel.
    """
    import TechDraw  # noqa: F401  (registers the TechDraw types)

    page = doc.addObject("TechDraw::DrawPage", "SheetPage")
    page.Label = title
    template = doc.addObject("TechDraw::DrawSVGTemplate", "SheetTemplate")
    template.Template = default_template_path()
    page.Template = template
    doc.recompute()  # template read -> page size known
    page_w, page_h = float(page.PageWidth), float(page.PageHeight)

    panels = []
    for placed in sheet.items:
        ref = refs[placed.item.key]
        item = placed.item
        panels.append(
            sheetdraw.Panel(
                placed.u0, placed.v0, placed.du, placed.dv, ref.body.Label,
                "{:g} x {:g} x {:g} mm".format(item.length, item.width, item.thickness),
            )
        )
    cuts = [sheetdraw.Cut(l.axis, l.pos, l.a0, l.a1, l.tabs) for l in sheet.lines]
    views = sheetdraw.compose(
        page_w, page_h, title, subtitle, settings.sheet_w, settings.sheet_h, panels, cuts,
        settings.tool_d, TAB_WIDTH, settings.origin == ORIGIN_TOP_LEFT,
    )
    for v in views:
        sym = doc.addObject("TechDraw::DrawViewSymbol", "Sheet" + v.name)
        sym.Label = v.name
        sym.addProperty("App::PropertyString", PAGE_VIEW_PROP, "Lumberjack", "Role of this view")
        setattr(sym, PAGE_VIEW_PROP, v.name)
        sym.Symbol = v.svg
        page.addView(sym)
        sym.X = v.x
        sym.Y = v.y
        sym.LockPosition = False
    doc.recompute()
    frame.addObject(page)
    return page


# --- layout -> job placement ---------------------------------------------------


def _clone_placement(frame, placed, origin):
    """
    Rotation that lays a panel flat on the sheet, featured face up.

    Unrotated: panel length along X, and the panel-frame "up" side (v, where a wall's
    groove is NOT) pointing away from the reference edge along X, i.e. towards -Y for a
    top-left origin and +Y for a bottom-left origin. Rotated: length along +Y, v along -X,
    so the groove side ends up away from the sheet's left edge (the reference edge in both
    cases).
    """
    rot = frame.rotation()  # U -> X, V -> Y, N -> Z
    if placed.rotated:
        rot = FreeCAD.Rotation(Vector(0, 0, 1), 90).multiply(rot)  # X -> Y, Y -> -X
    elif origin == ORIGIN_BOTTOM_LEFT:
        rot = FreeCAD.Rotation(Vector(0, 0, 1), 180).multiply(rot)  # X -> -X, Y -> -Y
    return FreeCAD.Placement(Vector(0, 0, 0), rot)


def _place_clone(doc, clone, frame, placed, origin):
    """Position a model clone at its nested location (reference corner at (u0, ±v0))."""
    clone.Placement = _clone_placement(frame, placed, origin)
    doc.recompute()
    bb = clone.Shape.BoundBox
    pl = clone.Placement
    if origin == ORIGIN_TOP_LEFT:
        dy = -placed.v0 - bb.YMax
    else:
        dy = placed.v0 - bb.YMin
    pl.Base = pl.Base + Vector(placed.u0 - bb.XMin, dy, -bb.ZMax)
    clone.Placement = pl
    doc.recompute()


def layout_to_job(u, v, origin):
    """
    Layout frame (u right, v away from the reference edge along X) -> job XY.

    Top-left origin: Y = -v. Bottom-left origin: Y = +v.
    """
    return Vector(u, -v if origin == ORIGIN_TOP_LEFT else v, 0)


def edge_name_along_x(origin):
    """Physical name of the sheet edge that lies along X at Y = 0."""
    return "top" if origin == ORIGIN_TOP_LEFT else "bottom"


class PanelRef:
    """Everything the job builder needs to know about one nested panel."""

    def __init__(self, part, holder, params, role, body, frame):
        self.part = part
        self.holder = holder
        self.params = params
        self.role = role
        self.body = body
        self.frame = frame

    @property
    def key(self):
        return (self.part.Name, self.role)


def collect_items(drawers, skip_drawer_front=True):
    """nesting.Item list for the panels of [(part, holder)]."""
    items = []
    for part, holder in drawers:
        params = DrawerParams(holder)
        for role, body in drawer_panels(part):
            if role == "DrawerFront" and skip_drawer_front:
                continue
            frame = panel_frame(role, params)
            ref = PanelRef(part, holder, params, role, body, frame)
            items.append(nesting.Item(ref.key, frame.L, frame.W, frame.t, data=ref))
    return items


def group_by_thickness(items):
    groups = {}
    for item in items:
        groups.setdefault(round(item.thickness, 2), []).append(item)
    return [groups[t] for t in sorted(groups)]


class SheetJobResult:
    def __init__(self, job, thickness, sheet):
        self.job = job
        self.thickness = thickness
        self.sheet = sheet
        self.pocket_slots = 0
        self.cut_slots = 0
        self.disabled_tabs = []
        self.gcode_files = []
        self.container = None
        self.frame = None
        self.page = None

    @property
    def drawers(self):
        return sorted({p.item.data.part.Label for p in self.sheet.items})


def build_sheet_job(doc, sheet, thickness, sheet_no, settings, out_dir, container, x_offset=0.0):
    """
    Create one CAM Job for one nested sheet inside the run's container.

    The Job lives in its own sheet frame (App::Part) displayed x_offset to the right, so
    several sheets do not overlap in the 3D view while all keep machine coordinates.
    """
    refs = {p.item.key: p.item.data for p in sheet.items}
    bodies = [p.item.data.body for p in sheet.items]
    drawer_names = sorted({r.part.Name for r in refs.values()})
    label = "{:g}mm sheet {}".format(thickness, sheet_no)
    if set(drawer_names) != set(container.LumberjackDrawers):  # only some of the drawers
        label += " ({})".format(", ".join(sorted({r.part.Label for r in refs.values()})))
    sheet_frame = _create_sheet_frame(doc, container, label, x_offset)
    job = _create_job(doc, bodies, "Job " + label)
    job.LumberjackDrawers = drawer_names
    job.LumberjackThickness = float(thickness)
    job.LumberjackSheet = int(sheet_no)
    group_slug = _sanitize(re.sub(r"^CAM\s+", "", container.Label))
    out_path = os.path.join(
        out_dir,
        "{}_{}_{:g}mm_{}.nc".format(_sanitize(doc.Label), group_slug, thickness, sheet_no),
    )
    _configure_job(job, settings, out_path)
    result = SheetJobResult(job, thickness, sheet)
    result.container = container
    result.frame = sheet_frame

    # Place every model clone where the nest put its panel.
    clones = {}
    for clone in list(job.Model.Group):
        src = clone.Objects[0] if getattr(clone, "Objects", None) else None
        if src is None:
            continue
        for placed in sheet.items:
            if placed.item.data.body.Name == src.Name:
                _place_clone(doc, clone, placed.item.data.frame, placed, settings.origin)
                clones[placed.item.key] = clone
                break

    tc = _setup_tool(job, doc, settings)
    _setup_stock(job, doc, settings, thickness)
    tool_d = settings.tool_d

    # Pockets first (grooves, rabbets) so panels stay attached while pocketing.
    for placed in sheet.items:
        ref = placed.item.data
        clone = clones[placed.item.key]
        frame = ref.frame
        pl = clone.Placement
        z_top = clone.Shape.BoundBox.ZMax
        for region in pocket_regions(ref.role, ref.params, frame):
            for i, ((u0, v0), (u1, v1)) in enumerate(slot_passes(region, tool_d)):
                p1 = pl.multVec(frame.to_local(u0, v0))
                p2 = pl.multVec(frame.to_local(u1, v1))
                _make_slot(
                    job,
                    "{}_{}_{}_{}".format(_sanitize(ref.part.Label), ref.role, region.name, i + 1),
                    tc, p1, p2, z_top, region.depth, settings.step_down,
                )
                result.pocket_slots += 1
    doc.recompute()

    # Outline cuts: one Slot per merged cut line, tabs from the nest.
    cut_ops = []
    origin = settings.origin
    for i, line in enumerate(sheet.lines):
        if line.axis == "h":
            p1, p2 = layout_to_job(line.a0, line.pos, origin), layout_to_job(line.a1, line.pos, origin)
            tabs = [layout_to_job(t, line.pos, origin) for t in line.tabs]
        else:
            p1, p2 = layout_to_job(line.pos, line.a0, origin), layout_to_job(line.pos, line.a1, origin)
            tabs = [layout_to_job(line.pos, t, origin) for t in line.tabs]
        tabs = [(t.x, t.y) for t in tabs]
        name = "Cut{:g}mm_{}_{}{}".format(thickness, sheet_no, i + 1, "H" if line.axis == "h" else "V")
        op = _make_slot(job, name, tc, p1, p2, 0.0, thickness + THROUGH_OVERCUT, settings.step_down)
        cut_ops.append((op, tabs, name))
        result.cut_slots += 1
    doc.recompute()
    for op, tabs, name in cut_ops:
        if not tabs:
            continue
        tags = _make_tags(job, doc, op, tabs, thickness, name + "_Tags")
        if tags.Disabled:
            result.disabled_tabs.append((name, list(tags.Disabled)))
    doc.recompute()

    # Move the Job into its frame only now: App::Part.addObject pulls the whole tree of
    # local links (stock, tools, operations, dress-ups, clones) along, but objects created
    # later would stay outside and trip the link-scope check.
    sheet_frame.addObject(job)
    doc.recompute()

    title = os.path.basename(out_path)
    subtitle = "{}  |  {} panels, {} cuts, {} tabs  |  zero at the {} corner".format(
        os.path.dirname(out_path), len(sheet.items), len(sheet.lines),
        sum(len(l.tabs) for l in sheet.lines), settings.origin,
    )
    result.page = make_sheet_page(doc, sheet_frame, sheet, refs, settings, title, subtitle)

    if settings.write_gcode:
        result.gcode_files = post_process(job, doc)
    return result


def run(drawers, settings):
    """
    Validate, nest and build the sheet Jobs for [(part, holder)].

    Existing Lumberjack Jobs and containers involving any of the drawers are replaced;
    drawers that shared them are re-nested along (otherwise their panels would lose their
    Job). The Jobs go into one App::Part container named after the drawers; a container
    covering exactly the same drawers is reused, so a renamed container keeps its name.
    Returns (results, problems, warnings). Nothing is modified when problems is non-empty.
    """
    problems = []
    warnings = []
    drawers = list(drawers)
    doc = drawers[0][0].Document
    names = {part.Name for part, _h in drawers}
    extra = []
    while True:  # expand until every touched Job and container is fully covered
        involved = set()
        for obj in find_lumberjack_jobs(doc, names) + find_cam_groups(doc, names):
            involved.update(getattr(obj, "LumberjackDrawers", []) or [])
        added = False
        for name in sorted(involved - names):
            other = doc.getObject(name)
            other_holder = _drawers.drawer_holder(other) if other is not None else None
            names.add(name)  # even if the drawer is gone: nothing more to expand from it
            if other_holder is not None:
                drawers.append((other, other_holder))
                extra.append(other.Label)
                added = True
        if not added:
            break
    names = {part.Name for part, _h in drawers}
    if extra:
        warnings.append(
            "also re-nested drawers that shared sheets with the selection: {}".format(
                ", ".join(sorted(extra))
            )
        )
    for part, holder in drawers:
        pr, wa = validate_drawer(part, DrawerParams(holder), settings)
        problems.extend(pr)
        warnings.extend(wa)
    if problems:
        return [], problems, warnings

    items = collect_items(drawers, settings.skip_drawer_front)
    if not items:
        problems.append("nothing to cut (only drawer fronts selected and those are skipped)")
        return [], problems, warnings
    nested = []  # (thickness, [Sheet])
    for group in group_by_thickness(items):
        try:
            sheets = nesting.nest(group, settings.sheet_w, settings.sheet_h, settings.tool_d)
        except nesting.DoesNotFit as e:
            problems.append(str(e))
            continue
        nested.append((group[0].thickness, sheets))
    if problems:
        return [], problems, warnings

    old_groups = {g.Name: g for g in find_cam_groups(doc, names)}
    for job in find_lumberjack_jobs(doc, names):
        group = cam_group_of(job)
        if group is not None:
            old_groups[group.Name] = group
        delete_job(job)
    container = None
    for group in list(old_groups.values()):
        if container is None and set(group.LumberjackDrawers) == names:
            container = group  # same drawers: keep it (and its possibly edited label)
        elif not _remove_cam_group_if_empty(group):
            warnings.append(
                "kept container '{}': it holds objects not created by Lumberjack".format(group.Label)
            )
    if container is None:
        container = _create_cam_group(doc, drawers)

    out_dir = output_dir(doc)
    results = []
    pitch = settings.sheet_w * (1.0 + JOB_GAP_FRACTION)  # sheets side by side in the view
    for thickness, sheets in nested:
        for sheet in sheets:
            results.append(
                build_sheet_job(
                    doc, sheet, thickness, sheet.index + 1, settings, out_dir, container,
                    x_offset=len(results) * pitch,
                )
            )
    doc.recompute()
    return results, problems, warnings


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
        labels = ", ".join(part.Label for part, _holder in self.drawers)
        existing = find_lumberjack_jobs(doc, [p.Name for p, _h in self.drawers]) if doc else []
        text = "Drawers: {}".format(labels)
        if existing:
            text += "\nExisting Jobs will be replaced: {}".format(
                ", ".join(j.Label for j in existing)
            )
        info = QtWidgets.QLabel(text)
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

        # --- Machine / sheet ---
        machine_group = QtWidgets.QGroupBox("Sheet and machine")
        machine_layout = QtWidgets.QVBoxLayout(machine_group)
        self.sheet_w = self._quantity_spinbox("sheet_w", DEFAULT_SHEET_W)
        self._row(machine_layout, "Sheet width (X)", self.sheet_w)
        self.sheet_h = self._quantity_spinbox("sheet_h", DEFAULT_SHEET_H)
        self._row(machine_layout, "Sheet height (Y)", self.sheet_h)
        self.clamp_h = self._quantity_spinbox("clamp_h", DEFAULT_CLAMP_H)
        self._row(machine_layout, "Clamp height", self.clamp_h)
        self.origin_combo = QtWidgets.QComboBox()
        self.origin_combo.addItem("Top-left corner (Y negative towards you)", ORIGIN_TOP_LEFT)
        self.origin_combo.addItem("Bottom-left corner (Y positive)", ORIGIN_BOTTOM_LEFT)
        last_origin = _get_last_str(_pref("origin"), ORIGIN_TOP_LEFT)
        self.origin_combo.setCurrentIndex(max(0, self.origin_combo.findData(last_origin)))
        self._row(machine_layout, "Origin corner", self.origin_combo)
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

        self.skip_front_check = QtWidgets.QCheckBox(
            "Skip drawer fronts (plain rectangles, usually other material)"
        )
        self.skip_front_check.setChecked(_get_last_bool(_pref("skip_front"), True))
        layout.addWidget(self.skip_front_check)

        self.write_check = QtWidgets.QCheckBox("Write G-code files now")
        self.write_check.setChecked(_get_last_bool(_pref("write_gcode"), True))
        layout.addWidget(self.write_check)

        note = QtWidgets.QLabel(
            "Zero is the chosen sheet corner (X to the right). Panels hug the two sheet "
            "edges at that corner; clamp there. One Job per sheet and thickness; existing "
            "Jobs of these drawers are replaced. Tabs {:g} mm wide, {:g} mm high, rapids "
            "clear the clamp height.".format(TAB_WIDTH, TAB_HEIGHT)
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
        s.sheet_w = self._raw(self.sheet_w)
        s.sheet_h = self._raw(self.sheet_h)
        s.clamp_h = self._raw(self.clamp_h)
        s.origin = self.origin_combo.currentData() or ORIGIN_TOP_LEFT
        s.skip_drawer_front = self.skip_front_check.isChecked()
        s.post = self.post_combo.currentText()
        s.spindle = float(self.spindle.value())
        s.feed_xy = self._raw(self.feed_xy)
        s.feed_z = self._raw(self.feed_z)
        s.step_down = self._raw(self.step_down)
        s.write_gcode = self.write_check.isChecked()
        return s


def remember_settings(s):
    _set_last_str(_pref("bit_id"), s.bit_id)
    _set_last_str(_pref("sheet_w"), str(s.sheet_w))
    _set_last_str(_pref("sheet_h"), str(s.sheet_h))
    _set_last_str(_pref("clamp_h"), str(s.clamp_h))
    _set_last_str(_pref("origin"), s.origin)
    _set_last_bool(_pref("skip_front"), s.skip_drawer_front)
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


def summarize_results(results, warnings, origin=ORIGIN_TOP_LEFT):
    lines = []
    x_edge = edge_name_along_x(origin)
    containers = []
    for r in results:
        if r.container is not None and r.container not in containers:
            containers.append(r.container)
    for c in containers:
        lines.append(
            "Jobs collected in '{}' (sheets shown side by side, {:.0f} % apart; "
            "G-code coordinates are unaffected)".format(c.Label, JOB_GAP_FRACTION * 100)
        )
    for r in results:
        s = r.sheet
        lines.append(
            "{}: {} panels, blank at least {:.0f} x {:.0f} mm, {} pocket passes, {} cuts{}".format(
                r.job.Label, len(s.items), s.used_w, s.used_h, r.pocket_slots, r.cut_slots,
                ", G-code: " + ", ".join(r.gcode_files) if r.gcode_files else "",
            )
        )
        if s.top_edge_cuts():
            lines.append("  cuts reach the {} edge at x = {} (no clamps there)".format(
                x_edge, ", ".join("{:.0f}".format(u) for u in s.top_edge_cuts())))
        if s.left_edge_cuts():
            lines.append("  cuts reach the left edge {} mm from the origin at y = {} (no clamps there)".format(
                ", ".join("{:.0f}".format(v) for v in s.left_edge_cuts()),
                ", ".join("{:.0f}".format(-v if origin == ORIGIN_TOP_LEFT else v) for v in s.left_edge_cuts())))
        for name, ids in r.disabled_tabs:
            lines.append("  WARNING {}: tabs {} were disabled by CAM, check the cut".format(name, ids))
    if warnings:
        lines.append("")
        lines.extend("Note: " + w for w in warnings)
    return lines


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
        _message("Drawer CAM Job", "Cannot create the CAM Jobs:\n- " + "\n- ".join(problems), error=True)
        return None
    remember_settings(settings)
    doc.recompute()
    _message("Drawer CAM Job", "\n".join(summarize_results(results, warnings, settings.origin)))
    return results
