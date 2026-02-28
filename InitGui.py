# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - InitGui.py

This module runs when FreeCAD GUI starts.
It registers the workbench and its commands.

Additionally, this workbench installs a global toolbar named
"Lumberjack QuickMenu" so you can access Lumberjack commands from any
workbench.

NOTE: FreeCAD 1.1's Customize→Keyboard does not reliably dispatch multi-stroke
(shortcut sequences like "q, q") for Python commands in all builds, so we also
install a minimal, safe Qt event filter that detects q,q globally and launches
`Lumberjack_QuickMenu` everywhere except while typing in input fields.
"""

import FreeCAD
import FreeCADGui


def _lj_qm_msg(msg):
    """Minimal logging helper."""
    try:
        FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(msg) + "\n")
    except Exception:
        pass


def _lj_qm_debug_enabled():
    """Return True if verbose QuickMenu debug logging is enabled."""
    try:
        p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Lumberjack")
        return bool(p.GetBool("QuickMenuDebug", False))
    except Exception:
        return False


def _lj_qm_dbg(msg):
    """Debug logging gated behind a preference flag."""
    if not _lj_qm_debug_enabled():
        return
    try:
        FreeCAD.Console.PrintMessage("Lumberjack QuickMenu DEBUG: " + str(msg) + "\n")
    except Exception:
        pass


def _lj_qm_msg(msg):
    """Minimal logging helper."""
    try:
        FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(msg) + "\n")
    except Exception:
        pass


def _install_global_toolbar_late():
    """Install a global toolbar in the main window after GUI startup.

    We avoid importing Qt at module import time and schedule installation
    on the event loop to make startup robust.
    """
    try:
        from PySide2 import QtCore, QtWidgets  # type: ignore
    except Exception:
        try:
            import PySide.QtGui as QtWidgets  # type: ignore
            from PySide import QtCore  # type: ignore
        except Exception:
            _lj_qm_msg("Qt bindings not available; cannot install global toolbar")
            return

    def _do_install():
        # Local logger: do not depend on resolving globals later.
        def _msg(m):
            try:
                FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(m) + "\n")
            except Exception:
                pass

        try:
            # Main window is the QMainWindow instance.
            mw = None
            try:
                mw = FreeCADGui.getMainWindow()
            except Exception:
                mw = None

            if mw is None:
                _msg("main window not available; toolbar not installed")
                return

            toolbar_name = "Lumberjack QuickMenu"

            # Look for an existing toolbar by objectName to avoid duplicates.
            existing = None
            try:
                for tb in mw.findChildren(QtWidgets.QToolBar):
                    try:
                        if tb.objectName() == toolbar_name:
                            existing = tb
                            break
                    except Exception:
                        pass
            except Exception:
                existing = None

            if existing is None:
                tb = QtWidgets.QToolBar(toolbar_name, mw)
                tb.setObjectName(toolbar_name)
                mw.addToolBar(tb)
            else:
                tb = existing

            # Ensure the toolbar has the right actions (idempotent install).
            try:
                tb.clear()
            except Exception:
                # If clear isn't available, remove actions manually.
                try:
                    for a in list(tb.actions()):
                        tb.removeAction(a)
                except Exception:
                    pass

            # Add actions that run FreeCAD commands.
            def _add_cmd(cmd_name, text=None):
                act = QtWidgets.QAction(tb)
                act.setText(text or cmd_name)
                act.triggered.connect(
                    lambda checked=False, c=cmd_name: FreeCADGui.runCommand(c)
                )
                tb.addAction(act)

            _add_cmd("Lumberjack_QuickMenu", "QuickMenu")
            tb.addSeparator()
            _add_cmd("Lumberjack_NewProject", "New Project")
            _add_cmd("Lumberjack_CreatePanel", "Create Panel")
            _add_cmd("Lumberjack_SyncAliases", "Sync Parameter Aliases")

            _msg("installed global toolbar: {}".format(toolbar_name))
        except Exception as e:
            _msg("failed to install global toolbar: {}".format(e))

    try:
        QtCore.QTimer.singleShot(0, _do_install)
    except Exception:
        _do_install()


def _install_global_qq_shortcut_late():
    """Install a minimal global q,q detector that launches Lumberjack_QuickMenu.

    Requirements:
    - Works from any workbench.
    - Does NOT interfere while typing in input fields.
    - Single q does nothing.
    - Holding q does nothing.
    """

    try:
        from PySide2 import QtCore, QtWidgets  # type: ignore
    except Exception:
        try:
            import PySide.QtGui as QtWidgets  # type: ignore
            from PySide import QtCore  # type: ignore
        except Exception:
            _lj_qm_msg("Qt bindings not available; cannot install q,q shortcut")
            return

    def _looks_like_text_input(w):
        if w is None:
            return False
        try:
            # Common Qt inputs
            if hasattr(QtWidgets, "QLineEdit") and isinstance(w, QtWidgets.QLineEdit):
                return True
            if hasattr(QtWidgets, "QTextEdit") and isinstance(w, QtWidgets.QTextEdit):
                return True
            if hasattr(QtWidgets, "QPlainTextEdit") and isinstance(
                w, QtWidgets.QPlainTextEdit
            ):
                return True
            if hasattr(QtWidgets, "QAbstractSpinBox") and isinstance(
                w, QtWidgets.QAbstractSpinBox
            ):
                return True
            if hasattr(QtWidgets, "QComboBox") and isinstance(w, QtWidgets.QComboBox):
                try:
                    return bool(w.isEditable())
                except Exception:
                    return True
        except Exception:
            pass

        # FreeCAD custom widgets: detect by class name heuristics
        try:
            mo = w.metaObject()
            cls = str(mo.className()) if mo else ""
            cls_l = cls.lower()
            if any(
                s in cls_l
                for s in (
                    "expression",
                    "quantity",
                    "lineedit",
                    "textedit",
                    "editor",
                    "input",
                )
            ):
                return True
        except Exception:
            pass

        # Focus proxy recursion (some compound widgets proxy to line edits)
        try:
            fp = w.focusProxy()
            if fp is not None and fp is not w:
                return _looks_like_text_input(fp)
        except Exception:
            pass

        return False

    def _do_install():
        # Local logger: this callback runs later (via QTimer) and must not depend on
        # resolving module-level globals.
        def _msg(m):
            try:
                FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(m) + "\n")
            except Exception:
                pass

        app = None
        try:
            app = QtWidgets.QApplication.instance()
        except Exception:
            app = None

        if app is None:
            _msg("failed to install q,q shortcut (no QApplication instance)")
            return

        # Hold a strong ref on the QApplication object so the filter isn't GC'd.
        # (We can't rely on module globals being resolvable later in all execution paths.)
        try:
            existing = getattr(app, "_lumberjackQuickMenuQQFilter", None)
            if existing is not None:
                _msg("q,q shortcut already installed")
                return
        except Exception:
            pass

        class _QQFilter(QtCore.QObject):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._last_q_ms = None
                self._timeout_ms = 450
                self._min_delta_ms = 80

            def eventFilter(self, obj, event):
                try:
                    # Ignore auto-repeat (holding key)
                    try:
                        if hasattr(event, "isAutoRepeat") and event.isAutoRepeat():
                            return False
                    except Exception:
                        pass

                    # Use KeyRelease to avoid multiple KeyPress events from a single physical press
                    if event.type() != QtCore.QEvent.KeyRelease:
                        return False

                    # Never intercept while typing
                    try:
                        fw = QtWidgets.QApplication.focusWidget()
                    except Exception:
                        fw = None
                    if _looks_like_text_input(fw):
                        self._last_q_ms = None
                        return False

                    # Identify q
                    try:
                        key = int(event.key())
                    except Exception:
                        key = None
                    try:
                        txt = str(event.text() or "").lower().strip()
                    except Exception:
                        txt = ""

                    if not ((txt == "q") or (key == int(getattr(QtCore.Qt, "Key_Q")))):
                        self._last_q_ms = None
                        return False

                    # Disallow Ctrl/Alt/Meta modifiers
                    try:
                        disallowed = (
                            QtCore.Qt.ControlModifier
                            | QtCore.Qt.AltModifier
                            | QtCore.Qt.MetaModifier
                        )
                        if int(event.modifiers()) & int(disallowed):
                            self._last_q_ms = None
                            return False
                    except Exception:
                        pass

                    # Timestamp
                    try:
                        now_ms = int(QtCore.QTime.currentTime().msecsSinceStartOfDay())
                    except Exception:
                        import time

                        now_ms = int(time.time() * 1000)

                    if self._last_q_ms is None:
                        self._last_q_ms = now_ms
                        return False

                    dt = now_ms - self._last_q_ms
                    if dt < self._min_delta_ms:
                        # Too fast: treat as noise/hold
                        return False
                    if dt <= 0 or dt > self._timeout_ms:
                        # Restart sequence
                        self._last_q_ms = now_ms
                        return False

                    # Trigger
                    self._last_q_ms = None
                    FreeCADGui.runCommand("Lumberjack_QuickMenu")
                    return True
                except Exception:
                    self._last_q_ms = None
                    return False

        filt = _QQFilter(app)
        try:
            app.installEventFilter(filt)
            setattr(app, "_lumberjackQuickMenuQQFilter", filt)
            _msg("installed global q,q shortcut handler")
        except Exception as e:
            _msg("failed to install q,q shortcut handler: {}".format(e))

    try:
        QtCore.QTimer.singleShot(0, _do_install)
    except Exception:
        _do_install()


# =============================================================================
# COMMANDS
# =============================================================================


class NewProjectCommand:
    """Command to create a new project with parameter spreadsheet."""

    def GetResources(self):
        return {
            "MenuText": "New Project",
            "ToolTip": "Create a new document with a parameter spreadsheet",
            "Pixmap": "document-new",
        }

    def IsActive(self):
        return True

    def Activated(self):
        """Execute the command."""
        import project

        project.create_new_project()


class SyncAliasesCommand:
    """Command to manually sync all aliases in the parameter spreadsheet."""

    def GetResources(self):
        return {
            "MenuText": "Sync Parameter Aliases",
            "ToolTip": "Manually sync all aliases in the parameter spreadsheet",
            "Pixmap": "view-refresh",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        """Execute the command."""
        import project

        project.sync_all_aliases()


class CreatePanelCommand:
    """Command to create a new furniture panel."""

    def GetResources(self):
        return {
            "MenuText": "Create Panel",
            "ToolTip": "Create a new furniture panel (PartDesign Body with parametric dimensions)",
            "Pixmap": "PartDesign_Body",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        """Execute the command."""
        import panels

        panels.show_create_panel_dialog()


class QuickMenuCommand:
    """Global popup menu for quick access to Lumberjack commands."""

    def __init__(self):
        # Store commands on the instance so command execution doesn't depend on
        # module-level globals being resolvable later.
        self._commands = [
            ("Lumberjack_NewProject", "New Project"),
            ("Lumberjack_CreatePanel", "Create Panel"),
            ("Lumberjack_SyncAliases", "Sync Parameter Aliases"),
        ]

    def GetResources(self):
        return {
            "MenuText": "Lumberjack Quick Menu",
            "ToolTip": "Show Lumberjack pie menu (bind a shortcut in Tools → Customize… → Keyboard)",
            "Pixmap": "view-list-details",
        }

    def IsActive(self):
        return True

    def Activated(self):
        # FreeCAD can execute InitGui.py in a non-standard namespace where module-level
        # symbols are not resolvable at command activation time. Use a local no-op
        # debug function to avoid NameError.
        def _dbg(_msg):
            return

        _dbg("QuickMenuCommand.Activated() called")

        # Self-contained: do not rely on module-level symbols being resolvable later at
        # command execution time.
        try:
            from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore

            _lj_qm_dbg("Using PySide2 Qt bindings")
        except Exception as e:
            _dbg("PySide2 import failed: {}".format(e))
            try:
                import PySide.QtGui as QtWidgets  # type: ignore
                from PySide import QtCore, QtGui  # type: ignore

                _dbg("Using PySide (Qt4) bindings")
            except Exception as e2:
                _dbg("PySide import failed: {}".format(e2))
                return

        mw = None
        try:
            mw = FreeCADGui.getMainWindow()
        except Exception as e:
            _dbg("FreeCADGui.getMainWindow() failed: {}".format(e))
            mw = None
        if mw is None:
            _dbg("No main window; cannot show pie menu")
            return

        try:
            center = QtGui.QCursor.pos()
        except Exception as e:
            _dbg("QCursor.pos() failed: {}".format(e))
            center = mw.mapToGlobal(mw.rect().center())

        commands = list(getattr(self, "_commands", []))
        _dbg("Pie menu commands: {}".format([c for c, _ in commands]))

        class _PieMenuPopup(QtWidgets.QWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowFlags(
                    QtCore.Qt.Tool
                    | QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.WindowStaysOnTopHint
                )
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)

                self._radius = 56
                self._button_size = 44
                self._commands = list(commands)

                size = (self._radius * 2) + (self._button_size * 2)
                self.resize(size, size)

                self._buttons = []
                for cmd_name, label in self._commands:
                    b = QtWidgets.QToolButton(self)
                    hint = ""
                    if cmd_name == "Lumberjack_NewProject":
                        hint = " (N)"
                    elif cmd_name == "Lumberjack_CreatePanel":
                        hint = " (P)"
                    b.setText(label + hint)
                    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
                    b.setAutoRaise(True)
                    b.setCursor(QtCore.Qt.PointingHandCursor)
                    b.setProperty("_lj_cmd", cmd_name)
                    b.clicked.connect(self._on_click)
                    b.resize(self._button_size * 2, self._button_size)
                    self._buttons.append(b)

                self._layout_buttons()

            def _layout_buttons(self):
                # Place buttons at 120° increments (top, bottom-left, bottom-right)
                w = self.width()
                h = self.height()
                cx = w // 2
                cy = h // 2

                import math

                angles = [-90, 150, 30]  # degrees
                for i, b in enumerate(self._buttons):
                    ang = angles[i % len(angles)]
                    rad = math.radians(ang)
                    x = int(cx + self._radius * math.cos(rad) - (b.width() // 2))
                    y = int(cy + self._radius * math.sin(rad) - (b.height() // 2))
                    b.move(x, y)

            def _on_click(self):
                try:
                    b = self.sender()
                    cmd = b.property("_lj_cmd")
                except Exception:
                    cmd = None
                self.close()
                if cmd:
                    FreeCADGui.runCommand(cmd)

            def keyPressEvent(self, ev):
                try:
                    k = ev.text() or ""
                    k = k.lower().strip()

                    if ev.key() == QtCore.Qt.Key_Escape:
                        self.close()
                        ev.accept()
                        return

                    # Single-key shortcuts while the pie menu is open:
                    #  - n: New Project
                    #  - p: Create Panel
                    if k == "n":
                        self.close()
                        FreeCADGui.runCommand("Lumberjack_NewProject")
                        ev.accept()
                        return
                    if k == "p":
                        self.close()
                        FreeCADGui.runCommand("Lumberjack_CreatePanel")
                        ev.accept()
                        return
                except Exception as e:
                    _dbg("Pie menu keyPressEvent exception: {}".format(e))
                super().keyPressEvent(ev)

            def focusOutEvent(self, ev):
                # Close when losing focus (click elsewhere)
                try:
                    self.close()
                except Exception:
                    pass
                super().focusOutEvent(ev)

            def paintEvent(self, ev):
                # Draw a subtle circular background ring
                try:
                    painter = QtGui.QPainter(self)
                    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                    rect = self.rect().adjusted(8, 8, -8, -8)
                    color = QtGui.QColor(20, 20, 20, 180)
                    painter.setBrush(color)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.drawEllipse(rect)
                except Exception as e:
                    _dbg("Pie menu paintEvent exception: {}".format(e))

        popup = _PieMenuPopup(mw)

        # Center the popup at cursor position, but clamp to the current screen so it
        # never opens off-screen (macOS can report cursor positions near edges which
        # would yield negative coords).
        desired_x = int(center.x() - (popup.width() / 2))
        desired_y = int(center.y() - (popup.height() / 2))

        clamped_x = desired_x
        clamped_y = desired_y
        try:
            screen = QtWidgets.QApplication.screenAt(center)
            if screen is None:
                screen = QtWidgets.QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                clamped_x = max(
                    int(geo.left()),
                    min(desired_x, int(geo.right()) - int(popup.width()) + 1),
                )
                clamped_y = max(
                    int(geo.top()),
                    min(desired_y, int(geo.bottom()) - int(popup.height()) + 1),
                )
        except Exception:
            pass

        top_left = QtCore.QPoint(clamped_x, clamped_y)
        popup.move(top_left)
        popup.show()
        popup.raise_()
        try:
            popup.activateWindow()
        except Exception:
            pass
        popup.setFocus()
        _dbg(
            "Pie menu popup shown at {},{} (desired {},{})".format(
                top_left.x(), top_left.y(), desired_x, desired_y
            )
        )


# =============================================================================
# COMMAND REGISTRATION
# =============================================================================

FreeCADGui.addCommand("Lumberjack_NewProject", NewProjectCommand())
FreeCADGui.addCommand("Lumberjack_SyncAliases", SyncAliasesCommand())
FreeCADGui.addCommand("Lumberjack_CreatePanel", CreatePanelCommand())
FreeCADGui.addCommand("Lumberjack_QuickMenu", QuickMenuCommand())

# Install a global toolbar (visible from any workbench).
_lj_qm_msg("InitGui loaded; installing global toolbar")
_install_global_toolbar_late()

# Install global q,q quick access (works everywhere except while typing).
_install_global_qq_shortcut_late()


# =============================================================================
# WORKBENCH
# =============================================================================


class LumberjackWorkbench(FreeCADGui.Workbench):
    """Lumberjack workbench for woodworking and furniture design."""

    MenuText = "Lumberjack"
    ToolTip = "Woodworking and furniture design tools"
    Icon = """
