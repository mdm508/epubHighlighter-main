"""
Helper utilities for inspecting the structure of the
Concise Oxford English Dictionary StarDict set.

Run `python parse.py abandon` to see the parsed representation for a word.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

import pystardict
from bs4 import BeautifulSoup, Tag


# Basic helpers ---------------------------------------------------------------
WS_RE = re.compile(r"\s+")
POS_BULLETS = "\u25a0\u25aa\u2022\u25b8"
SENSE_MARKER_RE = re.compile(r"^(\d+)\u300b\s*(.*)")
SECTION_HEADER_PATTERNS: Dict[str, re.Pattern[str]] = {
    "phrases": re.compile(r"^\s*phrases\s*$", re.I),
    "derivatives": re.compile(r"^\s*derivatives\s*$", re.I),
    "origin": re.compile(r"^\s*origin\s*$", re.I),
    "usage": re.compile(r"^\s*usage\s*$", re.I),
    "grammar": re.compile(r"^\s*grammar\s*$", re.I),
}
SECTION_DISPLAY_NAMES = {
    "headnote": "Headnote",
    "phrases": "Phrases",
    "derivatives": "Derivatives",
    "origin": "Origin",
    "usage": "Usage",
    "grammar": "Grammar",
    "verb_forms": "Verb forms",
    "thesaurus": "Thesaurus",
    "extra_examples": "Extra examples",
    "more_about": "More about",
    "notes": "Notes",
}


def _normalize_ws(text: str) -> str:
    return WS_RE.sub(" ", text).strip()


def _strip_pos_bullet(text: str) -> str:
    text = text.lstrip()
    if text and text[0] in POS_BULLETS:
        text = text[1:]
    return text.strip()


def _strip_leading_parentheticals(text: str) -> str:
    remaining = text.lstrip()
    while remaining.startswith("("):
        depth = 0
        for idx, char in enumerate(remaining):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    remaining = remaining[idx + 1 :].lstrip()
                    break
        else:
            # Unbalanced parentheses, stop trimming.
            return remaining.strip()
    return remaining.strip()


def _tidy_punctuation_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:)\]])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    return text.strip()


def _tag_to_html(tag: Tag) -> str:
    return tag.decode_contents().strip()


def _tag_to_text(tag: Tag) -> str:
    return _normalize_ws(tag.get_text(" ", strip=True))


# Data containers -------------------------------------------------------------
@dataclass
class Sense:
    text: str
    marker: Optional[str] = None
    html: Optional[str] = None


@dataclass
class PartOfSpeechBlock:
    label: str
    html: str
    senses: list[Sense] = field(default_factory=list)


@dataclass
class SectionEntry:
    text: str
    label: Optional[str] = None
    html: Optional[str] = None


@dataclass
class ParsedEntry:
    headword: str
    pos_blocks: list[PartOfSpeechBlock] = field(default_factory=list)
    sections: Dict[str, list[SectionEntry]] = field(default_factory=dict)
    raw_html: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


# Parser ----------------------------------------------------------------------
class ConciseOxfordParser:
    """
    Parses Concise Oxford entries into structured data.
    """

    def __init__(self, dict_root: Optional[Path] = None):
        self.base_path = self._resolve_base_path(dict_root)
        self._dict = pystardict.Dictionary(str(self.base_path))

    def get_entry(self, word: str) -> ParsedEntry:
        raw = self._dict.get(word, "")
        if not raw:
            raise KeyError(f"'{word}' is not present in {self.base_path}")
        return self._parse_html(word, raw)

    # Internal helpers --------------------------------------------------------
    def _resolve_base_path(self, user_supplied: Optional[Path]) -> Path:
        if user_supplied:
            supplied = Path(user_supplied)
            if supplied.suffix == ".ifo":
                supplied = supplied.with_suffix("")
            return supplied

        dict_dir = Path(__file__).resolve().parent / "dicts"
        matches = list(
            dict_dir.rglob("Concise_Oxford_English_Dictionary.ifo")
        )
        if not matches:
            raise FileNotFoundError(
                "Unable to find Concise_Oxford_English_Dictionary.ifo inside ./dicts."
            )
        return matches[0].with_suffix("")

    def _parse_html(self, fallback_word: str, raw_html: str) -> ParsedEntry:
        soup = BeautifulSoup(f"<entry>{raw_html}</entry>", "html.parser")
        root = soup.entry
        if root is None:
            raise ValueError("Dictionary payload could not be parsed as HTML.")

        headword_tag = root.find("k")
        headword = headword_tag.get_text(strip=True) if headword_tag else fallback_word
        entry = ParsedEntry(headword=headword, raw_html=raw_html)

        current_section = "senses"
        current_block: Optional[PartOfSpeechBlock] = None

        for block in root.find_all("blockquote", recursive=False):
            if not _tag_to_text(block):
                continue

            section = self._match_section_header(block)
            if section:
                current_section = section
                entry.sections.setdefault(section, [])
                continue

            if current_section == "senses" and self._looks_like_pos_header(block):
                current_block = PartOfSpeechBlock(
                    label=self._extract_pos_label(block), html=_tag_to_html(block)
                )
                entry.pos_blocks.append(current_block)
                current_section = "senses"
                inline = self._build_inline_sense(block)
                if inline:
                    current_block.senses.append(inline)
                continue

            if current_section != "senses":
                entry.sections[current_section].append(
                    self._build_section_entry(block)
                )
                continue

            sense = self._build_sense(block)
            if sense:
                if current_block is None:
                    current_block = PartOfSpeechBlock(label="general", html="")
                    entry.pos_blocks.append(current_block)
                current_block.senses.append(sense)
                continue

            # Fallback: treat as miscellaneous note.
            entry.sections.setdefault("notes", []).append(
                self._build_section_entry(block)
            )

        return entry

    def _match_section_header(self, block: Tag) -> Optional[str]:
        text = _tag_to_text(block).lower()
        for name, pattern in SECTION_HEADER_PATTERNS.items():
            if pattern.match(text):
                return name
        return None

    def _looks_like_pos_header(self, block: Tag) -> bool:
        text = _strip_pos_bullet(_tag_to_text(block))
        has_pos_tag = block.find("c", attrs={"c": re.compile(r"^green$", re.I)}) is not None
        return bool(text) and has_pos_tag

    def _extract_pos_label(self, block: Tag) -> str:
        text = _strip_pos_bullet(_tag_to_text(block))
        inline_text = self._inline_sense_text(block)
        if inline_text and text.endswith(inline_text):
            text = text[: -len(inline_text)].rstrip()
        return _tidy_punctuation_spacing(text)

    def _build_sense(self, block: Tag) -> Optional[Sense]:
        inner = block.find("blockquote")
        target = inner if inner else block
        text = _tag_to_text(target)

        if not text:
            return None

        marker = None
        match = SENSE_MARKER_RE.match(text)
        html_content = _tag_to_html(target)
        if match:
            marker = match.group(1)
            text = match.group(2).strip()
            html_content = re.sub(
                rf"^{re.escape(marker)}\u300b\s*", "", html_content, flags=re.UNICODE
            )

        return Sense(
            text=_tidy_punctuation_spacing(text),
            marker=marker,
            html=html_content,
        )

    def _inline_sense_text(self, block: Tag) -> str:
        # Work on a copy to avoid mutating the original soup tree.
        clone = BeautifulSoup(str(block), "html.parser").blockquote
        if clone is None:
            return ""

        c_tag = clone.find("c", attrs={"c": re.compile(r"^green$", re.I)})
        if c_tag:
            c_tag.extract()

        text = _strip_pos_bullet(_tag_to_text(clone))
        text = _strip_leading_parentheticals(text)
        return _tidy_punctuation_spacing(text)

    def _build_inline_sense(self, block: Tag) -> Optional[Sense]:
        text = self._inline_sense_text(block)
        if not text:
            return None
        return Sense(text=text, marker=None, html=text)

    def _build_section_entry(self, block: Tag) -> SectionEntry:
        clone = BeautifulSoup(str(block), "html.parser").blockquote
        if clone is None:
            return SectionEntry(text=_tag_to_text(block), html=_tag_to_html(block))

        label = None
        bold = clone.find("b")
        if bold:
            parent = bold.parent
            label = _tag_to_text(bold)
            bold.extract()
            if isinstance(parent, Tag) and not parent.get_text(strip=True):
                parent.decompose()

        return SectionEntry(
            text=_tidy_punctuation_spacing(_tag_to_text(clone)),
            label=label,
            html=_tag_to_html(clone),
        )



# HTML rendering helpers ------------------------------------------------------
def _entry_mapping(entry: ParsedEntry | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(entry, ParsedEntry):
        return entry.to_dict()
    if isinstance(entry, Mapping):
        return entry
    raise TypeError("entry must be a ParsedEntry or dict-like object.")


def _get_display_name(section_key: str) -> str:
    return SECTION_DISPLAY_NAMES.get(section_key, section_key.replace("_", " ").title())


def _section_class_name(section_key: str) -> str:
    safe = re.sub(r"[^0-9a-zA-Z_-]+", "-", section_key)
    safe = safe.strip("-").lower()
    return safe or "section"


def _html_or_text(html_value: Optional[str], text_value: str) -> str:
    if html_value:
        return html_value
    return escape(text_value)


def render_entry_html(
    entry: ParsedEntry | Mapping[str, object],
    heading_level: int = 2,
) -> str:
    """
    Convert a parsed dictionary entry into standalone HTML that works nicely
    inside Anki cards or other HTML surfaces.

    Example
    -------
    >>> parser = ConciseOxfordParser()
    >>> entry = parser.get_entry("abandon")
    >>> html = render_entry_html(entry)
    """

    entry_dict = _entry_mapping(entry)
    heading_level = min(6, max(1, heading_level))
    headword = escape(str(entry_dict.get("headword", "")).strip() or "Entry")
    h_tag = f"h{heading_level}"
    subseq_tag = f"h{min(6, heading_level + 1)}"

    parts: list[str] = [
        '<article class="concise-oxford-entry">',
        f'<{h_tag} class="entry-headword">{headword}</{h_tag}>',
    ]

    sections = dict(entry_dict.get("sections") or {})
    headnote_entries = sections.pop("headnote", None)

    def _append_section_block(section_key: str, entries: list[Mapping[str, object]]):
        if not entries:
            return
        section_name = escape(_get_display_name(section_key))
        parts.append(
            f'<section class="entry-section entry-section-{_section_class_name(str(section_key))}">'
        )
        parts.append(f"<{subseq_tag}>{section_name}</{subseq_tag}>")
        parts.append("<ul>")
        for item in entries:
            label_raw = item.get("label")
            label = str(label_raw).strip() if label_raw is not None else ""
            if label and label.lower().strip(".:") == "none":
                label = ""
            label_html = (
                f'<strong class="section-label">{escape(label)}</strong> ' if label else ""
            )
            body_html = _html_or_text(item.get("html"), item.get("text", ""))
            parts.append(f"<li>{label_html}{body_html}</li>")
        parts.append("</ul></section>")

    if headnote_entries:
        _append_section_block("headnote", headnote_entries)

    for block in entry_dict.get("pos_blocks", []) or []:
        label = escape(str(block.get("label", "")).strip())
        parts.append('<section class="pos-block">')
        if label:
            parts.append(f'<{subseq_tag} class="pos-label">{label}</{subseq_tag}>')

        senses = block.get("senses") or []
        if senses:
            parts.append('<ol class="sense-list">')
            for sense in senses:
                text_html = _html_or_text(sense.get("html"), sense.get("text", ""))
                marker = str(sense.get("marker", "")).strip()
                marker_html = (
                    f'<span class="sense-marker">{escape(marker)}.</span> '
                    if marker
                    else ""
                )
                parts.append(f"<li>{marker_html}{text_html}</li>")
            parts.append("</ol>")
        elif block.get("html"):
            parts.append(f"<p>{block['html']}</p>")

        parts.append("</section>")

    for section_key, entries in sections.items():
        _append_section_block(section_key, entries)

    parts.append("</article>")
    return "\n".join(parts)


# CLI -------------------------------------------------------------------------
def _iter_words(words: Iterable[str]) -> Iterable[str]:
    for word in words:
        stripped = word.strip()
        if stripped:
            yield stripped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Concise Oxford dictionary entries."
    )
    parser.add_argument(
        "word",
        nargs="+",
        help="Words to look up inside the Concise Oxford dictionary.",
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
    lookup = ConciseOxfordParser(args.dict_path)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    indent = None if args.compact else 2

    for word in _iter_words(args.word):
        try:
            parsed = lookup.get_entry(word)
        except KeyError as exc:
            print(str(exc))
            continue
        payload = json.dumps(parsed.to_dict(), ensure_ascii=False, indent=indent)
        print(payload)


if __name__ == "__main__":
    main()
