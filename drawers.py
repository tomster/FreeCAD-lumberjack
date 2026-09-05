# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - drawers.py

Parametric drawer creation, analogous to panels.py.

A drawer is an App::Part (Std_Part) placed inside the currently active container.
It contains:
  - a lightweight parameter "holder" object (App::FeaturePython, label "Parameters")
    that carries every drawer parameter as an editable, expression-capable property,
  - the drawer panels, each a PartDesign::Body named after the drawer:
      <Name>_SideL, <Name>_SideR, <Name>_Back, <Name>_Front, <Name>_Bottom
      and optionally <Name>_DrawerFront.

Why a holder instead of putting the parameters directly on the App::Part?
  FreeCAD raises a cyclic-reference error when a child object (a body inside the Part)
  references a property of its own parent App::Part (verified on FreeCAD 1.1.1, both for
  sketch-constraint expressions and Body.Placement expressions). A sibling holder object
  inside the Part can be referenced freely, so it is the robust place to store the
  editable, expression-driven parameters. The holder has no Shape and is therefore
  ignored by the cutlist macro.

Geometry / coordinate system (drawer-Part local):
  X = width, Y = depth, Z = up (height).
  The bottom panel is centered in X and Y on the origin; its bottom face is at z = 0
  (at the default bottom_v_offset of 0).

All panel bodies are built as "centered slabs" (a centered rectangle sketched on a body
datum plane, padded symmetrically so the slab is centered in its thickness) and then
positioned with expression-driven Body.Placement.Base, with no rotations. Grooves for the
bottom are cut as ThroughAll pockets that run the full length of each wall.

Bottom joint (decided live by the expression t_bottom < t_side):
  - inserted (t_bottom < t_side): the bottom keeps its full thickness, the groove is
    t_bottom wide and starts t_bottom above the box bottom (plus bottom_v_offset); the
    bottom's rabbet pocket is suppressed.
  - captured (t_bottom >= t_side): groove t_bottom / 2 wide starting t_bottom / 2 above
    the box bottom, the bottom is rabbeted to a t_bottom / 2 tongue.

