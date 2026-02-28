# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - project.py

Project setup functionality:
- Creating new projects with parameter spreadsheets
- Syncing aliases across the spreadsheet
"""

import FreeCAD
import FreeCADGui

# =============================================================================
# CONFIGURATION
# =============================================================================

# Number of parameter rows to create (excluding header)
NUM_ROWS = 10

# Spreadsheet configuration
SPREADSHEET_NAME = "p"  # Short name for easy expression references
SPREADSHEET_LABEL = "Parameters"  # Human-readable label shown in tree

# Default parameter presets - can be customized
# Format: (param_name, default_value, description)
DEFAULT_PARAMETERS = [
    ("thickness", "18", "Material thickness (mm)"),
    ("width", "600", "Overall width (mm)"),
    ("height", "800", "Overall height (mm)"),
    ("depth", "400", "Overall depth (mm)"),
]


# =============================================================================
# SPREADSHEET CREATION
# =============================================================================


def create_parameter_spreadsheet(doc, num_rows=NUM_ROWS):
    """
    Create a parameter spreadsheet with the configured structure.

    Args:
        doc: FreeCAD document to add the spreadsheet to
        num_rows: Number of parameter rows to create (excluding header)

    Returns:
        The created spreadsheet object
    """
    # Create spreadsheet with short internal name for easy referencing
    spreadsheet = doc.addObject("Spreadsheet::Sheet", SPREADSHEET_NAME)
    spreadsheet.Label = SPREADSHEET_LABEL

    # Set up header row
    spreadsheet.set("A1", "param")
    spreadsheet.set("B1", "value")
    spreadsheet.set("C1", "description")

    # Set column widths for better readability
    spreadsheet.setColumnWidth("A", 120)
    spreadsheet.setColumnWidth("B", 100)
    spreadsheet.setColumnWidth("C", 250)

    # Fill in parameter rows
    for i in range(num_rows):
        row_num = i + 2  # Start from row 2 (row 1 is header)

        # Check if we have a default parameter for this row
        if i < len(DEFAULT_PARAMETERS):
            param_name, default_value, description = DEFAULT_PARAMETERS[i]
        else:
            # Empty row for user to fill in
            param_name = ""
            default_value = ""
            description = ""

        # Set cell values
        param_cell = "A{}".format(row_num)
        value_cell = "B{}".format(row_num)
        desc_cell = "C{}".format(row_num)

        spreadsheet.set(param_cell, param_name)
        spreadsheet.set(value_cell, default_value)
        spreadsheet.set(desc_cell, description)

        # Set alias on the value cell using the param name
        # Only if param_name is valid
        if param_name and _is_valid_alias(param_name):
            try:
                spreadsheet.setAlias(value_cell, param_name)
            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    "Lumberjack: Could not set alias '{}' on {}: {}\n".format(
                        param_name, value_cell, e
                    )
                )

    # Recompute to apply changes
    doc.recompute()

    return spreadsheet


def create_new_project():
    """
    Create a new FreeCAD document with preset configurations.

    Returns:
        The created document, or None on failure
    """
    # Create new document
    doc = FreeCAD.newDocument("Untitled")

    if doc is None:
        FreeCAD.Console.PrintError("Lumberjack: Failed to create new document.\n")
        return None

    # Create the parameter spreadsheet
    spreadsheet = create_parameter_spreadsheet(doc, NUM_ROWS)

    FreeCAD.Console.PrintMessage(
        "Lumberjack: Created new project with parameter spreadsheet '{}'\n".format(
            SPREADSHEET_NAME
        )
    )
    FreeCAD.Console.PrintMessage("  - {} parameter rows created\n".format(NUM_ROWS))
    FreeCAD.Console.PrintMessage(
        "  - Reference parameters in expressions as: {}.<param_name>\n".format(
            SPREADSHEET_NAME
        )
    )
    FreeCAD.Console.PrintMessage(
        "  - Example: {}.thickness, {}.width\n".format(
            SPREADSHEET_NAME, SPREADSHEET_NAME
        )
    )
    FreeCAD.Console.PrintMessage(
        "  - Aliases auto-sync when you edit the 'param' column\n"
    )

    # Set view to show the spreadsheet
    FreeCADGui.ActiveDocument.setEdit(spreadsheet.Name)

    return doc


# =============================================================================
# ALIAS SYNC
# =============================================================================


def _is_valid_alias(name):
    """Check if name is a valid FreeCAD alias (Python identifier)."""
    if not name:
        return False
    # Must start with letter or underscore
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    # Must contain only alphanumeric and underscore
    for char in name:
        if not (char.isalnum() or char == "_"):
            return False
    # Cannot be a Python keyword
    import keyword

    if keyword.iskeyword(name):
        return False
    return True


def sync_all_aliases(spreadsheet=None):
    """
    Manually sync all aliases in the parameter spreadsheet.

    Args:
        spreadsheet: The spreadsheet to sync. If None, finds 'p' in active document.

    Returns:
        Number of aliases synced, or -1 on error
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintError("Lumberjack: No active document.\n")
        return -1

    # Find the spreadsheet
    if spreadsheet is None:
        spreadsheet = doc.getObject(SPREADSHEET_NAME)

    if spreadsheet is None:
        FreeCAD.Console.PrintError(
            "Lumberjack: No spreadsheet named '{}' found.\n".format(SPREADSHEET_NAME)
        )
        return -1

    if spreadsheet.TypeId != "Spreadsheet::Sheet":
        FreeCAD.Console.PrintError(
            "Lumberjack: Object '{}' is not a spreadsheet.\n".format(SPREADSHEET_NAME)
        )
        return -1

    synced = 0
    row = 2  # Start from row 2 (skip header)

    # Process rows until we hit an empty param cell (with some buffer)
    empty_count = 0
    max_empty = 5  # Stop after 5 consecutive empty rows

    while empty_count < max_empty:
        param_cell = "A{}".format(row)
        value_cell = "B{}".format(row)

        try:
            param_name = spreadsheet.getContents(param_cell)
        except Exception:
            param_name = ""

        # Clean up the param name
        if param_name:
            param_name = param_name.strip().strip("'\"")

        if not param_name:
            empty_count += 1
            row += 1
            continue

        empty_count = 0  # Reset empty counter

        # Skip header-like content
        if param_name.lower() == "param":
            row += 1
            continue

        # Validate and set alias
        if _is_valid_alias(param_name):
            try:
                current_alias = spreadsheet.getAlias(value_cell)
            except Exception:
                current_alias = None

            if current_alias != param_name:
                # Clear old alias first
                if current_alias:
                    try:
                        spreadsheet.setAlias(value_cell, "")
                    except Exception:
                        pass

                # Set new alias
                try:
                    spreadsheet.setAlias(value_cell, param_name)
                    synced += 1
                    FreeCAD.Console.PrintMessage(
                        "Lumberjack: Set alias '{}' on cell {}\n".format(
                            param_name, value_cell
                        )
                    )
                except Exception as e:
                    FreeCAD.Console.PrintWarning(
                        "Lumberjack: Could not set alias '{}' on {}: {}\n".format(
                            param_name, value_cell, e
                        )
                    )
        else:
            FreeCAD.Console.PrintWarning(
                "Lumberjack: '{}' is not a valid alias name\n".format(param_name)
            )

        row += 1

    doc.recompute()

    FreeCAD.Console.PrintMessage("Lumberjack: Synced {} aliases\n".format(synced))

    return synced
