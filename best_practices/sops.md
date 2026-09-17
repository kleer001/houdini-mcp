# Best Practices — SOPs / geometry / file cache

Context-specific findings for SOPs and file caching. General rules live in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### `parm.set()` Silently Ignored When Expression Active

> Houdini 21.0.631

**`parm.set(value)` on a float/int parm is silently ignored if the parm has an active expression or keyframe.** The expression always takes priority. No error, no warning — the value just doesn't stick.

**Anti-pattern:** Created a `filecache::2.0` node and called `fc.parm("f1").set(100)`. The parm still evaluated to `1` because `f1` has a default expression (`$FSTART`). The `set()` call was completely ignored.

**Affected parms on filecache::2.0:** `f1` (`$FSTART`), `f2` (`$FEND`), `f3` (may have `$FINC`). String parms like `basedir` and `basename` are NOT affected — they store raw strings, not expressions.

**Fix:** Call `deleteAllKeyframes()` before `set()` to clear the expression first:

```python
fc.parm("f1").deleteAllKeyframes()
fc.parm("f1").set(100)  # Now actually takes effect
```

**Note:** This applies to any parm with a default expression, not just filecache nodes. Common offenders: `$FSTART`/`$FEND` on frame range parms, `ch("../parm")` on HDA-internal parms.

---

### hbatch `render` Only Works with ROPs, Not SOPs

> Houdini 21.0.631

**The hbatch `render` command silently does nothing when given a SOP path like a filecache node.** It only works with ROP nodes. No error, no output — just exits cleanly with rc=0.

**Anti-pattern:** `hbatch -c "mread scene.hip; render -f 1 1 /obj/geo/filecache1; quit"` — exits successfully but produces zero cache files.

**Fix:** Use hython with `pressButton()` on the filecache's `execute` parm instead:

```bash
hython -c '
import hou
hou.hipFile.load("scene.hip")
node = hou.node("/obj/geo/filecache1")
node.parm("execute").pressButton()
'
```

`pressButton()` is synchronous in hython — it blocks until all frames are written.
