#!/usr/bin/env python
"""
Fetch the Redshift for Houdini manual from Maxon's official offline help ZIP
and build a separate BM25 index for it.

Usage:
    python scripts/fetch_redshift_docs.py                # download ZIP + convert + index
    python scripts/fetch_redshift_docs.py --zip PATH     # use a ZIP already on disk
    python scripts/fetch_redshift_docs.py --no-index     # convert only

The ZIP is listed on https://www.maxon.net/en/downloads ("Redshift Offline Help",
Houdini). It is about 2.7 GB, almost all images and video; only the HTML pages
are read. Pages go to redshift_docs/ as markdown and the index to
redshift_docs_index.json. The manual is © MAXON Computer: neither output is
committed to the repo (see .gitignore).
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

from html_to_markdown import html_to_markdown

DOWNLOADS_PAGE = "https://www.maxon.net/en/downloads"
ZIP_URL_RE = re.compile(r"https://help\.maxon\.net/download/[^\"'\s]*_houdini_en-us_offline_help\.zip")
ONLINE_BASE = "https://help.maxon.net/r3d/houdini/en-us/Content/html/"
USER_AGENT = "Mozilla/5.0 (houdini-mcp fetch_redshift_docs)"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DOCS_DIR = os.path.join(REPO_ROOT, "redshift_docs")
INDEX_PATH = os.path.join(REPO_ROOT, "redshift_docs_index.json")


def find_zip_url():
    """Read the current Houdini offline help ZIP URL from Maxon's downloads page."""
    req = urllib.request.Request(DOWNLOADS_PAGE, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    urls = sorted(set(ZIP_URL_RE.findall(page)))
    if not urls:
        raise RuntimeError(f"No Redshift Houdini offline help ZIP link found on {DOWNLOADS_PAGE}")
    return urls[-1]  # file names start with the build date, so the last is newest


def download(url, dest):
    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    print(f"Downloaded {os.path.getsize(dest) / 1e9:.2f} GB")


def convert_zip(zip_path):
    """Write one markdown file per manual page into DOCS_DIR."""
    os.makedirs(DOCS_DIR)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if "/Content/html/" not in name or not name.endswith(".html"):
                continue
            filename = name.rsplit("/", 1)[1]
            body = html_to_markdown(zf.read(name).decode("utf-8"), "mc-main-content", {"nocontent"})
            header = f"Source: {ONLINE_BASE}{filename}\n© MAXON Computer\n\n"
            out_name = filename[: -len(".html")].replace("+", "_") + ".md"
            with open(os.path.join(DOCS_DIR, out_name), "w", encoding="utf-8") as f:
                f.write(header + body + "\n")
            count += 1
    print(f"Converted {count} pages to {DOCS_DIR}")


def build_index():
    sys.path.insert(0, REPO_ROOT)
    from houdini_rag import build_index as _build

    _build(docs_dir=DOCS_DIR, output_path=INDEX_PATH)
    size_mb = os.path.getsize(INDEX_PATH) / (1024 * 1024)
    print(f"Index built: {INDEX_PATH} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", help="use this offline help ZIP instead of downloading it")
    parser.add_argument("--no-index", action="store_true", help="convert pages only")
    args = parser.parse_args()

    if os.path.exists(DOCS_DIR):
        print(f"Docs already exist at {DOCS_DIR} — remove to re-fetch.")
    elif args.zip:
        convert_zip(args.zip)
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "redshift_offline_help.zip")
            download(find_zip_url(), zip_path)
            convert_zip(zip_path)

    if not args.no_index:
        build_index()
    print("Done.")


if __name__ == "__main__":
    main()
