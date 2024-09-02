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


"""
 * ensure factory exists
 * create panel with default values or values from previous panel
 * bind parameters to object in form
 * on cancel, delete the object
 * on submit select the panel
 * optional: create link in current assembly

setup_document

"""


panel_properties = ["Width", "Length", "Height"]
settings_name = "Settings"
components_name = "Components"


class PanelTemplate:

    name = "PanelTemplate"

    def __init__(self, obj):
        obj.Proxy = self
        for property in panel_properties:
            try:
                obj.addProperty("App::PropertyLength", property)
            except Exception:
                pass
            # make sure we have an expression ready for the property
            # but don't overwrite existing values
            if obj.getExpression(property) is None:
                if property == 'Height':
                    # initialise height to the first default height
                    obj.setExpression(property, f"{settings_name}.d1")
                else:
                    obj.setExpression(property, "10 mm")


class PanelFactory:

    name = None
    assembly = None
    body = None
    pad = None
    sketch = None
    components = None
    template = None

    def setup_document(self):
        """
        idempotent setup that ensures that the current document has everything
        that the workbench needs, i.e. Components group, templates etc.
        """

        self._ensure_settings_sheet()
        self._make_template(recreate=False)

    def _make_template(self, recreate=False):
        """Creates the comoponents group and any templates inside it"""
        if recreate:
            # remove any existing instance:
            try:
                App.ActiveDocument.removeObject(PanelTemplate.name)
                App.ActiveDocument.removeObject(components_name)
            except Exception:
                pass
        # create components container (a link group)
        if App.ActiveDocument.getObject(components_name) is None:
            App.ActiveDocument.addObject("App::LinkGroup", components_name)
        self.components = components = App.ActiveDocument.getObject(components_name)

        # ensure panels template
        if App.ActiveDocument.getObject(PanelTemplate.name) is None:
            template = App.ActiveDocument.addObject(
                "App::FeaturePython", PanelTemplate.name
            )
            # move the template inside the components container:
            components.ViewObject.dropObject(template)
        self.template = template = App.ActiveDocument.getObject(PanelTemplate.name)
        # initialise the helper class with the actual object:
        PanelTemplate(template)
        self.template.ViewObject.Proxy = 0

    def _ensure_settings_sheet(self):
        """ensure a Spreadsheet for settings exists"""
        if App.ActiveDocument.getObject(settings_name) is not None:
            return
        self.settings_sheet = sheet = FreeCAD.ActiveDocument.addObject(
            "Spreadsheet::Sheet", settings_name
        )
        row = 1
        sheet.insertRows(f'{row}', 1)
        sheet.mergeCells(f'A{row}:ZZ{row}')
        sheet.set(f'A{row}', 'Thicknesses')
        sheet.setStyle(f'A{row}:ZZ{row}', 'bold', 'add')
        row += 1
        for index in range(row, row+5):
            sheet.set(f"A{index}", f"d{index-1}")
            sheet.set(f"B{index}", f"{index-1}")
            sheet.setEditMode(f"A{index}", "AutoAlias")
            row += 1
        for section in range(1,7):
            sheet.insertRows(f'{row}', 1)
            sheet.mergeCells(f'A{row}:ZZ{row}')
            sheet.set(f'A{row}', f'Section {section}')
            sheet.setStyle(f'A{row}:ZZ{row}', 'bold', 'add')
            row += 1
            for index in range(row, row+5):
                sheet.set(f"A{index}", f"{index-1}")
                sheet.setEditMode(f"A{index}", "AutoAlias")
                row += 1
        App.ActiveDocument.recompute()

    def create_part(self):

        try:
            # get inputs from dialog
            self.name = name = self.d_name.text()
            body = self._make_body(name)
            self.components.ViewObject.dropObject(self._make_assembly(name, body))
            self._dimension_body()
            self._finalize_assembly(name)
            self._create_link()
            App.ActiveDocument.recompute()
            Gui.SendMsgToActiveView("ViewFit")

        except Exception:
            FreeCAD.Console.PrintError("Ooops: %s" % traceback.print_exc())
        self.close()

    def _make_assembly(self, name, part):
        self.assembly = assembly = asm3.assembly.Assembly.make(App.ActiveDocument, name)
        # add the part to the assembly:
        assembly.ViewObject.dropObject(part, None, "", [])
        # copy the template attributes onto the new object:
        for property in panel_properties:
            self.assembly.addProperty("App::PropertyLength", property)
        return assembly

    def _finalize_assembly(self, name):
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

    def _create_link(self):
        link = App.ActiveDocument.addObject("App::Link", "Link")
        link.setLink(self.assembly)
        active_assembly = FreeCADGui.ActiveDocument.ActiveView.getActiveObject(asm3.assembly._asm3ActiveKey)
        if active_assembly is not None:
            active_assembly.ViewObject.dropObject(link)

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

    def _dimension_body(self):
        """ """
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

    #
    # GUI
    #

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

        for property in panel_properties:
            label = QtGui.QLabel(property)
            layout.addWidget(label)
            widget = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
            widget.setProperty("unit", "mm")
            widget.setProperty("rawValue", self.template.getPropertyByName(property))
            Gui.ExpressionBinding(widget).bind(self.template, property)
            layout.addWidget(widget)
            widget.show()

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
        self.setup_document()
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
