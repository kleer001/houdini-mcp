#!/usr/bin/env python
"""
houdini_mcp_server.py

This is the "bridge" or "driver" script that Claude will run via `uv run`.
It uses the MCP library (fastmcp) to communicate with Claude over stdio,
and relays each command to the local Houdini plugin on port 9876.
"""
import sys
import os
import site

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Add the virtual environment's site-packages to Python's path
# Check both Windows (Lib/site-packages) and Unix (lib/python*/site-packages) layouts
import glob as _glob
_venv_candidates = [
    os.path.join(script_dir, '.venv', 'Lib', 'site-packages'),  # Windows
    *_glob.glob(os.path.join(script_dir, '.venv', 'lib', 'python*', 'site-packages')),  # Unix
]
_venv_found = False
for venv_site_packages in _venv_candidates:
    if os.path.exists(venv_site_packages):
        sys.path.insert(0, venv_site_packages)
        print(f"Added {venv_site_packages} to sys.path", file=sys.stderr)
        _venv_found = True
        break
if not _venv_found:
    print(f"Warning: Virtual environment site-packages not found in {script_dir}/.venv/", file=sys.stderr)


# For debugging
print("Python path:", sys.path, file=sys.stderr)
import json
import socket
import logging
import tempfile
from dataclasses import dataclass
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio

# --- OPUS Imports and Setup ---
import requests
from dotenv import load_dotenv
from urllib.parse import urljoin # To construct RapidAPI URLs
try:
    from langchain.output_parsers import ResponseSchema, StructuredOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("Warning: Langchain not found. opus_get_model_params_schema tool will be limited.", file=sys.stderr)

