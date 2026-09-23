<p align="center">
  <img src="logos/banner_light.svg" alt="HoudiniMCP — Talk to Houdini." width="700"/>
</p>

<p align="center">
  <a href="https://github.com/kleer001/houdini-mcp/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kleer001/houdini-mcp?color=blue" alt="License: MIT"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+"/></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-compatible-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJ3aGl0ZSI+PHBhdGggZD0iTTEyIDJDNi40OCAyIDIgNi40OCAyIDEyczQuNDggMTAgMTAgMTAgMTAtNC40OCAxMC0xMFMxNy41MiAyIDEyIDJ6Ii8+PC9zdmc+" alt="MCP Compatible"/></a>
  <a href="https://www.sidefx.com/"><img src="https://img.shields.io/badge/Houdini-21.0-orange?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJ3aGl0ZSI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiLz48L3N2Zz4=&logoColor=white" alt="Houdini 21.0"/></a>
  <a href="https://github.com/kleer001/houdini-mcp/commits/main"><img src="https://img.shields.io/github/last-commit/kleer001/houdini-mcp" alt="Last Commit"/></a>
  <a href="https://github.com/kleer001/houdini-mcp/issues"><img src="https://img.shields.io/github/issues/kleer001/houdini-mcp" alt="Issues"/></a>
  <a href="https://github.com/kleer001/houdini-mcp/network/members"><img src="https://img.shields.io/github/forks/kleer001/houdini-mcp?style=social" alt="Forks"/></a>
  <a href="https://github.com/kleer001/houdini-mcp/watchers"><img src="https://img.shields.io/github/watchers/kleer001/houdini-mcp?style=social" alt="Watchers"/></a>
  <a href="https://github.com/kleer001/houdini-mcp/stargazers"><img src="https://img.shields.io/github/stars/kleer001/houdini-mcp?style=social" alt="GitHub Stars"/></a>
</p>

<p align="center">
  <strong>166 MCP tools</strong> &middot; <strong>30,000+ searchable documents</strong> &middot; <strong>Bidirectional events</strong>
</p>

---

Control **SideFX Houdini** from **Claude** using the **Model Context Protocol**. HoudiniMCP connects to your running Houdini instance — your license, your scene, your tools. The bridge talks to Houdini's Python API over a local TCP socket, so everything runs on your machine against your own installation. If no Houdini GUI is running, the bridge auto-launches a headless `hython` session so you can work without opening the UI.

- **166 MCP tools** — nodes, rendering, geometry, PDG/TOPs, USD/Solaris, HDAs, scene management, parameters, animation, VEX, DOPs, viewport, COPs, CHOPs, takes, cache, workflows
- **30,000+ searchable documents** — Houdini docs + patterns extracted from your Houdini install's example files
- **Bidirectional event system** — Houdini pushes scene changes to Claude in real time

## Get Started

**Prerequisites:** git and Python 3.10+. Houdini is optional at setup time.

**Linux / macOS:**
```bash
curl -sSL https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.sh | bash
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://raw.githubusercontent.com/kleer001/houdini-mcp/main/bootstrap.bat -OutFile bootstrap.bat; .\bootstrap.bat"
```

