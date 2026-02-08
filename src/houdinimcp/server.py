"""Houdini-side TCP server that receives JSON commands from the MCP bridge."""
import hou
import json
import socket
import traceback
import os
from PySide2 import QtCore

from .handlers.scene import (
    get_scene_info, save_scene, load_scene, set_frame, get_asset_lib_status,
)
from .handlers.nodes import (
    create_node, modify_node, delete_node, get_node_info, set_material,
    connect_nodes, disconnect_node_input, set_node_flags,
    layout_children, set_node_color, set_expression, find_error_nodes,
)
from .handlers.code import execute_code, DANGEROUS_PATTERNS
from .handlers.geometry import get_geo_summary, geo_export
from .handlers.pdg import pdg_cook, pdg_status, pdg_workitems, pdg_dirty, pdg_cancel
from .handlers.lop import (
    lop_stage_info, lop_prim_get, lop_prim_search, lop_layer_info, lop_import,
)
from .handlers.hda import hda_list, hda_get, hda_install, hda_create
from .handlers.rendering import (
    handle_render_single_view, handle_render_quad_view,
    handle_render_specific_camera, render_flipbook,
)
from .event_collector import EventCollector

EXTENSION_NAME = "Houdini MCP"
EXTENSION_VERSION = (0, 2)
EXTENSION_DESCRIPTION = "Connect Houdini to Claude via MCP"

DEFAULT_PORT = int(os.environ.get("HOUDINIMCP_PORT", 9876))


class HoudiniMCPServer:
    MUTATING_COMMANDS = {
        "create_node", "modify_node", "delete_node", "execute_code",
        "set_material", "connect_nodes", "disconnect_node_input",
        "set_node_flags", "save_scene", "load_scene", "set_expression",
        "set_frame", "layout_children", "set_node_color",
        "pdg_cook", "pdg_dirty", "pdg_cancel",
        "lop_import", "hda_install", "hda_create", "batch",
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

    def start(self):
        """Begin listening on the given port; sets up a QTimer to poll for data."""
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._process_server)
            self.timer.start(100)
            self.event_collector.start()
            print(f"HoudiniMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()

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

    # -------------------------------------------------------------------------
    # Command Handling
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Handlers that need self (ping, batch, asset placeholders)
    # -------------------------------------------------------------------------

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