# Load environment variables from urls.env located in the script's directory
dotenv_path = os.path.join(script_dir, 'urls.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    print(f"Loaded environment variables from {dotenv_path}", file=sys.stderr)
else:
    print(f"Warning: urls.env not found at {dotenv_path}", file=sys.stderr)

# --- Use RapidAPI variables --- 
RAPIDAPI_HOST_URL = os.getenv("RAPIDAPI_HOST_URL") # e.g., https://opus5.p.rapidapi.com/
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST") # e.g., opus5.p.rapidapi.com
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Set paths for OPUS API endpoints relative to the RapidAPI host URL
GET_ATTRIBUTES_PATH = "/get_attributes_with_name" 
CREATE_BATCH_PATH = "/create_opus_batch_component" # Use batch endpoint
CREATE_COMPONENT_PATH = "/create_opus_component" # Keep old path if needed elsewhere, or remove
VARIATE_PATH = "/variate_opus_result"
GET_JOB_RESULT_PATH = "/get_opus_job_result"

TIMEOUT = 15 # seconds
HOUDINI_PORT = int(os.getenv("HOUDINIMCP_PORT", 9876))

if not RAPIDAPI_HOST_URL or not RAPIDAPI_HOST or not RAPIDAPI_KEY:
    print("Error: RAPIDAPI_HOST_URL, RAPIDAPI_HOST, and RAPIDAPI_KEY environment variables must be set in urls.env", file=sys.stderr)
else:
    # Construct full URLs
    GET_ATTRIBUTES_URL = urljoin(RAPIDAPI_HOST_URL, GET_ATTRIBUTES_PATH)
#    CREATE_BATCH_URL = urljoin(RAPIDAPI_HOST_URL, CREATE_BATCH_PATH)
    CREATE_COMPONENT_URL = urljoin(RAPIDAPI_HOST_URL, CREATE_COMPONENT_PATH)
    VARIATE_URL = urljoin(RAPIDAPI_HOST_URL, VARIATE_PATH)
    GET_JOB_RESULT_URL = urljoin(RAPIDAPI_HOST_URL, GET_JOB_RESULT_PATH)
    # Optionally warn if old OPUS_API is still set

# --- End OPUS Setup ---


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HoudiniMCP_StdioServer")

# --- Minimal api.utils.fix_rgb replication ---
# Assume it takes a list/tuple and returns [r, g, b] if valid, else None
def fix_rgb(color_val):
    if isinstance(color_val, (list, tuple)) and len(color_val) == 3:
        try:
            # Ensure they are numbers (int or float) and within typical 0-255 or 0-1 range
            # For simplicity, just check if they are numbers. API might expect 0-255 ints.
            rgb = [float(c) for c in color_val]
            # Basic check - could add range validation 0-255 or 0-1 if needed
            return rgb # Returning as floats for now
        except (ValueError, TypeError):
            return None
    return None
# --- End utils replication ---


# --- OPUS Helper Functions (Updated for RapidAPI) ---
def get_all_component_names() -> List[str]:
    # result = ["Sofa", "Chair", "Table", "CoffeeTable"] # Original subset
    result = [
        "Sofa", "Chair", "Table", "CoffeeTable",
         "Library", "StreetBench", "StreetLamp", "MailboxStandalone",
         "AntennaStandalone", "ParkingMeterStandalone", "AirConditionerStandalone",
         "BasketballHoop", "BusStop", "FloorLamp", "Bed", "TvUnit",
         "Sewer", "GarageDoorStandalone",
    ] # User provided list
    return result

def get_struct_params(struct: str) -> tuple[bool, dict]:
    if not RAPIDAPI_HOST_URL: return False, {"error": "RAPIDAPI_HOST_URL not configured"}
    url = GET_ATTRIBUTES_URL
    payload = {} # GET request, params in URL
    params = { "name": struct }
    headers = {
        'x-rapidapi-host': RAPIDAPI_HOST,
        'x-rapidapi-key': RAPIDAPI_KEY
    }
    try:
        response = requests.request("GET", url, headers=headers, params=params, data=payload, timeout=TIMEOUT)
        if str(response.status_code).startswith("2"):
            r = response.json()
            struct_result = r.get(struct) # Check if response structure changed
            if struct_result:
                return True, struct_result
            elif isinstance(r, dict) and not struct_result: # Maybe the top-level key is gone?
                 if struct in r.get("result", {}): # Check common patterns
                     return True, r["result"]
                 else:
                     # Fallback: return the whole response if structure unclear but success
                     logger.warning(f"Structure '{struct}' key not found directly in RapidAPI response, returning full JSON: {r}")
                     return True, r 
            else:
                return False, {"error": f"Structure '{struct}' not found in RapidAPI response: {r}"}
        else:
            return False, {"error": f"RapidAPI Error {response.status_code}: {response.text}"}
    except requests.exceptions.RequestException as e:
        return False, {"error": f"RapidAPI request failed: {str(e)}"}

def format_params(opus_response: dict) -> dict:
    formatted = {}
    # Adjust based on actual RapidAPI response structure if needed
    # Assuming original structure: { "StructureName": { "assets": [...] } }
    # Or maybe it's now just { "assets": [...] } or similar?
    # This needs verification against actual RapidAPI output.
    
    # Attempt 1: Original structure
    for asset_key, asset_data in opus_response.items():
        if isinstance(asset_data, dict) and "assets" in asset_data:
             for element in asset_data.get("assets", []):
                name = element.get("name")
                params = element.get("parameters", [])
                if not name: continue
                for p in params:
                    pname = p.get("name")
                    prange = p.get("range")
                    ptype = p.get("type")
                    if pname and prange is not None and ptype is not None:
                         formatted[f"{name}/{pname}"] = (prange, ptype)
    
    # Attempt 2: If assets are directly under top level (heuristic)
    if not formatted and "assets" in opus_response and isinstance(opus_response["assets"], list):
        logger.warning("format_params: Using fallback structure parsing (assets at top level).")
        for element in opus_response.get("assets", []):
            name = element.get("name")
            params = element.get("parameters", [])
            if not name: continue
            for p in params:
                pname = p.get("name")
                prange = p.get("range")
                ptype = p.get("type")
                if pname and prange is not None and ptype is not None:
                        formatted[f"{name}/{pname}"] = (prange, ptype)
                        
    # Attempt 3: If params are directly under top level (another heuristic)
    elif not formatted and "parameters" in opus_response and isinstance(opus_response["parameters"], list):
        logger.warning("format_params: Using fallback structure parsing (parameters at top level).")
        # How to get the asset name here? Assume it's part of the param name?
        # This path is less likely or needs more info.
        pass # Add logic if this structure is encountered

    if not formatted:
         logger.warning(f"format_params: Could not extract parameters from response: {opus_response}")
         
    return formatted

def get_color_params(component_name: str, opus_asset_keys: List[str]) -> dict:
    result = {}
    # Component level color
    result.setdefault(
        f"{component_name}/color_rgb",
        (
            "List[float]", # Assuming List[float] based on fix_rgb output
            f"Valid RGB color [R, G, B] (values likely 0-1 or 0-255, check API docs). Use if the user sets the entire color of the {component_name} or provided a single color without specifying a part."
        ),
    )
    # Asset level colors
    for asset in opus_asset_keys:
        result.setdefault(
            f"{asset}/color_rgb",
            (
                "List[float]", # Assuming List[float]
                f"Valid RGB color [R, G, B] for the {asset} part. Use if user set the color of this specific part of the {component_name}."
            ),
        )
    return result

def get_param_json(param_json: dict, color_params: dict) -> str:
    if not LANGCHAIN_AVAILABLE:
        # Fallback: simple JSON representation if Langchain is missing
        combined = {}
        for key, value in param_json.items():
            combined[key] = {"range": value[0], "type": value[1], "description": f"Allowed range: {value[0]}"}
        for key, value in color_params.items():
            combined[key] = {"type": value[0], "description": value[1]}
        return json.dumps(combined, indent=2)

    # Langchain way
    response_schemas = []
    for key, value in param_json.items():
        response_schemas.append(
            ResponseSchema(name=key, description=f"Allowed range: {value[0]}", type=str(value[1])) # Ensure type is string
        )
    for key, value in color_params.items():
        response_schemas.append(
            ResponseSchema(name=key, description=str(value[1]), type=str(value[0])) # Ensure type is string
        )
    try:
        output_parser = StructuredOutputParser.from_response_schemas(response_schemas)
        prompt_var = output_parser.get_format_instructions(only_json=True)
        return prompt_var
    except Exception as e:
        logger.error(f"Langchain StructuredOutputParser failed: {e}")
        # Fallback if Langchain parsing fails
        combined = {key: {"range": value[0], "type": value[1]} for key, value in param_json.items()}
        combined.update({key: {"type": value[0], "description": value[1]} for key, value in color_params.items()})
        return json.dumps(combined, indent=2)


def get_formatted_opus_params(structure: str) -> dict:
    # this is the main function to be called, copy of lambda function
    f, structure_json = get_struct_params(structure)
    if f:
        formatted_params = format_params(structure_json)
        # Extract keys carefully, might need adjustment based on format_params heuristics
        asset_keys = list(structure_json.keys()) if isinstance(structure_json, dict) else [] 
        if not asset_keys and "assets" in structure_json and isinstance(structure_json["assets"], list):
             asset_keys = [a.get("name") for a in structure_json["assets"] if a.get("name")]
             
        color_params = get_color_params(structure, asset_keys) 
        schema_str = get_param_json(formatted_params, color_params)
        # Try to parse back to JSON for consistent return type
        try:
            schema_json = json.loads(schema_str)
            return {"statusCode": 200, "result": schema_json}
        except json.JSONDecodeError:
             # If get_param_json returned non-JSON string (e.g. Langchain format instructions)
             return {"statusCode": 200, "result_format_instructions": schema_str}
    else:
        # structure_json should contain the error from get_struct_params
        status_code = 500 # Default error code
        if isinstance(structure_json, dict) and "error" in structure_json:
             if "RapidAPI Error 4" in structure_json["error"]: #粗略检查 4xx 错误
                  status_code = 400 # Or map specific codes if needed
             elif "RapidAPI Error 5" in structure_json["error"]:
                  status_code = 503 # Service unavailable or internal error
                  
        return {"statusCode": status_code, "error": structure_json.get("error", "Unknown error retrieving parameters")} 

def check_rgbs(structure: str, params: dict) -> dict:
    clean_params = {}
    if not isinstance(params, dict): return {} # Guard against non-dict input
    for k, v in params.items():
        if "color_rgb" in k:
            # Handle simplified key case from get_color_params
            if k == f"{structure}/color_rgb":
                valid_rgb = fix_rgb(v)
                if valid_rgb is not None:
                    clean_params[k] = valid_rgb # Use the potentially simplified key
            elif "/" in k: # Assume format like "asset/color_rgb"
                 valid_rgb = fix_rgb(v)
                 if valid_rgb is not None:
                    clean_params[k] = valid_rgb
            # Optional: Add handling for _layout/color_rgb if needed? User code had it commented.
            # elif "_layout/color_rgb" in k:
            #     k_fixed = f"{structure}/color_rgb" # Map it?
            #     valid_rgb = fix_rgb(v)
            #     if valid_rgb is not None:
            #         clean_params[k_fixed] = valid_rgb
        else:
            clean_params[k] = v
    return clean_params

def create_opus_batch(component_type: str, params: dict, count: int = 1) -> tuple[bool, dict]:
    if not RAPIDAPI_HOST_URL: return False, {"error": "RAPIDAPI_HOST_URL not configured"}
    url = CREATE_COMPONENT_URL # Use the correct RapidAPI URL
    p = {
        "name": component_type,
        "parameters": params,
        "extensions": ["gltf"], # Hardcoded GLTF for now
    #    "count": count, # Add count parameter
        # Add texture_resolution? Required by user example?
        # "texture_resolution": "1024", # Assuming default, adjust if needed
    }
    payload = json.dumps(p)
    headers = {
        'Content-Type': 'application/json',
        'x-rapidapi-host': RAPIDAPI_HOST,
        'x-rapidapi-key': RAPIDAPI_KEY
    }
    try:
        response = requests.request("POST", url, headers=headers, data=payload, timeout=TIMEOUT)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        r = response.json()
        # Check response structure for batch_id (might be different from old API)
        batch_id = r.get("batch_job_id") or r.get("batch_id") or r.get("job_id") # Check common keys
        if batch_id:
            return True, r # Return the full response which contains the ID
        else:
             logger.error(f"RapidAPI batch creation success but no batch_id found in response: {r}")
             return False, {"error": "API succeeded but batch_id missing in response."}
    except requests.exceptions.HTTPError as e:
        logger.error(f"RapidAPI Error {e.response.status_code} creating batch: {e.response.text}")
        try:
             # Try to return the JSON error body if possible
             error_json = e.response.json()
             error_json["status_code"] = e.response.status_code # Add status code for later use
             return False, error_json
        except json.JSONDecodeError:
             return False, {"error": f"RapidAPI Error {e.response.status_code}: {e.response.text}", "status_code": e.response.status_code}
    except requests.exceptions.RequestException as e:
        logger.error(f"RapidAPI request failed creating batch: {str(e)}")
        return False, {"error": f"RapidAPI request failed: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode RapidAPI response: {str(e)}")
        return False, {"error": "Failed to decode RapidAPI response."}


def create_opus_component(structure: str, params: dict, count: int = 1) -> dict:
    # Ensure params is a dict
    if not isinstance(params, dict):
         return {"statusCode": 400, "error": "Parameters must be a valid JSON object (dict)."}
         
    clean_params = check_rgbs(structure, params)
    status, result_json = create_opus_batch(structure, clean_params, count)
    if status:
        # Extract batch ID (key might vary)
        batch_id = result_json.get("batch_job_id") or result_json.get("batch_id") or result_json.get("job_id")
        if batch_id:
             logger.info(f"OPUS (RapidAPI) batch job created: {batch_id}")
             # Return a consistent success structure
             return {"statusCode": 200, "batch_id": batch_id, "raw_response": result_json}
        else:
             # This case should be handled inside create_opus_batch now
             logger.error(f"API success but no batch_job_id found in response: {result_json}")
             return {"statusCode": 500, "error": "API succeeded but batch_id missing."}
    else:
        # result_json already contains the error from create_opus_batch
        return {"statusCode": result_json.pop("status_code", 500), **result_json} # Use status_code if available


def variate_opus_result(result_id: str, count: int = 12) -> dict:
    if not RAPIDAPI_HOST_URL: return {"statusCode": 500, "error": "RAPIDAPI_HOST_URL not configured"}
    url = VARIATE_URL # Use RapidAPI URL
    p = {
         "base_job_uid": result_id, # Parameter name might change, check RapidAPI docs
         "count": count
         # Any other params needed for variation?
    }
    payload = json.dumps(p)
    headers = {
        'Content-Type': 'application/json',
        'x-rapidapi-host': RAPIDAPI_HOST,
        'x-rapidapi-key': RAPIDAPI_KEY
    }
    try:
        response = requests.request("POST", url, headers=headers, data=payload, timeout=TIMEOUT)
        response.raise_for_status()
        result_json = response.json()
        # Extract batch_id (key might vary)
        batch_id = result_json.get("batch_job_id") or result_json.get("batch_id") or result_json.get("job_id")
        if batch_id:
            logger.info(f"OPUS (RapidAPI) variation batch job created: {batch_id}")
            return {"statusCode": 200, "batch_id": batch_id, "raw_response": result_json}
        else:
            logger.error(f"RapidAPI variation success but no batch_id found: {result_json}")
            return {"statusCode": 500, "error": "API variation succeeded but batch_id missing."}
    except requests.exceptions.HTTPError as e:
        logger.error(f"RapidAPI Error {e.response.status_code} creating variation: {e.response.text}")
        try:
             error_json = e.response.json()
             return {"statusCode": e.response.status_code, "error": error_json}
        except json.JSONDecodeError:
             return {"statusCode": e.response.status_code, "error": e.response.text}
    except requests.exceptions.RequestException as e:
        logger.error(f"RapidAPI request failed creating variation: {str(e)}")
        return {"statusCode": 500, "error": f"Request failed: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode variation RapidAPI response: {str(e)}")
        return {"statusCode": 500, "error": "Failed to decode variation RapidAPI response."}

# --- End OPUS Helper Functions ---


@dataclass
class HoudiniConnection:
    host: str
    port: int
    sock: socket.socket = None
    connected_since: float = None
    last_command_at: float = None
    command_count: int = 0

    def connect(self) -> bool:
        """Connect to the Houdini plugin (which is listening on self.host:self.port)."""
        if self.sock is not None:
            return True  # Already connected
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.connected_since = asyncio.get_event_loop().time()
            logger.info(f"Connected to Houdini at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Houdini: {str(e)}")
            self.sock = None
            self.connected_since = None
            return False

    def disconnect(self):
        """Close socket if open."""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Houdini: {str(e)}")
            self.sock = None
            self.connected_since = None

    def get_status(self) -> dict:
        """Return current connection status info."""
        return {
            "connected": self.sock is not None,
            "host": self.host,
            "port": self.port,
            "connected_since": self.connected_since,
            "last_command_at": self.last_command_at,
            "command_count": self.command_count,
        }

    def send_command(self, cmd_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a JSON command to Houdini's server and wait for the JSON response.
        Returns the parsed Python dict (e.g. {"status": "success", "result": {...}})
        """
        if not self.connect():
            # Instead of raising, return an error dict consistent with API errors
            error_msg = f"Could not connect to Houdini on port {self.port}."
            logger.error(error_msg)
            # Return structure similar to API failures
            return {"status": "error", "message": error_msg, "origin": "mcp_server_connection"}
            # raise ConnectionError("Could not connect to Houdini on port 9876.") # Original way

        command = {"type": cmd_type, "params": params or {}}
        data_out = json.dumps(command).encode("utf-8")

        try:
            # Send the command
            self.sock.sendall(data_out)
            self.last_command_at = asyncio.get_event_loop().time()
            self.command_count += 1
            logger.info(f"Sent command to Houdini: {command}")

            # Read response. We'll accumulate chunks until we can parse a full JSON.
            chunks = []
            self.sock.settimeout(10.0) # Use TIMEOUT? Or keep specific timeout for Houdini comms?
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                 # Check for timeout
                if asyncio.get_event_loop().time() - start_time > 10.0: # Use same timeout value
                     raise socket.timeout("Timeout waiting for Houdini response")
                     
                # Non-blocking read if possible, or use select/poll?
                # Sticking with blocking recv with timeout for now
                chunk = self.sock.recv(8192)
                if not chunk:
                    # Connection closed gracefully by Houdini?
                    if buffer: # If we have partial data, it's an error
                         raise ConnectionAbortedError("Connection closed by Houdini with incomplete data.")
                    else: # No data received and socket closed -> Houdini might have crashed?
                         raise ConnectionAbortedError("Connection closed by Houdini before sending data.")
                         
                buffer += chunk
                # Try to decode the accumulated buffer
                try:
                    decoded_string = buffer.decode("utf-8")
                    # Attempt to load JSON from the decoded string
                    parsed = json.loads(decoded_string)
                    # If successful, we have a complete JSON object
                    logger.info(f"Received response from Houdini: {parsed}")
                    return parsed
                except json.JSONDecodeError:
                    # Not a complete JSON object yet, continue receiving
                    continue
                except UnicodeDecodeError:
                    # Data received is not valid UTF-8
                     logger.error("Received non-UTF-8 data from Houdini")
                     raise ValueError("Received non-UTF-8 data from Houdini")

            # Should not be reached if loop exits via return or exception
            # raise Exception("No (or incomplete) data from Houdini; EOF reached without valid JSON.")

        except socket.timeout: # Explicitly catch socket timeout
            error_msg = "Timeout receiving data from Houdini."
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command_timeout"}
        except Exception as e:
            error_msg = f"Error during Houdini communication for command '{cmd_type}': {str(e)}"
            logger.error(error_msg)
            # Invalidate socket so we reconnect next time
            self.disconnect()
            # Return error dict consistent with API failures
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command"}
            # raise # Re-raise original exception? Or return dict? Returning dict.


# A global Houdini connection object
_houdini_connection: HoudiniConnection = None

def get_houdini_connection() -> HoudiniConnection:
    """Get or create a persistent HoudiniConnection object."""
    global _houdini_connection
    if _houdini_connection is None:
        logger.info("Creating new HoudiniConnection.")
        _houdini_connection = HoudiniConnection(host="localhost", port=HOUDINI_PORT)

    # Always try to connect, returns True if already connected or successful now
    if not _houdini_connection.connect():
         # Connection failed, reset _houdini_connection to allow retry next time?
         _houdini_connection = None
         raise ConnectionError(f"Could not connect to Houdini on localhost:{HOUDINI_PORT}. Is the plugin running?")
         
    return _houdini_connection


# Now define the MCP server that Claude will talk to over stdio
mcp = FastMCP(
    "HoudiniMCP",
    description="A bridging server that connects Claude to Houdini via MCP stdio + TCP, with OPUS API integration."
)

@asynccontextmanager
async def server_lifespan(app: FastMCP):
    """Startup/shutdown logic. Called automatically by fastmcp."""
    logger.info("Houdini MCP server starting up (stdio).")
    # Attempt to connect right away? Or lazily on first call? Lazy seems safer.
    # try:
    #     get_houdini_connection()
    #     logger.info("Successfully connected to Houdini on startup.")
    # except Exception as e:
    #     logger.warning(f"Could not connect to Houdini on startup: {e}")
    #     logger.warning("Make sure Houdini is running with the plugin on port 9876.")
    yield {} # Context is empty for now
    logger.info("Houdini MCP server shutting down.")
    global _houdini_connection
    if _houdini_connection is not None:
        _houdini_connection.disconnect()
        _houdini_connection = None
    logger.info("Connection to Houdini closed.")

mcp.lifespan = server_lifespan


# -------------------------------------------------------------------
# Original Houdini Tools (Get/Create Node, Execute Code)
# -------------------------------------------------------------------
@mcp.tool()
def ping(ctx: Context) -> str:
    """
    Health check to verify Houdini is connected and responsive.
    Returns server status info or an error if Houdini is unreachable.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("ping")
        if response.get("status") == "error":
            return f"Houdini unreachable: {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
        return f"Houdini unreachable: {str(e)}"
    except Exception as e:
        return f"Ping failed: {str(e)}"

@mcp.tool()
def get_connection_status(ctx: Context) -> str:
    """
    Returns the current connection status to Houdini, including
    whether connected, port, command count, and timing info.
    """
    global _houdini_connection
    if _houdini_connection is None:
        return json.dumps({"connected": False, "host": "localhost", "port": HOUDINI_PORT})
    return json.dumps(_houdini_connection.get_status(), indent=2)

@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """
    Ask Houdini for scene info. Returns JSON as a string.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("get_scene_info")
        # response should look like {"status": "success", "result": {...}} or {"status": "error", ...}
        if response.get("status") == "error":
            # Include origin if available
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2) # Return empty dict if no result
    except ConnectionError as e:
         return f"Connection Error getting scene info: {str(e)}"
    except Exception as e:
        # Catch-all for unexpected errors in this function
        logger.error(f"Unexpected error in get_scene_info tool: {str(e)}", exc_info=True)
        return f"Server Error retrieving scene info: {str(e)}"

@mcp.tool()
def create_node(ctx: Context, node_type: str, parent_path: str = "/obj", name: str = None) -> str:
    """
    Create a new node in Houdini.
    """
    try:
        conn = get_houdini_connection()
        params = { "node_type": node_type, "parent_path": parent_path }
        if name: params["name"] = name
        response = conn.send_command("create_node", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        # Assuming result contains node info like {'name': ..., 'path': ..., 'type': ...}
        return f"Node created: {json.dumps(response.get('result', {}), indent=2)}"
    except ConnectionError as e:
         return f"Connection Error creating node: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in create_node tool: {str(e)}", exc_info=True)
        return f"Server Error creating node: {str(e)}"

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Houdini's environment.
    Returns status and any stdout/stderr generated by the code.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("execute_code", {"code": code})

        # Handle Houdini-side errors first (could be connection error or execution error)
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        # Handle success case (response should have status=success and a result dict)
        result = response.get("result", {}) # Default to empty dict
        if result.get("executed"): # Check if executed flag is True
            stdout = result.get("stdout", "").strip()
            stderr = result.get("stderr", "").strip()

            output_message = "Code executed successfully."
            if stdout:
                output_message += f"\\n--- Stdout ---\\n{stdout}"
            if stderr:
                output_message += f"\\n--- Stderr ---\\n{stderr}"
            return output_message
        else:
            # Unexpected success response format or executed flag missing/false
            logger.warning(f"execute_houdini_code received success status but unexpected result format: {response}")
            return f"Execution status unclear from Houdini response: {json.dumps(response)}"

    except ConnectionError as e:
         return f"Connection Error executing code: {str(e)}"
    except Exception as e:
        # Errors during communication or parsing in this script
        logger.error(f"Unexpected error in execute_houdini_code tool: {str(e)}", exc_info=True)
        return f"Server Error executing code: {str(e)}"

# -------------------------------------------------------------------
# NEW rendering Tools
# -------------------------------------------------------------------
@mcp.tool()
def render_single_view(ctx: Context,
                       orthographic: bool = False,
                       rotation: List[float] = [0, 90, 0],
                       render_path: str = None,
                       render_engine: str = "opengl",
                       karma_engine: str = "cpu") -> str:
    """
    Render a single view inside Houdini and return the rendered image path.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_single_view", {
            "orthographic": orthographic,
            "rotation": rotation,
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_single_view failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_quad_views(ctx: Context,
                      render_path: str = None,
                      render_engine: str = "opengl",
                      karma_engine: str = "cpu") -> str:
    """
    Render 4 canonical views from Houdini and return the image paths.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_quad_view", {
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output returned.")
    except Exception as e:
        logger.error(f"render_quad_views failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_specific_camera(ctx: Context,
                           camera_path: str,
                           render_path: str = None,
                           render_engine: str = "opengl",
                           karma_engine: str = "cpu") -> str:
    """
    Render from a specific camera path in the Houdini scene.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_specific_camera", {
            "camera_path": camera_path,
            "render_path": render_path or tempfile.gettempdir(),
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_specific_camera failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

# -------------------------------------------------------------------
# NEW OPUS API Tools
# -------------------------------------------------------------------

@mcp.tool()
def opus_get_model_names(ctx: Context) -> List[str]:
    """
    Returns a list of available OPUS component/structure names.
    """
    # Currently uses the hardcoded list from helpers
    return get_all_component_names()

@mcp.tool()
def opus_get_model_params_schema(ctx: Context, structure: str) -> dict:
    """
    Retrieves the parameter schema or format instructions for a given OPUS model structure.
    Returns a dictionary, which might contain 'result' (JSON schema) or 'result_format_instructions' (string).
    Check 'statusCode' for success (200) or failure (e.g., 500).
    """
    if not structure:
        return {"statusCode": 400, "error": "Structure name cannot be empty."}
    # This function now returns a dict with statusCode and result/error
    return get_formatted_opus_params(structure)

@mcp.tool()
def opus_create_model(ctx: Context, structure: str, parameters: Dict[str, Any], count: int = 1) -> dict:
    """
    Starts a batch job to create one or more 3D models using the OPUS API.
    Requires the model structure name and a dictionary of parameters.
    Returns a dictionary containing the 'batch_id' on success (statusCode 200) or an error message.
    """
    if not structure:
        return {"statusCode": 400, "error": "Structure name cannot be empty."}
    if not isinstance(parameters, dict):
         return {"statusCode": 400, "error": "Parameters must be a valid JSON object (dict)."}
    if not isinstance(count, int) or count < 1:
         return {"statusCode": 400, "error": "Count must be a positive integer."}
         
    # This function handles API call and returns dict with statusCode and batch_id/error
    return create_opus_component(structure, parameters, count)

@mcp.tool()
def opus_variate_model(ctx: Context, result_id: str, count: int = 12) -> dict:
    """
    Starts a batch job to create variations of an existing OPUS model result.
    Requires the result_id of the base model.
    Returns a dictionary containing the 'batch_id' on success (statusCode 200) or an error message.
    """
    if not result_id:
        return {"statusCode": 400, "error": "Result ID cannot be empty."}
    if not isinstance(count, int) or count < 1:
         return {"statusCode": 400, "error": "Count must be a positive integer."}

    # This function handles API call and returns dict with statusCode and batch_id/error
    return variate_opus_result(result_id, count)

# -------------------------------------------------------------------
# NEW Tools Forwarding to Houdini for OPUS Job Handling
# -------------------------------------------------------------------

@mcp.tool()
def opus_check_job_status(ctx: Context, batch_id: str) -> dict:
    """
    Checks the status of an OPUS batch job directly via the API.
    Requires the batch_id returned by opus_create_model or opus_variate_model.
    Returns the JSON response from the OPUS API, including status and potential download URLs, or an error dictionary.
    """
    if not batch_id:
        return {"error": "Batch ID cannot be empty."}
    
    # Call the helper function directly
    result = get_opus_job_result(batch_job_id=batch_id)
    return result # Return the dictionary (contains result or error)

@mcp.tool()
def opus_import_model_url(ctx: Context, download_url: str, node_name: str = None) -> str:
    """
    Asks Houdini to download a model (zip containing USD) from a URL and import it into the scene.
    Requires the download URL (likely obtained from opus_check_job_status).
    Optionally specify a base name for the new container node.
    (Houdini needs a corresponding 'import_opus_url' command handler)
    """
    if not download_url:
        return "Error: Download URL cannot be empty."
    try:
        conn = get_houdini_connection()
        params = {"url": download_url}
        # Use provided name or generate one from URL
        if node_name:
             params["node_name"] = node_name
        else:
             # Basic name generation from URL
             try:
                 parsed_name = os.path.splitext(os.path.basename(urlparse(download_url).path))[0]
                 params["node_name"] = hou.nodeType(hou.nodeTypeCategories()["Object"], "subnet").instance(parsed_name) # Generate unique name
             except Exception:
                 params["node_name"] = "opus_import" # Fallback name
             
        logger.info(f"Requesting Houdini import: URL={download_url}, NodeName={params['node_name']}")
        # Send command to Houdini's server.py
        response = conn.send_command("import_opus_url", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}) importing model: {response.get('message', 'Unknown error')}"

        # Assuming success returns a dict in 'result' with import info (e.g., new node path)
        result_data = response.get('result', {})
        return f"Import Result: {json.dumps(result_data)}"

    except ConnectionError as e:
         return f"Connection Error importing model: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in opus_import_model_url tool: {str(e)}", exc_info=True)
        return f"Server Error importing model: {str(e)}"

