import FreeCADGui


class LumberjackWorkbench(FreeCADGui.Workbench):
    "Lumberjack workbench object"
    Icon = """
/* XPM */
static char * infologo_xpm[] = {
"16 16 2 1",
"   c None",
".  c #E55303",
"                ",
"          .     ",
"        .. ..   ",
"       . .   .. ",
"       .  ..  . ",
"      .     ..  ",
"      .     .   ",
"     .      .   ",
"     .     .    ",
"    .      .    ",
"    .     .     ",
"   .      .     ",
"   .     .      ",
"    ... .       ",
"                ",
"                ",
"""
    MenuText = "Lumberjack"
    ToolTip = "Lumberjack workbench"

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(LumberjackWorkbench())
