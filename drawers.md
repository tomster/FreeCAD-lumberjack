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

### box

the box can either be constructed using half lap dados (using half of the thickness `t_side`)
optionally, the user can indicate that it should be built using box joints. in this case we don't compute the joints themselve but simply dimension the panels of the box so that they all fully overlap.

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
beneath those is a checkbox `overlap_box` - if it is set to true, the box shall be considered to be made via box joints and the dimensions of the box parts shall overlap, otherwise they need to be dimensioned to consider the joinery.
beneath those is a checkbox `has_front`. the value for that is intitially false, but shall be remembered between invocations, i.e. if the user sets it to true, the next drawer shall have that value as default.
this must be true for all fields, actually - so that they retain the value (or expression) from the previous invocation, i.e. to streamline creation of multiple drawers with similar dimensions.
if the checkbox is set to true, additional input fields for `height_front`, `width_front`, `t_front` and `front_v_offset` shall be activated.
like with the other features that create an object, this, too, shall create the part inside any currently selected container.
all input fields representing sizes should be set to support dimensions in mm explicitly.
