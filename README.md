# Lumberjack Workbench

A FreeCAD workbench for woodworking and furniture design.

## Overview

Lumberjack provides tools to streamline furniture design workflows in FreeCAD 1.1+, with a focus on parametric design and efficient project setup.

## Features

### Automatic Alias Synchronization

The workbench installs a document observer that watches the parameter spreadsheet (`p`) and automatically:

- Sets aliases on value cells when you type a parameter name
- Updates aliases when you rename parameters
- Clears aliases when you delete parameter names
- Validates alias names and warns about invalid characters

This means you **never need to manually set aliases** - just type the parameter name in column A and it becomes available as `p.parameter_name` in expressions.

### New Project Command

Creates a new FreeCAD document with a pre-configured parameter spreadsheet:

| Column | Purpose |
|--------|---------|
| **param** (A) | Parameter name - automatically becomes the alias |
| **value** (B) | Parameter value - reference via `p.<param_name>` |
| **description** (C) | Human-readable description |

### Create Panel Command

Creates furniture panels as PartDesign bodies with parametric dimensions:

- **Name**: Label for the body
- **Thickness**: Expression for pad length (default: `p.thickness`)
- **Width**: Expression for sketch width (default: `p.width`)
- **Height**: Expression for sketch height (default: `p.height`)

The dialog uses FreeCAD's native expression input (`Gui::QuantitySpinBox`) with full auto-completion support. All expressions remain editable on the created objects.

### Create Drawer Command

Creates a complete parametric drawer as a `Std_Part` (App::Part) containing PartDesign
bodies — two sides, a front, a back, a bottom, and an optional dedicated drawer front.
The drawer is placed inside the currently active container (if any).

**Box parameters** (always present):

- **Name**: base name for the drawer Part and its bodies.
- **Width / Height / Depth**: outer box dimensions (mm).
- **Side thickness** (`t_side`): thickness of the side/front/back panels.
- **Bottom thickness** (`t_bottom`): thickness of the bottom panel.
- **Bottom offset** (`bottom_v_offset`): raises the bottom panel above the flush position.

**Options:**

- **Box joints** (`overlap_box`): when checked, the box panels are dimensioned to fully
  overlap (box-joint style — the joints themselves are not modelled). When unchecked, the
  sides are shortened by `t_side` for half-lap dado construction. This option stays live
  and editable on the created drawer.
- **Add a dedicated drawer front** (`has_front`): when checked, an extra front panel is
  added with its own parameters:
  - **Front width / Front height** (`width_front`, `height_front`): outer size of the front.
  - **Front thickness** (`t_front`).
  - **Front offset** (`front_v_offset`): positive values move the front *down*; the front's
    lower edge sits at `z = -front_v_offset`.

**Joinery:** The bottom is captured in a groove (width `0.5 * t_bottom`) cut into the inner
faces of the side, front, and back panels ("captured-bottom drawer"), and the bottom panel
carries a matching perimeter rabbet so its upper-half tongue seats into the grooves.

**Coordinate system:** The bottom panel is centered on the Part origin in X (width) and Y
(depth); its bottom face is at `z = 0` (at the default `bottom_v_offset` of 0). The whole
drawer Part is rotated 180° about Z so its front faces the FreeCAD "front" (−Y) view.

**Box joinery orientation:** When **Box joints** is off (half-lap dados) the joinery
orientation depends on whether a drawer front is requested:

- *No drawer front:* the front/back panels run full width and the sides lap into them, so
  the drawer shows a clean, uniform front face.
- *With a drawer front:* the joinery is rotated 90° about Z — the sides run the full depth
  and the front/back lap into them. This puts the corner glue joints in shear when the
  drawer front is pulled, giving a stronger bond against the drawer being pulled out. The
  less tidy front-edge grain this exposes is hidden behind the drawer front.

When **Box joints** is on, all box panels are dimensioned to fully overlap regardless.

**Parameters / data model:** Every parameter is stored as an editable, expression-capable
property. Because FreeCAD raises a cyclic-reference error when a child body references its
parent App::Part's properties, the parameters live on a lightweight sibling holder object
(labelled "… Parameters") inside the drawer Part. Edit values there (or bind them to a
spreadsheet cell, e.g. `p.drawer_width`) and recompute — the panels update accordingly.
The holder has no shape, so it is ignored by the cutlist; each panel body is named after
the drawer (e.g. `Drawer_SideL`, `Drawer_Bottom`) and is picked up by the cutlist generator.

