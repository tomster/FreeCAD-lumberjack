# -*- coding: utf-8 -*-
"""
GUI-mode smoke test for cam.py (view providers and dialog widgets), runnable offscreen:

    QT_QPA_PLATFORM=offscreen ~/Applications/FreeCAD.AppImage \
        --module-path ~/Projects/FreeCAD/Mod/Lumberjack \
        ~/Projects/FreeCAD/Mod/Lumberjack/test_cam_gui.py

Writes /tmp/lj_cam_gui/RESULT (PASSED/FAILED) and quits FreeCAD.
"""

import os
import shutil
import sys
import traceback

import FreeCAD
import FreeCADGui

OUT_DIR = "/tmp/lj_cam_gui"
LOG = os.path.join(OUT_DIR, "log.txt")


def log(msg):
    # FreeCAD's GUI redirects stdout/stderr into the report view, so log to a file.
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    log("  ok: {}".format(msg))


def main():
    import cam
    import drawers

    doc = FreeCAD.newDocument("LjCamGuiTest")
    doc.saveAs(os.path.join(OUT_DIR, "gui.FCStd"))
    check(FreeCAD.GuiUp, "GUI is up")

    part = drawers.create_drawer(
        "Schublade",
        {
            "width": "400 mm", "height": "120 mm", "depth": "500 mm",
            "t_side": "12 mm", "t_bottom": "8 mm", "bottom_v_offset": "0 mm",
            "width_front": "440 mm", "height_front": "160 mm", "t_front": "18 mm",
            "front_v_offset": "20 mm", "overlap_box": False, "has_front": False,
        },
    )
    holder = cam.drawer_holder(part)

    # Selection resolution as the command sees it.
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, part.Group[2].Name)  # a body
    drawers_sel, rejected = cam.selected_drawers()
    check(len(drawers_sel) == 1 and not rejected, "selection of a body resolves to the drawer")

    # Dialog widgets (not shown).
    dlg = cam.CreateDrawerCamDialog(drawers_sel, FreeCADGui.getMainWindow())
    check(dlg.bit_combo.count() > 0 and dlg.bits, "dialog lists tool bits")
    idx = [i for i, b in enumerate(dlg.bits) if b.diameter <= 4.0 and b.shape.lower().startswith("endmill")][0]
    dlg.bit_combo.setCurrentIndex(idx)
    s = dlg.get_settings()
    check(s.tool_d == dlg.bits[idx].diameter, "settings carry the bit diameter")
    check(s.sheet_w > 0 and s.clamp_h > 0 and s.feed_xy > 0 and s.step_down > 0, "quantity spinboxes read back")
    check(s.post, "post processor selected: {}".format(s.post))
    check(s.origin in cam.ORIGINS, "origin corner read from the combo: {}".format(s.origin))
    dlg.origin_combo.setCurrentIndex(1)
    check(dlg.get_settings().origin == cam.ORIGIN_BOTTOM_LEFT, "bottom-left selectable")
    dlg.origin_combo.setCurrentIndex(0)
    dlg.deleteLater()

    results, problems, warnings = cam.run(drawers_sel, s)
    check(not problems, "run ok: {}".format(problems))
    check(sorted(r.thickness for r in results) == [8.0, 12.0], "one job per thickness (8 and 12 mm)")
    res = [r for r in results if r.thickness == 12.0][0]
    job = res.job
    check(job.ViewObject is not None and job.ViewObject.Proxy is not None, "job has a view provider")
    check(not getattr(job.ViewObject.Proxy, "deleteOnReject", False), "job not marked deleteOnReject")
    for op in job.Operations.Group:
        check(op.ViewObject.Proxy is not None, "{} has a view provider".format(op.Label))
    check(len(job.Model.Group) == 4, "4 clones on the 12 mm sheet (walls)")
    check(res.cut_slots > 0 and res.pocket_slots > 0, "ops created")
    rabbets = [o for o in job.Proxy.allOperations() if "RabbetEnd" in o.Label]
    check(rabbets and all("_Front_" in o.Label or "_Back_" in o.Label for o in rabbets),
          "without drawer front the Front/Back panels get the end rabbets")
    check(res.gcode_files and os.path.exists(res.gcode_files[0]), "gcode written")
    check(job.Tools.Group[0].ViewObject.Proxy is not None, "tool controller has a view provider")
    check(abs(job.Stock.Shape.BoundBox.XMax - s.sheet_w) < 1e-6, "stock is the sheet")

    # Selecting the Job resolves back to its drawer.
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, job.Name)
    d2, rej2 = cam.selected_drawers()
    check(len(d2) == 1 and d2[0][0] == part and not rej2, "job selection resolves to the drawer")

    # Jobs live in an App::Part container named after the drawer; selecting it works too.
    container = res.container
    check(container is not None and container.TypeId == "App::Part", "jobs collected in an App::Part")
    check(container.Label == "CAM Schublade", "container label: {}".format(container.Label))
    check(all(r.frame in container.Group and r.job in r.frame.Group for r in results), "all jobs in sheet frames in the container")
    check(container.ViewObject is not None and container.ViewObject.Visibility, "container visible")
    xs = sorted(r.frame.Placement.Base.x for r in results)
    check(xs[0] == 0 and abs(xs[1] - s.sheet_w * 1.1) < 1e-6, "second sheet shown one sheet width plus 10 % to the right: {}".format(xs))
    everything = [o for r in results for o in r.frame.Group] + list(container.Group)
    check(not any("Invalid" in o.State for o in everything), "no invalid objects in the container (link scope)")
    check(all(r.frame.ViewObject is not None and r.frame.ViewObject.Visibility for r in results), "frames visible")

    # TechDraw pages render and export.
    import TechDrawGui
    page = res.page
    check(page is not None and page.ViewObject is not None, "page has a view provider")
    pdf = os.path.join(OUT_DIR, "sheet.pdf")
    TechDrawGui.exportPageAsPdf(page, pdf)
    check(os.path.exists(pdf) and os.path.getsize(pdf) > 1000, "page exported as PDF")
    svg = os.path.join(OUT_DIR, "sheet.svg")
    TechDrawGui.exportPageAsSvg(page, svg)
    check(os.path.exists(svg) and "font-family" in open(svg, encoding="utf-8").read(), "exported SVG contains rendered text (as outlines)")
    check(all("Schublade_" + role in cam.page_view(page, kind).Symbol for kind in ("Sheet", "Legend") for role in ("SideL", "SideR", "Front", "Back")), "symbols carry the panel labels")
    log("open pages: {}".format([w.windowTitle() for w in FreeCADGui.getMainWindow().findChildren(cam.QtWidgets.QMdiSubWindow)]))
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, container.Name)
    d3, rej3 = cam.selected_drawers()
    check(len(d3) == 1 and d3[0][0] == part and not rej3, "container selection resolves to the drawer")

    doc.save()


if True:
    status = "FAILED"
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)
    try:
        main()
        status = "PASSED"
        log("ALL GUI CHECKS PASSED")
    except Exception:
        log(traceback.format_exc())
        log("GUI TEST FAILED")
    with open(os.path.join(OUT_DIR, "RESULT"), "w") as f:
        f.write(status + "\n")
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide import QtCore
    # Tear down gently: an active selection during main-window destruction crashes
    # FreeCAD 1.1.3's Measure module (unrelated to cam.py).
    try:
        FreeCADGui.Selection.clearSelection()
        for d in list(FreeCAD.listDocuments().values()):
            FreeCAD.closeDocument(d.Name)
    except Exception:
        pass
    QtCore.QTimer.singleShot(500, FreeCADGui.getMainWindow().close)
    QtCore.QTimer.singleShot(1500, QtCore.QCoreApplication.quit)
