# Roadmap: Embedded Claude Code Terminal in Houdini

## Goal
Embed a full terminal emulator inside a dockable Houdini Python Panel using QTermWidget. The terminal runs `claude` (Claude Code CLI), giving users the complete Claude Code experience without leaving Houdini — tool calls, MCP integration, file editing, and all CLI features.

## Why Embedded Terminal over Custom Chat UI
- Zero duplication: no need to reimplement tool schemas, streaming, or message rendering
- Full Claude Code feature set (slash commands, MCP tools, file operations, git)
- Claude Code already knows how to talk to Houdini via the MCP bridge
- Dramatically less code to write and maintain
- Users get the same experience they know from the terminal

## Architecture

```
┌──────────────────────────────────────────────────────┐
│ Houdini                                              │
│  ┌──────────────────────────────────┐                │
│  │ Python Panel (dockable)          │                │
│  │  ┌────────────────────────────┐  │                │
│  │  │ QTermWidget                │  │                │
│  │  │  └─ runs: claude           │  │                │
│  │  │     (Claude Code CLI)      │  │                │
│  │  └────────────────────────────┘  │                │
│  │  [ toolbar: new session | ↻ ]    │                │
│  └──────────────────────────────────┘                │
│                                                      │
│  HoudiniMCPServer (existing, TCP :9876)              │
└──────────────┬───────────────────────────────────────┘
               │ TCP (MCP tool calls go through here)
┌──────────────▼───────────────────────────────────────┐
│ houdini_mcp_server.py (MCP bridge, started by claude)│
└──────────────────────────────────────────────────────┘
```

Claude Code, running inside the embedded terminal, connects to the MCP bridge as usual. The bridge talks to Houdini's TCP server. The only new piece is the QTermWidget panel hosting the `claude` process.

## Phases

### Phase 1: QTermWidget Integration Proof of Concept
**Effort: ~1-2 days**

- [ ] Verify QTermWidget availability / build for Houdini's Python + Qt version
  - Houdini ships PySide2 (Qt 5.x). QTermWidget needs to match this Qt version.
  - Check if `qtermwidget` pip package exists for the platform, or if building from source is needed
  - Alternative: `pyqtermwidget` or building the C++ lib and writing a thin Python binding
- [ ] Create minimal test: PySide2 app with QTermWidget running `/bin/bash`
- [ ] Confirm it works inside a Houdini Python Panel (not just standalone)
- [ ] Document build/install steps for QTermWidget on Linux

Key question to resolve: Does Houdini's embedded Python + PySide2 allow loading QTermWidget's shared library? If not, fallback plan is to use `QProcess` + `QPlainTextEdit` as a basic terminal emulator (less capable but no native dependency).

### Phase 2: Houdini Python Panel Registration
**Effort: ~1 day**

- [ ] Create `claude_terminal.py` — the Python Panel implementation
  - Subclass `QWidget`, embed QTermWidget as child
  - Launch `claude` (or configurable command) on panel creation
  - Handle panel destroy (send SIGTERM to child process)
- [ ] Create `ClaudeTerminal.pypanel` — Houdini panel definition XML
  - Register under Window > Python Panels
  - Set panel label, icon, default size
- [ ] Add to `install.py` — auto-install the .pypanel file into Houdini's python_panels dir
- [ ] Panel survives tab switches and re-docking (QTermWidget state persists)

### Phase 3: Toolbar and Session Management
**Effort: ~1-2 days**

- [ ] Add toolbar above the terminal:
  - **New Session** button — kills current `claude` process, starts fresh
  - **Restart** button — restarts the `claude` process
  - **Working Directory** selector — set CWD for the claude session (defaults to $HIP or project dir)
  - **Connection indicator** — shows if MCP bridge + Houdini TCP server are connected (polls `ping` command)
- [ ] Auto-set environment variables before launching `claude`:
  - `HOUDINIMCP_PORT` — so claude's MCP config picks up the right port
  - `HIP` — current .hip file path
  - `HOUDINI_VERSION` — detected from `hou.applicationVersionString()`
