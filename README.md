# HoudiniMCP – Connect Houdini to Claude via Model Context Protocol

**HoudiniMCP** allows you to control **SideFX Houdini** from **Claude** using the **Model Context Protocol (MCP)**. It provides:

- **41 MCP tools** for nodes, rendering, geometry, PDG/TOPs, USD/Solaris, HDAs, scene management, and more
- **Offline documentation search** (BM25) across 11,000+ Houdini doc pages
- **Event system** for bidirectional communication (Houdini pushes scene changes to Claude)
- **Embedded Claude terminal** panel inside Houdini's UI with tabbed sessions

## Architecture

```
Claude (MCP stdio) → houdini_mcp_server.py (Bridge) → TCP:9876 → server.py (Houdini Plugin) → hou API
                   ↘ houdini_rag.py (docs search, local)
```

## Repository Structure

```
houdini_mcp_server.py          # MCP bridge entry point (uv run)
houdini_rag.py                 # BM25 docs search engine (stdlib only)
pyproject.toml
src/houdinimcp/
    __init__.py                # Plugin init (auto-start server)
    server.py                  # Houdini-side TCP server + command dispatcher
    handlers/                  # Handler modules by category
        scene.py               #   Scene management (save, load, frame, info)
        nodes.py               #   Node operations (create, modify, connect, flags)
        code.py                #   Code execution with safety guard
        geometry.py            #   Geometry inspection and export
        pdg.py                 #   PDG/TOPs (cook, status, work items)
        lop.py                 #   USD/Solaris (stages, prims, layers)
        hda.py                 #   HDA management (list, install, create)
        rendering.py           #   Rendering (OpenGL, Karma, Mantra, flipbook)
    event_collector.py         # Event system (scene/node/frame callbacks)
    HoudiniMCPRender.py        # Rendering utilities (camera rig, bbox)
    claude_terminal.py         # Embedded Claude terminal panel
    ClaudeTerminal.pypanel     # Houdini panel XML definition
scripts/
    install.py                 # Install plugin into Houdini prefs
    launch.py                  # Launch Houdini and/or MCP bridge
    fetch_houdini_docs.py      # Download Houdini docs and build search index
tests/                         # pytest test suite (69 tests)
docs/                          # User guides and implementation plans
```

---

## Quick Start

### One-Liner Install

**Linux / macOS:**
```bash
curl -sSL https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.bat -OutFile bootstrap.bat; .\bootstrap.bat"
```