The whole drawer Part is rotated 180 deg about Z so its front (the optional drawer front
and the front wall) faces the FreeCAD "front" (-Y) view direction.
"""

import FreeCAD
import FreeCADGui
import Part
import Sketcher

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide import QtCore
    from PySide import QtGui as QtWidgets


# =============================================================================
# PREFERENCES (remember last used values/expressions between invocations)
# =============================================================================


def _get_param_group():
    """Get the parameter group for storing drawer preferences."""
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Lumberjack")


def _get_last_str(key, default):
    return _get_param_group().GetString(key, default)


def _set_last_str(key, value):
    _get_param_group().SetString(key, value)


def _get_last_bool(key, default):
    return _get_param_group().GetBool(key, default)


def _set_last_bool(key, value):
    _get_param_group().SetBool(key, bool(value))


# Length parameters: (key, label, default expression)
BOX_FIELDS = [
    ("drawer_width", "Width", "400 mm"),
    ("drawer_height", "Height", "120 mm"),
    ("drawer_depth", "Depth", "500 mm"),
    ("drawer_t_side", "Side thickness", "12 mm"),
    ("drawer_t_bottom", "Bottom thickness", "6 mm"),
    ("drawer_bottom_v_offset", "Bottom offset", "0 mm"),
]

FRONT_FIELDS = [
    ("drawer_width_front", "Front width", "440 mm"),
    ("drawer_height_front", "Front height", "160 mm"),
    ("drawer_t_front", "Front thickness", "18 mm"),
    ("drawer_front_v_offset", "Front offset", "20 mm"),
]

# Maps a preference key to the holder property name it drives.
_KEY_TO_PROP = {
    "drawer_width": "width",
    "drawer_height": "height",
    "drawer_depth": "depth",
    "drawer_t_side": "t_side",
    "drawer_t_bottom": "t_bottom",
    "drawer_bottom_v_offset": "bottom_v_offset",
    "drawer_width_front": "width_front",
    "drawer_height_front": "height_front",
    "drawer_t_front": "t_front",
    "drawer_front_v_offset": "front_v_offset",
}


# =============================================================================
# DRAWER DISCOVERY
# =============================================================================

PANEL_ROLES = ("SideL", "SideR", "Back", "Front", "Bottom", "DrawerFront")


def _is_holder(obj):
    if hasattr(obj, "Shape"):
        return False
    props = getattr(obj, "PropertiesList", [])
    return all(p in props for p in ("width", "t_side", "t_bottom", "overlap_box"))


def drawer_holder(part):
    """Return the parameter holder of a drawer Part, or None."""
    if getattr(part, "TypeId", "") != "App::Part":
        return None
    for child in part.Group:
        if _is_holder(child):
            return child
    return None


def find_drawer_part(obj):
    """
    Resolve any object (drawer Part, body, feature, or a generated CAM Job) to its drawer.

    Returns (part, holder) or None.
    """
    if obj is None:
        return None
    if hasattr(obj, "LumberjackDrawer"):
        part = obj.Document.getObject(obj.LumberjackDrawer)
        holder = drawer_holder(part) if part else None
        if holder:
            return part, holder
    queue = [obj]
    seen = set()
    while queue:
        o = queue.pop(0)
        if o.Name in seen:
            continue
        seen.add(o.Name)
        holder = drawer_holder(o)
        if holder:
            return o, holder
        queue.extend(o.InList)
    return None


def selected_drawers():
    """
    Resolve the current selection to drawers.

    Returns (drawers, rejected): drawers is a list of (part, holder) without duplicates,
    rejected the labels of selected objects that are not part of a drawer.
    """
    drawers = []
    rejected = []
    if not hasattr(FreeCADGui, "Selection"):
        return drawers, rejected
    seen = set()
    for obj in FreeCADGui.Selection.getSelection():
        found = find_drawer_part(obj)
        if found is None:
            rejected.append(obj.Label)
            continue
        part, holder = found
        if part.Name not in seen:
            seen.add(part.Name)
            drawers.append((part, holder))
    return drawers, rejected


def drawer_panels(part):
    """Return [(role, body)] for the panel bodies of a drawer, in PANEL_ROLES order."""
    panels = []
    for child in part.Group:
        if child.TypeId != "PartDesign::Body":
            continue
        role = child.Name.rsplit("_", 1)[-1]
        if role in PANEL_ROLES:
            panels.append((role, child))
    panels.sort(key=lambda rb: PANEL_ROLES.index(rb[0]))
    return panels


def _strip_outer_parens(expr):
    """Remove one pair of enclosing parentheses if they wrap the whole expression."""
    e = expr.strip()
    if not (e.startswith("(") and e.endswith(")")):
        return e
    depth = 0
    for i, ch in enumerate(e):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(e) - 1:
                return e  # the first "(" closes before the end: not a wrapping pair
    return e[1:-1].strip()


def read_drawer_values(holder):
    """
    Read a drawer's parameters back as a values dict (see create_parameter_holder).

    Expressions are returned as written (spreadsheet references survive); properties
    without an expression are returned as "<value> mm".
    """
    exprs = dict(holder.ExpressionEngine)
    values = {}
    for prop in _HOLDER_LENGTH_PROPS:
        expr = exprs.get(prop)
        if expr:
            values[prop] = _strip_outer_parens(expr)
        else:
            values[prop] = "{} mm".format(getattr(holder, prop).Value)
    values["overlap_box"] = bool(holder.overlap_box)
    values["has_front"] = bool(holder.has_front)
    return values


# =============================================================================
# PARAMETER HOLDER
# =============================================================================


# Property name, default value (used only before the expression is applied).
_HOLDER_LENGTH_PROPS = [
    "width",
    "height",
    "depth",
    "t_side",
    "t_bottom",
    "bottom_v_offset",
    "width_front",
    "height_front",
    "t_front",
    "front_v_offset",
]


def create_parameter_holder(doc, part, name, label, values):
    """
    Create the parameter holder object inside the drawer Part.

    Args:
        doc: the active document
        part: the drawer App::Part the holder is placed in
        name: base name of the drawer (used to build the holder name)
        values: dict mapping holder property names to expression strings (length props)
                plus "overlap_box" and "has_front" booleans.

    Returns:
        The holder object.
    """
    holder = doc.addObject("App::FeaturePython", "{}_Params".format(name))
    holder.Label = "{} Parameters".format(label)
    part.addObject(holder)

    for prop in _HOLDER_LENGTH_PROPS:
        holder.addProperty(
            "App::PropertyLength", prop, "Drawer", "Drawer parameter '{}'".format(prop)
        )
    holder.addProperty(
        "App::PropertyBool",
        "overlap_box",
        "Drawer",
        "Box joints (panels fully overlap) instead of half-lap dados",
    )
    holder.addProperty(
        "App::PropertyBool",
        "has_front",
        "Drawer",
        "Whether the drawer has a dedicated front panel",
    )

    # Booleans first (referenced by ternary expressions).
    holder.overlap_box = bool(values.get("overlap_box", False))
    holder.has_front = bool(values.get("has_front", False))

    # Apply the length expressions.
    for prop in _HOLDER_LENGTH_PROPS:
        expr = values.get(prop)
        if expr:
            try:
                holder.setExpression(prop, "({})".format(expr))
            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    "Lumberjack: Could not set expression on {}.{}: {}\n".format(
                        holder.Name, prop, e
                    )
                )

    doc.recompute()
    return holder


# =============================================================================
# SKETCH / BODY GEOMETRY HELPERS
# =============================================================================


def _datum_plane(body, role):
    """Return the body origin datum plane with the given Role, or None."""
    for feature in body.Origin.OriginFeatures:
        if getattr(feature, "Role", "") == role:
            return feature
    return None


def _add_centered_rect(sketch, init_a=20.0, init_b=10.0):
    """
    Add a rectangle centered on the sketch origin in both axes.

    Returns (width_constraint_idx, height_constraint_idx) where width is along the
    sketch local X axis and height along the sketch local Y axis.
    """
    a, b = init_a, init_b
    g = len(sketch.Geometry)  # base index so this works for nested rectangles
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(-a, -b, 0), FreeCAD.Vector(a, -b, 0))
    )
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(a, -b, 0), FreeCAD.Vector(a, b, 0))
    )
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(a, b, 0), FreeCAD.Vector(-a, b, 0))
    )
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(-a, b, 0), FreeCAD.Vector(-a, -b, 0))
    )
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", g + i, 2, g + (i + 1) % 4, 1)
        )
    sketch.addConstraint(Sketcher.Constraint("Horizontal", g + 0))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", g + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", g + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", g + 3))
    # Center on the origin.
    sketch.addConstraint(Sketcher.Constraint("Symmetric", g + 0, 1, g + 2, 1, -1, 1))
    wi = sketch.addConstraint(Sketcher.Constraint("DistanceX", g + 0, 1, g + 0, 2, 2 * a))
    hi = sketch.addConstraint(Sketcher.Constraint("DistanceY", g + 1, 1, g + 1, 2, 2 * b))
    return wi, hi


def _add_positioned_rect(sketch, u0_init=0.0, v0_init=0.0, du_init=10.0, dv_init=10.0):
    """
    Add a rectangle whose lower-left corner sits at (u0, v0) with size (du, dv).

    Returns (u0_idx, v0_idx, du_idx, dv_idx) constraint indices, in that order.
    """
    u0, v0, du, dv = u0_init, v0_init, du_init, dv_init
    g = len(sketch.Geometry)
    p0 = FreeCAD.Vector(u0, v0, 0)
    p1 = FreeCAD.Vector(u0 + du, v0, 0)
    p2 = FreeCAD.Vector(u0 + du, v0 + dv, 0)
    p3 = FreeCAD.Vector(u0, v0 + dv, 0)
    sketch.addGeometry(Part.LineSegment(p0, p1))
    sketch.addGeometry(Part.LineSegment(p1, p2))
    sketch.addGeometry(Part.LineSegment(p2, p3))
    sketch.addGeometry(Part.LineSegment(p3, p0))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", g + i, 2, g + (i + 1) % 4, 1)
        )
    sketch.addConstraint(Sketcher.Constraint("Horizontal", g + 0))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", g + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", g + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", g + 3))
    u0_idx = sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, g + 0, 1, u0))
    v0_idx = sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, g + 0, 1, v0))
    du_idx = sketch.addConstraint(Sketcher.Constraint("DistanceX", g + 0, 1, g + 0, 2, du))
    dv_idx = sketch.addConstraint(Sketcher.Constraint("DistanceY", g + 1, 1, g + 1, 2, dv))
    return u0_idx, v0_idx, du_idx, dv_idx


def _create_body(doc, part, name, label):
    """Create a PartDesign::Body inside the drawer part and return it."""
    body = doc.addObject("PartDesign::Body", name)
    body.Label = label
    part.addObject(body)
    return body


def _build_slab(doc, body, role, a_expr, b_expr, t_expr):
    """
    Build a centered slab (sketch on the given datum plane + Midplane pad) in a body.

    Returns the Pad feature.
    """
    sketch = doc.addObject("Sketcher::SketchObject", "{}_Profile".format(body.Name))
    body.addObject(sketch)
    plane = _datum_plane(body, role)
    if plane is not None:
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
    wi, hi = _add_centered_rect(sketch)
    sketch.setExpression("Constraints[{}]".format(wi), a_expr)
    sketch.setExpression("Constraints[{}]".format(hi), b_expr)
    doc.recompute()

    pad = doc.addObject("PartDesign::Pad", "{}_Pad".format(body.Name))
    pad.Profile = sketch
    body.addObject(pad)
    pad.Length = 10
    pad.SideType = "Symmetric"
    pad.setExpression("Length", t_expr)
    sketch.Visibility = False
    doc.recompute()
    return pad


def _cut_groove(doc, body, role, u0_expr, du_expr, v0_expr, dv_expr):
    """
    Cut a ThroughAll groove pocket into a wall body.

    The pocket sketch is placed on the same datum plane the wall was padded from, so the
    pocket runs the full length of the wall. (u, v) are the in-plane sketch axes.
    """
    sketch = doc.addObject("Sketcher::SketchObject", "{}_GrooveSk".format(body.Name))
    body.addObject(sketch)
    plane = _datum_plane(body, role)
    if plane is not None:
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
    u0_idx, v0_idx, du_idx, dv_idx = _add_positioned_rect(sketch)
    sketch.setExpression("Constraints[{}]".format(u0_idx), u0_expr)
    sketch.setExpression("Constraints[{}]".format(du_idx), du_expr)
    sketch.setExpression("Constraints[{}]".format(v0_idx), v0_expr)
    sketch.setExpression("Constraints[{}]".format(dv_idx), dv_expr)
    doc.recompute()

    pocket = doc.addObject("PartDesign::Pocket", "{}_Groove".format(body.Name))
    pocket.Profile = sketch
    body.addObject(pocket)
    pocket.Type = "ThroughAll"
    pocket.SideType = "Symmetric"
    sketch.Visibility = False
    doc.recompute()
    return pocket


def _set_placement(body, x_expr=None, y_expr=None, z_expr=None):
    """Set expression-driven Body.Placement.Base components."""
    if x_expr is not None:
        body.setExpression("Placement.Base.x", x_expr)
    if y_expr is not None:
        body.setExpression("Placement.Base.y", y_expr)
    if z_expr is not None:
        body.setExpression("Placement.Base.z", z_expr)


# =============================================================================
# DRAWER CREATION
# =============================================================================


def create_drawer(name, values, container=None, placement=None, internal_name=None):
    """
    Create a parametric drawer (App::Part with panel bodies) in the active document.

    Args:
        name: label for the drawer Part (and base for the body labels).
        values: dict of expression strings for the length parameters plus the
                "overlap_box" and "has_front" booleans (see create_parameter_holder).
        container: App::Part to add the drawer to; default is the active container.
        placement: Placement for the drawer Part; default is the 180 deg Z rotation.
        internal_name: internal object name to request (used when recreating a drawer
                so that references by name, e.g. CAM Jobs, stay valid).

    Returns:
        The created App::Part, or None on failure.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintError("Lumberjack: No active document.\n")
        return None

    # --- Drawer Part, placed inside the (active) container --------------------
    part = doc.addObject("App::Part", internal_name or name)
    part.Label = name
    if container is not None:
        container.addObject(part)
    else:
        _add_part_to_active_container(part)

    # Rotate the whole drawer 180 deg about Z so the front faces the FreeCAD front
    # (-Y) view. The rotation is about the Part origin, so the bottom stays centered
    # in X/Y and its bottom face stays on z = 0.
    if placement is None:
        placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 180
        )
    part.Placement = placement

    # Use the Part's actual (unique) internal name as the base for child names so
    # multiple drawers with the same requested name don't collide. Labels follow the
    # Part's label so the cutlist shows recognizable, drawer-specific names.
    base = part.Name
    lbl = part.Label

    holder = create_parameter_holder(doc, part, base, lbl, values)
    hn = holder.Name

    def H(prop):
        return "{}.{}".format(hn, prop)

    has_front = bool(values.get("has_front", False))

    # --- Derived dimension expressions ---------------------------------------
    # Box corner joinery orientation:
    #   - Without a dedicated front, keep the front/back panels full-width so the drawer
    #     shows a clean, uniform front face; the sides lap into the front/back.
    #   - With a dedicated front, rotate the joinery 90 deg about Z: the sides run the
    #     full depth and the front/back lap into them. This puts the corner glue joints
    #     in shear when the drawer front is pulled, giving a stronger bond against the
    #     drawer being pulled out. The less tidy front-edge grain is hidden behind the
    #     drawer front.
    # overlap_box stays live-editable via the ternary: when set, all panels fully overlap
    # (box-joint dimensioning); otherwise a half-lap (t_side inset) is applied.
    if has_front:
        side_len = H("depth")
        fb_len = "{ov} == 1 ? {w} : {w} - {ts}".format(
            ov=H("overlap_box"), w=H("width"), ts=H("t_side")
        )
    else:
        side_len = "{ov} == 1 ? {d} : {d} - {ts}".format(
            ov=H("overlap_box"), d=H("depth"), ts=H("t_side")
        )
        fb_len = H("width")
    height = H("height")
    t_side = H("t_side")
    t_bottom = H("t_bottom")
    bottom_x = "{w} - {ts}".format(w=H("width"), ts=H("t_side"))
    bottom_y = "{d} - {ts}".format(d=H("depth"), ts=H("t_side"))
    cavity_x = "{w} - 2 * {ts}".format(w=H("width"), ts=H("t_side"))
    cavity_y = "{d} - 2 * {ts}".format(d=H("depth"), ts=H("t_side"))
    groove_depth = "{ts} / 2".format(ts=H("t_side"))
    # Bottom joint, live-editable via the ternaries:
    #   - t_bottom < t_side ("inserted" bottom): the bottom keeps its full thickness and
    #     sits in a groove t_bottom wide that starts t_bottom above the box bottom. No
    #     rabbet on the bottom, so no need for a bit narrower than t_bottom / 2, and a
    #     stronger joint.
    #   - otherwise ("captured" bottom): groove t_bottom / 2 wide starting t_bottom / 2
    #     above the box bottom, the bottom is rabbeted to a t_bottom / 2 tongue.
    inserted = "{tb} < {ts}".format(tb=H("t_bottom"), ts=H("t_side"))
    groove_dv = "{ins} ? {tb} : {tb} / 2".format(ins=inserted, tb=H("t_bottom"))
    # Groove Z band in wall-local v (wall is centered in Z then placed at height/2).
    groove_v0 = "({ins} ? {tb} : {tb} / 2) + {off} - {h} / 2".format(
        ins=inserted, tb=H("t_bottom"), off=H("bottom_v_offset"), h=H("height")
    )

    half_w = "{w} / 2 - {ts} / 2".format(w=H("width"), ts=H("t_side"))
    half_d = "{d} / 2 - {ts} / 2".format(d=H("depth"), ts=H("t_side"))

    # --- Left side wall (inner face +X) --------------------------------------
    side_l = _create_body(doc, part, "{}_SideL".format(base), "{}_SideL".format(lbl))
    _build_slab(doc, side_l, "XZ_Plane", t_side, height, side_len)
    _cut_groove(
        doc, side_l, "XZ_Plane",
        u0_expr="0", du_expr=groove_depth, v0_expr=groove_v0, dv_expr=groove_dv,
    )
    _set_placement(side_l, x_expr="-({})".format(half_w), z_expr="{} / 2".format(height))

    # --- Right side wall (inner face -X) -------------------------------------
    side_r = _create_body(doc, part, "{}_SideR".format(base), "{}_SideR".format(lbl))
    _build_slab(doc, side_r, "XZ_Plane", t_side, height, side_len)
    _cut_groove(
        doc, side_r, "XZ_Plane",
        u0_expr="-({})".format(groove_depth), du_expr=groove_depth,
        v0_expr=groove_v0, dv_expr=groove_dv,
    )
    _set_placement(side_r, x_expr=half_w, z_expr="{} / 2".format(height))

    # --- Back wall (inner face +Y) -------------------------------------------
    back = _create_body(doc, part, "{}_Back".format(base), "{}_Back".format(lbl))
    _build_slab(doc, back, "YZ_Plane", t_side, height, fb_len)
    _cut_groove(
        doc, back, "YZ_Plane",
        u0_expr="0", du_expr=groove_depth, v0_expr=groove_v0, dv_expr=groove_dv,
    )
    _set_placement(back, y_expr="-({})".format(half_d), z_expr="{} / 2".format(height))

    # --- Front wall (inner face -Y) ------------------------------------------
    front = _create_body(doc, part, "{}_Front".format(base), "{}_Front".format(lbl))
    _build_slab(doc, front, "YZ_Plane", t_side, height, fb_len)
    _cut_groove(
        doc, front, "YZ_Plane",
        u0_expr="-({})".format(groove_depth), du_expr=groove_depth,
        v0_expr=groove_v0, dv_expr=groove_dv,
    )
    _set_placement(front, y_expr=half_d, z_expr="{} / 2".format(height))

    # --- Bottom panel (rabbeted, sits in the wall grooves) -------------------
    bottom = _create_body(doc, part, "{}_Bottom".format(base), "{}_Bottom".format(lbl))
    _build_slab(doc, bottom, "XY_Plane", bottom_x, bottom_y, t_bottom)
    _rabbet_bottom(
        doc, bottom, bottom_x, bottom_y, cavity_x, cavity_y, t_bottom,
        suppress_expr="{ins} ? 1 : 0".format(ins=inserted),
    )
    # Captured: bottom face on z = offset. Inserted: raised by t_bottom (groove start).
    _set_placement(
        bottom,
        z_expr="{off} + {tb} / 2 + ({ins} ? {tb} : 0 mm)".format(
            off=H("bottom_v_offset"), tb=H("t_bottom"), ins=inserted
        ),
    )

    # --- Optional drawer front -----------------------------------------------
    if has_front:
        dfront = _create_body(doc, part, "{}_DrawerFront".format(base), "{}_DrawerFront".format(lbl))
        _build_slab(
            doc, dfront, "XZ_Plane", H("width_front"), H("height_front"), H("t_front")
        )
        _set_placement(
            dfront,
            y_expr="{d} / 2 + {tf} / 2".format(d=H("depth"), tf=H("t_front")),
            z_expr="-{off} + {hf} / 2".format(
                off=H("front_v_offset"), hf=H("height_front")
            ),
        )

    doc.recompute()

    FreeCAD.Console.PrintMessage(
        "Lumberjack: Created drawer '{}' ({} bodies).\n".format(
            name, len(part.Group) - 1
        )
    )
    return part


