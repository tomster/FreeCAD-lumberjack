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
(depth); its bottom face is at `z = 0` (at the default `bottom_v_offset` of 0).

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