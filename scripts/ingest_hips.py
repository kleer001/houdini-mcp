#!/usr/bin/env python3
"""
Houdini .hip ingest pipeline — discover, parse, extract, and index.

Usage:
    python scripts/ingest_hips.py discover                     # list .hip files
    python scripts/ingest_hips.py parse                        # discover + parse all
    python scripts/ingest_hips.py extract-hdas                 # extract HDA networks via hython
    python scripts/ingest_hips.py extract                      # merge parsed data + extract patterns
    python scripts/ingest_hips.py index                        # build combined BM25 index
    python scripts/ingest_hips.py all                          # full pipeline (including HDAs)

    Options for discover/parse/extract-hdas/extract/all:
        --hfs-dir /opt/hfs21.0          Explicit $HFS path
        --extra-dir ~/my_hips           Additional directories to scan
        --output results.json           Custom output path for parse
"""

import argparse
import glob
import json
import os
import platform
import re
import subprocess
import sys
import time


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

HIP_EXTENSIONS = {".hip", ".hipnc"}
HDA_EXTENSIONS = {".hda", ".otl"}
ALL_EXTENSIONS = HIP_EXTENSIONS | HDA_EXTENSIONS


def _select_highest_version_houdini_path(candidates, system):
    """Return the highest-version Houdini install path from candidate directories.

    This explicitly returns the highest-version Houdini path when candidate
    directory names contain parseable version numbers. If no versioned names
    match for the current platform, falls back to reverse string sorting.
    """
    version_patterns = {
        "Linux": r"^hfs(\d+)\.(\d+)(?:\.(\d+))?$",
        "Darwin": r"^Houdini(\d+)\.(\d+)(?:\.(\d+))?$",
        "Windows": r"^Houdini (\d+)\.(\d+)(?:\.(\d+))?$",
    }
    pattern = version_patterns.get(system)
    all_candidates = [path for path in candidates if os.path.isdir(path)]
    if not pattern:
        return sorted(all_candidates, reverse=True)

    versioned_candidates = []
    for path in all_candidates:
        name = os.path.basename(path)
        match = re.match(pattern, name)
        if not match:
            continue
        major = int(match.group(1))
        minor = int(match.group(2))
        build = int(match.group(3) or 0)
        versioned_candidates.append(((major, minor, build), path))

    versioned_candidates.sort(reverse=True)
    return [path for _version, path in versioned_candidates] or sorted(all_candidates, reverse=True)


