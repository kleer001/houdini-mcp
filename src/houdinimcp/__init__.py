import os
import hou
from .server import HoudiniMCPServer

def start_server():
    if not hasattr(hou.session, "houdinimcp_server") or hou.session.houdinimcp_server is None:
        hou.session.houdinimcp_server = HoudiniMCPServer()
        hou.session.houdinimcp_server.start()
    else:
        print("Houdini MCP Server is already running.")

def stop_server():
    if hasattr(hou.session, "houdinimcp_server") and hou.session.houdinimcp_server:
        hou.session.houdinimcp_server.stop()
        hou.session.houdinimcp_server = None
    else:
        print("Houdini MCP Server is not running.")

# Optionally auto-start
def initialize_plugin():
    # Set up default session toggles if desired
    if not hasattr(hou.session, "houdinimcp_use_assetlib"):
        hou.session.houdinimcp_use_assetlib = False
    # Auto-start server if you want:
    start_server()

# Auto-start only in an interactive GUI session. Never under headless hython:
# batch tools (e.g. a render farm's scene analysis) launch hython, where an
# unsolicited server thread breaks the run — and the UI-bound bridge cannot
# work headless anyway. Opt out in the GUI with HOUDINIMCP_AUTOSTART=0; start
# it on demand from the HoudiniMCP shelf when headless access is needed.
if hou.isUIAvailable() and os.environ.get("HOUDINIMCP_AUTOSTART", "1") != "0":
    initialize_plugin()
