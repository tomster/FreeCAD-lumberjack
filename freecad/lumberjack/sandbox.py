# convenience snippets to debug from FreeCAD python console
from freecad.lumberjack import cutlist, panels, utils
from importlib import reload

# then you can select something in the GUI and do
# this
foo = cutlist.main()
foo.write_cutlist_csv()

# after you make changes in code you can then
reload(cutlist)

blub = obj.addConstraint(Sketcher.Constraint("DistanceY", 3, 1, 3, 2, 30.0))

settings = App.getDocument('Unnamed').getObject('Spreadsheet')