"""Tests for hip_patterns.py — pattern extraction from parsed .hip data."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from hip_patterns import (
    extract_patterns,
    write_patterns,
    build_patterns_index,
    _extract_scene_graph,
    _extract_subgraphs,
    _extract_recipes,
    _format_params,
    _format_annotations,
    _network_context,
    _source_label,
)


# ---------------------------------------------------------------------------
# Fixtures — reuse the cpio helpers from test_hip_parser to build parsed data
# ---------------------------------------------------------------------------

def _make_parsed_scene(source="test.hip", nodes=None, connections=None,
                       sticky_notes=None, netboxes=None):
    """Build a minimal parsed scene dict (same shape as hip_parser output)."""
    return {
        "source": source,
        "nodes": nodes or [],
        "connections": connections or [],
        "sticky_notes": sticky_notes or [],
        "netboxes": netboxes or [],
    }


def _make_node(path, node_type, category, params=None):
    """Build a node dict matching hip_parser output."""
    name = path.rsplit("/", 1)[-1]
    return {
        "type": node_type,
        "path": path,
        "name": name,
        "category": category,
        "parameters": params or {},
        "children": [],
    }


def _make_conn(src_path, dst_path, src_output=0, dst_input=0):
    return {
        "src_path": src_path,
        "src_output": src_output,
        "dst_path": dst_path,
        "dst_input": dst_input,
    }


# A reusable multi-node scene
@pytest.fixture
def sop_chain_scene():
    """Scene with a 3-node SOP chain: box → xform → copy."""
    return _make_parsed_scene(
        source="/example/copy.hip",
        nodes=[
            _make_node("/obj/geo1", "geo", "OBJ"),
            _make_node("/obj/geo1/box1", "box", "SOP", {"size": ["1.0", "1.0", "1.0"]}),
            _make_node("/obj/geo1/xform1", "xform", "SOP", {"t": ["2.0", "0", "0"]}),
            _make_node("/obj/geo1/copy1", "copy", "SOP", {"ncy": "10"}),
        ],
        connections=[
            _make_conn("/obj/geo1/box1", "/obj/geo1/xform1"),
            _make_conn("/obj/geo1/xform1", "/obj/geo1/copy1"),
        ],
    )


@pytest.fixture
def two_component_scene():
    """Scene with two disconnected SOP chains in the same context."""
    return _make_parsed_scene(
        source="/example/two_chains.hip",
        nodes=[
            _make_node("/obj/geo1", "geo", "OBJ"),
            _make_node("/obj/geo1/box1", "box", "SOP"),
            _make_node("/obj/geo1/xform1", "xform", "SOP"),
            _make_node("/obj/geo1/sphere1", "sphere", "SOP"),
            _make_node("/obj/geo1/color1", "color", "SOP"),
        ],
        connections=[
            _make_conn("/obj/geo1/box1", "/obj/geo1/xform1"),
            _make_conn("/obj/geo1/sphere1", "/obj/geo1/color1"),
        ],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_format_params_empty(self):
        assert _format_params({}) == ""

    def test_format_params_single(self):
        assert _format_params({"ncy": "10"}) == "ncy: 10"

    def test_format_params_vector(self):
        result = _format_params({"t": ["1.0", "2.0", "3.0"]})
        assert result == "t: 1.0 2.0 3.0"

    def test_format_params_sorted(self):
        result = _format_params({"z": "1", "a": "2"})
        assert result.startswith("a: 2")

    def test_network_context(self):
        assert _network_context("/obj/geo1/box1") == "/obj/geo1"
        assert _network_context("/obj/geo1") == "/obj"
        assert _network_context("/obj") == "/"


# ---------------------------------------------------------------------------
# Scene graph extraction
# ---------------------------------------------------------------------------

class TestSceneGraph:
    def test_contains_all_nodes(self, sop_chain_scene):
        sg = _extract_scene_graph(sop_chain_scene)
        assert sg is not None
        assert sg["type"] == "scene"
        assert sg["node_count"] == 4
        assert "box1" in sg["text"]
        assert "xform1" in sg["text"]
        assert "copy1" in sg["text"]
        assert "geo1" in sg["text"]

    def test_contains_connections(self, sop_chain_scene):
        sg = _extract_scene_graph(sop_chain_scene)
        assert "box1 → xform1" in sg["text"]
        assert "xform1 → copy1" in sg["text"]

    def test_contains_source(self, sop_chain_scene):
        sg = _extract_scene_graph(sop_chain_scene)
        assert "/example/copy.hip" in sg["source"]
        assert "Source: /example/copy.hip" in sg["text"]

    def test_contains_parameters(self, sop_chain_scene):
        sg = _extract_scene_graph(sop_chain_scene)
        assert "ncy: 10" in sg["text"]

    def test_empty_scene_returns_none(self):
        scene = _make_parsed_scene(nodes=[])
        assert _extract_scene_graph(scene) is None

    def test_id_starts_with_scene(self, sop_chain_scene):
        sg = _extract_scene_graph(sop_chain_scene)
        assert sg["id"].startswith("scene_")


# ---------------------------------------------------------------------------
# Subgraph extraction
# ---------------------------------------------------------------------------

class TestSubgraphs:
    def test_finds_connected_component(self, sop_chain_scene):
        subgraphs = _extract_subgraphs(sop_chain_scene)
        # Should find at least one subgraph (the 3-node SOP chain)
        sop_sgs = [s for s in subgraphs if s["context"] == "/obj/geo1"]
        assert len(sop_sgs) == 1
        assert sop_sgs[0]["node_count"] == 3
        assert "box1" in sop_sgs[0]["text"]

    def test_two_components(self, two_component_scene):
        subgraphs = _extract_subgraphs(two_component_scene)
        sop_sgs = [s for s in subgraphs if s["context"] == "/obj/geo1"]
        assert len(sop_sgs) == 2
        node_counts = sorted(s["node_count"] for s in sop_sgs)
        assert node_counts == [2, 2]

    def test_single_node_no_subgraph(self):
        """A context with only one node should not produce a subgraph."""
        scene = _make_parsed_scene(
            nodes=[_make_node("/obj/geo1/box1", "box", "SOP")],
            connections=[],
        )
        subgraphs = _extract_subgraphs(scene)
        assert subgraphs == []

    def test_subgraph_has_connections_text(self, sop_chain_scene):
        subgraphs = _extract_subgraphs(sop_chain_scene)
        sop_sg = [s for s in subgraphs if s["context"] == "/obj/geo1"][0]
        assert "Connections:" in sop_sg["text"]
        assert "box1 → xform1" in sop_sg["text"]

    def test_subgraph_id_starts_with_subgraph(self, sop_chain_scene):
        subgraphs = _extract_subgraphs(sop_chain_scene)
        for sg in subgraphs:
            assert sg["id"].startswith("subgraph_")

    def test_dedup_identical_subgraphs(self):
        """Same topology from two files → merged sources."""
        scene_a = _make_parsed_scene(
            source="a.hip",
            nodes=[
                _make_node("/obj/geo1/box1", "box", "SOP"),
                _make_node("/obj/geo1/xform1", "xform", "SOP"),
            ],
            connections=[_make_conn("/obj/geo1/box1", "/obj/geo1/xform1")],
        )
        scene_b = _make_parsed_scene(
            source="b.hip",
            nodes=[
                _make_node("/obj/geo1/box1", "box", "SOP"),
                _make_node("/obj/geo1/xform1", "xform", "SOP"),
            ],
            connections=[_make_conn("/obj/geo1/box1", "/obj/geo1/xform1")],
        )
        patterns = extract_patterns([scene_a, scene_b])
        subgraphs = [p for p in patterns if p["type"] == "subgraph"]
        assert len(subgraphs) == 1
        assert len(subgraphs[0]["source"]) == 2

    def test_dedup_different_names_same_topology(self):
        """Same types and connections but different node names → still deduped."""
        scene_a = _make_parsed_scene(
            source="a.hip",
            nodes=[
                _make_node("/obj/geo1/box1", "box", "SOP"),
                _make_node("/obj/geo1/xform1", "xform", "SOP"),
            ],
            connections=[_make_conn("/obj/geo1/box1", "/obj/geo1/xform1")],
        )
        scene_b = _make_parsed_scene(
            source="b.hip",
            nodes=[
                _make_node("/obj/geo1/box2", "box", "SOP"),
                _make_node("/obj/geo1/xform2", "xform", "SOP"),
            ],
            connections=[_make_conn("/obj/geo1/box2", "/obj/geo1/xform2")],
        )
        patterns = extract_patterns([scene_a, scene_b])
        subgraphs = [p for p in patterns if p["type"] == "subgraph"]
        assert len(subgraphs) == 1
        assert len(subgraphs[0]["source"]) == 2


# ---------------------------------------------------------------------------
# Node recipe extraction
# ---------------------------------------------------------------------------

class TestRecipes:
    def test_extracts_recipes_with_params(self, sop_chain_scene):
        recipes = _extract_recipes(sop_chain_scene)
        types = {r["text"].split("\n")[0] for r in recipes}
        assert any("box Recipe" in t for t in types)
        assert any("copy Recipe" in t for t in types)

    def test_skips_nodes_without_params(self):
        scene = _make_parsed_scene(
            nodes=[_make_node("/obj/geo1/box1", "box", "SOP", {})],
        )
        recipes = _extract_recipes(scene)
        assert recipes == []

    def test_recipe_dedup_across_files(self):
        """Same (type, params) from two files → one recipe with two sources."""
        scene_a = _make_parsed_scene(
            source="a.hip",
            nodes=[_make_node("/obj/geo1/box1", "box", "SOP", {"size": "2"})],
        )
        scene_b = _make_parsed_scene(
            source="b.hip",
            nodes=[_make_node("/obj/geo1/box1", "box", "SOP", {"size": "2"})],
        )
        patterns = extract_patterns([scene_a, scene_b])
        recipes = [p for p in patterns if p["type"] == "recipe"]
        assert len(recipes) == 1
        assert "a.hip" in recipes[0]["source"]
        assert "b.hip" in recipes[0]["source"]

    def test_recipe_text_contains_params(self, sop_chain_scene):
        recipes = _extract_recipes(sop_chain_scene)
        copy_recipes = [r for r in recipes if "copy Recipe" in r["text"]]
        assert len(copy_recipes) == 1
        assert "ncy: 10" in copy_recipes[0]["text"]

    def test_recipe_id_starts_with_recipe(self, sop_chain_scene):
        recipes = _extract_recipes(sop_chain_scene)
        for r in recipes:
            assert r["id"].startswith("recipe_")


# ---------------------------------------------------------------------------
# extract_patterns (integration)
# ---------------------------------------------------------------------------

class TestExtractPatterns:
    def test_returns_all_types(self, sop_chain_scene):
        patterns = extract_patterns([sop_chain_scene])
        types = {p["type"] for p in patterns}
        assert "scene" in types
        assert "subgraph" in types
        assert "recipe" in types

    def test_empty_input(self):
        patterns = extract_patterns([])
        assert patterns == []

    def test_scene_with_no_nodes(self):
        scene = _make_parsed_scene(nodes=[], connections=[])
        patterns = extract_patterns([scene])
        assert patterns == []


# ---------------------------------------------------------------------------
# write_patterns
# ---------------------------------------------------------------------------

class TestWritePatterns:
    def test_writes_files(self, sop_chain_scene):
        patterns = extract_patterns([sop_chain_scene])
        with tempfile.TemporaryDirectory() as tmpdir:
            count = write_patterns(patterns, tmpdir)
            assert count == len(patterns)
            files = os.listdir(tmpdir)
            assert len(files) == len(patterns)
            # All files are .txt
            assert all(f.endswith(".txt") for f in files)

    def test_file_content_matches_text(self, sop_chain_scene):
        patterns = extract_patterns([sop_chain_scene])
        with tempfile.TemporaryDirectory() as tmpdir:
            write_patterns(patterns, tmpdir)
            for p in patterns:
                path = os.path.join(tmpdir, f"{p['id']}.txt")
                with open(path, encoding="utf-8") as f:
                    assert f.read() == p["text"]


# ---------------------------------------------------------------------------
# build_patterns_index
# ---------------------------------------------------------------------------

class TestBuildPatternsIndex:
    def test_writes_json(self, sop_chain_scene):
        patterns = extract_patterns([sop_chain_scene])
        with tempfile.TemporaryDirectory() as tmpdir:
            idx_path = os.path.join(tmpdir, "index.json")
            entries = build_patterns_index(patterns, idx_path)
            assert os.path.exists(idx_path)

            with open(idx_path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert len(loaded) == len(patterns)

    def test_entry_fields(self, sop_chain_scene):
        patterns = extract_patterns([sop_chain_scene])
        with tempfile.TemporaryDirectory() as tmpdir:
            idx_path = os.path.join(tmpdir, "index.json")
            entries = build_patterns_index(patterns, idx_path)
            for entry in entries:
                assert "id" in entry
                assert "type" in entry
                assert "source" in entry
                assert "node_count" in entry
                assert entry["type"] in ("scene", "subgraph", "recipe")


# ---------------------------------------------------------------------------
# Source label and annotation helpers
# ---------------------------------------------------------------------------

class TestSourceLabel:
    def test_hip_file(self):
        assert _source_label("/opt/hfs21.0/houdini/help/examples/copy.hip") == "copy"

    def test_hda_file(self):
        assert _source_label("/opt/hfs21.0/.../AttributePromote.hda") == "AttributePromote"

    def test_nested_path(self):
        assert _source_label("/a/b/c/particle_advect.hipnc") == "particle_advect"


class TestFormatAnnotations:
    def test_sticky_notes(self):
        scene = _make_parsed_scene(
            sticky_notes=[{"context": "/obj", "name": "sn1", "text": "Dive in"}],
        )
        lines = _format_annotations(scene)
        assert any("Dive in" in l for l in lines)

    def test_netbox_labels(self):
        scene = _make_parsed_scene(
            netboxes=[{"context": "/obj", "name": "nb1", "label": "Merge Step"}],
        )
        lines = _format_annotations(scene)
        assert any("Merge Step" in l for l in lines)

    def test_node_comments_included_without_context(self):
        node = _make_node("/obj/geo1/box1", "box", "SOP")
        node["comment"] = "Width attribute for Mantra"
        scene = _make_parsed_scene(nodes=[node])
        lines = _format_annotations(scene)
        assert any("Width attribute" in l for l in lines)

    def test_context_filter(self):
        scene = _make_parsed_scene(
            sticky_notes=[
                {"context": "/obj", "name": "sn1", "text": "Object level"},
                {"context": "/obj/geo1", "name": "sn2", "text": "SOP level"},
            ],
        )
        lines = _format_annotations(scene, context="/obj/geo1")
        assert any("SOP level" in l for l in lines)
        assert not any("Object level" in l for l in lines)

    def test_empty_scene(self):
        scene = _make_parsed_scene()
        assert _format_annotations(scene) == []


# ---------------------------------------------------------------------------
# Annotations in pattern text output
# ---------------------------------------------------------------------------

class TestAnnotationsInPatterns:
    def test_scene_graph_includes_filename(self):
        scene = _make_parsed_scene(
            source="/example/copy.hip",
            nodes=[_make_node("/obj/geo1", "geo", "OBJ")],
        )
        sg = _extract_scene_graph(scene)
        assert "Name: copy" in sg["text"]

    def test_scene_graph_includes_sticky_notes(self):
        scene = _make_parsed_scene(
            source="/example/test.hip",
            nodes=[_make_node("/obj/geo1", "geo", "OBJ")],
            sticky_notes=[{"context": "/obj", "name": "sn1",
                           "text": "This demonstrates the copy SOP"}],
        )
        sg = _extract_scene_graph(scene)
        assert "This demonstrates the copy SOP" in sg["text"]
        assert "Notes:" in sg["text"]

    def test_scene_graph_includes_node_comment(self):
        node = _make_node("/obj/geo1/box1", "box", "SOP", {"size": "2"})
        node["comment"] = "Width for Mantra"
        scene = _make_parsed_scene(
            source="/example/test.hip",
            nodes=[node],
        )
        sg = _extract_scene_graph(scene)
        assert "Width for Mantra" in sg["text"]

    def test_subgraph_includes_sticky_notes(self):
        scene = _make_parsed_scene(
            source="/example/test.hip",
            nodes=[
                _make_node("/obj/geo1/box1", "box", "SOP"),
                _make_node("/obj/geo1/xform1", "xform", "SOP"),
            ],
            connections=[_make_conn("/obj/geo1/box1", "/obj/geo1/xform1")],
            sticky_notes=[{"context": "/obj/geo1", "name": "sn1",
                           "text": "Transform the box"}],
        )
        subgraphs = _extract_subgraphs(scene)
        assert len(subgraphs) == 1
        assert "Transform the box" in subgraphs[0]["text"]

    def test_recipe_includes_node_comment(self):
        node = _make_node("/obj/geo1/box1", "box", "SOP", {"size": "2"})
        node["comment"] = "Creates geometry"
        scene = _make_parsed_scene(
            source="/example/test.hip",
            nodes=[node],
        )
        recipes = _extract_recipes(scene)
        assert len(recipes) == 1
        assert "Creates geometry" in recipes[0]["text"]

    def test_recipe_includes_filename(self):
        scene = _make_parsed_scene(
            source="/example/particle_advect.hip",
            nodes=[_make_node("/obj/geo1/box1", "box", "SOP", {"size": "2"})],
        )
        recipes = _extract_recipes(scene)
        assert "Name: particle_advect" in recipes[0]["text"]
