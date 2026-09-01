#!/usr/bin/env hython
"""
Extract HDA networks via hython — produces hda_parsed.json.

Must be run with hython (Houdini's Python interpreter), not regular Python.
Supports parallel extraction with --workers N.

Usage:
    hython scripts/extract_hdas.py                          # auto-detect $HFS
    hython scripts/extract_hdas.py --hfs-dir /opt/hfs21.0
    hython scripts/extract_hdas.py --output hda_parsed.json
    hython scripts/extract_hdas.py --extra-dir ~/my_hdas
    hython scripts/extract_hdas.py --workers 8              # parallel extraction

    # Internal: worker mode (called by orchestrator, not by user)
    hython scripts/extract_hdas.py --worker-chunk chunk.json --worker-out out.json

The output JSON has the same shape as hip_parsed.json:
    [{"source", "nodes", "connections", "sticky_notes", "netboxes"}, ...]
"""

import argparse
import json
import os
import sys
import time


def _find_hdas(hfs_path, extra_dirs=None):
    """Find all .hda/.otl files under $HFS/houdini/help and extra dirs."""
    results = []
    search_dirs = [
        os.path.join(hfs_path, "houdini", "help"),
        os.path.join(hfs_path, "houdini", "otls"),
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
                if ext in (".hda", ".otl"):
                    results.append(os.path.join(root, fname))
    return results


# Map hou node category names to parent context paths for createNode
_CATEGORY_PARENTS = {
    "Object": "/obj",
    "Sop": None,       # needs geo container
    "Dop": None,       # needs dopnet container
    "Top": None,       # needs topnet container
    "Lop": "/stage",
    "Driver": "/out",
    "Cop2": "/img",
    "CopNet": "/img",
    "Chop": "/ch",
    "ChopNet": "/ch",
    "Shop": "/shop",
    "Vop": None,       # needs vop container
}


def _create_parent(hou, category_name):
    """Create an appropriate parent node for the given HDA category."""
    direct = _CATEGORY_PARENTS.get(category_name)
    if direct:
        return hou.node(direct)

    obj = hou.node("/obj")
    if category_name == "Sop":
        return obj.createNode("geo")
    if category_name == "Dop":
        return obj.createNode("dopnet")
    if category_name == "Top":
        return obj.createNode("topnet")
    if category_name == "Vop":
        geo = obj.createNode("geo")
        return geo.createNode("attribvop")

    # Fallback: try /obj
    return obj


_UI_ONLY_TYPES = {"Folder", "FolderSet", "Separator", "Label", "Button"}


def _extract_one(hou, hda_path):
    """Extract a single HDA file → list of result dicts (one per definition)."""
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hda.installFile(hda_path)
    defs = hou.hda.definitionsInFile(hda_path)

    results = []
    for defn in defs:
        cat_name = defn.nodeTypeCategory().name()
        parent = _create_parent(hou, cat_name)
        node = parent.createNode(defn.nodeTypeName())
        node.allowEditingOfContents()

        result = {
            "source": hda_path,
            "nodes": [],
            "connections": [],
            "sticky_notes": [],
            "netboxes": [],
        }

        # Walk all sub-children
        for child in node.allSubChildren():
            parms = {}
            for p in child.parms():
                try:
                    tmpl_type = p.parmTemplate().type().name()
                    if tmpl_type in _UI_ONLY_TYPES:
                        continue
                    if not p.isAtDefault():
                        val = p.eval()
                        if isinstance(val, (int, float, str)):
                            parms[p.name()] = str(val)
                except Exception:
                    pass

            node_dict = {
                "type": child.type().name(),
                "path": child.path(),
                "name": child.name(),
                "category": child.type().category().name().upper(),
                "parameters": parms,
                "children": [c.path() for c in child.children()],
            }

            comment = child.comment()
            if comment:
                node_dict["comment"] = comment

            result["nodes"].append(node_dict)

            # Connections
            for conn in child.inputConnections():
                result["connections"].append({
                    "src_path": conn.inputNode().path(),
                    "src_output": conn.outputIndex(),
                    "dst_path": child.path(),
                    "dst_input": conn.inputIndex(),
                })

        # Sticky notes and network boxes at every level
        for container in [node] + list(node.allSubChildren()):
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

        results.append(result)

    return results


def _run_worker(chunk_path, output_path):
    """Worker mode: process a chunk of HDA paths, write results to JSON."""
    import hou

    with open(chunk_path, encoding="utf-8") as f:
        hda_files = json.load(f)

    all_results = []
    errors = 0

    for i, hda_path in enumerate(hda_files, 1):
        basename = os.path.basename(hda_path)
        try:
            results = _extract_one(hou, hda_path)
            all_results.extend(results)
            print(f"  [{i}/{len(hda_files)}] {basename}: "
                  f"{sum(len(r['nodes']) for r in results)} nodes")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(hda_files)}] {basename}: ERROR — {e}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"results": all_results, "errors": errors}, f)