def _rabbet_bottom(
    doc, body, bottom_x, bottom_y, cavity_x, cavity_y, t_bottom, suppress_expr=None
):
    """
    Cut a perimeter rabbet into the bottom so its tongue seats in the wall grooves.

    Removes the lower half (t_bottom/2) of the perimeter frame between the cavity
    rectangle and the outer (tongue) rectangle. If suppress_expr is given it drives the
    pocket's Suppressed property (1 = no rabbet, used for the inserted bottom).
    """
    sketch = doc.addObject("Sketcher::SketchObject", "{}_RabbetSk".format(body.Name))
    body.addObject(sketch)
    plane = _datum_plane(body, "XY_Plane")
    if plane is not None:
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
    # Outer rectangle (tongue extent) then inner rectangle (cavity); the frame between
    # them is the rabbet region.
    ow, oh = _add_centered_rect(sketch, 30.0, 20.0)
    iw, ih = _add_centered_rect(sketch, 20.0, 10.0)
    sketch.setExpression("Constraints[{}]".format(ow), bottom_x)
    sketch.setExpression("Constraints[{}]".format(oh), bottom_y)
    sketch.setExpression("Constraints[{}]".format(iw), cavity_x)
    sketch.setExpression("Constraints[{}]".format(ih), cavity_y)
    doc.recompute()

    pocket = doc.addObject("PartDesign::Pocket", "{}_Rabbet".format(body.Name))
    pocket.Profile = sketch
    body.addObject(pocket)
    pocket.Length = 10
    pocket.setExpression("Length", "{} / 2".format(t_bottom))
    if suppress_expr:
        pocket.setExpression("Suppressed", suppress_expr)
    sketch.Visibility = False
    doc.recompute()
    return pocket


