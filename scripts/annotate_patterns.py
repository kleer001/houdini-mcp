#!/usr/bin/env python3
"""
Annotate extracted patterns — list, view, annotate, and track progress.

Operates on the hip_patterns/ directory produced by `ingest_hips.py extract`.

Usage:
    python scripts/annotate_patterns.py list                  # show unannotated patterns
    python scripts/annotate_patterns.py list --limit 5        # limit output
    python scripts/annotate_patterns.py get <pattern_id>      # view a pattern
    python scripts/annotate_patterns.py annotate <pattern_id> "summary text"
    python scripts/annotate_patterns.py progress              # show annotation stats
"""

import argparse
import json
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
PATTERNS_DIR = os.path.join(REPO_ROOT, "hip_patterns")
INDEX_PATH = os.path.join(REPO_ROOT, "hip_patterns_index.json")


def list_unannotated(limit=20):
    """Return patterns without annotations."""
    if not os.path.exists(INDEX_PATH):
        return {"error": "No patterns index found. Run: python scripts/ingest_hips.py extract"}

    with open(INDEX_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    unannotated = []
    for entry in entries:
        filepath = os.path.join(PATTERNS_DIR, f"{entry['id']}.txt")
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        if "## Annotation" not in content:
            unannotated.append(entry)
            if len(unannotated) >= limit:
                break

    return unannotated


def get_pattern(pattern_id):
    """Read a specific pattern file's full text."""
    filepath = os.path.join(PATTERNS_DIR, f"{pattern_id}.txt")
    if not os.path.exists(filepath):
        return {"error": f"Pattern not found: {pattern_id}"}
    with open(filepath, encoding="utf-8") as f:
        return {"id": pattern_id, "content": f.read()}


def annotate_pattern(pattern_id, summary):
    """Append an ## Annotation section to a pattern file."""
    filepath = os.path.join(PATTERNS_DIR, f"{pattern_id}.txt")
    if not os.path.exists(filepath):
        return {"error": f"Pattern not found: {pattern_id}"}
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    if "## Annotation" in content:
        return {"error": f"Pattern {pattern_id} is already annotated"}
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n\n## Annotation\n{summary}\n")
    return {"status": "ok", "id": pattern_id}


def get_progress():
    """Return annotation progress counts."""
    if not os.path.exists(INDEX_PATH):
        return {"annotated": 0, "total": 0, "percent": 0.0}

    with open(INDEX_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    annotated = 0
    total = len(entries)
    for entry in entries:
        filepath = os.path.join(PATTERNS_DIR, f"{entry['id']}.txt")
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding="utf-8") as f:
            if "## Annotation" in f.read():
                annotated += 1

    percent = (annotated / total * 100) if total > 0 else 0.0
    return {"annotated": annotated, "total": total, "percent": round(percent, 1)}


def cmd_list(args):
    result = list_unannotated(limit=args.limit)
    if isinstance(result, dict) and "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"Unannotated patterns ({len(result)}):\n")
    for entry in result:
        print(f"  {entry['id']}  ({entry.get('type', '?')}, {entry.get('node_count', '?')} nodes)")


def cmd_get(args):
    result = get_pattern(args.pattern_id)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(result["content"])


def cmd_annotate(args):
    result = annotate_pattern(args.pattern_id, args.summary)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"Annotated: {args.pattern_id}")


def cmd_progress(args):
    result = get_progress()
    print(f"Annotated: {result['annotated']}/{result['total']} ({result['percent']}%)")


def main():
    parser = argparse.ArgumentParser(description="Annotate extracted Houdini patterns")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List unannotated patterns")
    list_parser.add_argument("--limit", type=int, default=20, help="Max patterns to show")

    get_parser = subparsers.add_parser("get", help="View a pattern")
    get_parser.add_argument("pattern_id", help="Pattern ID to view")

    annot_parser = subparsers.add_parser("annotate", help="Annotate a pattern")
    annot_parser.add_argument("pattern_id", help="Pattern ID to annotate")
    annot_parser.add_argument("summary", help="Annotation summary text")

    subparsers.add_parser("progress", help="Show annotation progress")

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "get": cmd_get,
        "annotate": cmd_annotate,
        "progress": cmd_progress,
    }
    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
