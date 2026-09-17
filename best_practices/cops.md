# Best Practices — Copernicus COPs

Context-specific findings for Copernicus (`Cop`) compositing, COP-HDAs, and COP diagnostics. General rules and routing live in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### Layer Naming

> Houdini 21.0.631

**The Layer Merge (average) node matches inputs by layer name, not by input index.** Mismatched names are **silently ignored** — no error, no warning, just missing pixels.

**Anti-pattern:** Created a Python Snippet COP with output named `"C"` feeding into a Layer Merge alongside a `"mono"` input. Merge output contained only the mono input. Zero contribution from the other layer, zero errors.

**Diagnosis:** Check `node.outputNames()` on each input to the merge.

**Fix:** Set your node's `output1_name` parm to match the upstream layer name. The `return` dict key must also match: `return {'mono': out_layer}`.

---

### ImageLayer Creation

> Houdini 21.0.631

When creating a new `hou.ImageLayer()` from scratch (e.g., in a Python Snippet COP), three things will break downstream nodes:

#### 1. Construction order matters

**Anti-pattern:** Set `setDataWindow()` before `setChannelCount()` / `setStorageType()`. Result: `"Provided buffer incorrect size"` on `setAllBufferElements()`.

Buffer size is calculated from resolution + channels + storage at the time the window is set. Set channel count and storage type **first**.

```python
out_layer = hou.ImageLayer()
out_layer.setChannelCount(1)                            # FIRST
out_layer.setStorageType(hou.imageLayerStorageType.Float32)  # FIRST
out_layer.setDataWindow(0, 0, width, height)            # THEN
out_layer.setDisplayWindow(0, 0, width, height)
out_layer.setAllBufferElements(result.tobytes())
```

#### 2. `setDataWindow` / `setDisplayWindow` take 4 separate args, not a list

**Anti-pattern:** Called `setDataWindow([0, 0, 1920, 1080])`. Fails with `"missing 3 required positional arguments"`.

**Fix:** `setDataWindow(0, 0, 1920, 1080)` — four separate ints.

#### 3. Copy all metadata from the source layer

**Anti-pattern:** Returned a new `hou.ImageLayer()` with correct pixel data but no attributes. Downstream Layer Merge **silently discarded** the entire layer.

A bare `hou.ImageLayer()` has zero attributes. Always copy metadata:

```python
out_layer.setBorder(input_layer.border())
out_layer.setPixelScale(input_layer.pixelScale())
out_layer.setTypeInfo(input_layer.typeInfo())
out_layer.setProjection(input_layer.projection())
out_layer.setAttributes(input_layer.attributes())
```

---

### Python Snippet COP

> Houdini 21.0.631

#### `kwargs` contains ImageLayer objects, not numpy arrays

Extract pixel data with:

```python
data = layer.allBufferElements(hou.imageLayerStorageType.Float32, channels)
arr = np.frombuffer(data, dtype=np.float32).reshape(height, width).copy()
```

The `.copy()` is required — the original buffer is read-only.

#### Input layers are GPU-resident and NOT frozen

**Anti-pattern:** Tried `setAllBufferElements()`, `makeConstant()`, and `freeze()` on `kwargs` input layers. All fail — they're GPU-resident with `isFrozen=False`.

**Fix:** Always create a new `hou.ImageLayer()` for output. Never modify the input in-place.

#### `hou` module IS accessible

