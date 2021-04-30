from importlib import reload as _reload
import FreeCADGui as Gui
from . import utils


def reload():
    from freecad import lumberjack as this

    _reload(this)


def get_parts_for_selection():
    selection = Gui.Selection.getSelection()

    parts = []

    for item in selection:
        print("selection: %s" % item.Label)
        parts.extend(utils.get_part(item))

    return parts


def main():
    parts = get_parts_for_selection()
    for part in parts:
        print("Got: %s" % part.Label)
