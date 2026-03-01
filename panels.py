# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - panels.py

Panel (furniture part) creation functionality:
- Create PartDesign bodies with parametric dimensions
- Expression-driven sketch constraints and pad operations
- Dialog with proper expression binding using Gui::QuantitySpinBox
"""

import FreeCAD
import FreeCADGui
import Part
import Sketcher

# =============================================================================
# CONTAINER UTILITIES
# =============================================================================


def get_active_container():
    """
    Get the currently active container (App::Part or Assembly).

    Returns the active 'part' object if one is set, otherwise None.
    This allows bodies to be created inside the currently active container.
    """
    if FreeCADGui.ActiveDocument is None:
        return None

    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        if view is not None and hasattr(view, "getActiveObject"):
            # Check for active 'part' (App::Part container)
            active_part = view.getActiveObject("part")
            if active_part is not None:
                return active_part
    except Exception:
        pass

    return None


def add_object_to_active_container(obj):
    """
    Add an object to the currently active container, if any.

    Args:
        obj: The FreeCAD object to add to the container

    Returns:
        The container the object was added to, or None if no active container
    """
    container = get_active_container()
    if container is not None:
        try:
            # App::Part uses addObject method
            if hasattr(container, "addObject"):
                container.addObject(obj)
                FreeCAD.Console.PrintMessage(
                    "Lumberjack: Added '{}' to container '{}'\n".format(
                        obj.Label, container.Label
                    )
                )
                return container
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "Lumberjack: Could not add '{}' to container: {}\n".format(obj.Label, e)
            )
    return None


try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide import QtCore
    from PySide import QtGui as QtWidgets


# =============================================================================
# CONFIGURATION
# =============================================================================


def _get_param_group():
    """Get the parameter group for storing preferences."""
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Lumberjack")


def _get_last_value(key, default):
    """Get a stored value, or return default."""
    params = _get_param_group()
    return params.GetString(key, default)


def _set_last_value(key, value):
    """Store a value for later retrieval."""
    params = _get_param_group()
    params.SetString(key, value)


# =============================================================================
# PANEL TEMPLATE
# =============================================================================


class PanelTemplate:
    """
    A temporary FeaturePython object used to bind expression widgets.

    This object holds the Width, Length, and Thickness properties that the
    Gui::QuantitySpinBox widgets bind to. After the dialog is accepted,
    we read the expressions from this object and apply them to the actual
    sketch constraints and pad.
    """

    name = "PanelTemplate"

    def __init__(self, obj):
        obj.Proxy = self
        for prop in ["Width", "Length", "Thickness"]:
            if prop not in obj.PropertiesList:
                obj.addProperty("App::PropertyLength", prop)


# =============================================================================
# PANEL CREATION DIALOG
# =============================================================================


class CreatePanelDialog(QtWidgets.QDialog):
    """Dialog for creating a new furniture panel using Gui::QuantitySpinBox with expression binding."""

    def __init__(self, parent=None):
        super(CreatePanelDialog, self).__init__(parent)
        self.setWindowTitle("Create Panel")
        self.setMinimumWidth(400)
        self.template = None
        self._setup_template()
        self._setup_ui()

    def _setup_template(self):
        """Create a temporary template object for expression binding."""
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        # Remove any existing template
        if doc.getObject(PanelTemplate.name):
            doc.removeObject(PanelTemplate.name)

        # Create new template
        template_obj = doc.addObject("App::FeaturePython", PanelTemplate.name)
        PanelTemplate(template_obj)
        template_obj.ViewObject.Proxy = 0
        self.template = template_obj

        # Set default expressions from last used values or defaults
        thickness_expr = _get_last_value("panel_thickness", "p.thickness")
        width_expr = _get_last_value("panel_width", "p.width")
        height_expr = _get_last_value("panel_height", "p.height")

        # Set expressions on template
        self.template.setExpression("Thickness", thickness_expr)
        self.template.setExpression("Width", width_expr)
        self.template.setExpression("Length", height_expr)

        doc.recompute()

    def _cleanup_template(self):
        """Remove the temporary template object."""
        doc = FreeCAD.ActiveDocument
        if doc and self.template:
            try:
                doc.removeObject(PanelTemplate.name)
            except Exception:
                pass
        self.template = None

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QtWidgets.QVBoxLayout(self)

        # Name field
        name_layout = QtWidgets.QHBoxLayout()
        name_label = QtWidgets.QLabel("Name:")
        name_label.setMinimumWidth(70)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setText("Panel")
        self.name_edit.selectAll()  # Highlight by default
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # Separator
        layout.addSpacing(10)

        # Info label
        info_label = QtWidgets.QLabel(
            "Enter values or expressions. Click the 'f(x)' button or\n"
            "type directly to use expressions like p.thickness."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        layout.addSpacing(5)

        if self.template:
            # Thickness field - using Gui::QuantitySpinBox with ExpressionBinding
            thickness_layout = QtWidgets.QHBoxLayout()
            thickness_label = QtWidgets.QLabel("Thickness:")
            thickness_label.setMinimumWidth(70)
            self.thickness_widget = FreeCADGui.UiLoader().createWidget(
                "Gui::QuantitySpinBox"
            )
            self.thickness_widget.setProperty("unit", "mm")
            self.thickness_widget.setProperty("rawValue", self.template.Thickness.Value)
            FreeCADGui.ExpressionBinding(self.thickness_widget).bind(
                self.template, "Thickness"
            )
            thickness_layout.addWidget(thickness_label)
            thickness_layout.addWidget(self.thickness_widget)
            layout.addLayout(thickness_layout)

            # Width field - using Gui::QuantitySpinBox with ExpressionBinding
            width_layout = QtWidgets.QHBoxLayout()
            width_label = QtWidgets.QLabel("Width:")
            width_label.setMinimumWidth(70)
            self.width_widget = FreeCADGui.UiLoader().createWidget(
                "Gui::QuantitySpinBox"
            )
            self.width_widget.setProperty("unit", "mm")
            self.width_widget.setProperty("rawValue", self.template.Width.Value)
            FreeCADGui.ExpressionBinding(self.width_widget).bind(self.template, "Width")
            width_layout.addWidget(width_label)
            width_layout.addWidget(self.width_widget)
            layout.addLayout(width_layout)

            # Height field - using Gui::QuantitySpinBox with ExpressionBinding
            height_layout = QtWidgets.QHBoxLayout()
            height_label = QtWidgets.QLabel("Height:")
            height_label.setMinimumWidth(70)
            self.height_widget = FreeCADGui.UiLoader().createWidget(
                "Gui::QuantitySpinBox"
            )
            self.height_widget.setProperty("unit", "mm")
            self.height_widget.setProperty("rawValue", self.template.Length.Value)
            FreeCADGui.ExpressionBinding(self.height_widget).bind(
                self.template, "Length"
            )
            height_layout.addWidget(height_label)
            height_layout.addWidget(self.height_widget)
            layout.addLayout(height_layout)
        else:
            # Fallback if template creation failed
            error_label = QtWidgets.QLabel(
                "Error: Could not create template object.\n"
                "Please ensure a document is open."
            )
            error_label.setStyleSheet("color: red;")
            layout.addWidget(error_label)

        # Separator
        layout.addSpacing(15)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton("Create")
        self.create_button.setDefault(True)
        self.create_button.setEnabled(self.template is not None)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        button_layout.addStretch()
        button_layout.addWidget(self.create_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Connect signals
        self.create_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        # Focus on name field
        self.name_edit.setFocus()

    def _get_expression_for_property(self, prop_name):
        """
        Get the expression string for a property from the template.

        In FreeCAD 1.1, expressions are accessed via the ExpressionEngine property,
        which returns a list of tuples: [(property_path, expression_string), ...]
        """
        if not self.template:
            return None

        # ExpressionEngine is a list of (property, expression) tuples
        try:
            for prop, expr in self.template.ExpressionEngine:
                if prop == prop_name:
                    return expr
        except Exception:
            pass

        return None

    def get_values(self):
        """Return the dialog values as a dict with expressions from the template."""
        if not self.template:
            return None

        # Get expressions from template using ExpressionEngine
        thickness_expr = self._get_expression_for_property("Thickness")
        width_expr = self._get_expression_for_property("Width")
        height_expr = self._get_expression_for_property("Length")

        # Use expression string or fall back to raw value with unit
        thickness_str = (
            thickness_expr
            if thickness_expr
            else "{} mm".format(self.template.Thickness.Value)
        )
        width_str = (
            width_expr if width_expr else "{} mm".format(self.template.Width.Value)
        )
        height_str = (
            height_expr if height_expr else "{} mm".format(self.template.Length.Value)
        )

        return {
            "name": self.name_edit.text().strip(),
            "thickness": thickness_str,
            "width": width_str,
            "height": height_str,
        }

    def reject(self):
        """Handle cancel - cleanup template."""
        self._cleanup_template()
        super(CreatePanelDialog, self).reject()


# =============================================================================
# PANEL CREATION
# =============================================================================


def create_panel(name, thickness_expr, width_expr, height_expr):
    """
    Create a furniture panel (PartDesign Body with Pad).

    Args:
        name: Name for the body
        thickness_expr: Expression for pad length (thickness)
        width_expr: Expression for sketch width
        height_expr: Expression for sketch height

    Returns:
        The created Body object, or None on failure
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintError("Lumberjack: No active document.\n")
        return None

    # Create the Body
    body = doc.addObject("PartDesign::Body", name)
    body.Label = name

    # Add to active container if one is set
    add_object_to_active_container(body)

    # Create the Sketch
    sketch = doc.addObject("Sketcher::SketchObject", "{}_Sketch".format(name))
    sketch.Label = "{}_Sketch".format(name)

    # Add sketch to body first
    body.addObject(sketch)

    # Find the XY plane from the body's origin
    xy_plane = None
    for feature in body.Origin.OriginFeatures:
        if hasattr(feature, "Role") and feature.Role == "XY_Plane":
            xy_plane = feature
            break

    if xy_plane:
        sketch.AttachmentSupport = [(xy_plane, "")]
        sketch.MapMode = "FlatFace"
    else:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: Could not find XY plane, sketch may not be properly attached.\n"
        )

    # Create rectangle geometry
    # Rectangle from origin: 4 lines forming a closed rectangle
    # Line 0: bottom (0,0) to (width, 0)
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(100, 0, 0))
    )
    # Line 1: right (width, 0) to (width, height)
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(100, 0, 0), FreeCAD.Vector(100, 100, 0))
    )
    # Line 2: top (width, height) to (0, height)
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(100, 100, 0), FreeCAD.Vector(0, 100, 0))
    )
    # Line 3: left (0, height) to (0, 0)
    sketch.addGeometry(
        Part.LineSegment(FreeCAD.Vector(0, 100, 0), FreeCAD.Vector(0, 0, 0))
    )

    # Add constraints to close the rectangle
    # Coincident constraints to connect corners
    sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))  # bottom-right
    sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))  # top-right
    sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))  # top-left
    sketch.addConstraint(
        Sketcher.Constraint("Coincident", 3, 2, 0, 1)
    )  # bottom-left (close)

    # Fix to origin
    sketch.addConstraint(
        Sketcher.Constraint("Coincident", 0, 1, -1, 1)
    )  # bottom-left to origin

    # Horizontal/Vertical constraints
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))  # bottom
    sketch.addConstraint(Sketcher.Constraint("Horizontal", 2))  # top
    sketch.addConstraint(Sketcher.Constraint("Vertical", 1))  # right
    sketch.addConstraint(Sketcher.Constraint("Vertical", 3))  # left

    # Add dimensional constraints for width (on bottom line) and height (on right line)
    width_constraint_idx = sketch.addConstraint(
        Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 100)
    )
    height_constraint_idx = sketch.addConstraint(
        Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 100)
    )

    # Set expressions on the dimensional constraints
    sketch.setExpression("Constraints[{}]".format(width_constraint_idx), width_expr)
    sketch.setExpression("Constraints[{}]".format(height_constraint_idx), height_expr)

    # Recompute sketch
    doc.recompute()

    # Create the Pad
    pad = doc.addObject("PartDesign::Pad", "{}_Pad".format(name))
    pad.Label = "{}_Pad".format(name)
    pad.Profile = sketch
    pad.Length = 10  # Temporary value, will be overridden by expression
    pad.Type = 0  # Dimension type
    pad.UpToFace = None
    pad.Reversed = False

    # Add pad to body
    body.addObject(pad)

    # Set expression on pad length
    pad.setExpression("Length", thickness_expr)

    # Hide the sketch
    sketch.Visibility = False

    # Recompute
    doc.recompute()

    FreeCAD.Console.PrintMessage(
        "Lumberjack: Created panel '{}' with expressions:\n".format(name)
    )
    FreeCAD.Console.PrintMessage("  - Thickness: {}\n".format(thickness_expr))
    FreeCAD.Console.PrintMessage("  - Width: {}\n".format(width_expr))
    FreeCAD.Console.PrintMessage("  - Height: {}\n".format(height_expr))

    return body


def show_create_panel_dialog():
    """Show the Create Panel dialog and create a panel if confirmed."""
    doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintError(
            "Lumberjack: No active document. Create or open a document first.\n"
        )
        return None

    # Get the main window as parent
    main_window = FreeCADGui.getMainWindow()

    dialog = CreatePanelDialog(main_window)
    result = dialog.exec_()

    if result == QtWidgets.QDialog.Accepted:
        values = dialog.get_values()

        if values is None:
            FreeCAD.Console.PrintError(
                "Lumberjack: Could not get values from dialog.\n"
            )
            dialog._cleanup_template()
            return None

        # Validate name
        if not values["name"]:
            FreeCAD.Console.PrintError("Lumberjack: Panel name cannot be empty.\n")
            dialog._cleanup_template()
            return None

        # Save values for next time
        _set_last_value("panel_thickness", values["thickness"])
        _set_last_value("panel_width", values["width"])
        _set_last_value("panel_height", values["height"])

        # Cleanup template before creating panel
        dialog._cleanup_template()

        # Create the panel
        return create_panel(
            values["name"], values["thickness"], values["width"], values["height"]
        )

    return None
