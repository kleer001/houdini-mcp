"""Geometry inspection and export handlers."""
import os
import tempfile

import hou


def _vertex_count(geo):
    """Vertex count via intrinsic — `hou.Geometry` has no `.vertices()` method."""
    try:
        return int(geo.intrinsicValue("vertexcount"))
    except hou.OperationFailed:
        return sum(len(p.vertices()) for p in geo.prims())


def get_geo_summary(node_path):
    """Return geometry stats: point/prim/vertex counts, bbox, attributes."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    bbox = geo.boundingBox()
    return {
        "num_points": len(geo.points()),
        "num_prims": len(geo.prims()),
        "num_vertices": _vertex_count(geo),
        "bounding_box": {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
        },
        "point_attribs": [a.name() for a in geo.pointAttribs()],
        "prim_attribs": [a.name() for a in geo.primAttribs()],
        "detail_attribs": [a.name() for a in geo.globalAttribs()],
    }


def get_points(node_path, start=0, count=100, attribs=None):
    """Get point data with pagination. Returns positions and optional attrib values."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    points = geo.points()
    total = len(points)
    end = min(start + count, total)
    result_points = []
    for i in range(start, end):
        pt = points[i]
        pt_data = {"num": pt.number(), "pos": list(pt.position())}
        if attribs:
            for attr_name in attribs:
                attr = geo.findPointAttrib(attr_name)
                if attr:
                    pt_data[attr_name] = pt.attribValue(attr)
        result_points.append(pt_data)
    return {"total": total, "start": start, "count": len(result_points), "points": result_points}


def get_prims(node_path, start=0, count=100, attribs=None):
    """Get primitive data with pagination."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    prims = geo.prims()
    total = len(prims)
    end = min(start + count, total)
    result_prims = []
    for i in range(start, end):
        pr = prims[i]
        pr_data = {
            "num": pr.number(),
            "type": str(pr.type()),
            "vertex_count": pr.numVertices(),
        }
        if attribs:
            for attr_name in attribs:
                attr = geo.findPrimAttrib(attr_name)
                if attr:
                    pr_data[attr_name] = pr.attribValue(attr)
        result_prims.append(pr_data)
    return {"total": total, "start": start, "count": len(result_prims), "prims": result_prims}


def get_attrib_values(node_path, attrib_name, attrib_class="point"):
    """Get all values of an attribute. attrib_class: point, prim, vertex, detail."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    class_map = {
        "point": (geo.findPointAttrib, geo.pointFloatAttribValues, geo.pointIntAttribValues, geo.pointStringAttribValues),
        "prim": (geo.findPrimAttrib, geo.primFloatAttribValues, geo.primIntAttribValues, geo.primStringAttribValues),
    }
    if attrib_class == "detail":
        attr = geo.findGlobalAttrib(attrib_name)
        if not attr:
            raise ValueError(f"Detail attrib not found: {attrib_name}")
        return {"attrib": attrib_name, "class": "detail", "value": geo.attribValue(attrib_name)}
    finders = class_map.get(attrib_class)
    if not finders:
        raise ValueError(f"Unknown attrib class: {attrib_class}")
    find_fn = finders[0]
    attr = find_fn(attrib_name)
    if not attr:
        raise ValueError(f"Attrib not found: {attrib_name} ({attrib_class})")
    data_type = attr.dataType().name()
    if "Float" in data_type:
        values = list(finders[1](attrib_name))
    elif "Int" in data_type:
        values = list(finders[2](attrib_name))
    else:
        values = list(finders[3](attrib_name))
    return {"attrib": attrib_name, "class": attrib_class, "count": len(values), "values": values}


def set_detail_attrib(node_path, attrib_name, value):
    """Set a detail (global) attribute value."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    geo.addAttrib(hou.attribType.Global, attrib_name, value)
    geo.setGlobalAttribValue(attrib_name, value)
    return {"path": node_path, "attrib": attrib_name, "value": value}


def get_groups(node_path, group_type="point"):
    """List geometry groups. group_type: point, prim, edge, vertex."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    type_map = {
        "point": geo.pointGroups,
        "prim": geo.primGroups,
        "edge": geo.edgeGroups,
        "vertex": geo.vertexGroups,
    }
    fn = type_map.get(group_type)
    if not fn:
        raise ValueError(f"Unknown group type: {group_type}")
    groups = fn()
    return {
        "path": node_path,
        "type": group_type,
        "groups": [{"name": g.name(), "size": len(g)} for g in groups],
    }


def get_group_members(node_path, group_name, group_type="point"):
    """Get the members of a geometry group."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    if group_type == "point":
        group = geo.findPointGroup(group_name)
    elif group_type == "prim":
        group = geo.findPrimGroup(group_name)
    else:
        raise ValueError(f"Unsupported group type for members: {group_type}")
    if not group:
        raise ValueError(f"Group not found: {group_name}")
    members = [elem.number() for elem in group.iterEntries()]
    return {"group": group_name, "type": group_type, "count": len(members), "members": members}


def get_bounding_box(node_path):
    """Get the bounding box of a node's geometry."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    bbox = geo.boundingBox()
    size = bbox.sizevec()
    center = bbox.center()
    return {
        "min": list(bbox.minvec()),
        "max": list(bbox.maxvec()),
        "size": list(size),
        "center": list(center),
    }


def get_prim_intrinsics(node_path, prim_index=0):
    """Get intrinsic values of a primitive."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    prims = geo.prims()
    if prim_index >= len(prims):
        raise ValueError(f"Prim index {prim_index} out of range (max {len(prims) - 1})")
    prim = prims[prim_index]
    intrinsics = {}
    for name in prim.intrinsicNames():
        intrinsics[name] = str(prim.intrinsicValue(name))
    return {"prim_index": prim_index, "intrinsics": intrinsics}


def find_nearest_point(node_path, position):
    """Find the nearest point to a given position."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    pos = hou.Vector3(position)
    pt = geo.nearestPoint(pos)
    return {
        "point_num": pt.number(),
        "position": list(pt.position()),
        "query_position": position,
    }


def geo_export(node_path, format="obj", output=None):
    """Export geometry to a file. Formats: obj, gltf, glb, usd, usda, ply, bgeo.sc."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    geo = node.geometry()
    if not geo:
        raise ValueError(f"Node has no geometry: {node_path}")
    if not output:
        output = os.path.join(tempfile.gettempdir(), f"mcp_export.{format}")
    geo.saveToFile(output)
    bbox = geo.boundingBox()
    return {
        "exported": True,
        "file": output,
        "format": format,
        "num_points": len(geo.points()),
        "num_prims": len(geo.prims()),
        "num_vertices": _vertex_count(geo),
        "bounding_box": {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
        },
    }