- [ ] Handle Houdini shutdown gracefully (SIGTERM the terminal process)

### Phase 4: Quality of Life
**Effort: ~2-3 days**

- [ ] Font size control (Ctrl+= / Ctrl+- or toolbar buttons)
- [ ] Color scheme selection (dark/light, match Houdini's theme)
- [ ] Copy/paste integration (Ctrl+Shift+C / Ctrl+Shift+V, standard terminal behavior)
- [ ] Scroll-back buffer size configuration
- [ ] Auto-restart `claude` if it exits unexpectedly (with user prompt)
- [ ] Multiple terminal tabs (run several claude sessions or plain bash)
- [ ] Shelf tool to toggle the panel open/closed
- [ ] Keyboard shortcut to focus the terminal panel from anywhere in Houdini

### Phase 5: Context Injection (Optional)
**Effort: ~2-3 days**

- [ ] "Send Selection" button — pipes selected node paths into the terminal as text
- [ ] "Send Scene Info" button — runs `get_scene_info` and pastes result into terminal
- [ ] "Attach Viewport" — renders current viewport, saves to temp file, and pastes the path
- [ ] Right-click context menu on nodes: "Ask Claude about this node" — opens terminal with node context
- [ ] Auto-inject a `/init` prompt on session start with scene summary

## Fallback: QProcess + QPlainTextEdit Terminal
If QTermWidget proves incompatible with Houdini's Qt build:

- Use `QProcess` to spawn `claude` with PTY (via `pty` module)
- Render output in a `QPlainTextEdit` with ANSI escape code parsing
- Handle input via key events forwarded to the QProcess stdin
- Less capable (no full VT100, no mouse support) but zero native dependencies
- Libraries like `pyte` (pure Python VT100 emulator) can help parse escape codes

## Dependencies
- **QTermWidget** — Qt terminal widget ([github.com/lxqt/qtermwidget](https://github.com/lxqt/qtermwidget))
  - Requires building against Houdini's Qt 5.x headers
  - Or: find/build a Python wheel compatible with Houdini's Python
- **PySide2** — ships with Houdini
- **claude** CLI — must be installed and on PATH (or configured via env var)

## Build Notes for QTermWidget on Linux
```bash
# Install build dependencies
sudo apt install cmake qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5

# Clone and build
git clone https://github.com/lxqt/qtermwidget.git
cd qtermwidget
mkdir build && cd build
cmake .. -DCMAKE_PREFIX_PATH=/path/to/houdini/qt  # Use Houdini's Qt if versions differ
make -j$(nproc)

# The resulting .so needs to be importable from Houdini's Python
# May need a Python binding (sip/shiboken2) or ctypes wrapper
```

Alternatively, check if the `qtermwidget5` package from your distro matches Houdini's Qt version:
```bash
sudo apt install qtermwidget5-dev python3-qtermwidget  # if available
```

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| QTermWidget Qt version mismatch with Houdini's bundled Qt | Build QTermWidget against Houdini's Qt headers; or use fallback (QProcess + QPlainTextEdit) |
| Python binding for QTermWidget doesn't exist | Write a minimal shiboken2 binding, or use ctypes to wrap the C++ API |
| Houdini's Python Panel sandboxing blocks subprocess spawning | Test early in Phase 1; Python Panels generally allow subprocess/QProcess |
| Terminal process outlives Houdini | Register `atexit` handler and panel destroy callback to kill child |
| No `claude` CLI on PATH | Show clear error in panel with install instructions; allow configurable command path |
| Performance: terminal rendering in Houdini's UI thread | QTermWidget renders in its own widget; shouldn't block Houdini. Monitor for frame drops. |

## Success Criteria
- User opens a dockable panel in Houdini and sees a fully functional terminal
- `claude` runs inside it with full MCP integration to the running Houdini session
- User can create nodes, run code, render — all from the embedded terminal
- Panel is dockable, resizable, and persists across tab switches
- Works on Linux (primary target); macOS and Windows are stretch goals
