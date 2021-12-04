from importlib import reload as _reload
import FreeCADGui as Gui
import FreeCAD as App
from os import path
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
            self.parts.extend(utils.get_part_recursive(item))
            names.append(item.Label)

        self.name = "%sCutlist" % "".join(["%s-" % name for name in names])

    def get_dimensions(self):
        return [
            (name, sorted(utils.dimensions_of_obj(obj), reverse=True))
            for obj, name in self.parts
        ]

    def _cutlist_csv(self):
        yield """Length,Width,Qty,Material,Label,Enabled"""
        for name, dimension in self.get_dimensions():
            yield "%d,%d,1,%d,%s,true" % (
                dimension[0],
                dimension[1],
                dimension[2],
                name,
            )

    def write_cutlist_csv(self):
        with open(
            path.join(path.dirname(App.ActiveDocument.FileName), "%s.csv" % self.name),
            "w",
        ) as outfile:
            for line in self._cutlist_csv():
                outfile.writelines(line + "\n")

    def __repr__(self):
        return "<%s>: %s" % (self.__class__, self.name)
