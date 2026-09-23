#!/usr/bin/env hython
"""
Parse .hip files via hython — produces hip_parsed.json with filtered parameters.

Must be run with hython (Houdini's Python interpreter), not regular Python.
Supports parallel parsing with --workers N.

Parameter filtering:
  - Skips UI-only types (Folder, FolderSet, Separator, Label, Button)
  - Skips parameters at their default value (hou.Parm.isAtDefault())
  - Keeps only non-default, data-bearing parameters (~80% reduction)

Usage:
    hython scripts/parse_hips.py                          # auto-detect $HFS
    hython scripts/parse_hips.py --hfs-dir /opt/hfs21.0
    hython scripts/parse_hips.py --output hip_parsed.json
    hython scripts/parse_hips.py --extra-dir ~/my_hips
    hython scripts/parse_hips.py --workers 4              # parallel parsing

    # Internal: worker mode (called by orchestrator, not by user)
    hython scripts/parse_hips.py --worker-chunk chunk.json --worker-out out.json

The output JSON has the same shape as hip_parser.py (cpio parser):
    [{"source", "nodes", "connections", "sticky_notes", "netboxes"}, ...]
"""

import argparse
import json
import os
import sys
import time


# Parameter template types that carry no data — skip unconditionally
_UI_ONLY_TYPES = {"Folder", "FolderSet", "Separator", "Label", "Button"}

# Context → node category mapping (matches hip_parser.py)
_CONTEXT_CATEGORIES = {
    "obj": "OBJ",
    "out": "ROP",
    "ch": "CHOP",
    "shop": "SHOP",
    "img": "COP",
    "vex": "VEX",
    "mat": "MAT",
    "stage": "LOP",
    "part": "POP",
}


def _node_category(path):
    """Derive the node category from its Houdini path.

    Matches the logic in hip_parser.py — SOPs are obj children at depth 3+.
    """
    # Strip leading slash for splitting
    clean = path.lstrip("/")
    parts = clean.split("/")
    context = parts[0]
    if context == "obj" and len(parts) >= 3:
        return "SOP"
    return _CONTEXT_CATEGORIES.get(context, context.upper())


def _find_hips(hfs_path, extra_dirs=None):
    """Find all .hip/.hipnc files under $HFS search dirs and extra dirs."""
    results = []
    search_dirs = [
        os.path.join(hfs_path, "houdini", "help"),
        os.path.join(hfs_path, "packages"),
        os.path.join(hfs_path, "toolkit"),
        os.path.join(hfs_path, "engine"),
    ]
    for extra in extra_dirs or []:
        expanded = os.path.expanduser(extra)
        if os.path.isdir(expanded):
            search_dirs.append(expanded)

    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".hip", ".hipnc"):
                    results.append(os.path.join(root, fname))
    return results


def _parse_one(hou, filepath):
    """Load a .hip file and extract filtered node/connection/annotation data."""
    hou.hipFile.load(filepath, suppress_save_prompt=True, ignore_load_warnings=True)

    result = {
        "source": filepath,
        "nodes": [],
        "connections": [],
        "sticky_notes": [],
        "netboxes": [],
    }

    # Walk all nodes in the scene
    for node in hou.node("/").allSubChildren():
        parms = {}
        for p in node.parms():
            try:
                tmpl_type = p.parmTemplate().type().name()
                if tmpl_type in _UI_ONLY_TYPES:
                    continue
                if p.isAtDefault():
                    continue
                val = p.eval()
                if isinstance(val, (int, float, str)):
                    parms[p.name()] = str(val)
            except Exception:
                pass

        node_dict = {
            "type": node.type().name(),
            "path": node.path(),
            "name": node.name(),
            "category": _node_category(node.path()),
            "parameters": parms,
            "children": [c.path() for c in node.children()],
        }

        comment = node.comment()
        if comment:
            node_dict["comment"] = comment

        result["nodes"].append(node_dict)

        # Connections
        for conn in node.inputConnections():
            result["connections"].append({
                "src_path": conn.inputNode().path(),
                "src_output": conn.outputIndex(),
                "dst_path": node.path(),
                "dst_input": conn.inputIndex(),
            })

    # Sticky notes and network boxes at every level
    for container in [hou.node("/")] + list(hou.node("/").allSubChildren()):
        try:
            for sn in container.stickyNotes():
                text = sn.text().strip()
                if text:
                    result["sticky_notes"].append({
                        "context": container.path(),
                        "name": sn.name(),
                        "text": text,
                    })
        except Exception:
            pass

        try:
            for nb in container.networkBoxes():
                label = nb.comment()
                if label:
                    result["netboxes"].append({
                        "context": container.path(),
                        "name": nb.name(),
                        "label": label,
                    })
        except Exception:
            pass

    return result


def _run_worker(chunk_path, output_path):
    """Worker mode: process a chunk of .hip paths, write results to JSON."""
    import hou

    with open(chunk_path, encoding="utf-8") as f:
        hip_files = json.load(f)

    all_results = []
    errors = 0

    for i, filepath in enumerate(hip_files, 1):
        basename = os.path.basename(filepath)
        try:
            result = _parse_one(hou, filepath)
            all_results.append(result)
            print(f"  [{i}/{len(hip_files)}] {basename}: "
                  f"{len(result['nodes'])} nodes, "
                  f"{len(result['connections'])} connections")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(hip_files)}] {basename}: ERROR — {e}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"results": all_results, "errors": errors}, f)


