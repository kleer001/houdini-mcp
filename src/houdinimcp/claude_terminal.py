"""
claude_terminal.py — Embedded Claude CLI terminal panel for Houdini.

Provides a PySide2-based panel that runs `claude` (or a configurable command)
inside Houdini's UI. Uses QProcess for subprocess management and a
QPlainTextEdit widget for output display.

Requires: PySide2 (bundled with Houdini), optionally pyte for ANSI parsing.
"""
import os
import sys

from PySide2 import QtWidgets, QtCore, QtGui


# ANSI escape stripping — use pyte if available, otherwise regex fallback
try:
    import pyte
    _PYTE_AVAILABLE = True
except ImportError:
    _PYTE_AVAILABLE = False
    import re
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


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


class ClaudeTerminalWidget(QtWidgets.QWidget):
    """Widget that embeds a Claude CLI session inside Houdini."""

    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        self._command = command or "claude"
        self._process = None
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()

        self._new_btn = QtWidgets.QPushButton("New Session")
        self._new_btn.clicked.connect(self._start_session)
        toolbar.addWidget(self._new_btn)

        self._restart_btn = QtWidgets.QPushButton("Restart")
        self._restart_btn.clicked.connect(self._restart_session)
        toolbar.addWidget(self._restart_btn)

        toolbar.addStretch()

        self._led = ConnectionStatusLED()
        toolbar.addWidget(self._led)

        layout.addLayout(toolbar)

        # Output display
        self._output = QtWidgets.QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QtGui.QFont("Courier", 10))
        self._output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self._output)

        # Input line
        input_layout = QtWidgets.QHBoxLayout()
        self._input = QtWidgets.QLineEdit()
        self._input.setPlaceholderText("Type a message to Claude...")
        self._input.returnPressed.connect(self._send_input)
        input_layout.addWidget(self._input)

        self._send_btn = QtWidgets.QPushButton("Send")
        self._send_btn.clicked.connect(self._send_input)
        input_layout.addWidget(self._send_btn)

        layout.addLayout(input_layout)

    def _build_env(self):
        """Build environment variables for the subprocess."""
        env = QtCore.QProcessEnvironment.systemEnvironment()
        port = os.environ.get("HOUDINIMCP_PORT", "9876")
        env.insert("HOUDINIMCP_PORT", port)

        # Set HIP file path if available
        try:
            import hou
            hip = hou.hipFile.path()
            if hip:
                env.insert("HIP", hip)
            env.insert("HOUDINI_VERSION", hou.applicationVersionString())
        except ImportError:
            pass

        return env

    def _start_session(self):
        """Start a new Claude CLI process."""
        if self._process and self._process.state() != QtCore.QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(3000)

        self._output.clear()
        self._output.appendPlainText(f"Starting: {self._command}\n")

        self._process = QtCore.QProcess(self)
        self._process.setProcessEnvironment(self._build_env())
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.started.connect(lambda: self._led.set_connected(True))

        self._process.start(self._command)

    def _restart_session(self):
        """Kill current session and start a fresh one."""
        self._start_session()

    def _send_input(self):
        """Write user input to the process stdin."""
        if not self._process or self._process.state() == QtCore.QProcess.NotRunning:
            self._output.appendPlainText("[Not running — click 'New Session' to start]")
            return

        text = self._input.text()
        self._input.clear()
        self._output.appendPlainText(f"> {text}")
        self._process.write((text + "\n").encode("utf-8"))

    def _on_stdout(self):
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        cleaned = strip_ansi(data)
        self._output.appendPlainText(cleaned)
        # Auto-scroll
        scrollbar = self._output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_stderr(self):
        data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        cleaned = strip_ansi(data)
        self._output.appendPlainText(cleaned)

    def _on_finished(self, exit_code, exit_status):
        self._led.set_connected(False)
        self._output.appendPlainText(f"\n[Process exited with code {exit_code}]")

    def closeEvent(self, event):
        """Clean up subprocess on panel destroy."""
        if self._process and self._process.state() != QtCore.QProcess.NotRunning:
            self._process.kill()
            self._process.waitForFinished(3000)
        super().closeEvent(event)


def create_panel():
    """Entry point called by the .pypanel definition."""
    return ClaudeTerminalWidget()
