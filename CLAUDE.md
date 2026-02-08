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
scripts/
    install.py                 # Install plugin + handlers + panel into Houdini prefs
    launch.py                  # Launch Houdini and/or MCP bridge
    fetch_houdini_docs.py      # Download Houdini docs corpus and build BM25 index
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

Guidelines to reduce common LLM coding mistakes. Biased toward caution over speed—use judgment for trivial tasks.

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them—don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked
- No abstractions for single-use code
- No "flexibility" or "configurability" that wasn't requested
- No defensive code for scenarios the caller cannot produce
- If 200 lines could be 50, rewrite it

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting
- Don't refactor things that aren't broken
- Match existing style, even if you'd do it differently
- If you notice unrelated dead code, mention it—don't delete it
- Remove only imports/variables/functions that YOUR changes orphaned

### No Unrequested Fallbacks

**Do one thing. If it fails, report—don't silently try alternatives.**

Violations:
- `try: primary() except: fallback()` — just call `primary()`
- "If the file doesn't exist, create it" — if it should exist, raise
- Retry loops for operations that aren't network calls
- Multiple implementation strategies "for robustness"

Unrequested fallbacks hide bugs, complicate debugging, and add untested code paths.

**The rule:** One path. Let it fail loudly.

### Goal-Driven Execution

**State success criteria before implementing. Verify after.**

Transform tasks into verifiable goals:
- "Add validation" → "Tests for invalid inputs pass"
- "Fix the bug" → "Regression test passes"
- "Refactor X" → "Tests pass before and after"

---

## Enforcement Checklist

Before proposing code changes, pass these checks.

### Scope Check
- [ ] List files to modify: `[file1, file2, ...]`
- [ ] Each file traces to user request or direct dependency
- [ ] No "while I'm here" improvements

### Complexity Check
- [ ] No new classes/modules unless requested
- [ ] No new abstractions for single use
- [ ] No configuration options unless requested
- [ ] No fallback/retry logic unless requested

### Diff Audit
- [ ] Diff under 100 lines (excluding tests), or justification provided
- [ ] No whitespace-only changes outside modified blocks
- [ ] No comment changes unless behavior changed
- [ ] Removed code: only YOUR orphans

### Verification Gate
- [ ] Success criteria stated before implementation
- [ ] Verification method identified (test, type check, manual)
- [ ] Verification ran and passed

---

## Code Style

- **Naming:** `snake_case` functions/variables, `PascalCase` classes. Self-documenting names.
- **Comments:** Only for complex algorithms, performance workarounds, TODO/FIXME. No commented-out code. Explain **why**, not **what**.
- **Imports:** Standard library → Third-party → Local
- **Statelessness:** Pass dependencies explicitly. Acceptable state: caching, connection pooling, configuration.

---

## Error Handling

- Don't catch errors you can't handle
- Fail fast for programmer errors (assertions)
- Handle gracefully for user errors (validation)
- Validate at system boundaries only (CLI args, file inputs). Trust internal functions.

---

## Git Conventions

**Commits:** Atomic, working code, clear messages.

**Message Format:**
```
type(scope): short description

Longer explanation if needed. Explain WHY, not what.
```
**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`

---

## Critical Rules (Summary)

1. **One path, no fallbacks.** Don't `try X except: Y`. Let it fail.
2. **Touch only what's asked.** No adjacent "improvements."
3. **No single-use abstractions.** No helpers for one call site.
4. **Verify before done.** Run it. Test it. Don't guess.
5. **Uncertain? Ask.** Don't pick silently between interpretations.
