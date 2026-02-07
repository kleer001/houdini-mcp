# Phase 1: Borrow from oculairmedia/houdini-mcp

**Source:** https://github.com/oculairmedia/houdini-mcp

**Goal:** Go from 6 tools to ~22. Keep TCP socket transport — do not switch to hrpyc.

## 1A. Expose existing server.py handlers as MCP tools

These handlers already work in `server.py` but have no `@mcp.tool()` wrappers in `houdini_mcp_server.py`. Add MCP tool definitions only — no Houdini-side code needed.

- `modify_node` — rename, reposition, set parameters
- `delete_node` — remove node by path
- `get_node_info` — inspect node details, params, connections
- `set_material` — create/apply materials

## 1B. New tools (need both server.py handlers and MCP wrappers)

### Wiring & Connections

Reference: [oculairmedia tools/wiring.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/wiring.py)

- `connect_nodes(src_path, dst_path, dst_input_index, src_output_index)` — `node.setInput()`
- `disconnect_node_input(node_path, input_index)` — `node.setInput(idx, None)`
- `set_node_flags(node_path, display, render, bypass)` — flag toggling

### Scene Management

Reference: [oculairmedia tools/scene.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/scene.py)

- `save_scene(file_path?)` — `hou.hipFile.save()`
- `load_scene(file_path)` — `hou.hipFile.load()`

### Parameters

Reference: [oculairmedia tools/parameters.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/parameters.py)

- `set_expression(node_path, parm_name, expression, language)` — `parm.setExpression()`

### Animation

- `set_frame(frame)` — `hou.setFrame()`

### Geometry

Reference: [oculairmedia tools/geometry.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/geometry.py)

- `get_geo_summary(node_path)` — point/prim/vertex counts, bounding box, attribute names

### Layout & Organization

Reference: [oculairmedia tools/layout.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/layout.py)

- `layout_children(node_path)` — `node.layoutChildren()`
- `set_node_color(node_path, color)` — `node.setColor(hou.Color(r,g,b))`

### Error Detection

Reference: [oculairmedia tools/errors.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/errors.py)

- `find_error_nodes(root_path)` — scan hierarchy for cook errors/warnings

## 1C. Patterns to adopt (no new tools)

### Dangerous code detection

Reference: [oculairmedia tools/_common.py](https://github.com/oculairmedia/houdini-mcp/blob/main/houdini_mcp/tools/_common.py)

Add pattern-matching guard to `execute_houdini_code`. Block `hou.exit()`, `os.remove()`, `shutil.rmtree()`, `subprocess`, `os.system()`. Add `allow_dangerous` parameter to override.

### Undo groups

Reference: [MoleskinProductions houdini_bridge/server.py](https://github.com/MoleskinProductions/houdini-mcp/blob/main/houdini_bridge/server.py)

Wrap all mutation handlers in `server.py` with `hou.undos.group("MCP: <operation>")` so operations are reversible from Houdini's Edit menu.

### Response size guards

Add byte-size metadata to large responses. Truncate geometry/node data that exceeds reasonable limits. Add `max_results` / `compact` parameters where applicable.

## 1D. Deferred (evaluate later)

| Feature | Why defer |
|---------|----------|
| Switch to hrpyc | Entire transport rewrite. TCP works. |
| AI summarization | Adds Claude proxy dependency. |
| Pane screenshots | Requires GUI. Nice-to-have. |
| Test suite infrastructure | Worth borrowing eventually, not blocking. |
| Modular `tools/` file structure | Refactor after tool count warrants it (~Phase 2). |

## Verify

- All 22 tools respond correctly via MCP
- `connect_nodes` + `create_node` together can build a basic node graph
- `save_scene` / `load_scene` round-trip works
- `execute_houdini_code` rejects dangerous patterns by default
- Undo works in Houdini for all mutation operations
