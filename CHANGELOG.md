# Changelog

## [Unreleased]

### Added
- **Offline renderer manuals as separate search sources.** `search_docs` and `get_doc` take `source`: `houdini` (default: Houdini docs and hip patterns), `redshift`, or `arnold`. Each renderer has its own index, so its pages do not dilute Houdini results.
  - `scripts/fetch_redshift_docs.py` reads the Redshift for Houdini manual from Maxon's official offline help ZIP (only the HTML pages; the ZIP is discarded).
  - `scripts/fetch_arnold_docs.py` fetches the Arnold core and HtoA user guides from help.autodesk.com (CC BY-NC-SA 3.0), with a 6-second delay between requests. A rerun resumes an interrupted fetch.
  - `scripts/html_to_markdown.py` — stdlib converter shared by both fetchers.
  - The manuals are copyrighted, so their markdown and indexes are gitignored.

### Fixed
- `get_geo_summary` and `geo_export` no longer crash on point-only geometry; `hou.Geometry` has no `vertices()` (#4, thanks @arghhhhh).
- `capture_screenshot` works on Houdini 21, where `GeometryViewport.saveAsImage` was removed (#5, thanks @arghhhhh).
- `install.py` honors `HOUDINI_USER_PREF_DIR` (expanding `__HVER__`) and `$HOME` on Windows (#6, thanks @arghhhhh).
- Windows: all text files open as UTF-8, doc paths use forward slashes, and install detection picks the newest Houdini by parsed version, never Houdini Server (from #2, thanks @ysysimon).
- `tests/test_server_commands.py` failed to import: the `hou` mock lacked `isUIAvailable()`.

## [0.3.1] — 2026-09-23

### Fixed
- **Plugin auto-start runs only in interactive GUI sessions.** The old guard tested `HOUDINIMCP_HEADLESS`, a variable that nothing sets, so the server also started under headless hython. A render farm's scene-analysis hython then got an unsolicited server thread and aborted (Fox Renderfarm "Analysis termination", resultCode 3). The guard now uses `hou.isUIAvailable()`.

### Added
- `REDSHIFT_BESTPRACTICES.md` — all Redshift render findings in one file, linked from the Layer 1 routing table. Corrects the AOV multilayer facts: `RS_outputMultilayerMode` takes the string `"2"` for Full Multi-Layered EXR, and per-AOV output paths use `RS_aovCustomPrefix_<i>`.
- Best-practice entries: typed `setprimattrib` and int→float AOV primvars, the `rotate()` axis bitmask (pitfall C), `$HIP` empty before a hip save (`sops`), Karma velocity-blur inputs, and ACEScg→sRGB on 8-bit export (`karma`).

### Changed
- `.gitignore` ignores `tmp/` and `research/` scratch directories.

## [0.3.0] — 2026-09-19

### Added
- **Multiple LLM-driven Houdini instances on one machine.** Each LLM↔Houdini pair binds its own port (`HOUDINIMCP_PORT`), which flows through the bridge, GUI plugin, and headless server. Claim files are per-port, so GUI/headless hand-off stays isolated per instance.
- **Machine-wide GPU render lock** (`src/houdinimcp/render_lock.py`). One GPU serves every instance, so two simultaneous renders can exhaust VRAM and crash the card. All GPU render commands serialize through one OS file lock, applied centrally in the command dispatcher next to the existing undo grouping. The OS releases the lock when the holder exits, so a crashed render never deadlocks the machine. Cross-platform: `fcntl` on POSIX, `msvcrt` on Windows — no new dependencies.
- **`status: gpu_busy` response.** A render that waits past the timeout returns `gpu_busy` instead of failing; the driving LLM backs off and retries (server instruction 3a).

### Changed
- **Instance ceiling is a configurable port range.** Default is eight slots (`9876-9883`); an out-of-range port fails loudly at bridge start and plugin bind. Override with `HOUDINIMCP_BASE_PORT` and `HOUDINIMCP_MAX_INSTANCES`.
- The render lock is tunable: `HOUDINIMCP_RENDER_LOCK=0` disables it (multi-GPU hosts that assign devices themselves); `HOUDINIMCP_RENDER_LOCK_TIMEOUT` sets the wait (default 25 s, under the bridge's 30 s socket timeout).

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
