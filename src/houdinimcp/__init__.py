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

# If you want the plugin to auto-load on import:
initialize_plugin()
