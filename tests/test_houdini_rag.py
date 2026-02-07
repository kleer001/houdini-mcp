"""Tests for houdini_rag.py — BM25 engine, tokenizer, search, get_doc."""
import json
import os
import tempfile

import pytest

# Import directly — houdini_rag.py has no heavy side effects
from houdini_rag import (
    HoudiniTokenizer,
    BM25Index,
    DocumentLoader,
    build_index,
    search_docs,
    get_doc_content,
)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
class TestHoudiniTokenizer:
    def setup_method(self):
        self.tok = HoudiniTokenizer()

    def test_basic_tokenization(self):
        tokens = self.tok.tokenize("create a box node")
        assert "create" in tokens
        assert "box" in tokens
        assert "node" in tokens
        # stopwords removed
        assert "a" not in tokens

    def test_preserves_hou_calls(self):
        tokens = self.tok.tokenize("use hou.node() to get a reference")
        assert "hou.node()" in tokens

    def test_preserves_node_paths(self):
        tokens = self.tok.tokenize("navigate to /obj/geo1/scatter")
        assert "/obj/geo1/scatter" in tokens

    def test_preserves_underscore_compounds(self):
        tokens = self.tok.tokenize("apply mtlxstandard_surface material")
        assert "mtlxstandard_surface" in tokens

    def test_stopwords_removed(self):
        tokens = self.tok.tokenize("the quick brown fox is very fast")
        for stop in ("the", "is", "very"):
            assert stop not in tokens

    def test_short_tokens_removed(self):
        tokens = self.tok.tokenize("I x y node")
        # single-char tokens removed (except special patterns)
        assert "x" not in tokens
        assert "y" not in tokens


# ---------------------------------------------------------------------------
# BM25 Index
# ---------------------------------------------------------------------------
class TestBM25Index:
    def setup_method(self):
        self.index = BM25Index()
        self.index.add_document("sop/box.md", "Box SOP", "Creates a box primitive geometry")
        self.index.add_document("sop/sphere.md", "Sphere SOP", "Creates a sphere primitive geometry")
        self.index.add_document("lop/karma.md", "Karma Renderer", "Karma is a USD-based renderer for Solaris")
        self.index.build()

    def test_search_returns_results(self):
        results = self.index.search("box geometry")
        assert len(results) > 0
        assert results[0]["path"] == "sop/box.md"

    def test_search_ranking(self):
        results = self.index.search("karma renderer")
        assert results[0]["path"] == "lop/karma.md"

    def test_search_top_k(self):
        results = self.index.search("primitive geometry", top_k=1)
        assert len(results) == 1

    def test_search_no_match(self):
        results = self.index.search("xyznonexistent")
        assert results == []

    def test_search_empty_query(self):
        # All stopwords → empty tokens
        results = self.index.search("the and is")
        assert results == []

    def test_result_has_required_fields(self):
        results = self.index.search("box")
        assert len(results) > 0
        r = results[0]
        assert "path" in r
        assert "title" in r
        assert "preview" in r
        assert "score" in r
        assert isinstance(r["score"], float)

    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            self.index.save(tmp_path)
            loaded = BM25Index.load(tmp_path)
            assert loaded is not None
            results = loaded.search("box")
            assert len(results) > 0
            assert results[0]["path"] == "sop/box.md"
        finally:
            os.unlink(tmp_path)

    def test_load_missing_file(self):
        result = BM25Index.load("/nonexistent/path.json")
        assert result is None


# ---------------------------------------------------------------------------
# DocumentLoader
# ---------------------------------------------------------------------------
class TestDocumentLoader:
    def test_extract_title_wiki_style(self):
        loader = DocumentLoader()
        title = loader.extract_title("= Box SOP =\nCreates a box.", None)
        assert title == "Box SOP"

    def test_extract_title_markdown_style(self):
        loader = DocumentLoader()
        title = loader.extract_title("# Karma Renderer\nRendering info.", None)
        assert title == "Karma Renderer"

    def test_extract_title_fallback(self):
        loader = DocumentLoader()

        class FakePath:
            stem = "my_cool_node"
        title = loader.extract_title("No heading here.", FakePath())
        assert title == "My Cool Node"

    def test_clean_content(self):
        loader = DocumentLoader()
        raw = "#bestbet: box\n[Icon:SOP/box] The box node.\n((Ctrl+B)) shortcut."
        cleaned = loader.clean_content(raw)
        assert "#bestbet" not in cleaned
        assert "[Icon:" not in cleaned
        assert "((" not in cleaned

    def test_load_all_from_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a couple of test docs
            os.makedirs(os.path.join(tmpdir, "sop"))
            with open(os.path.join(tmpdir, "sop", "box.md"), "w") as f:
                f.write("= Box SOP =\nCreates a box.")
            with open(os.path.join(tmpdir, "sop", "sphere.md"), "w") as f:
                f.write("# Sphere SOP\nCreates a sphere.")

            loader = DocumentLoader(tmpdir)
            docs = loader.load_all()
            assert len(docs) == 2
            paths = {d["path"] for d in docs}
            assert "sop/box.md" in paths
            assert "sop/sphere.md" in paths


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------
class TestBuildIndex:
    def test_build_from_temp_docs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "sop"))
            with open(os.path.join(tmpdir, "sop", "box.md"), "w") as f:
                f.write("= Box SOP =\nCreates a box primitive.")
            with open(os.path.join(tmpdir, "sop", "sphere.md"), "w") as f:
                f.write("= Sphere SOP =\nCreates a sphere primitive.")

            idx_path = os.path.join(tmpdir, "index.json")
            index = build_index(docs_dir=tmpdir, output_path=idx_path)
            assert len(index.documents) == 2
            assert os.path.exists(idx_path)

            # Verify index is loadable
            loaded = BM25Index.load(idx_path)
            results = loaded.search("box")
            assert len(results) > 0


# ---------------------------------------------------------------------------
# Top-level search_docs / get_doc_content
# ---------------------------------------------------------------------------
class TestSearchAndGetDoc:
    def test_search_docs_no_index(self, monkeypatch):
        """With no index available, returns an error dict."""
        import houdini_rag
        monkeypatch.setattr(houdini_rag, "_index", None)
        monkeypatch.setattr(houdini_rag, "INDEX_PATH", __import__("pathlib").Path("/nonexistent"))
        monkeypatch.setattr(houdini_rag, "DOCS_DIR", __import__("pathlib").Path("/nonexistent"))
        result = search_docs("anything")
        assert isinstance(result, dict)
        assert "error" in result

    def test_get_doc_content_missing(self, monkeypatch):
        import houdini_rag
        monkeypatch.setattr(houdini_rag, "DOCS_DIR", __import__("pathlib").Path("/nonexistent"))
        result = get_doc_content("sop/box.md")
        assert "error" in result

    def test_get_doc_content_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "sop"))
            with open(os.path.join(tmpdir, "sop", "box.md"), "w") as f:
                f.write("= Box SOP =\nCreates a box.")

            import houdini_rag
            old_docs = houdini_rag.DOCS_DIR
            try:
                houdini_rag.DOCS_DIR = __import__("pathlib").Path(tmpdir)
                result = get_doc_content("sop/box.md")
                assert result["path"] == "sop/box.md"
                assert "Box SOP" in result["content"]
            finally:
                houdini_rag.DOCS_DIR = old_docs
