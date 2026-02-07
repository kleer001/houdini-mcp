#!/usr/bin/env python
"""
Fetch Houdini documentation from the Houdini21MCP repo and build the BM25 index.

Usage:
    python scripts/fetch_houdini_docs.py           # fetch docs + build index
    python scripts/fetch_houdini_docs.py --no-index # fetch docs only

The docs are placed in houdini_docs/ and the index in houdini_docs_index.json.
Neither is committed to the repo (see .gitignore).
"""

import os
import sys
import shutil
import subprocess
import tempfile

REPO_URL = "https://github.com/orrzxz/Houdini21MCP.git"
DOCS_SUBPATH = "houdini/scripts/python/houdinimcp/docs"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DOCS_DIR = os.path.join(REPO_ROOT, "houdini_docs")
INDEX_PATH = os.path.join(REPO_ROOT, "houdini_docs_index.json")


def fetch_docs():
    """Clone the reference repo (sparse checkout) and copy docs."""
    if os.path.exists(DOCS_DIR) and os.listdir(DOCS_DIR):
        print(f"Docs already exist at {DOCS_DIR} — remove to re-fetch.")
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = os.path.join(tmpdir, "repo")
        print(f"Cloning {REPO_URL} (sparse, docs only)...")

        subprocess.run(
            ["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", REPO_URL, clone_dir],
            check=True,
        )
        subprocess.run(
            ["git", "-C", clone_dir, "sparse-checkout", "set", DOCS_SUBPATH],
            check=True,
        )

        src = os.path.join(clone_dir, DOCS_SUBPATH)
        if not os.path.exists(src):
            print(f"ERROR: Expected docs at {src} but not found.")
            return False

        shutil.copytree(src, DOCS_DIR)
        md_count = sum(1 for _ in _rglob_md(DOCS_DIR))
        print(f"Fetched {md_count} markdown files to {DOCS_DIR}")
    return True


def _rglob_md(directory):
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith('.md'):
                yield os.path.join(root, f)


def build_index():
    """Build the BM25 index from the local docs directory."""
    sys.path.insert(0, REPO_ROOT)
    from houdini_rag import build_index as _build

    os.environ.setdefault("HOUDINIMCP_DOCS_DIR", DOCS_DIR)
    os.environ.setdefault("HOUDINIMCP_DOCS_INDEX", INDEX_PATH)

    _build(docs_dir=DOCS_DIR, output_path=INDEX_PATH)
    size_mb = os.path.getsize(INDEX_PATH) / (1024 * 1024)
    print(f"Index built: {INDEX_PATH} ({size_mb:.1f} MB)")


def main():
    no_index = "--no-index" in sys.argv
    fetched = fetch_docs()
    if not no_index and (fetched or os.path.exists(DOCS_DIR)):
        build_index()
    print("Done.")


if __name__ == "__main__":
    main()
