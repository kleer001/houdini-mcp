"""Geometry inspection and export handlers."""
import os
import tempfile

import hou


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
        "num_vertices": len(geo.vertices()),
        "bounding_box": {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
        },
        "point_attribs": [a.name() for a in geo.pointAttribs()],
        "prim_attribs": [a.name() for a in geo.primAttribs()],
        "detail_attribs": [a.name() for a in geo.globalAttribs()],
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
        "num_vertices": len(geo.vertices()),
        "bounding_box": {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
        },
    }
