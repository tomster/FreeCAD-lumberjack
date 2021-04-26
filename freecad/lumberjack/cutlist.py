import FreeCADGui as Gui
import freecad.asm3 as asm3


def get_parts_from_assembly(asm):
    parts = []
    part_group = asm.getPartGroup()
    for child in part_group.LinkedChildren:
        parts.append(child)
    return parts


def get_parts_from_link(link):
    parts = []
    if link.ElementCount > 0:
        for element in link.ElementList:
            parts.append(element.LinkedObject)
    else:
        parts.append(link.LinkedObject)
    return parts


def get_part(obj):
    parts = []
    if is_assembly(obj):
        for item in get_parts_from_assembly(obj.Proxy):
            parts.extend(get_part(item))
    elif obj.isDerivedFrom("App::Link"):
        for item in get_parts_from_link(obj):
            parts.extend(get_part(item))
    else:
        if obj.Visibility:
            parts.append(obj)
        else:
            print("Skipping invisible %s" % obj.Label)
    return parts


def is_assembly(item):
    try:
        if (
            item.Proxy.__class__ is asm3.assembly.Assembly
            or item.__class__ is asm3.assembly.Assembly  # noqa
        ):
            return True
    except AttributeError:
        pass
    return False


def get_parts_for_selection():
    selection = Gui.Selection.getSelection()

    parts = []

    for item in selection:
        print("selection: %s" % item.Label)
        parts.extend(get_part(item))

    return parts


def main():
    parts = get_parts_for_selection()
    for part in parts:
        print("Got: %s" % part.Label)
