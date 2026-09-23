"""
Convert the main content of a documentation HTML page to markdown (stdlib only).

Vendor help pages repeat site navigation on every page; only the subtree of
the element with a given id is kept, minus elements whose class marks them as
chrome (breadcrumbs, toolbars, related links).
"""

import re
from html.parser import HTMLParser

HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
BLOCKS = {"p", "div", "ul", "ol", "table", "tr", "blockquote", "details", "summary"}
SKIPPED = {"script", "style", "img", "svg", "video", "iframe"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "col"}


class MainContentToMarkdown(HTMLParser):
    """Emit markdown for the element with id `root_id`, skipping `skip_classes`."""

    def __init__(self, root_id, skip_classes):
        super().__init__(convert_charrefs=True)
        self.root_id = root_id
        self.skip_classes = set(skip_classes)
        self.out = []
        self.depth = 0          # open elements inside the main div; 0 = outside
        self.skip_depth = 0     # >0 while inside a skipped subtree
        self.in_pre = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.depth == 0:
            if attrs.get("id") == self.root_id:
                self.depth = 1
            return
        if tag not in VOID:
            self.depth += 1
        if self.skip_depth:
            if tag not in VOID:
                self.skip_depth += 1
            return
        if tag in SKIPPED or self.skip_classes & set((attrs.get("class") or "").split()):
            if tag not in VOID:
                self.skip_depth = 1
            return
        if tag in HEADINGS:
            self.out.append(f"\n\n{HEADINGS[tag]} ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag == "pre":
            self.in_pre = True
            self.out.append("\n\n```\n")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        elif tag == "br":
            self.out.append("\n")
        elif tag in BLOCKS:
            self.out.append("\n\n")

    def handle_endtag(self, tag):
        if self.depth == 0 or tag in VOID:
            return
        self.depth -= 1
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in HEADINGS or tag in BLOCKS:
            self.out.append("\n\n")
        elif tag == "pre":
            self.in_pre = False
            self.out.append("\n```\n\n")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")

    def handle_data(self, data):
        if self.depth == 0 or self.skip_depth:
            return
        self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))

    def markdown(self):
        text = "".join(self.out)
        text = re.sub(r"(?m)^[ \t|]*$", "", text)  # table rows emptied by dropped images
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+(?=\S)", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html, root_id, skip_classes=()):
    parser = MainContentToMarkdown(root_id, skip_classes)
    parser.feed(html)
    parser.close()
    return parser.markdown()
