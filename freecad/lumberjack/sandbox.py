# convenience snippets to debug from FreeCAD python console
from freecad.lumberjack import cutlist as cl
from freecad.lumberjack import utils
from importlib import reload

# then you can select something in the GUI and do
# this
foo = cl.main()
foo.write_cutlist_csv()

# after you make changes in code you can then
reload(cl)
