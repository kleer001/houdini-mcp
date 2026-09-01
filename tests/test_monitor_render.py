"""Tests for the monitor_render MCP tool and _find_render_processes helper.

Uses AST extraction (same pattern as test_bridge_connection.py) to pull
_find_render_processes without executing the full houdini_mcp_server.py module.
"""
import ast
import json
import os
import subprocess
import sys
import types

import pytest


def _load_find_render_processes():
    """Extract _find_render_processes and _RENDER_PROCESS_NAMES from the bridge."""
    bridge_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "houdini_mcp_server.py",
    )
    with open(bridge_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)

    names_to_extract = {"_find_render_processes", "_RENDER_PROCESS_NAMES"}
    nodes_to_compile = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in (
                    "json", "subprocess", "sys",
                ):
                    nodes_to_compile.append(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in ("json", "subprocess", "sys"):
                        nodes_to_compile.append(node)
                        break
        elif isinstance(node, ast.FunctionDef) and node.name in names_to_extract:
            nodes_to_compile.append(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names_to_extract:
                    nodes_to_compile.append(node)

    from typing import Dict, List
    ns = {
        "__builtins__": __builtins__,
        "Dict": Dict,
        "List": List,
    }
    module = ast.Module(body=nodes_to_compile, type_ignores=[])
    code = compile(module, bridge_path, "exec")
    exec(code, ns)
    return ns["_find_render_processes"]


_find_render_processes = _load_find_render_processes()


# -- Sample ps aux / tasklist output -------------------------------------------

PS_AUX_HEADER = "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"

PS_AUX_HUSK = (
    "user     12345  98.0  4.2 1234560 54321 ?   Sl   10:00   5:23 "
    "/opt/hfs21.0/bin/husk --renderer karma /tmp/scene.usd"
)

PS_AUX_MANTRA = (
    "user     67890  85.0  3.1 987654  43210 ?   Sl   10:01   3:12 "
    "/opt/hfs21.0/bin/mantra-bin -f driver1"
)

PS_AUX_UNRELATED = "user      1111   0.1  0.0  12345   678 pts/0 Ss   09:00   0:00 bash"

TASKLIST_HEADER = '"Image Name","PID","Session Name","Session#","Mem Usage","Status","User Name","CPU Time","Window Title"'
TASKLIST_HUSK = '"husk.exe","12345","Console","1","100,000 K","Running","USER","0:05:23","N/A"'
TASKLIST_MANTRA = '"mantra-bin.exe","67890","Console","1","80,000 K","Running","USER","0:03:12","N/A"'
TASKLIST_UNRELATED = '"explorer.exe","1111","Console","1","50,000 K","Running","USER","0:00:01","N/A"'


# -- Tests ---------------------------------------------------------------------

class TestFindRenderProcessesUnix:
    """Tests for Linux/macOS (ps aux) path."""

    def test_no_render_processes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        stdout = "\n".join([PS_AUX_HEADER, PS_AUX_UNRELATED])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert result == []

    def test_husk_running(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        stdout = "\n".join([PS_AUX_HEADER, PS_AUX_UNRELATED, PS_AUX_HUSK])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert len(result) == 1
        assert result[0]["name"] == "husk"
        assert result[0]["pid"] == "12345"

    def test_mantra_running(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        stdout = "\n".join([PS_AUX_HEADER, PS_AUX_MANTRA])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert len(result) == 1
        assert result[0]["name"] == "mantra-bin"
        assert result[0]["pid"] == "67890"

    def test_multiple_processes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        stdout = "\n".join([PS_AUX_HEADER, PS_AUX_HUSK, PS_AUX_MANTRA, PS_AUX_UNRELATED])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"husk", "mantra-bin"}


class TestFindRenderProcessesWindows:
    """Tests for Windows (tasklist /FO CSV /V) path."""

    def test_no_render_processes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        stdout = "\n".join([TASKLIST_HEADER, TASKLIST_UNRELATED])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert result == []

    def test_husk_running(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        stdout = "\n".join([TASKLIST_HEADER, TASKLIST_HUSK])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert len(result) == 1
        assert result[0]["pid"] == "12345"

    def test_multiple_processes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        stdout = "\n".join([TASKLIST_HEADER, TASKLIST_HUSK, TASKLIST_MANTRA])
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=stdout, returncode=0),
        )
        result = _find_render_processes()
        assert len(result) == 2


class TestMonitorRenderOutput:
    """Test output_path file-checking logic (independent of process detection)."""

    def test_output_file_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=PS_AUX_HEADER, returncode=0),
        )
        # Create a fake output file
        out = tmp_path / "render.exr"
        out.write_bytes(b"\x00" * 1024)

        # Simulate what monitor_render does for output_path
        result = _find_render_processes()
        info = {"rendering": len(result) > 0, "processes": result}
        if os.path.exists(str(out)):
            info["output_file"] = {
                "exists": True,
                "size_bytes": os.path.getsize(str(out)),
            }
        assert info["output_file"]["exists"] is True
        assert info["output_file"]["size_bytes"] == 1024

    def test_output_file_missing(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: types.SimpleNamespace(stdout=PS_AUX_HEADER, returncode=0),
        )
        result = _find_render_processes()
        info = {"rendering": len(result) > 0, "processes": result}
        path = "/tmp/nonexistent_render_output_12345.exr"
        if not os.path.exists(path):
            info["output_file"] = {"exists": False}
        assert info["output_file"]["exists"] is False
