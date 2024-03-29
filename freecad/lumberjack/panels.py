import freecad.fcscript.v_0_0_1 as fc
from FreeCAD import Vector, Rotation, Placement, Console
from PySide import QtCore, QtGui

import os

__dir__ = os.path.dirname(__file__)

import traceback

import FreeCAD
import FreeCAD as App
import freecad.asm3 as asm3
import FreeCADGui
import FreeCADGui as Gui
import Part
import Sketcher
from PySide import QtCore, QtGui


class PartTemplate:

    name = "PartFactory"
    groupname = "Components"
    properties = ["Width", "Length", "Height"]

    def __init__(self, obj):
        obj.Proxy = self
        for property in self.properties:
            try:
                obj.addProperty("App::PropertyQuantity", property)
            except Exception:
                pass
            # make sure we have an expression ready for the property
            if obj.getExpression(property) is None:
                obj.setExpression(property, "10 mm")


class PanelFactory:

    name = None
    assembly = None
    body = None
    pad = None
    sketch = None
    group = None
    template = None

    def _make_template(self, recreate=False):
        if recreate:
            try:
                App.ActiveDocument.removeObject(PartTemplate.name)
                App.ActiveDocument.removeObject(PartTemplate.groupname)
            except Exception:
                pass
        if App.ActiveDocument.getObject(PartTemplate.groupname) is None:
            App.ActiveDocument.addObject("App::LinkGroup", PartTemplate.groupname)
        self.group = group = App.ActiveDocument.getObject(PartTemplate.groupname)
        self.template = obj = App.ActiveDocument.getObject(PartTemplate.name)
        if App.ActiveDocument.getObject(PartTemplate.name) is None:
            obj = App.ActiveDocument.addObject("App::FeaturePython", PartTemplate.name)
            group.ViewObject.dropObject(obj)
        self.template = obj = App.ActiveDocument.getObject(PartTemplate.name)
        PartTemplate(obj)
        self.template.ViewObject.Proxy = 0

    def _ensure_settings_sheet(self):
        """ensure a Spreadsheet for settings exists"""
        if App.ActiveDocument.getObject(settings_name) is None:
            self.settings_sheet = FreeCAD.ActiveDocument.addObject(
                "Spreadsheet::Sheet", settings_name
            )

    def create_part(self):

        try:
            # get inputs from dialog
            self.name = name = self.d_name.text()
            body = self._make_body(name)
            self.group.ViewObject.dropObject(self._make_assembly(name, body))
            self.dimension_body()
            App.ActiveDocument.recompute()
            Gui.SendMsgToActiveView("ViewFit")

        except Exception:
            FreeCAD.Console.PrintError("Ooops: %s" % traceback.print_exc())
        self.close()

    def _make_assembly(self, name, part):
        self.assembly = assembly = asm3.assembly.Assembly.make(App.ActiveDocument, name)
        # add the part to the assembly:
        assembly.ViewObject.dropObject(part, None, "", [])

        # create named elements from each face:
        faces = [
            ("Face1", "rear"),
            ("Face2", "right"),
            ("Face3", "front"),
            ("Face4", "left"),
            ("Face5", "bottom"),
            ("Face6", "top"),
        ]
        for face, fname in faces:
            Gui.Selection.clearSelection()
            selection = Gui.Selection.addSelection(self.pad, face)
            asm3.assembly.AsmElement.make(selection, "%s_%s" % (name, fname))

        Gui.Selection.clearSelection()
        return assembly

    def _make_body(self, name):
        body_name = "%s_body" % name
        App.ActiveDocument.addObject("PartDesign::Body", body_name)
        self.body = body = App.ActiveDocument.getObject(body_name)
        sketch_name = "%s_sketch" % name
        body.newObjectAt(
            "Sketcher::SketchObject",
            sketch_name,
            FreeCADGui.Selection.getSelection(),
        )
        self.sketch = sketch = App.ActiveDocument.getObject(sketch_name)
        sketch.AttachmentOffset = App.Placement(
            App.Vector(0.0000000000, 0.0000000000, 0.0000000000),
            App.Rotation(0.0000000000, 0.0000000000, 0.0000000000),
        )
        sketch.MapReversed = False
        sketch.MapPathParameter = 0.000000
        sketch.MapMode = "FlatFace"
        geoList = []
        geoList.append(
            Part.LineSegment(
                App.Vector(-10, 20, 0),
                App.Vector(10, 20, 0),
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(10, 20, 0),
                App.Vector(10, -20, 0),
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(10, -20, 0),
                App.Vector(-10, -20, 0),
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(-10, -20, 0),
                App.Vector(-10, 20, 0),
            )
        )
        sketch.addGeometry(geoList, False)
        conList = []
        # create undimensioned constraints
        # (like you would roughly clicking the sketch in the GUI)
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 0))
        conList.append(Sketcher.Constraint("Horizontal", 2))
        conList.append(Sketcher.Constraint("Vertical", 1))
        conList.append(Sketcher.Constraint("Vertical", 3))
        conList.append(Sketcher.Constraint("Symmetric", 1, 2, 0, 1, -1, 1))
        conList.append(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 50.0))
        conList.append(Sketcher.Constraint("DistanceY", 3, 1, 3, 2, 30.0))
        sketch.addConstraint(conList)

        self.pad_name = pad_name = "%s_pad" % name
        body.newObjectAt(
            "PartDesign::Pad", pad_name, FreeCADGui.Selection.getSelection()
        )
        self.pad = pad = App.ActiveDocument.getObject(pad_name)
        pad.Profile = App.ActiveDocument.getObject(sketch_name)
        sketch.Visibility = False
        App.ActiveDocument.recompute()
        return self.body

    def dimension_body(self):
        # width:
        self.sketch.setExpression(
            ".Constraints[9]", self.template.getExpression("Width")[1]
        )
        # length:
        self.sketch.setExpression(
            ".Constraints[10]", self.template.getExpression("Length")[1]
        )
        # height:
        pad = self.pad
        pad.Type = 0  # -> Length
        pad.setExpression("Length", self.template.getExpression("Height")[1])
        pad.Midplane = 1

    def close(self):
        self.dialog.hide()

    def _make_dialog(self):
        dialog = QtGui.QDialog()
        dialog.resize(240, 100)

        dialog.setWindowTitle("Create part")
        layout = QtGui.QVBoxLayout(dialog)

        name = QtGui.QLabel("Name")
        layout.addWidget(name)
        self.d_name = d_name = QtGui.QLineEdit()
        layout.addWidget(d_name)

        for property in PartTemplate.properties:
            label = QtGui.QLabel(property)
            layout.addWidget(label)
            widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
            widget.setProperty("unit", "mm")
            Gui.ExpressionBinding(widget).bind(self.template, property)
            layout.addWidget(widget)

        okbox = QtGui.QDialogButtonBox(dialog)
        okbox.setOrientation(QtCore.Qt.Horizontal)
        okbox.setStandardButtons(
            QtGui.QDialogButtonBox.Cancel | QtGui.QDialogButtonBox.Ok
        )
        layout.addWidget(okbox)
        QtCore.QObject.connect(okbox, QtCore.SIGNAL("accepted()"), self.create_part)
        QtCore.QObject.connect(okbox, QtCore.SIGNAL("rejected()"), self.close)
        QtCore.QMetaObject.connectSlotsByName(dialog)
        return dialog

    def __init__(self):
        self._ensure_settings_sheet()
        self._make_template(recreate=False)
        self.dialog = self._make_dialog()
        self.dialog.show()
        self.dialog.exec_()


class _CommandMakePanel:
    def GetResources(self):
        return {
            "Pixmap": __dir__ + "/icons/make_panel.png",
            "MenuText": QtCore.QT_TRANSLATE_NOOP("Lumberjack", "Create Panel"),
            "ToolTip": QtCore.QT_TRANSLATE_NOOP("Lumberjack", "Create a new panel"),
        }

    def IsActive(self):
        return True

    def Activated(self):
        PanelFactory()
