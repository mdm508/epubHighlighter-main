# endict.py
import os
import re
import pystardict
import spacy

# spaCy REQUIRED
try:
    _SPACY_NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])
except OSError as e:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' is required but not installed. "
        "Run: python -m spacy download en_core_web_sm"
    ) from e


class StarDictWrapper:
    """
    - loads ALL .ifo dicts from PROJECT_DICT_DIR (recursively), in sorted order
    - looks up a word in all of them
    - turns weird stardict markup into HTML
    - **sanitizes inline styles** so we don’t get huge vertical borders in the EPUB
    - returns ALL matching defs as one HTML string
    """

    # change this to your actual folder with multiple dicts
    PROJECT_DICT_DIR = r"C:\Users\metta\Downloads\epubHighlighter-main\dicts"

    # very light xml-ish to html-ish
    XML_TO_HTML_MAP = [
        (re.compile(r"<k>(.*?)</k>", re.DOTALL), r"<h3>\1</h3>"),
    ]

    # regex to find style="...":
    STYLE_ATTR_RE = re.compile(r'style="([^"]*)"')

    def __init__(self):
        self.nlp = _SPACY_NLP
        self.dicts = self._load_all_dicts()

    # ---------------------------------------------------------
    # loading
    # ---------------------------------------------------------
    def _load_all_dicts(self):
        loaded = []
        root_dir = self.PROJECT_DICT_DIR

        if not os.path.isdir(root_dir):
            print(f"[StarDictWrapper] dict folder not found: {root_dir}")
            return loaded

        for root, dirs, files in os.walk(root_dir):
            dirs.sort()
            for fname in sorted(files):
                if not fname.lower().endswith(".ifo"):
                    continue
                base_path = os.path.join(root, fname[:-4])  # strip .ifo
                try:
                    d = pystardict.Dictionary(base_path)
                    loaded.append(d)
                    print(f"[StarDictWrapper] loaded dict: {base_path}")
                except Exception as e:
                    print(f"[StarDictWrapper] failed to load {base_path}: {e}")

        if not loaded:
            print("[StarDictWrapper] WARNING: no dictionaries loaded.")
        return loaded

    # ---------------------------------------------------------
    # text helpers
    # ---------------------------------------------------------
    def _lemmatize(self, word: str) -> str:
        doc = self.nlp(word)
        if doc and len(doc) > 0:
            return doc[0].lemma_.lower()
        return word.lower()

    def _convert_xml_to_html(self, text: str) -> str:
        for pattern, replacement in self.XML_TO_HTML_MAP:
            text = pattern.sub(replacement, text)
        return text

    # ---------------------------------------------------------
    # style sanitizer
    # ---------------------------------------------------------
    def _sanitize_styles(self, html: str) -> str:
        """
        Remove inline stuff that causes the tall grey bars / vertical text:
        - any writing-mode
        - any border-*
        We do it with a regexy pass so we don’t need BeautifulSoup here.
        """
        def _clean_style(match: re.Match) -> str:
            style_val = match.group(1)
            # split into declarations
            parts = [p.strip() for p in style_val.split(";") if p.strip()]
            cleaned = []
            for p in parts:
                lower = p.lower()
                if "writing-mode" in lower:
                    continue
                if lower.startswith("border"):
                    continue
                # sometimes dicts use "border-left" in middle
                if "border-left" in lower or "border-right" in lower:
                    continue
                cleaned.append(p)
            if not cleaned:
                return ""  # drop the whole style=""
            return 'style="' + "; ".join(cleaned) + '"'

        sanitized = self.STYLE_ATTR_RE.sub(_clean_style, html)
        return sanitized

    # ---------------------------------------------------------
    # lookup helpers
    # ---------------------------------------------------------
    def _collect_from_all(self, key: str) -> list[str]:
        out = []
        for d in self.dicts:
            val = d.get(key, "")
            if val:
                out.append(val)
        return out

    def _candidate_keys(self, word: str) -> list[str]:
        word_l = word.lower()
        candidates = []

        # spaCy lemma
        lemma = self._lemmatize(word)
        candidates.append(lemma)

        # lower
        candidates.append(word_l)

        # original
        candidates.append(word)

        # cheap plural fallbacks
        if word_l.endswith("ies"):
            candidates.append(word_l[:-3] + "y")
        if word_l.endswith("es"):
            candidates.append(word_l[:-2])
        if word_l.endswith("s"):
            candidates.append(word_l[:-1])

        seen = set()
        ordered = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                ordered.append(c)
        return ordered

    # ---------------------------------------------------------
    # public API
    # ---------------------------------------------------------
    def get_def(self, word: str) -> str:
        if not self.dicts:
            return ""

        raw_defs: list[str] = []
        for key in self._candidate_keys(word):
            defs_for_key = self._collect_from_all(key)
            if defs_for_key:
                raw_defs.extend(defs_for_key)

        if not raw_defs:
            return ""

        html_blocks = []
        for raw in raw_defs:
            converted = self._convert_xml_to_html(raw)
            sanitized = self._sanitize_styles(converted)
            block = (
                '<div class="dict-block" '
                'style="margin:0 0 .5em 0; padding:0.35em 0.6em; border-left:0;">'
                f'{sanitized}'
                '</div>'
            )
            html_blocks.append(block)

        # separate multiple dictionaries with a horizontal divider
        return '<div style="border-top:1px solid #eee; margin:0.5em 0;"></div>'.join(html_blocks)

    def __getitem__(self, word: str) -> str:
        return self.get_def(word)
