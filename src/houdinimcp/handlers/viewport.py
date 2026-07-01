"""Viewport and pane manipulation handlers."""
import os

import hou


def list_panes():
    """List all pane tabs in the desktop."""
    panes = []
    for tab in hou.ui.paneTabs():
        panes.append({
            "name": tab.name(),
            "type": str(tab.type()),
            "is_current": tab.isCurrentTab(),
        })
    return {"count": len(panes), "panes": panes}


def get_viewport_info():
    """Get current viewport settings."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    settings = viewport.settings()
    return {
        "name": viewport.name(),
        "type": str(viewport.type()),
        "camera": viewport.camera().path() if viewport.camera() else None,
        "display_set": str(settings.displaySet()),
    }


def set_viewport_camera(camera_path):
    """Set the viewport camera to a specific camera node."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    cam = hou.node(camera_path)
    if not cam:
        raise ValueError(f"Camera not found: {camera_path}")
    viewport = viewer.curViewport()
    viewport.setCamera(cam)
    return {"camera": camera_path}


def set_viewport_display(shading_mode=None, guide=None):
    """Set viewport display options (shading mode, guides)."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    settings = viewport.settings()
    changes = []
    if shading_mode is not None:
        mode_map = {
            "wireframe": hou.glShadingType.Wire,
            "flat": hou.glShadingType.Flat,
            "smooth": hou.glShadingType.Smooth,
            "smooth_wire": hou.glShadingType.SmoothWire,
        }
        mode = mode_map.get(shading_mode)
        if mode is not None:
            settings.setDisplaySet(mode)
            changes.append(f"shading={shading_mode}")
    if guide is not None:
        settings.enableGuide(hou.viewportGuide.NodeGuides, guide)
        changes.append(f"guides={'on' if guide else 'off'}")
    return {"changes": changes}


def set_viewport_renderer(renderer):
    """Set the viewport renderer (GL, Karma, etc.)."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    viewport.changeType(hou.geometryViewportType.__dict__.get(renderer, hou.geometryViewportType.Perspective))
    return {"renderer": renderer}


def frame_selection():
    """Frame the viewport on the current selection."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    viewport.frameSelected()
    return {"framed": "selection"}


def frame_all():
    """Frame the viewport on all geometry."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    viewport.frameAll()
    return {"framed": "all"}


def set_viewport_direction(direction):
    """Set viewport to a standard direction: front, back, left, right, top, bottom, persp."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    viewport = viewer.curViewport()
    dir_map = {
        "front": hou.geometryViewportType.Front,
        "back": hou.geometryViewportType.Back,
        "left": hou.geometryViewportType.Left,
        "right": hou.geometryViewportType.Right,
        "top": hou.geometryViewportType.Top,
        "bottom": hou.geometryViewportType.Bottom,
        "persp": hou.geometryViewportType.Perspective,
    }
    vtype = dir_map.get(direction)
    if vtype is None:
        raise ValueError(f"Unknown direction: {direction}. Use: {list(dir_map.keys())}")
    viewport.changeType(vtype)
    return {"direction": direction}


def capture_screenshot(output_path=None):
    """Capture a screenshot of the current viewport via single-frame flipbook.

    `hou.GeometryViewport.saveAsImage` was removed in Houdini 21; the supported
    path is a single-frame flipbook through the SceneViewer.
    """
    import tempfile  # noqa: local import for optional temp path
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        raise RuntimeError("No scene viewer found")
    if not output_path:
        output_path = os.path.join(tempfile.gettempdir(), "mcp_screenshot.png")
    output_path = output_path.replace("\\", "/")
    frame = int(hou.frame())
    settings = viewer.flipbookSettings().stash()
    settings.frameRange((frame, frame))
    settings.output(output_path)
    settings.outputToMPlay(False)
    viewer.flipbook(viewer.curViewport(), settings)
    # The flipbook writes straight-alpha RGBA; where the viewport background is
    # transparent the alpha is ~0, so image viewers composite over white and the
    # screenshot reads blank. Force the saved PNG opaque (keep RGB, drop alpha)
    # so it's directly viewable. Best-effort — keep the raw capture if Qt is
    # unavailable or the flatten fails.
    try:
        try:
            from PySide6 import QtGui
        except ImportError:
            from PySide2 import QtGui
        img = QtGui.QImage(output_path)
        if not img.isNull() and img.hasAlphaChannel():
            img.convertToFormat(QtGui.QImage.Format_RGB32).save(output_path)
    except Exception:
        pass
    return {"filepath": output_path}


def set_current_network(path):
    """Set the current network path in the network editor."""
    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if not editor:
        raise RuntimeError("No network editor found")
    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")
    editor.setCurrentNode(node)
    return {"path": path}
