# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role & Philosophy

**Role:** Senior Software Developer

**Core Tenets:** DRY, SOLID, YAGNI, KISS

**Communication Style:**
- Concise and minimal. Focus on code, not chatter
- Provide clear rationale for architectural decisions
- Surface tradeoffs when multiple approaches exist

**Planning Protocol:**
- For complex requests: Provide bulleted outline/plan before writing code
- For simple requests: Execute directly
- Override keyword: **"skip planning"** — Execute immediately without planning phase
- Do not give time estimates unless explicitly asked

---

## Project Overview

HoudiniMCP is a Model Context Protocol (MCP) bridge connecting SideFX Houdini to Claude AI. It provides 41+ MCP tools for programmatic Houdini control — node operations, rendering, geometry, PDG/TOPs, USD/Solaris, HDA management, scene management, offline docs search, and a bidirectional event system.

## Best Practices

See **[BEST_PRACTICES.md](BEST_PRACTICES.md)** for hard-won lessons from production use — Copernicus COP pitfalls, ImageLayer creation, temporal effects, diagnostics workflow, and more. Organized by context (COPs, SOPs, etc.) so you can jump to what's relevant.

## Repo Structure

```
houdini_mcp_server.py          # MCP bridge entry point (uv run), 41+ @mcp.tool() wrappers
houdini_rag.py                 # BM25 docs search engine (stdlib only, zero deps)
pyproject.toml
src/houdinimcp/
    __init__.py                # Houdini plugin init (auto-start server)
    server.py                  # Houdini-side TCP server + command dispatcher (~270 lines)
    handlers/                  # Handler modules by category:
        scene.py               #   get_scene_info, save_scene, load_scene, set_frame
        nodes.py               #   create/modify/delete/connect/flags/layout/color/errors
        code.py                #   execute_code + DANGEROUS_PATTERNS guard
        geometry.py            #   get_geo_summary, geo_export
        pdg.py                 #   pdg_cook/status/workitems/dirty/cancel
        lop.py                 #   lop_stage_info/prim_get/prim_search/layer_info/import
        hda.py                 #   hda_list/get/install/create
        rendering.py           #   render_single_view/quad_view/specific_camera/flipbook
    event_collector.py         # EventCollector: Houdini callbacks → buffered events
    HoudiniMCPRender.py        # Rendering utilities (camera rig, bbox, OpenGL/Karma/Mantra)
    claude_terminal.py         # Embedded Claude terminal panel (tabbed, themed)
    ClaudeTerminal.pypanel     # Houdini panel XML definition
    houdinimcp.shelf           # Shelf toolbar (Claude Terminal + Toggle Server buttons)
scripts/
    install.py                 # Install plugin + handlers + panel + pythonrc into Houdini prefs
    launch.py                  # Launch Houdini and/or MCP bridge
    headless_server.py         # Run MCP TCP server inside hython (no GUI)
    fetch_houdini_docs.py      # Download Houdini docs corpus and build BM25 index
    hip_parser.py              # Cpio-based .hip file parser (stdlib only)
    hip_patterns.py            # Pattern extraction from parsed .hip data
tests/                         # pytest test suite (69 tests)
docs/                          # User guides (getting started, tools, terminal, events)
houdini_docs/                  # (gitignored) Fetched Houdini documentation
houdini_docs_index.json        # (gitignored) BM25 index built from docs
```

## Running

```bash
# Run the MCP bridge server (communicates with Claude over stdio, with Houdini over TCP)
uv run python houdini_mcp_server.py

# Install dependencies
uv add "mcp[cli]"

# Run tests (no Houdini instance required)
pytest tests/ -v

# Fetch Houdini docs for offline search
python scripts/fetch_houdini_docs.py

# Install plugin into Houdini
python scripts/install.py
```

## Architecture

```
Claude (MCP stdio) → houdini_mcp_server.py (Bridge) → TCP:9876 → server.py (Plugin) → hou API
                   ↘ houdini_rag.py (docs search, local-only)

No Houdini? Bridge auto-launches: hython → headless_server.py → server.py → hou API
```

### Layer 1: Houdini Plugin (`src/houdinimcp/`)
- Runs **inside** the Houdini process. Uses the `hou` module (Houdini Python API).
- `HoudiniMCPServer` in `server.py` listens on `localhost:9876` with a non-blocking TCP socket polled via Qt's `QTimer`.
- `execute_command()` dispatches JSON commands to handler functions in `handlers/`.
- Mutating commands are wrapped in `hou.undos.group()` for undo support.
- `EventCollector` registers Houdini callbacks (hipFile, node, playbar) and buffers events with deduplication.
- `claude_terminal.py` provides a dockable PySide2 panel with tabbed Claude CLI sessions.