The bootstrap script clones the repo, installs [uv](https://docs.astral.sh/uv/), creates a venv, installs deps, sets up the Houdini plugin, optionally downloads offline docs, and configures your MCP client. Re-run from inside the repo at any time — it's idempotent. Full install is ~1 GB (mostly the documentation corpus).

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

This copies plugin files to your Houdini preferences directory, creates a packages JSON for auto-loading, and adds a startup hook (`pythonrc.py`) so the MCP server starts automatically when Houdini opens.

#### 2. Install MCP Dependencies

```bash
# Using uv (recommended)
cd /path/to/houdini-mcp
uv sync

# Or using pip
pip install "mcp[cli]"
```

#### 3. Configure Your MCP Client

**Claude Code (CLI):**
```bash
claude mcp add --transport stdio houdini -- uv --directory /path/to/houdini-mcp run python houdini_mcp_server.py
```

**Claude Desktop:** Go to **File > Settings > Developer > Edit Config** and add:

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

**ChatGPT Desktop:** ChatGPT only supports remote (HTTP) MCP servers, not local stdio. You'll need to wrap the bridge in an HTTP transport and expose it via a tunnel:

```bash
# 1. Run the MCP server with HTTP transport (requires mcp[cli])
uv --directory /path/to/houdini-mcp run fastmcp run houdini_mcp_server.py --transport http --port 8080

# 2. Expose it with ngrok (or Cloudflare Tunnel, etc.)
ngrok http 8080
```

Then in ChatGPT: **Settings > Connectors > Create** — paste the ngrok HTTPS URL as the Connector URL.

**Ollama (local LLM):** Ollama doesn't have a built-in MCP client. Use [ollama-mcp-bridge](https://github.com/jonigl/ollama-mcp-bridge) to connect:

```bash
pip install ollama-mcp-bridge
```

Create `mcp-config.json`:

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

```bash
ollama-mcp-bridge --config ./mcp-config.json
```

The bridge proxies Ollama's API and routes tool calls to HoudiniMCP automatically.

#### 4. Set Up Documentation Search

```bash
# Downloads Houdini docs and builds the BM25 index (~1 GB)
python scripts/fetch_houdini_docs.py
```

This enables the `search_docs` and `get_doc` tools — they work offline without a Houdini connection.

Optional: index the Redshift for Houdini manual as a separate source (`source="redshift"`).
The script downloads Maxon's official offline help ZIP (~2.7 GB) and keeps only the text:

```bash
python scripts/fetch_redshift_docs.py              # or: --zip PATH to use a ZIP on disk
```

Optional: index the Arnold core and HtoA user guides (`source="arnold"`). Autodesk offers no
offline copy, so the script fetches each page politely (~2 hours; a rerun resumes):

```bash
python scripts/fetch_arnold_docs.py
```

</details>

## What You Get

HoudiniMCP exposes 166 tools, 8 resources, and 6 prompts over MCP, organized by domain: scene management, node operations, scene context, parameters, code execution, materials, animation, VEX, geometry, rendering, viewport, DOPs, PDG/TOPs, USD/Solaris, COPs, CHOPs, takes, cache, HDA management, batch operations, workflow templates, events, and documentation search. The bridge runs as a separate process (`houdini_mcp_server.py`) and talks to the Houdini plugin over TCP.

```
Claude (MCP stdio) → houdini_mcp_server.py (Bridge) → TCP:9876 → server.py (Houdini Plugin) → hou API
                   ↘ houdini_rag.py (BM25 search — docs + patterns, local-only)
                   ↖ scripts/ingest_hips.py (pattern extraction from .hip files)

No Houdini running? Bridge auto-launches hython → headless_server.py → server.py → hou API
```

<details>
<summary><strong>All 166 MCP Tools</strong></summary>

### Scene Management (6)
| Tool | Description |
|------|-------------|
| `ping` | Health check — verify Houdini is connected |
| `get_connection_status` | Connection info (port, command count, timing) |
| `get_scene_info` | Scene summary (file, frame, FPS, node counts) |
| `save_scene` | Save current scene, optionally to a new path |
| `load_scene` | Load a .hip file |
| `set_frame` | Set the playbar frame |

### Scene Context (6)
| Tool | Description |
|------|-------------|
| `get_network_overview` | Overview of a network's children and connections |
| `get_cook_chain` | Trace upstream cook dependency chain |
| `explain_node` | Human-readable summary of a node's role |
| `get_scene_summary` | High-level scene statistics |
| `get_selection` | Get currently selected nodes |
| `set_selection` | Set the node selection |

### Node Operations (18)
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
| `copy_node` | Copy a node to a new parent |
| `move_node` | Move a node to a new parent |
| `rename_node` | Rename a node |
| `list_children` | List children of a node |
| `find_nodes` | Search for nodes by type/name pattern |
| `list_node_types` | List available node types for a context |
| `connect_nodes_batch` | Connect multiple node pairs at once |
| `reorder_inputs` | Reorder a node's input connections |

### Parameters (10)
| Tool | Description |
|------|-------------|
| `get_parameter` | Read a single parameter value |
| `set_parameter` | Set a single parameter value |
| `set_parameters` | Set multiple parameters at once |
| `get_parameter_schema` | Get parameter metadata (type, range, menu items) |
| `get_expression` | Get the expression on a parameter |
| `revert_parameter` | Revert a parameter to its default |
| `link_parameters` | Create a channel reference between parameters |
| `lock_parameter` | Lock or unlock a parameter |
| `create_spare_parameter` | Add a spare parameter to a node |
| `create_spare_parameters` | Add multiple spare parameters at once |

### Code Execution (4)
| Tool | Description |
|------|-------------|
| `execute_houdini_code` | Run Python code in Houdini (with safety guard) |
| `execute_hscript` | Run HScript commands |
| `evaluate_expression` | Evaluate an HScript or Python expression |
| `get_env_variable` | Get a Houdini environment variable |

### Materials (6)
| Tool | Description |
|------|-------------|
| `set_material` | Create or apply a material to an OBJ node |
| `list_materials` | List all materials in a context |
| `get_material_info` | Get material parameters and properties |
| `create_material_network` | Create a material network with a shader |
| `assign_material` | Assign a material to geometry |
| `list_material_types` | List available material/shader types |

### Animation (9)
| Tool | Description |
|------|-------------|
| `set_expression` | Set an HScript or Python expression on a parm |
| `set_keyframe` | Set a keyframe on a parameter |
| `set_keyframes` | Set multiple keyframes at once |
| `delete_keyframe` | Delete a keyframe at a frame |
| `get_keyframes` | Get all keyframes on a parameter |
| `get_frame` | Get the current frame |
| `set_frame_range` | Set the global frame range |
| `set_playback_range` | Set the playback frame range |
| `playbar_control` | Control playbar (play, stop, reverse, step) |

### VEX (5)
| Tool | Description |
|------|-------------|
| `create_wrangle` | Create an attribute wrangle node with VEX code |
| `set_wrangle_code` | Set VEX code on an existing wrangle |
| `get_wrangle_code` | Get VEX code from a wrangle |
| `create_vex_expression` | Create a wrangle with a VEX expression |
| `validate_vex` | Validate VEX syntax |

### Geometry (11)
| Tool | Description |
|------|-------------|
| `get_geo_summary` | Point/prim/vertex counts, bbox, attributes |
| `geo_export` | Export geometry (obj, gltf, glb, usd, ply, bgeo.sc) |
| `get_points` | Get point positions and attributes (paginated) |
| `get_prims` | Get primitive data and attributes (paginated) |
| `get_attrib_values` | Get attribute values for all elements |
| `set_detail_attrib` | Set a detail attribute value |
| `get_groups` | List point/prim groups |
| `get_group_members` | Get members of a group |
| `get_bounding_box` | Get geometry bounding box |
| `get_prim_intrinsics` | Get primitive intrinsic values |
| `find_nearest_point` | Find the nearest point to a position |

### Rendering (11)
| Tool | Description |
|------|-------------|
| `render_single_view` | Render a single viewport (OpenGL/Karma/Mantra) |
| `render_quad_views` | Render 4 canonical views |
| `render_specific_camera` | Render from a specific camera node |
| `render_flipbook` | Render a flipbook sequence |
| `monitor_render` | Check if a Karma/Mantra render is still running |
| `list_render_nodes` | List all ROP nodes in /out |
| `get_render_settings` | Get render node parameters |
| `set_render_settings` | Set render node parameters |
| `create_render_node` | Create a new ROP node |
| `start_render` | Start a render from a ROP node |
| `get_render_progress` | Get render progress percentage |

### Viewport (10)
| Tool | Description |
|------|-------------|
| `list_panes` | List all pane tabs in the desktop |
| `get_viewport_info` | Get viewport settings and camera info |
| `set_viewport_camera` | Set the viewport camera |
| `set_viewport_display` | Set viewport display options |
| `set_viewport_renderer` | Set viewport renderer (OpenGL, Karma, etc.) |
| `frame_selection` | Frame the viewport on selected nodes |
| `frame_all` | Frame all geometry in the viewport |
| `set_viewport_direction` | Set viewport to a standard direction |
| `capture_screenshot` | Capture a viewport screenshot |
| `set_current_network` | Set the current network editor path |

### DOPs (8)
| Tool | Description |
|------|-------------|
| `get_simulation_info` | Get simulation status and properties |
| `list_dop_objects` | List objects in a DOP simulation |
| `get_dop_object` | Get details of a DOP object |
| `get_dop_field` | Get a DOP field's data/stats |
| `get_dop_relationships` | Get DOP object relationships |
| `step_simulation` | Advance simulation by N frames |
| `reset_simulation` | Reset simulation to start frame |
| `get_sim_memory_usage` | Get simulation memory usage |

### PDG/TOPs (5)
| Tool | Description |
|------|-------------|
| `pdg_cook` | Start cooking a TOP network |
| `pdg_status` | Get cook status and work item counts |
| `pdg_workitems` | List work items (optionally by state) |
| `pdg_dirty` | Dirty work items for re-cooking |
| `pdg_cancel` | Cancel a running PDG cook |

### USD/Solaris (15)
| Tool | Description |
|------|-------------|
| `lop_stage_info` | USD stage summary (prims, layers, time) |
| `lop_prim_get` | Inspect a specific USD prim |
| `lop_prim_search` | Search prims by pattern and type |
| `lop_layer_info` | USD layer stack info |
| `lop_import` | Import USD via reference or sublayer |
| `list_usd_prims` | List USD prims with hierarchy traversal |
| `get_usd_attribute` | Get a USD prim attribute value |
| `set_usd_attribute` | Set a USD prim attribute value |
| `get_usd_prim_stats` | Get USD prim statistics |
| `get_last_modified_prims` | Get recently modified prims |
| `create_lop_node` | Create a LOP node |
| `get_usd_composition` | Get USD composition arcs |
| `get_usd_variants` | Get USD variant sets and selections |
| `inspect_usd_layer` | Inspect a USD layer |
| `list_lights` | List lights in the USD stage |

### COPs (7)
| Tool | Description |
|------|-------------|
| `get_cop_info` | Get COP node info and planes |
| `get_cop_geometry` | Get COP geometry data |
| `get_cop_layer` | Get COP layer/plane info |
| `create_cop_node` | Create a COP node |
| `set_cop_flags` | Set COP node flags |
| `list_cop_node_types` | List available COP node types |
| `get_cop_vdb` | Get COP VDB volume info |

### CHOPs (4)
| Tool | Description |
|------|-------------|
| `get_chop_data` | Get CHOP channel data and samples |
| `create_chop_node` | Create a CHOP node |
| `list_chop_channels` | List channels in a CHOP node |
| `export_chop_to_parm` | Export a CHOP channel to a parameter |

### Takes (4)
| Tool | Description |
|------|-------------|
| `list_takes` | List all takes in the scene |
| `get_current_take` | Get the current take |
| `set_current_take` | Set the current take |
| `create_take` | Create a new take |

### Cache (4)
| Tool | Description |
|------|-------------|
| `list_caches` | List all cache nodes in the scene |
| `get_cache_status` | Get cache node status |
| `clear_cache` | Clear a cache node |
| `write_cache` | Write/execute a cache node |

### HDA Management (10)
| Tool | Description |
|------|-------------|
| `hda_list` | List available HDA definitions |
| `hda_get` | Detailed info about an HDA |
| `hda_install` | Install an HDA file into the session |
| `hda_create` | Create an HDA from an existing node |
| `uninstall_hda` | Uninstall an HDA definition |
| `reload_hda` | Reload an HDA from disk |
| `update_hda` | Update an HDA definition from a node |
| `get_hda_sections` | List sections in an HDA |
| `get_hda_section_content` | Read content of an HDA section |
| `set_hda_section_content` | Write content to an HDA section |

### Workflow Templates (8)
| Tool | Description |
|------|-------------|
| `setup_pyro_sim` | Set up a Pyro simulation from source geometry |
| `setup_rbd_sim` | Set up an RBD simulation from source geometry |
| `setup_flip_sim` | Set up a FLIP fluid simulation |
| `setup_vellum_sim` | Set up a Vellum simulation (cloth, hair, grain) |
| `create_material_workflow` | Create a material in a material context |
| `assign_material_workflow` | Assign a material to geometry |
| `build_sop_chain` | Build a chain of connected SOP nodes |
| `setup_render` | Set up a render node with camera and output |

### Batch Operations (1)
| Tool | Description |
|------|-------------|
| `batch` | Execute multiple operations atomically |

### Event System (2)
| Tool | Description |
|------|-------------|
| `get_houdini_events` | Get pending Houdini events (scene/node/frame changes) |
| `subscribe_houdini_events` | Configure which event types to collect |

### Documentation Search (2)
| Tool | Description |
|------|-------------|
| `search_docs` | BM25 search across 30,000+ documents (no Houdini needed); `source` picks Houdini docs, the Redshift manual, or the Arnold guides |
| `get_doc` | Read full content of a doc page from any `source` |

</details>

## Shelf Tools

The installer adds a **HoudiniMCP** shelf with a **Toggle MCP Server** button that starts or stops the TCP server on localhost:9876.

## Headless Mode

If no Houdini GUI is running when the MCP bridge starts, it automatically launches a headless `hython` session with the TCP server. This means Claude can work with Houdini's Python API (nodes, geometry, parameters, USD, PDG, rendering, etc.) without opening the UI.

- **Auto-detected**: the bridge probes port 9876 on first tool call — if nothing is listening, it finds `hython` and starts it
- **Transparent**: same tools, same API — just no viewport or interactive UI
- **Cleanup**: the hython process is terminated when the MCP bridge shuts down
- **Disable**: set `HOUDINIMCP_NO_HEADLESS=1` to prevent auto-launch

hython is found via `$HFS/bin/hython`, `PATH`, or common install locations (`/opt/hfs*`, `C:\Program Files\Side Effects Software\*`).

> **Note:** GUI-only tools (viewport, screenshots, flipbook) won't work in headless mode. All node, geometry, parameter, rendering, USD, PDG, HDA, and code execution tools work normally.

<details>
<summary><strong>Ingest Pipeline</strong></summary>

The ingest pipeline extracts reusable patterns from Houdini's own example `.hip` files and HDA definitions, then indexes them alongside the documentation corpus for BM25 search.

```bash
# Run the full pipeline (discover → parse → extract HDAs → extract patterns → index)
python scripts/ingest_hips.py all

# Or run individual stages
python scripts/ingest_hips.py discover    # Find .hip files in Houdini install
python scripts/ingest_hips.py parse       # Parse .hip files (cpio format, no Houdini needed)
python scripts/ingest_hips.py extract-hdas # Extract HDA networks (requires hython)
python scripts/ingest_hips.py extract     # Extract patterns (scene graphs, subgraphs, recipes)
python scripts/ingest_hips.py index       # Build combined BM25 index (docs + patterns)
```

Pattern types extracted:
- **Scene graphs** — full node hierarchies from each .hip file
- **Subgraphs** — connected node clusters, deduplicated by topology
- **Recipes** — individual node configurations with parameter values

The combined index feeds the same `search_docs` and `get_doc` MCP tools used for documentation search.

</details>

<details>
<summary><strong>Documentation & Guides</strong></summary>

- [Best Practices](BEST_PRACTICES.md) — hard-won lessons from production use (COP pitfalls, diagnostics, etc.)
- [Getting Started](docs/GUIDE_GETTING_STARTED.md) — first-time setup walkthrough
- [Tools Reference](docs/GUIDE_TOOLS.md) — detailed tool documentation with examples
- [Events Guide](docs/GUIDE_EVENTS.md) — event system setup and usage
- [Troubleshooting](docs/TROUBLESHOOTING.md) — common issues and fixes
- [.hip Format Reference](docs/hip_format.md) — cpio-based .hip file format internals

</details>

## Skills

Skills are multi-step workflow guides that define how Claude should approach
complex, repeatable production tasks using HoudiniMCP. Unlike single tool calls,
skills orchestrate sequences of MCP tools, filesystem queries, and user
confirmation gates to complete high-level operations safely.

Skills live in the [`skills/`](skills/) folder. Invoke one by describing the task
to Claude — it will recognise the workflow and follow the skill's phases.

| Skill | Description |
|---|---|
| [`retarget-fx-shot`](skills/retarget-fx-shot.md) | Duplicate an FX rig network and remap all file references from one shot's sequences to another's |

---

## Best Practices — The Recipe Book

Houdini is deep software, and the best way to learn it is from someone who's already been there. [**BEST_PRACTICES.md**](BEST_PRACTICES.md) is a growing collection of practical recipes — the kind of knowledge that saves you hours.

Every entry follows the same format: **what we tried, what surprised us, and what works.** Tagged with the Houdini version so you know what applies to you.

This file is baked into Claude's context, so the AI builds on previous experience instead of starting from scratch. The more you use HoudiniMCP, the smarter it gets.

**Got recipes to share?** As you work with HoudiniMCP, your AI will add entries to its own `BEST_PRACTICES.md`. If you've accumulated useful ones, [open an issue](https://github.com/kleer001/houdini-mcp/issues/new?labels=best-practice&title=Best+Practices+Contribution&body=Paste+your+BEST_PRACTICES.md+contents+below%0A%0A---%0A%0A) and paste your file — we'll merge the good stuff in for everyone.

## Under the Hood

- **Zero external deps for search** — BM25 engine is pure stdlib Python, no numpy/scipy/nltk
- **Cpio parser for .hip files** — reads Houdini's binary scene format without Houdini installed
- **19,000+ patterns** extracted from Houdini's own example files, searchable alongside 11,000+ doc pages
- **Event deduplication** collapses rapid-fire callbacks (same type + path within 100ms)
- **Undo groups** wrap all mutating commands, dangerous code patterns blocked by default
- **256 tests**, all run without a Houdini instance

## Acknowledgements

HoudiniMCP builds on the work of several open-source projects:

- [blender-mcp](https://github.com/ahujasid/blender-mcp) by ahujasid — architectural inspiration (MCP bridge + TCP socket pattern)
- [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp) by capoomgit — first full-featured Houdini MCP implementation
- [eetumartola/houdini-mcp](https://github.com/eetumartola/houdini-mcp) by eetumartola — early Houdini MCP implementation
- [Houdini21MCP](https://github.com/orrzxz/Houdini21MCP) by orrzxz — documentation search engine
- [fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp) by healkeiser — comprehensive Houdini MCP with 167 tools across 19 categories (MIT license)

## License

MIT

---

<sub>HoudiniMCP is an independent community project and is not affiliated with, endorsed by, or sponsored by SideFX Software. Houdini and SideFX are trademarks of SideFX Software Inc.</sub>
