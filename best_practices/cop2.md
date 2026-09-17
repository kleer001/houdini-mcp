# Best Practices — COP2 (Legacy Compositing)

Context-specific findings for legacy COP2 (`Cop2`). General rules live in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### COP2 VEX Filter Custom Shaders

> Houdini 21.0.631

**The `vexfilter` node cannot find custom `.vex` shaders by short name from user directories.** It only resolves short names from the system `$HH/vex/Cop2/` directory.

**Anti-pattern:** Compiled a `.vfl` to `~/houdini21.0/vex/Cop2/softlight.vex` (which IS on `HOUDINI_PATH`), set `function` parm to `"softlight"`. Error: `"Could not find VEX Cop2 shader 'softlight'"`.

**Fix:** Use the full absolute path without extension:

```python
node.parm("function").set("/home/user/houdini21.0/vex/Cop2/softlight")
```

**VFL compilation:** `vcc myfilter.vfl` from the target directory. The `cop2` context is declared in the file itself — no `-d` flag needed (that flag means "compile all functions", not "set context").

---

### Copernicus to COP2 Translation

> Houdini 21.0.631

**Copernicus (`copnet`, child category `Cop`) and COP2 (`cop2net`, child category `Cop2`) are different systems.** Node types don't cross between them.

Key type mappings:

| Copernicus | COP2 | Notes |
|---|---|---|
| `blend` (mode=over) | `over` | Input order swapped: COP2 `over` is FG=in0, BG=in1 (Copernicus blend is A/BG=in0, B/FG=in1) |
| `blend` (mode=max) | `max` | `mask` parm → `effectamount` parm |
| `xform2d` | `xform` | Same parm names (tx, ty, etc.) |
| `constant` | `color` | `f4r/f4g/f4b` → `colorr/colorg/colorb`; COP2 `color` is a generator (set resolution explicitly) |
| `resample` | `scale` | COP2 `scale` uses explicit resolution, not a reference input |
| `rop_image` | `rop_comp` | `filename` → `filename1`; frame range parms differ |
| `channelswap` | `channelcopy` | No direct equivalent; consider skipping if `mono` is downstream |
| `file`, `null`, `mono`, `invert`, `gamma`, `layer` | same name | Parm names may differ (e.g. COP2 file uses `filename1`) |

---

### COP2 File Node Frame Range

> Houdini 21.0.631

**COP2 `file` node shows a grey dotted X when the current frame is outside the node's `start`/`length` range.** No error — just a blank frame with a grey X overlay.

**Anti-pattern:** File node with expression-based frame offset (e.g. `` `padzero(4,$F-1001)` ``) mapping frames 1002–1265 to files frame_0001.png–frame_0264.png. Default `start=1` and `length=264` meant valid range was frames 1–264, but timeline was at frame 1016.

**Fix:** Set `start` to match the first Houdini frame where a file exists (1002 in this case). The `length` stays at the file count (264).
