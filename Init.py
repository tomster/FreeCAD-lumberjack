# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - Init.py

This module runs when FreeCAD starts (before GUI initialization).
It sets up the document observer that automatically syncs spreadsheet
aliases with parameter names.
"""

import FreeCAD


def install_observer():
    """Install the alias sync observer (idempotent)."""

    # Configuration - defined inside function to avoid scope issues
    SPREADSHEET_NAME = "p"
    PARAM_COLUMN = 0  # Column A - parameter names
    OBSERVER_ATTR = "_lumberjack_alias_sync_observer"

    # Check if already installed
    try:
        if getattr(FreeCAD, OBSERVER_ATTR, None) is not None:
            return
    except Exception:
        pass

    class ParameterAliasSyncObserver:
        """
        Document observer that automatically syncs spreadsheet aliases.

        When a cell in the param column changes, the corresponding value cell's
        alias is updated to match the new param name.
        """

        def __init__(self, spreadsheet_name, param_column):
            self._processing = False  # Prevent recursive updates
            self._spreadsheet_name = spreadsheet_name
            self._param_column = int(param_column)

        def slotChangedObject(self, obj, prop):
            """Called when any object property changes."""
            if self._processing:
                return

            if not hasattr(obj, "TypeId"):
                return
            if obj.TypeId != "Spreadsheet::Sheet":
                return
            if obj.Name != self._spreadsheet_name:
                return

            if not prop or len(prop) < 2:
                return

            # Parse cell address from property name (e.g., "A2", "B3")
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

            # Only process changes to the param column (column A), skip header row (row 1)
            if col_index != self._param_column or row_num < 2:
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
                param_name = spreadsheet.getContents(param_cell)
                if param_name:
                    param_name = param_name.strip().strip("'\"")

                if not param_name or param_name.lower() == "param":
                    try:
                        spreadsheet.setAlias(value_cell, "")
                    except Exception:
                        pass
                    return

                if not self._is_valid_alias(param_name):
                    FreeCAD.Console.PrintWarning(
                        "Lumberjack: '{}' is not a valid alias name "
                        "(must start with letter, contain only letters/numbers/underscores)\n".format(
                            param_name
                        )
                    )
                    return

                try:
                    current_alias = spreadsheet.getAlias(value_cell)
                except Exception:
                    current_alias = None

                if current_alias != param_name:
                    if current_alias:
                        try:
                            spreadsheet.setAlias(value_cell, "")
                        except Exception:
                            pass

                    spreadsheet.setAlias(value_cell, param_name)
                    FreeCAD.Console.PrintMessage(
                        "Lumberjack: Set alias '{}' on cell {}\n".format(
                            param_name, value_cell
                        )
                    )

            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    "Lumberjack: Could not sync alias for row {}: {}\n".format(
                        row_num, e
                    )
                )

        def _is_valid_alias(self, name):
            """Check if name is a valid FreeCAD alias (Python identifier)."""
            if not name:
                return False
            if not (name[0].isalpha() or name[0] == "_"):
                return False
            for char in name:
                if not (char.isalnum() or char == "_"):
                    return False
            import keyword

            if keyword.iskeyword(name):
                return False
            return True

    # Create and install the observer
    obs = ParameterAliasSyncObserver(SPREADSHEET_NAME, PARAM_COLUMN)
    try:
        FreeCAD.addDocumentObserver(obs)
        setattr(FreeCAD, OBSERVER_ATTR, obs)
        FreeCAD.Console.PrintMessage("Lumberjack: Alias sync observer installed\n")
    except Exception as e:
        FreeCAD.Console.PrintWarning(
            "Lumberjack: Failed to install alias sync observer: {}\n".format(e)
        )


# Install observer when this module loads
install_observer()