# =============================================================================
# RECREATION
# =============================================================================


def _parent_container(part):
    """The App::Part (or other group) that directly contains part, or None."""
    for parent in part.InList:
        group = getattr(parent, "Group", None)
        if group is not None and hasattr(parent, "addObject") and part in group:
            if parent.TypeId not in ("App::Origin",):
                return parent
    return None


def delete_drawer(part):
    """Remove a drawer Part together with its holder, bodies and their features."""
    doc = part.Document
    names = []
    for child in list(part.Group):
        if child.TypeId == "PartDesign::Body":
            names.extend(f.Name for f in child.Group)
        names.append(child.Name)
    names.append(part.Name)
    for name in names:
        if doc.getObject(name) is not None:
            doc.removeObject(name)
    doc.recompute()


def recreate_drawer(part, name=None, values=None):
    """
    Rebuild an existing drawer with the current code.

    Keeps the internal name, label (unless name is given), container and placement.
    values defaults to the drawer's current parameters (expressions preserved).

    Returns the new App::Part, or None on failure.
    """
    holder = drawer_holder(part)
    if holder is None:
        FreeCAD.Console.PrintError(
            "Lumberjack: '{}' is not a Lumberjack drawer.\n".format(part.Label)
        )
        return None
    if values is None:
        values = read_drawer_values(holder)
    label = name or part.Label
    internal_name = part.Name
    container = _parent_container(part)
    placement = FreeCAD.Placement(part.Placement)
    doc = part.Document

    had_job = False
    try:
        import cam

        had_job = cam.find_existing_job(doc, part) is not None
    except Exception:
        pass

    delete_drawer(part)
    new_part = create_drawer(
        label, values, container=container, placement=placement, internal_name=internal_name
    )
    if new_part is None:
        return None
    if new_part.Name != internal_name:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: recreated drawer got the new internal name '{}' (was '{}').\n".format(
                new_part.Name, internal_name
            )
        )
    if had_job:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: drawer '{}' has a CAM Job; run 'Drawer CAM Job' again to rebuild "
            "its models and operations.\n".format(label)
        )
    FreeCAD.Console.PrintMessage("Lumberjack: Recreated drawer '{}'.\n".format(label))
    return new_part


