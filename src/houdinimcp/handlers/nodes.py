"""Node CRUD, wiring, flags, layout, and material handlers."""
import traceback

import hou


def create_node(node_type, parent_path="/obj", name=None, position=None, parameters=None):
    """Creates a new node in the specified parent."""
    try:
        parent = hou.node(parent_path)
        if not parent:
            raise ValueError(f"Parent path not found: {parent_path}")

        node = parent.createNode(node_type, node_name=name)
        if position and len(position) >= 2:
            node.setPosition([position[0], position[1]])
        if parameters:
            for p_name, p_val in parameters.items():
                parm = node.parm(p_name)
                if parm:
                    parm.set(p_val)

        return {
            "name": node.name(),
            "path": node.path(),
            "type": node.type().name(),
            "position": list(node.position()),
        }
    except Exception as e:
        raise Exception(f"Failed to create node: {str(e)}")


def modify_node(path, parameters=None, position=None, name=None):
    """Modifies an existing node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")

    changes = []
    old_name = node.name()

    if name and name != old_name:
        node.setName(name)
        changes.append(f"Renamed from {old_name} to {name}")

    if position and len(position) >= 2:
        node.setPosition([position[0], position[1]])
        changes.append(f"Position set to {position}")

    if parameters:
        for p_name, p_val in parameters.items():
            parm = node.parm(p_name)
            if parm:
                old_val = parm.eval()
                parm.set(p_val)
                changes.append(f"Parameter {p_name} changed from {old_val} to {p_val}")

    return {"path": node.path(), "changes": changes}


def delete_node(path):
    """Deletes a node from the scene."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    node_path = node.path()
    node_name = node.name()
    node.destroy()
    return {"deleted": node_path, "name": node_name}


def get_node_info(path):
    """Returns detailed information about a single node."""
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")

    node_info = {
        "name": node.name(),
        "path": node.path(),
        "type": node.type().name(),
        "category": node.type().category().name(),
        "position": [node.position()[0], node.position()[1]],
        "color": list(node.color()) if node.color() else None,
        "is_bypassed": node.isBypassed(),
        "is_displayed": getattr(node, "isDisplayFlagSet", lambda: None)(),
        "is_rendered": getattr(node, "isRenderFlagSet", lambda: None)(),
        "parameters": [],
        "inputs": [],
        "outputs": []
    }

    for i, parm in enumerate(node.parms()):
        if i >= 20:
            break
        node_info["parameters"].append({
            "name": parm.name(),
            "label": parm.label(),
            "value": str(parm.eval()),
            "raw_value": parm.rawValue(),
            "type": parm.parmTemplate().type().name()
        })

    for i, in_node in enumerate(node.inputs()):
        if in_node:
            node_info["inputs"].append({
                "index": i,
                "name": in_node.name(),
                "path": in_node.path(),
                "type": in_node.type().name()
            })

    for i, out_conn in enumerate(node.outputConnections()):
        out_node = out_conn.outputNode()
        node_info["outputs"].append({
            "index": i,
            "name": out_node.name(),
            "path": out_node.path(),
            "type": out_node.type().name(),
            "input_index": out_conn.inputIndex()
        })

    return node_info


def connect_nodes(src_path, dst_path, dst_input_index=0, src_output_index=0):
    """Connect two nodes: src output -> dst input."""
    src = hou.node(src_path)
    dst = hou.node(dst_path)
    if not src:
        raise ValueError(f"Source node not found: {src_path}")
    if not dst:
        raise ValueError(f"Destination node not found: {dst_path}")
    dst.setInput(dst_input_index, src, src_output_index)
    return {
        "connected": True,
        "src": src.path(),
        "dst": dst.path(),
        "dst_input": dst_input_index,
        "src_output": src_output_index,
    }


