import re
import os
import subprocess
import shutil
import zipfile
import posixpath
from xml.dom import minidom
from html import unescape
from typing import List

import ebooklib
from ebooklib import epub

from wordfreq import zipf_frequency
from endict import StarDictWrapper  # your multi-dict loader

# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------
GENERATE_HIGHLIGHTED_EPUB = True
GENERATE_DEFS_EPUB = True
GENERATE_ANKI = True
CONVERT_EPUBS_TO_PDF = False  # keep off while testing

# build the rare-word list automatically from the EPUB before doing anything else
AUTO_BUILD_WORD_LIST = True
AUTO_WORDLIST_FREQ_THRESHOLD = 2.7
AUTO_WORDLIST_OUTPUT = "./epub/infj-rare-words-auto.txt"

# if AUTO_BUILD_WORD_LIST = False, we use this one:
WORD_LIST_PATH = "epub/infj-rare-words.txt"

# no need to filter short words
WORD_INCLUSION_MIN_LEN = 1

# test mode: stop after this many (word,def) entries
TEST_MODE = False
TEST_MAX_DEFS = 100
# ----------------------------------------------------

EPUB_PATH = "./input/infj.epub"
OUTPUT_EPUB_PATH = "./epub/infj-highlighted.epub"
OUTPUT_DEFS_EPUB_PATH = "./epub/infj-definitions.epub"
OUTPUT_ANKI_PATH = "./epub/infj-defs-anki.tsv"
OUTPUT_EPUB_PDF_PATH = "./epub/infj-highlighted.pdf"
OUTPUT_DEFS_PDF_PATH = "./epub/infj-definitions.pdf"

CHAPTER_PATTERN = r'Year\s*(\d+)'
WORD_SEEN_MAX = 1

import spacy
try:
    _NLP = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    # add a light sentence segmenter since we disabled the parser
    if "sentencizer" not in _NLP.pipe_names:
        _NLP.add_pipe("sentencizer")
except OSError as e:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' is required but not installed. "
        "Run: python -m spacy download en_core_web_sm"
    ) from e



# ====================================================
# PART 1: rare-word extractor
# ====================================================
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _read_container_from_zip(zf: zipfile.ZipFile) -> str:
    container_xml = zf.read("META-INF/container.xml").decode("utf-8")
    dom = minidom.parseString(container_xml)
    for el in dom.getElementsByTagName("rootfile"):
        if el.getAttribute("media-type") == "application/oebps-package+xml":
            return el.getAttribute("full-path")
    raise ValueError("No OPF path found in container.xml")


def _get_content_files_from_opf(zf: zipfile.ZipFile, opf_path: str) -> List[str]:
    opf_xml = zf.read(opf_path).decode("utf-8")
    dom = minidom.parseString(opf_xml)
    base_dir = posixpath.dirname(opf_path)
    items = []
    for item in dom.getElementsByTagName("item"):
        media_type = item.getAttribute("media-type")
        if media_type in ("application/xhtml+xml", "application/x-dtbook+xml", "text/html"):
            href = item.getAttribute("href")
            full_path = posixpath.normpath(posixpath.join(base_dir, href))
            items.append(full_path)
    return items


def _extract_textish(html_str: str) -> str:
    html_str = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        html_str,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", " ", html_str)
    text = unescape(text)
    return text


def build_rare_word_list_from_epub(
    epub_path: str,
    output_path: str,
    freq_threshold: float = 4.5,
) -> str:
    print(f"[AUTO] Building rare-word list from {epub_path} with threshold {freq_threshold} ...")
    with zipfile.ZipFile(epub_path, "r") as zf:
        opf_path = _read_container_from_zip(zf)
        content_paths = _get_content_files_from_opf(zf, opf_path)

        seen = set()
        ordered_rare_words = []

        for rel_path in content_paths:
            rel_path_zip = rel_path.replace("\\", "/")
            if rel_path_zip not in zf.namelist():
                continue

            raw_html = zf.read(rel_path_zip).decode("utf-8", errors="ignore")
            text = _extract_textish(raw_html)

            for m in WORD_RE.finditer(text):
                word_original = m.group(0)
                word_lower = word_original.lower()

                # frequency filter using wordfreq
                if zipf_frequency(word_lower, "en") >= freq_threshold:
                    continue

                if word_lower not in seen:
                    seen.add(word_lower)
                    ordered_rare_words.append(word_original)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for w in ordered_rare_words:
            f.write(w + "\n")

    print(f"[AUTO] Wrote {len(ordered_rare_words)} rare words to {output_path}")
    return output_path


