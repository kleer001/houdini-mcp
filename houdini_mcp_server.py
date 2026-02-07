#!/usr/bin/env python
"""
houdini_mcp_server.py

This is the "bridge" or "driver" script that Claude will run via `uv run`.
It uses the MCP library (fastmcp) to communicate with Claude over stdio,
and relays each command to the local Houdini plugin on port 9876.
"""
import sys
import os
import site

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Add the virtual environment's site-packages to Python's path
# Check both Windows (Lib/site-packages) and Unix (lib/python*/site-packages) layouts
import glob as _glob
_venv_candidates = [
    os.path.join(script_dir, '.venv', 'Lib', 'site-packages'),  # Windows
    *_glob.glob(os.path.join(script_dir, '.venv', 'lib', 'python*', 'site-packages')),  # Unix
]
_venv_found = False
for venv_site_packages in _venv_candidates:
    if os.path.exists(venv_site_packages):
        sys.path.insert(0, venv_site_packages)
        print(f"Added {venv_site_packages} to sys.path", file=sys.stderr)
        _venv_found = True
        break
if not _venv_found:
    print(f"Warning: Virtual environment site-packages not found in {script_dir}/.venv/", file=sys.stderr)


# For debugging
print("Python path:", sys.path, file=sys.stderr)
import json
import socket
import logging
import tempfile
from dataclasses import dataclass
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio

HOUDINI_PORT = int(os.getenv("HOUDINIMCP_PORT", 9876))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HoudiniMCP_StdioServer")


