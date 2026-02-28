# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - Init.py

This module runs when FreeCAD starts (before GUI initialization).
It sets up the document observer that automatically syncs spreadsheet
aliases with parameter names.
"""

import FreeCAD

# =============================================================================
# CONFIGURATION
# =============================================================================

# Name of the spreadsheet to watch for alias sync
SPREADSHEET_NAME = "p"

# Column configuration (0-indexed)
PARAM_COLUMN = 0  # Column A - parameter names


# =============================================================================
# ALIAS SYNC OBSERVER
# =============================================================================


class ParameterAliasSyncObserver:
    """
    Document observer that automatically syncs spreadsheet aliases.

    When a cell in the param column changes, the corresponding value cell's
    alias is updated to match the new param name.
    """

    def __init__(self):
        self._processing = False  # Prevent recursive updates

    def slotChangedObject(self, obj, prop):
        """Called when any object property changes."""
        # Avoid recursive calls
        if self._processing:
            return

        # Only process spreadsheets with the target name
        if not hasattr(obj, "TypeId"):
            return
        if obj.TypeId != "Spreadsheet::Sheet":
            return
        if obj.Name != SPREADSHEET_NAME:
            return

        # Check if this is a cell change (properties like 'A2', 'B3', etc.)
        if not prop or len(prop) < 2:
            return

        # Parse cell address
        col_letter = ""
        row_str = ""
        for char in prop:
            if char.isalpha():
                col_letter += char
            elif char.isdigit():
                row_str += char

        if not col_letter or not row_str:
            return

        # Convert column letter to index (A=0, B=1, etc.)
        col_index = 0
        for i, char in enumerate(reversed(col_letter.upper())):
            col_index += (ord(char) - ord("A") + 1) * (26**i)
        col_index -= 1  # Make 0-indexed

        row_num = int(row_str)

        # Only process changes to the param column (column A)
        # Skip header row (row 1)
        if col_index != PARAM_COLUMN or row_num < 2:
            return

        self._processing = True
        try:
            self._sync_alias(obj, row_num)
        finally:
            self._processing = False

    def _sync_alias(self, spreadsheet, row_num):
        """Sync the alias for a specific row."""
        param_cell = "A{}".format(row_num)
        value_cell = "B{}".format(row_num)

        try:
            # Get the param name from column A
            param_name = spreadsheet.getContents(param_cell)

            # Clean up the param name (remove quotes, whitespace)
            if param_name:
                param_name = param_name.strip().strip("'\"")

            # Skip empty param names or header-like content
            if not param_name or param_name.lower() == "param":
                # Clear any existing alias
                try:
                    spreadsheet.setAlias(value_cell, "")
                except Exception:
                    pass
                return

            # Validate alias name (must be valid Python identifier)
            if not self._is_valid_alias(param_name):
                FreeCAD.Console.PrintWarning(
                    "Lumberjack: '{}' is not a valid alias name "
                    "(must start with letter, contain only letters/numbers/underscores)\n".format(
                        param_name
                    )
                )
                return

            # Get current alias to check if update is needed
            try:
                current_alias = spreadsheet.getAlias(value_cell)
            except Exception:
                current_alias = None

            # Only update if different
            if current_alias != param_name:
                # Clear old alias first if it exists
                if current_alias:
                    try:
                        spreadsheet.setAlias(value_cell, "")
                    except Exception:
                        pass

                # Set new alias
                spreadsheet.setAlias(value_cell, param_name)
                FreeCAD.Console.PrintMessage(
                    "Lumberjack: Set alias '{}' on cell {}\n".format(
                        param_name, value_cell
                    )
                )

        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "Lumberjack: Could not sync alias for row {}: {}\n".format(row_num, e)
            )

    def _is_valid_alias(self, name):
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


# =============================================================================
# OBSERVER MANAGEMENT
# =============================================================================

# Global observer instance
_observer = None


def install_observer():
    """Install the alias sync observer."""
    global _observer
    if _observer is None:
        _observer = ParameterAliasSyncObserver()
        FreeCAD.addDocumentObserver(_observer)
        FreeCAD.Console.PrintMessage("Lumberjack: Alias sync observer installed\n")


def uninstall_observer():
    """Uninstall the alias sync observer."""
    global _observer
    if _observer is not None:
        FreeCAD.removeDocumentObserver(_observer)
        _observer = None
        FreeCAD.Console.PrintMessage("Lumberjack: Alias sync observer removed\n")


# Install observer when this module loads
install_observer()
