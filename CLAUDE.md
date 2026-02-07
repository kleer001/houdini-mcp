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

HoudiniMCP is a Model Context Protocol (MCP) bridge connecting SideFX Houdini to Claude AI. It enables Claude to programmatically control Houdini — creating/modifying nodes, executing code, rendering images, and importing 3D assets via the OPUS API.

## Repo Structure

```
houdini_mcp_server.py      # MCP bridge entry point (uv run)
pyproject.toml
src/houdinimcp/
    __init__.py             # Houdini plugin init (auto-start server)
    server.py               # Houdini-side TCP server + command dispatcher
    HoudiniMCPRender.py     # Rendering utilities (camera rig, OpenGL/Karma/Mantra)
    claude_terminal.py      # Embedded Claude terminal panel for Houdini
    ClaudeTerminal.pypanel  # Houdini panel XML definition
scripts/
    install.py              # Install plugin into Houdini prefs directory
    launch.py               # Launch Houdini and/or MCP bridge
tests/                      # pytest test suite
docs/                       # Phased implementation plans and roadmaps
```

## Running

```bash
# Run the MCP bridge server (communicates with Claude over stdio, with Houdini over TCP)
uv run python houdini_mcp_server.py

# Install dependencies
uv add "mcp[cli]"

# Run tests
uv run pytest tests/ -v
```

Tests in `tests/`. Some test pure helper functions; integration tests use a mock TCP server. No running Houdini instance required for the test suite.

## Architecture

The system is a 3-layer bridge:

```
Claude (MCP stdio) → houdini_mcp_server.py (MCP Bridge) → TCP:9876 → src/houdinimcp/server.py (Houdini Plugin) → Houdini API
```

### Layer 1: Houdini Plugin (`src/houdinimcp/__init__.py`, `src/houdinimcp/server.py`)
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

### Layer 3: Rendering (`src/houdinimcp/HoudiniMCPRender.py`)
- Utility module imported by `src/houdinimcp/server.py` (runs inside Houdini).
- Handles camera rig setup, geometry bounding box calculation, and rendering (OpenGL, Karma, Mantra).
- `render_single_view()`, `render_quad_view()`, `render_specific_camera()` are the main entry points.
- Rendered images are base64-encoded for JSON transport.

## Key Patterns

- **Command dispatcher**: `src/houdinimcp/server.py:execute_command()` routes by command type string to handler methods.
- **Global connection singleton**: `houdini_mcp_server.py` reuses one TCP connection across all MCP tool calls.
- **OPUS batch job flow**: Create batch → poll status → download ZIP → extract → import into Houdini.
- **Conditional imports**: `langchain` is optional (used for OPUS schema parsing); `HoudiniMCPRender` import is guarded.

## Dependencies

- **Python:** 3.12+ (see `.python-version`)
- **Package manager:** `uv`
- Declared in `pyproject.toml`: `mcp[cli]>=1.4.1`
- Runtime also needs `requests`, `python-dotenv`, and optionally `langchain`
- Houdini-side code depends on `hou`, `PySide2`, and standard library modules

## OPUS Integration

Requires a RapidAPI key in `urls.env`. The OPUS API provides procedural furniture/environment 3D assets. See README.md section 5 for setup.

## Phased Implementation Plans

See `docs/` for phased plans:
- **Phase 0**: Remove all OPUS/RapidAPI code
- **Phase 1**: Expand to ~22 tools (wiring, scene management, parameters, animation, geometry)
- **Phase 2**: Add PDG/USD/HDA/batch/export (~36 tools), refactor into `handlers/` and `tools/` subdirs
- **Phase 3**: Offline Houdini docs search (BM25, zero external deps)

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
