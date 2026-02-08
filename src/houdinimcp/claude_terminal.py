"""
claude_terminal.py — Embedded Claude CLI terminal panel for Houdini.

Provides a PySide2-based panel that runs `claude` (or a configurable command)
inside Houdini's UI. Uses QProcess for subprocess management and a
QPlainTextEdit widget for output display.

Features: CWD selector, font size control, dark/light theme, auto-restart,
tabbed sessions, connection status LED, context injection buttons.

Requires: PySide2 (bundled with Houdini), optionally pyte for ANSI parsing.
"""
import atexit
import os
import re

from PySide2 import QtWidgets, QtCore, QtGui


# ANSI escape stripping — use pyte if available, otherwise regex fallback
try:
    import pyte
    _PYTE_AVAILABLE = True
except ImportError:
    _PYTE_AVAILABLE = False

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07')

THEMES = {
    "dark": {"bg": "#1e1e1e", "fg": "#d4d4d4"},
    "light": {"bg": "#ffffff", "fg": "#1e1e1e"},
}

DEFAULT_FONT_SIZE = 10
MIN_FONT_SIZE = 6
MAX_FONT_SIZE = 24
DEFAULT_SCROLLBACK = 10000


def strip_ansi(text):
    """Remove ANSI escape sequences from text."""
    if _PYTE_AVAILABLE:
        screen = pyte.Screen(200, 50)
        stream = pyte.Stream(screen)
        stream.feed(text)
        return "\n".join(screen.display).rstrip()
    return _ANSI_RE.sub('', text)


