"""USD/Solaris (LOP) handlers."""
import hou


def lop_stage_info(path):
    """Get USD stage info from a LOP node: prims, layers, time codes."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    root_prims = [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]
    default_prim = str(stage.GetDefaultPrim().GetPath()) if stage.HasDefaultPrim() else None
    return {
        "path": node.path(),
        "prim_count": len(list(stage.Traverse())),
        "root_prims": root_prims,
        "default_prim": default_prim,
        "layer_count": len(stage.GetLayerStack()),
        "start_time": stage.GetStartTimeCode(),
        "end_time": stage.GetEndTimeCode(),
    }


def lop_prim_get(path, prim_path, include_attrs=False):
    """Get details of a specific USD prim."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise ValueError(f"Prim not found: {prim_path}")
    info = {
        "prim_path": str(prim.GetPath()),
        "type": str(prim.GetTypeName()),
        "children": [str(c.GetPath()) for c in prim.GetChildren()],
    }
    if include_attrs:
        attrs = {}
        for attr in prim.GetAttributes():
            val = attr.Get()
            attrs[attr.GetName()] = str(val) if val is not None else None
        info["attributes"] = attrs
    return info


def lop_prim_search(path, pattern, type_name=None):
    """Search for USD prims matching a pattern."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    rule = hou.LopSelectionRule()
    rule.setPathPattern(pattern)
    if type_name:
        rule.setTypeName(type_name)
    prims = rule.expandedPaths(node)
    return {
        "path": node.path(),
        "pattern": pattern,
        "matches": [str(p) for p in prims],
        "count": len(prims),
    }


def lop_layer_info(path):
    """Get USD layer stack info from a LOP node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    stage = node.stage()
    if not stage:
        raise ValueError(f"No USD stage on: {path}")
    layers = []
    for layer in stage.GetLayerStack():
        layers.append({
            "identifier": layer.identifier,
            "path": layer.realPath,
        })
    return {"path": node.path(), "layers": layers, "count": len(layers)}


def lop_import(path, file, method="reference", prim_path=None):
    """Import a USD file via reference or sublayer."""
    parent = hou.node(path)
    if not parent:
        raise ValueError(f"Parent path not found: {path}")
    if method == "reference":
        node = parent.createNode("reference", "usd_import")
        node.parm("filepath1").set(file)
        if prim_path:
            node.parm("primpath").set(prim_path)
    elif method == "sublayer":
        node = parent.createNode("sublayer", "usd_import")
        node.parm("filepath1").set(file)
    else:
        raise ValueError(f"Unknown import method: {method}")
    return {"imported": True, "path": node.path(), "file": file, "method": method}
