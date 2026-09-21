# Best Practices — Karma / husk

Context-specific findings for Karma and standalone `husk` rendering. General render rules are in [`rops_render.md`](rops_render.md); the entry layer is [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### Standalone husk: Let Karma Author RenderVars, Don't DIY

> Houdini 21.0.631

**Symptom:** Manually authored RenderVars produce `Unsupported AOV settings for: C` or black renders. No orderedVars produces `No orderedVars to specify channels`.

**Cause:** Karma in-process and standalone husk validate RenderVar attributes differently (SideFX BUG #134678). Copying the exact values from `karmarendersettings` LOP output (`color4f` + LPE + `color4h`) fails in standalone husk. Manually authoring simpler values (`color3f`/`raw`/`C`) also fails. There is no known manually-authored RenderVar configuration that reliably works across husk versions.

**Anti-patterns tried:**
- `color4f` + `sourceName=C.*[LO]` + `sourceType=lpe` → "Unsupported AOV settings"
- `color3f` + `sourceName=C` + `sourceType=raw` + husk attrs → "Unsupported AOV settings"
- `color3f` + `sourceName=Ci` + `sourceType=raw` (no husk attrs) → warning + black render

**Fix:** Don't author RenderVars yourself. Enable the **Beauty AOV** checkbox on the Karma RenderSettings LOP in the scene. The LOP authors RenderVars through an internal code path that husk accepts. Detect missing orderedVars during auditing and warn the user to enable Beauty.

---

### Standalone husk: productName Time-Sampled vs Default

> Houdini 21.0.631

**Symptom:** husk writes to a stale path like `/old/path/$HIPNAME.$OS.$F4.exr` instead of the productName you authored.

**Cause:** Karma RenderSettings LOP evaluates `$HIP/render/$HIPNAME.$OS.$F4.exr` at cook time, baking it as a **time-sampled** value on `productName`. After `stage.Flatten()`, setting `attr_spec.default = new_path` is ignored — time-sampled values always win over defaults in USD composition.

**Fix:** Clear time-sampled values before setting the default:

```python
attr = prim.GetAttribute("productName")
if attr and attr.GetTimeSamples():
    attr.Clear()
attr_spec = Sdf.AttributeSpec(prim_spec, "productName", Sdf.ValueTypeNames.Token)
attr_spec.default = new_path
```

**Diagnostic:** `attr.GetTimeSamples()` returns non-empty if time samples exist.

---

### Standalone husk: VEX Shaders Need opdef: URIs

> Houdini 21.0.631

**Symptom:** `Unhandled node type <name> in material`. Objects render default grey.

**Cause:** VEX shader resolution in husk works ONLY through `opdef:` URI resolution (e.g. `opdef:/Vop/principledshader::2.0?SurfaceVexCode`), which triggers on-demand VEX compilation via `VEX_VexResolver`. There is **no Sdr parser plugin for VEX/VFL** — the Sdr registry only handles `kma`, `mtlx`, `glslfx`, and `USD` source types. Baking opdef: references to VFL files on disk does nothing — husk cannot use them.

**Anti-patterns tried:**
- Baking VFL source to a file inside USDZ → husk can't read files from zip archives
- Extracting VFL to disk and overriding sourceAsset → no Sdr parser for VFL files
- Baking to disk with various file extensions → irrelevant, no parser exists

**Fix:** Preserve `opdef:` URIs for VEX shaders. If you must bake `opdef:` references for USDZ packaging (`CreateNewUsdzPackage` needs real files), override `info:sourceAsset` back to the original `opdef:` URI in a wrapper USDA layer:

```python
# During baking: record original opdef: URIs for Shader prims
# After USDZ creation: wrapper overrides sourceAsset back to opdef:

# In wrapper .usda:
# over "materials" { over "mirror" { over "mirror_surface" {
#     asset info:sourceAsset = @opdef:/Vop/principledshader::2.0?SurfaceVexCode@
# }}}
```

**Requirements:** Karma CPU only (not XPU). Houdini must be installed on the render machine — the OTL libraries (`$HH/otls/OPlibVop.hda`) must be loadable for factory shaders. Custom VOP HDAs need their `.hda` files deployed via `HOUDINI_OTLSCAN_PATH`.

**Fully portable alternative:** Replace VEX shaders with MaterialX (`mtlxstandard_surface`, `ND_*` nodes) or `UsdPreviewSurface`. These work with Karma CPU, XPU, and standalone husk without any Houdini dependencies.

---

### Velocity motion blur needs `velocities` + geosamples ≥ 2

> Houdini 20.0.1544

**Symptom:** No motion blur, and the motion-vector AOV is flat, though points move each frame.

**Cause:** Karma blurs along a `velocities` point attribute across ≥2 geometry time samples. `geosamples=1`, or a missing `velocities` on the USD, gives no blur and an empty AOV. A SOP `v` attribute drives this only once it reaches USD **as `velocities`** — some import LOPs drop it.

**Fix:** Author `v` as `velocities` on the imported geometry; set `geosamples≥2`, `enablemblur=1`, and a camera shutter. Confirm `velocities` on the USD prim, not just the SOP.

---

### EXRs carry the scene OCIO — apply the display transform on 8-bit export

> Houdini 20.0.1544

**Symptom:** PNG previews of a Karma EXR look dark or muddy.

**Cause:** When the session OCIO is an ACES config (`echo $OCIO`), Karma writes linear **ACEScg** EXRs. A straight 8-bit PNG skips the display transform, so it reads dark.

**Fix:** Apply an ACEScg→sRGB (the config's display) transform on EXR→PNG or previews — via `hoiiotool` / `ocioconvert` / OpenImageIO, not a bare `iconvert`.
