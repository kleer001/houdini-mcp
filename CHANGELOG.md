# Changelog

## [0.2.0] — 2026-09-17

### Changed
- **Best Practices restructured into two layers.** `BEST_PRACTICES.md` is now the always-read entry — the *build nodes, not code* authoring philosophy, the A–H LLM workflow pitfalls, and a routing table. The involved, context-specific gotchas moved verbatim into per-area files under `best_practices/` (`sops`, `dops`, `cops`, `cop2`, `lops_usd`, `rops_render`, `karma`, `mcp_and_environment`; `hda`/`pdg`/`chops` stubs). Load only the area you're working in instead of the whole file.
- **Server instructions lead with "Build nodes, not code."** The FastMCP `instructions` string gained rule 0 — author node networks, not procedural code; motion/behavior from real solver/force nodes; wrangles for attributes and selection; no control null of promoted parameters unless asked — plus the A–H pitfall pointer. Rule 9 now documents the two-layer placement gate.
- `CLAUDE.md` "Contributing to Best Practices" rewritten around the two layers and the ≤100–200-token placement gate.

### Added
- `best_practices/dops.md` — DOP/POP simulation discipline: sequential cook + resimulate, gating real forces by a released group, POP Source `soppath`, sampling sim geometry, `removepoint` silent no-op.
- `best_practices/rops_render.md` — async render discipline (poll, don't judge on the immediate file) and the Mantra unlit `Cf` surface pattern.

## [0.1.0]

- Initial Houdini MCP bridge: 41+ tools (nodes, geometry, rendering, PDG/TOPs, USD/Solaris, HDA management, COPs, offline docs search), GUI/headless port handoff, and the first `BEST_PRACTICES.md`.
