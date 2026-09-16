"""Houdini-side TCP server that receives JSON commands from the MCP bridge."""
import hou
import json
import socket
import traceback
import os
import time as _time
import tempfile
try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

from .handlers.scene import (
    get_scene_info, save_scene, load_scene, set_frame, get_asset_lib_status,
)
from .handlers.nodes import (
    create_node, modify_node, delete_node, get_node_info, set_material,
    connect_nodes, disconnect_node_input, set_node_flags,
    layout_children, set_node_color, set_expression, find_error_nodes,
    copy_node, move_node, rename_node, list_children, find_nodes,
    list_node_types, connect_nodes_batch, reorder_inputs,
)
from .handlers.context import (
    get_network_overview, get_cook_chain, explain_node, get_scene_summary,
    get_selection, set_selection,
)
from .handlers.parameters import (
    get_parameter, set_parameter, set_parameters, get_parameter_schema,
    get_expression, revert_parameter, link_parameters, lock_parameter,
    create_spare_parameter, create_spare_parameters,
)
from .handlers.animation import (
    set_keyframe, set_keyframes, delete_keyframe, get_keyframes,
    get_frame, set_frame_range, set_playback_range, playbar_control,
)
from .handlers.vex import (
    create_wrangle, set_wrangle_code, get_wrangle_code,
    create_vex_expression, validate_vex,
)
from .handlers.materials import (
    list_materials, get_material_info, create_material_network,
    assign_material, list_material_types,
)
from .handlers.code import execute_code, execute_hscript, evaluate_expression, get_env_variable, DANGEROUS_PATTERNS
from .handlers.geometry import (
    get_geo_summary, geo_export, get_points, get_prims, get_attrib_values,
    set_detail_attrib, get_groups, get_group_members, get_bounding_box,
    get_prim_intrinsics, find_nearest_point,
)
from .handlers.pdg import pdg_cook, pdg_status, pdg_workitems, pdg_dirty, pdg_cancel
from .handlers.lop import (
    lop_stage_info, lop_prim_get, lop_prim_search, lop_layer_info, lop_import,
    list_usd_prims, get_usd_attribute, set_usd_attribute, get_usd_prim_stats,
    get_last_modified_prims, create_lop_node, get_usd_composition,
    get_usd_variants, inspect_usd_layer, list_lights,
)
from .handlers.workflow import (
    setup_pyro_sim, setup_rbd_sim, setup_flip_sim, setup_vellum_sim,
    create_material_workflow, assign_material_workflow, build_sop_chain, setup_render,
)
from .handlers.cops import (
    get_cop_info, get_cop_geometry, get_cop_layer, create_cop_node,
    set_cop_flags, list_cop_node_types, get_cop_vdb,
)
from .handlers.chops import (
    get_chop_data, create_chop_node, list_chop_channels, export_chop_to_parm,
)
from .handlers.takes import list_takes, get_current_take, set_current_take, create_take
from .handlers.cache import list_caches, get_cache_status, clear_cache, write_cache
from .handlers.hda import (
    hda_list, hda_get, hda_install, hda_create,
    uninstall_hda, reload_hda, update_hda,
    get_hda_sections, get_hda_section_content, set_hda_section_content,
)
from .handlers.dops import (
    get_simulation_info, list_dop_objects, get_dop_object, get_dop_field,
    get_dop_relationships, step_simulation, reset_simulation, get_sim_memory_usage,
)
from .handlers.viewport import (
    list_panes, get_viewport_info, set_viewport_camera, set_viewport_display,
    set_viewport_renderer, frame_selection, frame_all, set_viewport_direction,
    capture_screenshot, set_current_network,
)
from .handlers.rendering import (
    handle_render_single_view, handle_render_quad_view,
    handle_render_specific_camera, render_flipbook,
    list_render_nodes, get_render_settings, set_render_settings,
    create_render_node, start_render, get_render_progress,
)
from .event_collector import EventCollector

EXTENSION_NAME = "Houdini MCP"
EXTENSION_VERSION = (0, 2)
EXTENSION_DESCRIPTION = "Connect Houdini to Claude via MCP"

