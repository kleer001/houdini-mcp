# Troubleshooting

## Connection Problems

### "Could not connect to Houdini on port 9876"

This means the MCP bridge can't reach the plugin running inside Houdini. Work through these checks in order:

**1. Is the plugin loaded?**

Open the Houdini Python Shell (**Windows > Python Shell**) and run:

```python
import hou
print(hasattr(hou.session, 'houdinimcp_server'))
print(hou.session.houdinimcp_server)
```

If it prints `False` or `None`, the plugin didn't load. Check:

- The package file exists: `~/houdiniX.Y/packages/houdinimcp.json`
- The plugin files exist: `~/houdiniX.Y/scripts/python/houdinimcp/`
- Houdini's console (**Windows > Python Shell**) for import errors on startup
- Re-run the installer: `uv run python scripts/install.py`

**2. Is the server actually listening?**

In the Houdini Python Shell:

```python
server = hou.session.houdinimcp_server
print(f"Running: {server.running}, Port: {server.port}, Socket: {server.socket}")
```

If `running` is `False`, start it manually:

```python
from houdinimcp import start_server
start_server()
```

Or use the **Toggle MCP Server** shelf button.

**3. Is something else using port 9876?**

```bash
# Linux/macOS
lsof -i :9876

# Windows
netstat -ano | findstr :9876
```

If another process has the port, either kill it or use a custom port:

```bash
# Set on both sides — the plugin and the bridge must match
export HOUDINIMCP_PORT=9877
```

Set it in Houdini's Python Shell before starting the server:

```python
import os
os.environ["HOUDINIMCP_PORT"] = "9877"
from houdinimcp import start_server
start_server()
```

**4. Is a firewall blocking localhost connections?**

Unlikely on most systems, but some corporate/VPN setups block loopback connections. Test with:

```bash
# Should connect instantly if the server is listening
python -c "import socket; s=socket.socket(); s.connect(('localhost', 9876)); print('OK'); s.close()"
```

### Connection drops mid-session

The MCP bridge has a 10-second timeout for Houdini responses (`send_command` in `houdini_mcp_server.py`). Operations that take longer will timeout and disconnect. This commonly hits:

- **Rendering with Karma/Mantra** — these can take minutes for complex scenes
- **PDG cooks** — `pdg_cook` is non-blocking, but if the cook triggers heavy computation before returning, it can timeout
- **Large geometry exports** — exporting millions of polygons takes time

If you hit timeouts on renders, consider using OpenGL renders (fast) for previews and only switching to Karma for final frames.

After a timeout, the bridge reconnects automatically on the next tool call.

### "Client disconnected" appears in Houdini console

This is normal. It means the MCP bridge closed its TCP connection (e.g., Claude session ended, bridge restarted). The plugin keeps listening for new connections.

---

## Plugin Loading Issues

### Plugin doesn't auto-start when Houdini opens

The plugin auto-starts via `houdinimcp/__init__.py` which calls `initialize_plugin()` on import. If it's not loading:

1. Check that the Houdini packages file is valid JSON:
   ```bash
   python -m json.tool ~/houdiniX.Y/packages/houdinimcp.json
   ```

2. Check that `PYTHONPATH` in the package includes the right directory. Open the file and verify the `env` section points to `~/houdiniX.Y/scripts/python/`.

3. Look for import errors in the Houdini console on startup. Common causes:
   - **PySide2 not available** — the server uses `QTimer` from PySide2. This should always be present in GUI Houdini, but may be missing in `hython` (command-line Houdini). The plugin is designed for GUI sessions.
   - **Missing handler files** — if `handlers/` wasn't fully copied, you'll get `ImportError`. Re-run `uv run python scripts/install.py`.

### Plugin loads but server fails to start

Check the Houdini console for `Failed to start server:` messages. Usually means:

