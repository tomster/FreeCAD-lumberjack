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


def get_dimensions(parts):
    return [(obj, sorted(utils.dimensions_of_obj(obj), reverse=True)) for obj in parts]


def main():
    dims = get_dimensions(get_parts_for_selection())
    print_cutlist_csv(dims)
    return dims


def print_cutlist_csv(dimensions):
    print("""Length,Width,Qty,Material,Label,Enabled""")
    for part, dimension in dimensions:
        print(
            "%d, %d, 1, %d, %s, true"
            % (
                dimension[0],
                dimension[1],
                dimension[2],
                part.Label,
            )
        )
