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
_hou_mock.hipFile = types.SimpleNamespace(
    name=lambda: "untitled.hip",
    save=lambda *a, **kw: None,
    load=lambda *a, **kw: None,
)
_hou_mock.fps = lambda: 24.0
_hou_mock.playbar = types.SimpleNamespace(frameRange=lambda: (1, 240))
_hou_mock.setFrame = lambda f: None
_hou_mock.exprLanguage = types.SimpleNamespace(
    Hscript=0,
    Python=1,
)
_hou_mock.Color = lambda r, g, b: (r, g, b)
_hou_mock.nodeTypeCategories = lambda: {}
_hou_mock.hda = types.SimpleNamespace(
    installFile=lambda f: None,
    definitionsInFile=lambda f: [],
)
_hou_mock.ui = types.SimpleNamespace(
    paneTabOfType=lambda t: None,
)
_hou_mock.paneTabType = types.SimpleNamespace(
    SceneViewer=0,
)
_hou_mock.LopSelectionRule = type("LopSelectionRule", (), {
    "__init__": lambda self: None,
    "setPathPattern": lambda self, p: None,
    "setTypeName": lambda self, t: None,
    "expandedPaths": lambda self, n: [],
})
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
        expected = {
            "create_node", "modify_node", "delete_node", "execute_code",
            "set_material", "connect_nodes", "disconnect_node_input",
            "set_node_flags", "save_scene", "load_scene", "set_expression",
            "set_frame", "layout_children", "set_node_color",
            "pdg_cook", "pdg_dirty", "pdg_cancel",
            "lop_import", "hda_install", "hda_create", "batch",
        }
        assert expected == HoudiniMCPServer.MUTATING_COMMANDS

    def test_ping_handler_fields(self):
        result = self.server.ping()
        assert "alive" in result
        assert "host" in result
        assert "port" in result
        assert result["alive"] is True
        assert result["port"] == 9876

    def test_dangerous_code_blocked(self):
        """execute_code should reject dangerous patterns by default."""
        result = self.server.execute_command({
            "type": "execute_code",
            "params": {"code": "import os; os.remove('/tmp/foo')"},
        })
        assert result["status"] == "error"
        assert "Dangerous pattern" in result["message"]

    def test_dangerous_code_allowed(self):
        """execute_code with allow_dangerous=True should proceed."""
        result = self.server.execute_command({
            "type": "execute_code",
            "params": {"code": "x = 1 + 1", "allow_dangerous": True},
        })
        assert result["status"] == "success"
        assert result["result"]["executed"] is True

    def test_safe_code_executes(self):
        """Normal code without dangerous patterns should execute fine."""
        result = self.server.execute_command({
            "type": "execute_code",
            "params": {"code": "x = 42"},
        })
        assert result["status"] == "success"
        assert result["result"]["executed"] is True

    def test_set_frame_dispatches(self):
        """set_frame should call through the dispatcher."""
        result = self.server.execute_command({
            "type": "set_frame",
            "params": {"frame": 10},
        })
        assert result["status"] == "success"
        assert result["result"]["frame"] == 10

    def test_save_scene_dispatches(self):
        """save_scene should return saved status."""
        result = self.server.execute_command({
            "type": "save_scene",
            "params": {},
        })
        assert result["status"] == "success"
        assert result["result"]["saved"] is True

    def test_dangerous_patterns_list(self):
        """Verify all expected dangerous patterns are in the list."""
        expected_patterns = {"hou.exit", "os.remove", "os.unlink",
                             "shutil.rmtree", "subprocess", "os.system",
                             "os.popen", "__import__"}
        assert expected_patterns == set(HoudiniMCPServer.DANGEROUS_PATTERNS)

    def test_batch_dispatches(self):
        """Batch handler should execute multiple operations."""
        result = self.server.execute_command({
            "type": "batch",
            "params": {"operations": [
                {"type": "set_frame", "params": {"frame": 5}},
                {"type": "set_frame", "params": {"frame": 10}},
            ]},
        })
        assert result["status"] == "success"
        assert result["result"]["count"] == 2

    def test_batch_unknown_op_fails(self):
        """Batch with unknown operation type should fail."""
        result = self.server.execute_command({
            "type": "batch",
            "params": {"operations": [
                {"type": "nonexistent_op", "params": {}},
            ]},
        })
        assert result["status"] == "error"
        assert "Unknown operation" in result["message"]

    def test_hda_list_dispatches(self):
        """hda_list should return without error (empty with mocked hou)."""
        result = self.server.execute_command({
            "type": "hda_list",
            "params": {},
        })
        assert result["status"] == "success"
        assert result["result"]["count"] == 0

    def test_all_handlers_registered(self):
        """Every expected command type should have a handler."""
        handlers = self.server._get_handlers()
        expected = [
            "ping", "get_scene_info", "create_node", "modify_node",
            "delete_node", "get_node_info", "execute_code", "set_material",
            "connect_nodes", "disconnect_node_input", "set_node_flags",
            "save_scene", "load_scene", "set_expression", "set_frame",
            "get_geo_summary", "geo_export", "layout_children", "set_node_color",
            "find_error_nodes", "pdg_cook", "pdg_status", "pdg_workitems",
            "pdg_dirty", "pdg_cancel", "lop_stage_info", "lop_prim_get",
            "lop_prim_search", "lop_layer_info", "lop_import",
            "hda_list", "hda_get", "hda_install", "hda_create",
            "batch", "render_single_view", "render_quad_view",
            "render_specific_camera", "render_flipbook",
        ]
        for cmd in expected:
            assert cmd in handlers, f"Handler not registered: {cmd}"