# =============================================================================
# CONTAINER UTILITIES
# =============================================================================


def _add_part_to_active_container(part):
    """Add the drawer Part to the currently active App::Part container, if any."""
    if not hasattr(FreeCADGui, "ActiveDocument") or FreeCADGui.ActiveDocument is None:
        return
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        if view is not None and hasattr(view, "getActiveObject"):
            container = view.getActiveObject("part")
            if container is not None and container is not part:
                container.addObject(part)
                FreeCAD.Console.PrintMessage(
                    "Lumberjack: Added drawer '{}' to container '{}'\n".format(
                        part.Label, container.Label
                    )
                )
    except Exception as e:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: Could not add drawer to active container: {}\n".format(e)
        )


# =============================================================================
# CREATE DRAWER DIALOG
# =============================================================================


class DrawerTemplate:
    """
    Temporary FeaturePython object used to bind the dialog's Gui::QuantitySpinBox
    widgets via ExpressionBinding. After the dialog is accepted the expressions are
    read back from this object and applied to the parameter holder.
    """

    name = "DrawerTemplate"

    def __init__(self, obj):
        obj.Proxy = self
        for prop in _HOLDER_LENGTH_PROPS:
            if prop not in obj.PropertiesList:
                obj.addProperty("App::PropertyLength", prop)


