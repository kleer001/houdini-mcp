"""Tests for the MCP bridge's HoudiniConnection class.

We extract HoudiniConnection via AST to avoid triggering the full
houdini_mcp_server.py initialization (FastMCP, env vars, OPUS imports).
"""
import ast
import json
import os
import socket
import sys
import types
import asyncio

import pytest


def _load_houdini_connection_class():
    """Extract the HoudiniConnection dataclass from houdini_mcp_server.py
    without executing the full module.
    """
    bridge_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "houdini_mcp_server.py",
    )

    with open(bridge_path) as f:
        source = f.read()

    tree = ast.parse(source)

    # Collect the imports and class def we need
    nodes_to_compile = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Include standard library imports
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in (
                    "json", "socket", "logging", "asyncio", "dataclasses"
                ):
                    nodes_to_compile.append(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in (
                        "json", "socket", "logging", "asyncio"
                    ):
                        nodes_to_compile.append(node)
                        break
        elif isinstance(node, ast.ClassDef) and node.name == "HoudiniConnection":
            nodes_to_compile.append(node)

    import logging
    from typing import Dict, Any, List
    ns = {
        "__builtins__": __builtins__,
        "Dict": Dict,
        "Any": Any,
        "List": List,
        "logger": logging.getLogger("test_bridge"),
    }
    module = ast.Module(body=nodes_to_compile, type_ignores=[])
    code = compile(module, bridge_path, "exec")
    exec(code, ns)

    return ns["HoudiniConnection"]


HoudiniConnection = _load_houdini_connection_class()

# Ensure an event loop exists — HoudiniConnection.connect() calls
# asyncio.get_event_loop().time() which requires a running or set loop.
# HoudiniConnection.connect() calls asyncio.get_event_loop().time()
asyncio.set_event_loop(asyncio.new_event_loop())


def _make_connection(port):
    return HoudiniConnection(host="localhost", port=port)


class TestHoudiniConnection:
    def test_ping(self, mock_houdini_server):
        mock_houdini_server.set_response("ping", {
            "status": "success",
            "result": {"alive": True},
        })
        conn = _make_connection(mock_houdini_server.port)
        result = conn.send_command("ping")
        assert result["status"] == "success"
        assert result["result"]["alive"] is True
        conn.disconnect()

    def test_unknown_command(self, mock_houdini_server):
        """Mock server returns a generic success for unknown commands."""
        conn = _make_connection(mock_houdini_server.port)
        result = conn.send_command("nonexistent_command")
        assert result["status"] == "success"
        assert result["result"]["echo"] == "nonexistent_command"
        conn.disconnect()

    def test_connection_error_returns_error_dict(self):
        """Connecting to a port with nothing listening returns an error dict."""
        conn = _make_connection(19999)
        result = conn.send_command("ping")
        assert result["status"] == "error"
        assert "origin" in result
        conn.disconnect()

    def test_disconnect_resets_socket(self, mock_houdini_server):
        conn = _make_connection(mock_houdini_server.port)
        conn.connect()
        assert conn.sock is not None
        conn.disconnect()
        assert conn.sock is None

    def test_get_status_disconnected(self):
        conn = _make_connection(19999)
        status = conn.get_status()
        assert status["connected"] is False
        assert status["port"] == 19999
