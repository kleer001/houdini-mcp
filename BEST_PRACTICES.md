# Houdini MCP — Best Practices

Hard-won lessons from real production use of the Houdini MCP. This file is the **always-read entry layer**: the authoring philosophy, the cross-cutting workflow pitfalls, and a routing table to the per-area deep-dives under [`best_practices/`](best_practices/).

## How this is organized (two layers)

- **Layer 1 — this file.** General philosophy plus short, first-pass, broadly-applicable rules. Read it every session.
- **Layer 2 — [`best_practices/<area>.md`](best_practices/).** Involved, context-specific gotchas. Load only the file that matches what you're working in (DOPs, COPs, Karma, …) so you don't carry 600 lines of unrelated arcana.

**Contributing:** A finding that condenses to a first-pass, generalizable rule (roughly ≤100–200 tokens) lives **here**. Repetition across layers is deliberate — a one-line echo in Layer 1 keeps the next agent primed even when the detail sits in an area file. Anything more involved, or narrow to one context, goes **strictly** into its area file. Every entry names the Houdini version it was validated against. Prefer the anti-pattern format: "Tried X, it silently failed, do Y instead."

---

## Authoring philosophy: build nodes, not code

**Hard rule: the deliverable is a node network a TD can open and edit — not procedural code that does the work.** When you drive Houdini through this MCP, the Python you send is *scaffolding to build the graph*. The graph's logic must live in nodes.

- **Motion and behavior come from real solver / force nodes** — POP Force (gravity), POP Wind (noise), POP Drag, and the DOP/SOP solvers — **not** from `@v += …` or position math in a wrangle. Let the solver integrate.
- **Wrangles are for attributes and selection** — ids, groups, release times, colors — **not** for integrating motion.
- **Do not build a control null of promoted parameters up front.** Use each node's own parameters with sensible defaults. Add a `CONTROLS` null with `ch()` references **only when the user asks** for it.

**Exceptions — when code is the honest tool:** creating or deriving attributes; grouping and selection; genuinely kinematic looks with no force-node equivalent (e.g. confetti flutter); and real math or programming. Do those in a wrangle and *say so* — don't dress procedural motion up as a simulation, and don't force a node graph where code is clearer.

**Worked example.** To make confetti fall, do **not** write `@v += {0,-9.8,0} * @TimeInc` in a POP wrangle. Build the real chain —
`POP Source → POP Force (gravity) → POP Wind (large-feature noise) → POP Drag → POP Solver` —
gate the forces to a "released" point group, and let the solver integrate. Wrangles set only the release time, the group membership, and the color. Rotation you can't get from a force node (flutter) is the allowed kinematic exception: drive `@w` in a wrangle and note it.

---

## Workflow pitfalls (they will bite an LLM)

Each rule is general; the fiddly, context-specific instances live in the area files.

- **A — Don't guess node types or parm names; inspect first.** They are rarely what you'd assume (`popnet` is actually `dopnet`; a `uvtexture` SOP may not exist; a bind menu entry labelled "vector" can be *vector2* and silently drop a channel). List types (`list_node_types`), read the parm template and its menu labels, *then* set.
- **B — Verify results; operations silently no-op.** `removepoint` can delete nothing, a group/blast can select the wrong set, and a dangling solver chain can cook with **zero errors**. After each build step check the thing you expected — count points, read the attribute — don't trust that it worked.
- **C — VEX type-prefixes and ambiguous signatures fail quietly or hard.** There is no `w@` prefix (`@w` is a vector → use `v@w`); `colormap(...).r` and `(int)prim(...)` are ambiguous and abort the compile. After setting any wrangle, run `find_error_nodes`.
- **D — Sim discipline.** DOP sims cook **sequentially from the start frame**, need a **resimulate** after parm edits, and a full-point Python read loop **times out the bridge** — sample points or read via a wrangle. *(details: [`best_practices/dops.md`](best_practices/dops.md))*
- **E — Respect the co-edited scene.** The `.hip` is shared with the user; they rename and rewire nodes between your calls. **Inspect the current wiring before you restructure**, and never destroy a node you didn't create. *(details: [`best_practices/mcp_and_environment.md`](best_practices/mcp_and_environment.md))*
- **F — Renders are async; poll, don't judge early.** `start_render` / `rop.render()` return before the image is written, and a 0-byte file is mid-write, not a failure. Poll the output path and the render process (`monitor_render`). *(details: [`best_practices/rops_render.md`](best_practices/rops_render.md))*
- **G — Trace attributes end-to-end to the render.** An attribute in the sim (e.g. `@orient`) is only "working" once you confirm it survives copy-to-points and reaches the material. Watch for reversed normals (a −Z card faces away from the camera → renders dark). Verify the whole chain, not just the source.
- **H — Build incrementally, not one mega-blob.** One bad node type aborts an entire `execute_houdini_code` build and leaves partial state. Stage the build and verify each stage; prefer `batch` (atomic undo group) for bulk node creation.

---

## Cross-cutting rules that stay in Layer 1

### Connection discipline
> Houdini 21.0.631

**The MCP plugin uses a single-threaded TCP listener.** Ping before starting work. Never rapid-fire commands. On a connection error, **stop** — don't retry in a loop; the plugin likely needs a restart. Use `batch` for bulk operations (atomic single undo group).

### Node inspection can crash
> Houdini 21.0.631

`get_node_info` can raise (e.g. `'Color' object is not iterable`) on nodes with non-standard color configs. Fall back to `execute_houdini_code` and iterate `node.parms() / inputs() / outputs()` directly.

### Diagnostics: inspect, don't eyeball
> Houdini 21.0.631

When something looks wrong: iterate `children()` printing each node's inputs/outputs; check `node.errors()` and `node.warnings()`; compare the actual data (attribute values, point counts, layer names) between a working and a broken path; A/B with a switch node. Never trust visual inspection alone. *(COP-specific version: [`best_practices/cops.md`](best_practices/cops.md))*

---

## Area files (Layer 2)

| Area | File | Covers |
|---|---|---|
| SOPs / geometry / file cache | [`best_practices/sops.md`](best_practices/sops.md) | wrangle deletion, expression-vs-`set()`, file cache execute |
| DOPs / POPs / sims | [`best_practices/dops.md`](best_practices/dops.md) | sim cadence & resimulate, force-node gating, POP Source, reading sim geo |
| Copernicus COPs | [`best_practices/cops.md`](best_practices/cops.md) | layers, ImageLayer, temporal access, COP-HDAs, headless, blend math, diagnostics |
| COP2 (legacy) | [`best_practices/cop2.md`](best_practices/cop2.md) | vexfilter shaders, Copernicus↔COP2 map, file frame range |
| LOPs / USD | [`best_practices/lops_usd.md`](best_practices/lops_usd.md) | editmaterialproperties spare-parm scan |
| ROPs / rendering | [`best_practices/rops_render.md`](best_practices/rops_render.md) | async render discipline, Mantra unlit surface |
| Karma / husk | [`best_practices/karma.md`](best_practices/karma.md) | standalone husk RenderVars, productName, VEX opdef |
| MCP & environment | [`best_practices/mcp_and_environment.md`](best_practices/mcp_and_environment.md) | port handoff, autostart, licensing, tmpfs logs, HDA code sync, run-script |
| HDAs | [`best_practices/hda.md`](best_practices/hda.md) | *(stub — add findings)* |
| PDG / TOPs | [`best_practices/pdg.md`](best_practices/pdg.md) | *(stub — add findings)* |
| CHOPs | [`best_practices/chops.md`](best_practices/chops.md) | *(stub — add findings)* |
