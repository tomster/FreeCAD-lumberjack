# CLAUDE.md — Lumberjack workbench

FreeCAD workbench for furniture design: parametric panels and drawers, plus CAM Job
generation (nesting, grooves/rabbets, tabs, G-code) for drawers. The broader development
reference (AppImages, headless patterns, isolation rules, hot reload) lives one level up
in `../../agents.md`; read it once per session. This file holds what is specific to the
code in this folder.

## Runtime and API sources

- Target runtime: FreeCAD **1.1.3** AppImage (`~/Applications/FreeCAD.AppImage`).
- The source checkout `~/Development/freecad/FreeCAD` is on `main`. Read CAM/Path API
  from tag `1.1.3` (`git show 1.1.3:src/Mod/CAM/Path/...`), not from the working tree.
- Toolbits come from the asset manager (`Path.Tool.camassets`), active library at
  `~/.local/share/FreeCAD/v1-1/CamAssets`. The old `Toolbits/` tree in the synced folder
  is not used by FreeCAD.

## Files

| File | Role |
|---|---|
| `InitGui.py` | commands, registration, menu/toolbar/global toolbar/pie menu (restart needed) |
| `panels.py`, `project.py`, `Init.py` | Create Panel, parameter spreadsheet, alias observer |
| `drawers.py` | drawer model (Part + holder + bodies), dialog, recreate, drawer discovery |
| `cam.py` | Drawer CAM Job: validation, sheet Jobs, Slot ops, Tags, post-processing, dialog |
| `nesting.py` | pure-Python sheet nesting and cut-line/tab planning (no FreeCAD imports) |
| `naming.py` | pure-Python compact group names for CAM containers (`python3 naming.py` self-checks) |
| `sheetdraw.py` | pure-Python SVG for the TechDraw sheet pages (`python3 sheetdraw.py > page.svg` previews) |
| `reload.py` | hot-reload helpers (`reload_all()`), smoke helpers |
| `test_cam.py` | headless end-to-end test (drawers, nesting, Jobs, G-code, recreate) |
| `test_cam_gui.py` | offscreen GUI smoke test (dialog widgets, view providers) |
| `drawers.md` | drawer feature spec (the authoritative description of the joinery) |

## Tests (run both before delivering CAM or drawer changes)

```
~/Applications/FreeCAD.AppImage --console --module-path ~/Projects/FreeCAD/Mod/Lumberjack \
    ~/Projects/FreeCAD/Mod/Lumberjack/test_cam.py
QT_QPA_PLATFORM=offscreen ~/Applications/FreeCAD.AppImage --module-path \
    ~/Projects/FreeCAD/Mod/Lumberjack ~/Projects/FreeCAD/Mod/Lumberjack/test_cam_gui.py
```

- Console mode: `print()` is swallowed, use `FreeCAD.Console.PrintMessage`; a script must
  end with `sys.exit()` or FreeCAD waits at the interactive prompt.
- GUI mode: stdout/stderr go to the report view; log to a file (see `test_cam_gui.py`,
  result in `/tmp/lj_cam_gui/RESULT`). The forced shutdown may segfault inside FreeCAD's
  Measure module after the checks ran; that is not a test failure.
- Filter recompute progress noise: `sed -E 's/\([0-9]+ %\)//g; s/Recompute\.*//g'`.
- `nesting.py` can be exercised with plain `python3` (it has a `__main__` self-check).

## Conventions that matter

- Drawer bodies are centred slabs positioned by expression-driven `Placement.Base` only;
  all CAM geometry is computed in body-local coordinates and mapped through the model
  clone's Placement. Keep it that way.
- Everything parametric goes through the `<Part>_Params` holder with expressions
  (ternaries for live switches such as `overlap_box` and `t_bottom < t_side`). The
  bottom rabbet is switched off via an expression on the pocket's `Suppressed` property.
