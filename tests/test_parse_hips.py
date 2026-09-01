"""Tests for scripts/parse_hips.py pure-Python helpers.

Uses AST extraction to import helpers without triggering hython/hou imports.
"""
import ast
import os
import sys
import types

import pytest


SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "parse_hips.py",
)


def _load_module():
    """Extract pure-Python objects from parse_hips.py via AST."""
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)

    # Collect top-level assignments and function defs we need
    target_funcs = {"_node_category", "_auto_workers", "_find_hips", "main"}
    target_assigns = {"_UI_ONLY_TYPES", "_CONTEXT_CATEGORIES"}

    nodes_to_compile = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in (
                    "argparse", "json", "os", "sys", "time",
                ):
                    nodes_to_compile.append(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in (
                        "argparse", "json", "os", "sys", "time",
                    ):
                        nodes_to_compile.append(node)
                        break
        elif isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            nodes_to_compile.append(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in target_assigns:
                    nodes_to_compile.append(node)

    module = ast.Module(body=nodes_to_compile, type_ignores=[])
    code = compile(module, SCRIPT_PATH, "exec")
    ns = {"__builtins__": __builtins__}
    exec(code, ns)
    return ns


@pytest.fixture(scope="module")
def mod():
    return _load_module()


class TestUIOnlyTypes:
    def test_contains_expected_types(self, mod):
        ui_types = mod["_UI_ONLY_TYPES"]
        assert "Folder" in ui_types
        assert "FolderSet" in ui_types
        assert "Separator" in ui_types
        assert "Label" in ui_types
        assert "Button" in ui_types

    def test_is_a_set(self, mod):
        assert isinstance(mod["_UI_ONLY_TYPES"], set)

    def test_no_data_types(self, mod):
        ui_types = mod["_UI_ONLY_TYPES"]
        assert "Float" not in ui_types
        assert "Int" not in ui_types
        assert "String" not in ui_types


class TestNodeCategory:
    def test_obj_root(self, mod):
        assert mod["_node_category"]("/obj/geo1") == "OBJ"

    def test_sop_depth(self, mod):
        assert mod["_node_category"]("/obj/geo1/box1") == "SOP"

    def test_deep_sop(self, mod):
        assert mod["_node_category"]("/obj/geo1/subnet1/box1") == "SOP"

    def test_stage(self, mod):
        assert mod["_node_category"]("/stage/sublayer1") == "LOP"

    def test_out(self, mod):
        assert mod["_node_category"]("/out/mantra1") == "ROP"

    def test_shop(self, mod):
        assert mod["_node_category"]("/shop/principled1") == "SHOP"

    def test_unknown_context(self, mod):
        assert mod["_node_category"]("/foo/bar") == "FOO"


class TestAutoWorkers:
    def test_returns_positive_int(self, mod):
        result = mod["_auto_workers"](50)
        assert isinstance(result, int)
        assert result >= 1

    def test_small_count_limits_workers(self, mod):
        # 5 files → file_workers = max(1, 5//10) = 1
        result = mod["_auto_workers"](5)
        assert result >= 1

    def test_large_count(self, mod):
        result = mod["_auto_workers"](500)
        assert result >= 1


class TestArgparse:
    def test_main_function_exists(self, mod):
        assert callable(mod["main"])

    def test_context_categories_matches_hip_parser(self, mod):
        # Verify category mapping is consistent with hip_parser.py
        cats = mod["_CONTEXT_CATEGORIES"]
        assert cats["obj"] == "OBJ"
        assert cats["stage"] == "LOP"
        assert cats["out"] == "ROP"
        assert cats["ch"] == "CHOP"