DEFAULT_PORT = int(os.environ.get("HOUDINIMCP_PORT", 9876))


# ---- GUI/headless port handoff ------------------------------------------------
# Only one process can listen on the port. A GUI (interactive) session always
# wins: it writes a short-lived claim file, a headless server sees the claim and
# steps down to free the port, and the GUI then binds. This lets the bridge and
# an artist share one port without manual juggling.
_CLAIM_TTL = 15.0  # seconds a port claim stays valid


def _claim_path(port):
    return os.path.join(tempfile.gettempdir(), "houdinimcp_claim_%d" % port)


def _write_claim(port):
    try:
        with open(_claim_path(port), "w") as f:
            f.write("%d %f" % (os.getpid(), _time.time()))
    except Exception:
        pass


def _clear_claim(port):
    try:
        os.remove(_claim_path(port))
    except OSError:
        pass


def _read_claim(port):
    try:
        with open(_claim_path(port)) as f:
            pid_s, ts_s = f.read().split()
        return int(pid_s), float(ts_s)
    except Exception:
        return None


def _gui_claim_pending(port):
    """True if another process has a fresh claim on the port."""
    c = _read_claim(port)
    if not c:
        return False
    pid, ts = c
    if pid == os.getpid():
        return False
    return (_time.time() - ts) < _CLAIM_TTL


def _clean_stale_claim(port):
    c = _read_claim(port)
    if c and (_time.time() - c[1]) >= _CLAIM_TTL:
        _clear_claim(port)