def find_houdini_install(hfs_dir=None):
    """Return the $HFS path (Houdini install root) or None.

    Priority: hfs_dir arg > $HFS env var > platform-specific glob.
    """
    if hfs_dir:
        if os.path.isdir(hfs_dir):
            return hfs_dir
        return None

    hfs_env = os.environ.get("HFS")
    if hfs_env and os.path.isdir(hfs_env):
        return hfs_env

    system = platform.system()
    if system == "Linux":
        candidates = _select_highest_version_houdini_path(glob.glob("/opt/hfs*"), system)
    elif system == "Darwin":
        candidates = _select_highest_version_houdini_path(
            glob.glob("/Applications/Houdini/Houdini*"),
            system,
        )
    elif system == "Windows":
        candidates = _select_highest_version_houdini_path(
            glob.glob(r"C:\Program Files\Side Effects Software\Houdini *"),
            system,
        )
    else:
        candidates = []

    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def _walk_for_extensions(base_dir):
    """Walk base_dir recursively and yield matching files."""
    for root, _dirs, files in os.walk(base_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALL_EXTENSIONS:
                continue
            full_path = os.path.join(root, fname)
            rel_dir = os.path.relpath(root, base_dir)
            file_type = "hip" if ext in HIP_EXTENSIONS else "hda"
            yield {
                "path": full_path,
                "type": file_type,
                "size": os.path.getsize(full_path),
                "rel_dir": rel_dir,
            }


# Subdirectories of $HFS to search (in priority order).
# Houdini stores examples under houdini/help/, HDAs under houdini/otls/,
# demo scenes under packages/, and sample files under toolkit/ and engine/.
_HFS_SEARCH_SUBDIRS = [
    os.path.join("houdini", "help"),
    os.path.join("houdini", "otls"),
    "packages",
    "toolkit",
    "engine",
]


def discover_hip_files(hfs_path, extra_dirs=None):
    """Walk directories and catalog .hip/.hipnc/.hda/.otl files.

    Searches known $HFS subdirectories (houdini/help, houdini/otls, packages,
    toolkit, engine) plus any --extra-dir paths.

    Returns a list of dicts: {"path", "type", "size", "rel_dir"}.
    """
    results = []

    for subdir in _HFS_SEARCH_SUBDIRS:
        full = os.path.join(hfs_path, subdir)
        if os.path.isdir(full):
            results.extend(_walk_for_extensions(full))

    for extra in extra_dirs or []:
        expanded = os.path.expanduser(extra)
        if os.path.isdir(expanded):
            results.extend(_walk_for_extensions(expanded))

    return results


def print_summary(files, hfs_path):
    """Print a summary of discovered files."""
    hip_count = sum(1 for f in files if f["type"] == "hip")
    hda_count = sum(1 for f in files if f["type"] == "hda")
    total_size = sum(f["size"] for f in files)

    print(f"Houdini install: {hfs_path}")
    print(f"Files found: {len(files)} ({hip_count} hip, {hda_count} hda)")
    print(f"Total size:  {total_size / (1024 * 1024):.1f} MB")

    # Subdirectory breakdown
    dir_counts = {}
    for f in files:
        d = f["rel_dir"]
        dir_counts[d] = dir_counts.get(d, 0) + 1

    if dir_counts:
        print("\nBy directory:")
        for d in sorted(dir_counts):
            print(f"  {d}: {dir_counts[d]} files")


def _resolve_hfs(args):
    """Resolve $HFS from args or exit with error."""
    hfs_path = find_houdini_install(hfs_dir=args.hfs_dir)
    if not hfs_path:
        print("Error: Could not find Houdini installation.", file=sys.stderr)
        print("Use --hfs-dir to specify the $HFS path.", file=sys.stderr)
        sys.exit(1)
    return hfs_path


def cmd_discover(args):
    """Handle the 'discover' subcommand."""
    hfs_path = _resolve_hfs(args)
    files = discover_hip_files(hfs_path, extra_dirs=args.extra_dir)
    if not files:
        print(f"No .hip/.hda files found under {hfs_path}")
        return
    print_summary(files, hfs_path)


def _cmd_parse_cpio(args):
    """Parse .hip files using the cpio parser (no Houdini required)."""
    sys.path.insert(0, SCRIPT_DIR)
    from hip_parser import parse_hip_file

    hfs_path = _resolve_hfs(args)
    all_files = discover_hip_files(hfs_path, extra_dirs=args.extra_dir)
    hip_files = [f for f in all_files if f["type"] == "hip"]

    if not hip_files:
        print(f"No .hip files found under {hfs_path}")
        return

    print(f"Houdini install: {hfs_path}")
    print(f"Parsing {len(hip_files)} .hip files (cpio fallback)...\n")

    results = []
    total_nodes = 0
    total_conns = 0
    errors = 0
    start = time.time()

    for i, entry in enumerate(hip_files, 1):
        filepath = entry["path"]
        basename = os.path.basename(filepath)
        try:
            result = parse_hip_file(filepath)
            n_nodes = len(result["nodes"])
            n_conns = len(result["connections"])
            total_nodes += n_nodes
            total_conns += n_conns
            results.append(result)
            print(f"  [{i}/{len(hip_files)}] {basename}: {n_nodes} nodes, {n_conns} connections")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(hip_files)}] {basename}: ERROR — {e}")

    elapsed = time.time() - start

    # Write results to JSON
    output_path = args.output or os.path.join(REPO_ROOT, "hip_parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Parsed:      {len(results)} files ({errors} errors)")
    print(f"Total nodes: {total_nodes}")
    print(f"Total conns: {total_conns}")
    print(f"Time:        {elapsed:.1f}s")
    print(f"Output:      {output_path}")