/* XPM */
static char * lumberjack_xpm[] = {
"16 16 4 1",
"   c None",
".  c #8B4513",
"+  c #228B22",
"@  c #FFD700",
"                ",
"      ....      ",
"     ..@@..     ",
"    ..@@@@..    ",
"   ..@@..@@..   ",
"  ..@@....@@..  ",
"  ..@@....@@..  ",
"   ..@@..@@..   ",
"    ..@@@@..    ",
"     ..@@..     ",
"      ....      ",
"       ..       ",
"       ..       ",
"       ..       ",
"       ..       ",
"                "};
"""

    def Initialize(self):
        """Called when the workbench is first activated."""
        # Create menu
        self.appendMenu(
            "Lumberjack",
            [
                "Lumberjack_NewProject",
                "Lumberjack_CreatePanel",
                "Separator",
                "Lumberjack_SyncAliases",
            ],
        )

        # Create toolbar
        self.appendToolbar(
            "Lumberjack",
            [
                "Lumberjack_NewProject",
                "Lumberjack_CreatePanel",
                "Lumberjack_SyncAliases",
            ],
        )

    def Activated(self):
        """Called when switching to this workbench."""
        FreeCAD.Console.PrintMessage("Lumberjack workbench activated\n")

    def Deactivated(self):
        """Called when switching away from this workbench."""
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# Register the workbench
FreeCADGui.addWorkbench(LumberjackWorkbench())
