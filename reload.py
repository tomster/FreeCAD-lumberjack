# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - reload.py

Development helper for reloading modules without restarting FreeCAD.

Usage from FreeCAD Python console:
    import reload
    reload.reload_all()

Or reload specific modules:
    reload.reload_panels()
    reload.reload_project()
"""

import importlib
import sys


def reload_module(module_name):
    """
    Reload a single module by name.

    Args:
        module_name: Name of the module to reload (e.g., 'panels', 'project')

    Returns:
        The reloaded module, or None on failure
    """
    import FreeCAD

    try:
        if module_name in sys.modules:
            module = sys.modules[module_name]
            importlib.reload(module)
            FreeCAD.Console.PrintMessage(
                "Lumberjack: Reloaded '{}'\n".format(module_name)
            )
            return module
        else:
            # Try to import it first
            module = importlib.import_module(module_name)
            FreeCAD.Console.PrintMessage(
                "Lumberjack: Imported '{}' (was not loaded)\n".format(module_name)
            )
            return module
    except Exception as e:
        FreeCAD.Console.PrintError(
            "Lumberjack: Failed to reload '{}': {}\n".format(module_name, e)
        )
        return None


def reload_panels():
    """Reload the panels module."""
    return reload_module("panels")


def reload_project():
    """Reload the project module."""
    return reload_module("project")


def reload_drawers():
    """Reload the drawers module."""
    return reload_module("drawers")


def reload_nesting():
    """Reload the nesting module (sheet layout for CAM)."""
    return reload_module("nesting")


def reload_naming():
    """Reload the naming module (compact names for CAM containers)."""
    return reload_module("naming")


def reload_cam():
    """Reload the cam module (drawer CAM job generation); reloads nesting and naming first."""
    reload_nesting()
    reload_naming()
    return reload_module("cam")


def reload_init():
    """
    Reload the Init module and reinstall the observer.

    Note: This removes and reinstalls the alias sync observer.
    """
    import FreeCAD

    # Remove existing observer if present
    observer_attr = "_lumberjack_alias_sync_observer"
    try:
        old_observer = getattr(FreeCAD, observer_attr, None)
        if old_observer is not None:
            FreeCAD.removeDocumentObserver(old_observer)
            delattr(FreeCAD, observer_attr)
            FreeCAD.Console.PrintMessage("Lumberjack: Removed old observer\n")
    except Exception as e:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: Could not remove old observer: {}\n".format(e)
        )

    # Reload and reinstall
    import Init

    importlib.reload(Init)
    return Init


def reload_all():
    """
    Reload all Lumberjack modules.

    Call this after making changes to any module files.
    """
    import FreeCAD

    FreeCAD.Console.PrintMessage("Lumberjack: Reloading all modules...\n")

    reload_project()
    reload_panels()
    reload_drawers()
    reload_cam()

    FreeCAD.Console.PrintMessage("Lumberjack: All modules reloaded.\n")
    FreeCAD.Console.PrintMessage(
        "Lumberjack: Note - InitGui changes require FreeCAD restart.\n"
    )


def test_panel_creation():
    """
    Quick test for panel creation without using the dialog.

    Useful for testing create_panel() function directly.
    """
    import FreeCAD

    # Reload panels first to get latest code
    panels = reload_panels()

    if panels is None:
        return None

    doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("LumberjackTest")

    # Check for active container
    container = panels.get_active_container()
    if container:
        FreeCAD.Console.PrintMessage(
            "Lumberjack: Active container: '{}'\n".format(container.Label)
        )
    else:
        FreeCAD.Console.PrintMessage("Lumberjack: No active container\n")

    # Create a test panel
    body = panels.create_panel(
        name="TestPanel",
        thickness_expr="18 mm",
        width_expr="200 mm",
        height_expr="300 mm",
    )

    return body


def test_drawer_creation():
    """
    Quick test for drawer creation without using the dialog.

    Useful for testing create_drawer() function directly from the console.
    """
    import FreeCAD

    drawers = reload_drawers()
    if drawers is None:
        return None

    doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("LumberjackDrawerTest")

    part = drawers.create_drawer(
        name="TestDrawer",
        values={
            "width": "400 mm",
            "height": "120 mm",
            "depth": "500 mm",
            "t_side": "12 mm",
            "t_bottom": "6 mm",
            "bottom_v_offset": "0 mm",
            "width_front": "440 mm",
            "height_front": "160 mm",
            "t_front": "18 mm",
            "front_v_offset": "20 mm",
            "overlap_box": False,
            "has_front": True,
        },
    )
    return part
    """
    Test different approaches to creating a centered rectangle in a sketch.
    Run this to experiment with constraint combinations.
    """
    import FreeCAD
    import FreeCADGui
    import Part
    import Sketcher

    doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("SketchTest")

    # Create a simple sketch
    sketch = doc.addObject("Sketcher::SketchObject", "TestCenteredRect")

    # Approach: Use the built-in rectangle slot from sketcher
    # Create 4 lines with proper initial geometry
    hw, hh = 100, 75  # half-width, half-height

    # Add 4 lines forming rectangle (counterclockwise from bottom-left)
    # Line 0: bottom
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(-hw, -hh, 0), FreeCAD.Vector(hw, -hh, 0))
    )
    # Line 1: right
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(hw, -hh, 0), FreeCAD.Vector(hw, hh, 0))
    )
    # Line 2: top
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(hw, hh, 0), FreeCAD.Vector(-hw, hh, 0))
    )
    # Line 3: left
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(-hw, hh, 0), FreeCAD.Vector(-hw, -hh, 0))
    )

    # Close the rectangle - connect endpoints
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
    sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
    sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
    sketch.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))

    # Make horizontal and vertical
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", 3))

    # Center: constrain the midpoint of bottom edge to be at X=0
    # and midpoint of left edge to be at Y=0
    # Use Block constraint on origin point, then PointOnObject for midpoints

    # Alternative: use horizontal/vertical distance from origin to corners
    # Constrain bottom-left corner: its X = -width/2, its Y = -height/2
    # But we want to use width and height as the full dimensions

    # Simplest approach:
    # - Constrain horizontal distance from origin to right edge = width/2
    # - Constrain horizontal distance from origin to left edge = width/2 (equal)
    # - Same for vertical

    # Or even simpler: use DistanceX from origin to line endpoints
    # Line 0 vertex 1 is bottom-left, line 0 vertex 2 is bottom-right
    # Constrain: X of bottom-left = -(X of bottom-right)
    # This is what Equal constraint with negation would do, but FreeCAD uses Symmetric

    # Let's try: PointOnObject to put a line through the origin
    # Actually, let's just set explicit distances from origin

    # Distance from origin (point -1, vertex 1) to bottom-left corner (line 0, vertex 1)
    # We want this to equal half the diagonal, but that's complex

    # Simplest working approach:
    # Set width constraint on bottom line
    # Set height constraint on right line
    # Then position: set X of bottom-left = -width/2 using expression
    # and Y of bottom-left = -height/2 using expression

    # For now, let's just constrain the center manually:
    # Make left edge X = -100 and right edge X = 100 (symmetric)
    # DistanceX from origin to a point

    # Constraint: horizontal distance from origin to bottom-left corner
    sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, -hw))
    # Constraint: vertical distance from origin to bottom-left corner
    sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, -hh))

    # Width and height constraints
    sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 2 * hw))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 2 * hh))

    doc.recompute()

    # Check constraint status
    if sketch.FullyConstrained:
        FreeCAD.Console.PrintMessage("Sketch is fully constrained!\n")
    else:
        FreeCAD.Console.PrintWarning(
            "Sketch has {} DOF remaining\n".format(sketch.solve())
        )

    # Open the sketch for viewing
    FreeCADGui.ActiveDocument.setEdit(sketch.Name)

    return sketch