def _cmd_parse_hython(args, hfs_path, hython):
    """Parse .hip files using hython (filtered parameters)."""
    script = os.path.join(SCRIPT_DIR, "parse_hips.py")
    cmd = [hython, script, "--hfs-dir", hfs_path]
    for extra in args.extra_dir:
        cmd.extend(["--extra-dir", extra])
    if hasattr(args, "output") and args.output:
        cmd.extend(["--output", args.output])
    workers = getattr(args, "workers", 0)
    cmd.extend(["--workers", str(workers)])

    print(f"Running: {os.path.basename(hython)} {os.path.basename(script)}")
    result = subprocess.run(cmd, env={**os.environ, "HFS": hfs_path})
    if result.returncode != 0:
        print("Error: hython parsing failed.", file=sys.stderr)
        sys.exit(result.returncode)


def cmd_parse(args):
    """Handle the 'parse' subcommand — hython if available, cpio fallback."""
    hfs_path = _resolve_hfs(args)
    hython = _find_hython(hfs_path)
    if hython:
        _cmd_parse_hython(args, hfs_path, hython)
    else:
        print("Warning: hython not found — using cpio parser (no parameter filtering)")
        _cmd_parse_cpio(args)


def _find_hython(hfs_path):
    """Find hython binary under $HFS/bin/."""
    for name in ("hython", "hython.exe"):
        path = os.path.join(hfs_path, "bin", name)
        if os.path.isfile(path):
            return path
    return None


def cmd_extract_hdas(args):
    """Handle the 'extract-hdas' subcommand — extract HDA networks via hython."""
    hfs_path = _resolve_hfs(args)
    hython = _find_hython(hfs_path)
    if not hython:
        print(f"Error: hython not found under {hfs_path}/bin/", file=sys.stderr)
        sys.exit(1)

    script = os.path.join(SCRIPT_DIR, "extract_hdas.py")
    cmd = [hython, script, "--hfs-dir", hfs_path]
    for extra in args.extra_dir:
        cmd.extend(["--extra-dir", extra])
    if hasattr(args, "output") and args.output:
        cmd.extend(["--output", args.output])
    workers = getattr(args, "workers", 0)
    cmd.extend(["--workers", str(workers)])

    print(f"Running: {os.path.basename(hython)} {os.path.basename(script)}")
    result = subprocess.run(cmd, env={**os.environ, "HFS": hfs_path})
    if result.returncode != 0:
        print("Error: HDA extraction failed.", file=sys.stderr)
        sys.exit(result.returncode)


def cmd_extract(args):
    """Handle the 'extract' subcommand — merge parsed data + extract patterns."""
    sys.path.insert(0, SCRIPT_DIR)
    from hip_patterns import extract_patterns, write_patterns, build_patterns_index

    # Load parsed data from both sources
    hip_path = args.output or os.path.join(REPO_ROOT, "hip_parsed.json")
    hda_path = os.path.join(REPO_ROOT, "hda_parsed.json")

    parsed_scenes = []
    if os.path.exists(hip_path):
        print(f"Loading .hip data from {hip_path}")
        with open(hip_path, encoding="utf-8") as f:
            parsed_scenes.extend(json.load(f))
    else:
        print("No hip_parsed.json found, running parse first...")
        cmd_parse(args)
        if not os.path.exists(hip_path):
            print(f"No parsed .hip data available at {hip_path} - skipping pattern extraction.")
            return
        with open(hip_path, encoding="utf-8") as f:
            parsed_scenes.extend(json.load(f))

    if os.path.exists(hda_path):
        print(f"Loading .hda data from {hda_path}")
        with open(hda_path, encoding="utf-8") as f:
            hda_scenes = json.load(f)
        parsed_scenes.extend(hda_scenes)
        print(f"  {len(hda_scenes)} HDA definitions loaded")
    else:
        print("No hda_parsed.json found (run extract-hdas to include HDAs)")

    print(f"\nExtracting patterns from {len(parsed_scenes)} scenes...")
    patterns = extract_patterns(parsed_scenes)

    patterns_dir = os.path.join(REPO_ROOT, "hip_patterns")
    count = write_patterns(patterns, patterns_dir)

    index_path = os.path.join(REPO_ROOT, "hip_patterns_index.json")
    build_patterns_index(patterns, index_path)

    # Summarize by type
    type_counts = {}
    for p in patterns:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1

    print(f"\nPatterns extracted: {count}")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")
    print(f"Output: {patterns_dir}")
    print(f"Index:  {index_path}")