def _run_serial(hfs, hip_files, output_path):
    """Single-process parsing."""
    import hou

    all_results = []
    total_nodes = 0
    total_conns = 0
    total_stickies = 0
    total_netboxes = 0
    errors = 0

    for i, filepath in enumerate(hip_files, 1):
        basename = os.path.basename(filepath)
        try:
            result = _parse_one(hou, filepath)
            n_nodes = len(result["nodes"])
            n_conns = len(result["connections"])
            total_nodes += n_nodes
            total_conns += n_conns
            total_stickies += len(result["sticky_notes"])
            total_netboxes += len(result["netboxes"])
            all_results.append(result)
            print(f"  [{i}/{len(hip_files)}] {basename}: "
                  f"{n_nodes} nodes, {n_conns} connections")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(hip_files)}] {basename}: ERROR — {e}")

    return all_results, total_nodes, total_conns, total_stickies, total_netboxes, errors


def _run_parallel(hfs, hip_files, output_path, workers):
    """Multi-process parsing: split file list into chunks, run N hython workers."""
    import subprocess
    import tempfile

    script_path = os.path.abspath(__file__)
    hython = os.path.join(hfs, "bin", "hython")

    # Round-robin split for balanced load
    chunks = [[] for _ in range(workers)]
    for i, path in enumerate(hip_files):
        chunks[i % workers].append(path)

    tmpdir = tempfile.mkdtemp(prefix="hip_parse_")
    processes = []
    output_files = []

    print(f"Launching {workers} parallel workers...")
    for w in range(workers):
        if not chunks[w]:
            continue
        chunk_path = os.path.join(tmpdir, f"chunk_{w}.json")
        out_path = os.path.join(tmpdir, f"result_{w}.json")
        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(chunks[w], f)
        output_files.append(out_path)

        cmd = [hython, script_path, "--worker-chunk", chunk_path, "--worker-out", out_path]
        proc = subprocess.Popen(
            cmd,
            env={**os.environ, "HFS": hfs},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        processes.append((w, proc, len(chunks[w])))
        print(f"  Worker {w}: {len(chunks[w])} files (PID {proc.pid})")

    # Wait and collect
    all_results = []
    total_errors = 0
    for w, proc, count in processes:
        proc.wait()
        out_path = output_files[w]
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            all_results.extend(data["results"])
            total_errors += data["errors"]
            print(f"  Worker {w} done: {len(data['results'])} files, {data['errors']} errors")
        else:
            print(f"  Worker {w} failed: no output file")
            total_errors += count

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    total_nodes = sum(len(r["nodes"]) for r in all_results)
    total_conns = sum(len(r["connections"]) for r in all_results)
    total_stickies = sum(len(r["sticky_notes"]) for r in all_results)
    total_netboxes = sum(len(r["netboxes"]) for r in all_results)

    return all_results, total_nodes, total_conns, total_stickies, total_netboxes, total_errors


def _auto_workers(hip_count):
    """Choose worker count based on system resources and file count."""
    try:
        import multiprocessing
        cpus = multiprocessing.cpu_count()
    except Exception:
        cpus = 4

    # Hip files are heavier than HDAs — 1200 MB headroom per worker
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail_mb = int(line.split()[1]) / 1024
                    break
            else:
                avail_mb = 8000
    except Exception:
        avail_mb = 8000

    mem_workers = max(1, int(avail_mb / 1200))
    cpu_workers = max(1, cpus - 4)
    file_workers = max(1, hip_count // 10)  # at least 10 files per worker

    workers = max(1, min(mem_workers, cpu_workers, file_workers))
    return workers


def main():
    parser = argparse.ArgumentParser(description="Parse .hip files via hython")
    parser.add_argument("--hfs-dir", default=None, help="Explicit $HFS path")
    parser.add_argument("--extra-dir", action="append", default=[],
                        help="Additional directories to scan for .hip files")
    parser.add_argument("--output", default=None,
                        help="Output JSON path (default: hip_parsed.json)")
    parser.add_argument("--workers", type=int, default=0,
                        help="Parallel workers (0=auto, 1=serial)")
    parser.add_argument("--worker-chunk", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Worker mode: process chunk and exit
    if args.worker_chunk and args.worker_out:
        _run_worker(args.worker_chunk, args.worker_out)
        return

    # Resolve $HFS
    hfs = args.hfs_dir or os.environ.get("HFS")
    if not hfs or not os.path.isdir(hfs):
        print("Error: Could not find Houdini installation.", file=sys.stderr)
        print("Use --hfs-dir or set $HFS.", file=sys.stderr)
        sys.exit(1)

    hip_files = _find_hips(hfs, extra_dirs=args.extra_dir)
    if not hip_files:
        print(f"No .hip/.hipnc files found under {hfs}")
        return

    # Determine worker count
    workers = args.workers
    if workers == 0:
        workers = _auto_workers(len(hip_files))
    use_parallel = workers > 1

    print(f"Houdini install: {hfs}")
    print(f"Parsing {len(hip_files)} .hip files ({workers} worker{'s' if workers > 1 else ''})...\n")

    start = time.time()

    if use_parallel:
        all_results, total_nodes, total_conns, total_stickies, total_netboxes, errors = \
            _run_parallel(hfs, hip_files, args.output, workers)
    else:
        all_results, total_nodes, total_conns, total_stickies, total_netboxes, errors = \
            _run_serial(hfs, hip_files, args.output)

    elapsed = time.time() - start

    # Write output
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    output_path = args.output or os.path.join(repo_root, "hip_parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Parsed:      {len(all_results)} files ({errors} errors)")
    print(f"Total nodes: {total_nodes}")
    print(f"Total conns: {total_conns}")
    print(f"Stickies:    {total_stickies}")
    print(f"Net boxes:   {total_netboxes}")
    print(f"Workers:     {workers}")
    print(f"Time:        {elapsed:.1f}s")
    print(f"Output:      {output_path}")


if __name__ == "__main__":
    main()
