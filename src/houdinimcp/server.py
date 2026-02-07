import hou
import json
import threading
import socket
import time
import requests
import tempfile
import traceback
import os
import shutil
import sys
from PySide2 import QtWidgets, QtCore
import io
from contextlib import redirect_stdout, redirect_stderr
import base64 # Added for encoding

# Imports for OPUS import
import zipfile
from urllib.parse import urlparse
import uuid # For unique temp dirs and file processing

# --- NEW: Import render functions --- 
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
        "set_material", "import_opus_url",
    }

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
            "import_opus_url": self.handle_import_opus_url,
            # Add new render handlers
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

    def execute_code(self, code):
        """Executes arbitrary Python code within Houdini."""
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
    # NEW OPUS Import Handler and Helpers
    # -------------------------------------------------------------------------
    
    def _download_file(self, url, dest_folder):
        """
        Download from 'url' to local 'dest_folder', returning local filepath.
        Helper for import_opus_url.
        """
        if not url:
            raise ValueError("Download URL cannot be empty.")
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder, exist_ok=True)
    
        # Generate filename, ensure it ends with .zip if possible
        try:
            path_part = urlparse(url).path
            filename = os.path.basename(path_part) if path_part else f"{uuid.uuid4()}.zip"
            if not filename.lower().endswith('.zip'):
                filename += ".zip"
        except Exception:
             filename = f"{uuid.uuid4()}.zip" # Fallback
             
        local_path = os.path.join(dest_folder, filename)
        # Ensure forward slashes
        local_path = local_path.replace('\\', '/')
        print(f"  Downloading {url} => {local_path}")
    
        try:
            # Use requests (already imported) for downloading
            resp = requests.get(url, stream=True, timeout=60) # Add timeout
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"  Download complete: {local_path}")
            return local_path
        except requests.exceptions.RequestException as e:
             print(f"  Download failed: {str(e)}")
             # Clean up potentially incomplete file
             if os.path.exists(local_path):
                  try: os.remove(local_path)
                  except: pass
             raise ConnectionError(f"Failed to download file: {str(e)}") from e

    def _unzip_file(self, zip_path, dest_folder):
        """
        Unzip 'zip_path' into 'dest_folder'. Return list of extracted file paths.
        Helper for import_opus_url.
        """
        extracted_files = []
        print(f"  Unzipping {zip_path} => {dest_folder}")
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(dest_folder)
                # Ensure forward slashes in extracted paths
                extracted_files = [os.path.join(dest_folder, p).replace('\\', '/') for p in z.namelist()]
            print(f"  Unzip complete. Extracted {len(extracted_files)} files.")
            return extracted_files
        except zipfile.BadZipFile as e:
             print(f"  Unzip failed: Bad zip file - {str(e)}")
             raise ValueError(f"Downloaded file is not a valid zip file: {str(e)}") from e
        except Exception as e:
             print(f"  Unzip failed: {str(e)}")
             raise IOError(f"Failed to unzip file: {str(e)}") from e

    def handle_import_opus_url(self, url, node_name="opus_import"):
        """
        Downloads a ZIP file from URL, unzips it, finds a USD file,
        and imports it into a new subnet in Houdini.
        """
        temp_dir = None
        try:
            # Create a unique temporary directory for download and extraction
            temp_dir = tempfile.mkdtemp(prefix="houdini_opus_import_")
            print(f"Created temporary directory: {temp_dir}")

            # Download the zip file
            zip_filepath = self._download_file(url, temp_dir)
            if not zip_filepath or not os.path.exists(zip_filepath):
                 raise FileNotFoundError("Download failed or file not found.")

            # Unzip the file
            extract_dir = os.path.join(temp_dir, "extracted")
            extracted_files = self._unzip_file(zip_filepath, extract_dir)
            if not extracted_files:
                 raise FileNotFoundError("Unzip failed or zip file was empty.")

            # Find the primary USD file (e.g., .usd, .usda, .usdc)
            # Also check for GLTF/GLB as the zip name was gltf.zip
            import_file = None
            possible_usd_extensions = (".usd", ".usda", ".usdc")
            possible_gltf_extensions = (".gltf", ".glb")
            
            # Prioritize USD files
            for f in extracted_files:
                if f.lower().endswith(possible_usd_extensions):
                    import_file = f
                    print(f"Found USD file: {import_file}")
                    break
            
            # If no USD found, check for GLTF/GLB
            if not import_file:
                for f in extracted_files:
                     if f.lower().endswith(possible_gltf_extensions):
                        import_file = f
                        print(f"Found GLTF/GLB file: {import_file}")
                        break # Take the first match
            
            if not import_file:
                 raise FileNotFoundError(f"No USD ({possible_usd_extensions}) or GLTF/GLB ({possible_gltf_extensions}) file found in the extracted contents.")

            # --- Import into Houdini using gltf_hierarchy node directly in /obj ---
            obj_context = hou.node("/obj")
            if not obj_context:
                 raise RuntimeError("Cannot find /obj context in Houdini.")
            
            # Create a gltf_hierarchy node directly in /obj
            node_actual_name = node_name or "opus_import"
            gltf_node = obj_context.createNode("gltf_hierarchy", node_actual_name)
            if not gltf_node:
                 raise RuntimeError(f"Failed to create gltf_hierarchy node '{node_actual_name}' in /obj.")
            print(f"Created gltf_hierarchy node: {gltf_node.path()}")

            # Set the filename parameter
            print(f"Setting filename on {gltf_node.path()} to {import_file}")
            try:
                 # Parameter name might vary slightly, check common names
                 param_name = "filename"
                 if not gltf_node.parm(param_name):
                      param_name = "file"
                      if not gltf_node.parm(param_name):
                           raise RuntimeError(f"Could not find filename parameter ('filename' or 'file') on {gltf_node.path()}")
                           
                 gltf_node.parm(param_name).set(import_file)
                 print(f"Set parameter '{param_name}' successfully.")
            except hou.Error as parm_e:
                 print(f"Error setting filename parameter on gltf_hierarchy node: {parm_e}")
                 raise RuntimeError(f"Failed to set filename on gltf_hierarchy node: {parm_e}") from parm_e

            # Press the Build Scene button
            build_scene_parm = gltf_node.parm("buildscene")
            if build_scene_parm:
                 print(f"Pressing 'Build Scene' button on {gltf_node.path()}")
                 build_scene_parm.pressButton()
            else:
                 print(f"Warning: Could not find 'buildscene' parameter on {gltf_node.path()}. Scene might not be built automatically.")

            # Layout nodes in /obj (optional, might be useful)
            obj_context.layoutChildren()
            
            # Return the path to the gltf_hierarchy node
            return {"status": "success", "imported_node_path": gltf_node.path(), "imported_file": import_file}

        except Exception as e:
            error_message = f"OPUS Import Failed: {str(e)}"
            print(error_message)
            traceback.print_exc() # Print full traceback to Houdini console
            # Re-raise to be caught by execute_command and sent back as standard error
            raise Exception(error_message) from e

        finally:
            # --- Cleanup --- 
            # Only delete the downloaded zip file, keep the extracted contents
            # as the gltf_hierarchy SOP needs to reference them.
            if zip_filepath and os.path.exists(zip_filepath):
                try:
                    os.remove(zip_filepath)
                    print(f"Cleaned up temporary zip file: {zip_filepath}")
                except Exception as cleanup_zip_e:
                    print(f"Warning: Failed to clean up temporary zip file {zip_filepath}: {cleanup_zip_e}")
            
            # Keep the temp_dir itself and the extracted folder for now
            # If keeping the temp dir is problematic, we could copy the needed files elsewhere
            # before deleting the temp_dir.
            # if temp_dir and os.path.exists(temp_dir):
            #     try:
            #         shutil.rmtree(temp_dir)
            #         print(f"Cleaned up temporary directory: {temp_dir}")
            #     except Exception as cleanup_e:
            #         print(f"Warning: Failed to clean up temporary directory {temp_dir}: {cleanup_e}")

    # -------------------------------------------------------------------------
    # NEW Render Command Handlers (using HoudiniMCPRender.py)
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
