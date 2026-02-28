# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - InitGui.py

This module runs when FreeCAD GUI starts.
It registers the workbench and its commands.
"""

import FreeCAD
import FreeCADGui


def _lj_qm_msg(msg):
    """Always-on, minimal logging.

    IMPORTANT: FreeCAD's init loader can execute this file in a non-standard namespace,
    so any code that runs later (e.g. via QTimer) must not depend on resolving globals.
    We keep this helper tiny and also provide a per-callback local logger.
    """
    try:
        FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(msg) + "\n")
    except Exception:
        pass


# =============================================================================
# GLOBAL QUICK ACCESS (Q, Q)
# =============================================================================
#
# FreeCAD's built-in shortcut system doesn't support multi-key sequences like "q, q".
# Also, FreeCAD startup order can be a bit sensitive, so we:
#  - do NOT import Qt at module import time
#  - install a global Qt event filter *lazily* via a single-shot timer once the GUI is up
#  - show a popup menu listing Lumberjack commands so you can run them from any workbench

# NOTE: Do not rely on this module global being resolvable later at runtime.
# Some FreeCAD init paths execute InitGui.py in a non-standard namespace.
_QUICK_MENU_COMMANDS = [
    ("Lumberjack_NewProject", "New Project"),
    ("Lumberjack_CreatePanel", "Create Panel"),
    ("Lumberjack_SyncAliases", "Sync Parameter Aliases"),
]

_QUICK_MENU_SEQUENCE_TIMEOUT_MS = 450
_quick_menu_key_filter = None

# Debug switch for diagnosing key delivery / filter installation.
# NOTE: During FreeCAD init, this module can be executed in a non-standard namespace.
# Do not rely on this global always being resolvable at runtime; `_dbg()` reads it defensively.
_LUMBERJACK_QUICKMENU_DEBUG = (
    False  # Keep off by default; enable temporarily when debugging
)


def _lj_qm_msg(msg):
    """Always-on, minimal logging (so you can confirm InitGui ran without enabling debug)."""
    try:
        FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + msg + "\n")
    except Exception:
        pass


def _install_quick_menu_late():
    """
    Schedule the event filter installation for after the GUI event loop starts.

    Avoid referencing global function names in the timer callback, because
    FreeCAD's init loader can execute this module in a non-standard namespace.
    """
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except Exception:
        try:
            import PySide.QtGui as QtWidgets  # type: ignore
            from PySide import QtCore, QtGui  # type: ignore
        except Exception:
            _lj_qm_msg("Qt bindings not available; quick menu disabled")
            return

    def _dbg(msg):
        # Be defensive: during init the module globals may not be resolvable in the expected way.
        try:
            enabled = bool(globals().get("_LUMBERJACK_QUICKMENU_DEBUG", False))
        except Exception:
            enabled = False
        if not enabled:
            return
        try:
            FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + msg + "\n")
        except Exception:
            pass

    def _do_install():
        """Actually install the global event filter."""
        global _quick_menu_key_filter

        # Local logger so we never depend on resolving module globals from this callback.
        def _msg(m):
            try:
                FreeCAD.Console.PrintMessage("Lumberjack QuickMenu: " + str(m) + "\n")
            except Exception:
                pass

        if _quick_menu_key_filter is not None:
            _msg("q,q handler already installed")
            return

        app = None
        try:
            app = QtWidgets.QApplication.instance()
        except Exception:
            app = None

        if app is None:
            _msg("failed to install q,q handler (no QApplication instance)")
            return

        # Bind timeout into the filter instance so we don't rely on module globals later.
        timeout_ms = 450
        try:
            timeout_ms = int(
                globals().get("_QUICK_MENU_SEQUENCE_TIMEOUT_MS", timeout_ms)
            )
        except Exception:
            timeout_ms = 450

        class _QuickMenuKeyFilter(QtCore.QObject):
            def __init__(self, parent=None, timeout_ms=timeout_ms):
                super().__init__(parent)
                self._last_q_ms = None
                self._timeout_ms = int(timeout_ms)

            def eventFilter(self, obj, event):
                try:
                    if event.type() != QtCore.QEvent.KeyPress:
                        return False

                    # Avoid stealing keys while typing in text boxes / expression fields.
                    try:
                        fw = None
                        try:
                            fw = QtWidgets.QApplication.focusWidget()
                        except Exception:
                            fw = None
                        if _is_text_input_widget(fw):
                            self._last_q_ms = None
                            return False
                    except Exception:
                        pass

                    key = None
                    text = ""
                    try:
                        key = int(event.key())
                    except Exception:
                        key = None
                    try:
                        text = str(event.text() or "")
                    except Exception:
                        text = ""

                    is_q = (text.lower() == "q") or (
                        key == int(getattr(QtCore.Qt, "Key_Q"))
                    )
                    if not is_q:
                        self._last_q_ms = None
                        return False

                    # Only react to plain q presses (allow Shift; disallow Ctrl/Alt/Meta)
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

                    # First q: arm sequence but don't consume keypress
                    if (
                        self._last_q_ms is None
                        or (now_ms - self._last_q_ms) > self._timeout_ms
                    ):
                        self._last_q_ms = now_ms
                        return False

                    # Second q within window: trigger and consume only this second q
                    self._last_q_ms = None
                    FreeCADGui.runCommand("Lumberjack_QuickMenu")
                    return True

                except Exception as e:
                    _dbg("eventFilter exception: {}".format(e))
                    self._last_q_ms = None
                    return False

        _quick_menu_key_filter = _QuickMenuKeyFilter(app)
        try:
            app.installEventFilter(_quick_menu_key_filter)
            _msg("installed global q,q handler")
        except Exception as e:
            _quick_menu_key_filter = None
            _msg("failed to install global q,q handler: {}".format(e))

    # Schedule after event loop starts; fall back to immediate install.
    try:
        QtCore.QTimer.singleShot(0, _do_install)
    except Exception:
        _do_install()


def _is_text_input_widget(widget):
    """Return True if widget is likely a text-entry control; used to avoid stealing keys while typing."""
    if widget is None:
        return False
    try:
        # Prefer PySide2 (Qt5)
        from PySide2 import QtWidgets  # type: ignore
    except Exception:
        try:
            import PySide.QtGui as QtWidgets  # type: ignore
        except Exception:
            return False

    try:
        # Line edits / text edits
        if isinstance(widget, QtWidgets.QLineEdit):
            return True
        if hasattr(QtWidgets, "QTextEdit") and isinstance(widget, QtWidgets.QTextEdit):
            return True
        if hasattr(QtWidgets, "QPlainTextEdit") and isinstance(
            widget, QtWidgets.QPlainTextEdit
        ):
            return True

        # Spin boxes accept typing
        if hasattr(QtWidgets, "QAbstractSpinBox") and isinstance(
            widget, QtWidgets.QAbstractSpinBox
        ):
            return True

        # Editable combo box accepts typing
        if hasattr(QtWidgets, "QComboBox") and isinstance(widget, QtWidgets.QComboBox):
            try:
                return bool(widget.isEditable())
            except Exception:
                return True

        # Any widget with an input method tends to accept text
        try:
            if bool(
                widget.testAttribute(getattr(QtWidgets.Qt, "WA_InputMethodEnabled"))
            ):
                return True
        except Exception:
            pass
    except Exception:
        return False

    return False


def _show_lumberjack_pie_menu(parent, center_global_pos, commands):
    """Show a small radial (pie) menu around the cursor."""
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except Exception:
        import PySide.QtGui as QtWidgets  # type: ignore
        from PySide import QtCore, QtGui  # type: ignore

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
                b.setText(label)
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
                if ev.key() == QtCore.Qt.Key_Escape:
                    self.close()
                    ev.accept()
                    return
            except Exception:
                pass
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
            except Exception:
                pass

    popup = _PieMenuPopup(parent)
    # Center the popup at cursor position
    top_left = QtCore.QPoint(
        int(center_global_pos.x() - (popup.width() / 2)),
        int(center_global_pos.y() - (popup.height() / 2)),
    )
    popup.move(top_left)
    popup.show()
    popup.activateWindow()
    popup.setFocus()


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
            "ToolTip": "Show Lumberjack pie menu (triggered by q, q)",
            "Pixmap": "view-list-details",
        }

    def IsActive(self):
        return True

    def Activated(self):
        # Self-contained: do not rely on module-level symbols being resolvable at
        # command execution time.
        try:
            from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
        except Exception:
            import PySide.QtGui as QtWidgets  # type: ignore
            from PySide import QtCore, QtGui  # type: ignore

        mw = None
        try:
            mw = FreeCADGui.getMainWindow()
        except Exception:
            mw = None
        if mw is None:
            return

        try:
            center = QtGui.QCursor.pos()
        except Exception:
            center = mw.mapToGlobal(mw.rect().center())

        commands = list(getattr(self, "_commands", []))

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
                    b.setText(label)
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
                    if ev.key() == QtCore.Qt.Key_Escape:
                        self.close()
                        ev.accept()
                        return
                except Exception:
                    pass
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
                except Exception:
                    pass

        popup = _PieMenuPopup(mw)
        top_left = QtCore.QPoint(
            int(center.x() - (popup.width() / 2)),
            int(center.y() - (popup.height() / 2)),
        )
        popup.move(top_left)
        popup.show()
        popup.activateWindow()
        popup.setFocus()


# =============================================================================
# COMMAND REGISTRATION
# =============================================================================

FreeCADGui.addCommand("Lumberjack_NewProject", NewProjectCommand())
FreeCADGui.addCommand("Lumberjack_SyncAliases", SyncAliasesCommand())
FreeCADGui.addCommand("Lumberjack_CreatePanel", CreatePanelCommand())
FreeCADGui.addCommand("Lumberjack_QuickMenu", QuickMenuCommand())

# Install the global q, q key sequence handler after the GUI event loop starts.
# Always emit a minimal message so you can confirm this file ran even when debug is off.
_lj_qm_msg("InitGui loaded; installing global q,q handler")
_install_quick_menu_late()


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
