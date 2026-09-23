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
_playbar_callbacks = []
_hou_mock.playbar = types.SimpleNamespace(
    frameRange=lambda: (1, 240),
    addEventCallback=lambda cb: _playbar_callbacks.append(cb),
    removeEventCallback=lambda cb: _playbar_callbacks.remove(cb) if cb in _playbar_callbacks else None,
)
_hou_mock.playbarEvent = types.SimpleNamespace(FrameChanged="FrameChanged")
_hou_mock.hipFile.addEventCallback = lambda cb: None
_hou_mock.hipFile.removeEventCallback = lambda cb: None
_hou_mock.hipFile.path = lambda: "/tmp/test.hip"

# Node event types for EventCollector
_hou_mock.nodeEventType = types.SimpleNamespace(
    ChildCreated="ChildCreated",
    ChildDeleted="ChildDeleted",
)
_hou_mock.hipFileEventType = types.SimpleNamespace(
    AfterLoad="AfterLoad",
    AfterSave="AfterSave",
    AfterClear="AfterClear",
)

# Make hou.node("/obj") return a mock with addEventCallback
_obj_node = types.SimpleNamespace(
    path=lambda: "/obj",
    addEventCallback=lambda event_types, cb: None,
    removeEventCallback=lambda event_types, cb: None,
    children=lambda: [],
)
_orig_hou_node = _hou_mock.node
_hou_mock.node = lambda path: _obj_node if path == "/obj" else None
_hou_mock.setFrame = lambda f: None
_hou_mock.exprLanguage = types.SimpleNamespace(
    Hscript=0,
    Python=1,
)
_hou_mock.Color = lambda r, g, b: (r, g, b)
_hou_mock.nodeTypeCategories = lambda: {}
_hou_mock.hda = types.SimpleNamespace(
    installFile=lambda f, **kw: None,
    uninstallFile=lambda f: None,
    definitionsInFile=lambda f: [],
)
# Animation / playbar extras
_hou_mock.time = lambda: 0.0
_hou_mock.intFrame = lambda: 1
_hou_mock.playbar.setFrameRange = lambda s, e: None
_hou_mock.playbar.setPlaybackRange = lambda s, e: None
_hou_mock.playbar.play = lambda: None
_hou_mock.playbar.stop = lambda: None
_hou_mock.playbar.reverse = lambda: None
_hou_mock.Keyframe = type("Keyframe", (), {
    "__init__": lambda self: None,
    "setFrame": lambda self, f: None,
    "setValue": lambda self, v: None,
    "frame": lambda self: 0,
    "value": lambda self: 0,
})
# HScript
_hou_mock.hscript = lambda cmd: ("", "")
_hou_mock.hscriptExpression = lambda expr: 0
_hou_mock.expressionGlobals = lambda: {}
_hou_mock.getenv = lambda name: ""
# VEX
_hou_mock.text = types.SimpleNamespace(vexSyntaxCheck=lambda code: "")
# Parm templates
_hou_mock.FloatParmTemplate = lambda *a, **kw: None
_hou_mock.IntParmTemplate = lambda *a, **kw: None
_hou_mock.StringParmTemplate = lambda *a, **kw: None
_hou_mock.ToggleParmTemplate = lambda *a, **kw: None
_hou_mock.OperationFailed = type("OperationFailed", (Exception,), {})
# Geometry extras
_hou_mock.Vector3 = lambda pos: pos
_hou_mock.attribType = types.SimpleNamespace(Global=0, Point=1, Prim=2)
# Viewport extras
_hou_mock.glShadingType = types.SimpleNamespace(Wire=0, Flat=1, Smooth=2, SmoothWire=3)
_hou_mock.viewportGuide = types.SimpleNamespace(NodeGuides=0)
_hou_mock.geometryViewportType = types.SimpleNamespace(
    Perspective=0, Front=1, Back=2, Left=3, Right=4, Top=5, Bottom=6,
)
# Selected nodes
_hou_mock.selectedNodes = lambda: []
# copyNodesTo / moveNodesTo
_hou_mock.copyNodesTo = lambda nodes, parent: nodes
_hou_mock.moveNodesTo = lambda nodes, parent: nodes
# Takes
_mock_take = types.SimpleNamespace(
    name=lambda: "Main", isCurrent=lambda: True, setCurrent=lambda: None,
    children=lambda: [], parmTuples=lambda: [],
)
_hou_mock.takes = types.SimpleNamespace(
    takes=lambda: [_mock_take],
    currentTake=lambda: _mock_take,
    addTake=lambda name, parent=None: _mock_take,
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
_hou_mock.isUIAvailable = lambda: False
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
        from houdinimcp.event_collector import EventCollector
        self.server.event_collector = EventCollector()

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
            # Phase 1
            "set_selection", "set_parameter", "set_parameters",
            "revert_parameter", "link_parameters", "lock_parameter",
            "create_spare_parameter", "create_spare_parameters",
            # Phase 2
            "copy_node", "move_node", "rename_node", "connect_nodes_batch",
            "reorder_inputs", "set_detail_attrib", "execute_hscript",
            # Phase 3
            "set_keyframe", "set_keyframes", "delete_keyframe",
            "set_frame_range", "set_playback_range", "playbar_control",
            "create_wrangle", "set_wrangle_code", "create_vex_expression",
            "create_material_network", "assign_material",
            # Phase 4
            "step_simulation", "reset_simulation",
            "set_viewport_camera", "set_viewport_display", "set_viewport_renderer",
            "frame_selection", "frame_all", "set_viewport_direction", "set_current_network",
            "set_render_settings", "create_render_node", "start_render",
            # Phase 5
            "create_cop_node", "set_cop_flags",
            "create_chop_node", "export_chop_to_parm",
            "set_current_take", "create_take",
            "clear_cache", "write_cache",
            "uninstall_hda", "reload_hda", "update_hda", "set_hda_section_content",
            # Phase 6
            "set_usd_attribute", "create_lop_node",
            "setup_pyro_sim", "setup_rbd_sim", "setup_flip_sim", "setup_vellum_sim",
            "create_material_workflow", "assign_material_workflow", "build_sop_chain", "setup_render",
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
            # Original
            "ping", "get_scene_info", "create_node", "modify_node",
            "delete_node", "get_node_info", "execute_code", "set_material",
            "connect_nodes", "disconnect_node_input", "set_node_flags",
            "save_scene", "load_scene", "set_expression", "set_frame",
            "get_geo_summary", "geo_export", "layout_children", "set_node_color",
            "find_error_nodes", "pdg_cook", "pdg_status", "pdg_workitems",
            "pdg_dirty", "pdg_cancel", "lop_stage_info", "lop_prim_get",
            "lop_prim_search", "lop_layer_info", "lop_import",
            "hda_list", "hda_get", "hda_install", "hda_create",
            "batch", "get_pending_events", "subscribe_events",
            "render_single_view", "render_quad_view",
            "render_specific_camera", "render_flipbook",
            # Phase 1 — Context + Parameters
            "get_network_overview", "get_cook_chain", "explain_node",
            "get_scene_summary", "get_selection", "set_selection",
            "get_parameter", "set_parameter", "set_parameters",
            "get_parameter_schema", "get_expression", "revert_parameter",
            "link_parameters", "lock_parameter",
            "create_spare_parameter", "create_spare_parameters",
            # Phase 2 — Nodes + Geometry + Code
            "copy_node", "move_node", "rename_node", "list_children",
            "find_nodes", "list_node_types", "connect_nodes_batch", "reorder_inputs",
            "get_points", "get_prims", "get_attrib_values", "set_detail_attrib",
            "get_groups", "get_group_members", "get_bounding_box",
            "get_prim_intrinsics", "find_nearest_point",
            "execute_hscript", "evaluate_expression", "get_env_variable",
            # Phase 3 — Animation + VEX + Materials
            "set_keyframe", "set_keyframes", "delete_keyframe", "get_keyframes",
            "get_frame", "set_frame_range", "set_playback_range", "playbar_control",
            "create_wrangle", "set_wrangle_code", "get_wrangle_code",
            "create_vex_expression", "validate_vex",
            "list_materials", "get_material_info", "create_material_network",
            "assign_material", "list_material_types",
            # Phase 4 — DOPs + Viewport + Rendering
            "get_simulation_info", "list_dop_objects", "get_dop_object",
            "get_dop_field", "get_dop_relationships",
            "step_simulation", "reset_simulation", "get_sim_memory_usage",
            "list_panes", "get_viewport_info", "set_viewport_camera",
            "set_viewport_display", "set_viewport_renderer",
            "frame_selection", "frame_all", "set_viewport_direction",
            "capture_screenshot", "set_current_network",
            "list_render_nodes", "get_render_settings", "set_render_settings",
            "create_render_node", "start_render", "get_render_progress",
            # Phase 5 — COPs + CHOPs + Takes + Cache + HDA
            "get_cop_info", "get_cop_geometry", "get_cop_layer",
            "create_cop_node", "set_cop_flags", "list_cop_node_types", "get_cop_vdb",
            "get_chop_data", "create_chop_node", "list_chop_channels", "export_chop_to_parm",
            "list_takes", "get_current_take", "set_current_take", "create_take",
            "list_caches", "get_cache_status", "clear_cache", "write_cache",
            "uninstall_hda", "reload_hda", "update_hda",
            "get_hda_sections", "get_hda_section_content", "set_hda_section_content",
            # Phase 6 — USD + Workflow
            "list_usd_prims", "get_usd_attribute", "set_usd_attribute",
            "get_usd_prim_stats", "get_last_modified_prims", "create_lop_node",
            "get_usd_composition", "get_usd_variants", "inspect_usd_layer", "list_lights",
            "setup_pyro_sim", "setup_rbd_sim", "setup_flip_sim", "setup_vellum_sim",
            "create_material_workflow", "assign_material_workflow",
            "build_sop_chain", "setup_render",
        ]
        for cmd in expected:
            assert cmd in handlers, f"Handler not registered: {cmd}"

    def test_get_pending_events_dispatches(self):
        """get_pending_events should return empty events list."""
        result = self.server.execute_command({
            "type": "get_pending_events",
            "params": {},
        })
        assert result["status"] == "success"
        assert result["result"]["count"] == 0
        assert result["result"]["events"] == []

    def test_subscribe_events_dispatches(self):
        """subscribe_events should accept a type filter."""
        result = self.server.execute_command({
            "type": "subscribe_events",
            "params": {"types": ["scene_saved", "node_created"]},
        })
        assert result["status"] == "success"
        assert result["result"]["subscribed"] == ["scene_saved", "node_created"]

    def test_subscribe_events_all(self):
        """subscribe_events with no types = subscribe to all."""
        result = self.server.execute_command({
            "type": "subscribe_events",
            "params": {},
        })
        assert result["status"] == "success"
        assert result["result"]["subscribed"] == "all"
