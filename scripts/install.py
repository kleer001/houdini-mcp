#!/usr/bin/env python3
"""
install.py — Set up HoudiniMCP for automatic loading in Houdini.

This script:
1. Detects the Houdini user preferences directory
2. Copies the plugin files to the scripts/python/houdinimcp/ directory
3. Creates a packages JSON file so Houdini auto-loads the plugin at startup

Usage:
    python install.py                    # Auto-detect Houdini version
    python install.py --houdini-version 20.5  # Specify Houdini version
    python install.py --prefs-dir /path/to/houdiniX.Y  # Explicit prefs directory
    python install.py --dry-run          # Show what would be done without doing it
"""
import os
import sys
import shutil
import json
import argparse
import platform
import glob


PLUGIN_FILES = [
    "src/houdinimcp/__init__.py",
    "src/houdinimcp/server.py",
    "src/houdinimcp/HoudiniMCPRender.py",
    "src/houdinimcp/claude_terminal.py",
    "src/houdinimcp/event_collector.py",
]
HANDLER_DIR = "src/houdinimcp/handlers"
PANEL_FILES = [
    "src/houdinimcp/ClaudeTerminal.pypanel",
]
SHELF_FILES = [
    "src/houdinimcp/houdinimcp.shelf",
]
PACKAGE_NAME = "houdinimcp"


def find_houdini_prefs(houdini_version=None):
    """Find the Houdini user preferences directory."""
    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        base = os.path.join(home, "Documents")
    elif system == "Darwin":
        base = os.path.join(home, "Library", "Preferences", "houdini")
    else:  # Linux
        base = home

    if houdini_version:
        if system == "Windows":
            candidate = os.path.join(base, f"houdini{houdini_version}")
        elif system == "Darwin":
            candidate = os.path.join(base, houdini_version)
        else:
            candidate = os.path.join(base, f"houdini{houdini_version}")
        if os.path.isdir(candidate):
            return candidate
        # Directory doesn't exist yet — still return it so we can create it
        return candidate

    # Auto-detect: find the newest houdini prefs directory
    if system == "Darwin":
        search_base = base
        pattern = "[0-9]*.[0-9]*"
    else:
        search_base = base
        pattern = "houdini[0-9]*.[0-9]*"

    candidates = sorted(glob.glob(os.path.join(search_base, pattern)), reverse=True)
    if candidates:
        return candidates[0]

    return None


def install(prefs_dir, source_dir, dry_run=False):
    """Install plugin files and create the packages JSON."""
    plugin_dest = os.path.join(prefs_dir, "scripts", "python", PACKAGE_NAME)
    packages_dir = os.path.join(prefs_dir, "packages")

    print(f"Source directory:  {source_dir}")
    print(f"Plugin install to: {plugin_dest}")
    print(f"Package config:    {os.path.join(packages_dir, f'{PACKAGE_NAME}.json')}")
    print()

    # Copy plugin files
    if not dry_run:
        os.makedirs(plugin_dest, exist_ok=True)

    for filepath in PLUGIN_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(plugin_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)}")

    # Copy handlers/ directory
    handlers_src = os.path.join(source_dir, HANDLER_DIR)
    handlers_dest = os.path.join(plugin_dest, "handlers")
    if os.path.isdir(handlers_src):
        if dry_run:
            print(f"  COPY {handlers_src}/ -> {handlers_dest}/")
        else:
            if os.path.exists(handlers_dest):
                shutil.rmtree(handlers_dest)
            shutil.copytree(handlers_src, handlers_dest)
            handler_count = sum(1 for f in os.listdir(handlers_dest) if f.endswith('.py'))
            print(f"  Copied handlers/ ({handler_count} modules)")

    # Copy .pypanel files to Houdini's python_panels directory
    panels_dest = os.path.join(prefs_dir, "python_panels")
    if not dry_run:
        os.makedirs(panels_dest, exist_ok=True)
    for filepath in PANEL_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(panels_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)} -> python_panels/")

    # Copy .shelf files to Houdini's toolbar directory
    toolbar_dest = os.path.join(prefs_dir, "toolbar")
    if not dry_run:
        os.makedirs(toolbar_dest, exist_ok=True)
    for filepath in SHELF_FILES:
        src = os.path.join(source_dir, filepath)
        dst = os.path.join(toolbar_dest, os.path.basename(filepath))
        if not os.path.isfile(src):
            print(f"  SKIP {filepath} (not found in source)")
            continue
        if dry_run:
            print(f"  COPY {src} -> {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  Copied {os.path.basename(filepath)} -> toolbar/")

    # Create packages JSON
    # Use forward slashes for cross-platform Houdini compatibility
    python_scripts_dir = os.path.join(prefs_dir, "scripts", "python").replace("\\", "/")
    package_json = {
        "path": plugin_dest.replace("\\", "/"),
        "load_package_once": True,
        "version": "0.1",
        "env": [
            {
                "PYTHONPATH": {
                    "value": python_scripts_dir,
                    "method": "append",
                }
            }
        ]
    }

    package_file = os.path.join(packages_dir, f"{PACKAGE_NAME}.json")
    if dry_run:
        print(f"\n  WRITE {package_file}:")
        print(f"  {json.dumps(package_json, indent=2)}")
    else:
        os.makedirs(packages_dir, exist_ok=True)
        with open(package_file, "w") as f:
            json.dump(package_json, f, indent=2)
        print(f"\n  Created package file: {package_file}")

    print("\nDone!" if not dry_run else "\nDry run complete — no files were changed.")
    if not dry_run:
        print("Restart Houdini for changes to take effect.")
        print("The MCP server will auto-start when Houdini loads the plugin.")


def main():
    parser = argparse.ArgumentParser(description="Install HoudiniMCP plugin for auto-loading")
    parser.add_argument("--houdini-version", default=None, help="Houdini version (e.g. 20.5)")
    parser.add_argument("--prefs-dir", default=None, help="Explicit Houdini preferences directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()

    # scripts/ is one level below the repo root
    source_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.prefs_dir:
        prefs_dir = args.prefs_dir
    else:
        prefs_dir = find_houdini_prefs(args.houdini_version)

    if not prefs_dir:
        print("Error: Could not find Houdini preferences directory.", file=sys.stderr)
        print("Use --houdini-version or --prefs-dir to specify it.", file=sys.stderr)
        sys.exit(1)

    print(f"Houdini prefs directory: {prefs_dir}\n")
    install(prefs_dir, source_dir, args.dry_run)


if __name__ == "__main__":
    main()