# ====================================================
# PART 2: highlighting helpers
# ====================================================

def normalize_name(name: str) -> str:
    return name.replace("\\", "/").split("/")[-1]


def build_toc_title_map(book: epub.EpubBook) -> dict[str, str]:
    title_map: dict[str, str] = {}

    def _walk(toc_items):
        for entry in toc_items:
            if isinstance(entry, epub.Link):
                href = entry.href.split("#")[0]
                title_map[normalize_name(href)] = entry.title
            elif isinstance(entry, epub.Section):
                _walk(entry.subitems)
            else:
                fname = getattr(entry, "file_name", None)
                title = getattr(entry, "title", None)
                if fname and title:
                    title_map[normalize_name(fname)] = title

    _walk(book.toc)
    return title_map


def read_words_into_dictionary(list_path: str) -> dict[str, int]:
    print(f"[1/8] Loading word list from {list_path} ...")
    with open(list_path, 'r', encoding="utf-8") as file:
        words = [line.strip() for line in file.read().splitlines() if line.strip()]
    d = {w.lower(): 0 for w in words}
    print(f"[1/8] Loaded {len(d)} words to match.")
    return d


def highlight_content(body_content: str, words_to_replace: set[str]) -> str:
    if not words_to_replace:
        return body_content
    pattern = r'(' + '|'.join(re.escape(word) for word in words_to_replace) + r')'
    return re.sub(pattern, lambda m: f'<b>{m.group(0)}</b>', body_content, flags=re.IGNORECASE)


def discover_section_title(filename: str, body_content: str, toc_map: dict[str, str]) -> str:
    norm = normalize_name(filename)
    if norm in toc_map:
        return toc_map[norm]

    m = re.search(CHAPTER_PATTERN, body_content)
    if m:
        if m.lastindex:
            return m.group(1)
        else:
            return m.group(0)

    return os.path.splitext(norm)[0]


def build_glossary_section(
    d: StarDictWrapper,
    matched_words: list[str],
    section_title: str,
    def_cache: dict[str, str],
    context_map: dict[str, str],
) -> str:
    section_html = f'''
    <section style="margin-bottom: 0; padding: 0;">
        <h2 style="text-align: center; font-size: 1.5em; margin: 0; padding: 0;">Glossary {section_title}</h2>
    </section>
    '''
    for word in matched_words:
        if word in def_cache:
            definition = def_cache[word]
        else:
            definition = d.get_def(word)
            def_cache[word] = definition

        sentence = context_map.get(word, "")
        if sentence:
            section_html += f'<p style="font-style:italic; margin:0.25em 0 0.4em 0;">{sentence}</p>'

        if not definition:
            section_html += f'<div class="dict-entry" style="margin:0.35em 0;"><h3>{word}</h3></div>'
        else:
            section_html += (
                '<div class="dict-entry" style="margin:0.35em 0;">'
                f'{definition}'
                '</div>'
            )
    section_html += "</section>"
    return section_html


def count_matches_delete_frequent(d: dict[str, int], matched_words: list[str]) -> None:
    for m in matched_words:
        if m in d:
            d[m] += 1
            if d[m] >= WORD_SEEN_MAX:
                del d[m]


def get_matched_words_with_context(
    body_content: str,
    words_to_match: dict[str, int],
    min_len: int
) -> tuple[list[str], dict[str, str]]:
    """
    Returns (matched_words_sorted, context_map)
    context_map[word] = original sentence (first time we see it)
    """
    text_no_tags = re.sub(r"<[^>]+>", " ", body_content)
    doc = _NLP(text_no_tags)

    matched = []
    context: dict[str, str] = {}
    seen = set()

    for sent in doc.sents:
        sent_text = sent.text.strip()
        for tok in sent:
            tok_l = tok.text.lower()
            if tok_l in words_to_match and len(tok_l) >= min_len:
                if tok_l not in seen:
                    seen.add(tok_l)
                    matched.append(tok_l)
                    context[tok_l] = sent_text

    matched.sort()
    return matched, context