class ConnectionStatusLED(QtWidgets.QWidget):
    """Small coloured circle indicating MCP connection status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._connected = False

    def set_connected(self, connected):
        self._connected = connected
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(0, 200, 0) if self._connected else QtGui.QColor(200, 0, 0)
        painter.setBrush(color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(2, 2, 12, 12)
        painter.end()


class TerminalTab(QtWidgets.QWidget):
    """A single terminal session — QProcess + output + input."""

    process_finished = QtCore.Signal(int, str)  # exit_code, tab_name

    def __init__(self, command="claude", cwd=None, parent=None):
        super().__init__(parent)
        self._command = command
        self._cwd = cwd or os.path.expanduser("~")
        self._process = None
        self._font_size = DEFAULT_FONT_SIZE
        self._theme = "dark"
        self._auto_restart = False
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._output = QtWidgets.QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(DEFAULT_SCROLLBACK)
        self._apply_theme()
        layout.addWidget(self._output)

        input_layout = QtWidgets.QHBoxLayout()
        self._input = QtWidgets.QLineEdit()
        self._input.setPlaceholderText("Type a message to Claude...")
        self._input.returnPressed.connect(self._send_input)
        input_layout.addWidget(self._input)

        self._send_btn = QtWidgets.QPushButton("Send")
        self._send_btn.clicked.connect(self._send_input)
        input_layout.addWidget(self._send_btn)

        layout.addLayout(input_layout)

    def _apply_theme(self):
        t = THEMES[self._theme]
        self._output.setFont(QtGui.QFont("Courier", self._font_size))
        self._output.setStyleSheet(f"background-color: {t['bg']}; color: {t['fg']};")

    def set_font_size(self, size):
        self._font_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
        self._apply_theme()

    def set_theme(self, theme):
        if theme in THEMES:
            self._theme = theme
            self._apply_theme()

    def set_scrollback(self, lines):
        self._output.setMaximumBlockCount(max(100, lines))

    def set_auto_restart(self, enabled):
        self._auto_restart = enabled

    def _build_env(self):
        env = QtCore.QProcessEnvironment.systemEnvironment()
        port = os.environ.get("HOUDINIMCP_PORT", "9876")
        env.insert("HOUDINIMCP_PORT", port)
        try:
            import hou
            hip = hou.hipFile.path()
            if hip:
                env.insert("HIP", hip)
            env.insert("HOUDINI_VERSION", hou.applicationVersionString())
        except ImportError:
            pass
        return env

    def start(self):
        """Start the CLI process."""
        self.stop()
        self._output.clear()
        self._output.appendPlainText(f"Starting: {self._command} (cwd: {self._cwd})\n")

        self._process = QtCore.QProcess(self)
        self._process.setProcessEnvironment(self._build_env())
        self._process.setWorkingDirectory(self._cwd)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.start(self._command)

    def stop(self):
        if self._process and self._process.state() != QtCore.QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(3000)

    def is_running(self):
        return self._process is not None and self._process.state() != QtCore.QProcess.NotRunning

    def send_text(self, text):
        """Write text to the process stdin."""
        if self.is_running():
            self._output.appendPlainText(f"> {text}")
            self._process.write((text + "\n").encode("utf-8"))

    def _send_input(self):
        if not self.is_running():
            self._output.appendPlainText("[Not running — click 'New Session' to start]")
            return
        text = self._input.text()
        self._input.clear()
        self.send_text(text)

    def _on_stdout(self):
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._output.appendPlainText(strip_ansi(data))
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_stderr(self):
        data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        self._output.appendPlainText(strip_ansi(data))

    def _on_finished(self, exit_code, exit_status):
        self._output.appendPlainText(f"\n[Process exited with code {exit_code}]")
        self.process_finished.emit(exit_code, "")
        if self._auto_restart and exit_code != 0:
            self._output.appendPlainText("[Auto-restarting...]\n")
            QtCore.QTimer.singleShot(1000, self.start)

    def copy_selection(self):
        self._output.copy()

    def set_cwd(self, cwd):
        self._cwd = cwd


class ClaudeTerminalWidget(QtWidgets.QWidget):
    """Tabbed terminal widget that embeds Claude CLI sessions inside Houdini."""

    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        self._command = command or "claude"
        self._font_size = DEFAULT_FONT_SIZE
        self._theme = "dark"
        self._auto_restart = False
        self._cwd = self._default_cwd()
        self._build_ui()
        atexit.register(self._cleanup)

    @staticmethod
    def _default_cwd():
        try:
            import hou
            hip = hou.hipFile.path()
            if hip:
                return os.path.dirname(hip)
        except ImportError:
            pass
        return os.path.expanduser("~")

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # Toolbar row 1: session controls
        toolbar = QtWidgets.QHBoxLayout()

        self._new_btn = QtWidgets.QPushButton("New Session")
        self._new_btn.clicked.connect(self._new_tab)
        toolbar.addWidget(self._new_btn)

        self._restart_btn = QtWidgets.QPushButton("Restart")
        self._restart_btn.clicked.connect(self._restart_current)
        toolbar.addWidget(self._restart_btn)

        self._close_tab_btn = QtWidgets.QPushButton("Close Tab")
        self._close_tab_btn.clicked.connect(self._close_current_tab)
        toolbar.addWidget(self._close_tab_btn)

        toolbar.addWidget(QtWidgets.QLabel("CWD:"))
        self._cwd_edit = QtWidgets.QLineEdit(self._cwd)
        self._cwd_edit.setMinimumWidth(120)
        self._cwd_edit.editingFinished.connect(self._on_cwd_changed)
        toolbar.addWidget(self._cwd_edit)

        self._cwd_browse = QtWidgets.QPushButton("...")
        self._cwd_browse.setFixedWidth(30)
        self._cwd_browse.clicked.connect(self._browse_cwd)
        toolbar.addWidget(self._cwd_browse)

        toolbar.addStretch()

        # Font size
        self._font_down = QtWidgets.QPushButton("A-")
        self._font_down.setFixedWidth(30)
        self._font_down.clicked.connect(lambda: self._change_font_size(-1))
        toolbar.addWidget(self._font_down)

        self._font_label = QtWidgets.QLabel(str(self._font_size))
        self._font_label.setFixedWidth(20)
        self._font_label.setAlignment(QtCore.Qt.AlignCenter)
        toolbar.addWidget(self._font_label)

        self._font_up = QtWidgets.QPushButton("A+")
        self._font_up.setFixedWidth(30)
        self._font_up.clicked.connect(lambda: self._change_font_size(1))
        toolbar.addWidget(self._font_up)

        # Theme toggle
        self._theme_btn = QtWidgets.QPushButton("Light")
        self._theme_btn.setFixedWidth(50)
        self._theme_btn.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self._theme_btn)

        # Auto-restart toggle
        self._auto_restart_cb = QtWidgets.QCheckBox("Auto-restart")
        self._auto_restart_cb.toggled.connect(self._toggle_auto_restart)
        toolbar.addWidget(self._auto_restart_cb)

        self._led = ConnectionStatusLED()
        toolbar.addWidget(self._led)

        layout.addLayout(toolbar)

        # Toolbar row 2: context injection
        ctx_toolbar = QtWidgets.QHBoxLayout()

        self._send_sel_btn = QtWidgets.QPushButton("Send Selection")
        self._send_sel_btn.setToolTip("Send selected node paths to Claude")
        self._send_sel_btn.clicked.connect(self._send_selection)
        ctx_toolbar.addWidget(self._send_sel_btn)

        self._send_scene_btn = QtWidgets.QPushButton("Send Scene Info")
        self._send_scene_btn.setToolTip("Send scene summary to Claude")
        self._send_scene_btn.clicked.connect(self._send_scene_info)
        ctx_toolbar.addWidget(self._send_scene_btn)

        ctx_toolbar.addStretch()
        layout.addLayout(ctx_toolbar)

        # Tabbed terminal area
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

    # ---- Tab management ----

    def _new_tab(self):
        tab = TerminalTab(command=self._command, cwd=self._cwd, parent=self)
        tab.set_font_size(self._font_size)
        tab.set_theme(self._theme)
        tab.set_auto_restart(self._auto_restart)
        idx = self._tabs.addTab(tab, f"Session {self._tabs.count() + 1}")
        self._tabs.setCurrentIndex(idx)
        tab.process_finished.connect(lambda code, _: self._on_process_finished(tab, code))
        tab.start()

    def _close_tab(self, index):
        tab = self._tabs.widget(index)
        if tab:
            tab.stop()
            self._tabs.removeTab(index)

    def _close_current_tab(self):
        idx = self._tabs.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _restart_current(self):
        tab = self._tabs.currentWidget()
        if tab:
            tab.set_cwd(self._cwd)
            tab.start()

    def _current_tab(self):
        return self._tabs.currentWidget()

    def _on_tab_changed(self, index):
        tab = self._tabs.widget(index)
        if tab:
            self._led.set_connected(tab.is_running())

    def _on_process_finished(self, tab, exit_code):
        if tab == self._current_tab():
            self._led.set_connected(False)

    # ---- CWD ----

    def _on_cwd_changed(self):
        path = self._cwd_edit.text().strip()
        if os.path.isdir(path):
            self._cwd = path

    def _browse_cwd(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Working Directory", self._cwd)
        if path:
            self._cwd = path
            self._cwd_edit.setText(path)

    # ---- Font size ----

    def _change_font_size(self, delta):
        self._font_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, self._font_size + delta))
        self._font_label.setText(str(self._font_size))
        for i in range(self._tabs.count()):
            self._tabs.widget(i).set_font_size(self._font_size)

    # ---- Theme ----

    def _toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        self._theme_btn.setText("Dark" if self._theme == "light" else "Light")
        for i in range(self._tabs.count()):
            self._tabs.widget(i).set_theme(self._theme)

    # ---- Auto-restart ----

    def _toggle_auto_restart(self, checked):
        self._auto_restart = checked
        for i in range(self._tabs.count()):
            self._tabs.widget(i).set_auto_restart(checked)

    # ---- Context injection ----

    def send_to_current(self, text):
        """Send text to the current tab's process stdin. Used by context buttons."""
        tab = self._current_tab()
        if tab and tab.is_running():
            tab.send_text(text)

    def _send_selection(self):
        """Send selected node paths to the current session."""
        try:
            import hou
            selected = hou.selectedNodes()
            if not selected:
                self.send_to_current("No nodes selected in Houdini.")
                return
            paths = [n.path() for n in selected]
            msg = f"Selected Houdini nodes ({len(paths)}):\n" + "\n".join(paths)
            self.send_to_current(msg)
        except ImportError:
            self.send_to_current("[Error: hou module not available]")

    def _send_scene_info(self):
        """Send a scene summary to the current session."""
        try:
            import hou
            hip = hou.hipFile.path()
            frame = hou.frame()
            fps = hou.fps()
            obj_count = len(hou.node("/obj").children()) if hou.node("/obj") else 0
            info = (
                f"Houdini scene info:\n"
                f"  File: {hip}\n"
                f"  Frame: {frame} (FPS: {fps})\n"
                f"  Objects in /obj: {obj_count}"
            )
            self.send_to_current(info)
        except ImportError:
            self.send_to_current("[Error: hou module not available]")

    # ---- Keyboard shortcuts ----

    def keyPressEvent(self, event):
        mods = event.modifiers()
        key = event.key()
        # Ctrl+Shift+C = copy
        if mods == (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier) and key == QtCore.Qt.Key_C:
            tab = self._current_tab()
            if tab:
                tab.copy_selection()
            return
        # Ctrl+= / Ctrl+- for font size
        if mods == QtCore.Qt.ControlModifier:
            if key == QtCore.Qt.Key_Equal or key == QtCore.Qt.Key_Plus:
                self._change_font_size(1)
                return
            if key == QtCore.Qt.Key_Minus:
                self._change_font_size(-1)
                return
        super().keyPressEvent(event)

    # ---- Cleanup ----

    def _cleanup(self):
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if tab:
                tab.stop()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)


def create_panel():
    """Entry point called by the .pypanel definition."""
    return ClaudeTerminalWidget()
