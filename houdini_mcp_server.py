#!/usr/bin/env python
"""
houdini_mcp_server.py

This is the "bridge" or "driver" script that Claude will run via `uv run`.
It uses the MCP library (fastmcp) to communicate with Claude over stdio,
and relays each command to the local Houdini plugin on port 9876.
"""
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))

import glob as _glob
_venv_candidates = [
    os.path.join(script_dir, '.venv', 'Lib', 'site-packages'),
    *_glob.glob(os.path.join(script_dir, '.venv', 'lib', 'python*', 'site-packages')),
]
for venv_site_packages in _venv_candidates:
    if os.path.exists(venv_site_packages):
        sys.path.insert(0, venv_site_packages)
        break
import json
import socket
import subprocess
import logging
import tempfile
import shutil
import platform
import atexit
import time as _time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio

HOUDINI_PORT = int(os.getenv("HOUDINIMCP_PORT", 9876))
HEADLESS_DISABLED = os.getenv("HOUDINIMCP_NO_HEADLESS", "").strip() in ("1", "true", "yes")

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

        timeout = 30.0
        recv_size = 8192

        try:
            # Send the command
            self.sock.sendall(data_out)
            self.last_command_at = asyncio.get_event_loop().time()
            self.command_count += 1
            logger.info(f"Sent command to Houdini: {command}")

            # Read response. We'll accumulate chunks until we can parse a full JSON.
            self.sock.settimeout(timeout)
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - start_time > timeout:
                     raise socket.timeout("Timeout waiting for Houdini response")

                chunk = self.sock.recv(recv_size)
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


# ---- Headless hython management ----

_hython_process = None