The bootstrap script handles everything: clones the repo, installs [uv](https://docs.astral.sh/uv/) (to `~/.local/bin`), creates a venv, installs deps, sets up the Houdini plugin, downloads offline docs (~100 MB), and prints the Claude Desktop config snippet. Re-run from inside the repo at any time — it's idempotent.

**Prerequisites:** git and Python 3.12+ must be installed. Houdini is optional at setup time.

<details>
<summary><strong>Manual setup (step by step)</strong></summary>

#### 1. Install the Houdini Plugin

```bash
# Auto-detect Houdini version and install
python scripts/install.py

# Or specify version explicitly
python scripts/install.py --houdini-version 20.5

# Preview without changing anything
python scripts/install.py --dry-run
```

This copies plugin files to your Houdini preferences directory and creates a packages JSON for auto-loading.

#### 2. Install MCP Dependencies

```bash
# Using uv (recommended)
cd /path/to/houdini-mcp
uv sync

# Or using pip
pip install "mcp[cli]"
```

#### 3. Configure Claude Desktop

Go to **File > Settings > Developer > Edit Config** and add:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/houdini-mcp",
        "run",
        "python",
        "houdini_mcp_server.py"
      ]
    }
  }
}
```

#### 4. Set Up Documentation Search

```bash
# Downloads Houdini docs and builds the BM25 index (~100 MB)
python scripts/fetch_houdini_docs.py
```

This enables the `search_docs` and `get_doc` tools — they work offline without a Houdini connection.

</details>

---

## MCP Tools Reference

### Scene Management
| Tool | Description |
|------|-------------|
| `ping` | Health check — verify Houdini is connected |
| `get_connection_status` | Connection info (port, command count, timing) |
| `get_scene_info` | Scene summary (file, frame, FPS, node counts) |
| `save_scene` | Save current scene, optionally to a new path |
| `load_scene` | Load a .hip file |
| `set_frame` | Set the playbar frame |

### Node Operations
| Tool | Description |
|------|-------------|
| `create_node` | Create a node (type, parent, name) |
| `modify_node` | Rename, reposition, or change parameters |
| `delete_node` | Delete a node by path |
| `get_node_info` | Inspect a node (type, parms, inputs, outputs) |
| `connect_nodes` | Wire src output → dst input |
| `disconnect_node_input` | Disconnect a specific input |
| `set_node_flags` | Set display/render/bypass flags |
| `set_node_color` | Set a node's color [r, g, b] |
| `layout_children` | Auto-layout child nodes |
| `find_error_nodes` | Scan hierarchy for cook errors |

### Code Execution
| Tool | Description |
|------|-------------|
| `execute_houdini_code` | Run Python code in Houdini (with safety guard) |

### Materials
| Tool | Description |
|------|-------------|
| `set_material` | Create or apply a material to an OBJ node |

### Parameters & Animation
| Tool | Description |
|------|-------------|
| `set_expression` | Set an HScript or Python expression on a parm |

### Geometry
| Tool | Description |
|------|-------------|
| `get_geo_summary` | Point/prim/vertex counts, bbox, attributes |
| `geo_export` | Export geometry (obj, gltf, glb, usd, ply, bgeo.sc) |

### Rendering
| Tool | Description |
|------|-------------|
| `render_single_view` | Render a single viewport (OpenGL/Karma/Mantra) |
| `render_quad_views` | Render 4 canonical views |
| `render_specific_camera` | Render from a specific camera node |
| `render_flipbook` | Render a flipbook sequence |

### PDG/TOPs
| Tool | Description |
|------|-------------|
| `pdg_cook` | Start cooking a TOP network |
| `pdg_status` | Get cook status and work item counts |
| `pdg_workitems` | List work items (optionally by state) |
| `pdg_dirty` | Dirty work items for re-cooking |
| `pdg_cancel` | Cancel a running PDG cook |

### USD/Solaris (LOP)
| Tool | Description |
|------|-------------|
| `lop_stage_info` | USD stage summary (prims, layers, time) |
| `lop_prim_get` | Inspect a specific USD prim |
| `lop_prim_search` | Search prims by pattern and type |
| `lop_layer_info` | USD layer stack info |
| `lop_import` | Import USD via reference or sublayer |

### HDA Management
| Tool | Description |
|------|-------------|
| `hda_list` | List available HDA definitions |
| `hda_get` | Detailed info about an HDA |
| `hda_install` | Install an HDA file into the session |
| `hda_create` | Create an HDA from an existing node |

### Batch Operations
| Tool | Description |
|------|-------------|
| `batch` | Execute multiple operations atomically |

### Event System
| Tool | Description |
|------|-------------|
| `get_houdini_events` | Get pending Houdini events (scene/node/frame changes) |
| `subscribe_houdini_events` | Configure which event types to collect |

### Documentation Search (offline)
| Tool | Description |
|------|-------------|
| `search_docs` | BM25 search across Houdini docs (no Houdini needed) |
| `get_doc` | Read full content of a doc page |

---

## Embedded Claude Terminal

The plugin includes a dockable Python Panel that runs Claude Code inside Houdini:

- **Window > Python Panels > Claude Terminal**
- Tabbed sessions, font size control, dark/light theme
- Context injection: "Send Selection" and "Send Scene Info" buttons
- Auto-restart on unexpected exit
- Keyboard shortcuts: Ctrl+Shift+C (copy), Ctrl+=/- (font size)

---

## Shelf Tools

The installer adds a **HoudiniMCP** shelf to Houdini's toolbar with two buttons:

| Button | Icon | Action |
|--------|------|--------|
| **Claude Terminal** | IM_NewViewport | Opens the Claude Terminal panel in a floating window |
| **Toggle MCP Server** | BUTTONS_connected | Starts or stops the MCP TCP server on localhost:9876 |

The shelf is installed automatically by `scripts/install.py` (or the bootstrap script).

---

## Using with Cursor

Go to **Settings > MCP > Add new MCP server** and add the same config as Claude Desktop.

---

## Troubleshooting

- **"Could not connect to Houdini"**: Ensure the plugin is loaded and the server is running on port 9876. Check the Houdini console for error messages.
- **Claude can't find `mcp` package**: Verify `uv run python -c "import mcp; print('OK')"` works. If using system Python, ensure Claude Desktop is configured to use the same Python.
- **Docs search returns error**: Run `python scripts/fetch_houdini_docs.py` to download the documentation corpus and build the index.
- **Terminal panel not showing**: Ensure `ClaudeTerminal.pypanel` was installed to the `python_panels/` directory. Re-run `python scripts/install.py` if needed.

---

## Running Tests

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/ -v
```

---

## Acknowledgements

Houdini-MCP was built following [blender-mcp](https://github.com/ahujasid/blender-mcp). Documentation search engine based on [Houdini21MCP](https://github.com/orrzxz/Houdini21MCP).