def cmd_index(args):
    """Handle the 'index' subcommand — build combined BM25 index."""
    sys.path.insert(0, REPO_ROOT)
    from houdini_rag import build_combined_index

    index = build_combined_index()
    print(f"Index built: {len(index.documents)} documents")


def cmd_all(args):
    """Handle the 'all' subcommand — full pipeline including HDAs."""
    sys.path.insert(0, REPO_ROOT)

    print("=== Step 1/5: Discover ===")
    cmd_discover(args)

    print(f"\n=== Step 2/5: Parse .hip files ===")
    cmd_parse(args)

    print(f"\n=== Step 3/5: Extract HDAs (hython) ===")
    hfs_path = find_houdini_install(hfs_dir=args.hfs_dir)
    hython = _find_hython(hfs_path) if hfs_path else None
    if hython:
        cmd_extract_hdas(args)
    else:
        print("Skipping: hython not found (HDA extraction requires Houdini)")

    print(f"\n=== Step 4/5: Extract patterns ===")
    cmd_extract(args)

    print(f"\n=== Step 5/5: Index ===")
    cmd_index(args)

    print(f"\n{'='*60}")
    print("Pipeline complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_common_args(parser):
    """Add --hfs-dir and --extra-dir to a subparser."""
    parser.add_argument("--hfs-dir", default=None, help="Explicit $HFS path")
    parser.add_argument("--extra-dir", action="append", default=[], help="Additional directories to scan")


def main():
    parser = argparse.ArgumentParser(description="Houdini .hip ingest pipeline")
    subparsers = parser.add_subparsers(dest="command")

    discover_parser = subparsers.add_parser("discover", help="Find Houdini install and list .hip files")
    _add_common_args(discover_parser)

    parse_parser = subparsers.add_parser("parse", help="Discover + parse all .hip files")
    _add_common_args(parse_parser)
    parse_parser.add_argument("--output", default=None, help="Output JSON path (default: hip_parsed.json)")
    parse_parser.add_argument("--workers", type=int, default=0, help="Parallel workers for hython parsing (0=auto, 1=serial)")

    extract_hdas_parser = subparsers.add_parser("extract-hdas", help="Extract HDA networks via hython")
    _add_common_args(extract_hdas_parser)
    extract_hdas_parser.add_argument("--output", default=None, help="Output JSON path (default: hda_parsed.json)")
    extract_hdas_parser.add_argument("--workers", type=int, default=0, help="Parallel workers (0=auto, 1=serial)")

    extract_parser = subparsers.add_parser("extract", help="Merge parsed data + extract patterns")
    _add_common_args(extract_parser)
    extract_parser.add_argument("--output", default=None, help="Output JSON path (default: hip_parsed.json)")

    subparsers.add_parser("index", help="Build combined BM25 index from docs + patterns")

    all_parser = subparsers.add_parser("all", help="Run full pipeline including HDAs")
    _add_common_args(all_parser)
    all_parser.add_argument("--output", default=None, help="Output JSON path (default: hip_parsed.json)")
    all_parser.add_argument("--workers", type=int, default=0, help="Parallel workers for HDA extraction (0=auto, 1=serial)")

    args = parser.parse_args()

    commands = {
        "discover": cmd_discover,
        "parse": cmd_parse,
        "extract-hdas": cmd_extract_hdas,
        "extract": cmd_extract,
        "index": cmd_index,
        "all": cmd_all,
    }
    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
