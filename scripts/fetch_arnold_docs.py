#!/usr/bin/env python
"""
Fetch the Arnold core and Arnold for Houdini (HtoA) user guides from
help.autodesk.com and build a separate BM25 index for them.

Usage:
    python scripts/fetch_arnold_docs.py             # fetch pages + index
    python scripts/fetch_arnold_docs.py --no-index  # fetch pages only

Autodesk publishes no offline Arnold manual, so each page is fetched from its
static HTML, listed in the help site's toctree.json. There is a 6-second delay
between requests: a full run takes about two hours. A rerun skips pages that
are already converted, so an interrupted run resumes where it stopped.

Pages go to arnold_docs/<book>/ as markdown and the index to
arnold_docs_index.json. The pages are © Autodesk, Inc. under CC BY-NC-SA 3.0:
neither output is committed to the repo (see .gitignore).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from html_to_markdown import html_to_markdown

HOST = "https://help.autodesk.com"
TOCTREE_URL = f"{HOST}/view/ARNOL/ENU/data/toctree.json"
BOOKS = ("AR-Core", "AR-Houdini")
REQUEST_DELAY = 6.0  # seconds between requests to the same host
USER_AGENT = "Mozilla/5.0 (houdini-mcp fetch_arnold_docs)"
LICENSE = "© Autodesk, Inc. — CC BY-NC-SA 3.0 (https://creativecommons.org/licenses/by-nc-sa/3.0/)"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DOCS_DIR = os.path.join(REPO_ROOT, "arnold_docs")
INDEX_PATH = os.path.join(REPO_ROOT, "arnold_docs_index.json")


def get(url, attempts=3):
    """GET a page, retrying transient network errors (a two-hour run meets some)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError:
            raise  # the server answered; retrying will not change it
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == attempts:
                raise
            print(f"  retry {attempt}/{attempts - 1} after {e}: {url}", flush=True)
            time.sleep(REQUEST_DELAY * 5 * attempt)


def list_pages(toctree):
    """Return {link: (book, page id)} for every page in BOOKS."""
    pages = {}

    def walk(node):
        link = node.get("ln")
        if link and link.split("/")[3] in BOOKS:
            pages[link] = (link.split("/")[3], node["id"])
        for child in node.get("children", []):
            walk(child)

    for book in toctree["books"]:
        walk(book)
    return pages


def page_path(book, page_id):
    return os.path.join(DOCS_DIR, book, page_id + ".md")


def fetch_pages():
    pages = list_pages(json.loads(get(TOCTREE_URL)))
    todo = {link: bp for link, bp in pages.items() if not os.path.exists(page_path(*bp))}
    print(f"{len(pages)} pages in {', '.join(BOOKS)}; {len(todo)} to fetch "
          f"(~{len(todo) * REQUEST_DELAY / 60:.0f} min)")
    for i, (link, (book, page_id)) in enumerate(sorted(todo.items()), 1):
        time.sleep(REQUEST_DELAY)
        url = HOST + link
        body = html_to_markdown(get(url), "body-content", {"related-links"})
        os.makedirs(os.path.join(DOCS_DIR, book), exist_ok=True)
        with open(page_path(book, page_id), "w", encoding="utf-8") as f:
            f.write(f"Source: {url}\n{LICENSE}\n\n{body}\n")
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} fetched", flush=True)


def build_index():
    sys.path.insert(0, REPO_ROOT)
    from houdini_rag import build_index as _build

    _build(docs_dir=DOCS_DIR, output_path=INDEX_PATH)
    size_mb = os.path.getsize(INDEX_PATH) / (1024 * 1024)
    print(f"Index built: {INDEX_PATH} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-index", action="store_true", help="fetch pages only")
    args = parser.parse_args()

    fetch_pages()
    if not args.no_index:
        build_index()
    print("Done.")


if __name__ == "__main__":
    main()