class CreateDrawerDialog(QtWidgets.QDialog):
    """
    Dialog for creating a parametric drawer.

    With existing=(part, holder) the dialog is seeded from that drawer and the accept
    button recreates it (see recreate_drawer) instead of creating a new one.
    """

    def __init__(self, parent=None, existing=None):
        super(CreateDrawerDialog, self).__init__(parent)
        self.existing = existing
        self.existing_values = (
            read_drawer_values(existing[1]) if existing is not None else None
        )
        self.setWindowTitle("Recreate Drawer" if existing else "Create Drawer")
        self.setMinimumWidth(420)
        self.template = None
        self.spin = {}  # holder-prop-name -> spinbox widget
        self.front_rows = []  # (label, widget) tuples to enable/disable
        self._setup_template()
        self._setup_ui()

    # -- template ----------------------------------------------------------
    def _setup_template(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return
        if doc.getObject(DrawerTemplate.name):
            doc.removeObject(DrawerTemplate.name)
        obj = doc.addObject("App::FeaturePython", DrawerTemplate.name)
        DrawerTemplate(obj)
        obj.ViewObject.Proxy = 0
        self.template = obj

        # Seed each length property from the drawer being recreated, else from the
        # remembered preference (or default).
        for key, _label, default in BOX_FIELDS + FRONT_FIELDS:
            prop = _KEY_TO_PROP[key]
            if self.existing_values is not None:
                expr = self.existing_values[prop]
            else:
                expr = _get_last_str(key, default)
            try:
                self.template.setExpression(prop, expr)
            except Exception:
                pass
        doc.recompute()

    def _cleanup_template(self):
        doc = FreeCAD.ActiveDocument
        if doc and self.template:
            try:
                doc.removeObject(self.template.Name)
            except Exception:
                pass
        self.template = None

    # -- ui ----------------------------------------------------------------
    def _make_spinbox(self, prop):
        widget = FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")
        widget.setProperty("unit", "mm")
        try:
            widget.setProperty("rawValue", getattr(self.template, prop).Value)
        except Exception:
            pass
        FreeCADGui.ExpressionBinding(widget).bind(self.template, prop)
        self.spin[prop] = widget
        return widget

    def _add_field_row(self, layout, label_text, prop):
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text + ":")
        label.setMinimumWidth(110)
        widget = self._make_spinbox(prop)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)
        return label, widget

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Name
        name_row = QtWidgets.QHBoxLayout()
        name_label = QtWidgets.QLabel("Name:")
        name_label.setMinimumWidth(110)
        self.name_edit = QtWidgets.QLineEdit()
        if self.existing is not None:
            self.name_edit.setText(self.existing[0].Label)
        else:
            self.name_edit.setText(_get_last_str("drawer_name", "Drawer"))
        self.name_edit.selectAll()
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)

        layout.addSpacing(8)
        if self.existing is not None:
            info = QtWidgets.QLabel(
                "Recreating '{}': the Part and its bodies are deleted and rebuilt with "
                "the current code, keeping name, container and placement. Objects that "
                "reference the old bodies (e.g. a CAM Job) must be regenerated "
                "afterwards.".format(self.existing[0].Label)
            )
        else:
            info = QtWidgets.QLabel(
                "Enter values or expressions (e.g. p.width). Sizes are in mm."
            )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(4)

        if not self.template:
            err = QtWidgets.QLabel(
                "Error: could not create template object. Open a document first."
            )
            err.setStyleSheet("color: red;")
            layout.addWidget(err)
        else:
            box_group = QtWidgets.QGroupBox("Box")
            box_layout = QtWidgets.QVBoxLayout(box_group)
            for key, label_text, _default in BOX_FIELDS:
                self._add_field_row(box_layout, label_text, _KEY_TO_PROP[key])
            layout.addWidget(box_group)

            # overlap_box checkbox
            self.overlap_check = QtWidgets.QCheckBox(
                "Box joints (overlapping panels) instead of half-lap dados"
            )
            if self.existing_values is not None:
                self.overlap_check.setChecked(self.existing_values["overlap_box"])
            else:
                self.overlap_check.setChecked(_get_last_bool("drawer_overlap_box", False))
            layout.addWidget(self.overlap_check)

            # has_front checkbox
            self.front_check = QtWidgets.QCheckBox("Add a dedicated drawer front")
            if self.existing_values is not None:
                self.front_check.setChecked(self.existing_values["has_front"])
            else:
                self.front_check.setChecked(_get_last_bool("drawer_has_front", False))
            layout.addWidget(self.front_check)

            self.front_group = QtWidgets.QGroupBox("Drawer front")
            front_layout = QtWidgets.QVBoxLayout(self.front_group)
            for key, label_text, _default in FRONT_FIELDS:
                self._add_field_row(front_layout, label_text, _KEY_TO_PROP[key])
            layout.addWidget(self.front_group)

            self.front_check.toggled.connect(self.front_group.setEnabled)
            self.front_group.setEnabled(self.front_check.isChecked())

        layout.addSpacing(12)
        button_row = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton(
            "Recreate" if self.existing is not None else "Create"
        )
        self.create_button.setDefault(True)
        self.create_button.setEnabled(self.template is not None)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        button_row.addStretch()
        button_row.addWidget(self.create_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.create_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.name_edit.setFocus()

    # -- value extraction --------------------------------------------------
    def _expr_for(self, prop):
        if not self.template:
            return None
        try:
            for p, expr in self.template.ExpressionEngine:
                if p == prop:
                    return expr
        except Exception:
            pass
        return None

    def get_values(self):
        if not self.template:
            return None
        values = {}
        for key, _label, _default in BOX_FIELDS + FRONT_FIELDS:
            prop = _KEY_TO_PROP[key]
            expr = self._expr_for(prop)
            if not expr:
                try:
                    expr = "{} mm".format(getattr(self.template, prop).Value)
                except Exception:
                    expr = _default
            values[prop] = expr
        values["overlap_box"] = self.overlap_check.isChecked()
        values["has_front"] = self.front_check.isChecked()
        values["name"] = self.name_edit.text().strip()
        return values

    def reject(self):
        self._cleanup_template()
        super(CreateDrawerDialog, self).reject()


def show_create_drawer_dialog():
    """
    Show the Create Drawer dialog and create the drawer if confirmed.

    If exactly one existing drawer is selected, the dialog is seeded from it and the
    drawer is recreated (same name, container and placement) instead.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintError(
            "Lumberjack: No active document. Create or open a document first.\n"
        )
        return None

    existing = None
    try:
        drawers, rejected = selected_drawers()
        if len(drawers) == 1 and not rejected:
            existing = drawers[0]
    except Exception as e:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: could not inspect the selection: {}\n".format(e)
        )

    dialog = CreateDrawerDialog(FreeCADGui.getMainWindow(), existing=existing)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None

    values = dialog.get_values()
    if values is None:
        dialog._cleanup_template()
        return None

    name = values.pop("name")
    if not name:
        FreeCAD.Console.PrintError("Lumberjack: Drawer name cannot be empty.\n")
        dialog._cleanup_template()
        return None

    # Remove the dialog's binding template before validating/creating so it does not
    # linger in the document.
    dialog._cleanup_template()

    ok, problem = _validate_values(values)
    if not ok:
        FreeCAD.Console.PrintError("Lumberjack: {}\n".format(problem))
        return None

    if existing is not None:
        # Recreating does not touch the remembered "last used" values.
        return recreate_drawer(existing[0], name=name, values=values)

    # Remember all fields for next time (only once the values are known good).
    _set_last_str("drawer_name", name)
    for key, _label, _default in BOX_FIELDS + FRONT_FIELDS:
        _set_last_str(key, values[_KEY_TO_PROP[key]])
    _set_last_bool("drawer_overlap_box", values["overlap_box"])
    _set_last_bool("drawer_has_front", values["has_front"])

    return create_drawer(name, values)


def _validate_values(values):
    """
    Best-effort validation of evaluated dimensions at creation time.

    Returns (ok, message). Only catches gross errors; expression-driven edits made
    later cannot be fully validated here.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return True, ""
    # Evaluate the length expressions via a scratch object.
    probe = doc.addObject("App::FeaturePython", "DrawerValidate")
    probe_name = probe.Name
    try:
        for prop in _HOLDER_LENGTH_PROPS:
            probe.addProperty("App::PropertyLength", prop)
            if values.get(prop):
                try:
                    probe.setExpression(prop, "({})".format(values[prop]))
                except Exception:
                    pass
        doc.recompute()
        w = probe.width.Value
        d = probe.depth.Value
        h = probe.height.Value
        ts = probe.t_side.Value
        tb = probe.t_bottom.Value
        off = probe.bottom_v_offset.Value
        # Inserted bottom (tb < ts): groove top is at offset + 2 * tb; captured: offset + tb.
        groove_top = off + (2 * tb if tb < ts else tb)
        checks = [
            (ts > 0, "side thickness must be > 0"),
            (tb > 0, "bottom thickness must be > 0"),
            (w > 2 * ts, "width must be greater than 2 x side thickness"),
            (d > 2 * ts, "depth must be greater than 2 x side thickness"),
            (h > groove_top, "height must be greater than the top of the bottom groove"),
        ]
        for ok, msg in checks:
            if not ok:
                return False, msg
        return True, ""
    finally:
        try:
            doc.removeObject(probe_name)
        except Exception:
            pass