**Notes:**

- All dialog fields (including the checkboxes) remember their last value/expression between
  invocations, to streamline creating several similar drawers in a row.
- `has_front` is applied at creation time: toggling it later on the holder will not add or
  remove the drawer-front body.

**Recreate**: with exactly one existing drawer selected (the Part or anything inside
it), *Create Drawer* opens pre-filled with that drawer's expressions and rebuilds it with
the current code under the same name, container and placement. Use this after updates to
`drawers.py`. Objects referencing the old bodies must be regenerated (a CAM Job: run
*Drawer CAM Job* again). Recreating does not change the remembered "last used" values.

**Bottom joint** (live, decided by `t_bottom < t_side`): a bottom thinner than the sides is
*inserted* at full thickness into a groove `t_bottom` wide that starts `t_bottom` above the
box bottom (no rabbet on the bottom). A bottom at least as thick as the sides is *captured*:
groove `t_bottom / 2` wide starting `t_bottom / 2` up, bottom rabbeted to a `t_bottom / 2`
tongue. `bottom_v_offset` raises the groove in both cases.

### Drawer CAM Job Command

Generates FreeCAD CAM Jobs with operations, hold-down tabs and G-code for drawers made
with *Create Drawer*. Select one or more drawers (a drawer Part, anything inside it, or a
previously generated Job) and run **Drawer CAM Job** (toolbar, pie menu key `G`).

The dialog asks for (all values are remembered):

- **Tool bit** from the CAM toolbit library (`~/.local/share/FreeCAD/v1-1/CamAssets`).
  A single bit is used for everything; it must not be wider than the bottom groove
  (`t_bottom` for an inserted bottom, `t_bottom / 2` for a captured one) or the rabbets,
  otherwise the command refuses with an explanation.
- **Spindle speed, XY feed, plunge feed, step down**.
- **Sheet width / height**: the machine work area, default 630 x 1080 mm. Every panel
  must fit in some orientation (with tool clearance at the right/bottom edges).
- **Clamp height** (default 20 mm): rapids travel 2 mm above it.
- **Origin corner**: *top-left* (zero at the far-left corner, Y negative towards you) or
  *bottom-left* (zero at the near-left corner, Y positive). Panels hug the two sheet edges
  at that corner, which are the clamping edges.
- **Skip drawer fronts** (default on): fronts are plain rectangles, usually of another
  material, and are left out of the Jobs.
- **Post processor** (default `uccnc`) and whether to **write the G-code now**.

Nesting (`nesting.py`): the panels of all selected drawers are grouped by thickness and
packed in columns from the sheet's top-left corner, long side vertical whenever it fits,
rotated otherwise. Neighbouring panels are exactly one tool diameter apart so one cut
separates both and its tabs hold both. Edges flush with the sheet's top and left edges are
not cut at all, so those edges are where the sheet gets clamped; the summary lists the
positions where cuts do reach those edges. Panels that do not fit go onto another sheet.

All Jobs of one run are collected in an `App::Part` container labelled `CAM <name>`,
where `<name>` describes the selected drawers compactly (`naming.py`): shared name parts
are factored out and numbered series are collapsed, e.g. `Kitchen_Left_Top`,
`Kitchen_Left_Bottom`, `Kitchen_Right_Top` become `CAM Kitchen Left Bottom/Top, Right Top`,
and `Drawer001` .. `Drawer003` become `CAM Drawer 001-003`. Selecting the container selects
all its drawers for the command. Per sheet one Job labelled `Job <t>mm sheet <n>` (plus
the drawer names when the sheet holds only some of the container's drawers), each inside
its own sheet frame (`App::Part` labelled `<t>mm sheet <n>`). The frames are displayed
side by side along X, one sheet width plus a 10 % gap apart, so the sheets do not overlap
in the 3D view; the first sheet sits at the origin. Only the display is shifted: every
Job, its stock and operations keep machine coordinates and the G-code is unaffected.

Each sheet frame also gets a **TechDraw page** (`sheetdraw.py`) titled with the name of
the sheet's G-code file, on a blank A4 portrait page (`templates/A4_Portrait_Blank.svg`,
no frame or title block): the title on top, then the sheet with its panels, cut lines,
tabs and the panel label inside every panel, and underneath a legend with one strip per
panel (label and length x width x thickness, dashed cut guides between strips) to cut
off and tape onto the physical parts. Double click the page in the tree to open it;
File > Export or the TechDraw toolbar print it.