def simplify_html_for_defs(html: str) -> str:
    """
    Try to turn dictionary HTML into simple, safe HTML.
    If we end up with almost nothing, fall back to plain text extracted
    from the original HTML.
    """
    if not html:
        return ""

    original_html = html

    # 1) remove inline style attributes
    html = re.sub(r'\s*style="[^"]*"', "", html, flags=re.IGNORECASE)

    # 2) normalize <br>
    html = re.sub(r"<br\s*/?>", "<br>", html, flags=re.IGNORECASE)

    # 3) strip container-ish tags that often carry weird layout
    html = re.sub(r"</?(div|section|article|blockquote)[^>]*>", "", html, flags=re.IGNORECASE)

    # 4) h1-h6 -> <p><b>...</b></p>
    def _h_to_p(match: re.Match) -> str:
        inner = match.group(1)
        return f"<p><b>{inner}</b></p>"

    html = re.sub(
        r"<h[1-6][^>]*>(.*?)</h[1-6]>",
        _h_to_p,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # allow only a small set of tags, but preserve text
    placeholders = {
        "<p>": "___P_OPEN___",
        "</p>": "___P_CLOSE___",
        "<b>": "___B_OPEN___",
        "</b>": "___B_CLOSE___",
        "<br>": "___BR___",
        "<i>": "___I_OPEN___",
        "</i>": "___I_CLOSE___",
        "<em>": "___EM_OPEN___",
        "</em>": "___EM_CLOSE___",
    }
    for real, ph in placeholders.items():
        html = html.replace(real, ph)

    # strip every other tag
    html = re.sub(r"</?[^>]+>", "", html)

    # restore our allowed tags
    for real, ph in placeholders.items():
        html = html.replace(ph, real)

    # tidy
    html = re.sub(r"\n\s*\n", "\n", html).strip()

    # if we lost everything / just <p></p> then fallback to plain text
    def _is_effectively_empty(s: str) -> bool:
        s2 = re.sub(r"<[^>]+>", "", s).strip()
        return len(s2) == 0

    if _is_effectively_empty(html):
        # fallback: strip ALL tags from original
        text_only = re.sub(r"<[^>]+>", " ", original_html)
        text_only = re.sub(r"\s+", " ", text_only).strip()
        if text_only:
            return f"<p>{text_only}</p>"
        else:
            return ""

    if not html.lower().startswith("<p"):
        html = f"<p>{html}</p>"

    return html



def write_definitions_epub_from_wordlist(
    all_entries: list[tuple[str, str, str]],
    output_path: str,
    chunk_size: int = 50
) -> None:
    """
    all_entries: list of (word, def_html, sentence)
    """
    print(f"[6/8] Building definitions-only EPUB ({len(all_entries)} words total) ...")

    defs_book = epub.EpubBook()
    defs_book.set_identifier("defs-only-epub")
    defs_book.set_title("Definitions")
    defs_book.set_language("en")

    spine = ["nav"]
    toc = []

    NORMALIZE_STYLE = """
    <style>
      .dict-entry { margin: 0.4em 0 0.6em 0; }
      .dict-entry p { margin: 0.2em 0; }
      .context { font-style: italic; margin: 0.25em 0 0.4em 0; }
    </style>
    """

    current_chunk_found: list[tuple[str, str, str]] = []
    current_chunk_missing: list[str] = []
    chunk_index = 1

    def flush_chunk():
        nonlocal chunk_index, current_chunk_found, current_chunk_missing
        if not current_chunk_found and not current_chunk_missing:
            return

        first_word = (current_chunk_found[0][0]
                      if current_chunk_found
                      else (current_chunk_missing[0] if current_chunk_missing else f"Chunk {chunk_index}"))
        last_word = (current_chunk_found[-1][0]
                     if current_chunk_found
                     else (current_chunk_missing[-1] if current_chunk_missing else first_word))

        chunk_title = f"{first_word} – {last_word}"
        file_name = f"defs_{chunk_index}.xhtml"
        page = epub.EpubHtml(title=chunk_title, file_name=file_name, lang="en")

        html_parts = [NORMALIZE_STYLE, f"<h2>{chunk_title}</h2>"]

        if current_chunk_found:
            html_parts.append("<ol>")
            for idx, (word, _def_html, _ctx) in enumerate(current_chunk_found, start=1):
                anchor_id = f"w{idx}"
                html_parts.append(f'<li><a href="#{anchor_id}">{idx} {word}</a></li>')
            html_parts.append("</ol>")

        for idx, (word, def_html, ctx_sent) in enumerate(current_chunk_found, start=1):
            anchor_id = f"w{idx}"
            simplified = simplify_html_for_defs(def_html)
            html_parts.append(f'<h3 id="{anchor_id}">{idx} {word}</h3>')
            if ctx_sent:
                html_parts.append(f'<p class="context">{ctx_sent}</p>')
            html_parts.append(f'<div class="dict-entry">{simplified}</div>')

        if current_chunk_missing:
            html_parts.append("<h3>Words without definition</h3><ul>")
            for w in current_chunk_missing:
                html_parts.append(f"<li>{w}</li>")
            html_parts.append("</ul>")

        page.content = "\n".join(html_parts)

        defs_book.add_item(page)
        spine.append(page)

        children_links = []
        for idx, (word, _def_html, _ctx) in enumerate(current_chunk_found, start=1):
            anchor_id = f"w{idx}"
            children_links.append(
                epub.Link(f"{file_name}#{anchor_id}", f"{idx} {word}", f"{file_name}_w{idx}")
            )
        toc.append((page, tuple(children_links)))

        chunk_index += 1
        current_chunk_found = []
        current_chunk_missing = []

    for word, def_html, ctx in all_entries:
        if def_html:
            current_chunk_found.append((word, def_html, ctx))
            if len(current_chunk_found) >= chunk_size:
                flush_chunk()
        else:
            current_chunk_missing.append(word)

    flush_chunk()

    defs_book.toc = tuple(toc)
    defs_book.spine = spine
    defs_book.add_item(epub.EpubNcx())
    defs_book.add_item(epub.EpubNav())

    epub.write_epub(output_path, defs_book)
    print(f"[6/8] Definitions-only EPUB saved to {output_path}")


def write_anki_tsv(all_entries: list[tuple[str, str, str]], output_path: str) -> None:
    print(f"[7/8] Writing Anki TSV ({len(all_entries)} total entries before filtering) ...")
    lines = []
    for word, html_def, ctx_sent in all_entries:
        if not html_def:
            continue
        if ctx_sent:
            full_html = f"<p><em>{ctx_sent}</em></p>{html_def}"
        else:
            full_html = html_def
        clean_html = full_html.replace("\t", " ").replace("\r", "").replace("\n", " ")
        clean_word = word.replace("\t", " ").replace("\r", "").replace("\n", " ")
        lines.append(f"{clean_word}\t{clean_html}")
    if lines:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[7/8] Anki TSV saved to {output_path} ({len(lines)} cards).")
    else:
        print("[7/8] No non-empty definitions to write to Anki TSV.")


def convert_epub_to_pdf(epub_path: str, pdf_path: str) -> None:
    print(f"[PDF] Converting {epub_path} -> {pdf_path} ...")
    exe = shutil.which("ebook-convert")
    if exe is None:
        print("[PDF] WARNING: 'ebook-convert' not found on PATH. Skipping PDF.")
        return
    try:
        subprocess.run([exe, epub_path, pdf_path], check=True)
        print(f"[PDF] Wrote {pdf_path}")
    except subprocess.CalledProcessError as e:
        print(f"[PDF] ERROR converting {epub_path} -> {pdf_path}: {e}")


def main():
    print("[0/8] Loading EPUB ...")
    book = epub.read_epub(EPUB_PATH)
    print(f"[0/8] EPUB loaded from {EPUB_PATH}")

    # maybe auto-build the list
    actual_wordlist_path = WORD_LIST_PATH
    if AUTO_BUILD_WORD_LIST:
        actual_wordlist_path = build_rare_word_list_from_epub(
            EPUB_PATH,
            AUTO_WORDLIST_OUTPUT,
            freq_threshold=AUTO_WORDLIST_FREQ_THRESHOLD,
        )

    toc_map = build_toc_title_map(book)
    words_to_replace = read_words_into_dictionary(actual_wordlist_path)

    print("[2/8] Loading dictionaries (via StarDictWrapper) ...")
    english_dict = StarDictWrapper()
    print("[2/8] Dictionaries loaded.")

    definition_cache: dict[str, str] = {}
    doc_items = [it for it in book.get_items() if it.get_type() == ebooklib.ITEM_DOCUMENT]
    total_docs = len(doc_items)
    print(f"[3/8] Processing {total_docs} document items ...")

    # now: (word, def_html, sentence)
    all_entries: list[tuple[str, str, str]] = []
    total_defs_collected = 0
    stop_processing = False

    for idx, item in enumerate(doc_items, start=1):
        if stop_processing:
            break

        body_content = item.get_body_content().decode("utf-8")
        matched_words, context_map = get_matched_words_with_context(
            body_content,
            words_to_replace,
            WORD_INCLUSION_MIN_LEN
        )
        section_title = discover_section_title(item.get_name(), body_content, toc_map)

        if matched_words:
            if TEST_MODE and total_defs_collected + len(matched_words) > TEST_MAX_DEFS:
                allowed = TEST_MAX_DEFS - total_defs_collected
                matched_words = matched_words[:allowed]

            print(f"    - [{idx}/{total_docs}] matched {len(matched_words)} words in {item.get_name()} ({section_title})")

            glossary_section = build_glossary_section(
                english_dict,
                matched_words,
                section_title,
                definition_cache,
                context_map,
            )

            if GENERATE_HIGHLIGHTED_EPUB:
                body_content_with_glossary = glossary_section + body_content
                body_content_with_glossary = highlight_content(body_content_with_glossary, set(matched_words))
                item.set_content(body_content_with_glossary.encode("utf-8"))

            if GENERATE_DEFS_EPUB or GENERATE_ANKI:
                for word in matched_words:
                    definition = definition_cache.get(word)
                    if definition is None:
                        definition = english_dict.get_def(word)
                        definition_cache[word] = definition
                    ctx_sent = context_map.get(word, "")
                    all_entries.append((word, definition, ctx_sent))
                    total_defs_collected += 1
                    if TEST_MODE and total_defs_collected >= TEST_MAX_DEFS:
                        stop_processing = True
                        break

            count_matches_delete_frequent(words_to_replace, matched_words)
        else:
            print(f"    - [{idx}/{total_docs}] no matches in {item.get_name()} ({section_title})")

    print(f"[4/8] Collected {len(all_entries)} (word, def, context) entries (including missing defs).")

    highlighted_written = False
    defs_written = False

    if GENERATE_HIGHLIGHTED_EPUB:
        print("[5/8] Rebuilding EPUB TOC/spine ...")
        for i, it in enumerate(doc_items, start=1):
            if not getattr(it, "uid", None):
                it.uid = f"doc_{i}"
        book.toc = tuple(doc_items)
        book.spine = ["nav"] + doc_items
        epub.write_epub(OUTPUT_EPUB_PATH, book)
        highlighted_written = True
        print(f"[5/8] Modified EPUB saved to {OUTPUT_EPUB_PATH}")
    else:
        print("[5/8] Skipping modified EPUB (GENERATE_HIGHLIGHTED_EPUB=False).")

    if GENERATE_DEFS_EPUB:
        if all_entries:
            write_definitions_epub_from_wordlist(all_entries, OUTPUT_DEFS_EPUB_PATH, chunk_size=50)
            defs_written = True
        else:
            print("[6/8] No entries; skipping defs EPUB.")
    else:
        print("[6/8] Skipping defs EPUB (GENERATE_DEFS_EPUB=False).")

    if GENERATE_ANKI:
        if all_entries:
            write_anki_tsv(all_entries, OUTPUT_ANKI_PATH)
        else:
            print("[7/8] No entries; skipping Anki TSV.")
    else:
        print("[7/8] Skipping Anki TSV (GENERATE_ANKI=False).")

    if CONVERT_EPUBS_TO_PDF:
        print("[PDF] Conversion option enabled.")
        if highlighted_written:
            convert_epub_to_pdf(OUTPUT_EPUB_PATH, OUTPUT_EPUB_PDF_PATH)
        if defs_written:
            convert_epub_to_pdf(OUTPUT_DEFS_EPUB_PATH, OUTPUT_DEFS_PDF_PATH)
    else:
        print("[PDF] Skipping EPUB->PDF conversion (CONVERT_EPUBS_TO_PDF=False).")

    print("[8/8] Done.")


if __name__ == "__main__":
    main()
