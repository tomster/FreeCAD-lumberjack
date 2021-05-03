from importlib import reload as _reload
import FreeCADGui as Gui
from . import utils


def reload():
    from freecad import lumberjack as this

    _reload(this)


def main():
    list = CutList(Gui.Selection.getSelection())
    return list


class CutList:
    def __init__(self, items):

        self.parts = []
        names = []

        for item in items:
            self.parts.extend(utils.get_part(item))
            names.append(item.Label)

        self.name = "%sCutlist" % "".join(["%s-" % name for name in names])

    def get_dimensions(self):
        return [
            (obj, sorted(utils.dimensions_of_obj(obj), reverse=True))
            for obj in self.parts
        ]

    def print_cutlist_csv(self):
        print("""Length,Width,Qty,Material,Label,Enabled""")
        for part, dimension in self.get_dimensions():
            print(
                "%d, %d, 1, %d,%s, true"
                % (
                    dimension[0],
                    dimension[1],
                    dimension[2],
                    part.Label,
                )
            )

    def __repr__(self):
        print("<%>: %s" % (self.__class__, self.name))
