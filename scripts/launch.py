#!/usr/bin/env python3
"""
launch.py — Start Houdini with the MCP plugin and optionally the MCP bridge.

Usage:
    python launch.py                  # Launch Houdini only (bridge started separately)
    python launch.py --bridge         # Launch Houdini + MCP bridge
    python launch.py --bridge-only    # Launch MCP bridge only (Houdini already running)

Environment variables:
    HOUDINI_PATH       Path to Houdini executable (e.g. /opt/hfs20.0/bin/houdini)
    HOUDINIMCP_PORT    TCP port for plugin communication (default: 9876)
    HOUDINIMCP_HIP     Optional .hip file to open on launch
"""
import os
import sys
import subprocess
import shutil
import argparse
import platform


def find_houdini():
    """Locate the Houdini executable, checking HOUDINI_PATH env var first, then common locations."""
    env_path = os.environ.get("HOUDINI_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    system = platform.system()
    candidates = []

    if system == "Windows":
        # Check common Windows install locations
        for base in [r"C:\Program Files\Side Effects Software", r"C:\Program Files (x86)\Side Effects Software"]:
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    candidates.append(os.path.join(base, d, "bin", "houdini.exe"))
    elif system == "Darwin":
        # macOS: /Applications/Houdini/HoudiniX.Y.Z/...
        for base in ["/Applications/Houdini"]:
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    candidates.append(os.path.join(base, d, "Frameworks", "Houdini.framework", "Versions", "Current", "Resources", "bin", "houdini"))
        # Also check /opt
        if os.path.isdir("/opt"):
            for d in sorted(os.listdir("/opt"), reverse=True):
                if d.startswith("hfs"):
                    candidates.append(os.path.join("/opt", d, "bin", "houdini"))
    else:
        # Linux: /opt/hfsX.Y or common install dirs
        if os.path.isdir("/opt"):
            for d in sorted(os.listdir("/opt"), reverse=True):
                if d.startswith("hfs"):
                    candidates.append(os.path.join("/opt", d, "bin", "houdini"))

    # Also check if houdini is on PATH
    path_houdini = shutil.which("houdini")
    if path_houdini:
        candidates.insert(0, path_houdini)

    for c in candidates:
        if os.path.isfile(c):
            return c

    return None


def launch_houdini(houdini_path, hip_file=None):
    """Launch Houdini as a detached subprocess."""
    cmd = [houdini_path]
    if hip_file:
        cmd.append(hip_file)

    print(f"Launching Houdini: {' '.join(cmd)}")
    subprocess.Popen(cmd, start_new_session=True)


def launch_bridge():
    """Launch the MCP bridge server in the foreground."""
    # scripts/ is one level below the repo root where houdini_mcp_server.py lives
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bridge_script = os.path.join(repo_root, "houdini_mcp_server.py")

    if not os.path.isfile(bridge_script):
        print(f"Error: Bridge script not found at {bridge_script}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting MCP bridge: uv run python {bridge_script}")
    try:
        subprocess.run(["uv", "run", "python", bridge_script])
    except KeyboardInterrupt:
        print("\nMCP bridge stopped.")


def main():
    parser = argparse.ArgumentParser(description="Launch HoudiniMCP components")
    parser.add_argument("--bridge", action="store_true", help="Also start the MCP bridge after launching Houdini")
    parser.add_argument("--bridge-only", action="store_true", help="Start only the MCP bridge (Houdini already running)")
    parser.add_argument("--hip", default=os.environ.get("HOUDINIMCP_HIP"), help="Path to .hip file to open")
    parser.add_argument("--houdini-path", default=None, help="Explicit path to Houdini executable")
    args = parser.parse_args()

    if args.bridge_only:
        launch_bridge()
        return

    houdini_path = args.houdini_path or find_houdini()
    if not houdini_path:
        print("Error: Could not find Houdini. Set HOUDINI_PATH or use --houdini-path.", file=sys.stderr)
        sys.exit(1)

    launch_houdini(houdini_path, args.hip)

    if args.bridge:
        print("Waiting a few seconds for Houdini to start...")
        import time
        time.sleep(5)
        launch_bridge()
    else:
        print("Houdini launched. Start the MCP bridge separately with: uv run python houdini_mcp_server.py")


if __name__ == "__main__":
    main()
