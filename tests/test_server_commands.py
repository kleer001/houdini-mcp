"""Tests for the Houdini-side server command dispatcher.

These tests mock the `hou` module and other Houdini-only deps since
server.py normally runs inside the Houdini process.
"""
import sys
import os
import types

import pytest

# ---------- Mock modules that only exist inside Houdini ----------

# Mock hou
_hou_mock = types.ModuleType("hou")
_hou_mock.session = types.SimpleNamespace(
    houdinimcp_server=None,
    houdinimcp_use_assetlib=False,
)


class _UndoGroup:
    def __init__(self, label):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


_hou_mock.undos = types.SimpleNamespace(group=_UndoGroup)
_hou_mock.node = lambda path: None
_hou_mock.hipFile = types.SimpleNamespace(name=lambda: "untitled.hip")
_hou_mock.fps = lambda: 24.0
_hou_mock.playbar = types.SimpleNamespace(frameRange=lambda: (1, 240))
sys.modules["hou"] = _hou_mock

# Mock PySide2
for mod_name in ["PySide2", "PySide2.QtWidgets", "PySide2.QtCore", "PySide2.QtGui"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

_qtcore = sys.modules["PySide2.QtCore"]

class _MockQTimer:
    def __init__(self):
        self._callback = None
    def timeout_connect(self, cb):
        self._callback = cb
    @property
    def timeout(self):
        return types.SimpleNamespace(connect=self.timeout_connect)
    def start(self, ms):
        pass
    def stop(self):
        pass

_qtcore.QTimer = _MockQTimer

# Mock numpy (used by HoudiniMCPRender.py)
_numpy_mock = types.ModuleType("numpy")
_numpy_mock.array = lambda *a, **kw: a[0] if a else []
_numpy_mock.isinf = lambda x: types.SimpleNamespace(any=lambda: False)
sys.modules["numpy"] = _numpy_mock

# ---------- Now import the server ----------
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from houdinimcp.server import HoudiniMCPServer


class TestCommandDispatcher:
    def setup_method(self):
        self.server = HoudiniMCPServer.__new__(HoudiniMCPServer)
        self.server.host = "localhost"
        self.server.port = 9876
        self.server.running = False
        self.server.socket = None
        self.server.client = None
        self.server.buffer = b""
        self.server.timer = None

    def test_ping_returns_alive(self):
        result = self.server.execute_command({"type": "ping"})
        assert result["status"] == "success"
        assert result["result"]["alive"] is True

    def test_unknown_command_returns_error(self):
        result = self.server.execute_command({"type": "totally_fake"})
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_mutating_commands_set(self):
        """Verify MUTATING_COMMANDS contains the expected commands."""
        expected = {"create_node", "modify_node", "delete_node", "execute_code",
                    "set_material"}
        assert expected == HoudiniMCPServer.MUTATING_COMMANDS

    def test_ping_handler_fields(self):
        result = self.server.ping()
        assert "alive" in result
        assert "host" in result
        assert "port" in result
        assert result["alive"] is True
        assert result["port"] == 9876
