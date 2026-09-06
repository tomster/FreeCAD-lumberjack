# -*- coding: utf-8 -*-
"""
Headless end-to-end test for cam.py / nesting.py.

Run:
    ~/Applications/FreeCAD.AppImage --console \
        --module-path ~/Projects/FreeCAD/Mod/Lumberjack \
        ~/Projects/FreeCAD/Mod/Lumberjack/test_cam.py

Creates drawers, nests them onto sheets, generates the CAM Jobs with a bit from the CAM
library, post-processes and checks the result, then recreates a drawer and re-runs.
"""

import os
import shutil
import sys
import traceback

import FreeCAD

OUT_DIR = "/tmp/lj_cam"
BIT_MAX_D = 4.0  # groove = t_bottom = 8 mm (inserted bottom) needs <= 8, rabbets 6 mm need <= 6


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    FreeCAD.Console.PrintMessage("  ok: {}\n".format(msg))


def pick_bit(cam):
    bits = [b for b in cam.list_toolbits() if b.shape.lower().startswith("endmill")]
    check(bits, "toolbit library has endmills")
    fitting = [b for b in bits if b.diameter <= BIT_MAX_D]
    check(fitting, "an endmill <= {} mm exists".format(BIT_MAX_D))
    return max(fitting, key=lambda b: b.diameter)


def min_z_in_gcode(path):
    zmin = None
    with open(path) as f:
        for line in f:
            for tok in line.replace(",", " ").split():
                if tok.startswith("Z"):
                    try:
                        z = float(tok[1:])
                    except ValueError:
                        continue
                    zmin = z if zmin is None else min(zmin, z)
    return zmin


def xy_range_in_gcode(path):
    xs, ys = [], []
    with open(path) as f:
        for line in f:
            if line.startswith("(") or line.startswith("%"):
                continue
            for tok in line.split():
                try:
                    if tok.startswith("X"):
                        xs.append(float(tok[1:]))
                    elif tok.startswith("Y"):
                        ys.append(float(tok[1:]))
                except ValueError:
                    pass
    return (min(xs), max(xs), min(ys), max(ys)) if xs and ys else None


DRAWER_A = {
    "width": "400 mm", "height": "120 mm", "depth": "500 mm",
    "t_side": "12 mm", "t_bottom": "8 mm", "bottom_v_offset": "0 mm",
    "width_front": "440 mm", "height_front": "160 mm", "t_front": "18 mm",
    "front_v_offset": "20 mm", "corner_joint": 0, "has_front": True,
    "handle_slot": True, "handle_diameter": "32 mm", "handle_width": "100 mm",
    "handle_v_offset": "20 mm",
}
DRAWER_C = {  # captured bottom (t_bottom == t_side), no drawer front
    "width": "300 mm", "height": "100 mm", "depth": "400 mm",
    "t_side": "12 mm", "t_bottom": "12 mm", "bottom_v_offset": "0 mm",
    "width_front": "340 mm", "height_front": "140 mm", "t_front": "18 mm",
    "front_v_offset": "20 mm", "corner_joint": 0, "has_front": False,
}


import math


def test_geometry(cam, nesting):
    r = cam.Region("x", 0, 100, 0, 3, 1, "u")
    check(len(cam.slot_passes(r, 3.0)) == 1, "w == d gives one pass")
    check(len(cam.slot_passes(r, 1.5)) == 3, "w == 2d gives 3 passes (50% step-over)")
    try:
        cam.slot_passes(r, 3.5)
        raise AssertionError("ToolTooWide not raised")
    except cam.ToolTooWide:
        FreeCAD.Console.PrintMessage("  ok: ToolTooWide raised\n")
    (p1, p2), = cam.slot_passes(r, 3.0)
    check(p1[0] < 0 < 100 < p2[0], "open region: passes overshoot both ends")
    rc = cam.Region("x", 0, 100, 0, 3, 1, "u", closed=True)
    (p1, p2), = cam.slot_passes(rc, 3.0)
    check(abs(p1[0] - 1.5) < 1e-9 and abs(p2[0] - 98.5) < 1e-9, "closed region: passes stop a tool radius inside")
    try:
        cam.slot_passes(cam.Region("x", 0, 2, 0, 3, 1, "u", closed=True), 3.0)
        raise AssertionError("ToolTooWide not raised for a short stopped pocket")
    except cam.ToolTooWide:
        FreeCAD.Console.PrintMessage("  ok: short stopped pocket rejected\n")
    # stadium 100 x 32 with a 4 mm bit: passes follow the semicircles
    import math
    st = cam.Region("h", -50, 50, 8, 40, 12.2, "u", shape="slot")
    check(st.closed, "slot regions are closed")
    ps = cam.slot_passes(st, 4.0)
    check(len(ps) >= 15, "stadium needs many passes ({})".format(len(ps)))
    for (u0, v), (u1, _v) in ps:
        reach = math.sqrt(max((16 - 2) ** 2 - (v - 24) ** 2, 0))
        check(abs(max(u0, u1) - (50 - 16 + reach)) < 1e-9 and abs(min(u0, u1) + (50 - 16 + reach)) < 1e-9,
              "pass at v={:.2f} ends on the inset arc".format(v))
    vs = sorted(v for (_u0, v), _ in ps)
    check(abs(vs[0] - 10) < 1e-9 and abs(vs[-1] - 38) < 1e-9, "outer passes a tool radius inside the slot")
    check(abs(sorted(abs(u1 - u0) for (u0, _), (u1, _) in ps)[0] - 68) < 1e-9, "outermost pass covers the straight part only")

    # nesting: the standard drawer's 12 mm panels on a 630 x 1080 sheet with a 6 mm bit
    items = [nesting.Item(k, l, w, 12) for k, l, w in
             (("SideL", 500, 120), ("SideR", 500, 120), ("Front", 388, 120), ("Back", 388, 120))]
    sheets = nesting.nest(items, 630, 1080, 6.0)
    check(len(sheets) == 1, "four walls fit one sheet")
    sh = sheets[0]
    by = {p.item.key: p for p in sh.items}
    check(all(p.rotated for p in sh.items), "walls stand vertically (long side along the sheet height)")
    check(by["SideL"].u0 == 0 and by["SideL"].v0 == 0, "first panel hugs the top-left corner")
    check(abs(by["SideR"].v0 - (500 + 6)) < 1e-9, "stacked panels are one tool diameter apart")
    check(abs(by["Front"].u0 - (120 + 6)) < 1e-9, "second column is one tool diameter to the right")
    check(sh.used_w <= 630 and sh.used_h <= 1080, "layout within the sheet")
    vlines = [l for l in sh.lines if l.axis == "v"]
    hlines = [l for l in sh.lines if l.axis == "h"]
    check(len(vlines) == 2, "two vertical cuts (shared column line + right edge)")
    check(abs(vlines[0].pos - 123) < 1e-9 and len(vlines[0].edges) == 4, "shared column cut serves 4 edges")
    check(all(l.pos > 0 for l in hlines), "no cut along the top edge")
    check(all(l.pos > 0 for l in vlines), "no cut along the left edge")
    check(all(l.tabs for l in sh.lines), "every cut has tabs")
    check(sh.top_edge_cuts() == [123.0, 249.0], "top-edge cut positions reported")
    try:
        nesting.nest([nesting.Item("big", 1200, 700, 12)], 630, 1080, 6.0)
        raise AssertionError("DoesNotFit not raised")
    except nesting.DoesNotFit:
        FreeCAD.Console.PrintMessage("  ok: DoesNotFit raised\n")
    many = [nesting.Item("p%d" % i, 1000, 200, 12) for i in range(4)]
    check(len(nesting.nest(many, 630, 1080, 6.0)) == 2, "overflow opens a second sheet")
    sheets = nesting.nest([nesting.Item("long", 900, 200, 12)], 630, 1080, 6.0)
    check(sheets[0].items[0].rotated, "panel longer than the sheet width is rotated")


