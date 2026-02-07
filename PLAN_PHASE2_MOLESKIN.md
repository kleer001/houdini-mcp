# Phase 2: Borrow from MoleskinProductions/houdini-mcp

**Source:** https://github.com/MoleskinProductions/houdini-mcp

**Goal:** Add production VFX pipeline tools — PDG, USD, HDA, batch ops, geometry export. ~22 tools to ~36.

## 2A. PDG/TOPs (5 tools)

Reference: [MoleskinProductions houdini_bridge/server.py](https://github.com/MoleskinProductions/houdini-mcp/blob/main/houdini_bridge/server.py) — search for `pdg` handlers

- `pdg_cook(path, tops_only)` — non-blocking `node.executeGraph()`, returns immediately
- `pdg_status(path)` — cook state + aggregated work item counts (waiting/cooking/cooked/failed)
- `pdg_workitems(path, state?)` — enumerate items with attributes and output files, filter by state
- `pdg_dirty(path, dirty_all)` — `dirtyAllTasks()` for re-cooking
- `pdg_cancel(path)` — `cancelCook()` on graph context

**Usage pattern:** `pdg_cook` (fire) → poll `pdg_status` → read `pdg_workitems` with state="success"

## 2B. USD/Solaris (5 tools)

Reference: same file, search for `lop` handlers

- `lop_stage_info(path)` — prim count, root prims, default prim, layer count, time codes via `node.stage()`
- `lop_prim_get(path, prim_path, include_attrs)` — prim type, kind, purpose, children, attributes via `stage.GetPrimAtPath()`
- `lop_prim_search(path, pattern, type_name?)` — pattern search via `hou.LopSelectionRule` (the correct native API for this)
- `lop_layer_info(path)` — layer stack from `stage.GetLayerStack()`
- `lop_import(path, file, method, prim_path?)` — create reference or sublayer node

## 2C. HDA Management (4 tools)

Reference: same file, search for `hda` handlers

- `hda_list(category?)` — enumerate available HDA definitions
- `hda_get(node_type, category?)` — definition details: library file, version, help, sections, inputs
- `hda_install(file_path)` — `hou.hda.installFile()`, report what was installed
- `hda_create(node_path, name, label, file_path)` — `node.createDigitalAsset()`

## 2D. Additional capabilities

### Batch operations

- `batch(operations)` — array of `{type, args}` where type is create/connect/set_parm/set_flag. Execute all in a single `hou.undos.group()` for atomic undo.

### Geometry export

- `geo_export(path, format, output)` — `geo.saveToFile()`. Formats: obj, gltf, glb, usd, usda, ply, bgeo.sc. Return point/prim/vertex counts + bounding box.

### Flipbook rendering

- `render_flipbook(frame_range, output?, resolution?)` — viewport grab via `scene_viewer.flipbook()`. Uses `$F4` frame padding.

### `require_main_thread` decorator

Reference: [MoleskinProductions houdini_bridge/server.py](https://github.com/MoleskinProductions/houdini-mcp/blob/main/houdini_bridge/server.py) — `require_main_thread` function

Apply to all `server.py` handlers. Wraps calls in `hdefereval.executeInMainThreadWithResult()` when UI is available. Ensures thread safety without Qt timer coupling.

## 2E. File structure refactor

At ~36 tools, split the monolithic files:

```
server.py          → server.py (core + dispatch) + handlers/*.py by category
houdini_mcp_server.py → mcp_server.py (core) + tools/*.py by category
```

Categories: scene, nodes, wiring, parameters, rendering, geometry, pdg, lop, hda, errors

## Verify

- PDG: cook a TOP network, poll status until done, read work item outputs
- USD: inspect a Solaris stage, search prims by type, import a USD file
- HDA: list definitions, inspect one, install from file
- Batch: create+connect+set_parm in one call, single Ctrl+Z undoes all
- Geometry export: export to at least obj and glb, verify file written