### Layer 2: MCP Bridge (`houdini_mcp_server.py`)
- Runs in a **separate** Python process (via `uv run`).
- `HoudiniConnection` dataclass manages a persistent TCP connection (global singleton).
- `_send_tool_command()` helper reduces each MCP tool to ~3 lines.
- `search_docs` and `get_doc` tools run locally via `houdini_rag.py` — no Houdini connection needed.
- **Headless auto-launch**: if no Houdini is listening, `find_hython()` locates the binary and `_launch_headless_houdini()` spawns `scripts/headless_server.py` in a managed subprocess. Cleaned up on shutdown via lifespan + atexit. Disable with `HOUDINIMCP_NO_HEADLESS=1`.
- **GUI launch is the LLM's job, not the server's**: the server only ever auto-launches *headless* hython. GUI-only work (viewport, flipbooks, GPU-only Copernicus/COPs) needs a real GUI session. When the user asks for it, the assistant launches the `houdini`/`houdinifx` binary from the shell itself (see instructions rule 5a in `houdini_mcp_server.py`) — it does not ask the user to open it. It does not open the GUI unprompted.

### Layer 3: Rendering (`src/houdinimcp/HoudiniMCPRender.py`)
- Utility module imported by `handlers/rendering.py` (runs inside Houdini).
- Handles camera rig setup, geometry bounding box calculation, and rendering.
- Rendered images are base64-encoded for JSON transport.

## Key Patterns

- **Handler modules**: Standalone functions in `handlers/*.py` that import `hou` directly. Dispatched via dict in `server.py:_get_handlers()`.
- **`_send_tool_command()` helper**: All MCP tool wrappers in the bridge use this to send commands and handle errors uniformly.
- **Global connection singleton**: `houdini_mcp_server.py` reuses one TCP connection across all MCP tool calls.
- **Dangerous code guard**: `handlers/code.py` blocks `os.remove`, `subprocess`, `hou.exit`, etc. unless `allow_dangerous=True`.
- **Event deduplication**: `EventCollector` collapses rapid-fire events (same type + path within 100ms) into one.
- **BM25 docs search**: `houdini_rag.py` is pure stdlib — no external deps. Index lazy-loaded on first search.

## Dependencies

- **Python:** 3.12+ (see `.python-version`)
- **Package manager:** `uv` (or pip)
- Declared in `pyproject.toml`: `mcp[cli]>=1.4.1`
- Houdini-side code depends on `hou`, `PySide2`, and standard library modules
- `houdini_rag.py` has zero external dependencies (stdlib only)

## Testing

69 tests across 5 test files:
- `test_bridge_connection.py` — HoudiniConnection (AST extraction, mock TCP server)
- `test_server_commands.py` — command dispatcher, handlers, MUTATING_COMMANDS, events
- `test_houdini_rag.py` — tokenizer, BM25 index, search, document loading
- `test_event_collector.py` — EventCollector with mocked hou callbacks
- `test_terminal.py` — ANSI stripping, terminal constants

All tests run without Houdini. `server.py` tests mock `hou`, `PySide2`, `numpy`. `houdini_mcp_server.py` tests use AST extraction to avoid FastMCP side effects.

---

## Behavioral Guidelines

See **[CLAUDE_GENERIC.md](CLAUDE_GENERIC.md)** — reusable coding guidelines (think before coding, simplicity first, surgical changes, no unrequested fallbacks, enforcement checklist, code style, error handling, git conventions).

---

## Contributing to Best Practices

When you discover a **non-trivial** Houdini behavior while working through this MCP — silent failures, undocumented API quirks, metadata requirements, required parameter ordering, etc. — add it to [`BEST_PRACTICES.md`](BEST_PRACTICES.md).

**What qualifies as non-trivial:**
- Behavior that has no error message (silent failure)
- API usage where parameter order or metadata matters but isn't documented
- Workarounds for missing Houdini features (e.g., no timeshift in Copernicus)
- Anything that took multiple attempts to diagnose

**How to add it:**
1. **Read `BEST_PRACTICES.md` first** — check that the item isn't already covered
2. Place it under the appropriate context section (COPs, SOPs, LOPs, TOPs, etc.)
3. Create the section if it doesn't exist yet
4. Add an entry to the Index at the top of the file
5. **Include the Houdini version** (e.g., `> Houdini 21.0.631`) — behaviors change between releases
6. **Use anti-pattern format** when applicable: "Tried X, it silently failed, do Y instead"
7. Be brief: problem, symptom, fix. A few sentences, not paragraphs. Code snippets only when the syntax is the non-obvious part

Do **not** add trivial items (standard API usage, well-documented behavior, one-off bugs).
