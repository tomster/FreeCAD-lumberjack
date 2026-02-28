# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - InitGui.py

This module runs when FreeCAD GUI starts.
It registers the workbench and its commands.
"""

import FreeCAD
import FreeCADGui

# =============================================================================
# COMMANDS
# =============================================================================


class NewProjectCommand:
    """Command to create a new project with parameter spreadsheet."""

    def GetResources(self):
        return {
            "MenuText": "New Project",
            "ToolTip": "Create a new document with a parameter spreadsheet",
            "Pixmap": "document-new",
        }

    def IsActive(self):
        return True

    def Activated(self):
        """Execute the command."""
        import project

        project.create_new_project()


class SyncAliasesCommand:
    """Command to manually sync all aliases in the parameter spreadsheet."""

    def GetResources(self):
        return {
            "MenuText": "Sync Parameter Aliases",
            "ToolTip": "Manually sync all aliases in the parameter spreadsheet",
            "Pixmap": "view-refresh",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        """Execute the command."""
        import project

        project.sync_all_aliases()


class CreatePanelCommand:
    """Command to create a new furniture panel."""

    def GetResources(self):
        return {
            "MenuText": "Create Panel",
            "ToolTip": "Create a new furniture panel (PartDesign Body with parametric dimensions)",
            "Pixmap": "PartDesign_Body",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        """Execute the command."""
        import panels

        panels.show_create_panel_dialog()


# =============================================================================
# COMMAND REGISTRATION
# =============================================================================

FreeCADGui.addCommand("Lumberjack_NewProject", NewProjectCommand())
FreeCADGui.addCommand("Lumberjack_SyncAliases", SyncAliasesCommand())
FreeCADGui.addCommand("Lumberjack_CreatePanel", CreatePanelCommand())


# =============================================================================
# WORKBENCH
# =============================================================================


class LumberjackWorkbench(FreeCADGui.Workbench):
    """Lumberjack workbench for woodworking and furniture design."""

    MenuText = "Lumberjack"
    ToolTip = "Woodworking and furniture design tools"
    Icon = """
/* XPM */
static char * lumberjack_xpm[] = {
"16 16 4 1",
"   c None",
".  c #8B4513",
"+  c #228B22",
"@  c #FFD700",
"                ",
"      ....      ",
"     ..@@..     ",
"    ..@@@@..    ",
"   ..@@..@@..   ",
"  ..@@....@@..  ",
"  ..@@....@@..  ",
"   ..@@..@@..   ",
"    ..@@@@..    ",
"     ..@@..     ",
"      ....      ",
"       ..       ",
"       ..       ",
"       ..       ",
"       ..       ",
"                "};
"""

    def Initialize(self):
        """Called when the workbench is first activated."""
        # Create menu
        self.appendMenu(
            "Lumberjack",
            [
                "Lumberjack_NewProject",
                "Lumberjack_CreatePanel",
                "Separator",
                "Lumberjack_SyncAliases",
            ],
        )

        # Create toolbar
        self.appendToolbar(
            "Lumberjack",
            [
                "Lumberjack_NewProject",
                "Lumberjack_CreatePanel",
                "Lumberjack_SyncAliases",
            ],
        )

    def Activated(self):
        """Called when switching to this workbench."""
        FreeCAD.Console.PrintMessage("Lumberjack workbench activated\n")

    def Deactivated(self):
        """Called when switching away from this workbench."""
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# Register the workbench
FreeCADGui.addWorkbench(LumberjackWorkbench())
