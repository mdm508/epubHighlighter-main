"""
Parser and renderer helpers for the Oxford Advanced Learner's Dictionary
StarDict bundle.

Usage examples
--------------
    python parse_oald.py abandon
    python tests/render_oald_preview.py abandon
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

import pystardict
from bs4 import BeautifulSoup, NavigableString, Tag

from parse import (
    ParsedEntry,
    PartOfSpeechBlock,
    SectionEntry,
    Sense,
    render_entry_html,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
WS_RE = re.compile(r"\s+")
MARKER_RE = re.compile(r"^(\d+)\.?$")
SECTION_KEYWORDS: Dict[str, str] = {
    "word origin": "origin",
    "verb forms": "verb_forms",
    "thesaurus": "thesaurus",
    "extra examples": "extra_examples",
    "more about": "more_about",
}
SECTION_ALWAYS_COLLECT = {"thesaurus"}


def _normalize_ws(text: str) -> str:
    return WS_RE.sub(" ", text).strip()


def _tag_text(tag: Tag) -> str:
    return _normalize_ws(tag.get_text(" ", strip=True))


def _tag_html(tag: Tag) -> str:
    return tag.decode_contents().strip()


def _looks_like_section_label(text_lower: str, keyword: str) -> bool:
    return text_lower.rstrip(":") == keyword


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class OxfordAdvancedLearnersParser:
    def __init__(self, dict_root: Optional[Path] = None):
        self.base_path = self._resolve_base_path(dict_root)
        self._dict = pystardict.Dictionary(str(self.base_path))

    def get_entry(self, word: str) -> ParsedEntry:
        raw = self._dict.get(word, "")
        if not raw:
            raise KeyError(f"'{word}' is not present in {self.base_path}")
        return self._parse_entry(word, raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_base_path(self, dict_root: Optional[Path]) -> Path:
        if dict_root:
            dict_root = Path(dict_root)
            if dict_root.suffix == ".ifo":
                return dict_root.with_suffix("")
            return dict_root

        dict_dir = Path(__file__).resolve().parent / "dicts"
        matches = list(dict_dir.rglob("Oxford_Advanced_Learner_s_Dictionary.ifo"))
        if not matches:
            raise FileNotFoundError(
                "Unable to find Oxford_Advanced_Learner_s_Dictionary.ifo inside ./dicts."
            )
        return matches[0].with_suffix("")

    def _parse_entry(self, fallback_word: str, raw_html: str) -> ParsedEntry:
        soup = BeautifulSoup(f"<entry>{raw_html}</entry>", "html.parser")
        root = soup.entry
        if root is None:
            raise ValueError("Dictionary payload could not be parsed as HTML.")

        headword_tag = root.find("k")
        headword = headword_tag.get_text(strip=True) if headword_tag else fallback_word
        entry = ParsedEntry(headword=headword, raw_html=raw_html)

        headnote_fragments: list[str] = []
        before_first_sense = True
        current_block: Optional[PartOfSpeechBlock] = None
        last_sense: Optional[Sense] = None
        pending_section: Optional[str] = None
        active_section: Optional[str] = None

        for child in list(root.children):
            if isinstance(child, NavigableString):
                if before_first_sense and child.strip():
                    headnote_fragments.append(str(child))
                continue

            if not isinstance(child, Tag):
                continue

            if child.name == "k":
                continue

            if child.name == "c" and self._is_pos_label(child):
                if before_first_sense:
                    self._flush_headnote(entry, headnote_fragments)
                    before_first_sense = False
                active_section = None
                label = _normalize_ws(child.get_text(" ", strip=True))
                current_block = PartOfSpeechBlock(label=label, html=child.decode())
                entry.pos_blocks.append(current_block)
                last_sense = None
                continue

            if child.name == "blockquote":
                if before_first_sense:
                    self._flush_headnote(entry, headnote_fragments)
                    before_first_sense = False

                text_lower = _tag_text(child).lower()
                section_match = self._detect_section(text_lower)
                if section_match:
                    keyword, section_key = section_match
                    active_section = section_key
                    if _looks_like_section_label(text_lower, keyword):
                        pending_section = section_key
                        continue
                    self._append_section(entry, section_key, child)
                    pending_section = None
                    continue

                if pending_section:
                    self._append_section(entry, pending_section, child)
                    pending_section = None
                    continue

                if active_section and (
                    active_section in SECTION_ALWAYS_COLLECT
                    or not self._looks_like_sense(child)
                ):
                    self._append_section(entry, active_section, child)
                    continue

                if self._looks_like_sense(child):
                    active_section = None
                    if current_block is None:
                        current_block = PartOfSpeechBlock(label="entry", html="")
                        entry.pos_blocks.append(current_block)
                    sense = self._build_sense(child)
                    current_block.senses.append(sense)
                    last_sense = sense
                else:
                    if last_sense is not None:
                        self._append_to_sense(last_sense, child)
                    else:
                        self._append_section(entry, "notes", child)
                continue

            # Any other tag outside headnote becomes part of notes.
            if before_first_sense:
                headnote_fragments.append(child.decode())
            else:
                active_section = None
                self._append_section(entry, "notes", child)

        self._flush_headnote(entry, headnote_fragments)
        entry.pos_blocks = [block for block in entry.pos_blocks if block.senses]
        return entry

    def _flush_headnote(self, entry: ParsedEntry, fragments: list[str]) -> None:
        if not fragments:
            return
        html = "".join(fragments).strip()
        if not html:
            fragments.clear()
            return
        text = _normalize_ws(
            BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        )
        entry.sections.setdefault("headnote", []).append(
            SectionEntry(text=text, label=None, html=html)
        )
        fragments.clear()

    def _is_pos_label(self, tag: Tag) -> bool:
        return tag.get("c", "").lower() == "orange"

    def _detect_section(self, text_lower: str) -> Optional[tuple[str, str]]:
        for keyword, section in SECTION_KEYWORDS.items():
            if text_lower.startswith(keyword):
                return keyword, section
        return None

    def _looks_like_sense(self, block: Tag) -> bool:
        return block.find("b", string=MARKER_RE) is not None

    def _build_sense(self, block: Tag) -> Sense:
        clone = BeautifulSoup(str(block), "html.parser").blockquote
        marker = None
        marker_tag = clone.find("b", string=MARKER_RE)
        if marker_tag:
            marker_text = marker_tag.get_text(strip=True)
            marker_match = MARKER_RE.match(marker_text.rstrip("."))
            if marker_match:
                marker = marker_match.group(1)
            parent = marker_tag.parent
            marker_tag.decompose()
            if isinstance(parent, Tag) and not parent.get_text(strip=True):
                parent.decompose()

        text = _tag_text(clone)
        html = _tag_html(clone)
        return Sense(text=text, marker=marker, html=html)

    def _append_to_sense(self, sense: Sense, block: Tag) -> None:
        html = _tag_html(block)
        if not html:
            return
        extra = f'<div class="sense-note">{html}</div>'
        sense.html = (sense.html or "") + extra

    def _append_section(self, entry: ParsedEntry, key: str, block: Tag) -> None:
        html = _tag_html(block)
        if not html:
            return
        entry.sections.setdefault(key, []).append(
            SectionEntry(text=_tag_text(block), label=None, html=html)
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _iter_words(words: Iterable[str]) -> Iterable[str]:
    for word in words:
        cleaned = word.strip()
        if cleaned:
            yield cleaned


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Oxford Advanced Learner's Dictionary entries."
    )
    parser.add_argument(
        "word",
        nargs="+",
        help="Words to look up inside the Oxford Advanced Learner's Dictionary.",
    )
    parser.add_argument(
        "--dict-path",
        type=Path,
        help="Optional path to the .ifo file or dictionary base directory.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of pretty-printing.",
    )

    args = parser.parse_args()
    lookup = OxfordAdvancedLearnersParser(args.dict_path)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    for word in _iter_words(args.word):
        try:
            parsed = lookup.get_entry(word)
        except KeyError as exc:
            print(str(exc))
            continue
        payload = json.dumps(
            parsed.to_dict(),
            ensure_ascii=False,
            indent=None if args.compact else 2,
        )
        print(payload)


if __name__ == "__main__":
    main()
