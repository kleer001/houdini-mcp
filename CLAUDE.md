# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HoudiniMCP is a Model Context Protocol (MCP) bridge connecting SideFX Houdini to Claude AI. It enables Claude to programmatically control Houdini — creating/modifying nodes, executing code, rendering images, and importing 3D assets via the OPUS API.

## Running

```bash
# Run the MCP bridge server (communicates with Claude over stdio, with Houdini over TCP)
uv run python houdini_mcp_server.py

# Install dependencies
uv add "mcp[cli]"
```

There is no test suite. Testing requires a running Houdini instance with the plugin loaded on port 9876.

## Architecture

The system is a 3-layer bridge:

```
Claude (MCP stdio) → houdini_mcp_server.py (MCP Bridge) → TCP:9876 → server.py (Houdini Plugin) → Houdini API
```

### Layer 1: Houdini Plugin (`__init__.py`, `server.py`)
- Runs **inside** the Houdini process. Uses the `hou` module (Houdini Python API).
- `HoudiniMCPServer` listens on `localhost:9876` with a non-blocking TCP socket polled via Qt's `QTimer` to avoid freezing Houdini's UI.
- `execute_command()` is the central dispatcher — routes JSON commands (`create_node`, `modify_node`, `delete_node`, `get_node_info`, `execute_code`, `set_material`, `render_*`, `import_opus_url`) to handler methods.
- Responses are JSON: `{"status": "success/error", "result": {...}}`.
- Accumulates partial socket data in a buffer until a complete JSON object is received.

### Layer 2: MCP Bridge (`houdini_mcp_server.py`)
- Runs in a **separate** Python process (via `uv run`).
- `HoudiniConnection` class manages a persistent TCP connection to Houdini (global singleton via `get_houdini_connection()`).
- MCP tools are decorated with `@mcp.tool()` (using `fastmcp`).
- OPUS API calls (RapidAPI) are handled **directly** here, not forwarded to Houdini — only the final model import goes through the TCP bridge.
- Loads config from `urls.env` via `python-dotenv`.

### Layer 3: Rendering (`HoudiniMCPRender.py`)
- Utility module imported by `server.py` (runs inside Houdini).
- Handles camera rig setup, geometry bounding box calculation, and rendering (OpenGL, Karma, Mantra).
- `render_single_view()`, `render_quad_view()`, `render_specific_camera()` are the main entry points.
- Rendered images are base64-encoded for JSON transport.

## Key Patterns

- **Command dispatcher**: `server.py:execute_command()` routes by command type string to handler methods.
- **Global connection singleton**: `houdini_mcp_server.py` reuses one TCP connection across all MCP tool calls.
- **OPUS batch job flow**: Create batch → poll status → download ZIP → extract → import into Houdini.
- **Conditional imports**: `langchain` is optional (used for OPUS schema parsing); `HoudiniMCPRender` import is guarded.

## Dependencies

Declared in `pyproject.toml`: `mcp[cli]>=1.4.1`. Runtime also needs `requests`, `python-dotenv`, and optionally `langchain`. The Houdini-side code depends on `hou`, `PySide2`, and standard library modules.

## OPUS Integration

Requires a RapidAPI key in `urls.env`. The OPUS API provides procedural furniture/environment 3D assets. See README.md section 5 for setup.