# --- Add get_opus_job_result helper (Updated for RapidAPI) --- 
def get_opus_job_result(batch_job_id: str) -> dict:
    """
    Query OPUS API via RapidAPI for latest job info (including download URLs).
    Uses GET_JOB_RESULT_URL constructed from RapidAPI env vars.
    Returns the JSON response as a dictionary.
    On error, returns a dictionary with an 'error' key.
    """
    if not RAPIDAPI_HOST_URL: # Check RapidAPI config
        return {"error": "RAPIDAPI_HOST_URL not configured."}
    if not batch_job_id:
        return {"error": "batch_job_id cannot be empty."}
        
    url = GET_JOB_RESULT_URL # Use RapidAPI URL
    params = { "result_uid": batch_job_id } # Parameter name from user example, check RapidAPI docs
    headers = { 
        "accept": "application/json",
        'x-rapidapi-host': RAPIDAPI_HOST,
        'x-rapidapi-key': RAPIDAPI_KEY
    }
    try:
        logger.info(f"Querying job status (RapidAPI): URL={url}, Params={params}")
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return resp.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"RapidAPI Error {e.response.status_code} getting job result: {e.response.text}")
        try:
             # Return the error structure from the API if possible
             return {"error": e.response.json(), "status_code": e.response.status_code} 
        except json.JSONDecodeError:
             return {"error": f"RapidAPI Error {e.response.status_code}: {e.response.text}", "status_code": e.response.status_code}
    except requests.exceptions.RequestException as e:
        logger.error(f"RapidAPI request failed getting job result: {str(e)}")
        return {"error": f"RapidAPI request failed: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode job status RapidAPI response: {str(e)}")
        return {"error": "Failed to decode job status RapidAPI response."}
# --- End get_opus_job_result helper ---


# ... (rest of existing code, main function etc) ...


def main():
    """Run the MCP server on stdio."""
    # Check necessary RapidAPI variables are set before running
    if not RAPIDAPI_HOST_URL or not RAPIDAPI_HOST or not RAPIDAPI_KEY:
         logger.critical("RAPIDAPI_HOST_URL, RAPIDAPI_HOST, and RAPIDAPI_KEY environment variables are not set. Please configure urls.env.")
         logger.critical("Server will not start.")
         sys.exit(1) # Exit if critical configuration is missing
         
    logger.info(f"Using RapidAPI Host URL: {RAPIDAPI_HOST_URL}")
    logger.info(f"Using RapidAPI Host Header: {RAPIDAPI_HOST}")
    logger.info(f"Langchain available: {LANGCHAIN_AVAILABLE}")
    mcp.run()

if __name__ == "__main__":
    main()
