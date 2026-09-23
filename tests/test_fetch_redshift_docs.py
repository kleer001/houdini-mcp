"""Tests for scripts/fetch_redshift_docs.py HTML-to-markdown conversion."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from fetch_redshift_docs import html_to_markdown, ZIP_URL_RE  # noqa: E402

PAGE = """<html><head><title>T</title><script>var x = 1;</script></head><body>
<nav><ul><li><a href="Other.html">Other page</a></li></ul></nav>
<div class="main-content">
  <div role="main" id="mc-main-content">
    <div class="nocontent"><div class="breadcrumbs">You are here: </div></div>
    <h1 id="title-text">Redshift ROP Node</h1>
    <h2>Main Tab</h2>
    <p>The core of the   plugin is the <em>ROP</em> node.</p>
    <p><br /></p>
    <p><img src="../Resources/Images/a.jpg" /></p>
    <ul><li>Frame range</li><li>Takes</li></ul>
    <pre>rsProxy -f file.rs</pre>
    <p>Use <code>$AOV</code> in the name.</p>
  </div>
  <div class="buttons nocontent"></div>
</div>
<nav id="quick-float-nav"><a href="#top">Back to top</a></nav>
<div class="fixed-footer"><a href="https://www.maxon.net/en/legal">Impressum</a></div>
</body></html>"""


def test_keeps_only_main_content():
    md = html_to_markdown(PAGE)
    assert "Other page" not in md
    assert "You are here" not in md
    assert "Back to top" not in md
    assert "Impressum" not in md
    assert "var x" not in md


def test_structure():
    md = html_to_markdown(PAGE)
    assert md.startswith("# Redshift ROP Node")
    assert "\n## Main Tab\n" in md
    assert "The core of the plugin is the ROP node." in md
    assert "\n- Frame range\n- Takes" in md
    assert "```\nrsProxy -f file.rs\n```" in md
    assert "Use `$AOV` in the name." in md
    assert "\n\n\n" not in md


def test_zip_url_pattern():
    page = ('<a href="https://help.maxon.net/download/20260907_2026.9_houdini_en-us_offline_help.zip">'
            '<a href="https://help.maxon.net/download/20260907_2026.9_maya_en-us_offline_help.zip">')
    assert ZIP_URL_RE.findall(page) == [
        "https://help.maxon.net/download/20260907_2026.9_houdini_en-us_offline_help.zip",
    ]
