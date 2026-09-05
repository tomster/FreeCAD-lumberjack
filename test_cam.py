# -*- coding: utf-8 -*-
"""
Headless end-to-end test for cam.py.

Run:
    ~/Applications/FreeCAD.AppImage --console \
        --module-path ~/Projects/FreeCAD/Mod/Lumberjack \
        ~/Projects/FreeCAD/Mod/Lumberjack/test_cam.py

Creates a drawer, generates its CAM Job with a bit from the CAM library, post-processes
it and checks the result. Then moves one panel and regenerates to verify that the
operations follow the new placement.
"""

import math
import os
import shutil
import sys
import traceback

import FreeCAD

OUT_DIR = "/tmp/lj_cam"
BIT_MAX_D = 4.0  # groove = t_bottom / 2 = 4 mm with t_bottom = 8 mm


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


def main():
    import cam
    import drawers

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    doc = FreeCAD.newDocument("LjCamTest")
    doc.saveAs(os.path.join(OUT_DIR, "test.FCStd"))

    part = drawers.create_drawer(
        "Drawer",
        {
            "width": "400 mm",
            "height": "120 mm",
            "depth": "500 mm",
            "t_side": "12 mm",
            "t_bottom": "8 mm",
            "bottom_v_offset": "0 mm",
            "width_front": "440 mm",
            "height_front": "160 mm",
            "t_front": "18 mm",
            "front_v_offset": "20 mm",
            "overlap_box": False,
            "has_front": True,
        },
    )
    check(part is not None, "drawer created")
    holder = cam.drawer_holder(part)
    check(holder is not None, "holder found")
    check(cam.find_drawer_part(part.Group[1]) == (part, holder), "body resolves to drawer")

    # --- drawer model: inserted bottom (t_bottom 8 < t_side 12) -----------------
    bodies = {b.Name.rsplit("_", 1)[-1]: b for b in part.Group if b.TypeId == "PartDesign::Body"}
    bot = bodies["Bottom"]
    check(abs(bot.Shape.Volume - 388.0 * 488.0 * 8.0) < 1e-3, "inserted bottom keeps its full thickness (no rabbet)")
    check(abs(bot.Shape.BoundBox.ZMin - 8.0) < 1e-6, "inserted bottom sits 8 mm up (groove start)")
    side = bodies["SideL"]
    check(abs(side.Shape.Volume - (500.0 * 120.0 * 12.0 - 500.0 * 6.0 * 8.0)) < 1e-3, "side groove is 8 wide x 6 deep")
    gz = [f.BoundBox.ZMin for f in side.Shape.Faces if abs(f.normalAt(0, 0).z) > 0.99 and 7 < f.BoundBox.ZMin < 17]
    check(any(abs(z - 8.0) < 1e-6 for z in gz) and any(abs(z - 16.0) < 1e-6 for z in gz), "groove band is z 8..16 ({})".format(sorted(set(round(z, 3) for z in gz))))
    # live toggle: making the bottom as thick as the sides switches to the captured joint
    holder.setExpression("t_bottom", None)
    holder.t_bottom = "12 mm"
    doc.recompute()
    check(bot.Shape.Volume < 388.0 * 488.0 * 12.0 - 1.0, "captured bottom (12 == 12) gets the rabbet back")
    check(abs(bot.Shape.BoundBox.ZMin) < 1e-6, "captured bottom sits on z = 0")
    holder.t_bottom = "8 mm"
    doc.recompute()
    check(abs(bot.Shape.Volume - 388.0 * 488.0 * 8.0) < 1e-3, "back to inserted after resetting t_bottom")

    bit = pick_bit(cam)
    FreeCAD.Console.PrintMessage("  using bit {} (d={})\n".format(bit.label, bit.diameter))

    s = cam.CamSettings()
    s.bit_id = bit.bit_id
    s.bit_label = bit.label
    s.tool_d = bit.diameter
    s.cutting_edge_height = bit.edge_height
    s.bed_x, s.bed_y = 1200.0, 800.0
    posts = cam.available_post_processors()
    s.post = "uccnc" if "uccnc" in posts else posts[0]
    s.spindle, s.feed_xy, s.feed_z, s.step_down = 16000.0, 360.0, 360.0, 3.0
    s.write_gcode = True

    # --- pure geometry -----------------------------------------------------
    r = cam.Region("x", 0, 100, 0, 3, 1, "u")
    check(len(cam.slot_passes(r, 3.0)) == 1, "w == d gives one pass")
    check(len(cam.slot_passes(r, 1.5)) == 3, "w == 2d gives 3 passes (50% step-over)")
    r6 = cam.Region("x", 0, 100, 0, 6, 1, "u")
    check(len(cam.slot_passes(r6, 3.0)) == 3, "w == 2d (6/3) gives 3 passes")
    try:
        cam.slot_passes(r, 3.5)
        raise AssertionError("ToolTooWide not raised")
    except cam.ToolTooWide:
        FreeCAD.Console.PrintMessage("  ok: ToolTooWide raised\n")
    pos = cam.tab_positions([(0, 0), (100, 0), (100, 50), (0, 50)], 2.0)
    check(len(pos) == 8, "8 tab positions")
    check(all(abs(y + 2.0) < 1e-9 for x, y in pos[0:2]), "bottom-edge tabs offset outward")

    # --- validation ---------------------------------------------------------
    params = cam.DrawerParams(holder)
    problems, warnings = cam.validate_drawer(part, params, s)
    check(not problems, "no validation problems: {}".format(problems))
    bad = cam.CamSettings()
    bad.__dict__.update(s.__dict__)
    bad.tool_d = 6.0
    problems, _ = cam.validate_drawer(part, params, bad)
    check(not problems, "6 mm bit is fine for the 8 mm groove of an inserted bottom")
    bad.tool_d = 9.0
    problems, _ = cam.validate_drawer(part, params, bad)
    check(any("Groove" in p for p in problems), "9 mm bit is rejected for an 8 mm groove")
    bad.tool_d = s.tool_d
    bad.bed_x, bad.bed_y = 300.0, 300.0
    problems, _ = cam.validate_drawer(part, params, bad)
    check(problems, "small bed is rejected")

    # --- job ------------------------------------------------------------------
    results, problems, warnings = cam.run([(part, holder)], s)
    check(not problems, "run succeeded")
    res = results[0]
    job = res.job
    check(res.created, "job created")
    check(job.LumberjackDrawer == part.Name, "job tagged with drawer")
    clones = job.Model.Group
    check(len(clones) == 6, "6 model clones ({})".format(len(clones)))
    for c in clones:
        check(abs(c.Shape.BoundBox.ZMax) < 1e-6, "{} top at Z=0".format(c.Label))
    xs = sorted((c.Shape.BoundBox.XMin, c.Shape.BoundBox.XMax) for c in clones)
    for (a0, a1), (b0, b1) in zip(xs, xs[1:]):
        check(b0 > a1, "panels do not overlap in X")
    # groove of SideL: 4 mm wide, one pass with a <= 4 mm bit... count slots:
    d = s.tool_d
    def npass(w):
        return len(cam.slot_passes(cam.Region("r", 0, 10, 0, w, 1, "u"), d))
    # inserted bottom (8 < 12): groove 8 mm wide, no bottom rabbet strips
    expected_slots = 4 * npass(8.0) + 2 * 2 * npass(12.0)
    check(res.slots == expected_slots, "slot count {} == {}".format(res.slots, expected_slots))
    check(res.profiles == 6, "6 profiles")
    ops = job.Operations.Group
    tags = [o for o in ops if o.Name.endswith("Tags") or "Tags" in o.Label]
    check(len(tags) == 6, "6 tag dress-ups in the operations group ({})".format(len(tags)))
    profiles_in_group = [o for o in ops if o.Label.endswith("_Profile")]
    check(not profiles_in_group, "base profiles removed from the operations group")
    check(not res.disabled_tabs, "no tabs disabled: {}".format(res.disabled_tabs))
    for t in tags:
        check(len(t.Positions) == 8, "{} has 8 tabs".format(t.Label))
    check(len(job.Tools.Group) == 1, "exactly one tool controller")
    tc = job.Tools.Group[0]
    check(abs(float(tc.Tool.Diameter) - d) < 1e-6, "tool controller diameter matches")
    stock = job.Stock
    sb = stock.Shape.BoundBox
    check(abs(sb.ZMax) < 1e-6 and sb.ZMin < -17.9, "stock spans from -18 to 0 ({:.2f}..{:.2f})".format(sb.ZMin, sb.ZMax))

    # --- geometry of the generated operations ---------------------------------
    def clone_of(role):
        return [c for c in clones if c.Label.endswith("_" + role)][0]

    def ops_starting(prefix):
        return [o for o in job.Proxy.allOperations() if o.Label.startswith(prefix)]

    ts, tb = 12.0, 8.0
    for role in ("SideL", "SideR", "Back", "Front"):
        c = clone_of(role)
        bb = c.Shape.BoundBox
        check(abs(bb.ZMin + ts) < 1e-6, "{} is {} thick when flat".format(role, ts))
        check(abs(bb.YLength - 120.0) < 1e-6, "{} height runs along Y".format(role))
        grooves = ops_starting(role + "_Groove")
        check(len(grooves) >= 1, "{} has a groove".format(role))
        for g in grooves:
            y = g.CustomPoint1.y
            check(abs(g.CustomPoint1.y - g.CustomPoint2.y) < 1e-9, "{} groove pass runs along X".format(role))
            check(bb.YMin + tb + d / 2 - 1e-6 <= y <= bb.YMin + 2 * tb - d / 2 + 1e-6,
                  "{} groove pass at {:.2f} lies in the band {:.1f}..{:.1f} above the bottom edge".format(
                      role, y - bb.YMin, tb, 2 * tb))
            check(g.CustomPoint1.x < bb.XMin and g.CustomPoint2.x > bb.XMax or
                  g.CustomPoint2.x < bb.XMin and g.CustomPoint1.x > bb.XMax,
                  "{} groove overshoots both ends".format(role))
            check(abs(g.FinalDepth.Value + ts / 2) < 1e-6 and abs(g.StartDepth.Value) < 1e-6,
                  "{} groove depth is t_side/2".format(role))
        rabbets = ops_starting(role + "_RabbetEnd")
        if role in ("SideL", "SideR"):
            check(rabbets, "{} (full length with drawer front) has end rabbets".format(role))
            for r_ in rabbets:
                x = r_.CustomPoint1.x
                check(abs(r_.CustomPoint1.x - r_.CustomPoint2.x) < 1e-9, "rabbet pass runs along Y")
                inside_end = (bb.XMax - ts + d / 2 - 1e-6 <= x <= bb.XMax - d / 2 + 1e-6) or (
                    bb.XMin + d / 2 - 1e-6 <= x <= bb.XMin + ts - d / 2 + 1e-6)
                check(inside_end, "{} rabbet pass at x={:.2f} is within {} mm of an end".format(role, x, ts))
                check(min(r_.CustomPoint1.y, r_.CustomPoint2.y) < bb.YMin and
                      max(r_.CustomPoint1.y, r_.CustomPoint2.y) > bb.YMax, "rabbet overshoots top and bottom")
        else:
            check(not rabbets, "{} (short panel) has no end rabbets".format(role))
    c = clone_of("Bottom")
    bb = c.Shape.BoundBox
    check(abs(bb.ZMin + tb) < 1e-6, "Bottom is 8 thick when flat")
    check(abs(bb.XLength - 488.0) < 1e-6 and abs(bb.YLength - 388.0) < 1e-6, "Bottom is 488 x 388 with length along X")
    check(not ops_starting("Bottom_Rabbet"), "inserted bottom has no rabbet passes")
    for r_ in ops_starting("Bottom_Rabbet"):
        p1, p2 = r_.CustomPoint1, r_.CustomPoint2
        if abs(p1.y - p2.y) < 1e-9:  # pass along X
            near = min(abs(p1.y - bb.YMin), abs(bb.YMax - p1.y))
        else:
            near = min(abs(p1.x - bb.XMin), abs(bb.XMax - p1.x))
        check(d / 2 - 1e-6 <= near <= ts / 2 - d / 2 + 1e-6, "{} runs within the 6 mm rim (at {:.2f})".format(r_.Label, near))
        check(abs(r_.FinalDepth.Value + tb / 2) < 1e-6, "bottom rabbet depth is t_bottom/2")
    for role, t in (("SideL", ts), ("Bottom", tb), ("DrawerFront", 18.0)):
        prof = ops_starting(role + "_Profile")[0]
        check(abs(prof.FinalDepth.Value + t + 0.2) < 1e-6, "{} profile cuts to -{}".format(role, t + 0.2))
    df = clone_of("DrawerFront")
    check(abs(df.Shape.BoundBox.XLength - 440.0) < 1e-6, "DrawerFront width along X")

    check(res.gcode_files, "gcode written")
    gpath = res.gcode_files[0]
    check(os.path.exists(gpath) and os.path.getsize(gpath) > 1000, "gcode file {} non-empty".format(gpath))
    text = open(gpath).read()
    check("G1" in text, "gcode has G1 moves")
    zmin = min_z_in_gcode(gpath)
    check(abs(zmin - (-(18.0 + 0.2))) < 1e-3, "deepest Z {} == -18.2 (drawer front)".format(zmin))
    check(job.PostProcessorOutputFile == gpath, "job output file set")

    # --- captured bottom drawer (t_bottom == t_side), no drawer front --------------
    part_c = drawers.create_drawer(
        "Captured",
        {
            "width": "300 mm", "height": "100 mm", "depth": "400 mm",
            "t_side": "12 mm", "t_bottom": "12 mm", "bottom_v_offset": "0 mm",
            "width_front": "340 mm", "height_front": "140 mm", "t_front": "18 mm",
            "front_v_offset": "20 mm", "overlap_box": False, "has_front": False,
        },
    )
    holder_c = cam.drawer_holder(part_c)
    bot_c = [b for b in part_c.Group if b.Name.endswith("_Bottom")][0]
    check(bot_c.Shape.Volume < 288.0 * 388.0 * 12.0 - 1.0, "captured bottom is rabbeted")
    results_c, problems_c, _ = cam.run([(part_c, holder_c)], s)
    check(not problems_c, "captured drawer job ok: {}".format(problems_c))
    job_c = results_c[0].job
    check(job_c != job, "separate job for the second drawer")
    ops_c = job_c.Proxy.allOperations()
    check(len([o for o in ops_c if o.Label.startswith("Bottom_Rabbet")]) == 4 * npass(6.0), "captured bottom has 4 rabbet strips")
    check(all(o.Label.startswith(("Front", "Back")) for o in ops_c if "RabbetEnd" in o.Label) and
          any("RabbetEnd" in o.Label for o in ops_c), "Front/Back get the end rabbets without a drawer front")
    sl = [c for c in job_c.Model.Group if c.Label.endswith("SideL")][0]
    bbc = sl.Shape.BoundBox
    for g in [o for o in ops_c if o.Label.startswith("SideL_Groove")]:
        y = g.CustomPoint1.y - bbc.YMin
        check(6.0 + d / 2 - 1e-6 <= y <= 12.0 - d / 2 + 1e-6, "captured groove band 6..12 (pass at {:.2f})".format(y))
    check(results_c[0].gcode_files and os.path.exists(results_c[0].gcode_files[0]), "captured drawer gcode written")

    # --- recreate the drawer (as after a drawers.py update) -----------------------
    cont = doc.addObject("App::Part", "Cabinet")
    old_pl = FreeCAD.Placement(FreeCAD.Vector(100, 200, 300), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90))
    part_r = drawers.create_drawer("Recreated", {
        "width": "300 mm", "height": "100 mm", "depth": "400 mm",
        "t_side": "12 mm", "t_bottom": "8 mm", "bottom_v_offset": "0 mm",
        "width_front": "340 mm", "height_front": "140 mm", "t_front": "18 mm",
        "front_v_offset": "20 mm", "overlap_box": False, "has_front": True,
    }, container=cont, placement=old_pl)
    holder_r = cam.drawer_holder(part_r)
    doc.addObject("Spreadsheet::Sheet", "Sheet")
    doc.Sheet.set("A1", "=320 mm")
    doc.Sheet.setAlias("A1", "Cabinet_Width")
    holder_r.setExpression("width", "Sheet.Cabinet_Width")
    doc.recompute()
    vals = drawers.read_drawer_values(holder_r)
    check(vals["width"] == "Sheet.Cabinet_Width", "expression read back verbatim ({})".format(vals["width"]))
    check(vals["t_side"] in ("12 mm", "12.0 mm"), "plain value read back ({})".format(vals["t_side"]))
    check(vals["has_front"] is True and vals["overlap_box"] is False, "booleans read back")
    res_r0 = cam.run([(part_r, holder_r)], s)[0][0]
    job_r = res_r0.job
    old_name = part_r.Name
    n_before = len(doc.Objects)
    new_part = drawers.recreate_drawer(part_r)
    check(new_part is not None and new_part.Name == old_name, "recreated drawer keeps its internal name")
    check(new_part.Label == "Recreated", "label kept")
    check(new_part in cont.Group, "still inside the container")
    check(new_part.Placement.isSame(old_pl, 1e-9), "placement kept")
    check(len(doc.Objects) == n_before, "no leaked objects ({} -> {})".format(n_before, len(doc.Objects)))
    new_holder = cam.drawer_holder(new_part)
    check(dict(new_holder.ExpressionEngine).get("width") in ("Sheet.Cabinet_Width", "(Sheet.Cabinet_Width)"),
          "spreadsheet expression survives recreation")
    check(abs(new_holder.width.Value - 320.0) < 1e-6, "expression evaluates after recreation")
    check(len(cam.drawer_panels(new_part)) == 6, "6 panels after recreation")
    res_r = cam.run([(new_part, new_holder)], s)[0][0]
    check(res_r.job == job_r and not res_r.created, "CAM job re-attached to the recreated drawer")
    check(len(job_r.Model.Group) == 6 and all(c.Objects and c.Objects[0].Document for c in job_r.Model.Group),
          "job models rebuilt from the new bodies")
    check(res_r.gcode_files, "gcode after recreation")

    # --- regenerate after moving a panel ---------------------------------------
    side = [c for c in clones if c.Label.endswith("SideL")][0]
    groove_before = [o for o in ops if o.Label.startswith("SideL_Groove")][0].CustomPoint1.x
    pl = side.Placement
    pl.Base = pl.Base + FreeCAD.Vector(50, 0, 0)
    side.Placement = pl
    doc.recompute()
    results2, problems, _ = cam.run([(part, holder)], s)
    check(not problems, "regeneration succeeded")
    res2 = results2[0]
    check(res2.job == job, "same job reused")
    check(not res2.created, "job not recreated")
    side2 = [c for c in job.Model.Group if c.Label.endswith("SideL")][0]
    check(side2 == side, "clone kept")
    check(abs(side2.Placement.Base.x - pl.Base.x) < 1e-9, "manual placement kept")
    groove_after = [o for o in job.Operations.Group if o.Label.startswith("SideL_Groove")][0].CustomPoint1.x
    check(abs((groove_after - groove_before) - 50.0) < 1e-6, "groove followed the panel (+50)")
    check(len(job.Tools.Group) == 1, "still one tool controller")
    check(len(job.Model.Group) == 6, "still 6 clones")
    check(len([o for o in doc.Objects if o.TypeId == "Path::FeaturePython" and o.Name.startswith("Stock")]) <= 1, "old stock removed")

    doc.save()
    FreeCAD.Console.PrintMessage("ALL CHECKS PASSED\n")


if __name__ == "__main__" or True:
    try:
        main()
    except Exception:
        traceback.print_exc()
        FreeCAD.Console.PrintError("TEST FAILED\n")
        sys.exit(1)
    sys.exit(0)
