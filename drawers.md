we're writing a new user facing feature called 'Create Drawer' for the [@Lumberjack](file:///home/tomster/Projects/FreeCAD/Mod/Lumberjack/) workbench in analogy to the existing 'Create Panel' feature for this workbench as described in xxx such that:

- it will receive an entry in the global toolbar
- when activated it will present a popup menu that allows to specify all relevant parameters for creating a drawer.
- multiple variants of drawers will be supported. 
- all variants share some common aspects but different styles may have additional parameters

## common characteristics of a drawer

- the main parameters of a drawer are
  - width, in mm `width`
  - height, in mmm `height`
  - depth, in mm `depth`
  - thickness of the sides, in mm `t_side`
  - thickness of the bottom, in mm `t_bottom`

this represents the "box", i.e. the main body of the drawer

additionally, there may be a dedicated "front" present - an additional panel
  - heigher and wider than the box `height_front` and `width_front`
  - with its own thickness `t_front`
  - horizontally centered
  - with a specific vertical bottom offset, in mm, defining the distance of its lower edge to the lower edge of the box `front_v_offset`

- a drawer shall be defined as a `Std_Part` containing PartDesign bodies in such a way that they contain 
  - two equal panels representing the sides of the drawer
  - two equal panels representing the front and back of the drawer, of the same height as the sides
  - one panel representing the bottom of the drawer
  - and optional panel representing the drawer front

## joinery

### bottom

the bottom is inserted into the box by slotting it into a groove which is cut into the insides of the front and side panels.
the groove depth (into the wall) is `0.5 * t_side`. which joint is used depends on the thicknesses (decided live by the expression `t_bottom < t_side`):

- **inserted bottom** (`t_bottom < t_side`): the bottom keeps its full thickness and is inserted as-is. the groove is `t_bottom` wide and begins `t_bottom` above the box bottom (a 6 mm dado beginning at 6 mm for a 6 mm bottom). no rabbet on the bottom, so no bit narrower than `t_bottom / 2` is needed and the joint is stronger.
- **captured bottom** (`t_bottom >= t_side`): the width of the groove is half the thickness of the bottom, `0.5 * t_bottom`, and it begins `0.5 * t_bottom` above the box bottom (flush bottom). the bottom is rabbeted around its perimeter to a `0.5 * t_bottom` tongue.

optionally the vertical distance can be increased using a parameter `bottom_v_offset`

the **back**'s groove is open towards its lower edge (it runs from the bottom of the panel up to the top of the groove); the front's and the sides' grooves are closed. this fixes the assembly order: glue up the sides and the front, slide the bottom in from the back, then drop the back in. front and back are therefore not identical parts.

### box

the corner joinery is selected per drawer with the `corner_joint` enumeration (live-editable on the created drawer; the list is append-only because saved drawers bake the indices into their expressions). the orientation is the same for every variant: the **sides run the full `depth`** and carry the corner pocket on their inner face at each end, the **front and back are `t_side` shorter than the `width`** and tuck into the sides. every cut sits on a panel's inner face, so each panel can be machined in a single setup.

- **tongue and dado (recessed)** (default): the sides get a **dado at each end**, `0.5 * t_side` wide and `0.5 * t_side` deep, offset `0.5 * t_side` from the end edge. the front and back get a matching **half-lap** at each end on their *inner* face, `0.5 * t_side` long and `0.5 * t_side` deep; what remains — the outer half of their thickness — is the tongue that slides into the side dados. the joint locates itself during glue-up and every cut is on an inner face, so the whole box comes off the CNC in one setup per panel. the price: the front and back sit `0.5 * t_side` behind the ends of the sides (the sides form a small lip at the front and the back; hidden by a dedicated drawer front, visible without one). interior depth `depth - 3 * t_side`, bottom panel `depth - 2 * t_side` long.
- **tongue and dado (flush)**: the same side dado, but the front and back sit **flush with the side ends**; their tongue is the *inner* half and the lap is on the **outer** face. a lock joint needs the lap and the bottom groove on opposite faces, so this lap cannot be reached with the panel lying inner-face-up on the CNC: the model contains it, but CAM does not machine it and reports it as a manual cut (four straight `0.5 * t_side × 0.5 * t_side` rabbets per drawer, table saw or router table). interior depth `depth - 2 * t_side`, bottom panel `depth - t_side` long.
- **half-lap**: the side pocket widens to `t_side` and runs out to the end edge — a rabbet, `t_side` wide and `0.5 * t_side` deep. the front and back sit in it **flush with the side ends** and get no cut of their own (strictly this is a rabbet joint, only the side is cut; the workbench keeps calling it half-lap). one cut per corner, and the bit only needs to be `<= t_side`. interior depth `depth - 2 * t_side`, bottom panel `depth - t_side` long.
- **overlap**: box joints made by hand. we don't compute the joints themselves but simply dimension the panels so that they all fully overlap (front and back run the full `width`); no corner pocket is cut.

all pockets run the full height of the panel. the sides' end grain shows at the drawer face in every variant unless a dedicated drawer front covers it.

## datamodel

all parameters must be paremeterized, so that the resulting `Std_part` shall have custom attributes that can be altered after creation and the values need to be reflected in the bodies.
note that the parameters / attribues themselves need to be able to be an expression, i.e. referencing the cell of a spreadsheet, so that changes in that are also reflected in the panels.

the resulting bodies must be named with the name of the containing part and need to be exposed/visible to the existing cutlist generation feature of the lumberjack workbench.
the goal is to generate explicitly named parts for all drawers with recognizable names.

## assembly

the drawer should not be implemented as an assembly but instead as individual __Part Design_ bodies that are positioned within the enclosing `Std_part` coordinate system.
the bottom of the drawer should be centered horizontally (along the x and y axises) around the origin of the coordinate system of the part.
the bottom of the bottom should be at 0 (on the z-axis).

## user interface

the panel shall consist of an input field for the name of the drawer at the top.
beneath this are the input fields for the box parameters.
beneath those is a combo box `corner_joint` selecting the corner joinery (tongue and dado / half-lap / overlap, see above); with overlap the box shall be considered to be made via box joints and the dimensions of the box parts shall overlap, otherwise they are dimensioned to consider the joinery.
beneath those is a checkbox `has_front`. the value for that is intitially false, but shall be remembered between invocations, i.e. if the user sets it to true, the next drawer shall have that value as default.
this must be true for all fields, actually - so that they retain the value (or expression) from the previous invocation, i.e. to streamline creation of multiple drawers with similar dimensions.
if the checkbox is set to true, additional input fields for `height_front`, `width_front`, `t_front` and `front_v_offset` shall be activated.
like with the other features that create an object, this, too, shall create the part inside any currently selected container.
all input fields representing sizes should be set to support dimensions in mm explicitly.