def find_hython() -> Optional[str]:
    """Locate the hython binary (Houdini's headless Python interpreter)."""
    # 1. HFS env var (set when Houdini environment is sourced)
    hfs = os.environ.get("HFS")
    if hfs:
        candidate = os.path.join(hfs, "bin", "hython")
        if os.path.isfile(candidate):
            return candidate

    # 2. Already on PATH
    on_path = shutil.which("hython")
    if on_path:
        return on_path

    # 3. Scan common install locations
    system = platform.system()
    candidates = []
    if system == "Linux":
        if os.path.isdir("/opt"):
            for d in sorted(os.listdir("/opt"), reverse=True):
                if d.startswith("hfs"):
                    candidates.append(os.path.join("/opt", d, "bin", "hython"))
    elif system == "Windows":
        for base in [r"C:\Program Files\Side Effects Software",
                     r"C:\Program Files (x86)\Side Effects Software"]:
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    candidates.append(os.path.join(base, d, "bin", "hython.exe"))
    elif system == "Darwin":
        for base in ["/Applications/Houdini"]:
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    candidates.append(os.path.join(
                        base, d, "Frameworks", "Houdini.framework",
                        "Versions", "Current", "Resources", "bin", "hython"))
        if os.path.isdir("/opt"):
            for d in sorted(os.listdir("/opt"), reverse=True):
                if d.startswith("hfs"):
                    candidates.append(os.path.join("/opt", d, "bin", "hython"))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _port_is_listening(port: int, host: str = "localhost") -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((host, port))
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def _launch_headless_houdini() -> bool:
    """Launch hython with the headless MCP server. Returns True if server is ready."""
    global _hython_process
    if _hython_process and _hython_process.poll() is None:
        return _port_is_listening(HOUDINI_PORT)

    hython = find_hython()
    if not hython:
        logger.warning("Cannot launch headless Houdini: hython not found.")
        return False

    headless_script = os.path.join(script_dir, "scripts", "headless_server.py")
    if not os.path.isfile(headless_script):
        logger.error(f"Headless server script not found: {headless_script}")
        return False

    env = os.environ.copy()
    env["HOUDINIMCP_PORT"] = str(HOUDINI_PORT)

    logger.info(f"Launching headless Houdini: {hython} {headless_script}")
    _hython_process = subprocess.Popen(
        [hython, headless_script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the server to start listening (up to 30 seconds — hython startup is slow)
    for _ in range(60):
        if _hython_process.poll() is not None:
            # Process exited unexpectedly
            stderr = _hython_process.stderr.read().decode(errors="replace")
            logger.error(f"hython exited early (code {_hython_process.returncode}): {stderr[:500]}")
            _hython_process = None
            return False
        if _port_is_listening(HOUDINI_PORT):
            logger.info("Headless Houdini is ready.")
            return True
        _time.sleep(0.5)

    logger.error("Headless Houdini failed to start within 30 seconds.")
    _cleanup_hython()
    return False


def _cleanup_hython():
    """Terminate the managed hython process if running."""
    global _hython_process
    if _hython_process and _hython_process.poll() is None:
        logger.info("Shutting down headless Houdini...")
        _hython_process.terminate()
        try:
            _hython_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _hython_process.kill()
            _hython_process.wait()
    _hython_process = None


atexit.register(_cleanup_hython)


# ---- Global connection ----

_houdini_connection: HoudiniConnection = None


def get_houdini_connection() -> HoudiniConnection:
    """Get or create a persistent HoudiniConnection object.

    If no Houdini instance is listening, attempts to launch a headless hython
    session automatically (unless HOUDINIMCP_NO_HEADLESS=1 is set).
    """
    global _houdini_connection
    if _houdini_connection is None:
        logger.info("Creating new HoudiniConnection.")
        _houdini_connection = HoudiniConnection(host="localhost", port=HOUDINI_PORT)

    if not _houdini_connection.connect():
        # No Houdini listening — try launching headless
        if not HEADLESS_DISABLED:
            logger.info("No Houdini detected. Attempting headless launch...")
            if _launch_headless_houdini():
                # Retry connection
                _houdini_connection = HoudiniConnection(host="localhost", port=HOUDINI_PORT)
                if _houdini_connection.connect():
                    return _houdini_connection

        _houdini_connection = None
        raise ConnectionError(
            f"Could not connect to Houdini on localhost:{HOUDINI_PORT}. "
            "Is the plugin running? (Set HOUDINIMCP_NO_HEADLESS=1 to disable auto-launch.)"
        )

    return _houdini_connection


# Now define the MCP server that Claude will talk to over stdio
mcp = FastMCP("HoudiniMCP", instructions="""\
IMPORTANT — Houdini MCP — Authoring & Connection Rules:

0. **Build nodes, not code.** The deliverable is a node network a TD can open and edit —
   not procedural code that does the work. The Python you send is scaffolding to build the
   graph; the graph's logic lives in nodes. Motion/behavior comes from real solver/force
   nodes (POP Force, POP Wind, DOP/SOP solvers), NOT from `@v += ...` in a wrangle; wrangles
   are for attributes and selection. Don't add a control null of promoted parameters unless
   the user asks. Honest exceptions (creating attributes, grouping, genuinely kinematic looks
   with no force-node equivalent, real math) stay in a wrangle — say so. Full philosophy plus
   the LLM pitfall checklist (A–H: don't guess node/parm names, verify silent no-ops, VEX
   prefixes, sim discipline, respect the co-edited scene, async renders, trace attrs to the
   render, build incrementally) is in BEST_PRACTICES.md — read it before non-trivial work.

1. **Never rapid-fire commands.** Wait at least 1 second between consecutive tool calls.
   The Houdini plugin uses a single-threaded listener and needs time to reset between connections.

2. **Separate scene commands from render commands.** Do all scene setup (create nodes,
   modify parameters, set materials, connect nodes, etc.) FIRST. Then call render tools
   in a separate step.

3. **Render commands are slow.** Rendering takes significantly longer than node operations.
   Do not assume a render has failed just because it takes time.

4. **If you get a connection error, STOP.** Do not retry in a loop — you likely crashed
   the plugin. Tell the user to restart the Houdini MCP plugin and verify the port is
   listening before trying again.

5. **Verify connectivity first.** Use the `ping` tool before starting work to confirm
   the Houdini plugin is reachable.

5a. **You can open the Houdini GUI yourself — when the user asks for it.** This server
   only ever auto-launches *headless* hython; it never starts the GUI. But GUI-only work
   (viewport, screenshots, flipbooks, and GPU-only paths such as Copernicus/COPs) needs a
   real GUI session. When the user asks you to open Houdini — or asks for GUI-only work
   that has no live GUI session — launch it yourself from the shell instead of asking the
   user to do it: run the `houdini` (or `houdinifx`) binary from the newest install
   (`$HFS/bin`, else the highest `/opt/hfsNN.N.NNN/bin`), optionally with a `.hip` path,
   in the background; a display must be present (`$DISPLAY`). The GUI's `pythonrc.py`
   autostart binds the plugin on port 9876 — poll `ss -ltn | grep :9876` (startup takes
   ~20–40s), then `ping`. Do NOT open the GUI on your own initiative to tidy up or
   "get ready" — only when the user asks for it or for work that requires it.

6. **Render workflow:** Render tools save images to disk (in /tmp/ by default) and return
   the file path. Use the Read tool to view the rendered image directly, or tell the user
   the file path.

7. **Use batch for bulk operations.** When creating multiple nodes or making many
   changes at once, prefer the `batch` tool over individual calls. This executes
   atomically in a single undo group and avoids rapid-fire connection issues.

8. **Monitor long renders.** After launching a Karma or Mantra render, use
   `monitor_render` to poll for `husk` / `mantra-bin` processes and check if
   the output file exists. No Houdini connection needed.

9. **Document non-trivial discoveries (two layers).** Read `BEST_PRACTICES.md`
   (repo root) first — it holds the philosophy, the A–H pitfalls, and a routing table.
   A short, generalizable, first-pass rule (roughly <=100-200 tokens) goes there; an
   involved or context-specific gotcha goes strictly in `best_practices/<area>.md`
   (dops, cops, cop2, sops, lops_usd, rops_render, karma, mcp_and_environment, hda,
   pdg, chops; create the file if missing). Always include the Houdini version. Keep
   it to problem, symptom, fix — no essays.
""")

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
    _cleanup_hython()
    logger.info("Connection to Houdini closed.")

mcp.lifespan = server_lifespan


def _send_tool_command(cmd_type: str, params: Dict[str, Any] = None) -> str:
    """Send a command to Houdini and return the JSON result string."""
    conn = get_houdini_connection()
    response = conn.send_command(cmd_type, params)
    if response.get("status") == "error":
        origin = response.get("origin", "houdini")
        return f"Error ({origin}): {response.get('message', 'Unknown error')}"
    return json.dumps(response.get("result", {}), indent=2)


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
    return _send_tool_command("get_scene_info")

@mcp.tool()
def create_node(ctx: Context, node_type: str, parent_path: str = "/obj", name: str = None) -> str:
    """
    Create a new node in Houdini.
    """
    params = {"node_type": node_type, "parent_path": parent_path}
    if name:
        params["name"] = name
    return _send_tool_command("create_node", params)

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str, allow_dangerous: bool = False) -> str:
    """
    Execute arbitrary Python code in Houdini's environment.
    Returns status and any stdout/stderr generated by the code.
    Blocks dangerous patterns (hou.exit, os.remove, subprocess, etc.) unless allow_dangerous=True.
    """
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

    return f"Execution status unclear from Houdini response: {json.dumps(response)}"

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

        result = response.get("result", {})
        if isinstance(result, dict) and result.get("filepath"):
            res = result.get("resolution", [0, 0])
            return f"Rendered to {result['filepath']} ({res[0]}x{res[1]}, {render_engine})"
        return json.dumps(result, indent=2)
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

        result = response.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            lines = ["Rendered views:"]
            for view in result["results"]:
                name = view.get("view_name", "unknown")
                fp = view.get("filepath", "?")
                res = view.get("resolution", [0, 0])
                lines.append(f"  {name}: {fp} ({res[0]}x{res[1]})")
            return "\n".join(lines)
        return json.dumps(result, indent=2)
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

        result = response.get("result", {})
        if isinstance(result, dict) and result.get("filepath"):
            res = result.get("resolution", [0, 0])
            return f"Rendered to {result['filepath']} ({res[0]}x{res[1]}, {render_engine})"
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"render_specific_camera failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"


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

@mcp.tool()
def get_geo_summary(ctx: Context, node_path: str) -> str:
    """Get geometry stats: point/prim/vertex counts, bounding box, attribute names."""
    return _send_tool_command("get_geo_summary", {"node_path": node_path})

@mcp.tool()
def layout_children(ctx: Context, node_path: str = "/obj") -> str:
    """Auto-layout child nodes in the network editor."""
    return _send_tool_command("layout_children", {"node_path": node_path})

@mcp.tool()
def set_node_color(ctx: Context, node_path: str, color: List[float] = [1, 1, 1]) -> str:
    """Set a node's color as [r, g, b] (0-1 range)."""
    return _send_tool_command("set_node_color", {"node_path": node_path, "color": color})

@mcp.tool()
def find_error_nodes(ctx: Context, root_path: str = "/obj") -> str:
    """Scan the node hierarchy for cook errors and warnings."""
    return _send_tool_command("find_error_nodes", {"root_path": root_path})


# ── Context tools ──

@mcp.tool()
def get_network_overview(ctx: Context, path: str = "/obj") -> str:
    """Get an overview of all nodes in a network with their connections."""
    return _send_tool_command("get_network_overview", {"path": path})

@mcp.tool()
def get_cook_chain(ctx: Context, path: str) -> str:
    """Get the cook dependency chain for a node (inputs all the way up)."""
    return _send_tool_command("get_cook_chain", {"path": path})

@mcp.tool()
def explain_node(ctx: Context, path: str) -> str:
    """Get a human-readable explanation of a node: type, non-default parms, connections."""
    return _send_tool_command("explain_node", {"path": path})

@mcp.tool()
def get_scene_summary(ctx: Context) -> str:
    """Get a high-level summary of the entire scene: node counts by category, frame info."""
    return _send_tool_command("get_scene_summary")

@mcp.tool()
def get_selection(ctx: Context) -> str:
    """Get the currently selected nodes in Houdini."""
    return _send_tool_command("get_selection")

@mcp.tool()
def set_selection(ctx: Context, paths: List[str]) -> str:
    """Set the node selection to the given list of node paths."""
    return _send_tool_command("set_selection", {"paths": paths})

# ── Parameter tools ──

@mcp.tool()
def get_parameter(ctx: Context, node_path: str, parm_name: str) -> str:
    """Get a single parameter's value, type, expression, and metadata."""
    return _send_tool_command("get_parameter", {"node_path": node_path, "parm_name": parm_name})

@mcp.tool()
def set_parameter(ctx: Context, node_path: str, parm_name: str, value: Any) -> str:
    """Set a single parameter value on a node."""
    return _send_tool_command("set_parameter", {"node_path": node_path, "parm_name": parm_name, "value": value})

@mcp.tool()
def set_parameters(ctx: Context, node_path: str, parameters: Dict[str, Any]) -> str:
    """Set multiple parameters at once on a node."""
    return _send_tool_command("set_parameters", {"node_path": node_path, "parameters": parameters})

@mcp.tool()
def get_parameter_schema(ctx: Context, node_path: str) -> str:
    """Get the full parameter schema (all parm templates) for a node."""
    return _send_tool_command("get_parameter_schema", {"node_path": node_path})

@mcp.tool()
def get_expression(ctx: Context, node_path: str, parm_name: str) -> str:
    """Get the expression set on a parameter, if any."""
    return _send_tool_command("get_expression", {"node_path": node_path, "parm_name": parm_name})

@mcp.tool()
def revert_parameter(ctx: Context, node_path: str, parm_name: str) -> str:
    """Revert a parameter to its default value."""
    return _send_tool_command("revert_parameter", {"node_path": node_path, "parm_name": parm_name})

@mcp.tool()
def link_parameters(ctx: Context, src_path: str, src_parm: str,
                    dst_path: str, dst_parm: str) -> str:
    """Create a channel reference from dst_parm to src_parm."""
    return _send_tool_command("link_parameters", {
        "src_path": src_path, "src_parm": src_parm,
        "dst_path": dst_path, "dst_parm": dst_parm,
    })

@mcp.tool()
def lock_parameter(ctx: Context, node_path: str, parm_name: str,
                   locked: bool = True) -> str:
    """Lock or unlock a parameter."""
    return _send_tool_command("lock_parameter", {
        "node_path": node_path, "parm_name": parm_name, "locked": locked,
    })

@mcp.tool()
def create_spare_parameter(ctx: Context, node_path: str, name: str,
                           label: str, parm_type: str, default: Any = None) -> str:
    """Add a spare parameter to a node. Types: float, int, string, toggle."""
    params = {"node_path": node_path, "name": name, "label": label, "parm_type": parm_type}
    if default is not None:
        params["default"] = default
    return _send_tool_command("create_spare_parameter", params)

@mcp.tool()
def create_spare_parameters(ctx: Context, node_path: str,
                            parameters: List[Dict[str, Any]]) -> str:
    """Add multiple spare parameters to a node at once."""
    return _send_tool_command("create_spare_parameters", {
        "node_path": node_path, "parameters": parameters,
    })

# ── Animation tools ──

@mcp.tool()
def set_keyframe(ctx: Context, node_path: str, parm_name: str,
                 frame: float, value: float) -> str:
    """Set a keyframe on a parameter at a specific frame."""
    return _send_tool_command("set_keyframe", {
        "node_path": node_path, "parm_name": parm_name, "frame": frame, "value": value,
    })

@mcp.tool()
def set_keyframes(ctx: Context, node_path: str, parm_name: str,
                  keyframes: List[Dict[str, float]]) -> str:
    """Set multiple keyframes. Each: {frame, value}."""
    return _send_tool_command("set_keyframes", {
        "node_path": node_path, "parm_name": parm_name, "keyframes": keyframes,
    })

@mcp.tool()
def delete_keyframe(ctx: Context, node_path: str, parm_name: str, frame: float) -> str:
    """Delete a keyframe at a specific frame."""
    return _send_tool_command("delete_keyframe", {
        "node_path": node_path, "parm_name": parm_name, "frame": frame,
    })

@mcp.tool()
def get_keyframes(ctx: Context, node_path: str, parm_name: str) -> str:
    """Get all keyframes on a parameter."""
    return _send_tool_command("get_keyframes", {"node_path": node_path, "parm_name": parm_name})

@mcp.tool()
def get_frame(ctx: Context) -> str:
    """Get the current frame and time."""
    return _send_tool_command("get_frame")

@mcp.tool()
def set_frame_range(ctx: Context, start: float, end: float) -> str:
    """Set the global animation frame range."""
    return _send_tool_command("set_frame_range", {"start": start, "end": end})

@mcp.tool()
def set_playback_range(ctx: Context, start: float, end: float) -> str:
    """Set the playback range (subset of the global range)."""
    return _send_tool_command("set_playback_range", {"start": start, "end": end})

@mcp.tool()
def playbar_control(ctx: Context, action: str) -> str:
    """Control playbar: play, stop, reverse, step_forward, step_backward."""
    return _send_tool_command("playbar_control", {"action": action})

# ── VEX tools ──

@mcp.tool()
def create_wrangle(ctx: Context, parent_path: str,
                   wrangle_type: str = "attribwrangle",
                   name: str = None, code: str = "") -> str:
    """Create a VEX wrangle node with optional initial code."""
    params = {"parent_path": parent_path, "wrangle_type": wrangle_type, "code": code}
    if name is not None:
        params["name"] = name
    return _send_tool_command("create_wrangle", params)

@mcp.tool()
def set_wrangle_code(ctx: Context, node_path: str, code: str) -> str:
    """Set the VEX code on a wrangle node."""
    return _send_tool_command("set_wrangle_code", {"node_path": node_path, "code": code})

@mcp.tool()
def get_wrangle_code(ctx: Context, node_path: str) -> str:
    """Get the VEX code from a wrangle node."""
    return _send_tool_command("get_wrangle_code", {"node_path": node_path})

@mcp.tool()
def create_vex_expression(ctx: Context, parent_path: str, attrib_name: str,
                          expression: str, run_over: str = "Points") -> str:
    """Create a wrangle that evaluates a VEX expression into an attribute."""
    return _send_tool_command("create_vex_expression", {
        "parent_path": parent_path, "attrib_name": attrib_name,
        "expression": expression, "run_over": run_over,
    })

@mcp.tool()
def validate_vex(ctx: Context, code: str) -> str:
    """Validate VEX code syntax."""
    return _send_tool_command("validate_vex", {"code": code})

# ── Material tools ──

@mcp.tool()
def list_materials(ctx: Context, mat_path: str = "/mat") -> str:
    """List all materials in a material network."""
    return _send_tool_command("list_materials", {"mat_path": mat_path})

@mcp.tool()
def get_material_info(ctx: Context, path: str) -> str:
    """Get detailed info about a material node."""
    return _send_tool_command("get_material_info", {"path": path})

@mcp.tool()
def create_material_network(ctx: Context, parent_path: str = "/obj",
                            name: str = "matnet") -> str:
    """Create a material network (matnet) node."""
    return _send_tool_command("create_material_network", {
        "parent_path": parent_path, "name": name,
    })

@mcp.tool()
def assign_material(ctx: Context, node_path: str, material_path: str) -> str:
    """Assign a material to a node by setting shop_materialpath."""
    return _send_tool_command("assign_material", {
        "node_path": node_path, "material_path": material_path,
    })

@mcp.tool()
def list_material_types(ctx: Context) -> str:
    """List available material/shader node types."""
    return _send_tool_command("list_material_types")

# ── Nodes expanded tools ──

@mcp.tool()
def copy_node(ctx: Context, path: str, destination_path: str) -> str:
    """Copy a node to a new parent network."""
    return _send_tool_command("copy_node", {"path": path, "destination_path": destination_path})

@mcp.tool()
def move_node(ctx: Context, path: str, destination_path: str) -> str:
    """Move a node to a new parent network."""
    return _send_tool_command("move_node", {"path": path, "destination_path": destination_path})

@mcp.tool()
def rename_node(ctx: Context, path: str, new_name: str) -> str:
    """Rename a node."""
    return _send_tool_command("rename_node", {"path": path, "new_name": new_name})

@mcp.tool()
def list_children(ctx: Context, path: str, recursive: bool = False) -> str:
    """List all children of a node, optionally recursive."""
    return _send_tool_command("list_children", {"path": path, "recursive": recursive})

@mcp.tool()
def find_nodes(ctx: Context, pattern: str, node_type: str = None,
               root_path: str = "/") -> str:
    """Find nodes matching a name pattern, optionally filtered by type."""
    params = {"pattern": pattern, "root_path": root_path}
    if node_type is not None:
        params["node_type"] = node_type
    return _send_tool_command("find_nodes", params)

@mcp.tool()
def list_node_types(ctx: Context, category: str = None) -> str:
    """List available node types, optionally filtered by category."""
    params = {}
    if category is not None:
        params["category"] = category
    return _send_tool_command("list_node_types", params)

@mcp.tool()
def connect_nodes_batch(ctx: Context, connections: List[Dict[str, Any]]) -> str:
    """Connect multiple node pairs at once. Each: {src_path, dst_path, dst_input_index, src_output_index}."""
    return _send_tool_command("connect_nodes_batch", {"connections": connections})

@mcp.tool()
def reorder_inputs(ctx: Context, path: str, input_indices: List[int]) -> str:
    """Reorder the inputs of a node by specifying the new index order."""
    return _send_tool_command("reorder_inputs", {"path": path, "input_indices": input_indices})

# ── Geometry expanded tools ──

@mcp.tool()
def get_points(ctx: Context, node_path: str, start: int = 0,
               count: int = 100, attribs: List[str] = None) -> str:
    """Get point data with pagination. Returns positions and optional attrib values."""
    params = {"node_path": node_path, "start": start, "count": count}
    if attribs is not None:
        params["attribs"] = attribs
    return _send_tool_command("get_points", params)

@mcp.tool()
def get_prims(ctx: Context, node_path: str, start: int = 0,
              count: int = 100, attribs: List[str] = None) -> str:
    """Get primitive data with pagination."""
    params = {"node_path": node_path, "start": start, "count": count}
    if attribs is not None:
        params["attribs"] = attribs
    return _send_tool_command("get_prims", params)

@mcp.tool()
def get_attrib_values(ctx: Context, node_path: str, attrib_name: str,
                      attrib_class: str = "point") -> str:
    """Get all values of a geometry attribute. attrib_class: point, prim, detail."""
    return _send_tool_command("get_attrib_values", {
        "node_path": node_path, "attrib_name": attrib_name, "attrib_class": attrib_class,
    })

@mcp.tool()
def set_detail_attrib(ctx: Context, node_path: str, attrib_name: str, value: Any) -> str:
    """Set a detail (global) attribute value on geometry."""
    return _send_tool_command("set_detail_attrib", {
        "node_path": node_path, "attrib_name": attrib_name, "value": value,
    })

@mcp.tool()
def get_groups(ctx: Context, node_path: str, group_type: str = "point") -> str:
    """List geometry groups. group_type: point, prim, edge, vertex."""
    return _send_tool_command("get_groups", {"node_path": node_path, "group_type": group_type})

@mcp.tool()
def get_group_members(ctx: Context, node_path: str, group_name: str,
                      group_type: str = "point") -> str:
    """Get the members of a geometry group."""
    return _send_tool_command("get_group_members", {
        "node_path": node_path, "group_name": group_name, "group_type": group_type,
    })

@mcp.tool()
def get_bounding_box(ctx: Context, node_path: str) -> str:
    """Get the bounding box of a node's geometry (min, max, size, center)."""
    return _send_tool_command("get_bounding_box", {"node_path": node_path})

@mcp.tool()
def get_prim_intrinsics(ctx: Context, node_path: str, prim_index: int = 0) -> str:
    """Get intrinsic values of a primitive."""
    return _send_tool_command("get_prim_intrinsics", {"node_path": node_path, "prim_index": prim_index})

@mcp.tool()
def find_nearest_point(ctx: Context, node_path: str, position: List[float]) -> str:
    """Find the nearest point to a given position in world space."""
    return _send_tool_command("find_nearest_point", {"node_path": node_path, "position": position})

# ── Code expanded tools ──

@mcp.tool()
def execute_hscript(ctx: Context, command: str) -> str:
    """Execute an HScript command and return stdout/stderr."""
    return _send_tool_command("execute_hscript", {"command": command})

@mcp.tool()
def evaluate_expression(ctx: Context, expression: str, language: str = "hscript") -> str:
    """Evaluate a Houdini expression and return the result."""
    return _send_tool_command("evaluate_expression", {"expression": expression, "language": language})

@mcp.tool()
def get_env_variable(ctx: Context, name: str) -> str:
    """Get a Houdini environment variable ($HIP, $JOB, etc.)."""
    return _send_tool_command("get_env_variable", {"name": name})

# ── PDG tools ──

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


# ── DOP tools ──

@mcp.tool()
def get_simulation_info(ctx: Context, path: str) -> str:
    """Get simulation info from a DOP network."""
    return _send_tool_command("get_simulation_info", {"path": path})

@mcp.tool()
def list_dop_objects(ctx: Context, path: str) -> str:
    """List all DOP objects in a simulation."""
    return _send_tool_command("list_dop_objects", {"path": path})

@mcp.tool()
def get_dop_object(ctx: Context, path: str, object_name: str) -> str:
    """Get info about a specific DOP object."""
    return _send_tool_command("get_dop_object", {"path": path, "object_name": object_name})

@mcp.tool()
def get_dop_field(ctx: Context, path: str, object_name: str, field_name: str) -> str:
    """Get a specific field from a DOP object."""
    return _send_tool_command("get_dop_field", {
        "path": path, "object_name": object_name, "field_name": field_name,
    })

@mcp.tool()
def get_dop_relationships(ctx: Context, path: str, object_name: str) -> str:
    """Get relationships of a DOP object."""
    return _send_tool_command("get_dop_relationships", {"path": path, "object_name": object_name})

@mcp.tool()
def step_simulation(ctx: Context, path: str, num_steps: int = 1) -> str:
    """Step a simulation forward by a number of frames."""
    return _send_tool_command("step_simulation", {"path": path, "num_steps": num_steps})

@mcp.tool()
def reset_simulation(ctx: Context, path: str) -> str:
    """Reset a simulation to its initial state."""
    return _send_tool_command("reset_simulation", {"path": path})

@mcp.tool()
def get_sim_memory_usage(ctx: Context, path: str) -> str:
    """Get memory usage of a simulation."""
    return _send_tool_command("get_sim_memory_usage", {"path": path})

# ── Viewport tools ──

@mcp.tool()
def list_panes(ctx: Context) -> str:
    """List all pane tabs in the Houdini desktop."""
    return _send_tool_command("list_panes")

@mcp.tool()
def get_viewport_info(ctx: Context) -> str:
    """Get current viewport settings (camera, shading, etc.)."""
    return _send_tool_command("get_viewport_info")

@mcp.tool()
def set_viewport_camera(ctx: Context, camera_path: str) -> str:
    """Set the viewport camera to a specific camera node."""
    return _send_tool_command("set_viewport_camera", {"camera_path": camera_path})

@mcp.tool()
def set_viewport_display(ctx: Context, shading_mode: str = None,
                         guide: bool = None) -> str:
    """Set viewport display options (shading mode, guides)."""
    params = {}
    if shading_mode is not None:
        params["shading_mode"] = shading_mode
    if guide is not None:
        params["guide"] = guide
    return _send_tool_command("set_viewport_display", params)

@mcp.tool()
def set_viewport_renderer(ctx: Context, renderer: str) -> str:
    """Set the viewport renderer."""
    return _send_tool_command("set_viewport_renderer", {"renderer": renderer})

@mcp.tool()
def frame_selection(ctx: Context) -> str:
    """Frame the viewport on the current selection."""
    return _send_tool_command("frame_selection")

@mcp.tool()
def frame_all(ctx: Context) -> str:
    """Frame the viewport on all geometry."""
    return _send_tool_command("frame_all")

@mcp.tool()
def set_viewport_direction(ctx: Context, direction: str) -> str:
    """Set viewport direction: front, back, left, right, top, bottom, persp."""
    return _send_tool_command("set_viewport_direction", {"direction": direction})

@mcp.tool()
def capture_screenshot(ctx: Context, output_path: str = None) -> str:
    """Capture a screenshot of the current viewport."""
    params = {}
    if output_path is not None:
        params["output_path"] = output_path
    return _send_tool_command("capture_screenshot", params)

@mcp.tool()
def set_current_network(ctx: Context, path: str) -> str:
    """Set the current network path in the network editor."""
    return _send_tool_command("set_current_network", {"path": path})

# ── Rendering expanded tools ──

@mcp.tool()
def list_render_nodes(ctx: Context) -> str:
    """List all ROP (render) nodes in the scene."""
    return _send_tool_command("list_render_nodes")

@mcp.tool()
def get_render_settings(ctx: Context, path: str) -> str:
    """Get render settings from a ROP node."""
    return _send_tool_command("get_render_settings", {"path": path})

@mcp.tool()
def set_render_settings(ctx: Context, path: str, settings: Dict[str, Any]) -> str:
    """Set render settings on a ROP node."""
    return _send_tool_command("set_render_settings", {"path": path, "settings": settings})

@mcp.tool()
def create_render_node(ctx: Context, render_type: str = "opengl",
                       name: str = None, parent_path: str = "/out") -> str:
    """Create a ROP (render) node."""
    params = {"render_type": render_type, "parent_path": parent_path}
    if name is not None:
        params["name"] = name
    return _send_tool_command("create_render_node", params)

@mcp.tool()
def start_render(ctx: Context, path: str, frame_range: List[float] = None) -> str:
    """Start a render from a ROP node."""
    params = {"path": path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return _send_tool_command("start_render", params)

@mcp.tool()
def get_render_progress(ctx: Context, path: str) -> str:
    """Get render progress from a ROP node."""
    return _send_tool_command("get_render_progress", {"path": path})

# ── COP tools ──

@mcp.tool()
def get_cop_info(ctx: Context, path: str) -> str:
    """Get info about a COP node: resolution, planes, depth."""
    return _send_tool_command("get_cop_info", {"path": path})

@mcp.tool()
def get_cop_geometry(ctx: Context, path: str) -> str:
    """Get geometry data from a COP node."""
    return _send_tool_command("get_cop_geometry", {"path": path})

@mcp.tool()
def get_cop_layer(ctx: Context, path: str, plane_name: str = "C") -> str:
    """Get info about a specific plane/layer in a COP node."""
    return _send_tool_command("get_cop_layer", {"path": path, "plane_name": plane_name})

@mcp.tool()
def create_cop_node(ctx: Context, parent_path: str, node_type: str,
                    name: str = None) -> str:
    """Create a COP node."""
    params = {"parent_path": parent_path, "node_type": node_type}
    if name is not None:
        params["name"] = name
    return _send_tool_command("create_cop_node", params)

@mcp.tool()
def set_cop_flags(ctx: Context, node_path: str, display: bool = None,
                  render: bool = None, bypass: bool = None) -> str:
    """Set display/render/bypass flags on a COP node."""
    params = {"node_path": node_path}
    if display is not None:
        params["display"] = display
    if render is not None:
        params["render"] = render
    if bypass is not None:
        params["bypass"] = bypass
    return _send_tool_command("set_cop_flags", params)

@mcp.tool()
def list_cop_node_types(ctx: Context) -> str:
    """List available COP node types."""
    return _send_tool_command("list_cop_node_types")

@mcp.tool()
def get_cop_vdb(ctx: Context, path: str) -> str:
    """Get VDB info from a COP node."""
    return _send_tool_command("get_cop_vdb", {"path": path})

# ── CHOP tools ──

@mcp.tool()
def get_chop_data(ctx: Context, path: str, channel: str = None,
                  start: int = None, end: int = None) -> str:
    """Get CHOP channel data, optionally for a specific channel and sample range."""
    params = {"path": path}
    if channel is not None:
        params["channel"] = channel
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    return _send_tool_command("get_chop_data", params)

@mcp.tool()
def create_chop_node(ctx: Context, parent_path: str, node_type: str,
                     name: str = None) -> str:
    """Create a CHOP node."""
    params = {"parent_path": parent_path, "node_type": node_type}
    if name is not None:
        params["name"] = name
    return _send_tool_command("create_chop_node", params)

@mcp.tool()
def list_chop_channels(ctx: Context, path: str) -> str:
    """List all channels in a CHOP node."""
    return _send_tool_command("list_chop_channels", {"path": path})

@mcp.tool()
def export_chop_to_parm(ctx: Context, chop_path: str, channel_name: str,
                        target_path: str, parm_name: str) -> str:
    """Export a CHOP channel to a parameter via expression."""
    return _send_tool_command("export_chop_to_parm", {
        "chop_path": chop_path, "channel_name": channel_name,
        "target_path": target_path, "parm_name": parm_name,
    })

# ── Takes tools ──

@mcp.tool()
def list_takes(ctx: Context) -> str:
    """List all takes in the scene."""
    return _send_tool_command("list_takes")

@mcp.tool()
def get_current_take(ctx: Context) -> str:
    """Get the current take."""
    return _send_tool_command("get_current_take")

@mcp.tool()
def set_current_take(ctx: Context, take_name: str) -> str:
    """Set the current take by name."""
    return _send_tool_command("set_current_take", {"take_name": take_name})

@mcp.tool()
def create_take(ctx: Context, name: str, parent_name: str = None) -> str:
    """Create a new take, optionally under a parent take."""
    params = {"name": name}
    if parent_name is not None:
        params["parent_name"] = parent_name
    return _send_tool_command("create_take", params)

# ── Cache tools ──

@mcp.tool()
def list_caches(ctx: Context, root_path: str = "/obj") -> str:
    """List all nodes with cache data."""
    return _send_tool_command("list_caches", {"root_path": root_path})

@mcp.tool()
def get_cache_status(ctx: Context, path: str) -> str:
    """Get cache status for a file cache node."""
    return _send_tool_command("get_cache_status", {"path": path})

@mcp.tool()
def clear_cache(ctx: Context, path: str) -> str:
    """Clear cache on a file cache node."""
    return _send_tool_command("clear_cache", {"path": path})

@mcp.tool()
def write_cache(ctx: Context, path: str, frame_range: List[float] = None) -> str:
    """Write cache for a file cache node."""
    params = {"path": path}
    if frame_range is not None:
        params["frame_range"] = frame_range
    return _send_tool_command("write_cache", params)

# ── USD/LOP expanded tools ──

@mcp.tool()
def list_usd_prims(ctx: Context, path: str, root_prim: str = "/",
                   max_depth: int = 3) -> str:
    """List USD prims up to a given depth."""
    return _send_tool_command("list_usd_prims", {"path": path, "root_prim": root_prim, "max_depth": max_depth})

@mcp.tool()
def get_usd_attribute(ctx: Context, path: str, prim_path: str,
                      attr_name: str) -> str:
    """Get a specific USD attribute value."""
    return _send_tool_command("get_usd_attribute", {
        "path": path, "prim_path": prim_path, "attr_name": attr_name,
    })

@mcp.tool()
def set_usd_attribute(ctx: Context, path: str, prim_path: str,
                      attr_name: str, value: Any) -> str:
    """Set a USD attribute value."""
    return _send_tool_command("set_usd_attribute", {
        "path": path, "prim_path": prim_path, "attr_name": attr_name, "value": value,
    })

@mcp.tool()
def get_usd_prim_stats(ctx: Context, path: str, prim_path: str) -> str:
    """Get stats about a USD prim: child count, attr count, active, payload."""
    return _send_tool_command("get_usd_prim_stats", {"path": path, "prim_path": prim_path})

@mcp.tool()
def get_last_modified_prims(ctx: Context, path: str, count: int = 10) -> str:
    """Get recently modified prims from the edit target layer."""
    return _send_tool_command("get_last_modified_prims", {"path": path, "count": count})

@mcp.tool()
def create_lop_node(ctx: Context, parent_path: str, node_type: str,
                    name: str = None) -> str:
    """Create a LOP node."""
    params = {"parent_path": parent_path, "node_type": node_type}
    if name is not None:
        params["name"] = name
    return _send_tool_command("create_lop_node", params)

@mcp.tool()
def get_usd_composition(ctx: Context, path: str, prim_path: str) -> str:
    """Get composition arcs (references, payloads, inherits, specializes) for a prim."""
    return _send_tool_command("get_usd_composition", {"path": path, "prim_path": prim_path})

@mcp.tool()
def get_usd_variants(ctx: Context, path: str, prim_path: str) -> str:
    """Get variant sets and selections for a USD prim."""
    return _send_tool_command("get_usd_variants", {"path": path, "prim_path": prim_path})

@mcp.tool()
def inspect_usd_layer(ctx: Context, path: str, layer_index: int = 0) -> str:
    """Inspect a specific USD layer by index in the stack."""
    return _send_tool_command("inspect_usd_layer", {"path": path, "layer_index": layer_index})

@mcp.tool()
def list_lights(ctx: Context, path: str) -> str:
    """List all light prims in a USD stage."""
    return _send_tool_command("list_lights", {"path": path})

# ── Workflow template tools ──

@mcp.tool()
def setup_pyro_sim(ctx: Context, source_path: str, name: str = "pyro_sim",
                   parent_path: str = "/obj") -> str:
    """Set up a Pyro simulation from a source geometry."""
    return _send_tool_command("setup_pyro_sim", {
        "source_path": source_path, "name": name, "parent_path": parent_path,
    })

@mcp.tool()
def setup_rbd_sim(ctx: Context, source_path: str, name: str = "rbd_sim",
                  parent_path: str = "/obj") -> str:
    """Set up an RBD simulation from a source geometry."""
    return _send_tool_command("setup_rbd_sim", {
        "source_path": source_path, "name": name, "parent_path": parent_path,
    })

@mcp.tool()
def setup_flip_sim(ctx: Context, source_path: str, name: str = "flip_sim",
                   parent_path: str = "/obj") -> str:
    """Set up a FLIP fluid simulation from a source geometry."""
    return _send_tool_command("setup_flip_sim", {
        "source_path": source_path, "name": name, "parent_path": parent_path,
    })

@mcp.tool()
def setup_vellum_sim(ctx: Context, source_path: str, sim_type: str = "cloth",
                     name: str = "vellum_sim", parent_path: str = "/obj") -> str:
    """Set up a Vellum simulation (cloth, hair, grain)."""
    return _send_tool_command("setup_vellum_sim", {
        "source_path": source_path, "sim_type": sim_type, "name": name, "parent_path": parent_path,
    })

@mcp.tool()
def create_material_workflow(ctx: Context, name: str = "mat_principled",
                             parent_path: str = "/mat",
                             material_type: str = "principledshader") -> str:
    """Create a material node in a material context."""
    return _send_tool_command("create_material_workflow", {
        "name": name, "parent_path": parent_path, "material_type": material_type,
    })

@mcp.tool()
def assign_material_workflow(ctx: Context, geo_path: str, material_path: str) -> str:
    """Assign a material to a geometry node."""
    return _send_tool_command("assign_material_workflow", {
        "geo_path": geo_path, "material_path": material_path,
    })

@mcp.tool()
def build_sop_chain(ctx: Context, parent_path: str,
                    nodes: List[Dict[str, Any]]) -> str:
    """Build a chain of SOP nodes connected in sequence. Each: {type, name?, parameters?}."""
    return _send_tool_command("build_sop_chain", {"parent_path": parent_path, "nodes": nodes})

@mcp.tool()
def setup_render(ctx: Context, camera_path: str = None,
                 render_engine: str = "karma", output_path: str = None) -> str:
    """Set up a render node in /out with camera and output path."""
    params = {"render_engine": render_engine}
    if camera_path is not None:
        params["camera_path"] = camera_path
    if output_path is not None:
        params["output_path"] = output_path
    return _send_tool_command("setup_render", params)

# ── HDA expanded tools ──

@mcp.tool()
def uninstall_hda(ctx: Context, file_path: str) -> str:
    """Uninstall an HDA file from the current session."""
    return _send_tool_command("uninstall_hda", {"file_path": file_path})

@mcp.tool()
def reload_hda(ctx: Context, file_path: str) -> str:
    """Reload all HDA definitions from a file."""
    return _send_tool_command("reload_hda", {"file_path": file_path})

@mcp.tool()
def update_hda(ctx: Context, node_path: str) -> str:
    """Update an HDA definition from its current node contents."""
    return _send_tool_command("update_hda", {"node_path": node_path})

@mcp.tool()
def get_hda_sections(ctx: Context, node_type: str, category: str = None) -> str:
    """Get the section names of an HDA."""
    params = {"node_type": node_type}
    if category is not None:
        params["category"] = category
    return _send_tool_command("get_hda_sections", params)

@mcp.tool()
def get_hda_section_content(ctx: Context, node_type: str, section_name: str,
                            category: str = None) -> str:
    """Get the content of a specific HDA section."""
    params = {"node_type": node_type, "section_name": section_name}
    if category is not None:
        params["category"] = category
    return _send_tool_command("get_hda_section_content", params)

@mcp.tool()
def set_hda_section_content(ctx: Context, node_type: str, section_name: str,
                            content: str, category: str = None) -> str:
    """Set the content of a specific HDA section."""
    params = {"node_type": node_type, "section_name": section_name, "content": content}
    if category is not None:
        params["category"] = category
    return _send_tool_command("set_hda_section_content", params)

# ── Event tools ──

@mcp.tool()
def get_houdini_events(ctx: Context, since: float = None) -> str:
    """Get pending Houdini events (scene changes, node operations, frame changes).
    Returns buffered events since last poll and clears the buffer.
    Optionally pass a timestamp to only get events after that time."""
    params = {}
    if since is not None:
        params["since"] = since
    return _send_tool_command("get_pending_events", params)

@mcp.tool()
def subscribe_houdini_events(ctx: Context, types: List[str] = None) -> str:
    """Configure which Houdini event types to collect.
    Types: scene_loaded, scene_saved, scene_cleared, node_created, node_deleted, frame_changed.
    Pass None/empty for all events."""
    params = {}
    if types is not None:
        params["types"] = types
    return _send_tool_command("subscribe_events", params)


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


_RENDER_PROCESS_NAMES = ("husk", "mantra-bin")


def _find_render_processes() -> List[Dict[str, str]]:
    """Detect running husk/mantra-bin processes via OS process listing.

    Returns a list of dicts with keys: name, pid, cpu_time, command.
    Works on Linux/macOS (ps aux) and Windows (tasklist /FO CSV /V).
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=10,
        )
        processes = []
        for line in result.stdout.splitlines()[1:]:  # skip header
            lower = line.lower()
            for name in _RENDER_PROCESS_NAMES:
                if name in lower:
                    parts = line.strip('"').split('","')
                    processes.append({
                        "name": parts[0] if parts else name,
                        "pid": parts[1] if len(parts) > 1 else "?",
                        "cpu_time": parts[7] if len(parts) > 7 else "?",
                        "command": parts[0] if parts else name,
                    })
        return processes

    # Linux / macOS
    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True, timeout=10,
    )
    processes = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        lower = line.lower()
        for name in _RENDER_PROCESS_NAMES:
            if name in lower:
                cols = line.split(None, 10)
                processes.append({
                    "name": name,
                    "pid": cols[1] if len(cols) > 1 else "?",
                    "cpu_time": cols[9] if len(cols) > 9 else "?",
                    "command": cols[10] if len(cols) > 10 else line.strip(),
                })
    return processes


@mcp.tool()
def monitor_render(ctx: Context, output_path: str = None) -> str:
    """Check if a Karma (husk) or Mantra (mantra-bin) render is still running.
    Optionally pass output_path to also report file existence and size.
    No Houdini connection needed — runs on the bridge side."""
    processes = _find_render_processes()
    info: Dict[str, Any] = {
        "rendering": len(processes) > 0,
        "process_count": len(processes),
        "processes": processes,
    }
    if output_path is not None:
        if os.path.exists(output_path):
            info["output_file"] = {
                "exists": True,
                "size_bytes": os.path.getsize(output_path),
            }
        else:
            info["output_file"] = {"exists": False}
    return json.dumps(info, indent=2)


# ── MCP Resources ──

@mcp.resource("houdini://scene/info")
def resource_scene_info() -> str:
    """Current scene info: filename, node count, frame range, FPS."""
    return _send_tool_command("get_scene_info")

@mcp.resource("houdini://scene/nodes/{path}")
def resource_node_info(path: str) -> str:
    """Detailed info about a node: type, parameters, inputs, outputs."""
    return _send_tool_command("get_node_info", {"path": f"/{path}"})

@mcp.resource("houdini://scene/tree")
def resource_scene_tree() -> str:
    """Full scene node tree (recursive children of /obj)."""
    return _send_tool_command("list_children", {"path": "/obj", "recursive": True})

@mcp.resource("houdini://errors")
def resource_errors() -> str:
    """All cook errors and warnings in the scene."""
    return _send_tool_command("find_error_nodes", {"root_path": "/obj"})

@mcp.resource("houdini://node-types/{context}")
def resource_node_types(context: str) -> str:
    """Available node types for a given category (Sop, Object, Cop2, etc.)."""
    return _send_tool_command("list_node_types", {"category": context})

@mcp.resource("houdini://hdas")
def resource_hdas() -> str:
    """All installed HDA definitions."""
    return _send_tool_command("hda_list")

@mcp.resource("houdini://geometry/{node_path}/summary")
def resource_geo_summary(node_path: str) -> str:
    """Geometry summary for a node: point/prim/vertex counts, bbox, attribs."""
    return _send_tool_command("get_geo_summary", {"node_path": f"/{node_path}"})

@mcp.resource("houdini://usd/{node_path}/stage")
def resource_usd_stage(node_path: str) -> str:
    """USD stage info from a LOP node."""
    return _send_tool_command("lop_stage_info", {"path": f"/{node_path}"})


# ── MCP Prompts ──

@mcp.prompt()
def procedural_modeling_workflow() -> str:
    """Guide for building a procedural SOP modeling chain in Houdini."""
    return """You are helping build a procedural SOP modeling chain in Houdini.

Steps:
1. Use get_scene_info to understand the current scene
2. Create a geometry container with create_node (type="geo", parent="/obj")
3. Build a chain of SOP nodes using build_sop_chain or individual create_node calls
4. Common SOP types: box, sphere, grid, tube, torus, circle, line
5. Transform with: xform, blast, delete, group, attribwrangle
6. Boolean with: boolean, intersect, subtract
7. Refine with: subdivide, polyextrude, polybevel, remesh
8. Use connect_nodes to wire them together
9. Set display/render flags with set_node_flags on the final node
10. Use layout_children to organize the network
11. Render with render_single_view to verify the result

Always check for errors with find_error_nodes after building the chain."""


@mcp.prompt()
def usd_scene_assembly() -> str:
    """Guide for assembling a USD scene with LOPs, materials, and lighting."""
    return """You are helping assemble a USD scene using Houdini's LOPs (Solaris).

Steps:
1. Use get_scene_info to check the current scene
2. Create a LOP network: create_node(type="lopnet", parent="/obj")
3. Import geometry: create_lop_node with type="sopimport" or lop_import for USD files
4. Add materials: create_material_workflow, then assign via set_usd_attribute
5. Add lights: create_lop_node with light types (distantlight, domelight, spherelight)
6. Set light parameters with modify_node
7. Configure render settings: setup_render with camera_path and render_engine
8. Use list_usd_prims to verify the stage hierarchy
9. Use lop_stage_info for stage overview
10. Render with render_single_view or start_render

Check composition with get_usd_composition and variants with get_usd_variants."""


@mcp.prompt()
def simulation_setup() -> str:
    """Guide for setting up Pyro/FLIP/RBD/Vellum simulations."""
    return """You are helping set up a simulation in Houdini.

Workflow templates (one-call setup):
- Pyro: setup_pyro_sim(source_path, name)
- RBD: setup_rbd_sim(source_path, name)
- FLIP: setup_flip_sim(source_path, name)
- Vellum: setup_vellum_sim(source_path, sim_type="cloth|hair|grain")

Manual setup:
1. Create source geometry (SOP level)
2. Create DOP network: create_node(type="dopnet")
3. Add appropriate solver nodes
4. Configure solver parameters with set_parameter/set_parameters
5. Set simulation frame range with set_frame_range
6. Run simulation: step_simulation or use the playbar

Monitoring:
- get_simulation_info — memory usage, object count
- list_dop_objects — all simulation objects
- get_dop_field — specific simulation data
- get_sim_memory_usage — track memory

Cache results:
- Use write_cache on file cache nodes
- Check cache with get_cache_status
- Clear with clear_cache when needed"""


@mcp.prompt()
def pdg_pipeline() -> str:
    """Guide for building a PDG/TOPs pipeline."""
    return """You are helping build a PDG (Procedural Dependency Graph) pipeline using TOPs.

Steps:
1. Create a TOP network: create_node(type="topnet", parent="/obj")
2. Add TOP nodes for your pipeline stages
3. Common TOP types: localscheduler, filepattern, ropfetch, pythonprocessor, waitforall
4. Connect nodes to define dependencies with connect_nodes
5. Cook the network: pdg_cook(path)
6. Monitor progress: pdg_status(path)
7. Check work items: pdg_workitems(path, state="cooked|cooking|waiting|failed")
8. If needed, dirty and re-cook: pdg_dirty(path) then pdg_cook(path)
9. Cancel if needed: pdg_cancel(path)

Tips:
- Use batch operations for efficiency
- Check errors with find_error_nodes
- Use pdg_workitems with state filter to find failures"""


@mcp.prompt()
def hda_development() -> str:
    """Guide for HDA (Houdini Digital Asset) development workflow."""
    return """You are helping develop an HDA (Houdini Digital Asset).

Creation:
1. Build your node network in a subnet
2. Create the HDA: hda_create(node_path, name, label, file_path)
3. The node becomes an HDA instance

Inspection:
- hda_list — see all installed HDAs
- hda_get — detailed info about an HDA type
- get_hda_sections — list sections (code, help, etc.)
- get_hda_section_content — read section content

Modification:
- set_hda_section_content — update section content (help text, scripts)
- update_hda — sync HDA definition from node changes
- reload_hda — reload from disk after external changes

Management:
- hda_install — install from .hda file
- uninstall_hda — remove from session
- Use get_node_info on HDA instances to see parameters

Best practices:
- Name with namespace: company::asset_name::1.0
- Add help text in the Help section
- Include OnCreated/OnLoaded scripts as needed
- Test with create_node after any definition changes"""


@mcp.prompt()
def debug_scene() -> str:
    """Systematic debugging checklist for Houdini scenes."""
    return """You are helping debug a Houdini scene. Follow this systematic approach:

1. Scene Overview:
   - get_scene_info — basic scene info
   - get_scene_summary — node counts by category

2. Find Errors:
   - find_error_nodes(root_path="/obj") — cook errors and warnings
   - Check specific nodes with get_node_info

3. Inspect Problem Nodes:
   - explain_node(path) — see non-default parms, connections
   - get_cook_chain(path) — trace dependency chain upstream
   - get_parameter(node_path, parm_name) — check specific values

4. Check Geometry:
   - get_geo_summary — point/prim counts, bbox, attribs
   - get_bounding_box — verify geometry is where expected
   - get_points/get_prims — inspect actual data

5. Check Connections:
   - get_network_overview — see all nodes and connections
   - list_children — verify node hierarchy

6. Performance:
   - get_sim_memory_usage — simulation memory
   - list_caches — find cache nodes
   - get_cache_status — check if caches are loaded

7. Fix Issues:
   - set_parameter — correct parameter values
   - revert_parameter — reset to defaults
   - connect_nodes/disconnect_node_input — fix wiring

8. Verify Fix:
   - render_single_view — visual verification
   - find_error_nodes — confirm errors resolved"""


def main():
    """Run the MCP server on stdio."""
    mcp.run()

if __name__ == "__main__":
    main()
