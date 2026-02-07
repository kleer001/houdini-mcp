# Phase 3: Offline Houdini Documentation Search

**Source:** https://github.com/orrzxz/Houdini21MCP

**Goal:** Add BM25-based search across 11,238 Houdini doc pages. 2 new tools, no Houdini connection required.

## What to borrow

### Core engine

- [`houdini_rag.py`](https://github.com/orrzxz/Houdini21MCP/blob/main/houdini/scripts/python/houdinimcp/houdini_rag.py) — self-contained, zero external dependencies (stdlib only: `math`, `collections`, `re`, `json`, `pathlib`)
- Contains: `BM25Index`, `HoudiniTokenizer` (preserves `hou.*` calls, node paths, underscore compounds), `DocumentLoader` (handles Houdini wiki-format markdown)
- BM25 params: k1=1.5, b=0.75

### Documentation corpus

- [`docs/`](https://github.com/orrzxz/Houdini21MCP/tree/main/houdini/scripts/python/houdinimcp/docs) directory — 59 subdirectories, ~11,238 markdown pages covering nodes (SOP/LOP/DOP/VOP/CHOP/COP/TOP/OBJ/OUT), HOM Python API, VEX, expressions, workflows
- [`docs_index.json`](https://github.com/orrzxz/Houdini21MCP/blob/main/houdini/scripts/python/houdinimcp/docs_index.json) — 35.5 MB pre-built index (88,916 unique terms, inverted index, per-doc term frequencies, IDF values, 500-char previews)

## MCP tools to add

### `search_docs(query, top_k=5)`

- Local-only — runs in the MCP bridge process, never touches Houdini TCP connection
- Returns: ranked list of `{path, title, preview (500 chars), score}`
- Lazy-loads index on first call (~35 MB into memory)

### `get_doc(path)`

- Reads full markdown file from `docs/` directory by relative path (from search results)
- Returns: `{path, content}`

## Integration

1. Place `houdini_rag.py` alongside `houdini_mcp_server.py` (or in a `docs/` submodule)
2. Place `docs/` directory and `docs_index.json` in a known location relative to the engine
3. Register both tools as `@mcp.tool()` in `houdini_mcp_server.py` — route directly to `search_docs()` / `get_doc_content()` without going through TCP
4. If `docs_index.json` is missing, it auto-builds from `docs/` on first call

## Licensing concern

The `docs/` content is scraped from SideFX documentation. Verify redistribution rights before shipping. Alternative: provide a build script that scrapes docs locally rather than bundling them.

## Verify

- `search_docs("karma render settings")` returns relevant results with scores
- `get_doc` on a result path returns full page content
- Both tools work with Houdini disconnected
- Index loads in under 5 seconds on first call
