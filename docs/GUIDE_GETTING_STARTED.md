# Getting Started with HoudiniMCP

This guide walks you through setting up HoudiniMCP from scratch.

## Prerequisites

- SideFX Houdini (20.0+)
- Python 3.10+ with `uv` or `pip`
- Claude Desktop or Cursor

## Step 1: Clone the Repository

```bash
git clone https://github.com/kleer001/houdini-mcp.git
cd houdini-mcp
```

## Step 2: Install the Houdini Plugin

```bash
python scripts/install.py
```

This auto-detects your Houdini version and copies the plugin files to the correct
location. Use `--dry-run` to preview what it will do.

**What it installs:**
- Plugin Python package to `scripts/python/houdinimcp/` in your Houdini prefs
- Handler modules (scene, nodes, geometry, rendering, etc.)
- Claude Terminal panel (`.pypanel`) to `python_panels/`
- A packages JSON for auto-loading at Houdini startup

## Step 3: Install MCP Dependencies

```bash
# Using uv (recommended)
uv add "mcp[cli]"

# Or using pip in a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install "mcp[cli]"
```

## Step 4: Configure Your AI Client

### Claude Desktop

1. Open Claude Desktop
2. Go to **File > Settings > Developer > Edit Config**
3. Add the HoudiniMCP server:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "uv",
      "args": ["run", "python", "/path/to/houdini-mcp/houdini_mcp_server.py"]
    }
  }
}
```

### Cursor

Go to **Settings > MCP > Add new MCP server** and use the same configuration.

## Step 5: Verify the Connection

1. Start Houdini (the MCP server plugin should auto-start on port 9876)
2. In Claude, ask: "Ping Houdini — is it connected?"
3. Claude should respond with server status info

If auto-start didn't work, run this in Houdini's Python console:

```python
import houdinimcp
houdinimcp.start_server()
```

## Step 6: (Optional) Set Up Documentation Search

```bash
python scripts/fetch_houdini_docs.py
```

This downloads ~11,000 Houdini documentation pages and builds a BM25 search index.
Once built, Claude can search Houdini docs offline without a Houdini connection.

## What's Next?

- See the [Tool Reference](GUIDE_TOOLS.md) for all 41+ MCP tools
- See the [Terminal Panel Guide](GUIDE_TERMINAL.md) for the embedded Claude terminal
- See the [Event System Guide](GUIDE_EVENTS.md) for bidirectional communication
