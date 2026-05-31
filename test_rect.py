# -*- coding: utf-8 -*-
"""
Test script for centered rectangle constraints.

Run from FreeCAD:
    exec(open('/path/to/test_rect.py').read())

Or via command line:
    FreeCAD test_rect.py
"""

import FreeCAD
import Part
import Sketcher

doc = FreeCAD.ActiveDocument
if doc is None:
    doc = FreeCAD.newDocument("RectTest")

# Remove old test sketch if exists
if doc.getObject("TestRect"):
    doc.removeObject("TestRect")

sketch = doc.addObject("Sketcher::SketchObject", "TestRect")

# Dimensions
hw, hh = 100, 75  # half-width, half-height

# Add 4 lines forming rectangle centered at origin
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

# Close the rectangle - connect corners
sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
sketch.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))

# Make horizontal and vertical
sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))
sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
sketch.addConstraint(Sketcher.Constraint("Vertical", 3))

# Position: constrain bottom-left corner position relative to origin
# DistanceX from origin (geometry -1, vertex 1) to bottom-left (line 0, vertex 1)
sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, -hw))
# DistanceY from origin to bottom-left
sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, -hh))

# Size: width and height
sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 2 * hw))
sketch.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 2 * hh))

doc.recompute()

# Report status
print("=" * 50)
print("Rectangle test results:")
print("  FullyConstrained:", sketch.FullyConstrained)
print("  DOF:", sketch.solve())
print("  ConstraintCount:", sketch.ConstraintCount)
print("=" * 50)

# Open for viewing if GUI available
try:
    import FreeCADGui
    if FreeCADGui.ActiveDocument:
        FreeCADGui.ActiveDocument.setEdit(sketch.Name)
except Exception:
    pass