@dataclass
class HoudiniConnection:
    host: str
    port: int
    sock: socket.socket = None
    connected_since: float = None
    last_command_at: float = None
    command_count: int = 0

    def connect(self) -> bool:
        """Connect to the Houdini plugin (which is listening on self.host:self.port)."""
        if self.sock is not None:
            return True  # Already connected
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.connected_since = asyncio.get_event_loop().time()
            logger.info(f"Connected to Houdini at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Houdini: {str(e)}")
            self.sock = None
            self.connected_since = None
            return False

    def disconnect(self):
        """Close socket if open."""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Houdini: {str(e)}")
            self.sock = None
            self.connected_since = None

    def get_status(self) -> dict:
        """Return current connection status info."""
        return {
            "connected": self.sock is not None,
            "host": self.host,
            "port": self.port,
            "connected_since": self.connected_since,
            "last_command_at": self.last_command_at,
            "command_count": self.command_count,
        }

    def send_command(self, cmd_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a JSON command to Houdini's server and wait for the JSON response.
        Returns the parsed Python dict (e.g. {"status": "success", "result": {...}})
        """
        if not self.connect():
            error_msg = f"Could not connect to Houdini on port {self.port}."
            logger.error(error_msg)
            return {"status": "error", "message": error_msg, "origin": "mcp_server_connection"}

        command = {"type": cmd_type, "params": params or {}}
        data_out = json.dumps(command).encode("utf-8")

        try:
            # Send the command
            self.sock.sendall(data_out)
            self.last_command_at = asyncio.get_event_loop().time()
            self.command_count += 1
            logger.info(f"Sent command to Houdini: {command}")

            # Read response. We'll accumulate chunks until we can parse a full JSON.
            self.sock.settimeout(10.0)
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - start_time > 10.0:
                     raise socket.timeout("Timeout waiting for Houdini response")

                chunk = self.sock.recv(8192)
                if not chunk:
                    if buffer:
                         raise ConnectionAbortedError("Connection closed by Houdini with incomplete data.")
                    else:
                         raise ConnectionAbortedError("Connection closed by Houdini before sending data.")

                buffer += chunk
                try:
                    decoded_string = buffer.decode("utf-8")
                    parsed = json.loads(decoded_string)
                    logger.info(f"Received response from Houdini: {parsed}")
                    return parsed
                except json.JSONDecodeError:
                    continue
                except UnicodeDecodeError:
                     logger.error("Received non-UTF-8 data from Houdini")
                     raise ValueError("Received non-UTF-8 data from Houdini")

        except socket.timeout:
            error_msg = "Timeout receiving data from Houdini."
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command_timeout"}
        except Exception as e:
            error_msg = f"Error during Houdini communication for command '{cmd_type}': {str(e)}"
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command"}


# A global Houdini connection object
_houdini_connection: HoudiniConnection = None

def get_houdini_connection() -> HoudiniConnection:
    """Get or create a persistent HoudiniConnection object."""
    global _houdini_connection
    if _houdini_connection is None:
        logger.info("Creating new HoudiniConnection.")
        _houdini_connection = HoudiniConnection(host="localhost", port=HOUDINI_PORT)

    if not _houdini_connection.connect():
         _houdini_connection = None
         raise ConnectionError(f"Could not connect to Houdini on localhost:{HOUDINI_PORT}. Is the plugin running?")

    return _houdini_connection


# Now define the MCP server that Claude will talk to over stdio
mcp = FastMCP("HoudiniMCP")

@asynccontextmanager
async def server_lifespan(app: FastMCP):
    """Startup/shutdown logic. Called automatically by fastmcp."""
    logger.info("Houdini MCP server starting up (stdio).")
    yield {}
    logger.info("Houdini MCP server shutting down.")
    global _houdini_connection
    if _houdini_connection is not None:
        _houdini_connection.disconnect()
        _houdini_connection = None
    logger.info("Connection to Houdini closed.")

mcp.lifespan = server_lifespan


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _send_tool_command(cmd_type: str, params: Dict[str, Any] = None) -> str:
    """Send a command to Houdini and return the JSON result string."""
    conn = get_houdini_connection()
    response = conn.send_command(cmd_type, params)
    if response.get("status") == "error":
        origin = response.get("origin", "houdini")
        return f"Error ({origin}): {response.get('message', 'Unknown error')}"
    return json.dumps(response.get("result", {}), indent=2)


# -------------------------------------------------------------------
# MCP Tools
# -------------------------------------------------------------------
@mcp.tool()
def ping(ctx: Context) -> str:
    """
    Health check to verify Houdini is connected and responsive.
    Returns server status info or an error if Houdini is unreachable.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("ping")
        if response.get("status") == "error":
            return f"Houdini unreachable: {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
        return f"Houdini unreachable: {str(e)}"
    except Exception as e:
        return f"Ping failed: {str(e)}"

@mcp.tool()
def get_connection_status(ctx: Context) -> str:
    """
    Returns the current connection status to Houdini, including
    whether connected, port, command count, and timing info.
    """
    global _houdini_connection
    if _houdini_connection is None:
        return json.dumps({"connected": False, "host": "localhost", "port": HOUDINI_PORT})
    return json.dumps(_houdini_connection.get_status(), indent=2)

@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """
    Ask Houdini for scene info. Returns JSON as a string.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("get_scene_info")
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
         return f"Connection Error getting scene info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in get_scene_info tool: {str(e)}", exc_info=True)
        return f"Server Error retrieving scene info: {str(e)}"

@mcp.tool()
def create_node(ctx: Context, node_type: str, parent_path: str = "/obj", name: str = None) -> str:
    """
    Create a new node in Houdini.
    """
    try:
        conn = get_houdini_connection()
        params = { "node_type": node_type, "parent_path": parent_path }
        if name: params["name"] = name
        response = conn.send_command("create_node", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return f"Node created: {json.dumps(response.get('result', {}), indent=2)}"
    except ConnectionError as e:
         return f"Connection Error creating node: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in create_node tool: {str(e)}", exc_info=True)
        return f"Server Error creating node: {str(e)}"

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str, allow_dangerous: bool = False) -> str:
    """
    Execute arbitrary Python code in Houdini's environment.
    Returns status and any stdout/stderr generated by the code.
    Blocks dangerous patterns (hou.exit, os.remove, subprocess, etc.) unless allow_dangerous=True.
    """
    try:
        conn = get_houdini_connection()
        params = {"code": code}
        if allow_dangerous:
            params["allow_dangerous"] = True
        response = conn.send_command("execute_code", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        result = response.get("result", {})
        if result.get("executed"):
            stdout = result.get("stdout", "").strip()
            stderr = result.get("stderr", "").strip()

            output_message = "Code executed successfully."
            if stdout:
                output_message += f"\\n--- Stdout ---\\n{stdout}"
            if stderr:
                output_message += f"\\n--- Stderr ---\\n{stderr}"
            return output_message
        else:
            logger.warning(f"execute_houdini_code received success status but unexpected result format: {response}")
            return f"Execution status unclear from Houdini response: {json.dumps(response)}"

    except ConnectionError as e:
         return f"Connection Error executing code: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in execute_houdini_code tool: {str(e)}", exc_info=True)
        return f"Server Error executing code: {str(e)}"

# -------------------------------------------------------------------
# Rendering Tools
# -------------------------------------------------------------------
@mcp.tool()
def render_single_view(ctx: Context,
                       orthographic: bool = False,
                       rotation: List[float] = [0, 90, 0],
                       render_path: str = None,
                       render_engine: str = "opengl",
                       karma_engine: str = "cpu") -> str:
    """
    Render a single view inside Houdini and return the rendered image path.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_single_view", {
            "orthographic": orthographic,
            "rotation": rotation,
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_single_view failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_quad_views(ctx: Context,
                      render_path: str = None,
                      render_engine: str = "opengl",
                      karma_engine: str = "cpu") -> str:
    """
    Render 4 canonical views from Houdini and return the image paths.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_quad_view", {
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output returned.")
    except Exception as e:
        logger.error(f"render_quad_views failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_specific_camera(ctx: Context,
                           camera_path: str,
                           render_path: str = None,
                           render_engine: str = "opengl",
                           karma_engine: str = "cpu") -> str:
    """
    Render from a specific camera path in the Houdini scene.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_specific_camera", {
            "camera_path": camera_path,
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_specific_camera failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"


# -------------------------------------------------------------------
# Node Operations
# -------------------------------------------------------------------
@mcp.tool()
def modify_node(ctx: Context, path: str, parameters: Dict[str, Any] = None,
                position: List[float] = None, name: str = None) -> str:
    """Modify an existing node — rename, reposition, or change parameters."""
    params = {"path": path}
    if parameters is not None:
        params["parameters"] = parameters
    if position is not None:
        params["position"] = position
    if name is not None:
        params["name"] = name
    return _send_tool_command("modify_node", params)

@mcp.tool()
def delete_node(ctx: Context, path: str) -> str:
    """Delete a node from the Houdini scene by path."""
    return _send_tool_command("delete_node", {"path": path})

@mcp.tool()
def get_node_info(ctx: Context, path: str) -> str:
    """Get detailed info about a node: type, parameters, inputs, outputs."""
    return _send_tool_command("get_node_info", {"path": path})

@mcp.tool()
def set_material(ctx: Context, node_path: str, material_type: str = "principledshader",
                 name: str = None, parameters: Dict[str, Any] = None) -> str:
    """Create or apply a material to an OBJ node."""
    params = {"node_path": node_path, "material_type": material_type}
    if name is not None:
        params["name"] = name
    if parameters is not None:
        params["parameters"] = parameters
    return _send_tool_command("set_material", params)

# -------------------------------------------------------------------
# Wiring & Connections
# -------------------------------------------------------------------
@mcp.tool()
def connect_nodes(ctx: Context, src_path: str, dst_path: str,
                  dst_input_index: int = 0, src_output_index: int = 0) -> str:
    """Connect two nodes: src output -> dst input."""
    return _send_tool_command("connect_nodes", {
        "src_path": src_path,
        "dst_path": dst_path,
        "dst_input_index": dst_input_index,
        "src_output_index": src_output_index,
    })

@mcp.tool()
def disconnect_node_input(ctx: Context, node_path: str, input_index: int = 0) -> str:
    """Disconnect a specific input on a node."""
    return _send_tool_command("disconnect_node_input", {
        "node_path": node_path,
        "input_index": input_index,
    })

@mcp.tool()
def set_node_flags(ctx: Context, node_path: str, display: bool = None,
                   render: bool = None, bypass: bool = None) -> str:
    """Set display, render, and/or bypass flags on a node."""
    params = {"node_path": node_path}
    if display is not None:
        params["display"] = display
    if render is not None:
        params["render"] = render
    if bypass is not None:
        params["bypass"] = bypass
    return _send_tool_command("set_node_flags", params)

# -------------------------------------------------------------------
# Scene Management
# -------------------------------------------------------------------
@mcp.tool()
def save_scene(ctx: Context, file_path: str = None) -> str:
    """Save the current Houdini scene, optionally to a new file path."""
    params = {}
    if file_path is not None:
        params["file_path"] = file_path
    return _send_tool_command("save_scene", params)

@mcp.tool()
def load_scene(ctx: Context, file_path: str = "") -> str:
    """Load a .hip file into Houdini."""
    return _send_tool_command("load_scene", {"file_path": file_path})

# -------------------------------------------------------------------
# Parameters & Animation
# -------------------------------------------------------------------
@mcp.tool()
def set_expression(ctx: Context, node_path: str, parm_name: str,
                   expression: str, language: str = "hscript") -> str:
    """Set an expression on a node parameter. Language: 'hscript' or 'python'."""
    return _send_tool_command("set_expression", {
        "node_path": node_path,
        "parm_name": parm_name,
        "expression": expression,
        "language": language,
    })

@mcp.tool()
def set_frame(ctx: Context, frame: float = 1.0) -> str:
    """Set the current frame in Houdini's playbar."""
    return _send_tool_command("set_frame", {"frame": frame})

# -------------------------------------------------------------------
# Geometry
# -------------------------------------------------------------------
@mcp.tool()
def get_geo_summary(ctx: Context, node_path: str) -> str:
    """Get geometry stats: point/prim/vertex counts, bounding box, attribute names."""
    return _send_tool_command("get_geo_summary", {"node_path": node_path})

# -------------------------------------------------------------------
# Layout & Organization
# -------------------------------------------------------------------
@mcp.tool()
def layout_children(ctx: Context, node_path: str = "/obj") -> str:
    """Auto-layout child nodes in the network editor."""
    return _send_tool_command("layout_children", {"node_path": node_path})

@mcp.tool()
def set_node_color(ctx: Context, node_path: str, color: List[float] = [1, 1, 1]) -> str:
    """Set a node's color as [r, g, b] (0-1 range)."""
    return _send_tool_command("set_node_color", {"node_path": node_path, "color": color})

# -------------------------------------------------------------------
# Error Detection
# -------------------------------------------------------------------
@mcp.tool()
def find_error_nodes(ctx: Context, root_path: str = "/obj") -> str:
    """Scan the node hierarchy for cook errors and warnings."""
    return _send_tool_command("find_error_nodes", {"root_path": root_path})


# -------------------------------------------------------------------
# PDG/TOPs
# -------------------------------------------------------------------
@mcp.tool()
def pdg_cook(ctx: Context, path: str) -> str:
    """Start cooking a TOP network (non-blocking)."""
    return _send_tool_command("pdg_cook", {"path": path})

@mcp.tool()
def pdg_status(ctx: Context, path: str) -> str:
    """Get cook status and work item counts for a TOP network."""
    return _send_tool_command("pdg_status", {"path": path})

@mcp.tool()
def pdg_workitems(ctx: Context, path: str, state: str = None) -> str:
    """List work items for a TOP node, optionally filtered by state."""
    params = {"path": path}
    if state is not None:
        params["state"] = state
    return _send_tool_command("pdg_workitems", params)

@mcp.tool()
def pdg_dirty(ctx: Context, path: str, dirty_all: bool = False) -> str:
    """Dirty work items on a TOP node for re-cooking."""
    return _send_tool_command("pdg_dirty", {"path": path, "dirty_all": dirty_all})

@mcp.tool()
def pdg_cancel(ctx: Context, path: str) -> str:
    """Cancel a running PDG cook."""
    return _send_tool_command("pdg_cancel", {"path": path})

# -------------------------------------------------------------------
# USD/Solaris (LOP)
# -------------------------------------------------------------------
@mcp.tool()
def lop_stage_info(ctx: Context, path: str) -> str:
    """Get USD stage info from a LOP node: prims, layers, time codes."""
    return _send_tool_command("lop_stage_info", {"path": path})

@mcp.tool()
def lop_prim_get(ctx: Context, path: str, prim_path: str,
                 include_attrs: bool = False) -> str:
    """Get details of a specific USD prim."""
    return _send_tool_command("lop_prim_get", {
        "path": path, "prim_path": prim_path, "include_attrs": include_attrs,
    })

@mcp.tool()
def lop_prim_search(ctx: Context, path: str, pattern: str,
                    type_name: str = None) -> str:
    """Search for USD prims matching a pattern."""
    params = {"path": path, "pattern": pattern}
    if type_name is not None:
        params["type_name"] = type_name
    return _send_tool_command("lop_prim_search", params)

@mcp.tool()
def lop_layer_info(ctx: Context, path: str) -> str:
    """Get USD layer stack info from a LOP node."""
    return _send_tool_command("lop_layer_info", {"path": path})

@mcp.tool()
def lop_import(ctx: Context, path: str, file: str,
               method: str = "reference", prim_path: str = None) -> str:
    """Import a USD file via reference or sublayer."""
    params = {"path": path, "file": file, "method": method}
    if prim_path is not None:
        params["prim_path"] = prim_path
    return _send_tool_command("lop_import", params)

# -------------------------------------------------------------------
# HDA Management
# -------------------------------------------------------------------
@mcp.tool()
def hda_list(ctx: Context, category: str = None) -> str:
    """List available HDA definitions, optionally filtered by category."""
    params = {}
    if category is not None:
        params["category"] = category
    return _send_tool_command("hda_list", params)

@mcp.tool()
def hda_get(ctx: Context, node_type: str, category: str = None) -> str:
    """Get detailed info about an HDA definition."""
    params = {"node_type": node_type}
    if category is not None:
        params["category"] = category
    return _send_tool_command("hda_get", params)

@mcp.tool()
def hda_install(ctx: Context, file_path: str) -> str:
    """Install an HDA file into the current Houdini session."""
    return _send_tool_command("hda_install", {"file_path": file_path})

@mcp.tool()
def hda_create(ctx: Context, node_path: str, name: str,
               label: str, file_path: str) -> str:
    """Create an HDA from an existing node."""
    return _send_tool_command("hda_create", {
        "node_path": node_path, "name": name, "label": label, "file_path": file_path,
    })

# -------------------------------------------------------------------
# Batch & Export
# -------------------------------------------------------------------
@mcp.tool()
def batch(ctx: Context, operations: List[Dict[str, Any]] = []) -> str:
    """Execute multiple operations atomically in a single undo group.
    Each operation: {"type": "create_node", "params": {...}}."""
    return _send_tool_command("batch", {"operations": operations})

@mcp.tool()
def geo_export(ctx: Context, node_path: str, format: str = "obj",
               output: str = None) -> str:
    """Export geometry to a file. Formats: obj, gltf, glb, usd, usda, ply, bgeo.sc."""
    params = {"node_path": node_path, "format": format}
    if output is not None:
        params["output"] = output
    return _send_tool_command("geo_export", params)

@mcp.tool()
def render_flipbook(ctx: Context, frame_range: List[float] = None,
                    output: str = None, resolution: List[int] = None) -> str:
    """Render a flipbook sequence from the viewport."""
    params = {}
    if frame_range is not None:
        params["frame_range"] = frame_range
    if output is not None:
        params["output"] = output
    if resolution is not None:
        params["resolution"] = resolution
    return _send_tool_command("render_flipbook", params)


# -------------------------------------------------------------------
# Documentation Search (local-only, no Houdini connection)
# -------------------------------------------------------------------
@mcp.tool()
def search_docs(ctx: Context, query: str, top_k: int = 5) -> str:
    """Search Houdini documentation offline using BM25.
    Returns ranked results with path, title, preview, and relevance score.
    Does NOT require a Houdini connection."""
    from houdini_rag import search_docs as _search
    results = _search(query, top_k)
    if isinstance(results, dict) and "error" in results:
        return f"Error: {results['error']}"
    return json.dumps(results, indent=2)

@mcp.tool()
def get_doc(ctx: Context, path: str) -> str:
    """Get the full content of a Houdini documentation page by its relative path
    (as returned by search_docs). Does NOT require a Houdini connection."""
    from houdini_rag import get_doc_content
    result = get_doc_content(path)
    if "error" in result:
        return f"Error: {result['error']}"
    return json.dumps(result, indent=2)


def main():
    """Run the MCP server on stdio."""
    mcp.run()

if __name__ == "__main__":
    main()
