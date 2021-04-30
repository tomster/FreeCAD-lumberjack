import Draft
import FreeCAD
from FreeCAD import Vector, Rotation
import freecad.asm3 as asm3
import math
import DraftGeomUtils
import DraftVecUtils


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


def get_area(face):
    return face.Area


def get_faces_max(faces):
    faces = sorted(faces, key=get_area, reverse=True)
    facesMax = faces[0:4]
    return facesMax


def get_perpendicular_tuples(faces):
    listeCouple = []
    lenfaces = len(faces)
    faces.append(faces[0])
    for n in range(lenfaces):
        norm2 = faces[n + 1].normalAt(0, 0)
        norm1 = faces[n].normalAt(0, 0)
        norm0 = faces[n - 1].normalAt(0, 0)
        if abs(round(math.degrees(DraftVecUtils.angle(norm1, norm0)))) == 90.0:
            listeCouple.append([faces[n], faces[n - 1]])
        if abs(round(math.degrees(DraftVecUtils.angle(norm1, norm2)))) == 90.0:
            listeCouple.append([faces[n], faces[n + 1]])
    return listeCouple


def dimensions_of_shape(shape, name=None):
    """ returns the normalized width, length and height of the given shape
    as a tuple of integers by creating a temporary body which is rotated
    to be perpendicular to the XY plane and then measured.
    """
    if name is None:
        name = "temp_shape"
    # taken from
    # https://github.com/j-wiedemann/FreeCAD-Timber/blob/master/TimberListing.py
    obj = FreeCAD.ActiveDocument.addObject("Part::Feature", name)
    obj.Shape = shape
    obj.Placement.Base = FreeCAD.Vector(0.0, 0.0, 0.0)
    obj.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 0.0)
    FreeCAD.ActiveDocument.recompute()
    # Get the face to align with XY plane
    faces = obj.Shape.Faces
    facesMax = get_faces_max(obj.Shape.Faces)
    perpendicular_tuples = get_perpendicular_tuples(facesMax)
    # Get the normal of this face
    nv1 = perpendicular_tuples[0][0].normalAt(0, 0)
    # Get the goal normal vector
    zv = Vector(0, 0, 1)
    # Find and apply a rotation to the object to align face
    pla = obj.Placement
    rot = pla.Rotation
    rot1 = Rotation(nv1, zv)
    newrot = rot.multiply(rot1)
    pla.Rotation = newrot
    # Get the face to align with XY plane
    faces = obj.Shape.Faces
    facesMax = get_faces_max(faces)
    perpendicular_tuples = get_perpendicular_tuples(facesMax)
    # Get the longest edge from aligned face
    maxLength = 0.0
    for e in perpendicular_tuples[0][0].Edges:
        if e.Length > maxLength:
            maxLength = e.Length
            edgeMax = e
    # Get the angle between edge and X axis and rotate object
    vec = DraftGeomUtils.vec(edgeMax)
    vecZ = FreeCAD.Vector(vec[0], vec[1], 0.0)
    pos2 = obj.Placement.Base
    rotZ = math.degrees(DraftVecUtils.angle(vecZ, FreeCAD.Vector(1.0, 0.0, 0.0), zv))
    Draft.rotate([obj], rotZ, pos2, axis=zv, copy=False)
    bb = obj.Shape.BoundBox
    movex = bb.XMin * -1
    movey = bb.YMin * -1
    movez = bb.ZMin * -1
    Draft.move([obj], FreeCAD.Vector(movex, movey, movez))
    FreeCAD.ActiveDocument.recompute()
    # Get the boundbox
    dimensions = (
        int(obj.Shape.BoundBox.YLength),
        int(obj.Shape.BoundBox.ZLength),
        int(obj.Shape.BoundBox.XLength),
    )
    FreeCAD.ActiveDocument.removeObject(name)
    return dimensions
