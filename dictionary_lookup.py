"""
Dictionary lookup helpers that combine structured StarDict parsers and
legacy fallbacks to produce HTML suitable for EPUB/Anki output.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Optional, Set

from endict import StarDictWrapper
from parse import ConciseOxfordParser, render_entry_html
from parse_oald import OxfordAdvancedLearnersParser
from bs4 import BeautifulSoup


class HTMLDefinitionLookup:
    """
    Tries multiple dictionary sources (currently OALD + Concise Oxford +
    any StarDict fallback) and returns nice HTML for each headword.
    """

    def __init__(self, fallback: Optional[StarDictWrapper] = None):
        self._fallback = fallback or StarDictWrapper()
        self._oald_parser: Optional[OxfordAdvancedLearnersParser | bool] = None
        self._concise_parser: Optional[ConciseOxfordParser | bool] = None
        self._cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API mirrors StarDictWrapper
    # ------------------------------------------------------------------
    def get_def(self, word: str) -> str:
        key = word.strip()
        if not key:
            return ""

        cache_key = key.lower()
        if cache_key in self._cache:
            return self._cache[cache_key]

        html = (
            self._lookup_with_cross_reference(key, self._lookup_oald)
            or self._lookup_with_cross_reference(key, self._lookup_concise)
            or self._lookup_with_cross_reference(key, self._lookup_fallback)
        )
        html = self._strip_unwanted_segments(html)
        self._cache[cache_key] = html
        return html

    def __getitem__(self, word: str) -> str:
        return self.get_def(word)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _lookup_oald(self, word: str) -> str:
        parser = self._get_oald_parser()
        if parser is None:
            return ""
        try:
            entry = parser.get_entry(word)
        except KeyError:
            return ""
        return render_entry_html(entry)

    def _lookup_concise(self, word: str) -> str:
        parser = self._get_concise_parser()
        if parser is None:
            return ""
        try:
            entry = parser.get_entry(word)
        except KeyError:
            return ""
        return render_entry_html(entry)

    def _lookup_fallback(self, word: str) -> str:
        return self._fallback.get_def(word)

    def _get_oald_parser(self) -> Optional[OxfordAdvancedLearnersParser]:
        if self._oald_parser is None:
            try:
                self._oald_parser = OxfordAdvancedLearnersParser()
            except FileNotFoundError as exc:
                print(f"[DictionaryLookup] OALD unavailable: {exc}")
                self._oald_parser = False
        return self._oald_parser or None

    def _get_concise_parser(self) -> Optional[ConciseOxfordParser]:
        if self._concise_parser is None:
            try:
                self._concise_parser = ConciseOxfordParser()
            except FileNotFoundError as exc:
                print(f"[DictionaryLookup] Concise Oxford unavailable: {exc}")
                self._concise_parser = False
        return self._concise_parser or None

    # ------------------------------------------------------------------
    def _lookup_with_cross_reference(
        self,
        word: str,
        provider: Optional[Callable[[str], str]],
        seen: Optional[Set[str]] = None,
    ) -> str:
        if provider is None:
            return ""
        key = word.strip()
        if not key:
            return ""
        seen = seen or set()
        lowered = key.lower()
        if lowered in seen:
            return ""
        seen.add(lowered)
        html = provider(key)
        if self._is_valid_definition(html):
            return html
        target = self._extract_cross_reference(html)
        if target and target.lower() not in seen:
            return self._lookup_with_cross_reference(target, provider, seen)
        return ""

    # Sanitization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_unwanted_segments(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")

        # Remove explicit audio references
        for tag in soup.find_all(["rref", "audio"]):
            tag.decompose()

        def _should_drop(text: str) -> bool:
            if not text:
                return False
            raw = text.strip()
            if not raw:
                return False
            normalized = raw.lower()
            letters_only = re.sub(r"[^a-z]", "", normalized)
            if letters_only in {"bre", "name", "nam e"}:
                return True
            if re.fullmatch(r"\[[^\]]+\]", raw):
                return True
            if raw.lower().endswith(".wav"):
                return True
            if "pronunciation" in normalized and len(raw.split()) <= 3:
                return True
            return False

        for text_node in list(soup.find_all(string=True)):
            if _should_drop(str(text_node)):
                parent = text_node.parent
                text_node.extract()
                # Drop parent if empty afterwards
                while parent and not parent.get_text(" ", strip=True):
                    next_parent = parent.parent
                    parent.decompose()
                    parent = next_parent

        return soup.decode()

    @staticmethod
    def _is_valid_definition(html: str) -> bool:
        if not html:
            return False
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        if not text:
            return False
        normalized = text.lower()
        stripped = normalized.strip()
        if stripped.startswith("see "):
            return False
        if stripped.startswith("see also "):
            return False
        if stripped.startswith("→"):
            return False
        if stripped.startswith("none. →"):
            return False
        return True

    @staticmethod
    def _extract_cross_reference(html: str) -> Optional[str]:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        if not text:
            return None
        arrow = re.search(r"→\s*([A-Za-z][A-Za-z'_-]*)", text)
        if arrow:
            return arrow.group(1)
        see = re.match(
            r"(?i)\bsee(?:\s+also)?\s+([A-Za-z][A-Za-z'_-]*)", text.strip()
        )
        if see:
            return see.group(1)
        return None
