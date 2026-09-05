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
    "front_v_offset": "20 mm", "overlap_box": False, "has_front": True,
}
DRAWER_C = {  # captured bottom (t_bottom == t_side), no drawer front
    "width": "300 mm", "height": "100 mm", "depth": "400 mm",
    "t_side": "12 mm", "t_bottom": "12 mm", "bottom_v_offset": "0 mm",
    "width_front": "340 mm", "height_front": "140 mm", "t_front": "18 mm",
    "front_v_offset": "20 mm", "overlap_box": False, "has_front": False,
}


def test_geometry(cam, nesting):
    r = cam.Region("x", 0, 100, 0, 3, 1, "u")
    check(len(cam.slot_passes(r, 3.0)) == 1, "w == d gives one pass")
    check(len(cam.slot_passes(r, 1.5)) == 3, "w == 2d gives 3 passes (50% step-over)")
    try:
        cam.slot_passes(r, 3.5)
        raise AssertionError("ToolTooWide not raised")
    except cam.ToolTooWide:
        FreeCAD.Console.PrintMessage("  ok: ToolTooWide raised\n")

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
    check(abs(bot.Shape.Volume - 388.0 * 488.0 * 8.0) < 1e-3, "inserted bottom keeps its full thickness")
    check(abs(bot.Shape.BoundBox.ZMin - 8.0) < 1e-6, "inserted bottom sits 8 mm up")
    holder.setExpression("t_bottom", None)
    holder.t_bottom = "12 mm"
    doc.recompute()
    check(bot.Shape.Volume < 388.0 * 488.0 * 12.0 - 1.0, "captured bottom (12 == 12) gets the rabbet")
    holder.t_bottom = "8 mm"
    doc.recompute()
    check(abs(bot.Shape.Volume - 388.0 * 488.0 * 8.0) < 1e-3, "back to inserted after resetting")

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
    check([o for o in ops if o.Label.startswith("Captured_Bottom_Rabbet")], "captured bottom has rabbet passes")
    check(not [o for o in ops if o.Label.startswith("Drawer_Bottom_Rabbet")], "inserted bottom has none")
    check(any("_Front_RabbetEnd" in o.Label or "_Back_RabbetEnd" in o.Label for o in ops if o.Label.startswith("Captured_")),
          "captured drawer (no front) rabbets its Front/Back")
    check(any("_SideL_RabbetEnd" in o.Label for o in ops if o.Label.startswith("Drawer_")), "drawer with front rabbets its sides")
    check(abs(job.SetupSheet.ClearanceHeightOffset.Value - 22) < 1e-6, "clearance offset = clamp height + 2")

    # --- G-code ---------------------------------------------------------------------
    check(r12.gcode_files, "gcode written")
    g = r12.gcode_files[0]
    check(os.path.basename(g) == "test_CAM_12mm_1.nc", "gcode name {}".format(os.path.basename(g)))
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
    results2, problems, _ = cam.run([(part, holder), (part_c, holder_c)], s)
    check(not problems, "re-run ok")
    check(len(doc.Objects) == n_after, "re-run replaces jobs without leaking objects ({} -> {})".format(n_after, len(doc.Objects)))
    check(len(cam.find_lumberjack_jobs(doc, [part.Name])) == 3, "three jobs involve the first drawer")
    results3, problems, warn3 = cam.run([(part_c, holder_c)], s)
    check(not problems, "single drawer run ok")
    check(any("also re-nested" in w for w in warn3), "sharing drawer is pulled into the run and reported")
    check(sorted(r.thickness for r in results3) == [8.0, 12.0, 18.0], "shared drawers are re-nested together")
    check(len(cam.find_lumberjack_jobs(doc, [part.Name])) == 3, "the other drawer keeps full job coverage")
    check(len(doc.Objects) == n_after, "still no leaked objects")

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
