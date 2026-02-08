# Claude Terminal Panel Guide

The Claude Terminal is a dockable Python Panel that runs Claude Code (CLI) directly
inside Houdini. This gives you the full Claude Code experience — MCP tools, file
editing, git operations — without leaving the Houdini UI.

## Opening the Panel

- Click **Claude Terminal** on the **HoudiniMCP** shelf toolbar (one click)
- Or: **Window > Python Panels > Claude Terminal**

The panel appears as a floating window. Drag it into any pane layout to dock it.

## Features

### Tabbed Sessions

- **New Session**: Start a new Claude CLI session in a new tab
- **Restart**: Restart the current tab's session
- **Close Tab**: Close the current tab and kill its process

Multiple tabs let you run several Claude sessions or different commands
simultaneously.

### Working Directory

- The **CWD** field shows the working directory for new sessions
- Defaults to the directory of the current .hip file (or $HOME)
- Click **"..."** to browse for a different directory
- Edit the path directly and press Enter

### Font Size

- Click **A-** / **A+** to decrease/increase font size
- Or use **Ctrl+=** (increase) and **Ctrl+-** (decrease) keyboard shortcuts
- Range: 6pt to 24pt

### Color Theme

- Click the **Light/Dark** button to toggle between themes
- Dark theme: #1e1e1e background, #d4d4d4 text
- Light theme: white background, dark text

### Auto-Restart

- Check **Auto-restart** to automatically restart Claude if it exits unexpectedly
  (non-zero exit code)
- A 1-second delay is applied before restarting
- Normal exits (code 0) do not trigger restart

### Connection Status LED

- **Green**: Claude process is running
- **Red**: Process is not running or has exited

### Context Injection

Two buttons send Houdini context directly to Claude:

- **Send Selection**: Sends the paths of all currently selected nodes
- **Send Scene Info**: Sends a scene summary (file path, frame, FPS, object count)

These are useful for giving Claude context about what you're working on without
typing it manually.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Enter** | Send current input to Claude |
| **Ctrl+Shift+C** | Copy selected text from output |
| **Ctrl+=** / **Ctrl++** | Increase font size |
| **Ctrl+-** | Decrease font size |

## Environment Variables

The terminal automatically sets these environment variables for each Claude session:

| Variable | Value |
|----------|-------|
| `HOUDINIMCP_PORT` | The MCP server port (default 9876) |
| `HIP` | Path to the current .hip file |
| `HOUDINI_VERSION` | Houdini version string |

This means Claude Code automatically knows how to connect to your Houdini session.

## Requirements

- `claude` CLI must be installed and on your PATH
- The HoudiniMCP plugin must be loaded (for context injection to work)
- PySide2 is bundled with Houdini — no additional dependencies needed

## Troubleshooting

- **Panel not listed**: Re-run `python scripts/install.py` to install the `.pypanel` file
- **"Not running" message**: Click "New Session" to start a Claude process
- **No output**: Claude CLI may need a moment to initialize. Check that `claude`
  works in a regular terminal first
- **ANSI artifacts**: Install `pyte` (`pip install pyte`) for better ANSI escape
  code handling. The panel works without it using regex-based stripping.
