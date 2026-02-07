"""
Houdini Documentation Search (BM25)
====================================
Offline BM25-based retrieval for Houdini documentation.
No external dependencies — uses only Python standard library.

Based on: https://github.com/orrzxz/Houdini21MCP
"""

import os
import re
import json
import math
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DOCS_DIR = Path(os.environ.get("HOUDINIMCP_DOCS_DIR", SCRIPT_DIR / "houdini_docs"))
INDEX_PATH = Path(os.environ.get("HOUDINIMCP_DOCS_INDEX", SCRIPT_DIR / "houdini_docs_index.json"))


class HoudiniTokenizer:
    """Tokenizer optimized for Houdini documentation.
    Preserves hou.* calls, node paths, and underscore compounds."""

    STOPWORDS = {
        'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'this', 'that', 'these', 'those', 'it', 'its', 'you', 'your', 'we',
        'our', 'they', 'their', 'he', 'she', 'his', 'her', 'if', 'then',
        'else', 'when', 'where', 'which', 'what', 'who', 'how', 'why',
        'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
        'some', 'such', 'no', 'not', 'only', 'same', 'so', 'than', 'too',
        'very', 'just', 'also', 'now', 'here', 'there', 'any', 'many'
    }

    def tokenize(self, text):
        text = text.lower()
        preserved = []

        # hou.node, hou.parm, etc.
        for match in re.finditer(r'hou\.\w+(?:\(\))?', text):
            preserved.append(match.group())

        # Node paths: /obj/geo1, /mat/shader
        for match in re.finditer(r'/\w+(?:/\w+)+', text):
            preserved.append(match.group())

        # Underscore compounds: mtlxstandard_surface
        for match in re.finditer(r'\w+_\w+(?:_\w+)*', text):
            preserved.append(match.group())

        # General tokenization
        tokens = re.findall(r'[a-z0-9_]+', text)
        tokens.extend(preserved)

        return [t for t in tokens if t not in self.STOPWORDS and len(t) > 1]