- **Coordinates**: zero is the chosen sheet corner, X to the right, Z = 0 on the sheet
  surface; Y is negative (top-left origin) or positive (bottom-left origin). Cut a blank
  at least as large as the reported minimum, square at that corner, and zero the machine
  there.
- The models are the panel bodies laid flat, pocketed face up, at their nested places.
  The stock is the whole sheet.
- **Slot passes** for the bottom groove of the walls, the half-lap end rabbets of the
  full-length walls (not with `overlap_box`) and, for a captured bottom, its four rabbet
  strips. Passes overlap by 50 % of the tool diameter and overshoot open ends.
- **One Slot per merged cut line** (through cut, 0.2 mm into the spoilboard) with a
  **Tags** dress-up: tabs at 1/3 and 2/3 of every panel edge on that line, 10 mm wide,
  3 mm high (at most half the thickness).
- G-code at `<document folder>/<Document>_<container name>_<t>mm_<n>.nc` (also set as the
  Job output).

Running the command again re-nests and **replaces** the Jobs of the selected drawers
(and Jobs they shared with other drawers, so a container is always regenerated as a
whole). Manual changes to those Jobs are lost. The container is kept when the set of
drawers is unchanged, so you may rename it; when the set changes a fresh container with a
generated name replaces the old ones.

Half-lap joinery is not modelled in the drawer bodies; the CAM code synthesises it:
the full-length panels (Front/Back, or SideL/SideR when a drawer front exists) get a
rabbet `t_side` wide x `t_side / 2` deep on their inner face at both ends.

### Sync Aliases Command

Manually sync all aliases in the parameter spreadsheet. Useful if:

- You opened an existing project without the workbench active
- Something went wrong with automatic sync
- You want to batch-update aliases

## Installation

### Option 1: Symlink (Recommended for Development)

```bash
# macOS
ln -s /path/to/FreeCAD/Mod/Lumberjack ~/Library/Application\ Support/FreeCAD/Mod/Lumberjack

# Linux
ln -s /path/to/FreeCAD/Mod/Lumberjack ~/.local/share/FreeCAD/Mod/Lumberjack

# Windows (run as admin)
mklink /D "%APPDATA%\FreeCAD\Mod\Lumberjack" "C:\path\to\FreeCAD\Mod\Lumberjack"
```

### Option 2: Copy

Copy the entire `Lumberjack` folder to your FreeCAD Mod directory:

- **macOS**: `~/Library/Application Support/FreeCAD/Mod/`
- **Linux**: `~/.local/share/FreeCAD/Mod/`
- **Windows**: `%APPDATA%\FreeCAD\Mod\`

## Usage

### Creating a New Project

1. Switch to the Lumberjack workbench
2. Click "New Project" in the toolbar or use **Lumberjack → New Project**
3. A new document is created with a parameter spreadsheet

### Adding Parameters

1. Open the parameter spreadsheet `p` (double-click "Parameters" in the model tree)
2. In column A, type a parameter name (e.g., `shelf_spacing`)
3. The alias is automatically set on the value cell in column B
4. Enter your value in column B
5. Optionally add a description in column C
6. Use the parameter in expressions: `p.shelf_spacing`

### Creating Panels

1. Ensure you have an active document (create a new project first)
2. Click "Create Panel" in the toolbar or use **Lumberjack → Create Panel**
3. Enter a name for the panel
4. Adjust thickness, width, and height expressions as needed
5. Click "Create"

The panel is created as a PartDesign Body with a sketch and pad. All dimensions are expression-driven.

### Creating Drawers

1. Ensure you have an active document and (optionally) activate the container the drawer
   should be placed in.
2. Click "Create Drawer" in the toolbar, use **Lumberjack → Create Drawer**, or press
   **D** in the Lumberjack quick menu.
3. Enter a name and set the box dimensions (width, height, depth, side/bottom thickness).
4. Optionally tick **Box joints** for overlapping panels, and **Add a dedicated drawer
   front** to enable the front-panel fields.
5. Click "Create".

The drawer is created as a `Std_Part` containing the panel bodies. All dimensions stay
editable on the parameter holder inside the Part (and can reference spreadsheet cells), and
every panel body is exposed to the cutlist generator.

### Generating drawer G-code

1. Select the drawers in the tree
2. Run **Drawer CAM Job** (`q,q` then `G`, or the toolbar)
3. Pick the tool bit and check sheet size, clamp height, feeds and post processor
4. Read the summary: minimum blank per sheet and where cuts reach the clamp edges
5. Inspect the Jobs in the CAM workbench (simulator works per operation)
6. The `.nc` files sit next to the document, one per sheet

Headless tests: `test_cam.py` (console) and `test_cam_gui.py` (offscreen GUI), see the
docstrings for the command lines.

## Parameter Naming Rules

Parameter names must be valid Python identifiers:

- ✅ Start with a letter or underscore
- ✅ Contain only letters, numbers, and underscores
- ❌ No spaces or special characters
- ❌ Cannot be Python keywords (`if`, `for`, `class`, etc.)

**Valid examples**: `thickness`, `shelf_1`, `total_width`, `_private`

**Invalid examples**: `1st_shelf`, `total-width`, `my param`, `class`

## Architecture

```
Lumberjack/
├── Init.py           # Runs at FreeCAD start, installs alias sync observer
├── InitGui.py        # Runs at GUI start, registers workbench and commands
├── project.py        # Project setup and spreadsheet creation
├── panels.py         # Panel creation dialog and logic
├── drawers.py        # Parametric drawer (Std_Part with panel bodies) and dialog
├── cam.py            # Drawer CAM Job generation (operations, tabs, G-code)
├── nesting.py        # Sheet nesting and cut-line planning (pure Python)
├── naming.py         # Compact names for CAM containers (pure Python)
├── sheetdraw.py      # SVG for the TechDraw sheet overview pages (pure Python)
├── templates/        # Blank A4 portrait TechDraw template for those pages
├── reload.py         # Development helpers: hot-reload modules, smoke tests
├── test_cam.py       # Headless end-to-end test for cam.py
├── test_cam_gui.py   # Offscreen GUI smoke test for cam.py
└── README.md         # This file
```

## Troubleshooting

### Workbench Doesn't Appear

1. Check that the `Lumberjack` folder is in the correct Mod directory
2. Restart FreeCAD
3. Check the Python console for error messages

### Aliases Not Syncing

1. Ensure the spreadsheet is named `p` (internal name, not label)
2. Check the console for "Lumberjack: Alias sync observer installed" message
3. Try the manual "Sync Parameter Aliases" command
4. Verify parameter names are valid (no spaces, starts with letter)

### Panel Creation Fails

1. Ensure you have an active document
2. Check that the parameter spreadsheet `p` exists with the referenced parameters
3. Look at the console for detailed error messages

## Configuration

Edit `project.py` to customize default parameters:

```python
# Number of parameter rows to create
NUM_ROWS = 10

# Spreadsheet internal name (for expressions)
SPREADSHEET_NAME = "p"

# Spreadsheet display label (shown in tree)
SPREADSHEET_LABEL = "Parameters"

# Default parameters to pre-fill
DEFAULT_PARAMETERS = [
    ("thickness", "18", "Material thickness (mm)"),
    ("width", "600", "Overall width (mm)"),
    ("height", "800", "Overall height (mm)"),
    ("depth", "400", "Overall depth (mm)"),
]
```

## Version History

### v2.0.0

- Complete rewrite for FreeCAD 1.1+
- Automatic alias synchronization via document observer
- Create Panel command with expression-driven dimensions
- Uses native `Gui::QuantitySpinBox` with expression binding

### v1.x (Legacy)

- Original FreeCAD-lumberjack for LinkStage3/Assembly3 fork
- Not compatible with FreeCAD 1.1

## Future Development

Planned features:

- [ ] Panel edge banding options
- [ ] Grain direction indicators
- [ ] Cutlist generation integration
- [ ] Drawer CAM: second bit for the through cut, configurable tabs, nesting of plain panels
- [ ] Material database
- [ ] Hardware library (hinges, slides, etc.)
- [ ] Assembly helpers
- [ ] Project templates

## License

MIT

## Contributing

Contributions are welcome! Please:

1. Follow the existing code style
2. Add tests for new functionality
3. Update documentation
4. Test with FreeCAD 1.1+