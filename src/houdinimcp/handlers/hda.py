"""HDA management handlers."""
import hou


def hda_list(category=None):
    """List available HDA definitions, optionally filtered by category."""
    result = []
    for cat_name, cat in hou.nodeTypeCategories().items():
        if category and cat_name != category:
            continue
        for name, node_type in cat.nodeTypes().items():
            defn = node_type.definition()
            if defn:
                result.append({
                    "name": name,
                    "category": cat_name,
                    "label": node_type.description(),
                    "library": defn.libraryFilePath(),
                })
        if len(result) >= 200:
            break
    return {"count": len(result), "definitions": result}


def hda_get(node_type, category=None):
    """Get detailed info about an HDA definition."""
    nt = None
    if category:
        cat = hou.nodeTypeCategories().get(category)
        if not cat:
            raise ValueError(f"Category not found: {category}")
        nt = cat.nodeTypes().get(node_type)
    else:
        for cat in hou.nodeTypeCategories().values():
            nt = cat.nodeTypes().get(node_type)
            if nt:
                break
    if not nt:
        raise ValueError(f"Node type not found: {node_type}")
    defn = nt.definition()
    if not defn:
        raise ValueError(f"No HDA definition for: {node_type}")
    return {
        "name": nt.name(),
        "label": nt.description(),
        "category": nt.category().name(),
        "library": defn.libraryFilePath(),
        "version": defn.version(),
        "max_inputs": defn.maxNumInputs(),
        "help": defn.comment() or "",
        "sections": list(defn.sections().keys()),
    }


def hda_install(file_path):
    """Install an HDA file into the current Houdini session."""
    hou.hda.installFile(file_path)
    definitions = hou.hda.definitionsInFile(file_path)
    installed = []
    for defn in definitions:
        installed.append({
            "name": defn.nodeType().name(),
            "category": defn.nodeTypeCategory().name(),
            "label": defn.description(),
        })
    return {"installed": True, "file": file_path, "definitions": installed}


def hda_create(node_path, name, label, file_path):
    """Create an HDA from an existing node."""
    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    hda_node = node.createDigitalAsset(
        name=name,
        hda_file_name=file_path,
        description=label,
    )
    return {"created": True, "path": hda_node.path(), "name": name, "file": file_path}
