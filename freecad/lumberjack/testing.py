from mock import Mock
import sys
import types

# mock FreeCAD package to allow our own code
# to load in a non-FreeCAD environment
FreeCAD = types.ModuleType("FreeCAD")
sys.modules["FreeCAD"] = FreeCAD
FreeCADGui = types.ModuleType("FreeCADGui")
sys.modules["FreeCADGui"] = FreeCADGui
Draft = types.ModuleType("Draft")
sys.modules["Draft"] = Draft
DraftGeomUtils = types.ModuleType("DraftGeomUtils")
sys.modules["DraftGeomUtils"] = DraftGeomUtils
DraftVecUtils = types.ModuleType("DraftVecUtils")
sys.modules["DraftVecUtils"] = DraftVecUtils
FreeCAD.Vector = Mock(name="FreeCAD.Vector")
FreeCAD.Rotation = Mock(name="FreeCAD.Rotation")