def disconnect_node_input(node_path, input_index=0):
    """Disconnect a specific input on a node."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    node.setInput(input_index, None)
    return {"disconnected": True, "node": node.path(), "input_index": input_index}


def set_node_flags(node_path, display=None, render=None, bypass=None):
    """Set display, render, and/or bypass flags on a node."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    changes = []
    if display is not None:
        node.setDisplayFlag(display)
        changes.append(f"display={display}")
    if render is not None:
        node.setRenderFlag(render)
        changes.append(f"render={render}")
    if bypass is not None:
        node.bypass(bypass)
        changes.append(f"bypass={bypass}")
    return {"path": node.path(), "changes": changes}


def layout_children(node_path="/obj"):
    """Auto-layout child nodes."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    node.layoutChildren()
    return {"path": node.path(), "laid_out": True}


def set_node_color(node_path, color):
    """Set a node's color as [r, g, b] (0-1 range)."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    if len(color) != 3:
        raise ValueError(f"Color must be [r, g, b], got: {color}")
    node.setColor(hou.Color(color[0], color[1], color[2]))
    return {"path": node.path(), "color": color}


def set_material(node_path, material_type="principledshader", name=None, parameters=None):
    """Creates or applies a material to an OBJ node."""
    try:
        target_node = hou.node(node_path)
        if not target_node:
            raise ValueError(f"Node not found: {node_path}")

        if target_node.type().category().name() != "Object":
            raise ValueError(
                f"Node {node_path} is not an OBJ-level node and cannot accept direct materials."
            )

        mat_context = hou.node("/mat")
        if not mat_context:
            mat_context = hou.node("/shop")
            if not mat_context:
                raise RuntimeError("No /mat or /shop context found to create materials.")

        mat_name = name or (f"{material_type}_auto")
        mat_node = mat_context.node(mat_name)
        if not mat_node:
            mat_node = mat_context.createNode(material_type, mat_name)

        if parameters:
            for k, v in parameters.items():
                p = mat_node.parm(k)
                if p:
                    p.set(v)

        mat_parm = target_node.parm("shop_materialpath")
        if mat_parm:
            mat_parm.set(mat_node.path())
        else:
            geo_sop = target_node.node("geometry")
            if not geo_sop:
                raise RuntimeError("No 'geometry' node found inside OBJ to apply material to.")

            material_sop = geo_sop.node("material1")
            if not material_sop:
                material_sop = geo_sop.createNode("material", "material1")
                first_sop = None
                for c in geo_sop.children():
                    if c.isDisplayFlagSet():
                        first_sop = c
                        break
                if first_sop:
                    material_sop.setFirstInput(first_sop)
                material_sop.setDisplayFlag(True)
                material_sop.setRenderFlag(True)

            mat_sop_parm = material_sop.parm("shop_materialpath1")
            if mat_sop_parm:
                mat_sop_parm.set(mat_node.path())
            else:
                raise RuntimeError(
                    "No shop_materialpath1 on Material SOP to assign the material."
                )

        return {
            "status": "ok",
            "material_node": mat_node.path(),
            "applied_to": target_node.path(),
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e), "node": node_path}


def set_expression(node_path, parm_name, expression, language="hscript"):
    """Set an expression on a node parameter."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    parm = node.parm(parm_name)
    if not parm:
        raise ValueError(f"Parameter not found: {parm_name} on {node_path}")
    lang = hou.exprLanguage.Hscript if language == "hscript" else hou.exprLanguage.Python
    parm.setExpression(expression, lang)
    return {
        "path": node.path(),
        "parm": parm_name,
        "expression": expression,
        "language": language,
    }


def find_error_nodes(root_path="/obj"):
    """Scan node hierarchy for cook errors and warnings."""
    root = hou.node(root_path)
    if not root:
        raise ValueError(f"Root node not found: {root_path}")
    error_nodes = []
    for node in root.allSubChildren():
        if node.errors():
            error_nodes.append({
                "path": node.path(),
                "type": node.type().name(),
                "errors": node.errors(),
            })
        elif node.warnings():
            error_nodes.append({
                "path": node.path(),
                "type": node.type().name(),
                "warnings": node.warnings(),
            })
    return {"root": root_path, "error_count": len(error_nodes), "nodes": error_nodes}