- Drawer detection is by structure (holder with `width`, `t_side`, `t_bottom`,
  `overlap_box`; bodies named `<Part>_<Role>`), see `drawers.drawer_holder` /
  `find_drawer_part`. Jobs carry `LumberjackDrawers`, `LumberjackThickness`,
  `LumberjackSheet`; the `App::Part` container of a run carries `LumberjackCamGroup`
  and `LumberjackDrawers` (so selecting it resolves to its drawers). Jobs are told apart
  from containers by having `Operations`. Each Job sits in a sheet frame (`App::Part`
  with `LumberjackSheetFrame`) whose Placement offsets the display along X
  (`JOB_GAP_FRACTION`); never move Job objects themselves, that would change the G-code.
- Every sheet frame holds a TechDraw page (`cam.make_sheet_page`) with three
  `DrawViewSymbol` views tagged `LumberjackView` = Title/Sheet/Legend. Labels are not
  unique across pages; find views via `cam.page_view(page, role)`.
- A container is reused only when its drawer set equals the run's (keeps user renames);
  otherwise emptied containers are removed and a new one is named via `naming.group_name`.
- CAM layout frame: `u` right, `v` away from the reference edge; mapped to Job XY by
  `cam.layout_to_job` depending on the origin corner setting. Never mix the frames.
- Preferences: `FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Lumberjack")`,
  keys prefixed per feature (`drawer_*`, `cam_*`); save only after validation.
- Commit messages: conventional `feat:`/`fix:` prefixes, concise body.

## CAM API gotchas (FreeCAD 1.1.3)

- Fresh ops bind `StartDepth`/`FinalDepth`/`StepDown` to SetupSheet expressions; call
  `op.setExpression(prop, None)` before assigning values.
- `Slot` custom points need identical Z; force `p2.z = p1.z`.
- `Path.Dressup.Tags.Create` only removes its base op from `Operations.Group` via the GUI
  view provider; do it explicitly (headless would post the cut twice). Tag solids are
  `Width + tool_d` wide; closer tabs get auto-disabled.
- `Job.PostProcessor` is an enumeration of `Path.Preferences.allEnabledPostProcessors()`.
- `Job.Create` adds a default tool controller; clear all tools before adding ours, and
  remove tool bits via `tool.Proxy.onDelete(tool)` (deletes the imported shape body).
- `Job.Proxy.onDelete` only walks `Operations.Group`; delete dress-up bases yourself.
- `App::Part.addObject(job)` pulls the Job's whole tree of *local* links (stock, tools,
  ops, dress-ups, clones) into the container; objects created afterwards stay outside and
  trip the link-scope check ("Link(s) ... go out of the allowed scope"). Add the Job to
  the container last. Global links (Draft clone `Objects`) may cross containers. Adding
  a nested `App::Part` does not extract its children (nested groups keep their own tree).
- Inside a container, `obj.InList` includes the container itself; use `cam._users_of`
  instead of `not obj.InList` when deciding whether a tool bit is still referenced.
- FreeCAD reuses freed internal names (`Job`, `CamJobs`); never identify old objects by
  name across a delete/recreate cycle in tests.
- TechDraw (1.1.3): the shipped default template is a blank A4 landscape without title
  block or editable texts. `DrawViewSymbol` SVGs with `width/height` in `mm` and a
  matching `viewBox` render 1:1 in page millimetres; the view's `X`/`Y` is the symbol
  centre (page origin bottom-left, Y up). Page size is `page.PageWidth/PageHeight`
  (attributes, not methods). Removing a page removes its template. Page exports:
  `TechDrawGui.exportPageAsPdf/Svg(page, path)` (text becomes outlines in SVG). Pages do
  not auto-open MDI windows when created from Python. `frame.addObject(page)` does not
  pull in views/template (their links are not local scope); that is fine.
- Object names that are unit symbols (`H`, `m`, `A`, ...) break expressions.
- Legacy post scripts pop an editor in GUI mode unless `--no-show-editor` is passed.

## Hazards

- This folder is Syncthing-synced with other devices. Stale copies have been pushed over
  the working tree before (`*.sync-conflict-*` files appear). Check `git status` at the
  start of a session and after breaks; restore from git, never merge blindly.
- Recreating a drawer replaces its bodies; anything linking to the old bodies (CAM Jobs,
  measurements) must be regenerated.
