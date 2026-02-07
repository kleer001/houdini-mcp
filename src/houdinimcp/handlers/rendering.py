"""Rendering handlers (OpenGL, Karma, Mantra, flipbook)."""
import os
import tempfile
import traceback
import base64

import hou
from ..HoudiniMCPRender import render_single_view, render_quad_view, render_specific_camera


def _process_rendered_image(filepath, camera_path=None, view_name=None):
    """Read, base64-encode, and return metadata for a rendered image file."""
    if not filepath or not os.path.exists(filepath):
        return {"status": "error", "message": f"Rendered file not found: {filepath}",
                "origin": "_process_rendered_image"}

    _, ext = os.path.splitext(filepath)
    fmt = ext[1:].lower() if ext else 'unknown'

    resolution = [0, 0]
    if camera_path:
        cam_node = hou.node(camera_path)
        if cam_node and cam_node.parm("resx") and cam_node.parm("resy"):
            resolution = [cam_node.parm("resx").eval(), cam_node.parm("resy").eval()]

    with open(filepath, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

    result_data = {
        "status": "success",
        "format": fmt,
        "resolution": resolution,
        "image_base64": encoded_string,
        "filepath_on_server": filepath,
    }
    if view_name:
        result_data["view_name"] = view_name
    return result_data


def handle_render_single_view(orthographic=False, rotation=(0, 90, 0),
                               render_path=None, render_engine="opengl",
                               karma_engine="cpu"):
    """Handles the 'render_single_view' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    try:
        if isinstance(rotation, list):
            rotation = tuple(rotation)
        filepath = render_single_view(
            orthographic=orthographic,
            rotation=rotation,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        return _process_rendered_image(filepath, "/obj/MCP_CAMERA")
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Single View Failed: {str(e)}",
                "origin": "handle_render_single_view"}


def handle_render_quad_view(orthographic=True, render_path=None,
                             render_engine="opengl", karma_engine="cpu"):
    """Handles the 'render_quad_view' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    try:
        filepaths = render_quad_view(
            orthographic=orthographic,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        results = []
        camera_path = "/obj/MCP_CAMERA"
        for fp in filepaths:
            view_name = None
            try:
                filename = os.path.basename(fp)
                parts = filename.split('_')
                if len(parts) > 2:
                    view_name = parts[2]
            except Exception:
                pass
            results.append(_process_rendered_image(fp, camera_path, view_name))
        return {"status": "success", "results": results}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Quad View Failed: {str(e)}",
                "origin": "handle_render_quad_view"}


def handle_render_specific_camera(camera_path, render_path=None,
                                   render_engine="opengl", karma_engine="cpu"):
    """Handles the 'render_specific_camera' command."""
    if not render_path:
        render_path = tempfile.gettempdir()
    if not camera_path or not hou.node(camera_path):
        return {"status": "error",
                "message": f"Camera path '{camera_path}' is invalid or node not found.",
                "origin": "handle_render_specific_camera"}
    try:
        filepath = render_specific_camera(
            camera_path=camera_path,
            render_path=render_path,
            render_engine=render_engine,
            karma_engine=karma_engine
        )
        return _process_rendered_image(filepath, camera_path)
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"Render Specific Camera Failed: {str(e)}",
                "origin": "handle_render_specific_camera"}


def render_flipbook(frame_range=None, output=None, resolution=None):
    """Render a flipbook sequence from the viewport."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found for flipbook")
    settings = viewer.flipbookSettings().stash()
    if frame_range and len(frame_range) == 2:
        settings.frameRange((frame_range[0], frame_range[1]))
    if not output:
        output = os.path.join(tempfile.gettempdir(), "mcp_flipbook.$F4.jpg")
    settings.output(output)
    if resolution and len(resolution) == 2:
        settings.resolution((resolution[0], resolution[1]))
    viewer.flipbook(settings=settings)
    return {"flipbook": True, "output": output}