def check_panels(cam, drawers, part, holder, interference=True):
    """Panel solids match the frames cam.py derives, and the box panels do not overlap."""
    import Part

    params = cam.DrawerParams(holder)
    bodies = {}
    for role, body in drawers.drawer_panels(part):
        bodies[role] = body
        frame = cam.panel_frame(role, params)
        bb = body.Shape.BoundBox
        got = sorted([bb.XLength, bb.YLength, bb.ZLength])
        want = sorted([frame.L, frame.W, frame.t])
        check(all(abs(a - b) < 1e-6 for a, b in zip(got, want)),
              "{} {}: solid {} matches the CAM frame {}".format(part.Label, role, got, want))
    box = [r for r in ("SideL", "SideR", "Front", "Back", "Bottom") if r in bodies and interference]
    for i, ra in enumerate(box):
        for rb in box[i + 1:]:
            v = bodies[ra].Shape.common(bodies[rb].Shape).Volume
            check(v < 1e-6, "{}: {} and {} do not interpenetrate ({:.3f} mm3)".format(
                part.Label, ra, rb, v))


def main():
    import cam
    import drawers
    import nesting

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)
    doc = FreeCAD.newDocument("LjCamTest")
    doc.saveAs(os.path.join(OUT_DIR, "test.FCStd"))

    test_geometry(cam, nesting)

    part = drawers.create_drawer("Drawer", DRAWER_A)
    holder = cam.drawer_holder(part)
    check(holder is not None, "drawer created")
    check(cam.find_drawer_part(part.Group[1]) == (part, holder), "body resolves to drawer")

    # --- drawer model: inserted bottom (8 < 12) ------------------------------------
    bodies = {b.Name.rsplit("_", 1)[-1]: b for b in part.Group if b.TypeId == "PartDesign::Body"}
    bot = bodies["Bottom"]
    check(abs(bot.Shape.Volume - 388.0 * 476.0 * 8.0) < 1e-3, "inserted bottom keeps its full thickness")
    check(abs(bot.Shape.BoundBox.ZMin - 8.0) < 1e-6, "inserted bottom sits 8 mm up")
    holder.setExpression("t_bottom", None)
    holder.t_bottom = "12 mm"
    doc.recompute()
    check(bot.Shape.Volume < 388.0 * 476.0 * 12.0 - 1.0, "captured bottom (12 == 12) gets the rabbet")
    holder.t_bottom = "8 mm"
    doc.recompute()
    check(abs(bot.Shape.Volume - 388.0 * 476.0 * 8.0) < 1e-3, "back to inserted after resetting")

    # --- handle slots in the sides ----------------------------------------------------
    import Part
    for role in ("SideL", "SideR"):
        side = bodies[role]
        sbb = side.Shape.BoundBox
        # through the thickness at the slot centre (z = 120 - 20 - 16), solid just above the slot
        probe = Part.makeBox(sbb.XLength, 2, 2, FreeCAD.Vector(sbb.XMin, -1, 83))
        check(side.Shape.common(probe).Volume < 1e-9, "{}: handle slot goes through".format(role))
        probe = Part.makeBox(sbb.XLength, 2, 2, FreeCAD.Vector(sbb.XMin, -1, 101))
        check(abs(side.Shape.common(probe).Volume - sbb.XLength * 4) < 1e-6, "{}: material above the slot (top edge at 100)".format(role))
        probe = Part.makeBox(sbb.XLength, 2, 2, FreeCAD.Vector(sbb.XMin, -1, 66))
        check(abs(side.Shape.common(probe).Volume - sbb.XLength * 4) < 1e-6, "{}: material below the slot (bottom edge at 68)".format(role))
        probe = Part.makeBox(sbb.XLength, 2, 2, FreeCAD.Vector(sbb.XMin, 50.5, 83))
        check(abs(side.Shape.common(probe).Volume - sbb.XLength * 4) < 1e-6, "{}: solid beyond the slot end at 50".format(role))
        probe = Part.makeBox(sbb.XLength, 2, 2, FreeCAD.Vector(sbb.XMin, 46, 83))
        check(side.Shape.common(probe).Volume < 1e-9, "{}: semicircle end reaches past 48".format(role))
    v_on = bodies["SideL"].Shape.Volume
    holder.handle_slot = False
    doc.recompute()
    slot_area = 68.0 * 32.0 + math.pi * 16.0 ** 2
    check(abs(bodies["SideL"].Shape.Volume - v_on - slot_area * 12.0) < 1e-3, "handle slot removes a 100 x 32 stadium x t_side")
    holder.handle_slot = True
    doc.recompute()
    check(abs(bodies["SideL"].Shape.Volume - v_on) < 1e-6, "handle slot back on")
    ok_v, msg_v = drawers._validate_values(dict(DRAWER_A, handle_width="600 mm"))
    check(not ok_v and "depth" in msg_v, "handle slot wider than the depth is rejected")
    ok_v, msg_v = drawers._validate_values(dict(DRAWER_A, handle_v_offset="80 mm"))
    check(not ok_v and "groove" in msg_v, "handle slot reaching the bottom groove is rejected")
    check(drawers._validate_values(DRAWER_A)[0], "default handle slot validates")

    bit = pick_bit(cam)
    d = bit.diameter
    FreeCAD.Console.PrintMessage("  using bit {} (d={})\n".format(bit.label, d))
    s = cam.CamSettings()
    s.bit_id, s.bit_label, s.tool_d, s.cutting_edge_height = bit.bit_id, bit.label, d, bit.edge_height
    s.sheet_w, s.sheet_h, s.clamp_h = 630.0, 1080.0, 20.0
    posts = cam.available_post_processors()
    s.post = "uccnc" if "uccnc" in posts else posts[0]
    s.spindle, s.feed_xy, s.feed_z, s.step_down = 16000.0, 360.0, 360.0, 3.0
    s.write_gcode = True

    # --- validation -----------------------------------------------------------------
    params = cam.DrawerParams(holder)
    problems, warnings = cam.validate_drawer(part, params, s)
    check(not problems, "no validation problems: {}".format(problems))
    bad = cam.CamSettings()
    bad.__dict__.update(s.__dict__)
    bad.tool_d = 9.0
    problems, _ = cam.validate_drawer(part, params, bad)
    check(any("Groove" in p for p in problems), "9 mm bit is rejected for an 8 mm groove")
    bad.tool_d = d
    bad.sheet_w, bad.sheet_h = 300.0, 300.0
    problems, _ = cam.validate_drawer(part, params, bad)
    check(problems, "small sheet is rejected")

    # --- second drawer, nested together ---------------------------------------------
    part_c = drawers.create_drawer("Captured", DRAWER_C)
    holder_c = cam.drawer_holder(part_c)

    # The solids in drawers.py and the dimensions cam.py re-derives must agree, and with
    # the corner joinery modelled the box panels must no longer interpenetrate.
    for dp, dh in ((part, holder), (part_c, holder_c)):
        check_panels(cam, drawers, dp, dh)
    # The other two corner joints are live switches on the same bodies.
    bodies_c = {r: b for r, b in drawers.drawer_panels(part_c)}
    holder_c.corner_joint = "Half-lap"
    doc.recompute()
    check(cam.DrawerParams(holder_c).corner_joint == drawers.JOINT_HALF_LAP, "half-lap read back")
    check_panels(cam, drawers, part_c, holder_c)
    sbb = bodies_c["SideL"].Shape.BoundBox
    check(abs(bodies_c["SideL"].Shape.BoundBox.YLength - 400.0) < 1e-6 and not [
        r for r in cam.pocket_regions("SideL", cam.DrawerParams(holder_c), cam.panel_frame("SideL", cam.DrawerParams(holder_c))) if r.closed],
        "half-lap: side groove runs through (ends inside the rabbet)")
    fb = bodies_c["Front"].Shape.BoundBox
    sb = bodies_c["SideL"].Shape.BoundBox
    check(abs(fb.YMax - sb.YMax) < 1e-6 and abs(fb.XLength - 288.0) < 1e-6, "half-lap: front flush with the side ends, t_side shorter")
    check(abs(bodies_c["Bottom"].Shape.BoundBox.YLength - 388.0) < 1e-6, "half-lap: bottom is depth - t_side long")
    holder_c.corner_joint = "Overlap"
    doc.recompute()
    check_panels(cam, drawers, part_c, holder_c, interference=False)  # overlapping stock by design
    check(abs(bodies_c["Front"].Shape.BoundBox.XLength - 300.0) < 1e-6, "overlap: front runs the full width")
    check(not [f for f in bodies_c["SideL"].Group if f.Name.endswith("_CornerFront") and not f.Suppressed], "overlap: corner pockets suppressed")
    holder_c.corner_joint = "Tongue and dado (flush)"
    doc.recompute()
    check_panels(cam, drawers, part_c, holder_c)
    # Stopped side groove: the lip (last 6 mm of depth) is solid over the groove band.
    import Part
    sbb = bodies_c["SideL"].Shape.BoundBox
    lip = Part.makeBox(6, 6, 100, FreeCAD.Vector(sbb.XMax - 6, sbb.YMax - 6, 0))
    check(abs(bodies_c["SideL"].Shape.common(lip).Volume - 6 * 6 * 100) < 1e-6, "flush T&D: side groove stopped, lip is solid")
    mid = Part.makeBox(6, 6, 100, FreeCAD.Vector(sbb.XMax - 6, -3, 0))
    check(bodies_c["SideL"].Shape.common(mid).Volume < 6 * 6 * 100 - 1.0, "flush T&D: groove present mid-panel")
    fb = bodies_c["Front"].Shape.BoundBox
    check(abs(fb.YMax - sb.YMax) < 1e-6 and abs(fb.XLength - 288.0) < 1e-6, "flush T&D: front flush with the side ends, t_side shorter")
    check(abs(bodies_c["Bottom"].Shape.BoundBox.YLength - 388.0) < 1e-6, "flush T&D: bottom is depth - t_side long")
    # The lap is on the outer face: the outer end corner is void, the inner one (tongue) solid.
    outer = Part.makeBox(6, 6, 100, FreeCAD.Vector(fb.XMax - 6, fb.YMax - 6, 0))
    inner = Part.makeBox(6, 6, 100, FreeCAD.Vector(fb.XMax - 6, fb.YMin, 0))
    front_shape = bodies_c["Front"].Shape
    check(front_shape.common(outer).Volume < 1e-6 and front_shape.common(inner).Volume > 100.0, "flush T&D: lap on the outer face, tongue on the inner half")
    holder_c.corner_joint = "Tongue and dado (recessed)"
    doc.recompute()
    check_panels(cam, drawers, part_c, holder_c)
    front_shape = bodies_c["Front"].Shape
    fb = front_shape.BoundBox
    outer = Part.makeBox(6, 6, 100, FreeCAD.Vector(fb.XMax - 6, fb.YMax - 6, 0))
    inner = Part.makeBox(6, 6, 100, FreeCAD.Vector(fb.XMax - 6, fb.YMin, 0))
    check(front_shape.common(inner).Volume < 1e-6 and front_shape.common(outer).Volume > 100.0, "recessed T&D: lap on the inner face, tongue on the outer half")

    # Legacy holders (pre corner_joint) only carry the overlap_box boolean.
    legacy = doc.addObject("App::Part", "Legacy")
    lh = doc.addObject("App::FeaturePython", "Legacy_Params")
    legacy.addObject(lh)
    for prop in ("width", "height", "depth", "t_side", "t_bottom", "bottom_v_offset",
                 "width_front", "height_front", "t_front", "front_v_offset"):
        lh.addProperty("App::PropertyLength", prop)
        setattr(lh, prop, DRAWER_C[prop])
    lh.addProperty("App::PropertyBool", "overlap_box")
    lh.addProperty("App::PropertyBool", "has_front")
    lh.overlap_box = True
    doc.recompute()
    check(drawers.drawer_holder(legacy) == lh, "legacy holder detected")
    check(drawers.read_drawer_values(lh)["corner_joint"] == drawers.JOINT_OVERLAP, "legacy overlap_box=True reads as Overlap")
    check(cam.DrawerParams(lh).overlap_box and not cam.DrawerParams(lh).recessed, "DrawerParams reads the legacy holder")
    lv = drawers.read_drawer_values(lh)
    check(lv["handle_slot"] is False and lv["handle_diameter"] == "32 mm", "legacy holder: handle slot off, defaults for the missing lengths")
    check(not cam.DrawerParams(lh).handle_slot, "DrawerParams: legacy holder has no handle slot")
    lh.overlap_box = False
    check(drawers.read_drawer_values(lh)["corner_joint"] == drawers.JOINT_TONGUE_DADO, "legacy overlap_box=False reads as tongue and dado")
    drawers.delete_drawer(legacy)
    results, problems, warnings = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems, "run succeeded: {}".format(problems))
    by_t = {}
    for r in results:
        by_t.setdefault(r.thickness, []).append(r)
    check(sorted(by_t) == [8.0, 12.0], "drawer fronts skipped by default: {}".format(sorted(by_t)))
    check(not [c for r in results for c in r.job.Model.Group if c.Label.endswith("DrawerFront")], "no front on any sheet")
    s.skip_drawer_front = False
    results, problems, warnings = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems, "run with fronts ok")
    by_t = {}
    for r in results:
        by_t.setdefault(r.thickness, []).append(r)
    check(sorted(by_t) == [8.0, 12.0, 18.0], "with fronts: one thickness group per panel thickness: {}".format(sorted(by_t)))
    check(all(len(v) == 1 for v in by_t.values()), "each thickness fits one sheet")
    r12 = by_t[12.0][0]
    job = r12.job
    check(len(job.Model.Group) == 9, "12 mm sheet holds 4 + 5 panels ({})".format(len(job.Model.Group)))
    check(sorted(job.LumberjackDrawers) == sorted([part.Name, part_c.Name]), "job records both drawers")

    # --- container ------------------------------------------------------------------
    import naming
    check(naming.group_name(["Kitchen_Left_Top", "Kitchen_Left_Bottom", "Kitchen_Right_Top"]) == "Kitchen Left Bottom/Top, Right Top", "naming factors common tokens")
    check(naming.group_name(["Left_Drawer", "Right_Drawer"]) == "Left/Right Drawer", "naming factors the common suffix")
    check(naming.group_name(["Drawer001", "Drawer002", "Drawer003"]) == "Drawer 001-003", "naming compresses numeric runs")
    check(naming.group_name(["Drawer", "Drawer001"]) == "Drawer " + naming.TIMES + "2", "naming counts when a label is a prefix of another")
    containers = [o for o in doc.Objects if hasattr(o, cam.CAM_GROUP_PROP)]
    check(len(containers) == 1, "one CAM container ({})".format(len(containers)))
    container = containers[0]
    check(container.TypeId == "App::Part", "container is an App::Part")
    check(container.Label == "CAM Captured/Drawer", "container named after the drawers: {}".format(container.Label))
    check(sorted(container.LumberjackDrawers) == sorted([part.Name, part_c.Name]), "container records its drawers")
    check(all(r.frame in container.Group and r.frame.TypeId == "App::Part" for r in results), "every job has a sheet frame in the container")
    check(all(r.job in r.frame.Group for r in results), "all jobs live in their frames")
    check(all(r.container == container for r in results), "results reference the container")
    frame = r12.frame
    check(job.Model in frame.Group and all(c in frame.Group for c in job.Model.Group), "job resources moved into the frame")
    check(job.Stock in frame.Group and job.Tools.Group[0] in frame.Group, "stock and tool controller in the frame")
    check(cam.sheet_frame_of(job) == frame, "sheet_frame_of resolves the frame")
    check(abs(results[0].frame.Placement.Base.x) < 1e-9 and results[0].frame.Placement.Rotation.isIdentity(), "first sheet frame stays at the origin")
    for i, r in enumerate(results):
        check(abs(r.frame.Placement.Base.x - i * 630 * 1.1) < 1e-6 and abs(r.frame.Placement.Base.y) < 1e-9,
              "sheet {} displayed at x = {:.0f} (10 % gap)".format(i + 1, i * 693))
    check(abs(job.Stock.Placement.Base.x) < 1e-6 and abs(job.Stock.Shape.BoundBox.XMin) < 1e-6, "stock itself keeps machine coordinates")

    # --- TechDraw overview page --------------------------------------------------------
    page = r12.page
    check(page is not None and page.TypeId == "TechDraw::DrawPage" and page in frame.Group, "sheet frame holds a TechDraw page")
    check(page.Label == os.path.basename(job.PostProcessorOutputFile), "page titled after the gcode file: {}".format(page.Label))
    check(page.Template is not None and len(page.Views) == 3 and not any("Invalid" in o.State for o in [page, page.Template] + list(page.Views)), "page, template and views valid (no link-scope errors)")
    names = sorted(v.LumberjackView for v in page.Views)
    check(names == ["Legend", "Sheet", "Title"], "page has title, sheet and legend views: {}".format(names))
    sheet_view = cam.page_view(page, "Sheet")
    legend_view = cam.page_view(page, "Legend")
    for clone in job.Model.Group:
        body_label = clone.Objects[0].Label
        check(body_label in sheet_view.Symbol and body_label in legend_view.Symbol, "{} labelled inline and in the legend".format(body_label))
    check(legend_view.Symbol.count("<text") == 2 * len(job.Model.Group), "legend has one label and one dimension text per panel")
    check(sheet_view.Symbol.count('fill="#000"') == sum(len(l.tabs) for l in r12.sheet.lines), "every tab is drawn")
    check(abs(page.PageWidth - 210) < 1e-6 and abs(page.PageHeight - 297) < 1e-6, "blank A4 portrait page")
    check('rotate(90)' not in sheet_view.Symbol and 'rotate(90)' not in legend_view.Symbol, "portrait page: content not rotated")
    check(cam.page_view(page, "Title").Y > sheet_view.Y > legend_view.Y > 0, "title above the sheet above the legend")
    check(abs(sheet_view.X.Value - 105) < 1e-6, "sheet drawing centred horizontally")
    check("Lumberjack: blank A4 portrait" in open(page.Template.Template, encoding="utf-8").read(), "shipped blank template used ({})".format(page.Template.Template))
    check(all(0 < v.X < page.PageWidth and 0 < v.Y < page.PageHeight for v in page.Views), "all views on the page")
    check(all(r.page is not None and r.page in r.frame.Group for r in results), "every sheet job has its page")
    check(all(not any(o in container.Group for o in p.Group) for p in (part, part_c)), "drawer bodies stay in their drawers")
    check(frame.Label == "12mm sheet 1" and job.Label == "Job 12mm sheet 1", "sheet with all drawers is labelled plainly: {} / {}".format(frame.Label, job.Label))
    f18 = by_t[18.0][0].frame
    check(f18.Label == "18mm sheet 1 (Drawer)", "sheet with a subset names its drawers: {}".format(f18.Label))
    check(cam.find_lumberjack_jobs(doc, [part.Name]) and not [o for o in cam.find_lumberjack_jobs(doc, [part.Name]) if o == container], "container is not mistaken for a job")
    check(cam.find_cam_groups(doc, [part_c.Name]) == [container], "container found by drawer name")
    check(cam.cam_group_of(job) == container, "cam_group_of resolves the job's container")
    check([p.Name for p in drawers._job_drawer_parts(container)] == sorted([part.Name, part_c.Name]), "container resolves to its drawers")
    check(len(job.Tools.Group) == 1 and abs(float(job.Tools.Group[0].Tool.Diameter) - d) < 1e-6, "one tool controller")
    sb = job.Stock.Shape.BoundBox
    check(abs(sb.XMin) < 1e-6 and abs(sb.XMax - 630) < 1e-6 and abs(sb.YMax) < 1e-6 and abs(sb.YMin + 1080) < 1e-6
          and abs(sb.ZMax) < 1e-6 and abs(sb.ZMin + 12) < 1e-6, "stock is the whole sheet with the top-left corner at the origin")
    sheet = r12.sheet
    for placed in sheet.items:
        clone = [c for c in job.Model.Group if c.Objects and c.Objects[0].Name == placed.item.data.body.Name][0]
        bb = clone.Shape.BoundBox
        check(abs(bb.XMin - placed.u0) < 1e-6 and abs(bb.YMax + placed.v0) < 1e-6, "{} placed at its nested position".format(clone.Label))
        check(abs(bb.XLength - placed.du) < 1e-6 and abs(bb.YLength - placed.dv) < 1e-6, "{} orientation matches the nest".format(clone.Label))
        check(abs(bb.ZMax) < 1e-6 and abs(bb.ZMin + 12) < 1e-6, "{} top at Z=0".format(clone.Label))
        check(bb.XMax <= 630 - d and bb.YMin >= -1080 + d, "{} within the sheet with clearance".format(clone.Label))
    check([p for p in sheet.items if p.v0 == 0] and [p for p in sheet.items if p.u0 == 0],
          "panels flush with the top and left edges")
    ops = job.Proxy.allOperations()
    is_dressup = lambda o: hasattr(o, "Base") and not isinstance(o.Base, list) and o.Base is not None
    tags = [o for o in ops if is_dressup(o)]
    cuts = [o for o in ops if o.Name.startswith("Cut12mm_1_") and not is_dressup(o)]
    check(len(cuts) == len(sheet.lines) == r12.cut_slots, "one Slot per cut line ({})".format(len(cuts)))
    check(len(tags) == len([l for l in sheet.lines if l.tabs]), "one Tags dress-up per cut with tabs")
    check(not r12.disabled_tabs, "no tabs disabled: {}".format(r12.disabled_tabs))
    check(all(t.Base in cuts for t in tags), "every dress-up wraps a cut of this sheet")
    check(not any(t.Base in job.Operations.Group for t in tags), "dressed cuts are not in the operations group twice")
    cuts.sort(key=lambda o: int(o.Name[len("Cut12mm_1_"):-1]))
    for line, op in zip(sheet.lines, cuts):
        p1, p2 = op.CustomPoint1, op.CustomPoint2
        if line.axis == "h":
            check(abs(p1.y + line.pos) < 1e-6 and abs(p2.y + line.pos) < 1e-6, "{} at y = -{}".format(op.Label, line.pos))
        else:
            check(abs(p1.x - line.pos) < 1e-6 and abs(p2.x - line.pos) < 1e-6, "{} at x = {}".format(op.Label, line.pos))
        check(abs(op.FinalDepth.Value + 12.2) < 1e-6, "{} cuts through (-12.2)".format(op.Label))
    # groove pockets follow the nested placement: SideL of the first drawer
    side_clone = [c for c in job.Model.Group if c.Label.endswith("Drawer_SideL")][0]
    sbb = side_clone.Shape.BoundBox
    grooves = [o for o in ops if o.Label.startswith("Drawer_SideL_Groove")]
    check(grooves, "SideL has groove passes")
    placed_side = [p for p in sheet.items if p.item.key == (part.Name, "SideL")][0]
    for g in grooves:
        if placed_side.rotated:
            check(abs(g.CustomPoint1.x - g.CustomPoint2.x) < 1e-9, "rotated SideL groove runs along Y")
            dist = sbb.XMax - g.CustomPoint1.x  # groove side away from the left edge
            check(8 + d / 2 - 1e-6 <= dist <= 16 - d / 2 + 1e-6, "groove band 8..16 from the right edge ({:.2f})".format(dist))
        else:
            check(abs(g.CustomPoint1.y - g.CustomPoint2.y) < 1e-9, "SideL groove runs along X")
            dist = g.CustomPoint1.y - sbb.YMin
            check(8 + d / 2 - 1e-6 <= dist <= 16 - d / 2 + 1e-6, "groove band 8..16 above the bottom edge ({:.2f})".format(dist))
        check(abs(g.FinalDepth.Value + 6) < 1e-6, "groove depth 6")
        # recessed T&D: stopped groove, the pass ends 6 mm (lip) + tool radius inside the panel ends
        ends = sorted([g.CustomPoint1.y, g.CustomPoint2.y] if placed_side.rotated else [g.CustomPoint1.x, g.CustomPoint2.x])
        lo, hi = (sbb.YMin, sbb.YMax) if placed_side.rotated else (sbb.XMin, sbb.XMax)
        check(abs(ends[0] - lo - (6 + d / 2)) < 1e-6 and abs(hi - ends[1] - (6 + d / 2)) < 1e-6,
              "SideL groove pass stops {:.1f} inside each end".format(6 + d / 2))
    handles = [o for o in ops if o.Label.startswith("Drawer_SideL_Handle")]
    check(len(handles) >= 15 and all(abs(o.FinalDepth.Value + 12.2) < 1e-6 for o in handles), "SideL handle slot: through passes ({})".format(len(handles)))
    hx = [c for o in handles for c in (o.CustomPoint1, o.CustomPoint2)]
    if placed_side.rotated:
        span = max(c.y for c in hx) - min(c.y for c in hx)
        across = max(c.x for c in hx) - min(c.x for c in hx)
    else:
        span = max(c.x for c in hx) - min(c.x for c in hx)
        across = max(c.y for c in hx) - min(c.y for c in hx)
    hreg = [r for r in cam.pocket_regions("SideL", params, cam.panel_frame("SideL", params)) if r.name == "Handle"][0]
    hus = [c[0] for pp in cam.slot_passes(hreg, d) for c in pp]
    check(abs(span - (max(hus) - min(hus))) < 1e-6 and abs(across - (32 - d)) < 1e-6 and span <= 100 - d + 1e-9,
          "handle passes on the sheet match the frame passes ({:.2f} x {:.2f}, tool {:g})".format(span, across, d))
    check(not [o for o in ops if o.Label.startswith("Captured_SideL_Handle")], "drawer without handle slots has no handle passes")
    check([o for o in ops if o.Label.startswith("Captured_Bottom_Rabbet")], "captured bottom has rabbet passes")
    check(not [o for o in ops if o.Label.startswith("Drawer_Bottom_Rabbet")], "inserted bottom has none")
    for prefix in ("Captured_", "Drawer_"):
        for role, feature in (("SideL", "Corner"), ("SideR", "Corner"), ("Front", "Lap"), ("Back", "Lap")):
            ends = sorted(set(o.Label.split("_")[-2] for o in ops
                              if o.Label.startswith("{}{}_{}".format(prefix, role, feature))))
            want = ["CornerBack", "CornerFront"] if feature == "Corner" else ["LapLeft", "LapRight"]
            check(ends == want, "{}{} has both {} cuts: {}".format(prefix, role, feature, ends))
    # Half-lap: corner rabbets t_side wide, no laps; the wide rabbet accepts an 8 mm bit
    # while the 6 mm groove of the captured drawer's inserted sibling still does not.
    holder_c.corner_joint = "Half-lap"
    doc.recompute()
    params_h = cam.DrawerParams(holder_c)
    frame_h = cam.panel_frame("SideL", params_h)
    corners_h = [r for r in cam.pocket_regions("SideL", params_h, frame_h) if r.name.startswith("Corner")]
    check(len(corners_h) == 2 and all(abs(r.u1 - r.u0 - 12.0) < 1e-9 for r in corners_h), "half-lap corner rabbets are t_side wide")
    check(abs(max(r.u1 for r in corners_h) - frame_h.L / 2.0) < 1e-9, "half-lap rabbet runs to the end edge")
    check(not [r for r in cam.pocket_regions("Front", params_h, cam.panel_frame("Front", params_h)) if r.name.startswith("Lap")], "half-lap: no laps on the front")
    wide = cam.CamSettings()
    wide.__dict__.update(s.__dict__)
    wide.tool_d = 8.0
    problems_h, _ = cam.validate_drawer(part_c, params_h, wide)
    check(problems_h and not any("Corner" in p or "Lap" in p for p in problems_h),
          "8 mm bit fits the half-lap rabbets; only the 6 mm groove/bottom rabbet reject it: {}".format(problems_h))
    holder_c.corner_joint = "Tongue and dado (flush)"
    doc.recompute()
    params_f = cam.DrawerParams(holder_c)
    check(not [r for r in cam.pocket_regions("Front", params_f, cam.panel_frame("Front", params_f)) if r.name.startswith("Lap")], "flush T&D: outer-face laps are not machined")
    check([r for r in cam.pocket_regions("SideL", params_f, cam.panel_frame("SideL", params_f)) if r.name.startswith("Corner") and abs(r.u1 - r.u0 - 6.0) < 1e-9], "flush T&D: sides keep the 6 mm dado")
    groove_f = [r for r in cam.pocket_regions("SideL", params_f, cam.panel_frame("SideL", params_f)) if r.name == "Groove"][0]
    check(groove_f.closed and abs(groove_f.u1 - (400.0 / 2 - 6.0)) < 1e-9, "flush T&D: CAM groove stopped 6 mm short of the side ends")
    problems_f, warn_f = cam.validate_drawer(part_c, params_f, s)
    check(not problems_f and any("OUTER face" in w and "by hand" in w for w in warn_f), "flush T&D: manual lap reported as a warning: {}".format(warn_f))
    holder_c.corner_joint = "Tongue and dado (recessed)"
    doc.recompute()
    problems_t, warn_t = cam.validate_drawer(part_c, cam.DrawerParams(holder_c), wide)
    check(any("Corner" in p for p in problems_t) and any("Lap" in p for p in problems_t),
          "8 mm bit is rejected for the tongue-and-dado corners")
    check(not [w for w in warn_t if "by hand" in w], "recessed T&D: no manual-cut warning")
    check(abs(job.SetupSheet.ClearanceHeightOffset.Value - 22) < 1e-6, "clearance offset = clamp height + 2")

    # --- G-code ---------------------------------------------------------------------
    check(r12.gcode_files, "gcode written")
    g = r12.gcode_files[0]
    check(os.path.basename(g) == "test_Captured_Drawer_12mm_1.nc", "gcode name {}".format(os.path.basename(g)))
    text = open(g).read()
    check("G1" in text and "M6" in text, "gcode has moves and a tool change")
    check(abs(min_z_in_gcode(g) + 12.2) < 1e-3, "deepest Z is -12.2")
    xr = xy_range_in_gcode(g)
    check(xr[0] >= -d and xr[1] <= 630 and xr[3] <= d and xr[2] >= -1080, "XY within the sheet: {}".format(xr))
    check("Z22" in text, "rapids at clamp clearance Z=22")
    r8 = by_t[8.0][0]
    check(abs(min_z_in_gcode(r8.gcode_files[0]) + 8.2) < 1e-3, "8 mm sheet cuts to -8.2")

    # --- re-run replaces the jobs without leaking -----------------------------------
    n_after = len(doc.Objects)
    container.Label = "CAM my kitchen"
    results2, problems, _ = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems, "re-run ok")
    check(len(doc.Objects) == n_after, "re-run replaces jobs without leaking objects ({} -> {})".format(n_after, len(doc.Objects)))
    check(results2[0].container == container and container.Label == "CAM my kitchen", "same drawers: container reused, rename kept")
    check(os.path.basename(results2[0].gcode_files[0]).startswith("test_my_kitchen_"), "gcode named after the renamed container")
    check(len(container.Group) == len(results2) and all(r.frame in container.Group and r.job in r.frame.Group for r in results2), "reused container holds exactly the new frames")
    check(len(cam.find_lumberjack_jobs(doc, [part.Name])) == 3, "three jobs involve the first drawer")
    results3, problems, warn3 = cam.run([(part_c, holder_c)], s)
    check(not problems, "single drawer run ok")
    check(any("also re-nested" in w for w in warn3), "sharing drawer is pulled into the run and reported")
    check(sorted(r.thickness for r in results3) == [8.0, 12.0, 18.0], "shared drawers are re-nested together")
    check(len(cam.find_lumberjack_jobs(doc, [part.Name])) == 3, "the other drawer keeps full job coverage")
    check(len(doc.Objects) == n_after, "still no leaked objects")
    check(results3[0].container == container, "expanded selection reuses the container")

    # a run on a single drawer that never shared a container gets its own container
    part_solo = drawers.create_drawer("Solo", DRAWER_C)
    holder_solo = cam.drawer_holder(part_solo)
    n_before_solo = len(doc.Objects)
    results_solo, problems, _ = cam.run([(part_solo, holder_solo)], s)
    check(not problems, "solo run ok")
    solo_container = results_solo[0].container
    check(solo_container != container and solo_container.Label == "CAM Solo", "solo drawer gets its own container: {}".format(solo_container.Label))
    # nesting solo with the others merges into a new container and removes the old ones
    results_all, problems, warn_all = cam.run([(part, holder), (part_solo, holder_solo)], s)
    check(not problems, "merged run ok")
    check(any("Captured" in w for w in warn_all), "drawer sharing the old container is pulled in")
    merged = results_all[0].container
    check(merged.Label == "CAM Captured/Drawer/Solo", "merged container named after all three: {}".format(merged.Label))
    check([o for o in doc.Objects if hasattr(o, cam.CAM_GROUP_PROP)] == [merged], "old containers removed, only the merged one remains")
    check(sorted(merged.LumberjackDrawers) == sorted([part.Name, part_c.Name, part_solo.Name]), "merged container records all drawers")
    check(all(r.frame in merged.Group and r.job in r.frame.Group for r in results_all), "all merged jobs in the merged container")
    xs = sorted(r.frame.Placement.Base.x for r in results_all)
    check(len(xs) == len(results_all) and all(abs(b - a - 693) < 1e-6 for a, b in zip(xs, xs[1:])), "merged sheets spaced 693 mm apart: {}".format(xs))
    # back to the two original drawers: solo is expanded in again (shared container)
    results_two, problems, warn_two = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems and results_two[0].container == merged, "container fully covered: drawers sharing it are re-nested along")
    check(any("Solo" in w for w in warn_two), "expansion reported")
    n12 = sum(len(r.job.Model.Group) for r in results_two if r.thickness == 12.0)
    check(n12 == 4 + 5 + 5, "all three drawers' 12 mm panels are nested ({})".format(n12))
    drawers.delete_drawer(part_solo)
    results_two, problems, _ = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems, "run after deleting a drawer of the container ok")
    container = results_two[0].container
    check(container.Label == "CAM Captured/Drawer" and len([o for o in doc.Objects if hasattr(o, cam.CAM_GROUP_PROP)]) == 1, "deleted drawer dropped, fresh container: {}".format(container.Label))
    n_after = len(doc.Objects)
    results2, problems, _ = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems and len(doc.Objects) == n_after, "stable object count after cleanup")

    # --- bottom-left origin: mirrored layout, Y positive ------------------------------
    sb_ = cam.CamSettings()
    sb_.__dict__.update(s.__dict__)
    sb_.origin = cam.ORIGIN_BOTTOM_LEFT
    results_b, problems, _ = cam.run([(part, holder), (part_c, holder_c)], sb_)
    check(not problems, "bottom-left run ok")
    rb = [r for r in results_b if r.thickness == 12.0][0]
    jb = rb.job
    bbs = jb.Stock.Shape.BoundBox
    check(abs(bbs.YMin) < 1e-6 and abs(bbs.YMax - 1080) < 1e-6, "bottom-left: stock spans Y 0..1080")
    for placed in rb.sheet.items:
        clone = [c for c in jb.Model.Group if c.Objects and c.Objects[0].Name == placed.item.data.body.Name][0]
        bb = clone.Shape.BoundBox
        check(abs(bb.XMin - placed.u0) < 1e-6 and abs(bb.YMin - placed.v0) < 1e-6, "{} hugs bottom-left placement".format(clone.Label))
        check(abs(bb.XLength - placed.du) < 1e-6 and abs(bb.YLength - placed.dv) < 1e-6, "{} orientation kept".format(clone.Label))
    ops_b = jb.Proxy.allOperations()
    cuts_b = [o for o in ops_b if o.Name.startswith("Cut12mm_1_") and not (hasattr(o, "Base") and not isinstance(o.Base, list) and o.Base is not None)]
    cuts_b.sort(key=lambda o: int(o.Name[len("Cut12mm_1_"):-1]))
    for line, op in zip(rb.sheet.lines, cuts_b):
        if line.axis == "h":
            check(abs(op.CustomPoint1.y - line.pos) < 1e-6, "{} at y = +{}".format(op.Label, line.pos))
        else:
            check(abs(op.CustomPoint1.x - line.pos) < 1e-6, "{} at x = {}".format(op.Label, line.pos))
    # an unrotated wall (if any) must have its groove away from the bottom edge
    for placed in rb.sheet.items:
        ref = placed.item.data
        if placed.rotated or ref.role not in ("SideL", "SideR", "Front", "Back"):
            continue
        clone = [c for c in jb.Model.Group if c.Objects and c.Objects[0].Name == ref.body.Name][0]
        gs = [o for o in ops_b if o.Label.startswith("{}_{}_Groove".format(ref.part.Label, ref.role))]
        check(gs and all(o.CustomPoint1.y > clone.Shape.BoundBox.Center.y for o in gs),
              "bottom-left: groove of {} lies away from the bottom edge".format(clone.Label))
    xr = xy_range_in_gcode(rb.gcode_files[0])
    check(xr[2] >= -d and xr[3] <= 1080, "bottom-left gcode Y is positive: {}".format(xr))
    summary = "\n".join(cam.summarize_results(results_b, [], cam.ORIGIN_BOTTOM_LEFT))
    check("bottom edge" in summary, "summary names the bottom edge")
    check(len(doc.Objects) == n_after, "no leak after origin switch")

    # --- recreate a drawer and re-run --------------------------------------------------
    cam.run([(part, holder)], s)
    old_name = part.Name
    n_jobs = len(cam.find_lumberjack_jobs(doc, [old_name]))
    new_part = drawers.recreate_drawer(part)
    check(new_part is not None and new_part.Name == old_name, "recreated drawer keeps its name")
    new_holder = cam.drawer_holder(new_part)
    results4, problems, _ = cam.run([(new_part, new_holder)], s)
    check(not problems and len(results4) == n_jobs, "jobs rebuilt after recreation")
    check(all(r.gcode_files for r in results4), "gcode after recreation")

    doc.save()
    FreeCAD.Console.PrintMessage("ALL CHECKS PASSED\n")


try:
    main()
except Exception:
    traceback.print_exc()
    FreeCAD.Console.PrintError("TEST FAILED\n")
    sys.exit(1)
sys.exit(0)
