"""Tests for pattern annotation functions in scripts/annotate_patterns.py."""

import json
import os
import sys

import pytest

# Add scripts/ to path so we can import annotate_patterns
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from annotate_patterns import (
    list_unannotated,
    get_pattern,
    annotate_pattern,
    get_progress,
)


@pytest.fixture
def patterns_env(monkeypatch, tmp_path):
    """Set up a temp patterns dir with index and pattern files."""
    patterns_dir = tmp_path / "hip_patterns"
    patterns_dir.mkdir()

    # Write 3 pattern files
    for i, ptype in enumerate(["scene", "subgraph", "recipe"]):
        pid = f"{ptype}_test{i}"
        (patterns_dir / f"{pid}.txt").write_text(
            f"Pattern: {ptype} test\nSource: test{i}.hip\nCategory: SOP\n\nNodes:\n  box (SOP)",
            encoding="utf-8",
        )

    # Write index
    index = [
        {"id": f"{t}_test{i}", "type": t, "source": [f"test{i}.hip"], "context": "/obj", "node_count": 1}
        for i, t in enumerate(["scene", "subgraph", "recipe"])
    ]
    index_path = tmp_path / "hip_patterns_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    # Monkeypatch the module-level paths
    import annotate_patterns
    monkeypatch.setattr(annotate_patterns, "PATTERNS_DIR", str(patterns_dir))
    monkeypatch.setattr(annotate_patterns, "INDEX_PATH", str(index_path))

    return patterns_dir, index_path


# ---------------------------------------------------------------------------
# list_unannotated
# ---------------------------------------------------------------------------

class TestListUnannotated:
    def test_all_unannotated(self, patterns_env):
        result = list_unannotated()
        assert len(result) == 3

    def test_limit(self, patterns_env):
        result = list_unannotated(limit=1)
        assert len(result) == 1

    def test_excludes_annotated(self, patterns_env):
        patterns_dir, _ = patterns_env
        # Annotate one pattern
        filepath = patterns_dir / "scene_test0.txt"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("\n\n## Annotation\nThis is a test scene.\n")

        result = list_unannotated()
        ids = [e["id"] for e in result]
        assert "scene_test0" not in ids
        assert len(result) == 2

    def test_no_index(self, monkeypatch):
        import annotate_patterns
        monkeypatch.setattr(annotate_patterns, "INDEX_PATH", "/nonexistent/index.json")
        result = list_unannotated()
        assert "error" in result


# ---------------------------------------------------------------------------
# get_pattern
# ---------------------------------------------------------------------------

class TestGetPattern:
    def test_existing_pattern(self, patterns_env):
        result = get_pattern("scene_test0")
        assert result["id"] == "scene_test0"
        assert "Pattern: scene test" in result["content"]

    def test_missing_pattern(self, patterns_env):
        result = get_pattern("nonexistent_abc")
        assert "error" in result


# ---------------------------------------------------------------------------
# annotate_pattern
# ---------------------------------------------------------------------------

class TestAnnotatePattern:
    def test_annotate_success(self, patterns_env):
        patterns_dir, _ = patterns_env
        result = annotate_pattern("scene_test0", "A test scene with a box.")
        assert result["status"] == "ok"

        # Verify file was modified
        content = (patterns_dir / "scene_test0.txt").read_text(encoding="utf-8")
        assert "## Annotation" in content
        assert "A test scene with a box." in content

    def test_annotate_already_annotated(self, patterns_env):
        # Annotate once
        annotate_pattern("scene_test0", "First annotation.")
        # Try again
        result = annotate_pattern("scene_test0", "Second annotation.")
        assert "error" in result
        assert "already annotated" in result["error"]

    def test_annotate_missing_pattern(self, patterns_env):
        result = annotate_pattern("nonexistent_abc", "summary")
        assert "error" in result


# ---------------------------------------------------------------------------
# get_progress
# ---------------------------------------------------------------------------

class TestGetProgress:
    def test_none_annotated(self, patterns_env):
        result = get_progress()
        assert result["annotated"] == 0
        assert result["total"] == 3
        assert result["percent"] == 0.0

    def test_partial_annotated(self, patterns_env):
        annotate_pattern("scene_test0", "Annotated.")
        result = get_progress()
        assert result["annotated"] == 1
        assert result["total"] == 3
        assert abs(result["percent"] - 33.3) < 0.1

    def test_all_annotated(self, patterns_env):
        annotate_pattern("scene_test0", "A.")
        annotate_pattern("subgraph_test1", "B.")
        annotate_pattern("recipe_test2", "C.")
        result = get_progress()
        assert result["annotated"] == 3
        assert result["percent"] == 100.0

    def test_no_index(self, monkeypatch):
        import annotate_patterns
        monkeypatch.setattr(annotate_patterns, "INDEX_PATH", "/nonexistent/index.json")
        result = get_progress()
        assert result["total"] == 0
