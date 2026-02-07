"""Scene management handlers."""
import os
import traceback

import hou


def get_asset_lib_status():
    """Checks if the user toggled asset library usage in hou.session."""
    use_assetlib = getattr(hou.session, "houdinimcp_use_assetlib", False)
    msg = ("Asset library usage is enabled."
           if use_assetlib
           else "Asset library usage is disabled.")
    return {"enabled": use_assetlib, "message": msg}


def get_scene_info():
    """Returns basic info about the current .hip file and a few top-level nodes."""
    try:
        hip_file = hou.hipFile.name()
        scene_info = {
            "name": os.path.basename(hip_file) if hip_file else "Untitled",
            "filepath": hip_file or "",
            "node_count": len(hou.node("/").allSubChildren()),
            "nodes": [],
            "fps": hou.fps(),
            "start_frame": hou.playbar.frameRange()[0],
            "end_frame": hou.playbar.frameRange()[1],
        }

        root = hou.node("/")
        contexts = ["obj", "shop", "out", "ch", "vex", "stage"]
        top_nodes = []

        for ctx_name in contexts:
            ctx_node = root.node(ctx_name)
            if ctx_node:
                children = ctx_node.children()
                for node in children:
                    if len(top_nodes) >= 10:
                        break
                    top_nodes.append({
                        "name": node.name(),
                        "path": node.path(),
                        "type": node.type().name(),
                        "category": ctx_name,
                    })
                if len(top_nodes) >= 10:
                    break

        scene_info["nodes"] = top_nodes
        return scene_info

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def save_scene(file_path=None):
    """Save the current scene, optionally to a new path."""
    if file_path:
        hou.hipFile.save(file_path)
    else:
        hou.hipFile.save()
    return {"saved": True, "file": hou.hipFile.name()}


def load_scene(file_path):
    """Load a .hip file."""
    hou.hipFile.load(file_path)
    return {"loaded": True, "file": hou.hipFile.name()}


def set_frame(frame):
    """Set the current frame in Houdini's playbar."""
    hou.setFrame(frame)
    return {"frame": frame}