- Port 9876 is already in use (another Houdini instance, or a previous server didn't shut down cleanly)
- Socket permissions issue (extremely rare on modern systems)

Fix: restart Houdini, or change the port via `HOUDINIMCP_PORT` environment variable.

### After upgrading Houdini, the plugin stops working

Each Houdini version has its own preferences directory (`houdini20.5/`, `houdini21.0/`, etc.). After upgrading, re-run the installer targeting the new version:

```bash
uv run python scripts/install.py --houdini-version 21.0
```

---

## MCP Bridge Issues

### `uv` command not found

The bootstrap installs `uv` to `~/.local/bin/`. Ensure that's in your `PATH`:

```bash
# Add to your .bashrc / .zshrc
export PATH="$HOME/.local/bin:$PATH"
```

On Windows, check `%USERPROFILE%\.local\bin` is in your system PATH.

### `mcp` package import fails

```bash
# Verify from the repo directory
cd /path/to/houdini-mcp
uv run python -c "import mcp; print(mcp.__version__)"
```

If this fails:
- The venv may be broken. Delete `.venv/` and re-run `uv sync`
- If using system Python directly (not uv), install with: `pip install "mcp[cli]>=1.4.1"`

### MCP server starts but Claude says "no tools found"

Check your MCP client configuration:

- **Claude Code:** Run `claude mcp list` and verify the `houdini` entry shows the correct path
- **Claude Desktop:** Open the config file and verify the `--directory` path points to the actual repo location. Paths must be absolute.

Common mistake: the repo was cloned to a different location than what's in the config. If you moved the repo, update the path.

### Claude Code: "server failed to start"

Run the bridge manually to see error output:

```bash
cd /path/to/houdini-mcp
uv run python houdini_mcp_server.py
```

If it starts successfully, the issue is in how the MCP client launches it. Check that the `--directory` argument points to the repo root (where `houdini_mcp_server.py` lives).

---

## Rendering Problems

### "No scene viewer found for flipbook"

Flipbook rendering requires a visible Scene Viewer pane in the Houdini UI. If you've closed all viewers or are running headless, flipbook won't work. Ensure at least one viewport is open.

### Renders return black or empty images

- **No geometry in the scene** — the render camera targets the origin by default. Ensure geometry exists and is visible.
- **Camera is inside or clipping through geometry** — the auto-generated `MCP_CAMERA` node might be badly positioned if geometry bounds are extreme. Try `render_specific_camera` with a manually placed camera.
- **Display flag not set** — the render sees what the viewport sees. Check that the correct SOP has its display flag enabled.

### Karma renders fail with license errors

Karma requires a valid Houdini license (not Apprentice for some features). If you're on Houdini Apprentice or Indie, stick to `render_engine="opengl"` for previews.

### Renders are very slow

- Use `render_engine="opengl"` for fast viewport-quality renders (milliseconds)
- Karma CPU and Mantra are production renderers — they're slow by design
- Reduce resolution or scene complexity for iterative work with Claude

---

## Documentation Search Issues

### "Index not found" or search returns no results

The BM25 index must be built before search works:

```bash
cd /path/to/houdini-mcp
uv run python scripts/fetch_houdini_docs.py
```

This downloads ~1 GB of Houdini documentation and builds `houdini_docs_index.json` (~34 MB). It takes a while.

### Index build fails or downloads are incomplete

- Check disk space (~1.5 GB needed during build)
- Check network connectivity — the script downloads from SideFX's documentation site
- If it partially downloaded, delete the `houdini_docs/` directory and `houdini_docs_index.json`, then re-run the fetch script

### Search results seem irrelevant

The BM25 search is keyword-based. Tips:
- Use specific Houdini terminology: "VEX wrangle" not "code node"
- Use node type names: "polyextrude" not "extrude faces"
- Try different phrasings — BM25 matches on token overlap, not semantic meaning

---

## Claude Terminal Issues

### Panel doesn't appear in Window > Python Panels

The `.pypanel` file must be in Houdini's `python_panels/` directory:

```bash
ls ~/houdiniX.Y/python_panels/ClaudeTerminal.pypanel
```

If missing, re-run `uv run python scripts/install.py`. Then restart Houdini.

### Terminal opens but shows "claude: command not found"

The terminal runs Claude Code CLI (`claude`). It must be installed and in the PATH that Houdini sees. Houdini may not inherit your shell's PATH — especially on macOS where GUI apps get a minimal environment.

Fix: Add Claude Code's install directory to Houdini's environment. In `~/houdiniX.Y/houdini.env`:

```
PATH = $PATH:/path/to/claude/bin
```

Or set it in the Houdini packages JSON.

### Terminal session crashes or freezes

- **Ctrl+C** in the terminal sends an interrupt to the Claude process, not to Houdini. Use it freely.
- If the terminal is completely unresponsive, close the panel tab and reopen it — it auto-restarts the subprocess.
- Check Houdini's console for Python errors from `claude_terminal.py`.

---

## Code Execution Issues

### "Dangerous pattern detected" error

The `execute_houdini_code` tool blocks patterns like `os.remove`, `subprocess`, `hou.exit`, etc. by default. This is a safety guard.

If you genuinely need to run blocked code, pass `allow_dangerous=True`. But be aware: Claude will be executing arbitrary code in your Houdini session with full access. Review what it's doing.

### Code runs but `print()` output doesn't appear

The code execution handler captures stdout/stderr and returns them in the response. Your `print()` output goes to Claude, not to Houdini's console. This is by design.

If you need to see output in Houdini's console, write to `sys.__stdout__` instead:

```python
import sys
print("This goes to Claude", file=sys.stdout)
print("This goes to Houdini console", file=sys.__stdout__)
```

### Code can access `hou` but not other Houdini modules

The execution namespace starts with only `hou` pre-imported. Import what you need inside your code:

```python
import toolutils
viewer = toolutils.sceneViewer()
```

---

## PDG/TOPs Issues

### PDG cook starts but immediately shows 0 work items

- The TOP node may not have generated work items yet. Some TOP nodes need upstream cooks first.
- Check that the TOP network has a valid scheduler (usually **localscheduler**). Without one, nothing cooks.

### `pdg_status` returns stale data

PDG cook is non-blocking. After calling `pdg_cook`, poll `pdg_status` after a delay to get updated counts. The cook runs asynchronously in Houdini.

---

## Multiple Houdini Instances

Only one process can bind to port 9876 at a time. If you're running multiple Houdini instances, only the first one will successfully start the MCP server.

To connect to a specific instance, use different ports:

```bash
# Instance 1 (default)
export HOUDINIMCP_PORT=9876

# Instance 2
export HOUDINIMCP_PORT=9877
```

Set the port on the bridge side too:

```bash
HOUDINIMCP_PORT=9877 uv run python houdini_mcp_server.py
```

---

## Platform-Specific Notes

### Windows

- File paths in the Claude Desktop config JSON must use forward slashes (`/`) or escaped backslashes (`\\`). The bootstrap handles this automatically.
- If `uv` was installed via PowerShell but isn't found in `cmd.exe`, the PATH update may only apply to PowerShell. Add `%USERPROFILE%\.local\bin` to your system PATH manually.

### macOS

- Houdini preferences live in `~/Library/Preferences/houdini/X.Y/`, not `~/houdiniX.Y/`.
- GUI apps on macOS don't inherit your shell PATH. If the Claude Terminal can't find `claude`, set the path in Houdini's environment (see Terminal section above).

### Linux

- Houdini preferences are in `~/houdiniX.Y/`.
- If Houdini was installed to `/opt/hfsX.Y`, you need to source `houdini_setup` before Houdini's Python environment is available. The plugin doesn't need this — it runs inside Houdini where `hou` is already available.
