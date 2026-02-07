import hou
import json
import threading
import socket
import time
import tempfile
import traceback
import os
import sys
from PySide2 import QtWidgets, QtCore
import io
from contextlib import redirect_stdout, redirect_stderr
import base64 # Added for encoding

# --- Import render functions --- 
# try:
from .HoudiniMCPRender import *
# HMCPLib = HoudiniMCPRender # Alias for easier use
print("HoudiniMCPRender module loaded successfully.")
# except ImportError:
#     HMCPLib = None
#     print("Warning: HoudiniMCPRender.py not found or failed to import. Rendering tools will be unavailable.")
# ----------------------------------

# Info about the extension (optional metadata)
EXTENSION_NAME = "Houdini MCP"
EXTENSION_VERSION = (0, 1)
EXTENSION_DESCRIPTION = "Connect Houdini to Claude via MCP"

DEFAULT_PORT = int(os.environ.get("HOUDINIMCP_PORT", 9876))

class HoudiniMCPServer:
    def __init__(self, host='localhost', port=None):
        port = port if port is not None else DEFAULT_PORT
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b''  # Buffer for incomplete data
        self.timer = None

    def start(self):
        """Begin listening on the given port; sets up a QTimer to poll for data."""
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)
            
            # Create a timer in the main thread to process server events
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._process_server)
            self.timer.start(100)  # 100ms interval
            
            print(f"HoudiniMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()
            
    def stop(self):
        """Stop listening; close sockets and timers."""
        self.running = False
        if self.timer:
            self.timer.stop()
            self.timer = None
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
        self.socket = None
        self.client = None
        print("HoudiniMCP server stopped")

    def _process_server(self):
        """
        Timer callback to accept connections and process any incoming data.
        This runs in the main Houdini thread to avoid concurrency issues.
        """
        if not self.running:
            return
        
        try:
            # Accept new connections if we don't already have a client
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    self.client.setblocking(False)
                    print(f"Connected to client: {address}")
                except BlockingIOError:
                    pass  # No connection waiting
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
            
            # Process data from existing client
            if self.client:
                try:
                    data = self.client.recv(8192)
                    if data:
                        self.buffer += data
                        try:
                            # Attempt to parse JSON
                            command = json.loads(self.buffer.decode('utf-8'))
                            # If successful, clear the buffer and process
                            self.buffer = b''
                            response = self.execute_command(command)
                            response_json = json.dumps(response)
                            self.client.sendall(response_json.encode('utf-8'))
                        except json.JSONDecodeError:
                            # Incomplete data; keep appending to buffer
                            pass
                    else:
                        # Connection closed by client
                        print("Client disconnected")
                        self.client.close()
                        self.client = None
                        self.buffer = b''
                except BlockingIOError:
                    pass  # No data available
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    self.client.close()
                    self.client = None
                    self.buffer = b''

        except Exception as e:
            print(f"Server error: {str(e)}")

    # -------------------------------------------------------------------------
    # Command Handling
    # -------------------------------------------------------------------------
    
    # Commands that mutate the scene and should be wrapped in an undo group
    MUTATING_COMMANDS = {
        "create_node", "modify_node", "delete_node", "execute_code",
        "set_material", "connect_nodes", "disconnect_node_input",
        "set_node_flags", "save_scene", "load_scene", "set_expression",
        "set_frame", "layout_children", "set_node_color",
    }

    DANGEROUS_PATTERNS = [
        "hou.exit", "os.remove", "os.unlink", "shutil.rmtree",
        "subprocess", "os.system", "os.popen", "__import__",
    ]

    def execute_command(self, command):
        """Entry point for executing a JSON command from the client."""
        try:
            cmd_type = command.get("type", "")
            if cmd_type in self.MUTATING_COMMANDS:
                with hou.undos.group(f"MCP: {cmd_type}"):
                    return self._execute_command_internal(command)
            else:
                return self._execute_command_internal(command)
        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        """
        Internal dispatcher that looks up 'cmd_type' from the JSON,
        calls the relevant function, and returns a JSON-friendly dict.
        """
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Always-available handlers
        handlers = {
            "ping": self.ping,
            "get_scene_info": self.get_scene_info,
            "create_node": self.create_node,
            "modify_node": self.modify_node,
            "delete_node": self.delete_node,
            "get_node_info": self.get_node_info,
            "execute_code": self.execute_code,
            "set_material": self.set_material,
            "get_asset_lib_status": self.get_asset_lib_status,
            # Wiring & connections
            "connect_nodes": self.connect_nodes,
            "disconnect_node_input": self.disconnect_node_input,
            "set_node_flags": self.set_node_flags,
            # Scene management
            "save_scene": self.save_scene,
            "load_scene": self.load_scene,
            # Parameters & animation
            "set_expression": self.set_expression,
            "set_frame": self.set_frame,
            # Geometry
            "get_geo_summary": self.get_geo_summary,
            # Layout & organization
            "layout_children": self.layout_children,
            "set_node_color": self.set_node_color,
            # Error detection
            "find_error_nodes": self.find_error_nodes,
            # Render handlers
            "render_single_view": self.handle_render_single_view,
            "render_quad_view": self.handle_render_quad_view,
            "render_specific_camera": self.handle_render_specific_camera,
        }
        
        # If user has toggled asset library usage
        if getattr(hou.session, "houdinimcp_use_assetlib", False):
            asset_handlers = {
                "get_asset_categories": self.get_asset_categories,
                "search_assets": self.search_assets,
                "import_asset": self.import_asset,
            }
            handlers.update(asset_handlers)

        handler = handlers.get(cmd_type)
        if not handler:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}
        
        print(f"Executing handler for {cmd_type}")
        result = handler(**params)
        print(f"Handler execution complete for {cmd_type}")
        return {"status": "success", "result": result}

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    def ping(self):
        """Simple health check that returns server status."""
        return {
            "alive": True,
            "host": self.host,
            "port": self.port,
            "has_client": self.client is not None,
        }

    # -------------------------------------------------------------------------
    # Basic Info & Node Operations
    # -------------------------------------------------------------------------

    def get_asset_lib_status(self):
        """Checks if the user toggled asset library usage in hou.session."""
        use_assetlib = getattr(hou.session, "houdinimcp_use_assetlib", False)
        msg = ("Asset library usage is enabled." 
               if use_assetlib 
               else "Asset library usage is disabled.")
        return {"enabled": use_assetlib, "message": msg}

    def get_scene_info(self):
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
            
            # Collect limited node info from key contexts
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

    def create_node(self, node_type, parent_path="/obj", name=None, position=None, parameters=None):
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

    def modify_node(self, path, parameters=None, position=None, name=None):
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

    def delete_node(self, path):
        """Deletes a node from the scene."""
        node = hou.node(path)
        if not node:
            raise ValueError(f"Node not found: {path}")
        node_path = node.path()
        node_name = node.name()
        node.destroy()
        return {"deleted": node_path, "name": node_name}

    def get_node_info(self, path):
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

        # Limit to 20 parameters for brevity
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

        # Inputs
        for i, in_node in enumerate(node.inputs()):
            if in_node:
                node_info["inputs"].append({
                    "index": i,
                    "name": in_node.name(),
                    "path": in_node.path(),
                    "type": in_node.type().name()
                })

        # Outputs
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

    def execute_code(self, code, allow_dangerous=False):
        """Executes arbitrary Python code within Houdini."""
        if not allow_dangerous:
            for pattern in self.DANGEROUS_PATTERNS:
                if pattern in code:
                    raise ValueError(
                        f"Dangerous pattern detected: '{pattern}'. "
                        "Pass allow_dangerous=True to override."
                    )
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        try:
            namespace = {"hou": hou}
            # Capture stdout/stderr during exec
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, namespace)

            # Success case: return execution status and captured output
            return {
                "executed": True,
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }
        except Exception as e:
            # Failure case: print traceback to actual stderr for debugging in Houdini
            print("--- Houdini MCP: execute_code Error ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("--- End Error ---", file=sys.stderr)
            # Re-raise the exception so it's caught by execute_command
            # and reported back as a standard error message.
            raise Exception(f"Code execution error: {str(e)}")

    # -------------------------------------------------------------------------
    # set_material (now completed)
    # -------------------------------------------------------------------------
    def set_material(self, node_path, material_type="principledshader", name=None, parameters=None):
        """
        Creates or applies a material to an OBJ node. 
        For example, we can create a Principled Shader in /mat 
        and assign it to a geometry node or set the 'shop_materialpath'.
        """
        try:
            target_node = hou.node(node_path)
            if not target_node:
                raise ValueError(f"Node not found: {node_path}")
            
            # Verify it's an OBJ node (i.e., category Object)
            if target_node.type().category().name() != "Object":
                raise ValueError(
                    f"Node {node_path} is not an OBJ-level node and cannot accept direct materials."
                )

            # Attempt to create/find a material in /mat (or /shop)
            mat_context = hou.node("/mat")
            if not mat_context:
                # Fallback: try /shop if /mat doesn't exist
                mat_context = hou.node("/shop")
                if not mat_context:
                    raise RuntimeError("No /mat or /shop context found to create materials.")

            mat_name = name or (f"{material_type}_auto")
            mat_node = mat_context.node(mat_name)
            if not mat_node:
                # Create a new material node
                mat_node = mat_context.createNode(material_type, mat_name)

            # Apply any parameter overrides
            if parameters:
                for k, v in parameters.items():
                    p = mat_node.parm(k)
                    if p:
                        p.set(v)

            # Now assign this material to the OBJ node
            # Typically, you either set a "shop_materialpath" parameter 
            # or inside the geometry, you create a Material SOP.
            mat_parm = target_node.parm("shop_materialpath")
            if mat_parm:
                mat_parm.set(mat_node.path())
            else:
                # If there's a geometry node inside, we might make or update a Material SOP
                geo_sop = target_node.node("geometry")
                if not geo_sop:
                    raise RuntimeError("No 'geometry' node found inside OBJ to apply material to.")
                
                material_sop = geo_sop.node("material1")
                if not material_sop:
                    material_sop = geo_sop.createNode("material", "material1")
                    # Hook it up to the chain
                    # For a brand-new geometry node, there's often a 'file1' SOP or similar
                    first_sop = None
                    for c in geo_sop.children():
                        if c.isDisplayFlagSet():
                            first_sop = c
                            break
                    if first_sop:
                        material_sop.setFirstInput(first_sop)
                    material_sop.setDisplayFlag(True)
                    material_sop.setRenderFlag(True)

                # The Material SOP typically has shop_materialpath1, shop_materialpath2, etc.
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

    # -------------------------------------------------------------------------
    # Wiring & Connections
    # -------------------------------------------------------------------------

    def connect_nodes(self, src_path, dst_path, dst_input_index=0, src_output_index=0):
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

    def disconnect_node_input(self, node_path, input_index=0):
        """Disconnect a specific input on a node."""
        node = hou.node(node_path)
        if not node:
            raise ValueError(f"Node not found: {node_path}")
        node.setInput(input_index, None)
        return {"disconnected": True, "node": node.path(), "input_index": input_index}

    def set_node_flags(self, node_path, display=None, render=None, bypass=None):
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

    # -------------------------------------------------------------------------
    # Scene Management
    # -------------------------------------------------------------------------

    def save_scene(self, file_path=None):
        """Save the current scene, optionally to a new path."""
        if file_path:
            hou.hipFile.save(file_path)
        else:
            hou.hipFile.save()
        return {"saved": True, "file": hou.hipFile.name()}

    def load_scene(self, file_path):
        """Load a .hip file."""
        hou.hipFile.load(file_path)
        return {"loaded": True, "file": hou.hipFile.name()}

    # -------------------------------------------------------------------------
    # Parameters & Animation
    # -------------------------------------------------------------------------

    def set_expression(self, node_path, parm_name, expression, language="hscript"):
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

    def set_frame(self, frame):
        """Set the current frame in Houdini's playbar."""
        hou.setFrame(frame)
        return {"frame": frame}

    # -------------------------------------------------------------------------
    # Geometry
    # -------------------------------------------------------------------------

    def get_geo_summary(self, node_path):
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

    # -------------------------------------------------------------------------
    # Layout & Organization
    # -------------------------------------------------------------------------

    def layout_children(self, node_path="/obj"):
        """Auto-layout child nodes."""
        node = hou.node(node_path)
        if not node:
            raise ValueError(f"Node not found: {node_path}")
        node.layoutChildren()
        return {"path": node.path(), "laid_out": True}

    def set_node_color(self, node_path, color):
        """Set a node's color as [r, g, b] (0-1 range)."""
        node = hou.node(node_path)
        if not node:
            raise ValueError(f"Node not found: {node_path}")
        if len(color) != 3:
            raise ValueError(f"Color must be [r, g, b], got: {color}")
        node.setColor(hou.Color(color[0], color[1], color[2]))
        return {"path": node.path(), "color": color}

    # -------------------------------------------------------------------------
    # Error Detection
    # -------------------------------------------------------------------------

    def find_error_nodes(self, root_path="/obj"):
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

    # -------------------------------------------------------------------------
    # Render Command Handlers (using HoudiniMCPRender.py)
    # -------------------------------------------------------------------------
    # def _check_render_lib(self):
    #     """Helper to check if the render library was imported."""
    #     if HMCPLib is None:
    #         raise RuntimeError("HoudiniMCPRender library not available. Cannot execute render commands.")

    def _process_rendered_image(self, filepath, camera_path=None, view_name=None):
        """
        Helper to read, encode, get metadata, and clean up a rendered image file.
        Returns a dictionary compatible with the expected tool output.
        """
        if not filepath or not os.path.exists(filepath):
            return {"status": "error", "message": f"Rendered file not found: {filepath}", "origin": "_process_rendered_image"}
        

        # Determine format from extension
        _, ext = os.path.splitext(filepath)
        format = ext[1:].lower() if ext else 'unknown'

        # Get resolution from the camera if possible
        resolution = [0, 0]
        if camera_path:
                cam_node = hou.node(camera_path)
                if cam_node and cam_node.parm("resx") and cam_node.parm("resy"):
                    resolution = [cam_node.parm("resx").eval(), cam_node.parm("resy").eval()]
                else: # Fallback for camera not found or no res parms
                    print(f"Warning: Could not get resolution from camera {camera_path}")
                    # Could try to get from image header, but complex. Returning 0,0
                    pass
        
        # Read file and encode
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        
        result_data = {
            "status": "success",
            "format": format,
            "resolution": resolution, 
            "image_base64": encoded_string,
            "filepath_on_server": filepath # For debugging, maybe remove later
        }
        if view_name:
                result_data["view_name"] = view_name
                
        return result_data

        # except Exception as e:
        #     error_message = f"Failed to process rendered image {filepath}: {str(e)}"
        #     print(error_message)
        #     traceback.print_exc()
        #     return {"status": "error", "message": error_message, "origin": "_process_rendered_image"}
        # finally:
        #     # Clean up the temporary file
        #     if os.path.exists(filepath):
        #         try:
        #             os.remove(filepath)
        #             print(f"Cleaned up temporary render file: {filepath}")
        #         except Exception as cleanup_e:
        #             print(f"Warning: Failed to clean up temporary render file {filepath}: {cleanup_e}")

    def handle_render_single_view(self, orthographic=False, rotation=(0, 90, 0), render_path=None, render_engine="opengl", karma_engine="cpu"):
        """Handles the 'render_single_view' command."""
        # self._check_render_lib()
        
        # Use a temporary directory for the render output
        if not render_path:
            render_path = tempfile.gettempdir()
            
        try:
            # Ensure rotation is a tuple
            if isinstance(rotation, list): rotation = tuple(rotation)
            
            print(f"Calling HoudiniMCPRender.render_single_view with rotation={rotation}, ortho={orthographic}, engine={render_engine}...")
            filepath = render_single_view(
                orthographic=orthographic,
                rotation=rotation,
                render_path=render_path,
                render_engine=render_engine,
                karma_engine=karma_engine
            )
            print(f"render_single_view returned filepath: {filepath}")

            # Process the result
            # Determine camera path used (it's always /obj/MCP_CAMERA for this func)
            camera_path = "/obj/MCP_CAMERA"
            return self._process_rendered_image(filepath, camera_path)

        except Exception as e:
            error_message = f"Render Single View Failed: {str(e)}"
            print(error_message)
            traceback.print_exc()
            return {"status": "error", "message": error_message, "origin": "handle_render_single_view"}

    def handle_render_quad_view(self, orthographic=True, render_path=None, render_engine="opengl", karma_engine="cpu"):
        """Handles the 'render_quad_view' command."""
        # self._check_render_lib()
        
        if not render_path:
            render_path = tempfile.gettempdir()

        try:
            print(f"Calling HoudiniMCPRender.render_quad_view with ortho={orthographic}, engine={render_engine}...")
            filepaths = render_quad_view(
                orthographic=orthographic,
                render_path=render_path,
                render_engine=render_engine,
                karma_engine=karma_engine
            )
            print(f"render_quad_view returned filepaths: {filepaths}")

            # Process each resulting file
            results = []
            camera_path = "/obj/MCP_CAMERA" # Same camera is reused and modified
            for fp in filepaths:
                # Extract view name from filename if possible (e.g., MCP_OGL_RENDER_front_ortho.jpg -> front)
                view_name = None
                try:
                     filename = os.path.basename(fp)
                     parts = filename.split('_')
                     if len(parts) > 2: # Look for the part after engine/render type
                         view_name = parts[2] 
                except:
                     pass # Ignore errors extracting view name
                     
                results.append(self._process_rendered_image(fp, camera_path, view_name))
                
            # Return the list of results
            return {"status": "success", "results": results}

        except Exception as e:
            error_message = f"Render Quad View Failed: {str(e)}"
            print(error_message)
            traceback.print_exc()
            return {"status": "error", "message": error_message, "origin": "handle_render_quad_view"}

    def handle_render_specific_camera(self, camera_path, render_path=None, render_engine="opengl", karma_engine="cpu"):
        """Handles the 'render_specific_camera' command."""
        # self._check_render_lib()
        
        if not render_path:
            render_path = tempfile.gettempdir()
            
        if not camera_path or not hou.node(camera_path):
             return {"status": "error", "message": f"Camera path '{camera_path}' is invalid or node not found.", "origin": "handle_render_specific_camera"}

        try:
            print(f"Calling HoudiniMCPRender.render_specific_camera for camera={camera_path}, engine={render_engine}...")
            filepath = render_specific_camera(
                camera_path=camera_path,
                render_path=render_path,
                render_engine=render_engine,
                karma_engine=karma_engine
            )
            print(f"render_specific_camera returned filepath: {filepath}")

            # Process the result, using the provided camera_path
            return self._process_rendered_image(filepath, camera_path)

        except Exception as e:
            error_message = f"Render Specific Camera Failed: {str(e)}"
            print(error_message)
            traceback.print_exc()
            return {"status": "error", "message": error_message, "origin": "handle_render_specific_camera"}

    # -------------------------------------------------------------------------
    # Existing Placeholder asset library methods
    # -------------------------------------------------------------------------
    def get_asset_categories(self):
        """Placeholder for an asset library feature (e.g., Poly Haven)."""
        return {"error": "get_asset_categories not implemented"}

    def search_assets(self):
        """Placeholder for asset search logic."""
        return {"error": "search_assets not implemented"}

    def import_asset(self):
        """Placeholder for asset import logic."""
        return {"error": "import_asset not implemented"}
