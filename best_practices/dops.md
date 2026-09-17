# Best Practices — DOPs / POPs / simulations

Context-specific findings for DOP networks and POP simulations. General rules and the "build nodes, not code" philosophy live in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md).

### Sim cadence: cook sequentially, resimulate after edits

> Houdini 21.0.596

**A DOP sim is stateful — it must be cooked forward from its start frame, in order.** Jumping straight to a late frame does not give a valid result, and reading a frame you didn't cook through returns stale or empty geometry.

- To evaluate frame N, step frames `start..N` in order, cooking each.
- **After changing any parameter feeding the sim, press the dopnet `resimulate` button** (or the cache is stale and your change appears to do nothing).
- Heavy multi-frame cooks issued in one `execute_houdini_code` call can exceed the bridge timeout — cook in chunks across calls if needed.

### Reading sim geometry: sample, don't loop over every point

> Houdini 21.0.596

**Iterating every point of a large particle system in Python (`for p in geo.points(): p.attribValue(...)`) over the bridge times out** — the round-trip cost per attribute read is high. Symptom: a generic "operation failed" with no node error.

**Fix:** sample a handful of points by index (`geo.points()[i]`), or aggregate inside a wrangle / detail attribute and read the single result. Reserve full iteration for tiny point counts.

### Gate real forces by a "released" group, don't move points with code

> Houdini 21.0.596

To release particles at a per-point time while keeping the "build nodes, not code" rule (see [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md)):

1. Birth **all** points at the start frame, still (zero velocity).
2. A POP wrangle (selection only) flags a point group when its time arrives: `if (@Frame >= @frelease) i@group_released = 1;`.
3. Point the real force nodes (POP Force, POP Wind, POP Drag) at **Group = `released`**.

Un-released points are in no group → receive no force → stay put with zero velocity. Released points fall/scatter under the actual solver integration. No `@v +=` anywhere. Angular velocity with no force-node equivalent (flutter) is the allowed kinematic exception: set `v@w` in a wrangle and let the solver integrate `@w → @orient`.

### POP Source from a SOP: set `soppath`, not just the context toggle

> Houdini 21.0.596

**`popsource` with "Use Context Geometry" (`usecontextgeo`) on did not emit the dopnet's SOP input** — births came out empty with no error. Setting the explicit SOP path worked:

```python
src.parm("usecontextgeo").set(0)
src.parm("soppath").set("/obj/.../merge_fields")
src.parm("emittype").set(0)                    # 0 = All Points (emit every source point)
src.parm("impulseactiveate").set(0)
src.parm("constantactivate").setExpression('$FF==1')   # emit once, at frame 1
src.parm("useframepointlimit").set(0)          # don't cap points/frame
src.parm("jitterbirthtime").set(0)             # keep points on their source positions
```

**`jitterbirthtime` (default 2) offsets birth in sub-frame time**, which nudges points off their exact source positions — for an image-reconstruction / grid layout it shows up as gaps and darkening. Zero it when point positions must match the source exactly.

### `removepoint` can silently do nothing

> Houdini 21.0.596

Deleting points with `removepoint(0, @ptnum)` in a wrangle over the bridge **left the points in place with no error**. To hide points reliably, either set `pscale = 0` (invisible, keeps a clean point↔primitive mapping for downstream copy-to-points), or select them into a point group and delete with a **Blast** node — and then **verify the resulting point count** (Blast's `grouptype` menu index for Points is not 0; confirm it culled what you meant).