class HoudiniMCPServer:
    MUTATING_COMMANDS = {
        "create_node", "modify_node", "delete_node", "execute_code",
        "set_material", "connect_nodes", "disconnect_node_input",
        "set_node_flags", "save_scene", "load_scene", "set_expression",
        "set_frame", "layout_children", "set_node_color",
        "pdg_cook", "pdg_dirty", "pdg_cancel",
        "lop_import", "hda_install", "hda_create", "batch",
        "set_selection", "set_parameter", "set_parameters",
        "revert_parameter", "link_parameters", "lock_parameter",
        "create_spare_parameter", "create_spare_parameters",
        "copy_node", "move_node", "rename_node", "connect_nodes_batch",
        "reorder_inputs", "set_detail_attrib", "execute_hscript",
        "set_keyframe", "set_keyframes", "delete_keyframe",
        "set_frame_range", "set_playback_range", "playbar_control",
        "create_wrangle", "set_wrangle_code", "create_vex_expression",
        "create_material_network", "assign_material",
        "step_simulation", "reset_simulation",
        "set_viewport_camera", "set_viewport_display", "set_viewport_renderer",
        "frame_selection", "frame_all", "set_viewport_direction", "set_current_network",
        "set_render_settings", "create_render_node", "start_render",
        "create_cop_node", "set_cop_flags",
        "create_chop_node", "export_chop_to_parm",
        "set_current_take", "create_take",
        "clear_cache", "write_cache",
        "uninstall_hda", "reload_hda", "update_hda", "set_hda_section_content",
        "set_usd_attribute", "create_lop_node",
        "setup_pyro_sim", "setup_rbd_sim", "setup_flip_sim", "setup_vellum_sim",
        "create_material_workflow", "assign_material_workflow", "build_sop_chain", "setup_render",
    }

    # Re-export for tests that reference it on the class
    DANGEROUS_PATTERNS = DANGEROUS_PATTERNS

    def __init__(self, host='localhost', port=None):
        port = port if port is not None else DEFAULT_PORT
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b''
        self.timer = None
        self.event_collector = EventCollector()
        # Interactive sessions win the port; headless sessions yield it.
        try:
            self.is_ui = bool(hou.isUIAvailable())
        except Exception:
            self.is_ui = False

    def _bind_and_serve(self):
        """Try to bind the port and start the poll timer. Returns True on success."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(1)
            s.setblocking(False)
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            return False
        self.socket = s
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._process_server)
        self.timer.start(100)
        print(f"HoudiniMCP server started on {self.host}:{self.port} "
              f"({'GUI' if self.is_ui else 'headless'})")
        self.event_collector.start()
        return True

    def start(self):
        """Begin listening. A GUI session claims the port from a headless one if busy."""
        self.running = True
        _clean_stale_claim(self.port)
        if self._bind_and_serve():
            return
        # Port is busy.
        if self.is_ui:
            # Claim the port; a headless holder will step down, then we bind.
            _write_claim(self.port)
            for _ in range(20):  # up to ~10s
                _time.sleep(0.5)
                if self._bind_and_serve():
                    _clear_claim(self.port)
                    print("HoudiniMCP: GUI session took the port from a headless instance.")
                    return
            _clear_claim(self.port)
            print(f"HoudiniMCP: port {self.port} held by another GUI session; not starting.")
        else:
            print(f"HoudiniMCP: port {self.port} already in use; headless server not started.")
        self.running = False

    def stop(self):
        """Stop listening; close sockets and timers."""
        self.running = False
        self.event_collector.stop()
        if self.timer:
            self.timer.stop()
            self.timer = None
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
        self.socket = None
        self.client = None
        print("HoudiniMCP server stopped")

    def _process_server(self):
        """Timer callback to accept connections and process incoming data."""
        if not self.running:
            return
        # A headless server yields the port when a GUI session claims it.
        if not self.is_ui and _gui_claim_pending(self.port):
            print("HoudiniMCP: GUI session requested the port; headless stepping down.")
            self.stop()
            app = QtCore.QCoreApplication.instance()
            if app is not None:
                app.quit()  # let the managed hython process exit cleanly
            return
        try:
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    self.client.setblocking(False)
                    print(f"Connected to client: {address}")
                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
            if self.client:
                try:
                    data = self.client.recv(8192)
                    if data:
                        self.buffer += data
                        try:
                            command = json.loads(self.buffer.decode('utf-8'))
                            self.buffer = b''
                            response = self.execute_command(command)
                            self.client.sendall(json.dumps(response).encode('utf-8'))
                        except json.JSONDecodeError:
                            pass
                    else:
                        print("Client disconnected")
                        self.client.close()
                        self.client = None
                        self.buffer = b''
                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    self.client.close()
                    self.client = None
                    self.buffer = b''
        except Exception as e:
            print(f"Server error: {str(e)}")

    def execute_command(self, command):
        """Entry point for executing a JSON command from the client."""
        try:
            cmd_type = command.get("type", "")
            if cmd_type in self.MUTATING_COMMANDS:
                with hou.undos.group(f"MCP: {cmd_type}"):
                    return self._execute_command_internal(command)
            else:
                return self._execute_command_internal(command)
        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _get_handlers(self):
        """Return the command handler dispatch dict."""
        handlers = {
            "ping": self.ping,
            "get_scene_info": get_scene_info,
            "create_node": create_node,
            "modify_node": modify_node,
            "delete_node": delete_node,
            "get_node_info": get_node_info,
            "execute_code": execute_code,
            "set_material": set_material,
            "get_asset_lib_status": get_asset_lib_status,
            "connect_nodes": connect_nodes,
            "disconnect_node_input": disconnect_node_input,
            "set_node_flags": set_node_flags,
            "save_scene": save_scene,
            "load_scene": load_scene,
            "set_expression": set_expression,
            "set_frame": set_frame,
            "get_geo_summary": get_geo_summary,
            "geo_export": geo_export,
            "layout_children": layout_children,
            "set_node_color": set_node_color,
            "find_error_nodes": find_error_nodes,
            "pdg_cook": pdg_cook,
            "pdg_status": pdg_status,
            "pdg_workitems": pdg_workitems,
            "pdg_dirty": pdg_dirty,
            "pdg_cancel": pdg_cancel,
            "lop_stage_info": lop_stage_info,
            "lop_prim_get": lop_prim_get,
            "lop_prim_search": lop_prim_search,
            "lop_layer_info": lop_layer_info,
            "lop_import": lop_import,
            "hda_list": hda_list,
            "hda_get": hda_get,
            "hda_install": hda_install,
            "hda_create": hda_create,
            "batch": self.batch,
            "get_pending_events": self.get_pending_events,
            "subscribe_events": self.subscribe_events,
            "render_single_view": handle_render_single_view,
            "render_quad_view": handle_render_quad_view,
            "render_specific_camera": handle_render_specific_camera,
            "render_flipbook": render_flipbook,
            # Context
            "get_network_overview": get_network_overview,
            "get_cook_chain": get_cook_chain,
            "explain_node": explain_node,
            "get_scene_summary": get_scene_summary,
            "get_selection": get_selection,
            "set_selection": set_selection,
            # Parameters
            "get_parameter": get_parameter,
            "set_parameter": set_parameter,
            "set_parameters": set_parameters,
            "get_parameter_schema": get_parameter_schema,
            "get_expression": get_expression,
            "revert_parameter": revert_parameter,
            "link_parameters": link_parameters,
            "lock_parameter": lock_parameter,
            "create_spare_parameter": create_spare_parameter,
            "create_spare_parameters": create_spare_parameters,
            # Nodes expanded
            "copy_node": copy_node,
            "move_node": move_node,
            "rename_node": rename_node,
            "list_children": list_children,
            "find_nodes": find_nodes,
            "list_node_types": list_node_types,
            "connect_nodes_batch": connect_nodes_batch,
            "reorder_inputs": reorder_inputs,
            # Geometry expanded
            "get_points": get_points,
            "get_prims": get_prims,
            "get_attrib_values": get_attrib_values,
            "set_detail_attrib": set_detail_attrib,
            "get_groups": get_groups,
            "get_group_members": get_group_members,
            "get_bounding_box": get_bounding_box,
            "get_prim_intrinsics": get_prim_intrinsics,
            "find_nearest_point": find_nearest_point,
            # Code expanded
            "execute_hscript": execute_hscript,
            "evaluate_expression": evaluate_expression,
            "get_env_variable": get_env_variable,
            # Animation
            "set_keyframe": set_keyframe,
            "set_keyframes": set_keyframes,
            "delete_keyframe": delete_keyframe,
            "get_keyframes": get_keyframes,
            "get_frame": get_frame,
            "set_frame_range": set_frame_range,
            "set_playback_range": set_playback_range,
            "playbar_control": playbar_control,
            # VEX
            "create_wrangle": create_wrangle,
            "set_wrangle_code": set_wrangle_code,
            "get_wrangle_code": get_wrangle_code,
            "create_vex_expression": create_vex_expression,
            "validate_vex": validate_vex,
            # Materials
            "list_materials": list_materials,
            "get_material_info": get_material_info,
            "create_material_network": create_material_network,
            "assign_material": assign_material,
            "list_material_types": list_material_types,
            # DOPs
            "get_simulation_info": get_simulation_info,
            "list_dop_objects": list_dop_objects,
            "get_dop_object": get_dop_object,
            "get_dop_field": get_dop_field,
            "get_dop_relationships": get_dop_relationships,
            "step_simulation": step_simulation,
            "reset_simulation": reset_simulation,
            "get_sim_memory_usage": get_sim_memory_usage,
            # Viewport
            "list_panes": list_panes,
            "get_viewport_info": get_viewport_info,
            "set_viewport_camera": set_viewport_camera,
            "set_viewport_display": set_viewport_display,
            "set_viewport_renderer": set_viewport_renderer,
            "frame_selection": frame_selection,
            "frame_all": frame_all,
            "set_viewport_direction": set_viewport_direction,
            "capture_screenshot": capture_screenshot,
            "set_current_network": set_current_network,
            # Rendering expanded
            "list_render_nodes": list_render_nodes,
            "get_render_settings": get_render_settings,
            "set_render_settings": set_render_settings,
            "create_render_node": create_render_node,
            "start_render": start_render,
            "get_render_progress": get_render_progress,
            # COPs
            "get_cop_info": get_cop_info,
            "get_cop_geometry": get_cop_geometry,
            "get_cop_layer": get_cop_layer,
            "create_cop_node": create_cop_node,
            "set_cop_flags": set_cop_flags,
            "list_cop_node_types": list_cop_node_types,
            "get_cop_vdb": get_cop_vdb,
            # CHOPs
            "get_chop_data": get_chop_data,
            "create_chop_node": create_chop_node,
            "list_chop_channels": list_chop_channels,
            "export_chop_to_parm": export_chop_to_parm,
            # Takes
            "list_takes": list_takes,
            "get_current_take": get_current_take,
            "set_current_take": set_current_take,
            "create_take": create_take,
            # Cache
            "list_caches": list_caches,
            "get_cache_status": get_cache_status,
            "clear_cache": clear_cache,
            "write_cache": write_cache,
            # HDA expanded
            "uninstall_hda": uninstall_hda,
            "reload_hda": reload_hda,
            "update_hda": update_hda,
            "get_hda_sections": get_hda_sections,
            "get_hda_section_content": get_hda_section_content,
            "set_hda_section_content": set_hda_section_content,
            # LOP expanded
            "list_usd_prims": list_usd_prims,
            "get_usd_attribute": get_usd_attribute,
            "set_usd_attribute": set_usd_attribute,
            "get_usd_prim_stats": get_usd_prim_stats,
            "get_last_modified_prims": get_last_modified_prims,
            "create_lop_node": create_lop_node,
            "get_usd_composition": get_usd_composition,
            "get_usd_variants": get_usd_variants,
            "inspect_usd_layer": inspect_usd_layer,
            "list_lights": list_lights,
            # Workflow templates
            "setup_pyro_sim": setup_pyro_sim,
            "setup_rbd_sim": setup_rbd_sim,
            "setup_flip_sim": setup_flip_sim,
            "setup_vellum_sim": setup_vellum_sim,
            "create_material_workflow": create_material_workflow,
            "assign_material_workflow": assign_material_workflow,
            "build_sop_chain": build_sop_chain,
            "setup_render": setup_render,
        }
        if getattr(hou.session, "houdinimcp_use_assetlib", False):
            handlers.update({
                "get_asset_categories": self.get_asset_categories,
                "search_assets": self.search_assets,
                "import_asset": self.import_asset,
            })
        return handlers

    def _execute_command_internal(self, command):
        """Dispatch a JSON command to its handler."""
        cmd_type = command.get("type")
        params = command.get("params", {})

        handler = self._get_handlers().get(cmd_type)
        if not handler:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

        print(f"Executing handler for {cmd_type}")
        result = handler(**params)
        print(f"Handler execution complete for {cmd_type}")
        return {"status": "success", "result": result}

    def ping(self):
        """Simple health check that returns server status."""
        return {
            "alive": True,
            "host": self.host,
            "port": self.port,
            "has_client": self.client is not None,
        }

    def batch(self, operations):
        """Execute multiple operations atomically. Each op: {type, params}."""
        handlers = self._get_handlers()
        results = []
        for op in operations:
            cmd_type = op.get("type")
            params = op.get("params", {})
            handler = handlers.get(cmd_type)
            if not handler:
                raise ValueError(f"Unknown operation in batch: {cmd_type}")
            result = handler(**params)
            results.append({"type": cmd_type, "result": result})
        return {"count": len(results), "results": results}

    def get_pending_events(self, since=None):
        """Return buffered events since last poll and clear the buffer."""
        events = self.event_collector.get_pending(since=since)
        return {"count": len(events), "events": events}

    def subscribe_events(self, types=None):
        """Configure which event types to collect. None = all."""
        self.event_collector.subscribe(types)
        return {"subscribed": types or "all"}

    def get_asset_categories(self):
        """Placeholder for an asset library feature."""
        return {"error": "get_asset_categories not implemented"}

    def search_assets(self):
        """Placeholder for asset search logic."""
        return {"error": "search_assets not implemented"}

    def import_asset(self):
        """Placeholder for asset import logic."""
        return {"error": "import_asset not implemented"}
