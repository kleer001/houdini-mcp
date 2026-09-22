# Best Practices — Redshift

Redshift-specific findings for rendering through the Redshift ROP in Houdini. The entry layer is [`BEST_PRACTICES.md`](BEST_PRACTICES.md); engine-agnostic render discipline is in [`best_practices/rops_render.md`](best_practices/rops_render.md), and Karma in [`best_practices/karma.md`](best_practices/karma.md).

### AOVs: one multi-layer EXR, not a file per AOV

> Redshift (repo env: 2026.3.1 / Houdini 20.0.896). `RS_outputMultilayerMode` and its `"1"`/`"2"` string values are confirmed across production pipelines — AYON `ayon-houdini`, Prism, quadpype; the `RS_aov*` multiparm names in the RsCreative `Houdini_AOV_Tool` (`set_aovs.py`).

**Goal: beauty plus every AOV (masks, occlusion, depth, IDs) in one render, one file**, then split into layers in the comp. Each extra render pass costs a full render; use a separate pass only when one render cannot express the output (a different camera or engine).

- **Set `RS_outputMultilayerMode` to the string `"2"` — Full Multi-Layered EXR** (Output → Common, the *Multi-Layered EXR* menu). The value is a **string token, not an int**: `"1"` = *No Multi-Layered EXR File*, `"2"` = *Full Multi-Layered EXR File*. Set it explicitly — `rop.parm("RS_outputMultilayerMode").set("2")`. The layers then pack as `ao.R`, `depth`, `normals.R`, … into one file.
- **Redshift AOVs are a multiparm on the ROP.** The count is `RS_aov`; each instance carries `RS_aovID_<i>` (type), `RS_aovSuffix_<i>` (name), `RS_aovCustomPrefix_<i>` (output path), and `RS_aovCustomShader_<i>` (a custom shader — e.g. a short-range AmbientOcclusion that rides alongside beauty). The names carry a 1-based index; a bare `RS_aovCustomPrefix` does not evaluate.
- **AOVs that share an output prefix land in the same EXR.** Leave `RS_aovCustomPrefix_<i>` **blank** so each AOV inherits the common output prefix and writes into one file. A per-AOV `RS_aovCustomPrefix_<i>` **silently diverts that AOV to its own file** — the usual cause of an accidental file-per-AOV layout.

One file per frame keeps the output atomic and matches how compositors pull AOVs. A file-per-AOV layout is the exception a farm or client asks for, not the default.

### A Motion Vectors AOV silently disables 3D motion blur in the beauty

> Redshift 2026.3.1 / Houdini 20.0.896

Redshift turns off *all* beauty motion blur — transformation and deformation — whenever a Motion Vectors AOV is enabled, by design: it assumes you will apply 2D vector blur in comp from that AOV. The beauty renders dead sharp with no error or warning, and toggling `MotionBlurEnabled` changes nothing, so it reads as "motion blur is broken" when every blur parameter is correct. You cannot have both the Motion Vectors AOV and real 3D blur baked into the beauty from one render — pick per shot: drop the Motion Vectors AOV to bake true 3D blur into the beauty, or keep the AOV and do the blur in comp.