class BM25Index:
    """BM25 (Best Matching 25) implementation for document retrieval."""

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.tokenizer = HoudiniTokenizer()
        self.documents = []
        self.doc_freqs = []
        self.doc_lens = []
        self.avgdl = 0
        self.idf = {}
        self.term_docs = {}

    def add_document(self, path, title, content):
        tokens = self.tokenizer.tokenize(content)
        doc_freq = Counter(tokens)
        doc_idx = len(self.documents)
        self.documents.append({
            'path': str(path),
            'title': title,
            'content': content[:500],
        })
        self.doc_freqs.append(doc_freq)
        self.doc_lens.append(len(tokens))

        for term in doc_freq:
            if term not in self.term_docs:
                self.term_docs[term] = []
            self.term_docs[term].append(doc_idx)

    def build(self):
        n = len(self.documents)
        if n == 0:
            return
        self.avgdl = sum(self.doc_lens) / n
        self.idf = {}
        for term, doc_indices in self.term_docs.items():
            df = len(doc_indices)
            self.idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query, top_k=5):
        query_tokens = self.tokenizer.tokenize(query)
        if not query_tokens:
            return []

        candidate_docs = set()
        for term in query_tokens:
            if term in self.term_docs:
                candidate_docs.update(self.term_docs[term])

        if not candidate_docs:
            return []

        scores = []
        for doc_idx in candidate_docs:
            score = self._score_document(doc_idx, query_tokens)
            if score > 0:
                scores.append((doc_idx, score))

        scores.sort(key=lambda x: -x[1])

        results = []
        for doc_idx, score in scores[:top_k]:
            doc = self.documents[doc_idx]
            results.append({
                'path': doc['path'],
                'title': doc['title'],
                'preview': doc['content'],
                'score': round(score, 3)
            })
        return results

    def _score_document(self, doc_idx, query_tokens):
        score = 0
        doc_freq = self.doc_freqs[doc_idx]
        dl = self.doc_lens[doc_idx]

        for term in query_tokens:
            if term not in doc_freq:
                continue
            tf = doc_freq[term]
            idf = self.idf.get(term, 0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * (numerator / denominator)
        return score

    def save(self, path=None):
        path = Path(path) if path else INDEX_PATH
        data = {
            'k1': self.k1,
            'b': self.b,
            'documents': self.documents,
            'doc_freqs': [dict(df) for df in self.doc_freqs],
            'doc_lens': self.doc_lens,
            'avgdl': self.avgdl,
            'idf': self.idf,
            'term_docs': self.term_docs,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path else INDEX_PATH
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        index = cls(k1=data['k1'], b=data['b'])
        index.documents = data['documents']
        index.doc_freqs = [Counter(df) for df in data['doc_freqs']]
        index.doc_lens = data['doc_lens']
        index.avgdl = data['avgdl']
        index.idf = data['idf']
        index.term_docs = data['term_docs']
        return index


class DocumentLoader:
    """Load and parse Houdini documentation markdown files."""

    def __init__(self, docs_dir=None):
        self.docs_dir = Path(docs_dir) if docs_dir else DOCS_DIR

    def extract_title(self, content, filepath):
        match = re.search(r'^=\s*(.+?)\s*=', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return filepath.stem.replace('_', ' ').title()

    def clean_content(self, content):
        content = re.sub(r'^#\w+:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r':\w+:', ' ', content)
        content = re.sub(r'\[Icon:[^\]]+\]', '', content)
        content = re.sub(r'\(\([^\)]+\)\)', '', content)
        content = re.sub(r'\[([^\]]+)\]\|[^\]]+\]', r'\1', content)
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        content = re.sub(r'```\w*\n?', '', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        return content.strip()

    def load_all(self):
        documents = []
        for filepath in self.docs_dir.rglob('*.md'):
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                title = self.extract_title(content, filepath)
                cleaned = self.clean_content(content)
                rel_path = filepath.relative_to(self.docs_dir)
                documents.append({
                    'path': str(rel_path),
                    'title': title,
                    'content': cleaned,
                })
            except Exception as e:
                print(f"Error loading {filepath}: {e}")
        return documents


def build_index(docs_dir=None, output_path=None):
    """Build the BM25 index from documentation files."""
    loader = DocumentLoader(docs_dir)
    documents = loader.load_all()

    index = BM25Index()
    for doc in documents:
        index.add_document(doc['path'], doc['title'], doc['content'])
    index.build()
    index.save(output_path)
    return index


# Global index instance (loaded on demand)
_index = None

def get_index():
    """Get or load the global index instance."""
    global _index
    if _index is None:
        _index = BM25Index.load()
        if _index is None:
            if DOCS_DIR.exists():
                _index = build_index()
    return _index


def search_docs(query, top_k=5):
    """Search Houdini documentation. Returns list of {path, title, preview, score}."""
    index = get_index()
    if index is None:
        return {"error": "Docs index not available. Run: python scripts/fetch_houdini_docs.py"}
    return index.search(query, top_k)


def get_doc_content(doc_path):
    """Get full content of a specific document by relative path."""
    full_path = DOCS_DIR / doc_path
    if not full_path.exists():
        return {"error": f"Document not found: {doc_path}"}
    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    return {"path": doc_path, "content": content}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_index()
        print("Index built.")
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        query = " ".join(sys.argv[2:])
        results = search_docs(query)
        if isinstance(results, dict) and "error" in results:
            print(results["error"])
        else:
            for r in results:
                print(f"\n[{r['score']}] {r['title']}")
                print(f"    {r['path']}")
                print(f"    {r['preview'][:100]}...")
    else:
        print("Usage:")
        print("  python houdini_rag.py build          - Build index from docs")
        print("  python houdini_rag.py search <query> - Search docs")