def _run_serial(hfs, hda_files, output_path):
    """Single-process extraction (original behavior)."""
    import hou

    all_results = []
    total_nodes = 0
    total_stickies = 0
    total_comments = 0
    total_netboxes = 0
    errors = 0

    for i, hda_path in enumerate(hda_files, 1):
        basename = os.path.basename(hda_path)
        try:
            results = _extract_one(hou, hda_path)
            for r in results:
                n_nodes = len(r["nodes"])
                n_stickies = len(r["sticky_notes"])
                n_comments = sum(1 for n in r["nodes"] if "comment" in n)
                n_netboxes = len(r["netboxes"])
                total_nodes += n_nodes
                total_stickies += n_stickies
                total_comments += n_comments
                total_netboxes += n_netboxes
                all_results.append(r)
            print(f"  [{i}/{len(hda_files)}] {basename}: "
                  f"{sum(len(r['nodes']) for r in results)} nodes, "
                  f"{sum(len(r['sticky_notes']) for r in results)} stickies")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(hda_files)}] {basename}: ERROR — {e}")

    return all_results, total_nodes, total_stickies, total_comments, total_netboxes, errors


def _run_parallel(hfs, hda_files, output_path, workers):
    """Multi-process extraction: split HDA list into chunks, run N hython workers."""
    import subprocess
    import tempfile

    script_path = os.path.abspath(__file__)
    hython = os.path.join(hfs, "bin", "hython")

    # Split HDA list into chunks (round-robin for balanced load)
    chunks = [[] for _ in range(workers)]
    for i, path in enumerate(hda_files):
        chunks[i % workers].append(path)

    # Write chunk files and launch workers
    tmpdir = tempfile.mkdtemp(prefix="hda_extract_")
    processes = []
    chunk_files = []
    output_files = []

    print(f"Launching {workers} parallel workers...")
    for w in range(workers):
        if not chunks[w]:
            continue
        chunk_path = os.path.join(tmpdir, f"chunk_{w}.json")
        out_path = os.path.join(tmpdir, f"result_{w}.json")
        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(chunks[w], f)
        chunk_files.append(chunk_path)
        output_files.append(out_path)

        cmd = [hython, script_path, "--worker-chunk", chunk_path, "--worker-out", out_path]
        proc = subprocess.Popen(
            cmd,
            env={**os.environ, "HFS": hfs},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        processes.append((w, proc, len(chunks[w])))
        print(f"  Worker {w}: {len(chunks[w])} HDAs (PID {proc.pid})")

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
            print(f"  Worker {w} done: {len(data['results'])} definitions, {data['errors']} errors")
        else:
            print(f"  Worker {w} failed: no output file")
            total_errors += count

    # Cleanup temp files
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    # Compute totals
    total_nodes = sum(len(r["nodes"]) for r in all_results)
    total_stickies = sum(len(r["sticky_notes"]) for r in all_results)
    total_comments = sum(sum(1 for n in r["nodes"] if "comment" in n) for r in all_results)
    total_netboxes = sum(len(r["netboxes"]) for r in all_results)

    return all_results, total_nodes, total_stickies, total_comments, total_netboxes, total_errors


def _auto_workers(hda_count):
    """Choose worker count based on system resources and HDA count."""
    try:
        import multiprocessing
        cpus = multiprocessing.cpu_count()
    except Exception:
        cpus = 4

    # Hython uses ~555 MB per instance; leave headroom
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

    mem_workers = max(1, int(avail_mb / 800))  # 800 MB per worker with overhead
    cpu_workers = max(1, cpus - 4)              # leave 4 cores for OS + orchestrator
    hda_workers = max(1, hda_count // 20)       # at least 20 HDAs per worker

    workers = max(1, min(mem_workers, cpu_workers, hda_workers))
    return workers


def main():
    parser = argparse.ArgumentParser(description="Extract HDA networks via hython")
    parser.add_argument("--hfs-dir", default=None, help="Explicit $HFS path")
    parser.add_argument("--extra-dir", action="append", default=[],
                        help="Additional directories to scan for HDAs")
    parser.add_argument("--output", default=None,
                        help="Output JSON path (default: hda_parsed.json)")
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

    hda_files = _find_hdas(hfs, extra_dirs=args.extra_dir)
    if not hda_files:
        print(f"No .hda/.otl files found under {hfs}")
        return

    # Determine worker count
    workers = args.workers
    if workers == 0:
        workers = _auto_workers(len(hda_files))
    use_parallel = workers > 1

    print(f"Houdini install: {hfs}")
    print(f"Extracting {len(hda_files)} HDAs ({workers} worker{'s' if workers > 1 else ''})...\n")

    start = time.time()

    if use_parallel:
        all_results, total_nodes, total_stickies, total_comments, total_netboxes, errors = \
            _run_parallel(hfs, hda_files, args.output, workers)
    else:
        import hou
        all_results, total_nodes, total_stickies, total_comments, total_netboxes, errors = \
            _run_serial(hfs, hda_files, args.output)

    elapsed = time.time() - start

    # Write output
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    output_path = args.output or os.path.join(repo_root, "hda_parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Extracted:     {len(all_results)} HDA definitions ({errors} errors)")
    print(f"Total nodes:   {total_nodes}")
    print(f"Sticky notes:  {total_stickies}")
    print(f"Node comments: {total_comments}")
    print(f"Network boxes: {total_netboxes}")
    print(f"Workers:       {workers}")
    print(f"Time:          {elapsed:.1f}s")
    print(f"Output:        {output_path}")


if __name__ == "__main__":
    main()