Despite the docs stating "this node can't access the currently evaluating node", `import hou` works. You can call `hou.pwd()`, `hou.frame()`, `hou.node()`, and critically `node.layerAtFrame(frame)` for temporal effects. See [Temporal Access](#temporal-access-time-shifting).

---

### Temporal Access (Time-Shifting)

> Houdini 21.0.631

**Copernicus has no native timeshift COP.** The old COP2 `shift` node does not exist in Copernicus networks.

**Anti-patterns tried:**
- `op:` syntax in the File COP to reference another COP's output → `"Unable to read file"`
- Searching for `shift`, `timefilter`, `timeshift` in the Cop category → none exist
- File COP `videoframemethod` / `videoframe` with expressions → only works for on-disk sequences, not upstream COP outputs

**Workaround:** `node.layerAtFrame(float)` from Python (via `execute_houdini_code` or inside a Python Snippet COP). Cooks the target node at any frame and returns an `ImageLayer`.

```python
source = hou.pwd().inputs()[0]
layer_past = source.layerAtFrame(hou.frame() - 5)
layer_future = source.layerAtFrame(hou.frame() + 5)
```

**Performance:** Each call triggers a full upstream cook at that frame. 10 echo offsets = 10 extra cooks per frame.

---

### Node Categories

> Houdini 21.0.631

**Copernicus node category is `"Cop"`, not `"Cop2"`.** Use `node.childTypeCategory()` to query. Old COP2 nodes (`shift`, `timefilter`, `vopcop2filter`, etc.) are not available in Copernicus networks.

```python
parent = hou.node("/path/to/copnet")
for name in sorted(parent.childTypeCategory().nodeTypes().keys()):
    print(name)
```

---

### COP HDA Output Naming

> Houdini 21.0.631

**For COP HDAs, `outputNames()` is controlled by the `output` line in the DialogScript section of the HDA definition — NOT by the `outputname#` multiparm parm.**

**Anti-pattern:** Created a COP HDA with `outputname1` multiparm (matching the null node pattern) and set it to `"mono"`. `outputNames()` still returned `('output1',)` — the default connector name from the DialogScript. Downstream Layer Merge silently ignored the HDA's output.

**Diagnosis:** Read the HDA's DialogScript section: `hda_def.sections()['DialogScript'].contents()`. Look for the `output` line (format: `output <connector_name> <label>`).

**Fix:** Modify the DialogScript's `output` line to set the desired layer name:

```python
hda_def = node.type().definition()
ds = hda_def.sections()['DialogScript'].contents()
ds = ds.replace('output\toutput1\tC', 'output\tlayer\tlayer')
hda_def.sections()['DialogScript'].setContents(ds)
node.matchCurrentDefinition()
```

**Note:** The `outputname#` multiparm on a COP HDA has no effect on `outputNames()`. It works on built-in nodes like `null` because their output naming is handled in C++, not via DialogScript.

---

### Resolution Mismatch at Sequence Boundaries

> Houdini 21.0.631

**`layerAtFrame()` returns a default 1024×1024 layer for frames outside the source sequence range.** No error — just wrong resolution.

**Anti-pattern:** Echo effect called `layerAtFrame(frame - 5)` near the start of a sequence (frame 1001). Frames before 1001 returned 1024×1024 instead of the expected 1920×1080. `np.maximum()` then failed or produced garbage due to shape mismatch.

**Fix:** Guard against resolution mismatch before blending:

```python
echo_layer = source.layerAtFrame(echo_frame)
if echo_layer.bufferResolution() != (width, height):
    continue
```

---

### HDA `matchCurrentDefinition` Resets Internals

> Houdini 21.0.631

**Calling `node.matchCurrentDefinition()` on an unlocked HDA reverts ALL internal edits** — manually created nodes, rewired connections, and parm changes inside the HDA are lost.

**Anti-pattern:** Unlocked an HDA with `allowEditingOfContents()`, created a null node inside, wired it into the chain, then called `matchCurrentDefinition()` to refresh the outer node. The null node disappeared and the internal chain reverted to the saved definition.

**Fix:** Make all changes to the HDA definition (DialogScript, parm template, etc.) BEFORE calling `matchCurrentDefinition()`. Or save the definition (`hda_def.save()`) after internal edits and before refreshing.

---

### COP VEX Wrangle: `volumesamplep` Is Input-0-Only

> Houdini 21.0

**`volumesamplep(input, "layer", pos)` silently returns `{0,0,0}` for any `input` other than `0`.** There is no error, no warning, and no cook failure — just black pixels.

**Anti-pattern:** Wrangle with source at input 0 (resample) and original image at input 1. Used `volumesamplep(1, "C", tiled_pos)` to sample the original at a custom UV. Always returned zero.

**Fix:** Only input 0 is accessible for custom-position sampling via `volumesamplep`. If you need to sample a different COP input at arbitrary positions, restructure so that input is connected at slot 0. For tiling specifically: force the resample to STRETCH fit mode so its image space is identical to the source's, then sample `volumesamplep(0, "C", tiled_pos)` on the resample — it gives the same result as sampling the source directly.

**Note:** `volumeres(input, "layer")` has the same limitation — returns 0 for non-zero input indices and for layer names that don't exist on the input. Read source dimensions from HDA hidden parms set by Python callbacks instead.

---

### COP VEX Wrangle: Coordinate System Is Image Space

> Houdini 21.0

**In a COP wrangle, `@P` is in image space — `(-1, -1)` at top-left to `(+1, +1)` at bottom-right — not pixel indices.** `volumesamplep` expects image-space coordinates.

**Verified:** At pixel `(0, 0)` of a 1024-wide image, `@P.x ≈ -0.999`. At pixel `(1023, 0)`, `@P.x ≈ +0.999`.

**Coordinate conversion from tile UV (0..1) to image space:**

```c
// Naïve — lands on cell boundaries at u=0.25, 0.5 etc.; bilinear bleed produces 0.5 gray
float ip_x = 2.0f * u - 1.0f;

// Correct — shifts to voxel center; avoids boundary interpolation
float ip_x = 2.0f * u - 1.0f + 1.0f / src_w;
```

The `+ 1/src_w` half-pixel shift matters whenever your UV lands near a voxel boundary (e.g. at checkerboard cell edges). Without it, bilinear interpolation between a white and a black cell produces 0.5.

**Pixel reads from Python:** Use `layer.bufferIndex(x, y)` to read individual pixels — not `.pixel()` (doesn't exist on `hou.ImageLayer`). `bufferIndexV4(x, y)` returns all four channels.

---

### COP HDA Callbacks Cannot Modify Internal Node Parms

> Houdini 21.0

**Python callbacks (`OnCreated`, `OnParmChanged`, `OnInputChanged`) raise `hou.PermissionError: locked assets` if they attempt to call `parm.set()` on any node inside the HDA's locked subnet.**

**Anti-pattern:** `onParmChanged` computed a fit mode integer and called `resample.parm("stretch").set(computed_value)` on the internal resample node. Raised `PermissionError` at cook time.

**Fix:** Callbacks may only modify the HDA's **own** parameters. Drive internal node parms exclusively via HScript channel-reference expressions baked in at build time:

```python
# At HDA build time — expressions are locked in permanently:
rs.parm("stretch").setExpression('ch("../fit_mode")', language=hou.exprLanguage.Hscript)

# In OnParmChanged — only touch the HDA's own parms:
def onParmChanged(kwargs):
    node = kwargs["node"]
    node.parm("_computed_res_w").set(...)   # HDA's own hidden parm — OK
    # node.parm("internal_rs_parm").set()  # PermissionError — never do this
```

---

### COP HDA: Prototype Parm Expressions Don't Persist

> Houdini 21.0

**`parm.setExpression()` called on the prototype/build instance of an HDA is an instance-level override. It is NOT saved into the HDA type definition.** New instances created from the saved HDA get the default value (e.g. `0`), never the expression.

**Anti-pattern:** After `hda_def.setParmTemplateGroup(ptg)` and before `hda_def.save()`, called `hda_node.parm("tile_mode_int").setExpression('ch("tile_mode")')`. The build instance had the expression. Every new instance of the HDA evaluated `tile_mode_int` as `0`.

**Symptom:** A hidden integer mirror parm always reads its default value regardless of what the source menu parm is set to.

**Fix:** Maintain integer-mirror parms via Python callbacks, not expressions:

```python
# In onCreated AND _update():
node.parm("tile_mode_int").set(node.parm("tile_mode").eval())
```

**Also note:** In headless hython, `parm.set()` does **not** fire `OnParmChanged` event handlers. When testing, call your update function manually: `node.hdaModule()._update(node)`.

---

### HScript Menu Parm Conditionals Require Integer Comparisons

> Houdini 21.0

**Using `chs("parm") == "token"` in an HScript expression causes a "Bad data type for function or operation" cook error.** No visual feedback during build — the error only surfaces when the node cooks.

**Anti-pattern:**

```python
# Breaks at cook time:
FILTER_EXPR = 'if(chs("../filter_mode")=="auto", 4, if(chs(...)==..., ...))'
```

**Fix:** Menu parms (`MenuParmTemplate`) store integer indices. Use `ch("parm")` (not `chs`) and compare against the zero-based index:

```python
# Works — compare index integers, not token strings:
FILTER_EXPR = (
    'if(ch("../filter_mode")==0, 4, '   # auto → catmull-rom
    'if(ch("../filter_mode")==1, 0, '   # point
    # ...
    '1))'
)
```

The token strings shown in the UI (`"auto"`, `"point"`) are only accessible via `chs()`, but `chs()` comparisons in `if()` expressions do not work. Always use the integer index from `ch()`.

---

### HDA OnParmChanged Event Section Does Not Fire

> Houdini 21.0

**Adding an `OnParmChanged` section to an HDA definition has no effect — Houdini does not fire it when parameters change.** The section is stored silently and never called. `OnCreated` and `OnInputChanged` are the only reliably fired interactive HDA events.

**Anti-pattern:**

```python
hda_def.addSection("OnParmChanged", "kwargs['node'].hdaModule().onParmChanged(kwargs)")
hda_def.setExtraFileOption("OnParmChanged/IsPython", True)
# Never fires — parameters changing in the UI do nothing.
```

**Fix:** Set `script_callback` on each `ParmTemplate` that needs to trigger Python when changed. This fires on interactive edits and is stored in the HDA type definition, so it persists to every new instance without per-instance setup:

```python
def _cb(pt):
    pt.setScriptCallback("kwargs['node'].hdaModule().onParmChanged(kwargs)")
    pt.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    return pt

width_pt = hou.IntParmTemplate("width", "Width", 1)
_cb(width_pt)
```

`kwargs['node']` is the node, `kwargs['parm_name']` is the changed parameter name, `kwargs['script_value']` is the new value.

---

## Merge / Blend Mode Math Reference

Comprehensive reference for compositing blend modes. Useful when implementing custom VEX filters.

Source: [Nuke Merge Operations](https://learn.foundry.com/nuke/9.0/content/comp_environment/merging/merge_operations.html)

Where **A = foreground**, **B = background**, **a/b = respective alpha**:

| Mode | Formula |
|---|---|
| Over | `A + B(1-a)` |
| Under | `A(1-b) + B` |
| Plus / Add | `A + B` |
| Multiply | `AB` |
| Screen | `A + B - AB` |
| Max / Lighten | `max(A, B)` |
| Min / Darken | `min(A, B)` |
| Soft Light | If `AB < 1`: `B(2A + B(1 - AB))`, else: `2AB` |
| Hard Light | If `A < 0.5`: `2AB`, else: `1 - 2(1-A)(1-B)` |
| Overlay | Hard Light with inputs swapped |
| Color Dodge | `B / (1-A)` |
| Color Burn | `1 - (1-B)/A` |
| Difference | `|A - B|` |
| Exclusion | `A + B - 2AB` |

---

### Diagnostics Workflow

> Houdini 21.0.631

When something looks wrong in a COP network, use `execute_houdini_code` to inspect systematically:

1. **Check network topology** — iterate `parent.children()`, print inputs/outputs for each node.
2. **Check for errors** — `node.errors()` and `node.warnings()` on each node in the chain.
3. **Check layer names first** — `node.outputNames()` mismatches are the #1 cause of silent failures in Copernicus. See [Layer Naming](#layer-naming).
4. **Compare pixel values** — `layer.allBufferElements()` + numpy at specific coordinates. Don't trust visual inspection alone.
5. **Compare layer metadata** — `outputNames()`, `channelCount()`, `attributes()`, `typeInfo()` between working and broken paths.
6. **Use a switch node for A/B testing** — insert a switch to isolate which part of the chain causes the issue.

---

### Copernicus Cooks Nothing in Headless hython

**Problem:** Copernicus (`Cop`) networks produce no pixels when the bridge auto-launches a headless `hython` session.

**Symptom:** A `file` COP cooks with no errors, but `node.layerAtFrame(frame)` returns `None`; downstream nodes fail with `source is missing`; `rop_image` render fails with `Failed to cook layers`. No error explains why.

**Cause:** Copernicus is GPU-accelerated. A headless `hython` with no GPU/display context cannot cook COP layers at all.

**Fix:** Run Copernicus work in a GUI (GPU-backed) Houdini session. For headless pixel work, use `numpy`/`PIL` inside `execute_houdini_code` instead of a COP network. Validated: Houdini 21.0.631.
